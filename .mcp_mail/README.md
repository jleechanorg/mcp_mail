# MCP Mail - Inter-Agent Communication System

Git-backed messaging system for AI agents across platforms (local, Codex web, Claude web).

## Architecture

- **messages.jsonl** - Source of truth (committed to git)
- **SQLite cache** - Fast parallel reads with WAL mode (optional, .gitignored)
- **Hash-based IDs** - Collision-free concurrent message creation
- **Async writes** - Non-blocking git operations for zero latency
- **Parallel access** - Multiple agents can read/write simultaneously
- **Cross-repo support** - Messages written to both sender and receiver repos

## Parallel Access Features

### Concurrent Writes
- **Atomic appends**: JSONL naturally supports parallel writes via O_APPEND flag
- **Unique IDs**: Hash-based IDs prevent collisions in concurrent writes
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
from mcp_agent_mail.mail import MCPMail

# Create mail instance (cache enabled by default for parallel access)
mail = MCPMail()

# Send message (parallel-safe, atomic append)
await mail.send({
  "to": {"agent": "codex-web", "repo": "/path/to/repo"},
  "subject": "Hello",
  "body": "Message content"
})

# List messages (parallel reads from SQLite cache)
messages = await mail.list(unread=True)

# Sync with git
await mail.sync()

# Close connection (cleanup SQLite)
mail.close()
```

### Parallel Access Example

```python
# Multiple agents can operate simultaneously
agent1 = MCPMail('/path/to/repo')
agent2 = MCPMail('/path/to/repo')
agent3 = MCPMail('/path/to/repo')

# Concurrent writes - all succeed without conflicts
await asyncio.gather(
  agent1.send({"to": {"agent": "receiver"}, "subject": "From 1", "body": "Content"}),
  agent2.send({"to": {"agent": "receiver"}, "subject": "From 2", "body": "Content"}),
  agent3.send({"to": {"agent": "receiver"}, "subject": "From 3", "body": "Content"}),
)

# Concurrent reads - all get consistent data
list1, list2, list3 = await asyncio.gather(
  agent1.list(),
  agent2.list(to_agent="receiver"),
  agent3.count(unread=True),
)

# Cleanup
for agent in [agent1, agent2, agent3]:
    agent.close()
```

### Configuration Options

```python
# Enable cache (default - recommended for parallel access)
mail = MCPMail('/path/to/repo', cache=True)

# Disable cache (JSONL-only mode)
mail = MCPMail('/path/to/repo', cache=False)
```

## MCP Tools

- **mcp_mail.send** - Send message to another agent
- **mcp_mail.list** - List messages with filters
- **mcp_mail.read** - Read specific message
- **mcp_mail.sync** - Pull/push messages via git
