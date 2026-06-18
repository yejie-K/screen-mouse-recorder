from __future__ import annotations

import ctypes
from pathlib import Path
import time
from typing import Any

from . import __version__
from .config import AppConfig
from .models import Region, TimingContext, monotonic_ms, wall_time_iso
from .mouse_logger import MouseActivityLogger
from .postprocess import generate_summary
from .region_selector import virtual_screen_geometry
from .storage import JsonlWriter, SessionStorage
from .video_recorder import FFmpegRecorder, concat_mp4_segments


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800


def run_recording_selftest(base_dir: Path, seconds: float = 2.0) -> dict[str, Any]:
    config = AppConfig.load(base_dir / "config.json")
    origin_x, origin_y, screen_w, screen_h = virtual_screen_geometry()
    width = max(64, min(320, screen_w))
    height = max(64, min(240, screen_h))
    region = Region(origin_x, origin_y, width, height)

    session_id = f"selftest_{time.strftime('%Y%m%d_%H%M%S')}"
    storage = SessionStorage.create_unique(config.output_root_path(base_dir), session_id)
    timing = TimingContext(session_id=session_id, logger_start_monotonic_ms=monotonic_ms())
    recorder = FFmpegRecorder(config.ffmpeg_path)
    logger = MouseActivityLogger(
        region=region,
        timing=timing,
        config=config,
        event_writer=JsonlWriter(storage.mouse_events),
        sample_writer=JsonlWriter(storage.mouse_samples),
    )
    sync_markers: list[dict[str, Any]] = []
    original_cursor = _cursor_pos()

    meta = _build_meta(config, region, storage, timing, sync_markers)
    storage.write_json(storage.session_meta, meta)

    try:
        logger.start()
        timing.video_start_request_monotonic_ms = monotonic_ms()
        timing.video_zero_monotonic_ms = recorder.start(region, storage.recording_mp4, config.video_fps, storage.ffmpeg_log)
        marker = logger.emit_sync_marker("SYNC_001")
        sync_markers.append(
            {
                "marker_id": "SYNC_001",
                "t_monotonic_ms": marker["t_monotonic_ms"],
                "expected_video_ms": marker["t_video_ms"],
            }
        )
        storage.write_json(storage.session_meta, _build_meta(config, region, storage, timing, sync_markers))
        _exercise_mouse(region)
        time.sleep(max(0.2, seconds))
    finally:
        timing.recording_stop_monotonic_ms = monotonic_ms()
        recorder.stop()
        logger.stop()
        ctypes.windll.user32.SetCursorPos(original_cursor[0], original_cursor[1])

    storage.write_json(storage.session_meta, _build_meta(config, region, storage, timing, sync_markers))
    summary = generate_summary(storage)
    video_size = storage.recording_mp4.stat().st_size if storage.recording_mp4.exists() else 0
    result = {
        "session_dir": str(storage.session_dir),
        "recording_mp4": str(storage.recording_mp4),
        "recording_mp4_bytes": video_size,
        "mouse_events_jsonl": str(storage.mouse_events),
        "mouse_samples_jsonl": str(storage.mouse_samples),
        "summary": summary,
    }
    if video_size <= 0:
        raise RuntimeError(f"recording.mp4 was not created or is empty: {storage.recording_mp4}")
    if summary["samples_total"] <= 0:
        raise RuntimeError("mouse_samples.jsonl has no samples.")
    if summary["clicks_total"] <= 0:
        raise RuntimeError("mouse_events.jsonl did not capture the synthetic click.")
    return result


def run_pause_selftest(base_dir: Path, segment_seconds: float = 0.8, pause_seconds: float = 0.5) -> dict[str, Any]:
    config = AppConfig.load(base_dir / "config.json")
    origin_x, origin_y, screen_w, screen_h = virtual_screen_geometry()
    region = Region(origin_x, origin_y, max(64, min(320, screen_w)), max(64, min(240, screen_h)))
    session_id = f"selftest_pause_{time.strftime('%Y%m%d_%H%M%S')}"
    storage = SessionStorage.create_unique(config.output_root_path(base_dir), session_id)
    timing = TimingContext(session_id=session_id, logger_start_monotonic_ms=monotonic_ms())
    segments: list[dict[str, Any]] = []
    segment_paths: list[Path] = []
    pause_periods: list[dict[str, Any]] = []
    event_counter = 0
    sample_counter = 0
    original_cursor = _cursor_pos()

    try:
        for segment_index in (1, 2):
            segment_path = storage.session_dir / f"recording_part_{segment_index:03d}.mp4"
            recorder = FFmpegRecorder(config.ffmpeg_path)
            logger = MouseActivityLogger(
                region=region,
                timing=timing,
                config=config,
                event_writer=JsonlWriter(storage.mouse_events),
                sample_writer=JsonlWriter(storage.mouse_samples),
                event_counter_start=event_counter,
                sample_counter_start=sample_counter,
            )
            logger.start()
            start_ms = recorder.start(region, segment_path, config.video_fps, storage.ffmpeg_log)
            if timing.video_zero_monotonic_ms is None:
                timing.video_zero_monotonic_ms = start_ms
            _exercise_mouse(region)
            time.sleep(max(0.2, segment_seconds))
            end_ms = monotonic_ms()
            recorder.stop()
            logger.stop()
            event_counter = logger.event_counter
            sample_counter = logger.sample_counter
            segment_paths.append(segment_path)
            segments.append(
                {
                    "file": segment_path.name,
                    "start_monotonic_ms": round(start_ms, 3),
                    "start_video_ms": round(timing.t_video_ms(start_ms), 3),
                    "end_monotonic_ms": round(end_ms, 3),
                    "end_video_ms": round(timing.t_video_ms(end_ms), 3),
                }
            )
            if segment_index == 1:
                pause_start = monotonic_ms()
                time.sleep(max(0.1, pause_seconds))
                pause_end = monotonic_ms()
                duration = pause_end - pause_start
                timing.paused_duration_ms += duration
                pause_periods.append(
                    {
                        "start_monotonic_ms": round(pause_start, 3),
                        "end_monotonic_ms": round(pause_end, 3),
                        "duration_ms": round(duration, 3),
                    }
                )
        timing.recording_stop_monotonic_ms = monotonic_ms()
    finally:
        ctypes.windll.user32.SetCursorPos(original_cursor[0], original_cursor[1])

    concat_mp4_segments(config.ffmpeg_path, segment_paths, storage.recording_mp4, storage.ffmpeg_log)
    meta = _build_meta(config, region, storage, timing, [])
    meta["video"]["segments"] = segments
    meta["pause_periods"] = pause_periods
    storage.write_json(storage.session_meta, meta)
    summary = generate_summary(storage)
    video_size = storage.recording_mp4.stat().st_size if storage.recording_mp4.exists() else 0
    result = {
        "session_dir": str(storage.session_dir),
        "recording_mp4": str(storage.recording_mp4),
        "recording_mp4_bytes": video_size,
        "segments": [str(path) for path in segment_paths],
        "pause_periods": pause_periods,
        "summary": summary,
    }
    if video_size <= 0:
        raise RuntimeError("pause selftest did not create recording.mp4")
    if len(segment_paths) != 2:
        raise RuntimeError("pause selftest did not create two recording segments")
    if summary["clicks_total"] < 2:
        raise RuntimeError("pause selftest did not capture clicks across both segments")
    return result


def _build_meta(
    config: AppConfig,
    region: Region,
    storage: SessionStorage,
    timing: TimingContext,
    sync_markers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": timing.session_id,
        "app_version": __version__,
        "platform": "windows",
        "created_at": wall_time_iso(),
        "recording_region": region.to_dict(),
        "video": {
            "file": storage.recording_mp4.name,
            "fps": config.video_fps,
            "width": region.width,
            "height": region.height,
            "codec": "h264",
        },
        "config": {
            "sample_fps": config.sample_fps,
            "record_outside_region": config.record_outside_region,
            "record_mouse_samples": config.record_mouse_samples,
            "record_click_events": config.record_click_events,
            "record_wheel_events": config.record_wheel_events,
            "record_drag_events": config.record_drag_events,
            "show_sync_marker": config.show_sync_marker,
            "show_recording_status_banner": config.show_recording_status_banner,
            "startup_countdown_seconds": config.startup_countdown_seconds,
            "click_max_duration_ms": config.click_max_duration_ms,
            "click_max_distance_px": config.click_max_distance_px,
            "drag_min_distance_px": config.drag_min_distance_px,
            "double_click_window_ms": config.double_click_window_ms,
            "calibration_click_tolerance_px": config.calibration_click_tolerance_px,
            "calibration_residual_warning_px": config.calibration_residual_warning_px,
        },
        "timing": timing.timing_dict(),
        "sync_markers": sync_markers,
    }


def _exercise_mouse(region: Region) -> None:
    x = region.screen_x + min(region.width - 1, max(1, region.width // 2))
    y = region.screen_y + min(region.height - 1, max(1, region.height // 2))
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(0.1)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.1)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, 120, 0)


def _cursor_pos() -> tuple[int, int]:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)
