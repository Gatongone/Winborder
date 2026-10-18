"""Typing text as keystrokes, because a HID link carries keys and not characters.

A keyboard report carries usages, and the target turns them into characters
through its own layout. So "sending" a string is only possible for characters the
target layout can produce from those keys; there is no way to express a character
the layout has no key for, which rules out everything outside the layout's own
alphabet -- CJK, emoji, and anything the layout reaches only through a compose
sequence with an input method.

This module plans the strokes for a US layout, which is what Windows and iPadOS
use by default, and reports what it had to leave out so the caller can say so
rather than typing half a sentence in silence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import keymap

#: How much of one clipboard is typed in a single request. A long one is not a
#: failure, it is a decision the user did not mean to make: 2000 keys at the pace
#: below is about twenty seconds of the target being typed into.
MAX_CHARS = 2000

#: A US layout, character -> (usage, needs shift). The usages are the keys of the
#: layout, in HID order; every punctuation key serves two characters and the
#: shifted one shares its usage.
US_LAYOUT: dict[str, tuple[int, bool]] = {}


def _add(chars: str, usage: int, shift: bool = False) -> None:
    for char in chars:
        US_LAYOUT[char] = (usage, shift)


# Letters: the shifted form is the same key with shift held.
for _index in range(26):
    _letter = chr(ord("a") + _index)
    _add(_letter, 0x04 + _index)
    _add(_letter.upper(), 0x04 + _index, shift=True)

# The digit row, and the shifted row above it.
for _digit in range(1, 10):
    _add(str(_digit), 0x1E + _digit - 1)
_add("0", 0x27)
_add("!", 0x1E, shift=True)
_add("@", 0x1F, shift=True)
_add("#", 0x20, shift=True)
_add("$", 0x21, shift=True)
_add("%", 0x22, shift=True)
_add("^", 0x23, shift=True)
_add("&", 0x24, shift=True)
_add("*", 0x25, shift=True)
_add("(", 0x26, shift=True)
_add(")", 0x27, shift=True)

# Everything else the layout can type, unshifted then shifted.
_add(" ", 0x2C)
_add("\n", 0x28)
_add("\t", 0x2B)
_add("-", 0x2D)
_add("_", 0x2D, shift=True)
_add("=", 0x2E)
_add("+", 0x2E, shift=True)
_add("[", 0x2F)
_add("{", 0x2F, shift=True)
_add("]", 0x30)
_add("}", 0x30, shift=True)
_add("\\", 0x31)
_add("|", 0x31, shift=True)
_add(";", 0x33)
_add(":", 0x33, shift=True)
_add("'", 0x34)
_add('"', 0x34, shift=True)
_add("`", 0x35)
_add("~", 0x35, shift=True)
_add(",", 0x36)
_add("<", 0x36, shift=True)
_add(".", 0x37)
_add(">", 0x37, shift=True)
_add("/", 0x38)
_add("?", 0x38, shift=True)


@dataclass(frozen=True)
class Stroke:
    """One key press: the usage, and the modifiers held while it is down."""

    usage: int
    modifiers: int

    @property
    def shifted(self) -> bool:
        return bool(self.modifiers & keymap.MOD_LEFT_SHIFT)


@dataclass(frozen=True)
class Plan:
    """What a piece of text becomes, and what it could not become."""

    strokes: tuple[Stroke, ...] = ()
    #: Characters this layout cannot produce, so they were left out.
    skipped: int = 0
    #: Characters dropped because the text was longer than the limit.
    truncated: int = 0
    #: The characters that were skipped, for the log line, at most a few of them.
    examples: tuple[str, ...] = field(default=())

    def __bool__(self) -> bool:
        return bool(self.strokes)


def plan(text: str, limit: int = MAX_CHARS) -> Plan:
    """Turn text into keystrokes a US layout can type.

    A line break is Enter and a tab is Tab; a Windows clipboard holds CRLF, so the
    pair is folded into the one stroke the target understands.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if limit <= 0:
        return Plan(truncated=len(text))
    body, rest = text[:limit], text[limit:]
    strokes: list[Stroke] = []
    skipped: list[str] = []
    for char in body:
        entry = US_LAYOUT.get(char)
        if entry is None:
            skipped.append(char)
            continue
        usage, shift = entry
        strokes.append(Stroke(usage, keymap.MOD_LEFT_SHIFT if shift else 0))
    return Plan(tuple(strokes), len(skipped), len(rest), tuple(skipped[:5]))
