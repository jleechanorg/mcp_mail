"""Integration tests for search_mailbox with .mcp_mail/ storage.

Tests the search_mailbox tool with the default .mcp_mail/ storage backend to ensure:
- SQLite FTS5 search works correctly with git-backed message storage
- .mcp_mail/ directory structure is created properly
- Search results respect project isolation
- Concurrent searches don't cause race conditions
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from mcp_agent_mail import config as _config
from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import ensure_schema, reset_database_state


def extract_results(result):
    """Helper to extract results from fastmcp CallToolResult."""
    if hasattr(result, "structured_content") and result.structured_content:
        return result.structured_content.get("result", result.data if hasattr(result, "data") else [])
    if hasattr(result, "data"):
        return result.data
    return []


@pytest.fixture
async def mcp_mail_search_env(tmp_path, monkeypatch):
    """Set up .mcp_mail/ storage for search integration tests."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Set up .mcp_mail/ as storage location
    mcp_mail_dir = project_dir / ".mcp_mail"
    mcp_mail_dir.mkdir()

    # Configure environment to use .mcp_mail/ storage
    monkeypatch.setenv("STORAGE_ROOT", str(mcp_mail_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{mcp_mail_dir}/storage.sqlite3")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test-agent")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

    # Clear caches and reset DB state so the new env vars take effect
    _config.clear_settings_cache()
    reset_database_state()

    # Initialize database (creates FTS5 tables)
    await ensure_schema()

    yield {
        "project_dir": project_dir,
        "storage_dir": mcp_mail_dir,
        "db_path": mcp_mail_dir / "storage.sqlite3",
    }

    # Cleanup
    _config.clear_settings_cache()
    reset_database_state()


@pytest.mark.asyncio
async def test_search_with_mcp_mail_storage_structure(mcp_mail_search_env):
    """Test that search_mailbox works with .mcp_mail/ storage backend."""
    storage_dir = mcp_mail_search_env["storage_dir"]

    server = build_mcp_server()
    async with Client(server) as client:
        # Register agents and send messages
        await client.call_tool(
            "register_agent",
            {
                "project_key": "test-proj",
                "program": "claude",
                "model": "sonnet",
                "name": "Alice",
            },
        )

        await client.call_tool(
            "register_agent",
            {
                "project_key": "test-proj",
                "program": "claude",
                "model": "sonnet",
                "name": "Bob",
            },
        )

        # Send a test message
        await client.call_tool(
            "send_message",
            {
                "project_key": "test-proj",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "FTS5 search test",
                "body_md": "Testing fulltext search with mcp_mail storage backend.",
            },
        )

        # Search for the message
        result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "test-proj",
                "query": "fulltext search",
                "requesting_agent": "Bob",
                "limit": 10,
            },
        )

    results = extract_results(result)
    assert len(results) >= 1, f"Should find at least one message, got {len(results)}"
    assert any("search" in r["subject"].lower() for r in results)

    # Verify .mcp_mail/ structure was created
    assert storage_dir.exists(), ".mcp_mail/ should exist"
    assert (storage_dir / "storage.sqlite3").exists(), "SQLite database should exist"
    assert (storage_dir / "projects").exists(), "projects/ directory should exist"


@pytest.mark.asyncio
async def test_search_respects_project_isolation_in_mcp_mail(mcp_mail_search_env):
    """Test that search results are isolated by project in .mcp_mail/ storage."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Set up two projects
        for project in ["project-a", "project-b"]:
            await client.call_tool(
                "register_agent",
                {
                    "project_key": project,
                    "program": "claude",
                    "model": "sonnet",
                    "name": "Agent",
                },
            )

            await client.call_tool(
                "send_message",
                {
                    "project_key": project,
                    "sender_name": "Agent",
                    "to": ["Agent"],
                    "subject": f"Project {project} message",
                    "body_md": f"This is a unique message for {project} about security implementation",
                },
            )

        # Search in project-a should only find project-a messages
        result_a = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "project-a",
                "query": "security implementation",
                "requesting_agent": "Agent",
                "limit": 10,
            },
        )

        results_a = extract_results(result_a)
        assert len(results_a) == 1, "Should find exactly one message in project-a"
        assert "project-a" in results_a[0]["subject"].lower(), "Should only find project-a message"

        # Search in project-b should only find project-b messages
        result_b = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "project-b",
                "query": "security implementation",
                "requesting_agent": "Agent",
                "limit": 10,
            },
        )

        results_b = extract_results(result_b)
        assert len(results_b) == 1, "Should find exactly one message in project-b"
        assert "project-b" in results_b[0]["subject"].lower(), "Should only find project-b message"


@pytest.mark.asyncio
async def test_concurrent_searches_on_mcp_mail_storage(mcp_mail_search_env):
    """Test concurrent search operations don't cause race conditions."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Register agents
        await client.call_tool(
            "register_agent",
            {
                "project_key": "concurrent-test",
                "program": "claude",
                "model": "sonnet",
                "name": "Searcher",
            },
        )

        # Send multiple messages
        for i in range(10):
            await client.call_tool(
                "send_message",
                {
                    "project_key": "concurrent-test",
                    "sender_name": "Searcher",
                    "to": ["Searcher"],
                    "subject": f"Test message {i}",
                    "body_md": f"Concurrent search test message number {i}",
                },
            )

        # Perform 10 concurrent searches
        async def search():
            return await client.call_tool(
                "search_mailbox",
                {
                    "project_key": "concurrent-test",
                    "query": "concurrent search test",
                    "requesting_agent": "Searcher",
                    "limit": 20,
                },
            )

        results_list = await asyncio.gather(*[search() for _ in range(10)])

    # All searches should succeed and return consistent results
    for result in results_list:
        results = extract_results(result)
        assert len(results) >= 5, "Each search should find multiple messages"


@pytest.mark.asyncio
async def test_search_agent_filter_complete_recipients(mcp_mail_search_env):
    """Test that agent filter shows complete recipient lists in .mcp_mail/ storage."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Register agents
        for name in ["Alice", "Bob", "Charlie", "Diana"]:
            await client.call_tool(
                "register_agent",
                {
                    "project_key": "filter-test",
                    "program": "claude",
                    "model": "sonnet",
                    "name": name,
                },
            )

        # Alice sends to Bob, CC Charlie and Diana
        await client.call_tool(
            "send_message",
            {
                "project_key": "filter-test",
                "sender_name": "Alice",
                "to": ["Bob"],
                "cc": ["Charlie", "Diana"],
                "subject": "Multi-recipient message about testing",
                "body_md": "This message has multiple recipients in to and cc.",
            },
        )

        # Search with agent filter for Bob
        result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "filter-test",
                "query": "testing",
                "requesting_agent": "Alice",
                "agent_filter": "Bob",
                "limit": 10,
            },
        )

        results = extract_results(result)
        assert len(results) >= 1, "Should find message involving Bob"

        # Verify complete recipient list is shown (not just Bob)
        msg = results[0]
        assert "Bob" in msg["to"], "Bob should be in to list"
        assert "Charlie" in msg["cc"], "Charlie should be in cc list"
        assert "Diana" in msg["cc"], "Diana should be in cc list"
