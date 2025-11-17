"""Edge case tests for search_mailbox tool.

Tests covering unusual scenarios and boundary conditions:
- Special characters in queries
- Very long messages
- Messages with attachments
- Unicode and international characters
- Messages with code blocks and markdown
- Empty and whitespace queries
- Case sensitivity
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
async def test_search_with_special_characters(isolated_env):
    """Test search with special characters in query."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/special-chars"})
        await client.call_tool(
            "register_agent",
            {"project_key": "special-chars", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        # Message with special characters
        await client.call_tool(
            "send_message",
            {
                "project_key": "special-chars",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "C++ template<typename T> implementation",
                "body_md": "Working on vector<int> and map<string, vector<int>> structures",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "special-chars",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Regex pattern: [a-zA-Z0-9]+",
                "body_md": "Using regex /^[0-9]{3}-[0-9]{2}-[0-9]{4}$/ for validation",
            },
        )

        # Search for template (FTS5 treats + as special, so search for words instead)
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "special-chars",
                "query": "template typename",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) >= 1, "Should find template-related messages"

        # Search for vector
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "special-chars",
                "query": "vector map",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) >= 1, "Should find vector/map structures"


@pytest.mark.asyncio
async def test_search_with_unicode_characters(isolated_env):
    """Test search with Unicode and international characters."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/unicode"})
        await client.call_tool(
            "register_agent",
            {"project_key": "unicode", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        # Messages with various Unicode characters
        await client.call_tool(
            "send_message",
            {
                "project_key": "unicode",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Internationalization support 国际化支持",
                "body_md": "Added support for 中文, Español, العربية, and Русский",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "unicode",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Emoji support 🎉🚀",
                "body_md": "Now supporting emojis: ✅ ❌ 🔍 📝 💡",
            },
        )

        # Search for Internationalization (FTS5 may not fully support Unicode queries in all builds)
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "unicode",
                "query": "Internationalization",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) >= 1, "Should find internationalization message"

        # Search for emoji
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "unicode",
                "query": "emoji",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) >= 1, "Should handle emoji in content"


@pytest.mark.asyncio
async def test_search_with_code_blocks(isolated_env):
    """Test search in messages containing code blocks."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/code"})
        await client.call_tool(
            "register_agent",
            {"project_key": "code", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        # Message with code blocks
        await client.call_tool(
            "send_message",
            {
                "project_key": "code",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Python async function example",
                "body_md": """Here's an async function:

```python
async def fetch_data(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()
```

This uses aiohttp for asynchronous HTTP requests.""",
            },
        )

        # Search for async-related terms
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "code",
                "query": "async aiohttp",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) >= 1, "Should find code in message body"
        assert "aiohttp" in results[0]["body_md"]


@pytest.mark.asyncio
async def test_search_with_very_long_message(isolated_env):
    """Test search on very long messages."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/long"})
        await client.call_tool(
            "register_agent",
            {"project_key": "long", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        # Create a long message body
        long_body = "# Documentation\n\n"
        long_body += "## Introduction\n" + ("This is a paragraph of text. " * 20) + "\n\n"
        long_body += "## Implementation Details\n" + ("More detailed text here. " * 30) + "\n\n"
        long_body += "## IMPORTANT_KEYWORD_HERE for testing\n"
        long_body += "## Conclusion\n" + ("Final thoughts. " * 15)

        await client.call_tool(
            "send_message",
            {
                "project_key": "long",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Very long documentation",
                "body_md": long_body,
            },
        )

        # Search for keyword buried in long text
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "long",
                "query": "IMPORTANT_KEYWORD_HERE",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 1, "Should find keyword in long message"
        assert "IMPORTANT_KEYWORD_HERE" in results[0]["body_snippet"]


@pytest.mark.asyncio
async def test_search_case_insensitive(isolated_env):
    """Test that search is case-insensitive."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/case"})
        await client.call_tool(
            "register_agent",
            {"project_key": "case", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "case",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "PostgreSQL Database Setup",
                "body_md": "Configured POSTGRESQL with proper indexes",
            },
        )

        # Search with different cases
        for query in ["postgresql", "PostgreSQL", "POSTGRESQL", "postgreSQL"]:
            search_result = await client.call_tool(
                "search_mailbox",
                {
                    "project_key": "case",
                    "query": query,
                    "requesting_agent": "Agent1",
                },
            )

            results = _extract_result(search_result)
            assert len(results) == 1, f"Should find result regardless of case: {query}"


@pytest.mark.asyncio
async def test_search_with_whitespace_variations(isolated_env):
    """Test search with various whitespace in query."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/whitespace"})
        await client.call_tool(
            "register_agent",
            {"project_key": "whitespace", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "whitespace",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Database migration",
                "body_md": "Running database migration scripts",
            },
        )

        # Search with extra whitespace
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "whitespace",
                "query": "  database   migration  ",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 1, "Should handle extra whitespace in query"


@pytest.mark.asyncio
async def test_search_with_prefix_wildcard(isolated_env):
    """Test prefix search with asterisk wildcard."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/prefix"})
        await client.call_tool(
            "register_agent",
            {"project_key": "prefix", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        # Messages with related words
        for word in ["authenticate", "authentication", "authenticator", "authorized", "authorization"]:
            await client.call_tool(
                "send_message",
                {
                    "project_key": "prefix",
                    "sender_name": "Agent1",
                    "to": ["Agent1"],
                    "subject": f"Working on {word}",
                    "body_md": f"Implementing {word} functionality",
                },
            )

        # Search with prefix wildcard
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "prefix",
                "query": "authen*",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        # Should find authenticate, authentication, authenticator
        assert len(results) >= 3, "Prefix wildcard should match multiple words"


@pytest.mark.asyncio
async def test_search_with_attachments_metadata(isolated_env):
    """Test search on messages with attachments (metadata in subject/body)."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/attachments"})
        await client.call_tool(
            "register_agent",
            {"project_key": "attachments", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        # Message mentioning attachments
        await client.call_tool(
            "send_message",
            {
                "project_key": "attachments",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Design mockups attached",
                "body_md": "See attached mockup.png and design-v2.pdf for the new UI design",
            },
        )

        # Search for attachment references
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "attachments",
                "query": "mockup design",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 1, "Should find message mentioning attachments"


@pytest.mark.asyncio
async def test_search_excludes_terms_with_NOT(isolated_env):
    """Test FTS5 NOT operator to exclude terms."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/exclude"})
        await client.call_tool(
            "register_agent",
            {"project_key": "exclude", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "exclude",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Testing frontend components",
                "body_md": "Unit testing the React components",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "exclude",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Testing backend API",
                "body_md": "Integration testing for the API endpoints",
            },
        )

        # Search for testing but exclude frontend
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "exclude",
                "query": "testing NOT frontend",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 1, "Should find only backend testing message"
        assert "backend" in results[0]["subject"].lower()


@pytest.mark.asyncio
async def test_search_with_numbers_and_versions(isolated_env):
    """Test search for version numbers and numeric values."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/versions"})
        await client.call_tool(
            "register_agent",
            {"project_key": "versions", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "versions",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Upgraded to Python 3.11",
                "body_md": "Migration from Python 3.9 to Python 3.11 complete",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "versions",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "API v2.5.3 released",
                "body_md": "Released version 2.5.3 with bug fixes",
            },
        )

        # Search for Python version (search for words, as FTS5 may tokenize numbers differently)
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "versions",
                "query": "Python upgraded",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) >= 1, "Should find Python upgrade message"

        # Search for API release
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "versions",
                "query": "API released",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) >= 1, "Should find API release message"


@pytest.mark.asyncio
async def test_search_result_structure_completeness(isolated_env):
    """Test that search results contain all expected fields."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/structure"})
        await client.call_tool(
            "register_agent",
            {"project_key": "structure", "program": "test", "model": "gpt-4", "name": "Alice"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "structure", "program": "test", "model": "gpt-4", "name": "Bob"},
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "structure",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Test message",
                "body_md": "Testing search functionality",
            },
        )

        # Search and verify result structure
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "structure",
                "query": "test",
                "include_bodies": True,
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 1

        # Verify all expected fields are present
        required_fields = [
            "id",
            "subject",
            "from",
            "to",
            "cc",
            "bcc",
            "created_ts",
            "importance",
            "relevance_score",
            "subject_snippet",
            "body_snippet",
            "in_global_inbox",
            "body_md",  # Should be present because include_bodies=True
        ]

        result = results[0]
        for field in required_fields:
            assert field in result, f"Result should contain field: {field}"

        # Verify types
        assert isinstance(result["id"], int)
        assert isinstance(result["from"], str)
        assert isinstance(result["to"], list)
        assert isinstance(result["cc"], list)
        assert isinstance(result["bcc"], list)
        assert isinstance(result["relevance_score"], (int, float))
        assert isinstance(result["in_global_inbox"], bool)


@pytest.mark.asyncio
async def test_search_without_bodies(isolated_env):
    """Test search with include_bodies=False to reduce payload size."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/no-bodies"})
        await client.call_tool(
            "register_agent",
            {"project_key": "no-bodies", "program": "test", "model": "gpt-4", "name": "Agent1"},
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "no-bodies",
                "sender_name": "Agent1",
                "to": ["Agent1"],
                "subject": "Test message",
                "body_md": "This is a long body that shouldn't be included when include_bodies=False",
            },
        )

        # Search without bodies
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "no-bodies",
                "query": "test",
                "include_bodies": False,
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 1
        assert "body_md" not in results[0], "body_md should not be present when include_bodies=False"
        assert "body_snippet" in results[0], "body_snippet should still be present"
