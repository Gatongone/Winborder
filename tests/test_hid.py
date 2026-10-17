"""Tests for the HID report payloads and the report kinds they travel under.

Each payload here is byte for byte the report that goes on the air, so the layout
is the whole contract: the host discards a report whose length disagrees with the
report map and reports nothing at all, which reaches the user as a target that
connects and then types nothing. The sizes are therefore pinned here as tightly
as the layouts, because a wrong length is the fault that cannot be seen.
"""

from __future__ import annotations

import struct
import unittest

from winborder import hid


class TestReportKinds(unittest.TestCase):
    def test_the_kinds_are_distinct_strings(self) -> None:
        """Nothing is framed any more, so a kind is a name and not a byte."""
        kinds = (hid.KEYBOARD, hid.MOUSE_MOVE, hid.MOUSE_BUTTON, hid.MOUSE_WHEEL,
                 hid.CONSUMER, hid.RELEASE_ALL)
        self.assertTrue(all(isinstance(kind, str) for kind in kinds))
        self.assertEqual(len(set(kinds)), len(kinds))


class TestKeyboardPayload(unittest.TestCase):
    def test_the_payload_is_eight_bytes(self) -> None:
        data = hid.encode_keyboard(0x02, (0x04, 0x05))
        self.assertEqual(len(data), 8)
        self.assertEqual(len(data), hid.KEYBOARD_PAYLOAD)
        self.assertEqual(data[0], 0x02)

    def test_the_keys_start_right_after_the_modifiers(self) -> None:
        """There is no reserved byte between the modifiers and the slots.

        The report map declares one modifier byte and seven key slots, so the
        first key sits at index 1 and the whole report is eight bytes.
        """
        data = hid.encode_keyboard(0x00, (0x04, 0x05))
        self.assertEqual(data[1:3], b"\x04\x05")
        self.assertEqual(hid.KEY_SLOTS, 7)
        self.assertEqual(hid.KEYBOARD_PAYLOAD, 1 + hid.KEY_SLOTS)

    def test_the_slots_are_padded(self) -> None:
        self.assertEqual(hid.encode_keyboard(0, ()), b"\x00" * 8)
        self.assertEqual(hid.encode_keyboard(0, (0x04,)), b"\x00\x04" + b"\x00" * 6)

    def test_extra_keys_are_dropped(self) -> None:
        data = hid.encode_keyboard(0, tuple(range(20)))
        self.assertEqual(len(data), hid.KEYBOARD_PAYLOAD)
        self.assertEqual(data[1:], bytes(range(hid.KEY_SLOTS)))

    def test_the_modifiers_are_one_byte(self) -> None:
        self.assertEqual(hid.encode_keyboard(0x1FF, ())[0], 0xFF)


class TestMouseAndConsumerPayloads(unittest.TestCase):
    def test_the_size_constants_measure_what_is_encoded(self) -> None:
        """A payload checked against the wrong count is dropped without a word.

        The sink refuses a payload whose length disagrees with the constant for
        its kind, so a constant that does not describe its encoder turns into a
        report that is never sent and an error nobody sees.
        """
        self.assertEqual(len(hid.encode_keyboard(0, ())), hid.KEYBOARD_PAYLOAD)
        self.assertEqual(len(hid.encode_mouse_move(0, 0)), hid.MOUSE_MOVE_PAYLOAD)
        self.assertEqual(len(hid.encode_wheel(0)), hid.WHEEL_PAYLOAD)
        self.assertEqual(len(hid.encode_consumer(0)), hid.CONSUMER_PAYLOAD)

    def test_move_is_two_signed_shorts(self) -> None:
        self.assertEqual(hid.encode_mouse_move(-1, 300), b"\xff\xff\x2c\x01")
        self.assertEqual(len(hid.encode_mouse_move(0, 0)), hid.MOUSE_MOVE_PAYLOAD)

    def test_move_is_clamped(self) -> None:
        self.assertEqual(hid.encode_mouse_move(99999, -99999), b"\xff\x7f\x00\x80")

    def test_button_mask(self) -> None:
        self.assertEqual(hid.encode_mouse_button(0x1FF), b"\xff")
        self.assertEqual(hid.encode_mouse_button(0x05), b"\x05")

    def test_wheel_is_clamped_to_int8(self) -> None:
        self.assertEqual(hid.encode_wheel(500, -500), b"\x7f\x81")

    def test_wheel_rests_horizontally_by_default(self) -> None:
        self.assertEqual(hid.encode_wheel(3), b"\x03\x00")

    def test_consumer_usage(self) -> None:
        self.assertEqual(hid.encode_consumer(0xE9), b"\xe9\x00")
        self.assertEqual(len(hid.encode_consumer(0)), hid.CONSUMER_PAYLOAD)


class TestPayloadDecoders(unittest.TestCase):
    """The sink decodes what the router encoded, so the two have to agree."""

    def test_mouse_move_round_trips(self) -> None:
        for dx, dy in ((0, 0), (-30, 12), (127, -127), (-32768, 32767)):
            with self.subTest(dx=dx, dy=dy):
                self.assertEqual(
                    hid.decode_mouse_move(hid.encode_mouse_move(dx, dy)), (dx, dy))

    def test_wheel_round_trips(self) -> None:
        for vertical, horizontal in ((0, 0), (3, 0), (-3, 5), (127, -127)):
            with self.subTest(vertical=vertical, horizontal=horizontal):
                self.assertEqual(
                    hid.decode_wheel(hid.encode_wheel(vertical, horizontal)),
                    (vertical, horizontal))

    def test_a_short_mouse_payload_is_rejected(self) -> None:
        with self.assertRaises(struct.error):
            hid.decode_mouse_move(b"\x01\x02")


if __name__ == "__main__":
    unittest.main()
