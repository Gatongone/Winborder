"""Device link: serial port transport and port discovery."""

from __future__ import annotations

import logging
import re
import threading
import time

from . import ipc

log = logging.getLogger("winborder.link")


class LinkError(Exception):
    """Raised when the device link cannot be opened or written to."""


class SerialLink:
    """Framed byte link over a serial port.

    Writes are serialised onto a dedicated thread. Writing from several
    threads previously interleaved frames on the wire and caused the device
    heartbeat to time out.

    DTR and RTS are cleared before opening. pyserial asserts them by default,
    and on ESP32-S3 that resets the chip, which drops the BLE connection the
    moment the host starts.
    """

    def __init__(self, port: str, baudrate: int = ipc.DEFAULT_BAUDRATE,
                 open_timeout: float = 3.0) -> None:
        try:
            import serial
        except ImportError as exc:  # pragma: no cover
            raise LinkError("pyserial is required: pip install pyserial") from exc

        self.port = port
        self.baudrate = baudrate
        try:
            self._ser = serial.Serial()
            self._ser.port = port
            self._ser.baudrate = baudrate
            self._ser.timeout = 0
            self._ser.write_timeout = open_timeout
            self._ser.dtr = False
            self._ser.rts = False
            self._ser.open()
        except Exception as exc:
            raise LinkError(f"cannot open {port}: {exc}") from exc

        try:
            self._ser.dtr = False
            self._ser.rts = False
        except Exception:
            log.debug("port does not expose DTR/RTS control")

        self.is_open = True
        self.bad_frames = 0
        self.written_frames = 0
        self._parser = ipc.FrameParser()
        self._events: list[tuple[int, bytes]] = []
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._queue: list[bytes] = []
        self._queue_cv = threading.Condition()
        self._writer = threading.Thread(
            target=self._write_loop, name="winborder-writer", daemon=True
        )
        self._writer.start()
        self._reader = threading.Thread(
            target=self._read_loop, name="winborder-reader", daemon=True
        )
        self._reader.start()
        log.info("serial open: %s @ %d", port, baudrate)

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(4096)
            except Exception:
                if not self._stop.is_set():
                    log.debug("serial read failed", exc_info=True)
                return
            if not chunk:
                continue
            frames = self._parser.feed(chunk)
            self.bad_frames = self._parser.bad_frames
            if frames:
                with self._lock:
                    self._events.extend(frames)

    def _write_loop(self) -> None:
        while not self._stop.is_set():
            with self._queue_cv:
                while not self._queue and not self._stop.is_set():
                    self._queue_cv.wait(0.2)
                if self._stop.is_set():
                    return
                batch = list(self._queue)
                self._queue.clear()
            for data in batch:
                try:
                    with self._write_lock:
                        self._ser.write(data)
                    self.written_frames += 1
                except Exception:
                    if not self._stop.is_set():
                        log.debug("serial write failed", exc_info=True)
                    return

    def submit(self, data: bytes) -> bool:
        """Queue a frame for writing. Never blocks the caller."""
        if self._stop.is_set() or not self.is_open:
            return False
        with self._queue_cv:
            if len(self._queue) > 512:
                return False
            self._queue.append(data)
            self._queue_cv.notify()
        return True

    def poll(self) -> list[tuple[int, bytes]]:
        with self._lock:
            out, self._events = self._events, []
        return out

    def close(self) -> None:
        self._stop.set()
        with self._queue_cv:
            self._queue_cv.notify_all()
        self.is_open = False
        try:
            self._ser.close()
        except Exception:
            log.debug("serial close failed", exc_info=True)

    def __enter__(self) -> "SerialLink":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


_PORT_RX = re.compile(r"^COM(\d+)$", re.IGNORECASE)


def list_serial_ports() -> list[str]:
    """Return available COM ports sorted by numeric index."""
    try:
        from serial.tools import list_ports
    except ImportError:  # pragma: no cover
        return []
    ports = [p.device for p in list_ports.comports()]
    return sorted(ports, key=port_index)


def port_index(name: str) -> int:
    """Sort key that orders COM10 after COM9."""
    match = _PORT_RX.match(name)
    return int(match.group(1)) if match else 1 << 30


def probe_port(port: str, baudrate: int = ipc.DEFAULT_BAUDRATE,
               timeout: float = 2.0) -> bool:
    """Return True when a Winborder device answers on the given port."""
    try:
        link = SerialLink(port, baudrate)
    except LinkError:
        return False
    try:
        link.submit(ipc.encode_frame(ipc.MsgType.VERSION_REQ))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg_type, payload in link.poll():
                if msg_type == ipc.DevMsgType.VERSION and len(payload) == 3:
                    return True
            time.sleep(0.05)
        return False
    finally:
        link.close()


def suggest_port(ports: list[str]) -> str | None:
    """Pick the most likely Winborder port: the highest-numbered COM port.

    Boards with a USB-UART bridge expose two ports. The runtime protocol runs
    on the native USB port, which enumerates after the bridge.
    """
    ranked = sorted(ports, key=port_index)
    return ranked[-1] if ranked else None
