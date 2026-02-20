"""Tests that agents in different projects can message each other.

Projects are informational labels (e.g., repo paths). They do NOT isolate agents —
any agent can message any other agent regardless of project_key.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server
from tests.conftest import extract_result, get_field


@pytest.mark.asyncio
async def test_cross_project_messaging(isolated_env):
    """Agents in different projects can message each other."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "project-a"})
        await client.call_tool("ensure_project", {"human_key": "project-b"})

        await client.call_tool(
            "register_agent",
            {"project_key": "project-a", "program": "test", "model": "test", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "project-b", "program": "test", "model": "test", "name": "Bob"},
        )

        # Alice (project-a) sends to Bob (project-b)
        result = await client.call_tool(
            "send_message",
            {
                "project_key": "project-a",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Cross-project hello",
                "body_md": "Hi from project A!",
            },
        )
        data = extract_result(result)
        deliveries = data.get("deliveries") if isinstance(data, dict) else getattr(data, "deliveries", [])
        assert deliveries, "send_message should return deliveries"
        assert len(deliveries) > 0, "Message should have at least one delivery"

        # Bob (project-b) sees the message in his inbox
        inbox = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": "project-b",
                "agent_name": "Bob",
                "limit": 10,
            },
        )
        messages = extract_result(inbox)
        assert len(messages) == 1, f"Bob should have 1 message, got {len(messages)}"
        assert get_field("subject", messages[0]) == "Cross-project hello"


@pytest.mark.asyncio
async def test_cross_project_fetch_inbox_any_project_key(isolated_env):
    """fetch_inbox works regardless of which project_key is passed — agents are global."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "proj-sender"})
        await client.call_tool("ensure_project", {"human_key": "proj-receiver"})

        await client.call_tool(
            "register_agent",
            {"project_key": "proj-sender", "program": "test", "model": "test", "name": "Sender"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "proj-receiver", "program": "test", "model": "test", "name": "Receiver"},
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "proj-sender",
                "sender_name": "Sender",
                "to": ["Receiver"],
                "subject": "Test delivery",
                "body_md": "body",
            },
        )

        # Fetch using sender's project_key — should still find Receiver's message
        inbox = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": "proj-sender",
                "agent_name": "Receiver",
                "limit": 10,
            },
        )
        messages = extract_result(inbox)
        assert len(messages) == 1, "Receiver should see the message regardless of project_key used in fetch"


@pytest.mark.asyncio
async def test_cross_project_reply(isolated_env):
    """An agent can reply to a message from an agent in a different project."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "reply-proj-a"})
        await client.call_tool("ensure_project", {"human_key": "reply-proj-b"})

        await client.call_tool(
            "register_agent",
            {"project_key": "reply-proj-a", "program": "test", "model": "test", "name": "Sprout"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "reply-proj-b", "program": "test", "model": "test", "name": "Fern"},
        )

        # Sprout sends to Fern across projects
        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": "reply-proj-a",
                "sender_name": "Sprout",
                "to": ["Fern"],
                "subject": "Hello Fern",
                "body_md": "Can you reply?",
            },
        )
        send_data = extract_result(send_result)
        deliveries = (
            send_data.get("deliveries") if isinstance(send_data, dict) else getattr(send_data, "deliveries", [])
        )
        assert deliveries, "send_message should return deliveries"
        mid = deliveries[0]["payload"]["id"]

        # Fern replies from project-b — should work cross-project
        reply_result = await client.call_tool(
            "reply_message",
            {
                "project_key": "reply-proj-b",
                "message_id": mid,
                "sender_name": "Fern",
                "body_md": "Sure, here's my reply!",
            },
        )
        reply_data = extract_result(reply_result)
        thread_id = (
            reply_data.get("thread_id") if isinstance(reply_data, dict) else getattr(reply_data, "thread_id", None)
        )
        deliveries_reply = (
            reply_data.get("deliveries") if isinstance(reply_data, dict) else getattr(reply_data, "deliveries", [])
        )
        assert thread_id, "Reply should have thread_id"
        assert deliveries_reply, "Reply should have deliveries"
