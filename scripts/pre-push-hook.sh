#!/bin/bash
# Pre-push hook for MCP Mail
# This hook runs full test suite including integration tests before pushing

set -e

echo "🚀 Running pre-push checks..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track if any checks fail
FAILED=0

# 1. Run integration tests
echo "🧪 Running integration tests..."
if uv run pytest tests/integration/test_mcp_mail_messaging.py -v; then
    echo -e "${GREEN}✓ Integration tests passed${NC}"
else
    echo -e "${RED}✗ Integration tests failed${NC}"
    FAILED=1
fi

# 2. Run smoke tests
echo "🧪 Running smoke tests..."
if uv run pytest tests/test_reply_and_threads.py tests/test_identity_resources.py -v; then
    echo -e "${GREEN}✓ Smoke tests passed${NC}"
else
    echo -e "${RED}✗ Smoke tests failed${NC}"
    FAILED=1
fi

# Final result
if [ $FAILED -eq 0 ]; then
    echo -e "\n${GREEN}✓ All pre-push checks passed!${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Some pre-push checks failed. Please fix before pushing.${NC}"
    echo -e "${YELLOW}Tip: Run 'uv run pytest tests/integration/ -v' to debug integration test failures${NC}"
    exit 1
fi
