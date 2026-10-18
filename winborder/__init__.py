"""Winborder — share a PC keyboard and mouse with another device over BLE HID.

The PC owns edge detection, input capture and cursor confinement, and
publishes itself as the Bluetooth LE peripheral the target connects to. The
target sees a standard Bluetooth keyboard and mouse and installs nothing.
"""

from __future__ import annotations

__version__ = "0.2.0"

# Who made it and under what terms. The About card shows these, so they live
# beside the version rather than being typed into the window.
__author__ = "Gatongone"
__repository__ = "https://github.com/Gatongone/Winborder"
__license__ = "MIT"

__all__ = ["__author__", "__license__", "__repository__", "__version__"]
