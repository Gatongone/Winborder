"""Tests for the one-instance rule.

Two copies would fight over the HID service, and the loser advertises an address
nothing is bonded to. The rule has to be a real lock across processes, so one of
these tests starts a second interpreter rather than calling itself twice.

The name is per test run: the host itself may well be running while the tests are,
and it holds the real name for as long as it lives.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from winborder import single

ROOT = Path(__file__).resolve().parents[1]


class TestLock(unittest.TestCase):
    def setUp(self) -> None:
        self.name = f"WinborderTestLock-{os.getpid()}"
        single.release()
        self.addCleanup(single.release)

    def test_the_first_copy_takes_the_lock(self) -> None:
        self.assertTrue(single.acquire(self.name))

    def test_asking_again_in_the_same_process_is_not_a_refusal(self) -> None:
        self.assertTrue(single.acquire(self.name))
        self.assertTrue(single.acquire(self.name))

    def test_the_lock_can_be_given_back(self) -> None:
        self.assertTrue(single.acquire(self.name))
        single.release()
        self.assertTrue(single.acquire(self.name))

    def test_a_second_process_is_refused(self) -> None:
        """The lock has to hold across processes, which is where it is needed."""
        self.assertTrue(single.acquire(self.name))
        code = (
            "from winborder import single\n"
            f"print('first' if single.acquire({self.name!r}) else 'second')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True,
            text=True, timeout=120,
        )
        self.assertEqual(result.stdout.strip(), "second",
                         result.stderr or "the second process took the lock")


class TestFocus(unittest.TestCase):
    def test_a_window_that_does_not_exist_is_reported(self) -> None:
        self.assertFalse(single.focus_existing("no window carries this title 4711"))


if __name__ == "__main__":
    unittest.main()
