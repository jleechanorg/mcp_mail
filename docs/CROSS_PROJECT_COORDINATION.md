# Cross-Project Coordination Patterns

This guide explains how to coordinate agents working across different parts of a codebase (e.g., frontend and backend, multiple microservices, etc.).

## About This Guide

**Example Format**: Code examples use simplified pseudo-JSON for clarity. Your MCP client library handles the actual JSON-RPC protocol - focus on understanding the tool calls and architectural patterns shown here.

## Current State: Global Agent Namespace

**IMPORTANT:** Agent names are **globally unique** across ALL projects (case-insensitive).

This means:

- An agent named "BlueLake" can only exist **once** across the entire system
- Agents can discover and message **any other agent** regardless of project boundaries
- Projects serve as **organizational containers** for archiving and context, not as access control boundaries
- `resource://agents` is the **canonical endpoint** for discovering all agents globally

**Example of how agents work:**

```
Project A: /data/projects/frontend
  - Agent: "FrontendDev"

Project B: /data/projects/backend
  - Agent: "BackendDev"

Result: FrontendDev and BackendDev CAN communicate freely!
        Both appear in resource://agents (global directory)
```

## Agent Discovery

### Primary Method: Global Agent Directory (RECOMMENDED)

Use `resource://agents` to discover all agents across all projects:

```json
{"resource": "resource://agents", "method": "read"}
```

**Response:**
```json
{
  "agents": [
    {
      "name": "BackendDev",
      "program": "claude-code",
      "model": "opus-4.1",
      "task_description": "API development",
      "project_slug": "my-app-abc123",
      "project_human_key": "my-app",
      "inception_ts": "2025-10-25T12:00:00Z",
      "last_active_ts": "2025-10-25T12:34:56Z",
      "unread_count": 3
    },
    {
      "name": "FrontendDev",
      "program": "claude-code",
      "model": "sonnet-4.5",
      "project_slug": "my-app-abc123",
      "project_human_key": "my-app",
      "inception_ts": "2025-10-25T11:00:00Z",
      "last_active_ts": "2025-10-25T12:10:00Z",
      "unread_count": 0
    },
    {
      "name": "DatabaseAdmin",
      "program": "claude-code",
      "project_slug": "db-service-def456",
      "project_human_key": "db-service",
      "model": "gpt5",
      "inception_ts": "2025-10-20T08:15:00Z",
      "last_active_ts": "2025-10-25T09:45:00Z",
      "unread_count": 1
    }
  ],
  "total": 3
}
```

### Secondary Method: Project-Scoped View (Deprecated)

`resource://agents/{project_key}` still works but shows a filtered view only:

```json
{"resource": "resource://agents/my-app", "method": "read"}
```

**Note:** This endpoint is **deprecated**. Use `resource://agents` for complete discovery.

## Messaging Across Projects

### Direct Messaging (RECOMMENDED)

Agents can message any other agent directly by name:

```json
{
  "tool": "send_message",
  "arguments": {
    "project_key": "/data/projects/frontend",
    "sender_name": "FrontendDev",
    "to": ["BackendDev"],
    "subject": "API contract question",
    "body_md": "What's the format for the /api/users response?"
  }
}
```

**Key Points:**
- The `to` field accepts any registered agent name
- No need for project prefixes or special addressing
- Messages are delivered regardless of which project the recipient is registered in

### Cross-Project Addressing (Alternative)

For explicit cross-project messaging, you can use the `project:slug#AgentName` format:

```json
{
  "tool": "send_message",
  "arguments": {
    "project_key": "/data/projects/frontend",
    "sender_name": "FrontendDev",
    "to": ["project:backend#BackendDev"],
    "subject": "Need API coordination",
    "body_md": "Let's discuss the upcoming changes..."
  }
}
```

**Note:** This format is optional - simple agent names work just as well since agents are globally unique.

## Projects: Organizational Containers

Projects now serve primarily as:

1. **Archive Organization** - Messages and agent profiles are stored in project-specific directories
2. **Contextual Grouping** - Helps organize agents working on related codebases
3. **Human-Readable Identification** - The `human_key` provides meaningful project names
4. **Git History** - Each project has its own archive with commit history

### When to Use Multiple Projects

Use multiple projects when you want:

- **Logical Separation** - Keep frontend and backend message archives separate
- **Different Codebases** - Each repository can have its own project
- **Team Organization** - Organize agents by team or domain

#### Example: Monorepo with Logical Separation

```text
Project A: /data/projects/my-app/frontend
  - Agent: "FrontendDev"
  - Archives: UI component discussions

Project B: /data/projects/my-app/backend
  - Agent: "BackendDev"
  - Archives: API development discussions

Both agents can freely communicate!
```

### When to Use a Single Project

Use a single shared project when you want:

- **Unified Archive** - All messages in one place
- **Simplified Setup** - Single project key for all operations
- **Shared Thread Context** - All agents see the same thread history

#### Example: Unified Project

```text
Project: /data/projects/my-app
  - Agent: "FrontendDev"
  - Agent: "BackendDev"
  - Agent: "DatabaseAdmin"
  - Agent: "DevOpsEngineer"

All agents share the same archive.
```

## Registration Patterns

### Pattern 1: Separate Projects, Global Communication

```json
// FrontendDev registers in frontend project
{
  "tool": "register_agent",
  "arguments": {
    "project_key": "/data/projects/frontend",
    "name": "FrontendDev",
    "program": "claude-code",
    "model": "sonnet-4.5",
    "task_description": "React UI development"
  }
}

// BackendDev registers in backend project
{
  "tool": "register_agent",
  "arguments": {
    "project_key": "/data/projects/backend",
    "name": "BackendDev",
    "program": "codex-cli",
    "model": "gpt5-codex",
    "task_description": "API development"
  }
}

// They can now communicate directly!
{
  "tool": "send_message",
  "arguments": {
    "sender_name": "FrontendDev",
    "to": ["BackendDev"],
    "subject": "API question"
  }
}
```

### Pattern 2: Single Project, Multiple Agents

```json
// Both agents register in the same project
{
  "tool": "register_agent",
  "arguments": {
    "project_key": "/data/projects/my-app",
    "name": "FrontendDev",
    "task_description": "React UI components"
  }
}

{
  "tool": "register_agent",
  "arguments": {
    "project_key": "/data/projects/my-app",
    "name": "BackendDev",
    "task_description": "API endpoints"
  }
}
```

## Best Practices

### DO: Use resource://agents for Discovery

```json
// Good: Global discovery
{"resource": "resource://agents"}
```

### DO: Use Descriptive, Globally Unique Names

```json
// Good: Clear, unique names
"FrontendUIComponents", "BackendAPIServices", "DatabaseMigrations"
```

### DON'T: Use Generic Names

```json
// Bad: Will conflict with other users
"Claude", "Agent1", "Helper"
```

### DO: Use whois for Agent Verification

```json
{
  "tool": "whois",
  "arguments": {
    "project_key": "/data/projects/my-app",
    "agent_name": "BackendDev"
  }
}
```

The `whois` tool searches globally and provides helpful suggestions if the agent isn't found.

## File Reservations

File reservations are **project-scoped** for organizational purposes, but agents can coordinate across projects via messaging:

```json
// FrontendDev reserves UI files in frontend project
{
  "tool": "file_reservation_paths",
  "arguments": {
    "project_key": "/data/projects/frontend",
    "agent_name": "FrontendDev",
    "paths": ["src/components/*.tsx"],
    "reason": "Redesigning user profile"
  }
}

// BackendDev reserves API files in backend project
{
  "tool": "file_reservation_paths",
  "arguments": {
    "project_key": "/data/projects/backend",
    "agent_name": "BackendDev",
    "paths": ["api/users/*.py"],
    "reason": "Adding OAuth support"
  }
}

// Coordinate via messaging if there's overlap
{
  "tool": "send_message",
  "arguments": {
    "sender_name": "FrontendDev",
    "to": ["BackendDev"],
    "subject": "Coordinating shared types",
    "body_md": "I'm updating UserProfile component - let me know when API changes are done."
  }
}
```

## Sibling Projects (UI Feature)

The web dashboard can identify potentially related projects and display them with badges for easier navigation:

- **Sibling suggestions** appear based on naming patterns and AI analysis
- **Confirming a sibling link** adds navigation badges (UI convenience only)
- **This does NOT affect messaging** - agents can always communicate regardless of sibling status

## Summary

**Key Changes from Previous Versions:**

| Feature | Previous | Current |
|---------|----------|---------|
| Agent Names | Per-project unique | **Globally unique** |
| Cross-Project Messaging | Not supported | **Fully supported** |
| Agent Discovery | `resource://agents/{project}` | **`resource://agents`** (global) |
| Projects | Isolation boundaries | **Organizational containers** |

**When in doubt:**
- Use `resource://agents` to find agents
- Send messages directly to agent names (no project prefix needed)
- Projects are for organization, not access control

For more information:
- [AGENT_ONBOARDING.md](./AGENT_ONBOARDING.md) - Step-by-step agent workflows
- [README.md](./README.md) - Full system documentation
