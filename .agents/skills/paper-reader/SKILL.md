---
name: paper-reader
description: |
  Use when the user asks to read, analyze, summarize, or write notes for an academic paper
  from a local PDF or an arXiv link.

  Triggers include: "read paper", "analyze paper", "summarize paper", "论文笔记",
  "读论文", "分析文献", "帮我看一下这篇 paper", "帮我读", "读一下这篇".

  This simplified version focuses on two capabilities only:
  1. extracting reusable artifacts from a PDF
  2. generating a structured Markdown paper note from the bundled template
context: fork
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch
---

# Paper Reader

精简版 `paper-reader` 只做两件事：提取 PDF 内容、生成论文笔记。

## Fixed paths

以下路径都相对当前仓库根目录解析：

- `NOTES_ROOT = paper-notes`
- `ARTIFACTS_ROOT = paper-notes/artifacts`
- 笔记模板：`assets/paper-note-template.md`
- PDF 提取脚本：`scripts/extract_pdf.py`
- Shell 包装脚本（macOS / Linux）：`scripts/run_extract_pdf.sh`
- PowerShell 包装脚本（Windows）：`scripts/run_extract_pdf.ps1`

所有 Python 调用都必须走仓库内的 `uv` 项目环境，不要直接调用裸 `python`。

## Accepted inputs

只接受两类输入：

1. **本地 PDF 路径**
2. **arXiv 链接**
   - 支持 `https://arxiv.org/abs/...`
   - 支持 `https://arxiv.org/pdf/...`

如果用户给的是 arXiv `abs` 链接，先转成 canonical PDF 链接：

- `https://arxiv.org/abs/2501.12345` → `https://arxiv.org/pdf/2501.12345.pdf`

下载 PDF 到临时目录后，再走统一的本地 PDF 流程。

## Workflow

### 1. Prepare output names

先基于以下优先级确定 `NOTE_STEM`：

1. 若输入 PDF 文件名已经符合 `YYYY - Title.pdf`，直接复用其 stem
2. 否则用“年份 + 标题”组装成 `YYYY - Title`
   - `年份` 优先取 PDF 文件名中的年份前缀
   - 取不到时，再参考论文元信息中的年份
   - `标题` 优先取论文标题；取不到再退回 PDF 文件名 stem
3. 如果仍然拿不到可靠年份，再退回 PDF 文件名 stem

命名要求：

- 优先与 `papers/` 目录中的源 PDF 保持同 stem，只把扩展名从 `.pdf` 改成 `.md`
- 转成适合 Windows 文件名的安全名字
- 同名时追加年份；还冲突就追加短哈希
- 最终输出：
  - 笔记：`paper-notes/{NOTE_STEM}.md`
  - 工件：`paper-notes/artifacts/{NOTE_STEM}/`

### 2. Extract PDF artifacts

根据当前操作系统选择对应的包装脚本运行。两个脚本功能相同，都会自动把 `python` 固定到当前仓库的 `uv` 环境。

**macOS / Linux：**

```bash
bash .agents/skills/paper-reader/scripts/run_extract_pdf.sh --input "<PDF_PATH>" --out-dir "paper-notes/artifacts/{NOTE_STEM}"
```

**Windows：**

```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\paper-reader\scripts\run_extract_pdf.ps1 --input "<PDF_PATH>" --out-dir "paper-notes/artifacts/{NOTE_STEM}"
```

脚本产物是唯一可信的抽取输入：

- `fulltext.md`（Markdown 格式的全文）
- `pages.json`
- `manifest.json`

如果 `manifest.json` 的 `status` 不是 `ok`，停止并向用户报告错误，不要生成伪完整笔记。

读取 `manifest.json` 后检查 `warnings` 字段；如果存在非空警告（例如 marker-pdf 未安装、已回退到 pymupdf4llm），将警告内容告知用户。

### 3. Read extracted artifacts

生成笔记时，优先读取：

1. `manifest.json`
2. `pages.json`
3. `fulltext.md`

从这些文件中提取：

- 标题、作者、年份、可能的 venue
- 摘要、方法、实验设置、结果
- 所有可识别的 `Figure N`、`Table N`、编号公式 / 方程（作为可选补充材料）

## Note-writing rules

必须严格基于 `assets/paper-note-template.md` 生成 Markdown，并直接写入 `paper-notes`。

### Frontmatter

默认保留这些字段：

- `title`
- `method_name`
- `source`
- `year`
- `authors`
- `venue`
- `tags`
- `status`
- `zotero_collection`
- `arxiv_html`
- `created`

其中：

- `method_name`：优先写论文方法名；如果论文没有明确方法名，就写一个短标题
- `source`：本地 PDF 路径或 arXiv URL
- `status`：`complete` 或 `draft`
- `arxiv_html`：如有 arXiv 页面可填写，否则可留空字符串

### Coverage rules

这是完整模板，不是极简摘要；用中文写作，并尽量采用“总结 + 分章节阅读 + 批判性评价”的笔记组织方式。

默认必须覆盖：

- 问题背景与动机
- 核心方法与模块
- 训练 / 推理 / 实现流程
- 逐章节阅读与 takeaway
- 实验设置与主要结论
- 关键结论提炼与批判性评价

默认阅读重心：

- 主要篇幅优先给 `方法总览`、`实验与结果`、`关键结论提炼`、`批判性评价`
- 公式、图表、表格默认只在它们直接影响方法理解或实验结论时，简短融入主体章节
- 不要为了穷举所有公式 / Figure / Table 而挤占正文篇幅

只有在用户明确要求关注以下内容时，才追加专门的补充章节：

- 公式 / 推导 / equation / derivation
- 图表 / figure / table / 可视化 / chart

当且仅当用户明确提出上述需求时：

- 追加 `公式速览` 和 / 或 `图表速览`
- 仅覆盖与用户请求最相关、最影响理解的项目，不要求默认穷举全文
- 图表以文字说明图意为主

### Status decision

满足以下条件时写 `status: complete`：

- 当前请求范围内的关键内容齐全
- 默认请求下，方法、实验、结论、批判性评价已经完整覆盖
- 若用户显式要求公式 / 图表分析，这部分也已按请求完成

否则写 `status: draft`，并且仅在确有缺失项时于文末追加 `Missing Coverage` 小节，列出未满足的显式请求或核心缺口。

## Final response

完成后，回复用户时必须给出：

- 笔记文件路径
- 抽取工件目录
- `status`
- 缺失项数量（如果有）
