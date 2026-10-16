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
        self._lines: deque[str] = deque(maxlen=capacity)
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
            self._lines.append(line)

    def snapshot(self, since: int) -> tuple[list[str], int]:
        """Return the lines after a previous total count, and that count.

        The total only grows, so a reader can poll with the value it was given
        last time and receive each line exactly once.
        """
        with self._lock:
            total = self._dropped + len(self._lines)
            first = total - len(self._lines)
            if since < first:
                since = first
            return list(self._lines)[since - first:], total

    def text(self) -> str:
        with self._lock:
            return "\n".join(self._lines)
