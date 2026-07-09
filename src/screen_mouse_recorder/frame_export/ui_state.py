from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import ClickKeyframeConfig, CropRegion, DenseRange, FrameSamplerConfig
from .timecode import parse_timecode


@dataclass(slots=True)
class FrameSamplerFormState:
    video_path: Path
    output_dir: Path
    output_name: str = ""
    start_text: str = ""
    end_text: str = ""
    interval_text: str = "10"
    cols_text: str = "5"
    rows_text: str = "6"
    thumb_width_text: str = "360"
    quality_preset: str = "高"
    show_timestamp: bool = True
    show_index: bool = True
    crop_enabled: bool = False
    crop_x_text: str = "0"
    crop_y_text: str = "0"
    crop_width_text: str = ""
    crop_height_text: str = ""
    dense_rows: list[dict[str, str]] = field(default_factory=list)
    click_events_path: Path | None = None
    draw_click_markers: bool = False
    click_match_window_seconds: float = 0.5


@dataclass(slots=True)
class ClickKeyframeFormState:
    video_path: Path
    events_path: Path
    output_dir: Path
    output_name: str = ""
    max_frames_text: str = "0"
    cols_text: str = "5"
    rows_text: str = "6"
    thumb_width_text: str = "360"
    time_dedupe_ms_text: str = "1500"
    distance_dedupe_px_text: str = "80"
    visual_threshold_percent_text: str = "22"
    show_timestamp: bool = True
    show_index: bool = True
    draw_click_markers: bool = True


def build_frame_sampler_config_from_state(state: FrameSamplerFormState) -> FrameSamplerConfig:
    quality, output_format = quality_settings(state.quality_preset)
    return FrameSamplerConfig(
        video_path=state.video_path,
        output_dir=state.output_dir,
        output_basename=sanitize_output_basename(state.output_name),
        start_seconds=parse_timecode(state.start_text) or 0.0,
        end_seconds=parse_timecode(state.end_text),
        interval_seconds=safe_float_text(state.interval_text, 10.0, 0.1, 3600.0),
        sheet_cols=safe_int_text(state.cols_text, 5, 1, 12),
        sheet_rows=safe_int_text(state.rows_text, 6, 1, 12),
        thumb_width=safe_int_text(state.thumb_width_text, 360, 120, 1600),
        jpeg_quality=quality,
        output_format=output_format,
        show_timestamp=state.show_timestamp,
        show_index=state.show_index,
        crop=crop_region_from_values(
            state.crop_enabled,
            state.crop_x_text,
            state.crop_y_text,
            state.crop_width_text,
            state.crop_height_text,
        ),
        dense_ranges=collect_dense_ranges(state.dense_rows),
        click_events_path=state.click_events_path,
        draw_click_markers=state.draw_click_markers,
        click_match_window_seconds=max(0.1, float(state.click_match_window_seconds or 0.5)),
    )


def build_click_keyframe_config_from_state(state: ClickKeyframeFormState) -> ClickKeyframeConfig:
    return ClickKeyframeConfig(
        video_path=state.video_path,
        events_path=state.events_path.resolve(),
        output_dir=state.output_dir,
        output_basename=sanitize_output_basename(state.output_name) or "keyframes_click_sheet",
        max_frames=safe_int_text(state.max_frames_text, 0, 0, 100000),
        sheet_cols=safe_int_text(state.cols_text, 5, 1, 12),
        sheet_rows=safe_int_text(state.rows_text, 6, 1, 12),
        thumb_width=safe_int_text(state.thumb_width_text, 360, 120, 1600),
        time_dedupe_seconds=safe_int_text(state.time_dedupe_ms_text, 1500, 0, 10000) / 1000,
        distance_dedupe_px=safe_int_text(state.distance_dedupe_px_text, 80, 0, 1000),
        visual_change_threshold=safe_int_text(state.visual_threshold_percent_text, 22, 0, 100) / 100,
        show_timestamp=state.show_timestamp,
        show_index=state.show_index,
        draw_click_markers=state.draw_click_markers,
    )


def crop_region_from_values(
    enabled: bool,
    x_text: str,
    y_text: str,
    width_text: str,
    height_text: str,
) -> CropRegion | None:
    if not enabled:
        return None
    crop_width = safe_int_text(width_text, 0, 0, 100000)
    crop_height = safe_int_text(height_text, 0, 0, 100000)
    if crop_width <= 0 or crop_height <= 0:
        return None
    return CropRegion(
        x=safe_int_text(x_text, 0, 0, 100000),
        y=safe_int_text(y_text, 0, 0, 100000),
        width=crop_width,
        height=crop_height,
    )


def collect_dense_ranges(rows: list[dict[str, str]]) -> list[DenseRange]:
    dense_ranges: list[DenseRange] = []
    for index, row in enumerate(rows, start=1):
        start_text = row.get("start", "").strip()
        end_text = row.get("end", "").strip()
        interval_text = row.get("interval", "").strip()
        if not start_text and not end_text:
            continue
        if not start_text or not end_text:
            raise ValueError(f"关键段第 {index} 行需要同时填写开始和结束时间。")
        start = parse_timecode(start_text)
        end = parse_timecode(end_text)
        if start is None or end is None:
            raise ValueError(f"关键段第 {index} 行时间格式不正确。")
        if end <= start:
            raise ValueError(f"关键段第 {index} 行的结束时间必须大于开始时间。")
        try:
            interval = float(interval_text or "2")
        except ValueError as exc:
            raise ValueError(f"关键段第 {index} 行的间隔秒必须是数字。") from exc
        dense_ranges.append(DenseRange(start, end, max(0.1, min(3600.0, interval))))
    return dense_ranges


def quality_settings(preset: str) -> tuple[int, str]:
    preset = preset.strip()
    if preset == "低":
        return 65, "jpg"
    if preset == "中":
        return 80, "jpg"
    if preset == "无损":
        return 100, "png"
    return 90, "jpg"


def safe_int_text(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def safe_float_text(value: str, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def sanitize_output_basename(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    forbidden = '<>:"/\\|?*'
    cleaned = "".join("_" if char in forbidden or ord(char) < 32 else char for char in text)
    cleaned = cleaned.strip(" ._")
    return cleaned[:120]
