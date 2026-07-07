from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from PIL import Image

from .models import VideoInfo


def resolve_ffmpeg(ffmpeg_path: str | None = None) -> str:
    if ffmpeg_path:
        path = Path(ffmpeg_path)
        if path.exists():
            return str(path)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError("FFmpeg not found. Configure ffmpeg_path in config.json or add ffmpeg.exe to PATH.")

def resolve_ffprobe(ffmpeg_path: str | None = None) -> str:
    if ffmpeg_path:
        ffmpeg = Path(ffmpeg_path)
        candidate = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe")
        if candidate.exists():
            return str(candidate)
    found = shutil.which("ffprobe")
    if found:
        return found
    raise FileNotFoundError("ffprobe not found next to ffmpeg.exe or on PATH.")

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

def extract_preview_frame(video_path: Path, ffmpeg_path: str | None = None, seconds: float = 0.0) -> Image.Image:
    ffmpeg = resolve_ffmpeg(ffmpeg_path)
    return _extract_frame(ffmpeg, video_path, seconds)

def _parse_fps(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    return float(value or 0)

def _extract_frame(ffmpeg: str, video_path: Path, seconds: float) -> Image.Image:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{seconds:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    proc = subprocess.run(command, capture_output=True, check=False, **_hidden_subprocess_kwargs())
    if proc.returncode != 0 or not proc.stdout:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"Failed to extract frame at {seconds:.3f}s")
    return Image.open(io.BytesIO(proc.stdout)).convert("RGB")

def _hidden_subprocess_kwargs() -> dict[str, Any]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": creationflags} if creationflags else {}

