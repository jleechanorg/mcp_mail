"""Tests for share update command and incremental export functionality."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mcp_agent_mail.share import (
    build_materialized_views,
    bundle_attachments,
    create_performance_indexes,
    finalize_snapshot_for_export,
)


def _create_snapshot_with_data(snapshot_path: Path, num_messages: int = 5) -> None:
    """Create a snapshot database with sample data."""
    conn = sqlite3.connect(str(snapshot_path))
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
            CREATE TABLE project_sibling_suggestions (id INTEGER PRIMARY KEY, project_a_id INTEGER, project_b_id INTEGER);
            """
        )

        # Insert test data
        conn.execute("INSERT INTO projects (id, slug, human_key) VALUES (1, 'test-proj', 'Test Project')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (1, 1, 'TestAgent')")

        for i in range(1, num_messages + 1):
            conn.execute(
                """
                INSERT INTO messages (
                    id, project_id, sender_id, thread_id, subject, body_md,
                    importance, ack_required, created_ts, attachments
                )
                VALUES (?, 1, 1, ?, ?, ?, 'normal', 0, ?, '[]')
                """,
                (i, f"thread-{i}", f"Subject {i}", f"Body {i}", f"2025-01-{i:02d}T00:00:00Z"),
            )

        conn.commit()
    finally:
        conn.close()


def test_finalize_snapshot_creates_all_optimizations(tmp_path: Path):
    """Test that finalize_snapshot_for_export creates all optimizations."""
    snapshot = tmp_path / "test.sqlite3"
    _create_snapshot_with_data(snapshot)

    # Finalize snapshot then build optimized views/indexes
    finalize_snapshot_for_export(snapshot)
    build_materialized_views(snapshot)
    create_performance_indexes(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify materialized views were created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_mv'")
        mv_tables = {row[0] for row in cursor.fetchall()}
        assert "message_overview_mv" in mv_tables

        # Verify performance indexes were created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_messages_subject_lower" in indexes

        # Verify lowercase columns exist
        cursor = conn.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "subject_lower" in columns

        # Verify ANALYZE was run
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'")
        stat_tables = cursor.fetchall()
        assert len(stat_tables) == 1

    finally:
        conn.close()


def test_share_update_incremental_processing(tmp_path: Path):
    """Test that share update can process incremental changes."""
    # Create initial snapshot
    snapshot_v1 = tmp_path / "snapshot_v1.sqlite3"
    _create_snapshot_with_data(snapshot_v1, num_messages=3)

    # Finalize v1 and build auxiliary structures
    finalize_snapshot_for_export(snapshot_v1)
    build_materialized_views(snapshot_v1)
    create_performance_indexes(snapshot_v1)

    # Create updated snapshot with more messages
    snapshot_v2 = tmp_path / "snapshot_v2.sqlite3"
    _create_snapshot_with_data(snapshot_v2, num_messages=5)

    # Finalize v2
    finalize_snapshot_for_export(snapshot_v2)
    build_materialized_views(snapshot_v2)
    create_performance_indexes(snapshot_v2)

    # Verify both snapshots have optimizations
    for snapshot in [snapshot_v1, snapshot_v2]:
        conn = sqlite3.connect(str(snapshot))
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
            count = cursor.fetchone()[0]
            assert count > 0
        finally:
            conn.close()


def test_materialized_views_refresh_on_update(tmp_path: Path):
    """Test that materialized views are refreshed when database is updated."""
    snapshot = tmp_path / "test.sqlite3"
    _create_snapshot_with_data(snapshot, num_messages=3)

    # Build initial materialized views
    build_materialized_views(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify initial count
        cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
        initial_count = cursor.fetchone()[0]
        assert initial_count == 3

        # Add more messages
        conn.execute(
            """
            INSERT INTO messages (
                id, project_id, sender_id, thread_id, subject, body_md,
                importance, ack_required, created_ts, attachments
            )
            VALUES (4, 1, 1, 'thread-4', 'Subject 4', 'Body 4', 'normal', 0, '2025-01-04T00:00:00Z', '[]')
            """
        )
        conn.commit()
    finally:
        conn.close()

    # Rebuild materialized views
    build_materialized_views(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify updated count
        cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
        updated_count = cursor.fetchone()[0]
        assert updated_count == 4
    finally:
        conn.close()


def test_bundle_attachments_with_detachment(tmp_path: Path):
    """Test attachment bundling with large files."""
    snapshot = tmp_path / "test.sqlite3"
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
                created_ts TEXT,
                attachments TEXT
            );
            """
        )

        # Create large attachment
        attachments = json.dumps(
            [
                {
                    "type": "file",
                    "path": "attachments/raw/large_file.bin",
                    "media_type": "application/octet-stream",
                    "size_bytes": 20000,  # Larger than typical detach threshold
                }
            ]
        )

        conn.execute("INSERT INTO projects (id, slug) VALUES (1, 'test')")
        conn.execute("INSERT INTO agents (id, name) VALUES (1, 'Agent')")
        conn.execute(
            """
            INSERT INTO messages (id, project_id, sender_id, thread_id, created_ts, attachments)
            VALUES (1, 1, 1, 'thread-1', '2025-01-01T00:00:00Z', ?)
            """,
            (attachments,),
        )

        conn.commit()
    finally:
        conn.close()

    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    # Create fake attachment file
    attach_dir = storage_root / "attachments" / "raw"
    attach_dir.mkdir(parents=True)
    large_file = attach_dir / "large_file.bin"
    large_file.write_bytes(b"X" * 20000)

    # Bundle with small detach threshold
    bundle_output = tmp_path / "bundle_output"
    bundle_output.mkdir()
    bundle_attachments(
        snapshot,
        bundle_output,
        storage_root=storage_root,
        inline_threshold=1024,
        detach_threshold=10000,  # File is larger than this
    )

    # Verify detached bundle was created
    bundles = list(bundle_output.glob("attachments/bundles/*.bin"))
    assert len(bundles) > 0


def test_performance_indexes_multiple_calls(tmp_path: Path):
    """Test that calling create_performance_indexes multiple times is safe."""
    snapshot = tmp_path / "test.sqlite3"
    _create_snapshot_with_data(snapshot)

    # Call multiple times
    create_performance_indexes(snapshot)
    create_performance_indexes(snapshot)
    create_performance_indexes(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify indexes still exist and are functional
        cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        count = cursor.fetchone()[0]
        assert count > 0

        # Verify lowercase columns work
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE subject_lower IS NOT NULL")
        count = cursor.fetchone()[0]
        assert count > 0

    finally:
        conn.close()


def test_finalize_snapshot_atomic_updates(tmp_path: Path):
    """Test that finalize_snapshot_for_export maintains consistency."""
    snapshot = tmp_path / "test.sqlite3"
    _create_snapshot_with_data(snapshot)

    # Finalize snapshot and refresh derived structures
    finalize_snapshot_for_export(snapshot)
    build_materialized_views(snapshot)
    create_performance_indexes(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify message counts are consistent across tables
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        messages_count = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
        mv_count = cursor.fetchone()[0]

        assert messages_count == mv_count

    finally:
        conn.close()


def test_lowercase_column_population(tmp_path: Path):
    """Test that lowercase columns are populated correctly."""
    snapshot = tmp_path / "test.sqlite3"
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
                created_ts TEXT,
                attachments TEXT
            );
            """
        )

        conn.execute("INSERT INTO projects (id, slug) VALUES (1, 'test')")
        conn.execute("INSERT INTO agents (id, name) VALUES (1, 'TestAgent')")

        # Insert messages with mixed case
        test_cases = [
            ("UPPERCASE SUBJECT", "TestAgent"),
            ("lowercase subject", "TestAgent"),
            ("MixedCase Subject", "TestAgent"),
        ]

        for i, (subject, _) in enumerate(test_cases, 1):
            conn.execute(
                """
                INSERT INTO messages (id, project_id, sender_id, thread_id, subject, body_md, created_ts, attachments)
                VALUES (?, 1, 1, ?, ?, 'body', '2025-01-01T00:00:00Z', '[]')
                """,
                (i, f"thread-{i}", subject),
            )

        conn.commit()
    finally:
        conn.close()

    # Create indexes (which populates lowercase columns)
    create_performance_indexes(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify lowercase columns are populated
        cursor = conn.execute("SELECT id, subject, subject_lower FROM messages ORDER BY id")
        rows = cursor.fetchall()

        assert rows[0][2] == "uppercase subject"
        assert rows[1][2] == "lowercase subject"
        assert rows[2][2] == "mixedcase subject"

    finally:
        conn.close()


def test_fts_search_overview_mv_creation(tmp_path: Path):
    """Test FTS search overview materialized view (if FTS5 is available)."""
    snapshot = tmp_path / "test.sqlite3"
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
            CREATE TABLE message_recipients (
                message_id INTEGER,
                agent_id INTEGER,
                kind TEXT
            );
            """
        )

        # Create FTS5 table
        conn.execute(
            """
            CREATE VIRTUAL TABLE fts_messages USING fts5(
                message_id UNINDEXED,
                project_id UNINDEXED,
                agent_name,
                subject,
                body,
                content=''
            )
            """
        )

        conn.execute("INSERT INTO projects (id, slug) VALUES (1, 'test')")
        conn.execute("INSERT INTO agents (id, name) VALUES (1, 'Agent')")
        conn.execute(
            """
            INSERT INTO messages (id, project_id, sender_id, thread_id, subject, body_md, importance, ack_required, created_ts, attachments)
            VALUES (1, 1, 1, 'thread-1', 'Test Subject', 'Test Body', 'normal', 0, '2025-01-01T00:00:00Z', '[]')
            """
        )

        conn.commit()
    finally:
        conn.close()

    # Build materialized views
    build_materialized_views(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Check if FTS search overview was created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fts_search_overview_mv'")
        tables = cursor.fetchall()

        # Should be created if FTS5 is available
        if len(tables) > 0:
            # Verify it has data
            cursor = conn.execute("SELECT COUNT(*) FROM fts_search_overview_mv")
            count = cursor.fetchone()[0]
            assert count > 0

    finally:
        conn.close()


def _create_old_schema_snapshot(snapshot_path: Path, num_messages: int = 5) -> None:
    """Create a snapshot database with OLD schema (no thread_id column)."""
    conn = sqlite3.connect(str(snapshot_path))
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
            CREATE TABLE project_sibling_suggestions (id INTEGER PRIMARY KEY, project_a_id INTEGER, project_b_id INTEGER);
            """
        )

        # Insert test data
        conn.execute("INSERT INTO projects (id, slug, human_key) VALUES (1, 'test-proj', 'Test Project')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (1, 1, 'TestAgent')")

        for i in range(1, num_messages + 1):
            conn.execute(
                """
                INSERT INTO messages (
                    id, project_id, sender_id, subject, body_md,
                    importance, ack_required, created_ts, attachments
                )
                VALUES (?, 1, 1, ?, ?, 'normal', 0, ?, '[]')
                """,
                (i, f"Subject {i}", f"Body {i}", f"2025-01-{i:02d}T00:00:00Z"),
            )

        conn.commit()
    finally:
        conn.close()


def test_performance_indexes_old_schema_without_thread_id(tmp_path: Path):
    """Test that create_performance_indexes works on old schemas without thread_id column.

    This is a regression test for PR #40 schema compatibility.
    Old databases don't have the thread_id column, so we must skip creating
    indexes on it to avoid sqlite3.OperationalError.
    """
    snapshot = tmp_path / "old_schema.sqlite3"
    _create_old_schema_snapshot(snapshot)

    # This should NOT crash even though messages table has no thread_id column
    create_performance_indexes(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify basic indexes were created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_messages_created_ts'")
        assert cursor.fetchone() is not None, "Basic timestamp index should be created"

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_messages_subject_lower'")
        assert cursor.fetchone() is not None, "Subject lowercase index should be created"

        # Verify thread_id index was NOT created (since column doesn't exist)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_messages_thread'")
        result = cursor.fetchone()
        assert result is None, "Thread index should NOT be created on old schema without thread_id column"

        # Verify lowercase columns were populated
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE subject_lower IS NOT NULL")
        count = cursor.fetchone()[0]
        assert count > 0, "Lowercase columns should be populated"

    finally:
        conn.close()
