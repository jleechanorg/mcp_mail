"""Integration tests for search_mailbox tool showing real-world usage patterns.

These tests demonstrate how agents would use search_mailbox in practice to:
- Learn from prior conversations before starting work
- Discover existing solutions to avoid duplication
- Find relevant context from other agents
- Coordinate multi-agent workflows
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
async def test_agent_learns_from_prior_work_before_implementation(isolated_env):
    """Test real-world scenario: Agent searches for prior work before implementing a feature."""
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup project and agents
        await client.call_tool("ensure_project", {"human_key": "/my-app"})

        # Alice implemented authentication last week
        await client.call_tool(
            "register_agent",
            {"project_key": "my-app", "program": "claude", "model": "sonnet", "name": "Alice"},
        )

        # Bob is starting today
        await client.call_tool(
            "register_agent",
            {"project_key": "my-app", "program": "claude", "model": "sonnet", "name": "Bob"},
        )

        # Alice's historical messages about authentication
        await client.call_tool(
            "send_message",
            {
                "project_key": "my-app",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Authentication implementation complete",
                "body_md": """I've implemented JWT authentication with the following approach:

1. Used bcrypt for password hashing
2. JWT tokens with 24-hour expiration
3. Refresh token mechanism for seamless re-auth
4. Rate limiting on login endpoint (5 attempts per 15 minutes)

Key lessons learned:
- Don't store JWT secrets in .env file - use environment-specific secrets manager
- Add token blacklist for logout functionality
- Test with multiple concurrent sessions

The implementation is in `src/auth/jwt.py` and tests in `tests/auth/test_jwt.py`.""",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "my-app",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Authentication gotcha - session handling",
                "body_md": """Found a subtle bug in the authentication flow:

The JWT middleware was not properly handling expired tokens. It would throw an exception
instead of returning 401. Fixed by adding proper exception handling in the middleware.

Also added comprehensive tests for edge cases like:
- Expired tokens
- Malformed tokens
- Tokens with invalid signatures
- Missing authorization header""",
            },
        )

        # Now Bob starts work on a related feature
        # BEST PRACTICE: Search before implementing
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "my-app",
                "query": "authentication",
                "requesting_agent": "Bob",
                "limit": 10,
            },
        )

        results = _extract_result(search_result)

        # Bob should find Alice's work
        assert len(results) == 2, f"Should find 2 messages about authentication, found {len(results)}"

        # Verify Bob found the key information
        found_implementation = False
        found_gotcha = False

        for msg in results:
            if "implementation complete" in msg["subject"].lower():
                found_implementation = True
                assert "bcrypt" in msg["body_md"]
                assert "JWT" in msg["body_md"]
                assert "lessons learned" in msg["body_md"].lower()
            if "gotcha" in msg["subject"].lower():
                found_gotcha = True
                assert "expired tokens" in msg["body_md"]

        assert found_implementation, "Should find Alice's implementation message"
        assert found_gotcha, "Should find Alice's gotcha message"

        # Bob now knows:
        # 1. Authentication is already implemented
        # 2. Where the code is located
        # 3. Common pitfalls to avoid
        # 4. Testing strategy
        # This saves hours of duplicate work!


@pytest.mark.asyncio
async def test_multi_agent_coordination_via_search(isolated_env):
    """Test agents coordinating work by searching for related messages."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/backend"})

        # Multiple agents working on different parts
        for agent_name in ["Alice", "Bob", "Charlie", "Diana"]:
            await client.call_tool(
                "register_agent",
                {
                    "project_key": "backend",
                    "program": "claude",
                    "model": "sonnet",
                    "name": agent_name,
                },
            )

        # Alice reports a database performance issue
        await client.call_tool(
            "send_message",
            {
                "project_key": "backend",
                "sender_name": "Alice",
                "to": ["Bob", "Charlie"],
                "subject": "Database queries slow on user table",
                "body_md": "Noticing 2-3 second query times on user table. Need to investigate indexing.",
            },
        )

        # Bob adds database indexes
        await client.call_tool(
            "send_message",
            {
                "project_key": "backend",
                "sender_name": "Bob",
                "to": ["Alice", "Charlie"],
                "subject": "Added indexes to user table",
                "body_md": "Added composite index on (email, status) and single index on created_at. Queries now < 100ms.",
            },
        )

        # Charlie optimizes queries
        await client.call_tool(
            "send_message",
            {
                "project_key": "backend",
                "sender_name": "Charlie",
                "to": ["Alice", "Bob"],
                "subject": "Optimized N+1 query problem in user endpoint",
                "body_md": "Used select_related to reduce 50+ queries to 2 queries. API response time improved from 5s to 200ms.",
            },
        )

        # Diana starts work on user feature - searches for context
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "backend",
                "query": "user",
                "requesting_agent": "Diana",
            },
        )

        results = _extract_result(search_result)

        # Diana should find all the context
        assert len(results) == 3, f"Should find all 3 messages about user table work, found {len(results)}"

        # All messages should be in global inbox (visible to all)
        for msg in results:
            assert msg["in_global_inbox"], "All coordination messages should be in global inbox"

        # Diana can now understand:
        # - There were performance issues (context)
        # - Bob added indexes (solution 1)
        # - Charlie optimized queries (solution 2)
        # - Combined work improved performance dramatically
        # She won't accidentally revert optimizations or duplicate work


@pytest.mark.asyncio
async def test_search_finds_error_patterns_and_solutions(isolated_env):
    """Test searching for error patterns and their solutions."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/frontend"})

        for agent_name in ["Alex", "Taylor"]:
            await client.call_tool(
                "register_agent",
                {"project_key": "frontend", "program": "cursor", "model": "gpt-4", "name": agent_name},
            )

        # Alex encounters and solves errors
        await client.call_tool(
            "send_message",
            {
                "project_key": "frontend",
                "sender_name": "Alex",
                "to": ["Taylor"],
                "subject": "Fixed: TypeError in React component",
                "body_md": """Encountered TypeError: Cannot read property 'map' of undefined

Root cause: API response sometimes returns null instead of empty array.

Solution: Added null coalescing operator: `data?.items ?? []`

This pattern should be used for all array operations on API data.""",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "frontend",
                "sender_name": "Alex",
                "to": ["Taylor"],
                "subject": "Fixed: Memory leak in useEffect",
                "body_md": """Memory leak detected in component with WebSocket connection.

Issue: useEffect didn't clean up WebSocket on unmount.

Solution: Always return cleanup function from useEffect:
```javascript
useEffect(() => {
  const ws = new WebSocket(url);
  return () => ws.close();
}, [url]);
```""",
            },
        )

        # Taylor encounters similar error - searches first
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "frontend",
                "query": "TypeError",
                "requesting_agent": "Taylor",
            },
        )

        results = _extract_result(search_result)

        assert len(results) >= 1, f"Should find TypeError solution, found {len(results)}"

        found_solution = any("Cannot read property" in msg.get("body_md", "") for msg in results)
        assert found_solution, "Should find Alex's TypeError solution"

        # Taylor can now apply the same fix pattern instead of debugging from scratch


@pytest.mark.asyncio
async def test_search_with_phrase_queries_for_exact_matches(isolated_env):
    """Test using phrase queries to find exact error messages or commands."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/devops"})
        await client.call_tool(
            "register_agent",
            {"project_key": "devops", "program": "claude", "model": "opus", "name": "DevOps"},
        )

        # Messages with similar words but different meanings
        await client.call_tool(
            "send_message",
            {
                "project_key": "devops",
                "sender_name": "DevOps",
                "to": ["DevOps"],
                "subject": "Docker build failed",
                "body_md": "Build process error: docker build failed with exit code 137",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "devops",
                "sender_name": "DevOps",
                "to": ["DevOps"],
                "subject": "Docker deployment successful",
                "body_md": "Successfully built and deployed the container. Build process completed.",
            },
        )

        await client.call_tool(
            "send_message",
            {
                "project_key": "devops",
                "sender_name": "DevOps",
                "to": ["DevOps"],
                "subject": "Python build script updated",
                "body_md": "Updated build.py to handle docker container creation more efficiently.",
            },
        )

        # Search for exact phrase "docker build failed"
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "devops",
                "query": '"docker build failed"',
                "requesting_agent": "DevOps",
            },
        )

        results = _extract_result(search_result)

        # Should find only the exact match
        assert len(results) == 1, "Phrase query should find only exact match"
        assert "exit code 137" in results[0]["body_md"]


@pytest.mark.asyncio
async def test_search_across_long_conversation_history(isolated_env):
    """Test search effectiveness with large message history."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/big-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "big-project", "program": "claude", "model": "sonnet", "name": "Agent1"},
        )

        # Create many messages
        topics = [
            ("API", "REST API endpoints", "Implemented GET /users and POST /users endpoints"),
            ("Database", "Database migration", "Added migration for user_profiles table"),
            ("API", "API authentication", "Added OAuth2 authentication to API"),
            ("Frontend", "React components", "Created UserProfile component"),
            ("Database", "Database indexing", "Optimized database queries with indexes"),
            ("API", "API rate limiting", "Implemented rate limiting for API endpoints"),
            ("Testing", "Unit tests", "Added unit tests for user service"),
            ("API", "API documentation", "Updated Swagger documentation for new endpoints"),
            ("Frontend", "CSS styling", "Applied new design system to components"),
            ("Database", "Database backup", "Set up automated database backups"),
        ]

        for i, (category, subject, body) in enumerate(topics):
            await client.call_tool(
                "send_message",
                {
                    "project_key": "big-project",
                    "sender_name": "Agent1",
                    "to": ["Agent1"],
                    "subject": f"{category}: {subject} #{i}",
                    "body_md": body,
                },
            )

        # Search for specific topic
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "big-project",
                "query": "API",
                "requesting_agent": "Agent1",
                "limit": 5,
            },
        )

        results = _extract_result(search_result)

        # Should find API-related messages (there are 4 API messages, so should get 4)
        assert len(results) >= 4, f"Should find at least 4 API messages with limit 5, found {len(results)}"
        assert all("API" in msg["subject"] for msg in results), "All results should be API-related"

        # Search for more specific query
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "big-project",
                "query": "authentication",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)

        # Should find authentication message
        assert len(results) >= 1, "Should find at least 1 authentication message"
        assert any(
            "authentication" in msg["subject"].lower() or "authentication" in msg["body_md"].lower() for msg in results
        )


@pytest.mark.asyncio
async def test_empty_project_search(isolated_env):
    """Test search behavior on a project with no messages."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/empty-project"})
        await client.call_tool(
            "register_agent",
            {"project_key": "empty-project", "program": "claude", "model": "sonnet", "name": "Agent1"},
        )

        # Search with no messages
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "empty-project",
                "query": "anything",
                "requesting_agent": "Agent1",
            },
        )

        results = _extract_result(search_result)
        assert len(results) == 0, "Should return empty list for empty project"


@pytest.mark.asyncio
async def test_search_respects_agent_filter_in_multi_agent_project(isolated_env):
    """Test that agent filter properly restricts search results."""
    server = build_mcp_server()
    async with Client(server) as client:
        await client.call_tool("ensure_project", {"human_key": "/team-project"})

        # Create multiple agents
        for agent_name in ["Alice", "Bob", "Charlie"]:
            await client.call_tool(
                "register_agent",
                {"project_key": "team-project", "program": "claude", "model": "sonnet", "name": agent_name},
            )

        # Alice and Bob discuss feature A
        await client.call_tool(
            "send_message",
            {
                "project_key": "team-project",
                "sender_name": "Alice",
                "to": ["Bob"],
                "subject": "Feature A implementation plan",
                "body_md": "Let's implement feature A with approach X",
            },
        )

        # Bob and Charlie discuss feature A (different perspective)
        await client.call_tool(
            "send_message",
            {
                "project_key": "team-project",
                "sender_name": "Bob",
                "to": ["Charlie"],
                "subject": "Feature A technical details",
                "body_md": "Here are the technical details for feature A implementation",
            },
        )

        # Alice and Charlie discuss feature B (unrelated)
        await client.call_tool(
            "send_message",
            {
                "project_key": "team-project",
                "sender_name": "Alice",
                "to": ["Charlie"],
                "subject": "Feature B requirements",
                "body_md": "Feature B needs different implementation",
            },
        )

        # Search all messages about "feature"
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "team-project",
                "query": "feature implementation",
            },
        )

        all_results = _extract_result(search_result)
        assert len(all_results) == 3, "Should find all 3 feature-related messages"

        # Search only Bob's involvement in "feature"
        search_result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": "team-project",
                "query": "feature implementation",
                "agent_filter": "Bob",
            },
        )

        bob_results = _extract_result(search_result)

        # Should only find messages where Bob is sender or recipient
        assert len(bob_results) == 2, "Should find only Bob's 2 messages about features"

        for msg in bob_results:
            assert (
                msg["from"] == "Bob" or "Bob" in msg["to"] or "Bob" in msg.get("cc", []) or "Bob" in msg.get("bcc", [])
            ), "Bob should be involved in all filtered results"
