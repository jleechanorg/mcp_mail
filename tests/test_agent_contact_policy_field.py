"""Test for Agent model contact_policy field.

This test verifies that the Agent model includes the contact_policy field
which must match the database schema to prevent IntegrityError on agent creation.

Regression test for: https://github.com/jleechanorg/mcp_mail/pull/4
"""

from __future__ import annotations

import pytest
from fastmcp import Client
from sqlalchemy import select

from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import get_session
from mcp_agent_mail.models import Agent


@pytest.mark.asyncio
async def test_agent_has_contact_policy_field_in_model(isolated_env):
    """Test that Agent model includes contact_policy field matching database schema.

    This is a regression test for the schema mismatch bug where the database
    had a contact_policy column (NOT NULL) but the SQLModel was missing it,
    causing all agent registrations to fail with IntegrityError.
    """
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create a project
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test_project"})

        # Register an agent - this should NOT raise IntegrityError
        result = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/test_project",
                "program": "test-cli",
                "model": "test-model",
                "name": "TestAgent",
                "task_description": "Testing contact_policy field",
            },
        )

        # Verify the agent was created successfully
        assert result.data is not None
        assert result.data["name"] == "TestAgent"
        agent_id = result.data["id"]

        # Verify the contact_policy field exists in the database
        async with get_session() as session:
            db_result = await session.execute(select(Agent).where(Agent.id == agent_id))
            agent = db_result.scalars().first()

            # Verify agent exists and has contact_policy field
            assert agent is not None
            assert hasattr(agent, "contact_policy"), "Agent model must have contact_policy field"

            # Verify default value is "auto"
            assert agent.contact_policy == "auto", "Default contact_policy should be 'auto'"


@pytest.mark.asyncio
async def test_agent_registration_with_auto_generated_name_has_contact_policy(isolated_env):
    """Test that auto-generated agent names also get contact_policy field set correctly."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create a project
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test_project_auto"})

        # Register an agent without specifying a name (auto-generated)
        result = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/test_project_auto",
                "program": "test-cli",
                "model": "test-model",
                # name is omitted - will be auto-generated
                "task_description": "Testing auto-generated name with contact_policy",
            },
        )

        # Verify the agent was created successfully
        assert result.data is not None
        agent_id = result.data["id"]
        agent_name = result.data["name"]

        # Verify a name was auto-generated
        assert agent_name is not None
        assert len(agent_name) > 0

        # Verify the contact_policy field exists and has default value
        async with get_session() as session:
            db_result = await session.execute(select(Agent).where(Agent.id == agent_id))
            agent = db_result.scalars().first()

            assert agent is not None
            assert hasattr(agent, "contact_policy")
            assert agent.contact_policy == "auto"


@pytest.mark.asyncio
async def test_multiple_agent_registrations_all_have_contact_policy(isolated_env):
    """Test that multiple agent registrations all properly set contact_policy field."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create a project
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/multi_agent_project"})

        # Register multiple agents
        agent_names = ["Agent1", "Agent2", "Agent3"]
        agent_ids = []

        for name in agent_names:
            result = await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": "/tmp/multi_agent_project",
                    "program": "test-cli",
                    "model": "test-model",
                    "name": name,
                    "task_description": f"Testing {name}",
                },
            )
            assert result.data is not None
            agent_ids.append(result.data["id"])

        # Verify all agents have contact_policy field set
        async with get_session() as session:
            for agent_id, expected_name in zip(agent_ids, agent_names, strict=True):
                db_result = await session.execute(select(Agent).where(Agent.id == agent_id))
                agent = db_result.scalars().first()

                assert agent is not None
                assert agent.name == expected_name
                assert hasattr(agent, "contact_policy")
                assert agent.contact_policy == "auto"
