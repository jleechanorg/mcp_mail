#!/bin/bash
# Setup git hooks for the repository

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Setting up git hooks...${NC}"

# Get the repository root
REPO_ROOT="$(git rev-parse --show-toplevel)"

# Make sure we're in a git repository
if [ ! -d "$REPO_ROOT/.git" ]; then
    echo "Error: Not in a git repository"
    exit 1
fi

# Create hooks directory if it doesn't exist
mkdir -p "$REPO_ROOT/.git/hooks"

# Install pre-commit hook
if [ -f "$REPO_ROOT/.githooks/pre-commit" ]; then
    cp "$REPO_ROOT/.githooks/pre-commit" "$REPO_ROOT/.git/hooks/pre-commit"
    chmod +x "$REPO_ROOT/.git/hooks/pre-commit"
    echo -e "${GREEN}✓ Installed pre-commit hook${NC}"
else
    echo "Warning: .githooks/pre-commit not found"
fi

echo -e "${GREEN}Git hooks setup complete!${NC}"
echo ""
echo "The following hooks are now active:"
echo "  - pre-commit: Runs ruff and type checks before each commit"
echo ""
echo "To skip hooks for a specific commit, use: git commit --no-verify"
