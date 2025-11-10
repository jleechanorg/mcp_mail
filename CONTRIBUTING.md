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
4. Runs `bandit` to scan for security vulnerabilities (warnings won't block commits)
5. Runs `safety` to check dependencies for known vulnerabilities (warnings won't block commits)

### What the Pre-Commit Hook Does

The pre-commit hook performs the following checks:

- **Ruff Linting**: Automatically fixes code style issues, import ordering, and common Python mistakes
  - If ruff makes any fixes, they will be automatically added to your commit
  - If ruff finds unfixable errors, the commit will be blocked until you fix them

- **Type Checking (ty)**: Runs type checks to catch potential type errors
  - Type checking warnings will be reported but won't block the commit
  - This helps maintain type safety while not being overly strict

- **Security Scanning (Bandit)**: Scans code for common security vulnerabilities
  - Checks for hardcoded credentials, SQL injection risks, unsafe functions, etc.
  - Security issues are reported but won't block the commit
  - Run `uv run bandit -r src/` for detailed security reports

- **Dependency Vulnerability Check (Safety)**: Scans dependencies for known vulnerabilities
  - Checks all installed packages against the Safety vulnerability database
  - Alerts you to known CVEs in your dependencies
  - Vulnerabilities are reported but won't block the commit
  - Run `uv run safety check` for detailed vulnerability reports

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

# Run security scan
uv run bandit -r src/

# Run security scan with verbose output
uv run bandit -r src/ -ll

# Check dependencies for vulnerabilities
uv run safety check

# Get detailed JSON report of vulnerabilities
uv run safety check --json
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
- **Ruff linting** - Code style and quality
- **Type checking with ty** - Static type analysis
- **Security scanning with Bandit** - Common security vulnerabilities
- **Dependency vulnerability checks with Safety** - Known CVEs in dependencies
- **Test suite** - Functional correctness

Make sure your code passes all checks before pushing. Security and dependency checks are informational and won't fail builds, but should be reviewed and addressed when possible.

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
