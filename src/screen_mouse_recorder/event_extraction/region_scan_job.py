from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock, Thread
from typing import Any

from .ocr_events import OCREngine
from .region_scan import RegionScanConfig, scan_all_extracted_frames


class RegionScanJob:
    """Run a region scan in the background and expose a small polling state."""

    def __init__(self, config: RegionScanConfig, *, engine: OCREngine | None = None) -> None:
        self.config = config
        self.engine = engine
        self._lock = RLock()
        self._thread: Thread | None = None
        self._state: dict[str, Any] = {
            "available": True,
            "status": "idle",
            "done": 0,
            "total": 0,
            "message": "等待开始",
            "error_code": "",
            "error_message": "",
            "result": {},
            "output_dir": str(config.output_dir.resolve()),
        }
        self._restore_completed_scan()

    def _restore_completed_scan(self) -> None:
        manifest_path = self.config.output_dir.resolve() / "region_scan_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            counts = manifest["counts"]
            frames_total = int(counts["frames_total"])
            frames_scanned = int(counts["frames_scanned"])
            if frames_total <= 0 or frames_scanned != frames_total:
                return
            outputs = {Path(value).name for value in manifest.get("outputs") or []}
            event_json = "event_observations_v2.json"
            metric_json = "metric_observations_v2.json"
            if event_json not in outputs or metric_json not in outputs:
                return
            if not all((self.config.output_dir / name).is_file() for name in (event_json, metric_json)):
                return
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return
        self._state.update({
            "status": "complete",
            "done": frames_scanned,
            "total": frames_total,
            "message": "区域扫描完成",
            "result": {
                "frames_total": frames_total,
                "frames_scanned": frames_scanned,
                "region_scans": int(counts.get("region_scans") or 0),
                "event_count": int(counts.get("event_observations") or 0),
                "metric_count": int(counts.get("metric_observations") or 0),
                "elapsed_seconds": float((manifest.get("timing") or {}).get("total_elapsed_seconds") or 0),
                "event_json": event_json,
                "metric_json": metric_json,
                "manifest_json": manifest_path.name,
            },
        })

    def state(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return deepcopy(self._state)
            self._state.update({
                "status": "running",
                "done": 0,
                "total": 0,
                "message": "正在准备区域扫描",
                "error_code": "",
                "error_message": "",
                "result": {},
            })
            self._thread = Thread(target=self._run, name="ocr-region-scan", daemon=True)
            self._thread.start()
            return deepcopy(self._state)

    def wait(self, timeout: float | None = None) -> dict[str, Any]:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return self.state()

    def _progress(self, done: int, total: int, message: str) -> None:
        with self._lock:
            self._state.update({"done": done, "total": total, "message": message})

    def _run(self) -> None:
        try:
            result = scan_all_extracted_frames(
                self.config,
                engine=self.engine,
                progress=self._progress,
            )
        except Exception as exc:  # The polling API must report worker failures instead of losing the thread.
            with self._lock:
                self._state.update({
                    "status": "error",
                    "message": "区域扫描失败",
                    "error_code": "OCR-REGION-SCAN-001",
                    "error_message": str(exc),
                })
            return
        with self._lock:
            self._state.update({
                "status": "complete",
                "done": result.frames_scanned,
                "total": result.frames_total,
                "message": "区域扫描完成",
                "result": {
                    "frames_total": result.frames_total,
                    "frames_scanned": result.frames_scanned,
                    "region_scans": result.region_scans,
                    "event_count": result.event_count,
                    "metric_count": result.metric_count,
                    "elapsed_seconds": result.elapsed_seconds,
                    "event_json": result.event_json.name,
                    "metric_json": result.metric_json.name,
                    "manifest_json": result.manifest_json.name,
                },
            })
