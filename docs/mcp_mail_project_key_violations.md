# MCP Mail Project Key Violations Audit

**Audit Date:** December 28, 2025  
**Auditor:** Automated Analysis  
**Scope:** All MCP tools that accept `project_key` parameter

## Executive Summary

This audit identified **5 CRITICAL violations** where MCP tools claim `project_key` is "informational only" but actually require a valid project by calling `_get_project_by_identifier()`, which raises `NoResultFound` when the project doesn't exist.

This violates the documented global agent namespace design where agents are globally unique and should be accessible without project context.

## Root Cause

Tools were calling `_get_project_by_identifier(project_key)` BEFORE looking up agents, causing failures when `project_key` didn't exist—even though agents are globally unique and don't require project context.

## Critical Violations (Priority 1 - User-Facing)

### 1. fetch_inbox (MCP-iu3) - CRITICAL
**Location:** `src/mcp_agent_mail/app.py:4655`  
**Documentation:** "project_key is informational only and does not affect message retrieval"  
**Actual Behavior:** Calls `_get_project_by_identifier(project_key)` which fails if project doesn't exist  
**User Impact:** User report: "I keep getting constant errors requiring a project key"  
**Fix:** Look up agent first using `_get_agent_by_name(agent_name)`, then use `agent.project_id`

### 2. send_message (MCP-uxk) - CRITICAL  
**Location:** `src/mcp_agent_mail/app.py:4036`  
**Documentation:** "project_key is informational only for agent lookup; agents are global"  
**Actual Behavior:** Calls `_get_project_by_identifier(project_key)` which can fail  
**User Impact:** Cannot send messages without valid project_key  
**Fix:** Look up sender first using `_get_agent_by_name(sender_name)`, then use `agent.project_id`

### 3. whois (MCP-c25) - CRITICAL  
**Location:** `src/mcp_agent_mail/app.py:3762`  
**Documentation:** "Agent names are GLOBALLY UNIQUE across all projects"  
**Actual Behavior:** Requires valid project_key by calling `_get_project_by_identifier(project_key)`  
**User Impact:** Cannot look up agents without valid project_key  
**Fix:** Look up agent globally using `_get_agent_by_name(agent_name)` without project_key validation

## High Priority Violations

### 4. delete_agent (MCP-915) - HIGH  
**Location:** `src/mcp_agent_mail/app.py:3705`  
**Documentation:** Global agent namespace  
**Actual Behavior:** Requires valid project_key  
**User Impact:** Cannot delete agents without valid project_key  
**Additional Bug:** Fails when agent has `project_id = None` because `_delete_agent()` queries `Agent.project_id == project.id`  
**Fix:** Look up agent globally, delete directly without project scoping

## Medium Priority Violations

### 5. reply_message (MCP-2pj) - MEDIUM  
**Location:** `src/mcp_agent_mail/app.py:4452`  
**Documentation:** Part of global agent messaging system  
**Actual Behavior:** Requires valid project_key by calling `_get_project_by_identifier(project_key)`  
**User Impact:** Cannot reply to messages without valid project_key  
**Fix:** Look up sender agent first, then use `agent.project_id` for routing

## Correct Pattern (Reference Implementation)

The following tools correctly implement "informational only" by skipping `_get_project_by_identifier()` calls:

- `mark_message_read`
- `acknowledge_message`

**Correct pattern:**
```python
# Look up agent first (global)
agent = await _get_agent_by_name(agent_name)
if agent is None:
    return error_response

# Get project from agent
project = await _get_project_for_agent(agent)
if project is None:
    project = await _get_default_project()

# Use project for operations
```

**Violating pattern (WRONG):**
```python
# Look up project first (FAILS if project doesn't exist)
project = await _get_project_by_identifier(project_key)
# Then look up agent
agent = await _get_agent_by_name(agent_name)
```

## Tools Analyzed (Total: 19)

The following tools call `_get_project_by_identifier()`:

### Critical Violations (5)
1. fetch_inbox
2. send_message
3. whois
4. delete_agent
5. reply_message

### Other Tools (14)
6. register_agent - Valid use (project required for registration)
7. list_agents - Valid use (listing project-specific agents)
8. update_agent_profile - Valid use (updating agent in project)
9. get_agent_profile - Could be improved (agents are global)
10. list_messages - Valid use (project-specific message listing)
11. get_message - Could be improved (messages could be global)
12. archive_messages - Valid use (archiving project messages)
13. create_thread - Valid use (threads in project context)
14. list_threads - Valid use (listing project threads)
15. get_thread_messages - Valid use (thread-specific messages)
16. create_project - Valid use (creating new project)
17. list_projects - No project_key parameter
18. get_project_stats - Valid use (project-specific stats)
19. configure_project - Valid use (project configuration)

## Impact Assessment

**Severity:** CRITICAL - Blocks basic functionality  
**User Reports:** "I keep getting constant errors requiring a project key"  
**CLI Error Example:** "No inbox yet. The fetch failed because that project key isn't registered in MCP Mail."

## Fix Effort Estimate

- **Per Tool:** ~30 minutes
- **Total:** 1-2 days for all 5 violations
- **Testing:** Additional 1 day for integration tests

## Prevention Recommendations

1. **Linting Rule:** Create rule to detect `_get_project_by_identifier()` calls in tools claiming "informational only"
2. **Documentation Standards:** Update tool parameter documentation guidelines
3. **CI Checks:** Add automated checks for "project_key is informational only" contract
4. **Integration Tests:** Add tests for agents without project_key

## Related Issues

- **Parent Issue:** MCP-5pi - Fix fetch_inbox and other tools to work without project_key
- **Child Issues:** MCP-iu3, MCP-uxk, MCP-c25, MCP-915, MCP-2pj

## Appendix: Detailed Analysis

### Analysis Methodology

1. Searched all MCP tools that accept `project_key` parameter
2. Identified tools claiming "informational only" in documentation
3. Verified actual implementation behavior
4. Analyzed dependencies and data flow
5. Documented violations and correct patterns

### Dependencies

- `_get_project_by_identifier()` - Raises `NoResultFound` if project doesn't exist
- `_get_agent_by_name()` - Global agent lookup
- `_get_project_for_agent()` - Get project from agent's `project_id`
- `_get_default_project()` - Fallback to default project
- `_list_inbox()` - Needs `Project` object for `get_global_inbox_name()`

### Test Coverage

Current gaps:
- No integration tests for agents without project_key
- No tests for tools with invalid/non-existent project_key
- No verification of "informational only" contract

Recommended additions:
- Test each fixed tool with non-existent project_key
- Test agent operations across projects
- Test global agent lookup scenarios

## Conclusion

The audit revealed systematic violations of the global agent namespace design. All 5 critical violations follow the same pattern: looking up projects before agents. The fix is straightforward and consistent: look up agents first (global), then use their associated project. This aligns with the documented design and user expectations.

**Status:** OPEN - Fixes in progress  
**Target:** Complete before next release  
**Owner:** Development Team
