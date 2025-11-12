"""Unit and integration tests for build slot functionality."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mcp_agent_mail import build_mcp_server
from mcp_agent_mail.config import get_settings
from mcp_agent_mail.storage import ensure_archive


@pytest.mark.asyncio
async def test_acquire_build_slot_basic(isolated_env, tmp_path: Path):
    """Test basic build slot acquisition."""
    server = build_mcp_server()
    settings = get_settings()
    archive = await ensure_archive(settings, "testproject")

    # Enable worktrees for build slots
    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "testproject",
            "agent_name": "TestAgent",
            "slot": "frontend-build",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )

    assert result is not None
    content = result[0].text
    data = json.loads(content)

    assert data["granted"] is True
    assert data["slot"] == "frontend-build"
    assert len(data["conflicts"]) == 0

    # Verify slot file was created
    slot_dir = archive.root / "build_slots" / "frontend-build"
    assert slot_dir.exists()

    slot_files = list(slot_dir.glob("*.json"))
    assert len(slot_files) == 1

    slot_data = json.loads(slot_files[0].read_text())
    assert slot_data["agent"] == "TestAgent"
    assert slot_data["exclusive"] is True


@pytest.mark.asyncio
async def test_acquire_build_slot_conflict(isolated_env, tmp_path: Path):
    """Test build slot conflict detection with multiple agents."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    # First agent acquires slot
    result1 = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "testproject",
            "agent_name": "AgentAlpha",
            "slot": "test-runner",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )

    data1 = json.loads(result1[0].text)
    assert data1["granted"] is True

    # Second agent tries to acquire same slot
    result2 = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "testproject",
            "agent_name": "AgentBeta",
            "slot": "test-runner",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )

    data2 = json.loads(result2[0].text)
    # Still granted (advisory), but should report conflicts
    assert data2["granted"] is True
    assert len(data2["conflicts"]) > 0
    assert any("AgentAlpha" in str(c) for c in data2["conflicts"])


@pytest.mark.asyncio
async def test_renew_build_slot(isolated_env, tmp_path: Path):
    """Test build slot renewal."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    # Acquire slot
    await server._mcp_server.call_tool(
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
    result = await server._mcp_server.call_tool(
        "renew_build_slot",
        {"project_key": "testproject", "agent_name": "TestAgent", "slot": "build", "extend_seconds": 1800},
    )

    data = json.loads(result[0].text)
    assert data["renewed"] is True
    assert data["expires_ts"] is not None

    # Verify expiry was extended
    expires_dt = datetime.fromisoformat(data["expires_ts"])
    now = datetime.now(timezone.utc)
    time_remaining = (expires_dt - now).total_seconds()
    # Should be close to 1800 seconds (allow for test execution time)
    assert time_remaining > 1700
    assert time_remaining < 2000


@pytest.mark.asyncio
async def test_release_build_slot(isolated_env, tmp_path: Path):
    """Test build slot release."""
    server = build_mcp_server()
    settings = get_settings()
    archive = await ensure_archive(settings, "testproject")

    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    # Acquire slot
    await server._mcp_server.call_tool(
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
    result = await server._mcp_server.call_tool(
        "release_build_slot", {"project_key": "testproject", "agent_name": "TestAgent", "slot": "deploy"}
    )

    data = json.loads(result[0].text)
    assert data["released"] is True
    assert data["released_at"] is not None

    # Verify slot file was marked as released
    slot_dir = archive.root / "build_slots" / "deploy"
    slot_files = list(slot_dir.glob("*.json"))
    assert len(slot_files) > 0

    slot_data = json.loads(slot_files[0].read_text())
    assert "released_ts" in slot_data


@pytest.mark.asyncio
async def test_build_slot_expiry(isolated_env, tmp_path: Path):
    """Test that expired slots are not reported as conflicts."""
    server = build_mcp_server()
    settings = get_settings()
    archive = await ensure_archive(settings, "testproject")

    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    # Manually create an expired slot
    slot_dir = archive.root / "build_slots" / "expired-slot"
    slot_dir.mkdir(parents=True, exist_ok=True)

    expired_time = datetime.now(timezone.utc) - timedelta(hours=2)
    slot_data = {
        "slot": "expired-slot",
        "agent": "OldAgent",
        "branch": "main",
        "exclusive": True,
        "acquired_ts": (expired_time - timedelta(hours=1)).isoformat(),
        "expires_ts": expired_time.isoformat(),
    }

    slot_file = slot_dir / "OldAgent__main.json"
    slot_file.write_text(json.dumps(slot_data))

    # New agent tries to acquire the same slot
    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "testproject",
            "agent_name": "NewAgent",
            "slot": "expired-slot",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )

    data = json.loads(result[0].text)
    assert data["granted"] is True
    # Expired slots should not be reported as conflicts
    assert len(data["conflicts"]) == 0


@pytest.mark.asyncio
async def test_build_slot_disabled_gate(isolated_env, tmp_path: Path):
    """Test that build slots respect WORKTREES_ENABLED gate."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    import os

    os.environ["WORKTREES_ENABLED"] = "0"

    # Try to acquire slot with gate disabled
    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "testproject",
            "agent_name": "TestAgent",
            "slot": "build",
            "ttl_seconds": 3600,
            "exclusive": True,
        },
    )

    data = json.loads(result[0].text)
    assert data.get("disabled") is True
    assert data.get("granted") is None


@pytest.mark.asyncio
async def test_build_slot_non_exclusive(isolated_env, tmp_path: Path):
    """Test non-exclusive build slots allow multiple holders."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    # First agent acquires non-exclusive slot
    result1 = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "testproject",
            "agent_name": "AgentA",
            "slot": "read-cache",
            "ttl_seconds": 3600,
            "exclusive": False,
        },
    )

    data1 = json.loads(result1[0].text)
    assert data1["granted"] is True

    # Second agent can also acquire non-exclusive slot
    result2 = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "testproject",
            "agent_name": "AgentB",
            "slot": "read-cache",
            "ttl_seconds": 3600,
            "exclusive": False,
        },
    )

    data2 = json.loads(result2[0].text)
    assert data2["granted"] is True
    # Non-exclusive slots should not conflict with other non-exclusive
    assert len(data2["conflicts"]) == 0


@pytest.mark.asyncio
async def test_build_slot_ttl_validation(isolated_env, tmp_path: Path):
    """Test TTL validation (minimum 60 seconds)."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    import os

    os.environ["WORKTREES_ENABLED"] = "1"

    # Try to acquire slot with very short TTL
    result = await server._mcp_server.call_tool(
        "acquire_build_slot",
        {
            "project_key": "testproject",
            "agent_name": "TestAgent",
            "slot": "build",
            "ttl_seconds": 30,  # Below minimum
            "exclusive": True,
        },
    )

    # Should still work, but TTL should be clamped to minimum
    data = json.loads(result[0].text)
    assert data["granted"] is True

    # Verify TTL was enforced
    expires_dt = datetime.fromisoformat(data["expires_ts"])
    acquired_dt = datetime.fromisoformat(data["acquired_ts"])
    actual_ttl = (expires_dt - acquired_dt).total_seconds()
    assert actual_ttl >= 60
