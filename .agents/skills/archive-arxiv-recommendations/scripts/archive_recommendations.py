#!/usr/bin/env python3
"""Archive past-month arXiv recommendation files without staging or committing."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

FILENAME_RE = re.compile(r"^(\d{4}-\d{2})-\d{2}-arxiv-recommended\.md$")


def configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[4]


def load_recommendations_root(config_path: Path, repo_root: Path) -> Path:
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")

    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("recommendations_root:"):
            value = stripped.split(":", 1)[1].strip()
            if not value:
                break
            root = Path(value)
            return root if root.is_absolute() else repo_root / root

    raise ValueError(f"recommendations_root not found in {config_path}")


def move_file(src: Path, dest: Path, repo_root: Path, dry_run: bool) -> None:
    if dest.exists():
        raise FileExistsError(f"Destination already exists: {dest}")

    rel_dest = dest.relative_to(repo_root).as_posix()
    if dry_run:
        print(f"[dry-run] move {src.name} -> {rel_dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    print(f"Moved {src.name} -> {rel_dest}")


def main() -> int:
    configure_stdio()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=".agents/skills/arxiv-daily/config.yaml",
        help="Path to arxiv-daily config.yaml (relative to repo root unless absolute)",
    )
    parser.add_argument(
        "--month",
        help="Treat this YYYY-MM as the current month (default: UTC today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without moving files",
    )
    args = parser.parse_args()

    repo_root = repo_root_from_script()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo_root / config_path

    recommendations_root = load_recommendations_root(config_path, repo_root)
    archive_root = recommendations_root / "archive"
    current_month = args.month or datetime.now(timezone.utc).strftime("%Y-%m")

    if not recommendations_root.is_dir():
        raise FileNotFoundError(
            f"Recommendations root not found: {recommendations_root}"
        )

    moves: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(recommendations_root.glob("*-arxiv-recommended.md")):
        match = FILENAME_RE.match(path.name)
        if not match:
            print(f"Skipping unrecognized filename: {path.name}", file=sys.stderr)
            continue
        month = match.group(1)
        if month == current_month:
            continue
        moves[month].append(path)

    if not moves:
        print(f"Nothing to archive. Current month kept in place: {current_month}")
        return 0

    total = sum(len(paths) for paths in moves.values())
    rel_root = recommendations_root.relative_to(repo_root).as_posix()
    print(f"Archiving {total} file(s); keeping {current_month} in {rel_root}/")

    for month in sorted(moves):
        dest_dir = archive_root / month
        for src in moves[month]:
            dest = dest_dir / src.name
            move_file(src, dest, repo_root, args.dry_run)

    if args.dry_run:
        print("Dry run only; no files moved and no git commands run.")
    else:
        print("No git staging or commit was performed. Review with git status.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
