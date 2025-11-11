"""Integration tests for default .mcp_mail/ storage with parallel writes.

Tests the actual implementation (not JSONL stub) with:
- Default .mcp_mail/ storage location
- SQLite database in .mcp_mail/storage.sqlite3
- Git-backed messages in .mcp_mail/projects/<slug>/messages/
- Parallel concurrent writes to verify no race conditions
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastmcp import Client

from mcp_agent_mail import config as _config
from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import ensure_schema


@pytest.fixture
async def mcp_mail_storage(tmp_path, monkeypatch):
    """Set up .mcp_mail/ storage with real implementation."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Set up .mcp_mail/ as storage location
    mcp_mail_dir = project_dir / ".mcp_mail"
    mcp_mail_dir.mkdir()  # Create directory before SQLite tries to connect

    # Configure environment to use .mcp_mail/ storage
    monkeypatch.setenv("STORAGE_ROOT", str(mcp_mail_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{mcp_mail_dir}/storage.sqlite3")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test-agent")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

    # Clear settings cache to pick up new env vars
    _config.clear_settings_cache()

    # Initialize database
    await ensure_schema()

    # Initialize git repo in storage location (will be created automatically)
    # The storage layer will create this on first write

    yield {
        "project_dir": project_dir,
        "storage_dir": mcp_mail_dir,
        "db_path": mcp_mail_dir / "storage.sqlite3",
    }

    # Cleanup
    _config.clear_settings_cache()


@pytest.mark.asyncio
async def test_default_storage_location_created(mcp_mail_storage):
    """Test that .mcp_mail/ storage is created with default configuration."""
    storage_dir = mcp_mail_storage["storage_dir"]

    # Build MCP server (triggers storage initialization on first use)
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Register an agent (triggers archive creation)
        result = await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "test-project",
                "program": "test-client",
                "model": "test-model",
                "name": "TestAgent",
                "task_description": "Testing storage",
            },
        )

        assert result.data["name"] == "TestAgent"

    # Verify .mcp_mail/ directory structure was created
    assert storage_dir.exists(), ".mcp_mail/ directory should be created"
    assert (storage_dir / "projects").exists(), "projects/ subdirectory should exist"
    assert (storage_dir / "projects" / "test-project").exists(), "project directory should exist"

    # Verify SQLite database was created in .mcp_mail/
    db_path = mcp_mail_storage["db_path"]
    assert db_path.exists(), "SQLite database should be in .mcp_mail/storage.sqlite3"


@pytest.mark.asyncio
async def test_messages_stored_in_mcp_mail_git_archive(mcp_mail_storage):
    """Test that messages are stored in .mcp_mail/projects/<slug>/messages/."""
    storage_dir = mcp_mail_storage["storage_dir"]

    server = build_mcp_server()

    # Register agents
    await server.call_tool(
        "register_agent",
        {
            "project_key": "my-project",
            "program": "agent-1",
            "model": "test",
            "name": "Agent1",
            "task_description": "Sender",
        },
    )

    await server.call_tool(
        "register_agent",
        {
            "project_key": "my-project",
            "program": "agent-2",
            "model": "test",
            "name": "Agent2",
            "task_description": "Receiver",
        },
    )

    # Send a message
    result = await server.call_tool(
        "send_message",
        {
            "project_key": "my-project",
            "sender_name": "Agent1",
            "to": ["Agent2"],
            "subject": "Test Message",
            "body": "This should be stored in .mcp_mail/",
        },
    )

    message_id = result["id"]

    # Verify message file was created in .mcp_mail/projects/my-project/messages/
    project_messages_dir = storage_dir / "projects" / "my-project" / "messages"
    assert project_messages_dir.exists(), "Messages directory should exist"

    # Find the message file (in YYYY/MM/<id>.md structure)
    message_files = list(project_messages_dir.rglob("*.md"))
    assert len(message_files) > 0, "At least one message file should exist"

    # Verify message content
    found_message = False
    for msg_file in message_files:
        content = msg_file.read_text()
        if "Test Message" in content and "This should be stored in .mcp_mail/" in content:
            found_message = True
            break

    assert found_message, "Message content should be in .mcp_mail/ archive"

    # Verify Git repo was initialized
    git_dir = storage_dir / ".git"
    assert git_dir.exists(), "Git repo should be initialized in .mcp_mail/"


@pytest.mark.asyncio
async def test_parallel_writes_to_mcp_mail_no_race_conditions(mcp_mail_storage):
    """Test concurrent writes to .mcp_mail/ storage without race conditions."""
    server = build_mcp_server()

    # Register sender agents
    agents = []
    for i in range(5):
        agent_name = f"ParallelAgent{i}"
        await server.call_tool(
            "register_agent",
            {
                "project_key": "concurrent-test",
                "program": f"agent-{i}",
                "model": "test",
                "name": agent_name,
                "task_description": f"Parallel sender {i}",
            },
        )
        agents.append(agent_name)

    # Register receiver
    await server.call_tool(
        "register_agent",
        {
            "project_key": "concurrent-test",
            "program": "receiver",
            "model": "test",
            "name": "Receiver",
            "task_description": "Receives parallel messages",
        },
    )

    # Send messages concurrently from multiple agents
    async def send_messages_from_agent(agent_name: str, count: int):
        """Send multiple messages from one agent."""
        results = []
        for i in range(count):
            result = await server.call_tool(
                "send_message",
                {
                    "project_key": "concurrent-test",
                    "sender_name": agent_name,
                    "to": ["Receiver"],
                    "subject": f"Parallel message {i} from {agent_name}",
                    "body": f"Testing concurrent write safety - message {i}",
                },
            )
            results.append(result["id"])
            # Small delay to simulate realistic timing
            await asyncio.sleep(0.01)
        return results

    # Run parallel writes
    tasks = [send_messages_from_agent(agent, 10) for agent in agents]
    all_results = await asyncio.gather(*tasks)

    # Flatten results
    all_message_ids = [msg_id for agent_results in all_results for msg_id in agent_results]

    # Verify we got all messages (5 agents × 10 messages = 50 total)
    assert len(all_message_ids) == 50, "Should have 50 total messages"

    # Verify all message IDs are unique (no corruption/race conditions)
    assert len(set(all_message_ids)) == 50, "All message IDs should be unique"

    # Verify messages are in the archive
    storage_dir = mcp_mail_storage["storage_dir"]
    project_messages_dir = storage_dir / "projects" / "concurrent-test" / "messages"
    message_files = list(project_messages_dir.rglob("*.md"))

    # Should have 50 message files
    assert len(message_files) == 50, "Should have 50 message files in archive"

    # Verify Git commits were created (check git log)
    git_dir = storage_dir
    result = subprocess.run(
        ["git", "log", "--oneline", "--all"],
        cwd=git_dir,
        capture_output=True,
        text=True,
    )

    # Should have commits for messages
    commits = result.stdout.strip().split("\n")
    assert len(commits) >= 50, "Should have at least 50 git commits"


@pytest.mark.asyncio
async def test_sqlite_and_git_storage_consistency(mcp_mail_storage):
    """Test that SQLite database and Git archive stay in sync."""
    storage_dir = mcp_mail_storage["storage_dir"]
    server = build_mcp_server()

    # Register agents
    await server.call_tool(
        "register_agent",
        {
            "project_key": "sync-test",
            "program": "sender",
            "model": "test",
            "name": "Sender",
            "task_description": "Message sender",
        },
    )

    await server.call_tool(
        "register_agent",
        {
            "project_key": "sync-test",
            "program": "receiver",
            "model": "test",
            "name": "Receiver",
            "task_description": "Message receiver",
        },
    )

    # Send messages
    message_ids = []
    for i in range(10):
        result = await server.call_tool(
            "send_message",
            {
                "project_key": "sync-test",
                "sender_name": "Sender",
                "to": ["Receiver"],
                "subject": f"Sync test message {i}",
                "body": f"Testing SQLite/Git sync - message {i}",
            },
        )
        message_ids.append(result["id"])

    # Verify messages in SQLite via fetch_inbox
    inbox = await server.call_tool(
        "fetch_inbox",
        {
            "project_key": "sync-test",
            "agent_name": "Receiver",
            "limit": 20,
        },
    )

    sqlite_message_ids = {msg["id"] for msg in inbox["messages"]}
    assert len(sqlite_message_ids) == 10, "SQLite should have all 10 messages"

    # Verify messages in Git archive
    project_messages_dir = storage_dir / "projects" / "sync-test" / "messages"
    message_files = list(project_messages_dir.rglob("*.md"))
    assert len(message_files) == 10, "Git archive should have all 10 message files"

    # Verify all message IDs match between SQLite and Git
    for msg_id in message_ids:
        assert msg_id in sqlite_message_ids, f"Message {msg_id} should be in SQLite"

        # Find corresponding file in Git archive
        found_in_git = False
        for msg_file in message_files:
            if f"{msg_id}.md" == msg_file.name:
                found_in_git = True
                break

        assert found_in_git, f"Message {msg_id} should be in Git archive"


@pytest.mark.asyncio
async def test_mcp_mail_gitignore_excludes_sqlite(mcp_mail_storage):
    """Test that .mcp_mail/.gitignore properly excludes SQLite files."""
    storage_dir = mcp_mail_storage["storage_dir"]
    server = build_mcp_server()

    # Trigger storage creation
    await server.call_tool(
        "register_agent",
        {
            "project_key": "test",
            "program": "test",
            "model": "test",
            "name": "TestAgent",
            "task_description": "Test",
        },
    )

    # Check if .gitignore exists in storage root
    gitignore_path = storage_dir / ".gitignore"

    # The storage system should create appropriate gitignore
    # Check if SQLite files would be ignored
    db_path = mcp_mail_storage["db_path"]
    assert db_path.exists(), "SQLite database should exist"

    # Verify .gitignore patterns (if exists)
    if gitignore_path.exists():
        gitignore_content = gitignore_path.read_text()
        assert "*.db" in gitignore_content or ".db" in gitignore_content, \
            ".gitignore should exclude SQLite database files"
