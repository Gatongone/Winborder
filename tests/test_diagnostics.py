"""Tests for the two "keeps running, but says so" helpers.

Both exist because of the same failure: an exception that is caught on purpose and
reported at a level nobody reads. The first version of this cost the project a
whole round -- a TypeError per keystroke, invisible, presenting as a link that
connects and does nothing.
"""

from __future__ import annotations

import logging
import unittest
from unittest import mock

from winborder import diagnostics


class TestSwallowedFailure(unittest.TestCase):
    def setUp(self) -> None:
        diagnostics.forget()
        self.addCleanup(diagnostics.forget)

    def test_the_first_failure_is_a_warning(self) -> None:
        with self.assertLogs("winborder.diagnostics", level="WARNING") as captured:
            diagnostics.failed("answering a read", ValueError("nope"))
        self.assertIn("answering a read failed", captured.output[0])
        self.assertIn("ValueError", captured.output[0])

    def test_the_second_one_of_the_same_operation_is_debug(self) -> None:
        diagnostics.failed("answering a read", ValueError("nope"))
        logger = logging.getLogger("winborder.diagnostics")
        with self.assertLogs(logger, level="DEBUG") as captured:
            diagnostics.failed("answering a read", ValueError("nope"))
        self.assertTrue(all("WARNING" not in line for line in captured.output),
                        "the same fault was announced twice")

    def test_another_operation_still_gets_its_own_warning(self) -> None:
        diagnostics.failed("answering a read", ValueError("nope"))
        with self.assertLogs("winborder.diagnostics", level="WARNING") as captured:
            diagnostics.failed("answering a write", ValueError("nope"))
        self.assertIn("answering a write", captured.output[0])

    def test_the_context_manager_keeps_going(self) -> None:
        with diagnostics.swallow("closing the handle"):
            raise OSError("busy")
        # Reaching here is the point: the operation was abandoned, not the caller.

    def test_forget_makes_the_next_failure_news_again(self) -> None:
        diagnostics.failed("answering a read", ValueError("nope"))
        diagnostics.forget()
        with self.assertLogs("winborder.diagnostics", level="WARNING"):
            diagnostics.failed("answering a read", ValueError("nope"))


class TestCallersUseIt(unittest.TestCase):
    """The send path is the one that hid a bug, so it is the one pinned here."""

    def setUp(self) -> None:
        diagnostics.forget()
        self.addCleanup(diagnostics.forget)

    def test_a_failing_report_is_reported_once(self) -> None:
        from winborder import hid
        from winborder.ble import BleFrameSink

        class Broken:
            def __getattr__(self, _name):
                raise RuntimeError("the radio went away")

        sink = BleFrameSink(Broken())
        with self.assertLogs("winborder.diagnostics", level="WARNING") as captured:
            for _ in range(3):
                self.assertFalse(sink.send(hid.KEYBOARD, hid.encode_keyboard(0, ())))
        warnings = [line for line in captured.output if "WARNING" in line]
        self.assertEqual(len(warnings), 1, "one line per send would drown the log")
        self.assertEqual(sink.bad_frames, 3)


if __name__ == "__main__":
    unittest.main()
