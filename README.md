# SnowmanResearch

轻量研究工作台，围绕两条主工作流组织：
1. 每日抓取并筛选 arXiv
2. 对选中的论文做结构化精读与笔记

本仓库将 repo-local skills、脚本入口和生成产物放在同一个目录体系里，便于持续追踪论文、复用抽取结果。

## Introduction

这个仓库当前包含两个核心 workflow：

- `arxiv-daily`
  从配置的 arXiv 分类抓取当天内容，跨分类去重、分批打分，最终生成每日推荐结果。
- `paper-reader`
  从本地 PDF 或 arXiv 论文出发，提取可复用 artifacts，并生成结构化 Markdown 论文笔记。

## Core Workflows

### 1. `arxiv-daily`

Purpose:

- 为你关注的 arXiv 分类生成当天推荐列表
- Keep a dated archive of raw fetch results, dedupe metadata, scoring batches, and final recommendations

Key entry points:

- Skill doc: [`.agents/skills/arxiv-daily/SKILL.md`](.agents/skills/arxiv-daily/SKILL.md)
- Config: [`.agents/skills/arxiv-daily/config.yaml`](.agents/skills/arxiv-daily/config.yaml)
- Outputs: [`arxiv-daily/`](arxiv-daily/)

Main knobs:

- `categories`: 要抓取的 arXiv 分类
- `interests.narrative`: 你的研究兴趣描述
- `score_threshold`: 推荐阈值
- `max_recommendations`: 推荐条数上限

### 2. `paper-reader`

Purpose:

- 从 PDF 中抽取 `fulltext.md`、`pages.json`、`manifest.json`
- Generate a structured Markdown note from the extracted artifacts

Key entry points:

- Skill doc: [`.agents/skills/paper-reader/SKILL.md`](.agents/skills/paper-reader/SKILL.md)
- PDFs folder: [`papers/`](papers/)
- Notes root: [`paper-notes/`](paper-notes/)
- Artifact root: [`paper-notes/artifacts/`](paper-notes/artifacts/)

Recommended convention:

- 将待读 PDF 放到 `papers/`
- 文件名尽量使用 `YYYY - Title.pdf`

## Prerequisites

- `uv`
- Python `>= 3.11`
- 若想走完整 assistant workflow，需要一个能读取仓库内 `.agents/skills` 的助手环境

First-time setup:

```bash
uv sync
```

所有 Python 相关脚本都应通过仓库内的 `uv` 项目环境运行。

## Quick Start

### Assistant-first

如果你的助手支持仓库内 skills，推荐直接用自然语言触发主流程。

For `arxiv-daily`:

- `用仓库里的 arxiv-daily skill 生成今天的 arXiv 推荐`
- `Generate today's arXiv recommendations with the repo-local arxiv-daily skill`

For `paper-reader`:

- `读一下 papers/<paper>.pdf，并按仓库模板生成论文笔记`
- `Read papers/<paper>.pdf and generate a structured note with the repo-local paper-reader skill`

### Manual entry points

脚本入口适合做“单步处理”或排查问题，但完整 workflow 仍以各自的 `SKILL.md` 为准。如遇到沙箱权限问题，可以先执行好脚本，让 Agent 直接读提取出的文档。

#### Paper artifact extraction

PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\paper-reader\scripts\run_extract_pdf.ps1 `
  --input "papers\<paper>.pdf" `
  --out-dir "paper-notes\artifacts\<note-stem>" `
  --overwrite
```

macOS / Linux:

```bash
bash .agents/skills/paper-reader/scripts/run_extract_pdf.sh \
  --input "papers/<paper>.pdf" \
  --out-dir "paper-notes/artifacts/<note-stem>" \
  --overwrite
```

这一步只负责生成抽取 artifacts；最终论文笔记通常仍由 Agent 按模板生成。

#### arXiv fetch + batch prep

PowerShell:

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

macOS / Linux:

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

这两步会生成当日抓取结果和评分批次。批次打分以及最终 `{date}-arxiv-recommended.md` 的写出，通常由 assistant 按 [`arxiv-daily` skill 文档](.agents/skills/arxiv-daily/SKILL.md) 完成。

Notes:

- `arxiv-daily` 的推荐质量依赖 `config.yaml` 中的兴趣描述与阈值设置

## Outputs

```text
arxiv-daily/
├─ {date}-arxiv-recommended.md
└─ {date}/
   ├─ {date}-arxiv-cs.CV.md
   ├─ {date}-arxiv-cs.CV.json
   ├─ {date}-manifest.json
   ├─ {date}-dedupe-meta.json
   └─ scoring-batches-{date}/

paper-notes/
├─ {note-stem}.md
└─ artifacts/
   └─ {note-stem}/
      ├─ fulltext.md
      ├─ pages.json
      └─ manifest.json

papers/
└─ local PDFs (git-ignored)
```

Output roles:

- `arxiv-daily/`: 每日发现与推荐结果
- `paper-notes/`: 最终笔记
- `paper-notes/artifacts/`: 供后续复用的抽取中间产物
- `papers/`: 本地 PDF 输入目录

## Repo Structure

```text
.
├─ .agents/
│  └─ skills/
│     ├─ arxiv-daily/
│     └─ paper-reader/
├─ arxiv-daily/
├─ paper-notes/
├─ papers/
├─ scripts/
├─ extract_pdf.ps1
├─ paper-reading-prompt.md
├─ pyproject.toml
└─ uv.lock
```

Notes:

- [`scripts/generate_paper_files.py`](scripts/generate_paper_files.py) 用于从单个 `note-stem` 更新根目录的便利文件
- [`extract_pdf.ps1`](extract_pdf.ps1) 是面向当前目标论文的快捷包装脚本
- [`paper-reading-prompt.md`](paper-reading-prompt.md) 是当前聚焦论文的 prompt 草稿，不是仓库主能力本身

## Further Docs

- [`arxiv-daily` skill](.agents/skills/arxiv-daily/SKILL.md)
- [`paper-reader` skill](.agents/skills/paper-reader/SKILL.md)
- [`arxiv-daily` config](.agents/skills/arxiv-daily/config.yaml)
- [`papers/README.md`](papers/README.md)
