"""HTTP transport helpers wrapping FastMCP with FastAPI."""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hmac
import importlib
import json
import logging
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, NoResultFound
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import Receive, Scope, Send

from .app import (
    DEFAULT_PROJECT_KEY,
    _create_message,
    _ensure_project,
    _expire_stale_file_reservations,
    _get_agent_by_name_optional,
    _get_default_project,
    _message_frontmatter,
    _tool_metrics_snapshot,
    build_mcp_server,
    get_project_sibling_data,
    refresh_project_sibling_suggestions,
    update_project_sibling_status,
)
from .config import Settings, get_settings
from .db import ensure_schema, get_session
from .models import Agent
from .storage import (
    collect_lock_status,
    ensure_archive,
    get_agent_communication_graph,
    get_archive_tree,
    get_commit_detail,
    get_file_content,
    get_historical_inbox_snapshot,
    get_message_commit_sha,
    get_recent_commits,
    get_timeline_commits,
    is_archive_enabled,
    write_message_bundle,
)

# Slack webhook dedupe cache (in-memory best-effort)
# NOTE: We use a plain deque (no maxlen) and manage eviction manually to keep
# the set and deque in sync. Using deque(maxlen=N) causes auto-eviction that
# would desynchronize the set, leading to unbounded memory growth.
_slack_event_cache: set[tuple[str, str]] = set()
_slack_event_cache_order: deque[tuple[str, str]] = deque()
_SLACK_EVENT_CACHE_MAX_SIZE = 5000
_slack_event_cache_lock = asyncio.Lock()


async def _project_slug_from_id(pid: int | None) -> str | None:
    if pid is None:
        return None
    async with get_session() as session:
        row = await session.execute(text("SELECT slug FROM projects WHERE id = :pid"), {"pid": pid})
        res = row.fetchone()
        return res[0] if res and res[0] else None


async def _project_identifiers_from_id(pid: int | None) -> tuple[str | None, str | None]:
    """Return (slug, human_key) for a project id, or (None, None) if missing."""
    if pid is None:
        return None, None
    async with get_session() as session:
        row = await session.execute(text("SELECT slug, human_key FROM projects WHERE id = :pid"), {"pid": pid})
        res = row.fetchone()
        if not res:
            return None, None
        return (res[0], res[1])


async def _project_from_thread_id(thread_id: str | None) -> tuple[int, str, str] | None:
    """Look up the project of the first message in a thread.

    Returns (project_id, slug, human_key) if a message with thread_id exists,
    otherwise None. Used to route Slack replies to the original message's project.
    """
    if not thread_id:
        return None
    await ensure_schema()
    async with get_session() as session:
        row = await session.execute(
            text("""
                SELECT p.id, p.slug, p.human_key
                FROM messages m
                JOIN projects p ON m.project_id = p.id
                WHERE m.thread_id = :thread_id
                ORDER BY m.id ASC
                LIMIT 1
            """),
            {"thread_id": thread_id},
        )
        res = row.fetchone()
        if res:
            return (res[0], res[1], res[2])
        return None


__all__ = ["build_http_app", "main"]


def _decode_jwt_header_segment(token: str) -> dict[str, object] | None:
    """Return decoded JWT header without verifying signature."""
    try:
        segment = token.split(".", 1)[0]
        padded = segment + "=" * (-len(segment) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


_LOGGING_CONFIGURED = False


def _configure_logging(settings: Settings) -> None:
    """Initialize structlog and stdlib logging formatting."""
    # Idempotent setup
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
    ]
    if settings.log_json_enabled:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.processors.KeyValueRenderer(key_order=["event", "path", "status"]))
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level.upper(), logging.INFO)),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    # Suppress verbose MCP library logging for stateless HTTP sessions
    # "Terminating session: None" is routine for stateless mode and just noise
    logging.getLogger("mcp.server.streamable_http").setLevel(logging.WARNING)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

    # Suppress verbose aiosqlite DEBUG logs (functools.partial cursor/operation noise)
    logging.getLogger("aiosqlite").setLevel(logging.INFO)

    # Suppress verbose git library DEBUG logs (Popen commands, platform detection)
    logging.getLogger("git.util").setLevel(logging.INFO)
    logging.getLogger("git.cmd").setLevel(logging.INFO)

    # Suppress filelock DEBUG logs (lock acquire/release routine operations)
    logging.getLogger("filelock").setLevel(logging.INFO)

    # Suppress SSE ping keepalive debug logs (periodic noise every 15s)
    logging.getLogger("sse_starlette.sse").setLevel(logging.INFO)

    # mark configured
    _LOGGING_CONFIGURED = True


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, token: str, allow_localhost: bool = False) -> None:
        super().__init__(app)
        self._token = token
        self._allow_localhost = allow_localhost

    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        if request.method == "OPTIONS":  # allow CORS preflight
            return await call_next(request)
        if path.startswith("/health/") or path in {"/slack/events", "/slackbox/incoming"}:
            return await call_next(request)
        # Allow localhost without Authorization when enabled
        try:
            client_host = request.client.host if request.client else ""
        except Exception:
            client_host = ""
        if self._allow_localhost and client_host in {"127.0.0.1", "::1", "localhost"}:
            return await call_next(request)
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {self._token}":
            return JSONResponse({"detail": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)


class SecurityAndRateLimitMiddleware(BaseHTTPMiddleware):
    """JWT auth (optional), RBAC, and token-bucket rate limiting.

    - If JWT is enabled, validates Authorization: Bearer <token> using either HMAC secret or JWKS URL.
    - Enforces basic RBAC when enabled: read-only roles may only call whitelisted tools and resource reads.
    - Applies per-endpoint token-bucket limits (tools vs resources) with in-memory or Redis backend.
    """

    def __init__(self, app: FastAPI, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self._jwt_enabled = bool(getattr(settings.http, "jwt_enabled", False))
        self._rbac_enabled = bool(getattr(settings.http, "rbac_enabled", True))
        self._reader_roles = set(getattr(settings.http, "rbac_reader_roles", []) or [])
        self._writer_roles = set(getattr(settings.http, "rbac_writer_roles", []) or [])
        self._readonly_tools = set(getattr(settings.http, "rbac_readonly_tools", []) or [])
        self._default_role = getattr(settings.http, "rbac_default_role", "tools")
        # Token bucket state (memory)
        from time import monotonic

        self._monotonic = monotonic
        self._buckets: dict[str, tuple[float, float]] = {}
        # Redis client (optional)
        self._redis = None
        if getattr(settings.http, "rate_limit_backend", "memory") == "redis" and getattr(
            settings.http, "rate_limit_redis_url", ""
        ):
            try:
                redis_asyncio = importlib.import_module("redis.asyncio")
                Redis = redis_asyncio.Redis
                self._redis = Redis.from_url(settings.http.rate_limit_redis_url)
            except Exception:
                self._redis = None

    async def _decode_jwt(self, token: str) -> dict | None:
        """Validate and decode JWT, returning claims or None on failure."""
        with contextlib.suppress(Exception):
            jose_mod = importlib.import_module("authlib.jose")
            JsonWebKey = jose_mod.JsonWebKey
            JsonWebToken = jose_mod.JsonWebToken
            algs = list(getattr(self.settings.http, "jwt_algorithms", ["HS256"]))
            jwt = JsonWebToken(algs)
            audience = getattr(self.settings.http, "jwt_audience", None) or None
            issuer = getattr(self.settings.http, "jwt_issuer", None) or None
            jwks_url = getattr(self.settings.http, "jwt_jwks_url", None) or None
            secret = getattr(self.settings.http, "jwt_secret", None) or None

            header = _decode_jwt_header_segment(token)
            if header is None:
                return None
            key = None
            if jwks_url:
                with contextlib.suppress(Exception):
                    httpx = importlib.import_module("httpx")
                    AsyncClient = httpx.AsyncClient
                    async with AsyncClient(timeout=5) as client:
                        jwks = (await client.get(jwks_url)).json()
                    key_set = JsonWebKey.import_key_set(jwks)
                    kid = header.get("kid")
                    key = key_set.find_by_kid(kid) if kid else key_set.keys[0]
            elif secret:
                with contextlib.suppress(Exception):
                    key = JsonWebKey.import_key(secret, {"kty": "oct"})
            if key is None:
                return None
            with contextlib.suppress(Exception):
                claims = jwt.decode(token, key)
                if audience:
                    claims.validate_aud(audience)
                if issuer and str(claims.get("iss") or "") != issuer:
                    return None
                claims.validate()
                return dict(claims)
        return None

    @staticmethod
    def _classify_request(path: str, method: str, body_bytes: bytes) -> tuple[str, str | None]:
        """Return (kind, tool_name) where kind is 'tools'|'resources'|'other'."""
        if method.upper() != "POST":
            return "other", None
        if not body_bytes:
            return "other", None
        with contextlib.suppress(Exception):
            import json as _json

            payload = _json.loads(body_bytes)
            rpc_method = str(payload.get("method", ""))
            if rpc_method == "tools/call":
                params = payload.get("params", {}) or {}
                tool_name = params.get("name")
                return "tools", tool_name if isinstance(tool_name, str) else None
            if rpc_method == "resources/read":
                return "resources", None
            return "other", None
        return "other", None

    def _rate_limits_for(self, kind: str) -> tuple[int, int]:
        # return (per_minute, burst)
        if kind == "tools":
            rpm = int(getattr(self.settings.http, "rate_limit_tools_per_minute", 60) or 60)
            burst = int(getattr(self.settings.http, "rate_limit_tools_burst", 0) or 0)
        elif kind == "resources":
            rpm = int(getattr(self.settings.http, "rate_limit_resources_per_minute", 120) or 120)
            burst = int(getattr(self.settings.http, "rate_limit_resources_burst", 0) or 0)
        else:
            rpm = int(getattr(self.settings.http, "rate_limit_per_minute", 60) or 60)
            burst = 0
        burst = int(burst) if burst > 0 else max(1, rpm)
        return rpm, burst

    async def _consume_bucket(self, key: str, per_minute: int, burst: int) -> bool:
        """Return True if token granted, False if limited."""
        if per_minute <= 0:
            return True
        rate_per_sec = per_minute / 60.0
        now = self._monotonic()

        # Redis backend
        if self._redis is not None:
            try:
                lua = (
                    "local key = KEYS[1]\n"
                    "local now = tonumber(ARGV[1])\n"
                    "local rate = tonumber(ARGV[2])\n"
                    "local burst = tonumber(ARGV[3])\n"
                    "local state = redis.call('HMGET', key, 'tokens', 'ts')\n"
                    "local tokens = tonumber(state[1]) or burst\n"
                    "local ts = tonumber(state[2]) or now\n"
                    "local delta = now - ts\n"
                    "tokens = math.min(burst, tokens + delta * rate)\n"
                    "local allowed = 0\n"
                    "if tokens >= 1 then tokens = tokens - 1 allowed = 1 end\n"
                    "redis.call('HMSET', key, 'tokens', tokens, 'ts', now)\n"
                    "redis.call('EXPIRE', key, math.ceil(burst / math.max(rate, 0.001)))\n"
                    "return allowed\n"
                )
                allowed = await self._redis.eval(lua, 1, f"rl:{key}", now, rate_per_sec, burst)
                return bool(int(allowed or 0) == 1)
            except Exception:
                # Fallback to memory on Redis failure
                pass

        # In-memory token bucket
        tokens, ts = self._buckets.get(key, (float(burst), now))
        elapsed = max(0.0, now - ts)
        tokens = min(float(burst), tokens + elapsed * rate_per_sec)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        tokens -= 1.0
        self._buckets[key] = (tokens, now)
        return True

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # Allow CORS preflight and health checks
        path = request.url.path or ""
        if request.method == "OPTIONS" or path.startswith("/health/"):
            return await call_next(request)

        # Apply dedicated rate limiting for Slack webhooks (and bypass auth) before further processing
        if path in {"/slack/events", "/slackbox/incoming"}:
            if path == "/slackbox/incoming":
                slack_rpm = int(getattr(self.settings.http, "rate_limit_slackbox_per_minute", 120) or 120)
                slack_burst = int(getattr(self.settings.http, "rate_limit_slackbox_burst", 0) or 0)
                route_label = "slackbox"
            else:
                slack_rpm = int(getattr(self.settings.http, "rate_limit_slack_per_minute", 120) or 120)
                slack_burst = int(getattr(self.settings.http, "rate_limit_slack_burst", 0) or 0)
                route_label = "slack"

            slack_burst = slack_burst if slack_burst > 0 else max(1, slack_rpm)
            client_ip = request.client.host if request.client else "unknown"
            key = f"{route_label}:{client_ip}"
            allowed = await self._consume_bucket(key, slack_rpm, slack_burst)
            if not allowed:
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
            return await call_next(request)

        # Only read/patch body for POST requests. GET (including SSE) must not receive http.request messages.
        body_bytes = b""
        if request.method.upper() == "POST":
            try:
                body_bytes = await request.body()

                async def _receive() -> dict[str, Any]:
                    return {"type": "http.request", "body": body_bytes, "more_body": False}

                cast(Any, request)._receive = _receive
            except Exception:
                body_bytes = b""

        kind, tool_name = self._classify_request(path, request.method, body_bytes)

        # JWT auth (if enabled)
        if self._jwt_enabled:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse({"detail": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
            token = auth_header.split(" ", 1)[1].strip()
            claims_dict = await self._decode_jwt(token)
            if claims_dict is None:
                return JSONResponse({"detail": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
            claims = cast(dict[str, Any], claims_dict)
            request.state.jwt_claims = claims
            roles_raw = claims.get(self.settings.http.jwt_role_claim, [])
            if isinstance(roles_raw, str):
                roles = {roles_raw}
            elif isinstance(roles_raw, (list, tuple)):
                roles = {str(r) for r in roles_raw}
            else:
                roles = set()
            if not roles:
                roles = {self._default_role}
        else:
            roles = {self._default_role}
            # Elevate localhost to writer when unauthenticated localhost is allowed
            try:
                client_host = request.client.host if request.client else ""
            except Exception:
                client_host = ""
            if bool(getattr(self.settings.http, "allow_localhost_unauthenticated", False)) and client_host in {
                "127.0.0.1",
                "::1",
                "localhost",
            }:
                roles.add("writer")

        # RBAC enforcement (skip for localhost when allowed)
        try:
            client_host = request.client.host if request.client else ""
        except Exception:
            client_host = ""
        is_local_ok = bool(getattr(self.settings.http, "allow_localhost_unauthenticated", False)) and client_host in {
            "127.0.0.1",
            "::1",
            "localhost",
        }
        # When RBAC is enabled but no authentication mechanism is available, return 401
        if self._rbac_enabled and not is_local_ok and kind in {"tools", "resources"}:
            # If JWT is not enabled AND bearer token is not configured, there's no way to authenticate
            bearer_token_configured = bool(getattr(self.settings.http, "bearer_token", None))
            if not self._jwt_enabled and not bearer_token_configured:
                return JSONResponse({"detail": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
        if self._rbac_enabled and not is_local_ok and kind in {"tools", "resources"}:
            is_reader = bool(roles & self._reader_roles)
            is_writer = bool(roles & self._writer_roles) or (not roles)
            if kind == "resources":
                pass  # readers allowed
            elif kind == "tools":
                if not tool_name:
                    # Without name, assume write-required to be safe
                    if not is_writer:
                        return JSONResponse({"detail": "Forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
                else:
                    if tool_name in self._readonly_tools:
                        if not is_reader and not is_writer:
                            return JSONResponse({"detail": "Forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
                    else:
                        if not is_writer:
                            return JSONResponse({"detail": "Forbidden"}, status_code=status.HTTP_403_FORBIDDEN)

        # Rate limiting
        if self.settings.http.rate_limit_enabled:
            rpm, burst = self._rate_limits_for(kind)
            identity = request.client.host if request.client else "ip-unknown"
            # Prefer stable subject from JWT if present
            with contextlib.suppress(Exception):
                maybe_claims = getattr(request.state, "jwt_claims", None)
                if isinstance(maybe_claims, dict):
                    sub = maybe_claims.get("sub")
                if isinstance(sub, str) and sub:
                    identity = f"sub:{sub}"
            endpoint = tool_name or "*"
            key = f"{kind}:{endpoint}:{identity}"
            allowed = await self._consume_bucket(key, rpm, burst)
            if not allowed:
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

        return await call_next(request)


async def readiness_check() -> None:
    await ensure_schema()
    async with get_session() as session:
        await session.execute(text("SELECT 1"))


def build_http_app(settings: Settings, server=None) -> FastAPI:
    # Configure logging once
    _configure_logging(settings)
    if server is None:
        server = build_mcp_server()

    # Build MCP HTTP sub-app with stateless mode for ASGI test transports
    mcp_http_app = server.http_app(path="/", stateless_http=True, json_response=True)

    # Normalize Accept/Content-Type headers on inbound MCP HTTP calls.

    # Background workers lifecycle
    async def _startup() -> None:  # pragma: no cover - service lifecycle
        if not (
            settings.file_reservations_cleanup_enabled
            or settings.ack_ttl_enabled
            or settings.retention_report_enabled
            or settings.quota_enabled
            or settings.tool_metrics_emit_enabled
        ):
            fastapi_app.state._background_tasks = []
            return

        async def _worker_cleanup() -> None:
            while True:
                try:
                    await ensure_schema()
                    async with get_session() as session:
                        rows = await session.execute(text("SELECT DISTINCT project_id FROM file_reservations"))
                        pids = [r[0] for r in rows.fetchall() if r[0] is not None]
                    released_total = 0
                    for pid in pids:
                        with contextlib.suppress(Exception):
                            stale = await _expire_stale_file_reservations(pid)
                            released_total += len(stale)
                    try:
                        rich_console = importlib.import_module("rich.console")
                        rich_panel = importlib.import_module("rich.panel")
                        Console = rich_console.Console
                        Panel = rich_panel.Panel
                        Console().print(
                            Panel.fit(
                                f"projects_scanned={len(pids)} released={released_total}",
                                title="File Reservations Cleanup",
                                border_style="cyan",
                            )
                        )
                    except Exception:
                        pass
                    with contextlib.suppress(Exception):
                        structlog.get_logger("tasks").info(
                            "file_reservations_cleanup",
                            projects_scanned=len(pids),
                            stale_released=released_total,
                        )
                except Exception:
                    pass
                await asyncio.sleep(settings.file_reservations_cleanup_interval_seconds)

        async def _worker_ack_ttl() -> None:
            import datetime as _dt

            while True:
                try:
                    await ensure_schema()
                    async with get_session() as session:
                        result = await session.execute(
                            text(
                                """
                            SELECT m.id, m.project_id, m.created_ts, mr.agent_id
                            FROM messages m
                            JOIN message_recipients mr ON mr.message_id = m.id
                            WHERE m.ack_required = 1 AND mr.ack_ts IS NULL
                            """
                            )
                        )
                        rows = result.fetchall()
                    now = _dt.datetime.now(_dt.timezone.utc)
                    for mid, project_id, created_ts, agent_id in rows:
                        # Normalize to timezone-aware UTC before arithmetic; SQLite may yield naive datetimes
                        ts = created_ts
                        if getattr(ts, "tzinfo", None) is None or ts.tzinfo.utcoffset(ts) is None:
                            ts = ts.replace(tzinfo=_dt.timezone.utc)
                        else:
                            ts = ts.astimezone(_dt.timezone.utc)
                        age = (now - ts).total_seconds()
                        if age >= settings.ack_ttl_seconds:
                            try:
                                rich_console = importlib.import_module("rich.console")
                                rich_panel = importlib.import_module("rich.panel")
                                rich_text = importlib.import_module("rich.text")
                                Console = rich_console.Console
                                Panel = rich_panel.Panel
                                Text = rich_text.Text
                                con = Console()
                                body = Text.assemble(
                                    ("message_id: ", "cyan"),
                                    (str(mid), "white"),
                                    "\n",
                                    ("agent_id: ", "cyan"),
                                    (str(agent_id), "white"),
                                    "\n",
                                    ("project_id: ", "cyan"),
                                    (str(project_id), "white"),
                                    "\n",
                                    ("age_s: ", "cyan"),
                                    (str(int(age)), "white"),
                                    "\n",
                                    ("ttl_s: ", "cyan"),
                                    (str(settings.ack_ttl_seconds), "white"),
                                )
                                con.print(Panel(body, title="ACK Overdue", border_style="red"))
                            except Exception:
                                print(
                                    f"ack-warning message_id={mid} project_id={project_id} agent_id={agent_id} age_s={int(age)} ttl_s={settings.ack_ttl_seconds}"
                                )
                            with contextlib.suppress(Exception):
                                structlog.get_logger("tasks").warning(
                                    "ack_overdue",
                                    message_id=str(mid),
                                    project_id=str(project_id),
                                    agent_id=str(agent_id),
                                    age_s=int(age),
                                    ttl_s=int(settings.ack_ttl_seconds),
                                )
                            if settings.ack_escalation_enabled:
                                mode = (settings.ack_escalation_mode or "log").lower()
                                if mode == "file_reservation":
                                    try:
                                        y_dir = created_ts.strftime("%Y")
                                        m_dir = created_ts.strftime("%m")
                                        # Resolve recipient name
                                        async with get_session() as s_lookup:
                                            name_row = await s_lookup.execute(
                                                text("SELECT name FROM agents WHERE id = :aid"), {"aid": agent_id}
                                            )
                                            name_res = name_row.fetchone()
                                        recipient_name = name_res[0] if name_res and name_res[0] else "*"
                                        pattern = (
                                            f"agents/{recipient_name}/inbox/{y_dir}/{m_dir}/*.md"
                                            if recipient_name != "*"
                                            else f"agents/*/inbox/{y_dir}/{m_dir}/*.md"
                                        )
                                        holder_agent_id = int(agent_id)
                                        if settings.ack_escalation_claim_holder_name:
                                            async with get_session() as s_holder:
                                                hid_row = await s_holder.execute(
                                                    text(
                                                        "SELECT id FROM agents WHERE project_id = :pid AND name = :name"
                                                    ),
                                                    {
                                                        "pid": project_id,
                                                        "name": settings.ack_escalation_claim_holder_name,
                                                    },
                                                )
                                                hid = hid_row.scalar_one_or_none()
                                                if isinstance(hid, int):
                                                    holder_agent_id = hid
                                                else:
                                                    # Auto-create ops holder in DB and write profile.json
                                                    await s_holder.execute(
                                                        text(
                                                            "INSERT INTO agents(project_id, name, program, model, task_description, inception_ts, last_active_ts) VALUES (:pid, :name, :program, :model, :task, :ts, :ts)"
                                                        ),
                                                        {
                                                            "pid": project_id,
                                                            "name": settings.ack_escalation_claim_holder_name,
                                                            "program": "ops",
                                                            "model": "system",
                                                            "task": "ops-escalation",
                                                            "ts": now,
                                                        },
                                                    )
                                                    await s_holder.commit()
                                                    hid_row2 = await s_holder.execute(
                                                        text(
                                                            "SELECT id FROM agents WHERE project_id = :pid AND name = :name"
                                                        ),
                                                        {
                                                            "pid": project_id,
                                                            "name": settings.ack_escalation_claim_holder_name,
                                                        },
                                                    )
                                                    hid2 = hid_row2.scalar_one_or_none()
                                                    if isinstance(hid2, int):
                                                        holder_agent_id = hid2
                                                        # Archive storage has been removed; no profile artifacts are written.
                                        async with get_session() as s2:
                                            await s2.execute(
                                                text(
                                                    """
                                                INSERT INTO file_reservations(project_id, agent_id, path_pattern, exclusive, reason, created_ts, expires_ts)
                                                VALUES (:pid, :holder, :pattern, :exclusive, :reason, :cts, :ets)
                                                """
                                                ),
                                                {
                                                    "pid": project_id,
                                                    "holder": holder_agent_id,
                                                    "pattern": pattern,
                                                    "exclusive": 1 if settings.ack_escalation_claim_exclusive else 0,
                                                    "reason": "ack-overdue",
                                                    "cts": now,
                                                    "ets": now
                                                    + _dt.timedelta(seconds=settings.ack_escalation_claim_ttl_seconds),
                                                },
                                            )
                                            await s2.commit()
                                        # Archive storage has been removed; no file-reservation artifacts are written.
                                    except Exception:
                                        pass
                except Exception:
                    pass
                await asyncio.sleep(settings.ack_ttl_scan_interval_seconds)

        async def _worker_tool_metrics() -> None:
            log = structlog.get_logger("tool.metrics")
            while True:
                try:
                    snapshot = _tool_metrics_snapshot()
                    if snapshot:
                        log.info("tool_metrics_snapshot", tools=snapshot)
                except Exception:
                    pass
                await asyncio.sleep(max(5, settings.tool_metrics_emit_interval_seconds))

        async def _worker_retention_quota() -> None:
            import datetime as _dt
            from pathlib import Path as _Path

            while True:
                from contextlib import suppress as _suppress

                with _suppress(Exception):
                    storage_root = _Path(settings.storage.root).expanduser().resolve()
                    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(
                        days=int(settings.retention_max_age_days)
                    )
                    old_messages = 0
                    total_attach_bytes = 0
                    per_project_attach: dict[str, int] = {}
                    per_project_inbox_counts: dict[str, int] = {}
                    # Compile ignore patterns once per loop
                    import fnmatch as _fnmatch

                    ignore_patterns = list(getattr(settings, "retention_ignore_project_patterns", []) or [])
                    for proj_dir in storage_root.iterdir() if storage_root.exists() else []:
                        if not proj_dir.is_dir():
                            continue
                        proj_name = proj_dir.name
                        # Skip test/demo projects in real server runs
                        if any(_fnmatch.fnmatch(proj_name, pat) for pat in ignore_patterns):
                            continue
                        msg_root = proj_dir / "messages"
                        if msg_root.exists():
                            for ydir in msg_root.iterdir():
                                for mdir in ydir.iterdir() if ydir.is_dir() else []:
                                    for f in mdir.iterdir() if mdir.is_dir() else []:
                                        if f.suffix.lower() == ".md":
                                            with _suppress(Exception):
                                                ts = _dt.datetime.fromtimestamp(f.stat().st_mtime, _dt.timezone.utc)
                                                if ts < cutoff:
                                                    old_messages += 1
                        # Count per-agent inbox files (agents/*/inbox/YYYY/MM/*.md)
                        inbox_root = proj_dir / "agents"
                        if inbox_root.exists():
                            count_inbox = 0
                            for f in inbox_root.rglob("inbox/*/*/*.md"):
                                with _suppress(Exception):
                                    if f.is_file():
                                        count_inbox += 1
                            per_project_inbox_counts[proj_name] = count_inbox
                        att_root = proj_dir / "attachments"
                        if att_root.exists():
                            for sub in att_root.rglob("*.webp"):
                                with _suppress(Exception):
                                    sz = sub.stat().st_size
                                    total_attach_bytes += sz
                                    per_project_attach[proj_name] = per_project_attach.get(proj_name, 0) + sz
                    structlog.get_logger("maintenance").info(
                        "retention_quota_report",
                        old_messages=old_messages,
                        retention_max_age_days=int(settings.retention_max_age_days),
                        total_attachments_bytes=total_attach_bytes,
                        quota_limit_bytes=int(settings.quota_attachments_limit_bytes),
                        per_project_attach=per_project_attach,
                        per_project_inbox_counts=per_project_inbox_counts,
                    )
                    # Quota alerts
                    limit_b = int(settings.quota_attachments_limit_bytes)
                    inbox_limit = int(settings.quota_inbox_limit_count)
                    if limit_b > 0:
                        for proj, used in per_project_attach.items():
                            if used >= limit_b:
                                structlog.get_logger("maintenance").warning(
                                    "quota_attachments_exceeded", project=proj, used_bytes=used, limit_bytes=limit_b
                                )
                    if inbox_limit > 0:
                        for proj, cnt in per_project_inbox_counts.items():
                            if cnt >= inbox_limit:
                                structlog.get_logger("maintenance").warning(
                                    "quota_inbox_exceeded", project=proj, inbox_count=cnt, limit=inbox_limit
                                )
                await asyncio.sleep(max(60, settings.retention_report_interval_seconds))

        tasks = []
        if settings.file_reservations_cleanup_enabled:
            tasks.append(asyncio.create_task(_worker_cleanup()))
        if settings.ack_ttl_enabled:
            tasks.append(asyncio.create_task(_worker_ack_ttl()))
        if settings.tool_metrics_emit_enabled:
            tasks.append(asyncio.create_task(_worker_tool_metrics()))
        if settings.retention_report_enabled or settings.quota_enabled:
            tasks.append(asyncio.create_task(_worker_retention_quota()))
        fastapi_app.state._background_tasks = tasks

    async def _shutdown() -> None:  # pragma: no cover - service lifecycle
        tasks = getattr(fastapi_app.state, "_background_tasks", [])
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await task

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_context(app: FastAPI):
        # Ensure the mounted MCP app initializes its internal task group
        async with mcp_http_app.lifespan(mcp_http_app):
            await _startup()
            try:
                yield
            finally:
                await _shutdown()

    # Now construct FastAPI with the composed lifespan so ASGI transports run it
    fastapi_app = FastAPI(lifespan=lifespan_context)

    # Simple request logging (configurable)
    if settings.http.request_log_enabled:
        import time as _time

        class RequestLoggingMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
                start = _time.time()
                response = await call_next(request)
                dur_ms = int((_time.time() - start) * 1000)
                method = request.method
                path = request.url.path
                status_code = getattr(response, "status_code", 0)
                client = request.client.host if request.client else "-"
                with contextlib.suppress(Exception):
                    structlog.get_logger("http").info(
                        "request",
                        method=method,
                        path=path,
                        status=status_code,
                        duration_ms=dur_ms,
                        client_ip=client,
                    )
                try:
                    rich_console = importlib.import_module("rich.console")
                    rich_panel = importlib.import_module("rich.panel")
                    rich_text = importlib.import_module("rich.text")
                    Console = rich_console.Console
                    Panel = rich_panel.Panel
                    Text = rich_text.Text
                    console = Console(width=100)
                    title = Text.assemble(
                        (method, "bold blue"),
                        ("  "),
                        (path, "bold white"),
                        ("  "),
                        (f"{status_code}", "bold green" if 200 <= status_code < 400 else "bold red"),
                        ("  "),
                        (f"{dur_ms}ms", "bold yellow"),
                    )
                    body = Text.assemble(
                        ("client: ", "cyan"),
                        (client, "white"),
                    )
                    console.print(Panel(body, title=title, border_style="dim"))
                except Exception:
                    print(f"http method={method} path={path} status={status_code} ms={dur_ms} client={client}")
                return response

        fastapi_app.add_middleware(RequestLoggingMiddleware)  # type: ignore[arg-type]

    # Unified JWT/RBAC and robust rate limiter middleware
    if (
        settings.http.rate_limit_enabled
        or getattr(settings.http, "jwt_enabled", False)
        or getattr(settings.http, "rbac_enabled", True)
    ):
        fastapi_app.add_middleware(SecurityAndRateLimitMiddleware, settings=settings)  # type: ignore[arg-type]
    # Bearer auth for non-localhost only; allow localhost unauth optionally for seamless local dev
    if settings.http.bearer_token:
        fastapi_app.add_middleware(
            BearerAuthMiddleware,  # type: ignore[arg-type]
            token=settings.http.bearer_token,
            allow_localhost=bool(getattr(settings.http, "allow_localhost_unauthenticated", False)),
        )

    # Optional CORS
    if settings.cors.enabled:
        fastapi_app.add_middleware(
            CORSMiddleware,  # type: ignore[arg-type]
            allow_origins=settings.cors.origins or ["*"],
            allow_credentials=settings.cors.allow_credentials,
            allow_methods=settings.cors.allow_methods or ["*"],
            allow_headers=settings.cors.allow_headers or ["*"],
        )

    # Health endpoints
    @fastapi_app.get("/health/liveness")
    async def liveness() -> JSONResponse:
        return JSONResponse({"status": "alive"})

    @fastapi_app.get("/health/readiness")
    async def readiness() -> JSONResponse:
        try:
            await readiness_check()
        except Exception as exc:
            try:
                rich_console = importlib.import_module("rich.console")
                rich_panel = importlib.import_module("rich.panel")
                Console = rich_console.Console
                Panel = rich_panel.Panel
                Console().print(Panel.fit(str(exc), title="Readiness Error", border_style="red"))
            except Exception:
                pass
            with contextlib.suppress(Exception):
                structlog.get_logger("health").error("readiness_error", error=str(exc))
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return JSONResponse({"status": "ready"})

    # Well-known OAuth metadata endpoints (some clients probe these); return harmless JSON
    @fastapi_app.get("/.well-known/oauth-authorization-server")
    async def oauth_meta_root() -> JSONResponse:
        return JSONResponse({"mcp_oauth": False})

    @fastapi_app.get("/.well-known/oauth-authorization-server/mcp")
    async def oauth_meta_root_mcp() -> JSONResponse:
        return JSONResponse({"mcp_oauth": False})

    async def _ingest_slack_bridge_message(
        message_info: dict[str, Any],
        *,
        logger: structlog.stdlib.BoundLogger,
        dedupe_key: tuple[str, str] | None = None,
        source: str = "slack",
    ) -> JSONResponse:
        """Shared ingestion path for Slack-derived payloads."""
        from .models import Agent

        slack_ts = message_info.get("slack_ts")
        slack_channel = message_info.get("slack_channel")
        cache_key = dedupe_key or ((slack_channel, slack_ts) if slack_ts and slack_channel else None)
        cache_key_added = False

        if cache_key:
            async with _slack_event_cache_lock:
                if cache_key in _slack_event_cache:
                    logger.info(
                        "slack_message_duplicate_skipped",
                        slack_ts=slack_ts,
                        channel=slack_channel,
                        source=source,
                    )
                    return JSONResponse({"ok": True, "message": "Duplicate Slack event skipped"})

                # Evict oldest entries if at capacity (before adding new one)
                while len(_slack_event_cache_order) >= _SLACK_EVENT_CACHE_MAX_SIZE:
                    old = _slack_event_cache_order.popleft()
                    _slack_event_cache.discard(old)

                _slack_event_cache.add(cache_key)
                _slack_event_cache_order.append(cache_key)
                cache_key_added = True

        try:
            # Determine project: Look up the original project for this thread so Slack replies
            # go to the same project as the original message. Supports both numeric message IDs
            # and string thread_ids (e.g., "bd-123", "slack_<channel>_<ts>").
            thread_id = message_info.get("thread_id")
            project = None

            if thread_id:
                async with get_session() as session:
                    if thread_id.isdigit():
                        # thread_id is a numeric MCP message ID - look up by message.id
                        result = await session.execute(
                            text(
                                "SELECT p.id, p.slug, p.human_key FROM messages m JOIN projects p ON p.id = m.project_id WHERE m.id = :mid"
                            ),
                            {"mid": int(thread_id)},
                        )
                    else:
                        # thread_id is a string - look up by messages.thread_id
                        # This handles non-numeric thread_ids like "bd-123", "slack_C123_456.789"
                        result = await session.execute(
                            text("""
                                SELECT p.id, p.slug, p.human_key
                                FROM messages m
                                JOIN projects p ON p.id = m.project_id
                                WHERE m.thread_id = :tid
                                ORDER BY m.id ASC
                                LIMIT 1
                            """),
                            {"tid": thread_id},
                        )
                    row = result.fetchone()
                    if row:
                        from .models import Project

                        project = Project(id=row[0], slug=row[1], human_key=row[2])
                        logger.info(
                            "slack_reply_routed_to_original_project",
                            thread_id=thread_id,
                            project_slug=project.slug,
                            source=source,
                        )

            if not project:
                # Fall back to sync_project_name for new Slack-originated threads
                project = await _ensure_project(settings.slack.sync_project_name)

            sender_name = message_info["sender_name"]
            # Agent names are globally unique. Treat Slack-derived senders as a shared/global
            # identity: reuse the same agent across projects to avoid cross-project mutation.
            sender_agent = await _get_agent_by_name_optional(sender_name)
            if sender_agent:
                logger.debug(
                    "slack_bridge_agent_reused",
                    agent_name=sender_name,
                    agent_project_id=sender_agent.project_id,
                    target_project_id=project.id,
                )

            if not sender_agent:
                if source in {"slack", "slack_events"}:
                    program = "slack_bridge"
                    model = "slack-events"
                else:
                    program = "slack_ingestion"
                    model = "slack-webhook"
                async with get_session() as session:
                    sender_agent = Agent(
                        name=sender_name,
                        project_id=project.id,
                        program=program,
                        model=model,
                        task_description="Bridges Slack messages into MCP Agent Mail",
                        is_active=True,
                    )
                    session.add(sender_agent)
                    try:
                        await session.commit()
                        await session.refresh(sender_agent)
                        logger.info("slack_bridge_agent_created", agent_name=sender_name)
                    except IntegrityError:
                        await session.rollback()
                        # Race: another request created this globally-unique agent first.
                        sender_agent = await _get_agent_by_name_optional(sender_name)
                        if not sender_agent:
                            raise

            async with get_session() as session:
                result = await session.execute(
                    select(Agent).where(
                        cast(Any, Agent.project_id) == project.id,
                        cast(Any, Agent.is_active).is_(True),
                        cast(Any, Agent.id) != sender_agent.id,
                    )
                )
                recipient_agents = list(result.scalars().all())

            if not recipient_agents:
                logger.warning("slack_no_recipients", project=project.slug, source=source)
                return JSONResponse({"ok": True, "message": "No active recipients"})

            recipients_list = [(agent, "to") for agent in recipient_agents]
            message = await _create_message(
                project=project,
                sender=sender_agent,
                subject=message_info["subject"],
                body_md=message_info["body_md"],
                recipients=recipients_list,
                importance="normal",
                ack_required=False,
                thread_id=message_info.get("thread_id"),
                attachments=[],
            )

            to_agents = [r[0] for r in recipients_list if r[1] == "to"]
            cc_agents = [r[0] for r in recipients_list if r[1] == "cc"]
            bcc_agents = [r[0] for r in recipients_list if r[1] == "bcc"]
            frontmatter = _message_frontmatter(
                message=message,
                project=project,
                sender=sender_agent,
                to_agents=to_agents,
                cc_agents=cc_agents,
                bcc_agents=bcc_agents,
                attachments=[],
            )

            async def _persist_archive() -> None:
                if not is_archive_enabled(settings):
                    logger.debug(
                        "slack_archive_write_skipped",
                        reason="archive_disabled",
                        source=source,
                    )
                    return
                try:
                    archive = await ensure_archive(settings, project.slug)
                    await write_message_bundle(
                        archive=archive,
                        message=frontmatter,
                        body_md=message.body_md,
                        sender=sender_agent.name,
                        recipients=[agent.name for agent in recipient_agents],
                        extra_paths=[],
                    )
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("slack_archive_write_failed", error=str(exc), source=source)

            _archive_task = asyncio.create_task(_persist_archive())
            _ = _archive_task

            slack_client_ref = None
            try:
                from .app import _slack_client as _global_slack_client

                slack_client_ref = _global_slack_client
            except Exception:
                slack_client_ref = None

            slack_thread_ts = message_info.get("slack_thread_ts") or message_info.get("slack_ts")
            slack_channel_id = message_info.get("slack_channel")
            if slack_client_ref and message_info.get("thread_id") and slack_thread_ts and slack_channel_id:
                try:
                    await slack_client_ref.map_thread(
                        mcp_thread_id=message_info["thread_id"],
                        slack_channel_id=slack_channel_id,
                        slack_thread_ts=slack_thread_ts,
                    )
                except Exception as exc:
                    logger.warning("slack_thread_map_failed", error=str(exc), source=source)

            logger.info(
                "slack_message_ingested",
                message_id=message.id,
                thread_id=message.thread_id,
                slack_ts=slack_ts,
                source=source,
            )

            return JSONResponse({"ok": True, "message": "Message created"})
        except Exception:
            if cache_key and cache_key_added:
                async with _slack_event_cache_lock:
                    _slack_event_cache.discard(cache_key)
                    with contextlib.suppress(ValueError):
                        _slack_event_cache_order.remove(cache_key)
            raise

    # Slack Events API webhook endpoint for bidirectional sync
    @fastapi_app.post("/slack/events")
    async def slack_events_webhook(request: Request) -> JSONResponse:
        """Handle incoming Slack events for bidirectional sync.

        Implements:
        - URL verification challenge (for Slack app setup)
        - Signature verification (security)
        - Message event processing (Slack → MCP Mail sync)
        - Reaction handling (optional acknowledgment sync)

        Reference: https://api.slack.com/apis/connections/events-api
        """
        logger = structlog.get_logger("slack")

        if not settings.slack.enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Slack integration disabled")

        # Read raw body for signature verification
        body_bytes = await request.body()

        if not settings.slack.signing_secret:
            logger.error("slack_signing_secret_missing")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Slack signing secret not configured",
            )

        from .slack_integration import SlackClient

        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")

        if not SlackClient.verify_signature(
            signing_secret=settings.slack.signing_secret,
            timestamp=timestamp,
            signature=signature,
            body=body_bytes,
        ):
            logger.warning("slack_signature_verification_failed")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

        # Parse JSON payload
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("slack_payload_decode_error", error=str(e))
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from e

        event_type = payload.get("type")
        logger.info("slack_event_received", event_type=event_type)

        # Handle URL verification challenge (required for Slack app setup)
        if event_type == "url_verification":
            challenge = payload.get("challenge", "")
            logger.info("slack_url_verification", challenge=challenge[:20])
            return JSONResponse({"challenge": challenge})

        # Handle event callback
        if event_type == "event_callback":
            event = payload.get("event", {})
            event_subtype = event.get("type")
            logger.info("slack_event_callback", subtype=event_subtype)

            # Handle message events
            if event_subtype == "message":
                from .slack_integration import handle_slack_message_event

                message_info = await handle_slack_message_event(event, settings)

                if message_info:
                    slack_ts = message_info.get("slack_ts")
                    slack_channel = message_info.get("slack_channel")
                    cache_key = (slack_channel, slack_ts) if slack_ts and slack_channel else None

                    # Check for duplicate events before processing
                    cache_key_added = False
                    if cache_key:
                        async with _slack_event_cache_lock:
                            if cache_key in _slack_event_cache:
                                logger.info(
                                    "slack_message_duplicate_skipped",
                                    slack_ts=slack_ts,
                                    channel=slack_channel,
                                )
                                return JSONResponse({"ok": True, "message": "Duplicate Slack event skipped"})

                            # Add to cache before processing to prevent concurrent duplicates
                            while len(_slack_event_cache_order) >= _SLACK_EVENT_CACHE_MAX_SIZE:
                                old = _slack_event_cache_order.popleft()
                                _slack_event_cache.discard(old)
                            _slack_event_cache.add(cache_key)
                            _slack_event_cache_order.append(cache_key)
                            cache_key_added = True

                    # Create MCP message from Slack event
                    try:
                        # Determine project: use original thread's project for replies,
                        # fall back to slack-sync or default project for new messages
                        thread_id = message_info.get("thread_id")
                        project = None
                        if thread_id:
                            thread_project = await _project_from_thread_id(thread_id)
                            if thread_project:
                                # Use original message's project for thread replies
                                _project_id, slug, human_key = thread_project
                                project = await _ensure_project(human_key)
                                logger.info(
                                    "slack_reply_using_thread_project",
                                    thread_id=thread_id,
                                    project_slug=slug,
                                )
                        if not project:
                            # New message or thread not found - use slack-sync or default
                            if settings.slack.sync_project_name:
                                project = await _ensure_project(settings.slack.sync_project_name)
                            else:
                                project = await _get_default_project()

                        # Get or create SlackBridge agent
                        sender_name = message_info["sender_name"]
                        sender_agent = await _get_agent_by_name_optional(sender_name)

                        if not sender_agent:
                            # Auto-create SlackBridge system agent; tolerate concurrent creation
                            async with get_session() as session:
                                sender_agent = Agent(
                                    name=sender_name,
                                    project_id=project.id if project else None,
                                    program="slack_bridge",
                                    model="slack-events",
                                    task_description="Bridges Slack messages into MCP Agent Mail",
                                    is_active=True,
                                )
                                session.add(sender_agent)
                                try:
                                    await session.commit()
                                    await session.refresh(sender_agent)
                                    logger.info("slack_bridge_agent_created", agent_name=sender_name)
                                except IntegrityError:
                                    await session.rollback()
                                    # Agent names are globally unique; look up without project filter
                                    # Must filter by is_active since unique index only covers active agents
                                    result = await session.execute(
                                        select(Agent).where(
                                            func.lower(Agent.name) == func.lower(sender_name),
                                            cast(Any, Agent.is_active).is_(True),
                                        )
                                    )
                                    existing_agent = result.scalars().first()
                                    if not existing_agent:
                                        raise
                                    sender_agent = existing_agent

                        # Broadcast to all active agents globally (agent names are globally unique)
                        # We intentionally avoid project scoping so Slack messages always reach active agents,
                        # even when thread context has no project or the project was deleted.
                        async with get_session() as session:
                            result = await session.execute(
                                select(Agent).where(
                                    cast(Any, Agent.is_active).is_(True),
                                    cast(Any, Agent.id) != sender_agent.id,
                                )
                            )
                            recipient_agents = list(result.scalars().all())

                        if not recipient_agents:
                            logger.warning(
                                "slack_no_recipients", project=(project.slug if project else DEFAULT_PROJECT_KEY)
                            )
                            return JSONResponse({"ok": True, "message": "No active recipients"})

                        # Create message
                        recipients_list = [(agent, "to") for agent in recipient_agents]
                        message = await _create_message(
                            project=project,
                            sender=sender_agent,
                            subject=message_info["subject"],
                            body_md=message_info["body_md"],
                            recipients=recipients_list,
                            importance="normal",
                            ack_required=False,
                            thread_id=message_info.get("thread_id"),
                            attachments=[],
                        )

                        # Write message to archive in background to avoid webhook timeout
                        to_agents = [r[0] for r in recipients_list if r[1] == "to"]
                        cc_agents = [r[0] for r in recipients_list if r[1] == "cc"]
                        bcc_agents = [r[0] for r in recipients_list if r[1] == "bcc"]
                        frontmatter = _message_frontmatter(
                            message=message,
                            project=project,
                            sender=sender_agent,
                            to_agents=to_agents,
                            cc_agents=cc_agents,
                            bcc_agents=bcc_agents,
                            attachments=[],
                        )

                        async def _persist_archive() -> None:
                            try:
                                archive_project = project or await _get_default_project()
                                archive = await ensure_archive(settings, archive_project.slug)
                                await write_message_bundle(
                                    archive=archive,
                                    message=frontmatter,
                                    body_md=message.body_md,
                                    sender=sender_agent.name,
                                    recipients=[agent.name for agent in recipient_agents],
                                    extra_paths=[],
                                )
                            except Exception as exc:
                                logger.error("slack_archive_write_failed", error=str(exc))

                        _archive_task = asyncio.create_task(_persist_archive())
                        _ = _archive_task

                        # Capture thread mapping so outbound replies stay in the same Slack thread
                        slack_client_ref = None
                        try:
                            from .app import _slack_client as _global_slack_client  # lazy import to avoid cycles

                            slack_client_ref = _global_slack_client
                        except Exception:
                            slack_client_ref = None

                        if (
                            slack_client_ref
                            and message_info.get("thread_id")
                            and message_info.get("slack_thread_ts")
                            and message_info.get("slack_channel")
                        ):
                            try:
                                await slack_client_ref.map_thread(
                                    mcp_thread_id=message_info["thread_id"],
                                    slack_channel_id=message_info["slack_channel"],
                                    slack_thread_ts=message_info["slack_thread_ts"],
                                )
                            except Exception as exc:  # best-effort; do not block ingestion
                                logger.warning("slack_thread_map_failed", error=str(exc))

                        logger.info(
                            "slack_message_created",
                            message_id=message.id,
                            subject=message.subject[:50],
                            recipients=len(recipient_agents),
                        )

                        return JSONResponse({"ok": True, "message_id": str(message.id)})

                    except Exception as e:
                        # Clean up cache on failure to allow Slack retries
                        if cache_key and cache_key_added:
                            async with _slack_event_cache_lock:
                                _slack_event_cache.discard(cache_key)
                                with contextlib.suppress(ValueError):
                                    _slack_event_cache_order.remove(cache_key)
                        logger.error("slack_message_creation_failed", error=str(e))
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create message: {e}"
                        ) from e
                else:
                    # Message was filtered/ignored (e.g., bot message, wrong channel)
                    return JSONResponse({"ok": True, "message": "Event ignored"})

            # Handle reaction_added events (future: map to acknowledgments)
            elif event_subtype == "reaction_added":
                logger.info("slack_reaction_received", reaction=event.get("reaction"))
                # TODO: Implement reaction → acknowledgment mapping
                return JSONResponse({"ok": True, "message": "Reaction handling not yet implemented"})

        # Return success for unhandled event types
        return JSONResponse({"ok": True})

    @fastapi_app.post("/slackbox/incoming")
    async def slackbox_incoming(request: Request) -> JSONResponse:
        """Handle legacy Slack outgoing webhook payloads (Slackbox)."""

        logger = structlog.get_logger("slackbox")

        if not settings.slack.slackbox_enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Slackbox disabled")

        if not settings.slack.slackbox_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Slackbox token not configured",
            )

        form = await request.form()

        token_raw = form.get("token")
        token = token_raw.strip() if isinstance(token_raw, str) else ""
        if not hmac.compare_digest(token, settings.slack.slackbox_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slackbox token")

        text_raw = form.get("text")
        text = text_raw.strip() if isinstance(text_raw, str) else ""
        if not text:
            return JSONResponse({"ok": True, "message": "No text provided"})

        channel_raw = form.get("channel_id") or form.get("channel_name")
        channel_id = channel_raw.strip() if isinstance(channel_raw, str) else ""
        if settings.slack.slackbox_channels and channel_id not in settings.slack.slackbox_channels:
            logger.info("slackbox_channel_skipped", channel=channel_id)
            return JSONResponse({"ok": True, "message": "Channel not allowed"})

        timestamp_raw = form.get("timestamp") or form.get("ts")
        timestamp = timestamp_raw.strip() if isinstance(timestamp_raw, str) else ""
        dedupe_key = (channel_id, timestamp) if channel_id and timestamp else None

        subject_line = text.split("\n", 1)[0].strip() or "Slackbox message"
        subject_prefixed = f"{settings.slack.slackbox_subject_prefix} {subject_line}".strip()
        subject = subject_prefixed[:120]

        thread_id = f"slackbox_{channel_id}_{timestamp}" if channel_id and timestamp else None

        message_info = {
            "sender_name": settings.slack.slackbox_sender_name,
            "subject": subject,
            "body_md": text,
            "thread_id": thread_id,
            "slack_channel": channel_id,
            "slack_ts": timestamp,
            "slack_thread_ts": timestamp,
        }

        return await _ingest_slack_bridge_message(
            message_info,
            logger=logger,
            dedupe_key=dedupe_key,
            source="slackbox",
        )

    # A minimal stateless ASGI adapter that does not rely on ASGI lifespan management
    # and runs a fresh StreamableHTTP transport per request.
    class MCPHeaderNormalizeASGIApp:
        def __init__(self, app) -> None:
            self._app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope.get("type") != "http":
                res = JSONResponse({"detail": "Not Found"}, status_code=404)
                await res(scope, receive, send)
                return

            # Ensure Accept and Content-Type headers are present per StreamableHTTP expectations
            headers = list(scope.get("headers") or [])

            def _has_header(key: bytes) -> bool:
                lk = key.lower()
                return any(h[0].lower() == lk for h in headers)

            # Ensure both JSON and SSE are present; httpx defaults no Accept header
            headers = [(k, v) for (k, v) in headers if k.lower() != b"accept"]
            headers.append((b"accept", b"application/json, text/event-stream"))
            if scope.get("method") == "POST" and not _has_header(b"content-type"):
                headers.append((b"content-type", b"application/json"))
            new_scope = dict(scope)
            new_scope["headers"] = headers

            # Ensure path is not empty (fix for mount point root handling)
            if not new_scope.get("path"):
                new_scope["path"] = "/"

            await self._app(new_scope, receive, send)

    # Mount at both '/base' and '/base/' to tolerate either form from clients/tests
    mount_base = settings.http.path or "/mcp"
    if not mount_base.startswith("/"):
        mount_base = "/" + mount_base
    base_no_slash = mount_base.rstrip("/") or "/"
    base_with_slash = base_no_slash if base_no_slash == "/" else base_no_slash + "/"
    stateless_app = MCPHeaderNormalizeASGIApp(mcp_http_app)

    # Add a direct route at the base path to handle POST /mcp without redirect (307)
    # and support streaming (by using ASGI app directly instead of buffering).
    class RootPathForceASGIApp:
        """ASGI adapter that rewrites requests to the root path ("/").

        Used to handle POST requests at the mount base path (e.g., /mcp) without
        FastAPI's automatic redirect (307) to the trailing-slash variant. This
        enables streaming responses at the exact base path by rewriting the
        incoming scope path to "/".
        """

        def __init__(self, app) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            new_scope = dict(scope)
            new_scope["path"] = "/"
            await self.app(new_scope, receive, send)

    if base_no_slash == "/":
        # CRITICAL WARNING: HTTP_PATH='/' will shadow ALL other routes including /mail UI
        # This is a fundamental limitation of ASGI/FastAPI routing - mount() at "/" captures everything
        # RECOMMENDED: Use HTTP_PATH='/mcp' instead
        structlog.get_logger(__name__).warning(
            "HTTP_PATH='/' will shadow all routes including /mail UI. "
            "The /mail interface will NOT be accessible when HTTP_PATH='/'. "
            "STRONGLY RECOMMENDED: Use HTTP_PATH='/mcp' instead."
        )
        # Mount at root - this WILL shadow /mail and other routes, but supports MCP streaming correctly
        with contextlib.suppress(Exception):
            fastapi_app.mount("/", stateless_app, name="mcp_root")
    else:
        # Fix ASGI handler signature mismatch: Use mount() instead of add_route()
        # for the no-slash path to properly handle ASGI app signature
        with contextlib.suppress(Exception):
            fastapi_app.mount(base_no_slash, RootPathForceASGIApp(stateless_app), name="mcp_no_slash")
        with contextlib.suppress(Exception):
            fastapi_app.mount(base_with_slash, stateless_app, name="mcp_with_slash")

    # Expose composed lifespan via router
    fastapi_app.router.lifespan_context = lifespan_context

    # ----- Simple SSR Mail UI -----
    def _register_mail_ui() -> None:
        import bleach  # type: ignore
        import markdown2  # type: ignore

        try:
            from bleach.css_sanitizer import CSSSanitizer  # type: ignore
        except Exception:  # tinycss2 may be missing; degrade gracefully
            CSSSanitizer = None  # type: ignore
        from jinja2 import Environment, FileSystemLoader, select_autoescape  # type: ignore

        templates_root = Path(__file__).resolve().parent / "templates"
        env = Environment(
            loader=FileSystemLoader(str(templates_root)),
            autoescape=select_autoescape(["html", "xml"]),
            enable_async=True,
        )
        # HTML sanitizer (allow safe images and limited CSS)
        _css_sanitizer = (
            CSSSanitizer(
                allowed_css_properties=["color", "background-color", "text-align", "text-decoration", "font-weight"]
            )
            if CSSSanitizer
            else None
        )
        _html_cleaner = bleach.Cleaner(
            tags=[
                "a",
                "abbr",
                "acronym",
                "b",
                "blockquote",
                "code",
                "em",
                "i",
                "li",
                "ol",
                "ul",
                "p",
                "pre",
                "strong",
                "table",
                "thead",
                "tbody",
                "tr",
                "th",
                "td",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "hr",
                "br",
                "span",
                "img",
            ],
            attributes={
                "*": ["class"],
                "a": ["href", "title", "rel"],
                "abbr": ["title"],
                "acronym": ["title"],
                "code": ["class"],
                "pre": ["class"],
                "span": ["class", "style"],
                "p": ["class", "style"],
                "table": ["class", "style"],
                "td": ["class", "style"],
                "th": ["class", "style"],
                "img": ["src", "alt", "title", "width", "height", "loading", "decoding", "class"],
            },
            protocols=["http", "https", "mailto", "data"],
            strip=True,
            css_sanitizer=_css_sanitizer,
        )

        async def _render(name: str, **ctx) -> HTMLResponse:
            tpl = env.get_template(name)
            html = await tpl.render_async(**ctx)
            return HTMLResponse(html)

        def _parse_fts_query(
            raw: str, scope_preference: str | None = None
        ) -> tuple[str, str, str, list[dict[str, str]]]:
            """Return (fts_expression, like_pattern) from a user query.
            Supports subject:foo and body:"multi word" tokens; otherwise defaults to subject/body OR.
            """
            raw = (raw or "").strip()
            if not raw:
                return "", "", "both", []
            scope_pref = scope_preference if scope_preference in {"subject", "body"} else "both"
            # tokens: key:"phrase" | "phrase" | key:word | word
            parts = re.findall(r"\w+:\"[^\"]+\"|\"[^\"]+\"|\w+:[^\s]+|[^\s]+", raw)
            exprs: list[str] = []
            like_terms: list[str] = []
            like_scope = scope_pref
            tokens: list[dict[str, str]] = []

            def _quote(s: str) -> str:
                return '"' + s.replace('"', '""') + '"'

            for p in parts:
                key = None
                val = p
                if ":" in p and not p.startswith('"'):
                    key, val = p.split(":", 1)
                val = val.strip()
                val_inner = val[1:-1] if val.startswith('"') and val.endswith('"') and len(val) >= 2 else val
                like_terms.append(val_inner)
                if key in {"subject", "body"}:
                    exprs.append(f"{key}:{_quote(val_inner)}")
                    tokens.append({"field": key, "value": val_inner})
                else:
                    if scope_pref == "subject":
                        exprs.append(f"subject:{_quote(val_inner)}")
                        tokens.append({"field": "subject", "value": val_inner})
                    elif scope_pref == "body":
                        exprs.append(f"body:{_quote(val_inner)}")
                        tokens.append({"field": "body", "value": val_inner})
                    else:
                        exprs.append(f"(subject:{_quote(val_inner)} OR body:{_quote(val_inner)})")
                        tokens.append({"field": "both", "value": val_inner})
            fts = " AND ".join(exprs) if exprs else ""
            like_pat = "%" + "%".join(like_terms) + "%" if like_terms else ""
            return fts, like_pat, like_scope, tokens

        @fastapi_app.get("/mail/api/locks", response_class=JSONResponse)
        async def mail_lock_status() -> JSONResponse:
            """Return metadata about active archive locks for observability."""

            settings_local = get_settings()
            payload = collect_lock_status(settings_local)
            return JSONResponse(payload)

        async def _build_unified_inbox_payload(*, limit: int = 500, include_projects: bool = True) -> dict[str, Any]:
            """Fetch unified inbox data for HTML and JSON consumers."""

            safe_limit = max(1, min(int(limit), 1000))
            messages: list[dict[str, Any]] = []
            projects: list[dict[str, Any]] = []

            try:
                await ensure_schema()

                sibling_map: dict[int, dict[str, Any]] = {}
                if include_projects:
                    await refresh_project_sibling_suggestions()
                    sibling_map = await get_project_sibling_data()

                async with get_session() as session:
                    # Fetch recent messages with sender/project and computed recipient list
                    query = text(
                        """
                        SELECT
                            m.id,
                            m.subject,
                            m.body_md,
                            LENGTH(COALESCE(m.body_md, '')) AS body_length,
                            m.created_ts,
                            m.importance,
                            m.thread_id,
                            sender.name AS sender_name,
                            p.slug AS project_slug,
                            p.human_key AS project_name,
                            COALESCE(
                                (
                                    SELECT GROUP_CONCAT(name, ', ')
                                    FROM (
                                        SELECT DISTINCT recip2.name AS name
                                        FROM message_recipients mr2
                                        JOIN agents recip2 ON recip2.id = mr2.agent_id
                                        WHERE mr2.message_id = m.id
                                        ORDER BY name
                                    )
                                ),
                                ''
                            ) AS recipients
                        FROM messages m
                        JOIN agents sender ON m.sender_id = sender.id
                        JOIN projects p ON m.project_id = p.id
                        ORDER BY m.created_ts DESC
                        LIMIT :limit
                        """
                    )

                    rows = await session.execute(query, {"limit": safe_limit})

                    for r in rows.fetchall():
                        body = r[2] or ""
                        raw_body_length = r[3]
                        body_length = int(raw_body_length) if raw_body_length is not None else len(body)
                        excerpt = body[:150].replace("#", "").replace("*", "").replace("`", "").strip()
                        if body_length > 150:
                            excerpt += "..."

                        created_ts = r[4]
                        if isinstance(created_ts, str):
                            created_dt = datetime.fromisoformat(created_ts.replace("Z", "+00:00"))
                        else:
                            created_dt = created_ts

                        if created_dt.tzinfo is None:
                            created_dt = created_dt.replace(tzinfo=timezone.utc)
                        else:
                            created_dt = created_dt.astimezone(timezone.utc)

                        now = datetime.now(timezone.utc)
                        delta = now - created_dt

                        if delta.days < 0 or (delta.days == 0 and delta.seconds < 0):
                            created_relative = "Just now"
                        elif delta.days > 365:
                            created_relative = f"{delta.days // 365}y ago"
                        elif delta.days > 30:
                            created_relative = f"{delta.days // 30}mo ago"
                        elif delta.days > 0:
                            created_relative = f"{delta.days}d ago"
                        elif delta.seconds > 3600:
                            created_relative = f"{delta.seconds // 3600}h ago"
                        elif delta.seconds > 60:
                            created_relative = f"{delta.seconds // 60}m ago"
                        else:
                            created_relative = "Just now"

                        messages.append(
                            {
                                "id": r[0],
                                "subject": r[1] or "(No subject)",
                                "body_md": body,
                                "body_length": body_length,
                                "excerpt": excerpt,
                                "created_ts": str(r[4]),
                                "created_full": created_dt.strftime("%B %d, %Y at %I:%M %p"),
                                "created_relative": created_relative,
                                "importance": r[5] or "normal",
                                "thread_id": r[6],
                                "sender": r[7],
                                "project_slug": r[8],
                                "project_name": r[9],
                                "recipients": ", ".join(
                                    part.strip() for part in (r[10] or "").split(",") if part.strip()
                                ),
                                "read": False,
                            }
                        )

                    if include_projects:
                        rows = await session.execute(
                            text("SELECT id, slug, human_key, created_at FROM projects ORDER BY created_at DESC")
                        )
                        for r in rows.fetchall():
                            project_id = int(r[0])
                            siblings = sibling_map.get(project_id, {"confirmed": [], "suggested": []})
                            projects.append(
                                {
                                    "id": project_id,
                                    "slug": r[1],
                                    "human_key": r[2],
                                    "created_at": str(r[3]),
                                    "confirmed_siblings": siblings.get("confirmed", []),
                                    "suggested_siblings": siblings.get("suggested", []),
                                }
                            )

            except Exception as exc:  # pragma: no cover - defensive logging
                logging.error("Error fetching unified inbox data", exc_info=True, extra={"error": str(exc)})

            return {"messages": messages, "projects": projects}

        @fastapi_app.get("/mail", response_class=HTMLResponse)
        async def mail_unified_inbox() -> HTMLResponse:
            """Unified inbox showing ALL messages across ALL projects (Gmail-style) + Projects below"""

            payload = await _build_unified_inbox_payload()
            return await _render(
                "mail_unified_inbox.html",
                messages=payload.get("messages", []),
                projects=payload.get("projects", []),
            )

        @fastapi_app.get("/mail/api/unified-inbox", response_class=JSONResponse)
        async def mail_unified_inbox_api(
            limit: int = 50000,
            include_projects: bool = False,
        ) -> JSONResponse:
            """JSON feed for the unified inbox view (used for background refresh)."""

            payload = await _build_unified_inbox_payload(limit=limit, include_projects=include_projects)
            if not include_projects:
                # Reduce payload size when polling for message updates only
                payload["projects"] = []
            return JSONResponse(payload)

        @fastapi_app.get("/mail/projects", response_class=HTMLResponse)
        async def mail_projects_list() -> HTMLResponse:
            """Projects list view (moved from /mail)"""
            await ensure_schema()
            await refresh_project_sibling_suggestions()
            sibling_map = await get_project_sibling_data()
            async with get_session() as session:
                rows = await session.execute(
                    text("SELECT id, slug, human_key, created_at FROM projects ORDER BY created_at DESC")
                )
                projects = []
                for r in rows.fetchall():
                    project_id = int(r[0])
                    siblings = sibling_map.get(project_id, {"confirmed": [], "suggested": []})
                    projects.append(
                        {
                            "id": project_id,
                            "slug": r[1],
                            "human_key": r[2],
                            "created_at": str(r[3]),
                            "confirmed_siblings": siblings.get("confirmed", []),
                            "suggested_siblings": siblings.get("suggested", []),
                        }
                    )
            return await _render("mail_index.html", projects=projects)

        @fastapi_app.get("/mail/{project}", response_class=HTMLResponse)
        async def mail_project(
            project: str,
            q: str | None = None,
            scope: str | None = None,
            order: str | None = None,
            boost: int | None = None,
        ) -> HTMLResponse:
            await ensure_schema()
            async with get_session() as session:
                proj = await session.execute(
                    text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"), {"k": project}
                )
                prow = proj.fetchone()
                if not prow:
                    return await _render("error.html", message="Project not found")
                pid = int(prow[0])
                agents_q = await session.execute(
                    text("SELECT id, name, program, model FROM agents WHERE project_id = :pid ORDER BY name"),
                    {"pid": pid},
                )
                agents = [{"id": r[0], "name": r[1], "program": r[2], "model": r[3]} for r in agents_q.fetchall()]
                matched_messages: list[dict] = []
                if q and q.strip():
                    # Prefer FTS5 when available (fts_messages maintained by triggers)
                    fts_expr, like_pat, like_scope, tokens = _parse_fts_query(q, scope)
                    weights = (0.0, 3.0, 1.0) if (boost or 0) else (0.0, 1.0, 1.0)
                    fts_sql = (
                        "SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id, "
                        "snippet(fts_messages, 2, '<mark>', '</mark>', '…', 18) AS body_snippet, "
                        "(length(snippet(fts_messages, 2, '<mark>', '</mark>', '…', 18)) - length(replace(snippet(fts_messages, 2, '<mark>', '</mark>', '…', 18), '<mark>', ''))) / 6 AS hits "
                        "FROM fts_messages JOIN messages m ON m.id = fts_messages.rowid JOIN agents s ON s.id = m.sender_id "
                        "WHERE m.project_id = :pid AND fts_messages MATCH :q "
                        + (
                            "ORDER BY m.created_ts DESC "
                            if (order or "relevance") == "time"
                            else f"ORDER BY bm25(fts_messages, {weights[0]}, {weights[1]}, {weights[2]}) "
                        )
                        + "LIMIT 10000"
                    )
                    try:
                        search = await session.execute(text(fts_sql), {"pid": pid, "q": fts_expr or q})
                        matched_messages = [
                            {
                                "id": r[0],
                                "subject": r[1],
                                "sender": r[2],
                                "created": str(r[3]),
                                "importance": r[4],
                                "thread_id": r[5],
                                "snippet": r[6],
                                "hits": int(r[7] or 0),
                            }
                            for r in search.fetchall()
                        ]
                    except Exception:
                        # Fallback to LIKE if FTS not available
                        if like_scope == "subject":
                            like_sql = "SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id FROM messages m JOIN agents s ON s.id = m.sender_id WHERE m.project_id = :pid AND m.subject LIKE :pat ORDER BY m.created_ts DESC LIMIT 10000"
                        elif like_scope == "body":
                            like_sql = "SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id FROM messages m JOIN agents s ON s.id = m.sender_id WHERE m.project_id = :pid AND m.body_md LIKE :pat ORDER BY m.created_ts DESC LIMIT 10000"
                        else:
                            like_sql = "SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id FROM messages m JOIN agents s ON s.id = m.sender_id WHERE m.project_id = :pid AND (m.subject LIKE :pat OR m.body_md LIKE :pat) ORDER BY m.created_ts DESC LIMIT 10000"
                        search = await session.execute(text(like_sql), {"pid": pid, "pat": like_pat or f"%{q}%"})
                        matched_messages = [
                            {
                                "id": r[0],
                                "subject": r[1],
                                "sender": r[2],
                                "created": str(r[3]),
                                "importance": r[4],
                                "thread_id": r[5],
                                "snippet": "",
                                "hits": 0,
                            }
                            for r in search.fetchall()
                        ]
            return await _render(
                "mail_project.html",
                project={"id": pid, "slug": prow[1], "human_key": prow[2]},
                agents=agents,
                q=q or "",
                scope=scope or "",
                order=order or "relevance",
                boost=bool(boost),
                tokens=tokens if q and q.strip() else [],
                results=matched_messages,
            )

        @fastapi_app.post("/api/projects/{project_id}/siblings/{other_id}", response_class=JSONResponse)
        async def update_project_sibling(project_id: int, other_id: int, request: Request) -> JSONResponse:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            action = str(payload.get("action", "")).lower()
            if action not in {"confirm", "dismiss", "reset"}:
                return JSONResponse({"error": "Invalid action"}, status_code=status.HTTP_400_BAD_REQUEST)

            target_status = {
                "confirm": "confirmed",
                "dismiss": "dismissed",
                "reset": "suggested",
            }[action]

            try:
                suggestion = await update_project_sibling_status(project_id, other_id, target_status)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
            except NoResultFound:
                return JSONResponse({"error": "Project pair not found"}, status_code=status.HTTP_404_NOT_FOUND)
            except Exception as exc:
                structlog.get_logger("sibling").exception(
                    "project_sibling.update_failed",
                    project_id=project_id,
                    other_id=other_id,
                    action=action,
                    error=str(exc),
                )
                return JSONResponse(
                    {"error": "Unable to update sibling status"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            return JSONResponse({"status": suggestion["status"], "suggestion": suggestion})

        @fastapi_app.get("/mail/unified-inbox", response_class=HTMLResponse)
        async def unified_inbox(limit: int = 10000, filter_importance: str | None = None) -> HTMLResponse:
            """Unified inbox showing messages from all active agents across all projects."""
            await ensure_schema()
            async with get_session() as session:
                # Get all projects with their agents
                projects_query = await session.execute(
                    text(
                        """
                    SELECT p.id, p.slug, p.human_key,
                           COUNT(DISTINCT a.id) as agent_count,
                           MAX(a.last_active_ts) as last_activity
                    FROM projects p
                    LEFT JOIN agents a ON a.project_id = p.id
                    GROUP BY p.id, p.slug, p.human_key
                    ORDER BY (last_activity IS NULL) ASC, last_activity DESC, p.created_at DESC
                    """
                    )
                )
                projects_data = []
                for r in projects_query.fetchall():
                    proj_id = int(r[0])
                    # Get agents for this project
                    agents_query = await session.execute(
                        text(
                            """
                        SELECT a.id, a.name, a.program, a.model, a.last_active_ts
                        FROM agents a
                        WHERE a.project_id = :pid
                        ORDER BY a.last_active_ts DESC, a.name ASC
                        """
                        ),
                        {"pid": proj_id},
                    )

                    agents_list = []
                    for ar in agents_query.fetchall():
                        agents_list.append(
                            {
                                "id": int(ar[0]),
                                "name": ar[1],
                                "program": ar[2],
                                "model": ar[3],
                                "last_active": str(ar[4]) if ar[4] else None,
                            }
                        )

                    if agents_list:  # Only include projects with agents
                        projects_data.append(
                            {
                                "id": proj_id,
                                "slug": r[1],
                                "human_key": r[2],
                                "agent_count": int(r[3] or 0),
                                "agents": agents_list,
                            }
                        )

                # Get recent messages across all projects with thread information
                # Build WHERE clause safely using parameterized queries
                importance_conditions = []
                query_params = {"lim": limit}

                if filter_importance and filter_importance.lower() in ["urgent", "high"]:
                    importance_conditions.append("m.importance IN ('urgent', 'high')")

                where_clause = "WHERE " + " AND ".join(importance_conditions) if importance_conditions else "WHERE 1=1"

                messages_query = await session.execute(
                    text(
                        f"""
                    SELECT
                        m.id, m.subject, m.body_md, m.created_ts, m.importance, m.thread_id,
                        p.slug, p.human_key,
                        sender.name as sender_name,
                        COALESCE(
                            (
                                SELECT GROUP_CONCAT(name, ', ')
                                FROM (
                                    SELECT DISTINCT recip2.name AS name
                                    FROM message_recipients mr2
                                    JOIN agents recip2 ON recip2.id = mr2.agent_id
                                    WHERE mr2.message_id = m.id
                                    ORDER BY name
                                )
                            ),
                            ''
                        ) as recipient_names,
                        COUNT(DISTINCT CASE WHEN m2.id IS NOT NULL THEN m2.id END) as thread_count
                    FROM messages m
                    JOIN projects p ON p.id = m.project_id
                    JOIN agents sender ON sender.id = m.sender_id
                    LEFT JOIN message_recipients mr ON mr.message_id = m.id
                    LEFT JOIN agents recip ON recip.id = mr.agent_id
                    LEFT JOIN messages m2 ON (
                        m.thread_id IS NOT NULL
                        AND m2.thread_id = m.thread_id
                        AND m2.project_id = m.project_id
                        AND m2.id != m.id
                    )
                    {where_clause}
                    GROUP BY m.id, m.subject, m.body_md, m.created_ts, m.importance, m.thread_id,
                             p.slug, p.human_key, sender.name
                    ORDER BY m.created_ts DESC
                    LIMIT :lim
                    """
                    ),
                    query_params,
                )

                messages = []
                for r in messages_query.fetchall():
                    messages.append(
                        {
                            "id": int(r[0]),
                            "subject": r[1],
                            "body_md": r[2] or "",
                            "created": str(r[3]),
                            "importance": r[4] or "normal",
                            "thread_id": r[5],
                            "project_slug": r[6],
                            "project_name": r[7],
                            "sender": r[8],
                            "recipients": r[9] or "",
                            "thread_count": int(r[10] or 0),
                        }
                    )

            return await _render(
                "mail_unified_inbox.html",
                projects=projects_data,
                messages=messages,
                total_agents=sum(p["agent_count"] for p in projects_data),
                total_messages=len(messages),
                filter_importance=filter_importance or "",
            )

        @fastapi_app.get("/mail/{project}/inbox/{agent}", response_class=HTMLResponse)
        async def mail_inbox(project: str, agent: str, limit: int = 10000, page: int = 1) -> HTMLResponse:
            await ensure_schema()
            async with get_session() as session:
                prow = (
                    await session.execute(
                        text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"),
                        {"k": project},
                    )
                ).fetchone()
                if not prow:
                    return await _render("error.html", message="Project not found")
                pid = int(prow[0])
                arow = (
                    await session.execute(
                        text("SELECT id, name FROM agents WHERE project_id = :pid AND lower(name) = lower(:name)"),
                        {"pid": pid, "name": agent},
                    )
                ).fetchone()
                if not arow:
                    return await _render("error.html", message="Agent not found")
                offset = max(0, (max(1, page) - 1) * max(1, limit))
                inbox_rows = await session.execute(
                    text(
                        """
                    SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id
                    FROM messages m
                    JOIN message_recipients mr ON mr.message_id = m.id
                    JOIN agents a ON a.id = mr.agent_id
                    JOIN agents s ON s.id = m.sender_id
                    WHERE m.project_id = :pid AND a.name = :name
                    ORDER BY m.created_ts DESC
                    LIMIT :lim OFFSET :off
                    """
                    ),
                    {"pid": pid, "name": agent, "lim": limit, "off": offset},
                )
                items = [
                    {
                        "id": r[0],
                        "subject": r[1],
                        "sender": r[2],
                        "created": str(r[3]),
                        "importance": r[4],
                        "thread_id": r[5],
                    }
                    for r in inbox_rows.fetchall()
                ]
            return await _render(
                "mail_inbox.html",
                project={"slug": prow[1], "human_key": prow[2]},
                agent=agent,
                items=items,
                page=page,
                limit=limit,
                next_page=page + 1,
                prev_page=page - 1 if page > 1 else None,
            )

        @fastapi_app.get("/mail/{project}/message/{mid}", response_class=HTMLResponse)
        async def mail_message(project: str, mid: int) -> HTMLResponse:
            await ensure_schema()
            async with get_session() as session:
                prow = (
                    await session.execute(
                        text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"),
                        {"k": project},
                    )
                ).fetchone()
                if not prow:
                    return await _render("error.html", message="Project not found")
                pid = int(prow[0])
                mrow = (
                    await session.execute(
                        text(
                            "SELECT m.id, m.subject, m.body_md, s.name, m.created_ts, m.importance, m.thread_id FROM messages m JOIN agents s ON s.id = m.sender_id WHERE m.project_id = :pid AND m.id = :mid"
                        ),
                        {"pid": pid, "mid": mid},
                    )
                ).fetchone()
                if not mrow:
                    return await _render("error.html", message="Message not found")
                recs = await session.execute(
                    text(
                        "SELECT a.name, mr.kind FROM message_recipients mr JOIN agents a ON a.id = mr.agent_id WHERE mr.message_id = :mid"
                    ),
                    {"mid": mid},
                )
                recipients = [{"name": r[0], "kind": r[1]} for r in recs.fetchall()]
                # Find thread messages if thread_id is set
                thread_items: list[dict] = []
                th = mrow[6]
                if isinstance(th, str) and th.strip():
                    th_rows = await session.execute(
                        text(
                            "SELECT m.id, m.subject, s.name, m.created_ts FROM messages m JOIN agents s ON s.id = m.sender_id WHERE m.project_id = :pid AND (m.thread_id = :th OR m.id = :id) ORDER BY m.created_ts ASC"
                        ),
                        {"pid": pid, "th": th, "id": mid},
                    )
                    thread_items = [
                        {"id": rr[0], "subject": rr[1], "from": rr[2], "created": str(rr[3])}
                        for rr in th_rows.fetchall()
                    ]
            # Convert markdown body to HTML for display (server-side render)
            body_html = (
                markdown2.markdown(mrow[2] or "", extras=["fenced-code-blocks", "tables", "strike", "cuddled-lists"])
                if mrow[2]
                else ""
            )
            if body_html:
                body_html = _html_cleaner.clean(body_html)

            # Get commit SHA for provenance badge
            commit_sha = None
            try:
                settings = get_settings()
                if is_archive_enabled(settings):
                    archive = await ensure_archive(settings, prow[1], project_key=prow[2])
                    commit_sha = await get_message_commit_sha(archive, mid)
            except Exception:
                pass  # Commit SHA is optional

            return await _render(
                "mail_message.html",
                project={"slug": prow[1], "human_key": prow[2]},
                message={
                    "id": mrow[0],
                    "subject": mrow[1],
                    "body_md": mrow[2],
                    "body_html": body_html,
                    "sender": mrow[3],
                    "created": str(mrow[4]),
                    "importance": mrow[5],
                    "thread_id": mrow[6],
                },
                recipients=recipients,
                thread_items=thread_items,
                commit_sha=commit_sha,
            )

        @fastapi_app.post("/mail/{project}/inbox/{agent}/mark-read")
        async def mark_selected_messages_read(project: str, agent: str, request: Request) -> JSONResponse:
            """Mark specific messages as read for an agent."""
            await ensure_schema()

            try:
                # Parse request body
                request_body = await request.json()
                message_ids: list[int] = request_body.get("message_ids", [])

                if not message_ids:
                    raise HTTPException(status_code=400, detail="No message IDs provided")

                # Limit to prevent SQL parameter overflow (SQLite default limit is 999)
                # Also prevents abuse - if someone wants to mark 1000+ messages, use "mark all"
                if len(message_ids) > 500:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Too many messages selected ({len(message_ids)}). Maximum is 500. Use 'Mark All Read' instead.",
                    )

                async with get_session() as session:
                    # Get project
                    prow = (
                        await session.execute(
                            text("SELECT id, slug FROM projects WHERE slug = :k OR human_key = :k"),
                            {"k": project},
                        )
                    ).fetchone()
                    if not prow:
                        raise HTTPException(status_code=404, detail="Project not found")

                    pid = int(prow[0])

                    # Get agent
                    arow = (
                        await session.execute(
                            text("SELECT id FROM agents WHERE project_id = :pid AND name = :name"),
                            {"pid": pid, "name": agent},
                        )
                    ).fetchone()
                    if not arow:
                        raise HTTPException(status_code=404, detail="Agent not found")

                    aid = int(arow[0])

                    # Mark specific messages as read
                    now = datetime.now(timezone.utc)

                    # Use IN clause with parameter binding
                    placeholders = ",".join([f":mid{i}" for i in range(len(message_ids))])
                    params = {"aid": aid, "now": now}
                    params.update({f"mid{i}": mid for i, mid in enumerate(message_ids)})

                    result = await session.execute(
                        text(
                            f"""
                            UPDATE message_recipients
                            SET read_ts = :now
                            WHERE agent_id = :aid
                            AND message_id IN ({placeholders})
                            AND read_ts IS NULL
                            """
                        ),
                        params,
                    )
                    await session.commit()

                    count = int(getattr(result, "rowcount", 0) or 0)

                    return JSONResponse(
                        {
                            "success": True,
                            "marked_count": count,
                            "requested_count": len(message_ids),
                            "agent": agent,
                            "project": prow[1],
                        }
                    )

            except HTTPException:
                raise
            except Exception as exc:
                import traceback

                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Failed to mark messages as read: {exc!s}") from exc

        @fastapi_app.post("/mail/{project}/inbox/{agent}/mark-all-read")
        async def mark_all_messages_read(project: str, agent: str) -> JSONResponse:
            """Mark all messages for an agent as read."""
            await ensure_schema()

            try:
                async with get_session() as session:
                    # Get project
                    prow = (
                        await session.execute(
                            text("SELECT id, slug FROM projects WHERE slug = :k OR human_key = :k"),
                            {"k": project},
                        )
                    ).fetchone()
                    if not prow:
                        raise HTTPException(status_code=404, detail="Project not found")

                    pid = int(prow[0])

                    # Get agent
                    arow = (
                        await session.execute(
                            text("SELECT id FROM agents WHERE project_id = :pid AND name = :name"),
                            {"pid": pid, "name": agent},
                        )
                    ).fetchone()
                    if not arow:
                        raise HTTPException(status_code=404, detail="Agent not found")

                    aid = int(arow[0])

                    # Mark all unread messages as read
                    now = datetime.now(timezone.utc)
                    result = await session.execute(
                        text(
                            """
                            UPDATE message_recipients
                            SET read_ts = :now
                            WHERE agent_id = :aid
                            AND read_ts IS NULL
                            """
                        ),
                        {"aid": aid, "now": now},
                    )
                    await session.commit()

                    count = int(getattr(result, "rowcount", 0) or 0)

                    return JSONResponse(
                        {
                            "success": True,
                            "marked_count": count,
                            "agent": agent,
                            "project": prow[1],
                        }
                    )

            except HTTPException:
                raise
            except Exception as exc:
                import traceback

                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Failed to mark messages as read: {exc!s}") from exc

        @fastapi_app.get("/mail/{project}/thread/{thread_id}", response_class=HTMLResponse)
        async def mail_thread(project: str, thread_id: str) -> HTMLResponse:
            """Display all messages in a thread chronologically (Gmail-style conversation view).

            NOTE: Currently loads ALL messages in thread without pagination.
            For threads with 1000+ messages, consider adding LIMIT/OFFSET pagination.
            """
            await ensure_schema()
            async with get_session() as session:
                # Get project
                prow = (
                    await session.execute(
                        text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"),
                        {"k": project},
                    )
                ).fetchone()
                if not prow:
                    return await _render("error.html", message="Project not found")

                pid = int(prow[0])

                # Get all messages in this thread, ordered chronologically
                # Include messages where thread_id matches OR message id matches (for thread starter)
                try:
                    thread_id_int = int(thread_id)
                    rows = await session.execute(
                        text(
                            """
                            SELECT m.id, m.subject, m.body_md, s.name, m.created_ts, m.importance, m.thread_id
                            FROM messages m
                            JOIN agents s ON s.id = m.sender_id
                            WHERE m.project_id = :pid
                            AND (m.thread_id = :tid OR m.id = :tid_int)
                            ORDER BY m.created_ts ASC
                            """
                        ),
                        {"pid": pid, "tid": thread_id, "tid_int": thread_id_int},
                    )
                except ValueError:
                    # Not an integer, just use string thread_id
                    rows = await session.execute(
                        text(
                            """
                            SELECT m.id, m.subject, m.body_md, s.name, m.created_ts, m.importance, m.thread_id
                            FROM messages m
                            JOIN agents s ON s.id = m.sender_id
                            WHERE m.project_id = :pid
                            AND m.thread_id = :tid
                            ORDER BY m.created_ts ASC
                            """
                        ),
                        {"pid": pid, "tid": thread_id},
                    )

                messages = []
                for r in rows.fetchall():
                    # Convert markdown to HTML for each message
                    body_html = ""
                    if r[2]:  # body_md
                        body_html = markdown2.markdown(
                            r[2], extras=["fenced-code-blocks", "tables", "strike", "cuddled-lists"]
                        )
                        body_html = _html_cleaner.clean(body_html)

                    messages.append(
                        {
                            "id": r[0],
                            "subject": r[1],
                            "body_md": r[2],
                            "body_html": body_html,
                            "sender": r[3],
                            "created": str(r[4]),
                            "importance": r[5],
                            "thread_id": r[6],
                        }
                    )

                if not messages:
                    return await _render(
                        "error.html",
                        message=f"No messages found in thread '{thread_id}'. The thread may not exist or all messages may have been deleted.",
                    )

                # Get unique subject (use first message's subject, with fallback)
                thread_subject = (
                    messages[0]["subject"] if messages and messages[0]["subject"] else f"Thread {thread_id}"
                )

                return await _render(
                    "mail_thread.html",
                    project={"slug": prow[1], "human_key": prow[2]},
                    thread_id=thread_id,
                    thread_subject=thread_subject,
                    messages=messages,
                    message_count=len(messages),
                )

        # Full-text search UI across subject/body using LIKE fallback (SQLite FTS handled elsewhere)
        @fastapi_app.get("/mail/{project}/search", response_class=HTMLResponse)
        async def mail_search(
            project: str,
            q: str,
            limit: int = 10000,
            scope: str | None = None,
            order: str | None = None,
            boost: int | None = None,
        ) -> HTMLResponse:
            await ensure_schema()
            async with get_session() as session:
                prow = (
                    await session.execute(
                        text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"),
                        {"k": project},
                    )
                ).fetchone()
                if not prow:
                    return await _render("error.html", message="Project not found")
                pid = int(prow[0])
                fts_expr, like_pat, like_scope, tokens = _parse_fts_query(q, scope)
                weights = (0.0, 3.0, 1.0) if (boost or 0) else (0.0, 1.0, 1.0)
                fts_sql = (
                    "SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id, "
                    "snippet(fts_messages, 2, '<mark>', '</mark>', '…', 22) AS body_snippet, "
                    "(length(snippet(fts_messages, 2, '<mark>', '</mark>', '…', 22)) - length(replace(snippet(fts_messages, 2, '<mark>', '</mark>', '…', 22), '<mark>', ''))) / 6 AS hits "
                    "FROM fts_messages JOIN messages m ON m.id = fts_messages.rowid JOIN agents s ON s.id = m.sender_id "
                    "WHERE m.project_id = :pid AND fts_messages MATCH :q "
                    + (
                        "ORDER BY m.created_ts DESC "
                        if (order or "relevance") == "time"
                        else f"ORDER BY bm25(fts_messages, {weights[0]}, {weights[1]}, {weights[2]}) "
                    )
                    + "LIMIT :lim"
                )
                try:
                    rows = await session.execute(text(fts_sql), {"pid": pid, "q": fts_expr or q, "lim": limit})
                    results = [
                        {
                            "id": r[0],
                            "subject": r[1],
                            "from": r[2],
                            "created": str(r[3]),
                            "importance": r[4],
                            "thread_id": r[5],
                            "snippet": r[6],
                            "hits": int(r[7] or 0),
                        }
                        for r in rows.fetchall()
                    ]
                except Exception:
                    if like_scope == "subject":
                        like_sql = "SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id FROM messages m JOIN agents s ON s.id = m.sender_id WHERE m.project_id = :pid AND m.subject LIKE :pat ORDER BY m.created_ts DESC LIMIT :lim"
                    elif like_scope == "body":
                        like_sql = "SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id FROM messages m JOIN agents s ON s.id = m.sender_id WHERE m.project_id = :pid AND m.body_md LIKE :pat ORDER BY m.created_ts DESC LIMIT :lim"
                    else:
                        like_sql = "SELECT m.id, m.subject, s.name, m.created_ts, m.importance, m.thread_id FROM messages m JOIN agents s ON s.id = m.sender_id WHERE m.project_id = :pid AND (m.subject LIKE :pat OR m.body_md LIKE :pat) ORDER BY m.created_ts DESC LIMIT :lim"
                    rows = await session.execute(
                        text(like_sql), {"pid": pid, "pat": like_pat or f"%{q}%", "lim": limit}
                    )
                    results = [
                        {
                            "id": r[0],
                            "subject": r[1],
                            "from": r[2],
                            "created": str(r[3]),
                            "importance": r[4],
                            "thread_id": r[5],
                            "snippet": "",
                            "hits": 0,
                        }
                        for r in rows.fetchall()
                    ]
            return await _render(
                "mail_search.html",
                project={"slug": prow[1], "human_key": prow[2]},
                q=q,
                scope=scope or "",
                order=order or "relevance",
                tokens=tokens,
                results=results,
                boost=bool(boost),
            )

        # File reservations and attachments views
        @fastapi_app.get("/mail/{project}/file_reservations", response_class=HTMLResponse)
        async def mail_file_reservations(project: str) -> HTMLResponse:
            await ensure_schema()
            async with get_session() as session:
                prow = (
                    await session.execute(
                        text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"),
                        {"k": project},
                    )
                ).fetchone()
                if not prow:
                    return await _render("error.html", message="Project not found")
                pid = int(prow[0])
                rows = await session.execute(
                    text(
                        "SELECT c.id, a.name, c.path_pattern, c.exclusive, c.created_ts, c.expires_ts, c.released_ts FROM file_reservations c JOIN agents a ON a.id = c.agent_id WHERE c.project_id = :pid ORDER BY c.created_ts DESC"
                    ),
                    {"pid": pid},
                )
                file_reservations = [
                    {
                        "id": r[0],
                        "agent": r[1],
                        "path_pattern": r[2],
                        "exclusive": bool(r[3]),
                        "created": str(r[4]),
                        "expires": str(r[5]) if r[5] else "",
                        "released": str(r[6]) if r[6] else "",
                    }
                    for r in rows.fetchall()
                ]
            return await _render(
                "mail_file_reservations.html",
                project={"slug": prow[1], "human_key": prow[2]},
                file_reservations=file_reservations,
            )

        @fastapi_app.get("/mail/{project}/attachments", response_class=HTMLResponse)
        async def mail_attachments(project: str) -> HTMLResponse:
            await ensure_schema()
            async with get_session() as session:
                prow = (
                    await session.execute(
                        text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"),
                        {"k": project},
                    )
                ).fetchone()
                if not prow:
                    return await _render("error.html", message="Project not found")
                pid = int(prow[0])
                rows = await session.execute(
                    text(
                        "SELECT id, subject, created_ts, attachments FROM messages WHERE project_id = :pid AND json_array_length(attachments) > 0 ORDER BY created_ts DESC LIMIT 10000"
                    ),
                    {"pid": pid},
                )
                items = []
                for r in rows.fetchall():
                    try:
                        attachments = r[3] or []
                    except Exception:
                        attachments = []
                    items.append({"id": r[0], "subject": r[1], "created": str(r[2]), "attachments": attachments})
            return await _render("mail_attachments.html", project={"slug": prow[1], "human_key": prow[2]}, items=items)

        # ========== Human Overseer Routes ==========

        @fastapi_app.get("/mail/{project}/overseer/compose", response_class=HTMLResponse)
        async def overseer_compose(project: str) -> HTMLResponse:
            """Display Human Overseer message composer."""
            await ensure_schema()
            async with get_session() as session:
                # Get project
                prow = (
                    await session.execute(
                        text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"),
                        {"k": project},
                    )
                ).fetchone()
                if not prow:
                    return await _render("error.html", message="Project not found")

                # Get all agents for this project
                pid = int(prow[0])
                agent_rows = await session.execute(
                    text("SELECT name FROM agents WHERE project_id = :pid ORDER BY name"), {"pid": pid}
                )
                agents = [{"name": r[0]} for r in agent_rows.fetchall()]

            return await _render(
                "overseer_compose.html", project={"slug": prow[1], "human_key": prow[2]}, agents=agents
            )

        @fastapi_app.post("/mail/{project}/overseer/send")
        async def overseer_send(project: str, request: Request) -> JSONResponse:
            """Send message from Human Overseer to selected agents."""
            await ensure_schema()

            try:
                # Parse request body
                request_body = await request.json()
                recipients: list[str] = request_body.get("recipients", [])
                subject: str = request_body.get("subject", "").strip()
                body_md: str = request_body.get("body_md", "").strip()
                thread_id: str | None = request_body.get("thread_id")

                # Comprehensive validation
                if not recipients:
                    raise HTTPException(status_code=400, detail="At least one recipient is required")
                if len(recipients) > 100:
                    raise HTTPException(status_code=400, detail="Too many recipients (maximum 100 agents)")
                if not subject:
                    raise HTTPException(status_code=400, detail="Subject is required")
                if len(subject) > 200:
                    raise HTTPException(status_code=400, detail="Subject too long (maximum 200 characters)")
                if not body_md:
                    raise HTTPException(status_code=400, detail="Message body is required")
                if len(body_md) > 50000:
                    raise HTTPException(status_code=400, detail="Message body too long (maximum 50,000 characters)")

                # Remove duplicate recipients while preserving order
                recipients = list(dict.fromkeys(recipients))

                # Add Human Overseer preamble (pure markdown for cross-renderer compatibility)
                preamble = """---

        🚨 MESSAGE FROM HUMAN OVERSEER 🚨

        This message is from a human operator overseeing this project. Please prioritize the instructions below over your current tasks.

        You should:
        1. Temporarily pause your current work
        2. Complete the request described below
        3. Resume your original plans afterward (unless modified by these instructions)

        The human's guidance supersedes all other priorities.

        ---

        """
                full_body = preamble + body_md

                # Validate combined length (preamble + user message)
                if len(full_body) > 50000:
                    preamble_length = len(preamble)
                    max_user_length = 50000 - preamble_length
                    raise HTTPException(
                        status_code=400,
                        detail=f"Message body too long ({len(body_md)} characters). Maximum is {max_user_length} characters to accommodate the overseer preamble ({preamble_length} characters).",
                    )

                # Single atomic transaction for all database operations
                from datetime import datetime, timezone

                async with get_session() as session:
                    # Get project
                    prow = (
                        await session.execute(
                            text("SELECT id, slug, human_key FROM projects WHERE slug = :k OR human_key = :k"),
                            {"k": project},
                        )
                    ).fetchone()
                    if not prow:
                        raise HTTPException(status_code=404, detail="Project not found")

                    # Extract project info consistently
                    project_id = int(prow[0])
                    project_slug = prow[1]
                    project_human_key = prow[2]

                    # Get or create "HumanOverseer" agent (with race condition protection)
                    overseer_name = "HumanOverseer"
                    overseer_row = (
                        await session.execute(
                            text("SELECT id, name FROM agents WHERE project_id = :pid AND name = :name"),
                            {"pid": project_id, "name": overseer_name},
                        )
                    ).fetchone()

                    if not overseer_row:
                        # Create HumanOverseer agent (use INSERT OR IGNORE to handle race conditions)
                        await session.execute(
                            text("""
                                INSERT OR IGNORE INTO agents (
                                    project_id,
                                    name,
                                    program,
                                    model,
                                    task_description,
                                    attachments_policy,
                                    inception_ts,
                                    last_active_ts
                                )
                                VALUES (
                                    :pid,
                                    :name,
                                    :program,
                                    :model,
                                    :task,
                                    :attachments_policy,
                                    :ts,
                                    :ts
                                )
                            """),
                            {
                                "pid": project_id,
                                "name": overseer_name,
                                "program": "WebUI",
                                "model": "Human",
                                "task": "Human operator providing guidance and oversight to agents",
                                "attachments_policy": "auto",
                                "ts": datetime.now(timezone.utc),
                            },
                        )
                        # Don't commit yet - wait until message is successfully created and written to Git

                        # Fetch the agent (whether we just created it or another request did)
                        overseer_row = (
                            await session.execute(
                                text("SELECT id, name FROM agents WHERE project_id = :pid AND name = :name"),
                                {"pid": project_id, "name": overseer_name},
                            )
                        ).fetchone()

                        if not overseer_row:
                            raise HTTPException(status_code=500, detail="Failed to create HumanOverseer agent")

                    # Extract overseer_id for later use
                    overseer_id = overseer_row[0]
                    # Insert message into database
                    message_id = None
                    now = datetime.now(timezone.utc)

                    result = await session.execute(
                        text("""
                            INSERT INTO messages (project_id, sender_id, subject, body_md, importance, thread_id, created_ts, ack_required)
                            VALUES (:pid, :sid, :subj, :body, :imp, :tid, :ts, :ack)
                            RETURNING id
                        """),
                        {
                            "pid": project_id,
                            "sid": overseer_id,
                            "subj": subject,
                            "body": full_body,
                            "imp": "high",  # Always high importance for overseer
                            "tid": thread_id,
                            "ts": now,
                            "ack": False,
                        },
                    )
                    message_row = result.fetchone()
                    if not message_row:
                        raise HTTPException(status_code=500, detail="Failed to create message")
                    message_id = message_row[0]

                    # Insert recipients (optimized: bulk SELECT + bulk INSERT instead of N+1 queries)
                    # Build SQL with proper parameter expansion for IN clause
                    placeholders = ", ".join([f":name_{i}" for i in range(len(recipients))])
                    params = {"pid": project_id}
                    params.update({f"name_{i}": name for i, name in enumerate(recipients)})

                    # Single query to get all valid recipient IDs
                    recipient_rows = await session.execute(
                        text(f"SELECT id, name FROM agents WHERE project_id = :pid AND name IN ({placeholders})"),
                        params,
                    )
                    recipient_map = {row[1]: row[0] for row in recipient_rows.fetchall()}  # name -> id mapping

                    # Build valid recipients list (only those that exist)
                    valid_recipients = [name for name in recipients if name in recipient_map]

                    # Bulk insert all message_recipients (single executemany call)
                    if valid_recipients:
                        # Prepare bulk insert params
                        insert_params = [
                            {"mid": message_id, "aid": recipient_map[name], "kind": "to"} for name in valid_recipients
                        ]
                        # Use executemany for bulk insert
                        await session.execute(
                            text("""
                                INSERT INTO message_recipients (message_id, agent_id, kind)
                                VALUES (:mid, :aid, :kind)
                            """),
                            insert_params,
                        )

                    # If no valid recipients found, rollback and error
                    if not valid_recipients:
                        await session.rollback()
                        raise HTTPException(
                            status_code=400,
                            detail=f"None of the specified recipients exist in this project. Available agents can be seen at /mail/{project_slug}",
                        )

                    settings = get_settings()
                    if is_archive_enabled(settings):
                        archive = await ensure_archive(settings, project_slug, project_key=project_human_key)

                    # Build message dict for Git (when enabled)
                    message_dict = {
                        "id": message_id,
                        "thread_id": thread_id,
                        "project": project_human_key,
                        "project_slug": project_slug,
                        "from": overseer_name,
                        "to": valid_recipients,
                        "cc": [],
                        "bcc": [],
                        "subject": subject,
                        "importance": "high",
                        "ack_required": False,
                        "created": now.isoformat(),
                        "attachments": [],
                    }

                    if is_archive_enabled(settings):
                        try:
                            # Write message bundle (canonical + outbox + inboxes) to Git
                            await write_message_bundle(
                                archive,
                                message_dict,
                                full_body,
                                overseer_name,
                                valid_recipients,
                                extra_paths=None,
                                commit_text=f"Human Overseer message: {subject}",
                            )
                        except Exception as git_error:
                            # Rollback database transaction if Git write fails
                            await session.rollback()
                            raise HTTPException(
                                status_code=500, detail=f"Failed to write message to Git archive: {git_error!s}"
                            ) from git_error

                    # Update HumanOverseer activity timestamp (after successful Git write, before commit)
                    await session.execute(
                        text("UPDATE agents SET last_active_ts = :ts WHERE id = :id"), {"ts": now, "id": overseer_id}
                    )

                    # Commit all changes atomically: agent creation/update + message + recipients
                    await session.commit()

                return JSONResponse(
                    {
                        "success": True,
                        "message_id": message_id,
                        "recipients": valid_recipients,
                        "sent_at": now.isoformat(),
                    }
                )

            except HTTPException:
                raise
            except Exception as e:
                import traceback

                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Failed to send message: {e!s}") from e

        # ========== Archive Visualization Routes ==========

        def _validate_project_slug(slug: str) -> bool:
            """Validate project slug format to prevent path traversal."""
            import re

            # Slugs should only contain lowercase letters, numbers, hyphens, underscores
            # No path separators or relative path components
            if not slug:
                return False
            if slug in (".", "..", "/", "\\"):
                return False
            if "/" in slug or "\\" in slug or ".." in slug:
                return False
            # Should match safe slug pattern
            return bool(re.match(r"^[a-z0-9_-]+$", slug, re.IGNORECASE))

        @fastapi_app.get("/mail/archive/guide", response_class=HTMLResponse)
        async def archive_guide() -> HTMLResponse:
            """Display the archive access guide and overview."""
            settings = get_settings()
            storage_root = str(Path(settings.storage.root).expanduser().resolve())

            # Get basic stats
            from pathlib import Path as P

            from git import Repo as GitRepo

            repo_root = P(storage_root)
            if (repo_root / ".git").exists():
                try:
                    repo = GitRepo(str(repo_root))
                    # Use efficient commit counting with limit to prevent DoS
                    commit_count = sum(1 for _ in repo.iter_commits(max_count=10000))
                    total_commits = "10,000+" if commit_count == 10000 else f"{commit_count:,}"
                    last_commit = next(repo.iter_commits(max_count=1), None)
                    last_commit_time = last_commit.authored_datetime.strftime("%b %d, %Y") if last_commit else "Never"

                    # Count projects (with limit for performance)
                    projects_dir = repo_root / "projects"
                    if projects_dir.exists():
                        # Use islice to avoid loading all dirs into memory
                        from itertools import islice

                        project_count = sum(1 for p in islice(projects_dir.iterdir(), 100) if p.is_dir())
                    else:
                        project_count = 0

                    # Estimate size with timeout (run blocking 'du' in a worker thread)
                    import asyncio as _asyncio
                    import subprocess as _subprocess

                    try:

                        def _run_du():
                            return _subprocess.run(
                                ["du", "-sh", str(repo_root)],
                                capture_output=True,
                                text=True,
                                timeout=5.0,
                            )

                        result = await _asyncio.to_thread(_run_du)
                        repo_size = result.stdout.split()[0] if getattr(result, "returncode", 1) == 0 else "Unknown"
                    except (_subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
                        # du not available, took too long, or other OS error
                        repo_size = "Unknown"
                    except Exception:
                        # Catch-all for unexpected errors
                        repo_size = "Unknown"
                except Exception:
                    total_commits = "0"
                    project_count = 0
                    repo_size = "Unknown"
                    last_commit_time = "Unknown"
            else:
                total_commits = "0"
                project_count = 0
                repo_size = "0 MB"
                last_commit_time = "Never"

            # Get list of projects for picker
            async with get_session() as session:
                rows = await session.execute(text("SELECT slug, human_key FROM projects ORDER BY human_key"))
                projects = [{"slug": r[0], "human_key": r[1]} for r in rows.fetchall()]

            return await _render(
                "archive_guide.html",
                storage_root=storage_root,
                total_commits=total_commits,
                project_count=project_count,
                repo_size=repo_size,
                last_commit_time=last_commit_time,
                projects=projects,
            )

        @fastapi_app.get("/mail/archive/activity", response_class=HTMLResponse)
        async def archive_activity(limit: int = 50) -> HTMLResponse:
            """Display recent commits across all projects."""
            # Validate and cap limit to prevent DoS
            limit = max(1, min(limit, 500))  # Between 1 and 500

            settings = get_settings()
            repo_root = Path(settings.storage.root).expanduser().resolve()

            from git import Repo as GitRepo

            if not (repo_root / ".git").exists():
                return await _render("archive_activity.html", commits=[])

            repo = GitRepo(str(repo_root))
            commits = await get_recent_commits(repo, limit=limit)

            return await _render("archive_activity.html", commits=commits)

        @fastapi_app.get("/mail/archive/commit/{sha}", response_class=HTMLResponse)
        async def archive_commit(sha: str) -> HTMLResponse:
            """Display detailed commit information with diffs."""
            settings = get_settings()
            repo_root = Path(settings.storage.root).expanduser().resolve()

            from git import Repo as GitRepo

            if not (repo_root / ".git").exists():
                return await _render("error.html", message="Archive repository not found")

            try:
                repo = GitRepo(str(repo_root))
                commit = await get_commit_detail(repo, sha)
                return await _render("archive_commit.html", commit=commit)
            except ValueError:
                # Validation errors (bad SHA, etc.)
                return await _render("error.html", message="Invalid commit identifier")
            except Exception:
                # Don't leak error details
                return await _render("error.html", message="Commit not found")

        @fastapi_app.get("/mail/archive/timeline", response_class=HTMLResponse)
        async def archive_timeline(project: str | None = None) -> HTMLResponse:
            """Display communication timeline with Mermaid.js visualization."""
            # Validate project slug if provided
            if project and not _validate_project_slug(project):
                return await _render("error.html", message="Invalid project identifier")

            settings = get_settings()
            repo_root = Path(settings.storage.root).expanduser().resolve()

            from git import Repo as GitRepo

            if not (repo_root / ".git").exists():
                return await _render("error.html", message="Archive repository not found")

            # Default to first project if not specified
            if not project:
                async with get_session() as session:
                    row = (
                        await session.execute(text("SELECT slug, human_key FROM projects ORDER BY id LIMIT 1"))
                    ).fetchone()
                    if row:
                        project = row[0]
                    else:
                        return await _render("error.html", message="No projects found")

            # Get project name
            project_name = project
            async with get_session() as session:
                row = (
                    await session.execute(text("SELECT human_key FROM projects WHERE slug = :s"), {"s": project})
                ).fetchone()
                if row:
                    project_name = row[0]

            repo = GitRepo(str(repo_root))
            commits = await get_timeline_commits(repo, project, limit=100)

            return await _render("archive_timeline.html", commits=commits, project=project, project_name=project_name)

        @fastapi_app.get("/mail/archive/browser", response_class=HTMLResponse)
        async def archive_browser(project: str | None = None, path: str = "") -> HTMLResponse:
            """Browse archive files and directories."""
            if not project:
                # Show project selector - requires project parameter
                return await _render("error.html", message="Please select a project to browse")

            # Validate project slug
            if not _validate_project_slug(project):
                return await _render("error.html", message="Invalid project identifier")

            async with get_session() as session:
                human_row = (
                    await session.execute(
                        text("SELECT human_key FROM projects WHERE slug = :s OR human_key = :s"), {"s": project}
                    )
                ).fetchone()
                project_human_key = human_row[0] if human_row else None

            settings = get_settings()
            if not is_archive_enabled(settings):
                return await _render("error.html", message="Archive storage is disabled")
            archive = await ensure_archive(settings, project, project_key=project_human_key)
            tree = await get_archive_tree(archive, path)

            return await _render("archive_browser.html", tree=tree, project=project, path=path)

        @fastapi_app.get("/mail/archive/browser/{project}/file")
        async def archive_browser_file(project: str, path: str) -> JSONResponse:
            """Get file content from archive."""
            # Validate project slug
            if not _validate_project_slug(project):
                raise HTTPException(status_code=400, detail="Invalid project identifier")

            try:
                async with get_session() as session:
                    human_row = (
                        await session.execute(
                            text("SELECT human_key FROM projects WHERE slug = :s OR human_key = :s"), {"s": project}
                        )
                    ).fetchone()
                    project_human_key = human_row[0] if human_row else None
                settings = get_settings()
                if not is_archive_enabled(settings):
                    raise HTTPException(status_code=404, detail="Archive storage is disabled")
                archive = await ensure_archive(settings, project, project_key=project_human_key)
                content = await get_file_content(archive, path)

                if content is None:
                    raise HTTPException(status_code=404, detail="File not found")

                return JSONResponse(content=content)
            except ValueError as err:
                # Path validation errors
                raise HTTPException(status_code=400, detail="Invalid file path") from err
            except Exception as err:
                raise HTTPException(status_code=404, detail="File not found") from err

        @fastapi_app.get("/mail/archive/network", response_class=HTMLResponse)
        async def archive_network(project: str | None = None) -> HTMLResponse:
            """Display agent communication network graph."""
            # Validate project slug if provided
            if project and not _validate_project_slug(project):
                return await _render("error.html", message="Invalid project identifier")

            settings = get_settings()
            repo_root = Path(settings.storage.root).expanduser().resolve()

            from git import Repo as GitRepo

            if not (repo_root / ".git").exists():
                return await _render("error.html", message="Archive repository not found")

            # Default to first project
            if not project:
                async with get_session() as session:
                    row = (
                        await session.execute(text("SELECT slug, human_key FROM projects ORDER BY id LIMIT 1"))
                    ).fetchone()
                    if row:
                        project = row[0]
                    else:
                        return await _render("error.html", message="No projects found")

            # Get project name
            project_name = project
            async with get_session() as session:
                row = (
                    await session.execute(text("SELECT human_key FROM projects WHERE slug = :s"), {"s": project})
                ).fetchone()
                if row:
                    project_name = row[0]

            repo = GitRepo(str(repo_root))
            graph = await get_agent_communication_graph(repo, project, limit=200)

            return await _render("archive_network.html", graph=graph, project=project, project_name=project_name)

        @fastapi_app.get("/api/projects/{project}/agents")
        async def api_project_agents(project: str) -> JSONResponse:
            """Get list of agents for a project."""
            # Validate project slug
            if not _validate_project_slug(project):
                raise HTTPException(status_code=400, detail="Invalid project identifier")

            async with get_session() as session:
                # Get project ID
                proj_result = await session.execute(
                    text("SELECT id FROM projects WHERE slug = :k OR human_key = :k"), {"k": project}
                )
                prow = proj_result.fetchone()
                if not prow:
                    raise HTTPException(status_code=404, detail="Project not found")

                # Get agents for this project
                agents_result = await session.execute(
                    text("SELECT name FROM agents WHERE project_id = :pid ORDER BY name"), {"pid": prow[0]}
                )
                agents = [r[0] for r in agents_result.fetchall()]

            return JSONResponse({"agents": agents})

        @fastapi_app.get("/mail/archive/time-travel", response_class=HTMLResponse)
        async def archive_time_travel() -> HTMLResponse:
            """Display time-travel interface."""
            # Get all projects
            async with get_session() as session:
                rows = await session.execute(text("SELECT slug FROM projects ORDER BY human_key"))
                projects = [r[0] for r in rows.fetchall()]

            return await _render("archive_time_travel.html", projects=projects)

        @fastapi_app.get("/mail/archive/time-travel/snapshot")
        async def archive_time_travel_snapshot(project: str, agent: str, timestamp: str) -> JSONResponse:
            """Get historical inbox snapshot."""
            # Validate project slug
            if not _validate_project_slug(project):
                raise HTTPException(status_code=400, detail="Invalid project identifier")

            # Validate agent name (alphanumeric only)
            if not agent or not re.match(r"^[A-Za-z0-9]+$", agent):
                raise HTTPException(status_code=400, detail="Invalid agent name format")

            # Validate timestamp format (basic ISO 8601 check)
            if not timestamp or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", timestamp):
                raise HTTPException(
                    status_code=400, detail="Invalid timestamp format. Use ISO 8601 format (YYYY-MM-DDTHH:MM)"
                )

            try:
                # Get project archive
                settings = get_settings()
                if not is_archive_enabled(settings):
                    raise HTTPException(status_code=404, detail="Archive storage is disabled")
                async with get_session() as session:
                    human_row = (
                        await session.execute(
                            text("SELECT human_key FROM projects WHERE slug = :s OR human_key = :s"), {"s": project}
                        )
                    ).fetchone()
                    project_human_key = human_row[0] if human_row else None
                repo = await ensure_archive(settings, project, project_key=project_human_key)

                # Get historical snapshot
                snapshot = await get_historical_inbox_snapshot(repo, agent, timestamp, limit=200)

                return JSONResponse(snapshot)

            except Exception as e:
                # Log error but return empty result rather than failing
                structlog.get_logger("archive").warning(
                    "time_travel_failed", project=project, agent=agent, timestamp=timestamp, error=str(e)
                )
                return JSONResponse(
                    {
                        "messages": [],
                        "snapshot_time": None,
                        "commit_sha": None,
                        "requested_time": timestamp,
                        "error": f"Unable to retrieve historical snapshot: {e!s}",
                    }
                )

    try:
        _register_mail_ui()
    except Exception as exc:
        # templates/Jinja may be missing in some environments; UI remains optional
        with contextlib.suppress(Exception):
            structlog.get_logger("ui").error("ui_init_failed", error=str(exc))
        pass

    return fastapi_app


def main() -> None:
    """Run the HTTP transport using settings-specified host/port."""

    parser = argparse.ArgumentParser(description="Run the MCP Agent Mail HTTP transport")
    parser.add_argument("--host", help="Override HTTP host", default=None)
    parser.add_argument("--port", help="Override HTTP port", type=int, default=None)
    parser.add_argument("--log-level", help="Uvicorn log level", default="info")
    # Be tolerant of extraneous argv when invoked under test runners
    args, _unknown = parser.parse_known_args()

    settings = get_settings()
    host = args.host or settings.http.host
    port = args.port or settings.http.port

    app = build_http_app(settings)
    # Disable WebSockets when running the service directly; HTTP-only transport
    import inspect as _inspect

    _sig = _inspect.signature(uvicorn.run)
    _kwargs: dict[str, Any] = {"host": host, "port": port, "log_level": args.log_level}
    if "ws" in _sig.parameters:
        _kwargs["ws"] = "none"
    uvicorn.run(app, **_kwargs)


if __name__ == "__main__":  # pragma: no cover - manual execution path
    main()
