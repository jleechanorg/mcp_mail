# Claude Code Agent Notes

Claude Code (or Claude Desktop) must assume the MCP Agent Mail server is already running in the background before it connects. Always start/refresh the server with a background `bash -lc` call so you capture the PID and tee logs to a safe location.

## Running from PyPI Package (Recommended)

Use the published PyPI package for production use:

```bash
bash -lc "cd /Users/jleechan/mcp_agent_mail && ./scripts/run_server_pypi.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"
```

This installs `mcp_mail` from PyPI in an isolated environment and runs the server.

## Running from Local Source (Development)

For development with local code changes:

```bash
bash -lc "cd /Users/jleechan/mcp_agent_mail && ./scripts/run_server_with_token.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"
```

## Running from Local Build (Testing)

For testing locally built packages before publishing to PyPI:

```bash
bash -lc "cd /Users/jleechan/mcp_agent_mail && ./scripts/run_server_local_build.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"
```

This script:
- Uses the wheel file from `dist/` (built with `uv build`)
- Installs in an isolated temporary virtual environment
- Uses Python 3.11-3.13 (avoiding Python 3.14 RC due to Pydantic compatibility issues)
- Runs the server from the locally built package

## General Notes

- Keep the printed PID handy; stop the service with `kill <PID>` when you are done.
- Tail `/tmp/mcp_agent_mail_server.log` if Claude reports connection errors.
- Launch Claude Code/Claude Desktop **after** the command above succeeds so it can reuse the existing HTTP MCP endpoint at `http://127.0.0.1:8765/mcp/`.

With the server running, Claude agents can call `ensure_project`, `register_agent`, `fetch_inbox`, and the other MCP tools without additional setup.

## GitHub Authentication

A GitHub token is available for use by agents via the `GITHUB_TOKEN` environment variable:

- **GitHub CLI (`gh`)**: The token is automatically available as `GITHUB_TOKEN` environment variable for all `gh` CLI operations
- **GitHub Actions/Workflows**: The `GITHUB_TOKEN` environment variable is available in all workflows
- **API calls**: Use the `GITHUB_TOKEN` environment variable for direct GitHub API calls
- **General use**: Use this token for any GitHub-related operations (creating PRs, managing issues, fetching repository data, etc.)

Example usage:
```bash
# GitHub CLI automatically uses GITHUB_TOKEN environment variable
gh pr create --title "My PR" --body "Description"

# For direct API calls
curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/repos/owner/repo
```

Example GitHub Actions workflow:
```yaml
- name: Create PR
  run: gh pr create --title "My PR" --body "Description"
  # GITHUB_TOKEN is automatically available as an environment variable
```

**Note**: The token is already configured and ready to use. No additional setup is required.

### Installing gh CLI if not available

If the `gh` CLI is not installed on the system, download and use the precompiled binary directly from GitHub releases:

```bash
# Download and extract the precompiled binary
curl -sL https://github.com/cli/cli/releases/download/v2.40.1/gh_2.40.1_linux_amd64.tar.gz | tar -xz -C /tmp

# Use the binary directly from the extracted location
/tmp/gh_2.40.1_linux_amd64/bin/gh --version

# Authenticate using the existing GitHub token
/tmp/gh_2.40.1_linux_amd64/bin/gh auth status
```

The binary can be used directly without installation by referencing the full path `/tmp/gh_2.40.1_linux_amd64/bin/gh`. The `GITHUB_TOKEN` environment variable will be automatically recognized for authentication.

## Credentials Management

All sensitive credentials (API tokens, passwords, etc.) should be stored in `~/.bashrc` as environment variables and sourced automatically by bash sessions. This ensures credentials are:
- **Centralized**: Single source of truth in `~/.bashrc`
- **Secure**: Not hardcoded in scripts or config files
- **Available**: Automatically loaded in all bash sessions via `bash -lc`

### PyPI Publishing

The PyPI token is stored in `~/.bashrc` as `PYPI_TOKEN`:

```bash
# In ~/.bashrc
export PYPI_TOKEN="pypi-..."
```

You must also configure `~/.pypirc` with this token before publishing (the heredoc expands `PYPI_TOKEN` so the file stores the actual token value):

```bash
cat > ~/.pypirc <<EOF
[distutils]
index-servers =
    pypi

[pypi]
username = __token__
password = ${PYPI_TOKEN}
EOF
chmod 600 ~/.pypirc
```

> ⚠️ `~/.pypirc` stores plaintext credentials. Restrict permissions with `chmod 600` and never commit or share this file. Keep `PYPI_TOKEN` in `~/.bashrc` so shells and scripts can regenerate `.pypirc` when needed.

To publish packages:

```bash
# Source bashrc to get credentials (or start new bash session)
source ~/.bashrc

# Publish to PyPI using twine
twine upload dist/mcp_mail-*.whl dist/mcp_mail-*.tar.gz
```

### Adding New Credentials

When adding new API tokens or credentials:

1. **Add to ~/.bashrc**:
   ```bash
   export SERVICE_API_TOKEN="your-token-here"
   ```

2. **Source bashrc**:
   ```bash
   source ~/.bashrc
   ```

3. **Use in scripts via bash -lc**:
   ```bash
   bash -lc 'echo $SERVICE_API_TOKEN'  # Credentials available
   ```

4. **Document in CLAUDE.md**: Add a section explaining the credential and its usage

### Available Credentials

Current credentials configured in `~/.bashrc`:
- `GITHUB_TOKEN` - GitHub API access (see GitHub Authentication section above)
- `PYPI_TOKEN` - PyPI package publishing

### Best Practices

- **Never commit credentials** to Git repositories
- **Use environment variables** instead of hardcoded tokens
- **Source bashrc** in scripts using `bash -lc` to access credentials
- **Document all credentials** in this section when adding new ones
- **Rotate tokens** at least quarterly (and immediately after any suspected exposure)

## PR Responsibility Model

When working on pull requests, understand that **PRs own all regressions versus `origin/main`**, regardless of which commit in the PR introduced them.

### Key Principle

If a bug exists in the PR branch but NOT in `origin/main`, the PR is responsible for fixing it before merge—even if:
- The bug was introduced in an earlier commit by a different contributor
- Your recent work didn't touch the affected code
- The bug came from a feature added days ago in the same PR

### Example Scenario

**PR #13 Timeline:**
1. Day 1: Contributor A adds retirement feature (commits 67b6974, a4844b7)
   - Introduces 5 bugs in the retirement logic
2. Day 3: Contributor B adds cross-project messaging (commits d44c7ae, d6a6754)
   - Doesn't touch retirement code
   - Introduces 1 new bug (unused import)

**Who fixes what?**
- Contributor B must fix ALL 6 bugs (5 pre-existing + 1 new)
- Why? The PR as a whole must be green vs `origin/main`
- The automation bots don't care which commit introduced the bugs

### Best Practices

1. **Check the entire PR branch**, not just your commits
2. **Run full test suite** before adding commits to an existing PR
3. **Document pre-existing bugs** in `roadmap/` but also fix them
4. **Communicate with earlier contributors** but don't block on them
5. **Own the merge** - if you're the last contributor, you own getting it green

### Reference

See PR #13 for a real example where this model was applied:
- Commits 336c20f, 879a81c, 80e9df5 fixed both new and pre-existing bugs
- All regressions vs `origin/main` were resolved before merge
- Documentation in `roadmap/pr13_preexisting_bugs.md` explained the triage

This ensures every merged PR maintains a clean history and working state.

## Beads hygiene (agents are responsible)

- Always keep Beads in lockstep with reality. If you uncover a new bug, regression, or TODO that isn't already tracked, **open a Beads issue immediately** (`bd create ...`) before starting the fix.
- Update Beads issue state as you work (`bd update`, `bd close`) so other agents see an accurate queue.
- Mirror the Beads id in every Mail thread (`thread_id`, subject prefix) to keep the audit trail consistent.
- Don't wait for humans to ask—treat Beads upkeep as part of the job every time you touch code.

## Test Execution Policy

When asked to "run all tests", "run tests in testing_llm/", or execute a test suite:

### Mandatory Rules

1. **Execute EVERY test** listed in the specified directory or test suite
2. **NEVER skip tests** due to cost, time, or complexity concerns without explicit permission
3. **Ask first, don't assume** - If a test requires resources (API credits, external services), ASK the user before skipping but DO NOT skip unilaterally
4. **Document all skipped tests** - If a test is skipped, it MUST be with explicit user permission and documented in the evidence

### Testing_LLM Directory

All tests in `testing_llm/` are designed to validate MCP Agent Mail functionality:
- **MESSAGE_DELIVERY_VALIDATION** - SQLite-based message delivery proof
- **MULTI_AGENT_MESSAGING_TEST** - Multi-agent coordination with Python
- **REAL_CLAUDE_MULTI_AGENT_TEST** - Real Claude CLI instances coordinating

**These tests exist for a reason.** Run them all unless explicitly instructed otherwise.

### Test Evidence

All tests must generate complete evidence in `/tmp/` with:
- Test execution logs
- Agent profiles and registrations
- Message exchanges and routing proof
- Validation results (pass/fail with details)
- Summary documents

### What Went Wrong (Lesson Learned)

**Issue:** On 2025-11-18, Test 3 (REAL_CLAUDE_MULTI_AGENT_TEST) was initially skipped due to assumed cost concerns without asking the user.

**User Feedback:** "wtf it should work" and "how do we make you follow instructions next time?"

**Resolution:**
- Test 3 was executed after user insistence
- This policy was added to prevent future unilateral skipping
- All future test execution requests will run ALL tests unless explicitly instructed to skip

### Correct Behavior

```markdown
User: "run all tests in testing_llm/"

Agent Response:
1. List all tests found in testing_llm/
2. If any test requires significant resources: "Test X requires API credits/external services. Proceed with all tests?"
3. Upon user confirmation (or if no concerns): Execute ALL tests sequentially
4. Generate complete evidence for each test
5. Provide comprehensive summary of all test results
```

**NEVER:**
- Skip tests without asking
- Assume cost/time concerns override explicit instructions
- Execute partial test suites when "all" was requested
