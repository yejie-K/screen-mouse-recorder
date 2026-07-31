#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.charts import render_emotion_timeline_draft, render_open_timeline
from screen_mouse_recorder.journey_analysis.handoff import (
    build_open_timeline_agent_spec,
    render_open_timeline_agent_report,
    write_text_atomic,
)
from screen_mouse_recorder.journey_analysis.package import JourneyPackageError, build_semantic_input, write_json_atomic
from screen_mouse_recorder.journey_analysis.rules import JourneyRuleError, load_rule_file


def load_source(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JourneyPackageError(f"无法读取确认结果 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise JourneyPackageError("确认结果顶层必须是对象")
    return payload


def run(
    source: Path,
    output_dir: Path,
    session_id: str,
    *,
    game_name: str,
    total_play_time_ms: int | None = None,
    overwrite: bool = False,
) -> dict:
    if not source.is_file():
        raise JourneyPackageError(f"确认结果不存在: {source}")
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise JourneyPackageError(f"输出目录必须为空: {output_dir}")
    taxonomy_path = ROOT / "rules" / "gameplay_taxonomy_v0.1.json"
    emotion_path = ROOT / "rules" / "emotion_rules_v0.1.json"
    taxonomy = load_rule_file(taxonomy_path)
    emotion_rules = load_rule_file(emotion_path)
    semantic_input = build_semantic_input(
        source,
        load_source(source),
        taxonomy,
        emotion_rules,
        session_id=session_id,
        total_play_time_ms=total_play_time_ms,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    ai_dir = output_dir / "ai_package"
    chart_dir = output_dir / "charts"
    ai_dir.mkdir(parents=True, exist_ok=True)
    chart_dir.mkdir(parents=True, exist_ok=True)
    request_path = ai_dir / "journey_semantic_input.json"
    write_json_atomic(request_path, semantic_input)
    for path in [
        taxonomy_path,
        emotion_path,
        ROOT / "schemas" / "journey_semantic_input.schema.json",
        ROOT / "schemas" / "journey_semantic_output.schema.json",
        ROOT / "schemas" / "journey_semantic_review.schema.json",
        ROOT / "schemas" / "confirmed_semantic_events.schema.json",
        ROOT / "schemas" / "game_semantic_profile.schema.json",
        ROOT / "prompts" / "journey_semantic_enrichment_v0.1.md",
    ]:
        shutil.copy2(path, ai_dir / path.name)
    chart_path = chart_dir / "chart_gameplay_open_timeline_draft.png"
    chart_report = render_open_timeline(semantic_input, chart_path, game_name=game_name)
    write_json_atomic(chart_dir / "chart_gameplay_open_timeline_report.json", chart_report)
    agent_spec = build_open_timeline_agent_spec(
        semantic_input,
        chart_report,
        taxonomy,
        game_name=game_name,
    )
    write_json_atomic(chart_dir / "chart_gameplay_open_timeline_agent_spec.json", agent_spec)
    write_text_atomic(
        chart_dir / "chart_gameplay_open_timeline_agent_report.md",
        render_open_timeline_agent_report(agent_spec),
    )
    shutil.copy2(
        ROOT / "docs" / "gameplay_open_timeline_contract.md",
        chart_dir / "chart_gameplay_open_timeline_contract.md",
    )
    emotion_chart_path = chart_dir / "chart_event_emotion_timeline_draft.png"
    emotion_chart_report = render_emotion_timeline_draft(semantic_input, emotion_rules, emotion_chart_path)
    write_json_atomic(chart_dir / "chart_event_emotion_timeline_report.json", emotion_chart_report)
    review_count = sum(1 for node in chart_report["nodes"] if node["review_status"] == "needs_review")
    manifest = {
        "schema_version": "1.0",
        "status": "success",
        "session_id": session_id,
        "game_name": game_name,
        "source_fingerprint": semantic_input["source_fingerprint"],
        "confirmed_event_count": semantic_input["session"]["event_count"],
        "open_event_count": chart_report["event_count"],
        "open_event_review_count": review_count,
        "emotion_candidate_count": emotion_chart_report["event_count"],
        "outputs": {
            "ai_input": "ai_package/journey_semantic_input.json",
            "ai_prompt": "ai_package/journey_semantic_enrichment_v0.1.md",
            "ai_output_schema": "ai_package/journey_semantic_output.schema.json",
            "semantic_review_schema": "ai_package/journey_semantic_review.schema.json",
            "confirmed_semantic_schema": "ai_package/confirmed_semantic_events.schema.json",
            "game_semantic_profile_schema": "ai_package/game_semantic_profile.schema.json",
            "open_timeline": "charts/chart_gameplay_open_timeline_draft.png",
            "open_timeline_pages": [
                f"charts/{filename}"
                for filename in chart_report.get("outputs", [chart_report["output"]])
            ],
            "open_timeline_report": "charts/chart_gameplay_open_timeline_report.json",
            "open_timeline_agent_spec": "charts/chart_gameplay_open_timeline_agent_spec.json",
            "open_timeline_agent_report": "charts/chart_gameplay_open_timeline_agent_report.md",
            "open_timeline_contract": "charts/chart_gameplay_open_timeline_contract.md",
            "emotion_timeline": "charts/chart_event_emotion_timeline_draft.png",
            "emotion_timeline_report": "charts/chart_event_emotion_timeline_report.json",
        },
        "next_gate": "调用大模型生成语义候选，再人工复核玩法分类与情绪规则匹配",
    }
    write_json_atomic(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="准备游戏历程AI语义包和玩法开放时间图测试版")
    parser.add_argument("confirmed_events", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--game-name", default="当前游戏")
    parser.add_argument("--total-play-minutes", type=float, help="累计有效游玩分钟数；默认读取输入或最后事件时间")
    parser.add_argument("--overwrite", action="store_true", help="覆盖本工具生成的同名产物")
    args = parser.parse_args()
    try:
        result = run(
            args.confirmed_events,
            args.output_dir,
            args.session_id,
            game_name=args.game_name,
            total_play_time_ms=(
                max(0, int(round(args.total_play_minutes * 60_000)))
                if args.total_play_minutes is not None
                else None
            ),
            overwrite=args.overwrite,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (JourneyPackageError, JourneyRuleError, ValueError, OSError) as exc:
        print(f"JOURNEY-ANALYSIS-001: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
