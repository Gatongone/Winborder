"""Tests for the hardware-free BLE transport.

The sink turns the router's reports into calls on the HID peripheral, so it can
be tested without a radio or a target device. What matters here is the mapping: a
wrong length or a misread payload is exactly the class of fault that reaches the
target as silence rather than as an error.
"""

from __future__ import annotations

import asyncio
import threading
import unittest

from winborder import ble, hid
from winborder.ble import BleFrameSink, _status_name as status_name


class StubPeripheral:
    """Records what the sink asked the peripheral to do."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.subscribed = True
        self.stopped = False

    @property
    def is_subscribed(self) -> bool:
        return self.subscribed

    def keyboard_state(self, modifier: int, keys: list[int]) -> bool:
        self.calls.append(("keyboard", modifier, list(keys)))
        return True

    def mouse_report(self, buttons: int, dx: int, dy: int, wheel: int = 0,
                     pan: int = 0) -> bool:
        self.calls.append(("mouse", buttons, dx, dy, wheel, pan))
        return True

    def consumer_press(self, usage: int) -> bool:
        self.calls.append(("consumer_press", usage))
        return True

    def consumer_release(self) -> bool:
        self.calls.append(("consumer_release",))
        return True

    def release_all(self) -> bool:
        self.calls.append(("release_all",))
        return True

    def refresh_subscriptions(self) -> None:
        self.calls.append(("refresh",))

    def stop(self) -> None:
        self.stopped = True


def sink() -> tuple[BleFrameSink, StubPeripheral]:
    peripheral = StubPeripheral()
    return BleFrameSink(peripheral), peripheral  # type: ignore[arg-type]


class TestKeyboardReports(unittest.TestCase):
    def test_a_state_becomes_one_keyboard_report(self) -> None:
        frame_sink, peripheral = sink()
        payload = hid.encode_keyboard(0x02, (0x04,))       # left shift + 'a'
        self.assertTrue(frame_sink.send(hid.KEYBOARD, payload))
        # The payload is [modifiers][k0..k6] with no reserved byte, so the sink
        # forwards the modifier and all seven slots.
        self.assertEqual(peripheral.calls,
                         [("keyboard", 0x02, [0x04, 0, 0, 0, 0, 0, 0])])

    def test_every_one_of_the_seven_slots_reaches_the_peripheral(self) -> None:
        """Seven keys fit in a report, so none of them may be dropped."""
        frame_sink, peripheral = sink()
        keys = tuple(range(0x04, 0x0B))
        frame_sink.send(hid.KEYBOARD, hid.encode_keyboard(0x00, keys))
        self.assertEqual(peripheral.calls,
                         [("keyboard", 0x00, [0x04, 0x05, 0x06, 0x07, 0x08,
                                              0x09, 0x0A])])

    def test_a_short_keyboard_payload_is_refused_not_truncated(self) -> None:
        frame_sink, peripheral = sink()
        self.assertFalse(frame_sink.send(hid.KEYBOARD, bytes(7)))
        self.assertEqual(peripheral.calls, [])
        self.assertEqual(frame_sink.bad_frames, 1)

    def test_release_reaches_every_report(self) -> None:
        frame_sink, peripheral = sink()
        frame_sink.send(hid.RELEASE_ALL, b"")
        self.assertEqual(peripheral.calls, [("release_all",)])


class TestMouseReports(unittest.TestCase):
    def test_move_keeps_the_delta_signs(self) -> None:
        frame_sink, peripheral = sink()
        frame_sink.send(hid.MOUSE_MOVE, hid.encode_mouse_move(-30, 12))
        self.assertEqual(peripheral.calls, [("mouse", 0, -30, 12, 0, 0)])

    def test_buttons_are_remembered_for_later_moves(self) -> None:
        frame_sink, peripheral = sink()
        frame_sink.send(hid.MOUSE_BUTTON, hid.encode_mouse_button(1))
        frame_sink.send(hid.MOUSE_MOVE, hid.encode_mouse_move(5, 0))
        self.assertEqual(peripheral.calls[1], ("mouse", 1, 5, 0, 0, 0))

    def test_wheel_goes_out_as_the_vertical_component(self) -> None:
        # A wheel payload is two bytes and not the four of a movement payload,
        # so measuring it against the wrong count drops the detent in silence.
        frame_sink, peripheral = sink()
        frame_sink.send(hid.MOUSE_WHEEL, hid.encode_wheel(-3))
        self.assertEqual(peripheral.calls, [("mouse", 0, 0, 0, -3, 0)])

    def test_a_horizontal_detent_reaches_the_pan_axis(self) -> None:
        # The map declares a pan axis beside the wheel, so a sideways detent has
        # a field to land in. This branch used to keep the vertical step and drop
        # the horizontal one without a word.
        frame_sink, peripheral = sink()
        frame_sink.send(hid.MOUSE_WHEEL, hid.encode_wheel(2, -4))
        self.assertEqual(peripheral.calls, [("mouse", 0, 0, 0, 2, -4)])

    def test_a_short_move_payload_is_refused(self) -> None:
        frame_sink, peripheral = sink()
        self.assertFalse(frame_sink.send(hid.MOUSE_MOVE, b"\x01\x02"))
        self.assertEqual(peripheral.calls, [])


class TestConsumerReports(unittest.TestCase):
    def test_a_usage_presses_then_the_zero_releases(self) -> None:
        frame_sink, peripheral = sink()
        frame_sink.send(hid.CONSUMER, hid.encode_consumer(0x00E9))
        frame_sink.send(hid.CONSUMER, hid.encode_consumer(0))
        self.assertEqual(peripheral.calls,
                         [("consumer_press", 0x00E9), ("consumer_release",)])

    def test_a_short_usage_is_refused(self) -> None:
        frame_sink, peripheral = sink()
        self.assertFalse(frame_sink.send(hid.CONSUMER, b"\x01"))
        self.assertEqual(peripheral.calls, [])
        self.assertEqual(frame_sink.bad_frames, 1)

    def test_an_unknown_kind_is_counted_not_raised(self) -> None:
        frame_sink, peripheral = sink()
        self.assertFalse(frame_sink.send("teleport", b""))
        self.assertEqual(peripheral.calls, [])
        self.assertEqual(frame_sink.bad_frames, 1)


class TestLinkSurface(unittest.TestCase):
    """The sink is the only link the service has."""

    def test_open_means_a_target_is_subscribed(self) -> None:
        frame_sink, peripheral = sink()
        self.assertTrue(frame_sink.is_open)
        peripheral.subscribed = False
        self.assertFalse(frame_sink.is_open)

    def test_health_counts_delivered_reports(self) -> None:
        frame_sink, _ = sink()
        frame_sink.send(hid.KEYBOARD, hid.encode_keyboard(0, ()))
        self.assertEqual(frame_sink.written_frames, 1)

    def test_a_refused_report_is_not_counted_as_written(self) -> None:
        frame_sink, _ = sink()
        frame_sink.send(hid.KEYBOARD, bytes(7))
        self.assertEqual(frame_sink.written_frames, 0)

    def test_close_stops_the_peripheral(self) -> None:
        frame_sink, peripheral = sink()
        frame_sink.close()
        self.assertTrue(peripheral.stopped)
        self.assertIn(("release_all",), peripheral.calls)

    def test_a_refresh_reaches_the_peripheral(self) -> None:
        """The watchdog asks the sink, and the sink asks the radio."""
        frame_sink, peripheral = sink()
        frame_sink.refresh_subscriptions()
        self.assertEqual(peripheral.calls, [("refresh",)])


class TestSubscriptionTracking(unittest.TestCase):
    """Who is subscribed is the whole meaning of "connected".

    ``SubscribedClientsChanged`` is the one event that says a target arrived, and
    an event that is not delivered looks exactly like a target that never came.
    Both the event and the poll behind it land in the same place, so these are
    the rules for what that place says: once per change, and never twice for the
    same state, because the poll asks every second.
    """

    def peripheral(self) -> tuple[ble.BleHidPeripheral, list[tuple[str, str]]]:
        events: list[tuple[str, str]] = []
        # Built without __init__: the constructor loads WinRT, and none of this
        # bookkeeping needs a radio.
        peripheral = ble.BleHidPeripheral.__new__(ble.BleHidPeripheral)
        peripheral._subscribed = set()
        peripheral._sub_lock = threading.Lock()
        peripheral._serving = True
        peripheral._subscriptions_unreadable = False
        peripheral._reports = {}
        peripheral._on_event = lambda kind, text: events.append((kind, text))
        return peripheral, events

    def test_the_first_report_is_announced(self) -> None:
        peripheral, events = self.peripheral()
        peripheral._note_subscription(1, True)
        self.assertTrue(peripheral.is_subscribed)
        self.assertEqual([kind for kind, _ in events], ["subscribed"])

    def test_the_same_state_twice_is_said_once(self) -> None:
        peripheral, events = self.peripheral()
        for _ in range(5):
            peripheral._note_subscription(1, True)
        self.assertEqual(len(events), 1, "a poll every second is not news")

    def test_losing_the_last_report_is_the_link_going(self) -> None:
        peripheral, events = self.peripheral()
        peripheral._note_subscription(1, True)
        peripheral._note_subscription(1, False)
        self.assertFalse(peripheral.is_subscribed)
        self.assertEqual([kind for kind, _ in events],
                         ["subscribed", "unsubscribed"])

    def test_a_report_that_was_never_subscribed_says_nothing(self) -> None:
        peripheral, events = self.peripheral()
        peripheral._note_subscription(2, False)
        self.assertEqual(events, [])

    def test_one_of_three_reports_is_still_a_connected_target(self) -> None:
        peripheral, _ = self.peripheral()
        peripheral._note_subscription(1, True)
        peripheral._note_subscription(2, False)
        self.assertTrue(peripheral.is_subscribed)

    def test_a_subscriber_present_at_start_is_adopted(self) -> None:
        """Windows hands a new server the subscribers that are already there."""
        peripheral, events = self.peripheral()
        peripheral._serving = False
        peripheral._note_subscription(1, True)
        self.assertEqual([kind for kind, _ in events], ["adopted", "subscribed"])

    def test_a_poll_sees_a_subscriber_the_event_missed(self) -> None:
        """This is the whole point of the poll: a missed event is not a lost run."""

        class Report:
            subscribed_clients = ("client",)

        peripheral, events = self.peripheral()
        peripheral._reports = {1: Report()}
        peripheral._read_subscriptions()
        self.assertTrue(peripheral.is_subscribed)
        self.assertEqual([kind for kind, _ in events], ["subscribed"])

    def test_an_unreadable_list_is_named_once_and_then_left_alone(self) -> None:
        """The collections projection is a package of its own, and it went missing.

        Every read raised, the raise arrived inside a callback where nothing could
        report it, and the window said "waiting for the target" over a link that
        was up and subscribed. One line naming the package is the fix; five
        hundred lines is a log nobody reads.
        """

        class Report:
            @property
            def subscribed_clients(self):
                raise ModuleNotFoundError(
                    "No module named 'winrt.windows.foundation.collections'")

        peripheral, _ = self.peripheral()
        peripheral._reports = {1: Report()}
        with self.assertLogs("winborder.ble", level="WARNING") as captured:
            for _ in range(5):
                peripheral._read_subscriptions()
        self.assertEqual(len(captured.output), 1, captured.output)
        self.assertIn("winrt-Windows.Foundation.Collections", captured.output[0])
        self.assertTrue(peripheral._subscriptions_unreadable)


class TestAdvertisementStatus(unittest.TestCase):
    """The window shows this line, so a number would say nothing at all."""

    def test_the_enum_is_named_not_counted(self) -> None:
        # The projection's enum is an IntEnum: str() of it is "2", and the name
        # is the part a reader can use.
        class Status:
            name = "STARTED_WITHOUT_ALL_ADVERTISEMENT_DATA"

        self.assertEqual(status_name(Status()),
                         "started without all advertisement data")

    def test_something_that_is_not_an_enum_still_reads(self) -> None:
        self.assertEqual(status_name(2), "2")


class TestAttributeProtection(unittest.TestCase):
    """A report may only be reached over an encrypted link.

    Reaching one is what makes the host start pairing and show its own prompt.
    When every attribute was plain, the host subscribed first and bonded after,
    and the subscription it had already taken was dropped in silence: the host
    showed no prompt at all, Windows showed one instead, and nothing was ever
    delivered. This test exists so that fault cannot come back quietly.
    """

    def test_the_reports_are_protected(self) -> None:
        self.assertTrue(ble.is_protected(ble.UUID_REPORT))

    def test_the_report_reference_is_protected(self) -> None:
        self.assertTrue(ble.is_protected(ble.UUID_REPORT_REFERENCE))

    def test_a_uuid_in_any_case_is_recognised(self) -> None:
        self.assertTrue(ble.is_protected(ble.UUID_REPORT.upper()))

    def test_the_control_plane_stays_reachable(self) -> None:
        """Protocol Mode and the control point are what the host writes first."""
        for value in (ble.UUID_PROTOCOL_MODE, ble.UUID_HID_CONTROL):
            with self.subTest(uuid=value):
                self.assertFalse(ble.is_protected(value))


class TestNotificationDelivery(unittest.TestCase):
    """A report goes out through an awaitable that is not a coroutine.

    The projection's ``notify_value_async`` returns an ``IAsyncOperation``.
    ``asyncio.run_coroutine_threadsafe`` refuses anything that is not a coroutine,
    so passing the operation itself raised "A coroutine object is required" for
    every report -- and the caller logged it quietly, which made the whole app
    look like a link that connects and does nothing.
    """

    class Operation:
        """Stands in for IAsyncOperation: awaitable, not a coroutine."""

        def __await__(self):
            yield from ()
            return "delivered"

    class Characteristic:
        def notify_value_async(self, buffer):
            return TestNotificationDelivery.Operation()

    def test_it_is_wrapped_in_a_real_coroutine(self) -> None:
        pending = ble._deliver(self.Characteristic(), b"\x01")
        self.assertTrue(asyncio.iscoroutine(pending), "not a coroutine")
        self.assertEqual(asyncio.run(pending), "delivered")

    def test_the_raw_operation_cannot_be_a_task(self) -> None:
        """create_task is what run_coroutine_threadsafe uses under the hood."""
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        with self.assertRaises(TypeError):
            loop.create_task(self.Operation())  # type: ignore[arg-type]


class TestNotificationResults(unittest.TestCase):
    """A notification reports one status per client, not one status."""

    class Result:
        def __init__(self, status: int) -> None:
            self.status = status

    def test_every_client_accepting_is_a_delivery(self) -> None:
        self.assertTrue(ble._delivered([self.Result(0), self.Result(0)]))

    def test_one_client_refusing_is_not(self) -> None:
        self.assertFalse(ble._delivered([self.Result(0), self.Result(1)]))

    def test_no_client_at_all_is_not_a_delivery(self) -> None:
        self.assertFalse(ble._delivered([]))


class TestReportFraming(unittest.TestCase):
    """The characteristic value is the bare report, with no identifier byte.

    Measured on an iPad: with one octet in front, pushing the mouse right moved
    the target pointer down, pushing it up or down moved nothing, and the
    keyboard would have had its modifier byte sitting where the first key
    belongs.
    """

    def test_a_mouse_report_keeps_every_axis_in_place(self) -> None:
        payload = bytes([0x00, 0x28, 0x00, 0x00])   # buttons, x=+40, y=0, wheel
        self.assertEqual(ble.report_value(payload), payload)

    def test_a_keyboard_report_keeps_its_modifier_first(self) -> None:
        payload = hid.encode_keyboard(0x02, (0x04,))
        self.assertEqual(ble.report_value(payload), payload)
        self.assertEqual(len(ble.report_value(payload)), hid.KEYBOARD_PAYLOAD)


if __name__ == "__main__":
    unittest.main()
