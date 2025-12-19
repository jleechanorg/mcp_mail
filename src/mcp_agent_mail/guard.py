"""Pre-commit guard helpers for MCP Agent Mail.

NOTE: Archive storage has been removed. Guard functionality is now disabled
since it previously depended on the archive's file_reservations directory.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config import Settings
from .storage import ProjectArchive

__all__ = [
    "install_guard",
    "install_prepush_guard",
    "render_precommit_script",
    "render_prepush_script",
    "uninstall_guard",
]


def render_precommit_script(archive: ProjectArchive) -> str:
    """Return stub pre-commit script.

    NOTE: Archive storage has been removed.
    """
    return "#!/usr/bin/env python3\n# Archive storage removed - guard disabled\nimport sys\nsys.exit(0)\n"


def render_prepush_script(archive: ProjectArchive) -> str:
    """Return stub pre-push script.

    NOTE: Archive storage has been removed.
    """
    return "#!/usr/bin/env python3\n# Archive storage removed - guard disabled\nimport sys\nsys.exit(0)\n"


async def install_guard(settings: Settings, project_slug: str, repo_path: Path) -> Path:
    """Install the pre-commit guard for the given project into the repo.

    NOTE: Archive storage has been removed. This is a no-op that returns a placeholder path.
    Parameters are retained for backwards compatibility but are unused.

    Args:
        settings: Unused, kept for backwards compatibility
        project_slug: Unused, kept for backwards compatibility
        repo_path: Repository path for constructing the hook path

    Returns:
        Path to where the pre-commit hook would be installed

    .. deprecated::
        Guard functionality has been removed along with archive storage.
    """
    return repo_path / ".git" / "hooks" / "pre-commit"


async def install_prepush_guard(settings: Settings, project_slug: str, repo_path: Path) -> Path:
    """Install the pre-push guard for the given project into the repo.

    NOTE: Archive storage has been removed. This is a no-op that returns a placeholder path.
    Parameters are retained for backwards compatibility but are unused.

    Args:
        settings: Unused, kept for backwards compatibility
        project_slug: Unused, kept for backwards compatibility
        repo_path: Repository path for constructing the hook path

    Returns:
        Path to where the pre-push hook would be installed

    .. deprecated::
        Guard functionality has been removed along with archive storage.
    """
    return repo_path / ".git" / "hooks" / "pre-push"


async def uninstall_guard(repo_path: Path) -> bool:
    """Remove the pre-commit guard from repo, returning True if removed."""
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    if hook_path.exists():
        await asyncio.to_thread(hook_path.unlink)
        return True
    return False
