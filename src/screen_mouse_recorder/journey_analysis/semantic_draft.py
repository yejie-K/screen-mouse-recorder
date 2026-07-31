from __future__ import annotations

from collections import defaultdict
from typing import Any

from .tagging import infer_event_labels


def build_semantic_draft(
    semantic_input: dict[str, Any],
    taxonomy: dict[str, Any],
    emotion_rules: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic, review-only semantic candidate package."""
    dimensions = taxonomy.get("dimensions") or {}
    known_categories = set(dimensions.get("event_category") or [])
    by_event_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in emotion_rules.get("rules", []):
        if isinstance(rule, dict) and rule.get("event_type"):
            by_event_type[str(rule["event_type"])].append(rule)

    def emotion_ids_for(category: str, repeat_index: int) -> list[str]:
        rules = by_event_type.get(category) or []
        scored = [rule for rule in rules if isinstance(rule.get("score"), int)]
        if not scored:
            return []
        pick = (
            max(scored, key=lambda rule: rule["score"])
            if repeat_index <= 1
            else min(scored, key=lambda rule: rule["score"])
        )
        return [str(pick["rule_id"])]

    seen_names: dict[str, int] = defaultdict(int)
    annotations: list[dict[str, Any]] = []
    review_items: list[dict[str, str]] = []
    for event in semantic_input["events"]:
        event_id = str(event["event_id"])
        name = str(event.get("event_name") or "")
        hints = event.get("deterministic_hints") or {}
        classification = hints.get("classification") or {}
        seen_names[name] += 1
        repeat_index = seen_names[name]
        gameplay_ids = _list(hints.get("matched_gameplay_rule_ids"))
        category = str(classification.get("event_category") or "")
        if category not in known_categories:
            category = "其他"
            review_items.append({
                "event_id": event_id,
                "reason": "规则初分未给出有效事件分类",
                "suggested_action": "人工确认事件分类",
            })
        object_scope = _list(classification.get("object_scope"))
        interaction_mode = _list(classification.get("interaction_mode"))
        gameplay_form = _list(classification.get("gameplay_form"))
        rhythm_category = _list(classification.get("rhythm_category"))
        if "未知" in object_scope or "未知" in interaction_mode or not gameplay_ids:
            review_items.append({
                "event_id": event_id,
                "reason": "分类含未知项或缺少玩法规则命中",
                "suggested_action": "人工核对截图证据后补全分类",
            })
        mode_tag, event_tag = infer_event_labels(
            classification,
            event_type=str(event.get("event_type") or ""),
            event_name=name,
        )
        annotations.append({
            "event_id": event_id,
            "tags": [mode_tag, event_tag],
            "mode_tag": mode_tag,
            "event_tag": event_tag,
            "event_category": category,
            "object_scope": object_scope,
            "interaction_mode": interaction_mode,
            "gameplay_form": gameplay_form,
            "rhythm_category": rhythm_category,
            "player_action": f"触发事件：{name}",
            "system_feedback": f"系统提示{event.get('event_type')}：{name}",
            "matched_gameplay_rule_ids": gameplay_ids,
            "matched_emotion_rule_ids": emotion_ids_for(category, repeat_index),
            "repeat_group_key": name or event_id,
            "repeat_index": repeat_index,
            "has_new_value": repeat_index == 1,
            "creative_high_value": False,
            "emotion_score_candidate": None,
            "emotion_reason": "情绪分值由复核终结器按规则计算",
            "output_relations": [],
            "confidence": 0.6 if gameplay_ids else 0.3,
            "review_status": "needs_review",
        })
    return {
        "schema_version": "1.0",
        "task_id": "JOURNEY_SEMANTIC_V1",
        "source_fingerprint": semantic_input["source_fingerprint"],
        "event_annotations": annotations,
        "review_items": review_items,
        "blocked_items": [],
    }


def _list(values: Any) -> list[str]:
    if isinstance(values, list):
        return [str(value) for value in values]
    if values in (None, ""):
        return []
    return [str(values)]
