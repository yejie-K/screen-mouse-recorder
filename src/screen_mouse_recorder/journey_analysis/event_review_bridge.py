from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .package import (
    JourneyPackageError,
    build_semantic_input,
    build_semantic_review_template,
    finalize_semantic_review,
    write_json_atomic,
)
from .rules import load_rule_file
from .semantic_draft import build_semantic_draft
from .tagging import EVENT_TAGS, MODE_TAGS


EVENT_OBSERVATIONS_VERSION = "2.0"
EVENT_OBSERVATIONS_TASK = "JOURNEY_EVENT_OBSERVATIONS_V2"


def validate_event_candidates(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != EVENT_OBSERVATIONS_VERSION:
        raise JourneyPackageError("功能事件候选schema_version必须为2.0")
    if payload.get("task_id") != EVENT_OBSERVATIONS_TASK:
        raise JourneyPackageError("功能事件候选task_id无效")
    if not str(payload.get("source_fingerprint") or "").strip():
        raise JourneyPackageError("功能事件候选缺少source_fingerprint")
    events = payload.get("events")
    if not isinstance(events, list):
        raise JourneyPackageError("功能事件候选events必须是数组")
    seen: set[str] = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise JourneyPackageError(f"events[{index}]必须是对象")
        observation_id = str(event.get("observation_id") or "").strip()
        if not observation_id or observation_id in seen:
            raise JourneyPackageError(f"events[{index}].observation_id缺失或重复")
        seen.add(observation_id)
        if not str(event.get("event_name") or "").strip():
            raise JourneyPackageError(f"events[{index}].event_name缺失")
        if event.get("mode_tag") not in MODE_TAGS:
            raise JourneyPackageError(f"events[{index}].mode_tag无效")
        if event.get("event_tag") not in EVENT_TAGS:
            raise JourneyPackageError(f"events[{index}].event_tag无效")
        review = event.get("review")
        if not isinstance(review, dict) or review.get("status") not in {"pending", "confirmed", "excluded"}:
            raise JourneyPackageError(f"events[{index}].review无效")


def build_semantic_input_from_event_candidates(
    source_path: Path,
    candidates: dict[str, Any],
    taxonomy: dict[str, Any],
    emotion_rules: dict[str, Any],
    *,
    total_play_time_ms: int | None = None,
) -> dict[str, Any]:
    validate_event_candidates(candidates)
    session = candidates.get("session") or {}
    session_id = str(session.get("session_id") or "").strip()
    if not session_id:
        raise JourneyPackageError("功能事件候选缺少session.session_id")
    normalized_events = []
    for event in candidates["events"]:
        evidence = event.get("evidence") or {}
        crop_images = evidence.get("crop_images") or []
        review_image = crop_images[0] if isinstance(crop_images, list) and crop_images else ""
        normalized_events.append({
            "event_id": str(event["observation_id"]),
            "session_id": str(event.get("session_id") or session_id),
            "time_ms": int(event.get("time_ms") or 0),
            "global_time_ms": int(event.get("time_ms") or 0),
            "timestamp": str(event.get("timestamp") or ""),
            "event_type": _event_type(str(event.get("event_tag") or "")),
            "event_name": str(event.get("event_name") or ""),
            "ocr_text": str(event.get("ocr_text") or ""),
            "source_image": str(evidence.get("source_image") or ""),
            "review_image": str(review_image),
            "contact_sheet": str(evidence.get("contact_sheet") or ""),
            "sheet_row": evidence.get("sheet_row"),
            "sheet_col": evidence.get("sheet_col"),
        })
    source_payload = {
        "confirmed_at": "",
        "duration_ms": max(
            [int(event.get("last_time_ms", event.get("time_ms", 0)) or 0) for event in candidates["events"]]
            or [0]
        ),
        "events": normalized_events,
    }
    semantic_input = build_semantic_input(
        source_path,
        source_payload,
        taxonomy,
        emotion_rules,
        session_id=session_id,
        total_play_time_ms=total_play_time_ms,
    )
    candidate_map = {str(event["observation_id"]): event for event in candidates["events"]}
    for event in semantic_input["events"]:
        candidate = candidate_map[event["event_id"]]
        event["source"] = str(candidate.get("source") or "automatic")
        classification = event["deterministic_hints"]["classification"]
        classification["mode_tag"] = candidate["mode_tag"]
        classification["event_tag"] = candidate["event_tag"]
    return semantic_input


def build_event_review_bundle(
    source_path: Path,
    output_dir: Path,
    *,
    taxonomy_path: Path,
    emotion_rules_path: Path,
    total_play_time_ms: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    candidates = _read_object(source_path)
    validate_event_candidates(candidates)
    if not candidates["events"]:
        raise JourneyPackageError("功能事件候选为空，不能创建复核包")
    targets = {
        "semantic_input": output_dir / "journey_semantic_input.json",
        "semantic_output": output_dir / "journey_semantic_output.json",
        "semantic_review": output_dir / "journey_semantic_review.json",
        "confirmed_events": output_dir / "confirmed_semantic_events.json",
        "manifest": output_dir / "event_review_manifest.json",
    }
    existing = [path.name for path in targets.values() if path.exists()]
    if existing and not overwrite:
        raise JourneyPackageError("事件复核包已存在: " + ", ".join(sorted(existing)))
    taxonomy = load_rule_file(taxonomy_path)
    emotion_rules = load_rule_file(emotion_rules_path)
    semantic_input = build_semantic_input_from_event_candidates(
        source_path,
        candidates,
        taxonomy,
        emotion_rules,
        total_play_time_ms=total_play_time_ms,
    )
    semantic_output = build_semantic_draft(semantic_input, taxonomy, emotion_rules)
    semantic_review = build_semantic_review_template(
        semantic_output,
        semantic_input,
        taxonomy,
        emotion_rules,
    )
    manual_event_ids = {
        str(event["observation_id"])
        for event in candidates["events"]
        if event.get("source") == "manual"
    }
    if manual_event_ids:
        annotations = {item["event_id"]: item for item in semantic_output["event_annotations"]}
        for decision in semantic_review["decisions"]:
            if decision["event_id"] not in manual_event_ids:
                continue
            annotation = annotations[decision["event_id"]]
            decision.update({
                "decision": "confirmed",
                "overrides": {
                    "mode_tag": annotation["mode_tag"],
                    "event_tag": annotation["event_tag"],
                    "tags": list(annotation["tags"]),
                },
                "review_note": "人工选帧工作台已确认，跳过OCR候选复核",
            })
        semantic_review["reviewer"] = "人工选帧工作台"
        semantic_review["reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    confirmed_events = finalize_semantic_review(
        semantic_input,
        semantic_output,
        semantic_review,
        taxonomy,
        emotion_rules,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, payload in (
        ("semantic_input", semantic_input),
        ("semantic_output", semantic_output),
        ("semantic_review", semantic_review),
        ("confirmed_events", confirmed_events),
    ):
        write_json_atomic(targets[key], payload)
    manifest = {
        "schema_version": "1.0",
        "task_id": "JOURNEY_EVENT_REVIEW_BUNDLE_V2",
        "status": "needs_review" if len(manual_event_ids) < len(candidates["events"]) else "complete",
        "session_id": str((candidates.get("session") or {}).get("session_id") or ""),
        "upstream": {
            "file": source_path.name,
            "schema_version": candidates["schema_version"],
            "task_id": candidates["task_id"],
            "source_fingerprint": candidates["source_fingerprint"],
        },
        "review_source_fingerprint": semantic_input["source_fingerprint"],
        "event_count": len(candidates["events"]),
        "manual_confirmed_count": len(manual_event_ids),
        "review_candidate_count": len(candidates["events"]) - len(manual_event_ids),
        "files": {
            key: {
                "path": path.name,
                "schema_version": _read_object(path)["schema_version"],
            }
            for key, path in targets.items()
            if key != "manifest"
        },
    }
    write_json_atomic(targets["manifest"], manifest)
    return deepcopy(manifest)


def _event_type(event_tag: str) -> str:
    return "new_skill_unlocked" if event_tag == "新技能" else "new_feature_unlocked"


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JourneyPackageError(f"无法读取JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise JourneyPackageError(f"JSON顶层必须是对象: {path}")
    return payload
