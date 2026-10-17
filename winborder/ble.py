"""Windows BLE HID peripheral: advertise and drive a keyboard/mouse over GATT.

This is the whole device side of Winborder. The PC registers a HID peripheral on
its own Bluetooth adapter and the target pairs with that:

    HID service (0x1812)
      Report Map         0x2A4B  read         HID_REPORT_MAP
      HID Information    0x2A4A  read         bcdHID 1.11, remote wake
      Report (kbd)       0x2A4D  read+notify  Report Reference 1, input
      Report (mouse)     0x2A4D  read+notify  Report Reference 2, input
      Report (consumer)  0x2A4D  read+notify  Report Reference 3, input
      Report (LEDs)      0x2A4D  read+write   Report Reference 1, output
      Protocol Mode      0x2A4E  read+write-no-response
      HID Control Point  0x2A4C  write-no-response
    Device Information (0x180A)
      Manufacturer Name  0x2A29, PnP ID 0x2A50
    Battery (0x180F)
      Battery Level      0x2A19

Two things the Windows stack does not allow, and which no application code can
work around:

``Appearance``
    A dedicated keyboard advertises 0x03C2 (HID Mouse). ``GattServiceProviderAdvertisingParameters``
    has no appearance field, and the one API that can put arbitrary bytes into an
    advertisement, ``BluetoothLEAdvertisementPublisher``, refuses to start on a
    normal Windows desktop (every payload shape returns E_INVALIDARG). A central
    therefore sees no appearance value. The HID service UUID and the local name
    still reach the air, which is what a HID central matches on.

``Local name``
    The advertised name is the Bluetooth adapter's own name, not a per-service
    string. Set "Winborder" in Windows Settings > Bluetooth before advertising.

``GattLocalCharacteristic`` publishes its CCCD itself; creating 0x2902 by hand
is rejected as a reserved descriptor.

Two further traps, both of which present as a target that connects but types
nothing, are documented where they bite: the byte budget of each report in
:data:`HID_REPORT_MAP`, and ``start_advertising_with_parameters`` below.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from typing import Callable

from . import diagnostics, hid
from .concurrency import LoopThread, StartupFailed
from .gatt import (
    HID_INFORMATION,
    HID_REPORT_MAP,
    MANUFACTURER,
    PROTECTED_UUIDS,
    REPORT_ID_CONSUMER,
    REPORT_ID_KEYBOARD,
    REPORT_ID_MOUSE,
    UUID_BATTERY_LEVEL,
    UUID_BATTERY_SERVICE,
    UUID_DIS_SERVICE,
    UUID_HID_CONTROL,
    UUID_HID_INFO,
    UUID_HID_SERVICE,
    UUID_MANUFACTURER_NAME,
    UUID_PNP_ID,
    UUID_PROTOCOL_MODE,
    UUID_REPORT,
    UUID_REPORT_MAP,
    UUID_REPORT_REFERENCE,
    is_protected,
)

log = logging.getLogger("winborder.ble")

#: How long a cached advertisement status is trusted before it is re-read.
STATUS_REFRESH_S = 1.0


# ==========================================================================
# WinRT access
# ==========================================================================


class BleUnavailable(Exception):
    """Raised when the Windows BLE peripheral APIs cannot be used."""


def _load_winrt():
    """Import the WinRT projections, raising BleUnavailable with the reason."""
    try:
        from winrt.windows.devices.bluetooth import BluetoothAdapter
        from winrt.windows.devices.bluetooth.genericattributeprofile import (
            GattCharacteristicProperties,
            GattLocalCharacteristicParameters,
            GattLocalDescriptorParameters,
            GattProtectionLevel,
            GattServiceProvider,
            GattServiceProviderAdvertisingParameters,
        )
        from winrt.windows.foundation import Deferral
        from winrt.windows.storage.streams import DataWriter
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise BleUnavailable(
            "the WinRT projections are missing: pip install winrt-runtime "
            "winrt-Windows.Devices.Bluetooth winrt-Windows.Devices.Bluetooth."
            "GenericAttributeProfile winrt-Windows.Storage.Streams "
            "winrt-Windows.Foundation"
        ) from exc

    return {
        "BluetoothAdapter": BluetoothAdapter,
        "GattServiceProvider": GattServiceProvider,
        "GattServiceProviderAdvertisingParameters": GattServiceProviderAdvertisingParameters,
        "GattLocalCharacteristicParameters": GattLocalCharacteristicParameters,
        "GattLocalDescriptorParameters": GattLocalDescriptorParameters,
        "GattCharacteristicProperties": GattCharacteristicProperties,
        "GattProtectionLevel": GattProtectionLevel,
        "Deferral": Deferral,
        "DataWriter": DataWriter,
    }


def _uuid(value) -> uuid.UUID:
    """The WinRT projections require a real UUID object, not a string."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _status_code(error) -> int:
    """Numeric status of a WinRT result.

    The projections hand back an IntEnum for these fields, so ``int()`` is the
    reliable way to test for success; comparing the rendered string is not, and
    silently treats a success as a failure.
    """
    try:
        return int(error)
    except (TypeError, ValueError):
        return 0 if str(error) == "0" else -1


async def _deliver(characteristic, buffer):
    """Await one notification and report what the target said.

    The projection's ``notify_value_async`` returns an ``IAsyncOperation``: it is
    awaitable, but it is **not** a coroutine, and ``run_coroutine_threadsafe``
    only takes coroutines. Handing the operation straight in raised "A coroutine
    object is required" for every single report, one line per keystroke, and the
    broad ``except`` in the sender logged it at debug level -- so the visible
    symptom was a link that connected, subscribed and never typed anything.
    """
    return await characteristic.notify_value_async(buffer)


def report_value(payload: bytes) -> bytes:
    """The bytes a Report characteristic carries: the report itself, nothing else.

    The host learns which report this is from the Report Reference descriptor
    (0x2908), not from a leading identifier octet. Prefixing the report id
    shifted every field by one octet on the host, and the symptom was measured on
    an iPad:

        pushing the mouse right moved the target pointer *down*
        pushing it up or down moved nothing (that octet had become the wheel)
        the keyboard arrived with its modifier byte in the first key slot

    A mapping that is wrong by one field looks like a bug on every axis at once,
    which is why it gets blamed on the encoder instead of on this byte.
    """
    return bytes(payload)


def _delivered(results) -> bool:
    """Whether a notification reached a client and none of them refused it.

    The awaited value is one ``GattClientNotificationResult`` **per subscribed
    client**, not a single status. The sender used to compare that vector against
    SUCCESS, which is never equal: every delivered report was counted as a
    failure, so the link looked dead while the target was receiving it.
    """
    delivered = False
    for result in results:
        if _status_code(getattr(result, "status", None)) != 0:
            return False
        delivered = True
    return delivered


def _status_name(status) -> str:
    """An advertisement status as lower case words.

    The projections hand back an IntEnum, and ``str()`` of one is its number on
    Python 3.11 — ``"2"``, which says nothing to whoever reads it in the window.
    The name is the part that carries the meaning.
    """
    name = getattr(status, "name", None)
    return (name if name else str(status)).lower().replace("_", " ")


class BleHidPeripheral:
    """A BLE HID keyboard and mouse built on the Windows GATT server.

    The GATT server is created on a dedicated asyncio loop thread, because the
    WinRT calls are awaitable and the caller (the Winborder service) is not
    asynchronous. Every public method is safe to call from another thread.
    """

    def __init__(self, *, on_event: Callable[[str, str], None] | None = None) -> None:
        self._on_event = on_event
        self._api = _load_winrt()
        self._thread: LoopThread | None = None

        self._services = []
        self._reports: dict[int, object] = {}
        self._subscribed: set[int] = set()
        self._sub_lock = threading.Lock()

        self._state_keyboard = (0, 0, 0, 0, 0, 0, 0, 0)   # modifier, k0..k6
        self._state_buttons = 0
        self._state_consumer = 0
        self._failed_reports = 0

        # The last advertisement status, kept as words rather than read back from
        # the provider: that property belongs to the loop's apartment, and the
        # window asks from its own thread. A string assignment is atomic.
        self._advertising = "not started"
        # False until the server has finished starting: Windows hands a new one
        # the subscribers that are already there, so a subscription seen before
        # then belongs to a link this process did not open.
        self._serving = False
        self._advertising_at = 0.0
        self._advertising_provider = None

        self.adapter_name = "?"

    # ---------------------------------------------------------------- lifecycle

    def start(self, wait: float = 10.0, stop_requested: threading.Event | None = None) -> None:
        """Create the GATT server and begin advertising. Raises on failure.

        ``stop_requested`` lets a caller own the lifetime: the loop ends when the
        event is set, which is what a test needs to shut the peripheral down
        without reaching into the loop from outside.
        """
        thread = LoopThread("winborder-ble", self._setup,
                            stop_when=stop_requested)
        # Assigned before the setup runs, because the setup wires the read and
        # write handlers and those capture the loop through this attribute: with
        # it set afterwards, every handler held None and the first read the target
        # made raised inside the callback.
        self._thread = thread
        try:
            thread.start(wait)
        except StartupFailed as exc:
            self._thread = None
            raise BleUnavailable(str(exc)) from None

    @property
    def _loop(self) -> asyncio.AbstractEventLoop | None:
        """The loop, while it lives: the WinRT objects are bound to it."""
        return self._thread.loop if self._thread is not None else None

    def _emit(self, kind: str, text: str) -> None:
        # Debug here, not info: the service repeats what matters to the user, and
        # two lines for one event is how a log stops being read.
        log.debug("%s: %s", kind, text)
        if self._on_event is not None:
            try:
                self._on_event(kind, text)
            except Exception as exc:  # noqa: BLE001 - the caller's bug
                diagnostics.failed("calling the event handler", exc)

    async def _setup(self) -> None:
        api = self._api
        BluetoothAdapter = api["BluetoothAdapter"]
        GattServiceProvider = api["GattServiceProvider"]
        GattServiceProviderAdvertisingParameters = api["GattServiceProviderAdvertisingParameters"]
        GattLocalCharacteristicParameters = api["GattLocalCharacteristicParameters"]
        GattLocalDescriptorParameters = api["GattLocalDescriptorParameters"]
        GattCharacteristicProperties = api["GattCharacteristicProperties"]
        GattProtectionLevel = api["GattProtectionLevel"]
        DataWriter = api["DataWriter"]

        adapter = await BluetoothAdapter.get_default_async()
        if adapter is None:
            raise BleUnavailable("no Bluetooth LE radio")
        if not adapter.is_peripheral_role_supported:
            raise BleUnavailable("the radio does not support the peripheral role")
        self.adapter_name = adapter.device_id or "?"

        def buffer(data: bytes):
            writer = DataWriter()
            writer.write_bytes(bytes(data))
            return writer.detach_buffer()

        def protection(uuid_value):
            """The level for one attribute: see PROTECTED_UUIDS."""
            return (GattProtectionLevel.ENCRYPTION_REQUIRED
                    if is_protected(uuid_value) else GattProtectionLevel.PLAIN)

        async def add_characteristic(service, uuid, properties, *, static=None,
                                     description=None):
            params = GattLocalCharacteristicParameters()
            params.characteristic_properties = properties
            params.read_protection_level = protection(uuid)
            params.write_protection_level = protection(uuid)
            if description:
                params.user_description = description
            if static is not None:
                params.static_value = buffer(static)
            result = await service.create_characteristic_async(_uuid(uuid), params)
            if _status_code(result.error) != 0:
                raise BleUnavailable(
                    f"characteristic {uuid} refused: {result.error}"
                )
            return result.characteristic

        async def add_report_reference(characteristic, report_id: int, report_type: int):
            """Attach Report Reference (0x2908): [report id][report type]."""
            params = GattLocalDescriptorParameters()
            params.read_protection_level = protection(UUID_REPORT_REFERENCE)
            params.write_protection_level = protection(UUID_REPORT_REFERENCE)
            params.static_value = buffer(bytes([report_id, report_type]))
            result = await characteristic.create_descriptor_async(_uuid(UUID_REPORT_REFERENCE), params)
            if _status_code(result.error) != 0:
                raise BleUnavailable(f"report reference refused: {result.error}")

        # ---------------------------------------------------------- HID service
        hid_result = await GattServiceProvider.create_async(_uuid(UUID_HID_SERVICE))
        if _status_code(hid_result.error) != 0:
            raise BleUnavailable(f"HID service refused: {hid_result.error}")
        hid = hid_result.service_provider
        self._services.append(hid)
        svc = hid.service

        report_map = await add_characteristic(
            svc, UUID_REPORT_MAP, GattCharacteristicProperties.READ,
            description="Report Map",
        )
        # Answered here rather than as a static value, so that a host reading it
        # leaves a line in the log. A static value is served by the stack, which
        # means a host that connects and reads the map leaves no trace at all --
        # and then "nothing happened" cannot be told apart from "no host ever
        # arrived", which is exactly the question a failed pairing asks.
        self._serve_read(report_map, "the report map", lambda: HID_REPORT_MAP)
        await add_characteristic(
            svc, UUID_HID_INFO, GattCharacteristicProperties.READ,
            static=HID_INFORMATION, description="HID Information",
        )
        await add_characteristic(
            svc, UUID_HID_CONTROL,
            GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE,
            description="HID Control Point",
        )
        await add_characteristic(
            svc, UUID_PROTOCOL_MODE,
            GattCharacteristicProperties.READ
            | GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE,
            static=bytes([0x01]), description="Protocol Mode",
        )

        # The three input reports. Report type 1 = input.
        for report_id, description in (
            (REPORT_ID_KEYBOARD, "Keyboard Report"),
            (REPORT_ID_MOUSE, "Mouse Report"),
            (REPORT_ID_CONSUMER, "Consumer Report"),
        ):
            characteristic = await add_characteristic(
                svc, UUID_REPORT,
                GattCharacteristicProperties.READ
                | GattCharacteristicProperties.NOTIFY,
                description=description,
            )
            await add_report_reference(characteristic, report_id, 1)
            self._reports[report_id] = characteristic
            self._wire_report_events(characteristic, report_id)

        # The LED output report the target writes back (report type 2 = output).
        led = await add_characteristic(
            svc, UUID_REPORT,
            GattCharacteristicProperties.READ
            | GattCharacteristicProperties.WRITE
            | GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE,
            description="LED Report",
        )
        await add_report_reference(led, REPORT_ID_KEYBOARD, 2)

        # ------------------------------------------- Device Information service
        dis_result = await GattServiceProvider.create_async(_uuid(UUID_DIS_SERVICE))
        if _status_code(dis_result.error) == 0:
            dis = dis_result.service_provider
            self._services.append(dis)
            await add_characteristic(
                dis.service, UUID_MANUFACTURER_NAME, GattCharacteristicProperties.READ,
                static=MANUFACTURER.encode("ascii"),
            )
            # PnP ID: vendor id source 0x02 (USB-IF), vendor 0x02E5, product
            # 0x0001, version 0x0100.
            await add_characteristic(
                dis.service, UUID_PNP_ID, GattCharacteristicProperties.READ,
                static=bytes([0x02, 0xE5, 0x02, 0x01, 0x00, 0x00, 0x01]),
            )

        # ------------------------------------------------------ Battery service
        battery_result = await GattServiceProvider.create_async(_uuid(UUID_BATTERY_SERVICE))
        if _status_code(battery_result.error) == 0:
            battery = battery_result.service_provider
            self._services.append(battery)
            await add_characteristic(
                battery.service, UUID_BATTERY_LEVEL, GattCharacteristicProperties.READ,
                static=bytes([100]), description="Battery Level",
            )

        # ------------------------------------------------------------ advertise
        params = GattServiceProviderAdvertisingParameters()
        params.is_connectable = True
        params.is_discoverable = True
        # The status is read on demand rather than from the status-changed event:
        # Windows reports ABORTED for a moment while it restarts the advertiser,
        # and a missed event left the cache saying "aborted" for good.
        self._advertising_provider = hid
        # The WinRT Python projection gives the zero-argument overload the
        # plain name and appends _with_parameters to the other one. Calling
        # start_advertising(params) therefore raises "Invalid parameter
        # count". C# overloads normally, so this only bites Python.
        hid.start_advertising_with_parameters(params)
        self._read_advertisement_status(hid)

        self._serving = True
        self._emit("started", "advertising HID service 0x1812")

    def _read_advertisement_status(self, provider) -> None:
        try:
            status = _status_name(provider.advertisement_status)
            previous, self._advertising = self._advertising, status
            self._advertising_at = time.monotonic()
        except Exception as exc:  # noqa: BLE001 - the status is a nicety
            diagnostics.failed("reading the advertisement status", exc)
            return
        if status != previous:
            # Worth a line of its own: an advertisement that Windows stopped is
            # not connectable, and from the target that is indistinguishable from
            # a PC that is switched off -- the row stays in its list and tapping
            # it fails. Windows aborts and restarts the advertiser on its own.
            self._emit("advertising", f"advertisement {status}")

    def refresh_advertising_status(self) -> None:
        """Queue a fresh read of the advertisement status on the loop's thread.

        Called from the thread that displays it. The read itself has to happen
        on the thread that created the provider, which is the loop thread.
        """
        provider, thread = self._advertising_provider, self._thread
        if provider is None or thread is None:
            return
        thread.call_soon_threadsafe(self._read_advertisement_status, provider)

    def _serve_read(self, characteristic, what: str, value: "Callable[[], bytes]") -> None:
        """Answer a read in application code, and say that it happened.

        Used for values that never change, which could equally be static: a
        static value is answered by the stack itself and leaves no trace, so a
        host that connects only to look at the descriptor would be invisible in
        the log.
        """
        api, loop = self._api, self._loop

        def read_requested(_sender, args):
            deferral = args.get_deferral()
            self._emit("read", f"a host read {what}")

            async def respond():
                try:
                    request = await args.get_request_async()
                    if request is not None:
                        writer = api["DataWriter"]()
                        writer.write_bytes(value())
                        request.respond_with_value(writer.detach_buffer())
                except Exception as exc:  # noqa: BLE001 - one read, not the link
                    diagnostics.failed("answering a read", exc)
                finally:
                    deferral.complete()

            loop.call_soon_threadsafe(lambda: loop.create_task(respond()))

        characteristic.add_read_requested(read_requested)

    def _wire_report_events(self, characteristic, report_id: int) -> None:
        api = self._api
        loop = self._loop

        def subscribed_changed(sender, _args):
            clients = list(sender.subscribed_clients)
            with self._sub_lock:
                if clients:
                    self._subscribed.add(report_id)
                else:
                    self._subscribed.discard(report_id)
                count = len(self._subscribed)
            if clients:
                if not self._serving:
                    # Worth a line: "connected" before this process put anything
                    # on the air is either another copy of the host sharing the
                    # service or a target that kept the link across a restart, and
                    # both change what the Device link row means.
                    self._emit("adopted", "a subscriber was already attached "
                                          "when the server started")
                self._emit("subscribed", f"report {report_id}, {count} of 3 subscribed")
            else:
                self._emit("unsubscribed", f"report {report_id}, {count} of 3 subscribed")

        def read_requested(sender, args):
            deferral = args.get_deferral()

            async def respond():
                try:
                    request = await args.get_request_async()
                    if request is not None:
                        if report_id == REPORT_ID_KEYBOARD:
                            value = bytes(self._state_keyboard)
                        elif report_id == REPORT_ID_MOUSE:
                            # A read answers with a report of the width the map
                            # declares, so this follows the map rather than a
                            # number kept beside it.
                            value = bytes(hid.MOUSE_REPORT)
                        else:
                            value = self._state_consumer.to_bytes(2, "little")
                        writer = api["DataWriter"]()
                        writer.write_bytes(value)
                        request.respond_with_value(writer.detach_buffer())
                except Exception as exc:  # noqa: BLE001 - one read, not the link
                    diagnostics.failed("answering a report read", exc)
                finally:
                    deferral.complete()

            loop.call_soon_threadsafe(lambda: loop.create_task(respond()))

        def write_requested(sender, args):
            deferral = args.get_deferral()

            async def collect():
                try:
                    request = await args.get_request_async()
                    if request is not None and request.value is not None:
                        reader = api["DataReader"].from_buffer(request.value)
                        data = bytes(reader.unconsumed_buffer_length)
                        # DataReader.read_bytes fills the buffer in place.
                        reader.read_bytes(data)
                        self._emit(
                            "output-report",
                            "target wrote " + data.hex(" "),
                        )
                        request.respond()
                except Exception as exc:  # noqa: BLE001 - one write, not the link
                    diagnostics.failed("answering a report write", exc)
                finally:
                    deferral.complete()

            loop.call_soon_threadsafe(lambda: loop.create_task(collect()))

        characteristic.add_subscribed_clients_changed(subscribed_changed)
        characteristic.add_read_requested(read_requested)
        characteristic.add_write_requested(write_requested)

    # ------------------------------------------------------------------ reports

    @property
    def is_subscribed(self) -> bool:
        with self._sub_lock:
            return bool(self._subscribed)

    @property
    def advertising_status(self) -> str:
        """The advertisement status, as words: "started", "aborted", ...

        Read from any thread. The value is cached, because the provider's own
        property belongs to the loop's apartment; a cache older than a second
        queues a fresh read on that thread for the next caller.
        """
        if time.monotonic() - self._advertising_at > STATUS_REFRESH_S:
            self.refresh_advertising_status()
        return self._advertising

    def _report_failure(self, message: str) -> None:
        """Complain the first time a report cannot be delivered, then stay quiet.

        This is the fault the user experiences as "it is connected and nothing
        happens", and it used to be logged at debug level only -- which is the
        same as not logging it at all.
        """
        self._failed_reports += 1
        if self._failed_reports == 1:
            log.warning("cannot hand reports to the target: %s", message)
        else:
            log.debug("report still failing: %s", message)

    def _notify(self, report_id: int, payload: bytes) -> bool:
        """Send one report. Returns False when no central is listening."""
        characteristic = self._reports.get(report_id)
        if characteristic is None or self._loop is None:
            return False
        with self._sub_lock:
            if report_id not in self._subscribed:
                return False

        api = self._api
        writer = api["DataWriter"]()
        writer.write_bytes(report_value(payload))
        buffer = writer.detach_buffer()

        future = asyncio.run_coroutine_threadsafe(
            _deliver(characteristic, buffer), self._loop
        )
        try:
            results = future.result(timeout=1.0)
        except Exception as exc:  # noqa: BLE001 - one report must not stop the rest
            self._report_failure(f"notify failed: {exc}")
            return False
        if not _delivered(results):
            self._report_failure("the target did not accept the report")
            return False
        return True

    def keyboard_state(self, modifier: int, keys: list[int]) -> bool:
        """Send a keyboard report: the modifier bitmap plus seven key slots.

        The seven bytes after the modifier are all key slots -- there is no
        reserved byte. The report map declares exactly that (one INPUT item of
        eight bits for the modifiers, one INPUT(Array) item with Report Count 7
        for the keys), so the payload is 8 bytes. A report whose length does not
        match the descriptor is discarded by the host with no error, which is
        exactly what a silent keyboard looks like, so the count here and the
        Report Count in HID_REPORT_MAP have to stay in step.
        """
        slots = [k & 0xFF for k in keys if k][:7]
        slots += [0] * (7 - len(slots))
        state = (modifier & 0xFF, *slots)
        if state == self._state_keyboard:
            return True
        ok = self._notify(REPORT_ID_KEYBOARD, bytes(state))
        if ok:
            self._state_keyboard = state
        return ok

    def mouse_report(self, buttons: int, dx: int, dy: int, wheel: int = 0,
                     pan: int = 0) -> bool:
        """Send a relative mouse report."""
        payload = bytes([
            buttons & 0xFF,
            dx & 0xFF,
            dy & 0xFF,
            wheel & 0xFF,
            pan & 0xFF,
        ])
        if (buttons == self._state_buttons and dx == 0 and dy == 0
                and wheel == 0 and pan == 0):
            return True
        ok = self._notify(REPORT_ID_MOUSE, payload)
        if ok:
            self._state_buttons = buttons
        return ok

    def consumer_press(self, usage: int) -> bool:
        """Send a consumer control usage, then release it."""
        ok = self._notify(REPORT_ID_CONSUMER, usage.to_bytes(2, "little"))
        self._notify(REPORT_ID_CONSUMER, bytes(2))
        self._state_consumer = 0
        return ok

    def consumer_release(self) -> bool:
        """Drop any held consumer usage."""
        ok = self._notify(REPORT_ID_CONSUMER, bytes(2))
        if ok:
            self._state_consumer = 0
        return ok

    def release_all(self) -> bool:
        """Release every held key, button and consumer usage.

        Used when control returns to the PC, so the target is never left holding
        a key the user has already let go of. Each part is best effort: a report
        that cannot be delivered must not stop the others.
        """
        results = [
            self.keyboard_state(0, []),
            self.mouse_report(0, 0, 0),
            self.consumer_release(),
        ]
        return all(results)

    # ------------------------------------------------------------------ cleanup

    def stop(self) -> None:
        """Stop advertising and shut the loop down. Safe to call more than once.

        The loop may already be finished: a caller that owns the lifetime through
        ``start(stop_requested=...)`` has closed it by the time it gets here, and
        calling into a closed loop raises rather than doing nothing.
        """
        if self._thread is None:
            return
        for service in self._services:
            try:
                service.stop_advertising()
            except Exception:
                log.debug("stop_advertising failed", exc_info=True)
        self._services.clear()
        self._reports.clear()
        self._advertising_provider = None
        self._advertising = "stopped"
        thread, self._thread = self._thread, None
        thread.stop()
        self._emit("stopped", "peripheral stopped")

    def __enter__(self) -> "BleHidPeripheral":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


class BleFrameSink:
    """Hands the router's reports to the peripheral.

    The router already thinks in HID: a keyboard report is eight bytes of
    modifiers and HID usages, never virtual key codes, because the translation
    happens in ``model.Router`` against ``keymap.VK_TO_HID``. Every payload this
    receives is therefore already the report the target needs, so nothing is
    re-encoded -- the payloads are decoded and passed straight on.

    ``is_open`` means "a target is subscribed", not merely "advertising": with no
    subscriber the peripheral has nowhere to deliver a report, and reporting
    health any other way would let the service capture the keyboard while nothing
    responds.
    """

    def __init__(self, peripheral: BleHidPeripheral) -> None:
        self._peripheral = peripheral
        # The service judges link health by frames that actually went out, so
        # these count successful reports rather than calls.
        self.written_frames = 0
        self.bad_frames = 0
        self._buttons = 0

    @property
    def is_open(self) -> bool:
        return self._peripheral.is_subscribed

    @property
    def peripheral(self) -> BleHidPeripheral:
        return self._peripheral

    def send(self, kind: str, payload: bytes) -> bool:
        """FrameSink entry point. Returns True when the report was delivered."""
        try:
            if kind == hid.KEYBOARD:
                if len(payload) != hid.KEYBOARD_PAYLOAD:
                    self.bad_frames += 1
                    log.warning("keyboard payload must be %d bytes, got %d",
                                hid.KEYBOARD_PAYLOAD, len(payload))
                    return False
                delivered = self._peripheral.keyboard_state(payload[0], list(payload[1:]))
            elif kind == hid.MOUSE_MOVE:
                if len(payload) != hid.MOUSE_MOVE_PAYLOAD:
                    self.bad_frames += 1
                    log.warning("mouse move payload must be %d bytes, got %d",
                                hid.MOUSE_MOVE_PAYLOAD, len(payload))
                    return False
                dx, dy = hid.decode_mouse_move(payload)
                delivered = self._peripheral.mouse_report(self._buttons, dx, dy)
            elif kind == hid.MOUSE_BUTTON:
                # One byte, like the button field of a move report. An empty
                # payload meant "no buttons" and a longer one was truncated, so a
                # malformed frame was accepted instead of counted.
                if len(payload) != hid.BUTTON_PAYLOAD:
                    self.bad_frames += 1
                    log.warning("button payload must be %d byte, got %d",
                                hid.BUTTON_PAYLOAD, len(payload))
                    return False
                self._buttons = payload[0]
                delivered = self._peripheral.mouse_report(self._buttons, 0, 0)
            elif kind == hid.MOUSE_WHEEL:
                # A wheel payload carries the two int8 steps decode_wheel reads,
                # which is shorter than a movement payload. Measuring it against
                # the movement width never matched, so the detent was dropped in
                # silence -- which reaches the user as a wheel that does nothing.
                vertical, horizontal = (hid.decode_wheel(payload)
                                        if len(payload) == hid.WHEEL_PAYLOAD
                                        else (0, 0))
                delivered = self._peripheral.mouse_report(self._buttons, 0, 0,
                                                          vertical, horizontal)
            elif kind == hid.CONSUMER:
                if len(payload) != hid.CONSUMER_PAYLOAD:
                    self.bad_frames += 1
                    log.warning("consumer payload must be %d bytes, got %d",
                                hid.CONSUMER_PAYLOAD, len(payload))
                    return False
                usage = int.from_bytes(payload, "little")
                delivered = (self._peripheral.consumer_press(usage) if usage
                             else self._peripheral.consumer_release())
            elif kind == hid.RELEASE_ALL:
                delivered = self._peripheral.release_all()
            else:
                self.bad_frames += 1
                log.debug("no peripheral mapping for report kind %r", kind)
                return False
        except Exception as exc:  # noqa: BLE001 - one report, not the bridge
            self.bad_frames += 1
            # This is where a TypeError per keystroke hid for a whole round: the
            # kind is part of the words so each report reports its own first fault.
            diagnostics.failed(f"sending a {kind} report", exc)
            return False

        if delivered:
            self.written_frames += 1
        return delivered

    def close(self) -> None:
        try:
            self._peripheral.release_all()
        except Exception:
            log.debug("release_all failed on close", exc_info=True)
        self._peripheral.stop()
