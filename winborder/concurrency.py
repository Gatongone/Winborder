"""One asyncio loop on a thread of its own, for the objects that need one.

The WinRT objects this program uses are apartment bound: a GATT service provider
or an advertisement watcher belongs to the thread that created it, and touching it
from anywhere else fails in ways that look like the feature not working. Both the
peripheral and the scanner therefore keep a loop on a thread of their own, and both
used to spell that out in full -- thread, ``asyncio.set_event_loop``, a ready event,
an error handshake, a join in ``stop``. This is that pattern once.

``setup`` runs on the new loop and may fail; whatever it raises is handed back to
the caller of :meth:`LoopThread.start` as :class:`StartupFailed`, so a caller can
say why it could not start in its own words.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Callable

log = logging.getLogger("winborder.concurrency")

#: How long the loop is given to run ``setup`` before ``start`` gives up.
DEFAULT_WAIT_S = 10.0


class StartupFailed(Exception):
    """The loop thread did not get as far as running its setup."""


class LoopThread:
    """An asyncio loop on a daemon thread, stopped from any other thread."""

    def __init__(self, name: str, setup: Callable[[], Awaitable[None]],
                 stop_when: threading.Event | None = None) -> None:
        self.name = name
        self._setup = setup
        self._stop_when = stop_when
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: str | None = None

    # ---------------------------------------------------------------- lifecycle

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The loop, once it is running; None before the start and after the stop."""
        return self._loop

    def start(self, wait: float = DEFAULT_WAIT_S) -> asyncio.AbstractEventLoop:
        """Run the setup on a new loop and return it. Raises StartupFailed."""
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._error = None
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name=self.name,
                                        daemon=True)
        self._thread.start()
        if not self._ready.wait(wait):
            raise StartupFailed("the loop did not start in time")
        if self._error:
            raise StartupFailed(self._error)
        return loop

    def _run(self) -> None:
        loop = self._loop
        assert loop is not None
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._setup())
        except Exception as exc:  # noqa: BLE001 - the reason travels to start()
            self._error = f"{type(exc).__name__}: {exc}"
            self._ready.set()
            loop.close()
            return
        self._ready.set()

        stop = self._stop_when
        if stop is not None:
            # Poll in the loop: the event belongs to another thread, and asyncio
            # has no portable way to await one.
            async def watch() -> None:
                while not stop.is_set():
                    await asyncio.sleep(0.1)
                loop.stop()

            loop.create_task(watch())
        try:
            loop.run_forever()
        finally:
            loop.close()

    def stop(self) -> None:
        """Stop the loop and wait for the thread. Safe to call more than once."""
        loop, self._loop = self._loop, None
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                log.debug("the loop was already stopping", exc_info=True)
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=3.0)

    @property
    def running(self) -> bool:
        return self._thread is not None

    def call_soon_threadsafe(self, callback: Callable[..., None], *args) -> bool:
        """Queue work on the loop; False when it is no longer there."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return False
        try:
            loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            log.debug("the loop was already closed", exc_info=True)
            return False
        return True
