#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
ARCHIVE_SCRIPT="$SCRIPT_DIR/archive_recommendations.py"

export UV_CACHE_DIR="$REPO_ROOT/.uv-cache"

exec uv run --project "$REPO_ROOT" python "$ARCHIVE_SCRIPT" "$@"
