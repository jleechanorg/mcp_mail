# Manual Test Plan - MCP Agent Mail
**Date**: 2025-11-13
**Current Version**: 0.1.2
**Branch**: dev1763066046 (commit 3c28767)
**Baseline**: Assumes running server may be on earlier PyPI package

## Executive Summary

This manual test plan covers all significant code changes between the potentially deployed server (PyPI package) and current HEAD (3c28767). The focus is on new features, bug fixes, performance improvements, and integration points that require manual validation beyond automated tests.

## Recent Changes Overview

### Major Features (Since ~Nov 8, 2025)
1. **NEW: search_mailbox tool** (PR #13) - FTS5 full-text search across messages
2. **FIX: since_ts filtering** (PR #32) - Fixed in fetch_inbox, fetch_outbox, global inbox
3. **IMPROVE: Agent registration** - Enhanced force_reclaim and conflict handling
4. **DEFAULT: .mcp_mail/ storage** - Project-local storage now default
5. **OPTIMIZE: fetch_inbox performance** - Database-level optimizations
6. **FIX: Agent filter scope** - Corrected search tool agent filtering

### Bug Fixes
- `since_ts` filter correctly applies BEFORE limit (was applying after)
- Agent filter in search_mailbox now scopes correctly to project
- Tool result wrapping consistency across all tools
- Pre-commit hooks configuration fixed

## Test Environment Setup

### Prerequisites
```bash
# 1. Stop any running MCP servers
kill <PID_from_previous_run>

# 2. Start fresh server from local source (testing current HEAD)
bash -lc "cd /Users/jleechan/mcp_agent_mail && ./scripts/run_server_with_token.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"
# Save the PID for later cleanup

# 3. Verify server is running
tail -f /tmp/mcp_agent_mail_server.log
# Look for "MCP Agent Mail server started" message

# 4. Launch Claude Code or Claude Desktop
# The MCP client will connect to http://127.0.0.1:8765/mcp/
```

### Test Projects
Create two test projects to validate cross-project functionality:
- `test_project_alpha` - Primary test project
- `test_project_beta` - Secondary for cross-project scenarios

## Test Scenarios

---

## 1. NEW FEATURE: search_mailbox Tool

### Test 1.1: Basic Search Functionality
**Priority**: 🔴 Critical
**Feature**: New search_mailbox tool
**Changed Files**: `src/mcp_agent_mail/app.py:4156-4407`

**Setup**:
1. Create project and register agent "SearchTester"
2. Send 5 messages with different keywords:
   - "authentication bug in login"
   - "database performance optimization"
   - "authentication feature request"
   - "frontend styling issue"
   - "database migration planning"

**Test Steps**:
```python
# Via MCP client or Claude Code:
# 1. Search for single keyword
result = search_mailbox(
    project_key="test_project_alpha",
    query="authentication",
    limit=10,
    include_bodies=True
)
# Expected: 2 results (bug + feature request)

# 2. Search with AND operator
result = search_mailbox(
    project_key="test_project_alpha",
    query="database AND performance",
    limit=10
)
# Expected: 1 result (performance optimization)

# 3. Search with OR operator
result = search_mailbox(
    project_key="test_project_alpha",
    query="authentication OR database",
    limit=10
)
# Expected: 4 results

# 4. Search with NOT operator
result = search_mailbox(
    project_key="test_project_alpha",
    query="authentication NOT bug",
    limit=10
)
# Expected: 1 result (feature request only)

# 5. Phrase search
result = search_mailbox(
    project_key="test_project_alpha",
    query='"database performance"',
    limit=10
)
# Expected: 1 result (exact phrase match)
```

**Validation**:
- [ ] All searches return correct number of results
- [ ] Results include relevance snippets
- [ ] Results are ordered by relevance score
- [ ] Bodies are included when `include_bodies=True`
- [ ] Bodies are excluded when `include_bodies=False`
- [ ] FTS5 query syntax errors are handled gracefully

---

### Test 1.2: Agent Filter in Search
**Priority**: 🔴 Critical
**Feature**: Agent-scoped search
**Bug Fix**: Commit 7aeed43 - Fixed agent filter scope

**Setup**:
1. Register two agents: "Alice" and "Bob"
2. Send 3 messages from Alice about "testing"
3. Send 2 messages from Bob about "testing"

**Test Steps**:
```python
# 1. Search without agent filter
result = search_mailbox(
    project_key="test_project_alpha",
    query="testing",
    limit=10
)
# Expected: 5 results (all messages)

# 2. Search with agent filter for Alice
result = search_mailbox(
    project_key="test_project_alpha",
    query="testing",
    agent_filter="Alice",
    limit=10
)
# Expected: 3 results (only Alice's messages)

# 3. Search with agent filter for Bob
result = search_mailbox(
    project_key="test_project_alpha",
    query="testing",
    agent_filter="Bob",
    limit=10
)
# Expected: 2 results (only Bob's messages)

# 4. Search with invalid agent filter
result = search_mailbox(
    project_key="test_project_alpha",
    query="testing",
    agent_filter="NonExistentAgent",
    limit=10
)
# Expected: Error or 0 results with clear message
```

**Validation**:
- [ ] Agent filter correctly scopes to project
- [ ] Agent filter case-insensitive matching works
- [ ] Invalid agent names handled gracefully
- [ ] Error messages are clear and actionable

---

### Test 1.3: Global Mailbox Priority
**Priority**: 🟠 High
**Feature**: Global mailbox search prioritization

**Setup**:
1. Register agent "Coordinator"
2. Send 3 messages to global inbox (all agents in project)
3. Send 2 messages to specific agents (inbox only)

**Test Steps**:
```python
result = search_mailbox(
    project_key="test_project_alpha",
    query="coordination",
    limit=10,
    include_bodies=True
)
# Inspect result order
```

**Validation**:
- [ ] Global mailbox messages appear first in results
- [ ] Relevance scoring still applies within global/specific groups
- [ ] Snippet highlighting works for all message types

---

## 2. BUG FIX: since_ts Filtering

### Test 2.1: fetch_inbox with since_ts
**Priority**: 🔴 Critical
**Bug Fix**: Commit 4618047 - since_ts applied before limit
**Changed Files**: `src/mcp_agent_mail/app.py:2021-2031`

**Setup**:
1. Register agent "InboxTester"
2. Send 10 messages at T0 (initial time)
3. Wait 2 seconds
4. Send 5 more messages at T1

**Test Steps**:
```python
# 1. Fetch without since_ts, limit 8
result = fetch_inbox(
    project_key="test_project_alpha",
    agent_name="InboxTester",
    limit=8,
    include_bodies=False
)
# Expected: 8 most recent messages (5 from T1 + 3 from T0)
assert len(result) == 8

# 2. Fetch with since_ts=T0, limit 8
result = fetch_inbox(
    project_key="test_project_alpha",
    agent_name="InboxTester",
    since_ts="<T0_ISO_TIMESTAMP>",
    limit=8,
    include_bodies=False
)
# Expected: 5 messages from T1 (not 8)
# This verifies since_ts filters BEFORE limit is applied
assert len(result) == 5

# 3. Fetch with since_ts=T1, limit 8
result = fetch_inbox(
    project_key="test_project_alpha",
    agent_name="InboxTester",
    since_ts="<T1_ISO_TIMESTAMP>",
    limit=8,
    include_bodies=False
)
# Expected: 0 messages (all messages are at or before T1)
assert len(result) == 0
```

**Validation**:
- [ ] since_ts filters messages correctly
- [ ] Limit is applied AFTER since_ts filter
- [ ] ISO8601 timestamp parsing works correctly
- [ ] Invalid timestamps handled gracefully

---

### Test 2.2: fetch_outbox with since_ts
**Priority**: 🟠 High
**Bug Fix**: Commit 4618047
**Changed Files**: `src/mcp_agent_mail/app.py:2054-2063`

**Setup**:
Same as Test 2.1, but test outbox instead of inbox

**Test Steps**:
```python
# Similar to Test 2.1 but using fetch_outbox
# Verify that sent messages are filtered correctly by since_ts
```

**Validation**:
- [ ] Outbox since_ts filtering works correctly
- [ ] Limit applied after since_ts filter

---

### Test 2.3: Global Inbox Mention Search with since_ts
**Priority**: 🟡 Medium
**Bug Fix**: Commit 4618047
**Changed Files**: `src/mcp_agent_mail/app.py:1970-1981`

**Setup**:
1. Register agent "MentionTester"
2. Send 10 messages mentioning "@MentionTester" at T0
3. Wait 2 seconds
4. Send 5 messages mentioning "@MentionTester" at T1

**Test Steps**:
```python
# Internal function test via fetch_inbox with urgent_only flag
# Or test directly if exposed
```

**Validation**:
- [ ] Mention search filters by since_ts correctly
- [ ] Limit applied after since_ts filter

---

## 3. IMPROVEMENT: Agent Registration

### Test 3.1: force_reclaim Parameter
**Priority**: 🟠 High
**Feature**: Enhanced agent name conflict handling
**Changed Files**: Commits dc727b4, c64b522

**Setup**:
1. Create two projects: "proj_a" and "proj_b"
2. Register agent "SharedName" in proj_a

**Test Steps**:
```python
# 1. Try to register "SharedName" in proj_b without force_reclaim
result = register_agent(
    project_key="proj_b",
    name="SharedName",
    program="test-cli",
    model="gpt4",
    force_reclaim=False
)
# Expected: Error message about name conflict, suggests force_reclaim

# 2. Register "SharedName" in proj_b WITH force_reclaim
result = register_agent(
    project_key="proj_b",
    name="SharedName",
    program="test-cli",
    model="gpt4",
    force_reclaim=True
)
# Expected: Success, agent registered in proj_b

# 3. Verify original agent in proj_a is retired
# Check via whois or list agents in proj_a
```

**Validation**:
- [ ] Error message without force_reclaim is clear and actionable
- [ ] force_reclaim successfully retires conflicting agent
- [ ] Retired agent has is_active=False
- [ ] Retired agent has deleted_ts set
- [ ] New agent is active in target project

---

### Test 3.2: Agent Reactivation
**Priority**: 🔴 Critical
**Bug**: Previously created duplicates (Bug #3 from pr13_preexisting_bugs.md)
**Status**: Check if fixed in current HEAD

**Setup**:
1. Register agent "Reactivator" in proj_a
2. Force retire it by registering "Reactivator" in proj_b with force_reclaim
3. Register "Reactivator" back in proj_a

**Test Steps**:
```python
# 1. Initial registration
register_agent(project_key="proj_a", name="Reactivator", ...)

# 2. Retire by claiming in proj_b
register_agent(project_key="proj_b", name="Reactivator", ..., force_reclaim=True)

# 3. Re-register in proj_a
register_agent(project_key="proj_a", name="Reactivator", ...)

# 4. Query database to check for duplicates
# Should find exactly 1 agent record for "Reactivator" in proj_a
# That record should be active (not a new duplicate)
```

**Validation**:
- [ ] No duplicate agent records created
- [ ] Original agent record is reactivated
- [ ] is_active=True after reactivation
- [ ] deleted_ts=None after reactivation
- [ ] Program/model/task updated correctly

---

### Test 3.3: Conflict Info Helper
**Priority**: 🟡 Medium
**Improvement**: Code refactoring for consistency
**Changed Files**: Commit c64b522

**Test Steps**:
```python
# Trigger various conflict scenarios and verify error messages are consistent:
# 1. Name conflict during registration
# 2. Race condition during concurrent registration
# 3. UPDATE path race condition

# All error messages should use the same format via _build_conflict_info()
```

**Validation**:
- [ ] Error messages are consistent across all conflict scenarios
- [ ] Error messages include helpful guidance
- [ ] No misleading suggestions about force_reclaim for same-project updates

---

## 4. DEFAULT CHANGE: .mcp_mail/ Storage

### Test 4.1: Project-Local Storage Default
**Priority**: 🟠 High
**Changed Files**: Commit 4ac6412

**Setup**:
1. Create a new project in a fresh directory
2. Register agent and send messages

**Test Steps**:
```bash
# 1. Verify .mcp_mail/ directory is created
ls -la /path/to/test_project/
# Expected: .mcp_mail/ directory exists

# 2. Check database location
ls -la /path/to/test_project/.mcp_mail/
# Expected: mcp_agent_mail.db exists

# 3. Check message storage
ls -la /path/to/test_project/.mcp_mail/messages/
# Expected: Message files organized by YYYY/MM/

# 4. Verify Git integration
cd /path/to/test_project/.mcp_mail/
git log --oneline
# Expected: Commits for agent registration, messages, etc.
```

**Validation**:
- [ ] .mcp_mail/ directory created automatically
- [ ] Database created in .mcp_mail/
- [ ] Message files stored in .mcp_mail/messages/
- [ ] Git repository initialized in .mcp_mail/
- [ ] Commits recorded for all operations

---

## 5. PERFORMANCE: fetch_inbox Optimization

### Test 5.1: Database-Level Query Optimization
**Priority**: 🟡 Medium
**Changed Files**: Commit ba85a92

**Setup**:
1. Create project with 1000 messages
2. Measure fetch_inbox performance

**Test Steps**:
```python
import time

# Warm up
fetch_inbox(project_key="perf_test", agent_name="PerfTester", limit=50)

# Measure performance
start = time.time()
result = fetch_inbox(project_key="perf_test", agent_name="PerfTester", limit=50)
elapsed = time.time() - start

print(f"fetch_inbox took {elapsed:.3f}s for 50 messages from 1000 total")
# Expected: < 100ms for simple queries
```

**Validation**:
- [ ] Query completes in reasonable time (< 100ms for 50 messages)
- [ ] No N+1 query issues
- [ ] Database indexes are used efficiently

---

## 6. INTEGRATION: End-to-End Workflows

### Test 6.1: Multi-Agent Coordination Workflow
**Priority**: 🔴 Critical
**Integration**: Tests search + messaging + agent management

**Scenario**: Three agents coordinate on a task
1. Agent "Planner" sends planning message to global inbox
2. Agent "Implementer" searches for "planning" and reads the message
3. Agent "Implementer" replies with implementation details
4. Agent "Reviewer" searches for "implementation" and finds the thread
5. Agent "Reviewer" replies in the thread

**Test Steps**:
```python
# 1. Register agents
register_agent(project_key="collab_test", name="Planner", ...)
register_agent(project_key="collab_test", name="Implementer", ...)
register_agent(project_key="collab_test", name="Reviewer", ...)

# 2. Planner sends planning message
send_message(
    project_key="collab_test",
    sender_name="Planner",
    to=["global"],  # or however global inbox is addressed
    subject="System Architecture Plan",
    body_md="## Architecture\n\n..."
)

# 3. Implementer searches and finds message
search_results = search_mailbox(
    project_key="collab_test",
    query="architecture plan",
    limit=10
)
# Verify: 1 result found

# 4. Implementer replies
reply_message(
    project_key="collab_test",
    message_id=<message_id_from_search>,
    sender_name="Implementer",
    body_md="## Implementation\n\n..."
)

# 5. Reviewer searches for implementation details
search_results = search_mailbox(
    project_key="collab_test",
    query="implementation",
    limit=10
)
# Verify: 1 result (the reply)

# 6. Reviewer replies in thread
reply_message(
    project_key="collab_test",
    message_id=<reply_message_id>,
    sender_name="Reviewer",
    body_md="## Review Feedback\n\n..."
)

# 7. Verify thread integrity
# All 3 messages should share the same thread_id
```

**Validation**:
- [ ] Search finds relevant messages
- [ ] Reply threading works correctly
- [ ] All messages have same thread_id
- [ ] Message order preserved
- [ ] All agents can access thread

---

### Test 6.2: Cross-Project Agent Migration
**Priority**: 🟡 Medium
**Integration**: Tests agent retirement across projects

**Scenario**: Agent moves between projects
1. Agent "Migrator" works in proj_a
2. Agent "Migrator" moves to proj_b (force_reclaim)
3. Original agent in proj_a is retired
4. Messages in proj_a still reference retired agent correctly

**Test Steps**:
```python
# 1. Create agent in proj_a and send messages
register_agent(project_key="proj_a", name="Migrator", ...)
send_message(project_key="proj_a", sender_name="Migrator", ...)

# 2. Move to proj_b
register_agent(project_key="proj_b", name="Migrator", ..., force_reclaim=True)

# 3. Verify proj_a agent retired
# whois or search should show is_active=False

# 4. Verify messages in proj_a still accessible
search_mailbox(project_key="proj_a", query="...", agent_filter="Migrator")
# Should still find messages from retired agent
```

**Validation**:
- [ ] Agent successfully moves between projects
- [ ] Original agent marked as retired
- [ ] Historical messages remain accessible
- [ ] Search includes retired agent messages
- [ ] No data loss during migration

---

## 7. ERROR HANDLING & EDGE CASES

### Test 7.1: Invalid FTS5 Query Syntax
**Priority**: 🟠 High
**Feature**: Graceful error handling in search

**Test Steps**:
```python
# Test various invalid FTS5 queries
invalid_queries = [
    '"unclosed quote',
    'AND OR NOT',
    '((unbalanced',
    '',  # empty query
    '   ',  # whitespace only
]

for query in invalid_queries:
    try:
        result = search_mailbox(
            project_key="test_project_alpha",
            query=query,
            limit=10
        )
        # Should either return empty results or raise clear error
    except Exception as e:
        # Error message should be user-friendly
        assert "FTS5" not in str(e) or "syntax" in str(e).lower()
```

**Validation**:
- [ ] Invalid queries don't crash server
- [ ] Error messages are user-friendly
- [ ] Empty/whitespace queries handled
- [ ] SQL injection attempts blocked

---

### Test 7.2: Large Result Sets
**Priority**: 🟡 Medium
**Feature**: Limit enforcement and pagination

**Setup**:
1. Create 200 messages in a project

**Test Steps**:
```python
# 1. Search without limit (should use default)
result = search_mailbox(
    project_key="large_project",
    query="test"
)
# Expected: Default limit applied (20)

# 2. Search with explicit limit
result = search_mailbox(
    project_key="large_project",
    query="test",
    limit=50
)
# Expected: 50 results max

# 3. Fetch inbox with limit
result = fetch_inbox(
    project_key="large_project",
    agent_name="Tester",
    limit=100
)
# Expected: 100 results max
```

**Validation**:
- [ ] Default limits applied correctly
- [ ] Explicit limits enforced
- [ ] Performance acceptable with large result sets
- [ ] No memory issues with large queries

---

### Test 7.3: Concurrent Operations
**Priority**: 🟡 Medium
**Feature**: Database locking and consistency

**Test Steps**:
```python
# Use multiple concurrent clients/agents
# 1. Register same agent name from two clients simultaneously
# 2. Send messages to same recipient simultaneously
# 3. Search while messages are being sent

# Verify no database locks or data corruption
```

**Validation**:
- [ ] No database lock errors
- [ ] No data corruption
- [ ] Race conditions handled gracefully
- [ ] Consistent results across clients

---

## 8. BACKWARDS COMPATIBILITY

### Test 8.1: Tool API Compatibility
**Priority**: 🔴 Critical
**Feature**: Ensure existing tools still work

**Test Steps**:
```python
# Test all existing tools with previous parameters:
# - ensure_project
# - register_agent
# - send_message
# - reply_message
# - fetch_inbox
# - mark_message_read
# - whois

# All should work without changes to client code
```

**Validation**:
- [ ] All existing tools work with previous parameters
- [ ] Optional new parameters don't break existing calls
- [ ] Response formats remain compatible

---

### Test 8.2: Storage Migration
**Priority**: 🟠 High
**Feature**: Existing projects work with new default storage

**Test Steps**:
```bash
# If you have an old project using global ~/.mcp_agent_mail/ storage:
# 1. Upgrade to new version
# 2. Access existing project
# 3. Verify messages still accessible
# 4. Verify can send new messages

# OR create project in old storage location and verify it still works
```

**Validation**:
- [ ] Existing projects continue to work
- [ ] No data migration required
- [ ] Both storage modes can coexist

---

## 9. DOCUMENTATION VALIDATION

### Test 9.1: CLAUDE.md Instructions
**Priority**: 🟡 Medium
**Changed Files**: Multiple documentation updates

**Test Steps**:
```bash
# Follow instructions in CLAUDE.md exactly:

# 1. Test PyPI package startup
bash -lc "cd /Users/jleechan/mcp_agent_mail && ./scripts/run_server_pypi.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"
# Verify: Server starts, logs written, PID returned

# 2. Test local source startup
bash -lc "cd /Users/jleechan/mcp_agent_mail && ./scripts/run_server_with_token.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"
# Verify: Server starts, logs written, PID returned

# 3. Test local build startup
bash -lc "cd /Users/jleechan/mcp_agent_mail && ./scripts/run_server_local_build.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"
# Verify: Server starts, logs written, PID returned

# 4. Test GitHub CLI instructions (if gh not installed)
# Follow gh CLI binary download instructions

# 5. Test slash commands
# Verify commands in claude-commands/.claude/commands/ are accessible
```

**Validation**:
- [ ] All startup scripts work as documented
- [ ] Log files created in correct location
- [ ] PID capture works
- [ ] GitHub CLI instructions accurate
- [ ] Slash commands accessible

---

## 10. REGRESSION TESTING

### Test 10.1: Known Fixed Bugs
**Priority**: 🔴 Critical
**Reference**: roadmap/pr13_preexisting_bugs.md

**Test Steps**:
Run tests to verify previously identified bugs are fixed:

1. **Bug #1: Missing .env file**
   - [ ] Tests run without .env file
   - [ ] Config gracefully handles missing .env

2. **Bug #2: deleted_ts serialization**
   - [ ] deleted_ts returns null (not "None" string) for active agents
   - [ ] JSON serialization correct

3. **Bug #3: Agent reactivation**
   - [ ] No duplicate agents created on reactivation
   - [ ] See Test 3.2 above

4. **Bug #4: _get_agent_by_id filters**
   - [ ] Retired agents not returned by _get_agent_by_id
   - [ ] Message contexts don't expose retired agents

5. **Bug #5: Test expectations**
   - [ ] test_agent_names_coerce_mode_auto_generates_unique_names fixed
   - [ ] All tests pass

---

## Test Execution Summary

### Critical Path (Must Test Before Release)
1. ✅ Test 1.1: Basic search functionality
2. ✅ Test 1.2: Agent filter in search
3. ✅ Test 2.1: fetch_inbox with since_ts
4. ✅ Test 3.1: force_reclaim parameter
5. ✅ Test 3.2: Agent reactivation (no duplicates)
6. ✅ Test 6.1: Multi-agent coordination workflow
7. ✅ Test 8.1: Tool API compatibility
8. ✅ Test 10.1: Known fixed bugs

### High Priority (Should Test)
- Test 1.3: Global mailbox priority
- Test 2.2: fetch_outbox with since_ts
- Test 4.1: Project-local storage default
- Test 7.1: Invalid FTS5 query syntax
- Test 8.2: Storage migration

### Medium Priority (Nice to Have)
- Test 2.3: Global inbox mention search
- Test 3.3: Conflict info helper
- Test 5.1: Database performance
- Test 6.2: Cross-project agent migration
- Test 7.2: Large result sets
- Test 7.3: Concurrent operations
- Test 9.1: Documentation validation

---

## Test Results Template

When executing tests, record results using this template:

```markdown
### Test X.Y: [Test Name]
**Date**: YYYY-MM-DD
**Tester**: [Name/Agent]
**Result**: ✅ PASS / ❌ FAIL / ⚠️ PARTIAL

**Observations**:
- [Finding 1]
- [Finding 2]

**Issues Found**:
- [Issue 1 - Severity - Description]

**Evidence**:
- [Log excerpts, screenshots, output]

**Follow-up Required**: [Yes/No - Description]
```

---

## Known Limitations & Workarounds

1. **Search tool requires FTS5**: SQLite must be compiled with FTS5 support
   - Workaround: Use modern SQLite (3.9.0+)

2. **since_ts parsing**: Only ISO8601 format supported
   - Workaround: Always use ISO8601 timestamps from datetime.isoformat()

3. **Agent names**: Alphanumeric only, globally unique
   - Workaround: Use descriptive names with project prefixes if needed

4. **Storage location**: Once set, difficult to migrate
   - Workaround: Choose storage location carefully at project creation

---

## Appendix A: Test Data Generation

Helper script for generating test data:

```python
import asyncio
from datetime import datetime, timezone

async def generate_test_messages(project_key: str, agent_name: str, count: int):
    """Generate test messages with various content."""
    topics = [
        "authentication", "database", "frontend", "backend",
        "performance", "security", "testing", "deployment"
    ]
    actions = ["bug", "feature", "optimization", "refactor"]

    for i in range(count):
        subject = f"{topics[i % len(topics)]} {actions[i % len(actions)]} #{i}"
        body = f"Test message {i} about {topics[i % len(topics)]} {actions[i % len(actions)]}"

        await send_message(
            project_key=project_key,
            sender_name=agent_name,
            to=["global"],
            subject=subject,
            body_md=body
        )

        # Small delay to ensure different timestamps
        await asyncio.sleep(0.1)

# Usage:
# await generate_test_messages("test_project_alpha", "TestBot", 100)
```

---

## Appendix B: Performance Benchmarks

Record baseline performance metrics:

| Operation | Count | Time (ms) | Notes |
|-----------|-------|-----------|-------|
| search_mailbox | 100 msgs | TBD | Basic keyword search |
| search_mailbox | 1000 msgs | TBD | Basic keyword search |
| fetch_inbox | 100 msgs | TBD | With limit=50 |
| send_message | 1 msg | TBD | Simple message |
| register_agent | 1 agent | TBD | New agent |

---

## Appendix C: Environment Info

Record environment details when testing:

```bash
# Python version
python3 --version

# Package versions
uv pip list | grep -E "(fastmcp|sqlalchemy|aiosqlite)"

# SQLite version and FTS5 support
python3 -c "import sqlite3; print(sqlite3.sqlite_version); print('FTS5:', 'fts5' in sqlite3.connect(':memory:').execute('pragma compile_options').fetchall())"

# System info
uname -a
```

---

## Sign-off

**Test Plan Created By**: Claude Code Agent
**Review Required By**: [Human reviewer name]
**Approval Date**: [Date]
**Release Approval**: ☐ Approved ☐ Conditional ☐ Rejected

**Notes**:
[Any additional context or requirements]
