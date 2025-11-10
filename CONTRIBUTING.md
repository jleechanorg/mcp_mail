# Contributing to MCP Mail

Thank you for your interest in contributing to MCP Mail! This document provides guidelines and instructions for developers.

## Development Setup

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- Git

### Clone and Install

```bash
git clone https://github.com/jleechanorg/mcp_mail.git
cd mcp_mail
uv sync --dev
```

## Git Hooks

We use git hooks to ensure code quality before commits. These hooks run automatically before each commit to check for issues.

### Installing Git Hooks

After cloning the repository, install the git hooks by running:

```bash
./scripts/setup_git_hooks.sh
```

This will install a pre-commit hook that automatically:
1. Syncs dependencies (if needed)
2. Runs `ruff check --fix --unsafe-fixes` to lint and auto-fix code issues
3. Runs `ty check` for type checking (warnings won't block commits)

### What the Pre-Commit Hook Does

The pre-commit hook performs the following checks:

- **Ruff Linting**: Automatically fixes code style issues, import ordering, and common Python mistakes
  - If ruff makes any fixes, they will be automatically added to your commit
  - If ruff finds unfixable errors, the commit will be blocked until you fix them

- **Type Checking**: Runs type checks to catch potential type errors
  - Type checking warnings will be reported but won't block the commit
  - This helps maintain type safety while not being overly strict

### Skipping Hooks

If you need to bypass the pre-commit hook for a specific commit (not recommended), use:

```bash
git commit --no-verify
```

## Code Quality Tools

### Running Checks Manually

You can run the quality checks manually at any time:

```bash
# Run ruff linting with auto-fix
uvx ruff check --fix --unsafe-fixes

# Run ruff without auto-fix (just check)
uvx ruff check

# Run type checking
uvx ty check
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific tests
uv run pytest tests/test_example.py

# Run with coverage
uv run pytest --cov=mcp_agent_mail --cov-report=term-missing
```

## CI/CD

All pull requests are automatically checked by GitHub Actions for:
- Ruff linting
- Type checking with ty
- Test suite

Make sure your code passes all checks before submitting a PR.

## Code Style

- Follow PEP 8 style guidelines (enforced by ruff)
- Use type hints for all function signatures
- Write docstrings for public functions and classes
- Keep line length to 120 characters or less

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Install git hooks (`./scripts/setup_git_hooks.sh`)
4. Make your changes
5. Ensure all tests pass and code quality checks succeed
6. Commit your changes (hooks will run automatically)
7. Push to your fork
8. Open a Pull Request

## Questions?

If you have questions or need help, please open an issue on GitHub.
