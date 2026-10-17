"""Version and publisher, in one place.

The version itself lives in :mod:`winborder`, so the number the window shows on
its Generic page, the number in the properties of the built executable and the
number in the installer are the same one. What is added here is what Windows
wants beside it: a four part file version, and who published the build.

A release takes its number from its tag: ``.github/workflows/release.yml`` reads
``v1.2.3`` and runs ``version.py --set 1.2.3`` before it builds, so nothing has to
be edited by hand before publishing, and the tag stays the only thing a release
is given. The same command is what the workflow commits back to the branch after
the assets are attached, so the source keeps naming the last release.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from winborder import __version__                     # noqa: E402

PRODUCT = "Winborder"
COMPANY = "Gatongone"

# Shown in the task manager and in the properties of the executable.
DESCRIPTION = "Share the PC keyboard and mouse with another device over BLE HID"

TRANSLATION = (0x0409, 1200)                          # English (US), Unicode

#: The file and the line a release rewrites. The line may end in CRLF, because the
#: file is read without newline translation.
SOURCE = ROOT / "winborder" / "__init__.py"
LINE = re.compile(r'^__version__ = "[^"]*"\r?$', re.MULTILINE)

#: What a release tag may say, once its leading v is gone.
NUMBER = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?")


def version() -> str:
    """The version every part of the build is stamped with."""
    return __version__


def set_version(number: str, path: Path = SOURCE) -> str:
    """Write ``number`` into the source, and return it.

    One line, matched once, so a release either rewrites the version or says why
    it cannot: a second ``__version__`` line would make the build stamp a number
    nobody chose.

    The file is read and written without newline translation, so a stamp leaves
    nothing behind but the number: rewriting a CRLF checkout as LF, or the other
    way round, would put a whole-file diff under a one-word commit.
    """
    global __version__
    if not NUMBER.fullmatch(number):
        raise ValueError(f"{number!r} is not a version like 1.2.3")
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as file:
        text = file.read()
    found = LINE.findall(text)
    if len(found) != 1:
        raise ValueError(f"{path} carries {len(found)} __version__ lines, not one")

    def replace(match: re.Match[str]) -> str:
        ending = "\r" if match.group(0).endswith("\r") else ""
        return f'__version__ = "{number}"{ending}'

    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(LINE.sub(replace, text))
    __version__ = number
    return number


def parts() -> tuple[int, int, int, int]:
    """The version as Windows stores it: four numbers, missing ones as zero.

    Anything a component carries after its digits is dropped, so a version
    written as ``2.1.0-rc1`` is the same 2.1.0 to Windows.
    """
    numbers = []
    for piece in __version__.split("."):
        match = re.match(r"\d+", piece)
        numbers.append(int(match.group()) if match else 0)
    numbers = (numbers + [0, 0, 0, 0])[:4]
    return numbers[0], numbers[1], numbers[2], numbers[3]


def file_version() -> str:
    """The four part version, for the file version of the executable."""
    return ".".join(str(number) for number in parts())


def copyright_line() -> str:
    """The copyright line, with the year the build was made."""
    return f"Copyright (C) {datetime.date.today().year} {COMPANY}"


def version_file(path: Path) -> Path:
    """Write the version resource PyInstaller embeds in the executable.

    PyInstaller evaluates this file, so it is one expression and the names have
    to stay exactly as they are.
    """
    file_parts = parts()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={file_parts},\n"
        f"    prodvers={file_parts},\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        f"      StringTable('{TRANSLATION[0]:04x}{TRANSLATION[1]:04x}', [\n"
        f"        StringStruct('CompanyName', '{COMPANY}'),\n"
        f"        StringStruct('FileDescription', '{DESCRIPTION}'),\n"
        f"        StringStruct('FileVersion', '{file_version()}'),\n"
        f"        StringStruct('InternalName', '{PRODUCT}'),\n"
        f"        StringStruct('LegalCopyright', '{copyright_line()}'),\n"
        f"        StringStruct('OriginalFilename', '{PRODUCT}.exe'),\n"
        f"        StringStruct('ProductName', '{PRODUCT}'),\n"
        f"        StringStruct('ProductVersion', '{version()}')\n"
        "      ])\n"
        "    ]),\n"
        f"    VarFileInfo([VarStruct('Translation', [{TRANSLATION[0]}, "
        f"{TRANSLATION[1]}])])\n"
        "  ]\n"
        ")\n",
        encoding="utf-8")
    return path


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if arguments[:1] == ["--plain"]:       # for a build script to read
        print(version())
    elif arguments[:1] == ["--set"]:
        if len(arguments) != 2:
            raise SystemExit("usage: version.py --set <major>.<minor>.<patch>")
        try:
            set_version(arguments[1])
        except ValueError as exc:
            raise SystemExit(f"::error::{exc}") from None
        print(f"version set to {arguments[1]}")
    else:
        print(f"{PRODUCT} {version()} ({file_version()}) by {COMPANY}")
