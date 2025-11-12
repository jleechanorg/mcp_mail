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

## Slash Commands

Custom slash commands are available in the git submodule at `claude-commands/.claude/commands/`. Claude Code agents should look for slash command definitions in this directory in addition to the standard `.claude/commands/` location.

To use these commands:
- Commands are defined as markdown files in `claude-commands/.claude/commands/`
- Invoke commands with the `/` prefix (e.g., `/command-name`)
- The git submodule contains shared commands that can be used across multiple projects
- Ensure the submodule is initialized: `git submodule update --init --recursive`

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

- Always keep Beads in lockstep with reality. If you uncover a new bug, regression, or TODO that isn’t already tracked, **open a Beads issue immediately** (`bd create ...`) before starting the fix.
- Update Beads issue state as you work (`bd update`, `bd close`) so other agents see an accurate queue.
- Mirror the Beads id in every Mail thread (`thread_id`, subject prefix) to keep the audit trail consistent.
- Don’t wait for humans to ask—treat Beads upkeep as part of the job every time you touch code.
