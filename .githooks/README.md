# Git hooks

We use local hooks in `.githooks` (pre-commit + post-checkout/post-merge) and set `core.hooksPath` to this directory.

## Install / enforce

```bash
git config core.hooksPath .githooks
```

The post-checkout and post-merge hooks here will reassert `core.hooksPath=.githooks` if it drifts.

## Pre-commit hook

Runs:
- `uv sync --dev` (cached)
- `uvx ruff check --fix --unsafe-fixes` (blocking)
- `uvx ty check` (non-blocking)
- `uv run bandit ...` (non-blocking)
- `uv run safety check` (non-blocking)
