# Enforcing Pre-Commit Hooks

This document explains how pre-commit hooks are enforced in this repository.

## Automatic Installation Methods

### 1. Post-Checkout Hook (Auto-installs)
A `.git/hooks/post-checkout` hook automatically installs pre-commit hooks when you:
- Clone the repository
- Checkout a branch
- Pull changes

This ensures hooks are always installed, even on fresh clones.

### 2. Makefile Target
Run `make install-hooks` or `make setup` to install hooks:
```bash
make install-hooks  # Install hooks only
make setup          # Full project setup (includes hooks)
```

### 3. Setup Script
Run the setup script directly:
```bash
./scripts/setup_git_hooks.sh
```

## CI Enforcement

The CI workflow (`.github/workflows/pre-commit-enforcement.yml`) checks if hooks are installed and warns if they're not. This helps developers know they should install hooks locally.

## Manual Installation

If automatic installation doesn't work:
```bash
pip install pre-commit  # or: uv tool install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
```

## Why This Matters

Pre-commit hooks:
- ✅ Auto-format code with Ruff before commit
- ✅ Catch linting errors locally
- ✅ Prevent formatting issues from reaching CI
- ✅ Save time by fixing issues before push

## Verification

Check if hooks are installed:
```bash
ls -la .git/hooks/pre-commit
```

If it exists and is executable, hooks are installed.

## Troubleshooting

If hooks aren't running:
1. Check installation: `ls -la .git/hooks/pre-commit`
2. Reinstall: `make install-hooks`
3. Test manually: `pre-commit run --all-files`
