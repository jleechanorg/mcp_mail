#!/bin/bash
# Install git hooks for MCP Mail presubmit checks
# Run this script to set up pre-commit and pre-push hooks

set -e

echo "🔧 Installing MCP Mail git hooks..."

# Get the root directory of the git repository
GIT_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$GIT_ROOT/.git/hooks"

# Check if we're in a git repository
if [ ! -d "$HOOKS_DIR" ]; then
    echo "❌ Error: Not in a git repository or .git/hooks directory not found"
    exit 1
fi

# Install pre-commit hook
echo "📝 Installing pre-commit hook..."
ln -sf "$GIT_ROOT/scripts/pre-commit-hook.sh" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"
echo "✓ Pre-commit hook installed"

# Install pre-push hook
echo "📝 Installing pre-push hook..."
ln -sf "$GIT_ROOT/scripts/pre-push-hook.sh" "$HOOKS_DIR/pre-push"
chmod +x "$HOOKS_DIR/pre-push"
echo "✓ Pre-push hook installed"

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
