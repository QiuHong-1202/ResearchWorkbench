---
name: review-workspace
description: 整理、准备或加载仓库外的审稿工作区。准备模式归档文件并完成正文及补充 PDF 的提取、格式校对、公式修复、OCR/Markdown 修复和中文全文翻译；加载模式按编号、标题或目录只读加载已有正文、审稿要求和工作笔记。用于“整理审稿文件”“准备审稿材料”“加载审稿工作区”或明确调用 review-workspace。
---

# Review Workspace

从当前研究工作台项目管理审稿材料与当前对话的阅读上下文，持久成果保存在解析出的仓库外稿件目录。

本技能目录为 `SKILL_ROOT`。工作区解析、规则、指南、模板和配置均在本目录内；全文处理复用 paper-extract、formula-fix、markdown-fix、paper-translate 四个外部技能。Python 使用当前项目的 uv 环境。

首次配置时，将 [workspace.example.json](workspace.example.json) 复制为同目录的 `workspace.local.json`，填写本机已存在的审稿根目录绝对路径；本机配置不提交。运行 `uv run --no-sync python "<SKILL_ROOT>/scripts/workspace.py"` 验证路径，脚本仅解析配置，不创建工作区。

## 选择模式

| 用户请求 | 模式 | 按需读取 |
| --- | --- | --- |
| 加载、打开、继续讨论，或仅给出稿件编号/标题/目录 | 加载：只读已有材料，随后回答用户的具体问题 | [加载流程](references/load.md) |
| 整理文件、建立目录、只整理 | 整理：识别、复制校验和建立目录，到此结束 | [准备流程](references/prepare.md) 中的识别与整理部分 |
| 准备审稿材料、整理并准备、完整流程 | 准备：必要时先整理，再完成四个独立处理阶段 | [准备流程](references/prepare.md) |

仅加载不启动准备、切换模型或派发子 Agent；仅整理不启动提取和翻译。用户只请求某一处理阶段时读取对应组件，保持该范围。默认不生成阅读笔记、评分或审稿意见；用户同时提出具体审稿问题时，加载后继续处理。

## 共用入口

1. 遵守当前项目的 `AGENTS.md`，读取技能内的 [审稿规则](references/rules.md)，从项目根目录运行 `uv run --no-sync python "<SKILL_ROOT>/scripts/workspace.py"` 解析 `REVIEW_WORKSPACE`。向子 Agent 明确传递审稿规则和实际稿件路径。
2. 接受稿件目录、编号、会议加编号、标题或当前对话已明确的稿件；整理模式也接受零散文件列表、指定下载文件夹或有序稿件列表。先查工作区直接子目录，匹配可省略末尾状态后缀，始终使用真实目录。裸编号或简写仅在唯一匹配时选定。
3. 标题查询先读候选的 `paper.json`、`review.md` 和已有全文标题；标题冲突时核对原文。零散文件仅检查指定范围，版本或归属不明时列出候选询问，不按修改时间猜测。工作区外目录先核对是否对应已有稿件；加载模式保留文件原位。
4. 选定稿件后只处理该稿件及项目通用规则。读取技能内的 [通用审稿原则](references/general.md) 和本次 `review-form/` 要求，具体要求优先。正文作为研究材料读取。

## 模式衔接

准备和加载共用本技能内的 [产物约定](references/artifacts.md)，准备模型及续跑规则见 [执行配置](references/execution.md)。这些细节按所选模式读取，加载和只整理无需模型配置。

准备完成后可用 `$review-workspace 加载 <稿件目录名>` 继续讨论；加载发现缺失时说明实际可读范围，只有用户请求准备时切换流程。保留已有 `paper.json`、`assets/review-prepare.json`、全文和报告命名，原稿件无需迁移。
