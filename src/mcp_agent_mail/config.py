"""Application configuration loaded via python-decouple with typed helpers.

Configuration sources (in order of precedence):
1. Environment variables
2. ~/.mcp_mail/credentials.json (for secrets, recommended for PyPI installs)
3. .env file in current directory (for development)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal, cast

from decouple import Config as DecoupleConfig, RepositoryEnv

# User-level credentials file (preferred for PyPI installs)
_USER_CREDENTIALS_PATH: Final[Path] = Path.home() / ".mcp_mail" / "credentials.json"
_DOTENV_PATH: Final[Path] = Path(".env")

# Load user credentials from ~/.mcp_mail/credentials.json
_user_credentials: dict[str, str] = {}
if _USER_CREDENTIALS_PATH.exists():
    try:
        with _USER_CREDENTIALS_PATH.open() as f:
            _user_credentials = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass  # Silently ignore malformed credentials file


def _get_config_value(name: str, default: str = "") -> str:
    """Get config value with precedence: env > credentials.json > .env > default."""
    # 1. Check environment variables first
    env_value = os.environ.get(name)
    if env_value is not None:
        return env_value
    # 2. Check user credentials file
    if name in _user_credentials:
        return str(_user_credentials[name])
    # 3. Fall through to decouple (handles .env and defaults)
    return _decouple_config(name, default=default)


# Create config that gracefully handles missing .env file
if _DOTENV_PATH.exists():
    _decouple_config: Final[DecoupleConfig] = DecoupleConfig(RepositoryEnv(str(_DOTENV_PATH)))
else:
    # Fall back to environment variables only when .env doesn't exist (e.g., in CI)
    from decouple import config as _env_config

    _decouple_config: Final[DecoupleConfig] = _env_config  # type: ignore[assignment]


@dataclass(slots=True, frozen=True)
class HttpSettings:
    """HTTP transport related settings."""

    host: str
    port: int
    path: str
    bearer_token: str | None
    # Basic per-IP limiter (legacy/simple)
    rate_limit_enabled: bool
    rate_limit_per_minute: int
    rate_limit_slack_per_minute: int
    rate_limit_slackbox_per_minute: int
    # Robust token-bucket limiter
    rate_limit_backend: str  # "memory" | "redis"
    rate_limit_tools_per_minute: int
    rate_limit_resources_per_minute: int
    rate_limit_slack_burst: int
    rate_limit_slackbox_burst: int
    rate_limit_redis_url: str
    # Optional bursts to control spikiness
    rate_limit_tools_burst: int
    rate_limit_resources_burst: int
    request_log_enabled: bool
    otel_enabled: bool
    otel_service_name: str
    otel_exporter_otlp_endpoint: str
    # JWT / RBAC
    jwt_enabled: bool
    jwt_algorithms: list[str]
    jwt_secret: str | None
    jwt_jwks_url: str | None
    jwt_audience: str | None
    jwt_issuer: str | None
    jwt_role_claim: str
    rbac_enabled: bool
    rbac_reader_roles: list[str]
    rbac_writer_roles: list[str]
    rbac_default_role: str
    rbac_readonly_tools: list[str]
    # Dev convenience
    allow_localhost_unauthenticated: bool


@dataclass(slots=True, frozen=True)
class DatabaseSettings:
    """Database connectivity settings."""

    url: str
    echo: bool


@dataclass(slots=True, frozen=True)
class StorageSettings:
    """Filesystem/Git storage configuration."""

    root: str
    git_author_name: str
    git_author_email: str
    inline_image_max_bytes: int
    convert_images: bool
    keep_original_images: bool


@dataclass(slots=True, frozen=True)
class CorsSettings:
    """CORS configuration for the HTTP app."""

    enabled: bool
    origins: list[str]
    allow_credentials: bool
    allow_methods: list[str]
    allow_headers: list[str]


@dataclass(slots=True, frozen=True)
class LlmSettings:
    """LiteLLM-related settings and defaults."""

    enabled: bool
    default_model: str
    temperature: float
    max_tokens: int
    cache_enabled: bool
    cache_backend: str  # "memory" | "redis"
    cache_redis_url: str
    cost_logging_enabled: bool


@dataclass(slots=True, frozen=True)
class SlackSettings:
    """Slack integration configuration."""

    enabled: bool
    bot_token: str | None  # Bot User OAuth Token (xoxb-...)
    app_token: str | None  # App-Level Token for Socket Mode (xapp-...)
    signing_secret: str | None  # For webhook signature verification
    default_channel: str  # Default channel ID or name for notifications
    # Notification behavior
    notify_on_message: bool  # Send Slack notification when MCP message is created
    notify_on_ack: bool  # Send Slack notification when message is acknowledged
    notify_mention_format: Literal["real_name", "display_name", "agent_name"]
    # Bidirectional sync
    sync_enabled: bool  # Enable bidirectional message sync
    sync_project_name: str  # Project used for Slack sync threads
    sync_channels: list[str]  # Channel IDs to sync messages from
    sync_thread_replies: bool  # Sync threaded replies as thread_id in MCP
    sync_reactions: bool  # Track reactions as acknowledgments
    # Advanced features
    use_blocks: bool  # Use Slack Block Kit for rich formatting
    include_attachments: bool  # Include MCP message attachments in Slack
    webhook_url: str | None  # Optional incoming webhook URL (legacy)
    # Slackbox (legacy outgoing webhook ingestion)
    slackbox_enabled: bool  # Accept Slack outgoing webhook payloads
    slackbox_token: str | None  # Verification token from Slack outgoing webhook
    slackbox_channels: list[str]  # Allowed channel IDs or names
    slackbox_sender_name: str  # Name for the synthetic sender agent
    slackbox_subject_prefix: str  # Prefix to apply to Slackbox-derived subjects


@dataclass(slots=True, frozen=True)
class Settings:
    """Top-level application settings."""

    environment: str
    http: HttpSettings
    database: DatabaseSettings
    storage: StorageSettings
    cors: CorsSettings
    llm: LlmSettings
    slack: SlackSettings
    # Background maintenance toggles
    file_reservations_cleanup_enabled: bool
    file_reservations_cleanup_interval_seconds: int
    file_reservation_inactivity_seconds: int
    file_reservation_activity_grace_seconds: int
    # Server-side enforcement
    file_reservations_enforcement_enabled: bool
    # Ack TTL warnings
    ack_ttl_enabled: bool
    ack_ttl_seconds: int
    ack_ttl_scan_interval_seconds: int
    # Ack escalation
    ack_escalation_enabled: bool
    ack_escalation_mode: str  # "log" | "file_reservation"
    ack_escalation_claim_ttl_seconds: int
    ack_escalation_claim_exclusive: bool
    ack_escalation_claim_holder_name: str
    # Logging
    log_rich_enabled: bool
    log_level: str
    log_include_trace: bool
    log_json_enabled: bool
    # Tools logging
    tools_log_enabled: bool
    # Tool metrics emission
    tool_metrics_emit_enabled: bool
    tool_metrics_emit_interval_seconds: int
    # Retention/quota reporting (non-destructive)
    retention_report_enabled: bool
    retention_report_interval_seconds: int
    retention_max_age_days: int
    quota_enabled: bool
    quota_attachments_limit_bytes: int
    quota_inbox_limit_count: int
    # Retention/project listing filters
    retention_ignore_project_patterns: list[str]
    # Agent identity naming policy
    # Values: "strict" | "coerce" | "always_auto"
    # - strict: reject invalid provided names (current hard-fail behavior)
    # - coerce: ignore invalid provided names and auto-generate a valid one (default)
    # - always_auto: ignore any provided name and always auto-generate
    agent_name_enforcement_mode: str
    # Messaging ergonomics
    # When true, attempt to register missing local recipients during send_message
    messaging_auto_register_recipients: bool
    # Tool exposure mode: "extended" (all 27 tools, ~25k tokens) | "core" (8 core + 2 meta tools, ~10k tokens)
    tools_mode: str
    # Worktree + guard configuration
    worktrees_enabled: bool
    project_identity_mode: str
    project_identity_remote: str


def _bool(value: str, *, default: bool) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n"}:
        return False
    return default


def _int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    environment = _decouple_config("APP_ENVIRONMENT", default="development")

    def _csv(name: str, default: str) -> list[str]:
        # Use credentials-aware precedence (env > credentials.json > .env > default)
        raw = _get_config_value(name, default=default)
        items = [part.strip() for part in raw.split(",") if part.strip()]
        return items

    http_settings = HttpSettings(
        host=_decouple_config("HTTP_HOST", default="127.0.0.1"),
        port=_int(_decouple_config("HTTP_PORT", default="8765"), default=8765),
        path=_decouple_config("HTTP_PATH", default="/mcp/"),
        bearer_token=_decouple_config("HTTP_BEARER_TOKEN", default="") or None,
        rate_limit_enabled=_bool(_decouple_config("HTTP_RATE_LIMIT_ENABLED", default="false"), default=False),
        rate_limit_per_minute=_int(_decouple_config("HTTP_RATE_LIMIT_PER_MINUTE", default="60"), default=60),
        rate_limit_slack_per_minute=_int(
            _decouple_config("HTTP_RATE_LIMIT_SLACK_PER_MINUTE", default="120"), default=120
        ),
        rate_limit_slackbox_per_minute=_int(
            _decouple_config("HTTP_RATE_LIMIT_SLACKBOX_PER_MINUTE", default="120"), default=120
        ),
        rate_limit_backend=_decouple_config("HTTP_RATE_LIMIT_BACKEND", default="memory").lower(),
        rate_limit_tools_per_minute=_int(
            _decouple_config("HTTP_RATE_LIMIT_TOOLS_PER_MINUTE", default="60"), default=60
        ),
        rate_limit_resources_per_minute=_int(
            _decouple_config("HTTP_RATE_LIMIT_RESOURCES_PER_MINUTE", default="120"), default=120
        ),
        rate_limit_redis_url=_decouple_config("HTTP_RATE_LIMIT_REDIS_URL", default=""),
        rate_limit_tools_burst=_int(_decouple_config("HTTP_RATE_LIMIT_TOOLS_BURST", default="0"), default=0),
        rate_limit_resources_burst=_int(_decouple_config("HTTP_RATE_LIMIT_RESOURCES_BURST", default="0"), default=0),
        rate_limit_slack_burst=_int(_decouple_config("HTTP_RATE_LIMIT_SLACK_BURST", default="0"), default=0),
        rate_limit_slackbox_burst=_int(_decouple_config("HTTP_RATE_LIMIT_SLACKBOX_BURST", default="0"), default=0),
        request_log_enabled=_bool(_decouple_config("HTTP_REQUEST_LOG_ENABLED", default="false"), default=False),
        otel_enabled=_bool(_decouple_config("HTTP_OTEL_ENABLED", default="false"), default=False),
        otel_service_name=_decouple_config("OTEL_SERVICE_NAME", default="mcp-agent-mail"),
        otel_exporter_otlp_endpoint=_decouple_config("OTEL_EXPORTER_OTLP_ENDPOINT", default=""),
        jwt_enabled=_bool(_decouple_config("HTTP_JWT_ENABLED", default="false"), default=False),
        jwt_algorithms=_csv("HTTP_JWT_ALGORITHMS", default="HS256"),
        jwt_secret=_decouple_config("HTTP_JWT_SECRET", default="") or None,
        jwt_jwks_url=_decouple_config("HTTP_JWT_JWKS_URL", default="") or None,
        jwt_audience=_decouple_config("HTTP_JWT_AUDIENCE", default="") or None,
        jwt_issuer=_decouple_config("HTTP_JWT_ISSUER", default="") or None,
        jwt_role_claim=_decouple_config("HTTP_JWT_ROLE_CLAIM", default="role") or "role",
        rbac_enabled=_bool(_decouple_config("HTTP_RBAC_ENABLED", default="true"), default=True),
        rbac_reader_roles=_csv("HTTP_RBAC_READER_ROLES", default="reader,read,ro"),
        rbac_writer_roles=_csv("HTTP_RBAC_WRITER_ROLES", default="writer,write,tools,rw"),
        rbac_default_role=_decouple_config("HTTP_RBAC_DEFAULT_ROLE", default="reader"),
        rbac_readonly_tools=_csv(
            "HTTP_RBAC_READONLY_TOOLS",
            default="health_check,fetch_inbox,whois,search_messages,summarize_thread,summarize_threads",
        ),
        allow_localhost_unauthenticated=_bool(
            _decouple_config("HTTP_ALLOW_LOCALHOST_UNAUTHENTICATED", default="true"), default=True
        ),
    )

    database_settings = DatabaseSettings(
        # Store SQLite database inside .mcp_mail/ alongside Git archive
        url=_decouple_config("DATABASE_URL", default="sqlite+aiosqlite:///./.mcp_mail/storage.sqlite3"),
        echo=_bool(_decouple_config("DATABASE_ECHO", default="false"), default=False),
    )

    storage_settings = StorageSettings(
        # Default to project-local storage (committed to git) for transparency
        root=_decouple_config("STORAGE_ROOT", default=".mcp_mail"),
        git_author_name=_decouple_config("GIT_AUTHOR_NAME", default="mcp-agent"),
        git_author_email=_decouple_config("GIT_AUTHOR_EMAIL", default="mcp-agent@example.com"),
        inline_image_max_bytes=_int(
            _decouple_config("INLINE_IMAGE_MAX_BYTES", default=str(64 * 1024)), default=64 * 1024
        ),
        convert_images=_bool(_decouple_config("CONVERT_IMAGES", default="true"), default=True),
        keep_original_images=_bool(_decouple_config("KEEP_ORIGINAL_IMAGES", default="false"), default=False),
    )

    cors_settings = CorsSettings(
        enabled=_bool(_decouple_config("HTTP_CORS_ENABLED", default="false"), default=False),
        origins=_csv("HTTP_CORS_ORIGINS", default=""),
        allow_credentials=_bool(_decouple_config("HTTP_CORS_ALLOW_CREDENTIALS", default="false"), default=False),
        allow_methods=_csv("HTTP_CORS_ALLOW_METHODS", default="*"),
        allow_headers=_csv("HTTP_CORS_ALLOW_HEADERS", default="*"),
    )

    def _float(value: str, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    llm_settings = LlmSettings(
        enabled=_bool(_decouple_config("LLM_ENABLED", default="true"), default=True),
        default_model=_decouple_config("LLM_DEFAULT_MODEL", default="gpt-5-mini"),
        temperature=_float(_decouple_config("LLM_TEMPERATURE", default="0.2"), default=0.2),
        max_tokens=_int(_decouple_config("LLM_MAX_TOKENS", default="512"), default=512),
        cache_enabled=_bool(_decouple_config("LLM_CACHE_ENABLED", default="true"), default=True),
        cache_backend=_decouple_config("LLM_CACHE_BACKEND", default="memory"),
        cache_redis_url=_decouple_config("LLM_CACHE_REDIS_URL", default=""),
        cost_logging_enabled=_bool(_decouple_config("LLM_COST_LOGGING_ENABLED", default="true"), default=True),
    )

    raw_mention_format = _get_config_value("SLACK_NOTIFY_MENTION_FORMAT", default="agent_name").strip().lower()
    allowed_mention_formats: tuple[Literal["real_name", "display_name", "agent_name"], ...] = (
        "real_name",
        "display_name",
        "agent_name",
    )
    mention_format = cast(
        Literal["real_name", "display_name", "agent_name"],
        raw_mention_format if raw_mention_format in allowed_mention_formats else "agent_name",
    )

    slack_settings = SlackSettings(
        enabled=_bool(_get_config_value("SLACK_ENABLED", default="false"), default=False),
        bot_token=_get_config_value("SLACK_BOT_TOKEN", default="") or None,
        app_token=_get_config_value("SLACK_APP_TOKEN", default="") or None,
        signing_secret=_get_config_value("SLACK_SIGNING_SECRET", default="") or None,
        default_channel=_get_config_value("SLACK_DEFAULT_CHANNEL", default="general"),
        notify_on_message=_bool(_get_config_value("SLACK_NOTIFY_ON_MESSAGE", default="true"), default=True),
        notify_on_ack=_bool(_get_config_value("SLACK_NOTIFY_ON_ACK", default="false"), default=False),
        notify_mention_format=mention_format,
        sync_enabled=_bool(_get_config_value("SLACK_SYNC_ENABLED", default="false"), default=False),
        sync_project_name=_get_config_value("SLACK_SYNC_PROJECT_NAME", default="Slack Sync"),
        sync_channels=_csv("SLACK_SYNC_CHANNELS", default=""),
        sync_thread_replies=_bool(_get_config_value("SLACK_SYNC_THREAD_REPLIES", default="true"), default=True),
        sync_reactions=_bool(_get_config_value("SLACK_SYNC_REACTIONS", default="true"), default=True),
        use_blocks=_bool(_get_config_value("SLACK_USE_BLOCKS", default="true"), default=True),
        include_attachments=_bool(_get_config_value("SLACK_INCLUDE_ATTACHMENTS", default="true"), default=True),
        webhook_url=_get_config_value("SLACK_WEBHOOK_URL", default="") or None,
        slackbox_enabled=_bool(_get_config_value("SLACKBOX_ENABLED", default="false"), default=False),
        slackbox_token=_get_config_value("SLACKBOX_TOKEN", default="") or None,
        slackbox_channels=_csv("SLACKBOX_CHANNELS", default=""),
        slackbox_sender_name=_get_config_value("SLACKBOX_SENDER_NAME", default="Slackbox"),
        slackbox_subject_prefix=_get_config_value("SLACKBOX_SUBJECT_PREFIX", default="[Slackbox]"),
    )

    def _agent_name_mode(value: str) -> str:
        v = (value or "").strip().lower()
        if v in {"strict", "coerce", "always_auto"}:
            return v
        return "coerce"

    def _tools_mode(value: str) -> str:
        v = (value or "").strip().lower()
        if v in {"extended", "core"}:
            return v
        return "core"

    return Settings(
        environment=environment,
        http=http_settings,
        database=database_settings,
        storage=storage_settings,
        cors=cors_settings,
        llm=llm_settings,
        slack=slack_settings,
        file_reservations_cleanup_enabled=_bool(
            _decouple_config("FILE_RESERVATIONS_CLEANUP_ENABLED", default="false"), default=False
        ),
        file_reservations_cleanup_interval_seconds=_int(
            _decouple_config("FILE_RESERVATIONS_CLEANUP_INTERVAL_SECONDS", default="60"), default=60
        ),
        file_reservation_inactivity_seconds=_int(
            _decouple_config("FILE_RESERVATION_INACTIVITY_SECONDS", default="1800"), default=1800
        ),
        file_reservation_activity_grace_seconds=_int(
            _decouple_config("FILE_RESERVATION_ACTIVITY_GRACE_SECONDS", default="900"), default=900
        ),
        file_reservations_enforcement_enabled=_bool(
            _decouple_config("FILE_RESERVATIONS_ENFORCEMENT_ENABLED", default="true"), default=True
        ),
        ack_ttl_enabled=_bool(_decouple_config("ACK_TTL_ENABLED", default="false"), default=False),
        ack_ttl_seconds=_int(_decouple_config("ACK_TTL_SECONDS", default="1800"), default=1800),
        ack_ttl_scan_interval_seconds=_int(_decouple_config("ACK_TTL_SCAN_INTERVAL_SECONDS", default="60"), default=60),
        ack_escalation_enabled=_bool(_decouple_config("ACK_ESCALATION_ENABLED", default="false"), default=False),
        ack_escalation_mode=_decouple_config("ACK_ESCALATION_MODE", default="log"),
        ack_escalation_claim_ttl_seconds=_int(
            _decouple_config("ACK_ESCALATION_CLAIM_TTL_SECONDS", default="3600"), default=3600
        ),
        ack_escalation_claim_exclusive=_bool(
            _decouple_config("ACK_ESCALATION_CLAIM_EXCLUSIVE", default="false"), default=False
        ),
        ack_escalation_claim_holder_name=_decouple_config("ACK_ESCALATION_CLAIM_HOLDER_NAME", default=""),
        tools_log_enabled=_bool(_decouple_config("TOOLS_LOG_ENABLED", default="true"), default=True),
        log_rich_enabled=_bool(_decouple_config("LOG_RICH_ENABLED", default="true"), default=True),
        log_level=_decouple_config("LOG_LEVEL", default="INFO"),
        log_include_trace=_bool(_decouple_config("LOG_INCLUDE_TRACE", default="false"), default=False),
        log_json_enabled=_bool(_decouple_config("LOG_JSON_ENABLED", default="false"), default=False),
        tool_metrics_emit_enabled=_bool(_decouple_config("TOOL_METRICS_EMIT_ENABLED", default="false"), default=False),
        tool_metrics_emit_interval_seconds=_int(
            _decouple_config("TOOL_METRICS_EMIT_INTERVAL_SECONDS", default="60"), default=60
        ),
        retention_report_enabled=_bool(_decouple_config("RETENTION_REPORT_ENABLED", default="false"), default=False),
        retention_report_interval_seconds=_int(
            _decouple_config("RETENTION_REPORT_INTERVAL_SECONDS", default="3600"), default=3600
        ),
        retention_max_age_days=_int(_decouple_config("RETENTION_MAX_AGE_DAYS", default="180"), default=180),
        quota_enabled=_bool(_decouple_config("QUOTA_ENABLED", default="false"), default=False),
        quota_attachments_limit_bytes=_int(_decouple_config("QUOTA_ATTACHMENTS_LIMIT_BYTES", default="0"), default=0),
        quota_inbox_limit_count=_int(_decouple_config("QUOTA_INBOX_LIMIT_COUNT", default="0"), default=0),
        retention_ignore_project_patterns=_csv(
            "RETENTION_IGNORE_PROJECT_PATTERNS",
            default="demo,test*,testproj*,testproject,backendproj*,frontendproj*",
        ),
        agent_name_enforcement_mode=_agent_name_mode(_decouple_config("AGENT_NAME_ENFORCEMENT_MODE", default="coerce")),
        messaging_auto_register_recipients=_bool(
            _decouple_config("MESSAGING_AUTO_REGISTER_RECIPIENTS", default="true"), default=True
        ),
        tools_mode=_tools_mode(_decouple_config("MCP_TOOLS_MODE", default="")),
        worktrees_enabled=_bool(_decouple_config("WORKTREES_ENABLED", default="0"), default=False),
        project_identity_mode=_decouple_config("PROJECT_IDENTITY_MODE", default="dir") or "dir",
        project_identity_remote=_decouple_config("PROJECT_IDENTITY_REMOTE", default="origin") or "origin",
    )


def clear_settings_cache() -> None:
    """Clear the lru_cache for get_settings in a mypy-friendly way."""
    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
