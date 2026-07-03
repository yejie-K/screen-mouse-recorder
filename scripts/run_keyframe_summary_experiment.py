from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from screen_mouse_recorder.frame_sampler import (  # noqa: E402
    ClickKeyframeConfig,
    VideoInfo,
    _add_silent_gap_keyframes,
    build_click_keyframe_plan,
    generate_click_keyframe_sheets,
    load_click_keyframe_events,
    probe_video,
    select_click_keyframes_with_stats,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the click keyframe summary experiment.")
    parser.add_argument(
        "--session",
        type=Path,
        default=ROOT / "sessions" / "20260610_163422",
        help="Session folder containing recording.mp4 and mouse_events.jsonl.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "test" / "keyframe_summary_90pct",
        help="Experiment output root.",
    )
    parser.add_argument("--first-minutes", type=float, default=0.0, help="Only use the first N minutes; 0 means full video.")
    parser.add_argument("--generate-sheets", action="store_true", help="Extract frames and write contact sheets.")
    parser.add_argument("--ffmpeg", type=str, default="", help="Override ffmpeg.exe path.")
    args = parser.parse_args()

    session_dir = args.session.resolve()
    source_video_path = session_dir / "recording.mp4"
    events_path = session_dir / "mouse_events.jsonl"
    if not source_video_path.exists():
        raise FileNotFoundError(source_video_path)
    if not events_path.exists():
        raise FileNotFoundError(events_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    range_label = f"first_{args.first_minutes:g}min" if args.first_minutes > 0 else "full"
    mode_label = "sheets" if args.generate_sheets else "metrics"
    run_dir = args.output_root.resolve() / f"run_{timestamp}_{range_label}_{mode_label}"
    run_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_path = args.ffmpeg or _load_ffmpeg_path(ROOT / "config.json")
    working_events_path = events_path
    video_path = source_video_path
    video_info = probe_video(source_video_path, ffmpeg_path)
    duration_limit = video_info.duration_seconds
    if args.first_minutes > 0:
        duration_limit = min(video_info.duration_seconds, args.first_minutes * 60)
        working_events_path = run_dir / "mouse_events_first_range.jsonl"
        _write_filtered_events(events_path, working_events_path, duration_limit)
        if args.generate_sheets:
            video_path = run_dir / "recording_first_range.mp4"
            _make_video_clip(source_video_path, video_path, duration_limit, ffmpeg_path)
        video_info = VideoInfo(
            video_path,
            duration_limit,
            video_info.width,
            video_info.height,
            video_info.fps,
            video_info.file_size_bytes,
        )

    config = ClickKeyframeConfig(
        video_path=video_path,
        events_path=working_events_path,
        output_dir=run_dir / "sheets",
        max_frames=0,
        sheet_cols=5,
        sheet_rows=6,
        thumb_width=320,
        time_dedupe_seconds=1.5,
        distance_dedupe_px=80,
        visual_change_threshold=0.22,
        include_double_clicks=False,
        include_drag_events=False,
        show_timestamp=True,
        show_index=True,
        draw_click_markers=True,
        output_basename="keyframe_summary",
    )

    if args.generate_sheets:
        result = generate_click_keyframe_sheets(config, ffmpeg_path, _print_progress)
        index_payload = json.loads(result.index_json.read_text(encoding="utf-8"))
        summary = _summary_from_index(index_payload, duration_limit, result.index_json, result.sheet_paths)
    else:
        events = load_click_keyframe_events(config)
        selection = select_click_keyframes_with_stats(events, config)
        combined = _add_silent_gap_keyframes(selection.events, config, video_info, selection)
        plan = build_click_keyframe_plan(combined, config, video_info, selection)
        summary = {
            "mode": "metrics_only_no_visual_signature_extraction",
            "duration_seconds": round(duration_limit, 3),
            "raw_click_events": len(events),
            "kept_frames": len(plan),
            "skipped_events": selection.skipped_count,
            "sheet_count_estimate": _sheet_count(len(plan), config.sheet_cols * config.sheet_rows),
            "selection": selection.stats,
        }

    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote: {summary_path}")
    return 0


def _load_ffmpeg_path(config_path: Path) -> str | None:
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    value = config.get("ffmpeg_path")
    return str(value) if value else None


def _write_filtered_events(source: Path, target: Path, max_seconds: float) -> None:
    accepted_lines: list[str] = []
    max_ms = max_seconds * 1000
    with source.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            milliseconds = _event_video_milliseconds(row)
            if milliseconds is None or milliseconds > max_ms:
                continue
            accepted_lines.append(json.dumps(row, ensure_ascii=False))
    target.write_text("\n".join(accepted_lines) + ("\n" if accepted_lines else ""), encoding="utf-8", newline="\n")


def _make_video_clip(source: Path, target: Path, duration_seconds: float, ffmpeg_path: str | None) -> None:
    command = [
        ffmpeg_path or "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-t",
        f"{duration_seconds:.3f}",
        "-c",
        "copy",
        str(target),
    ]
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffmpeg clip failed")


def _event_video_milliseconds(row: dict[str, Any]) -> float | None:
    value = row.get("t_video_ms")
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    timecode = row.get("video_timecode")
    if not timecode:
        return None
    parts = str(timecode).split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return (float(hours) * 3600 + float(minutes) * 60 + float(seconds)) * 1000
        if len(parts) == 2:
            minutes, seconds = parts
            return (float(minutes) * 60 + float(seconds)) * 1000
    except ValueError:
        return None
    return None


def _summary_from_index(index_payload: dict[str, Any], duration_seconds: float, index_json: Path, sheet_paths: list[Path]) -> dict[str, Any]:
    return {
        "mode": "generated_sheets",
        "duration_seconds": round(duration_seconds, 3),
        "raw_click_events": index_payload.get("events_total", 0),
        "kept_frames": index_payload.get("events_kept", 0),
        "skipped_events": index_payload.get("events_skipped", 0),
        "sheet_count": len(sheet_paths),
        "index_json": str(index_json),
        "sheets": [str(path) for path in sheet_paths],
        "selection": index_payload.get("selection", {}),
    }


def _sheet_count(frame_count: int, frames_per_sheet: int) -> int:
    frames_per_sheet = max(1, frames_per_sheet)
    return (frame_count + frames_per_sheet - 1) // frames_per_sheet if frame_count else 0


def _print_progress(done: int, total: int, message: str) -> None:
    if total <= 0:
        print(message)
    else:
        print(f"{done}/{total} {message}")


if __name__ == "__main__":
    raise SystemExit(main())
