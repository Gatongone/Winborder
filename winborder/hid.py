"""HID report payloads, and the report kinds the router emits them under.

The router decides *what* the target should receive; this module is the only
place that knows how those decisions are laid out as bytes. Each payload is byte
for byte the HID report that goes on the air, so the length of every one of them
is fixed by the report map in :mod:`winborder.gatt`:

| Report | Payload | Layout |
| --- | --- | --- |
| keyboard | 8 bytes | modifier bitfield (1) + seven key slots (7) |
| mouse | 5 bytes | buttons (1) + x (1) + y (1) + wheel (1) + pan (1) |
| consumer | 2 bytes | one 16 bit usage |

A report whose length disagrees with the map is discarded by the host with no
error at all, which presents as a target that connects and subscribes and then
types nothing, so the counts here and the map there are one fact in two places.
"""

from __future__ import annotations

import struct

#: Report kinds, as the router names them. Plain strings rather than the wire
#: message type bytes the old serial bridge used: nothing is framed any more.
KEYBOARD = "keyboard"
MOUSE_MOVE = "mouse_move"
MOUSE_BUTTON = "mouse_button"
MOUSE_WHEEL = "mouse_wheel"
CONSUMER = "consumer"
RELEASE_ALL = "release_all"

#: Key slots in a keyboard report, after the modifier byte.
KEY_SLOTS = 7

#: Bytes of the fixed part of a keyboard report: modifiers plus the key slots.
KEYBOARD_PAYLOAD = 1 + KEY_SLOTS

#: Bytes of a mouse report: buttons, x, y, wheel, pan.
MOUSE_REPORT = 5

#: Bytes of a movement payload: two signed 16 bit deltas. Not the width of a
#: report: a movement is measured against this, and a report adds the buttons and
#: both wheel axes to it.
MOUSE_MOVE_PAYLOAD = 4

#: Bytes of a button-only payload: the button bitmap on its own, the same width
#: as the button field of a movement report.
BUTTON_PAYLOAD = 1

#: Bytes of a wheel payload: the vertical and horizontal step, one signed byte
#: each. Shorter than a movement payload, so it is measured against its own count
#: rather than against :data:`MOUSE_MOVE_PAYLOAD`.
WHEEL_PAYLOAD = 2

#: Bytes of a consumer report: one 16 bit usage.
CONSUMER_PAYLOAD = 2


def encode_keyboard(modifiers: int, keys: tuple[int, ...]) -> bytes:
    """A keyboard state snapshot: modifiers, then the key slots.

    A snapshot rather than an event, so a dropped report costs nothing: the next
    one carries the whole truth. There is no reserved byte between the modifier
    bitmap and the slots.
    """
    slots = list(keys[:KEY_SLOTS]) + [0] * max(0, KEY_SLOTS - len(keys))
    return bytes((modifiers & 0xFF, *slots[:KEY_SLOTS]))


def encode_mouse_move(dx: int, dy: int) -> bytes:
    """A relative pointer move. The wheel is left at rest."""
    return struct.pack("<hh", _clamp(dx, -32768, 32767), _clamp(dy, -32768, 32767))


def encode_mouse_button(mask: int) -> bytes:
    """The button bitmap, with no movement."""
    return bytes((mask & 0xFF,))


def encode_wheel(vertical: int, horizontal: int = 0) -> bytes:
    """A wheel detent: the vertical step and the horizontal one, if any.

    The two are separate axes of the report, so a detent that moves only sideways
    carries a zero vertical step.
    """
    return struct.pack("<bb", _clamp(vertical, -127, 127), _clamp(horizontal, -127, 127))


def encode_consumer(usage: int) -> bytes:
    """One consumer page usage, or zero to release."""
    return struct.pack("<H", usage & 0xFFFF)


def decode_mouse_move(payload: bytes) -> tuple[int, int]:
    """The dx, dy a mouse move payload carries."""
    dx, dy = struct.unpack("<hh", payload)
    return dx, dy


def decode_wheel(payload: bytes) -> tuple[int, int]:
    """The vertical and horizontal wheel steps a wheel payload carries."""
    return struct.unpack("<bb", payload)


def _clamp(value: int, low: int, high: int) -> int:
    return low if value < low else high if value > high else value
