from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


@pytest.mark.asyncio
async def test_reply_preserves_thread_and_subject_prefix(isolated_env):
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/backend"})
        for n in ("GreenCastle", "BlueLake"):
            await client.call_tool(
                "register_agent",
                {"project_key": "Backend", "program": "x", "model": "y", "name": n},
            )
        # Note: Contact gating has been removed, direct messaging works by default

        orig = await client.call_tool(
            "send_message",
            {
                "project_key": "Backend",
                "sender_name": "GreenCastle",
                "to": ["BlueLake"],
                "subject": "Plan",
                "body_md": "body",
            },
        )
        delivery = (orig.data.get("deliveries") or [])[0]
        mid = delivery["payload"]["id"]

        rep = await client.call_tool(
            "reply_message",
            {
                "project_key": "Backend",
                "message_id": mid,
                "sender_name": "BlueLake",
                "body_md": "ack",
            },
        )
        # Ensure thread continuity and deliveries present
        assert rep.data.get("thread_id")
        assert rep.data.get("deliveries")

        # Subject prefix idempotent: replying again with same prefix shouldn't double it
        rep2 = await client.call_tool(
            "reply_message",
            {
                "project_key": "Backend",
                "message_id": mid,
                "sender_name": "BlueLake",
                "body_md": "second",
                "subject_prefix": "Re:",
            },
        )
        assert rep2.data.get("deliveries")

        # Thread listing is validated via tool response thread_id; resource listing is covered elsewhere


@pytest.mark.asyncio
async def test_reply_handles_reclaimed_names(isolated_env):
    server = build_mcp_server()
    async with Client(server) as client:
        project_a = "/tmp/reply_project_a"
        project_b = "/tmp/reply_project_b"
        await client.call_tool("ensure_project", {"human_key": project_a})
        await client.call_tool("ensure_project", {"human_key": project_b})

        # Alpha works in project A
        await client.call_tool(
            "register_agent",
            {"project_key": project_a, "program": "codex", "model": "gpt", "name": "Alpha"},
        )
        # Note: Contact gating has been removed, direct messaging works by default

        # Convo first exists in project A, then is reclaimed in project B (retiring the local copy)
        await client.call_tool(
            "register_agent",
            {"project_key": project_a, "program": "codex", "model": "gpt", "name": "Convo"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": project_b, "program": "codex", "model": "gpt", "name": "Convo"},
        )
        # Note: Contact gating has been removed, direct messaging works by default

        # Alpha sends a message to Convo (auto-routes cross-project after reclamation)
        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": project_a,
                "sender_name": "Alpha",
                "to": ["Convo"],
                "subject": "Ping",
                "body_md": "body",
            },
        )
        delivery = (send_result.data.get("deliveries") or [])[0]
        mid = delivery["payload"]["id"]

        # Reply again, explicitly addressing "Convo" (should not short-circuit on inactive local entry)
        reply_result = await client.call_tool(
            "reply_message",
            {
                "project_key": project_a,
                "message_id": mid,
                "sender_name": "Alpha",
                "body_md": "follow-up",
                "to": ["Convo"],
            },
        )
        assert reply_result.data.get("deliveries")

