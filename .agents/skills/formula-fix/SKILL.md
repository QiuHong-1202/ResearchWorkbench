---
name: formula-fix
description: |
  Use when the user asks to fix or normalize un-standardized formulas/equations
  in a paper / document Markdown (often produced by a PDF / OCR conversion) into LaTeX `$...$`.

  Triggers include: "公式修复", "修复公式", "公式标准化", "把公式转成 tex/latex",
  "修复未标准化的公式", "fix formulas", "formula fix", "normalize equations",
  "latexify formulas".

  This skill reviews a single Markdown file and rewrites un-standardized formula
  fragments (Unicode math symbols, HTML <sup>/<sub> math, set notation, inline
  variables) into LaTeX, in place, via an LLM SubAgent. Ambiguous fragments are
  left untouched and reported.
  It does NOT extract PDFs, translate, or summarize.
allowed-tools: Read, Write, Edit, Glob, Grep, Agent
---

# Formula Fix

review 一篇 Markdown 文档（常见于 PDF / OCR 转换得到的论文全文），把其中未被标准化的公式片段改写成标准 LaTeX（行内 `$...$`、显示 `$$...$$`），**就地修改**，由 LLM SubAgent 逐处人工编辑完成。无法确定 TeX 形式的片段保持原样并写入报告。

## Fixed paths

相对当前仓库根目录解析：

- LLM 任务 prompt 模板：`.agents/skills/formula-fix/assets/llm-formula-fix-prompt-template.md`

## Accepted inputs

用户提供以下之一：

1. **目标 Markdown 文件路径**（推荐），例如 `path/to/fulltext.zh-CN.md`
2. **包含 Markdown 的目录路径** —— 此时默认目标文件为该目录下的 `fulltext.md`；若不存在则请用户指定具体文件

若用户没给路径，尝试从上下文 / 最近对话推断；无法确定时询问用户。

## Scope（这个 skill 改什么）

只改"公式片段"，正文文字一律不动。完整规则见 prompt 模板，核心如下：

- **修复（转成 TeX）**：Unicode 数学符号（`Σ σ µ ∆ ◦`）、HTML 上/下标里的数学（`g<sup>t</sup>`）、集合记法（`{a0, .., a5}`）、行内变量/函数/分布（`gt`、`N(gt,Σ)`、`P(AOI=a_i|g_t)`、`D_B[...]`）、裸赋值/比较（`n = 8`、`∆t = 0.45 s`）、维度乘号（`1440 x 1600`）。
- **保持原样**：脚注/作者机构/引用上标（`Anna<sup>1</sup>`、`[7]`）、纯单位物理量（`20 cm`、`120 Hz`）、缩写/方法名（AOI、TPA、GHMM、HMM、softmax）、已正确的 `$...$` / `$$...$$`、参考文献条目。
- **无法确定 TeX 形式**（最常见 super/sub 歧义，如 `o<sup>i</sup>` 是 `o^i` 还是 `o_i`）：不改，登记到报告。

## Workflow

### 1. Resolve target & report paths

- 解析 `TARGET_PATH`（按 Accepted inputs；若给的是目录则取该目录下 `fulltext.md`）。
- 确认 `TARGET_PATH` 存在且是 `.md`；否则停止并报告。
- 令 `TARGET_DIR` 为其所在目录，确定报告落点 `REPORT_PATH`：
  - 若 `TARGET_DIR/assets/` 存在 → `TARGET_DIR/assets/formula-fix-report.md`
  - 否则 → `TARGET_DIR/formula-fix-report.md`
- 报告按"每次运行一个文件"覆盖写；报告开头会写明本次目标文件。

### 2. Prepare SubAgent prompt

读取模板 `.agents/skills/formula-fix/assets/llm-formula-fix-prompt-template.md`，把占位符替换为实际路径：

- `{{TARGET_PATH}}` → `TARGET_PATH`
- `{{REPORT_PATH}}` → `REPORT_PATH`

将替换后的内容作为 SubAgent 的任务说明（可同时写一份到 `REPORT_PATH` 同目录的 `formula-fix-prompt.md` 备查）。

### 3. Dispatch SubAgent

用 Agent / SubAgent 执行公式标准化。SubAgent 必须遵守模板里的硬性约束：

- **禁止编写任何代码 / 正则脚本来批处理文件**；只能用 Read 阅读全文 + Edit/StrReplace 逐处修改。
- 就地修改 `TARGET_PATH`，只改公式片段，不动其他文字、标点、空格、heading、引用编号。
- 无法确定 TeX 形式的片段不改，写入报告。
- 完成后写 `REPORT_PATH`，状态为 `done` 或 `skipped_no_change`。

### 4. Failure handling

- SubAgent 启动失败：立刻用同一 prompt 重试启动 1 次。
- 重试仍失败：停止；最终回复告知 LLM review 未执行（失败在启动阶段），列出 `TARGET_PATH` 与 prompt 模板路径。
- SubAgent 返回 ERROR / 未写出 `REPORT_PATH` / 状态未更新为 `done` 或 `skipped_no_change`：停止；最终回复说明失败原因、当前状态、`TARGET_PATH` 与 `REPORT_PATH`。

### 5. Validate completion

SubAgent 完成后主 Agent 检查：

- `REPORT_PATH` 存在且状态为 `done` 或 `skipped_no_change`。
- `TARGET_PATH` 中 `$` 定界符成对（行内 `$...$` 与显示 `$$...$$` 数量平衡）；不平衡则提示用户复核。
- 用 Grep 扫描 `TARGET_PATH` 残留的数学 Unicode 符号（`◦ Σ σ µ ∆ × ∑`）和"看起来是数学"的 `<sup>...</sup>`；把残留计数写进最终回复（残留可能是被判为歧义而保留，属正常）。
- 快速确认改动只影响公式片段，没有删除正文。

### 6. No SubAgent fallback

若当前环境没有 Agent / SubAgent 能力，或工具策略阻止启动 SubAgent：

- 不要假装已修复。
- 停止并说明"已识别目标文件，但公式修复 SubAgent 无法自动启动，因此尚未执行"，并报告 `TARGET_PATH`、prompt 模板路径与阻止原因。

只有用户明确要求时，才可由主 Agent 直接代替 SubAgent 执行（仍须遵守模板的全部约束）。

## Final response

完成后回复必须给出：

- 目标文件路径 `TARGET_PATH`
- 报告状态（`done` / `skipped_no_change`）与报告路径 `REPORT_PATH`
- 已修复数量 / 跳过（无法确定）数量
- 校验结果（`$` 是否平衡、残留 Unicode / `<sup>` 数学符号计数）
- 若存在"无法确定"的片段，提示用户这些需要人工确认
