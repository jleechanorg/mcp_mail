"""Build slot management tools for coordinating parallel build operations.

NOTE: Archive storage has been removed. Build slots functionality is now disabled
since it previously depended on the archive's filesystem structure.
"""

from __future__ import annotations

from typing import Any


async def acquire_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
    ttl_seconds: int = 3600,
    exclusive: bool = True,
) -> dict[str, Any]:
    """
    Acquire a build slot for coordinating parallel build operations.

    NOTE: Build slots are disabled since archive storage has been removed.

    Returns
    -------
    dict
        {"disabled": True}
    """
    return {"disabled": True, "reason": "Archive storage has been removed"}


async def renew_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
    extend_seconds: int = 1800,
) -> dict[str, Any]:
    """
    Renew an existing build slot by extending its expiration.

    NOTE: Build slots are disabled since archive storage has been removed.

    Returns
    -------
    dict
        {"disabled": True}
    """
    return {"disabled": True, "reason": "Archive storage has been removed"}


async def release_build_slot(
    project_key: str,
    agent_name: str,
    slot: str,
) -> dict[str, Any]:
    """
    Release a build slot.

    NOTE: Build slots are disabled since archive storage has been removed.

    Returns
    -------
    dict
        {"disabled": True}
    """
    return {"disabled": True, "reason": "Archive storage has been removed"}


def _worktrees_enabled() -> bool:
    """Return True when worktree-aware coordination is enabled.

    NOTE: Always returns False since archive storage has been removed.
    """
    return False
