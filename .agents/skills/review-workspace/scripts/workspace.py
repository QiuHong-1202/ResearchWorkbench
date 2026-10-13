"""Resolve the machine-local review workspace without creating directories."""
import json
import sys
from pathlib import Path


def resolve_workspace(config_path: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    value = config.get("REVIEW_WORKSPACE")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("REVIEW_WORKSPACE must be a non-empty absolute path")
    workspace = Path(value).expanduser()
    if not workspace.is_absolute():
        raise ValueError("REVIEW_WORKSPACE must be absolute on this operating system")
    if not workspace.is_dir():
        raise ValueError(f"Review workspace does not exist: {workspace}")
    return workspace.resolve()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    config_path = Path(__file__).resolve().parents[1] / "workspace.local.json"
    try:
        print(resolve_workspace(config_path))
    except (OSError, ValueError, AttributeError) as exc:
        print(f"Configure {config_path}: {exc}", file=sys.stderr)
        sys.exit(1)
