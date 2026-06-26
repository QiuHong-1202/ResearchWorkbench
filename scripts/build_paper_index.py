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
from pathlib import Path
from typing import Any
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_ROOT = REPO_ROOT / "library"
PAPERS_ROOT = LIBRARY_ROOT / "papers"
INDEX_HTML_PATH = LIBRARY_ROOT / "index.html"


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


def link(label: str, href: str, *, primary: bool = False) -> str:
    if not href:
        return f'<span class="missing">{html.escape(label)}</span>'
    cls = "link primary" if primary else "link"
    return f'<a class="{cls}" href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'


def collect_papers() -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
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
        if not supplements:
            supplements = '<span class="muted">None</span>'
        title = html.escape(paper["title"])
        year = html.escape(str(paper["year"] or ""))
        authors = html.escape(display_authors(paper["authors"]))
        search_text = html.escape(paper["search_text"], quote=True)
        rows.append(
            f'        <tr data-year="{year}" data-search="{search_text}">\n'
            f'          <td class="index">{index}</td>\n'
            f'          <td><div class="title">{title}</div><div class="authors">{authors}</div></td>\n'
            f'          <td class="year">{year}</td>\n'
            f'          <td class="actions">{link("Note", paper["note"], primary=True)}</td>\n'
            f'          <td class="actions">{link("PDF", paper["pdf"])}</td>\n'
            f'          <td class="actions">{link("Fulltext", paper["fulltext"])}</td>\n'
            f'          <td class="actions">{link("Translation", paper["translation"])}</td>\n'
            f'          <td class="actions">{supplements}</td>\n'
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
    <style>
      :root {{
        --bg: #f7f7f5;
        --panel: #ffffff;
        --text: #202421;
        --muted: #6f7772;
        --line: #d9ded7;
        --accent: #2f6f5d;
        --accent-soft: #e7f0ec;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
        line-height: 1.45;
      }}
      main {{
        width: min(1500px, calc(100vw - 28px));
        margin: 0 auto;
        padding: 24px 0 36px;
      }}
      header {{
        display: flex;
        justify-content: space-between;
        gap: 18px;
        align-items: end;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--line);
      }}
      h1 {{
        margin: 0;
        font-size: 26px;
        letter-spacing: 0;
      }}
      .meta {{
        color: var(--muted);
        font-size: 13px;
        margin-top: 5px;
      }}
      .count {{
        min-width: 96px;
        padding: 8px 12px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
        text-align: right;
      }}
      .count strong {{
        display: block;
        font-size: 22px;
      }}
      .table-wrap {{
        margin-top: 18px;
        overflow-x: auto;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
      }}
      .toolbar {{
        display: grid;
        grid-template-columns: minmax(260px, 1fr) 160px;
        gap: 10px;
        margin-top: 18px;
      }}
      input, select {{
        min-height: 40px;
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
        color: var(--text);
        padding: 0 11px;
        font: inherit;
      }}
      input:focus, select:focus {{
        outline: 2px solid rgba(47, 111, 93, 0.22);
        border-color: var(--accent);
      }}
      table {{
        width: 100%;
        min-width: 980px;
        border-collapse: collapse;
      }}
      th, td {{
        padding: 11px 12px;
        border-bottom: 1px solid var(--line);
        vertical-align: top;
        text-align: left;
      }}
      th {{
        position: sticky;
        top: 0;
        background: #f0f2ef;
        color: #3c443f;
        font-size: 12px;
        font-weight: 700;
      }}
      tr:last-child td {{ border-bottom: 0; }}
      .index, .year {{
        color: var(--muted);
        white-space: nowrap;
      }}
      .title {{
        font-weight: 650;
        max-width: 620px;
      }}
      .authors {{
        color: var(--muted);
        font-size: 12px;
        margin-top: 3px;
      }}
      .actions {{
        white-space: nowrap;
      }}
      .link, .missing {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 30px;
        border-radius: 8px;
        padding: 0 9px;
        font-size: 12px;
        font-weight: 650;
      }}
      .link {{
        border: 1px solid var(--line);
        color: var(--text);
        background: #ffffff;
        text-decoration: none;
      }}
      .link.primary {{
        border-color: var(--accent);
        background: var(--accent);
        color: #ffffff;
      }}
      .link + .link {{
        margin-left: 6px;
      }}
      .missing {{
        color: #9aa19b;
        background: #f1f3f0;
        border: 1px solid #e1e5df;
      }}
      .muted {{
        color: var(--muted);
        font-size: 12px;
      }}
      @media (max-width: 760px) {{
        header {{
          align-items: start;
          flex-direction: column;
        }}
        .count {{
          text-align: left;
        }}
        .toolbar {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <main>
      <header>
        <div>
          <h1>Paper Notes</h1>
          <div class="meta">Generated from local paper records. Open this file directly; no local server is required.</div>
        </div>
        <div class="count"><strong>{len(papers)}</strong><span class="meta">papers</span></div>
      </header>
      <section class="toolbar" aria-label="Filters">
        <input id="searchInput" type="search" placeholder="Search title or author">
        <select id="yearSelect" aria-label="Year filter">
          <option value="">All years</option>
{year_options}
        </select>
      </section>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Paper</th>
              <th>Year</th>
              <th>Note</th>
              <th>PDF</th>
              <th>Fulltext</th>
              <th>Translation</th>
              <th>Supplement</th>
            </tr>
          </thead>
          <tbody>
{rows}
          </tbody>
        </table>
      </div>
    </main>
    <script>
      const searchInput = document.getElementById("searchInput");
      const yearSelect = document.getElementById("yearSelect");
      const rows = Array.from(document.querySelectorAll("tbody tr"));
      const count = document.querySelector(".count strong");

      function applyFilters() {{
        const query = searchInput.value.trim().toLowerCase();
        const year = yearSelect.value;
        let visible = 0;
        rows.forEach((row) => {{
          const matchesSearch = !query || row.dataset.search.includes(query);
          const matchesYear = !year || row.dataset.year === year;
          const show = matchesSearch && matchesYear;
          row.hidden = !show;
          if (show) visible += 1;
        }});
        count.textContent = visible;
      }}

      searchInput.addEventListener("input", applyFilters);
      yearSelect.addEventListener("change", applyFilters);
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
