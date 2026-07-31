#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from urllib.parse import urlsplit
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
SHELL_CSS = ROOT / "tools" / "workspace_shell.css"
SHELL_JS = ROOT / "tools" / "workspace_shell.js"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.event_extraction import (  # noqa: E402
    RapidOCREngine,
    RegionProfileReviewWorkspace,
    RegionScanConfig,
    RegionScanJob,
)
from screen_mouse_recorder.frame_export import probe_video  # noqa: E402
from screen_mouse_recorder.journey_analysis.manual_frame_review import (  # noqa: E402
    ManualFrameReviewWorkspace,
)
from screen_mouse_recorder.journey_analysis.metric_review import MetricReviewWorkspace  # noqa: E402
from screen_mouse_recorder.journey_analysis.package import JourneyPackageError  # noqa: E402
from screen_mouse_recorder.journey_analysis.review_workspace import SemanticReviewWorkspace  # noqa: E402
from screen_mouse_recorder.journey_analysis.workspace import (  # noqa: E402
    ensure_region_profile_draft,
    refresh_journey_workspace,
    sync_journey_workspace,
)
from tools.serve_journey_semantic_review import ReviewHandler  # noqa: E402
from tools.serve_manual_frame_review import ManualFrameReviewHandler  # noqa: E402
from tools.serve_metric_review import MetricReviewHandler  # noqa: E402
from tools.serve_ocr_region_profile_review import RegionProfileHandler  # noqa: E402
from tools.prepare_journey_run import prepare_journey_run  # noqa: E402
from tools.ocr_runtime import load_rapidocr  # noqa: E402


ROUTES = {
    "manual": "/manual/",
    "regions": "/regions/",
    "events": "/events/",
    "metrics": "/metrics/",
}

WORKSPACE_REGISTRY_VERSION = 1
WORKSPACE_REGISTRY_LIMIT = 20


class WorkspaceDirectoryError(JourneyPackageError):
    def __init__(self, message: str, code: str = "JOURNEY-WORKSPACE-009") -> None:
        super().__init__(message)
        self.code = code


def _default_registry_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "ScreenMouseRecorder" / "journey_sessions.json"


class WorkspaceDirectoryRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or _default_registry_path()).resolve()

    def paths(self) -> tuple[Path, ...]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, dict) or payload.get("version") != WORKSPACE_REGISTRY_VERSION:
            return ()
        roots = payload.get("roots")
        if not isinstance(roots, list):
            return ()
        result: list[Path] = []
        seen: set[str] = set()
        for item in roots:
            if not isinstance(item, dict):
                continue
            value = str(item.get("path") or "").strip()
            if not value:
                continue
            path = Path(value).expanduser()
            key = str(path).casefold()
            if key not in seen and path.is_dir():
                seen.add(key)
                result.append(path.resolve())
        return tuple(result)

    def add(self, root: Path) -> None:
        resolved = root.resolve()
        existing = [path for path in self.paths() if str(path).casefold() != str(resolved).casefold()]
        roots = [resolved, *existing][:WORKSPACE_REGISTRY_LIMIT]
        payload = {
            "version": WORKSPACE_REGISTRY_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "roots": [{"path": str(path)} for path in roots],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def _choose_workspace_directory(initial_dir: Path) -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            parent=root,
            title="选择Session或工作空间文件夹",
            initialdir=str(initial_dir if initial_dir.is_dir() else Path.home()),
            mustexist=True,
        )
    finally:
        root.destroy()
    return Path(selected).resolve() if selected else None


def _resolve_startup_workspace(workspace_dir: Path | None) -> Path:
    if workspace_dir is not None:
        return workspace_dir.resolve()
    roots = (*WorkspaceDirectoryRegistry().paths(), ROOT / "outputs", ROOT / "sessions")
    candidates: list[Path] = []
    seen: set[str] = set()
    for root in _unique_existing_directories(roots):
        direct = (root / "journey_workspace.json")
        manifests = [direct] if direct.is_file() else []
        if not manifests:
            try:
                manifests = list(root.rglob("journey_workspace.json"))
            except OSError:
                continue
        for manifest in manifests:
            parent = manifest.parent.resolve()
            key = str(parent).casefold()
            if key not in seen:
                seen.add(key)
                candidates.append(parent)
    if not candidates:
        raise JourneyPackageError("未找到可用历程工作空间，请先准备一个Session")
    return max(candidates, key=lambda path: (path / "journey_workspace.json").stat().st_mtime)


def _path(root: Path, artifacts: dict, key: str) -> Path:
    value = str(artifacts.get(key) or "").strip()
    if not value:
        raise JourneyPackageError(f"工作空间缺少 artifact: {key}")
    result = (root / value).resolve()
    result.relative_to(root)
    return result


@dataclass(frozen=True)
class RouteApplication:
    handler: type[BaseHTTPRequestHandler]
    workspace: object
    scan_job: RegionScanJob | None = None


class WorkspaceApplications:
    def __init__(
        self,
        root: Path,
        *,
        ocr_runtime: Path | None = None,
        discovery_roots: tuple[Path, ...] | None = None,
        registry_path: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.ocr_runtime = ocr_runtime.resolve() if ocr_runtime else None
        self.ocr = load_rapidocr(
            ROOT,
            engine_factory=RapidOCREngine,
            explicit_runtime=self.ocr_runtime,
        )
        self.registry = WorkspaceDirectoryRegistry(registry_path)
        configured_roots = discovery_roots if discovery_roots is not None else (
            ROOT / "outputs",
            ROOT / "sessions",
            *self.registry.paths(),
        )
        self.discovery_roots = _unique_existing_directories(configured_roots)
        self._lock = threading.RLock()
        self._applications: dict[str, RouteApplication] = {}
        self._downstream_error = ""
        self._session_entries_cache: list[dict] = []
        self._session_entries_cached_at = 0.0
        self._prepare_thread: threading.Thread | None = None
        self._prepare_state: dict = {"status": "idle"}
        self.manifest = refresh_journey_workspace(self.root)
        self._build_primary()
        self._build_downstream(sync_if_missing=False)

    def _build_primary(self) -> None:
        artifacts = self.manifest["artifacts"]
        self._applications["manual"] = RouteApplication(
            ManualFrameReviewHandler,
            ManualFrameReviewWorkspace(
                runtime_dir=_path(self.root, artifacts, "review_runtime").parent,
                state_path=_path(self.root, artifacts, "manual_review"),
            ),
        )
        profile_value = str(artifacts.get("region_profile") or "").strip()
        if not profile_value:
            video = _path(self.root, artifacts, "video")
            info = probe_video(video)
            ensure_region_profile_draft(
                self.root,
                width=info.width,
                height=info.height,
            )
            self.manifest = refresh_journey_workspace(self.root)
            artifacts = self.manifest["artifacts"]
        profile = _path(self.root, artifacts, "region_profile")
        video = _path(self.root, artifacts, "video")
        scan_output = _path(self.root, artifacts, "event_observations").parent
        scan_job = RegionScanJob(RegionScanConfig(
            index_json=_path(self.root, artifacts, "frame_index"),
            region_profile=profile,
            output_dir=scan_output,
            video_path=video,
            session_id=str(self.manifest["session"]["session_id"]),
            save_crops=True,
        ), engine=self.ocr.engine) if self.ocr.available else None
        self._applications["regions"] = RouteApplication(
            RegionProfileHandler,
            RegionProfileReviewWorkspace(
                profile_path=profile,
                evidence_root=_path(self.root, artifacts, "region_evidence"),
                manual_review_path=_path(self.root, artifacts, "manual_review"),
                video_path=video,
                manual_cache_dir=scan_output / "manual_review_frames",
                ocr_engine=self.ocr.engine,
                ocr_status={
                    "available": self.ocr.available,
                    "source": self.ocr.source,
                    "message": self.ocr.message,
                },
            ),
            scan_job,
        )

    def _build_downstream(self, *, sync_if_missing: bool) -> None:
        self.manifest = refresh_journey_workspace(self.root)
        scan_complete = self.manifest["stages"]["region_scan"]["status"] == "complete"
        if not scan_complete:
            return
        downstream_stale = any(
            self.manifest["stages"][key]["status"] == "stale"
            for key in ("event_review", "metric_review")
        )
        if downstream_stale and not sync_if_missing:
            return
        artifacts = self.manifest["artifacts"]
        event_manifest = _path(self.root, artifacts, "event_review_manifest")
        metric_candidates = _path(self.root, artifacts, "metric_observations")
        metric_review = _path(self.root, artifacts, "metric_review")
        missing = not event_manifest.is_file() or not metric_candidates.is_file() or not metric_review.is_file()
        if (missing or downstream_stale) and sync_if_missing:
            sync_journey_workspace(
                self.root,
                taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
                emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
            )
            self.manifest = refresh_journey_workspace(self.root)
            self._downstream_error = ""
            artifacts = self.manifest["artifacts"]
            event_manifest = _path(self.root, artifacts, "event_review_manifest")
            metric_candidates = _path(self.root, artifacts, "metric_observations")
            metric_review = _path(self.root, artifacts, "metric_review")
        if "events" not in self._applications and event_manifest.is_file():
            event_dir = event_manifest.parent
            self._applications["events"] = RouteApplication(
                ReviewHandler,
                SemanticReviewWorkspace(
                    semantic_input_path=event_dir / "journey_semantic_input.json",
                    ai_output_path=event_dir / "journey_semantic_output.json",
                    review_path=event_dir / "journey_semantic_review.json",
                    confirmed_output_path=_path(self.root, artifacts, "confirmed_events"),
                    game_profile_path=_path(self.root, artifacts, "game_profile"),
                    taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
                    emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
                    evidence_root=event_dir / "evidence",
                    game_id=str(self.manifest["session"]["game_id"]),
                    game_name=str(self.manifest["session"]["game_name"]),
                ),
            )
        if "metrics" not in self._applications and metric_candidates.is_file() and metric_review.is_file():
            self._applications["metrics"] = RouteApplication(
                MetricReviewHandler,
                MetricReviewWorkspace(
                    candidates_path=metric_candidates,
                    review_path=metric_review,
                    confirmed_output_path=_path(self.root, artifacts, "confirmed_metrics"),
                    evidence_root=metric_candidates.parent,
                ),
            )

    def get(self, section: str) -> RouteApplication | None:
        with self._lock:
            if section in {"events", "metrics"} and section not in self._applications:
                try:
                    self._build_downstream(sync_if_missing=True)
                except (JourneyPackageError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    self._downstream_error = str(exc)
            return self._applications.get(section)

    def state(self) -> dict:
        with self._lock:
            self.manifest = refresh_journey_workspace(self.root)
            return {
                "status": "ready",
                "workspace": str(self.root),
                "routes": ROUTES,
                "available": sorted(self._applications),
                "stages": self.manifest["stages"],
                "downstream_error": self._downstream_error,
                "ocr": {
                    "available": self.ocr.available,
                    "source": self.ocr.source,
                    "message": self.ocr.message,
                },
            }

    def list_workspaces(self) -> dict:
        entries = [
            {key: value for key, value in item.items() if key != "path"}
            for item in self._session_entries()
        ]
        return {
            "status": "ready",
            "current_id": _workspace_id(self.root),
            "sessions": entries,
            "preparation": self.preparation_state(),
        }

    def browse_initial_directory(self) -> Path:
        candidates = (
            ROOT / "sessions" / "recordings",
            ROOT / "sessions",
            *self.registry.paths(),
            self.root.parent,
        )
        return next((path.resolve() for path in candidates if path.is_dir()), self.root.parent)

    def register_workspace_directory(self, selected_root: Path) -> dict:
        try:
            root = selected_root.expanduser().resolve(strict=True)
        except OSError as exc:
            raise WorkspaceDirectoryError(
                f"文件夹不可访问：{selected_root}",
                "JOURNEY-WORKSPACE-010",
            ) from exc
        if not root.is_dir():
            raise WorkspaceDirectoryError("请选择一个文件夹", "JOURNEY-WORKSPACE-010")
        try:
            has_workspace = any(root.rglob("journey_workspace.json"))
            has_recording = any(root.rglob("recording.mp4"))
        except OSError as exc:
            raise WorkspaceDirectoryError(
                f"无法读取所选文件夹：{root}",
                "JOURNEY-WORKSPACE-010",
            ) from exc
        if not has_workspace and not has_recording:
            raise WorkspaceDirectoryError(
                "所选文件夹中没有 journey_workspace.json 或 recording.mp4"
            )

        self.registry.add(root)
        with self._lock:
            self.discovery_roots = _unique_existing_directories((*self.discovery_roots, root))
            self._session_entries_cache = []
            self._session_entries_cached_at = 0.0

        entries_with_paths = self._session_entries()
        prepared_under_root = [
            item for item in entries_with_paths
            if item.get("prepared") and _is_relative_to(Path(str(item["path"])), root)
        ]
        payload = self.list_workspaces()
        raw_under_root = [
            item for item in entries_with_paths
            if not item.get("prepared") and _is_relative_to(Path(str(item["path"])), root)
        ]
        if len(prepared_under_root) == 1:
            payload.update({
                "suggested_id": prepared_under_root[0]["id"],
                "message": "已找到工作空间，正在切换Session",
            })
        elif prepared_under_root:
            payload["message"] = f"已加入{len(prepared_under_root)}个工作空间，请从列表选择"
        elif len(raw_under_root) == 1 and raw_under_root[0].get("preparable"):
            payload.update({
                "suggested_prepare_id": raw_under_root[0]["id"],
                "message": "已找到原始Session，请填写游戏名称后开始准备",
            })
        else:
            payload["message"] = "已找到原始Session，但需先生成抽帧拼图和工作空间"
        return payload

    def preparation_state(self) -> dict:
        with self._lock:
            return dict(self._prepare_state)

    def start_preparation(self, raw_workspace_id: str, game_name: str) -> dict:
        selected_id = str(raw_workspace_id or "").strip()
        clean_game_name = " ".join(str(game_name or "").split())
        if not clean_game_name:
            raise WorkspaceDirectoryError("准备原始Session前必须填写游戏名称")
        if len(clean_game_name) > 80:
            raise WorkspaceDirectoryError("游戏名称不能超过80个字符")
        candidates = {
            str(item["id"]): item
            for item in self._session_entries()
            if not item.get("prepared")
        }
        selected = candidates.get(selected_id)
        if selected is None:
            raise WorkspaceDirectoryError("原始Session不存在或已经完成准备")
        if not selected.get("preparable"):
            raise WorkspaceDirectoryError(str(selected.get("reason") or "原始Session缺少必要文件"))
        session_root = Path(str(selected["path"])).resolve()
        output_root = session_root / "analysis_output"
        workspace_root = output_root / "journey_workspace"
        with self._lock:
            if self._prepare_thread is not None and self._prepare_thread.is_alive():
                raise WorkspaceDirectoryError("已有Session正在后台准备")
            self._prepare_state = {
                "status": "starting",
                "session_id": str(selected.get("session_id") or session_root.name),
                "current": 0,
                "total": 0,
                "percent": 0,
                "message": "正在检查Session",
            }

        def worker() -> None:
            staging_root = output_root / (
                ".journey_prepare_" + datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            staging_workspace = staging_root / "workspace"
            try:
                def progress(done: int, total: int, message: str) -> None:
                    percent = round(done * 100 / total) if total > 0 else 0
                    with self._lock:
                        self._prepare_state.update({
                            "status": "running",
                            "current": max(0, int(done)),
                            "total": max(0, int(total)),
                            "percent": max(0, min(100, percent)),
                            "message": str(message or "正在生成抽帧拼图"),
                        })

                game_id = "game_" + hashlib.sha256(clean_game_name.encode("utf-8")).hexdigest()[:12]
                if workspace_root.exists():
                    raise JourneyPackageError(f"正式工作空间目录已存在: {workspace_root.name}")
                prepare_journey_run(
                    session_root,
                    staging_root,
                    game_id=game_id,
                    game_name=clean_game_name,
                    workspace_dir=staging_workspace,
                    progress=progress,
                )
                output_root.mkdir(parents=True, exist_ok=True)
                staging_workspace.replace(workspace_root)
                shutil.rmtree(staging_root, ignore_errors=True)
                self.registry.add(session_root)
                with self._lock:
                    self.discovery_roots = _unique_existing_directories((*self.discovery_roots, session_root))
                    self._session_entries_cache = []
                    self._session_entries_cached_at = 0.0
                    self._prepare_state = {
                        "status": "complete",
                        "session_id": str(selected.get("session_id") or session_root.name),
                        "current": 1,
                        "total": 1,
                        "percent": 100,
                        "message": "Session准备完成",
                        "workspace_id": _workspace_id(workspace_root),
                    }
            except (JourneyPackageError, OSError, ValueError, json.JSONDecodeError) as exc:
                with self._lock:
                    self._prepare_state = {
                        "status": "failed",
                        "session_id": str(selected.get("session_id") or session_root.name),
                        "current": 0,
                        "total": 0,
                        "percent": 0,
                        "message": str(exc),
                        "code": "JOURNEY-WORKSPACE-011",
                    }

        thread = threading.Thread(target=worker, name="journey-session-prepare", daemon=True)
        with self._lock:
            self._prepare_thread = thread
        thread.start()
        return self.preparation_state()

    def select_workspace(self, workspace_id: str) -> dict:
        selected_id = str(workspace_id or "").strip()
        candidates = {
            str(item["id"]): Path(str(item["path"]))
            for item in self._session_entries()
            if item.get("prepared")
        }
        target = candidates.get(selected_id)
        if target is None:
            raise JourneyPackageError("Session不存在、尚未准备或不在允许目录中")
        if target == self.root:
            return {**self.list_workspaces(), "selected": selected_id, "changed": False}

        replacement = WorkspaceApplications(
            target,
            ocr_runtime=self.ocr_runtime,
            discovery_roots=self.discovery_roots,
            registry_path=self.registry.path,
        )
        self.registry.add(target)
        with self._lock:
            self.root = replacement.root
            self.manifest = replacement.manifest
            self._applications = replacement._applications
            self._downstream_error = replacement._downstream_error
            self._session_entries_cache = []
            self._session_entries_cached_at = 0.0
            self._prepare_thread = None
            self._prepare_state = {"status": "idle"}
            self.ocr = replacement.ocr
        return {**self.list_workspaces(), "selected": selected_id, "changed": True}

    def _session_entries(self) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            if self._session_entries_cache and now - self._session_entries_cached_at < 30:
                return [dict(item) for item in self._session_entries_cache]
        entries = _discover_session_entries(self.discovery_roots, self.root, include_paths=True)
        with self._lock:
            self._session_entries_cache = [dict(item) for item in entries]
            self._session_entries_cached_at = now
        return entries


def _unique_existing_directories(paths) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        candidate = Path(path)
        if not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return tuple(result)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _workspace_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).casefold().encode("utf-8")).hexdigest()[:16]


def _read_manifest_summary(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("session"), dict):
        return None
    return payload


def _discover_session_entries(
    roots: tuple[Path, ...],
    current_root: Path,
    *,
    include_paths: bool = False,
) -> list[dict]:
    prepared: dict[str, dict] = {}
    prepared_roots: set[Path] = set()
    session_ids: set[str] = set()
    manifests: set[Path] = {current_root / "journey_workspace.json"}
    for root in roots:
        if root.is_dir():
            manifests.update(root.rglob("journey_workspace.json"))
    for manifest_path in sorted(manifests, key=lambda item: str(item).casefold()):
        payload = _read_manifest_summary(manifest_path)
        if payload is None:
            continue
        workspace_root = manifest_path.parent.resolve()
        session = payload["session"]
        session_id = str(session.get("session_id") or workspace_root.name).strip()
        game_name = str(session.get("game_name") or "未命名游戏").strip()
        try:
            duration_ms = int(session.get("duration_ms") or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        entry = {
            "id": _workspace_id(workspace_root),
            "session_id": session_id,
            "game_name": game_name,
            "label": f"{game_name} · {session_id}",
            "duration_ms": max(0, duration_ms),
            "prepared": True,
            "current": workspace_root == current_root,
            "reason": "",
            "_variant": workspace_root.parent.name if workspace_root.name == "workspace" else workspace_root.name,
        }
        if include_paths:
            entry["path"] = str(workspace_root)
        prepared[entry["id"]] = entry
        prepared_roots.add(workspace_root)
        session_ids.add(session_id)

    raw_entries: dict[str, dict] = {}
    for sessions_root in roots:
        if sessions_root.is_dir():
            for video_path in sorted(sessions_root.rglob("recording.mp4"), key=lambda item: str(item).casefold()):
                session_root = video_path.parent.resolve()
                session_id = session_root.name
                if session_id in session_ids or any(
                    _is_relative_to(session_root, workspace_root)
                    for workspace_root in prepared_roots
                ):
                    continue
                stat = video_path.stat()
                has_mouse_events = (session_root / "mouse_events.jsonl").is_file()
                has_session_meta = (session_root / "session_meta.json").is_file()
                is_native_session = has_mouse_events and has_session_meta
                raw_entries[str(session_root).casefold()] = {
                    "id": f"raw-{_workspace_id(session_root)}",
                    "session_id": session_id,
                    "game_name": "未配置游戏",
                    "label": f"{session_id} · 需准备分析资料",
                    "duration_ms": 0,
                    "prepared": False,
                    "current": False,
                    "reason": (
                        "可复用录屏交接或按点击生成拼图"
                        if is_native_session
                        else "普通视频模式：按10秒间隔生成备用拼图"
                    ),
                    "source_mode": "native_session" if is_native_session else "plain_video",
                    "preparable": True,
                    "video_size": stat.st_size,
                }
                if include_paths:
                    raw_entries[str(session_root).casefold()]["path"] = str(session_root)
    session_counts: dict[str, int] = {}
    for entry in prepared.values():
        key = str(entry["session_id"])
        session_counts[key] = session_counts.get(key, 0) + 1
    for entry in prepared.values():
        if session_counts[str(entry["session_id"])] > 1:
            entry["label"] = f"{entry['label']} · {entry['_variant']}"
        entry.pop("_variant", None)

    return sorted(
        [*prepared.values(), *raw_entries.values()],
        key=lambda item: (not bool(item["current"]), not bool(item["prepared"]), str(item["session_id"])),
    )


class JourneyWorkspaceHandler(BaseHTTPRequestHandler):
    applications: WorkspaceApplications

    def log_message(self, format: str, *args) -> None:
        return

    def _json_response(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 64_000:
            raise JourneyPackageError("请求体为空或过大")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise JourneyPackageError("请求体必须是JSON对象")
        return payload

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _unavailable_page(self, section: str) -> None:
        state = self.applications.state()
        stages = state.get("stages") or {}
        stage_key = "event_review" if section == "events" else "metric_review"
        stage = stages.get(stage_key) or {}
        scan = stages.get("region_scan") or {}
        reason = str(
            state.get("downstream_error")
            or scan.get("reason")
            or stage.get("reason")
            or "当前步骤尚未生成可复核数据"
        )
        labels = {"manual": "人工选帧", "regions": "区域校准", "events": "功能事件", "metrics": "指标结果"}
        links = "".join(
            f'<a href="{route}" class="{"active" if name == section else ""}">{labels[name]}</a>'
            for name, route in ROUTES.items()
        )
        body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{labels[section]}</title><style>
body{{margin:0;background:#f8fafb;color:#17202a;font:15px/1.6 "Segoe UI","Microsoft YaHei",sans-serif}}
.action{{display:inline-flex;height:36px;align-items:center;padding:0 16px;border-radius:4px;background:#176b55;color:#fff;text-decoration:none}}
</style><link rel="stylesheet" href="/workspace-shell.css"><script src="/workspace-shell.js" defer></script></head>
<body class="workspace-shell-body">
<header class="workspace-shell-header">
  <div class="workspace-shell-brand"><span class="workspace-shell-brand__mark">历</span><div class="workspace-shell-brand__copy"><strong>历程拆解</strong><span>Journey Review</span></div></div>
  <nav class="workspace-shell-nav" aria-label="分析流程">{links}</nav>
  <div class="workspace-shell-context"><div class="workspace-shell-page"><strong>{labels[section]}</strong><select class="workspace-shell-session" aria-label="切换Session"><option>加载Session...</option></select></div></div>
</header>
<div class="workspace-shell-toolbar"><strong>{labels[section]}</strong></div>
<main class="workspace-shell-unavailable"><h1>当前步骤暂不可用</h1><p>{html.escape(reason)}</p><a class="action" href="{ROUTES['regions']}">返回区域校准</a></main>
</body></html>"""
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _dispatch(self, method_name: str) -> None:
        path = urlsplit(self.path).path
        if path == "/workspace-shell.css":
            if method_name != "do_GET":
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            body = SHELL_CSS.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/workspace-shell.js":
            if method_name != "do_GET":
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            body = SHELL_JS.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/workspace":
            if method_name == "do_GET":
                self._json_response(self.applications.state())
            else:
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
            return
        if path == "/api/workspaces":
            if method_name == "do_GET":
                self._json_response(self.applications.list_workspaces())
            else:
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
            return
        if path == "/api/workspace/select":
            if method_name != "do_POST":
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            try:
                request = self._json_body()
                self._json_response(self.applications.select_workspace(str(request.get("workspace_id") or "")))
            except (JourneyPackageError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._json_response({
                    "status": "error",
                    "code": "JOURNEY-WORKSPACE-007",
                    "message": str(exc),
                }, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/workspace/browse":
            if method_name != "do_POST":
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            try:
                selected = _choose_workspace_directory(self.applications.browse_initial_directory())
                if selected is None:
                    self._json_response({
                        "status": "cancelled",
                        "code": "JOURNEY-WORKSPACE-008",
                        "message": "已取消选择",
                    })
                    return
                self._json_response(self.applications.register_workspace_directory(selected))
            except WorkspaceDirectoryError as exc:
                self._json_response({
                    "status": "error",
                    "code": exc.code,
                    "message": str(exc),
                }, HTTPStatus.BAD_REQUEST)
            except (OSError, ValueError) as exc:
                self._json_response({
                    "status": "error",
                    "code": "JOURNEY-WORKSPACE-010",
                    "message": str(exc),
                }, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/workspace/prepare":
            if method_name == "do_GET":
                self._json_response(self.applications.preparation_state())
                return
            if method_name != "do_POST":
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            try:
                request = self._json_body()
                self._json_response(self.applications.start_preparation(
                    str(request.get("workspace_id") or ""),
                    str(request.get("game_name") or ""),
                ), HTTPStatus.ACCEPTED)
            except WorkspaceDirectoryError as exc:
                self._json_response({
                    "status": "error",
                    "code": exc.code,
                    "message": str(exc),
                }, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/shutdown":
            if method_name != "do_POST":
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            if self.client_address[0] not in {"127.0.0.1", "::1"}:
                self._json_response({
                    "status": "error",
                    "code": "JOURNEY-WORKSPACE-012",
                    "message": "只允许在本机关闭分析工具",
                }, HTTPStatus.FORBIDDEN)
                return
            self._json_response({
                "status": "stopping",
                "message": "历程分析工具正在关闭",
            }, HTTPStatus.ACCEPTED)
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/":
            self._redirect(ROUTES["manual"])
            return
        section = path.strip("/").split("/", 1)[0]
        if section not in ROUTES:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if path == f"/{section}":
            self._redirect(ROUTES[section])
            return
        application = self.applications.get(section)
        if application is None:
            if method_name == "do_GET" and path in {f"/{section}/", f"/{section}/index.html"}:
                self._unavailable_page(section)
                return
            self._json_response({
                "status": "unavailable",
                "code": "JOURNEY-WORKSPACE-006",
                "message": "当前步骤尚未生成可复核数据",
                "section": section,
            }, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self.workspace = application.workspace
        self.scan_job = application.scan_job
        for helper_name in ("_json", "_body", "_send_file", "_error"):
            helper = getattr(application.handler, helper_name, None)
            if helper is not None:
                setattr(self, helper_name, helper.__get__(self, type(self)))
        getattr(application.handler, method_name)(self)

    def do_GET(self) -> None:
        self._dispatch("do_GET")

    def do_POST(self) -> None:
        self._dispatch("do_POST")


def main() -> int:
    parser = argparse.ArgumentParser(description="从唯一 journey_workspace.json 启动单端口工作台")
    parser.add_argument("workspace_dir", type=Path, nargs="?", help="可选；不填写时自动打开最近的工作空间")
    parser.add_argument("--ocr-runtime", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        applications = WorkspaceApplications(
            _resolve_startup_workspace(args.workspace_dir),
            ocr_runtime=args.ocr_runtime,
        )
        JourneyWorkspaceHandler.applications = applications
        server = ThreadingHTTPServer((args.host, args.port), JourneyWorkspaceHandler)
    except (JourneyPackageError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "status": "error",
            "code": "JOURNEY-WORKSPACE-004",
            "message": str(exc),
        }, ensure_ascii=False))
        return 2
    base_url = f"http://{args.host}:{server.server_port}"
    urls = {name: base_url + route for name, route in ROUTES.items()}
    print(json.dumps({
        "status": "ready",
        "workspace": str(applications.root),
        "url": urls["manual"],
        "urls": urls,
        "stages": applications.manifest["stages"],
    }, ensure_ascii=False), flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(urls["manual"])).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
