from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFont


RHYTHM_COLORS = {
    "核心循环（爆点）": "#F2B94B",
    "PVE": "#3E78B8",
    "PVP": "#D45A65",
    "日常任务": "#2F9B78",
    "竞技": "#7E5AA6",
    "帮会": "#C8793D",
    "异步社交": "#607D8B",
    "同步社交": "#238B8E",
    "其他": "#8A8F98",
}

BLOCK_FILL_COLORS = {
    "成长养成": "#F6DFA7",
    "BOSS": "#DCE8F5",
    "副本": "#D8ECE5",
    "日常任务": "#E4EED7",
    "竞技排行": "#E8DDF0",
    "社交协作": "#D7EAEC",
    "活动": "#F3DFC9",
    "商业化": "#F0D8DF",
    "通用功能": "#E2E6EA",
    "其他": "#DDE1E6",
}

INTERACTION_BORDER_COLORS = {
    "PVE": "#2E6FB5",
    "PVP": "#D14F5C",
    "GVG": "#7B4FA3",
    "社交": "#238B8E",
    "养成": "#C78318",
    "功能": "#66717D",
    "未知": "#89929C",
}

EVENT_COLORS = {
    "new_feature_unlocked": "#3478C8",
    "new_skill_unlocked": "#8B5FBF",
    "level_snapshot": "#C85867",
    "combat_power_snapshot": "#D9822B",
}


def _font(size: int, *, bold: bool = False):
    candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _format_time(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds) // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, second = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{second:02d}"


def _chart_category(event: dict[str, Any]) -> str:
    classification = event["deterministic_hints"]["classification"]
    rhythm_categories = classification.get("rhythm_category") or []
    for category in (
        "帮会",
        "竞技",
        "PVP",
        "日常任务",
        "同步社交",
        "异步社交",
        "PVE",
        "核心循环（爆点）",
    ):
        if category in rhythm_categories:
            return category
    return "其他"


def _block_type(event: dict[str, Any]) -> str:
    classification = event["deterministic_hints"]["classification"]
    forms = set(classification.get("gameplay_form") or [])
    scopes = set(classification.get("object_scope") or [])
    for forms_to_match, block_type in (
        ({"商业化入口"}, "商业化"),
        ({"日常"}, "日常任务"),
        ({"排行榜"}, "竞技排行"),
        ({"组队", "聊天"}, "社交协作"),
        ({"BOSS"}, "BOSS"),
        ({"副本"}, "副本"),
        ({"养成系统", "技能"}, "成长养成"),
        ({"活动"}, "活动"),
        ({"邮箱", "通用功能"}, "通用功能"),
    ):
        if forms & forms_to_match:
            return block_type
    if "商业化" in scopes:
        return "商业化"
    if "社交" in scopes:
        return "社交协作"
    if scopes & {"角色", "伙伴", "坐骑", "装备"}:
        return "成长养成"
    return "其他"


def _interaction_mode(event: dict[str, Any]) -> str:
    classification = event["deterministic_hints"]["classification"]
    modes = set(classification.get("interaction_mode") or [])
    for mode in ("GVG", "PVP", "PVE", "社交", "养成", "功能"):
        if mode in modes:
            return mode
    if _block_type(event) == "成长养成":
        return "养成"
    return "未知"


def _draw_style_legend(draw: ImageDraw.ImageDraw, width: int) -> None:
    start_x = max(620, width - 1280)
    fill_y = 22
    draw.text((start_x, fill_y), "填充色 = 块类型", fill="#34404C", font=_font(13, bold=True))
    chip_y = fill_y + 24
    chip_width, chip_height, chip_gap = 103, 25, 7
    for index, (label, color) in enumerate(BLOCK_FILL_COLORS.items()):
        x = start_x + index * (chip_width + chip_gap)
        draw.rounded_rectangle((x, chip_y, x + chip_width, chip_y + chip_height), radius=3, fill=color, outline="#AAB2BA", width=1)
        label_width = draw.textbbox((0, 0), label, font=_font(11, bold=True))[2]
        draw.text((x + (chip_width - label_width) / 2, chip_y + 5), label, fill="#34404C", font=_font(11, bold=True))
    border_y = 80
    draw.text((start_x, border_y), "外框色 = 交互模式", fill="#34404C", font=_font(13, bold=True))
    chip_y = border_y + 22
    for index, (label, color) in enumerate(INTERACTION_BORDER_COLORS.items()):
        x = start_x + index * (chip_width + chip_gap)
        draw.rounded_rectangle((x, chip_y, x + chip_width, chip_y + chip_height), radius=3, fill="#FFFFFF", outline=color, width=3)
        label_width = draw.textbbox((0, 0), label, font=_font(11, bold=True))[2]
        draw.text((x + (chip_width - label_width) / 2, chip_y + 5), label, fill="#34404C", font=_font(11, bold=True))


def _extract_level(event: dict[str, Any]) -> str:
    import re

    match = re.search(r"(\d+)\s*级", str(event.get("ocr_excerpt") or ""))
    return f"{match.group(1)}级" if match else ""


def _phase_candidates(duration_ms: int) -> list[dict[str, Any]]:
    if duration_ms <= 300_000:
        return [{"start_ms": 0, "end_ms": duration_ms, "label": "首局：核心功能展开", "color": "#3E78B8"}]
    phases = [
        {"start_ms": 0, "end_ms": min(duration_ms, 300_000), "label": "首局：核心功能展开", "color": "#3E78B8"},
        {"start_ms": 300_000, "end_ms": min(duration_ms, 900_000), "label": "中段：成长与日常", "color": "#3D809B"},
    ]
    if duration_ms > 900_000:
        phases.append({"start_ms": 900_000, "end_ms": duration_ms, "label": "后段：玩法延伸", "color": "#3A8B82"})
    return phases


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, sizes: tuple[int, ...] = (16, 14, 12)):
    for size in sizes:
        candidate = _font(size, bold=True)
        if draw.textbbox((0, 0), text, font=candidate)[2] <= max_width:
            return candidate
    return _font(sizes[-1], bold=True)


def _assign_event_matrix(
    events: list[dict[str, Any]],
    *,
    axis_left: int,
    axis_right: int,
    total_play_time_ms: int,
    virtual_day_ms: int,
    day_count: int,
    block_width: int,
    column_gap: int = 14,
) -> tuple[list[dict[str, Any]], int, dict[int, int]]:
    by_day = {day: [] for day in range(1, day_count + 1)}
    for event in events:
        by_day.setdefault(int(event["play_day_index"]), []).append(event)
    assigned: list[dict[str, Any]] = []
    rows_by_day: dict[int, int] = {}
    max_rows = 0
    axis_width = axis_right - axis_left
    for day in range(1, day_count + 1):
        day_events = sorted(
            by_day.get(day, []),
            key=lambda item: (int(item["global_time_ms"]), item["event_id"]),
        )
        day_start_ms = (day - 1) * virtual_day_ms
        day_end_ms = min(day * virtual_day_ms, total_play_time_ms)
        section_left = axis_left + day_start_ms / total_play_time_ms * axis_width
        section_right = axis_left + day_end_ms / total_play_time_ms * axis_width
        section_width = max(1, section_right - section_left)
        column_count = max(1, int((section_width + column_gap) // (block_width + column_gap)))
        grid_width = column_count * block_width + (column_count - 1) * column_gap
        grid_left = section_left + (section_width - grid_width) / 2
        grid_left = max(axis_left, min(axis_right - grid_width, grid_left))
        row_count = (len(day_events) + column_count - 1) // column_count
        rows_by_day[day] = row_count
        max_rows = max(max_rows, row_count)
        for index, event in enumerate(day_events):
            column_index, row_index = divmod(index, max(1, row_count))
            point_x = axis_left + int(event["global_time_ms"]) / total_play_time_ms * axis_width
            block_left = grid_left + column_index * (block_width + column_gap)
            assigned.append({
                "event": event,
                "point_x": point_x,
                "block_left": block_left,
                "row_index": row_index,
                "column_index": column_index,
                "day": day,
                "day_order": index,
            })
    return assigned, max_rows, rows_by_day


def _render_open_timeline_multiday(
    semantic_input: dict[str, Any],
    events: list[dict[str, Any]],
    target: Path,
    *,
    game_name: str,
    candidate_mode: bool,
) -> dict[str, Any]:
    virtual_day_ms = 60 * 60 * 1000
    day_count = max(1, int(semantic_input["session"].get("virtual_day_count") or 1))
    total_play_time_ms = max(
        int(semantic_input["session"].get("total_play_time_ms") or 0),
        max(int(event.get("global_time_ms", event.get("time_ms", 0))) for event in events),
    )
    width = max(1900, 300 + day_count * 220)
    axis_left, axis_right = 84, width - 84
    block_width, block_height, lane_gap = 154, 56, 10
    assigned, row_count, rows_by_day = _assign_event_matrix(
        events,
        axis_left=axis_left,
        axis_right=axis_right,
        total_play_time_ms=total_play_time_ms,
        virtual_day_ms=virtual_day_ms,
        day_count=day_count,
        block_width=block_width,
    )
    header_height = 148
    summary_top, summary_bottom = header_height + 18, header_height + 72
    axis_y = header_height + 126
    bottom_start = axis_y + 42
    height = max(500, bottom_start + row_count * (block_height + lane_gap) + 78)
    image = Image.new("RGB", (width, height), "#F7F8FA")
    draw = ImageDraw.Draw(image)
    draw.text((58, 26), game_name, fill="#20262E", font=_font(28, bold=True))
    draw.text((58, 66), "玩法/系统开放节奏", fill="#34404C", font=_font(21, bold=True))
    status_text = (
        f"开放事件候选 {len(events)} 个 · 尚未人工复核"
        if candidate_mode
        else f"人工确认开放事件 {len(events)} 个 · 阶段与分类待复核"
    )
    draw.text(
        (58, 101),
        f"{status_text} · 累计有效游玩 {round(total_play_time_ms / 60_000)} 分钟 · 每60分钟计1天",
        fill="#66717D",
        font=_font(14),
    )
    _draw_style_legend(draw, width)
    draw.line((58, 132, width - 58, 132), fill="#D9DEE5", width=1)

    summaries = semantic_input.get("cycle_summaries")
    if not isinstance(summaries, list) or not summaries:
        summaries = _phase_candidates(total_play_time_ms)
    normalized_summaries = []
    for summary in summaries:
        start_ms = max(0, int(summary.get("start_ms", 0)))
        end_ms = min(total_play_time_ms, int(summary.get("end_ms", total_play_time_ms)))
        if end_ms <= start_ms:
            continue
        normalized_summaries.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "label": str(summary.get("label") or "循环总结待复核"),
            "color": str(summary.get("color") or "#3E78B8"),
        })
    draw.text((axis_left, summary_top - 18), "循环总结（候选）", fill="#5D6874", font=_font(13, bold=True))
    for summary in normalized_summaries:
        x1 = axis_left + summary["start_ms"] / total_play_time_ms * (axis_right - axis_left)
        x2 = axis_left + summary["end_ms"] / total_play_time_ms * (axis_right - axis_left)
        draw.rounded_rectangle((x1 + 2, summary_top, x2 - 2, summary_bottom), radius=4, fill=summary["color"], outline="#405261", width=1)
        available_width = max(20, int(x2 - x1) - 10)
        display_label = summary["label"]
        label_font = _fit_font(draw, display_label, available_width, sizes=(16, 14, 12, 10))
        label_width = draw.textbbox((0, 0), display_label, font=label_font)[2]
        if label_width > available_width:
            display_label = display_label.split("：", 1)[0]
            label_font = _fit_font(draw, display_label, available_width, sizes=(14, 12, 10))
            label_width = draw.textbbox((0, 0), display_label, font=label_font)[2]
        if label_width <= x2 - x1 - 8:
            draw.text(((x1 + x2 - label_width) / 2, summary_top + 16), display_label, fill="#FFFFFF", font=label_font)

    day_band_top, day_band_bottom = axis_y - 34, axis_y - 10
    for day in range(1, day_count + 1):
        start_ms = (day - 1) * virtual_day_ms
        end_ms = min(day * virtual_day_ms, total_play_time_ms)
        x1 = axis_left + start_ms / total_play_time_ms * (axis_right - axis_left)
        x2 = axis_left + end_ms / total_play_time_ms * (axis_right - axis_left)
        fill = "#E6EEF7" if day % 2 else "#EDF2F0"
        draw.rectangle((x1, day_band_top, x2, day_band_bottom), fill=fill, outline="#BCC8D3", width=1)
        label = f"第{day}天"
        label_font = _fit_font(draw, label, max(20, int(x2 - x1) - 8), sizes=(14, 12, 10))
        label_width = draw.textbbox((0, 0), label, font=label_font)[2]
        draw.text(((x1 + x2 - label_width) / 2, day_band_top + 4), label, fill="#415364", font=label_font)
        draw.line((x1, axis_y - 7, x1, axis_y + 8), fill="#2E75B6", width=2)
        boundary = f"{day - 1}h"
        draw.text((x1 - 8, axis_y + 13), boundary, fill="#697580", font=_font(11, bold=True))
    draw.line((axis_right, axis_y - 7, axis_right, axis_y + 8), fill="#2E75B6", width=2)
    draw.text((axis_right - 12, axis_y + 13), _format_time(total_play_time_ms)[:5], fill="#697580", font=_font(11, bold=True))
    draw.line((axis_left, axis_y, axis_right, axis_y), fill="#2E75B6", width=4)

    all_nodes: list[dict[str, Any]] = []
    for item in assigned:
        event = item["event"]
        row_index = item["row_index"]
        block_top = bottom_start + row_index * (block_height + lane_gap)
        block_left, point_x = item["block_left"], item["point_x"]
        category = _chart_category(event)
        block_type = _block_type(event)
        interaction_mode = _interaction_mode(event)
        fill_color = BLOCK_FILL_COLORS[block_type]
        border_color = INTERACTION_BORDER_COLORS[interaction_mode]
        block_center_x = block_left + block_width / 2
        if row_index == 0:
            bend_x = point_x + (block_center_x - point_x) * 0.38
            bend_y = axis_y + 17
            draw.line(
                [(point_x, axis_y), (bend_x, bend_y), (block_center_x, block_top)],
                fill=border_color,
                width=2,
                joint="curve",
            )
            draw.ellipse((point_x - 6, axis_y - 6, point_x + 6, axis_y + 6), fill=fill_color, outline=border_color, width=2)
        else:
            previous_bottom = block_top - lane_gap
            draw.line(
                (block_center_x, previous_bottom, block_center_x, block_top),
                fill=border_color,
                width=2,
            )
        draw.rounded_rectangle(
            (block_left, block_top, block_left + block_width, block_top + block_height),
            radius=5,
            fill=fill_color,
            outline=border_color,
            width=4,
        )
        text_color = "#263746"
        event_name = str(event["event_name"])
        name_font = _fit_font(draw, event_name, block_width - 12)
        name_width = draw.textbbox((0, 0), event_name, font=name_font)[2]
        draw.text((block_left + (block_width - name_width) / 2, block_top + 7), event_name, fill=text_color, font=name_font)
        condition = _extract_level(event) or f"第{event['play_day_index']}天 {round(int(event['day_time_ms']) / 60_000)}分"
        condition_font = _font(11)
        condition_width = draw.textbbox((0, 0), condition, font=condition_font)[2]
        draw.text((block_left + (block_width - condition_width) / 2, block_top + 34), condition, fill=text_color, font=condition_font)
        day = int(event["play_day_index"])
        all_nodes.append({
            "event_id": event["event_id"],
            "play_day_index": day,
            "day_time_ms": int(event["day_time_ms"]),
            "global_time_ms": int(event["global_time_ms"]),
            "matrix_row": row_index + 1,
            "matrix_column": item["column_index"] + 1,
            "event_name": event["event_name"],
            "category_candidate": category,
            "block_type_candidate": block_type,
            "interaction_mode_candidate": interaction_mode,
            "fill_color": fill_color,
            "border_color": border_color,
            "opening_condition_candidate": condition,
            "matched_gameplay_rule_ids": event["deterministic_hints"]["matched_gameplay_rule_ids"],
            "review_status": "needs_review",
        })
    draw.text((58, height - 38), "阶段与分类均为候选；正式图仅读取人工复核后的首次开放节点。", fill="#6E7782", font=_font(13))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")
    image.close()

    day_summaries = []
    for day in range(1, day_count + 1):
        day_start = (day - 1) * virtual_day_ms
        day_duration = min(virtual_day_ms, max(0, total_play_time_ms - day_start))
        day_summaries.append({
            "play_day_index": day,
            "duration_ms": day_duration,
            "event_count": sum(1 for event in events if int(event["play_day_index"]) == day),
            "lane_count": rows_by_day.get(day, 0),
        })

    return {
        "schema_version": "1.0",
        "chart_id": "gameplay_open_timeline",
        "status": "draft",
        "layout_mode": "single_session" if day_count == 1 else "continuous_multi_day",
        "cycle_summary_side": "above",
        "event_block_side": "below",
        "connector_mode": "first_row_two_segment_column_chain",
        "virtual_day_minutes": 60,
        "day_count": day_count,
        "page_count": 1,
        "lane_count": row_count,
        "event_count": len(all_nodes),
        "nodes": all_nodes,
        "cycle_summary_candidates": [
            {key: value for key, value in summary.items() if key != "color"}
            for summary in normalized_summaries
        ],
        "day_summaries": day_summaries,
        "outputs": [target.name],
        "output": target.name,
    }


def render_open_timeline(
    semantic_input: dict[str, Any],
    target: Path,
    *,
    game_name: str = "当前游戏",
    candidate_mode: bool = False,
) -> dict[str, Any]:
    virtual_day_ms = 60 * 60 * 1000
    events = []
    for source_event in semantic_input["events"]:
        if source_event["event_type"] != "new_feature_unlocked":
            continue
        event = dict(source_event)
        global_time_ms = int(event.get("global_time_ms", event.get("time_ms", 0)))
        event.setdefault("global_time_ms", global_time_ms)
        event.setdefault("play_day_index", global_time_ms // virtual_day_ms + 1)
        event.setdefault("day_time_ms", global_time_ms % virtual_day_ms)
        events.append(event)
    events.sort(key=lambda item: (int(item["global_time_ms"]), item["event_id"]))
    if not events:
        raise ValueError("没有可绘制的新功能开放事件")
    session = semantic_input["session"]
    total_play_time_ms = max(
        int(session.get("total_play_time_ms", session.get("duration_ms", 0)) or 0),
        max(int(event["global_time_ms"]) for event in events),
    )
    inferred_day_count = max(
        1,
        (total_play_time_ms + virtual_day_ms - 1) // virtual_day_ms,
        max(int(event["play_day_index"]) for event in events),
    )
    day_count = max(int(session.get("virtual_day_count") or 1), inferred_day_count)
    normalized_input = {
        **semantic_input,
        "session": {
            **session,
            "total_play_time_ms": total_play_time_ms,
            "virtual_day_minutes": 60,
            "virtual_day_count": day_count,
        },
    }
    return _render_open_timeline_multiday(
        normalized_input,
        events,
        target,
        game_name=game_name,
        candidate_mode=candidate_mode,
    )


def render_emotion_timeline_draft(
    semantic_input: dict[str, Any],
    emotion_rules: dict[str, Any],
    target: Path,
) -> dict[str, Any]:
    from .rules import score_emotion

    candidates = []
    excluded = []
    for event in semantic_input["events"]:
        rule_ids = event["deterministic_hints"].get("suggested_emotion_rule_ids") or []
        score_result = score_emotion(rule_ids, emotion_rules)
        if score_result["score"] is None:
            excluded.append({"event_id": event["event_id"], "reason": "no_rule_candidate"})
            continue
        candidates.append({**event, "score_result": score_result})
    if not candidates:
        raise ValueError("没有可绘制的情绪规则候选")
    width, height = 1680, 760
    left, right, top, bottom = 96, 62, 170, 118
    plot_width = width - left - right
    plot_height = height - top - bottom
    duration_ms = max(int(semantic_input["session"]["duration_ms"]), 60_000)
    image = Image.new("RGB", (width, height), "#F7F8FA")
    draw = ImageDraw.Draw(image)
    draw.text((52, 30), "事件与情绪时间图", fill="#20262E", font=_font(30, bold=True))
    draw.text(
        (52, 73),
        f"规则候选事件 {len(candidates)} 个；分值范围 -2～+3，必须经过人工复核",
        fill="#66717D",
        font=_font(16),
    )
    draw.line((52, 108, width - 52, 108), fill="#D9DEE5", width=1)
    for score in range(-2, 4):
        y = top + (3 - score) / 5 * plot_height
        draw.line((left, y, width - right, y), fill="#DDE2E8", width=1)
        draw.text((left - 42, y - 11), f"{score:+d}" if score else "0", fill="#5F6974", font=_font(15, bold=True))
    for tick in range(6):
        x = left + plot_width * tick / 5
        draw.line((x, top, x, height - bottom), fill="#E8EBEF", width=1)
        draw.text((x - 30, height - bottom + 20), _format_time(round(duration_ms * tick / 5))[3:], fill="#6E7782", font=_font(14))
    draw.text((left, top - 34), "情绪分值", fill="#5F6974", font=_font(15, bold=True))
    nodes = []
    previous = None
    for index, event in enumerate(candidates):
        score = int(event["score_result"]["score"])
        x = left + event["time_ms"] / duration_ms * plot_width
        y = top + (3 - score) / 5 * plot_height
        color = EVENT_COLORS.get(event["event_type"], "#6F7B87")
        if previous is not None:
            draw.line((previous[0], previous[1], x, y), fill="#AEB7C1", width=2)
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline="white", width=2)
        label_y = top + 12 + (index % 4) * 30
        label = f"{event['timestamp'][3:8]} {event['event_name']} {score:+d}"
        label_width = draw.textbbox((0, 0), label, font=_font(12, bold=True))[2]
        label_x = min(max(left, x - label_width / 2), width - right - label_width)
        draw.rounded_rectangle((label_x - 5, label_y - 3, label_x + label_width + 5, label_y + 20), radius=3, fill="#FFFFFF", outline="#D9DEE5")
        draw.text((label_x, label_y), label, fill="#34404C", font=_font(12, bold=True))
        draw.line((x, label_y + 20, x, y - 10), fill="#C9D0D7", width=1)
        previous = (x, y)
        nodes.append({
            "event_id": event["event_id"],
            "timestamp": event["timestamp"],
            "event_name": event["event_name"],
            "emotion_score_candidate": score,
            "matched_emotion_rule_ids": event["score_result"]["matched_rule_ids"],
            "review_status": "needs_review",
        })
    draw.text(
        (52, height - 42),
        "注意：本图表达规则评分候选，不代表已观察到玩家真实情绪；无规则证据的等级/战力快照未强行赋分。",
        fill="#A44848",
        font=_font(14, bold=True),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")
    image.close()
    return {
        "schema_version": "1.0",
        "chart_id": "event_emotion_timeline",
        "status": "draft",
        "event_count": len(nodes),
        "excluded_count": len(excluded),
        "nodes": nodes,
        "excluded": excluded,
        "output": target.name,
    }


def render_emotion_timeline_final(
    confirmed_events: dict[str, Any],
    target: Path,
) -> dict[str, Any]:
    events = [
        event for event in confirmed_events.get("events") or []
        if (event.get("semantic_review") or {}).get("status") == "confirmed"
        and isinstance((event.get("semantic") or {}).get("emotion_score"), (int, float))
    ]
    return _render_final_line_chart(
        events,
        target,
        title="事件与情绪时间图",
        subtitle=f"人工确认事件 {len(events)} 个；分值范围 -2～+3",
    )


def render_growth_timeline_final(
    confirmed_metrics: dict[str, Any],
    target: Path,
) -> dict[str, Any]:
    metrics = [
        item for item in confirmed_metrics.get("metrics") or []
        if (item.get("review") or {}).get("status") == "confirmed"
    ]
    return _render_growth_timeline(
        metrics,
        confirmed_metrics,
        target,
        status="final",
        subtitle=f"人工确认指标 {len(metrics)} 条",
        empty_label="无人工确认数据",
        footer="仅展示人工确认的战力、等级与转生指标；候选和排除项不进入本图。",
    )


def render_growth_timeline_draft(
    metric_candidates: dict[str, Any],
    target: Path,
) -> dict[str, Any]:
    metrics = [
        item for item in metric_candidates.get("metrics") or []
        if (item.get("review") or {}).get("status") != "excluded"
    ]
    return _render_growth_timeline(
        metrics,
        metric_candidates,
        target,
        status="draft",
        subtitle=f"OCR候选指标 {len(metrics)} 条；尚未人工复核",
        empty_label="无可用候选数据",
        footer="预览：包含待复核OCR候选，仅用于验证趋势与产物结构，不可作为正式结论。",
    )


def _render_growth_timeline(
    metrics: list[dict[str, Any]],
    source: dict[str, Any],
    target: Path,
    *,
    status: str,
    subtitle: str,
    empty_label: str,
    footer: str,
) -> dict[str, Any]:
    duration_ms = max(
        int((source.get("session") or {}).get("duration_ms") or 0),
        max((int(item.get("time_ms") or 0) for item in metrics), default=0),
        60_000,
    )
    width, height = 1680, 900
    image = Image.new("RGB", (width, height), "#F7F8FA")
    draw = ImageDraw.Draw(image)
    draw.text((52, 30), "成长反馈时间图" if status == "final" else "成长反馈时间图（候选预览）", fill="#20262E", font=_font(30, bold=True))
    draw.text((52, 73), subtitle, fill="#66717D", font=_font(16))
    draw.line((52, 108, width - 52, 108), fill="#D9DEE5", width=1)
    groups = [
        ("combat_power", "战力", "#D75050"),
        ("level", "等级", "#3D809B"),
        ("level_rebirth", "转生 / 等级", "#6D62A8"),
    ]
    left, right = 110, 64
    plot_width = width - left - right
    panels = []
    for panel_index, (metric_key, label, color) in enumerate(groups):
        top = 150 + panel_index * 225
        bottom = top + 165
        values = [item for item in metrics if item.get("metric_key") == metric_key]
        numeric = [(item, _metric_numeric_value(item)) for item in values]
        numeric = [(item, value) for item, value in numeric if value is not None]
        draw.text((52, top), label, fill="#34404C", font=_font(17, bold=True))
        draw.rectangle((left, top, width - right, bottom), outline="#D9DEE5", width=1)
        for tick in range(6):
            x = left + plot_width * tick / 5
            draw.line((x, top, x, bottom), fill="#E8EBEF", width=1)
            if panel_index == len(groups) - 1:
                draw.text((x - 30, bottom + 14), _format_time(round(duration_ms * tick / 5))[3:], fill="#6E7782", font=_font(13))
        if not numeric:
            draw.text((left + 18, top + 68), empty_label, fill="#8A949E", font=_font(15))
            panels.append({"metric_key": metric_key, "count": 0, "points": []})
            continue
        min_value = min(value for _item, value in numeric)
        max_value = max(value for _item, value in numeric)
        span = max(1.0, max_value - min_value)
        points = []
        previous = None
        label_step = max(1, (len(numeric) + 11) // 12)
        for point_index, (item, value) in enumerate(numeric):
            x = left + int(item.get("time_ms") or 0) / duration_ms * plot_width
            y = bottom - 18 - (value - min_value) / span * (bottom - top - 36)
            if previous is not None:
                draw.line((previous[0], previous[1], x, y), fill=color, width=3)
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color, outline="#FFFFFF", width=2)
            if point_index % label_step == 0 or point_index == len(numeric) - 1:
                display = str(item.get("parsed_value") or item.get("raw_text") or "")
                draw.text((min(x + 8, width - right - 90), max(top + 4, y - 24)), display[:12], fill=color, font=_font(12, bold=True))
            previous = (x, y)
            points.append({"observation_id": item.get("observation_id"), "time_ms": item.get("time_ms"), "value": item.get("parsed_value")})
        panels.append({"metric_key": metric_key, "count": len(points), "points": points})
    draw.text((52, height - 42), footer, fill="#66717D", font=_font(14))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")
    image.close()
    return {"schema_version": "1.0", "chart_id": "growth_timeline", "status": status, "metric_count": len(metrics), "panels": panels, "output": target.name}


def _render_final_line_chart(events: list[dict[str, Any]], target: Path, *, title: str, subtitle: str) -> dict[str, Any]:
    width, height = 1680, 760
    left, right, top, bottom = 96, 62, 170, 118
    plot_width = width - left - right
    plot_height = height - top - bottom
    duration_ms = max(max((int(event.get("time_ms") or 0) for event in events), default=0), 60_000)
    image = Image.new("RGB", (width, height), "#F7F8FA")
    draw = ImageDraw.Draw(image)
    draw.text((52, 30), title, fill="#20262E", font=_font(30, bold=True))
    draw.text((52, 73), subtitle, fill="#66717D", font=_font(16))
    draw.line((52, 108, width - 52, 108), fill="#D9DEE5", width=1)
    for score in range(-2, 4):
        y = top + (3 - score) / 5 * plot_height
        draw.line((left, y, width - right, y), fill="#DDE2E8", width=1)
        draw.text((left - 42, y - 11), f"{score:+d}" if score else "0", fill="#5F6974", font=_font(15, bold=True))
    for tick in range(6):
        x = left + plot_width * tick / 5
        draw.line((x, top, x, height - bottom), fill="#E8EBEF", width=1)
        draw.text((x - 30, height - bottom + 20), _format_time(round(duration_ms * tick / 5))[3:], fill="#6E7782", font=_font(14))
    nodes = []
    previous = None
    for index, event in enumerate(events):
        score = int(round(float((event.get("semantic") or {}).get("emotion_score") or 0)))
        x = left + int(event.get("time_ms") or 0) / duration_ms * plot_width
        y = top + (3 - score) / 5 * plot_height
        color = EVENT_COLORS.get(str(event.get("event_type") or ""), "#6F7B87")
        if previous is not None:
            draw.line((previous[0], previous[1], x, y), fill="#AEB7C1", width=2)
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline="white", width=2)
        label_y = top + 12 + (index % 4) * 30
        label = f"{str(event.get('timestamp') or '')[3:8]} {str(event.get('event_name') or '')} {score:+d}"
        label_width = draw.textbbox((0, 0), label, font=_font(12, bold=True))[2]
        label_x = min(max(left, x - label_width / 2), width - right - label_width)
        draw.rounded_rectangle((label_x - 5, label_y - 3, label_x + label_width + 5, label_y + 20), radius=3, fill="#FFFFFF", outline="#D9DEE5")
        draw.text((label_x, label_y), label, fill="#34404C", font=_font(12, bold=True))
        draw.line((x, label_y + 20, x, y - 10), fill="#C9D0D7", width=1)
        previous = (x, y)
        nodes.append({"event_id": event.get("event_id"), "time_ms": event.get("time_ms"), "emotion_score": score})
    if not events:
        draw.text((left + 20, top + plot_height / 2), "无人工确认的情绪事件", fill="#8A949E", font=_font(17))
    draw.text((52, height - 42), "仅展示人工确认事件及规则终结后的情绪分值。", fill="#66717D", font=_font(14))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")
    image.close()
    return {"schema_version": "1.0", "chart_id": "event_emotion_timeline", "status": "final", "event_count": len(nodes), "nodes": nodes, "output": target.name}


def _metric_numeric_value(metric: dict[str, Any]) -> float | None:
    value = metric.get("parsed_value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    fields = metric.get("parsed_fields") or {}
    level = fields.get("level")
    rebirth = fields.get("rebirth")
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        return float(level) + float(rebirth or 0) * 1000
    match = re.search(r"(?:(\d+)转)?\s*(\d+)级", str(value or metric.get("raw_text") or ""))
    if match:
        return float(match.group(2)) + float(match.group(1) or 0) * 1000
    return None
