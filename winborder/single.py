"""One running copy, and a second launch hands over to it.

Two instances would both try to own the HID service, and the second one would
advertise an address that nothing is bonded to: the target then shows a device
that cannot connect, which is the hardest kind of fault to read from the outside.
So a second launch is not an error and not a second bridge -- it is a request to
show the window that is already open, which is also how a user whose window is in
the notification area asks for it back.

The lock is a named mutex in the session's namespace, so two users signed in at
the same time can each run their own copy.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from . import win32

log = logging.getLogger("winborder.single")

#: Per session: two users on one machine each get their own.
MUTEX_NAME = "WinborderHostWindow-1"
ERROR_ALREADY_EXISTS = 183
WINDOW_TITLE = "Winborder"

_handle = None
_owned = False


def acquire(name: str = MUTEX_NAME) -> bool:
    """Claim the one-instance lock.

    Returns False when another process already holds it. If the lock cannot be
    created at all, this says True: running twice is a worse state than running
    once, but refusing to start is not a state at all.
    """
    global _handle, _owned
    if _owned:
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
    except OSError:
        log.debug("no one-instance lock; running anyway", exc_info=True)
        return True
    _handle = handle
    _owned = True
    return True


def release() -> None:
    """Give the lock up, so the next launch starts a new copy.

    The host never calls this: it holds the lock until the process ends, which is
    exactly the lifetime the lock is about. A test has to be able to hand it back,
    because a test process outlives the case it is testing.
    """
    global _handle, _owned
    if _handle is not None:
        try:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(_handle)
        except OSError:
            log.debug("cannot close the one-instance handle", exc_info=True)
    _handle = None
    _owned = False


def focus_existing(title: str = WINDOW_TITLE) -> bool:
    """Bring the window of the running copy to the front, if it can be found."""
    return win32.focus_window(title)
