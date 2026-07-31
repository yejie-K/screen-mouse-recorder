from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(slots=True)
class VideoInfo:
    path: Path
    duration_seconds: float
    width: int
    height: int
    fps: float
    file_size_bytes: int


@dataclass(slots=True)
class CropRegion:
    x: int
    y: int
    width: int
    height: int


@dataclass(slots=True)
class DenseRange:
    start_seconds: float
    end_seconds: float
    interval_seconds: float


@dataclass(slots=True)
class ClickMarker:
    seconds: float
    x: float
    y: float


@dataclass(slots=True)
class ClickKeyframeEvent:
    source_index: int
    seconds: float
    event_type: str
    event_id: str
    x: float | None
    y: float | None


@dataclass(slots=True)
class ClickKeyframeSelection:
    events: list[ClickKeyframeEvent]
    skipped_count: int
    reasons_by_event_id: dict[str, str] = field(default_factory=dict)
    cluster_by_event_id: dict[str, int] = field(default_factory=dict)
    cluster_size_by_event_id: dict[str, int] = field(default_factory=dict)
    visual_diff_by_event_id: dict[str, float] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ClickVisualSignature:
    global_pixels: tuple[int, ...]
    local_pixels: tuple[int, ...] | None = None


@dataclass(slots=True)
class ClickKeyframeConfig:
    video_path: Path
    events_path: Path
    output_dir: Path
    max_frames: int = 0
    sheet_cols: int = 5
    sheet_rows: int = 6
    thumb_width: int = 360
    time_dedupe_seconds: float = 1.5
    distance_dedupe_px: float = 80.0
    visual_change_threshold: float = 0.22
    visual_sample_size: int = 48
    visual_crop_radius_px: int = 140
    cluster_tail_min_size: int = 5
    cluster_tail_min_duration_seconds: float = 2.0
    silent_gap_seconds: float = 10.0
    silent_long_gap_seconds: float = 25.0
    silent_max_frames_per_gap: int = 5
    include_double_clicks: bool = False
    include_drag_events: bool = False
    frame_offset_seconds: float = 0.0
    show_timestamp: bool = True
    show_index: bool = True
    draw_click_markers: bool = True
    output_basename: str = "keyframes_click_sheet"


@dataclass(slots=True)
class ClickKeyframeResult:
    output_dir: Path
    sheet_paths: list[Path]
    index_json: Path
    events_total: int
    events_kept: int
    events_skipped: int
    warnings: list[str]


@dataclass(slots=True)
class ClickKeyframeEstimate:
    events_total: int
    events_kept: int
    events_skipped: int
    sheet_count: int
    frames_per_sheet: int
    estimated_processing_seconds: float
    visual_signature_frames: int = 0
    cached_frame_reuses: int = 0
    estimated_frame_extractions: int = 0
    timeline_start_seconds: float = 0.0
    timeline_end_seconds: float = 0.0


@dataclass(slots=True)
class FrameSamplerConfig:
    video_path: Path
    output_dir: Path
    output_basename: str = ""
    start_seconds: float = 0.0
    end_seconds: float | None = None
    interval_seconds: float = 10.0
    sheet_cols: int = 5
    sheet_rows: int = 6
    thumb_width: int = 360
    jpeg_quality: int = 85
    output_format: str = "jpg"
    show_timestamp: bool = True
    show_index: bool = True
    crop: CropRegion | None = None
    dense_ranges: list[DenseRange] = field(default_factory=list)
    dense_start_seconds: float | None = None
    dense_end_seconds: float | None = None
    dense_interval_seconds: float | None = None
    click_events_path: Path | None = None
    draw_click_markers: bool = False
    click_match_window_seconds: float = 0.5


@dataclass(slots=True)
class FramePlanEntry:
    index: int
    seconds: float
    timestamp: str
    is_dense: bool
    sheet_index: int
    sheet_row: int
    sheet_col: int
    event_type: str = ""
    event_id: str = ""
    source_index: int = 0
    click_x: float | None = None
    click_y: float | None = None
    selection_reason: str = ""
    cluster_index: int = 0
    cluster_size: int = 0
    visual_diff: float | None = None


@dataclass(slots=True)
class FrameSamplerEstimate:
    duration_seconds: float
    effective_start_seconds: float
    effective_end_seconds: float
    frame_count: int
    sheet_count: int
    frames_per_sheet: int
    estimated_processing_seconds: float
    estimated_output_mb: float


@dataclass(slots=True)
class FrameSamplerResult:
    output_dir: Path
    sheets_dir: Path
    sheet_paths: list[Path]
    index_csv: Path
    report_html: Path
    config_json: Path
    estimate: FrameSamplerEstimate


ProgressCallback = Callable[[int, int, str], None]
