# ResearchWorkbench

轻量研究工作台，围绕 arXiv 发现、论文全文抽取、结构化笔记、全文翻译和本地论文库索引组织 repo-local skills 与脚本入口。

本仓库只跟踪工具链、模板和目录占位文件。PDF、推荐结果、抽取 artifacts、review/cookie/scratch 等个人或生成内容默认不提交；论文记录中建议只提交适合公开的 `paper.json` 与 `note.md`。

## Workflows

### Typical full paper workflow

如果助手环境同时支持 Zotero 和本仓库的 repo-local skills，可以用下面的提示串联完整处理流程：

```text
@zotero 提取 Zotero 文库中的文章：
${paper_name}
的论文和补充材料（如有）全文

按顺序执行以下步骤，如果文件已经存在、某个步骤失败、找不到 PDF、需要进一步批准，请停止流程让我 Debug：
- 使用 $paper-extract Skill，使用这个 Skill 的时候，批准使用 SubAgent 进行 LLM Review
- 使用 $formula-fix Skill 修复公式
- 使用 $markdown-fix Skill 修复 OCR 错误
- 使用 $paper-translate Skill 生成中文全文翻译
- 使用 $paper-note Skill 生成笔记
- 运行 `uv run --project . python scripts/build_paper_index.py` 更新本地论文库索引
```

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

### Optional: `archive-arxiv-recommendations`

把 `arxiv-daily/recommendations/` 中非当月的推荐文件移动到 `archive/YYYY-MM/`，保持根目录只放当月推荐。

Key entry point:

- Skill doc: [`.agents/skills/archive-arxiv-recommendations/SKILL.md`](.agents/skills/archive-arxiv-recommendations/SKILL.md)

Dry-run first:

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\archive-arxiv-recommendations\scripts\run_archive.ps1 --dry-run
```

```bash
bash .agents/skills/archive-arxiv-recommendations/scripts/run_archive.sh --dry-run
```

The archive helper does not run `git add`, `git mv`, `git commit`, or `git push`.

### 2. `paper-extract`

从本地 PDF 或 arXiv 链接生成可复用论文记录：`paper.json`、`fulltext.md`、`assets/pages.json`、`assets/manifest.json`、LLM 后处理 prompt，以及 marker-pdf 后端可选的图片与元数据。

Key entry points:

- Skill doc: [`.agents/skills/paper-extract/SKILL.md`](.agents/skills/paper-extract/SKILL.md)
- Extract script: [`.agents/skills/paper-extract/scripts/extract_pdf.py`](.agents/skills/paper-extract/scripts/extract_pdf.py)
- arXiv download script: [`.agents/skills/paper-extract/scripts/download_arxiv.py`](.agents/skills/paper-extract/scripts/download_arxiv.py)
- Paper record root: `library/papers/`

Manual extraction:

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\paper-extract\scripts\run_extract_pdf.ps1 `
  --input "papers\<paper>.pdf" `
  --out-dir "library\papers\<paper-stem>" `
  --overwrite
```

```bash
bash .agents/skills/paper-extract/scripts/run_extract_pdf.sh \
  --input "papers/<paper>.pdf" \
  --out-dir "library/papers/<paper-stem>" \
  --overwrite
```

### 3. `formula-fix` and `markdown-fix`

对 `paper-extract` 产出的 Markdown 全文做人工审阅式清理：

- `formula-fix`：把 OCR / PDF 抽取中未标准化的公式片段转换为 LaTeX。
- `markdown-fix`：修复标题层级、散落 OCR 字符、乱码、破碎列表和断词等结构噪声。

Key entry points:

- Skill doc: [`.agents/skills/formula-fix/SKILL.md`](.agents/skills/formula-fix/SKILL.md)
- Skill doc: [`.agents/skills/markdown-fix/SKILL.md`](.agents/skills/markdown-fix/SKILL.md)

### 4. `paper-note`

基于 `paper-extract` 产出的论文记录目录生成结构化中文论文笔记。

Key entry points:

- Skill doc: [`.agents/skills/paper-note/SKILL.md`](.agents/skills/paper-note/SKILL.md)
- Note template: [`.agents/skills/paper-note/assets/paper-note-template.md`](.agents/skills/paper-note/assets/paper-note-template.md)
- Output note: `library/papers/{paper-stem}/note.md`

### 5. `paper-translate`

将 `paper-extract` 产出的 `fulltext.md` 翻译为简体中文，输出到同一记录目录的 `fulltext.zh-CN.md`。

Key entry point:

- Skill doc: [`.agents/skills/paper-translate/SKILL.md`](.agents/skills/paper-translate/SKILL.md)

### 6. Paper library index

从 `library/papers/*/paper.json` 和 `note.md` 生成自包含静态索引页面：

```bash
uv run --project . python scripts/build_paper_index.py
```

然后直接用浏览器打开 `library/index.html`；该页面不需要本地服务器。

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
uv run --project . python scripts/generate_paper_files.py "2026 - My Paper Title"
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

library/
├─ index.html
└─ papers/
   └─ {paper-stem}/
      ├─ paper.json
      ├─ note.md
      ├─ fulltext.md
      ├─ fulltext.zh-CN.md
      ├─ assets/
      │  ├─ manifest.json
      │  ├─ pages.json
      │  ├─ llm-postprocess-prompt.md
      │  └─ llm-postprocess-report.md
      ├─ figs/
      └─ supplements/

papers/
└─ local PDFs (git-ignored)
```

## Repo Structure

```text
.
├─ .agents/
│  └─ skills/
│     ├─ archive-arxiv-recommendations/
│     ├─ arxiv-daily/
│     ├─ formula-fix/
│     ├─ markdown-fix/
│     ├─ paper-extract/
│     ├─ paper-note/
│     └─ paper-translate/
├─ arxiv-daily/
├─ library/
├─ papers/
├─ review/
├─ scripts/
├─ pyproject.toml
└─ uv.lock
```

## Further Docs

- [`arxiv-daily` skill](.agents/skills/arxiv-daily/SKILL.md)
- [`archive-arxiv-recommendations` skill](.agents/skills/archive-arxiv-recommendations/SKILL.md)
- [`formula-fix` skill](.agents/skills/formula-fix/SKILL.md)
- [`markdown-fix` skill](.agents/skills/markdown-fix/SKILL.md)
- [`paper-extract` skill](.agents/skills/paper-extract/SKILL.md)
- [`paper-note` skill](.agents/skills/paper-note/SKILL.md)
- [`paper-translate` skill](.agents/skills/paper-translate/SKILL.md)
- [`arxiv-daily` config template](.agents/skills/arxiv-daily/config.template.yaml)
- [`papers/README.md`](papers/README.md)
