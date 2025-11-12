"""Integration tests for .mcp_mail/ git-backed messaging system.

These tests validate end-to-end multi-agent communication using the .mcp_mail/
directory structure for message storage and git-based persistence.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def mcp_mail_repo(tmp_path):
    """Create a git repository with .mcp_mail/ directory for testing."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    mcp_mail_dir = repo_path / ".mcp_mail"
    mcp_mail_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test Agent"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create .mcp_mail/ structure
    (mcp_mail_dir / ".gitignore").write_text("*.db\n*.db-shm\n*.db-wal\n")
    (mcp_mail_dir / "messages.jsonl").write_text("")

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


def write_message(repo_path: Path, message: dict) -> str:
    """Write a message to messages.jsonl and return message ID."""
    import uuid
    from datetime import datetime, timezone

    # Generate message ID
    msg_id = f"msg-{uuid.uuid4()}"

    # Add metadata
    message["id"] = msg_id
    message["timestamp"] = datetime.now(timezone.utc).isoformat()
    if "from" not in message:
        message["from"] = {
            "agent": "test-agent",
            "repo": str(repo_path),
            "branch": "main",
            "email": "test@example.com",
        }

    # Append to messages.jsonl
    messages_file = repo_path / ".mcp_mail" / "messages.jsonl"
    with messages_file.open("a") as f:
        f.write(json.dumps(message) + "\n")

    return msg_id


def read_messages(repo_path: Path) -> list[dict]:
    """Read all messages from messages.jsonl."""
    messages_file = repo_path / ".mcp_mail" / "messages.jsonl"
    if not messages_file.exists():
        return []

    messages: list[dict] = []
    with messages_file.open() as f:
        for line in f:
            if not line.strip():
                continue
            with contextlib.suppress(json.JSONDecodeError):
                messages.append(json.loads(line))
    return messages


def commit_messages(repo_path: Path, message_description: str = "Add messages"):
    """Commit messages to git."""
    subprocess.run(
        ["git", "add", ".mcp_mail/messages.jsonl"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message_description],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


@pytest.mark.asyncio
async def test_basic_message_send_receive(mcp_mail_repo):
    """Test basic message send and receive using .mcp_mail/."""
    # Agent 1 sends a message
    msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "agent2"},
            "subject": "Hello from Agent 1",
            "body": "This is a test message",
        },
    )

    # Verify message was written
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1
    assert messages[0]["id"] == msg_id
    assert messages[0]["subject"] == "Hello from Agent 1"
    assert messages[0]["to"]["agent"] == "agent2"

    # Commit to git
    commit_messages(mcp_mail_repo, "Agent 1 sends message")

    # Verify git commit
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Agent 1 sends message" in result.stdout


@pytest.mark.asyncio
async def test_multi_agent_conversation(mcp_mail_repo):
    """Test multi-agent conversation flow."""
    # Agent 1 -> Agent 2
    msg1_id = write_message(
        mcp_mail_repo,
        {
            "from": {
                "agent": "frontend-dev",
                "repo": str(mcp_mail_repo),
                "branch": "main",
                "email": "frontend@example.com",
            },
            "to": {"agent": "backend-dev"},
            "subject": "Need API endpoint",
            "body": "Can you create /api/dashboard endpoint?",
        },
    )

    # Agent 2 -> Agent 3
    msg2_id = write_message(
        mcp_mail_repo,
        {
            "from": {
                "agent": "backend-dev",
                "repo": str(mcp_mail_repo),
                "branch": "main",
                "email": "backend@example.com",
            },
            "to": {"agent": "database-admin"},
            "subject": "Need query optimization",
            "body": "Help with user metrics query",
            "threadId": msg1_id,
        },
    )

    # Agent 3 -> Agent 2 (reply)
    msg3_id = write_message(
        mcp_mail_repo,
        {
            "from": {
                "agent": "database-admin",
                "repo": str(mcp_mail_repo),
                "branch": "main",
                "email": "db@example.com",
            },
            "to": {"agent": "backend-dev"},
            "subject": "Re: Need query optimization",
            "body": "Here's the optimized query",
            "threadId": msg2_id,
        },
    )

    # Agent 2 -> Agent 1 (completion)
    msg4_id = write_message(
        mcp_mail_repo,
        {
            "from": {
                "agent": "backend-dev",
                "repo": str(mcp_mail_repo),
                "branch": "main",
                "email": "backend@example.com",
            },
            "to": {"agent": "frontend-dev"},
            "subject": "API endpoint ready",
            "body": "Dashboard endpoint is ready",
            "threadId": msg1_id,
        },
    )

    # Verify all messages
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 4

    # Verify thread relationships - both msg2 and msg4 reference msg1
    thread_messages = [m for m in messages if m.get("threadId") == msg1_id]
    assert len(thread_messages) == 2  # msg2 and msg4 both reference msg1
    thread_ids = {m["id"] for m in thread_messages}
    assert msg2_id in thread_ids
    assert msg4_id in thread_ids

    # Verify msg3 references msg2
    msg3_thread = [m for m in messages if m.get("threadId") == msg2_id]
    assert len(msg3_thread) == 1
    assert msg3_thread[0]["id"] == msg3_id

    # Commit conversation
    commit_messages(mcp_mail_repo, "Multi-agent conversation")


@pytest.mark.asyncio
async def test_parallel_message_writes(mcp_mail_repo):
    """Test concurrent message writes from multiple agents."""

    async def write_messages_for_agent(agent_name: str, count: int):
        """Simulate an agent writing multiple messages."""
        for i in range(count):
            write_message(
                mcp_mail_repo,
                {
                    "from": {
                        "agent": agent_name,
                        "repo": str(mcp_mail_repo),
                        "branch": "main",
                        "email": f"{agent_name}@example.com",
                    },
                    "to": {"agent": "coordinator"},
                    "subject": f"Message {i} from {agent_name}",
                    "body": f"Parallel message {i}",
                },
            )
            # Small delay to simulate realistic timing
            await asyncio.sleep(0.01)

    # Simulate 3 agents writing concurrently
    await asyncio.gather(
        write_messages_for_agent("agent-1", 5),
        write_messages_for_agent("agent-2", 5),
        write_messages_for_agent("agent-3", 5),
    )

    # Verify all messages were written
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 15

    # Verify no duplicate message IDs
    message_ids = [m["id"] for m in messages]
    assert len(message_ids) == len(set(message_ids))

    # Verify messages from each agent
    agent1_messages = [m for m in messages if m["from"]["agent"] == "agent-1"]
    agent2_messages = [m for m in messages if m["from"]["agent"] == "agent-2"]
    agent3_messages = [m for m in messages if m["from"]["agent"] == "agent-3"]

    assert len(agent1_messages) == 5
    assert len(agent2_messages) == 5
    assert len(agent3_messages) == 5


@pytest.mark.asyncio
async def test_message_filtering(mcp_mail_repo):
    """Test filtering messages by agent, subject, thread, etc."""
    # Create diverse messages
    write_message(
        mcp_mail_repo,
        {
            "from": {"agent": "agent1"},
            "to": {"agent": "agent2"},
            "subject": "Urgent: Deploy now",
            "body": "Deploy ASAP",
            "metadata": {"importance": "urgent"},
        },
    )

    thread_id = write_message(
        mcp_mail_repo,
        {
            "from": {"agent": "agent2"},
            "to": {"agent": "agent3"},
            "subject": "Question about API",
            "body": "How does it work?",
        },
    )

    write_message(
        mcp_mail_repo,
        {
            "from": {"agent": "agent3"},
            "to": {"agent": "agent2"},
            "subject": "Re: Question about API",
            "body": "Here's how it works",
            "threadId": thread_id,
        },
    )

    write_message(
        mcp_mail_repo,
        {
            "from": {"agent": "agent1"},
            "to": {"agent": "agent4"},
            "subject": "FYI: New feature",
            "body": "Check this out",
            "metadata": {"importance": "normal"},
        },
    )

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 4

    # Filter by sender
    agent1_messages = [m for m in messages if m["from"]["agent"] == "agent1"]
    assert len(agent1_messages) == 2

    # Filter by recipient
    agent2_messages = [m for m in messages if m["to"]["agent"] == "agent2"]
    assert len(agent2_messages) == 2

    # Filter by thread
    thread_messages = [m for m in messages if m.get("threadId") == thread_id]
    assert len(thread_messages) == 1

    # Filter by metadata
    urgent_messages = [m for m in messages if m.get("metadata", {}).get("importance") == "urgent"]
    assert len(urgent_messages) == 1


@pytest.mark.asyncio
async def test_git_history_preservation(mcp_mail_repo):
    """Test that git history correctly tracks message additions."""
    # First batch of messages
    write_message(
        mcp_mail_repo,
        {"to": {"agent": "agent1"}, "subject": "Message 1", "body": "First batch"},
    )
    commit_messages(mcp_mail_repo, "Add message 1")

    # Second batch
    write_message(
        mcp_mail_repo,
        {"to": {"agent": "agent2"}, "subject": "Message 2", "body": "Second batch"},
    )
    commit_messages(mcp_mail_repo, "Add message 2")

    # Third batch
    write_message(
        mcp_mail_repo,
        {"to": {"agent": "agent3"}, "subject": "Message 3", "body": "Third batch"},
    )
    commit_messages(mcp_mail_repo, "Add message 3")

    # Verify git log
    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )

    log_lines = result.stdout.strip().split("\n")
    assert len(log_lines) >= 4  # Initial commit + 3 message commits

    assert "Add message 3" in result.stdout
    assert "Add message 2" in result.stdout
    assert "Add message 1" in result.stdout

    # Verify we can checkout previous state
    result = subprocess.run(
        ["git", "rev-list", "HEAD"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    commits = result.stdout.strip().split("\n")

    # Save current branch name
    branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    current_branch = branch_result.stdout.strip() or "main"

    second_commit = commits[1]  # Second most recent

    # Checkout previous commit (detached HEAD)
    subprocess.run(
        ["git", "checkout", second_commit],
        cwd=mcp_mail_repo,
        check=True,
        capture_output=True,
    )

    # Should only have 2 messages at this point
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 2

    # Return to original branch
    subprocess.run(
        ["git", "checkout", current_branch],
        cwd=mcp_mail_repo,
        check=True,
        capture_output=True,
    )

    # Should have all 3 messages again
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 3


@pytest.mark.asyncio
async def test_cross_repo_message_reference(mcp_mail_repo, tmp_path):
    """Test messages referencing other repositories."""
    # Create a second repository
    repo2_path = tmp_path / "test_repo2"
    repo2_path.mkdir()
    mcp_mail_dir2 = repo2_path / ".mcp_mail"
    mcp_mail_dir2.mkdir()

    subprocess.run(["git", "init"], cwd=repo2_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo2_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test Agent"],
        cwd=repo2_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=repo2_path,
        check=True,
        capture_output=True,
    )

    (mcp_mail_dir2 / ".gitignore").write_text("*.db\n*.db-shm\n*.db-wal\n")
    (mcp_mail_dir2 / "messages.jsonl").write_text("")
    subprocess.run(["git", "add", "."], cwd=repo2_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo2_path,
        check=True,
        capture_output=True,
    )

    # Agent in repo1 sends to agent in repo2
    _msg_id = write_message(
        mcp_mail_repo,
        {
            "from": {
                "agent": "agent-repo1",
                "repo": str(mcp_mail_repo),
                "branch": "main",
            },
            "to": {"agent": "agent-repo2", "repo": str(repo2_path), "branch": "main"},
            "subject": "Cross-repo message",
            "body": "Hello from repo1!",
        },
    )

    # Verify message in repo1
    messages_repo1 = read_messages(mcp_mail_repo)
    assert len(messages_repo1) == 1
    assert messages_repo1[0]["to"]["repo"] == str(repo2_path)

    # In real implementation, this would also write to repo2
    # For now, just verify the message structure is correct
    assert messages_repo1[0]["from"]["repo"] == str(mcp_mail_repo)
    assert messages_repo1[0]["to"]["agent"] == "agent-repo2"


@pytest.mark.asyncio
async def test_message_metadata_and_extensions(mcp_mail_repo):
    """Test that messages can carry arbitrary metadata."""
    _msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "agent1"},
            "subject": "Task assignment",
            "body": "Please complete this task",
            "metadata": {
                "priority": "high",
                "tags": ["bug", "urgent", "frontend"],
                "assignee": "agent1",
                "deadline": "2025-11-15T00:00:00Z",
                "estimated_hours": 4,
                "related_issues": ["#123", "#456"],
            },
        },
    )

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1

    msg = messages[0]
    assert msg["metadata"]["priority"] == "high"
    assert "bug" in msg["metadata"]["tags"]
    assert msg["metadata"]["estimated_hours"] == 4
    assert len(msg["metadata"]["related_issues"]) == 2


@pytest.mark.asyncio
async def test_empty_messages_file(mcp_mail_repo):
    """Test reading from empty messages.jsonl."""
    messages = read_messages(mcp_mail_repo)
    assert messages == []


@pytest.mark.asyncio
async def test_malformed_message_handling(mcp_mail_repo):
    """Test that malformed messages don't break the entire log."""
    # Write a good message
    write_message(
        mcp_mail_repo,
        {"to": {"agent": "agent1"}, "subject": "Good message", "body": "Valid"},
    )

    # Manually write a malformed line
    messages_file = mcp_mail_repo / ".mcp_mail" / "messages.jsonl"
    with messages_file.open("a") as f:
        f.write("this is not json\n")

    # Write another good message
    write_message(
        mcp_mail_repo,
        {"to": {"agent": "agent2"}, "subject": "Another good message", "body": "Also valid"},
    )

    # Reading should handle the error gracefully
    # In a real implementation, you'd want error handling
    messages = []
    with messages_file.open() as f:
        for line in f:
            if line.strip():
                with contextlib.suppress(json.JSONDecodeError):
                    messages.append(json.loads(line))

    # Should have 2 good messages
    assert len(messages) == 2
    assert all("subject" in m for m in messages)
