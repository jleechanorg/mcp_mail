"""Test that export_salt parameter enables pseudonymization in create_snapshot_context."""

import os
import sqlite3
from pathlib import Path

import pytest

from mcp_agent_mail.share import create_snapshot_context


@pytest.fixture
def test_database(tmp_path: Path) -> Path:
    """Create a minimal test database with agents."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # Create minimal schema
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
                created_ts TEXT,
                ack_required INTEGER DEFAULT 0,
                attachments TEXT
            );
            CREATE TABLE message_recipients (
                message_id INTEGER,
                agent_id INTEGER,
                kind TEXT,
                read_ts TEXT,
                ack_ts TEXT
            );
            CREATE TABLE file_reservations (id INTEGER PRIMARY KEY, project_id INTEGER);
            CREATE TABLE agent_links (id INTEGER PRIMARY KEY, a_project_id INTEGER, b_project_id INTEGER);
            """
        )

        # Insert test data
        conn.execute("INSERT INTO projects (id, slug, human_key) VALUES (1, 'test', 'Test Project')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (1, 1, 'Alice')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (2, 1, 'Bob')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (3, 1, NULL)")  # NULL name for Bug 2

        conn.commit()
    finally:
        conn.close()

    return db_path


def test_pseudonymization_with_export_salt(tmp_path: Path, test_database: Path):
    """export_salt enables deterministic pseudonymization."""
    snapshot_path = tmp_path / "snapshot.db"
    salt = os.urandom(32)

    context = create_snapshot_context(
        source_database=test_database,
        snapshot_path=snapshot_path,
        project_filters=[],
        scrub_preset="standard",
        export_salt=salt,
    )

    # Should have pseudonymized agents when salt is provided
    assert context.scrub_summary.agents_pseudonymized > 0, (
        "Expected agents to be pseudonymized when export_salt is provided"
    )
    assert context.scrub_summary.agents_total == 3, f"Expected 3 total agents, got {context.scrub_summary.agents_total}"

    # Verify the scrub summary records pseudonymization without leaking the salt
    assert context.scrub_summary.pseudonymization_enabled is True


def test_no_pseudonymization_without_export_salt(tmp_path: Path, test_database: Path):
    """Test that without export_salt, pseudonymization is skipped."""
    snapshot_path = tmp_path / "snapshot.db"

    # Call without export_salt
    context = create_snapshot_context(
        source_database=test_database,
        snapshot_path=snapshot_path,
        project_filters=[],
        scrub_preset="standard",
        # No export_salt parameter
    )

    # Should NOT have pseudonymized agents
    assert context.scrub_summary.agents_pseudonymized == 0, (
        "Expected no pseudonymization when export_salt is not provided"
    )


def test_pseudonymization_handles_null_names(tmp_path: Path, test_database: Path):
    """NULL agent names are skipped without crashing."""
    snapshot_path = tmp_path / "snapshot.db"
    salt = os.urandom(32)

    # THIS WILL FAIL if NULL check is missing
    context = create_snapshot_context(
        source_database=test_database,
        snapshot_path=snapshot_path,
        project_filters=[],
        scrub_preset="standard",
        export_salt=salt,
    )

    # Should have pseudonymized 2 agents (skipping the NULL one)
    assert context.scrub_summary.agents_pseudonymized == 2, (
        f"Expected 2 agents pseudonymized (skipping NULL), got {context.scrub_summary.agents_pseudonymized}"
    )
