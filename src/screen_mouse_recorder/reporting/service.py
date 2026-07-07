from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..analysis import BehaviorAnalysisResult, generate_behavior_report
from ..naming import default_report_output_dir


@dataclass(slots=True)
class BehaviorReportJob:
    source_path: Path
    output_dir: Path
    ffmpeg_path: str | None = None


def make_behavior_report_job(
    source_path: Path,
    *,
    output_dir: Path | None = None,
    ffmpeg_path: str | None = None,
) -> BehaviorReportJob:
    source_path = source_path.resolve()
    return BehaviorReportJob(
        source_path=source_path,
        output_dir=(output_dir or default_report_output_dir(source_path)).resolve(),
        ffmpeg_path=ffmpeg_path,
    )


def run_behavior_report_job(job: BehaviorReportJob) -> BehaviorAnalysisResult:
    return generate_behavior_report(job.source_path, job.output_dir, job.ffmpeg_path)
