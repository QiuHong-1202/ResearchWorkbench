---
name: markdown-fix
description: |
  Use when the user asks to fix OCR / structure problems in a paper / document
  Markdown (often produced by a PDF / OCR conversion): wrong Markdown heading levels, stray OCR
  glyphs / bullets, garbled Unicode, broken lists, and hyphenation / word-join
  artifacts.

  Triggers include: "markdown 修复", "修复标题层级", "标题层级错误", "修复 OCR",
  "清理多余符号", "OCR 字符", "修复破碎列表", "fix markdown", "fix heading levels",
  "fix ocr", "normalize markdown".

  This skill reviews a single Markdown file and fixes heading-level, Unicode-glyph,
  bullet/list and hyphenation OCR artifacts in place, via an LLM SubAgent. Ambiguous
  fragments are left untouched and reported. It does NOT extract PDFs, rewrite
  formulas, translate, or summarize.
allowed-tools: Read, Write, Edit, Glob, Grep, Agent
---

# Markdown Fix

review 一篇 Markdown 文档（常见于 PDF / OCR 转换得到的论文全文），修复其中的 OCR / 结构问题（错误的标题层级、散落的 OCR 杂字符与项目符号、乱码 Unicode、破碎列表、断词 / 连字），**就地修改**，由 LLM SubAgent 逐处人工编辑完成。无法确定如何修复的片段保持原样并写入报告。

## Fixed paths

相对当前仓库根目录解析：

- LLM 任务 prompt 模板：`.agents/skills/markdown-fix/assets/llm-markdown-fix-prompt-template.md`

## Accepted inputs

用户提供以下之一：

1. **目标 Markdown 文件路径**（推荐），例如 `path/to/fulltext.md`
2. **包含 Markdown 的目录路径** —— 此时默认目标文件为该目录下的 `fulltext.md`；若不存在则请用户指定具体文件

若用户没给路径，尝试从上下文 / 最近对话推断；无法确定时询问用户。

## Scope（这个 skill 改什么）

只修 "OCR / 结构噪声"，论文的措辞、术语、数字、公式、引用一律不改写。完整规则见 prompt 模板，核心如下：

**修复：**

- **标题层级**：按章节编号把 `#` 数量改对，并锚定到文首 H1 论文标题——顶层节 `N`（如 `1 INTRODUCTION`）→ `##`，子节 `N.M`（如 `3.1`）→ `###`，子子节 `N.M.K`（如 `4.1.1`）→ `####`；未编号但明显是顶层节的 `REFERENCES` / `ACKNOWLEDGEMENTS` → `##`。顺带去掉标题里多余的 `**` 强调。
- **散落符号 / 项目符号**：被 OCR 混进正文或列表行的 `• ● ▪ ‣` 等散字符（如作者行 `- *• Author Name ...*` 里的 `• `）。
- **Unicode 字形 / 编码**：连字 `ﬁ/ﬂ/ﬀ` → `fi/fl/ff`、不间断空格 → 普通空格、软连字符删除、花引号 → 直引号、破折号规范、mojibake（如 `Ã©`、`â€™`）。
- **破碎列表**：被打散成 `-` / `- 2.` 混合的有序列表（如"三点贡献"列表）在有把握时恢复为规整有序列表。
- **断词 / 连字（高风险）**：仅当能确定正确形式时（换行连字拼回一个真实单词，或同篇别处出现了正确写法）才修；否则不改并登记报告。

**保持原样：**

- 公式片段（`$...$` / `$$...$$`、Unicode 数学符号）：保持原样，公式标准化不在本 skill 范围。
- 残留页码 / 页眉页脚 / 孤立噪声：不在本 skill 范围，保持原样。
- 引用编号 `[7]`、脚注上标 `<sup>1</sup>`、作者机构行内容、参考文献条目内容。
- `## Figures` / `## Tables` / `## Copyright` 区块：不删除、不把内容移回正文，只在区块内顺手修同类格式噪声。
- 疑似 OCR 字符混淆（`l/1/I`、`O/0`、`rn/m`）——不在本 skill 范围，除非是上下文里 100% 确定的明显笔误。

**无法确定**如何修复（最常见：断词歧义、列表是否有序存疑、某符号是否该删存疑）：不改，登记到报告。

## Workflow

### 1. Resolve target & report paths

- 解析 `TARGET_PATH`（按 Accepted inputs；若给的是目录则取该目录下 `fulltext.md`）。
- 确认 `TARGET_PATH` 存在且是 `.md`；否则停止并报告。
- 令 `TARGET_DIR` 为其所在目录，确定报告落点 `REPORT_PATH`：
  - 若 `TARGET_DIR/assets/` 存在 → `TARGET_DIR/assets/markdown-fix-report.md`
  - 否则 → `TARGET_DIR/markdown-fix-report.md`
- 报告按"每次运行一个文件"覆盖写；报告开头写明本次目标文件。

### 2. Prepare SubAgent prompt

读取模板 `.agents/skills/markdown-fix/assets/llm-markdown-fix-prompt-template.md`，把占位符替换为实际路径：

- `{{TARGET_PATH}}` → `TARGET_PATH`
- `{{REPORT_PATH}}` → `REPORT_PATH`

将替换后的内容作为 SubAgent 的任务说明（可同时写一份到 `REPORT_PATH` 同目录的 `markdown-fix-prompt.md` 备查）。

### 3. Dispatch SubAgent

用 Agent / SubAgent 执行修复。SubAgent 必须遵守模板里的硬性约束：

- **禁止编写任何代码 / 正则脚本来批处理文件**；只能用 Read 阅读全文 + Edit/StrReplace 逐处修改。
- 就地修改 `TARGET_PATH`，只改上面 Scope 列出的 OCR / 结构片段，不动正文措辞、数字、公式、引用编号。
- 无法确定如何修复的片段不改，写入报告。
- 完成后写 `REPORT_PATH`，状态为 `done` 或 `skipped_no_change`。

### 4. Failure handling

- SubAgent 启动失败：立刻用同一 prompt 重试启动 1 次。
- 重试仍失败：停止；最终回复告知 LLM review 未执行（失败在启动阶段），列出 `TARGET_PATH` 与 prompt 模板路径。
- SubAgent 返回 ERROR / 未写出 `REPORT_PATH` / 状态未更新为 `done` 或 `skipped_no_change`：停止；最终回复说明失败原因、当前状态、`TARGET_PATH` 与 `REPORT_PATH`。

### 5. Validate completion

SubAgent 完成后主 Agent 检查：

- `REPORT_PATH` 存在且状态为 `done` 或 `skipped_no_change`。
- 用 Grep 列出所有标题行（`^#{1,6} `），抽查编号与层级是否自洽：顶层 `N` 应为 `##`、`N.M` 为 `###`、`N.M.K` 为 `####`，全文应只有一个 H1（论文标题）。不自洽则提示用户复核。
- 用 Grep 扫描残留散字符（`• ● ▪ ‣`）与连字（`ﬁ ﬂ ﬀ ﬃ ﬄ`）；把残留计数写进最终回复（残留可能是被判为歧义而保留，属正常）。
- 快速确认改动只影响 OCR / 结构片段，没有删除正文段落或参考文献。

### 6. No SubAgent fallback

若当前环境没有 Agent / SubAgent 能力，或工具策略阻止启动 SubAgent：

- 不要假装已修复。
- 停止并说明"已识别目标文件，但 markdown 修复 SubAgent 无法自动启动，因此尚未执行"，并报告 `TARGET_PATH`、prompt 模板路径与阻止原因。

只有用户明确要求时，才可由主 Agent 直接代替 SubAgent 执行（仍须遵守模板的全部约束）。

## Final response

完成后回复必须给出：

- 目标文件路径 `TARGET_PATH`
- 报告状态（`done` / `skipped_no_change`）与报告路径 `REPORT_PATH`
- 已修复数量 / 跳过（无法确定）数量（按类别）
- 校验结果（标题层级是否自洽、残留散字符 / 连字计数）
- 若存在"无法确定"的片段，提示用户这些需要人工确认
