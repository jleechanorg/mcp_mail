#!/usr/bin/env bash
# Auto-register agent with MCP Mail on session start.
# Usage: ./scripts/auto_register_agent.sh [--suffix SUFFIX] [--program PROGRAM] [--model MODEL]
#
# Examples:
#   Claude Code:  ./scripts/auto_register_agent.sh --program claude-code --model opus
#   Codex CLI:    ./scripts/auto_register_agent.sh --suffix c --program codex-cli --model o3
#
# The agent name is derived from the current git branch:
#   - Branch: feature/auth-system -> agent name: featureauthsystem
#   - With --suffix c: featureauthsystemc
#
# Environment variables:
#   HTTP_BEARER_TOKEN  - Required for authentication (or loaded from .env)
#   MCP_MAIL_URL       - Server URL (default: http://127.0.0.1:8765/mcp)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh" 2>/dev/null || true

# Initialize colors if lib.sh loaded
if command -v init_colors >/dev/null 2>&1; then
  init_colors
fi

# Defaults
SUFFIX=""
PROGRAM="unknown"
MODEL="unknown"
MCP_MAIL_URL="${MCP_MAIL_URL:-http://127.0.0.1:8765/mcp}"
QUIET="${QUIET:-0}"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --suffix)
      SUFFIX="$2"
      shift 2
      ;;
    --suffix=*)
      SUFFIX="${1#*=}"
      shift
      ;;
    --program)
      PROGRAM="$2"
      shift 2
      ;;
    --program=*)
      PROGRAM="${1#*=}"
      shift
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --model=*)
      MODEL="${1#*=}"
      shift
      ;;
    --quiet)
      QUIET=1
      shift
      ;;
    --url)
      MCP_MAIL_URL="$2"
      shift 2
      ;;
    --url=*)
      MCP_MAIL_URL="${1#*=}"
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [--suffix SUFFIX] [--program PROGRAM] [--model MODEL] [--quiet] [--url URL]"
      echo ""
      echo "Auto-register agent with MCP Mail using git branch name."
      echo ""
      echo "Options:"
      echo "  --suffix    Suffix to add to agent name (e.g., 'c' for Codex)"
      echo "  --program   Agent program identifier (e.g., 'claude-code', 'codex-cli')"
      echo "  --model     Model identifier (e.g., 'opus', 'o3')"
      echo "  --quiet     Suppress output on success"
      echo "  --url       MCP Mail server URL (default: http://127.0.0.1:8765/mcp)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Load bearer token from environment or .env
strip_token() {
  local token="${1:-}"
  # Trim surrounding whitespace
  token="${token#${token%%[![:space:]]*}}"
  token="${token%${token##*[![:space:]]}}"
  # Trim optional single/double quotes
  token="${token%\"}"
  token="${token#\"}"
  token="${token%\'}"
  token="${token#\'}"
  echo "$token"
}

if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  if [[ -f .env ]]; then
    HTTP_BEARER_TOKEN=$(grep -E '^HTTP_BEARER_TOKEN=' .env | sed -E 's/^HTTP_BEARER_TOKEN=//' | head -1) || true
  fi
  if [[ -z "${HTTP_BEARER_TOKEN:-}" ]] && [[ -f ~/.config/mcp-agent-mail/.env ]]; then
    HTTP_BEARER_TOKEN=$(grep -E '^HTTP_BEARER_TOKEN=' ~/.config/mcp-agent-mail/.env | sed -E 's/^HTTP_BEARER_TOKEN=//' | head -1) || true
  fi
fi

HTTP_BEARER_TOKEN=$(strip_token "${HTTP_BEARER_TOKEN:-}")

if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  echo "ERROR: HTTP_BEARER_TOKEN not set and not found in .env" >&2
  exit 1
fi

# Get current git branch
get_git_branch() {
  local branch=""

  # Try active branch first
  if command -v git >/dev/null 2>&1; then
    branch=$(git symbolic-ref --short HEAD 2>/dev/null) || true

    # Fallback for detached HEAD
    if [[ -z "$branch" ]]; then
      branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || true
    fi
  fi

  # Final fallback
  if [[ -z "$branch" ]] || [[ "$branch" == "HEAD" ]]; then
    branch="main"
  fi

  echo "$branch"
}

# Sanitize branch name to alphanumeric only (agent name requirement)
sanitize_agent_name() {
  local raw="$1"
  # Remove all non-alphanumeric characters, convert to lowercase
  echo "$raw" | tr -cd '[:alnum:]' | tr '[:upper:]' '[:lower:]'
}

# Main logic
BRANCH=$(get_git_branch)
AGENT_BASE=$(sanitize_agent_name "$BRANCH")
AGENT_NAME="${AGENT_BASE}${SUFFIX}"

# Validate agent name is not empty
if [[ -z "$AGENT_NAME" ]]; then
  echo "ERROR: Could not derive valid agent name from branch: $BRANCH" >&2
  exit 1
fi

# Build JSON-RPC request
REQUEST_ID=$(python3 - <<'PY'
import random
import time

timestamp = int(time.time() * 1_000_000)  # microseconds for portability
rand_suffix = random.randint(0, 9999)
print(f"{timestamp:014d}{rand_suffix:04d}"[:16])
PY
)
JSON_PAYLOAD=$(cat <<EOF
{
  "jsonrpc": "2.0",
  "id": "${REQUEST_ID}",
  "method": "tools/call",
  "params": {
    "name": "register_agent",
    "arguments": {
      "name": "${AGENT_NAME}",
      "program": "${PROGRAM}",
      "model": "${MODEL}",
      "task_description": "Auto-registered from branch ${BRANCH}"
    }
  }
}
EOF
)

# Make HTTP request
TMP_RESPONSE=$(mktemp)
HTTP_STATUS=$(curl -sS --connect-timeout 5 --max-time 30 \
  -o "$TMP_RESPONSE" \
  -w '%{http_code}' \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${HTTP_BEARER_TOKEN}" \
  -d "$JSON_PAYLOAD" \
  "${MCP_MAIL_URL}" 2>&1) || {
  echo "ERROR: Failed to connect to MCP Mail server at ${MCP_MAIL_URL}" >&2
  rm -f "$TMP_RESPONSE"
  exit 1
}
RESPONSE=$(cat "$TMP_RESPONSE")
rm -f "$TMP_RESPONSE"

if [[ ! "$HTTP_STATUS" =~ ^[0-9]{3}$ ]] || [[ "$HTTP_STATUS" -lt 200 || "$HTTP_STATUS" -ge 300 ]]; then
  echo "ERROR: Registration request failed with HTTP status ${HTTP_STATUS:-unknown}" >&2
  if [[ -n "$RESPONSE" ]]; then
    echo "Response: $RESPONSE" >&2
  fi
  exit 1
fi

# Check for JSON-RPC errors
ERROR_MSG=$(python3 - <<'PY'
import json
import sys

raw = sys.stdin.read()
try:
  payload = json.loads(raw)
except Exception:
  sys.exit(1)

error = payload.get("error")
if not error:
  sys.exit(2)

message = error.get("message") or json.dumps(error)
print(message)
PY
<<< "$RESPONSE" )

case $? in
  0)
    echo "ERROR: Registration failed: ${ERROR_MSG}" >&2
    exit 1
    ;;
  1)
    echo "ERROR: Unexpected response format: $RESPONSE" >&2
    exit 1
    ;;
  *)
    : # Success path (no error field)
    ;;
esac

# Success
if [[ "$QUIET" != "1" ]]; then
  echo "Registered agent '${AGENT_NAME}' (branch: ${BRANCH}, program: ${PROGRAM})"
fi

exit 0
