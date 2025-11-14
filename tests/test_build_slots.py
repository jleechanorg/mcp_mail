"""Unit and integration tests for build slot functionality."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastmcp import Client

from mcp_agent_mail import build_mcp_server
from mcp_agent_mail.config import get_settings
from mcp_agent_mail.storage import ensure_archive


def _set_worktrees(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """Patch slots.get_settings() to control the WORKTREES gate."""
    settings = get_settings()
    fake_settings = replace(settings, worktrees_enabled=enabled)
    monkeypatch.setattr("mcp_agent_mail.slots.get_settings", lambda: fake_settings)


@pytest.mark.asyncio
async def test_acquire_build_slot_basic(monkeypatch, isolated_env, tmp_path: Path):
    """Test basic build slot acquisition."""
    server = build_mcp_server()
    settings = get_settings()
    archive = await ensure_archive(settings, "testproject")

    _set_worktrees(monkeypatch, True)

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

    data = result.data

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
async def test_acquire_build_slot_conflict(monkeypatch, isolated_env, tmp_path: Path):
    """Test build slot conflict detection with multiple agents."""
    server = build_mcp_server()
    settings = get_settings()
    archive = await ensure_archive(settings, "testproject")

    _set_worktrees(monkeypatch, True)

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

        data1 = result1.data
        assert data1["granted"] is True

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

        data2 = result2.data
        assert data2["granted"] is False
        assert len(data2["conflicts"]) > 0
        assert any("AgentAlpha" in str(c) for c in data2["conflicts"])

    # Verify no second lease file was written for the conflicting agent
    slot_dir = archive.root / "build_slots" / "test-runner"
    slot_files = list(slot_dir.glob("*.json"))
    assert len(slot_files) == 1


@pytest.mark.asyncio
async def test_renew_build_slot(monkeypatch, isolated_env, tmp_path: Path):
    """Test build slot renewal."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    _set_worktrees(monkeypatch, True)

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

        data = result.data
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
async def test_release_build_slot(monkeypatch, isolated_env, tmp_path: Path):
    """Test build slot release."""
    server = build_mcp_server()
    settings = get_settings()
    archive = await ensure_archive(settings, "testproject")

    _set_worktrees(monkeypatch, True)

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

        data = result.data
        assert data["released"] is True
        assert data["released_ts"] is not None

        # Verify slot file was marked as released
        slot_dir = archive.root / "build_slots" / "deploy"
        slot_files = list(slot_dir.glob("*.json"))
        assert len(slot_files) > 0

        slot_data = json.loads(slot_files[0].read_text())
        assert "released_ts" in slot_data


@pytest.mark.asyncio
async def test_build_slot_expiry(monkeypatch, isolated_env, tmp_path: Path):
    """Test that expired slots are not reported as conflicts."""
    server = build_mcp_server()
    settings = get_settings()
    archive = await ensure_archive(settings, "testproject")

    _set_worktrees(monkeypatch, True)

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

        data = result.data
        assert data["granted"] is True
        # Expired slots should not be reported as conflicts
        assert len(data["conflicts"]) == 0


@pytest.mark.asyncio
async def test_build_slot_disabled_gate(monkeypatch, isolated_env, tmp_path: Path):
    """Test that build slots respect WORKTREES_ENABLED gate."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    _set_worktrees(monkeypatch, False)

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

        data = result.data
        assert data.get("disabled") is True
        assert data.get("granted") is None


@pytest.mark.asyncio
async def test_build_slot_non_exclusive(monkeypatch, isolated_env, tmp_path: Path):
    """Test non-exclusive build slots allow multiple holders."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    _set_worktrees(monkeypatch, True)

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

        data1 = result1.data
        assert data1["granted"] is True

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

        data2 = result2.data
        assert data2["granted"] is True
        # Non-exclusive slots should not conflict with other non-exclusive
        assert len(data2["conflicts"]) == 0


@pytest.mark.asyncio
async def test_build_slot_ttl_validation(monkeypatch, isolated_env, tmp_path: Path):
    """Test TTL validation (minimum 60 seconds)."""
    server = build_mcp_server()
    settings = get_settings()
    await ensure_archive(settings, "testproject")

    _set_worktrees(monkeypatch, True)

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

        # Should still work, but TTL should be clamped to minimum
        data = result.data
        assert data["granted"] is True

        # Verify TTL was enforced
        expires_dt = datetime.fromisoformat(data["expires_ts"])
        acquired_dt = datetime.fromisoformat(data["acquired_ts"])
        actual_ttl = (expires_dt - acquired_dt).total_seconds()
        assert actual_ttl >= 60


@pytest.mark.asyncio
async def test_build_slot_gate_respects_settings(monkeypatch, isolated_env, tmp_path: Path):
    """Build slot tools should follow settings gate even when env vars are unset."""
    server = build_mcp_server()
    real_settings = get_settings()
    archive = await ensure_archive(real_settings, "testproject")

    # Ensure the raw environment does not expose the gate flag
    monkeypatch.delenv("WORKTREES_ENABLED", raising=False)

    # Pretend the settings object enables the gate (the server uses python-decouple)
    fake_settings = replace(real_settings, worktrees_enabled=True)
    monkeypatch.setattr("mcp_agent_mail.slots.get_settings", lambda: fake_settings)

    async with Client(server) as client:
        result = await client.call_tool(
            "acquire_build_slot",
            {
                "project_key": "testproject",
                "agent_name": "SettingsAgent",
                "slot": "settings-slot",
            },
        )

    # Slot acquisition should succeed because the gate is enabled in settings
    assert result.data["granted"] is True

    slot_dir = archive.root / "build_slots" / "settings-slot"
    assert slot_dir.exists(), "slot directory created when settings gate is on"
