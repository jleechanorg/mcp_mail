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
    #
    # SCHEMA CHANGE (v0.2.0): project_id is now OPTIONAL (nullable)
    # - Agent names are the primary identifier for routing (globally unique)
    # - project_id is preserved for backwards compatibility and informational purposes
    # - Existing agents keep their project_id; new agents can be created without one

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="projects.id", index=True)
    name: str = Field(index=True, max_length=128)
    program: str = Field(max_length=128)
    model: str = Field(max_length=128)
    task_description: str = Field(default="", max_length=2048)
    inception_ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attachments_policy: str = Field(default="auto", max_length=16)
    contact_policy: str = Field(default="auto", max_length=16)
    is_active: bool = Field(default=True)
    deleted_ts: Optional[datetime] = Field(default=None)
    # True if agent was auto-created when receiving messages before official registration.
    # When officially registered, this is set to False. Placeholder agents can be "claimed"
    # by a later registration call, which updates the agent's program/model/task_description.
    is_placeholder: bool = Field(default=False)


class MessageRecipient(SQLModel, table=True):
    __tablename__ = "message_recipients"

    message_id: int = Field(foreign_key="messages.id", primary_key=True)
    agent_id: int = Field(foreign_key="agents.id", primary_key=True)
    kind: str = Field(max_length=8, default="to")
    read_ts: Optional[datetime] = Field(default=None)
    ack_ts: Optional[datetime] = Field(default=None)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    #
    # SCHEMA CHANGE (v0.2.0): project_id is now OPTIONAL (nullable)
    # - Messages are routed by sender/recipient agent IDs (globally unique agents)
    # - project_id is preserved for backwards compatibility and informational purposes
    # - Existing messages keep their project_id; new messages can be created without one

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="projects.id", index=True)
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
    # NOTE: FileReservation still requires project_id as file reservations are project-scoped

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


class Product(SQLModel, table=True):
    __tablename__ = "products"

    id: Optional[int] = Field(default=None, primary_key=True)
    product_uid: str = Field(index=True, unique=True, max_length=128)
    name: str = Field(index=True, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProductProjectLink(SQLModel, table=True):
    __tablename__ = "product_project_links"
    __table_args__ = (UniqueConstraint("product_id", "project_id", name="uq_product_project"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.id", index=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SlackThreadMapping(SQLModel, table=True):
    """Maps MCP thread IDs to their corresponding Slack thread coordinates.

    When an MCP message is posted to Slack, we store the mapping so that:
    1. Subsequent MCP replies can be posted to the same Slack thread
    2. Slack replies can be routed back to the correct MCP project
    """

    __tablename__ = "slack_thread_mappings"
    __table_args__ = (UniqueConstraint("slack_channel_id", "slack_thread_ts", name="uq_slack_thread"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    # The MCP thread ID (could be message ID as string, or thread_id field value)
    mcp_thread_id: str = Field(max_length=128, index=True)
    # Slack channel where the thread exists
    slack_channel_id: str = Field(max_length=64, index=True)
    # Slack timestamp that identifies the thread (the parent message's ts)
    slack_thread_ts: str = Field(max_length=64, index=True)
    # When this mapping was created
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
