from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import zipfile
from xml.sax.saxutils import escape, quoteattr
from typing import Any

from .storage import SessionStorage


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def generate_summary(storage: SessionStorage) -> dict[str, Any]:
    events = iter_jsonl(storage.mouse_events)
    samples = iter_jsonl(storage.mouse_samples)
    event_counts = Counter(row.get("event_type", "unknown") for row in events)
    click_rows = [row for row in events if row.get("event_type") == "click"]
    wheel_rows = [row for row in events if row.get("event_type") == "wheel"]
    drag_rows = [row for row in events if row.get("event_type") == "drag_start"]
    inside_clicks = sum(1 for row in click_rows if row_inside_video_region(row))
    outside_clicks = len(click_rows) - inside_clicks

    all_times = [row.get("t_video_ms", 0) for row in events + samples]
    duration_ms = max(all_times) if all_times else 0
    duration_minutes = duration_ms / 60_000 if duration_ms else 0
    clicks_per_minute = len(click_rows) / duration_minutes if duration_minutes else 0

    summary = {
        "schema_version": "1.0",
        "events_total": len(events),
        "samples_total": len(samples),
        "duration_ms": round(duration_ms, 3),
        "duration_minutes": round(duration_minutes, 3),
        "event_counts": dict(sorted(event_counts.items())),
        "clicks_total": len(click_rows),
        "clicks_inside_region": inside_clicks,
        "clicks_outside_region": outside_clicks,
        "clicks_per_minute": round(clicks_per_minute, 3),
        "wheel_events": len(wheel_rows),
        "drag_count": len(drag_rows),
    }
    storage.write_json(storage.mouse_summary, summary)
    write_summary_xlsx(storage.mouse_summary_xlsx, summary, events, samples)
    write_analysis_xlsx(storage.mouse_analysis_xlsx, summary, events)
    return summary


def row_inside_video_region(row: dict[str, Any]) -> bool:
    if "inside_video_region" in row:
        return bool(row["inside_video_region"])
    return bool(row.get("inside_region"))


EVENT_COLUMNS = [
    "event_id",
    "event_type",
    "t_video_ms",
    "video_timecode",
    "screen_x",
    "screen_y",
    "region_x",
    "region_y",
    "video_x",
    "video_y",
    "inside_video_region",
    "calibration_applied",
    "calibration_method",
    "coordinate_check_completed",
    "button",
    "wheel_delta",
    "duration_ms",
    "source",
]

SAMPLE_COLUMNS = [
    "sample_id",
    "t_video_ms",
    "video_timecode",
    "screen_x",
    "screen_y",
    "region_x",
    "region_y",
    "video_x",
    "video_y",
    "inside_video_region",
    "calibration_applied",
    "calibration_method",
    "coordinate_check_completed",
    "source",
]


def write_summary_xlsx(
    path: Path,
    summary: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
    samples: list[dict[str, Any]] | None = None,
) -> None:
    events = events or []
    samples = samples or []
    rows: list[list[Any]] = [
        ["Metric", "Value"],
        ["events_total", summary["events_total"]],
        ["samples_total", summary["samples_total"]],
        ["duration_ms", summary["duration_ms"]],
        ["duration_minutes", summary["duration_minutes"]],
        ["clicks_total", summary["clicks_total"]],
        ["clicks_inside_region", summary["clicks_inside_region"]],
        ["clicks_outside_region", summary["clicks_outside_region"]],
        ["clicks_per_minute", summary["clicks_per_minute"]],
        ["wheel_events", summary["wheel_events"]],
        ["drag_count", summary["drag_count"]],
        [],
        ["Event Type", "Count"],
    ]
    rows.extend([[key, value] for key, value in summary["event_counts"].items()])
    rows.extend(
        [
            [],
            ["Mouse Events"],
            EVENT_COLUMNS,
            *[[row.get(column) for column in EVENT_COLUMNS] for row in events],
            [],
            ["Mouse Samples"],
            SAMPLE_COLUMNS,
            *[[row.get(column) for column in SAMPLE_COLUMNS] for row in samples],
        ]
    )
    write_minimal_xlsx(path, rows, sheet_name="Summary")


def write_analysis_xlsx(path: Path, summary: dict[str, Any], events: list[dict[str, Any]]) -> None:
    operation_events = [
        row
        for row in events
        if row.get("event_type") in {"click", "double_click_candidate", "wheel", "drag_start", "drag_end"}
    ]
    rows: list[list[Any]] = [
        ["录制概览"],
        ["指标", "数值"],
        ["录制时长（分钟）", summary["duration_minutes"]],
        ["事件总数", summary["events_total"]],
        ["鼠标轨迹采样数", summary["samples_total"]],
        ["点击总数", summary["clicks_total"]],
        ["区域内点击数", summary["clicks_inside_region"]],
        ["区域外点击数", summary["clicks_outside_region"]],
        ["滚轮事件数", summary["wheel_events"]],
        ["拖拽次数", summary["drag_count"]],
        ["每分钟点击数", summary["clicks_per_minute"]],
        [],
        ["操作明细"],
        ["序号", "视频时间", "操作类型", "按钮/方向", "视频X", "视频Y", "是否在录制区域内", "持续毫秒", "原始事件", "事件ID"],
    ]
    for index, row in enumerate(operation_events, start=1):
        rows.append(
            [
                index,
                row.get("video_timecode"),
                chinese_event_type(str(row.get("event_type", ""))),
                operation_detail(row),
                row.get("video_x"),
                row.get("video_y"),
                "是" if row_inside_video_region(row) else "否",
                row.get("duration_ms"),
                row.get("event_type"),
                row.get("event_id"),
            ]
        )
    rows.extend(
        [
            [],
            ["字段说明"],
            ["视频X/视频Y", "鼠标在 mp4 视频画面内的位置，后续画图优先用这两个字段。"],
            ["是否在录制区域内", "否表示鼠标坐标落在录制区域外，通常不建议进入主分析。"],
            ["原始事件", "保留英文事件名，方便后续脚本继续处理。"],
        ]
    )
    write_minimal_xlsx(path, rows, sheet_name="中文分析")


def chinese_event_type(event_type: str) -> str:
    labels = {
        "click": "点击",
        "double_click_candidate": "双击候选",
        "wheel": "滚轮",
        "drag_start": "拖拽开始",
        "drag_end": "拖拽结束",
    }
    return labels.get(event_type, event_type)


def operation_detail(row: dict[str, Any]) -> str:
    event_type = row.get("event_type")
    if event_type == "wheel":
        delta = row.get("wheel_delta") or 0
        return "向上" if delta > 0 else "向下"
    button = row.get("button")
    labels = {"left": "左键", "right": "右键", "middle": "中键"}
    return labels.get(button, "") if isinstance(button, str) else ""


def write_minimal_xlsx(path: Path, rows: list[list[Any]], sheet_name: str = "Summary") -> None:
    sheet_xml = worksheet_xml(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", workbook_xml(sheet_name))
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        archive.writestr("xl/styles.xml", STYLES)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def worksheet_xml(rows: list[list[Any]]) -> str:
    row_xml: list[str] = []
    for r_idx, row in enumerate(rows, start=1):
        cells: list[str] = []
        for c_idx, value in enumerate(row, start=1):
            ref = f"{column_name(c_idx)}{r_idx}"
            if value is None:
                continue
            if isinstance(value, bool):
                cells.append(f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>')
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        row_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        + "".join(row_xml)
        + "</sheetData></worksheet>"
    )


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

def workbook_xml(sheet_name: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        f'<sheet name={quoteattr(sheet_name[:31])} sheetId="1" r:id="rId1"/>'
        "</sheets>"
        "</workbook>"
    )

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""
