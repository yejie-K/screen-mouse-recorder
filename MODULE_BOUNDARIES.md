# MODULE_BOUNDARIES

本文件说明 `screen_mouse_recorder` 包内各模块的职责边界、依赖方向和独立发布能力。任何 Agent 或开发者在新增依赖、移动函数、拆分模块前必须先读本文件，避免把已经解耦的模块重新耦合回去。

## 1. 依赖分层

底层到上层，箭头表示“依赖”，禁止反向依赖：

```text
                media_utils           models
                (ffmpeg/时间码)        (数据结构)
                  ↑     ↑                 ↑
        ┌─────────┘     └─────────┐       │
   frame_export              event_extraction (OCR)
   (录屏抽帧/拼图)             (点击帧 OCR 事件)
        ↑
   recorder 核心
   (app/cli/mouse_logger/video_recorder/…)

   journey_analysis (历程拆解出图/语义/复核) —— 完全自足，谁都不依赖
```

## 2. 三条可独立发布的功能线

| 功能线 | 目录 | 职责 | 对外依赖 |
|---|---|---|---|
| **recorder（录屏核心）** | `app.py` `cli.py` `mouse_logger.py` `video_recorder.py` `frame_export/` `region_selector.py` `storage.py` `reporting/` `diagnostics/` `updater.py` `ui/` | 区域录屏、鼠标事件采集、抽帧拼图、行为分析报告、GUI | `media_utils`、`models`、标准库、PIL、openpyxl |
| **ocr（事件识别）** | `event_extraction/` | 从点击关键帧做 OCR，产出候选事件表 | `media_utils`（仅此），rapidocr、openpyxl、PIL |
| **journey（历程拆解）** | `journey_analysis/`、历程CLI | 语义分类/复核/情绪评分/三类图表生成 | 自足，只读 JSON/schema，不引用包内其他业务模块 |

`tools/serve_journey_workspace.py` 是应用装配层，不属于 `journey_analysis` 业务模块。它可以同时装配 `event_extraction` 与 `journey_analysis` 的工作区对象，但不得把任一模块的业务类型写入另一模块；两条线之间仍只通过工作空间文件契约交换数据。

## 3. 硬性边界规则

1. **`media_utils` 保持中立**：只放依赖标准库 + PIL 的通用视频/时间码原语（`resolve_ffmpeg`、`resolve_ffprobe`、`extract_frame`、`extract_preview_frame`、`parse_fps`、`parse_timecode`、`format_timecode`）。禁止在此引入任何业务模型（如 `VideoInfo`）。需要业务模型的函数（如 `probe_video`）留在拥有该模型的模块里。
2. **OCR 不得再 import `frame_export`**：OCR 需要的抽帧/时间码能力一律走 `media_utils`。这是 2026-07-21 解耦的核心成果，不要回退。
3. **journey_analysis 不得依赖 recorder / OCR / GUI**：它只能读取已确认的 JSON 数据源，输入靠文件契约而非直接调用。
4. **GUI（app.py）不得直接依赖 OCR / journey_analysis**：这两条线通过 `cli.py` 和 `tools/*.py` 挂接，保证录屏本体可独立运行。
5. 移动函数时优先用 **re-export 保持旧 import 路径可用**（见 `frame_export/ffmpeg_io.py`、`frame_export/timecode.py`），避免大面积改调用点。
6. **人工选帧只通过文件契约跨线**：`journey_analysis.manual_frame_review` 写 `manual_frame_review.json` / `selected_ocr_tiles.json`；`event_extraction` 只能按显式路径读取这些文件，不得 import `journey_analysis`。区域页读取人工帧只用于候选与校准，不能绕过人工确认。
7. **统一网页服务只做装配与路由**：单端口工作台可以持有多个模块工作区对象，但不得在HTTP层复制业务判定、修改候选权限或绕过 `stale` / final gate。独立页面服务仅用于诊断，并继续复用同一工作区类。

## 4. 兼容别名

`media_utils` 保留下划线旧别名 `_extract_frame`、`_parse_fps`，兼容历史引用。新代码请用公共名 `extract_frame`、`parse_fps`。

## 5. 变更本文件的时机

- 新增一个可独立发布的功能线
- 调整模块依赖方向
- 把某个函数在模块间搬家

每次改动同时在 `docs/DEV_LOG.md` 追加一条记录。
