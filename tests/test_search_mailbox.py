"""Tests for the search_mailbox tool.

Tests cover:
1. Basic FTS5 search functionality
2. Global inbox priority in search results
3. Agent filter to restrict search to specific agents
4. Relevance scoring and result ranking
5. Snippet generation for results
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


def _extract_result(call_result):
    """Extract the actual data from a CallToolResult."""
    if hasattr(call_result, "structured_content") and call_result.structured_content:
        return call_result.structured_content.get("result", call_result.data)
    return call_result.data


@pytest.mark.asyncio
async def test_search_mailbox_basic(isolated_env):
    """Test basic search functionality."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-search"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-search", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-search", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Send messages with different content
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-search",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Authentication implementation",
                "body_md": "Let's implement JWT authentication for the API",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "test-search",
                "sender_name": "Bob",
                "to": ["Alice"],
                "subject": "Database optimization",
                "body_md": "We need to optimize the database queries for better performance",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "test-search",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Bug fix required",
                "body_md": "Found a critical authentication bug that needs immediate attention",
            },
        )

        # Search for "authentication"
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-search",
                "query": "authentication",
                "limit": 10,
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 2, "Should find 2 messages about authentication"

        # Verify results contain expected fields
        for msg in results:
            assert "id" in msg
            assert "subject" in msg
            assert "from" in msg
            assert "to" in msg
            assert "relevance_score" in msg
            assert "subject_snippet" in msg
            assert "body_snippet" in msg
            assert "in_global_inbox" in msg

        # Search for "database"
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-search",
                "query": "database",
                "limit": 10,
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 1, "Should find 1 message about database"
        assert "Database optimization" in results[0]["subject"]


@pytest.mark.asyncio
async def test_search_mailbox_with_agent_filter(isolated_env):
    """Test search with agent filter."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-filter"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-filter", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-filter", "program": "test", "model": "gpt-4", "name": "Bob"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-filter", "program": "test", "model": "gpt-4", "name": "Charlie"},
        )

        # Alice sends to Bob
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-filter",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Feature request",
                "body_md": "Can you implement the new feature?",
            },
        )

        # Bob sends to Charlie
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-filter",
                "sender_name": "Bob",
                "to": ["Charlie"],
                "subject": "Feature design",
                "body_md": "Here's the design for the new feature",
            },
        )

        # Charlie sends to Alice
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-filter",
                "sender_name": "Charlie",
                "to": ["Alice"],
                "subject": "Feature review",
                "body_md": "Please review the feature implementation",
            },
        )

        # Search all messages with "feature"
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-filter",
                "query": "feature",
                "limit": 10,
            },
        )
        results = _extract_result(search_result)
        assert len(results) == 3, "Should find all 3 messages about feature"
        assert (
            sorted(
                results,
                key=lambda x: (
                    0 if x.get("in_global_inbox") else 1,
                    -x.get("relevance_score", 0),
                ),
            )
            == results
        ), "Results should be ordered by global inbox priority then relevance"

        # Search only Alice's messages (sent or received)
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-filter",
                "query": "feature",
                "agent_filter": "Alice",
                "limit": 10,
            },
        )
        results = _extract_result(search_result)
        assert len(results) == 2, "Should find 2 messages involving Alice"

        # Verify Alice is sender or recipient in all results
        for msg in results:
            is_alice_involved = msg["from"] == "Alice" or "Alice" in msg["to"] + msg.get("cc", []) + msg.get("bcc", [])
            assert is_alice_involved, "Alice should be involved in all filtered results"


@pytest.mark.asyncio
async def test_search_mailbox_boolean_operators(isolated_env):
    """Test FTS5 boolean operators (AND, OR, NOT)."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-boolean"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-boolean", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-boolean", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Send messages with different keyword combinations
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-boolean",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Bug fix",
                "body_md": "Fixed the authentication bug in the login module",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "test-boolean",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "New feature",
                "body_md": "Added new authentication feature for OAuth support",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "test-boolean",
                "sender_name": "Bob",
                "to": ["Alice"],
                "subject": "Error report",
                "body_md": "Found an error in the database connection handling",
            },
        )

        # Search with AND operator
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-boolean",
                "query": "authentication AND bug",
                "limit": 10,
            },
        )
        results = _extract_result(search_result)
        assert len(results) == 1, "Should find 1 message with both authentication AND bug"
        assert "Bug fix" in results[0]["subject"]

        # Search with OR operator
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-boolean",
                "query": "bug OR error",
                "limit": 10,
            },
        )
        results = _extract_result(search_result)
        assert len(results) == 2, "Should find 2 messages with bug OR error"

        # Search with NOT operator
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-boolean",
                "query": "authentication NOT bug",
                "limit": 10,
            },
        )
        results = _extract_result(search_result)
        assert len(results) == 1, "Should exclude messages mentioning bug"
        assert "New feature" in results[0]["subject"]

        # Search with phrase query
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-boolean",
                "query": '"authentication bug"',
                "limit": 10,
            },
        )
        results = _extract_result(search_result)
        assert len(results) == 1, "Phrase query should return exact match"
        assert "Bug fix" in results[0]["subject"]

        # Search with prefix query
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-boolean",
                "query": "auth*",
                "limit": 10,
            },
        )
        results = _extract_result(search_result)
        assert len(results) == 2, "Prefix query should match authentication variants"


@pytest.mark.asyncio
async def test_search_mailbox_global_inbox_priority(isolated_env):
    """Test that global inbox messages are prioritized in search results."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-priority"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-priority", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-priority", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Send messages (all will be in global inbox automatically)
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-priority",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Test message one",
                "body_md": "Testing search functionality",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "test-priority",
                "sender_name": "Bob",
                "to": ["Alice"],
                "subject": "Test message two",
                "body_md": "More testing of search features",
            },
        )

        # Search for "testing"
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-priority",
                "query": "testing",
                "limit": 10,
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 2, "Should find 2 messages"

        # All messages should be in global inbox
        for msg in results:
            assert msg["in_global_inbox"] is True, "All messages should be in global inbox"


@pytest.mark.asyncio
async def test_search_mailbox_no_results(isolated_env):
    """Test search with no matching results."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-empty"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-empty", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-empty", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Send a message
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-empty",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Hello",
                "body_md": "Just saying hi",
            },
        )

        # Search for non-existent term
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-empty",
                "query": "nonexistentterm12345",
                "limit": 10,
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 0, "Should find no messages"


@pytest.mark.asyncio
async def test_search_mailbox_limit(isolated_env):
    """Test search limit parameter."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool("ensure_project", {"human_key": "/test-limit"})
        await client.call_tool(
            "register_agent",
            {"project_key": "test-limit", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "test-limit", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        # Send multiple messages with same keyword
        for i in range(10):
            await client.call_tool(
                "send_message",
                {
                    "project_key": "test-limit",
                    "sender_name": "Alice",
                    "to": ["Bob"],
                    "subject": f"Update {i}",
                    "body_md": f"Testing message number {i}",
                },
            )

        # Search with limit=5
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-limit",
                "query": "testing",
                "limit": 5,
                "include_bodies": False,
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 5, "Should return only 5 results due to limit"
        assert all("body_md" not in msg for msg in results), "Bodies should be omitted when include_bodies=False"
