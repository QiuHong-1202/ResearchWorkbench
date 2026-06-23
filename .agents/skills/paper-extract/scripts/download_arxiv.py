#!/usr/bin/env python
"""Download an arXiv paper PDF and save it with standardized naming to papers/."""
from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

USER_AGENT = "research-workbench-paper-extract/0.1"
ARXIV_API = "https://export.arxiv.org/api/query"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 5
RETRY_BACKOFF = 2.0
DOWNLOAD_CHUNK = 1 << 16  # 64 KiB

ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:)(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)


class ArxivMeta(NamedTuple):
    arxiv_id: str
    title: str
    year: int
    authors: list[str]
    pdf_url: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download arXiv PDF to papers/ with standard naming."
    )
    parser.add_argument(
        "link", help="arXiv link (abs or pdf URL, e.g. https://arxiv.org/abs/2501.12345)"
    )
    parser.add_argument(
        "--papers-dir",
        default="papers",
        help="Target directory for downloaded PDFs (default: papers/).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite if file already exists.",
    )
    return parser.parse_args()


def extract_arxiv_id(link: str) -> str:
    m = ARXIV_ID_RE.search(link)
    if m:
        return m.group(1)
    cleaned = link.strip().rstrip("/")
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", cleaned):
        return cleaned
    raise ValueError(f"Cannot extract arXiv ID from: {link}")


def _http_get(url: str, *, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": accept}
    )
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = RETRY_BACKOFF * (attempt + 1)
            print(f"Retry {attempt + 1}/{MAX_RETRIES} after {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _content_range_total(value: str | None) -> int | None:
    """Parse the total size from a Content-Range header (``bytes a-b/total``)."""
    m = re.search(r"/(\d+)\s*$", value or "")
    return int(m.group(1)) if m else None


def download_pdf(url: str, dest_path: Path) -> int:
    """Stream a PDF to ``dest_path`` with resumable, retrying downloads.

    Data is streamed to a ``.part`` file first. If the connection drops during a
    large arXiv PDF download, the next attempt resumes from the current offset
    using an HTTP Range request before the final PDF is validated and moved into
    place.
    """
    tmp_path = dest_path.with_name(dest_path.name + ".part")
    expected_total: int | None = None
    last_err: Exception | None = None

    for attempt in range(MAX_RETRIES):
        existing = tmp_path.stat().st_size if tmp_path.exists() else 0
        headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                if existing and status == 200:
                    existing = 0
                if status == 206:
                    total = _content_range_total(resp.headers.get("Content-Range"))
                    if total:
                        expected_total = total
                elif status == 200:
                    content_length = resp.headers.get("Content-Length")
                    if content_length and content_length.isdigit():
                        expected_total = int(content_length)

                mode = "ab" if existing else "wb"
                with open(tmp_path, mode) as f:
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)

            got = tmp_path.stat().st_size
            if expected_total and got < expected_total:
                raise http.client.IncompleteRead(b"", expected_total - got)

            with open(tmp_path, "rb") as f:
                magic = f.read(5)
            if not magic.startswith(b"%PDF"):
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(
                    "Downloaded content is not a valid PDF (bad magic bytes); "
                    "the paper may not be available yet."
                )
            if got < 1000:
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f"Downloaded data too small ({got} bytes).")

            tmp_path.replace(dest_path)
            return got
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 416:
                tmp_path.unlink(missing_ok=True)
                expected_total = None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            last_err = e

        if attempt == MAX_RETRIES - 1:
            break
        wait = RETRY_BACKOFF * (attempt + 1)
        have = tmp_path.stat().st_size if tmp_path.exists() else 0
        print(
            f"Download retry {attempt + 1}/{MAX_RETRIES} after {wait}s "
            f"(have {have} bytes): {last_err}",
            file=sys.stderr,
        )
        time.sleep(wait)

    raise RuntimeError(f"Failed to download after {MAX_RETRIES} attempts: {last_err}")


def fetch_metadata(arxiv_id: str) -> ArxivMeta:
    bare_id = re.sub(r"v\d+$", "", arxiv_id)
    query_url = f"{ARXIV_API}?id_list={bare_id}&max_results=1"
    data = _http_get(query_url, accept="application/xml")
    root = ET.fromstring(data)

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise RuntimeError(f"No entry found for arXiv ID: {arxiv_id}")

    id_elem = entry.find("atom:id", ns)
    if id_elem is None or id_elem.text is None:
        raise RuntimeError("Missing <id> in arXiv response")
    if "Error" in (id_elem.text or ""):
        raise RuntimeError(f"arXiv API error: {id_elem.text}")

    title_elem = entry.find("atom:title", ns)
    title = " ".join((title_elem.text or "").split()) if title_elem is not None else ""

    published_elem = entry.find("atom:published", ns)
    year = 2025
    if published_elem is not None and published_elem.text:
        year_match = re.match(r"(\d{4})", published_elem.text)
        if year_match:
            year = int(year_match.group(1))

    authors: list[str] = []
    for author_elem in entry.findall("atom:author", ns):
        name_elem = author_elem.find("atom:name", ns)
        if name_elem is not None and name_elem.text:
            authors.append(name_elem.text.strip())

    pdf_url = f"https://arxiv.org/pdf/{bare_id}.pdf"

    return ArxivMeta(
        arxiv_id=bare_id,
        title=title,
        year=year,
        authors=authors,
        pdf_url=pdf_url,
    )


def sanitize_filename(name: str) -> str:
    """Make a string safe for use as a Windows/POSIX filename."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(".")
    if len(name) > 200:
        name = name[:200].rstrip()
    return name


def build_standard_name(meta: ArxivMeta) -> str:
    title = sanitize_filename(meta.title)
    return f"{meta.year} - {title}"


def main() -> int:
    args = parse_args()

    try:
        arxiv_id = extract_arxiv_id(args.link)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"arXiv ID: {arxiv_id}", file=sys.stderr)
    print("Fetching metadata...", file=sys.stderr)

    try:
        meta = fetch_metadata(arxiv_id)
    except Exception as e:
        print(f"Failed to fetch metadata: {e}", file=sys.stderr)
        return 1

    print(f"Title: {meta.title}", file=sys.stderr)
    print(f"Year: {meta.year}", file=sys.stderr)
    print(f"Authors: {', '.join(meta.authors[:3])}{'...' if len(meta.authors) > 3 else ''}", file=sys.stderr)

    standard_name = build_standard_name(meta)
    papers_dir = Path(args.papers_dir)
    papers_dir.mkdir(parents=True, exist_ok=True)

    pdf_filename = f"{standard_name}.pdf"
    pdf_path = papers_dir / pdf_filename

    if pdf_path.exists() and not args.overwrite:
        print(f"File already exists: {pdf_path}", file=sys.stderr)
        print("Use --overwrite to replace it.", file=sys.stderr)
        result = {
            "status": "exists",
            "pdf_path": str(pdf_path),
            "note_stem": standard_name,
            "metadata": meta._asdict(),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(f"Downloading PDF from {meta.pdf_url} ...", file=sys.stderr)
    try:
        size = download_pdf(meta.pdf_url, pdf_path)
    except Exception as e:
        print(f"Failed to download PDF: {e}", file=sys.stderr)
        return 1

    print(f"Saved: {pdf_path} ({size} bytes)", file=sys.stderr)

    result = {
        "status": "downloaded",
        "pdf_path": str(pdf_path),
        "note_stem": standard_name,
        "metadata": {
            "arxiv_id": meta.arxiv_id,
            "title": meta.title,
            "year": meta.year,
            "authors": meta.authors,
            "pdf_url": meta.pdf_url,
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
