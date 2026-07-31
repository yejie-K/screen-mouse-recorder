#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.package import JourneyPackageError, write_json_atomic  # noqa: E402
from screen_mouse_recorder.journey_analysis.workspace import refresh_journey_workspace, validate_final_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="检查新历程拆解工作空间的链路状态")
    parser.add_argument("workspace_dir", type=Path)
    parser.add_argument("--final-gate", action="store_true", help="要求事件和指标均已完成复核")
    args = parser.parse_args()
    try:
        result = validate_final_gate(args.workspace_dir) if args.final_gate else refresh_journey_workspace(args.workspace_dir)
        write_json_atomic(args.workspace_dir.resolve() / "journey_workspace.json", result)
    except (JourneyPackageError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "code": "JOURNEY-WORKSPACE-003", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
