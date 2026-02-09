# Repository Scaffolding Documentation

## Overview

This repository has been scaffolded with essential development scripts from the [claude-commands](https://github.com/jleechanorg/claude-commands) repository. These scripts provide standardized tooling for development, testing, coverage analysis, and workflow management.

## Scaffolded Scripts

### Root Level Scripts

1. **`create_worktree.sh`** - Git worktree management for parallel branch work
   - Create isolated working directories for different branches
   - Avoid constant branch switching during development

2. **`integrate.sh`** - Branch integration and merge automation
   - Automated merge conflict resolution
   - Integration testing before merging

3. **`schedule_branch_work.sh`** - Branch work scheduling and tracking
   - Manage multiple parallel work streams
   - Track branch dependencies and blockers

### Scripts Directory

#### Code Quality & Testing

1. **`scripts/run_lint.sh`** - Comprehensive linting and code quality
   - **Adapted for mcp_mail:** Uses `uv run` instead of venv
   - **Default target:** `src/mcp_agent_mail` (customizable via first argument)
   - **Tools:**
     - Ruff for linting and formatting
     - Bandit for security scanning
   - **Note:** Type checking uses `ty` - run `uv run ty` separately
   - **Usage:**
     ```bash
     ./scripts/run_lint.sh                    # Check code quality
     ./scripts/run_lint.sh src/mcp_agent_mail fix  # Auto-fix issues
     ```

2. **`scripts/run_tests_with_coverage.sh`** - Test execution with coverage
   - **Adapted for mcp_mail:** Uses `uv run pytest` instead of raw pytest
   - **Default source:** `src/mcp_agent_mail`
   - **Features:**
     - Sequential test execution for accurate coverage
     - HTML and text coverage reports
     - Integration test support
   - **Usage:**
     ```bash
     ./scripts/run_tests_with_coverage.sh                # Unit tests only
     ./scripts/run_tests_with_coverage.sh --integration  # Include integration tests
     ./scripts/run_tests_with_coverage.sh --no-html      # Skip HTML report
     ```

3. **`scripts/coverage.sh`** - Dedicated coverage analysis
   - **Adapted for mcp_mail:** Uses `uv run` for all Python commands
   - **Output location:** `/tmp/mcp_mail/coverage/`
   - **Features:**
     - Comprehensive coverage reports
     - HTML visualization
     - Test execution tracking
   - **Usage:**
     ```bash
     ./scripts/coverage.sh                   # Full coverage with HTML
     ./scripts/coverage.sh --integration     # Include integration tests
     ./scripts/coverage.sh --no-html         # Text report only
     ```

#### Development Utilities

4. **`scripts/loc.sh`** - Lines of code analysis
   - Detailed source code statistics
   - Per-file and per-directory breakdown

5. **`scripts/loc_simple.sh`** - Simple LOC count
   - Quick line count for common file types

6. **`scripts/codebase_loc.sh`** - Comprehensive codebase analysis
   - Multi-language support
   - Detailed statistics and reports

#### Git & Version Control

7. **`scripts/push.sh`** - Safe git push with validation
   - Pre-push validation
   - Branch protection checks

8. **`scripts/sync_branch.sh`** - Branch synchronization
   - Keep feature branches up to date with main
   - Automated merge conflict detection

9. **`scripts/resolve_conflicts.sh`** - Conflict resolution helper
   - Guided conflict resolution
   - Automated merge strategies

#### CI/CD & Integration

10. **`scripts/setup-github-runner.sh`** - GitHub Actions runner setup
    - Self-hosted runner configuration
    - CI/CD integration

11. **`scripts/setup_email.sh`** - Email notification setup
    - Git notification configuration
    - Build status alerts

12. **`scripts/create_snapshot.sh`** - Project snapshot creation
    - Backup critical project state
    - Version archiving

13. **`scripts/claude_start.sh`** - Claude Code integration
    - MCP server startup automation
    - Development environment setup

## Project-Specific Adaptations

The following adaptations were made for the mcp_mail Python project:

### 1. Package Manager: uv

All scripts were updated to use `uv` instead of traditional `venv`:
- `uv run` prefix for all Python commands
- `uv pip install` for dependency installation
- No venv activation needed - uv handles it automatically

### 2. Source Directory

Updated default source directory from generic patterns to:
- Primary: `src/mcp_agent_mail`
- Fallback patterns: `src`, `lib`, `app`, `source`, `code`

### 3. Linting Tools

Configured for mcp_mail's specific toolchain:
- **Ruff:** Used for both linting and formatting (replaces isort)
- **Bandit:** Security scanning (configured via pyproject.toml)
- **Type checking:** Uses `ty` instead of mypy (run separately with `uv run ty`)

### 4. Test Framework

Configured for pytest with coverage:
- Uses pytest's built-in coverage support
- Coverage output to `/tmp/mcp_mail/coverage/`
- Support for both unit and integration tests

### 5. Coverage Reports

Adapted coverage report generation:
- HTML reports saved to `/tmp/mcp_mail/coverage/index.html`
- Text reports for CI/CD pipelines
- Configurable integration test inclusion

## Integration with Existing Workflows

### GitHub Actions Integration

Add these scripts to your CI/CD pipeline:

```yaml
name: Code Quality

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Run linting
        run: ./scripts/run_lint.sh

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Run tests with coverage
        run: ./scripts/run_tests_with_coverage.sh --no-html
```

### Pre-commit Hooks

Add to `.githooks/pre-commit`:

```bash
#!/bin/bash
# Run linting before commit
./scripts/run_lint.sh || {
    echo "Linting failed. Run './scripts/run_lint.sh src/mcp_agent_mail fix' to auto-fix."
    exit 1
}
```

### Pre-push Hooks

Add to `.githooks/pre-push`:

```bash
#!/bin/bash
# Run tests before push
./scripts/run_tests_with_coverage.sh --no-html || {
    echo "Tests failed. Fix tests before pushing."
    exit 1
}
```

## Quick Reference

### Common Development Tasks

```bash
# Code quality check
./scripts/run_lint.sh

# Auto-fix linting issues
./scripts/run_lint.sh src/mcp_agent_mail fix

# Run all tests with coverage
./scripts/coverage.sh

# Run tests without HTML report (CI)
./scripts/run_tests_with_coverage.sh --no-html

# Include integration tests
./scripts/coverage.sh --integration

# Count lines of code
./scripts/loc.sh

# Sync branch with main
./scripts/sync_branch.sh

# Create project snapshot
./scripts/create_snapshot.sh
```

### Script Locations

- **Root-level scripts:** For project-wide operations
  - `create_worktree.sh`, `integrate.sh`, `schedule_branch_work.sh`

- **scripts/ directory:** For development utilities
  - All other scaffolded scripts

## Maintenance

### Updating Scripts

To update scripts from claude-commands:

1. Pull latest claude-commands repository
2. Run the scaffolding command again (will overwrite existing scripts)
3. Re-apply mcp_mail-specific adaptations if needed

### Adding New Scripts

When adding new scripts:
1. Place in `scripts/` directory
2. Make executable: `chmod +x scripts/new_script.sh`
3. Document in this file
4. Add to git: `git add scripts/new_script.sh`

## Troubleshooting

### "uv not found" errors

Install uv:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Coverage reports not generating

Ensure coverage is installed:
```bash
uv pip install coverage pytest-cov
```

### Permission denied errors

Make scripts executable:
```bash
chmod +x scripts/*.sh *.sh
```

### Scripts reference wrong directories

Check these environment variables:
- `PROJECT_SRC_DIR` - Override source directory
- `COVERAGE_DIR` - Override coverage output location

## Next Steps

1. ✅ **Script Verification:** Test each script to ensure it works with the project
2. ✅ **Permission Setup:** All scripts are executable
3. **Integration Testing:** Run scripts to verify they work correctly
4. **Documentation:** Reference this file in main README.md
5. **CI/CD Integration:** Add scripts to GitHub Actions workflows
6. **Team Communication:** Share this documentation with collaborators

## Benefits

- **Consistency:** Standardized development workflows across projects
- **Quality:** Automated linting and testing enforcement
- **Efficiency:** Quick access to common development tasks
- **Best Practices:** Scripts embody established patterns and conventions
- **Time Savings:** Avoid manual setup of development infrastructure
- **Maintainability:** Centralized script updates from claude-commands repository

## Support

For issues or questions about:
- **Scaffolded scripts:** See [claude-commands repository](https://github.com/jleechanorg/claude-commands)
- **mcp_mail-specific adaptations:** See project maintainers or CLAUDE.md
- **General development:** See README.md and project documentation
