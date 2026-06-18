from __future__ import annotations

import math
import re
from typing import TypedDict


class RelocatedBlock(TypedDict):
    page: int
    text: str


RelocatedBlocks = dict[str, list[RelocatedBlock]]


class MarkdownPostprocessReport(TypedDict):
    page_anchor_spans_removed: int
    citation_page_links_simplified: int
    figure_image_alts_added: int
    display_math_blocks_normalized: int


def _split_marker_markdown_by_pages(
    markdown_text: str,
    page_count: int,
) -> tuple[dict[str, str], list[str]]:
    """Best-effort split of marker-pdf output into per-page chunks.

    marker-pdf inserts ``<span id="page-N-0"></span>`` anchors for
    cross-referenced pages.  This function uses those anchors as
    approximate page boundaries.  Pages without an anchor are merged
    into the preceding page's entry, with empty placeholders retained
    so page keys cover 1..page_count.

    Returns ``(pages_dict, warnings)`` where keys are 1-based page
    numbers as strings.
    """
    warnings: list[str] = []
    pattern = re.compile(r'<span\s+id="page-(\d+)-0"\s*>\s*</span>')
    markers: list[tuple[int, int]] = [
        (int(m.group(1)), m.start()) for m in pattern.finditer(markdown_text)
    ]

    if not markers:
        warnings.append(
            "marker-pdf output contains no page-boundary anchors; "
            'pages.json stores the entire text under page "1" and '
            "empty placeholders for remaining pages."
        )
        pages = {"1": markdown_text}
        for page_num in range(2, page_count + 1):
            pages[str(page_num)] = ""
        return pages, warnings

    markers.sort(key=lambda x: x[1])
    pages: dict[str, str] = {}

    # Content before the first anchor -> page 1 (0-based page 0)
    head = markdown_text[: markers[0][1]].strip()
    if head:
        pages["1"] = head

    for i, (pid, pos) in enumerate(markers):
        end = markers[i + 1][1] if i + 1 < len(markers) else len(markdown_text)
        chunk = markdown_text[pos:end].strip()
        key = str(pid + 1)  # 1-based
        pages[key] = (pages[key] + "\n\n" + chunk) if key in pages else chunk

    missing_keys = [str(i) for i in range(1, page_count + 1) if str(i) not in pages]
    if missing_keys:
        warnings.append(
            f"Page-boundary anchors covered {len(pages)}/{page_count} pages; "
            f"{len(missing_keys)} page(s) merged into adjacent entries in "
            "pages.json and stored as empty placeholders."
        )
        for key in missing_keys:
            pages[key] = ""

    return {k: pages[k] for k in sorted(pages, key=lambda k: int(k))}, warnings


_HF_NUM_RE = re.compile(r"(?:^|\s)\d{1,4}(?:\s|$)")


def _strip_running_headers_footers(
    pages: dict[str, str],
    max_edge: int = 5,
    min_ratio: float = 0.4,
) -> tuple[dict[str, str], int]:
    """Remove repeated running headers and footers from per-page text.

    Scans the first/last *max_edge* non-blank lines of each page
    (starting from page 2), identifies lines whose normalized form
    appears in >= *min_ratio* of those pages, and strips matching
    edge lines from every page except page 1.

    Returns ``(cleaned_pages, total_lines_removed)``.
    """
    page_keys = sorted(pages.keys(), key=lambda k: int(k))
    if len(page_keys) < 3:
        return dict(pages), 0

    def _norm(line: str) -> str:
        s = " ".join(line.split()).lower()
        return _HF_NUM_RE.sub(" ", s).strip()

    def _edges(
        text: str,
    ) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
        nonblank = [
            (i, ln) for i, ln in enumerate(text.splitlines()) if ln.strip()
        ]
        top = nonblank[:max_edge]
        bot = nonblank[-max_edge:] if len(nonblank) > max_edge else []
        return top, bot

    # --- Phase 1: detect candidates from pages 2+ ---
    detect_keys = [k for k in page_keys if int(k) >= 2]
    if len(detect_keys) < 2:
        return dict(pages), 0

    top_freq: dict[str, int] = {}
    bot_freq: dict[str, int] = {}
    for k in detect_keys:
        top, bot = _edges(pages[k])
        seen: set[str] = set()
        for _, raw in top:
            if raw.strip().startswith("#"):
                continue
            n = _norm(raw)
            if n and len(n) > 10 and n not in seen:
                seen.add(n)
                top_freq[n] = top_freq.get(n, 0) + 1
        seen = set()
        for _, raw in bot:
            if raw.strip().startswith("#"):
                continue
            n = _norm(raw)
            if n and len(n) > 10 and n not in seen:
                seen.add(n)
                bot_freq[n] = bot_freq.get(n, 0) + 1

    threshold = max(2, math.ceil(len(detect_keys) * min_ratio))
    header_pats = {p for p, c in top_freq.items() if c >= threshold}
    footer_pats = {p for p, c in bot_freq.items() if c >= threshold}

    if not header_pats and not footer_pats:
        return dict(pages), 0

    # --- Phase 2: strip matching edge lines from pages 2+ ---
    total_removed = 0
    cleaned: dict[str, str] = {}
    for k in page_keys:
        if int(k) < 2:
            cleaned[k] = pages[k]
            continue

        lines = pages[k].splitlines()
        top, bot = _edges(pages[k])
        to_remove: set[int] = set()
        for idx, raw in top:
            if _norm(raw) in header_pats:
                to_remove.add(idx)
        for idx, raw in bot:
            if _norm(raw) in footer_pats:
                to_remove.add(idx)

        total_removed += len(to_remove)
        cleaned[k] = "\n".join(
            ln for i, ln in enumerate(lines) if i not in to_remove
        )

    return cleaned, total_removed


_IMAGE_LINE_RE = re.compile(
    r"!\[[^\]]*\]\([^)]+\)"
    r"|<img\b[^>]*>"
    r"|==>\s*picture\s*\[[^\]]+\]\s*intentionally omitted",
    re.IGNORECASE,
)
_FIGURE_CAPTION_RE = re.compile(
    r"^(?:figure|fig\.?)\s+[\w.-]+\s*[:.)-]",
    re.IGNORECASE,
)
_TABLE_CAPTION_RE = re.compile(
    r"^(?:table|tab\.?)\s+[\w.-]+\s*[:.)-]",
    re.IGNORECASE,
)
_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s:\-|]+\|$")
_HTML_TABLE_OPEN_RE = re.compile(r"^<table\b", re.IGNORECASE)
_HTML_TABLE_CLOSE_RE = re.compile(r"</table>", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_PUBLICATION_ID_RE = re.compile(
    r"\b(?:ISSN\s*)?\d{4}-[\dXx]{3}[\dXx]\b"
    r"|\bISBN\s+\d[-\dXx]+\b",
    re.IGNORECASE,
)
_PAGE_ANCHOR_SPAN_RE = re.compile(
    r"<span\s+id=[\"']page-\d+-\d+[\"']\s*>\s*</span>",
    re.IGNORECASE,
)
_ESCAPED_CITATION_PAGE_LINK_RE = re.compile(
    r"\[(?P<label>\\\[\s*\d+(?:\s*(?:,|;|-|\u2013)\s*\d+)*\s*\\\])\]"
    r"\(#page-\d+-\d+\)"
)
_BRACKETED_CITATION_PAGE_LINK_RE = re.compile(
    r"\[(?P<label>\[\s*\d+(?:\s*(?:,|;|-|\u2013)\s*\d+)*\s*\])\]"
    r"\(#page-\d+-\d+\)"
)
_SIMPLE_CITATION_PAGE_LINK_RE = re.compile(
    r"\[(?P<label>\d+(?:\s*(?:,|;|-|\u2013)\s*\d+)*)\]"
    r"\(#page-\d+-\d+\)"
)
_EMPTY_IMAGE_ALT_RE = re.compile(r"!\[\s*\]\((?P<src>[^)\n]+)\)")
_DISPLAY_MATH_BLOCK_RE = re.compile(
    r"(?<!\$)\$\$(?P<body>.*?)(?<!\$)\$\$(?!\$)",
    re.DOTALL,
)


def _strip_markdown_wrappers(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^<span\s+id=\"page-\d+-\d+\"\s*>\s*</span>\s*", "", text)
    return text.strip(" *_`")


def _is_figure_line(line: str) -> bool:
    text = line.strip()
    if _IMAGE_LINE_RE.search(text):
        return True

    plain = _strip_markdown_wrappers(text)
    return bool(_FIGURE_CAPTION_RE.match(plain))


def _is_table_caption_line(line: str) -> bool:
    plain = _strip_markdown_wrappers(line)
    return bool(_TABLE_CAPTION_RE.match(plain))


def _match_markdown_table(
    lines: list[str],
    start: int,
) -> tuple[str | None, int]:
    """Detect a GitHub-style pipe table starting at ``lines[start]``.

    Requires the start line to be a pipe row and the next line to be a
    separator row (e.g. ``|---|---|``).  Returns ``(block_text,
    consumed)`` where ``block_text`` joins the consecutive pipe rows, or
    ``(None, 0)`` when no table is found.
    """
    if not _TABLE_ROW_RE.match(lines[start].strip()):
        return None, 0
    if start + 1 >= len(lines):
        return None, 0
    separator = lines[start + 1].strip()
    if not (_TABLE_SEPARATOR_RE.match(separator) and "-" in separator):
        return None, 0

    block: list[str] = []
    idx = start
    while idx < len(lines) and _TABLE_ROW_RE.match(lines[idx].strip()):
        block.append(lines[idx].strip())
        idx += 1

    return "\n".join(block), idx - start


def _match_html_table(
    lines: list[str],
    start: int,
) -> tuple[str | None, int]:
    """Detect an HTML ``<table>`` block starting at ``lines[start]``.

    Collects lines up to and including the closing ``</table>`` tag.
    Returns ``(None, 0)`` when the opening tag is absent or the table is
    not closed within the remaining lines.
    """
    if not _HTML_TABLE_OPEN_RE.match(lines[start].strip()):
        return None, 0

    block: list[str] = []
    idx = start
    while idx < len(lines):
        block.append(lines[idx].strip())
        if _HTML_TABLE_CLOSE_RE.search(lines[idx]):
            return "\n".join(block), idx - start + 1
        idx += 1

    return None, 0


def _is_front_page_boilerplate_line(line: str, page_num: int) -> bool:
    if page_num != 1:
        return False

    plain = _strip_markdown_wrappers(line)
    if not plain:
        return False

    lower = plain.lower()

    if "digital object identifier" in lower:
        return True
    if _DOI_RE.search(plain) and re.match(r"^(?:doi\b|https?://doi\.org)", lower):
        return True
    if _PUBLICATION_ID_RE.search(plain) and any(
        marker in lower
        for marker in ("copyright", "©", "ieee", "acm", "rights", "licensed")
    ):
        return True
    if re.search(r"\b(?:manuscript\s+)?received\b", lower) and any(
        marker in lower
        for marker in (
            "accepted",
            "revised",
            "published",
            "date of publication",
            "date of current version",
        )
    ):
        return True

    boilerplate_markers = (
        "permission to make digital",
        "personal use is permitted",
        "all rights reserved",
        "copyright held",
        "publication rights licensed",
        "request permissions",
        "to copy otherwise",
        "republication/redistribution",
        "this work is licensed under",
        "creative commons attribution",
        "date of publication",
        "date of current version",
    )
    if any(marker in lower for marker in boilerplate_markers):
        return True
    if "copyright" in lower and any(
        marker in lower for marker in ("©", "owner/author", "acm", "ieee", "rights")
    ):
        return True
    if "©" in plain and any(
        marker in lower for marker in ("ieee", "acm", "copyright", "rights")
    ):
        return True

    return False


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _simplify_citation_page_links(text: str) -> tuple[str, int]:
    total = 0

    def _replace_bracketed(match: re.Match[str]) -> str:
        label = match.group("label")
        return label.replace(r"\[", "[").replace(r"\]", "]")

    text, count = _ESCAPED_CITATION_PAGE_LINK_RE.subn(_replace_bracketed, text)
    total += count
    text, count = _BRACKETED_CITATION_PAGE_LINK_RE.subn(
        _replace_bracketed,
        text,
    )
    total += count

    def _replace_simple(match: re.Match[str]) -> str:
        return f"[{match.group('label')}]"

    text, count = _SIMPLE_CITATION_PAGE_LINK_RE.subn(_replace_simple, text)
    total += count
    return text, total


def _clean_marker_page_artifacts(text: str) -> tuple[str, int, int]:
    cleaned, spans_removed = _PAGE_ANCHOR_SPAN_RE.subn("", text)
    cleaned, citations_simplified = _simplify_citation_page_links(cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return _collapse_blank_lines(cleaned), spans_removed, citations_simplified


def _add_figure_image_alts(
    text: str,
    figure_start: int,
) -> tuple[str, int, int]:
    figure_num = figure_start

    def _replace(match: re.Match[str]) -> str:
        nonlocal figure_num
        label = f"Figure {figure_num}"
        figure_num += 1
        return f"![{label}]({match.group('src')})"

    cleaned, count = _EMPTY_IMAGE_ALT_RE.subn(_replace, text)
    return cleaned, count, figure_num


def _normalize_display_math_blocks(text: str) -> tuple[str, int]:
    """Put display math delimiters on their own lines."""
    changes = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal changes
        original = match.group(0)
        body = match.group("body").strip()
        if not body:
            return original

        normalized = f"$$\n{body}\n$$"
        if normalized == original:
            return original

        changes += 1
        return normalized

    return _DISPLAY_MATH_BLOCK_RE.sub(_replace, text), changes


def _postprocess_extracted_markdown(
    pages: dict[str, str],
    blocks: RelocatedBlocks,
) -> tuple[dict[str, str], RelocatedBlocks, MarkdownPostprocessReport]:
    """Apply deterministic cleanup before optional LLM review.

    The LLM postprocessor is responsible for higher-level judgment, but these
    rules address common marker-pdf artifacts that are safe to fix without
    model inference.
    """
    report: MarkdownPostprocessReport = {
        "page_anchor_spans_removed": 0,
        "citation_page_links_simplified": 0,
        "figure_image_alts_added": 0,
        "display_math_blocks_normalized": 0,
    }

    cleaned_pages: dict[str, str] = {}
    for page_key in sorted(pages.keys(), key=lambda k: int(k)):
        cleaned, spans_removed, citations_simplified = _clean_marker_page_artifacts(
            pages[page_key]
        )
        report["page_anchor_spans_removed"] += spans_removed
        report["citation_page_links_simplified"] += citations_simplified
        cleaned, math_blocks_normalized = _normalize_display_math_blocks(cleaned)
        report["display_math_blocks_normalized"] += math_blocks_normalized
        cleaned_pages[page_key] = cleaned

    cleaned_blocks: RelocatedBlocks = {}
    next_figure_num = 1
    for block_name, items in blocks.items():
        cleaned_items: list[RelocatedBlock] = []
        for item in items:
            cleaned_text, spans_removed, citations_simplified = (
                _clean_marker_page_artifacts(item["text"])
            )
            report["page_anchor_spans_removed"] += spans_removed
            report["citation_page_links_simplified"] += citations_simplified
            cleaned_text, math_blocks_normalized = _normalize_display_math_blocks(
                cleaned_text
            )
            report["display_math_blocks_normalized"] += math_blocks_normalized

            if block_name == "figures":
                cleaned_text, alts_added, next_figure_num = _add_figure_image_alts(
                    cleaned_text,
                    next_figure_num,
                )
                report["figure_image_alts_added"] += alts_added

            cleaned_items.append({"page": item["page"], "text": cleaned_text})
        cleaned_blocks[block_name] = cleaned_items

    return cleaned_pages, cleaned_blocks, report


def _relocate_markdown_blocks(
    pages: dict[str, str],
) -> tuple[dict[str, str], RelocatedBlocks]:
    blocks: RelocatedBlocks = {
        "figures": [],
        "tables": [],
        "copyright": [],
    }
    cleaned_pages: dict[str, str] = {}

    for page_key in sorted(pages.keys(), key=lambda k: int(k)):
        page_num = int(page_key)
        body_lines: list[str] = []
        lines = pages[page_key].splitlines()
        n = len(lines)
        i = 0

        while i < n:
            line = lines[i]
            normalized = line.strip()
            if not normalized:
                body_lines.append(line)
                i += 1
                continue

            table_text, consumed = _match_markdown_table(lines, i)
            if table_text is None:
                table_text, consumed = _match_html_table(lines, i)
            if table_text is not None:
                blocks["tables"].append({"page": page_num, "text": table_text})
                i += consumed
                continue

            if _is_table_caption_line(normalized):
                blocks["tables"].append({"page": page_num, "text": normalized})
                i += 1
                continue

            if _is_figure_line(normalized):
                blocks["figures"].append({"page": page_num, "text": normalized})
                i += 1
                continue

            if _is_front_page_boilerplate_line(normalized, page_num):
                blocks["copyright"].append({"page": page_num, "text": normalized})
                i += 1
                continue

            body_lines.append(line)
            i += 1

        cleaned_pages[page_key] = _collapse_blank_lines("\n".join(body_lines))

    return cleaned_pages, blocks


def _format_relocated_block(items: list[RelocatedBlock]) -> str:
    lines: list[str] = []
    current_page: int | None = None
    for item in items:
        page = item["page"]
        text = item["text"].strip()
        if not text:
            continue
        if page != current_page:
            if lines:
                lines.append("")
            lines.append(f"### Page {page}")
            lines.append("")
            current_page = page
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def _build_fulltext_with_relocated_blocks(
    pages: dict[str, str],
    blocks: RelocatedBlocks,
) -> str:
    sorted_keys = sorted(pages.keys(), key=lambda k: int(k))
    body = "\n\n".join(pages[k] for k in sorted_keys if pages[k].strip()).strip()

    sections: list[str] = []
    figures = _format_relocated_block(blocks.get("figures", []))
    if figures:
        sections.append(f"## Figures\n\n{figures}")

    tables = _format_relocated_block(blocks.get("tables", []))
    if tables:
        sections.append(f"## Tables\n\n{tables}")

    copyright_text = _format_relocated_block(blocks.get("copyright", []))
    if copyright_text:
        sections.append(f"## Copyright\n\n{copyright_text}")

    if sections:
        if body:
            body = f"{body}\n\n" + "\n\n".join(sections)
        else:
            body = "\n\n".join(sections)

    return body.strip() + "\n"
