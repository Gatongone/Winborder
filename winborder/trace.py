"""Status snapshots rendered as one line.

The console and the settings window show the same line, so the formatting lives
here rather than in either of them.

The trace carries the values the return rule decides on: the PC cursor, the
tracked pointer and the travel since the target was entered. Those numbers are
what a return has to be explained from, since the reports the host sends are
relative and the target may place its own pointer anywhere.
"""

from __future__ import annotations

from . import model


class StatusFormatter:
    """Renders a snapshot, skipping repeats while the target is active."""

    def __init__(self) -> None:
        self._previous: tuple[float, float] | None = None

    def line(self, state: dict[str, object]) -> str | None:
        """Return the line for this snapshot, or None when nothing changed."""
        cursor = state["cursor"]
        pointer = state["pointer"]
        previous = self._previous
        self._previous = pointer
        if state["mode"] == model.Mode.TARGET.value:
            if pointer == previous:
                return None
            return self._target_line(state, cursor, pointer, previous)
        return self._pc_line(state, cursor)

    @staticmethod
    def _target_line(state: dict[str, object], cursor, pointer,
                     previous: tuple[float, float] | None) -> str:
        step = "" if previous is None else " d=({:+.3f},{:+.3f})".format(
            pointer[0] - previous[0], pointer[1] - previous[1])
        return (
            "[target] cursor=({cx:.3f},{cy:.3f}) pointer=({px:.3f},{py:.3f})"
            " travel={travel:+.1f}%{d}"
        ).format(cx=cursor[0], cy=cursor[1], px=pointer[0], py=pointer[1],
                 travel=state["travel"] * 100, d=step)

    @staticmethod
    def _pc_line(state: dict[str, object], cursor) -> str:
        return (
            "[pc] cursor=({cx:.3f},{cy:.3f}) written={written} bad={bad}"
        ).format(cx=cursor[0], cy=cursor[1], written=state["written"],
                 bad=state["bad"])
