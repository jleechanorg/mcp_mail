# Contributing to MCP Agent Mail

Thank you for contributing to MCP Agent Mail! This guide will help you set up your development environment and ensure your contributions pass all CI checks.

## Development Setup

### 1. Install Dependencies

We use `uv` for dependency management:

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync --dev
```

### 2. Install Pre-commit Hooks

**This is critical!** Pre-commit hooks catch linting and type errors before you commit, preventing CI failures:

```bash
# Install pre-commit
pip install pre-commit

# Install the git hooks
pre-commit install
```

Now, every time you commit, the following checks will run automatically:
- **Ruff** - Linting and code formatting
- **Ty** - Type checking

### 3. Running Checks Manually

Before submitting a PR, run all checks locally:

```bash
# Run ruff lint check
ruff check

# Run ruff format check
ruff format --check

# Run ty type check
uvx ty check

# Run tests (smoke tests)
pytest -v tests/test_reply_and_threads.py tests/test_identity_resources.py

# Run all tests
pytest
```

Or use pre-commit to run all hooks:

```bash
# Run all pre-commit hooks
pre-commit run --all-files
```

## Why Pre-commit Hooks Matter

Without pre-commit hooks, you might commit code that fails CI checks. This creates extra noise in the PR:
- ❌ CI fails
- 🔄 You fix the issue
- 🔄 Push again
- ⏰ Wait for CI again

With pre-commit hooks:
- ✅ Issues caught immediately
- ✅ Fix before committing
- ✅ CI passes on first try
- ✅ Faster development cycle

## Common Issues

### Ty Configuration Errors

If you modify `pyproject.toml` and add ty configuration, make sure to use the correct format:

```toml
[tool.ty]
overrides = [
    { path = "scripts/**/*.py", rules = { "unresolved-reference" = "off" } }
]
```

**Not:**
```toml
[tool.ty]
exclude = ["scripts/"]  # ❌ Wrong - this field doesn't exist
```

### Ruff Errors

If ruff complains about imports or formatting:
```bash
# Auto-fix most issues
ruff check --fix

# Format code
ruff format
```

## Testing

### Run Specific Tests
```bash
pytest tests/test_specific_file.py
```

### Run Tests with Coverage
```bash
pytest --cov=mcp_agent_mail --cov-report=term-missing
```

### Run Only Fast Tests
```bash
pytest -v -m "not slow"
```

## PR Guidelines

1. **Run pre-commit checks** - Ensure all hooks pass
2. **Write tests** - Add tests for new features
3. **Update documentation** - Keep README and docstrings current
4. **Keep commits clean** - Each commit should be a logical unit
5. **Follow conventions** - Match existing code style

## Need Help?

- Check the [README](README.md) for project overview
- Check the [CLAUDE.md](CLAUDE.md) for Claude Code agent guidelines
- Open an issue if you're stuck

Thank you for contributing! 🎉
