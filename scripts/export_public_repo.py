from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "public-export.json"


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def has_glob_magic(pattern: str) -> bool:
    return any(token in pattern for token in "*?[")


def normalize_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def expand_pattern(root: Path, pattern: str) -> set[Path]:
    matches: set[Path] = set()

    if has_glob_magic(pattern):
        for raw_match in glob.glob(str(root / pattern), recursive=True):
            match = Path(raw_match)
            if match.is_file():
                matches.add(match.resolve())
        return matches

    candidate = (root / pattern).resolve()
    if not candidate.exists():
        return matches

    if candidate.is_file():
        matches.add(candidate)
        return matches

    for file_path in candidate.rglob("*"):
        if file_path.is_file():
            matches.add(file_path.resolve())
    return matches


def expand_patterns(root: Path, patterns: list[str]) -> list[Path]:
    files: set[Path] = set()
    for pattern in patterns:
        files.update(expand_pattern(root, pattern))
    return sorted(files, key=lambda item: normalize_rel(item, root))


def matches_any(path_str: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path_str, pattern) for pattern in patterns)


def get_tracked_files(root: Path) -> list[str]:
    command = ["git", "ls-files", "-z"]
    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=False,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())

    raw_items = [item for item in result.stdout.split(b"\x00") if item]
    tracked = [item.decode("utf-8", errors="replace").replace("\\", "/") for item in raw_items]
    return sorted(tracked)


def build_export_set(root: Path, config: dict) -> list[Path]:
    include_patterns = config.get("include", [])
    exclude_patterns = config.get("exclude", [])

    exported: list[Path] = []
    for file_path in expand_patterns(root, include_patterns):
        rel_path = normalize_rel(file_path, root)
        if matches_any(rel_path, exclude_patterns):
            continue
        exported.append(file_path)
    return exported


def audit_tracked_files(root: Path, config: dict) -> list[str]:
    audit_patterns = config.get("audit_tracked", [])
    if not audit_patterns:
        return []

    tracked = get_tracked_files(root)
    return [path for path in tracked if matches_any(path, audit_patterns)]


def copy_export(root: Path, files: list[Path], out_dir: Path, verbose: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    for file_path in files:
        rel_path = file_path.relative_to(root)
        target_path = out_dir / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target_path)
        if verbose:
            print(f"COPY {rel_path.as_posix()}")


def print_summary(files: list[Path], root: Path, audited: list[str]) -> None:
    print(f"Export file count: {len(files)}")
    for file_path in files:
        print(f"  {normalize_rel(file_path, root)}")

    if audited:
        print("\nTracked paths that match audit rules:")
        for item in audited:
            print(f"  {item}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a conservative public mirror from the private workspace.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to the export config JSON.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Destination directory for the public mirror.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the export plan without copying files.",
    )
    parser.add_argument(
        "--fail-on-audit",
        action="store_true",
        help="Exit with code 2 if tracked files match audit rules.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each copied file during export.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()

    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 1

    config = load_config(config_path)
    exported = build_export_set(ROOT, config)
    audited = audit_tracked_files(ROOT, config)

    print_summary(exported, ROOT, audited)

    if args.fail_on_audit and audited:
        return 2

    if args.dry_run or args.out_dir is None:
        return 0

    out_dir = args.out_dir.resolve()
    copy_export(ROOT, exported, out_dir, args.verbose)
    print(f"\nCopied export to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
