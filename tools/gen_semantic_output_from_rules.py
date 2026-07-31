#!/usr/bin/env python3
"""从规则初分派生 AI 语义候选草稿 (journey_semantic_output.json)。

用途：跑通语义复核闭环时，作为“AI 语义补全模块”的确定性替身。
它只把输入事件里**已由规则命中的初分**（deterministic_hints）整理成符合
journey_semantic_output.schema.json 的候选，全部标 needs_review，
不脑补产出关系、不自填情绪分值。真正的语义细化与情绪仍由人工复核决定。

边界（与 prompts/journey_semantic_enrichment_v0.1.md 一致）：
- 原样回填 task_id / source_fingerprint / event_id。
- 分类只取输入规则初分中的白名单值，不新增。
- output_relations 一律为空（无直接证据不脑补）。
- emotion_score_candidate 一律为 null，最终分数由 finalize 脚本按规则计算。
- review_status 只能是 needs_review / excluded。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.rules import load_rule_file
from screen_mouse_recorder.journey_analysis.semantic_draft import build_semantic_draft


def build_output(semantic_input: dict, taxonomy: dict, emotion_rules: dict) -> dict:
    return build_semantic_draft(semantic_input, taxonomy, emotion_rules)


def main() -> int:
    parser = argparse.ArgumentParser(description="从规则初分派生AI语义候选草稿")
    parser.add_argument("semantic_input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    semantic_input = json.loads(args.semantic_input.read_text(encoding="utf-8"))
    taxonomy = load_rule_file(ROOT / "rules" / "gameplay_taxonomy_v0.1.json")
    emotion = load_rule_file(ROOT / "rules" / "emotion_rules_v0.1.json")
    output = build_output(semantic_input, taxonomy, emotion)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "output": str(args.output),
        "annotations": len(output["event_annotations"]),
        "review_items": len(output["review_items"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
