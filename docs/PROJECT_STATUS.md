# 项目封版状态

版本快照：`v2.2.0`（封版核验日期：2026-07-31）

本仓库包含两个独立入口，仍保持一个 Git 仓库：

| 入口 | 状态 | 说明 |
|---|---|---|
| ScreenRecorder | Stable | 录屏、鼠标日志、自动抽帧、拼图、行为报告和 Session 交接 |
| JourneyAnalyzer | Beta | 人工选帧、OCR区域校准、全量局部OCR、事件/指标复核、XLSX与图表 |

## 当前完成内容

- 录屏端使用唯一 `CLICK_SUMMARY_V1` 抽帧契约。
- 录屏停止后可生成 `auto_report/analysis_handoff.json`。
- 分析端可从任意可访问磁盘选择 Session，并复用或补生成抽帧资料。
- 人工选帧、OCR区域校准、全量局部OCR和两条复核线已经接通。
- 图表由确定性 Pillow 脚本生成；大模型只产结构化候选，不直接写确认结果。
- XLSX和正式图表受到人工复核 final gate 保护。

## 当前限制

- JourneyAnalyzer 的真实长链路样本仍有待复核候选，不应宣称为生产级自动分析器。
- 当前发布快照不包含 Windows EXE；源码运行需要 Python、FFmpeg和按需安装 OCR 依赖。
- Session、录屏、OCR结果和生成图片不进入 GitHub，保存在本地归档。

## 验证基线

封版前全套单元测试：`111/111` 通过。

人工选帧网页的源码、锁文件和生产 `dist/` 会进入源码快照；依赖目录
`node_modules/`、OCR模型、真实Session和运行产物均不进入Git。

## 入口

- 录屏：`start_recorder.cmd`
- 历程分析：`start_journey_analyzer.cmd`
- 主链路：`docs/journey_pipeline_v2.md`
- 两端交接：`docs/recorder_analysis_handoff_contract.md`
