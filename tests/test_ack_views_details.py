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
        # acks-stale should return structured response with ttl_seconds and messages fields
        # Note: Client(server) test harness strips query params, so default TTL will apply
        stale_uri = "resource://views/acks-stale/RedRiver?project=Backend"
        stale = await client.read_resource(stale_uri)
        assert stale and "ttl_seconds" in (stale[0].text or "")
        assert '"messages"' in (stale[0].text or "")

        # ack-overdue should return structured response with messages field
        overdue_uri = "resource://views/ack-overdue/RedRiver?project=Backend"
        overdue = await client.read_resource(overdue_uri)
        assert overdue and '"messages"' in (overdue[0].text or "")
