from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import platform
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from . import __version__
from .analysis import default_analysis_output_dir, describe_analysis_source, generate_behavior_report
from .config import AppConfig
from .models import Region, TimingContext, monotonic_ms, wall_time_iso
from .mouse_logger import MouseActivityLogger
from .postprocess import generate_summary
from .region_selector import RecordingRegionOverlay, RegionSelector, run_click_calibration, show_sync_marker
from .storage import JsonlWriter, SessionStorage
from .ui.analysis_page import build_analysis_page
from .ui.components import (
    analysis_output_row as create_analysis_output_row,
    metric_card,
    number_field as create_number_field,
    option_checkbutton,
    transport_button as create_transport_button,
)
from .ui.record_page import build_record_page
from .ui.theme import apply_app_theme
from .video_recorder import FFmpegRecorder, concat_mp4_segments


class ScreenMouseRecorderApp:
    def __init__(self, root: tk.Tk, base_dir: Path) -> None:
        self.root = root
        self.base_dir = base_dir
        self.config_path = base_dir / "config.json"
        self.config = AppConfig.load(self.config_path)
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
        self.analysis_input_var = tk.StringVar(value="未选择")
        self.analysis_output_var = tk.StringVar(value="analysis_output")
        self.analysis_summary_var = tk.StringVar(value="等待导入")
        self.analysis_status_var = tk.StringVar(value="就绪")
        self.analysis_events_var = tk.StringVar(value="--")
        self.analysis_samples_var = tk.StringVar(value="--")
        self.analysis_clicks_var = tk.StringVar(value="--")
        self.analysis_duration_var = tk.StringVar(value="--")
        self.analysis_meta_var = tk.StringVar(value="--")
        self.analysis_source_path: Path | None = None
        self.analysis_output_dir: Path | None = None
        self.analysis_output_status_vars: dict[str, tk.StringVar] = {}
        self.analysis_output_badges: dict[str, tk.Label] = {}

        self.record_outside_var = tk.BooleanVar(value=self.config.record_outside_region)
        self.samples_var = tk.BooleanVar(value=self.config.record_mouse_samples)
        self.clicks_var = tk.BooleanVar(value=self.config.record_click_events)
        self.wheel_var = tk.BooleanVar(value=self.config.record_wheel_events)
        self.drag_var = tk.BooleanVar(value=self.config.record_drag_events)
        self.sync_var = tk.BooleanVar(value=self.config.show_sync_marker)
        self.recording_status_banner_var = tk.BooleanVar(value=self.config.show_recording_status_banner)
        self.privacy_var = tk.BooleanVar(value=False)
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
        ttk.Label(header, text=f"v{__version__}", style="App.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(7, 0))
        tk.Label(
            header,
            textvariable=self.env_var,
            bg="#edf1f4",
            fg="#60717d",
            anchor="e",
            font=("Segoe UI", 9),
            width=24,
        ).grid(row=0, column=1, sticky="e", padx=(12, 14), pady=(6, 0))
        self.status_badge = tk.Label(
            header,
            textvariable=self.status_var,
            bg="#dfe7ec",
            fg="#263238",
            padx=12,
            pady=4,
            width=10,
            anchor="center",
            font=("Segoe UI", 10, "bold"),
        )
        self.status_badge.grid(row=0, column=2, sticky="e")

        main_notebook = ttk.Notebook(shell, style="Settings.TNotebook", takefocus=False)
        main_notebook.bind("<ButtonRelease-1>", lambda _event: self.root.focus_set(), add="+")
        main_notebook.grid(row=1, column=0, sticky="nsew")

        record_page = ttk.Frame(main_notebook, style="App.TFrame", padding=(0, 12, 0, 0))
        analysis_page = ttk.Frame(main_notebook, style="App.TFrame", padding=(0, 12, 0, 0))
        main_notebook.add(record_page, text="录制")
        main_notebook.add(analysis_page, text="分析处理")

        build_record_page(self, record_page)
        self._build_analysis_page(analysis_page)

    def _build_analysis_page(self, parent: tk.Widget) -> None:
        build_analysis_page(self, parent)

    def _metric(self, parent: tk.Widget, column: int, label: str, variable: tk.StringVar) -> None:
        metric_card(parent, column, label, variable, padx=(6, 0))

    def _analysis_metric(self, parent: tk.Widget, column: int, label: str, variable: tk.StringVar) -> None:
        metric_card(
            parent,
            column,
            label,
            variable,
            value_font=("Segoe UI", 13, "bold"),
            padx=(8, 0),
        )

    def _analysis_output_row(self, parent: tk.Widget, row: int, column: int, key: str, title: str, filename: str) -> None:
        status_var = tk.StringVar(value="待")
        self.analysis_output_status_vars[key] = status_var
        self.analysis_output_badges[key] = create_analysis_output_row(parent, row, column, title, filename, status_var)

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
        ]
        for variable in vars_to_track:
            variable.trace_add("write", lambda *_args: self._on_config_changed())

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
            messagebox.showerror("平台不支持", "当前 MVP 使用 Windows 鼠标 hook 和 FFmpeg gdigrab。")
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
        messagebox.showerror("启动失败", str(exc))

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
            messagebox.showwarning("暂停失败", f"暂停录制失败：{error}")
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
            messagebox.showwarning("保存失败", f"录制已停止，但保存或摘要生成失败：{error}")
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
        else:
            self.status_var.set("已停止")
            self.summary_var.set("未生成摘要")
        self._refresh_readiness()

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
            messagebox.showerror("生成失败", str(exc))
            return
        self.summary_var.set(
            f"事件 {summary['events_total']} · 采样 {summary['samples_total']} · "
            f"点击 {summary['clicks_total']} · 滚轮 {summary['wheel_events']} · 拖拽 {summary['drag_count']}"
        )
        self._refresh_asset_status()
        messagebox.showinfo("已生成", "mouse_summary.json、mouse_summary.xlsx 和 mouse_analysis.xlsx 已重新生成。")

    def choose_analysis_xlsx(self) -> None:
        initial_dir = self.storage.session_dir if self.storage is not None else self.config.output_root_path(self.base_dir)
        path = filedialog.askopenfilename(
            title="选择 xlsx",
            initialdir=initial_dir,
            filetypes=[("Excel 工作簿", "*.xlsx"), ("所有文件", "*.*")],
        )
        if path:
            self._set_analysis_source(Path(path))

    def choose_analysis_folder(self) -> None:
        initial_dir = self.storage.session_dir if self.storage is not None else self.config.output_root_path(self.base_dir)
        path = filedialog.askdirectory(title="选择 session 文件夹", initialdir=initial_dir)
        if path:
            self._set_analysis_source(Path(path))

    def _set_analysis_source(self, path: Path) -> None:
        path = path.resolve()
        self.analysis_source_path = path
        self.analysis_output_dir = default_analysis_output_dir(path)
        self.analysis_input_var.set(str(path))
        self.analysis_output_var.set(str(self.analysis_output_dir))
        self.analysis_status_var.set("已导入")
        self.analysis_open_button.configure(state="normal" if self.analysis_output_dir.exists() else "disabled")

        info = describe_analysis_source(path)
        self.analysis_events_var.set(str(info["events_total"]))
        self.analysis_samples_var.set(str(info["samples_total"]))
        self.analysis_clicks_var.set(str(info["clicks_total"]))
        self.analysis_duration_var.set(f"{info['duration_minutes']}分")
        self.analysis_meta_var.set("OK" if info["has_meta"] else "--")
        warning_text = self._compact_text("；".join(str(item) for item in info["warnings"]), 62) if info["warnings"] else ""
        self.analysis_summary_var.set(warning_text or "可分析")
        self._refresh_analysis_output_statuses()

    def run_import_analysis(self) -> None:
        if self.analysis_source_path is None:
            messagebox.showwarning("需要导入", "请先选择 xlsx 或 session 文件夹。")
            return
        source_path = self.analysis_source_path
        output_dir = self.analysis_output_dir or default_analysis_output_dir(source_path)
        self._set_analysis_running(True)

        def worker() -> None:
            result = None
            error: Exception | None = None
            try:
                result = generate_behavior_report(source_path, output_dir)
            except Exception as exc:
                error = exc
            self.root.after(0, lambda: self._on_import_analysis_done(result, error))

        threading.Thread(target=worker, name="import-analysis", daemon=True).start()

    def _set_analysis_running(self, running: bool) -> None:
        self.analysis_generate_button.configure(state="disabled" if running else "normal")
        self.analysis_status_var.set("生成中" if running else "就绪")
        if running:
            self._set_all_analysis_output_statuses("生成中", "#f0b429", "#17212b")

    def _on_import_analysis_done(self, result: Any, error: Exception | None) -> None:
        self._set_analysis_running(False)
        if error is not None:
            self.analysis_status_var.set("生成失败")
            self._set_all_analysis_output_statuses("失败", "#d83b3b", "white")
            messagebox.showerror("生成失败", str(error))
            return
        if result is None:
            self.analysis_status_var.set("生成失败")
            return
        self.analysis_output_dir = result.output_dir
        self.analysis_output_var.set(str(result.output_dir))
        self.analysis_open_button.configure(state="normal")
        metrics = result.metrics
        self.analysis_events_var.set(str(metrics["events_total"]))
        self.analysis_samples_var.set(str(metrics["samples_total"]))
        self.analysis_clicks_var.set(str(metrics["clicks_total"]))
        self.analysis_duration_var.set(f"{metrics['duration_minutes']}分")
        self.analysis_meta_var.set("OK")
        warning_text = self._compact_text("；".join(result.warnings), 62) if result.warnings else ""
        self.analysis_summary_var.set(warning_text or f"已生成 · {metrics['clicks_per_minute']} 点击/分")
        self.analysis_status_var.set("已生成")
        self._refresh_analysis_output_statuses()

    def _refresh_analysis_output_statuses(self) -> None:
        if self.analysis_output_dir is None:
            self._set_all_analysis_output_statuses("待", "#dfe7ec", "#263238")
            return
        files = {
            "report": "mouse_behavior_report.xlsx",
            "heatmap_circle": "click_heatmap_circle.png",
            "timeline": "activity_timeline.png",
            "scatter": "click_scatter.png",
            "drag_durations": "drag_durations.png",
        }
        for key, filename in files.items():
            path = self.analysis_output_dir / filename
            if path.exists() and path.stat().st_size > 0:
                self._set_analysis_output_status(key, "OK", "#1f9d55", "white")
            else:
                self._set_analysis_output_status(key, "待", "#dfe7ec", "#263238")

    def _set_all_analysis_output_statuses(self, text: str, bg: str, fg: str) -> None:
        for key in self.analysis_output_status_vars:
            self._set_analysis_output_status(key, text, bg, fg)

    def _set_analysis_output_status(self, key: str, text: str, bg: str, fg: str) -> None:
        if key in self.analysis_output_status_vars:
            self.analysis_output_status_vars[key].set(text)
        if key in self.analysis_output_badges:
            self.analysis_output_badges[key].configure(bg=bg, fg=fg)

    def open_analysis_output(self) -> None:
        if self.analysis_output_dir is None:
            if self.analysis_source_path is None:
                messagebox.showinfo("没有输出", "请先生成分析报告。")
                return
            self.analysis_output_dir = default_analysis_output_dir(self.analysis_source_path)
        if not self.analysis_output_dir.exists():
            messagebox.showinfo("没有输出", "当前还没有生成分析输出。")
            return
        os.startfile(self.analysis_output_dir)

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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        custom_name = self._sanitize_session_name(self.session_name_var.get())
        return f"{timestamp}_{custom_name}" if custom_name else timestamp

    def _next_segment_path(self) -> Path:
        assert self.storage is not None
        segment_index = len(self.segment_paths) + 1
        return self.storage.session_dir / f"recording_part_{segment_index:03d}.mp4"

    @staticmethod
    def _sanitize_session_name(value: str) -> str:
        value = value.strip()
        value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value)
        value = value.strip("._-")
        return value[:60]

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
            self.primary_button.configure(text="▶", state="disabled", bg="#9aa8b1", activebackground="#9aa8b1")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg="#ffd166", fg="#17212b")
            self.recording_banner.configure(bg="#fff3cd", fg="#5c4400")
            self.recording_banner_var.set("倒计时")
        elif starting:
            self.primary_button.configure(text="▶", state="disabled", bg="#9aa8b1", activebackground="#9aa8b1")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg="#ffd166", fg="#17212b")
            self.recording_banner.configure(bg="#fff3cd", fg="#5c4400")
            self.recording_banner_var.set("启动中")
        elif recording:
            self.primary_button.configure(text="▶", state="disabled", bg="#9aa8b1", activebackground="#9aa8b1")
            self.finish_button.configure(state="normal")
            self.pause_button.configure(state="normal")
            self.status_badge.configure(bg="#d83b3b", fg="white")
            self.recording_banner.configure(bg="#d83b3b", fg="white")
            self.recording_banner_var.set("录制中")
        elif pausing:
            self.primary_button.configure(text="▶", state="disabled", bg="#9aa8b1", activebackground="#9aa8b1")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg="#ffd166", fg="#17212b")
            self.recording_banner.configure(bg="#fff3cd", fg="#5c4400")
            self.recording_banner_var.set("暂停中")
        elif paused:
            self.primary_button.configure(text="▶", state="normal", bg="#1f9d55", activebackground="#1f9d55")
            self.finish_button.configure(state="normal")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg="#60717d", fg="white")
            self.recording_banner.configure(bg="#60717d", fg="white")
            self.recording_banner_var.set("已暂停")
        elif stopping:
            self.primary_button.configure(text="▶", state="disabled", bg="#9aa8b1", activebackground="#9aa8b1")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg="#ffd166", fg="#17212b")
            self.recording_banner.configure(bg="#fff3cd", fg="#5c4400")
            self.recording_banner_var.set("保存中")
        else:
            self.primary_button.configure(text="▶", state="normal", bg="#1f9d55", activebackground="#1f9d55")
            self.finish_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_badge.configure(bg="#dfe7ec", fg="#263238")
            self.recording_banner.configure(bg="#dfe7ec", fg="#263238")
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


def main(base_dir: Path | None = None) -> None:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[2]
    root = tk.Tk()
    ScreenMouseRecorderApp(root, base_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
