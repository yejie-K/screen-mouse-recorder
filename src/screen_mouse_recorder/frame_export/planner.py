from __future__ import annotations

import math

from .models import DenseRange, FramePlanEntry, FrameSamplerConfig, FrameSamplerEstimate, VideoInfo
from .timecode import format_timecode


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

