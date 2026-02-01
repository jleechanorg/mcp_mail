# Gemini Agent Protocol

## Mandatory Context
You must locate and internalize the following project documentation before taking action:

1. **`CLAUDE.md`** (in project root):
    * Contains the **authoritative** coding standards, testing commands, and architectural patterns.
    * **INSTRUCTION:** Read this file immediately. Strict adherence to its testing policies (e.g., `TESTING=true`) and code style is mandatory.

2. **`AGENTS.md`** (if present):
    * Describes the agent ecosystem and roles.
    * **INSTRUCTION:** Check for this file to understand broader system context.

## Critical Protocol: Push & Deploy Verification
**NEVER** report a `git push` or deployment as "Complete" or "Success" based on a `RUNNING` status.

1. **Wait for Termination:** You MUST wait for the command to fully terminate.
2. **Verify Exit Code:** You MUST verify the `Exit code` is `0`.
3. **Verify Output:** You MUST see the confirmation output (e.g., `To https://github.com...`, `Resolving deltas`, or `Deployed to...`).
4. **Report Failures:** If hooks fail (even pre-push or pre-commit hooks), report the failure details immediately. Do NOT assume success.

## Operational Rules

### 1. Test Isolation
*   **Respect Flags:** Never ignore testing flags like `TESTING=true`.
*   **Mock Mode:** Ensure tests run in mock mode to avoid hitting production services unless explicitly running an end-to-end integration suite against a test environment.

### 2. Verify Before Action
*   **State check:** Use `grep`, `ls`, or `view_file` to confirm code state before editing. Do not rely on assumptions or memory of previous turns.

### 3. Logic Preservation
*   **Conflict Resolution:** When resolving conflicts, analyze the *intent* of both sides. Do not blindly discard validation logic (e.g., `try/except` blocks, parameter parsing) or architectural changes.

### 4. Efficient Testing
*   **Targeted Execution:** Do not run all tests via `run_tests.sh` indiscriminately, as it may take too long.
*   **Preferred Command:** Run only relevant tests using `uv run pytest <path/to/test>`.

### 5. Code Style & Linting
*   **Linting:** Run `./scripts/run_lint.sh src` before committing.
*   **Formatting:** Use `uv run ruff format src` and `uv run isort src` to fix formatting issues automatically.

## Project Context Summary
*   **Core Function:** MCP Server for Agent Mailbox (async messaging between agents).
*   **Key Components:**
    *   `src/mcp_agent_mail/app.py`: Main FastMCP application and resource handlers.
    *   `src/mcp_agent_mail/storage.py`: SQLite backend (migrated from JSON).
    *   `tests/`: Comprehensive test suite (Unit, Integration, Manual).
*   **Key Patterns:**
    *   **Resource URIs:** FastMCP may strip query parameters. Use `_extract_raw_uri_params(ctx)` helper in `app.py`.
    *   **Future Annotations:** Avoid `from __future__ import annotations` in `app.py` to prevent Pydantic/FastAPI conflicts in certain environments; use string forward references instead.

## Workflow Alignment
*   **Beads Integration:** Use `bd` for task tracking (check `CLAUDE.md` for details).
*   **Git Hygiene:** Keep PRs clean, atomic, and well-described.
