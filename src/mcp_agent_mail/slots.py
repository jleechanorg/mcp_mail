"""Build slot management tools for coordinating parallel build operations."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp_agent_mail.config import get_settings
from mcp_agent_mail.storage import ensure_archive
from mcp_agent_mail.utils import slugify


def _safe_component(value: str) -> str:
    """Sanitize a string for use as a filesystem component."""
    s = value.strip()
    for ch in ("/", "\\", ":", "*", "?", '"', "<", ">", "|", " "):
        s = s.replace(ch, "_")
    return s or "unknown"


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

    # Check if build slots are enabled via environment variable
    if os.environ.get("WORKTREES_ENABLED", "0") == "0":
        return {"disabled": True}

    # Enforce minimum TTL
    ttl_seconds = max(60, ttl_seconds)

    # Resolve project archive
    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)

    # Create slot directory
    slot_dir = archive.root / "build_slots" / _safe_component(slot)
    slot_dir.mkdir(parents=True, exist_ok=True)

    # Read active slots (non-expired)
    now = datetime.now(timezone.utc)
    conflicts: list[dict[str, Any]] = []

    for f in slot_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))

            # Skip expired slots
            exp = data.get("expires_ts")
            if exp:
                try:
                    if datetime.fromisoformat(exp) <= now:
                        continue
                except Exception:
                    pass

            # Skip released slots
            if data.get("released_ts"):
                continue

            # Check for conflicts (exclusive slots or our own exclusive request)
            if exclusive or data.get("exclusive", True):
                # Don't conflict with our own slot
                if not (data.get("agent") == agent_name):
                    conflicts.append(data)
        except Exception:
            continue

    # Create lease file
    branch = os.environ.get("BRANCH", "main")
    holder = _safe_component(f"{agent_name}__{branch}")
    lease_path = slot_dir / f"{holder}.json"

    acquired_ts = now.isoformat()
    expires_ts = (now + timedelta(seconds=ttl_seconds)).isoformat()

    payload = {
        "slot": slot,
        "agent": agent_name,
        "branch": branch,
        "exclusive": exclusive,
        "acquired_ts": acquired_ts,
        "expires_ts": expires_ts,
    }

    lease_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "granted": True,
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
        }
    """
    settings = get_settings()

    # Resolve project archive
    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)

    # Find slot file
    slot_dir = archive.root / "build_slots" / _safe_component(slot)
    if not slot_dir.exists():
        return {"renewed": False, "error": "Slot not found"}

    branch = os.environ.get("BRANCH", "main")
    holder = _safe_component(f"{agent_name}__{branch}")
    lease_path = slot_dir / f"{holder}.json"

    if not lease_path.exists():
        return {"renewed": False, "error": "Lease not found"}

    # Update expiration
    try:
        data = json.loads(lease_path.read_text(encoding="utf-8"))
        # Renew from now, not from old expiry
        now = datetime.now(timezone.utc)
        new_expires = now + timedelta(seconds=extend_seconds)
        data["expires_ts"] = new_expires.isoformat()

        lease_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return {
            "renewed": True,
            "expires_ts": new_expires.isoformat(),
        }
    except Exception as e:
        return {"renewed": False, "error": str(e)}


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
            "released_at": str (ISO8601),
        }
    """
    settings = get_settings()

    # Resolve project archive
    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)

    # Find slot file
    slot_dir = archive.root / "build_slots" / _safe_component(slot)
    if not slot_dir.exists():
        return {"released": False, "error": "Slot not found"}

    branch = os.environ.get("BRANCH", "main")
    holder = _safe_component(f"{agent_name}__{branch}")
    lease_path = slot_dir / f"{holder}.json"

    if not lease_path.exists():
        return {"released": False, "error": "Lease not found"}

    # Mark as released
    try:
        data = json.loads(lease_path.read_text(encoding="utf-8"))
        released_ts = datetime.now(timezone.utc).isoformat()
        data["released_ts"] = released_ts

        lease_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return {
            "released": True,
            "released_at": released_ts,
        }
    except Exception as e:
        return {"released": False, "error": str(e)}
