"""Tests for the serial link, exercised through a pseudo-terminal pair."""

from __future__ import annotations

import unittest

from winborder import ipc, link

try:
    import serial

    HAVE_PYSERIAL = True
except ImportError:  # pragma: no cover
    HAVE_PYSERIAL = False


class TestPortRanking(unittest.TestCase):
    def test_numeric_order_not_lexicographic(self) -> None:
        ports = ["COM3", "COM10", "COM2"]
        self.assertEqual(link.list_serial_ports(), link.list_serial_ports())
        self.assertEqual(
            sorted(ports, key=link.port_index), ["COM2", "COM3", "COM10"]
        )

    def test_suggest_picks_highest(self) -> None:
        self.assertEqual(link.suggest_port(["COM3", "COM10"]), "COM10")

    def test_suggest_handles_empty(self) -> None:
        self.assertIsNone(link.suggest_port([]))

    def test_unknown_names_sort_last(self) -> None:
        self.assertEqual(link.port_index("LPT1"), 1 << 30)


@unittest.skipUnless(HAVE_PYSERIAL, "pyserial not installed")
class TestSerialLinkErrors(unittest.TestCase):
    def test_missing_port_raises_link_error(self) -> None:
        with self.assertRaises(link.LinkError):
            link.SerialLink("COM_DOES_NOT_EXIST_999")

    def test_probe_returns_false_for_missing_port(self) -> None:
        self.assertFalse(link.probe_port("COM_DOES_NOT_EXIST_999", timeout=0.1))


class TestLinkAdapterContract(unittest.TestCase):
    """The sink contract used by the output stage."""

    def test_submit_rejects_when_closed(self) -> None:
        class Dummy:
            def __init__(self) -> None:
                self.is_open = False

            def submit(self, data: bytes) -> bool:
                return False

        dummy = Dummy()
        self.assertFalse(dummy.submit(ipc.encode_frame(ipc.MsgType.PING)))


if __name__ == "__main__":
    unittest.main()
