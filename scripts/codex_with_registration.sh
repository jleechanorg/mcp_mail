#!/usr/bin/env bash
# Wrapper script to start Codex CLI with auto-registration to MCP Mail.
# Usage: ./scripts/codex_with_registration.sh [codex args...]
#
# This script:
#   1. Auto-registers an agent with name = git branch + "c" suffix
#   2. Launches Codex CLI with the provided arguments
#
# Example: ./scripts/codex_with_registration.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-register agent (branch name + "c" suffix for Codex)
echo "Auto-registering Codex agent with MCP Mail..."
ERROR_LOG=$(mktemp)
trap 'rm -f "$ERROR_LOG"' EXIT

if ! "${SCRIPT_DIR}/auto_register_agent.sh" --suffix c --program codex-cli --model o3 --quiet 2>"$ERROR_LOG"; then
  echo "Warning: Could not register agent (server may not be running)" >&2
  if [[ -s "$ERROR_LOG" ]]; then
    echo "Details:" >&2
    cat "$ERROR_LOG" >&2
  fi
fi

# Launch Codex CLI with all arguments passed through
exec codex "$@"
