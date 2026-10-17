"""List the Bluetooth LE devices around this PC.

This is a diagnostic, and worth being clear about what it cannot do: it does not
connect to anything. In Bluetooth LE a connection is always opened by the
central, and in HID over GATT the central is the *target* — the iPad is the HID
host and this PC is the HID device. A device that hosts the HID service can only
advertise and wait, so the target has to make the connection from its own
Bluetooth settings.

What the list is good for is answering the first question that comes up when a
target will not connect: is the target actually nearby and advertising. It never
answers "which of these is this PC", because a radio does not hear itself -- the
window says so next to the list, and the Device Information Service is what names
the PC to the target.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass

from .concurrency import LoopThread, StartupFailed

log = logging.getLogger("winborder.scan")


class ScanUnavailable(Exception):
    """Raised when the radio cannot scan."""


@dataclass(frozen=True)
class Seen:
    """One device, as the latest advertisement described it."""

    address: str
    name: str
    rssi: int
    services: tuple[str, ...]


def _load_winrt():
    try:
        from winrt.windows.devices.bluetooth import BluetoothAdapter
        from winrt.windows.devices.bluetooth.advertisement import (
            BluetoothLEAdvertisementWatcher,
            BluetoothLEScanningMode,
        )
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ScanUnavailable(
            "the WinRT projections are missing: pip install winrt-runtime "
            "winrt-Windows.Devices.Bluetooth "
            "winrt-Windows.Devices.Bluetooth.Advertisement"
        ) from exc
    return BluetoothAdapter, BluetoothLEAdvertisementWatcher, BluetoothLEScanningMode


def _short(uuid: str) -> str:
    """A 16 bit UUID in the four hex digits people recognise, else the whole thing."""
    text = str(uuid).upper()
    if text.startswith("0000") and text.endswith("-0000-1000-8000-00805F9B34FB"):
        return text[4:8]
    return text


class DeviceScanner:
    """A background advertisement scan, readable from any thread.

    The watcher is created on a thread of its own that keeps an event loop
    running, for the same reason the peripheral does: the WinRT objects are
    apartment-bound, and callers must not have to know that.
    """

    def __init__(self) -> None:
        # Nothing is loaded here: constructing the scanner must not be able to
        # fail, because the window holds one whether or not it is ever used.
        self._adapter = None
        self._devices: dict[str, Seen] = {}
        self._lock = threading.Lock()
        self._watcher = None
        self._thread: LoopThread | None = None

    # ---------------------------------------------------------------- lifecycle

    def start(self, wait: float = 8.0) -> None:
        if self._thread is not None:
            return
        if self._adapter is None:
            self._adapter = _load_winrt()
        thread = LoopThread("winborder-scan", self._start_watcher)
        try:
            thread.start(wait)
        except StartupFailed as exc:
            raise ScanUnavailable(str(exc)) from None
        self._thread = thread

    async def _start_watcher(self) -> None:
        BluetoothAdapter, BluetoothLEAdvertisementWatcher, BluetoothLEScanningMode = \
            self._adapter
        adapter = await BluetoothAdapter.get_default_async()
        if adapter is None:
            raise ScanUnavailable("no Bluetooth LE radio")
        if not adapter.is_central_role_supported:
            raise ScanUnavailable("the radio cannot scan for devices")

        self._watcher = BluetoothLEAdvertisementWatcher()
        self._watcher.scanning_mode = BluetoothLEScanningMode.ACTIVE
        # The projection names the event accessor, not the event: this is the
        # Python binding's shape, and `received += handler` does not exist on it.
        self._watcher.add_received(self._on_advertisement)
        self._watcher.start()
        log.info("scanning for nearby Bluetooth LE devices")

    def _on_advertisement(self, _sender, args) -> None:
        try:
            address = f"{args.bluetooth_address:012X}"
            advertisement = args.advertisement
            name = advertisement.local_name or ""
            services = tuple(_short(uuid) for uuid in advertisement.service_uuids)
            rssi = int(args.raw_signal_strength_in_dbm)
        except Exception:
            log.debug("unreadable advertisement", exc_info=True)
            return

        with self._lock:
            previous = self._devices.get(address)
            # A name arrives in one packet and the service list in another, so
            # merge rather than replace: whatever this advertisement did not
            # carry is still true of the device.
            self._devices[address] = Seen(
                address=address,
                name=name or (previous.name if previous else ""),
                rssi=rssi,
                services=services or (previous.services if previous else ()),
            )

    def stop(self) -> None:
        watcher, self._watcher = self._watcher, None
        if watcher is not None:
            try:
                watcher.stop()
            except Exception:
                log.debug("stopping the watcher failed", exc_info=True)
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.stop()

    # ------------------------------------------------------------------ reading

    def snapshot(self, limit: int = 40) -> list[Seen]:
        """The devices seen so far, strongest first."""
        with self._lock:
            devices = list(self._devices.values())
        devices.sort(key=lambda seen: (-seen.rssi, seen.name or seen.address))
        return devices[:limit]

    def clear(self) -> None:
        with self._lock:
            self._devices.clear()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.running

    def __enter__(self) -> "DeviceScanner":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
