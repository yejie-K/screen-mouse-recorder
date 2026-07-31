from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .rules import classify_event, suggest_emotion_rule_ids
from .rules import score_emotion
from .tagging import EVENT_TAGS, MODE_TAGS, normalize_tags


class JourneyPackageError(ValueError):
    pass


def _clean_text(value: Any, limit: int = 360) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _basename(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    return text.rsplit("/", 1)[-1] if text else ""


def _time_ms(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JourneyPackageError(f"{field} 必须是数字")
    result = int(round(value))
    if result < 0:
        raise JourneyPackageError(f"{field} 不能小于0")
    return result


def build_semantic_input(
    source_path: Path,
    payload: dict[str, Any],
    taxonomy: dict[str, Any],
    emotion_rules: dict[str, Any],
    *,
    session_id: str,
    total_play_time_ms: int | None = None,
) -> dict[str, Any]:
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise JourneyPackageError("确认结果缺少 events 数组")
    if payload.get("task_id") == "JOURNEY_CONFIRMED_SEMANTIC_V1":
        raw_events = [
            event
            for event in raw_events
            if isinstance(event, dict)
            and (event.get("semantic_review") or {}).get("status") == "confirmed"
        ]
        if not raw_events:
            raise JourneyPackageError("确认语义结果中没有可进入正式产物的confirmed事件")
    events = []
    used_ids: set[str] = set()
    for raw in raw_events:
        if not isinstance(raw, dict):
            continue
        event_id = str(raw.get("event_id") or "").strip()
        event_name = str(raw.get("event_name") or "").strip()
        event_type = str(raw.get("event_type") or "unknown").strip()
        if not event_id or not event_name:
            raise JourneyPackageError("确认事件缺少 event_id 或 event_name")
        if event_id in used_ids:
            raise JourneyPackageError(f"确认事件ID重复: {event_id}")
        used_ids.add(event_id)
        video_time_ms = _time_ms(raw.get("time_ms"), f"events[{event_id}].time_ms")
        global_time_ms = _time_ms(raw.get("global_time_ms", video_time_ms), f"events[{event_id}].global_time_ms")
        virtual_day_ms = 60 * 60 * 1000
        hints = classify_event(raw, taxonomy)
        confirmed_semantic = raw.get("semantic")
        if isinstance(confirmed_semantic, dict):
            classification = hints["classification"]
            for field in (
                "event_category",
                "object_scope",
                "interaction_mode",
                "gameplay_form",
                "rhythm_category",
                "mode_tag",
                "event_tag",
            ):
                if field in confirmed_semantic:
                    classification[field] = deepcopy(confirmed_semantic[field])
            matched_rules = confirmed_semantic.get("matched_gameplay_rule_ids")
            if isinstance(matched_rules, list):
                hints["matched_gameplay_rule_ids"] = list(map(str, matched_rules))
        hints["suggested_emotion_rule_ids"] = suggest_emotion_rule_ids(raw, hints["classification"])
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
        events.append({
            "event_id": event_id,
            "session_id": str(raw.get("session_id") or session_id),
            "time_ms": video_time_ms,
            "video_time_ms": video_time_ms,
            "global_time_ms": global_time_ms,
            "play_day_index": global_time_ms // virtual_day_ms + 1,
            "day_time_ms": global_time_ms % virtual_day_ms,
            "timestamp": str(raw.get("timestamp") or ""),
            "event_type": event_type,
            "event_name": event_name,
            "ocr_excerpt": _clean_text(raw.get("ocr_text", raw.get("ocr_excerpt"))),
            "evidence": {
                "source_image": _basename(raw.get("source_image", evidence.get("source_image"))),
                "review_image": _basename(raw.get("review_image", evidence.get("review_image"))),
                "contact_sheet": _basename(raw.get("contact_sheet", evidence.get("contact_sheet"))),
                "sheet_row": (
                    raw.get("sheet_row", evidence.get("sheet_row"))
                    if isinstance(raw.get("sheet_row", evidence.get("sheet_row")), int)
                    else None
                ),
                "sheet_col": (
                    raw.get("sheet_col", evidence.get("sheet_col"))
                    if isinstance(raw.get("sheet_col", evidence.get("sheet_col")), int)
                    else None
                ),
            },
            "deterministic_hints": hints,
        })
    events.sort(key=lambda item: (item["global_time_ms"], item["event_id"]))
    type_counts = Counter(event["event_type"] for event in events)
    max_event_time_ms = max(event["global_time_ms"] for event in events)
    payload_duration = payload.get("total_play_time_ms", payload.get("duration_ms"))
    if total_play_time_ms is None and isinstance(payload_duration, (int, float)) and not isinstance(payload_duration, bool):
        total_play_time_ms = int(round(payload_duration))
    total_play_time_ms = max(max_event_time_ms, int(total_play_time_ms or 0))
    virtual_day_ms = 60 * 60 * 1000
    virtual_day_count = max(
        1,
        (total_play_time_ms + virtual_day_ms - 1) // virtual_day_ms,
        max(event["play_day_index"] for event in events),
    )
    return {
        "schema_version": "1.1",
        "task_id": "JOURNEY_SEMANTIC_V1",
        "source_fingerprint": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "rule_versions": {
            "gameplay": str(taxonomy.get("rule_set_id") or ""),
            "emotion": str(emotion_rules.get("rule_set_id") or ""),
        },
        "session": {
            "session_id": session_id,
            "confirmed_at": str(payload.get("confirmed_at") or ""),
            "duration_ms": total_play_time_ms,
            "total_play_time_ms": total_play_time_ms,
            "virtual_day_minutes": 60,
            "virtual_day_count": virtual_day_count,
            "event_count": len(events),
            "event_type_counts": dict(sorted(type_counts.items())),
        },
        "events": events,
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_semantic_output(
    payload: dict[str, Any],
    semantic_input: dict[str, Any],
    taxonomy: dict[str, Any],
    emotion_rules: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != "1.0":
        errors.append("schema_version 必须为1.0")
    if payload.get("task_id") != "JOURNEY_SEMANTIC_V1":
        errors.append("task_id 必须为JOURNEY_SEMANTIC_V1")
    if payload.get("source_fingerprint") != semantic_input.get("source_fingerprint"):
        errors.append("source_fingerprint 与输入不一致")
    annotations = payload.get("event_annotations")
    if not isinstance(annotations, list):
        errors.append("event_annotations 必须是数组")
        return errors
    known_event_ids = {event["event_id"] for event in semantic_input["events"]}
    known_gameplay_rules = {
        str(rule.get("rule_id")) for rule in taxonomy["rules"] if isinstance(rule, dict)
    }
    known_emotion_rules = {
        str(rule.get("rule_id")) for rule in emotion_rules["rules"] if isinstance(rule, dict)
    }
    dimensions = taxonomy.get("dimensions") or {}
    seen: set[str] = set()
    for index, annotation in enumerate(annotations):
        field = f"event_annotations[{index}]"
        if not isinstance(annotation, dict):
            errors.append(f"{field} 必须是对象")
            continue
        event_id = str(annotation.get("event_id") or "")
        if event_id not in known_event_ids:
            errors.append(f"{field}.event_id 无效")
        if event_id in seen:
            errors.append(f"{field}.event_id 重复")
        seen.add(event_id)
        if annotation.get("review_status") not in {"needs_review", "excluded"}:
            errors.append(f"{field}.review_status 不能写成已确认")
        for key in ("object_scope", "interaction_mode", "gameplay_form", "rhythm_category"):
            values = annotation.get(key)
            if not isinstance(values, list):
                errors.append(f"{field}.{key} 必须是数组")
                continue
            unknown = sorted(set(map(str, values)) - set(dimensions.get(key) or []))
            if unknown:
                errors.append(f"{field}.{key} 包含未知值: {', '.join(unknown)}")
        if "tags" in annotation:
            tags = annotation.get("tags")
            if not isinstance(tags, list):
                errors.append(f"{field}.tags 必须是数组")
            else:
                try:
                    normalized = normalize_tags(tags)
                except ValueError as exc:
                    errors.append(f"{field}.tags 无效: {exc}")
                else:
                    if normalized != tags:
                        errors.append(f"{field}.tags 必须使用规范化标签且不能重复或包含空值")
        if "mode_tag" in annotation and annotation.get("mode_tag") not in MODE_TAGS:
            errors.append(f"{field}.mode_tag 无效")
        if "event_tag" in annotation and annotation.get("event_tag") not in EVENT_TAGS:
            errors.append(f"{field}.event_tag 无效")
        event_category = str(annotation.get("event_category") or "")
        if event_category not in set(dimensions.get("event_category") or []):
            errors.append(f"{field}.event_category 无效")
        gameplay_ids = annotation.get("matched_gameplay_rule_ids") or []
        emotion_ids = annotation.get("matched_emotion_rule_ids") or []
        unknown_gameplay = sorted(set(map(str, gameplay_ids)) - known_gameplay_rules)
        unknown_emotion = sorted(set(map(str, emotion_ids)) - known_emotion_rules)
        if unknown_gameplay:
            errors.append(f"{field} 引用未知玩法规则: {', '.join(unknown_gameplay)}")
        if unknown_emotion:
            errors.append(f"{field} 引用未知情绪规则: {', '.join(unknown_emotion)}")
        repeat_index = annotation.get("repeat_index")
        if not isinstance(repeat_index, int) or isinstance(repeat_index, bool) or repeat_index < 1:
            errors.append(f"{field}.repeat_index 必须是正整数")
        if not unknown_emotion and isinstance(repeat_index, int) and repeat_index >= 1:
            expected = score_emotion(
                list(map(str, emotion_ids)),
                emotion_rules,
                repeat_index=repeat_index,
                has_new_value=bool(annotation.get("has_new_value")),
                creative_high_value=bool(annotation.get("creative_high_value")),
            )["score"]
            candidate = annotation.get("emotion_score_candidate")
            if candidate is not None and candidate != expected:
                errors.append(f"{field}.emotion_score_candidate 应由规则计算为 {expected}")
        relations = annotation.get("output_relations")
        if not isinstance(relations, list):
            errors.append(f"{field}.output_relations 必须是数组")
        else:
            for relation_index, relation in enumerate(relations):
                evidence = relation.get("evidence_event_ids") if isinstance(relation, dict) else None
                if not isinstance(evidence, list) or not evidence:
                    errors.append(f"{field}.output_relations[{relation_index}] 缺少证据事件")
                    continue
                unknown_evidence = sorted(set(map(str, evidence)) - known_event_ids)
                if unknown_evidence:
                    errors.append(
                        f"{field}.output_relations[{relation_index}] 引用未知证据: {', '.join(unknown_evidence)}"
                    )
    return errors


SEMANTIC_OVERRIDE_FIELDS = {
    "tags",
    "mode_tag",
    "event_tag",
    "event_category",
    "object_scope",
    "interaction_mode",
    "gameplay_form",
    "rhythm_category",
    "player_action",
    "system_feedback",
    "matched_gameplay_rule_ids",
    "matched_emotion_rule_ids",
    "repeat_group_key",
    "repeat_index",
    "has_new_value",
    "creative_high_value",
    "output_relations",
    "confidence",
}


def build_semantic_review_template(
    ai_output: dict[str, Any],
    semantic_input: dict[str, Any],
    taxonomy: dict[str, Any],
    emotion_rules: dict[str, Any],
) -> dict[str, Any]:
    errors = validate_semantic_output(ai_output, semantic_input, taxonomy, emotion_rules)
    if errors:
        raise JourneyPackageError(f"AI语义输出校验失败，共{len(errors)}项: {errors[0]}")
    snapshot_fields = (
        "tags",
        "mode_tag",
        "event_tag",
        "event_category",
        "object_scope",
        "interaction_mode",
        "gameplay_form",
        "rhythm_category",
        "matched_emotion_rule_ids",
        "emotion_score_candidate",
        "confidence",
        "review_status",
    )
    decisions = []
    for annotation in ai_output["event_annotations"]:
        decisions.append({
            "event_id": annotation["event_id"],
            "decision": "pending",
            "candidate_snapshot": {
                field: annotation.get(field)
                for field in snapshot_fields
            },
            "overrides": {},
            "review_note": "",
            "save_to_game_profile": False,
            "game_term": "",
        })
    return {
        "schema_version": "1.0",
        "task_id": "JOURNEY_SEMANTIC_REVIEW_V1",
        "source_fingerprint": semantic_input["source_fingerprint"],
        "reviewed_at": "",
        "reviewer": "",
        "decisions": decisions,
    }


def finalize_semantic_review(
    semantic_input: dict[str, Any],
    ai_output: dict[str, Any],
    review: dict[str, Any],
    taxonomy: dict[str, Any],
    emotion_rules: dict[str, Any],
) -> dict[str, Any]:
    ai_errors = validate_semantic_output(ai_output, semantic_input, taxonomy, emotion_rules)
    if ai_errors:
        raise JourneyPackageError(f"AI语义输出校验失败，共{len(ai_errors)}项: {ai_errors[0]}")
    if review.get("schema_version") != "1.0" or review.get("task_id") != "JOURNEY_SEMANTIC_REVIEW_V1":
        raise JourneyPackageError("语义复核文件版本或task_id无效")
    if review.get("source_fingerprint") != semantic_input.get("source_fingerprint"):
        raise JourneyPackageError("语义复核文件source_fingerprint与输入不一致")
    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        raise JourneyPackageError("语义复核文件decisions必须是数组")
    decision_map: dict[str, dict[str, Any]] = {}
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise JourneyPackageError(f"decisions[{index}]必须是对象")
        event_id = str(decision.get("event_id") or "")
        if not event_id or event_id in decision_map:
            raise JourneyPackageError(f"decisions[{index}].event_id缺失或重复")
        if decision.get("decision") not in {"pending", "confirmed", "excluded"}:
            raise JourneyPackageError(f"decisions[{index}].decision无效")
        overrides = decision.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise JourneyPackageError(f"decisions[{index}].overrides必须是对象")
        forbidden = sorted(set(overrides) - SEMANTIC_OVERRIDE_FIELDS)
        if forbidden:
            raise JourneyPackageError(
                f"decisions[{index}].overrides包含禁止字段: {', '.join(forbidden)}"
            )
        decision_map[event_id] = decision

    has_final_decision = any(
        decision["decision"] in {"confirmed", "excluded"}
        for decision in decision_map.values()
    )
    if has_final_decision and not str(review.get("reviewer") or "").strip():
        raise JourneyPackageError("存在已确认或排除决定时reviewer不能为空")
    if has_final_decision and not str(review.get("reviewed_at") or "").strip():
        raise JourneyPackageError("存在已确认或排除决定时reviewed_at不能为空")

    source_events = {event["event_id"]: event for event in semantic_input["events"]}
    candidate_map = {
        annotation["event_id"]: annotation
        for annotation in ai_output["event_annotations"]
    }
    unknown_decisions = sorted(set(decision_map) - set(source_events))
    if unknown_decisions:
        raise JourneyPackageError(f"复核引用未知事件: {', '.join(unknown_decisions)}")

    final_events = []
    counts = Counter()
    pending_event_ids = []
    for event_id, source_event in source_events.items():
        candidate = candidate_map.get(event_id)
        decision = decision_map.get(event_id)
        if candidate is None or decision is None or decision["decision"] == "pending":
            status = "pending"
            pending_event_ids.append(event_id)
            counts[status] += 1
            final_events.append({
                **source_event,
                "semantic": candidate,
                "semantic_review": {
                    "status": status,
                    "reviewer": str(review.get("reviewer") or ""),
                    "reviewed_at": str(review.get("reviewed_at") or ""),
                    "review_note": str((decision or {}).get("review_note") or ""),
                },
            })
            continue
        status = str(decision["decision"])
        merged = {**candidate, **(decision.get("overrides") or {})}
        merged["event_id"] = event_id
        merged["review_status"] = "needs_review"
        score_result = score_emotion(
            list(map(str, merged.get("matched_emotion_rule_ids") or [])),
            emotion_rules,
            repeat_index=int(merged.get("repeat_index") or 1),
            has_new_value=bool(merged.get("has_new_value")),
            creative_high_value=bool(merged.get("creative_high_value")),
        )
        merged["emotion_score_candidate"] = score_result["score"]
        validation_payload = {
            **ai_output,
            "event_annotations": [merged],
        }
        merged_errors = validate_semantic_output(
            validation_payload,
            semantic_input,
            taxonomy,
            emotion_rules,
        )
        if merged_errors:
            raise JourneyPackageError(
                f"事件{event_id}复核结果无效，共{len(merged_errors)}项: {merged_errors[0]}"
            )
        merged["review_status"] = status
        merged["emotion_score"] = score_result["score"]
        merged["emotion_score_detail"] = score_result
        counts[status] += 1
        final_events.append({
            **source_event,
            "semantic": merged,
            "semantic_review": {
                "status": status,
                "reviewer": str(review.get("reviewer") or ""),
                "reviewed_at": str(review.get("reviewed_at") or ""),
                "review_note": str(decision.get("review_note") or ""),
            },
        })
    return {
        "schema_version": "1.0",
        "task_id": "JOURNEY_CONFIRMED_SEMANTIC_V1",
        "source_fingerprint": semantic_input["source_fingerprint"],
        "status": "complete" if not pending_event_ids else "needs_review",
        "session": semantic_input["session"],
        "reviewed_at": str(review.get("reviewed_at") or ""),
        "reviewer": str(review.get("reviewer") or ""),
        "summary": {
            "event_count": len(final_events),
            "confirmed_count": counts["confirmed"],
            "excluded_count": counts["excluded"],
            "pending_count": counts["pending"],
        },
        "pending_event_ids": pending_event_ids,
        "events": final_events,
    }
