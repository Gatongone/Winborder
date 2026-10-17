"""Tests for the pure routing state machine."""

from __future__ import annotations

import unittest

from winborder import hid, keymap, model

SCREEN = (1920, 1080)
VK_F1 = 0x70
VK_F2 = 0x71


def make_router(side: model.Side = model.Side.RIGHT, **overrides) -> model.Router:
    cfg = model.Config(side=side, **overrides)
    router = model.Router(config=cfg, screen=SCREEN)
    # Silence is judged from this value, so it has to share the test clock.
    router.note_link_ok(0.0)
    return router


def at_edge(side: model.Side) -> tuple[int, int]:
    w, h = SCREEN
    if side is model.Side.RIGHT:
        return w - 1, h // 2
    if side is model.Side.LEFT:
        return 0, h // 2
    if side is model.Side.TOP:
        return w // 2, 0
    return w // 2, h - 1


def edge_cursor(side: model.Side, fraction: float) -> tuple[int, int]:
    """Cursor position on a screen edge, at the given ratio along it."""
    w, h = SCREEN
    along_x, along_y = int(fraction * w), int(fraction * h)
    if side is model.Side.RIGHT:
        return w - 1, along_y
    if side is model.Side.LEFT:
        return 0, along_y
    if side is model.Side.TOP:
        return along_x, 0
    return along_x, h - 1


def free_ratio(router: model.Router, side: model.Side) -> float:
    """Tracker value on the axis that runs along the edge."""
    if side in (model.Side.TOP, model.Side.BOTTOM):
        return router.pointer_x
    return router.pointer_y


def back_to_pc(side: model.Side) -> tuple[int, int]:
    """One mouse step along the axis that leads back to the PC edge."""
    return {
        model.Side.RIGHT: (-8, 0),
        model.Side.LEFT: (8, 0),
        model.Side.TOP: (0, 8),
        model.Side.BOTTOM: (0, -8),
    }[side]


def into_target(side: model.Side) -> tuple[int, int]:
    """One mouse step along the axis that leads further into the target."""
    dx, dy = back_to_pc(side)
    return -dx, -dy


def into_sign(side: model.Side) -> tuple[int, int]:
    """Unit direction that leads further into the target."""
    dx, dy = into_target(side)
    return (dx // abs(dx) if dx else 0), (dy // abs(dy) if dy else 0)


def step(router: model.Router, events, now: float,
         cursor: tuple[int, int]) -> list[model.Effect]:
    """Tick with the device link kept alive, the way the service does it.

    Silence is judged against the same clock the tests drive, so every step has
    to report the link as healthy unless the test is about losing it.
    """
    router.note_link_ok(now)
    return router.tick(events, now, cursor)


def cross_into(router: model.Router, now: float = 1000.0) -> float:
    """Move into the target from the PC edge and return the test clock."""
    step(router, [model.MouseMove(0, 0)], now, at_edge(router.cfg.side))
    return now


def move_in(router: model.Router, now: float, distance: int = 600) -> float:
    """Push the pointer away from the entry edge by a number of counts."""
    move = into_target(router.cfg.side)
    moved = 0
    while moved < distance:
        now += 0.01
        step(router, [model.MouseMove(*move)], now, at_edge(router.cfg.side))
        moved += abs(move[0]) + abs(move[1])
    return now


def pull_back(router: model.Router, now: float, budget: int = 3000) -> float:
    """Pull toward the entry edge until the mode changes or the budget runs out."""
    move = back_to_pc(router.cfg.side)
    moved = 0
    while moved < budget and router.mode is model.Mode.TARGET:
        now += 0.01
        step(router, [model.MouseMove(*move)], now, at_edge(router.cfg.side))
        moved += abs(move[0]) + abs(move[1])
    return now


class TestEdgeCrossing(unittest.TestCase):
    def test_enters_from_each_edge(self) -> None:
        for side in model.Side:
            with self.subTest(side=side):
                router = make_router(side)
                effects = step(router, 
                    [model.MouseMove(0, 0)], 1000.0, at_edge(side))
                self.assertIs(router.mode, model.Mode.TARGET)
                self.assertTrue(any(isinstance(e, model.ClipCursor)
                                    for e in effects))

    def test_does_not_enter_from_screen_centre(self) -> None:
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, (960, 540))
        self.assertIs(router.mode, model.Mode.PC)

    def test_edge_trigger_can_be_disabled(self) -> None:
        router = make_router(edge_trigger_enabled=False)
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.PC)

    def test_refuses_handoff_when_device_silent(self) -> None:
        """(False, reason) must block capture; otherwise input is swallowed."""
        cfg = model.Config(side=model.Side.RIGHT)
        router = model.Router(
            config=cfg, screen=SCREEN,
            handoff_allowed=lambda: (False, "device link is not open"),
        )
        effects = step(router, [model.MouseMove(0, 0)], 1000.0,
                              at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.PC)
        self.assertTrue(any(isinstance(e, model.Notify) and
                            e.event.startswith("handoff_refused") for e in effects))
        self.assertEqual(router.stats.handoff_refusals, 1)
        self.assertFalse(any(isinstance(e, model.CaptureInput) for e in effects))

    def test_allows_handoff_when_device_ready(self) -> None:
        router = model.Router(
            config=model.Config(side=model.Side.RIGHT), screen=SCREEN,
            handoff_allowed=lambda: (True, ""),
        )
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.TARGET)


class TestRatioMapping(unittest.TestCase):
    """Entry and exit must preserve the position ratio on both screens."""

    def test_entry_preserves_perpendicular_ratio(self) -> None:
        for fraction in (0.25, 1 / 3, 0.5, 0.75):
            with self.subTest(fraction=fraction):
                router = make_router(model.Side.RIGHT)
                y = int(fraction * SCREEN[1])
                step(router, [model.MouseMove(0, 0)], 1000.0, (SCREEN[0] - 1, y))
                self.assertAlmostEqual(router.pointer_y, fraction, places=6)

    def test_entry_ratio_spans_the_whole_edge(self) -> None:
        """Nothing narrows the edge: the ratio is carried as it was."""
        for side in model.Side:
            for fraction in (0.0, 0.25, 1.0):
                with self.subTest(side=side, fraction=fraction):
                    router = make_router(side)
                    step(router, [model.MouseMove(0, 0)], 1000.0,
                         edge_cursor(side, fraction))
                    if fraction == 1.0:
                        continue        # the edge itself is covered below
                    self.assertAlmostEqual(free_ratio(router, side), fraction,
                                           places=6)

    def test_ratio_is_restored_on_exit(self) -> None:
        """Whatever ratio the entry used is the one the exit returns to."""
        router = make_router(model.Side.BOTTOM, pullback_exit=False)
        w, h = SCREEN
        step(router, [model.MouseMove(0, 0)], 1000.0, (w, h))
        self.assertAlmostEqual(router.pointer_x, 1.0, places=6)
        effects = router.leave_target("test", 1001.0)
        place = next(e for e in effects if isinstance(e, model.PlaceCursor))
        self.assertAlmostEqual(place.x / (w - 1), 1.0, delta=0.01)

    def test_entry_sends_no_pointer_motion(self) -> None:
        """Entering must not move the target pointer at all.

        Anything sent on entry is a push into the target's own surface, and a
        target that keeps panels against its edges answers those pushes.
        """
        for side in model.Side:
            with self.subTest(side=side):
                router = make_router(side)
                effects = router.enter_target(at_edge(side), 1000.0)
                moved = [e for e in effects if isinstance(e, model.SendFrame)
                         and e.kind == hid.MOUSE_MOVE]
                self.assertEqual(moved, [])
                self.assertEqual(router._crossing_travel(), 0.0)

    def test_return_sends_no_motion_of_its_own(self) -> None:
        """The return must not push the pointer into the target's edge.

        A target that keeps panels against its edges reads a sustained push into
        one as the matching gesture, so the only motion the target ever sees is
        the user's own.
        """
        for side in model.Side:
            with self.subTest(side=side):
                router = make_router(side)
                now = move_in(router, cross_into(router), distance=400)
                sent = []
                steps = 0
                for _ in range(400):
                    now += 0.01
                    steps += 1
                    effects = step(router, [model.MouseMove(*back_to_pc(side))],
                                   now, at_edge(side))
                    sent += [hid.decode_mouse_move(e.payload) for e in effects
                             if isinstance(e, model.SendFrame)
                             and e.kind == hid.MOUSE_MOVE]
                    if router.mode is model.Mode.PC:
                        break
                self.assertIs(router.mode, model.Mode.PC)
                # Every count sent is one the user moved: reports are batched, so
                # a frame may carry a couple of steps, and the last step may not
                # be flushed once the mode changes, but nothing beyond that.
                self.assertTrue(sent)
                total = sum(abs(dx) + abs(dy) for dx, dy in sent)
                self.assertLessEqual(total, steps * 8)
                self.assertGreaterEqual(total, (steps - 2) * 8)
                self.assertLessEqual(max(abs(dx) + abs(dy) for dx, dy in sent), 24)

    def test_exit_returns_to_same_ratio_on_pc_edge(self) -> None:
        w, h = SCREEN
        for fraction in (0.2, 0.5, 0.8):
            with self.subTest(fraction=fraction):
                router = make_router(model.Side.RIGHT, pullback_exit=False)
                step(router, [model.MouseMove(0, 0)], 1000.0,
                            (w - 1, int(fraction * h)))
                effects = router.leave_target("test", 1001.0)
                place = next(e for e in effects
                             if isinstance(e, model.PlaceCursor))
                self.assertEqual(place.x, w - 1)
                self.assertAlmostEqual(place.y / (h - 1), fraction, delta=0.01)

    def test_round_trip_ratio_is_stable(self) -> None:
        w, h = SCREEN
        for fraction in (0.15, 0.5, 0.85):
            with self.subTest(fraction=fraction):
                router = make_router(model.Side.RIGHT, pullback_exit=False)
                step(router, [model.MouseMove(0, 0)], 1000.0,
                            (w - 1, int(fraction * h)))
                captured = router.pointer_y
                effects = router.leave_target("test", 1001.0)
                place = next(e for e in effects
                             if isinstance(e, model.PlaceCursor))
                self.assertAlmostEqual(place.y / (h - 1), captured, delta=0.01)

    def test_travel_counts_both_directions(self) -> None:
        router = make_router(model.Side.BOTTOM)
        now = move_in(router, cross_into(router), distance=400)
        inside = router._crossing_travel()
        self.assertGreater(inside, 0.0)
        for _ in range(25):
            now += 0.01
            step(router, [model.MouseMove(*back_to_pc(model.Side.BOTTOM))],
                 now, at_edge(model.Side.BOTTOM))
        self.assertAlmostEqual(router._crossing_travel(), inside - 200 / 768,
                               places=6)


class TestPullbackExit(unittest.TestCase):
    def test_exits_on_reaching_far_edge(self) -> None:
        router = make_router(model.Side.RIGHT)
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.TARGET)
        now = move_in(router, cross_into(router))
        for _ in range(400):
            now += 0.01
            step(router, [model.MouseMove(-8, 0)], now, (SCREEN[0] - 1, 540))
            if router.mode is model.Mode.PC:
                break
        self.assertIs(router.mode, model.Mode.PC)

    def test_short_pull_does_not_exit(self) -> None:
        """Moving inside the target must not trigger a return."""
        router = make_router(model.Side.RIGHT)
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        now = move_in(router, cross_into(router))
        for _ in range(5):
            now += 0.02
            step(router, [model.MouseMove(-10, 0)], now, (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.TARGET)

    def test_repeated_small_pull_does_not_exit_early(self) -> None:
        """An accumulator would sum these; the travel must still be inside."""
        router = make_router(model.Side.RIGHT)
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        now = move_in(router, cross_into(router))
        started_at = router.pointer_x
        for _ in range(5):
            now += 0.02
            step(router, [model.MouseMove(-4, 0)], now, (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.TARGET)
        self.assertLess(router.pointer_x, started_at)
        self.assertGreater(router._crossing_travel(), 0.0)

    def test_forward_motion_never_exits(self) -> None:
        router = make_router(model.Side.RIGHT)
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        now = 1000.0
        for _ in range(300):
            now += 0.01
            step(router, [model.MouseMove(20, 0)], now, (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.TARGET)

    def test_disable_flag_prevents_edge_exit(self) -> None:
        router = make_router(model.Side.RIGHT, pullback_exit=False)
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        now = move_in(router, cross_into(router))
        for _ in range(400):
            now += 0.01
            step(router, [model.MouseMove(-20, 0)], now, (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.TARGET)

    def test_every_side_exits_at_its_own_entry_edge(self) -> None:
        for side in model.Side:
            with self.subTest(side=side):
                router = make_router(side)
                step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(side))
                now = move_in(router, cross_into(router))
                move = back_to_pc(side)
                for _ in range(400):
                    now += 0.01
                    step(router, [model.MouseMove(*move)], now, at_edge(side))
                    if router.mode is model.Mode.PC:
                        break
                self.assertIs(router.mode, model.Mode.PC)

    def test_short_excursion_can_still_exit(self) -> None:
        """A return must stay possible however briefly the target was used."""
        router = make_router(model.Side.RIGHT)
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        now = 1000.0
        for _ in range(15):
            now += 0.01
            step(router, [model.MouseMove(8, 0)], now, (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.TARGET)
        pull_back(router, now)
        self.assertIs(router.mode, model.Mode.PC)

    def test_return_needs_the_configured_pull(self) -> None:
        """The return happens at the configured pull and not before."""
        distance = 400
        router = make_router(model.Side.RIGHT, pullback_distance=distance)
        now = move_in(router, cross_into(router), distance=800)
        pushed = 0
        while router.mode is model.Mode.TARGET and pushed < 4000:
            now += 0.01
            step(router, [model.MouseMove(-8, 0)], now, (SCREEN[0] - 1, 540))
            pushed += 8
        self.assertIs(router.mode, model.Mode.PC)
        self.assertGreaterEqual(pushed, 800 + distance - 8)

    def test_moving_back_inside_cancels_the_pull(self) -> None:
        router = make_router(model.Side.RIGHT, pullback_distance=400)
        now = move_in(router, cross_into(router), distance=200)
        step(router, [model.MouseMove(-8, 0)], now + 0.01, (SCREEN[0] - 1, 540))
        pulled = router._crossing_travel()
        now += 0.02
        step(router, [model.MouseMove(80, 0)], now, (SCREEN[0] - 1, 540))
        self.assertGreater(router._crossing_travel(), pulled)
        self.assertIs(router.mode, model.Mode.TARGET)

    def test_pointer_report_exposes_the_return_input(self) -> None:
        router = make_router(model.Side.BOTTOM)
        now = cross_into(router)
        self.assertEqual(router.pointer_report()["travel"], 0.0)
        move_in(router, now, distance=800)
        self.assertGreater(router.pointer_report()["travel"], 0.5)

    def test_pulling_out_without_going_in_still_returns(self) -> None:
        """A user who changes their mind must never be trapped in the target."""
        router = make_router(model.Side.RIGHT)
        now = cross_into(router)
        for _ in range(200):
            now += 0.01
            step(router, [model.MouseMove(-40, 0)], now, (SCREEN[0] - 1, 540))
            if router.mode is model.Mode.PC:
                break
        self.assertIs(router.mode, model.Mode.PC)

    def test_pulling_further_always_returns(self) -> None:
        """However the pointer was moved, a long enough pull comes back."""
        for side in model.Side:
            with self.subTest(side=side):
                router = make_router(side)
                now = move_in(router, cross_into(router), distance=1200)
                for _ in range(20):                       # wander back and forth
                    for move in (into_target(side), back_to_pc(side)):
                        for _ in range(10):
                            now += 0.01
                            step(router, [model.MouseMove(*move)], now, at_edge(side))
                for _ in range(600):
                    if router.mode is model.Mode.PC:
                        break
                    now += 0.01
                    step(router, [model.MouseMove(*back_to_pc(side))], now,
                         at_edge(side))
                self.assertIs(router.mode, model.Mode.PC)


class TestTargetPointerIndependence(unittest.TestCase):
    """The return must land on the entry edge whatever the target pointer does.

    Reports are relative and the target keeps its own pointer, with its own
    speed and its own screen. The simulation below models exactly that: it never
    sees the host's intent, only the frames that were actually sent, moves its
    pointer by a gain the host does not know, and saturates at its own edges.
    """

    SURFACE = 820.0

    def drive(self, side: model.Side, gain: float,
              plan: list[tuple[tuple[int, int], int]]) -> tuple[float, bool]:
        """Run the router against the simulated target; report its pointer.

        The return burst is sent before the mode changes, so a return always
        ends with the target pointer on the entry edge.
        """
        router = make_router(side)
        sign = into_sign(side)
        real = 0.0
        now = 1000.0
        step(router, [], now, at_edge(side))
        for move, count in plan:
            for _ in range(count):
                now += 0.01
                effects = step(router, [model.MouseMove(*move)], now, at_edge(side))
                for effect in effects:
                    if not isinstance(effect, model.SendFrame):
                        continue
                    if effect.kind != hid.MOUSE_MOVE:
                        continue
                    dx, dy = hid.decode_mouse_move(effect.payload)
                    inward = dx * sign[0] + dy * sign[1]
                    real = min(self.SURFACE, max(0.0, real + gain * inward))
                if router.mode is model.Mode.PC:
                    return real, True
        return real, False

    def test_return_lands_on_the_entry_edge(self) -> None:
        for gain in (0.4, 1.0, 2.5, 6.0):
            for outward, excursion in ((1, 120), (8, 400), (40, 3000)):
                with self.subTest(gain=gain, excursion=excursion):
                    real, exited = self.drive(
                        model.Side.BOTTOM, gain,
                        [(into_target(model.Side.BOTTOM), excursion),
                         (back_to_pc(model.Side.BOTTOM),
                          excursion * outward + 600)])
                    self.assertTrue(exited, "the return never fired")
                    self.assertEqual(real, 0.0,
                                     "returned while the target pointer was inside")

    def test_return_lands_on_the_entry_edge_for_every_side(self) -> None:
        for side in model.Side:
            for gain in (0.5, 3.0):
                with self.subTest(side=side, gain=gain):
                    real, exited = self.drive(
                        side, gain,
                        [(into_target(side), 600), (back_to_pc(side), 1400)])
                    self.assertTrue(exited, "the return never fired")
                    self.assertEqual(real, 0.0,
                                     "returned while the target pointer was inside")


class TestKeyboard(unittest.TestCase):
    def setUp(self) -> None:
        self.router = make_router()
        step(self.router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))

    def states(self, effects: list[model.Effect]) -> list[bytes]:
        return [e.payload for e in effects
                if isinstance(e, model.SendFrame) and e.kind == hid.KEYBOARD]

    def test_letter_produces_usage(self) -> None:
        effects = step(self.router, [model.KeyPress(0x41, True)], 1000.1,
                                   (SCREEN[0] - 1, 540))
        # The report is [modifiers][k0..k6]: the first key sits at index 1,
        # because there is no reserved byte in front of the slots.
        self.assertEqual(self.states(effects)[-1][1], 0x04)

    def test_key_release_clears_slot(self) -> None:
        step(self.router, [model.KeyPress(0x41, True)], 1000.1,
                         (SCREEN[0] - 1, 540))
        effects = step(self.router, [model.KeyPress(0x41, False)], 1000.2,
                                   (SCREEN[0] - 1, 540))
        self.assertEqual(self.states(effects)[-1][1:], b"\x00" * hid.KEY_SLOTS)

    def test_modifier_sets_bit_not_slot(self) -> None:
        effects = step(self.router, [model.KeyPress(0xA2, True)], 1000.1,
                                   (SCREEN[0] - 1, 540))
        state = self.states(effects)[-1]
        self.assertEqual(state[0], keymap.MOD_LEFT_CTRL)
        self.assertEqual(state[1:], b"\x00" * hid.KEY_SLOTS)

    def test_every_report_matches_the_map(self) -> None:
        """The payloads must be exactly as long as the report map declares.

        A report whose length disagrees with its descriptor is discarded by the
        host with no error anywhere, which presents as a target that connects,
        subscribes, and then types nothing. That is the fault that cost the most
        time in this project, so the map is parsed here rather than trusted.
        """
        from winborder import ble

        declared = _declared_report_bytes(ble.HID_REPORT_MAP)
        self.assertEqual(
            {report_id: declared[report_id] for report_id in sorted(declared)},
            {1: hid.KEYBOARD_PAYLOAD, 2: hid.MOUSE_REPORT, 3: hid.CONSUMER_PAYLOAD},
        )

        # And the encoders agree with the map, one report each. A movement
        # payload covers the two deltas only; the report adds the buttons and
        # both wheel axes around them.
        self.assertEqual(len(hid.encode_keyboard(0, ())), declared[1])
        self.assertEqual(len(hid.encode_mouse_move(1, 2)), hid.MOUSE_MOVE_PAYLOAD)
        self.assertEqual(declared[2], 1 + hid.MOUSE_MOVE_PAYLOAD)
        self.assertEqual(len(hid.encode_mouse_button(1)), 1)
        self.assertEqual(len(hid.encode_wheel(1)), 2)
        self.assertEqual(len(hid.encode_consumer(0xE9)), declared[3])

    def test_the_mouse_report_carries_a_pan_axis(self) -> None:
        # Both wheel settings feed the same report, and a horizontal detent has
        # nowhere to go unless the map declares a pan axis beside the wheel. The
        # bytes are Usage Page (Consumer) then Usage (AC Pan).
        from winborder import ble

        self.assertIn(bytes([0x05, 0x0C, 0x0A, 0x38, 0x02]), ble.HID_REPORT_MAP)

    def test_every_named_key_is_inside_what_the_map_declares(self) -> None:
        """A key outside the map's usage range can be named and never sent.

        The array's Usage Maximum is the ceiling for every key slot: F13 to F24
        are 0x68 to 0x73, so a map that stopped at 0x65 dropped them in silence.
        """
        from winborder import ble, keymap

        ceiling = _key_array_usage_max(ble.HID_REPORT_MAP)
        too_high = sorted(
            name for name, (_vk, usage) in keymap.KEY_NAMES.items()
            if not keymap._is_modifier(usage) and usage > ceiling)
        self.assertEqual(too_high, [],
                         f"the keyboard report declares usages up to {ceiling:#04x}")

    def test_the_keyboard_uses_every_slot_the_map_declares(self) -> None:
        """The router's rollover cap is the map's slot count.

        A short report is silently dropped; a cap below the slot count would
        also quietly discard the seventh key a user is holding.
        """
        from winborder import ble

        keyboard = _declared_report_bytes(ble.HID_REPORT_MAP)[1]
        self.assertEqual(keyboard, 1 + hid.KEY_SLOTS)
        state = hid.encode_keyboard(0, tuple(range(1, hid.KEY_SLOTS + 1)))
        self.assertEqual(len(state), keyboard)
        self.assertEqual(len(state) - 1, len(set(state[1:])))

    def test_rollover_drops_the_oldest_key(self) -> None:
        for vk in range(0x41, 0x41 + hid.KEY_SLOTS):
            step(self.router, [model.KeyPress(vk, True)], 1000.1,
                             (SCREEN[0] - 1, 540))
        self.assertEqual(len(self.router.keyboard.keys), hid.KEY_SLOTS)
        step(self.router, [model.KeyPress(0x5A, True)], 1000.2,
                         (SCREEN[0] - 1, 540))
        self.assertEqual(len(self.router.keyboard.keys), hid.KEY_SLOTS)
        self.assertNotIn(0x41, self.router.keyboard.keys, "oldest key should go")

    def test_consumer_key_goes_out_as_a_consumer_report(self) -> None:
        effects = step(self.router, [model.KeyPress(0xAF, True)], 1000.1,
                                   (SCREEN[0] - 1, 540))
        consumer = [e.payload for e in effects
                    if isinstance(e, model.SendFrame)
                    and e.kind == hid.CONSUMER]
        self.assertTrue(consumer)
        self.assertEqual(int.from_bytes(consumer[-1], "little"), 0xE8)

    def test_unmapped_key_is_ignored(self) -> None:
        effects = step(self.router, [model.KeyPress(0xFF, True)], 1000.1,
                                   (SCREEN[0] - 1, 540))
        self.assertEqual(self.states(effects)[-1][1:], b"\x00" * hid.KEY_SLOTS)


class TestHotkeys(unittest.TestCase):
    def test_panic_returns_to_pc(self) -> None:
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        effects = step(router, [model.KeyPress(VK_F1, True)], 1000.1,
                              (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.PC)
        self.assertTrue(any(isinstance(e, model.ReleaseCursor) for e in effects))

    def test_panic_works_without_device(self) -> None:
        router = make_router()
        step(router, [model.KeyPress(VK_F1, True)], 1000.0, (960, 540))
        self.assertIs(router.mode, model.Mode.PC)

    def test_toggle_edge_trigger(self) -> None:
        router = make_router()
        step(router, [model.KeyPress(VK_F2, True)], 1000.0, (960, 540))
        self.assertFalse(router.cfg.edge_trigger_enabled)
        step(router, [model.KeyPress(VK_F2, True)], 1000.1, (960, 540))
        self.assertTrue(router.cfg.edge_trigger_enabled)

    def test_ctrl_ctrl_esc_is_forwarded_to_the_target(self) -> None:
        """The gesture is gone, so the keys reach the target again."""
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        for vk in (keymap.VK_CTRL_LEFT, keymap.VK_ESCAPE):
            step(router, [model.KeyPress(vk, True)], 1000.2, (SCREEN[0] - 1, 540))
        self.assertTrue(router.keyboard.keys or router.keyboard.modifiers)

    def test_double_ctrl_returns_to_pc(self) -> None:
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        step(router, [model.KeyPress(keymap.VK_CTRL_LEFT, True)], 1000.1,
                    (SCREEN[0] - 1, 540))
        step(router, [model.KeyPress(keymap.VK_CTRL_LEFT, False)], 1000.2,
                    (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.TARGET)
        step(router, [model.KeyPress(keymap.VK_CTRL_LEFT, True)], 1000.3,
                    (SCREEN[0] - 1, 540))
        step(router, [model.KeyPress(keymap.VK_CTRL_LEFT, False)], 1000.4,
                    (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.PC)


class TestMouseReports(unittest.TestCase):
    def setUp(self) -> None:
        self.router = make_router()
        step(self.router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))

    def moves(self, effects: list[model.Effect]) -> list[tuple[int, int]]:
        out = []
        for e in effects:
            if isinstance(e, model.SendFrame) and e.kind == hid.MOUSE_MOVE:
                out.append(hid.decode_mouse_move(e.payload))
        return out

    def test_large_move_is_chunked(self) -> None:
        self.router.pointer_x = 0.5
        effects = step(self.router, [model.MouseMove(900, 0)], 1000.1,
                                   (SCREEN[0] - 1, 540))
        chunks = self.moves(effects)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(abs(dx) <= model.HID_STEP_LIMIT for dx, _ in chunks))
        self.assertEqual(sum(dx for dx, _ in chunks), 900)

    def test_gain_applied(self) -> None:
        self.router.cfg = model.Config(side=model.Side.RIGHT, sensitivity=2.0)
        effects = step(self.router, [model.MouseMove(10, 0)], 1000.1,
                                   (SCREEN[0] - 1, 540))
        self.assertEqual(sum(dx for dx, _ in self.moves(effects)), 20)

    def test_buttons_reported(self) -> None:
        effects = step(self.router, [model.MouseButton(0x01, True)], 1000.1,
                                   (SCREEN[0] - 1, 540))
        payloads = [e.payload for e in effects
                    if isinstance(e, model.SendFrame)
                    and e.kind == hid.MOUSE_BUTTON]
        self.assertEqual(payloads[-1], b"\x01")

    def test_wheel_direction_default_inverted(self) -> None:
        effects = step(self.router, [model.MouseWheel(-120)], 1000.1,
                                   (SCREEN[0] - 1, 540))
        effects += step(self.router, [model.MouseMove(1, 0)], 1000.6,
                                    (SCREEN[0] - 1, 540))
        wheels = [hid.decode_wheel(e.payload) for e in effects
                  if isinstance(e, model.SendFrame)
                  and e.kind == hid.MOUSE_WHEEL]
        self.assertTrue(wheels)
        self.assertGreater(wheels[0][0], 0)

    def test_pc_mode_forwards_nothing(self) -> None:
        router = make_router()
        effects = step(router, 
            [model.MouseMove(10, 10), model.MouseButton(0x01, True),
             model.MouseWheel(120), model.KeyPress(0x41, True)],
            1000.0, (960, 540))
        forwarded = [e for e in effects if isinstance(e, model.SendFrame)]
        self.assertEqual(forwarded, [])

    def test_a_held_key_is_never_released_to_keep_the_link_alive(self) -> None:
        """A periodic release_all used to let go of whatever was held.

        The reports it was meant to keep alive are already dropped by the
        peripheral when nothing changed, so all it did was make a held key look
        like it was repeating twice a second.
        """
        router = make_router()
        step(router, [model.MouseMove(10, 0)], 1000.0, at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.TARGET)
        step(router, [model.KeyPress(0x41, True)], 1000.1, at_edge(model.Side.RIGHT))

        releases = 0
        states: list[bytes] = []
        for tick in range(40):                    # two seconds of holding still
            # step() reports the link as healthy, as the service does: without it
            # the silence rule would leave the target at 1.5 s and release by
            # design, which is not what this test is about.
            for effect in step(router, [], 1000.2 + tick * 0.05,
                               at_edge(model.Side.RIGHT)):
                if not isinstance(effect, model.SendFrame):
                    continue
                if effect.kind == hid.RELEASE_ALL:
                    releases += 1
                elif effect.kind == hid.KEYBOARD:
                    states.append(effect.payload)
        self.assertEqual(releases, 0, "a held key was released to keep the link alive")
        self.assertTrue(states, "no keyboard state was sent while holding a key")
        self.assertEqual(states[-1][1], 0x04, "the held key is no longer down")


class TestNoChatter(unittest.TestCase):
    def test_cursor_placed_inside_after_exit(self) -> None:
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        effects = router.leave_target("test", 1000.1)
        place = next(e for e in effects if isinstance(e, model.PlaceCursor))
        self.assertGreaterEqual(place.move_inside, 1)

    def test_reentry_blocked_until_inward_motion(self) -> None:
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        step(router, [model.KeyPress(VK_F1, True)], 1000.1,
                    (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.PC)
        # Still pinned at the edge: must not re-enter immediately.
        step(router, [model.MouseMove(0, 0)], 1000.2, at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.PC)


class TestLinkLoss(unittest.TestCase):
    def test_silent_link_forces_pc(self) -> None:
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        router.note_link_ok(1000.0)
        router.tick([model.MouseMove(1, 0)],
                    1000.0 + model.LINK_SILENCE_TIMEOUT_S + 0.1,
                    (SCREEN[0] - 1, 540))
        self.assertIs(router.mode, model.Mode.PC)
        self.assertEqual(router.stats.link_losses, 1)



def _key_array_usage_max(report_map: bytes) -> int:
    """The Usage Maximum the keyboard's key array declares.

    The same walk as :func:`_declared_report_bytes`, but reading the Usage Maximum
    item (prefix 0x2A for a two byte value) that caps the array's values.
    """
    highest = 0
    index = 0
    while index < len(report_map):
        prefix = report_map[index]
        index += 1
        if prefix == 0xFE:
            index += 2 + report_map[index]
            continue
        size = prefix & 0x03
        if size == 3:
            size = 4
        tag = prefix & 0xFC
        data = int.from_bytes(report_map[index:index + size], "little") if size else 0
        index += size
        if tag == 0x28:                          # Usage Maximum (Local item)
            highest = max(highest, data)
    return highest


def _declared_report_bytes(report_map: bytes) -> dict[int, int]:
    """Bytes each report id declares, read out of the descriptor itself.

    A full USB HID parser is not needed: Report ID, Report Size and Report Count
    are enough to total each input report, which is the budget a payload has to
    match.
    """
    reports: dict[int, int] = {}
    current_id = 0
    report_size = 0
    report_count = 0
    bits = 0
    index = 0
    while index < len(report_map):
        prefix = report_map[index]
        index += 1
        if prefix == 0xFE:                      # long item, unused here
            index += 2 + report_map[index]
            continue
        size = prefix & 0x03
        if size == 3:
            size = 4
        tag = prefix & 0xFC
        data = int.from_bytes(report_map[index:index + size], "little") if size else 0
        index += size

        if tag == 0x84:                         # Report ID
            current_id = data
        elif tag == 0x74:                       # Report Size
            report_size = data
        elif tag == 0x94:                       # Report Count
            report_count = data
        elif tag == 0x80:                       # Input
            bits += report_size * report_count
        elif tag == 0xC0:                       # End Collection
            if current_id and bits:
                reports[current_id] = reports.get(current_id, 0) + bits
            bits = 0
    return {report_id: (total + 7) // 8 for report_id, total in reports.items()}

class TestPause(unittest.TestCase):
    """The bridge can be held still without being stopped."""

    def test_nothing_is_routed_while_it_is_held(self) -> None:
        router = make_router()
        router.set_paused(True, 0.0)
        effects = step(router, [model.MouseMove(0, 0), model.KeyPress(vk=0x41,
                                                                    down=True)],
                       1.0, at_edge(model.Side.RIGHT))
        self.assertEqual(effects, [])
        self.assertIs(router.mode, model.Mode.PC)

    def test_holding_it_gives_the_target_back(self) -> None:
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.TARGET)
        effects = router.set_paused(True, 1001.0)
        self.assertIs(router.mode, model.Mode.PC)
        kinds = [type(effect) for effect in effects]
        self.assertIn(model.ReleaseCursor, kinds)
        self.assertIn(model.CaptureInput, kinds)
        capture = next(effect for effect in effects
                       if isinstance(effect, model.CaptureInput))
        self.assertFalse(capture.keyboard)
        self.assertFalse(capture.mouse)

    def test_it_says_so_either_way(self) -> None:
        router = make_router()
        self.assertTrue(any(isinstance(effect, model.Notify)
                            for effect in router.set_paused(True, 0.0)))
        self.assertTrue(any(isinstance(effect, model.Notify)
                            for effect in router.set_paused(False, 1.0)))

    def test_asking_for_the_state_it_is_in_does_nothing(self) -> None:
        """Once paused, asking again changes nothing.

        The first request is reported, because that is what paused the bridge;
        every request after it is a no-op.
        """
        router = make_router()
        self.assertTrue(any(isinstance(effect, model.Notify)
                            for effect in router.set_paused(True, 0.0)))
        self.assertEqual(router.set_paused(True, 1.0), [])

    def test_resuming_does_not_hand_over_at_once(self) -> None:
        """The cursor may well be resting against the edge when it comes back."""
        router = make_router()
        router.set_paused(True, 0.0)
        router.set_paused(False, 1.0)
        step(router, [model.MouseMove(0, 0)], 1.1, at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.PC)

    def test_resuming_crosses_once_the_cursor_comes_back_to_the_edge(self) -> None:
        router = make_router()
        router.set_paused(True, 0.0)
        router.set_paused(False, 1.0)
        later = 1.0 + model.RESUME_COOLDOWN_S + 0.1
        # The cursor was never moved by the host, so nothing has to be moved
        # away before the edge works again: the wait is what holds it off.
        step(router, [model.MouseMove(0, 0)], later, at_edge(model.Side.RIGHT))
        step(router, [model.MouseMove(0, 0)], later + 0.1, at_edge(model.Side.RIGHT))
        self.assertIs(router.mode, model.Mode.TARGET)

    def test_the_link_watchdog_waits_while_it_is_held(self) -> None:
        """A held bridge sends nothing, which must not read as a lost link."""
        router = make_router()
        step(router, [model.MouseMove(0, 0)], 1000.0, at_edge(model.Side.RIGHT))
        router.set_paused(True, 1000.0)
        router.tick([model.MouseMove(1, 0)],
                    1000.0 + model.LINK_SILENCE_TIMEOUT_S + 0.1,
                    (SCREEN[0] - 1, 540))
        self.assertEqual(router.stats.link_losses, 0)
        self.assertTrue(router.paused)


class TestConfigValidation(unittest.TestCase):
    def test_rejects_negative_pull_distance(self) -> None:
        with self.assertRaises(ValueError):
            model.Config(pullback_distance=-1)

    def test_rejects_negative_cooldown(self) -> None:
        with self.assertRaises(ValueError):
            model.Config(enter_cooldown=-0.1)

    def test_defaults(self) -> None:
        cfg = model.Config()
        self.assertIs(cfg.side, model.Side.BOTTOM)
        self.assertTrue(cfg.pullback_exit)
        self.assertTrue(cfg.edge_trigger_enabled)


if __name__ == "__main__":
    unittest.main()
