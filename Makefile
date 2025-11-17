.PHONY: serve-http migrate lint typecheck guard-install guard-uninstall claims setup install-hooks

PY=uv run
CLI=$(PY) python -m mcp_agent_mail.cli

serve-http:
	$(CLI) serve-http

migrate:
	$(CLI) migrate

lint:
	$(PY) ruff check --fix --unsafe-fixes

typecheck:
	uvx ty check

guard-install:
	$(CLI) guard install $(PROJECT) $(REPO)

guard-uninstall:
	$(CLI) guard uninstall $(REPO)

claims:
	$(CLI) claims list --active-only $(ACTIVE) $(PROJECT)

# Setup project (install dependencies and git hooks)
setup: install-hooks
	@echo "✅ Project setup complete!"

# Install pre-commit hooks (enforced for code quality)
install-hooks:
	@echo "🔧 Ensuring pre-commit hooks are installed..."
	@./scripts/setup_git_hooks.sh || (echo "⚠️  Warning: Could not install hooks. Run manually: ./scripts/setup_git_hooks.sh" && exit 1)
