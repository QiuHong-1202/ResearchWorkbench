#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
FETCH_SCRIPT="$SCRIPT_DIR/fetch_arxiv.py"

export UV_CACHE_DIR="$REPO_ROOT/.uv-cache"

exec uv run --project "$REPO_ROOT" python "$FETCH_SCRIPT" "$@"
