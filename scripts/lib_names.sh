#!/usr/bin/env bash
# Branch-based memorable name generator for agent identification
# Derives short, memorable names from git branch names

# Generate memorable name from branch name
# Usage: generate_memorable_name <branch_name>
# Examples:
#   "claude/auto-register-codex-agent-qIAvB" -> "auto-register"
#   "feature/user-authentication" -> "user-authentication"
#   "fix/login-bug-123" -> "login-bug"
#   "main" -> "main"
generate_memorable_name() {
  local branch="${1:-}"

  if [[ -z "$branch" ]]; then
    echo "unknown"
    return 1
  fi

  # Remove common prefixes
  local name="$branch"
  name="${name#feature/}"
  name="${name#fix/}"
  name="${name#bugfix/}"
  name="${name#hotfix/}"
  name="${name#chore/}"
  name="${name#docs/}"
  name="${name#test/}"
  name="${name#claude/}"
  name="${name#codex/}"
  name="${name#cursor/}"
  name="${name#gemini/}"

  # Remove trailing random suffixes (e.g., -qIAvB, -ABC123, -xyz789)
  # Pattern: hyphen followed by 4-6 alphanumeric chars at end
  name=$(echo "$name" | sed -E 's/-[a-zA-Z0-9]{4,6}$//')

  # Convert to lowercase and replace slashes/underscores with hyphens
  name=$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr '/_' '--')

  # Take first 2 words (separated by hyphens) for brevity
  # This handles cases like "auto-register-codex-agent-handler" -> "auto-register"
  local words=(${name//-/ })
  if [[ ${#words[@]} -gt 2 ]]; then
    name="${words[0]}-${words[1]}"
  fi

  # Limit overall length to 40 chars (still readable)
  if [[ ${#name} -gt 40 ]]; then
    name="${name:0:40}"
    # Trim trailing hyphen if we cut mid-word
    name="${name%-}"
  fi

  echo "$name"
}

# Export function for use in other scripts
export -f generate_memorable_name 2>/dev/null || true
