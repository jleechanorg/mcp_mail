#!/usr/bin/env bash
set -euo pipefail

# Add auto-registration SessionStart hook to global Claude Code settings

# Source shared helpers (colorized logging, dependency checks)
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -f "${ROOT_DIR}/scripts/lib.sh" ]]; then
  # shellcheck disable=SC1090,SC1091
  . "${ROOT_DIR}/scripts/lib.sh"
else
  echo "FATAL: scripts/lib.sh not found at ${ROOT_DIR}/scripts/lib.sh" >&2
  exit 1
fi
init_colors
setup_traps

require_cmd jq

GLOBAL_SETTINGS="${HOME}/.claude/settings.json"
TMP_SETTINGS="${GLOBAL_SETTINGS}.tmp.$$.$(date +%s_%N)"
BACKUP_SETTINGS=""

# shellcheck disable=SC2329
cleanup_restore() {
  local exit_code=$?
  if [[ $exit_code -ne 0 ]]; then
    if [[ -n "${BACKUP_SETTINGS}" && -f "${BACKUP_SETTINGS}" ]]; then
      log_warn "Restoring ${GLOBAL_SETTINGS} from backup: ${BACKUP_SETTINGS}"
      cp -p "${BACKUP_SETTINGS}" "${GLOBAL_SETTINGS}" 2>/dev/null || true
    fi
    rm -f "${TMP_SETTINGS}" 2>/dev/null || true
  fi
}
trap cleanup_restore EXIT INT TERM

# Check if global settings file exists
if [[ ! -f "$GLOBAL_SETTINGS" ]]; then
  log_err "❌ Error: Global settings file not found at ${GLOBAL_SETTINGS}"
  exit 1
fi

# Refuse to modify invalid JSON
if ! jq empty "$GLOBAL_SETTINGS" >/dev/null 2>&1; then
  log_err "❌ Error: Invalid JSON in ${GLOBAL_SETTINGS}. Refusing to modify."
  exit 1
fi

# Build the exact command we want to run at SessionStart.
# Note: Use bash -c (not -l) to avoid sourcing user profile files.
# shellcheck disable=SC2016
AUTO_REGISTER_SNIPPET='repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"; if [[ -f "$repo_root/scripts/auto_register_agent.sh" ]]; then "$repo_root/scripts/auto_register_agent.sh" --program claude-code --model sonnet --nonfatal --force-reclaim; fi'
SESSION_START_COMMAND=$(jq -nr --arg snippet "$AUTO_REGISTER_SNIPPET" '$snippet | @sh | "bash -c " + .')

# Canonicalize original JSON so we can detect no-op runs without creating backups.
ORIGINAL_CANONICAL=$(jq -cS . "$GLOBAL_SETTINGS")

# Produce updated settings in a temp file:
# - Ensure .hooks and .hooks.SessionStart exist
# - Normalize older/incorrect SessionStart shapes into the correct matcher+hooks form
# - Add our hook only if it isn't already present (idempotent)
umask 077
jq --arg cmd "$SESSION_START_COMMAND" '
  .hooks = (if (.hooks | type) == "object" then .hooks else {} end)
  | .hooks.SessionStart = (if (.hooks.SessionStart | type) == "array" then .hooks.SessionStart else [] end)
  | .hooks.SessionStart |= map(
      if (type == "object" and (.hooks | type) == "array") then
        .
      elif (type == "object" and has("type") and has("command")) then
        { "matcher": {}, "hooks": [ { "type": .type, "command": .command } ] }
      else
        .
      end
    )
  | if (
      (.hooks.SessionStart // [])
      | map(.hooks // []) | flatten
      | any(.type == "command" and .command == $cmd)
    ) then
      .
    else
      .hooks.SessionStart += [ { "matcher": {}, "hooks": [ { "type": "command", "command": $cmd } ] } ]
    end
' "$GLOBAL_SETTINGS" > "$TMP_SETTINGS"

UPDATED_CANONICAL=$(jq -cS . "$TMP_SETTINGS")
if [[ "$ORIGINAL_CANONICAL" == "$UPDATED_CANONICAL" ]]; then
  log_ok "ℹ️  SessionStart auto-register hook already configured. No changes needed."
  rm -f "$TMP_SETTINGS" 2>/dev/null || true
  trap - EXIT INT TERM
  exit 0
fi

# Backup the current settings (only when we know we're going to write a change)
BACKUP_SETTINGS="${GLOBAL_SETTINGS}.backup.$(date +%Y%m%d_%H%M%S)"
cp -p "$GLOBAL_SETTINGS" "$BACKUP_SETTINGS"
log_ok "📝 Backup saved at ${BACKUP_SETTINGS}"

# Validate and apply
if jq empty "$TMP_SETTINGS" >/dev/null 2>&1; then
  if mv "$TMP_SETTINGS" "$GLOBAL_SETTINGS"; then
    trap - EXIT INT TERM
    log_ok "✅ Successfully updated ${GLOBAL_SETTINGS}"
    echo
    echo "The hook will run at the start of every Claude Code session."
    echo "It will auto-register an agent if the project has scripts/auto_register_agent.sh"
    echo
    log_ok "Installed SessionStart command:"
    echo "  ${SESSION_START_COMMAND}"
    exit 0
  fi
  log_err "❌ Error: Failed to write updated settings to ${GLOBAL_SETTINGS}"
else
  log_err "❌ Error: Generated invalid JSON. Aborting."
fi

exit 1
