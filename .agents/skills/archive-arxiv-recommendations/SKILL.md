---
name: archive-arxiv-recommendations
description: |
  Archives past-month arXiv daily recommendation files under archive/YYYY-MM/
  and keeps only the current month in recommendations/. This skill never stages,
  commits, or pushes changes; users review and commit the moved files manually.
  Use when the user asks to archive, organize, or roll over arxiv-daily
  recommendations by month, tidy recommendations/, or run monthly recommendation
  cleanup.
---

# Archive arXiv Recommendations

将 `arxiv-daily/recommendations/` 根目录中**非当月**的推荐文件移入 `archive/YYYY-MM/`，根目录只保留当月 `{YYYY-MM-DD}-arxiv-recommended.md`。

该工具只移动文件。它不会执行 `git add`、`git mv`、`git commit` 或 `git push`；归档后由用户人工审阅并提交。

## Layout

```text
arxiv-daily/recommendations/
├── {YYYY-MM-DD}-arxiv-recommended.md   # 仅当月，平铺在根目录
└── archive/
    └── {YYYY-MM}/
        └── {YYYY-MM-DD}-arxiv-recommended.md
```

`recommendations_root` 默认读 `.agents/skills/arxiv-daily/config.yaml`；当月判定用 **UTC** 的 `YYYY-MM`（与 arxiv-daily 日期语义一致）。

## Workflow

1. 确认 `.agents/skills/arxiv-daily/config.yaml` 存在且含 `recommendations_root`
2. 先 dry-run，确认待移动文件与目标月份：

   **Windows:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\.agents\skills\archive-arxiv-recommendations\scripts\run_archive.ps1 --dry-run
   ```

   **macOS / Linux:**
   ```bash
   bash .agents/skills/archive-arxiv-recommendations/scripts/run_archive.sh --dry-run
   ```

3. 无待归档文件：告知用户无需归档
4. 有待归档文件且用户确认后，正式执行：

   **Windows:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\.agents\skills\archive-arxiv-recommendations\scripts\run_archive.ps1
   ```

   **macOS / Linux:**
   ```bash
   bash .agents/skills/archive-arxiv-recommendations/scripts/run_archive.sh
   ```

5. 运行后报告移动文件数、涉及月份、根目录保留的当月前缀，并提醒用户用 `git status` 审阅后自行提交

## Options

| Flag | 作用 |
|------|------|
| `--dry-run` | 只打印计划，不移动文件 |
| `--month YYYY-MM` | 指定「当月」前缀（测试或补跑时用） |
| `--config PATH` | 覆盖 config 路径（相对仓库根） |

## Final response

完成后告知：

- 是否发生归档（文件数、涉及月份）
- 根目录保留的当月前缀
- 已明确未执行任何 git 写操作
- 提醒用户审阅 `git status` 并自行提交

## Errors

- config 缺失或 `recommendations_root` 未配置：停止并提示修复 config
- 目标路径已存在同名文件：停止，不部分提交
