"""Build the Windows installer.

Needs Inno Setup 6, which is not a Python package:

    winget install JRSoftware.InnoSetup

The executable is built first if it is not there, and the version, the publisher
and the copyright line come from :mod:`tools.version`, so the installer and the
program it installs carry the same numbers. Run it from the repository root:

    python .github/tools/build_installer.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Sibling build modules, loaded from the directory they sit in: .github/tools is
# not a package on sys.path.
sys.path.insert(0, str(HERE))

import build_exe                                  # noqa: E402
import version as version_mod                     # noqa: E402

SCRIPT = ROOT / "installer" / "winborder.iss"
EXE = ROOT / "dist" / f"{version_mod.PRODUCT}.exe"

# Inno Setup installs per user by default and per machine when run as an
# administrator; both are looked for, and the command line wins.
SEARCH = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
)


def compiler(explicit: str | None = None) -> Path | None:
    """The Inno Setup command line compiler, if it can be found."""
    if explicit:
        found = Path(explicit)
        return found if found.exists() else None
    on_path = shutil.which("ISCC") or shutil.which("iscc")
    if on_path:
        return Path(on_path)
    for folder in SEARCH:
        for name in ("Inno Setup 6", "Inno Setup 5"):
            candidate = folder / name / "ISCC.exe"
            if candidate.exists():
                return candidate
    return None


def installer_path() -> Path:
    """Where the built installer lands."""
    return (ROOT / "dist" /
            f"{version_mod.PRODUCT}-{version_mod.version()}-Setup.exe")


def build(iscc: Path, exe: Path = EXE) -> Path:
    """Compile the installer around a built executable."""
    output = installer_path()
    command = [
        str(iscc),
        f"/DAppVersion={version_mod.version()}",
        f"/DAppPublisher={version_mod.COMPANY}",
        f"/DCopyrightLine={version_mod.copyright_line()}",
        f"/DSourceExe={exe}",
        f"/DSourceIcon={build_exe.ICON}",
        str(SCRIPT),
    ]
    print(" ".join(command))
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    if not output.exists():
        raise SystemExit(f"the compiler did not write {output}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Winborder installer")
    parser.add_argument("--iscc", help="path to ISCC.exe, when it is not installed "
                                       "in the usual place")
    parser.add_argument("--no-exe", action="store_true",
                        help="use the executable already in dist/")
    args = parser.parse_args()

    iscc = compiler(args.iscc)
    if iscc is None:
        print("Inno Setup was not found. Install it with:\n"
              "    winget install JRSoftware.InnoSetup", file=sys.stderr)
        return 2
    print(f"compiler: {iscc}")

    if not build_exe.ICON.exists():
        build_exe.write_ico(build_exe.ICON)

    if not args.no_exe:
        if build_exe.main() != 0:
            return 1
    if not EXE.exists():
        print(f"{EXE} is missing; run .github/tools/build_exe.py first", file=sys.stderr)
        return 2

    output = build(iscc)
    print(f"installer: {output} ({output.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
