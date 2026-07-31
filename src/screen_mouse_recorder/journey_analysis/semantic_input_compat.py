from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from .package import JourneyPackageError


SEMANTIC_INPUT_VERSION = "1.1"


def validate_semantic_input(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SEMANTIC_INPUT_VERSION:
        raise JourneyPackageError(
            "语义输入schema_version必须为1.1；旧1.0请先运行migrate_semantic_input_v1.py",
        )
    if payload.get("task_id") != "JOURNEY_SEMANTIC_V1":
        raise JourneyPackageError("语义输入task_id无效")
    fingerprint = str(payload.get("source_fingerprint") or "")
    if len(fingerprint) != 64:
        raise JourneyPackageError("语义输入source_fingerprint无效")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise JourneyPackageError("语义输入events必须是非空数组")
    seen: set[str] = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise JourneyPackageError(f"events[{index}]必须是对象")
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in seen:
            raise JourneyPackageError(f"events[{index}].event_id缺失或重复")
        seen.add(event_id)


def migrate_semantic_input_v1(payload: dict[str, Any]) -> dict[str, Any]:
    version = str(payload.get("schema_version") or "")
    if version == SEMANTIC_INPUT_VERSION:
        result = deepcopy(payload)
        validate_semantic_input(result)
        return result
    if version != "1.0" or payload.get("task_id") != "JOURNEY_SEMANTIC_V1":
        raise JourneyPackageError("只支持迁移JOURNEY_SEMANTIC_V1的schema 1.0输入")
    result = deepcopy(payload)
    events = result.get("events")
    if not isinstance(events, list) or not events:
        raise JourneyPackageError("旧语义输入events必须是非空数组")
    virtual_day_ms = 60 * 60 * 1000
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise JourneyPackageError(f"events[{index}]必须是对象")
        time_ms = _non_negative_int(event.get("time_ms"), f"events[{index}].time_ms")
        global_time_ms = _non_negative_int(
            event.get("global_time_ms", time_ms),
            f"events[{index}].global_time_ms",
        )
        event["time_ms"] = time_ms
        event["video_time_ms"] = _non_negative_int(
            event.get("video_time_ms", time_ms),
            f"events[{index}].video_time_ms",
        )
        event["global_time_ms"] = global_time_ms
        event["play_day_index"] = global_time_ms // virtual_day_ms + 1
        event["day_time_ms"] = global_time_ms % virtual_day_ms
    session = result.setdefault("session", {})
    max_time = max(int(event["global_time_ms"]) for event in events)
    total_play_time_ms = _non_negative_int(
        session.get("total_play_time_ms", session.get("duration_ms", max_time)),
        "session.total_play_time_ms",
    )
    total_play_time_ms = max(total_play_time_ms, max_time)
    session["duration_ms"] = total_play_time_ms
    session["total_play_time_ms"] = total_play_time_ms
    session["virtual_day_minutes"] = 60
    session["virtual_day_count"] = max(
        1,
        (total_play_time_ms + virtual_day_ms - 1) // virtual_day_ms,
    )
    session["event_count"] = len(events)
    session["event_type_counts"] = dict(sorted(Counter(
        str(event.get("event_type") or "unknown") for event in events
    ).items()))
    result["schema_version"] = SEMANTIC_INPUT_VERSION
    validate_semantic_input(result)
    return result


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JourneyPackageError(f"{field}必须是数字")
    result = int(round(value))
    if result < 0:
        raise JourneyPackageError(f"{field}不能小于0")
    return result
