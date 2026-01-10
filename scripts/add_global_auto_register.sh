#!/usr/bin/env bash
# Add auto-registration SessionStart hook to global Claude Code settings
set -euo pipefail

# Source library functions
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$REPO_ROOT/scripts/lib.sh" ]]; then
  # shellcheck source=scripts/lib.sh
  . "$REPO_ROOT/scripts/lib.sh"
else
  echo "Error: scripts/lib.sh not found"
  exit 1
fi

init_colors
parse_common_flags "$@"


# Check for jq dependency
require_cmd jq

GLOBAL_SETTINGS="$HOME/.claude/settings.json"
BACKUP_SETTINGS="$HOME/.claude/settings.json.backup.$(date +%Y%m%d_%H%M%S)"

# Check if global settings file exists
if [[ ! -f "$GLOBAL_SETTINGS" ]]; then
  log_err "Global settings file not found at $GLOBAL_SETTINGS"
  exit 1
fi

# Validate existing JSON
if ! json_validate "$GLOBAL_SETTINGS"; then
  exit 1
fi

# Create the SessionStart hook entry (wrapped in "hooks" array)
# NOTE: The command uses escaped quotes inside to match JSON format in settings.json
SESSION_START_HOOK='{
  "matcher": {},
  "hooks": [
    {
      "type": "command",
      "command": "bash -lc '\''repo_root=\"$(git rev-parse --show-toplevel 2>/dev/null || pwd)\"; if [[ -f \"$repo_root/scripts/auto_register_agent.sh\" ]]; then \"$repo_root/scripts/auto_register_agent.sh\" --program claude-code --model sonnet --nonfatal --force-reclaim; fi'\''"
    }
  ]
}'

# Command string for duplicate detection (must match the JSON-decoded string in settings.json)
HOOK_CMD='bash -lc '\''repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"; if [[ -f "$repo_root/scripts/auto_register_agent.sh" ]]; then "$repo_root/scripts/auto_register_agent.sh" --program claude-code --model sonnet --nonfatal --force-reclaim; fi'\'''

# Check if hook already exists
# Use type-safe check: ensure arrays are arrays, handle nulls
HOOK_EXISTS=$(jq --arg cmd "$HOOK_CMD" \
  'def arr(x): if (x|type)=="array" then x else [] end;
   arr(.hooks.SessionStart) | any(arr(.hooks)[]? | .command == $cmd)' \
  "$GLOBAL_SETTINGS" 2>/dev/null || echo "false")

if [[ "$HOOK_EXISTS" == "true" ]]; then
  log_step "SessionStart hook already exists in $GLOBAL_SETTINGS"
  echo ""
  echo "The hook is already configured. No changes needed."
  exit 0
fi

# Backup the current settings (only if we are going to change them)
log_step "Creating backup at $BACKUP_SETTINGS"
cp "$GLOBAL_SETTINGS" "$BACKUP_SETTINGS"

# Use jq to add the SessionStart hook
# 1. Initialize .hooks if missing
# 2. Initialize .hooks.SessionStart if missing
# 3. Remove legacy entries/duplicates where command matches
# 4. Append new hook

log_step "Adding SessionStart hook to global settings..."

if jq --argjson hook "$SESSION_START_HOOK" --arg cmd "$HOOK_CMD" \
  '.hooks = (.hooks // {}) |
   .hooks.SessionStart = ((.hooks.SessionStart // []) | map(select(
     # Remove legacy entries where command matches
     (.command != $cmd) and
     # Remove new entries where any hook command matches
     ((.hooks // []) | any(.command == $cmd) | not)
   )) + [$hook])' \
  "$GLOBAL_SETTINGS" | write_atomic "$GLOBAL_SETTINGS"; then
  
  log_ok "Successfully added SessionStart hook to $GLOBAL_SETTINGS"
  echo "📝 Backup saved at $BACKUP_SETTINGS"
  echo ""
  echo "The hook will now run at the start of every Claude Code session."
  echo "It will auto-register an agent if the project has scripts/auto_register_agent.sh"
  echo ""
  echo "💡 Tip: Clean up old backups periodically with: rm ~/.claude/settings.json.backup.*"
else
  log_err "Failed to update settings. Restoring from backup..."
  cp "$BACKUP_SETTINGS" "$GLOBAL_SETTINGS"
  exit 1
fi
