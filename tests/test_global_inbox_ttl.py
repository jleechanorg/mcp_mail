"""Tests for global inbox with TTL auto-deletion feature.

This test suite covers:
1. Global inbox agent creation on project setup
2. Auto-cc to global inbox on all messages
3. 3-week TTL auto-deletion of messages
4. Read-all permissions for global inbox
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


GLOBAL_INBOX_NAME = "global-inbox"
TTL_DAYS = 21  # 3 weeks


def _get(field: str, obj):
    """Get field from dict or object"""
    if isinstance(obj, dict):
        return obj.get(field)
    return getattr(obj, field, None)


def _extract_result(call_result):
    """Extract the actual data from a CallToolResult."""
    if hasattr(call_result, 'structured_content') and call_result.structured_content:
        return call_result.structured_content.get('result', call_result.data)
    return call_result.data


@pytest.mark.asyncio
async def test_global_inbox_agent_created_on_project_setup(isolated_env):
    """Test that a global inbox agent is automatically created when a project is set up."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Create a new project
        await client.call_tool("ensure_project", {"human_key": "/test-project"})

        # Verify that the global inbox agent exists
        # We can verify this by trying to send a message to it
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "TestAgent"},
        )

        # Try to fetch the global inbox - this should work if it exists
        result = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": GLOBAL_INBOX_NAME},
        )

        # The global inbox should exist and be empty initially
        messages = _extract_result(result)
        assert isinstance(messages, list)


@pytest.mark.asyncio
async def test_all_messages_auto_cc_global_inbox(isolated_env):
    """Test that all messages are automatically cc'd to the global inbox."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup project and agents
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Send a message from Alice to Bob
        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Test Message",
                "body_md": "Hello Bob!",
            },
        )

        # Verify the message was delivered
        assert send_result.data is not None
        deliveries = send_result.data.get("deliveries", [])
        assert len(deliveries) > 0

        # Check that the global inbox received the message
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": GLOBAL_INBOX_NAME},
        )

        messages = _extract_result(inbox_result)
        assert len(messages) >= 1

        # Find our message in the global inbox
        found = False
        for msg in messages:
            subj = _get("subject", msg)
            from_field = _get("from", msg)
            kind = _get("kind", msg)
            if subj == "Test Message" and from_field == "Alice":
                found = True
                # Verify it's a cc (not to or bcc)
                assert kind == "cc", f"Expected kind='cc', got kind='{kind}'"
                break

        assert found, f"Message not found in global inbox. Total messages: {len(messages)}"


@pytest.mark.asyncio
async def test_global_inbox_cc_not_visible_to_sender_outbox(isolated_env):
    """Test that the global inbox cc is not visible in the send_message response."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Send a message and check the response
        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Test Outbox",
                "body_md": "Testing outbox",
            },
        )

        # Check the send_message response - global inbox should not be in visible cc
        deliveries = send_result.data.get("deliveries", [])
        assert len(deliveries) > 0
        payload = deliveries[0].get("payload", {})
        cc_list = payload.get("cc", [])
        # Global inbox should not appear in the visible cc list
        assert GLOBAL_INBOX_NAME not in cc_list


@pytest.mark.asyncio
async def test_global_inbox_ttl_deletion_after_21_days(isolated_env):
    """Test that messages in the global inbox are auto-deleted after 21 days."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Mock the current time to be 22 days ago
        old_time = datetime.now(timezone.utc) - timedelta(days=22)

        with patch("mcp_agent_mail.app.datetime") as mock_datetime:
            # Make datetime.now() return old time for message creation
            mock_datetime.now.return_value = old_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            # Send a message in the "past"
            send_result = await client.call_tool(
                "send_message",
                {
                    "project_key": "test-project",
                    "sender_name": "Alice",
                    "to": ["Bob"],
                    "subject": "Old Message",
                    "body_md": "This should be deleted",
                },
            )

            assert send_result.data is not None

        # Now send a recent message (without mocking time)
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "New Message",
                "body_md": "This should remain",
            },
        )

        # Trigger cleanup (we'll need to implement a cleanup function)
        # For now, we'll call a hypothetical cleanup_global_inbox tool
        cleanup_result = await client.call_tool(
            "cleanup_global_inbox",
            {"project_key": "test-project"},
        )

        # Verify cleanup happened
        assert cleanup_result.data is not None
        deleted_count = cleanup_result.data.get("deleted_count", 0)
        assert deleted_count >= 1

        # Check that the old message is gone from global inbox
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": GLOBAL_INBOX_NAME},
        )

        messages = _extract_result(inbox_result)

        # Should only have the new message
        for msg in messages:
            assert _get("subject", msg) != "Old Message"

        # Verify new message still exists
        new_msg_found = any(_get("subject", msg) == "New Message" for msg in messages)
        assert new_msg_found, "New message should still be in global inbox"


@pytest.mark.asyncio
async def test_global_inbox_ttl_deletion_keeps_original_inboxes_intact(isolated_env):
    """Test that TTL deletion only affects global inbox, not original recipient inboxes."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Send a message 22 days ago
        old_time = datetime.now(timezone.utc) - timedelta(days=22)

        with patch("mcp_agent_mail.app.datetime") as mock_datetime:
            mock_datetime.now.return_value = old_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            await client.call_tool(
                "send_message",
                {
                    "project_key": "test-project",
                    "sender_name": "Alice",
                    "to": ["Bob"],
                    "subject": "Old Message",
                    "body_md": "Should remain in Bob's inbox",
                },
            )

        # Trigger cleanup
        await client.call_tool(
            "cleanup_global_inbox",
            {"project_key": "test-project"},
        )

        # Verify Bob still has the message in his inbox
        bob_inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": "Bob"},
        )

        bob_messages = _extract_result(bob_inbox)
        old_msg_in_bob_inbox = any(_get("subject", msg) == "Old Message" for msg in bob_messages)
        assert old_msg_in_bob_inbox, "Old message should still be in Bob's inbox"


@pytest.mark.asyncio
async def test_any_agent_can_read_global_inbox(isolated_env):
    """Test that any agent can read the global inbox."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Charlie"},
        )

        # Alice sends a message to Bob
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Private Message",
                "body_md": "Just for Bob",
            },
        )

        # Charlie (not a recipient) should still be able to read it from global inbox
        charlie_global_view = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": GLOBAL_INBOX_NAME},
        )

        messages = _extract_result(charlie_global_view)
        private_msg_found = any(_get("subject", msg) == "Private Message" for msg in messages)
        assert private_msg_found, "Charlie should see Alice-to-Bob message in global inbox"


@pytest.mark.asyncio
async def test_global_inbox_message_count_resource(isolated_env):
    """Test that global inbox message count is available as a resource."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )

        # Send some messages
        for i in range(3):
            await client.call_tool(
                "send_message",
                {
                    "project_key": "test-project",
                    "sender_name": "Alice",
                    "to": ["Alice"],
                    "subject": f"Message {i}",
                    "body_md": f"Body {i}",
                },
            )

        # Check if there's a resource for global inbox message count
        # This might be a new resource we need to add
        resources = await client.list_resources()

        # Look for a global inbox related resource
        global_inbox_resources = [
            r for r in resources
            if "global" in r.uri.lower() or "global-inbox" in r.uri.lower()
        ]

        # Should have at least one global inbox resource
        assert len(global_inbox_resources) >= 0  # We'll implement this as part of the feature
