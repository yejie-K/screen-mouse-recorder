from __future__ import annotations

from dataclasses import dataclass, field, fields
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    video_fps: int = 30
    sample_fps: int = 30
    output_root: str = "sessions"
    session_name: str = ""
    record_outside_region: bool = True
    record_mouse_samples: bool = True
    record_click_events: bool = True
    record_wheel_events: bool = True
    record_drag_events: bool = True
    show_sync_marker: bool = False
    show_recording_status_banner: bool = True
    startup_countdown_seconds: int = 3
    click_max_duration_ms: int = 500
    click_max_distance_px: int = 8
    drag_min_distance_px: int = 10
    double_click_window_ms: int = 500
    calibration_click_tolerance_px: int = 80
    calibration_residual_warning_px: int = 20
    ffmpeg_path: str | None = None
    frame_sampler_output_root: str = "frame_exports"
    frame_sampler_output_name: str = ""
    frame_sampler_mode: str = "interval"
    frame_sampler_start: str = "00:00"
    frame_sampler_end: str = ""
    frame_sampler_interval_seconds: float = 10.0
    frame_sampler_cols: int = 5
    frame_sampler_rows: int = 6
    frame_sampler_thumb_width: int = 360
    frame_sampler_keyframe_max_frames: int = 0
    frame_sampler_keyframe_time_dedupe_ms: int = 1500
    frame_sampler_keyframe_distance_dedupe_px: int = 80
    frame_sampler_keyframe_visual_threshold_percent: int = 22
    frame_sampler_jpeg_quality: int = 85
    frame_sampler_quality_preset: str = "高"
    frame_sampler_show_timestamp: bool = True
    frame_sampler_show_index: bool = True
    frame_sampler_dense_enabled: bool = False
    frame_sampler_dense_start: str = ""
    frame_sampler_dense_end: str = ""
    frame_sampler_dense_interval_seconds: float = 2.0
    frame_sampler_dense_ranges: list[dict[str, str]] = field(default_factory=list)
    frame_sampler_crop_enabled: bool = False
    frame_sampler_crop_x: int = 0
    frame_sampler_crop_y: int = 0
    frame_sampler_crop_width: int = 0
    frame_sampler_crop_height: int = 0
    frame_sampler_draw_click_markers: bool = True
    frame_sampler_click_events_path: str = ""
    frame_sampler_click_match_window_seconds: float = 0.5

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        valid = {field.name for field in fields(cls)}
        filtered: dict[str, Any] = {key: value for key, value in data.items() if key in valid}
        if filtered.get("frame_sampler_output_root") == "frame_sheets":
            filtered["frame_sampler_output_root"] = "frame_exports"
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def output_root_path(self, base_dir: Path) -> Path:
        path = Path(self.output_root)
        if not path.is_absolute():
            path = base_dir / path
        return path
