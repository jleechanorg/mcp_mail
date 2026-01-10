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

# Load shared helpers if available
if [[ -r "${SCRIPT_DIR}/lib.sh" ]]; then
  source "${SCRIPT_DIR}/lib.sh"
else
  # Fallback: Minimal token loading if lib.sh is missing (standalone mode)
  load_token_from_file() {
    local file="$1"
    local line value
    [[ -f "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
      case "$line" in
        ''|'#'*) continue ;;
        HTTP_BEARER_TOKEN=*)
          value="${line#HTTP_BEARER_TOKEN=}"
          # Simple strip (remove quotes/whitespace)
          value="${value#"${value%%[![:space:]]*}"}"
          value="${value%"${value##*[![:space:]]}"}"
          if [[ ( "${value:0:1}" == '"' && "${value: -1}" == '"' ) || ( "${value:0:1}" == "'" && "${value: -1}" == "'" ) ]]; then
            value="${value:1:${#value}-2}"
          fi
          if [[ -n "$value" ]]; then HTTP_BEARER_TOKEN="$value"; fi
          break
          ;;
      esac
    done < "$file"
  }
fi

# Ensure HTTP_BEARER_TOKEN is available for Codex CLI
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  # Try standard locations
  if [[ -f "${HOME}/.mcp_mail/credentials.json" ]] && command -v jq >/dev/null 2>&1; then
    HTTP_BEARER_TOKEN=$(jq -r '.HTTP_BEARER_TOKEN // empty' "${HOME}/.mcp_mail/credentials.json" 2>/dev/null || true)
  fi
  
  if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
     REPO_ROOT="$(cd "$SCRIPT_DIR" && git rev-parse --show-toplevel 2>/dev/null || echo ".")"
     load_token_from_file "${REPO_ROOT}/.env"
  fi
  
  if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
    load_token_from_file "${HOME}/.config/mcp-agent-mail/.env"
  fi
  
  if [[ -n "${HTTP_BEARER_TOKEN:-}" ]]; then
    export HTTP_BEARER_TOKEN
  fi
fi

# Auto-register agent (branch name + "c" suffix for Codex)
echo "Auto-registering Codex agent with MCP Mail..."
if ! error_output=$("${SCRIPT_DIR}/auto_register_agent.sh" --suffix c --program codex-cli --model o3 2>&1); then
  echo "Warning: Could not register Codex agent with MCP Mail (server may not be running)." >&2
  echo "Details:" >&2
  printf '%s\n' "$error_output" >&2
fi

# Launch Codex CLI with all arguments passed through
exec codex "$@"
