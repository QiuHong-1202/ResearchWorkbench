---
name: paper-extract
description: |
  Use when the user asks to extract text and artifacts from an academic paper PDF.

  Triggers include: "extract paper", "提取论文", "提取 PDF", "extract PDF",
  "抽取论文", "PDF 转 Markdown", "格式化论文", "fulltext review".

  This skill extracts reusable artifacts (fulltext Markdown, page JSON,
  manifest, images) from a local PDF or arXiv link, performs deterministic
  Markdown cleanup, and then dispatches a SubAgent for LLM postprocess
  review to produce a clean fulltext.md ready for downstream skills
  (paper-note, paper-translate).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch, Agent
---

# Paper Extract

从 PDF 提取可复用的 Markdown 工件，并通过 LLM SubAgent 执行格式化 review。

## Fixed paths

以下路径都相对当前仓库根目录解析：

- `ARTIFACTS_ROOT = paper-notes/artifacts`
- `PAPERS_DIR = papers`（源 PDF 标准存放目录）
- LLM 后处理 prompt 模板：`assets/llm-postprocess-prompt-template.md`
- PDF 提取脚本：`scripts/extract_pdf.py`
- arXiv 下载脚本：`scripts/download_arxiv.py`
- Shell 包装脚本（macOS / Linux）：`scripts/run_extract_pdf.sh`
- PowerShell 包装脚本（Windows）：`scripts/run_extract_pdf.ps1`
- arXiv 下载包装脚本（Windows）：`scripts/run_download_arxiv.ps1`

所有 Python 调用都必须走仓库内的 `uv` 项目环境，不要直接调用裸 `python`。

## Accepted inputs

只接受两类输入：

1. **本地 PDF 路径**
2. **arXiv 链接**
   - 支持 `https://arxiv.org/abs/...`
   - 支持 `https://arxiv.org/pdf/...`
   - 支持裸 ID，如 `2501.12345`

当输入为 arXiv 链接时，执行 **arXiv 下载流程**（见 Workflow Step 0），将 PDF 下载到 `papers/` 目录并以标准格式 `YYYY - Title.pdf` 命名，然后再走统一的本地 PDF 流程。

## Workflow

### 0. Download arXiv PDF (when input is arXiv link)

当用户输入为 arXiv 链接时，运行下载脚本将 PDF 存入 `papers/` 目录。

**Windows：**

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\paper-extract\scripts\run_download_arxiv.ps1 "<ARXIV_LINK>" --papers-dir papers
```

**macOS / Linux：**

```bash
cd <REPO_ROOT> && uv run --project . python .agents/skills/paper-extract/scripts/download_arxiv.py "<ARXIV_LINK>" --papers-dir papers
```

脚本行为：
1. 从链接中解析 arXiv ID
2. 通过 arXiv API 获取论文元信息（标题、年份、作者）
3. 下载 PDF 并以 `YYYY - Title.pdf` 格式保存到 `papers/`
4. 输出 JSON 到 stdout，包含 `status`、`pdf_path`、`note_stem`、`metadata`

脚本输出的 JSON 结构：

```json
{
  "status": "downloaded",         // 或 "exists"（文件已存在）
  "pdf_path": "papers/2025 - Some Title.pdf",
  "note_stem": "2025 - Some Title",
  "metadata": {
    "arxiv_id": "2501.12345",
    "title": "Some Title",
    "year": 2025,
    "authors": ["Author A", "Author B"],
    "pdf_url": "https://arxiv.org/pdf/2501.12345.pdf"
  }
}
```

**成功时**：使用返回的 `pdf_path` 作为后续步骤的 PDF 输入路径，`note_stem` 直接作为 `NOTE_STEM`。

**文件已存在时**（`status: "exists"`）：同样使用已有文件的 `pdf_path` 和 `note_stem`，除非用户明确要求重新下载（此时加 `--overwrite`）。

**失败时**：停止并报告错误。

完成下载后，跳到 Step 1 继续。此时 `PDF_PATH` 和 `NOTE_STEM` 已确定，Step 1 中 NOTE_STEM 的推导可直接使用下载脚本返回的 `note_stem`。

---

### 1. Prepare output names

先基于以下优先级确定 `NOTE_STEM`：

1. 若 Step 0 已经返回了 `note_stem`（arXiv 下载场景），直接使用
2. 若输入 PDF 文件名已经符合 `YYYY - Title.pdf`，直接复用其 stem
3. 否则用"年份 + 标题"组装成 `YYYY - Title`
   - `年份` 优先取 PDF 文件名中的年份前缀
   - 取不到时，再参考论文元信息中的年份
   - `标题` 优先取论文标题；取不到再退回 PDF 文件名 stem
4. 如果仍然拿不到可靠年份，再退回 PDF 文件名 stem

命名要求：

- 优先与 `papers/` 目录中的源 PDF 保持同 stem，只把扩展名从 `.pdf` 改成 `.md`
- 转成适合 Windows 文件名的安全名字
- 同名时追加年份；还冲突就追加短哈希
- 最终输出工件目录：`paper-notes/artifacts/{NOTE_STEM}/`

### 2. Extract PDF artifacts

根据当前操作系统选择对应的包装脚本运行。两个脚本功能相同，都会自动把 `python` 固定到当前仓库的 `uv` 环境。

**macOS / Linux：**

```bash
bash .agents/skills/paper-extract/scripts/run_extract_pdf.sh --input "<PDF_PATH>" --out-dir "paper-notes/artifacts/{NOTE_STEM}"
```

**Windows：**

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\paper-extract\scripts\run_extract_pdf.ps1 --input "<PDF_PATH>" --out-dir "paper-notes/artifacts/{NOTE_STEM}"
```

工件目录布局：

```
paper-notes/artifacts/{NOTE_STEM}/
├── fulltext.md                        # 核心：Markdown 全文（图 / 表 / 版权归集到文末区块）
├── assets/                            # 元数据与后处理文件
│   ├── manifest.json
│   ├── pages.json
│   ├── _marker_meta.json              # marker 后端时生成
│   ├── llm-postprocess-prompt.md      # SubAgent 任务说明
│   └── llm-postprocess-report.md      # SubAgent review 报告
└── figs/                              # 提取的图片
    └── _page_*_*.jpeg
```

抽取脚本会对 Markdown 做轻量后处理：

- 首页出版 / 版权样板文本（例如 DOI、Received / accepted 时间线、IEEE / ACM 版权声明）会从正文中移到 `fulltext.md` 文末的 `## Copyright` 区块。
- 图片语法、被省略的图片占位符，以及可识别的 `Figure` / `Fig.` 图注会从正文中移到 `fulltext.md` 文末的 `## Figures` 区块。
- Markdown 管道表格、HTML `<table>` 表格，以及可识别的 `Table` / `Tab.` 表格标题会从正文中移到 `fulltext.md` 文末的 `## Tables` 区块。
- `assets/pages.json` 中的 `pages` 字段保存移除这些内容后的页文本；原始被移动内容保存在 `extracted_blocks.figures`、`extracted_blocks.tables` 和 `extracted_blocks.copyright`。
- `assets/manifest.json` 的 `relocated_block_counts` 会记录每类被移动条目的数量。
- marker 页锚点（例如 `<span id="page-17-25"></span>`）会被删除。
- 空 alt 的图片语法（例如 `![](figs/_page_0_Figure_7.jpeg)`）会按出现顺序补成 `![Figure N](figs/...)`。
- 只指向 marker 页锚点的引用链接（例如 `[\[78\]](#page-17-16)`）会简化为普通引用编号（例如 `[78]`）。
- 单行显示公式块（例如 `$$eq$$`）会规范为三行形式：`$$`、公式内容、`$$`。
- `assets/manifest.json.postprocess.deterministic` 会记录确定性清理规则和命中数量。

如果 `assets/manifest.json` 的 `status` 不是 `ok`，停止并向用户报告错误。

读取 `assets/manifest.json` 后检查 `warnings` 字段；如果存在非空警告（例如 marker-pdf 未安装、已回退到 pymupdf4llm），将警告内容告知用户。

### 3. LLM postprocess review

抽取成功后，检查 `assets/manifest.json.postprocess.llm_agent.status`：

- 若已经是 `done` 或 `skipped_no_change`：跳过 review，直接报告当前状态和 `assets/llm-postprocess-report.md` 内容。
- 若为 `prompt_ready`：继续执行 LLM review。

#### SubAgent 调度

使用 Agent / SubAgent 直接读取 `fulltext.md` 全文，用文件编辑工具（Read / Edit / Write）逐处修改。

**禁止 SubAgent 编写任何代码（Python、Bash、正则脚本等）来批量处理文件。** 所有修复必须由 SubAgent 阅读原文后，通过文件编辑工具逐条定位并替换完成。这是一个人工审阅任务，不是自动化脚本任务。

- SubAgent 的任务说明必须直接来自工件目录中的 `assets/llm-postprocess-prompt.md`，不要临时改写成论文总结任务。
- SubAgent 只应修改 `fulltext.md`、必要时同步修改 `assets/pages.json`、更新 `assets/manifest.json.postprocess.llm_agent`，并写入 `assets/llm-postprocess-report.md`。
- SubAgent 重点清理确定性规则未覆盖的 HTML 噪声、残留页码 / 页眉页脚、破碎引用、图片 alt / Figure 编号不一致、异常 heading level、断裂 DOI / 链接等格式问题；不得总结、翻译、扩写或改写论文内容。

#### Failure handling

- 若 SubAgent 启动失败，必须立刻对同一工件目录重试启动 1 次，继续使用同一个 `assets/llm-postprocess-prompt.md`。
- 若重试后仍无法启动 SubAgent，立即停止；最终回复告知用户 LLM review 未执行、失败发生在 SubAgent 启动阶段，并列出工件目录与 `assets/llm-postprocess-prompt.md` 路径，方便用户查看。
- 若 SubAgent 返回 `ERROR`、未正常完成、未写出 `assets/llm-postprocess-report.md`，或未把 `assets/manifest.json.postprocess.llm_agent.status` 更新为 `done` / `skipped_no_change`，立即停止；最终回复说明失败原因、当前 `llm_agent.status`、工件目录和 report / prompt 路径。

#### Validate completion

SubAgent 完成后，主 Agent 必须检查：

- `assets/llm-postprocess-report.md` 存在
- `assets/manifest.json.postprocess.llm_agent.status` 已更新为 `done` 或 `skipped_no_change`
- 快速检查改动是否只影响后处理范围（未删除正文内容）

#### No SubAgent fallback

若当前环境完全没有 Agent / SubAgent 工具能力，或更高优先级工具策略阻止自动启动 SubAgent：

- 不要把 `prompt_ready` 当作已 review。
- 立即停止并向用户说明："PDF 已抽取，但 LLM fulltext review 无法自动启动，因此尚未执行。"
- 报告工件目录、`assets/llm-postprocess-prompt.md` 路径，以及阻止启动的原因。

只有在用户明确要求跳过 LLM review 时，才可跳过此步骤。

## Final response

完成后，回复用户时必须给出：

- 工件目录路径
- `assets/manifest.json` 的 `status`
- `warnings`（如有）
- `postprocess.llm_agent.status`（`done` / `skipped_no_change`）
- `assets/llm-postprocess-report.md` 路径
- 提示用户可使用 `paper-note` skill 生成阅读笔记，或 `paper-translate` skill 生成中文翻译
