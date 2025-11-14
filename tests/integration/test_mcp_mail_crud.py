"""Comprehensive CRUD integration tests for .mcp_mail/ data operations.

These tests validate Create, Read, Update, and Delete operations on the .mcp_mail/
messages.jsonl file, including edge cases, data integrity, and git integration.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
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

    # Generate message ID if not provided
    msg_id = message.get("id", f"msg-{uuid.uuid4()}")
    message["id"] = msg_id

    # Add timestamp if not provided
    if "timestamp" not in message:
        message["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Add from field if not provided
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


def read_message_by_id(repo_path: Path, msg_id: str) -> dict | None:
    """Read a specific message by ID."""
    messages = read_messages(repo_path)
    for msg in messages:
        if msg.get("id") == msg_id:
            return msg
    return None


def update_message_metadata(repo_path: Path, msg_id: str, metadata: dict) -> bool:
    """Update a message's metadata by rewriting the entire file (append-only simulation)."""
    messages_file = repo_path / ".mcp_mail" / "messages.jsonl"
    messages = read_messages(repo_path)

    updated = False
    for msg in messages:
        if msg.get("id") == msg_id:
            msg.setdefault("metadata", {}).update(metadata)
            updated = True
            break

    if updated:
        # Rewrite the entire file (in practice, you might use a different strategy)
        with messages_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

    return updated


def mark_message_deleted(repo_path: Path, msg_id: str) -> bool:
    """Mark a message as deleted by adding a metadata flag."""
    return update_message_metadata(
        repo_path, msg_id, {"deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat()}
    )


def archive_message(repo_path: Path, msg_id: str) -> bool:
    """Archive a message by moving it to an archive section."""
    return update_message_metadata(
        repo_path, msg_id, {"archived": True, "archived_at": datetime.now(timezone.utc).isoformat()}
    )


# === CREATE Tests ===


@pytest.mark.asyncio
async def test_create_basic_message(mcp_mail_repo):
    """Test creating a basic message."""
    msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Test Subject",
            "body": "Test body content",
        },
    )

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1
    assert messages[0]["id"] == msg_id
    assert messages[0]["subject"] == "Test Subject"
    assert messages[0]["body"] == "Test body content"
    assert "timestamp" in messages[0]
    assert "from" in messages[0]


@pytest.mark.asyncio
async def test_create_message_with_custom_id(mcp_mail_repo):
    """Test creating a message with a custom ID."""
    custom_id = "msg-custom-123"
    msg_id = write_message(
        mcp_mail_repo,
        {
            "id": custom_id,
            "to": {"agent": "recipient"},
            "subject": "Custom ID message",
            "body": "Message with custom ID",
        },
    )

    assert msg_id == custom_id

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1
    assert messages[0]["id"] == custom_id


@pytest.mark.asyncio
async def test_create_message_with_metadata(mcp_mail_repo):
    """Test creating a message with metadata."""
    _msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Message with metadata",
            "body": "Testing metadata",
            "metadata": {
                "priority": "high",
                "tags": ["important", "urgent"],
                "context": {"feature": "auth", "module": "login"},
            },
        },
    )

    messages = read_messages(mcp_mail_repo)
    assert messages[0]["metadata"]["priority"] == "high"
    assert "important" in messages[0]["metadata"]["tags"]
    assert messages[0]["metadata"]["context"]["feature"] == "auth"


@pytest.mark.asyncio
async def test_create_threaded_messages(mcp_mail_repo):
    """Test creating threaded messages."""
    # Root message
    root_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Thread root",
            "body": "Starting a conversation",
        },
    )

    # Reply 1
    reply1_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "sender"},
            "subject": "Re: Thread root",
            "body": "First reply",
            "threadId": root_id,
        },
    )

    # Reply 2 to reply 1
    reply2_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Re: Re: Thread root",
            "body": "Second reply",
            "threadId": reply1_id,
        },
    )

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 3

    # Verify thread structure
    root_msg = read_message_by_id(mcp_mail_repo, root_id)
    assert root_msg is not None
    assert "threadId" not in root_msg

    reply1_msg = read_message_by_id(mcp_mail_repo, reply1_id)
    assert reply1_msg is not None
    assert reply1_msg["threadId"] == root_id

    reply2_msg = read_message_by_id(mcp_mail_repo, reply2_id)
    assert reply2_msg is not None
    assert reply2_msg["threadId"] == reply1_id


@pytest.mark.asyncio
async def test_create_message_with_unicode(mcp_mail_repo):
    """Test creating messages with Unicode characters."""
    _msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "国际化测试 🌍",
            "body": "支持中文、Español、العربية、Русский、日本語 and emojis ✅🎉🚀",
        },
    )

    messages = read_messages(mcp_mail_repo)
    assert "国际化" in messages[0]["subject"]
    assert "中文" in messages[0]["body"]
    assert "🌍" in messages[0]["subject"]
    assert "✅" in messages[0]["body"]


@pytest.mark.asyncio
async def test_create_message_with_large_body(mcp_mail_repo):
    """Test creating a message with a large body."""
    large_body = "Lorem ipsum " * 10000  # ~120KB of text

    _msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Large message",
            "body": large_body,
        },
    )

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1
    assert len(messages[0]["body"]) > 100000


# === READ Tests ===


@pytest.mark.asyncio
async def test_read_message_by_id(mcp_mail_repo):
    """Test reading a specific message by ID."""
    msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Specific message",
            "body": "Find me!",
        },
    )

    message = read_message_by_id(mcp_mail_repo, msg_id)
    assert message is not None
    assert message["id"] == msg_id
    assert message["subject"] == "Specific message"


@pytest.mark.asyncio
async def test_read_messages_by_recipient(mcp_mail_repo):
    """Test reading messages filtered by recipient."""
    # Create messages to different recipients
    write_message(mcp_mail_repo, {"to": {"agent": "alice"}, "subject": "For Alice 1", "body": "Message 1"})
    write_message(mcp_mail_repo, {"to": {"agent": "bob"}, "subject": "For Bob", "body": "Message 2"})
    write_message(mcp_mail_repo, {"to": {"agent": "alice"}, "subject": "For Alice 2", "body": "Message 3"})

    messages = read_messages(mcp_mail_repo)
    alice_messages = [m for m in messages if m["to"]["agent"] == "alice"]
    bob_messages = [m for m in messages if m["to"]["agent"] == "bob"]

    assert len(alice_messages) == 2
    assert len(bob_messages) == 1


@pytest.mark.asyncio
async def test_read_messages_by_thread(mcp_mail_repo):
    """Test reading messages filtered by thread."""
    root_id = write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Root", "body": "Root message"})

    write_message(
        mcp_mail_repo, {"to": {"agent": "sender"}, "subject": "Reply 1", "body": "First reply", "threadId": root_id}
    )
    write_message(
        mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Reply 2", "body": "Second reply", "threadId": root_id}
    )
    write_message(mcp_mail_repo, {"to": {"agent": "other"}, "subject": "Unrelated", "body": "Different thread"})

    messages = read_messages(mcp_mail_repo)
    thread_messages = [m for m in messages if m.get("threadId") == root_id]

    assert len(thread_messages) == 2


@pytest.mark.asyncio
async def test_read_messages_chronologically(mcp_mail_repo):
    """Test reading messages in chronological order."""
    # Create messages with explicit timestamps
    base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    for i in range(5):
        timestamp = (base_time + timedelta(hours=i)).isoformat()
        write_message(
            mcp_mail_repo,
            {
                "to": {"agent": "recipient"},
                "subject": f"Message {i}",
                "body": f"Content {i}",
                "timestamp": timestamp,
            },
        )

    messages = read_messages(mcp_mail_repo)
    timestamps = [m["timestamp"] for m in messages]

    # Verify chronological order (messages should be in order they were written)
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio
async def test_read_messages_with_malformed_lines(mcp_mail_repo):
    """Test reading messages when file contains malformed JSON lines."""
    # Write valid message
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Valid 1", "body": "Content"})

    # Manually append malformed lines
    messages_file = mcp_mail_repo / ".mcp_mail" / "messages.jsonl"
    with messages_file.open("a") as f:
        f.write("{ this is not valid json }\n")
        f.write("\n")  # Empty line
        f.write("   \n")  # Whitespace line

    # Write another valid message
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Valid 2", "body": "Content"})

    # Should gracefully skip malformed lines
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 2
    assert messages[0]["subject"] == "Valid 1"
    assert messages[1]["subject"] == "Valid 2"


# === UPDATE Tests ===


@pytest.mark.asyncio
async def test_update_message_metadata(mcp_mail_repo):
    """Test updating a message's metadata."""
    msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Test message",
            "body": "Original content",
        },
    )

    # Update metadata
    success = update_message_metadata(
        mcp_mail_repo, msg_id, {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}
    )
    assert success

    # Verify update
    message = read_message_by_id(mcp_mail_repo, msg_id)
    assert message is not None
    assert message["metadata"]["read"] is True
    assert "read_at" in message["metadata"]


@pytest.mark.asyncio
async def test_mark_message_as_read(mcp_mail_repo):
    """Test marking a message as read."""
    msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Unread message",
            "body": "Please read me",
        },
    )

    # Mark as read
    success = update_message_metadata(mcp_mail_repo, msg_id, {"read": True})
    assert success

    message = read_message_by_id(mcp_mail_repo, msg_id)
    assert message is not None
    assert message["metadata"]["read"] is True


@pytest.mark.asyncio
async def test_add_tags_to_message(mcp_mail_repo):
    """Test adding tags to a message."""
    msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Taggable message",
            "body": "Add tags to me",
        },
    )

    # Add tags
    success = update_message_metadata(mcp_mail_repo, msg_id, {"tags": ["bug", "high-priority", "backend"]})
    assert success

    message = read_message_by_id(mcp_mail_repo, msg_id)
    assert message is not None
    assert "bug" in message["metadata"]["tags"]
    assert "high-priority" in message["metadata"]["tags"]


# === DELETE Tests ===


@pytest.mark.asyncio
async def test_mark_message_deleted(mcp_mail_repo):
    """Test soft-deleting a message (marking as deleted)."""
    msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "To be deleted",
            "body": "Delete me",
        },
    )

    # Mark as deleted
    success = mark_message_deleted(mcp_mail_repo, msg_id)
    assert success

    # Verify message is marked deleted
    message = read_message_by_id(mcp_mail_repo, msg_id)
    assert message is not None
    assert message["metadata"]["deleted"] is True
    assert "deleted_at" in message["metadata"]

    # Verify message still exists in file
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_archive_message(mcp_mail_repo):
    """Test archiving a message."""
    msg_id = write_message(
        mcp_mail_repo,
        {
            "to": {"agent": "recipient"},
            "subject": "Old message",
            "body": "Archive me",
        },
    )

    # Archive message
    success = archive_message(mcp_mail_repo, msg_id)
    assert success

    # Verify message is archived
    message = read_message_by_id(mcp_mail_repo, msg_id)
    assert message is not None
    assert message["metadata"]["archived"] is True
    assert "archived_at" in message["metadata"]


@pytest.mark.asyncio
async def test_filter_active_messages(mcp_mail_repo):
    """Test filtering out deleted and archived messages."""
    # Create various messages
    active_id = write_message(
        mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Active", "body": "Active message"}
    )
    deleted_id = write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Deleted", "body": "To delete"})
    archived_id = write_message(
        mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Archived", "body": "To archive"}
    )

    # Mark as deleted and archived
    mark_message_deleted(mcp_mail_repo, deleted_id)
    archive_message(mcp_mail_repo, archived_id)

    # Filter active messages (not deleted, not archived)
    messages = read_messages(mcp_mail_repo)
    active_messages = [
        m for m in messages if not m.get("metadata", {}).get("deleted") and not m.get("metadata", {}).get("archived")
    ]

    assert len(active_messages) == 1
    assert active_messages[0]["id"] == active_id


# === GIT Integration Tests ===


@pytest.mark.asyncio
async def test_commit_messages_to_git(mcp_mail_repo):
    """Test committing messages to git."""
    # Create messages
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Message 1", "body": "Content 1"})
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Message 2", "body": "Content 2"})

    # Commit to git
    subprocess.run(
        ["git", "add", ".mcp_mail/messages.jsonl"],
        cwd=mcp_mail_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add two messages"],
        cwd=mcp_mail_repo,
        check=True,
        capture_output=True,
    )

    # Verify git commit
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Add two messages" in result.stdout

    # Verify files are tracked
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert ".mcp_mail/messages.jsonl" in result.stdout


@pytest.mark.asyncio
async def test_git_diff_shows_new_messages(mcp_mail_repo):
    """Test that git diff shows new messages."""
    # Initial commit is already done by fixture

    # Add a message
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "New message", "body": "Content"})

    # Check git diff
    result = subprocess.run(
        ["git", "diff", ".mcp_mail/messages.jsonl"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "New message" in result.stdout
    assert "+{" in result.stdout  # Shows added JSON line


@pytest.mark.asyncio
async def test_clone_and_verify_messages(mcp_mail_repo):
    """Test cloning a repo and verifying messages are preserved."""
    # Add messages
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Message 1", "body": "Content 1"})
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Message 2", "body": "Content 2"})

    # Commit
    subprocess.run(
        ["git", "add", ".mcp_mail/messages.jsonl"],
        cwd=mcp_mail_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add messages"],
        cwd=mcp_mail_repo,
        check=True,
        capture_output=True,
    )

    # Clone to new location
    clone_path = mcp_mail_repo.parent / "cloned_repo"
    subprocess.run(
        ["git", "clone", str(mcp_mail_repo), str(clone_path)],
        check=True,
        capture_output=True,
    )

    # Verify messages in clone
    cloned_messages = read_messages(clone_path)
    assert len(cloned_messages) == 2
    assert cloned_messages[0]["subject"] == "Message 1"
    assert cloned_messages[1]["subject"] == "Message 2"


# === Data Integrity Tests ===


@pytest.mark.asyncio
async def test_message_id_uniqueness(mcp_mail_repo):
    """Test that message IDs are unique."""
    msg_ids = []
    for i in range(100):
        msg_id = write_message(
            mcp_mail_repo,
            {
                "to": {"agent": "recipient"},
                "subject": f"Message {i}",
                "body": f"Content {i}",
            },
        )
        msg_ids.append(msg_id)

    # Check uniqueness
    assert len(msg_ids) == len(set(msg_ids))


@pytest.mark.asyncio
async def test_jsonl_file_integrity(mcp_mail_repo):
    """Test that messages.jsonl maintains integrity after multiple writes."""
    # Write many messages
    for i in range(50):
        write_message(
            mcp_mail_repo,
            {
                "to": {"agent": f"recipient-{i % 5}"},
                "subject": f"Message {i}",
                "body": f"Content {i}",
            },
        )

    # Read and verify
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 50

    # Verify each message is valid
    for msg in messages:
        assert "id" in msg
        assert "timestamp" in msg
        assert "from" in msg
        assert "to" in msg
        assert "subject" in msg
        assert "body" in msg


@pytest.mark.asyncio
async def test_append_only_semantics(mcp_mail_repo):
    """Test that messages.jsonl follows append-only semantics."""
    messages_file = mcp_mail_repo / ".mcp_mail" / "messages.jsonl"

    # Get initial size
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Message 1", "body": "Content"})
    size1 = messages_file.stat().st_size

    # Add another message
    write_message(mcp_mail_repo, {"to": {"agent": "recipient"}, "subject": "Message 2", "body": "Content"})
    size2 = messages_file.stat().st_size

    # File should only grow
    assert size2 > size1

    # Verify both messages exist
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_concurrent_reads_consistency(mcp_mail_repo):
    """Test that concurrent reads return consistent data."""
    # Create messages
    for i in range(10):
        write_message(
            mcp_mail_repo,
            {
                "to": {"agent": "recipient"},
                "subject": f"Message {i}",
                "body": f"Content {i}",
            },
        )

    # Multiple concurrent reads
    import asyncio

    async def read_and_count():
        return len(read_messages(mcp_mail_repo))

    counts = await asyncio.gather(
        read_and_count(),
        read_and_count(),
        read_and_count(),
        read_and_count(),
        read_and_count(),
    )

    # All reads should see the same count
    assert all(c == 10 for c in counts)


# === Error Handling Tests ===


@pytest.mark.asyncio
async def test_read_nonexistent_message(mcp_mail_repo):
    """Test reading a nonexistent message."""
    message = read_message_by_id(mcp_mail_repo, "msg-nonexistent")
    assert message is None


@pytest.mark.asyncio
async def test_read_from_empty_file(mcp_mail_repo):
    """Test reading from empty messages.jsonl."""
    messages = read_messages(mcp_mail_repo)
    assert messages == []


@pytest.mark.asyncio
async def test_update_nonexistent_message(mcp_mail_repo):
    """Test updating a nonexistent message."""
    success = update_message_metadata(mcp_mail_repo, "msg-nonexistent", {"updated": True})
    assert not success
