#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRIMARY_RSS = "https://rss.arxiv.org/rss/{category}"
FALLBACK_RSS = "http://export.arxiv.org/rss/{category}"
API_ENDPOINT = "http://export.arxiv.org/api/query"
API_PAGE_SIZE = 500
USER_AGENT = "snowman-arxiv-daily/0.1 (+https://github.com/snowman)"
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 2.0
INTER_CATEGORY_SLEEP = 3.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch arXiv RSS feeds and write daily digest artifacts.")
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="arXiv category, e.g. cs.CV. Repeatable. If omitted, categories come from --config.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output root directory; per-day files are written to {out-dir}/{date}/.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Target arXiv announcement UTC date YYYY-MM-DD (default: auto-detect from feed).",
    )
    parser.add_argument("--config", default=None, help="Optional config.yaml to source categories from.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-fetch even if today's outputs already exist (default: skip).",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "rss", "api"),
        default="auto",
        help="Fetch source. auto (default): RSS for UTC today, arXiv Query API for historical --date. "
             "rss: always RSS. api: always arXiv Query API (requires --date).",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=DEFAULT_REQUEST_TIMEOUT,
        help=f"HTTP request timeout in seconds (default: {DEFAULT_REQUEST_TIMEOUT}).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Retry count for transient HTTP failures (default: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF,
        help=f"Base backoff in seconds for retries (default: {DEFAULT_RETRY_BACKOFF}).",
    )
    return parser.parse_args()


def load_categories_from_config(config_path: Path) -> list[str]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("pyyaml is required when --config is used. Run `uv sync` first.") from exc
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    cats = data.get("categories") or []
    if not isinstance(cats, list) or not all(isinstance(c, str) for c in cats):
        raise RuntimeError(f"config.yaml `categories` must be a list of strings, got {cats!r}")
    return cats


def is_retryable_http_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or 500 <= exc.code < 600
    return True


def http_get(url: str, *, timeout: int, max_retries: int, retry_backoff: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    total_attempts = max(1, max_retries + 1)
    for attempt in range(1, total_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout) as exc:
            if attempt >= total_attempts or not is_retryable_http_error(exc):
                raise
            sleep_seconds = retry_backoff * (2 ** (attempt - 1))
            time.sleep(max(0.0, sleep_seconds))
    raise RuntimeError(f"HTTP request exhausted retries for {url}")


def fetch_feed_bytes(
    category: str,
    *,
    timeout: int,
    max_retries: int,
    retry_backoff: float,
) -> tuple[bytes, str]:
    last_err: Exception | None = None
    for template in (PRIMARY_RSS, FALLBACK_RSS):
        url = template.format(category=category)
        try:
            return http_get(
                url,
                timeout=timeout,
                max_retries=max_retries,
                retry_backoff=retry_backoff,
            ), url
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout) as exc:
            last_err = exc
            continue
    raise RuntimeError(f"All RSS endpoints failed for {category}: {last_err}")


def fetch_via_api(
    category: str,
    date_str: str,
    *,
    timeout: int,
    max_retries: int,
    retry_backoff: float,
) -> tuple[list[Any], str]:
    """Fetch all entries for a given UTC date via the arXiv Query API.

    Uses submittedDate:[D0000 TO D2359] (GMT) combined with cat:{category},
    paginating with start/max_results and sleeping 3s between pages.
    Returns (feedparser_entries, first_page_url).
    """
    try:
        import feedparser
    except ImportError as exc:
        raise RuntimeError("feedparser is required. Run `uv sync` first.") from exc

    ymd = date_str.replace("-", "")
    search_query = f"cat:{category} AND submittedDate:[{ymd}0000 TO {ymd}2359]"

    all_entries: list[Any] = []
    first_url: str | None = None
    start = 0
    while True:
        params = {
            "search_query": search_query,
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
            "start": str(start),
            "max_results": str(API_PAGE_SIZE),
        }
        url = f"{API_ENDPOINT}?{urllib.parse.urlencode(params)}"
        if first_url is None:
            first_url = url
        try:
            raw = http_get(
                url,
                timeout=timeout,
                max_retries=max_retries,
                retry_backoff=retry_backoff,
            )
        except Exception as exc:
            raise RuntimeError(
                f"API page fetch failed for {category} at start={start}: {exc}"
            ) from exc
        feed = feedparser.parse(raw)
        batch = list(feed.entries or [])
        all_entries.extend(batch)
        if len(batch) < API_PAGE_SIZE:
            break
        start += len(batch)
        time.sleep(INTER_CATEGORY_SLEEP)
    return all_entries, first_url or API_ENDPOINT


ARXIV_ID_RE = re.compile(r"arxiv\.org/abs/([^\s/?#]+)")
ABSTRACT_SPLIT_RE = re.compile(r"(?is)\bAbstract\s*:\s*")
COMMENT_SPLIT_RE = re.compile(r"(?is)\bComment\s*:\s*")
AUTHORS_SPLIT_RE = re.compile(r"(?is)\bAuthors?\s*:\s*")


def clean_text(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\r", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_entry(entry: Any, category: str) -> dict[str, Any]:
    title = clean_text(getattr(entry, "title", "") or entry.get("title", ""))
    title = re.sub(r"\s*\(arXiv:[^)]*\)\s*$", "", title).strip()

    link = (getattr(entry, "link", "") or entry.get("link", "") or "").strip()
    arxiv_id = ""
    m = ARXIV_ID_RE.search(link)
    if m:
        arxiv_id = m.group(1)
    if not arxiv_id:
        eid = entry.get("id", "") if hasattr(entry, "get") else getattr(entry, "id", "")
        m2 = ARXIV_ID_RE.search(eid or "")
        if m2:
            arxiv_id = m2.group(1)
    if arxiv_id:
        abs_link = f"https://arxiv.org/abs/{arxiv_id}"
        pdf_link = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    else:
        abs_link = link
        pdf_link = link.replace("/abs/", "/pdf/") + ".pdf" if "/abs/" in link else ""

    authors: list[str] = []
    raw_authors = entry.get("authors") if hasattr(entry, "get") else None
    if raw_authors:
        for a in raw_authors:
            name = a.get("name") if isinstance(a, dict) else str(a)
            name = clean_text(name)
            if name:
                authors.append(name)
    if not authors:
        dc = entry.get("author", "") if hasattr(entry, "get") else ""
        if dc:
            authors = [clean_text(x) for x in re.split(r",| and ", dc) if clean_text(x)]

    description = ""
    for key in ("summary", "description"):
        val = entry.get(key, "") if hasattr(entry, "get") else getattr(entry, key, "")
        if val:
            description = val
            break

    abstract = description
    if ABSTRACT_SPLIT_RE.search(abstract):
        abstract = ABSTRACT_SPLIT_RE.split(abstract, maxsplit=1)[1]
    if COMMENT_SPLIT_RE.search(abstract):
        abstract = COMMENT_SPLIT_RE.split(abstract, maxsplit=1)[0]
    abstract = clean_text(abstract)

    if not authors:
        auth_section = description
        if AUTHORS_SPLIT_RE.search(auth_section):
            auth_section = AUTHORS_SPLIT_RE.split(auth_section, maxsplit=1)[1]
            if ABSTRACT_SPLIT_RE.search(auth_section):
                auth_section = ABSTRACT_SPLIT_RE.split(auth_section, maxsplit=1)[0]
            authors = [clean_text(x) for x in re.split(r",| and ", auth_section) if clean_text(x)]

    published = ""
    for key in ("published", "updated", "pubDate"):
        val = entry.get(key, "") if hasattr(entry, "get") else ""
        if val:
            published = val
            break
    parsed_time = None
    for key in ("published_parsed", "updated_parsed"):
        pt = entry.get(key) if hasattr(entry, "get") else None
        if pt:
            parsed_time = pt
            break
    if parsed_time:
        try:
            dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
            published = dt.isoformat()
        except Exception:
            pass

    return {
        "arxiv_id": arxiv_id,
        "category": category,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "abs_link": abs_link,
        "pdf_link": pdf_link,
        "published": published,
    }


def extract_utc_date(entry: Any) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        pt = entry.get(key) if hasattr(entry, "get") else None
        if pt:
            try:
                return datetime(*pt[:6], tzinfo=timezone.utc).date().isoformat()
            except Exception:
                continue
    return None


def render_markdown(date_str: str, category: str, entries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f"# ArXiv Daily - {date_str}")
    lines.append(f"Category: {category} | Entries: {len(entries)}")
    lines.append("")
    if not entries:
        lines.append("No new submissions today.")
        lines.append("")
        return "\n".join(lines)
    for i, e in enumerate(entries, 1):
        title = e["title"] or "(no title)"
        abs_link = e["abs_link"] or ""
        lines.append(f"## {i}. [{title}]({abs_link})")
        if e["authors"]:
            lines.append(f"**Authors:** {', '.join(e['authors'])}")
        if e["published"]:
            lines.append(f"**Published:** {e['published']}")
        if e["pdf_link"]:
            lines.append(f"**PDF:** {e['pdf_link']}")
        if e["abstract"]:
            lines.append(f"**Abstract:** {e['abstract']}")
        lines.append("")
    return "\n".join(lines)


def resolve_explicit_date(value: str | None) -> str | None:
    if value is None:
        return None
    datetime.strptime(value, "%Y-%m-%d")
    return value


def infer_announce_date_from_feed(entries_raw: list[Any]) -> str | None:
    for e in entries_raw:
        utc = extract_utc_date(e)
        if utc:
            return utc
    return None


def process_category(
    category: str,
    date_str: str,
    announce_date: str,
    out_dir: Path,
    force: bool,
    prefetched: tuple[bytes, str] | None = None,
    source: str = "rss",
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
) -> dict[str, Any]:
    md_path = out_dir / f"{date_str}-arxiv-{category}.md"
    json_path = out_dir / f"{date_str}-arxiv-{category}.json"

    if not force and md_path.exists() and json_path.exists():
        entry_count = 0
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
            entry_count = len(existing.get("entries", []))
        except Exception:
            pass
        return {
            "category": category,
            "status": "skipped",
            "source": source,
            "md_path": str(md_path),
            "json_path": str(json_path),
            "entry_count": entry_count,
            "filtered_out": 0,
            "note": "existing outputs reused; pass --force to refetch",
        }

    try:
        import feedparser
    except ImportError as exc:
        raise RuntimeError("feedparser is required. Run `uv sync` first.") from exc

    result: dict[str, Any] = {
        "category": category,
        "status": "ok",
        "source": source,
        "md_path": str(md_path),
        "json_path": str(json_path),
        "entry_count": 0,
        "filtered_out": 0,
    }

    try:
        if source == "api":
            entries_raw, used_url = fetch_via_api(
                category,
                announce_date,
                timeout=request_timeout,
                max_retries=max_retries,
                retry_backoff=retry_backoff,
            )
            result["source_url"] = used_url
            filter_by_announce = False
        else:
            if prefetched is not None:
                raw, used_url = prefetched
            else:
                raw, used_url = fetch_feed_bytes(
                    category,
                    timeout=request_timeout,
                    max_retries=max_retries,
                    retry_backoff=retry_backoff,
                )
            result["source_url"] = used_url
            feed = feedparser.parse(raw)
            entries_raw = list(feed.entries or [])
            filter_by_announce = True

        seen: set[str] = set()
        entries: list[dict[str, Any]] = []
        filtered_out = 0
        for e in entries_raw:
            if filter_by_announce:
                entry_utc = extract_utc_date(e)
                if entry_utc is None or entry_utc != announce_date:
                    filtered_out += 1
                    continue
            parsed = parse_entry(e, category)
            key = parsed["arxiv_id"] or parsed["abs_link"] or parsed["title"]
            if key in seen:
                continue
            seen.add(key)
            entries.append(parsed)

        result["entry_count"] = len(entries)
        result["filtered_out"] = filtered_out

        md_path.write_text(render_markdown(date_str, category, entries), encoding="utf-8")
        json_path.write_text(
            json.dumps(
                {"date": date_str, "category": category, "entries": entries},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    return result


def main() -> int:
    args = parse_args()
    root_dir = Path(args.out_dir).expanduser().resolve()
    force = args.force
    request_timeout = max(1, args.request_timeout)
    max_retries = max(0, args.max_retries)
    retry_backoff = max(0.0, args.retry_backoff)

    categories: list[str] = list(args.category)
    if not categories and args.config:
        categories = load_categories_from_config(Path(args.config).expanduser().resolve())
    if not categories:
        print("No categories provided. Use --category or --config.", file=sys.stderr)
        return 2

    try:
        import feedparser
    except ImportError as exc:
        raise RuntimeError("feedparser is required. Run `uv sync` first.") from exc

    explicit_date = resolve_explicit_date(args.date)
    utc_today = datetime.now(timezone.utc).date().isoformat()

    if args.source == "api":
        if not explicit_date:
            print("--source api requires --date YYYY-MM-DD.", file=sys.stderr)
            return 2
        source = "api"
    elif args.source == "rss":
        source = "rss"
    else:  # auto
        source = "api" if (explicit_date and explicit_date != utc_today) else "rss"

    announce_date: str | None = explicit_date
    announce_date_source: str | None = None
    prefetch_warnings: list[str] = []
    prefetch_errors_by_cat: dict[str, str] = {}
    prefetch: dict[str, tuple[bytes, str]] = {}

    if source == "api":
        announce_date_source = "api-explicit"
    elif explicit_date is not None:
        announce_date_source = "explicit"
    else:
        for idx, cat in enumerate(categories):
            if idx > 0:
                time.sleep(INTER_CATEGORY_SLEEP)
            try:
                raw, used_url = fetch_feed_bytes(
                    cat,
                    timeout=request_timeout,
                    max_retries=max_retries,
                    retry_backoff=retry_backoff,
                )
            except Exception as exc:
                prefetch_errors_by_cat[cat] = str(exc)
                continue
            prefetch[cat] = (raw, used_url)
            feed = feedparser.parse(raw)
            inferred = infer_announce_date_from_feed(feed.entries or [])
            if inferred:
                announce_date = inferred
                announce_date_source = "feed-inference"
                break
            prefetch_warnings.append(f"{cat}: feed had no entries with UTC date")

        if announce_date is None:
            announce_date = utc_today
            announce_date_source = "utc-today-fallback"
            prefetch_warnings.append(
                f"Could not infer announce_date from any feed; using UTC today ({announce_date})."
            )

    date_str = announce_date
    out_dir = root_dir / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / f"{date_str}-manifest.json"
    previous_manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            previous_manifest = None
    previous_was_incomplete = bool(
        previous_manifest
        and (
            previous_manifest.get("status") in ("partial", "error")
            or any(c.get("status") == "error" for c in previous_manifest.get("categories", []))
        )
    )

    manifest: dict[str, Any] = {
        "date": date_str,
        "announce_date": announce_date,
        "announce_date_source": announce_date_source,
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_timeout": request_timeout,
        "max_retries": max_retries,
        "retry_backoff": retry_backoff,
        "status": "ok",
        "categories": [],
        "warnings": list(prefetch_warnings),
        "errors": [],
    }

    fetched_any = False
    for idx, cat in enumerate(categories):
        # Only sleep when we actually need to hit the network again.
        needs_network = cat not in prefetch
        if fetched_any and needs_network:
            time.sleep(INTER_CATEGORY_SLEEP)
        res = process_category(
            cat,
            date_str,
            announce_date,
            out_dir,
            force,
            prefetched=prefetch.get(cat),
            source=source,
            request_timeout=request_timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
        )
        manifest["categories"].append(res)
        if res["status"] == "ok":
            fetched_any = True
        if res["status"] == "error":
            # If a pre-fetch attempt also failed for this cat, surface both causes.
            pre_err = prefetch_errors_by_cat.pop(cat, None)
            detail = res.get("error", "unknown error")
            if pre_err:
                detail = f"{detail} (pre-fetch also failed: {pre_err})"
            manifest["errors"].append(f"{cat}: {detail}")
        else:
            # Pre-fetch blip was recovered; demote it from errors to a warning.
            pre_err = prefetch_errors_by_cat.pop(cat, None)
            if pre_err:
                manifest["warnings"].append(
                    f"{cat}: pre-fetch failed ({pre_err}) but formal fetch succeeded"
                )
        filtered = res.get("filtered_out", 0)
        if filtered:
            manifest["warnings"].append(
                f"{cat}: filtered out {filtered} entries not matching announce_date {announce_date}"
            )

    # Any pre-fetch errors left over are for categories never formally processed
    # (shouldn't normally happen, but surface them so nothing is silently dropped).
    for cat, err in prefetch_errors_by_cat.items():
        manifest["errors"].append(f"{cat} (pre-fetch, no formal fetch attempted): {err}")

    good_count = sum(1 for c in manifest["categories"] if c["status"] in ("ok", "skipped"))
    err_count = sum(1 for c in manifest["categories"] if c["status"] == "error")
    if err_count and good_count:
        manifest["status"] = "partial"
    elif err_count and not good_count:
        manifest["status"] = "error"

    if previous_was_incomplete and manifest["status"] == "ok":
        meta_path = out_dir / f"{date_str}-dedupe-meta.json"
        recommended_path = root_dir / f"{date_str}-arxiv-recommended.md"
        stale_outputs: list[str] = []
        if meta_path.exists():
            stale_outputs.append(str(meta_path))
        if recommended_path.exists():
            stale_outputs.append(str(recommended_path))
        if stale_outputs:
            manifest["warnings"].append(
                "Recovered from a previous partial fetch. Regenerate downstream artifacts "
                f"with --force because these outputs may be stale: {', '.join(stale_outputs)}"
            )

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if manifest["status"] == "error":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
