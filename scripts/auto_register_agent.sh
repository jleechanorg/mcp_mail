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
# Source lib.sh if it exists and is readable
if [[ -f "${SCRIPT_DIR}/lib.sh" ]] && [[ -r "${SCRIPT_DIR}/lib.sh" ]]; then
  source "${SCRIPT_DIR}/lib.sh" 2>/dev/null || true
fi

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
      if [[ -z "${2:-}" ]] || [[ "$2" == --* ]]; then
        echo "ERROR: --suffix requires a value" >&2
        exit 1
      fi
      SUFFIX="$2"
      shift 2
      ;;
    --suffix=*)
      SUFFIX="${1#*=}"
      shift
      ;;
    --program)
      if [[ -z "${2:-}" ]] || [[ "$2" == --* ]]; then
        echo "ERROR: --program requires a value" >&2
        exit 1
      fi
      PROGRAM="$2"
      shift 2
      ;;
    --program=*)
      PROGRAM="${1#*=}"
      shift
      ;;
    --model)
      if [[ -z "${2:-}" ]] || [[ "$2" == --* ]]; then
        echo "ERROR: --model requires a value" >&2
        exit 1
      fi
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
      if [[ -z "${2:-}" ]] || [[ "$2" == --* ]]; then
        echo "ERROR: --url requires a value" >&2
        exit 1
      fi
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

# Function to load token from .env file and strip surrounding quotes
load_token_from_env() {
  local env_file="$1"
  local token=""
  
  if [[ -f "$env_file" ]]; then
    token=$(grep -E '^HTTP_BEARER_TOKEN=' "$env_file" | sed -E 's/^HTTP_BEARER_TOKEN=//' | head -1) || true
    # Strip surrounding quotes if present
    token="${token%\"}"
    token="${token#\"}"
    token="${token%\'}"
    token="${token#\'}"
  fi
  
  echo "$token"
}

# Load bearer token from environment or .env
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  HTTP_BEARER_TOKEN=$(load_token_from_env ".env")
  if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
    HTTP_BEARER_TOKEN=$(load_token_from_env "${HOME}/.config/mcp-agent-mail/.env")
  fi
fi

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

# Generate request ID (use portable date command + PID for uniqueness)
# Note: Using $$ (process ID) for portability across Linux and macOS
REQUEST_ID="$(date +%s)$$"

# Build JSON-RPC request using jq for safe JSON construction
# Security note: Bearer token is visible in process listing during execution
if command -v jq >/dev/null 2>&1; then
  JSON_PAYLOAD=$(jq -n \
    --arg request_id "$REQUEST_ID" \
    --arg agent_name "$AGENT_NAME" \
    --arg program "$PROGRAM" \
    --arg model "$MODEL" \
    --arg branch "$BRANCH" \
    '{
      "jsonrpc": "2.0",
      "id": $request_id,
      "method": "tools/call",
      "params": {
        "name": "register_agent",
        "arguments": {
          "name": $agent_name,
          "program": $program,
          "model": $model,
          "task_description": ("Auto-registered from branch " + $branch)
        }
      }
    }')
else
  # Fallback: basic escaping for JSON strings (replace ", \, and control characters)
  escape_json() {
    local str="$1"
    str="${str//\\/\\\\}"    # Escape backslashes
    str="${str//\"/\\\"}"    # Escape quotes
    str="${str//$'\n'/\\n}"  # Escape newlines
    str="${str//$'\r'/\\r}"  # Escape carriage returns
    str="${str//$'\t'/\\t}"  # Escape tabs
    echo "$str"
  }
  
  AGENT_NAME_ESC=$(escape_json "$AGENT_NAME")
  PROGRAM_ESC=$(escape_json "$PROGRAM")
  MODEL_ESC=$(escape_json "$MODEL")
  BRANCH_ESC=$(escape_json "$BRANCH")
  
  JSON_PAYLOAD=$(cat <<EOF
{
  "jsonrpc": "2.0",
  "id": "${REQUEST_ID}",
  "method": "tools/call",
  "params": {
    "name": "register_agent",
    "arguments": {
      "name": "${AGENT_NAME_ESC}",
      "program": "${PROGRAM_ESC}",
      "model": "${MODEL_ESC}",
      "task_description": "Auto-registered from branch ${BRANCH_ESC}"
    }
  }
}
EOF
)
fi

# Make HTTP request with status code capture
HTTP_RESPONSE=$(mktemp)
HTTP_STATUS=$(curl -sS --connect-timeout 5 --max-time 30 \
  -w '%{http_code}' \
  -o "$HTTP_RESPONSE" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${HTTP_BEARER_TOKEN}" \
  -d "$JSON_PAYLOAD" \
  "${MCP_MAIL_URL}" 2>&1) || {
  rm -f "$HTTP_RESPONSE"
  echo "ERROR: Failed to connect to MCP Mail server at ${MCP_MAIL_URL}" >&2
  exit 1
}

RESPONSE=$(cat "$HTTP_RESPONSE")
rm -f "$HTTP_RESPONSE"

# Check HTTP status code
if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "ERROR: HTTP request failed with status ${HTTP_STATUS}" >&2
  echo "Response: ${RESPONSE}" >&2
  exit 1
fi

# Check for JSON-RPC error in response
if command -v jq >/dev/null 2>&1; then
  ERROR_MSG=$(echo "$RESPONSE" | jq -r '.error.message // empty' 2>/dev/null)
  if [[ -n "$ERROR_MSG" ]]; then
    echo "ERROR: Registration failed: ${ERROR_MSG}" >&2
    exit 1
  fi
else
  # Fallback: check if response contains error field
  if echo "$RESPONSE" | grep -q '"error"[[:space:]]*:[[:space:]]*{'; then
    ERROR_MSG=$(echo "$RESPONSE" | grep -oE '"message"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/"message"[[:space:]]*:[[:space:]]*"([^"]*)"/\1/')
    echo "ERROR: Registration failed: ${ERROR_MSG:-$RESPONSE}" >&2
    exit 1
  fi
fi

# Success
if [[ "$QUIET" != "1" ]]; then
  echo "Registered agent '${AGENT_NAME}' (branch: ${BRANCH}, program: ${PROGRAM})"
fi

exit 0
