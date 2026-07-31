from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from .event_review_bridge import build_event_review_bundle
from .game_profile import new_game_profile
from .metric_review import build_metric_review_template, finalize_metric_review
from .package import JourneyPackageError, write_json_atomic


WORKSPACE_VERSION = "1.0"
WORKSPACE_TASK = "JOURNEY_WORKSPACE_V1"


def initialize_journey_workspace(
    session_dir: Path,
    index_json: Path,
    output_dir: Path,
    *,
    game_id: str,
    game_name: str,
    region_profile: Path | None = None,
    region_evidence_root: Path | None = None,
) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    index_json = index_json.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise JourneyPackageError(f"工作空间目录必须为空: {output_dir}")
    session_meta_path = session_dir / "session_meta.json"
    session_meta = _read_object(session_meta_path)
    session_id = str(session_meta.get("session_id") or session_dir.name).strip()
    if not session_id:
        raise JourneyPackageError("Session缺少session_id")
    video_name = str((session_meta.get("video") or {}).get("file") or "recording.mp4")
    video_path = (session_dir / video_name).resolve()
    if not video_path.is_file():
        raise JourneyPackageError(f"Session视频不存在: {video_path}")
    index_payload = _read_object(index_json)
    frames = _validate_index(index_payload, index_json.parent)

    runtime_dir = output_dir / "runtime"
    contact_dir = runtime_dir / "contact_sheets"
    review_dir = output_dir / "review"
    region_dir = output_dir / "region"
    scan_dir = output_dir / "scan"
    event_dir = output_dir / "event_review"
    metric_dir = output_dir / "metric_review"
    final_dir = output_dir / "final"
    for directory in (contact_dir, review_dir, region_dir / "evidence", scan_dir, event_dir, metric_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)

    _materialize_file(video_path, runtime_dir / "recording.mp4")
    _materialize_file(index_json, runtime_dir / "keyframes_index.json")
    sheets = _materialize_contact_sheets(frames, index_json.parent, contact_dir)
    duration_ms = _session_duration_ms(session_meta, frames)
    review_runtime = _build_review_runtime(
        session_id=session_id,
        game_name=game_name,
        duration_ms=duration_ms,
        frames=frames,
        sheets=sheets,
    )
    write_json_atomic(runtime_dir / "review_session.json", review_runtime)
    write_json_atomic(output_dir / "game_profile.json", new_game_profile(game_id, game_name))

    profile_relative = ""
    if region_profile is not None:
        source_profile = region_profile.resolve()
        profile_payload = _read_object(source_profile)
        if profile_payload.get("schema_version") != "1.1":
            raise JourneyPackageError("新工作空间只接受OCR区域profile 1.1")
        if str(profile_payload.get("game_id") or "") != game_id:
            raise JourneyPackageError("区域profile.game_id与工作空间不一致")
        profile_target = region_dir / "ocr_region_profile.json"
        write_json_atomic(profile_target, profile_payload)
        evidence_root = (region_evidence_root or source_profile.parent).resolve()
        _materialize_profile_evidence(profile_payload, evidence_root, region_dir / "evidence")
        profile_relative = _relative(output_dir, profile_target)
    else:
        profile_target = region_dir / "ocr_region_profile.json"
        write_json_atomic(
            profile_target,
            _new_region_profile_draft(session_meta, game_id=game_id, game_name=game_name),
        )
        profile_relative = _relative(output_dir, profile_target)

    manifest = {
        "schema_version": WORKSPACE_VERSION,
        "task_id": WORKSPACE_TASK,
        "status": "initialized",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session": {
            "session_id": session_id,
            "game_id": game_id,
            "game_name": game_name,
            "duration_ms": duration_ms,
            "frame_count": len(frames),
            "sheet_count": len(sheets),
        },
        "source": {
            "session_fingerprint": _fingerprint_files(session_meta_path, index_json),
            "session_meta_sha256": _sha256_file(session_meta_path),
            "index_sha256": _sha256_file(index_json),
        },
        "artifacts": {
            "review_runtime": "runtime/review_session.json",
            "video": "runtime/recording.mp4",
            "frame_index": "runtime/keyframes_index.json",
            "manual_review": "review/manual_frame_review.json",
            "selected_ocr_tiles": "review/selected_ocr_tiles.json",
            "region_profile": profile_relative,
            "region_evidence": "region/evidence",
            "event_observations": "scan/event_observations_v2.json",
            "metric_observations": "scan/metric_observations_v2.json",
            "scan_manifest": "scan/region_scan_manifest.json",
            "combined_event_observations": "event_review/event_observations_v2.json",
            "event_review_manifest": "event_review/event_review_manifest.json",
            "confirmed_events": "event_review/confirmed_semantic_events.json",
            "metric_review": "metric_review/journey_metric_review.json",
            "confirmed_metrics": "metric_review/confirmed_metric_observations_v2.json",
            "final_manifest": "final/manifest.json",
            "preview_manifest": "preview/manifest.json",
            "game_profile": "game_profile.json",
        },
        "stages": {},
    }
    manifest = refresh_journey_workspace(output_dir, manifest=manifest)
    write_json_atomic(output_dir / "journey_workspace.json", manifest)
    return manifest


def ensure_region_profile_draft(
    workspace_dir: Path,
    *,
    width: int,
    height: int,
) -> Path:
    workspace_dir = workspace_dir.resolve()
    manifest_path = workspace_dir / "journey_workspace.json"
    manifest = _read_workspace(manifest_path)
    artifacts = manifest["artifacts"]
    profile_value = str(artifacts.get("region_profile") or "").strip()
    profile_path = (
        _artifact(workspace_dir, artifacts, "region_profile")
        if profile_value
        else workspace_dir / "region" / "ocr_region_profile.json"
    )
    if profile_path.is_file():
        return profile_path
    session = manifest["session"]
    write_json_atomic(
        profile_path,
        _new_region_profile_draft(
            {"video": {"width": width, "height": height}},
            game_id=str(session["game_id"]),
            game_name=str(session["game_name"]),
        ),
    )
    artifacts["region_profile"] = _relative(workspace_dir, profile_path)
    manifest = refresh_journey_workspace(workspace_dir, manifest=manifest)
    write_json_atomic(manifest_path, manifest)
    return profile_path


def _new_region_profile_draft(
    session_meta: dict[str, Any],
    *,
    game_id: str,
    game_name: str,
) -> dict[str, Any]:
    video = session_meta.get("video") or {}
    recording_region = session_meta.get("recording_region") or {}
    try:
        width = int(video.get("width") or recording_region.get("width") or 0)
        height = int(video.get("height") or recording_region.get("height") or 0)
    except (TypeError, ValueError) as exc:
        raise JourneyPackageError("Session视频尺寸无效，无法创建区域校准草稿") from exc
    if width <= 0 or height <= 0:
        raise JourneyPackageError("Session缺少视频宽高，无法创建区域校准草稿")
    return {
        "schema_version": "1.1",
        "game_id": game_id,
        "game_name": game_name,
        "status": "needs_review",
        "scan_scope": "all_extracted_frames",
        "source_frame": {"width": width, "height": height},
        "regions": [],
        "review": {"reviewer": "", "reviewed_at": ""},
    }


def sync_journey_workspace(
    workspace_dir: Path,
    *,
    taxonomy_path: Path,
    emotion_rules_path: Path,
    reset_review: bool = False,
) -> dict[str, Any]:
    workspace_dir = workspace_dir.resolve()
    manifest_path = workspace_dir / "journey_workspace.json"
    manifest = _read_workspace(manifest_path)
    artifacts = manifest["artifacts"]
    if not str(artifacts.get("game_profile") or "").strip():
        artifacts["game_profile"] = "game_profile.json"
    game_profile_path = _artifact(workspace_dir, artifacts, "game_profile")
    if not game_profile_path.is_file():
        write_json_atomic(
            game_profile_path,
            new_game_profile(str(manifest["session"]["game_id"]), str(manifest["session"]["game_name"])),
        )
    event_source = _artifact(workspace_dir, artifacts, "event_observations")
    metric_source = _artifact(workspace_dir, artifacts, "metric_observations")
    automatic_events = _read_object(event_source)
    metrics = _read_object(metric_source)
    _validate_scan_pair(workspace_dir, manifest, automatic_events, metrics)

    manual_path = _artifact(workspace_dir, artifacts, "manual_review")
    manual = _read_object(manual_path) if manual_path.is_file() else {
        "schema_version": "1.0",
        "session_id": manifest["session"]["session_id"],
        "candidates": [],
    }
    combined_path = _artifact(workspace_dir, artifacts, "combined_event_observations")
    combined = _combine_event_candidates(automatic_events, manual)
    if combined_path.is_file():
        existing_combined = _read_object(combined_path)
        if _event_review_projection(existing_combined) == _event_review_projection(combined):
            combined = existing_combined
        else:
            write_json_atomic(combined_path, combined)
    else:
        write_json_atomic(combined_path, combined)
    _materialize_event_evidence(workspace_dir, combined, automatic_events, manual)

    event_dir = combined_path.parent
    _prepare_event_review(
        combined_path,
        event_dir,
        taxonomy_path=taxonomy_path,
        emotion_rules_path=emotion_rules_path,
        duration_ms=int(manifest["session"]["duration_ms"]),
        reset_review=reset_review,
    )
    metric_sha256 = _sha256_file(metric_source)
    previous_metric_sha256 = str((manifest.get("source") or {}).get("metric_candidates_sha256") or "")
    if (
        previous_metric_sha256
        and previous_metric_sha256 != metric_sha256
        and _artifact(workspace_dir, artifacts, "metric_review").is_file()
        and not reset_review
    ):
        raise JourneyPackageError("指标候选内容已变化；为保护已有复核结果，请显式使用--reset-review")
    _prepare_metric_review(
        metrics,
        _artifact(workspace_dir, artifacts, "metric_review"),
        _artifact(workspace_dir, artifacts, "confirmed_metrics"),
        reset_review=reset_review,
    )
    manifest["source"].update({
        "scan_source_fingerprint": automatic_events["source_fingerprint"],
        "event_candidates_sha256": _sha256_file(event_source),
        "manual_candidates_sha256": _manual_candidates_fingerprint(manual),
        "combined_event_sha256": _sha256_file(combined_path),
        "metric_candidates_sha256": metric_sha256,
    })
    manifest["source"].pop("manual_review_sha256", None)
    manifest = refresh_journey_workspace(workspace_dir, manifest=manifest)
    write_json_atomic(manifest_path, manifest)
    return manifest


def refresh_journey_workspace(
    workspace_dir: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace_dir = workspace_dir.resolve()
    result = deepcopy(manifest or _read_workspace(workspace_dir / "journey_workspace.json"))
    artifacts = result["artifacts"]
    manual_path = _artifact(workspace_dir, artifacts, "manual_review")
    profile_path = _optional_artifact(workspace_dir, artifacts, "region_profile")
    event_candidates_path = _artifact(workspace_dir, artifacts, "event_observations")
    metric_candidates_path = _artifact(workspace_dir, artifacts, "metric_observations")
    confirmed_events_path = _artifact(workspace_dir, artifacts, "confirmed_events")
    confirmed_metrics_path = _artifact(workspace_dir, artifacts, "confirmed_metrics")

    manual_count = 0
    if manual_path.is_file():
        manual = _read_object(manual_path)
        _require_session(result, manual.get("session_id"), "人工选帧")
        manual_count = sum(1 for item in manual.get("candidates") or [] if item.get("status") != "rejected")
    profile_status = "missing"
    if profile_path is not None and profile_path.is_file():
        profile_status = str(_read_object(profile_path).get("status") or "invalid")
    scan_ready = False
    scan_status = "blocked"
    scan_reason = "尚未生成同工作空间扫描结果"
    if event_candidates_path.is_file() and metric_candidates_path.is_file():
        try:
            _validate_scan_pair(
                workspace_dir,
                result,
                _read_object(event_candidates_path),
                _read_object(metric_candidates_path),
            )
        except JourneyPackageError as exc:
            scan_status = "stale"
            scan_reason = str(exc)
        else:
            scan_ready = True
            scan_status = "complete"
            scan_reason = ""
    event_manifest_path = _artifact(workspace_dir, artifacts, "event_review_manifest")
    event_review_fingerprint = ""
    if event_manifest_path.is_file():
        event_review_fingerprint = str(_read_object(event_manifest_path).get("review_source_fingerprint") or "")
    scan_metric_payload = _read_object(metric_candidates_path) if metric_candidates_path.is_file() else {}
    event_status, event_count, event_pending = _review_status(
        confirmed_events_path,
        "events",
        session_id=str(result["session"]["session_id"]),
        source_fingerprint=event_review_fingerprint,
    )
    metric_status, metric_count, metric_pending = _review_status(
        confirmed_metrics_path,
        "metrics",
        session_id=str(result["session"]["session_id"]),
        source_fingerprint=str(scan_metric_payload.get("source_fingerprint") or ""),
    )
    source_state = result.get("source") or {}
    manual_current_sha = _manual_candidates_fingerprint(_read_object(manual_path)) if manual_path.is_file() else ""
    event_sync_current = bool(source_state.get("event_candidates_sha256")) and (
        source_state.get("event_candidates_sha256") == (_sha256_file(event_candidates_path) if event_candidates_path.is_file() else "")
        and source_state.get("manual_candidates_sha256", "") == manual_current_sha
    )
    metric_sync_current = bool(source_state.get("metric_candidates_sha256")) and (
        source_state.get("metric_candidates_sha256") == (_sha256_file(metric_candidates_path) if metric_candidates_path.is_file() else "")
    )
    if not scan_ready:
        if confirmed_events_path.is_file():
            event_status = "stale"
        if confirmed_metrics_path.is_file():
            metric_status = "stale"
    else:
        if confirmed_events_path.is_file() and not event_sync_current:
            event_status = "stale"
        if confirmed_metrics_path.is_file() and not metric_sync_current:
            metric_status = "stale"
    final_ready = scan_ready and event_status == "complete" and metric_status == "complete"
    final_manifest_path = _artifact(workspace_dir, artifacts, "final_manifest")
    if not str(artifacts.get("preview_manifest") or "").strip():
        artifacts["preview_manifest"] = "preview/manifest.json"
    preview_manifest_path = _artifact(workspace_dir, artifacts, "preview_manifest")
    semantic_input_path = event_manifest_path.parent / "journey_semantic_input.json"
    preview_status = "ready" if semantic_input_path.is_file() and metric_candidates_path.is_file() else "blocked"
    if preview_manifest_path.is_file():
        preview_payload = _read_object(preview_manifest_path)
        preview_inputs = preview_payload.get("inputs") or {}
        preview_current = (
            semantic_input_path.is_file()
            and metric_candidates_path.is_file()
            and str((preview_inputs.get("event_candidates") or {}).get("sha256") or "") == _sha256_file(semantic_input_path)
            and str((preview_inputs.get("metric_candidates") or {}).get("sha256") or "") == _sha256_file(metric_candidates_path)
        )
        preview_status = "complete" if preview_current else "stale"
    final_complete = final_ready and final_manifest_path.is_file()
    result["status"] = "complete" if final_complete else ("ready_for_final" if final_ready else "in_progress")
    result["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    result["stages"] = {
        "manual_review": {"status": "ready", "candidate_count": manual_count},
        "region_profile": {"status": profile_status},
        "region_scan": {"status": scan_status, "reason": scan_reason},
        "event_review": {"status": event_status, "event_count": event_count, "pending_count": event_pending},
        "metric_review": {"status": metric_status, "metric_count": metric_count, "pending_count": metric_pending},
        "final_product": {
            "status": "complete" if final_complete else ("ready" if final_ready else "blocked"),
            "reason": "" if final_ready else "事件和指标必须全部完成复核",
        },
        "preview_product": {
            "status": preview_status,
            "reason": "" if preview_status != "blocked" else "需要至少一个事件候选和指标扫描结果",
        },
    }
    return result


def validate_final_gate(workspace_dir: Path) -> dict[str, Any]:
    manifest = refresh_journey_workspace(workspace_dir)
    if manifest["stages"]["final_product"]["status"] != "ready":
        event = manifest["stages"]["event_review"]
        metric = manifest["stages"]["metric_review"]
        raise JourneyPackageError(
            "正式产物门禁未通过: "
            f"功能事件={event['status']}({event['pending_count']}待复核), "
            f"指标={metric['status']}({metric['pending_count']}待复核)"
        )
    return manifest


def _build_review_runtime(
    *,
    session_id: str,
    game_name: str,
    duration_ms: int,
    frames: list[dict[str, Any]],
    sheets: dict[str, dict[str, int]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for frame in frames:
        grouped[str(frame["sheet"])].append(frame)
    contact_sheets = []
    for sheet_name, sheet_frames in grouped.items():
        dimensions = sheets[sheet_name]
        tiles = []
        for frame in sorted(sheet_frames, key=lambda item: int(item["index"])):
            seconds = float(frame["seconds"])
            tiles.append({
                "id": f"tile_{int(frame['index'])}",
                "eventId": str(frame.get("event_id") or f"frame_{int(frame['index']):06d}"),
                "timeMs": int(round(seconds * 1000)),
                "timecode": str(frame.get("timestamp") or _format_timecode(seconds)),
                "row": int(frame["sheet_row"]),
                "column": int(frame["sheet_col"]),
                "videoX": frame.get("video_x"),
                "videoY": frame.get("video_y"),
                "reason": str(frame.get("selection_reason") or "selected"),
            })
        contact_sheets.append({
            "name": sheet_name,
            "url": f"/runtime/contact_sheets/{sheet_name}",
            "rows": dimensions["rows"],
            "columns": dimensions["columns"],
            "tiles": tiles,
        })
    return {
        "schemaVersion": WORKSPACE_VERSION,
        "projectName": f"{game_name} · {session_id}",
        "sessionId": session_id,
        "durationMs": duration_ms,
        "durationTimecode": _format_timecode(duration_ms / 1000),
        "videoUrl": "/runtime/recording.mp4",
        "sourceIndex": "keyframes_index.json",
        "videoFile": "recording.mp4",
        "contactSheets": contact_sheets,
        "candidates": [],
    }


def _combine_event_candidates(automatic: dict[str, Any], manual: dict[str, Any]) -> dict[str, Any]:
    if automatic.get("schema_version") != "2.0" or automatic.get("task_id") != "JOURNEY_EVENT_OBSERVATIONS_V2":
        raise JourneyPackageError("扫描事件候选不是当前2.0契约")
    session_id = str((automatic.get("session") or {}).get("session_id") or "")
    if str(manual.get("session_id") or "") != session_id:
        raise JourneyPackageError("人工选帧与区域扫描Session不一致")
    events = [deepcopy(item) for item in automatic.get("events") or []]
    used = {str(item.get("observation_id") or "") for item in events}
    manual_count = 0
    manual_metric_count = 0
    for candidate in manual.get("candidates") or []:
        if candidate.get("status") == "rejected":
            continue
        if candidate.get("eventKind") == "growth":
            manual_metric_count += 1
            continue
        candidate_id = str(candidate.get("id") or "")
        observation_id = f"manual_{candidate_id}"
        if not candidate_id or observation_id in used:
            raise JourneyPackageError("人工事件ID缺失或与扫描事件重复")
        used.add(observation_id)
        mode_tag, event_tag = _manual_tags(str(candidate.get("eventKind") or ""))
        contact_sheet = str(candidate.get("contactSheet") or "")
        events.append({
            "observation_id": observation_id,
            "session_id": session_id,
            "time_ms": int(candidate.get("timeMs") or 0),
            "timestamp": str(candidate.get("timecode") or ""),
            "source": "manual",
            "evidence": {
                "source_image": contact_sheet,
                "review_image": "",
                "contact_sheet": contact_sheet,
                "sheet_row": candidate.get("sheetRow"),
                "sheet_col": candidate.get("sheetColumn"),
                "manual_candidate_id": candidate_id,
            },
            "event_name": str(candidate.get("title") or "待人工确认").strip() or "待人工确认",
            "ocr_text": str(candidate.get("ocrText") or ""),
            "confidence": float(candidate.get("confidence") or 1),
            "mode_tag": mode_tag,
            "event_tag": event_tag,
            "region_group_id": "manual_selection",
            "last_time_ms": int(candidate.get("timeMs") or 0),
            "occurrence_frame_count": 1,
            "review": {"status": "pending", "reviewer": "", "reviewed_at": "", "note": "人工选帧高置信样本，仍需语义复核"},
        })
        manual_count += 1
    events.sort(key=lambda item: (int(item.get("time_ms") or 0), str(item.get("observation_id") or "")))
    counts = Counter(str((item.get("review") or {}).get("status") or "pending") for item in events)
    result = deepcopy(automatic)
    result["status"] = "needs_review" if events else "complete"
    result["summary"] = {
        "observation_count": len(events),
        "pending": counts["pending"],
        "confirmed": counts["confirmed"],
        "excluded": counts["excluded"],
        "automatic_count": len(automatic.get("events") or []),
        "manual_count": manual_count,
        "manual_metric_sample_count": manual_metric_count,
    }
    result["events"] = events
    result["compatibility"] = {
        "scan_source_fingerprint": automatic["source_fingerprint"],
        "manual_candidates_sha256": _manual_candidates_fingerprint(manual),
    }
    return result


def _event_review_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version"),
        "task_id": payload.get("task_id"),
        "source_fingerprint": payload.get("source_fingerprint"),
        "scan_scope": payload.get("scan_scope"),
        "session": payload.get("session"),
        "events": payload.get("events") or [],
    }


def _manual_candidates_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload.get("candidates") or [],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _prepare_event_review(
    source: Path,
    output_dir: Path,
    *,
    taxonomy_path: Path,
    emotion_rules_path: Path,
    duration_ms: int,
    reset_review: bool,
) -> None:
    expected_fingerprint = _sha256_file(source)
    manifest_path = output_dir / "event_review_manifest.json"
    if not (_read_object(source).get("events") or []):
        if manifest_path.is_file() and not reset_review:
            raise JourneyPackageError("事件候选已变为空；为保护已有复核结果，请显式使用--reset-review")
        return
    if manifest_path.is_file() and not reset_review:
        existing = _read_object(manifest_path)
        if existing.get("review_source_fingerprint") == expected_fingerprint:
            return
        raise JourneyPackageError("人工/扫描事件已变化；为保护已有复核结果，请显式使用--reset-review重建事件复核包")
    build_event_review_bundle(
        source,
        output_dir,
        taxonomy_path=taxonomy_path,
        emotion_rules_path=emotion_rules_path,
        total_play_time_ms=duration_ms,
        overwrite=reset_review,
    )


def _prepare_metric_review(candidates: dict[str, Any], review_path: Path, confirmed_path: Path, *, reset_review: bool) -> None:
    if review_path.is_file() and not reset_review:
        existing = _read_object(review_path)
        if existing.get("source_fingerprint") == candidates.get("source_fingerprint"):
            finalize_metric_review(candidates, existing)
            return
        raise JourneyPackageError("指标扫描来源已变化；为保护已有复核结果，请显式使用--reset-review重建指标复核包")
    review = build_metric_review_template(candidates)
    write_json_atomic(review_path, review)
    write_json_atomic(confirmed_path, finalize_metric_review(candidates, review))


def _validate_scan_pair(
    workspace_dir: Path,
    manifest: dict[str, Any],
    events: dict[str, Any],
    metrics: dict[str, Any],
) -> None:
    if events.get("schema_version") != "2.0" or metrics.get("schema_version") != "2.0":
        raise JourneyPackageError("新链路只接受区域扫描候选2.0")
    if events.get("source_fingerprint") != metrics.get("source_fingerprint"):
        raise JourneyPackageError("事件和指标候选不是同一次区域扫描")
    artifacts = manifest["artifacts"]
    profile_path = _optional_artifact(workspace_dir, artifacts, "region_profile")
    if profile_path is None or not profile_path.is_file():
        raise JourneyPackageError("工作空间缺少当前区域profile，不能验证扫描来源")
    expected_fingerprint = hashlib.sha256(
        _artifact(workspace_dir, artifacts, "frame_index").read_bytes() + profile_path.read_bytes()
    ).hexdigest()
    if events.get("source_fingerprint") != expected_fingerprint:
        raise JourneyPackageError("区域扫描结果与当前抽帧索引/profile不匹配，必须重新扫描")
    session_id = manifest["session"]["session_id"]
    if str((events.get("session") or {}).get("session_id") or "") != session_id:
        raise JourneyPackageError("事件候选Session与工作空间不一致")
    if str((metrics.get("session") or {}).get("session_id") or "") != session_id:
        raise JourneyPackageError("指标候选Session与工作空间不一致")


def _materialize_event_evidence(
    workspace_dir: Path,
    combined: dict[str, Any],
    automatic: dict[str, Any],
    manual: dict[str, Any],
) -> None:
    del automatic, manual
    evidence_dir = workspace_dir / "event_review" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for event in combined.get("events") or []:
        evidence = event.get("evidence") or {}
        source_root = workspace_dir / ("runtime/contact_sheets" if event.get("source") == "manual" else "scan")
        for field in ("source_image", "review_image", "contact_sheet"):
            value = str(evidence.get(field) or "").replace("\\", "/").strip()
            if not value:
                continue
            source = (source_root / value).resolve()
            try:
                source.relative_to(source_root.resolve())
            except ValueError:
                continue
            if not source.is_file():
                continue
            target_name = f"{event['observation_id']}_{source.name}" if (evidence_dir / source.name).exists() else source.name
            _materialize_evidence_file(source, evidence_dir / target_name)
            evidence[field] = target_name
        crops = []
        for value in evidence.get("crop_images") or []:
            relative = Path(str(value).replace("\\", "/"))
            source = (workspace_dir / "scan" / relative).resolve()
            if source.is_file():
                target_name = f"{event['observation_id']}_{source.name}"
                _materialize_evidence_file(source, evidence_dir / target_name)
                crops.append(target_name)
        if crops:
            evidence["crop_images"] = crops


def _validate_index(payload: dict[str, Any], index_dir: Path) -> list[dict[str, Any]]:
    frames = payload.get("frames")
    if not isinstance(frames, list) or not frames:
        raise JourneyPackageError("抽帧索引缺少frames")
    seen: set[int] = set()
    result = []
    for offset, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise JourneyPackageError(f"frames[{offset}]必须是对象")
        try:
            index = int(frame.get("index"))
            seconds = float(frame.get("seconds"))
            row = int(frame.get("sheet_row"))
            column = int(frame.get("sheet_col"))
        except (TypeError, ValueError) as exc:
            raise JourneyPackageError(f"frames[{offset}]索引字段无效") from exc
        sheet = str(frame.get("sheet") or "").strip()
        if index <= 0 or index in seen or seconds < 0 or row <= 0 or column <= 0 or not sheet:
            raise JourneyPackageError(f"frames[{offset}]内容无效或重复")
        if not (index_dir / sheet).is_file():
            raise JourneyPackageError(f"抽帧拼图不存在: {sheet}")
        seen.add(index)
        result.append({**frame, "index": index, "seconds": seconds, "sheet_row": row, "sheet_col": column, "sheet": sheet})
    result.sort(key=lambda item: (item["seconds"], item["index"]))
    return result


def _materialize_contact_sheets(frames: list[dict[str, Any]], source_dir: Path, target_dir: Path) -> dict[str, dict[str, int]]:
    sheets: dict[str, dict[str, int]] = {}
    for frame in frames:
        name = str(frame["sheet"])
        values = sheets.setdefault(name, {"rows": 0, "columns": 0})
        values["rows"] = max(values["rows"], int(frame["sheet_row"]))
        values["columns"] = max(values["columns"], int(frame["sheet_col"]))
    for name in sheets:
        _materialize_file((source_dir / name).resolve(), target_dir / name)
    return sheets


def _materialize_profile_evidence(profile: dict[str, Any], source_root: Path, target_root: Path) -> None:
    for region in profile.get("regions") or []:
        for value in region.get("sample_evidence") or []:
            relative = Path(str(value).replace("\\", "/"))
            if relative.is_absolute():
                continue
            source = (source_root / relative).resolve()
            try:
                source.relative_to(source_root)
            except ValueError:
                continue
            if source.is_file():
                _materialize_file(source, target_root / relative)


def _materialize_file(source: Path, target: Path) -> None:
    source = source.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise JourneyPackageError(f"目标文件已存在: {target}")
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _materialize_evidence_file(source: Path, target: Path) -> None:
    source = source.resolve()
    if target.exists():
        if target.stat().st_size == source.stat().st_size and _sha256_file(target) == _sha256_file(source):
            return
        target.unlink()
    _materialize_file(source, target)


def _session_duration_ms(session_meta: dict[str, Any], frames: list[dict[str, Any]]) -> int:
    segments = ((session_meta.get("video") or {}).get("segments") or [])
    segment_ends = [float(item.get("end_video_ms") or 0) for item in segments if isinstance(item, dict)]
    frame_end = max(float(item["seconds"]) * 1000 for item in frames)
    return max(1, int(round(max(segment_ends + [frame_end]))))


def _manual_tags(event_kind: str) -> tuple[str, str]:
    return {
        "new_feature": ("系统", "新玩法"),
        "growth": ("系统", "新养成系统"),
        "combat": ("PVE", "其他开放"),
        "system": ("系统", "其他开放"),
        "unclassified": ("待判断", "其他开放"),
    }.get(event_kind, ("待判断", "其他开放"))


def _review_status(
    path: Path,
    key: str,
    *,
    session_id: str,
    source_fingerprint: str,
) -> tuple[str, int, int]:
    if not path.is_file():
        return "blocked", 0, 0
    payload = _read_object(path)
    values = payload.get(key) or []
    pending = int((payload.get("summary") or {}).get("pending_count", (payload.get("summary") or {}).get("pending", 0)) or 0)
    if str((payload.get("session") or {}).get("session_id") or "") != session_id:
        return "stale", len(values), pending
    if not source_fingerprint or payload.get("source_fingerprint") != source_fingerprint:
        return "stale", len(values), pending
    return str(payload.get("status") or "invalid"), len(values), pending


def _read_workspace(path: Path) -> dict[str, Any]:
    payload = _read_object(path)
    if payload.get("schema_version") != WORKSPACE_VERSION or payload.get("task_id") != WORKSPACE_TASK:
        raise JourneyPackageError("journey_workspace.json不是当前1.0契约")
    if not isinstance(payload.get("artifacts"), dict) or not isinstance(payload.get("session"), dict):
        raise JourneyPackageError("journey_workspace.json缺少artifacts或session")
    return payload


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JourneyPackageError(f"无法读取JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise JourneyPackageError(f"JSON顶层必须是对象: {path}")
    return payload


def _artifact(root: Path, artifacts: dict[str, Any], key: str) -> Path:
    value = str(artifacts.get(key) or "").strip()
    if not value:
        raise JourneyPackageError(f"工作空间缺少artifact: {key}")
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise JourneyPackageError(f"工作空间artifact越界: {key}") from exc
    return path


def _optional_artifact(root: Path, artifacts: dict[str, Any], key: str) -> Path | None:
    return _artifact(root, artifacts, key) if str(artifacts.get(key) or "").strip() else None


def _require_session(manifest: dict[str, Any], value: Any, label: str) -> None:
    if str(value or "") != str(manifest["session"]["session_id"]):
        raise JourneyPackageError(f"{label}Session与工作空间不一致")


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint_files(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _format_timecode(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"
