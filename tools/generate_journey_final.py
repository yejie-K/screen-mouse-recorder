#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.final_product import generate_final_product  # noqa: E402
from screen_mouse_recorder.journey_analysis.package import JourneyPackageError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="从统一工作空间生成人工确认后的XLSX和三张正式图")
    parser.add_argument("workspace_dir", type=Path)
    args = parser.parse_args()
    try:
        result = generate_final_product(
            args.workspace_dir,
            taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
            emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
        )
    except (JourneyPackageError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "code": "JOURNEY-FINAL-001", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
