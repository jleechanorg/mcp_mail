"""Build slot management tools for coordinating parallel build operations."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp_agent_mail.config import Settings, get_settings
from mcp_agent_mail.storage import AsyncFileLock, ensure_archive
from mcp_agent_mail.utils import safe_filesystem_component, slugify


def _normalize_branch(value: str | None) -> str:
    branch = (value or "main").strip()
    return branch or "main"


def _slot_dir(archive_root: Path, slot: str) -> Path:
    directory = archive_root / "build_slots" / safe_filesystem_component(slot)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _slot_lock(slot_dir: Path) -> AsyncFileLock:
    return AsyncFileLock(slot_dir / ".lock", timeout_seconds=30.0)


async def acquire_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
    ttl_seconds: int = 3600,
    exclusive: bool = True,
) -> dict[str, Any]:
    """
    Acquire a build slot for coordinating parallel build operations.

    Parameters
    ----------
    project_key : str
        Project identifier
    agent_name : str
        Agent requesting the slot
    slot : str
        Slot name (e.g., "frontend-build", "test-runner")
    ttl_seconds : int
        Time-to-live in seconds (minimum 60)
    exclusive : bool
        Whether this is an exclusive lock

    Returns
    -------
    dict
        {
            "granted": bool,
            "slot": str,
            "agent": str,
            "acquired_ts": str (ISO8601),
            "expires_ts": str (ISO8601),
            "conflicts": list[dict],
            "disabled": bool (if WORKTREES_ENABLED=0)
        }
    """
    settings = get_settings()

    # Check if build slots are enabled via settings (backed by python-decouple)
    if not _worktrees_enabled(settings):
        return {"disabled": True}

    # Enforce minimum TTL
    ttl_seconds = max(60, ttl_seconds)

    # Resolve project archive
    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)

    # Create slot directory
    slot_dir = _slot_dir(archive.root, slot)
    branch = _normalize_branch(os.environ.get("BRANCH"))
    holder = safe_filesystem_component(f"{agent_name}__{branch}")
    lease_path = slot_dir / f"{holder}.json"

    async with _slot_lock(slot_dir):
        now = datetime.now(timezone.utc)
        conflicts: list[dict[str, Any]] = []
        existing_payload: dict[str, Any] | None = None

        for candidate in slot_dir.glob("*.json"):
            if candidate.name.startswith(".lock"):
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue

            exp = data.get("expires_ts")
            if exp:
                try:
                    if datetime.fromisoformat(exp) <= now:
                        continue
                except Exception:
                    continue

            if data.get("released_ts"):
                continue

            same_holder = data.get("agent") == agent_name and _normalize_branch(data.get("branch")) == branch
            if same_holder:
                existing_payload = data
                continue

            if exclusive or data.get("exclusive", True):
                conflicts.append(data)

        granted = not conflicts
        acquired_ts: str | None = None
        expires_ts: str | None = None

        if granted:
            acquired_ts = now.isoformat()
            expires_ts = (now + timedelta(seconds=ttl_seconds)).isoformat()
            payload = existing_payload or {}
            payload.update(
                {
                    "slot": slot,
                    "agent": agent_name,
                    "branch": branch,
                    "exclusive": exclusive,
                    "acquired_ts": acquired_ts,
                    "expires_ts": expires_ts,
                }
            )
            lease_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        return {
            "granted": granted,
            "slot": slot,
            "agent": agent_name,
            "acquired_ts": acquired_ts,
            "expires_ts": expires_ts,
            "conflicts": conflicts,
        }


async def renew_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
    extend_seconds: int = 1800,
) -> dict[str, Any]:
    """
    Renew an existing build slot by extending its expiration.

    Parameters
    ----------
    project_key : str
        Project identifier
    agent_name : str
        Agent name
    slot : str
        Slot name
    extend_seconds : int
        Seconds to extend the expiration

    Returns
    -------
        dict
            {
                "renewed": bool,
                "expires_ts": str (ISO8601),
                "disabled": bool (if WORKTREES_ENABLED=0),
            }
    """
    settings = get_settings()
    if not _worktrees_enabled(settings):
        return {"disabled": True}

    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)

    slot_dir = archive.root / "build_slots" / safe_filesystem_component(slot)
    if not slot_dir.exists():
        return {"renewed": False, "error": "Slot not found"}

    branch = _normalize_branch(os.environ.get("BRANCH"))
    holder = safe_filesystem_component(f"{agent_name}__{branch}")
    lease_path = slot_dir / f"{holder}.json"
    if not lease_path.exists():
        return {"renewed": False, "error": "Lease not found"}

    async with _slot_lock(slot_dir):
        if not lease_path.exists():
            return {"renewed": False, "error": "Lease not found"}
        try:
            data = json.loads(lease_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"renewed": False, "error": str(exc)}

        if data.get("agent") != agent_name or _normalize_branch(data.get("branch")) != branch:
            return {"renewed": False, "error": "Lease owned by another agent"}

        now = datetime.now(timezone.utc)
        new_expires = now + timedelta(seconds=extend_seconds)
        data["expires_ts"] = new_expires.isoformat()

        try:
            lease_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            return {"renewed": False, "error": str(exc)}

        return {
            "renewed": True,
            "expires_ts": new_expires.isoformat(),
        }


async def release_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
) -> dict[str, Any]:
    """
    Release a build slot.

    Parameters
    ----------
    project_key : str
        Project identifier
    agent_name : str
        Agent name
    slot : str
        Slot name

    Returns
    -------
        dict
            {
                "released": bool,
                "released_ts": str (ISO8601),
                "disabled": bool (if WORKTREES_ENABLED=0),
            }
    """
    settings = get_settings()
    if not _worktrees_enabled(settings):
        return {"disabled": True}

    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)

    slot_dir = archive.root / "build_slots" / safe_filesystem_component(slot)
    if not slot_dir.exists():
        return {"released": False, "error": "Slot not found"}

    branch = _normalize_branch(os.environ.get("BRANCH"))
    holder = safe_filesystem_component(f"{agent_name}__{branch}")
    lease_path = slot_dir / f"{holder}.json"
    if not lease_path.exists():
        return {"released": False, "error": "Lease not found"}

    async with _slot_lock(slot_dir):
        if not lease_path.exists():
            return {"released": False, "error": "Lease not found"}
        try:
            data = json.loads(lease_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"released": False, "error": str(exc)}

        if data.get("agent") != agent_name or _normalize_branch(data.get("branch")) != branch:
            return {"released": False, "error": "Lease owned by another agent"}

        released_ts = datetime.now(timezone.utc).isoformat()
        data["released_ts"] = released_ts

        try:
            lease_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            return {"released": False, "error": str(exc)}

        return {
            "released": True,
            "released_ts": released_ts,
        }


def _worktrees_enabled(settings: Settings | None = None) -> bool:
    """Return True when worktree-aware coordination is enabled."""
    try:
        config = settings or get_settings()
    except Exception:
        return False
    return bool(getattr(config, "worktrees_enabled", False))
