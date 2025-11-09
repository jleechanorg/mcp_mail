"""Tests for automatic global inbox scanning when fetching inbox.

When an agent fetches their inbox, they should also see:
1. Messages from global inbox that are addressed to them (to/cc/bcc)
2. Messages from global inbox that mention them in the body
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


def get_global_inbox_name(project_slug: str) -> str:
    """Get project-specific global inbox name."""
    return f"global-inbox-{project_slug}"


def _get(field: str, obj):
    """Get field from dict or object"""
    if isinstance(obj, dict):
        return obj.get(field)
    return getattr(obj, field, None)


def _extract_result(call_result):
    """Extract the actual data from a CallToolResult."""
    if hasattr(call_result, "structured_content") and call_result.structured_content:
        return call_result.structured_content.get("result", call_result.data)
    return call_result.data


@pytest.mark.asyncio
async def test_inbox_includes_direct_messages_to_agent_from_global_inbox(isolated_env):
    """Test that fetch_inbox includes messages addressed to the agent from global inbox."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Charlie"},
        )

        # Alice sends a message to Bob (Charlie is not a recipient)
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Direct to Bob",
                "body_md": "This is for Bob only",
            },
        )

        # Charlie fetches their inbox
        charlie_inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": "Charlie"},
        )

        messages = _extract_result(charlie_inbox)

        # Charlie should NOT see this message since they're not a recipient and not mentioned
        found = any(_get("subject", msg) == "Direct to Bob" for msg in messages)
        assert not found, "Charlie should not see message not addressed to them and not mentioning them"

        # Bob fetches their inbox
        bob_inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": "Bob"},
        )

        bob_messages = _extract_result(bob_inbox)

        # Bob should see the message (they're a direct recipient)
        found = any(_get("subject", msg) == "Direct to Bob" for msg in bob_messages)
        assert found, "Bob should see message addressed to them"


@pytest.mark.asyncio
async def test_inbox_includes_messages_mentioning_agent_from_global_inbox(isolated_env):
    """Test that fetch_inbox includes messages that mention the agent from global inbox."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Charlie"},
        )

        # Alice sends a message to Bob that mentions Charlie
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Discussing Charlie",
                "body_md": "Hey Bob, we should talk to Charlie about the project",
            },
        )

        # Charlie fetches their inbox
        charlie_inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": "Charlie"},
        )

        messages = _extract_result(charlie_inbox)

        # Charlie should see this message because they're mentioned in the body
        found = False
        for msg in messages:
            if _get("subject", msg) == "Discussing Charlie":
                found = True
                # Verify it's marked as from global inbox scan
                source = _get("source", msg)
                assert source == "global_inbox_mention", f"Expected source='global_inbox_mention', got '{source}'"
                break

        assert found, "Charlie should see message mentioning them from global inbox"


@pytest.mark.asyncio
async def test_inbox_includes_cc_messages_from_global_inbox(isolated_env):
    """Test that fetch_inbox includes messages where agent is cc'd from global inbox."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Charlie"},
        )

        # Alice sends a message to Bob, cc Charlie
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "cc": ["Charlie"],
                "subject": "CC'd to Charlie",
                "body_md": "Charlie should see this",
            },
        )

        # Charlie fetches their inbox
        charlie_inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": "Charlie"},
        )

        messages = _extract_result(charlie_inbox)

        # Charlie should see this message (they're cc'd, which means they're already a direct recipient)
        found = any(_get("subject", msg) == "CC'd to Charlie" for msg in messages)
        assert found, "Charlie should see message where they are cc'd"


@pytest.mark.asyncio
async def test_inbox_deduplicates_messages_from_global_inbox(isolated_env):
    """Test that messages are not duplicated when they appear in both regular and global inbox."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Alice sends a message to Bob
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Direct Message",
                "body_md": "Hello Bob",
            },
        )

        # Bob fetches their inbox
        bob_inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": "Bob"},
        )

        messages = _extract_result(bob_inbox)

        # Count how many times the message appears
        count = sum(1 for msg in messages if _get("subject", msg) == "Direct Message")

        # Should appear exactly once (not duplicated from global inbox)
        assert count == 1, f"Message should appear exactly once, but appeared {count} times"


@pytest.mark.asyncio
async def test_inbox_mention_detection_case_insensitive(isolated_env):
    """Test that mention detection is case-insensitive."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Charlie"},
        )

        # Alice sends a message mentioning "charlie" (lowercase)
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "About charlie",
                "body_md": "Let's talk to charlie tomorrow",
            },
        )

        # Charlie fetches their inbox
        charlie_inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": "Charlie"},
        )

        messages = _extract_result(charlie_inbox)

        # Charlie should see this message (case-insensitive mention)
        found = any(_get("subject", msg) == "About charlie" for msg in messages)
        assert found, "Charlie should see message mentioning them (case-insensitive)"


@pytest.mark.asyncio
async def test_inbox_global_scan_respects_limit(isolated_env):
    """Test that global inbox scanning respects the limit parameter."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Bob"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-project", "program": "test", "model": "gpt-4", "name": "Charlie"},
        )

        # Create 5 messages mentioning Charlie
        for i in range(5):
            await client.call_tool(
                "send_message",
                {
                    "project_key": "test-project",
                    "sender_name": "Alice",
                    "to": ["Bob"],
                    "subject": f"Message {i}",
                    "body_md": f"Hey Bob, ask Charlie about issue {i}",
                },
            )

        # Charlie fetches inbox with limit=2
        charlie_inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": "test-project", "agent_name": "Charlie", "limit": 2},
        )

        messages = _extract_result(charlie_inbox)

        # Should get at most 2 messages (respecting limit)
        assert len(messages) <= 2, f"Expected at most 2 messages, got {len(messages)}"
