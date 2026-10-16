"""Winborder — share a PC keyboard and mouse with another device over BLE HID.

The host owns edge detection, input capture, cursor confinement and the
serial protocol. The target sees a standard Bluetooth keyboard and mouse
provided by the firmware in ``firmware/ble_bridge``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
