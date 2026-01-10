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

# Check state of hooks
# We only want to exit early if:
# 1. The NEW format hook exists
# 2. AND the OLD format hook does NOT exist (so we don't leave duplicates)
HOOK_STATE=$(jq --arg cmd "$HOOK_CMD" \
  'def arr(x): if (x|type)=="array" then x else [] end;
   {
     new_exists: (arr(.hooks.SessionStart) | any(arr(.hooks)[]? | .command == $cmd)),
     legacy_exists: (arr(.hooks.SessionStart) | any(.command == $cmd))
   }' \
  "$GLOBAL_SETTINGS" 2>/dev/null)

NEW_EXISTS=$(echo "$HOOK_STATE" | jq -r .new_exists)
LEGACY_EXISTS=$(echo "$HOOK_STATE" | jq -r .legacy_exists)

if [[ "$NEW_EXISTS" == "true" && "$LEGACY_EXISTS" == "false" ]]; then
  log_step "SessionStart hook already configured correctly in $GLOBAL_SETTINGS"
  echo ""
  echo "The hook is already configured. No changes needed."
  exit 0
fi

# Backup the current settings (only if we are going to change them)
backup_file "$GLOBAL_SETTINGS"

# Use jq to add the SessionStart hook
# 1. Initialize .hooks if missing
# 2. Initialize .hooks.SessionStart if missing
# 3. Remove legacy entries/duplicates where command matches
# 4. Append new hook

log_step "Adding SessionStart hook to global settings..."

# Generate new settings content
NEW_SETTINGS=$(jq --argjson hook "$SESSION_START_HOOK" --arg cmd "$HOOK_CMD" \
  '.hooks = (.hooks // {}) |
   .hooks.SessionStart = ((.hooks.SessionStart // []) | map(select(
     # Remove legacy entries where command matches
     (.command != $cmd) and
     # Remove new entries where any hook command matches
     ((.hooks // []) | any(.command == $cmd) | not)
   )) + [$hook])' \
  "$GLOBAL_SETTINGS")

# Validate generated JSON
if ! echo "$NEW_SETTINGS" | jq empty >/dev/null 2>&1; then
  log_err "Failed to generate valid JSON. Aborting."
  exit 1
fi

# Write atomically
if echo "$NEW_SETTINGS" | write_atomic "$GLOBAL_SETTINGS"; then
  
  log_ok "Successfully added SessionStart hook to $GLOBAL_SETTINGS"
  echo "📝 Backup saved (check backup_config_files/)"
  echo ""
  echo "The hook will now run at the start of every Claude Code session."
  echo "It will auto-register an agent if the project has scripts/auto_register_agent.sh"
  echo ""
  echo "💡 Tip: Clean up old backups periodically with: rm backup_config_files/*.bak"
else
  log_err "Failed to update settings."
  exit 1
fi
