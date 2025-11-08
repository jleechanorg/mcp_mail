# Test Failures Snapshot – 2025‑11‑06

## Context

- Trigger: full `uv run pytest` after adding the CI `test` job.
- Result: suite times out after ~215 s with dozens of failures across many modules.
- Additional verification: `tests/test_contact_policy.py::test_contact_blocked_and_contacts_only` also fails on `origin/main`, so at least part of the backlog predates this branch.

## Summary of Failing Suites (fork branch)

| Suite / File | Notes from latest run |
|--------------|----------------------|
| `tests/test_claim_overlap_and_macro_failures.py` | 2 failures early in the run (details not yet triaged). |
| `tests/test_contact_and_routing.py` | First test fails because `set_contact_policy` is not available when `MCP_TOOLS_MODE=core`. Same behavior on `origin/main`. |
| `tests/test_contact_policy.py` | Six consecutive failures for the same reason as above (unknown `set_contact_policy`). |
| `tests/test_contacts.py` | Four failures, also blocked by `set_contact_policy`. |
| `tests/test_global_agent_uniqueness_modes.py` | First test fails (investigation pending). |
| `tests/test_guard_tools.py` | Single failure (likely regression in guard CLI). |
| `tests/test_lazy_loading.py` | Five failures—lazy-loading meta-tool behavior diverges from expectations when only core tools are exposed. |
| `tests/test_macro_start_session_with_claims.py` | Two failures (macro utilities). |
| `tests/test_macros.py` | Four failures (macro helpers). |
| `tests/test_messaging_semantics.py` | Two failures (semantics around ack/contact gating). |
| `tests/test_outbox_and_claims.py` | One failure (claims workflow). |
| `tests/test_reply_and_threads.py` | Two failures (one due to `set_contact_policy`, the other tied to reclaimed-handle routing). |
| `tests/test_resources_mailbox.py` | One failure (resource contract needs review). |
| `tests/test_server.py` | Multiple failures sprinkled across HTTP entrypoints. |
| `tests/test_share_export.py` | Several failures + skips (share workflow + viewer export). |
| `tests/test_summarize_threads_*` | All three summarization suites fail (LLM off/on). |
| Many other suites | Pass or skip; see pytest log for full coverage. |

## Known Root Causes / Patterns

1. **Extended tool access in tests**  
   - Default config exposes only the 10 core tools. Tests that call `set_contact_policy`, `list_contacts`, etc. expect those extended tools to be callable directly and currently fail with `ToolError: Unknown tool: set_contact_policy`.  
   - Reproduced on `origin/main` (`uv run pytest tests/test_contact_policy.py::test_contact_blocked_and_contacts_only`).
   - Mitigation ideas: either set `MCP_TOOLS_MODE=extended` in `tests/conftest.py` or update tests to invoke `call_extended_tool`.

2. **Share/export schemas**  
   - Integration and unit share tests need `messages.sender_id`/`thread_id`. Several fixtures still create legacy schemas without these columns, causing `sqlite3.OperationalError: no such column: m.thread_id` during export.
   - Some viewer assertions still look for “Static Viewer” text even though the new UI title is “Agent Mail Viewer”.

3. **Large backlog beyond current scope**  
   - Macros, guard tools, messaging semantics, summarization, and claims suites show real regressions unrelated to the naming work. Triage requires stepping through each failure with focused pytest invocations.

## Next Steps

1. Decide on a test strategy for extended tools (env var vs. meta-tool usage).
2. Modernize remaining sqlite fixtures to include the current schema (sender/thread columns).
3. Prioritize failing suites (e.g., macros/contact) and assign owners; each will need targeted fixes.
4. Once the backlog shrinks, re‑enable the CI job to run the full `pytest` command.

## Baseline Verification on `origin/main`

- `uv run pytest tests/test_contact_policy.py::test_contact_blocked_and_contacts_only` fails with the same “Unknown tool: set_contact_policy” error.
- Indicates at least part of the failure backlog exists upstream and is not unique to this branch.

## Upstream Repository Check (Dicklesworthstone/mcp_agent_mail)

Command: `uv run pytest` in a fresh clone of <https://github.com/Dicklesworthstone/mcp_agent_mail.git> (commit 8bde565 as of 2025‑11‑06).

- Suite still fails (timeout after ~200 s) even before applying any of our changes.
- Representative failures:
  1. `tests/integration/test_mailbox_share_integration.py::test_share_export_end_to_end` → `sqlite3.OperationalError: no such column: m.thread_id` while building the export snapshot (seed schema missing `sender_id`/`thread_id`).
  2. `tests/test_http_logging_and_errors.py::test_rbac_denies_when_tool_name_missing` → expects HTTP 401 but server returns 403 when RBAC is enabled without auth.
  3. `tests/test_messaging_semantics.py::test_acknowledge_idempotent_multiple_calls` → second `acknowledge_message` returns a different timestamp; test expects idempotent `acknowledged_at`.
  4. `tests/test_outbox_and_claims.py::test_renew_file_reservations_extends_expiry_and_updates_artifact` → renewed reservation timestamp is earlier than the original (timezone math bug).
  5. `tests/test_share_export.py::test_scrub_snapshot_pseudonymizes_and_clears` → summary reports `agents_pseudonymized == 0` though test expects 1 (pseudonymization no-op).
- Conclusion: these failures are present in the upstream repository itself; fixing them will require upstream code changes, not just adjustments in our fork.

### Severity snapshot

| Area | Failure | Why it matters |
|------|---------|----------------|
| Share export CLI | `test_share_export_end_to_end` – schema mismatch (`thread_id` column missing) kills the export pipeline | Users literally can’t generate a bundle; flagship feature broken. |
| HTTP RBAC | `test_rbac_denies_when_tool_name_missing` – returns 403 instead of 401 | Misleading status for unauthenticated clients; may break agents relying on 401 semantics. |
| Messaging ACKs | `test_acknowledge_idempotent_multiple_calls` – ACK timestamp changes on repeat calls | Idempotence guarantee broken; retryable ACKs now double-book work. |
| Reservation renewals | `test_renew_file_reservations_extends_expiry_and_updates_artifact` – renewed expiry earlier than original | Renewing a lease effectively shortens it, undermining reservations. |
| Scrubber | `test_scrub_snapshot_pseudonymizes_and_clears` – agent names not pseudonymized | Shared bundles leak real agent names (privacy/security regression). |
