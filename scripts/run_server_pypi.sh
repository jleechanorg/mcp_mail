#!/usr/bin/env bash
set -euo pipefail

# This script runs the MCP Agent Mail server using the PyPI package
# instead of local development code

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source shared library functions
source "$SCRIPT_DIR/lib.sh"

echo "🔄 Installing mcp_mail from PyPI..."

# Create a temporary directory for the isolated installation
TEMP_ENV=$(mktemp -d -t mcp_mail-XXXXXX)
trap 'rm -rf "$TEMP_ENV"' EXIT

# Find Python 3.11+ (prefer the default python3 if it meets the requirement)
PYTHON_BIN=""
MIN_VERSION=311  # e.g. 3.11 -> 311, 3.12 -> 312

if command -v python3 >/dev/null 2>&1; then
  PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor:02d}")')
  if [[ "$PY_VER" -ge "$MIN_VERSION" ]]; then
    PYTHON_BIN=$(command -v python3)
  fi
fi

if [[ -z "$PYTHON_BIN" ]]; then
  for py in python3.15 python3.14 python3.13 python3.12 python3.11; do
    if command -v "$py" >/dev/null 2>&1; then
      PYTHON_BIN=$(command -v "$py")
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "❌ Error: Python 3.11 or higher is required"
  exit 1
fi

echo "Using Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

# Check if uv is available
if ! command -v uv >/dev/null 2>&1; then
  echo "❌ Error: uv is required but not installed"
  echo "Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# Install the package from PyPI using uv
# Note: We install in a temp dir but DON'T change working directory
# so the server's SQLite DB and archive persist across restarts
uv venv "$TEMP_ENV/.venv" --python "$PYTHON_BIN"
source "$TEMP_ENV/.venv/bin/activate"

uv pip install mcp_mail

echo "✅ Installed mcp_mail from PyPI"

# Load or generate HTTP_BEARER_TOKEN
load_or_generate_token "$PYTHON_BIN"

echo "🚀 Starting MCP Mail server from PyPI package..."
python -m mcp_agent_mail.cli serve-http "$@"
