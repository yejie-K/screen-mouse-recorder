#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.package import (
    JourneyPackageError,
    finalize_semantic_review,
    write_json_atomic,
)
from screen_mouse_recorder.journey_analysis.rules import JourneyRuleError, load_rule_file


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise JourneyPackageError(f"JSON顶层必须是对象: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="合并AI语义候选和人工复核，生成统一确认事件文件")
    parser.add_argument("semantic_input", type=Path)
    parser.add_argument("ai_output", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        taxonomy = load_rule_file(ROOT / "rules" / "gameplay_taxonomy_v0.1.json")
        emotion = load_rule_file(ROOT / "rules" / "emotion_rules_v0.1.json")
        result = finalize_semantic_review(
            read_json(args.semantic_input),
            read_json(args.ai_output),
            read_json(args.review),
            taxonomy,
            emotion,
        )
        write_json_atomic(args.output, result)
        message = {
            "status": result["status"],
            "output": str(args.output),
            **result["summary"],
        }
        print(json.dumps(message, ensure_ascii=False))
        return 0 if result["status"] == "complete" else 1
    except (JourneyPackageError, JourneyRuleError, OSError, json.JSONDecodeError) as exc:
        print(f"JOURNEY-SEMANTIC-FINALIZE-001: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
