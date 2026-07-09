"""Build a standalone Windows executable with PyInstaller.

Usage (from the project root, on Windows):

    python -m pip install -e ".[dev]"
    python scripts/build_exe.py

Output: dist/screen-mouse-recorder.exe

Notes:
- FFmpeg and Tesseract are NOT bundled. They stay external per tools/README.md;
  point config.json at them with ffmpeg_path / tesseract_path / tessdata_dir.
- The executable resolves its base directory next to itself (see cli.default_base_dir),
  so config.json / sessions / frame_sheets live beside the .exe at runtime.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from screen_mouse_recorder import __version__

    return __version__


def main() -> int:
    entry = ROOT / "run.py"
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "screen-mouse-recorder",
        "--paths",
        str(ROOT / "src"),
        str(entry),
    ]
    print(f"Building screen-mouse-recorder {_version()}")
    print(" ".join(args))
    return subprocess.call(args, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
