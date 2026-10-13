# 执行配置与续跑

完整准备读取本文件；只整理和加载模式不需要模型配置。

## 模型配置

[task-defaults.json](../task-defaults.json) 是技能项目配置，不改变主聊天或全局设置。按字段解析：本次阶段指定 > 本次流程指定 > `tasks.<任务名>` > `defaults`。省略字段继续继承，解析结果保留在本次上下文，临时指定不写回文件。

`defaults` 必须含非空字符串 `model` 和 `reasoning_effort`，`tasks` 为对象，各任务可覆盖这两个字段。配置缺失、JSON 无效、未知任务/字段或空值时，报告问题并停止受影响阶段。

| 任务名 | 完成记录位置 |
| --- | --- |
| `postprocess` | `stages.extraction.llm_execution` |
| `formula_fix` | `stages.formula.llm_execution` |
| `markdown_fix` | `stages.ocr.llm_execution` |
| `translation` | `stages.translation.llm_execution` |

派发前检查工具支持的模型与强度，并显式传入两个参数。完整历史继承不允许覆盖时，使用允许覆盖的上下文模式，传入原始 prompt、组件技能、审稿规则及路径。配置不可用、无法设置或有效配置不符时停止该阶段，不静默替换或由主 Agent 代做。工具接受参数但未回报有效配置时可继续，交付时说明确认范围；未确认实际配置的旧任务不作为满足新配置的任务复用。

每个 `llm_execution` 记录 `requested`（工具请求的两个字段）、`config_source`（逐字段取 `user_task`、`user_run`、`task`、`defaults`）及可用的 `agent_id`。`effective` 仅填工具确认的有效配置，未确认字段为 null；`verification` 为 `confirmed`、`partial` 或 `not_reported`。不把 requested 或子 Agent 自述当作有效配置。

## 完成记录

每个文档维护 `assets/review-prepare.json`。新记录使用 `schema_version: 1`、`path_base: "review-prepare"`，文件路径均相对该 JSON，沿用阶段名 `extraction`、`formula`、`ocr`、`translation`。

- 源文件：`source_pdf`、`source_pdf_sha256`。
- 各阶段：`status`（`pending`、`done`、`failed`）、`input_path`、`input_sha256`、`output_path`、`output_sha256`、上表的 `llm_execution` 和报告的 `report_path`。翻译验收直接记入 `translation.validation` 时可省略其 report_path。
- 提取另记 `llm_postprocess_status`；翻译输入为最终修复全文、输出为实际译文。组件报告的 `skipped_no_change` 经独立审阅和验收后计为阶段 `done`。
- `translation.validation` 记录章节覆盖、公式、引用与图片链接的检查结果。失败记录阶段及原因，后续保持未完成。

## 复用与续跑

复用完整成果须核对源 PDF 哈希、四阶段状态及哈希衔接、当前全文与 OCR 输出、当前译文与翻译输出、翻译输入与当前全文，并检查引用文件、已登记报告及翻译验收依据。中间文件已原地修改，不要求当前全文等于每个中间输出。

部分完成时核对最后完成阶段的输出与当前文件，从下一阶段继续。无完成记录的历史成果按 manifest/报告逐项确认，复用可验证阶段，其余列为待执行。缺少新模型字段或默认配置变化不触发已验证内容重跑，也不补造历史有效配置。

源 PDF 或当前文件不匹配、用户指定模型重跑时列明差异与受影响产物；覆盖译文或破坏性刷新按组件和审稿规则确认覆盖或另存版本，保留手动修改。续跑解析本机路径并重新生成 prompt，不执行旧机器路径。
