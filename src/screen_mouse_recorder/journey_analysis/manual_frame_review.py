from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any


class ManualFrameReviewError(ValueError):
    pass


class ManualFrameReviewWorkspace:
    def __init__(self, *, runtime_dir: Path, state_path: Path) -> None:
        self.runtime_dir = runtime_dir.resolve()
        self.runtime_json = self.runtime_dir / "review_session.json"
        self.state_path = state_path.resolve()
        self._lock = RLock()
        if not self.runtime_json.is_file():
            raise ManualFrameReviewError(f"缺少人工选帧运行文件: {self.runtime_json}")

    def _runtime(self) -> dict[str, Any]:
        payload = _read_object(self.runtime_json)
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise ManualFrameReviewError("review_session.json缺少sessionId")
        return payload

    def _saved_candidates(self, session_id: str) -> list[dict[str, Any]]:
        if not self.state_path.is_file():
            return []
        payload = _read_object(self.state_path)
        if payload.get("schema_version") != "1.0":
            raise ManualFrameReviewError("manual_frame_review.json版本不受支持")
        if str(payload.get("session_id") or "") != session_id:
            raise ManualFrameReviewError("人工选帧状态与当前Session不匹配")
        return _candidates(payload.get("candidates"))

    def state(self) -> dict[str, Any]:
        with self._lock:
            runtime = self._runtime()
            session_id = str(runtime["sessionId"])
            handoff = _ocr_handoff(runtime, self.runtime_dir)
            return {
                **deepcopy(runtime),
                "manualCandidates": self._saved_candidates(session_id),
                "persistence": {
                    "stateFile": self.state_path.name,
                    "exists": self.state_path.is_file(),
                },
                "ocrHandoff": handoff,
            }

    def save(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            runtime = self._runtime()
            session_id = str(runtime["sessionId"])
            if str(request.get("sessionId") or "") != session_id:
                raise ManualFrameReviewError("保存请求与当前Session不匹配")
            candidates = _candidates(request.get("candidates"))
            payload = {
                "schema_version": "1.0",
                "session_id": session_id,
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "candidates": candidates,
            }
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(self.state_path, payload)
            selected_ocr_path = self.state_path.with_name("selected_ocr_tiles.json")
            selected_count = _write_selected_ocr_tiles(
                selected_ocr_path,
                runtime,
                candidates,
                runtime_dir=self.runtime_dir,
            )
            handoff = _ocr_handoff(runtime, self.runtime_dir)
            return {
                "status": "saved",
                "session_id": session_id,
                "candidate_count": len(candidates),
                "state_file": self.state_path.name,
                "selected_ocr_file": selected_ocr_path.name if selected_count else "",
                "selected_ocr_count": selected_count,
                "selected_ocr_ready": bool(selected_count and handoff["ready"]),
                "selected_ocr_blockers": handoff["blockers"],
            }

    def runtime_file(self, relative_value: str) -> Path:
        relative = Path(relative_value.replace("\\", "/"))
        if relative.is_absolute() or not relative.name:
            raise ManualFrameReviewError("运行资源路径无效")
        candidate = (self.runtime_dir / relative).resolve()
        try:
            candidate.relative_to(self.runtime_dir)
        except ValueError as exc:
            raise ManualFrameReviewError("运行资源路径越界") from exc
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate


def _candidates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ManualFrameReviewError("candidates必须是数组")
    if len(value) > 10_000:
        raise ManualFrameReviewError("人工候选数量超过10000")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ManualFrameReviewError(f"candidates[{index}]必须是对象")
        candidate = deepcopy(item)
        candidate_id = str(candidate.get("id") or "").strip()
        if not candidate_id or candidate_id in seen:
            raise ManualFrameReviewError(f"candidates[{index}].id缺失或重复")
        seen.add(candidate_id)
        if candidate.get("source") not in {"manual_frame", "manual_video_frame"}:
            raise ManualFrameReviewError(f"{candidate_id}.source不是人工选帧")
        if candidate.get("status") not in {"needs_review", "confirmed", "rejected"}:
            raise ManualFrameReviewError(f"{candidate_id}.status无效")
        if candidate.get("eventKind") not in {"unclassified", "new_feature", "growth", "combat", "system"}:
            raise ManualFrameReviewError(f"{candidate_id}.eventKind无效")
        for field in ("title", "timecode", "eventId", "evidenceFile", "ocrText", "note"):
            if not isinstance(candidate.get(field), str):
                raise ManualFrameReviewError(f"{candidate_id}.{field}必须是字符串")
        time_ms = candidate.get("timeMs")
        if isinstance(time_ms, bool) or not isinstance(time_ms, (int, float)) or time_ms < 0:
            raise ManualFrameReviewError(f"{candidate_id}.timeMs无效")
        candidate["timeMs"] = int(round(time_ms))
        confidence = candidate.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ManualFrameReviewError(f"{candidate_id}.confidence无效")
        if candidate["source"] == "manual_frame":
            if not isinstance(candidate.get("contactSheet"), str):
                raise ManualFrameReviewError(f"{candidate_id}.contactSheet必须是字符串")
            tile_id = str(candidate.get("contactSheetTileId") or "")
            if not re.search(r"\d+$", tile_id):
                raise ManualFrameReviewError(f"{candidate_id}.contactSheetTileId无效")
        result.append(candidate)
    result.sort(key=lambda item: (item["timeMs"], item["id"]))
    return result


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManualFrameReviewError(f"无法读取JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ManualFrameReviewError(f"{path.name}顶层必须是对象")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_selected_ocr_tiles(
    path: Path,
    runtime: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    runtime_dir: Path | None = None,
) -> int:
    selections = []
    video_selections = []
    for candidate in candidates:
        if candidate["status"] == "rejected":
            continue
        common = {
            "candidate_id": candidate["id"],
            "event_name": candidate["title"],
            "event_kind": candidate["eventKind"],
            "time_ms": candidate["timeMs"],
            "timecode": candidate["timecode"],
            "review_status": candidate["status"],
            "note": candidate["note"],
        }
        if candidate["source"] == "manual_frame":
            tile_match = re.search(r"(\d+)$", str(candidate["contactSheetTileId"]))
            if tile_match:
                selections.append({
                    "sheet": candidate["contactSheet"],
                    "tile_index": int(tile_match.group(1)),
                    **common,
                })
        else:
            video_selections.append({
                "source_frame": candidate["evidenceFile"],
                "video_file": candidate.get("videoFile") or "recording.mp4",
                "frame_status": candidate.get("frameStatus") or "pending_export",
                **common,
            })
    if not selections:
        path.unlink(missing_ok=True)
        return 0
    payload = {
        "schema_version": "1.0",
        "selections": selections,
        "manual_video_frames": video_selections,
    }
    source_index = _runtime_asset_reference(path.parent, runtime_dir, runtime.get("sourceIndex"))
    source_video = _runtime_asset_reference(path.parent, runtime_dir, runtime.get("videoFile"))
    if source_index:
        payload["source_index"] = source_index
    if source_video:
        payload["source_video"] = source_video
    _write_json(path, payload)
    return len(selections)


def _ocr_handoff(runtime: dict[str, Any], runtime_dir: Path | None = None) -> dict[str, Any]:
    blockers = []
    source_index = str(runtime.get("sourceIndex") or "").strip()
    source_video = str(runtime.get("videoFile") or "").strip()
    if not source_index:
        blockers.append("review_session.json缺少sourceIndex")
    if not source_video:
        blockers.append("review_session.json缺少videoFile")
    if runtime_dir is not None and source_index and not (runtime_dir / source_index).resolve().is_file():
        blockers.append("review_session.json的sourceIndex文件不存在")
    if runtime_dir is not None and source_video and not (runtime_dir / source_video).resolve().is_file():
        blockers.append("review_session.json的videoFile文件不存在")
    return {
        "ready": not blockers,
        "sourceIndex": source_index,
        "sourceVideo": source_video,
        "blockers": blockers,
    }


def _runtime_asset_reference(state_dir: Path, runtime_dir: Path | None, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if runtime_dir is None:
        return text
    source = (runtime_dir / text).resolve()
    if not source.is_file():
        return ""
    return Path(os.path.relpath(source, state_dir.resolve())).as_posix()
