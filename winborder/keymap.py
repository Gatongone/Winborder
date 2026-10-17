"""Key tables: names, Windows virtual keys and HID usages.

``KEY_NAMES`` is the single source for the named keys: the settings file is
written in these names, and the tables used on the wire are derived from it.

Modifier keys are translated through ``VK_TO_MODIFIER`` into the keyboard report
modifier bitfield. They are deliberately excluded from ``VK_TO_HID`` so a key is
never reported as both a modifier bit and a key slot.

Consumer-page keys (volume, media transport, browser navigation) are translated
through ``VK_TO_CONSUMER`` and sent as HID report id 3.
"""

from __future__ import annotations

MOD_LEFT_CTRL = 0x01
MOD_LEFT_SHIFT = 0x02
MOD_LEFT_ALT = 0x04
MOD_LEFT_GUI = 0x08
# The upper half of the modifier byte the report map declares. Nothing sends
# these today; they are here so the mask is one readable table rather than a
# quarter of one, and so a right hand key mapped as a modifier has a name.
MOD_RIGHT_CTRL = 0x10
MOD_RIGHT_SHIFT = 0x20
MOD_RIGHT_ALT = 0x40
MOD_RIGHT_GUI = 0x80

VK_CTRL_LEFT = 0xA2
VK_CTRL_RIGHT = 0xA3
VK_ESCAPE = 0x1B

# HID usage ids of the eight modifier keys, in report bit order.
HID_MODIFIER_FIRST = 0xE0
HID_MODIFIER_LAST = 0xE7

# name -> (virtual key, HID usage)
KEY_NAMES: dict[str, tuple[int, int]] = {
    **{chr(ord("A") + i): (0x41 + i, 0x04 + i) for i in range(26)},
    **{str(digit): (0x30 + digit, 0x1E + digit - 1) for digit in range(1, 10)},
    # The zero key is named as its keycap reads: its virtual key code does not
    # follow the other digits, and its usage ends the run they start.
    "0": (0x30, 0x27),
    **{f"F{i}": (0x70 + i - 1, 0x3A + i - 1) for i in range(1, 13)},
    **{f"F{i}": (0x7C + i - 13, 0x68 + i - 13) for i in range(13, 25)},
    **{f"Numpad{i}": (0x60 + i, 0x62 if i == 0 else 0x58 + i) for i in range(10)},
    "Escape": (0x1B, 0x29),
    "Tab": (0x09, 0x2B),
    "CapsLock": (0x14, 0x39),
    "Space": (0x20, 0x2C),
    "Enter": (0x0D, 0x28),
    "Backspace": (0x08, 0x2A),
    "Insert": (0x2D, 0x49),
    "Delete": (0x2E, 0x4C),
    "Home": (0x24, 0x4A),
    "End": (0x23, 0x4D),
    "PageUp": (0x21, 0x4B),
    "PageDown": (0x22, 0x4E),
    "ArrowUp": (0x26, 0x52),
    "ArrowDown": (0x28, 0x51),
    "ArrowLeft": (0x25, 0x50),
    "ArrowRight": (0x27, 0x4F),
    "PrintScreen": (0x2C, 0x46),
    "ScrollLock": (0x91, 0x47),
    "Pause": (0x13, 0x48),
    "NumLock": (0x90, 0x53),
    "Menu": (0x5D, 0x65),
    # Keys a Mac keyboard has where a PC one has PrintScreen and NumLock: Help
    # is the key next to the function keys, Clear is the keypad's NumLock.
    "Help": (0x2F, 0x75),
    "Clear": (0x0C, 0x53),
    "Minus": (0xBD, 0x2D),
    "Equal": (0xBB, 0x2E),
    "BracketLeft": (0xDB, 0x2F),
    "BracketRight": (0xDD, 0x30),
    "Backslash": (0xDC, 0x31),
    "Semicolon": (0xBA, 0x33),
    "Quote": (0xDE, 0x34),
    "Backquote": (0xC0, 0x35),
    "Comma": (0xBC, 0x36),
    "Period": (0xBE, 0x37),
    "Slash": (0xBF, 0x38),
    "NumpadDivide": (0x6F, 0x54),
    "NumpadMultiply": (0x6A, 0x55),
    "NumpadSubtract": (0x6D, 0x56),
    "NumpadAdd": (0x6B, 0x57),
    "NumpadDecimal": (0x6E, 0x63),
    # Usage 0x58 is Keypad ENTER, not a separator: the name follows the table.
    # Most Windows layouts report the numpad Enter as a plain Return, so this
    # name is only reachable through the list -- it exists to be a target.
    "NumpadEnter": (0x6C, 0x58),
    # The ISO key between the left Shift and the letters.
    "NonUsBackslash": (0xE2, 0x64),
    "LeftCtrl": (0xA2, 0xE0),
    "LeftShift": (0xA0, 0xE1),
    "LeftAlt": (0xA4, 0xE2),
    "LeftWin": (0x5B, 0xE3),
    "RightCtrl": (0xA3, 0xE4),
    "RightShift": (0xA1, 0xE5),
    "RightAlt": (0xA5, 0xE6),
    "RightWin": (0x5C, 0xE7),
}

def _is_modifier(usage: int) -> bool:
    return HID_MODIFIER_FIRST <= usage <= HID_MODIFIER_LAST


# Modifiers are deliberately absent here: they travel as bits in the modifier
# bitfield, so a key is never reported both as a bit and as a key slot.
VK_TO_HID: dict[int, int] = {
    vk: usage for vk, usage in KEY_NAMES.values() if not _is_modifier(usage)
}
VK_TO_MODIFIER: dict[int, int] = {
    vk: 1 << (usage - HID_MODIFIER_FIRST)
    for vk, usage in KEY_NAMES.values() if _is_modifier(usage)
}

VK_TO_CONSUMER: dict[int, int] = {
    0xAD: 0xE2,
    0xAE: 0xE9,
    0xAF: 0xE8,
    0xB0: 0xCD,
    0xB1: 0xB6,
    0xB2: 0xB3,
    0xB3: 0xB0,
    0xA6: 0x224,
    0xA7: 0x225,
    0xA8: 0x226,
    0xAC: 0x221,
    0xA9: 0x22A,
    0xAA: 0x22D,
    0xAB: 0x21D,
}

NAME_BY_VK: dict[int, str] = {vk: name for name, (vk, _) in KEY_NAMES.items()}
NAME_BY_USAGE: dict[int, str] = {usage: name for name, (_, usage) in KEY_NAMES.items()}


def vk_from_name(name: str) -> int:
    """Virtual key for a key name.

    A number is accepted too, so a key the table does not name can still be
    bound by its virtual key code.
    """
    entry = KEY_NAMES.get(name)
    if entry is not None:
        return entry[0]
    try:
        return int(name, 0)
    except ValueError:
        raise ValueError(f"unknown key name: {name!r}") from None


def usage_from_name(name: str) -> int:
    """HID usage for a key name, used by the remap setting."""
    entry = KEY_NAMES.get(name)
    if entry is None:
        raise ValueError(f"unknown key name: {name!r}")
    return entry[1]


def modifier_bit(usage: int) -> int | None:
    """Modifier bit for a HID usage, or None when it is an ordinary key."""
    if _is_modifier(usage):
        return 1 << (usage - HID_MODIFIER_FIRST)
    return None


def describe_vk(vk: int) -> str:
    return NAME_BY_VK.get(vk, f"VK 0x{vk:02X}")


def describe_usage(usage: int) -> str:
    return NAME_BY_USAGE.get(usage, f"usage 0x{usage:02X}")
