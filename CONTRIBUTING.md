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

## Git Hooks (Pre-commit Framework)

We use the [pre-commit framework](https://pre-commit.com/) to ensure code quality before commits and pushes. This is the Python equivalent of Husky for JavaScript projects.

### Installing Git Hooks

After cloning the repository, install the git hooks using one of these methods:

**Option 1: Using uvx (Recommended - No installation needed)**

```bash
uvx pre-commit install --hook-type pre-commit --hook-type pre-push
```

**Option 2: Using setup script**

```bash
./scripts/setup_git_hooks.sh
```

This script will:
1. Install the `pre-commit` tool (via `uv tool install pre-commit`)
2. Set up pre-commit and pre-push hooks in your `.git/hooks/` directory
3. Configure hooks to run automatically on `git commit` and `git push`

**Option 3: Manual installation**

```bash
uv tool install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
```

### What the Hooks Do

**Pre-commit hooks** (run on `git commit`):
- **Ruff Linting**: Automatically fixes code style issues, import ordering, and common Python mistakes
  - If ruff makes any fixes, they will be automatically added to your commit
  - If ruff finds unfixable errors, the commit will be blocked until you fix them
- **Trailing Whitespace**: Removes trailing whitespace from all files
- **End-of-File Fixer**: Ensures files end with a newline
- **YAML/JSON Syntax**: Validates YAML and JSON files
- **Large File Detection**: Prevents committing files larger than 1MB
- **Merge Conflict Detection**: Checks for unresolved merge conflict markers
- **Type Checking (ty)**: Runs type checks to catch potential type errors (non-blocking)
- **Fast Unit Tests**: Runs quick smoke tests to catch obvious breakage

**Pre-push hooks** (run on `git push`):
- **Integration Tests**: Runs slower integration tests before pushing to remote

### Configuration

Hooks are configured in `.pre-commit-config.yaml`. The configuration includes:
- Hook versions and repositories
- Which checks run at which stages (commit vs push)
- Arguments and options for each check

### Running Hooks Manually

```bash
# Run all pre-commit hooks on all files
uvx pre-commit run --all-files
# or if pre-commit is installed: pre-commit run --all-files

# Run specific hook
uvx pre-commit run ruff --all-files

# Run on staged files only (what would run on commit)
uvx pre-commit run

# Update hook versions in config
pre-commit autoupdate
```

### Skipping Hooks

If you need to bypass hooks for a specific commit (not recommended), use:

```bash
# Skip all hooks
git commit --no-verify

# Skip pre-push hooks
git push --no-verify
```

## Code Quality Tools

### Running Checks Manually

You can run the quality checks manually at any time:

```bash
# Run all pre-commit hooks
pre-commit run --all-files

# Run ruff linting with auto-fix
uvx ruff check --fix --unsafe-fixes

# Run ruff without auto-fix (just check)
uvx ruff check

# Run type checking
uvx ty check

# Optional: Run security scan (not in pre-commit hooks)
uv run bandit -r src/

# Optional: Check dependencies for vulnerabilities (not in pre-commit hooks)
uv run safety check
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

All pushes to any branch are automatically checked by GitHub Actions for:
- **Ruff linting** - Code style and quality (matches pre-commit hooks)
- **Type checking with ty** - Static type analysis
- **Test suite** - Functional correctness
- **Security scanning with Bandit** - Common security vulnerabilities (optional)
- **Dependency vulnerability checks with Safety** - Known CVEs in dependencies (optional)

Make sure your code passes all checks before pushing. The pre-commit hooks will catch most issues locally.

## Code Style

- Follow PEP 8 style guidelines (enforced by ruff)
- Use type hints for all function signatures
- Write docstrings for public functions and classes
- Keep line length to 120 characters or less

## Security Best Practices

When contributing code, keep these security practices in mind:

- **Never commit secrets**: No API keys, passwords, tokens, or credentials in code
- **Avoid hardcoded credentials**: Use environment variables or secure config files
- **Validate inputs**: Sanitize and validate all user inputs to prevent injection attacks
- **Use parameterized queries**: Prevent SQL injection by using parameterized database queries
- **Keep dependencies updated**: Regularly check for and update vulnerable dependencies
- **Review Bandit warnings**: Pay attention to security scan results, even if they don't block commits
- **Use secure random**: Use `secrets` module instead of `random` for security-sensitive operations

The pre-commit hook will flag common security issues, but developer awareness is the best defense.

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
