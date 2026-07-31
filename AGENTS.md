# AGENTS.md — Screen Mouse Recorder 开发规则

本文件是任何 Agent 或开发者进入 `D:\screen_capture` 后的强制入口。开始改动前必读，改完必须按第 1 节回写日志。

## 0. 项目定位（一句话）

Screen Mouse Recorder 是本项目的**唯一主体实现**：区域录屏 + 鼠标行为分析 + 抽帧拼图 + OCR 事件识别 + 游戏历程拆解出图。

`D:\历程拆解工具` 只是早期蓝图/规范/控制台原型，**不是第二个主体**，只作设计参考，不在此仓库内实现。

## 1. 强制约定：每次改动必须回写日志

这是不可跳过的收尾步骤。任何代码或结构改动完成后：

1. 在 `docs/DEV_LOG.md` **顶部**（时间倒序）追加一条，用文件里已定义的模板：日期、动机、改了什么、影响面、验证结果、是否已提交。
2. 若改动影响了模块依赖关系，同步更新 `MODULE_BOUNDARIES.md`。
3. 若改动了输入/输出结构或对外契约，检查并同步相关 `docs/*.md` 契约文件。

未回写 DEV_LOG 的改动视为未完成。其他 Agent 依赖这份日志判断“我们干到哪了”，不能靠对话记忆。

## 2. 必读顺序

1. 本文件 `AGENTS.md`
2. `docs/DEV_LOG.md`（当前进度与最近改动）
3. `MODULE_BOUNDARIES.md`（模块边界与依赖规则）
4. `README.md`、`PROJECT_DESIGN.md`（产品与 UI 基调）
5. 当前任务涉及的 `docs/*.md` 契约

## 3. 架构边界（不可违背）

1. 依赖方向：`media_utils`（底层，仅 stdlib + PIL）← `recorder/frame_export`、`ocr(event_extraction)`、`journey_analysis` 三个可独立发布模块。
2. `ocr` 不得再 import `frame_export`；需要的视频/时间码能力一律走 `media_utils`。
3. `journey_analysis` 保持自足：不依赖录屏侧（config/app/mouse/video/storage）。
4. GUI 主体 `app.py` 不得依赖 `ocr` 或 `journey_analysis`（它们通过 `cli.py` / `tools/` 挂载）。
5. 往 `media_utils` 添加内容时，不得引入业务模型（如 `VideoInfo`）；需要业务模型的函数留在拥有该模型的模块。
6. 公共 API 变更要保持向后兼容或在 DEV_LOG 中明确记录破坏性变更。

## 4. 数据与 AI 边界

1. AI / 外部工具只产候选，状态只能是 `needs_review` / `excluded`，不得自我写入 `confirmed`。
2. 只有人工复核文件能把候选变成确认数据（见 `docs/journey_semantic_review_workflow.md`）。
3. 图表只读取人工确认后的统一数据源。
4. 每个结论必须可追溯到截图 / 帧 / 视频时间 / session。

## 5. 验证要求

- 改完跑全套测试：`python -m unittest discover -s tests`（封版基线 111/111）。
- 涉及模块解耦时，用全新进程验证依赖未回流（命令见 `MODULE_BOUNDARIES.md`）。
- 测试或验证失败时，DEV_LOG 如实记录，不得标记为完成。
