# 归档与恢复开发指南

## GitHub源码快照

GitHub只保存源码、测试、规则、Schema、契约、提示词和说明。不要提交 `sessions/`、`outputs/`、`experiments/`、`release_packages/`、配置、日志和本机运行时。

## 本地资料归档

本次封版不移动或复制约7.5GB的原始资料，避免破坏现有Session相对路径。
资料继续原位保存在下列Git忽略目录：

```text
sessions/          原始录屏和鼠标日志
outputs/           分析工作空间、XLSX和图片
experiments/       历史OCR与阈值实验
release_packages/  历史源码分发包
```

运行 `python scripts/create_local_archive_manifest.py`，会在被忽略的
`local_archive/` 下生成目录统计和 `FILE_HASHES.sha256`。不要把录屏、
截图、哈希清单或本机路径推送到公开仓库。

## 恢复开发

1. 克隆仓库并安装 Python 依赖。
2. 先阅读 `AGENTS.md`、`docs/DEV_LOG.md`、`MODULE_BOUNDARIES.md` 和本文件。
3. 将本地归档中的 Session 或工作空间放到任意磁盘位置，不要求恢复原盘符。
4. 用 `start_recorder.cmd` 或 `start_journey_analyzer.cmd` 启动对应入口。
5. 先运行全套测试，再修改契约或模块边界。
6. 分析端只通过 Session 文件契约读取录屏端产物，不直接 import 录屏业务模块。

## 发布快照

当前快照建议使用 Git tag `v2.2.0`。录屏端标记为 Stable，历程分析端标记为 Beta；不要把候选 XLSX或候选图表描述成正式结论。
