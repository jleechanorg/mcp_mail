"""Application factory for the MCP Agent Mail server."""

from __future__ import annotations

import asyncio
import fnmatch
import functools
import hashlib
import inspect
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from functools import wraps
from pathlib import Path
from typing import Any, Optional, cast
from urllib.parse import parse_qsl

from fastmcp import Context, FastMCP
from fastmcp.tools.tool import ToolResult  # type: ignore
from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError
from sqlalchemy import Column, Integer, MetaData, Table, asc, bindparam, delete, desc, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError, NoResultFound, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from . import rich_logger
from .config import Settings, get_settings
from .db import ensure_schema, get_session, init_engine
from .guard import install_guard as install_guard_script, uninstall_guard as uninstall_guard_script
from .llm import complete_system_user
from .models import (
    Agent,
    FileReservation,
    Message,
    MessageRecipient,
    Product,
    ProductProjectLink,
    Project,
    ProjectSiblingSuggestion,
)
from .slack_integration import SlackClient, notify_slack_ack, notify_slack_message
from .slots import (
    acquire_build_slot as acquire_slot_impl,
    release_build_slot as release_slot_impl,
    renew_build_slot as renew_slot_impl,
)
from .storage import (
    ProjectArchive,
    ProjectStorageResolutionError,
    collect_lock_status,
    heal_archive_locks,
    write_file_reservation_artifacts,
)
from .utils import generate_agent_name, sanitize_agent_name, slugify

logger = logging.getLogger(__name__)

# Global Slack client instance (initialized in lifespan)
_slack_client: Optional[SlackClient] = None

TOOL_METRICS: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "errors": 0})
TOOL_CLUSTER_MAP: dict[str, str] = {}
TOOL_METADATA: dict[str, dict[str, Any]] = {}

RECENT_TOOL_USAGE: deque[tuple[datetime, str, Optional[str], Optional[str]]] = deque(maxlen=4096)

CLUSTER_SETUP = "infrastructure"
CLUSTER_IDENTITY = "identity"
CLUSTER_MESSAGING = "messaging"
CLUSTER_SEARCH = "search"
CLUSTER_FILE_RESERVATIONS = "file_reservations"
CLUSTER_MACROS = "workflow_macros"
CLUSTER_PRODUCT = "product"

# Default project for agents when project_key is not specified
DEFAULT_PROJECT_KEY = "global"


# Global inbox configuration


async def _ensure_archive_if_enabled(settings: Settings, project: Project) -> ProjectArchive | None:
    """Initialize and return the project archive when archive storage is enabled.

    NOTE: Archive storage has been removed. This always returns None.
    """
    return None


def _resolve_project_identity(target_path: str) -> dict[str, Any]:
    """
    Resolve project identity using markers and git metadata.

    Priority:
    1. Committed marker (.agent-mail-project-id)
    2. Private marker (.git/agent-mail/project-id)
    3. Remote fingerprint (SHA1 of normalized remote URL + default branch)

    Returns dict with 'project_uid' key.
    """
    import re
    import subprocess

    path = Path(target_path).resolve()

    # 1. Check for committed marker
    committed_marker = path / ".agent-mail-project-id"
    if committed_marker.exists():
        uid = committed_marker.read_text(encoding="utf-8").strip()
        if uid:
            return {"project_uid": uid}

    # 1b. Private marker at conventional .git path
    direct_private_marker = path / ".git" / "agent-mail" / "project-id"
    if direct_private_marker.exists():
        uid = direct_private_marker.read_text(encoding="utf-8").strip()
        if uid:
            return {"project_uid": uid}

    # 2. Check for private marker in git-common-dir
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_common_dir = result.stdout.strip()
        if not git_common_dir.startswith("/"):
            git_common_dir = str(path / git_common_dir)

        private_candidates = [
            Path(git_common_dir) / "agent-mail" / "project-id",
            path / ".git" / "agent-mail" / "project-id",
        ]
        for private_marker in private_candidates:
            if private_marker.exists():
                uid = private_marker.read_text(encoding="utf-8").strip()
                if uid:
                    return {"project_uid": uid}
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # 3. Fall back to remote fingerprint
    try:
        # Get remote URL
        result = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        remote_url = result.stdout.strip()

        # Normalize URL to host/owner/repo pattern
        # Handle both https://github.com/owner/repo.git and git@github.com:owner/repo.git
        normalized = re.sub(r"\.git$", "", remote_url)
        normalized = re.sub(r"^https?://", "", normalized)
        normalized = re.sub(r"^git@([^:]+):", r"\1/", normalized)

        # Get default branch (fallback to 'main' if not found)
        default_branch = "main"
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "symbolic-ref", "refs/remotes/origin/HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            branch_guess = result.stdout.strip().split("/")[-1]
            if branch_guess and branch_guess != "master":
                default_branch = branch_guess
        except (subprocess.CalledProcessError, IndexError):
            pass

        # Create fingerprint and hash it
        fingerprint = f"{normalized}@{default_branch}"
        uid = hashlib.sha1(fingerprint.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
        return {"project_uid": uid}
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Final fallback - use path-based slug
    return {"project_uid": slugify(str(path))}


def get_global_inbox_name(project: Project) -> str:
    """Get project-specific global inbox name for message archival organization."""
    return f"global-inbox-{project.slug}"


class ToolExecutionError(Exception):
    def __init__(
        self, error_type: str, message: str, *, recoverable: bool = True, data: Optional[dict[str, Any]] = None
    ):
        super().__init__(message)
        self.error_type = error_type
        self.recoverable = recoverable
        self.data = data or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "type": self.error_type,
                "message": str(self),
                "recoverable": self.recoverable,
                "data": self.data,
            }
        }


def _record_tool_error(tool_name: str, exc: Exception) -> None:
    logger.warning(
        "tool_error",
        extra={
            "tool": tool_name,
            "error": type(exc).__name__,
            "error_message": str(exc),
        },
    )


def _register_tool(name: str, metadata: dict[str, Any]) -> None:
    TOOL_CLUSTER_MAP[name] = metadata["cluster"]
    TOOL_METADATA[name] = metadata


def _bind_arguments(
    signature: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> inspect.BoundArguments:
    try:
        return signature.bind_partial(*args, **kwargs)
    except TypeError:
        return signature.bind(*args, **kwargs)


def _extract_argument(bound: inspect.BoundArguments, name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    value = bound.arguments.get(name)
    if value is None:
        return None
    return str(value)


def _enforce_capabilities(ctx: Context, required: set[str], tool_name: str) -> None:
    if not required:
        return
    metadata = getattr(ctx, "metadata", {}) or {}
    allowed = metadata.get("allowed_capabilities")
    if allowed is None:
        return
    allowed_set = {str(item) for item in allowed}
    if allowed_set and not required.issubset(allowed_set):
        missing = sorted(required - allowed_set)
        raise ToolExecutionError(
            "CAPABILITY_DENIED",
            f"Tool '{tool_name}' requires capabilities {missing} (allowed={sorted(allowed_set)}).",
            recoverable=False,
            data={"required": missing, "allowed": sorted(allowed_set)},
        )


def _record_recent(tool_name: str, project: Optional[str], agent: Optional[str]) -> None:
    RECENT_TOOL_USAGE.append((datetime.now(timezone.utc), tool_name, project, agent))


def _instrument_tool(
    tool_name: str,
    *,
    cluster: str,
    capabilities: Optional[set[str]] = None,
    complexity: str = "medium",
    agent_arg: Optional[str] = None,
    project_arg: Optional[str] = None,
):
    meta = {
        "cluster": cluster,
        "capabilities": sorted(capabilities or {cluster}),
        "complexity": complexity,
        "agent_arg": agent_arg,
        "project_arg": project_arg,
    }
    _register_tool(tool_name, meta)

    def decorator(func):
        signature = inspect.signature(func)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.perf_counter()

            metrics = TOOL_METRICS[tool_name]
            metrics["calls"] += 1
            bound = _bind_arguments(signature, args, kwargs)
            ctx = bound.arguments.get("ctx")
            if isinstance(ctx, Context) and meta["capabilities"]:
                required_caps = set(cast(list[str], meta["capabilities"]))
                _enforce_capabilities(ctx, required_caps, tool_name)
            project_value = _extract_argument(bound, project_arg)
            agent_value = _extract_argument(bound, agent_arg)

            # Rich logging: Log tool call start if enabled
            settings = get_settings()
            log_enabled = settings.tools_log_enabled
            log_ctx = None

            if log_enabled:
                try:
                    clean_kwargs = {k: v for k, v in bound.arguments.items() if k != "ctx"}
                    log_ctx = rich_logger.ToolCallContext(
                        tool_name=tool_name,
                        args=[],
                        kwargs=clean_kwargs,
                        project=project_value,
                        agent=agent_value,
                        start_time=start_time,
                    )
                    rich_logger.log_tool_call_start(log_ctx)
                except Exception:
                    # Logging errors should not break tool execution
                    log_ctx = None

            result = None
            error = None
            try:
                result = await func(*args, **kwargs)
            except ToolExecutionError as exc:
                metrics["errors"] += 1
                _record_tool_error(tool_name, exc)
                error = exc
                raise
            except ProjectStorageResolutionError as exc:
                metrics["errors"] += 1
                _record_tool_error(tool_name, exc)
                error_type = "PROJECT_STORAGE_PROMPT" if getattr(exc, "prompt", None) else "PROJECT_STORAGE"
                base_message = str(exc)
                message = (
                    f"{base_message} Choose a resolution option from the prompt."
                    if getattr(exc, "prompt", None)
                    else base_message
                )
                wrapped_exc = ToolExecutionError(
                    error_type,
                    message,
                    recoverable=bool(getattr(exc, "prompt", None)),
                    data={"tool": tool_name, "project": project_value, "prompt": getattr(exc, "prompt", {})},
                )
                error = wrapped_exc
                raise wrapped_exc from exc
            except NoResultFound as exc:
                # Handle agent/project not found errors with helpful messages
                metrics["errors"] += 1
                _record_tool_error(tool_name, exc)
                wrapped_exc = ToolExecutionError(
                    "NOT_FOUND",
                    str(exc),  # Use the original helpful error message
                    recoverable=True,
                    data={"tool": tool_name},
                )
                error = wrapped_exc
                raise wrapped_exc from exc
            except Exception as exc:
                metrics["errors"] += 1
                _record_tool_error(tool_name, exc)
                wrapped_exc = ToolExecutionError(
                    "UNHANDLED_EXCEPTION",
                    "Server encountered an unexpected error while executing tool.",
                    recoverable=False,
                    data={"tool": tool_name, "original_error": type(exc).__name__},
                )
                error = wrapped_exc
                raise wrapped_exc from exc
            finally:
                _record_recent(tool_name, project_value, agent_value)

                # Rich logging: Log tool call end if enabled
                if log_ctx is not None:
                    try:
                        log_ctx.end_time = time.perf_counter()
                        log_ctx.result = result
                        log_ctx.error = error
                        log_ctx.success = error is None
                        rich_logger.log_tool_call_end(log_ctx)
                    except Exception:
                        # Logging errors should not suppress original exceptions
                        pass

            return result

        # Preserve annotations so FastMCP can infer output schema
        with suppress(Exception):
            wrapper.__annotations__ = getattr(func, "__annotations__", {})
        return wrapper

    return decorator


def _tool_metrics_snapshot() -> list[dict[str, Any]]:
    snapshot = []
    for name, data in sorted(TOOL_METRICS.items()):
        metadata = TOOL_METADATA.get(name, {})
        snapshot.append(
            {
                "name": name,
                "calls": data["calls"],
                "errors": data["errors"],
                "cluster": TOOL_CLUSTER_MAP.get(name, "unclassified"),
                "capabilities": metadata.get("capabilities", []),
                "complexity": metadata.get("complexity", "unknown"),
            }
        )
    return snapshot


@functools.lru_cache(maxsize=1)
def _load_capabilities_mapping() -> list[dict[str, Any]]:
    mapping_path = Path(__file__).resolve().parent.parent.parent / "deploy" / "capabilities" / "agent_capabilities.json"
    if not mapping_path.exists():
        return []
    try:
        data = json.loads(mapping_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("capability_mapping.load_failed", extra={"error": str(exc)})
        return []
    agents = data.get("agents", [])
    if not isinstance(agents, list):
        return []
    normalized: list[dict[str, Any]] = []
    for entry in agents:
        if not isinstance(entry, dict):
            continue
        normalized.append(entry)
    return normalized


def _capabilities_for(agent: Optional[str], project: Optional[str]) -> list[str]:
    mapping = _load_capabilities_mapping()
    caps: set[str] = set()
    for entry in mapping:
        entry_agent = entry.get("name")
        entry_project = entry.get("project")
        if agent and entry_agent != agent:
            continue
        if project and entry_project != project:
            continue
        for item in entry.get("capabilities", []):
            if isinstance(item, str):
                caps.add(item)
    return sorted(caps)


def _lifespan_factory(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastMCP):
        global _slack_client

        init_engine(settings)
        heal_summary = await heal_archive_locks(settings)
        if heal_summary.get("locks_removed") or heal_summary.get("metadata_removed"):
            logger.info(
                "archive.healed_on_startup",
                extra={
                    "locks_scanned": heal_summary.get("locks_scanned", 0),
                    "locks_removed": len(heal_summary.get("locks_removed", [])),
                    "metadata_removed": len(heal_summary.get("metadata_removed", [])),
                },
            )
        await ensure_schema(settings)

        # Initialize Slack client if enabled (using singleton to share thread mappings)
        if settings.slack.enabled:
            try:
                _slack_client = await SlackClient.get_instance(settings.slack)
                logger.info("Slack integration initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Slack integration: {e}")
                _slack_client = None

        yield

        # Cleanup Slack client
        if _slack_client:
            try:
                await _slack_client.close()
                logger.info("Slack client closed")
            except Exception as e:
                logger.error(f"Error closing Slack client: {e}")
            finally:
                _slack_client = None

    return lifespan


def _iso(dt: Any) -> str:
    """Return ISO-8601 in UTC from datetime or best-effort from string.

    Accepts datetime or ISO-like string; falls back to str(dt) if unknown.
    """
    try:
        if isinstance(dt, str):
            try:
                parsed = datetime.fromisoformat(dt)
                parsed_utc = _ensure_utc(parsed)
                return parsed_utc.isoformat() if parsed_utc else dt
            except Exception:
                return dt
        if isinstance(dt, datetime):
            ensured = _ensure_utc(dt)
            return ensured.isoformat() if ensured else str(dt)
        if hasattr(dt, "astimezone"):
            return dt.astimezone(timezone.utc).isoformat()  # type: ignore[no-any-return]
        return str(dt)
    except Exception:
        return str(dt)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return a timezone-aware UTC datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _max_datetime(*timestamps: Optional[datetime]) -> Optional[datetime]:
    values = [ts for ts in timestamps if ts is not None]
    if not values:
        return None
    return max(values)


_TRUE_FLAG_VALUES: tuple[str, ...] = ("1", "true", "yes", "on", "y")
_FALSE_FLAG_VALUES: tuple[str, ...] = ("0", "false", "no", "off", "n")


def _split_slug_and_query(raw_value: str) -> tuple[str, dict[str, str]]:
    slug, _, query_string = raw_value.partition("?")
    if not query_string:
        return slug, {}
    params = dict(parse_qsl(query_string, keep_blank_values=True))
    return slug, params


def _coerce_flag_to_bool(value: str, *, default: bool) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_FLAG_VALUES:
        return True
    if normalized in _FALSE_FLAG_VALUES:
        return False
    return default


@dataclass(slots=True)
class FileReservationStatus:
    reservation: FileReservation
    agent: Agent
    stale: bool
    stale_reasons: list[str]
    last_agent_activity: Optional[datetime]
    last_mail_activity: Optional[datetime]
    last_fs_activity: Optional[datetime]
    last_git_activity: Optional[datetime]


_GLOB_MARKERS: tuple[str, ...] = ("*", "?", "[")


def _contains_glob(pattern: str) -> bool:
    return any(marker in pattern for marker in _GLOB_MARKERS)


def _normalize_pattern(pattern: str) -> str:
    return pattern.lstrip("/").strip()


def _collect_matching_paths(base: Path, pattern: str) -> list[Path]:
    if not base.exists():
        return []
    normalized = _normalize_pattern(pattern)
    if not normalized:
        return []
    if _contains_glob(normalized):
        return list(base.glob(normalized))
    candidate = base / normalized
    if not candidate.exists():
        return []
    return [candidate]


def _latest_filesystem_activity(paths: Sequence[Path]) -> Optional[datetime]:
    mtimes: list[datetime] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        mtimes.append(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))
    if not mtimes:
        return None
    return max(mtimes)


def _latest_git_activity(repo: Optional[Repo], matches: Sequence[Path]) -> Optional[datetime]:
    if repo is None:
        return None
    repo_root = Path(repo.working_tree_dir or "").resolve()
    commit_times: list[datetime] = []
    for match in matches:
        try:
            rel_path = match.resolve().relative_to(repo_root)
        except Exception:
            continue
        try:
            commit = next(repo.iter_commits(paths=str(rel_path), max_count=1))
        except StopIteration:
            continue
        except Exception:
            continue
        commit_times.append(datetime.fromtimestamp(commit.committed_date, tz=timezone.utc))
    if not commit_times:
        return None
    return max(commit_times)


def _project_workspace_path(project: Project) -> Optional[Path]:
    try:
        candidate = Path(project.human_key).expanduser()
    except Exception:
        return None
    with suppress(OSError):
        if candidate.exists():
            return candidate
    return None


def _open_repo_if_available(workspace: Optional[Path]) -> Optional[Repo]:
    if workspace is None:
        return None
    try:
        repo = Repo(workspace, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return None
    except Exception:
        return None
    try:
        root = Path(repo.working_tree_dir or "")
    except Exception:
        return None
    with suppress(Exception):
        workspace.resolve().relative_to(root.resolve())
        return repo
    return None


def _parse_json_safely(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction supporting code fences and stray text.

    Returns parsed dict on success, otherwise None.
    """
    import json as _json
    import re as _re

    try:
        parsed = _json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    # Code fence block
    m = _re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        inner = m.group(1)
        try:
            parsed = _json.loads(inner)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    # Braces slice heuristic
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            parsed = _json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return None


def _parse_iso(raw_value: Optional[str]) -> Optional[datetime]:
    """Parse ISO-8601 timestamps, accepting a trailing 'Z' as UTC.

    Returns None when parsing fails.
    """
    if raw_value is None:
        return None
    s = raw_value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _rich_error_panel(title: str, payload: dict[str, Any]) -> None:
    """Render a compact JSON error panel if Rich is available and tools logging is enabled."""
    try:
        if not get_settings().tools_log_enabled:
            return
        import importlib as _imp

        _rc = _imp.import_module("rich.console")
        _rj = _imp.import_module("rich.json")
        Console = _rc.Console
        JSON = _rj.JSON
        Console().print(JSON.from_data({"title": title, **payload}))
    except Exception:
        return


def _render_commit_panel(
    tool_name: str,
    project_label: str,
    agent_name: str,
    start_monotonic: float,
    end_monotonic: float,
    result_payload: dict[str, Any],
    created_iso: Optional[str],
) -> str | None:
    """Create the Rich panel text used for Git commit messages."""
    try:
        panel_ctx = rich_logger.ToolCallContext(
            tool_name=tool_name,
            args=[],
            kwargs={},
            project=project_label,
            agent=agent_name,
        )
        panel_ctx.start_time = start_monotonic
        panel_ctx.end_time = end_monotonic
        panel_ctx.success = True
        panel_ctx.result = result_payload
        if created_iso:
            parsed = _parse_iso(created_iso)
            if parsed:
                panel_ctx._created_at = parsed
        return rich_logger.render_tool_call_panel(panel_ctx)
    except Exception:
        return None


def _project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "slug": project.slug,
        "human_key": project.human_key,
        "created_at": _iso(project.created_at),
    }


def _agent_to_dict(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "name": agent.name,
        "program": agent.program,
        "model": agent.model,
        "task_description": agent.task_description,
        "inception_ts": _iso(agent.inception_ts),
        "last_active_ts": _iso(agent.last_active_ts),
        "project_id": agent.project_id,
        "attachments_policy": getattr(agent, "attachments_policy", "auto"),
        "contact_policy": getattr(agent, "contact_policy", "auto"),
        "is_active": getattr(agent, "is_active", True),
        "deleted_ts": _iso(deleted_ts) if (deleted_ts := getattr(agent, "deleted_ts", None)) is not None else None,
        "is_placeholder": getattr(agent, "is_placeholder", False),
    }


def _message_to_dict(message: Message, include_body: bool = True) -> dict[str, Any]:
    data = {
        "id": message.id,
        "project_id": message.project_id,
        "sender_id": message.sender_id,
        "thread_id": message.thread_id,
        "subject": message.subject,
        "importance": message.importance,
        "ack_required": message.ack_required,
        "created_ts": _iso(message.created_ts),
        "attachments": message.attachments,
    }
    if include_body:
        data["body_md"] = message.body_md
    return data


def _message_frontmatter(
    message: Message,
    project: Project | None,
    sender: Agent,
    to_agents: Sequence[Agent],
    cc_agents: Sequence[Agent],
    bcc_agents: Sequence[Agent],
    attachments: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    project_key = project.human_key if project else DEFAULT_PROJECT_KEY
    project_slug = project.slug if project else slugify(DEFAULT_PROJECT_KEY)
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "project": project_key,
        "project_slug": project_slug,
        "from": sender.name,
        "to": [agent.name for agent in to_agents],
        "cc": [agent.name for agent in cc_agents],
        "bcc": [agent.name for agent in bcc_agents],
        "subject": message.subject,
        "importance": message.importance,
        "ack_required": message.ack_required,
        "created": _iso(message.created_ts),
        "attachments": attachments,
    }


async def _ensure_project(human_key: str) -> Project:
    await ensure_schema()
    slug = slugify(human_key)
    async with get_session() as session:
        result = await session.execute(select(Project).where(Project.slug == slug))
        project = result.scalars().first()
        if project:
            # Ensure global inbox agent exists for existing project
            await _ensure_global_inbox_agent(project, session)
            return project
        project = Project(slug=slug, human_key=human_key)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        # Create global inbox agent for new project
        await _ensure_global_inbox_agent(project, session)
        return project


async def _get_default_project() -> Project:
    """Get or create the default global project for agents without explicit project context.

    This enables backwards compatibility: agents can be created without specifying a project,
    and they'll be associated with this default global project.
    """
    return await _ensure_project(DEFAULT_PROJECT_KEY)


async def _get_project_for_agent(agent: Agent) -> Optional[Project]:
    """Get the project associated with an agent, if any.

    Returns None if the agent has no project_id (new schema allows this).
    For backwards compatibility, existing agents retain their project association.
    """
    if agent.project_id is None:
        return None
    await ensure_schema()
    async with get_session() as session:
        project = await session.get(Project, agent.project_id)
        return project


async def _require_project_for_agent(agent: Agent, action: str) -> Project:
    """Return the agent's project or raise a clear error if none exists."""

    project = await _get_project_for_agent(agent)
    if project is None:
        raise ToolExecutionError(
            "NOT_FOUND",
            (
                f"Cannot {action}: agent '{agent.name}' is not associated with a project. "
                "The project may have been deleted or not yet assigned."
            ),
            recoverable=False,
        )
    return project


async def _ensure_global_inbox_agent(project: Project, session: AsyncSession | None = None) -> Agent:
    """Ensure the global inbox agent exists for the given project.

    Each project gets its own global inbox agent with a project-specific name
    for organizational purposes and message archival.
    """
    if project.id is None:
        raise ValueError("Project must have an id before creating global inbox agent.")

    global_inbox_name = get_global_inbox_name(project)

    await ensure_schema()
    if session is None:
        async with get_session() as session_local:
            return await _ensure_global_inbox_agent(project, session_local)

    # Check if global inbox agent already exists for this project
    result = await session.execute(
        select(Agent).where(
            Agent.project_id == project.id,
            Agent.name == global_inbox_name,
        )
    )
    existing_agent = result.scalars().first()
    if existing_agent:
        return existing_agent

    # Create global inbox agent for this project
    agent = Agent(
        project_id=project.id,
        name=global_inbox_name,
        program="mcp-mail-system",
        model="system",
        task_description=f"Global inbox for project '{project.slug}'.",
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def _get_project_by_identifier(identifier: str) -> Project:
    await ensure_schema()
    slug = slugify(identifier)
    async with get_session() as session:
        result = await session.execute(select(Project).where(Project.slug == slug))
        project = result.scalars().first()
        if not project:
            raise NoResultFound(f"Project '{identifier}' not found.")
        return project


async def _get_project_by_id(project_id: int) -> Project:
    await ensure_schema()
    async with get_session() as session:
        project = await session.get(Project, project_id)
        if not project:
            raise NoResultFound(f"Project id '{project_id}' not found.")
        return project


# --- Project sibling suggestion helpers -----------------------------------------------------

_PROJECT_PROFILE_FILENAMES: tuple[str, ...] = (
    "README.md",
    "Readme.md",
    "readme.md",
    "AGENTS.md",
    "CLAUDE.md",
    "Claude.md",
    "agents/README.md",
    "docs/README.md",
    "docs/overview.md",
)
_PROJECT_PROFILE_MAX_TOTAL_CHARS = 6000
_PROJECT_PROFILE_PER_FILE_CHARS = 1800
_PROJECT_SIBLING_REFRESH_TTL = timedelta(hours=12)
_PROJECT_SIBLING_REFRESH_LIMIT = 3
_PROJECT_SIBLING_MIN_SUGGESTION_SCORE = 0.92


def _canonical_project_pair(a_id: int, b_id: int) -> tuple[int, int]:
    if a_id == b_id:
        raise ValueError("Project pair must reference distinct projects.")
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


async def _read_file_preview(path: Path, *, max_chars: int) -> str:
    def _read() -> str:
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                data = handle.read(max_chars + 1024)
        except Exception:
            return ""
        return (data or "").strip()[:max_chars]

    return await asyncio.to_thread(_read)


async def _build_project_profile(
    project: Project,
    agent_names: list[str],
) -> str:
    pieces: list[str] = [
        f"Identifier: {project.human_key}",
        f"Slug: {project.slug}",
        f"Agents: {', '.join(agent_names) if agent_names else 'None registered'}",
    ]

    base_path = Path(project.human_key)
    if base_path.exists():
        total_chars = 0
        seen_files: set[Path] = set()
        for rel_name in _PROJECT_PROFILE_FILENAMES:
            candidate = base_path / rel_name
            if candidate in seen_files or not candidate.exists() or not candidate.is_file():
                continue
            preview = await _read_file_preview(candidate, max_chars=_PROJECT_PROFILE_PER_FILE_CHARS)
            if not preview:
                continue
            pieces.append(f"===== {rel_name} =====\n{preview}")
            seen_files.add(candidate)
            total_chars += len(preview)
            if total_chars >= _PROJECT_PROFILE_MAX_TOTAL_CHARS:
                break
    return "\n\n".join(pieces)


def _heuristic_project_similarity(project_a: Project, project_b: Project) -> tuple[float, str]:
    # CRITICAL: Projects with identical human_key are the SAME project, not siblings
    # This should be filtered earlier, but adding safeguard here
    if project_a.human_key == project_b.human_key:
        return 0.0, "ERROR: Identical human_key - these are the SAME project, not siblings"

    slug_ratio = SequenceMatcher(None, project_a.slug, project_b.slug).ratio()
    human_ratio = SequenceMatcher(None, project_a.human_key, project_b.human_key).ratio()
    shared_prefix = 0.0
    try:
        prefix_a = Path(project_a.human_key).name.lower()
        prefix_b = Path(project_b.human_key).name.lower()
        shared_prefix = SequenceMatcher(None, prefix_a, prefix_b).ratio()
    except Exception:
        shared_prefix = 0.0

    score = max(slug_ratio, human_ratio, shared_prefix)
    reasons: list[str] = []
    if slug_ratio > 0.6:
        reasons.append(f"Slugs are similar ({slug_ratio:.2f})")
    if human_ratio > 0.6:
        reasons.append(f"Human keys align ({human_ratio:.2f})")
    parent_a = Path(project_a.human_key).parent
    parent_b = Path(project_b.human_key).parent
    if parent_a == parent_b:
        score = max(score, 0.85)
        reasons.append("Projects share the same parent directory")
    if not reasons:
        reasons.append("Heuristic comparison found limited overlap; treating as weak relation")
    return min(max(score, 0.0), 1.0), ", ".join(reasons)


async def _score_project_pair(
    project_a: Project,
    profile_a: str,
    project_b: Project,
    profile_b: str,
) -> tuple[float, str]:
    settings = get_settings()
    heuristic_score, heuristic_reason = _heuristic_project_similarity(project_a, project_b)

    if not settings.llm.enabled:
        return heuristic_score, heuristic_reason

    system_prompt = (
        "You are an expert analyst who maps whether two software projects are tightly related parts "
        "of the same overall product. Score relationship strength from 0.0 (unrelated) to 1.0 "
        "(same initiative with tightly coupled scope)."
    )
    user_prompt = (
        "Return strict JSON with keys: score (float 0-1), rationale (<=120 words).\n"
        "Focus on whether these projects represent collaborating slices of the same product.\n\n"
        f"Project A Profile:\n{profile_a}\n\nProject B Profile:\n{profile_b}"
    )

    try:
        completion = await complete_system_user(system_prompt, user_prompt, max_tokens=400)
        payload = completion.content.strip()
        data = json.loads(payload)
        score = float(data.get("score", heuristic_score))
        rationale = str(data.get("rationale", "")).strip() or heuristic_reason
        return min(max(score, 0.0), 1.0), rationale
    except Exception as exc:
        logger.debug("project_sibling.llm_failed", exc_info=exc)
        return heuristic_score, heuristic_reason + " (LLM fallback)"


async def refresh_project_sibling_suggestions(*, max_pairs: int = _PROJECT_SIBLING_REFRESH_LIMIT) -> None:
    await ensure_schema()
    async with get_session() as session:
        projects = (await session.execute(select(Project))).scalars().all()
        if len(projects) < 2:
            return

        agents_rows = await session.execute(select(Agent.project_id, Agent.name))
        agent_map: dict[int, list[str]] = defaultdict(list)
        for proj_id, name in agents_rows.fetchall():
            agent_map[int(proj_id)].append(name)

        existing_rows = (await session.execute(select(ProjectSiblingSuggestion))).scalars().all()
        existing_map: dict[tuple[int, int], ProjectSiblingSuggestion] = {}
        for suggestion in existing_rows:
            pair = _canonical_project_pair(suggestion.project_a_id, suggestion.project_b_id)
            existing_map[pair] = suggestion

        now = datetime.now(timezone.utc)
        to_evaluate: list[tuple[Project, Project, ProjectSiblingSuggestion | None]] = []
        for idx, project_a in enumerate(projects):
            if project_a.id is None:
                continue
            for project_b in projects[idx + 1 :]:
                if project_b.id is None:
                    continue

                # CRITICAL: Skip projects with identical human_key - they're the SAME project, not siblings
                # Two agents in /data/projects/smartedgar_mcp are on the SAME project
                # Siblings would be different directories like /data/projects/smartedgar_mcp_frontend
                if project_a.human_key == project_b.human_key:
                    continue

                pair = _canonical_project_pair(project_a.id, project_b.id)
                suggestion = existing_map.get(pair)
                if suggestion is None:
                    to_evaluate.append((project_a, project_b, None))
                else:
                    eval_ts = suggestion.evaluated_ts
                    # Normalize to timezone-aware UTC before arithmetic; SQLite may return naive datetimes
                    if eval_ts is not None:
                        if eval_ts.tzinfo is None or eval_ts.tzinfo.utcoffset(eval_ts) is None:
                            eval_ts = eval_ts.replace(tzinfo=timezone.utc)
                        else:
                            eval_ts = eval_ts.astimezone(timezone.utc)
                        age = now - eval_ts
                    else:
                        age = _PROJECT_SIBLING_REFRESH_TTL
                    if suggestion.status == "dismissed" and age < timedelta(days=7):
                        continue
                    if age >= _PROJECT_SIBLING_REFRESH_TTL and len(to_evaluate) < max_pairs:
                        to_evaluate.append((project_a, project_b, suggestion))
            if len(to_evaluate) >= max_pairs:
                break

        if not to_evaluate:
            return

        updated = False
        for project_a, project_b, suggestion in to_evaluate[:max_pairs]:
            profile_a = await _build_project_profile(project_a, agent_map.get(project_a.id or -1, []))
            profile_b = await _build_project_profile(project_b, agent_map.get(project_b.id or -1, []))
            score, rationale = await _score_project_pair(project_a, profile_a, project_b, profile_b)

            pair = _canonical_project_pair(project_a.id or 0, project_b.id or 0)
            record = existing_map.get(pair) if suggestion is None else suggestion
            if record is None:
                record = ProjectSiblingSuggestion(
                    project_a_id=pair[0],
                    project_b_id=pair[1],
                    score=score,
                    rationale=rationale,
                    status="suggested",
                )
                session.add(record)
                existing_map[pair] = record
            else:
                record.score = score
                record.rationale = rationale
                # Preserve user decisions
                if record.status not in {"confirmed", "dismissed"}:
                    record.status = "suggested"
            record.evaluated_ts = now
            updated = True

        if updated:
            await session.commit()


async def get_project_sibling_data() -> dict[int, dict[str, list[dict[str, Any]]]]:
    await ensure_schema()
    async with get_session() as session:
        rows = await session.execute(
            text(
                """
                SELECT s.id, s.project_a_id, s.project_b_id, s.score, s.status, s.rationale,
                       s.evaluated_ts, pa.slug AS slug_a, pa.human_key AS human_a,
                       pb.slug AS slug_b, pb.human_key AS human_b
                FROM project_sibling_suggestions s
                JOIN projects pa ON pa.id = s.project_a_id
                JOIN projects pb ON pb.id = s.project_b_id
                ORDER BY s.score DESC
                """
            )
        )
        result_map: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"confirmed": [], "suggested": []})

        for row in rows.fetchall():
            suggestion_id = int(row[0])
            a_id = int(row[1])
            b_id = int(row[2])
            entry_base = {
                "suggestion_id": suggestion_id,
                "score": float(row[3] or 0.0),
                "status": row[4],
                "rationale": row[5] or "",
                "evaluated_ts": str(row[6]) if row[6] else None,
            }
            a_info = {"id": a_id, "slug": row[7], "human_key": row[8]}
            b_info = {"id": b_id, "slug": row[9], "human_key": row[10]}

            for current, other in ((a_info, b_info), (b_info, a_info)):
                bucket = result_map[current["id"]]
                entry = {**entry_base, "peer": other}
                if entry["status"] == "confirmed":
                    bucket["confirmed"].append(entry)
                elif (
                    entry["status"] != "dismissed"
                    and float(entry_base["score"]) >= _PROJECT_SIBLING_MIN_SUGGESTION_SCORE
                ):
                    bucket["suggested"].append(entry)

        return result_map


async def update_project_sibling_status(project_id: int, other_id: int, status: str) -> dict[str, Any]:
    normalized_status = status.lower()
    if normalized_status not in {"confirmed", "dismissed", "suggested"}:
        raise ValueError("Invalid status")

    await ensure_schema()
    async with get_session() as session:
        pair = _canonical_project_pair(project_id, other_id)
        suggestion = (
            (
                await session.execute(
                    select(ProjectSiblingSuggestion).where(
                        ProjectSiblingSuggestion.project_a_id == pair[0],
                        ProjectSiblingSuggestion.project_b_id == pair[1],
                    )
                )
            )
            .scalars()
            .first()
        )

        if suggestion is None:
            # Create a baseline suggestion via refresh for this specific pair
            project_a_obj = await session.get(Project, pair[0])
            project_b_obj = await session.get(Project, pair[1])
            projects = [proj for proj in (project_a_obj, project_b_obj) if proj is not None]
            if len(projects) != 2:
                raise NoResultFound("Project pair not found")
            project_map = {proj.id: proj for proj in projects if proj.id is not None}
            agents_rows = await session.execute(
                select(Agent.project_id, Agent.name).where(
                    or_(Agent.project_id == pair[0], Agent.project_id == pair[1])
                )
            )
            agent_map: dict[int, list[str]] = defaultdict(list)
            for proj_id, name in agents_rows.fetchall():
                agent_map[int(proj_id)].append(name)
            profile_a = await _build_project_profile(project_map[pair[0]], agent_map.get(pair[0], []))
            profile_b = await _build_project_profile(project_map[pair[1]], agent_map.get(pair[1], []))
            score, rationale = await _score_project_pair(
                project_map[pair[0]], profile_a, project_map[pair[1]], profile_b
            )
            suggestion = ProjectSiblingSuggestion(
                project_a_id=pair[0],
                project_b_id=pair[1],
                score=score,
                rationale=rationale,
                status="suggested",
            )
            session.add(suggestion)
            await session.flush()

        now = datetime.now(timezone.utc)
        suggestion.status = normalized_status
        suggestion.evaluated_ts = now
        if normalized_status == "confirmed":
            suggestion.confirmed_ts = now
            suggestion.dismissed_ts = None
        elif normalized_status == "dismissed":
            suggestion.dismissed_ts = now
            suggestion.confirmed_ts = None

        await session.commit()

        project_a_obj = await session.get(Project, suggestion.project_a_id)
        project_b_obj = await session.get(Project, suggestion.project_b_id)
        project_lookup = {
            proj.id: proj for proj in (project_a_obj, project_b_obj) if proj is not None and proj.id is not None
        }

        def _project_payload(proj_id: int) -> dict[str, Any]:
            proj = project_lookup.get(proj_id)
            if proj is None:
                return {"id": proj_id, "slug": "", "human_key": ""}
            return {"id": proj.id, "slug": proj.slug, "human_key": proj.human_key}

        return {
            "id": suggestion.id,
            "status": suggestion.status,
            "score": suggestion.score,
            "rationale": suggestion.rationale,
            "project_a": _project_payload(suggestion.project_a_id),
            "project_b": _project_payload(suggestion.project_b_id),
            "evaluated_ts": str(suggestion.evaluated_ts) if suggestion.evaluated_ts else None,
        }


async def _agent_name_exists(project: Project, name: str) -> bool:
    if project.id is None:
        raise ValueError("Project must have an id before querying agents.")
    async with get_session() as session:
        result = await session.execute(
            select(Agent.id).where(
                Agent.project_id == project.id,
                func.lower(Agent.name) == name.lower(),
                cast(Any, Agent.is_active).is_(True),
            )
        )
        return result.first() is not None


async def _agent_name_exists_globally(name: str) -> bool:
    """Check if an agent name exists across ALL projects (globally unique)."""
    async with get_session() as session:
        result = await session.execute(
            select(Agent.id).where(func.lower(Agent.name) == name.lower(), cast(Any, Agent.is_active).is_(True))
        )
        return result.first() is not None


async def _get_placeholder_agent_globally(name: str) -> Optional[Agent]:
    """Get a placeholder agent by name globally, if one exists.

    Returns the Agent if it exists and is_placeholder=True, otherwise None.
    This is used to "claim" placeholder agents during official registration.
    """
    async with get_session() as session:
        result = await session.execute(
            select(Agent).where(
                func.lower(Agent.name) == name.lower(),
                cast(Any, Agent.is_active).is_(True),
                cast(Any, Agent.is_placeholder).is_(True),
            )
        )
        return result.scalars().first()


async def _generate_unique_agent_name(
    project: Project,
    settings: Settings,
    name_hint: Optional[str] = None,
    *,
    retire_conflicts: bool = False,
    include_same_project_conflicts: bool = False,
) -> str:
    async def available(candidate: str) -> bool:
        # Check globally across all projects for uniqueness
        # Database is the source of truth - filesystem check removed
        # (each project has separate archive directories, so filesystem check was project-specific)
        return not await _agent_name_exists_globally(candidate)

    mode = getattr(settings, "agent_name_enforcement_mode", "coerce").lower()
    if name_hint:
        sanitized = sanitize_agent_name(name_hint)
        if mode == "always_auto":
            sanitized = None
        if sanitized:
            if await available(sanitized):
                return sanitized
            if retire_conflicts and mode != "strict":
                await _retire_conflicting_agents(
                    sanitized,
                    project_to_keep=project,
                    settings=settings,
                    include_same_project=include_same_project_conflicts,
                )
                if await available(sanitized):
                    return sanitized
            if mode == "strict":
                raise ToolExecutionError(
                    "NAME_TAKEN",
                    f"Agent name '{sanitized}' is already in use globally.",
                    recoverable=True,
                    data={"name": sanitized},
                )
        else:
            if mode == "strict":
                raise ToolExecutionError(
                    "INVALID_ARGUMENT",
                    "Name hint must contain alphanumeric characters.",
                    recoverable=True,
                    data={"name_hint": name_hint},
                )

    if settings.environment == "test":
        preferred_test_name = "Alpha"
        if await available(preferred_test_name):
            return preferred_test_name

    for _ in range(1024):
        candidate = sanitize_agent_name(generate_agent_name())
        if candidate and await available(candidate):
            return candidate
    raise RuntimeError("Unable to generate a unique agent name.")


async def _create_agent_record(
    project: Project,
    name: str,
    program: str,
    model: str,
    task_description: str,
) -> Agent:
    if project.id is None:
        raise ValueError("Project must have an id before creating agents.")
    await ensure_schema()
    async with get_session() as session:
        agent = Agent(
            project_id=project.id,
            name=name,
            program=program,
            model=model,
            task_description=task_description,
        )
        session.add(agent)
        try:
            await session.commit()
            await session.refresh(agent)
        except IntegrityError as exc:
            await session.rollback()
            raise ToolExecutionError(
                "NAME_TAKEN",
                f"Agent name '{name}' is already in use globally.",
                recoverable=True,
                data={"name": name},
            ) from exc
        return agent


async def _build_conflict_info(name: str) -> list[dict[str, Any]]:
    """Build conflict information for agents with the given name.

    Returns a list of dictionaries containing project, program, model, and task
    information for all agents currently using the specified name.
    """
    try:
        conflicts = await _lookup_agents_any_project(name)
        return [
            {
                "project": conf_proj.human_key,
                "program": conf_agent.program,
                "model": conf_agent.model,
                "task": conf_agent.task_description,
            }
            for conf_proj, conf_agent in conflicts
        ]
    except Exception:
        return []


async def _get_or_create_agent(
    project: Project,
    name: Optional[str],
    program: str,
    model: str,
    task_description: str,
    settings: Settings,
    force_reclaim: bool = False,
) -> Agent:
    if project.id is None:
        raise ValueError("Project must have an id before creating agents.")
    mode = getattr(settings, "agent_name_enforcement_mode", "coerce").lower()
    if mode == "always_auto" or name is None:
        desired_name = await _generate_unique_agent_name(project, settings, None)
    else:
        sanitized = sanitize_agent_name(name)
        if not sanitized:
            if mode == "strict":
                raise ToolExecutionError(
                    "INVALID_ARGUMENT",
                    "Agent name must contain alphanumeric characters.",
                    recoverable=True,
                    data={"name": name},
                )
            desired_name = await _generate_unique_agent_name(project, settings, None)
        else:
            # Check if there's a placeholder agent with this name that can be claimed
            placeholder = await _get_placeholder_agent_globally(sanitized)
            if placeholder:
                # Claim the placeholder: update its details and mark as non-placeholder
                await ensure_schema()
                async with get_session() as session:
                    result = await session.execute(
                        select(Agent).where(
                            Agent.id == placeholder.id,
                            cast(Any, Agent.is_placeholder).is_(True),
                            cast(Any, Agent.is_active).is_(True),
                        )
                    )
                    agent = result.scalars().first()
                    if agent:
                        # Race condition check: verify it's still a placeholder
                        if not getattr(agent, "is_placeholder", False):
                            # Already claimed by another process, fall through to regular logic
                            pass
                        else:
                            # Update placeholder to claim it
                            agent.project_id = project.id
                            agent.program = program
                            agent.model = model
                            agent.task_description = task_description
                            agent.last_active_ts = datetime.now(timezone.utc)
                            agent.is_placeholder = False
                            # Reactivate if previously retired
                            if not getattr(agent, "is_active", True):
                                agent.is_active = True
                                agent.deleted_ts = None
                            session.add(agent)
                            await session.commit()
                            await session.refresh(agent)
                            return agent
                # If we couldn't find the agent, fall through to regular logic
            # Check if the user-provided name is globally unique
            if await _agent_name_exists_globally(sanitized):
                # Name exists globally; check if it's in THIS project
                if await _agent_name_exists(project, sanitized):
                    # Exists in this project, we'll update it below
                    desired_name = sanitized
                else:
                    # Name exists in another project
                    if mode == "strict" and not force_reclaim:
                        # In strict mode, require explicit force_reclaim
                        conflict_info = await _build_conflict_info(sanitized)
                        raise ToolExecutionError(
                            "NAME_TAKEN",
                            f"Agent name '{sanitized}' is already in use. Set force_reclaim=True to override and retire the existing agent(s).",
                            recoverable=True,
                            data={
                                "name": sanitized,
                                "conflict": "other_project",
                                "conflicting_agents": conflict_info,
                                "hint": "Call register_agent with force_reclaim=True to reclaim this name",
                            },
                        )
                    # Retire conflicting agents in other projects (auto in coerce mode, or forced via force_reclaim)
                    await _retire_conflicting_agents(
                        sanitized,
                        project_to_keep=project,
                        settings=settings,
                        include_same_project=False,
                    )
                    # Verify retirement cleared the conflict; otherwise provide a clear path
                    if await _agent_name_exists_globally(sanitized):
                        raise ToolExecutionError(
                            "NAME_TAKEN",
                            f"Agent name '{sanitized}' is still in use after attempting retirement.",
                            recoverable=True,
                            data={
                                "name": sanitized,
                                "conflict": "residual_or_race",
                                "hint": "Retry with force_reclaim=True if this persists",
                            },
                        )
                    else:
                        desired_name = sanitized
            else:
                # Globally unique, safe to use
                desired_name = sanitized
    await ensure_schema()
    async with get_session() as session:
        # Use case-insensitive matching to be consistent with _agent_name_exists() and _get_agent()
        result = await session.execute(
            select(Agent).where(
                Agent.project_id == project.id,
                func.lower(Agent.name) == desired_name.lower(),
            )
        )
        agent = result.scalars().first()
        if agent:
            agent.program = program
            agent.model = model
            agent.task_description = task_description
            agent.last_active_ts = datetime.now(timezone.utc)
            # Mark as officially registered (not a placeholder)
            agent.is_placeholder = False
            # Reactivate if previously retired
            if not getattr(agent, "is_active", True):
                agent.is_active = True
                agent.deleted_ts = None
            session.add(agent)
            try:
                await session.commit()
                await session.refresh(agent)
            except IntegrityError as exc:
                await session.rollback()
                # Race condition in UPDATE path: agent was being updated in same project,
                # but name collision occurred (likely with a different project's agent).
                # This shouldn't happen since we already verified the agent exists in this project,
                # but could occur if another process retired this agent and created a new one elsewhere.
                conflict_info = await _build_conflict_info(desired_name)
                raise ToolExecutionError(
                    "NAME_TAKEN",
                    f"Agent name '{desired_name}' is already in use globally. "
                    f"This agent may have been retired and the name claimed by another project. "
                    f"Please retry the operation.",
                    recoverable=True,
                    data={
                        "name": desired_name,
                        "race_condition": True,
                        "conflicting_agents": conflict_info,
                    },
                ) from exc
        else:
            agent = Agent(
                project_id=project.id,
                name=desired_name,
                program=program,
                model=model,
                task_description=task_description,
                contact_policy="auto",
            )
            session.add(agent)
            try:
                await session.commit()
                await session.refresh(agent)
            except IntegrityError as exc:
                await session.rollback()
                # Race condition: name was taken between our check and commit.
                # Another process claimed this name just before we could commit.
                conflict_info = await _build_conflict_info(desired_name)
                raise ToolExecutionError(
                    "NAME_TAKEN",
                    f"Agent name '{desired_name}' is already in use globally (race condition). "
                    f"Another process claimed this name before the commit completed. "
                    f"Please retry the operation. If the conflict persists, use force_reclaim=True to override.",
                    recoverable=True,
                    data={
                        "name": desired_name,
                        "race_condition": True,
                        "conflicting_agents": conflict_info,
                        "hint": "Retry the operation; if it persists, call register_agent with force_reclaim=True",
                    },
                ) from exc
    return agent


async def _create_placeholder_agent(
    project: Project,
    name: str,
    sender_program: str,
    sender_model: str,
    settings: Settings,
) -> Agent:
    """Create a placeholder agent to receive messages before official registration.

    Placeholder agents:
    - Have is_placeholder=True
    - Inherit program/model from the sender (as a reasonable default)
    - Can receive messages just like regular agents
    - Can be "claimed" by a later register_agent call, which sets is_placeholder=False

    This enables the pattern: send messages to an agent that doesn't exist yet,
    and when they register later, they can read their pending messages.
    """
    if project.id is None:
        raise ValueError("Project must have an id before creating placeholder agents.")

    sanitized = sanitize_agent_name(name)
    if not sanitized:
        raise ValueError(f"Invalid agent name for placeholder: {name}")

    await ensure_schema()
    async with get_session() as session:
        # Check if agent already exists (shouldn't happen, but be safe)
        result = await session.execute(
            select(Agent).where(
                func.lower(Agent.name) == sanitized.lower(),
                cast(Any, Agent.is_active).is_(True),
            )
        )
        existing = result.scalars().first()
        if existing:
            if not getattr(existing, "is_placeholder", False):
                raise ValueError(f"Agent '{sanitized}' already exists and is not a placeholder")
            return existing  # Placeholder already exists

        agent = Agent(
            project_id=project.id,
            name=sanitized,
            program=sender_program,
            model=sender_model,
            task_description="(pending registration)",
            contact_policy="auto",
            is_placeholder=True,
        )
        session.add(agent)
        try:
            await session.commit()
            await session.refresh(agent)
        except IntegrityError as exc:
            # Race condition: name was taken between check and commit
            await session.rollback()
            # Try to fetch the existing agent
            result = await session.execute(
                select(Agent).where(
                    func.lower(Agent.name) == sanitized.lower(),
                    cast(Any, Agent.is_active).is_(True),
                )
            )
            existing = result.scalars().first()
            if existing:
                if not getattr(existing, "is_placeholder", False):
                    raise ValueError(
                        f"Agent '{sanitized}' was created as non-placeholder during race condition"
                    ) from exc
                return existing
            raise ValueError(f"Failed to create placeholder agent: {sanitized}") from exc

    return agent


async def _delete_agent(agent: Agent, project: Project) -> dict[str, Any]:
    """Delete an agent and all related records from the database.

    This function:
    1. Deletes associated MessageRecipient records
    2. Deletes messages sent by the agent
    3. Deletes file reservations held by the agent
    4. Deletes the agent record itself

    Returns a dict with deletion statistics.
    """
    if project.id is None:
        raise ValueError("Project must have an id before deleting agents.")

    await ensure_schema()

    if agent.id is None:
        raise ValueError("Agent must have an id before deletion.")
    if agent.project_id is not None and agent.project_id != project.id:
        raise ValueError("Agent project does not match provided project; refusing cross-project deletion.")

    agent_id = agent.id
    agent_name = agent.name

    stats = {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "project": project.human_key,
        "message_recipients_deleted": 0,
        "messages_deleted": 0,
        "file_reservations_deleted": 0,
    }

    async with get_session() as session, session.begin():
        # Subquery of messages authored by this agent (keeps work in DB; avoids param limits)
        msg_ids_subq = select(Message.id).where(
            Message.sender_id == agent_id,
        )

        # 1) Delete MessageRecipient records where this agent is the recipient
        res1 = await session.execute(delete(MessageRecipient).where(MessageRecipient.agent_id == agent_id))
        stats["message_recipients_deleted"] = int(res1.rowcount or 0)

        # 2) Delete MessageRecipient records for messages authored by this agent
        #    (Must be done BEFORE deleting the messages to avoid FK violations)
        res2 = await session.execute(
            delete(MessageRecipient).where(cast(Any, MessageRecipient.message_id).in_(msg_ids_subq))
        )
        stats["message_recipients_deleted"] += int(res2.rowcount or 0)

        # 3) Now safe to delete messages sent by the agent
        res3 = await session.execute(delete(Message).where(Message.sender_id == agent_id))
        stats["messages_deleted"] = int(res3.rowcount or 0)

        # 4) Delete file reservations
        res4 = await session.execute(delete(FileReservation).where(FileReservation.agent_id == agent_id))
        stats["file_reservations_deleted"] = int(res4.rowcount or 0)

        # 5) Finally, delete the agent itself
        await session.execute(delete(Agent).where(Agent.id == agent_id))

    return stats


async def _lookup_agents_any_project(name: str, include_inactive: bool = False) -> list[tuple[Project, Agent]]:
    """Return all (project, agent) pairs matching a given agent name globally."""

    target = (name or "").strip()
    if not target:
        return []
    await ensure_schema()
    async with get_session() as session:
        stmt = (
            select(Project, Agent)
            .join(Agent, Agent.project_id == Project.id)
            .where(func.lower(Agent.name) == target.lower())
        )
        if not include_inactive:
            stmt = stmt.where(cast(Any, Agent.is_active).is_(True))
        result = await session.execute(stmt)
        return [(proj, agent) for proj, agent in result.all() if proj and agent]


async def _retire_agent(agent: Agent, project: Project, settings: Settings) -> Agent:
    """Mark an agent inactive so its name can be reused elsewhere (history is preserved)."""

    if agent.id is None:
        return agent
    await ensure_schema()
    async with get_session() as session:
        db_agent = await session.get(Agent, agent.id)
        if db_agent is None or not getattr(db_agent, "is_active", True):
            return agent
        db_agent.is_active = False
        db_agent.deleted_ts = datetime.now(timezone.utc)
        session.add(db_agent)
        # Release any outstanding reservations
        await session.execute(
            update(FileReservation)
            .where(
                FileReservation.agent_id == db_agent.id,
                cast(Any, FileReservation.released_ts).is_(None),
            )
            .values(released_ts=datetime.now(timezone.utc))
        )
        await session.commit()
        await session.refresh(db_agent)
        agent = db_agent

    return agent


async def _retire_conflicting_agents(
    name: str,
    *,
    project_to_keep: Project,
    settings: Settings,
    include_same_project: bool = False,
) -> None:
    """Retire any active agents with the requested name outside the current project."""

    conflicts = [
        (proj, agent)
        for proj, agent in await _lookup_agents_any_project(name)
        if include_same_project or proj.id != project_to_keep.id
    ]
    if not conflicts:
        return
    for conflict_project, conflict_agent in conflicts:
        await _retire_agent(conflict_agent, conflict_project, settings)


async def _get_agent(project: Project, name: str) -> Agent:
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(Agent).where(
                Agent.project_id == project.id,
                func.lower(Agent.name) == name.lower(),
                cast(Any, Agent.is_active).is_(True),
            )
        )
        agent = result.scalars().first()
        if not agent:
            raise NoResultFound(
                f"Agent '{name}' not registered for project '{project.human_key}'. "
                "Tip: Use resource://agents to discover registered agents globally."
            )
        return agent


async def _get_agent_optional(project: Project, name: str) -> Agent | None:
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(Agent).where(
                Agent.project_id == project.id,
                func.lower(Agent.name) == name.lower(),
                cast(Any, Agent.is_active).is_(True),
            )
        )
        return result.scalars().first()


async def _get_agent_by_name(name: str) -> Agent:
    """Get agent by name alone, ignoring project boundaries.

    Since agent names are globally unique, we can look up agents
    by name without needing project context.
    """
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(Agent).where(
                func.lower(Agent.name) == name.lower(),
                cast(Any, Agent.is_active).is_(True),
            )
        )
        agent = result.scalars().first()
        if not agent:
            raise NoResultFound(f"Agent '{name}' not found. Tip: Use register_agent to create a new agent.")
        return agent


async def _get_agent_by_name_optional(name: str) -> Agent | None:
    """Get agent by name alone, returning None if not found."""
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(Agent).where(
                func.lower(Agent.name) == name.lower(),
                cast(Any, Agent.is_active).is_(True),
            )
        )
        return result.scalars().first()


async def _find_similar_agents(name: str, limit: int = 5) -> list[str]:
    """Find agent names similar to the given name for suggestions.

    Uses multiple strategies to find similar names:
    1. Case variations (exact match with different case)
    2. Prefix matches (agent names starting with the input, e.g., "BlueLake" for "Blue")
    3. Reverse prefix matches (agent names that are prefixes of the input, e.g., "Blue" for "BlueLake")
    4. Substring matches (agent names containing the input, e.g., "BlueLake" for "Lake")
    5. Reverse substring matches (agent names that are substrings of the input, e.g., "Blue" for "BlueLakeExtra")
    """
    target = (name or "").strip()
    if not target:
        return []

    await ensure_schema()
    suggestions: list[str] = []
    name_lower = target.lower()

    async with get_session() as session:
        # Get all active agent names
        result = await session.execute(select(Agent.name).where(cast(Any, Agent.is_active).is_(True)))
        all_names = [row[0] for row in result.all()]

    # Strategy 1: Exact case-insensitive match (shouldn't happen, but just in case)
    for agent_name in all_names:
        if agent_name.lower() == name_lower:
            suggestions.append(agent_name)

    # Strategy 2: Prefix matches (e.g., "Blue" matches "BlueLake")
    for agent_name in all_names:
        if agent_name.lower().startswith(name_lower) and agent_name not in suggestions:
            suggestions.append(agent_name)
        if len(suggestions) >= limit:
            break

    # Strategy 3: Agent names that are prefixes of the input (e.g., "Blue" when searching "BlueLake")
    if len(suggestions) < limit:
        for agent_name in all_names:
            if name_lower.startswith(agent_name.lower()) and agent_name not in suggestions:
                suggestions.append(agent_name)
            if len(suggestions) >= limit:
                break

    # Strategy 4: Substring matches (e.g., "Lake" matches "BlueLake")
    if len(suggestions) < limit:
        for agent_name in all_names:
            if name_lower in agent_name.lower() and agent_name not in suggestions:
                suggestions.append(agent_name)
            if len(suggestions) >= limit:
                break

    # Strategy 5: Agent names that are substrings of the input (e.g., "Blue" when searching "BlueLakeExtra")
    if len(suggestions) < limit:
        for agent_name in all_names:
            if agent_name.lower() in name_lower and agent_name not in suggestions:
                suggestions.append(agent_name)
            if len(suggestions) >= limit:
                break

    return suggestions[:limit]


async def _create_message(
    project: Optional[Project],
    sender: Agent,
    subject: str,
    body_md: str,
    recipients: Sequence[tuple[Agent, str]],
    importance: str,
    ack_required: bool,
    thread_id: Optional[str],
    attachments: Sequence[dict[str, Any]],
) -> Message:
    # project_id is now optional - messages can exist without project context
    project_id = project.id if project else None
    if sender.id is None:
        raise ValueError("Sender must have an id before sending messages.")
    create_start = time.perf_counter()
    await ensure_schema()
    schema_elapsed = time.perf_counter() - create_start
    async with get_session() as session:
        session_start = time.perf_counter()
        message = Message(
            project_id=project_id,
            sender_id=sender.id,
            subject=subject,
            body_md=body_md,
            importance=importance,
            ack_required=ack_required,
            thread_id=thread_id,
            attachments=list(attachments),
        )
        session.add(message)
        flush_start = time.perf_counter()
        await session.flush()
        flush_elapsed = time.perf_counter() - flush_start
        if message.id is None:
            raise RuntimeError("Message id was not assigned after flush().")
        for recipient, kind in recipients:
            if recipient.id is None:
                raise ValueError(f"Recipient '{recipient.name}' must have an id before sending messages.")
            entry = MessageRecipient(message_id=message.id, agent_id=recipient.id, kind=kind)
            session.add(entry)
        sender.last_active_ts = datetime.now(timezone.utc)
        session.add(sender)
        commit_start = time.perf_counter()
        await session.commit()
        commit_elapsed = time.perf_counter() - commit_start
        refresh_start = time.perf_counter()
        await session.refresh(message)
        refresh_elapsed = time.perf_counter() - refresh_start
        session_elapsed = time.perf_counter() - session_start
    total_elapsed = time.perf_counter() - create_start
    logger.debug(
        "[LATENCY] _create_message: total=%.3fs schema=%.3fs session=%.3fs "
        "(flush=%.3fs commit=%.3fs refresh=%.3fs) msg_id=%s",
        total_elapsed,
        schema_elapsed,
        session_elapsed,
        flush_elapsed,
        commit_elapsed,
        refresh_elapsed,
        message.id,
    )
    return message


async def _create_file_reservation(
    project: Project,
    agent: Agent,
    path: str,
    exclusive: bool,
    reason: str,
    ttl_seconds: int,
) -> FileReservation:
    if project.id is None or agent.id is None:
        raise ValueError("Project and agent must have ids before creating file_reservations.")
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    await ensure_schema()
    async with get_session() as session:
        file_reservation = FileReservation(
            project_id=project.id,
            agent_id=agent.id,
            path_pattern=path,
            exclusive=exclusive,
            reason=reason,
            expires_ts=expires,
        )
        session.add(file_reservation)
        await session.commit()
        await session.refresh(file_reservation)
    return file_reservation


async def _collect_file_reservation_statuses(
    project: Project,
    *,
    include_released: bool = False,
    now: Optional[datetime] = None,
) -> list[FileReservationStatus]:
    if project.id is None:
        return []
    await ensure_schema()
    moment = now or datetime.now(timezone.utc)
    settings = get_settings()
    inactivity_seconds = max(0, int(settings.file_reservation_inactivity_seconds))
    activity_grace = max(0, int(settings.file_reservation_activity_grace_seconds))

    async with get_session() as session:
        stmt = (
            select(FileReservation, Agent)
            .join(Agent, FileReservation.agent_id == Agent.id)
            .where(FileReservation.project_id == project.id)
            .order_by(asc(FileReservation.created_ts))
        )
        if not include_released:
            stmt = stmt.where(cast(Any, FileReservation.released_ts).is_(None))
        result = await session.execute(stmt)
        rows = result.all()
        if not rows:
            return []
        agent_ids = [agent.id for _, agent in rows if agent.id is not None]
        send_map: dict[int, Optional[datetime]] = {}
        ack_map: dict[int, Optional[datetime]] = {}
        read_map: dict[int, Optional[datetime]] = {}
        if agent_ids:
            send_result = await session.execute(
                select(Message.sender_id, func.max(Message.created_ts))
                .where(
                    Message.project_id == project.id,
                    cast(Any, Message.sender_id).in_(agent_ids),
                )
                .group_by(Message.sender_id)
            )
            send_map = {row[0]: _ensure_utc(row[1]) for row in send_result}
            ack_result = await session.execute(
                select(MessageRecipient.agent_id, func.max(MessageRecipient.ack_ts))
                .join(Message, MessageRecipient.message_id == Message.id)
                .where(
                    Message.project_id == project.id,
                    cast(Any, MessageRecipient.agent_id).in_(agent_ids),
                    cast(Any, MessageRecipient.ack_ts).is_not(None),
                )
                .group_by(MessageRecipient.agent_id)
            )
            ack_map = {row[0]: _ensure_utc(row[1]) for row in ack_result}
            read_result = await session.execute(
                select(MessageRecipient.agent_id, func.max(MessageRecipient.read_ts))
                .join(Message, MessageRecipient.message_id == Message.id)
                .where(
                    Message.project_id == project.id,
                    cast(Any, MessageRecipient.agent_id).in_(agent_ids),
                    cast(Any, MessageRecipient.read_ts).is_not(None),
                )
                .group_by(MessageRecipient.agent_id)
            )
            read_map = {row[0]: _ensure_utc(row[1]) for row in read_result}

    workspace = _project_workspace_path(project)
    repo = _open_repo_if_available(workspace) if workspace is not None else None

    statuses: list[FileReservationStatus] = []
    for reservation, agent in rows:
        agent_id = agent.id or -1
        agent_last_active = _ensure_utc(agent.last_active_ts)
        last_mail = _max_datetime(send_map.get(agent_id), ack_map.get(agent_id), read_map.get(agent_id))

        matches: list[Path] = []
        fs_activity: Optional[datetime] = None
        git_activity: Optional[datetime] = None

        if workspace is not None:
            matches = _collect_matching_paths(workspace, reservation.path_pattern)
            if matches:
                fs_activity = _latest_filesystem_activity(matches)
                git_activity = _latest_git_activity(repo, matches)

        agent_inactive = agent_last_active is None or (moment - agent_last_active).total_seconds() > inactivity_seconds
        recent_mail = last_mail is not None and (moment - last_mail).total_seconds() <= activity_grace
        recent_fs = fs_activity is not None and (moment - fs_activity).total_seconds() <= activity_grace
        recent_git = git_activity is not None and (moment - git_activity).total_seconds() <= activity_grace

        stale = bool(
            reservation.released_ts is None and agent_inactive and not (recent_mail or recent_fs or recent_git)
        )
        reasons: list[str] = []
        if agent_inactive:
            reasons.append(f"agent_inactive>{inactivity_seconds}s")
        else:
            reasons.append("agent_recently_active")
        if recent_mail:
            reasons.append("mail_activity_recent")
        else:
            reasons.append(f"no_recent_mail_activity>{activity_grace}s")
        if matches:
            if recent_fs:
                reasons.append("filesystem_activity_recent")
            else:
                reasons.append(f"no_recent_filesystem_activity>{activity_grace}s")
            if recent_git:
                reasons.append("git_activity_recent")
            else:
                reasons.append(f"no_recent_git_activity>{activity_grace}s")
        else:
            reasons.append("path_pattern_unmatched")

        statuses.append(
            FileReservationStatus(
                reservation=reservation,
                agent=agent,
                stale=stale,
                stale_reasons=reasons,
                last_agent_activity=agent_last_active,
                last_mail_activity=last_mail,
                last_fs_activity=fs_activity,
                last_git_activity=git_activity,
            )
        )
    return statuses


async def _expire_stale_file_reservations(project_id: int) -> list[FileReservationStatus]:
    await ensure_schema()
    now = datetime.now(timezone.utc)

    project: Optional[Project] = None
    async with get_session() as session:
        project = await session.get(Project, project_id)
    if project is None:
        return []

    # Release any entries whose TTL has already elapsed
    async with get_session() as session:
        await session.execute(
            update(FileReservation)
            .where(
                FileReservation.project_id == project_id,
                cast(Any, FileReservation.released_ts).is_(None),
                FileReservation.expires_ts < now,
            )
            .values(released_ts=now)
        )
        await session.commit()

    statuses = await _collect_file_reservation_statuses(project, include_released=False, now=now)
    stale_statuses = [status for status in statuses if status.stale and status.reservation.id is not None]
    stale_ids = [cast(int, status.reservation.id) for status in stale_statuses]
    if not stale_ids:
        return []

    async with get_session() as session:
        await session.execute(
            update(FileReservation)
            .where(
                FileReservation.project_id == project_id,
                cast(Any, FileReservation.id).in_(stale_ids),
                cast(Any, FileReservation.released_ts).is_(None),
            )
            .values(released_ts=now)
        )
        await session.commit()

    for status in stale_statuses:
        status.reservation.released_ts = now
    return stale_statuses


def _file_reservations_conflict(
    existing: FileReservation, candidate_path: str, candidate_exclusive: bool, candidate_agent: Agent
) -> bool:
    if existing.released_ts is not None:
        return False
    if existing.agent_id == candidate_agent.id:
        return False
    if not existing.exclusive and not candidate_exclusive:
        return False
    normalized_existing = existing.path_pattern
    # Allow **/ patterns to match files at the immediate directory level too
    fallback_existing = normalized_existing.replace("**/", "")

    # Treat simple directory patterns like "src/*" as inclusive of files under that directory
    # when comparing against concrete file paths like "src/app.py".
    def _expand_dir_star(p: str) -> str:
        if p.endswith("/*"):
            return p[:-1] + "*"  # "src/*" -> "src/**"-like breadth for fnmatchcase approximation
        return p

    a = _expand_dir_star(candidate_path)
    b = _expand_dir_star(normalized_existing)
    b_fallback = _expand_dir_star(fallback_existing)
    return (
        fnmatch.fnmatchcase(a, b)
        or fnmatch.fnmatchcase(b, a)
        or fnmatch.fnmatchcase(a, b_fallback)
        or fnmatch.fnmatchcase(b_fallback, a)
        or a == b
    )


def _patterns_overlap(a: str, b: str) -> bool:
    # Normalize simple relative prefixes for matching
    def _norm(s: str) -> str:
        while s.startswith("./"):
            s = s[2:]
        return s

    a1 = _norm(a)
    b1 = _norm(b)
    return fnmatch.fnmatchcase(a1, b1) or fnmatch.fnmatchcase(b1, a1) or a1 == b1


def _file_reservations_patterns_overlap(paths_a: Sequence[str], paths_b: Sequence[str]) -> bool:
    for pa in paths_a:
        for pb in paths_b:
            if _patterns_overlap(pa, pb):
                return True
    return False


async def _list_inbox(
    project: Project,
    agent: Agent,
    limit: int,
    urgent_only: bool,
    include_bodies: bool,
    since_ts: Optional[str],
) -> list[dict[str, Any]]:
    list_inbox_start = time.perf_counter()
    if agent.id is None:
        raise ValueError("Agent must have an id before listing inbox.")

    global_inbox_name = get_global_inbox_name(project)

    # Skip global inbox scanning if the agent IS the global inbox (prevent recursion)
    if agent.name == global_inbox_name:
        messages = await _list_inbox_basic(agent, limit, urgent_only, include_bodies, since_ts)
        elapsed = time.perf_counter() - list_inbox_start
        logger.debug(
            "[LATENCY] _list_inbox (global inbox agent): total=%.3fs count=%d agent=%s",
            elapsed,
            len(messages),
            agent.name,
        )
        return messages

    # Get regular inbox messages
    basic_start = time.perf_counter()
    messages = await _list_inbox_basic(agent, limit, urgent_only, include_bodies, since_ts)
    basic_elapsed = time.perf_counter() - basic_start
    message_ids_in_inbox: set[int] = set()
    for msg in messages:
        msg_id = msg.get("id")
        if msg_id is None:
            continue
        try:
            message_ids_in_inbox.add(int(msg_id))
        except (TypeError, ValueError):
            continue

    # Scan global inbox for messages mentioning this agent using FTS5 (much faster than regex)
    fts_elapsed = 0.0
    basic_count = len(messages)  # Track count before FTS merge
    fts_requested_count = 0
    fts_included_count = 0
    try:
        fts_start = time.perf_counter()
        global_inbox_agent = await _get_agent_by_name(global_inbox_name)
        # Use FTS5-based mention search - only fetches messages that actually mention the agent
        # This is significantly faster than the old approach which loaded 100 messages with bodies
        mentioned_messages = await _find_mentions_in_global_inbox(
            agent_name=agent.name,
            global_inbox_agent=global_inbox_agent,
            exclude_message_ids=message_ids_in_inbox,
            include_bodies=include_bodies,
            since_ts=since_ts,
            limit=30,  # Reduced from 100 - FTS5 query is precise, doesn't need to over-fetch
        )
        fts_elapsed = time.perf_counter() - fts_start
        fts_requested_count = len(mentioned_messages)

        # Merge with regular inbox, respecting the limit
        messages.extend(mentioned_messages)
        if len(messages) > limit:
            messages = messages[:limit]
        # Calculate actual FTS count included after truncation
        fts_included_count = max(0, len(messages) - basic_count)

    except Exception as exc:
        # If global inbox doesn't exist or there's an error, just return regular inbox
        logger.debug("global_inbox_fts_failed", exc_info=exc)

    total_elapsed = time.perf_counter() - list_inbox_start
    logger.debug(
        "[LATENCY] _list_inbox: total=%.3fs basic=%.3fs fts=%.3fs basic_count=%d "
        "fts_included=%d fts_requested=%d final_count=%d agent=%s",
        total_elapsed,
        basic_elapsed,
        fts_elapsed,
        basic_count,
        fts_included_count,
        fts_requested_count,
        len(messages),
        agent.name,
    )
    return messages


async def _find_mentions_in_global_inbox(
    agent_name: str,
    global_inbox_agent: Agent,
    exclude_message_ids: set[int],
    include_bodies: bool,
    since_ts: Optional[str],
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Use FTS5 to efficiently find messages mentioning the agent in global inbox.

    This is much faster than loading all messages and doing regex in Python.
    """
    if global_inbox_agent.id is None:
        return []

    await ensure_schema()
    sender_alias = aliased(Agent)
    # fts_messages is a SQLite FTS5 virtual table created by db._setup_fts(). It is not part of SQLModel metadata,
    # so we reference it via a lightweight Table construct for ORM-safe joins.
    fts_messages = Table(
        "fts_messages",
        MetaData(),
        Column("rowid", Integer),
        Column("message_id", Integer),
        Column("subject"),
        Column("body"),
    )
    fts_query = f'"{agent_name}"'

    async with get_session() as session:
        stmt = (
            select(Message, MessageRecipient.kind, sender_alias.name)
            .join(MessageRecipient, MessageRecipient.message_id == Message.id)
            .join(sender_alias, Message.sender_id == sender_alias.id)
            .where(
                MessageRecipient.agent_id == global_inbox_agent.id,
                text("fts_messages MATCH :agent_name"),
            )
            .order_by(desc(Message.created_ts))
        )

        if since_ts:
            since_dt = _parse_iso(since_ts)
            if since_dt:
                stmt = stmt.where(Message.created_ts > since_dt)

        # Apply limit after all filters for clarity and maintainability
        stmt = stmt.limit(limit)

        stmt = stmt.join(fts_messages, Message.id == fts_messages.c.rowid)

        result = await session.execute(stmt, {"agent_name": fts_query})
        rows = result.all()

    messages: list[dict[str, Any]] = []
    for message, recipient_kind, sender_name in rows:
        # Skip if already in regular inbox
        if message.id is None:
            continue
        if message.id in exclude_message_ids:
            continue

        payload = _message_to_dict(message, include_body=include_bodies)
        payload["from"] = sender_name
        payload["kind"] = recipient_kind
        payload["source"] = "global_inbox_mention"
        messages.append(payload)

    return messages


async def _list_inbox_basic(
    agent: Agent,
    limit: int,
    urgent_only: bool,
    include_bodies: bool,
    since_ts: Optional[str],
) -> list[dict[str, Any]]:
    """Basic inbox listing without global inbox scanning."""
    basic_start = time.perf_counter()
    if agent.id is None:
        raise ValueError("Agent must have an id before listing inbox.")
    sender_alias = aliased(Agent)
    schema_start = time.perf_counter()
    await ensure_schema()
    schema_elapsed = time.perf_counter() - schema_start
    query_start = time.perf_counter()
    async with get_session() as session:
        stmt = (
            select(Message, MessageRecipient.kind, sender_alias.name)
            .join(MessageRecipient, MessageRecipient.message_id == Message.id)
            .join(sender_alias, Message.sender_id == sender_alias.id)
            .where(
                MessageRecipient.agent_id == agent.id,
            )
            .order_by(desc(Message.created_ts))
        )
        if urgent_only:
            stmt = stmt.where(cast(Any, Message.importance).in_(["high", "urgent"]))
        if since_ts:
            since_dt = _parse_iso(since_ts)
            if since_dt:
                stmt = stmt.where(Message.created_ts > since_dt)
        # Apply limit after all filters for clarity and maintainability
        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        rows = result.all()
    query_elapsed = time.perf_counter() - query_start
    messages: list[dict[str, Any]] = []
    for message, recipient_kind, sender_name in rows:
        payload = _message_to_dict(message, include_body=include_bodies)
        payload["from"] = sender_name
        payload["kind"] = recipient_kind
        messages.append(payload)
    total_elapsed = time.perf_counter() - basic_start
    logger.debug(
        "[LATENCY] _list_inbox_basic: total=%.3fs schema=%.3fs query=%.3fs count=%d agent=%s",
        total_elapsed,
        schema_elapsed,
        query_elapsed,
        len(messages),
        agent.name,
    )
    return messages


async def _list_outbox(
    project: Project,
    agent: Agent,
    limit: int,
    include_bodies: bool,
    since_ts: Optional[str],
) -> list[dict[str, Any]]:
    """List messages sent by the agent (their outbox)."""
    if agent.id is None:
        raise ValueError("Agent must have an id before listing outbox.")
    await ensure_schema()
    messages: list[dict[str, Any]] = []
    async with get_session() as session:
        stmt = select(Message).where(Message.sender_id == agent.id).order_by(desc(Message.created_ts))
        if since_ts:
            since_dt = _parse_iso(since_ts)
            if since_dt:
                stmt = stmt.where(Message.created_ts > since_dt)
        # Apply limit after all filters for clarity and maintainability
        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        message_rows = result.scalars().all()

        # Batch load all recipients for all messages in a single query (avoids N+1)
        message_ids = [msg.id for msg in message_rows]
        if message_ids:
            recipients_result = await session.execute(
                select(MessageRecipient.message_id, MessageRecipient.kind, Agent.name)
                .join(Agent, MessageRecipient.agent_id == Agent.id)
                .where(cast(Any, MessageRecipient.message_id).in_(message_ids))
            )
            # Group recipients by message_id
            recipients_by_message: dict[str, dict[str, list[str]]] = {}
            for msg_id, kind, name in recipients_result.all():
                if msg_id not in recipients_by_message:
                    recipients_by_message[msg_id] = {"to": [], "cc": [], "bcc": []}
                recipients_by_message[msg_id][kind].append(name)
        else:
            recipients_by_message = {}

        # Build message payloads with pre-loaded recipients
        for msg in message_rows:
            recipients = recipients_by_message.get(msg.id, {"to": [], "cc": [], "bcc": []})
            payload = _message_to_dict(msg, include_body=include_bodies)
            payload["from"] = agent.name
            payload["to"] = recipients["to"]
            payload["cc"] = recipients["cc"]
            payload["bcc"] = recipients["bcc"]
            messages.append(payload)
    return messages


def _canonical_relpath_for_message(project: Project, message: Message, archive) -> str | None:
    """Resolve the canonical repo-relative path for a message markdown file.

    NOTE: Archive storage has been removed. This always returns None.
    Deprecated: parameters are retained for backwards compatibility.
    """
    return None


async def _commit_info_for_message(settings: Settings, project: Project, message: Message) -> dict[str, Any] | None:
    """Fetch commit metadata for the canonical message file.

    NOTE: Archive storage has been removed. This always returns None.
    Deprecated: parameters are retained for backwards compatibility.
    """
    return None


def _summarize_messages(messages: Sequence[tuple[Message, str]]) -> dict[str, Any]:
    participants: set[str] = set()
    key_points: list[str] = []
    action_items: list[str] = []
    open_actions = 0
    done_actions = 0
    mentions: dict[str, int] = {}
    code_references: set[str] = set()
    keywords = ("TODO", "ACTION", "FIXME", "NEXT", "BLOCKED")

    def _record_mentions(text: str) -> None:
        # very lightweight @mention parser
        for token in text.split():
            if token.startswith("@") and len(token) > 1:
                name = token[1:].strip(".,:;()[]{}")
                if name:
                    mentions[name] = mentions.get(name, 0) + 1

    def _maybe_code_ref(text: str) -> None:
        # capture backtick-enclosed references that look like files/paths
        start = 0
        while True:
            i = text.find("`", start)
            if i == -1:
                break
            j = text.find("`", i + 1)
            if j == -1:
                break
            snippet = text[i + 1 : j].strip()
            if ("/" in snippet or ".py" in snippet or ".ts" in snippet or ".md" in snippet) and (
                1 <= len(snippet) <= 120
            ):
                code_references.add(snippet)
            start = j + 1

    for message, sender_name in messages:
        participants.add(sender_name)
        for line in message.body_md.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            _record_mentions(stripped)
            _maybe_code_ref(stripped)
            # bullet points and ordered lists → key points
            if stripped.startswith(("-", "*", "+")) or stripped[:2] in {"1.", "2.", "3.", "4.", "5."}:
                # normalize checkbox bullets to plain text for key points
                normalized = stripped
                if normalized.startswith(("- [ ]", "- [x]", "- [X]")):
                    normalized = normalized.split("]", 1)[-1].strip()
                key_points.append(normalized.lstrip("-+* "))
            # checkbox TODOs
            if stripped.startswith(("- [ ]", "* [ ]", "+ [ ]")):
                open_actions += 1
                action_items.append(stripped)
                continue
            if stripped.startswith(("- [x]", "- [X]", "* [x]", "* [X]", "+ [x]", "+ [X]")):
                done_actions += 1
                action_items.append(stripped)
                continue
            # keyword-based action detection
            upper = stripped.upper()
            if any(token in upper for token in keywords):
                action_items.append(stripped)

    # Sort mentions by frequency desc
    sorted_mentions = sorted(mentions.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    summary: dict[str, Any] = {
        "participants": sorted(participants),
        "key_points": key_points[:10],
        "action_items": action_items[:10],
        "total_messages": len(messages),
        "open_actions": open_actions,
        "done_actions": done_actions,
        "mentions": [{"name": name, "count": count} for name, count in sorted_mentions],
    }
    if code_references:
        summary["code_references"] = sorted(code_references)[:10]
    return summary


async def _compute_thread_summary(
    project: Project,
    thread_id: str,
    include_examples: bool,
    llm_mode: bool,
    llm_model: Optional[str],
    *,
    per_thread_limit: Optional[int] = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    if project.id is None:
        raise ValueError("Project must have an id before summarizing threads.")
    await ensure_schema()
    sender_alias = aliased(Agent)
    try:
        message_id = int(thread_id)
    except ValueError:
        message_id = None
    criteria = [Message.thread_id == thread_id]
    if message_id is not None:
        criteria.append(Message.id == message_id)
    async with get_session() as session:
        stmt = (
            select(Message, sender_alias.name)
            .join(sender_alias, Message.sender_id == sender_alias.id)
            .where(Message.project_id == project.id, or_(*criteria))
            .order_by(asc(Message.created_ts))
        )
        if per_thread_limit:
            stmt = stmt.limit(per_thread_limit)
        result = await session.execute(stmt)
        rows = result.all()
    summary = _summarize_messages(rows)

    if llm_mode and get_settings().llm.enabled:
        try:
            excerpts: list[str] = []
            for message, sender_name in rows[:15]:
                excerpts.append(f"- {sender_name}: {message.subject}\n{message.body_md[:800]}")
            if excerpts:
                system = (
                    "You are a senior engineer. Produce a concise JSON summary with keys: "
                    "participants[], key_points[], action_items[], mentions[{name,count}], code_references[], "
                    "total_messages, open_actions, done_actions. Derive from the given thread excerpts."
                )
                user = "\n\n".join(excerpts)
                llm_resp = await complete_system_user(system, user, model=llm_model)
                parsed = _parse_json_safely(llm_resp.content)
                if parsed:
                    for key in (
                        "participants",
                        "key_points",
                        "action_items",
                        "mentions",
                        "code_references",
                        "total_messages",
                        "open_actions",
                        "done_actions",
                    ):
                        value = parsed.get(key)
                        if value:
                            summary[key] = value
        except Exception as e:
            logger.debug("thread_summary.llm_skipped", extra={"thread_id": thread_id, "error": str(e)})

    examples: list[dict[str, Any]] = []
    if include_examples:
        for message, sender_name in rows[:3]:
            examples.append(
                {
                    "id": message.id,
                    "subject": message.subject,
                    "from": sender_name,
                    "created_ts": _iso(message.created_ts),
                }
            )
    return summary, examples, len(rows)


async def _get_message(project: Project, message_id: int) -> Message:
    if project.id is None:
        raise ValueError("Project must have an id before reading messages.")
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(Message).where(Message.project_id == project.id, Message.id == message_id)
        )
        message = result.scalars().first()
        if not message:
            raise NoResultFound(f"Message '{message_id}' not found for project '{project.human_key}'.")
        return message


async def _get_message_by_id_global(message_id: int) -> Message:
    """Fetch message by ID globally (ignoring project boundaries).

    Projects are informational only - messages are globally accessible by ID.
    This allows agents to reply to messages they received regardless of which
    project context they're currently operating in.
    """
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(select(Message).where(Message.id == message_id))
        message = result.scalars().first()
        if not message:
            raise NoResultFound(f"Message id '{message_id}' not found.")
        return message


async def _get_agent_by_id(project: Project, agent_id: int) -> Agent:
    """Fetch active agent by ID within project."""
    if project.id is None:
        raise ValueError("Project must have an id before querying agents.")
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(Agent).where(
                Agent.project_id == project.id,
                Agent.id == agent_id,
                cast(Any, Agent.is_active).is_(True),
            )
        )
        agent = result.scalars().first()
        if not agent:
            raise NoResultFound(f"Agent id '{agent_id}' not found (or inactive) for project '{project.human_key}'.")
        return agent


async def _get_agent_by_id_global(agent_id: int) -> Agent:
    """Fetch active agent by ID globally (ignoring project boundaries)."""
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(Agent).where(
                Agent.id == agent_id,
                cast(Any, Agent.is_active).is_(True),
            )
        )
        agent = result.scalars().first()
        if not agent:
            raise NoResultFound(f"Agent id '{agent_id}' not found or inactive.")
        return agent


async def _update_recipient_timestamp(
    agent: Agent,
    message_id: int,
    field: str,
) -> Optional[datetime]:
    if agent.id is None:
        raise ValueError("Agent must have an id before updating message state.")
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        # Read current value first
        result_sel = await session.execute(
            select(MessageRecipient).where(
                MessageRecipient.message_id == message_id,
                MessageRecipient.agent_id == agent.id,
            )
        )
        rec = result_sel.scalars().first()
        if not rec:
            return None
        current: Optional[datetime] = getattr(rec, field, None)
        if current is not None:
            # Already set; return existing value without updating
            return _ensure_utc(current)
        # Set only if null
        stmt = (
            update(MessageRecipient)
            .where(MessageRecipient.message_id == message_id, MessageRecipient.agent_id == agent.id)
            .values({field: now})
        )
        await session.execute(stmt)
        await session.commit()
    return now


async def _get_recipient_timestamp(agent: Agent, message_id: int, field: str) -> Optional[datetime]:
    if agent.id is None:
        raise ValueError("Agent must have an id before reading message state.")
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(getattr(MessageRecipient, field)).where(
                MessageRecipient.message_id == message_id,
                MessageRecipient.agent_id == agent.id,
            )
        )
        return _ensure_utc(result.scalars().first())


async def _validate_agent_is_recipient(agent: Agent, message_id: int) -> None:
    """Validate that an agent is a recipient of a message.

    Raises NoResultFound if the agent is not a recipient of the message.
    This prevents agents from marking messages as read/acknowledged when
    they never received them.
    """
    if agent.id is None:
        raise ValueError("Agent must have an id before validation.")
    await ensure_schema()
    async with get_session() as session:
        result = await session.execute(
            select(MessageRecipient).where(
                MessageRecipient.message_id == message_id,
                MessageRecipient.agent_id == agent.id,
            )
        )
        recipient = result.scalars().first()
        if not recipient:
            raise NoResultFound(
                f"Agent '{agent.name}' is not a recipient of message {message_id}. "
                f"Only recipients can mark messages as read or acknowledged."
            )


# Tool exposure configuration for lazy loading
# Core tools (~9k tokens): Essential coordination functionality
CORE_TOOLS = {
    "health_check",
    "ensure_project",
    "register_agent",
    "whois",
    "send_message",
    "reply_message",
    "fetch_inbox",
    "mark_message_read",
    "search_mailbox",
}

# Extended tools (~16k tokens): Advanced features available via meta-tools
EXTENDED_TOOLS = {
    "create_agent_identity",
    "delete_agent",
    "acknowledge_message",
    "search_messages",
    "create_file_reservation",
    "file_reservation_paths",
    "release_file_reservations",
    "force_release_file_reservation",
    "renew_file_reservations",
    "summarize_thread",
    "summarize_threads",
    "macro_start_session",
    "macro_prepare_thread",
    "macro_file_reservation_cycle",
    "install_precommit_guard",
    "uninstall_precommit_guard",
    "slack_post_message",
    "slack_list_channels",
    "slack_get_channel_info",
    "acquire_build_slot",
    "renew_build_slot",
    "release_build_slot",
}

# Tool metadata for discovery
EXTENDED_TOOL_METADATA = {
    "acknowledge_message": {
        "category": "messaging",
        "description": "Acknowledge a message (sets both read_ts and ack_ts)",
    },
    "search_messages": {"category": "search", "description": "Full-text search over subject and body"},
    "create_agent_identity": {"category": "identity", "description": "Create a new unique agent identity"},
    "delete_agent": {
        "category": "identity",
        "description": "Permanently delete an agent and related records (destructive, irreversible)",
    },
    "file_reservation_paths": {
        "category": "file_reservations",
        "description": "Reserve file paths/globs for exclusive or shared access",
    },
    "create_file_reservation": {
        "category": "file_reservations",
        "description": "Create a single file reservation (path/glob)",
    },
    "release_file_reservations": {"category": "file_reservations", "description": "Release active file reservations"},
    "force_release_file_reservation": {
        "category": "file_reservations",
        "description": "Force-release stale reservation from another agent",
    },
    "renew_file_reservations": {
        "category": "file_reservations",
        "description": "Extend expiry for active reservations",
    },
    "acquire_build_slot": {
        "category": "coordination",
        "description": "Acquire exclusive build slot for parallel operations",
    },
    "renew_build_slot": {
        "category": "coordination",
        "description": "Extend build slot expiration",
    },
    "release_build_slot": {
        "category": "coordination",
        "description": "Release build slot",
    },
    "summarize_thread": {
        "category": "search",
        "description": "Extract participants, key points, and action items for a thread",
    },
    "summarize_threads": {"category": "search", "description": "Produce digest across multiple threads"},
    "macro_start_session": {
        "category": "workflow_macros",
        "description": "Boot project session with registration and inbox fetch",
    },
    "macro_prepare_thread": {"category": "workflow_macros", "description": "Align agent with existing thread context"},
    "macro_file_reservation_cycle": {
        "category": "workflow_macros",
        "description": "Reserve and optionally release file paths in one operation",
    },
    "install_precommit_guard": {
        "category": "infrastructure",
        "description": "Install pre-commit guard for a code repository",
    },
    "uninstall_precommit_guard": {
        "category": "infrastructure",
        "description": "Remove pre-commit guard from repository",
    },
    "slack_post_message": {"category": "messaging", "description": "Post a message to a Slack channel"},
    "slack_list_channels": {"category": "messaging", "description": "List available Slack channels"},
    "slack_get_channel_info": {
        "category": "messaging",
        "description": "Get detailed information about a Slack channel",
    },
}

# Registry for extended tool functions (for future dynamic invocation)
_EXTENDED_TOOL_REGISTRY: dict[str, Any] = {}


def build_mcp_server() -> FastMCP:
    """Create and configure the FastMCP server instance."""
    settings: Settings = get_settings()
    lifespan = _lifespan_factory(settings)

    instructions = (
        "You are the MCP Agent Mail coordination server. "
        "Provide message routing, coordination tooling, and project context to cooperating agents."
    )

    mcp = FastMCP(name="mcp-agent-mail", instructions=instructions, lifespan=lifespan)

    async def _deliver_message(
        ctx: Context,
        tool_name: str,
        project: Project,
        sender: Agent,
        to_names: Sequence[str],
        cc_names: Sequence[str],
        bcc_names: Sequence[str],
        subject: str,
        body_md: str,
        attachment_paths: Sequence[str] | None,
        convert_images_override: Optional[bool],
        importance: str,
        ack_required: bool,
        thread_id: Optional[str],
        *,
        allow_empty_recipients: bool = False,
    ) -> dict[str, Any]:
        # Re-fetch settings at call time so tests that mutate env + clear cache take effect
        settings = get_settings()
        call_start = time.perf_counter()
        if not to_names and not cc_names and not bcc_names and not allow_empty_recipients:
            raise ValueError("At least one recipient must be specified.")

        def _unique(items: Sequence[str]) -> list[str]:
            seen: set[str] = set()
            ordered: list[str] = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
            return ordered

        to_names = _unique(to_names)
        cc_names = _unique(cc_names)
        bcc_names = _unique(bcc_names)

        # Check if global inbox exists (will be added directly to cc_agents to avoid race condition)
        recipient_lookup_start = time.perf_counter()
        global_inbox_name = get_global_inbox_name(project)
        global_inbox_agent = await _get_agent_by_name_optional(global_inbox_name)
        # Only add to cc if sender is not the global inbox itself
        should_cc_global_inbox = (
            global_inbox_agent is not None and sender.name != global_inbox_name and global_inbox_name not in cc_names
        )

        if to_names or cc_names or bcc_names:
            to_agents = [await _get_agent_by_name(name) for name in to_names]
            cc_agents = [await _get_agent_by_name(name) for name in cc_names]
            bcc_agents = [await _get_agent_by_name(name) for name in bcc_names]
        else:
            to_agents = []
            cc_agents = []
            bcc_agents = []

        # Add global inbox to cc_agents directly (avoids race condition from re-fetching by name)
        if should_cc_global_inbox:
            cc_agents.append(global_inbox_agent)

        # Filter out global inbox from cc_agents for outbox visibility (keep in recipient_records)
        cc_agents_for_outbox = [agent for agent in cc_agents if agent.name != global_inbox_name]

        recipient_records: list[tuple[Agent, str]] = [(agent, "to") for agent in to_agents]
        recipient_records.extend((agent, "cc") for agent in cc_agents)
        recipient_records.extend((agent, "bcc") for agent in bcc_agents)
        recipient_lookup_elapsed = time.perf_counter() - recipient_lookup_start

        # Server-side file_reservations enforcement: block if conflicting active exclusive file_reservation exists
        if settings.file_reservations_enforcement_enabled:
            await _expire_stale_file_reservations(project.id or 0)
            now_ts = datetime.now(timezone.utc)
            y_dir = now_ts.strftime("%Y")
            m_dir = now_ts.strftime("%m")
            candidate_surfaces: list[str] = []
            candidate_surfaces.append(f"agents/{sender.name}/outbox/{y_dir}/{m_dir}/*.md")
            for r in to_agents + cc_agents + bcc_agents:
                candidate_surfaces.append(f"agents/{r.name}/inbox/{y_dir}/{m_dir}/*.md")

            async with get_session() as session:
                rows = await session.execute(
                    select(FileReservation, Agent.name)
                    .join(Agent, FileReservation.agent_id == Agent.id)
                    .where(
                        FileReservation.project_id == project.id,
                        cast(Any, FileReservation.released_ts).is_(None),
                        FileReservation.expires_ts > now_ts,
                    )
                )
                active_file_reservations = rows.all()

            conflicts: list[dict[str, Any]] = []
            for surface in candidate_surfaces:
                for file_reservation_record, holder_name in active_file_reservations:
                    if _file_reservations_conflict(file_reservation_record, surface, True, sender):
                        conflicts.append(
                            {
                                "surface": surface,
                                "holder": holder_name,
                                "path_pattern": file_reservation_record.path_pattern,
                                "exclusive": file_reservation_record.exclusive,
                                "expires_ts": _iso(file_reservation_record.expires_ts),
                            }
                        )
            if conflicts:
                # Return a structured error payload that clients can surface directly
                return {
                    "error": {
                        "type": "FILE_RESERVATION_CONFLICT",
                        "message": "Conflicting active file_reservations prevent message write.",
                        "conflicts": conflicts,
                    }
                }

        # Body processing - attachments tracked as metadata only (archive storage removed)
        processed_body = body_md
        attachments_meta: list[dict[str, object]] = []
        # Detect inline data URI images in body
        if "data:image" in body_md:
            attachments_meta.append({"type": "inline", "media_type": "image/webp"})
        if attachment_paths:
            for attachment_path in attachment_paths:
                try:
                    path_str = str(Path(attachment_path))
                except TypeError:
                    continue
                attachments_meta.append({"type": "file", "path": path_str})
            await ctx.warning(
                "Attachment paths are recorded as metadata only; files are no longer copied into storage."
            )
        if convert_images_override is not None:
            await ctx.warning("convert_images override is deprecated; images are no longer converted or copied.")

        db_write_start = time.perf_counter()
        message = await _create_message(
            project,
            sender,
            subject,
            processed_body,
            recipient_records,
            importance,
            ack_required,
            thread_id,
            attachments_meta,
        )
        db_write_elapsed = time.perf_counter() - db_write_start
        frontmatter = _message_frontmatter(
            message,
            project,
            sender,
            to_agents,
            cc_agents,
            bcc_agents,
            attachments_meta,
        )
        recipients_list = [agent.name for agent in to_agents + cc_agents + bcc_agents]
        payload: dict[str, Any] = _message_to_dict(message)
        payload.update(
            {
                "from": sender.name,
                "to": [agent.name for agent in to_agents],
                "cc": [agent.name for agent in cc_agents_for_outbox],
                "bcc": [agent.name for agent in bcc_agents],
                "attachments": attachments_meta,
            }
        )

        # Optional Slack mirror via incoming webhook (env-driven)
        try:
            from .slack_integration import mirror_message_to_slack

            mirror_message_to_slack(frontmatter, body_md)
        except Exception:
            logger.exception("Slack mirror failed (non-blocking)")

        total_elapsed = time.perf_counter() - call_start
        logger.info(
            "[LATENCY] _deliver_message: total=%.3fs recipients=%.3fs db_write=%.3fs msg_id=%s",
            total_elapsed,
            recipient_lookup_elapsed,
            db_write_elapsed,
            message.id,
        )
        await ctx.info(f"Message {message.id} created by {sender.name} (to {', '.join(recipients_list)})")

        # Send Slack notification if enabled (fire-and-forget, non-blocking)
        # Capture client reference before async boundary to avoid race condition during shutdown
        slack_client = _slack_client
        if settings.slack.enabled and settings.slack.notify_on_message:

            def _slack_done_cb(t: asyncio.Task) -> None:
                try:
                    _ = t.result()
                except Exception as e:
                    logger.exception("Failed to send Slack notification", exc_info=e)

            # Try Web API client first, fall back to webhook
            if slack_client:

                async def _send_slack_notification() -> None:
                    if slack_client is None or getattr(slack_client, "_http_client", None) is None:
                        logger.debug("Slack client unavailable, skipping notification")
                        return
                    await notify_slack_message(
                        client=slack_client,
                        settings=settings,
                        message_id=str(message.id),
                        subject=subject,
                        body_md=body_md,
                        sender_name=sender.name,
                        recipients=recipients_list,
                        importance=importance,
                        thread_id=thread_id,
                    )

                task = asyncio.create_task(_send_slack_notification())
                task.add_done_callback(_slack_done_cb)
            elif settings.slack.webhook_url:
                # Fallback to webhook URL if no client available
                from .slack_integration import format_mcp_message_for_slack, post_via_webhook

                async def _post_webhook():
                    text, blocks = format_mcp_message_for_slack(
                        subject=subject,
                        body_md=body_md,
                        sender_name=sender.name,
                        recipients=recipients_list,
                        message_id=str(message.id),
                        importance=importance,
                        use_blocks=settings.slack.use_blocks,
                    )
                    await post_via_webhook(settings.slack.webhook_url, text, blocks=blocks)

                task = asyncio.create_task(_post_webhook())
                task.add_done_callback(_slack_done_cb)

        return payload

    @mcp.tool(name="health_check", description="Return basic readiness information for the Agent Mail server.")
    @_instrument_tool("health_check", cluster=CLUSTER_SETUP, capabilities={"infrastructure"}, complexity="low")
    async def health_check(ctx: Context) -> dict[str, Any]:
        """
        Quick readiness probe for agents and orchestrators.

        When to use
        -----------
        - Before starting a workflow, to ensure the coordination server is reachable
          and configured (right environment, host/port, DB wiring).
        - During incident triage to print basic diagnostics to logs via `ctx.info`.

        What it checks vs what it does not
        ----------------------------------
        - Reports current environment and HTTP binding details.
        - Returns the configured database URL (not a live connection test).
        - Does not perform deep dependency health checks or connection attempts.

        Returns
        -------
        dict
            {
              "status": "ok" | "degraded" | "error",
              "environment": str,
              "http_host": str,
              "http_port": int,
              "database_url": str
            }

        Examples
        --------
        JSON-RPC (generic MCP client):
        ```json
        {"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"health_check","arguments":{}}}
        ```

        Typical agent usage (pseudocode):
        - Call `health_check`.
        - If status != ok, sleep/retry with backoff and log `environment`/`http_host`/`http_port`.
        """
        await ctx.info("Running health check.")
        return {
            "status": "ok",
            "environment": settings.environment,
            "http_host": settings.http.host,
            "http_port": settings.http.port,
            "database_url": settings.database.url,
        }

    @mcp.tool(name="list_extended_tools")
    @_instrument_tool("list_extended_tools", cluster=CLUSTER_SETUP, capabilities={"discovery"}, complexity="low")
    async def list_extended_tools(ctx: Context) -> dict[str, Any]:
        """
        List all extended tools with metadata.

        Returns
        -------
        dict
            {
              "total": int,
              "by_category": dict[str, list[str]],
              "tools": list[dict] with name, category, description
            }
        """
        await ctx.info("Listing extended tools")

        by_category: dict[str, list[str]] = {}
        tools_list = []

        for tool_name in sorted(EXTENDED_TOOLS):
            metadata = EXTENDED_TOOL_METADATA.get(tool_name, {})
            category = metadata.get("category", "uncategorized")
            description = metadata.get("description", "")

            by_category.setdefault(category, []).append(tool_name)
            tools_list.append({"name": tool_name, "category": category, "description": description})

        return {"total": len(EXTENDED_TOOLS), "by_category": by_category, "tools": tools_list}

    @mcp.tool(name="call_extended_tool")
    @_instrument_tool("call_extended_tool", cluster=CLUSTER_SETUP, capabilities={"proxy"}, complexity="medium")
    async def call_extended_tool(ctx: Context, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        Dynamically invoke an extended tool by name.

        Parameters
        ----------
        tool_name : str
            Name of extended tool (e.g., "file_reservation_paths")
        arguments : dict
            Tool-specific arguments

        Returns
        -------
        dict
            Result from invoked tool

        Raises
        ------
        ValueError
            If tool_name not in EXTENDED_TOOLS
        RuntimeError
            If tool not registered (internal error)
        """
        if tool_name not in EXTENDED_TOOLS:
            raise ValueError(f"Unknown extended tool: {tool_name}. Use list_extended_tools to see available options.")

        tool_func = _EXTENDED_TOOL_REGISTRY.get(tool_name)
        if not tool_func:
            raise RuntimeError(f"Extended tool {tool_name} is not registered. This is an internal server error.")

        await ctx.info(f"Invoking extended tool: {tool_name}")

        try:
            if hasattr(tool_func, "run"):
                result = await tool_func.run(arguments or {})
            else:
                result = await tool_func(ctx, **(arguments or {}))

            if isinstance(result, ToolResult):
                payload: Any = getattr(result, "structured_content", None)
                if payload is None and hasattr(result, "content"):
                    payload = result.content
                if payload is None and hasattr(result, "data"):
                    payload = result.data
                if payload is None:
                    try:
                        payload = next(iter(result)) if result else None
                    except (TypeError, IndexError, StopIteration):
                        payload = None
                result = payload

            # Avoid double-wrapping if the tool already returned a structured result
            if isinstance(result, dict) and set(result.keys()) == {"result"}:
                return result

            return {"result": result}
        except TypeError as e:
            # Invalid arguments
            raise ValueError(f"Invalid arguments for {tool_name}: {e!s}") from e

    @mcp.tool(name="ensure_project")
    @_instrument_tool(
        "ensure_project",
        cluster=CLUSTER_SETUP,
        capabilities={"infrastructure", "storage"},
        complexity="low",
        project_arg="human_key",
    )
    async def ensure_project(ctx: Context, human_key: str) -> dict[str, Any]:
        """
        Idempotently create or ensure a project exists for the given human key.

        When to use
        -----------
        - First call in a workflow targeting a new repo/path/project identifier.
        - As a guard before registering agents or sending messages.

        How it works
        ------------
        - Accepts any string as the project identifier (human_key).
        - Computes a stable slug from `human_key` (lowercased, safe characters) so
          multiple agents can refer to the same project consistently.
        - Ensures the DB row exists and, when archive storage is enabled, initializes
          the on-disk archive (e.g., `messages/`, `agents/`, `file_reservations/`
          directories).

        CRITICAL: Project Identity Rules
        ---------------------------------
        - The `human_key` can be any string identifier for your project
        - Common patterns: absolute paths, repo names, or custom project identifiers
        - Two agents using the SAME human_key are working on the SAME project
        - Example: Both agents using "smartedgar_mcp" → SAME project
        - Different identifiers create DIFFERENT projects (e.g., "smartedgar_mcp"
          vs "smartedgar_mcp_frontend")

        Parameters
        ----------
        human_key : str
            Any string identifier for the project. Common patterns:
            - Absolute path: "/data/projects/backend"
            - Repository name: "my-repo"
            - Custom identifier: "project-alpha"
            This is the canonical identifier for the project - all agents using this
            same key will share the same project identity.

        Returns
        -------
        dict
            Minimal project descriptor: { id, slug, human_key, created_at }.

        Examples
        --------
        JSON-RPC with absolute path:
        ```json
        {
          "jsonrpc": "2.0",
          "id": "2",
          "method": "tools/call",
          "params": {"name": "ensure_project", "arguments": {"human_key": "/data/projects/backend"}}
        }
        ```

        JSON-RPC with custom identifier:
        ```json
        {
          "jsonrpc": "2.0",
          "id": "2",
          "method": "tools/call",
          "params": {"name": "ensure_project", "arguments": {"human_key": "my-project-name"}}
        }
        ```

        Common mistakes
        ---------------
        - Using different identifiers for the same project (creates duplicate projects)
        - Not being consistent with the identifier format across agents

        Idempotency
        -----------
        - Safe to call multiple times. If the project already exists, the existing
          record is returned and the archive is ensured on disk when archive storage
          is enabled (no destructive changes).
        """
        await ctx.info(f"Ensuring project for key '{human_key}'.")
        project = await _ensure_project(human_key)
        return _project_to_dict(project)

    @mcp.tool(name="register_agent")
    @_instrument_tool(
        "register_agent",
        cluster=CLUSTER_IDENTITY,
        capabilities={"identity"},
        agent_arg="name",
        project_arg="project_key",
    )
    async def register_agent(
        ctx: Context,
        project_key: Optional[str] = None,
        program: Optional[str] = None,
        model: Optional[str] = None,
        name: Optional[str] = None,
        task_description: str = "",
        attachments_policy: str = "auto",
        force_reclaim: bool = False,
        auto_fetch_inbox: bool = False,
        inbox_limit: int = 10,
        inbox_urgent_only: bool = False,
        inbox_since_ts: Optional[str] = None,
        inbox_include_bodies: bool = False,
    ) -> dict[str, Any]:
        """
        Create or update an agent identity within a project and persist its profile to Git when enabled.

        IMPORTANT: Global Namespace
        ---------------------------
        Agent names are GLOBALLY UNIQUE across all projects. Use `whois` or `resource://agents`
        to verify agent existence - do NOT rely on project-scoped agent lists for discovery.

        Before choosing a name, check resource://agents to see all existing agents.

        When to use
        -----------
        - At the start of a coding session by any automated agent.
        - To update an existing agent's program/model/task metadata and bump last_active.

        Semantics
        ---------
        - If the project doesn't exist, it will be automatically created (you don't need to call `ensure_project` first).
        - If `name` is omitted, a random adjective+noun name is auto-generated (e.g., "BlueLake").
        - Reusing the same `name` updates the profile (program/model/task) and
          refreshes `last_active_ts`.
        - Registration succeeds even when archive storage is disabled; in that case
          Git profile writes are skipped.
        - When archive storage is enabled, a `profile.json` file is written under
          `agents/<Name>/` in the project archive.
        - Providing a name that is active in another project automatically retires that identity so you can claim the handle.

        CRITICAL: Agent Naming Rules
        -----------------------------
        - Agent names can be any alphanumeric string (letters and numbers only)
        - Examples: "BlueLake", "streamf", "agent1", "BackendWorker"
        - Names are globally unique across all projects (case-insensitive)
        - Non-alphanumeric characters are automatically stripped during sanitization
        - Names are limited to 128 characters
        - Best practice: Use memorable, short names that are easy to reference

        Parameters
        ----------
        project_key : Optional[str]
            Any string identifier for your project. Informational only for agent lookup; agents are
            global. The project will be automatically created if it doesn't exist. If omitted, the
            agent is associated with the default global project ("global").
        program : str
            The agent program (e.g., "codex-cli", "claude-code").
        model : str
            The underlying model (e.g., "gpt5-codex", "opus-4.1").
        name : Optional[str]
            Any alphanumeric string for the agent name (e.g., "BlueLake", "streamf", "agent1").
            If omitted, the server auto-generates a random codename (currently adjective+noun).
            Names are globally unique; passing the same name updates the profile.
        task_description : str
            Short description of current focus (shows up in directory listings).
        force_reclaim : bool
            If True, forcefully reclaim this agent name by retiring any active agents that currently
            use it, even in other projects. Use this when you want to override existing agents.
            Default is False. When False, the system will warn you if the name is already taken.

        Returns
        -------
        dict
            { id, name, program, model, task_description, inception_ts, last_active_ts, project_id }

        Examples
        --------
        Register with auto-generated name (RECOMMENDED):
        ```json
        {"jsonrpc":"2.0","id":"3","method":"tools/call","params":{"name":"register_agent","arguments":{
          "project_key":"/data/projects/backend","program":"codex-cli","model":"gpt5-codex","task_description":"Auth refactor"
        }}}
        ```

        Register with explicit valid name:
        ```json
        {"jsonrpc":"2.0","id":"4","method":"tools/call","params":{"name":"register_agent","arguments":{
          "project_key":"/data/projects/backend","program":"claude-code","model":"opus-4.1","name":"BlueLake","task_description":"Navbar redesign"
        }}}
        ```

        Pitfalls
        --------
        - Names must be alphanumeric (non-alphanumeric characters are stripped automatically)
        - Names are globally unique (case-insensitive). If you see "already in use", pick another or omit `name`.
        - Use the same `project_key` consistently across cooperating agents.
        """
        if program is None or model is None:
            await ctx.error("INVALID_ARGUMENT: program and model are required.")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "program and model are required.",
                recoverable=True,
                data={"argument": "program/model"},
            )
        assert program is not None
        assert model is not None
        # Auto-create project if it doesn't exist (allows any string as project_key)
        # If project_key is None, use the default global project
        if project_key is None:
            project = await _get_default_project()
        else:
            project = await _ensure_project(project_key)

        if settings.tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                c = Console()
                c.print(
                    Panel(
                        f"project=[bold]{project.human_key}[/]\nname=[bold]{name or '(generated)'}[/]\nprogram={program}\nmodel={model}",
                        title="tool: register_agent",
                        border_style="green",
                    )
                )
            except Exception:
                # Logging with rich is best-effort; skip errors to avoid impacting tool execution.
                pass
        # sanitize attachments policy
        ap = (attachments_policy or "auto").lower()
        if ap not in {"auto", "inline", "file"}:
            ap = "auto"
        agent = await _get_or_create_agent(
            project, name, program, model, task_description, settings, force_reclaim=force_reclaim
        )
        # Persist attachment policy if changed
        if getattr(agent, "attachments_policy", None) != ap:
            async with get_session() as session:
                db_agent = await session.get(Agent, agent.id)
                if db_agent:
                    db_agent.attachments_policy = ap
                    session.add(db_agent)
                    await session.commit()
                    await session.refresh(db_agent)
                    agent = db_agent
        await ctx.info(f"Registered agent '{agent.name}' for project '{project.human_key}'.")

        # Auto-fetch inbox if requested
        if auto_fetch_inbox:
            inbox_items = await _list_inbox(
                project,
                agent,
                inbox_limit,
                urgent_only=inbox_urgent_only,
                include_bodies=inbox_include_bodies,
                since_ts=inbox_since_ts,
            )
            return {
                "agent": _agent_to_dict(agent),
                "inbox": inbox_items,
            }

        return _agent_to_dict(agent)

    @mcp.tool(name="delete_agent")
    @_instrument_tool(
        "delete_agent", cluster=CLUSTER_IDENTITY, capabilities={"identity"}, agent_arg="name", project_arg="project_key"
    )
    async def delete_agent(
        ctx: Context,
        project_key: str,
        name: str,
    ) -> dict[str, Any]:
        """
        Delete an agent and all associated data from the system.

        When to use
        -----------
        - When an agent is no longer needed and should be permanently removed.
        - To clean up test agents or obsolete agent identities.

        Semantics
        ---------
        - Deletes the agent from the database
        - Deletes all messages sent by the agent
        - Deletes all message recipient records for the agent
        - Deletes all file reservations held by the agent
        - Writes a deletion marker to the Git archive at agents/<Name>/deleted.json

        WARNING
        -------
        This operation is DESTRUCTIVE and IRREVERSIBLE. All messages and reservations
        associated with this agent will be permanently deleted from the database.
        A deletion marker will be preserved in the Git archive for audit purposes.

        Parameters
        ----------
        project_key : str
            Informational only; the agent is identified globally by name. Used for logging/telemetry.
        name : str
            The exact name of the agent to delete (case-insensitive).

        Returns
        -------
        dict
            Deletion statistics including:
            - agent_id: The ID of the deleted agent
            - agent_name: The name of the deleted agent
            - project: The project human_key
            - message_recipients_deleted: Number of recipient records deleted
            - messages_deleted: Number of messages deleted
            - file_reservations_deleted: Number of file reservations deleted

        Examples
        --------
        Delete an agent:
        ```json
        {"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"delete_agent","arguments":{
          "project_key":"/data/projects/backend","name":"BlueLake"
        }}}
        ```

        Pitfalls
        --------
        - This operation cannot be undone. The agent and all associated data will be permanently deleted.
        - If the agent doesn't exist, a NoResultFound error will be raised.
        - If the agent has no associated project (e.g., project was deleted), deletion will fail
          with a clear error to avoid partial cleanup.
        - Other agents' messages TO this agent will have their recipient records deleted but the messages themselves remain.
        """
        # Look up agent globally first (agents are globally unique)
        agent = await _get_agent_by_name(name)

        # Get the agent's actual project (no fallback to avoid partial deletions)
        project = await _require_project_for_agent(agent, "delete agent")

        stats = await _delete_agent(agent, project)
        await ctx.info(f"Deleted agent '{name}' from project '{project.human_key}'.")
        return stats

    @mcp.tool(name="whois")
    @_instrument_tool(
        "whois",
        cluster=CLUSTER_IDENTITY,
        capabilities={"identity", "audit"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def whois(
        ctx: Context,
        project_key: str,
        agent_name: str,
        include_recent_commits: bool = True,
        commit_limit: int = 5,
    ) -> dict[str, Any]:
        """
        Return enriched profile details for an agent.

        IMPORTANT: Global Namespace
        ---------------------------
        Agent names are GLOBALLY UNIQUE across all projects. Use `whois` or `resource://agents`
        to verify agent existence - do NOT rely on project-scoped agent lists for discovery.

        This tool performs a global search by name (project_key is informational only).
        If no agent is found, it suggests similar agent names that may match your intent.
        If the agent has no associated project, the profile is still returned and the
        missing project association is logged as a warning.

        Discovery
        ---------
        Use resource://agents (global) to discover all registered agents.
        Agent names are NOT the same as program names or user names.

        Parameters
        ----------
        project_key : str
            Informational only; provided for logging/telemetry. Agent lookup is global.
        agent_name : str
            Agent name to look up (use resource://agents to discover names globally).
        include_recent_commits : bool
            Deprecated. Retained for compatibility; recent commits are no longer available.
        commit_limit : int
            Deprecated. Retained for compatibility; recent commits are no longer available.

        Returns
        -------
        dict
            Agent profile augmented with { recent_commits: [] }.

        Raises
        ------
        ToolExecutionError
            If the agent cannot be found. The error payload includes suggestions.
        """
        # Look up agent globally first (agents are globally unique)
        agent = await _get_agent_by_name_optional(agent_name)

        # If still not found, generate suggestions
        if not agent:
            suggestions = await _find_similar_agents(agent_name)
            suggestion_text = ""
            if suggestions:
                suggestion_text = f" Did you mean one of: {suggestions}?"
            error_msg = f"Agent '{agent_name}' not found.{suggestion_text}"
            await ctx.warning(error_msg)
            raise ToolExecutionError(
                "NOT_FOUND",
                f"Agent '{agent_name}' not registered globally.{suggestion_text}",
                data={
                    "agent_name": agent_name,
                    "suggestions": suggestions,
                    "tip": "Use resource://agents to see all registered agents globally.",
                },
            )

        profile = _agent_to_dict(agent)
        # NOTE: Archive storage has been removed. recent_commits is always empty.
        profile["recent_commits"] = []
        agent_project = await _get_project_for_agent(agent)
        if agent_project is None:
            await ctx.warning(
                ("Agent '%s' has no associated project; returning profile without project context.") % agent_name
            )
            project_label = "<no-project>"
        else:
            project_label = agent_project.human_key
        await ctx.info(f"whois for '{agent_name}' in '{project_label}'")
        return profile

    @mcp.tool(name="create_agent_identity")
    @_instrument_tool(
        "create_agent_identity",
        cluster=CLUSTER_IDENTITY,
        capabilities={"identity"},
        agent_arg="name_hint",
        project_arg="project_key",
    )
    async def create_agent_identity(
        ctx: Context,
        project_key: str,
        program: str,
        model: str,
        name_hint: Optional[str] = None,
        task_description: str = "",
        attachments_policy: str = "auto",
    ) -> dict[str, Any]:
        """
        Create a new, unique agent identity and persist its profile to Git.

        How this differs from `register_agent`
        --------------------------------------
        - Always creates a new identity with a fresh unique name (never updates an existing one).
        - `name_hint`, if provided, must be alphanumeric; if it matches an active agent, that identity is retired automatically before provisioning the new profile. Without a hint, the server auto-generates a random codename (currently adjective+noun).

        CRITICAL: Agent Naming Rules
        -----------------------------
        - Agent names can be any alphanumeric string (letters and numbers only)
        - Examples: "GreenCastle", "BlueLake", "streamf", "worker1", "BackendHarmonizer"
        - Names are globally unique across all projects
        - Non-alphanumeric characters are automatically stripped during sanitization
        - Names are limited to 128 characters
        - Best practice: Omit `name_hint` to auto-generate a valid name (RECOMMENDED)

        When to use
        -----------
        - Spawning a brand new worker agent that should not overwrite an existing profile.
        - Temporary task-specific identities (e.g., short-lived refactor assistants).

        Returns
        -------
        dict
            { id, name, program, model, task_description, inception_ts, last_active_ts, project_id }

        Examples
        --------
        Auto-generate name (RECOMMENDED):
        ```json
        {"jsonrpc":"2.0","id":"c2","method":"tools/call","params":{"name":"create_agent_identity","arguments":{
          "project_key":"/data/projects/backend","program":"claude-code","model":"opus-4.1"
        }}}
        ```

        With valid name hint:
        ```json
        {"jsonrpc":"2.0","id":"c1","method":"tools/call","params":{"name":"create_agent_identity","arguments":{
          "project_key":"/data/projects/backend","program":"codex-cli","model":"gpt5-codex","name_hint":"GreenCastle",
          "task_description":"DB migration spike"
        }}}
        ```
        """
        project = await _get_project_by_identifier(project_key)
        unique_name = await _generate_unique_agent_name(
            project,
            settings,
            name_hint,
            retire_conflicts=bool(name_hint),
            include_same_project_conflicts=bool(name_hint),
        )
        ap = (attachments_policy or "auto").lower()
        if ap not in {"auto", "inline", "file"}:
            ap = "auto"
        agent = await _create_agent_record(project, unique_name, program, model, task_description)
        # Update attachments policy immediately
        async with get_session() as session:
            db_agent = await session.get(Agent, agent.id)
            if db_agent:
                db_agent.attachments_policy = ap
                session.add(db_agent)
                await session.commit()
                await session.refresh(db_agent)
                agent = db_agent
        await ctx.info(f"Created new agent identity '{agent.name}' for project '{project.human_key}'.")
        return _agent_to_dict(agent)

    @mcp.tool(name="send_message")
    @_instrument_tool(
        "send_message",
        cluster=CLUSTER_MESSAGING,
        capabilities={"messaging", "write"},
        project_arg="project_key",
        agent_arg="sender_name",
    )
    async def send_message(
        ctx: Context,
        project_key: Optional[str] = None,
        sender_name: Optional[str] = None,
        to: Optional[list[str]] = None,
        subject: Optional[str] = None,
        body_md: Optional[str] = None,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        attachment_paths: Optional[list[str]] = None,
        convert_images: Optional[bool] = None,
        importance: str = "normal",
        ack_required: bool = False,
        thread_id: Optional[str] = None,
        auto_contact_if_blocked: bool = False,
    ) -> dict[str, Any]:
        """
        Send a Markdown message to one or more recipients and persist it to SQLite.

        IMPORTANT: Global Namespace
        ---------------------------
        Agent names are GLOBALLY UNIQUE across all projects. Use `whois` or `resource://agents`
        to verify agent existence - do NOT rely on project-scoped agent lists for discovery.

        Recipients can be any registered agent by name, regardless of project boundaries.
        The project_key parameter is informational only and does not restrict which agents
        can communicate.

        Project resolution
        ------------------
        Messages are recorded under the sender's associated project. If the sender no longer
        has an associated project (for example, the project was deleted), this call fails to
        avoid mis-routing messages into an unrelated project.

        Discovery
        ---------
        Use resource://agents (global) to discover all registered agents.
        Use whois(agent_name) to verify a specific agent exists.
        Agent names are NOT the same as program names or user names.

        What this does
        --------------
        - Stores message (and recipients) in the database; updates sender's activity
        - Records attachment metadata for inline data URIs and explicit attachment paths
        - Does not copy files or convert images (archive storage is removed)

        Parameters
        ----------
        project_key : Optional[str]
            Informational only; agent lookup is global. Routing uses the sender's actual project
            association and fails if none exists.
        sender_name : str
            Must match an existing agent name (agents are global).
        to : Optional[list[str]]
            Primary recipients (agent names). At least one of to/cc/bcc must be non-empty.
        subject : str
            Short subject line that will be visible in inbox/outbox and search results.
        body_md : str
            GitHub-Flavored Markdown body. Image references can be file paths or data URIs.
        cc, bcc : Optional[list[str]]
            Additional recipients by name. At least one of to/cc/bcc must be provided.
        attachment_paths : Optional[list[str]]
            Extra file paths to include as attachment metadata (files are not copied).
        convert_images : Optional[bool]
            Deprecated. Retained for compatibility; images are not converted or copied.
        importance : str
            One of {"low","normal","high","urgent"} (free form tolerated; used by filters).
        ack_required : bool
            If true, recipients should call `acknowledge_message` after reading.
        thread_id : Optional[str]
            If provided, message will be associated with an existing thread.

        Returns
        -------
        dict
            {
              "deliveries": [ { "project": str, "payload": { ... message payload ... } } ],
              "count": int
            }

        Edge cases
        ----------
        - If no recipients are given, the call fails.
        - Unknown recipient names fail fast; register them first.
        - Non-absolute attachment paths are preserved as provided; clients resolve them.

        Do / Don't
        ----------
        Do:
        - Keep subjects concise and specific (aim for ≤ 80 characters).
        - Use `thread_id` (or `reply_message`) to keep related discussion in a single thread.
        - Address only relevant recipients; use CC/BCC sparingly and intentionally.
        - Prefer Markdown links; attach images only when they materially aid understanding. The server
          records attachment metadata but does not copy or convert files.

        Don't:
        - Send large, repeated binaries—reuse prior attachments via `attachment_paths` when possible.
        - Change topics mid-thread—start a new thread for a new subject.
        - Broadcast to "all" agents unnecessarily—target just the agents who need to act.

        Examples
        --------
        1) Simple message:
        ```json
        {"jsonrpc":"2.0","id":"5","method":"tools/call","params":{"name":"send_message","arguments":{
          "project_key":"/abs/path/backend","sender_name":"GreenCastle","to":["BlueLake"],
          "subject":"Plan for /api/users","body_md":"See below."
        }}}
        ```

        2) Inline image (data URI auto-detected; file paths must be listed in attachment_paths):
        ```json
        {"jsonrpc":"2.0","id":"6a","method":"tools/call","params":{"name":"send_message","arguments":{
          "project_key":"/abs/path/backend","sender_name":"GreenCastle","to":["BlueLake"],
          "subject":"Diagram","body_md":"![diagram](docs/flow.png)","attachment_paths":["docs/flow.png"]
        }}}
        ```

        3) Explicit attachments:
        ```json
        {"jsonrpc":"2.0","id":"6b","method":"tools/call","params":{"name":"send_message","arguments":{
          "project_key":"/abs/path/backend","sender_name":"GreenCastle","to":["BlueLake"],
          "subject":"Screenshots","body_md":"Please review.","attachment_paths":["shots/a.png","shots/b.png"]
        }}}
        ```
        """
        if sender_name is None:
            await ctx.error("INVALID_ARGUMENT: sender_name is required.")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "sender_name is required.",
                recoverable=True,
                data={"argument": "sender_name"},
            )
        if subject is None or body_md is None:
            await ctx.error("INVALID_ARGUMENT: subject and body_md are required.")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "subject and body_md are required.",
                recoverable=True,
                data={"argument": "subject/body_md"},
            )
        assert sender_name is not None
        assert subject is not None
        assert body_md is not None
        # Messages are routed by agent name (globally unique), so project is informational only
        # Look up sender first, then use sender's project (ignore project_key)
        sender = await _get_agent_by_name(sender_name)

        # Use sender's associated project; fail fast if missing to avoid mis-routing
        project = await _require_project_for_agent(sender, "send message")

        to = to or []
        if not isinstance(to, list):
            await ctx.error("INVALID_ARGUMENT: to must be a list of strings.")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "to must be a list of strings.",
                recoverable=True,
                data={"argument": "to"},
            )
        if any(not isinstance(x, str) for x in to):
            await ctx.error("INVALID_ARGUMENT: to items must be strings (agent names).")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "to items must be strings (agent names).",
                recoverable=True,
                data={"argument": "to"},
            )
        # Normalize cc/bcc inputs and validate types for friendlier UX
        if isinstance(cc, str):
            cc = [cc]
        if isinstance(bcc, str):
            bcc = [bcc]
        if cc is not None and not isinstance(cc, list):
            await ctx.error("INVALID_ARGUMENT: cc must be a list of strings or a single string.")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "cc must be a list of strings or a single string.",
                recoverable=True,
                data={"argument": "cc"},
            )
        if bcc is not None and not isinstance(bcc, list):
            await ctx.error("INVALID_ARGUMENT: bcc must be a list of strings or a single string.")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "bcc must be a list of strings or a single string.",
                recoverable=True,
                data={"argument": "bcc"},
            )
        cc = cc or []
        if cc is not None and any(not isinstance(x, str) for x in cc):
            await ctx.error("INVALID_ARGUMENT: cc items must be strings (agent names).")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "cc items must be strings (agent names).",
                recoverable=True,
                data={"argument": "cc"},
            )
        bcc = bcc or []
        if bcc is not None and any(not isinstance(x, str) for x in bcc):
            await ctx.error("INVALID_ARGUMENT: bcc items must be strings (agent names).")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "bcc items must be strings (agent names).",
                recoverable=True,
                data={"argument": "bcc"},
            )
        # sender and project already looked up above
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                _rt = _imp.import_module("rich.text")
                Console = _rc.Console
                Panel = _rp.Panel
                Text = _rt.Text
                c = Console()
                title = f"tool: send_message — to={len(to)} cc={len(cc or [])} bcc={len(bcc or [])}"
                body = Text.assemble(
                    ("project: ", "cyan"),
                    (project.human_key, "white"),
                    "\n",
                    ("sender: ", "cyan"),
                    (sender_name, "white"),
                    "\n",
                    ("subject: ", "cyan"),
                    (subject[:120], "white"),
                )
                c.print(Panel(body, title=title, border_style="green"))
            except Exception:
                pass
        settings_local = get_settings()
        # Collect all recipients (project boundaries don't matter anymore)
        all_to: list[str] = []
        all_cc: list[str] = []
        all_bcc: list[str] = []

        async with get_session() as sx:
            # Preload ALL agent names globally (since names are unique)
            existing = await sx.execute(
                select(Agent.name).where(
                    cast(Any, Agent.is_active).is_(True),
                )
            )
            global_lookup: dict[str, str] = {}
            for row in existing.fetchall():
                canonical_name = (row[0] or "").strip()
                if not canonical_name:
                    continue
                sanitized_canonical = sanitize_agent_name(canonical_name) or canonical_name
                for key in {canonical_name.lower(), sanitized_canonical.lower()}:
                    global_lookup.setdefault(key, canonical_name)

            sender_candidate_keys = {
                key.lower()
                for key in (
                    (sender.name or "").strip(),
                    sanitize_agent_name(sender.name or "") or "",
                )
                if key
            }

            def _normalize(value: str) -> tuple[str, set[str], Optional[str]]:
                """Trim input, derive comparable lowercase keys, and canonical lookup token."""
                trimmed = (value or "").strip()
                sanitized = sanitize_agent_name(trimmed)
                keys: set[str] = set()
                if trimmed:
                    keys.add(trimmed.lower())
                if sanitized:
                    keys.add(sanitized.lower())
                canonical = sanitized or (trimmed if trimmed else None)
                return trimmed or value, keys, canonical

            unknown: dict[str, set[str]] = {}

            async def _route(name_list: list[str], kind: str) -> None:
                """Route recipients, supporting cross-project addressing."""

                async def _resolve_cross_project(project_identifier: str, target: str) -> str | None:
                    try:
                        proj = await _get_project_by_identifier(project_identifier)
                    except NoResultFound:
                        return None

                    # Try original and sanitized name variants
                    candidates = [target]
                    sanitized = sanitize_agent_name(target)
                    if sanitized and sanitized not in candidates:
                        candidates.append(sanitized)

                    for candidate in candidates:
                        try:
                            agent_obj = await _get_agent(proj, candidate)
                            return agent_obj.name
                        except NoResultFound:
                            continue
                    return None

                for raw in name_list:
                    display_value, key_candidates, canonical = _normalize(raw)
                    unknown_key = canonical or (
                        display_value.strip() if display_value else (raw.strip() if raw else raw)
                    )
                    if not key_candidates or not canonical:
                        if unknown_key is not None:
                            unknown.setdefault(unknown_key, set()).add(kind)
                        continue

                    target_project: str | None = None
                    target_name = canonical

                    # Format 1: "project:<identifier>#<agent-name>"
                    if display_value.startswith("project:") and "#" in display_value:
                        parts = display_value.split("#", 1)
                        if len(parts) == 2:
                            target_project = parts[0].replace("project:", "", 1).strip()
                            target_name = (parts[1] or target_name).strip() or target_name
                            key_candidates = {target_name.lower()}
                            sanitized = sanitize_agent_name(target_name)
                            if sanitized:
                                key_candidates.add(sanitized.lower())

                    # Format 2: "<agent-name>@<project-identifier>"
                    elif "@" in display_value and not display_value.startswith("@"):
                        parts = display_value.rsplit("@", 1)
                        if len(parts) == 2:
                            target_name = (parts[0] or target_name).strip() or target_name
                            target_project = (parts[1] or "").strip() or None
                            key_candidates = {target_name.lower()}
                            sanitized = sanitize_agent_name(target_name)
                            if sanitized:
                                key_candidates.add(sanitized.lower())

                    # Allow self-send unless explicitly targeting another project
                    if not target_project and sender_candidate_keys.intersection(key_candidates):
                        if kind == "to":
                            all_to.append(sender.name)
                        elif kind == "cc":
                            all_cc.append(sender.name)
                        else:
                            all_bcc.append(sender.name)
                        continue

                    resolved = None

                    if target_project:
                        resolved = await _resolve_cross_project(target_project, target_name)
                    else:
                        for key in key_candidates:
                            resolved = global_lookup.get(key)
                            if resolved:
                                break

                    if resolved:
                        if kind == "to":
                            all_to.append(resolved)
                        elif kind == "cc":
                            all_cc.append(resolved)
                        else:
                            all_bcc.append(resolved)
                    else:
                        if unknown_key is not None:
                            unknown.setdefault(unknown_key, set()).add(kind)

            await _route(to, "to")
            await _route(cc, "cc")
            await _route(bcc, "bcc")

            if unknown:
                # Auto-register missing recipients if enabled
                if getattr(settings_local, "messaging_auto_register_recipients", True):
                    # Best effort: create placeholder agents for unknown recipients.
                    # Placeholder agents can receive messages and be "claimed" later
                    # when the real agent registers with that name.
                    newly_registered: list[tuple[str, set[str]]] = []
                    for missing in list(unknown.keys()):
                        # Skip cross-project address syntaxes; only auto-register simple names
                        if missing.startswith("project:") or "@" in missing:
                            continue
                        try:
                            placeholder = await _create_placeholder_agent(
                                project,
                                missing,
                                sender.program,
                                sender.model,
                                settings_local,
                            )
                            newly_registered.append((missing, unknown.get(missing, set())))
                            unknown.pop(missing, None)
                            # Add the newly created placeholder to global_lookup so _route can find it
                            canonical_name = placeholder.name
                            sanitized_canonical = sanitize_agent_name(canonical_name) or canonical_name
                            for key in {canonical_name.lower(), sanitized_canonical.lower()}:
                                global_lookup.setdefault(key, canonical_name)
                        except Exception:
                            pass
                    # Re-run routing for any that were registered
                    if newly_registered:
                        for name, kinds in newly_registered:
                            route_kinds = kinds or {"to"}
                            if "to" in route_kinds:
                                await _route([name], "to")
                            if "cc" in route_kinds:
                                await _route([name], "cc")
                            if "bcc" in route_kinds:
                                await _route([name], "bcc")

                # If still have unknown recipients, raise error
                if unknown:
                    missing_names = sorted({name for name in unknown if name})
                    message = f"Recipients not found: {', '.join(missing_names)}"
                    await ctx.error(f"RECIPIENT_NOT_FOUND: {message}")
                    suggestions: list[dict[str, Any]] = []
                    for name in missing_names[:5]:
                        suggestions.append(
                            {
                                "tool": "register_agent",
                                "arguments": {
                                    "project_key": project.human_key,
                                    "name": name,
                                    "program": sender.program,
                                    "model": sender.model,
                                    "task_description": sender.task_description,
                                },
                            }
                        )
                    raise ToolExecutionError(
                        "RECIPIENT_NOT_FOUND",
                        message,
                        recoverable=True,
                        data={"unknown_recipients": missing_names, "suggested_tool_calls": suggestions},
                    )

        if not (all_to or all_cc or all_bcc):
            await ctx.error("INVALID_ARGUMENT: At least one recipient must be specified (to/cc/bcc).")
            raise ToolExecutionError(
                "INVALID_ARGUMENT",
                "At least one recipient must be specified (to/cc/bcc).",
                recoverable=True,
                data={"argument": "recipients"},
            )

        # Deliver message to all recipients (no project boundaries)
        payload = await _deliver_message(
            ctx,
            "send_message",
            project,
            sender,
            all_to,
            all_cc,
            all_bcc,
            subject,
            body_md,
            attachment_paths,
            convert_images,
            importance,
            ack_required,
            thread_id,
            allow_empty_recipients=False,
        )

        # If delivery returned a structured error payload, bubble it up
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            return {"error": payload["error"]}

        # Maintain backward-compatible return format
        result: dict[str, Any] = {
            "deliveries": [{"project": project.human_key, "payload": payload}],
            "count": 1,
        }
        # Expose attachments at top level if present
        if isinstance(payload, dict) and "attachments" in payload:
            result["attachments"] = payload.get("attachments")
        return result

    @mcp.tool(name="reply_message")
    @_instrument_tool(
        "reply_message",
        cluster=CLUSTER_MESSAGING,
        capabilities={"messaging", "write"},
        project_arg="project_key",
        agent_arg="sender_name",
    )
    async def reply_message(
        ctx: Context,
        project_key: str,
        message_id: int,
        sender_name: str,
        body_md: str,
        to: Optional[list[str]] = None,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        subject_prefix: str = "Re:",
    ) -> dict[str, Any]:
        """
        Reply to an existing message, preserving or establishing a thread.

        Behavior
        --------
        - Inherits original `importance` and `ack_required` flags
        - `thread_id` is taken from the original message if present; otherwise, the original id is used
        - Subject is prefixed with `subject_prefix` if not already present
        - Defaults `to` to the original sender if not explicitly provided
        - Agent lookup is global by name; project_key is informational only and used for logging
        - Replies are recorded under the sender's associated project; if the sender has no project,
          the call fails to prevent routing the reply into an unrelated project

        Parameters
        ----------
        project_key : str
            Informational only; agent lookup is global and routing uses the sender's project association.
        message_id : int
            The id of the message you are replying to.
        sender_name : str
            Your agent name (looked up globally by name).
        body_md : str
            Reply body in Markdown.
        to, cc, bcc : Optional[list[str]]
            Recipients by agent name. If omitted, `to` defaults to original sender.
        subject_prefix : str
            Prefix to apply (default "Re:"). Case-insensitive idempotent.

        Do / Don't
        ----------
        Do:
        - Keep the subject focused; avoid topic drift within a thread.
        - Reply to the original sender unless new stakeholders are strictly required.
        - Preserve importance/ack flags from the original unless there is a clear reason to change.
        - Use CC for FYI only; BCC sparingly and with intention.

        Don't:
        - Change `thread_id` when continuing the same discussion.
        - Escalate to many recipients; prefer targeted replies and start a new thread for new topics.
        - Attach large binaries in replies unless essential; reference prior attachments where possible.

        Returns
        -------
        dict
            Message payload including `thread_id` and `reply_to`.

        Examples
        --------
        Minimal reply to original sender:
        ```json
        {"jsonrpc":"2.0","id":"6","method":"tools/call","params":{"name":"reply_message","arguments":{
          "project_key":"/abs/path/backend","message_id":1234,"sender_name":"BlueLake",
          "body_md":"Questions about the migration plan..."
        }}}
        ```

        Reply with explicit recipients and CC:
        ```json
        {"jsonrpc":"2.0","id":"6c","method":"tools/call","params":{"name":"reply_message","arguments":{
          "project_key":"/abs/path/backend","message_id":1234,"sender_name":"BlueLake",
          "body_md":"Looping ops.","to":["GreenCastle"],"cc":["RedCat"],"subject_prefix":"RE:"
        }}}
        ```
        """
        # Look up sender globally first (agents are globally unique)
        sender = await _get_agent_by_name(sender_name)

        # Get project from sender's association (no fallback to avoid cross-project replies)
        project = await _require_project_for_agent(sender, "send reply")

        original = await _get_message_by_id_global(message_id)
        original_sender = await _get_agent_by_id_global(original.sender_id)
        thread_key = original.thread_id or str(original.id)
        subject_prefix_clean = subject_prefix.strip()
        base_subject = original.subject
        if subject_prefix_clean and base_subject.lower().startswith(subject_prefix_clean.lower()):
            reply_subject = base_subject
        else:
            reply_subject = f"{subject_prefix_clean} {base_subject}".strip()
        to_names = to or [original_sender.name]
        cc_list = cc or []
        bcc_list = bcc or []

        # Simplified routing: all agents are global
        all_to: list[str] = []
        all_cc: list[str] = []
        all_bcc: list[str] = []

        async with get_session() as sx:
            # Preload ALL agent names globally
            existing = await sx.execute(
                select(Agent.name).where(
                    cast(Any, Agent.is_active).is_(True),
                )
            )
            global_lookup: dict[str, str] = {}
            for row in existing.fetchall():
                canonical_name = (row[0] or "").strip()
                if canonical_name:
                    global_lookup[canonical_name.lower()] = canonical_name

            unknown: set[str] = set()

            async def _route(name_list: list[str], kind: str) -> None:
                """Routing with cross-project addressing support.

                Supported formats:
                - Bare name: "AgentName"
                - project:id#name: "project:/path/to/proj#AgentName"
                - name@project: "AgentName@/path/to/proj"
                """
                for raw in name_list:
                    name = (raw or "").strip()
                    if not name:
                        continue

                    # Parse cross-project addressing formats
                    target_name = name
                    target_project = None

                    # Format 1: "project:<identifier>#<agent-name>"
                    if name.startswith("project:") and "#" in name:
                        parts = name.split("#", 1)
                        if len(parts) == 2:
                            project_part = parts[0].replace("project:", "", 1)
                            target_name = parts[1].strip()
                            target_project = project_part.strip()

                    # Format 2: "<agent-name>@<project-identifier>"
                    elif "@" in name and not name.startswith("@"):
                        parts = name.rsplit("@", 1)  # rsplit to handle names with @ in them
                        if len(parts) == 2:
                            target_name = parts[0].strip()
                            target_project = parts[1].strip()

                    # Look up agent (cross-project if target_project specified, otherwise global)
                    if target_project:
                        # Cross-project lookup: resolve project and agent explicitly
                        try:
                            proj = await _get_project_by_identifier(target_project)
                            agent = await _get_agent(proj, target_name)
                            resolved = agent.name  # Agent names are globally unique
                        except NoResultFound:
                            resolved = None
                    else:
                        # Global lookup by name (returns canonical name)
                        resolved = global_lookup.get(target_name.lower())

                    if resolved:
                        if kind == "to":
                            all_to.append(resolved)
                        elif kind == "cc":
                            all_cc.append(resolved)
                        else:
                            all_bcc.append(resolved)
                    else:
                        unknown.add(name)

            await _route(to_names, "to")
            await _route(cc_list, "cc")
            await _route(bcc_list, "bcc")

            # Validate all recipients were resolved
            if unknown:
                missing_names = sorted({name for name in unknown if name})
                message = f"Recipients not found: {', '.join(missing_names)}"
                raise ToolExecutionError(
                    "RECIPIENT_UNKNOWN",
                    message,
                    recoverable=True,
                    data={"unknown_recipients": missing_names},
                )

        # Deliver reply to all recipients (no project boundaries)
        payload = await _deliver_message(
            ctx,
            "reply_message",
            project,
            sender,
            all_to,
            all_cc,
            all_bcc,
            reply_subject,
            body_md,
            None,
            None,
            importance=original.importance,
            ack_required=original.ack_required,
            thread_id=thread_key,
        )

        # Maintain backward-compatible return format
        deliveries = [{"project": project.human_key, "payload": payload}]
        result = dict(payload) if isinstance(payload, dict) else {}
        result["thread_id"] = thread_key
        result["reply_to"] = message_id
        result["deliveries"] = deliveries
        result["count"] = 1
        if isinstance(payload, dict) and "attachments" in payload:
            result.setdefault("attachments", payload.get("attachments"))
        return result

    @mcp.tool(name="fetch_inbox")
    @_instrument_tool(
        "fetch_inbox",
        cluster=CLUSTER_MESSAGING,
        capabilities={"messaging", "read"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def fetch_inbox(
        ctx: Context,
        project_key: str,
        agent_name: str,
        limit: int = 20,
        urgent_only: bool = False,
        include_bodies: bool = False,
        since_ts: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve recent messages for an agent without mutating read/ack state.

        NOTE: Agent names are globally unique. The project_key parameter is informational only
        and does not affect message retrieval. Agents can see all messages sent to them
        regardless of which project_key is used in the fetch call.

        Project resolution
        ------------------
        Messages are fetched from the inbox associated with the agent's project. If the agent no
        longer has a project (for example, the project was deleted), the call fails to avoid
        returning messages from an unrelated project.

        Filters
        -------
        - `urgent_only`: only messages with importance in {high, urgent}
        - `since_ts`: ISO-8601 timestamp string; messages strictly newer than this are returned
        - `limit`: max number of messages (default 20)
        - `include_bodies`: include full Markdown bodies in the payloads

        Usage patterns
        --------------
        - Poll after each editing step in an agent loop to pick up coordination messages.
        - Use `since_ts` with the timestamp from your last poll for efficient incremental fetches.
        - Combine with `acknowledge_message` if `ack_required` is true.

        Returns
        -------
        list[dict]
            Each message includes: { id, subject, from, created_ts, importance, ack_required, kind, [body_md] }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"7","method":"tools/call","params":{"name":"fetch_inbox","arguments":{
          "project_key":"/abs/path/backend","agent_name":"BlueLake","since_ts":"2025-10-23T00:00:00+00:00"
        }}}
        ```
        """
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(
                        f"project={project_key}\nagent={agent_name}\nlimit={limit}\nurgent_only={urgent_only}",
                        title="tool: fetch_inbox",
                        border_style="green",
                    )
                )
            except Exception:
                pass
        try:
            # project_key is now informational only - agents are looked up globally
            agent = await _get_agent_by_name(agent_name)

            # Get project from agent's association (no fallback to avoid reading wrong inbox)
            project = await _require_project_for_agent(agent, "fetch inbox")

            items = await _list_inbox(project, agent, limit, urgent_only, include_bodies, since_ts)
            await ctx.info(f"Fetched {len(items)} messages for '{agent.name}'. urgent_only={urgent_only}")
            return items
        except Exception as exc:
            _rich_error_panel("fetch_inbox", {"error": str(exc)})
            raise

    @mcp.tool(name="mark_message_read")
    @_instrument_tool(
        "mark_message_read",
        cluster=CLUSTER_MESSAGING,
        capabilities={"messaging", "read"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def mark_message_read(
        ctx: Context,
        agent_name: str,
        message_id: int,
        project_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Mark a specific message as read for the given agent.

        Parameters
        ----------
        agent_name : str
            Name of the agent marking the message as read.
        message_id : int
            ID of the message to mark as read.
        project_key : Optional[str]
            Project identifier (optional, informational only - agents and messages are globally accessible).

        Notes
        -----
        - Read receipts are per-recipient; this only affects the specified agent.
        - Agent must be a recipient of the message (raises error if not).
        - This does not send an acknowledgement; use `acknowledge_message` for that.
        - Safe to call multiple times; later calls return the original timestamp.

        Idempotency
        -----------
        - If `mark_message_read` has already been called earlier for the same (agent, message),
          the original timestamp is returned and no error is raised.

        Returns
        -------
        dict
            { message_id, read: bool, read_at: iso8601 | null }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"8","method":"tools/call","params":{"name":"mark_message_read","arguments":{
          "project_key":"/abs/path/backend","agent_name":"BlueLake","message_id":1234
        }}}
        ```
        """
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(
                        f"project={project_key}\nagent={agent_name}\nmessage_id={message_id}",
                        title="tool: mark_message_read",
                        border_style="green",
                    )
                )
            except Exception:
                pass
        try:
            agent = await _get_agent_by_name(agent_name)
            await _get_message_by_id_global(message_id)
            await _validate_agent_is_recipient(agent, message_id)
            read_ts = await _update_recipient_timestamp(agent, message_id, "read_ts")
            await ctx.info(f"Marked message {message_id} read for '{agent.name}'.")
            return {"message_id": message_id, "read": bool(read_ts), "read_at": _iso(read_ts) if read_ts else None}
        except Exception as exc:
            if get_settings().tools_log_enabled:
                try:
                    from rich.console import Console  # type: ignore
                    from rich.json import JSON  # type: ignore

                    Console().print(JSON.from_data({"error": str(exc)}))
                except Exception:
                    pass
            raise

    @mcp.tool(name="acknowledge_message")
    @_instrument_tool(
        "acknowledge_message",
        cluster=CLUSTER_MESSAGING,
        capabilities={"messaging", "ack"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def acknowledge_message(
        ctx: Context,
        agent_name: str,
        message_id: int,
        project_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Acknowledge a message addressed to an agent (and mark as read).

        Parameters
        ----------
        agent_name : str
            Name of the agent acknowledging the message.
        message_id : int
            ID of the message to acknowledge.
        project_key : Optional[str]
            Project identifier (optional, informational only - agents and messages are globally accessible).

        Behavior
        --------
        - Sets both read_ts and ack_ts for the (agent, message) pairing
        - Agent must be a recipient of the message (raises error if not)
        - Safe to call multiple times; subsequent calls will return the prior timestamps

        Idempotency
        -----------
        - If acknowledgement already exists, the previous timestamps are preserved and returned.

        When to use
        -----------
        - Respond to messages with `ack_required=true` to signal explicit receipt.
        - Agents can treat an acknowledgement as a lightweight, non-textual reply.

        Returns
        -------
        dict
            { message_id, acknowledged: bool, acknowledged_at: iso8601 | null, read_at: iso8601 | null }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"9","method":"tools/call","params":{"name":"acknowledge_message","arguments":{
          "project_key":"/abs/path/backend","agent_name":"BlueLake","message_id":1234
        }}}
        ```
        """
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(
                        f"project={project_key}\nagent={agent_name}\nmessage_id={message_id}",
                        title="tool: acknowledge_message",
                        border_style="green",
                    )
                )
            except Exception:
                pass
        try:
            settings = get_settings()
            agent = await _get_agent_by_name(agent_name)
            message = await _get_message_by_id_global(message_id)
            await _validate_agent_is_recipient(agent, message_id)
            read_ts = await _update_recipient_timestamp(agent, message_id, "read_ts")
            prev_ack_ts = await _get_recipient_timestamp(agent, message_id, "ack_ts")
            ack_ts = await _update_recipient_timestamp(agent, message_id, "ack_ts")
            await ctx.info(f"Acknowledged message {message_id} for '{agent.name}'.")
            result = {
                "message_id": message_id,
                "acknowledged": bool(ack_ts),
                "acknowledged_at": _iso(ack_ts) if ack_ts else None,
                "read_at": _iso(read_ts) if read_ts else None,
            }
            # Fire-and-forget Slack notification for acknowledgements
            slack_client = _slack_client
            if settings.slack.enabled and settings.slack.notify_on_ack and prev_ack_ts is None and ack_ts:

                def _ack_done_cb(task: asyncio.Task) -> None:
                    try:
                        task.result()
                    except Exception as exc:
                        logger.exception("Failed to send Slack ack notification", exc_info=exc)

                if slack_client:

                    async def _send_ack_notification() -> None:
                        if slack_client is None or getattr(slack_client, "_http_client", None) is None:
                            logger.debug("Slack client unavailable, skipping ack notification")
                            return
                        await notify_slack_ack(
                            client=slack_client,
                            settings=settings,
                            message_id=str(message.id),
                            agent_name=agent.name,
                            subject=message.subject,
                            thread_id=message.thread_id,
                        )

                    task = asyncio.create_task(_send_ack_notification())
                    task.add_done_callback(_ack_done_cb)
                elif settings.slack.webhook_url:
                    from .slack_integration import post_via_webhook

                    async def _post_ack_webhook() -> None:
                        text = f":white_check_mark: {agent.name} acknowledged: {message.subject}"
                        await post_via_webhook(settings.slack.webhook_url, text)

                    task = asyncio.create_task(_post_ack_webhook())
                    task.add_done_callback(_ack_done_cb)

            return result
        except Exception as exc:
            if get_settings().tools_log_enabled:
                try:
                    import importlib as _imp

                    _rc = _imp.import_module("rich.console")
                    _rj = _imp.import_module("rich.json")
                    Console = _rc.Console
                    JSON = _rj.JSON
                    Console().print(JSON.from_data({"error": str(exc)}))
                except Exception:
                    pass
            raise

    @mcp.tool(name="search_mailbox")
    @_instrument_tool(
        "search_mailbox",
        cluster=CLUSTER_SEARCH,
        capabilities={"search", "read"},
        project_arg="project_key",
        agent_arg="requesting_agent",
    )
    async def search_mailbox(
        ctx: Context,
        project_key: str,
        query: str,
        requesting_agent: Optional[str] = None,
        agent_filter: Optional[str] = None,
        limit: int = 20,
        include_bodies: bool = True,
    ) -> ToolResult:
        """
        Search through mailboxes for messages matching a query.

        This tool helps agents learn from prior conversations and coordinate by searching
        historical messages. **Always search before tackling challenging tasks** to see
        what prior learnings exist.

        Search Priority
        ---------------
        1. Global mailbox (all messages in the project) - searched first
        2. Specific agent mailbox (if agent_filter is specified)

        Parameters
        ----------
        project_key : str
            Project identifier to search within.
        query : str
            Search terms. Supports FTS5 syntax:
            - Simple: "feature implementation"
            - Phrase: '"exact phrase"'
            - Boolean: "bug AND fix", "error OR warning", "test NOT failed"
            - Prefix: "auth*" matches "authentication", "authorization", etc.
        requesting_agent : str, optional
            Name of the agent performing the search (for audit purposes).
        agent_filter : str, optional
            Restrict search to messages sent to/from this specific agent.
        limit : int
            Maximum number of results to return (default 20).
        include_bodies : bool
            Include full message bodies in results (default True).

        Returns
        -------
        list[dict]
            Matching messages ranked by relevance. Each includes:
            { id, subject, from, to, created_ts, relevance_score, snippet, [body_md] }

        Usage Examples
        --------------
        # Search for prior authentication work
        search_mailbox(project_key="my-app", query="authentication implementation")

        # Find error discussions
        search_mailbox(project_key="my-app", query="error OR exception OR bug")

        # Check specific agent's conversations
        search_mailbox(project_key="my-app", query="database", agent_filter="AliceAgent")

        Best Practices
        --------------
        - Search the global mailbox before starting complex tasks
        - Use specific keywords from your current task
        - Review search results to avoid duplicating work
        - Learn from past solutions and mistakes
        """
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(
                        f"project={project_key}\nquery={query}\nagent_filter={agent_filter}\nlimit={limit}",
                        title="tool: search_mailbox",
                        border_style="green",
                    )
                )
            except Exception:
                # Logging with rich is best-effort; skip failures to avoid interfering with tool behavior.
                pass

        try:
            project = await _get_project_by_identifier(project_key)
            global_inbox_name = get_global_inbox_name(project)

            # Prepare FTS5 query (escape double quotes, wrap in quotes for phrase search if needed)
            fts_query = query.strip()

            await ensure_schema()
            async with get_session() as session:
                # Search using FTS5 virtual table scoped to this project.
                # bm25 returns lower values for more relevant rows; convert to a 0-1 score for readability.
                fts_stmt = text("""
                    SELECT
                        m.id AS message_id,
                        1.0 / (1.0 + bm25(fts_messages)) AS relevance_score,
                        snippet(fts_messages, 1, '<mark>', '</mark>', '...', 32) AS subject_snippet,
                        snippet(fts_messages, 2, '<mark>', '</mark>', '...', 64) AS body_snippet
                    FROM fts_messages
                    JOIN messages AS m ON fts_messages.rowid = m.id
                    WHERE m.project_id = :project_id
                      AND fts_messages MATCH :query
                    ORDER BY bm25(fts_messages) ASC
                    LIMIT :limit
                """)

                fts_limit = limit * 2 if agent_filter else limit
                try:
                    fts_result = await session.execute(
                        fts_stmt,
                        {"project_id": project.id, "query": fts_query, "limit": fts_limit},
                    )
                except SQLAlchemyError as exc:
                    await ctx.error("Invalid search query. Please check your search syntax and try again.")
                    logger.warning("FTS5 query error for %r: %s", query, exc)
                    return ToolResult(structured_content={"result": []})

                fts_rows = fts_result.fetchall()

                if not fts_rows:
                    await ctx.info(f"No messages found matching query: {query}")
                    return ToolResult(structured_content={"result": []})

                message_ids = list(dict.fromkeys(row[0] for row in fts_rows))
                relevance_map = {row[0]: (row[1], row[2], row[3]) for row in fts_rows}

                # Now fetch full message details with recipient info
                # Join with agents to get sender/recipient names
                sender_alias = aliased(Agent)
                recipient_alias = aliased(Agent)

                # Fetch agent filter object if specified (for later filtering)
                # Use global agent lookup since agent names are globally unique
                agent_filter_obj = None
                if agent_filter:
                    try:
                        agent_filter_obj = await _get_agent_by_name(agent_filter)
                    except NoResultFound as exc:  # pragma: no cover - validated via tests
                        raise ToolExecutionError(
                            "agent_filter_not_found",
                            (
                                f"Agent filter '{agent_filter}' was not found. "
                                "Verify the agent name via resource://agents."
                            ),
                        ) from exc

                messages_stmt = (
                    select(
                        Message,
                        sender_alias.name.label("sender_name"),
                        MessageRecipient.kind,
                        recipient_alias.name.label("recipient_name"),
                        recipient_alias.id.label("recipient_id"),
                    )
                    .join(sender_alias, Message.sender_id == sender_alias.id)
                    .join(MessageRecipient, MessageRecipient.message_id == Message.id)
                    .join(recipient_alias, MessageRecipient.agent_id == recipient_alias.id)
                    # Always fetch the full recipient lists even when agent_filter is provided so we can
                    # apply filtering after assembling the complete message payload.
                    .where(
                        cast(Any, Message.id).in_(message_ids),
                        Message.project_id == project.id,
                    )
                )

                messages_result = await session.execute(messages_stmt)
                message_rows = messages_result.all()

                # Group recipients by message
                messages_dict: dict[int, dict[str, Any]] = {}
                for msg, sender_name, kind, recipient_name, _recipient_id in message_rows:
                    msg_id = msg.id
                    if msg_id not in messages_dict:
                        relevance_score, subject_snippet, body_snippet = relevance_map[msg_id]

                        payload = _message_to_dict(msg, include_body=include_bodies)
                        payload["from"] = sender_name
                        payload["to"] = []
                        payload["cc"] = []
                        payload["bcc"] = []
                        payload["relevance_score"] = float(relevance_score)
                        payload["subject_snippet"] = subject_snippet
                        payload["body_snippet"] = body_snippet
                        payload["in_global_inbox"] = False  # Will be set to True if global inbox is found
                        messages_dict[msg_id] = payload

                    # Add recipient to appropriate list and check for global inbox
                    if recipient_name == global_inbox_name:
                        messages_dict[msg_id]["in_global_inbox"] = True

                    if kind == "to":
                        messages_dict[msg_id]["to"].append(recipient_name)
                    elif kind == "cc":
                        messages_dict[msg_id]["cc"].append(recipient_name)
                    elif kind == "bcc":
                        messages_dict[msg_id]["bcc"].append(recipient_name)

                # Convert to list and apply agent filter if specified
                results = list(messages_dict.values())

                # Filter messages to only include those involving the agent_filter agent
                if agent_filter_obj:
                    filtered_results = []
                    for msg in results:
                        # Check if agent is involved (sender or in any recipient list)
                        is_sender = msg["from"] == agent_filter_obj.name
                        is_recipient = (
                            agent_filter_obj.name in msg["to"]
                            or agent_filter_obj.name in msg.get("cc", [])
                            or agent_filter_obj.name in msg.get("bcc", [])
                        )
                        if is_sender or is_recipient:
                            filtered_results.append(msg)
                    results = filtered_results

                # Sort by relevance, prioritizing global inbox messages
                results.sort(
                    key=lambda x: (
                        0 if x["in_global_inbox"] else 1,  # Global inbox first
                        -x["relevance_score"],  # Then by relevance (higher first)
                    )
                )
                results = results[:limit]

                await ctx.info(
                    f"Found {len(results)} messages matching query '{query}' "
                    f"({sum(1 for r in results if r['in_global_inbox'])} in global inbox)"
                )

                return ToolResult(structured_content={"result": results})

        except Exception as exc:
            _rich_error_panel("search_mailbox", {"error": str(exc)})
            raise

    @mcp.tool(name="macro_start_session")
    @_instrument_tool(
        "macro_start_session",
        cluster=CLUSTER_MACROS,
        capabilities={"workflow", "messaging", "file_reservations", "identity"},
        project_arg="human_key",
        agent_arg="agent_name",
    )
    async def macro_start_session(
        ctx: Context,
        human_key: str,
        program: str,
        model: str,
        task_description: str = "",
        agent_name: Optional[str] = None,
        file_reservation_paths: Optional[list[str]] = None,
        file_reservation_reason: str = "macro-session",
        file_reservation_ttl_seconds: int = 3600,
        inbox_limit: int = 10,
    ) -> dict[str, Any]:
        """
        Macro helper that boots a project session: ensure project, register agent,
        optionally file_reservation paths, and fetch the latest inbox snapshot.
        """
        settings = get_settings()
        project = await _ensure_project(human_key)
        agent = await _get_or_create_agent(project, agent_name, program, model, task_description, settings)

        file_reservations_result: Optional[dict[str, Any]] = None
        if file_reservation_paths:
            # Use MCP tool registry to avoid param shadowing (file_reservation_paths param shadows file_reservation_paths function)
            from fastmcp.tools.tool import FunctionTool

            _file_reservation_tool = cast(FunctionTool, await mcp.get_tool("file_reservation_paths"))
            _file_reservation_run = await _file_reservation_tool.run(
                {
                    "project_key": project.human_key,
                    "agent_name": agent.name,
                    "paths": file_reservation_paths,
                    "ttl_seconds": file_reservation_ttl_seconds,
                    "exclusive": True,
                    "reason": file_reservation_reason,
                }
            )
            file_reservations_result = cast(dict[str, Any], _file_reservation_run.structured_content or {})

        inbox_items = await _list_inbox(
            project,
            agent,
            inbox_limit,
            urgent_only=False,
            include_bodies=False,
            since_ts=None,
        )
        await ctx.info(
            f"macro_start_session prepared agent '{agent.name}' on project '{project.human_key}' "
            f"(file_reservations={len(file_reservations_result['granted']) if file_reservations_result else 0})."
        )
        return {
            "project": _project_to_dict(project),
            "agent": _agent_to_dict(agent),
            "file_reservations": file_reservations_result or {"granted": [], "conflicts": []},
            "inbox": inbox_items,
        }

    @mcp.tool(name="macro_prepare_thread")
    @_instrument_tool(
        "macro_prepare_thread",
        cluster=CLUSTER_MACROS,
        capabilities={"workflow", "messaging", "summarization"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def macro_prepare_thread(
        ctx: Context,
        project_key: str,
        thread_id: str,
        program: str,
        model: str,
        agent_name: Optional[str] = None,
        task_description: str = "",
        register_if_missing: bool = True,
        include_examples: bool = True,
        inbox_limit: int = 10,
        include_inbox_bodies: bool = False,
        llm_mode: bool = True,
        llm_model: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Macro helper that aligns an agent with an existing thread by ensuring registration,
        summarising the thread, and fetching recent inbox context.
        """
        settings = get_settings()
        project = await _get_project_by_identifier(project_key)
        if register_if_missing:
            agent = await _get_or_create_agent(project, agent_name, program, model, task_description, settings)
        else:
            if not agent_name:
                raise ValueError("agent_name is required when register_if_missing is False.")
            agent = await _get_agent(project, agent_name)

        inbox_items = await _list_inbox(
            project,
            agent,
            inbox_limit,
            urgent_only=False,
            include_bodies=include_inbox_bodies,
            since_ts=None,
        )
        summary, examples, total_messages = await _compute_thread_summary(
            project,
            thread_id,
            include_examples,
            llm_mode,
            llm_model,
        )
        await ctx.info(
            f"macro_prepare_thread prepared agent '{agent.name}' for thread '{thread_id}' "
            f"on project '{project.human_key}' (messages={total_messages})."
        )
        return {
            "project": _project_to_dict(project),
            "agent": _agent_to_dict(agent),
            "thread": {
                "thread_id": thread_id,
                "summary": summary,
                "examples": examples,
                "total_messages": total_messages,
            },
            "inbox": inbox_items,
        }

    @mcp.tool(name="macro_file_reservation_cycle")
    @_instrument_tool(
        "macro_file_reservation_cycle",
        cluster=CLUSTER_MACROS,
        capabilities={"workflow", "file_reservations", "repository"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def macro_file_reservation_cycle(
        ctx: Context,
        project_key: str,
        agent_name: str,
        paths: list[str],
        ttl_seconds: int = 3600,
        exclusive: bool = True,
        reason: str = "macro-file_reservation",
        auto_release: bool = False,
    ) -> dict[str, Any]:
        """Reserve a set of file paths and optionally release them at the end of the workflow."""

        # Call underlying FunctionTool directly so we don't treat the wrapper as a plain coroutine
        from fastmcp.tools.tool import FunctionTool

        file_reservations_tool = cast(FunctionTool, cast(Any, file_reservation_paths))
        file_reservations_tool_result = await file_reservations_tool.run(
            {
                "project_key": project_key,
                "agent_name": agent_name,
                "paths": paths,
                "ttl_seconds": ttl_seconds,
                "exclusive": exclusive,
                "reason": reason,
            }
        )
        file_reservations_result = cast(dict[str, Any], file_reservations_tool_result.structured_content or {})

        release_result = None
        if auto_release:
            release_tool = cast(FunctionTool, cast(Any, release_file_reservations_tool))
            release_tool_result = await release_tool.run(
                {
                    "project_key": project_key,
                    "agent_name": agent_name,
                    "paths": paths,
                }
            )
            release_result = cast(dict[str, Any], release_tool_result.structured_content or {})

        await ctx.info(
            f"macro_file_reservation_cycle issued {len(file_reservations_result['granted'])} file_reservation(s) for '{agent_name}' on '{project_key}'"
            + (" and released them immediately." if auto_release else ".")
        )
        return {
            "file_reservations": file_reservations_result,
            "released": release_result,
        }

    @mcp.tool(name="search_messages")
    @_instrument_tool("search_messages", cluster=CLUSTER_SEARCH, capabilities={"search"}, project_arg="project_key")
    async def search_messages(
        ctx: Context,
        project_key: str,
        query: str,
        limit: int = 20,
    ) -> Any:
        """
        Full-text search over subject and body for a project.

        Tips
        ----
        - SQLite FTS5 syntax supported: phrases ("build plan"), prefix (mig*), boolean (plan AND users)
        - Results are ordered by bm25 score (best matches first)
        - Limit defaults to 20; raise for broad queries

        Query examples
        ---------------
        - Phrase search: `"build plan"`
        - Prefix: `migrat*`
        - Boolean: `plan AND users`
        - Require urgent: `urgent AND deployment`

        Parameters
        ----------
        project_key : str
            Project identifier.
        query : str
            FTS5 query string.
        limit : int
            Max results to return.

        Returns
        -------
        list[dict]
            Each entry: { id, subject, importance, ack_required, created_ts, thread_id, from }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"10","method":"tools/call","params":{"name":"search_messages","arguments":{
          "project_key":"/abs/path/backend","query":"\"build plan\" AND users", "limit": 50
        }}}
        ```
        """
        project = await _get_project_by_identifier(project_key)
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                _rt = _imp.import_module("rich.text")
                Console = _rc.Console
                Panel = _rp.Panel
                Text = _rt.Text
                cons = Console()
                body = Text.assemble(
                    ("project: ", "cyan"),
                    (project.human_key, "white"),
                    "\n",
                    ("query: ", "cyan"),
                    (query[:200], "white"),
                    "\n",
                    ("limit: ", "cyan"),
                    (str(limit), "white"),
                )
                cons.print(Panel(body, title="tool: search_messages", border_style="green"))
            except Exception:
                pass
        if project.id is None:
            raise ValueError("Project must have an id before searching messages.")
        await ensure_schema()
        async with get_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT m.id, m.subject, m.body_md, m.importance, m.ack_required, m.created_ts,
                           m.thread_id, a.name AS sender_name
                    FROM fts_messages
                    JOIN messages m ON fts_messages.rowid = m.id
                    JOIN agents a ON m.sender_id = a.id
                    WHERE m.project_id = :project_id AND fts_messages MATCH :query
                    ORDER BY bm25(fts_messages) ASC
                    LIMIT :limit
                    """
                ),
                {"project_id": project.id, "query": query, "limit": limit},
            )
            rows = result.mappings().all()
        await ctx.info(f"Search '{query}' returned {len(rows)} messages for project '{project.human_key}'.")
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel(f"results={len(rows)}", title="tool: search_messages — done", border_style="green")
                )
            except Exception:
                pass
        items = [
            {
                "id": row["id"],
                "subject": row["subject"],
                "body_md": row["body_md"],
                "importance": row["importance"],
                "ack_required": row["ack_required"],
                "created_ts": _iso(row["created_ts"]),
                "thread_id": row["thread_id"],
                "from": row["sender_name"],
            }
            for row in rows
        ]
        return ToolResult(structured_content={"result": items})

    @mcp.tool(name="acquire_build_slot")
    @_instrument_tool(
        "acquire_build_slot", cluster=CLUSTER_SETUP, capabilities={"coordination"}, project_arg="project_key"
    )
    async def acquire_build_slot(
        ctx: Context,
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
        result = await acquire_slot_impl(project_key, agent_name, slot, ttl_seconds, exclusive)
        await ctx.info(f"Build slot '{slot}' acquisition for agent '{agent_name}': {result.get('granted', False)}")
        return result

    @mcp.tool(name="renew_build_slot")
    @_instrument_tool(
        "renew_build_slot", cluster=CLUSTER_SETUP, capabilities={"coordination"}, project_arg="project_key"
    )
    async def renew_build_slot(
        ctx: Context,
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
                "disabled": bool (if WORKTREES_ENABLED=0)
            }
        """
        result = await renew_slot_impl(project_key, agent_name, slot, extend_seconds)
        await ctx.info(f"Build slot '{slot}' renewal for agent '{agent_name}': {result.get('renewed', False)}")
        return result

    @mcp.tool(name="release_build_slot")
    @_instrument_tool(
        "release_build_slot", cluster=CLUSTER_SETUP, capabilities={"coordination"}, project_arg="project_key"
    )
    async def release_build_slot(
        ctx: Context,
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
                "disabled": bool (if WORKTREES_ENABLED=0)
            }
        """
        result = await release_slot_impl(project_key, agent_name, slot)
        await ctx.info(f"Build slot '{slot}' released for agent '{agent_name}': {result.get('released', False)}")
        return result

    @mcp.tool(name="summarize_thread")
    @_instrument_tool(
        "summarize_thread", cluster=CLUSTER_SEARCH, capabilities={"summarization", "search"}, project_arg="project_key"
    )
    async def summarize_thread(
        ctx: Context,
        project_key: str,
        thread_id: str,
        include_examples: bool = False,
        llm_mode: bool = True,
        llm_model: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Extract participants, key points, and action items for a thread.

        Notes
        -----
        - If `thread_id` is not an id present on any message, it is treated as a string key
        - If `thread_id` is a message id, messages where `id == thread_id` are also included
        - `include_examples` returns up to 3 sample messages for quick preview

        Suggested use
        -------------
        - Call after a long discussion to inform a summarizing or planning agent.
        - Use `key_points` to seed a TODO list and `action_items` to assign work.

        Returns
        -------
        dict
            { thread_id, summary: {participants[], key_points[], action_items[], total_messages}, examples[] }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"11","method":"tools/call","params":{"name":"summarize_thread","arguments":{
          "project_key":"/abs/path/backend","thread_id":"TKT-123","include_examples":true
        }}}
        ```
        """
        project = await _get_project_by_identifier(project_key)
        summary, examples, total_messages = await _compute_thread_summary(
            project,
            thread_id,
            include_examples,
            llm_mode,
            llm_model,
        )
        await ctx.info(
            f"Summarized thread '{thread_id}' for project '{project.human_key}' with {total_messages} messages"
        )
        return {"thread_id": thread_id, "summary": summary, "examples": examples}

    @mcp.tool(name="summarize_threads")
    @_instrument_tool(
        "summarize_threads", cluster=CLUSTER_SEARCH, capabilities={"summarization", "search"}, project_arg="project_key"
    )
    async def summarize_threads(
        ctx: Context,
        project_key: str,
        thread_ids: list[str],
        llm_mode: bool = True,
        llm_model: Optional[str] = None,
        per_thread_limit: int = 50,
    ) -> dict[str, Any]:
        """
        Produce a digest across multiple threads including top mentions and action items.

        Parameters
        ----------
        project_key : str
            Project identifier.
        thread_ids : list[str]
            Collection of thread keys or seed message ids.
        llm_mode : bool
            If true and LLM is enabled, refine the digest with the LLM for clarity.
        llm_model : Optional[str]
            Override model name for the LLM call.
        per_thread_limit : int
            Max messages to consider per thread.

        Returns
        -------
        dict
            {
              threads: [{thread_id, summary}],
              aggregate: { top_mentions[], action_items[], key_points[] }
            }
        """
        project = await _get_project_by_identifier(project_key)
        if project.id is None:
            raise ValueError("Project must have an id before summarizing threads.")
        await ensure_schema()

        sender_alias = aliased(Agent)
        all_mentions: dict[str, int] = {}
        all_actions: list[str] = []
        all_points: list[str] = []
        thread_summaries: list[dict[str, Any]] = []

        async with get_session() as session:
            for tid in thread_ids:
                try:
                    seed_id = int(tid)
                except ValueError:
                    seed_id = None
                criteria = [Message.thread_id == tid]
                if seed_id is not None:
                    criteria.append(Message.id == seed_id)
                stmt = (
                    select(Message, sender_alias.name)
                    .join(sender_alias, Message.sender_id == sender_alias.id)
                    .where(Message.project_id == project.id, or_(*criteria))
                    .order_by(asc(Message.created_ts))
                    .limit(per_thread_limit)
                )
                rows = (await session.execute(stmt)).all()
                summary = _summarize_messages(rows)
                # accumulate
                for m in summary.get("mentions", []):
                    name = str(m.get("name", "")).strip()
                    if not name:
                        continue
                    all_mentions[name] = all_mentions.get(name, 0) + int(m.get("count", 0) or 0)
                all_actions.extend(summary.get("action_items", []))
                all_points.extend(summary.get("key_points", []))
                thread_summaries.append({"thread_id": tid, "summary": summary})

        # Lightweight heuristic digest
        top_mentions = sorted(all_mentions.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        aggregate = {
            "top_mentions": [{"name": n, "count": c} for n, c in top_mentions],
            "action_items": all_actions[:25],
            "key_points": all_points[:25],
        }

        # Optional LLM refinement
        if llm_mode and get_settings().llm.enabled and thread_summaries:
            try:
                # Compose compact context combining per-thread key points & actions only
                parts: list[str] = []
                for item in thread_summaries[:8]:
                    s = item["summary"]
                    parts.append(
                        "\n".join(
                            [
                                f"# Thread {item['thread_id']}",
                                "## Key Points",
                                *[f"- {p}" for p in s.get("key_points", [])[:6]],
                                "## Actions",
                                *[f"- {a}" for a in s.get("action_items", [])[:6]],
                            ]
                        )
                    )
                system = (
                    "You are a senior engineer producing a crisp digest across threads. "
                    "Return JSON: { threads: [{thread_id, key_points[], actions[]}], aggregate: {top_mentions[], key_points[], action_items[]} }."
                )
                user = "\n\n".join(parts)
                llm_resp = await complete_system_user(system, user, model=llm_model)
                parsed = _parse_json_safely(llm_resp.content)
                if parsed:
                    agg = parsed.get("aggregate") or {}
                    if agg:
                        for k in ("top_mentions", "key_points", "action_items"):
                            v = agg.get(k)
                            if v:
                                aggregate[k] = v
                    # Replace per-thread summaries' key aggregates if returned
                    revised_threads = []
                    threads_payload = parsed.get("threads") or []
                    if threads_payload:
                        mapping = {str(t.get("thread_id")): t for t in threads_payload}
                        for item in thread_summaries:
                            tid = str(item["thread_id"])
                            if tid in mapping:
                                s = item["summary"].copy()
                                tdata = mapping[tid]
                                if tdata.get("key_points"):
                                    s["key_points"] = tdata["key_points"]
                                if tdata.get("actions"):
                                    s["action_items"] = tdata["actions"]
                                revised_threads.append({"thread_id": item["thread_id"], "summary": s})
                            else:
                                revised_threads.append(item)
                        thread_summaries = revised_threads
            except Exception as e:
                await ctx.debug(f"summarize_threads.llm_skipped: {e}")

        await ctx.info(f"Summarized {len(thread_ids)} thread(s) for project '{project.human_key}'.")
        return {"threads": thread_summaries, "aggregate": aggregate}

    @mcp.tool(name="install_precommit_guard")
    @_instrument_tool(
        "install_precommit_guard",
        cluster=CLUSTER_SETUP,
        capabilities={"infrastructure", "repository"},
        project_arg="project_key",
    )
    async def install_precommit_guard(
        ctx: Context,
        project_key: str,
        code_repo_path: str,
    ) -> dict[str, Any]:
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(
                        f"project={project_key}\nrepo={code_repo_path}",
                        title="tool: install_precommit_guard",
                        border_style="green",
                    )
                )
            except Exception:
                pass
        project = await _get_project_by_identifier(project_key)
        repo_path = Path(code_repo_path).expanduser().resolve()
        hook_path = await install_guard_script(settings, project.slug, repo_path)
        await ctx.info(f"Installed pre-commit guard for project '{project.human_key}' at {hook_path}.")
        return {"hook": str(hook_path)}

    @mcp.tool(name="uninstall_precommit_guard")
    @_instrument_tool("uninstall_precommit_guard", cluster=CLUSTER_SETUP, capabilities={"infrastructure", "repository"})
    async def uninstall_precommit_guard(
        ctx: Context,
        code_repo_path: str,
    ) -> dict[str, Any]:
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(f"repo={code_repo_path}", title="tool: uninstall_precommit_guard", border_style="green")
                )
            except Exception:
                pass
        repo_path = Path(code_repo_path).expanduser().resolve()
        removed = await uninstall_guard_script(repo_path)
        if removed:
            await ctx.info(f"Removed pre-commit guard at {repo_path / '.git/hooks/pre-commit'}.")
        else:
            await ctx.info(f"No pre-commit guard to remove at {repo_path / '.git/hooks/pre-commit'}.")
        return {"removed": removed}

    @mcp.tool(name="create_file_reservation")
    @_instrument_tool(
        "create_file_reservation",
        cluster=CLUSTER_FILE_RESERVATIONS,
        capabilities={"file_reservations", "repository"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def create_file_reservation(
        ctx: Context,
        project_key: str,
        agent_name: str,
        path_pattern: str,
        ttl_seconds: int = 3600,
        exclusive: bool = True,
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Create a single advisory file reservation (lease) for a project-relative path/glob.

        This is the single-path convenience tool; for multiple paths use `file_reservation_paths`.
        """
        project = await _ensure_project(project_key)
        settings = get_settings()
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(
                        f"path_pattern={path_pattern}",
                        title=f"tool: create_file_reservation — agent={agent_name} ttl={ttl_seconds}s",
                        border_style="green",
                    )
                )
            except Exception:
                pass

        agent = await _get_agent_optional(project, agent_name)
        if not agent:
            agent = await _get_or_create_agent(
                project,
                agent_name,
                program="mcp-agent-mail",
                model="auto",
                task_description="Auto-created for file reservations",
                settings=settings,
            )
        if project.id is None:
            raise ValueError("Project must have an id before creating file reservations.")
        stale_auto_releases = await _expire_stale_file_reservations(project.id)
        if stale_auto_releases:
            summary = ", ".join(
                f"{status.agent.name}:{status.reservation.path_pattern}" for status in stale_auto_releases[:5]
            )
            extra = f" ({summary})" if summary else ""
            await ctx.info(f"Auto-released {len(stale_auto_releases)} stale file_reservation(s){extra}.")
        project_id = project.id
        async with get_session() as session:
            existing_rows = await session.execute(
                select(FileReservation, Agent.name)
                .join(Agent, FileReservation.agent_id == Agent.id)
                .where(
                    FileReservation.project_id == project_id,
                    cast(Any, FileReservation.released_ts).is_(None),
                    FileReservation.expires_ts > datetime.now(timezone.utc),
                )
            )
            existing_reservations = existing_rows.all()

        conflicting_holders: list[dict[str, Any]] = []
        for file_reservation_record, holder_name in existing_reservations:
            if _file_reservations_conflict(file_reservation_record, path_pattern, exclusive, agent):
                conflicting_holders.append(
                    {
                        "agent": holder_name,
                        "path_pattern": file_reservation_record.path_pattern,
                        "exclusive": file_reservation_record.exclusive,
                        "expires_ts": _iso(file_reservation_record.expires_ts),
                    }
                )

        file_reservation = await _create_file_reservation(project, agent, path_pattern, exclusive, reason, ttl_seconds)
        file_reservation_payload = {
            "id": file_reservation.id,
            "project": project.human_key,
            "agent": agent.name,
            "path_pattern": file_reservation.path_pattern,
            "exclusive": file_reservation.exclusive,
            "reason": file_reservation.reason,
            "created_ts": _iso(file_reservation.created_ts),
            "expires_ts": _iso(file_reservation.expires_ts),
            "released_ts": None,
        }
        await write_file_reservation_artifacts(
            settings, project.slug, [cast(dict[str, object], file_reservation_payload)], project_key=project.human_key
        )

        granted = [
            {
                "id": file_reservation.id,
                "path_pattern": file_reservation.path_pattern,
                "exclusive": file_reservation.exclusive,
                "reason": file_reservation.reason,
                "expires_ts": _iso(file_reservation.expires_ts),
            }
        ]
        conflicts: list[dict[str, Any]] = []
        if conflicting_holders:
            conflicts.append({"path": path_pattern, "holders": conflicting_holders})
        await ctx.info(f"Issued 1 file_reservation for '{agent.name}'. Conflicts: {len(conflicts)}")
        return {"granted": granted, "conflicts": conflicts}

    @mcp.tool(name="file_reservation_paths")
    @_instrument_tool(
        "file_reservation_paths",
        cluster=CLUSTER_FILE_RESERVATIONS,
        capabilities={"file_reservations", "repository"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def file_reservation_paths(
        ctx: Context,
        project_key: str,
        agent_name: str,
        paths: list[str],
        ttl_seconds: int = 3600,
        exclusive: bool = True,
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Request advisory file reservations (leases) on project-relative paths/globs.

        Semantics
        ---------
        - Conflicts are reported if an overlapping active exclusive reservation exists held by another agent
        - Glob matching is symmetric (`fnmatchcase(a,b)` or `fnmatchcase(b,a)`), including exact matches
        - The database is the source of truth; archive artifacts are disabled when archive storage is removed
        - TTL must be >= 60 seconds (enforced by the server settings/policy)

        Do / Don't
        ----------
        Do:
        - Reserve files before starting edits to signal intent to other agents.
        - Use specific, minimal patterns (e.g., `app/api/*.py`) instead of broad globs.
        - Set a realistic TTL and renew with `renew_file_reservations` if you need more time.

        Don't:
        - Reserve the entire repository or very broad patterns (e.g., `**/*`) unless absolutely necessary.
        - Hold long-lived exclusive reservations when you are not actively editing.
        - Ignore conflicts; resolve them by coordinating with holders or waiting for expiry.

        Parameters
        ----------
        project_key : str
        agent_name : str
        paths : list[str]
            File paths or glob patterns relative to the project workspace (e.g., "app/api/*.py").
        ttl_seconds : int
            Time to live for the file_reservation; expired file_reservations are auto-released.
        exclusive : bool
            If true, exclusive intent; otherwise shared/observe-only.
        reason : str
            Optional explanation (helps humans reviewing Git artifacts).

        Returns
        -------
        dict
            { granted: [{id, path_pattern, exclusive, reason, expires_ts}], conflicts: [{path, holders: [...]}] }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"12","method":"tools/call","params":{"name":"file_reservation_paths","arguments":{
          "project_key":"/abs/path/backend","agent_name":"GreenCastle","paths":["app/api/*.py"],
          "ttl_seconds":7200,"exclusive":true,"reason":"migrations"
        }}}
        ```
        """
        project = await _ensure_project(project_key)
        settings = get_settings()
        if settings.tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                c = Console()
                c.print(
                    Panel(
                        "\n".join(paths),
                        title=f"tool: file_reservation_paths — agent={agent_name} ttl={ttl_seconds}s",
                        border_style="green",
                    )
                )
            except Exception:
                pass
        agent = await _get_agent_optional(project, agent_name)
        if not agent:
            agent = await _get_or_create_agent(
                project,
                agent_name,
                program="mcp-agent-mail",
                model="auto",
                task_description="Auto-created for file reservations",
                settings=settings,
            )
        if project.id is None:
            raise ValueError("Project must have an id before reserving file paths.")
        stale_auto_releases = await _expire_stale_file_reservations(project.id)
        if stale_auto_releases:
            summary = ", ".join(
                f"{status.agent.name}:{status.reservation.path_pattern}" for status in stale_auto_releases[:5]
            )
            extra = f" ({summary})" if summary else ""
            await ctx.info(f"Auto-released {len(stale_auto_releases)} stale file_reservation(s){extra}.")
        project_id = project.id
        async with get_session() as session:
            existing_rows = await session.execute(
                select(FileReservation, Agent.name)
                .join(Agent, FileReservation.agent_id == Agent.id)
                .where(
                    FileReservation.project_id == project_id,
                    cast(Any, FileReservation.released_ts).is_(None),
                    FileReservation.expires_ts > datetime.now(timezone.utc),
                )
            )
            existing_reservations = existing_rows.all()

        granted: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for path in paths:
            conflicting_holders: list[dict[str, Any]] = []
            for file_reservation_record, holder_name in existing_reservations:
                if _file_reservations_conflict(file_reservation_record, path, exclusive, agent):
                    conflicting_holders.append(
                        {
                            "agent": holder_name,
                            "path_pattern": file_reservation_record.path_pattern,
                            "exclusive": file_reservation_record.exclusive,
                            "expires_ts": _iso(file_reservation_record.expires_ts),
                        }
                    )
            if conflicting_holders:
                # Advisory model: still grant the file_reservation but surface conflicts
                conflicts.append({"path": path, "holders": conflicting_holders})
            file_reservation = await _create_file_reservation(project, agent, path, exclusive, reason, ttl_seconds)
            granted.append(
                {
                    "id": file_reservation.id,
                    "path_pattern": file_reservation.path_pattern,
                    "exclusive": file_reservation.exclusive,
                    "reason": file_reservation.reason,
                    "expires_ts": _iso(file_reservation.expires_ts),
                }
            )
            existing_reservations.append((file_reservation, agent.name))
        await ctx.info(f"Issued {len(granted)} file_reservations for '{agent.name}'. Conflicts: {len(conflicts)}")
        return {"granted": granted, "conflicts": conflicts}

    @mcp.tool(name="release_file_reservations")
    @_instrument_tool(
        "release_file_reservations",
        cluster=CLUSTER_FILE_RESERVATIONS,
        capabilities={"file_reservations"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def release_file_reservations_tool(
        ctx: Context,
        project_key: str,
        agent_name: str,
        paths: Optional[list[str]] = None,
        file_reservation_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        """
        Release active file reservations held by an agent.

        Behavior
        --------
        - If both `paths` and `file_reservation_ids` are omitted, all active reservations for the agent are released
        - Otherwise, restricts release to matching ids and/or path patterns
        - JSON artifacts stay in Git for audit; DB records get `released_ts`

        Returns
        -------
        dict
            { released: int, released_at: iso8601 }

        Idempotency
        -----------
        - Safe to call repeatedly. Releasing an already-released (or non-existent) reservation is a no-op.

        Examples
        --------
        Release all active reservations for agent:
        ```json
        {"jsonrpc":"2.0","id":"13","method":"tools/call","params":{"name":"release_file_reservations","arguments":{
          "project_key":"/abs/path/backend","agent_name":"GreenCastle"
        }}}
        ```

        Release by ids:
        ```json
        {"jsonrpc":"2.0","id":"14","method":"tools/call","params":{"name":"release_file_reservations","arguments":{
          "project_key":"/abs/path/backend","agent_name":"GreenCastle","file_reservation_ids":[101,102]
        }}}
        ```
        """
        if get_settings().tools_log_enabled:
            try:
                from rich.console import Console  # type: ignore
                from rich.panel import Panel  # type: ignore

                details = [
                    f"project={project_key}",
                    f"agent={agent_name}",
                    f"paths={len(paths or [])}",
                    f"ids={len(file_reservation_ids or [])}",
                ]
                Console().print(
                    Panel.fit("\n".join(details), title="tool: release_file_reservations", border_style="green")
                )
            except Exception:
                pass
        try:
            project = await _get_project_by_identifier(project_key)
            agent = await _get_agent(project, agent_name)
            if project.id is None or agent.id is None:
                raise ValueError("Project and agent must have ids before releasing file_reservations.")
            await ensure_schema()
            now = datetime.now(timezone.utc)
            released_reservations: list[FileReservation] = []
            async with get_session() as session:
                sel = select(FileReservation).where(
                    FileReservation.project_id == project.id,
                    FileReservation.agent_id == agent.id,
                    cast(Any, FileReservation.released_ts).is_(None),
                )
                if file_reservation_ids:
                    sel = sel.where(cast(Any, FileReservation.id).in_(file_reservation_ids))
                if paths:
                    sel = sel.where(cast(Any, FileReservation.path_pattern).in_(paths))
                rows = await session.execute(sel)
                released_reservations = list(rows.scalars().all())

                stmt = update(FileReservation).where(
                    FileReservation.project_id == project.id,
                    FileReservation.agent_id == agent.id,
                    cast(Any, FileReservation.released_ts).is_(None),
                )
                if file_reservation_ids:
                    stmt = stmt.where(cast(Any, FileReservation.id).in_(file_reservation_ids))
                if paths:
                    stmt = stmt.where(cast(Any, FileReservation.path_pattern).in_(paths))
                stmt = stmt.values(released_ts=now)
                result = await session.execute(stmt)
                await session.commit()
            affected = int(result.rowcount or 0)
            if affected and released_reservations:
                payloads: list[dict[str, object]] = []
                for reservation in released_reservations:
                    payloads.append(
                        {
                            "id": reservation.id,
                            "project": project.human_key,
                            "agent": agent.name,
                            "path_pattern": reservation.path_pattern,
                            "exclusive": reservation.exclusive,
                            "reason": reservation.reason,
                            "created_ts": _iso(reservation.created_ts),
                            "expires_ts": _iso(reservation.expires_ts),
                            "released_ts": _iso(now),
                        }
                    )
                await write_file_reservation_artifacts(
                    settings,
                    project.slug,
                    payloads,
                    project_key=project.human_key,
                )
            await ctx.info(f"Released {affected} file_reservations for '{agent.name}'.")
            return {"released": affected, "released_at": _iso(now)}
        except Exception as exc:
            if get_settings().tools_log_enabled:
                try:
                    import importlib as _imp

                    _rc = _imp.import_module("rich.console")
                    _rj = _imp.import_module("rich.json")
                    Console = _rc.Console
                    JSON = _rj.JSON
                    Console().print(JSON.from_data({"error": str(exc)}))
                except Exception:
                    pass
            raise

    @mcp.tool(name="force_release_file_reservation")
    @_instrument_tool(
        "force_release_file_reservation",
        cluster=CLUSTER_FILE_RESERVATIONS,
        capabilities={"file_reservations", "repository"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def force_release_file_reservation(
        ctx: Context,
        project_key: str,
        agent_name: str,
        file_reservation_id: int,
        notify_previous: bool = True,
        note: str = "",
    ) -> dict[str, Any]:
        """
        Force-release a stale file reservation held by another agent after inactivity heuristics.

        The tool validates that the reservation appears abandoned (agent inactive beyond threshold and
        no recent mail/filesystem/git activity). When released, an optional notification is sent to the
        previous holder summarizing the heuristics.
        """
        project = await _get_project_by_identifier(project_key)
        actor = await _get_agent(project, agent_name)
        if project.id is None:
            raise ValueError("Project must have an id before releasing file_reservations.")

        await ensure_schema()
        async with get_session() as session:
            result = await session.execute(
                select(FileReservation, Agent)
                .join(Agent, FileReservation.agent_id == Agent.id)
                .where(
                    FileReservation.id == file_reservation_id,
                    FileReservation.project_id == project.id,
                )
            )
            row = result.first()
        if not row:
            raise ToolExecutionError(
                "NOT_FOUND",
                f"File reservation id={file_reservation_id} not found for project '{project.human_key}'.",
                recoverable=True,
                data={"file_reservation_id": file_reservation_id},
            )

        reservation, holder = row
        if reservation.released_ts is not None:
            return {
                "released": 0,
                "released_at": _iso(reservation.released_ts),
                "already_released": True,
            }

        statuses = await _collect_file_reservation_statuses(project, include_released=False)
        target_status = next((status for status in statuses if status.reservation.id == reservation.id), None)
        if target_status is None:
            raise ToolExecutionError(
                "NOT_FOUND",
                "Unable to evaluate reservation status; it may have been released concurrently.",
                recoverable=True,
                data={"file_reservation_id": file_reservation_id},
            )

        if not target_status.stale:
            raise ToolExecutionError(
                "RESERVATION_ACTIVE",
                "Reservation still shows recent activity; refusing forced release.",
                recoverable=True,
                data={
                    "file_reservation_id": file_reservation_id,
                    "stale_reasons": target_status.stale_reasons,
                },
            )

        now = datetime.now(timezone.utc)
        async with get_session() as session:
            await session.execute(
                update(FileReservation)
                .where(
                    FileReservation.id == file_reservation_id,
                    cast(Any, FileReservation.released_ts).is_(None),
                )
                .values(released_ts=now)
            )
            await session.commit()

        reservation.released_ts = now
        settings = get_settings()
        grace_seconds = int(settings.file_reservation_activity_grace_seconds)
        inactivity_seconds = int(settings.file_reservation_inactivity_seconds)

        summary = {
            "id": reservation.id,
            "agent": holder.name,
            "path_pattern": reservation.path_pattern,
            "exclusive": reservation.exclusive,
            "reason": reservation.reason,
            "created_ts": _iso(reservation.created_ts),
            "expires_ts": _iso(reservation.expires_ts),
            "released_ts": _iso(reservation.released_ts),
            "stale_reasons": target_status.stale_reasons,
            "last_agent_activity_ts": _iso(target_status.last_agent_activity)
            if target_status.last_agent_activity
            else None,
            "last_mail_activity_ts": _iso(target_status.last_mail_activity)
            if target_status.last_mail_activity
            else None,
            "last_filesystem_activity_ts": _iso(target_status.last_fs_activity)
            if target_status.last_fs_activity
            else None,
            "last_git_activity_ts": _iso(target_status.last_git_activity) if target_status.last_git_activity else None,
        }

        # Emit an updated artifact so hooks/guards can observe the released state.
        artifact_payload = dict(summary)
        artifact_payload["project"] = project.human_key
        await write_file_reservation_artifacts(
            settings,
            project.slug,
            [cast(dict[str, object], artifact_payload)],
            project_key=project.human_key,
        )

        await ctx.info(
            f"Force released reservation {file_reservation_id} held by '{holder.name}' on '{reservation.path_pattern}'."
        )

        notified = False
        if notify_previous and holder.name != actor.name:
            reasons_md = "\n".join(f"- {reason}" for reason in target_status.stale_reasons)
            extras: list[str] = []
            if target_status.last_agent_activity:
                delta = now - target_status.last_agent_activity
                extras.append(f"last agent activity ≈ {int(delta.total_seconds() // 60)} minutes ago")
            if target_status.last_mail_activity:
                delta = now - target_status.last_mail_activity
                extras.append(f"last mail activity ≈ {int(delta.total_seconds() // 60)} minutes ago")
            if target_status.last_fs_activity:
                delta = now - target_status.last_fs_activity
                extras.append(f"last filesystem touch ≈ {int(delta.total_seconds() // 60)} minutes ago")
            if target_status.last_git_activity:
                delta = now - target_status.last_git_activity
                extras.append(f"last git commit ≈ {int(delta.total_seconds() // 60)} minutes ago")
            extras.append(f"inactivity threshold={inactivity_seconds}s grace={grace_seconds}s")
            extra_md = "\n".join(f"- {line}" for line in extras if line)
            body_lines = [
                f"Hi {holder.name},",
                "",
                f"I released your file reservation on `{reservation.path_pattern}` because it looked abandoned.",
                "",
                "Observed signals:",
                reasons_md or "- (none)",
            ]
            if extra_md:
                body_lines.extend(["", "Details:", extra_md])
            if note:
                body_lines.extend(["", f"Additional note from {actor.name}:", note.strip()])
            body_lines.extend(
                [
                    "",
                    "If you still need this reservation, please re-acquire it via `file_reservation_paths`.",
                ]
            )
            try:
                from fastmcp.tools.tool import FunctionTool

                send_tool = cast(FunctionTool, cast(Any, send_message))
                await send_tool.run(
                    {
                        "project_key": project_key,
                        "sender_name": agent_name,
                        "to": [holder.name],
                        "subject": f"[file-reservations] Released stale lock on {reservation.path_pattern}",
                        "body_md": "\n".join(body_lines),
                    }
                )
                notified = True
            except Exception:
                notified = False

        summary["notified"] = notified
        return {"released": 1, "released_at": _iso(now), "reservation": summary}

    @mcp.tool(name="renew_file_reservations")
    @_instrument_tool(
        "renew_file_reservations",
        cluster=CLUSTER_FILE_RESERVATIONS,
        capabilities={"file_reservations"},
        project_arg="project_key",
        agent_arg="agent_name",
    )
    async def renew_file_reservations(
        ctx: Context,
        project_key: str,
        agent_name: str,
        extend_seconds: int = 1800,
        paths: Optional[list[str]] = None,
        file_reservation_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        """
        Extend expiry for active file reservations held by an agent without reissuing them.

        Parameters
        ----------
        project_key : str
            Project slug or human key.
        agent_name : str
            Agent identity who owns the reservations.
        extend_seconds : int
            Seconds to extend from the later of now or current expiry (min 60s).
        paths : Optional[list[str]]
            Restrict renewals to matching path patterns.
        file_reservation_ids : Optional[list[int]]
            Restrict renewals to matching reservation ids.

        Returns
        -------
        dict
            { renewed: int, file_reservations: [{id, path_pattern, old_expires_ts, new_expires_ts}] }
        """
        if get_settings().tools_log_enabled:
            try:
                from rich.console import Console  # type: ignore
                from rich.panel import Panel  # type: ignore

                meta = [
                    f"project={project_key}",
                    f"agent={agent_name}",
                    f"extend={extend_seconds}s",
                    f"paths={len(paths or [])}",
                    f"ids={len(file_reservation_ids or [])}",
                ]
                Console().print(Panel.fit("\n".join(meta), title="tool: renew_file_reservations", border_style="green"))
            except Exception:
                pass
        project = await _get_project_by_identifier(project_key)
        agent = await _get_agent(project, agent_name)
        if project.id is None or agent.id is None:
            raise ValueError("Project and agent must have ids before renewing file_reservations.")
        await ensure_schema()
        now = datetime.now(timezone.utc)
        bump = max(60, int(extend_seconds))

        async with get_session() as session:
            stmt = (
                select(FileReservation)
                .where(
                    FileReservation.project_id == project.id,
                    FileReservation.agent_id == agent.id,
                    cast(Any, FileReservation.released_ts).is_(None),
                )
                .order_by(asc(FileReservation.expires_ts))
            )
            if file_reservation_ids:
                stmt = stmt.where(cast(Any, FileReservation.id).in_(file_reservation_ids))
            if paths:
                stmt = stmt.where(cast(Any, FileReservation.path_pattern).in_(paths))
            result = await session.execute(stmt)
            file_reservations: list[FileReservation] = list(result.scalars().all())

        if not file_reservations:
            await ctx.info(f"No active file_reservations to renew for '{agent.name}'.")
            return {"renewed": 0, "file_reservations": []}

        updated: list[dict[str, Any]] = []
        artifact_payloads: list[dict[str, object]] = []
        async with get_session() as session:
            for file_reservation in file_reservations:
                old_exp = file_reservation.expires_ts
                if getattr(old_exp, "tzinfo", None) is None:
                    from datetime import timezone as _tz

                    old_exp = old_exp.replace(tzinfo=_tz.utc)
                base = old_exp if old_exp > now else now
                file_reservation.expires_ts = base + timedelta(seconds=bump)
                session.add(file_reservation)
                updated.append(
                    {
                        "id": file_reservation.id,
                        "path_pattern": file_reservation.path_pattern,
                        "old_expires_ts": _iso(old_exp),
                        "new_expires_ts": _iso(file_reservation.expires_ts),
                    }
                )
                artifact_payloads.append(
                    {
                        "id": file_reservation.id,
                        "project": project.human_key,
                        "agent": agent.name,
                        "path_pattern": file_reservation.path_pattern,
                        "exclusive": file_reservation.exclusive,
                        "reason": file_reservation.reason,
                        "created_ts": _iso(file_reservation.created_ts),
                        "expires_ts": _iso(file_reservation.expires_ts),
                        "released_ts": None,
                    }
                )
            await session.commit()

        await ctx.info(f"Renewed {len(updated)} file_reservation(s) for '{agent.name}'.")
        return {"renewed": len(updated), "file_reservations": updated}

    @mcp.resource("resource://config/environment", mime_type="application/json")
    def environment_resource() -> dict[str, Any]:
        """
        Inspect the server's current environment and HTTP settings.

        When to use
        -----------
        - Debugging client connection issues (wrong host/port/path).
        - Verifying which environment (dev/stage/prod) the server is running in.

        Notes
        -----
        - This surfaces configuration only; it does not perform live health checks.

        Returns
        -------
        dict
            {
              "environment": str,
              "database_url": str,
              "http": { "host": str, "port": int, "path": str }
            }

        Example (JSON-RPC)
        ------------------
        ```json
        {"jsonrpc":"2.0","id":"r1","method":"resources/read","params":{"uri":"resource://config/environment"}}
        ```
        """
        return {
            "environment": settings.environment,
            "database_url": settings.database.url,
            "http": {
                "host": settings.http.host,
                "port": settings.http.port,
                "path": settings.http.path,
            },
        }

    # --- Product Bus (Phase 2): ensure/link/search/resources ---------------------------------

    async def _get_product_by_key(session, key: str) -> Optional[Product]:
        # Key may match product_uid or name (case-sensitive by default)
        stmt = select(Product).where((Product.product_uid == key) | (Product.name == key))
        res = await session.execute(stmt)
        return res.scalars().first()

    @mcp.tool(name="ensure_product")
    @_instrument_tool("ensure_product", cluster=CLUSTER_PRODUCT, capabilities={"product"})
    async def ensure_product_tool(
        ctx: Context,
        product_key: Optional[str] = None,
        name: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Ensure a Product exists. If not, create one.

        - product_key may be a product_uid or a name
        - If both are absent, error
        """
        await ensure_schema()
        key_raw = (product_key or name or "").strip()
        if not key_raw:
            raise ToolExecutionError("INVALID_ARGUMENT", "Provide product_key or name.")
        async with get_session() as session:
            prod = await _get_product_by_key(session, key_raw)
            if prod is None:
                # Create with strict uid pattern; otherwise generate uid and normalize name
                import re as _re
                import uuid as _uuid

                uid_pattern = _re.compile(r"^[A-Fa-f0-9]{8,64}$")
                if product_key and uid_pattern.fullmatch(product_key.strip()):
                    uid = product_key.strip().lower()
                else:
                    uid = _uuid.uuid4().hex[:20]
                display_name = (name or key_raw).strip()
                # Collapse internal whitespace and cap length
                display_name = " ".join(display_name.split())[:255] or uid
                prod = Product(product_uid=uid, name=display_name)
                session.add(prod)
                await session.commit()
                await session.refresh(prod)
        return {"id": prod.id, "product_uid": prod.product_uid, "name": prod.name, "created_at": _iso(prod.created_at)}

    @mcp.tool(name="products_link")
    @_instrument_tool("products_link", cluster=CLUSTER_PRODUCT, capabilities={"product"}, project_arg="project_key")
    async def products_link_tool(
        ctx: Context,
        product_key: str,
        project_key: str,
    ) -> dict[str, Any]:
        """
        Link a project into a product (idempotent).
        """
        await ensure_schema()
        async with get_session() as session:
            prod = await _get_product_by_key(session, product_key.strip())
            if prod is None:
                raise ToolExecutionError("NOT_FOUND", f"Product '{product_key}' not found.", recoverable=True)
            # Resolve project
            project = await _get_project_by_identifier(project_key)
            if project.id is None:
                raise ToolExecutionError("NOT_FOUND", f"Project '{project_key}' not found.", recoverable=True)
            # Link if missing
            existing = await session.execute(
                select(ProductProjectLink).where(
                    ProductProjectLink.product_id == cast(Any, prod.id),
                    ProductProjectLink.project_id == cast(Any, project.id),
                )
            )
            link = existing.scalars().first()
            if link is None:
                link = ProductProjectLink(product_id=int(prod.id), project_id=int(project.id))
                session.add(link)
                await session.commit()
                await session.refresh(link)
            return {
                "product": {"id": prod.id, "product_uid": prod.product_uid, "name": prod.name},
                "project": {"id": project.id, "slug": project.slug, "human_key": project.human_key},
                "linked": True,
            }

    @mcp.resource("resource://product/{key}", mime_type="application/json")
    def product_resource(key: str) -> dict[str, Any]:
        """
        Inspect product and list linked projects.
        """

        # Safe runner that works even if an event loop is already running
        def _run_coro_sync(coro):
            try:
                asyncio.get_running_loop()
                # Run in a separate thread to avoid nested loop issues
            except RuntimeError:
                return asyncio.run(coro)
            import queue  # type: ignore
            import threading  # type: ignore

            q: "queue.Queue[tuple[bool, Any]]" = queue.Queue()

            def _runner():
                try:
                    q.put((True, asyncio.run(coro)))
                except Exception as e:
                    q.put((False, e))

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            ok, val = q.get()
            if ok:
                return val
            raise val

        async def _load() -> dict[str, Any]:
            await ensure_schema()
            async with get_session() as session:
                prod = await _get_product_by_key(session, key.strip())
                if prod is None:
                    raise ToolExecutionError("NOT_FOUND", f"Product '{key}' not found.", recoverable=True)
                proj_rows = await session.execute(
                    select(Project)
                    .join(ProductProjectLink, ProductProjectLink.project_id == Project.id)
                    .where(ProductProjectLink.product_id == cast(Any, prod.id))
                )
                projects = [
                    {"id": p.id, "slug": p.slug, "human_key": p.human_key, "created_at": _iso(p.created_at)}
                    for p in proj_rows.scalars().all()
                ]
                return {
                    "id": prod.id,
                    "product_uid": prod.product_uid,
                    "name": prod.name,
                    "created_at": _iso(prod.created_at),
                    "projects": projects,
                }

        # Run async in a synchronous resource
        return _run_coro_sync(_load())

    @mcp.tool(name="search_messages_product")
    @_instrument_tool("search_messages_product", cluster=CLUSTER_PRODUCT, capabilities={"search"})
    async def search_messages_product(
        ctx: Context,
        product_key: str,
        query: str,
        limit: int = 20,
    ) -> Any:
        """
        Full-text search across all projects linked to a product.
        """
        await ensure_schema()
        async with get_session() as session:
            prod = await _get_product_by_key(session, product_key.strip())
            if prod is None:
                raise ToolExecutionError("NOT_FOUND", f"Product '{product_key}' not found.", recoverable=True)
            proj_ids_rows = await session.execute(
                select(ProductProjectLink.project_id).where(ProductProjectLink.product_id == cast(Any, prod.id))
            )
            proj_ids = [int(row[0]) for row in proj_ids_rows.fetchall()]
            if not proj_ids:
                return []
            # FTS search limited to projects in proj_ids
            result = await session.execute(
                text(
                    """
                    SELECT m.id, m.subject, m.body_md, m.importance, m.ack_required, m.created_ts,
                           m.thread_id, a.name AS sender_name, m.project_id
                    FROM fts_messages
                    JOIN messages m ON fts_messages.rowid = m.id
                    JOIN agents a ON m.sender_id = a.id
                    WHERE m.project_id IN (:proj_ids) AND fts_messages MATCH :query
                    ORDER BY bm25(fts_messages) ASC
                    LIMIT :limit
                    """
                ).bindparams(bindparam("proj_ids", expanding=True)),
                {"proj_ids": proj_ids, "query": query, "limit": limit},
            )
            rows = result.mappings().all()
        items = [
            {
                "id": row["id"],
                "subject": row["subject"],
                "importance": row["importance"],
                "ack_required": row["ack_required"],
                "created_ts": _iso(row["created_ts"]),
                "thread_id": row["thread_id"],
                "from": row["sender_name"],
                "project_id": row["project_id"],
            }
            for row in rows
        ]
        try:
            from fastmcp.tools.tool import ToolResult  # type: ignore

            return ToolResult(structured_content={"result": items})
        except Exception:
            return items

    @mcp.tool(name="fetch_inbox_product")
    @_instrument_tool("fetch_inbox_product", cluster=CLUSTER_PRODUCT, capabilities={"messaging", "read"})
    async def fetch_inbox_product(
        ctx: Context,
        product_key: str,
        agent_name: str,
        limit: int = 20,
        urgent_only: bool = False,
        include_bodies: bool = False,
        since_ts: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve recent messages for an agent across all projects linked to a product (non-mutating).
        """
        await ensure_schema()
        # Collect linked projects
        async with get_session() as session:
            prod = await _get_product_by_key(session, product_key.strip())
            if prod is None:
                raise ToolExecutionError("NOT_FOUND", f"Product '{product_key}' not found.", recoverable=True)
            proj_rows = await session.execute(
                select(Project)
                .join(ProductProjectLink, ProductProjectLink.project_id == Project.id)
                .where(ProductProjectLink.product_id == cast(Any, prod.id))
            )
            projects: list[Project] = list(proj_rows.scalars().all())
        # For each project, if agent exists, list inbox items
        messages: list[dict[str, Any]] = []
        for project in projects:
            try:
                ag = await _get_agent(project, agent_name)
            except Exception:
                continue
            proj_items = await _list_inbox(project, ag, limit, urgent_only, include_bodies, since_ts)
            for item in proj_items:
                item["project_id"] = item.get("project_id") or project.id
                messages.append(item)

        # Sort by created_ts desc and trim to limit
        def _dt_key(it: dict[str, Any]) -> float:
            ts = _parse_iso(str(it.get("created_ts") or ""))
            return ts.timestamp() if ts else 0.0

        messages.sort(key=_dt_key, reverse=True)
        return messages[: max(0, int(limit))]

    @mcp.tool(name="summarize_thread_product")
    @_instrument_tool("summarize_thread_product", cluster=CLUSTER_PRODUCT, capabilities={"summarization", "search"})
    async def summarize_thread_product(
        ctx: Context,
        product_key: str,
        thread_id: str,
        include_examples: bool = False,
        llm_mode: bool = True,
        llm_model: Optional[str] = None,
        per_thread_limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Summarize a thread (by id or thread key) across all projects linked to a product.
        """
        await ensure_schema()
        sender_alias = aliased(Agent)
        try:
            seed_id = int(thread_id)
        except ValueError:
            seed_id = None
        criteria = [Message.thread_id == thread_id]
        if seed_id is not None:
            criteria.append(Message.id == seed_id)

        async with get_session() as session:
            prod = await _get_product_by_key(session, product_key.strip())
            if prod is None:
                raise ToolExecutionError("NOT_FOUND", f"Product '{product_key}' not found.", recoverable=True)
            proj_ids_rows = await session.execute(
                select(ProductProjectLink.project_id).where(ProductProjectLink.product_id == cast(Any, prod.id))
            )
            proj_ids = [int(row[0]) for row in proj_ids_rows.fetchall()]
            if not proj_ids:
                return {
                    "thread_id": thread_id,
                    "summary": {"participants": [], "key_points": [], "action_items": [], "total_messages": 0},
                    "examples": [],
                }
            stmt = (
                select(Message, sender_alias.name)
                .join(sender_alias, Message.sender_id == sender_alias.id)
                .where(cast(Any, Message.project_id).in_(proj_ids), or_(*criteria))
                .order_by(asc(Message.created_ts))
            )
            if per_thread_limit:
                stmt = stmt.limit(per_thread_limit)
            rows = (await session.execute(stmt)).all()
        summary = _summarize_messages(rows)

        # Optional LLM refinement (same as project-level)
        if llm_mode and get_settings().llm.enabled:
            try:
                excerpts: list[str] = []
                for message, sender_name in rows[:15]:
                    excerpts.append(f"- {sender_name}: {message.subject}\n{message.body_md[:800]}")
                if excerpts:
                    system = (
                        "You are a senior engineer. Produce a concise JSON summary with keys: "
                        "participants[], key_points[], action_items[], mentions[{name,count}], code_references[], "
                        "total_messages, open_actions, done_actions. Derive from the given thread excerpts."
                    )
                    user = "\n\n".join(excerpts)
                    llm_resp = await complete_system_user(system, user, model=llm_model)
                    parsed = _parse_json_safely(llm_resp.content)
                    if parsed:
                        for key in (
                            "participants",
                            "key_points",
                            "action_items",
                            "mentions",
                            "code_references",
                            "total_messages",
                            "open_actions",
                            "done_actions",
                        ):
                            value = parsed.get(key)
                            if value:
                                summary[key] = value
            except Exception as e:
                await ctx.debug(f"summarize_thread_product.llm_skipped: {e}")

        examples: list[dict[str, Any]] = []
        if include_examples:
            for message, sender_name in rows[:3]:
                examples.append(
                    {
                        "id": message.id,
                        "subject": message.subject,
                        "from": sender_name,
                        "created_ts": _iso(message.created_ts),
                    }
                )
        await ctx.info(f"Summarized thread '{thread_id}' across product '{product_key}' with {len(rows)} messages")
        return {"thread_id": thread_id, "summary": summary, "examples": examples}

    @mcp.resource("resource://identity/{project}", mime_type="application/json")
    def identity_resource(project: str) -> dict[str, Any]:
        """
        Inspect identity resolution for a given project path. Returns the slug actually used,
        the identity mode in effect, canonical path for the selected mode, and git repo facts.
        """
        raw_path, _ = _split_slug_and_query(project)
        target_path = str(Path(raw_path).expanduser().resolve())

        return _resolve_project_identity(target_path)

    @mcp.resource("resource://tooling/directory", mime_type="application/json")
    def tooling_directory_resource() -> dict[str, Any]:
        """
        Provide a clustered view of exposed MCP tools to combat option overload.

        The directory groups tools by workflow, outlines primary use cases,
        highlights nearby alternatives, and shares starter playbooks so agents
        can focus on the verbs relevant to their immediate task.
        """

        clusters = [
            {
                "name": "Infrastructure & Workspace Setup",
                "purpose": "Bootstrap coordination and guardrails before agents begin editing.",
                "tools": [
                    {
                        "name": "health_check",
                        "summary": "Report environment and HTTP wiring so orchestrators confirm connectivity.",
                        "use_when": "Beginning a session or during incident response triage.",
                        "related": ["ensure_project"],
                        "expected_frequency": "Once per agent session or when connectivity is in doubt.",
                        "required_capabilities": ["infrastructure"],
                        "usage_examples": [{"hint": "Pre-flight", "sample": "health_check()"}],
                    },
                    {
                        "name": "ensure_project",
                        "summary": "Ensure project slug, schema, and archive exist for a shared repo identifier.",
                        "use_when": "First call against a repo or when switching projects.",
                        "related": ["register_agent", "file_reservation_paths"],
                        "expected_frequency": "Whenever a new repo/path is encountered.",
                        "required_capabilities": ["infrastructure", "storage"],
                        "usage_examples": [
                            {"hint": "First action", "sample": "ensure_project(human_key='/abs/path/backend')"}
                        ],
                    },
                    {
                        "name": "install_precommit_guard",
                        "summary": "Install Git pre-commit hook that enforces advisory file_reservations locally.",
                        "use_when": "Onboarding a repository into coordinated mode.",
                        "related": ["file_reservation_paths", "uninstall_precommit_guard"],
                        "expected_frequency": "Infrequent—per repository setup.",
                        "required_capabilities": ["repository", "filesystem"],
                        "usage_examples": [
                            {
                                "hint": "Onboard",
                                "sample": "install_precommit_guard(project_key='backend', code_repo_path='~/repo')",
                            }
                        ],
                    },
                    {
                        "name": "uninstall_precommit_guard",
                        "summary": "Remove the advisory pre-commit hook from a repo.",
                        "use_when": "Decommissioning or debugging the guard hook.",
                        "related": ["install_precommit_guard"],
                        "expected_frequency": "Rare; only when disabling guard enforcement.",
                        "required_capabilities": ["repository"],
                        "usage_examples": [
                            {"hint": "Cleanup", "sample": "uninstall_precommit_guard(code_repo_path='~/repo')"}
                        ],
                    },
                    {
                        "name": "acquire_build_slot",
                        "summary": "Acquire exclusive build slot for coordinating parallel build operations.",
                        "use_when": "Before starting builds/tests that need exclusive access to resources.",
                        "related": ["renew_build_slot", "release_build_slot"],
                        "expected_frequency": "Once per build/test cycle.",
                        "required_capabilities": ["coordination"],
                        "usage_examples": [
                            {
                                "hint": "Acquire slot",
                                "sample": "acquire_build_slot(project_key='backend', agent_name='BuildAgent', slot='frontend-build')",
                            }
                        ],
                    },
                    {
                        "name": "renew_build_slot",
                        "summary": "Extend expiration of an active build slot.",
                        "use_when": "When build operations are taking longer than expected TTL.",
                        "related": ["acquire_build_slot", "release_build_slot"],
                        "expected_frequency": "As needed during long-running builds.",
                        "required_capabilities": ["coordination"],
                        "usage_examples": [
                            {
                                "hint": "Renew slot",
                                "sample": "renew_build_slot(project_key='backend', agent_name='BuildAgent', slot='frontend-build', extend_seconds=1800)",
                            }
                        ],
                    },
                    {
                        "name": "release_build_slot",
                        "summary": "Release an acquired build slot.",
                        "use_when": "After completing build operations or on error/cleanup.",
                        "related": ["acquire_build_slot", "renew_build_slot"],
                        "expected_frequency": "Once per build/test cycle.",
                        "required_capabilities": ["coordination"],
                        "usage_examples": [
                            {
                                "hint": "Release slot",
                                "sample": "release_build_slot(project_key='backend', agent_name='BuildAgent', slot='frontend-build')",
                            }
                        ],
                    },
                ],
            },
            {
                "name": "Identity & Directory",
                "purpose": "Register agents, mint unique identities, and inspect directory metadata.",
                "tools": [
                    {
                        "name": "register_agent",
                        "summary": "Upsert an agent profile and refresh last_active_ts for a known persona.",
                        "use_when": "Resuming an identity or updating program/model/task metadata.",
                        "related": ["create_agent_identity", "whois"],
                        "expected_frequency": "At the start of each automated work session.",
                        "required_capabilities": ["identity"],
                        "usage_examples": [
                            {
                                "hint": "Resume persona",
                                "sample": "register_agent(project_key='/abs/path/backend', program='codex', model='gpt5')",
                            }
                        ],
                    },
                    {
                        "name": "create_agent_identity",
                        "summary": "Always create a new unique agent name (optionally using a sanitized hint).",
                        "use_when": "Spawning a brand-new helper that should not overwrite existing profiles.",
                        "related": ["register_agent"],
                        "expected_frequency": "When minting fresh, short-lived identities.",
                        "required_capabilities": ["identity"],
                        "usage_examples": [
                            {
                                "hint": "New helper",
                                "sample": "create_agent_identity(project_key='backend', name_hint='GreenCastle', program='codex', model='gpt5')",
                            }
                        ],
                    },
                    {
                        "name": "whois",
                        "summary": "Return enriched profile info plus recent archive commits for an agent.",
                        "use_when": "Dashboarding, routing coordination messages, or auditing activity.",
                        "related": ["register_agent"],
                        "expected_frequency": "Ad hoc when context about an agent is required.",
                        "required_capabilities": ["identity", "audit"],
                        "usage_examples": [
                            {
                                "hint": "Directory lookup",
                                "sample": "whois(project_key='backend', agent_name='BlueLake')",
                            }
                        ],
                    },
                ],
            },
            {
                "name": "Messaging Lifecycle",
                "purpose": "Send, receive, and acknowledge threaded Markdown mail.",
                "tools": [
                    {
                        "name": "send_message",
                        "summary": "Deliver a new message with attachments, WebP conversion, and policy enforcement.",
                        "use_when": "Starting new threads or broadcasting plans across projects.",
                        "related": ["reply_message"],
                        "expected_frequency": "Frequent—core write operation.",
                        "required_capabilities": ["messaging"],
                        "usage_examples": [
                            {
                                "hint": "New plan",
                                "sample": "send_message(project_key='backend', sender_name='GreenCastle', to=['BlueLake'], subject='Plan', body_md='...')",
                            }
                        ],
                    },
                    {
                        "name": "reply_message",
                        "summary": "Reply within an existing thread, inheriting flags and default recipients.",
                        "use_when": "Continuing discussions or acknowledging decisions.",
                        "related": ["send_message"],
                        "expected_frequency": "Frequent when collaborating inside a thread.",
                        "required_capabilities": ["messaging"],
                        "usage_examples": [
                            {
                                "hint": "Thread reply",
                                "sample": "reply_message(project_key='backend', message_id=42, sender_name='BlueLake', body_md='Got it!')",
                            }
                        ],
                    },
                    {
                        "name": "fetch_inbox",
                        "summary": "Poll recent messages for an agent with filters (urgent_only, since_ts).",
                        "use_when": "After each work unit to ingest coordination updates.",
                        "related": ["mark_message_read", "acknowledge_message"],
                        "expected_frequency": "Frequent polling in agent loops.",
                        "required_capabilities": ["messaging", "read"],
                        "usage_examples": [
                            {
                                "hint": "Poll",
                                "sample": "fetch_inbox(project_key='backend', agent_name='BlueLake', since_ts='2025-10-24T00:00:00Z')",
                            }
                        ],
                    },
                    {
                        "name": "mark_message_read",
                        "summary": "Record read_ts for FYI messages without sending acknowledgements.",
                        "use_when": "Clearing inbox notifications once reviewed.",
                        "related": ["acknowledge_message"],
                        "expected_frequency": "Whenever FYI mail is processed.",
                        "required_capabilities": ["messaging", "read"],
                        "usage_examples": [
                            {
                                "hint": "Read receipt",
                                "sample": "mark_message_read(project_key='backend', agent_name='BlueLake', message_id=42)",
                            }
                        ],
                    },
                    {
                        "name": "acknowledge_message",
                        "summary": "Set read_ts and ack_ts so senders know action items landed.",
                        "use_when": "Responding to ack_required messages.",
                        "related": ["mark_message_read"],
                        "expected_frequency": "Each time a message requests acknowledgement.",
                        "required_capabilities": ["messaging", "ack"],
                        "usage_examples": [
                            {
                                "hint": "Ack",
                                "sample": "acknowledge_message(project_key='backend', agent_name='BlueLake', message_id=42)",
                            }
                        ],
                    },
                ],
            },
            {
                "name": "Search & Summaries",
                "purpose": "Surface signal from large mailboxes and compress long threads.",
                "tools": [
                    {
                        "name": "search_messages",
                        "summary": "Run FTS5 queries across subject/body text to locate relevant threads.",
                        "use_when": "Triage or gathering context before editing.",
                        "related": ["fetch_inbox", "summarize_thread"],
                        "expected_frequency": "Regular during investigation phases.",
                        "required_capabilities": ["search"],
                        "usage_examples": [
                            {
                                "hint": "FTS",
                                "sample": "search_messages(project_key='backend', query='\"build plan\" AND users', limit=20)",
                            }
                        ],
                    },
                    {
                        "name": "summarize_thread",
                        "summary": "Extract participants, key points, and action items for a single thread.",
                        "use_when": "Briefing new agents on long discussions or closing loops.",
                        "related": ["summarize_threads"],
                        "expected_frequency": "When threads exceed quick skim length.",
                        "required_capabilities": ["search", "summarization"],
                        "usage_examples": [
                            {
                                "hint": "Thread brief",
                                "sample": "summarize_thread(project_key='backend', thread_id='TKT-123', include_examples=True)",
                            }
                        ],
                    },
                    {
                        "name": "summarize_threads",
                        "summary": "Produce a digest across multiple threads with aggregate mentions/actions.",
                        "use_when": "Daily standups or cross-team sync summaries.",
                        "related": ["summarize_thread"],
                        "expected_frequency": "At cadence checkpoints (daily/weekly).",
                        "required_capabilities": ["search", "summarization"],
                        "usage_examples": [
                            {
                                "hint": "Digest",
                                "sample": "summarize_threads(project_key='backend', thread_ids=['TKT-123','UX-42'])",
                            }
                        ],
                    },
                ],
            },
            {
                "name": "File Reservations & Workspace Guardrails",
                "purpose": "Coordinate file/glob ownership to avoid overwriting concurrent work.",
                "tools": [
                    {
                        "name": "file_reservation_paths",
                        "summary": "Issue advisory file_reservations with overlap detection and Git artifacts.",
                        "use_when": "Before touching high-traffic surfaces or long-lived refactors.",
                        "related": ["release_file_reservations", "renew_file_reservations"],
                        "expected_frequency": "Whenever starting work on contested surfaces.",
                        "required_capabilities": ["file_reservations", "repository"],
                        "usage_examples": [
                            {
                                "hint": "Lock file",
                                "sample": "file_reservation_paths(project_key='backend', agent_name='BlueLake', paths=['src/app.py'], ttl_seconds=7200)",
                            }
                        ],
                    },
                    {
                        "name": "release_file_reservations",
                        "summary": "Release active file_reservations (fully or by subset) and stamp released_ts.",
                        "use_when": "Finishing work so surfaces become available again.",
                        "related": ["file_reservation_paths", "renew_file_reservations"],
                        "expected_frequency": "Each time work on a surface completes.",
                        "required_capabilities": ["file_reservations"],
                        "usage_examples": [
                            {
                                "hint": "Unlock",
                                "sample": "release_file_reservations(project_key='backend', agent_name='BlueLake', paths=['src/app.py'])",
                            }
                        ],
                    },
                    {
                        "name": "renew_file_reservations",
                        "summary": "Extend file_reservation expiry windows without allocating new file_reservation IDs.",
                        "use_when": "Long-running work needs more time but should retain ownership.",
                        "related": ["file_reservation_paths", "release_file_reservations"],
                        "expected_frequency": "Periodically during multi-hour work items.",
                        "required_capabilities": ["file_reservations"],
                        "usage_examples": [
                            {
                                "hint": "Extend",
                                "sample": "renew_file_reservations(project_key='backend', agent_name='BlueLake', extend_seconds=1800)",
                            }
                        ],
                    },
                ],
            },
            {
                "name": "Workflow Macros",
                "purpose": "Opinionated orchestrations that compose multiple primitives for smaller agents.",
                "tools": [
                    {
                        "name": "macro_start_session",
                        "summary": "Ensure project, register/update agent, optionally file_reservation surfaces, and return inbox context.",
                        "use_when": "Kickstarting a focused work session with one call.",
                        "related": ["ensure_project", "register_agent", "file_reservation_paths", "fetch_inbox"],
                        "expected_frequency": "At the beginning of each autonomous session.",
                        "required_capabilities": ["workflow", "messaging", "file_reservations", "identity"],
                        "usage_examples": [
                            {
                                "hint": "Bootstrap",
                                "sample": "macro_start_session(human_key='/abs/path/backend', program='codex', model='gpt5', file_reservation_paths=['src/api/*.py'])",
                            }
                        ],
                    },
                    {
                        "name": "macro_prepare_thread",
                        "summary": "Register or refresh an agent, summarise a thread, and fetch inbox context in one call.",
                        "use_when": "Briefing a helper before joining an ongoing discussion.",
                        "related": ["register_agent", "summarize_thread", "fetch_inbox"],
                        "expected_frequency": "Whenever onboarding a new contributor to an active thread.",
                        "required_capabilities": ["workflow", "messaging", "summarization"],
                        "usage_examples": [
                            {
                                "hint": "Join thread",
                                "sample": "macro_prepare_thread(project_key='backend', thread_id='TKT-123', program='codex', model='gpt5', agent_name='ThreadHelper')",
                            }
                        ],
                    },
                    {
                        "name": "macro_file_reservation_cycle",
                        "summary": "FileReservation a set of paths and optionally release them once work is complete.",
                        "use_when": "Wrapping a focused edit cycle that needs advisory locks.",
                        "related": ["file_reservation_paths", "release_file_reservations", "renew_file_reservations"],
                        "expected_frequency": "Per guarded work block.",
                        "required_capabilities": ["workflow", "file_reservations", "repository"],
                        "usage_examples": [
                            {
                                "hint": "FileReservation & release",
                                "sample": "macro_file_reservation_cycle(project_key='backend', agent_name='BlueLake', paths=['src/app.py'], auto_release=true)",
                            }
                        ],
                    },
                ],
            },
        ]

        for cluster in clusters:
            for tool_entry in cluster["tools"]:
                tool_dict = cast(dict[str, Any], tool_entry)
                meta = TOOL_METADATA.get(str(tool_dict.get("name", "")))
                if not meta:
                    continue
                tool_dict["capabilities"] = meta["capabilities"]
                tool_dict.setdefault("complexity", meta["complexity"])
                if "required_capabilities" in tool_dict:
                    tool_dict["required_capabilities"] = meta["capabilities"]

        playbooks = [
            {
                "workflow": "Kick off new agent session (macro)",
                "sequence": ["health_check", "macro_start_session", "summarize_thread"],
            },
            {
                "workflow": "Kick off new agent session (manual)",
                "sequence": ["health_check", "ensure_project", "register_agent", "fetch_inbox"],
            },
            {
                "workflow": "Start focused refactor",
                "sequence": [
                    "ensure_project",
                    "file_reservation_paths",
                    "send_message",
                    "fetch_inbox",
                    "acknowledge_message",
                ],
            },
            {
                "workflow": "Join existing discussion",
                "sequence": ["macro_prepare_thread", "reply_message", "acknowledge_message"],
            },
        ]

        return {
            "generated_at": _iso(datetime.now(timezone.utc)),
            "metrics_uri": "resource://tooling/metrics",
            "clusters": clusters,
            "playbooks": playbooks,
        }

    @mcp.resource("resource://tooling/schemas", mime_type="application/json")
    def tooling_schemas_resource() -> dict[str, Any]:
        """Expose JSON-like parameter schemas for tools/macros to prevent drift.

        This is a lightweight, hand-maintained view focusing on the most error-prone
        parameters and accepted aliases to guide clients.
        """
        return {
            "generated_at": _iso(datetime.now(timezone.utc)),
            "tools": {
                "send_message": {
                    "required": ["sender_name", "subject", "body_md"],
                    "optional": [
                        "project_key",
                        "to",
                        "cc",
                        "bcc",
                        "attachment_paths",
                        "convert_images",
                        "importance",
                        "ack_required",
                        "thread_id",
                        "auto_contact_if_blocked",
                    ],
                    "shapes": {
                        "to": "list[str]",
                        "cc": "list[str] | str",
                        "bcc": "list[str] | str",
                        "importance": "low|normal|high|urgent",
                        "auto_contact_if_blocked": "bool",
                    },
                },
            },
        }

    @mcp.resource("resource://tooling/metrics", mime_type="application/json")
    def tooling_metrics_resource() -> dict[str, Any]:
        """Expose aggregated tool call/error counts for analysis."""
        return {
            "generated_at": _iso(datetime.now(timezone.utc)),
            "tools": _tool_metrics_snapshot(),
        }

    @mcp.resource("resource://tooling/locks", mime_type="application/json")
    def tooling_locks_resource() -> dict[str, Any]:
        """Return lock metadata from the shared archive storage."""

        settings_local = get_settings()
        return collect_lock_status(settings_local)

    @mcp.resource("resource://tooling/capabilities/{agent}", mime_type="application/json")
    def tooling_capabilities_resource(agent: str, project: Optional[str] = None) -> dict[str, Any]:
        # Parse query embedded in agent path if present (robust to FastMCP variants)
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
            except Exception:
                pass
        caps = _capabilities_for(agent, project)
        return {
            "generated_at": _iso(datetime.now(timezone.utc)),
            "agent": agent,
            "project": project,
            "capabilities": caps,
        }

    @mcp.resource("resource://tooling/recent/{window_seconds}", mime_type="application/json")
    def tooling_recent_resource(
        window_seconds: str,
        agent: Optional[str] = None,
        project: Optional[str] = None,
    ) -> dict[str, Any]:
        # Allow query string to be embedded in the path segment per some transports
        if "?" in window_seconds:
            seg, _, qs = window_seconds.partition("?")
            window_seconds = seg
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                agent = agent or (parsed.get("agent") or [None])[0]
                project = project or (parsed.get("project") or [None])[0]
            except Exception:
                pass
        try:
            win = int(window_seconds)
        except Exception:
            win = 60
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, win))
        entries: list[dict[str, Any]] = []
        for ts, tool_name, proj, ag in list(RECENT_TOOL_USAGE):
            if ts < cutoff:
                continue
            if project and proj != project:
                continue
            if agent and ag != agent:
                continue

            record = {
                "timestamp": _iso(ts),
                "tool": tool_name,
                "project": proj,
                "agent": ag,
                "cluster": TOOL_CLUSTER_MAP.get(tool_name, "unclassified"),
            }
            entries.append(record)
        return {
            "generated_at": _iso(datetime.now(timezone.utc)),
            "window_seconds": win,
            "count": len(entries),
            "entries": entries,
        }

    @mcp.resource("resource://projects", mime_type="application/json")
    async def projects_resource() -> list[dict[str, Any]]:
        """
        List all projects known to the server in creation order.

        When to use
        -----------
        - Discover available projects when a user provides only an agent name.
        - Build UIs that let operators switch context between projects.

        Returns
        -------
        list[dict]
            Each: { id, slug, human_key, created_at }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"r2","method":"resources/read","params":{"uri":"resource://projects"}}
        ```
        """
        settings = get_settings()
        await ensure_schema(settings)
        # Build ignore matcher for test/demo projects
        import fnmatch as _fnmatch

        ignore_patterns = set(getattr(settings, "retention_ignore_project_patterns", []) or [])
        async with get_session() as session:
            result = await session.execute(select(Project).order_by(asc(Project.created_at)))
            projects = result.scalars().all()

            def _is_ignored(name: str) -> bool:
                return any(_fnmatch.fnmatch(name, pat) for pat in ignore_patterns)

            filtered = [p for p in projects if not (_is_ignored(p.slug) or _is_ignored(p.human_key))]
            return [_project_to_dict(project) for project in filtered]

    @mcp.resource("resource://project/{slug}", mime_type="application/json")
    async def project_detail(slug: str) -> dict[str, Any]:
        """
        Fetch a project and its agents by project slug or human key.

        When to use
        -----------
        - Populate an "LDAP-like" directory for agents in tooling UIs.
        - Determine available agent identities and their metadata before addressing mail.

        Parameters
        ----------
        slug : str
            Project slug (or human key; both resolve to the same target).

        Returns
        -------
        dict
            Project descriptor including { agents: [...] } with agent profiles.

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"r3","method":"resources/read","params":{"uri":"resource://project/backend-abc123"}}
        ```
        """
        project = await _get_project_by_identifier(slug)
        await ensure_schema()
        async with get_session() as session:
            result = await session.execute(
                select(Agent).where(
                    Agent.project_id == project.id,
                    cast(Any, Agent.is_active).is_(True),
                )
            )
            agents_raw = result.scalars().all()
        global_inbox_name = get_global_inbox_name(project)
        agents = sorted(
            agents_raw,
            key=lambda agent: (
                agent.name == global_inbox_name,
                -(agent.last_active_ts.timestamp() if agent.last_active_ts else 0.0),
                -(agent.id or 0),
            ),
        )
        return {
            **_project_to_dict(project),
            "agents": [_agent_to_dict(agent) for agent in agents],
        }

    @mcp.resource("resource://agents", mime_type="application/json")
    async def agents_directory_global() -> dict[str, Any]:
        """
        List ALL active agents across all projects (global agent directory).

        This is the CANONICAL way to discover agents. Agent names are globally unique,
        so this endpoint shows the complete namespace of registered agents.

        When to use
        -----------
        - ALWAYS use this first when looking for an agent by name.
        - Before sending messages to verify recipients exist.
        - At session start to see all active agents across the system.
        - When cross-project collaboration is needed.

        Returns
        -------
        dict
            {
              "agents": [
                {
                  "name": "BackendDev",
                  "program": "claude-code",
                  "model": "sonnet-4.5",
                  "task_description": "API development",
                  "project_slug": "backend-abc123",
                  "project_human_key": "backend",
                  "inception_ts": "2025-10-25T...",
                  "last_active_ts": "2025-10-25T...",
                  "unread_count": 3
                },
                ...
              ],
              "total": 42
            }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"r5","method":"resources/read","params":{"uri":"resource://agents"}}
        ```

        Notes
        -----
        - Agent names are globally unique across all projects.
        - Use whois(agent_name) to get detailed info about a specific agent.
        - Cross-project messaging is fully supported; project boundaries are informational only.
        - This is the primary agent discovery endpoint; prefer this over project-scoped views.
        """
        await ensure_schema()

        async with get_session() as session:
            # Join agents with projects to get project info
            result = await session.execute(
                select(Agent, Project)
                .join(Project, Agent.project_id == Project.id)
                .where(cast(Any, Agent.is_active).is_(True))
                .order_by(desc(Agent.last_active_ts))
            )
            rows = result.all()

            # Get agent IDs for unread count query
            agent_ids = [row.Agent.id for row in rows]

            # Get unread message counts for all agents in one query
            unread_counts_map: dict[int, int] = {}
            if agent_ids:
                unread_counts_stmt = (
                    select(MessageRecipient.agent_id, func.count(MessageRecipient.message_id).label("unread_count"))
                    .where(
                        cast(Any, MessageRecipient.read_ts).is_(None),
                        cast(Any, MessageRecipient.agent_id).in_(agent_ids),
                    )
                    .group_by(MessageRecipient.agent_id)
                )
                unread_counts_result = await session.execute(unread_counts_stmt)
                unread_counts_map = {row.agent_id: row.unread_count for row in unread_counts_result}

            # Build agent data with project info and unread counts
            agent_data = []
            for row in rows:
                agent = row.Agent
                project = row.Project
                agent_dict = _agent_to_dict(agent)
                agent_dict["project_slug"] = project.slug
                agent_dict["project_human_key"] = project.human_key
                agent_dict["unread_count"] = unread_counts_map.get(agent.id, 0)
                agent_data.append(agent_dict)

        return {
            "agents": agent_data,
            "total": len(agent_data),
        }

    @mcp.resource("resource://agents/{project_key}", mime_type="application/json")
    async def agents_directory(project_key: str) -> dict[str, Any]:
        """
        List agents in a specific project (FILTERED VIEW - prefer resource://agents for discovery).

        DEPRECATION NOTICE
        ------------------
        This endpoint returns a project-filtered view only. Agent names are globally unique,
        so filtering by project may cause you to miss agents you're looking for.

        **Prefer resource://agents for agent discovery.**

        Use this endpoint only when you specifically need to see agents working on a
        particular project.

        When to use
        -----------
        - To see which agents are currently assigned to a specific project.
        - NOT for general agent discovery (use resource://agents instead).

        Parameters
        ----------
        project_key : str
            Project slug or human key (both work).

        Returns
        -------
        dict
            {
              "_notice": "Filtered view only. Use resource://agents for complete global agent list.",
              "project": { "slug": "...", "human_key": "..." },
              "agents": [
                {
                  "name": "BackendDev",
                  "program": "claude-code",
                  "model": "sonnet-4.5",
                  "task_description": "API development",
                  "inception_ts": "2025-10-25T...",
                  "last_active_ts": "2025-10-25T...",
                  "unread_count": 3
                },
                ...
              ]
            }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"r5","method":"resources/read","params":{"uri":"resource://agents/backend-abc123"}}
        ```

        Notes
        -----
        - Agent names are NOT the same as your program name or user name.
        - Use the returned names when calling tools like whois(), send_message().
        - This directory lists agents registered in the specified project ONLY.
        - Agent names are globally unique; an agent not in this list may still exist elsewhere.
        - For complete agent discovery, use resource://agents instead.
        """
        project = await _get_project_by_identifier(project_key)
        await ensure_schema()

        async with get_session() as session:
            # Get all active agents in the project
            result = await session.execute(
                select(Agent)
                .where(
                    Agent.project_id == project.id,
                    cast(Any, Agent.is_active).is_(True),
                )
                .order_by(desc(Agent.last_active_ts))
            )
            agents = result.scalars().all()

            # Get unread message counts for all agents in one query
            agent_ids = [agent.id for agent in agents if agent.id is not None]
            unread_counts_map: dict[int, int] = {}
            if agent_ids:
                unread_counts_stmt = (
                    select(MessageRecipient.agent_id, func.count(MessageRecipient.message_id).label("unread_count"))
                    .where(
                        cast(Any, MessageRecipient.read_ts).is_(None),
                        cast(Any, MessageRecipient.agent_id).in_(agent_ids),
                    )
                    .group_by(MessageRecipient.agent_id)
                )
                unread_counts_result = await session.execute(unread_counts_stmt)
                unread_counts_map = {row.agent_id: row.unread_count for row in unread_counts_result}

            # Build agent data with unread counts
            agent_data = []
            for agent in agents:
                agent_dict = _agent_to_dict(agent)
                agent_dict["unread_count"] = unread_counts_map.get(agent.id, 0)
                agent_data.append(agent_dict)

        return {
            "_notice": "Filtered view only. Use resource://agents for complete global agent list.",
            "project": {
                "slug": project.slug,
                "human_key": project.human_key,
            },
            "agents": agent_data,
        }

    @mcp.resource("resource://file_reservations/{slug}", mime_type="application/json")
    async def file_reservations_resource(slug: str, active_only: bool = False) -> list[dict[str, Any]]:
        """
        List file_reservations for a project, optionally filtering to active-only.

        Why this exists
        ---------------
        - File reservations communicate edit intent and reduce collisions across agents.
        - Surfacing them helps humans review ongoing work and resolve contention.

        Why this exists
        ---------------
        - Claims communicate edit intent and reduce collisions across agents.
        - Surfacing them helps humans review ongoing work and resolve contention.

        Parameters
        ----------
        slug : str
            Project slug or human key.
        active_only : bool
            If true (default), only returns file_reservations with no `released_ts`.

        Returns
        -------
        list[dict]
            Each file_reservation with { id, agent, path_pattern, exclusive, reason, created_ts, expires_ts, released_ts }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"r4","method":"resources/read","params":{"uri":"resource://file_reservations/backend-abc123?active_only=true"}}
        ```

        Also see all historical (including released) file_reservations:
        ```json
        {"jsonrpc":"2.0","id":"r4b","method":"resources/read","params":{"uri":"resource://file_reservations/backend-abc123?active_only=false"}}
        ```

        Also see all historical (including released) claims:
        ```json
        {"jsonrpc":"2.0","id":"r4b","method":"resources/read","params":{"uri":"resource://claims/backend-abc123?active_only=false"}}
        ```
        """
        slug_value, query_params = _split_slug_and_query(slug)
        if "active_only" in query_params:
            active_only = _coerce_flag_to_bool(query_params["active_only"], default=active_only)

        project = await _get_project_by_identifier(slug_value)
        await ensure_schema()
        if project.id is None:
            raise ValueError("Project must have an id before listing file_reservations.")

        await _expire_stale_file_reservations(project.id)
        statuses = await _collect_file_reservation_statuses(project, include_released=not active_only)

        payload: list[dict[str, Any]] = []
        for status in statuses:
            reservation = status.reservation
            if active_only and reservation.released_ts is not None:
                continue
            payload.append(
                {
                    "id": reservation.id,
                    "agent": status.agent.name,
                    "path_pattern": reservation.path_pattern,
                    "exclusive": reservation.exclusive,
                    "reason": reservation.reason,
                    "created_ts": _iso(reservation.created_ts),
                    "expires_ts": _iso(reservation.expires_ts),
                    "released_ts": _iso(reservation.released_ts) if reservation.released_ts else None,
                    "stale": status.stale,
                    "stale_reasons": status.stale_reasons,
                    "last_agent_activity_ts": _iso(status.last_agent_activity) if status.last_agent_activity else None,
                    "last_mail_activity_ts": _iso(status.last_mail_activity) if status.last_mail_activity else None,
                    "last_filesystem_activity_ts": _iso(status.last_fs_activity) if status.last_fs_activity else None,
                    "last_git_activity_ts": _iso(status.last_git_activity) if status.last_git_activity else None,
                }
            )
        return payload

    @mcp.resource("resource://message/{message_id}", mime_type="application/json")
    async def message_resource(message_id: str, project: Optional[str] = None) -> dict[str, Any]:
        """
        Read a single message by id within a project.

        When to use
        -----------
        - Fetch the canonical body/metadata for rendering in a client after list/search.
        - Retrieve attachments and full details for a given message id.

        Parameters
        ----------
        message_id : str
            Numeric id as a string.
        project : str
            Project slug or human key (required for disambiguation).

        Common mistakes
        ---------------
        - Omitting `project` when a message id might exist in multiple projects.

        Returns
        -------
        dict
            Full message payload including body and sender name.

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"r5","method":"resources/read","params":{"uri":"resource://message/1234?project=/abs/path/backend"}}
        ```
        """
        # Support toolkits that pass query in the template segment
        if "?" in message_id:
            id_part, _, qs = message_id.partition("?")
            message_id = id_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
            except Exception:
                pass
        if project is None:
            # Try to infer project by message id when unique
            async with get_session() as s_auto:
                rows = await s_auto.execute(
                    select(Project, Message)
                    .join(Message, Message.project_id == Project.id)
                    .where(cast(Any, Message.id) == int(message_id))
                    .limit(2)
                )
                data = rows.all()
            if len(data) == 1:
                project_obj = data[0][0]
            else:
                raise ValueError("project parameter is required for message resource")
        else:
            project_obj = await _get_project_by_identifier(project)
        message = await _get_message(project_obj, int(message_id))
        sender = await _get_agent_by_id(project_obj, message.sender_id)
        payload = _message_to_dict(message, include_body=True)
        payload["from"] = sender.name
        return payload

    @mcp.resource("resource://thread/{thread_id*}", mime_type="application/json")
    async def thread_resource(
        thread_id: str,
        project: Optional[str] = None,
        include_bodies: bool = False,
    ) -> dict[str, Any]:
        """
        List messages for a thread within a project.

        When to use
        -----------
        - Present a conversation view for a given ticket/thread key.
        - Export a thread for summarization or reporting.

        Parameters
        ----------
        thread_id : str
            Either a string thread key or a numeric message id to seed the thread.
        project : Optional[str]
            Project slug or human key. If omitted, the server attempts to infer it from a unique
            numeric seed (message id) or a uniquely-scoped thread key; otherwise a ValueError is raised.
        include_bodies : bool
            Include message bodies if true (default false).

        Returns
        -------
        dict
            { project, thread_id, messages: [{...}] }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"r6","method":"resources/read","params":{"uri":"resource://thread/TKT-123?project=/abs/path/backend&include_bodies=true"}}
        ```

        Numeric seed example (message id as thread seed):
        ```json
        {"jsonrpc":"2.0","id":"r6b","method":"resources/read","params":{"uri":"resource://thread/1234?project=/abs/path/backend"}}
        ```
        """
        # Robust query parsing: FastMCP with greedy patterns may include query string in path segment.
        # Extract query parameters from thread_id if present, as FastMCP may not extract them automatically.
        if "?" in thread_id:
            id_part, _, qs = thread_id.partition("?")
            thread_id = id_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and "project" in parsed and parsed["project"]:
                    project = parsed["project"][0]
                # Always parse include_bodies from query string if present, overriding any default
                if parsed.get("include_bodies"):
                    include_bodies = _coerce_flag_to_bool(parsed["include_bodies"][0], default=False)
            except Exception:
                pass

        logger.debug(
            f"thread_resource called: thread_id={thread_id!r}, project={project!r}, include_bodies={include_bodies!r}"
        )

        # Determine project if omitted by client
        if project is None:
            # Auto-detect project using numeric seed (message id) or unique thread key
            async with get_session() as s_auto:
                try:
                    msg_id = int(thread_id)
                except ValueError:
                    msg_id = None
                if msg_id is not None:
                    rows = await s_auto.execute(
                        select(Project)
                        .join(Message, Message.project_id == Project.id)
                        .where(cast(Any, Message.id) == msg_id)
                        .limit(2)
                    )
                    projects = [row[0] for row in rows.all()]
                else:
                    rows = await s_auto.execute(
                        select(Project)
                        .join(Message, Message.project_id == Project.id)
                        .where(Message.thread_id == thread_id)
                        .limit(2)
                    )
                    projects = [row[0] for row in rows.all()]
            if len(projects) == 1:
                project_obj = projects[0]
            else:
                raise ValueError("project parameter is required for thread resource")
        else:
            project_obj = await _get_project_by_identifier(project)

        if project_obj.id is None:
            raise ValueError("Project must have an id before listing threads.")
        await ensure_schema()
        try:
            message_id = int(thread_id)
        except ValueError:
            message_id = None
        sender_alias = aliased(Agent)
        criteria = [Message.thread_id == thread_id]
        if message_id is not None:
            criteria.append(Message.id == message_id)
        async with get_session() as session:
            stmt = (
                select(Message, sender_alias.name)
                .join(sender_alias, Message.sender_id == sender_alias.id)
                .where(Message.project_id == project_obj.id, or_(*criteria))
                .order_by(asc(Message.created_ts))
            )
            result = await session.execute(stmt)
            rows = result.all()
        messages = []
        for message, sender_name in rows:
            payload = _message_to_dict(message, include_body=include_bodies)
            payload["from"] = sender_name
            messages.append(payload)
        return {"project": project_obj.human_key, "thread_id": thread_id, "messages": messages}

    @mcp.resource(
        "resource://inbox/{agent}",
        mime_type="application/json",
    )
    async def inbox_resource(
        agent: str,
        project: Optional[str] = None,
        since_ts: Optional[str] = None,
        urgent_only: bool = False,
        include_bodies: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Read an agent's inbox for a project.

        Parameters
        ----------
        agent : str
            Agent name.
        project : str
            Project slug or human key (required).
        since_ts : Optional[str]
            ISO-8601 timestamp string; only messages newer than this are returned.
        urgent_only : bool
            If true, limits to importance in {high, urgent}.
        include_bodies : bool
            Include message bodies in results (default false).
        limit : int
            Maximum number of messages to return (default 20).

        Returns
        -------
        dict
            { project, agent, count, messages: [...] }

        Example
        -------
        ```json
        {"jsonrpc":"2.0","id":"r7","method":"resources/read","params":{"uri":"resource://inbox/BlueLake?project=/abs/path/backend&limit=10&urgent_only=true"}}
        ```
        Incremental fetch example (using since_ts):
        ```json
        {"jsonrpc":"2.0","id":"r7b","method":"resources/read","params":{"uri":"resource://inbox/BlueLake?project=/abs/path/backend&since_ts=2025-10-23T15:00:00Z"}}
        ```
        """
        # Robust query parsing: some FastMCP versions do not inject query args.
        # If the templating layer included the query string in the last path segment,
        # extract it and fill missing parameters.
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and "project" in parsed and parsed["project"]:
                    project = parsed["project"][0]
                if since_ts is None and "since_ts" in parsed and parsed["since_ts"]:
                    since_ts = parsed["since_ts"][0]
                if parsed.get("urgent_only"):
                    val = parsed["urgent_only"][0].strip().lower()
                    urgent_only = val in ("1", "true", "t", "yes", "y")
                if parsed.get("include_bodies"):
                    val = parsed["include_bodies"][0].strip().lower()
                    include_bodies = val in ("1", "true", "t", "yes", "y")
                if parsed.get("limit"):
                    with suppress(Exception):
                        limit = int(parsed["limit"][0])
            except Exception:
                pass

        if project is None:
            # Auto-detect project by agent name if uniquely identifiable
            async with get_session() as s_auto:
                rows = await s_auto.execute(
                    select(Project)
                    .join(Agent, Agent.project_id == Project.id)
                    .where(func.lower(Agent.name) == agent.lower(), cast(Any, Agent.is_active).is_(True))
                    .limit(2)
                )
                projects = [row[0] for row in rows.all()]
            if len(projects) == 1:
                project_obj = projects[0]
            else:
                raise ValueError("project parameter is required for inbox resource")
        else:
            project_obj = await _get_project_by_identifier(project)
        agent_obj = await _get_agent(project_obj, agent)
        messages = await _list_inbox(project_obj, agent_obj, limit, urgent_only, include_bodies, since_ts)
        # Enrich with commit info for canonical markdown files (best-effort)
        enriched: list[dict[str, Any]] = []
        for item in messages:
            try:
                msg_obj = await _get_message(project_obj, int(item["id"]))
                commit_info = await _commit_info_for_message(settings, project_obj, msg_obj)
                if commit_info:
                    item["commit"] = commit_info
            except Exception:
                pass
            enriched.append(item)
        return {
            "project": project_obj.human_key,
            "agent": agent_obj.name,
            "count": len(enriched),
            "messages": enriched,
        }

    @mcp.resource("resource://views/urgent-unread/{agent}", mime_type="application/json")
    async def urgent_unread_view(agent: str, project: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        """
        Convenience view listing urgent and high-importance messages that are unread for an agent.

        Parameters
        ----------
        agent : str
            Agent name.
        project : str
            Project slug or human key (required).
        limit : int
            Max number of messages.
        """
        # Parse query embedded in agent path if present
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
                if parsed.get("limit"):
                    with suppress(Exception):
                        limit = int(parsed["limit"][0])
            except Exception:
                pass

        if project is None:
            async with get_session() as s_auto:
                rows = await s_auto.execute(
                    select(Project)
                    .join(Agent, Agent.project_id == Project.id)
                    .where(func.lower(Agent.name) == agent.lower(), cast(Any, Agent.is_active).is_(True))
                    .limit(2)
                )
                projects = [row[0] for row in rows.all()]
            if len(projects) == 1:
                project_obj = projects[0]
            else:
                raise ValueError("project parameter is required for urgent view")
        else:
            project_obj = await _get_project_by_identifier(project)
        agent_obj = await _get_agent(project_obj, agent)
        items = await _list_inbox(project_obj, agent_obj, limit, urgent_only=True, include_bodies=False, since_ts=None)
        # Filter unread (no read_ts recorded)
        unread: list[dict[str, Any]] = []
        async with get_session() as session:
            for item in items:
                result = await session.execute(
                    select(MessageRecipient.read_ts).where(
                        MessageRecipient.message_id == item["id"], MessageRecipient.agent_id == agent_obj.id
                    )
                )
                read_ts = result.scalar_one_or_none()
                if read_ts is None:
                    unread.append(item)
        return {
            "project": project_obj.human_key,
            "agent": agent_obj.name,
            "count": len(unread),
            "messages": unread[:limit],
        }

    @mcp.resource("resource://views/ack-required/{agent}", mime_type="application/json")
    async def ack_required_view(agent: str, project: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        """
        Convenience view listing messages requiring acknowledgement for an agent where ack is pending.

        Parameters
        ----------
        agent : str
            Agent name.
        project : str
            Project slug or human key (required).
        limit : int
            Max number of messages.
        """
        # Parse query embedded in agent path if present
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
                if parsed.get("limit"):
                    with suppress(Exception):
                        limit = int(parsed["limit"][0])
            except Exception:
                pass

        if project is None:
            async with get_session() as s_auto:
                rows = await s_auto.execute(
                    select(Project)
                    .join(Agent, Agent.project_id == Project.id)
                    .where(func.lower(Agent.name) == agent.lower(), cast(Any, Agent.is_active).is_(True))
                    .limit(2)
                )
                projects = [row[0] for row in rows.all()]
            if len(projects) == 1:
                project_obj = projects[0]
            else:
                raise ValueError("project parameter is required for ack view")
        else:
            project_obj = await _get_project_by_identifier(project)
        agent_obj = await _get_agent(project_obj, agent)
        if project_obj.id is None or agent_obj.id is None:
            raise ValueError("Project/agent IDs must exist")
        await ensure_schema()
        out: list[dict[str, Any]] = []
        async with get_session() as session:
            rows = await session.execute(
                select(Message, MessageRecipient.kind)
                .join(MessageRecipient, MessageRecipient.message_id == Message.id)
                .where(
                    Message.project_id == project_obj.id,
                    MessageRecipient.agent_id == agent_obj.id,
                    cast(Any, Message.ack_required).is_(True),
                    cast(Any, MessageRecipient.ack_ts).is_(None),
                )
                .order_by(desc(Message.created_ts))
                .limit(limit)
            )
            for msg, kind in rows.all():
                payload = _message_to_dict(msg, include_body=False)
                payload["kind"] = kind
                out.append(payload)
        return {"project": project_obj.human_key, "agent": agent_obj.name, "count": len(out), "messages": out}

    @mcp.resource("resource://views/acks-stale/{agent}", mime_type="application/json")
    async def acks_stale_view(
        agent: str,
        project: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        List ack-required messages older than a TTL where acknowledgement is still missing.

        Parameters
        ----------
        agent : str
            Agent name.
        project : str
            Project slug or human key (required).
        ttl_seconds : Optional[int]
            Minimum age in seconds to consider a message stale. Defaults to settings.ack_ttl_seconds.
        limit : int
            Max number of messages to return.
        """
        # Parse query embedded in agent path if present
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
                if parsed.get("ttl_seconds"):
                    with suppress(Exception):
                        ttl_seconds = int(parsed["ttl_seconds"][0])
                if parsed.get("limit"):
                    with suppress(Exception):
                        limit = int(parsed["limit"][0])
            except Exception:
                pass

        if project is None:
            async with get_session() as s_auto:
                rows = await s_auto.execute(
                    select(Project)
                    .join(Agent, Agent.project_id == Project.id)
                    .where(func.lower(Agent.name) == agent.lower(), cast(Any, Agent.is_active).is_(True))
                    .limit(2)
                )
                projects = [row[0] for row in rows.all()]
            if len(projects) == 1:
                project_obj = projects[0]
            else:
                raise ValueError("project parameter is required for stale acks view")
        else:
            project_obj = await _get_project_by_identifier(project)
        agent_obj = await _get_agent(project_obj, agent)
        if project_obj.id is None or agent_obj.id is None:
            raise ValueError("Project/agent IDs must exist")
        await ensure_schema()
        ttl = int(ttl_seconds) if ttl_seconds is not None else get_settings().ack_ttl_seconds
        now = datetime.now(timezone.utc)
        out: list[dict[str, Any]] = []
        async with get_session() as session:
            rows = await session.execute(
                select(Message, MessageRecipient.kind, MessageRecipient.read_ts)
                .join(MessageRecipient, MessageRecipient.message_id == Message.id)
                .where(
                    Message.project_id == project_obj.id,
                    MessageRecipient.agent_id == agent_obj.id,
                    cast(Any, Message.ack_required).is_(True),
                    cast(Any, MessageRecipient.ack_ts).is_(None),
                )
                .order_by(asc(Message.created_ts))
                .limit(limit * 5)
            )
            for msg, kind, read_ts in rows.all():
                # Coerce potential naive datetimes from SQLite to UTC for arithmetic
                created = msg.created_ts
                if getattr(created, "tzinfo", None) is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_s = int((now - created).total_seconds())
                if age_s >= ttl:
                    payload = _message_to_dict(msg, include_body=False)
                    payload["kind"] = kind
                    payload["read_at"] = _iso(read_ts) if read_ts else None
                    payload["age_seconds"] = age_s
                    out.append(payload)
                    if len(out) >= limit:
                        break
        return {
            "project": project_obj.human_key,
            "agent": agent_obj.name,
            "ttl_seconds": ttl,
            "count": len(out),
            "messages": out,
        }

    @mcp.resource("resource://views/ack-overdue/{agent}", mime_type="application/json")
    async def ack_overdue_view(
        agent: str,
        project: Optional[str] = None,
        ttl_minutes: int = 60,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List messages requiring acknowledgement older than ttl_minutes without ack."""
        # Parse query embedded in agent path if present
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
                if parsed.get("ttl_minutes"):
                    with suppress(Exception):
                        ttl_minutes = int(parsed["ttl_minutes"][0])
                if parsed.get("limit"):
                    with suppress(Exception):
                        limit = int(parsed["limit"][0])
            except Exception:
                pass

        if project is None:
            async with get_session() as s_auto:
                rows = await s_auto.execute(
                    select(Project)
                    .join(Agent, Agent.project_id == Project.id)
                    .where(func.lower(Agent.name) == agent.lower(), cast(Any, Agent.is_active).is_(True))
                    .limit(2)
                )
                projects = [row[0] for row in rows.all()]
            if len(projects) == 1:
                project_obj = projects[0]
            else:
                raise ValueError("project parameter is required for ack-overdue view")
        else:
            project_obj = await _get_project_by_identifier(project)
        agent_obj = await _get_agent(project_obj, agent)
        if project_obj.id is None or agent_obj.id is None:
            raise ValueError("Project/agent IDs must exist")
        await ensure_schema()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, ttl_minutes))
        out: list[dict[str, Any]] = []
        async with get_session() as session:
            rows = await session.execute(
                select(Message, MessageRecipient.kind)
                .join(MessageRecipient, MessageRecipient.message_id == Message.id)
                .where(
                    Message.project_id == project_obj.id,
                    MessageRecipient.agent_id == agent_obj.id,
                    cast(Any, Message.ack_required).is_(True),
                    cast(Any, MessageRecipient.ack_ts).is_(None),
                )
                .order_by(asc(Message.created_ts))
                .limit(limit * 5)
            )
            for msg, kind in rows.all():
                created = msg.created_ts
                if getattr(created, "tzinfo", None) is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created <= cutoff:
                    payload = _message_to_dict(msg, include_body=False)
                    payload["kind"] = kind
                    out.append(payload)
                    if len(out) >= limit:
                        break
        return {"project": project_obj.human_key, "agent": agent_obj.name, "count": len(out), "messages": out}

    @mcp.resource("resource://mailbox/{agent}", mime_type="application/json")
    async def mailbox_resource(agent: str, project: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        """
        List recent messages in an agent's mailbox.

        Returns
        -------
        dict
            { project, agent, count, messages: [{ id, subject, from, created_ts, importance, ack_required, kind, commit: null }] }
        """
        # Parse query embedded in agent path if present
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
                if parsed.get("limit"):
                    with suppress(Exception):
                        limit = int(parsed["limit"][0])
            except Exception:
                pass

        if project is None:
            async with get_session() as s_auto:
                rows = await s_auto.execute(
                    select(Project)
                    .join(Agent, Agent.project_id == Project.id)
                    .where(func.lower(Agent.name) == agent.lower(), cast(Any, Agent.is_active).is_(True))
                    .limit(2)
                )
                projects = [row[0] for row in rows.all()]
            if len(projects) == 1:
                project_obj = projects[0]
            else:
                raise ValueError("project parameter is required for mailbox resource")
        else:
            project_obj = await _get_project_by_identifier(project)
        agent_obj = await _get_agent(project_obj, agent)
        items = await _list_inbox(project_obj, agent_obj, limit, urgent_only=False, include_bodies=False, since_ts=None)

        # NOTE: Archive storage has been removed. commit metadata is no longer available.
        out: list[dict[str, Any]] = []
        for item in items:
            payload = dict(item)
            payload["commit"] = None
            out.append(payload)
        return {"project": project_obj.human_key, "agent": agent_obj.name, "count": len(out), "messages": out}

    @mcp.resource(
        "resource://mailbox-with-commits/{agent}",
        mime_type="application/json",
    )
    async def mailbox_with_commits_resource(
        agent: str, project: Optional[str] = None, limit: int = 20
    ) -> dict[str, Any]:
        """List recent messages in an agent's mailbox (commit metadata unavailable)."""
        # Parse query embedded in agent path if present
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
                if parsed.get("limit"):
                    with suppress(Exception):
                        limit = int(parsed["limit"][0])
            except Exception:
                pass
        if project is None:
            async with get_session() as s_auto:
                rows = await s_auto.execute(
                    select(Project)
                    .join(Agent, Agent.project_id == Project.id)
                    .where(func.lower(Agent.name) == agent.lower(), cast(Any, Agent.is_active).is_(True))
                    .limit(2)
                )
                projects = [row[0] for row in rows.all()]
            if len(projects) == 1:
                project_obj = projects[0]
            else:
                raise ValueError("project parameter is required for mailbox-with-commits resource")
        else:
            project_obj = await _get_project_by_identifier(project)
        agent_obj = await _get_agent(project_obj, agent)
        items = await _list_inbox(project_obj, agent_obj, limit, urgent_only=False, include_bodies=False, since_ts=None)

        out: list[dict[str, Any]] = []
        for item in items:
            payload = dict(item)
            payload["commit"] = None
            out.append(payload)
        return {"project": project_obj.human_key, "agent": agent_obj.name, "count": len(out), "messages": out}

    @mcp.resource("resource://outbox/{agent}", mime_type="application/json")
    async def outbox_resource(
        agent: str,
        project: Optional[str] = None,
        limit: int = 20,
        include_bodies: bool = False,
        since_ts: Optional[str] = None,
    ) -> dict[str, Any]:
        """List messages sent by the agent (commit metadata unavailable)."""
        # Support toolkits that incorrectly pass query in the template segment
        if "?" in agent:
            name_part, _, qs = agent.partition("?")
            agent = name_part
            try:
                from urllib.parse import parse_qs

                parsed = parse_qs(qs, keep_blank_values=False)
                if project is None and parsed.get("project"):
                    project = parsed["project"][0]
                if parsed.get("limit"):
                    from contextlib import suppress

                    with suppress(Exception):
                        limit = int(parsed["limit"][0])
                if parsed.get("include_bodies"):
                    include_bodies = parsed["include_bodies"][0].lower() in {"1", "true", "t", "yes", "y"}
                if parsed.get("since_ts"):
                    since_ts = parsed["since_ts"][0]
            except Exception:
                pass
        if project is None:
            raise ValueError("project parameter is required for outbox resource")
        project_obj = await _get_project_by_identifier(project)
        agent_obj = await _get_agent(project_obj, agent)
        items = await _list_outbox(project_obj, agent_obj, limit, include_bodies, since_ts)
        out: list[dict[str, Any]] = []
        for item in items:
            payload = dict(item)
            payload["commit"] = None
            out.append(payload)
        return {"project": project_obj.human_key, "agent": agent_obj.name, "count": len(out), "messages": out}

    # No explicit output-schema transform; the tool returns ToolResult with {"result": ...}

    @mcp.tool(name="slack_post_message")
    @_instrument_tool("slack_post_message", cluster=CLUSTER_MESSAGING, capabilities={"messaging", "slack", "write"})
    async def slack_post_message(
        ctx: Context,
        channel: str,
        text: str,
        thread_ts: str = "",
    ) -> dict[str, Any]:
        """
        Post a message to a Slack channel.

        Purpose
        -------
        Send notifications or messages to Slack channels for external visibility
        or to notify non-MCP team members about important events.

        Parameters
        ----------
        channel : str
            Slack channel ID (e.g., "C1234567890") or name (e.g., "#general")
        text : str
            Message text to post (supports Slack mrkdwn formatting)
        thread_ts : str, optional
            Thread timestamp to reply in a specific thread

        Returns
        -------
        dict
            {
              "ok": true,
              "channel": "C1234567890",
              "ts": "1503435956.000247",
              "permalink": "https://example.slack.com/archives/..."
            }

        Examples
        --------
        Post a simple message:
            slack_post_message(
                channel="general",
                text="Deployment to production completed successfully!"
            )

        Reply in a thread:
            slack_post_message(
                channel="C1234567890",
                text="I've completed the review",
                thread_ts="1503435956.000247"
            )

        Raises
        ------
        ToolExecutionError
            - SLACK_DISABLED: Slack integration is not enabled
            - SLACK_API_ERROR: Failed to post message to Slack
        """
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(
                        f"channel={channel[:50]}, text={text[:100]}",
                        title="tool: slack_post_message",
                        border_style="green",
                    )
                )
            except Exception:
                # Suppress all exceptions from rich logging to avoid interfering with main tool execution
                pass

        settings = get_settings()
        if not settings.slack.enabled or not _slack_client:
            raise ToolExecutionError(
                "SLACK_DISABLED",
                "Slack client is not available (disabled or failed to initialize). "
                "Verify SLACK_ENABLED/SLACK_BOT_TOKEN and check startup logs.",
                recoverable=False,
            )

        try:
            result = await _slack_client.post_message(
                channel=channel,
                text=text,
                thread_ts=thread_ts if thread_ts else None,
            )

            # Get permalink for the message
            permalink = ""
            if result.get("ok") and result.get("channel") and result.get("ts"):
                # Permalink retrieval is non-critical; log failures only at debug level
                try:
                    permalink = await _slack_client.get_permalink(
                        channel=result["channel"],
                        message_ts=result["ts"],
                    )
                except Exception as ex:
                    logger.debug(
                        "slack_post_message.permalink_failed",
                        extra={
                            "channel": result.get("channel"),
                            "ts": result.get("ts"),
                            "error": str(ex),
                        },
                    )

            await ctx.info(f"Posted message to Slack channel {channel}")
            return {
                "ok": True,
                "channel": result.get("channel", ""),
                "ts": result.get("ts", ""),
                "permalink": permalink,
            }

        except Exception as e:
            logger.error(f"Slack API error: {e}")
            raise ToolExecutionError(
                "SLACK_API_ERROR",
                f"Failed to post message to Slack: {e}",
                recoverable=True,
                data={"channel": channel},
            ) from e

    @mcp.tool(name="slack_list_channels")
    @_instrument_tool("slack_list_channels", cluster=CLUSTER_MESSAGING, capabilities={"messaging", "slack", "read"})
    async def slack_list_channels(ctx: Context) -> dict[str, Any]:
        """
        List available Slack channels.

        Purpose
        -------
        Discover available Slack channels that the bot has access to,
        useful for determining where to post messages.

        Returns
        -------
        dict
            {
              "channels": [
                {
                  "id": "C1234567890",
                  "name": "general",
                  "is_private": false,
                  "is_archived": false,
                  "num_members": 42
                },
                ...
              ],
              "count": 10
            }

        Raises
        ------
        ToolExecutionError
            - SLACK_DISABLED: Slack integration is not enabled
            - SLACK_API_ERROR: Failed to list channels
        """
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(Panel.fit("", title="tool: slack_list_channels", border_style="green"))
            except Exception:
                # Suppress all exceptions from rich logging to avoid interfering with tool execution
                pass

        settings = get_settings()
        if not settings.slack.enabled or not _slack_client:
            raise ToolExecutionError(
                "SLACK_DISABLED",
                "Slack client is not available (disabled or failed to initialize). "
                "Verify SLACK_ENABLED/SLACK_BOT_TOKEN and check startup logs.",
                recoverable=False,
            )

        try:
            channels_data = await _slack_client.list_channels(exclude_archived=True)
            channels = [
                {
                    "id": ch.get("id", ""),
                    "name": ch.get("name", ""),
                    "is_private": ch.get("is_private", False),
                    "is_archived": ch.get("is_archived", False),
                    "num_members": ch.get("num_members", 0),
                }
                for ch in channels_data
            ]

            await ctx.info(f"Listed {len(channels)} Slack channels")
            return {
                "channels": channels,
                "count": len(channels),
            }

        except Exception as e:
            logger.error(f"Slack API error: {e}")
            raise ToolExecutionError(
                "SLACK_API_ERROR",
                f"Failed to list Slack channels: {e}",
                recoverable=True,
            ) from e

    @mcp.tool(name="slack_get_channel_info")
    @_instrument_tool("slack_get_channel_info", cluster=CLUSTER_MESSAGING, capabilities={"messaging", "slack", "read"})
    async def slack_get_channel_info(ctx: Context, channel: str) -> dict[str, Any]:
        """
        Get detailed information about a Slack channel.

        Parameters
        ----------
        channel : str
            Channel ID to lookup

        Returns
        -------
        dict
            {
              "id": "C1234567890",
              "name": "general",
              "is_private": false,
              "topic": "General discussion",
              "purpose": "Company-wide announcements",
              "num_members": 42
            }

        Raises
        ------
        ToolExecutionError
            - SLACK_DISABLED: Slack integration is not enabled
            - SLACK_API_ERROR: Failed to get channel info
        """
        if get_settings().tools_log_enabled:
            try:
                import importlib as _imp

                _rc = _imp.import_module("rich.console")
                _rp = _imp.import_module("rich.panel")
                Console = _rc.Console
                Panel = _rp.Panel
                Console().print(
                    Panel.fit(f"channel={channel}", title="tool: slack_get_channel_info", border_style="green")
                )
            except Exception:
                # Ignore all errors in rich logging to avoid interfering with tool execution
                pass

        settings = get_settings()
        if not settings.slack.enabled or not _slack_client:
            raise ToolExecutionError(
                "SLACK_DISABLED",
                "Slack client is not available (disabled or failed to initialize). "
                "Verify SLACK_ENABLED/SLACK_BOT_TOKEN and check startup logs.",
                recoverable=False,
            )

        try:
            channel_info = await _slack_client.get_channel_info(channel)

            result = {
                "id": channel_info.get("id", ""),
                "name": channel_info.get("name", ""),
                "is_private": channel_info.get("is_private", False),
                "topic": channel_info.get("topic", {}).get("value", ""),
                "purpose": channel_info.get("purpose", {}).get("value", ""),
                "num_members": channel_info.get("num_members", 0),
            }

            await ctx.info(f"Retrieved info for channel {channel}")
            return result

        except Exception as e:
            logger.error(f"Slack API error: {e}")
            raise ToolExecutionError(
                "SLACK_API_ERROR",
                f"Failed to get channel info: {e}",
                recoverable=True,
                data={"channel": channel},
            ) from e

    # Populate extended tool registry for dynamic invocation via call_extended_tool
    _EXTENDED_TOOL_REGISTRY.update(
        {
            "acknowledge_message": acknowledge_message,
            "acquire_build_slot": acquire_build_slot,
            "create_agent_identity": create_agent_identity,
            "create_file_reservation": create_file_reservation,
            "delete_agent": delete_agent,
            "file_reservation_paths": file_reservation_paths,
            "force_release_file_reservation": force_release_file_reservation,
            "install_precommit_guard": install_precommit_guard,
            "macro_file_reservation_cycle": macro_file_reservation_cycle,
            "macro_prepare_thread": macro_prepare_thread,
            "macro_start_session": macro_start_session,
            "release_build_slot": release_build_slot,
            "release_file_reservations": release_file_reservations_tool,
            "renew_build_slot": renew_build_slot,
            "renew_file_reservations": renew_file_reservations,
            "search_messages": search_messages,
            "summarize_thread": summarize_thread,
            "summarize_threads": summarize_threads,
            "uninstall_precommit_guard": uninstall_precommit_guard,
            "slack_post_message": slack_post_message,
            "slack_list_channels": slack_list_channels,
            "slack_get_channel_info": slack_get_channel_info,
        }
    )

    # Conditional tool exposure based on tools_mode setting
    if settings.tools_mode == "core":
        # In core mode, hide extended tools from direct MCP exposure
        # They remain accessible via call_extended_tool meta-tool
        # Note: Meta-tools (list_extended_tools, call_extended_tool) are intentionally
        # NOT in CORE_TOOLS or EXTENDED_TOOLS - they're kept by not being in EXTENDED_TOOLS
        # Remove extended tools using FastMCP's remove_tool method
        for tool_name in EXTENDED_TOOLS:
            try:
                mcp.remove_tool(tool_name)
            except (KeyError, AttributeError, ValueError) as e:
                # Tool might not exist or already removed, that's ok
                logger.debug(f"Could not remove tool {tool_name}: {e}")

        # Count remaining tools by checking what's in CORE_TOOLS + meta tools
        exposed_count = len(CORE_TOOLS) + 2  # +2 for list_extended_tools and call_extended_tool
        hidden_count = len(EXTENDED_TOOLS)
        logger.info(f"Core mode enabled: Exposed {exposed_count} tools (hidden {hidden_count} extended tools)")
    else:
        # Extended mode: all tools exposed
        total_count = len(CORE_TOOLS) + len(EXTENDED_TOOLS) + 2  # +2 for meta tools
        logger.info(f"Extended mode: All {total_count} tools exposed directly")

    return mcp
