#!/bin/bash
# Setup git hooks for the repository using pre-commit framework

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Setting up git hooks with pre-commit framework...${NC}"

# Get the repository root
REPO_ROOT="$(git rev-parse --show-toplevel)"

# Make sure we're in a git repository
if [ ! -d "$REPO_ROOT/.git" ]; then
    echo "Error: Not in a git repository"
    exit 1
fi

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo -e "${YELLOW}pre-commit not found. Installing via uv...${NC}"
    uv tool install pre-commit
    echo -e "${GREEN}✓ Installed pre-commit framework${NC}"
else
    echo -e "${BLUE}pre-commit is already installed${NC}"
fi

# Install pre-commit hooks
echo -e "${YELLOW}Installing pre-commit hooks...${NC}"
cd "$REPO_ROOT"
pre-commit install
pre-commit install --hook-type pre-push

echo -e "${GREEN}✓ Pre-commit hooks installed successfully${NC}"
echo ""
echo -e "${GREEN}Git hooks setup complete!${NC}"
echo ""
echo "The following hooks are now active:"
echo "  ${BLUE}pre-commit:${NC}"
echo "    • Ruff linter (auto-fix enabled)"
echo "    • Trailing whitespace fixer"
echo "    • End-of-file fixer"
echo "    • YAML/JSON syntax checks"
echo "    • Large file detection"
echo "    • Merge conflict detection"
echo "    • Type checking with ty"
echo "    • Fast unit tests"
echo ""
echo "  ${BLUE}pre-push:${NC}"
echo "    • Integration tests"
echo ""
echo "To skip hooks for a specific commit: ${YELLOW}git commit --no-verify${NC}"
echo "To run hooks manually: ${YELLOW}pre-commit run --all-files${NC}"
echo ""
echo "Configuration is in ${BLUE}.pre-commit-config.yaml${NC}"
