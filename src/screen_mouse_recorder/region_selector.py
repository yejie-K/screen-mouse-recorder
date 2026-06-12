from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk

from .calibration import (
    DEFAULT_CALIBRATION_CLICK_TOLERANCE_PX,
    DEFAULT_CALIBRATION_RESIDUAL_WARNING_PX,
    build_calibration_result,
)
from .models import Region


SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


def virtual_screen_geometry() -> tuple[int, int, int, int]:
    if ctypes.windll:
        user32 = ctypes.windll.user32
        return (
            int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
        )
    return (0, 0, 1280, 720)


def cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return (int(point.x), int(point.y))


class RegionSelector:
    def __init__(self, parent: tk.Tk) -> None:
        self.parent = parent
        self.result: Region | None = None
        self._start_x = 0
        self._start_y = 0
        self._rect_id: int | None = None
        self._text_id: int | None = None
        self._origin_x, self._origin_y, self._width, self._height = virtual_screen_geometry()

    def select(self) -> Region | None:
        window = tk.Toplevel(self.parent)
        window.title("Select Recording Region")
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", 0.28)
        window.geometry(f"{self._width}x{self._height}+{self._origin_x}+{self._origin_y}")
        window.configure(bg="black")
        window.focus_force()

        canvas = tk.Canvas(window, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            24,
            24,
            text="Drag to select recording region. Esc cancels.",
            fill="white",
            anchor="nw",
            font=("Segoe UI", 14, "bold"),
        )

        def clamp_event(event: tk.Event) -> tuple[int, int]:
            return (max(0, min(int(event.x), self._width)), max(0, min(int(event.y), self._height)))

        def on_down(event: tk.Event) -> None:
            self._start_x, self._start_y = clamp_event(event)
            if self._rect_id is not None:
                canvas.delete(self._rect_id)
            if self._text_id is not None:
                canvas.delete(self._text_id)
            self._rect_id = canvas.create_rectangle(
                self._start_x,
                self._start_y,
                self._start_x,
                self._start_y,
                outline="#00e5ff",
                width=3,
            )
            self._text_id = canvas.create_text(
                self._start_x + 8,
                self._start_y + 8,
                text="",
                fill="#ffffff",
                anchor="nw",
                font=("Segoe UI", 12, "bold"),
            )

        def on_drag(event: tk.Event) -> None:
            if self._rect_id is None:
                return
            x, y = clamp_event(event)
            x1, y1 = min(self._start_x, x), min(self._start_y, y)
            x2, y2 = max(self._start_x, x), max(self._start_y, y)
            canvas.coords(self._rect_id, x1, y1, x2, y2)
            if self._text_id is not None:
                screen_x = self._origin_x + x1
                screen_y = self._origin_y + y1
                canvas.coords(self._text_id, x1 + 8, y1 + 8)
                canvas.itemconfigure(
                    self._text_id,
                    text=f"x={screen_x} y={screen_y}  {x2 - x1}x{y2 - y1}",
                )

        def on_up(event: tk.Event) -> None:
            x, y = clamp_event(event)
            x1, y1 = min(self._start_x, x), min(self._start_y, y)
            x2, y2 = max(self._start_x, x), max(self._start_y, y)
            width = x2 - x1
            height = y2 - y1
            if width >= 16 and height >= 16:
                self.result = Region(
                    screen_x=self._origin_x + x1,
                    screen_y=self._origin_y + y1,
                    width=width,
                    height=height,
                ).even_sized()
            window.destroy()

        def on_cancel(_event: tk.Event | None = None) -> None:
            self.result = None
            window.destroy()

        canvas.bind("<ButtonPress-1>", on_down)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_up)
        window.bind("<Escape>", on_cancel)
        self.parent.wait_window(window)
        return self.result


class RecordingRegionOverlay:
    def __init__(self, parent: tk.Tk, region: Region) -> None:
        self.parent = parent
        self.region = region
        self.windows: list[tk.Toplevel] = []
        self.label: tk.Label | None = None
        self._build()
        self.set_mode("ready")

    def _build(self) -> None:
        thickness = 5
        x = self.region.screen_x
        y = self.region.screen_y
        width = self.region.width
        height = self.region.height
        segments = [
            (x, y, width, thickness),
            (x, y + height - thickness, width, thickness),
            (x, y, thickness, height),
            (x + width - thickness, y, thickness, height),
        ]
        for index, (sx, sy, sw, sh) in enumerate(segments):
            window = tk.Toplevel(self.parent)
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.geometry(f"{sw}x{sh}+{sx}+{sy}")
            window.configure(bg="#24a0ed")
            if index == 0:
                self.label = tk.Label(
                    window,
                    text="READY",
                    fg="white",
                    bg="#24a0ed",
                    font=("Segoe UI", 9, "bold"),
                    padx=8,
                )
                self.label.pack(side="left", fill="y")
            self.windows.append(window)

    def set_mode(self, mode: str) -> None:
        color = "#d83b3b" if mode == "recording" else "#24a0ed"
        text = "REC" if mode == "recording" else "READY"
        for window in self.windows:
            window.configure(bg=color)
            window.lift()
        if self.label is not None:
            self.label.configure(text=text, bg=color)

    def destroy(self) -> None:
        for window in self.windows:
            if window.winfo_exists():
                window.destroy()
        self.windows = []
        self.label = None


def show_sync_marker(parent: tk.Tk, region: Region, label: str = "SYNC_001", duration_ms: int = 1200) -> None:
    marker = tk.Toplevel(parent)
    marker.overrideredirect(True)
    marker.attributes("-topmost", True)
    marker.configure(bg="#ff1744")
    width = min(max(220, region.width // 2), region.width)
    height = min(max(90, region.height // 5), region.height)
    x = region.screen_x + max(0, (region.width - width) // 2)
    y = region.screen_y + max(0, (region.height - height) // 2)
    marker.geometry(f"{width}x{height}+{x}+{y}")
    text = tk.Label(
        marker,
        text=f"CALIBRATION\n{label}",
        fg="white",
        bg="#ff1744",
        font=("Segoe UI", 18, "bold"),
        justify="center",
    )
    text.pack(fill="both", expand=True)
    marker.after(duration_ms, marker.destroy)


def run_click_calibration(
    parent: tk.Tk,
    region: Region,
    click_tolerance_px: int = DEFAULT_CALIBRATION_CLICK_TOLERANCE_PX,
    residual_warning_px: int = DEFAULT_CALIBRATION_RESIDUAL_WARNING_PX,
) -> dict | None:
    origin_x, origin_y, screen_width, screen_height = virtual_screen_geometry()
    inset = max(8, min(24, min(region.width, region.height) // 12))
    targets = [
        ("top_left", region.screen_x + inset, region.screen_y + inset, "左上"),
        ("top_right", region.screen_x + region.width - inset, region.screen_y + inset, "右上"),
        ("bottom_left", region.screen_x + inset, region.screen_y + region.height - inset, "左下"),
        ("bottom_right", region.screen_x + region.width - inset, region.screen_y + region.height - inset, "右下"),
        ("center", region.screen_x + region.width // 2, region.screen_y + region.height // 2, "中心"),
    ]
    clicks: list[dict] = []
    index = 0

    window = tk.Toplevel(parent)
    window.title("Mouse Calibration")
    window.overrideredirect(True)
    window.attributes("-topmost", True)
    window.attributes("-alpha", 0.82)
    window.geometry(f"{screen_width}x{screen_height}+{origin_x}+{origin_y}")
    window.configure(bg="#101820")
    window.focus_force()

    canvas = tk.Canvas(window, bg="#101820", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    result: dict | None = None

    def draw_target() -> None:
        canvas.delete("all")
        target_id, expected_x, expected_y, label = targets[index]
        local_x = expected_x - origin_x
        local_y = expected_y - origin_y
        canvas.create_rectangle(
            region.screen_x - origin_x,
            region.screen_y - origin_y,
            region.screen_x - origin_x + region.width,
            region.screen_y - origin_y + region.height,
            outline="#24a0ed",
            width=4,
        )
        radius = 16
        canvas.create_oval(
            local_x - radius,
            local_y - radius,
            local_x + radius,
            local_y + radius,
            outline="#ff1744",
            width=4,
        )
        canvas.create_line(local_x - 28, local_y, local_x + 28, local_y, fill="#ff1744", width=3)
        canvas.create_line(local_x, local_y - 28, local_x, local_y + 28, fill="#ff1744", width=3)
        canvas.create_text(
            28,
            28,
            text=f"坐标对应检查 {index + 1}/5：请点击录制框内 {label} 附近。Esc 取消。",
            fill="white",
            anchor="nw",
            font=("Segoe UI", 16, "bold"),
        )
        canvas.create_text(
            local_x,
            local_y + 44,
            text=label,
            fill="white",
            anchor="n",
            font=("Segoe UI", 13, "bold"),
        )

    def on_click(event: tk.Event) -> None:
        nonlocal index, result
        target_id, expected_x, expected_y, label = targets[index]
        actual_x, actual_y = cursor_position()
        event_x = int(event.x_root)
        event_y = int(event.y_root)
        dx = actual_x - expected_x
        dy = actual_y - expected_y
        clicks.append(
            {
                "target_id": target_id,
                "label": label,
                "expected_screen_x": expected_x,
                "expected_screen_y": expected_y,
                "actual_screen_x": actual_x,
                "actual_screen_y": actual_y,
                "tk_event_screen_x": event_x,
                "tk_event_screen_y": event_y,
                "dx": dx,
                "dy": dy,
                "distance_px": round((dx * dx + dy * dy) ** 0.5, 3),
                "inside_region": region.contains(actual_x, actual_y),
            }
        )
        index += 1
        if index >= len(targets):
            result = build_calibration_result(region, clicks, click_tolerance_px, residual_warning_px)
            window.destroy()
        else:
            draw_target()

    def on_cancel(_event: tk.Event | None = None) -> None:
        nonlocal result
        result = {
            "schema_version": "1.0",
            "method": "five_point_click",
            "region": region.to_dict(),
            "points": clicks,
            "completed": False,
        }
        window.destroy()

    canvas.bind("<ButtonPress-1>", on_click)
    window.bind("<Escape>", on_cancel)
    draw_target()
    parent.wait_window(window)
    return result
