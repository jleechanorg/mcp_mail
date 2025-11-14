"""Build slot management tools for coordinating parallel build operations."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from mcp_agent_mail.config import get_settings
from mcp_agent_mail.storage import ensure_archive
from mcp_agent_mail.utils import safe_filesystem_component, slugify

LOCK_TIMEOUT_SECONDS = 30
MIN_TTL_SECONDS = 60


def _normalize_branch(value: str | None) -> str:
    branch = (value or "main").strip()
    return branch or "main"


def _slot_directory(root: Path, slot: str, create: bool = True) -> Path | None:
    directory = root / "build_slots" / safe_filesystem_component(slot)
    if directory.exists() or create:
        directory.mkdir(parents=True, exist_ok=True)
        return directory
    return None


def _lease_path(slot_dir: Path, agent_name: str, branch: str) -> Path:
    holder = safe_filesystem_component(f"{agent_name}__{branch}")
    return slot_dir / f"{holder}.json"


def _slot_lock(slot_dir: Path) -> FileLock:
    return FileLock(str(slot_dir / ".lock"), timeout=LOCK_TIMEOUT_SECONDS)


async def acquire_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
    ttl_seconds: int = 3600,
    exclusive: bool = True,
) -> dict[str, Any]:
    """Acquire a build slot for coordinating parallel build operations."""

    settings = get_settings()

    if os.environ.get("WORKTREES_ENABLED", "0") == "0":
        return {"disabled": True}

    agent_name = (agent_name or "").strip()
    slot = (slot or "").strip()
    if not agent_name:
        return {"granted": False, "error": "agent_name is required"}
    if not slot:
        return {"granted": False, "error": "slot is required"}

    ttl_seconds = max(MIN_TTL_SECONDS, ttl_seconds)

    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)
    slot_dir = _slot_directory(archive.root, slot)

    branch = _normalize_branch(os.environ.get("BRANCH"))

    try:
        with _slot_lock(slot_dir):
            now = datetime.now(timezone.utc)
            conflicts: list[dict[str, Any]] = []

            for lease_file in slot_dir.glob("*.json"):
                try:
                    data = json.loads(lease_file.read_text(encoding="utf-8"))
                except Exception:
                    continue

                exp = data.get("expires_ts")
                if exp:
                    try:
                        if datetime.fromisoformat(exp) <= now:
                            continue
                    except Exception:
                        continue

            same_holder = data.get("agent") == agent_name and _normalize_branch(data.get("branch")) == branch
            if same_holder:
                existing_payload = data
                continue

            if (exclusive or data.get("exclusive", True)):
                conflicts.append(data)

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

            lease_path = _lease_path(slot_dir, agent_name, branch)
            lease_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            return {
                "granted": True,
                "slot": slot,
                "agent": agent_name,
                "acquired_ts": acquired_ts,
                "expires_ts": expires_ts,
                "exclusive": exclusive,
                "conflicts": conflicts,
            }
    except Timeout:
        return {"granted": False, "error": "Timed out while acquiring slot lock"}
    except OSError as exc:
        return {"granted": False, "error": str(exc)}


async def renew_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
    extend_seconds: int = 1800,
) -> dict[str, Any]:
    """Renew an existing build slot by extending its expiration."""

    settings = get_settings()

    if os.environ.get("WORKTREES_ENABLED", "0") == "0":
        return {"disabled": True}

    agent_name = (agent_name or "").strip()
    slot = (slot or "").strip()
    if not agent_name:
        return {"renewed": False, "error": "agent_name is required"}
    if not slot:
        return {"renewed": False, "error": "slot is required"}

    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)
    slot_dir = _slot_directory(archive.root, slot, create=False)
    if slot_dir is None or not slot_dir.exists():
        return {"renewed": False, "error": "Slot not found"}

    branch = _normalize_branch(os.environ.get("BRANCH"))
    lease_path = _lease_path(slot_dir, agent_name, branch)
    if not lease_path.exists():
        return {"renewed": False, "error": "Lease not found"}

    try:
        with _slot_lock(slot_dir):
            data = json.loads(lease_path.read_text(encoding="utf-8"))
            owner_branch = _normalize_branch(data.get("branch"))
            owner_agent = data.get("agent")
            if owner_agent != agent_name or owner_branch != branch:
                return {
                    "renewed": False,
                    "error": f"Lease owned by {owner_agent}@{owner_branch}",
                }

            now = datetime.now(timezone.utc)
            new_expires = now + timedelta(seconds=extend_seconds)
            data["expires_ts"] = new_expires.isoformat()

            lease_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            return {
                "renewed": True,
                "expires_ts": new_expires.isoformat(),
            }
    except Timeout:
        return {"renewed": False, "error": "Timed out while acquiring slot lock"}
    except Exception as exc:
        return {"renewed": False, "error": str(exc)}


async def release_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
) -> dict[str, Any]:
    """Release a build slot."""

    settings = get_settings()

    if os.environ.get("WORKTREES_ENABLED", "0") == "0":
        return {"disabled": True}

    agent_name = (agent_name or "").strip()
    slot = (slot or "").strip()
    if not agent_name:
        return {"released": False, "error": "agent_name is required"}
    if not slot:
        return {"released": False, "error": "slot is required"}

    slug = slugify(project_key)
    archive = await ensure_archive(settings, slug)
    slot_dir = _slot_directory(archive.root, slot, create=False)
    if slot_dir is None or not slot_dir.exists():
        return {"released": False, "error": "Slot not found"}

    branch = _normalize_branch(os.environ.get("BRANCH"))
    lease_path = _lease_path(slot_dir, agent_name, branch)
    if not lease_path.exists():
        return {"released": False, "error": "Lease not found"}

    try:
        with _slot_lock(slot_dir):
            data = json.loads(lease_path.read_text(encoding="utf-8"))
            owner_branch = _normalize_branch(data.get("branch"))
            owner_agent = data.get("agent")
            if owner_agent != agent_name or owner_branch != branch:
                return {
                    "released": False,
                    "error": f"Lease owned by {owner_agent}@{owner_branch}",
                }

            released_ts = datetime.now(timezone.utc).isoformat()
            data["released_ts"] = released_ts

            lease_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            return {
                "released": True,
                "released_ts": released_ts,
            }
    except Timeout:
        return {"released": False, "error": "Timed out while acquiring slot lock"}
    except Exception as exc:
        return {"released": False, "error": str(exc)}
