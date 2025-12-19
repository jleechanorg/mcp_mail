"""Pre-commit guard helpers for MCP Agent Mail.

NOTE: Archive storage has been removed. Guard functionality is now disabled
since it previously depended on the archive's file_reservations directory.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config import Settings

__all__ = [
    "install_guard",
    "install_prepush_guard",
    "render_precommit_script",
    "render_prepush_script",
    "uninstall_guard",
]


def _guard_stub_script() -> str:
    return "#!/usr/bin/env python3\n# Archive storage removed - guard disabled\nimport sys\nsys.exit(0)\n"


async def _write_guard_stub(hook_path: Path) -> None:
    def _write() -> None:
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text(_guard_stub_script(), encoding="utf-8")
        hook_path.chmod(0o755)

    await asyncio.to_thread(_write)


def render_precommit_script(file_reservations_dir: Path) -> str:
    """Return stub pre-commit script.

    NOTE: Archive storage has been removed. The file_reservations_dir is ignored.
    """
    return _guard_stub_script()


def render_prepush_script(file_reservations_dir: Path) -> str:
    """Return stub pre-push script.

    NOTE: Archive storage has been removed. The file_reservations_dir is ignored.
    """
    return _guard_stub_script()


async def install_guard(settings: Settings, project_slug: str, repo_path: Path) -> Path:
    """Install the pre-commit guard for the given project into the repo.

    NOTE: Archive storage has been removed. Installs a no-op stub script.
    """
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    await _write_guard_stub(hook_path)
    return hook_path


async def install_prepush_guard(settings: Settings, project_slug: str, repo_path: Path) -> Path:
    """Install the pre-push guard for the given project into the repo.

    NOTE: Archive storage has been removed. Installs a no-op stub script.
    """
    hook_path = repo_path / ".git" / "hooks" / "pre-push"
    await _write_guard_stub(hook_path)
    return hook_path


async def uninstall_guard(repo_path: Path) -> bool:
    """Remove the pre-commit guard from repo, returning True if removed."""
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    if hook_path.exists():
        await asyncio.to_thread(hook_path.unlink)
        return True
    return False
