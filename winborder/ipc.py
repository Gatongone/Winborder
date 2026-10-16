"""Wire format shared with the ESP32 firmware, plus HID report encoding.

Frame layout (little endian)::

    +--------+--------+--------+--------+
    | 0xA5   | 0x5A   | type   | len    |
    +--------+--------+--------+--------+
    | payload[len]                      |
    +-----------------------------------+
    | checksum                          |  (sum(payload) + type + len) & 0xFF
    +-----------------------------------+

The parser is self-synchronising: an unknown byte is skipped and scanning
resumes, so a corrupt frame cannot desynchronise the stream permanently.

Keyboard input uses state snapshots rather than event deltas. The host sends
the full set of currently pressed keys every report cycle and the device
deduplicates, which makes a dropped frame harmless.
"""

from __future__ import annotations

import struct
from enum import IntEnum

MAGIC0 = 0xA5
MAGIC1 = 0x5A

# Must match MAX_PAYLOAD in firmware/ble_bridge/ble_bridge.ino.
MAX_PAYLOAD = 64

DEFAULT_BAUDRATE = 115200


class MsgType(IntEnum):
    """Host to device."""

    PING = 0x01
    VERSION_REQ = 0x02
    STATE = 0x03
    MOUSE_MOVE = 0x04
    MOUSE_BUTTON = 0x05
    MOUSE_WHEEL = 0x06
    RESET = 0x07
    CONFIG = 0x08
    CONSUMER = 0x09


class DevMsgType(IntEnum):
    """Device to host."""

    VERSION = 0x81
    ACK = 0x82
    NAK = 0x83
    SWITCH_BACK = 0x84
    KEY_ECHO = 0x85
    LOG = 0x86


NAK_REASON = {
    0x01: "bad length",
    0x02: "unknown type",
    0x03: "target mode disabled",
}

SWITCH_BACK_REASON = {
    0x00: "device gesture",
    0x01: "host request",
}


def encode_frame(msg_type: int, payload: bytes = b"") -> bytes:
    """Serialise one frame. Raises ValueError when payload exceeds MAX_PAYLOAD."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too long: {len(payload)} > {MAX_PAYLOAD}")
    checksum = (sum(payload) + msg_type + len(payload)) & 0xFF
    return (
        bytes((MAGIC0, MAGIC1, msg_type & 0xFF, len(payload)))
        + payload
        + bytes((checksum,))
    )


class FrameParser:
    """Incremental frame parser over an arbitrary byte stream."""

    _NEED_MORE = 0
    _RESYNC = 1
    _FRAME = 2

    def __init__(self) -> None:
        self._buf = bytearray()
        self.bad_frames = 0
        self.discarded_bytes = 0

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        """Consume raw bytes and return every complete frame found."""
        self._buf.extend(data)
        out: list[tuple[int, bytes]] = []
        while True:
            status, msg_type, payload = self._try_pop()
            if status == self._NEED_MORE:
                return out
            if status == self._FRAME:
                out.append((msg_type, payload))

    def _try_pop(self) -> tuple[int, int, bytes]:
        buf = self._buf
        while len(buf) >= 2 and not (buf[0] == MAGIC0 and buf[1] == MAGIC1):
            del buf[0]
            self.discarded_bytes += 1
        if len(buf) < 4:
            return self._NEED_MORE, 0, b""
        msg_type = buf[2]
        length = buf[3]
        if length > MAX_PAYLOAD:
            del buf[0]
            self.discarded_bytes += 1
            self.bad_frames += 1
            return self._RESYNC, 0, b""
        total = 4 + length + 1
        if len(buf) < total:
            return self._NEED_MORE, 0, b""
        payload = bytes(buf[4 : 4 + length])
        checksum = buf[4 + length]
        expected = (sum(payload) + msg_type + length) & 0xFF
        if checksum != expected:
            del buf[0]
            self.discarded_bytes += 1
            self.bad_frames += 1
            return self._RESYNC, 0, b""
        del buf[:total]
        return self._FRAME, msg_type, payload

    def reset(self) -> None:
        self._buf.clear()


def encode_state(modifiers: int, keys: tuple[int, ...]) -> bytes:
    """Keyboard state snapshot: modifiers, reserved byte, six key slots."""
    slots = list(keys[:6]) + [0] * max(0, 6 - len(keys))
    return bytes((modifiers & 0xFF, 0x00, *slots[:6]))


def encode_mouse_move(dx: int, dy: int) -> bytes:
    return struct.pack("<hh", _clamp(dx, -32768, 32767), _clamp(dy, -32768, 32767))


def encode_mouse_button(mask: int) -> bytes:
    return bytes((mask & 0xFF,))


def encode_wheel(vertical: int, horizontal: int = 0) -> bytes:
    return struct.pack("<bb", _clamp(vertical, -127, 127), _clamp(horizontal, -127, 127))


def encode_consumer(usage: int) -> bytes:
    return struct.pack("<H", usage & 0xFFFF)


def decode_version(payload: bytes) -> tuple[int, int, int]:
    if len(payload) != 3:
        raise ValueError(f"version payload must be 3 bytes, got {len(payload)}")
    return payload[0], payload[1], payload[2]


def decode_nak(payload: bytes) -> tuple[int, str]:
    if len(payload) < 2:
        raise ValueError(f"nak payload must be >= 2 bytes, got {len(payload)}")
    return payload[0], NAK_REASON.get(payload[1], f"unknown reason 0x{payload[1]:02X}")


def decode_switch_back(payload: bytes) -> str:
    code = payload[0] if payload else 0
    return SWITCH_BACK_REASON.get(code, f"unknown reason {code}")


def decode_log(payload: bytes) -> str:
    return payload.decode("utf-8", "replace")


def _clamp(value: int, low: int, high: int) -> int:
    return low if value < low else high if value > high else value
