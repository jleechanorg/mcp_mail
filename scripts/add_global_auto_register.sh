#!/usr/bin/env bash
# Add auto-registration SessionStart hook to global Claude Code settings
set -euo pipefail

# Check for jq dependency
if ! command -v jq &> /dev/null; then
  echo "❌ Error: jq is required but not installed."
  echo "Install with: brew install jq (macOS) or apt-get install jq (Linux)"
  exit 1
fi

GLOBAL_SETTINGS="$HOME/.claude/settings.json"
BACKUP_SETTINGS="$HOME/.claude/settings.json.backup.$(date +%Y%m%d_%H%M%S)"

# Check if global settings file exists
if [[ ! -f "$GLOBAL_SETTINGS" ]]; then
  echo "Error: Global settings file not found at $GLOBAL_SETTINGS"
  exit 1
fi

# Backup the current settings
echo "Creating backup at $BACKUP_SETTINGS"
cp "$GLOBAL_SETTINGS" "$BACKUP_SETTINGS"

# Create the SessionStart hook entry with correct format (matcher-based with hooks array)
SESSION_START_HOOK='{
  "hooks": [
    {
      "type": "command",
      "command": "bash -lc '\''repo_root=\"$(git rev-parse --show-toplevel 2>/dev/null || pwd)\"; if [[ -f \"$repo_root/scripts/auto_register_agent.sh\" ]]; then \"$repo_root/scripts/auto_register_agent.sh\" --program claude-code --model sonnet --nonfatal --force-reclaim; fi'\''"
    }
  ]
}'

# Check if hook already exists (check for command string in any hook entry)
HOOK_CMD='bash -lc '\''repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"; if [[ -f "$repo_root/scripts/auto_register_agent.sh" ]]; then "$repo_root/scripts/auto_register_agent.sh" --program claude-code --model sonnet --nonfatal --force-reclaim; fi'\'''
HOOK_EXISTS=$(jq --arg cmd "$HOOK_CMD" \
  '(.hooks.SessionStart // []) | any(.hooks[]?.command == $cmd)' \
  "$GLOBAL_SETTINGS" 2>/dev/null || echo "false")

if [[ "$HOOK_EXISTS" == "true" ]]; then
  echo "ℹ️  SessionStart hook already exists in $GLOBAL_SETTINGS"
  echo "📝 Backup saved at $BACKUP_SETTINGS (not modified)"
  echo ""
  echo "The hook is already configured. No changes needed."
  exit 0
fi

# Use jq to add the SessionStart hook (initialize array if needed, remove legacy entries, then append)
echo "Adding SessionStart hook to global settings..."
jq --argjson hook "$SESSION_START_HOOK" --arg cmd "$HOOK_CMD" \
  '.hooks.SessionStart = ((.hooks.SessionStart // []) | map(select(.command != $cmd)) + [$hook])' \
  "$GLOBAL_SETTINGS" > "$GLOBAL_SETTINGS.tmp"

# Validate the JSON is still valid
if jq empty "$GLOBAL_SETTINGS.tmp" 2>/dev/null; then
  mv "$GLOBAL_SETTINGS.tmp" "$GLOBAL_SETTINGS"
  echo "✅ Successfully added SessionStart hook to $GLOBAL_SETTINGS"
  echo "📝 Backup saved at $BACKUP_SETTINGS"
  echo ""
  echo "The hook will now run at the start of every Claude Code session."
  echo "It will auto-register an agent if the project has scripts/auto_register_agent.sh"
  echo ""
  echo "💡 Tip: Clean up old backups periodically with: rm ~/.claude/settings.json.backup.*"
else
  echo "❌ Error: Generated invalid JSON. Restoring from backup..."
  mv "$BACKUP_SETTINGS" "$GLOBAL_SETTINGS"
  rm -f "$GLOBAL_SETTINGS.tmp"
  exit 1
fi
