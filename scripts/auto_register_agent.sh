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
# Security note: The bearer token is passed via a temporary curl config file to avoid
# exposure in process listings. Ensure temporary files are secured (this script uses mktemp).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Optionally load shared helpers; script works without lib.sh
if [[ -r "${SCRIPT_DIR}/lib.sh" ]]; then
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/lib.sh"
fi

# Load name generator for memorable agent names
if [[ -r "${SCRIPT_DIR}/lib_names.sh" ]]; then
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/lib_names.sh"
fi

# Initialize colors if lib.sh loaded
if command -v init_colors >/dev/null 2>&1; then
  init_colors
fi

# Defaults
SUFFIX=""
PROGRAM="unknown"
MODEL="unknown"
MCP_MAIL_URL="${MCP_MAIL_URL:-http://127.0.0.1:8765/mcp/}"
QUIET="${QUIET:-0}"
NONFATAL="${NONFATAL:-0}"
FORCE_RECLAIM="${FORCE_RECLAIM:-0}"

# Graceful exit for nonfatal mode (SessionStart hooks shouldn't break sessions)
graceful_exit() {
  local exit_code="${1:-1}"
  local msg="${2:-}"
  if [[ "$NONFATAL" == "1" ]]; then
    # In nonfatal mode, log to stderr but exit 0 to not break SessionStart hooks
    if [[ -n "$msg" ]] && [[ "$QUIET" != "1" ]]; then
      echo "$msg" >&2
    fi
    exit 0
  else
    if [[ -n "$msg" ]] && [[ "$QUIET" != "1" ]]; then
      echo "$msg" >&2
    fi
    exit "$exit_code"
  fi
}

# Temp file cleanup (best-effort; avoids leaks on early exit/signals)
TEMP_FILE=""
CURL_ERROR_LOG=""
CURL_CONFIG=""
cleanup_temp_files() {
  if [[ -n "${TEMP_FILE:-}" ]]; then
    rm -f "$TEMP_FILE" 2>/dev/null || true
  fi
  if [[ -n "${CURL_ERROR_LOG:-}" ]]; then
    rm -f "$CURL_ERROR_LOG" 2>/dev/null || true
  fi
  if [[ -n "${CURL_CONFIG:-}" ]]; then
    rm -f "$CURL_CONFIG" 2>/dev/null || true
  fi
}
trap cleanup_temp_files EXIT INT TERM

# Load HTTP_BEARER_TOKEN from a .env-style file
# Handles comments, whitespace, and quoted values
# Note: This logic duplicates lib.sh to ensure this script remains standalone/portable.
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
        value=$(strip_token "$value")
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
  # Trim leading/trailing whitespace
  token="${token#"${token%%[![:space:]]*}"}"
  token="${token%"${token##*[![:space:]]}"}"
  # Remove matching surrounding quotes (single or double)
  if [[ ( "${token:0:1}" == '"' && "${token: -1}" == '"' ) || \
        ( "${token:0:1}" == "'" && "${token: -1}" == "'" ) ]]; then
    token="${token:1:${#token}-2}"
  fi
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
    --nonfatal|--best-effort)
      NONFATAL=1
      shift
      ;;
    --force-reclaim)
      FORCE_RECLAIM=1
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
      echo "Usage: $0 [--suffix SUFFIX] [--program PROGRAM] [--model MODEL] [--quiet] [--nonfatal] [--force-reclaim] [--url URL]"
      echo ""
      echo "Auto-register agent with MCP Mail using git branch name."
      echo ""
      echo "Options:"
      echo "  --suffix           Suffix to add to agent name (e.g., 'c' for Codex)"
      echo "  --program          Agent program identifier (e.g., 'claude-code', 'codex-cli')"
      echo "  --model            Model identifier (e.g., 'opus', 'o3')"
      echo "  --quiet            Suppress output (both success and error messages)"
      echo "  --nonfatal         Exit 0 even on failure (for SessionStart hooks)"
      echo "  --best-effort      Alias for --nonfatal"
      echo "  --force-reclaim    Retire any existing agent with this name before registering"
      echo "  --url              MCP Mail server URL (default: http://127.0.0.1:8765/mcp)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Auto-detect program if not specified
if [[ "$PROGRAM" == "unknown" ]]; then
  if [[ -n "${CLAUDECODE:-}" ]]; then
    PROGRAM="claude-code"
  elif command -v codex >/dev/null 2>&1 && [[ "$0" =~ codex ]]; then
    PROGRAM="codex-cli"
  fi
fi

# Auto-detect model if not specified (sensible defaults based on program)
# Note: Process detection (ps aux) is best-effort and may miss if process hasn't started fully or differs in name.
if [[ "$MODEL" == "unknown" ]]; then
  case "$PROGRAM" in
    claude-code)
      # Try to detect from process args, fallback to sonnet
      if ps aux 2>/dev/null | grep -q "[c]laude.*--model opus"; then
        MODEL="opus"
      elif ps aux 2>/dev/null | grep -q "[c]laude.*--model sonnet"; then
        MODEL="sonnet"
      else
        MODEL="sonnet"  # Default for Claude Code
      fi
      ;;
    codex-cli)
      MODEL="o3"  # Default for Codex
      ;;
    *)
      MODEL="unknown"  # Keep as unknown if we can't detect
      ;;
  esac
fi

# Load bearer token from environment or .env files
# Order prioritizes ~/.mcp_mail/credentials.json per CLAUDE.md (differs from lib.sh defaults)
# Try: 1. Env var, 2. ~/.mcp_mail/credentials.json, 3. Repo .env, 4. Config .env, 5. Legacy .env
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  # Check ~/.mcp_mail/credentials.json (recommended location per CLAUDE.md)
  if [[ -f "${HOME}/.mcp_mail/credentials.json" ]] && command -v jq >/dev/null 2>&1; then
    HTTP_BEARER_TOKEN=$(jq -r '.HTTP_BEARER_TOKEN // empty' "${HOME}/.mcp_mail/credentials.json" 2>/dev/null || true)
  fi
fi
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  # Determine repo root for local .env
  REPO_ROOT="."
  if command -v git >/dev/null 2>&1; then
    REPO_ROOT=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || echo ".")
  fi
  load_token_from_file "${REPO_ROOT}/.env"
fi
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  load_token_from_file "${HOME}/.config/mcp-agent-mail/.env"
fi
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  load_token_from_file "${HOME}/mcp_agent_mail/.env"
fi

# Strip whitespace/quotes from env var (load_token_from_file already handles this for file-loaded tokens)
HTTP_BEARER_TOKEN=$(strip_token "${HTTP_BEARER_TOKEN:-}")

# Use default token if none provided (for servers without authentication)
if [[ -z "${HTTP_BEARER_TOKEN:-}" ]]; then
  if [[ "$QUIET" != "1" ]]; then
    echo "WARNING: No HTTP_BEARER_TOKEN found. Using default token 'mcp-agent-mail-default-token'." >&2
    echo "         This may fail if your server requires authentication." >&2
    echo "         Configure token in ~/.mcp_mail/credentials.json or set HTTP_BEARER_TOKEN env var." >&2
  fi
  HTTP_BEARER_TOKEN="mcp-agent-mail-default-token"
fi

# Get current git branch
get_git_branch() {
  local branch=""

  # Try active branch first
  if command -v git >/dev/null 2>&1; then
    # Use SCRIPT_DIR to ensure we are in the repo even if called from elsewhere
    branch=$(git -C "$SCRIPT_DIR" symbolic-ref --short HEAD 2>/dev/null) || true

    # Fallback for detached HEAD
    if [[ -z "$branch" ]]; then
      branch=$(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null) || true
    fi
  fi

  # Final fallback
  if [[ -z "$branch" ]] || [[ "$branch" == "HEAD" ]]; then
    branch="main"
  fi

  echo "$branch"
}

# Get project key (repo root path)
get_project_key() {
  local project_key=""
  if command -v git >/dev/null 2>&1; then
    project_key=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null) || true
  fi
  # Fallback to current directory if not in git
  if [[ -z "$project_key" ]]; then
    project_key="$(pwd)"
  fi
  echo "$project_key"
}

# Sanitize string to alphanumeric only
sanitize_alphanumeric() {
  local raw="$1"
  # Remove all non-alphanumeric characters, convert to lowercase
  echo "$raw" | tr -cd '[:alnum:]' | tr '[:upper:]' '[:lower:]'
}

# Generate short hash of project key (6 chars for uniqueness across repos)
get_project_hash() {
  local project_key="$1"
  # Use SHA256 and take first 6 chars for compact unique identifier
  if command -v sha256sum >/dev/null 2>&1; then
    echo "$project_key" | sha256sum | cut -c1-6
  elif command -v shasum >/dev/null 2>&1; then
    echo "$project_key" | shasum -a 256 | cut -c1-6
  else
    # Fallback: use last 6 chars of sanitized project path
    local sanitized
    sanitized=$(sanitize_alphanumeric "$(basename "$project_key")")
    echo "${sanitized: -6}"
  fi
}

# Main logic
BRANCH=$(get_git_branch)
PROJECT_KEY=$(get_project_key)
PROJECT_HASH=$(get_project_hash "$PROJECT_KEY")

# Generate memorable name from branch (2 words with hyphens)
MEMORABLE_NAME=""
if command -v generate_memorable_name >/dev/null 2>&1; then
  MEMORABLE_NAME=$(generate_memorable_name "$BRANCH")
else
  # Fallback if lib_names.sh not loaded
  MEMORABLE_NAME="$BRANCH"
fi

# Add suffix if provided (e.g., "c" for codex -> "auto-register-c")
if [[ -n "$SUFFIX" ]]; then
  MEMORABLE_NAME="${MEMORABLE_NAME}-${SUFFIX}"
fi

# Add project hash for cross-repo uniqueness (e.g., "auto-register-c-3f2a1b")
MEMORABLE_NAME="${MEMORABLE_NAME}-${PROJECT_HASH}"

# Agent names must be alphanumeric only - sanitize by removing hyphens
# Example: "auto-register-c-3f2a1b" -> "autoregisterc3f2a1b"
AGENT_NAME=$(sanitize_alphanumeric "$MEMORABLE_NAME")

# Validate agent name is not empty
if [[ -z "$AGENT_NAME" ]]; then
  graceful_exit 1 "ERROR: Could not derive valid agent name from branch: $BRANCH"
fi

# Validate agent name length (max 128 chars per MCP agent registration spec)
if [[ ${#AGENT_NAME} -gt 128 ]]; then
  graceful_exit 1 "ERROR: Agent name too long (${#AGENT_NAME} chars): ${AGENT_NAME:0:50}... (max 128 chars)"
fi

# Generate portable request ID with nanosecond precision if available
if date +%N | grep -q '^[0-9]'; then
  REQUEST_ID="$(date +%s%N)$$"  # Linux/GNU date
else
  REQUEST_ID="$(date +%s)$$"    # macOS/BSD date fallback
fi

# Build JSON-RPC request using jq for proper escaping
if ! command -v jq >/dev/null 2>&1; then
  graceful_exit 1 "ERROR: jq is required to build a safe JSON-RPC request payload. Install jq and retry. (https://jqlang.github.io/jq/)"
fi

JSON_PAYLOAD=$(jq -n \
  --arg id "$REQUEST_ID" \
  --arg agent "$AGENT_NAME" \
  --arg prog "$PROGRAM" \
  --arg model "$MODEL" \
  --arg branch "$BRANCH" \
  --arg project "$PROJECT_KEY" \
  --argjson force_reclaim "$([[ "$FORCE_RECLAIM" == "1" ]] && echo "true" || echo "false")" \
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
        project_key: $project,
        task_description: ("Auto-registered from branch " + $branch),
        force_reclaim: $force_reclaim
      }
    }
  }')

# Make HTTP request and capture both response and status code
# Use curl config file to avoid exposing token in ps output
TEMP_FILE=$(mktemp)
CURL_ERROR_LOG=$(mktemp)
CURL_CONFIG=$(mktemp)

# Write auth header to config file (not visible in ps)
cat > "$CURL_CONFIG" <<EOF
header = "Content-Type: application/json"
header = "Accept: application/json"
header = "Authorization: Bearer ${HTTP_BEARER_TOKEN}"
EOF

HTTP_STATUS=$(curl -sS --connect-timeout 5 --max-time 30 \
  -w '%{http_code}' \
  -o "$TEMP_FILE" \
  -X POST \
  --config "$CURL_CONFIG" \
  -d "$JSON_PAYLOAD" \
  "${MCP_MAIL_URL}" 2>"$CURL_ERROR_LOG") || {
  msg="ERROR: Failed to connect to MCP Mail server at ${MCP_MAIL_URL}"
  if [[ -s "$CURL_ERROR_LOG" ]]; then
    curl_err=$(cat "$CURL_ERROR_LOG")
    msg="$msg"$'\n'"curl error: $curl_err"
  fi
  graceful_exit 1 "$msg"
}

# Clean up curl config file immediately after use
rm -f "$CURL_CONFIG"

RESPONSE=$(cat "$TEMP_FILE")

# Check HTTP status code
if [[ ! "$HTTP_STATUS" =~ ^2[0-9][0-9]$ ]]; then
  msg="ERROR: HTTP request failed with status $HTTP_STATUS"
  if [[ -n "$RESPONSE" ]]; then
    msg="$msg"$'\n'"Response: $RESPONSE"
  fi
  graceful_exit 1 "$msg"
fi

# Parse JSON-RPC response and validate success (jq is required)
ERROR_MSG=$(echo "$RESPONSE" | jq -r '.error.message // empty' 2>&1) || true
if [[ -n "$ERROR_MSG" ]] && [[ ! "$ERROR_MSG" =~ "parse error" ]]; then
  graceful_exit 1 "ERROR: Registration failed: $ERROR_MSG"
fi

	# Note: FastMCP puts the tool result in 'structuredContent', not directly in 'result'
	if ! echo "$RESPONSE" | jq -e --arg req_id "$REQUEST_ID" --arg agent "$AGENT_NAME" '
	  .jsonrpc == "2.0"
	  and .id == $req_id
	  and (.error | not)
	  and (.result | type == "object")
	  and (
	    # Handle both direct result format and structuredContent format
	    ((.result.name | type == "string") and (.result.name == $agent))
	    or ((.result.structuredContent.name | type == "string") and (.result.structuredContent.name == $agent))
	  )
	' >/dev/null; then
	  graceful_exit 1 "ERROR: Registration response did not validate as a successful register_agent call."$'\n'"Response: $RESPONSE"
	fi

# Success
if [[ "$QUIET" != "1" ]]; then
  # Display memorable name with hyphens and sanitized agent name
  echo "🤖 Agent registered: ${MEMORABLE_NAME}"
  echo "   Agent ID: ${AGENT_NAME}"
  echo "   Branch: ${BRANCH}, Program: ${PROGRAM}, Model: ${MODEL}"
fi

exit 0
