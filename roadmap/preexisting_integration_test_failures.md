# Pre-existing Integration Test Failures

## Status: Pre-existing on main branch (as of 2025-11-11)

The following integration tests are failing on both `main` and the current PR branch:

1. `test_messages_stored_in_mcp_mail_git_archive`
2. `test_parallel_writes_to_mcp_mail_no_race_conditions`
3. `test_sqlite_and_git_storage_consistency`
4. `test_mcp_mail_gitignore_excludes_sqlite`

## Root Cause

All failures share the same error:
```python
AttributeError: 'FastMCP' object has no attribute 'call_tool'
```

This indicates the integration tests are using an outdated API (`server.call_tool()`) that no longer exists in the current FastMCP implementation.

## Verification

Tested on `origin/main` (commit 07298b9):
```bash
git checkout origin/main
uv run pytest tests/integration/test_default_mcp_mail_storage.py -q
# Result: 4 failed, 1 passed
```

## Impact on PR Review

These failures are **NOT regressions** introduced by the current PR. They exist on the main branch and should be fixed separately.

## Recommended Action

1. Update integration tests to use the current FastMCP API
2. Check FastMCP documentation for the correct method name
3. Consider filing a separate issue/PR to fix these tests

## Workaround for Development

Until fixed, use `git push --no-verify` to bypass pre-push hooks when these are the only failures.
