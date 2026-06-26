#!/usr/bin/env python
"""Download an arXiv paper PDF and save it with standardized naming to papers/."""
from __future__ import annotations

import argparse
import email.utils
import gzip
import http.client
import http.cookiejar
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

ARXIV_API = "https://export.arxiv.org/api/query"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 6
# The export API is aggressively rate-limited but we have a reliable abs-page
# fallback, so fail over quickly instead of burning the full backoff schedule.
API_MAX_RETRIES = 3
RETRY_BACKOFF = 3.0  # base seconds; arXiv asks for >=3s between API requests
BACKOFF_CAP = 60.0  # cap a single computed backoff wait
RETRY_AFTER_CAP = 120.0  # never honor a server Retry-After longer than this
DOWNLOAD_CHUNK = 1 << 16  # 64 KiB

# Simulate a real browser: modern Chrome UA + the headers a browser actually
# sends. arXiv's API/abs endpoints sit behind Cloudflare, which is friendlier to
# requests that look like a genuine browser navigation than to a bare urllib UA.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# A single opener with a shared cookie jar so cookies set by arXiv/Cloudflare
# (e.g. on the abs page) are reused on the subsequent PDF request, exactly like a
# browser that visits the abstract page and then clicks the PDF link.
_COOKIE_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_COOKIE_JAR))

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


def _build_headers(
    *, accept: str | None = None, referer: str | None = None, identity: bool = False
) -> dict[str, str]:
    """Return browser-like headers, optionally overriding Accept/Referer."""
    headers = dict(BROWSER_HEADERS)
    if accept:
        headers["Accept"] = accept
    if referer:
        headers["Referer"] = referer
        # A "click from the abs page" is a same-origin navigation.
        headers["Sec-Fetch-Site"] = "same-origin"
    if identity:
        # Stream raw bytes (no gzip) so chunked reads and Range resume stay valid.
        headers["Accept-Encoding"] = "identity"
    return headers


def _read_response(resp) -> bytes:
    """Read a fully-buffered response, transparently decoding gzip/deflate."""
    data = resp.read()
    encoding = (resp.headers.get("Content-Encoding") or "").lower()
    if "gzip" in encoding:
        try:
            return gzip.decompress(data)
        except OSError:
            return data
    if "deflate" in encoding:
        try:
            return zlib.decompress(data)
        except zlib.error:
            try:
                return zlib.decompress(data, -zlib.MAX_WBITS)
            except zlib.error:
                return data
    return data


def _retry_after_seconds(err: urllib.error.HTTPError) -> float | None:
    """Parse a Retry-After header (delta-seconds or HTTP-date) into seconds."""
    value = err.headers.get("Retry-After") if err.headers else None
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())


def _backoff_wait(attempt: int, retry_after: float | None) -> float:
    """Exponential backoff with jitter, honoring a server Retry-After hint."""
    if retry_after is not None:
        return min(retry_after, RETRY_AFTER_CAP) + random.uniform(0.0, 1.0)
    base = min(RETRY_BACKOFF * (2 ** attempt), BACKOFF_CAP)
    return base + random.uniform(0.0, base * 0.25)


def _http_get(
    url: str,
    *,
    accept: str = "*/*",
    referer: str | None = None,
    max_retries: int = MAX_RETRIES,
) -> bytes:
    req = urllib.request.Request(url, headers=_build_headers(accept=accept, referer=referer))
    last_err: Exception | None = None
    for attempt in range(max_retries):
        retry_after: float | None = None
        try:
            with _OPENER.open(req, timeout=REQUEST_TIMEOUT) as resp:
                return _read_response(resp)
        except urllib.error.HTTPError as e:
            last_err = e
            retry_after = _retry_after_seconds(e)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            last_err = e
        if attempt == max_retries - 1:
            raise last_err
        wait = _backoff_wait(attempt, retry_after)
        print(
            f"Retry {attempt + 1}/{max_retries} after {wait:.1f}s: {last_err}",
            file=sys.stderr,
        )
        time.sleep(wait)
    raise RuntimeError(f"unreachable: {last_err}")


def _content_range_total(value: str | None) -> int | None:
    """Parse the total size from a Content-Range header (``bytes a-b/total``)."""
    m = re.search(r"/(\d+)\s*$", value or "")
    return int(m.group(1)) if m else None


def download_pdf(url: str, dest_path: Path, *, referer: str | None = None) -> int:
    """Stream a PDF to ``dest_path`` with resumable, retrying downloads.

    Robust against ``IncompleteRead`` / dropped connections on large files:
    data is streamed to a ``.part`` temp file and, on failure, the download
    resumes from the current offset using an HTTP Range request. The final
    file is validated (PDF magic bytes + expected length) before being moved
    into place.

    Requests are made with browser-like headers and a ``Referer`` pointing at
    the abstract page, reusing the shared cookie jar, so the download mimics a
    user clicking the PDF link from the abs page.
    """
    tmp_path = dest_path.with_name(dest_path.name + ".part")
    expected_total: int | None = None
    last_err: Exception | None = None

    for attempt in range(MAX_RETRIES):
        retry_after: float | None = None
        existing = tmp_path.stat().st_size if tmp_path.exists() else 0
        headers = _build_headers(accept="application/pdf", referer=referer, identity=True)
        if existing:
            headers["Range"] = f"bytes={existing}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            with _OPENER.open(req, timeout=REQUEST_TIMEOUT) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                if existing and status == 200:
                    # Server ignored the Range request; restart from scratch.
                    existing = 0
                if status == 206:
                    total = _content_range_total(resp.headers.get("Content-Range"))
                    if total:
                        expected_total = total
                elif status == 200:
                    cl = resp.headers.get("Content-Length")
                    if cl and cl.isdigit():
                        expected_total = int(cl)
                mode = "ab" if existing else "wb"
                with open(tmp_path, mode) as f:
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)

            got = tmp_path.stat().st_size
            if expected_total and got < expected_total:
                # Short read: connection dropped before EOF; trigger a resume.
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
            retry_after = _retry_after_seconds(e)
            if e.code == 416:
                # Range not satisfiable (stale/complete .part); restart clean.
                tmp_path.unlink(missing_ok=True)
                expected_total = None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            last_err = e

        if attempt == MAX_RETRIES - 1:
            break
        wait = _backoff_wait(attempt, retry_after)
        have = tmp_path.stat().st_size if tmp_path.exists() else 0
        print(
            f"Download retry {attempt + 1}/{MAX_RETRIES} after {wait:.1f}s "
            f"(have {have} bytes): {last_err}",
            file=sys.stderr,
        )
        time.sleep(wait)

    raise RuntimeError(f"Failed to download after {MAX_RETRIES} attempts: {last_err}")


def fetch_metadata(arxiv_id: str) -> ArxivMeta:
    bare_id = re.sub(r"v\d+$", "", arxiv_id)
    query_url = f"{ARXIV_API}?id_list={bare_id}&max_results=1"
    data = _http_get(query_url, accept="application/xml", max_retries=API_MAX_RETRIES)
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


def _meta_tag(html: str, name: str) -> str | None:
    """Extract a ``<meta name=... content=...>`` value (attribute order agnostic)."""
    patterns = (
        rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']{re.escape(name)}["\']',
    )
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _year_from_id(bare_id: str) -> int:
    """Derive the publication year from the YYMM prefix of an arXiv id."""
    m = re.match(r"(\d{2})\d{2}\.", bare_id)
    if m:
        return 2000 + int(m.group(1))
    return 2025


def fetch_metadata_from_abs(arxiv_id: str) -> ArxivMeta:
    """Fallback metadata parse from the CDN-cached abs page (the page a browser
    loads). Used when the rate-limited export API returns 429/503."""
    bare_id = re.sub(r"v\d+$", "", arxiv_id)
    abs_url = f"https://arxiv.org/abs/{bare_id}"
    html = _http_get(abs_url, accept="text/html").decode("utf-8", "replace")

    title = _meta_tag(html, "citation_title") or ""
    if not title:
        tm = re.search(
            r"<title>\s*(?:\[[^\]]*\]\s*)?(.*?)</title>", html, re.IGNORECASE | re.DOTALL
        )
        if tm:
            title = tm.group(1)
    title = " ".join(title.split())
    if not title:
        raise RuntimeError("Could not parse title from abs page")

    date_str = (
        _meta_tag(html, "citation_date")
        or _meta_tag(html, "citation_online_date")
        or _meta_tag(html, "citation_publication_date")
    )
    year = _year_from_id(bare_id)
    if date_str:
        ym = re.search(r"(\d{4})", date_str)
        if ym:
            year = int(ym.group(1))

    authors: list[str] = []
    for am in re.finditer(
        r'<meta[^>]+name=["\']citation_author["\'][^>]+content=["\']([^"\']*)["\']',
        html,
        re.IGNORECASE,
    ):
        name = am.group(1).strip()
        if name:
            authors.append(name)

    return ArxivMeta(
        arxiv_id=bare_id,
        title=title,
        year=year,
        authors=authors,
        pdf_url=f"https://arxiv.org/pdf/{bare_id}.pdf",
    )


def fallback_meta(arxiv_id: str) -> ArxivMeta:
    """Last-resort metadata when neither API nor abs page is reachable.

    The PDF is still downloadable from the CDN, so we never block on naming:
    use a deterministic ``arXiv-<id>`` stem derived purely from the id."""
    bare_id = re.sub(r"v\d+$", "", arxiv_id)
    return ArxivMeta(
        arxiv_id=bare_id,
        title="",
        year=_year_from_id(bare_id),
        authors=[],
        pdf_url=f"https://arxiv.org/pdf/{bare_id}.pdf",
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
    if not title:
        return sanitize_filename(f"arXiv-{meta.arxiv_id}")
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

    # Metadata is only used for naming, so it must never block the download.
    # Degrade gracefully: export API -> CDN-cached abs page -> id-only stem.
    meta_source = "api"
    try:
        meta = fetch_metadata(arxiv_id)
    except Exception as e:
        print(f"Metadata API failed: {e}", file=sys.stderr)
        print("Falling back to abs page (CDN-cached) for metadata...", file=sys.stderr)
        try:
            meta = fetch_metadata_from_abs(arxiv_id)
            meta_source = "abs"
        except Exception as e2:
            print(f"Abs-page metadata fallback failed: {e2}", file=sys.stderr)
            print(
                "Proceeding with id-only filename; PDF download is unaffected.",
                file=sys.stderr,
            )
            meta = fallback_meta(arxiv_id)
            meta_source = "id_only"

    print(f"Metadata source: {meta_source}", file=sys.stderr)
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
            "paper_stem": standard_name,
            "metadata_source": meta_source,
            "metadata": meta._asdict(),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    abs_url = f"https://arxiv.org/abs/{meta.arxiv_id}"
    print(f"Downloading PDF from {meta.pdf_url} ...", file=sys.stderr)
    try:
        size = download_pdf(meta.pdf_url, pdf_path, referer=abs_url)
    except Exception as e:
        print(f"Failed to download PDF: {e}", file=sys.stderr)
        return 1

    print(f"Saved: {pdf_path} ({size} bytes)", file=sys.stderr)

    result = {
        "status": "downloaded",
        "pdf_path": str(pdf_path),
        "paper_stem": standard_name,
        "metadata_source": meta_source,
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
