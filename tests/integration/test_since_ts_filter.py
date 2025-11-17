"""Integration test for since_ts filter bug in fetch_inbox and fetch_outbox.

This test demonstrates the bug where since_ts parameter doesn't filter correctly
when using .mcp_mail/ storage with SQLite database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastmcp import Client

from mcp_agent_mail import config as _config
from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import ensure_schema


def _get(field: str, obj):
    """Helper to get field from either dict or object."""
    if isinstance(obj, dict):
        return obj.get(field)
    return getattr(obj, field, None)


@pytest.fixture
async def mcp_mail_storage(tmp_path, monkeypatch):
    """Set up .mcp_mail/ storage with real implementation."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Set up .mcp_mail/ as storage location
    mcp_mail_dir = project_dir / ".mcp_mail"
    mcp_mail_dir.mkdir()

    # Configure environment to use .mcp_mail/ storage
    monkeypatch.setenv("STORAGE_ROOT", str(mcp_mail_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{mcp_mail_dir}/storage.sqlite3")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test-agent")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

    # Clear settings cache to pick up new env vars
    _config.clear_settings_cache()

    # Initialize database
    await ensure_schema()

    yield {
        "project_dir": project_dir,
        "storage_dir": mcp_mail_dir,
        "db_path": mcp_mail_dir / "storage.sqlite3",
    }

    # Cleanup
    _config.clear_settings_cache()


@pytest.mark.asyncio
async def test_fetch_inbox_since_ts_filter(mcp_mail_storage):
    """Test that fetch_inbox correctly filters messages using since_ts parameter.

    This test verifies the fix for the bug where since_ts was not filtering
    correctly because LIMIT was applied before WHERE clauses in SQLAlchemy.
    """
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Setup: Create project and agents
        await client.call_tool("ensure_project", {"human_key": "/test-project"})

        await client.call_tool(
            "register_agent",
            {
                "project_key": "test-project",
                "program": "test",
                "model": "test-model",
                "name": "sender",
            },
        )

        await client.call_tool(
            "register_agent",
            {
                "project_key": "test-project",
                "program": "test",
                "model": "test-model",
                "name": "receiver",
            },
        )

        # Create some OLD messages (before checkpoint)
        for i in range(5):
            await client.call_tool(
                "send_message",
                {
                    "project_key": "test-project",
                    "sender_name": "sender",
                    "to": ["receiver"],
                    "subject": f"Old Message {i}",
                    "body_md": "This is an old message before checkpoint",
                },
            )
            await asyncio.sleep(0.05)

        # Get a checkpoint timestamp AFTER old messages
        checkpoint_ts = datetime.now(timezone.utc).isoformat()
        await asyncio.sleep(0.1)

        # Create NEW messages (should be included when filtering with checkpoint)
        msg1_result = await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "sender",
                "to": ["receiver"],
                "subject": "New Message 1",
                "body_md": "This message was created after checkpoint",
            },
        )
        msg1_ts = msg1_result.data["deliveries"][0]["payload"]["created_ts"]

        await asyncio.sleep(0.1)

        msg2_result = await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "sender",
                "to": ["receiver"],
                "subject": "New Message 2",
                "body_md": "This message was also created after checkpoint",
            },
        )
        msg2_ts = msg2_result.data["deliveries"][0]["payload"]["created_ts"]

        # Test 1: Fetch inbox WITHOUT since_ts filter (baseline)
        result_no_filter = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": "test-project",
                "agent_name": "receiver",
                "limit": 20,
            },
        )

        messages_no_filter = list(result_no_filter.data)
        assert len(messages_no_filter) == 7, (
            f"Expected 7 messages without filter (5 old + 2 new), got {len(messages_no_filter)}"
        )

        # Test 2: Fetch inbox WITH since_ts filter (this should work!)
        result_with_filter = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": "test-project",
                "agent_name": "receiver",
                "limit": 20,
                "since_ts": checkpoint_ts,
            },
        )

        messages_with_filter = list(result_with_filter.data)

        # Debug: Check what we actually got
        print("\n=== Debug Info ===")
        print(f"Checkpoint: {checkpoint_ts}")
        print(f"Msg1 timestamp: {msg1_ts}")
        print(f"Msg2 timestamp: {msg2_ts}")
        print(f"Messages without filter: {len(messages_no_filter)}")
        print(f"Messages with filter: {len(messages_with_filter)}")

        for i, msg in enumerate(messages_with_filter):
            subj = _get("subject", msg)
            ts = _get("created_ts", msg)
            print(f"  Message {i}: subject={subj}, created_ts={ts}")

        # THIS IS THE BUG: since_ts filter should return the same 2 messages
        # because they were both created after checkpoint_ts
        assert len(messages_with_filter) == 2, (
            f"BUG: since_ts filter returned {len(messages_with_filter)} messages, "
            f"expected 2. Both messages were created after checkpoint ({checkpoint_ts}): "
            f"msg1 at {msg1_ts}, msg2 at {msg2_ts}"
        )


# Note: fetch_outbox is not exposed as an MCP tool, so we can't test it here.
# The fix applies to _list_outbox which is used internally.
