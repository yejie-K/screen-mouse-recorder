from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from .theme import COLORS, FONT_SMALL, FONT_SMALL_BOLD, FONT_UI, FONT_UI_BOLD


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event: tk.Event | None = None) -> None:
        if self.window is not None:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + 20
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.geometry(f"+{x}+{y}")
        label = tk.Label(
            self.window,
            text=self.text,
            bg=COLORS["text"],
            fg="white",
            padx=10,
            pady=7,
            justify="left",
            wraplength=280,
            font=FONT_SMALL,
        )
        label.pack()

    def hide(self, _event: tk.Event | None = None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


def metric_card(
    parent: tk.Widget,
    column: int,
    label: str,
    variable: tk.StringVar,
    *,
    value_font: tuple[str, int, str] = ("Segoe UI", 14, "bold"),
    label_font: tuple[str, int] = ("Segoe UI", 8),
    padx: tuple[int, int] = (6, 0),
) -> tk.Frame:
    frame = tk.Frame(parent, bg=COLORS["panel_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
    frame.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else padx[0], padx[1]))
    tk.Label(frame, textvariable=variable, bg=COLORS["panel_alt"], fg=COLORS["text"], font=value_font).pack(pady=(8, 0))
    tk.Label(frame, text=label, bg=COLORS["panel_alt"], fg=COLORS["muted"], font=label_font).pack(pady=(0, 8))
    return frame


def analysis_output_row(
    parent: tk.Widget,
    row: int,
    column: int,
    title: str,
    filename: str,
    status_var: tk.StringVar,
) -> tk.Label:
    frame = tk.Frame(parent, bg=COLORS["panel_row"], highlightbackground=COLORS["border"], highlightthickness=1)
    frame.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0), pady=(0, 8))
    frame.columnconfigure(1, weight=1)

    badge = tk.Label(
        frame,
        textvariable=status_var,
        bg=COLORS["border_soft"],
        fg=COLORS["text_secondary"],
        width=6,
        font=FONT_SMALL_BOLD,
    )
    badge.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(10, 8), pady=8)

    tk.Label(frame, text=title, bg=COLORS["panel_row"], fg=COLORS["text"], anchor="w", font=FONT_UI).grid(
        row=0, column=1, sticky="ew", pady=(7, 0)
    )
    tk.Label(frame, text=filename, bg=COLORS["panel_row"], fg=COLORS["muted"], anchor="w", font=("Segoe UI", 8)).grid(
        row=1, column=1, sticky="ew", pady=(0, 7)
    )
    return badge


def option_checkbutton(
    parent: tk.Widget,
    root: tk.Tk,
    row: int,
    text: str,
    variable: tk.BooleanVar,
    tooltip: str,
    *,
    column: int = 0,
    command: Callable[[], None] | None = None,
) -> tk.Checkbutton:
    frame = tk.Frame(parent, bg=COLORS["panel_row"], highlightbackground=COLORS["border_soft"], highlightthickness=1)
    frame.grid(row=row, column=column, sticky="ew", padx=(0, 8 if column == 0 else 0), pady=4)
    frame.columnconfigure(0, weight=1)
    widget = tk.Checkbutton(
        frame,
        text=text,
        variable=variable,
        command=command,
        takefocus=False,
        highlightthickness=0,
        bd=0,
        bg=COLORS["panel_row"],
        fg=COLORS["text_secondary"],
        activebackground=COLORS["panel_row"],
        activeforeground=COLORS["text"],
        selectcolor=COLORS["panel_row"],
        disabledforeground="#9aa8b1",
        anchor="w",
        justify="left",
        font=FONT_UI,
        padx=8,
        pady=8,
        cursor="hand2",
    )
    widget.grid(row=0, column=0, sticky="ew")

    def sync_state(*_args: object) -> None:
        selected = bool(variable.get())
        bg = "#edf7f1" if selected else COLORS["panel_row"]
        fg = COLORS["text"] if selected else COLORS["text_secondary"]
        frame.configure(bg=bg, highlightbackground=COLORS["green"] if selected else COLORS["border_soft"])
        widget.configure(bg=bg, fg=fg, activebackground=bg, selectcolor=bg)

    sync_state()
    variable.trace_add("write", sync_state)
    widget.bind("<ButtonRelease-1>", lambda _event: root.focus_set(), add="+")
    frame.configure(cursor="hand2")

    def invoke_from_frame(_event: tk.Event) -> str:
        if str(widget.cget("state")) != "disabled":
            widget.invoke()
        root.focus_set()
        return "break"

    frame.bind("<ButtonRelease-1>", invoke_from_frame)
    Tooltip(widget, tooltip)
    return widget


def confirmation_checkbutton(
    parent: tk.Widget,
    root: tk.Tk,
    row: int,
    text: str,
    variable: tk.BooleanVar,
    tooltip: str,
    *,
    command: Callable[[], None] | None = None,
) -> tk.Checkbutton:
    frame = tk.Frame(parent, bg=COLORS["panel_row"], highlightbackground=COLORS["border"], highlightthickness=1)
    frame.grid(row=row, column=0, sticky="ew", pady=(12, 0))
    frame.columnconfigure(1, weight=1)

    widget = tk.Checkbutton(
        frame,
        variable=variable,
        command=command,
        takefocus=False,
        highlightthickness=0,
        bd=0,
        bg=COLORS["panel_row"],
        activebackground=COLORS["panel_row"],
        selectcolor=COLORS["panel_row"],
        disabledforeground="#9aa8b1",
        cursor="hand2",
    )
    widget.grid(row=0, column=0, sticky="ns", padx=(10, 6), pady=10)

    label = tk.Label(
        frame,
        text=text,
        bg=COLORS["panel_row"],
        fg=COLORS["text_secondary"],
        anchor="w",
        font=FONT_UI_BOLD,
        cursor="hand2",
    )
    label.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)

    def sync_state(*_args: object) -> None:
        selected = bool(variable.get())
        bg = "#edf7f1" if selected else COLORS["panel_row"]
        fg = COLORS["text"] if selected else COLORS["text_secondary"]
        border = COLORS["green"] if selected else COLORS["border"]
        frame.configure(bg=bg, highlightbackground=border, cursor="hand2")
        widget.configure(bg=bg, activebackground=bg, selectcolor=bg)
        label.configure(bg=bg, fg=fg)

    def invoke_from_anywhere(_event: tk.Event) -> str:
        if str(widget.cget("state")) != "disabled":
            widget.invoke()
        root.focus_set()
        return "break"

    sync_state()
    variable.trace_add("write", sync_state)
    for target in (frame, label):
        target.bind("<ButtonRelease-1>", invoke_from_anywhere)
    widget.bind("<ButtonRelease-1>", lambda _event: root.focus_set(), add="+")
    Tooltip(frame, tooltip)
    Tooltip(label, tooltip)
    return widget


def transport_button(parent: tk.Widget, text: str, command: Callable[[], None], color: str) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=color,
        fg="white",
        activebackground=color,
        activeforeground="white",
        disabledforeground="#e4eaee",
        relief="flat",
        width=4,
        height=2,
        font=("Segoe UI", 18, "bold"),
        cursor="hand2",
    )


def number_field(
    parent: tk.Widget,
    row: int,
    column: int,
    text: str,
    variable: tk.IntVar,
    from_: int,
    to: int,
) -> ttk.Spinbox:
    ttk.Label(parent, text=text, style="Panel.TLabel").grid(row=row, column=column, sticky="w", pady=4)
    spinbox = ttk.Spinbox(parent, textvariable=variable, from_=from_, to=to, width=8)
    spinbox.grid(row=row, column=column + 1, sticky="w", padx=(8, 18), pady=4)
    return spinbox
