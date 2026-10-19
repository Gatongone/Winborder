"""Build the Windows executable.

Writes the application icon from the same shapes the window uses and the version
resource from :mod:`tools.version`, then hands the project to PyInstaller. Run it
from the repository root:

    python .github/tools/build_exe.py                 one file, no console window
    python .github/tools/build_exe.py --onedir        a folder, starts faster
    python .github/tools/build_exe.py --console       keep a console for debugging
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import struct
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# These scripts live under .github/tools, which is not a package on sys.path,
# so the sibling modules are loaded from the directory they sit in.
sys.path.insert(0, str(HERE))

import version as version_mod                     # noqa: E402
from winborder import icon, theme                 # noqa: E402

NAME = version_mod.PRODUCT
ENTRY = HERE / "exe_entry.py"
BUILD = ROOT / "build"
ICON = BUILD / f"{NAME.lower()}.ico"
VERSION_FILE = BUILD / "version_info.txt"
# PyInstaller's own files are kept out of build/ itself, and the spec out of the
# repository root: a spec left beside the entry script is picked up by the next
# build instead of the command line, which silently drops options such as the
# version resource.
WORK = BUILD / "pyinstaller"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def rgba(size: int) -> bytes:
    """One icon image as BGRA rows, top down, with an alpha channel."""
    return icon.rgba(size, theme.BRAND, "#000000")


def write_ico(path: Path) -> Path:
    """Write a real .ico, with an alpha channel and no palette."""
    images = []
    for size in SIZES:
        pixels = rgba(size)
        header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                             len(pixels), 0, 0, 0, 0)
        mask_stride = ((size + 31) // 32) * 4
        mask = b"\x00" * (mask_stride * size)
        images.append(header + pixels + mask)

    path.parent.mkdir(parents=True, exist_ok=True)
    offset = 6 + 16 * len(images)
    directory = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    for size, image in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                               len(image), offset)
        offset += len(image)
    path.write_bytes(directory + entries + b"".join(images))
    return path


def available() -> bool:
    """Whether this interpreter can run PyInstaller at all.

    The build is a subprocess of the interpreter running this script, so the
    package has to be installed in that one. Installing it into some other Python
    is the mistake worth catching, which is why the message below names the path.
    """
    try:
        return importlib.util.find_spec("PyInstaller") is not None
    except (ImportError, ValueError):   # a broken install answers with a raise
        return False


#: The dependency list: what pip installs, and therefore what the build has to
#: find importable. Reading it instead of keeping a second copy means a package
#: added there is checked, and a namespace the program starts importing is added
#: there -- the tests compare the two directions.
REQUIREMENTS = ROOT / "requirements.txt"


def runtime_modules(lines: Iterable[str] | None = None) -> tuple[str, ...]:
    """The modules the listed WinRT packages provide.

    ``winrt-Windows.Foundation.Collections`` is imported as
    ``winrt.windows.foundation.collections``, and ``winrt-runtime`` provides the
    ``winrt`` namespace itself. Anything else in the file is installed by pip
    but is not a WinRT module to probe for.
    """
    if lines is None:
        lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    modules = []
    for line in lines:
        line = line.split("#", 1)[0].strip()
        name = re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0].lower()
        if not name.startswith("winrt"):
            continue
        if name == "winrt-runtime":
            modules.append("winrt")
        else:
            modules.append("winrt." + name[len("winrt-"):])
    return tuple(modules)


#: What the program imports at run time. A build made without these succeeds and
#: produces an executable that starts and then cannot reach the radio, which is
#: the failure this whole program exists to make visible -- so it is refused here
#: rather than discovered by a user.
RUNTIME_MODULES = runtime_modules()


def missing_runtime() -> list[str]:
    """The runtime projections this interpreter cannot import."""
    missing = []
    for name in RUNTIME_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


#: Where this repository's own virtual environment keeps its interpreter.
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def other_interpreter() -> Path | None:
    """This repository's venv interpreter, when it is not the one running here.

    Two interpreters on one machine is the ordinary case: the build tool gets
    installed into whichever ``pip`` was on the path, while the program runs from
    the venv that has the runtime packages. Naming the file that is missing them
    the ones it needs ends the guessing, so both failure messages say it.
    """
    if not VENV_PYTHON.exists():
        return None
    if VENV_PYTHON.resolve() == Path(sys.executable).resolve():
        return None
    return VENV_PYTHON


def _the_other_interpreter_lines() -> str:
    """The two commands that make the venv able to build, when there is one."""
    venv = other_interpreter()
    if venv is None:
        return ""
    return ("\nThis repository has its own interpreter, which is the one the\n"
            "program runs from:\n"
            f"    {venv} -m pip install pyinstaller\n"
            f"    {venv} .github/tools/build_exe.py\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Winborder executable")
    parser.add_argument("--onedir", action="store_true",
                        help="a folder instead of a single file (starts faster)")
    parser.add_argument("--console", action="store_true",
                        help="keep a console window, for debugging")
    parser.add_argument("--clean", action="store_true", help="remove build output")
    args = parser.parse_args()

    if args.clean:
        for target in (BUILD, ROOT / "dist"):
            if target.exists():
                subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(target)],
                               check=False)
                print(f"removed {target}")
        return 0

    if not available():
        print("PyInstaller was not found. Install it with:\n"
              f"    {sys.executable} -m pip install pyinstaller"
              + _the_other_interpreter_lines(),
              file=sys.stderr)
        return 2

    missing = missing_runtime()
    if missing:
        print("The runtime packages are missing from this interpreter:\n"
              + "".join(f"    {name}\n" for name in missing)
              + "The executable would build and then fail to reach the radio.\n"
              "Install them in the interpreter that runs Winborder, or run this\n"
              f"script with that one:\n    {sys.executable} -m pip install "
              "winrt-runtime winrt-Windows.Devices.Bluetooth "
              "winrt-Windows.Devices.Bluetooth.Advertisement "
              "winrt-Windows.Devices.Bluetooth.GenericAttributeProfile "
              "winrt-Windows.Storage.Streams winrt-Windows.Foundation "
              "winrt-Windows.Foundation.Collections"
              + _the_other_interpreter_lines(),
              file=sys.stderr)
        return 2

    icon = write_ico(ICON)
    print(f"icon: {icon} ({icon.stat().st_size} bytes, {len(SIZES)} sizes)")

    version = version_mod.version_file(VERSION_FILE)
    print(f"version: {version_mod.version()} ({version_mod.file_version()}) "
          f"by {version_mod.COMPANY} -> {version}")

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--name", NAME,
        "--icon", str(icon),
        "--version-file", str(version),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(WORK),
        "--specpath", str(BUILD),
        "--paths", str(ROOT),
        "--hidden-import", "winborder.ui",
        "--hidden-import", "winborder.tray",
        # The projections import this one themselves, when a caller first reads a
        # WinRT collection: an analysis that only follows the source misses it,
        # and the frozen copy then fails to read the subscriber list at runtime.
        "--hidden-import", "winrt.windows.foundation.collections",
        # The translation tables are data files, not modules: without this the
        # window is built in English and says so in the log.
        "--add-data", f"{ROOT / 'winborder' / 'locales'}{os.pathsep}winborder/locales",
        "--onefile" if not args.onedir else "--onedir",
        "--windowed" if not args.console else "--console",
        str(ENTRY),
    ]
    print(" ".join(command[1:]))
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    artifact = ROOT / "dist" / (f"{NAME}.exe" if not args.onedir
                                else f"{NAME}/{NAME}.exe")
    if artifact.exists():
        print(f"built {artifact} ({artifact.stat().st_size / 1e6:.1f} MB)")
    copy_settings(artifact.parent)
    return 0


def copy_settings(target: Path) -> None:
    """Put the current settings beside the executable, if it has none.

    The executable looks for its settings file next to itself, so this is what
    makes a freshly built copy start with the settings that were being used.
    """
    source = ROOT / "winborder.json"
    destination = target / "winborder.json"
    if source.exists() and not destination.exists():
        shutil.copyfile(source, destination)
        print(f"settings: {destination}")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
