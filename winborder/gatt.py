"""The HID over GATT protocol this program publishes.

Everything here is data the protocol defines: service and characteristic UUIDs,
the report map and its bcdHID block, the report ids the map declares, and which
attributes a target may only reach over an encrypted link. None of it needs a
radio, so it can be read, compared and tested without one -- which is why it is
not part of :mod:`winborder.ble`, where the connection machinery lives.

The report map is the contract the whole write path is measured against: a
payload whose length disagrees with it is dropped by the host with no error at
all, so the byte counts here and the payload widths in :mod:`winborder.hid` are
two halves of one fact.
"""

from __future__ import annotations

# ==========================================================================
# GATT UUIDs
# ==========================================================================

UUID_HID_SERVICE = "00001812-0000-1000-8000-00805f9b34fb"
UUID_HID_INFO = "00002a4a-0000-1000-8000-00805f9b34fb"
UUID_REPORT_MAP = "00002a4b-0000-1000-8000-00805f9b34fb"
UUID_HID_CONTROL = "00002a4c-0000-1000-8000-00805f9b34fb"
UUID_REPORT = "00002a4d-0000-1000-8000-00805f9b34fb"
UUID_PROTOCOL_MODE = "00002a4e-0000-1000-8000-00805f9b34fb"
UUID_REPORT_REFERENCE = "00002908-0000-1000-8000-00805f9b34fb"

UUID_DIS_SERVICE = "0000180a-0000-1000-8000-00805f9b34fb"
UUID_MANUFACTURER_NAME = "00002a29-0000-1000-8000-00805f9b34fb"
UUID_PNP_ID = "00002a50-0000-1000-8000-00805f9b34fb"

UUID_BATTERY_SERVICE = "0000180f-0000-1000-8000-00805f9b34fb"
UUID_BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"

# Report ids, matching the descriptor below and the report map it declares.
REPORT_ID_KEYBOARD = 1
REPORT_ID_MOUSE = 2
REPORT_ID_CONSUMER = 3

# ==========================================================================
# HID report descriptor. The layout is the standard keyboard one.
#
#   Report ID 1 (keyboard, 8B payload): [modifiers][k0..k6]
#   Report ID 2 (mouse, 5B payload):    [buttons][dx][dy][wheel][pan]
#   Report ID 3 (consumer, 2B payload): [usage_lo][usage_hi]
# ==========================================================================

HID_REPORT_MAP = bytes([
    # ---------------- Report ID 1: keyboard ----------------
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x01,        #   Report ID (1)
    0x05, 0x07,        #   Usage Page (Keyboard/Keypad)
    0x19, 0xE0,        #   Usage Minimum (LeftControl)
    0x29, 0xE7,        #   Usage Maximum (Right GUI)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    0x81, 0x02,        #   Input (Data,Var,Abs)   <- modifier bitmap (1B)
    0x95, 0x05,        #   Report Count (5)
    0x75, 0x01,        #   Report Size (1)
    0x05, 0x08,        #   Usage Page (LEDs)
    0x19, 0x01,        #   Usage Minimum (Num Lock)
    0x29, 0x05,        #   Usage Maximum (Kana)
    0x91, 0x02,        #   Output (Data,Var,Abs)  <- LEDs, written back by the target
    0x95, 0x01,        #   Report Count (1)
    0x75, 0x03,        #   Report Size (3)
    0x91, 0x01,        #   Output (Const)
    0x95, 0x07,        #   Report Count (7)
    0x75, 0x08,        #   Report Size (8)
    0x15, 0x00,        #   Logical Minimum (0)
    0x26, 0xFF, 0x00,  #   Logical Maximum (255)
    0x05, 0x07,        #   Usage Page (Keyboard/Keypad)
    0x19, 0x00,        #   Usage Minimum (0)
    # Up to the end of the page, not 0x65: F13 to F24 are 0x68 to 0x73 and the
    # keyboard page runs to 0xE7, so a map that stops at 0x65 can name those keys
    # and never send them.
    0x2A, 0xFF, 0x00,  #   Usage Maximum (255)
    0x81, 0x00,        #   Input (Data,Array)     <- 7 key slots (7B)
    0xC0,              # End Collection

    # ---------------- Report ID 2: mouse ----------------
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x02,        #   Report ID (2)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)
    0x05, 0x09,        #     Usage Page (Button)
    0x19, 0x01,        #     Usage Minimum (Button 1)
    0x29, 0x05,        #     Usage Maximum (Button 5)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x95, 0x05,        #     Report Count (5)
    0x75, 0x01,        #     Report Size (1)
    0x81, 0x02,        #     Input (Data,Var,Abs)  <- button bitmap (1B)
    0x95, 0x01,        #     Report Count (1)
    0x75, 0x03,        #     Report Size (3)
    0x81, 0x01,        #     Input (Const)         <- 3 padding bits
    0x05, 0x01,        #     Usage Page (Generic Desktop)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x09, 0x38,        #     Usage (Wheel)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x03,        #     Report Count (3)
    0x81, 0x06,        #     Input (Data,Var,Rel)  <- dx, dy, wheel (3B)
    0x05, 0x0C,        #     Usage Page (Consumer)
    0x0A, 0x38, 0x02,  #     Usage (AC Pan)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x06,        #     Input (Data,Var,Rel)  <- horizontal (1B)
    0xC0,              #   End Collection
    0xC0,              # End Collection

    # ---------------- Report ID 3: consumer control ----------------
    0x05, 0x0C,        # Usage Page (Consumer)
    0x09, 0x01,        # Usage (Consumer Control)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x03,        #   Report ID (3)
    0x15, 0x00,        #   Logical Minimum (0)
    0x26, 0xFF, 0x03,  #   Logical Maximum (1023)
    0x19, 0x00,        #   Usage Minimum (0)
    0x2A, 0xFF, 0x03,  #   Usage Maximum (1023)
    0x75, 0x10,        #   Report Size (16)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x00,        #   Input (Data,Array,Abs) <- 16 bit usage (2B)
    0xC0,              # End Collection
])

# bcdHID 1.11 / bCountryCode 0 / flags: remote wake supported.
HID_INFORMATION = bytes([0x11, 0x01, 0x00, 0x02])


# Manufacturer name reported through the Device Information Service.
MANUFACTURER = "Winborder"


#: The attributes a target may only reach over an encrypted link.
#:
#: HOGP §6.1 makes bonding a *shall* for the HID reports, and this level is also
#: what starts the host's own pairing flow (Apple ADG §58.10): the first read or
#: subscribe comes back Insufficient Authentication, so the host pairs and shows
#: its prompt. Plain is the one configuration that must not be used here: the
#: host subscribes over an unencrypted link, its HID stack bonds afterwards, and
#: the subscription it already took is dropped without a word -- the prompt that
#: should have appeared on the host appears on Windows instead, and nothing is
#: ever delivered. Both references that are known to work against iOS encrypt
#: exactly these (`WinBleTouch`: report + 0x2908).
PROTECTED_UUIDS = frozenset({UUID_REPORT, UUID_REPORT_REFERENCE})


def is_protected(uuid_value: object) -> bool:
    """Whether an attribute has to be reached over an encrypted link."""
    return str(uuid_value).lower() in PROTECTED_UUIDS
