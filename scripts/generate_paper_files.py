#!/usr/bin/env python3
"""Generate repo-root paper-reading-prompt.md, extract_pdf.ps1, and extract_pdf.sh from a single paper stem.

paper-reading-prompt.md is overwritten from scripts/paper-reading-prompt.template.md
({{paper_name}} placeholder). extract_pdf.ps1 and extract_pdf.sh are updated
in place by replacing the quoted paths after --input and --out-dir in the
short wrapper that calls run_extract_pdf.ps1 / run_extract_pdf.sh. If a file is
missing or neither pattern applies, a short wrapper script is written.

The paper stem must match the PDF basename under papers/ (without .pdf) and the
record directory name under library/papers/.

Usage:
  python scripts/generate_paper_files.py "2026 - My Paper Title"
"""

from __future__ import annotations

import argparse
import os
import re
import stat
from pathlib import Path


def escape_powershell_single_quoted(value: str) -> str:
    """Escape for a PowerShell single-quoted string (double any ')."""
    return value.replace("'", "''")


def escape_powershell_double_quoted(value: str) -> str:
    """Escape for embedding in a PowerShell double-quoted string."""
    return value.replace("`", "``").replace("$", "`$").replace('"', '`"')


def escape_bash_double_quoted(value: str) -> str:
    """Escape for embedding in a Bash double-quoted string."""
    return value.replace("\\", "\\\\").replace("$", "\\$").replace("`", "\\`").replace('"', '\\"').replace("!", "\\!")


def paper_reading_prompt_template_file() -> Path:
    return Path(__file__).resolve().parent / "paper-reading-prompt.template.md"


DRAFT_PLACEHOLDER = "{{paper_name}}"
INPUT_PDF_PLACEHOLDER = "{{input_pdf}}"
OUTPUT_DIR_PLACEHOLDER = "{{output_dir}}"

_INPUT_ARG_RE = re.compile(r'(--input\s+")([^"]*)(")', re.IGNORECASE)
_OUT_DIR_ARG_RE = re.compile(r'(--out-dir\s+")([^"]*)(")', re.IGNORECASE)
_LEADING_TEMPLATE_HTML_COMMENT = re.compile(r"^\s*<!--.*?-->\s*\n?")

INVOKE_PS1_TEMPLATE = r"""powershell -ExecutionPolicy Bypass -File .\.agents\skills\paper-extract\scripts\run_extract_pdf.ps1 `
  --input "{{input_pdf}}" `
  --out-dir "{{output_dir}}" `
  --overwrite
"""

INVOKE_SH_TEMPLATE = r"""#!/usr/bin/env bash
set -euo pipefail

.agents/skills/paper-extract/scripts/run_extract_pdf.sh \
  --input "{{input_pdf}}" \
  --out-dir "{{output_dir}}" \
  --overwrite
"""


def render_paper_reading_prompt(paper_stem: str) -> str:
    template = paper_reading_prompt_template_file().read_text(encoding="utf-8")
    template = _LEADING_TEMPLATE_HTML_COMMENT.sub("", template, count=1)
    return template.replace(DRAFT_PLACEHOLDER, paper_stem)


def _invoke_paths_quoted(paper_stem: str) -> tuple[str, str]:
    inp = escape_powershell_double_quoted(f"papers\\{paper_stem}.pdf")
    out = escape_powershell_double_quoted(f"library\\papers\\{paper_stem}")
    return inp, out


def update_extract_ps1_invoke_paths(content: str, paper_stem: str) -> str:
    """Replace only --input / --out-dir quoted path values; preserve the rest."""
    inp, out = _invoke_paths_quoted(paper_stem)

    def sub_input(m: re.Match[str]) -> str:
        return f"{m.group(1)}{inp}{m.group(3)}"

    def sub_out(m: re.Match[str]) -> str:
        return f"{m.group(1)}{out}{m.group(3)}"

    updated = _INPUT_ARG_RE.sub(sub_input, content, count=1)
    return _OUT_DIR_ARG_RE.sub(sub_out, updated, count=1)


def render_invoke_ps1(paper_stem: str) -> str:
    inp, out = _invoke_paths_quoted(paper_stem)
    return (
        INVOKE_PS1_TEMPLATE
        .replace(INPUT_PDF_PLACEHOLDER, inp)
        .replace(OUTPUT_DIR_PLACEHOLDER, out)
    )


def _invoke_sh_paths_quoted(paper_stem: str) -> tuple[str, str]:
    inp = escape_bash_double_quoted(f"papers/{paper_stem}.pdf")
    out = escape_bash_double_quoted(f"library/papers/{paper_stem}")
    return inp, out


_SH_INPUT_ARG_RE = re.compile(r'(--input\s+")([^"]*)(")')
_SH_OUT_DIR_ARG_RE = re.compile(r'(--out-dir\s+")([^"]*)(")')


def update_extract_sh_invoke_paths(content: str, paper_stem: str) -> str:
    inp, out = _invoke_sh_paths_quoted(paper_stem)

    def sub_input(m: re.Match[str]) -> str:
        return f"{m.group(1)}{inp}{m.group(3)}"

    def sub_out(m: re.Match[str]) -> str:
        return f"{m.group(1)}{out}{m.group(3)}"

    updated = _SH_INPUT_ARG_RE.sub(sub_input, content, count=1)
    return _SH_OUT_DIR_ARG_RE.sub(sub_out, updated, count=1)


def render_invoke_sh(paper_stem: str) -> str:
    inp, out = _invoke_sh_paths_quoted(paper_stem)
    return (
        INVOKE_SH_TEMPLATE
        .replace(INPUT_PDF_PLACEHOLDER, inp)
        .replace(OUTPUT_DIR_PLACEHOLDER, out)
    )


def update_extract_sh(content: str, paper_stem: str) -> str:
    if _SH_INPUT_ARG_RE.search(content) or _SH_OUT_DIR_ARG_RE.search(content):
        return update_extract_sh_invoke_paths(content, paper_stem)
    return render_invoke_sh(paper_stem)


def update_extract_ps1(content: str, paper_stem: str) -> str:
    """Update wrapper paths; preserve script structure."""
    if _INPUT_ARG_RE.search(content) or _OUT_DIR_ARG_RE.search(content):
        return update_extract_ps1_invoke_paths(content, paper_stem)
    return render_invoke_ps1(paper_stem)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Overwrite paper-reading-prompt.md from scripts/paper-reading-prompt.template.md; "
            "in extract_pdf.ps1 / extract_pdf.sh replace the --input / --out-dir paths; "
            "otherwise write short wrapper scripts. paper_stem "
            "must match papers/<stem>.pdf and library/papers/<stem>."
        )
    )
    parser.add_argument(
        "paper_stem",
        help='Paper / path stem, e.g. "2026 - My Paper Title"',
    )
    args = parser.parse_args()
    paper_stem = args.paper_stem.strip()
    if not paper_stem:
        parser.error("paper_stem must not be empty")

    repo_root = Path(__file__).resolve().parent.parent
    prompt_path = repo_root / "paper-reading-prompt.md"
    ps1_path = repo_root / "extract_pdf.ps1"
    sh_path = repo_root / "extract_pdf.sh"

    prompt_path.write_text(
        render_paper_reading_prompt(paper_stem),
        encoding="utf-8",
        newline="\n",
    )

    ps1_text = ps1_path.read_text(encoding="utf-8") if ps1_path.is_file() else ""
    ps1_path.write_text(update_extract_ps1(ps1_text, paper_stem), encoding="utf-8", newline="\n")

    sh_text = sh_path.read_text(encoding="utf-8") if sh_path.is_file() else ""
    sh_path.write_text(update_extract_sh(sh_text, paper_stem), encoding="utf-8", newline="\n")
    os.chmod(sh_path, sh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Updated {prompt_path}, {ps1_path}, and {sh_path}")


if __name__ == "__main__":
    main()
