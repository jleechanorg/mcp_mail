"""Async database engine and session management utilities."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from .config import DatabaseSettings, Settings, get_settings

T = TypeVar("T")

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_schema_ready = False
_schema_lock: asyncio.Lock | None = None


def retry_on_db_lock(max_retries: int = 5, base_delay: float = 0.1, max_delay: float = 5.0):
    """Decorator to retry async functions on SQLite database lock errors with exponential backoff + jitter.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds (will be exponentially increased)
        max_delay: Maximum delay between retries in seconds

    This handles transient "database is locked" errors from SQLite by:
    1. Catching OperationalError with lock-related messages
    2. Waiting with exponential backoff: base_delay * (2 ** attempt)
    3. Adding jitter to prevent thundering herd: random ±25% of delay
    4. Giving up after max_retries and re-raising the error
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except OperationalError as e:
                    # Check if it's a lock-related error
                    error_msg = str(e).lower()
                    is_lock_error = any(
                        phrase in error_msg for phrase in ["database is locked", "database is busy", "locked"]
                    )

                    if not is_lock_error or attempt >= max_retries:
                        # Not a lock error, or we've exhausted retries - raise it
                        raise

                    last_exception = e

                    # Calculate exponential backoff with jitter
                    delay = min(base_delay * (2**attempt), max_delay)
                    jitter = delay * 0.25 * (2 * random.random() - 1)  # ±25% jitter
                    total_delay = delay + jitter

                    func_name = getattr(func, "__name__", getattr(func, "__qualname__", "<callable>"))
                    logger.warning(
                        f"Database locked, retrying {func_name} "
                        f"(attempt {attempt + 1}/{max_retries}) after {total_delay:.2f}s"
                    )

                    await asyncio.sleep(total_delay)

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry loop exit")

        return wrapper

    return decorator


def _build_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build async SQLAlchemy engine with SQLite-optimized settings for concurrency."""
    from sqlalchemy import event

    # For SQLite, enable WAL mode and set timeout for better concurrent access
    connect_args = {}
    is_sqlite = "sqlite" in settings.url.lower()

    if is_sqlite:
        # Register datetime adapters ONCE globally for Python 3.12+ compatibility
        # These are module-level registrations, not per-connection
        import datetime as dt_module
        import sqlite3

        def adapt_datetime_iso(val):
            """Adapt datetime.datetime to ISO 8601 date."""
            return val.isoformat()

        def convert_datetime(val):
            """Convert ISO 8601 datetime to datetime.datetime object.

            Returns None for any conversion errors (invalid format, wrong type,
            corrupted data, etc.) to allow graceful degradation rather than crashing.
            """
            try:
                # Handle both bytes and str (SQLite can return either)
                if isinstance(val, bytes):
                    val = val.decode("utf-8")
                return dt_module.datetime.fromisoformat(val)
            except (ValueError, AttributeError, TypeError, UnicodeDecodeError, OverflowError):
                # Return None for any conversion failure:
                # - ValueError: invalid ISO format string
                # - TypeError: unexpected type (shouldn't happen but defensive)
                # - AttributeError: val has no expected attributes (defensive)
                # - UnicodeDecodeError: corrupted bytes (extreme edge case)
                # - OverflowError: datetime value out of valid range (year outside 1-9999)
                return None

        # Register adapters globally (safe to call multiple times - last registration wins)
        sqlite3.register_adapter(dt_module.datetime, adapt_datetime_iso)
        sqlite3.register_converter("timestamp", convert_datetime)

        connect_args = {
            "timeout": 60.0,  # Increased from 30 to 60 seconds for lock wait (default is 5)
            "check_same_thread": False,  # Required for async SQLite
        }

    engine = create_async_engine(
        settings.url,
        echo=settings.echo,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        connect_args=connect_args,
    )

    # For SQLite: Set up event listener to configure each connection with WAL mode
    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:  # pragma: no cover - db hook
            """Set SQLite PRAGMAs for better concurrent performance on each connection."""
            cursor = dbapi_conn.cursor()
            # Enable WAL mode for concurrent reads/writes
            cursor.execute("PRAGMA journal_mode=WAL")
            # Use NORMAL synchronous mode (safer than OFF, faster than FULL)
            cursor.execute("PRAGMA synchronous=NORMAL")
            # Set busy timeout (wait up to 60 seconds for locks, increased from 30)
            cursor.execute("PRAGMA busy_timeout=60000")
            # Enforce foreign key constraints (SQLite defaults to OFF)
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def init_engine(settings: Settings | None = None) -> None:
    """Initialise global engine and session factory once."""
    global _engine, _session_factory
    if _engine is not None and _session_factory is not None:
        return
    resolved_settings = settings or get_settings()
    engine = _build_engine(resolved_settings.database)
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


@retry_on_db_lock(max_retries=5, base_delay=0.1, max_delay=5.0)
async def ensure_schema(settings: Settings | None = None) -> None:
    """Ensure database schema exists (creates tables from SQLModel definitions).

    This is the pure SQLModel approach:
    - Models define the schema
    - create_all() creates tables that don't exist yet
    - For schema changes: delete the DB and regenerate (dev) or use Alembic (prod)

    Also enables SQLite WAL mode for better concurrent access.
    """
    global _schema_ready, _schema_lock
    if _schema_ready:
        return
    if _schema_lock is None:
        _schema_lock = asyncio.Lock()
    async with _schema_lock:
        if _schema_ready:
            return
        init_engine(settings)
        engine = get_engine()
        async with engine.begin() as conn:
            # Pure SQLModel: create tables from metadata
            # (WAL mode is set automatically via event listener in _build_engine)
            await conn.run_sync(SQLModel.metadata.create_all)
            # Setup FTS and custom indexes
            await conn.run_sync(_setup_fts)
        _schema_ready = True


def reset_database_state() -> None:
    """Test helper to reset global engine/session state."""
    global _engine, _session_factory, _schema_ready, _schema_lock
    _engine = None
    _session_factory = None
    _schema_ready = False
    _schema_lock = None


def _check_and_fix_duplicate_agent_names(connection) -> None:
    """Check for duplicate ACTIVE agent names and auto-rename to ensure global uniqueness.

    This handles migration from the old schema (per-project uniqueness) to the new schema
    (global uniqueness). Only considers active agents - inactive agents don't conflict.
    """
    # Find all duplicate names among ACTIVE agents only (case-insensitive)
    cursor = connection.exec_driver_sql(
        """
        SELECT lower(name) as name_lower, COUNT(*) as count
        FROM agents
        WHERE is_active = 1
        GROUP BY name_lower
        HAVING count > 1
        """
    )
    duplicates = cursor.fetchall()

    if not duplicates:
        return  # No duplicates among active agents, safe to proceed

    logger.warning(
        f"Found {len(duplicates)} active agent name(s) with duplicates. Auto-renaming for global uniqueness..."
    )

    for name_lower, _count in duplicates:
        # Get all ACTIVE agents with this name
        cursor = connection.exec_driver_sql(
            """
            SELECT id, name, project_id
            FROM agents
            WHERE lower(name) = ? AND is_active = 1
            ORDER BY id
            """,
            (name_lower,),
        )
        agents = cursor.fetchall()

        # Keep first occurrence, rename others
        for i, (agent_id, original_name, project_id) in enumerate(agents):
            if i == 0:
                logger.info(f"  Keeping original: {original_name} (id={agent_id}, project_id={project_id})")
                continue

            # Generate new name by appending number (respecting 128-char limit)
            max_name_length = 128  # keep in sync with Agent.name max_length
            suffix = 2
            while True:
                suffix_str = str(suffix)
                # Trim base name to leave room for suffix
                trimmed_name = original_name[: max_name_length - len(suffix_str)]
                new_name = f"{trimmed_name}{suffix_str}"
                # Check if this new name exists among active agents
                check = connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM agents WHERE lower(name) = lower(?) AND is_active = 1",
                    (new_name,),
                ).fetchone()[0]
                if check == 0:
                    break
                suffix += 1

            # Rename the agent
            connection.exec_driver_sql(
                "UPDATE agents SET name = ? WHERE id = ?",
                (new_name, agent_id),
            )
            logger.info(f"  Renamed: {original_name} → {new_name} (id={agent_id}, project_id={project_id})")


def _setup_fts(connection) -> None:
    _ensure_agent_active_columns(connection)
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_messages USING fts5(message_id UNINDEXED, subject, body)"
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS fts_messages_ai
        AFTER INSERT ON messages
        BEGIN
            INSERT INTO fts_messages(rowid, message_id, subject, body)
            VALUES (new.id, new.id, new.subject, new.body_md);
        END;
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS fts_messages_ad
        AFTER DELETE ON messages
        BEGIN
            DELETE FROM fts_messages WHERE rowid = old.id;
        END;
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS fts_messages_au
        AFTER UPDATE ON messages
        BEGIN
            DELETE FROM fts_messages WHERE rowid = old.id;
            INSERT INTO fts_messages(rowid, message_id, subject, body)
            VALUES (new.id, new.id, new.subject, new.body_md);
        END;
        """
    )
    # Additional performance indexes for common access patterns
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_messages_created_ts ON messages(created_ts)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_messages_importance ON messages(importance)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_file_reservations_expires_ts ON file_reservations(expires_ts)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_message_recipients_agent ON message_recipients(agent_id)"
    )
    # Composite index for optimized inbox queries (agent_id + message_id for joins)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_message_recipients_agent_msg ON message_recipients(agent_id, message_id)"
    )
    # Composite index for timestamp-ordered queries (created_ts DESC, id for tie-breaking)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_messages_created_ts_desc_id ON messages(created_ts DESC, id)"
    )

    # MIGRATION: Check for duplicate agent names before enforcing global uniqueness
    # This handles upgrading from per-project uniqueness to global uniqueness
    _check_and_fix_duplicate_agent_names(connection)

    # Case-insensitive unique index on ACTIVE agent names for global uniqueness
    connection.exec_driver_sql("DROP INDEX IF EXISTS uq_agents_name_ci")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agents_name_ci ON agents(lower(name)) WHERE is_active = 1"
    )


def _ensure_agent_active_columns(connection) -> None:
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info('agents')").fetchall()}
    if "is_active" not in columns:
        connection.exec_driver_sql("ALTER TABLE agents ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "deleted_ts" not in columns:
        connection.exec_driver_sql("ALTER TABLE agents ADD COLUMN deleted_ts TEXT")
    if "contact_policy" not in columns:
        connection.exec_driver_sql("ALTER TABLE agents ADD COLUMN contact_policy TEXT NOT NULL DEFAULT 'auto'")
    if "is_placeholder" not in columns:
        # Add is_placeholder column for tracking agents auto-created before official registration.
        # Existing agents are assumed to be officially registered (is_placeholder=0).
        connection.exec_driver_sql("ALTER TABLE agents ADD COLUMN is_placeholder INTEGER NOT NULL DEFAULT 0")
    connection.exec_driver_sql("UPDATE agents SET is_active = 1 WHERE is_active IS NULL")
    connection.exec_driver_sql("UPDATE agents SET contact_policy = 'auto' WHERE contact_policy IS NULL")

    # MIGRATION v0.2.0: Make project_id nullable on agents and messages tables
    # This allows agents and messages to exist without project context
    _migrate_project_id_nullable(connection)


def _migrate_project_id_nullable(connection) -> None:
    """Migrate agents and messages tables to make project_id nullable.

    SQLite doesn't support ALTER COLUMN, so we need to recreate tables.
    This migration:
    1. Checks if project_id is NOT NULL (needs migration)
    2. Recreates table with nullable project_id
    3. Copies all data
    4. Drops old table and renames new one

    Existing data retains its project_id values; new records can have NULL.
    """
    # Check if agents.project_id is NOT NULL
    agents_info = connection.exec_driver_sql("PRAGMA table_info('agents')").fetchall()
    agents_project_id_notnull = False
    for col in agents_info:
        # col format: (cid, name, type, notnull, dflt_value, pk)
        if col[1] == "project_id" and col[3] == 1:  # notnull == 1
            agents_project_id_notnull = True
            break

    if agents_project_id_notnull:
        logger.info("Migrating agents table: making project_id nullable...")
        _recreate_agents_table_nullable_project_id(connection)
        logger.info("agents table migration complete")

    # Check if messages.project_id is NOT NULL
    messages_info = connection.exec_driver_sql("PRAGMA table_info('messages')").fetchall()
    messages_project_id_notnull = False
    for col in messages_info:
        if col[1] == "project_id" and col[3] == 1:
            messages_project_id_notnull = True
            break

    if messages_project_id_notnull:
        logger.info("Migrating messages table: making project_id nullable...")
        _recreate_messages_table_nullable_project_id(connection)
        logger.info("messages table migration complete")


def _recreate_agents_table_nullable_project_id(connection) -> None:
    """Recreate agents table with nullable project_id."""
    # Clean up orphaned project references so FK enforcement does not break migration
    orphaned_projects_result = connection.exec_driver_sql(
        """
        SELECT COUNT(*)
        FROM agents a
        LEFT JOIN projects p ON p.id = a.project_id
        WHERE a.project_id IS NOT NULL
          AND p.id IS NULL
        """
    )
    orphaned_projects = orphaned_projects_result.scalar_one()
    if orphaned_projects:
        logger.warning(
            "Found %s agent(s) with orphaned project_id; setting project_id to NULL before migration",
            orphaned_projects,
        )
        connection.exec_driver_sql(
            """
            UPDATE agents
            SET project_id = NULL
            WHERE project_id IS NOT NULL
              AND project_id NOT IN (SELECT id FROM projects)
            """
        )

    invalid_count_result = connection.exec_driver_sql(
        """
        SELECT COUNT(*)
        FROM agents
        WHERE name IS NULL OR program IS NULL OR model IS NULL
        """
    )
    invalid_count = invalid_count_result.scalar_one()
    if invalid_count > 0:
        raise RuntimeError("Cannot migrate agents table: rows contain NULL in required columns (name/program/model).")
    # Create new table with nullable project_id
    connection.exec_driver_sql(
        """
        CREATE TABLE agents_new (
            id INTEGER PRIMARY KEY,
            project_id INTEGER REFERENCES projects(id),
            name VARCHAR(128) NOT NULL,
            program VARCHAR(128) NOT NULL,
            model VARCHAR(128) NOT NULL,
            task_description VARCHAR(2048) DEFAULT '',
            inception_ts TIMESTAMP,
            last_active_ts TIMESTAMP,
            attachments_policy VARCHAR(16) DEFAULT 'auto',
            contact_policy VARCHAR(16) DEFAULT 'auto',
            is_active INTEGER DEFAULT 1,
            deleted_ts TIMESTAMP,
            is_placeholder INTEGER DEFAULT 0
        )
        """
    )

    # Copy data from old table
    try:
        connection.exec_driver_sql(
            """
            INSERT INTO agents_new (
                id, project_id, name, program, model, task_description,
                inception_ts, last_active_ts, attachments_policy, contact_policy,
                is_active, deleted_ts, is_placeholder
            )
            SELECT
                id, project_id, name, program, model, task_description,
                inception_ts, last_active_ts, attachments_policy, contact_policy,
                is_active, deleted_ts, is_placeholder
            FROM agents
            """
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        raise RuntimeError("Failed to migrate data from agents to agents_new") from exc

    # Drop old table and rename new one
    # Disable FK enforcement temporarily to allow DROP (other tables reference agents)
    connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
    connection.exec_driver_sql("DROP TABLE agents")
    connection.exec_driver_sql("ALTER TABLE agents_new RENAME TO agents")
    connection.exec_driver_sql("PRAGMA foreign_keys = ON")

    # Recreate indexes
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_agents_project_id ON agents(project_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_agents_name ON agents(name)")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agents_name_ci ON agents(lower(name)) WHERE is_active = 1"
    )


def _recreate_messages_table_nullable_project_id(connection) -> None:
    """Recreate messages table with nullable project_id."""
    # Clean up orphaned project references so FK enforcement does not break migration
    orphaned_projects_result = connection.exec_driver_sql(
        """
        SELECT COUNT(*)
        FROM messages m
        LEFT JOIN projects p ON p.id = m.project_id
        WHERE m.project_id IS NOT NULL
          AND p.id IS NULL
        """
    )
    orphaned_projects = orphaned_projects_result.scalar_one()
    if orphaned_projects:
        logger.warning(
            "Found %s message(s) with orphaned project_id; setting project_id to NULL before migration",
            orphaned_projects,
        )
        connection.exec_driver_sql(
            """
            UPDATE messages
            SET project_id = NULL
            WHERE project_id IS NOT NULL
              AND project_id NOT IN (SELECT id FROM projects)
            """
        )

    # Validate sender references remain resolvable once FK enforcement is applied
    orphaned_senders_result = connection.exec_driver_sql(
        """
        SELECT COUNT(*)
        FROM messages m
        LEFT JOIN agents a ON a.id = m.sender_id
        WHERE a.id IS NULL
        """
    )
    orphaned_senders = orphaned_senders_result.scalar_one()
    if orphaned_senders:
        raise RuntimeError(
            "Cannot migrate messages table: sender_id references missing agents "
            f"({orphaned_senders} orphaned row(s)). Please recreate the referenced agents "
            "or remove the invalid rows before retrying."
        )

    invalid_count_result = connection.exec_driver_sql(
        """
        SELECT COUNT(*)
        FROM messages
        WHERE sender_id IS NULL
           OR subject IS NULL
           OR body_md IS NULL
        """
    )
    invalid_count = invalid_count_result.scalar_one()
    if invalid_count > 0:
        raise RuntimeError(
            "Cannot migrate messages table: NULL values found in required columns (sender_id/subject/body_md)."
        )
    # Create new table with nullable project_id
    connection.exec_driver_sql(
        """
        CREATE TABLE messages_new (
            id INTEGER PRIMARY KEY,
            project_id INTEGER REFERENCES projects(id),
            sender_id INTEGER NOT NULL REFERENCES agents(id),
            thread_id VARCHAR(128),
            subject VARCHAR(512) NOT NULL,
            body_md TEXT NOT NULL,
            importance VARCHAR(16) DEFAULT 'normal',
            ack_required INTEGER DEFAULT 0,
            created_ts TIMESTAMP,
            attachments JSON DEFAULT '[]'
        )
        """
    )

    # Copy data from old table
    try:
        connection.exec_driver_sql(
            """
            INSERT INTO messages_new (
                id, project_id, sender_id, thread_id, subject, body_md,
                importance, ack_required, created_ts, attachments
            )
            SELECT
                id, project_id, sender_id, thread_id, subject, body_md,
                importance, ack_required, created_ts, attachments
            FROM messages
            """
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        raise RuntimeError("Failed to migrate data from messages to messages_new") from exc

    # Drop old table and rename new one
    # Disable FK enforcement temporarily to allow DROP (message_recipients references messages)
    connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
    connection.exec_driver_sql("DROP TABLE messages")
    connection.exec_driver_sql("ALTER TABLE messages_new RENAME TO messages")
    connection.exec_driver_sql("PRAGMA foreign_keys = ON")

    # Recreate indexes
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_messages_project_id ON messages(project_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_messages_sender_id ON messages(sender_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_messages_thread_id ON messages(thread_id)")
