#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
EXTRACT_SCRIPT="$SCRIPT_DIR/extract_pdf.py"

export UV_CACHE_DIR="$REPO_ROOT/.uv-cache"

exec uv run --project "$REPO_ROOT" python "$EXTRACT_SCRIPT" "$@"
