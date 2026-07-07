from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any


REPORT_OUTPUT_DIR_NAME = "auto_report"
LEGACY_REPORT_OUTPUT_DIR_NAME = "analysis_output"
FRAME_EXPORT_DIR_NAME = "frame_exports"


def sanitize_session_name(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value)
    value = value.strip("._-")
    return value[:60]


def build_session_id(custom_name: str = "", *, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("rec_%Y%m%d_%H%M%S")
    safe_name = sanitize_session_name(custom_name)
    return f"{timestamp}_{safe_name}" if safe_name else timestamp


def default_report_output_dir(source_path: Path) -> Path:
    source_path = source_path.resolve()
    import_dir = source_path if source_path.is_dir() else source_path.parent
    output_dir = import_dir / REPORT_OUTPUT_DIR_NAME
    legacy_dir = import_dir / LEGACY_REPORT_OUTPUT_DIR_NAME
    if not output_dir.exists() and legacy_dir.exists():
        return legacy_dir
    return output_dir


def default_frame_export_output_dir(
    video_path: Path,
    output_root: Path,
    *,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    mode: str = "interval",
    crop: Any = None,
    unique: bool = True,
) -> Path:
    del video_path
    range_text = f"{compact_timecode(start_seconds)}-{compact_timecode(end_seconds)}"
    mode_text = export_mode_prefix(mode)
    crop_text = export_crop_text(crop)
    version = 1
    while True:
        candidate = output_root / f"{mode_text}_{range_text}_{crop_text}_v{version:03d}"
        if not unique or not candidate.exists():
            return candidate
        version += 1


def export_mode_prefix(mode: str) -> str:
    mode = re.sub(r"[^a-z0-9_]+", "_", str(mode or "").lower()).strip("_")
    if mode in {"click", "click_keyframes", "keyframes"}:
        return "click"
    if mode in {"dense", "dense_interval"}:
        return "dense"
    return "interval"


def export_crop_text(crop: Any) -> str:
    if crop is None:
        return "full"
    x = int(getattr(crop, "x", 0) or 0)
    y = int(getattr(crop, "y", 0) or 0)
    width = int(getattr(crop, "width", 0) or 0)
    height = int(getattr(crop, "height", 0) or 0)
    if width <= 0 or height <= 0:
        return "full"
    return f"crop_x{x}_y{y}_w{width}_h{height}"


def compact_timecode(seconds: float | None) -> str:
    if seconds is None:
        return "end"
    seconds = max(0.0, float(seconds))
    whole = int(round(seconds))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}{minutes:02d}{secs:02d}"
