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

- `RECORDS_ROOT = library/papers`
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

当本地 PDF 是从 Zotero 附件解析得到的路径（通常位于 `Zotero/storage/...`）时，必须先执行 **Zotero PDF 本地化流程**（见 Workflow Step 0A），把真实 PDF 文件复制到仓库 `papers/` 目录。后续提取必须使用仓库副本，不得直接从 Zotero storage 路径提取。

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
4. 输出 JSON 到 stdout，包含 `status`、`pdf_path`、`paper_stem`、`metadata`

成功时使用返回的 `pdf_path` 作为后续步骤的 PDF 输入路径，`paper_stem` 作为 `PAPER_STEM`。

### 0A. Localize Zotero attachment PDF (when input comes from Zotero)

当 PDF 路径由 Zotero 附件获得时，先把附件复制到仓库本地，再执行任何抽取：

1. 确认 Zotero 附件路径存在且后缀为 `.pdf`。
2. 按 Step 1 的命名规则确定 `PAPER_STEM`，目标路径固定为 `papers/{PAPER_STEM}.pdf`。
   - 若 Zotero 附件文件名已经符合 `YYYY - Title.pdf`，优先复用其 stem。
   - 补充材料使用与主论文一致的 stem 和明确后缀，例如 `papers/{PAPER_STEM} supplementary.pdf`。
3. 目标文件不存在时，执行真实文件复制（不要创建符号链接）：

**Windows：**

```powershell
Copy-Item -LiteralPath "<ZOTERO_PDF_PATH>" -Destination "papers/{PAPER_STEM}.pdf"
```

**macOS / Linux：**

```bash
cp -- "<ZOTERO_PDF_PATH>" "papers/{PAPER_STEM}.pdf"
```

4. 复制后比较源文件与仓库副本的字节大小和 SHA-256；只有两者一致才可继续。
5. 若目标文件已存在：
   - SHA-256 一致：直接复用仓库副本。
   - SHA-256 不一致：停止并报告冲突，不得自动覆盖现有仓库 PDF。
6. 从此步骤起，将仓库副本 `papers/{PAPER_STEM}.pdf` 作为唯一 `PDF_PATH`。生成或更新 `paper.json` 时，`source` 与 `pdf_path` 都必须写仓库相对路径，不得写 Zotero storage 的绝对路径。

### 1. Prepare record directory

先基于以下优先级确定 `PAPER_STEM`：

1. 若 Step 0 已返回 `paper_stem`（arXiv 下载场景），直接使用
2. 若输入 PDF 文件名已经符合 `YYYY - Title.pdf`，直接复用其 stem
3. 否则用“年份 + 标题”组装成 `YYYY - Title`
   - 年份优先取 PDF 文件名中的年份前缀
   - 取不到时，再参考论文元信息中的年份
   - 标题优先取论文标题；取不到再退回 PDF 文件名 stem
4. 如果仍然拿不到可靠年份，再退回 PDF 文件名 stem

命名要求：

- 优先与 `papers/` 目录中的源 PDF 保持同 stem
- 转成适合 Windows 文件名的安全名字
- 同名时追加短后缀或短哈希
- 最终论文记录目录：`library/papers/{PAPER_STEM}/`

如果用户明确说明当前 PDF 是某篇论文的补充材料，则不要建立顶层 record；输出到该论文记录下：

```text
library/papers/{PAPER_STEM}/supplements/{SUPPLEMENT_LABEL}/
```

默认补充材料 label 使用 `supplementary-material`。

### 2. Extract PDF artifacts

根据当前操作系统选择对应的包装脚本运行。两个脚本功能相同，都会自动把 `python` 固定到当前仓库的 `uv` 环境。

#### 超时

运行提取 PDF 脚本时，显式将外层命令超时设为至少 5 分钟（`300000 ms` / `300 s`；大文件可更长），不得依赖模型或工具的默认值。`yield` / 轮询间隔不等同于命令超时，应保留同一进程句柄继续等待。若仍然超时，先检查进程状态与 `assets/manifest.json`，再判断提取是否失败。

**macOS / Linux：**

```bash
bash .agents/skills/paper-extract/scripts/run_extract_pdf.sh --input "<PDF_PATH>" --out-dir "library/papers/{PAPER_STEM}"
```

**Windows：**

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\paper-extract\scripts\run_extract_pdf.ps1 --input "<PDF_PATH>" --out-dir "library/papers/{PAPER_STEM}"
```

记录目录布局：

```text
library/papers/{PAPER_STEM}/
├── paper.json                         # 小型元数据入口，供静态 index.html 生成使用
├── note.md                            # paper-note 后续生成；paper-extract 不覆盖它
├── fulltext.md                        # 核心：Markdown 全文（图 / 表 / 版权归集到文末区块）
├── fulltext.zh-CN.md                  # paper-translate 后续生成；paper-extract 不覆盖它
├── assets/
│   ├── manifest.json
│   ├── pages.json
│   ├── _marker_meta.json              # marker 后端时生成
│   ├── llm-postprocess-prompt.md      # SubAgent 任务说明
│   └── llm-postprocess-report.md      # SubAgent review 报告
└── figs/
    └── _page_*_*.jpeg
```

`--overwrite` 只用于刷新 `fulltext.md`、`assets/`、`figs/` 这些抽取生成物；不要删除 `note.md`、`paper.json` 或 `fulltext.zh-CN.md`。

抽取脚本会生成或更新 `paper.json`，至少包含：

- `paper_stem`
- `title`
- `year`
- `authors`
- `venue`
- `tags`
- `status`
- `source`
- `pdf_path`
- `note_path`
- `fulltext_path`
- `translation_path`
- `manifest_path`
- `pages_path`
- `supplements`

若原始附件来自 Zotero，抽取后必须再次确认 `paper.json.source` 和 `paper.json.pdf_path` 都指向 Step 0A 生成的仓库副本。HTML 索引或笔记中的 PDF 链接也必须使用该仓库相对路径。

抽取脚本会对 Markdown 做轻量后处理：

- 首页出版 / 版权样板文本会移到 `fulltext.md` 文末的 `## Copyright` 区块。
- 图片语法、图片占位符、可识别 Figure 图注会移到 `## Figures` 区块。
- Markdown 管道表格、HTML `<table>` 表格、可识别 Table 标题会移到 `## Tables` 区块。
- `assets/pages.json` 保存移除这些内容后的页文本；原始被移动内容保存在 `extracted_blocks`。
- `assets/manifest.json.relocated_block_counts` 记录每类被移动条目的数量。
- marker 页锚点会被删除，页锚点引用会简化为空间普通引用编号。
- 空 alt 图片语法会按出现顺序补成 `![Figure N](figs/...)`。
- 单行显示公式块会规范为三行形式。
- `assets/manifest.json.postprocess.deterministic` 记录确定性清理规则和命中数量。

如果 `assets/manifest.json.status` 不是 `ok`，停止并向用户报告错误。

读取 `assets/manifest.json` 后检查 `warnings` 字段；如果存在非空警告，将警告内容告知用户。

### 3. LLM postprocess review

抽取成功后，检查 `assets/manifest.json.postprocess.llm_agent.status`：

- 若已经是 `done` 或 `skipped_no_change`：跳过 review，直接报告当前状态和 `assets/llm-postprocess-report.md` 内容。
- 若为 `prompt_ready`：继续执行 LLM review。

#### SubAgent 调度

使用 Agent / SubAgent 直接读取 `fulltext.md` 全文，用文件编辑工具（Read / Edit / Write）逐处修改。

**禁止 SubAgent 编写任何代码（Python、Bash、正则脚本等）来批量处理文件。** 所有修复必须由 SubAgent 阅读原文后，通过文件编辑工具逐条定位并替换完成。

- SubAgent 的任务说明必须直接来自记录目录中的 `assets/llm-postprocess-prompt.md`，不要临时改写成论文总结任务。
- SubAgent 只应修改 `fulltext.md`、必要时同步修改 `assets/pages.json`、更新 `assets/manifest.json.postprocess.llm_agent`，并写入 `assets/llm-postprocess-report.md`。
- SubAgent 重点清理确定性规则未覆盖的 HTML 噪声、残留页码 / 页眉页脚、破碎引用、图片 alt / Figure 编号不一致、异常 heading level、断裂 DOI / 链接等格式问题；不得总结、翻译、扩写或改写论文内容。

#### Failure handling

- 若 SubAgent 启动失败，必须立刻对同一记录目录重试启动 1 次，继续使用同一个 `assets/llm-postprocess-prompt.md`。
- 若重试后仍无法启动 SubAgent，立即停止；最终回复告知用户 LLM review 未执行、失败发生在 SubAgent 启动阶段，并列出记录目录与 `assets/llm-postprocess-prompt.md` 路径。
- 若 SubAgent 返回 `ERROR`、未正常完成、未写出 `assets/llm-postprocess-report.md`，或未把 `assets/manifest.json.postprocess.llm_agent.status` 更新为 `done` / `skipped_no_change`，立即停止；最终回复说明失败原因、当前 `llm_agent.status`、记录目录和 report / prompt 路径。

#### Validate completion

SubAgent 完成后，主 Agent 必须检查：

- `assets/llm-postprocess-report.md` 存在
- `assets/manifest.json.postprocess.llm_agent.status` 已更新为 `done` 或 `skipped_no_change`
- 快速检查改动是否只影响后处理范围（未删除正文内容）

#### No SubAgent fallback

若当前环境完全没有 Agent / SubAgent 工具能力，或更高优先级工具策略阻止自动启动 SubAgent：

- 不要把 `prompt_ready` 当作已 review。
- 立即停止并向用户说明：“PDF 已抽取，但 LLM fulltext review 无法自动启动，因此尚未执行。”
- 报告记录目录、`assets/llm-postprocess-prompt.md` 路径，以及阻止启动的原因。

只有在用户明确要求跳过 LLM review 时，才可跳过此步骤。

## Final response

完成后，回复用户时必须给出：

- 源 PDF 来自 Zotero 时，仓库本地 PDF 副本路径与哈希校验结果
- 记录目录路径
- `paper.json` 路径
- `assets/manifest.json` 的 `status`
- `warnings`（如有）
- `postprocess.llm_agent.status`（`done` / `skipped_no_change`）
- `assets/llm-postprocess-report.md` 路径
- 提示用户可使用 `paper-note` skill 生成 `note.md`，或 `paper-translate` skill 生成 `fulltext.zh-CN.md`
