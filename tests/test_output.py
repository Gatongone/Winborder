"""Tests for effect application against a fake device and fake Win32 state."""

from __future__ import annotations

import unittest
from unittest import mock

from winborder import ipc, model, output, win32


class FakeEngine:
    """Records cursor confinement and input capture requests."""

    def __init__(self) -> None:
        self.clipped: list[str] = []
        self.release_count = 0
        self.suppress_keyboard = False
        self.suppress_mouse = False

    def clip_to_edge(self, side: str, x=None, y=None) -> None:
        self.clipped.append(side)

    def release_clip(self) -> None:
        self.release_count += 1


class FakeLink:
    def __init__(self, accept: bool = True) -> None:
        self.accept = accept
        self.frames: list[tuple[int, bytes]] = []

    def send(self, msg_type: int, payload: bytes) -> bool:
        if not self.accept:
            return False
        self.frames.append((msg_type, payload))
        return True


class TestEffectSink(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.link = FakeLink()
        self.sink = output.EffectSink(self.link, self.engine)

    def test_send_frame_forwarded(self) -> None:
        self.sink.apply([model.SendFrame(ipc.MsgType.PING, b"")])
        self.assertEqual(self.link.frames, [(ipc.MsgType.PING, b"")])
        self.assertEqual(self.sink.sent_frames, 1)
        self.assertEqual(self.sink.failed_frames, 0)

    def test_failed_send_counted(self) -> None:
        link = FakeLink(accept=False)
        sink = output.EffectSink(link, self.engine)
        sink.apply([model.SendFrame(ipc.MsgType.PING, b"")])
        self.assertEqual(sink.failed_frames, 1)

    def test_clip_and_release_toggle_engine(self) -> None:
        self.sink.apply([model.ClipCursor(model.Side.RIGHT)])
        self.assertEqual(self.engine.clipped, ["right"])
        self.assertTrue(self.sink.clip_active)
        self.sink.apply([model.ReleaseCursor()])
        self.assertEqual(self.engine.release_count, 1)
        self.assertFalse(self.sink.clip_active)

    def test_capture_input_applied(self) -> None:
        self.sink.apply([model.CaptureInput(keyboard=True, mouse=True)])
        self.assertTrue(self.engine.suppress_keyboard)
        self.assertTrue(self.engine.suppress_mouse)
        self.sink.apply([model.CaptureInput(keyboard=False, mouse=False)])
        self.assertFalse(self.engine.suppress_keyboard)

    def test_notify_collected(self) -> None:
        notes = self.sink.apply([model.Notify("enter_target")])
        self.assertEqual(notes, ["enter_target"])

    def test_release_all_is_idempotent(self) -> None:
        self.sink.apply([model.ClipCursor(model.Side.RIGHT)])
        self.sink.release_all()
        self.sink.release_all()
        self.assertFalse(self.engine.suppress_keyboard)
        self.assertFalse(self.sink.clip_active)


class TestPlaceCursor(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.sink = output.EffectSink(FakeLink(), self.engine)
        self.positions: list[tuple[int, int]] = []
        self._patches = [
            mock.patch.object(win32, "primary_screen_rect",
                              lambda: (0, 0, 1920, 1080)),
            mock.patch.object(win32, "set_cursor_pos",
                              lambda x, y: self.positions.append((x, y))),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def test_exit_insets_away_from_the_edge(self) -> None:
        # Exiting on the right edge at 25% height must move inwards.
        self.sink.apply([model.PlaceCursor(
            x=1919, y=int(0.25 * 1079), move_inside=60,
            side=model.Side.RIGHT)])
        x, y = self.positions[-1]
        self.assertLess(x, 1919)
        self.assertEqual(x, 1920 - 1 - 60)
        self.assertAlmostEqual(y / 1079, 0.25, delta=0.01)

    def test_each_side_insets_in_the_right_direction(self) -> None:
        cases = {
            model.Side.RIGHT: ((1919, 540), "x", "<"),
            model.Side.LEFT: ((0, 540), "x", ">"),
            model.Side.TOP: ((960, 0), "y", ">"),
            model.Side.BOTTOM: ((960, 1079), "y", "<"),
        }
        for side, (point, axis, direction) in cases.items():
            with self.subTest(side=side):
                self.positions.clear()
                self.sink.apply([model.PlaceCursor(
                    x=point[0], y=point[1], move_inside=40, side=side)])
                x, y = self.positions[-1]
                value = x if axis == "x" else y
                origin = point[0] if axis == "x" else point[1]
                if direction == "<":
                    self.assertLess(value, origin)
                else:
                    self.assertGreater(value, origin)


if __name__ == "__main__":
    unittest.main()
