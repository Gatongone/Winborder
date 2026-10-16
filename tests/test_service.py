"""Tests for the service glue around the routing state machine.

The service owns the thread the effects go out on, so a pause asked for by the
window has to travel through it rather than being set on the router directly.
"""

from __future__ import annotations

import unittest

from winborder import model
from winborder.service import Service


class StubSink:
    """Stands in for the effect sink, which is only built once a link is open."""

    def __init__(self) -> None:
        self.applied: list[model.Effect] = []

    def apply(self, effects: list[model.Effect]) -> list[str]:
        self.applied.extend(effects)
        return []


class TestPause(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Service("COM-test")
        self.sink = StubSink()
        self.service._sink = self.sink

    def test_a_request_reaches_the_router(self) -> None:
        self.service.set_paused(True)
        self.assertFalse(self.service.router.paused, "not applied by the caller")
        self.service._apply_pause(1.0)
        self.assertTrue(self.service.router.paused)
        self.assertTrue(self.service.status()["paused"])

    def test_the_target_is_let_go_of_when_it_is_held(self) -> None:
        self.service.router.enter_target((1919, 540), 0.0)
        self.assertIs(self.service.router.mode, model.Mode.TARGET)
        self.service.set_paused(True)
        self.service._apply_pause(1.0)
        self.assertIs(self.service.router.mode, model.Mode.PC)
        kinds = [type(effect) for effect in self.sink.applied]
        self.assertIn(model.ReleaseCursor, kinds)
        self.assertIn(model.CaptureInput, kinds)

    def test_resuming_gives_the_router_back(self) -> None:
        self.service.set_paused(True)
        self.service._apply_pause(1.0)
        self.service.set_paused(False)
        self.service._apply_pause(2.0)
        self.assertFalse(self.service.router.paused)

    def test_it_is_only_applied_once(self) -> None:
        self.service.set_paused(True)
        self.service._apply_pause(1.0)
        applied = len(self.sink.applied)
        self.service._apply_pause(1.1)
        self.assertEqual(len(self.sink.applied), applied)

    def test_the_status_line_reports_it(self) -> None:
        self.assertFalse(self.service.status()["paused"])
        self.service.set_paused(True)
        self.service._apply_pause(1.0)
        self.assertTrue(self.service.status()["paused"])


if __name__ == "__main__":
    unittest.main()
