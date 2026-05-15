---
name: arxiv-daily
description: |
  Use when the user asks for today's arXiv digest or daily paper recommendations
  from configured categories.

  Triggers include: "arxiv daily", "今日 arxiv", "今天的 arxiv", "每日论文推荐",
  "扫一下 arxiv", "daily digest", "推荐今天的论文", "arxiv 推荐".

  This skill runs a four-step pipeline:
  1. fetch arXiv RSS per category into a per-day subdirectory
  2. dedupe across categories and split into scoring batches
  3. dispatch one scoring SubAgent per batch in parallel
  4. aggregate scores, filter by threshold, write a recommendation file under recommendations/
context: fork
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent
---

# ArXiv Daily

自动抓取 arXiv RSS 指定分类、跨分类去重、分批由 SubAgent 并行打分，最终在 `arxiv-daily/recommendations/` 产出当天的 `recommended.md`。所有中间产物收敛到 `arxiv-daily/artifacts/{date}/`。

**日期语义**：`{date}` 始终是 **arXiv announcement UTC date**（与 RSS entries 里 `published` 字段的 UTC 日期一致），与本地时区无关。脚本默认从第一次拿到的 feed 里读出这个日期，保证同一次 announcement 无论何时/何地运行都落到同一目录。

## Output layout

```
arxiv-daily/
├─ artifacts/
│  └─ {date}/
│     ├─ {date}-arxiv-cs.CV.{md,json}
│     ├─ {date}-arxiv-cs.GR.{md,json}
│     ├─ {date}-arxiv-cs.HC.{md,json}
│     ├─ {date}-manifest.json                    # 抓取 manifest
│     ├─ {date}-dedupe-meta.json                 # 去重 + 批次元数据
│     └─ scoring-batches-{date}/
│        ├─ batch-01.json                         # 输入
│        ├─ batch-01-scores.ndjson                # SubAgent 输出
│        └─ ... batch-NN.json / batch-NN-scores.ndjson
└─ recommendations/
   └─ {date}-arxiv-recommended.md                # 最终推荐输出
```

## Fixed paths

以下路径都相对当前仓库根目录解析：

- 配置：`.agents/skills/arxiv-daily/config.yaml`
- 中间产物根：`arxiv-daily/artifacts/`（可在 config 的 `artifacts_root` 改）
- 推荐文件根：`arxiv-daily/recommendations/`（可在 config 的 `recommendations_root` 改）
- 抓取脚本：`.agents/skills/arxiv-daily/scripts/fetch_arxiv.py`
- 批次脚本：`.agents/skills/arxiv-daily/scripts/prepare_batches.py`
- 包装脚本（macOS / Linux）：`run_fetch.sh` / `run_prepare_batches.sh`
- 包装脚本（Windows）：`run_fetch.ps1` / `run_prepare_batches.ps1`
- 推荐文件模板：`.agents/skills/arxiv-daily/assets/recommended-template.md`

所有 Python 调用都必须走仓库内的 `uv` 项目环境，不要直接调用裸 `python`。

## Accepted inputs

默认无需任何输入。可选：

- `--date YYYY-MM-DD`：指定抓取日期（UTC）。
  - 不传：走 RSS 路径，从 feed 自动推断 announcement UTC date（等同于"今天"）。
  - 传 UTC today：仍走 RSS。
  - 传历史日期（非 UTC today）：**自动切换到 arXiv Query API**（`http://export.arxiv.org/api/query`），按 `submittedDate:[D 00:00 TO D 23:59]`（GMT）拉取。语义 ≈ "当天提交的论文"；与 RSS 的 "announcement date" 可能相差 1–3 天（周末/节假日前后最明显），对历史回放通常可接受。
- `--source {auto,rss,api}`：手动覆盖抓取源，默认 `auto`（见上）；`api` 必须配合 `--date` 使用。
- 临时分类覆盖（例如用户明确说"只看 cs.LG 今天的"）

**短路行为**：无论日期是显式给的还是推断出的，一旦确定 `{date}`，检查 `<RECOMMENDATIONS_ROOT>/{date}-arxiv-recommended.md` 与 `<ARTIFACTS_ROOT>/{date}/{date}-manifest.json`。只有当推荐文件已存在，且 manifest 也存在并且 `status == "ok"`、所有 category `status` 都不是 `error` 时，才直接告诉用户"该日推荐已生成：`<路径>`；如需重跑请先删除该文件"，并**跳过 Step 2/3/4**。若 manifest 缺失或 `status in {"partial","error"}`，视为上次抓取未完成，**不要短路**，继续 Step 1 做补抓。

## Workflow

### Step 1 — Fetch

0. Read `config.yaml`，确认 `categories`、`artifacts_root`、`recommendations_root`、`score_threshold`、`max_recommendations`、`batch_size` 与 `interests` 都存在；将 `<ARTIFACTS_ROOT>` 设为 `artifacts_root`，将 `<RECOMMENDATIONS_ROOT>` 设为 `recommendations_root`
1. **预检（显式日期场景）**：若用户在本次调用里给出了具体日期 `{date}`，**先**查 `<RECOMMENDATIONS_ROOT>/{date}-arxiv-recommended.md` 与 `<ARTIFACTS_ROOT>/{date}/{date}-manifest.json`。仅当推荐文件存在且 manifest 完整（`status == "ok"` 且无 category error）时，才直接结束，回复用户「该日推荐已生成：`<路径>`，如需重跑请先删除该文件」。若 manifest 不完整，则继续执行 Step 1 以补抓缺失分类。
2. 若 `interests.narrative` 仍是占位符（含"请用中文或英文填写"等字样），停下让用户先填
3. 按 OS 选包装脚本：

   **macOS / Linux：**
   ```bash
   bash .agents/skills/arxiv-daily/scripts/run_fetch.sh \
     --config .agents/skills/arxiv-daily/config.yaml \
     --out-dir <ARTIFACTS_ROOT>
   ```

   **Windows：**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\.agents\skills\arxiv-daily\scripts\run_fetch.ps1 `
     --config .agents\skills\arxiv-daily\config.yaml `
     --out-dir <ARTIFACTS_ROOT>
   ```

4. 读 `<ARTIFACTS_ROOT>/{date}/{date}-manifest.json`
   - `status == "error"`：停止并把 `errors` 数组原样告知用户
   - `status == "partial"`：继续，但最终回复里列出失败的分类
   - `status == "ok"`：继续
   - 单个分类 status 可能是 `ok`（新抓）/ `skipped`（已存在复用）/ `error`（失败）
   - manifest 里 `announce_date` 是 `{date}` 的权威值；`announce_date_source` 为 `explicit` / `feed-inference` / `utc-today-fallback` / `api-explicit`（历史日期走 API 时使用；回退时应额外提示用户）
   - manifest 顶层 `source` 和每个 category 的 `source` 字段记录本次抓取走的是 `rss` 还是 `api`
   - 每个 category 会带 `filtered_out`，记录被丢弃的「跨日」条目数；汇总进 `warnings`（API 路径下该值恒为 0，因为 API 已按 `submittedDate` 精确过滤）
   - 若 manifest `warnings` 提示 "Recovered from a previous partial fetch..."，说明本次只是补齐了上次失败的分类；此时下游 `dedupe-meta.json` / 推荐文件可能仍是旧结果，后续 Step 2 必须加 `--force`
5. **二次预检（推断日期场景）**：从 manifest 拿到权威 `{date}` 之后，再次检查 `<RECOMMENDATIONS_ROOT>/{date}-arxiv-recommended.md` 与 manifest 完整性。仅当推荐文件存在且 manifest 完整时，才直接结束并回复用户「该日推荐已生成：`<路径>`，如需重跑请先删除该文件」，不再执行 Step 2/3/4

**幂等性：** 默认跳过已存在的当日输出，强制重抓加 `--force`。

**日期推断：** 不带 `--date` 运行时，脚本会先请求第一个 category 的 RSS，读首条 entry 的 `published` UTC date 作为本次 `{date}`；这次请求的 bytes 会被缓存复用、不会二次拉取。若所有 category 都失败，退而使用「UTC today」并在 warnings 中标注。

### Step 2 — Prepare batches

运行批次脚本。它会跨分类按 `arxiv_id` 去重（首次出现的分类为 `primary_category`，其余进 `extra_categories`），再按 `batch_size` 切片写入 `scoring-batches-{date}/`。

**务必显式传 `--date {date}`**，`{date}` 取自 Step 1 manifest 里的 `announce_date`（UTC）；否则脚本会回退到扫描 `<ARTIFACTS_ROOT>/` 下最新的 manifest，当目录里残留旧日期时会选错。

**macOS / Linux：**
```bash
bash .agents/skills/arxiv-daily/scripts/run_prepare_batches.sh \
  --config .agents/skills/arxiv-daily/config.yaml \
  --out-dir <ARTIFACTS_ROOT> \
  --date {date}
```

**Windows：**
```powershell
powershell -ExecutionPolicy Bypass -File .\.agents\skills\arxiv-daily\scripts\run_prepare_batches.ps1 `
  --config .agents\skills\arxiv-daily\config.yaml `
  --out-dir <ARTIFACTS_ROOT> `
  --date {date}
```

若 `{date}-dedupe-meta.json` 已存在会跳过；需要重切加 `--force`。**如果 Step 1 是在修复之前的 partial/error 抓取，必须加 `--force` 重新切批**，否则会继续沿用缺分类时生成的旧批次。读取 meta 拿到 `total`、`batch_count`、`batches` 列表后继续 Step 3。

### Step 3 — Score with SubAgents (parallel)

**为 `batches` 列表中的每一个 batch 启动一个 SubAgent**，在**同一条消息里并行发起**所有调用（按 Claude Code 的并行调用约定 `multiple Agent tool uses in a single message`）。每个 SubAgent 只处理一批，完成后退出。

**严格约束：**

- Step 3 只能由 SubAgent 产出评分结果；**禁止**主 Agent 自己读取 batch 后做关键词匹配、启发式排序、本地打分或任何其他代码兜底
- 只有对应 batch 的 `batch-NN-scores.ndjson` 被成功写出并通过校验，才算该批完成；没有合法 SubAgent 输出就视为该批未完成
- 若某个 batch 的 **SubAgent 启动失败**，必须立刻对**同一个 batch**重试启动 **1 次**，复用原来的 `{BATCH_PATH}` 与 `{SCORES_PATH}`
- 若重试后仍启动失败，**立即终止整个任务**，直接告知用户失败批次；**不要**继续其他批次的聚合，**不要**进入 Step 4，**不要**生成部分推荐结果

SubAgent 调用参数：

- `subagent_type`: `"general-purpose"`
- `description`: 形如 `"Score arxiv batch 03"`
- `prompt`: 用下面的模板，替换 `{BATCH_PATH}`、`{SCORES_PATH}`、`{THRESHOLD}`、`{NARRATIVE}`、`{BOOST}`、`{DEMOTE}`：

```
你是 arxiv-daily skill 的打分 SubAgent，只负责给一批 arXiv 论文打相关性分。

## 输入
- 批次文件（只读）：{BATCH_PATH}
- 用户兴趣描述 (interests.narrative)：
{NARRATIVE}
- keywords_boost：{BOOST}
- keywords_demote：{DEMOTE}
- 当前阈值：{THRESHOLD}（仅供参考，你仍需给出全部论文的分数，不要预过滤）

## 任务
1. 用 Read 工具打开 {BATCH_PATH}，里面是 `{"batch": N, "papers": [...]}`
2. 对 `papers` 里的**每一篇**给出相关性分数：
   - 与 narrative 的相关性 60%
   - 方法或选题新颖性 20%
   - 对用户实际可应用性 20%
   - 标题或摘要命中 boost 词 +5；demote 词主导 −10
   - 校准：90+ 立刻读、70–89 本周读、<70 忽略
3. 用 Write 工具把结果写入 {SCORES_PATH}，**NDJSON 格式**：每一行严格是一个 JSON 对象
   `{"arxiv_id":"<id>","score":<int 0-100>,"reason":"<一句中文，≤40 字，解释为什么这位研究者会感兴趣>"}`
   - 不要加 markdown fence、不要加额外解释、不要空行、不要数组包裹
   - 行数必须等于 papers 数，arxiv_id 顺序与输入保持一致

## 输出
写完 {SCORES_PATH} 后回复一行：`OK <N>` 其中 N 是写入的行数。出错时回复 `ERROR: <原因>`。
```

等待所有成功启动的 SubAgent 返回。逐一检查对应的 `batch-NN-scores.ndjson`：行数必须等于该批 papers 数，`arxiv_id` 顺序必须与输入一致；校验失败或 SubAgent 返回 `ERROR` 时，将该批记为失败批次并在最终回复中列出。**只有在所有 batch 都已成功启动（含最多一次重试后成功启动）时，才允许进入 Step 4。**

### Step 4 — Aggregate & write recommended.md

1. 读 `<ARTIFACTS_ROOT>/{date}/{date}-dedupe-meta.json`，以 `total` 和 `batches` 重新 Read 每个 `batch-NN.json`，重建 `arxiv_id → paper_metadata` 映射
2. 读每个 `batch-NN-scores.ndjson`，合并成 `arxiv_id → {score, reason}`
3. 过滤 `score < score_threshold`
4. 按 `score` 降序排序，分数相同时按 `arxiv_id` 升序稳定排序
5. 截取前 `max_recommendations` 条
6. 确保 `<RECOMMENDATIONS_ROOT>/` 存在，按 `assets/recommended-template.md` 的格式写 `<RECOMMENDATIONS_ROOT>/{date}-arxiv-recommended.md`（注意：**不写入 artifacts/{date}/**）：
   - 头部：阈值、命中数（阈值以上总数，即便超过 max_recommendations 也照写实际命中数）、扫描总数、覆盖分类
   - 每条：`## N. [标题](abs_link) — 分数/100` + 分类（有 `extra_categories` 时附 `（也出现在 X, Y）`）+ 作者 + 推荐理由 + 摘要 + PDF
   - **不要写 `作者备注` 行**（RSS 不提供 Comment）
7. 即便命中为 0，也要写一个合法的推荐文件并注明"本日无新投稿符合阈值"
8. 如果 `<RECOMMENDATIONS_ROOT>/{date}-arxiv-recommended.md` 已存在且本次是在补抓后重建，直接覆盖它；不要因为旧文件存在而提前退出

## Final response

完成后必须告知用户：

- 推荐文件路径（`arxiv-daily/recommendations/{date}-arxiv-recommended.md`）
- 当日 artifacts 子目录路径（`arxiv-daily/artifacts/{date}/`）
- 扫描总数、命中数、推荐输出条数
- 失败分类 / 失败批次列表（如果有）
- 如出现未填写 `narrative`、缺依赖、网络失败等阻断情况，单独列出并给出修复命令

若因为 SubAgent **启动失败且重试后仍失败**而提前终止，则必须改为明确告知用户：

- 失败批次编号与对应的 batch 文件路径
- 已执行到 Step 3，但因 SubAgent 无法启动而中止
- 本次**没有**进入 Step 4，且**没有**使用任何本地关键词匹配或代码兜底打分

## Future extensions

- **作者 Comment（`Comment: 12 pages, accepted to SIGGRAPH`）**：arXiv 2023+ 的新 RSS 格式完全不暴露 Comment 字段（description 只有 `arXiv:ID Announce Type / Abstract`，作者走 `dc:creator`）。arXiv Query API 的 Atom 输出里有 `<arxiv:comment>`，若要全链路拿 Comment，可在 API 路径的 `parse_entry` 里一并抽取
- 与 `paper-reader` 联动：推荐列表点链接直接触发深读
- 订阅过滤后自动发送到其他渠道（邮件、Slack）
