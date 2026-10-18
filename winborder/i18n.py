"""The languages the interface is shown in.

The window asks for a name, and the tables say what that name reads as. The names
are built from the thing they show, never from the text:

* ``label_*`` -- a page title, a group heading, a field label, a button, a menu
  item. The part after the prefix is the field or page it belongs to, so
  ``label_sensitivity`` is the label of the pointer gain row.
* ``desc_*`` -- the description under one of those.
* ``value_*`` -- a word a setting holds, such as the side a target sits on.
* ``msg_*`` -- anything the program says on its own: a notification, a log line
  it shows, an error from the settings file.

One JSON file per language in ``winborder/locales``, with ``en.json`` as the
English source and the fallback for a name a translation lacks. Editing a
sentence is editing one value in those files; editing what the window *says*
means adding a name to the code and to all five files. A name no table carries is
shown as the name itself, so a half-finished rename is visible rather than blank.

Only the window is translated. The log lines the host produces are
diagnostic output and stay in English, so they can be searched for and compared
between versions.

How the text is written, in every language -- the rules come from reviewing the
wording with the person who uses the program:

* Say what a setting *is*, not what the reader should do with it. Noun phrases,
  not instructions: "Interval before the same edge can be crossed again", not
  "Wait this long before crossing again".
* No second person and no imperatives. "Click a field and press a key" describes
  the author's own UI; "Key remapping for the target device; right-click a field
  to choose from the full list" describes the field.
* No rhetorical questions in titles or descriptions. A dialog that really asks
  something asks it formally: "Reset all settings to their default values?".
* One name per thing. The machine this program runs on is the *PC* in English and
  主机 in Chinese; the device it drives is the *target device*, or just the target
  where a label is short. Never "host": the word named both sides of the link on
  this page and its opposite on that one, and it is gone from the strings
  entirely. Nor a synonym invented halfway through, nor 被控端 in one label and
  目标设备 in the next. Chinese says 指针 and never 光标, and writes 此, never
  这个.
* Technical phrasing, not conversational: "the current value is {kind}", not
  "got {kind}"; "see the Log", not "the Log will tell you why".
* Short is a feature, not a compromise. A note that repeats what the page title
  already says is a note that will not be read.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

DEFAULT_LANGUAGE = "en"

# Code, and the name of the language written in that language.
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("ru", "Русский"),
    ("zh", "简体中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
)

_NAME_BY_CODE = dict(LANGUAGES)
_CODE_BY_NAME = {name: code for code, name in LANGUAGES}

_LANGUAGE = DEFAULT_LANGUAGE


def codes() -> tuple[str, ...]:
    """Every language code, in the order they are offered."""
    return tuple(code for code, _name in LANGUAGES)


def native_name(code: str) -> str:
    """The name of a language in that language."""
    return _NAME_BY_CODE.get(code, _NAME_BY_CODE[DEFAULT_LANGUAGE])


def name_for_code(code: object) -> str:
    """The name to show for a value of the language setting."""
    return native_name(code if isinstance(code, str) else DEFAULT_LANGUAGE)


def code_for_name(name: object) -> str | None:
    """The code a shown name stands for, or None when it names no language."""
    if not isinstance(name, str):
        return None
    if name in _CODE_BY_NAME:
        return _CODE_BY_NAME[name]
    for code, native in LANGUAGES:              # codes are accepted as well
        if name.strip().lower() == code:
            return code
    return None


def is_supported(code: object) -> bool:
    return isinstance(code, str) and code in _NAME_BY_CODE


def language() -> str:
    """The language in use."""
    return _LANGUAGE


def set_language(code: object) -> str:
    """Use a language. An unknown code leaves English in place."""
    global _LANGUAGE
    _LANGUAGE = code if is_supported(code) else DEFAULT_LANGUAGE
    return _LANGUAGE


def t(key: str) -> str:
    """The text a key stands for, in the language in use.

    A key that no table carries is returned as it is: a missing string then shows
    up as ``label_something`` in the window instead of an empty label, which is
    what makes a half-finished rename visible rather than silent.
    """
    if _LANGUAGE == DEFAULT_LANGUAGE:
        return ENGLISH.get(key, key)
    return TRANSLATIONS.get(_LANGUAGE, {}).get(key) or ENGLISH.get(key, key)


#: Where the tables live: one JSON file per language, keyed by name.
LOCALES = Path(__file__).resolve().parent / "locales"

log = logging.getLogger("winborder.i18n")


def _read_table(code: str) -> dict[str, str]:
    """One language's table, or nothing when the file cannot be used.

    A missing or malformed file leaves that language in English: an empty table
    makes :func:`t` return the text it was given, which is a window that reads
    rather than a crash on import.
    """
    path = LOCALES / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("%s could not be read (%s); %s stays in English",
                  path, exc, code)
        return {}
    if not isinstance(data, dict):
        log.error("%s does not hold a JSON object; %s stays in English",
                  path, code)
        return {}
    return {str(key): str(value) for key, value in data.items()}


#: The English text, which is also the fallback for a key a translation lacks.
ENGLISH: dict[str, str] = _read_table(DEFAULT_LANGUAGE)

TRANSLATIONS: dict[str, dict[str, str]] = {
    code: _read_table(code) for code in codes() if code != DEFAULT_LANGUAGE
}
