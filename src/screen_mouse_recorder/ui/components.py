from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from .theme import COLORS, FONT_SMALL, FONT_UI, FONT_UI_BOLD


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
    frame.configure(height=58)
    frame.pack_propagate(False)
    tk.Label(frame, textvariable=variable, bg=COLORS["panel_alt"], fg=COLORS["text"], font=value_font).pack(pady=(7, 0))
    tk.Label(frame, text=label, bg=COLORS["panel_alt"], fg=COLORS["muted"], font=label_font).pack(pady=(0, 6))
    return frame


class ToggleRow(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        root: tk.Tk,
        text: str,
        variable: tk.BooleanVar,
        tooltip: str,
        *,
        command: Callable[[], None] | None = None,
        strong: bool = False,
    ) -> None:
        super().__init__(
            parent,
            bg=COLORS["panel_row"],
            highlightbackground=COLORS["border_soft"],
            highlightthickness=1,
            cursor="hand2",
        )
        self._state = "normal"
        self.root = root
        self.variable = variable
        self.command = command
        self.text = text
        self.strong = strong
        self.configure(height=42 if strong else 36)
        self.grid_propagate(False)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.indicator = tk.Label(
            self,
            bg=COLORS["panel_row"],
            fg=COLORS["muted"],
            width=2,
            anchor="center",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self.indicator.grid(row=0, column=0, sticky="ns", padx=(10, 6), pady=0)

        self.label = tk.Label(
            self,
            text=text,
            bg=COLORS["panel_row"],
            fg=COLORS["text_secondary"],
            anchor="w",
            justify="left",
            font=FONT_UI_BOLD if strong else FONT_UI,
            cursor="hand2",
        )
        self.label.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=0)

        self.variable.trace_add("write", lambda *_args: self._sync_state())
        for target in (self, self.indicator, self.label):
            target.bind("<ButtonRelease-1>", self._toggle_from_event)
            Tooltip(target, tooltip)
        self._sync_state()

    def _toggle_from_event(self, _event: tk.Event | None = None) -> str:
        if self._state != "disabled":
            self.variable.set(not bool(self.variable.get()))
            if self.command is not None:
                self.command()
        self.root.focus_set()
        return "break"

    def _sync_state(self) -> None:
        selected = bool(self.variable.get())
        bg = COLORS["green_soft"] if selected else COLORS["panel_row"]
        fg = COLORS["text"] if selected else COLORS["text_secondary"]
        indicator_fg = COLORS["green"] if selected else COLORS["muted"]
        border = COLORS["green"] if selected else COLORS["border_soft"]
        self.configure(bg=bg, highlightbackground=border)
        self.indicator.configure(text="✓" if selected else "□", bg=bg, fg=indicator_fg)
        self.label.configure(bg=bg, fg=fg)

    def configure(self, cnf: dict[str, object] | None = None, **kwargs: object) -> object:
        state = None
        if cnf is not None and "state" in cnf:
            cnf = dict(cnf)
            state = cnf.pop("state")
        if "state" in kwargs:
            state = kwargs.pop("state")
        result = super().configure(cnf, **kwargs)
        if state is not None and hasattr(self, "indicator"):
            self._state = str(state)
            disabled = self._state == "disabled"
            cursor = "" if disabled else "hand2"
            self.indicator.configure(fg="#9a9a9a" if disabled else (COLORS["green"] if self.variable.get() else COLORS["muted"]), cursor=cursor)
            self.label.configure(fg="#9a9a9a" if disabled else (COLORS["text"] if self.variable.get() else COLORS["text_secondary"]), cursor=cursor)
            super().configure(cursor=cursor)
        return result

    def cget(self, key: str) -> object:
        if key == "state":
            return self._state
        return super().cget(key)


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
) -> ToggleRow:
    widget = ToggleRow(parent, root, text, variable, tooltip, command=command)
    widget.grid(row=row, column=column, sticky="ew", padx=(0, 0), pady=2)
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
    widget = ToggleRow(parent, root, text, variable, tooltip, command=command, strong=True)
    widget.grid(row=row, column=0, sticky="ew", pady=(12, 0))
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
        bd=0,
        highlightthickness=1,
        highlightbackground=color,
        highlightcolor=color,
        width=4,
        height=1,
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
    ttk.Label(parent, text=text, style="Panel.TLabel").grid(row=row, column=column, sticky="w", pady=5, padx=(0, 6))
    spinbox = ttk.Spinbox(parent, textvariable=variable, from_=from_, to=to, width=8)
    spinbox.grid(row=row, column=column + 1, sticky="ew", padx=(0, 12), pady=5)
    return spinbox
