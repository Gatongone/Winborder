"""Tests for the pieces the settings window is built from.

The window itself needs a display, so only the parts that decide what a setting
means are covered here.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from tkinter import ttk

from winborder import config, i18n, icon, logbuffer, model, startup, theme, \
    trace, ui, widgets


class TestSettingsForm(unittest.TestCase):
    def test_every_setting_has_a_field(self) -> None:
        names = {field.name for field in ui.FIELDS}
        for field in dataclasses.fields(model.Config):
            with self.subTest(field=field.name):
                if field.name == "remap":
                    continue          # the form edits it, the file stores it
                self.assertIn(field.name, names)
        self.assertTrue(set(config.LINK_FIELDS) <= names)

    def test_labels_are_unique(self) -> None:
        labels = [field.label for field in ui.FIELDS]
        self.assertEqual(len(labels), len(set(labels)))

    def test_round_trip_keeps_values(self) -> None:
        settings = config.defaults()
        form = ui.SettingsForm(settings)
        self.assertEqual(form.settings({}), settings)

    def test_keys_are_edited_by_name(self) -> None:
        form = ui.SettingsForm(config.defaults())
        self.assertEqual(form.values["panic_keys"], "F1")
        form.values["panic_keys"] = "F12, LeftCtrl"
        self.assertEqual(form.settings({})["panic_keys"], ["F12", "LeftCtrl"])

    def test_remap_is_edited_as_lines(self) -> None:
        form = ui.SettingsForm({"remap": {"CapsLock": "Escape"}})
        self.assertEqual(form.values["remap"], "CapsLock=Escape")
        form.values["remap"] = "CapsLock=LeftCtrl\nMenu=Escape"
        self.assertEqual(form.settings({})["remap"],
                         {"CapsLock": "LeftCtrl", "Menu": "Escape"})

    def test_blank_number_keeps_the_default(self) -> None:
        form = ui.SettingsForm(config.defaults())
        form.values["pullback_distance"] = ""
        self.assertNotIn("pullback_distance", form.settings({}))

    def test_bad_input_is_rejected(self) -> None:
        for name, value in (("pullback_distance", "soon"), ("panic_keys", "Nope"),
                            ("remap", "CapsLock"), ("remap", "Nope=Escape")):
            with self.subTest(name=name, value=value):
                form = ui.SettingsForm(config.defaults())
                form.values[name] = value
                with self.assertRaises(config.ConfigError):
                    form.settings({})

    def test_form_values_build_a_config(self) -> None:
        form = ui.SettingsForm(config.defaults())
        form.values["side"] = "top"
        form.values["sensitivity"] = "1.5"
        built = config.build(form.settings({}))
        self.assertIs(built.side, model.Side.TOP)
        self.assertEqual(built.sensitivity, 1.5)


class TestSettingsWriteBack(unittest.TestCase):
    """What the window saves has to load back unchanged."""

    def test_saved_settings_reload(self) -> None:
        directory = tempfile.mkdtemp(prefix="winborder_ui_")
        path = Path(directory) / "winborder.json"
        path.write_text(json.dumps(config.defaults()), encoding="utf-8")
        settings = config.read(path)
        form = ui.SettingsForm(settings)
        form.values["side"] = "right"
        form.values["panic_keys"] = "F12"
        form.values["remap"] = "CapsLock=Escape"
        edited = form.settings(settings)

        config.write(path, edited)
        again = config.read(path)
        self.assertEqual(again["side"], "right")
        self.assertEqual(again["panic_keys"], ["F12"])
        self.assertEqual(again["remap"], {"CapsLock": "Escape"})
        self.assertEqual(config.build(again), config.build(edited))

    def test_written_keys_are_names(self) -> None:
        written = config.in_file_form({"panic_keys": (0x70,), "side": model.Side.TOP,
                                        "remap": ((0x14, 0x29),)})
        self.assertEqual(written["panic_keys"], ["F1"])
        self.assertEqual(written["side"], "top")
        self.assertEqual(written["remap"], {"CapsLock": "Escape"})


class TestLogBuffer(unittest.TestCase):
    def setUp(self) -> None:
        self.buffer = logbuffer.LogBuffer(capacity=3)
        self.log = logging.getLogger("winborder.test")
        self.log.setLevel(logging.DEBUG)
        self.log.addHandler(self.buffer)
        self.addCleanup(self.log.removeHandler, self.buffer)

    def test_reads_each_line_once(self) -> None:
        self.log.info("one")
        self.log.info("two")
        lines, seen = self.buffer.snapshot(0)
        self.assertEqual([line.split()[-1] for line in lines], ["one", "two"])
        more, seen = self.buffer.snapshot(seen)
        self.assertEqual(more, [])
        self.log.info("three")
        more, _ = self.buffer.snapshot(seen)
        self.assertEqual([line.split()[-1] for line in more], ["three"])

    def test_old_lines_are_dropped(self) -> None:
        for name in ("one", "two", "three", "four"):
            self.log.info("%s", name)
        lines, total = self.buffer.snapshot(0)
        self.assertEqual(len(lines), 3)
        self.assertEqual(total, 4)


class TestRuntimeConfigChange(unittest.TestCase):
    def test_router_accepts_new_settings(self) -> None:
        router = model.Router(config=model.Config(side=model.Side.BOTTOM),
                              screen=(1920, 1080))
        router.note_link_ok(1000.0)
        router.tick([model.MouseMove(0, 0)], 1000.0, (960, 1079))
        router.tick([model.MouseMove(0, 40)], 1000.1, (960, 1079))
        self.assertGreater(router._crossing_travel(), 0.0)

        router.set_config(model.Config(side=model.Side.TOP, pullback_distance=123))
        self.assertIs(router.cfg.side, model.Side.TOP)
        self.assertEqual(router.cfg.pullback_distance, 123)
        self.assertEqual(router._crossing_travel(), 0.0)

    def test_remap_follows_the_new_settings(self) -> None:
        router = model.Router(config=model.Config(side=model.Side.RIGHT),
                              screen=(1920, 1080))
        router.note_link_ok(1000.0)
        router.tick([model.MouseMove(0, 0)], 1000.0, (1919, 540))
        router.set_config(model.Config(side=model.Side.RIGHT,
                                       remap=((0x41, 0x29),)))   # A sends Escape
        effects = router.tick([model.KeyPress(0x41, True)], 1000.1, (1919, 540))
        states = [e.payload for e in effects
                  if isinstance(e, model.SendFrame)
                  and e.msg_type == model.ipc.MsgType.STATE]
        self.assertEqual(states[-1][2], 0x29)


class TestStatusLine(unittest.TestCase):
    def state(self, **overrides) -> dict[str, object]:
        base = {"mode": "pc", "cursor": (0.5, 1.0), "pointer": (0.25, 0.5),
                "travel": 0.0, "frames": 10, "written": 9, "bad": 0,
                "connected": True}
        base.update(overrides)
        return base

    def test_pc_line_reports_the_link(self) -> None:
        line = trace.StatusFormatter().line(self.state())
        self.assertIn("written=9", line)
        self.assertIn("bad=0", line)

    def test_target_line_reports_travel(self) -> None:
        formatter = trace.StatusFormatter()
        line = formatter.line(self.state(mode="target", travel=-0.5))
        self.assertIn("travel=-50.0%", line)

    def test_repeated_target_snapshots_are_skipped(self) -> None:
        formatter = trace.StatusFormatter()
        state = self.state(mode="target")
        self.assertIsNotNone(formatter.line(state))
        self.assertIsNone(formatter.line(state))

    def test_change_is_shown_as_a_delta(self) -> None:
        formatter = trace.StatusFormatter()
        formatter.line(self.state(mode="target"))
        line = formatter.line(self.state(mode="target", pointer=(0.30, 0.5)))
        self.assertIn("d=(+0.050,+0.000)", line)


if __name__ == "__main__":
    unittest.main()


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16)


class TestWidgetGeometry(unittest.TestCase):
    """The drawn controls have to line up, which is easy to get wrong."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.addCleanup(widgets.set_animated, True)
        # These are about where the parts are, so the controls are put in their
        # state at once rather than travelling to it.
        widgets.set_animated(False)
        self.palette = theme.system_theme()

    def row_of(self, widget, y: int) -> list[tuple[int, int, int]]:
        """The colours across one row of a rendered control."""
        return [widget.image.get(x, y) for x in range(widget.image.width())]

    def test_switch_is_round_at_both_ends(self) -> None:
        variable = tk.BooleanVar(value=True)
        switch = widgets.ToggleSwitch(self.root, variable, self.palette,
                                      background="#2b2b2b")
        centre = switch.height // 2
        row = self.row_of(switch, centre)
        self.assertEqual(len(row), switch.width)
        # A rounded end leaves the corner pixels showing the background.
        self.assertNotEqual(row[0], row[switch.height // 2])
        self.assertNotEqual(row[-1], row[switch.width - switch.height // 2])

    def test_switch_knob_is_inside_the_track(self) -> None:
        variable = tk.BooleanVar(value=False)
        switch = widgets.ToggleSwitch(self.root, variable, self.palette,
                                      background="#2b2b2b")
        for state in (False, True):
            variable.set(state)
            centre = switch.height // 2
            row = self.row_of(switch, centre)
            # The knob is white when on and the muted colour when off; match it
            # rather than brightness, because the track itself is the accent.
            wanted = (255, 255, 255) if state else _rgb(self.palette.muted)
            knob = [index for index, pixel in enumerate(row)
                    if all(abs(pixel[channel] - wanted[channel]) <= 10
                           for channel in range(3))]
            with self.subTest(state=state):
                self.assertTrue(knob, "no knob was drawn")
                self.assertGreater(min(knob), 0)
                self.assertLess(max(knob), switch.width - 1)
                middle = (min(knob) + max(knob)) / 2
                expected = (switch.height / 2 if not state
                            else switch.width - switch.height / 2)
                self.assertAlmostEqual(middle, expected, delta=2.0)

    def test_checkbox_draws_a_tick_only_when_set(self) -> None:
        variable = tk.BooleanVar(value=False)
        box = widgets.CheckBox(self.root, variable, self.palette,
                              background="#202020")
        unit = box.size / 17.0
        spot = (int(round(10.4 * unit)), int(round(8.8 * unit)))
        off = box.image.get(*spot)
        variable.set(True)
        on = box.image.get(*spot)
        # Clear of the tick the box shows its own colour; on the tick it shows
        # the contrasting one drawn over the accent. The tick is anti-aliased,
        # so the sample is close to that colour rather than equal to it.
        self.assertEqual(off, _rgb(self.palette.surface))
        wanted = _rgb(self.palette.accent_fg)
        self.assertTrue(all(abs(on[channel] - wanted[channel]) <= 40
                            for channel in range(3)),
                        f"{on} is not close to the tick colour {wanted}")

    def test_every_icon_draws_something(self) -> None:
        canvas = tk.Canvas(self.root, width=32, height=32)
        for name in ("status", "link", "pointer", "edge", "keyboard", "log", "file",
                     "reload", "quit"):
            with self.subTest(icon=name):
                widgets.draw_icon(canvas, name, 16, "#ffffff", "#000000")
                self.assertTrue(canvas.find_all(), f"{name} drew nothing")


class TestStateAnimation(unittest.TestCase):
    """A control moves between its two states instead of jumping."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.addCleanup(widgets.set_animated, True)
        widgets.set_animated(True)
        self.palette = theme.system_theme()

    def settle(self, widget, budget: float = 3.0) -> list[float]:
        """Run the window until the control stops moving, and report the trip."""
        seen = []
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            self.root.update()
            seen.append(widget._progress)
            if widget._job is None:
                break
            time.sleep(0.004)
        return seen

    def test_the_switch_travels_between_its_states(self) -> None:
        variable = tk.BooleanVar(value=False)
        switch = widgets.ToggleSwitch(self.root, variable, self.palette)
        self.assertEqual(switch._progress, 0.0)
        variable.set(True)
        seen = self.settle(switch)
        self.assertTrue(any(0.0 < progress < 1.0 for progress in seen),
                        f"the switch jumped: {seen}")
        self.assertEqual(switch._progress, 1.0)

    def test_the_checkbox_travels_too(self) -> None:
        variable = tk.BooleanVar(value=False)
        box = widgets.CheckBox(self.root, variable, self.palette)
        variable.set(True)
        seen = self.settle(box)
        self.assertTrue(any(0.0 < progress < 1.0 for progress in seen),
                        f"the checkbox jumped: {seen}")
        self.assertEqual(box._progress, 1.0)

    def test_it_can_be_turned_around_on_the_way(self) -> None:
        variable = tk.BooleanVar(value=False)
        switch = widgets.ToggleSwitch(self.root, variable, self.palette)
        variable.set(True)
        for _ in range(2):                    # a frame or two of the trip
            self.root.update()
            time.sleep(0.008)
        variable.set(False)
        seen = self.settle(switch)
        self.assertEqual(switch._progress, 0.0)
        self.assertTrue(all(0.0 <= progress <= 1.0 for progress in seen))

    def test_a_control_at_rest_looks_like_the_palette(self) -> None:
        """The ends of the movement are the two states, not frames of it."""
        variable = tk.BooleanVar(value=False)
        switch = widgets.ToggleSwitch(self.root, variable, self.palette,
                                      background="#2b2b2b")
        centre = switch.height // 2
        off = [switch.image.get(x, centre) for x in range(switch.width)]
        variable.set(True)
        self.settle(switch)
        on = [switch.image.get(x, centre) for x in range(switch.width)]
        self.assertIn(_rgb(self.palette.surface_alt), off)
        self.assertIn(_rgb(self.palette.accent), on)
        self.assertIn((255, 255, 255), on)
        self.assertNotEqual(off, on)

    def test_filling_a_form_does_not_animate(self) -> None:
        widgets.set_animated(False)
        variable = tk.BooleanVar(value=False)
        switch = widgets.ToggleSwitch(self.root, variable, self.palette)
        variable.set(True)
        self.assertEqual(switch._progress, 1.0)
        self.assertIsNone(switch._job)

    def test_destroying_stops_the_movement(self) -> None:
        variable = tk.BooleanVar(value=False)
        switch = widgets.ToggleSwitch(self.root, variable, self.palette)
        variable.set(True)
        self.assertIsNotNone(switch._job)
        switch.destroy()
        self.assertIsNone(switch._job)

    def test_the_tick_is_drawn_on(self) -> None:
        """The tick is a path: it is drawn along, corner first, not faded in."""
        unit = 1.0
        corner = widgets.TICK[1]
        self.assertEqual(widgets.tick_strokes(unit, 0.0), [])

        early = widgets.tick_strokes(unit, 0.2)
        self.assertEqual(len(early), 1, "the first stroke is still being drawn")
        start_x, start_y, end_x, end_y = early[0]
        self.assertEqual((start_x, start_y), widgets.TICK[0])
        self.assertGreater(end_x, widgets.TICK[0][0])
        self.assertLess(end_x, corner[0])

        late = widgets.tick_strokes(unit, 0.6)
        self.assertEqual(len(late), 2, "the corner is behind it by now")
        self.assertEqual(late[0][2:], corner)
        self.assertGreater(late[1][2], corner[0])

        whole = widgets.tick_strokes(unit, 1.0)
        self.assertEqual([stroke[2:] for stroke in whole],
                         [corner, widgets.TICK[2]])


class TestRowLayout(unittest.TestCase):
    """A row owns its control, or every control lands in the card's grid."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.palette = theme.system_theme()

    def test_control_is_built_inside_its_row(self) -> None:
        row = widgets.Row(self.root, self.palette, "Title", "Description",
                          lambda parent: tk.Label(parent, text="control"))
        self.assertIsNotNone(row.control)
        # The control sits in the row's own holder, never in the card's grid.
        self.assertIs(row.control.master, row.holder)
        self.assertIs(row.holder.master, row)
        self.assertEqual(int(row.holder.grid_info()["row"]), 0)
        self.assertEqual(int(row.holder.grid_info()["column"]), 2)

    def test_row_without_a_control_is_allowed(self) -> None:
        row = widgets.Row(self.root, self.palette, "Title", "Description")
        self.assertIsNone(row.control)

    def test_rows_of_a_card_use_separate_grid_rows(self) -> None:
        card = tk.Frame(self.root)
        rows = [widgets.Row(card, self.palette, f"Row {index}", "",
                            lambda parent: tk.Label(parent))
                for index in range(3)]
        for index, row in enumerate(rows):
            row.grid(row=index * 2, column=0, sticky="ew")
        placed = sorted(int(row.grid_info()["row"]) for row in rows)
        self.assertEqual(placed, [0, 2, 4])


class TestWheelRouting(unittest.TestCase):
    """The wheel has to reach the page on screen, not whichever was built last."""

    class Event:
        def __init__(self, delta: int) -> None:
            self.delta = delta

    def make(self, pages: dict, current: str):
        window = ui.SettingsWindow.__new__(ui.SettingsWindow)
        window._page_canvas = pages
        window._current_page = current
        return window

    def test_scrolls_the_page_on_screen(self) -> None:
        class Canvas:
            def __init__(self) -> None:
                self.calls: list[tuple[int, str]] = []

            def yview_scroll(self, steps, what) -> None:
                self.calls.append((steps, what))

        bridge, pointer = Canvas(), Canvas()
        window = self.make({"bridge": bridge, "pointer": pointer}, "bridge")
        window._on_wheel(self.Event(-120))          # wheel down scrolls down
        self.assertEqual(bridge.calls, [(1, "units")])
        self.assertEqual(pointer.calls, [])

    def test_scrolls_up_for_a_wheel_up(self) -> None:
        class Canvas:
            def __init__(self) -> None:
                self.calls: list[tuple[int, str]] = []

            def yview_scroll(self, steps, what) -> None:
                self.calls.append((steps, what))

        canvas = Canvas()
        window = self.make({"bridge": canvas}, "bridge")
        window._on_wheel(self.Event(120))           # wheel up scrolls up
        self.assertEqual(canvas.calls, [(-1, "units")])

    def test_page_without_scrolling_is_ignored(self) -> None:
        window = self.make({"bridge": object()}, "log")
        window._on_wheel(self.Event(-120))          # must not raise


class StubService:
    """Enough of the service for the window to be built and measured."""

    def __init__(self) -> None:
        self.paused: list[bool] = []

    def status(self) -> dict[str, object]:
        return {"mode": "pc", "paused": bool(self.paused and self.paused[-1]),
                "side": "bottom", "cursor": (0.5, 1.0), "pointer": (0.5, 0.5),
                "travel": 0.0, "frames": 0, "written": 0, "bad": 0,
                "connected": True}

    def apply_config(self, config) -> None:
        pass

    def set_paused(self, paused: bool) -> None:
        self.paused.append(bool(paused))

    def request_stop(self) -> None:
        pass

    def run(self) -> None:
        pass


class TestWindowLayout(unittest.TestCase):
    """The window has to fill its width, at whatever scale the display asks."""

    def setUp(self) -> None:
        # A window of its own, with settings of its own: a test must not touch
        # the settings file or the startup entry of whoever is running it.
        directory = tempfile.mkdtemp(prefix="winborder_layout_")
        try:
            self.window = ui.SettingsWindow(
                StubService(), {"port": "COM10"},
                str(Path(directory) / config.DEFAULT_FILENAME))
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.addCleanup(self.window.root.destroy)
        self.window._windows_settings = config.app_settings(self.window.settings)
        self.window.root.update_idletasks()

    def test_showing_the_window_changes_nothing(self) -> None:
        """Filling the form is not editing it."""
        self.window.root.update()
        self.assertFalse(Path(self.window.config_path).exists())

    def test_the_sidebar_holds_the_bridge_and_lets_it_go(self) -> None:
        button = self.window.sidebar.items["pause"]
        self.assertEqual(button.label.cget("text"), "Pause")
        self.window.toggle_bridge()
        self.assertTrue(self.window._bridge_paused)
        self.assertEqual(self.window.service.paused, [True])
        self.assertEqual(button.label.cget("text"), "Resume")
        self.window.toggle_bridge()
        self.assertFalse(self.window._bridge_paused)
        self.assertEqual(self.window.service.paused, [True, False])
        self.assertEqual(button.label.cget("text"), "Pause")

    def test_the_status_page_says_when_it_is_held(self) -> None:
        self.window.toggle_bridge()
        self.window._closing = True              # one pass of the pump
        self.window._pump_status()
        self.assertEqual(self.window.status_rows["mode"].cget("text"),
                         i18n.t("Paused"))

    def test_pages_fill_the_width(self) -> None:
        for key, canvas in self.window._page_canvas.items():
            with self.subTest(page=key):
                body = canvas.winfo_children()[0]
                self.assertEqual(int(body.grid_columnconfigure(0)["weight"]), 1,
                                 "the body column must take the width")

    def test_pages_are_pinned_to_the_top(self) -> None:
        """A short page must not float in the middle of the viewport."""
        for key, canvas in self.window._page_canvas.items():
            with self.subTest(page=key):
                self.window.show_page(key)
                self.window.root.update()
                region = [int(value) for value in
                          str(canvas.cget("scrollregion")).split()]
                self.assertGreaterEqual(region[3] - region[1],
                                        canvas.winfo_height())
                self.assertEqual(canvas.yview()[0], 0.0)

    def test_scrollbar_only_when_the_page_overflows(self) -> None:
        for key, body in self.window._page_body.items():
            with self.subTest(page=key):
                self.window.show_page(key)
                self.window.root.update()
                canvas = self.window._page_canvas[key]
                bar = self.window._page_scroll[key]
                overflows = body.winfo_reqheight() > canvas.winfo_height()
                self.assertEqual(bool(bar.winfo_ismapped()), overflows,
                                 "the bar must follow what the page needs")

    def test_cards_use_the_canvas_width(self) -> None:
        self.window.show_page("bridge")
        self.window.root.update_idletasks()
        canvas = self.window._page_canvas["bridge"]
        body = canvas.winfo_children()[0]
        widths = [child.winfo_width() for child in body.winfo_children()
                  if isinstance(child, widgets.Card)]
        self.assertTrue(widths)
        # Cards keep the page margins and nothing more.
        self.assertGreater(min(widths), canvas.winfo_width() * 0.8)

    def test_drawn_widgets_scale_with_the_display(self) -> None:
        self.assertGreaterEqual(self.window.scale, 1.0)
        self.assertEqual(widgets.scaled(widgets.ICON_SIZE),
                         int(round(widgets.ICON_SIZE * self.window.scale)))


class TestLogHold(unittest.TestCase):
    """Holding the log still must not lose what arrives while it is held."""

    def setUp(self) -> None:
        directory = tempfile.mkdtemp(prefix="winborder_log_")
        try:
            self.window = ui.SettingsWindow(
                StubService(), {"port": "COM10"},
                str(Path(directory) / config.DEFAULT_FILENAME))
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.addCleanup(self.window.root.destroy)
        self.window._windows_settings = config.app_settings(self.window.settings)
        self.window._closing = True           # never reschedule the pump
        root = logging.getLogger()
        root.addHandler(self.window.log_buffer)
        self.addCleanup(root.removeHandler, self.window.log_buffer)
        self.log = logging.getLogger("winborder.holdtest")

    def shown(self) -> str:
        return self.window.log_text.get("1.0", "end")

    def test_lines_arriving_while_it_is_held_are_kept(self) -> None:
        self.log.warning("the first line")
        self.window._pump_log()
        self.assertIn("the first line", self.shown())

        self.window._toggle_pause()
        self.assertEqual(self.window.pause_button.cget("text"), "Resume log")
        self.log.warning("the second line")
        self.window._pump_log()
        self.assertNotIn("the second line", self.shown())
        self.assertIn("1", self.window.waiting.cget("text"))

        self.window._toggle_pause()
        self.assertEqual(self.window.pause_button.cget("text"), "Pause log")
        self.window._pump_log()
        self.assertIn("the second line", self.shown())
        self.assertEqual(self.window.waiting.cget("text"), "")

    def test_nothing_is_shown_twice(self) -> None:
        self.window._toggle_pause()
        self.log.warning("held back")
        self.window._pump_log()
        self.window._pump_log()
        self.window._toggle_pause()
        self.window._pump_log()
        self.window._pump_log()
        self.assertEqual(self.shown().count("held back"), 1)


class TestControlAlignment(unittest.TestCase):
    """Controls in a card share one column, whatever kind they are."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.addCleanup(self.root.destroy)
        self.palette = theme.system_theme()
        widgets.set_scale(theme.ui_scale(self.root))

    def test_controls_share_the_same_column(self) -> None:
        card = tk.Frame(self.root)
        card.pack(fill="x")
        makers = (
            lambda parent: ttk.Entry(parent, width=20),
            lambda parent: ttk.Entry(parent, width=12),
            lambda parent: ttk.Combobox(parent, values=["bottom"],
                                        state="readonly", width=11),
            lambda parent: widgets.ToggleSwitch(parent, tk.BooleanVar(),
                                                self.palette),
            lambda parent: tk.Label(parent, text="0.500", anchor="e"),
        )
        rows = []
        for index, maker in enumerate(makers):
            row = widgets.Row(card, self.palette, f"Row {index}", "description",
                              maker)
            row.pack(fill="x")
            rows.append(row)
        self.root.update()

        widths = {row.holder.winfo_width() for row in rows}
        self.assertEqual(len(widths), 1, "holders must have one width")
        right = {row.control.winfo_rootx() + row.control.winfo_width()
                 for row in rows}
        self.assertEqual(len(right), 1, "controls must share a right edge")

    def test_controls_keep_their_height(self) -> None:
        """A fixed width must not cost the control its height."""
        card = tk.Frame(self.root)
        card.pack(fill="x")
        rows = []
        for name, maker in (("label", lambda parent: tk.Label(parent, text="0.500",
                                                              anchor="e")),
                            ("entry", lambda parent: ttk.Entry(parent, width=20)),
                            ("switch", lambda parent: widgets.ToggleSwitch(
                                parent, tk.BooleanVar(), self.palette))):
            row = widgets.Row(card, self.palette, name, "description", maker)
            row.pack(fill="x")
            rows.append(row)
        self.root.update()
        for row in rows:
            with self.subTest(control=row.control.winfo_class()):
                self.assertEqual(row.control.winfo_height(),
                                 row.control.winfo_reqheight())
                self.assertGreater(row.control.winfo_height(),
                                   row.control.winfo_reqheight() * 0.9)

    def test_fields_fill_the_column(self) -> None:
        card = tk.Frame(self.root)
        card.pack(fill="x")
        row = widgets.Row(card, self.palette, "Field", "", 
                          lambda parent: ttk.Entry(parent, width=8))
        row.pack(fill="x")
        self.root.update()
        self.assertEqual(row.control.winfo_width(), row.holder.winfo_width())


class TestWindowsSettings(unittest.TestCase):
    """The settings Windows owns travel in the same file as the rest."""

    def test_defaults_include_them(self) -> None:
        written = config.defaults()
        for name in startup.APP_FIELDS:
            self.assertIn(name, written)
            self.assertIsInstance(written[name], bool)

    def test_they_survive_a_round_trip(self) -> None:
        directory = tempfile.mkdtemp(prefix="winborder_app_")
        path = Path(directory) / "winborder.json"
        settings = config.defaults()
        settings["start_with_windows"] = True
        config.write(path, settings)
        again = config.read(path)
        self.assertTrue(again["start_with_windows"])
        self.assertTrue(config.app_settings(again)["start_with_windows"])

    def test_bad_values_are_rejected(self) -> None:
        directory = tempfile.mkdtemp(prefix="winborder_app_")
        path = Path(directory) / "winborder.json"
        path.write_text(json.dumps({"start_hidden": "yes"}), encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            config.read(path)

    def test_missing_values_fall_back_to_off(self) -> None:
        self.assertEqual(config.app_settings({}),
                         {"start_with_windows": False, "start_hidden": False})

    def test_launch_command_points_at_this_interpreter(self) -> None:
        command = startup.launch_command("winborder.json")
        self.assertIn("winborder", command)
        self.assertIn("--config", command)

    def test_startup_entry_round_trip(self) -> None:
        """Whatever the registry said before, it says again afterwards."""
        was = startup.is_enabled()
        self.addCleanup(startup.apply, was, "winborder.json")
        if not startup.apply(True, "winborder.json"):
            self.skipTest("cannot write the startup entry")
        self.assertTrue(startup.is_enabled())
        self.assertTrue(startup.apply(False, "winborder.json"))
        self.assertFalse(startup.is_enabled())


class TestThemeColours(unittest.TestCase):
    """Only light or dark follows Windows; the accent is the application's."""

    def test_both_palettes_are_blue(self) -> None:
        for palette in (theme.DARK, theme.LIGHT):
            red, green, blue = _rgb(palette.accent)
            with self.subTest(palette=palette.name):
                self.assertGreater(blue, red, "the accent is not a blue")

    def test_the_system_accent_is_not_read(self) -> None:
        import inspect
        source = inspect.getsource(theme)
        self.assertNotIn("AccentColor", source)


class TestApplicationIcon(unittest.TestCase):
    """One mark, used by the window, the tray and the executable."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_it_renders_square_at_every_size(self) -> None:
        for size in (16, 24, 32, 48, 64, 256):
            with self.subTest(size=size):
                image = icon.render(self.root, size, "#4cc2ff")
                self.assertEqual((image.width(), image.height()), (size, size))

    def test_it_has_no_background_block(self) -> None:
        """Clear between the arms and between the panes, ink where they are."""
        size = 64
        image = icon.render(self.root, size, "#4cc2ff")
        for x, y in ((size // 2, 1), (size // 2, size - 2),
                     (size // 2, size // 2)):
            with self.subTest(clear=(x, y)):
                self.assertTrue(image.transparency_get(x, y),
                                "the mark carries a background block")
        # A filled pane, and the arm of a corner, both have to be solid.
        for x, y in ((14, 14), (8, 3)):
            with self.subTest(ink=(x, y)):
                self.assertFalse(image.transparency_get(x, y))

    def test_every_corner_has_its_right_angle(self) -> None:
        """On the arm itself, in all four corners."""
        size = 64
        image = icon.render(self.root, size, "#4cc2ff")
        inset, mid = 3, size // 2
        for x, y in ((8, inset), (size - 9, inset),
                     (8, size - 4), (size - 9, size - 4)):
            with self.subTest(arm=(x, y)):
                self.assertFalse(image.transparency_get(x, y),
                                 "a corner arm is missing ink")
        # ... and the middle of each edge stays clear, so they read as corners.
        for x, y in ((mid, 1), (mid, size - 2)):
            with self.subTest(edge=(x, y)):
                self.assertTrue(image.transparency_get(x, y))

    def test_open_panes_are_hollow(self) -> None:
        """The open panes must be a hole, not a painted background."""
        size = 64
        image = icon.render(self.root, size, "#4cc2ff")
        # Centre of the filled top-left pane, then of the open top-right one.
        self.assertFalse(image.transparency_get(14, 14))
        self.assertTrue(image.transparency_get(43, 14))

    def test_the_mark_uses_the_brand_blue(self) -> None:
        """The window, the tray and the executable all draw the same colour."""
        image = icon.render(self.root, 48, theme.BRAND)
        colours = {image.get(x, y) for x in range(0, 48, 3) for y in range(0, 48, 3)}
        self.assertIn(_rgb(theme.BRAND), colours)
        self.assertEqual(theme.DARK.accent, theme.BRAND)

    def test_small_sizes_drop_the_panes(self) -> None:
        small = icon.app_icon_shapes(16, "#ffffff", "#000000")
        large = icon.app_icon_shapes(64, "#ffffff", "#000000")
        self.assertLess(len(small), len(large))

    def test_rgba_is_the_right_length(self) -> None:
        self.assertEqual(len(icon.rgba(32, "#4cc2ff", "#000000")), 32 * 32 * 4)
