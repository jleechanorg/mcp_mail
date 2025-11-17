"""Test thread resource query parameter parsing."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


def extract_msg_id(result) -> int | None:
    """Extract message ID from send_message result."""

    def _get(field: str, obj):
        if isinstance(obj, dict):
            return obj.get(field)
        return getattr(obj, field, None)

    data = getattr(result, "data", result)
    deliveries = _get("deliveries", data) or []
    if deliveries:
        payload = _get("payload", deliveries[0]) or {}
        return _get("id", payload)
    return None


@pytest.mark.asyncio
async def test_thread_resource_with_absolute_path(isolated_env):
    """Test that thread resource accepts project parameter as absolute path."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Create a project with an absolute path-like human key
        await client.call_tool("ensure_project", {"human_key": "/Users/test/backend"})
        await client.call_tool(
            "register_agent", {"project_key": "/Users/test/backend", "program": "x", "model": "y", "name": "TestAgent"}
        )

        # Send a test message
        result = await client.call_tool(
            "send_message",
            {
                "project_key": "/Users/test/backend",
                "sender_name": "TestAgent",
                "to": ["TestAgent"],
                "subject": "Test Message",
                "body_md": "Test body",
            },
        )

        msg_id = extract_msg_id(result)
        assert msg_id is not None, "Message ID should be returned"

        # Try to read the thread resource with absolute path in project parameter
        # This should work but currently fails with "project parameter is required"
        blocks = await client.read_resource(
            f"resource://thread/{msg_id}?project=/Users/test/backend&include_bodies=true"
        )
        assert blocks, "Should receive resource blocks"
        data = json.loads(blocks[0].text or "{}")
        assert isinstance(data.get("messages"), list) and data["messages"], "Should contain messages"
        # include_bodies=true ⇒ at least one message has body_md
        # Check if body_md key exists in any message dict
        assert any("body_md" in m for m in data["messages"]), (
            f"Expected body_md in messages when include_bodies=true, got: {json.dumps(data, indent=2)}"
        )
        assert any(
            (m.get("subject") == "Test Message") or ("Test body" in (m.get("body_md") or "")) for m in data["messages"]
        )


@pytest.mark.asyncio
async def test_thread_resource_with_url_encoded_path(isolated_env):
    """Test that thread resource handles URL-encoded project paths."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Create a project with spaces in the path (requires URL encoding)
        await client.call_tool("ensure_project", {"human_key": "/Users/test/my project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "/Users/test/my project", "program": "x", "model": "y", "name": "TestAgent"},
        )

        # Send a test message
        result = await client.call_tool(
            "send_message",
            {
                "project_key": "/Users/test/my project",
                "sender_name": "TestAgent",
                "to": ["TestAgent"],
                "subject": "Test Message",
                "body_md": "Test body",
            },
        )

        msg_id = extract_msg_id(result)
        assert msg_id is not None

        # Try with URL-encoded path (%20 for space)
        blocks = await client.read_resource(
            f"resource://thread/{msg_id}?project=/Users/test/my%20project&include_bodies=false"
        )
        assert blocks
        data = json.loads(blocks[0].text or "{}")
        assert isinstance(data.get("messages"), list) and data["messages"]
        # include_bodies=false ⇒ messages should not include body_md
        assert all("body_md" not in m for m in data["messages"])
