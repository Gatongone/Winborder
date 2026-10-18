"""Tests that call each Win32 helper once.

A missing constant in this module does not fail an import and does not fail a test
that never reaches the line: ``focus_window`` raised ``NameError: name
'SW_RESTORE' is not defined`` in a released build, because the only test that
touched it asked for a window title that does not exist and returned before the
constant was used. These calls are deliberately shallow -- the point is that each
function runs, not that Windows does what it was asked.
"""

from __future__ import annotations

import ctypes
import unittest
from ctypes import wintypes

from winborder import win32


class TestEveryHelperRuns(unittest.TestCase):
    def test_cursor_position_round_trips(self) -> None:
        x, y = win32.get_cursor_pos()
        self.assertIsInstance(x, int)
        self.assertIsInstance(y, int)
        win32.set_cursor_pos(x, y)
        self.assertEqual(win32.get_cursor_pos(), (x, y))

    def test_the_screen_has_a_size(self) -> None:
        left, top, right, bottom = win32.primary_screen_rect()
        self.assertGreater(right - left, 0)
        self.assertGreater(bottom - top, 0)

    def test_dpi_awareness_reports_one_of_its_outcomes(self) -> None:
        self.assertIn(win32.enable_dpi_awareness(),
                      {"per-monitor v2", "per-monitor", "system", "unavailable"})

    def test_the_cursor_clip_can_be_released(self) -> None:
        win32.release_clip_global()          # must not raise

    def test_the_radio_name_is_a_string(self) -> None:
        self.assertIsInstance(win32.bluetooth_name(), str)

    def test_a_window_that_is_not_there_is_reported(self) -> None:
        self.assertFalse(win32.focus_window("no window carries this title 4711"))

    def test_the_clip_guard_counts(self) -> None:
        guard = win32.ClipGuard.instance()
        win32.ClipGuard.install_atexit()
        guard.acquire()
        guard.release()
        guard.force_release()
        self.assertEqual(guard.depth, 0)

    def test_a_key_can_be_injected(self) -> None:
        """Used to hand back a key whose release was swallowed."""
        self.assertIn(win32.send_key_up(0x70), (True, False))   # F1

    def test_the_clipboard_reads_as_text(self) -> None:
        self.assertIsInstance(win32.read_clipboard_text(), str)


class TestFocusFindsARealWindow(unittest.TestCase):
    """The path that raised in the released build: a window that IS there."""

    TITLE = "Winborder focus test 4711"

    def setUp(self) -> None:
        try:
            import tkinter as tk
            self.root = tk.Tk()
        except Exception as exc:              # no display available
            self.skipTest(f"no display: {exc}")
        self.root.title(self.TITLE)
        self.root.geometry("200x100+40+40")
        self.root.update()
        self.addCleanup(self.root.destroy)

    def test_it_is_brought_to_the_front(self) -> None:
        # Restoring and foregrounding needs SW_RESTORE, ShowWindow and
        # SetForegroundWindow to all exist under the names they are used with.
        self.assertTrue(win32.focus_window(self.TITLE))


if __name__ == "__main__":
    unittest.main()
