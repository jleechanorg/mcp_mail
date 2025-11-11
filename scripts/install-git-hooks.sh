#!/bin/bash
# Install git hooks for MCP Mail presubmit checks
# Run this script to set up pre-commit and pre-push hooks

set -e

FORCE=0

while (($#)); do
    case "$1" in
        --force)
            FORCE=1
            shift
            ;;
        *)
            echo "❌ Error: Unknown option '$1'"
            echo "Usage: $0 [--force]"
            exit 1
            ;;
    esac
done

echo "🔧 Installing MCP Mail git hooks..."

# Get the root directory of the git repository
GIT_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$GIT_ROOT/.git/hooks"

# Colors for output
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

# Check if we're in a git repository
if [ ! -d "$HOOKS_DIR" ]; then
    echo "❌ Error: Not in a git repository or .git/hooks directory not found"
    exit 1
fi

install_hook() {
    local name="$1"
    local target="$2"
    local destination="$HOOKS_DIR/$name"

    echo "📝 Installing $name hook..."

    if [ -e "$destination" ] && [ ! -L "$destination" ]; then
        if [ "$FORCE" -eq 1 ]; then
            local backup="$destination.$(date +%Y%m%d%H%M%S).bak"
            mv "$destination" "$backup"
            echo "${YELLOW}⚠ Backed up existing $name hook to $backup${NC}"
        elif [ -t 0 ]; then
            echo -e "${YELLOW}⚠ Warning: Existing $name hook found (not a symlink).${NC}"
            printf "Overwrite? (y/N): "
            read -r response
            if [[ ! "$response" =~ ^[Yy]$ ]]; then
                echo "Skipping $name hook installation"
                return
            fi
        else
            echo -e "${YELLOW}⚠ Warning: Existing $name hook found (not a symlink). Rerun with --force to overwrite.${NC}"
            return
        fi
    fi

    ln -sf "$target" "$destination"
    chmod +x "$destination"
    echo "${GREEN}✓ $name hook installed${NC}"
}

install_hook "pre-commit" "$GIT_ROOT/scripts/pre-commit-hook.sh"
install_hook "pre-push" "$GIT_ROOT/scripts/pre-push-hook.sh"

echo ""
echo "✅ Git hooks successfully installed!"
echo ""
echo "The following checks will now run:"
echo "  • Before commit: Ruff linting, Ty type checking, fast unit tests"
echo "  • Before push: Integration tests, smoke tests"
echo ""
echo "To skip hooks temporarily, use:"
echo "  git commit --no-verify"
echo "  git push --no-verify"
echo ""
echo "To uninstall hooks:"
echo "  rm .git/hooks/pre-commit .git/hooks/pre-push"
echo ""
echo "Pass --force to overwrite existing hooks without prompting (backups are kept)."
