from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
from threading import RLock
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image

from ..media_utils import extract_frame, resolve_ffmpeg
from .ocr_events import OCREngine

from .region_profile import (
    EVENT_TAGS,
    METRIC_KEYS,
    METRIC_PARSERS,
    MODE_TAGS,
    RegionProfileError,
    validate_region_profile,
)


class RegionProfileReviewWorkspace:
    def __init__(
        self,
        *,
        profile_path: Path,
        evidence_root: Path,
        manual_review_path: Path | None = None,
        video_path: Path | None = None,
        manual_cache_dir: Path | None = None,
        ffmpeg_path: str | None = None,
        ocr_engine: OCREngine | None = None,
        ocr_status: dict[str, Any] | None = None,
    ) -> None:
        self.profile_path = profile_path.resolve()
        self.evidence_root = evidence_root.resolve()
        self.manual_review_path = manual_review_path.resolve() if manual_review_path else None
        self.video_path = video_path.resolve() if video_path else None
        self.manual_cache_dir = manual_cache_dir.resolve() if manual_cache_dir else None
        self.ffmpeg_path = ffmpeg_path
        self.ocr_engine = ocr_engine
        self.ocr_status = deepcopy(ocr_status) if ocr_status else {
            "available": ocr_engine is not None,
            "source": "configured" if ocr_engine is not None else "missing",
            "message": "OCR已就绪" if ocr_engine is not None else "OCR组件未配置",
        }
        self._lock = RLock()

    def _read(self) -> dict[str, Any]:
        payload = json.loads(self.profile_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise RegionProfileError("区域profile顶层必须是对象")
        validate_region_profile(payload)
        return payload

    def _evidence(self, region: dict[str, Any], *, preview: bool) -> Path | None:
        values = region.get("sample_evidence") or []
        candidates = values[::-1] if preview else values
        for value in candidates:
            relative = Path(str(value or ""))
            if not relative.name:
                continue
            is_preview = any("preview" in part.lower() for part in relative.parts)
            if preview != is_preview:
                continue
            candidate = (self.evidence_root / relative).resolve()
            try:
                candidate.relative_to(self.evidence_root)
            except ValueError:
                continue
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def evidence_for(self, region_id: str, *, preview: bool) -> Path | None:
        with self._lock:
            payload = self._read()
            region = next(
                (item for item in payload["regions"] if item.get("region_id") == region_id),
                None,
            )
            return self._evidence(region, preview=preview) if region else None

    def _manual_candidates(self) -> list[dict[str, Any]]:
        if self.manual_review_path is None or not self.manual_review_path.is_file():
            return []
        try:
            payload = json.loads(self.manual_review_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegionProfileError("无法读取人工选帧状态") from exc
        values = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            raise RegionProfileError("人工选帧状态缺少candidates")
        result = []
        for item in values:
            if not isinstance(item, dict) or item.get("source") not in {"manual_frame", "manual_video_frame"}:
                continue
            if item.get("status") == "rejected":
                continue
            candidate_id = str(item.get("id") or "").strip()
            time_ms = item.get("timeMs")
            if not candidate_id or isinstance(time_ms, bool) or not isinstance(time_ms, (int, float)):
                continue
            result.append({**deepcopy(item), "id": candidate_id, "timeMs": max(0, int(round(time_ms)))})
        result.sort(key=lambda item: (item["timeMs"], item["id"]))
        return result

    def manual_evidence_for(self, candidate_id: str) -> Path | None:
        with self._lock:
            if self.video_path is None or not self.video_path.is_file() or self.manual_cache_dir is None:
                return None
            candidate = next((item for item in self._manual_candidates() if item["id"] == candidate_id), None)
            if candidate is None:
                return None
            safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate_id).strip("._") or "manual"
            output = self.manual_cache_dir / f"{safe_id}_{candidate['timeMs']:010d}.jpg"
            if output.is_file():
                return output
            self.manual_cache_dir.mkdir(parents=True, exist_ok=True)
            ffmpeg = resolve_ffmpeg(self.ffmpeg_path)
            image = extract_frame(ffmpeg, self.video_path, candidate["timeMs"] / 1000)
            temporary = output.with_name(f"{output.name}.part")
            image.save(temporary, format="JPEG", quality=92)
            temporary.replace(output)
            return output

    def state(self) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            counts = {"needs_review": 0, "confirmed": 0, "excluded": 0}
            regions = []
            for region in payload["regions"]:
                status = str(region.get("status") or "needs_review")
                counts[status] = counts.get(status, 0) + 1
                region_id = str(region["region_id"])
                regions.append({
                    **deepcopy(region),
                    "preview_url": (
                        f"/api/preview/{region_id}" if self._evidence(region, preview=True) else ""
                    ),
                    "source_url": (
                        f"/api/source/{region_id}" if self._evidence(region, preview=False) else ""
                    ),
                })
            blockers = self._completion_blockers(payload)
            manual_samples = [
                {
                    "id": item["id"],
                    "title": str(item.get("title") or item["id"]),
                    "time_ms": item["timeMs"],
                    "timecode": str(item.get("timecode") or ""),
                    "status": str(item.get("status") or "needs_review"),
                    "source_url": f"/api/manual-source/{item['id']}",
                }
                for item in self._manual_candidates()
                if self.video_path is not None and self.manual_cache_dir is not None
            ]
            return {
                "schema_version": "1.0",
                "game": {"game_id": payload["game_id"], "game_name": payload["game_name"]},
                "profile_status": payload["status"],
                "source_frame": payload["source_frame"],
                "summary": {"region_count": len(regions), **counts},
                "completion_blockers": blockers,
                "options": {
                    "metric_keys": [
                        "combat_power", "level", "level_rebirth",
                        "vip_level", "currency", "unknown",
                    ],
                    "metric_parsers": ["numeric_cn", "integer", "level_rebirth", "text"],
                    "mode_tags": ["PVE", "PVP", "GVG", "系统", "待判断"],
                    "event_tags": [
                        "新玩法", "新副本", "新养成系统", "新技能", "新任务系统",
                        "新社交功能", "新商业功能", "其他开放",
                    ],
                    "region_roles": ["trigger", "name", "auxiliary"],
                },
                "review": payload.get("review") or {},
                "ocr": deepcopy(self.ocr_status),
                "manual_samples": manual_samples,
                "regions": regions,
            }

    def suggest_metric(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.ocr_engine is None:
                raise RegionProfileError("当前工作台未配置OCR建议引擎")
            payload = self._read()
            region_id = str(request.get("region_id") or "")
            region = next((item for item in payload["regions"] if item.get("region_id") == region_id), None)
            if region is None:
                raise RegionProfileError("region_id不存在")
            rect = _rect(request.get("rect_normalized"))
            sample_ids = _manual_ids(request.get("manual_sample_ids"))
            sources = [self.manual_evidence_for(value) for value in sample_ids]
            source_paths = [value for value in sources if value is not None]
            if not source_paths:
                source = self._evidence(region, preview=False)
                if source is not None:
                    source_paths = [source]
            if not source_paths:
                raise RegionProfileError("没有可用于自动判断的代表帧")
            texts: list[str] = []
            confidences: list[float] = []
            elapsed = 0.0
            with TemporaryDirectory(prefix="metric_suggest_") as directory:
                temporary_root = Path(directory)
                for index, source_path in enumerate(source_paths[:3]):
                    with Image.open(source_path) as opened:
                        image = opened.convert("RGB")
                    width, height = image.size
                    left, top, right, bottom = rect
                    crop = image.crop((
                        int(round(left * width)), int(round(top * height)),
                        int(round(right * width)), int(round(bottom * height)),
                    ))
                    crop_path = temporary_root / f"sample_{index + 1}.png"
                    crop.save(crop_path)
                    items, item_elapsed = self.ocr_engine.recognize(crop_path)
                    elapsed += item_elapsed
                    text = " ".join(item.text.strip() for item in items if item.text.strip())
                    texts.append(text)
                    confidences.extend(item.confidence for item in items if item.text.strip())
            metric_key, parser, reason = _infer_metric(texts)
            return {
                "metric_key": metric_key,
                "parser": parser,
                "reason": reason,
                "ocr_texts": texts,
                "confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
                "elapsed_seconds": round(elapsed, 4),
            }

    def save_region(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            region_id = str(request.get("region_id") or "")
            decision = str(request.get("decision") or "")
            reviewer = str(request.get("reviewer") or "").strip()
            if decision not in {"needs_review", "confirmed", "excluded"}:
                raise RegionProfileError("decision无效")
            if decision in {"confirmed", "excluded"} and not reviewer:
                raise RegionProfileError("确认或排除区域时必须填写复核人")
            region = next(
                (item for item in payload["regions"] if item.get("region_id") == region_id),
                None,
            )
            if region is None:
                raise RegionProfileError("region_id不存在")
            region["rect_normalized"] = _rect(request.get("rect_normalized"))
            region["manual_sample_ids"] = _manual_ids(request.get("manual_sample_ids"))
            region["sample_texts"] = _sample_texts(request.get("sample_texts"))
            region["scene_hint"] = str(request.get("scene_hint") or "").strip()
            region["enabled"] = bool(request.get("enabled")) and decision != "excluded"
            kind = str(request.get("region_kind") or "")
            if kind not in {"metric", "event"}:
                raise RegionProfileError("region_kind无效")
            region["region_kind"] = kind
            if kind == "metric":
                metric_key = str(request.get("metric_key") or "")
                parser = str(request.get("parser") or "")
                if metric_key not in METRIC_KEYS or parser not in METRIC_PARSERS:
                    raise RegionProfileError("指标类型或解析器无效")
                region["metric_key"] = metric_key
                region["parser"] = parser
                for key in ("region_group_id", "region_role", "fixed_keywords", "mode_tag", "event_tag"):
                    region.pop(key, None)
            else:
                group_id = str(request.get("region_group_id") or "").strip()
                role = str(request.get("region_role") or "")
                mode_tag = str(request.get("mode_tag") or "")
                event_tag = str(request.get("event_tag") or "")
                if not group_id or role not in {"trigger", "name", "auxiliary"}:
                    raise RegionProfileError("事件区域缺少有效组名或区域角色")
                if mode_tag not in MODE_TAGS or event_tag not in EVENT_TAGS:
                    raise RegionProfileError("事件区域标签无效")
                keywords = request.get("fixed_keywords")
                if not isinstance(keywords, list):
                    raise RegionProfileError("fixed_keywords必须是数组")
                region["region_group_id"] = group_id
                region["region_role"] = role
                region["fixed_keywords"] = _keywords(keywords)
                region["mode_tag"] = mode_tag
                region["event_tag"] = event_tag
                region.pop("metric_key", None)
                region.pop("parser", None)
            region["status"] = decision
            reviewed_at = datetime.now().astimezone().isoformat(timespec="seconds")
            if decision in {"confirmed", "excluded"}:
                payload["review"] = {"reviewer": reviewer, "reviewed_at": reviewed_at}
            blockers = self._completion_blockers(payload)
            payload["status"] = "complete" if not blockers else "needs_review"
            _write_json(self.profile_path, payload)
            return self.state()

    def add_metric_region(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            sample_id = str(request.get("sample_region_id") or "")
            regions = payload["regions"]
            sample = next(
                (item for item in regions if item.get("region_id") == sample_id),
                regions[0] if regions else None,
            )
            evidence = [
                str(value)
                for value in (sample or {}).get("sample_evidence") or []
                if "preview" not in str(value).lower()
            ][:1]
            manual_sample_ids = list((sample or {}).get("manual_sample_ids") or [])[:1]
            if not manual_sample_ids:
                manual_candidates = self._manual_candidates()
                manual_sample_ids = [str(manual_candidates[0]["id"])] if manual_candidates else []
            existing = {str(item.get("region_id") or "") for item in regions}
            sequence = 1
            while f"roi_metric_custom_{sequence:03d}" in existing:
                sequence += 1
            region_id = f"roi_metric_custom_{sequence:03d}"
            regions.append({
                "region_id": region_id,
                "region_kind": "metric",
                "rect_normalized": [0.35, 0.35, 0.65, 0.45],
                "scene_hint": "新指标区域",
                "sample_texts": [],
                "sample_evidence": evidence,
                "manual_sample_ids": manual_sample_ids,
                "enabled": True,
                "status": "needs_review",
                "metric_key": "unknown",
                "parser": "text",
            })
            payload["status"] = "needs_review"
            _write_json(self.profile_path, payload)
            return {"region_id": region_id, "state": self.state()}

    @staticmethod
    def _completion_blockers(payload: dict[str, Any]) -> list[str]:
        pending = [
            str(region.get("region_id") or "")
            for region in payload.get("regions") or []
            if region.get("status") == "needs_review"
        ]
        if pending:
            return [f"仍有{len(pending)}个区域待复核"]
        candidate = deepcopy(payload)
        candidate["status"] = "complete"
        try:
            validate_region_profile(candidate, require_complete=True)
        except RegionProfileError as exc:
            return [str(exc)]
        return []


def _rect(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise RegionProfileError("rect_normalized必须包含4个数字")
    try:
        left, top, right, bottom = map(float, value)
    except (TypeError, ValueError) as exc:
        raise RegionProfileError("rect_normalized无效") from exc
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise RegionProfileError("区域坐标必须位于0到1且形成有效矩形")
    return [round(left, 6), round(top, 6), round(right, 6), round(bottom, 6)]


def _keywords(values: list[Any]) -> list[str]:
    result = []
    for value in values:
        keyword = " ".join(str(value or "").split()).strip()
        if keyword and keyword not in result:
            result.append(keyword)
    return result[:16]


def _manual_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RegionProfileError("manual_sample_ids必须是数组")
    result = []
    for item in value:
        candidate_id = str(item or "").strip()
        if not candidate_id or candidate_id in result:
            continue
        result.append(candidate_id)
    if len(result) > 3:
        raise RegionProfileError("manual_sample_ids最多3项")
    return result


def _sample_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RegionProfileError("sample_texts必须是数组")
    result = []
    for item in value:
        text = " ".join(str(item or "").split()).strip()
        if text and text not in result:
            result.append(text)
    return result[:8]


def _infer_metric(texts: list[str]) -> tuple[str, str, str]:
    joined = " ".join(texts).upper()
    compact = re.sub(r"\s+", "", joined)
    if re.search(r"\d+转.*?\d+级", compact) or ("转" in compact and "级" in compact):
        return "level_rebirth", "level_rebirth", "识别到“转 + 级”组合"
    if any(keyword in compact for keyword in ("战力", "成力", "诚力", "戰力")):
        return "combat_power", "numeric_cn", "识别到战力文字"
    if "VIP" in compact:
        return "vip_level", "integer", "识别到VIP文字"
    if any(keyword in compact for keyword in ("元宝", "金币", "银两", "钻石", "铜钱")):
        return "currency", "numeric_cn", "识别到货币文字"
    if "级" in compact:
        return "level", "integer", "识别到等级文字"
    return "unknown", "text", "未识别到稳定指标关键词"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
