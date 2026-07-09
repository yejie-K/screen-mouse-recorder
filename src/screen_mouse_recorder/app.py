from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from PIL import Image, ImageTk

from . import __version__
from .config import AppConfig
from .diagnostics.error_report import format_error_dialog_message
from .diagnostics.service import ErrorReporter
from .frame_sampler import (
    ClickKeyframeConfig,
    CropRegion,
    DenseRange,
    FrameSamplerConfig,
    VideoInfo,
    default_output_dir,
    estimate_click_keyframe_sampling,
    estimate_sampling,
    extract_preview_frame,
    format_timecode,
    parse_timecode,
    probe_video,
    run_frame_export,
)
from .frame_export.ui_state import (
    ClickKeyframeFormState,
    FrameSamplerFormState,
    build_click_keyframe_config_from_state,
    build_frame_sampler_config_from_state,
    collect_dense_ranges,
    crop_region_from_values,
    quality_settings,
)
from .frame_export.progress import completed_progress, failed_progress, starting_progress, update_progress
from .models import Region, TimingContext, monotonic_ms, wall_time_iso
from .mouse_logger import MouseActivityLogger
from .naming import FRAME_EXPORT_DIR_NAME, build_session_id, sanitize_session_name
from .postprocess import generate_summary
from .reporting.service import BehaviorReportJob, make_behavior_report_job, run_behavior_report_job
from .region_selector import RecordingRegionOverlay, RegionSelector, run_click_calibration, show_sync_marker
from .storage import JsonlWriter, SessionStorage
from .ui.components import (
    metric_card,
    number_field as create_number_field,
    option_checkbutton,
    transport_button as create_transport_button,
)
from .ui.frame_sampler_page import build_frame_sampler_page, create_timecode_inputs
from .ui.record_page import build_record_page
from .ui.theme import COLORS, apply_app_theme
from .updater import UpdateStatus, apply_update, check_for_updates
from .video_recorder import FFmpegRecorder, concat_mp4_segments


class ScreenMouseRecorderApp:
    def __init__(self, root: tk.Tk, base_dir: Path) -> None:
        self.root = root
        self.base_dir = base_dir
        self.config_path = base_dir / "config.json"
        self.config = AppConfig.load(self.config_path)
        self.error_reporter = ErrorReporter(base_dir)
        self.region: Region | None = None
        self.storage: SessionStorage | None = None
        self.timing: TimingContext | None = None
        self.recorder: FFmpegRecorder | None = None
        self.logger: MouseActivityLogger | None = None
        self.region_overlay: RecordingRegionOverlay | None = None
        self.sync_markers: list[dict[str, Any]] = []
        self.is_recording = False
        self.is_starting = False
        self.is_stopping = False
        self.is_paused = False
        self.is_pausing = False
        self.is_counting_down = False
        self.calibration_data: dict[str, Any] | None = None
        self.segment_paths: list[Path] = []
        self.video_segments: list[dict[str, Any]] = []
        self.current_segment_path: Path | None = None
        self.current_segment_record: dict[str, Any] | None = None
        self.event_counter = 0
        self.sample_counter = 0
        self.countdown_window: tk.Toplevel | None = None
        self.countdown_after_id: str | None = None
        self.pause_started_monotonic_ms: float | None = None
        self.pause_periods: list[dict[str, Any]] = []
        self.current_session_name = self.config.session_name.strip()
        self.current_session_created_at = wall_time_iso()

        self.status_var = tk.StringVar(value="就绪")
        self.recording_banner_var = tk.StringVar(value="未开始")
        self.readiness_var = tk.StringVar(value="")
        self.env_var = tk.StringVar(value="")
        self.region_var = tk.StringVar(value="未选择录制区域")
        self.output_var = tk.StringVar(value=str(self.config.output_root_path(base_dir)))
        self.session_name_var = tk.StringVar(value=self.config.session_name)
        self.session_var = tk.StringVar(value="尚未录制")
        self.elapsed_var = tk.StringVar(value="00:00.000")
        self.summary_var = tk.StringVar(value="暂无摘要")
        self.calibration_var = tk.StringVar(value="未检查")
        self.segment_count_var = tk.StringVar(value="0")
        self.pause_count_var = tk.StringVar(value="0")
        self.mouse_video_var = tk.StringVar(value="视频可见")
        self.asset_status_var = tk.StringVar(value="等待生成")
        self.auto_report_output_dir: Path | None = None
        self.frame_video_var = tk.StringVar(value="未选择")
        self.frame_output_var = tk.StringVar(value=str((base_dir / self.config.frame_sampler_output_root).resolve()))
        self.frame_output_name_var = tk.StringVar(value=self.config.frame_sampler_output_name)
        self.frame_duration_var = tk.StringVar(value="--")
        self.frame_resolution_var = tk.StringVar(value="--")
        self.frame_count_var = tk.StringVar(value="--")
        self.frame_sheet_count_var = tk.StringVar(value="--")
        self.frame_eta_var = tk.StringVar(value="--")
        self.frame_status_var = tk.StringVar(value="选择视频后可预估抽帧数量和合成图数量。")
        self.frame_progress_var = tk.StringVar(value="")
        self.frame_progress_percent_var = tk.DoubleVar(value=0.0)
        self.frame_remaining_var = tk.StringVar(value="")
        self.frame_mode_var = tk.StringVar(
            value="点击关键帧" if self.config.frame_sampler_mode == "click_keyframes" else "均匀抽帧"
        )
        self.frame_start_var = tk.StringVar(value=self.config.frame_sampler_start)
        self.frame_end_var = tk.StringVar(value=self.config.frame_sampler_end)
        self.frame_interval_var = tk.StringVar(value=str(self.config.frame_sampler_interval_seconds).rstrip("0").rstrip("."))
        self.frame_cols_var = tk.StringVar(value=str(self.config.frame_sampler_cols))
        self.frame_rows_var = tk.StringVar(value=str(self.config.frame_sampler_rows))
        self.frame_thumb_width_var = tk.StringVar(value=str(self.config.frame_sampler_thumb_width))
        self.frame_keyframe_max_var = tk.StringVar(value=str(self.config.frame_sampler_keyframe_max_frames))
        self.frame_keyframe_time_dedupe_var = tk.StringVar(value=str(self.config.frame_sampler_keyframe_time_dedupe_ms))
        self.frame_keyframe_distance_dedupe_var = tk.StringVar(value=str(self.config.frame_sampler_keyframe_distance_dedupe_px))
        self.frame_keyframe_visual_threshold_var = tk.StringVar(
            value=str(getattr(self.config, "frame_sampler_keyframe_visual_threshold_percent", 22))
        )
        self.frame_quality_var = tk.StringVar(value=str(self.config.frame_sampler_jpeg_quality))
        self.frame_quality_preset_var = tk.StringVar(value=self._frame_quality_preset_from_config())
        self.frame_dense_start_var = tk.StringVar(value=self.config.frame_sampler_dense_start)
        self.frame_dense_end_var = tk.StringVar(value=self.config.frame_sampler_dense_end)
        self.frame_dense_interval_var = tk.StringVar(
            value=str(self.config.frame_sampler_dense_interval_seconds).rstrip("0").rstrip(".")
        )
        self.frame_crop_x_var = tk.StringVar(value=str(self.config.frame_sampler_crop_x))
        self.frame_crop_y_var = tk.StringVar(value=str(self.config.frame_sampler_crop_y))
        self.frame_crop_w_var = tk.StringVar(value=str(self.config.frame_sampler_crop_width or ""))
        self.frame_crop_h_var = tk.StringVar(value=str(self.config.frame_sampler_crop_height or ""))
        self.frame_source_path: Path | None = None
        self.frame_output_dir: Path | None = None
        self.frame_default_output_dir: Path | None = None
        self.frame_output_is_default = True
        self.frame_video_info: VideoInfo | None = None
        self.frame_is_running = False
        self.frame_progress_started_ms: float | None = None
        self.frame_crop_canvas: tk.Canvas | None = None
        self.frame_crop_zoom_canvas: tk.Canvas | None = None
        self.frame_crop_preview_original: Image.Image | None = None
        self.frame_crop_preview_photo: ImageTk.PhotoImage | None = None
        self.frame_crop_zoom_photo: ImageTk.PhotoImage | None = None
        self.frame_crop_preview_scale = 1.0
        self.frame_crop_preview_offset = (0, 0)
        self.frame_crop_view_zoom = 1.0
        self.frame_crop_drag_start: tuple[int, int] | None = None
        self.frame_crop_rect_id: int | None = None
        self.frame_crop_preview_seconds_var = tk.DoubleVar(value=0.0)
        self.frame_crop_preview_time_var = tk.StringVar(value="00:00:00 / --")
        self.frame_crop_time_scale: ttk.Scale | None = None
        self.frame_crop_preview_buttons: list[ttk.Button] = []
        self.frame_crop_preview_after_id: str | None = None
        self.frame_crop_preview_controls_updating = False
        self.frame_crop_value_trace_updating = False
        self.frame_dense_rows_container: ttk.Frame | None = None
        self.frame_dense_ranges: list[dict[str, tk.StringVar]] = []
        self.frame_click_events_path: Path | None = self._resolve_config_path(self.config.frame_sampler_click_events_path)
        self.frame_click_events_var = tk.StringVar(value=str(self.frame_click_events_path or ""))
        self.main_notebook: ttk.Notebook | None = None
        self._tab_animation_after_ids: list[str] = []
        self.update_button: tk.Button | None = None
        self.update_status: UpdateStatus | None = None
        self.update_check_running = False
        self.update_apply_running = False
        self.update_prompt_shown = False

        self.record_outside_var = tk.BooleanVar(value=self.config.record_outside_region)
        self.samples_var = tk.BooleanVar(value=self.config.record_mouse_samples)
        self.clicks_var = tk.BooleanVar(value=self.config.record_click_events)
        self.wheel_var = tk.BooleanVar(value=self.config.record_wheel_events)
        self.drag_var = tk.BooleanVar(value=self.config.record_drag_events)
        self.sync_var = tk.BooleanVar(value=self.config.show_sync_marker)
        self.recording_status_banner_var = tk.BooleanVar(value=self.config.show_recording_status_banner)
        self.privacy_var = tk.BooleanVar(value=False)
        self.frame_show_timestamp_var = tk.BooleanVar(value=self.config.frame_sampler_show_timestamp)
        self.frame_show_index_var = tk.BooleanVar(value=self.config.frame_sampler_show_index)
        self.frame_dense_enabled_var = tk.BooleanVar(value=self.config.frame_sampler_dense_enabled)
        self.frame_crop_enabled_var = tk.BooleanVar(value=self.config.frame_sampler_crop_enabled)
        self.frame_draw_click_markers_var = tk.BooleanVar(value=self.config.frame_sampler_draw_click_markers)
        self.frame_dense_ranges = self._initial_frame_dense_ranges()
        self.video_fps_var = tk.IntVar(value=self.config.video_fps)
        self.sample_fps_var = tk.IntVar(value=self.config.sample_fps)
        self.click_duration_var = tk.IntVar(value=self.config.click_max_duration_ms)
        self.click_distance_var = tk.IntVar(value=self.config.click_max_distance_px)
        self.drag_distance_var = tk.IntVar(value=self.config.drag_min_distance_px)
        self.calibration_tolerance_var = tk.IntVar(value=self.config.calibration_click_tolerance_px)
        self.startup_countdown_var = tk.IntVar(value=self.config.startup_countdown_seconds)

        self.option_widgets: list[tk.Widget] = []
        self._build_ui()
        self._apply_recording_banner_visibility()
        self._bind_config_vars()
        self._refresh_environment()
        self._refresh_readiness()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", self._on_escape)
        self.root.after(1800, self.check_for_updates)

    def _build_ui(self) -> None:
        self.root.title("Screen Mouse Recorder")
        self.root.geometry("1220x780")
        self.root.minsize(1220, 780)
        self.root.maxsize(1220, 780)
        self.root.resizable(False, False)
        apply_app_theme(self.root)

        shell = ttk.Frame(self.root, style="App.TFrame", padding=18)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Screen Mouse Recorder", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        version_box = ttk.Frame(header, style="App.TFrame")
        version_box.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(7, 0))
        ttk.Label(version_box, text=f"v{__version__}", style="App.TLabel").pack(side="left")
        self.update_button = tk.Button(
            version_box,
            text="↑",
            command=self.prompt_update,
            bg=COLORS["green"],
            fg="white",
            activebackground="#0b6a0b",
            activeforeground="white",
            bd=0,
            padx=5,
            pady=0,
            width=2,
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            takefocus=False,
        )
        tk.Label(
            header,
            textvariable=self.env_var,
            bg=COLORS["app_bg"],
            fg=COLORS["muted"],
            anchor="e",
            font=("Segoe UI", 9),
            width=24,
        ).grid(row=0, column=1, sticky="e", padx=(12, 14), pady=(6, 0))
        self.status_badge = tk.Label(
            header,
            textvariable=self.status_var,
            bg=COLORS["panel_alt"],
            fg=COLORS["text_secondary"],
            padx=12,
            pady=4,
            width=10,
            anchor="center",
            font=("Segoe UI", 10, "bold"),
        )
        self.status_badge.grid(row=0, column=2, sticky="e")

        main_notebook = ttk.Notebook(shell, style="Settings.TNotebook", takefocus=False)
        self.main_notebook = main_notebook
        main_notebook.bind("<ButtonRelease-1>", lambda _event: self.root.focus_set(), add="+")
        main_notebook.bind("<<NotebookTabChanged>>", self._animate_tab_change, add="+")
        main_notebook.grid(row=1, column=0, sticky="nsew")

        record_page = ttk.Frame(main_notebook, style="TabPage.TFrame", padding=(0, 12, 0, 0))
        frame_sampler_page = ttk.Frame(main_notebook, style="TabPage.TFrame", padding=(0, 12, 0, 0))
        main_notebook.add(record_page, text="录制")
        main_notebook.add(frame_sampler_page, text="抽帧拼图")

        build_record_page(self, record_page)
        self._build_frame_sampler_page(frame_sampler_page)

    def _animate_tab_change(self, _event: tk.Event | None = None) -> None:
        notebook = self.main_notebook
        if notebook is None:
            return
        for after_id in self._tab_animation_after_ids:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self._tab_animation_after_ids.clear()
        for tab_id in notebook.tabs():
            page = notebook.nametowidget(tab_id)
            if isinstance(page, ttk.Frame):
                page.configure(style="TabPage.TFrame")
        try:
            selected_page = notebook.nametowidget(notebook.select())
        except tk.TclError:
            return
        if not isinstance(selected_page, ttk.Frame):
            return

        def set_style(style_name: str) -> None:
            try:
                selected_page.configure(style=style_name)
            except tk.TclError:
                pass

        set_style("TabPagePulse.TFrame")
        self._tab_animation_after_ids.append(self.root.after(90, lambda: set_style("TabPage.TFrame")))

    def check_for_updates(self) -> None:
        if self.update_check_running or self.update_apply_running:
            return
        self.update_check_running = True

        def worker() -> None:
            status = check_for_updates(self.base_dir)
            try:
                self.root.after(0, lambda: self._on_update_check_done(status))
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="update-check", daemon=True).start()

    def _on_update_check_done(self, status: UpdateStatus) -> None:
        self.update_check_running = False
        self.update_status = status
        if not status.available:
            self._hide_update_button()
            return

        self._show_update_button()
        if self.update_prompt_shown or status.dirty:
            return
        self.update_prompt_shown = True
        self.prompt_update()

    def _show_update_button(self) -> None:
        if self.update_button is None:
            return
        self.update_button.configure(state="normal", text="↑")
        if not self.update_button.winfo_ismapped():
            self.update_button.pack(side="left", padx=(6, 0))

    def _hide_update_button(self) -> None:
        if self.update_button is not None and self.update_button.winfo_ismapped():
            self.update_button.pack_forget()

    def prompt_update(self) -> None:
        status = self.update_status
        if status is None or not status.available:
            self.check_for_updates()
            return
        if self.is_recording or self.is_paused or self.is_starting or self.is_stopping or self.frame_is_running:
            messagebox.showinfo("暂不能更新", "录制或抽帧运行中不能更新，请结束当前任务后再试。")
            return
        if status.dirty:
            messagebox.showwarning(
                "暂不能自动更新",
                "检测到本地代码目录有改动，已阻止自动拉取。\n\n"
                "录制数据不会影响更新；这里指的是源码文件存在本地改动。请先提交、备份或切换到干净版本后再更新。",
            )
            return

        message = (
            f"GitHub 上发现新版本，当前分支 {status.current_branch} 落后 {status.behind_count} 个提交。\n\n"
            "同意后会从 GitHub 拉取代码并只执行 fast-forward 更新；sessions、auto_report、frame_exports 等本地数据不会被删除。\n\n"
            "现在更新吗？"
        )
        if not messagebox.askyesno("发现新版本", message):
            return
        self.apply_update_from_github()

    def apply_update_from_github(self) -> None:
        if self.update_apply_running:
            return
        status = self.update_status
        if status is None:
            return
        self.update_apply_running = True
        if self.update_button is not None:
            self.update_button.configure(state="disabled", text="...")

        def worker() -> None:
            result = apply_update(status)
            try:
                self.root.after(0, lambda: self._on_update_applied(result))
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="update-apply", daemon=True).start()

    def _on_update_applied(self, result: UpdateStatus) -> None:
        self.update_apply_running = False
        self.update_status = result
        if result.message == "更新完成":
            self._hide_update_button()
            if messagebox.askyesno("更新完成", "最新版代码已拉取完成，需要重启软件后生效。\n\n是否现在重启？"):
                self._restart_app()
            return
        self._show_update_button()
        self._show_error_report(
            "更新失败",
            "update_apply",
            RuntimeError(result.message or "更新失败，请稍后重试。"),
            {
                "branch": result.current_branch,
                "target_ref": result.target_ref,
                "behind_count": result.behind_count,
                "ahead_count": result.ahead_count,
                "dirty": result.dirty,
            },
        )

    def _restart_app(self) -> None:
        command = [sys.executable, *sys.argv]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs = {"creationflags": creationflags} if creationflags else {}
        try:
            subprocess.Popen(command, cwd=str(self.base_dir), close_fds=True, **kwargs)
        except OSError as exc:
            self._show_error_report("重启失败", "app_restart", exc)
            return
        self.root.destroy()

    def _create_error_report(
        self,
        stage: str,
        error: BaseException,
        context: dict[str, Any] | None = None,
    ) -> tuple[Any, Path | None]:
        result = self.error_reporter.create(stage, error, context)
        return result.report, result.txt_path

    def _show_error_report(
        self,
        title: str,
        stage: str,
        error: BaseException,
        context: dict[str, Any] | None = None,
        *,
        warning: bool = False,
    ) -> tuple[Any, Path | None]:
        report, txt_path = self._create_error_report(stage, error, context)
        message = format_error_dialog_message(report, txt_path)
        if warning:
            messagebox.showwarning(title, message)
        else:
            messagebox.showerror(title, message)
        return report, txt_path

    def _build_frame_sampler_page(self, parent: tk.Widget) -> None:
        build_frame_sampler_page(self, parent)

    def _frame_quality_preset_from_config(self) -> str:
        preset = str(getattr(self.config, "frame_sampler_quality_preset", "")).strip()
        if preset in {"低", "中", "高", "无损"}:
            return preset
        quality = int(getattr(self.config, "frame_sampler_jpeg_quality", 85) or 85)
        if quality <= 70:
            return "低"
        if quality <= 84:
            return "中"
        return "高"

    def _resolve_config_path(self, value: str) -> Path | None:
        text = str(value or "").strip()
        if not text:
            return None
        path = Path(text)
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()

    def _initial_frame_dense_ranges(self) -> list[dict[str, tk.StringVar]]:
        rows: list[dict[str, tk.StringVar]] = []
        for item in self.config.frame_sampler_dense_ranges:
            if not isinstance(item, dict):
                continue
            start = str(item.get("start", "")).strip()
            end = str(item.get("end", "")).strip()
            interval = str(item.get("interval", "")).strip() or "2"
            if start or end:
                rows.append(self._make_frame_dense_row(start, end, interval))
        if not rows and self.config.frame_sampler_dense_enabled:
            start = self.config.frame_sampler_dense_start.strip()
            end = self.config.frame_sampler_dense_end.strip()
            interval = str(self.config.frame_sampler_dense_interval_seconds).rstrip("0").rstrip(".") or "2"
            if start or end:
                rows.append(self._make_frame_dense_row(start, end, interval))
        return rows

    def _make_frame_dense_row(self, start: str = "", end: str = "", interval: str = "2") -> dict[str, tk.StringVar]:
        row = {
            "start": tk.StringVar(value=start),
            "end": tk.StringVar(value=end),
            "interval": tk.StringVar(value=interval),
        }
        for variable in row.values():
            variable.trace_add("write", lambda *_args: self._on_config_changed())
        return row

    def _metric(self, parent: tk.Widget, column: int, label: str, variable: tk.StringVar) -> None:
        metric_card(parent, column, label, variable, padx=(6, 0))

    def _frame_metric(self, parent: tk.Widget, column: int, label: str, variable: tk.StringVar) -> None:
        metric_card(
            parent,
            column,
            label,
            variable,
            value_font=("Segoe UI", 13, "bold"),
            padx=(8, 0),
        )

    def _option(
        self,
        parent: ttk.LabelFrame,
        row: int,
        text: str,
        variable: tk.BooleanVar,
        tooltip: str,
        column: int = 0,
    ) -> None:
        widget = option_checkbutton(parent, self.root, row, text, variable, tooltip, column=column)
        self.option_widgets.append(widget)

    def _transport_button(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], None],
        color: str,
    ) -> tk.Button:
        return create_transport_button(parent, text, command, color)

    def _number_field(
        self,
        parent: ttk.LabelFrame,
        row: int,
        column: int,
        text: str,
        variable: tk.IntVar,
        from_: int,
        to: int,
    ) -> None:
        self.option_widgets.append(create_number_field(parent, row, column, text, variable, from_, to))

    def _bind_config_vars(self) -> None:
        vars_to_track: list[tk.Variable] = [
            self.record_outside_var,
            self.samples_var,
            self.clicks_var,
            self.wheel_var,
            self.drag_var,
            self.sync_var,
            self.recording_status_banner_var,
            self.video_fps_var,
            self.sample_fps_var,
            self.click_duration_var,
            self.click_distance_var,
            self.drag_distance_var,
            self.calibration_tolerance_var,
            self.startup_countdown_var,
            self.session_name_var,
            self.frame_mode_var,
            self.frame_output_name_var,
            self.frame_start_var,
            self.frame_end_var,
            self.frame_interval_var,
            self.frame_cols_var,
            self.frame_rows_var,
            self.frame_thumb_width_var,
            self.frame_keyframe_max_var,
            self.frame_keyframe_time_dedupe_var,
            self.frame_keyframe_distance_dedupe_var,
            self.frame_quality_var,
            self.frame_quality_preset_var,
            self.frame_show_timestamp_var,
            self.frame_show_index_var,
            self.frame_draw_click_markers_var,
            self.frame_dense_enabled_var,
            self.frame_dense_start_var,
            self.frame_dense_end_var,
            self.frame_dense_interval_var,
            self.frame_crop_enabled_var,
            self.frame_crop_x_var,
            self.frame_crop_y_var,
            self.frame_crop_w_var,
            self.frame_crop_h_var,
        ]
        for variable in vars_to_track:
            variable.trace_add("write", lambda *_args: self._on_config_changed())
        for variable in (self.frame_crop_x_var, self.frame_crop_y_var, self.frame_crop_w_var, self.frame_crop_h_var):
            variable.trace_add("write", lambda *_args: self._on_frame_crop_values_changed())
        self.frame_crop_enabled_var.trace_add("write", lambda *_args: self._on_frame_crop_option_changed())
        self.frame_mode_var.trace_add("write", lambda *_args: self._refresh_frame_default_output_dir(force=True))
        self.frame_start_var.trace_add("write", lambda *_args: self._on_frame_time_range_changed())
        self.frame_end_var.trace_add("write", lambda *_args: self._on_frame_time_range_changed())
        self.frame_dense_enabled_var.trace_add("write", lambda *_args: self._refresh_frame_default_output_dir())
        self.frame_dense_start_var.trace_add("write", lambda *_args: self._refresh_frame_default_output_dir())
        self.frame_dense_end_var.trace_add("write", lambda *_args: self._refresh_frame_default_output_dir())

    def _play_action(self) -> None:
        if self.is_paused:
            self.resume_recording()
        else:
            self.start_recording()

    def _primary_record_action(self) -> None:
        self._play_action()

    def select_region(self) -> None:
        if self.is_recording or self.is_starting or self.is_stopping or self.is_paused or self.is_pausing or self.is_counting_down:
            return
        self.root.withdraw()
        try:
            region = RegionSelector(self.root).select()
        finally:
            self.root.deiconify()
        if region is None:
            self.status_var.set("区域选择已取消")
            self._refresh_readiness()
            return
        region = region.even_sized()
        if self.region_overlay is not None:
            self.region_overlay.destroy()
        self.region = region
        self.calibration_data = None
        self.region_overlay = RecordingRegionOverlay(self.root, region)
        self.region_var.set(f"x={region.screen_x} y={region.screen_y}  {region.width}x{region.height}")
        self.status_var.set("区域已选择")
        self.calibration_var.set("未检查 · 可录制")
        self._refresh_readiness()

    def clear_region(self, show_message: bool = True) -> None:
        if self.is_recording or self.is_starting or self.is_stopping or self.is_paused or self.is_pausing or self.is_counting_down:
            if show_message:
                messagebox.showinfo("不能取消区域", "当前录制状态下不能取消区域，请先结束录制。")
            return
        if self.region_overlay is not None:
            self.region_overlay.destroy()
            self.region_overlay = None
        self.region = None
        self.calibration_data = None
        self.region_var.set("未选择录制区域")
        self.calibration_var.set("未检查")
        self.status_var.set("区域已取消")
        self._set_recording_ui()
        self._refresh_readiness()

    def _on_escape(self, _event: tk.Event | None = None) -> str | None:
        if self.region is None:
            return None
        self.clear_region(show_message=False)
        return "break"

    def run_calibration(self) -> None:
        if self.is_recording or self.is_starting or self.is_stopping or self.is_paused or self.is_pausing or self.is_counting_down:
            return
        if self.region is None:
            messagebox.showwarning("需要选择区域", "请先选择录制区域，再进行坐标对应检查。")
            return
        self._sync_config_from_ui()
        self.status_var.set("检查中")
        result = run_click_calibration(
            self.root,
            self.region,
            self.config.calibration_click_tolerance_px,
            self.config.calibration_residual_warning_px,
        )
        self.calibration_data = result
        if result and result.get("completed"):
            warnings = result.get("warnings") or []
            warning_text = " · 警告" if warnings else ""
            self.calibration_var.set(
                self._compact_text(
                    f"完成 · 平均 {result.get('avg_residual_px', 0)}px · 最大 {result.get('max_residual_px', 0)}px{warning_text}",
                    54,
                )
            )
            self.status_var.set("检查完成")
        else:
            reasons = "；".join(result.get("failure_reasons", [])) if result else "未完成五点检查"
            self.calibration_var.set(self._compact_text(f"未通过 · {reasons}", 54))
            self.status_var.set("等待检查")
        self._refresh_readiness()

    def choose_output_root(self) -> None:
        if self.is_recording or self.is_starting or self.is_stopping or self.is_paused or self.is_pausing or self.is_counting_down:
            return
        directory = filedialog.askdirectory(initialdir=self.output_var.get() or str(self.base_dir))
        if directory:
            self.config.output_root = directory
            self.output_var.set(directory)
            self._save_config()
            self._refresh_environment()
            self._refresh_readiness()

    def _run_start_countdown(self, title: str, callback: Callable[[], None]) -> None:
        if self.is_counting_down:
            return
        seconds = self._safe_int(self.startup_countdown_var, 3, 0, 10)
        self.config.startup_countdown_seconds = seconds
        if seconds <= 0:
            callback()
            return
        if self.region is None:
            self._refresh_readiness()
            return

        self.is_counting_down = True
        self.status_var.set("倒计时")
        self._set_recording_ui(counting_down=True)
        if self.region_overlay is not None:
            self.region_overlay.set_mode("ready")

        window = tk.Toplevel(self.root)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        transparent_color = "#010203"
        window.configure(bg=transparent_color)
        try:
            window.attributes("-transparentcolor", transparent_color)
        except tk.TclError:
            window.attributes("-alpha", 0.82)
        width = min(max(220, self.region.width // 2), self.region.width)
        height = min(max(130, self.region.height // 4), self.region.height)
        x = self.region.screen_x + max(0, (self.region.width - width) // 2)
        y = self.region.screen_y + max(0, (self.region.height - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.lift()
        font_size = max(18, min(42, height // 3))

        canvas = tk.Canvas(
            window,
            bg=transparent_color,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)
        center_x = width // 2
        center_y = height // 2
        shadow_id = canvas.create_text(
            center_x + 2,
            center_y + 2,
            text="",
            fill="#000000",
            justify="center",
            font=("Segoe UI", font_size, "bold"),
        )
        text_id = canvas.create_text(
            center_x,
            center_y,
            text="",
            fill="#ffffff",
            justify="center",
            font=("Segoe UI", font_size, "bold"),
        )
        self.countdown_window = window

        def tick(remaining: int) -> None:
            if not self.is_counting_down:
                return
            if remaining <= 0:
                self.countdown_after_id = None
                self._destroy_countdown_window()
                self.is_counting_down = False
                callback()
                return
            text = f"{remaining}\n{title}"
            canvas.itemconfigure(shadow_id, text=text, font=("Segoe UI", font_size, "bold"))
            canvas.itemconfigure(text_id, text=text, font=("Segoe UI", font_size, "bold"))
            self.recording_banner_var.set(f"{title} · {remaining}")
            self.countdown_after_id = self.root.after(1000, lambda: tick(remaining - 1))

        tick(seconds)

    def _destroy_countdown_window(self) -> None:
        if self.countdown_after_id is not None:
            try:
                self.root.after_cancel(self.countdown_after_id)
            except tk.TclError:
                pass
            self.countdown_after_id = None
        if self.countdown_window is not None:
            try:
                if self.countdown_window.winfo_exists():
                    self.countdown_window.destroy()
            except tk.TclError:
                pass
            self.countdown_window = None

    def start_recording(self) -> None:
        if self.is_recording or self.is_starting or self.is_stopping or self.is_paused or self.is_counting_down:
            return
        self._sync_config_from_ui()
        self._save_config()
        if platform.system().lower() != "windows":
            messagebox.showerror("平台不支持", "当前版本仅支持 Windows 鼠标 hook 和 FFmpeg gdigrab。")
            return
        if self.region is None:
            self.status_var.set("缺少区域")
            self.readiness_var.set("需 选择区域")
            messagebox.showwarning("需要选择区域", "请先选择录制区域。")
            return
        normalized_region = self.region.even_sized()
        if normalized_region != self.region:
            self.region = normalized_region
            if self.region_overlay is not None:
                self.region_overlay.destroy()
            self.region_overlay = RecordingRegionOverlay(self.root, self.region)
            self.region_var.set(f"x={self.region.screen_x} y={self.region.screen_y}  {self.region.width}x{self.region.height}")
            self.calibration_data = None
            self.calibration_var.set("尺寸已调整 · 可录制")
            self.status_var.set("区域已调整")
            self._refresh_readiness()
            messagebox.showinfo("区域已调整", "录制区域宽高需要为偶数，已自动裁掉右侧/底部 1 像素。可以直接录制，或重新做一次坐标对应检查。")
        if not self.privacy_var.get():
            self.status_var.set("等待确认")
            self.readiness_var.set("需 确认")
            messagebox.showwarning("需要确认", "请先确认记录选项底部的本地录制提示。")
            return
        if not self._output_root_writable():
            self.status_var.set("输出不可写")
            self.readiness_var.set("需 可写输出")
            messagebox.showerror("输出目录不可写", "请选择一个可写的输出地址。")
            return

        recorder = FFmpegRecorder(self.config.ffmpeg_path)
        if not recorder.is_available():
            self.status_var.set("FFmpeg 不可用")
            self.readiness_var.set("需 FFmpeg")
            messagebox.showerror(
                "FFmpeg 不可用",
                "没有找到 FFmpeg。请检查 config.json 中的 ffmpeg_path。",
            )
            self._refresh_environment()
            self._refresh_readiness()
            return

        self._run_start_countdown("开始录制", self._start_recording_now)

    def _start_recording_now(self) -> None:
        if self.is_recording or self.is_starting or self.is_stopping or self.is_paused:
            return
        if self.region is None:
            self._set_recording_ui()
            self._refresh_readiness()
            return
        self.recorder = FFmpegRecorder(self.config.ffmpeg_path)
        if not self.recorder.is_available():
            self.status_var.set("FFmpeg 不可用")
            self.readiness_var.set("需 FFmpeg")
            self._set_recording_ui()
            self._refresh_environment()
            self._refresh_readiness()
            messagebox.showerror("FFmpeg 不可用", "没有找到 FFmpeg。请检查 config.json 中的 ffmpeg_path。")
            return

        session_id = self._build_session_id()
        self.current_session_name = self.config.session_name.strip()
        self.current_session_created_at = wall_time_iso()
        output_root = self.config.output_root_path(self.base_dir)
        self.storage = SessionStorage.create_unique(output_root, session_id)
        self.session_var.set(self._compact_path(self.storage.session_dir, 86))
        self.summary_var.set("录制中")
        self.segment_count_var.set("0")
        self.pause_count_var.set("0")
        self.asset_status_var.set("录制中")
        self.sync_markers = []
        self.segment_paths = []
        self.video_segments = []
        self.current_segment_path = self._next_segment_path()
        self.current_segment_record = None
        self.event_counter = 0
        self.sample_counter = 0
        self.pause_started_monotonic_ms = None
        self.pause_periods = []

        logger_start = monotonic_ms()
        self.timing = TimingContext(session_id=session_id, logger_start_monotonic_ms=logger_start)
        self.storage.write_json(self.storage.session_meta, self._build_meta())
        if self.calibration_data is not None:
            self.storage.write_json(self.storage.calibration, self.calibration_data)

        event_writer = JsonlWriter(self.storage.mouse_events, flush_every=1)
        sample_writer = JsonlWriter(self.storage.mouse_samples)
        self.logger = MouseActivityLogger(
            self.region,
            self.timing,
            self.config,
            event_writer,
            sample_writer,
            calibration_data=self.calibration_data,
            event_counter_start=self.event_counter,
            sample_counter_start=self.sample_counter,
        )

        self.is_starting = True
        self.status_var.set("启动中")
        self._set_recording_ui(starting=True)
        self.root.update_idletasks()
        threading.Thread(target=self._start_recording_worker, name="recording-start", daemon=True).start()

    def _start_recording_worker(self) -> None:
        try:
            assert self.logger is not None
            assert self.recorder is not None
            assert self.region is not None
            assert self.storage is not None
            assert self.timing is not None
            assert self.current_segment_path is not None
            self.logger.start()
            if self.timing.video_start_request_monotonic_ms is None:
                self.timing.video_start_request_monotonic_ms = monotonic_ms()
            segment_start = self.recorder.start(self.region, self.current_segment_path, self.config.video_fps, self.storage.ffmpeg_log)
            if self.timing.video_zero_monotonic_ms is None:
                self.timing.video_zero_monotonic_ms = segment_start
            if self.current_segment_path not in self.segment_paths:
                self.segment_paths.append(self.current_segment_path)
            self.current_segment_record = {
                "file": self.current_segment_path.name,
                "start_monotonic_ms": round(segment_start, 3),
                "start_video_ms": round(self.timing.t_video_ms(segment_start), 3),
                "end_monotonic_ms": None,
                "end_video_ms": None,
            }
            self.video_segments.append(self.current_segment_record)
            self.storage.write_json(self.storage.session_meta, self._build_meta())
            self.root.after(0, self._on_recording_started)
        except Exception as exc:
            self._cleanup_recording_resources()
            self.root.after(0, lambda error=exc: self._on_start_failed(error))

    def _on_recording_started(self) -> None:
        self.is_starting = False
        self.is_recording = True
        self.is_paused = False
        self.status_var.set("录制中")
        self._set_recording_ui(recording=True)
        self._refresh_runtime_stats()
        if self.region_overlay is not None:
            self.region_overlay.set_mode("recording")
        if self.config.show_sync_marker:
            self.root.after(500, self._emit_sync_marker)
        self._tick_elapsed()
        self._poll_recorder()

    def _on_start_failed(self, exc: Exception) -> None:
        self.is_starting = False
        self.is_recording = False
        self.is_stopping = False
        self.is_paused = False
        self.is_pausing = False
        self.is_counting_down = False
        self.recorder = None
        self.logger = None
        self._set_recording_ui()
        if self.region_overlay is not None:
            self.region_overlay.set_mode("ready")
        self.status_var.set("启动失败")
        self._refresh_readiness()
        self._show_error_report(
            "启动失败",
            "recording_start",
            exc,
            {
                "output_root": self.config.output_root_path(self.base_dir),
                "ffmpeg_path": self.config.ffmpeg_path,
                "region": self.region,
            },
        )

    def stop_recording(self) -> None:
        if self.is_stopping:
            return
        if not self.is_recording and self.logger is None and self.recorder is None:
            if not self.is_paused:
                return
        if not self.is_recording and not self.is_paused and self.logger is None and self.recorder is None:
            return
        self.is_recording = False
        self.is_paused = False
        self.is_stopping = True
        self.status_var.set("保存中")
        self._set_recording_ui(stopping=True)
        self.root.update_idletasks()
        threading.Thread(target=self._stop_recording_worker, name="recording-stop", daemon=True).start()

    def pause_recording(self) -> None:
        if not self.is_recording or self.is_pausing or self.is_stopping or self.is_counting_down:
            return
        self.is_recording = False
        self.is_pausing = True
        self.status_var.set("暂停中")
        self._set_recording_ui(pausing=True)
        self._refresh_runtime_stats()
        threading.Thread(target=self._pause_recording_worker, name="recording-pause", daemon=True).start()

    def _pause_recording_worker(self) -> None:
        error: Exception | None = None
        pause_started = monotonic_ms()
        try:
            if self.recorder is not None:
                self.recorder.stop()
            if self.logger is not None:
                self.logger.stop()
                self.event_counter = self.logger.event_counter
                self.sample_counter = self.logger.sample_counter
            self._mark_current_segment_end(pause_started)
        except Exception as exc:
            error = exc
        self.root.after(0, lambda: self._on_recording_paused(pause_started, error))

    def _on_recording_paused(self, pause_started: float, error: Exception | None) -> None:
        self.is_pausing = False
        self.recorder = None
        self.logger = None
        if error is not None:
            self.is_paused = False
            self._set_recording_ui()
            self._show_error_report(
                "暂停失败",
                "recording_pause",
                error,
                {"session_dir": self.storage.session_dir if self.storage is not None else None},
                warning=True,
            )
            return
        self.is_paused = True
        self.pause_started_monotonic_ms = pause_started
        self.status_var.set("已暂停")
        self._set_recording_ui(paused=True)
        self._refresh_runtime_stats()
        if self.region_overlay is not None:
            self.region_overlay.set_mode("ready")
        self._write_meta()

    def resume_recording(self) -> None:
        if not self.is_paused or self.is_starting or self.is_stopping or self.is_counting_down:
            return
        self._run_start_countdown("继续录制", self._resume_recording_now)

    def _resume_recording_now(self) -> None:
        if not self.is_paused or self.is_starting or self.is_stopping:
            return
        assert self.storage is not None
        assert self.region is not None
        assert self.timing is not None
        pause_end = monotonic_ms()
        if self.pause_started_monotonic_ms is not None:
            duration = pause_end - self.pause_started_monotonic_ms
            self.timing.paused_duration_ms += duration
            self.pause_periods.append(
                {
                    "start_monotonic_ms": round(self.pause_started_monotonic_ms, 3),
                    "end_monotonic_ms": round(pause_end, 3),
                    "duration_ms": round(duration, 3),
                }
            )
            self._refresh_runtime_stats()
        self.pause_started_monotonic_ms = None
        self.current_segment_path = self._next_segment_path()
        self.current_segment_record = None
        self.recorder = FFmpegRecorder(self.config.ffmpeg_path)
        event_writer = JsonlWriter(self.storage.mouse_events, flush_every=1)
        sample_writer = JsonlWriter(self.storage.mouse_samples)
        self.logger = MouseActivityLogger(
            self.region,
            self.timing,
            self.config,
            event_writer,
            sample_writer,
            calibration_data=self.calibration_data,
            event_counter_start=self.event_counter,
            sample_counter_start=self.sample_counter,
        )
        self.is_paused = False
        self.is_starting = True
        self.status_var.set("继续中")
        self._set_recording_ui(starting=True)
        threading.Thread(target=self._start_recording_worker, name="recording-resume", daemon=True).start()

    def _stop_recording_worker(self) -> None:
        summary = None
        error: Exception | None = None
        if self.timing is not None:
            self.timing.recording_stop_monotonic_ms = self.pause_started_monotonic_ms or monotonic_ms()
        try:
            if self.recorder is not None:
                self.recorder.stop()
            if self.logger is not None:
                self.logger.stop()
                self.event_counter = self.logger.event_counter
                self.sample_counter = self.logger.sample_counter
            self._mark_current_segment_end(self.timing.recording_stop_monotonic_ms or monotonic_ms())
            self._finalize_video_segments()
            if self.storage is not None:
                self.storage.write_json(self.storage.session_meta, self._build_meta())
                summary = generate_summary(self.storage)
        except Exception as exc:
            error = exc
        self.root.after(0, lambda: self._on_recording_stopped(summary, error))

    def _on_recording_stopped(self, summary: dict[str, Any] | None, error: Exception | None) -> None:
        if error is not None:
            self._show_error_report(
                "保存失败",
                "recording_stop",
                error,
                {"session_dir": self.storage.session_dir if self.storage is not None else None},
                warning=True,
            )
        self.is_stopping = False
        self.is_paused = False
        self.is_pausing = False
        self.is_counting_down = False
        self.pause_started_monotonic_ms = None
        self.logger = None
        self.recorder = None
        self._set_recording_ui()
        if self.region_overlay is not None:
            self.region_overlay.destroy()
            self.region_overlay = None
        self.region = None
        self.calibration_data = None
        self.region_var.set("未选择录制区域")
        self.calibration_var.set("未检查")
        self.elapsed_var.set("00:00.000")
        self._refresh_runtime_stats()
        self._refresh_asset_status()
        if summary:
            self.status_var.set("已完成")
            self.summary_var.set(
                f"事件 {summary['events_total']} · 采样 {summary['samples_total']} · "
                f"点击 {summary['clicks_total']} · 滚轮 {summary['wheel_events']} · 拖拽 {summary['drag_count']}"
            )
            if self.storage is not None:
                self._start_auto_behavior_report(self.storage.session_dir)
        else:
            self.status_var.set("已停止")
            self.summary_var.set("未生成摘要")
        self._refresh_readiness()

    def _start_auto_behavior_report(self, session_dir: Path) -> None:
        job = make_behavior_report_job(session_dir, ffmpeg_path=self.config.ffmpeg_path)
        self.auto_report_output_dir = job.output_dir
        self._set_asset_status_extra("图表 --")
        self._append_recording_summary_note("图表生成中")

        def worker() -> None:
            result = None
            error: Exception | None = None
            try:
                result = run_behavior_report_job(job)
            except Exception as exc:
                error = exc
            try:
                self.root.after(0, lambda: self._on_auto_behavior_report_done(job, result, error))
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="auto-behavior-report", daemon=True).start()

    def _on_auto_behavior_report_done(self, job: BehaviorReportJob, result: Any, error: Exception | None) -> None:
        current_session = self.storage.session_dir.resolve() if self.storage is not None else None
        if current_session != job.source_path:
            return
        if error is not None:
            report, _txt_path = self._create_error_report(
                "auto_report",
                error,
                {"source_path": job.source_path, "output_dir": job.output_dir},
            )
            self._set_asset_status_extra("图表 --")
            self._append_recording_summary_note(f"图表生成失败 {report.code}", 96)
            return
        if result is None:
            report, _txt_path = self._create_error_report(
                "auto_report",
                RuntimeError("报告服务未返回生成结果"),
                {"source_path": job.source_path, "output_dir": job.output_dir},
            )
            self._set_asset_status_extra("图表 --")
            self._append_recording_summary_note(f"图表生成失败 {report.code}", 96)
            return

        self.auto_report_output_dir = result.output_dir
        self._refresh_asset_status()
        self._set_asset_status_extra("图表 OK")
        self._append_recording_summary_note("图表已生成")

    def _append_recording_summary_note(self, note: str, max_chars: int = 88) -> None:
        current = self.summary_var.get().strip()
        if note != "图表生成中":
            current = self._remove_summary_note(current, "图表生成中")
        if note in current:
            return
        if not current or current in {"暂无摘要", "未生成摘要"}:
            next_text = note
        else:
            next_text = f"{current} · {note}"
        self.summary_var.set(self._compact_text(next_text, max_chars))

    @staticmethod
    def _remove_summary_note(text: str, note: str) -> str:
        for pattern in (f" · {note}", f"{note} · ", note):
            text = text.replace(pattern, "")
        return text.strip()

    def _set_asset_status_extra(self, extra: str) -> None:
        current = self.asset_status_var.get().strip()
        parts = [
            part.strip()
            for part in current.split("·")
            if part.strip() and not part.strip().startswith("图表")
        ]
        parts.append(extra)
        self.asset_status_var.set(" · ".join(parts))

    def _mark_current_segment_end(self, end_monotonic_ms: float) -> None:
        if self.current_segment_record is None or self.timing is None:
            return
        if self.current_segment_record.get("end_monotonic_ms") is not None:
            return
        self.current_segment_record["end_monotonic_ms"] = round(end_monotonic_ms, 3)
        self.current_segment_record["end_video_ms"] = round(self.timing.t_video_ms(end_monotonic_ms), 3)

    def _finalize_video_segments(self) -> None:
        if self.storage is None:
            return
        existing_segments = [path for path in self.segment_paths if path.exists() and path.stat().st_size > 0]
        if not existing_segments:
            return
        concat_mp4_segments(self.config.ffmpeg_path, existing_segments, self.storage.recording_mp4, self.storage.ffmpeg_log)

    def _refresh_runtime_stats(self) -> None:
        active_pause = 1 if self.is_paused or self.is_pausing else 0
        self.segment_count_var.set(str(len(self.video_segments)))
        self.pause_count_var.set(str(len(self.pause_periods) + active_pause))

    def _refresh_asset_status(self) -> None:
        if self.storage is None:
            self.asset_status_var.set("等待生成")
            return
        checks = [
            ("视频", self.storage.recording_mp4),
            ("事件", self.storage.mouse_events),
            ("采样", self.storage.mouse_samples),
            ("摘要", self.storage.mouse_summary_xlsx),
            ("分析", self.storage.mouse_analysis_xlsx),
            ("检查", self.storage.calibration),
        ]
        parts = []
        for label, path in checks:
            ok = path.exists() and path.stat().st_size > 0
            parts.append(f"{label} {'OK' if ok else '--'}")
        self.asset_status_var.set(" · ".join(parts))

    def _cleanup_recording_resources(self) -> None:
        try:
            if self.recorder is not None:
                self.recorder.stop()
        finally:
            try:
                if self.logger is not None:
                    self.logger.stop()
            except Exception:
                pass

    def _emit_sync_marker(self) -> None:
        if not self.is_recording or self.logger is None or self.region is None or self.timing is None:
            return
        marker_id = f"SYNC_{len(self.sync_markers) + 1:03d}"
        event = self.logger.emit_sync_marker(marker_id)
        show_sync_marker(self.root, self.region, marker_id)
        self.sync_markers.append(
            {
                "marker_id": marker_id,
                "t_monotonic_ms": event["t_monotonic_ms"],
                "expected_video_ms": event["t_video_ms"],
                "visible_duration_ms": 1200,
            }
        )
        self._write_meta()

    def _tick_elapsed(self) -> None:
        if self.is_recording and self.timing is not None:
            elapsed = self.timing.t_video_ms(monotonic_ms())
            minutes, remainder = divmod(int(elapsed), 60_000)
            seconds, millis = divmod(remainder, 1000)
            elapsed_text = f"{minutes:02d}:{seconds:02d}.{millis:03d}"
            self.elapsed_var.set(elapsed_text)
            marker_text = " · 同步" if self.config.show_sync_marker else ""
            self.recording_banner_var.set(f"录制中 · {elapsed_text}{marker_text}")
            self.root.after(120, self._tick_elapsed)

    def _poll_recorder(self) -> None:
        if not self.is_recording:
            return
        if self.recorder is not None and self.recorder.returncode() is not None:
            self.recording_banner_var.set("FFmpeg 停止 · 保存中")
            self.stop_recording()
            messagebox.showwarning("录制已停止", "FFmpeg 录制进程已退出，已保存当前 session。")
            return
        self.root.after(500, self._poll_recorder)

    def _build_meta(self) -> dict[str, Any]:
        assert self.region is not None
        assert self.timing is not None
        return {
            "schema_version": "1.0",
            "session_id": self.timing.session_id,
            "app_version": __version__,
            "platform": "windows",
            "created_at": self.current_session_created_at,
            "recording_region": self.region.to_dict(),
            "video": {
                "file": "recording.mp4",
                "fps": self.config.video_fps,
                "width": self.region.width,
                "height": self.region.height,
                "codec": "h264",
                "segments": self.video_segments,
            },
            "session_name": self.current_session_name,
            "config": {
                "sample_fps": self.config.sample_fps,
                "record_outside_region": self.config.record_outside_region,
                "record_mouse_samples": self.config.record_mouse_samples,
                "record_click_events": self.config.record_click_events,
                "record_wheel_events": self.config.record_wheel_events,
                "record_drag_events": self.config.record_drag_events,
                "show_sync_marker": self.config.show_sync_marker,
                "show_recording_status_banner": self.config.show_recording_status_banner,
                "startup_countdown_seconds": self.config.startup_countdown_seconds,
                "click_max_duration_ms": self.config.click_max_duration_ms,
                "click_max_distance_px": self.config.click_max_distance_px,
                "drag_min_distance_px": self.config.drag_min_distance_px,
                "double_click_window_ms": self.config.double_click_window_ms,
                "calibration_click_tolerance_px": self.config.calibration_click_tolerance_px,
                "calibration_residual_warning_px": self.config.calibration_residual_warning_px,
            },
            "calibration": self.calibration_data,
            "pause_periods": self.pause_periods,
            "timing": self.timing.timing_dict(),
            "sync_markers": self.sync_markers,
        }

    def _write_meta(self) -> None:
        if self.storage is not None:
            self.storage.write_json(self.storage.session_meta, self._build_meta())

    def _cleanup_after_failed_start(self) -> None:
        if self.recorder is not None:
            self.recorder.stop()
        if self.logger is not None:
            self.logger.stop()
        self.recorder = None
        self.logger = None
        self.is_recording = False
        self.is_starting = False
        self.is_stopping = False
        self.is_paused = False
        self.is_pausing = False
        self.is_counting_down = False
        self._set_recording_ui()
        if self.region_overlay is not None:
            self.region_overlay.set_mode("ready")
        self.status_var.set("启动失败")
        self._refresh_readiness()

    def open_output(self) -> None:
        path = self.storage.session_dir if self.storage is not None else self.config.output_root_path(self.base_dir)
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def open_video(self) -> None:
        if self.storage is None:
            messagebox.showinfo("没有视频", "当前还没有完成的 session。")
            return
        if not self.storage.recording_mp4.exists():
            messagebox.showinfo("没有视频", "当前 session 还没有生成 recording.mp4。")
            return
        os.startfile(self.storage.recording_mp4)

    def regenerate_outputs(self) -> None:
        if self.storage is None:
            messagebox.showinfo("没有 session", "当前还没有可重新生成的 session。")
            return
        if self.is_recording or self.is_starting or self.is_stopping or self.is_paused or self.is_pausing or self.is_counting_down:
            messagebox.showinfo("正在录制", "录制过程中不能重新生成表格。")
            return
        try:
            summary = generate_summary(self.storage)
        except Exception as exc:
            self._show_error_report(
                "生成失败",
                "summary_regenerate",
                exc,
                {"session_dir": self.storage.session_dir},
            )
            return
        self.summary_var.set(
            f"事件 {summary['events_total']} · 采样 {summary['samples_total']} · "
            f"点击 {summary['clicks_total']} · 滚轮 {summary['wheel_events']} · 拖拽 {summary['drag_count']}"
        )
        self._refresh_asset_status()
        messagebox.showinfo("已生成", "mouse_summary.json、mouse_summary.xlsx 和 mouse_analysis.xlsx 已重新生成。")

    def choose_frame_video(self) -> None:
        initial_dir = self.storage.session_dir if self.storage is not None else self.config.output_root_path(self.base_dir)
        path = filedialog.askopenfilename(
            title="选择视频",
            initialdir=initial_dir,
            filetypes=[
                ("视频文件", "*.mp4 *.mov *.mkv *.avi"),
                ("MP4", "*.mp4"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        self._set_frame_video(Path(path))

    def choose_frame_output(self) -> None:
        initial_dir = self.frame_output_dir or Path(self.frame_output_var.get() or self.base_dir)
        directory = filedialog.askdirectory(title="选择输出目录", initialdir=initial_dir)
        if not directory:
            return
        self.frame_output_dir = Path(directory).resolve()
        self.frame_output_is_default = False
        self.frame_output_var.set(str(self.frame_output_dir))
        self._sync_frame_config_from_ui()
        self._save_config()

    def _set_frame_video(self, path: Path) -> None:
        path = path.resolve()
        self.frame_source_path = path
        self.frame_video_info = None
        self.frame_output_is_default = True
        self.frame_video_var.set(str(path))
        self.frame_status_var.set("读取视频信息中...")
        self.frame_progress_var.set("")
        self._refresh_frame_default_output_dir(force=True)
        self.frame_click_events_path = self._guess_frame_click_events_path(path)
        self.frame_click_events_var.set(str(self.frame_click_events_path or ""))
        if hasattr(self, "frame_open_button"):
            self.frame_open_button.configure(state="disabled")
        self._cancel_frame_crop_preview_reload()
        self._set_frame_crop_preview_seconds(0.0, reload=False)
        self._clear_frame_crop_preview()

        def worker() -> None:
            info = None
            error: Exception | None = None
            try:
                info = probe_video(path, self.config.ffmpeg_path)
            except Exception as exc:
                error = exc
            self.root.after(0, lambda: self._on_frame_probe_done(info, error))

        threading.Thread(target=worker, name="frame-probe", daemon=True).start()

    def _on_frame_probe_done(self, info: VideoInfo | None, error: Exception | None) -> None:
        if error is not None:
            self.frame_video_info = None
            self.frame_duration_var.set("--")
            self.frame_resolution_var.set("--")
            self._set_frame_crop_preview_seconds(0.0, reload=False)
            self.sync_frame_crop_preview_controls()
            self.frame_status_var.set(f"读取失败：{error}")
            self._show_error_report(
                "读取视频失败",
                "frame_probe",
                error,
                {"video_path": self.frame_source_path, "ffmpeg_path": self.config.ffmpeg_path},
            )
            return
        if info is None:
            return
        self.frame_video_info = info
        self.frame_duration_var.set(format_timecode(info.duration_seconds))
        self.frame_resolution_var.set(f"{info.width}x{info.height}")
        self._set_frame_crop_preview_seconds(parse_timecode(self.frame_start_var.get()) or 0.0, reload=False)
        self.sync_frame_crop_preview_controls()
        self._refresh_frame_default_output_dir()
        self.frame_status_var.set("视频已读取，可调整参数后预估或生成。")
        self.load_frame_crop_preview(show_message=False)
        self.estimate_frame_sampling(show_message=False)

    def _on_frame_time_range_changed(self) -> None:
        self._refresh_frame_default_output_dir()

    def _refresh_frame_default_output_dir(self, *, force: bool = False) -> None:
        video_path = self.frame_source_path
        if video_path is None:
            return
        current_text = self.frame_output_var.get().strip()
        if not force and current_text and not self.frame_output_is_default:
            return
        if not force and current_text and self.frame_default_output_dir is not None:
            try:
                current_path = Path(current_text).resolve()
            except OSError:
                self.frame_output_is_default = False
                return
            if current_path != self.frame_default_output_dir.resolve():
                self.frame_output_is_default = False
                return
        start, end = self._frame_output_range_seconds()
        crop = self._frame_crop_region_from_ui()
        if self._frame_is_click_keyframe_mode():
            mode = "click"
        elif self.frame_dense_enabled_var.get():
            mode = "dense"
        else:
            mode = "interval"
        output_dir = default_output_dir(
            video_path,
            video_path.parent / FRAME_EXPORT_DIR_NAME,
            start_seconds=start,
            end_seconds=end,
            mode=mode,
            crop=crop,
        )
        self.frame_default_output_dir = output_dir
        self.frame_output_dir = output_dir
        self.frame_output_is_default = True
        self.frame_output_var.set(str(output_dir))

    def _frame_output_range_seconds(self) -> tuple[float, float | None]:
        try:
            start = parse_timecode(self.frame_start_var.get()) or 0.0
        except ValueError:
            start = 0.0
        try:
            end = parse_timecode(self.frame_end_var.get())
        except ValueError:
            end = None
        if end is None and self.frame_video_info is not None:
            end = self.frame_video_info.duration_seconds
        return start, end

    def _frame_is_click_keyframe_mode(self) -> bool:
        return self.frame_mode_var.get().strip() == "点击关键帧"

    def _guess_frame_click_events_path(self, video_path: Path) -> Path | None:
        candidates = [
            video_path.with_name("mouse_events.jsonl"),
            video_path.parent / "mouse_events.jsonl",
            video_path.parent.parent / "mouse_events.jsonl",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        if self.storage is not None and self.storage.mouse_events.exists():
            return self.storage.mouse_events.resolve()
        return self.frame_click_events_path if self.frame_click_events_path and self.frame_click_events_path.exists() else None

    def add_frame_dense_range(self, start: str = "", end: str = "", interval: str = "2") -> None:
        self.frame_dense_ranges.append(self._make_frame_dense_row(start, end, interval))
        self.frame_dense_enabled_var.set(bool(self.frame_dense_ranges))
        self.render_frame_dense_rows()
        self._on_config_changed()

    def remove_frame_dense_range(self, index: int) -> None:
        if 0 <= index < len(self.frame_dense_ranges):
            del self.frame_dense_ranges[index]
        self.frame_dense_enabled_var.set(bool(self.frame_dense_ranges))
        self.render_frame_dense_rows()
        self._on_config_changed()

    def render_frame_dense_rows(self) -> None:
        container = self.frame_dense_rows_container
        if container is None:
            return
        for child in container.winfo_children():
            child.destroy()
        if not self.frame_dense_ranges:
            tk.Label(
                container,
                text="未添加关键段",
                bg=COLORS["panel_bg"],
                fg=COLORS["muted"],
                anchor="w",
                font=("Segoe UI", 9),
            ).grid(row=0, column=0, sticky="ew", pady=(2, 0))
            return

        for row_index, row_data in enumerate(self.frame_dense_ranges, start=1):
            card = tk.Frame(
                container,
                bg=COLORS["panel_row"],
                highlightbackground=COLORS["border_soft"],
                highlightthickness=1,
            )
            card.grid(row=row_index - 1, column=0, sticky="ew", pady=(0, 8))
            card.columnconfigure(1, weight=1)
            card.columnconfigure(3, weight=0)

            tk.Label(
                card,
                text=f"关键段 {row_index}",
                bg=COLORS["panel_row"],
                fg=COLORS["text_secondary"],
                anchor="w",
                font=("Segoe UI", 9, "bold"),
            ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=(10, 8), pady=(8, 2))
            ttk.Button(
                card,
                text="删",
                command=lambda index=row_index - 1: self.remove_frame_dense_range(index),
                width=4,
            ).grid(row=0, column=3, sticky="ne", padx=(0, 8), pady=(6, 0))

            tk.Label(
                card,
                text="开始",
                bg=COLORS["panel_row"],
                fg=COLORS["muted"],
                anchor="w",
                font=("Segoe UI", 9),
                width=5,
            ).grid(row=1, column=0, sticky="w", padx=(10, 6), pady=3)
            create_timecode_inputs(card, row_data["start"], empty_as_blank=True).grid(
                row=1, column=1, sticky="w", padx=(0, 8), pady=3
            )

            tk.Label(
                card,
                text="间隔",
                bg=COLORS["panel_row"],
                fg=COLORS["muted"],
                anchor="w",
                font=("Segoe UI", 9),
                width=5,
            ).grid(row=1, column=2, sticky="w", padx=(0, 6), pady=3)
            ttk.Entry(card, textvariable=row_data["interval"], width=7, justify="center").grid(
                row=1, column=3, sticky="e", padx=(0, 8), pady=3
            )

            tk.Label(
                card,
                text="结束",
                bg=COLORS["panel_row"],
                fg=COLORS["muted"],
                anchor="w",
                font=("Segoe UI", 9),
                width=5,
            ).grid(row=2, column=0, sticky="w", padx=(10, 6), pady=(3, 8))
            create_timecode_inputs(card, row_data["end"], empty_as_blank=True).grid(
                row=2, column=1, sticky="w", padx=(0, 8), pady=(3, 8)
            )

    def sync_frame_crop_preview_controls(self) -> None:
        duration = self._frame_crop_preview_duration()
        enabled = duration > 0
        if self.frame_crop_time_scale is not None:
            self.frame_crop_time_scale.configure(from_=0.0, to=max(1.0, duration), state="normal" if enabled else "disabled")
        for button in self.frame_crop_preview_buttons:
            button.configure(state="normal" if enabled else "disabled")
        self._set_frame_crop_preview_seconds(self.frame_crop_preview_seconds_var.get(), reload=False)

    def set_frame_crop_preview_fraction(self, fraction: float) -> None:
        duration = self._frame_crop_preview_duration()
        if duration <= 0:
            return
        fraction = max(0.0, min(1.0, float(fraction)))
        self._cancel_frame_crop_preview_reload()
        self._set_frame_crop_preview_seconds(duration * fraction, reload=True)

    def on_frame_crop_preview_scale(self, value: str) -> None:
        if self.frame_crop_preview_controls_updating:
            return
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            seconds = 0.0
        self._set_frame_crop_preview_seconds(seconds, reload=False)
        self._schedule_frame_crop_preview_reload()

    def _frame_crop_preview_duration(self) -> float:
        if self.frame_video_info is None:
            return 0.0
        return max(0.0, float(self.frame_video_info.duration_seconds))

    def _clamp_frame_crop_preview_seconds(self, seconds: float) -> float:
        duration = self._frame_crop_preview_duration()
        if duration <= 0:
            return max(0.0, float(seconds))
        return max(0.0, min(duration, float(seconds)))

    def _set_frame_crop_preview_seconds(self, seconds: float, *, reload: bool) -> None:
        seconds = self._clamp_frame_crop_preview_seconds(seconds)
        self.frame_crop_preview_controls_updating = True
        try:
            self.frame_crop_preview_seconds_var.set(seconds)
        finally:
            self.frame_crop_preview_controls_updating = False
        self._update_frame_crop_preview_time_label(seconds)
        if reload:
            self.load_frame_crop_preview(show_message=False)

    def _update_frame_crop_preview_time_label(self, seconds: float | None = None) -> None:
        if seconds is None:
            seconds = self._clamp_frame_crop_preview_seconds(self.frame_crop_preview_seconds_var.get())
        duration = self._frame_crop_preview_duration()
        if duration <= 0:
            self.frame_crop_preview_time_var.set("00:00:00 / --")
            return
        self.frame_crop_preview_time_var.set(f"{format_timecode(seconds)} / {format_timecode(duration)}")

    def _schedule_frame_crop_preview_reload(self) -> None:
        if self.frame_source_path is None:
            return
        self._cancel_frame_crop_preview_reload()
        self.frame_crop_preview_after_id = self.root.after(300, self._load_scheduled_frame_crop_preview)

    def _load_scheduled_frame_crop_preview(self) -> None:
        self.frame_crop_preview_after_id = None
        self.load_frame_crop_preview(show_message=False)

    def _cancel_frame_crop_preview_reload(self) -> None:
        if self.frame_crop_preview_after_id is None:
            return
        try:
            self.root.after_cancel(self.frame_crop_preview_after_id)
        except tk.TclError:
            pass
        self.frame_crop_preview_after_id = None

    def bind_frame_crop_canvas(self) -> None:
        canvas = self.frame_crop_canvas
        if canvas is None:
            return
        canvas.bind("<ButtonPress-1>", self._on_frame_crop_press)
        canvas.bind("<B1-Motion>", self._on_frame_crop_drag)
        canvas.bind("<ButtonRelease-1>", self._on_frame_crop_release)
        canvas.bind("<MouseWheel>", self._on_frame_crop_mousewheel)
        canvas.bind("<Double-Button-1>", self._reset_frame_crop_view_zoom)
        canvas.bind("<Configure>", lambda _event: self._render_frame_crop_preview())
        self._clear_frame_crop_preview()

    def bind_frame_crop_zoom_canvas(self) -> None:
        canvas = self.frame_crop_zoom_canvas
        if canvas is None:
            return
        canvas.bind("<Configure>", lambda _event: self._render_frame_crop_zoom_preview())
        self._clear_frame_crop_zoom_preview()

    def load_frame_crop_preview(self, show_message: bool = True) -> None:
        video_path = self.frame_source_path
        if video_path is None:
            raw_path = self.frame_video_var.get().strip()
            if raw_path and raw_path != "未选择":
                video_path = Path(raw_path)
        if video_path is None or not video_path.exists():
            if show_message:
                messagebox.showinfo("需要选择视频", "请先选择一个视频。")
            return
        seconds = self._clamp_frame_crop_preview_seconds(self.frame_crop_preview_seconds_var.get())
        self._set_frame_crop_preview_seconds(seconds, reload=False)
        self.frame_status_var.set("读取裁剪预览中...")

        def worker() -> None:
            image = None
            error: Exception | None = None
            try:
                image = extract_preview_frame(video_path, self.config.ffmpeg_path, seconds)
            except Exception as exc:
                error = exc
            self.root.after(0, lambda: self._on_frame_crop_preview_done(image, error, show_message))

        threading.Thread(target=worker, name="frame-crop-preview", daemon=True).start()

    def _on_frame_crop_preview_done(self, image: Image.Image | None, error: Exception | None, show_message: bool = True) -> None:
        if error is not None:
            self.frame_status_var.set(f"裁剪预览读取失败：{error}")
            if show_message:
                self._show_error_report(
                    "裁剪预览失败",
                    "frame_preview",
                    error,
                    {
                        "video_path": self.frame_source_path,
                        "preview_seconds": self.frame_crop_preview_seconds_var.get(),
                        "ffmpeg_path": self.config.ffmpeg_path,
                    },
                )
            return
        if image is None:
            return
        if self.frame_crop_preview_original is not None:
            self.frame_crop_preview_original.close()
        self.frame_crop_preview_original = image
        self.frame_crop_view_zoom = 1.0
        self.frame_status_var.set("裁剪预览已读取；拖拽框选区域，不框选则默认全屏。")
        self._render_frame_crop_preview()

    def reset_frame_crop(self) -> None:
        self.frame_crop_value_trace_updating = True
        try:
            self.frame_crop_enabled_var.set(False)
            self.frame_crop_x_var.set("0")
            self.frame_crop_y_var.set("0")
            self.frame_crop_w_var.set("")
            self.frame_crop_h_var.set("")
        finally:
            self.frame_crop_value_trace_updating = False
        self._render_frame_crop_preview()
        self._on_config_changed()

    def _on_frame_crop_values_changed(self) -> None:
        if self.frame_crop_value_trace_updating:
            return
        image = self.frame_crop_preview_original
        max_width = image.width if image is not None else 100000
        max_height = image.height if image is not None else 100000
        crop_width = self._safe_int_string(self.frame_crop_w_var, 0, 0, max_width)
        crop_height = self._safe_int_string(self.frame_crop_h_var, 0, 0, max_height)
        if crop_width > 0 and crop_height > 0 and not self.frame_crop_enabled_var.get():
            self.frame_crop_value_trace_updating = True
            try:
                self.frame_crop_enabled_var.set(True)
            finally:
                self.frame_crop_value_trace_updating = False
        self._on_frame_crop_option_changed()

    def _on_frame_crop_option_changed(self) -> None:
        self._render_frame_crop_preview()
        self._refresh_frame_default_output_dir()

    def _clear_frame_crop_preview(self) -> None:
        if self.frame_crop_preview_original is not None:
            self.frame_crop_preview_original.close()
        self.frame_crop_preview_original = None
        self.frame_crop_preview_photo = None
        self.frame_crop_zoom_photo = None
        self.frame_crop_view_zoom = 1.0
        self.frame_crop_drag_start = None
        self.frame_crop_rect_id = None
        canvas = self.frame_crop_canvas
        if canvas is not None:
            self._draw_crop_canvas_message(canvas, "选择视频后自动预览首帧")
        self._clear_frame_crop_zoom_preview()

    def _clear_frame_crop_zoom_preview(self) -> None:
        self.frame_crop_zoom_photo = None
        canvas = self.frame_crop_zoom_canvas
        if canvas is not None:
            self._draw_crop_canvas_message(canvas, "框选后显示裁剪预览")

    def _draw_crop_canvas_message(self, canvas: tk.Canvas, text: str) -> None:
        canvas.delete("all")
        width = max(1, canvas.winfo_width() or int(canvas.cget("width")))
        height = max(1, canvas.winfo_height() or int(canvas.cget("height")))
        canvas.create_text(width // 2, height // 2, text=text, fill="#dfe7ec", font=("Segoe UI", 10))

    def _render_frame_crop_preview(self) -> None:
        canvas = self.frame_crop_canvas
        image = self.frame_crop_preview_original
        if canvas is None:
            return
        if image is None:
            self._clear_frame_crop_preview()
            return

        canvas_width = max(1, canvas.winfo_width() or int(canvas.cget("width")))
        canvas_height = max(1, canvas.winfo_height() or int(canvas.cget("height")))
        fit_scale = min(canvas_width / image.width, canvas_height / image.height)
        scale = fit_scale * self.frame_crop_view_zoom
        display_width = max(1, round(image.width * scale))
        display_height = max(1, round(image.height * scale))
        if self.frame_crop_view_zoom <= 1.001:
            offset_x = (canvas_width - display_width) // 2
            offset_y = (canvas_height - display_height) // 2
        else:
            offset_x, offset_y = self._clamp_frame_crop_view_offset(
                self.frame_crop_preview_offset[0],
                self.frame_crop_preview_offset[1],
                display_width,
                display_height,
                canvas_width,
                canvas_height,
            )
        preview = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self.frame_crop_preview_photo = ImageTk.PhotoImage(preview)
        self.frame_crop_preview_scale = scale
        self.frame_crop_preview_offset = (offset_x, offset_y)

        canvas.delete("all")
        canvas.create_image(offset_x, offset_y, image=self.frame_crop_preview_photo, anchor="nw")
        self._draw_frame_crop_rect_from_vars()
        self._render_frame_crop_zoom_preview()

    def _on_frame_crop_mousewheel(self, event: tk.Event) -> str:
        image = self.frame_crop_preview_original
        canvas = self.frame_crop_canvas
        if image is None or canvas is None:
            return "break"
        old_scale = self.frame_crop_preview_scale
        if old_scale <= 0:
            return "break"
        offset_x, offset_y = self.frame_crop_preview_offset
        focus_x = max(0.0, min(float(image.width), (float(event.x) - offset_x) / old_scale))
        focus_y = max(0.0, min(float(image.height), (float(event.y) - offset_y) / old_scale))
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        new_zoom = max(1.0, min(6.0, self.frame_crop_view_zoom * factor))
        if abs(new_zoom - self.frame_crop_view_zoom) < 0.001:
            return "break"
        self.frame_crop_view_zoom = new_zoom

        canvas_width = max(1, canvas.winfo_width() or int(canvas.cget("width")))
        canvas_height = max(1, canvas.winfo_height() or int(canvas.cget("height")))
        new_scale = min(canvas_width / image.width, canvas_height / image.height) * self.frame_crop_view_zoom
        display_width = max(1, round(image.width * new_scale))
        display_height = max(1, round(image.height * new_scale))
        target_offset_x = round(float(event.x) - focus_x * new_scale)
        target_offset_y = round(float(event.y) - focus_y * new_scale)
        self.frame_crop_preview_offset = self._clamp_frame_crop_view_offset(
            target_offset_x,
            target_offset_y,
            display_width,
            display_height,
            canvas_width,
            canvas_height,
        )
        self._render_frame_crop_preview()
        return "break"

    def _reset_frame_crop_view_zoom(self, _event: tk.Event | None = None) -> str:
        self.frame_crop_view_zoom = 1.0
        self._render_frame_crop_preview()
        return "break"

    def _clamp_frame_crop_view_offset(
        self,
        offset_x: int,
        offset_y: int,
        display_width: int,
        display_height: int,
        canvas_width: int,
        canvas_height: int,
    ) -> tuple[int, int]:
        if display_width <= canvas_width:
            clamped_x = (canvas_width - display_width) // 2
        else:
            clamped_x = max(canvas_width - display_width, min(0, offset_x))
        if display_height <= canvas_height:
            clamped_y = (canvas_height - display_height) // 2
        else:
            clamped_y = max(canvas_height - display_height, min(0, offset_y))
        return clamped_x, clamped_y

    def _render_frame_crop_zoom_preview(self) -> None:
        canvas = self.frame_crop_zoom_canvas
        image = self.frame_crop_preview_original
        if canvas is None:
            return
        if image is None:
            self._clear_frame_crop_zoom_preview()
            return
        bounds = self._frame_crop_bounds_from_vars()
        if bounds is None:
            self.frame_crop_zoom_photo = None
            self._draw_crop_canvas_message(canvas, "框选后显示裁剪预览")
            return

        crop = image.crop(bounds)
        canvas_width = max(1, canvas.winfo_width() or int(canvas.cget("width")))
        canvas_height = max(1, canvas.winfo_height() or int(canvas.cget("height")))
        crop_width = max(1, crop.width)
        crop_height = max(1, crop.height)
        scale = min(canvas_width / crop_width, canvas_height / crop_height)
        display_width = max(1, round(crop_width * scale))
        display_height = max(1, round(crop_height * scale))
        offset_x = max(0, (canvas_width - display_width) // 2)
        offset_y = max(0, (canvas_height - display_height) // 2)
        preview = crop.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self.frame_crop_zoom_photo = ImageTk.PhotoImage(preview)
        canvas.delete("all")
        canvas.create_image(offset_x, offset_y, image=self.frame_crop_zoom_photo, anchor="nw")

    def _frame_crop_bounds_from_vars(self) -> tuple[int, int, int, int] | None:
        image = self.frame_crop_preview_original
        if image is None or not self.frame_crop_enabled_var.get():
            return None
        width = self._safe_int_string(self.frame_crop_w_var, 0, 0, image.width)
        height = self._safe_int_string(self.frame_crop_h_var, 0, 0, image.height)
        if width <= 0 or height <= 0:
            return None
        x = self._safe_int_string(self.frame_crop_x_var, 0, 0, image.width - 1)
        y = self._safe_int_string(self.frame_crop_y_var, 0, 0, image.height - 1)
        right = max(x + 1, min(image.width, x + width))
        bottom = max(y + 1, min(image.height, y + height))
        return x, y, right, bottom

    def _draw_frame_crop_rect_from_vars(self) -> None:
        canvas = self.frame_crop_canvas
        image = self.frame_crop_preview_original
        if canvas is None or image is None:
            return
        bounds = self._frame_crop_bounds_from_vars()
        if bounds is None:
            return
        x, y, right, bottom = bounds
        scale = self.frame_crop_preview_scale
        offset_x, offset_y = self.frame_crop_preview_offset
        x1 = offset_x + round(x * scale)
        y1 = offset_y + round(y * scale)
        x2 = offset_x + round(right * scale)
        y2 = offset_y + round(bottom * scale)
        self.frame_crop_rect_id = canvas.create_rectangle(x1, y1, x2, y2, outline="#ffd166", width=2)

    def _on_frame_crop_press(self, event: tk.Event) -> str | None:
        if self.frame_crop_preview_original is None:
            return "break"
        self.frame_crop_drag_start = self._clamp_frame_crop_canvas_point(int(event.x), int(event.y))
        canvas = self.frame_crop_canvas
        if canvas is not None:
            if self.frame_crop_rect_id is not None:
                canvas.delete(self.frame_crop_rect_id)
            x, y = self.frame_crop_drag_start
            self.frame_crop_rect_id = canvas.create_rectangle(x, y, x, y, outline="#ffd166", width=2)
        return "break"

    def _on_frame_crop_drag(self, event: tk.Event) -> str | None:
        if self.frame_crop_drag_start is None or self.frame_crop_rect_id is None or self.frame_crop_canvas is None:
            return "break"
        x1, y1 = self.frame_crop_drag_start
        x2, y2 = self._clamp_frame_crop_canvas_point(int(event.x), int(event.y))
        self.frame_crop_canvas.coords(self.frame_crop_rect_id, x1, y1, x2, y2)
        return "break"

    def _on_frame_crop_release(self, event: tk.Event) -> str | None:
        image = self.frame_crop_preview_original
        if image is None or self.frame_crop_drag_start is None:
            return "break"
        x1, y1 = self.frame_crop_drag_start
        x2, y2 = self._clamp_frame_crop_canvas_point(int(event.x), int(event.y))
        self.frame_crop_drag_start = None
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        if right - left < 3 or bottom - top < 3:
            self._render_frame_crop_preview()
            return "break"
        offset_x, offset_y = self.frame_crop_preview_offset
        scale = self.frame_crop_preview_scale
        crop_x = max(0, min(image.width - 1, round((left - offset_x) / scale)))
        crop_y = max(0, min(image.height - 1, round((top - offset_y) / scale)))
        crop_right = max(crop_x + 1, min(image.width, round((right - offset_x) / scale)))
        crop_bottom = max(crop_y + 1, min(image.height, round((bottom - offset_y) / scale)))
        self.frame_crop_enabled_var.set(True)
        self.frame_crop_x_var.set(str(crop_x))
        self.frame_crop_y_var.set(str(crop_y))
        self.frame_crop_w_var.set(str(crop_right - crop_x))
        self.frame_crop_h_var.set(str(crop_bottom - crop_y))
        self._render_frame_crop_preview()
        self._on_config_changed()
        return "break"

    def _clamp_frame_crop_canvas_point(self, x: int, y: int) -> tuple[int, int]:
        image = self.frame_crop_preview_original
        if image is None:
            return x, y
        scale = self.frame_crop_preview_scale
        offset_x, offset_y = self.frame_crop_preview_offset
        min_x = offset_x
        min_y = offset_y
        max_x = offset_x + round(image.width * scale)
        max_y = offset_y + round(image.height * scale)
        return max(min_x, min(max_x, x)), max(min_y, min(max_y, y))

    def estimate_frame_sampling(self, show_message: bool = True) -> None:
        try:
            info = self.frame_video_info or probe_video(self._frame_video_path(), self.config.ffmpeg_path)
            self.frame_video_info = info
            if self._frame_is_click_keyframe_mode():
                config = self._build_click_keyframe_config()
                estimate = estimate_click_keyframe_sampling(config)
                self.frame_duration_var.set(format_timecode(info.duration_seconds))
                self.frame_resolution_var.set(f"{info.width}x{info.height}")
                self.frame_count_var.set(str(estimate.events_kept))
                self.frame_sheet_count_var.set(str(estimate.sheet_count))
                self.frame_eta_var.set(f"约 {estimate.estimated_processing_seconds:.0f} 秒")
                self.frame_status_var.set(f"识别点击事件 {estimate.events_total} 个，智能去重预估保留 {estimate.events_kept} 帧。")
                self._sync_frame_config_from_ui()
                self._save_config()
                return
            config = self._build_frame_sampler_config()
            estimate = estimate_sampling(config, info)
        except Exception as exc:
            self.frame_status_var.set(f"预估失败：{exc}")
            if show_message:
                self._show_error_report(
                    "预估失败",
                    "frame_estimate",
                    exc,
                    {
                        "video_path": self.frame_source_path,
                        "mode": self.frame_mode_var.get(),
                        "start": self.frame_start_var.get(),
                        "end": self.frame_end_var.get(),
                        "output_dir": self.frame_output_var.get(),
                    },
                )
            return
        self.frame_duration_var.set(format_timecode(info.duration_seconds))
        self.frame_resolution_var.set(f"{info.width}x{info.height}")
        self.frame_count_var.set(str(estimate.frame_count))
        self.frame_sheet_count_var.set(str(estimate.sheet_count))
        self.frame_eta_var.set(f"约 {estimate.estimated_processing_seconds:.0f} 秒")
        self.frame_status_var.set(
            f"预计抽帧 {estimate.frame_count} 张，生成 {estimate.sheet_count} 张合成图；"
            f"范围 {format_timecode(estimate.effective_start_seconds)} - {format_timecode(estimate.effective_end_seconds)}。"
        )
        self._sync_frame_config_from_ui()
        self._save_config()

    def run_frame_sampling(self) -> None:
        if self.frame_is_running:
            return
        try:
            if self.frame_output_is_default:
                self._refresh_frame_default_output_dir(force=True)
            info = self.frame_video_info or probe_video(self._frame_video_path(), self.config.ffmpeg_path)
            if self._frame_is_click_keyframe_mode():
                config = self._build_click_keyframe_config()
                click_estimate = estimate_click_keyframe_sampling(config)
                interval_estimate = None
            else:
                config = self._build_frame_sampler_config()
                interval_estimate = estimate_sampling(config, info)
                click_estimate = None
        except Exception as exc:
            self._show_error_report(
                "无法开始",
                "frame_estimate",
                exc,
                {
                    "video_path": self.frame_source_path,
                    "mode": self.frame_mode_var.get(),
                    "output_dir": self.frame_output_var.get(),
                },
            )
            return
        self.frame_video_info = info
        self._set_frame_running(True)
        if interval_estimate is not None:
            self.frame_count_var.set(str(interval_estimate.frame_count))
            self.frame_sheet_count_var.set(str(interval_estimate.sheet_count))
            self.frame_eta_var.set(f"约 {interval_estimate.estimated_processing_seconds:.0f} 秒")
        else:
            assert click_estimate is not None
            self.frame_count_var.set(str(click_estimate.events_kept))
            self.frame_sheet_count_var.set(str(click_estimate.sheet_count))
            self.frame_eta_var.set(f"约 {click_estimate.estimated_processing_seconds:.0f} 秒")

        def progress(done: int, total: int, message: str) -> None:
            try:
                self.root.after(0, lambda: self._update_frame_progress(done, total, message))
            except tk.TclError:
                pass

        def worker() -> None:
            result = None
            error: Exception | None = None
            try:
                result = run_frame_export(config, self.config.ffmpeg_path, progress)
            except Exception as exc:
                error = exc
            try:
                self.root.after(0, lambda: self._on_frame_sampling_done(result, error))
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="frame-sampler", daemon=True).start()

    def _set_frame_running(self, running: bool) -> None:
        self.frame_is_running = running
        state = "disabled" if running else "normal"
        self.frame_estimate_button.configure(state=state)
        self.frame_generate_button.configure(state=state)
        if running:
            self.frame_progress_started_ms = monotonic_ms()
            progress = starting_progress()
            self.frame_progress_percent_var.set(progress.percent)
            self.frame_progress_var.set(progress.progress_text)
            self.frame_remaining_var.set(progress.remaining_text)
        else:
            self.frame_progress_started_ms = None
        self.frame_status_var.set("生成中..." if running else "就绪")

    def _update_frame_progress(self, done: int, total: int, message: str) -> None:
        progress = update_progress(
            done,
            total,
            message,
            started_ms=self.frame_progress_started_ms,
            now_ms=monotonic_ms(),
        )
        self.frame_progress_percent_var.set(progress.percent)
        self.frame_progress_var.set(progress.progress_text)
        self.frame_remaining_var.set(progress.remaining_text)

    def _on_frame_sampling_done(self, result: Any, error: Exception | None) -> None:
        self._set_frame_running(False)
        if error is not None:
            self.frame_status_var.set(f"生成失败：{error}")
            progress = failed_progress()
            self.frame_progress_var.set(progress.progress_text)
            self.frame_progress_percent_var.set(progress.percent)
            self.frame_remaining_var.set(progress.remaining_text)
            self._show_error_report(
                "生成失败",
                "frame_export",
                error,
                {
                    "video_path": self.frame_source_path,
                    "mode": self.frame_mode_var.get(),
                    "output_dir": self.frame_output_var.get(),
                },
            )
            return
        if result is None:
            self.frame_status_var.set("生成失败")
            return
        self.frame_output_dir = result.output_dir
        self.frame_output_var.set(str(result.output_dir))
        self.frame_default_output_dir = result.output_dir
        self.frame_output_is_default = True
        self.frame_open_button.configure(state="normal")
        if hasattr(result, "index_json") and not hasattr(result, "report_html"):
            if result.sheet_paths:
                self.frame_status_var.set(f"已生成 {len(result.sheet_paths)} 张点击关键帧图，索引已写入输出目录。")
            else:
                self.frame_status_var.set("无点击事件，未生成点击关键帧图。")
        else:
            self.frame_status_var.set(
                f"已生成 {len(result.sheet_paths)} 张合成图，索引和预览页已写入输出目录。"
            )
        progress = completed_progress()
        self.frame_progress_percent_var.set(progress.percent)
        self.frame_progress_var.set(progress.progress_text)
        self.frame_remaining_var.set(progress.remaining_text)

    def open_frame_output(self) -> None:
        path = self.frame_output_dir or Path(self.frame_output_var.get() or "")
        if not path:
            messagebox.showinfo("没有输出", "请先生成合成图。")
            return
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def _frame_video_path(self) -> Path:
        if self.frame_source_path is None:
            raw_path = self.frame_video_var.get().strip()
            if not raw_path or raw_path == "未选择":
                raise ValueError("请先选择视频。")
            self.frame_source_path = Path(raw_path)
        video_path = self.frame_source_path.resolve()
        if not video_path.exists():
            raise FileNotFoundError(video_path)
        return video_path

    def _build_frame_sampler_config(self) -> FrameSamplerConfig:
        video_path = self._frame_video_path()

        output_dir = Path(self.frame_output_var.get().strip() or "").resolve()
        if not str(output_dir):
            raise ValueError("请设置输出目录。")

        return build_frame_sampler_config_from_state(
            FrameSamplerFormState(
                video_path=video_path,
                output_dir=output_dir,
                output_name=self.frame_output_name_var.get(),
                start_text=self.frame_start_var.get(),
                end_text=self.frame_end_var.get(),
                interval_text=self.frame_interval_var.get(),
                cols_text=self.frame_cols_var.get(),
                rows_text=self.frame_rows_var.get(),
                thumb_width_text=self.frame_thumb_width_var.get(),
                quality_preset=self.frame_quality_preset_var.get(),
                show_timestamp=self.frame_show_timestamp_var.get(),
                show_index=self.frame_show_index_var.get(),
                crop_enabled=self.frame_crop_enabled_var.get(),
                crop_x_text=self.frame_crop_x_var.get(),
                crop_y_text=self.frame_crop_y_var.get(),
                crop_width_text=self.frame_crop_w_var.get(),
                crop_height_text=self.frame_crop_h_var.get(),
                dense_rows=self._frame_dense_row_values(),
                click_events_path=self.frame_click_events_path,
                draw_click_markers=self.frame_draw_click_markers_var.get(),
                click_match_window_seconds=float(self.config.frame_sampler_click_match_window_seconds or 0.5),
            )
        )

    def _frame_crop_region_from_ui(self) -> CropRegion | None:
        return crop_region_from_values(
            self.frame_crop_enabled_var.get(),
            self.frame_crop_x_var.get(),
            self.frame_crop_y_var.get(),
            self.frame_crop_w_var.get(),
            self.frame_crop_h_var.get(),
        )

    def _build_click_keyframe_config(self) -> ClickKeyframeConfig:
        video_path = self._frame_video_path()
        events_path = self.frame_click_events_path or self._guess_frame_click_events_path(video_path)
        if events_path is None or not events_path.exists():
            raise FileNotFoundError("未找到 mouse_events.jsonl，无法按点击生成关键帧。")
        output_dir = Path(self.frame_output_var.get().strip() or "").resolve()
        if not str(output_dir):
            raise ValueError("请设置输出目录。")
        return build_click_keyframe_config_from_state(
            ClickKeyframeFormState(
                video_path=video_path,
                events_path=events_path,
                output_dir=output_dir,
                output_name=self.frame_output_name_var.get(),
                max_frames_text=self.frame_keyframe_max_var.get(),
                cols_text=self.frame_cols_var.get(),
                rows_text=self.frame_rows_var.get(),
                thumb_width_text=self.frame_thumb_width_var.get(),
                time_dedupe_ms_text=self.frame_keyframe_time_dedupe_var.get(),
                distance_dedupe_px_text=self.frame_keyframe_distance_dedupe_var.get(),
                visual_threshold_percent_text=self.frame_keyframe_visual_threshold_var.get(),
                show_timestamp=self.frame_show_timestamp_var.get(),
                show_index=self.frame_show_index_var.get(),
                draw_click_markers=self.frame_draw_click_markers_var.get(),
            )
        )

    def _frame_quality_settings(self) -> tuple[int, str]:
        return quality_settings(self.frame_quality_preset_var.get())

    def _collect_frame_dense_ranges(self) -> list[DenseRange]:
        return collect_dense_ranges(self._frame_dense_row_values())

    def _frame_dense_row_values(self) -> list[dict[str, str]]:
        return [
            {
                "start": row["start"].get().strip(),
                "end": row["end"].get().strip(),
                "interval": row["interval"].get().strip(),
            }
            for row in self.frame_dense_ranges
        ]

    def _sync_frame_config_from_ui(self) -> None:
        output_text = self.frame_output_var.get().strip()
        try:
            output_path = Path(output_text)
            if output_path.is_absolute():
                self.config.frame_sampler_output_root = str(output_path.parent)
            else:
                self.config.frame_sampler_output_root = output_text or FRAME_EXPORT_DIR_NAME
        except OSError:
            self.config.frame_sampler_output_root = FRAME_EXPORT_DIR_NAME
        self.config.frame_sampler_mode = "click_keyframes" if self._frame_is_click_keyframe_mode() else "interval"
        self.config.frame_sampler_output_name = self.frame_output_name_var.get().strip()
        self.config.frame_sampler_start = self.frame_start_var.get().strip()
        self.config.frame_sampler_end = self.frame_end_var.get().strip()
        self.config.frame_sampler_interval_seconds = self._safe_float_string(self.frame_interval_var, 10.0, 0.1, 3600.0)
        self.config.frame_sampler_cols = self._safe_int_string(self.frame_cols_var, 5, 1, 12)
        self.config.frame_sampler_rows = self._safe_int_string(self.frame_rows_var, 6, 1, 12)
        self.config.frame_sampler_thumb_width = self._safe_int_string(self.frame_thumb_width_var, 360, 120, 1600)
        self.config.frame_sampler_keyframe_max_frames = self._safe_int_string(self.frame_keyframe_max_var, 0, 0, 100000)
        self.config.frame_sampler_keyframe_time_dedupe_ms = self._safe_int_string(
            self.frame_keyframe_time_dedupe_var, 1500, 0, 10000
        )
        self.config.frame_sampler_keyframe_distance_dedupe_px = self._safe_int_string(
            self.frame_keyframe_distance_dedupe_var, 80, 0, 1000
        )
        self.config.frame_sampler_keyframe_visual_threshold_percent = self._safe_int_string(
            self.frame_keyframe_visual_threshold_var, 22, 0, 100
        )
        quality, _output_format = self._frame_quality_settings()
        self.config.frame_sampler_jpeg_quality = quality
        self.config.frame_sampler_quality_preset = self.frame_quality_preset_var.get().strip() or "高"
        self.config.frame_sampler_show_timestamp = self.frame_show_timestamp_var.get()
        self.config.frame_sampler_show_index = self.frame_show_index_var.get()
        dense_rows = [
            {
                "start": row["start"],
                "end": row["end"],
                "interval": row["interval"] or "2",
            }
            for row in self._frame_dense_row_values()
            if row["start"] or row["end"]
        ]
        self.config.frame_sampler_dense_enabled = bool(dense_rows)
        self.config.frame_sampler_dense_ranges = dense_rows
        if dense_rows:
            first_dense = dense_rows[0]
            self.config.frame_sampler_dense_start = first_dense["start"]
            self.config.frame_sampler_dense_end = first_dense["end"]
            try:
                self.config.frame_sampler_dense_interval_seconds = max(0.1, float(first_dense["interval"]))
            except ValueError:
                self.config.frame_sampler_dense_interval_seconds = 2.0
        else:
            self.config.frame_sampler_dense_start = ""
            self.config.frame_sampler_dense_end = ""
            self.config.frame_sampler_dense_interval_seconds = 2.0
        self.config.frame_sampler_crop_enabled = self.frame_crop_enabled_var.get()
        self.config.frame_sampler_crop_x = self._safe_int_string(self.frame_crop_x_var, 0, 0, 100000)
        self.config.frame_sampler_crop_y = self._safe_int_string(self.frame_crop_y_var, 0, 0, 100000)
        self.config.frame_sampler_crop_width = self._safe_int_string(self.frame_crop_w_var, 0, 0, 100000)
        self.config.frame_sampler_crop_height = self._safe_int_string(self.frame_crop_h_var, 0, 0, 100000)
        self.config.frame_sampler_draw_click_markers = self.frame_draw_click_markers_var.get()
        self.config.frame_sampler_click_events_path = str(self.frame_click_events_path or "")
        self.config.frame_sampler_click_match_window_seconds = 0.5

    def on_close(self) -> None:
        if self.is_counting_down:
            self.is_counting_down = False
            self._destroy_countdown_window()
        if self.is_recording or self.is_paused:
            if not messagebox.askyesno("正在录制", "是否停止录制并关闭？"):
                return
            self.stop_recording()
        self._destroy_countdown_window()
        if self.region_overlay is not None:
            self.region_overlay.destroy()
        self.root.destroy()

    def _on_config_changed(self) -> None:
        if self.is_recording or self.is_starting or self.is_stopping or self.is_paused or self.is_pausing or self.is_counting_down:
            return
        self._sync_config_from_ui()
        self._sync_frame_config_from_ui()
        self._save_config()
        self._apply_recording_banner_visibility()
        self._refresh_environment()
        self._refresh_readiness()

    def _sync_config_from_ui(self) -> None:
        self.config.session_name = self.session_name_var.get().strip()
        self.current_session_name = self.config.session_name
        self.config.record_outside_region = self.record_outside_var.get()
        self.config.record_mouse_samples = self.samples_var.get()
        self.config.record_click_events = self.clicks_var.get()
        self.config.record_wheel_events = self.wheel_var.get()
        self.config.record_drag_events = self.drag_var.get()
        self.config.show_sync_marker = self.sync_var.get()
        self.config.show_recording_status_banner = self.recording_status_banner_var.get()
        self.config.video_fps = self._safe_int(self.video_fps_var, 30, 1, 120)
        self.config.sample_fps = self._safe_int(self.sample_fps_var, 30, 1, 120)
        self.config.click_max_duration_ms = self._safe_int(self.click_duration_var, 500, 50, 2000)
        self.config.click_max_distance_px = self._safe_int(self.click_distance_var, 8, 1, 80)
        self.config.drag_min_distance_px = self._safe_int(self.drag_distance_var, 10, 1, 120)
        self.config.calibration_click_tolerance_px = self._safe_int(self.calibration_tolerance_var, 80, 20, 200)
        self.config.startup_countdown_seconds = self._safe_int(self.startup_countdown_var, 3, 0, 10)

    def _build_session_id(self) -> str:
        return build_session_id(self.session_name_var.get())

    def _next_segment_path(self) -> Path:
        assert self.storage is not None
        segment_index = len(self.segment_paths) + 1
        return self.storage.session_dir / f"recording_part_{segment_index:03d}.mp4"

    @staticmethod
    def _sanitize_session_name(value: str) -> str:
        return sanitize_session_name(value)

    @staticmethod
    def _compact_text(value: str, max_chars: int) -> str:
        text = " ".join(str(value).strip().split())
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return text[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _compact_path(value: Path | str, max_chars: int) -> str:
        text = str(value)
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[-max_chars:]
        path = Path(text)
        tail_parts = path.parts[-2:]
        if tail_parts:
            tail = str(Path(*tail_parts))
            separator = "\\" if "\\" in text else "/"
            candidate = f"...{separator}{tail}"
            if len(candidate) <= max_chars:
                return candidate
        return "..." + text[-(max_chars - 3) :]

    def _save_config(self) -> None:
        self.config.save(self.config_path)

    def _refresh_environment(self) -> None:
        ffmpeg_ok = FFmpegRecorder(self.config.ffmpeg_path).is_available()
        ffmpeg_status = "FFmpeg OK" if ffmpeg_ok else "FFmpeg 未配置"
        self.env_var.set(ffmpeg_status)

    def _apply_recording_banner_visibility(self) -> None:
        if self.config.show_recording_status_banner:
            self.recording_banner.grid()
        else:
            self.recording_banner.grid_remove()

    def _refresh_readiness(self) -> None:
        if self.is_starting or self.is_stopping or self.is_pausing or self.is_paused or self.is_counting_down:
            return
        if self.is_recording:
            self.primary_button.configure(state="normal")
            return
        self.cancel_region_button.configure(state="normal" if self.region is not None else "disabled")
        self.calibrate_button.configure(state="normal" if self.region is not None else "disabled")
        reasons = []
        if self.region is None:
            reasons.append("选区域")
        if not self.privacy_var.get():
            reasons.append("确认")
        if not FFmpegRecorder(self.config.ffmpeg_path).is_available():
            reasons.append("FFmpeg")
        if not self._output_root_writable():
            reasons.append("输出")

        if reasons:
            self.primary_button.configure(state="normal")
            self.readiness_var.set("需 " + " / ".join(reasons))
        else:
            self.primary_button.configure(state="normal")
            self.readiness_var.set("就绪")

    def _set_recording_ui(
        self,
        starting: bool = False,
        recording: bool = False,
        stopping: bool = False,
        pausing: bool = False,
        paused: bool = False,
        counting_down: bool = False,
    ) -> None:
        locked = starting or recording or stopping or pausing or paused or counting_down
        for widget in self.option_widgets:
            widget.configure(state="disabled" if locked else "normal")
        self.browse_button.configure(state="disabled" if locked else "normal")
        self.session_name_entry.configure(state="disabled" if locked else "normal")
        self.select_button.configure(state="disabled" if locked else "normal")
        if locked:
            self.calibrate_button.configure(state="disabled")
            self.cancel_region_button.configure(state="disabled")
        else:
            self.calibrate_button.configure(state="normal" if self.region is not None else "disabled")
            self.cancel_region_button.configure(state="normal" if self.region is not None else "disabled")
        if counting_down:
            self.primary_button.configure(text="▶", state="disabled", bg="#9a9a9a", activebackground="#9a9a9a")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg=COLORS["yellow"], fg=COLORS["text"])
            self.recording_banner.configure(bg=COLORS["warning_bg"], fg=COLORS["warning_text"])
            self.recording_banner_var.set("倒计时")
        elif starting:
            self.primary_button.configure(text="▶", state="disabled", bg="#9a9a9a", activebackground="#9a9a9a")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg=COLORS["yellow"], fg=COLORS["text"])
            self.recording_banner.configure(bg=COLORS["warning_bg"], fg=COLORS["warning_text"])
            self.recording_banner_var.set("启动中")
        elif recording:
            self.primary_button.configure(text="▶", state="disabled", bg="#9a9a9a", activebackground="#9a9a9a")
            self.finish_button.configure(state="normal")
            self.pause_button.configure(state="normal")
            self.status_badge.configure(bg=COLORS["red"], fg="white")
            self.recording_banner.configure(bg=COLORS["red"], fg="white")
            self.recording_banner_var.set("录制中")
        elif pausing:
            self.primary_button.configure(text="▶", state="disabled", bg="#9a9a9a", activebackground="#9a9a9a")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg=COLORS["yellow"], fg=COLORS["text"])
            self.recording_banner.configure(bg=COLORS["warning_bg"], fg=COLORS["warning_text"])
            self.recording_banner_var.set("暂停中")
        elif paused:
            self.primary_button.configure(text="▶", state="normal", bg=COLORS["green"], activebackground=COLORS["green"])
            self.finish_button.configure(state="normal")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg=COLORS["muted"], fg="white")
            self.recording_banner.configure(bg=COLORS["muted"], fg="white")
            self.recording_banner_var.set("已暂停")
        elif stopping:
            self.primary_button.configure(text="▶", state="disabled", bg="#9a9a9a", activebackground="#9a9a9a")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg=COLORS["yellow"], fg=COLORS["text"])
            self.recording_banner.configure(bg=COLORS["warning_bg"], fg=COLORS["warning_text"])
            self.recording_banner_var.set("保存中")
        else:
            self.primary_button.configure(text="▶", state="normal", bg=COLORS["green"], activebackground=COLORS["green"])
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg=COLORS["panel_alt"], fg=COLORS["text_secondary"])
            self.recording_banner.configure(bg=COLORS["panel_alt"], fg=COLORS["text_secondary"])
            if self.storage is None:
                self.recording_banner_var.set("未开始")
            else:
                self.recording_banner_var.set("已保存")

    def _output_root_writable(self) -> bool:
        output_root = self.config.output_root_path(self.base_dir)
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            probe = output_root / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except OSError:
            return False

    @staticmethod
    def _safe_int(variable: tk.IntVar, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(variable.get())
        except (tk.TclError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _safe_int_string(variable: tk.StringVar, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(float(str(variable.get()).strip()))
        except (tk.TclError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _safe_float_string(variable: tk.StringVar, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(str(variable.get()).strip())
        except (tk.TclError, ValueError):
            value = default
        return max(minimum, min(maximum, value))


def main(base_dir: Path | None = None) -> None:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[2]
    root = tk.Tk()
    ScreenMouseRecorderApp(root, base_dir)
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.focus_force()
    root.attributes("-topmost", True)
    root.after(1200, lambda: root.attributes("-topmost", False))
    root.mainloop()


if __name__ == "__main__":
    main()
