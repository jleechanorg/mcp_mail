#!/bin/bash
# Install post-checkout hook that auto-installs pre-commit hooks
# This ensures hooks are always installed, even on fresh clones

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"
POST_CHECKOUT_HOOK="$HOOKS_DIR/post-checkout"

cat > "$POST_CHECKOUT_HOOK" << 'EOF'
#!/bin/bash
# Auto-install pre-commit hooks after checkout/clone
# This ensures hooks are always installed, even on fresh clones

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Only install if hooks aren't already installed
if [ ! -f .git/hooks/pre-commit ] || ! grep -q "pre-commit" .git/hooks/pre-commit 2>/dev/null; then
    # Check if setup script exists
    if [ -f scripts/setup_git_hooks.sh ]; then
        echo "🔧 Auto-installing pre-commit hooks..."
        bash scripts/setup_git_hooks.sh >/dev/null 2>&1 || true
    elif command -v pre-commit >/dev/null 2>&1; then
        echo "🔧 Auto-installing pre-commit hooks..."
        pre-commit install >/dev/null 2>&1 || true
        pre-commit install --hook-type pre-push >/dev/null 2>&1 || true
    fi
fi
EOF

chmod +x "$POST_CHECKOUT_HOOK"
echo "✅ Post-checkout hook installed (will auto-install pre-commit hooks)"
