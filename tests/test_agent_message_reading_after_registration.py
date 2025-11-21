"""Test for agent message reading after registration bug.

This test validates the fix for the issue where agents couldn't properly read
messages immediately after registration.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


@pytest.mark.asyncio
async def test_agent_reads_messages_immediately_after_registration(isolated_env):
    """
    Test that an agent can read messages sent to it immediately after registration.

    Steps:
    1. Register sender agent
    2. Register recipient agent
    3. Sender immediately sends message to recipient
    4. Recipient immediately fetches inbox
    5. Verify message is visible

    This tests for potential race conditions or database session issues.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Step 1: Register sender agent
        sender_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "test-sender",
                "model": "test-model-1",
                "name": "SenderBot",
            },
        )
        assert sender_result.data["name"] == "SenderBot"

        # Step 2: Register recipient agent
        recipient_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "test-recipient",
                "model": "test-model-2",
                "name": "RecipientBot",
            },
        )
        assert recipient_result.data["name"] == "RecipientBot"

        # Step 3: Sender immediately sends message to recipient
        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "SenderBot",
                "to": ["RecipientBot"],
                "subject": "Test Message",
                "body_md": "Hello RecipientBot!",
            },
        )
        assert send_result.data["count"] > 0
        assert "deliveries" in send_result.data
        assert send_result.data["deliveries"], "Expected at least one delivery"
        message_id = send_result.data["deliveries"][0]["payload"]["id"]

        # Step 4: Recipient immediately fetches inbox
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": "/test/project",
                "agent_name": "RecipientBot",
                "include_bodies": True,
            },
        )

        # Step 5: Verify message is visible
        inbox_messages = (
            inbox_result.structured_content.get("result", inbox_result.data)
            if hasattr(inbox_result, "structured_content")
            else inbox_result.data
        )
        assert len(inbox_messages) > 0, "Inbox should not be empty after message was sent"
        matching = [msg for msg in inbox_messages if msg["id"] == message_id]
        assert matching, f"Message {message_id} not found in inbox. Got: {inbox_messages}"
        assert matching[0]["subject"] == "Test Message"


@pytest.mark.asyncio
async def test_brand_new_agent_fetch_inbox_empty(isolated_env):
    """
    Test that a brand new agent can fetch inbox (should be empty) without errors.

    This tests that fetch_inbox works correctly for agents that just registered
    and have no messages yet.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register a brand new agent
        agent_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "test-agent",
                "model": "test-model",
                "name": "BrandNewAgent",
            },
        )
        assert agent_result.data["name"] == "BrandNewAgent"

        # Immediately try to fetch inbox (should be empty, not error)
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": "/test/project",
                "agent_name": "BrandNewAgent",
            },
        )

        # Should return empty list, not error
        inbox_messages = (
            inbox_result.structured_content.get("result", inbox_result.data)
            if hasattr(inbox_result, "structured_content")
            else inbox_result.data
        )
        assert isinstance(inbox_messages, list)
        assert len(inbox_messages) == 0


@pytest.mark.asyncio
async def test_agent_auto_fetch_inbox_on_registration(isolated_env):
    """
    Test that auto_fetch_inbox parameter works correctly on first registration.

    This tests that when an agent registers for the first time with
    auto_fetch_inbox=True, it correctly returns an empty inbox (or any
    existing messages).
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Create a sender first to send message before recipient registers
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "sender",
                "model": "test",
                "name": "PreSender",
            },
        )

        # Register recipient with auto_fetch_inbox=True
        # This is the FIRST time this agent registers
        recipient_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "recipient",
                "model": "test",
                "name": "AutoFetchRecipient",
                "auto_fetch_inbox": True,
            },
        )

        # Should return both agent and inbox
        assert "agent" in recipient_result.data
        assert "inbox" in recipient_result.data
        assert recipient_result.data["agent"]["name"] == "AutoFetchRecipient"
        assert isinstance(recipient_result.data["inbox"], list)
        first_agent_id = recipient_result.data["agent"]["id"]
        # Inbox should be empty since no messages sent yet
        assert len(recipient_result.data["inbox"]) == 0

        # Now send a message
        await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "PreSender",
                "to": ["AutoFetchRecipient"],
                "subject": "Late message",
                "body_md": "Sent after registration",
            },
        )

        # Re-register with auto_fetch (updates agent)
        update_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "recipient-updated",
                "model": "test-updated",
                "name": "AutoFetchRecipient",
                "auto_fetch_inbox": True,
            },
        )

        # Now inbox should have the message
        assert update_result.data["agent"]["id"] == first_agent_id
        assert len(update_result.data["inbox"]) == 1
        assert update_result.data["inbox"][0]["subject"] == "Late message"
