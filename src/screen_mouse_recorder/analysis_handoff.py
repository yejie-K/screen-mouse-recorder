from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .frame_export.presets import click_summary_policy


ANALYSIS_HANDOFF_VERSION = "1.0"
ANALYSIS_HANDOFF_TASK = "RECORDER_ANALYSIS_HANDOFF_V1"
ANALYSIS_HANDOFF_RELATIVE_PATH = Path("auto_report") / "analysis_handoff.json"


class AnalysisHandoffError(ValueError):
    pass


@dataclass(frozen=True)
class AnalysisHandoff:
    path: Path
    session_root: Path
    session_id: str
    video_path: Path
    session_meta_path: Path
    mouse_events_path: Path | None
    frame_index_path: Path
    contact_sheet_paths: tuple[Path, ...]
    frame_count: int


def write_analysis_handoff(
    session_root: Path,
    *,
    frame_index_path: Path,
    contact_sheet_paths: list[Path],
) -> Path:
    root = session_root.resolve()
    video = root / "recording.mp4"
    mouse_events = root / "mouse_events.jsonl"
    session_meta = root / "session_meta.json"
    for required in (video, mouse_events, session_meta, frame_index_path, *contact_sheet_paths):
        if not required.is_file():
            raise AnalysisHandoffError(f"交接文件不存在: {required.name}")
    meta = _read_object(session_meta)
    index = _read_object(frame_index_path)
    session_id = str(meta.get("session_id") or root.name).strip()
    if not session_id:
        raise AnalysisHandoffError("session_meta.json缺少session_id")
    target = root / ANALYSIS_HANDOFF_RELATIVE_PATH
    payload = {
        "schema_version": ANALYSIS_HANDOFF_VERSION,
        "task_id": ANALYSIS_HANDOFF_TASK,
        "status": "complete",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "path_base": "session_root",
        "session_id": session_id,
        "frame_policy": click_summary_policy(),
        "source": {
            "video": _file_record(root, video),
            "mouse_events": _file_record(root, mouse_events),
            "session_meta": _file_record(root, session_meta),
        },
        "artifacts": {
            "frame_index": _relative(root, frame_index_path),
            "contact_sheets": [_relative(root, path) for path in contact_sheet_paths],
        },
        "summary": {
            "frame_count": len(index.get("frames") or []),
            "sheet_count": len(contact_sheet_paths),
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def load_analysis_handoff(session_root: Path, *, verify_hashes: bool = True) -> AnalysisHandoff | None:
    root = session_root.resolve()
    path = root / ANALYSIS_HANDOFF_RELATIVE_PATH
    if not path.is_file():
        return None
    payload = _read_object(path)
    if payload.get("schema_version") != ANALYSIS_HANDOFF_VERSION or payload.get("task_id") != ANALYSIS_HANDOFF_TASK:
        raise AnalysisHandoffError("analysis_handoff.json不是当前1.0契约")
    if payload.get("status") != "complete" or payload.get("path_base") != "session_root":
        raise AnalysisHandoffError("analysis_handoff.json尚未完成或路径基准错误")
    policy = payload.get("frame_policy") or {}
    if policy != click_summary_policy():
        raise AnalysisHandoffError("抽帧策略版本与分析工具不一致")
    source = payload.get("source") or {}
    artifacts = payload.get("artifacts") or {}
    video = _validated_record(root, source.get("video"), "video", verify_hashes)
    session_meta = _validated_record(root, source.get("session_meta"), "session_meta", verify_hashes)
    mouse_events = _validated_record(root, source.get("mouse_events"), "mouse_events", verify_hashes)
    frame_index = _validated_path(root, artifacts.get("frame_index"), "frame_index")
    sheet_values = artifacts.get("contact_sheets")
    if not isinstance(sheet_values, list) or not sheet_values:
        raise AnalysisHandoffError("交接清单没有合成图")
    sheets = tuple(_validated_path(root, value, "contact_sheet") for value in sheet_values)
    index = _read_object(frame_index)
    frames = index.get("frames")
    if not isinstance(frames, list) or not frames:
        raise AnalysisHandoffError("抽帧索引没有可用帧")
    referenced = {str(item.get("sheet") or "") for item in frames if isinstance(item, dict)}
    if not referenced.issubset({sheet.name for sheet in sheets}):
        raise AnalysisHandoffError("抽帧索引引用了交接清单之外的合成图")
    summary = payload.get("summary") or {}
    if int(summary.get("frame_count") or 0) != len(frames) or int(summary.get("sheet_count") or 0) != len(sheets):
        raise AnalysisHandoffError("交接清单统计与实际文件不一致")
    return AnalysisHandoff(
        path=path,
        session_root=root,
        session_id=str(payload.get("session_id") or "").strip(),
        video_path=video,
        session_meta_path=session_meta,
        mouse_events_path=mouse_events,
        frame_index_path=frame_index,
        contact_sheet_paths=sheets,
        frame_count=len(frames),
    )


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": _relative(root, path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _validated_record(root: Path, value: Any, label: str, verify_hashes: bool) -> Path:
    if not isinstance(value, dict):
        raise AnalysisHandoffError(f"交接清单缺少{label}")
    path = _validated_path(root, value.get("path"), label)
    if int(value.get("size_bytes") or -1) != path.stat().st_size:
        raise AnalysisHandoffError(f"{label}文件大小已变化")
    if verify_hashes and str(value.get("sha256") or "") != _sha256(path):
        raise AnalysisHandoffError(f"{label}文件指纹已变化")
    return path


def _validated_path(root: Path, value: Any, label: str) -> Path:
    relative = str(value or "").strip()
    if not relative:
        raise AnalysisHandoffError(f"交接清单缺少{label}路径")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AnalysisHandoffError(f"{label}路径越界") from exc
    if not path.is_file():
        raise AnalysisHandoffError(f"{label}文件不存在")
    return path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise AnalysisHandoffError(f"交接文件不在Session目录内: {path.name}") from exc


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisHandoffError(f"无法读取JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise AnalysisHandoffError(f"JSON顶层必须是对象: {path.name}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
