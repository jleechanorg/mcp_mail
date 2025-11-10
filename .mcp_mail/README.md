# MCP Mail - Inter-Agent Communication System

Git-backed messaging system for AI agents across platforms (local, Codex web, Claude web).

## Architecture

This directory (`.mcp_mail/`) provides a simple file-based messaging system:

- **messages.jsonl** - Source of truth for all messages (tracked in git)
- **Format** - One JSON message per line (JSONL format)
- **Parallel access** - JSONL supports atomic appends via O_APPEND flag
- **Git-backed** - Messages persist across sessions via git commits
- **Cross-repo support** - Can be used in any repository with this structure

## Message Format

Each line in `messages.jsonl` is a complete JSON object with the following structure:

```json
{
  "id": "msg-a1b2c3d4",
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

### Required Fields

- **id** - Unique message identifier (e.g., `msg-{uuid}`)
- **from** - Sender information with agent name, repo path, and branch
- **to** - Recipient information with agent name and optional repo path
- **subject** - Message subject line
- **body** - Message content
- **timestamp** - ISO 8601 timestamp in UTC

### Optional Fields

- **threadId** - ID of parent message for threading
- **metadata** - Additional key-value data

## Usage

### Direct File Access

The simplest way to use this messaging system is through direct file I/O:

```python
import json
from pathlib import Path
from datetime import datetime, timezone
import uuid

# Append a new message
def write_message(repo_path: Path, message: dict):
    messages_file = repo_path / ".mcp_mail" / "messages.jsonl"
    
    # Add required fields
    message["id"] = f"msg-{uuid.uuid4()}"
    message["timestamp"] = datetime.now(timezone.utc).isoformat()
    
    # Atomic append
    with messages_file.open("a") as f:
        f.write(json.dumps(message) + "\n")

# Read all messages
def read_messages(repo_path: Path) -> list[dict]:
    messages_file = repo_path / ".mcp_mail" / "messages.jsonl"
    messages = []
    
    with messages_file.open() as f:
        for line in f:
            if line.strip():
                messages.append(json.loads(line))
    
    return messages
```

### Using MCP Agent Mail Server

For more advanced features (filtering, threading, recipients), use the MCP Agent Mail server tools:

```python
from mcp import ClientSession
from mcp.client.stdio import stdio_client

# Connect to MCP server
async with stdio_client() as (read, write):
    async with ClientSession(read, write) as session:
        # Initialize server
        await session.initialize()
        
        # Send message using MCP tool
        result = await session.call_tool(
            "send_message",
            {
                "project_key": "my-project",
                "sender_name": "my-agent",
                "to": ["recipient-agent"],
                "subject": "Hello",
                "body": "Message content"
            }
        )
```

### Available MCP Tools

When using the `mcp_agent_mail` server, these tools are available:

- **send_message** - Send a message to one or more agents
- **list_messages** - List messages with filtering options
- **get_message** - Read a specific message by ID
- **search_messages** - Search messages by content or metadata

## Parallel Access

The JSONL format naturally supports concurrent writes:

- **Atomic appends** - Multiple agents can append simultaneously using O_APPEND
- **No locking required** - File system handles append atomicity
- **Collision-free IDs** - UUID-based message IDs prevent conflicts

## Git Integration

Messages are tracked in git for persistence:

```bash
# Commit new messages
cd /path/to/repo
git add .mcp_mail/messages.jsonl
git commit -m "Add new messages"

# Sync with remote
git pull --rebase
git push

# View message history
git log -p .mcp_mail/messages.jsonl
```
