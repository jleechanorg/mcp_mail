"""Test thread resource query parameter parsing."""
from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


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

        # Extract message ID from result
        def _get(field: str, obj):
            if isinstance(obj, dict):
                return obj.get(field)
            return getattr(obj, field, None)

        # The send_message result has structure: { "deliveries": [{ "payload": { "id": ..., ...}, ...}], ...}
        deliveries = _get("deliveries", result.data) or []
        if deliveries:
            payload = _get("payload", deliveries[0])
            msg_id = _get("id", payload) if payload else None
        else:
            msg_id = None
        assert msg_id is not None, "Message ID should be returned"

        # Try to read the thread resource with absolute path in project parameter
        # This should work but currently fails with "project parameter is required"
        blocks = await client.read_resource(
            f"resource://thread/{msg_id}?project=/Users/test/backend&include_bodies=true"
        )
        assert blocks, "Should receive resource blocks"
        text = blocks[0].text or ""
        assert "messages" in text, "Should contain messages"
        assert "Test Message" in text or "Test body" in text, "Should contain message content"


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

        def _get(field: str, obj):
            if isinstance(obj, dict):
                return obj.get(field)
            return getattr(obj, field, None)

        # The send_message result has structure: { "deliveries": [{ "payload": { "id": ..., ...}, ...}], ...}
        deliveries = _get("deliveries", result.data) or []
        if deliveries:
            payload = _get("payload", deliveries[0])
            msg_id = _get("id", payload) if payload else None
        else:
            msg_id = None
        assert msg_id is not None

        # Try with URL-encoded path (%20 for space)
        blocks = await client.read_resource(
            f"resource://thread/{msg_id}?project=/Users/test/my%20project&include_bodies=false"
        )
        assert blocks
        assert "messages" in (blocks[0].text or "")
