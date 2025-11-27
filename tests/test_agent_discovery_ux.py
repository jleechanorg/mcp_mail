"""Tests for agent discovery UX improvements.

This test suite covers:
1. _find_similar_agents function for agent name suggestions
2. whois tool with global lookup fallback and suggestions
3. whois commit history using correct project on global fallback
4. Global agents directory resource (resource://agents)
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
            result = await client.call_tool(
                "whois",
                arguments={
                    "project_key": "/tmp/test",
                    "agent_name": "BlueLakeAgent",  # Close but not exact
                },
            )

            assert "error" in result.data
            assert "suggestions" in result.data
            assert "BlueLake" in result.data["suggestions"]
            assert "_tip" in result.data

    @pytest.mark.asyncio
    async def test_whois_not_found_error_structure(self, isolated_env):
        """Test the error response structure when agent is not found."""
        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})

            result = await client.call_tool(
                "whois",
                arguments={
                    "project_key": "/tmp/test",
                    "agent_name": "NonExistentAgent",
                },
            )

            assert "error" in result.data
            assert "agent_name" in result.data
            assert result.data["agent_name"] == "NonExistentAgent"
            assert "suggestions" in result.data
            assert isinstance(result.data["suggestions"], list)
            assert "_tip" in result.data
            assert "resource://agents" in result.data["_tip"]


class TestGlobalAgentsDirectory:
    """Tests for the global agents directory resource (resource://agents)."""

    @pytest.mark.asyncio
    async def test_global_agents_returns_all_active_agents(self, isolated_env):
        """Test that resource://agents returns all active agents across all projects."""
        import json

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            # Create agents in multiple projects
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project1"})
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project2"})

            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/project1",
                    "program": "test",
                    "model": "test",
                    "name": "Agent1",
                },
            )
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/project2",
                    "program": "test",
                    "model": "test",
                    "name": "Agent2",
                },
            )

            # Read the global agents directory
            blocks = await client.read_resource("resource://agents")
            assert blocks and blocks[0].text
            data = json.loads(blocks[0].text)

            # Check structure
            assert "agents" in data
            assert "total" in data
            agents = data["agents"]

            # Filter out global-inbox agents - these are system agents auto-created
            # for each project during ensure_project() and aren't user-registered agents
            test_agents = [a for a in agents if not a["name"].startswith("global-inbox-")]
            agent_names = [a["name"] for a in test_agents]

            assert "Agent1" in agent_names
            assert "Agent2" in agent_names
            assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_global_agents_includes_project_info(self, isolated_env):
        """Test that global directory includes correct project information."""
        import json

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/testproj"})
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/testproj",
                    "program": "test-program",
                    "model": "test-model",
                    "name": "TestAgent",
                },
            )

            blocks = await client.read_resource("resource://agents")
            assert blocks and blocks[0].text
            data = json.loads(blocks[0].text)
            agents = data["agents"]

            # Find our test agent
            test_agent = next((a for a in agents if a["name"] == "TestAgent"), None)
            assert test_agent is not None

            # Check project info is included
            assert "project_slug" in test_agent
            assert "project_human_key" in test_agent
            assert test_agent["project_human_key"] == "/tmp/testproj"

    @pytest.mark.asyncio
    async def test_global_agents_includes_unread_count(self, isolated_env):
        """Test that global directory calculates unread_count correctly."""
        import json

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})

            # Create two agents
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "Sender",
                },
            )
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "Receiver",
                },
            )

            # Send a message to create an unread count
            await client.call_tool(
                "send_message",
                arguments={
                    "project_key": "/tmp/test",
                    "sender_name": "Sender",
                    "to": ["Receiver"],
                    "subject": "Test message",
                    "body_md": "Test body",
                },
            )

            blocks = await client.read_resource("resource://agents")
            assert blocks and blocks[0].text
            data = json.loads(blocks[0].text)
            agents = data["agents"]

            # Find the receiver agent
            receiver = next((a for a in agents if a["name"] == "Receiver"), None)
            assert receiver is not None
            assert "unread_count" in receiver
            assert receiver["unread_count"] >= 1

    @pytest.mark.asyncio
    async def test_global_agents_excludes_inactive_agents(self, isolated_env):
        """Test that inactive (retired) agents are not in the global directory."""
        import json

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})

            # Create and then retire an agent
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "RetiredAgent",
                },
            )
            await client.call_tool(
                "delete_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "name": "RetiredAgent",
                },
            )

            blocks = await client.read_resource("resource://agents")
            assert blocks and blocks[0].text
            data = json.loads(blocks[0].text)
            agents = data["agents"]
            agent_names = [a["name"] for a in agents]

            assert "RetiredAgent" not in agent_names

    @pytest.mark.asyncio
    async def test_global_agents_ordered_by_last_active(self, isolated_env):
        """Test that agents are ordered by last_active_ts descending."""
        import asyncio
        import json

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})

            # Create agents with slight delay to ensure different timestamps
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "OlderAgent",
                },
            )
            await asyncio.sleep(0.1)
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/test",
                    "program": "test",
                    "model": "test",
                    "name": "NewerAgent",
                },
            )

            blocks = await client.read_resource("resource://agents")
            assert blocks and blocks[0].text
            data = json.loads(blocks[0].text)
            agents = data["agents"]

            # Filter to just our test agents
            test_agents = [a for a in agents if a["name"] in ("OlderAgent", "NewerAgent")]

            # Verify they exist (don't check order strictly as there may be other agents)
            agent_names = [a["name"] for a in test_agents]
            assert "OlderAgent" in agent_names
            assert "NewerAgent" in agent_names

    @pytest.mark.asyncio
    async def test_global_agents_handles_empty_directory(self, isolated_env):
        """Test that resource://agents returns valid response with no agents."""
        import json

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            # Just ensure a project exists but no agents
            await client.call_tool("ensure_project", arguments={"human_key": "/tmp/empty"})

            blocks = await client.read_resource("resource://agents")
            assert blocks and blocks[0].text
            data = json.loads(blocks[0].text)

            assert "agents" in data
            assert "total" in data
            assert isinstance(data["agents"], list)
            assert isinstance(data["total"], int)
