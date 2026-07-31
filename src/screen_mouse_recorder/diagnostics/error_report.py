from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
import traceback
from typing import Any


ERROR_REPORT_DIR = Path("logs") / "error_reports"


@dataclass(frozen=True, slots=True)
class ErrorDefinition:
    title: str
    explanation: str
    suggestion: str


@dataclass(slots=True)
class ErrorReport:
    code: str
    stage: str
    title: str
    explanation: str
    suggestion: str
    exception_type: str
    exception_message: str
    timestamp: str
    context: dict[str, Any] = field(default_factory=dict)
    traceback_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ERROR_DEFINITIONS: dict[str, ErrorDefinition] = {
    "REC-START-001": ErrorDefinition(
        "录制启动失败",
        "软件未能启动录制进程或鼠标记录器。",
        "检查录制区域、输出目录和 FFmpeg 配置，然后重新开始录制。",
    ),
    "REC-PAUSE-001": ErrorDefinition(
        "录制暂停失败",
        "暂停时未能正确停止当前录制片段或鼠标记录器。",
        "先确认输出目录可写；如果仍然失败，重启软件后重新录制。",
    ),
    "REC-SAVE-001": ErrorDefinition(
        "录制保存失败",
        "录制已经停止，但保存、合并视频或生成摘要时出现错误。",
        "检查 session 目录内的视频片段和 ffmpeg.log，确认磁盘空间和 FFmpeg 是否正常。",
    ),
    "SUM-REGEN-001": ErrorDefinition(
        "摘要表格生成失败",
        "重新生成 mouse_summary 或 mouse_analysis 表格时出现错误。",
        "检查当前 session 目录是否完整，尤其是 mouse_events.jsonl、mouse_samples.jsonl 和写入权限。",
    ),
    "RPT-AUTO-001": ErrorDefinition(
        "自动报告生成失败",
        "录制数据已保存，但自动分析图表或报告生成失败。",
        "检查 session 中是否存在 mouse_events.jsonl、mouse_samples.jsonl 和 recording.mp4。",
    ),
    "FRM-PROBE-001": ErrorDefinition(
        "视频读取失败",
        "软件无法读取视频时长、分辨率或帧率信息。",
        "检查视频路径是否存在，FFmpeg/ffprobe 是否可用，以及视频文件是否损坏。",
    ),
    "FRM-PREVIEW-001": ErrorDefinition(
        "裁剪预览失败",
        "软件无法从视频中截取预览帧。",
        "换一个预览时间点，或确认视频文件和 FFmpeg 配置是否正常。",
    ),
    "FRM-ESTIMATE-001": ErrorDefinition(
        "抽帧预估失败",
        "抽帧参数无法解析，或视频信息不足以生成抽帧计划。",
        "检查开始/结束时间、裁剪区域、点击事件文件和抽帧模式。",
    ),
    "FRM-EXPORT-001": ErrorDefinition(
        "抽帧拼图失败",
        "生成合成图、索引或预览页时失败。",
        "检查输出目录可写、磁盘空间充足，并确认视频和事件文件未被移动。",
    ),
    "OCR-INPUT-001": ErrorDefinition(
        "OCR 输入无效",
        "人工选帧文件、抽帧索引、原始视频或图片路径不完整。",
        "检查 selected_ocr_tiles.json、keyframes_click_sheet_index.json 和视频/原图路径。",
    ),
    "OCR-RUN-001": ErrorDefinition(
        "关键帧 OCR 失败",
        "OCR 模型未安装、识别失败，或事件结果文件无法写入。",
        "检查 OCR 可选依赖、输入图片、输出目录权限和错误报告中的技术信息。",
    ),
    "OCR-REGION-SCAN-001": ErrorDefinition(
        "区域 OCR 扫描失败",
        "确认区域无法应用到抽帧原图，或全抽帧局部 OCR 在读取、识别、解析或写入时失败。",
        "检查区域 profile 是否已人工确认、抽帧索引和原始视频是否匹配，并核对分辨率与 OCR 依赖。",
    ),
    "UPD-APPLY-001": ErrorDefinition(
        "自动更新失败",
        "软件检查或执行 GitHub 更新时失败。",
        "检查网络、Git 是否可用，以及本地源码是否有未提交改动。",
    ),
    "APP-RESTART-001": ErrorDefinition(
        "自动重启失败",
        "更新完成后，软件未能自动启动新进程。",
        "手动关闭并重新打开软件即可让更新生效。",
    ),
    "APP-UNKNOWN-001": ErrorDefinition(
        "未知错误",
        "软件遇到了未分类的异常。",
        "保留错误报告文件，复现后根据报告中的阶段、上下文和 traceback 排查。",
    ),
}


STAGE_TO_CODE: dict[str, str] = {
    "recording_start": "REC-START-001",
    "recording_pause": "REC-PAUSE-001",
    "recording_stop": "REC-SAVE-001",
    "summary_regenerate": "SUM-REGEN-001",
    "auto_report": "RPT-AUTO-001",
    "frame_probe": "FRM-PROBE-001",
    "frame_preview": "FRM-PREVIEW-001",
    "frame_estimate": "FRM-ESTIMATE-001",
    "frame_export": "FRM-EXPORT-001",
    "ocr_input": "OCR-INPUT-001",
    "ocr_run": "OCR-RUN-001",
    "ocr_region_scan": "OCR-REGION-SCAN-001",
    "update_apply": "UPD-APPLY-001",
    "app_restart": "APP-RESTART-001",
}


def build_error_report(
    stage: str,
    error: BaseException,
    *,
    code: str | None = None,
    context: dict[str, Any] | None = None,
) -> ErrorReport:
    error_code = code or infer_error_code(stage, error)
    definition = ERROR_DEFINITIONS.get(error_code, ERROR_DEFINITIONS["APP-UNKNOWN-001"])
    return ErrorReport(
        code=error_code,
        stage=stage,
        title=definition.title,
        explanation=definition.explanation,
        suggestion=definition.suggestion,
        exception_type=type(error).__name__,
        exception_message=str(error),
        timestamp=datetime.now().isoformat(timespec="seconds"),
        context=_jsonable_context(context or {}),
        traceback_text="".join(traceback.format_exception(type(error), error, error.__traceback__)),
    )


def infer_error_code(stage: str, error: BaseException) -> str:
    if isinstance(error, PermissionError):
        return "REC-SAVE-001" if stage.startswith("recording") else STAGE_TO_CODE.get(stage, "APP-UNKNOWN-001")
    return STAGE_TO_CODE.get(stage, "APP-UNKNOWN-001")


def write_error_report(base_dir: Path, report: ErrorReport) -> tuple[Path, Path]:
    report_dir = (base_dir / ERROR_REPORT_DIR).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_code = report.code.lower().replace("-", "_")
    json_path = report_dir / f"{stamp}_{safe_code}.json"
    txt_path = report_dir / f"{stamp}_{safe_code}.txt"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    txt_path.write_text(format_error_report_text(report), encoding="utf-8", newline="\n")
    return json_path, txt_path


def format_error_dialog_message(report: ErrorReport, txt_path: Path | None = None) -> str:
    lines = [
        f"错误代码：{report.code}",
        f"阶段：{report.stage}",
        f"说明：{report.explanation}",
        f"建议：{report.suggestion}",
        f"技术信息：{report.exception_type}: {report.exception_message}",
    ]
    if txt_path is not None:
        lines.append(f"报告：{txt_path}")
    return "\n\n".join(lines)


def format_error_report_text(report: ErrorReport) -> str:
    context_text = "\n".join(f"- {key}: {value}" for key, value in report.context.items()) or "- 无"
    return (
        f"{report.title}\n"
        f"错误代码: {report.code}\n"
        f"阶段: {report.stage}\n"
        f"时间: {report.timestamp}\n\n"
        f"说明:\n{report.explanation}\n\n"
        f"建议:\n{report.suggestion}\n\n"
        f"异常:\n{report.exception_type}: {report.exception_message}\n\n"
        f"上下文:\n{context_text}\n\n"
        f"Traceback:\n{report.traceback_text or '无'}\n"
    )


def _jsonable_context(context: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, Path):
            result[key] = str(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        else:
            result[key] = str(value)
    return result
