"""In-memory log, so the settings window can show what the host is doing."""

from __future__ import annotations

import logging
import threading
from collections import deque

FORMAT = "%(asctime)s %(levelname)-7s %(name)-14s %(message)s"
DATE_FORMAT = "%H:%M:%S"


class LogBuffer(logging.Handler):
    """Keeps the most recent formatted records for a reader thread."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(logging.Formatter(FORMAT, datefmt=DATE_FORMAT))
        self._lines: deque[tuple[int, str]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # noqa: BLE001 - logging must never break the host
            return
        with self._lock:
            if len(self._lines) == self._lines.maxlen:
                self._dropped += 1
            self._lines.append((record.levelno, line))

    def snapshot(self, since: int,
                 level: int = logging.DEBUG) -> tuple[list[str], int]:
        """Return the lines after a previous total count, and that count.

        The total only grows, so a reader can poll with the value it was given
        last time and receive each line exactly once. ``level`` filters what is
        handed out without disturbing that count: the window asks for what the
        user can act on, while the console sees everything.
        """
        with self._lock:
            total = self._dropped + len(self._lines)
            first = total - len(self._lines)
            if since < first:
                since = first
            recent = list(self._lines)[since - first:]
        return [line for levelno, line in recent if levelno >= level], total

    def text(self, level: int = logging.DEBUG) -> str:
        with self._lock:
            lines = list(self._lines)
        return "\n".join(line for levelno, line in lines if levelno >= level)
