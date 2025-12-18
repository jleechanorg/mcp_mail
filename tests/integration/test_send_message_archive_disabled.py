"""Integration tests for send_message with archive disabled (SQLite-only mode).

This test verifies that messaging works when STORAGE_LOCAL_ARCHIVE_ENABLED=false,
using SQLite as the sole storage backend without Git archive operations.

This is a critical test for deployments that want fast, lightweight messaging
without the overhead of Git operations.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail import config as _config
from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import ensure_schema


@pytest.fixture
async def sqlite_only_storage(tmp_path, monkeypatch):
    """Set up SQLite-only storage with archive disabled."""
    storage_dir = tmp_path / "sqlite_only"
    storage_dir.mkdir()
    db_path = storage_dir / "storage.sqlite3"

    # Disable archive, use SQLite only
    monkeypatch.setenv("STORAGE_LOCAL_ARCHIVE_ENABLED", "false")
    monkeypatch.setenv("STORAGE_PROJECT_KEY_ENABLED", "false")
    monkeypatch.setenv("STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    _config.clear_settings_cache()
    await ensure_schema()

    yield {
        "storage_dir": storage_dir,
        "db_path": db_path,
    }

    _config.clear_settings_cache()


@pytest.mark.asyncio
async def test_send_message_works_with_archive_disabled(sqlite_only_storage):
    """Test that send_message works when archive is disabled.

    This is the RED test - it should FAIL before we fix the code.
    The error will be: "Local .mcp_mail storage is disabled..."
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register sender
        sender_result = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "test-project",
                "program": "sender-program",
                "model": "test-model",
                "name": "Sender",
                "task_description": "Sends messages",
            },
        )
        assert sender_result.data["name"] == "Sender"

        # Register receiver
        receiver_result = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "test-project",
                "program": "receiver-program",
                "model": "test-model",
                "name": "Receiver",
                "task_description": "Receives messages",
            },
        )
        assert receiver_result.data["name"] == "Receiver"

        # Send message - THIS IS THE CRITICAL TEST
        # Before fix: Fails with "Local .mcp_mail storage is disabled"
        # After fix: Should succeed and store in SQLite only
        send_result = await client.call_tool(
            "send_message",
            arguments={
                "project_key": "test-project",
                "sender_name": "Sender",
                "to": ["Receiver"],
                "subject": "Test message with archive disabled",
                "body_md": "This message should be stored in SQLite only.",
            },
        )

        # Verify message was sent
        deliveries = send_result.data.get("deliveries", [])
        assert len(deliveries) == 1, "Should have one delivery"
        payload = deliveries[0]["payload"]
        assert payload["subject"] == "Test message with archive disabled"
        assert payload["id"] is not None, "Message should have an ID"

        # Verify message can be fetched from inbox
        inbox_result = await client.call_tool(
            "fetch_inbox",
            arguments={
                "project_key": "test-project",
                "agent_name": "Receiver",
                "include_bodies": True,
            },
        )

        result_data = inbox_result.structured_content.get("result", [])
        assert len(result_data) == 1, "Should have one message in inbox"
        assert result_data[0]["subject"] == "Test message with archive disabled"


@pytest.mark.asyncio
async def test_reply_message_works_with_archive_disabled(sqlite_only_storage):
    """Test that reply_message works when archive is disabled."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Register agents
        await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "test-project",
                "program": "agent-a",
                "model": "test",
                "name": "AgentA",
                "task_description": "First agent",
            },
        )
        await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "test-project",
                "program": "agent-b",
                "model": "test",
                "name": "AgentB",
                "task_description": "Second agent",
            },
        )

        # Send initial message
        send_result = await client.call_tool(
            "send_message",
            arguments={
                "project_key": "test-project",
                "sender_name": "AgentA",
                "to": ["AgentB"],
                "subject": "Initial message",
                "body_md": "Hello from AgentA",
            },
        )
        message_id = send_result.data["deliveries"][0]["payload"]["id"]

        # Reply to the message
        reply_result = await client.call_tool(
            "reply_message",
            arguments={
                "project_key": "test-project",
                "message_id": message_id,
                "sender_name": "AgentB",
                "body_md": "Reply from AgentB",
            },
        )

        # Verify reply was sent
        assert reply_result.data["subject"].startswith("Re:")
        assert reply_result.data["id"] is not None


@pytest.mark.asyncio
async def test_no_archive_files_created_when_disabled(sqlite_only_storage):
    """Test that no archive files are created when archive is disabled."""
    storage_dir = sqlite_only_storage["storage_dir"]

    server = build_mcp_server()
    async with Client(server) as client:
        # Register and send messages
        await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "test-project",
                "program": "sender",
                "model": "test",
                "name": "Sender",
                "task_description": "Sends",
            },
        )
        await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "test-project",
                "program": "receiver",
                "model": "test",
                "name": "Receiver",
                "task_description": "Receives",
            },
        )
        await client.call_tool(
            "send_message",
            arguments={
                "project_key": "test-project",
                "sender_name": "Sender",
                "to": ["Receiver"],
                "subject": "No archive test",
                "body_md": "Should not create archive files",
            },
        )

    # Verify NO Git archive was created
    git_dir = storage_dir / ".git"
    assert not git_dir.exists(), "Git repo should NOT be initialized when archive is disabled"

    # Verify NO projects directory was created
    projects_dir = storage_dir / "projects"
    assert not projects_dir.exists(), "projects/ directory should NOT exist when archive is disabled"

    # Note: We don't check db_path.exists() because FastMCP Client runs in-process
    # and may use a memory database or different path. The key verification is that
    # archive-related files (Git, projects/) are NOT created.
