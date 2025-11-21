"""Test for multi-agent registration with global inbox (MCP-fq5 bug fix validation).

This test validates the fix for the critical database session bug where
_ensure_project() created nested sessions causing detached instance errors.

Bug: MCP-fq5 - Database session bug in _ensure_project() blocks agent registration
Fixed in: commit 68c47518 (2025-11-18)
Root cause: _ensure_global_inbox_agent() opened nested session, causing project
            object to become detached from inner session
Solution: Pass session parameter to reuse outer session instead of creating nested one

The old code would fail with:
    InvalidRequestError: Could not refresh instance

This test would have caught the bug before it reached production.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server


@pytest.mark.asyncio
async def test_multiple_agents_register_with_global_inbox(isolated_env):
    """
    Test that multiple agents can register in the same project without session errors.

    This test specifically validates the fix for MCP-fq5 where nested sessions
    in _ensure_project() caused registration failures after the first agent.

    Flow:
    1. Register Agent 1 (creates project + global inbox agent)
    2. Register Agent 2 (reuses project, ensures global inbox exists)
    3. Register Agent 3 (same project)
    4. All registrations should succeed
    5. All agents should be able to send and receive messages

    The bug would manifest on Agent 2 or 3 registration with:
    "InvalidRequestError: Could not refresh instance"
    """
    server = build_mcp_server()
    async with Client(server) as client:
        project_key = "/test/multiagent/project"

        # Register first agent - creates project and global inbox
        agent1_result = await client.call_tool(
            "register_agent",
            {
                "project_key": project_key,
                "program": "test-agent-1",
                "model": "test-model",
                "name": "Agent1",
            },
        )
        assert agent1_result.data["name"] == "Agent1"
        assert "id" in agent1_result.data

        # Register second agent - this would fail with nested session bug
        # because _ensure_project() would call _ensure_global_inbox_agent()
        # which would open a nested session, causing project to be detached
        agent2_result = await client.call_tool(
            "register_agent",
            {
                "project_key": project_key,
                "program": "test-agent-2",
                "model": "test-model",
                "name": "Agent2",
            },
        )
        assert agent2_result.data["name"] == "Agent2"
        assert "id" in agent2_result.data

        # Register third agent - verify the fix holds for multiple agents
        agent3_result = await client.call_tool(
            "register_agent",
            {
                "project_key": project_key,
                "program": "test-agent-3",
                "model": "test-model",
                "name": "Agent3",
            },
        )
        assert agent3_result.data["name"] == "Agent3"
        assert "id" in agent3_result.data

        # Verify all agents can send messages (registration was successful)
        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": project_key,
                "sender_name": "Agent1",
                "to": ["Agent2", "Agent3"],
                "subject": "Multi-agent test",
                "body_md": "Testing multi-agent registration fix",
            },
        )
        # At least one message should be sent (exact count may vary with global inbox)
        assert send_result.data["count"] >= 1

        # Verify Agent2 can receive messages (registration was successful)
        agent2_inbox = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": project_key,
                "agent_name": "Agent2",
                "include_bodies": True,
            },
        )
        messages = (
            agent2_inbox.structured_content.get("result", agent2_inbox.data)
            if hasattr(agent2_inbox, "structured_content")
            else agent2_inbox.data
        )
        # Agent2 should have at least one message
        assert len(messages) >= 1

        # Verify Agent3 inbox can be fetched (registration was successful)
        agent3_inbox = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": project_key,
                "agent_name": "Agent3",
            },
        )
        messages = (
            agent3_inbox.structured_content.get("result", agent3_inbox.data)
            if hasattr(agent3_inbox, "structured_content")
            else agent3_inbox.data
        )
        assert isinstance(messages, list)
        assert len(messages) >= 1


@pytest.mark.asyncio
async def test_agent_reregistration_with_same_name(isolated_env):
    """
    Test that re-registering an agent with the same name works correctly.

    This tests another scenario where the session bug could manifest:
    updating an existing agent's profile.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        project_key = "/test/reregistration/project"

        # Initial registration
        result1 = await client.call_tool(
            "register_agent",
            {
                "project_key": project_key,
                "program": "program-v1",
                "model": "model-v1",
                "name": "UpdateableAgent",
                "task_description": "Initial task",
            },
        )
        agent_id_1 = result1.data["id"]
        assert result1.data["task_description"] == "Initial task"

        # Re-register with updated details (updates existing agent)
        result2 = await client.call_tool(
            "register_agent",
            {
                "project_key": project_key,
                "program": "program-v2",
                "model": "model-v2",
                "name": "UpdateableAgent",
                "task_description": "Updated task",
            },
        )
        agent_id_2 = result2.data["id"]

        # Should be the same agent (updated, not new)
        assert agent_id_1 == agent_id_2
        assert result2.data["program"] == "program-v2"
        assert result2.data["model"] == "model-v2"
        assert result2.data["task_description"] == "Updated task"


@pytest.mark.asyncio
async def test_sequential_agent_registration_same_project(isolated_env):
    """
    Test that multiple agents can register sequentially in the same project without
    session errors.

    This is a stress test for the session management fix, ensuring that registering
    several agents one after another does not cause session conflicts or errors.

    Note: Agents are registered sequentially (not concurrently) to avoid race conditions
    in agent name uniqueness checking. The key test is that multiple agents can register
    in the same project without session errors.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        project_key = "/test/concurrent/project"

        # Register 5 agents in the same project (sequentially to avoid name conflicts)
        results = []
        for i in range(5):
            result = await client.call_tool(
                "register_agent",
                {
                    "project_key": project_key,
                    "program": f"concurrent-program-{i}",
                    "model": f"model-{i}",
                    "name": f"ConcurrentAgent{i}",
                },
            )
            results.append(result)

        # Verify all agents were registered successfully
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result.data["name"] == f"ConcurrentAgent{i}"
            assert "id" in result.data

        # Verify all agents have unique IDs
        agent_ids = [r.data["id"] for r in results]
        assert len(agent_ids) == len(set(agent_ids)), "Agent IDs should be unique"
