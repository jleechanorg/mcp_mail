#!/usr/bin/env bash
# Add auto-registration SessionStart hook to global Claude Code settings
set -euo pipefail

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

# Create the SessionStart hook entry
SESSION_START_HOOK='{
  "hooks": [
    {
      "type": "command",
      "command": "bash -lc '\''repo_root=\"$(git rev-parse --show-toplevel 2>/dev/null || pwd)\"; if [[ -f \"$repo_root/scripts/auto_register_agent.sh\" ]]; then \"$repo_root/scripts/auto_register_agent.sh\" --program claude-code --model sonnet --nonfatal --force-reclaim; fi'\''"
    }
  ]
}'

# Use jq to add the SessionStart hook
echo "Adding SessionStart hook to global settings..."
jq --argjson hook "$SESSION_START_HOOK" \
  '.hooks.SessionStart += [$hook]' \
  "$GLOBAL_SETTINGS" > "$GLOBAL_SETTINGS.tmp"

# Validate the JSON is still valid
if jq empty "$GLOBAL_SETTINGS.tmp" 2>/dev/null; then
  mv "$GLOBAL_SETTINGS.tmp" "$GLOBAL_SETTINGS"
  echo "✅ Successfully added SessionStart hook to $GLOBAL_SETTINGS"
  echo "📝 Backup saved at $BACKUP_SETTINGS"
  echo ""
  echo "The hook will now run at the start of every Claude Code session."
  echo "It will auto-register an agent if the project has scripts/auto_register_agent.sh"
else
  echo "❌ Error: Generated invalid JSON. Restoring from backup..."
  mv "$BACKUP_SETTINGS" "$GLOBAL_SETTINGS"
  rm -f "$GLOBAL_SETTINGS.tmp"
  exit 1
fi
