#!/bin/bash
# Command Runner for claude-commands submodule
# Usage: ./run-claude-command.sh <command-name> [args...]
#
# This script provides access to slash commands from the claude-commands submodule
# when the SlashCommand tool doesn't dynamically discover them.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <command-name> [args...]"
    echo ""
    echo "Available commands:"
    echo "  From submodule (claude-commands/.claude/commands/):"
    find claude-commands/.claude/commands -maxdepth 1 -type f -name "*.md" -print0 2>/dev/null | \
        sort -z | xargs -0 -n1 basename -s .md | sed 's/^/    /' || true
    exit 1
fi

COMMAND_NAME="$1"
shift
COMMAND_ARGS=("$@")

# Look for command in submodule
COMMAND_FILE="claude-commands/.claude/commands/${COMMAND_NAME}.md"

if [ ! -f "${COMMAND_FILE}" ]; then
    echo "❌ Command not found: ${COMMAND_NAME}"
    echo ""
    echo "Available commands:"
    find claude-commands/.claude/commands -maxdepth 1 -type f -name "*.md" -print0 2>/dev/null | \
        sort -z | xargs -0 -n1 basename -s .md | sed 's/^/  /' || true
    exit 1
fi

echo "📋 Running command: ${COMMAND_NAME}"
echo "📄 Command file: ${COMMAND_FILE}"
echo ""

# Display the command description
echo "Description:"
grep "^description:" "${COMMAND_FILE}" | sed 's/description: /  /' || echo "  (no description available)"
echo ""

# Check if it's a script-based command (has Python script)
COMMAND_SCRIPT="claude-commands/.claude/commands/${COMMAND_NAME}.py"

if [ -f "${COMMAND_SCRIPT}" ]; then
    echo "🐍 Executing Python script: ${COMMAND_SCRIPT}"
    python3 "${COMMAND_SCRIPT}" "${COMMAND_ARGS[@]}"
else
    echo "📖 This is a prompt-based command."
    echo "📄 Read the full command with: cat ${COMMAND_FILE}"
    echo ""
    echo "Command preview:"
    echo "----------------------------------------"
    head -50 "${COMMAND_FILE}"
    echo "----------------------------------------"
    echo ""
    echo "💡 For full command details: cat ${COMMAND_FILE}"
fi
