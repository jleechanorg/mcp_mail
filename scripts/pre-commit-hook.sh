#!/bin/bash
# Pre-commit hook for MCP Mail
# This hook runs linting and type checking before each commit

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🔍 Running pre-commit checks..."

# Ensure required tooling is available
missing_dependency() {
    echo -e "${RED}✗ Error: '$1' is not installed. Please install it before committing.${NC}"
    exit 1
}

command -v uv >/dev/null 2>&1 || missing_dependency "uv"
command -v uvx >/dev/null 2>&1 || missing_dependency "uvx"

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

# 2. Run Ty type checker (optional - can fail due to Python version differences)
echo "🔬 Running Ty type checker..."
if uvx ty check; then
    echo -e "${GREEN}✓ Type checks passed${NC}"
else
    echo -e "${YELLOW}⚠ Type checks failed (non-blocking - CI will validate)${NC}"
    echo -e "${YELLOW}  Note: Local Python version may differ from CI (3.13)${NC}"
fi

# 3. Run fast unit tests
echo "🧪 Running fast unit tests..."
run_fast_tests() {
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
        echo -e "${YELLOW}⚠ No fast tests found; skipping pytest${NC}"
        return 0
    fi

    uv run pytest "${existing[@]}" -q
}

if run_fast_tests; then
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
