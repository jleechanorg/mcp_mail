#!/usr/bin/env bash
set -euo pipefail

# Publish the current project to PyPI using uv.
# Requires PYPI_TOKEN (and optionally PYPI_INDEX_URL) to be set in the environment.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ uv is required (install from https://astral.sh/uv/)" >&2
  exit 1
fi

PYPI_TOKEN="${PYPI_TOKEN:-}"
if [[ -z "$PYPI_TOKEN" ]]; then
  echo "❌ PYPI_TOKEN is not set; export it before running (token lives in bashrc per repo instructions)." >&2
  exit 1
fi

INDEX_URL="${PYPI_INDEX_URL:-}"
CHECK_URL="${PYPI_CHECK_URL:-https://pypi.org/simple}"

echo "🏗️  Building distributions with uv..."
uv build

if [[ -n "$INDEX_URL" ]]; then
  echo "🚀 Publishing to ${INDEX_URL}..."
  uv publish --token "$PYPI_TOKEN" --index "$INDEX_URL"
else
  echo "🚀 Publishing to PyPI (default index) with pre-check at ${CHECK_URL}..."
  uv publish --token "$PYPI_TOKEN" --check-url "$CHECK_URL"
fi

echo "✅ Publish step finished (skip-existing enabled)."
