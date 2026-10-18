"""Settings Windows owns rather than the bridge: startup, and where things live.

Kept apart from :mod:`winborder.config` so the routing settings stay a pure
description of how the bridge behaves.
"""

from __future__ import annotations

import logging
import os
import sys
import winreg
from pathlib import Path

log = logging.getLogger("winborder.startup")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Winborder"

# Stored in the settings file beside the routing settings, but not part of them.
APP_FIELDS = ("start_with_windows", "start_hidden")

DEFAULTS = {"start_with_windows": False, "start_hidden": False}


def is_frozen() -> bool:
    """True when running from a built executable rather than from Python."""
    return bool(getattr(sys, "frozen", False))


def launch_command(config_path: str) -> str:
    """The command Windows should run to start the host as it is running now."""
    config = Path(config_path).resolve()
    if is_frozen():
        parts = [f'"{Path(sys.executable)}"']
    else:
        # pythonw keeps a console window from appearing at logon.
        python = Path(sys.executable)
        windowless = python.with_name("pythonw.exe")
        parts = [f'"{windowless if windowless.exists() else python}"',
                 "-m", "winborder"]
    parts.append(f'--config "{config}"')
    return " ".join(parts)


def is_enabled() -> bool:
    """True when the host is registered to start with Windows."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
    except OSError:
        return False
    return bool(value)


def apply(start_with_windows: bool, config_path: str) -> bool:
    """Add or remove the start with Windows entry. False when it did not work.

    The whole footprint is one value: ``Winborder`` under the per-user Run key,
    holding the command line above. Nothing else is written, and turning the
    setting off deletes that one value again.

    Only the built executable is registered. A command line of
    ``pythonw -m winborder`` points at whichever interpreter happened to be
    running, which stops working as soon as that Python moves -- and an entry
    under Run is exactly what an antivirus is watching for, so it had better be
    one that will still be there at the next logon.
    """
    if start_with_windows and not is_frozen():
        log.warning("start with Windows needs the built executable, not a "
                    "Python interpreter")
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if start_with_windows:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ,
                                  launch_command(config_path))
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        log.warning("cannot change the startup entry: %s", exc)
        return False
    return True


def describe() -> dict[str, str]:
    """What is running, for the About card.

    The settings file is not here: the window knows which one it was given, and
    that is the one worth showing.
    """
    return {
        "version": _version(),
        "runtime": "value_executable" if is_frozen() else f"Python {sys.version.split()[0]}",
    }


def _version() -> str:
    from . import __version__
    return __version__



    """Show a folder in Explorer."""
    folder = Path(path).resolve()
    os.startfile(folder)  # noqa: S606 - a folder the user asked to see
