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

# Capture stderr to temp file for conditional display
TEMP_ERR=$(mktemp)
"${SCRIPT_DIR}/auto_register_agent.sh" --suffix c --program codex-cli --model o3 --quiet 2>"$TEMP_ERR" || {
  if [[ -s "$TEMP_ERR" ]]; then
    echo "Warning: Could not register agent:" >&2
    cat "$TEMP_ERR" >&2
  else
    echo "Warning: Could not register agent (server may not be running)" >&2
  fi
}
rm -f "$TEMP_ERR"

# Launch Codex CLI
exec codex "$@"
