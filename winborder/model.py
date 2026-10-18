"""Pure routing state machine.

This module contains the process stage of the pipeline and performs no I/O.
It accepts normalised input events and returns a list of effects that the
caller applies. Keeping the stage free of side effects makes every edge
crossing, ratio mapping and pull-back rule directly testable.

Pipeline position::

    input --> model.tick() --> effects --> output
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

from . import hid, keymap, keystrokes

PENDING_MOVE_CAP = 2000.0
HID_STEP_LIMIT = 127
LINK_SILENCE_TIMEOUT_S = 1.5
REPORT_INTERVAL_S = 1.0 / 90.0

# How a queued keystroke is timed: the target sees the key held for the hold, then
# released, and the next key comes after the interval. Twelve milliseconds per
# character is a typing speed a person cannot reach but a keyboard can, and it
# leaves the target time to act on each report.
STROKE_HOLD_S = 0.006
STROKE_INTERVAL_S = 0.012

# How long the bridge stays deaf to the screen edge after being resumed, so that
# resuming with the cursor already resting against the edge does not hand control
# over on the same instant.
RESUME_COOLDOWN_S = 0.5

# Logical target surface used to convert mouse deltas into pointer fractions.
# Deliberately independent of the PC resolution: the host cannot know the real
# target panel size, and the ratio mapping only needs a consistent scale. Using a
# fixed reference keeps the physical feel identical on any PC.
TARGET_REFERENCE_W = 1024.0
TARGET_REFERENCE_H = 768.0


class Side(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


class Mode(str, Enum):
    PC = "pc"
    TARGET = "target"


@dataclass(frozen=True)
class Config:
    side: Side = Side.BOTTOM
    sensitivity: float = 1.0
    accel: float = 0.0
    invert_wheel_v: bool = True
    invert_wheel_h: bool = False
    edge_trigger_enabled: bool = True
    edge_inset: int = 1
    exit_clear_distance: int = 60
    enter_cooldown: float = 0.30
    pullback_exit: bool = True
    # How far the pointer must be pulled towards the PC before the target is
    # left, in logical target pixels.
    #
    # Reports are relative and the target keeps its own pointer, so this counts
    # motion rather than measuring the target screen. Nothing about the target
    # pointer, its screen or its speed has to be known for the rule to hold, and
    # pulling further always returns. The default is tuned for a comfortable
    # return: a longer pull is safer against leaving early but risks pushing the
    # pointer into the target's edge, which targets with edge panels turn into a
    # gesture.
    pullback_distance: int = 300
    panic_keys: tuple[int, ...] = (0x70,)
    #: Pressed while the target has control: the clipboard is typed into it.
    type_clipboard_keys: tuple[int, ...] = (0x72,)
    toggle_edge_keys: tuple[int, ...] = (0x71,)
    notch_up: int = 3
    notch_down: int = 3
    # Key remapping applied to what the target receives, as (virtual key, HID
    # usage) pairs. The settings file writes it by name.
    remap: tuple[tuple[int, int], ...] = ()
    forward_consumer_keys: bool = True
    capture_mouse_buttons: bool = True

    def __post_init__(self) -> None:
        if self.enter_cooldown < 0.0:
            raise ValueError("enter_cooldown must not be negative")
        if self.pullback_distance < 0:
            raise ValueError("pullback_distance must not be negative")
        if self.sensitivity <= 0.0:
            raise ValueError("sensitivity must be greater than zero")
        if self.accel < 0.0:
            raise ValueError("accel must not be negative")


@dataclass(frozen=True)
class MouseMove:
    dx: int
    dy: int


@dataclass(frozen=True)
class MouseButton:
    mask: int
    down: bool


@dataclass(frozen=True)
class MouseWheel:
    delta: int
    horizontal: bool = False


@dataclass(frozen=True)
class KeyPress:
    vk: int
    down: bool
    injected: bool = False


InputEvent = MouseMove | MouseButton | MouseWheel | KeyPress


@dataclass(frozen=True)
class SendFrame:
    """One report for the target.

    ``kind`` is one of the report kinds in :mod:`winborder.hid` and ``payload``
    is the report itself, encoded there. The router produces these; the output
    stage hands them to whichever peripheral is connected.
    """

    kind: str
    payload: bytes


@dataclass(frozen=True)
class ClipCursor:
    side: Side


@dataclass(frozen=True)
class ReleaseCursor:
    pass


@dataclass(frozen=True)
class PlaceCursor:
    """Absolute virtual-screen position, used on exit to preserve the ratio."""

    x: int
    y: int
    move_inside: int
    side: "Side"


@dataclass(frozen=True)
class CaptureInput:
    keyboard: bool
    mouse: bool


@dataclass(frozen=True)
class Notify:
    event: str


Effect = SendFrame | ClipCursor | ReleaseCursor | PlaceCursor | CaptureInput | Notify


@dataclass
class Stats:
    entered: int = 0
    exited: int = 0
    frames: int = 0
    link_losses: int = 0
    handoff_refusals: int = 0
    keys: int = 0
    moves: int = 0
    buttons: int = 0
    wheels: int = 0


@dataclass
class _Keyboard:
    modifiers: int = 0
    keys: list[int] = field(default_factory=list)

    def key_down(self, usage: int) -> None:
        if usage in self.keys:
            return
        # Rollover is capped at the slots the report actually carries, so the
        # last slot is never dead padding. The oldest key is the one dropped:
        # a key the user is still holding is never silently ignored.
        if len(self.keys) >= hid.KEY_SLOTS:
            self.keys.pop(0)
        self.keys.append(usage)

    def key_up(self, usage: int) -> None:
        if usage in self.keys:
            self.keys.remove(usage)

    def clear(self) -> None:
        self.modifiers = 0
        self.keys.clear()

    def snapshot(self) -> bytes:
        return hid.encode_keyboard(self.modifiers, tuple(self.keys))


class Router:
    """Consumes input events, produces effects. Holds all routing state."""

    def __init__(
        self,
        config: Config | None = None,
        screen: tuple[int, int] = (1920, 1080),
        handoff_allowed: callable | None = None,
    ) -> None:
        self.cfg = config or Config()
        self._remap = dict(self.cfg.remap)
        self.screen_w, self.screen_h = screen
        self.handoff_allowed = handoff_allowed

        self.mode = Mode.PC
        self.stats = Stats()
        self.paused = False

        self.pointer_x = 0.5
        self.pointer_y = 0.5
        self.buttons = 0
        self.consumer = 0
        self.keyboard = _Keyboard()

        self._pending_dx = 0.0
        self._pending_dy = 0.0
        self._wheel_up = 0.0
        self._wheel_down = 0.0
        self._wheel_h = 0.0
        self._ctrl_armed = False
        self._ctrl_tap = False
        self._last_report = 0.0
        self._reentry_until = 0.0
        self._inward_left = 0.0
        self._returning = False
        self._guard_last: tuple[int, int] | None = None
        # None until the link is first reported alive. Judging silence before
        # that would blame a link that has not been used yet.
        self._last_tx_ok: float | None = None
        self._link_lost = False

        # Queued keystrokes, and where the queue is in its press/release cycle.
        self._typing: list[keystrokes.Stroke] = []
        self._typing_next_at = 0.0
        self._typing_held = False

    # -- geometry ---------------------------------------------------------

    def set_config(self, config: Config) -> None:
        """Replace the settings at runtime.

        Travel and the pointer anchors describe the settings they were taken
        under, so they are reset rather than carried into the new ones.
        """
        self.cfg = config
        self._remap = dict(config.remap)
        self._pending_dx = self._pending_dy = 0.0
        self._pullback_reset()

    def _pullback_reset(self) -> None:
        self.pointer_x = 0.5
        self.pointer_y = 0.5
        if self.mode is Mode.TARGET:
            self._anchor_from_entry((self.screen_w // 2, self.screen_h // 2))

    def set_screen(self, width: int, height: int) -> None:
        self.screen_w = max(1, width)
        self.screen_h = max(1, height)

    def _reference_span(self) -> float:
        """Logical size of the crossing axis, which the travel is scaled to.

        Travel is measured on one axis, so the distances that describe it are
        scaled by that axis rather than by a shared value, which keeps a
        distance in pixels meaning the same number of mouse counts on every side.
        """
        if self._crossing_axis() == "x":
            return TARGET_REFERENCE_W
        return TARGET_REFERENCE_H

    def _crossing_axis(self) -> str:
        """Axis the pointer crosses into the target on."""
        return "x" if self.cfg.side in (Side.RIGHT, Side.LEFT) else "y"

    def _crossing_travel(self) -> float:
        """Signed travel along the crossing axis, in pointer fractions.

        Zero at the entry edge, positive inside the target. Unlike the free axis
        this is not clamped: it is the net motion since the entry edge was
        established, so it stays meaningful when the target pointer saturates at
        a screen edge and keeps receiving reports it cannot follow.
        """
        if self._crossing_axis() == "x":
            value = self.pointer_x
        else:
            value = self.pointer_y
        if self.cfg.side in (Side.RIGHT, Side.BOTTOM):
            return value
        return 1.0 - value

    def _to_fraction(self, dx: float, dy: float) -> tuple[float, float]:
        """Convert mouse counts to pointer fractions of the logical target surface."""
        return dx / TARGET_REFERENCE_W, dy / TARGET_REFERENCE_H

    def pointer_report(self) -> dict[str, float | bool]:
        """Snapshot of the pointer tracking, for diagnostics.

        The fractions are counters over the relative reports the host sent, not
        target pointer positions. ``travel`` is the net motion since the target
        was entered, negative once it has been pulled back towards the PC, and it
        is what the return rule decides on.
        """
        return {
            "x": self.pointer_x,
            "y": self.pointer_y,
            "travel": self._crossing_travel(),
        }

    # -- lifecycle --------------------------------------------------------

    def note_link_ok(self, now: float) -> None:
        self._last_tx_ok = now
        self._link_lost = False

    def set_paused(self, paused: bool, now: float) -> list[Effect]:
        """Hold the bridge still, or let it go again.

        Pausing is a release rather than a mute. If the target had control it is
        handed back and everything it was holding is let go of, so the PC behaves
        exactly as it does while the host is not running. The link is left alone:
        the board stays paired and connected, and resuming needs no reconnect.

        The guard is armed on the way out, because coming back with the cursor
        already resting against the edge would otherwise hand control over on the
        first tick.
        """
        if bool(paused) == self.paused:
            return []
        self.paused = bool(paused)
        if self.paused:
            # Queued text is dropped rather than held: it was meant for the target
            # the moment it was asked for, and a pause is not a wait.
            self._typing.clear()
            self._typing_held = False
            if self.mode is Mode.TARGET:
                return self.leave_target("paused", now, lock_reentry=True)
            return [Notify("paused")]
        self._arm_resume(now)
        return [Notify("resumed")]

    def _arm_resume(self, now: float) -> None:
        """Make the edge deaf for a moment after the bridge is let go again.

        The clock alone, not the guard distance. The cursor was not moved, so
        there is no motion to consume, and waiting for some would leave the edge
        deaf until the user happened to move the way the guard expects.
        """
        self._returning = True
        self._inward_left = 0.0
        self._guard_last = None
        self._reentry_until = now + max(self.cfg.enter_cooldown, RESUME_COOLDOWN_S)

    def reset_device_state(self) -> list[Effect]:
        self.keyboard.clear()
        self._typing.clear()
        self._typing_held = False
        self.buttons = 0
        self.consumer = 0
        self._pending_dx = self._pending_dy = 0.0
        return [
            SendFrame(hid.KEYBOARD, self.keyboard.snapshot()),
            SendFrame(hid.CONSUMER, hid.encode_consumer(0)),
            SendFrame(hid.MOUSE_BUTTON, hid.encode_mouse_button(0)),
            SendFrame(hid.RELEASE_ALL, b""),
        ]

    def enter_target(self, cursor: tuple[int, int], now: float) -> list[Effect]:
        """Switch to target mode. Returns the effects to apply, or empty on refusal."""
        if self.mode is Mode.TARGET:
            return []
        if self.handoff_allowed is not None:
            allowed, reason = self.handoff_allowed()
            if not allowed:
                self.stats.handoff_refusals += 1
                return [Notify(f"handoff_refused:{reason}")]

        self.mode = Mode.TARGET
        self.stats.entered += 1
        self.keyboard.clear()
        self.buttons = 0
        self.consumer = 0
        self._pending_dx = self._pending_dy = 0.0
        self._wheel_up = self._wheel_down = self._wheel_h = 0.0
        self._ctrl_armed = False
        self._ctrl_tap = False

        self._anchor_from_entry(cursor)

        return [
            ClipCursor(self.cfg.side),
            CaptureInput(keyboard=True, mouse=self.cfg.capture_mouse_buttons),
            SendFrame(hid.RELEASE_ALL, b""),
            Notify("enter_target"),
        ]

    def leave_target(self, reason: str, now: float, lock_reentry: bool = False) -> list[Effect]:
        """Switch back to PC mode and restore the cursor at the mapped ratio."""
        if self.mode is Mode.PC:
            if lock_reentry:
                self._arm_reentry(self.cfg.exit_clear_distance,
                                  self.cfg.enter_cooldown, now)
            return []

        self.mode = Mode.PC
        self.stats.exited += 1
        self.keyboard.clear()
        self._typing.clear()
        self._typing_held = False
        self.buttons = 0
        self.consumer = 0
        self._pending_dx = self._pending_dy = 0.0

        target = self._target_cursor_on_pc()
        distance = self.cfg.exit_clear_distance
        if lock_reentry:
            self._arm_reentry(max(distance, 200), max(self.cfg.enter_cooldown, 1.0), now)
        else:
            self._arm_reentry(distance, self.cfg.enter_cooldown, now)

        return [
            SendFrame(hid.KEYBOARD, self.keyboard.snapshot()),
            SendFrame(hid.CONSUMER, hid.encode_consumer(0)),
            SendFrame(hid.MOUSE_BUTTON, hid.encode_mouse_button(0)),
            SendFrame(hid.RELEASE_ALL, b""),
            ReleaseCursor(),
            CaptureInput(keyboard=False, mouse=False),
            PlaceCursor(x=target[0], y=target[1], move_inside=distance,
                        side=self.cfg.side),
            Notify(f"leave_target:{reason}"),
        ]

    def _anchor_from_entry(self, cursor: tuple[int, int]) -> None:
        """Carry the entry ratio on the PC edge over to the target edge.

        The free axis keeps the ratio it had on the PC edge, which is what makes
        the entry and the exit land at the same relative position on both
        screens. The crossing axis starts at zero travel: entering sends no
        motion at all, so the target pointer is left exactly where it is.
        """
        x, y = cursor
        # Right and bottom enter at the low end of their axis, left and top at
        # the high end, so zero travel sits on the entry edge for every side.
        edge = 0.0 if self.cfg.side in (Side.RIGHT, Side.BOTTOM) else 1.0
        if self._crossing_axis() == "x":
            self.pointer_y = _clamp01(y / self.screen_h)
            self.pointer_x = edge
        else:
            self.pointer_x = _clamp01(x / self.screen_w)
            self.pointer_y = edge

    def _target_cursor_on_pc(self) -> tuple[int, int]:
        """Map the target pointer ratio back onto the PC entry edge."""
        w, h = self.screen_w, self.screen_h
        side = self.cfg.side
        if side is Side.RIGHT:
            return w - 1, int(round(self.pointer_y * (h - 1)))
        if side is Side.LEFT:
            return 0, int(round(self.pointer_y * (h - 1)))
        if side is Side.TOP:
            return int(round(self.pointer_x * (w - 1))), 0
        return int(round(self.pointer_x * (w - 1))), h - 1

    def _arm_reentry(self, distance: int, cooldown: float, now: float) -> None:
        """Hold off a new entry until the guard distance and cooldown pass.

        The deadline derives from the injected clock, so the rule stays testable
        without waiting for real time.
        """
        self._returning = True
        self._inward_left = float(max(1, distance))
        self._reentry_until = now + max(0.0, cooldown)

    # -- main step --------------------------------------------------------

    def tick(
        self,
        events: Iterable[InputEvent],
        now: float,
        cursor: tuple[int, int],
    ) -> list[Effect]:
        if self.paused:
            # Nothing is routed while the bridge is held. The caller still drains
            # the input, so no motion piles up for the moment it resumes.
            return []
        effects: list[Effect] = []
        for event in events:
            if isinstance(event, KeyPress):
                self.stats.keys += 1
                if event.down and self._typing:
                    # A real key is the user taking the keyboard back: the rest of
                    # the queue would type over whatever that key does.
                    effects += self._cancel_typing()
                    effects.append(Notify("typing_cancelled"))
                effects += self._on_key(event, now)
            elif isinstance(event, MouseMove):
                self.stats.moves += 1
                effects += self._on_move(event, cursor, now)
            elif isinstance(event, MouseButton):
                self.stats.buttons += 1
                effects += self._on_button(event)
            elif isinstance(event, MouseWheel):
                self.stats.wheels += 1
                effects += self._on_wheel(event)
        effects += self._typing_step(now)
        effects += self._maybe_report(now)
        if (self.mode is Mode.TARGET and self._last_tx_ok is not None
                and now - self._last_tx_ok > LINK_SILENCE_TIMEOUT_S):
            self.stats.link_losses += 1
            self._last_tx_ok = now
            effects += self.leave_target("link_lost", now)
        return effects

    def _on_move(
        self, event: MouseMove, cursor: tuple[int, int], now: float
    ) -> list[Effect]:
        if self.mode is Mode.PC:
            return self._check_enter(cursor, now)
        if event.dx == 0 and event.dy == 0:
            return []

        gain = self.cfg.sensitivity
        if self.cfg.accel > 0.0:
            speed = (event.dx * event.dx + event.dy * event.dy) ** 0.5
            gain *= 1.0 + self.cfg.accel * min(speed, 60.0) / 60.0

        self._pending_dx = _clamp(self._pending_dx + event.dx * gain,
                                  -PENDING_MOVE_CAP, PENDING_MOVE_CAP)
        self._pending_dy = _clamp(self._pending_dy + event.dy * gain,
                                  -PENDING_MOVE_CAP, PENDING_MOVE_CAP)

        fx, fy = self._to_fraction(event.dx * gain, event.dy * gain)
        if self._crossing_axis() == "x":
            self.pointer_x += fx
            self.pointer_y = _clamp01(self.pointer_y + fy)
        else:
            self.pointer_y += fy
            self.pointer_x = _clamp01(self.pointer_x + fx)

        if self.cfg.pullback_exit and self._return_requested():
            return self.leave_target("edge", now)
        return []

    def _return_requested(self) -> bool:
        """True once the pointer has been pulled far enough towards the PC.

        The travel counts the reports sent since the target was entered; it is
        not a position on the target screen, because the host cannot read where
        the target keeps its pointer. A return is therefore a deliberate pull of
        ``pullback_distance`` towards the PC, and nothing about the target
        pointer, its screen or its own speed has to be known for it to hold.
        Because the pull is a count, pulling further always returns, so there is
        no state the user can get stuck in.
        """
        need = self.cfg.pullback_distance / self._reference_span()
        return self._crossing_travel() <= -need

    def _check_enter(self, cursor: tuple[int, int], now: float) -> list[Effect]:
        if not self.cfg.edge_trigger_enabled:
            return []
        x, y = cursor
        if self._returning:
            self._consume_guard(x, y, now)
            if self._returning:
                return []
        w, h = self.screen_w, self.screen_h
        inset = self.cfg.edge_inset
        side = self.cfg.side
        hit = (
            (side is Side.RIGHT and x >= w - 1 - inset)
            or (side is Side.LEFT and x <= inset)
            or (side is Side.TOP and y <= inset)
            or (side is Side.BOTTOM and y >= h - 1 - inset)
        )
        if not hit:
            return []
        return self.enter_target(cursor, now)

    def _consume_guard(self, x: int, y: int, now: float) -> None:
        if self._guard_last is not None:
            dx = x - self._guard_last[0]
            dy = y - self._guard_last[1]
            inward = -dx if self.cfg.side is Side.RIGHT else (
                dx if self.cfg.side is Side.LEFT else (
                    -dy if self.cfg.side is Side.BOTTOM else dy))
            if inward > 0.0:
                self._inward_left = max(0.0, self._inward_left - inward)
        self._guard_last = (x, y)
        if self._inward_left > 0.0:
            return
        if now < self._reentry_until:
            return
        self._returning = False

    def _on_button(self, event: MouseButton) -> list[Effect]:
        if self.mode is Mode.PC:
            return []
        self.buttons = (self.buttons | event.mask) if event.down else (
            self.buttons & ~event.mask)
        out: list[Effect] = [
            SendFrame(hid.MOUSE_BUTTON, hid.encode_mouse_button(self.buttons))
        ]
        if event.down:
            out.append(Notify("target_click"))
        return out

    def _on_wheel(self, event: MouseWheel) -> list[Effect]:
        if self.mode is Mode.PC:
            return []
        detents = event.delta / 120.0
        if event.horizontal:
            self._wheel_h = _clamp(self._wheel_h + detents, -20.0, 20.0)
        elif detents > 0:
            self._wheel_up = _clamp(self._wheel_up + detents, 0.0, 20.0)
        else:
            self._wheel_down = _clamp(self._wheel_down + detents, -20.0, 0.0)
        return []

    def _on_key(self, event: KeyPress, now: float) -> list[Effect]:
        if event.down:
            if event.vk in self.cfg.panic_keys:
                return self.leave_target(f"panic:{keymap.describe_vk(event.vk)}",
                                       now, lock_reentry=True)
            if event.vk in self.cfg.toggle_edge_keys:
                self.cfg = _replace(self.cfg,
                                    edge_trigger_enabled=not self.cfg.edge_trigger_enabled)
                return [Notify(
                    f"edge_trigger:{'on' if self.cfg.edge_trigger_enabled else 'off'}")]
            if (event.vk in self.cfg.type_clipboard_keys
                    and self.mode is Mode.TARGET):
                # The key is swallowed: it is a request to the host, not something
                # the target has any use for. Nothing is read here -- the router has
                # no I/O, so the service answers the note with the clipboard.
                return [Notify("type_requested")]

        if self.mode is Mode.PC:
            return []

        if self._is_double_ctrl(event, now):
            return self.leave_target("double_ctrl", now)

        self._apply_key(event)
        return self._maybe_report(now, force=True)

    def _is_double_ctrl(self, event: KeyPress, now: float) -> bool:
        """True on the release of the second Ctrl tap.

        Settling on the release rather than the press keeps a recenter or a
        shortcut from being swallowed by the pairing.
        """
        if event.vk not in (keymap.VK_CTRL_LEFT, keymap.VK_CTRL_RIGHT):
            if event.down:
                self._ctrl_armed = False
                self._ctrl_tap = False
            return False
        if event.down:
            self._ctrl_armed = True
            return False
        if not self._ctrl_armed:
            return False
        self._ctrl_armed = False
        if self._ctrl_tap:
            self._ctrl_tap = False
            return True
        self._ctrl_tap = True
        return False

    def _apply_key(self, event: KeyPress) -> None:
        vk = event.vk
        usage = self._remap.get(vk)
        if usage is None:
            usage = keymap.VK_TO_HID.get(vk)
        if usage is not None:
            # A remapped key may land on a modifier, which the report carries as
            # a bit rather than as a key slot.
            bit = keymap.modifier_bit(usage)
            if bit is not None:
                if event.down:
                    self.keyboard.modifiers |= bit
                else:
                    self.keyboard.modifiers &= ~bit
            elif event.down:
                self.keyboard.key_down(usage)
            else:
                self.keyboard.key_up(usage)
            return
        bit = keymap.VK_TO_MODIFIER.get(vk)
        if bit is not None:
            if event.down:
                self.keyboard.modifiers |= bit
            else:
                self.keyboard.modifiers &= ~bit
            return
        if self.cfg.forward_consumer_keys and vk in keymap.VK_TO_CONSUMER:
            self.consumer = keymap.VK_TO_CONSUMER[vk] if event.down else 0

    # -- typing -----------------------------------------------------------

    def type_text(self, plan: keystrokes.Plan) -> str:
        """Queue text to be typed into the target, and say whether it was taken.

        A keyboard report is a key state and not a character, so this cannot be
        one frame: the plan is played out at the pace in ``STROKE_*_S``, a press
        and a release per character. A second request while one is playing is
        refused rather than interleaved, and so is one that arrives while the user
        is holding keys: the report carries only one state, so typing over a held
        key would let go of it.
        """
        if not plan.strokes:
            return "empty"
        if self._typing or self._typing_held:
            return "busy"
        if self.keyboard.keys or self.keyboard.modifiers:
            return "keys_held"
        self._typing = list(plan.strokes)
        self._typing_next_at = 0.0
        self._typing_held = False
        return "queued"

    def typing(self) -> int:
        """How many keystrokes are still to be played."""
        return len(self._typing) + (1 if self._typing_held else 0)

    def _cancel_typing(self) -> list[Effect]:
        """Drop the rest of the queue, letting go of a key that is still held."""
        self._typing.clear()
        if not self._typing_held:
            return []
        self._typing_held = False
        self.keyboard.clear()
        return [SendFrame(hid.KEYBOARD, self.keyboard.snapshot())]

    def _typing_step(self, now: float) -> list[Effect]:
        """One press or one release, whichever is due."""
        if self._typing_held:
            if now < self._typing_next_at:
                return []
            self.keyboard.clear()
            self._typing_held = False
            self._typing_next_at = now + STROKE_INTERVAL_S - STROKE_HOLD_S
            self.stats.frames += 1
            return [SendFrame(hid.KEYBOARD, self.keyboard.snapshot())]
        if not self._typing or now < self._typing_next_at:
            return []
        stroke = self._typing.pop(0)
        self.keyboard.modifiers = stroke.modifiers
        self.keyboard.keys[:] = [stroke.usage]
        self._typing_held = True
        self._typing_next_at = now + STROKE_HOLD_S
        self.stats.frames += 1
        return [SendFrame(hid.KEYBOARD, self.keyboard.snapshot())]

    # -- output framing ---------------------------------------------------

    def _maybe_report(self, now: float, force: bool = False) -> list[Effect]:
        """The frames one step puts on the wire, and nothing else.

        There used to be a periodic ``release_all`` here, meant as a keep alive.
        It did not keep anything alive -- the peripheral drops a report that is
        identical to the last one it sent, so an idle router was already silent --
        and while a key was held it released that key and pressed it again twice a
        second, which the target reads as the key repeating.
        """
        out: list[Effect] = []
        if self.mode is not Mode.TARGET:
            return out
        if not force and now - self._last_report < REPORT_INTERVAL_S:
            return out
        self._last_report = now

        guard = 0
        while ((abs(self._pending_dx) >= 1.0 or abs(self._pending_dy) >= 1.0)
               and guard < 32):
            guard += 1
            dx = int(_clamp(round(self._pending_dx), -HID_STEP_LIMIT, HID_STEP_LIMIT))
            dy = int(_clamp(round(self._pending_dy), -HID_STEP_LIMIT, HID_STEP_LIMIT))
            if dx == 0 and dy == 0:
                break
            self._pending_dx -= dx
            self._pending_dy -= dy
            out.append(SendFrame(hid.MOUSE_MOVE, hid.encode_mouse_move(dx, dy)))
            self.stats.frames += 1

        v_sign = -1 if self.cfg.invert_wheel_v else 1
        h_sign = -1 if self.cfg.invert_wheel_h else 1
        if self._wheel_up >= 1.0:
            steps = int(self._wheel_up)
            self._wheel_up -= steps
            out.append(SendFrame(hid.MOUSE_WHEEL,
                                 hid.encode_wheel(v_sign * steps * self.cfg.notch_up, 0)))
        if self._wheel_down <= -1.0:
            steps = int(-self._wheel_down)
            self._wheel_down += steps
            out.append(SendFrame(hid.MOUSE_WHEEL,
                                 hid.encode_wheel(v_sign * -steps * self.cfg.notch_down, 0)))
        if abs(self._wheel_h) >= 1.0:
            steps = int(_clamp(self._wheel_h, -HID_STEP_LIMIT, HID_STEP_LIMIT))
            self._wheel_h -= steps
            out.append(SendFrame(hid.MOUSE_WHEEL,
                                 hid.encode_wheel(0, h_sign * steps)))

        out.append(SendFrame(hid.KEYBOARD, self.keyboard.snapshot()))
        out.append(SendFrame(hid.CONSUMER, hid.encode_consumer(self.consumer)))
        self.stats.frames += len(out)
        return out


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _replace(cfg: Config, **changes: object) -> Config:
    data = {f: getattr(cfg, f) for f in cfg.__dataclass_fields__}
    data.update(changes)
    return Config(**data)  # type: ignore[arg-type]
