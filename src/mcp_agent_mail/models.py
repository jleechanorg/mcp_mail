"""SQLModel data models representing agents, messages, projects, and file reservations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=255)
    human_key: str = Field(max_length=255, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Agent(SQLModel, table=True):
    __tablename__ = "agents"
    # BREAKING CHANGE: Agent names are now globally unique across all projects (case-insensitive)
    #
    # Previous behavior: Names were unique per-project; "Alice" could exist in multiple projects
    # New behavior: "Alice" can only exist once across ALL projects; "alice" and "Alice" are considered the same
    #
    # Enforcement: Global case-insensitive uniqueness via functional index uq_agents_name_ci in db.py (_setup_fts)
    # Migration: Existing duplicate names are auto-renamed with numeric suffixes (Alice → Alice2, Alice3, etc.)
    # Race handling: IntegrityError is caught and converted to ValueError with clear user-facing message

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    name: str = Field(index=True, max_length=128)
    program: str = Field(max_length=128)
    model: str = Field(max_length=128)
    task_description: str = Field(default="", max_length=2048)
    inception_ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attachments_policy: str = Field(default="auto", max_length=16)
    is_active: bool = Field(default=True)
    deleted_ts: Optional[datetime] = Field(default=None)


class MessageRecipient(SQLModel, table=True):
    __tablename__ = "message_recipients"

    message_id: int = Field(foreign_key="messages.id", primary_key=True)
    agent_id: int = Field(foreign_key="agents.id", primary_key=True)
    kind: str = Field(max_length=8, default="to")
    read_ts: Optional[datetime] = Field(default=None)
    ack_ts: Optional[datetime] = Field(default=None)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    sender_id: int = Field(foreign_key="agents.id", index=True)
    thread_id: Optional[str] = Field(default=None, index=True, max_length=128)
    subject: str = Field(max_length=512)
    body_md: str
    importance: str = Field(default="normal", max_length=16)
    ack_required: bool = Field(default=False)
    created_ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )


class FileReservation(SQLModel, table=True):
    __tablename__ = "file_reservations"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    agent_id: int = Field(foreign_key="agents.id", index=True)
    path_pattern: str = Field(max_length=512)
    exclusive: bool = Field(default=True)
    reason: str = Field(default="", max_length=512)
    created_ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_ts: datetime
    released_ts: Optional[datetime] = None


class ProjectSiblingSuggestion(SQLModel, table=True):
    """LLM-ranked sibling project suggestion (undirected pair)."""

    __tablename__ = "project_sibling_suggestions"
    __table_args__ = (UniqueConstraint("project_a_id", "project_b_id", name="uq_project_sibling_pair"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    project_a_id: int = Field(foreign_key="projects.id", index=True)
    project_b_id: int = Field(foreign_key="projects.id", index=True)
    score: float = Field(default=0.0)
    status: str = Field(default="suggested", max_length=16)  # suggested | confirmed | dismissed
    rationale: str = Field(default="", max_length=4096)
    created_ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluated_ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_ts: Optional[datetime] = Field(default=None)
    dismissed_ts: Optional[datetime] = Field(default=None)
