"""Tests for database optimizations: materialized views and performance indexes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mcp_agent_mail.share import (
    build_materialized_views,
    create_performance_indexes,
)


def _create_test_snapshot(snapshot_path: Path) -> None:
    """Create a test database snapshot with sample data."""
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
            """
        )

        # Insert test data
        conn.execute("INSERT INTO projects (id, slug, human_key) VALUES (1, 'test-proj', 'Test Project')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (1, 1, 'Alice')")
        conn.execute("INSERT INTO agents (id, project_id, name) VALUES (2, 1, 'Bob')")

        # Insert messages
        for i in range(1, 6):
            conn.execute(
                """
                INSERT INTO messages (
                    id, project_id, sender_id, thread_id, subject, body_md,
                    importance, ack_required, created_ts, attachments
                )
                VALUES (?, 1, ?, ?, ?, ?, 'normal', 0, ?, '[]')
                """,
                (i, (i % 2) + 1, f"thread-{i}", f"Subject {i}", f"Body {i}", f"2025-01-{i:02d}T00:00:00Z"),
            )

        # Insert message recipients
        conn.execute("INSERT INTO message_recipients (message_id, agent_id, kind) VALUES (1, 2, 'to')")
        conn.execute("INSERT INTO message_recipients (message_id, agent_id, kind) VALUES (2, 1, 'to')")

        conn.commit()
    finally:
        conn.close()


def test_build_materialized_views_basic(tmp_path: Path):
    """Test basic materialized view creation."""
    snapshot = tmp_path / "test.sqlite3"
    _create_test_snapshot(snapshot)

    # Build materialized views
    build_materialized_views(snapshot)

    # Verify message_overview_mv was created
    conn = sqlite3.connect(str(snapshot))
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_overview_mv'")
        tables = cursor.fetchall()
        assert len(tables) == 1

        # Verify data in materialized view
        cursor = conn.execute("SELECT COUNT(*) FROM message_overview_mv")
        count = cursor.fetchone()[0]
        assert count == 5  # 5 messages inserted

        # Verify denormalized sender names
        cursor = conn.execute("SELECT id, sender_name FROM message_overview_mv WHERE id = 1")
        row = cursor.fetchone()
        assert row[1] == "Alice"

    finally:
        conn.close()


def test_build_materialized_views_with_recipients(tmp_path: Path):
    """Test materialized view includes recipient information."""
    snapshot = tmp_path / "test.sqlite3"
    _create_test_snapshot(snapshot)

    build_materialized_views(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Check recipient aggregation
        cursor = conn.execute("SELECT id, recipients FROM message_overview_mv WHERE id = 1")
        row = cursor.fetchone()
        assert row is not None
        assert "Bob" in row[1]  # Recipient name should be in aggregated list

    finally:
        conn.close()


def test_attachments_materialized_view(tmp_path: Path):
    """Test attachments_by_message_mv materialized view."""
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

        # Insert message with attachments
        attachments = json.dumps(
            [
                {"type": "file", "path": "doc.pdf", "media_type": "application/pdf", "size_bytes": 1024},
                {"type": "image", "path": "screenshot.png", "media_type": "image/png", "size_bytes": 2048},
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

    # Build materialized views
    build_materialized_views(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify attachments_by_message_mv was created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attachments_by_message_mv'")
        tables = cursor.fetchall()
        assert len(tables) == 1

        # Verify flattened attachments
        cursor = conn.execute("SELECT message_id, attachment_type, media_type FROM attachments_by_message_mv")
        rows = cursor.fetchall()
        assert len(rows) == 2  # 2 attachments

        types = {row[1] for row in rows}
        assert "file" in types
        assert "image" in types

    finally:
        conn.close()


def test_create_performance_indexes(tmp_path: Path):
    """Test performance index creation."""
    snapshot = tmp_path / "test.sqlite3"
    _create_test_snapshot(snapshot)

    # Create performance indexes
    create_performance_indexes(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify lowercase columns were added
        cursor = conn.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "subject_lower" in columns
        assert "sender_lower" in columns

        # Verify indexes were created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        indexes = {row[0] for row in cursor.fetchall()}

        expected_indexes = {
            "idx_messages_subject_lower",
            "idx_messages_sender_lower",
            "idx_messages_created_ts",
            "idx_messages_thread",
            "idx_messages_sender",
        }

        assert expected_indexes.issubset(indexes)

    finally:
        conn.close()


def test_case_insensitive_search_optimization(tmp_path: Path):
    """Test that lowercase columns enable efficient case-insensitive search."""
    snapshot = tmp_path / "test.sqlite3"
    _create_test_snapshot(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Insert messages with mixed case subjects
        conn.execute(
            """
            INSERT INTO messages (id, project_id, sender_id, thread_id, subject, body_md, created_ts, attachments)
            VALUES (10, 1, 1, 'thread-10', 'URGENT: Production Issue', 'Help needed', '2025-01-10T00:00:00Z', '[]')
            """
        )
        conn.execute(
            """
            INSERT INTO messages (id, project_id, sender_id, thread_id, subject, body_md, created_ts, attachments)
            VALUES (11, 1, 1, 'thread-11', 'urgent: database down', 'Emergency', '2025-01-11T00:00:00Z', '[]')
            """
        )
        conn.commit()
    finally:
        conn.close()

    # Create indexes with lowercase columns
    create_performance_indexes(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Search should now use lowercase column
        cursor = conn.execute("SELECT id, subject FROM messages WHERE subject_lower LIKE '%urgent%' ORDER BY id")
        rows = cursor.fetchall()

        assert len(rows) == 2
        assert rows[0][0] == 10
        assert rows[1][0] == 11
        assert "URGENT" in rows[0][1]
        assert "urgent" in rows[1][1]

    finally:
        conn.close()


def test_materialized_view_indexes(tmp_path: Path):
    """Test that materialized views have covering indexes."""
    snapshot = tmp_path / "test.sqlite3"
    _create_test_snapshot(snapshot)

    build_materialized_views(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Verify indexes on message_overview_mv
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='index'
            AND tbl_name='message_overview_mv'
            AND name LIKE 'idx_%'
            """
        )
        indexes = {row[0] for row in cursor.fetchall()}

        expected_indexes = {
            "idx_msg_overview_created",
            "idx_msg_overview_thread",
            "idx_msg_overview_project",
            "idx_msg_overview_importance",
        }

        assert expected_indexes.issubset(indexes)

    finally:
        conn.close()


def test_analyze_runs_after_index_creation(tmp_path: Path):
    """Test that ANALYZE is run for query optimizer statistics."""
    snapshot = tmp_path / "test.sqlite3"
    _create_test_snapshot(snapshot)

    create_performance_indexes(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        # Check that sqlite_stat1 table exists (created by ANALYZE)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'")
        stat_tables = cursor.fetchall()
        assert len(stat_tables) == 1

    finally:
        conn.close()


def test_idempotent_index_creation(tmp_path: Path):
    """Test that running index creation multiple times is safe."""
    snapshot = tmp_path / "test.sqlite3"
    _create_test_snapshot(snapshot)

    # Run twice
    create_performance_indexes(snapshot)
    create_performance_indexes(snapshot)

    # Should not error, and indexes should still exist
    conn = sqlite3.connect(str(snapshot))
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        count = cursor.fetchone()[0]
        assert count > 0

    finally:
        conn.close()


def test_materialized_view_snippet_column(tmp_path: Path):
    """Test that message_overview_mv includes snippet for previews."""
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
            CREATE TABLE message_recipients (message_id INTEGER, agent_id INTEGER, kind TEXT);
            """
        )

        # Insert long message
        long_body = "A" * 500  # Longer than snippet limit
        conn.execute("INSERT INTO projects (id, slug) VALUES (1, 'test')")
        conn.execute("INSERT INTO agents (id, name) VALUES (1, 'Agent')")
        conn.execute(
            """
            INSERT INTO messages (id, project_id, sender_id, thread_id, subject, body_md, importance, ack_required, created_ts, attachments)
            VALUES (1, 1, 1, 'thread-1', 'Test', ?, 'normal', 0, '2025-01-01T00:00:00Z', '[]')
            """,
            (long_body,),
        )

        conn.commit()
    finally:
        conn.close()

    build_materialized_views(snapshot)

    conn = sqlite3.connect(str(snapshot))
    try:
        cursor = conn.execute("SELECT latest_snippet FROM message_overview_mv WHERE id = 1")
        snippet = cursor.fetchone()[0]

        # Snippet should be truncated
        assert len(snippet) <= 280
        assert snippet.startswith("A")

    finally:
        conn.close()
