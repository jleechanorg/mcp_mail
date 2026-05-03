#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1090
. "${SCRIPT_DIR}/lib.sh"

load_or_generate_token python3

uv run python -m mcp_agent_mail.cli serve-http "$@"