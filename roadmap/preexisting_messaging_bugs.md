# Pre-Existing Messaging Bugs (origin/main)

**Documentation Date**: 2025-11-07
**Discovered During**: PR #13 review
**Status**: Pre-existing in origin/main, not introduced by PR #13

## Overview

Two messaging bugs were discovered during PR #13 review. Both bugs exist in `origin/main` and are NOT new regressions introduced by the agent retirement/naming work.

---

## Bug #1: Auto-Register Local Recipients Never Succeeds

**Severity**: 🔴 Critical (Feature completely broken)
**Status**: Pre-existing in origin/main
**File**: `src/mcp_agent_mail/app.py`
**Lines**: 3136-3157 (origin/main), 3310-3331 (PR #13)

### Issue

The `send_message` tool has an "auto-register missing local recipients" feature that never works due to stale lookup dictionary.

**Root Cause**:
```python
# Step 1: Build local_lookup once at the start (line ~3090)
async with get_session() as sx:
    existing = await sx.execute(
        select(Agent.name).where(
            Agent.project_id == project.id,
            cast(Any, Agent.is_active).is_(True),
        )
    )
    local_lookup: dict[str, str] = {}
    for row in existing.fetchall():
        canonical_name = (row[0] or "").strip()
        if not canonical_name:
            continue
        normalized = canonical_name.lower()
        local_lookup[normalized] = canonical_name

# ... much later (line ~3310) ...

# Step 2: Try to auto-register missing recipients
newly_registered: set[str] = set()
for missing in list(unknown_local):
    try:
        _ = await _get_or_create_agent(
            project,
            missing,
            sender.program,
            sender.model,
            sender.task_description,
            settings_local,
        )
        newly_registered.add(missing)  # Agent created successfully
    except Exception:
        pass

# Step 3: Try to re-route the newly registered agents
if newly_registered:
    from contextlib import suppress
    with suppress(_ContactBlocked):
        await _route(list(newly_registered), "to")  # ❌ FAILS - local_lookup never updated!
```

**Why It Fails**:
1. `local_lookup` is built once at the beginning from pre-existing agents
2. `_get_or_create_agent()` creates new agents in the database
3. `local_lookup` dictionary is **never refreshed** with the new agents
4. `_route()` uses the stale `local_lookup` to resolve names
5. Newly registered names still can't be found → `unknown_local` stays populated
6. Tool raises `RECIPIENT_NOT_FOUND` even though agents were just created

### Impact

- Users cannot send messages to recipients that don't exist yet, even with auto-register enabled
- The feature appears to work (no error during registration) but then fails at routing
- Error message is misleading: "recipient not found" even though it was just created

### Fix Required

**Option A: Refresh the lookup dictionary after registration**
```python
# After creating new agents, rebuild local_lookup
if newly_registered:
    async with get_session() as refresh_sx:
        refreshed = await refresh_sx.execute(
            select(Agent.name).where(
                Agent.project_id == project.id,
                cast(Any, Agent.is_active).is_(True),
            )
        )
        # Update local_lookup with newly registered agents
        for row in refreshed.fetchall():
            canonical_name = (row[0] or "").strip()
            if canonical_name and canonical_name in newly_registered:
                normalized = canonical_name.lower()
                local_lookup[normalized] = canonical_name

    # Now re-route will work
    with suppress(_ContactBlocked):
        await _route(list(newly_registered), "to")
```

**Option B: Manually append to local_lookup**
```python
# After each successful creation
for missing in list(unknown_local):
    try:
        agent = await _get_or_create_agent(...)
        newly_registered.add(missing)
        # Add to lookup immediately
        local_lookup[missing.lower()] = agent.name
    except Exception:
        pass
```

### Test Case Required

```python
async def test_auto_register_missing_recipients():
    """Test that send_message can auto-register missing local recipients."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create project and sender
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test"})
        await client.call_tool("register_agent", arguments={
            "project_key": "/tmp/test",
            "program": "claude-code",
            "model": "sonnet-4.5",
            "name": "Sender"
        })

        # Send message to non-existent recipient (should auto-register)
        result = await client.call_tool("send_message", arguments={
            "project_key": "/tmp/test",
            "sender_name": "Sender",
            "to": ["NonExistentRecipient"],  # This recipient doesn't exist yet
            "subject": "Test",
            "body_md": "Testing auto-register"
        })

        # Should succeed (not raise RECIPIENT_NOT_FOUND)
        assert result.data["count"] == 1

        # Verify recipient was auto-registered
        inbox = await client.call_tool("fetch_inbox", arguments={
            "project_key": "/tmp/test",
            "agent_name": "NonExistentRecipient",
            "limit": 1
        })
        assert len(inbox.data) == 1
        assert inbox.data[0]["subject"] == "Test"
```

---

## Bug #2: Auto-Handshake AgentLink Creation Uses Wrong Project IDs

**Severity**: 🔴 Critical (Feature completely broken)
**Status**: Pre-existing in origin/main
**File**: `src/mcp_agent_mail/app.py`
**Lines**: 3912-3916 (origin/main), 4094-4098 (PR #13)

### Issue

The `respond_contact` tool creates `AgentLink` records with incorrect project IDs, making cross-project messaging impossible via auto-handshake.

**Root Cause**:
```python
async def respond_contact(
    ctx: Context,
    project_key: str,        # Responder's project
    to_agent: str,           # Responder agent
    from_agent: str,         # Requester agent
    accept: bool,
    from_project: Optional[str] = None,  # Requester's project
):
    project = await _get_project_by_identifier(project_key)  # Responder's project
    a_project = project if not from_project else await _get_project_by_identifier(from_project)  # Requester's project
    a = await _get_agent(a_project, from_agent)  # Requester agent
    b = await _get_agent(project, to_agent)      # Responder agent

    # ... later when creating new link ...

    s.add(AgentLink(
        a_project_id=project.id or 0,      # ❌ WRONG! This is responder's project
        a_agent_id=a.id or 0,              # ✓ Requester's agent (correct)
        b_project_id=project.id or 0,      # ❌ WRONG! Both are responder's project
        b_agent_id=b.id or 0,              # ✓ Responder's agent (correct)
        status="approved",
        ...
    ))
```

**Why It Fails**:
1. Both `a_project_id` and `b_project_id` are set to `project.id` (responder's project)
2. This makes the link "self-referential" - both sides point to the same project
3. Later, when routing messages, the system looks for links where `a_project_id == sender_project.id`
4. If sender is in `a_project` (requester's project), the link won't be found because both IDs point to `project` (responder's project)
5. Message routing fails with `RECIPIENT_NOT_FOUND` even though handshake was "approved"

### Correct Behavior

The AgentLink should link **two different projects**:
```python
s.add(AgentLink(
    a_project_id=a_project.id or 0,    # ✅ Requester's project
    a_agent_id=a.id or 0,              # ✅ Requester's agent
    b_project_id=project.id or 0,      # ✅ Responder's project
    b_agent_id=b.id or 0,              # ✅ Responder's agent
    status="approved",
    ...
))
```

### Impact

- Cross-project auto-handshake never works
- `macro_contact_handshake(auto_accept=True)` creates links that are invisible to routing
- Users get `RECIPIENT_NOT_FOUND` even after successful handshake approval
- The bug is silent - no error during link creation, only during message routing

### Routing Code That Fails

```python
# src/mcp_agent_mail/app.py lines ~3198-3208
# This query looks for links where sender's project is 'a' side
result = await sx.execute(
    select(AgentLink, Project, Agent).where(
        AgentLink.a_project_id == project.id,  # Sender's project ID
        # ...
    )
)

# If AgentLink has both a_project_id and b_project_id == responder's project,
# and sender is in requester's project, this query returns nothing!
```

### Fix Required

```python
async def respond_contact(
    ctx: Context,
    project_key: str,
    to_agent: str,
    from_agent: str,
    accept: bool,
    from_project: Optional[str] = None,
    ttl_seconds: int = 30 * 24 * 3600,
):
    project = await _get_project_by_identifier(project_key)
    a_project = project if not from_project else await _get_project_by_identifier(from_project)
    a = await _get_agent(a_project, from_agent)
    b = await _get_agent(project, to_agent)

    # ... existing code ...

    else:
        if accept:
            s.add(AgentLink(
                a_project_id=a_project.id or 0,  # ✅ FIXED: Use requester's project
                a_agent_id=a.id or 0,
                b_project_id=project.id or 0,    # ✅ FIXED: Use responder's project
                b_agent_id=b.id or 0,
                status="approved",
                reason="",
                created_ts=now,
                updated_ts=now,
                expires_ts=exp,
            ))
            updated = 1
```

### Test Case Required

```python
async def test_auto_handshake_enables_cross_project_messaging():
    """Test that macro_contact_handshake allows subsequent send_message to succeed."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Create two projects
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project_a"})
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/project_b"})

        # Register agents in each project
        await client.call_tool("register_agent", arguments={
            "project_key": "/tmp/project_a",
            "program": "claude-code",
            "model": "sonnet-4.5",
            "name": "AgentA"
        })
        await client.call_tool("register_agent", arguments={
            "project_key": "/tmp/project_b",
            "program": "claude-code",
            "model": "sonnet-4.5",
            "name": "AgentB"
        })

        # Auto-handshake from A to B
        handshake_result = await client.call_tool("macro_contact_handshake", arguments={
            "project_key": "/tmp/project_a",
            "requester": "AgentA",
            "target": "AgentB",
            "to_project": "/tmp/project_b",
            "auto_accept": True
        })
        assert handshake_result.data["status"] == "approved"

        # Now send message from A to B (should succeed)
        message_result = await client.call_tool("send_message", arguments={
            "project_key": "/tmp/project_a",
            "sender_name": "AgentA",
            "to": ["project:/tmp/project_b#AgentB"],  # Cross-project addressing
            "subject": "Test cross-project message",
            "body_md": "This should work after handshake"
        })

        # Should succeed (not raise RECIPIENT_NOT_FOUND)
        assert message_result.data["count"] == 1

        # Verify AgentB received the message
        inbox = await client.call_tool("fetch_inbox", arguments={
            "project_key": "/tmp/project_b",
            "agent_name": "AgentB",
            "limit": 1
        })
        assert len(inbox.data) == 1
        assert inbox.data[0]["from"] == "AgentA"
```

---

## Verification Against origin/main

Both bugs were verified to exist in `origin/main` by checking the exact same code:

### Bug #1 Verification
```bash
git show origin/main:src/mcp_agent_mail/app.py | sed -n '3136,3157p'
# Shows identical code pattern - local_lookup never refreshed
```

### Bug #2 Verification
```bash
git show origin/main:src/mcp_agent_mail/app.py | sed -n '3912,3916p'
# Shows:
# a_project_id=project.id or 0,  # WRONG
# b_project_id=project.id or 0,  # WRONG
```

---

## Recommendation

**For PR #13**:
- ❌ **DO NOT FIX** these bugs in PR #13
- ✅ Document them in roadmap (this file)
- ✅ Communicate to reviewers that these are pre-existing

**For Future PRs**:
1. Create separate PR to fix Bug #1 (auto-register lookup refresh)
2. Create separate PR to fix Bug #2 (AgentLink project IDs)
3. Add comprehensive test coverage for both features
4. Consider adding integration tests that validate end-to-end flows

---

## Priority

Both bugs are **Critical** severity but can be addressed post-merge of PR #13 since:
1. They exist in production (origin/main) already
2. PR #13 does not make them worse
3. They are distinct from the agent retirement/naming changes
4. Fixing them requires careful testing to avoid introducing new issues

---

## Related Issues

- The auto-register feature was likely introduced in commit 1d1089d
- The contact enforcement removal work may have exposed these bugs
- Both features may not have had comprehensive end-to-end tests

---

## Next Steps

1. ✅ Document bugs in roadmap (this file)
2. ✅ Notify mv that these are pre-existing
3. Create GitHub issues for tracking
4. Assign to appropriate developer for fix
5. Add test cases before implementing fixes
6. Consider feature flag for auto-register until fixed
