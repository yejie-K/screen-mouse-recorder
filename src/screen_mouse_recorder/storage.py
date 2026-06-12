from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, TextIO


class JsonlWriter:
    def __init__(self, path: Path, flush_every: int = 20) -> None:
        self.path = path
        self.flush_every = flush_every
        self._file: TextIO | None = None
        self._lock = Lock()
        self._count = 0

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8", newline="\n")

    def write(self, row: dict[str, Any]) -> None:
        if self._file is None:
            raise RuntimeError("JsonlWriter is not open")
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._file.write(line + "\n")
            self._count += 1
            if self._count % self.flush_every == 0:
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._file.close()
                self._file = None


class SessionStorage:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.recording_mp4 = session_dir / "recording.mp4"
        self.mouse_events = session_dir / "mouse_events.jsonl"
        self.mouse_samples = session_dir / "mouse_samples.jsonl"
        self.session_meta = session_dir / "session_meta.json"
        self.calibration = session_dir / "calibration.json"
        self.mouse_summary = session_dir / "mouse_summary.json"
        self.mouse_summary_xlsx = session_dir / "mouse_summary.xlsx"
        self.mouse_analysis_xlsx = session_dir / "mouse_analysis.xlsx"
        self.ffmpeg_log = session_dir / "ffmpeg.log"

    @classmethod
    def create_unique(cls, output_root: Path, session_id: str) -> "SessionStorage":
        output_root.mkdir(parents=True, exist_ok=True)
        session_dir = output_root / session_id
        suffix = 1
        while session_dir.exists():
            session_dir = output_root / f"{session_id}_{suffix:02d}"
            suffix += 1
        session_dir.mkdir(parents=True)
        return cls(session_dir)

    def write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
