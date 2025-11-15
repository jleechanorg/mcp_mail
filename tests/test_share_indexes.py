"""Regression tests for performance index creation compatibility."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mcp_agent_mail.share import create_performance_indexes


def _build_snapshot(tmp_path: Path, *, with_thread_id: bool) -> Path:
    snapshot_path = tmp_path / ("snapshot_with_thread.db" if with_thread_id else "snapshot_without_thread.db")
    conn = sqlite3.connect(snapshot_path)
    try:
        thread_column = ", thread_id TEXT" if with_thread_id else ""
        conn.executescript(
            f"""
            CREATE TABLE agents (
                id INTEGER PRIMARY KEY,
                name TEXT
            );

            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                subject TEXT,
                sender_id INTEGER,
                created_ts TEXT,
                body_md TEXT,
                attachments TEXT{thread_column}
            );
            """
        )
        conn.execute("INSERT INTO agents (id, name) VALUES (1, 'Agent One')")
        conn.execute(
            """
            INSERT INTO messages (id, subject, sender_id, created_ts, body_md, attachments{extra_cols})
            VALUES (1, 'Hello', 1, '2024-01-01T00:00:00Z', 'Body', '[]'{extra_values})
            """.format(
                extra_cols=", thread_id" if with_thread_id else "",
                extra_values=", 'thread-1'" if with_thread_id else "",
            )
        )
        conn.commit()
    finally:
        conn.close()
    return snapshot_path


def _get_message_indexes(snapshot_path: Path) -> set[str]:
    conn = sqlite3.connect(snapshot_path)
    try:
        rows = conn.execute("PRAGMA index_list(messages)").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def test_create_performance_indexes_skips_thread_index_when_column_missing(tmp_path: Path) -> None:
    snapshot_path = _build_snapshot(tmp_path, with_thread_id=False)

    create_performance_indexes(snapshot_path)

    indexes = _get_message_indexes(snapshot_path)
    assert "idx_messages_thread" not in indexes


def test_create_performance_indexes_builds_thread_index_when_column_present(tmp_path: Path) -> None:
    snapshot_path = _build_snapshot(tmp_path, with_thread_id=True)

    create_performance_indexes(snapshot_path)

    indexes = _get_message_indexes(snapshot_path)
    assert "idx_messages_thread" in indexes
