"""Tests for the pieces the settings window is built from.

The window itself needs a display, so only the parts that decide what a setting
means are covered here.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import platform
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock
from pathlib import Path

from tkinter import font as tkfc
from tkinter import ttk

from winborder import config, hid, i18n, icon, keymap, logbuffer, model, startup, \
    theme, trace, ui, widgets
from winborder.widgets import filter_names


class TestSettingsForm(unittest.TestCase):
    def test_every_setting_has_a_field(self) -> None:
        names = {field.name for field in ui.FIELDS}
        for field in dataclasses.fields(model.Config):
            with self.subTest(field=field.name):
                if field.name == "remap":
                    continue          # the form edits it, the file stores it
                self.assertIn(field.name, names)

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

    def test_remap_is_edited_as_pairs(self) -> None:
        form = ui.SettingsForm({"remap": {"CapsLock": "Escape"}})
        self.assertEqual(form.values["remap"], [("CapsLock", "Escape")])
        form.values["remap"] = [("CapsLock", "LeftCtrl"), ("Menu", "Escape")]
        self.assertEqual(form.settings({})["remap"],
                         {"CapsLock": "LeftCtrl", "Menu": "Escape"})

    def test_a_blank_number_keeps_the_default(self) -> None:
        form = ui.SettingsForm(config.defaults())
        form.values["pullback_distance"] = ""
        self.assertNotIn("pullback_distance", form.settings({}))

    def test_bad_input_is_rejected(self) -> None:
        for name, value in (("pullback_distance", "soon"), ("panic_keys", "Nope"),
                            ("remap", [("CapsLock", "")]),
                            ("remap", [("", "Escape")]),
                            ("remap", [("Nope", "Escape")])):
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
        form.values["remap"] = [("CapsLock", "Escape")]
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


class TestLogLevels(unittest.TestCase):
    """The log page is for whoever is using the program, not for me."""

    def setUp(self) -> None:
        self.buffer = logbuffer.LogBuffer(capacity=10)
        self.log = logging.getLogger("winborder.levels")
        self.log.setLevel(logging.DEBUG)
        self.log.addHandler(self.buffer)
        self.addCleanup(self.log.removeHandler, self.buffer)

    def test_debug_lines_are_kept_but_not_offered(self) -> None:
        self.log.debug("a proactor detail")
        self.log.info("the target has the keyboard and mouse")
        lines, total = self.buffer.snapshot(0, level=logging.INFO)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("the target has the keyboard", lines[0])
        # The buffer still has both, and the reader is past both.
        self.assertEqual(total, 2)
        self.assertIn("a proactor detail", self.buffer.text())

    def test_the_cursor_advances_past_what_was_hidden(self) -> None:
        """Hiding a line must not make it appear later."""
        self.log.debug("first")
        _, seen = self.buffer.snapshot(0, level=logging.INFO)
        self.log.info("second")
        lines, _ = self.buffer.snapshot(seen, level=logging.INFO)
        self.assertEqual([line.split()[-1] for line in lines], ["second"])

    def test_everything_is_offered_at_debug(self) -> None:
        self.log.debug("a proactor detail")
        lines, _ = self.buffer.snapshot(0)
        self.assertEqual(len(lines), 1)


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
                  and e.kind == hid.KEYBOARD]
        # [modifiers][k0..k6]: the first key slot is at index 1.
        self.assertEqual(states[-1][1], 0x29)


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
                     "reload", "quit", "plus", "cross"):
            with self.subTest(icon=name):
                widgets.draw_icon(canvas, name, 16, "#ffffff", "#000000")
                self.assertTrue(canvas.find_all(), f"{name} drew nothing")


class TestRemapList(unittest.TestCase):
    """Remaps are edited as a list of lines, not as a block of text."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.palette = theme.system_theme()
        widgets.set_scale(theme.ui_scale(self.root))

    def editor(self, changes: list[int] | None = None):
        reported = changes if changes is not None else []
        return widgets.RemapList(self.root, self.palette,
                                 on_change=lambda: reported.append(1))

    def test_it_starts_empty_and_says_so(self) -> None:
        editor = self.editor()
        self.assertEqual(editor.pairs(), [])
        self.assertTrue(editor.empty.winfo_manager(), "the empty note is missing")

    def test_a_line_is_one_remap(self) -> None:
        editor = self.editor()
        editor.add_row("CapsLock", "Escape")
        editor.add_row("A", "B")
        self.assertEqual(editor.pairs(), [("CapsLock", "Escape"), ("A", "B")])
        self.assertFalse(editor.empty.winfo_manager(), "the empty note is still shown")

    def test_a_line_with_nothing_in_it_is_not_a_remap(self) -> None:
        editor = self.editor()
        editor.add_row()
        self.assertEqual(editor.pairs(), [])

    def test_a_half_filled_line_is_kept_but_not_saved(self) -> None:
        """A remap in progress is not an error, and it must stay on screen."""
        editor = self.editor()
        editor.add_row("CapsLock", "")
        self.assertEqual(editor.pairs(), [])
        self.assertEqual(len(editor._rows), 1)

    def test_a_line_can_be_removed(self) -> None:
        editor = self.editor()
        editor.add_row("CapsLock", "Escape")
        editor.add_row("A", "B")
        editor._rows[0]["remove"].invoke()      # the ✕ of the first line
        self.assertEqual(editor.pairs(), [("A", "B")])

    def test_the_whole_list_can_be_replaced(self) -> None:
        editor = self.editor()
        editor.add_row("A", "B")
        editor.set_pairs([("CapsLock", "Escape")])
        self.assertEqual(editor.pairs(), [("CapsLock", "Escape")])
        self.assertEqual(len(editor._rows), 1)

    def test_a_blank_line_is_not_reported_as_an_edit(self) -> None:
        """Reporting one would have the window commit, and rebuild, mid-edit."""
        changes: list[int] = []
        editor = self.editor(changes)
        editor.add_row()
        self.assertEqual(changes, [])

    def test_naming_a_key_reports_a_change(self) -> None:
        changes: list[int] = []
        editor = self.editor(changes)
        editor.add_row()
        editor._rows[0]["source"].assign("CapsLock")
        self.assertTrue(changes, "a key was set without reporting it")


class TestKeyField(unittest.TestCase):
    """A key is named by pressing it, not by finding it in a list of 116."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.palette = theme.system_theme()
        widgets.set_scale(theme.ui_scale(self.root))

    class Event:
        def __init__(self, keycode: int) -> None:
            self.keycode = keycode

    def field(self, value: str = ""):
        return widgets.KeyField(self.root, self.palette, value)

    def test_it_asks_for_a_key_when_it_is_empty(self) -> None:
        self.assertEqual(self.field().cget("text"), i18n.t("Press a key"))

    def test_pressing_a_key_names_it(self) -> None:
        field = self.field()
        field.capture()
        field._pressed(self.Event(0x14))       # CapsLock
        self.assertEqual(field.value, "CapsLock")
        self.assertEqual(field.cget("text"), "CapsLock")

    def test_a_key_that_is_not_in_the_map_is_refused(self) -> None:
        field = self.field("Escape")
        field.capture()
        field._pressed(self.Event(0xFF))       # not a key the host knows
        self.assertEqual(field.value, "Escape")

    def test_a_modifier_is_named_with_the_side_that_has_one(self) -> None:
        """VK_CONTROL has no side, and the settings file needs one."""
        for code, name in ((0x11, "LeftCtrl"), (0x12, "LeftAlt"), (0x10, "LeftShift")):
            with self.subTest(key=name):
                field = self.field()
                field.capture()
                field._pressed(self.Event(code))
                self.assertEqual(field.value, name)

    def test_a_field_that_was_only_clicked_stays_empty(self) -> None:
        field = self.field()
        field.capture()
        field._give_up()                       # focus left without a key
        self.assertEqual(field.value, "")

    def test_pressing_a_key_reports_a_change(self) -> None:
        changes: list[int] = []
        field = widgets.KeyField(self.root, self.palette, "",
                                 on_change=lambda: changes.append(1))
        field.capture()
        field._pressed(self.Event(0x41))       # A
        self.assertTrue(changes)

    def test_the_list_offers_every_key(self) -> None:
        """The keys a keyboard lacks have another way in."""
        field = self.field()
        picker = field.pick()
        self.addCleanup(picker.close)
        self.assertEqual(picker.listbox.size(), len(keymap.KEY_NAMES))
        picker.query.set("rightw")
        self.assertEqual(list(picker.listbox.get(0, "end")),
                         [name for name in filter_names(keymap.KEY_NAMES, "rightw")])
        self.assertIn("RightWin", picker.listbox.get(0, "end"))

    def test_choosing_from_the_list_sets_the_key(self) -> None:
        field = self.field()
        picker = field.pick()
        self.addCleanup(picker.close)
        picker.query.set("rightwin")
        picker.listbox.selection_clear(0, "end")
        picker.listbox.selection_set(0)
        picker._choose()
        self.assertEqual(field.value, "RightWin")


class TestKeyListFilter(unittest.TestCase):
    """The picker is searchable: 116 names is too many to scan."""

    NAMES = ("RightWin", "LeftWin", "RightShift", "Escape")

    def test_an_empty_query_keeps_everything(self) -> None:
        self.assertEqual(widgets.filter_names(self.NAMES, ""), list(self.NAMES))

    def test_a_query_narrows_the_list(self) -> None:
        self.assertEqual(widgets.filter_names(self.NAMES, "right"),
                         ["RightWin", "RightShift"])

    def test_the_search_ignores_case_and_spaces(self) -> None:
        self.assertEqual(widgets.filter_names(self.NAMES, "  WIn "),
                         ["RightWin", "LeftWin"])

    def test_nothing_matching_is_an_empty_list(self) -> None:
        self.assertEqual(widgets.filter_names(self.NAMES, "z"), [])


class TestThemedLabel(unittest.TestCase):
    """A label that repaints itself, so the window does not have to remember."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        widgets.set_scale(theme.ui_scale(self.root))

    def test_it_starts_in_its_palette_colours(self) -> None:
        label = widgets.ThemedLabel(self.root, theme.DARK, "x", tone="muted")
        self.assertEqual(label.cget("foreground"), theme.DARK.muted)
        self.assertEqual(label.cget("background"), theme.DARK.bg)

    def test_a_repaint_follows_the_new_palette(self) -> None:
        label = widgets.ThemedLabel(self.root, theme.DARK, "x")
        label.repaint(theme.LIGHT)
        self.assertEqual(label.cget("foreground"), theme.LIGHT.fg)
        self.assertEqual(label.cget("background"), theme.LIGHT.bg)

    def test_it_can_sit_on_a_card(self) -> None:
        label = widgets.ThemedLabel(self.root, theme.DARK, "x", on="surface")
        self.assertEqual(label.cget("background"), theme.DARK.surface)

    def test_a_tone_can_change_and_still_follow_the_palette(self) -> None:
        label = widgets.ThemedLabel(self.root, theme.DARK, "x", tone="muted")
        label.set_tone("accent")
        label.repaint(theme.LIGHT)
        self.assertEqual(label.cget("foreground"), theme.LIGHT.accent)

    def test_a_literal_colour_survives_a_repaint(self) -> None:
        """An error line keeps its colour; the palette does not own it."""
        label = widgets.ThemedLabel(self.root, theme.DARK, "x")
        label.set_colour("#e06c75")
        label.repaint(theme.LIGHT)
        self.assertEqual(label.cget("foreground"), "#e06c75")
        label.set_colour(None)
        self.assertEqual(label.cget("foreground"), theme.LIGHT.fg)


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
        window = self.make({"handoff": bridge, "pointer": pointer}, "handoff")
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
        window = self.make({"handoff": canvas}, "handoff")
        window._on_wheel(self.Event(120))           # wheel up scrolls up
        self.assertEqual(canvas.calls, [(-1, "units")])

    def test_page_without_scrolling_is_ignored(self) -> None:
        window = self.make({"bridge": object()}, "log")
        window._on_wheel(self.Event(-120))          # must not raise


class StubService:
    """Enough of the service for the window to be built and measured."""

    def __init__(self) -> None:
        self.paused: list[bool] = []
        self.advertising = "started"
        self.connected = True
        self.name = "Winborder"

    def status(self) -> dict[str, object]:
        return {"mode": "pc", "paused": bool(self.paused and self.paused[-1]),
                "side": "bottom", "cursor": (0.5, 1.0), "pointer": (0.5, 0.5),
                "travel": 0.0, "frames": 0, "written": 0, "bad": 0,
                "connected": self.connected,
                "advertising": self.advertising,
                "name": self.name}

    def apply_config(self, config) -> None:
        pass

    def set_paused(self, paused: bool) -> None:
        self.paused.append(bool(paused))

    def request_stop(self) -> None:
        pass

    def run(self) -> None:
        pass


class TestPathFitting(unittest.TestCase):
    """A long path must not be broken in the middle of a file name.

    Tk wraps a label at any character it likes, so the settings path came out as
    ``…\\winborder.js`` over ``on``, which reads as two unrelated strings.
    """

    PATH = r"C:\Program Files\Winborder\winborder.json"

    def test_a_path_that_fits_is_left_alone(self) -> None:
        self.assertEqual(ui.wrap_path(self.PATH, 80), self.PATH)

    def test_it_breaks_after_a_separator(self) -> None:
        limit = 40
        wrapped = ui.wrap_path(self.PATH, limit)
        first, second = wrapped.split("\n")
        self.assertTrue(first.endswith("\\"), first)
        self.assertEqual(first + second, self.PATH, "the path was not kept whole")
        self.assertEqual(second, "winborder.json", "the file name was cut")

    def test_every_line_fits_the_column(self) -> None:
        for limit in (12, 20, 28, 40, 51):
            with self.subTest(limit=limit):
                for line in ui.wrap_path(self.PATH, limit).split("\n"):
                    self.assertLessEqual(len(line), max(limit, 8))

    def test_a_single_long_name_is_shortened_in_the_middle(self) -> None:
        wrapped = ui.wrap_path("C:\\" + "a" * 60, 20)
        self.assertIn("…", wrapped)
        for line in wrapped.split("\n"):
            self.assertLessEqual(len(line), 20)

    def test_shortening_keeps_both_ends(self) -> None:
        shortened = ui.shorten_path(self.PATH, 20)
        self.assertTrue(shortened.startswith("C:"))
        self.assertTrue(shortened.endswith(".json"))
        self.assertEqual(len(shortened), 20)


class TestLinkSummary(unittest.TestCase):
    """The Devices page has to say which way round the link is."""

    def setUp(self) -> None:
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)

    def test_a_subscriber_is_a_connection(self) -> None:
        line = ui.link_summary({"connected": True, "advertising": "started"},
                               since=time.time())
        self.assertIn("connected since", line)

    def test_waiting_names_the_pc_and_who_has_to_pair(self) -> None:
        line = ui.link_summary({"connected": False, "advertising": "started",
                                "name": "Winborder"})
        self.assertIn("waiting for the target device to pair", line)
        self.assertIn("Winborder", line)

    def test_a_name_that_could_not_be_read_is_not_invented(self) -> None:
        """The computer name is not the Bluetooth name, so it is not a fallback."""
        line = ui.link_summary({"connected": False, "advertising": "started",
                                "name": ""})
        self.assertIn("waiting for the target device to pair", line)
        self.assertNotIn(platform.node(), line)

    def test_an_advertisement_windows_cut_short_is_reported(self) -> None:
        line = ui.link_summary({"connected": False, "advertising": "aborted"},
                               aborted_for=ui.ABORT_GRACE_S + 1.0)
        self.assertIn("cut short", line)

    def test_an_abort_while_it_restarts_is_not_a_fault(self) -> None:
        """Every start reports aborted for a second or two, and that is normal."""
        line = ui.link_summary({"connected": False, "advertising": "aborted"},
                               aborted_for=0.2)
        self.assertNotIn("cut short", line)
        self.assertIn("not advertising", line)

    def test_nothing_on_the_air_is_reported_as_such(self) -> None:
        self.assertIn("not advertising", ui.link_summary(None))
        self.assertIn("not advertising",
                      ui.link_summary({"connected": False,
                                       "advertising": "not started"}))

    def test_the_moment_it_went_down_is_remembered(self) -> None:
        line = ui.link_summary({"connected": False, "advertising": "started"},
                               last_up=time.time())
        self.assertIn("last connected at", line)

    def test_a_live_subscription_outranks_a_stale_status(self) -> None:
        """The status goes ABORTED and back while a host is connected."""
        line = ui.link_summary({"connected": True, "advertising": "aborted"},
                               since=time.time())
        self.assertIn("connected since", line)
        self.assertNotIn("cut short", line)


class TestGainBounds(unittest.TestCase):
    def test_a_gain_of_zero_is_refused(self) -> None:
        form = ui.SettingsForm()
        form.values["sensitivity"] = "0"
        with self.assertRaises(config.ConfigError):
            form.settings({})
        form.values["sensitivity"] = "0.5"
        self.assertEqual(form.settings({})["sensitivity"], 0.5)

    def test_negative_acceleration_is_refused(self) -> None:
        form = ui.SettingsForm()
        form.values["accel"] = "-0.1"
        with self.assertRaises(config.ConfigError):
            form.settings({})


class TestNumberFields(unittest.TestCase):
    """The charset a number passes through, not the value it ends up as."""

    def test_an_integer_field_takes_digits_and_a_minus_sign(self) -> None:
        allowed = ui.number_allowed(False)
        for text_ in ("", "-", "0", "12", "-4"):
            with self.subTest(text=text_):
                self.assertTrue(allowed(text_))
        for text_ in ("a", "1a", "1.2", "-", "--1", "1 2", "1e5"):
            with self.subTest(text=text_):
                if text_ == "-":
                    continue
                self.assertFalse(allowed(text_))

    def test_a_float_field_takes_one_point(self) -> None:
        allowed = ui.number_allowed(True)
        for text_ in ("", "-", "1", "1.5", ".5", "-0.25"):
            with self.subTest(text=text_):
                self.assertTrue(allowed(text_))
        for text_ in ("1.2.3", "1,5", "abc"):
            with self.subTest(text=text_):
                self.assertFalse(allowed(text_))


class TestWindowLayout(unittest.TestCase):
    """The window has to fill its width, at whatever scale the display asks."""

    def setUp(self) -> None:
        # A window of its own, with settings of its own: a test must not touch
        # the settings file or the startup entry of whoever is running it.
        directory = tempfile.mkdtemp(prefix="winborder_layout_")
        try:
            self.window = ui.SettingsWindow(
                StubService(), {"side": "left"},
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

    def test_a_number_field_refuses_letters_as_they_are_typed(self) -> None:
        """A rejected value that only fails on save looks accepted until then."""
        control = self.window._controls["notch_up"]
        entry = control._widget
        entry.delete(0, "end")
        entry.insert(0, "3")
        self.assertEqual(control.read(), "3")
        entry.insert("end", "a")
        self.assertEqual(control.read(), "3", "the letter was not taken")

    def test_a_key_setting_is_entered_by_pressing_the_key(self) -> None:
        """116 names make a typed key field a place to get a name wrong."""
        control = self.window._controls["panic_keys"]
        self.assertIsInstance(control, ui._KeyControl)
        self.assertIsInstance(control._widget, widgets.KeyField)
        control.write("F1")
        self.assertEqual(self.window._read()["panic_keys"], ["F1"])

    def test_pressing_a_key_writes_its_name(self) -> None:
        field = self.window._controls["panic_keys"]._widget
        field.capture()
        self.assertEqual(field._pressed(mock.Mock(keycode=keymap.KEY_NAMES["F2"][0])),
                         "break")
        self.assertEqual(field.value, "F2")
        self.assertEqual(self.window._read()["panic_keys"], ["F2"])

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

    def test_the_devices_page_says_what_the_link_is_doing(self) -> None:
        self.window._closing = True
        self.window._pump_status()
        self.assertIn("connected since", self.window.link_state.cget("text"))

        self.window.service.connected = False
        self.window.service.advertising = "started"
        self.window._pump_status()
        self.assertIn("waiting for the target device to pair",
                      self.window.link_state.cget("text"))

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
        self.window.show_page("edge")
        self.window.root.update_idletasks()
        canvas = self.window._page_canvas["edge"]
        body = canvas.winfo_children()[0]
        widths = [child.winfo_width() for child in body.winfo_children()
                  if isinstance(child, widgets.Card)]
        self.assertTrue(widths)
        # Cards keep the page margins and nothing more.
        self.assertGreater(min(widths), canvas.winfo_width() * 0.8)

    def test_the_settings_path_is_not_cut_inside_a_name(self) -> None:
        """The About card shows the path on one line, or after a separator."""
        self.window.show_page("generic")
        self.window.root.update_idletasks()
        value = self.window.about_rows["settings"]
        text = value.cget("text")
        font = tkfc.Font(font=value.cget("font"))
        for line in str(text).split("\n"):
            with self.subTest(line=line):
                self.assertLessEqual(font.measure(line),
                                     int(value.cget("wraplength")),
                                     "a line would wrap, cutting a name in half")
        self.assertTrue(str(text).rstrip().endswith(".json"))

    def test_a_remap_in_progress_survives_a_commit(self) -> None:
        """Filling one side of a new line must not take the line away."""
        self.window.show_page("keyboard")
        self.window.remap_add.invoke()
        self.window.remap_list._rows[0]["source"].assign("CapsLock")
        self.window._commit()                  # what the commit timer does
        self.assertEqual(len(self.window.remap_list._rows), 1,
                         "the line being edited was rebuilt away")
        self.assertEqual(self.window.settings.get("remap"), {})

    def test_the_plus_adds_a_line(self) -> None:
        self.window.show_page("keyboard")
        self.assertEqual(self.window.remap_list.pairs(), [])
        self.assertTrue(self.window.remap_add.bind("<Button-1>"),
                        "the plus has no click binding")
        self.window.remap_add.invoke()
        self.assertEqual(len(self.window.remap_list._rows), 1)

    def test_the_remap_list_uses_the_card_width(self) -> None:
        """It is a list, so it reads across the card instead of a control column."""
        self.window.show_page("keyboard")
        self.window.remap_list.add_row("CapsLock", "Escape")
        self.window.remap_list.add_row("Menu", "LeftCtrl")
        self.window.root.update_idletasks()
        editor = self.window.remap_list
        card = editor.master.master
        self.assertGreater(editor.winfo_width(), card.winfo_width() * 0.6,
                           "the list is squeezed into a control's column")
        self.assertGreaterEqual(editor.winfo_height(),
                                editor.winfo_reqheight(),
                                "the list would be clipped")

    def test_the_remap_round_trips_through_the_window(self) -> None:
        directory = tempfile.mkdtemp(prefix="winborder_remap_")
        path = Path(directory) / "winborder.json"
        window = ui.SettingsWindow(StubService(), {"remap": {"CapsLock": "Escape"}},
                                   str(path))
        self.addCleanup(window.root.destroy)
        window._windows_settings = config.app_settings(window.settings)
        self.assertEqual(window.remap_list.pairs(), [("CapsLock", "Escape")])

        window.remap_list.add_row("Menu", "LeftCtrl")
        window._commit()
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written["remap"],
                         {"CapsLock": "Escape", "Menu": "LeftCtrl"})

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
                StubService(), {"side": "left"},
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

    def test_a_debug_line_stays_out_of_the_page(self) -> None:
        self.log.debug("an asyncio proactor detail")
        self.window._pump_log()
        self.assertNotIn("proactor", self.shown())

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
        # The entry is only written for the built executable, so the test says it
        # is one: a command line pointing at this interpreter is not what ships.
        with mock.patch.object(startup, "is_frozen", return_value=True):
            if not startup.apply(True, "winborder.json"):
                self.skipTest("cannot write the startup entry")
            self.assertTrue(startup.is_enabled())
            self.assertTrue(startup.apply(False, "winborder.json"))
        self.assertFalse(startup.is_enabled())

    def test_starting_from_source_is_not_registered(self) -> None:
        """A Run entry pointing at a Python interpreter outlives its usefulness."""
        was = startup.is_enabled()
        self.addCleanup(startup.apply, was, "winborder.json")
        with mock.patch.object(startup, "is_frozen", return_value=False):
            self.assertFalse(startup.apply(True, "winborder.json"))
        self.assertEqual(startup.is_enabled(), was)


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


class TestGlyphSet(unittest.TestCase):
    """A column of icons is read as a column before it is read as icons.

    The set is drawn to one specification: eleven units of ink on the centre of
    the box. Two marks may sit off centre across, because the eye weighs their
    ink rather than their outline -- an arrow points one way, and the joins of the
    Bluetooth rune are both on the right.
    """

    NAMES = ("status", "gear", "edge", "bluetooth", "pointer", "keyboard",
             "log", "terminal", "file", "reload", "quit", "pause", "play", "link")
    DIRECTIONAL = ("pointer", "edge", "link")
    SIZE = 32

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:            # no display available
            raise unittest.SkipTest(f"no display: {exc}") from None
        cls.root.withdraw()
        cls.measured = {name: cls.ink(name) for name in cls.NAMES}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    @classmethod
    def ink(cls, name: str) -> tuple[float, float, float]:
        """Height, and the centre of the ink by weight, in the glyph's own units."""
        image = widgets.render_icon(cls.root, name, cls.SIZE, "#ffffff",
                                    "#000000")
        unit = cls.SIZE / 16.0
        total = wx = wy = 0.0
        top, bottom = cls.SIZE, -1
        for y in range(cls.SIZE):
            for x in range(cls.SIZE):
                value = image.get(x, y)
                weight = (int(value[0]) if isinstance(value, tuple)
                          else int(value.lstrip("#")[:2], 16))
                if weight:
                    total += weight
                    wx += weight * (x + 0.5)
                    wy += weight * (y + 0.5)
                if weight > 12:
                    top, bottom = min(top, y), max(bottom, y)
        return (bottom + 1 - top) / unit, wx / total / unit, wy / total / unit

    def test_every_glyph_is_the_same_height(self) -> None:
        for name in self.NAMES:
            height = self.measured[name][0]
            with self.subTest(name=name):
                self.assertAlmostEqual(height, 11.0, delta=0.7,
                                       msg=f"{name} is {height:.1f} units tall")

    def test_every_glyph_sits_on_the_centre_of_its_box(self) -> None:
        for name in self.NAMES:
            _height, x, y = self.measured[name]
            with self.subTest(name=name):
                self.assertAlmostEqual(y, 8.0, delta=0.5,
                                       msg=f"{name} sits at {y:.2f} down")
                if name not in self.DIRECTIONAL:
                    self.assertAlmostEqual(x, 8.0, delta=0.5,
                                           msg=f"{name} sits at {x:.2f} across")
