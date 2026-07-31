from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import ClickKeyframeConfig


CLICK_SUMMARY_POLICY_ID = "CLICK_SUMMARY_V1"
CLICK_SUMMARY_SILENT_INTERVAL_SECONDS = 10.0


def click_summary_policy() -> dict[str, Any]:
    return {
        "id": CLICK_SUMMARY_POLICY_ID,
        "time_dedupe_seconds": 1.5,
        "distance_dedupe_px": 80.0,
        "visual_change_threshold": 0.22,
        "cluster_tail_min_size": 5,
        "cluster_tail_min_duration_seconds": 2.0,
        "silent_gap_seconds": CLICK_SUMMARY_SILENT_INTERVAL_SECONDS,
        "silent_long_gap_seconds": 25.0,
        "silent_max_frames_per_gap": 5,
        "include_double_clicks": False,
        "include_drag_events": False,
        "max_frames": 0,
    }


def build_click_summary_config(
    video_path: Path,
    events_path: Path,
    output_dir: Path,
    *,
    output_basename: str = "keyframes_click_sheet",
) -> ClickKeyframeConfig:
    policy = click_summary_policy()
    return ClickKeyframeConfig(
        video_path=video_path,
        events_path=events_path,
        output_dir=output_dir,
        max_frames=int(policy["max_frames"]),
        sheet_cols=5,
        sheet_rows=6,
        thumb_width=320,
        time_dedupe_seconds=float(policy["time_dedupe_seconds"]),
        distance_dedupe_px=float(policy["distance_dedupe_px"]),
        visual_change_threshold=float(policy["visual_change_threshold"]),
        cluster_tail_min_size=int(policy["cluster_tail_min_size"]),
        cluster_tail_min_duration_seconds=float(policy["cluster_tail_min_duration_seconds"]),
        silent_gap_seconds=float(policy["silent_gap_seconds"]),
        silent_long_gap_seconds=float(policy["silent_long_gap_seconds"]),
        silent_max_frames_per_gap=int(policy["silent_max_frames_per_gap"]),
        include_double_clicks=bool(policy["include_double_clicks"]),
        include_drag_events=bool(policy["include_drag_events"]),
        show_timestamp=True,
        show_index=True,
        draw_click_markers=True,
        output_basename=output_basename,
    )
