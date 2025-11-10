# Code Quality Tools Quick Reference

This document provides a quick reference for all the code quality tools used in this project.

## Tools Overview

| Tool | Purpose | When it Runs | Blocks Commit? |
|------|---------|--------------|----------------|
| **Ruff** | Linting & formatting | Pre-commit, CI | Yes |
| **Ty** | Type checking | Pre-commit, CI | No |
| **Bandit** | Security scanning | Pre-commit, CI | No |
| **Safety** | Dependency vulnerabilities | Pre-commit, CI | No |
| **Pytest** | Unit tests | CI | Yes (in CI) |

## Quick Commands

```bash
# Install git hooks (run once after cloning)
./scripts/setup_git_hooks.sh

# Run all checks manually
uvx ruff check --fix --unsafe-fixes  # Lint and auto-fix
uvx ty check                         # Type check
uv run bandit -r src/ -ll            # Security scan
uv run safety check                  # Dependency check
uv run pytest                        # Run tests

# Skip pre-commit hook (not recommended)
git commit --no-verify
```

## Understanding Check Results

### Ruff (Linting)
- **Blocks commits**: Yes, if unfixable errors exist
- **Auto-fixes**: Applied automatically and staged
- **Common issues**: Import ordering, unused variables, code style

### Ty (Type Checking)
- **Blocks commits**: No
- **Warnings**: Informational only
- **Common issues**: Missing type hints, type mismatches

### Bandit (Security)
- **Blocks commits**: No
- **Severity levels**: Low, Medium, High
- **Common issues**:
  - Hardcoded credentials
  - SQL injection vectors
  - Weak cryptographic hashes
  - Unsafe function usage

### Safety (Dependencies)
- **Blocks commits**: No
- **Reports**: Known CVEs in dependencies
- **Action**: Update vulnerable packages when possible

## Common Security Issues Found

Based on the current codebase scan, here are the most common security findings:

### 1. SQL Injection (B608)
**Issue**: Dynamic SQL query construction with string formatting
**Severity**: Medium
**Example**: `f"SELECT * FROM table WHERE id IN ({placeholders})"`
**Fix**: Use parameterized queries with SQLAlchemy's `bindparam()`

### 2. Weak Hashing (B324)
**Issue**: Use of SHA1 for hashing
**Severity**: High
**Example**: `hashlib.sha1(data).hexdigest()`
**Fix**: Use SHA256 or add `usedforsecurity=False` if not for security

### 3. Bind to All Interfaces (B104)
**Issue**: Binding to `0.0.0.0` can expose service to network
**Severity**: Medium
**Example**: `host = "0.0.0.0"`
**Fix**: Document intentional usage or use localhost for development

## CI/CD Pipeline

All checks run automatically on every push to any branch:

```yaml
Jobs:
  ✓ Ruff Lint          # Must pass
  ✓ Ty Type Check      # Informational
  ✓ Bandit Security    # Informational
  ✓ Safety Check       # Informational
  ✓ Run Tests          # Must pass
```

## Best Practices

1. **Always run `./scripts/setup_git_hooks.sh` after cloning**
2. **Review security warnings** - Even if they don't block commits
3. **Keep dependencies updated** - Run `uv lock --upgrade` regularly
4. **Fix high-severity security issues** - Especially before production
5. **Don't skip hooks without reason** - Use `--no-verify` sparingly

## Configuring Tools

### Ruff Configuration
Edit `pyproject.toml` section `[tool.ruff]` to adjust:
- Line length
- Enabled rules
- Ignored patterns

### Bandit Configuration
To suppress specific warnings, add `# nosec` comment:
```python
password = os.getenv("PASSWORD")  # nosec B105
```

### Safety Configuration
Create `.safety-policy.yml` to ignore specific CVEs:
```yaml
security:
  ignore-cves:
    - CVE-2023-12345  # Reason: False positive
```

## Getting Help

- **Ruff docs**: https://docs.astral.sh/ruff/
- **Ty docs**: https://docs.astral.sh/ty/
- **Bandit docs**: https://bandit.readthedocs.io/
- **Safety docs**: https://docs.pyup.io/docs/getting-started-with-safety-cli

For project-specific questions, see `CONTRIBUTING.md` or open an issue.
