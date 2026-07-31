# OCR Manual Event Workflow

本文档定义“人工选帧 OCR 结构化流程”。它给后续 AI 或开发者使用，目标是把人工从抽帧大图里选出的关键帧，稳定转换为可复核的 JSON / Excel 事件输出。

本流程是 [游戏历程拆解主链路 v2](journey_pipeline_v2.md) 的步骤3至5。抽帧覆盖率、点击后延迟帧、哨兵帧和去重策略由证据提取层负责；本流程负责：

```text
人工高置信帧 + 自动候选帧 -> 粗OCR -> 区域校准
-> 全部抽帧逐张裁剪确认区域 -> 局部OCR -> 分线复核
```

## 1. Workflow Position

推荐链路：

```text
recording.mp4 + mouse_events.jsonl
-> click keyframe contact sheets
-> human reviews contact sheets and selects useful tiles
-> system resolves selected tiles to source frames / frame metadata
-> OCR runs on source frame or crop, not on the contact sheet tile
-> event_ocr_results.json / event_ocr_results.xlsx
-> human confirms reusable OCR regions
-> ocr_region_profile.json
-> crop confirmed regions from every frame in the extraction index
-> event_observations_v2.json + metric_observations_v2.json
```

关键原则：

- Contact sheet 适合人工快速浏览。
- 初始粗OCR使用少量代表帧发现区域；区域确认后，对抽帧索引中的全部原始帧只做局部OCR。
- 时间戳和帧编号优先来自 index / manifest，不依赖 OCR。
- OCR 识别出的时间戳只作为校验或候补。
- 每条事件输出必须能返回到原图和合成图位置复核。
- 功能事件使用 `mode_tag + event_tag`；等级和战力等指标不使用事件标签，进入独立指标结果线。
- 区域候选必须经过 `serve_ocr_region_profile_review.py` 人工确认；`scan_ocr_regions.py` 不接受未完成的profile。
- 区域工作台允许人工新增指标区域；新增项始终从 `needs_review` 开始，需在最多3张代表帧上校准同一位置并选择指标类型/数值格式后确认。
- 人工选帧正式状态写入 `manual_frame_review.json`，并自动适配现有 `selected_ocr_tiles.json`；`localStorage` 不再是事实源。完整契约见 `docs/manual_frame_review_workflow.md`。
- `manual_frame_review.json` 中已确认的功能/技能事件视为人工事实，直接进入统一确认事件，不在功能事件页重复复核；功能事件页只处理局部OCR扫描产生的自动候选。
- 区域页从人工帧库选择最多3张样本后，可对框内区域运行RapidOCR并自动建议指标类型/数值格式；建议仍为待人工确认状态。
- 扫描器逐个索引帧只提取一次原始画面，再对该画面的全部确认区域分别裁剪OCR；不会重复做整图OCR。
- 连续相同指标值和连续相同功能事件在结果层合并，保留首尾时间、命中帧数和最高置信证据。
- 正式区域扫描可由区域复核页后台发起；进度、失败错误码和输出目录通过本地状态API展示。多区域批量OCR只减少模型调用次数，不合并不同区域的结果。

## 2. Existing Source Files

点击抽帧当前主要输出：

```text
frame_exports/<export_name>/
  keyframes_click_sheet.png
  keyframes_click_sheet_index.json
```

如果分多张图，文件名可能为：

```text
keyframes_click_sheet_001.png
keyframes_click_sheet_002.png
keyframes_click_sheet_index.json
```

`keyframes_click_sheet_index.json` 是 OCR 事件链路的主索引。后续 AI 应优先读取它，而不是从图片左上角 OCR 时间。

当前索引中的重要字段：

```json
{
  "events_total": 1800,
  "events_kept": 120,
  "events_skipped": 1680,
  "selection": {
    "strategy": "cluster_head_tail_for_large_clusters_plus_visual_change",
    "selection_reason_counts": {
      "single": 20,
      "cluster_start": 60,
      "cluster_end": 30,
      "visual_change": 10
    }
  },
  "frames": [
    {
      "index": 22,
      "event_id": "evt_000022",
      "event_type": "click",
      "source_index": 135,
      "seconds": 105.0,
      "timestamp": "00:01:45",
      "video_x": 210.0,
      "video_y": 480.0,
      "sheet": "keyframes_click_sheet.png",
      "sheet_row": 5,
      "sheet_col": 2,
      "selection_reason": "single",
      "cluster_index": 18,
      "cluster_size": 1,
      "visual_diff": null
    }
  ]
}
```

## 3. Contact Sheet Standards

合成大图上的每个格子必须满足：

- 左上角显示帧编号：`#022`
- 左上角显示视频时间：`00:01:45`
- 编号从 1 开始，和 index JSON 中 `frames[].index` 对齐。
- `sheet_row`、`sheet_col` 从 1 开始，便于人工描述“第几行第几列”。

这些文字是给人看的，不是主数据源。

主数据源优先级：

```text
keyframes_click_sheet_index.json
> frame export manifest / index.csv
> source file naming
> OCR text from image
```

## 4. Human Selection Input

人工选帧可以先用最简单的 JSON 表达。推荐文件名：

```text
selected_ocr_tiles.json
```

推荐结构：

```json
{
  "schema_version": "1.0",
  "source_index": "D:/.../keyframes_click_sheet_index.json",
  "selections": [
    {
      "sheet": "keyframes_click_sheet.png",
      "tile_index": 22,
      "note": "新功能开启：单人BOSS",
      "source_frame": "D:/optional/original_frame_000022.png"
    },
    {
      "sheet": "keyframes_click_sheet.png",
      "tile_index": 147,
      "note": "新技能解锁"
    }
  ]
}
```

允许人工只填 `tile_index`。如果同一个导出目录存在多张 sheet，则应同时填 `sheet`。

`source_frame` 是可选字段。提供后优先 OCR 该原图；未提供时从 `recording.mp4` 对应时间抽帧；两者都没有时才回退裁剪 contact sheet tile。

## 5. OCR Input Rule

OCR 目标按优先级选择：

1. 原始视频在该时间点抽出的完整帧。
2. 原始视频在该时间点抽出的局部裁剪帧。
3. 已经保存的单帧图片。
4. Contact sheet 中裁下来的 tile。

除非无法反查原始帧，否则不要直接 OCR 整张 contact sheet。

对于“新功能开启 / 新技能解锁 / 奖励弹窗”：

- 可以先全图 OCR，因为弹窗文字较大。
- 如果后续要提速，可以裁剪中间弹窗区域。

对于“战力 / 等级 / 固定状态栏”：

- 推荐先通过前 1-3 分钟全图 OCR 建立关注区域。
- 后续只裁固定小区域。
- 固定小区域可使用 OCR `use_det=false`，跳过文字检测，提高速度。

## 6. OCR Engine Recommendation

当前实验推荐：

```text
Engine: RapidOCR ONNX Runtime
Package tested: rapidocr-onnxruntime 1.4.4
License: Apache-2.0
Default models: ch_PP-OCRv4_det_infer.onnx / ch_PP-OCRv4_rec_infer.onnx
```

实测结论：

- 全屏帧 OCR：约 1-3 秒/张，适合建图和少量关键帧。
- 固定战力小区域，关闭检测只识别：约 0.06 秒/张。
- 中文可能有错字，例如 `战力` 被识别为 `成力`，但关键数字和大标题通常可用。

## 7. Event Output

推荐输出文件名：

```text
event_ocr_results.json
event_ocr_results.xlsx
```

对应 Schema：

```text
schemas/selected_ocr_tiles.schema.json
schemas/event_ocr_results.schema.json
```

JSON 顶层结构：

```json
{
  "schema_version": "1.0",
  "workflow": "manual_selected_frame_ocr",
  "source": {
    "video": "D:/.../recording.mp4",
    "index_json": "D:/.../keyframes_click_sheet_index.json",
    "selection_json": "D:/.../selected_ocr_tiles.json",
    "ocr_engine": "rapidocr-onnxruntime",
    "ocr_engine_version": "1.4.4"
  },
  "events": []
}
```

每条事件必须包含：

```json
{
  "event_id": "ocr_evt_000001",
  "event_type": "new_feature_unlocked",
  "event_name": "单人BOSS",
  "timestamp": "00:01:45",
  "seconds": 105.0,
  "frame_index": 22,
  "source_frame": "D:/.../frames/frame_000022.jpg",
  "contact_sheet": "D:/.../keyframes_click_sheet.png",
  "contact_sheet_tile": 22,
  "sheet_row": 5,
  "sheet_col": 2,
  "ocr_text": "#022 00:01:45 单人BOSS 新功能开启 任务奖励 5900 5000",
  "ocr_time_text": "00:01:45",
  "time_source": "index_json",
  "time_check": "matched",
  "confidence": 0.9,
  "review_status": "pending",
  "notes": ""
}
```

必填字段：

- `event_id`
- `event_type`
- `event_name`
- `timestamp`
- `seconds`
- `frame_index`
- `contact_sheet`
- `contact_sheet_tile`
- `sheet_row`
- `sheet_col`
- `ocr_text`
- `time_source`
- `time_check`
- `review_status`

如果暂时没有 `source_frame`，也必须保留字段并填空字符串：

```json
"source_frame": ""
```

## 8. Event Types

第一版事件类型：

```text
new_feature_unlocked
new_skill_unlocked
reward_popup
combat_power_snapshot
level_snapshot
task_progress
ui_opened
unknown
```

分类规则：

- OCR 包含 `新功能开启`：`new_feature_unlocked`
- OCR 包含 `新技能解锁`：`new_skill_unlocked`
- OCR 包含 `获得`、`奖励`、`领取`：`reward_popup`
- OCR 包含 `战力`、`成力`、`诚力`、`城力` 且有数字：`combat_power_snapshot`
- OCR 包含 `级`、`转生` 且位于顶部状态区域：`level_snapshot`
- OCR 包含 `任务`、`完成`、`前往`：`task_progress`
- 只打开界面但没有明确事件：`ui_opened`
- 无法判断：`unknown`

## 9. Event Name Extraction

`event_name` 的推荐提取方式：

- `new_feature_unlocked`：取 `新功能开启` 上方或附近最大的标题文字，例如 `单人BOSS`、`仙术`。
- `new_skill_unlocked`：取技能名，例如 `大圣归来`。
- `combat_power_snapshot`：取标准化数值，例如 `35.56万`。
- `reward_popup`：取奖励摘要，例如 `灵气x6; 绑定元宝x12`。

如果 OCR 文本不完整，允许填：

```json
"event_name": "待人工确认"
```

同时把 `review_status` 设为：

```json
"review_status": "needs_review"
```

## 10. Time Check

事件时间优先来自索引：

```text
index_json timestamp -> source metadata -> OCR fallback
```

`time_check` 可选值：

```text
matched
ocr_missing
ocr_mismatch
fallback_from_ocr
not_checked
```

使用规则：

- index 有时间，OCR 也读到相同或接近时间：`matched`
- index 有时间，OCR 没读到时间：`ocr_missing`
- index 有时间，OCR 时间明显不同：`ocr_mismatch`
- index 缺失，只能用 OCR 时间：`fallback_from_ocr`
- 未做 OCR 时间校验：`not_checked`

## 11. Review Return Mark

每条事件都要有返回标，方便复核。

最小返回标：

```json
{
  "contact_sheet": "D:/.../keyframes_click_sheet.png",
  "contact_sheet_tile": 22,
  "sheet_row": 5,
  "sheet_col": 2,
  "frame_index": 22,
  "timestamp": "00:01:45"
}
```

推荐返回标：

```json
{
  "source_frame": "D:/.../frames/frame_000022.jpg",
  "source_video": "D:/.../recording.mp4",
  "source_video_seconds": 105.0,
  "contact_sheet": "D:/.../keyframes_click_sheet.png",
  "contact_sheet_tile": 22,
  "sheet_row": 5,
  "sheet_col": 2
}
```

## 12. AI Usage Prompt

其他 AI 处理本软件输出时，可使用以下任务说明：

```text
你将收到 Screen Mouse Recorder 的点击抽帧索引 keyframes_click_sheet_index.json、
人工选帧 selected_ocr_tiles.json，以及对应图片文件。

请不要依赖图片左上角 OCR 出来的时间作为主时间。
主时间、帧编号、合成图位置必须来自 keyframes_click_sheet_index.json。

对人工选中的每个 tile：
1. 用 index_json 找到 frame_index、timestamp、seconds、sheet、sheet_row、sheet_col。
2. 优先 OCR 原始帧或原始裁剪帧；没有原始帧时才 OCR contact sheet tile。
3. 根据 OCR 文本判断 event_type。
4. 提取 event_name。
5. 输出 event_ocr_results.json，保留 ocr_text 和所有返回复核字段。
6. 不确定时不要编造，event_name 填“待人工确认”，review_status 填 needs_review。
```

## 13. Known Limits

本流程不解决：

- 点击瞬间没有截到结果帧。
- 关键事件没有点击触发。
- 视频抽帧策略漏掉自动弹窗。
- OCR 模型对小字、模糊字、遮挡字识别错误。

这些问题属于抽帧覆盖率和识别策略优化，不阻塞人工选帧 OCR 结构化流程。

## 14. Development Rules For Future Work

后续落地时遵循当前项目约定：

- 不把实验脚本直接混入主程序模块。
- OCR 相关代码应作为独立模块接入，例如 `ocr/` 或 `event_extraction/`。
- 主程序现有录制、抽帧、自动报告链路不应被 OCR 实验影响。
- 输出 JSON 必须带 `schema_version`。
- 任何会改变输出字段、文件命名、目录结构、事件类型、时间来源优先级或复核返回标的更新，都必须同步检查并更新本文档。本文档视为给其他 AI / 外部流程使用的接口文档。
- 任何 OCR 错误都应进入错误报告机制，使用稳定错误码，例如 `OCR-RUN-001`。
- 大文件、临时实验结果、私有视频样本不提交到公开仓库。
- UI 入口后置，先稳定文件输入输出契约。

## 15. API Position

当前阶段不建议做 HTTP API 或常驻服务。优先把稳定文件契约当作第一版 API：

```text
Input:
  keyframes_click_sheet_index.json
  selected_ocr_tiles.json
  recording.mp4 / source frame images

Output:
  event_ocr_results.json
  event_ocr_results.xlsx
  ocr_review/
```

当已确认事件继续生成玩法开放时间图时，图表目录同时输出可交接文件：

```text
charts/
  chart_gameplay_open_timeline_draft.png
  chart_gameplay_open_timeline_report.json
  chart_gameplay_open_timeline_agent_spec.json
  chart_gameplay_open_timeline_agent_report.md
  chart_gameplay_open_timeline_contract.md
```

其中 PNG 只是视觉结果；其他 agent 应优先读取 `agent_report.md` 理解图表，再读取 `agent_spec.json` 获取完整绘图输入、分类映射、颜色、布局、证据引用和可编辑边界。不得通过反推 PNG 修改事件事实。

AI语义候选、人工复核和统一确认事件的权限边界及CLI见 `docs/journey_semantic_review_workflow.md`。功能事件的正式 XLSX 和图表读取 `confirmed_semantic_events.json`；战力、等级和转生等指标读取 `confirmed_metric_observations_v2.json` 中人工确认的指标。两类下游都不得直接把 OCR / AI 候选当作确认事实。事件桥接和指标复核命令分别见 `docs/journey_pipeline_v2.md` 第5.1、5.2节，完整版本关系见 `docs/journey_contract_matrix.md`。

新运行不再手工拼接上述文件路径：先用 `tools/prepare_journey_workspace.py` 生成 `journey_workspace.json`，区域扫描后用 `tools/sync_journey_workspace.py` 合并人工/自动事件并初始化两类复核，使用 `tools/serve_journey_workspace.py` 统一启动页面。旧版单文件桥接和迁移命令只用于历史审计。

原因：

- 本软件是本地桌面工具，文件输入输出最容易复核和调试。
- 其他 AI 可以直接读取 JSON / Excel / 图片，不需要额外服务。
- 文件契约更适合当前半自动流程，也便于人工插入、修正和回滚。

后续如果需要程序化调用，优先顺序是：

1. Python 内部函数：`extract_selected_ocr_events(...)`，供 UI 调用和测试。
2. CLI 命令：`start_recorder.cmd ocr-events selected_ocr_tiles.json --index keyframes_click_sheet_index.json --video recording.mp4`。
3. HTTP API：只有在需要外部系统远程调用或多人服务化部署时再做。

因此现阶段“接口”指本文档定义的文件契约，不指网络 API。

外部产品如果需要机器可读进度，可以增加可选参数：

```powershell
start_recorder.cmd ocr-events selected_ocr_tiles.json `
  --index keyframes_click_sheet_index.json `
  --video recording.mp4 `
  --json-progress
```

输出为逐行 JSON，不带该参数时仍保持原有终端进度格式：

```json
{"stage":"ocr","current":1,"total":3,"message":"OCR 00:01:45 #022"}
{"stage":"completed","current":3,"total":3,"message":"OCR 完成"}
{"stage":"result","events":3,"needs_review":0}
```

## 16. Compatibility Policy

`schema_version: 1.0` 当前视为已冻结接口。

- 不删除或重命名现有字段。
- 不改变现有字段的数据类型和含义。
- 不改变现有 CLI 参数、输出文件名和目录结构。
- 新字段只能作为可选字段增加。
- 新 CLI 能力只能通过可选参数增加，未使用新参数时行为保持不变。
- 每次修改 OCR 输入输出前，必须同步检查本文档、两份 JSON Schema 和契约测试。
- 破坏性修改必须使用新的 `schema_version`，并保留 1.0 输出能力，不能直接覆盖。

## 17. Contract Changelog

### 1.0 - 2026-07-13

- 固定 `selected_ocr_tiles.json` 输入结构。
- 固定 `event_ocr_results.json` 输出结构。
- 固定索引时间优先、OCR 时间校验规则。
- 固定原图、合成图和行列返回标。
- 增加与现有格式一致的 JSON Schema。
- 增加可选 `--json-progress`，未改变原 CLI 行为。
