from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from html import escape
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont


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
    output_basename: str = "click_keyframes"


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
class FrameSamplerConfig:
    video_path: Path
    output_dir: Path
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


def parse_timecode(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return max(0.0, float(text))
    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid timecode: {value}")
    numbers = [float(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        return max(0.0, minutes * 60 + seconds)
    hours, minutes, seconds = numbers
    return max(0.0, hours * 3600 + minutes * 60 + seconds)


def format_timecode(seconds: float, *, filename_safe: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis >= 1000:
        whole += 1
        millis -= 1000
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    if millis:
        text = f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    else:
        text = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return text.replace(":", "-").replace(".", "-") if filename_safe else text


def default_output_dir(
    video_path: Path,
    output_root: Path,
    *,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    unique: bool = True,
) -> Path:
    safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", video_path.parent.name).strip("._-") or video_path.stem or "video"
    range_text = f"{_compact_timecode(start_seconds)}-{_compact_timecode(end_seconds)}"
    index = 1
    while True:
        candidate = output_root / f"{safe_name}_抽帧{index}（{range_text}）"
        if not unique or not candidate.exists():
            return candidate
        index += 1


def _compact_timecode(seconds: float | None) -> str:
    if seconds is None:
        return "end"
    seconds = max(0.0, float(seconds))
    whole = int(round(seconds))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}{minutes:02d}{secs:02d}"


def resolve_ffmpeg(ffmpeg_path: str | None = None) -> str:
    if ffmpeg_path:
        path = Path(ffmpeg_path)
        if path.exists():
            return str(path)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError("FFmpeg not found. Configure ffmpeg_path in config.json or add ffmpeg.exe to PATH.")


def resolve_ffprobe(ffmpeg_path: str | None = None) -> str:
    if ffmpeg_path:
        ffmpeg = Path(ffmpeg_path)
        candidate = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe")
        if candidate.exists():
            return str(candidate)
    found = shutil.which("ffprobe")
    if found:
        return found
    raise FileNotFoundError("ffprobe not found next to ffmpeg.exe or on PATH.")


def probe_video(video_path: Path, ffmpeg_path: str | None = None) -> VideoInfo:
    video_path = video_path.resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    ffprobe = resolve_ffprobe(ffmpeg_path)
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,duration",
        "-show_entries",
        "format=duration,size",
        "-of",
        "json",
        str(video_path),
    ]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **_hidden_subprocess_kwargs(),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffprobe failed")
    data = json.loads(proc.stdout)
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    duration = float(stream.get("duration") or fmt.get("duration") or 0)
    file_size = int(fmt.get("size") or video_path.stat().st_size)
    fps = _parse_fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    if width <= 0 or height <= 0 or duration <= 0:
        raise RuntimeError(f"Could not read video metadata for {video_path}")
    return VideoInfo(video_path, duration, width, height, fps, file_size)


def build_frame_plan(config: FrameSamplerConfig, video_info: VideoInfo) -> list[FramePlanEntry]:
    start = max(0.0, config.start_seconds)
    end = min(video_info.duration_seconds, config.end_seconds if config.end_seconds is not None else video_info.duration_seconds)
    if end < start:
        raise ValueError("End time must be greater than start time.")
    interval = max(0.1, config.interval_seconds)
    times: dict[int, tuple[float, bool]] = {}

    current = start
    while current <= end + 0.0001:
        key = int(round(current * 1000))
        times[key] = (round(current, 3), False)
        current += interval

    dense_ranges = list(config.dense_ranges)
    if (
        config.dense_start_seconds is not None
        and config.dense_end_seconds is not None
        and config.dense_interval_seconds is not None
    ):
        dense_ranges.append(
            DenseRange(
                start_seconds=config.dense_start_seconds,
                end_seconds=config.dense_end_seconds,
                interval_seconds=config.dense_interval_seconds,
            )
        )

    for dense_range in dense_ranges:
        dense_start = max(start, dense_range.start_seconds)
        dense_end = min(end, dense_range.end_seconds)
        dense_interval = max(0.1, dense_range.interval_seconds)
        if dense_end < dense_start:
            continue
        current = dense_start
        while current <= dense_end + 0.0001:
            key = int(round(current * 1000))
            existing = times.get(key)
            times[key] = (round(current, 3), True if existing is None else existing[1] or True)
            current += dense_interval

    per_sheet = max(1, config.sheet_cols * config.sheet_rows)
    entries: list[FramePlanEntry] = []
    for index, (_key, (seconds, is_dense)) in enumerate(sorted(times.items()), start=1):
        zero_index = index - 1
        sheet_zero = zero_index // per_sheet
        position = zero_index % per_sheet
        entries.append(
            FramePlanEntry(
                index=index,
                seconds=seconds,
                timestamp=format_timecode(seconds),
                is_dense=is_dense,
                sheet_index=sheet_zero + 1,
                sheet_row=position // config.sheet_cols + 1,
                sheet_col=position % config.sheet_cols + 1,
            )
        )
    return entries


def estimate_sampling(config: FrameSamplerConfig, video_info: VideoInfo) -> FrameSamplerEstimate:
    plan = build_frame_plan(config, video_info)
    frames_per_sheet = max(1, config.sheet_cols * config.sheet_rows)
    sheet_count = math.ceil(len(plan) / frames_per_sheet) if plan else 0
    end = min(video_info.duration_seconds, config.end_seconds if config.end_seconds is not None else video_info.duration_seconds)
    # Conservative local estimate: one FFmpeg seek per frame plus Pillow composition/export.
    thumb_factor = max(0.65, config.thumb_width / 360)
    estimated_seconds = len(plan) * 0.28 * thumb_factor + sheet_count * 0.8
    estimated_mb = sheet_count * config.sheet_cols * config.sheet_rows * (config.thumb_width * 0.000018)
    return FrameSamplerEstimate(
        duration_seconds=video_info.duration_seconds,
        effective_start_seconds=max(0.0, config.start_seconds),
        effective_end_seconds=end,
        frame_count=len(plan),
        sheet_count=sheet_count,
        frames_per_sheet=frames_per_sheet,
        estimated_processing_seconds=estimated_seconds,
        estimated_output_mb=estimated_mb,
    )


def sample_video_to_sheets(
    config: FrameSamplerConfig,
    ffmpeg_path: str | None = None,
    progress: ProgressCallback | None = None,
) -> FrameSamplerResult:
    video_info = probe_video(config.video_path, ffmpeg_path)
    estimate = estimate_sampling(config, video_info)
    plan = build_frame_plan(config, video_info)
    if not plan:
        raise ValueError("No frames to sample.")

    ffmpeg = resolve_ffmpeg(ffmpeg_path)
    output_dir = config.output_dir.resolve()
    sheets_dir = output_dir / "sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)

    sheet_paths: list[Path] = []
    frames_per_sheet = max(1, config.sheet_cols * config.sheet_rows)
    total = len(plan)
    start_time = time.perf_counter()
    click_markers = load_click_markers(config.click_events_path) if config.draw_click_markers else []
    output_format = _normalized_output_format(config.output_format)

    for sheet_offset in range(0, total, frames_per_sheet):
        sheet_entries = plan[sheet_offset : sheet_offset + frames_per_sheet]
        thumbs: list[Image.Image] = []
        for entry in sheet_entries:
            if progress:
                progress(entry.index, total, f"抽帧 {entry.timestamp}")
            image = _extract_frame(ffmpeg, config.video_path, entry.seconds)
            click_marker = _nearest_click_marker(click_markers, entry.seconds, config.click_match_window_seconds)
            image, click_position = _prepare_frame_image(image, config.crop, config.thumb_width, click_marker)
            _draw_overlay(image, entry, config)
            _draw_click_marker(image, click_position)
            thumbs.append(image)
        sheet_image = _compose_sheet(thumbs, sheet_entries, config)
        first = format_timecode(sheet_entries[0].seconds, filename_safe=True)
        last = format_timecode(sheet_entries[-1].seconds, filename_safe=True)
        suffix = "png" if output_format == "png" else "jpg"
        sheet_path = sheets_dir / f"sheet_{sheet_entries[0].sheet_index:03d}_{first}_to_{last}.{suffix}"
        if output_format == "png":
            sheet_image.save(sheet_path, "PNG", optimize=True)
        else:
            sheet_image.save(sheet_path, "JPEG", quality=max(40, min(100, config.jpeg_quality)), optimize=True)
        sheet_paths.append(sheet_path)
        for thumb in thumbs:
            thumb.close()
        sheet_image.close()

    if progress:
        progress(total, total, "写入索引")
    index_csv = output_dir / "index.csv"
    _write_index_csv(index_csv, plan, sheet_paths)
    config_json = output_dir / "config.json"
    _write_config_json(config_json, config, video_info, estimate)
    report_html = output_dir / "report.html"
    _write_report_html(report_html, config, video_info, estimate, sheet_paths, time.perf_counter() - start_time)

    if progress:
        progress(total, total, "完成")
    return FrameSamplerResult(output_dir, sheets_dir, sheet_paths, index_csv, report_html, config_json, estimate)


def load_click_keyframe_events(config: ClickKeyframeConfig) -> list[ClickKeyframeEvent]:
    if not config.events_path.exists():
        return []
    accepted = {"click"}
    if config.include_double_clicks:
        accepted.add("double_click_candidate")
    if config.include_drag_events:
        accepted.update({"drag_start", "drag_end"})

    events: list[ClickKeyframeEvent] = []
    with config.events_path.open("r", encoding="utf-8-sig") as handle:
        for source_index, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = str(row.get("event_type", ""))
            if event_type not in accepted:
                continue
            seconds = _row_video_seconds(row)
            if seconds is None:
                continue
            x = _safe_float(row.get("video_x"))
            y = _safe_float(row.get("video_y"))
            event_id = str(row.get("event_id") or f"row_{source_index:06d}")
            events.append(ClickKeyframeEvent(source_index, seconds, event_type, event_id, x, y))
    events.sort(key=lambda event: (event.seconds, event.source_index))
    return events


def select_click_keyframes(events: list[ClickKeyframeEvent], config: ClickKeyframeConfig) -> tuple[list[ClickKeyframeEvent], int]:
    selection = select_click_keyframes_with_stats(events, config)
    return selection.events, selection.skipped_count


def select_click_keyframes_with_stats(
    events: list[ClickKeyframeEvent],
    config: ClickKeyframeConfig,
    visual_signatures: dict[str, ClickVisualSignature] | None = None,
) -> ClickKeyframeSelection:
    clusters = _cluster_click_keyframe_events(events, config)
    selected: list[ClickKeyframeEvent] = []
    reasons_by_event_id: dict[str, str] = {}
    cluster_by_event_id: dict[str, int] = {}
    cluster_size_by_event_id: dict[str, int] = {}
    visual_diff_by_event_id: dict[str, float] = {}
    skipped_duplicate = 0
    visual_kept = 0
    cluster_tail_kept = 0
    repeated_clusters = 0
    visual_threshold = max(0.0, float(config.visual_change_threshold))
    tail_min_size = max(2, int(config.cluster_tail_min_size))
    tail_min_duration = max(0.0, float(config.cluster_tail_min_duration_seconds))

    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster_size = len(cluster)
        if cluster_size > 1:
            repeated_clusters += 1
        keep_ids: set[str] = set()
        keep_reasons: dict[str, str] = {}
        if cluster_size == 1:
            event = cluster[0]
            keep_ids.add(event.event_id)
            keep_reasons[event.event_id] = "single"
        else:
            first = cluster[0]
            last = cluster[-1]
            cluster_duration = max(0.0, last.seconds - first.seconds)
            keep_tail = cluster_size >= tail_min_size or cluster_duration >= tail_min_duration
            keep_ids.add(first.event_id)
            keep_reasons[first.event_id] = "cluster_start"
            previous_signature = visual_signatures.get(first.event_id) if visual_signatures else None
            for event in cluster[1:]:
                if event.event_id == last.event_id and keep_tail:
                    continue
                current_signature = visual_signatures.get(event.event_id) if visual_signatures else None
                visual_diff = (
                    _visual_signature_difference(previous_signature, current_signature)
                    if previous_signature is not None and current_signature is not None
                    else 0.0
                )
                if current_signature is not None:
                    visual_diff_by_event_id[event.event_id] = round(visual_diff, 4)
                if visual_threshold > 0 and visual_diff >= visual_threshold:
                    keep_ids.add(event.event_id)
                    keep_reasons[event.event_id] = "visual_change"
                    previous_signature = current_signature
                    visual_kept += 1
            if keep_tail and last.event_id not in keep_ids:
                last_signature = visual_signatures.get(last.event_id) if visual_signatures else None
                last_diff = (
                    _visual_signature_difference(previous_signature, last_signature)
                    if previous_signature is not None and last_signature is not None
                    else 0.0
                )
                if last_signature is not None:
                    visual_diff_by_event_id[last.event_id] = round(last_diff, 4)
                keep_ids.add(last.event_id)
                keep_reasons[last.event_id] = "cluster_end"
                cluster_tail_kept += 1

        for event in cluster:
            cluster_by_event_id[event.event_id] = cluster_index
            cluster_size_by_event_id[event.event_id] = cluster_size
            if event.event_id in keep_ids:
                selected.append(event)
                reasons_by_event_id[event.event_id] = keep_reasons.get(event.event_id, "selected")
            else:
                skipped_duplicate += 1

    capped_selected, cap_skipped = _apply_click_keyframe_cap(selected, config)
    if cap_skipped:
        capped_ids = {event.event_id for event in capped_selected}
        for event in selected:
            if event.event_id not in capped_ids:
                reasons_by_event_id.pop(event.event_id, None)

    skipped_count = skipped_duplicate + cap_skipped
    stats = {
        "strategy": "cluster_head_tail_for_large_clusters_plus_visual_change",
        "events_total": len(events),
        "events_kept": len(capped_selected),
        "events_skipped": skipped_count,
        "duplicate_skipped": skipped_duplicate,
        "cap_skipped": cap_skipped,
        "clusters_total": len(clusters),
        "repeated_clusters": repeated_clusters,
        "visual_change_kept": visual_kept,
        "cluster_tail_kept": cluster_tail_kept,
        "cluster_time_seconds": max(0.0, float(config.time_dedupe_seconds)),
        "cluster_distance_px": max(0.0, float(config.distance_dedupe_px)),
        "cluster_tail_min_size": tail_min_size,
        "cluster_tail_min_duration_seconds": tail_min_duration,
        "visual_change_threshold": visual_threshold,
        "visual_sample_size": max(8, int(config.visual_sample_size)),
        "visual_crop_radius_px": max(0, int(config.visual_crop_radius_px)),
        "max_frames": max(0, int(config.max_frames)),
        "selection_reason_counts": _selection_reason_counts(reasons_by_event_id),
    }
    return ClickKeyframeSelection(
        capped_selected,
        skipped_count,
        reasons_by_event_id,
        cluster_by_event_id,
        cluster_size_by_event_id,
        visual_diff_by_event_id,
        stats,
    )


def build_click_keyframe_visual_signatures(
    events: list[ClickKeyframeEvent],
    config: ClickKeyframeConfig,
    video_info: VideoInfo,
    ffmpeg: str,
    progress: ProgressCallback | None = None,
) -> dict[str, ClickVisualSignature]:
    clusters = _cluster_click_keyframe_events(events, config)
    events_to_sample = [event for cluster in clusters if len(cluster) > 2 for event in cluster]
    signatures: dict[str, ClickVisualSignature] = {}
    total = len(events_to_sample)
    if not total or float(config.visual_change_threshold) <= 0:
        return signatures
    offset = max(0.0, float(config.frame_offset_seconds))
    for index, event in enumerate(events_to_sample, start=1):
        if progress:
            progress(0, 0, f"去重分析 {index}/{total}")
        seconds = min(video_info.duration_seconds, max(0.0, event.seconds + offset))
        image = _extract_frame(ffmpeg, config.video_path, seconds)
        try:
            signatures[event.event_id] = _click_visual_signature(image, event, config)
        finally:
            image.close()
    return signatures


def _cluster_click_keyframe_events(
    events: list[ClickKeyframeEvent],
    config: ClickKeyframeConfig,
) -> list[list[ClickKeyframeEvent]]:
    if not events:
        return []
    time_threshold = max(0.0, float(config.time_dedupe_seconds))
    distance_threshold = max(0.0, float(config.distance_dedupe_px))
    if time_threshold <= 0 or distance_threshold <= 0:
        return [[event] for event in events]

    clusters: list[list[ClickKeyframeEvent]] = []
    current: list[ClickKeyframeEvent] = [events[0]]
    for event in events[1:]:
        previous = current[-1]
        if _is_near_duplicate_click(previous, event, time_threshold, distance_threshold):
            current.append(event)
        else:
            clusters.append(current)
            current = [event]
    clusters.append(current)
    return clusters


def _apply_click_keyframe_cap(
    events: list[ClickKeyframeEvent],
    config: ClickKeyframeConfig,
) -> tuple[list[ClickKeyframeEvent], int]:
    max_frames = max(0, int(config.max_frames))
    if not max_frames or len(events) <= max_frames:
        return events, 0
    return events[:max_frames], len(events) - max_frames


def _selection_reason_counts(reasons_by_event_id: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in reasons_by_event_id.values():
        key = reason or "selected"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _add_silent_gap_keyframes(
    events: list[ClickKeyframeEvent],
    config: ClickKeyframeConfig,
    video_info: VideoInfo,
    selection: ClickKeyframeSelection,
) -> list[ClickKeyframeEvent]:
    gap_threshold = max(0.0, float(config.silent_gap_seconds))
    if gap_threshold <= 0:
        selection.stats["silent_gap_enabled"] = False
        selection.stats["timeline_max_gap_before_seconds"] = round(_timeline_max_gap(events, video_info.duration_seconds), 3)
        selection.stats["timeline_max_gap_after_seconds"] = selection.stats["timeline_max_gap_before_seconds"]
        selection.stats["silent_gap_frames_added"] = 0
        selection.stats["events_kept_with_silent_gaps"] = len(events)
        selection.stats["selection_reason_counts"] = _selection_reason_counts(selection.reasons_by_event_id)
        return events

    sorted_events = sorted(events, key=lambda event: (event.seconds, event.source_index))
    long_gap_threshold = max(gap_threshold, float(config.silent_long_gap_seconds))
    max_per_gap = max(1, int(config.silent_max_frames_per_gap))
    added: list[ClickKeyframeEvent] = []
    gaps_total = 0

    anchors: list[tuple[float, float]] = []
    if sorted_events:
        first_time = sorted_events[0].seconds
        if first_time > gap_threshold:
            anchors.append((0.0, first_time))
        for previous, current in zip(sorted_events, sorted_events[1:]):
            anchors.append((previous.seconds, current.seconds))
        last_time = sorted_events[-1].seconds
        if video_info.duration_seconds - last_time > gap_threshold:
            anchors.append((last_time, video_info.duration_seconds))
    elif video_info.duration_seconds > gap_threshold:
        anchors.append((0.0, video_info.duration_seconds))

    for start, end in anchors:
        gap = max(0.0, end - start)
        if gap < gap_threshold:
            continue
        gaps_total += 1
        count = min(max_per_gap, max(1, math.ceil(gap / gap_threshold) - 1))
        positions = (
            [start + gap / 2]
            if count == 1
            else [start + gap * (index + 1) / (count + 1) for index in range(count)]
        )
        for index, seconds in enumerate(positions, start=1):
            event_id = f"silent_{int(round(start * 1000))}_{int(round(end * 1000))}_{index}"
            event = ClickKeyframeEvent(
                source_index=0,
                seconds=round(min(video_info.duration_seconds, max(0.0, seconds)), 3),
                event_type="silent_gap",
                event_id=event_id,
                x=None,
                y=None,
            )
            added.append(event)
            selection.reasons_by_event_id[event_id] = "silent_gap"
            selection.cluster_by_event_id[event_id] = 0
            selection.cluster_size_by_event_id[event_id] = 0

    combined = sorted(sorted_events + added, key=lambda event: (event.seconds, event.source_index, event.event_id))
    selection.stats["silent_gap_enabled"] = True
    selection.stats["silent_gap_seconds"] = gap_threshold
    selection.stats["silent_long_gap_seconds"] = long_gap_threshold
    selection.stats["silent_max_frames_per_gap"] = max_per_gap
    selection.stats["silent_gaps_total"] = gaps_total
    selection.stats["silent_gap_frames_added"] = len(added)
    selection.stats["timeline_max_gap_before_seconds"] = round(_timeline_max_gap(sorted_events, video_info.duration_seconds), 3)
    selection.stats["timeline_max_gap_after_seconds"] = round(_timeline_max_gap(combined, video_info.duration_seconds), 3)
    selection.stats["events_kept_with_silent_gaps"] = len(combined)
    selection.stats["selection_reason_counts"] = _selection_reason_counts(selection.reasons_by_event_id)
    return combined


def _timeline_max_gap(events: list[ClickKeyframeEvent], duration_seconds: float) -> float:
    duration = max(0.0, float(duration_seconds))
    times = [0.0] + [event.seconds for event in sorted(events, key=lambda event: event.seconds)] + [duration]
    if len(times) < 2:
        return duration
    return max(max(0.0, current - previous) for previous, current in zip(times, times[1:]))


def build_click_keyframe_plan(
    events: list[ClickKeyframeEvent],
    config: ClickKeyframeConfig,
    video_info: VideoInfo,
    selection: ClickKeyframeSelection | None = None,
) -> list[FramePlanEntry]:
    cols = max(1, int(config.sheet_cols))
    rows = max(1, int(config.sheet_rows))
    per_sheet = cols * rows
    offset = max(0.0, float(config.frame_offset_seconds))
    plan: list[FramePlanEntry] = []
    for index, event in enumerate(events, start=1):
        seconds = min(video_info.duration_seconds, max(0.0, event.seconds + offset))
        zero_index = index - 1
        sheet_zero = zero_index // per_sheet
        position = zero_index % per_sheet
        plan.append(
            FramePlanEntry(
                index=index,
                seconds=round(seconds, 3),
                timestamp=format_timecode(seconds),
                is_dense=True,
                sheet_index=sheet_zero + 1,
                sheet_row=position // cols + 1,
                sheet_col=position % cols + 1,
                event_type=event.event_type,
                event_id=event.event_id,
                source_index=event.source_index,
                click_x=event.x,
                click_y=event.y,
                selection_reason=selection.reasons_by_event_id.get(event.event_id, "") if selection else "",
                cluster_index=selection.cluster_by_event_id.get(event.event_id, 0) if selection else 0,
                cluster_size=selection.cluster_size_by_event_id.get(event.event_id, 0) if selection else 0,
                visual_diff=selection.visual_diff_by_event_id.get(event.event_id) if selection else None,
            )
        )
    return plan


def generate_click_keyframe_sheets(
    config: ClickKeyframeConfig,
    ffmpeg_path: str | None = None,
    progress: ProgressCallback | None = None,
) -> ClickKeyframeResult:
    video_info = probe_video(config.video_path, ffmpeg_path)
    ffmpeg = resolve_ffmpeg(ffmpeg_path)
    output_dir = config.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    _cleanup_click_keyframe_outputs(output_dir, config.output_basename)

    events = load_click_keyframe_events(config)
    visual_signatures = build_click_keyframe_visual_signatures(events, config, video_info, ffmpeg, progress)
    selection = select_click_keyframes_with_stats(events, config, visual_signatures)
    selected = selection.events
    skipped = selection.skipped_count
    if not selected:
        index_json = output_dir / f"{config.output_basename}_index.json"
        _write_click_keyframe_index_json(
            index_json,
            [],
            [],
            events_total=len(events),
            events_skipped=skipped,
            warnings=["无点击事件"],
            selection_stats=selection.stats,
        )
        return ClickKeyframeResult(output_dir, [], index_json, len(events), 0, skipped, ["无点击事件"])

    valid_events: list[ClickKeyframeEvent] = []
    for event in selected:
        if event.seconds > video_info.duration_seconds + 0.25:
            skipped += 1
            warnings.append(f"跳过超出视频时长的事件 {event.event_id}：{format_timecode(event.seconds)}")
            continue
        valid_events.append(event)
    valid_events = _add_silent_gap_keyframes(valid_events, config, video_info, selection)
    plan = build_click_keyframe_plan(valid_events, config, video_info, selection)
    if not plan:
        index_json = output_dir / f"{config.output_basename}_index.json"
        _write_click_keyframe_index_json(index_json, [], [], len(events), skipped, warnings, selection_stats=selection.stats)
        return ClickKeyframeResult(output_dir, [], index_json, len(events), 0, skipped, warnings)

    sheet_paths: list[Path] = []
    frames_per_sheet = max(1, int(config.sheet_cols) * int(config.sheet_rows))
    total = len(plan)
    for sheet_offset in range(0, total, frames_per_sheet):
        sheet_entries = plan[sheet_offset : sheet_offset + frames_per_sheet]
        thumbs: list[Image.Image] = []
        for entry in sheet_entries:
            if progress:
                progress(entry.index, total, f"关键帧 {entry.timestamp}")
            image = _extract_frame(ffmpeg, config.video_path, entry.seconds)
            marker = None
            if config.draw_click_markers and entry.click_x is not None and entry.click_y is not None:
                marker = ClickMarker(entry.seconds, entry.click_x, entry.click_y)
            image, click_position = _prepare_frame_image(image, None, config.thumb_width, marker)
            _draw_overlay(image, entry, _frame_overlay_config(config))
            _draw_click_marker(image, click_position)
            thumbs.append(image)
        sheet_image = _compose_sheet(thumbs, sheet_entries, _frame_overlay_config(config))
        if len(plan) <= frames_per_sheet:
            sheet_path = output_dir / f"{config.output_basename}.png"
        else:
            sheet_path = output_dir / f"{config.output_basename}_{sheet_entries[0].sheet_index:03d}.png"
        sheet_image.save(sheet_path, "PNG", optimize=True)
        sheet_paths.append(sheet_path)
        for thumb in thumbs:
            thumb.close()
        sheet_image.close()

    index_json = output_dir / f"{config.output_basename}_index.json"
    _write_click_keyframe_index_json(index_json, plan, sheet_paths, len(events), skipped, warnings, selection_stats=selection.stats)
    if progress:
        progress(total, total, "完成")
    return ClickKeyframeResult(output_dir, sheet_paths, index_json, len(events), len(plan), skipped, warnings)


def extract_preview_frame(video_path: Path, ffmpeg_path: str | None = None, seconds: float = 0.0) -> Image.Image:
    ffmpeg = resolve_ffmpeg(ffmpeg_path)
    return _extract_frame(ffmpeg, video_path, seconds)


def load_click_markers(path: Path | None) -> list[ClickMarker]:
    if path is None:
        return []
    path = path.resolve()
    if not path.exists():
        return []
    markers: list[ClickMarker] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event_type") != "click":
                continue
            t_video_ms = _safe_float(row.get("t_video_ms"))
            x = _safe_float(row.get("video_x"))
            y = _safe_float(row.get("video_y"))
            if t_video_ms is None or x is None or y is None:
                continue
            markers.append(ClickMarker(seconds=t_video_ms / 1000, x=x, y=y))
    markers.sort(key=lambda marker: marker.seconds)
    return markers


def _row_video_seconds(row: dict[str, Any]) -> float | None:
    t_video_ms = _safe_float(row.get("t_video_ms"))
    if t_video_ms is not None:
        return max(0.0, t_video_ms / 1000)
    timecode = row.get("video_timecode")
    if timecode is not None:
        try:
            return parse_timecode(str(timecode))
        except (TypeError, ValueError):
            return None
    return None


def _is_near_duplicate_click(
    previous: ClickKeyframeEvent,
    current: ClickKeyframeEvent,
    time_threshold: float,
    distance_threshold: float,
) -> bool:
    if current.seconds - previous.seconds > time_threshold:
        return False
    if previous.x is None or previous.y is None or current.x is None or current.y is None:
        return False
    distance = ((current.x - previous.x) ** 2 + (current.y - previous.y) ** 2) ** 0.5
    return distance <= distance_threshold


def _click_visual_signature(
    image: Image.Image,
    event: ClickKeyframeEvent,
    config: ClickKeyframeConfig,
) -> ClickVisualSignature:
    sample_size = max(8, int(config.visual_sample_size))
    grayscale = image.convert("L")
    global_pixels = _downsample_pixels(grayscale, sample_size)
    local_pixels = None
    radius = max(0, int(config.visual_crop_radius_px))
    if radius and event.x is not None and event.y is not None:
        left = max(0, int(round(event.x - radius)))
        top = max(0, int(round(event.y - radius)))
        right = min(grayscale.width, int(round(event.x + radius)))
        bottom = min(grayscale.height, int(round(event.y + radius)))
        if right > left and bottom > top:
            local_pixels = _downsample_pixels(grayscale.crop((left, top, right, bottom)), sample_size)
    return ClickVisualSignature(global_pixels=global_pixels, local_pixels=local_pixels)


def _downsample_pixels(image: Image.Image, sample_size: int) -> tuple[int, ...]:
    sampled = image.resize((sample_size, sample_size), Image.Resampling.BILINEAR)
    return tuple(int(value) for value in sampled.getdata())


def _visual_signature_difference(
    previous: ClickVisualSignature,
    current: ClickVisualSignature,
) -> float:
    global_diff = _pixel_mean_absolute_difference(previous.global_pixels, current.global_pixels)
    local_diff = 0.0
    if previous.local_pixels is not None and current.local_pixels is not None:
        local_diff = _pixel_mean_absolute_difference(previous.local_pixels, current.local_pixels)
    return max(global_diff, local_diff)


def _pixel_mean_absolute_difference(previous: tuple[int, ...], current: tuple[int, ...]) -> float:
    if not previous or not current:
        return 0.0
    count = min(len(previous), len(current))
    if count <= 0:
        return 0.0
    return sum(abs(previous[index] - current[index]) for index in range(count)) / (255 * count)


def _frame_overlay_config(config: ClickKeyframeConfig) -> FrameSamplerConfig:
    return FrameSamplerConfig(
        video_path=config.video_path,
        output_dir=config.output_dir,
        sheet_cols=config.sheet_cols,
        sheet_rows=config.sheet_rows,
        thumb_width=config.thumb_width,
        output_format="png",
        show_timestamp=config.show_timestamp,
        show_index=config.show_index,
    )


def _cleanup_click_keyframe_outputs(output_dir: Path, basename: str) -> None:
    for path in output_dir.glob(f"{basename}*.png"):
        try:
            path.unlink()
        except OSError:
            pass


def _write_click_keyframe_index_json(
    path: Path,
    plan: list[FramePlanEntry],
    sheet_paths: list[Path],
    events_total: int,
    events_skipped: int,
    warnings: list[str],
    selection_stats: dict[str, Any] | None = None,
) -> None:
    sheet_by_index = {index + 1: sheet_path.name for index, sheet_path in enumerate(sheet_paths)}
    payload = {
        "events_total": events_total,
        "events_kept": len(plan),
        "events_skipped": events_skipped,
        "warnings": warnings,
        "selection": selection_stats or {},
        "frames": [
            {
                "index": entry.index,
                "event_id": entry.event_id,
                "event_type": entry.event_type,
                "source_index": entry.source_index,
                "seconds": entry.seconds,
                "timestamp": entry.timestamp,
                "video_x": entry.click_x,
                "video_y": entry.click_y,
                "sheet": sheet_by_index.get(entry.sheet_index, ""),
                "sheet_row": entry.sheet_row,
                "sheet_col": entry.sheet_col,
                "selection_reason": entry.selection_reason,
                "cluster_index": entry.cluster_index,
                "cluster_size": entry.cluster_size,
                "visual_diff": entry.visual_diff,
            }
            for entry in plan
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _parse_fps(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    return float(value or 0)


def _extract_frame(ffmpeg: str, video_path: Path, seconds: float) -> Image.Image:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{seconds:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    proc = subprocess.run(command, capture_output=True, check=False, **_hidden_subprocess_kwargs())
    if proc.returncode != 0 or not proc.stdout:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"Failed to extract frame at {seconds:.3f}s")
    return Image.open(io.BytesIO(proc.stdout)).convert("RGB")


def _crop_and_resize(image: Image.Image, crop: CropRegion | None, thumb_width: int) -> Image.Image:
    image, _click_position = _prepare_frame_image(image, crop, thumb_width, None)
    return image


def _prepare_frame_image(
    image: Image.Image,
    crop: CropRegion | None,
    thumb_width: int,
    click_marker: ClickMarker | None,
) -> tuple[Image.Image, tuple[int, int] | None]:
    left, top, right, bottom = _crop_box(image, crop)
    click_position = _map_click_marker(click_marker, left, top, right, bottom, thumb_width)
    if (left, top, right, bottom) != (0, 0, image.width, image.height):
        image = image.crop((left, top, right, bottom))
    width = max(120, int(thumb_width))
    height = max(1, round(image.height * (width / image.width)))
    return image.resize((width, height), Image.Resampling.LANCZOS), click_position


def _crop_box(image: Image.Image, crop: CropRegion | None) -> tuple[int, int, int, int]:
    if crop is not None and crop.width > 0 and crop.height > 0:
        left = max(0, min(image.width - 1, crop.x))
        top = max(0, min(image.height - 1, crop.y))
        right = max(left + 1, min(image.width, left + crop.width))
        bottom = max(top + 1, min(image.height, top + crop.height))
        return left, top, right, bottom
    return 0, 0, image.width, image.height


def _map_click_marker(
    click_marker: ClickMarker | None,
    left: int,
    top: int,
    right: int,
    bottom: int,
    thumb_width: int,
) -> tuple[int, int] | None:
    if click_marker is None:
        return None
    if not (left <= click_marker.x <= right and top <= click_marker.y <= bottom):
        return None
    crop_width = max(1, right - left)
    scale = max(120, int(thumb_width)) / crop_width
    return round((click_marker.x - left) * scale), round((click_marker.y - top) * scale)


def _draw_overlay(image: Image.Image, entry: FramePlanEntry, config: FrameSamplerConfig) -> None:
    if not config.show_timestamp and not config.show_index:
        return
    draw = ImageDraw.Draw(image, "RGBA")
    font_size = max(13, min(24, image.width // 18))
    font = _load_font(font_size)
    lines: list[str] = []
    if config.show_index:
        lines.append(f"#{entry.index:03d}")
    if config.show_timestamp:
        lines.append(entry.timestamp)
    label = "  ".join(lines)
    bbox = draw.textbbox((0, 0), label, font=font)
    pad = max(5, font_size // 3)
    rect = (6, 6, 6 + (bbox[2] - bbox[0]) + pad * 2, 6 + (bbox[3] - bbox[1]) + pad * 2)
    fill = (0, 0, 0, 168 if not entry.is_dense else 196)
    draw.rounded_rectangle(rect, radius=5, fill=fill)
    draw.text((rect[0] + pad, rect[1] + pad), label, fill=(255, 255, 255, 255), font=font)
    if entry.is_dense:
        draw.rectangle((image.width - 8, 0, image.width, image.height), fill=(31, 111, 178, 190))


def _draw_click_marker(image: Image.Image, position: tuple[int, int] | None) -> None:
    if position is None:
        return
    x, y = position
    radius = max(7, min(14, image.width // 32))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2), fill=(255, 255, 255, 230))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(216, 59, 59, 220))
    inner = max(3, radius // 2)
    draw.ellipse((x - inner, y - inner, x + inner, y + inner), fill=(255, 255, 255, 120))


def _compose_sheet(images: list[Image.Image], entries: list[FramePlanEntry], config: FrameSamplerConfig) -> Image.Image:
    cols = max(1, config.sheet_cols)
    rows = max(1, config.sheet_rows)
    gap = 8
    header_h = 46
    thumb_w = max(image.width for image in images)
    thumb_h = max(image.height for image in images)
    canvas_w = cols * thumb_w + (cols + 1) * gap
    canvas_h = header_h + rows * thumb_h + (rows + 1) * gap
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#edf1f4")
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(18)
    title = f"Sheet {entries[0].sheet_index:03d}  {entries[0].timestamp} - {entries[-1].timestamp}"
    draw.text((gap, 12), title, fill="#17212b", font=title_font)
    for image, entry in zip(images, entries):
        row = entry.sheet_row - 1
        col = entry.sheet_col - 1
        x = gap + col * (thumb_w + gap)
        y = header_h + gap + row * (thumb_h + gap)
        canvas.paste(image, (x, y))
    return canvas


def _write_index_csv(path: Path, plan: list[FramePlanEntry], sheet_paths: list[Path]) -> None:
    sheet_by_index = {index + 1: sheet_path for index, sheet_path in enumerate(sheet_paths)}
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["帧序号", "视频时间戳", "秒数", "所属合成图", "合成图内行", "合成图内列", "是否关键段加密抽帧"])
        for entry in plan:
            writer.writerow(
                [
                    entry.index,
                    entry.timestamp,
                    f"{entry.seconds:.3f}",
                    sheet_by_index.get(entry.sheet_index, Path("")).name,
                    entry.sheet_row,
                    entry.sheet_col,
                    "是" if entry.is_dense else "否",
                ]
            )


def _write_config_json(path: Path, config: FrameSamplerConfig, video_info: VideoInfo, estimate: FrameSamplerEstimate) -> None:
    data = {
        "config": _jsonable(asdict(config)),
        "video": _jsonable(asdict(video_info)),
        "estimate": asdict(estimate),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_report_html(
    path: Path,
    config: FrameSamplerConfig,
    video_info: VideoInfo,
    estimate: FrameSamplerEstimate,
    sheet_paths: list[Path],
    elapsed_seconds: float,
) -> None:
    rows = [
        ("视频", str(video_info.path)),
        ("时长", format_timecode(video_info.duration_seconds)),
        ("分辨率", f"{video_info.width}x{video_info.height}"),
        ("抽帧范围", f"{format_timecode(estimate.effective_start_seconds)} - {format_timecode(estimate.effective_end_seconds)}"),
        ("抽帧间隔", f"{config.interval_seconds:g} 秒"),
        ("拼图布局", f"{config.sheet_cols} x {config.sheet_rows}"),
        ("抽帧数量", str(estimate.frame_count)),
        ("合成图数量", str(estimate.sheet_count)),
        ("实际耗时", f"{elapsed_seconds:.1f} 秒"),
    ]
    image_html = "\n".join(
        f'<section><h2>{escape(sheet.name)}</h2><a href="sheets/{escape(sheet.name)}"><img src="sheets/{escape(sheet.name)}" /></a></section>'
        for sheet in sheet_paths
    )
    metadata = "\n".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows)
    path.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>抽帧拼图报告</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; background: #edf1f4; color: #17212b; }}
    h1 {{ margin: 0 0 16px; font-size: 24px; }}
    h2 {{ margin: 24px 0 10px; font-size: 16px; }}
    table {{ border-collapse: collapse; margin-bottom: 18px; background: white; }}
    th, td {{ border: 1px solid #c7d0d8; padding: 8px 10px; text-align: left; }}
    th {{ width: 120px; background: #f8fafb; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #c7d0d8; background: white; }}
  </style>
</head>
<body>
  <h1>抽帧拼图报告</h1>
  <table>{metadata}</table>
  {image_html}
</body>
</html>
""",
        encoding="utf-8",
    )


def _nearest_click_marker(markers: list[ClickMarker], seconds: float, window_seconds: float) -> ClickMarker | None:
    if not markers:
        return None
    best_marker: ClickMarker | None = None
    best_delta = max(0.0, float(window_seconds))
    for marker in markers:
        delta = abs(marker.seconds - seconds)
        if delta <= best_delta:
            best_marker = marker
            best_delta = delta
        elif marker.seconds > seconds + best_delta:
            break
    return best_marker


def _normalized_output_format(value: str) -> str:
    return "png" if str(value).strip().lower() == "png" else "jpg"


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": creationflags} if creationflags else {}


def _jsonable(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf", "msyh.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()
