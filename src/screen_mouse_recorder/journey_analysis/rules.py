from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JourneyRuleError(ValueError):
    pass


def load_rule_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JourneyRuleError(f"无法读取规则文件 {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise JourneyRuleError(f"规则文件版本无效: {path}")
    if not isinstance(payload.get("rules"), list):
        raise JourneyRuleError(f"规则文件缺少 rules 数组: {path}")
    return payload


def _append_labels(target: dict[str, Any], labels: dict[str, Any]) -> None:
    for key, value in labels.items():
        if isinstance(value, list):
            current = target.setdefault(key, [])
            for item in value:
                if item not in current:
                    current.append(item)
        elif value not in (None, ""):
            target[key] = value


def classify_event(event: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("event_type") or "")
    searchable = f"{event.get('event_name', '')} {event.get('ocr_text', '')}".casefold()
    matched: list[tuple[int, str]] = []
    classification: dict[str, Any] = {
        "event_category": "其他",
        "object_scope": [],
        "interaction_mode": [],
        "gameplay_form": [],
        "rhythm_category": [],
    }
    for raw_rule in taxonomy["rules"]:
        if not isinstance(raw_rule, dict):
            continue
        match = raw_rule.get("match") if isinstance(raw_rule.get("match"), dict) else {}
        event_types = match.get("event_types") if isinstance(match.get("event_types"), list) else []
        keywords = match.get("keywords") if isinstance(match.get("keywords"), list) else []
        if event_types and event_type not in event_types:
            continue
        if keywords and not any(str(keyword).casefold() in searchable for keyword in keywords):
            continue
        if not event_types and not keywords:
            continue
        rule_id = str(raw_rule.get("rule_id") or "").strip()
        if not rule_id:
            continue
        matched.append((int(raw_rule.get("priority") or 0), rule_id))
        labels = raw_rule.get("labels") if isinstance(raw_rule.get("labels"), dict) else {}
        _append_labels(classification, labels)
    matched.sort(key=lambda item: (-item[0], item[1]))
    if not classification["object_scope"]:
        classification["object_scope"] = ["未知"]
    if not classification["interaction_mode"]:
        classification["interaction_mode"] = ["未知"]
    if not classification["gameplay_form"]:
        classification["gameplay_form"] = ["未知"]
    if not classification["rhythm_category"]:
        classification["rhythm_category"] = ["其他"]
    return {
        "matched_gameplay_rule_ids": [rule_id for _priority, rule_id in matched],
        "classification": classification,
    }


def suggest_emotion_rule_ids(event: dict[str, Any], classification: dict[str, Any]) -> list[str]:
    event_type = str(event.get("event_type") or "")
    forms = set(classification.get("gameplay_form") or [])
    modes = set(classification.get("interaction_mode") or [])
    if event_type == "new_feature_unlocked":
        if modes & {"PVE", "PVP", "GVG", "社交"} or forms & {"副本", "BOSS", "活动"}:
            return ["EMO-PLAY-001"]
        return ["EMO-PLAY-003"]
    if event_type == "new_skill_unlocked":
        return ["EMO-PLAY-003"]
    return []


def score_emotion(
    matched_rule_ids: list[str],
    emotion_rules: dict[str, Any],
    *,
    repeat_index: int = 1,
    has_new_value: bool = True,
    creative_high_value: bool = False,
) -> dict[str, Any]:
    rule_map = {
        str(rule.get("rule_id")): rule
        for rule in emotion_rules["rules"]
        if isinstance(rule, dict) and rule.get("rule_id")
    }
    unknown = sorted(set(matched_rule_ids) - set(rule_map))
    if unknown:
        raise JourneyRuleError(f"未知情绪规则: {', '.join(unknown)}")
    scores = [int(rule_map[rule_id]["score"]) for rule_id in matched_rule_ids]
    if not scores:
        return {"score": None, "base_score": None, "adjustments": [], "matched_rule_ids": []}
    policy = emotion_rules.get("scoring_policy") or {}
    base = max(scores)
    score = base
    adjustments: list[str] = []
    if creative_high_value:
        score = int(policy.get("creative_high_value_override", 3))
        adjustments.append("creative_high_value_override")
    elif repeat_index > 1 and not has_new_value:
        score += int(policy.get("repeat_without_new_value_delta", -1))
        adjustments.append("repeat_without_new_value")
    score_range = emotion_rules.get("score_range") or {"minimum": -2, "maximum": 3}
    if policy.get("clamp_to_score_range", True):
        score = max(int(score_range["minimum"]), min(int(score_range["maximum"]), score))
    return {
        "score": score,
        "base_score": base,
        "adjustments": adjustments,
        "matched_rule_ids": matched_rule_ids,
    }
