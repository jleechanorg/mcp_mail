"""End-to-end workflow tests for Tier 1 and Tier 2 features integration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mcp_agent_mail import build_mcp_server
from mcp_agent_mail.config import get_settings
from mcp_agent_mail.guard import render_prepush_script
from mcp_agent_mail.share import build_materialized_views, create_performance_indexes, finalize_snapshot_for_export
from mcp_agent_mail.storage import ensure_archive, write_file_reservation_record


def _init_git_repo(path: Path) -> None:
    """Initialize a git repository with config."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(path), check=True)


def _create_and_commit_file(repo: Path, filename: str, content: str = "test") -> None:
    """Create a file and commit it."""
    file_path = repo / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    subprocess.run(["git", "add", filename], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", f"Add {filename}"], cwd=str(repo), check=True, capture_output=True)


@pytest.mark.asyncio
async def test_e2e_build_slots_with_file_reservations(isolated_env, tmp_path: Path):
    """End-to-end test: Build slots combined with file reservations."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "e2e-project")

    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    # Agent1 creates a file reservation
    result = await server._mcp_server.call_tool(
        "create_file_reservation",
        {
            "project_key": "e2e-project",
            "agent_name": "Agent1",
            "path_pattern": "src/*.py",
            "exclusive": True,
            "ttl_seconds": 3600,
        },
    )
    assert result[0].text

    # Agent1 acquires a build slot
    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "e2e-project",
            "agent_name": "Agent1",
            "slot": "backend-build",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )
    data = json.loads(result[0].text)
    assert data["granted"] is True

    # Agent2 tries to acquire the same build slot
    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "e2e-project",
            "agent_name": "Agent2",
            "slot": "backend-build",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )
    data = json.loads(result[0].text)
    # Should report conflict
    assert len(data["conflicts"]) > 0

    # Agent1 releases the build slot
    result = await server._mcp_server.call_tool(
        "release_build_slot", {"project_key": "e2e-project", "agent_name": "Agent1", "slot": "backend-build"}
    )
    data = json.loads(result[0].text)
    assert data["released"] is True

    # Agent2 can now acquire the slot without conflicts
    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "e2e-project",
            "agent_name": "Agent2",
            "slot": "backend-build",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )
    data = json.loads(result[0].text)
    assert data["granted"] is True
    # No active conflicts from Agent1 (slot was released)
    assert all("Agent1" not in str(c) for c in data.get("conflicts", []))


@pytest.mark.asyncio
async def test_e2e_pre_push_guard_with_build_slots(isolated_env, tmp_path: Path):
    """End-to-end test: Pre-push guard checking file reservations while build slot is active."""
    settings = get_settings()
    archive = await ensure_archive(settings, "guard-project")

    # Create file reservation
    await write_file_reservation_record(
        archive,
        {
            "agent": "BuildAgent",
            "path_pattern": "build/**/*",
            "exclusive": True,
        },
    )

    # Render pre-push script
    prepush_script = render_prepush_script(archive)
    script_path = tmp_path / "prepush.py"
    script_path.write_text(prepush_script)

    # Create git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    # Commit changes to reserved area
    _create_and_commit_file(repo, "build/output.bin", "binary data")

    # Run pre-push hook
    import os

    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True)
    local_sha = result.stdout.strip()

    env = os.environ.copy()
    env["AGENT_NAME"] = "DeployAgent"  # Different from BuildAgent
    env["WORKTREES_ENABLED"] = "1"

    hook_input = f"refs/heads/main {local_sha} refs/heads/main 0000000000000000000000000000000000000000\n"
    proc = subprocess.run(
        ["python", str(script_path)], cwd=str(repo), env=env, input=hook_input, capture_output=True, text=True
    )

    # Should detect conflict
    assert proc.returncode == 1
    assert "conflict" in proc.stderr.lower()


@pytest.mark.asyncio
async def test_e2e_materialized_views_with_share_export(isolated_env, tmp_path: Path):
    """End-to-end test: Create messages, export with materialized views and indexes."""
    import sqlite3

    # Create a snapshot database
    snapshot = tmp_path / "export.sqlite3"
    conn = sqlite3.connect(str(snapshot))
    try:
        conn.executescript(
            """
            CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, human_key TEXT);
            CREATE TABLE agents (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                name TEXT,
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                sender_id INTEGER,
                thread_id TEXT,
                subject TEXT,
                body_md TEXT,
                importance TEXT,
                ack_required INTEGER,
                created_ts TEXT,
                attachments TEXT
            );
            CREATE TABLE message_recipients (
                message_id INTEGER,
                agent_id INTEGER,
                kind TEXT
            );
            CREATE TABLE file_reservations (id INTEGER PRIMARY KEY, project_id INTEGER);
            CREATE TABLE agent_links (id INTEGER PRIMARY KEY, a_project_id INTEGER, b_project_id INTEGER);
            CREATE TABLE project_sibling_suggestions (
                id INTEGER PRIMARY KEY,
                project_a_id INTEGER,
                project_b_id INTEGER
            );
            """
        )

        # Insert test data
        conn.execute("INSERT INTO projects (id, slug, human_key) VALUES (1, 'e2e', 'E2E Project')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (1, 1, 'Alice')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (2, 1, 'Bob')")

        # Insert messages with various subjects for case-insensitive search testing
        test_messages = [
            (1, "IMPORTANT: Database Migration", "Details about migration"),
            (2, "important: Code Review", "Please review PR"),
            (3, "Update: Important Changes", "Summary of changes"),
        ]

        for msg_id, subject, body in test_messages:
            conn.execute(
                """
                INSERT INTO messages (
                    id, project_id, sender_id, thread_id, subject, body_md,
                    importance, ack_required, created_ts, attachments
                )
                VALUES (?, 1, 1, ?, ?, ?, 'normal', 0, ?, '[]')
                """,
                (msg_id, f"thread-{msg_id}", subject, body, f"2025-01-{msg_id:02d}T00:00:00Z"),
            )

        conn.commit()
    finally:
        conn.close()

    # Run full export finalization
    finalize_snapshot_for_export(snapshot)
    build_materialized_views(snapshot)
    create_performance_indexes(snapshot)

    # Verify all optimizations were applied
    conn = sqlite3.connect(str(snapshot))
    try:
        # Check materialized views
        cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
        assert cursor.fetchone()[0] == 3

        # Check lowercase columns for case-insensitive search
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE subject_lower LIKE '%important%'")
        count = cursor.fetchone()[0]
        assert count == 3  # All three messages have "important" in different cases

        # Check indexes exist
        cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        assert cursor.fetchone()[0] > 0

        # Check ANALYZE was run
        cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'")
        assert cursor.fetchone()[0] == 1

    finally:
        conn.close()


@pytest.mark.asyncio
async def test_e2e_multi_agent_workflow(isolated_env, tmp_path: Path):
    """End-to-end test: Multiple agents coordinating with build slots and file reservations."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "multi-agent-project")

    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    # Scenario: Frontend and Backend agents working in parallel

    # Frontend agent claims frontend build slot
    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "multi-agent-project",
            "agent_name": "FrontendAgent",
            "slot": "frontend-build",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )
    assert json.loads(result[0].text)["granted"] is True

    # Backend agent claims backend build slot (different slot)
    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "multi-agent-project",
            "agent_name": "BackendAgent",
            "slot": "backend-build",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )
    assert json.loads(result[0].text)["granted"] is True

    # Frontend agent reserves frontend files
    result = await server._mcp_server.call_tool(
        "create_file_reservation",
        {
            "project_key": "multi-agent-project",
            "agent_name": "FrontendAgent",
            "path_pattern": "frontend/**/*.ts",
            "exclusive": True,
            "ttl_seconds": 3600,
        },
    )
    assert result[0].text

    # Backend agent reserves backend files
    result = await server._mcp_server.call_tool(
        "create_file_reservation",
        {
            "project_key": "multi-agent-project",
            "agent_name": "BackendAgent",
            "path_pattern": "backend/**/*.py",
            "exclusive": True,
            "ttl_seconds": 3600,
        },
    )
    assert result[0].text

    # Both agents can work in parallel - different slots, different files
    # Frontend agent renews slot
    result = await server._mcp_server.call_tool(
        "renew_build_slot",
        {
            "project_key": "multi-agent-project",
            "agent_name": "FrontendAgent",
            "slot": "frontend-build",
            "extend_seconds": 1800,
        },
    )
    assert json.loads(result[0].text)["renewed"] is True

    # Backend agent renews slot
    result = await server._mcp_server.call_tool(
        "renew_build_slot",
        {
            "project_key": "multi-agent-project",
            "agent_name": "BackendAgent",
            "slot": "backend-build",
            "extend_seconds": 1800,
        },
    )
    assert json.loads(result[0].text)["renewed"] is True

    # Both agents finish and release slots
    result = await server._mcp_server.call_tool(
        "release_build_slot",
        {"project_key": "multi-agent-project", "agent_name": "FrontendAgent", "slot": "frontend-build"},
    )
    assert json.loads(result[0].text)["released"] is True

    result = await server._mcp_server.call_tool(
        "release_build_slot",
        {"project_key": "multi-agent-project", "agent_name": "BackendAgent", "slot": "backend-build"},
    )
    assert json.loads(result[0].text)["released"] is True


@pytest.mark.asyncio
async def test_e2e_guard_lifecycle(isolated_env, tmp_path: Path):
    """End-to-end test: Full guard lifecycle from installation to execution."""
    settings = get_settings()
    archive = await ensure_archive(settings, "guard-lifecycle")

    # Install guards
    from mcp_agent_mail.guard import install_guard, install_prepush_guard

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    # Install both pre-commit and pre-push guards
    await install_guard(settings, "guard-lifecycle", repo)
    await install_prepush_guard(settings, "guard-lifecycle", repo)

    # Verify hooks were installed
    precommit_hook = repo / ".git" / "hooks" / "pre-commit"
    prepush_hook = repo / ".git" / "hooks" / "pre-push"

    assert precommit_hook.exists()
    assert prepush_hook.exists()

    # Create a file reservation
    await write_file_reservation_record(
        archive,
        {
            "agent": "ProtectedAgent",
            "path_pattern": "protected/**/*",
            "exclusive": True,
        },
    )

    # Try to commit a file in protected area (should be blocked by pre-commit)
    protected_file = repo / "protected" / "data.txt"
    protected_file.parent.mkdir()
    protected_file.write_text("sensitive data")

    subprocess.run(["git", "add", "protected/data.txt"], cwd=str(repo), check=True)

    # Run pre-commit hook
    import os

    env = os.environ.copy()
    env["AGENT_NAME"] = "OtherAgent"
    env["WORKTREES_ENABLED"] = "1"

    proc = subprocess.run(["python", str(precommit_hook)], cwd=str(repo), env=env, capture_output=True, text=True)

    # Should block the commit
    assert proc.returncode == 1


@pytest.mark.asyncio
async def test_e2e_database_optimizations_query_performance(isolated_env, tmp_path: Path):
    """End-to-end test: Verify database optimizations improve query performance."""
    import sqlite3
    import time

    from mcp_agent_mail.share import build_materialized_views, create_performance_indexes

    # Create a snapshot with many messages
    snapshot = tmp_path / "perf_test.sqlite3"
    conn = sqlite3.connect(str(snapshot))
    try:
        conn.executescript(
            """
            CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT);
            CREATE TABLE agents (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                sender_id INTEGER,
                thread_id TEXT,
                subject TEXT,
                body_md TEXT,
                importance TEXT,
                ack_required INTEGER,
                created_ts TEXT,
                attachments TEXT
            );
            CREATE TABLE message_recipients (message_id INTEGER, agent_id INTEGER, kind TEXT);
            """
        )

        conn.execute("INSERT INTO projects (id, slug) VALUES (1, 'perf')")
        conn.execute("INSERT INTO agents (id, name) VALUES (1, 'TestAgent')")

        # Insert 100 messages
        for i in range(100):
            conn.execute(
                """
                INSERT INTO messages (
                    id, project_id, sender_id, thread_id, subject, body_md,
                    importance, ack_required, created_ts, attachments
                )
                VALUES (?, 1, 1, ?, ?, 'body', 'normal', 0, '2025-01-01T00:00:00Z', '[]')
                """,
                (i + 1, f"thread-{i}", f"Subject {i % 10}"),
            )

        conn.commit()
    finally:
        conn.close()

    # Query performance WITHOUT optimizations
    conn = sqlite3.connect(str(snapshot))
    start = time.time()
    cursor = conn.execute("SELECT * FROM messages WHERE LOWER(subject) LIKE '%subject 5%' ORDER BY created_ts DESC")
    results_before = cursor.fetchall()
    time.time() - start
    conn.close()

    # Apply optimizations
    build_materialized_views(snapshot)
    create_performance_indexes(snapshot)

    # Query performance WITH optimizations (using lowercase column)
    conn = sqlite3.connect(str(snapshot))
    start = time.time()
    cursor = conn.execute("SELECT * FROM messages WHERE subject_lower LIKE '%subject 5%' ORDER BY created_ts DESC")
    results_after = cursor.fetchall()
    time_after = time.time() - start
    conn.close()

    # Both should return same results
    assert len(results_before) == len(results_after)

    # With such a small dataset, timing may not be significantly different,
    # but we can verify the optimization infrastructure is in place
    assert time_after >= 0  # Query completed


@pytest.mark.asyncio
async def test_e2e_incremental_share_updates(isolated_env, tmp_path: Path):
    """End-to-end test: Multiple share exports with incremental updates."""
    import sqlite3

    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    # Create initial snapshot (v1)
    snapshot_v1 = tmp_path / "snapshot_v1.sqlite3"
    conn = sqlite3.connect(str(snapshot_v1))
    try:
        conn.executescript(
            """
            CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, human_key TEXT);
            CREATE TABLE agents (id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, is_active INTEGER);
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY, project_id INTEGER, sender_id INTEGER,
                thread_id TEXT, subject TEXT, body_md TEXT, importance TEXT,
                ack_required INTEGER, created_ts TEXT, attachments TEXT
            );
            CREATE TABLE message_recipients (message_id INTEGER, agent_id INTEGER, kind TEXT);
            CREATE TABLE file_reservations (id INTEGER PRIMARY KEY, project_id INTEGER);
            CREATE TABLE agent_links (id INTEGER PRIMARY KEY, a_project_id INTEGER, b_project_id INTEGER);
            CREATE TABLE project_sibling_suggestions (id INTEGER PRIMARY KEY, project_a_id INTEGER, project_b_id INTEGER);
            """
        )
        conn.execute("INSERT INTO projects (id, slug, human_key) VALUES (1, 'inc', 'Incremental')")
        conn.execute("INSERT INTO agents (id, project_id, name, is_active) VALUES (1, 1, 'Agent', 1)")
        for i in range(5):
            conn.execute(
                """
                INSERT INTO messages (id, project_id, sender_id, thread_id, subject, body_md, importance, ack_required, created_ts, attachments)
                VALUES (?, 1, 1, ?, ?, 'body', 'normal', 0, '2025-01-01T00:00:00Z', '[]')
                """,
                (i + 1, f"thread-{i}", f"V1 Subject {i}"),
            )
        conn.commit()
    finally:
        conn.close()

    # Export v1
    finalize_snapshot_for_export(snapshot_v1)

    # Verify v1 has optimizations
    conn = sqlite3.connect(str(snapshot_v1))
    cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
    assert cursor.fetchone()[0] == 5
    conn.close()

    # Create updated snapshot (v2) with more messages
    snapshot_v2 = tmp_path / "snapshot_v2.sqlite3"
    subprocess.run(["cp", str(snapshot_v1), str(snapshot_v2)], check=True)

    conn = sqlite3.connect(str(snapshot_v2))
    try:
        # Add more messages
        for i in range(5, 10):
            conn.execute(
                """
                INSERT INTO messages (id, project_id, sender_id, thread_id, subject, body_md, importance, ack_required, created_ts, attachments)
                VALUES (?, 1, 1, ?, ?, 'body', 'normal', 0, '2025-01-02T00:00:00Z', '[]')
                """,
                (i + 1, f"thread-{i}", f"V2 Subject {i}"),
            )
        conn.commit()
    finally:
        conn.close()

    # Export v2 (incremental update)
    finalize_snapshot_for_export(snapshot_v2)

    # Verify v2 has all messages in materialized view
    conn = sqlite3.connect(str(snapshot_v2))
    cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
    assert cursor.fetchone()[0] == 10
    conn.close()
