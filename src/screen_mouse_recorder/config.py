from __future__ import annotations

from dataclasses import dataclass, fields
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

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        valid = {field.name for field in fields(cls)}
        filtered: dict[str, Any] = {key: value for key, value in data.items() if key in valid}
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
