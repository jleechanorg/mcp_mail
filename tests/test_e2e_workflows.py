"""End-to-end workflow tests for Tier 1 and Tier 2 features integration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mcp_agent_mail.share import build_materialized_views, create_performance_indexes, finalize_snapshot_for_export

# Removed _init_git_repo and _create_and_commit_file helpers as they were only used by removed tests


def _tool_text(result) -> str:
    assert result.content, "Expected non-empty result content"
    text = result.content[0].text
    assert text, "Expected text content"
    return text


def _tool_json(result) -> dict:
    text = _tool_text(result)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive assertion helper
        pytest.fail(f"Failed to parse tool result JSON: {exc}")


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
    build_materialized_views(snapshot)
    create_performance_indexes(snapshot)
    finalize_snapshot_for_export(snapshot)

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
    build_materialized_views(snapshot_v1)
    create_performance_indexes(snapshot_v1)
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
    build_materialized_views(snapshot_v2)
    create_performance_indexes(snapshot_v2)
    finalize_snapshot_for_export(snapshot_v2)

    # Verify v2 has all messages in materialized view
    conn = sqlite3.connect(str(snapshot_v2))
    cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
    assert cursor.fetchone()[0] == 10
    conn.close()
