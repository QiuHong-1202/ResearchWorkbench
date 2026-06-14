from __future__ import annotations

import json
from pathlib import Path


LLM_POSTPROCESS_PROMPT_NAME = "llm-postprocess-prompt.md"
LLM_POSTPROCESS_REPORT_NAME = "llm-postprocess-report.md"
_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "llm-postprocess-prompt-template.md"
)


def _render_prompt_template(
    *,
    fulltext_path: Path,
    pages_path: Path,
    manifest_path: Path,
    report_path: Path,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{FULLTEXT_PATH}}": str(fulltext_path),
        "{{PAGES_PATH}}": str(pages_path),
        "{{MANIFEST_PATH}}": str(manifest_path),
        "{{REPORT_PATH}}": str(report_path),
        "{{REPORT_PATH_JSON}}": json.dumps(
            str(report_path),
            ensure_ascii=False,
        ),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def write_llm_postprocess_prompt(
    assets_dir: Path,
    fulltext_path: Path,
    pages_path: Path,
    manifest_path: Path,
) -> Path:
    prompt_path = assets_dir / LLM_POSTPROCESS_PROMPT_NAME
    report_path = assets_dir / LLM_POSTPROCESS_REPORT_NAME
    prompt = _render_prompt_template(
        fulltext_path=fulltext_path,
        pages_path=pages_path,
        manifest_path=manifest_path,
        report_path=report_path,
    )
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path
