"""Tests for agent discovery UX improvements.

This test suite covers:
1. _find_similar_agents function for agent name suggestions
2. whois tool with global lookup fallback and suggestions
3. whois commit history using correct project on global fallback
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import _find_similar_agents, build_mcp_server


class TestFindSimilarAgents:
    """Tests for the _find_similar_agents helper function."""

    @pytest.mark.asyncio
    async def test_exact_case_insensitive_match(self, isolated_env):
        """Test Strategy 1: Case-insensitive exact matches."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "BlueLake",
                },
            )

            # Search with different case should find the agent
            suggestions = await _find_similar_agents("bluelake")
            assert "BlueLake" in suggestions

            suggestions = await _find_similar_agents("BLUELAKE")
            assert "BlueLake" in suggestions

    @pytest.mark.asyncio
    async def test_prefix_matches(self, isolated_env):
        """Test Strategy 2: Agent names starting with the input."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "BlueLakeAgent",
                },
            )

            # Searching "Blue" should find "BlueLakeAgent"
            suggestions = await _find_similar_agents("Blue")
            assert "BlueLakeAgent" in suggestions

    @pytest.mark.asyncio
    async def test_reverse_prefix_matches(self, isolated_env):
        """Test Strategy 3: Agent names that are prefixes of the input."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "Blue",
                },
            )

            # Searching "BlueLake" should find "Blue" (Blue is prefix of BlueLake)
            suggestions = await _find_similar_agents("BlueLake")
            assert "Blue" in suggestions

    @pytest.mark.asyncio
    async def test_substring_matches(self, isolated_env):
        """Test Strategy 4: Agent names containing the input."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "TheBlueLakeAgent",
                },
            )

            # Searching "Lake" should find "TheBlueLakeAgent" (Lake is substring)
            suggestions = await _find_similar_agents("Lake")
            assert "TheBlueLakeAgent" in suggestions

    @pytest.mark.asyncio
    async def test_reverse_substring_matches(self, isolated_env):
        """Test Strategy 5: Agent names that are substrings of the input."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "Blue",
                },
            )

            # Searching "BlueLakeExtra" should find "Blue" (Blue is substring of input)
            suggestions = await _find_similar_agents("BlueLakeExtra")
            assert "Blue" in suggestions

    @pytest.mark.asyncio
    async def test_empty_input_returns_no_suggestions(self, isolated_env):
        """Ensure empty or whitespace-only input short-circuits without DB work."""
        # No projects or agents needed; function should return early
        suggestions = await _find_similar_agents("   ")
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_limit_parameter_respected(self, isolated_env):
        """Test that the limit parameter restricts the number of suggestions."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})

            # Create many agents with "Agent" prefix
            for i in range(10):
                await client.call_tool(
                    "register_agent",
                    arguments={
                        "project_key": "/tmp/test",
                        "program": "test",
                        "model": "test",
                        "name": f"Agent{i}",
                    },
                )

            # With limit=3, should return at most 3 suggestions
            suggestions = await _find_similar_agents("Agent", limit=3)
            assert len(suggestions) <= 3

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty(self, isolated_env):
        """Test that no matching agents returns an empty list."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "AlphaAgent",
                },
            )

            # Search for completely unrelated term
            suggestions = await _find_similar_agents("XyzNonExistent")
            assert suggestions == []

    @pytest.mark.asyncio
    async def test_inactive_agents_excluded(self, isolated_env):
        """Test that inactive (retired) agents are not suggested."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})

            # Create an agent
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "OldAgent",
                },
            )

            # Delete (retire) the agent
            await client.call_tool(
                "delete_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "name": "OldAgent",
                },
            )

            # Should not find the retired agent
            suggestions = await _find_similar_agents("OldAgent")
            assert "OldAgent" not in suggestions


class TestWhoisGlobalLookup:
    """Tests for whois tool with global lookup fallback."""

    @pytest.mark.asyncio
    async def test_whois_finds_agent_in_specified_project(self, isolated_env):
        """Test that whois finds agent in the specified project."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project1"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/project1",
                    "program": "test",
                    "model": "test",
                    "name": "TestAgent",
                },
            )

            result = await client.call_tool(
                "whois",
                arguments={
                    "project_key": "/tmp/project1",
                    "agent_name": "TestAgent",
                },
            )

            assert "error" not in result.data
            assert result.data["name"] == "TestAgent"

    @pytest.mark.asyncio
    async def test_whois_global_fallback_finds_agent_in_different_project(self, isolated_env):
        """Test that whois falls back to global lookup when agent not in specified project."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            # Create agent in project1
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project1"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/project1",
                    "program": "test",
                    "model": "test",
                    "name": "CrossProjectAgent",
                },
            )

            # Create project2 (agent is NOT registered here)
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project2"})

            # whois from project2 should still find the agent via global fallback
            result = await client.call_tool(
                "whois",
                arguments={
                    "project_key": "/tmp/project2",
                    "agent_name": "CrossProjectAgent",
                },
            )

            assert "error" not in result.data
            assert result.data["name"] == "CrossProjectAgent"

    @pytest.mark.asyncio
    async def test_whois_not_found_returns_suggestions(self, isolated_env):
        """Test that whois returns suggestions when agent is not found."""
        from fastmcp.exceptions import ToolError

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "BlueLake",
                },
            )

            # Search for a typo/similar name
            with pytest.raises(ToolError) as excinfo:
                await client.call_tool(
                    "whois",
                    arguments={
                        "project_key": "/tmp/test",
                        "agent_name": "BlueLakeAgent",  # Close but not exact
                    },
                )

            # The error message should contain the suggestions
            error_msg = str(excinfo.value)
            assert "BlueLake" in error_msg
            assert "Did you mean one of" in error_msg

    @pytest.mark.asyncio
    async def test_whois_not_found_error_structure(self, isolated_env):
        """Test the error response structure when agent is not found."""
        from fastmcp.exceptions import ToolError

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})

            with pytest.raises(ToolError) as excinfo:
                await client.call_tool(
                    "whois",
                    arguments={
                        "project_key": "/tmp/test",
                        "agent_name": "NonExistentAgent",
                    },
                )

            error_msg = str(excinfo.value)
            assert "NonExistentAgent" in error_msg
            assert "not registered" in error_msg
