"""Colour palettes for the settings window.

The palette follows the Windows app theme, read from the registry, and is
re-read while the window is open so switching the system theme is picked up.
The accent is the application's own blue rather than the system accent colour,
which the mark uses too. ``WINBORDER_THEME`` overrides the choice, which is also
how the palettes are looked at without changing the system setting.

The fonts are chosen here as well, because the family depends on the language
the window is shown in.
"""

from __future__ import annotations

import ctypes
import os
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font, ttk

try:
    import winreg
except ImportError:                       # pragma: no cover - Windows only
    winreg = None                         # type: ignore[assignment]

PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
APPS_USE_LIGHT = "AppsUseLightTheme"

# The family that draws a language, most preferred first. Segoe UI has no CJK
# glyphs, so a language written with them gets a family of its own rather than
# whatever Windows substitutes. A family that is not installed is skipped.
FAMILIES: dict[str, tuple[str, ...]] = {
    "en": ("Segoe UI",),
    "ru": ("Segoe UI",),
    "zh": ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"),
    "ja": ("Yu Gothic UI", "Meiryo UI", "MS UI Gothic", "Segoe UI"),
    "ko": ("Malgun Gothic", "Gulim", "Segoe UI"),
}

# Font sizes are in points, which Tk scales by the display dpi by itself.
UI_FONT = ("Segoe UI", 10)
UI_FONT_SMALL = ("Segoe UI", 9)
NAV_FONT = ("Segoe UI", 10)
TITLE_FONT = ("Segoe UI Semibold", 19)
HERO_FONT = ("Segoe UI Semibold", 13)
SECTION_FONT = ("Segoe UI Semibold", 10)
MONO_FONT = ("Consolas", 10)


def use_language(code: str, root: tk.Misc) -> str:
    """Point the interface fonts at a language, and name the family chosen.

    A widget takes its font when it is built, so the window has to be built
    again after this for a change to show.
    """
    global UI_FONT, UI_FONT_SMALL, NAV_FONT, TITLE_FONT, HERO_FONT, SECTION_FONT

    family = _pick_family(code, root)
    UI_FONT = (family, 10)
    UI_FONT_SMALL = (family, 9)
    NAV_FONT = (family, 10)
    if family == "Segoe UI":
        # The display sizes are a lighter weight of the same family, which every
        # Windows has; the CJK families carry a bold face instead.
        TITLE_FONT = ("Segoe UI Semibold", 19)
        HERO_FONT = ("Segoe UI Semibold", 13)
        SECTION_FONT = ("Segoe UI Semibold", 10)
    else:
        TITLE_FONT = (family, 19, "bold")
        HERO_FONT = (family, 13, "bold")
        SECTION_FONT = (family, 10, "bold")
    # MONO_FONT is left alone on purpose. It is used for the log and for the
    # columns of numbers beside it, where the even spacing is the point, and
    # Windows draws the few translated words that appear among them with a
    # stand-in font without being asked.
    return family


def _pick_family(code: str, root: tk.Misc) -> str:
    """The first installed family for a language, or the first preferred one."""
    candidates = FAMILIES.get(code, FAMILIES["en"])
    try:
        available = set(font.families(root))
    except Exception:                     # noqa: BLE001 - no display to ask
        return candidates[0]
    if not available:
        return candidates[0]
    return next((name for name in candidates if name in available), candidates[0])


def ui_scale(root: tk.Misc) -> float:
    """How much bigger than 96 dpi this display is.

    Font sizes are in points and Tk scales them itself; everything sized in
    pixels has to be scaled by this to stay in proportion with the text.
    """
    try:
        ppi = float(root.winfo_fpixels("1i"))
    except Exception:                     # noqa: BLE001 - keep the window usable
        return 1.0
    return max(1.0, min(3.0, ppi / 96.0))

# The application's own blue, used for the mark everywhere and as the accent
# in the dark palette. The light palette needs a deeper shade to stay readable
# on white; the mark itself keeps the bright one on either background.
BRAND = "#4cc2ff"
ACCENT_DARK = BRAND
ACCENT_LIGHT = "#1f7ae0"


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    sidebar: str
    surface: str
    surface_alt: str
    fg: str
    muted: str
    border: str
    accent: str
    accent_fg: str
    log_bg: str
    log_fg: str
    ok: str
    scroll: str


DARK = Theme(
    name="dark",
    bg="#202020",
    sidebar="#272727",
    surface="#2b2b2b",
    surface_alt="#333333",
    fg="#ffffff",
    muted="#a0a0a0",
    border="#3d3d3d",
    accent=ACCENT_DARK,
    accent_fg="#10131a",
    log_bg="#1b1b1b",
    log_fg="#d6d6d6",
    ok="#6ccb7b",
    scroll="#3d3d3d",
)

LIGHT = Theme(
    name="light",
    bg="#f3f3f3",
    sidebar="#eaeaea",
    surface="#ffffff",
    surface_alt="#f0f0f0",
    fg="#1b1b1b",
    muted="#616161",
    border="#e0e0e0",
    accent=ACCENT_LIGHT,
    accent_fg="#ffffff",
    log_bg="#ffffff",
    log_fg="#2b2b2b",
    ok="#0f7b34",
    scroll="#c4c4c4",
)


def system_theme() -> Theme:
    """The palette the system asks for, dark when it cannot be read.

    Only the light or dark choice follows Windows: the accent is the
    application's own blue, so the window, the tray icon and the executable all
    carry the same colour whatever the desktop is set to.
    """
    override = os.environ.get("WINBORDER_THEME", "").strip().lower()
    if override == "dark":
        return DARK
    if override == "light":
        return LIGHT
    return LIGHT if _apps_use_light() else DARK


def _apps_use_light() -> bool:
    if winreg is None:
        return True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE) as key:
            value, _ = winreg.QueryValueEx(key, APPS_USE_LIGHT)
    except OSError:
        return True
    return bool(value)


class ThemeWatcher:
    """Reports when the system palette changed."""

    def __init__(self, theme: Theme) -> None:
        self.theme = theme

    def refresh(self) -> Theme | None:
        current = system_theme()
        if current.name == self.theme.name:
            return None
        self.theme = current
        return current


def apply(root: tk.Misc, style: ttk.Style, theme: Theme,
          scale: float = 1.0) -> None:
    """Colour the ttk widgets the window still uses, at the display scale."""
    style.theme_use("clam")
    pad = lambda pair: tuple(int(round(value * scale)) for value in pair)  # noqa: E731

    style.configure(".", background=theme.bg, foreground=theme.fg,
                    fieldbackground=theme.surface_alt, bordercolor=theme.border,
                    lightcolor=theme.surface_alt, darkcolor=theme.surface_alt,
                    focuscolor=theme.accent, font=UI_FONT)
    style.configure("TFrame", background=theme.bg)
    style.configure("TLabel", background=theme.bg, foreground=theme.fg)
    style.configure("Muted.TLabel", background=theme.bg, foreground=theme.muted)
    style.configure("Title.TLabel", background=theme.bg, foreground=theme.fg,
                    font=TITLE_FONT)

    style.configure("TButton", background=theme.surface_alt, foreground=theme.fg,
                    bordercolor=theme.border, relief="flat",
                    padding=pad((12, 5)))
    style.map("TButton",
              background=[("pressed", theme.border), ("active", theme.border)])

    for widget in ("TEntry", "TSpinbox"):
        style.configure(widget, fieldbackground=theme.surface_alt,
                        foreground=theme.fg, bordercolor=theme.border,
                        insertcolor=theme.fg, arrowcolor=theme.fg, padding=4)
    style.configure("TCombobox", fieldbackground=theme.surface_alt,
                    background=theme.surface_alt, foreground=theme.fg,
                    bordercolor=theme.border, arrowcolor=theme.fg, padding=4)
    style.map("TCombobox",
              fieldbackground=[("readonly", theme.surface_alt)],
              foreground=[("readonly", theme.fg)])
    root.option_add("*TCombobox*Listbox.background", theme.surface_alt)
    root.option_add("*TCombobox*Listbox.foreground", theme.fg)
    root.option_add("*TCombobox*Listbox.selectBackground", theme.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", theme.accent_fg)

    style.configure("TCheckbutton", background=theme.surface, foreground=theme.fg,
                    focuscolor=theme.surface)
    style.map("TCheckbutton", background=[("active", theme.surface)])
    for orient, sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
        name = f"{orient}.TScrollbar"
        style.layout(name, [
            (f"{orient}.Scrollbar.trough", {
                "sticky": sticky,
                "children": [(f"{orient}.Scrollbar.thumb",
                              {"expand": "1", "sticky": "nswe"})]})])
        style.configure(name, background=theme.scroll, troughcolor=theme.bg,
                        bordercolor=theme.bg, lightcolor=theme.scroll,
                        darkcolor=theme.scroll, arrowcolor=theme.bg,
                        borderwidth=0, relief="flat",
                        width=9 if orient == "Vertical" else 0)
    style.map("Vertical.TScrollbar",
              background=[("pressed", theme.muted), ("active", theme.muted)])
    style.map("Horizontal.TScrollbar",
              background=[("pressed", theme.muted), ("active", theme.muted)])
    style.configure("TSeparator", background=theme.border)


def style_text(widget: tk.Text, theme: Theme) -> None:
    widget.configure(background=theme.log_bg, foreground=theme.log_fg,
                     insertbackground=theme.fg, selectbackground=theme.accent,
                     selectforeground=theme.accent_fg, borderwidth=0,
                     highlightthickness=1, highlightbackground=theme.border,
                     highlightcolor=theme.border)


# DWMWA_USE_IMMERSIVE_DARK_MODE: 20 on current Windows, 19 before the 20H1 SDK.
_DWMWA_DARK = (20, 19)


def apply_title_bar(root: tk.Misc, theme: Theme) -> bool:
    """Ask Windows to draw the caption in the same theme as the window.

    The caption belongs to the window manager, so tkinter cannot colour it; the
    desktop composition attribute is the supported way to have it follow. Tk
    wraps its toplevel, so the attribute has to be set on the root ancestor
    rather than on the widget's own window, and only once the window exists.
    """
    if sys.platform != "win32":
        return True
    try:
        user32 = ctypes.windll.user32
        handle = user32.GetAncestor(root.winfo_id(), 2)      # GA_ROOT
        if not handle:
            handle = user32.GetParent(root.winfo_id())
        if not handle:
            return False
        value = ctypes.c_int(1 if theme.name == "dark" else 0)
        size = ctypes.sizeof(value)
        for attribute in _DWMWA_DARK:
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    handle, attribute, ctypes.byref(value), size) == 0:
                return True
    except (AttributeError, OSError):
        return False
    return False
