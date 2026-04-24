#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dedupe across categories and split papers into scoring batches."
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output root directory (same as fetch_arxiv.py --out-dir).",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Target arXiv announcement UTC date YYYY-MM-DD "
             "(default: auto-discover newest manifest under --out-dir).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override batch size; otherwise read from --config or default 55.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional config.yaml; provides default batch_size if --batch-size not given.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate batches even if dedupe-meta.json already exists.",
    )
    return parser.parse_args()


def resolve_date(value: str | None, out_dir: Path) -> str:
    if value:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    # Auto-discover: pick the newest YYYY-MM-DD subdir that has a manifest.
    # Prefer this over local/UTC "today" because the authoritative date is the
    # arXiv announcement UTC date that fetch_arxiv.py just wrote out.
    candidates: list[str] = []
    if out_dir.exists():
        for sub in out_dir.iterdir():
            if not sub.is_dir() or not DATE_DIR_RE.match(sub.name):
                continue
            if (sub / f"{sub.name}-manifest.json").exists():
                candidates.append(sub.name)
    if not candidates:
        raise RuntimeError(
            f"No dated manifest found under {out_dir}. "
            "Run fetch_arxiv.py first, or pass --date YYYY-MM-DD explicitly."
        )
    return max(candidates)


def load_batch_size_from_config(config_path: Path) -> int | None:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("pyyaml is required when --config is used. Run `uv sync` first.") from exc
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    val = data.get("batch_size")
    if val is None:
        return None
    if not isinstance(val, int) or val <= 0:
        raise RuntimeError(f"config.yaml `batch_size` must be a positive int, got {val!r}")
    return val


def load_manifest(date_dir: Path, date_str: str) -> dict[str, Any]:
    manifest_path = date_dir / f"{date_str}-manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            f"Manifest not found at {manifest_path}. Run fetch_arxiv.py first."
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def dedupe_across_categories(
    manifest: dict[str, Any],
    date_dir: Path,
) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for cat_entry in manifest.get("categories", []):
        status = cat_entry.get("status")
        if status not in ("ok", "skipped"):
            continue
        category = cat_entry["category"]
        json_path = Path(cat_entry["json_path"])
        if not json_path.is_absolute():
            json_path = date_dir / json_path.name
        if not json_path.exists():
            continue
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        for e in payload.get("entries", []):
            key = e.get("arxiv_id") or e.get("abs_link") or e.get("title")
            if not key:
                continue
            if key in seen:
                extras = seen[key].setdefault("extra_categories", [])
                if category != seen[key]["primary_category"] and category not in extras:
                    extras.append(category)
                continue
            seen[key] = {
                "arxiv_id": e.get("arxiv_id", ""),
                "primary_category": category,
                "extra_categories": [],
                "title": e.get("title", ""),
                "authors": e.get("authors", []),
                "abstract": e.get("abstract", ""),
                "abs_link": e.get("abs_link", ""),
                "pdf_link": e.get("pdf_link", ""),
                "published": e.get("published", ""),
            }
            order.append(key)
    return [seen[k] for k in order]


def write_batches(
    papers: list[dict[str, Any]],
    batches_dir: Path,
    batch_size: int,
) -> list[str]:
    if batches_dir.exists():
        shutil.rmtree(batches_dir)
    batches_dir.mkdir(parents=True, exist_ok=True)

    total = len(papers)
    batch_count = max(1, math.ceil(total / batch_size)) if total else 0
    rel_paths: list[str] = []
    for i in range(batch_count):
        start = i * batch_size
        end = min(start + batch_size, total)
        batch = {"batch": i + 1, "papers": papers[start:end]}
        fname = f"batch-{i + 1:02d}.json"
        (batches_dir / fname).write_text(
            json.dumps(batch, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rel_paths.append(f"{batches_dir.name}/{fname}")
    return rel_paths


def main() -> int:
    args = parse_args()
    root_dir = Path(args.out_dir).expanduser().resolve()
    try:
        date_str = resolve_date(args.date, root_dir)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    date_dir = root_dir / date_str

    if not date_dir.exists():
        print(f"Date directory not found: {date_dir}", file=sys.stderr)
        return 2

    batch_size = args.batch_size
    if batch_size is None and args.config:
        batch_size = load_batch_size_from_config(Path(args.config).expanduser().resolve())
    if batch_size is None:
        batch_size = 55

    meta_path = date_dir / f"{date_str}-dedupe-meta.json"
    batches_dir = date_dir / f"scoring-batches-{date_str}"

    if meta_path.exists() and not args.force:
        print(f"dedupe-meta already exists at {meta_path}. Use --force to regenerate.")
        print(f"Existing meta: {meta_path}")
        return 0

    manifest = load_manifest(date_dir, date_str)
    papers = dedupe_across_categories(manifest, date_dir)
    rel_paths = write_batches(papers, batches_dir, batch_size)

    meta = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(papers),
        "batch_count": len(rel_paths),
        "batch_size": batch_size,
        "batches": rel_paths,
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {meta_path}")
    print(f"Wrote {len(rel_paths)} batch file(s) under {batches_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
