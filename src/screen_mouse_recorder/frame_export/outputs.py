from __future__ import annotations

from dataclasses import asdict
import csv
from html import escape
import json
from pathlib import Path

from .models import FramePlanEntry, FrameSamplerConfig, FrameSamplerEstimate, VideoInfo
from .timecode import format_timecode


def _cleanup_click_keyframe_outputs(output_dir: Path, basename: str) -> None:
    for path in output_dir.glob(f"{basename}*.png"):
        try:
            path.unlink()
        except OSError:
            pass

def _write_click_keyframe_index_json(
    path: Path,
    plan: list[FramePlanEntry],
    sheet_paths: list[Path],
    events_total: int,
    events_skipped: int,
    warnings: list[str],
    selection_stats: dict[str, Any] | None = None,
) -> None:
    sheet_by_index = {index + 1: sheet_path.name for index, sheet_path in enumerate(sheet_paths)}
    payload = {
        "events_total": events_total,
        "events_kept": len(plan),
        "events_skipped": events_skipped,
        "warnings": warnings,
        "selection": selection_stats or {},
        "frames": [
            {
                "index": entry.index,
                "event_id": entry.event_id,
                "event_type": entry.event_type,
                "source_index": entry.source_index,
                "seconds": entry.seconds,
                "timestamp": entry.timestamp,
                "video_x": entry.click_x,
                "video_y": entry.click_y,
                "sheet": sheet_by_index.get(entry.sheet_index, ""),
                "sheet_row": entry.sheet_row,
                "sheet_col": entry.sheet_col,
                "selection_reason": entry.selection_reason,
                "cluster_index": entry.cluster_index,
                "cluster_size": entry.cluster_size,
                "visual_diff": entry.visual_diff,
            }
            for entry in plan
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

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

def _jsonable(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

