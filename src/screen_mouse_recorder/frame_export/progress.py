from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameExportProgress:
    percent: float
    progress_text: str
    remaining_text: str


def starting_progress() -> FrameExportProgress:
    return FrameExportProgress(0.0, "准备生成...", "预计剩余 --")


def failed_progress() -> FrameExportProgress:
    return FrameExportProgress(0.0, "", "生成失败")


def completed_progress() -> FrameExportProgress:
    return FrameExportProgress(100.0, "完成", "完成")


def update_progress(
    done: int,
    total: int,
    message: str,
    *,
    started_ms: float | None,
    now_ms: float,
) -> FrameExportProgress:
    if total <= 0:
        return FrameExportProgress(0.0, message, "")
    done = max(0, min(done, total))
    percent = done / total * 100
    progress_text = f"{done}/{total} · {message}"
    if started_ms is None or done <= 0:
        return FrameExportProgress(percent, progress_text, "预计剩余 --")
    elapsed_seconds = max(0.0, (now_ms - started_ms) / 1000)
    remaining_seconds = elapsed_seconds / done * max(0, total - done)
    return FrameExportProgress(percent, progress_text, f"预计剩余 {format_duration_seconds(remaining_seconds)}")


def format_duration_seconds(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes:02d}分"
    if minutes:
        return f"{minutes}分{secs:02d}秒"
    return f"{secs}秒"
