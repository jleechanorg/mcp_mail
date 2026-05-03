"""Unit and integration tests for build slot functionality."""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail import build_mcp_server


def _assert_disabled(data: dict[str, object]) -> None:
    assert data.get("disabled") is True
    reason = str(data.get("reason", "")).lower()
    assert "archive" in reason or "disabled" in reason


@pytest.mark.asyncio
async def test_acquire_build_slot_basic(isolated_env):
    """Build slots should be disabled when archive storage is removed."""
    server = build_mcp_server()

    async with Client(server) as client:
        result = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "TestAgent",
                "slot": "frontend-build",
                "ttl_seconds": 3600,
                "exclusive": True,
            },
        )

    _assert_disabled(result.data)


@pytest.mark.asyncio
async def test_acquire_build_slot_conflict(isolated_env):
    """Build slots remain disabled regardless of contention."""
    server = build_mcp_server()

    async with Client(server) as client:
        # First agent acquires slot
        result1 = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "AgentAlpha",
                "slot": "test-runner",
                "ttl_seconds": 3600,
                "exclusive": True,
            },
        )

        _assert_disabled(result1.data)

        # Second agent tries to acquire same slot
        result2 = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "AgentBeta",
                "slot": "test-runner",
                "ttl_seconds": 3600,
                "exclusive": True,
            },
        )

        _assert_disabled(result2.data)


@pytest.mark.asyncio
async def test_renew_build_slot(isolated_env):
    """Renewals should return disabled when build slots are removed."""
    server = build_mcp_server()

    async with Client(server) as client:
        # Acquire slot
        await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "TestAgent",
                "slot": "build",
                "ttl_seconds": 1800,
                "exclusive": True,
            },
        )

        # Renew slot
        result = await client.call_tool(
            "renew_build_slot",
            {"project_key": "testproject", "agent_name": "TestAgent", "slot": "build", "extend_seconds": 1800},
        )

        _assert_disabled(result.data)


@pytest.mark.asyncio
async def test_release_build_slot(isolated_env):
    """Releases should return disabled when build slots are removed."""
    server = build_mcp_server()

    async with Client(server) as client:
        # Acquire slot
        await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "TestAgent",
                "slot": "deploy",
                "ttl_seconds": 3600,
                "exclusive": True,
            },
        )

        # Release slot
        result = await client.call_tool(
            "release_build_slot", {"project_key": "testproject", "agent_name": "TestAgent", "slot": "deploy"}
        )

        _assert_disabled(result.data)


@pytest.mark.asyncio
async def test_build_slot_expiry(isolated_env):
    """Expired slots are irrelevant when build slots are disabled."""
    server = build_mcp_server()

    async with Client(server) as client:
        # New agent tries to acquire the same slot
        result = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "NewAgent",
                "slot": "expired-slot",
                "ttl_seconds": 3600,
                "exclusive": True,
            },
        )

        _assert_disabled(result.data)


@pytest.mark.asyncio
async def test_build_slot_disabled_gate(isolated_env):
    """Build slots remain disabled regardless of gate settings."""
    server = build_mcp_server()

    async with Client(server) as client:
        # Try to acquire slot with gate disabled
        result = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "TestAgent",
                "slot": "build",
                "ttl_seconds": 3600,
                "exclusive": True,
            },
        )

        _assert_disabled(result.data)


@pytest.mark.asyncio
async def test_build_slot_non_exclusive(isolated_env):
    """Non-exclusive settings do not matter when slots are disabled."""
    server = build_mcp_server()

    async with Client(server) as client:
        # First agent acquires non-exclusive slot
        result1 = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "AgentA",
                "slot": "read-cache",
                "ttl_seconds": 3600,
                "exclusive": False,
            },
        )

        _assert_disabled(result1.data)

        # Second agent can also acquire non-exclusive slot
        result2 = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "AgentB",
                "slot": "read-cache",
                "ttl_seconds": 3600,
                "exclusive": False,
            },
        )

        _assert_disabled(result2.data)


@pytest.mark.asyncio
async def test_build_slot_ttl_validation(isolated_env):
    """TTL validation is skipped when slots are disabled."""
    server = build_mcp_server()

    async with Client(server) as client:
        # Try to acquire slot with very short TTL
        result = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "TestAgent",
                "slot": "build",
                "ttl_seconds": 30,  # Below minimum
                "exclusive": True,
            },
        )

        _assert_disabled(result.data)


@pytest.mark.asyncio
async def test_build_slot_gate_respects_settings(isolated_env):
    """Build slot tools ignore settings gate when archive storage is removed."""
    server = build_mcp_server()

    async with Client(server) as client:
        result = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "SettingsAgent",
                "slot": "settings-slot",
            },
        )

    _assert_disabled(result.data)
