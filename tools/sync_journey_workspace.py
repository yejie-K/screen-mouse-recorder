#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.package import JourneyPackageError  # noqa: E402
from screen_mouse_recorder.journey_analysis.workspace import sync_journey_workspace  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="同步新工作空间的人工事件、区域扫描和两类复核包")
    parser.add_argument("workspace_dir", type=Path)
    parser.add_argument("--reset-review", action="store_true", help="显式丢弃并重建已有复核文件")
    args = parser.parse_args()
    try:
        result = sync_journey_workspace(
            args.workspace_dir,
            taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
            emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
            reset_review=args.reset_review,
        )
    except (JourneyPackageError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "code": "JOURNEY-WORKSPACE-002", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
