"""Service orchestration: wires the input, process and output stages together.

Responsibilities are limited to lifecycle and data flow. All routing rules live
in :mod:`winborder.model` and the peripheral itself lives in
:mod:`winborder.ble`.
"""

from __future__ import annotations

import logging
import threading
import time

from . import keystrokes, model, win32
from .ble import BleFrameSink, BleHidPeripheral
from .input import InputEngine
from .output import EffectSink

log = logging.getLogger("winborder.service")

TICK_INTERVAL_S = 1.0 / 250.0
SCREEN_REFRESH_TICKS = 250
#: How often the link is asked who is subscribed, in ticks: once a second. Fast
#: enough that a missed subscription event costs a moment, slow enough that the
#: question is free.
SUBSCRIPTION_REFRESH_TICKS = 250
RECONNECT_INTERVAL_S = 2.0


def _refusal_explained(reason: str) -> str:
    """Turn a router refusal reason into something the user can act on.

    The refusal is logged, not shown modally, so it has to carry the next step
    with it: "device link is not open" says nothing to someone who expects the
    cursor to cross.
    """
    if reason == "device link is not open":
        return ("not handing over yet: no target is connected. Pair this PC from "
                "the target's own Bluetooth settings; the name in that list is "
                "this computer's Bluetooth name")
    return "not handing over yet: " + reason


def _unit(value: float) -> float:
    """Clamp a fraction to the [0, 1] range used by the trace."""
    return min(1.0, max(0.0, value))


class Service:
    """Runs the bridge until stopped."""

    def __init__(self, config: model.Config | None = None) -> None:
        self.cfg = config or model.Config()

        # The name a target lists, which Windows keeps apart from the computer
        # name. Read once: it is what the target has to look for, so both the log
        # and the Devices page have to name the same thing.
        self.device_name = win32.bluetooth_name()

        self.engine = InputEngine()
        self.router = model.Router(
            config=self.cfg,
            screen=self._screen_size(),
            handoff_allowed=self._handoff_allowed,
        )
        self._link: BleFrameSink | None = None
        self._sink: EffectSink | None = None
        self._stop = threading.Event()
        self._ticks = 0
        self._last_written = 0
        self._link_failed = False
        self._pause_wanted = False
        self._refused_reason: str | None = None
        self._target_listening = False
        # Set from another thread, applied by the step on this one.
        self._typing_planned: keystrokes.Plan | None = None
        # Where the link's delivered count stood when the text was queued,
        # so the end of a paste can say whether the target took any of it.
        self._typing_start_frames: int | None = None
        self._typing_chars = 0
        self._cursor: tuple[int, int] = (0, 0)

    # -- wiring -----------------------------------------------------------

    def _screen_size(self) -> tuple[int, int]:
        left, top, right, bottom = win32.primary_screen_rect()
        return max(1, right - left), max(1, bottom - top)

    def _handoff_allowed(self) -> tuple[bool, str]:
        """Refuse to capture input unless the device link is open.

        Capturing without a live device would swallow the keyboard and confine
        the cursor while nothing responds, which the user cannot distinguish
        from a device fault. Returning (False, reason) blocks the handoff.
        """
        if self._link is None or not self._link.is_open:
            return False, "device link is not open"
        return True, ""

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self.engine.start_background()
        self._connect()

    def run(self) -> None:
        """Blocking main loop."""
        self.start()
        log.debug("bridge running, target side=%s", self.cfg.side.value)
        try:
            while not self._stop.is_set():
                self._step()
                time.sleep(TICK_INTERVAL_S)
        finally:
            self.shutdown()

    def request_stop(self) -> None:
        self._stop.set()

    def apply_config(self, config: model.Config) -> None:
        """Swap in settings changed while the bridge is running.

        The window thread calls this while the service thread is stepping. The
        router reads one immutable config per step, so replacing the reference is
        enough; only the state that described the old settings is reset.
        """
        self.cfg = config
        self.router.set_config(config)

    def set_paused(self, paused: bool) -> None:
        """Hold the bridge still, or let it go again.

        Only a request: the step on the service thread is what changes the router
        and puts the frames that release the target on the wire. Pausing and
        resuming are both safe to ask for at any time, and asking for the state it
        is already in does nothing.
        """
        self._pause_wanted = bool(paused)

    def type_clipboard(self) -> dict[str, object]:
        """Ask the service thread to type the clipboard's text into the target.

        The clipboard is read and the text planned here, on the caller's thread:
        the clipboard can wait a few milliseconds for another program to let go of
        it, and the step must not. Only the plan crosses over, so the router is
        touched by one thread and the step decides whether there is anywhere to
        type.

        The answer is what the caller can say out loud right away: how many
        keystrokes were queued, how many characters the layout cannot type, or
        that there was nothing to type and why.
        """
        plan = keystrokes.plan(win32.read_clipboard_text())
        if not plan.strokes:
            return {"result": "empty", "keys": 0, "skipped": plan.skipped,
                    "truncated": plan.truncated}
        if self._link is None or self._sink is None:
            return {"result": "no_target", "keys": 0, "skipped": plan.skipped,
                    "truncated": plan.truncated}
        if self.router.paused:
            # A paused router returns before the queue is played, so text queued now
            # would sit there until the bridge was unpaused and then type itself.
            return {"result": "paused", "keys": 0, "skipped": plan.skipped,
                    "truncated": plan.truncated}
        self._typing_planned = plan
        return {"result": "queued", "keys": len(plan.strokes),
                "skipped": plan.skipped, "truncated": plan.truncated}

    def status(self) -> dict[str, object]:
        """Snapshot for the debug status line and the pointer trace.

        Both positions are normalized to their own surface so the PC cursor and
        the tracked target pointer can be read side by side. The target value is
        a counter over the reports that were sent, not a measurement of where the
        target put its pointer.
        """
        link = self._link
        pointer = self.router.pointer_report()
        return {
            "mode": self.router.mode.value,
            "paused": self.router.paused,
            "side": self.router.cfg.side.value,
            "cursor": self._cursor_fraction(),
            "pointer": (_unit(pointer["x"]), _unit(pointer["y"])),
            "travel": pointer["travel"],
            "frames": self.router.stats.frames,
            "written": link.written_frames if link else 0,
            "bad": link.bad_frames if link else 0,
            "connected": bool(link and link.is_open),
            # Whether anything is on the air at all, and under what name. The
            # window shows both on the Devices page, where "nothing is
            # advertising" and "which entry is this PC" are the two questions a
            # target that will not connect leaves behind.
            "advertising": (link.peripheral.advertising_status if link
                            else "not started"),
            "name": self.device_name,
        }

    def _cursor_fraction(self) -> tuple[float, float]:
        """PC cursor position as a fraction of the primary screen."""
        left, top, right, bottom = win32.primary_screen_rect()
        x, y = self._cursor
        return (_unit((x - left) / max(1, right - left - 1)),
                _unit((y - top) / max(1, bottom - top - 1)))

    def shutdown(self) -> None:
        self._stop.set()
        if self._sink is not None:
            self._sink.release_all()
        if self._link is not None:
            self._link.close()
            self._link = None
        try:
            self.engine.stop()
        except Exception:
            log.debug("input engine stop failed", exc_info=True)
        win32.release_clip_global()

    # -- link management --------------------------------------------------

    def _connect(self) -> None:
        """Publish the PC as the BLE peripheral.

        The peripheral starts advertising immediately, but it is not usable until
        a target subscribes, and is_open reflects exactly that. Nothing here
        triggers pairing: Windows cannot initiate it as a peripheral, so the user
        pairs from the target's own Bluetooth settings.
        """
        if self._link is not None:
            return
        try:
            peripheral = BleHidPeripheral(on_event=self._on_ble_event)
            peripheral.start()
        except Exception as exc:
            if not self._link_failed:
                log.warning("BLE peripheral unavailable: %s", exc)
                self._link_failed = True
            return

        if self._link_failed:
            log.info("BLE peripheral advertising again")
        self._link = BleFrameSink(peripheral)
        self._link_failed = False
        self._sink = EffectSink(self._link, self.engine)
        self._sink.apply(self.router.reset_device_state())
        # Windows does not let an application set the advertised name, so say
        # which one to look for. That name is the Bluetooth name of this PC, not
        # its computer name, and only the radio itself knows it.
        log.info("advertising as %r; pair it from the target's own Bluetooth "
                 "settings", self.device_name or "this PC")

    def _on_ble_event(self, kind: str, text: str) -> None:
        if kind in ("subscribed", "unsubscribed"):
            # The target subscribes to three reports in a row, so the raw events
            # are three lines about one connection. What matters is the moment it
            # starts listening and the moment it stops, and the link itself knows
            # which of the two it is in: the count does not have to be read out of
            # the text.
            listening = self._link is not None and self._link.is_open
            if listening != self._target_listening:
                self._target_listening = listening
                log.info("the target is connected and listening" if listening
                         else "the target is gone; waiting for it to come back")
            else:
                log.debug("ble %s: %s", kind, text)
            if kind == "subscribed":
                # A fresh subscription is the one event that makes the refusal
                # notice worth saying again if the link is lost later.
                self._refused_reason = None
            return
        if kind == "report-map-read":
            # The first thing a HID host asks for once it is on the link: the
            # descriptor is what tells it what the reports mean, so a host that
            # reads it has found the service and is about to subscribe. Without
            # this line, "the target never arrived" and "the target arrived and
            # stopped here" are the same silence, and that is the state the user
            # cannot act on.
            log.info("the target is connected and reading the HID descriptor")
            return
        if kind == "started":
            # The one state that means the PC is on the air, in the words the
            # rule below gives: the service says it, the peripheral only details.
            log.info("%s", text)
            return
        # Everything else is for whoever is debugging: a read, an advertisement
        # restarting, a report the target wrote back.
        log.debug("ble %s: %s", kind, text)

    def _ensure_link(self) -> None:
        if self._link is not None and self._link.is_open:
            return
        if self._link is not None:
            # Advertising without a subscriber is normal while waiting for the
            # target, so the peripheral is kept up rather than restarted: a
            # restart changes its address and invalidates a bond the target made.
            return
        self._connect()

    # -- main step --------------------------------------------------------

    def _step(self) -> None:
        now = time.monotonic()
        self._ticks += 1
        # Read unconditionally: the trace has to report the real cursor even
        # while the link is down and the rest of the step is skipped.
        self._cursor = win32.get_cursor_pos()
        if self._ticks % SCREEN_REFRESH_TICKS == 0:
            width, height = self._screen_size()
            self.router.set_screen(width, height)

        self._apply_pause(now)
        self._apply_typing()
        self._ensure_link()
        link = self._link
        if link is None or self._sink is None:
            time.sleep(RECONNECT_INTERVAL_S)
            return

        # The subscription event is the only one that says a target arrived, and
        # an event that never fires looks like a target that never came. Asking
        # the link instead costs nothing and keeps the window honest.
        if self._ticks % SUBSCRIPTION_REFRESH_TICKS == 0:
            link.refresh_subscriptions()

        # Link health is judged by reports the peripheral actually delivered, not
        # by how many the router produced: a report with no subscriber behind it
        # is not a healthy link.
        if link.written_frames != self._last_written:
            self._last_written = link.written_frames
            self.router.note_link_ok(now)

        raw_dx, raw_dy = self.engine.take_raw_delta()
        events: list[model.InputEvent] = []
        if raw_dx or raw_dy:
            events.append(model.MouseMove(raw_dx, raw_dy))
        for event in self.engine.drain():
            if hasattr(event, "vk"):
                events.append(model.KeyPress(
                    vk=event.vk, down=event.down, injected=event.injected))
            elif hasattr(event, "mask"):
                events.append(model.MouseButton(mask=event.mask, down=event.down))
            else:
                events.append(model.MouseWheel(delta=event.delta,
                                               horizontal=event.horizontal))

        effects = self.router.tick(events, now, self._cursor)
        for note in self._sink.apply(effects):
            self._on_note(note)
        self._report_typing(link)

    def _apply_pause(self, now: float) -> None:
        """Carry out a pause or a resume that was asked for by another thread."""
        if self._pause_wanted == self.router.paused:
            return
        effects = self.router.set_paused(self._pause_wanted, now)
        if self._sink is not None:
            for note in self._sink.apply(effects):
                self._on_note(note)
        log.info("the bridge is %s",
                 "paused, the PC has the keyboard and mouse"
                 if self._pause_wanted else "running again")

    def _report_typing(self, link: object) -> None:
        """Say how a paste ended, and whether the target took any of it.

        The delivered count is the only honest answer: a target that is not
        listening, or a text field that was not focused, looks exactly like a paste
        that worked from this side of the link.
        """
        if self._typing_start_frames is None or self.router.typing():
            return
        accepted = link.written_frames - self._typing_start_frames
        self._typing_start_frames = None
        log.info("typed %d characters, %d reports accepted",
                 self._typing_chars, accepted)
        if accepted == 0:
            log.warning("the target accepted no keystrokes: it is not listening, "
                        "or no text field had focus")

    def _apply_typing(self) -> None:
        """Hand a clipboard request to the router, and say what became of it."""
        plan, self._typing_planned = self._typing_planned, None
        if plan is None:
            return
        if not plan.strokes:
            log.info("nothing to type: the clipboard holds no text this layout can "
                     "type")
            return
        if self._link is None or self._sink is None:
            log.info("not typing: the target is not connected")
            return
        reason = self.router.type_text(plan)
        if reason == "queued":
            self._typing_start_frames = (self._link.written_frames
                                         if self._link is not None else 0)
            self._typing_chars = len(plan.strokes)
            log.info("typing %d characters into the target", len(plan.strokes))
            if plan.skipped:
                log.info("%d characters cannot be typed in this layout, and were "
                         "left out", plan.skipped)
            if plan.truncated:
                log.info("%d characters past the limit were not typed",
                         plan.truncated)
        elif reason == "busy":
            log.info("not typing: the previous text is still going out")
        elif reason == "keys_held":
            log.info("not typing: keys are held, so the report would let go of them")
        else:
            log.debug("typing refused: %s", reason)

    def _on_note(self, note: str) -> None:
        pointer = self.router.pointer_report()
        if note == "enter_target":
            log.info("the target has the keyboard and mouse")
            log.debug("enter target mode, pointer at %.1f%%, %.1f%%",
                      self.router.pointer_x * 100, self.router.pointer_y * 100)
        elif note.startswith("leave_target"):
            reason = note.partition(":")[2]
            # These are the values the return rule decided on. They cannot say
            # where the target put its own pointer: the reports are relative and
            # the target scales them. The pointer trace is what shows whether
            # the two agree.
            # Said the way a user reads it; the numbers are what the return rule
            # decided on, and they belong on the debug line under it. They cannot
            # say where the target put its own pointer: the reports are relative
            # and the target scales them.
            log.info("the PC has the keyboard and mouse again")
            log.debug("leave target mode (%s) at pointer %.1f%%, %.1f%% "
                      "(travel %.1f%%)",
                      reason, self.router.pointer_x * 100,
                      self.router.pointer_y * 100, pointer["travel"] * 100)
        elif note.startswith("handoff_refused"):
            reason = note.partition(":")[2]
            # Pressing against the edge while the target is not connected is
            # normal — it is what waiting for the target looks like — so say it
            # once and then go quiet. Repeating it every attempt buries
            # everything else in the log.
            if reason != self._refused_reason:
                self._refused_reason = reason
                log.warning("%s", _refusal_explained(reason))
        elif note.startswith("paused"):
            log.debug("bridge paused by hand, the PC has the keyboard and mouse")
        elif note.startswith("resumed"):
            log.debug("bridge resumed")
        elif note == "type_requested":
            self._typing_planned = keystrokes.plan(win32.read_clipboard_text())
        elif note == "typing_cancelled":
            # The queue was dropped because a key was pressed: say so once, so a
            # paste that stopped halfway has an explanation in the log.
            log.info("typing stopped: the keyboard was used")
