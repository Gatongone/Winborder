"""Tests for the tray menu choices.

The window builds the menu on the tray thread and reads back an id, so which
callback an id runs is a wiring fact worth pinning: a wrong branch is a menu item
that does nothing at all.
"""

from __future__ import annotations

import unittest

from winborder import tray


def icon(calls: list[str], **kwargs) -> tray.TrayIcon:
    return tray.TrayIcon("winborder", lambda: calls.append("open"),
                         lambda: calls.append("quit"),
                         on_reload=lambda: calls.append("reload"),
                         on_open_config=lambda: calls.append("config"),
                         on_pause=lambda: calls.append("pause"),
                         paused=lambda: False, **kwargs)


class TestMenuChoice(unittest.TestCase):
    def test_every_item_runs_its_own_callback(self) -> None:
        expected = {
            tray.TrayIcon.MENU_OPEN: "open",
            tray.TrayIcon.MENU_RELOAD: "reload",
            tray.TrayIcon.MENU_CONFIG: "config",
            tray.TrayIcon.MENU_PAUSE: "pause",
            tray.TrayIcon.MENU_TYPE: "type",
            tray.TrayIcon.MENU_QUIT: "quit",
        }
        for choice, name in expected.items():
            calls: list[str] = []
            with self.subTest(item=name):
                icon(calls, on_type_clipboard=lambda: calls.append("type")
                     )._run_choice(choice)
                self.assertEqual(calls, [name])

    def test_the_clipboard_item_is_silent_without_a_callback(self) -> None:
        calls: list[str] = []
        icon(calls)._run_choice(tray.TrayIcon.MENU_TYPE)
        self.assertEqual(calls, [])

    def test_the_ids_are_distinct(self) -> None:
        ids = [tray.TrayIcon.MENU_OPEN, tray.TrayIcon.MENU_RELOAD,
               tray.TrayIcon.MENU_CONFIG, tray.TrayIcon.MENU_PAUSE,
               tray.TrayIcon.MENU_TYPE, tray.TrayIcon.MENU_QUIT]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
