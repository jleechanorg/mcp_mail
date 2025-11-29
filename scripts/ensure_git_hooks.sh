#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

current=$(git config --get core.hooksPath || true)
if [ "$current" != ".githooks" ]; then
  git config core.hooksPath .githooks
  echo "Set core.hooksPath to .githooks"
else
  echo "core.hooksPath already set to .githooks"
fi
