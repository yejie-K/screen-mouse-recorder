# 历程拆解链路契约矩阵

本文档是“每个页面实际读写什么”的唯一总表。新运行必须先生成 `journey_workspace.json` 1.0，所有页面只从该工作空间解析同一 Session 的相对路径。各文件的 `schema_version` 是**该文件自身的契约版本**，不是产品全局版本，因此允许同时出现1.0、1.1和2.0；禁止的是未声明转换、静默兼容和错用历史输出。

## 页面与文件

| 顺序 | 页面 / 工具 | 只读输入 | 人工状态 | 正式输出 | 契约版本 |
|---|---|---|---|---|---|
| 0 | 工作空间初始化 | Session、可选 `analysis_handoff.json`、MP4、抽帧索引/拼图 | 无 | `journey_workspace.json`、完整runtime | handoff 1.0 / workspace 1.0 |
| 1 | 人工选帧 `:8767/manual/` | `review_session.json`、MP4、拼图 | `manual_frame_review.json` | `selected_ocr_tiles.json` 兼容适配 | manual 1.0 / selected 1.0 |
| 2 | 区域校准 `:8767/regions/` | 区域草稿、人工帧库 | `ocr_region_profile.json` | `status=complete` 的区域profile | profile 1.1 |
| 3 | 全量区域OCR | 抽帧索引、完整区域profile | 无，算法只产候选 | `event_observations_v2.json`、`metric_observations_v2.json` | observations 2.0 |
| 4A | 工作空间同步 | 区域事件候选 + 人工选帧 | 初始化pending复核模板 | 合并事件候选、语义复核包、指标复核包 | observations 2.0 / input 1.1 / review 1.0 |
| 4B | 功能事件 `:8767/events/` | 语义输入1.1、候选1.0 | `journey_semantic_review.json` | `confirmed_semantic_events.json` | review/final 1.0 |
| 5 | 指标结果 `:8767/metrics/` | `metric_observations_v2.json` | `journey_metric_review.json` | `confirmed_metric_observations_v2.json` | candidates/final 2.0，review 1.0 |
| 6 | 最终产物 | 两条人工确认结果 | 无 | XLSX、三张图、Agent报告 | final manifest 1.0 |
| 6P | 候选预览 | 当前事件/指标候选 | 无，不改变复核状态 | 标明待复核的XLSX、三张预览图、Agent报告 | preview manifest 1.0 |

## 强制链接规则

1. 同一次区域扫描的事件与指标候选必须具有相同 `source_fingerprint` 和 `session.session_id`。
2. 区域扫描 `source_fingerprint` 必须等于当前工作空间 `sha256(index bytes + profile bytes)`；文件存在但指纹不符时状态是 `stale`，事件/指标路径只显示阻塞页，不挂载可写复核API。
3. 新链路的复核包必须由 `tools/sync_journey_workspace.py` 生成。它把未排除的人工帧作为 `manual` 事件候选，与自动事件候选合并；不读取历史语义包。
4. `journey_semantic_input.json` 当前只接受1.1，新链路不执行运行时迁移或静默补字段。
5. 语义候选、语义复核和确认事件的 `source_fingerprint` 必须与语义输入一致。
6. 指标复核与确认指标的 `source_fingerprint` 必须与指标候选一致；候选内容变化时禁止沿用旧人工决定。
7. `manual_frame_review.json` 的 `rejected` 在汇总时直接排除。人工候选即使已在选帧页确认，进入语义线时仍为 `pending`。
8. `selected_ocr_tiles.json` 的 `source_index`、`source_video` 必须指向工作空间内真实文件。人工候选清空后必须删除旧适配文件。
9. `outputs/`、`experiments/` 内复制的schema只属于对应历史产物；开发与新运行一律以仓库根目录 `schemas/` 为准。
10. 正式生成器必须先通过final gate，只读取人工确认事件和指标。未确认记录不得进入XLSX或三张正式图。
11. 新工作空间的正式区域扫描必须保存 `region_crops/`。指标候选的 `evidence.crop_images` 至少包含一个真实存在的局部证据文件；关闭证据图只允许用于debug扫描。
12. 录屏端与分析端仅通过Session文件契约交换数据，检测和回退顺序以 [recorder_analysis_handoff_contract.md](recorder_analysis_handoff_contract.md) 为准。合法交接必须直接复用；需要重建时两端只能使用 `CLICK_SUMMARY_V1`。

## 新链路标准命令

```powershell
python tools/prepare_journey_workspace.py `
  <session目录> <点击抽帧索引.json> <workspace目录> `
  --game-id <game_id> --game-name <game_name> `
  --region-profile <ocr_region_profile.json>
```

区域扫描完成后：

```text
python tools/sync_journey_workspace.py <workspace目录>
python tools/serve_journey_workspace.py <workspace目录>
```

正式页面全部由同一个 `127.0.0.1:8767` 服务提供。四个独立 `serve_*_review.py` 入口仅保留用于模块诊断，不再构成正式页面导航。

两条复核均完成后：

```powershell
python tools/check_journey_workspace.py <workspace目录> --final-gate
python tools/generate_journey_final.py <workspace目录>
```

需要暂时跳过大批量复核、继续验证下游产物时：

```powershell
python tools/generate_journey_preview.py <workspace目录>
```

预览固定写入 `preview/`，状态为 `draft`，不得覆盖或冒充 `final/`。

`prepare_event_review_v2.py` 和 `migrate_semantic_input_v1.py` 仅用于审计或历史数据人工迁移，不属于新工作空间默认链路。

## 当前完成边界

- 录屏、抽帧、人工选帧、区域校准、全量区域OCR、功能事件复核和指标复核均已有文件契约。
- 新工作空间已固定人工事件、区域扫描、事件复核、指标复核和最终产物的相对路径与状态门禁。
- 统一生成器输出带事件截图的XLSX、玩法系统开放节奏图、最终情绪图、成长反馈图和Agent说明。
