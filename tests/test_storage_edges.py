"""Tests for storage edge cases.

NOTE: Most archive-related tests have been removed since local disk message
archiving to .mcp_mail/projects/ has been deleted. These tests now focus on
SQLite-only message storage and inline data URI handling.
"""

from __future__ import annotations

import base64
import contextlib

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


@pytest.mark.asyncio
async def test_data_uri_embed_without_conversion(isolated_env, monkeypatch):
    """Test that inline data URI images are detected in message body."""
    # Disable server conversion so inline images remain as data URIs
    monkeypatch.setenv("CONVERT_IMAGES", "false")
    from mcp_agent_mail import config as _config

    # Intentionally ignore any errors when clearing the settings cache here.
    # This test only needs to exercise the "cache cleared" path; failures in
    # clear_settings_cache() itself are covered elsewhere and would make this
    # setup brittle if we asserted on a broad Exception type.
    with contextlib.suppress(Exception):
        _config.clear_settings_cache()
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/backend"})
        await client.call_tool(
            "register_agent",
            {"project_key": "Backend", "program": "codex", "model": "gpt-5", "name": "BlueLake"},
        )
        # Craft tiny data URI
        payload = base64.b64encode(b"dummy").decode("ascii")
        body = f"Inline ![x](data:image/webp;base64,{payload})"
        res = await client.call_tool(
            "send_message",
            {
                "project_key": "Backend",
                "sender_name": "BlueLake",
                "to": ["BlueLake"],
                "subject": "InlineImg",
                "body_md": body,
                "convert_images": False,
            },
        )
        deliveries = res.data.get("deliveries") or []
        assert deliveries, "Expected at least one delivery"
        attachments = deliveries[0].get("payload", {}).get("attachments") or []
        assert attachments, "Expected at least one attachment"
        assert any(att.get("type") == "inline" for att in attachments)
