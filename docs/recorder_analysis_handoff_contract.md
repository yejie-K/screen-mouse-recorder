# 录屏端与历程分析端交接契约

本文档定义两个独立软件如何只通过 Session 文件夹交换资料。录屏端和分析端可以位于同一仓库，但必须保持独立入口、独立打包和独立目录所有权。

## 1. 软件职责

| 软件 | 负责 | 不负责 |
|---|---|---|
| `ScreenRecorder` | 录屏、鼠标记录、停止录制后自动生成去重抽帧索引和合成图 | OCR、人工复核、XLSX和历程图 |
| `JourneyAnalyzer` | 选择Session、人工选帧、区域校准、OCR、复核、XLSX和图表 | 录屏和鼠标采集 |

录屏端新产物只写 `auto_report/`。分析端只写 `analysis_output/`。历史录屏报告可能位于 `analysis_output/`，只能兼容读取，不再作为录屏端新写入位置。

## 2. 标准 Session

```text
<Session>/
  recording.mp4
  mouse_events.jsonl
  session_meta.json
  auto_report/
    analysis_handoff.json
    keyframes_click_sheet_*.png
    keyframes_click_sheet_index.json
  analysis_output/
    journey_workspace/
```

在SC源码环境中，浏览选择推荐直接选中包含 `recording.mp4` 的具体时间Session，例如 `D:\screen_capture\sessions\recordings\<session_id>`。也可以选择其父级 `recordings` 或 `sessions` 作为资料库，分析工具会递归发现多个Session。不要选择 `auto_report/`、单独的图片目录或MP4文件本身；浏览控件接收的是Session文件夹。

`analysis_handoff.json` 使用 `schemas/analysis_handoff.schema.json` 1.0。所有路径相对 `session_root`，不得写入开发机绝对路径。清单记录源文件大小和SHA256、抽帧策略、索引、拼图列表及统计；分析端校验失败时不得静默信任旧产物。

## 3. 唯一抽帧策略

正式策略ID固定为 `CLICK_SUMMARY_V1`：

- 时间聚类 `1.5s`
- 距离聚类 `80px`
- 视觉变化阈值 `22%`
- 大簇尾帧：至少5次点击或持续2秒
- 静默补帧 `10s`，长静默阈值 `25s`，每段最多5帧
- 不纳入双击和拖动
- 默认不限制总帧数

参数唯一来源是 `frame_export/presets.py`。录屏自动报告与分析端备用生成必须调用同一个 `build_click_summary_config()`；CLI不得形成第二套阈值。

## 4. 分析端检测与备用顺序

1. 存在且通过校验的 `auto_report/analysis_handoff.json`：直接复用，不重新抽帧。
2. 清单缺失或无效，但存在 `recording.mp4 + mouse_events.jsonl + session_meta.json`：按 `CLICK_SUMMARY_V1` 补生成。
3. 只有 `recording.mp4`：创建临时派生元数据，并按每10秒一帧生成备用拼图；该模式没有鼠标点击语义。
4. 索引存在但图片缺失：若源视频可用，重新生成；否则阻塞并报告缺失文件。
5. 图片存在但索引缺失：不猜测图片顺序；若源视频可用，重新生成，否则阻塞。
6. 视频不存在、不可读或损坏：阻塞，不创建伪工作空间。

准备成功后工作空间固定写入 `<Session>/analysis_output/journey_workspace/`。生成过程使用同盘临时目录，成功后移动并清理临时文件，失败时保留诊断现场。

## 5. 权限边界

交接清单和自动抽帧只证明资料完整，不代表任何 OCR 或事件结论已确认。自动产物状态仍只能是候选；人工复核规则和 final gate 不变。
