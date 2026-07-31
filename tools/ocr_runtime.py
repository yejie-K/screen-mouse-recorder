from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
import sys
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class OCRRuntimeResult(Generic[T]):
    engine: T | None
    available: bool
    source: str
    message: str


def load_rapidocr(
    project_root: Path,
    *,
    engine_factory: Callable[[], T],
    explicit_runtime: Path | None = None,
) -> OCRRuntimeResult[T]:
    """Find an OCR installation without making a developer-only path mandatory."""
    source = "current"
    if find_spec("rapidocr_onnxruntime") is None:
        runtime, source = _discover_runtime(project_root, explicit_runtime)
        if runtime is None:
            return OCRRuntimeResult(
                engine=None,
                available=False,
                source="missing",
                message="OCR组件未安装，区域框选仍可使用，但测试识别和全量扫描暂不可用",
            )
        site_packages = _site_packages(runtime)
        if site_packages is None:
            return OCRRuntimeResult(
                engine=None,
                available=False,
                source="invalid",
                message="OCR运行时不完整，请重新安装OCR组件",
            )
        site_value = str(site_packages)
        if site_value not in sys.path:
            sys.path.insert(0, site_value)

    try:
        engine = engine_factory()
    except Exception as exc:  # Optional runtime failures must not prevent manual review.
        return OCRRuntimeResult(
            engine=None,
            available=False,
            source=source,
            message=f"OCR组件初始化失败：{exc}",
        )
    return OCRRuntimeResult(
        engine=engine,
        available=True,
        source=source,
        message=f"OCR已就绪（{getattr(engine, 'name', 'RapidOCR')} {getattr(engine, 'version', '')}）".rstrip(),
    )


def _discover_runtime(project_root: Path, explicit_runtime: Path | None) -> tuple[Path | None, str]:
    if explicit_runtime is not None:
        return explicit_runtime.expanduser().resolve(), "explicit"
    candidates = (
        (project_root / ".runtime" / "ocr", "portable"),
        (project_root / ".runtime" / "python", "portable"),
        (project_root / "experiments" / "ocr_engine_eval_20260709" / ".venv", "development"),
    )
    for runtime, source in candidates:
        site_packages = _site_packages(runtime)
        if site_packages is not None and (site_packages / "rapidocr_onnxruntime").is_dir():
            return runtime.resolve(), source
    return None, "missing"


def _site_packages(runtime: Path) -> Path | None:
    candidates = [runtime / "Lib" / "site-packages"]
    if (runtime / "lib").is_dir():
        candidates.extend(sorted((runtime / "lib").glob("python*/site-packages")))
    return next((candidate for candidate in candidates if candidate.is_dir()), None)
