from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from typing import Any, Callable

from PIL import Image

from ..media_utils import extract_frame, resolve_ffmpeg
from .ocr_events import OCREngine, OCRTextItem, RapidOCREngine
from .region_profile import read_region_profile


ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True)
class RegionScanConfig:
    index_json: Path
    region_profile: Path
    output_dir: Path
    video_path: Path | None = None
    ffmpeg_path: str | None = None
    session_id: str = ""
    max_frames: int | None = None
    save_crops: bool = False
    event_merge_gap_seconds: float = 5.0
    metric_merge_gap_seconds: float = 30.0


@dataclass(slots=True)
class RegionScanResult:
    output_dir: Path
    event_json: Path
    metric_json: Path
    manifest_json: Path
    frames_total: int
    frames_scanned: int
    region_scans: int
    event_count: int
    metric_count: int
    elapsed_seconds: float


def scan_all_extracted_frames(
    config: RegionScanConfig,
    *,
    engine: OCREngine | None = None,
    progress: ProgressCallback | None = None,
) -> RegionScanResult:
    started = time.perf_counter()
    index_path = config.index_json.resolve()
    profile_path = config.region_profile.resolve()
    index_payload = _read_json(index_path)
    profile = read_region_profile(profile_path, require_complete=True)
    frames = index_payload.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("抽帧索引缺少frames数组")
    all_frames = [dict(frame) for frame in frames if isinstance(frame, dict)]
    if not all_frames:
        raise ValueError("抽帧索引没有可扫描帧")
    frames_to_scan = all_frames
    if config.max_frames is not None:
        limit = max(1, int(config.max_frames))
        frames_to_scan = all_frames[:limit]

    regions = [
        dict(region)
        for region in profile["regions"]
        if bool(region.get("enabled", True)) and region.get("status") == "confirmed"
    ]
    if not regions:
        raise ValueError("区域profile没有已启用且已确认的区域")
    ocr_engine = engine or RapidOCREngine()
    output_dir = config.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    crop_root = output_dir / "region_crops"
    if config.save_crops:
        crop_root.mkdir(parents=True, exist_ok=True)

    video_path = config.video_path.resolve() if config.video_path else None
    if video_path is not None and not video_path.is_file():
        raise FileNotFoundError(video_path)
    needs_video = any(not _source_frame(frame, index_path.parent) for frame in frames_to_scan)
    if video_path is None and needs_video:
        raise ValueError("索引并非每帧都有source_frame，必须提供原始视频用于重新提取")
    video_reader = _VideoFrameReader(video_path, config.ffmpeg_path) if video_path is not None and needs_video else None

    session_id = str(
        config.session_id
        or index_payload.get("session_id")
        or (video_path.parent.name if video_path else index_path.parent.name)
    )
    metric_raw: list[dict[str, Any]] = []
    event_raw: list[dict[str, Any]] = []
    region_scans = 0
    ocr_calls = 0
    empty_scans = 0
    ocr_seconds = 0.0
    total = len(frames_to_scan)

    try:
        with TemporaryDirectory(prefix="region_scan_", dir=output_dir) as temporary:
            temporary_root = Path(temporary)
            for position, frame in enumerate(frames_to_scan, start=1):
                frame_index = _positive_frame_index(frame, position)
                seconds = _frame_seconds(frame)
                timestamp = str(frame.get("timestamp") or _format_seconds(seconds))
                if progress:
                    progress(position - 1, total, f"区域OCR {timestamp} ({position}/{total})")
                image, source_name = _load_frame(frame, index_path.parent, video_reader, seconds)
                try:
                    _check_frame_shape(image, profile["source_frame"])
                    prepared: list[dict[str, Any]] = []
                    for region in regions:
                        crop, box = _crop_region(image, region["rect_normalized"])
                        crop_dir = crop_root / f"frame_{frame_index:06d}" if config.save_crops else temporary_root
                        crop_dir.mkdir(parents=True, exist_ok=True)
                        crop_path = crop_dir / f"{_safe_name(region['region_id'])}.png"
                        crop.save(crop_path, "PNG")
                        crop.close()
                        relative_crop = (
                            str(crop_path.relative_to(output_dir)).replace("\\", "/")
                            if config.save_crops
                            else ""
                        )
                        prepared.append({
                            "region": region,
                            "box": box,
                            "crop_path": crop_path,
                            "crop_image": relative_crop,
                        })
                    recognized, frame_ocr_seconds, frame_ocr_calls = _recognize_region_crops(
                        ocr_engine,
                        prepared,
                        temporary_root / f"frame_{frame_index:06d}_regions.png",
                    )
                    region_scans += len(prepared)
                    ocr_calls += frame_ocr_calls
                    ocr_seconds += frame_ocr_seconds
                    frame_results: list[dict[str, Any]] = []
                    for prepared_region, (items, elapsed) in zip(prepared, recognized):
                        region = prepared_region["region"]
                        raw_text = " ".join(item.text.strip() for item in items if item.text.strip()).strip()
                        if not raw_text:
                            empty_scans += 1
                        relative_crop = prepared_region["crop_image"]
                        result = {
                            "region": region,
                            "raw_text": raw_text,
                            "confidence": _confidence(items),
                            "ocr_elapsed_seconds": round(float(elapsed), 4),
                            "box_px": list(prepared_region["box"]),
                            "crop_image": relative_crop,
                        }
                        frame_results.append(result)
                        if region["region_kind"] == "metric" and raw_text:
                            parsed_value, parsed_fields, unit = parse_metric_text(
                                raw_text,
                                parser=str(region["parser"]),
                                metric_key=str(region["metric_key"]),
                            )
                            if parsed_value is not None:
                                metric_raw.append({
                                    "observation_id": f"metric_{_safe_name(region['region_id'])}_{frame_index:06d}",
                                    "session_id": session_id,
                                    "time_ms": int(round(seconds * 1000)),
                                    "timestamp": timestamp,
                                    "source": "automatic",
                                    "evidence": _evidence(
                                        index_path,
                                        source_name,
                                        frame_index,
                                        [str(region["region_id"])],
                                        [relative_crop] if relative_crop else [],
                                    ),
                                    "metric_key": str(region["metric_key"]),
                                    "raw_text": raw_text,
                                    "ocr_text": raw_text,
                                    "confidence": result["confidence"],
                                    "ocr_elapsed_seconds": result["ocr_elapsed_seconds"],
                                    "parsed_value": parsed_value,
                                    "parsed_fields": parsed_fields,
                                    "unit": unit,
                                    "region_id": str(region["region_id"]),
                                    "last_time_ms": int(round(seconds * 1000)),
                                    "occurrence_frame_count": 1,
                                    "review": _pending_review(),
                                })
                    event_raw.extend(
                        _events_for_frame(
                            frame_results,
                            index_path=index_path,
                            source_name=source_name,
                            session_id=session_id,
                            frame_index=frame_index,
                            seconds=seconds,
                            timestamp=timestamp,
                        )
                    )
                finally:
                    image.close()
    finally:
        if video_reader is not None:
            video_reader.close()
    if progress:
        progress(total, total, "区域OCR完成")

    metrics = _collapse_metrics(metric_raw, max(0.0, config.metric_merge_gap_seconds))
    events = _collapse_events(event_raw, max(0.0, config.event_merge_gap_seconds))
    scan_scope = "all_extracted_frames" if len(frames_to_scan) == len(all_frames) else "debug_subset"
    fingerprint = hashlib.sha256(index_path.read_bytes() + profile_path.read_bytes()).hexdigest()
    session = {
        "session_id": session_id,
        "frame_index": index_path.name,
        "video": video_path.name if video_path else "",
    }
    event_payload = _result_payload(
        task_id="JOURNEY_EVENT_OBSERVATIONS_V2",
        key="events",
        values=events,
        fingerprint=fingerprint,
        scan_scope=scan_scope,
        session=session,
        extra_summary={"raw_match_count": len(event_raw)},
    )
    metric_payload = _result_payload(
        task_id="JOURNEY_METRIC_OBSERVATIONS_V2",
        key="metrics",
        values=metrics,
        fingerprint=fingerprint,
        scan_scope=scan_scope,
        session=session,
        extra_summary={"raw_match_count": len(metric_raw)},
    )
    event_path = output_dir / "event_observations_v2.json"
    metric_path = output_dir / "metric_observations_v2.json"
    manifest_path = output_dir / "region_scan_manifest.json"
    _write_json(event_path, event_payload)
    _write_json(metric_path, metric_payload)
    elapsed_seconds = round(time.perf_counter() - started, 4)
    _write_json(manifest_path, {
        "schema_version": "1.0",
        "workflow": "all_extracted_frames_region_ocr",
        "scan_scope": scan_scope,
        "source": {
            "index_json": index_path.name,
            "region_profile": profile_path.name,
            "video": video_path.name if video_path else "",
            "ocr_engine": ocr_engine.name,
            "ocr_engine_version": ocr_engine.version,
            "video_reader": video_reader.name if video_reader is not None else "source_frame",
        },
        "counts": {
            "frames_total": len(all_frames),
            "frames_scanned": len(frames_to_scan),
            "regions_per_frame": len(regions),
            "region_scans": region_scans,
            "ocr_calls": ocr_calls,
            "empty_region_scans": empty_scans,
            "raw_metric_matches": len(metric_raw),
            "metric_observations": len(metrics),
            "raw_event_matches": len(event_raw),
            "event_observations": len(events),
        },
        "timing": {
            "ocr_elapsed_seconds": round(ocr_seconds, 4),
            "total_elapsed_seconds": elapsed_seconds,
        },
        "outputs": [event_path.name, metric_path.name],
    })
    return RegionScanResult(
        output_dir=output_dir,
        event_json=event_path,
        metric_json=metric_path,
        manifest_json=manifest_path,
        frames_total=len(all_frames),
        frames_scanned=len(frames_to_scan),
        region_scans=region_scans,
        event_count=len(events),
        metric_count=len(metrics),
        elapsed_seconds=elapsed_seconds,
    )


def parse_metric_text(
    text: str,
    *,
    parser: str,
    metric_key: str = "",
) -> tuple[Any, dict[str, Any], str]:
    normalized = _normalize_ocr(text)
    if parser == "numeric_cn":
        if metric_key == "combat_power" and not _is_combat_power_text(normalized):
            return None, {}, ""
        match = re.search(r"(\d+(?:\.\d+)?)\s*([万亿]?)", normalized)
        if not match:
            return None, {}, ""
        value = float(match.group(1))
        unit = match.group(2)
        multiplier = {"": 1, "万": 10_000, "亿": 100_000_000}[unit]
        parsed = value * multiplier
        rounded = round(parsed)
        parsed_value = int(rounded) if abs(parsed - rounded) < 1e-6 else parsed
        return parsed_value, {"display_unit": unit}, ""
    if parser == "integer":
        match = re.search(r"(\d+)", normalized)
        return (int(match.group(1)), {}, "") if match else (None, {}, "")
    if parser == "level_rebirth":
        level_match = re.search(r"(\d+)\s*级", normalized)
        rebirth_match = re.search(r"(\d+)\s*转", normalized)
        fields: dict[str, Any] = {}
        if level_match:
            fields["level"] = int(level_match.group(1))
        if rebirth_match:
            fields["rebirth"] = int(rebirth_match.group(1))
        elif "未转生" in normalized:
            fields["rebirth"] = 0
        if not fields:
            return None, {}, ""
        display = "".join(
            part
            for part in (
                f"{fields['rebirth']}转" if "rebirth" in fields else "",
                f"{fields['level']}级" if "level" in fields else "",
            )
        )
        return display, fields, ""
    cleaned = " ".join(text.split()).strip()
    return (cleaned, {}, "") if cleaned else (None, {}, "")


def _is_combat_power_text(normalized: str) -> bool:
    if "/" in normalized or "／" in normalized:
        return False
    return any(label in normalized for label in ("战力", "戰力", "诚力", "誠力"))


def _events_for_frame(
    results: list[dict[str, Any]],
    *,
    index_path: Path,
    source_name: str,
    session_id: str,
    frame_index: int,
    seconds: float,
    timestamp: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        region = result["region"]
        if region["region_kind"] == "event":
            groups[str(region["region_group_id"])].append(result)
    events = []
    for group_id, members in groups.items():
        triggers = [item for item in members if item["region"]["region_role"] == "trigger"]
        if not triggers or not any(_trigger_hit(item) for item in triggers):
            continue
        names = [
            item["raw_text"]
            for item in members
            if item["region"]["region_role"] == "name" and item["raw_text"]
        ]
        auxiliary = [
            item["raw_text"]
            for item in members
            if item["region"]["region_role"] == "auxiliary" and item["raw_text"]
        ]
        event_name = " ".join(names).strip() or " ".join(auxiliary).strip() or "待人工确认"
        template = members[0]["region"]
        region_ids = [str(item["region"]["region_id"]) for item in members]
        crop_images = [item["crop_image"] for item in members if item["crop_image"]]
        elapsed = sum(float(item["ocr_elapsed_seconds"]) for item in members)
        confidence = max((float(item["confidence"]) for item in members), default=0.0)
        events.append({
            "observation_id": f"event_{_safe_name(group_id)}_{frame_index:06d}",
            "session_id": session_id,
            "time_ms": int(round(seconds * 1000)),
            "timestamp": timestamp,
            "source": "automatic",
            "evidence": _evidence(index_path, source_name, frame_index, region_ids, crop_images),
            "event_name": event_name,
            "ocr_text": " | ".join(item["raw_text"] for item in members if item["raw_text"]),
            "confidence": round(confidence, 4),
            "ocr_elapsed_seconds": round(elapsed, 4),
            "mode_tag": str(template.get("mode_tag") or "待判断"),
            "event_tag": str(template.get("event_tag") or "其他开放"),
            "region_group_id": group_id,
            "last_time_ms": int(round(seconds * 1000)),
            "occurrence_frame_count": 1,
            "review": _pending_review(),
        })
    return events


def _trigger_hit(result: dict[str, Any]) -> bool:
    text = _normalize_match(result["raw_text"])
    keywords = result["region"].get("fixed_keywords") or []
    return bool(text) and any(_normalize_match(keyword) in text for keyword in keywords if _normalize_match(keyword))


def _collapse_metrics(values: list[dict[str, Any]], gap_seconds: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    last_by_region: dict[str, dict[str, Any]] = {}
    for item in sorted(values, key=lambda value: (value["region_id"], value["time_ms"])):
        previous = last_by_region.get(item["region_id"])
        if previous and previous["parsed_value"] == item["parsed_value"]:
            previous["last_time_ms"] = item["time_ms"]
            previous["occurrence_frame_count"] += 1
            if item["confidence"] > previous["confidence"]:
                previous["confidence"] = item["confidence"]
                previous["evidence"] = item["evidence"]
                previous["ocr_text"] = item["ocr_text"]
            continue
        result.append(item)
        last_by_region[item["region_id"]] = item
    result.sort(key=lambda value: (value["time_ms"], value["region_id"]))
    return result


def _collapse_events(values: list[dict[str, Any]], gap_seconds: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    last_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    gap_ms = int(round(gap_seconds * 1000))
    for item in sorted(values, key=lambda value: value["time_ms"]):
        key = (item["region_group_id"], _normalize_match(item["event_name"]))
        previous = last_by_key.get(key)
        if previous and item["time_ms"] - previous["last_time_ms"] <= gap_ms:
            previous["last_time_ms"] = item["time_ms"]
            previous["occurrence_frame_count"] += 1
            if item["confidence"] > previous["confidence"]:
                previous["confidence"] = item["confidence"]
                previous["evidence"] = item["evidence"]
                previous["ocr_text"] = item["ocr_text"]
            continue
        result.append(item)
        last_by_key[key] = item
    return result


def _result_payload(
    *,
    task_id: str,
    key: str,
    values: list[dict[str, Any]],
    fingerprint: str,
    scan_scope: str,
    session: dict[str, Any],
    extra_summary: dict[str, Any],
) -> dict[str, Any]:
    counts = Counter(item["review"]["status"] for item in values)
    return {
        "schema_version": "2.0",
        "task_id": task_id,
        "source_fingerprint": fingerprint,
        "status": "needs_review" if values else "complete",
        "scan_scope": scan_scope,
        "session": session,
        "summary": {
            "observation_count": len(values),
            "pending": counts["pending"],
            "confirmed": counts["confirmed"],
            "excluded": counts["excluded"],
            **extra_summary,
        },
        key: values,
        "compatibility": {},
    }


def _load_frame(
    frame: dict[str, Any],
    index_dir: Path,
    video_reader: _VideoFrameReader | None,
    seconds: float,
) -> tuple[Image.Image, str]:
    source = _source_frame(frame, index_dir)
    if source is not None:
        with Image.open(source) as image:
            return image.convert("RGB"), source.name
    if video_reader is None:
        raise ValueError("无法读取原始帧，且未提供可用视频")
    return video_reader.read(seconds), video_reader.video_path.name


class _VideoFrameReader:
    def __init__(self, video_path: Path, ffmpeg_path: str | None) -> None:
        self.video_path = video_path
        self._capture = None
        self._cv2 = None
        self._fps = 0.0
        self._current_index = -1
        self._ffmpeg = None
        try:
            import cv2

            capture = cv2.VideoCapture(str(video_path))
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            if not capture.isOpened() or fps <= 0:
                capture.release()
                raise RuntimeError("OpenCV无法打开视频")
            self._capture = capture
            self._cv2 = cv2
            self._fps = fps
            self.name = "opencv-sequential"
        except (ImportError, RuntimeError):
            self._ffmpeg = resolve_ffmpeg(ffmpeg_path)
            self.name = "ffmpeg-per-frame"

    def read(self, seconds: float) -> Image.Image:
        if self._capture is None or self._cv2 is None:
            return extract_frame(self._ffmpeg, self.video_path, seconds)
        target = max(0, int(round(seconds * self._fps)))
        if target < self._current_index:
            self._capture.set(self._cv2.CAP_PROP_POS_FRAMES, target)
            self._current_index = target - 1
        while self._current_index < target:
            if not self._capture.grab():
                raise RuntimeError(f"视频读取失败: {seconds:.3f}s")
            self._current_index += 1
        ok, frame = self._capture.retrieve()
        if not ok or frame is None:
            raise RuntimeError(f"视频解码失败: {seconds:.3f}s")
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()


def _source_frame(frame: dict[str, Any], index_dir: Path) -> Path | None:
    value = str(frame.get("source_frame") or "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = index_dir / path
    return path.resolve() if path.is_file() else None


def _crop_region(image: Image.Image, rect: list[Any]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    left, top, right, bottom = map(float, rect)
    box = (
        max(0, min(image.width - 1, int(round(left * image.width)))),
        max(0, min(image.height - 1, int(round(top * image.height)))),
        max(1, min(image.width, int(round(right * image.width)))),
        max(1, min(image.height, int(round(bottom * image.height)))),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f"区域换算后无效: {rect}")
    return image.crop(box), box


def _recognize_region_crops(
    engine: OCREngine,
    prepared: list[dict[str, Any]],
    batch_path: Path,
) -> tuple[list[tuple[list[OCRTextItem], float]], float, int]:
    if len(prepared) <= 1 or engine.name != "rapidocr-onnxruntime":
        results = []
        elapsed_total = 0.0
        for item in prepared:
            recognized, elapsed = engine.recognize(item["crop_path"])
            elapsed_total += float(elapsed)
            results.append((recognized, float(elapsed)))
        return results, elapsed_total, len(prepared)

    scale = 2
    gap = 16
    sizes = []
    for item in prepared:
        with Image.open(item["crop_path"]) as crop:
            sizes.append((crop.width * scale, crop.height * scale))
    canvas = Image.new(
        "RGB",
        (max(width for width, _height in sizes), sum(height for _width, height in sizes) + gap * (len(sizes) - 1)),
        (16, 20, 24),
    )
    placements = []
    top = 0
    try:
        for item, (width, height) in zip(prepared, sizes):
            with Image.open(item["crop_path"]) as crop:
                resized = crop.convert("RGB").resize((width, height), Image.Resampling.BICUBIC)
                canvas.paste(resized, (0, top))
                resized.close()
            placements.append((0, top, width, top + height))
            top += height + gap
        canvas.save(batch_path, "PNG")
    finally:
        canvas.close()
    items, elapsed = engine.recognize(batch_path)
    grouped: list[list[OCRTextItem]] = [[] for _item in prepared]
    for item in items:
        if item.box is None:
            continue
        center_x = (item.box[0] + item.box[2]) / 2
        center_y = (item.box[1] + item.box[3]) / 2
        for index, (left, top, right, bottom) in enumerate(placements):
            if left <= center_x <= right and top <= center_y <= bottom:
                grouped[index].append(item)
                break
    allocated = float(elapsed) / max(1, len(prepared))
    return [(group, allocated) for group in grouped], float(elapsed), 1


def _check_frame_shape(image: Image.Image, expected: dict[str, Any]) -> None:
    expected_ratio = float(expected["width"]) / float(expected["height"])
    actual_ratio = image.width / image.height
    if abs(actual_ratio - expected_ratio) / expected_ratio > 0.02:
        raise ValueError(
            f"原始帧宽高比{image.width}x{image.height}与区域profile的"
            f"{expected['width']}x{expected['height']}不一致"
        )


def _evidence(
    index_path: Path,
    source_name: str,
    frame_index: int,
    region_ids: list[str],
    crop_images: list[str],
) -> dict[str, Any]:
    return {
        "index_json": index_path.name,
        "source_image": source_name,
        "frame_index": frame_index,
        "region_ids": region_ids,
        "crop_images": crop_images,
    }


def _pending_review() -> dict[str, Any]:
    return {"status": "pending", "reviewer": "", "reviewed_at": "", "note": ""}


def _confidence(items: list[OCRTextItem]) -> float:
    values = [float(item.confidence) for item in items if item.text.strip()]
    return round(sum(values) / len(values), 4) if values else 0.0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON顶层必须是对象: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _positive_frame_index(frame: dict[str, Any], fallback: int) -> int:
    try:
        value = int(frame.get("index") or fallback)
    except (TypeError, ValueError):
        value = fallback
    return max(1, value)


def _frame_seconds(frame: dict[str, Any]) -> float:
    try:
        value = float(frame.get("seconds") or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("抽帧索引包含无效seconds") from exc
    return max(0.0, value)


def _normalize_ocr(text: str) -> str:
    return (
        text.replace(",", "")
        .replace("，", "")
        .replace("成力", "战力")
        .replace("诚力", "战力")
        .replace("戰力", "战力")
        .replace("O", "0")
        .replace("o", "0")
    )


def _normalize_match(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def _safe_name(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._-")
    return text or "region"


def _format_seconds(seconds: float) -> str:
    milliseconds = int(round(max(0.0, seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
