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


def _guard_stub_script() -> str:
    return "#!/usr/bin/env python3\n# Archive storage removed - guard disabled\nimport sys\nsys.exit(0)\n"


async def _write_guard_stub(hook_path: Path) -> None:
    def _write() -> None:
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text(_guard_stub_script(), encoding="utf-8")
        hook_path.chmod(0o755)

    await asyncio.to_thread(_write)


def render_precommit_script(archive: ProjectArchive | None = None) -> str:
    """Return stub pre-commit script.

    NOTE: Archive storage has been removed. Parameter is ignored but kept for backward compatibility.
    
    Args:
        archive: Ignored. Kept for backward compatibility.
        
    Returns:
        A stub pre-commit script that exits successfully.
    """
    return _guard_stub_script()


def render_prepush_script(file_reservations_dir: Path | ProjectArchive | None = None) -> str:
    """Return stub pre-push script.

    NOTE: Archive storage has been removed. Parameter is ignored but kept for backward compatibility.
    
    Args:
        file_reservations_dir: Ignored. Kept for backward compatibility.
        
    Returns:
        A stub pre-push script that exits successfully.
    """
    return _guard_stub_script()


async def install_guard(settings: Settings | None, project_slug: str | None, repo_path: Path) -> Path:
    """Install the pre-commit guard for the given project into the repo.

    NOTE: Archive storage has been removed. Installs a no-op stub script.
    
    Args:
        settings: Ignored. Kept for backward compatibility.
        project_slug: Ignored. Kept for backward compatibility.
        repo_path: Path to the repository root.
        
    Returns:
        Path to the installed hook file.
    """
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    await _write_guard_stub(hook_path)
    return hook_path


async def install_prepush_guard(settings: Settings | None, project_slug: str | None, repo_path: Path) -> Path:
    """Install the pre-push guard for the given project into the repo.

    NOTE: Archive storage has been removed. Installs a no-op stub script.
    
    Args:
        settings: Ignored. Kept for backward compatibility.
        project_slug: Ignored. Kept for backward compatibility.
        repo_path: Path to the repository root.
        
    Returns:
        Path to the installed hook file.
    """
    hook_path = repo_path / ".git" / "hooks" / "pre-push"
    await _write_guard_stub(hook_path)
    return hook_path


def uninstall_guard(repo_path: Path) -> bool:
    """Remove the pre-commit guard from repo, returning True if removed.
    
    Args:
        repo_path: Path to the repository root.
        
    Returns:
        True if the hook was removed, False if it didn't exist.
    """
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    if hook_path.exists():
        hook_path.unlink()
        return True
    return False
