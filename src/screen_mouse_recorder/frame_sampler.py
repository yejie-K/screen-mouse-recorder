from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from html import escape
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Callable

from PIL import Image, ImageDraw, ImageFont


@dataclass(slots=True)
class VideoInfo:
    path: Path
    duration_seconds: float
    width: int
    height: int
    fps: float
    file_size_bytes: int


@dataclass(slots=True)
class CropRegion:
    x: int
    y: int
    width: int
    height: int


@dataclass(slots=True)
class DenseRange:
    start_seconds: float
    end_seconds: float
    interval_seconds: float


@dataclass(slots=True)
class ClickMarker:
    seconds: float
    x: float
    y: float


@dataclass(slots=True)
class FrameSamplerConfig:
    video_path: Path
    output_dir: Path
    start_seconds: float = 0.0
    end_seconds: float | None = None
    interval_seconds: float = 10.0
    sheet_cols: int = 5
    sheet_rows: int = 6
    thumb_width: int = 360
    jpeg_quality: int = 85
    output_format: str = "jpg"
    show_timestamp: bool = True
    show_index: bool = True
    crop: CropRegion | None = None
    dense_ranges: list[DenseRange] = field(default_factory=list)
    dense_start_seconds: float | None = None
    dense_end_seconds: float | None = None
    dense_interval_seconds: float | None = None
    click_events_path: Path | None = None
    draw_click_markers: bool = False
    click_match_window_seconds: float = 0.5


@dataclass(slots=True)
class FramePlanEntry:
    index: int
    seconds: float
    timestamp: str
    is_dense: bool
    sheet_index: int
    sheet_row: int
    sheet_col: int


@dataclass(slots=True)
class FrameSamplerEstimate:
    duration_seconds: float
    effective_start_seconds: float
    effective_end_seconds: float
    frame_count: int
    sheet_count: int
    frames_per_sheet: int
    estimated_processing_seconds: float
    estimated_output_mb: float


@dataclass(slots=True)
class FrameSamplerResult:
    output_dir: Path
    sheets_dir: Path
    sheet_paths: list[Path]
    index_csv: Path
    report_html: Path
    config_json: Path
    estimate: FrameSamplerEstimate


ProgressCallback = Callable[[int, int, str], None]


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


def default_output_dir(
    video_path: Path,
    output_root: Path,
    *,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    unique: bool = True,
) -> Path:
    safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", video_path.parent.name).strip("._-") or video_path.stem or "video"
    range_text = f"{_compact_timecode(start_seconds)}-{_compact_timecode(end_seconds)}"
    index = 1
    while True:
        candidate = output_root / f"{safe_name}_抽帧{index}（{range_text}）"
        if not unique or not candidate.exists():
            return candidate
        index += 1


def _compact_timecode(seconds: float | None) -> str:
    if seconds is None:
        return "end"
    seconds = max(0.0, float(seconds))
    whole = int(round(seconds))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}{minutes:02d}{secs:02d}"


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
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
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


def build_frame_plan(config: FrameSamplerConfig, video_info: VideoInfo) -> list[FramePlanEntry]:
    start = max(0.0, config.start_seconds)
    end = min(video_info.duration_seconds, config.end_seconds if config.end_seconds is not None else video_info.duration_seconds)
    if end < start:
        raise ValueError("End time must be greater than start time.")
    interval = max(0.1, config.interval_seconds)
    times: dict[int, tuple[float, bool]] = {}

    current = start
    while current <= end + 0.0001:
        key = int(round(current * 1000))
        times[key] = (round(current, 3), False)
        current += interval

    dense_ranges = list(config.dense_ranges)
    if (
        config.dense_start_seconds is not None
        and config.dense_end_seconds is not None
        and config.dense_interval_seconds is not None
    ):
        dense_ranges.append(
            DenseRange(
                start_seconds=config.dense_start_seconds,
                end_seconds=config.dense_end_seconds,
                interval_seconds=config.dense_interval_seconds,
            )
        )

    for dense_range in dense_ranges:
        dense_start = max(start, dense_range.start_seconds)
        dense_end = min(end, dense_range.end_seconds)
        dense_interval = max(0.1, dense_range.interval_seconds)
        if dense_end < dense_start:
            continue
        current = dense_start
        while current <= dense_end + 0.0001:
            key = int(round(current * 1000))
            existing = times.get(key)
            times[key] = (round(current, 3), True if existing is None else existing[1] or True)
            current += dense_interval

    per_sheet = max(1, config.sheet_cols * config.sheet_rows)
    entries: list[FramePlanEntry] = []
    for index, (_key, (seconds, is_dense)) in enumerate(sorted(times.items()), start=1):
        zero_index = index - 1
        sheet_zero = zero_index // per_sheet
        position = zero_index % per_sheet
        entries.append(
            FramePlanEntry(
                index=index,
                seconds=seconds,
                timestamp=format_timecode(seconds),
                is_dense=is_dense,
                sheet_index=sheet_zero + 1,
                sheet_row=position // config.sheet_cols + 1,
                sheet_col=position % config.sheet_cols + 1,
            )
        )
    return entries


def estimate_sampling(config: FrameSamplerConfig, video_info: VideoInfo) -> FrameSamplerEstimate:
    plan = build_frame_plan(config, video_info)
    frames_per_sheet = max(1, config.sheet_cols * config.sheet_rows)
    sheet_count = math.ceil(len(plan) / frames_per_sheet) if plan else 0
    end = min(video_info.duration_seconds, config.end_seconds if config.end_seconds is not None else video_info.duration_seconds)
    # Conservative local estimate: one FFmpeg seek per frame plus Pillow composition/export.
    thumb_factor = max(0.65, config.thumb_width / 360)
    estimated_seconds = len(plan) * 0.28 * thumb_factor + sheet_count * 0.8
    estimated_mb = sheet_count * config.sheet_cols * config.sheet_rows * (config.thumb_width * 0.000018)
    return FrameSamplerEstimate(
        duration_seconds=video_info.duration_seconds,
        effective_start_seconds=max(0.0, config.start_seconds),
        effective_end_seconds=end,
        frame_count=len(plan),
        sheet_count=sheet_count,
        frames_per_sheet=frames_per_sheet,
        estimated_processing_seconds=estimated_seconds,
        estimated_output_mb=estimated_mb,
    )


def sample_video_to_sheets(
    config: FrameSamplerConfig,
    ffmpeg_path: str | None = None,
    progress: ProgressCallback | None = None,
) -> FrameSamplerResult:
    video_info = probe_video(config.video_path, ffmpeg_path)
    estimate = estimate_sampling(config, video_info)
    plan = build_frame_plan(config, video_info)
    if not plan:
        raise ValueError("No frames to sample.")

    ffmpeg = resolve_ffmpeg(ffmpeg_path)
    output_dir = config.output_dir.resolve()
    sheets_dir = output_dir / "sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)

    sheet_paths: list[Path] = []
    frames_per_sheet = max(1, config.sheet_cols * config.sheet_rows)
    total = len(plan)
    start_time = time.perf_counter()
    click_markers = load_click_markers(config.click_events_path) if config.draw_click_markers else []
    output_format = _normalized_output_format(config.output_format)

    for sheet_offset in range(0, total, frames_per_sheet):
        sheet_entries = plan[sheet_offset : sheet_offset + frames_per_sheet]
        thumbs: list[Image.Image] = []
        for entry in sheet_entries:
            if progress:
                progress(entry.index, total, f"抽帧 {entry.timestamp}")
            image = _extract_frame(ffmpeg, config.video_path, entry.seconds)
            click_marker = _nearest_click_marker(click_markers, entry.seconds, config.click_match_window_seconds)
            image, click_position = _prepare_frame_image(image, config.crop, config.thumb_width, click_marker)
            _draw_overlay(image, entry, config)
            _draw_click_marker(image, click_position)
            thumbs.append(image)
        sheet_image = _compose_sheet(thumbs, sheet_entries, config)
        first = format_timecode(sheet_entries[0].seconds, filename_safe=True)
        last = format_timecode(sheet_entries[-1].seconds, filename_safe=True)
        suffix = "png" if output_format == "png" else "jpg"
        sheet_path = sheets_dir / f"sheet_{sheet_entries[0].sheet_index:03d}_{first}_to_{last}.{suffix}"
        if output_format == "png":
            sheet_image.save(sheet_path, "PNG", optimize=True)
        else:
            sheet_image.save(sheet_path, "JPEG", quality=max(40, min(100, config.jpeg_quality)), optimize=True)
        sheet_paths.append(sheet_path)
        for thumb in thumbs:
            thumb.close()
        sheet_image.close()

    if progress:
        progress(total, total, "写入索引")
    index_csv = output_dir / "index.csv"
    _write_index_csv(index_csv, plan, sheet_paths)
    config_json = output_dir / "config.json"
    _write_config_json(config_json, config, video_info, estimate)
    report_html = output_dir / "report.html"
    _write_report_html(report_html, config, video_info, estimate, sheet_paths, time.perf_counter() - start_time)

    if progress:
        progress(total, total, "完成")
    return FrameSamplerResult(output_dir, sheets_dir, sheet_paths, index_csv, report_html, config_json, estimate)


def extract_preview_frame(video_path: Path, ffmpeg_path: str | None = None, seconds: float = 0.0) -> Image.Image:
    ffmpeg = resolve_ffmpeg(ffmpeg_path)
    return _extract_frame(ffmpeg, video_path, seconds)


def load_click_markers(path: Path | None) -> list[ClickMarker]:
    if path is None:
        return []
    path = path.resolve()
    if not path.exists():
        return []
    markers: list[ClickMarker] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event_type") != "click":
                continue
            t_video_ms = _safe_float(row.get("t_video_ms"))
            x = _safe_float(row.get("video_x"))
            y = _safe_float(row.get("video_y"))
            if t_video_ms is None or x is None or y is None:
                continue
            markers.append(ClickMarker(seconds=t_video_ms / 1000, x=x, y=y))
    markers.sort(key=lambda marker: marker.seconds)
    return markers


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
    proc = subprocess.run(command, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"Failed to extract frame at {seconds:.3f}s")
    return Image.open(io.BytesIO(proc.stdout)).convert("RGB")


def _crop_and_resize(image: Image.Image, crop: CropRegion | None, thumb_width: int) -> Image.Image:
    image, _click_position = _prepare_frame_image(image, crop, thumb_width, None)
    return image


def _prepare_frame_image(
    image: Image.Image,
    crop: CropRegion | None,
    thumb_width: int,
    click_marker: ClickMarker | None,
) -> tuple[Image.Image, tuple[int, int] | None]:
    left, top, right, bottom = _crop_box(image, crop)
    click_position = _map_click_marker(click_marker, left, top, right, bottom, thumb_width)
    if (left, top, right, bottom) != (0, 0, image.width, image.height):
        image = image.crop((left, top, right, bottom))
    width = max(120, int(thumb_width))
    height = max(1, round(image.height * (width / image.width)))
    return image.resize((width, height), Image.Resampling.LANCZOS), click_position


def _crop_box(image: Image.Image, crop: CropRegion | None) -> tuple[int, int, int, int]:
    if crop is not None and crop.width > 0 and crop.height > 0:
        left = max(0, min(image.width - 1, crop.x))
        top = max(0, min(image.height - 1, crop.y))
        right = max(left + 1, min(image.width, left + crop.width))
        bottom = max(top + 1, min(image.height, top + crop.height))
        return left, top, right, bottom
    return 0, 0, image.width, image.height


def _map_click_marker(
    click_marker: ClickMarker | None,
    left: int,
    top: int,
    right: int,
    bottom: int,
    thumb_width: int,
) -> tuple[int, int] | None:
    if click_marker is None:
        return None
    if not (left <= click_marker.x <= right and top <= click_marker.y <= bottom):
        return None
    crop_width = max(1, right - left)
    scale = max(120, int(thumb_width)) / crop_width
    return round((click_marker.x - left) * scale), round((click_marker.y - top) * scale)


def _draw_overlay(image: Image.Image, entry: FramePlanEntry, config: FrameSamplerConfig) -> None:
    if not config.show_timestamp and not config.show_index:
        return
    draw = ImageDraw.Draw(image, "RGBA")
    font_size = max(13, min(24, image.width // 18))
    font = _load_font(font_size)
    lines: list[str] = []
    if config.show_index:
        lines.append(f"#{entry.index:03d}")
    if config.show_timestamp:
        lines.append(entry.timestamp)
    label = "  ".join(lines)
    bbox = draw.textbbox((0, 0), label, font=font)
    pad = max(5, font_size // 3)
    rect = (6, 6, 6 + (bbox[2] - bbox[0]) + pad * 2, 6 + (bbox[3] - bbox[1]) + pad * 2)
    fill = (0, 0, 0, 168 if not entry.is_dense else 196)
    draw.rounded_rectangle(rect, radius=5, fill=fill)
    draw.text((rect[0] + pad, rect[1] + pad), label, fill=(255, 255, 255, 255), font=font)
    if entry.is_dense:
        draw.rectangle((image.width - 8, 0, image.width, image.height), fill=(31, 111, 178, 190))


def _draw_click_marker(image: Image.Image, position: tuple[int, int] | None) -> None:
    if position is None:
        return
    x, y = position
    radius = max(7, min(14, image.width // 32))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2), fill=(255, 255, 255, 230))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(216, 59, 59, 220))
    inner = max(3, radius // 2)
    draw.ellipse((x - inner, y - inner, x + inner, y + inner), fill=(255, 255, 255, 120))


def _compose_sheet(images: list[Image.Image], entries: list[FramePlanEntry], config: FrameSamplerConfig) -> Image.Image:
    cols = max(1, config.sheet_cols)
    rows = max(1, config.sheet_rows)
    gap = 8
    header_h = 46
    thumb_w = max(image.width for image in images)
    thumb_h = max(image.height for image in images)
    canvas_w = cols * thumb_w + (cols + 1) * gap
    canvas_h = header_h + rows * thumb_h + (rows + 1) * gap
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#edf1f4")
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(18)
    title = f"Sheet {entries[0].sheet_index:03d}  {entries[0].timestamp} - {entries[-1].timestamp}"
    draw.text((gap, 12), title, fill="#17212b", font=title_font)
    for image, entry in zip(images, entries):
        row = entry.sheet_row - 1
        col = entry.sheet_col - 1
        x = gap + col * (thumb_w + gap)
        y = header_h + gap + row * (thumb_h + gap)
        canvas.paste(image, (x, y))
    return canvas


def _write_index_csv(path: Path, plan: list[FramePlanEntry], sheet_paths: list[Path]) -> None:
    sheet_by_index = {index + 1: sheet_path for index, sheet_path in enumerate(sheet_paths)}
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["帧序号", "视频时间戳", "秒数", "所属合成图", "合成图内行", "合成图内列", "是否关键段加密抽帧"])
        for entry in plan:
            writer.writerow(
                [
                    entry.index,
                    entry.timestamp,
                    f"{entry.seconds:.3f}",
                    sheet_by_index.get(entry.sheet_index, Path("")).name,
                    entry.sheet_row,
                    entry.sheet_col,
                    "是" if entry.is_dense else "否",
                ]
            )


def _write_config_json(path: Path, config: FrameSamplerConfig, video_info: VideoInfo, estimate: FrameSamplerEstimate) -> None:
    data = {
        "config": _jsonable(asdict(config)),
        "video": _jsonable(asdict(video_info)),
        "estimate": asdict(estimate),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_report_html(
    path: Path,
    config: FrameSamplerConfig,
    video_info: VideoInfo,
    estimate: FrameSamplerEstimate,
    sheet_paths: list[Path],
    elapsed_seconds: float,
) -> None:
    rows = [
        ("视频", str(video_info.path)),
        ("时长", format_timecode(video_info.duration_seconds)),
        ("分辨率", f"{video_info.width}x{video_info.height}"),
        ("抽帧范围", f"{format_timecode(estimate.effective_start_seconds)} - {format_timecode(estimate.effective_end_seconds)}"),
        ("抽帧间隔", f"{config.interval_seconds:g} 秒"),
        ("拼图布局", f"{config.sheet_cols} x {config.sheet_rows}"),
        ("抽帧数量", str(estimate.frame_count)),
        ("合成图数量", str(estimate.sheet_count)),
        ("实际耗时", f"{elapsed_seconds:.1f} 秒"),
    ]
    image_html = "\n".join(
        f'<section><h2>{escape(sheet.name)}</h2><a href="sheets/{escape(sheet.name)}"><img src="sheets/{escape(sheet.name)}" /></a></section>'
        for sheet in sheet_paths
    )
    metadata = "\n".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows)
    path.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>抽帧拼图报告</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; background: #edf1f4; color: #17212b; }}
    h1 {{ margin: 0 0 16px; font-size: 24px; }}
    h2 {{ margin: 24px 0 10px; font-size: 16px; }}
    table {{ border-collapse: collapse; margin-bottom: 18px; background: white; }}
    th, td {{ border: 1px solid #c7d0d8; padding: 8px 10px; text-align: left; }}
    th {{ width: 120px; background: #f8fafb; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #c7d0d8; background: white; }}
  </style>
</head>
<body>
  <h1>抽帧拼图报告</h1>
  <table>{metadata}</table>
  {image_html}
</body>
</html>
""",
        encoding="utf-8",
    )


def _nearest_click_marker(markers: list[ClickMarker], seconds: float, window_seconds: float) -> ClickMarker | None:
    if not markers:
        return None
    best_marker: ClickMarker | None = None
    best_delta = max(0.0, float(window_seconds))
    for marker in markers:
        delta = abs(marker.seconds - seconds)
        if delta <= best_delta:
            best_marker = marker
            best_delta = delta
        elif marker.seconds > seconds + best_delta:
            break
    return best_marker


def _normalized_output_format(value: str) -> str:
    return "png" if str(value).strip().lower() == "png" else "jpg"


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _jsonable(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf", "msyh.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()
