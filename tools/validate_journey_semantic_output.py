#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.package import (
    build_semantic_review_template,
    validate_semantic_output,
    write_json_atomic,
)
from screen_mouse_recorder.journey_analysis.rules import load_rule_file


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON顶层必须是对象: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="校验游戏历程AI语义输出")
    parser.add_argument("semantic_input", type=Path)
    parser.add_argument("ai_output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review-template", type=Path, help="校验通过后生成语义人工复核模板")
    args = parser.parse_args()
    try:
        taxonomy = load_rule_file(ROOT / "rules" / "gameplay_taxonomy_v0.1.json")
        emotion = load_rule_file(ROOT / "rules" / "emotion_rules_v0.1.json")
        errors = validate_semantic_output(
            read_json(args.ai_output), read_json(args.semantic_input), taxonomy, emotion
        )
        report = {
            "schema_version": "1.0",
            "status": "valid" if not errors else "invalid",
            "error_count": len(errors),
            "errors": errors,
        }
        write_json_atomic(args.report, report)
        if not errors and args.review_template:
            template = build_semantic_review_template(
                read_json(args.ai_output),
                read_json(args.semantic_input),
                taxonomy,
                emotion,
            )
            write_json_atomic(args.review_template, template)
            report["review_template"] = args.review_template.name
            write_json_atomic(args.report, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if not errors else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"JOURNEY-SEMANTIC-VALIDATE-001: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
