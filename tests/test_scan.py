"""Tests for the device list.

The radio itself cannot be exercised here, but the two pieces that decide what
the page shows can be: how a 16 bit UUID is abbreviated, and how a device's name
and service list survive being spread across several advertisements.
"""

from __future__ import annotations

import unittest
import uuid as uuid_module

from winborder import scan


class FakeAdvertisement:
    def __init__(self, local_name: str = "", service_uuids: list | None = None) -> None:
        self.local_name = local_name
        self.service_uuids = service_uuids or []


class FakeArgs:
    def __init__(self, address: int, rssi: int, advertisement: FakeAdvertisement) -> None:
        self.bluetooth_address = address
        self.raw_signal_strength_in_dbm = rssi
        self.advertisement = advertisement


def uuid16(short: str) -> uuid_module.UUID:
    return uuid_module.UUID(f"0000{short}-0000-1000-8000-00805F9B34FB")


class TestShortUuid(unittest.TestCase):
    def test_a_standard_16_bit_uuid_becomes_its_four_digits(self) -> None:
        self.assertEqual(scan._short(uuid16("1812")), "1812")

    def test_a_vendor_uuid_is_left_whole(self) -> None:
        custom = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
        self.assertEqual(scan._short(custom), custom.upper())


class TestMerging(unittest.TestCase):
    """One advertisement rarely carries everything about a device."""

    def setUp(self) -> None:
        self.scanner = scan.DeviceScanner()

    def feed(self, address: int, rssi: int, **kwargs) -> None:
        self.scanner._on_advertisement(None, FakeArgs(address, rssi, FakeAdvertisement(**kwargs)))

    def test_a_name_from_a_later_packet_is_kept(self) -> None:
        self.feed(0x4904730BD9AD, -60)
        self.feed(0x4904730BD9AD, -58, local_name="iPad")
        device = self.scanner.snapshot()[0]
        self.assertEqual(device.name, "iPad")
        self.assertEqual(device.rssi, -58, "the latest signal is the current one")

    def test_a_later_packet_without_a_name_does_not_erase_it(self) -> None:
        self.feed(0x4904730BD9AD, -60, local_name="iPad")
        self.feed(0x4904730BD9AD, -62)
        self.assertEqual(self.scanner.snapshot()[0].name, "iPad")

    def test_services_survive_a_packet_that_has_none(self) -> None:
        self.feed(0x001122334455, -50, service_uuids=[uuid16("1812")])
        self.feed(0x001122334455, -50)
        self.assertEqual(self.scanner.snapshot()[0].services, ("1812",))

    def test_devices_are_one_row_each_and_strongest_first(self) -> None:
        self.feed(0x01, -90)
        self.feed(0x02, -40)
        self.feed(0x01, -80)
        order = [device.address for device in self.scanner.snapshot()]
        self.assertEqual(len(order), 2, "the same address is one device")
        self.assertEqual(order[0], "000000000002")

    def test_clear_empties_the_list(self) -> None:
        self.feed(0x01, -40)
        self.scanner.clear()
        self.assertEqual(self.scanner.snapshot(), [])

    def test_it_is_not_running_before_it_is_started(self) -> None:
        self.assertFalse(self.scanner.running)


if __name__ == "__main__":
    unittest.main()
