# 人工选帧工作台契约

人工选帧是历程拆解主链路的第3步，正式入口为 `http://127.0.0.1:8767/manual/`。该页面由 `tools/manual_frame_review_web/` 提供，代码迁自已完成真实Session打磨的旧工作台；旧 `D:\journey-agent-pilot` 只保留历史参考，不再继续开发。

## 输入

运行目录必须包含：

```text
review_session.json
recording.mp4
contact_sheets/*.png
frames/*.jpg                 # 可选
```

`review_session.json` 提供 Session ID、视频URL、真实抽帧索引、视频文件名、拼图页、每个小图的时间和行列位置。新链路由 `prepare_journey_workspace.py` 生成runtime，视频与拼图优先使用NTFS硬链接物化，不复制进源码目录，也不猜测文件名。

## 人工交互

- 点击拼图小图后，主视频跳到对应时间。
- 方向键只在拼图获得操作焦点后切换小图。
- 空格将当前拼图帧快速加入待复核。
- 相机按钮把视频当前时间加入待复核。
- 人工填写事件名称/类型并确认或排除。
- 主视频与拼图宽度可拖动调整，时间轴可直接拖动。

## 持久化

正式状态写入 `manual_frame_review.json`，Schema 为 `schemas/manual_frame_review.schema.json`。浏览器 `localStorage` 只用于首次迁移旧数据；服务端成功保存后会删除对应旧缓存，后续事实源只能是JSON文件。

```json
{
  "schema_version": "1.0",
  "session_id": "20260610_163422",
  "updated_at": "2026-07-21T21:00:00+08:00",
  "candidates": []
}
```

人工拼图帧还会自动适配为现有 `selected_ocr_tiles.json`，不改变OCR CLI 1.0契约。视频当前帧保存在 `manual_video_frames` 扩展字段中，待按 `timeMs` 物化后再作为原图证据。

`review_session.json` 只有提供真实 `sourceIndex` 和 `videoFile` 时，适配文件才写入 `source_index` 和 `source_video`。缺失时服务在 `ocrHandoff.blockers` 明确报告，不再猜测一个可能不存在的文件名。人工拼图帧全部删除或排除后，旧 `selected_ocr_tiles.json` 会同步删除，避免下游继续读取过期选择。

## 与区域校准连接

区域工作台通过 `--manual-review manual_frame_review.json` 读取未排除的人工帧，不 import `journey_analysis`。每个OCR区域可保存最多3个 `manual_sample_ids`：

1. 在人工选帧页建立高置信候选。
2. 在区域页“人工帧库”选择正确代表帧。
3. 调整同一归一化区域框。
4. 点击“自动判断”，对1至3张选区做RapidOCR。
5. 软件建议指标类型和数值格式，人工确认区域。

自动判断只产候选，不得修改区域 `status`；只有人工点击确认才能让区域进入正式扫描。

## 启动

前端修改后先构建：

```powershell
cd tools/manual_frame_review_web
pnpm install --frozen-lockfile
pnpm run build
```

新链路统一启动：

```powershell
python tools/serve_journey_workspace.py <workspace目录>
```

统一服务只占用一个Python进程和一个端口，页面路径固定为 `/manual/`、`/regions/`、`/events/`、`/metrics/`。下游数据尚未生成或指纹过期时，对应路径显示阻塞原因，但不会挂载可写复核API。

只调试人工选帧服务时：

```powershell
python tools/serve_manual_frame_review.py <runtime目录> `
  --state-json <分析目录>/manual_frame_review.json `
  --port 5173
```

服务只监听 `127.0.0.1`，支持MP4 Range请求。稳定错误码为 `MANUAL-REVIEW-001`（读取/资源错误）和 `MANUAL-REVIEW-002`（保存请求错误）。
