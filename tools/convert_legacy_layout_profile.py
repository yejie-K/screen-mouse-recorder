#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.event_extraction import convert_legacy_layout_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="将旧OCR布局候选转换为v1.1区域profile草稿")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--game-name", required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    result = convert_legacy_layout_profile(
        source,
        game_id=args.game_id,
        game_name=args.game_name,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f"{args.output.name}.part")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "status": result["status"],
        "region_count": len(result["regions"]),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
