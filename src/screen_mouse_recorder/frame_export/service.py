from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import time

from PIL import Image

from ..naming import compact_timecode, default_frame_export_output_dir
from .click_keyframes import (
    _add_silent_gap_keyframes,
    _frame_overlay_config,
    _nearest_click_marker,
    _visual_signature_events,
    build_click_keyframe_plan,
    build_click_keyframe_visual_signatures,
    load_click_keyframe_events,
    load_click_markers,
    select_click_keyframes_with_stats,
)
from .ffmpeg_io import _extract_frame, probe_video, resolve_ffmpeg
from .models import (
    ClickKeyframeConfig,
    ClickKeyframeEstimate,
    ClickKeyframeResult,
    ClickMarker,
    CropRegion,
    FrameSamplerConfig,
    FrameSamplerResult,
    ProgressCallback,
)
from .outputs import (
    _cleanup_click_keyframe_outputs,
    _write_click_keyframe_index_json,
    _write_config_json,
    _write_index_csv,
    _write_report_html,
)
from .planner import build_frame_plan, estimate_sampling
from .renderer import _compose_sheet, _draw_click_marker, _prepare_frame_image
from .timecode import format_timecode


def default_output_dir(
    video_path: Path,
    output_root: Path,
    *,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    mode: str = "interval",
    crop: CropRegion | None = None,
    unique: bool = True,
) -> Path:
    return default_frame_export_output_dir(
        video_path,
        output_root,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        mode=mode,
        crop=crop,
        unique=unique,
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
    custom_basename = str(config.output_basename or "").strip()
    sheets_dir = output_dir if custom_basename else output_dir / "sheets"
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
            _draw_click_marker(image, click_position)
            thumbs.append(image)
        sheet_image = _compose_sheet(thumbs, sheet_entries, config)
        first = compact_timecode(sheet_entries[0].seconds)
        last = compact_timecode(sheet_entries[-1].seconds)
        suffix = "png" if output_format == "png" else "jpg"
        if custom_basename:
            if len(plan) <= frames_per_sheet:
                sheet_path = sheets_dir / f"{custom_basename}.{suffix}"
            else:
                sheet_path = sheets_dir / f"{custom_basename}_{sheet_entries[0].sheet_index:03d}.{suffix}"
        else:
            sheet_path = sheets_dir / f"sheet_{sheet_entries[0].sheet_index:03d}_{first}-{last}.{suffix}"
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
    index_csv = output_dir / (f"{custom_basename}_index.csv" if custom_basename else "index.csv")
    _write_index_csv(index_csv, plan, sheet_paths)
    config_json = output_dir / (f"{custom_basename}_manifest.json" if custom_basename else "manifest.json")
    _write_config_json(config_json, config, video_info, estimate)
    report_html = output_dir / (f"{custom_basename}_preview.html" if custom_basename else "preview.html")
    _write_report_html(report_html, config, video_info, estimate, sheet_paths, time.perf_counter() - start_time)

    if progress:
        progress(total, total, "完成")
    return FrameSamplerResult(output_dir, sheets_dir, sheet_paths, index_csv, report_html, config_json, estimate)


def estimate_click_keyframe_sampling(config: ClickKeyframeConfig) -> ClickKeyframeEstimate:
    events = load_click_keyframe_events(config)
    selection = select_click_keyframes_with_stats(events, config)
    frames_per_sheet = max(1, int(config.sheet_cols) * int(config.sheet_rows))
    sheet_count = (len(selection.events) + frames_per_sheet - 1) // frames_per_sheet if selection.events else 0
    visual_signature_frames = int(selection.stats.get("visual_signature_frames") or 0)
    signature_ids = {event.event_id for event in _visual_signature_events(events, config)}
    cached_frame_reuses = sum(1 for event in selection.events if event.event_id in signature_ids)
    estimated_frame_extractions = len(selection.events) + visual_signature_frames - cached_frame_reuses
    estimated_seconds = max(1, estimated_frame_extractions) * 0.3
    return ClickKeyframeEstimate(
        events_total=len(events),
        events_kept=len(selection.events),
        events_skipped=selection.skipped_count,
        sheet_count=sheet_count,
        frames_per_sheet=frames_per_sheet,
        estimated_processing_seconds=estimated_seconds,
        visual_signature_frames=visual_signature_frames,
        cached_frame_reuses=cached_frame_reuses,
        estimated_frame_extractions=estimated_frame_extractions,
        timeline_start_seconds=events[0].seconds if events else 0.0,
        timeline_end_seconds=events[-1].seconds if events else 0.0,
    )


def run_frame_export(
    config: FrameSamplerConfig | ClickKeyframeConfig,
    ffmpeg_path: str | None = None,
    progress: ProgressCallback | None = None,
) -> FrameSamplerResult | ClickKeyframeResult:
    if isinstance(config, ClickKeyframeConfig):
        return generate_click_keyframe_sheets(config, ffmpeg_path, progress)
    return sample_video_to_sheets(config, ffmpeg_path, progress)


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
    frame_cache_temp = TemporaryDirectory(prefix="click_frame_cache_", dir=output_dir)
    frame_cache: dict[str, Path] = {}
    visual_signatures = build_click_keyframe_visual_signatures(
        events,
        config,
        video_info,
        ffmpeg,
        progress,
        frame_cache=frame_cache,
        frame_cache_dir=Path(frame_cache_temp.name),
    )
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
        frame_cache_temp.cleanup()
        return ClickKeyframeResult(output_dir, [], index_json, len(events), 0, skipped, ["无点击事件"])

    valid_events = []
    for event in selected:
        if event.seconds > video_info.duration_seconds + 0.25:
            skipped += 1
            warnings.append(f"跳过超出视频时长的事件 {event.event_id}: {format_timecode(event.seconds)}")
            continue
        valid_events.append(event)
    valid_events = _add_silent_gap_keyframes(valid_events, config, video_info, selection)
    plan = build_click_keyframe_plan(valid_events, config, video_info, selection)
    if not plan:
        index_json = output_dir / f"{config.output_basename}_index.json"
        _write_click_keyframe_index_json(index_json, [], [], len(events), skipped, warnings, selection_stats=selection.stats)
        frame_cache_temp.cleanup()
        return ClickKeyframeResult(output_dir, [], index_json, len(events), 0, skipped, warnings)

    sheet_paths: list[Path] = []
    cache_reuses = 0
    frames_per_sheet = max(1, int(config.sheet_cols) * int(config.sheet_rows))
    total = len(plan)
    for sheet_offset in range(0, total, frames_per_sheet):
        sheet_entries = plan[sheet_offset : sheet_offset + frames_per_sheet]
        thumbs: list[Image.Image] = []
        for entry in sheet_entries:
            if progress:
                progress(entry.index, total, f"关键帧 {entry.timestamp}")
            cache_path = frame_cache.get(entry.event_id)
            if cache_path is not None:
                with Image.open(cache_path) as cached:
                    image = cached.convert("RGB")
                cache_reuses += 1
            else:
                image = _extract_frame(ffmpeg, config.video_path, entry.seconds)
            marker = None
            if config.draw_click_markers and entry.click_x is not None and entry.click_y is not None:
                marker = ClickMarker(entry.seconds, entry.click_x, entry.click_y)
            image, click_position = _prepare_frame_image(image, None, config.thumb_width, marker)
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

    selection.stats["frame_cache_reuses"] = cache_reuses
    selection.stats["actual_frame_extractions"] = len(visual_signatures) + total - cache_reuses
    index_json = output_dir / f"{config.output_basename}_index.json"
    _write_click_keyframe_index_json(index_json, plan, sheet_paths, len(events), skipped, warnings, selection_stats=selection.stats)
    frame_cache_temp.cleanup()
    if progress:
        progress(total, total, "完成")
    return ClickKeyframeResult(output_dir, sheet_paths, index_json, len(events), len(plan), skipped, warnings)


def _normalized_output_format(value: str) -> str:
    return "png" if str(value).strip().lower() == "png" else "jpg"
