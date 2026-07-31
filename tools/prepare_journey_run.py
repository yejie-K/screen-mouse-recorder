#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.analysis_handoff import AnalysisHandoffError, load_analysis_handoff  # noqa: E402
from screen_mouse_recorder.frame_export import (  # noqa: E402
    CLICK_SUMMARY_POLICY_ID,
    CLICK_SUMMARY_SILENT_INTERVAL_SECONDS,
    ClickKeyframeConfig,
    build_click_summary_config,
    estimate_click_keyframe_sampling,
    generate_click_keyframe_sheets,
    probe_video,
)
from screen_mouse_recorder.journey_analysis.package import JourneyPackageError, write_json_atomic  # noqa: E402
from screen_mouse_recorder.journey_analysis.workspace import initialize_journey_workspace  # noqa: E402
from screen_mouse_recorder.storage import SessionStorage  # noqa: E402


ProgressCallback = Callable[[int, int, str], None]


def _preflight(config: ClickKeyframeConfig) -> dict:
    estimate = estimate_click_keyframe_sampling(config)
    return {
        "schema_version": "1.0",
        "task_id": "JOURNEY_RUN_PREFLIGHT_V1",
        "source": {
            "video": config.video_path.name,
            "mouse_events": config.events_path.name,
            "mode": "generated",
            "frame_policy": CLICK_SUMMARY_POLICY_ID,
        },
        "selection": {
            "events_total": estimate.events_total,
            "events_kept": estimate.events_kept,
            "events_skipped": estimate.events_skipped,
            "max_frames": max(0, int(config.max_frames)),
            "cap_strategy": "uniform_timeline" if config.max_frames and estimate.events_skipped else "none",
            "timeline_start_seconds": estimate.timeline_start_seconds,
            "timeline_end_seconds": estimate.timeline_end_seconds,
        },
        "workload": {
            "sheet_count": estimate.sheet_count,
            "sheet_count_basis": "点击聚类基线，不含画面变化保留帧和静默区间补帧",
            "frames_per_sheet": estimate.frames_per_sheet,
            "source_frames_before_visual_and_silent_gap": estimate.events_kept,
            "visual_signature_frames": estimate.visual_signature_frames,
            "cached_frame_reuses": estimate.cached_frame_reuses,
            "estimated_frame_extractions": estimate.estimated_frame_extractions,
            "estimated_frame_extractions_excludes_silent_gap": True,
            "estimated_processing_seconds": round(estimate.estimated_processing_seconds, 1),
        },
    }


def _preflight_from_index(index_payload: dict, *, mode: str) -> dict:
    frames = index_payload.get("frames") or []
    selection = index_payload.get("selection") or {}
    return {
        "schema_version": "1.0",
        "task_id": "JOURNEY_RUN_PREFLIGHT_V1",
        "source": {
            "mode": mode,
            "frame_policy": CLICK_SUMMARY_POLICY_ID,
        },
        "selection": {
            "events_total": int(index_payload.get("events_total") or 0),
            "events_kept": len(frames),
            "events_skipped": int(index_payload.get("events_skipped") or 0),
            "max_frames": int(selection.get("max_frames") or 0),
            "cap_strategy": str(selection.get("cap_strategy") or "none"),
        },
        "workload": {
            "sheet_count": len({str(item.get("sheet") or "") for item in frames if isinstance(item, dict)}),
            "frames_per_sheet": 30,
            "actual_frame_extractions": int(selection.get("actual_frame_extractions") or 0),
            "reused_existing_output": mode == "recorder_handoff",
        },
    }


def _materialize_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_plain_video_session(session_dir: Path, run_dir: Path) -> Path:
    source_video = session_dir / "recording.mp4"
    if not source_video.is_file():
        raise JourneyPackageError("所选文件夹缺少recording.mp4")
    info = probe_video(source_video)
    derived = run_dir / "derived_session"
    derived.mkdir(parents=True, exist_ok=True)
    _materialize_file(source_video, derived / "recording.mp4")
    identity = _file_sha256(source_video)[:16]
    session_id = f"video_{identity}"
    meta = {
        "schema_version": "1.0",
        "session_id": session_id,
        "platform": "derived",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "derived_from_plain_video": True,
        "video": {
            "file": "recording.mp4",
            "fps": info.fps,
            "width": info.width,
            "height": info.height,
            "segments": [{"file": "recording.mp4", "start_video_ms": 0, "end_video_ms": round(info.duration_seconds * 1000)}],
        },
    }
    write_json_atomic(derived / "session_meta.json", meta)
    positions = [index * CLICK_SUMMARY_SILENT_INTERVAL_SECONDS for index in range(max(1, math.ceil(info.duration_seconds / CLICK_SUMMARY_SILENT_INTERVAL_SECONDS)))]
    with (derived / "mouse_events.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for index, seconds in enumerate(positions, start=1):
            handle.write(json.dumps({
                "event_id": f"interval_{index:06d}",
                "event_type": "click",
                "t_video_ms": round(min(seconds, max(0.0, info.duration_seconds - 0.001)) * 1000),
                "derived_interval_frame": True,
            }, ensure_ascii=False) + "\n")
    return derived


def prepare_journey_run(
    session_dir: Path,
    run_dir: Path,
    *,
    game_id: str,
    game_name: str,
    region_profile: Path | None = None,
    region_evidence_root: Path | None = None,
    workspace_dir: Path | None = None,
    progress: ProgressCallback | None = None,
) -> dict:
    session_dir = session_dir.resolve()
    run_dir = run_dir.resolve()
    workspace_dir = workspace_dir.resolve() if workspace_dir else run_dir / "workspace"
    if run_dir.exists() and any(run_dir.iterdir()):
        raise JourneyPackageError(f"运行目录必须为空: {run_dir}")
    if workspace_dir.exists() and any(workspace_dir.iterdir()):
        raise JourneyPackageError(f"工作空间目录必须为空: {workspace_dir}")
    source_storage = SessionStorage(session_dir)
    handoff = None
    handoff_warning = ""
    try:
        handoff = load_analysis_handoff(session_dir)
    except AnalysisHandoffError as exc:
        handoff_warning = str(exc)
    source_mode = "recorder_handoff" if handoff is not None else "generated_native"
    working_session = session_dir
    if handoff is None and not (
        source_storage.recording_mp4.is_file()
        and source_storage.mouse_events.is_file()
        and source_storage.session_meta.is_file()
    ):
        source_mode = "plain_video_interval"

    run_dir.mkdir(parents=True, exist_ok=True)
    if source_mode == "plain_video_interval":
        working_session = _prepare_plain_video_session(session_dir, run_dir)
    storage = SessionStorage(working_session)
    started = time.perf_counter()

    def on_progress(done: int, total: int, message: str) -> None:
        if progress is not None:
            progress(done, total, message)

    if handoff is not None:
        index_path = handoff.frame_index_path
        sheet_paths = list(handoff.contact_sheet_paths)
        index_payload = json.loads(index_path.read_text(encoding="utf-8-sig"))
        preflight = _preflight_from_index(index_payload, mode=source_mode)
        if progress is not None:
            progress(1, 1, "复用录屏软件抽帧结果")
    else:
        config = build_click_summary_config(
            storage.recording_mp4,
            storage.mouse_events,
            run_dir / "contact_sheets",
        )
        preflight = _preflight(config)
        preflight["source"]["mode"] = source_mode
        keyframes = generate_click_keyframe_sheets(config, progress=on_progress)
        index_path = keyframes.index_json
        sheet_paths = list(keyframes.sheet_paths)
        index_payload = json.loads(index_path.read_text(encoding="utf-8-sig"))
    if not sheet_paths or not (index_payload.get("frames") or []):
        raise JourneyPackageError("没有生成可供分析的抽帧和合成图")
    write_json_atomic(run_dir / "preflight.json", preflight)
    selection_stats = index_payload.get("selection") or {}
    workspace = initialize_journey_workspace(
        working_session,
        index_path,
        workspace_dir,
        game_id=game_id,
        game_name=game_name,
        region_profile=region_profile.resolve() if region_profile else None,
        region_evidence_root=region_evidence_root.resolve() if region_evidence_root else None,
    )
    report = {
        "schema_version": "1.0",
        "task_id": "JOURNEY_RUN_PREPARE_V1",
        "status": "ready",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "preflight": "preflight.json",
        "contact_sheets": {
            "source_mode": source_mode,
            "frame_policy": CLICK_SUMMARY_POLICY_ID,
            "index": os.path.relpath(index_path, run_dir).replace("\\", "/"),
            "sheet_count": len(sheet_paths),
            "events_total": int(index_payload.get("events_total") or 0),
            "events_kept": len(index_payload.get("frames") or []),
            "events_skipped": int(index_payload.get("events_skipped") or 0),
            "extracted_frame_count": len(index_payload.get("frames") or []),
            "source_events_kept": int(selection_stats.get("events_kept") or len(index_payload.get("frames") or [])),
            "synthetic_frames_added": int(selection_stats.get("silent_gap_frames_added") or 0),
            "frame_cache_reuses": int(selection_stats.get("frame_cache_reuses") or 0),
            "actual_frame_extractions": int(selection_stats.get("actual_frame_extractions") or 0),
            "handoff_warning": handoff_warning,
        },
        "workspace": os.path.relpath(workspace_dir, run_dir).replace("\\", "/"),
        "stages": workspace["stages"],
    }
    write_json_atomic(run_dir / "prepare_report.json", report)
    write_json_atomic(workspace_dir / "preflight.json", preflight)
    published_report = {
        **report,
        "preflight": "preflight.json",
        "workspace": "journey_workspace.json",
        "contact_sheets": {
            **report["contact_sheets"],
            "index": "runtime/keyframes_index.json",
        },
    }
    write_json_atomic(workspace_dir / "prepare_report.json", published_report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="一次性预检点击抽帧并初始化历程拆解工作空间")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("run_dir", type=Path, help="本次运行目录；内部创建contact_sheets和workspace")
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--game-name", required=True)
    parser.add_argument("--region-profile", type=Path)
    parser.add_argument("--region-evidence-root", type=Path)
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="兼容旧命令；正式CLICK_SUMMARY_V1仅接受0（不限制）",
    )
    parser.add_argument(
        "--no-visual-change",
        action="store_true",
        help="已停用；正式CLICK_SUMMARY_V1固定启用画面变化判断",
    )
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--serve", action="store_true", help="初始化后直接启动当前工作空间页面")
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    run_dir = args.run_dir.resolve()
    try:
        if args.max_frames != 0 or args.no_visual_change:
            raise JourneyPackageError(
                "抽帧参数已统一为CLICK_SUMMARY_V1；不再支持自定义max-frames或关闭画面变化判断"
            )
        if args.estimate_only:
            storage = SessionStorage(session_dir)
            config = build_click_summary_config(
                storage.recording_mp4,
                storage.mouse_events,
                run_dir / "contact_sheets",
            )
            preflight = _preflight(config)
            print(json.dumps(preflight, ensure_ascii=False))
            return 0

        def progress(done: int, total: int, message: str) -> None:
            print(json.dumps({"stage": "keyframes", "current": done, "total": total, "message": message}, ensure_ascii=False), flush=True)

        report = prepare_journey_run(
            session_dir,
            run_dir,
            game_id=args.game_id,
            game_name=args.game_name,
            region_profile=args.region_profile,
            region_evidence_root=args.region_evidence_root,
            progress=progress,
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if args.serve:
            return subprocess.call([sys.executable, str(ROOT / "tools" / "serve_journey_workspace.py"), str(run_dir / "workspace")])
        return 0
    except (JourneyPackageError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "code": "JOURNEY-RUN-001", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
