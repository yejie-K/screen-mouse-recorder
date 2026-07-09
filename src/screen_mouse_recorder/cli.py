from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tkinter
from typing import Any

from . import __version__
from .app import main as app_main
from .config import AppConfig
from .frame_sampler import (
    CropRegion,
    FrameSamplerConfig,
    default_output_dir,
    estimate_sampling,
    format_timecode,
    parse_timecode,
    probe_video,
    sample_video_to_sheets,
)
from .naming import FRAME_EXPORT_DIR_NAME
from .postprocess import generate_summary
from .selftest import run_pause_selftest, run_recording_selftest
from .storage import SessionStorage


def enable_dpi_awareness() -> None:
    if platform.system().lower() != "windows":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def default_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="screen-mouse-recorder")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--base-dir", type=Path, default=default_base_dir(), help="Project/runtime base directory.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("app", help="Launch the desktop app.")
    subparsers.add_parser("doctor", help="Check runtime dependencies.")
    subparsers.add_parser("init-config", help="Create config.json from defaults if missing.")

    postprocess_parser = subparsers.add_parser("postprocess", help="Regenerate summary files for a session.")
    postprocess_parser.add_argument("session_dir", type=Path)

    selftest_parser = subparsers.add_parser("selftest-record", help="Run a short real recording self-test.")
    selftest_parser.add_argument("--seconds", type=float, default=2.0)

    pause_selftest_parser = subparsers.add_parser("selftest-pause", help="Run a pause/resume real recording self-test.")
    pause_selftest_parser.add_argument("--segment-seconds", type=float, default=0.8)
    pause_selftest_parser.add_argument("--pause-seconds", type=float, default=0.5)

    sample_parser = subparsers.add_parser("sample-frames", help="Extract video frames into contact sheets.")
    sample_parser.add_argument("video", type=Path)
    sample_parser.add_argument("--output-dir", type=Path)
    sample_parser.add_argument("--start", default="00:00")
    sample_parser.add_argument("--end", default="")
    sample_parser.add_argument("--interval", type=float, default=10.0)
    sample_parser.add_argument("--cols", type=int, default=5)
    sample_parser.add_argument("--rows", type=int, default=6)
    sample_parser.add_argument("--thumb-width", type=int, default=360)
    sample_parser.add_argument("--quality", type=int, default=85)
    sample_parser.add_argument("--format", choices=["jpg", "png"], default="jpg")
    sample_parser.add_argument("--click-events", type=Path)
    sample_parser.add_argument("--draw-clicks", action="store_true")
    sample_parser.add_argument("--click-window", type=float, default=0.5)
    sample_parser.add_argument("--dense-start", default="")
    sample_parser.add_argument("--dense-end", default="")
    sample_parser.add_argument("--dense-interval", type=float, default=2.0)
    sample_parser.add_argument("--crop", default="", help="Optional crop x,y,w,h")
    sample_parser.add_argument("--estimate-only", action="store_true")

    args = parser.parse_args(argv)
    command = args.command or "app"
    base_dir: Path = args.base_dir.resolve()
    if getattr(sys, "frozen", False):
        os.chdir(base_dir)
    enable_dpi_awareness()

    if command == "app":
        app_main(base_dir=base_dir)
        return 0
    if command == "doctor":
        return doctor(base_dir)
    if command == "init-config":
        return init_config(base_dir)
    if command == "postprocess":
        return postprocess(args.session_dir)
    if command == "selftest-record":
        return selftest_record(base_dir, args.seconds)
    if command == "selftest-pause":
        return selftest_pause(base_dir, args.segment_seconds, args.pause_seconds)
    if command == "sample-frames":
        return sample_frames(base_dir, args)
    parser.error(f"Unknown command: {command}")
    return 2


def doctor(base_dir: Path) -> int:
    config = AppConfig.load(base_dir / "config.json")
    output_root = config.output_root_path(base_dir)
    ffmpeg = config.ffmpeg_path or shutil.which("ffmpeg")
    checks: list[tuple[str, bool, str]] = [
        ("platform_windows", platform.system().lower() == "windows", platform.platform()),
        ("tkinter_available", bool(tkinter.TkVersion), f"Tk {tkinter.TkVersion}"),
        ("ffmpeg_available", bool(ffmpeg), str(ffmpeg or "missing")),
    ]

    writable = False
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        probe = output_root / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError as exc:
        checks.append(("output_root_writable", False, f"{output_root}: {exc}"))
    else:
        checks.append(("output_root_writable", True, str(output_root)))

    for name, ok, detail in checks:
        status = "OK" if ok else "FAIL"
        print(f"{status:4} {name}: {detail}")

    return 0 if all(ok for _, ok, _ in checks) and writable else 1


def init_config(base_dir: Path) -> int:
    path = base_dir / "config.json"
    if path.exists():
        print(f"config.json already exists: {path}")
        return 0
    config = AppConfig()
    data: dict[str, Any] = config.to_dict()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"created {path}")
    return 0


def postprocess(session_dir: Path) -> int:
    session_dir = session_dir.resolve()
    storage = SessionStorage(session_dir)
    if not storage.mouse_events.exists() and not storage.mouse_samples.exists():
        print(f"No mouse_events.jsonl or mouse_samples.jsonl found in {session_dir}", file=sys.stderr)
        return 1
    summary = generate_summary(storage)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def selftest_record(base_dir: Path, seconds: float) -> int:
    try:
        result = run_recording_selftest(base_dir, seconds=seconds)
    except Exception as exc:
        print(f"selftest-record failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def selftest_pause(base_dir: Path, segment_seconds: float, pause_seconds: float) -> int:
    try:
        result = run_pause_selftest(base_dir, segment_seconds=segment_seconds, pause_seconds=pause_seconds)
    except Exception as exc:
        print(f"selftest-pause failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def sample_frames(base_dir: Path, args: argparse.Namespace) -> int:
    config = AppConfig.load(base_dir / "config.json")
    video = args.video.resolve()
    crop = _parse_crop(args.crop)
    start_seconds = parse_timecode(args.start) or 0.0
    end_seconds = parse_timecode(args.end)
    dense_start = parse_timecode(args.dense_start)
    dense_end = parse_timecode(args.dense_end)
    try:
        video_info = probe_video(video, config.ffmpeg_path)
        output_dir = (
            args.output_dir.resolve()
            if args.output_dir
            else default_output_dir(
                video,
                base_dir / FRAME_EXPORT_DIR_NAME,
                start_seconds=start_seconds,
                end_seconds=end_seconds if end_seconds is not None else video_info.duration_seconds,
                mode="dense" if dense_start is not None and dense_end is not None else "interval",
                crop=crop,
            )
        )
        sampler_config = FrameSamplerConfig(
            video_path=video,
            output_dir=output_dir,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            interval_seconds=args.interval,
            sheet_cols=args.cols,
            sheet_rows=args.rows,
            thumb_width=args.thumb_width,
            jpeg_quality=args.quality,
            output_format=args.format,
            crop=crop,
            dense_start_seconds=dense_start,
            dense_end_seconds=dense_end,
            dense_interval_seconds=args.dense_interval if dense_start is not None and dense_end is not None else None,
            click_events_path=args.click_events.resolve() if args.click_events else None,
            draw_click_markers=args.draw_clicks,
            click_match_window_seconds=args.click_window,
        )
        estimate = estimate_sampling(sampler_config, video_info)
    except Exception as exc:
        print(f"sample-frames failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "video": str(video),
                "duration": format_timecode(video_info.duration_seconds),
                "resolution": f"{video_info.width}x{video_info.height}",
                "frames": estimate.frame_count,
                "sheets": estimate.sheet_count,
                "estimated_seconds": round(estimate.estimated_processing_seconds, 1),
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.estimate_only:
        return 0

    def progress(done: int, total: int, message: str) -> None:
        print(f"[{done}/{total}] {message}")

    try:
        result = sample_video_to_sheets(sampler_config, config.ffmpeg_path, progress)
    except Exception as exc:
        print(f"sample-frames failed: {exc}", file=sys.stderr)
        return 1
    print(f"saved: {result.output_dir}")
    print(f"report: {result.report_html}")
    return 0


def _parse_crop(value: str) -> CropRegion | None:
    text = value.strip()
    if not text:
        return None
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--crop must be x,y,w,h")
    x, y, width, height = (int(float(part)) for part in parts)
    if width <= 0 or height <= 0:
        return None
    return CropRegion(x=x, y=y, width=width, height=height)
