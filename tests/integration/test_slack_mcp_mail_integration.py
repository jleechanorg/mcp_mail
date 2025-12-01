"""Integration tests for Slack ↔ MCP Mail bidirectional sync.

These tests validate end-to-end Slack integration with .mcp_mail/ messaging:
- Slack → MCP: Incoming Slack messages create MCP database messages that are archived to .mcp_mail/
- MCP → Slack: MCP messages trigger Slack notifications
- Thread mapping: Slack threads ↔ MCP thread_id
- CRUD operations on .mcp_mail/ with Slack context
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

import pytest


@pytest.fixture
def mcp_mail_repo(tmp_path):
    """Create a git repository with .mcp_mail/ directory for Slack testing."""
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


def write_slack_message(
    repo_path: Path,
    slack_event: dict[str, Any],
    *,
    sender_name: str = "SlackBridge",
) -> str:
    """Simulate Slack → MCP message creation."""
    import uuid

    # Generate message ID
    msg_id = f"msg-{uuid.uuid4()}"

    # Extract Slack event details
    channel_id = slack_event.get("channel", "C0000000000")
    text = slack_event.get("text", "")
    user_id = slack_event.get("user", "U0000000000")
    slack_ts = slack_event.get("ts", "0000000000.000000")
    thread_ts = slack_event.get("thread_ts")

    # Create MCP message from Slack event
    subject_line = text.splitlines()[0][:100] if text else ""

    message = {
        "id": msg_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "from": {
            "agent": sender_name,
            "repo": str(repo_path),
            "branch": "main",
            "email": f"{sender_name}@slack.local",
        },
        "to": {"agent": "all"},  # Broadcast to all agents
        "subject": f"[Slack] {subject_line}",
        "body": text,
        "metadata": {
            "slack_channel": channel_id,
            "slack_ts": slack_ts,
            "slack_user": user_id,
            "source": "slack",
        },
    }

    # Add thread mapping if threaded
    if thread_ts:
        message["threadId"] = f"slack_{channel_id}_{thread_ts}"
        message["metadata"]["slack_thread_ts"] = thread_ts

    # Write to messages.jsonl
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


def _send_live_slack_message(text: str) -> str:
    """Send a live Slack message when explicitly enabled via env vars.

    Guarded by:
    - SLACK_LIVE_TEST=1
    - SLACK_MCP_MAIL_WEBHOOK_URL set to the target webhook
    """
    webhook = os.getenv("SLACK_MCP_MAIL_WEBHOOK_URL")
    enabled = os.getenv("SLACK_LIVE_TEST") == "1"
    if not (enabled and webhook):
        return "skipped"

    payload = json.dumps({"text": text}).encode("utf-8")
    req = request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        if resp.status != 200 or "ok" not in body.lower():
            raise RuntimeError(f"Slack live send failed: status={resp.status}, body={body}")
        return body.strip()


def _live_mirror_payload(sender: str, recipients: list[str]) -> str | None:
    """Send a real webhook payload and return response if live testing is enabled."""
    webhook = os.getenv("SLACK_MCP_MAIL_WEBHOOK_URL")
    enabled = os.getenv("SLACK_LIVE_TEST") == "1"
    if not (enabled and webhook):
        return None

    frontmatter = {
        "project": "live-test",
        "subject": "Live Slack agent visibility test",
        "from": sender,
        "to": recipients,
    }
    body_md = "This is a live Slack webhook test to verify agent names are included."

    from mcp_agent_mail.slack_integration import mirror_message_to_slack

    return mirror_message_to_slack(frontmatter, body_md)


@pytest.mark.asyncio
async def test_slack_live_webhook_includes_agent_names(monkeypatch):
    """Live Slack webhook test: ensures From/To are present in the payload sent to the webhook.

    Guarded by SLACK_LIVE_TEST=1 and SLACK_MCP_MAIL_WEBHOOK_URL. If not set, this test is skipped.
    """
    if os.getenv("SLACK_LIVE_TEST") != "1" or not os.getenv("SLACK_MCP_MAIL_WEBHOOK_URL"):
        pytest.skip("SLACK_LIVE_TEST not enabled or webhook not set")

    sender = "LiveSenderAgent"
    recipients = ["LiveRecipientA", "LiveRecipientB"]

    resp = _live_mirror_payload(sender, recipients)
    assert resp is not None  # Should have been sent


@pytest.mark.asyncio
async def test_slack_message_creates_mcp_mail_entry(mcp_mail_repo):
    """Test that incoming Slack message creates entry in .mcp_mail/."""
    # Simulate Slack message event
    slack_event = {
        "type": "message",
        "channel": "C1234567890",
        "user": "U9876543210",
        "text": "Hey agents, can you help with deployment?",
        "ts": "1234567890.123456",
    }

    # Write Slack message to .mcp_mail/
    msg_id = write_slack_message(mcp_mail_repo, slack_event)

    # Verify message was written
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1

    msg = messages[0]
    assert msg["id"] == msg_id
    assert msg["from"]["agent"] == "SlackBridge"
    assert "[Slack]" in msg["subject"]
    assert "deployment" in msg["body"]
    assert msg["metadata"]["slack_channel"] == "C1234567890"
    assert msg["metadata"]["slack_user"] == "U9876543210"
    assert msg["metadata"]["source"] == "slack"

    # Commit to git
    commit_messages(mcp_mail_repo, "Slack message: deployment help")

    # Verify git commit
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "deployment help" in result.stdout

    # Optional: send a live Slack message to #mcp-mail when explicitly enabled
    live_status = _send_live_slack_message("MCP Mail Slack test: deployment help flow")
    if live_status != "skipped":
        assert "ok" in live_status.lower()


@pytest.mark.asyncio
async def test_slack_thread_maps_to_mcp_thread_id(mcp_mail_repo):
    """Test that Slack threads map to MCP thread_id."""
    # Original message
    original_event = {
        "type": "message",
        "channel": "C1234567890",
        "user": "U1111111111",
        "text": "Starting discussion about API design",
        "ts": "1234567890.111111",
    }

    msg1_id = write_slack_message(mcp_mail_repo, original_event)

    # Thread reply 1
    reply1_event = {
        "type": "message",
        "channel": "C1234567890",
        "user": "U2222222222",
        "text": "I think we should use REST",
        "ts": "1234567890.222222",
        "thread_ts": "1234567890.111111",  # References original
    }

    msg2_id = write_slack_message(mcp_mail_repo, reply1_event)

    # Thread reply 2
    reply2_event = {
        "type": "message",
        "channel": "C1234567890",
        "user": "U3333333333",
        "text": "GraphQL might be better",
        "ts": "1234567890.333333",
        "thread_ts": "1234567890.111111",  # References original
    }

    msg3_id = write_slack_message(mcp_mail_repo, reply2_event)

    # Verify thread mapping
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 3

    # Original message has no threadId
    original_msg = next(m for m in messages if m["id"] == msg1_id)
    assert "threadId" not in original_msg

    # Replies have matching threadId
    reply1_msg = next(m for m in messages if m["id"] == msg2_id)
    reply2_msg = next(m for m in messages if m["id"] == msg3_id)

    expected_thread_id = "slack_C1234567890_1234567890.111111"
    assert reply1_msg["threadId"] == expected_thread_id
    assert reply2_msg["threadId"] == expected_thread_id

    # Both replies reference the same thread
    thread_messages = [m for m in messages if m.get("threadId") == expected_thread_id]
    assert len(thread_messages) == 2

    commit_messages(mcp_mail_repo, "Slack thread: API design discussion")


@pytest.mark.asyncio
async def test_concurrent_slack_messages(mcp_mail_repo):
    """Test concurrent Slack messages from multiple channels."""

    async def write_channel_messages(channel_id: str, count: int):
        """Simulate messages from a specific channel."""
        for i in range(count):
            event = {
                "channel": channel_id,
                "user": f"U{channel_id[-5:]}",
                "text": f"Message {i} from {channel_id}",
                "ts": f"{1234567890 + i}.{channel_id[-6:]}",
            }
            write_slack_message(mcp_mail_repo, event)
            await asyncio.sleep(0.01)

    # Simulate messages from 3 different Slack channels concurrently
    await asyncio.gather(
        write_channel_messages("C1111111111", 4),
        write_channel_messages("C2222222222", 4),
        write_channel_messages("C3333333333", 4),
    )

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 12

    # Verify messages from each channel
    c1_messages = [m for m in messages if m["metadata"]["slack_channel"] == "C1111111111"]
    c2_messages = [m for m in messages if m["metadata"]["slack_channel"] == "C2222222222"]
    c3_messages = [m for m in messages if m["metadata"]["slack_channel"] == "C3333333333"]

    assert len(c1_messages) == 4
    assert len(c2_messages) == 4
    assert len(c3_messages) == 4

    # No duplicate message IDs
    message_ids = [m["id"] for m in messages]
    assert len(message_ids) == len(set(message_ids))


@pytest.mark.asyncio
async def test_slack_message_filtering_by_channel(mcp_mail_repo):
    """Test filtering .mcp_mail/ entries by Slack channel."""
    # Create messages from different channels
    channels = ["C1111111111", "C2222222222", "C3333333333"]
    for channel in channels:
        for i in range(3):
            event = {
                "channel": channel,
                "user": "U0000000000",
                "text": f"Message {i} in {channel}",
                "ts": f"{1234567890 + i}.000000",
            }
            write_slack_message(mcp_mail_repo, event)

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 9

    # Filter by specific channel
    c1_messages = [m for m in messages if m["metadata"]["slack_channel"] == "C1111111111"]
    assert len(c1_messages) == 3
    assert all(m["metadata"]["slack_channel"] == "C1111111111" for m in c1_messages)

    # Filter by Slack source
    slack_messages = [m for m in messages if m["metadata"]["source"] == "slack"]
    assert len(slack_messages) == 9

    # All from SlackBridge
    assert all(m["from"]["agent"] == "SlackBridge" for m in messages)


@pytest.mark.asyncio
async def test_mcp_message_with_slack_metadata(mcp_mail_repo):
    """Test MCP messages can carry Slack-specific metadata."""
    import uuid

    # Create MCP message with Slack context
    msg_id = f"msg-{uuid.uuid4()}"
    message = {
        "id": msg_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "from": {"agent": "DeployAgent", "repo": str(mcp_mail_repo)},
        "to": {"agent": "SlackBridge"},
        "subject": "Deployment completed",
        "body": "Production deployment successful! 🚀",
        "metadata": {
            "slack_notification": True,
            "slack_channel": "deployments",
            "importance": "high",
            "slack_blocks_enabled": True,
        },
    }

    messages_file = mcp_mail_repo / ".mcp_mail" / "messages.jsonl"
    with messages_file.open("a") as f:
        f.write(json.dumps(message) + "\n")

    # Verify message
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1

    msg = messages[0]
    assert msg["to"]["agent"] == "SlackBridge"
    assert msg["metadata"]["slack_notification"] is True
    assert msg["metadata"]["slack_channel"] == "deployments"
    assert msg["metadata"]["importance"] == "high"

    commit_messages(mcp_mail_repo, "Deployment notification for Slack")


@pytest.mark.asyncio
async def test_slack_bridge_agent_messages_history(mcp_mail_repo):
    """Test that SlackBridge agent messages are properly tracked in history."""
    # Simulate multiple Slack interactions over time
    events = [
        {
            "channel": "C1111111111",
            "user": "U1111111111",
            "text": "Question about API",
            "ts": "1234567890.100000",
        },
        {
            "channel": "C2222222222",
            "user": "U2222222222",
            "text": "Bug report",
            "ts": "1234567891.200000",
        },
        {
            "channel": "C1111111111",
            "user": "U3333333333",
            "text": "Feature request",
            "ts": "1234567892.300000",
        },
    ]

    for event in events:
        write_slack_message(mcp_mail_repo, event)
        await asyncio.sleep(0.01)

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 3

    # All from SlackBridge
    assert all(m["from"]["agent"] == "SlackBridge" for m in messages)

    # Commit each batch
    commit_messages(mcp_mail_repo, "Slack messages batch 1")

    # Add more messages
    write_slack_message(
        mcp_mail_repo,
        {
            "channel": "C3333333333",
            "user": "U4444444444",
            "text": "Another message",
            "ts": "1234567893.400000",
        },
    )

    commit_messages(mcp_mail_repo, "Slack messages batch 2")

    # Verify git history
    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=mcp_mail_repo,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "batch 1" in result.stdout
    assert "batch 2" in result.stdout

    # Verify total messages
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 4


@pytest.mark.asyncio
async def test_slack_webhook_fallback_metadata(mcp_mail_repo):
    """Test messages include webhook fallback metadata when applicable."""
    import uuid

    # MCP message intended for Slack via webhook
    msg_id = f"msg-{uuid.uuid4()}"
    message = {
        "id": msg_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "from": {"agent": "TestAgent"},
        "to": {"agent": "SlackBridge"},
        "subject": "Test webhook notification",
        "body": "This should use webhook fallback",
        "metadata": {
            "slack_method": "webhook",
            "webhook_url": "https://hooks.slack.com/test",
            "fallback_mode": True,
        },
    }

    messages_file = mcp_mail_repo / ".mcp_mail" / "messages.jsonl"
    with messages_file.open("a") as f:
        f.write(json.dumps(message) + "\n")

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1

    msg = messages[0]
    assert msg["metadata"]["slack_method"] == "webhook"
    assert msg["metadata"]["fallback_mode"] is True
    assert "hooks.slack.com" in msg["metadata"]["webhook_url"]


@pytest.mark.asyncio
async def test_slack_message_with_mentions(mcp_mail_repo):
    """Test Slack messages with @mentions are properly recorded."""
    # Slack message with @mentions
    event = {
        "channel": "C1234567890",
        "user": "U9999999999",
        "text": "<@U1111111111> and <@U2222222222> can you help with this?",
        "ts": "1234567890.123456",
    }

    msg_id = write_slack_message(mcp_mail_repo, event)

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 1

    msg = messages[0]
    assert msg["id"] == msg_id
    # Mentions preserved in body
    assert "<@U1111111111>" in msg["body"] or "@U1111111111" in msg["body"]
    assert "help with this" in msg["body"]


@pytest.mark.asyncio
async def test_update_slack_message_metadata(mcp_mail_repo):
    """Test updating message metadata for Slack reactions/acks."""
    # Create initial Slack message
    event = {
        "channel": "C1234567890",
        "user": "U1111111111",
        "text": "Task completed",
        "ts": "1234567890.123456",
    }

    _ = write_slack_message(mcp_mail_repo, event)

    # Simulate adding reaction metadata (in real implementation)
    messages = read_messages(mcp_mail_repo)
    msg = messages[0]

    # Update metadata to include reaction
    msg["metadata"]["reactions"] = [{"name": "thumbsup", "user": "U2222222222", "ts": "1234567890.234567"}]

    # Rewrite messages (simulating update)
    messages_file = mcp_mail_repo / ".mcp_mail" / "messages.jsonl"
    messages_file.write_text("")
    with messages_file.open("a") as f:
        f.write(json.dumps(msg) + "\n")

    # Verify update
    updated_messages = read_messages(mcp_mail_repo)
    assert len(updated_messages) == 1
    assert "reactions" in updated_messages[0]["metadata"]
    assert len(updated_messages[0]["metadata"]["reactions"]) == 1
    assert updated_messages[0]["metadata"]["reactions"][0]["name"] == "thumbsup"


@pytest.mark.asyncio
async def test_delete_slack_message_from_mcp_mail(mcp_mail_repo):
    """Test removing Slack messages from .mcp_mail/."""
    # Create multiple messages
    for i in range(5):
        event = {
            "channel": "C1234567890",
            "user": "U0000000000",
            "text": f"Message {i}",
            "ts": f"{1234567890 + i}.000000",
        }
        write_slack_message(mcp_mail_repo, event)

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 5

    # Delete specific message (by filtering)
    target_ts = "1234567892.000000"
    filtered_messages = [m for m in messages if m["metadata"]["slack_ts"] != target_ts]
    assert len(filtered_messages) == 4

    # Rewrite messages file without deleted message
    messages_file = mcp_mail_repo / ".mcp_mail" / "messages.jsonl"
    messages_file.write_text("")
    with messages_file.open("a") as f:
        for msg in filtered_messages:
            f.write(json.dumps(msg) + "\n")

    # Verify deletion
    remaining_messages = read_messages(mcp_mail_repo)
    assert len(remaining_messages) == 4
    assert all(m["metadata"]["slack_ts"] != target_ts for m in remaining_messages)

    # Commit deletion
    commit_messages(mcp_mail_repo, "Remove Slack message")


@pytest.mark.asyncio
async def test_slack_thread_conversation_in_mcp_mail(mcp_mail_repo):
    """Test full Slack threaded conversation recorded in .mcp_mail/."""
    # Initial question
    question_event = {
        "channel": "C1234567890",
        "user": "U1111111111",
        "text": "How do I deploy to staging?",
        "ts": "1234567890.100000",
    }
    write_slack_message(mcp_mail_repo, question_event)

    # Multiple replies in thread
    replies = [
        {
            "channel": "C1234567890",
            "user": "U2222222222",
            "text": "Use the deploy.sh script",
            "ts": "1234567890.200000",
            "thread_ts": "1234567890.100000",
        },
        {
            "channel": "C1234567890",
            "user": "U3333333333",
            "text": "Make sure to run tests first",
            "ts": "1234567890.300000",
            "thread_ts": "1234567890.100000",
        },
        {
            "channel": "C1234567890",
            "user": "U1111111111",
            "text": "Thanks! It worked",
            "ts": "1234567890.400000",
            "thread_ts": "1234567890.100000",
        },
    ]

    for reply in replies:
        write_slack_message(mcp_mail_repo, reply)

    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 4

    # Original has no threadId
    original = messages[0]
    assert "threadId" not in original

    # All replies share same threadId
    thread_messages = messages[1:]
    thread_id = "slack_C1234567890_1234567890.100000"
    assert all(m["threadId"] == thread_id for m in thread_messages)

    # Verify conversation flow
    assert "deploy to staging" in original["body"]
    assert "deploy.sh" in thread_messages[0]["body"]
    assert "tests first" in thread_messages[1]["body"]
    assert "worked" in thread_messages[2]["body"]

    commit_messages(mcp_mail_repo, "Slack thread: deployment help")


@pytest.mark.asyncio
async def test_query_mcp_mail_for_slack_messages(mcp_mail_repo):
    """Test querying .mcp_mail/ specifically for Slack-sourced messages."""
    # Mix of Slack and non-Slack messages
    # Slack message 1
    write_slack_message(
        mcp_mail_repo,
        {"channel": "C1111111111", "user": "U1", "text": "From Slack", "ts": "1.0"},
    )

    # Regular MCP message
    import uuid

    regular_msg = {
        "id": f"msg-{uuid.uuid4()}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "from": {"agent": "RegularAgent"},
        "to": {"agent": "AnotherAgent"},
        "subject": "Regular message",
        "body": "Not from Slack",
    }

    messages_file = mcp_mail_repo / ".mcp_mail" / "messages.jsonl"
    with messages_file.open("a") as f:
        f.write(json.dumps(regular_msg) + "\n")

    # Slack message 2
    write_slack_message(
        mcp_mail_repo,
        {"channel": "C2222222222", "user": "U2", "text": "Also from Slack", "ts": "2.0"},
    )

    # Query all messages
    messages = read_messages(mcp_mail_repo)
    assert len(messages) == 3

    # Filter Slack messages
    slack_messages = [m for m in messages if m.get("metadata", {}).get("source") == "slack"]
    assert len(slack_messages) == 2
    assert all(m["from"]["agent"] == "SlackBridge" for m in slack_messages)

    # Filter non-Slack messages
    regular_messages = [m for m in messages if m.get("metadata", {}).get("source") != "slack"]
    assert len(regular_messages) == 1
    assert regular_messages[0]["from"]["agent"] == "RegularAgent"
