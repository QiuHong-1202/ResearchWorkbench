# 审稿产物约定

准备模式写入产物，加载模式按本约定只读读取；目录与安全规则见 [审稿规则](rules.md)。历史布局原位兼容，不要求迁移或补造字段。

## 材料入口

新记录位于 `<稿件目录>/artifacts/paper/`，独立补充 PDF 位于其 `supplements/<稳定标签>/`，各记录保存：

```text
paper.json
fulltext.md
fulltext.zh-CN.md
assets/
  manifest.json
  pages.json
  llm-postprocess-report.md
  formula-fix-report.md
  markdown-fix-report.md
  review-prepare.json
figs/
```

`paper.json` 提供标题、源 PDF、全文、译文及补充关联；主记录 `supplements` 包含子记录的 `record_path` 和文件路径，无独立补充 PDF 时不创建补充目录。`assets/review-prepare.json` 保存阶段进度，写入规则见 [执行配置与续跑](execution.md)；`paper.json.status` 保留组件语义。准备进度和用户确认的审稿/提交状态分别表述。

阅读使用修复后的 fulltext.md；pages.json 保留页级溯源，可能尚未同步修复。加载从完成记录、manifest 和阶段报告提取影响阅读的警告，按问题读取补充与相关工作。

## 路径基准

| 字段 | 相对路径基准 |
| --- | --- |
| `paper.json` 的 `source`、`pdf_path`、`fulltext_path`、`translation_path`、`manifest_path`、`pages_path`、存在的 `note_path` 及 `supplements` 内路径 | paper.json 所在目录，`path_base: "record"`；补充条目相对主记录，子记录字段相对子记录。 |
| manifest 的 `input_pdf`、`output_dir`、`fulltext_path`、`pages_path`、`marker_meta_path`、`postprocess.llm_agent.prompt_path/report_path`、`recovered_figures[].report_path` | manifest 所在目录，`path_base: "manifest"`。 |
| manifest 的 `extracted_images`、`recovered_figures[].image`、`postprocess.llm_agent.changed_files` | 解析后的 `output_dir`，保留提取器语义。 |
| `review-prepare.json` 的文件路径 | JSON 所在目录，`path_base: "review-prepare"`。 |
| Markdown 图片/文件链接 | Markdown 所在目录。 |

提取和翻译后规范化本次记录的已知路径字段，用 pathlib/os.path.relpath 计算并输出正斜杠。未知字段和论文内容中的 URL/路径不递归替换；真实存在的旧 note.md 保留。

历史元数据可能缺少 path_base，报告可能含旧机器绝对路径。在选定稿件内核对实际文件；路径或版本有歧义时报告。只读加载不回写元数据或执行历史 prompt。

## 产物精简

保留提取器生成的 `llm-postprocess-prompt.md`，供组件派发及失败续跑；formula/markdown 的可选 prompt 副本默认不另存。任务脚本、日志、截图和诊断放入项目 `.agent-tmp/<task-id>/`。

新增翻译验收结果可直接写入阶段完成记录；需要独立核验细节时另建报告。已有完成摘要与翻译 QA 报告可复用，缺少它们或新模型字段不影响加载。默认不增加重复摘要、索引或加载报告，不删除历史产物。
