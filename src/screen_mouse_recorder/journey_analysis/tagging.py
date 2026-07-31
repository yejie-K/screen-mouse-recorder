from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from typing import Any


MODE_TAGS = ("PVE", "PVP", "GVG", "系统", "待判断")
EVENT_TAGS = (
    "新玩法",
    "新副本",
    "新养成系统",
    "新技能",
    "新任务系统",
    "新社交功能",
    "新商业功能",
    "其他开放",
)
METRIC_EVENT_TYPES = {
    "level_snapshot",
    "power_snapshot",
    "combat_power_snapshot",
}
FUNCTION_EVENT_TYPES = {"new_feature_unlocked", "new_skill_unlocked"}

_IGNORED_TAGS = {"", "未知", "其他", "无", "未分类"}
_TAG_ALIASES = {
    "pve": "PVE",
    "pvp": "PVP",
    "gvg": "GVG",
    "非对抗": "系统",
    "养成": "新养成系统",
    "养成系统": "新养成系统",
    "技能": "新技能",
    "副本": "新副本",
    "任务": "新任务系统",
    "日常": "新任务系统",
    "商业化": "新商业功能",
    "社交": "新社交功能",
}


def normalize_tags(values: Iterable[Any] | None, *, limit: int = 24) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("标签必须是数组")
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        tag = " ".join(str(value or "").split()).strip()
        tag = _TAG_ALIASES.get(tag, _TAG_ALIASES.get(tag.casefold(), tag))
        if tag in _IGNORED_TAGS or tag in seen:
            continue
        if len(tag) > 32:
            raise ValueError(f"标签不能超过32个字符: {tag[:32]}…")
        seen.add(tag)
        result.append(tag)
        if len(result) > limit:
            raise ValueError(f"单个事件最多允许{limit}个标签")
    return result


def observation_lane(event_type: Any) -> str:
    value = str(event_type or "")
    if value in METRIC_EVENT_TYPES:
        return "metric"
    if value in FUNCTION_EVENT_TYPES:
        return "event"
    return "unknown"


def metric_key_for_event(event_type: Any, event_name: Any = "") -> str:
    value = str(event_type or "")
    if value == "level_snapshot":
        return "level_rebirth" if "转" in str(event_name or "") else "level"
    if value in {"power_snapshot", "combat_power_snapshot"}:
        return "combat_power"
    return "unknown"


def infer_event_labels(
    annotation: dict[str, Any] | None,
    *,
    event_type: str = "",
    event_name: str = "",
) -> tuple[str, str]:
    annotation = annotation or {}
    explicit_mode = str(annotation.get("mode_tag") or "").strip()
    explicit_event = str(annotation.get("event_tag") or "").strip()
    if explicit_mode in MODE_TAGS and explicit_event in EVENT_TAGS:
        return explicit_mode, explicit_event

    legacy_tags = normalize_tags(annotation.get("tags") or [])
    dimensions = [
        *(annotation.get("interaction_mode") or []),
        *(annotation.get("gameplay_form") or []),
        *(annotation.get("object_scope") or []),
        *legacy_tags,
    ]
    normalized = normalize_tags(dimensions, limit=64)
    mode_tag = next((tag for tag in MODE_TAGS[:3] if tag in normalized), "系统")

    if str(event_type) == "new_skill_unlocked" or "新技能" in normalized:
        return mode_tag, "新技能"

    text = " ".join([str(event_name or ""), *map(str, dimensions)])
    if any(word in text for word in ("任务", "每日", "日常", "历练")):
        event_tag = "新任务系统"
    elif "副本" in text or "BOSS" in text.upper():
        event_tag = "新副本"
    elif any(word in text for word in ("社交", "聊天", "好友", "帮会", "公会")):
        event_tag = "新社交功能"
    elif any(word in text for word in ("商业", "充值", "礼包", "商城", "VIP")):
        event_tag = "新商业功能"
    elif any(word in text for word in ("养成", "伙伴", "坐骑", "装备", "宝石", "仙品", "角色")):
        event_tag = "新养成系统"
    elif str(event_type) == "new_feature_unlocked":
        event_tag = "新玩法"
    else:
        event_tag = "其他开放"
    return mode_tag, event_tag


def tags_from_annotation(
    annotation: dict[str, Any] | None,
    *,
    event_type: str = "",
    event_name: str = "",
) -> list[str]:
    if observation_lane(event_type) == "metric":
        return []
    mode_tag, event_tag = infer_event_labels(
        annotation,
        event_type=event_type,
        event_name=event_name,
    )
    return [mode_tag, event_tag]


def build_tag_catalog(*_tag_groups: Iterable[Any]) -> list[str]:
    """Compatibility helper for older callers; new UI uses two fixed catalogs."""
    return [*MODE_TAGS, *EVENT_TAGS]


def _review(source: dict[str, Any], *, lane: str) -> dict[str, Any]:
    legacy = source.get("semantic_review") or {}
    status = str(legacy.get("status") or "pending")
    if status not in {"pending", "confirmed", "excluded"}:
        status = "pending"
    return {
        "status": "pending",
        "reviewer": "",
        "reviewed_at": "",
        "note": (
            "指标线需独立复核；未沿用旧事件线结论"
            if lane == "metric"
            else "两组事件标签为迁移候选，需重新人工确认"
        ),
        "legacy_event_review_status": status,
    }


def split_confirmed_v1_to_parallel_v2(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_events = payload.get("events")
    if not isinstance(source_events, list):
        raise ValueError("v1确认文件缺少events数组")
    event_observations = []
    metric_observations = []
    session_id = str((payload.get("session") or {}).get("session_id") or "")
    for source in source_events:
        if not isinstance(source, dict):
            continue
        event_id = str(source.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("v1事件缺少event_id")
        event_type = str(source.get("event_type") or "")
        event_name = str(source.get("event_name") or "")
        common = {
            "observation_id": event_id,
            "session_id": str(source.get("session_id") or session_id),
            "time_ms": int(source.get("global_time_ms", source.get("time_ms", 0)) or 0),
            "timestamp": str(source.get("timestamp") or ""),
            "source": "legacy_v1",
            "evidence": deepcopy(source.get("evidence") or {}),
        }
        lane = observation_lane(event_type)
        if lane == "metric":
            metric_observations.append({
                **common,
                "metric_key": metric_key_for_event(event_type, event_name),
                "raw_text": event_name,
                "ocr_text": str(source.get("ocr_excerpt") or ""),
                "parsed_value": None,
                "unit": "",
                "region_id": "",
                "review": _review(source, lane="metric"),
            })
            continue
        if lane != "event":
            continue
        mode_tag, event_tag = infer_event_labels(
            source.get("semantic") or {},
            event_type=event_type,
            event_name=event_name,
        )
        event_observations.append({
            **common,
            "event_name": event_name,
            "ocr_text": str(source.get("ocr_excerpt") or ""),
            "mode_tag": mode_tag,
            "event_tag": event_tag,
            "region_group_id": "",
            "review": _review(source, lane="event"),
        })

    def package(task_id: str, key: str, values: list[dict[str, Any]]) -> dict[str, Any]:
        counts = Counter(item["review"]["status"] for item in values)
        return {
            "schema_version": "2.0",
            "task_id": task_id,
            "source_fingerprint": str(payload.get("source_fingerprint") or ""),
            "status": "complete" if not counts["pending"] else "needs_review",
            "scan_scope": "legacy_confirmed_events",
            "session": deepcopy(payload.get("session") or {}),
            "summary": {
                "observation_count": len(values),
                "pending": counts["pending"],
                "confirmed": counts["confirmed"],
                "excluded": counts["excluded"],
            },
            key: values,
            "compatibility": {
                "source_task_id": str(payload.get("task_id") or ""),
                "legacy_fields_preserved_in_source": True,
            },
        }

    return (
        package("JOURNEY_EVENT_OBSERVATIONS_V2", "events", event_observations),
        package("JOURNEY_METRIC_OBSERVATIONS_V2", "metrics", metric_observations),
    )


def convert_confirmed_v1_to_tagged_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Deprecated compatibility wrapper returning the event lane only."""
    events, _metrics = split_confirmed_v1_to_parallel_v2(payload)
    return events
