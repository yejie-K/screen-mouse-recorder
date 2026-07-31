#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.package import JourneyPackageError  # noqa: E402
from screen_mouse_recorder.journey_analysis.workspace import initialize_journey_workspace  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="从真实Session初始化唯一的新历程拆解工作空间")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("index_json", type=Path, help="该Session对应的点击抽帧索引JSON")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--game-name", required=True)
    parser.add_argument("--region-profile", type=Path, help="可选的当前1.1区域profile")
    parser.add_argument("--region-evidence-root", type=Path, help="profile中sample_evidence的根目录")
    args = parser.parse_args()
    try:
        result = initialize_journey_workspace(
            args.session_dir,
            args.index_json,
            args.output_dir,
            game_id=args.game_id,
            game_name=args.game_name,
            region_profile=args.region_profile,
            region_evidence_root=args.region_evidence_root,
        )
    except (JourneyPackageError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "code": "JOURNEY-WORKSPACE-001", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
