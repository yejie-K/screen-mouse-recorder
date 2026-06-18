from __future__ import annotations

from typing import Any
import tkinter as tk
from tkinter import ttk


def build_analysis_page(app: Any, parent: tk.Widget) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(2, weight=1)

    import_panel = ttk.LabelFrame(parent, text="导入", style="Panel.TLabelframe", padding=14)
    import_panel.grid(row=0, column=0, sticky="ew", pady=(0, 12))
    import_panel.columnconfigure(1, weight=1)
    import_panel.columnconfigure(2, minsize=112)
    import_panel.columnconfigure(3, minsize=112)

    ttk.Label(import_panel, text="输入", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
    ttk.Entry(import_panel, textvariable=app.analysis_input_var, state="readonly").grid(
        row=0, column=1, sticky="ew", padx=(0, 8)
    )
    ttk.Button(import_panel, text="选择 xlsx", command=app.choose_analysis_xlsx, width=12).grid(
        row=0, column=2, sticky="ew", padx=(0, 8)
    )
    ttk.Button(import_panel, text="选择文件夹", command=app.choose_analysis_folder, width=12).grid(
        row=0, column=3, sticky="ew"
    )

    ttk.Label(import_panel, text="输出", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
    ttk.Entry(import_panel, textvariable=app.analysis_output_var, state="readonly").grid(
        row=1, column=1, columnspan=3, sticky="ew", pady=(8, 0)
    )

    summary_panel = ttk.LabelFrame(parent, text="数据检查", style="Panel.TLabelframe", padding=14)
    summary_panel.grid(row=1, column=0, sticky="ew", pady=(0, 12))
    summary_panel.columnconfigure(0, weight=1)
    metrics = ttk.Frame(summary_panel, style="Panel.TFrame")
    metrics.grid(row=0, column=0, sticky="ew")
    for column in range(5):
        metrics.columnconfigure(column, weight=1)
    app._analysis_metric(metrics, 0, "事件", app.analysis_events_var)
    app._analysis_metric(metrics, 1, "采样", app.analysis_samples_var)
    app._analysis_metric(metrics, 2, "点击", app.analysis_clicks_var)
    app._analysis_metric(metrics, 3, "时长", app.analysis_duration_var)
    app._analysis_metric(metrics, 4, "元数据", app.analysis_meta_var)
    tk.Label(
        summary_panel,
        textvariable=app.analysis_summary_var,
        bg="#ffffff",
        fg="#6b6b6b",
        height=1,
        anchor="w",
        justify="left",
        wraplength=980,
        font=("Segoe UI", 9),
    ).grid(row=1, column=0, sticky="ew", pady=(8, 0))

    output_panel = ttk.LabelFrame(parent, text="生成", style="Panel.TLabelframe", padding=14)
    output_panel.grid(row=2, column=0, sticky="nsew")
    output_panel.columnconfigure(0, weight=1)
    output_panel.rowconfigure(1, weight=1)

    actions = ttk.Frame(output_panel, style="Panel.TFrame")
    actions.grid(row=0, column=0, sticky="ew", pady=(0, 12))
    actions.columnconfigure(2, weight=1)
    app.analysis_generate_button = ttk.Button(actions, text="生成分析报告", command=app.run_import_analysis, style="Primary.TButton", width=14)
    app.analysis_generate_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
    app.analysis_open_button = ttk.Button(actions, text="打开输出", command=app.open_analysis_output, state="disabled", width=12)
    app.analysis_open_button.grid(row=0, column=1, sticky="ew", padx=(0, 8))
    tk.Label(
        actions,
        textvariable=app.analysis_status_var,
        bg="#ffffff",
        fg="#6b6b6b",
        anchor="e",
        font=("Segoe UI", 9),
    ).grid(row=0, column=2, sticky="e")

    output_list = ttk.Frame(output_panel, style="Panel.TFrame")
    output_list.grid(row=1, column=0, sticky="new")
    output_list.columnconfigure(0, weight=1)
    output_list.columnconfigure(1, weight=1)
    output_items = [
        ("report", "中文分析报告", "mouse_behavior_report.xlsx"),
        ("heatmap_circle", "圆圈热力图", "click_heatmap_circle.png"),
        ("timeline", "每分钟事件节奏", "activity_timeline.png"),
        ("scatter", "点击位置分布", "click_scatter.png"),
        ("drag_durations", "拖拽时长分布", "drag_durations.png"),
    ]
    for index, (key, title, filename) in enumerate(output_items):
        app._analysis_output_row(output_list, index // 2, index % 2, key, title, filename)
