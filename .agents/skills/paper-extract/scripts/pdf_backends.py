from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import re
from typing import cast


MarkerMetadata = dict[str, object]


def _as_pdf_metadata(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}

    mapping = cast(Mapping[object, object], value)
    return {
        key: item
        for key, item in mapping.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _as_string_keyed_dict(value: object) -> MarkerMetadata:
    if not isinstance(value, Mapping):
        return {}

    mapping = cast(Mapping[object, object], value)
    return {key: item for key, item in mapping.items() if isinstance(key, str)}


def _page_count_from_marker_meta(marker_meta: MarkerMetadata) -> int | None:
    page_stats = marker_meta.get("page_stats")
    if isinstance(page_stats, Sequence) and not isinstance(
        page_stats, (str, bytes, bytearray)
    ):
        return len(page_stats)
    return None


def _title_from_marker_toc(marker_meta: MarkerMetadata) -> str | None:
    toc = marker_meta.get("table_of_contents")
    if not isinstance(toc, Sequence) or isinstance(toc, (str, bytes, bytearray)):
        return None
    if not toc:
        return None

    first_entry = toc[0]
    if not isinstance(first_entry, Mapping):
        return None

    entry = cast(Mapping[object, object], first_entry)
    title = entry.get("title")
    if isinstance(title, str):
        return title.replace("\n", " ")
    return None


def _markdown_result_to_text(value: object) -> str:
    if isinstance(value, str):
        return value

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        chunks: list[str] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue

            entry = cast(Mapping[object, object], item)
            for key in ("text", "markdown", "md"):
                chunk = entry.get(key)
                if isinstance(chunk, str) and chunk:
                    chunks.append(chunk)
                    break

        if chunks:
            return "\n\n".join(chunks)

    raise TypeError("pymupdf4llm.to_markdown returned unsupported output type")


def _try_import_marker() -> bool:
    """Return True if marker-pdf can be imported."""
    try:
        from marker.converters.pdf import PdfConverter  # noqa: F401
        from marker.models import create_model_dict  # noqa: F401
        from marker.output import text_from_rendered  # noqa: F401

        return True
    except ImportError:
        return False


_INVALID_WINDOWS_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_image_filename(name: str, used_names: set[str]) -> str:
    safe_name = _INVALID_WINDOWS_FILENAME_CHARS.sub("_", Path(name).name).strip()
    if not safe_name:
        safe_name = "image.jpeg"

    stem = Path(safe_name).stem or "image"
    suffix = Path(safe_name).suffix
    candidate = safe_name
    counter = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate


def _save_images(images: dict, out_dir: Path) -> dict[str, str]:
    saved: dict[str, str] = {}
    used_names: set[str] = set()
    for fname, img in images.items():
        from io import BytesIO

        safe_fname = _safe_image_filename(str(fname), used_names)
        dest = out_dir / safe_fname
        buf = BytesIO()
        img.save(buf, format="JPEG")
        dest.write_bytes(buf.getvalue())
        saved[str(fname)] = safe_fname
    return saved


def _get_pdf_page_count(pdf_path: Path) -> int:
    """Get the page count from the PDF directly via pymupdf."""
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    count = doc.page_count
    doc.close()
    return count


def extract_with_pymupdf4llm(pdf_path: Path) -> tuple[dict[str, str], int, dict[str, str]]:
    """Extract markdown text per page using pymupdf4llm.

    Returns (pages_dict, page_count, metadata).
    """
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(str(pdf_path))
    page_count = cast(int, doc.page_count)
    metadata = _as_pdf_metadata(doc.metadata)

    pages: dict[str, str] = {}
    for page_num in range(page_count):
        md_text = _markdown_result_to_text(
            pymupdf4llm.to_markdown(
                doc,
                pages=[page_num],  # 0-based
            )
        )
        pages[str(page_num + 1)] = md_text

    doc.close()
    return pages, page_count, metadata


def extract_with_marker_pdf(
    pdf_path: Path,
) -> tuple[str, int, dict[str, str], MarkerMetadata, dict[str, bytes], list[str]]:
    """Extract text from a PDF using marker-pdf.

    Returns (markdown_text, page_count, pdf_metadata, marker_meta,
    images, warnings).
    """
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    converter = PdfConverter(artifact_dict=create_model_dict())
    rendered = converter(str(pdf_path))
    markdown_text, _, images = text_from_rendered(rendered)

    marker_meta = _as_string_keyed_dict(rendered.metadata)
    warnings: list[str] = []

    # Derive page count from marker metadata, fall back to pymupdf
    page_count_from_meta = _page_count_from_marker_meta(marker_meta)
    if page_count_from_meta is not None:
        page_count = page_count_from_meta
    else:
        page_count = _get_pdf_page_count(pdf_path)
        if page_count > 1:
            warnings.append(
                "marker-pdf metadata lacks page_stats; "
                f"page_count ({page_count}) obtained via pymupdf."
            )

    pdf_metadata: dict[str, str] = {}
    title = _title_from_marker_toc(marker_meta)
    if title:
        pdf_metadata["title"] = title

    return markdown_text, page_count, pdf_metadata, marker_meta, images, warnings
