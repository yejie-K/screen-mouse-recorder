# tools目录状态

本目录包含当前主链路入口、独立维护命令和历史迁移工具。新增功能前先确认工具状态，不要继续扩展已被替代的入口。

## 当前主链路

| 工具 | 状态 | 用途 |
|---|---|---|
| `prepare_journey_run.py` | 当前 | 一次性预检、点击抽帧、初始化工作空间，可选直接启动页面 |
| `prepare_journey_workspace.py` | 当前 | 已有点击抽帧索引时单独初始化工作空间 |
| `serve_journey_workspace.py` | 当前 | 单进程、单端口启动全部页面；扫描完成后按需同步并挂载下游复核 |
| `sync_journey_workspace.py` | 当前维护 | 手工恢复/诊断同步，通常由统一启动器自动调用 |
| `check_journey_workspace.py` | 当前 | 检查阶段状态和final gate |
| `scan_ocr_regions.py` | 当前维护 | 独立执行区域扫描，页面内也可发起 |
| `generate_journey_preview.py` | 当前 | 生成明确标记为候选的XLSX和三图 |
| `generate_journey_final.py` | 当前 | final gate通过后生成正式产物 |
| `serve_manual_frame_review.py` | 诊断页面 | 单独调试人工选帧；正式入口为统一工作台 `/manual/` |
| `serve_ocr_region_profile_review.py` | 诊断页面 | 单独调试OCR区域校准；正式入口为统一工作台 `/regions/` |
| `serve_journey_semantic_review.py` | 诊断页面 | 单独调试功能事件；正式入口为统一工作台 `/events/` |
| `serve_metric_review.py` | 诊断页面 | 单独调试指标结果；正式入口为统一工作台 `/metrics/` |

## 维护与诊断

| 工具 | 用途 |
|---|---|
| `gen_semantic_output_from_rules.py` | 用规则草稿替代AI输出，诊断语义闭环 |
| `validate_journey_semantic_output.py` | 独立校验语义输出 |
| `finalize_journey_semantic_review.py` | 独立重建确认事件文件 |
| `convert_legacy_layout_profile.py` | 将旧布局候选转换为待复核区域profile |

这些命令不是普通用户每次都要执行的步骤，但仍是有效恢复工具。

## 历史迁移

| 工具 | 状态 |
|---|---|
| `prepare_event_review_v2.py` | legacy，仅显式桥接历史v2事件文件 |
| `migrate_semantic_input_v1.py` | legacy，仅显式迁移语义输入1.0到1.1 |
| `split_journey_v1_to_parallel_v2.py` | legacy，仅拆分历史v1混合结果 |
| `prepare_journey_analysis_v1.py` | legacy，早期草稿产物入口 |

历史迁移工具暂不删除，但不得成为新工作空间的默认调用路径。

## 停止扩展

`build_journey_decomposition_v0.mjs` 是早期一次性产物脚本，硬编码旧分类/情绪规则并依赖独立artifact工具。当前Python正式生成器已替代它；仅保留审计，不再增加功能。
