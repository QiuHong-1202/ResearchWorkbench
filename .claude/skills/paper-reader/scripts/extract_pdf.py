#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract text from a PDF into reusable artifacts."
    )
    parser.add_argument("--input", required=True, help="Path to the input PDF file.")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory for extracted artifacts.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing non-empty output directory.",
    )
    return parser.parse_args()


def guess_title(metadata: dict[str, str], first_page_text: str, pdf_path: Path) -> str:
    title = metadata.get("title", "").strip()
    if title and title.lower() not in {"untitled", "unknown", ""}:
        return title

    meaningful_lines: list[str] = []
    for line in first_page_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            # Markdown heading — likely the title; strip heading markers and bold
            clean = stripped.lstrip("# ").strip().strip("*").strip()
            if clean:
                return clean
        if stripped.lower().startswith("arxiv:"):
            continue
        meaningful_lines.append(stripped)
        if len(meaningful_lines) >= 3:
            break

    if meaningful_lines:
        candidate = max(meaningful_lines, key=len)
        # Strip markdown bold markers if present
        return candidate.strip("*").strip()
    return pdf_path.stem


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if any(path.iterdir()) and not overwrite:
            raise RuntimeError(
                f"Output directory already exists and is not empty: {path}. "
                "Use --overwrite to reuse it."
            )
        if overwrite:
            for child in path.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def extract_with_pymupdf4llm(pdf_path: Path) -> tuple[dict[str, str], int, dict[str, str]]:
    """Extract markdown text per page using pymupdf4llm.

    Returns (pages_dict, page_count, metadata).
    """
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(str(pdf_path))
    page_count = doc.page_count
    metadata = doc.metadata or {}

    pages: dict[str, str] = {}
    for page_num in range(page_count):
        md_text = pymupdf4llm.to_markdown(
            doc,
            pages=[page_num],  # 0-based
        )
        pages[str(page_num + 1)] = md_text

    doc.close()
    return pages, page_count, metadata


def main() -> int:
    args = parse_args()

    pdf_path = Path(args.input).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    fulltext_path = out_dir / "fulltext.md"
    pages_path = out_dir / "pages.json"
    manifest_path = out_dir / "manifest.json"

    manifest: dict[str, object] = {
        "input_pdf": str(pdf_path),
        "output_dir": str(out_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warnings": [],
        "errors": [],
    }

    try:
        if not pdf_path.exists():
            raise RuntimeError(f"Input PDF does not exist: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise RuntimeError(f"Input file is not a PDF: {pdf_path}")

        prepare_output_dir(out_dir, args.overwrite)

        pages, page_count, metadata = extract_with_pymupdf4llm(pdf_path)
        title_guess = guess_title(metadata, pages.get("1", ""), pdf_path)

        # Write fulltext.md — concatenate all pages
        fulltext = "\n\n".join(pages[str(i)] for i in range(1, page_count + 1))
        fulltext_path.write_text(fulltext, encoding="utf-8")

        # Write pages.json
        pages_payload = {
            "page_count": page_count,
            "pages": pages,
        }
        pages_path.write_text(
            json.dumps(pages_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        manifest.update(
            {
                "status": "ok",
                "title_guess": title_guess,
                "page_count": page_count,
                "fulltext_chars": len(fulltext),
                "fulltext_path": str(fulltext_path),
                "pages_path": str(pages_path),
                "pdfinfo": metadata,
            }
        )
    except Exception as exc:
        manifest["status"] = "error"
        manifest["errors"].append(str(exc))
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(str(exc), file=sys.stderr)
        return 1

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
