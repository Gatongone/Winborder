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
import os
import shutil
import struct
import subprocess
import sys
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
