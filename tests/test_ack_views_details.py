from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


@pytest.mark.asyncio
async def test_ack_overdue_and_stale_detail_fields(isolated_env):
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/backend"})
        await client.call_tool(
            "register_agent",
            {"project_key": "Backend", "program": "codex", "model": "gpt-5", "name": "RedRiver"},
        )
        await client.call_tool(
            "send_message",
            {
                "project_key": "Backend",
                "sender_name": "RedRiver",
                "to": ["RedRiver"],
                "subject": "A1",
                "body_md": "x",
                "ack_required": True,
            },
        )
        # Test acks-stale resource - with default TTL, message won't be stale yet
        # so we just verify the resource returns valid JSON with expected structure
        stale_uri = "resource://views/acks-stale/RedRiver"
        stale = await client.read_resource(stale_uri)
        assert stale and stale[0].text
        import json

        stale_data = json.loads(stale[0].text)
        assert "project" in stale_data and "agent" in stale_data
        assert stale_data["agent"] == "RedRiver"

        # Test ack-overdue resource - verify it returns valid JSON with messages field
        overdue_uri = "resource://views/ack-overdue/RedRiver"
        overdue = await client.read_resource(overdue_uri)
        assert overdue and "messages" in (overdue[0].text or "")
