"""Tests for the wire format."""

from __future__ import annotations

import unittest

from winborder import ipc


class TestFrameRoundTrip(unittest.TestCase):
    def test_encode_then_parse(self) -> None:
        parser = ipc.FrameParser()
        frames = parser.feed(ipc.encode_frame(ipc.MsgType.PING))
        self.assertEqual(frames, [(ipc.MsgType.PING, b"")])

    def test_payload_preserved(self) -> None:
        parser = ipc.FrameParser()
        payload = bytes(range(16))
        frames = parser.feed(ipc.encode_frame(ipc.MsgType.STATE, payload))
        self.assertEqual(frames, [(ipc.MsgType.STATE, payload)])

    def test_max_payload_accepted(self) -> None:
        parser = ipc.FrameParser()
        payload = b"\x01" * ipc.MAX_PAYLOAD
        frames = parser.feed(ipc.encode_frame(ipc.DevMsgType.LOG, payload))
        self.assertEqual(frames[0][1], payload)

    def test_oversized_payload_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ipc.encode_frame(ipc.DevMsgType.LOG, b"\x00" * (ipc.MAX_PAYLOAD + 1))

    def test_several_frames_in_one_chunk(self) -> None:
        parser = ipc.FrameParser()
        data = (
            ipc.encode_frame(ipc.MsgType.PING)
            + ipc.encode_frame(ipc.MsgType.RESET)
            + ipc.encode_frame(ipc.MsgType.VERSION_REQ)
        )
        self.assertEqual(len(parser.feed(data)), 3)

    def test_split_across_chunks(self) -> None:
        parser = ipc.FrameParser()
        data = ipc.encode_frame(ipc.MsgType.STATE, b"abcdefgh")
        self.assertEqual(parser.feed(data[:4]), [])
        self.assertEqual(parser.feed(data[4:]), [(ipc.MsgType.STATE, b"abcdefgh")])


class TestFrameResync(unittest.TestCase):
    def test_leading_garbage_skipped(self) -> None:
        parser = ipc.FrameParser()
        frames = parser.feed(b"\x00\x11\x22" + ipc.encode_frame(ipc.MsgType.PING))
        self.assertEqual(frames, [(ipc.MsgType.PING, b"")])
        self.assertEqual(parser.discarded_bytes, 3)

    def test_bad_checksum_discarded_then_recovers(self) -> None:
        parser = ipc.FrameParser()
        bad = bytearray(ipc.encode_frame(ipc.MsgType.PING))
        bad[-1] ^= 0xFF
        good = ipc.encode_frame(ipc.MsgType.RESET)
        frames = parser.feed(bytes(bad) + good)
        self.assertEqual(frames, [(ipc.MsgType.RESET, b"")])
        self.assertEqual(parser.bad_frames, 1)

    def test_illegal_length_recovers(self) -> None:
        parser = ipc.FrameParser()
        bogus = bytes((ipc.MAGIC0, ipc.MAGIC1, 0x01, ipc.MAX_PAYLOAD + 1))
        frames = parser.feed(bogus + ipc.encode_frame(ipc.MsgType.PING))
        self.assertEqual(frames, [(ipc.MsgType.PING, b"")])
        self.assertGreater(parser.bad_frames, 0)

    def test_no_infinite_loop_on_magic_only(self) -> None:
        parser = ipc.FrameParser()
        self.assertEqual(parser.feed(bytes((ipc.MAGIC0, ipc.MAGIC1))), [])


class TestPayloadEncoders(unittest.TestCase):
    def test_state_is_eight_bytes(self) -> None:
        data = ipc.encode_state(0x02, (0x04, 0x05))
        self.assertEqual(len(data), 8)
        self.assertEqual(data[0], 0x02)
        self.assertEqual(data[2:4], b"\x04\x05")

    def test_state_pads_and_truncates(self) -> None:
        self.assertEqual(len(ipc.encode_state(0, ())), 8)
        self.assertEqual(len(ipc.encode_state(0, tuple(range(20)))), 8)

    def test_mouse_move_is_two_signed_shorts(self) -> None:
        self.assertEqual(ipc.encode_mouse_move(-1, 300), b"\xff\xff\x2c\x01")

    def test_mouse_move_clamped(self) -> None:
        self.assertEqual(ipc.encode_mouse_move(99999, -99999), b"\xff\x7f\x00\x80")

    def test_wheel_clamped_to_int8(self) -> None:
        self.assertEqual(ipc.encode_wheel(500, -500), b"\x7f\x81")

    def test_button_mask(self) -> None:
        self.assertEqual(ipc.encode_mouse_button(0x1FF), b"\xff")

    def test_consumer_usage(self) -> None:
        self.assertEqual(ipc.encode_consumer(0xE9), b"\xe9\x00")


class TestDeviceDecoders(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(ipc.decode_version(b"\x01\x02\x03"), (1, 2, 3))

    def test_version_wrong_length(self) -> None:
        with self.assertRaises(ValueError):
            ipc.decode_version(b"\x01")

    def test_nak_known_reason(self) -> None:
        self.assertEqual(ipc.decode_nak(b"\x03\x01"), (0x03, "bad length"))

    def test_nak_unknown_reason(self) -> None:
        code, reason = ipc.decode_nak(b"\x03\x7f")
        self.assertEqual(code, 0x03)
        self.assertIn("unknown", reason)

    def test_nak_too_short(self) -> None:
        with self.assertRaises(ValueError):
            ipc.decode_nak(b"\x01")

    def test_switch_back(self) -> None:
        self.assertEqual(ipc.decode_switch_back(b"\x00"), "device gesture")

    def test_log_utf8(self) -> None:
        self.assertEqual(ipc.decode_log("ok".encode()), "ok")


if __name__ == "__main__":
    unittest.main()
