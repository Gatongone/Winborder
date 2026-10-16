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
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import config, i18n, icon, keymap, model, startup, theme, trace
from .logbuffer import LogBuffer
from .service import Service
from pathlib import Path
from .tray import TrayIcon
from . import widgets
from .widgets import Card, CheckBox, Icon, Row, Separator, Sidebar, \
    ToggleSwitch

log = logging.getLogger("winborder.ui")

POLL_MS = 200
THEME_POLL_MS = 2000
COMMIT_DELAY_MS = 400


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
    Field("port", "Serial port", "text", "Empty finds the board automatically"),
    Field("baudrate", "Baud rate", "int", "115200 matches the firmware"),
    Field("side", "Target side", "choice",
          "Which side of the PC the target device sits on",
          tuple(side.value for side in model.Side)),
    Field("sensitivity", "Pointer gain", "float",
          "1.0 moves the target pointer as far as the PC cursor"),
    Field("accel", "Speed gain", "float",
          "Extra pointer gain proportional to how fast the mouse moves"),
    Field("pullback_distance", "Return pull", "int",
          "Motion towards the PC that returns control. Raise it if a return "
          "arrives while the target pointer still looks inside its screen"),
    Field("invert_wheel_v", "Invert vertical scroll", "bool",
          "Scroll up on the target means scroll up on the PC"),
    Field("invert_wheel_h", "Invert horizontal scroll", "bool"),
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
          "Comma separated key names, for example F1"),
    Field("toggle_edge_keys", "Toggle edge crossing", "keys",
          "Comma separated key names, for example F2"),
    Field("forward_consumer_keys", "Forward media keys", "bool",
          "Volume and transport keys go to the target"),
    Field("capture_mouse_buttons", "Capture mouse buttons", "bool",
          "Clicks go to the target while it has control"),
    Field("start_with_windows", "Start with Windows", "bool",
          "Starts the host, minimised to the notification area, when you sign in"),
    Field("start_hidden", "Start hidden", "bool",
          "Open with the notification area icon only, without this window"),
    Field("language", "Language", "choice",
          "The language of this window. Changes apply immediately",
          i18n.codes()),
    Field("remap", "Remap keys", "remap",
          "One From=To per line, for example CapsLock=Escape. The PC is unaffected"),
)

FIELDS_BY_NAME = {field.name: field for field in FIELDS}

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


# page key, title, icon, description, groups of rows
PAGES: tuple[tuple[str, str, str, str,
                  tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]], ...] = (
    ("status", "Status", "status", "What the bridge is doing right now", ()),
    ("generic", "Generic", "gear",
     "Startup, maintenance and what is running",
     (("Startup", (("start_with_windows",), ("start_hidden",))),
      ("Interface", (("language",),)))),
    ("bridge", "Bridge", "link",
     "The serial link to the board and where the target sits",
     (("Connection", (("port", "baudrate"), ("side",))),)),
    ("pointer", "Pointer", "pointer", "How mouse movement reaches the target",
     (("Movement", (("sensitivity", "accel"),)),
      ("Returning", (("pullback_distance",), ("pullback_exit",))),
      ("Scrolling", (("notch_up", "notch_down"),
                     ("invert_wheel_v", "invert_wheel_h"))))),
    ("edge", "Edge crossing", "edge",
     "Handing the keyboard and mouse over at the screen edge",
     (("Crossing", (("edge_inset", "enter_cooldown"),
                    ("exit_clear_distance",))),)),
    ("keyboard", "Keyboard", "keyboard",
     "Keys the host keeps for itself, and what the target receives",
     (("Host keys", (("panic_keys",), ("toggle_edge_keys",))),
      ("Target keyboard", (("capture_mouse_buttons", "forward_consumer_keys"),
                           ("remap",))))),
    ("log", "Log", "log", "Everything the host and the board report", ()),
)

# The master switch shown in a page header, where the page has one.
PAGE_SWITCHES = {"edge": "edge_trigger_enabled"}

# The read-only rows of the status page: key, title, description. The words the
# values are made of are translated where they are written. These rows carry a
# wider value column than a settings row: the link line names three counters.
STATUS_ROWS: tuple[tuple[str, str, str], ...] = (
    ("mode", "Mode", "Which side has the keyboard and mouse"),
    ("cursor", "PC cursor", "fraction of the PC screen"),
    ("pointer", "Target pointer", "fraction of the tracked surface"),
    ("travel", "Travel", "motion since the target was entered, negative on "
                         "the way back"),
    ("link", "Device link", "frames the board acknowledged"),
)
STATUS_CONTROL_WIDTH = 300

# The read-only rows of the About card, on the Generic page. The settings file
# is a full path, so these rows carry a wider value column than the controls of
# a settings card do.
ABOUT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("version", "Version", "the host and this window"),
    ("runtime", "Running from", "an executable, or Python"),
    ("settings", "Settings file", "the file this window writes"),
)
ABOUT_CONTROL_WIDTH = 360


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
                self.values[field.name] = "\n".join(f"{a}={b}" for a, b in pairs.items())
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
                    out[field.name] = int(text) if field.kind == "int" else float(text)
                except ValueError:
                    raise config.ConfigError(
                        i18n.t("{label} must be a number").format(label=label)) from None
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
                for line in str(raw).splitlines():
                    entry = line.strip()
                    if not entry:
                        continue
                    source, _, target = entry.partition("=")
                    source, target = source.strip(), target.strip()
                    if not source or not target:
                        raise config.ConfigError(
                            i18n.t("{label}: expected From=To, got {entry}").format(
                                label=label, entry=entry))
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
                             paused=lambda: self._bridge_paused)
        self._service_thread = threading.Thread(target=self._run_service,
                                                name="winborder-service", daemon=True)

    def px(self, value: float) -> int:
        """A pixel size at the display scale."""
        return max(1, int(round(value * self.scale)))

    # -- construction -----------------------------------------------------

    def _build(self) -> None:
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
        self.message = tk.Label(self.content, text="", font=theme.UI_FONT_SMALL,
                                anchor="w", background=palette.bg,
                                foreground=palette.muted)
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
        hero_title = tk.Label(inner, text=i18n.t(title), font=theme.HERO_FONT,
                              anchor="w", background=palette.surface,
                              foreground=palette.fg)
        hero_title.grid(row=0, column=1, columnspan=2, sticky="w",
                        pady=(self.px(18), 0))
        hero_text = tk.Label(inner, text=i18n.t(text), font=theme.UI_FONT,
                             anchor="w", justify="left",
                             wraplength=self.px(620),
                             background=palette.surface, foreground=palette.muted)
        hero_text.grid(row=1, column=1, columnspan=2, sticky="w",
                       pady=(self.px(2), self.px(18)))
        self._paintable.extend([hero, hero_title, hero_text])

        switch_name = PAGE_SWITCHES.get(key)
        if switch_name is not None:
            variable = tk.BooleanVar()
            self._variables[switch_name] = variable
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
            label = tk.Label(body, text=i18n.t(title), font=theme.SECTION_FONT,
                             anchor="w", background=palette.bg,
                             foreground=palette.muted)
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
                row = Row(card.inner, palette, i18n.t(field.label),
                          i18n.t(field.hint),
                          make_control=lambda parent, name=name:
                          self._control(parent, name))
                row.grid(row=index * 2, column=0, sticky="ew")
                self._paintable.append(row)

    def _control(self, parent: tk.Widget, name: str) -> tk.Widget:
        palette = self.palette
        field = FIELDS_BY_NAME[name]
        if field.kind == "bool":
            variable = self._variables.get(name) or tk.BooleanVar()
            self._variables[name] = variable
            return ToggleSwitch(parent, variable, palette,
                                command=lambda: self._changed(name),
                                background=palette.surface)
        variable = tk.StringVar()
        self._variables[name] = variable
        if field.kind == "choice":
            control: tk.Widget = ttk.Combobox(parent, textvariable=variable, width=11,
                                              values=list(choice_labels(field)),
                                              state="readonly")
        elif field.kind == "remap":
            control = ttk.Entry(parent, textvariable=variable, width=30)
        elif field.kind in ("int", "float"):
            control = ttk.Entry(parent, textvariable=variable, width=12)
        else:
            control = ttk.Entry(parent, textvariable=variable, width=20)
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
                value = tk.Label(parent, text="", font=theme.MONO_FONT, anchor="e",
                                 background=self.palette.surface,
                                 foreground=self.palette.fg)
                self.status_rows[key] = value
                self._paintable.append(value)
                return value

            row = Row(card.inner, palette, i18n.t(title), i18n.t(description),
                      make_value, control_width=STATUS_CONTROL_WIDTH)
            row.grid(row=index * 2, column=0, sticky="ew")
            self._paintable.append(row)

    def _about_page(self, body: tk.Frame) -> None:
        """Where things live, and what is running."""
        palette = self.palette
        label = tk.Label(body, text=i18n.t("About"), font=theme.SECTION_FONT,
                         anchor="w", background=palette.bg,
                         foreground=palette.muted)
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
                value = tk.Label(parent, text=facts.get(key, ""),
                                 font=theme.MONO_FONT, anchor="e", justify="right",
                                 wraplength=self.px(ABOUT_CONTROL_WIDTH - 10),
                                 background=self.palette.surface,
                                 foreground=self.palette.fg)
                self.about_rows[key] = value
                self._paintable.append(value)
                return value

            row = Row(card.inner, palette, i18n.t(title), i18n.t(description),
                      make_value, control_width=ABOUT_CONTROL_WIDTH)
            row.grid(row=index * 2, column=0, sticky="ew")
            self._paintable.append(row)

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
        facts["settings"] = str(Path(self.config_path).resolve())
        return facts

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
        self.log_text = tk.Text(card.inner, wrap="char", height=16,
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
        self.scroll_var = tk.BooleanVar(value=True)
        follow = tk.Frame(tools, background=palette.bg)
        follow.pack(side="left", padx=(self.px(10), 0))
        box = CheckBox(follow, self.scroll_var, palette, background=palette.bg)
        box.pack(side="left")
        label = tk.Label(follow, text=i18n.t("Auto-scroll"), font=theme.UI_FONT,
                         background=palette.bg,
                         foreground=palette.fg, cursor="hand2")
        label.pack(side="left", padx=(self.px(8), 0))
        for widget in (box, label):
            widget.bind("<Button-1>", lambda _event: box._toggle())
        self._paintable.extend([follow, box, label])
        ttk.Button(tools, text=i18n.t("Clear"), command=self._clear_log).pack(
            side="left", padx=self.px(10))
        self.waiting = tk.Label(tools, text="", font=theme.UI_FONT_SMALL,
                                background=palette.bg, foreground=palette.muted)
        self.waiting.pack(side="right")
        self._paintable.extend([card, tools, self.waiting])

    def _pause_label(self) -> str:
        return i18n.t("Resume log") if self._paused else i18n.t("Pause log")

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_button.configure(text=self._pause_label())
        self._show_waiting()

    # -- the bridge itself ------------------------------------------------

    def _bridge_label(self) -> str:
        """What the sidebar and the tray call holding the bridge still."""
        return i18n.t("Resume") if self._bridge_paused else i18n.t("Pause")

    def toggle_bridge(self) -> None:
        """Hold the bridge still, or let it go again.

        The host keeps running and the board stays paired; only the routing stops,
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
            for name, variable in self._variables.items():
                value = self.form.values.get(name, "")
                field = FIELDS_BY_NAME.get(name)
                if isinstance(variable, tk.BooleanVar):
                    variable.set(bool(value))
                elif field is not None and field.kind == "choice":
                    # A dropdown shows a label; the value it stands for is what
                    # the form holds and what is written to the file.
                    labels = choice_labels(field)
                    raw = str(value)
                    variable.set(labels[field.choices.index(raw)]
                                 if raw in field.choices else "")
                else:
                    variable.set(str(value))
        finally:
            self._loading = False
            widgets.set_animated(True)

    def _read(self) -> dict[str, object]:
        for name, variable in self._variables.items():
            field = FIELDS_BY_NAME.get(name)
            if field is not None:
                if field.kind == "choice":
                    value = choice_value(field, variable.get())
                    if value is not None:
                        self.form.values[name] = value
                else:
                    self.form.values[name] = variable.get()
        settings = self.form.settings(self.settings)
        for name, variable in self._variables.items():
            if name in startup.APP_FIELDS:
                settings[name] = bool(variable.get())
        return settings

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
            self._notify(str(exc), error=True)
            self._fill(self.settings)
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
        self.root.configure(background=palette.bg)
        self.content.configure(background=palette.bg)
        self.message.configure(background=palette.bg, foreground=palette.muted)
        self.sidebar.repaint(palette)
        for widget in self._paintable:
            repaint = getattr(widget, "repaint", None)
            if repaint is not None:
                repaint(palette)
        for row in getattr(self, "status_rows", {}).values():
            row.configure(background=palette.surface, foreground=palette.fg)
        if hasattr(self, "log_text"):
            theme.style_text(self.log_text, palette)
        self._apply_caption(palette)

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
        if not self._closing:
            self.root.after(POLL_MS, self._pump_events)

    def _pump_log(self) -> None:
        lines, total = self.log_buffer.snapshot(self._log_lines)
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
        except Exception:  # noqa: BLE001 - the window outlives a failed service
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
        self.message.configure(
            text=message,
            foreground="#e06c75" if error else self.palette.muted)
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
