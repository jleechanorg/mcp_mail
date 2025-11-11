#!/bin/bash
# Pre-push hook for MCP Mail
# This hook runs full test suite including integration tests before pushing

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🚀 Running pre-push checks..."

# Ensure required tooling is available
missing_dependency() {
    echo -e "${RED}✗ Error: '$1' is not installed. Please install it before pushing.${NC}"
    exit 1
}

command -v uv >/dev/null 2>&1 || missing_dependency "uv"
command -v uvx >/dev/null 2>&1 || missing_dependency "uvx"

# Track if any checks fail
FAILED=0

# 1. Run Ty type checker (blocking - must pass before push)
echo "🔬 Running Ty type checker..."
if uvx ty check; then
    echo -e "${GREEN}✓ Type checks passed${NC}"
else
    echo -e "${RED}✗ Type checks failed${NC}"
    echo -e "${YELLOW}Type errors must be fixed before pushing to match CI requirements${NC}"
    FAILED=1
fi

# 2. Run integration tests
echo "🧪 Running integration tests..."
run_integration_tests() {
    local integration_file="tests/integration/test_mcp_mail_messaging.py"
    if [ ! -f "$integration_file" ]; then
        echo -e "${YELLOW}⚠ Integration suite not found; skipping${NC}"
        return 0
    fi

    uv run pytest "$integration_file" -v
}

if run_integration_tests; then
    echo -e "${GREEN}✓ Integration tests passed${NC}"
else
    echo -e "${RED}✗ Integration tests failed${NC}"
    FAILED=1
fi

# 3. Run smoke tests
echo "🧪 Running smoke tests..."
run_smoke_tests() {
    local tests=("tests/test_reply_and_threads.py" "tests/test_identity_resources.py")
    local existing=()

    for test_path in "${tests[@]}"; do
        if [ -f "$test_path" ]; then
            existing+=("$test_path")
        else
            echo -e "${YELLOW}⚠ Skipping missing smoke test: $test_path${NC}"
        fi
    done

    if [ ${#existing[@]} -eq 0 ]; then
        echo -e "${YELLOW}⚠ No smoke tests found; skipping pytest${NC}"
        return 0
    fi

    uv run pytest "${existing[@]}" -v
}

if run_smoke_tests; then
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
