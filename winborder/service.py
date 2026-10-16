"""Service orchestration: wires the input, process and output stages together.

Responsibilities are limited to lifecycle and data flow. All routing rules
live in :mod:`winborder.model` and all device I/O lives in :mod:`winborder.link`.
"""

from __future__ import annotations

import logging
import threading
import time

from . import ipc, model, win32
from .input import InputEngine
from .link import LinkError, SerialLink
from .output import EffectSink

log = logging.getLogger("winborder.service")

TICK_INTERVAL_S = 1.0 / 250.0
SCREEN_REFRESH_TICKS = 250
RECONNECT_INTERVAL_S = 2.0


def _unit(value: float) -> float:
    """Clamp a fraction to the [0, 1] range used by the trace."""
    return min(1.0, max(0.0, value))


class Service:
    """Runs the bridge until stopped."""

    def __init__(self, port: str, config: model.Config | None = None,
                 baudrate: int = ipc.DEFAULT_BAUDRATE) -> None:
        self.cfg = config or model.Config()
        self.port = port
        self.baudrate = baudrate

        self.engine = InputEngine()
        self.router = model.Router(
            config=self.cfg,
            screen=self._screen_size(),
            handoff_allowed=self._handoff_allowed,
        )
        self._link: SerialLink | None = None
        self._sink: EffectSink | None = None
        self._stop = threading.Event()
        self._ticks = 0
        self._last_written = 0
        self._link_failed = False
        self._pause_wanted = False
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
        log.info("bridge running, target side=%s", self.cfg.side.value)
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
        try:
            self._link = SerialLink(self.port, self.baudrate)
        except LinkError as exc:
            if not self._link_failed:
                log.warning("link unavailable on %s: %s", self.port, exc)
                self._link_failed = True
            self._link = None
            return
        if self._link_failed:
            log.info("link restored on %s", self.port)
        self._link_failed = False
        self._sink = EffectSink(_LinkAdapter(self._link), self.engine)
        self._sink.apply(self.router.reset_device_state())

    def _ensure_link(self) -> None:
        if self._link is not None and self._link.is_open:
            return
        if self._link is not None:
            log.warning("link lost on %s, reconnecting", self.port)
            if self._sink is not None:
                self._sink.apply(
                    self.router.leave_target("link_lost", time.monotonic()))
            self._link = None
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
        self._ensure_link()
        link = self._link
        if link is None or self._sink is None:
            time.sleep(RECONNECT_INTERVAL_S)
            return

        # Link health is judged by frames the writer thread actually put on the
        # wire, not by how many the router produced. Frames are queued, so a
        # successful enqueue says nothing about delivery.
        if link.written_frames != self._last_written:
            self._last_written = link.written_frames
            self.router.note_link_ok(now)

        self._drain_device_frames(link)

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

    def _apply_pause(self, now: float) -> None:
        """Carry out a pause or a resume that was asked for by another thread."""
        if self._pause_wanted == self.router.paused:
            return
        effects = self.router.set_paused(self._pause_wanted, now)
        if self._sink is not None:
            for note in self._sink.apply(effects):
                self._on_note(note)
        log.info("bridge %s", "paused" if self._pause_wanted else "resumed")

    def _drain_device_frames(self, link: SerialLink) -> None:
        for msg_type, payload in link.poll():
            try:
                if msg_type == ipc.DevMsgType.LOG:
                    log.debug("device: %s", ipc.decode_log(payload))
                elif msg_type == ipc.DevMsgType.VERSION:
                    major, minor, patch = ipc.decode_version(payload)
                    log.info("firmware %d.%d.%d", major, minor, patch)
                elif msg_type == ipc.DevMsgType.NAK:
                    _, reason = ipc.decode_nak(payload)
                    log.warning("device rejected a frame: %s", reason)
                elif msg_type == ipc.DevMsgType.SWITCH_BACK:
                    reason = ipc.decode_switch_back(payload)
                    self._sink.apply(
                        self.router.leave_target(f"device:{reason}", time.monotonic()))
            except ValueError as exc:
                log.debug("malformed device frame: %s", exc)

    def _on_note(self, note: str) -> None:
        pointer = self.router.pointer_report()
        if note == "enter_target":
            log.info("enter target mode, pointer at %.1f%%, %.1f%%",
                     self.router.pointer_x * 100, self.router.pointer_y * 100)
        elif note.startswith("leave_target"):
            reason = note.partition(":")[2]
            # These are the values the return rule decided on. They cannot say
            # where the target put its own pointer: the reports are relative and
            # the target scales them. The pointer trace is what shows whether
            # the two agree.
            log.info("leave target mode (%s) at pointer %.1f%%, %.1f%% "
                     "(travel %.1f%%)",
                     reason, self.router.pointer_x * 100, self.router.pointer_y * 100,
                     pointer["travel"] * 100)
        elif note.startswith("handoff_refused"):
            log.error("input capture refused: %s", note.partition(":")[2])
        elif note.startswith("paused"):
            log.info("bridge paused by hand, the PC has the keyboard and mouse")
        elif note.startswith("resumed"):
            log.info("bridge resumed")


class _LinkAdapter:
    """Adapts SerialLink to the frame sink protocol."""

    def __init__(self, link: SerialLink) -> None:
        self._link = link

    def send(self, msg_type: int, payload: bytes) -> bool:
        try:
            return self._link.submit(ipc.encode_frame(msg_type, payload))
        except ValueError:
            log.debug("dropped oversized frame type=0x%02X", msg_type)
            return False
