from __future__ import annotations

from typing import Any
import tkinter as tk
from tkinter import ttk

from .components import Tooltip, confirmation_checkbutton
from .theme import COLORS, FONT_SMALL, FONT_SMALL_BOLD, FONT_TIMER, FONT_UI, FONT_UI_BOLD


def build_record_page(app: Any, parent: tk.Widget) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)

    body = ttk.Frame(parent, style="App.TFrame")
    body.grid(row=0, column=0, sticky="nsew")
    body.columnconfigure(0, weight=0, minsize=276)
    body.columnconfigure(1, weight=1, minsize=500)
    body.columnconfigure(2, weight=0, minsize=320)
    body.rowconfigure(0, weight=1)

    _build_workflow(app, body).grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    _build_console(app, body).grid(row=0, column=1, sticky="nsew", padx=(0, 10))
    _build_settings(app, body).grid(row=0, column=2, sticky="nsew")


def _build_workflow(app: Any, parent: tk.Widget) -> ttk.LabelFrame:
    workflow = ttk.LabelFrame(parent, text="录制流程", style="Panel.TLabelframe", padding=14)
    workflow.configure(width=276)
    workflow.columnconfigure(0, weight=1)
    workflow.rowconfigure(6, weight=1)

    region = _step_frame(workflow, 0, "1", "选择录制区域")
    _variable_text(region, 1, app.region_var, wraplength=202, fg=COLORS["text_secondary"])
    region_actions = ttk.Frame(region, style="Panel.TFrame")
    region_actions.grid(row=2, column=1, sticky="ew", pady=(8, 0))
    region_actions.columnconfigure(0, weight=1)
    region_actions.columnconfigure(1, weight=1)
    app.select_button = ttk.Button(region_actions, text="选择区域", command=app.select_region)
    app.select_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    app.cancel_region_button = ttk.Button(region_actions, text="取消", command=app.clear_region)
    app.cancel_region_button.grid(row=0, column=1, sticky="ew")

    _divider(workflow, 1)

    calibration = _step_frame(workflow, 2, "2", "坐标对应检查")
    _variable_text(calibration, 1, app.calibration_var, wraplength=202)
    app.calibrate_button = ttk.Button(calibration, text="对应检查", command=app.run_calibration)
    app.calibrate_button.grid(row=2, column=1, sticky="w", pady=(8, 0))

    _divider(workflow, 3)

    readiness = _step_frame(workflow, 4, "3", "开始长时间测试")
    _variable_text(readiness, 1, app.readiness_var, wraplength=202)
    tk.Label(
        readiness,
        text="输出可写、FFmpeg 就绪并确认记录后即可开始。",
        bg=COLORS["panel_bg"],
        fg=COLORS["muted"],
        anchor="nw",
        justify="left",
        wraplength=202,
        font=FONT_SMALL,
    ).grid(row=2, column=1, sticky="ew", pady=(6, 0))

    return workflow


def _build_console(app: Any, parent: tk.Widget) -> ttk.Frame:
    center = ttk.Frame(parent, style="App.TFrame")
    center.columnconfigure(0, weight=1)
    center.rowconfigure(2, weight=1)

    control = ttk.LabelFrame(center, text="录制控制", style="Panel.TLabelframe", padding=16)
    control.grid(row=0, column=0, sticky="ew")
    control.configure(height=258)
    control.grid_propagate(False)
    control.columnconfigure(0, weight=1)

    tk.Label(
        control,
        textvariable=app.elapsed_var,
        bg=COLORS["panel_bg"],
        fg=COLORS["text"],
        width=10,
        anchor="center",
        font=FONT_TIMER,
    ).grid(row=0, column=0, sticky="ew", pady=(10, 0))
    ttk.Label(control, text="录制时长", style="Muted.TLabel").grid(row=1, column=0, sticky="n", pady=(0, 16))

    app.recording_banner = tk.Label(
        control,
        textvariable=app.recording_banner_var,
        bg=COLORS["border_soft"],
        fg=COLORS["text_secondary"],
        padx=12,
        pady=8,
        height=1,
        wraplength=430,
        justify="center",
        font=FONT_UI_BOLD,
        anchor="center",
    )
    app.recording_banner.grid(row=2, column=0, sticky="ew", pady=(0, 16))

    record_actions = ttk.Frame(control, style="Panel.TFrame")
    record_actions.grid(row=3, column=0, sticky="ew", pady=(0, 2))
    for column in range(3):
        record_actions.columnconfigure(column, weight=1)
    record_actions.configure(height=54)
    record_actions.grid_propagate(False)
    app.primary_button = app._transport_button(record_actions, "▶", app._play_action, COLORS["green"])
    app.primary_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
    app.pause_button = app._transport_button(record_actions, "Ⅱ", app.pause_recording, COLORS["yellow"])
    app.pause_button.grid(row=0, column=1, sticky="ew", padx=8)
    app.finish_button = app._transport_button(record_actions, "■", app.stop_recording, COLORS["red"])
    app.finish_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))

    stats = ttk.Frame(center, style="App.TFrame")
    stats.grid(row=1, column=0, sticky="ew", pady=(12, 12))
    for column in range(3):
        stats.columnconfigure(column, weight=1)
    app._metric(stats, 0, "视频段", app.segment_count_var)
    app._metric(stats, 1, "暂停次数", app.pause_count_var)
    app._metric(stats, 2, "鼠标映射", app.mouse_video_var)

    latest = ttk.LabelFrame(center, text="最近 Session", style="Panel.TLabelframe", padding=14)
    latest.grid(row=2, column=0, sticky="nsew")
    latest.columnconfigure(0, weight=1)
    latest.rowconfigure(3, weight=1)

    tk.Label(
        latest,
        textvariable=app.session_var,
        bg=COLORS["panel_alt"],
        fg=COLORS["text_secondary"],
        anchor="w",
        justify="left",
        wraplength=440,
        font=FONT_SMALL,
        padx=8,
        pady=7,
        highlightbackground=COLORS["border_soft"],
        highlightthickness=1,
    ).grid(row=0, column=0, sticky="ew", pady=(0, 10))

    actions = ttk.Frame(latest, style="Panel.TFrame")
    actions.grid(row=1, column=0, sticky="w", pady=(0, 10))
    ttk.Button(actions, text="文件夹", command=app.open_output).grid(row=0, column=0, padx=(0, 6))
    ttk.Button(actions, text="视频", command=app.open_video).grid(row=0, column=1, padx=(0, 6))
    recalc = ttk.Button(actions, text="重算", command=app.regenerate_outputs)
    recalc.grid(row=0, column=2)
    Tooltip(recalc, "重新生成摘要、表格和分析文件。")

    tk.Label(
        latest,
        textvariable=app.summary_var,
        bg=COLORS["panel_bg"],
        fg=COLORS["text_secondary"],
        anchor="nw",
        justify="left",
        wraplength=455,
        font=FONT_UI,
    ).grid(row=2, column=0, sticky="ew", pady=(0, 8))
    tk.Label(
        latest,
        textvariable=app.asset_status_var,
        bg=COLORS["panel_bg"],
        fg=COLORS["muted"],
        anchor="nw",
        justify="left",
        wraplength=455,
        font=FONT_SMALL,
    ).grid(row=3, column=0, sticky="new")

    return center


def _build_settings(app: Any, parent: tk.Widget) -> ttk.LabelFrame:
    settings = ttk.LabelFrame(parent, text="记录设置", style="Panel.TLabelframe", padding=14)
    settings.configure(width=320)
    settings.columnconfigure(0, weight=1)
    settings.rowconfigure(1, weight=1)

    output = ttk.Frame(settings, style="Panel.TFrame")
    output.grid(row=0, column=0, sticky="ew", pady=(0, 12))
    output.columnconfigure(0, weight=1)
    output.columnconfigure(1, weight=1)

    ttk.Label(output, text="输出目录", style="Panel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
    app.output_entry = ttk.Entry(output, textvariable=app.output_var, state="readonly")
    app.output_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 6))
    app.browse_button = ttk.Button(output, text="浏览", command=app.choose_output_root)
    app.browse_button.grid(row=2, column=0, sticky="ew", padx=(0, 6))
    app.open_button = ttk.Button(output, text="打开", command=app.open_output)
    app.open_button.grid(row=2, column=1, sticky="ew")

    ttk.Label(output, text="Session", style="Panel.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
    app.session_name_entry = ttk.Entry(output, textvariable=app.session_name_var)
    app.session_name_entry.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    notebook = ttk.Notebook(settings, style="Settings.TNotebook", takefocus=False)
    notebook.bind("<ButtonRelease-1>", lambda _event: app.root.focus_set(), add="+")
    notebook.grid(row=1, column=0, sticky="nsew")
    options = ttk.Frame(notebook, style="Panel.TFrame", padding=(10, 10, 10, 8))
    advanced = ttk.Frame(notebook, style="Panel.TFrame", padding=(10, 10, 10, 8))
    notebook.add(options, text="记录选项")
    notebook.add(advanced, text="高级参数")
    options.columnconfigure(0, weight=1)

    row = 0
    app._option(options, row, "区域外活动", app.record_outside_var, "开启后，录制区域外的鼠标坐标也会写入日志；关闭后只保留区域内数据。")
    row += 1
    app._option(options, row, "轨迹采样", app.samples_var, "按采样频率持续记录鼠标位置，生成 mouse_samples.jsonl。")
    row += 1
    app._option(options, row, "点击识别", app.clicks_var, "记录 down/up，并根据时间和距离合成 click / double_click_candidate。")
    row += 1
    app._option(options, row, "滚轮记录", app.wheel_var, "记录鼠标滚轮方向和滚动量，用于分析浏览、缩放等行为。")
    row += 1
    app._option(options, row, "拖拽识别", app.drag_var, "按按下、移动距离、抬起识别 drag_start / drag_move / drag_end。")
    row += 1
    app._option(options, row, "同步标记", app.sync_var, "调试用。开启后录制开始时在视频里闪现同步标记，并在日志里写入 sync_marker。")
    row += 1
    app._option(options, row, "状态提示栏", app.recording_status_banner_var, "开启后在控制区显示录制、暂停、保存等状态提示；关闭后隐藏该提示栏，不影响录制数据。")

    for column in range(4):
        advanced.columnconfigure(column, weight=1 if column in (1, 3) else 0)
    app._number_field(advanced, 0, 0, "视频 FPS", app.video_fps_var, 1, 120)
    app._number_field(advanced, 0, 2, "采样 Hz", app.sample_fps_var, 1, 120)
    app._number_field(advanced, 1, 0, "点击间隔 ms", app.click_duration_var, 50, 2000)
    app._number_field(advanced, 1, 2, "点击距离 px", app.click_distance_var, 1, 80)
    app._number_field(advanced, 2, 0, "拖拽距离 px", app.drag_distance_var, 1, 120)
    app._number_field(advanced, 2, 2, "检查容差 px", app.calibration_tolerance_var, 20, 200)
    app._number_field(advanced, 3, 0, "倒计时秒", app.startup_countdown_var, 0, 10)

    privacy = confirmation_checkbutton(
        settings,
        app.root,
        2,
        "确认本地录制与鼠标记录",
        app.privacy_var,
        "应用会录制选定屏幕区域，并在本地记录鼠标活动数据。",
        command=app._refresh_readiness,
    )
    app.option_widgets.append(privacy)

    return settings


def _step_frame(parent: tk.Widget, row: int, number: str, title: str) -> tk.Frame:
    frame = tk.Frame(parent, bg=COLORS["panel_bg"])
    frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
    frame.columnconfigure(1, weight=1)
    tk.Label(
        frame,
        text=number,
        bg="#dceeff",
        fg=COLORS["blue"],
        width=2,
        height=1,
        font=FONT_SMALL_BOLD,
    ).grid(row=0, column=0, sticky="n", padx=(0, 10), pady=(1, 0))
    tk.Label(
        frame,
        text=title,
        bg=COLORS["panel_bg"],
        fg=COLORS["text"],
        anchor="w",
        font=FONT_UI_BOLD,
    ).grid(row=0, column=1, sticky="ew")
    return frame


def _variable_text(
    parent: tk.Widget,
    row: int,
    variable: tk.StringVar,
    *,
    wraplength: int,
    fg: str = COLORS["muted"],
) -> None:
    tk.Label(
        parent,
        textvariable=variable,
        bg=COLORS["panel_bg"],
        fg=fg,
        anchor="nw",
        justify="left",
        wraplength=wraplength,
        font=FONT_SMALL,
    ).grid(row=row, column=1, sticky="ew", pady=(4, 0))


def _divider(parent: tk.Widget, row: int) -> None:
    tk.Frame(parent, bg=COLORS["border_soft"], height=1).grid(row=row, column=0, sticky="ew", pady=(0, 14))
