---
name: paper-translate
description: |
  Use when the user asks to translate the extracted fulltext of an academic
  paper into simplified Chinese.

  Triggers include: "translate paper", "翻译论文", "中文版", "翻译 fulltext",
  "生成中文全文", "translate fulltext", "论文翻译".

  This skill translates the extracted fulltext.md into simplified Chinese,
  producing fulltext.zh-CN.md in the same paper record directory. It does NOT
  extract PDFs, run postprocess, or generate notes.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Paper Translate

将 `paper-extract` 产出的 `fulltext.md` 翻译为简体中文，输出 `fulltext.zh-CN.md`。

## Accepted inputs

用户提供论文记录目录路径，例如 `library/papers/{PAPER_STEM}/`。

该目录必须包含：

- `paper.json`
- `fulltext.md`（建议已经过 `paper-extract` 的 LLM 后处理格式化，但非必需）

如果用户提供的是补充材料目录，例如：

```text
library/papers/{PAPER_STEM}/supplements/{SUPPLEMENT_LABEL}/
```

则读取该目录下的 `fulltext.md`，并输出同目录 `fulltext.zh-CN.md`。

如果用户没有指定具体目录，尝试从上下文或最近的对话中推断；如果无法确定，询问用户。

## Translation rules

### Target language

简体中文（zh-CN）。

### Structural preservation

- 保持 Markdown 结构不变：heading 层级、列表、代码块、引用块、分隔线
- 保留图片引用语法原样不翻译：`![Figure N](...)` 保持英文
- 保留 `## Figures`、`## Tables` 和 `## Copyright` 区块结构，区块内图注 / 表格文字翻译、版权文本保留原文
- 保留表格结构，翻译表格内的文字内容

### Terminology handling

- 技术术语首次出现时标注英文原文，格式：`中文译名（English Term）`，后续直接用中文
- 广泛使用的缩写（如 CNN、GAN、LLM、AR、VR）无需翻译，保持原样
- 方法名 / 系统名保留英文原名，首次出现可附中文说明

### Content that must NOT be translated

- 人名（保留原文拼写）
- 机构名（保留原文，首次出现可附中文说明）
- 参考文献条目（`## References` 区块内容全部保留原文）
- 数学公式与方程（LaTeX / MathJax 内容保持原样）
- 代码片段
- DOI、URL、arXiv ID

### Quality requirements

- 翻译应准确传达学术含义，不要意译成口语化表达
- 保持句间逻辑关系，必要时调整语序以符合中文阅读习惯
- 不要增删内容：不要添加原文没有的解释，也不要省略原文内容
- 中英文之间加半角空格（例如：`使用 Transformer 架构`）

## Workflow

### 1. Validate input

检查 `fulltext.md` 存在。如果同目录已存在 `fulltext.zh-CN.md`，提示用户确认是否覆盖。

### 2. Read fulltext

读取 `fulltext.md` 全文。如果文件过长，分段翻译以确保质量，但必须保证段落边界不破坏 Markdown 结构。

### 3. Translate and write

按上述规则翻译全文，写入同目录下的 `fulltext.zh-CN.md`。

如果当前目录是顶层论文记录目录，更新 `paper.json.translation_path`。如果当前目录是 `supplements/{SUPPLEMENT_LABEL}/`，更新父记录 `paper.json.supplements` 中对应条目的 `translation_path`。

不要移动或删除 `note.md`、`paper.json`、`assets/`、`figs/` 或源 PDF。

## Final response

完成后，回复用户时必须给出：

- 翻译文件路径
- 原文字符数与译文字符数
- 记录目录或补充材料目录路径
- `paper.json` 路径（如已更新）
