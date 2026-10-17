"""Saying what went wrong once, instead of saying nothing or shouting.

The peripheral talks to WinRT callbacks, the window to a service that may be
unavailable, and the tray to Windows messages. All three sit where an exception
has nowhere useful to go: it cannot be raised at the user, and it cannot stop the
copy that is already running. The usual answer -- ``except Exception:
log.debug(...)`` -- hides real faults at a level nobody reads, which cost this
project a whole round: a ``TypeError`` per keystroke, invisible, presenting as a
link that connects and does nothing.

:func:`swallow` keeps the resilience and gives the first failure a voice: one
warning per distinct operation, then debug, so a fault that repeats per keystroke
does not drown the log either.
"""

from __future__ import annotations

import contextlib
import logging

log = logging.getLogger("winborder.diagnostics")

#: Operations that have already been reported. Keyed by the words the caller gave
#: :func:`swallow`, so the same operation is announced once however often it runs.
_reported: set[str] = set()


@contextlib.contextmanager
def swallow(what: str):
    """Let an exception go, but say what failed the first time it does.

    ``what`` names the operation, not the exception: "notifying a report",
    "answering a read". The same words always describe the same operation, which
    is what the "already reported" set keys on.
    """
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - the point is to keep running
        failed(what, exc)


def failed(what: str, exc: BaseException) -> None:
    """Report an exception that was caught on purpose, once per operation.

    For code that already has its own ``try``/``finally`` and only needs the
    reporting half, which is most of it.
    """
    if what in _reported:
        log.debug("%s failed again: %s", what, exc, exc_info=True)
    else:
        _reported.add(what)
        log.warning("%s failed: %s: %s", what, type(exc).__name__, exc,
                    exc_info=True)


def forget() -> None:
    """Report every operation again.

    Used by a test, and by anything that would rather the next failure be news.
    """
    _reported.clear()
