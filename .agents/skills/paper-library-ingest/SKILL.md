---
name: paper-library-ingest
description: Orchestrate complete paper-library ingestion for an ordered list of paper titles, identifiers, links, or PDF files, including acquisition, extraction, formula and Markdown cleanup, Chinese translation, notes, supplements, and index updates. Use for the full workflow; do not use for a single downstream transformation.
---

# Paper Library Ingest

将用户给出的文章列表依次纳入本地论文库。一篇文章全部完成并通过验证后，才开始下一篇；主论文与其补充材料属于同一篇文章。

本流程只管理本地论文库文件，不执行 `git add`、`git commit`、`git push` 或其他 Git 写操作。`paper.json`、`note.md` 和 `library/index.html` 可能包含个人分类、研究判断或本机信息，完成后应提醒用户在公开仓库中提交前逐项审阅。

## 输入与预检

接受一项或多项任意组合：论文标题、DOI、arXiv URL/ID、Zotero 条目线索、本地 PDF 路径或直接附加的 PDF。保留用户给出的顺序，不按年份、标题或来源重排。

在写入任何文件前完成整批只读预检：

1. 确认当前目录是论文库仓库根目录，并确认 `.agents/skills/paper-extract/SKILL.md`、`.agents/skills/formula-fix/SKILL.md`、`.agents/skills/markdown-fix/SKILL.md`、`.agents/skills/paper-translate/SKILL.md`、`.agents/skills/paper-note/SKILL.md` 和 `library/scripts/build_paper_index.py` 均存在。
2. 完整读取上述组件 Skill；组件的输入、产物、验证和失败规则优先于本 Skill。本 Skill 只补充跨组件的顺序、恢复语义和记录契约。
3. 依次解析每项输入的稳定标识符、标题、年份、主论文来源和明确存在的补充材料。先检查 `library/papers/` 与 `library/pdf/`，再使用用户明确提供的文件或线索；只有在环境具备访问能力且请求范围允许时才查询 Zotero，最后才查询公共网络。Zotero 不可用本身不是失败。
4. 补充材料发现范围限定为：精确匹配 Zotero 条目的 PDF 附件、出版页明确链接的 supplementary PDF，以及 arXiv ancillary PDF。只有这些来源明确列出 PDF 补充材料但无法获取时才停止；明确列出的非 PDF 材料应报告为当前工具链不支持，但不把它误判为缺失 PDF。不得无限搜索或根据模糊线索猜测其存在。
5. 如果任一输入与多篇文章匹配、版本无法确认或整批预检无法可靠消歧，停止并报告所有候选项，不要先处理已经消歧的文章。
6. 确认 `library/pdf/` 与 `library/papers/` 可用；目录不存在时可以创建，但不得删除或覆盖已有论文库文件。

按组件要求使用 SubAgent 或其他工具，并遵守宿主策略与用户授权；不得由本 Skill 推定额外权限。组件要求的能力不可用时，执行其停止规则。

## PDF 获取与归一化

主论文使用 Windows 安全文件名 `YYYY - Title.pdf`。补充材料沿用主论文 stem，命名为 `YYYY - Title supplementary[-label].pdf`；只有多个补充文件时才添加简短、稳定且唯一的 label。

用户直接提供文件或 Zotero 本地附件时，将真实 PDF 复制到 `library/pdf/`，不要从原位置移动或删除。复制后比较源文件与目标文件的字节大小和 SHA-256；目标已存在且哈希相同则复用，哈希不同则停止且不得覆盖。Zotero 文件必须按 `paper-extract` 的本地化规则处理，后续不得直接从 Zotero storage 提取。

需要联网获取时，优先使用出版方公开 PDF、arXiv、作者或机构仓库等合法来源，并验证响应确实是目标文章的 PDF。遇到登录、验证码、付费墙、无法确认版本或需要新批准的动作时停止。

后续所有本地路径必须指向仓库内的规范化副本并以仓库相对路径记录；URL 可以保留为 `https://` 来源。不得把仓库外绝对路径或 `file://` URL 写入 `paper.json`、`note.md` 或索引。

## 论文记录与补充材料契约

主论文记录目录固定为 `library/papers/{PAPER_STEM}/`，补充材料目录固定为 `library/papers/{PAPER_STEM}/supplements/{SUPPLEMENT_LABEL}/`。`SUPPLEMENT_LABEL` 在同一主记录内必须唯一。

每个补充材料提取完成后，创建或更新主论文 `paper.json.supplements` 中 label 相同的唯一对象，至少包含以下字段；所有路径均为仓库相对 POSIX 路径：

```json
{
  "label": "supplementary-material",
  "title": "Supplementary Material",
  "pdf_path": "library/pdf/YYYY - Title supplementary.pdf",
  "fulltext_path": "library/papers/YYYY - Title/supplements/supplementary-material/fulltext.md",
  "translation_path": "library/papers/YYYY - Title/supplements/supplementary-material/fulltext.zh-CN.md",
  "manifest_path": "library/papers/YYYY - Title/supplements/supplementary-material/assets/manifest.json",
  "pages_path": "library/papers/YYYY - Title/supplements/supplementary-material/assets/pages.json"
}
```

`paper-extract` 可能在补充材料目录生成局部 `paper.json`，但它不能替代主记录中的 `supplements` 条目。更新条目时保留未知字段和其他 label 的条目，不得创建重复 label。

## 完整性与恢复

只有下列条件全部满足，才把一个文档视为已完整提取并跳过 `paper-extract`：规范化 PDF 存在；当前文档目录内的 `paper.json`、`fulltext.md`、`assets/manifest.json`、`assets/pages.json` 和 `assets/llm-postprocess-report.md` 存在；manifest 的 `status` 为 `ok`，`postprocess.llm_agent.status` 为 `done` 或 `skipped_no_change`；manifest 或 Markdown 引用的必需文件均存在。补充材料还必须有符合上述契约的主记录条目。

若只有部分文档完整，只跳过完整文档。对不完整记录，允许 `paper-extract` 按其规则刷新仅由提取阶段拥有的产物，但必须保留 `note.md`、`fulltext.zh-CN.md` 和其他下游产物；组件无法安全续跑或要求未获批准的覆盖操作时停止。

下游阶段按报告状态和产物时间恢复，避免重跑已经完成的文章：

- `formula-fix`：报告状态为 `done` 或 `skipped_no_change`，且报告不早于本次提取 manifest 时跳过。
- `markdown-fix`：报告状态有效，且报告不早于 formula 报告（没有 formula 报告时不早于提取 manifest）时跳过。
- `paper-translate`：译文存在，且不早于 markdown 报告时跳过。
- `paper-note`：主论文笔记存在，且不早于 markdown 报告时跳过。

时间戳不可用、报告状态无效或依赖产物更新过时，视为该阶段未完成并按组件规则执行；若组件因此要求覆盖确认，停止并报告需要用户决定的文件。

## 每篇文章的固定流程

对预检后的文章严格串行执行；每个阶段内先处理主论文，再按发现顺序处理补充材料：

1. 对未完整提取的文档调用 `$paper-extract`，输入必须是 `library/pdf/` 中的规范化 PDF，并验证 manifest、report、warnings 和必需文件。
2. 为每个补充材料创建或更新主 `paper.json.supplements` 条目，并验证 label 唯一；`pdf_path`、`fulltext_path`、`manifest_path` 和 `pages_path` 必须存在且为仓库相对路径，`translation_path` 此时只验证为预期的仓库相对目标，待步骤 5 再验证文件存在。
3. 对未通过恢复判定的每个 `fulltext.md` 调用 `$formula-fix`，验证报告状态、LaTeX 定界符和残留计数。
4. 对未通过恢复判定的每个 `fulltext.md` 调用 `$markdown-fix`，验证报告状态、标题层级和残留噪声计数。
5. 对未通过恢复判定的主记录与补充材料目录调用 `$paper-translate`，生成 `fulltext.zh-CN.md`；再次验证主 `paper.json.supplements` 中对应 `translation_path`。
6. 仅对未通过恢复判定的主论文调用一次 `$paper-note`。明确要求以最终修复后的 `fulltext.md` 为正文权威来源；`assets/pages.json` 只用于页定位与 `extracted_blocks` 中的图、表和版权内容。
7. 在生成索引前，检查索引会扫描的全部顶层 `paper.json`、对应笔记 frontmatter 和补充材料条目；其中的本地路径必须位于仓库内且使用相对路径，发现仓库外绝对路径或 `file://` 时停止。运行 `uv run --project . python library/scripts/build_paper_index.py`，确认退出码为 0，并在 `library/index.html` 中验证当前论文标题、主记录链接和所有预期补充材料 label 均已出现；脚本静默跳过记录也视为失败。

## 停止与完成报告

任一步骤失败、文件哈希冲突、输出验证失败、明确存在的 PDF 无法获取、需要登录/批准/覆盖确认、组件缺失或索引漏项时，立即停止整个列表。报告当前文章、失败阶段、最后完成步骤、具体错误和路径，以及尚未处理的文章；保留已成功生成的产物等待用户处理。

全部完成后按输入顺序汇总每篇文章的规范化 PDF、记录目录、主全文、中文全文、笔记、补充材料产物和索引路径，并注明每个被恢复判定跳过的阶段。提醒用户这些本地论文库产物可能含私人研究信息，公开提交前必须逐项审阅。
