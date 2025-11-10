#!/bin/bash
# Pre-commit hook for MCP Mail
# This hook runs linting and type checking before each commit

set -e

echo "🔍 Running pre-commit checks..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track if any checks fail
FAILED=0

# 1. Run Ruff linter
echo "📝 Running Ruff linter..."
if uv run ruff check --output-format=github; then
    echo -e "${GREEN}✓ Ruff checks passed${NC}"
else
    echo -e "${RED}✗ Ruff checks failed${NC}"
    FAILED=1
fi

# 2. Run Ty type checker
echo "🔬 Running Ty type checker..."
if uvx ty check; then
    echo -e "${GREEN}✓ Type checks passed${NC}"
else
    echo -e "${RED}✗ Type checks failed${NC}"
    FAILED=1
fi

# 3. Run fast unit tests
echo "🧪 Running fast unit tests..."
if uv run pytest tests/test_reply_and_threads.py tests/test_identity_resources.py -q; then
    echo -e "${GREEN}✓ Fast tests passed${NC}"
else
    echo -e "${RED}✗ Fast tests failed${NC}"
    FAILED=1
fi

# Final result
if [ $FAILED -eq 0 ]; then
    echo -e "\n${GREEN}✓ All pre-commit checks passed!${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Some pre-commit checks failed. Please fix before committing.${NC}"
    echo -e "${YELLOW}Tip: Run 'uv run ruff check --fix' to auto-fix linting issues${NC}"
    exit 1
fi
