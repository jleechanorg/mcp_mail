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
#
# Security note: The bearer token will be visible in process listings during curl execution.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Optionally load shared helpers; script works without lib.sh
if [[ -r "${SCRIPT_DIR}/lib.sh" ]]; then
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/lib.sh" || true
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

# Load HTTP_BEARER_TOKEN from a .env-style file
# Handles comments, whitespace, and quoted values
load_token_from_file() {
  local file="$1"
  local line value

  [[ -f "$file" ]] || return 0

  while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip empty lines and comments
    case "$line" in
      ''|'#'*) continue ;;
      HTTP_BEARER_TOKEN=*)
        value="${line#HTTP_BEARER_TOKEN=}"
        # Trim leading/trailing whitespace
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        # Remove matching surrounding quotes (single or double)
        if [[ ( "${value:0:1}" == '"' && "${value: -1}" == '"' ) || \
              ( "${value:0:1}" == "'" && "${value: -1}" == "'" ) ]]; then
          value="${value:1:${#value}-2}"
        fi
        if [[ -n "$value" ]]; then
          HTTP_BEARER_TOKEN="$value"
        fi
        break
        ;;
    esac
  done < "$file"
}

# Strip whitespace and quotes from token (for env var fallback)
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

# Parse arguments with validation
while [[ $# -gt 0 ]]; do
  case "$1" in
    --suffix)
      if [[ $# -lt 2 || "$2" == --* ]]; then
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
      if [[ $# -lt 2 || "$2" == --* ]]; then
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
      if [[ $# -lt 2 || "$2" == --* ]]; then
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
      if [[ $# -lt 2 || "$2" == --* ]]; then
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

# Load bearer token from environment or .env files
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  load_token_from_file ".env"
fi
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  load_token_from_file "${HOME}/.config/mcp-agent-mail/.env"
fi

# Strip whitespace/quotes from env var (load_token_from_file already handles this for file-loaded tokens)
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

# Generate portable request ID (macOS date doesn't support %N)
REQUEST_ID="$(date +%s)$$"

# Build JSON-RPC request using jq for proper escaping if available
if command -v jq >/dev/null 2>&1; then
  JSON_PAYLOAD=$(jq -n \
    --arg id "$REQUEST_ID" \
    --arg agent "$AGENT_NAME" \
    --arg prog "$PROGRAM" \
    --arg model "$MODEL" \
    --arg branch "$BRANCH" \
    '{
      jsonrpc: "2.0",
      id: $id,
      method: "tools/call",
      params: {
        name: "register_agent",
        arguments: {
          name: $agent,
          program: $prog,
          model: $model,
          task_description: ("Auto-registered from branch " + $branch)
        }
      }
    }')
else
  # Fallback: construct JSON directly (agent name is already sanitized to alphanumeric)
  # PROGRAM and MODEL should be safe values; BRANCH is only used in description
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
      "task_description": "Auto-registered from branch ${AGENT_BASE}"
    }
  }
}
EOF
)
fi

# Make HTTP request and capture both response and status code
TEMP_FILE=$(mktemp)
trap 'rm -f "$TEMP_FILE"' EXIT

HTTP_STATUS=$(curl -sS --connect-timeout 5 --max-time 30 \
  -w '%{http_code}' \
  -o "$TEMP_FILE" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${HTTP_BEARER_TOKEN}" \
  -d "$JSON_PAYLOAD" \
  "${MCP_MAIL_URL}" 2>&1) || {
  CURL_ERROR="$HTTP_STATUS"
  echo "ERROR: Failed to connect to MCP Mail server at ${MCP_MAIL_URL}" >&2
  if [[ -n "${CURL_ERROR:-}" ]]; then
    echo "curl error: $CURL_ERROR" >&2
  fi
  exit 1
}

RESPONSE=$(cat "$TEMP_FILE")

# Check HTTP status code
if [[ ! "$HTTP_STATUS" =~ ^2[0-9][0-9]$ ]]; then
  echo "ERROR: HTTP request failed with status $HTTP_STATUS" >&2
  if [[ -n "$RESPONSE" ]]; then
    echo "Response: $RESPONSE" >&2
  fi
  exit 1
fi

# Check for JSON-RPC error in response
# Use jq if available for robust parsing, otherwise fallback to grep
if command -v jq >/dev/null 2>&1; then
  ERROR_MSG=$(echo "$RESPONSE" | jq -r '.error.message // empty' 2>/dev/null)
  if [[ -n "$ERROR_MSG" ]]; then
    echo "ERROR: Registration failed: $ERROR_MSG" >&2
    exit 1
  fi
else
  # Fallback: check for top-level "error" field (JSON-RPC spec)
  # This pattern matches "error": { at the top level
  if echo "$RESPONSE" | grep -qE '"error"\s*:\s*\{'; then
    ERROR_MSG=$(echo "$RESPONSE" | grep -oE '"message"\s*:\s*"[^"]*"' | head -1 | sed 's/"message"\s*:\s*"\([^"]*\)"/\1/')
    echo "ERROR: Registration failed: ${ERROR_MSG:-unknown error}" >&2
    exit 1
  fi
fi

# Success
if [[ "$QUIET" != "1" ]]; then
  echo "Registered agent '${AGENT_NAME}' (branch: ${BRANCH}, program: ${PROGRAM})"
fi

exit 0
