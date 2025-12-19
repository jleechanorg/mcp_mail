"""Filesystem and Git archive helpers for MCP Agent Mail.

NOTE: Local disk message copying to .mcp_mail/projects/ has been removed.
This module now only provides stub functions for backwards compatibility.
All message storage is handled via SQLite database.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Sequence

from .config import Settings

logger = logging.getLogger(__name__)


def is_archive_enabled(settings: Settings) -> bool:
    """Check if archive storage is enabled.

    Archive storage has been removed. This always returns False.
    """
    return False


@dataclass(slots=True)
class ProjectArchive:
    """Placeholder for backwards compatibility. Archive functionality has been removed."""

    settings: Settings
    slug: str
    root: Path
    repo: Any = field(default=None)  # Was: Repo
    lock_path: Path = Path("/dev/null")
    repo_root: Path = Path("/dev/null")

    @property
    def attachments_dir(self) -> Path:
        return self.root / "attachments"


class ProjectStorageResolutionError(RuntimeError):
    """Raised when project-key storage cannot resolve a repository root."""

    def __init__(self, message: str, *, prompt: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.prompt = prompt or {}


async def ensure_archive(settings: Settings, slug: str, *, project_key: str | None = None) -> ProjectArchive:
    """Stub function - archive functionality has been removed.

    Returns a dummy ProjectArchive for backwards compatibility.
    """
    root = Path(settings.storage.root).expanduser().resolve() / "projects" / slug
    return ProjectArchive(
        settings=settings,
        slug=slug,
        root=root,
        repo=None,
        lock_path=root / ".archive.lock",
        repo_root=root,
    )


async def ensure_archive_root(settings: Settings, project_key: str | None, slug: str) -> tuple[Path, Any]:
    """Stub function - archive functionality has been removed."""
    root = Path(settings.storage.root).expanduser().resolve()
    return root, None


@asynccontextmanager
async def archive_write_lock(archive: ProjectArchive, *, timeout_seconds: float = 120.0) -> AsyncIterator[None]:
    """Stub async context manager - archive functionality has been removed.

    This is a no-op context manager for backwards compatibility.
    """
    yield


async def write_agent_profile(archive: ProjectArchive, agent: dict[str, object]) -> None:
    """Stub function - archive functionality has been removed."""
    pass


async def write_agent_deletion_marker(
    archive: ProjectArchive, agent_name: str, deletion_stats: dict[str, object]
) -> None:
    """Stub function - archive functionality has been removed."""
    pass


async def write_file_reservation_record(archive: ProjectArchive, file_reservation: dict[str, object]) -> None:
    """Stub function - archive functionality has been removed."""
    pass


async def write_message_bundle(
    archive: ProjectArchive,
    message: dict[str, object],
    body_md: str,
    sender: str,
    recipients: Sequence[str],
    extra_paths: Sequence[str] | None = None,
    commit_text: str | None = None,
) -> None:
    """Stub function - archive functionality has been removed."""
    pass


async def process_attachments(
    archive: ProjectArchive,
    body_md: str,
    attachment_paths: Iterable[str] | None,
    convert_markdown: bool,
    *,
    embed_policy: str = "auto",
) -> tuple[str, list[dict[str, object]], list[str]]:
    """Stub function - archive functionality has been removed.

    Returns body_md unchanged with empty attachment lists.
    """
    return body_md, [], []


def collect_lock_status(settings: Settings) -> dict[str, Any]:
    """Return empty lock status since archive functionality has been removed."""
    return {"locks": [], "summary": {"total": 0, "active": 0, "stale": 0, "metadata_missing": 0}}


async def heal_archive_locks(settings: Settings) -> dict[str, Any]:
    """Stub function - archive functionality has been removed."""
    return {"locks_scanned": 0, "locks_removed": [], "metadata_removed": []}


async def get_recent_commits(
    repo: Any,
    limit: int = 50,
    project_slug: str | None = None,
    path_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Stub function - archive functionality has been removed."""
    return []


async def get_commit_detail(repo: Any, sha: str, max_diff_size: int = 5 * 1024 * 1024) -> dict[str, Any]:
    """Stub function - archive functionality has been removed."""
    return {}


async def get_message_commit_sha(archive: ProjectArchive, message_id: int) -> str | None:
    """Stub function - archive functionality has been removed."""
    return None


async def get_archive_tree(
    archive: ProjectArchive,
    path: str = "",
    commit_sha: str | None = None,
) -> list[dict[str, Any]]:
    """Stub function - archive functionality has been removed."""
    return []


async def get_file_content(
    archive: ProjectArchive,
    path: str,
    commit_sha: str | None = None,
    max_size_bytes: int = 10 * 1024 * 1024,
) -> str | None:
    """Stub function - archive functionality has been removed."""
    return None


async def get_agent_communication_graph(
    repo: Any,
    project_slug: str,
    limit: int = 200,
) -> dict[str, Any]:
    """Stub function - archive functionality has been removed."""
    return {"nodes": [], "edges": []}


async def get_timeline_commits(
    repo: Any,
    project_slug: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Stub function - archive functionality has been removed."""
    return []


async def get_historical_inbox_snapshot(
    archive: ProjectArchive,
    agent_name: str,
    timestamp: str,
    limit: int = 100,
) -> dict[str, Any]:
    """Stub function - archive functionality has been removed."""
    return {
        "messages": [],
        "snapshot_time": None,
        "commit_sha": None,
        "requested_time": timestamp,
        "note": "Archive functionality has been removed",
    }


async def write_file_reservation_artifacts(
    settings: Settings,
    project_slug: str,
    payloads: list[dict[str, object]],
    *,
    project_key: str | None = None,
) -> list[Path]:
    """Stub function - archive functionality has been removed."""
    return []


async def ensure_runtime_project_root(settings: Settings, project_slug: str) -> Path:
    """Stub function - archive functionality has been removed."""
    base = Path(tempfile.gettempdir()) / "mcp_mail_dummy_runtime"
    path = base / project_slug
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
    return path
