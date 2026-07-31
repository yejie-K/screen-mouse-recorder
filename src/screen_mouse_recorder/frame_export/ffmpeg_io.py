from __future__ import annotations

import json
from pathlib import Path
import subprocess

from ..media_utils import (
    _extract_frame,
    _hidden_subprocess_kwargs,
    _parse_fps,
    extract_frame,
    extract_preview_frame,
    parse_fps,
    resolve_ffmpeg,
    resolve_ffprobe,
)
from .models import VideoInfo

# resolve_ffmpeg / resolve_ffprobe / _extract_frame / extract_frame /
# extract_preview_frame / _parse_fps / parse_fps / _hidden_subprocess_kwargs are
# re-exported from media_utils so existing imports of this module keep working.
__all__ = [
    "resolve_ffmpeg",
    "resolve_ffprobe",
    "probe_video",
    "extract_preview_frame",
    "extract_frame",
    "_extract_frame",
    "parse_fps",
    "_parse_fps",
    "_hidden_subprocess_kwargs",
]


def probe_video(video_path: Path, ffmpeg_path: str | None = None) -> VideoInfo:
    video_path = video_path.resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    ffprobe = resolve_ffprobe(ffmpeg_path)
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,duration",
        "-show_entries",
        "format=duration,size",
        "-of",
        "json",
        str(video_path),
    ]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **_hidden_subprocess_kwargs(),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffprobe failed")
    data = json.loads(proc.stdout)
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    duration = float(stream.get("duration") or fmt.get("duration") or 0)
    file_size = int(fmt.get("size") or video_path.stat().st_size)
    fps = _parse_fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    if width <= 0 or height <= 0 or duration <= 0:
        raise RuntimeError(f"Could not read video metadata for {video_path}")
    return VideoInfo(video_path, duration, width, height, fps, file_size)
