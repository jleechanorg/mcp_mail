#!/usr/bin/env bash
set -euo pipefail

# 2026-07-20: load the slack-off overlay FIRST so its SLACK_ENABLED=false
# wins over any later inherited env (e.g. ~/.bashrc exports).
# The MCP Agent Mail server is for agent-to-agent mail; the passive Slack
# listening path was the source of bot self-reports leaking into operator
# threads (incident C09GRLXF9GR/p1784573557759039).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/../.env.slack-off" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/../.env.slack-off"
  set +a
fi

if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  if [[ -f .env ]]; then
    HTTP_BEARER_TOKEN=$(grep -E '^HTTP_BEARER_TOKEN=' .env | sed -E 's/^HTTP_BEARER_TOKEN=//') || true
  fi
fi
# 2026-07-20: stop pulling SLACK_WEBHOOK_URL out of .env — if the user
# re-enables slack, they should set it explicitly via .env.slack-off.
# Leaving the variable defined keeps any older tool paths that read it
# from blowing up, but the outbound notifier is now gated by SLACK_ENABLED=false.
if [[ -z "${SLACK_WEBHOOK_URL:-}" ]]; then
  if [[ -f .env ]]; then
    SLACK_WEBHOOK_URL=$(grep -E '^SLACK_WEBHOOK_URL=' .env | sed -E 's/^SLACK_WEBHOOK_URL=//') || true
  fi
fi
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  if command -v uv >/dev/null 2>&1; then
    HTTP_BEARER_TOKEN=$(uv run python - <<'PY'
import secrets; print(secrets.token_hex(32))
PY
)
  else
    HTTP_BEARER_TOKEN="$(date +%s)_$(hostname)"
  fi
fi
export HTTP_BEARER_TOKEN
export SLACK_WEBHOOK_URL

uv run python -m mcp_agent_mail.cli serve-http "$@"
