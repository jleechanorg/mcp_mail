#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SLACK_WEBHOOK_URL:-}" ]]; then
  if [[ -f .env ]]; then
    SLACK_WEBHOOK_URL=$(grep -E '^SLACK_WEBHOOK_URL=' .env | sed -E 's/^SLACK_WEBHOOK_URL=//') || true
  fi
fi
export SLACK_WEBHOOK_URL

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1090
. "${SCRIPT_DIR}/lib.sh"
load_or_generate_token python3

uv run python -m mcp_agent_mail.cli serve-http "$@"