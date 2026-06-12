from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time

from .models import Region, monotonic_ms


class FFmpegRecorder:
    def __init__(self, ffmpeg_path: str | None = None) -> None:
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self.process: subprocess.Popen[bytes] | None = None
        self._log_file = None

    def is_available(self) -> bool:
        if self.ffmpeg_path:
            return Path(self.ffmpeg_path).exists() or shutil.which(self.ffmpeg_path) is not None
        return shutil.which("ffmpeg") is not None

    def start(self, region: Region, output_file: Path, fps: int, log_file: Path) -> float:
        ffmpeg = self.ffmpeg_path or shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg was not found. Add ffmpeg.exe to PATH or set ffmpeg_path in config.json.")

        self._log_file = log_file.open("a", encoding="utf-8", newline="\n")
        command = self._build_command(ffmpeg, region, output_file, fps)
        self._log_file.write(" ".join(command) + "\n\n")
        self._log_file.flush()

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
        start_ms = monotonic_ms()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=self._log_file,
            stderr=self._log_file,
            creationflags=creationflags,
        )
        time.sleep(0.25)
        if self.process.poll() is not None:
            returncode = self.process.returncode
            self._log_file.flush()
            raise RuntimeError(f"FFmpeg exited immediately with code {returncode}. See {log_file}.")
        return start_ms

    @staticmethod
    def _build_command(ffmpeg: str, region: Region, output_file: Path, fps: int) -> list[str]:
        return [
            ffmpeg,
            "-y",
            "-f",
            "gdigrab",
            "-framerate",
            str(fps),
            "-offset_x",
            str(region.screen_x),
            "-offset_y",
            str(region.screen_y),
            "-video_size",
            f"{region.width}x{region.height}",
            "-draw_mouse",
            "1",
            "-i",
            "desktop",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(output_file),
        ]

    def stop(self, timeout_seconds: float = 60.0) -> None:
        proc = self.process
        if proc is None:
            return
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
                proc.wait(timeout=timeout_seconds)
            except Exception:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.process = None
        if self._log_file is not None:
            self._log_file.write(f"\nStopped at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            self._log_file.flush()
            self._log_file.close()
            self._log_file = None

    def returncode(self) -> int | None:
        return None if self.process is None else self.process.poll()


def concat_mp4_segments(ffmpeg_path: str | None, segment_files: list[Path], output_file: Path, log_file: Path) -> None:
    if not segment_files:
        raise RuntimeError("No video segments were created.")
    ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg was not found. Cannot combine recording segments.")
    if len(segment_files) == 1:
        shutil.copy2(segment_files[0], output_file)
        return

    concat_file = output_file.parent / "segments.txt"
    concat_file.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in segment_files) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    command = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(output_file),
    ]
    with log_file.open("a", encoding="utf-8", newline="\n") as file:
        file.write("\nConcat command:\n" + " ".join(command) + "\n")
        result = subprocess.run(command, stdout=file, stderr=file, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed with code {result.returncode}. See {log_file}.")
