#!/usr/bin/env python
"""Build a standalone library/index.html from paper library records."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_ROOT = REPO_ROOT / "library"
PAPERS_ROOT = LIBRARY_ROOT / "papers"
INDEX_HTML_PATH = LIBRARY_ROOT / "index.html"
VENUE_ALIASES_PATH = Path(__file__).with_name("venue_aliases.json")


def normalize_venue(value: str, aliases: dict[str, list[str]]) -> str:
    def words(text: str) -> str:
        return re.sub(r"[^\w]+", " ", text.casefold()).strip()

    normalized = words(value)
    names = sorted(
        ((words(name), short) for short, names in aliases.items() for name in [short, *names]),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for name, short in names:
        if normalized == name:
            return short
        if not normalized.startswith(name + " "):
            continue
        suffix = normalized[len(name):].strip()
        if short == "arxiv":
            return short
        if suffix.startswith("under review"):
            return short + " (under review)"
        if suffix.startswith(words(short) + " "):
            suffix = suffix[len(words(short)):].strip()
        if re.match(r"(?:\d|vol\b|article\b|january\b|february\b|march\b|april\b|may\b|june\b|july\b|august\b|september\b|october\b|november\b|december\b)", suffix):
            return short
    return value


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def notes_rel(path: Path) -> str:
    return os.path.relpath(path.resolve(), LIBRARY_ROOT.resolve()).replace("\\", "/")


def url_path(value: str) -> str:
    if not value:
        return ""
    if re.match(r"^(?:https?|file)://", value):
        return value
    return quote(value, safe="/:#%")


def path_from_record_value(value: str) -> Path | None:
    if not value or re.match(r"^https?://", value):
        return None
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def link_for(value: str) -> str:
    if not value:
        return ""
    if re.match(r"^https?://", value):
        return value
    path = path_from_record_value(value)
    if path and path.exists():
        try:
            path.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError:
            return path.resolve().as_uri()
        return url_path(notes_rel(path))
    return ""


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    result: dict[str, Any] = {}
    for raw_line in text[3:end].strip().splitlines():
        if not raw_line.strip() or ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        result[key.strip()] = parse_value(value.strip())
    return result


def parse_value(value: str) -> Any:
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        reader = csv.reader(io.StringIO(inner), skipinitialspace=True)
        return [strip_quotes(item.strip()) for item in next(reader)]
    if re.fullmatch(r"\d+", value):
        return int(value)
    return strip_quotes(value)


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []


def display_authors(authors: list[str]) -> str:
    if len(authors) <= 3:
        return ", ".join(authors)
    return ", ".join(authors[:3]) + " et al."


def link(label: str, href: str, *, primary: bool = False, icon: str = "Supplement") -> str:
    paths = {
        "Note": '<path d="M4 4h12v16H4zM8 8h4M8 12h4M8 16h3M19 5v12"/>',
        "PDF": '<path d="M6 3h8l4 4v14H6zM14 3v5h4M12 11v6m-3-3 3 3 3-3"/>',
        "Fulltext": '<path d="M3 5h7l2 2 2-2h7v15h-7l-2 1-2-1H3zM12 7v14M6 9h3M6 12h3M15 9h3M15 12h3"/>',
        "Translation": '<path d="M3 5h10M8 3v2M5 5c0 5 3 8 7 10M11 5c0 5-3 8-7 10M13 21l4-10 4 10M15 17h4"/>',
        "Supplement": '<path d="m8 13 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l8-8M7 14l7-7"/>',
    }
    svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths[icon]}</svg>'
    label = html.escape(label, quote=True)
    if not href:
        return f'<span class="missing" title="{label} unavailable" role="img" aria-label="{label} unavailable">{svg}</span>'
    cls = "link primary" if primary else "link"
    return f'<a class="{cls}" href="{html.escape(href, quote=True)}" title="{label}" aria-label="{label}">{svg}</a>'


def collect_papers() -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    venue_aliases = json.loads(VENUE_ALIASES_PATH.read_text(encoding="utf-8"))
    if not PAPERS_ROOT.exists():
        return papers

    for record_path in sorted(PAPERS_ROOT.glob("*/paper.json")):
        record_dir = record_path.parent
        record = read_json(record_path)
        if not record:
            continue

        note_path = record_dir / "note.md"
        note_frontmatter: dict[str, Any] = {}
        if note_path.exists():
            note_frontmatter = parse_frontmatter(note_path.read_text(encoding="utf-8"))

        title = str(note_frontmatter.get("title") or record.get("title") or record_dir.name)
        year = note_frontmatter.get("year") or record.get("year") or ""
        venue = str(note_frontmatter.get("venue") or record.get("venue") or "")
        authors = list_value(note_frontmatter.get("authors") or record.get("authors"))
        source = str(note_frontmatter.get("source") or record.get("source") or "")
        pdf_link = link_for(str(record.get("pdf_path") or "")) or link_for(source)

        fulltext_path = record_dir / "fulltext.md"
        translation_path = record_dir / "fulltext.zh-CN.md"
        supplements = []
        for item in record.get("supplements") or []:
            if not isinstance(item, dict):
                continue
            supplement_href = link_for(str(item.get("path") or "")) or link_for(
                str(item.get("translation_path") or "")
            )
            if supplement_href:
                supplements.append(
                    {
                        "label": str(item.get("label") or "Supplement"),
                        "href": supplement_href,
                    }
                )

        papers.append(
            {
                "paper_stem": str(record.get("paper_stem") or record_dir.name),
                "title": title,
                "year": year,
                "venue": normalize_venue(venue, venue_aliases),
                "venue_full": venue,
                "added_at": str(record.get("added_at") or record.get("created") or ""),
                "authors": authors,
                "note": url_path(notes_rel(note_path)) if note_path.exists() else "",
                "pdf": pdf_link,
                "fulltext": url_path(notes_rel(fulltext_path)) if fulltext_path.exists() else "",
                "translation": url_path(notes_rel(translation_path)) if translation_path.exists() else "",
                "supplements": supplements,
                "search_text": " ".join(
                    str(item)
                    for item in [title, year, display_authors(authors), record_dir.name]
                    if item
                ).lower(),
            }
        )

    papers.sort(
        key=lambda item: (
            -(int(item["year"]) if str(item["year"]).isdigit() else 0),
            item["title"].lower(),
        )
    )
    return papers


def render_rows(papers: list[dict[str, Any]]) -> str:
    rows = []
    for index, paper in enumerate(papers, start=1):
        supplements = " ".join(
            link(item["label"], item["href"]) for item in paper["supplements"]
        )
        title = html.escape(paper["title"])
        year = html.escape(str(paper["year"] or ""))
        venue = html.escape(paper["venue"] or "—", quote=True)
        venue_full = html.escape(paper["venue_full"] or "—", quote=True)
        added_at = paper["added_at"]
        added_timestamp = ""
        if added_at:
            added_date = datetime.fromisoformat(added_at)
            if added_date.tzinfo is None:
                added_date = added_date.replace(tzinfo=timezone.utc)
            added_timestamp = str(added_date.timestamp())
        added_display = html.escape(added_at[:10] or "Unknown")
        authors = html.escape(display_authors(paper["authors"]))
        search_text = html.escape(paper["search_text"], quote=True)
        rows.append(
            f'        <tr data-year="{year}" data-added="{added_timestamp}" data-order="{index}" data-search="{search_text}">\n'
            f'          <td class="index">{index}</td>\n'
            f'          <td><div class="title" title="{title}">{title}</div><div class="authors" title="{authors}">{authors}</div></td>\n'
            f'          <td class="year">{year}</td>\n'
            f'          <td><div class="venue" title="{venue_full}">{venue}</div></td>\n'
            f'          <td class="year" title="{html.escape(added_at, quote=True)}">{added_display}</td>\n'
            f'          <td><div class="actions">{link("Note", paper["note"], primary=True, icon="Note")} '
            f'{link("PDF", paper["pdf"], icon="PDF")} {link("Fulltext", paper["fulltext"], icon="Fulltext")} '
            f'{link("Translation", paper["translation"], icon="Translation")} {supplements}</div></td>\n'
            "        </tr>"
        )
    return "\n".join(rows)


def render_year_options(papers: list[dict[str, Any]]) -> str:
    years = sorted({str(paper["year"]) for paper in papers if paper["year"]}, reverse=True)
    return "\n".join(
        f'            <option value="{html.escape(year, quote=True)}">{html.escape(year)}</option>'
        for year in years
    )


def render_html(papers: list[dict[str, Any]]) -> str:
    rows = render_rows(papers)
    year_options = render_year_options(papers)
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Paper Notes</title>
    <link rel="icon" type="image/svg+xml" href="favicon.svg">
    <style>
      :root {{
        --bg: #f7f7f5;
        --panel: #ffffff;
        --text: #202421;
        --muted: #6f7772;
        --line: #e4e8e2;
        --accent: #2f6f5d;
        --accent-soft: #e7f0ec;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 14px;
        line-height: 1.5;
      }}
      main {{
        width: min(1320px, calc(100% - 64px));
        margin: 0 auto;
        padding: 36px 0 48px;
      }}
      header {{ margin-bottom: 24px; }}
      h1 {{ margin: 0; font-size: 28px; font-weight: 600; letter-spacing: -0.5px; }}
      .meta {{ color: var(--muted); font-size: 13px; }}
      header .meta {{ margin-top: 6px; }}
      .toolbar {{
        display: grid;
        grid-template-columns: minmax(200px, 1fr) 140px 200px;
        gap: 10px;
      }}
      input, select {{
        height: 38px;
        min-width: 0;
        width: 100%;
        border: 1px solid #d5dcd3;
        border-radius: 6px;
        background: var(--panel);
        color: var(--text);
        padding: 0 12px;
        font: inherit;
      }}
      input::placeholder {{ color: var(--muted); }}
      input:focus, select:focus, button:focus-visible, a:focus-visible {{
        outline: 2px solid var(--accent);
        outline-offset: 2px;
      }}
      .filter-status {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        min-height: 44px;
      }}
      button {{ font: inherit; cursor: pointer; }}
      #clearFilters {{
        border: 0;
        padding: 6px 0 6px 12px;
        background: transparent;
        color: var(--accent);
        font-size: 13px;
      }}
      #clearFilters:disabled {{ color: var(--muted); opacity: 0.55; cursor: default; }}
      .table-wrap {{
        overflow-x: auto;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
      }}
      table {{ width: 100%; min-width: 880px; border-collapse: collapse; table-layout: fixed; }}
      .number-col {{ width: 48px; }}
      .year-col {{ width: 76px; }}
      .venue-col {{ width: 120px; }}
      .venue {{ color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .date-col {{ width: 120px; }}
      .resources-col {{ width: 220px; }}
      th, td {{ padding: 12px 14px; text-align: left; vertical-align: middle; border-bottom: 1px solid var(--line); }}
      th {{ padding-top: 10px; padding-bottom: 10px; background: #f0f2ef; color: var(--muted); font-size: 12px; font-weight: 600; }}
      th:first-child, .index {{ text-align: right; }}
      tr:last-child td {{ border-bottom: 0; }}
      tbody tr:hover {{ background: #f8faf7; }}
      tbody tr {{ height: 72px; }}
      .index, .year {{ color: var(--muted); white-space: nowrap; font-size: 12px; font-variant-numeric: tabular-nums; }}
      .title {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 15px; font-weight: 600; line-height: 1.5; }}
      .authors {{ margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .actions {{ display: flex; align-items: center; gap: 6px; overflow-x: auto; padding: 3px; }}
      .link, .missing {{ display: inline-flex; flex: 0 0 30px; align-items: center; justify-content: center; height: 30px; border-radius: 5px; }}
      .actions svg {{ width: 19px; height: 19px; }}
      .link {{ color: var(--accent); text-decoration: none; }}
      .link:hover, .link.primary {{ background: var(--accent-soft); }}
      .missing {{ color: #aab2ac; }}
      .sort-button {{ border: 0; padding: 0; background: transparent; color: inherit; font-weight: inherit; white-space: nowrap; }}
      th[aria-sort="ascending"], th[aria-sort="descending"] {{ color: var(--accent); }}
      #emptyState {{ padding: 40px 20px; text-align: center; color: var(--muted); }}
      @media (max-width: 900px) {{
        main {{ width: calc(100% - 32px); padding-top: 24px; }}
        table {{ min-width: 760px; }}
        .number-col {{ width: 36px; }}
        .year-col {{ width: 64px; }}
        .date-col {{ width: 104px; }}
        .resources-col {{ width: 206px; }}
        th, td {{ padding-left: 10px; padding-right: 10px; }}
      }}
      @media (max-width: 600px) {{
        header {{ margin-bottom: 18px; }}
        h1 {{ font-size: 24px; }}
        .toolbar {{ grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: 8px; }}
        #searchInput {{ grid-column: 1 / -1; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <header>
        <div>
          <h1>Paper Notes</h1>
          <div class="meta">论文、阅读笔记与全文资料</div>
        </div>
      </header>
      <section class="toolbar" aria-label="Filters">
        <input id="searchInput" type="search" aria-label="搜索标题或作者" placeholder="搜索标题或作者">
        <select id="yearSelect" aria-label="Year filter">
          <option value="">全部年份</option>
{year_options}
        </select>
        <select id="sortSelect" aria-label="排序方式">
          <option value="added-desc">添加时间：新到旧</option>
          <option value="added-asc">添加时间：旧到新</option>
          <option value="year-desc">出版年份：新到旧</option>
          <option value="year-asc">出版年份：旧到新</option>
        </select>
      </section>
      <div class="filter-status">
        <span id="resultCount" class="meta" role="status" aria-live="polite">找到 {len(papers)} / {len(papers)} 篇</span>
        <button id="clearFilters" type="button" disabled>清除筛选</button>
      </div>
      <div class="table-wrap">
        <table>
          <colgroup><col class="number-col"><col><col class="year-col"><col class="venue-col"><col class="date-col"><col class="resources-col"></colgroup>
          <thead>
            <tr>
              <th>#</th>
              <th>Paper</th>
              <th aria-sort="none"><button type="button" class="sort-button" data-sort="year" data-label="Year">Year ↕</button></th>
              <th>Venue</th>
              <th aria-sort="descending"><button type="button" class="sort-button" data-sort="added" data-label="添加时间">添加时间 ↓</button></th>
              <th>资料</th>
            </tr>
          </thead>
          <tbody>
{rows}
          </tbody>
        </table>
        <div id="emptyState" hidden>没有找到匹配的论文，请尝试其他关键词或清除筛选。</div>
      </div>
    </main>
    <script>
      const searchInput = document.getElementById("searchInput");
      const yearSelect = document.getElementById("yearSelect");
      const sortSelect = document.getElementById("sortSelect");
      const tbody = document.querySelector("tbody");
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      const resultCount = document.getElementById("resultCount");
      const clearFilters = document.getElementById("clearFilters");
      const emptyState = document.getElementById("emptyState");
      const sortButtons = Array.from(document.querySelectorAll(".sort-button"));
      const storageKey = "paper-library-view:" + location.pathname;

      try {{
        const saved = JSON.parse(localStorage.getItem(storageKey));
        if (saved && typeof saved === "object") {{
          if (typeof saved.search === "string") searchInput.value = saved.search;
          if (Array.from(yearSelect.options).some((option) => option.value === saved.year)) yearSelect.value = saved.year;
          if (Array.from(sortSelect.options).some((option) => option.value === saved.sort)) sortSelect.value = saved.sort;
        }}
      }} catch {{ /* Browsing still works when local storage is unavailable. */ }}

      function saveSettings() {{
        try {{
          localStorage.setItem(storageKey, JSON.stringify({{
            search: searchInput.value, year: yearSelect.value, sort: sortSelect.value,
          }}));
        }} catch {{ /* Browsing still works when local storage is unavailable. */ }}
      }}

      function applyFilters() {{
        const query = searchInput.value.trim().toLowerCase();
        const year = yearSelect.value;
        let visible = 0;
        rows.forEach((row) => {{
          const matchesSearch = !query || row.dataset.search.includes(query);
          const matchesYear = !year || row.dataset.year === year;
          const show = matchesSearch && matchesYear;
          row.hidden = !show;
          if (show) row.querySelector(".index").textContent = ++visible;
        }});
        resultCount.textContent = `找到 ${{visible}} / ${{rows.length}} 篇`;
        emptyState.hidden = visible !== 0;
        clearFilters.disabled = !searchInput.value && !year;
        saveSettings();
      }}

      searchInput.addEventListener("input", applyFilters);
      yearSelect.addEventListener("change", applyFilters);
      function applySort() {{
        const [field, direction] = sortSelect.value.split("-");
        rows.sort((a, b) => {{
          const originalOrder = Number(a.dataset.order) - Number(b.dataset.order);
          if (!a.dataset[field] || !b.dataset[field]) {{
            return Number(!a.dataset[field]) - Number(!b.dataset[field]) || originalOrder;
          }}
          const difference = Number(a.dataset[field]) - Number(b.dataset[field]);
          return (direction === "asc" ? difference : -difference) || originalOrder;
        }});
        rows.forEach((row) => tbody.appendChild(row));
        sortButtons.forEach((button) => {{
          const active = button.dataset.sort === field;
          button.parentElement.setAttribute("aria-sort", active ? (direction === "asc" ? "ascending" : "descending") : "none");
          button.textContent = button.dataset.label + " " + (active ? (direction === "asc" ? "↑" : "↓") : "↕");
        }});
        applyFilters();
      }}
      sortSelect.addEventListener("change", applySort);
      sortButtons.forEach((button) => button.addEventListener("click", () => {{
        const field = button.dataset.sort;
        sortSelect.value = field + (sortSelect.value === field + "-desc" ? "-asc" : "-desc");
        applySort();
      }}));
      clearFilters.addEventListener("click", () => {{
        searchInput.value = "";
        yearSelect.value = "";
        applyFilters();
        searchInput.focus();
      }});
      applySort();
    </script>
  </body>
</html>
"""


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="Build standalone library/index.html.")
    parser.add_argument("--out", default=str(INDEX_HTML_PATH), help="Output HTML path.")
    args = parser.parse_args()

    papers = collect_papers()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(papers), encoding="utf-8", newline="\n")
    print(f"Wrote {repo_rel(out_path)} with {len(papers)} papers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
