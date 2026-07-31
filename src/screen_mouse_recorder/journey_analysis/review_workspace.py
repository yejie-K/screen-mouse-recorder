from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from threading import RLock
from typing import Any

from .game_profile import find_game_term, new_game_profile, upsert_game_term
from .package import (
    JourneyPackageError,
    SEMANTIC_OVERRIDE_FIELDS,
    finalize_semantic_review,
    validate_semantic_output,
    write_json_atomic,
)
from .rules import load_rule_file
from .semantic_input_compat import validate_semantic_input
from .tagging import (
    EVENT_TAGS,
    MODE_TAGS,
    infer_event_labels,
    normalize_tags,
    observation_lane,
)


class SemanticReviewWorkspace:
    def __init__(
        self,
        *,
        semantic_input_path: Path,
        ai_output_path: Path,
        review_path: Path,
        confirmed_output_path: Path,
        game_profile_path: Path,
        taxonomy_path: Path,
        emotion_rules_path: Path,
        evidence_root: Path | None,
        game_id: str,
        game_name: str,
    ) -> None:
        self.semantic_input_path = semantic_input_path
        self.ai_output_path = ai_output_path
        self.review_path = review_path
        self.confirmed_output_path = confirmed_output_path
        self.game_profile_path = game_profile_path
        self.taxonomy_path = taxonomy_path
        self.emotion_rules_path = emotion_rules_path
        self.evidence_root = evidence_root
        self.game_id = game_id
        self.game_name = game_name
        self._lock = RLock()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise JourneyPackageError(f"JSON顶层必须是对象: {path}")
        return payload

    def _load(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        semantic_input = self._read_json(self.semantic_input_path)
        validate_semantic_input(semantic_input)
        ai_output = self._read_json(self.ai_output_path)
        review = self._read_json(self.review_path)
        taxonomy = load_rule_file(self.taxonomy_path)
        emotion = load_rule_file(self.emotion_rules_path)
        profile = (
            self._read_json(self.game_profile_path)
            if self.game_profile_path.is_file()
            else new_game_profile(self.game_id, self.game_name)
        )
        errors = validate_semantic_output(ai_output, semantic_input, taxonomy, emotion)
        if errors:
            raise JourneyPackageError(f"AI语义输出校验失败: {errors[0]}")
        self._normalize_review(review, ai_output)
        return semantic_input, ai_output, review, taxonomy, emotion, profile

    @staticmethod
    def _normalize_review(review: dict[str, Any], ai_output: dict[str, Any]) -> None:
        candidates = {item["event_id"]: item for item in ai_output["event_annotations"]}
        for decision in review.get("decisions") or []:
            event_id = decision.get("event_id")
            decision.setdefault("save_to_game_profile", False)
            decision.setdefault("game_term", "")
            decision.setdefault("overrides", {})
            decision.setdefault("review_note", "")
            decision.setdefault("candidate_snapshot", {})
            overrides = decision["overrides"]
            if isinstance(overrides, dict) and "tags" in overrides:
                overrides["tags"] = normalize_tags(overrides["tags"])
            if not decision["game_term"] and event_id in candidates:
                decision["game_term"] = ""

    @staticmethod
    def _downgrade_unreviewed_legacy_confirmations(review: dict[str, Any]) -> None:
        for decision in review.get("decisions") or []:
            if decision.get("decision") != "confirmed":
                continue
            overrides = decision.get("overrides") or {}
            labels_reviewed = (
                overrides.get("mode_tag") in MODE_TAGS
                and overrides.get("event_tag") in EVENT_TAGS
            )
            if not labels_reviewed:
                decision["decision"] = "pending"

    @staticmethod
    def _merged_annotation(candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        return {**candidate, **(decision.get("overrides") or {})}

    def _evidence_file(self, event: dict[str, Any]) -> Path | None:
        if self.evidence_root is None:
            return None
        evidence = event.get("evidence") or {}
        for key in ("review_image", "source_image"):
            name = Path(str(evidence.get(key) or "")).name
            if not name:
                continue
            candidate = (self.evidence_root / name).resolve()
            if candidate.parent == self.evidence_root.resolve() and candidate.is_file():
                return candidate
        return None

    def evidence_for(self, event_id: str) -> Path | None:
        with self._lock:
            semantic_input = self._read_json(self.semantic_input_path)
            event = next((item for item in semantic_input["events"] if item["event_id"] == event_id), None)
            return self._evidence_file(event) if event else None

    def state(self) -> dict[str, Any]:
        with self._lock:
            semantic_input, ai_output, review, taxonomy, _emotion, profile = self._load()
            event_map = {item["event_id"]: item for item in semantic_input["events"]}
            candidate_map = {item["event_id"]: item for item in ai_output["event_annotations"]}
            decision_map = {item["event_id"]: item for item in review["decisions"]}
            review_reasons: dict[str, list[dict[str, str]]] = {}
            for item in ai_output.get("review_items") or []:
                review_reasons.setdefault(str(item.get("event_id") or ""), []).append(item)
            events = []
            metric_observation_count = 0
            counts = {"pending": 0, "confirmed": 0, "excluded": 0}
            for event_id, event in event_map.items():
                if event.get("source") == "manual":
                    continue
                candidate = candidate_map.get(event_id)
                decision = decision_map.get(event_id)
                if candidate is None or decision is None:
                    continue
                lane = observation_lane(event.get("event_type"))
                if lane == "metric":
                    metric_observation_count += 1
                    continue
                if lane != "event":
                    continue
                legacy_status = str(decision.get("decision") or "pending")
                overrides = decision.get("overrides") or {}
                labels_reviewed = (
                    overrides.get("mode_tag") in MODE_TAGS
                    and overrides.get("event_tag") in EVENT_TAGS
                )
                status = legacy_status
                if legacy_status == "confirmed" and not labels_reviewed:
                    status = "pending"
                counts[status] = counts.get(status, 0) + 1
                profile_match = find_game_term(profile, event.get("event_name") or "")
                if profile_match:
                    mapping = profile_match.setdefault("mapping", {})
                    mode_tag, event_tag = infer_event_labels(mapping)
                    mapping["mode_tag"] = mode_tag
                    mapping["event_tag"] = event_tag
                    mapping["tags"] = [mode_tag, event_tag]
                merged = self._merged_annotation(candidate, decision)
                mode_tag, event_tag = infer_event_labels(
                    merged,
                    event_type=str(event.get("event_type") or ""),
                    event_name=str(event.get("event_name") or ""),
                )
                decision_view = deepcopy(decision)
                decision_view["decision"] = status
                decision_view["legacy_decision"] = legacy_status
                decision_view["labels_reviewed"] = labels_reviewed
                events.append({
                    "event_id": event_id,
                    "event_name": event.get("event_name"),
                    "event_type": event.get("event_type"),
                    "timestamp": event.get("timestamp"),
                    "global_time_ms": event.get("global_time_ms", event.get("time_ms", 0)),
                    "ocr_excerpt": event.get("ocr_excerpt"),
                    "evidence": event.get("evidence") or {},
                    "evidence_url": f"/api/evidence/{event_id}" if self._evidence_file(event) else "",
                    "candidate": candidate,
                    "decision": decision_view,
                    "merged_annotation": merged,
                    "mode_tag": mode_tag,
                    "event_tag": event_tag,
                    "review_items": review_reasons.get(event_id, []),
                    "profile_match": profile_match,
                })
            return {
                "schema_version": "1.0",
                "game": {"game_id": self.game_id, "game_name": self.game_name},
                "session": semantic_input["session"],
                "dimensions": taxonomy.get("dimensions") or {},
                "mode_tags": list(MODE_TAGS),
                "event_tags": list(EVENT_TAGS),
                "summary": {
                    "event_count": len(events),
                    **counts,
                    "flagged": sum(1 for event in events if event["review_items"]),
                    "profile_terms": len(profile.get("terms") or []),
                    "metric_observations": metric_observation_count,
                },
                "reviewer": review.get("reviewer") or "",
                "reviewed_at": review.get("reviewed_at") or "",
                "events": events,
            }

    @staticmethod
    def _validate_overrides(overrides: Any, taxonomy: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(overrides, dict):
            raise JourneyPackageError("overrides必须是对象")
        forbidden = sorted(set(overrides) - SEMANTIC_OVERRIDE_FIELDS)
        if forbidden:
            raise JourneyPackageError(f"overrides包含禁止字段: {', '.join(forbidden)}")
        dimensions = taxonomy.get("dimensions") or {}
        result = deepcopy(overrides)
        if "event_category" in result and result["event_category"] not in dimensions.get("event_category", []):
            raise JourneyPackageError("event_category无效")
        if "tags" in result:
            try:
                result["tags"] = normalize_tags(result["tags"])
            except (TypeError, ValueError) as exc:
                raise JourneyPackageError(f"tags无效: {exc}") from exc
        if "mode_tag" in result and result["mode_tag"] not in MODE_TAGS:
            raise JourneyPackageError("mode_tag无效")
        if "event_tag" in result and result["event_tag"] not in EVENT_TAGS:
            raise JourneyPackageError("event_tag无效")
        for field in ("object_scope", "interaction_mode", "gameplay_form", "rhythm_category"):
            if field not in result:
                continue
            values = result[field]
            if not isinstance(values, list) or not values:
                raise JourneyPackageError(f"{field}必须是非空数组")
            unknown = sorted(set(map(str, values)) - set(dimensions.get(field) or []))
            if unknown:
                raise JourneyPackageError(f"{field}包含未知值: {', '.join(unknown)}")
        return result

    def save_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            semantic_input, ai_output, review, taxonomy, emotion, profile = self._load()
            event_id = str(payload.get("event_id") or "")
            decision_value = str(payload.get("decision") or "")
            reviewer = str(payload.get("reviewer") or "").strip()
            if decision_value not in {"pending", "confirmed", "excluded"}:
                raise JourneyPackageError("decision无效")
            if decision_value in {"confirmed", "excluded"} and not reviewer:
                raise JourneyPackageError("确认或排除时必须填写复核人")
            decision = next((item for item in review["decisions"] if item["event_id"] == event_id), None)
            candidate = next((item for item in ai_output["event_annotations"] if item["event_id"] == event_id), None)
            event = next((item for item in semantic_input["events"] if item["event_id"] == event_id), None)
            if decision is None or candidate is None or event is None:
                raise JourneyPackageError("event_id不存在")
            overrides = self._validate_overrides(payload.get("overrides") or {}, taxonomy)
            reviewed_at = datetime.now().astimezone().isoformat(timespec="seconds")
            decision.update({
                "decision": decision_value,
                "overrides": overrides,
                "review_note": str(payload.get("review_note") or "").strip(),
                "save_to_game_profile": bool(payload.get("save_to_game_profile")),
                "game_term": str(payload.get("game_term") or event["event_name"]).strip(),
            })
            if decision_value in {"confirmed", "excluded"}:
                review["reviewer"] = reviewer
                review["reviewed_at"] = reviewed_at
            self._downgrade_unreviewed_legacy_confirmations(review)
            final = finalize_semantic_review(semantic_input, ai_output, review, taxonomy, emotion)
            write_json_atomic(self.review_path, review)
            write_json_atomic(self.confirmed_output_path, final)
            if decision_value == "confirmed" and decision["save_to_game_profile"]:
                profile = upsert_game_term(
                    profile,
                    term=decision["game_term"],
                    annotation=self._merged_annotation(candidate, decision),
                    event_id=event_id,
                    reviewer=reviewer,
                    reviewed_at=reviewed_at,
                )
                write_json_atomic(self.game_profile_path, profile)
            return self.state()

    def bulk_confirm(self, event_ids: list[str], reviewer: str) -> dict[str, Any]:
        result = self.state()
        known = {event["event_id"] for event in result["events"]}
        for event_id in event_ids:
            if event_id not in known:
                raise JourneyPackageError(f"未知事件: {event_id}")
            current = next(event for event in result["events"] if event["event_id"] == event_id)
            overrides = deepcopy(current["decision"].get("overrides") or {})
            overrides["mode_tag"] = str(current.get("mode_tag") or "待判断")
            overrides["event_tag"] = str(current.get("event_tag") or "其他开放")
            overrides["tags"] = [overrides["mode_tag"], overrides["event_tag"]]
            result = self.save_decision({
                "event_id": event_id,
                "decision": "confirmed",
                "reviewer": reviewer,
                "overrides": overrides,
                "review_note": current["decision"].get("review_note") or "",
                "save_to_game_profile": False,
                "game_term": current["event_name"],
            })
        return result
