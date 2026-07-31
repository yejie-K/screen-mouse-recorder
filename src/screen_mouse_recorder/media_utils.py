"""Generic video/timecode helpers shared by recorder, frame_export, and ocr.

This module holds media primitives that depend on nothing else in the package
(only stdlib + PIL), so that OCR and other consumers can use ffmpeg frame
extraction and timecode parsing without reaching into ``frame_export``.

Keep this module free of any business models (e.g. VideoInfo). Functions that
need package-specific models belong in the module that owns those models.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": creationflags} if creationflags else {}


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


def parse_fps(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    return float(value or 0)


# Backwards-compatible private alias (frame_export historically imported _parse_fps).
_parse_fps = parse_fps


def extract_frame(ffmpeg: str, video_path: Path, seconds: float) -> Image.Image:
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


# Backwards-compatible private alias (frame_export/ocr historically imported _extract_frame).
_extract_frame = extract_frame


def extract_preview_frame(video_path: Path, ffmpeg_path: str | None = None, seconds: float = 0.0) -> Image.Image:
    ffmpeg = resolve_ffmpeg(ffmpeg_path)
    return extract_frame(ffmpeg, video_path, seconds)


def parse_timecode(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return max(0.0, float(text))
    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid timecode: {value}")
    numbers = [float(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        return max(0.0, minutes * 60 + seconds)
    hours, minutes, seconds = numbers
    return max(0.0, hours * 3600 + minutes * 60 + seconds)


def format_timecode(seconds: float, *, filename_safe: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis >= 1000:
        whole += 1
        millis -= 1000
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    if millis:
        text = f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    else:
        text = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return text.replace(":", "-").replace(".", "-") if filename_safe else text
