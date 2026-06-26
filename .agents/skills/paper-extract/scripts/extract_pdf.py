#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from markdown_cleanup import (
    _build_fulltext_with_relocated_blocks,
    _postprocess_extracted_markdown,
    _relocate_markdown_blocks,
    _split_marker_markdown_by_pages,
    _strip_running_headers_footers,
)
from llm_postprocess import (
    LLM_POSTPROCESS_REPORT_NAME,
    write_llm_postprocess_prompt,
)
from pdf_backends import (
    _save_images,
    _try_import_marker,
    extract_with_marker_pdf,
    extract_with_pymupdf4llm,
)


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
    generated_names = {"fulltext.md", "assets", "figs"}
    if path.exists():
        existing_generated = [path / name for name in generated_names if (path / name).exists()]
        if existing_generated and not overwrite:
            names = ", ".join(p.name for p in existing_generated)
            raise RuntimeError(
                f"Output directory already contains extracted artifacts ({names}): {path}. "
                "Use --overwrite to refresh generated artifacts."
            )
        if overwrite:
            for child in existing_generated:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def year_from_stem(stem: str) -> int | None:
    match = re.match(r"^(\d{4})\s+-\s+", stem)
    return int(match.group(1)) if match else None


def authors_from_metadata(metadata: dict[str, str]) -> list[str]:
    value = metadata.get("author") or metadata.get("authors") or ""
    if not value:
        return []
    parts = re.split(r"\s*[,;]\s*", value)
    return [part for part in (p.strip() for p in parts) if part]


def write_paper_record(
    *,
    out_dir: Path,
    pdf_path: Path,
    title: str,
    metadata: dict[str, str],
    manifest_path: Path,
    pages_path: Path,
    fulltext_path: Path,
) -> None:
    record_path = out_dir / "paper.json"
    existing: dict[str, object] = {}
    if record_path.exists():
        try:
            loaded = json.loads(record_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except json.JSONDecodeError:
            existing = {}

    paper_stem = out_dir.name
    record: dict[str, object] = {
        "schema_version": 1,
        "paper_stem": paper_stem,
        "title": existing.get("title") or title,
        "year": existing.get("year") or year_from_stem(paper_stem),
        "authors": existing.get("authors") or authors_from_metadata(metadata),
        "venue": existing.get("venue") or "",
        "tags": existing.get("tags") or [],
        "status": existing.get("status") or "extracted",
        "source": existing.get("source") or repo_relative(pdf_path),
        "pdf_path": existing.get("pdf_path") or repo_relative(pdf_path),
        "note_path": repo_relative(out_dir / "note.md"),
        "fulltext_path": repo_relative(fulltext_path),
        "translation_path": repo_relative(out_dir / "fulltext.zh-CN.md"),
        "manifest_path": repo_relative(manifest_path),
        "pages_path": repo_relative(pages_path),
        "supplements": existing.get("supplements") or [],
    }
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()

    pdf_path = Path(args.input).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    assets_dir = out_dir / "assets"
    figs_dir = out_dir / "figs"
    fulltext_path = out_dir / "fulltext.md"
    pages_path = assets_dir / "pages.json"
    manifest_path = assets_dir / "manifest.json"

    warnings: list[str] = []
    errors: list[str] = []
    manifest: dict[str, object] = {
        "input_pdf": str(pdf_path),
        "output_dir": str(out_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
        "errors": errors,
    }

    try:
        if not pdf_path.exists():
            raise RuntimeError(f"Input PDF does not exist: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise RuntimeError(f"Input file is not a PDF: {pdf_path}")

        prepare_output_dir(out_dir, args.overwrite)
        assets_dir.mkdir(exist_ok=True)
        figs_dir.mkdir(exist_ok=True)

        if _try_import_marker():
            from importlib.metadata import version

            manifest["backend"] = f"marker-pdf {version('marker-pdf')}"
            raw_text, page_count, metadata, marker_meta, images, marker_warnings = (
                extract_with_marker_pdf(pdf_path)
            )
            warnings.extend(marker_warnings)

            marker_meta_path = assets_dir / "_marker_meta.json"
            marker_meta_path.write_text(
                json.dumps(marker_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            saved_image_map = _save_images(images, figs_dir)

            for original_fname, saved_fname in saved_image_map.items():
                raw_text = raw_text.replace(
                    f"]({original_fname})", f"](figs/{saved_fname})"
                )

            # Split into per-page chunks using page-boundary anchors
            pages, split_warnings = _split_marker_markdown_by_pages(
                raw_text, page_count,
            )
            warnings.extend(split_warnings)

            # Strip running headers/footers from split pages
            pages, n_hf = _strip_running_headers_footers(pages)
            if n_hf:
                warnings.append(
                    f"Stripped {n_hf} running header/footer line(s)."
                )
        else:
            warning_msg = (
                "marker-pdf is not installed; falling back to pymupdf4llm. "
                "Install marker-pdf with: uv sync --extra marker"
            )
            print(warning_msg, file=sys.stderr)
            warnings.append(warning_msg)
            manifest["backend"] = "pymupdf4llm"
            pages, page_count, metadata = extract_with_pymupdf4llm(pdf_path)
            marker_meta_path = None
            saved_image_map = {}

            # Strip running headers/footers, then build fulltext
            pages, n_hf = _strip_running_headers_footers(pages)
            if n_hf:
                warnings.append(
                    f"Stripped {n_hf} running header/footer line(s)."
                )

        pages, extracted_blocks = _relocate_markdown_blocks(pages)
        pages, extracted_blocks, markdown_postprocess_report = (
            _postprocess_extracted_markdown(pages, extracted_blocks)
        )
        fulltext = _build_fulltext_with_relocated_blocks(pages, extracted_blocks)
        relocated_block_counts = {
            name: len(items) for name, items in extracted_blocks.items() if items
        }

        title_guess = guess_title(metadata, pages.get("1", ""), pdf_path)
        llm_postprocess_prompt_path = write_llm_postprocess_prompt(
            assets_dir=assets_dir,
            fulltext_path=fulltext_path,
            pages_path=pages_path,
            manifest_path=manifest_path,
        )

        # Write fulltext.md
        fulltext_path.write_text(fulltext, encoding="utf-8")

        # Write pages.json
        pages_payload = {
            "page_count": page_count,
            "pages": pages,
            "extracted_blocks": extracted_blocks,
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
                "relocated_block_counts": relocated_block_counts,
                "postprocess": {
                    "deterministic": {
                        "status": "ok",
                        "rules": [
                            "remove_marker_page_anchor_spans",
                            "simplify_citation_page_anchor_links",
                            "add_sequential_figure_image_alt_text",
                            "normalize_display_math_blocks",
                        ],
                        "changes": markdown_postprocess_report,
                    },
                    "llm_agent": {
                        "status": "prompt_ready",
                        "prompt_path": str(llm_postprocess_prompt_path),
                        "report_path": str(
                            assets_dir / LLM_POSTPROCESS_REPORT_NAME
                        ),
                    },
                },
            }
        )
        if marker_meta_path is not None:
            manifest["marker_meta_path"] = str(marker_meta_path)
        if saved_image_map:
            manifest["extracted_images"] = [
                f"figs/{f}" for f in saved_image_map.values()
            ]
        write_paper_record(
            out_dir=out_dir,
            pdf_path=pdf_path,
            title=title_guess,
            metadata=metadata,
            manifest_path=manifest_path,
            pages_path=pages_path,
            fulltext_path=fulltext_path,
        )
    except Exception as exc:
        manifest["status"] = "error"
        errors.append(str(exc))
        manifest["error_type"] = type(exc).__name__
        manifest["traceback"] = traceback.format_exc()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
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
