from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .error_report import ErrorReport, build_error_report, write_error_report


@dataclass(frozen=True, slots=True)
class ErrorReportResult:
    report: ErrorReport
    json_path: Path | None
    txt_path: Path | None


class ErrorReporter:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def create(
        self,
        stage: str,
        error: BaseException,
        context: dict[str, Any] | None = None,
    ) -> ErrorReportResult:
        report = build_error_report(stage, error, context=context)
        try:
            json_path, txt_path = write_error_report(self.base_dir, report)
        except Exception:
            json_path = None
            txt_path = None
        return ErrorReportResult(report, json_path, txt_path)
