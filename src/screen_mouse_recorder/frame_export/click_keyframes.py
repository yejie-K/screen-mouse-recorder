from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PIL import Image

from .ffmpeg_io import _extract_frame
from .models import (
    ClickKeyframeConfig,
    ClickKeyframeEvent,
    ClickKeyframeSelection,
    ClickMarker,
    ClickVisualSignature,
    FramePlanEntry,
    FrameSamplerConfig,
    ProgressCallback,
    VideoInfo,
)
from .timecode import format_timecode, parse_timecode


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
    visual_signature_frames = sum(len(cluster) for cluster in clusters if len(cluster) > 2)

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
        "visual_signature_frames": visual_signature_frames if visual_threshold > 0 else 0,
        "cluster_tail_kept": cluster_tail_kept,
        "cluster_time_seconds": max(0.0, float(config.time_dedupe_seconds)),
        "cluster_distance_px": max(0.0, float(config.distance_dedupe_px)),
        "cluster_tail_min_size": tail_min_size,
        "cluster_tail_min_duration_seconds": tail_min_duration,
        "visual_change_threshold": visual_threshold,
        "visual_sample_size": max(8, int(config.visual_sample_size)),
        "visual_crop_radius_px": max(0, int(config.visual_crop_radius_px)),
        "max_frames": max(0, int(config.max_frames)),
        "cap_strategy": "uniform_timeline" if cap_skipped else "none",
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
    *,
    frame_cache: dict[str, Path] | None = None,
    frame_cache_dir: Path | None = None,
) -> dict[str, ClickVisualSignature]:
    events_to_sample = _visual_signature_events(events, config)
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
            if frame_cache is not None and frame_cache_dir is not None:
                frame_cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path = frame_cache_dir / f"frame_{index:06d}.jpg"
                image.save(cache_path, "JPEG", quality=92, optimize=False)
                frame_cache[event.event_id] = cache_path
        finally:
            image.close()
    return signatures


def _visual_signature_events(
    events: list[ClickKeyframeEvent],
    config: ClickKeyframeConfig,
) -> list[ClickKeyframeEvent]:
    if float(config.visual_change_threshold) <= 0:
        return []
    return [
        event
        for cluster in _cluster_click_keyframe_events(events, config)
        if len(cluster) > 2
        for event in cluster
    ]

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
    if max_frames == 1:
        selected = [events[len(events) // 2]]
    else:
        last_index = len(events) - 1
        indices = [round(position * last_index / (max_frames - 1)) for position in range(max_frames)]
        selected = [events[index] for index in indices]
    return selected, len(events) - len(selected)

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
    frame_cap = max(0, int(config.max_frames))
    remaining_budget = max(0, frame_cap - len(sorted_events)) if frame_cap else None
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
        if remaining_budget is not None and remaining_budget <= 0:
            break
        gap = max(0.0, end - start)
        if gap < gap_threshold:
            continue
        gaps_total += 1
        count = min(max_per_gap, max(1, math.ceil(gap / gap_threshold) - 1))
        if remaining_budget is not None:
            count = min(count, remaining_budget)
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
        if remaining_budget is not None:
            remaining_budget -= count

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
    pixels = sampled.get_flattened_data() if hasattr(sampled, "get_flattened_data") else sampled.getdata()
    return tuple(int(value) for value in pixels)

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

def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

