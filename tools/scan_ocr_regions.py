#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.event_extraction import (  # noqa: E402
    RegionProfileError,
    RegionScanConfig,
    scan_all_extracted_frames,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="对抽帧索引中的全部原始帧执行局部区域OCR")
    parser.add_argument("index_json", type=Path)
    parser.add_argument("region_profile", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--limit", type=int, help="仅用于debug；正式扫描不要设置")
    parser.add_argument("--save-crops", action="store_true", default=True, help="保存局部证据图（正式扫描默认开启）")
    parser.add_argument("--no-save-crops", action="store_false", dest="save_crops", help="仅调试时关闭局部证据图")
    parser.add_argument("--json-progress", action="store_true")
    args = parser.parse_args()

    def progress(done: int, total: int, message: str) -> None:
        if args.json_progress:
            print(json.dumps({
                "type": "progress",
                "done": done,
                "total": total,
                "message": message,
            }, ensure_ascii=False), flush=True)

    try:
        result = scan_all_extracted_frames(
            RegionScanConfig(
                index_json=args.index_json,
                region_profile=args.region_profile,
                output_dir=args.output_dir,
                video_path=args.video,
                ffmpeg_path=args.ffmpeg,
                session_id=args.session_id,
                max_frames=args.limit,
                save_crops=args.save_crops,
            ),
            progress=progress,
        )
    except (RegionProfileError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(json.dumps({
            "type": "error",
            "code": "OCR-REGION-SCAN-001",
            "message": str(exc),
        }, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({
        "type": "complete",
        "frames_total": result.frames_total,
        "frames_scanned": result.frames_scanned,
        "region_scans": result.region_scans,
        "event_count": result.event_count,
        "metric_count": result.metric_count,
        "elapsed_seconds": result.elapsed_seconds,
        "output_dir": str(result.output_dir),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
