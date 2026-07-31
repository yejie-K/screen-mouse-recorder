from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any


PROFILE_SCHEMA_VERSION = "1.1"
METRIC_KEYS = {"combat_power", "level", "level_rebirth", "vip_level", "currency", "unknown"}
METRIC_PARSERS = {"numeric_cn", "integer", "level_rebirth", "text"}
MODE_TAGS = {"PVE", "PVP", "GVG", "系统", "待判断"}
EVENT_TAGS = {
    "新玩法",
    "新副本",
    "新养成系统",
    "新技能",
    "新任务系统",
    "新社交功能",
    "新商业功能",
    "其他开放",
}


class RegionProfileError(ValueError):
    pass


def read_region_profile(path: Path, *, require_complete: bool = False) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RegionProfileError("区域profile顶层必须是对象")
    validate_region_profile(payload, require_complete=require_complete)
    return payload


def validate_region_profile(payload: dict[str, Any], *, require_complete: bool = False) -> None:
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise RegionProfileError(f"区域profile版本必须为{PROFILE_SCHEMA_VERSION}")
    if payload.get("scan_scope") != "all_extracted_frames":
        raise RegionProfileError("区域profile.scan_scope必须为all_extracted_frames")
    status = str(payload.get("status") or "")
    if status not in {"needs_review", "complete"}:
        raise RegionProfileError("区域profile.status无效")
    if require_complete and status != "complete":
        raise RegionProfileError("扫描只接受人工确认完成的区域profile")
    source_frame = payload.get("source_frame")
    if not isinstance(source_frame, dict):
        raise RegionProfileError("区域profile缺少source_frame")
    width = _positive_int(source_frame.get("width"), "source_frame.width")
    height = _positive_int(source_frame.get("height"), "source_frame.height")
    if width <= 0 or height <= 0:
        raise RegionProfileError("source_frame宽高必须大于0")
    review = payload.get("review") or {}
    if require_complete and (
        not str(review.get("reviewer") or "").strip()
        or not str(review.get("reviewed_at") or "").strip()
    ):
        raise RegionProfileError("完成的区域profile必须记录复核人和复核时间")
    regions = payload.get("regions")
    if not isinstance(regions, list):
        raise RegionProfileError("区域profile.regions必须是数组")
    if require_complete and not regions:
        raise RegionProfileError("完成区域校准前至少需要一个区域")
    seen: set[str] = set()
    confirmed_event_groups: dict[str, set[str]] = {}
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            raise RegionProfileError(f"regions[{index}]必须是对象")
        region_id = str(region.get("region_id") or "").strip()
        if not region_id or region_id in seen:
            raise RegionProfileError(f"regions[{index}].region_id缺失或重复")
        seen.add(region_id)
        kind = str(region.get("region_kind") or "")
        if kind not in {"metric", "event"}:
            raise RegionProfileError(f"{region_id}.region_kind无效")
        region_status = str(region.get("status") or "")
        if region_status not in {"needs_review", "confirmed", "excluded"}:
            raise RegionProfileError(f"{region_id}.status无效")
        rect = region.get("rect_normalized")
        if not isinstance(rect, list) or len(rect) != 4:
            raise RegionProfileError(f"{region_id}.rect_normalized必须包含4个数字")
        try:
            left, top, right, bottom = map(float, rect)
        except (TypeError, ValueError) as exc:
            raise RegionProfileError(f"{region_id}.rect_normalized无效") from exc
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise RegionProfileError(f"{region_id}.rect_normalized必须位于0到1且形成有效矩形")
        manual_sample_ids = region.get("manual_sample_ids") or []
        if (
            not isinstance(manual_sample_ids, list)
            or len(manual_sample_ids) > 3
            or any(not str(value or "").strip() for value in manual_sample_ids)
            or len(set(map(str, manual_sample_ids))) != len(manual_sample_ids)
        ):
            raise RegionProfileError(f"{region_id}.manual_sample_ids必须是最多3个不重复ID")
        enabled = bool(region.get("enabled", True))
        if require_complete and enabled and region_status != "confirmed":
            raise RegionProfileError(f"启用区域{region_id}尚未人工确认")
        if kind == "metric":
            if region.get("metric_key") not in METRIC_KEYS:
                raise RegionProfileError(f"{region_id}.metric_key无效")
            if region.get("parser") not in METRIC_PARSERS:
                raise RegionProfileError(f"{region_id}.parser无效")
        else:
            group_id = str(region.get("region_group_id") or "").strip()
            role = str(region.get("region_role") or "")
            if not group_id or role not in {"trigger", "name", "auxiliary"}:
                raise RegionProfileError(f"{region_id}缺少有效事件组或区域角色")
            if region.get("mode_tag") not in MODE_TAGS or region.get("event_tag") not in EVENT_TAGS:
                raise RegionProfileError(f"{region_id}的事件标签无效")
            keywords = region.get("fixed_keywords")
            if not isinstance(keywords, list):
                raise RegionProfileError(f"{region_id}.fixed_keywords必须是数组")
            if enabled and region_status == "confirmed":
                confirmed_event_groups.setdefault(group_id, set()).add(role)
    if require_complete:
        missing_trigger = sorted(
            group_id for group_id, roles in confirmed_event_groups.items() if "trigger" not in roles
        )
        if missing_trigger:
            raise RegionProfileError(
                "确认事件组必须包含trigger区域: " + ", ".join(missing_trigger)
            )


def convert_legacy_layout_profile(
    payload: dict[str, Any],
    *,
    game_id: str,
    game_name: str,
) -> dict[str, Any]:
    video = payload.get("video") or {}
    width = _positive_int(video.get("width"), "video.width")
    height = _positive_int(video.get("height"), "video.height")
    regions = []
    for index, source in enumerate(payload.get("regions") or []):
        if not isinstance(source, dict) or not bool(source.get("enabled", True)):
            continue
        rect = source.get("box_norm")
        if not isinstance(rect, list) or len(rect) != 4:
            continue
        role = str(source.get("role") or "unknown")
        sample_texts = [str(value) for value in (source.get("sample_texts") or []) if str(value).strip()]
        region_id = str(source.get("region_id") or f"legacy_region_{index + 1:03d}")
        region: dict[str, Any] = {
            "region_id": region_id,
            "region_kind": "metric" if role in {"combat_power", "level"} else "event",
            "rect_normalized": [round(float(value), 6) for value in rect],
            "scene_hint": str(source.get("label") or role),
            "sample_texts": sample_texts[:8],
            "sample_evidence": [
                value
                for value in (str(source.get("source_frame") or ""), str(source.get("preview") or ""))
                if value
            ][:3],
            "enabled": True,
            "status": "needs_review",
        }
        if role == "combat_power":
            region.update(metric_key="combat_power", parser="numeric_cn")
        elif role == "level":
            has_rebirth = any("转" in text for text in sample_texts)
            region.update(
                metric_key="level_rebirth" if has_rebirth else "level",
                parser="level_rebirth" if has_rebirth else "integer",
            )
        else:
            group_id, event_role, mode_tag, event_tag = _legacy_event_mapping(role)
            region.update(
                region_group_id=group_id,
                region_role=event_role,
                fixed_keywords=_stable_keywords(sample_texts),
                mode_tag=mode_tag,
                event_tag=event_tag,
            )
        regions.append(region)
    result = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "game_id": str(game_id).strip(),
        "game_name": str(game_name).strip(),
        "status": "needs_review",
        "scan_scope": "all_extracted_frames",
        "source_frame": {"width": width, "height": height},
        "regions": regions,
        "review": {"reviewer": "", "reviewed_at": ""},
        "legacy_source": {
            "schema_version": str(payload.get("schema_version") or ""),
            "session_id": str(payload.get("session_id") or ""),
        },
    }
    # The public schema is intentionally strict; keep migration audit outside scanner input.
    scanner_profile = deepcopy(result)
    scanner_profile.pop("legacy_source", None)
    validate_region_profile(scanner_profile)
    return result


def scanner_profile_from_draft(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    result.pop("legacy_source", None)
    return result


def _legacy_event_mapping(role: str) -> tuple[str, str, str, str]:
    if role == "task_panel":
        return "task_panel", "name", "PVE", "新任务系统"
    if role == "feature_menu":
        return "feature_menu", "name", "系统", "新玩法"
    if role == "center_feedback":
        return "center_feedback", "trigger", "系统", "其他开放"
    return role or "legacy_unknown", "auxiliary", "待判断", "其他开放"


def _stable_keywords(values: list[str]) -> list[str]:
    result = []
    for value in values:
        cleaned = re.sub(r"\s+", "", value).strip()
        if not cleaned or cleaned in result:
            continue
        result.append(cleaned)
        if len(result) >= 8:
            break
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise RegionProfileError(f"{field}必须是正整数")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RegionProfileError(f"{field}必须是正整数") from exc
    if result <= 0:
        raise RegionProfileError(f"{field}必须是正整数")
    return result
