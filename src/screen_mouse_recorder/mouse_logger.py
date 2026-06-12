from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import queue
import threading
import time
from typing import Any, Callable

from .calibration import video_mapping
from .config import AppConfig
from .models import Region, TimingContext, monotonic_ms, video_timecode, wall_time_iso
from .storage import JsonlWriter


WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_QUIT = 0x0012
HC_ACTION = 0


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


LowLevelMouseProc = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


def _configure_win32_signatures() -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelMouseProc, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = wintypes.LPARAM
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD


@dataclass(slots=True)
class ButtonState:
    is_down: bool = False
    down_x: int = 0
    down_y: int = 0
    down_t_ms: float = 0.0
    dragging: bool = False


class MouseActivityLogger:
    def __init__(
        self,
        region: Region,
        timing: TimingContext,
        config: AppConfig,
        event_writer: JsonlWriter,
        sample_writer: JsonlWriter,
        calibration_data: dict[str, Any] | None = None,
        event_counter_start: int = 0,
        sample_counter_start: int = 0,
    ) -> None:
        self.region = region
        self.timing = timing
        self.config = config
        self.event_writer = event_writer
        self.sample_writer = sample_writer
        self.calibration_data = calibration_data
        self.event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=20_000)
        self.sample_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=20_000)
        self.stop_event = threading.Event()
        self._hook_ready = threading.Event()
        self._hook_error: BaseException | None = None
        self._hook_thread: threading.Thread | None = None
        self._sample_thread: threading.Thread | None = None
        self._event_writer_thread: threading.Thread | None = None
        self._sample_writer_thread: threading.Thread | None = None
        self._hook_handle = None
        self._hook_thread_id: int | None = None
        self._proc: Callable[..., int] | None = None
        self._event_counter = event_counter_start
        self._sample_counter = sample_counter_start
        self._states = {button: ButtonState() for button in ("left", "right", "middle")}
        self._last_click: dict[str, tuple[float, int, int] | None] = {button: None for button in self._states}

    def start(self) -> None:
        self.event_writer.open()
        self.sample_writer.open()
        self._event_writer_thread = threading.Thread(
            target=self._writer_loop,
            args=(self.event_queue, self.event_writer),
            name="mouse-event-writer",
            daemon=True,
        )
        self._sample_writer_thread = threading.Thread(
            target=self._writer_loop,
            args=(self.sample_queue, self.sample_writer),
            name="mouse-sample-writer",
            daemon=True,
        )
        self._sample_thread = None
        if self.config.record_mouse_samples or self.config.record_drag_events:
            self._sample_thread = threading.Thread(target=self._sample_loop, name="mouse-sampler", daemon=True)
        self._hook_thread = threading.Thread(target=self._hook_loop, name="mouse-hook", daemon=True)
        self._event_writer_thread.start()
        self._sample_writer_thread.start()
        if self._sample_thread is not None:
            self._sample_thread.start()
        self._hook_thread.start()
        if not self._hook_ready.wait(timeout=1.5):
            self.stop()
            raise RuntimeError("Mouse hook did not start within 1.5 seconds.")
        if self._hook_error is not None:
            error = self._hook_error
            self.stop()
            raise RuntimeError(f"Mouse hook failed to start: {error}") from error

    def stop(self) -> None:
        self.stop_event.set()
        self._unhook()
        if self._hook_thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
        for thread in (self._hook_thread, self._sample_thread):
            if thread:
                thread.join(timeout=2.0)
        self._enqueue_stop_signal(self.event_queue)
        self._enqueue_stop_signal(self.sample_queue)
        for thread in (self._event_writer_thread, self._sample_writer_thread):
            if thread:
                thread.join(timeout=3.0)
        self.event_writer.close()
        self.sample_writer.close()

    def emit_sync_marker(self, marker_id: str) -> dict[str, Any]:
        x, y = self._cursor_pos()
        event = self._make_event("sync_marker", x, y, source="time_sync", marker_id=marker_id)
        self._enqueue_event(event)
        return event

    @property
    def event_counter(self) -> int:
        return self._event_counter

    @property
    def sample_counter(self) -> int:
        return self._sample_counter

    def _hook_loop(self) -> None:
        _configure_win32_signatures()
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._hook_thread_id = kernel32.GetCurrentThreadId()

        @LowLevelMouseProc
        def proc(n_code: int, w_param: int, l_param: int) -> int:
            if n_code == HC_ACTION and not self.stop_event.is_set():
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                self._handle_hook_event(int(w_param), int(info.pt.x), int(info.pt.y), int(info.mouseData))
            return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        self._proc = proc
        self._hook_handle = user32.SetWindowsHookExW(WH_MOUSE_LL, proc, None, 0)
        if not self._hook_handle:
            self._hook_error = ctypes.WinError()
            self._hook_ready.set()
            return
        self._hook_ready.set()
        msg = MSG()
        while not self.stop_event.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._unhook()

    def _unhook(self) -> None:
        if self._hook_handle:
            ctypes.windll.user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None

    def _handle_hook_event(self, message: int, x: int, y: int, mouse_data: int) -> None:
        mapping = {
            WM_LBUTTONDOWN: ("left_down", "left"),
            WM_LBUTTONUP: ("left_up", "left"),
            WM_RBUTTONDOWN: ("right_down", "right"),
            WM_RBUTTONUP: ("right_up", "right"),
            WM_MBUTTONDOWN: ("middle_down", "middle"),
            WM_MBUTTONUP: ("middle_up", "middle"),
        }
        if message in mapping:
            event_type, button = mapping[message]
            self._handle_button(event_type, button, x, y)
            return
        if message == WM_MOUSEWHEEL:
            delta = ctypes.c_short((mouse_data >> 16) & 0xFFFF).value
            self._enqueue_event(self._make_event("wheel", x, y, source="mouse_hook", wheel_delta=delta))

    def _handle_button(self, event_type: str, button: str, x: int, y: int) -> None:
        now_ms = monotonic_ms()
        state = self._states[button]
        if event_type.endswith("_down"):
            state.is_down = True
            state.down_x = x
            state.down_y = y
            state.down_t_ms = now_ms
            state.dragging = False
            self._enqueue_event(self._make_event(event_type, x, y, button=button, source="mouse_hook", t_ms=now_ms))
            return

        if state.dragging:
            self._enqueue_event(self._make_event("drag_end", x, y, button=button, source="drag_detector", t_ms=now_ms))
        self._enqueue_event(self._make_event(event_type, x, y, button=button, source="mouse_hook", t_ms=now_ms))

        duration = now_ms - state.down_t_ms
        distance = ((x - state.down_x) ** 2 + (y - state.down_y) ** 2) ** 0.5
        if (
            state.is_down
            and not state.dragging
            and duration <= self.config.click_max_duration_ms
            and distance <= self.config.click_max_distance_px
        ):
            click = self._make_event(
                "click",
                x,
                y,
                button=button,
                source="click_synthesizer",
                t_ms=now_ms,
                duration_ms=round(duration, 3),
            )
            self._enqueue_event(click)
            last_click = self._last_click.get(button)
            if last_click is not None:
                last_t, last_x, last_y = last_click
                double_distance = ((x - last_x) ** 2 + (y - last_y) ** 2) ** 0.5
                if now_ms - last_t <= self.config.double_click_window_ms and double_distance <= self.config.click_max_distance_px:
                    self._enqueue_event(
                        self._make_event("double_click_candidate", x, y, button=button, source="click_synthesizer", t_ms=now_ms),
                    )
            self._last_click[button] = (now_ms, x, y)

        state.is_down = False
        state.dragging = False

    def _sample_loop(self) -> None:
        interval = 1.0 / max(1, self.config.sample_fps)
        while not self.stop_event.is_set():
            started = time.monotonic()
            x, y = self._cursor_pos()
            t_ms = monotonic_ms()
            sample = self._make_sample(x, y, t_ms=t_ms)
            self._enqueue_sample(sample)
            if self.config.record_drag_events:
                self._detect_drag_from_sample(x, y, t_ms)
            elapsed = time.monotonic() - started
            time.sleep(max(0.001, interval - elapsed))

    def _detect_drag_from_sample(self, x: int, y: int, t_ms: float) -> None:
        for button, state in self._states.items():
            if not state.is_down:
                continue
            distance = ((x - state.down_x) ** 2 + (y - state.down_y) ** 2) ** 0.5
            if not state.dragging and distance >= self.config.drag_min_distance_px:
                state.dragging = True
                self._enqueue_event(self._make_event("drag_start", state.down_x, state.down_y, button=button, source="drag_detector", t_ms=state.down_t_ms))
            if state.dragging:
                self._enqueue_event(self._make_event("drag_move", x, y, button=button, source="drag_detector", t_ms=t_ms))

    def _make_event(self, event_type: str, x: int, y: int, source: str, t_ms: float | None = None, **extra: Any) -> dict[str, Any]:
        self._event_counter += 1
        t_monotonic_ms = t_ms if t_ms is not None else monotonic_ms()
        t_video_ms = self.timing.t_video_ms(t_monotonic_ms)
        row = {
            "schema_version": "1.0",
            "session_id": self.timing.session_id,
            "event_id": f"evt_{self._event_counter:06d}",
            "event_type": event_type,
            "wall_time": wall_time_iso(),
            "t_monotonic_ms": round(t_monotonic_ms, 3),
            "t_video_ms": round(t_video_ms, 3),
            "video_timecode": video_timecode(t_video_ms),
            **self.region.map_point(x, y),
            **video_mapping(self.region, x, y, self.calibration_data),
            "source": source,
        }
        row.update(extra)
        return row

    def _make_sample(self, x: int, y: int, t_ms: float) -> dict[str, Any]:
        self._sample_counter += 1
        t_video_ms = self.timing.t_video_ms(t_ms)
        return {
            "schema_version": "1.0",
            "session_id": self.timing.session_id,
            "sample_id": f"smp_{self._sample_counter:06d}",
            "event_type": "move_sample",
            "wall_time": wall_time_iso(),
            "t_monotonic_ms": round(t_ms, 3),
            "t_video_ms": round(t_video_ms, 3),
            "video_timecode": video_timecode(t_video_ms),
            **self.region.map_point(x, y),
            **video_mapping(self.region, x, y, self.calibration_data),
            "source": "cursor_sampler",
        }

    @staticmethod
    def _writer_loop(target_queue: queue.Queue[dict[str, Any] | None], writer: JsonlWriter) -> None:
        while True:
            row = target_queue.get()
            if row is None:
                return
            writer.write(row)

    def _enqueue_event(self, row: dict[str, Any]) -> None:
        event_type = row.get("event_type")
        click_event_types = {
            "left_down",
            "left_up",
            "right_down",
            "right_up",
            "middle_down",
            "middle_up",
            "click",
            "double_click_candidate",
        }
        drag_event_types = {"drag_start", "drag_move", "drag_end"}
        if event_type in click_event_types and not self.config.record_click_events:
            return
        if event_type == "wheel" and not self.config.record_wheel_events:
            return
        if event_type in drag_event_types and not self.config.record_drag_events:
            return
        if not self.config.record_outside_region and not self._row_inside_video_region(row) and row.get("event_type") != "sync_marker":
            return
        self._enqueue(self.event_queue, row)

    def _enqueue_sample(self, row: dict[str, Any]) -> None:
        if not self.config.record_mouse_samples:
            return
        if not self.config.record_outside_region and not self._row_inside_video_region(row):
            return
        self._enqueue(self.sample_queue, row)

    @staticmethod
    def _row_inside_video_region(row: dict[str, Any]) -> bool:
        if "inside_video_region" in row:
            return bool(row["inside_video_region"])
        return bool(row.get("inside_region"))

    @staticmethod
    def _enqueue(target_queue: queue.Queue[dict[str, Any] | None], row: dict[str, Any]) -> None:
        try:
            target_queue.put_nowait(row)
        except queue.Full:
            pass

    @staticmethod
    def _enqueue_stop_signal(target_queue: queue.Queue[dict[str, Any] | None], timeout_seconds: float = 3.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                target_queue.put(None, timeout=0.1)
                return
            except queue.Full:
                if time.monotonic() >= deadline:
                    return

    @staticmethod
    def _cursor_pos() -> tuple[int, int]:
        point = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return (int(point.x), int(point.y))
