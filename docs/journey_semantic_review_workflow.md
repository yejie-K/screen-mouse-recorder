# 游戏历程语义复核与统一事件契约

> v2主链路已经拆成功能事件线和指标跟踪线，见 [journey_pipeline_v2.md](journey_pipeline_v2.md)。本文件描述的五维语义字段作为 v1 兼容契约继续保留。当前工作台只复核功能事件，编辑 `mode_tag`、`event_tag`、游戏术语和备注；等级、战力等指标快照不进入该工作台。

## 目标

将规则初分和大模型语义候选转换为经过人工确认的统一事件文件，供 XLSX、开放节奏图、成长反馈图和情绪时间图共同读取。

## 权限边界

1. `journey_semantic_input.json` 保存人工确认的事件事实和规则初分。
2. `journey_semantic_output.json` 是 AI 候选，`review_status` 只能为 `needs_review` 或 `excluded`。
3. `journey_semantic_review.json` 保存人工决定和受限修正。
4. `confirmed_semantic_events.json` 是正式统一数据源；只有人工复核文件可以产生 `confirmed`。`manual_frame_review.json` 中已确认的人工事件属于上游人工事实，生成复核包时直接标记为确认；功能事件工作台只处理OCR自动候选。

AI 和复核 overrides 均不得修改：`event_id`、事件名称、事件时间、事件类型和证据引用。

## 生成复核模板

```powershell
python tools/validate_journey_semantic_output.py `
  journey_semantic_input.json `
  journey_semantic_output.json `
  --report semantic_validation_report.json `
  --review-template journey_semantic_review.json
```

校验不通过时不会生成复核模板。

## 人工复核

每个 decision 有三种状态：

- `pending`：尚未完成，不能进入正式图表。
- `confirmed`：接受候选或接受 overrides 后的结果。
- `excluded`：保留审计记录，但不进入正式分析。

允许在 `overrides` 修正：分类、多标签、玩家行为、系统反馈、规则 ID、重复关系、产出关系和置信度。禁止填写事件事实字段。

只要存在 `confirmed` 或 `excluded`，`reviewer` 和 `reviewed_at` 必须填写。

### 本地复核工作台

推荐通过独立本地网页复核，不直接手改 JSON：

```powershell
python tools/serve_journey_semantic_review.py `
  journey_semantic_input.json `
  journey_semantic_output.json `
  journey_semantic_review.json `
  --confirmed-output confirmed_semantic_events.json `
  --game-profile game_profiles/qingyun_jue_fumo.json `
  --game-id qingyun_jue_fumo `
  --game-name 青云诀之伏魔 `
  --evidence-root <ocr_review目录> `
  --port 8766
```

页面默认优先展示OCR自动候选中的重点冲突项，支持证据图、OCR原文、两组事件标签修正、确认、排除、批量确认和同游戏术语沉淀。人工选帧事件不会出现在该页面，但仍保留在 `confirmed_semantic_events.json` 中。服务只监听本机 `127.0.0.1`。指标线不在事件工作台中确认，使用 `tools/serve_metric_review.py`、`journey_metric_review.json` 和 `confirmed_metric_observations_v2.json`，具体见 `docs/journey_pipeline_v2.md` 第5.2节。

当前语义输入固定为 `schema_version=1.1`。新运行必须通过 `tools/sync_journey_workspace.py` 合并人工/自动事件并生成同源复核包；页面不得自行选择其他目录的语义文件。`prepare_event_review_v2.py` 与 `migrate_semantic_input_v1.py` 只保留给历史审计和显式迁移。完整版本和指纹链接见 `docs/journey_contract_matrix.md`。

## 游戏术语词典

- 全局 taxonomy 只保存跨游戏抽象类别，不保存“仙术一定属于养成”等游戏特例。
- OCR/人工事件名作为当前游戏术语，先做 Unicode 规范化后的精确匹配，不跨游戏模糊套用。
- 只有人工确认事件并勾选“加入本游戏术语词典”时，才写入该游戏 profile。
- profile 只保存术语与分类映射，不保存截图、时间或 session 私有数据。
- 相同游戏后续 session 可复用 profile 候选，但仍需人工确认；其他游戏使用独立 profile。

词典结构见 `schemas/game_semantic_profile.schema.json`。

## 生成统一确认事件

```powershell
python tools/finalize_journey_semantic_review.py `
  journey_semantic_input.json `
  journey_semantic_output.json `
  journey_semantic_review.json `
  --output confirmed_semantic_events.json
```

存在 pending 或缺少 AI 候选时，仍会输出审计文件，但顶层 `status` 为 `needs_review`，命令返回码为 1。全部处理完成后 `status` 才是 `complete`。

情绪分值不接受人工直接填写；终结器根据已确认规则 ID、重复次数和特殊叠加重新计算。

## 下游读取规则

- 正式 XLSX 和图表只读取 `semantic_review.status == confirmed` 的事件。
- 指标表和成长反馈图只读取 `confirmed_metric_observations_v2.json` 中 `review.status == confirmed` 的指标。
- `excluded` 事件保留在文件中供追溯。
- `status != complete` 时不得标记整份分析为正式完成。
- 修改本契约时同步检查两个 semantic schema、最终事件 schema、CLI、图表 Agent 报告和 `docs/ocr_manual_event_workflow.md`。
