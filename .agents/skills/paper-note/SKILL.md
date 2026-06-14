---
name: paper-note
description: |
  Use when the user asks to generate reading notes or a structured summary
  for an academic paper from its extracted artifacts.

  Triggers include: "paper note", "论文笔记", "生成笔记", "读论文",
  "阅读理解", "写笔记", "summarize paper", "reading notes".

  This skill generates a structured Markdown paper note from the extracted
  fulltext.md. It does NOT extract PDFs or run LLM postprocess — those
  are handled by the paper-extract skill.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch
---

# Paper Note

基于 `paper-extract` 产出的工件（`fulltext.md`、`assets/pages.json`、`assets/manifest.json`），按模板生成结构化中文论文笔记。

## Fixed paths

以下路径相对当前仓库根目录解析：

- `NOTES_ROOT = paper-notes`
- `ARTIFACTS_ROOT = paper-notes/artifacts`
- 笔记模板：`assets/paper-note-template.md`

## Accepted inputs

用户提供工件目录路径，例如 `paper-notes/artifacts/{NOTE_STEM}/`。

该目录必须包含：

- `assets/manifest.json`（`status` 为 `ok`）
- `fulltext.md`
- `assets/pages.json`

如果用户没有指定具体工件目录，尝试从上下文或最近的对话中推断；如果无法确定，询问用户。

## Workflow

### 1. Check format status

读取 `assets/manifest.json`，检查 `postprocess.llm_agent.status`：

- 若为 `done` 或 `skipped_no_change`：继续生成笔记。
- 若为 `prompt_ready`：警告用户 LLM 后处理 review 尚未执行，建议先运行 `paper-extract` skill 完成格式化。
  - 如果用户明确要求跳过 review，可继续，但必须在最终笔记中标记"LLM fulltext review 未执行"为缺失项。
- 若 `assets/manifest.json` 的 `status` 不是 `ok`：停止并报告抽取错误。

### 2. Read extracted artifacts

生成笔记时，优先读取：

1. `assets/manifest.json`
2. `assets/pages.json`
3. `fulltext.md`

从这些文件中提取：

- 标题、作者、年份、可能的 venue
- 摘要、方法、实验设置、结果
- 所有可识别的 `Figure N`、`Table N`、编号公式 / 方程（作为可选补充材料）
- 若需要查看图像或版权 / 出版样板信息，优先读取 `assets/pages.json.extracted_blocks` 或 `fulltext.md` 的 `## Figures` / `## Copyright` 区块；默认不要把 `## Copyright` 内容当作论文正文贡献来总结。

### 3. Generate note

必须严格基于 `assets/paper-note-template.md` 生成 Markdown，并直接写入 `paper-notes/{NOTE_STEM}.md`。

`NOTE_STEM` 取自工件目录名（即 `paper-notes/artifacts/{NOTE_STEM}/` 中的目录名）。

## Note-writing rules

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

这是完整模板，不是极简摘要；用中文写作，并尽量采用"总结 + 分章节阅读 + 批判性评价"的笔记组织方式。

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
- `assets/manifest.json.postprocess.llm_agent.status` 为 `done` 或 `skipped_no_change`；或用户明确要求跳过 review

否则写 `status: draft`，并且仅在确有缺失项时于文末追加 `## 缺失覆盖` 章节，列出未满足的显式请求或核心缺口。若用户明确要求跳过 LLM review 后继续，将"LLM fulltext review 未执行"计为一个缺失项。

## Final response

完成后，回复用户时必须给出：

- 笔记文件路径
- 工件目录路径
- `status`
- `assets/manifest.json.postprocess.llm_agent.status`
- 缺失项数量（如果有）
