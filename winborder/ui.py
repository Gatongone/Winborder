"""Settings window and notification area icon.

The window is the normal way to run the host: settings are edited here, applied
to the running bridge as they change and written back to the settings file, and
the log is shown beside them. There is no separate debug build to run.

The text and the font of every widget are decided when it is built, so the
window is built again when the language changes rather than relabelled.

Both tkinter and the tray icon are optional. When either is unavailable the host
says so and keeps working from the console.
"""

from __future__ import annotations

import logging
import os
import re
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from . import config, diagnostics, i18n, icon, keymap, model, startup, theme, \
    trace
# Project identity, kept in the package root beside the version it describes.
from . import __author__, __license__, __repository__
from .logbuffer import LogBuffer
from .service import Service
from pathlib import Path
from .scan import DeviceScanner
from .tray import TrayIcon
from . import widgets
from .widgets import Card, CheckBox, Icon, KeyField, RemapList, Row, Separator, \
    Sidebar, ThemedLabel, ToggleSwitch

log = logging.getLogger("winborder.ui")

POLL_MS = 200
SCAN_POLL_MS = 1000
THEME_POLL_MS = 2000
COMMIT_DELAY_MS = 400
# Windows reports the advertisement as aborted for the second or two it takes to
# restart the advertiser, so a short abort is what every start looks like.
ABORT_GRACE_S = 3.0


class Field:
    """One editable setting."""

    def __init__(self, name: str, label: str, kind: str, hint: str = "",
                 choices: tuple[str, ...] = ()) -> None:
        self.name = name
        self.label = label
        self.kind = kind
        self.hint = hint
        self.choices = choices


# Every setting appears here once; the pages below decide where it is shown.
# The text is the English source: it is translated where it is shown, so the
# window can be built again in another language without touching this table.
FIELDS: tuple[Field, ...] = (
    Field("side", "Target side", "choice",
          "Which side of the PC the target device sits on",
          tuple(side.value for side in model.Side)),
    Field("sensitivity", "Pointer gain", "float",
          "1.0 moves the target pointer as far as the PC cursor"),
    Field("accel", "Speed gain", "float",
          "Extra pointer gain proportional to how fast the mouse moves"),
    Field("pullback_distance", "Damping", "int",
          "Pull-back distance needed for control to return"),
    Field("invert_wheel_v", "Invert vertical scroll", "bool",
          "Vertical scrolling is reversed on the target"),
    Field("invert_wheel_h", "Invert horizontal scroll", "bool",
          "Horizontal scrolling is reversed on the target"),
    Field("notch_up", "Scroll step up", "int", "Lines per wheel detent"),
    Field("notch_down", "Scroll step down", "int", "Lines per wheel detent"),
    Field("edge_trigger_enabled", "Cross at the screen edge", "bool",
          "The toggle key switches this while running"),
    Field("edge_inset", "Edge inset", "int",
          "How close to the PC screen edge the cursor has to get"),
    Field("exit_clear_distance", "Exit clearance", "int",
          "How far the cursor is placed back inside the PC screen on exit"),
    Field("enter_cooldown", "Enter cooldown", "float",
          "Seconds before the same edge can be crossed again"),
    Field("pullback_exit", "Return by pulling back", "bool",
          "Pulling the pointer towards the PC returns control"),
    Field("panic_keys", "Release control", "keys",
          "Releases the keyboard and mouse back to the PC at once"),
    Field("toggle_edge_keys", "Toggle edge crossing", "keys",
          "Turns the pointer's screen crossing on or off"),
    Field("type_clipboard_keys", "Type clipboard", "keys",
          "Sends the PC clipboard to the target as ASCII characters"),
    Field("forward_consumer_keys", "Forward media keys", "bool",
          "Volume and transport keys go to the target"),
    Field("capture_mouse_buttons", "Capture mouse buttons", "bool",
          "Clicks go to the target while it has control"),
    Field("start_with_windows", "Start with Windows", "bool",
          "One value under HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run, holding the command line; nothing else is written"),
    Field("start_hidden", "Start hidden", "bool",
          "Open with the notification area icon only, without this window"),
    Field("language", "Language", "choice",
          "Language of this window",
          i18n.codes()),
    Field("remap", "Remap keys", "remap",
          "Key remapping for the target device; right-click a field to choose from the full list"),
)

FIELDS_BY_NAME = {field.name: field for field in FIELDS}

#: Settings a zero or a negative value would silence: a pointer gain of zero moves
#: the target pointer nowhere at all, which reads as a broken link.
MUST_BE_POSITIVE = ("sensitivity",)
MUST_NOT_BE_NEGATIVE = ("accel",)

# What a dropdown shows for each value it accepts. A value is what the settings
# file holds and is never translated; only what stands for it is.
VALUE_LABELS = {"left": "Left", "right": "Right", "top": "Top", "bottom": "Bottom"}


def choice_labels(field: Field) -> tuple[str, ...]:
    """The text a dropdown shows, one for each value it accepts."""
    if field.name == config.LOCALE_FIELD:
        return tuple(i18n.native_name(code) for code in field.choices)
    return tuple(i18n.t(VALUE_LABELS.get(value, value)) for value in field.choices)


def choice_value(field: Field, label: object) -> str | None:
    """The value a shown label stands for, or None when it stands for nothing."""
    if not isinstance(label, str):
        return None
    labels = choice_labels(field)
    if label in labels:
        return field.choices[labels.index(label)]
    if label in field.choices:              # a value that was given as itself
        return label
    return None


def wrap_path(path: str, limit: int) -> str:
    """A path that fits its column, broken after a separator rather than inside a name.

    Tk wraps a label at any character, so a long settings path came out as
    ``…\\winborder.js`` over ``on`` -- a file name cut in half, which reads as two
    strings rather than as one path. Breaking after the last separator that still
    fits keeps the file name whole, and the label shows the folder above it.

    When there is no separator to break on, the middle is replaced with an
    ellipsis instead: something has to give, and half a name is worse than a gap.
    """
    if len(path) <= limit:
        return path
    cut = path.rfind("\\", 0, limit)
    if cut <= 0:
        return shorten_path(path, limit)
    head, tail = path[:cut + 1], path[cut + 1:]
    if len(tail) > limit:
        tail = shorten_path(tail, limit)
    return head + "\n" + tail


def shorten_path(path: str, limit: int) -> str:
    """A path cut in the middle, keeping both ends distinguishable."""
    if len(path) <= limit:
        return path
    if limit <= 3:
        return path[:max(0, limit)]
    keep = limit - 1
    head = max(1, keep // 2)
    tail = max(1, keep - head)
    return path[:head] + "…" + path[-tail:]


def link_summary(state: dict[str, object] | None, *,
                 since: float | None = None,
                 last_up: float | None = None,
                 aborted_for: float = 0.0) -> str:
    """What this PC's own Bluetooth link is doing, in one line.

    This PC is the HID device, so the only connection it can have is one a host
    opened: "connected" here means a host subscribed to the reports, and the
    pairing itself can only be started from that host. The line is worded so
    that it does not invite the reader to look for a connect button that could
    not work.

    ``since`` and ``last_up`` are wall clock times: when the subscription that is
    open now began, and when the previous one ended. Which of them applies is
    decided by the caller, which is the part that can see the transitions.

    ``aborted_for`` is how long the stack has been reporting the advertisement as
    aborted. Windows says that for the second or two it takes to restart the
    advertiser after the peripheral starts, so short is normal and only a lasting
    one is worth calling a fault.
    """
    def clock(when: float) -> str:
        return time.strftime("%H:%M:%S", time.localtime(when))

    if state is None:
        return i18n.t("not advertising yet — the Log says why")

    advertising = str(state.get("advertising") or "")
    if state.get("connected"):
        # A live subscription outranks the advertisement status: the status goes
        # ABORTED and back again while a host is connected, and reporting that
        # as a fault would be wrong at the one moment things are working.
        when = since if since is not None else time.time()
        return i18n.t("connected since {time} — the target device is subscribed").format(
            time=clock(when))

    if "aborted" in advertising and aborted_for >= ABORT_GRACE_S:
        line = i18n.t("the advertisement was cut short — see the Log")
    elif not advertising.startswith("start"):
        line = i18n.t("not advertising yet — the Log says why")
    else:
        name = str(state.get("name") or "")
        # Only ever the name the radio reports: the computer name is a different
        # name, and a line naming the wrong one sends the reader looking for it in
        # the target's list and finding nothing.
        line = (i18n.t("advertising as {name} — waiting for the target device to pair").format(name=name)
                if name else
                i18n.t("advertising as a keyboard and mouse — waiting for the target device to pair"))
    if last_up is not None:
        line += "  ·  " + i18n.t("last connected at {time}").format(
            time=clock(last_up))
    return line


# page key, title, icon, description, groups of rows
PAGES: tuple[tuple[str, str, str, str,
                  tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]], ...] = (
    ("status", "Status", "status", "What the bridge is doing right now", ()),
    ("generic", "Generic", "gear",
     "Startup, maintenance and what is running",
     (("Startup", (("start_with_windows",), ("start_hidden",))),
      ("Interface", (("language",),)))),
    # The page is named for the screen edge the pointer crosses; the code still
    # calls the act a handoff (the service refuses one, the router hands over), and
    # the entry event is logged as one. Both halves meet here: where the target
    # sits, where the keyboard and mouse leave the PC, and how they come back.
    ("edge", "Edge", "edge",
     "Where the target sits, and where the keyboard and mouse change hands",
     (("Connection", (("side",),)),
      ("Crossing", (("edge_inset", "enter_cooldown"), ("exit_clear_distance",))),
      ("Returning", (("pullback_distance",), ("pullback_exit",))))),
    ("nearby", "Devices", "bluetooth",
     "BLE devices around this PC", ()),
    ("pointer", "Pointer", "pointer", "How mouse movement reaches the target",
     (("Movement", (("sensitivity", "accel"),)),
      ("Scrolling", (("notch_up", "notch_down"),
                     ("invert_wheel_v", "invert_wheel_h"))))),
    ("keyboard", "Keyboard", "keyboard",
     "Keys the PC keeps for itself, and what the target receives",
     (("PC keys", (("panic_keys",), ("toggle_edge_keys",),
                  ("type_clipboard_keys",))),
      ("Target keyboard", (("capture_mouse_buttons", "forward_consumer_keys"),
                           ("remap",))))),
    ("log", "Log", "terminal", "Everything Winborder reports", ()),
)

# The master switch shown in a page header, where the page has one.
PAGE_SWITCHES = {"edge": "edge_trigger_enabled"}

# The read-only rows of the status page: key, title, description. The words the
# values are made of are translated where they are written. These rows carry a
# wider value column than a settings row: the link line names three counters.
STATUS_ROWS: tuple[tuple[str, str, str], ...] = (
    ("mode", "Mode", "Which side has the keyboard and mouse"),
    ("cursor", "PC cursor", "Fraction of the PC screen"),
    ("pointer", "Target pointer", "Fraction of the tracked surface"),
    ("travel", "Travel", "Motion since the target was entered, negative on the way back"),
    ("link", "Device link", "Reports the target accepted"),
)
STATUS_CONTROL_WIDTH = 300

# The read-only rows of the About card, on the Generic page. The settings file
# is a full path, so these rows carry a wider value column than the controls of
# a settings card do.
ABOUT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("version", "Version", "Shared by the window and the background service"),
    ("runtime", "Running from", "An executable, or Python"),
    ("developer", "Developer", "Maintainer of this project"),
    ("repository", "Repository", "Source code and releases"),
    ("license", "License", "Terms for use and redistribution"),
    ("settings", "Settings file",
     "The file on disk that holds the current configuration"),
)
ABOUT_CONTROL_WIDTH = 360


class Control:
    """One editable control, read and written without knowing what it is.

    A field's control used to be reached through whatever it happened to be: a
    ``BooleanVar`` needed a branch, a dropdown needed the label behind its value,
    and the remap list needed a special case in both directions. Each control now
    answers ``read`` and ``write`` in the form's own terms -- the code behind a
    label, a list of pairs, a bool -- so filling and reading are one loop each.
    """

    def read(self) -> object:
        raise NotImplementedError

    def write(self, value: object) -> None:
        raise NotImplementedError


def number_allowed(allow_point: bool) -> Callable[[str], bool]:
    """Whether an entry text could still become a number.

    The setting is validated when it is committed, which is too late to be useful:
    the field had already taken the text, so a typo looked accepted until the next
    save. This rejects the keystroke instead, and allows the states a number passes
    through while it is being typed -- empty, and a lone minus sign.
    """

    pattern = r"-?\d*(?:\.\d*)?" if allow_point else r"-?\d*"

    def allowed(proposed: str) -> bool:
        return re.fullmatch(pattern, proposed) is not None

    return allowed


class _VariableControl(Control):
    """A control backed by a Tk variable, holding what the form holds."""

    def __init__(self, variable: tk.Variable,
                 widget: tk.Widget | None = None) -> None:
        self._variable = variable
        self._widget = widget

    def read(self) -> object:
        return self._variable.get()

    def write(self, value: object) -> None:
        self._variable.set(str(value))


class _BoolControl(Control):
    def __init__(self, variable: tk.BooleanVar) -> None:
        self._variable = variable

    def read(self) -> object:
        return bool(self._variable.get())

    def write(self, value: object) -> None:
        self._variable.set(bool(value))


class _ChoiceControl(Control):
    """A dropdown shows a label; the form holds the value the label stands for."""

    def __init__(self, field: Field, variable: tk.StringVar) -> None:
        self._field = field
        self._variable = variable

    def read(self) -> object:
        return choice_value(self._field, self._variable.get())

    def write(self, value: object) -> None:
        labels = choice_labels(self._field)
        raw = str(value)
        self._variable.set(labels[self._field.choices.index(raw)]
                           if raw in self._field.choices else "")


class _KeyControl(Control):
    """A key entered by pressing it, held as the name the form and the file use.

    The setting is a list and the file writes it comma separated, but a row with
    one key on it is a row with one key on it: the control carries the same string,
    and pressing a key replaces it.
    """

    def __init__(self, widget: "KeyField") -> None:
        self._widget = widget

    def read(self) -> object:
        return self._widget.value

    def write(self, value: object) -> None:
        self._widget.set(str(value))


class _RemapControl(Control):
    """The remap list is its own widget, so it is its own adapter."""

    def __init__(self, widget: "RemapList") -> None:
        self._widget = widget

    def read(self) -> object:
        return self._widget.pairs()

    def write(self, value: object) -> None:
        self._widget.set_pairs(value if isinstance(value, list) else [])


class SettingsForm:
    """The settings as text, with the parsing kept away from the widgets."""

    def __init__(self, settings: dict[str, object] | None = None) -> None:
        self.values: dict[str, object] = {}
        if settings is not None:
            self.load(settings)

    def load(self, settings: dict[str, object]) -> None:
        for field in FIELDS:
            value = settings.get(field.name)
            if field.kind == "bool":
                self.values[field.name] = bool(value)
            elif field.kind == "keys":
                names = [keymap.describe_vk(vk) if isinstance(vk, int) else str(vk)
                         for vk in (value or ())]
                self.values[field.name] = ", ".join(names)
            elif field.kind == "remap":
                pairs = value if isinstance(value, dict) else {}
                self.values[field.name] = [(str(a), str(b)) for a, b in pairs.items()]
            elif value is None:
                self.values[field.name] = ""
            else:
                self.values[field.name] = str(value)

    def settings(self, base: dict[str, object]) -> dict[str, object]:
        """Merge the form over earlier settings, rejecting what cannot be used."""
        out = dict(base)
        for field in FIELDS:
            raw = self.values.get(field.name, "")
            label = i18n.t(field.label)
            if field.kind == "bool":
                out[field.name] = bool(raw)
            elif field.kind in ("int", "float"):
                text = str(raw).strip()
                if text == "":
                    out.pop(field.name, None)
                    continue
                try:
                    number = int(text) if field.kind == "int" else float(text)
                except ValueError:
                    raise config.ConfigError(
                        i18n.t("{label} must be a number").format(label=label)) from None
                if field.name in MUST_BE_POSITIVE and number <= 0:
                    raise config.ConfigError(
                        i18n.t("{label} must be greater than zero").format(label=label))
                if field.name in MUST_NOT_BE_NEGATIVE and number < 0:
                    raise config.ConfigError(
                        i18n.t("{label} must not be negative").format(label=label))
                out[field.name] = number
            elif field.kind == "keys":
                names = [name.strip() for name in str(raw).split(",") if name.strip()]
                for name in names:
                    if name not in keymap.KEY_NAMES:
                        raise config.ConfigError(
                            i18n.t("{label}: unknown key {name}").format(
                                label=label, name=name))
                out[field.name] = names
            elif field.kind == "remap":
                pairs: dict[str, str] = {}
                for entry in raw or ():
                    source, target = (str(part).strip() for part in entry)
                    if not source or not target:
                        raise config.ConfigError(
                            i18n.t("{label}: every row needs a key on both sides").format(
                                label=label))
                    for name in (source, target):
                        if name not in keymap.KEY_NAMES:
                            raise config.ConfigError(
                                i18n.t("{label}: unknown key {name}").format(
                                    label=label, name=name))
                    pairs[source] = target
                out[field.name] = pairs
            else:
                out[field.name] = str(raw).strip()
        return out


class SettingsWindow:
    """The window: a status page, the settings pages and the log."""

    def __init__(self, service: Service, settings: dict[str, object],
                 config_path: str) -> None:
        self.service = service
        # Everything the form shows, whether or not the file named all of it.
        self.settings = config.complete(settings)
        self.config_path = config_path
        self.log_buffer = LogBuffer()
        self.form = SettingsForm()
        self.palette = theme.system_theme()
        self.watcher = theme.ThemeWatcher(self.palette)

        self._variables: dict[str, tk.Variable] = {}
        self._controls: dict[str, Control] = {}
        self._page_canvas: dict[str, tk.Canvas] = {}
        self._page_body: dict[str, tk.Frame] = {}
        self._page_scroll: dict[str, ttk.Scrollbar] = {}
        self._paintable: list[tk.Widget] = []
        self._log_lines = 0
        self._paused = False
        self._waiting = 0
        self._bridge_paused = False
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._formatter = trace.StatusFormatter()
        self._commit_job: str | None = None
        self._message_job: str | None = None
        self._caption_jobs: list[str] = []
        self._loading = False
        # The scan is started from its page and stopped when the window goes,
        # so it is created here rather than in the page builder.
        self._scanner = DeviceScanner()
        # When this PC's own link came up and went down, for the Devices page.
        # Only the window can see the moment a host arrives, so it keeps them.
        self._link_up = False
        self._link_since: float | None = None
        self._link_ended: float | None = None
        self._abort_since: float | None = None
        # WINBORDER_PAGE opens a page directly, which is how the layout is looked
        # at without clicking through the sidebar.
        self._current_page = os.environ.get("WINBORDER_PAGE", "").strip()
        if self._current_page not in {page[0] for page in PAGES}:
            self._current_page = PAGES[0][0]
        self._closing = False

        self.root = tk.Tk()
        self.root.title("Winborder")
        # The fonts follow the language, and both are needed before anything is
        # built: a widget takes its text and its font at that moment.
        i18n.set_language(self.settings.get(config.LOCALE_FIELD))
        theme.use_language(i18n.language(), self.root)
        self.scale = theme.ui_scale(self.root)
        widgets.set_scale(self.scale)
        self.root.minsize(min(self.px(820), self.root.winfo_screenwidth()),
                          min(self.px(540), self.root.winfo_screenheight()))
        self.root.geometry(f"{min(self.px(1120), int(self.root.winfo_screenwidth() * 0.92))}"
                           f"x{min(self.px(760), int(self.root.winfo_screenheight() * 0.9))}")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        # Tk ships its own icon; this is the same mark as the tray and the exe.
        self._icon_image = icon.render(self.root, 64, theme.BRAND)
        self.root.iconphoto(True, self._icon_image)
        self._build()
        self._fill(self.settings)
        self._apply_theme(self.palette)
        self.show_page(self._current_page)
        # One handler for the whole window: the wheel goes to the widget under
        # the pointer, and widgets that do not use it pass it on to here.
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self._focus_job = self.root.after_idle(self.root.focus_set)

        self.tray = TrayIcon("Winborder", self._open_from_tray, self._quit_from_tray,
                             self._reload_from_tray, self._open_config_file,
                             on_pause=self._pause_from_tray,
                             paused=lambda: self._bridge_paused,
                             on_type_clipboard=self._type_clipboard_from_tray)
        self._service_thread = threading.Thread(target=self._run_service,
                                                name="winborder-service", daemon=True)

    def px(self, value: float) -> int:
        """A pixel size at the display scale."""
        return max(1, int(round(value * self.scale)))

    # -- construction -----------------------------------------------------

    def _build(self) -> None:
        # Every row, so the control column can be measured once the window has been
        # styled: the style is what sets the height of what the rows hold.
        self._rows: list[Row] = []
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        palette = self.palette
        self.sidebar = Sidebar(self.root, palette)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.add("status", i18n.t("Status"), "status",
                         lambda: self.show_page("status"))
        for key, title, icon, _text, _groups in PAGES[1:]:
            self.sidebar.add(key, i18n.t(title), icon,
                             lambda key=key: self.show_page(key))
        self.sidebar.add("pause", self._bridge_label(),
                         "play" if self._bridge_paused else "pause",
                         self.toggle_bridge, bottom=True)
        self.sidebar.add("file", i18n.t("Settings file"), "file",
                         self._open_config_file, bottom=True)
        self.sidebar.add("reload", i18n.t("Reload settings"), "reload",
                         self.reload, bottom=True)
        self.sidebar.add("quit", i18n.t("Quit"), "quit", self.stop, bottom=True)

        self.content = tk.Frame(self.root, background=palette.bg)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        self.pages: dict[str, tk.Frame] = {}
        for key, title, icon, text, groups in PAGES:
            self.pages[key] = self._page(key, title, icon, text, groups)
        self.message = ThemedLabel(self.content, palette, "", tone="muted",
                                   font=theme.UI_FONT_SMALL)
        self.message.grid(row=1, column=0, sticky="ew", padx=self.px(26),
                          pady=(0, self.px(8)))

    def _rebuild(self) -> None:
        """Build the window again, in the language that is now in use.

        The text and the font of a widget are decided when it is built, so a
        language change is a rebuild rather than a relabelling. Everything the
        window shows that is not text is kept: the settings, the palette, and
        the page that was on screen.
        """
        page = self._current_page
        self.sidebar.destroy()
        self.content.destroy()
        self._paintable = []
        self._variables = {}
        self._controls = {}
        self._page_canvas = {}
        self._page_body = {}
        self._page_scroll = {}
        self._log_lines = 0
        for name in ("status_rows", "about_rows", "log_text", "scroll_var",
                     "pause_button", "waiting"):
            if hasattr(self, name):
                delattr(self, name)
        self._build()
        self._fill(self.settings)
        self._apply_theme(self.palette)
        self.show_page(page)

    def _page(self, key: str, title: str, icon: str, text: str,
              groups: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]) -> tk.Frame:
        """One page: the header card, then the groups of rows.

        The title is on the card only. A second, larger one above it said the
        same thing twice.
        """
        palette = self.palette
        page = tk.Frame(self.content, background=palette.bg)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        self._paintable.append(page)

        if key == "log":
            body = tk.Frame(page, background=palette.bg)
            body.grid(row=0, column=0, sticky="nsew")
            body.columnconfigure(0, weight=1)
        elif key == "nearby":
            body = tk.Frame(page, background=palette.bg)
            body.grid(row=0, column=0, sticky="nsew")
            body.columnconfigure(0, weight=1)
        else:
            body = self._scrolling(page, key)

        hero = Card(body, palette)
        hero.grid(row=self._next_row(body), column=0, sticky="ew",
                  padx=self.px(26), pady=(self.px(22), 0))
        inner = hero.inner
        inner.columnconfigure(2, weight=1)
        Icon(inner, icon, palette, size=32, background=palette.surface).grid(
            row=0, column=0, rowspan=2, padx=(self.px(18), self.px(16)),
            pady=self.px(18))
        hero_title = ThemedLabel(inner, palette, i18n.t(title), on="surface",
                                 font=theme.HERO_FONT)
        hero_title.grid(row=0, column=1, columnspan=2, sticky="w",
                        pady=(self.px(18), 0))
        hero_text = ThemedLabel(inner, palette, i18n.t(text), on="surface",
                                tone="muted", font=theme.UI_FONT,
                                wraplength=self.px(620))
        hero_text.grid(row=1, column=1, columnspan=2, sticky="w",
                       pady=(self.px(2), self.px(18)))
        self._paintable.extend([hero, hero_title, hero_text])

        switch_name = PAGE_SWITCHES.get(key)
        if switch_name is not None:
            variable = tk.BooleanVar()
            self._variables[switch_name] = variable
            self._controls[switch_name] = _BoolControl(variable)
            switch = ToggleSwitch(inner, variable, palette,
                                  command=lambda: self._changed(switch_name),
                                  background=palette.surface)
            switch.grid(row=0, column=3, rowspan=2,
                        padx=(self.px(12), self.px(20)))
            self._paintable.append(switch)

        if key == "status":
            self._status_page(body)
        elif key == "log":
            self._log_page(body)
        elif key == "nearby":
            self._nearby_page(body)
        elif key == "generic":
            self._groups(body, groups)
            self._about_page(body)
        else:
            self._groups(body, groups)
        return page

    def _scrolling(self, page: tk.Frame, key: str) -> tk.Frame:
        """A body that scrolls, so a long page is never cut off."""
        palette = self.palette
        canvas = tk.Canvas(page, highlightthickness=0, borderwidth=0,
                           background=palette.bg)
        scroll = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, background=palette.bg)
        # The column has to take the width, or every card stops at the width of
        # its own contents and the page leaves the rest of the window empty.
        body.columnconfigure(0, weight=1)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        body.bind("<Configure>", lambda _event: self._sync_page(key))
        canvas.bind("<Configure>",
                    lambda event: (canvas.itemconfigure(window, width=event.width),
                                   self._sync_page(key)))
        canvas.pack(side="left", fill="both", expand=True)
        self._page_canvas[key] = canvas
        self._page_body[key] = body
        self._page_scroll[key] = scroll
        self._paintable.append(canvas)
        return body

    def _sync_page(self, key: str) -> None:
        """Fit a page to its viewport: pinned to the top, bar only if needed.

        A scroll region shorter than the viewport makes Tk centre the content,
        which leaves dead space above it and lets the page be dragged around, so
        the region is at least as tall as the viewport. The bar is then only
        shown for a page that really is taller than the window.
        """
        canvas = self._page_canvas[key]
        body = self._page_body[key]
        scroll = self._page_scroll[key]
        height = max(body.winfo_reqheight(), canvas.winfo_height())
        canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), height))

        needed = body.winfo_reqheight() > canvas.winfo_height()
        if needed and not scroll.winfo_ismapped():
            scroll.pack(side="right", fill="y")
        elif not needed and scroll.winfo_ismapped():
            scroll.pack_forget()

    def _scroll_canvas(self) -> tk.Canvas | None:
        """The scrolling body of the page on screen, if it has one."""
        return self._page_canvas.get(self._current_page)

    def _on_wheel(self, event) -> None:
        """Scroll the visible page. Widgets that scroll themselves come first."""
        canvas = self._scroll_canvas()
        if canvas is None:
            return
        steps = int(-event.delta / 120) or (-1 if event.delta > 0 else 1)
        canvas.yview_scroll(steps, "units")

    def _groups(self, body: tk.Frame,
                groups: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]) -> None:
        palette = self.palette
        for title, rows in groups:
            label = ThemedLabel(body, palette, i18n.t(title), tone="muted",
                                font=theme.SECTION_FONT)
            label.grid(row=self._next_row(body), column=0, sticky="w",
                       padx=self.px(26), pady=(self.px(18), self.px(6)))
            card = Card(body, palette)
            card.grid(row=self._next_row(body), column=0, sticky="ew",
                      padx=self.px(26))
            card.inner.columnconfigure(0, weight=1)
            self._paintable.extend([label, card])
            # A page groups settings into rows of names; each one is shown on a
            # line of its own, the way a settings list reads.
            for index, name in enumerate(
                    name for row in rows for name in row):
                if index:
                    separator = Separator(card.inner, palette)
                    separator.grid(row=index * 2 - 1, column=0, sticky="ew")
                    self._paintable.append(separator)
                field = FIELDS_BY_NAME[name]
                if field.kind == "remap":
                    self._remap_block(card.inner, index, field)
                    continue
                row = Row(card.inner, palette, i18n.t(field.label),
                          i18n.t(field.hint),
                          make_control=lambda parent, name=name:
                          self._control(parent, name))
                row.grid(row=index * 2, column=0, sticky="ew")
                self._paintable.append(row)
                self._rows.append(row)

    def _remap_block(self, card: tk.Frame, index: int, field: Field) -> None:
        """The remap list takes the width of the card, not the width of a control.

        It is a list rather than a single value, so it reads across the card. The
        way to add a line is the one thing on this row that belongs in the control
        column, where every other row keeps its control: a plus at the right, on
        the line with the description.
        """
        block = tk.Frame(card, background=self.palette.surface)
        block.grid(row=index * 2, column=0, sticky="ew")
        block.columnconfigure(0, weight=1)
        self.remap_list = RemapList(block, self.palette,
                                    on_change=lambda: self._changed("remap"))
        self._controls["remap"] = _RemapControl(self.remap_list)

        def make_add(parent: tk.Widget) -> tk.Widget:
            # A drawn plus with no frame, rather than the word "Add" on a button:
            # the row is already described by its title, and the action is one
            # shape. It sits in the control column, on the description's line.
            self.remap_add = widgets.IconButton(parent, "plus", self.palette,
                                                command=self._add_remap)
            self._paintable.append(self.remap_add)
            return self.remap_add

        Row(block, self.palette, i18n.t(field.label), i18n.t(field.hint),
            make_control=make_add).grid(row=0, column=0, sticky="ew")
        self.remap_list.grid(row=1, column=0, sticky="ew",
                             padx=(self.px(14), self.px(16)),
                             pady=(self.px(8), self.px(14)))
        self._paintable.extend([block, self.remap_list])

    def _add_remap(self) -> None:
        """Add an empty line, ready to be filled in."""
        self.remap_list.add_row()

    def _control(self, parent: tk.Widget, name: str) -> tk.Widget:
        palette = self.palette
        field = FIELDS_BY_NAME[name]
        if field.kind == "bool":
            variable = self._variables.get(name) or tk.BooleanVar()
            self._variables[name] = variable
            self._controls[name] = _BoolControl(variable)
            return ToggleSwitch(parent, variable, palette,
                                command=lambda: self._changed(name),
                                background=palette.surface)
        if field.kind == "keys":
            # 116 key names make a dropdown a search problem dressed as a field,
            # and a typed name is a name that can be wrong.
            key_field = KeyField(parent, palette, width=10,
                                 on_change=lambda: self._changed(name))
            self._controls[name] = _KeyControl(key_field)
            key_field.bind("<Return>", lambda _event: self._commit())
            key_field.bind("<FocusOut>", lambda _event: self._commit())
            return key_field
        variable = tk.StringVar()
        self._variables[name] = variable
        if field.kind == "choice":
            control: tk.Widget = ttk.Combobox(parent, textvariable=variable, width=11,
                                              values=list(choice_labels(field)),
                                              state="readonly")
            self._controls[name] = _ChoiceControl(field, variable)
        elif field.kind in ("int", "float"):
            control = ttk.Entry(parent, textvariable=variable, width=12)
            check = self.root.register(number_allowed(field.kind == "float"))
            control.configure(validate="key", validatecommand=(check, "%P"))
            self._controls[name] = _VariableControl(variable, control)
        else:
            control = ttk.Entry(parent, textvariable=variable, width=20)
            self._controls[name] = _VariableControl(variable, control)
        variable.trace_add("write", lambda *_: self._changed(name))
        control.bind("<Return>", lambda _event: self._commit())
        control.bind("<FocusOut>", lambda _event: self._commit())
        return control

    def _status_page(self, body: tk.Frame) -> None:
        palette = self.palette
        card = Card(body, palette)
        card.grid(row=self._next_row(body), column=0, sticky="ew",
                  padx=self.px(26), pady=(self.px(18), 0))
        card.inner.columnconfigure(0, weight=1)
        self._paintable.append(card)

        self.status_rows: dict[str, tk.Label] = {}
        for index, (key, title, description) in enumerate(STATUS_ROWS):
            if index:
                separator = Separator(card.inner, palette)
                separator.grid(row=index * 2 - 1, column=0, sticky="ew")
                self._paintable.append(separator)
            def make_value(parent, key=key) -> tk.Label:
                value = ThemedLabel(parent, self.palette, on="surface",
                                    font=theme.MONO_FONT, anchor="e")
                self.status_rows[key] = value
                self._paintable.append(value)
                return value

            row = Row(card.inner, palette, i18n.t(title), i18n.t(description),
                      make_value, control_width=STATUS_CONTROL_WIDTH)
            row.grid(row=index * 2, column=0, sticky="ew")
            self._paintable.append(row)
            self._rows.append(row)

    def _about_page(self, body: tk.Frame) -> None:
        """Where things live, and what is running."""
        palette = self.palette
        label = ThemedLabel(body, palette, i18n.t("About"), tone="muted",
                            font=theme.SECTION_FONT)
        label.grid(row=self._next_row(body), column=0, sticky="w",
                   padx=self.px(26), pady=(self.px(18), self.px(6)))
        card = Card(body, palette)
        card.grid(row=self._next_row(body), column=0, sticky="ew",
                  padx=self.px(26))
        card.inner.columnconfigure(0, weight=1)
        self._paintable.extend([label, card])

        facts = self._facts()
        self.about_rows: dict[str, tk.Label] = {}
        for index, (key, title, description) in enumerate(ABOUT_ROWS):
            if index:
                separator = Separator(card.inner, palette)
                separator.grid(row=index * 2 - 1, column=0, sticky="ew")
                self._paintable.append(separator)

            def make_value(parent, key=key) -> tk.Label:
                text = self._fit(facts.get(key, ""), ABOUT_CONTROL_WIDTH - 10)
                value = ThemedLabel(parent, self.palette, text, on="surface",
                                    font=theme.MONO_FONT, anchor="e",
                                    justify="right",
                                    wraplength=self.px(ABOUT_CONTROL_WIDTH - 10))
                if key == "repository":
                    # The one value here that is an address rather than a path, so
                    # it is drawn as a link and opens in the browser.
                    value.configure(cursor="hand2", font=self._link_font())
                    value.set_tone("accent")
                    value.bind("<Button-1>",
                               lambda _event: self._open_url(__repository__))
                self.about_rows[key] = value
                self._paintable.append(value)
                return value

            row = Row(card.inner, palette, i18n.t(title), i18n.t(description),
                      make_value, control_width=ABOUT_CONTROL_WIDTH)
            row.grid(row=index * 2, column=0, sticky="ew")
            self._paintable.append(row)
            self._rows.append(row)

        tools = tk.Frame(body, background=palette.bg)
        tools.grid(row=self._next_row(body), column=0, sticky="w",
                   padx=self.px(26), pady=(self.px(14), 0))
        ttk.Button(tools, text=i18n.t("Open settings file"),
                   command=lambda: self._open_path(self.config_path)).pack(side="left")
        ttk.Button(tools, text=i18n.t("Reset to defaults"),
                   command=self.reset).pack(side="left", padx=self.px(8))
        self._paintable.append(tools)

    def _facts(self) -> dict[str, str]:
        """What the About card shows on the right."""
        facts = startup.describe()
        facts["runtime"] = i18n.t(facts["runtime"])
        facts["developer"] = __author__
        facts["repository"] = __repository__
        facts["license"] = __license__
        facts["settings"] = str(Path(self.config_path).resolve())
        return facts

    def _link_font(self) -> tkfont.Font:
        """The monospaced font with an underline, for the one address on the page.

        Kept on the window rather than made on each rebuild: a named Tk font is
        deleted with its object, and a label built with it would lose the underline.
        """
        font = getattr(self, "_underlined_mono", None)
        if font is None:
            font = tkfont.Font(root=self.root, font=theme.MONO_FONT, underline=1)
            self._underlined_mono = font
        return font

    def _fit(self, text: str, width: float) -> str:
        """Shorten a value until it fits the column, without wrapping mid-token.

        Measured rather than guessed: the monospaced font gives one character
        width to work with, and both that and the column follow the display
        scale, so a character count worked out here would be wrong on a scaled
        desktop.
        """
        units = max(1, int(round(tkfont.Font(font=theme.MONO_FONT).measure("0"))))
        limit = max(8, int(self.px(width)) // units)
        return wrap_path(text, limit)

    def reset(self) -> None:
        """Put every setting back to its built in default."""
        if not messagebox.askyesno(
                "Winborder", i18n.t("Reset every setting to its default value?"),
                parent=self.root):
            return
        self.settings = config.defaults()
        self._fill(self.settings)
        self._commit()
        self._notify(i18n.t("Settings reset to defaults"))

    def _log_page(self, body: tk.Frame) -> None:
        palette = self.palette
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        card = Card(body, palette, padding=1)
        card.grid(row=2, column=0, sticky="nsew", padx=self.px(26))
        card.inner.columnconfigure(0, weight=1)
        card.inner.rowconfigure(0, weight=1)
        # width=1 keeps the widget from asking for its default 80 columns,
        # which is wider than the page and pushes everything off the right edge.
        self.log_text = tk.Text(card.inner, wrap="char", height=16, width=1,
                                font=theme.MONO_FONT,
                                state="disabled", padx=8, pady=6, borderwidth=0,
                                highlightthickness=0)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(card.inner, orient="vertical",
                               command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        tools = tk.Frame(body, background=palette.bg)
        tools.grid(row=3, column=0, sticky="ew", padx=self.px(26),
                   pady=(self.px(10), 0))
        # Pausing holds the view still while the host keeps logging, which is
        # what reading a line that is already on screen needs. What has piled up
        # in the meantime is counted at the other end of the row, and it appears
        # as soon as the view is let go again.
        self.pause_button = ttk.Button(tools, text=self._pause_label(),
                                       command=self._toggle_pause)
        self.pause_button.pack(side="left")
        ttk.Button(tools, text=i18n.t("Clear"), command=self._clear_log).pack(
            side="left", padx=self.px(10))
        # Auto-scroll is a view setting rather than an action, so it sits at the
        # far end of the row, and the count of what arrived while the view was
        # held sits beside it: both are about the view, not about the log.
        self.scroll_var = tk.BooleanVar(value=True)
        follow = tk.Frame(tools, background=palette.bg)
        follow.pack(side="right")
        box = CheckBox(follow, self.scroll_var, palette, background=palette.bg)
        box.pack(side="left")
        label = ThemedLabel(follow, palette, i18n.t("Auto-scroll"),
                            font=theme.UI_FONT)
        label.configure(cursor="hand2")
        label.pack(side="left", padx=(self.px(8), 0))
        for widget in (box, label):
            widget.bind("<Button-1>", lambda _event: box._toggle())
        self._paintable.extend([follow, box, label])
        self.waiting = ThemedLabel(tools, palette, tone="muted",
                                   font=theme.UI_FONT_SMALL)
        self.waiting.pack(side="right", padx=(0, self.px(12)))
        self._paintable.extend([card, tools, self.waiting])

    def _pause_label(self) -> str:
        return i18n.t("Resume log") if self._paused else i18n.t("Pause log")

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_button.configure(text=self._pause_label())
        self._show_waiting()

    # -- nearby devices ---------------------------------------------------

    def _nearby_page(self, body: tk.Frame) -> None:
        """This PC's own link, then the devices around this PC.

        The devices are a list, and deliberately nothing more: it cannot connect
        to anything. In Bluetooth LE a connection is opened by the central, and
        in HID over GATT the central is the target — this PC is the HID device
        and can only advertise. What the list is good for is checking that the
        target is in range while the target refuses to connect.

        The line above it is the part that can be acted on, and the one thing the
        list cannot show, because this PC never appears in its own scan.
        """
        palette = self.palette
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        self.link_state = ThemedLabel(
            body, palette, tone="muted", font=theme.SECTION_FONT,
            wraplength=self.px(520))
        self.link_state.grid(row=1, column=0, sticky="ew", padx=self.px(26),
                             pady=(self.px(16), 0))

        note = ThemedLabel(
            body, palette,
            i18n.t("Nearby BLE does not include this PC"),
            tone="muted", font=theme.UI_FONT_SMALL, wraplength=self.px(520))
        note.grid(row=2, column=0, sticky="ew", padx=self.px(26),
                  pady=(self.px(6), 0))
        self.devices_note = note

        card = Card(body, palette, padding=1)
        card.grid(row=3, column=0, sticky="nsew", padx=self.px(26),
                  pady=(self.px(12), 0))
        card.inner.columnconfigure(0, weight=1)
        card.inner.rowconfigure(0, weight=1)
        # width=1 for the same reason as the log: the default 80 columns would
        # be wider than the page.
        self.nearby_text = tk.Text(card.inner, wrap="none", height=14, width=1,
                                   font=theme.MONO_FONT, state="disabled",
                                   padx=8, pady=6, borderwidth=0,
                                   highlightthickness=0)
        theme.style_text(self.nearby_text, palette)
        self.nearby_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(card.inner, orient="vertical",
                               command=self.nearby_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.nearby_text.configure(yscrollcommand=scroll.set)

        tools = tk.Frame(body, background=palette.bg)
        tools.grid(row=4, column=0, sticky="ew", padx=self.px(26),
                   pady=(self.px(10), self.px(16)))

        self.scan_button = ttk.Button(tools, text=self._scan_label(),
                                      command=self._toggle_scan)
        self.scan_button.pack(side="left")
        ttk.Button(tools, text=i18n.t("Clear"),
                   command=self._clear_nearby).pack(side="left", padx=self.px(10))
        self._paintable.extend([self.link_state, note, card, tools])
        # Wrap both lines of text to the width the list card has: it spans the
        # same insets, so neither can run past the window on a scaled desktop.
        card.bind("<Configure>",
                  lambda event: (
                      note.configure(
                          wraplength=max(self.px(200), event.width - self.px(4))),
                      self.link_state.configure(
                          wraplength=max(self.px(200), event.width - self.px(4)))),
                  add="+")

    def _show_link_state(self, state: dict[str, object] | None) -> None:
        """Say what the link is doing, and note the moments it changes.

        Nothing below the window keeps these times: the peripheral reports that a
        host subscribed or left, and only the window can turn that into "since
        when", which is what a user comparing two attempts wants to see.
        """
        now = time.time()
        up = bool(state and state.get("connected"))
        if up and not self._link_up:
            self._link_since, self._link_ended = now, None
        elif not up and self._link_up:
            self._link_since, self._link_ended = None, now
        self._link_up = up
        if state is not None and "aborted" in str(state.get("advertising") or ""):
            if self._abort_since is None:
                self._abort_since = now
        else:
            self._abort_since = None
        aborted_for = 0.0 if self._abort_since is None else now - self._abort_since
        self.link_state.configure(
            text=link_summary(state, since=self._link_since,
                              last_up=self._link_ended, aborted_for=aborted_for))
        self.link_state.set_tone("accent" if up else "muted")


    def _scan_label(self) -> str:
        return i18n.t("Stop scanning") if self._scanner.running else i18n.t("Scan")

    def _toggle_scan(self) -> None:
        if self._scanner.running:
            self._scanner.stop()
            self.scan_button.configure(text=self._scan_label())
            return
        self._start_scan()

    def _start_scan(self) -> None:
        """Begin scanning, and report why if the radio will not."""
        try:
            self._scanner.start()
        except Exception as exc:  # noqa: BLE001 - the reason is what matters
            self._notify(str(exc), error=True)
            log.warning("cannot scan for devices: %s", exc)
            return
        self.scan_button.configure(text=self._scan_label())
        self._pump_scan()

    def _pump_scan(self) -> None:
        if self._closing or not self._scanner.running:
            return
        seen = self._scanner.snapshot()
        lines = []
        for device in seen:
            services = ",".join(device.services[:4])
            lines.append(f"  {device.rssi:5} dBm  {device.address}  "
                         f"{device.name or i18n.t("unnamed")}"
                         f"{'  ' + services if services else ''}")
        if not lines:
            lines = ["  " + i18n.t("No devices seen yet")]
        self.nearby_text.configure(state="normal")
        self.nearby_text.delete("1.0", "end")
        self.nearby_text.insert("end", "\n".join(lines) + "\n")
        self.nearby_text.configure(state="disabled")
        self.root.after(SCAN_POLL_MS, self._pump_scan)

    def _clear_nearby(self) -> None:
        self._scanner.clear()
        self.nearby_text.configure(state="normal")
        self.nearby_text.delete("1.0", "end")
        self.nearby_text.configure(state="disabled")

    # -- the bridge itself ------------------------------------------------

    def _bridge_label(self) -> str:
        """What the sidebar and the tray call holding the bridge still."""
        return i18n.t("Resume") if self._bridge_paused else i18n.t("Pause")

    def toggle_bridge(self) -> None:
        """Hold the bridge still, or let it go again.

        The host keeps running and the target stays paired; only the routing stops,
        and the PC gets its keyboard and mouse back while it is held.
        """
        self._bridge_paused = not self._bridge_paused
        self.service.set_paused(self._bridge_paused)
        self.sidebar.items["pause"].set_text(
            self._bridge_label(), "play" if self._bridge_paused else "pause")
        self._notify(i18n.t("Paused") if self._bridge_paused else i18n.t("Running"))

    @staticmethod
    def _next_row(frame: tk.Widget) -> int:
        rows = [int(slave.grid_info()["row"]) for slave in frame.grid_slaves()]
        return max(rows) + 1 if rows else 0

    # -- pages ------------------------------------------------------------

    def show_page(self, key: str) -> None:
        self._current_page = key
        for name, page in self.pages.items():
            if name == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()
        self.sidebar.select(key)
        # Opening the list starts the scan: a page whose only content is "press
        # Scan" is a step nobody wants to take twice.
        if key == "nearby" and not self._scanner.running:
            self._start_scan()
        if key in self._page_canvas:
            self._sync_page(key)
            self._page_canvas[key].yview_moveto(0.0)

    # -- values -----------------------------------------------------------

    def _fill(self, settings: dict[str, object]) -> None:
        """Show settings in the widgets, without committing them back.

        Setting a variable runs its change callback, which would apply and write
        settings that nobody edited: every value is already what it says. The
        controls are filled without their state animation as well, since a value
        arriving from the file is not a click.
        """
        self.form.load(settings)
        self._loading = True
        widgets.set_animated(False)
        try:
            for name, control in self._controls.items():
                control.write(self.form.values.get(name, ""))
        finally:
            self._loading = False
            widgets.set_animated(True)

    def _read(self) -> dict[str, object]:
        for name, control in self._controls.items():
            value = control.read()
            if value is not None:
                self.form.values[name] = value
        return self.form.settings(self.settings)

    # -- actions ----------------------------------------------------------

    def _changed(self, name: str) -> None:
        """Apply a change, pausing briefly so typing is not committed per key."""
        if self._loading:                 # the form is being filled, not edited
            return
        self._cancel_commit()
        delay = COMMIT_DELAY_MS if FIELDS_BY_NAME[name].kind in (
            "text", "int", "float", "keys", "remap") else 0
        self._commit_job = self.root.after(delay, self._commit)

    def _cancel_commit(self) -> None:
        job, self._commit_job = self._commit_job, None
        if job is None:
            return
        try:
            self.root.after_cancel(job)
        except tk.TclError:                  # it has already run
            pass

    def _commit(self) -> None:
        # A commit that was still waiting would only do this again.
        self._cancel_commit()
        try:
            settings = self._read()
            built = config.build(settings)
        except config.ConfigError as exc:
            # The controls keep what was typed: filling the form again from the
            # last saved settings would take a line out from under the cursor,
            # and the half-finished edit is the thing the message is about.
            self._notify(str(exc), error=True)
            return
        self.settings = settings
        # The language is the one setting that changes the window itself.
        if i18n.language() != settings.get(config.LOCALE_FIELD):
            i18n.set_language(settings.get(config.LOCALE_FIELD))
            theme.use_language(i18n.language(), self.root)
            self._rebuild()
        self.service.apply_config(built)
        self._apply_windows_settings(settings)
        try:
            config.write(self.config_path, settings)
        except OSError as exc:
            self._notify(i18n.t("Cannot write {path}: {error}").format(
                path=self.config_path, error=exc), error=True)
            return
        self._notify(i18n.t("Saved"))

    def _apply_windows_settings(self, settings: dict[str, object]) -> None:
        """Push the settings Windows owns, once they have changed."""
        app = config.app_settings(settings)
        if app == getattr(self, "_windows_settings", None):
            return
        self._windows_settings = app
        if not startup.apply(bool(app["start_with_windows"]), self.config_path):
            self._notify(i18n.t("Could not change the startup entry"), error=True)

    def reload(self) -> None:
        try:
            settings = config.read(self.config_path)
        except config.ConfigError as exc:
            messagebox.showerror("Winborder", str(exc), parent=self.root)
            return
        self.settings = settings
        self._fill(settings)
        self.service.apply_config(config.build(settings))
        self._notify(i18n.t("Reloaded {path}").format(path=self.config_path))

    def hide(self) -> None:
        self.root.withdraw()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        theme.apply_title_bar(self.root, self.palette)

    def stop(self) -> None:
        self._closing = True
        self.tray.stop()
        self.service.request_stop()
        self.root.quit()

    # -- theme ------------------------------------------------------------

    def _apply_theme(self, palette: theme.Theme) -> None:
        self.palette = palette
        self.watcher.theme = palette
        theme.apply(self.root, ttk.Style(self.root), palette, self.scale)
        # Fit after the window has been laid out: a control only reports the height
        # its style gives it once the toplevel has been mapped, so a measurement
        # taken here would still be the pre-style one.
        self.root.after_idle(self._fit_rows)
        self.root.configure(background=palette.bg)
        self.content.configure(background=palette.bg)
        self.sidebar.repaint(palette)
        for widget in self._paintable:
            repaint = getattr(widget, "repaint", None)
            if repaint is not None:
                repaint(palette)
        for name in ("log_text", "nearby_text"):
            widget = getattr(self, name, None)
            if widget is not None:
                theme.style_text(widget, palette)
        self._apply_caption(palette)

    def _fit_rows(self) -> None:
        """Give every row the height its control needs, once the style is in force."""
        for row in getattr(self, "_rows", ()):
            row.fit()

    def _apply_caption(self, palette: theme.Theme) -> None:
        """Colour the caption once the window exists.

        Windows accepts the attribute before the window is mapped and then draws
        the caption from the system theme anyway, so it is applied again after
        the window is on screen and whenever it is shown.
        """
        self._cancel_timers()
        self._caption_jobs = [
            self.root.after(delay, lambda: theme.apply_title_bar(self.root, palette))
            for delay in (0, 120, 400, 1200)]
        if not getattr(self, "_caption_bound", False):
            self._caption_bound = True
            self.root.bind("<Map>",
                           lambda _event: theme.apply_title_bar(self.root, palette),
                           add="+")
            self.root.bind("<Destroy>", self._cancel_timers, add="+")

    def _cancel_timers(self, event=None) -> None:
        self._scanner.stop()
        """Drop the timers that are still pending.

        A timer that fires after its widget is gone is reported by Tk as an
        error on a command that no longer exists, so they are cancelled rather
        than left to run out.
        """
        if event is not None and event.widget is not self.root:
            return
        self._cancel_commit()
        jobs, self._caption_jobs = self._caption_jobs, []
        for name in ("_message_job", "_focus_job"):
            job = getattr(self, name, None)
            if job is not None:
                jobs.append(job)
                setattr(self, name, None)
        for job in jobs:
            try:
                self.root.after_cancel(job)
            except tk.TclError:                  # the window is already gone
                pass

    # -- threads ----------------------------------------------------------

    def _open_from_tray(self) -> None:
        self._events.put(("show", None))

    def _quit_from_tray(self) -> None:
        self._events.put(("quit", None))

    def _reload_from_tray(self) -> None:
        self._events.put(("reload", None))

    def _pause_from_tray(self) -> None:
        self._events.put(("pause", None))

    def _open_config_file(self) -> None:
        self._events.put(("open-config", None))

    def _type_clipboard_from_tray(self) -> None:
        """Type the clipboard into the target, and answer in the window."""
        self._events.put(("type-clipboard", None))

    def type_clipboard(self) -> None:
        """Send the clipboard as keystrokes, and say what became of the request.

        The window is the only place that can say it: the tray has no room for a
        sentence, and "nothing happened" is the answer a silent refusal gives.
        """
        outcome = self.service.type_clipboard()
        result = outcome["result"]
        if result == "empty":
            self._notify(i18n.t("The clipboard holds no text this layout can type"),
                         error=True)
        elif result == "no_target":
            self._notify(i18n.t("The target is not connected"), error=True)
        elif result == "paused":
            self._notify(i18n.t("The bridge is paused"), error=True)
        elif outcome["skipped"]:
            self._notify(i18n.t("Typing {count} characters, {skipped} left out").format(
                count=outcome["keys"], skipped=outcome["skipped"]))
        else:
            self._notify(i18n.t("Typing {count} characters").format(
                count=outcome["keys"]))

    def _run_service(self) -> None:
        try:
            self.service.run()
        except Exception:  # noqa: BLE001 - the window has to say what happened
            log.exception("the bridge stopped with an error")
            self._events.put(("show", None))

    def _pump_events(self) -> None:
        while True:
            try:
                action, _payload = self._events.get_nowait()
            except queue.Empty:
                break
            if action == "show":
                self.show()
            elif action == "quit":
                self.stop()
                return
            elif action == "reload":
                self.reload()
            elif action == "pause":
                self.toggle_bridge()
            elif action == "open-config":
                self._open_path(self.config_path)
            elif action == "type-clipboard":
                self.type_clipboard()
        if not self._closing:
            self.root.after(POLL_MS, self._pump_events)

    def _pump_log(self) -> None:
        # INFO and above: the window is for whoever is using the program, and a
        # debug line about an asyncio proactor is not something they can act on.
        lines, total = self.log_buffer.snapshot(self._log_lines,
                                                level=logging.INFO)
        if self._paused:
            # The cursor stays where it is, so nothing is lost and the same
            # lines are handed over again once the view is let go.
            self._waiting = len(lines)
            self._show_waiting()
        else:
            self._log_lines = total
            self._waiting = 0
            self._show_waiting()
            if lines:
                self.log_text.configure(state="normal")
                self.log_text.insert("end", "\n".join(lines) + "\n")
                if self.scroll_var.get():
                    self.log_text.see("end")
                self.log_text.configure(state="disabled")
        if not self._closing:
            self.root.after(POLL_MS, self._pump_log)

    def _show_waiting(self) -> None:
        """Say how much has arrived while the view was held still."""
        self.waiting.configure(
            text=i18n.t("{count} new lines").format(count=self._waiting)
            if self._paused and self._waiting else "")

    def _pump_status(self) -> None:
        try:
            state = self.service.status()
        except Exception as exc:  # noqa: BLE001 - the window outlives a failure
            diagnostics.failed("reading the service status", exc)
            state = None
        if state is not None and hasattr(self, "status_rows"):
            cursor = state["cursor"]
            pointer = state["pointer"]
            mode = i18n.t("target" if state["mode"] == "target" else "pc")
            if state.get("paused"):
                mode = i18n.t("Paused")
            link = i18n.t("up" if state["connected"] else "down")
            written, bad = i18n.t("written"), i18n.t("bad")
            self.status_rows["mode"].configure(text=mode)
            self.status_rows["cursor"].configure(
                text=f"({cursor[0]:.3f}, {cursor[1]:.3f})")
            self.status_rows["pointer"].configure(
                text=f"({pointer[0]:.3f}, {pointer[1]:.3f})")
            self.status_rows["travel"].configure(text=f"{state['travel'] * 100:+.1f}%")
            self.status_rows["link"].configure(
                text=f"{link}   {written} {state['written']}   "
                     f"{bad} {state['bad']}")
        if hasattr(self, "link_state"):
            # Outside the guard above: a service that cannot be asked is itself
            # worth saying on the Devices page.
            self._show_link_state(state)
        if not self._closing:
            self.root.after(POLL_MS, self._pump_status)

    def _pump_theme(self) -> None:
        palette = self.watcher.refresh()
        if palette is not None:
            self._apply_theme(palette)
        if not self._closing:
            self.root.after(THEME_POLL_MS, self._pump_theme)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _notify(self, message: str, error: bool = False) -> None:
        if error:
            log.warning("%s", message)
        self.message.configure(text=message)
        self.message.set_colour("#e06c75" if error else None)
        if not error:
            self.message.set_tone("muted")
        if self._message_job is not None:
            self.root.after_cancel(self._message_job)
        self._message_job = self.root.after(6000, self._clear_message)

    def _clear_message(self) -> None:
        self._message_job = None
        self.message.configure(text="")

    @staticmethod
    def _open_path(path: str) -> None:
        try:
            os.startfile(path)  # noqa: S606 - opening our own settings file
        except OSError:
            subprocess.Popen(["notepad.exe", path])  # noqa: S607

    @staticmethod
    def _open_url(url: str) -> None:
        """Hand a web address to the default browser.

        No notepad fallback: an address that fails to open is a browser problem,
        and opening it as text would be worse than doing nothing.
        """
        try:
            os.startfile(url)  # noqa: S606 - a web address, not a file
        except OSError as exc:
            diagnostics.failed("opening the repository", exc)

    # -- run --------------------------------------------------------------

    def run(self) -> int:
        """Start the bridge, the tray icon and the window."""
        logging.getLogger().addHandler(self.log_buffer)
        if bool(self.settings.get("start_hidden")):
            self.root.withdraw()
        if not self.tray.start():
            log.warning("no notification area icon; use the window to control it")
        self._service_thread.start()
        self.root.after(POLL_MS, self._pump_events)
        self.root.after(POLL_MS, self._pump_log)
        self.root.after(POLL_MS, self._pump_status)
        self.root.after(THEME_POLL_MS, self._pump_theme)
        try:
            self.root.mainloop()
        finally:
            logging.getLogger().removeHandler(self.log_buffer)
        return 0
