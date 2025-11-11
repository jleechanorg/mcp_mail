# MCP Mail - Inter-Agent Communication System

Git-backed messaging system for AI agents across platforms (local, Codex web, Claude web).

## Architecture

- **messages.jsonl** - Source of truth (committed to git)
- **SQLite cache** - Fast parallel reads with WAL mode (optional, .gitignored)
- **UUID-based IDs** - Collision-free concurrent message creation
- **Append-only writes** - O_APPEND style JSONL appends keep writes simple
- **Parallel access** - Multiple agents can read/write simultaneously
- **Git history** - Messages flow through normal commits for auditing

## Parallel Access Features

### Concurrent Writes
- **Atomic appends**: JSONL naturally supports parallel writes via O_APPEND flag
- **Unique IDs**: UUID-based IDs prevent collisions in concurrent writes
- **Cache updates**: SQLite cache updated immediately after JSONL write

### Concurrent Reads
- **SQLite cache**: Fast parallel reads using WAL (Write-Ahead Logging) mode
- **JSONL fallback**: If cache disabled, JSONL still supports parallel reads
- **Zero contention**: Multiple agents can read simultaneously without blocking

### Performance
- **Cache enabled (default)**: 2-10x faster for repeated reads
- **High concurrency**: Tested with 20 concurrent agents, 100+ messages
- **Stress tested**: 100 simultaneous writes without corruption

## Message Format

```json
{
  "id": "msg-a1b2c3",
  "from": {
    "agent": "claude-code",
    "repo": "/home/user/ai_universe",
    "branch": "main",
    "email": "user@example.com"
  },
  "to": {
    "agent": "codex-web",
    "repo": "/home/user/other-repo",
    "branch": "main"
  },
  "subject": "Code review request",
  "body": "Please review PR #123",
  "timestamp": "2025-11-10T12:00:00Z",
  "threadId": "msg-parent123",
  "metadata": {}
}
```

## Usage

### Basic Operations

```python
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

repo_path = Path("/path/to/repo")
messages_file = repo_path / ".mcp_mail" / "messages.jsonl"


def append_message(message: dict) -> dict:
    """Append a message to messages.jsonl and return the stored payload."""

    enriched = {**message}
    enriched.setdefault("id", f"msg-{uuid.uuid4()}")
    enriched.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    enriched.setdefault(
        "from",
        {"agent": "example-agent", "repo": str(repo_path), "branch": "main"},
    )

    with messages_file.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(enriched) + "\n")

    return enriched


def load_messages() -> list[dict]:
    """Return every well-formed message from messages.jsonl."""

    if not messages_file.exists():
        return []

    messages: list[dict] = []
    with messages_file.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                # Malformed lines are ignored so a single bad entry does not
                # block the rest of the log.
                continue

    return messages


# Write a message and inspect the resulting log
append_message({
    "to": {"agent": "codex-web", "repo": "/path/to/repo"},
    "subject": "Hello",
    "body": "Message content",
})

for entry in load_messages():
    print(entry["subject"], "→", entry["to"]["agent"])
```

### Parallel Access Example

```python
import asyncio


async def concurrent_writes():
    await asyncio.gather(
        asyncio.to_thread(
            append_message,
            {"to": {"agent": "receiver"}, "subject": "From 1", "body": "Content"},
        ),
        asyncio.to_thread(
            append_message,
            {"to": {"agent": "receiver"}, "subject": "From 2", "body": "Content"},
        ),
        asyncio.to_thread(
            append_message,
            {"to": {"agent": "receiver"}, "subject": "From 3", "body": "Content"},
        ),
    )


async def concurrent_reads():
    return await asyncio.gather(
        asyncio.to_thread(load_messages),
        asyncio.to_thread(load_messages),
        asyncio.to_thread(load_messages),
    )


async def main():
    await concurrent_writes()
    reads = await concurrent_reads()
    print(f"Observed {len(reads[0])} messages from three parallel readers")


asyncio.run(main())
```

### Configuration Options

- **Repository path (required)**: point tools at the git repository that owns
  the `.mcp_mail/` directory.
- **Cache toggle (optional)**: the MCP server populates a SQLite cache next to
  `messages.jsonl`. Agents that only need the JSONL log can ignore it, while
  high-throughput agents can opt-in to reading from the cache for better
  latency.
- **Git integration**: commits are still handled by `git add` / `git commit`.
  The integration tests in `tests/integration/test_mcp_mail_messaging.py`
  demonstrate atomic writes followed by commits.

## MCP Tools

- **send_message** - Send message to another agent via the MCP server
- **list_messages** - List messages with filters (recipient, thread, unread)
- **read_message** - Retrieve a specific message by identifier
- **sync_mailbox** - Trigger git pull/push synchronization

> **Note:** The MCP implementation lives in the `mcp_agent_mail` package. When
> you launch the server (for example with `uv run python -m mcp_agent_mail`),
> these tool names are exposed directly on the MCP interface—no intermediate
> `mcp_mail.*` module prefix is required.
