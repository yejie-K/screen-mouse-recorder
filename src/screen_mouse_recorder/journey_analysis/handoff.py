from __future__ import annotations

from pathlib import Path
from typing import Any

from .charts import BLOCK_FILL_COLORS, INTERACTION_BORDER_COLORS


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.part")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def build_open_timeline_agent_spec(
    semantic_input: dict[str, Any],
    chart_report: dict[str, Any],
    taxonomy: dict[str, Any],
    *,
    game_name: str,
    candidate_mode: bool = True,
    source_files: dict[str, str] | None = None,
    generator_command: str = "",
) -> dict[str, Any]:
    source_events = {event["event_id"]: event for event in semantic_input["events"]}
    drawing_events = []
    for node in chart_report["nodes"]:
        source = source_events[node["event_id"]]
        global_time_ms = int(source.get("global_time_ms", source.get("time_ms", 0)))
        play_day_index = int(source.get("play_day_index", global_time_ms // 3_600_000 + 1))
        day_time_ms = int(source.get("day_time_ms", global_time_ms % 3_600_000))
        drawing_events.append({
            "event_id": node["event_id"],
            "event_name": node["event_name"],
            "event_type": source["event_type"],
            "global_time_ms": global_time_ms,
            "play_day_index": play_day_index,
            "day_time_ms": day_time_ms,
            "opening_condition_candidate": node["opening_condition_candidate"],
            "source_classification": source["deterministic_hints"]["classification"],
            "matched_gameplay_rule_ids": source["deterministic_hints"]["matched_gameplay_rule_ids"],
            "visual_encoding": {
                "block_type": node["block_type_candidate"],
                "interaction_mode": node["interaction_mode_candidate"],
                "fill_color": node["fill_color"],
                "border_color": node["border_color"],
                "matrix_row": node.get("matrix_row"),
                "matrix_column": node.get("matrix_column"),
            },
            "evidence": source.get("evidence") or {},
            "review_status": node["review_status"],
        })
    source_file_map = source_files or {
        "semantic_input": "journey_semantic_input.json",
        "gameplay_taxonomy": "gameplay_taxonomy_v0.1.json",
        "semantic_prompt": "journey_semantic_enrichment_v0.1.md",
        "semantic_output_schema": "journey_semantic_output.schema.json",
        "chart_contract": "玩法系统开放节奏.contract.md",
        "render_report": "玩法系统开放节奏.report.json",
        "rendered_image": chart_report["output"],
    }
    return {
        "schema_version": "1.0",
        "artifact_id": "gameplay_open_timeline_agent_spec",
        "status": "draft" if candidate_mode else "complete",
        "purpose": "说明玩法/系统开放节奏图画了什么、为什么这样分类，以及如何复现和二次修改。",
        "game": {
            "game_name": game_name,
            "session_id": semantic_input["session"]["session_id"],
            "source_fingerprint": semantic_input["source_fingerprint"],
        },
        "source_files": source_file_map,
        "selection_rules": {
            "included_event_types": ["new_feature_unlocked"],
            "excluded": (
                ["重复开放", "只有预告但未实际开放", "无证据节点"]
                if candidate_mode
                else ["重复开放", "只有预告但未实际开放", "无证据节点", "未确认事件"]
            ),
            "selected_event_count": len(drawing_events),
        },
        "time_model": {
            "basis": "累计有效游玩时间，不使用自然日期",
            "virtual_day_minutes": 60,
            "total_play_time_ms": semantic_input["session"]["total_play_time_ms"],
            "virtual_day_count": semantic_input["session"]["virtual_day_count"],
            "play_day_formula": "floor(global_time_ms / 3600000) + 1",
            "day_time_formula": "global_time_ms % 3600000",
        },
        "classification_model": {
            "source_dimensions": taxonomy["dimensions"],
            "visual_fill": {
                "meaning": "块类型",
                "source_field": "deterministic_hints.classification.gameplay_form",
                "fallback_field": "deterministic_hints.classification.object_scope",
                "colors": dict(BLOCK_FILL_COLORS),
            },
            "visual_border": {
                "meaning": "交互/对抗模式",
                "source_field": "deterministic_hints.classification.interaction_mode",
                "colors": dict(INTERACTION_BORDER_COLORS),
            },
            "non_visual_dimensions": [
                "event_category",
                "object_scope",
                "rhythm_category",
                "完整 gameplay_form 与 interaction_mode 多标签",
            ],
        },
        "layout": {
            "layout_mode": chart_report["layout_mode"],
            "timeline_count": 1,
            "cycle_summary_side": chart_report.get("cycle_summary_side", "above"),
            "event_block_side": chart_report.get("event_block_side", "below"),
            "matrix_order": "每个游玩日内按事件时间先从上到下填满一列，再进入右侧下一列",
            "connector_mode": chart_report.get("connector_mode", "legacy"),
            "pagination": False,
        },
        "drawing_inputs": {
            "cycle_summary_candidates": chart_report.get("cycle_summary_candidates", chart_report.get("phase_candidates", [])),
            "events": drawing_events,
        },
        "editable_fields": {
            "safe_to_edit_then_regenerate": [
                "cycle summary label/start_ms/end_ms",
                "block_type visual mapping",
                "interaction_mode visual mapping",
                "fill and border color maps",
                "matrix and connector layout parameters",
            ],
            "must_not_change_without_source_review": [
                "event_id",
                "event_name",
                "global_time_ms",
                "opening condition",
                "evidence references",
            ],
        },
        "generator": {
            "entrypoint": "tools/generate_journey_preview.py" if candidate_mode else "tools/generate_journey_final.py",
            "render_function": "screen_mouse_recorder.journey_analysis.charts.render_open_timeline",
            "command_template": generator_command or (
                "python tools/generate_journey_preview.py <workspace_dir>"
                if candidate_mode
                else "python tools/generate_journey_final.py <workspace_dir>"
            ),
        },
        "review_notes": [
            "当前分类和循环总结仍是候选，正式使用前需人工复核。",
            "OCR只能作为校验或候补证据，事件时间以结构化字段为准。",
            "本图的填充色和外框色表达两个独立维度，不得合并解释。",
        ],
    }


def render_open_timeline_agent_report(spec: dict[str, Any]) -> str:
    game = spec["game"]
    time_model = spec["time_model"]
    lines = [
        f"# {game['game_name']} 玩法/系统开放节奏图交接报告",
        "",
        "## 这份图表达什么",
        "",
        spec["purpose"],
        "",
        f"- 会话：`{game['session_id']}`",
        f"- 累计有效游玩：`{time_model['total_play_time_ms'] / 60000:.1f}` 分钟",
        f"- 游玩日：`{time_model['virtual_day_count']}` 天，每 60 分钟计 1 天",
        f"- 图中事件：`{spec['selection_rules']['selected_event_count']}` 个"
        f"{'待复核候选节点' if spec['status'] == 'draft' else '人工确认首次开放节点'}",
        "",
        "## 视觉编码",
        "",
        "- 填充色表示块类型，来源于 `gameplay_form`，必要时用 `object_scope` 兜底。",
        "- 外框色表示交互/对抗模式，PVE 蓝、PVP 红、GVG 紫；非对抗模式使用辅助框色。",
        "- 时间轴上方是循环总结候选，下方是事件矩阵。",
        "- 每日内部按时间先竖向排列，再进入右侧下一列；只有每列首块连接时间轴。",
        "",
        "### 填充色",
        "",
        "| 块类型 | 色值 |",
        "|---|---|",
    ]
    for label, color in spec["classification_model"]["visual_fill"]["colors"].items():
        lines.append(f"| {label} | `{color}` |")
    lines.extend(["", "### 外框色", "", "| 交互模式 | 色值 |", "|---|---|"])
    for label, color in spec["classification_model"]["visual_border"]["colors"].items():
        lines.append(f"| {label} | `{color}` |")
    lines.extend([
        "",
        "## 当前游戏分类结果",
        "",
        "| 时间 | 事件 | 开放条件 | 填充类型 | 外框模式 | 原始玩法形态 | 原始交互模式 |",
        "|---|---|---|---|---|---|---|",
    ])
    for event in spec["drawing_inputs"]["events"]:
        classification = event["source_classification"]
        minutes = event["global_time_ms"] / 60000
        forms = "、".join(classification.get("gameplay_form") or [])
        modes = "、".join(classification.get("interaction_mode") or [])
        visual = event["visual_encoding"]
        lines.append(
            f"| {minutes:.2f}分 | {event['event_name']} | {event['opening_condition_candidate']} | "
            f"{visual['block_type']} | {visual['interaction_mode']} | {forms} | {modes} |"
        )
    lines.extend([
        "",
        "## 文件关系",
        "",
        "| 文件 | 用途 |",
        "|---|---|",
        f"| `{spec['source_files']['rendered_image']}` | 当前渲染图 |",
        f"| `{spec['source_files']['render_report']}` | 渲染结果、节点和布局位置 |",
        "| `玩法系统开放节奏.agent_spec.json` | 完整机器可读绘图规格与输入 |",
        f"| `{spec['source_files']['chart_contract']}` | 稳定输入输出与布局约束 |",
        f"| `{spec['source_files']['semantic_input']}` | 结构化语义输入 |",
        f"| `{spec['source_files']['gameplay_taxonomy']}` | 分类规则 |",
        "",
        "## 二次修改边界",
        "",
        "可以修改循环总结、可视化映射、颜色与布局参数后重新生成。事件名称、时间、开放条件和证据引用属于确认事实，修改前必须回到源事件复核。",
        "",
        "## 重新生成",
        "",
        "```text",
        spec["generator"]["command_template"],
        "```",
        "",
        "完整字段、循环总结和每个节点的证据引用请读取 `chart_gameplay_open_timeline_agent_spec.json`。",
        "",
    ])
    return "\n".join(lines)
