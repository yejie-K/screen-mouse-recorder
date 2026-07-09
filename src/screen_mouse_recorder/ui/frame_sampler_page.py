from __future__ import annotations

from typing import Any
import tkinter as tk
from tkinter import ttk

from .theme import COLORS, FONT_SMALL, FONT_UI, FONT_UI_BOLD


def build_frame_sampler_page(app: Any, parent: tk.Widget) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)
    parent.rowconfigure(1, weight=0)

    content = ttk.Frame(parent, style="App.TFrame")
    content.grid(row=0, column=0, sticky="nsew")
    content.columnconfigure(0, weight=1)
    content.rowconfigure(1, weight=1)

    _build_source_panel(app, content).grid(row=0, column=0, sticky="ew", pady=(0, 12))

    middle = ttk.Frame(content, style="App.TFrame")
    middle.grid(row=1, column=0, sticky="nsew")
    middle.columnconfigure(0, weight=0, minsize=430)
    middle.columnconfigure(1, weight=1, minsize=660)
    middle.rowconfigure(0, weight=1)

    _build_basic_panel(app, middle).grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    _build_crop_panel(app, middle).grid(row=0, column=1, sticky="nsew")

    actions = tk.Frame(parent, bg=COLORS["panel_bg"], highlightbackground=COLORS["border"], highlightthickness=1)
    actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
    actions.configure(height=64)
    actions.grid_propagate(False)
    actions.columnconfigure(0, weight=0)
    actions.columnconfigure(1, weight=1)

    button_group = ttk.Frame(actions, style="Panel.TFrame")
    button_group.grid(row=0, column=0, sticky="w", padx=12, pady=12)
    app.frame_estimate_button = ttk.Button(button_group, text="预估", command=app.estimate_frame_sampling, width=10)
    app.frame_estimate_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
    app.frame_generate_button = ttk.Button(
        button_group,
        text="生成合成图",
        command=app.run_frame_sampling,
        style="Primary.TButton",
        width=14,
    )
    app.frame_generate_button.grid(row=0, column=1, sticky="ew", padx=(0, 8))
    app.frame_open_button = ttk.Button(button_group, text="打开输出", command=app.open_frame_output, state="disabled", width=10)
    app.frame_open_button.grid(row=0, column=2, sticky="ew")

    progress_group = ttk.Frame(actions, style="Panel.TFrame")
    progress_group.grid(row=0, column=1, sticky="ew", padx=(8, 12), pady=10)
    progress_group.columnconfigure(0, weight=1)
    progress_group.columnconfigure(1, weight=0, minsize=150)
    tk.Label(
        progress_group,
        textvariable=app.frame_progress_var,
        bg=COLORS["panel_bg"],
        fg=COLORS["muted"],
        anchor="w",
        font=FONT_SMALL,
    ).grid(row=0, column=0, sticky="ew")
    tk.Label(
        progress_group,
        textvariable=app.frame_remaining_var,
        bg=COLORS["panel_bg"],
        fg=COLORS["muted"],
        anchor="e",
        font=FONT_SMALL,
    ).grid(row=0, column=1, sticky="e", padx=(8, 0))
    app.frame_progress_bar = ttk.Progressbar(
        progress_group,
        variable=app.frame_progress_percent_var,
        maximum=100,
        mode="determinate",
    )
    app.frame_progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))


def _build_source_panel(app: Any, parent: tk.Widget) -> ttk.LabelFrame:
    panel = ttk.LabelFrame(parent, text="任务与预估", style="Panel.TLabelframe", padding=12)
    panel.columnconfigure(1, weight=1)
    panel.columnconfigure(2, minsize=100)
    panel.columnconfigure(3, minsize=54)
    panel.columnconfigure(4, minsize=168)

    ttk.Label(panel, text="视频", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
    ttk.Entry(panel, textvariable=app.frame_video_var, state="readonly").grid(
        row=0, column=1, sticky="ew", padx=(0, 8)
    )
    ttk.Button(panel, text="选择视频", command=app.choose_frame_video, width=10).grid(row=0, column=2, sticky="ew")

    ttk.Label(panel, text="输出", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
    ttk.Entry(panel, textvariable=app.frame_output_var).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(8, 0))
    ttk.Button(panel, text="选择目录", command=app.choose_frame_output, width=10).grid(row=1, column=2, sticky="ew", pady=(8, 0))
    ttk.Label(panel, text="文件名", style="Panel.TLabel").grid(row=1, column=3, sticky="w", padx=(12, 8), pady=(8, 0))
    ttk.Entry(panel, textvariable=app.frame_output_name_var).grid(row=1, column=4, sticky="ew", pady=(8, 0))

    metrics = ttk.Frame(panel, style="Panel.TFrame")
    metrics.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(10, 0))
    for column in range(5):
        metrics.columnconfigure(column, weight=1)
    _metric_text(metrics, 0, "时长", app.frame_duration_var)
    _metric_text(metrics, 1, "分辨率", app.frame_resolution_var)
    _metric_text(metrics, 2, "抽帧", app.frame_count_var)
    _metric_text(metrics, 3, "合成图", app.frame_sheet_count_var)
    _metric_text(metrics, 4, "耗时", app.frame_eta_var)
    return panel


def _metric_text(parent: tk.Widget, column: int, label: str, variable: tk.StringVar) -> None:
    item = tk.Frame(parent, bg=COLORS["panel_bg"])
    item.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 14, 0))
    item.columnconfigure(1, weight=1)
    tk.Label(item, text=f"{label} ", bg=COLORS["panel_bg"], fg=COLORS["muted"], font=FONT_SMALL).grid(row=0, column=0, sticky="w")
    tk.Label(
        item,
        textvariable=variable,
        bg=COLORS["panel_bg"],
        fg=COLORS["text"],
        font=FONT_UI_BOLD,
        anchor="w",
    ).grid(row=0, column=1, sticky="ew")


def _build_basic_panel(app: Any, parent: tk.Widget) -> ttk.LabelFrame:
    panel = ttk.LabelFrame(parent, text="抽帧参数", style="Panel.TLabelframe", padding=12)
    panel.columnconfigure(0, weight=0, minsize=74)
    panel.columnconfigure(1, weight=1, minsize=118)
    panel.columnconfigure(2, weight=0, minsize=74)
    panel.columnconfigure(3, weight=1, minsize=118)
    ttk.Label(panel, text="合成模式", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=5, padx=(0, 8))
    mode = ttk.Combobox(
        panel,
        textvariable=app.frame_mode_var,
        values=("均匀抽帧", "点击关键帧"),
        state="readonly",
        width=10,
    )
    mode.grid(row=0, column=1, sticky="ew", pady=5, padx=(0, 14))
    create_timecode_fields(panel, 1, 0, "开始时间", app.frame_start_var, columnspan=3)
    create_timecode_fields(panel, 2, 0, "结束时间", app.frame_end_var, allow_empty=True, empty_text="到结尾", columnspan=3)
    _labeled_entry(panel, 3, 0, "抽帧间隔秒", app.frame_interval_var, "10")
    _labeled_entry(panel, 3, 2, "单帧宽度", app.frame_thumb_width_var, "360")
    _labeled_entry(panel, 4, 0, "拼图列数", app.frame_cols_var, "5")
    _labeled_entry(panel, 4, 2, "拼图行数", app.frame_rows_var, "6")

    ttk.Label(panel, text="导出质量", style="Panel.TLabel").grid(row=5, column=0, sticky="w", pady=5, padx=(0, 8))
    quality = ttk.Combobox(
        panel,
        textvariable=app.frame_quality_preset_var,
        values=("低", "中", "高", "无损"),
        state="readonly",
        width=8,
    )
    quality.grid(row=5, column=1, sticky="ew", pady=5, padx=(0, 14))
    tk.Label(
        panel,
        text="JPG / PNG",
        bg=COLORS["panel_bg"],
        fg=COLORS["muted"],
        anchor="w",
        font=FONT_SMALL,
    ).grid(row=5, column=2, columnspan=2, sticky="ew", pady=5)

    flags = ttk.Frame(panel, style="Panel.TFrame")
    flags.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(8, 0))
    flags.columnconfigure(0, weight=1)
    _check(flags, 0, "显示时间戳", app.frame_show_timestamp_var, columnspan=4)
    _check(flags, 1, "显示序号", app.frame_show_index_var, columnspan=4)
    _check(flags, 2, "叠加鼠标点击点", app.frame_draw_click_markers_var, columnspan=4)
    _build_dense_section(app, panel, 7)
    return panel


def _build_crop_panel(app: Any, parent: tk.Widget) -> ttk.LabelFrame:
    panel = ttk.LabelFrame(parent, text="画面裁剪", style="Panel.TLabelframe", padding=12)
    panel.columnconfigure(0, weight=1)
    panel.rowconfigure(2, weight=1)

    crop_tools = ttk.Frame(panel, style="Panel.TFrame")
    crop_tools.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
    crop_tools.columnconfigure(2, weight=1)
    _check(crop_tools, 0, "启用裁剪", app.frame_crop_enabled_var)
    ttk.Button(crop_tools, text="重置全屏", command=app.reset_frame_crop, width=10).grid(row=0, column=1, sticky="w", padx=(12, 0))

    coord_fields = ttk.Frame(panel, style="Panel.TFrame")
    coord_fields.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 10))
    for column in range(4):
        coord_fields.columnconfigure(column, weight=1)
    _labeled_entry(coord_fields, 0, 0, "X", app.frame_crop_x_var, "0")
    _labeled_entry(coord_fields, 0, 2, "Y", app.frame_crop_y_var, "0")
    _labeled_entry(coord_fields, 1, 0, "宽", app.frame_crop_w_var, "全屏")
    _labeled_entry(coord_fields, 1, 2, "高", app.frame_crop_h_var, "全屏")

    preview_grid = ttk.Frame(panel, style="Panel.TFrame")
    preview_grid.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(0, 10))
    preview_grid.columnconfigure(0, weight=1, uniform="crop_preview")
    preview_grid.columnconfigure(1, weight=1, uniform="crop_preview")
    preview_grid.rowconfigure(1, weight=1)

    tk.Label(
        preview_grid,
        text="全画面定位",
        bg=COLORS["panel_bg"],
        fg=COLORS["text_secondary"],
        anchor="w",
        font=FONT_SMALL,
    ).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 4))
    tk.Label(
        preview_grid,
        text="裁剪预览",
        bg=COLORS["panel_bg"],
        fg=COLORS["text_secondary"],
        anchor="w",
        font=FONT_SMALL,
    ).grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))

    preview_wrap = tk.Frame(preview_grid, bg=COLORS["panel_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
    preview_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
    preview_wrap.configure(height=220)
    preview_wrap.grid_propagate(False)
    preview_wrap.columnconfigure(0, weight=1)
    preview_wrap.rowconfigure(0, weight=1)
    app.frame_crop_canvas = tk.Canvas(preview_wrap, width=320, height=202, bg="#1f1f1f", highlightthickness=0)
    app.frame_crop_canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
    app.bind_frame_crop_canvas()

    zoom_wrap = tk.Frame(preview_grid, bg=COLORS["panel_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
    zoom_wrap.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
    zoom_wrap.configure(height=220)
    zoom_wrap.grid_propagate(False)
    zoom_wrap.columnconfigure(0, weight=1)
    zoom_wrap.rowconfigure(0, weight=1)
    app.frame_crop_zoom_canvas = tk.Canvas(zoom_wrap, width=320, height=202, bg="#1f1f1f", highlightthickness=0)
    app.frame_crop_zoom_canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
    app.bind_frame_crop_zoom_canvas()

    time_controls = ttk.Frame(panel, style="Panel.TFrame")
    time_controls.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 10))
    time_controls.columnconfigure(1, weight=1)
    ttk.Label(time_controls, text="帧位置", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
    app.frame_crop_time_scale = ttk.Scale(
        time_controls,
        from_=0.0,
        to=1.0,
        variable=app.frame_crop_preview_seconds_var,
        command=app.on_frame_crop_preview_scale,
    )
    app.frame_crop_time_scale.grid(row=0, column=1, sticky="ew", padx=(0, 8))
    ttk.Label(
        time_controls,
        textvariable=app.frame_crop_preview_time_var,
        style="Panel.TLabel",
        width=18,
        anchor="e",
    ).grid(row=0, column=2, sticky="e")

    app.frame_crop_preview_buttons = []
    app.sync_frame_crop_preview_controls()

    for column in range(4):
        panel.columnconfigure(column, weight=1)
    return panel


def _build_dense_section(app: Any, parent: tk.Widget, row: int) -> None:
    divider = ttk.Separator(parent, orient="horizontal")
    divider.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(14, 10))

    header = ttk.Frame(parent, style="Panel.TFrame")
    header.grid(row=row + 1, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    header.columnconfigure(0, weight=1)
    tk.Label(
        header,
        text="关键段加密抽帧",
        bg=COLORS["panel_bg"],
        fg=COLORS["text_secondary"],
        anchor="w",
        font=FONT_UI_BOLD,
    ).grid(row=0, column=0, sticky="ew")
    ttk.Button(header, text="添加关键段", command=lambda: app.add_frame_dense_range(), width=12).grid(row=0, column=1, sticky="e")

    app.frame_dense_rows_container = ttk.Frame(parent, style="Panel.TFrame")
    app.frame_dense_rows_container.grid(row=row + 2, column=0, columnspan=4, sticky="ew")
    app.frame_dense_rows_container.columnconfigure(0, weight=1)
    app.render_frame_dense_rows()


def create_timecode_fields(
    parent: tk.Widget,
    row: int,
    column: int,
    label: str,
    variable: tk.Variable,
    *,
    allow_empty: bool = False,
    empty_text: str = "到结尾",
    columnspan: int = 1,
) -> None:
    ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=column, sticky="w", pady=5, padx=(0, 8))
    frame = create_timecode_inputs(parent, variable, allow_empty=allow_empty, empty_text=empty_text)
    frame.grid(row=row, column=column + 1, columnspan=columnspan, sticky="w", pady=5, padx=(0, 14))


def create_timecode_inputs(
    parent: tk.Widget,
    variable: tk.Variable,
    *,
    allow_empty: bool = False,
    empty_text: str = "到结尾",
    empty_as_blank: bool = False,
    compact: bool = False,
) -> tk.Frame:
    frame = tk.Frame(parent, bg=COLORS["panel_bg"])
    if compact:
        frame_width = 146
    else:
        frame_width = 260 if allow_empty else 178
    frame.configure(width=frame_width, height=32)
    frame.grid_propagate(False)
    parts = [tk.StringVar(value="00"), tk.StringVar(value="00"), tk.StringVar(value="00")]
    empty_var = tk.BooleanVar(value=allow_empty and not str(variable.get()).strip())
    syncing = {"active": False}

    def parse_parts(value: str) -> tuple[int, int, int] | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            if ":" in text:
                raw_parts = [float(part or 0) for part in text.split(":")]
                if len(raw_parts) == 2:
                    total = raw_parts[0] * 60 + raw_parts[1]
                elif len(raw_parts) == 3:
                    total = raw_parts[0] * 3600 + raw_parts[1] * 60 + raw_parts[2]
                else:
                    total = 0
            else:
                total = float(text)
        except ValueError:
            total = 0
        total_seconds = max(0, int(round(total)))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return hours, minutes, seconds

    def set_entries(values: tuple[int, int, int]) -> None:
        for part_var, value in zip(parts, values):
            part_var.set(f"{value:02d}")

    def field_value(index: int, maximum: int | None = None) -> int:
        text = parts[index].get().strip()
        try:
            value = int(text) if text else 0
        except ValueError:
            value = 0
        value = max(0, value)
        return min(maximum, value) if maximum is not None else value

    def set_field_state() -> None:
        # Keep the fields editable even when "到结尾" is selected. Typing a value
        # below will automatically switch the field back to a concrete end time.
        state = "normal"
        for child in frame.winfo_children():
            if isinstance(child, ttk.Entry):
                child.configure(state=state)

    def update_variable(*, normalize: bool = False) -> None:
        if syncing["active"]:
            return
        if allow_empty and empty_var.get():
            variable.set("")
            set_field_state()
            return
        if empty_as_blank and not any(part.get().strip() for part in parts):
            variable.set("")
            return
        hours = field_value(0)
        minutes = field_value(1, 59)
        seconds = field_value(2, 59)
        if normalize:
            set_entries((hours, minutes, seconds))
        syncing["active"] = True
        try:
            variable.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        finally:
            syncing["active"] = False

    def show_variable() -> None:
        if syncing["active"]:
            return
        syncing["active"] = True
        try:
            values = parse_parts(str(variable.get()))
            if values is None and allow_empty:
                empty_var.set(True)
                set_entries((0, 0, 0))
            elif values is None and empty_as_blank:
                empty_var.set(False)
                for part_var in parts:
                    part_var.set("")
            else:
                empty_var.set(False)
                set_entries(values or (0, 0, 0))
        finally:
            syncing["active"] = False
        set_field_state()

    def toggle_empty() -> None:
        if empty_var.get():
            variable.set("")
            set_field_state()
        else:
            update_variable(normalize=True)

    def update_from_manual_input(*, normalize: bool = False) -> None:
        if allow_empty and empty_var.get():
            empty_var.set(False)
        update_variable(normalize=normalize)

    validate_digits = (parent.register(lambda value: value == "" or value.isdigit()), "%P")
    for grid_column in (0, 2, 4):
        frame.columnconfigure(grid_column, minsize=38)
    for column, (part_var, unit) in enumerate(zip(parts, ("时", "分", "秒"))):
        entry = ttk.Entry(frame, textvariable=part_var, width=3, justify="center", validate="key", validatecommand=validate_digits)
        entry.grid(row=0, column=column * 2, sticky="ew")
        tk.Label(frame, text=unit, bg=COLORS["panel_bg"], fg=COLORS["muted"], font=FONT_SMALL).grid(
            row=0, column=column * 2 + 1, sticky="w", padx=(2, 5)
        )
        entry.bind("<KeyRelease>", lambda _event: update_from_manual_input(normalize=False))
        entry.bind("<FocusOut>", lambda _event: update_variable(normalize=True))

    if allow_empty:
        tk.Checkbutton(
            frame,
            text=empty_text,
            variable=empty_var,
            command=toggle_empty,
            bg=COLORS["panel_bg"],
            fg=COLORS["text_secondary"],
            activebackground=COLORS["panel_bg"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["panel_bg"],
            font=FONT_SMALL,
            relief="flat",
            highlightthickness=0,
        ).grid(row=0, column=6, sticky="w", padx=(4, 0))

    trace_name = variable.trace_add("write", lambda *_args: show_variable())

    def remove_trace(event: tk.Event) -> None:
        if event.widget is not frame:
            return
        try:
            variable.trace_remove("write", trace_name)
        except tk.TclError:
            pass

    frame.bind("<Destroy>", remove_trace, add="+")
    frame._timecode_state = (parts, empty_var)  # type: ignore[attr-defined]
    show_variable()
    return frame


def _labeled_entry(parent: tk.Widget, row: int, column: int, label: str, variable: tk.Variable, placeholder: str) -> None:
    ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=column, sticky="w", pady=5, padx=(0, 8))
    frame = tk.Frame(parent, bg=COLORS["panel_bg"])
    frame.grid(row=row, column=column + 1, sticky="ew", pady=5, padx=(0, 14))
    frame.columnconfigure(0, weight=1)
    entry = ttk.Entry(frame, width=10)
    entry.grid(row=0, column=0, sticky="ew")
    syncing = {"active": False, "focused": False}

    def show_value() -> None:
        if syncing["active"]:
            return
        syncing["active"] = True
        try:
            value = str(variable.get()).strip()
            entry.delete(0, "end")
            if value:
                entry.insert(0, value)
                entry.configure(foreground=COLORS["text"])
            elif placeholder and not syncing["focused"]:
                entry.insert(0, placeholder)
                entry.configure(foreground=COLORS["muted"])
            else:
                entry.configure(foreground=COLORS["text"])
        finally:
            syncing["active"] = False

    def commit_value() -> None:
        if syncing["active"]:
            return
        value = entry.get().strip()
        variable.set("" if placeholder and value == placeholder else value)

    def on_focus_in(_event: tk.Event) -> None:
        syncing["focused"] = True
        if placeholder and not str(variable.get()).strip() and entry.get() == placeholder:
            entry.delete(0, "end")
            entry.configure(foreground=COLORS["text"])

    def on_focus_out(_event: tk.Event) -> None:
        syncing["focused"] = False
        commit_value()
        show_value()

    def on_key_release(_event: tk.Event) -> None:
        if not syncing["active"]:
            variable.set(entry.get().strip())

    variable.trace_add("write", lambda *_args: show_value())
    entry.bind("<FocusIn>", on_focus_in)
    entry.bind("<FocusOut>", on_focus_out)
    entry.bind("<KeyRelease>", on_key_release)
    show_value()


def _check(parent: tk.Widget, column_or_row: int, text: str, variable: tk.BooleanVar, *, columnspan: int = 1) -> None:
    if columnspan > 1:
        row = column_or_row
        column = 0
    else:
        row = 0
        column = column_or_row
    widget = tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        bg=COLORS["panel_bg"],
        fg=COLORS["text_secondary"],
        activebackground=COLORS["panel_bg"],
        activeforeground=COLORS["text"],
        selectcolor=COLORS["panel_bg"],
        anchor="w",
        font=FONT_UI,
        relief="flat",
        highlightthickness=0,
    )
    widget.grid(row=row, column=column, columnspan=columnspan, sticky="w", pady=5)
