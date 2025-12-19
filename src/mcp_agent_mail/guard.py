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


def _resolve_file_reservations_dir(file_reservations_dir: Path | ProjectArchive) -> Path:
    if isinstance(file_reservations_dir, ProjectArchive):
        return file_reservations_dir.root / "file_reservations"
    return file_reservations_dir


def render_precommit_script(file_reservations_dir: Path | ProjectArchive) -> str:
    """Return stub pre-commit script.

    NOTE: Archive storage has been removed. This keeps the legacy signature for compatibility.
    """
    resolved_dir = _resolve_file_reservations_dir(file_reservations_dir)
    return (
        "#!/usr/bin/env python3\n"
        "# Archive storage removed - guard disabled\n"
        f"FILE_RESERVATIONS_DIR = {resolved_dir!r}\n"
        "AGENT_NAME = None\n"
        "import sys\n"
        "sys.exit(0)\n"
    )


def render_prepush_script(file_reservations_dir: Path | ProjectArchive) -> str:
    """Return stub pre-push script.

    NOTE: Archive storage has been removed. This keeps the legacy signature for compatibility.
    """
    resolved_dir = _resolve_file_reservations_dir(file_reservations_dir)
    return (
        "#!/usr/bin/env python3\n"
        "# Archive storage removed - guard disabled\n"
        f"FILE_RESERVATIONS_DIR = {resolved_dir!r}\n"
        "AGENT_NAME = None\n"
        "import sys\n"
        "sys.exit(0)\n"
    )


def _write_guard_stub(hook_path: Path, content: str) -> None:
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(content, encoding="utf-8")
    hook_path.chmod(0o755)


async def install_guard(settings: Settings, project_slug: str, repo_path: Path) -> Path:
    """Install the pre-commit guard for the given project into the repo.

    NOTE: Archive storage has been removed. This writes a placeholder script for compatibility.
    """
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    await asyncio.to_thread(_write_guard_stub, hook_path, render_precommit_script(hook_path.parent))
    return hook_path


async def install_prepush_guard(settings: Settings, project_slug: str, repo_path: Path) -> Path:
    """Install the pre-push guard for the given project into the repo.

    NOTE: Archive storage has been removed. This writes a placeholder script for compatibility.
    """
    hook_path = repo_path / ".git" / "hooks" / "pre-push"
    await asyncio.to_thread(_write_guard_stub, hook_path, render_prepush_script(hook_path.parent))
    return hook_path


async def uninstall_guard(repo_path: Path) -> bool:
    """Remove the pre-commit guard from repo, returning True if removed."""
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    if hook_path.exists():
        await asyncio.to_thread(hook_path.unlink)
        return True
    return False
