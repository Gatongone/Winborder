"""Tests for the service glue around the routing state machine.

The service owns the thread the effects go out on, so a pause asked for by the
window has to travel through it rather than being set on the router directly.
"""

from __future__ import annotations

import types
import unittest
from unittest import mock

from winborder import model
from winborder import service as service_mod
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
        # The service used to be handed a port; there is only one transport now.
        self.service = Service()
        self.sink = StubSink()
        self.service._sink = self.sink

    def test_a_request_reaches_the_router(self) -> None:
        self.service.set_paused(True)
        self.assertFalse(self.service.router.paused, "not applied by the caller")
        self.service._apply_pause(1.0)
        self.assertTrue(self.service.router.paused)
        self.assertTrue(self.service.status()["paused"])

    def test_the_target_is_let_go_of_when_it_is_held(self) -> None:
        # The service refuses the handoff until the device link is open, and this
        # test has no link. Let the router through so the pause is what is under
        # test here; the refusal itself is covered by its own test.
        self.service.router.handoff_allowed = lambda: (True, "")
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


class TestConnect(unittest.TestCase):
    """There is one transport: the PC publishes itself as the BLE peripheral."""

    def test_connecting_publishes_the_peripheral(self) -> None:
        with mock.patch.object(service_mod, "BleHidPeripheral") as peripheral_cls:
            peripheral = peripheral_cls.return_value
            peripheral.is_subscribed = False
            service = Service()
            service._connect()
            peripheral.start.assert_called_once()
            self.assertIs(service._link.peripheral, peripheral)
            self.assertIsNotNone(service._sink)

    def test_a_peripheral_that_will_not_start_is_survived(self) -> None:
        """No radio is not a crash: the console build has to keep running."""
        with mock.patch.object(service_mod, "BleHidPeripheral") as peripheral_cls:
            peripheral_cls.return_value.start.side_effect = RuntimeError("no radio")
            service = Service()
            service._connect()
            self.assertIsNone(service._link)

    def test_the_status_reports_what_is_on_the_air(self) -> None:
        """The Devices page reads this to say whether anything is advertising."""
        with mock.patch.object(service_mod, "BleHidPeripheral") as peripheral_cls:
            peripheral = peripheral_cls.return_value
            peripheral.is_subscribed = True
            peripheral.advertising_status = "started"
            service = Service()
            service._connect()
            self.assertEqual(service.status()["advertising"], "started")

    def listening_service(self, open_link: bool) -> Service:
        service = Service()
        service._link = types.SimpleNamespace(is_open=open_link)
        return service

    def test_one_line_per_connection_not_per_report(self) -> None:
        """The three subscriptions are one connection, and only one line."""
        service = self.listening_service(open_link=True)
        with self.assertLogs("winborder.service", level="DEBUG") as captured:
            for report in range(1, 4):
                service._on_ble_event("subscribed", f"report {report}, "
                                       f"{report} of 3 subscribed")
        info = [line for line in captured.output if line.startswith("INFO")]
        self.assertEqual(len(info), 1, f"the window would show {info}")
        self.assertIn("the target is connected and listening", info[0])

    def test_the_link_state_is_what_decides_it(self) -> None:
        service = self.listening_service(open_link=True)
        service._on_ble_event("subscribed", "report 1, 1 of 3 subscribed")
        service._link = types.SimpleNamespace(is_open=False)
        with self.assertLogs("winborder.service", level="INFO") as captured:
            service._on_ble_event("unsubscribed", "report 1, 0 of 3 subscribed")
        self.assertIn("waiting for it to come back", captured.output[0])

    def test_a_read_stays_out_of_the_window(self) -> None:
        """It is the sign that a host arrived and was refused; a report, not news."""
        service = self.listening_service(open_link=False)
        with self.assertLogs("winborder.service", level="DEBUG") as captured:
            service._on_ble_event("read", "a host read the report map")
        self.assertTrue(all(line.startswith("DEBUG") for line in captured.output),
                        captured.output)

    def test_the_report_map_read_is_shown(self) -> None:
        """The one read a user needs: it says the target reached the service.

        Every other read is detail, but this one is the difference between a
        target that never arrived and one that arrived, paired and stopped short
        of subscribing -- and the window said nothing about either before.
        """
        service = self.listening_service(open_link=False)
        with self.assertLogs("winborder.service", level="INFO") as captured:
            service._on_ble_event("report-map-read", "a host read the report map")
        self.assertIn("reading the HID descriptor", captured.output[0])

    def test_nothing_is_advertising_without_a_peripheral(self) -> None:
        service = Service()
        self.assertEqual(service.status()["advertising"], "not started")

    def test_the_handoff_is_refused_without_a_subscriber(self) -> None:
        """Capturing input with nowhere to send it would swallow the keyboard."""
        service = Service()
        self.assertEqual(service._handoff_allowed(),
                         (False, "device link is not open"))

    def test_the_refusal_is_said_once_not_once_per_attempt(self) -> None:
        """Pressing the edge while waiting for the target is normal.

        Saying it on every attempt fills the log with one line and hides
        everything else, so only a change of reason is reported again.
        """
        service = Service()
        with self.assertLogs("winborder.service", level="DEBUG") as captured:
            for _ in range(5):
                service._on_note("handoff_refused:device link is not open")
            service._on_note("handoff_refused:some other reason")
        said = [line for line in captured.output if "not handing over yet" in line]
        self.assertEqual(len(said), 2, "one per distinct reason")

    def test_a_later_refusal_is_reported_again(self) -> None:
        """After the target has connected, a lost link is news again."""
        service = Service()
        service._on_note("handoff_refused:device link is not open")
        service._on_ble_event("subscribed", "report 1")
        with self.assertLogs("winborder.service", level="DEBUG") as captured:
            service._on_note("handoff_refused:device link is not open")
        self.assertEqual(
            len([line for line in captured.output if "not handing over yet" in line]), 1)


if __name__ == "__main__":
    unittest.main()


class StubLink:
    """The link as the typing path sees it: something to count accepted reports."""

    def __init__(self) -> None:
        self.written_frames = 0


class TestTypingRequest(unittest.TestCase):
    """Clipboard text is planned on the caller's thread and typed by the step.

    Reading the clipboard can wait, so it does not happen on the thread that has
    to keep the reports going; the plan is what crosses over.
    """

    def setUp(self) -> None:
        self.service = Service()
        self.sink = StubSink()
        self.service._sink = self.sink
        self.service._link = StubLink()

    def request(self, text: str) -> None:
        with mock.patch.object(service_mod.win32, "read_clipboard_text",
                               return_value=text):
            self.service.type_clipboard()

    def test_the_clipboard_is_planned_before_the_step_runs(self) -> None:
        self.request("Hi")
        self.assertEqual(len(self.service._typing_planned.strokes), 2)
        self.assertEqual(self.service.router.typing(), 0,
                         "the caller does not touch the router")

    def test_the_step_hands_the_plan_to_the_router(self) -> None:
        self.request("Hi")
        self.service._apply_typing()
        self.assertEqual(self.service.router.typing(), 2)
        self.assertIsNone(self.service._typing_planned, "the request is used once")

    def test_the_clipboard_key_note_queues_the_clipboard(self) -> None:
        with mock.patch.object(service_mod.win32, "read_clipboard_text",
                              return_value="Hi"):
            self.service._on_note("type_requested")
        self.assertIsNotNone(self.service._typing_planned)
        self.service._apply_typing()
        self.assertEqual(self.service.router.typing(), 2)

    def test_nothing_is_typed_without_a_link(self) -> None:
        self.service._link = None
        self.request("Hi")
        self.service._apply_typing()
        self.assertEqual(self.service.router.typing(), 0)

    def test_an_empty_clipboard_queues_nothing(self) -> None:
        self.request("")
        self.service._apply_typing()
        self.assertEqual(self.service.router.typing(), 0)

    def test_text_with_nothing_typable_queues_nothing(self) -> None:
        self.request("中文")
        self.service._apply_typing()
        self.assertEqual(self.service.router.typing(), 0)
