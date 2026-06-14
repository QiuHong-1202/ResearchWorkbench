# ResearchWorkbench

轻量研究工作台，围绕 arXiv 发现、论文全文抽取、结构化笔记和全文翻译组织 repo-local skills 与脚本入口。

本仓库只跟踪工具链、模板和目录占位文件。PDF、论文笔记、推荐结果、抽取 artifacts、review/cookie/scratch 等个人或生成内容默认不提交。

## Workflows

### 1. `arxiv-daily`

从配置的 arXiv 分类抓取论文，跨分类去重，分批打分，并在 `arxiv-daily/recommendations/` 生成每日推荐文件。

Key entry points:

- Skill doc: [`.agents/skills/arxiv-daily/SKILL.md`](.agents/skills/arxiv-daily/SKILL.md)
- Config template: [`.agents/skills/arxiv-daily/config.template.yaml`](.agents/skills/arxiv-daily/config.template.yaml)
- Artifacts root: `arxiv-daily/artifacts/`
- Recommendations root: `arxiv-daily/recommendations/`

First-time config:

```bash
cp .agents/skills/arxiv-daily/config.template.yaml .agents/skills/arxiv-daily/config.yaml
```

Then edit `config.yaml` locally. It is ignored because it contains personal research interests.

Manual fetch and batch prep:

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\arxiv-daily\scripts\run_fetch.ps1 `
  --config .\.agents\skills\arxiv-daily\config.yaml `
  --out-dir arxiv-daily
```

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\arxiv-daily\scripts\run_prepare_batches.ps1 `
  --config .\.agents\skills\arxiv-daily\config.yaml `
  --out-dir arxiv-daily `
  --date {date}
```

```bash
bash .agents/skills/arxiv-daily/scripts/run_fetch.sh \
  --config .agents/skills/arxiv-daily/config.yaml \
  --out-dir arxiv-daily
```

```bash
bash .agents/skills/arxiv-daily/scripts/run_prepare_batches.sh \
  --config .agents/skills/arxiv-daily/config.yaml \
  --out-dir arxiv-daily \
  --date {date}
```

### 2. `paper-extract`

从本地 PDF 或 arXiv 链接生成可复用 artifacts：`fulltext.md`、`assets/pages.json`、`assets/manifest.json`、LLM 后处理 prompt，以及 marker-pdf 后端可选的图片与元数据。

Key entry points:

- Skill doc: [`.agents/skills/paper-extract/SKILL.md`](.agents/skills/paper-extract/SKILL.md)
- Extract script: [`.agents/skills/paper-extract/scripts/extract_pdf.py`](.agents/skills/paper-extract/scripts/extract_pdf.py)
- arXiv download script: [`.agents/skills/paper-extract/scripts/download_arxiv.py`](.agents/skills/paper-extract/scripts/download_arxiv.py)
- Artifacts root: `paper-notes/artifacts/`

Manual extraction:

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\paper-extract\scripts\run_extract_pdf.ps1 `
  --input "papers\<paper>.pdf" `
  --out-dir "paper-notes\artifacts\<note-stem>" `
  --overwrite
```

```bash
bash .agents/skills/paper-extract/scripts/run_extract_pdf.sh \
  --input "papers/<paper>.pdf" \
  --out-dir "paper-notes/artifacts/<note-stem>" \
  --overwrite
```

### 3. `paper-note`

基于 `paper-extract` 产出的 artifacts 生成结构化中文论文笔记。

Key entry points:

- Skill doc: [`.agents/skills/paper-note/SKILL.md`](.agents/skills/paper-note/SKILL.md)
- Note template: [`.agents/skills/paper-note/assets/paper-note-template.md`](.agents/skills/paper-note/assets/paper-note-template.md)
- Notes root: `paper-notes/`

### 4. `paper-translate`

将 `paper-extract` 产出的 `fulltext.md` 翻译为简体中文，输出到同一 artifact 目录的 `fulltext.zh-CN.md`。

Key entry point:

- Skill doc: [`.agents/skills/paper-translate/SKILL.md`](.agents/skills/paper-translate/SKILL.md)

## Prerequisites

- `uv`
- Python `>= 3.11`
- 一个能读取仓库内 `.agents/skills` 的 assistant 环境

Default install:

```bash
uv sync
```

Optional marker-pdf backend:

```bash
uv sync --extra marker
```

所有 Python 脚本都应通过仓库内的 `uv` 项目环境运行。

## Helper Script

生成当前论文的根目录 prompt 和快捷抽取脚本：

```bash
uv run python scripts/generate_paper_files.py "2026 - My Paper Title"
```

该命令会更新被 Git 忽略的 `paper-reading-prompt.md`、`extract_pdf.ps1` 和 `extract_pdf.sh`。

## Outputs

```text
arxiv-daily/
├─ artifacts/
│  └─ {date}/
│     ├─ {date}-arxiv-cs.CV.md
│     ├─ {date}-arxiv-cs.CV.json
│     ├─ {date}-manifest.json
│     ├─ {date}-dedupe-meta.json
│     └─ scoring-batches-{date}/
└─ recommendations/
   └─ {date}-arxiv-recommended.md

paper-notes/
├─ {note-stem}.md
└─ artifacts/
   └─ {note-stem}/
      ├─ fulltext.md
      ├─ assets/
      │  ├─ manifest.json
      │  ├─ pages.json
      │  ├─ llm-postprocess-prompt.md
      │  └─ llm-postprocess-report.md
      └─ figs/

papers/
└─ local PDFs (git-ignored)
```

## Repo Structure

```text
.
├─ .agents/
│  └─ skills/
│     ├─ arxiv-daily/
│     ├─ paper-extract/
│     ├─ paper-note/
│     └─ paper-translate/
├─ arxiv-daily/
├─ paper-notes/
├─ papers/
├─ review/
├─ scripts/
├─ pyproject.toml
└─ uv.lock
```

## Further Docs

- [`arxiv-daily` skill](.agents/skills/arxiv-daily/SKILL.md)
- [`paper-extract` skill](.agents/skills/paper-extract/SKILL.md)
- [`paper-note` skill](.agents/skills/paper-note/SKILL.md)
- [`paper-translate` skill](.agents/skills/paper-translate/SKILL.md)
- [`arxiv-daily` config template](.agents/skills/arxiv-daily/config.template.yaml)
- [`papers/README.md`](papers/README.md)
