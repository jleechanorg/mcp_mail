# MCP Mail project_key audit (global agent tools)

This document preserves the findings from the audit referenced in MCP-5pi. It summarizes the five
critical violations where `project_key` was documented as informational but enforcement in code
made it mandatory.

## Scope
- Tools reviewed: `fetch_inbox`, `send_message`, `whois`, `delete_agent`, `reply_message`
- Root issue: `_get_project_by_identifier(project_key)` raised `NoResultFound` when `project_key`
  did not exist, even though agent names are globally unique.

## Violations
- `fetch_inbox`: looked up project by `project_key` before agent; failed when project missing.
- `send_message`: required `project_key` before resolving sender globally.
- `whois`: performed project-scoped lookup despite global uniqueness.
- `delete_agent`: required `project_key`, preventing deletion of globally unique agents.
- `reply_message`: required `project_key` for sender lookup and routing.

## Fix pattern
1. Look up agents globally by name.
2. Resolve the project from the agent association.
3. Fail fast if no project is associated to avoid routing or deletion in the wrong project.

## References
- Parent issue: MCP-5pi
- Implemented in PR #151 (`project_key` branch)
