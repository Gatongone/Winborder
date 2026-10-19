"""Build Winborder from a checkout that has never been built.

    python .github/tools/build.py                the executable, in dist\\
    python .github/tools/build.py --installer    and the Setup.exe

The build needs packages the machine may not have, and it needs them in the
interpreter PyInstaller runs in. So this creates ``.venv`` beside the source
tree, installs ``requirements.txt`` and PyInstaller into it, and runs the real
build with that interpreter. A fresh clone and a machine that has been building
for months then take the same path, and the machine's own Python is not touched.

``build_exe.py`` and ``build_installer.py`` are still the programs that do the
work; they expect the interpreter running them to have the packages already,
which is what ``.venv`` is for. The installer also needs Inno Setup 6, which is
an application rather than a package: ``--install-inno`` installs it with winget.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import build_exe                                 # noqa: E402
import build_installer                           # noqa: E402

VENV = ROOT / ".venv"
PYTHON = VENV / "Scripts" / "python.exe"
REQUIREMENTS = ROOT / "requirements.txt"
BUILD_EXE = HERE / "build_exe.py"
BUILD_INSTALLER = HERE / "build_installer.py"
INNO = ["winget", "install", "--id", "JRSoftware.InnoSetup", "-e",
        "--accept-source-agreements", "--accept-package-agreements"]


def imports() -> list[str]:
    """Every module the build needs from its interpreter.

    PyInstaller is the build tool; the rest is the program's own run time, which
    has to be importable where the freezing happens or the result cannot reach
    the radio.
    """
    return ["PyInstaller", *build_exe.RUNTIME_MODULES]


def ready(python: Path) -> bool:
    """Whether that interpreter can run the build without installing anything."""
    if not python.exists():
        return False
    script = "\n".join(f"import {name}" for name in imports())
    done = subprocess.run([str(python), "-c", script],
                          capture_output=True, cwd=str(ROOT))
    return done.returncode == 0


def create() -> int:
    """Make the virtual environment, from the interpreter running this script."""
    print(f"creating {VENV}")
    done = subprocess.run([sys.executable, "-m", "venv", str(VENV)], cwd=str(ROOT))
    if done.returncode != 0:
        print("the virtual environment could not be created", file=sys.stderr)
    return done.returncode


def ensure_pip(python: Path) -> int:
    """A new environment can arrive without pip, which is not a build fault."""
    if subprocess.run([str(python), "-m", "pip", "--version"],
                      capture_output=True).returncode == 0:
        return 0
    print(f"installing pip into {VENV}")
    return subprocess.run([str(python), "-m", "ensurepip", "--upgrade"],
                          cwd=str(ROOT)).returncode


def install() -> int:
    """Put the requirements and the build tool into the environment."""
    print(f"installing the build requirements into {VENV}")
    command = [str(PYTHON), "-m", "pip", "install",
               "--disable-pip-version-check", "--no-input",
               "-r", str(REQUIREMENTS), "pyinstaller"]
    done = subprocess.run(command, cwd=str(ROOT))
    if done.returncode != 0:
        print("the build requirements could not be installed; this needs the "
              "package index to be reachable once", file=sys.stderr)
    return done.returncode


def setup() -> int:
    """Leave the environment able to build, saying nothing when it already can."""
    if not PYTHON.exists():
        code = create()
        if code != 0:
            return code
    code = ensure_pip(PYTHON)
    if code != 0:
        return code
    if ready(PYTHON):
        return 0
    return install()


def ensure_inno(install_it: bool) -> int:
    """Make Inno Setup available, or say how to get it."""
    if build_installer.compiler() is not None:
        return 0
    if not install_it:
        print("Inno Setup 6 is needed for the installer, and it is an "
              "application rather than a package:\n"
              "    winget install JRSoftware.InnoSetup\n"
              "or let this script do it:\n"
              f"    {Path(sys.executable).name} .github/tools/build.py "
              "--installer --install-inno",
              file=sys.stderr)
        return 2
    print(" ".join(INNO))
    code = subprocess.run(INNO, cwd=str(ROOT)).returncode
    if code != 0:
        return code
    if build_installer.compiler() is None:
        # winget updates the user's PATH, which this process has already read:
        # the usual install locations are searched as well, so this only happens
        # when it went somewhere else.
        print("Inno Setup installed, but ISCC.exe was not found; build the "
              "installer with --iscc <path> instead", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Winborder from a checkout that has never been built")
    parser.add_argument("--console", action="store_true",
                        help="keep a console window, for debugging")
    parser.add_argument("--onedir", action="store_true",
                        help="a folder instead of a single file (starts faster)")
    parser.add_argument("--installer", action="store_true",
                        help="also build the Setup.exe")
    parser.add_argument("--install-inno", action="store_true",
                        help="install Inno Setup with winget when it is missing")
    args = parser.parse_args(argv)

    if os.name != "nt":
        print("Winborder builds on Windows only", file=sys.stderr)
        return 2

    code = setup()
    if code != 0:
        return code

    command = [str(PYTHON), str(BUILD_EXE)]
    if args.console:
        command.append("--console")
    if args.onedir:
        command.append("--onedir")
    code = subprocess.run(command, cwd=str(ROOT)).returncode
    if code != 0 or not args.installer:
        return code

    code = ensure_inno(args.install_inno)
    if code != 0:
        return code
    return subprocess.run([str(PYTHON), str(BUILD_INSTALLER), "--no-exe"],
                          cwd=str(ROOT)).returncode


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
