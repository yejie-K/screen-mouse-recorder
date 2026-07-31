# 游戏历程拆解主链路 v2

本文档定义 Screen Mouse Recorder 从录屏到 XLSX / 图表的唯一主链路。v2 将 OCR 明确拆成**功能事件线**和**指标跟踪线**，两条线共享区域校准和全抽帧扫描能力，但分别复核、分别输出。

各阶段精确文件版本、生产者和消费者以 [journey_contract_matrix.md](journey_contract_matrix.md) 为准。新运行以 `journey_workspace.json` 为唯一顶层入口，不再手工给四个页面配置不同输出目录。

## 1. 主流程

```text
1. 游玩录屏
2. 自动生成全部抽帧原图、索引和合成大图
3. 人工从前30分钟选择代表帧并标注
4. 对人工帧和自动候选帧做粗OCR，发现稳定区域
5. 人工复核OCR结果并校准关键区域
6. 对全部抽帧原图逐张裁剪确认区域，只对裁剪区域OCR
7. 功能事件结果和指标变化结果分别复核
8. 分别回填XLSX，再汇总生成图表和Agent报告
```

人工选帧用于提供高置信样本和校准区域，不决定后续扫描范围。人工确认帧先按用途分流：功能/技能样本以 `manual_frame_review.json` 的人工确认状态直接进入统一事件结果，不在功能事件页重复复核；功能事件页只复核OCR自动候选。等级、转生、战力等成长样本保留在指标线的人工样本层，不得转成“功能开放”事件。第6步的扫描范围固定为 `all_extracted_frames`：抽帧索引中的每一张原始帧都参与，但不再做整张图片OCR。

## 2. 两条OCR线

### 2.1 功能事件线

识别新玩法、新副本、新养成系统、新技能、新任务、新社交和新商业功能。一个事件检测器可以由多个区域组成：

- `trigger`：固定提示文字，如“新功能开启”；
- `name`：具体功能或玩法名称；
- `auxiliary`：开放条件、按钮或页面标题。

连续多帧命中同一内容时聚合为一次事件，并选取清晰帧作为证据。

功能事件只维护两组单选标签：

```json
{
  "event_name": "伙伴副本",
  "mode_tag": "PVE",
  "event_tag": "新副本"
}
```

`mode_tag`：`PVE / PVP / GVG / 系统 / 待判断`。

`event_tag`：`新玩法 / 新副本 / 新养成系统 / 新技能 / 新任务系统 / 新社交功能 / 新商业功能 / 其他开放`。

伙伴、坐骑、具体技能名等游戏内名称保存在 `event_name` 和 OCR 原文中，不再扩张标签集合。

### 2.2 指标跟踪线

识别战力、等级、转生、VIP等级和货币等固定位置数值。每个指标区域独立扫描、独立形成时间序列，不要求战力和等级出现在同一帧。

指标观察不使用事件标签。相同值连续出现时可在结果层合并，只保留变化节点；异常跳变、低置信结果和解析失败项进入指标复核。

## 3. 各阶段输入输出

| 阶段 | 输入 | 输出 |
|---|---|---|
| 录屏 | 游戏画面、鼠标操作 | MP4、鼠标日志、session元数据 |
| 抽帧 | MP4、鼠标日志 | 全部抽帧原图、索引、合成大图 |
| 人工样本 | 合成大图、视频预览 | `manual_frame_review.json`、`selected_ocr_tiles.json`、代表帧与事件名称候选 |
| 粗OCR | 人工帧、自动候选帧 | 全图文字框候选，仅用于发现区域 |
| 区域校准 | 1至3张样本、文字框 | `ocr_region_profile.json` |
| 定向全量OCR | 全部抽帧原图、区域profile | 事件候选、指标观察候选 |
| 分线复核 | OCR功能事件候选、指标候选 | 人工事件直通后的统一确认事件、确认指标变化 |
| 产物生成 | 两类确认结果 | XLSX、三张图、Agent报告 |

## 4. 区域契约

新录屏推荐使用一次性入口，先输出工作量预检，再生成点击拼图并初始化工作空间：

```powershell
python tools/prepare_journey_run.py `
  <session目录> <本次运行目录> `
  --game-id <game_id> --game-name <game_name> `
  --region-profile <ocr_region_profile.json> --serve
```

正式抽帧只使用 `CLICK_SUMMARY_V1`，默认不限制总帧数；不再为分析端维护第二套阈值。`preflight.json`记录画面差异帧数、缓存复用数、预计实际取帧数和拼图数。

先初始化新工作空间：

```powershell
python tools/prepare_journey_workspace.py `
  <session目录> <点击抽帧索引.json> <workspace目录> `
  --game-id <game_id> --game-name <game_name> `
  --region-profile <ocr_region_profile.json>
```

初始化器验证Session、视频、索引中的每一张拼图，并用硬链接优先物化到工作空间。`review_session.json` 一定包含真实 `sourceIndex/videoFile`。

统一工作台顶栏提供共享 Session 选择器、“浏览”和“退出”入口。用户可以选择任意可访问磁盘上的工作空间、包含 `workspace/` 的运行目录，或包含多个 Session 的资料目录；服务端校验目录后将其加入本机最近记录，并使用不透明 ID 切换整套工作空间，前端不提交或保存绝对路径。“退出”调用仅允许回环地址访问的关闭接口，保存当前人工选帧后停止本地HTTP服务；只关闭浏览器标签不会停止后台。最近目录仅写入当前 Windows 用户的 `%LOCALAPPDATA%\ScreenMouseRecorder\journey_sessions.json`，不进入源码、发布包或工作空间契约；换设备后重新选择资料目录即可。工作空间内的 artifact 路径仍必须为相对路径，不依赖原设备盘符。

Windows日常入口为仓库根目录 `start_journey_analyzer.cmd`。不传参数时自动选择最近修改的可用 `journey_workspace.json` 并打开浏览器；也可把工作空间目录作为第一个参数显式指定。

外部 Session 只要包含 `recording.mp4` 就可以选择。存在合法录屏交接清单时直接复用 `auto_report/` 的索引和拼图；清单无效或缺失但鼠标日志和元数据齐全时，按同一 `CLICK_SUMMARY_V1` 补生成；只有视频时进入每10秒一帧的普通视频备用模式。用户填写游戏名称后服务在后台准备，进度显示在共享顶栏；成功产物固定写入 `<Session>/analysis_output/journey_workspace/` 并自动切换，原始录屏和日志不修改。临时目录位于同一 `analysis_output/`，成功后清理，失败时保留用于诊断。完整检测顺序和目录所有权见 [recorder_analysis_handoff_contract.md](recorder_analysis_handoff_contract.md)。游戏ID由本机根据人工填写的游戏名称稳定生成；不得从OCR或视频内容自动确认游戏身份。

后台准备完成时只创建人工选帧工作空间；没有经过人工校准的OCR区域不会被自动确认或从其他游戏静默继承。切换成功后四个页面共同读取新工作空间，视频、拼图、OCR profile、扫描结果和人工复核数据不得跨 Session 混用。稳定错误码：`JOURNEY-WORKSPACE-008` 表示用户取消选择，`JOURNEY-WORKSPACE-009` 表示所选目录不含可识别的 Session/工作空间，`JOURNEY-WORKSPACE-010` 表示目录不可访问，`JOURNEY-WORKSPACE-011` 表示后台准备失败。

新工作空间同时创建 `needs_review` 的空白区域草稿，因此人工选帧完成后“区域校准”入口始终可用。空白草稿允许暂时没有区域；用户点击区域队列“+”后，首个待校准区域默认绑定第一张未排除的人工选帧，再选择“数值指标”或“功能事件”并拖动框选。只有完成校准或开始扫描时才要求至少一个有效区域。区域可以只使用 `manual_sample_ids` 作为证据，`sample_evidence` 允许为空；这不降低人工确认要求。

区域使用 `schemas/ocr_region_profile.schema.json`，顶层 `scan_scope` 必须为 `all_extracted_frames`。

- 指标区域：`region_kind=metric`，必须声明 `metric_key` 和解析器。
- 功能区域：`region_kind=event`，必须声明 `region_group_id`、`region_role` 和固定关键词。
- 坐标使用 `rect_normalized`，并保留1至3张人工确认样本。
- 分辨率或页面布局明显变化时创建新区域，不静默复用旧坐标。

旧布局候选先转换成待复核草稿：

```powershell
python tools/convert_legacy_layout_profile.py `
  layout_profile.json `
  ocr_region_profile_draft.json `
  --game-id <game_id> `
  --game-name <game_name>
```

通过本地工作台确认、排除或调整区域：

```powershell
python tools/serve_ocr_region_profile_review.py `
  ocr_region_profile_draft.json `
  <包含scan_frames和region_previews的目录> `
  --index-json keyframes_index.json `
  --video recording.mp4 `
  --scan-output region_scan_output `
  --save-crops `
  --port 8767
```

工作台按“左侧区域队列 -> 中间画面校准 -> 右侧识别确认”组织。当前框支持整体拖动以及四边、四角八向缩放，坐标输入和画面实时双向同步；框不会越过画面边界，也不能缩小到不可操作。每个区域可切换最多3张代表帧，并显示裁剪预览和逐样本识别结果。普通校准只暴露识别内容、区域名称、指标类型或事件关键词；归一化坐标、解析器、事件组和玩法标签收进高级设置。人工选帧工作台是正式第1入口，其服务端JSON可通过 `--manual-review` 接入区域页“人工帧库”；每个区域把最多3个选择保存为 `manual_sample_ids`。左栏“+”会创建一个 `needs_review` 指标区域，人工选择正确帧并框定位置后点击“测试识别”，软件对选区运行RapidOCR并建议指标类型/数值格式；自动建议不能确认区域。确认后页面自动进入下一条待处理区域。只有所有候选都处理完成，且启用的事件组包含 `trigger` 区域时，profile 才会变成 `complete`。配置 `--index-json / --video / --scan-output` 后，区域全部就绪才显示可用的全量扫描操作；区域发生变更时历史扫描明确标记为“待更新”，不能进入旧指标结果。扫描在后台线程执行，不阻塞区域页面。`--save-crops` 用于保留后续指标复核所需的局部证据图。

本地开发若OCR依赖位于独立虚拟环境，可额外传入 `--ocr-runtime <venv目录>`。正式安装或打包环境应直接安装 `.[ocr]`，不依赖该开发参数。

正式局部OCR：

```powershell
python tools/scan_ocr_regions.py `
  keyframes_index.json `
  ocr_region_profile.json `
  output_directory `
  --video recording.mp4 `
  --session-id <session_id> `
  --json-progress
```

正式扫描默认保存 `region_crops/` 局部证据图，指标复核页直接读取这些图片。只有调试性能时才能显式使用 `--no-save-crops`。扫描器拒绝 `needs_review` profile。`--limit` 只用于调试；设置后输出的 `scan_scope` 是 `debug_subset`，不能冒充全量结果。

## 5. 结果契约

- 功能事件：`schemas/journey_event_observations.schema.json`
- 指标观察：`schemas/journey_metric_observations.schema.json`
- 指标人工决定：`schemas/journey_metric_review.schema.json`

全抽帧局部OCR还会输出 `region_scan_manifest.json`，记录总帧数、实际扫描帧数、每帧区域数、`ocr_calls`、空结果数、聚合前后命中数和耗时。多区域会合并为单张批次图做一次RapidOCR，再按文字框位置拆回各区域；该优化不改变区域、时间和证据契约。

指标输出表达“值发生变化”，不是周期快照。只要同一区域连续识别到相同解析值，无论两次观察间隔多久都折叠为一条，并累计`occurrence_frame_count`、更新`last_time_ms`、保留最高置信证据；中间出现其他值后再次回到旧值时仍生成新候选。战力数值还必须包含“战力”或受控OCR近似词，带`/`的生命值格式不进入候选。

事件和指标复核是并行阶段。若一次扫描没有功能事件候选，同步器不会伪造事件或创建空语义包，也不会阻断指标复核包生成；事件阶段保持`blocked`，直到人工选帧或自动检测产生至少一个待复核事件。正式XLSX/三图仍要求事件与指标两路都完成人工复核。

### 5.1 工作空间同步与功能事件复核

扫描完成后使用工作空间同步器。它先校验事件/指标来自同一Session和同一 `index + profile` 指纹，再把人工高置信事件与自动事件合并，最后生成事件和指标复核包：

```powershell
python tools/sync_journey_workspace.py <workspace目录>
```

输出包含合并后的 `event_observations_v2.json`、事件复核四件套、`journey_metric_review.json` 和确认指标文件。上游变化时同步器拒绝覆盖已有人工决定，只有显式 `--reset-review` 才能重建。

正常使用 `serve_journey_workspace.py` 时不需要手工执行该命令：统一服务在一个Python进程和一个端口内提供 `/manual/`、`/regions/`、`/events/`、`/metrics/`。扫描完成后，首次进入下游页面时自动同步并挂载对应复核工作区，不需要重启；扫描过期时只显示阻塞页，不开放旧结果写入。独立页面命令保留用于恢复和诊断。

旧语义迁移工具保留作历史审计，不属于新链路，也不会被工作空间服务自动调用。

### 5.2 指标结果复核

指标候选文件保持只读。工作台把人工决定写入独立文件，再生成复核后的指标结果：

```powershell
python tools/serve_metric_review.py `
  metric_observations_v2.json `
  --review journey_metric_review.json `
  --confirmed-output confirmed_metric_observations_v2.json `
  --evidence-root <来源帧或region_crops目录> `
  --port 8769
```

工作台支持证据图、时间、OCR原文、指标类型、解析值修正、确认、排除和已解析项批量确认。批量确认只接受没有重点警告的候选；缺少固定文字、疑似生命值、数值回退/突变和低置信结果必须逐条处理。人工可修正 `metric_key / parsed_value / parsed_fields / unit`，但不能修改时间、帧号、区域和证据引用。

- `metric_observations_v2.json`：OCR候选，只读，不会被工作台覆盖。
- `journey_metric_review.json`：人工决定和受限修正，是产生 `confirmed` 的唯一来源。
- `confirmed_metric_observations_v2.json`：复核结果；保留确认、排除和待复核项以便审计。
- 顶层 `status=complete` 只表示所有候选都已处理。下游仍必须只读取 `metrics[].review.status == confirmed`。

## 6. XLSX与图表

- 功能事件确认结果进入事件单和玩法/系统开放节奏图。
- 指标确认结果进入战力变化表、等级/转生变化表和成长反馈图。
- 两条线只在最终报告中按视频时间对齐，不要求同一帧同时识别全部信息。
- 情绪图和循环总结只能读取人工确认结果。
- `python tools/check_journey_workspace.py <workspace目录> --final-gate` 要求事件和指标均无待复核项。
- `python tools/generate_journey_final.py <workspace目录>` 输出带事件截图的XLSX、玩法系统开放节奏图、最终情绪图、成长反馈图、各图报告和Agent说明。
- 暂不处理大批量复核时，可运行 `python tools/generate_journey_preview.py <workspace目录>`；它读取pending候选生成独立 `preview/`，所有文件均标记为草稿，正式门禁和 `final/` 不受影响。
- `prepare_journey_analysis_v1.py` 只保留为早期草稿工具，不属于新链路。

## 7. AI权限

- OCR、规则和大模型只能产 `pending / needs_review / excluded` 候选。
- 只有人工复核文件能产生 `confirmed`。
- 时间、证据、指标数值和人工标签不能由大模型覆盖。
- 正式XLSX和图表只读取已确认数据。
