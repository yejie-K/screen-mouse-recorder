from __future__ import annotations

import tkinter as tk
from tkinter import ttk


COLORS = {
    "app_bg": "#edf1f4",
    "panel_bg": "#f8fafb",
    "panel_alt": "#eef3f6",
    "panel_row": "#ffffff",
    "text": "#17212b",
    "text_secondary": "#263238",
    "muted": "#60717d",
    "border": "#c7d0d8",
    "border_soft": "#dfe7ec",
    "tab_active": "#263238",
    "tab_idle": "#dfe7ec",
    "tab_hover": "#d2dce3",
    "blue": "#1f6fb2",
    "green": "#1f9d55",
    "yellow": "#f0b429",
    "red": "#d83b3b",
    "warning_bg": "#fff3cd",
    "warning_text": "#5c4400",
}

FONT_UI = ("Segoe UI", 10)
FONT_UI_BOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_SMALL_BOLD = ("Segoe UI", 8, "bold")
FONT_TITLE = ("Segoe UI", 19, "bold")
FONT_TIMER = ("Consolas", 38, "bold")


def apply_app_theme(root: tk.Tk) -> ttk.Style:
    root.configure(bg=COLORS["app_bg"])
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("App.TFrame", background=COLORS["app_bg"])
    style.configure("Panel.TFrame", background=COLORS["panel_bg"])
    style.configure("Panel.TLabelframe", background=COLORS["panel_bg"], bordercolor=COLORS["border"], relief="solid")
    style.configure(
        "Panel.TLabelframe.Label",
        background=COLORS["panel_bg"],
        foreground=COLORS["text_secondary"],
        font=FONT_UI_BOLD,
    )
    style.configure("App.TLabel", background=COLORS["app_bg"], foreground=COLORS["text_secondary"], font=FONT_UI)
    style.configure("Panel.TLabel", background=COLORS["panel_bg"], foreground=COLORS["text_secondary"], font=FONT_UI)
    style.configure("Muted.TLabel", background=COLORS["panel_bg"], foreground=COLORS["muted"], font=FONT_SMALL)
    style.configure("Title.TLabel", background=COLORS["app_bg"], foreground=COLORS["text"], font=FONT_TITLE)
    style.configure("Timer.TLabel", background=COLORS["panel_bg"], foreground=COLORS["text"], font=FONT_TIMER)
    style.configure(
        "TButton",
        font=FONT_UI,
        padding=(10, 6),
        background=COLORS["panel_row"],
        foreground=COLORS["text_secondary"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["panel_row"],
        darkcolor=COLORS["border"],
        relief="solid",
        focusthickness=0,
    )
    style.map(
        "TButton",
        background=[
            ("disabled", "#e7edf1"),
            ("pressed", COLORS["border_soft"]),
            ("active", COLORS["panel_alt"]),
            ("!disabled", COLORS["panel_row"]),
        ],
        foreground=[("disabled", "#9aa8b1"), ("!disabled", COLORS["text_secondary"])],
        bordercolor=[("active", "#9fb5c5"), ("!active", COLORS["border"])],
        lightcolor=[("active", COLORS["panel_alt"]), ("!active", COLORS["panel_row"])],
        darkcolor=[("active", "#9fb5c5"), ("!active", COLORS["border"])],
    )
    style.configure("TCheckbutton", background=COLORS["panel_bg"], foreground=COLORS["text_secondary"], font=FONT_UI)

    style.layout(
        "Option.TCheckbutton",
        [
            (
                "Checkbutton.padding",
                {
                    "sticky": "nswe",
                    "children": [
                        ("Checkbutton.indicator", {"side": "left", "sticky": ""}),
                        ("Checkbutton.label", {"side": "left", "sticky": "w"}),
                    ],
                },
            )
        ],
    )
    style.configure("Option.TCheckbutton", background=COLORS["panel_bg"], foreground=COLORS["text_secondary"], font=FONT_UI)
    style.map(
        "Option.TCheckbutton",
        background=[("active", COLORS["panel_bg"]), ("!active", COLORS["panel_bg"])],
        foreground=[("disabled", "#9aa8b1"), ("!disabled", COLORS["text_secondary"])],
    )

    style.configure("TNotebook", background=COLORS["panel_bg"], borderwidth=0)
    style.configure("TNotebook.Tab", font=FONT_UI, padding=(12, 6))
    style.configure("Settings.TNotebook", background=COLORS["panel_bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.layout(
        "Settings.TNotebook.Tab",
        [
            (
                "Notebook.tab",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Notebook.padding",
                            {
                                "side": "top",
                                "sticky": "nswe",
                                "children": [("Notebook.label", {"side": "top", "sticky": ""})],
                            },
                        )
                    ],
                },
            )
        ],
    )
    style.configure(
        "Settings.TNotebook.Tab",
        font=FONT_UI,
        width=12,
        padding=(14, 7),
        borderwidth=0,
        relief="flat",
        background=COLORS["tab_idle"],
        foreground=COLORS["text_secondary"],
        lightcolor=COLORS["tab_idle"],
        darkcolor=COLORS["tab_idle"],
        bordercolor=COLORS["tab_idle"],
    )
    style.map(
        "Settings.TNotebook.Tab",
        background=[("selected", COLORS["tab_active"]), ("active", COLORS["tab_hover"]), ("!selected", COLORS["tab_idle"])],
        foreground=[("selected", "white"), ("!selected", COLORS["text_secondary"])],
        lightcolor=[("selected", COLORS["tab_active"]), ("!selected", COLORS["tab_idle"])],
        darkcolor=[("selected", COLORS["tab_active"]), ("!selected", COLORS["tab_idle"])],
        bordercolor=[("selected", COLORS["tab_active"]), ("!selected", COLORS["tab_idle"])],
    )
    return style
