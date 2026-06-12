from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import time
from typing import Any


def monotonic_ms() -> float:
    return time.monotonic() * 1000.0


def wall_time_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def video_timecode(t_video_ms: float) -> str:
    if t_video_ms < 0:
        t_video_ms = 0.0
    total_ms = int(round(t_video_ms))
    minutes, remainder = divmod(total_ms, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


@dataclass(slots=True)
class Region:
    screen_x: int
    screen_y: int
    width: int
    height: int

    def even_sized(self) -> "Region":
        width = self.width - (self.width % 2)
        height = self.height - (self.height % 2)
        return Region(
            screen_x=self.screen_x,
            screen_y=self.screen_y,
            width=max(2, width),
            height=max(2, height),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "screen_x": self.screen_x,
            "screen_y": self.screen_y,
            "width": self.width,
            "height": self.height,
        }

    def contains(self, x: int, y: int) -> bool:
        return (
            self.screen_x <= x < self.screen_x + self.width
            and self.screen_y <= y < self.screen_y + self.height
        )

    def map_point(self, x: int, y: int) -> dict[str, Any]:
        region_x = x - self.screen_x
        region_y = y - self.screen_y
        inside = self.contains(x, y)
        return {
            "screen_x": x,
            "screen_y": y,
            "region_x": region_x,
            "region_y": region_y,
            "region_x_norm": round(region_x / self.width, 6) if self.width else None,
            "region_y_norm": round(region_y / self.height, 6) if self.height else None,
            "inside_region": inside,
        }


@dataclass(slots=True)
class TimingContext:
    session_id: str
    logger_start_monotonic_ms: float
    video_start_request_monotonic_ms: float | None = None
    video_zero_monotonic_ms: float | None = None
    recording_stop_monotonic_ms: float | None = None
    paused_duration_ms: float = 0.0

    def t_video_ms(self, t_monotonic_ms: float) -> float:
        zero = self.video_zero_monotonic_ms or self.logger_start_monotonic_ms
        return max(0.0, t_monotonic_ms - zero - self.paused_duration_ms)

    def timing_dict(self) -> dict[str, float | None]:
        return {
            "logger_start_monotonic_ms": round(self.logger_start_monotonic_ms, 3),
            "video_start_request_monotonic_ms": self._round(self.video_start_request_monotonic_ms),
            "video_zero_monotonic_ms": self._round(self.video_zero_monotonic_ms),
            "recording_stop_monotonic_ms": self._round(self.recording_stop_monotonic_ms),
            "paused_duration_ms": round(self.paused_duration_ms, 3),
        }

    @staticmethod
    def _round(value: float | None) -> float | None:
        if value is None or math.isnan(value):
            return None
        return round(value, 3)
