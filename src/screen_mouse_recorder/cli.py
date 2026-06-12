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

from .app import main as app_main
from .config import AppConfig
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
    data: dict[str, Any] = {
        "video_fps": config.video_fps,
        "sample_fps": config.sample_fps,
        "output_root": config.output_root,
        "session_name": config.session_name,
        "record_outside_region": config.record_outside_region,
        "record_mouse_samples": config.record_mouse_samples,
        "record_click_events": config.record_click_events,
        "record_wheel_events": config.record_wheel_events,
        "record_drag_events": config.record_drag_events,
        "show_sync_marker": config.show_sync_marker,
        "show_recording_status_banner": config.show_recording_status_banner,
        "startup_countdown_seconds": config.startup_countdown_seconds,
        "click_max_duration_ms": config.click_max_duration_ms,
        "click_max_distance_px": config.click_max_distance_px,
        "drag_min_distance_px": config.drag_min_distance_px,
        "double_click_window_ms": config.double_click_window_ms,
        "calibration_click_tolerance_px": config.calibration_click_tolerance_px,
        "calibration_residual_warning_px": config.calibration_residual_warning_px,
        "ffmpeg_path": config.ffmpeg_path,
    }
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
