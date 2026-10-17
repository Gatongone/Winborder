"""Output effects: device sink, cursor confinement and PC-side restoration."""

from __future__ import annotations

import logging
from typing import Protocol

from . import diagnostics, model, win32
from .input import InputEngine

log = logging.getLogger("winborder.output")


class FrameSink(Protocol):
    def send(self, kind: str, payload: bytes) -> bool:
        ...


class EffectSink:
    """Applies model effects to the device link and to the Windows session.

    The router never touches the link or the cursor directly; it returns
    effects and this class performs them. That keeps the routing rules free
    of I/O and therefore directly testable.
    """

    def __init__(self, frames: FrameSink, engine: InputEngine) -> None:
        self._frames = frames
        self._engine = engine
        self.sent_frames = 0
        self.failed_frames = 0
        self.clip_active = False

    def apply(self, effects: list[model.Effect]) -> list[str]:
        notes: list[str] = []
        for effect in effects:
            if isinstance(effect, model.SendFrame):
                if self._frames.send(effect.kind, effect.payload):
                    self.sent_frames += 1
                else:
                    self.failed_frames += 1
            elif isinstance(effect, model.ClipCursor):
                self._engine.clip_to_edge(effect.side.value)
                self.clip_active = True
            elif isinstance(effect, model.ReleaseCursor):
                self._engine.release_clip()
                self.clip_active = False
            elif isinstance(effect, model.PlaceCursor):
                self._place(effect)
            elif isinstance(effect, model.CaptureInput):
                self._engine.suppress_keyboard = effect.keyboard
                self._engine.suppress_mouse = effect.mouse
            elif isinstance(effect, model.Notify):
                notes.append(effect.event)
        return notes

    def _place(self, effect: model.PlaceCursor) -> None:
        """Move the cursor to the mapped edge point, then inset it.

        The inset prevents the next frame from immediately satisfying the edge
        trigger again, which would produce a rapid enter/leave loop.
        """
        x, y = effect.x, effect.y
        left, top, right, bottom = win32.primary_screen_rect()
        clear = max(1, effect.move_inside)
        if effect.side is model.Side.RIGHT:
            x = max(left, right - 1 - clear)
        elif effect.side is model.Side.LEFT:
            x = min(right - 1, left + clear)
        elif effect.side is model.Side.TOP:
            y = min(bottom - 1, top + clear)
        else:
            y = max(top, bottom - 1 - clear)
        win32.set_cursor_pos(x, y)

    def release_all(self) -> None:
        """Undo every PC-side effect. Safe to call in any state."""
        try:
            self._engine.release_clip()
        except Exception as exc:  # noqa: BLE001 - shutdown has to finish
            diagnostics.failed("releasing the cursor confinement", exc)
        self.clip_active = False
        self._engine.suppress_keyboard = False
        self._engine.suppress_mouse = False
