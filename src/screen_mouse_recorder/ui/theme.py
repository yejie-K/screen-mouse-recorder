from __future__ import annotations

import tkinter as tk
from tkinter import ttk


COLORS = {
    "app_bg": "#f3f3f3",
    "panel_bg": "#ffffff",
    "panel_alt": "#f7f7f7",
    "panel_row": "#ffffff",
    "text": "#1f1f1f",
    "text_secondary": "#323130",
    "muted": "#6b6b6b",
    "border": "#d0d0d0",
    "border_soft": "#e5e5e5",
    "tab_active": "#ffffff",
    "tab_idle": "#ededed",
    "tab_hover": "#f8f8f8",
    "tab_pulse": "#eaf3ff",
    "blue": "#0067c0",
    "blue_soft": "#eaf3ff",
    "green": "#107c10",
    "green_soft": "#ecf7ec",
    "yellow": "#f9c23c",
    "red": "#c42b1c",
    "red_soft": "#fdf3f2",
    "warning_bg": "#fff3cd",
    "warning_text": "#5c4400",
}

FONT_UI = ("Segoe UI", 10)
FONT_UI_BOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_SMALL_BOLD = ("Segoe UI", 8, "bold")
FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_TIMER = ("Consolas", 36, "bold")


def apply_app_theme(root: tk.Tk) -> ttk.Style:
    root.configure(bg=COLORS["app_bg"])
    root.option_add("*Font", FONT_UI)
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("App.TFrame", background=COLORS["app_bg"])
    style.configure("TabPage.TFrame", background=COLORS["app_bg"])
    style.configure("TabPagePulse.TFrame", background=COLORS["tab_pulse"])
    style.configure("Panel.TFrame", background=COLORS["panel_bg"])
    style.configure(
        "Panel.TLabelframe",
        background=COLORS["panel_bg"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["panel_bg"],
        darkcolor=COLORS["border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "Panel.TLabelframe.Label",
        background=COLORS["app_bg"],
        foreground=COLORS["text_secondary"],
        font=FONT_UI_BOLD,
    )
    style.configure("App.TLabel", background=COLORS["app_bg"], foreground=COLORS["text_secondary"], font=FONT_UI)
    style.configure("Panel.TLabel", background=COLORS["panel_bg"], foreground=COLORS["text_secondary"], font=FONT_UI)
    style.configure("Muted.TLabel", background=COLORS["panel_bg"], foreground=COLORS["muted"], font=FONT_SMALL)
    style.configure("Title.TLabel", background=COLORS["app_bg"], foreground=COLORS["text"], font=FONT_TITLE)
    style.configure("Timer.TLabel", background=COLORS["panel_bg"], foreground=COLORS["text"], font=FONT_TIMER)
    style.configure(
        "TEntry",
        font=FONT_UI,
        padding=(8, 5),
        fieldbackground=COLORS["panel_row"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["panel_row"],
        darkcolor=COLORS["border"],
        insertcolor=COLORS["text"],
        relief="solid",
    )
    style.map(
        "TEntry",
        fieldbackground=[("readonly", "#fafafa"), ("disabled", "#f0f0f0"), ("!disabled", COLORS["panel_row"])],
        foreground=[("disabled", "#9a9a9a"), ("!disabled", COLORS["text"])],
        bordercolor=[("focus", COLORS["blue"]), ("!focus", COLORS["border"])],
    )
    style.configure(
        "TCombobox",
        font=FONT_UI,
        padding=(8, 5),
        fieldbackground=COLORS["panel_row"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        arrowcolor=COLORS["text_secondary"],
        relief="solid",
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLORS["panel_row"]), ("disabled", "#f0f0f0")],
        foreground=[("disabled", "#9a9a9a"), ("!disabled", COLORS["text"])],
        bordercolor=[("focus", COLORS["blue"]), ("!focus", COLORS["border"])],
    )
    style.configure(
        "TSpinbox",
        font=FONT_UI,
        padding=(8, 5),
        fieldbackground=COLORS["panel_row"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        relief="solid",
    )
    style.configure(
        "TButton",
        font=FONT_UI,
        padding=(12, 6),
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
            ("disabled", "#f0f0f0"),
            ("pressed", COLORS["border_soft"]),
            ("active", COLORS["panel_alt"]),
            ("!disabled", COLORS["panel_row"]),
        ],
        foreground=[("disabled", "#9a9a9a"), ("!disabled", COLORS["text_secondary"])],
        bordercolor=[("focus", COLORS["blue"]), ("active", "#bdbdbd"), ("!active", COLORS["border"])],
        lightcolor=[("active", COLORS["panel_alt"]), ("!active", COLORS["panel_row"])],
        darkcolor=[("active", "#bdbdbd"), ("!active", COLORS["border"])],
    )
    style.configure(
        "Primary.TButton",
        font=FONT_UI_BOLD,
        padding=(14, 7),
        background=COLORS["blue"],
        foreground="white",
        bordercolor=COLORS["blue"],
        lightcolor=COLORS["blue"],
        darkcolor=COLORS["blue"],
        relief="solid",
    )
    style.map(
        "Primary.TButton",
        background=[("disabled", "#c7c7c7"), ("pressed", "#004e8c"), ("active", "#005a9e"), ("!disabled", COLORS["blue"])],
        foreground=[("disabled", "#f0f0f0"), ("!disabled", "white")],
        bordercolor=[("!disabled", COLORS["blue"]), ("disabled", "#c7c7c7")],
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

    style.configure("TNotebook", background=COLORS["app_bg"], borderwidth=0)
    style.configure("TNotebook.Tab", font=FONT_UI, padding=(12, 6))
    style.configure("Settings.TNotebook", background=COLORS["app_bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
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
        padding=(14, 8),
        borderwidth=1,
        relief="solid",
        background=COLORS["tab_idle"],
        foreground=COLORS["text_secondary"],
        lightcolor=COLORS["tab_idle"],
        darkcolor=COLORS["tab_idle"],
        bordercolor=COLORS["tab_idle"],
    )
    style.map(
        "Settings.TNotebook.Tab",
        background=[("selected", COLORS["tab_active"]), ("active", COLORS["tab_hover"]), ("!selected", COLORS["tab_idle"])],
        foreground=[("selected", COLORS["blue"]), ("!selected", COLORS["text_secondary"])],
        lightcolor=[("selected", COLORS["tab_active"]), ("!selected", COLORS["tab_idle"])],
        darkcolor=[("selected", COLORS["tab_active"]), ("!selected", COLORS["tab_idle"])],
        bordercolor=[("selected", COLORS["border"]), ("active", COLORS["border"]), ("!selected", COLORS["tab_idle"])],
    )
    return style
