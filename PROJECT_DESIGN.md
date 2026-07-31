# PROJECT_DESIGN

## 1. Product Context

- Product: Screen Mouse Recorder.
- Target user: 需要长时间录制屏幕区域、采集鼠标行为，并把数据导出为 xlsx / 图表进行人工分析的人。
- Target surface: Windows Tkinter 桌面应用，当前包含“录制”和“分析处理”两个主页面。
- Secondary review surface: 历程语义确认使用 `tools/` 启动的 localhost 浏览器工作台，不嵌入 `app.py`，也不改变录屏主流程。
- Primary job-to-be-done: 快速可靠地完成一次录制；录制结束后自动生成可读的行为分析输出。分析页只作为已有 xlsx/session 的补处理工具。
- Success criteria: 用户 1 分钟内能开始录制；用户能明确知道当前状态、输出位置、自动分析是否完成、生成了哪些关键文件；分析页能让旧数据或未自动出图的数据快速补生成报告和图片。
- Content/data that must appear: 录制时长、区域状态、FFmpeg 状态、输出目录、记录选项、session 摘要、导入源、事件数、采样数、点击数、分析输出文件。
- Interaction requirements: 主操作始终可见；状态变化立即反馈；危险/不可逆动作有确认；长任务不能卡死主窗口；输入/输出路径应可复制或打开。
- Technical constraints: Tkinter/ttk；Windows 优先；使用 Segoe UI / Consolas；不引入重型 GUI 框架；图表由 Pillow/openpyxl 输出。

## 2. Existing UI Read

- Current visual vocabulary: 浅灰工作台背景、浅色面板、状态 badge、红/绿/黄录制控制、紧凑三栏布局。
- Strongest existing cue to preserve: “录制控制台”感，计时器和播放/暂停/结束按钮是录制页视觉中心。
- Components/tokens to reuse: `Panel.TFrame`、`Panel.TLabelframe`、`Muted.TLabel`、状态 badge、固定尺寸页签、复选项和数值 spinbox。
- Patterns to preserve: 两个主页面；录制页三栏；分析页导入 -> 检查 -> 生成 -> 输出；生成结果输出到导入目录下。
- Patterns to evolve: 减少面板内文本拥挤；统一按钮高度和色彩语义；让分析输出更像结果清单而不是说明文字。
- Patterns to remove or avoid: 欢迎页、营销 hero、装饰图形、过度卡片化、嵌套卡片、暗黑仪表盘默认风格、炫酷但不利于扫描的色彩。
- Accessibility/state conventions already present: 禁用态、录制锁定设置项、状态提示、错误弹窗、焦点虚线已在关键选项上避免。

## 3. Taste Direction

- Product identity sentence: 一个安静、可靠、可扫描的桌面行为采集与分析工作台。
- Recommended taste direction: Refined light workspace. 以 A 方案为主：浅色、清晰、精致但不酷炫；录制页是主工作台，分析页是轻量补处理工具。参考 Airtable 的结构化清晰和 Mintlify 的可读性，少量吸收 Linear 式精密感，但全部弱化为 Tkinter 桌面工具语言。
- Direction to avoid: Awwwards/landing-page style, dark precision cockpit, decorative gradient interface, oversized typography, portfolio-like polish.
- Why this makes the UI more useful: 该工具核心不是吸引用户，而是降低录制和分析时的认知负担；信息密度要高，但分组和状态必须清楚。
- What should feel distinctive: 录制页像可靠的长时间测试控制台；分析页像导入后补生成报告的小工具，而不是日常数据仪表盘。
- What should stay quiet: 背景、边框、说明文字、辅助按钮、输出文件列表。

## 4. Selected References

### Airtable-Like Structured Clarity

- Why it fits: 适合结构化数据、导入输出、表格/报告类工作流。
- Transferable traits: 白/浅灰画布、清晰分组、蓝色作为导入/分析辅助动作、边框分隔多于阴影。
- Non-transferable brand details: 大圆角、品牌蓝、营销式宽松排版、过多彩色块。
- Implementation substitutions: Tkinter 面板使用 1px 边框、8px 内间距倍数；蓝色只用于分析/导入，不抢录制主操作。
- Risk: 过度 Airtable 化会显得像 Web SaaS，不像本地工具。
- Weaken if needed: 保留浅色与分组，减少圆角和阴影。

### Mintlify-Like Readability

- Why it fits: 分析页需要把输出和解释写清楚，不能让用户猜文件含义。
- Transferable traits: 高可读正文、轻量边框、少量绿色成功态、清楚的说明层级。
- Non-transferable brand details: 大面积白色、胶囊按钮、绿色品牌氛围、文档站式 hero。
- Implementation substitutions: 使用 Segoe UI 10-11px 正文、9px 辅助说明；生成成功使用低饱和绿色 badge。
- Risk: 过于文档化会让录制页变慢。
- Weaken if needed: 只把该参考用于分析页和输出说明，不影响录制控制区。

### Sentry-Like Monitoring Density

- Why it fits: 数据采集、事件计数、图表生成和状态检查需要监控工具的“可扫读密度”。
- Transferable traits: 状态语义强、错误/警告突出、技术指标可见、输出健康检查一眼看清。
- Non-transferable brand details: 暗紫背景、霓虹色、品牌插画、强烈开发者个性。
- Implementation substitutions: 保留浅色主题，用红/黄/绿/蓝 badge 表达状态；不用暗色主背景。
- Risk: 过度监控化会让界面紧张。
- Weaken if needed: 只在状态、摘要、文件健康检查上使用该参考。

## 5. Visual Theme & Atmosphere

- Design thesis: The UI should feel like a reliable field instrument: compact, readable, calm under long tests.
- Emotional tone: 稳、清楚、低噪音。
- Product personality: 实用、专业、不会戏剧化、不假装是网站。
- First viewport message: “这里可以开始录制，也可以导入数据生成分析。”
- Visual weight priorities: 主操作按钮 > 计时器/状态 > 自动分析输出状态 > 输入输出路径 > 选项 > 辅助说明。

## 6. Color Palette & Roles

- Page/background: `#edf1f4`，保持浅灰工作台底色。
- Primary surface: `#f8fafb`，面板背景。
- Secondary/elevated surface: `#eef3f6`，指标块、轻量输出行。
- Primary text: `#17212b`。
- Secondary text: `#263238`。
- Muted text: `#60717d`。
- Accent/CTA:
  - 录制开始/继续：`#1f9d55`。
  - 录制中/停止风险：`#d83b3b`。
  - 暂停/处理中：`#ffd166` / `#f0b429`。
  - 分析/导入辅助动作：`#1f6fb2`。
- Border/divider: `#c7d0d8` for panels, `#dfe7ec` for subtle fills.
- Focus ring: `#1f6fb2` when explicit keyboard focus is useful; avoid persistent mouse-click focus frames on options.
- Success/warning/error: success `#1f9d55`, warning `#f0b429`, error `#d83b3b`.
- Color constraints: 每个页面最多一个主强调色；不要使用紫色主调、渐变背景、发光边缘或一页全蓝/全绿。

## 7. Typography Rules

- Font families and fallbacks: UI text uses `Segoe UI`; timer and numeric dense metrics may use `Consolas`.
- Display/hero: 不使用 hero-scale typography。
- Section headings: `Segoe UI` 10-11px bold for labelframe titles and local headings.
- Subheadings: 10px medium.
- Body: 10px regular.
- Labels/captions: 9px regular, muted color.
- Code/mono: `Consolas` for timer and timecodes only.
- Weight rules: Bold reserved for page title, timer, status badge, metric value, primary panel title.
- Line-height rules: Tkinter labels use fixed heights only when preventing layout shift; wrap long explanatory text.
- Letter-spacing rules: Tkinter 不调整字距。

## 8. Component Styling

- Main navigation tabs:
  - Equal width and height.
  - Selected state uses color, not size.
  - No mouse-click focus dashed frame.
- Panels:
  - Background `#f8fafb`.
  - 1px border `#c7d0d8`.
  - Padding 12-14px.
  - Avoid panel inside panel unless it is a repeated item or result list row.
- Buttons:
  - Primary recording controls are large and icon-like.
  - Standard command buttons use consistent height and concise text.
  - Use color by semantic action, not decoration.
  - Disabled state must visibly reduce contrast.
- Forms:
  - Readonly path inputs should align with their action buttons.
  - Numeric fields stay two-column and compact.
  - Long Chinese labels should wrap before overflowing.
- Check options:
  - Same size for checked/unchecked; state changes by color/check mark only.
  - Remove persistent focus frame after mouse click.
- Status badges:
  - Short text only: 就绪、录制中、保存中、已完成、生成中、失败。
  - Use color as status, not as branding.
- Result/output lists:
  - Prefer rows with file label, status, and open action.
  - Avoid long explanatory paragraphs after generation.
- Analysis page:
  - Keep it lightweight: input source, data sanity metrics, generate action, output status.
  - Do not turn it into a persistent dashboard; charts may be generated to files, not permanently showcased as the page's main purpose.
- Empty/loading/error:
  - Empty: one clear next action.
  - Loading: show status near action button.
  - Error: show message near the failed operation and optionally a modal.

## 9. Layout Principles

- Spacing scale: 4, 6, 8, 12, 14, 16, 18, 24px.
- Container width: Default window stays near `1120x760`; minimum no lower than current `1080x720` unless layout is reworked.
- Localhost review workbenches share one fixed shell contract from `tools/workspace_shell.css`: `1100px` minimum canvas, `64px` header, `54px` toolbar, `220px` brand area, `390px` navigation area, `15px/1.5` base type, and `36px` navigation/action controls.
- Review workbench columns never reflow between pages: every page uses `280px / minmax(420px, 1fr) / 380px`. Narrow windows keep this skeleton and use page scrolling; they do not hide controls, change column widths, or collapse into one column.
- Cross-page navigation must begin at the same x-coordinate for a given viewport. Page titles may truncate with ellipsis, but controls and labels must never overflow their boxes.
- The fixed header exposes one shared Session selector on every localhost review page. It switches a validated complete workspace, never an isolated MP4 or arbitrary filesystem path; unprepared raw sessions remain visible but disabled.
- Grid:
  - 录制页：流程 / 控制 / 设置 三栏。
- 分析页：导入 / 数据检查 / 生成输出 自上而下；不铺大面积图表预览，除非用于确认刚生成的关键图。
- Section rhythm: 每个主要区域之间 12-14px；面板内控件 6-8px。
- Density model: 信息密度中高，但每个页面只有一个主任务。
- Whitespace philosophy: Whitespace is for grouping and scan speed, not decorative spaciousness.
- Breakpoints: Tkinter 当前不做复杂响应式；若窗口变窄，优先保持可读，不压缩按钮文字。
- Mobile collapse strategy: Not applicable for MVP desktop.

## 10. Depth, Motion, And Interaction

- Elevation levels: Prefer borders and surface color; avoid heavy shadow.
- Border/ring/shadow rules: 面板用边框，按钮用实色，状态用 badge；阴影默认不用。
- Motion personality: Tkinter 中不加装饰动画。
- Transition rules: 状态变化通过文案、颜色、禁用态即时体现。
- Touch target rules: 桌面点击目标不低于 32px 高；主录制按钮更大。

## 11. Do's And Don'ts

### Do

- Preserve the software's operational clarity.
- Keep recording as the primary workbench and analysis as a fallback processing workbench.
- Use real metrics and real output filenames.
- Make the next action obvious.
- Keep analysis outputs understandable for non-engineering review.
- Use Chinese labels consistently in user-facing UI and generated reports.

### Don't

- Do not add a landing page.
- Do not use large hero copy, decorative gradients, bokeh, glows, or brand-like illustrations.
- Do not invent fake metrics or sample output.
- Do not bury Start/Stop/Generate behind secondary controls.
- Do not make the analysis page look like a website dashboard if it reduces task speed.
- Do not add new UI frameworks unless the user explicitly approves a migration.

## 12. Implementation Mapping

- Files likely to change:
  - `src/screen_mouse_recorder/app.py` for Tkinter layout and style.
  - `src/screen_mouse_recorder/analysis.py` for report output naming and generated visuals.
  - `README.md` / `FRONTEND_PRD.md` if workflow docs need updating.
- Existing components to reuse:
  - `_metric`, `_option`, `_number_field`, `_transport_button`.
  - `Settings.TNotebook` equal-size tab style.
  - Analysis output generation module.
- Tokens/classes/variables to extend:
  - Add semantic color constants in `app.py` before further visual refactors.
  - Keep style names descriptive: `Panel`, `Muted`, `Title`, `Settings`.
- New components needed:
  - Result file row component for analysis outputs.
  - Compact auto-analysis status row for the latest recording.
  - Optional small preview entry for latest generated heatmap on the recording page, not a required analysis dashboard.
  - Optional compact status strip for data quality.
- Assets needed:
  - None for core UI.
  - Generated PNG charts remain analysis outputs, not decorative UI assets.
- Data/copy assumptions:
  - User-facing UI copy should remain Chinese where workflows are Chinese.
  - Technical filenames stay English for interoperability.

## 13. Evaluation Plan

- Build/typecheck: Run `python -m unittest tests.test_core`.
- Desktop startup: Instantiate `ScreenMouseRecorderApp` with a temp base dir.
- Screenshot/visual: Launch app and inspect both pages after major UI changes.
- Responsive: Check default and minimum window sizes for text overlap.
- Contrast/readability: Verify muted text remains readable on `#f8fafb`.
- Interaction states: Check disabled, recording, paused, saving, analysis generating, generated, and failure states.
- Product fit: Confirm each page supports one primary job without explaining itself too much.
- Reference alignment: Airtable/Mintlify/Sentry influences should refine clarity and density, not become visible brand imitation.
- Generic UI regression: Reject changes that add fake cards, hero copy, gradients, or non-functional decoration.
- Better-than-original check: The user should find Start, Stop, Import, Generate, and Open Output faster than before.
