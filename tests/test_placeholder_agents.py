"""Tests for placeholder agents - messages sent to unregistered agents.

This tests the feature where:
1. Messages can be sent to agents that don't exist yet (creates placeholder)
2. The placeholder agent can be "claimed" by a later registration
3. All pending messages become accessible after registration
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


@pytest.mark.asyncio
async def test_send_message_to_unregistered_creates_placeholder(isolated_env):
    """
    Test that sending a message to an unregistered agent creates a placeholder.

    Steps:
    1. Register sender agent
    2. Send message to non-existent recipient (should auto-create placeholder)
    3. Verify message was delivered
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register sender
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "sender-program",
                "model": "sender-model",
                "name": "SenderAgent",
            },
        )

        # Send message to non-existent recipient
        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "SenderAgent",
                "to": ["UnregisteredRecipient"],
                "subject": "Hello Future Agent",
                "body_md": "This message was sent before you registered.",
            },
        )

        # Should succeed (auto-creates placeholder)
        assert send_result.data["count"] > 0
        assert "deliveries" in send_result.data


@pytest.mark.asyncio
async def test_placeholder_receives_messages_before_registration(isolated_env):
    """
    Test that messages sent to a placeholder are readable after registration.

    Steps:
    1. Register sender agent
    2. Send multiple messages to non-existent recipient
    3. Later, register the recipient
    4. Fetch inbox - should see all messages
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register sender
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "sender-program",
                "model": "sender-model",
                "name": "SenderAgent",
            },
        )

        # Send multiple messages to non-existent recipient
        await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "SenderAgent",
                "to": ["FutureRecipient"],
                "subject": "Message 1",
                "body_md": "First message before registration.",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "SenderAgent",
                "to": ["FutureRecipient"],
                "subject": "Message 2",
                "body_md": "Second message before registration.",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "SenderAgent",
                "to": ["FutureRecipient"],
                "subject": "Message 3",
                "body_md": "Third message before registration.",
            },
        )

        # Now register the recipient (claims the placeholder)
        register_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "recipient-program",
                "model": "recipient-model",
                "name": "FutureRecipient",
            },
        )
        assert register_result.data["name"] == "FutureRecipient"
        # After claiming, is_placeholder should be False
        assert register_result.data.get("is_placeholder", False) is False

        # Fetch inbox - should see all 3 messages
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": "/test/project",
                "agent_name": "FutureRecipient",
                "include_bodies": True,
            },
        )

        inbox_messages = (
            inbox_result.structured_content.get("result", inbox_result.data)
            if hasattr(inbox_result, "structured_content")
            else inbox_result.data
        )

        assert len(inbox_messages) == 3, f"Expected 3 messages, got {len(inbox_messages)}"
        subjects = {msg["subject"] for msg in inbox_messages}
        assert subjects == {"Message 1", "Message 2", "Message 3"}


@pytest.mark.asyncio
async def test_placeholder_is_marked_as_placeholder(isolated_env):
    """
    Test that auto-created placeholder agents have is_placeholder=True.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register sender
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "sender-program",
                "model": "sender-model",
                "name": "SenderAgent",
            },
        )

        # Send message to create placeholder
        await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "SenderAgent",
                "to": ["PlaceholderAgent"],
                "subject": "Test",
                "body_md": "Test message.",
            },
        )

        # Use whois to check the placeholder agent's status
        whois_result = await client.call_tool(
            "whois",
            {
                "project_key": "/test/project",
                "agent_name": "PlaceholderAgent",
            },
        )

        assert whois_result.data["name"] == "PlaceholderAgent"
        assert whois_result.data.get("is_placeholder", False) is True


@pytest.mark.asyncio
async def test_registration_claims_placeholder(isolated_env):
    """
    Test that registering with a placeholder's name claims it.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register sender
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "sender-program",
                "model": "sender-model",
                "name": "SenderAgent",
            },
        )

        # Send message to create placeholder
        await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "SenderAgent",
                "to": ["ClaimableAgent"],
                "subject": "Test",
                "body_md": "Test message.",
            },
        )

        # Verify placeholder was created
        whois_before = await client.call_tool(
            "whois",
            {
                "project_key": "/test/project",
                "agent_name": "ClaimableAgent",
            },
        )
        assert whois_before.data.get("is_placeholder") is True
        placeholder_id = whois_before.data["id"]

        # Now register with the same name (claims the placeholder)
        register_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "real-program",
                "model": "real-model",
                "name": "ClaimableAgent",
                "task_description": "I am the real agent now",
            },
        )

        # Should have same ID (claimed, not new)
        assert register_result.data["id"] == placeholder_id
        assert register_result.data["program"] == "real-program"
        assert register_result.data["model"] == "real-model"
        assert register_result.data.get("is_placeholder", True) is False


@pytest.mark.asyncio
async def test_placeholder_claim_from_different_project(isolated_env):
    """
    Test that placeholders can be claimed from a different project.

    This is important for cross-project messaging where the placeholder
    was created in one project but the agent registers in another.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register sender in project A
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/project-a",
                "program": "sender-program",
                "model": "sender-model",
                "name": "ProjectASender",
            },
        )

        # Send message to create placeholder (in project A)
        await client.call_tool(
            "send_message",
            {
                "project_key": "/project-a",
                "sender_name": "ProjectASender",
                "to": ["CrossProjectAgent"],
                "subject": "Cross-project message",
                "body_md": "This was sent from project A.",
            },
        )

        # Register agent in project B (claims the placeholder)
        register_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/project-b",
                "program": "project-b-program",
                "model": "project-b-model",
                "name": "CrossProjectAgent",
            },
        )

        # Agent should be claimed and associated with project B now
        assert register_result.data["name"] == "CrossProjectAgent"
        assert register_result.data.get("is_placeholder", True) is False

        # Should be able to read the message
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": "/project-b",
                "agent_name": "CrossProjectAgent",
                "include_bodies": True,
            },
        )

        inbox_messages = (
            inbox_result.structured_content.get("result", inbox_result.data)
            if hasattr(inbox_result, "structured_content")
            else inbox_result.data
        )

        assert len(inbox_messages) == 1
        assert inbox_messages[0]["subject"] == "Cross-project message"


@pytest.mark.asyncio
async def test_regular_agent_not_marked_as_placeholder(isolated_env):
    """
    Test that normally registered agents are NOT marked as placeholders.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register agent normally
        register_result = await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "normal-program",
                "model": "normal-model",
                "name": "NormalAgent",
            },
        )

        assert register_result.data["name"] == "NormalAgent"
        assert register_result.data.get("is_placeholder", True) is False


@pytest.mark.asyncio
async def test_send_to_existing_agent_does_not_create_placeholder(isolated_env):
    """
    Sending to an already registered agent should not create or require a placeholder.
    """

    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "sender-program",
                "model": "sender-model",
                "name": "ExistingSender",
            },
        )

        await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "existing-program",
                "model": "existing-model",
                "name": "ExistingRecipient",
            },
        )

        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "ExistingSender",
                "to": ["ExistingRecipient"],
                "subject": "Hello",
                "body_md": "Message to existing agent.",
            },
        )

        deliveries = send_result.data.get("deliveries") or []
        assert len(deliveries) == 1
        assert send_result.data.get("count") == 1

        whois_result = await client.call_tool(
            "whois",
            {
                "project_key": "/test/project",
                "agent_name": "ExistingRecipient",
            },
        )

        assert whois_result.data.get("is_placeholder") is False


@pytest.mark.asyncio
async def test_placeholder_inherits_sender_program_model(isolated_env):
    """
    Test that placeholder agents inherit the sender's program and model.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Register sender with specific program/model
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/test/project",
                "program": "special-sender-program",
                "model": "special-sender-model",
                "name": "SpecialSender",
            },
        )

        # Send message to create placeholder
        await client.call_tool(
            "send_message",
            {
                "project_key": "/test/project",
                "sender_name": "SpecialSender",
                "to": ["InheritedAgent"],
                "subject": "Test",
                "body_md": "Test message.",
            },
        )

        # Check that placeholder inherited sender's program/model
        whois_result = await client.call_tool(
            "whois",
            {
                "project_key": "/test/project",
                "agent_name": "InheritedAgent",
            },
        )

        assert whois_result.data["program"] == "special-sender-program"
        assert whois_result.data["model"] == "special-sender-model"
        assert whois_result.data.get("is_placeholder") is True
