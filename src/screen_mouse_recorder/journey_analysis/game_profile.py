from __future__ import annotations

from copy import deepcopy
import re
import unicodedata
from typing import Any

from .tagging import infer_event_labels


PROFILE_MAPPING_FIELDS = (
    "event_category",
    "object_scope",
    "interaction_mode",
    "gameplay_form",
    "rhythm_category",
)


def normalize_game_term(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[\s·•_\-—:：/\\]+", "", text)


def new_game_profile(game_id: str, game_name: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "game_id": str(game_id).strip(),
        "game_name": str(game_name).strip(),
        "updated_at": "",
        "terms": [],
    }


def find_game_term(profile: dict[str, Any], term: str) -> dict[str, Any] | None:
    normalized = normalize_game_term(term)
    if not normalized:
        return None
    for item in profile.get("terms") or []:
        if not isinstance(item, dict):
            continue
        candidates = [item.get("term"), *(item.get("aliases") or [])]
        if normalized in {normalize_game_term(candidate) for candidate in candidates}:
            return deepcopy(item)
    return None


def classification_mapping(annotation: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        field: deepcopy(annotation.get(field))
        for field in PROFILE_MAPPING_FIELDS
    }
    mode_tag, event_tag = infer_event_labels(annotation)
    mapping["mode_tag"] = mode_tag
    mapping["event_tag"] = event_tag
    mapping["tags"] = [mode_tag, event_tag]
    return mapping


def upsert_game_term(
    profile: dict[str, Any],
    *,
    term: str,
    annotation: dict[str, Any],
    event_id: str,
    reviewer: str,
    reviewed_at: str,
) -> dict[str, Any]:
    normalized = normalize_game_term(term)
    if not normalized:
        raise ValueError("游戏术语不能为空")
    result = deepcopy(profile)
    terms = result.setdefault("terms", [])
    existing = next(
        (
            item
            for item in terms
            if isinstance(item, dict) and normalize_game_term(item.get("term")) == normalized
        ),
        None,
    )
    if existing is None:
        existing = {
            "term": str(term).strip(),
            "normalized_term": normalized,
            "aliases": [],
            "mapping": {},
            "source_event_ids": [],
            "confirmed_by": "",
            "confirmed_at": "",
        }
        terms.append(existing)
    existing["mapping"] = classification_mapping(annotation)
    source_ids = existing.setdefault("source_event_ids", [])
    if event_id not in source_ids:
        source_ids.append(event_id)
    existing["confirmed_by"] = str(reviewer)
    existing["confirmed_at"] = str(reviewed_at)
    result["updated_at"] = str(reviewed_at)
    terms.sort(key=lambda item: normalize_game_term(item.get("term")))
    return result
