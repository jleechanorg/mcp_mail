"""Tests for global agent name uniqueness with different enforcement modes.

This test suite verifies that agent names are globally unique across all projects,
with different enforcement modes:
- "coerce" mode (default): Auto-generates unique names when duplicates are detected
- "strict" mode: Raises errors when duplicates are detected
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastmcp import Client
from sqlalchemy import func, select

from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import get_session
from mcp_agent_mail.models import Agent, MessageRecipient, Project


@pytest.mark.asyncio
async def test_agent_names_coerce_mode_auto_generates_unique_names(isolated_env):
    """Test that in coerce mode (default), duplicate names are auto-renamed to ensure global uniqueness."""
    # Default mode is "coerce" - should auto-generate unique names
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create two different projects
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project1"})
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project2"})

        # Create an agent "Alice" in project1
        result1 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project1",
                "program": "test_program",
                "model": "test_model",
                "name": "Alice",
            },
        )
        assert result1.data["name"] == "Alice"

        # Try to create another agent "Alice" in project2
        # In coerce mode (default), this retires the project1 agent and reuses the name
        result2 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project2",
                "program": "test_program",
                "model": "test_model",
                "name": "Alice",
            },
        )

        # Should reuse the same name "Alice" (after retiring the project1 agent)
        assert result2.data["name"] == "Alice"
        assert result2.data["project_id"] != result1.data["project_id"]

        # Verify that the old agent was retired
        async with get_session() as session:
            proj1 = (
                (await session.execute(select(Project).where(Project.human_key == "/tmp/project1"))).scalars().first()
            )
            assert proj1 is not None

            retired_agents = (
                (
                    await session.execute(
                        select(Agent).where(
                            Agent.project_id == proj1.id,
                            func.lower(Agent.name) == "alice",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(retired_agents) == 1
    assert retired_agents[0].is_active is False
    assert retired_agents[0].deleted_ts is not None


@pytest.mark.asyncio
async def test_agent_reclaim_reuses_name_and_targets_new_recipient(isolated_env):
    """Duplicate registration should reclaim the name (retiring the old agent) and route messages to the new agent."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        project1 = "/tmp/project1"
        project2 = "/tmp/project2"
        await client.call_tool("ensure_project", arguments={"human_key": project1})
        await client.call_tool("ensure_project", arguments={"human_key": project2})

        first = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": project1,
                "program": "test_program",
                "model": "test_model",
                "name": "Alpha",
            },
        )
        first_id = first.data["id"]

        # Re-register in a different project; should reclaim the name (not auto-suffix) and retire the old agent.
        second = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": project2,
                "program": "test_program",
                "model": "test_model",
                "name": "Alpha",
            },
        )
        assert second.data["name"] == "Alpha"
        assert second.data["id"] != first_id

        # Send a message to the reclaimed name; it must target the new agent (project2).
        send_result = await client.call_tool(
            "send_message",
            arguments={
                "project_key": project2,
                "sender_name": "Alpha",
                "to": ["Alpha"],
                "subject": "Ping reclaimed agent",
                "body_md": "Hello Alpha",
            },
        )
        message_id = send_result.data["deliveries"][0]["payload"]["id"]

        inbox = await client.call_tool(
            "fetch_inbox",
            arguments={
                "project_key": project2,
                "agent_name": "Alpha",
                "include_bodies": True,
                "limit": 5,
            },
        )
        assert len(inbox.data) == 1

        async with get_session() as session:
            # Old agent should be retired
            old_agent = await session.get(Agent, first_id)
            assert old_agent is not None
            assert old_agent.is_active is False

            # New agent should be active and receive the message
            new_agent = await session.get(Agent, second.data["id"])
            assert new_agent is not None
            assert new_agent.is_active is True

            recipients = (
                (
                    await session.execute(
                        select(MessageRecipient.agent_id).where(MessageRecipient.message_id == message_id)
                    )
                )
                .scalars()
                .all()
            )
            assert new_agent.id in recipients  # Delivered to the reclaimed agent
            assert old_agent.id not in recipients


@pytest.mark.asyncio
async def test_agent_names_strict_mode_raises_errors(isolated_env, monkeypatch):
    """Test that in strict mode, duplicate names raise errors for global uniqueness."""
    # Set strict mode via environment variable
    monkeypatch.setenv("AGENT_NAME_ENFORCEMENT_MODE", "strict")

    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create two different projects
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project1"})
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project2"})

        # Create an agent "Alice" in project1
        result1 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project1",
                "program": "test_program",
                "model": "test_model",
                "name": "Alice",
            },
        )
        assert result1.data["name"] == "Alice"

        # Try to create another agent "Alice" in project2 - should fail in strict mode
        with pytest.raises(Exception) as exc_info:
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/project2",
                    "program": "test_program",
                    "model": "test_model",
                    "name": "Alice",
                },
            )

        # Verify the error is about the name being taken globally
        error_msg = str(exc_info.value).lower()
        assert "already in use" in error_msg or "name_taken" in error_msg


@pytest.mark.asyncio
async def test_agent_names_are_case_insensitive_coerce_mode(isolated_env):
    """Test that agent names are case-insensitive in coerce mode (Alice == alice == ALICE)."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create project
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project1"})

        # Create agent "Alice"
        result1 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project1",
                "program": "test_program",
                "model": "test_model",
                "name": "Alice",
            },
        )
        assert result1.data["name"] == "Alice"

        # Try to create "alice" (lowercase) in same project
        # In coerce mode within same project, this should update the existing agent
        result2 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project1",
                "program": "test_program",
                "model": "test_model",
                "name": "alice",
                "task_description": "Updated task",
            },
        )

        # Should update the same agent (case-insensitive match)
        assert result2.data["name"] == "Alice"  # Preserves original casing
        assert result2.data["id"] == result1.data["id"]
        assert result2.data["task_description"] == "Updated task"


@pytest.mark.asyncio
async def test_same_agent_can_be_reregistered_in_same_project(isolated_env):
    """Test that registering the same agent name in the same project updates it."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create project
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project1"})

        # Create agent "Alice" with task description "Task 1"
        result1 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project1",
                "program": "test_program",
                "model": "test_model",
                "name": "Alice",
                "task_description": "Task 1",
            },
        )
        assert result1.data["name"] == "Alice"
        assert result1.data["task_description"] == "Task 1"
        agent_id = result1.data["id"]

        # Re-register same agent with different task description - should update
        result2 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project1",
                "program": "test_program",
                "model": "test_model",
                "name": "Alice",
                "task_description": "Task 2",
            },
        )
        assert result2.data["name"] == "Alice"
        assert result2.data["task_description"] == "Task 2"
        assert result2.data["id"] == agent_id  # Same agent ID


@pytest.mark.asyncio
async def test_reusing_name_retires_previous_agent(isolated_env):
    """Registering the same name elsewhere retires the prior identity."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        proj_a_key = "/tmp/reuse_project_a"
        proj_b_key = "/tmp/reuse_project_b"
        await client.call_tool("ensure_project", arguments={"human_key": proj_a_key})
        await client.call_tool("ensure_project", arguments={"human_key": proj_b_key})

        result_a = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": proj_a_key,
                "program": "test_program",
                "model": "test_model",
                "name": "Convo",
            },
        )
        assert result_a.data["name"] == "Convo"

        result_b = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": proj_b_key,
                "program": "test_program",
                "model": "test_model",
                "name": "Convo",
            },
        )
        assert result_b.data["name"] == "Convo"
        assert result_b.data["project_id"] != result_a.data["project_id"]

        async with get_session() as session:
            proj_a = (await session.execute(select(Project).where(Project.human_key == proj_a_key))).scalars().first()
            assert proj_a is not None
            agents_a = (
                (
                    await session.execute(
                        select(Agent).where(
                            Agent.project_id == proj_a.id, func.lower(Agent.name).not_like("global-inbox%")
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(agents_a) == 1
            retired = agents_a[0]
            assert retired.is_active is False
            assert retired.deleted_ts is not None

            active_convo = (
                (
                    await session.execute(
                        select(Agent).where(
                            func.lower(Agent.name) == "convo",
                            cast(Any, Agent.is_active).is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(active_convo) == 1
            assert active_convo[0].project_id != proj_a.id


@pytest.mark.asyncio
async def test_different_names_can_coexist_across_projects(isolated_env):
    """Test that different agent names can exist across multiple projects."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create two projects
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project1"})
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project2"})

        # Create Alice in project1
        result1 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project1",
                "program": "test_program",
                "model": "test_model",
                "name": "Alice",
            },
        )
        assert result1.data["name"] == "Alice"

        # Create Bob in project2 - should succeed (different name)
        result2 = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/project2",
                "program": "test_program",
                "model": "test_model",
                "name": "Bob",
            },
        )
        assert result2.data["name"] == "Bob"
        assert result2.data["id"] != result1.data["id"]  # Different agents
