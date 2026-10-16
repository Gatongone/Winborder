"""Tests for the keyboard handoff bookkeeping.

Only the state tracking is exercised here: the hook callbacks are not installed,
and the synthetic releases are recorded instead of being injected.
"""

from __future__ import annotations

import unittest
from unittest import mock

from winborder import input as input_mod
from winborder import win32

VK_CTRL_LEFT = 0xA2
VK_ENTER = 0x0D
VK_A = 0x41


class TestKeyboardHandoff(unittest.TestCase):
    """Neither half of a keystroke may be delivered on its own."""

    def setUp(self) -> None:
        self.engine = input_mod.InputEngine()
        patcher = mock.patch.object(win32, "send_key_up")
        self.send_key_up = patcher.start()
        self.addCleanup(patcher.stop)

    def test_passthrough_when_not_captured(self) -> None:
        self.assertFalse(self.engine._track_key(VK_A, True))
        self.assertFalse(self.engine._track_key(VK_A, False))
        self.send_key_up.assert_not_called()

    def test_captured_key_is_kept_from_the_pc(self) -> None:
        self.engine.suppress_keyboard = True
        self.assertTrue(self.engine._track_key(VK_A, True))
        self.assertTrue(self.engine._track_key(VK_A, False))
        self.send_key_up.assert_not_called()

    def test_release_of_a_held_key_is_handed_back(self) -> None:
        """A key the PC saw pressed must not stay down after the handoff."""
        self.engine._track_key(VK_CTRL_LEFT, True)
        self.engine.suppress_keyboard = True
        self.assertTrue(self.engine._track_key(VK_CTRL_LEFT, False))
        self.engine.suppress_keyboard = False
        self.send_key_up.assert_called_once_with(VK_CTRL_LEFT)

    def test_stale_release_is_not_delivered(self) -> None:
        """A key the PC never saw pressed must not have its release delivered."""
        self.engine.suppress_keyboard = True
        self.assertTrue(self.engine._track_key(VK_ENTER, True))
        self.engine.suppress_keyboard = False
        self.assertTrue(self.engine._track_key(VK_ENTER, False))
        self.send_key_up.assert_not_called()

    def test_keys_held_at_shutdown_are_handed_back(self) -> None:
        self.engine._track_key(VK_CTRL_LEFT, True)
        self.engine.suppress_keyboard = True
        self.engine._track_key(VK_CTRL_LEFT, False)
        # release_all() drives the same setter when the host shuts down.
        self.engine.suppress_keyboard = False
        self.send_key_up.assert_called_once_with(VK_CTRL_LEFT)

    def test_nothing_is_injected_without_a_lost_release(self) -> None:
        self.engine.suppress_keyboard = True
        self.engine.suppress_keyboard = False
        self.send_key_up.assert_not_called()

    def test_second_handoff_does_not_repeat_the_release(self) -> None:
        self.engine._track_key(VK_CTRL_LEFT, True)
        self.engine.suppress_keyboard = True
        self.engine._track_key(VK_CTRL_LEFT, False)
        self.engine.suppress_keyboard = False
        self.engine.suppress_keyboard = True
        self.engine.suppress_keyboard = False
        self.send_key_up.assert_called_once_with(VK_CTRL_LEFT)


if __name__ == "__main__":
    unittest.main()
