#!/usr/bin/env python3
"""Generate repo-root paper-reading-prompt.md and update extract_pdf.ps1 from a single note stem.

paper-reading-prompt.md is overwritten from scripts/paper-reading-prompt.template.md
({{paper_name}} placeholder). extract_pdf.ps1 is updated in
place: either only the $NoteStem assignment line (legacy script), or only the
quoted paths after --input and --out-dir (short wrapper that calls
run_extract_pdf.ps1). If the file is missing or neither pattern applies, a short
wrapper script is written.

The note stem must match the PDF basename under papers/ (without .pdf) and the
artifacts directory name under paper-notes/artifacts/.

Usage:
  python scripts/generate_paper_files.py "2026 - My Paper Title"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def escape_powershell_single_quoted(value: str) -> str:
    """Escape for a PowerShell single-quoted string (double any ')."""
    return value.replace("'", "''")


def escape_powershell_double_quoted(value: str) -> str:
    """Escape for embedding in a PowerShell double-quoted string."""
    return value.replace("`", "``").replace("$", "`$").replace('"', '`"')


def paper_reading_prompt_template_file() -> Path:
    return Path(__file__).resolve().parent / "paper-reading-prompt.template.md"


DRAFT_PLACEHOLDER = "{{paper_name}}"
INPUT_PDF_PLACEHOLDER = "{{input_pdf}}"
OUTPUT_DIR_PLACEHOLDER = "{{output_dir}}"

_NOTE_STEM_LINE = re.compile(r"^(\s*)\$NoteStem\s*=.*$", re.MULTILINE)
_INPUT_ARG_RE = re.compile(r'(--input\s+")([^"]*)(")', re.IGNORECASE)
_OUT_DIR_ARG_RE = re.compile(r'(--out-dir\s+")([^"]*)(")', re.IGNORECASE)
_LEADING_TEMPLATE_HTML_COMMENT = re.compile(r"^\s*<!--.*?-->\s*\n?")

INVOKE_PS1_TEMPLATE = r"""powershell -ExecutionPolicy Bypass -File .\.claude\skills\paper-reader\scripts\run_extract_pdf.ps1 `
  --input "{{input_pdf}}" `
  --out-dir "{{output_dir}}" `
  --overwrite
"""


def render_paper_reading_prompt(note_stem: str) -> str:
    template = paper_reading_prompt_template_file().read_text(encoding="utf-8")
    template = _LEADING_TEMPLATE_HTML_COMMENT.sub("", template, count=1)
    return template.replace(DRAFT_PLACEHOLDER, note_stem)


def note_stem_ps1_line(note_stem: str) -> str:
    inner = escape_powershell_single_quoted(note_stem)
    return f"$NoteStem = '{inner}'"


def _invoke_paths_quoted(note_stem: str) -> tuple[str, str]:
    inp = escape_powershell_double_quoted(f"papers\\{note_stem}.pdf")
    out = escape_powershell_double_quoted(f"paper-notes\\artifacts\\{note_stem}")
    return inp, out


def update_extract_ps1_invoke_paths(content: str, note_stem: str) -> str:
    """Replace only --input / --out-dir quoted path values; preserve the rest."""
    inp, out = _invoke_paths_quoted(note_stem)

    def sub_input(m: re.Match[str]) -> str:
        return f"{m.group(1)}{inp}{m.group(3)}"

    def sub_out(m: re.Match[str]) -> str:
        return f"{m.group(1)}{out}{m.group(3)}"

    updated = _INPUT_ARG_RE.sub(sub_input, content, count=1)
    return _OUT_DIR_ARG_RE.sub(sub_out, updated, count=1)


def render_invoke_ps1(note_stem: str) -> str:
    inp, out = _invoke_paths_quoted(note_stem)
    return (
        INVOKE_PS1_TEMPLATE
        .replace(INPUT_PDF_PLACEHOLDER, inp)
        .replace(OUTPUT_DIR_PLACEHOLDER, out)
    )


def update_extract_ps1(content: str, note_stem: str) -> str:
    """Update only title/path fragments; preserve script structure."""
    if _NOTE_STEM_LINE.search(content):
        line = note_stem_ps1_line(note_stem)
        return _NOTE_STEM_LINE.sub(lambda m: f"{m.group(1)}{line}", content, count=1)
    if _INPUT_ARG_RE.search(content) or _OUT_DIR_ARG_RE.search(content):
        return update_extract_ps1_invoke_paths(content, note_stem)
    return render_invoke_ps1(note_stem)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Overwrite paper-reading-prompt.md from scripts/paper-reading-prompt.template.md; "
            "in extract_pdf.ps1 replace only $NoteStem or the --input / --out-dir paths; "
            "otherwise write the short run_extract_pdf.ps1 wrapper. note_stem must match "
            "papers/<stem>.pdf and paper-notes/artifacts/<stem>."
        )
    )
    parser.add_argument(
        "note_stem",
        help='Note / path stem, e.g. "2026 - My Paper Title"',
    )
    args = parser.parse_args()
    note_stem = args.note_stem.strip()
    if not note_stem:
        parser.error("note_stem must not be empty")

    repo_root = Path(__file__).resolve().parent.parent
    prompt_path = repo_root / "paper-reading-prompt.md"
    ps1_path = repo_root / "extract_pdf.ps1"

    prompt_path.write_text(
        render_paper_reading_prompt(note_stem),
        encoding="utf-8",
        newline="\n",
    )

    ps1_text = ps1_path.read_text(encoding="utf-8") if ps1_path.is_file() else ""
    ps1_path.write_text(update_extract_ps1(ps1_text, note_stem), encoding="utf-8", newline="\n")
    print(f"Updated {prompt_path} and {ps1_path}")


if __name__ == "__main__":
    main()
