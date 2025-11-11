# Presubmit Hooks Setup

This directory contains presubmit hooks to catch issues locally before they reach CI.

## Quick Setup

### Option 1: Using pre-commit framework (Recommended)

Install the hooks using `uvx` (no global installation needed):

```bash
uvx pre-commit install --hook-type pre-commit --hook-type pre-push
```

Run manually to check all files:

```bash
uvx pre-commit run --all-files
```

**Note**: `uvx` automatically downloads and runs `pre-commit` without requiring installation. If you prefer to install it globally:

```bash
pip install pre-commit
# or
uv pip install pre-commit
```

### Option 2: Manual git hooks (Alternative)

If you prefer not to use the pre-commit framework:

```bash
./scripts/install-git-hooks.sh
```

This creates symlinks to the hook scripts in `.git/hooks/`.

## What Gets Checked

### Pre-commit (runs before `git commit`)

✅ **Ruff linting** - Fast Python linter with auto-fix (blocking)
⚠️ **Ty type checking** - Static type analysis (non-blocking warning)
✅ **Fast unit tests** - Quick smoke tests (~2 seconds)
✅ **Trailing whitespace** - Automatic cleanup
✅ **YAML/JSON syntax** - Configuration file validation

### Pre-push (runs before `git push`)

✅ **Ty type checking** - Static type analysis (blocking - must match CI)
✅ **Integration tests** - Full `.mcp_mail/` messaging system tests
✅ **Smoke tests** - Core functionality validation

## Skipping Hooks

Sometimes you need to skip hooks (e.g., WIP commits):

```bash
git commit --no-verify
git push --no-verify
```

**⚠️ Warning**: CI will still run all checks, so skipping hooks locally may cause CI failures.

## Hook Performance

- **Pre-commit**: ~5-10 seconds (fast enough for every commit)
- **Pre-push**: ~10-20 seconds (runs full test suite)

If hooks are too slow, you can:
1. Run `git commit --no-verify` for WIP commits
2. Manually run specific checks: `uv run ruff check --fix`
3. Configure hooks to run only on changed files

## Troubleshooting

### Hooks not running

```bash
# Check if hooks are installed
ls -la .git/hooks/

# Reinstall
./scripts/install-git-hooks.sh
# or
pre-commit install --install-hooks
```

### Type checking fails

```bash
# Run ty manually to see full output
uvx ty check
```

### Tests fail

```bash
# Run tests manually with verbose output
uv run pytest tests/integration/ -v
```

### Update hooks

```bash
# For pre-commit framework
pre-commit autoupdate

# For manual hooks, they're symlinked so changes apply immediately
```

## CI Alignment

These hooks run the **same checks as CI**:
- `.github/workflows/ci.yml` - Ruff, Ty, smoke tests
- `.github/workflows/integration.yml` - Integration tests

This ensures local validation matches CI, catching issues before push.

## Why Python 3.13?

All hooks use Python 3.13 to match CI configuration (see CLAUDE.md).
Python 3.14 RC causes Pydantic/Starlette compatibility issues.

## Type Checking Strategy

- **Pre-commit**: Ty runs as non-blocking warning (local Python version may differ)
- **Pre-push**: Ty runs as blocking check (must pass to match CI requirements)

This two-tier approach provides early feedback without blocking commits for Python version differences, while ensuring pushes match CI validation.

## Benefits

✅ **Faster feedback** - Catch issues in seconds vs minutes waiting for CI
✅ **Fewer CI failures** - Issues caught locally don't waste CI resources
✅ **Better commits** - Ensures code quality before it enters version control
✅ **Team consistency** - Everyone runs the same checks locally
