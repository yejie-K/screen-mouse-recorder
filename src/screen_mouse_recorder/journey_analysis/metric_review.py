from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from threading import RLock
from typing import Any

from .package import JourneyPackageError, write_json_atomic


METRIC_KEYS = (
    "combat_power",
    "level",
    "level_rebirth",
    "vip_level",
    "currency",
    "unknown",
)
METRIC_LABELS = {
    "combat_power": "战力",
    "level": "等级",
    "level_rebirth": "等级 / 转生",
    "vip_level": "VIP等级",
    "currency": "货币",
    "unknown": "待判断",
}
DECISIONS = {"pending", "confirmed", "excluded"}
OVERRIDE_FIELDS = {"metric_key", "parsed_value", "parsed_fields", "unit"}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise JourneyPackageError(f"JSON顶层必须是对象: {path}")
    return payload


def validate_metric_candidates(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "2.0":
        raise JourneyPackageError("指标候选schema_version必须为2.0")
    if payload.get("task_id") != "JOURNEY_METRIC_OBSERVATIONS_V2":
        raise JourneyPackageError("指标候选task_id无效")
    if not str(payload.get("source_fingerprint") or "").strip():
        raise JourneyPackageError("指标候选缺少source_fingerprint")
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        raise JourneyPackageError("指标候选metrics必须是数组")
    seen: set[str] = set()
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            raise JourneyPackageError(f"metrics[{index}]必须是对象")
        observation_id = str(metric.get("observation_id") or "").strip()
        if not observation_id or observation_id in seen:
            raise JourneyPackageError(f"metrics[{index}].observation_id缺失或重复")
        seen.add(observation_id)
        if metric.get("metric_key") not in METRIC_KEYS:
            raise JourneyPackageError(f"metrics[{index}].metric_key无效")
        review = metric.get("review")
        if not isinstance(review, dict) or review.get("status") not in DECISIONS:
            raise JourneyPackageError(f"metrics[{index}].review无效")


def build_metric_review_template(candidates: dict[str, Any]) -> dict[str, Any]:
    validate_metric_candidates(candidates)
    return {
        "schema_version": "1.0",
        "task_id": "JOURNEY_METRIC_REVIEW_V2",
        "source_fingerprint": candidates["source_fingerprint"],
        "reviewed_at": "",
        "reviewer": "",
        "decisions": [
            {
                "observation_id": metric["observation_id"],
                "decision": "pending",
                "candidate_snapshot": {
                    "metric_key": metric.get("metric_key"),
                    "raw_text": metric.get("raw_text"),
                    "parsed_value": metric.get("parsed_value"),
                    "parsed_fields": deepcopy(metric.get("parsed_fields") or {}),
                    "unit": metric.get("unit") or "",
                },
                "overrides": {},
                "review_note": "",
            }
            for metric in candidates["metrics"]
        ],
    }


def _validate_review(
    review: dict[str, Any],
    candidates: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if review.get("schema_version") != "1.0" or review.get("task_id") != "JOURNEY_METRIC_REVIEW_V2":
        raise JourneyPackageError("指标复核文件版本或task_id无效")
    if review.get("source_fingerprint") != candidates.get("source_fingerprint"):
        raise JourneyPackageError("指标复核文件source_fingerprint与候选不一致")
    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        raise JourneyPackageError("指标复核文件decisions必须是数组")
    candidate_ids = {str(metric["observation_id"]) for metric in candidates["metrics"]}
    decision_map: dict[str, dict[str, Any]] = {}
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise JourneyPackageError(f"decisions[{index}]必须是对象")
        observation_id = str(decision.get("observation_id") or "")
        if not observation_id or observation_id in decision_map:
            raise JourneyPackageError(f"decisions[{index}].observation_id缺失或重复")
        if observation_id not in candidate_ids:
            raise JourneyPackageError(f"复核引用未知指标: {observation_id}")
        if decision.get("decision") not in DECISIONS:
            raise JourneyPackageError(f"decisions[{index}].decision无效")
        overrides = decision.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise JourneyPackageError(f"decisions[{index}].overrides必须是对象")
        forbidden = sorted(set(overrides) - OVERRIDE_FIELDS)
        if forbidden:
            raise JourneyPackageError(f"decisions[{index}].overrides包含禁止字段: {', '.join(forbidden)}")
        _validate_overrides(overrides)
        decision_map[observation_id] = decision
    if any(item["decision"] in {"confirmed", "excluded"} for item in decision_map.values()):
        if not str(review.get("reviewer") or "").strip() or not str(review.get("reviewed_at") or "").strip():
            raise JourneyPackageError("存在确认或排除决定时必须记录复核人和时间")
    return decision_map


def _validate_overrides(overrides: dict[str, Any]) -> None:
    metric_key = overrides.get("metric_key")
    if metric_key is not None and metric_key not in METRIC_KEYS:
        raise JourneyPackageError("metric_key无效")
    parsed_fields = overrides.get("parsed_fields")
    if parsed_fields is not None and not isinstance(parsed_fields, dict):
        raise JourneyPackageError("parsed_fields必须是对象")
    parsed_value = overrides.get("parsed_value")
    if isinstance(parsed_value, bool) or not isinstance(parsed_value, (int, float, str, type(None))):
        raise JourneyPackageError("parsed_value类型无效")
    if "unit" in overrides and not isinstance(overrides["unit"], str):
        raise JourneyPackageError("unit必须是字符串")


def finalize_metric_review(
    candidates: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    validate_metric_candidates(candidates)
    decision_map = _validate_review(review, candidates)
    counts = Counter()
    pending_ids: list[str] = []
    metrics: list[dict[str, Any]] = []
    reviewer = str(review.get("reviewer") or "")
    reviewed_at = str(review.get("reviewed_at") or "")
    for candidate in candidates["metrics"]:
        observation_id = str(candidate["observation_id"])
        decision = decision_map.get(observation_id)
        status = str((decision or {}).get("decision") or "pending")
        if status == "pending":
            pending_ids.append(observation_id)
        counts[status] += 1
        metric = deepcopy(candidate)
        metric.update(deepcopy((decision or {}).get("overrides") or {}))
        metric["review"] = {
            "status": status,
            "reviewer": reviewer if status != "pending" else "",
            "reviewed_at": reviewed_at if status != "pending" else "",
            "note": str((decision or {}).get("review_note") or ""),
        }
        legacy_status = (candidate.get("review") or {}).get("legacy_event_review_status")
        if legacy_status in DECISIONS:
            metric["review"]["legacy_event_review_status"] = legacy_status
        metrics.append(metric)
    summary = {
        "observation_count": len(metrics),
        "pending": counts["pending"],
        "confirmed": counts["confirmed"],
        "excluded": counts["excluded"],
    }
    original_summary = candidates.get("summary") or {}
    if "raw_match_count" in original_summary:
        summary["raw_match_count"] = original_summary["raw_match_count"]
    return {
        "schema_version": "2.0",
        "task_id": "JOURNEY_METRIC_OBSERVATIONS_V2",
        "source_fingerprint": candidates["source_fingerprint"],
        "status": "complete" if not pending_ids else "needs_review",
        "scan_scope": candidates.get("scan_scope") or "debug_subset",
        "session": deepcopy(candidates.get("session") or {}),
        "summary": summary,
        "metrics": metrics,
        "compatibility": {
            **deepcopy(candidates.get("compatibility") or {}),
            "review_task_id": "JOURNEY_METRIC_REVIEW_V2",
            "pending_observation_ids": pending_ids,
        },
    }


class MetricReviewWorkspace:
    def __init__(
        self,
        *,
        candidates_path: Path,
        review_path: Path,
        confirmed_output_path: Path,
        evidence_root: Path | None = None,
    ) -> None:
        self.candidates_path = candidates_path.resolve()
        self.review_path = review_path.resolve()
        self.confirmed_output_path = confirmed_output_path.resolve()
        self.evidence_root = evidence_root.resolve() if evidence_root else None
        self._lock = RLock()
        self._ensure_review()

    def _ensure_review(self) -> None:
        candidates = _read_json(self.candidates_path)
        validate_metric_candidates(candidates)
        if not self.review_path.is_file():
            write_json_atomic(self.review_path, build_metric_review_template(candidates))
        review = _read_json(self.review_path)
        _validate_review(review, candidates)
        if not self.confirmed_output_path.is_file():
            write_json_atomic(self.confirmed_output_path, finalize_metric_review(candidates, review))

    def _load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        candidates = _read_json(self.candidates_path)
        review = _read_json(self.review_path)
        validate_metric_candidates(candidates)
        _validate_review(review, candidates)
        return candidates, review

    def _evidence_file(self, metric: dict[str, Any]) -> Path | None:
        if self.evidence_root is None:
            return None
        evidence = metric.get("evidence") or {}
        values = list(evidence.get("crop_images") or [])
        values.extend([evidence.get("review_image"), evidence.get("source_image")])
        root = self.evidence_root
        for value in values:
            text = str(value or "").replace("\\", "/").strip()
            if not text:
                continue
            relative = Path(text)
            candidates = [root / relative, root / relative.name]
            for candidate in candidates:
                resolved = candidate.resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    continue
                if resolved.is_file():
                    return resolved
        return None

    def evidence_for(self, observation_id: str) -> Path | None:
        with self._lock:
            candidates = _read_json(self.candidates_path)
            metric = next(
                (item for item in candidates.get("metrics") or [] if item.get("observation_id") == observation_id),
                None,
            )
            return self._evidence_file(metric) if metric else None

    def state(self) -> dict[str, Any]:
        with self._lock:
            candidates, review = self._load()
            decisions = {item["observation_id"]: item for item in review["decisions"]}
            sequence_flags = _sequence_flags(candidates["metrics"])
            counts = Counter()
            metrics = []
            for candidate in candidates["metrics"]:
                observation_id = str(candidate["observation_id"])
                decision = decisions.get(observation_id) or {
                    "decision": "pending",
                    "overrides": {},
                    "review_note": "",
                }
                status = str(decision.get("decision") or "pending")
                counts[status] += 1
                merged = {**deepcopy(candidate), **deepcopy(decision.get("overrides") or {})}
                flags = []
                confidence = candidate.get("confidence")
                if isinstance(confidence, (int, float)) and confidence < 0.75:
                    flags.append("OCR置信度较低")
                if merged.get("parsed_value") is None:
                    flags.append("尚未解析出指标值")
                flags.extend(sequence_flags.get(observation_id) or [])
                metrics.append({
                    **merged,
                    "status": status,
                    "review_note": str(decision.get("review_note") or ""),
                    "evidence_url": f"/api/evidence/{observation_id}" if self._evidence_file(candidate) else "",
                    "flags": flags,
                })
            return {
                "schema_version": "1.0",
                "session": deepcopy(candidates.get("session") or {}),
                "scan_scope": candidates.get("scan_scope") or "",
                "summary": {
                    "observation_count": len(metrics),
                    "pending": counts["pending"],
                    "confirmed": counts["confirmed"],
                    "excluded": counts["excluded"],
                    "flagged": sum(1 for metric in metrics if metric["flags"]),
                },
                "reviewer": str(review.get("reviewer") or ""),
                "reviewed_at": str(review.get("reviewed_at") or ""),
                "metric_keys": [{"value": key, "label": METRIC_LABELS[key]} for key in METRIC_KEYS],
                "metrics": metrics,
            }

    def save_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            candidates, review = self._load()
            observation_id = str(payload.get("observation_id") or "")
            decision_value = str(payload.get("decision") or "")
            reviewer = str(payload.get("reviewer") or "").strip()
            if decision_value not in DECISIONS:
                raise JourneyPackageError("decision无效")
            if decision_value in {"confirmed", "excluded"} and not reviewer:
                raise JourneyPackageError("确认或排除时必须填写复核人")
            decision = next(
                (item for item in review["decisions"] if item["observation_id"] == observation_id),
                None,
            )
            if decision is None:
                raise JourneyPackageError("observation_id不存在")
            overrides = deepcopy(payload.get("overrides") or {})
            if not isinstance(overrides, dict):
                raise JourneyPackageError("overrides必须是对象")
            forbidden = sorted(set(overrides) - OVERRIDE_FIELDS)
            if forbidden:
                raise JourneyPackageError(f"overrides包含禁止字段: {', '.join(forbidden)}")
            _validate_overrides(overrides)
            candidate = next(item for item in candidates["metrics"] if item["observation_id"] == observation_id)
            effective_value = overrides.get("parsed_value", candidate.get("parsed_value"))
            if decision_value == "confirmed" and effective_value is None:
                raise JourneyPackageError("确认指标前必须填写有效的指标值")
            decision.update({
                "decision": decision_value,
                "overrides": overrides,
                "review_note": str(payload.get("review_note") or "").strip(),
            })
            if decision_value in {"confirmed", "excluded"}:
                review["reviewer"] = reviewer
                review["reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            write_json_atomic(self.review_path, review)
            write_json_atomic(self.confirmed_output_path, finalize_metric_review(candidates, review))
            return self.state()

    def bulk_confirm(self, observation_ids: list[str], reviewer: str) -> dict[str, Any]:
        reviewer = reviewer.strip()
        if not reviewer:
            raise JourneyPackageError("批量确认必须填写复核人")
        state = self.state()
        metric_map = {metric["observation_id"]: metric for metric in state["metrics"]}
        for observation_id in observation_ids:
            metric = metric_map.get(observation_id)
            if metric is None:
                raise JourneyPackageError(f"未知指标: {observation_id}")
            if metric.get("parsed_value") is None:
                raise JourneyPackageError(f"指标{observation_id}尚未解析，不能批量确认")
            if metric.get("flags"):
                raise JourneyPackageError(f"指标{observation_id}存在重点核对项，不能批量确认")
            self.save_decision({
                "observation_id": observation_id,
                "decision": "confirmed",
                "reviewer": reviewer,
                "overrides": {
                    "metric_key": metric["metric_key"],
                    "parsed_value": metric["parsed_value"],
                    "parsed_fields": metric.get("parsed_fields") or {},
                    "unit": metric.get("unit") or "",
                },
                "review_note": metric.get("review_note") or "",
            })
        return self.state()


def _sequence_flags(metrics: list[dict[str, Any]]) -> dict[str, list[str]]:
    flags: dict[str, list[str]] = {}
    previous: dict[str, float] = {}
    combat_markers = ("战力", "诚力", "成力", "戌力")
    for metric in sorted(metrics, key=lambda item: (int(item.get("time_ms") or 0), str(item.get("observation_id") or ""))):
        observation_id = str(metric.get("observation_id") or "")
        metric_key = str(metric.get("metric_key") or "")
        raw_text = str(metric.get("raw_text") or "")
        item_flags = flags.setdefault(observation_id, [])
        marker_valid = True
        if metric_key == "combat_power":
            marker_valid = any(marker in raw_text for marker in combat_markers)
            if not marker_valid:
                item_flags.append("缺少战力文字标识")
            if "/" in raw_text or "／" in raw_text:
                item_flags.append("疑似生命值或进度数值")
        elif metric_key == "level" and "级" not in raw_text:
            item_flags.append("缺少等级文字标识")
        elif metric_key == "level_rebirth" and not any(marker in raw_text for marker in ("转", "转生")):
            item_flags.append("缺少转生文字标识")

        value = metric.get("parsed_value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if metric_key == "combat_power" and not marker_valid:
            continue
        prior = previous.get(metric_key)
        if prior is not None and prior > 0:
            if metric_key == "level" and value < prior:
                item_flags.append("等级出现回退")
            if metric_key == "combat_power":
                ratio = float(value) / prior
                if ratio < 0.7:
                    item_flags.append("战力出现明显回退")
                elif ratio > 5:
                    item_flags.append("战力出现异常跳变")
        previous[metric_key] = float(value)
    return {key: value for key, value in flags.items() if value}
