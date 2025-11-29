from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


@pytest.mark.asyncio
async def test_invalid_project_or_agent_errors(isolated_env):
    server = build_mcp_server()
    async with Client(server) as client:
        # register_agent now auto-creates projects, so this should succeed
        res = await client.call_tool_mcp(
            "register_agent", {"project_key": "Missing", "program": "x", "model": "y", "name": "A"}
        )
        assert res.isError is False  # Changed: project is auto-created
        assert res.content[0].text  # Should have success response

        # Now create another project and try sending from unknown agent
        await client.call_tool("ensure_project", {"human_key": "/backend"})
        res2 = await client.call_tool_mcp(
            "send_message",
            {"project_key": "Backend", "sender_name": "Ghost", "to": ["Ghost"], "subject": "x", "body_md": "y"},
        )
        # Should be error due to unknown agent
        assert res2.isError is True


@pytest.mark.asyncio
async def test_unknown_recipient_creates_placeholder_agent(isolated_env):
    """Messages to unknown recipients create placeholder agents and store messages."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/backend"})
        await client.call_tool(
            "register_agent",
            {"project_key": "Backend", "program": "codex", "model": "gpt-5", "name": "GreenCastle"},
        )

        # Unknown recipient creates placeholder agent and stores message (no error)
        res = await client.call_tool(
            "send_message",
            {
                "project_key": "Backend",
                "sender_name": "GreenCastle",
                "to": ["BlueLake"],
                "subject": "Hello",
                "body_md": "testing unknown recipient",
            },
        )
        # Message should be delivered successfully
        assert res.data.get("deliveries") is not None
        assert res.data.get("count") == 1

        # Send another message to verify placeholder agent is reused
        res2 = await client.call_tool(
            "send_message",
            {
                "project_key": "Backend",
                "sender_name": "GreenCastle",
                "to": ["BlueLake"],
                "subject": "Hello again",
                "body_md": "second message to placeholder",
            },
        )
        assert res2.data.get("count") == 1
        assert res2.data.get("deliveries") is not None

        # Register and ensure sanitized inputs (hyphen stripped/lowercased) route
        await client.call_tool(
            "register_agent",
            {"project_key": "Backend", "program": "codex", "model": "gpt-5", "name": "BlueLake"},
        )
        success = await client.call_tool(
            "send_message",
            {
                "project_key": "Backend",
                "sender_name": "GreenCastle",
                "to": ["blue-lake"],
                "subject": "Hello again",
                "body_md": "now routed",
            },
        )
        deliveries = success.data.get("deliveries") or []
        assert deliveries and deliveries[0].get("payload", {}).get("subject") == "Hello again"
