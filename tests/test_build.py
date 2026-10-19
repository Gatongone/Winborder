"""Tests for the build scripts that do not need a build.

The two scripts in ``.github/tools`` only run when publishing, so they are not on
``sys.path``: they are loaded by path here, the same way the version test does
it. What can be checked without PyInstaller and without Inno Setup is the part
that answers for them, because a missing tool is the first thing a build hits:
the message has to name the tool, the interpreter and the command, or the reader
is left with a traceback that looks like a broken script.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

_TOOLS = Path(__file__).resolve().parents[1] / ".github" / "tools"


def _load(name: str):
    """Import a build script by path, without putting its directory on sys.path."""
    spec = importlib.util.spec_from_file_location(f"winborder_build_{name}",
                                                  _TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_exe = _load("build_exe")
bootstrap = _load("build")


class TestMissingTools(unittest.TestCase):
    def test_a_missing_pyinstaller_is_named_not_traced(self) -> None:
        """The build shells out to PyInstaller, so its absence is a build answer."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(build_exe, "available", return_value=False), \
                mock.patch.object(sys, "argv", ["build_exe.py"]), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = build_exe.main()
        self.assertEqual(code, 2)
        self.assertIn("-m pip install pyinstaller", err.getvalue())
        # The interpreter is the whole point: installing into another one
        # changes nothing, and looks exactly like following the instructions.
        self.assertIn(sys.executable, err.getvalue())

    def test_the_question_is_about_this_interpreter(self) -> None:
        self.assertEqual(build_exe.available(),
                         importlib.util.find_spec("PyInstaller") is not None)

    def test_a_build_without_the_radio_packages_is_refused(self) -> None:
        """Built without them, the executable starts and cannot reach the radio.

        That is the failure this program exists to make visible, so a build
        configuration that would produce it is worth stopping before the file
        exists: nothing about the finished artifact says it is the wrong one.
        """
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(build_exe, "available", return_value=True), \
                mock.patch.object(build_exe, "missing_runtime",
                                  return_value=["winrt.windows.foundation."
                                                "collections"]), \
                mock.patch.object(sys, "argv", ["build_exe.py"]), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = build_exe.main()
        self.assertEqual(code, 2)
        self.assertIn("winrt.windows.foundation.collections", err.getvalue())
        self.assertIn("fail to reach the radio", err.getvalue())

    def test_the_refusal_names_the_interpreter_that_has_the_packages(self) -> None:
        """Two interpreters is the ordinary case, so the way out is spelled out."""
        venv = Path(r"E:\project\.venv\Scripts\python.exe")
        err = io.StringIO()
        with mock.patch.object(build_exe, "available", return_value=True), \
                mock.patch.object(build_exe, "missing_runtime",
                                  return_value=["winrt.windows.foundation."
                                                "collections"]), \
                mock.patch.object(build_exe, "other_interpreter",
                                  return_value=venv), \
                mock.patch.object(sys, "argv", ["build_exe.py"]), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            build_exe.main()
        self.assertIn(str(venv), err.getvalue())
        self.assertIn("-m pip install pyinstaller", err.getvalue())

    def test_one_interpreter_is_not_offered_itself(self) -> None:
        """The hint is for the other one; a venv that is this process says nothing."""
        with mock.patch.object(build_exe, "VENV_PYTHON", Path(sys.executable)):
            self.assertIsNone(build_exe.other_interpreter())

    def test_every_projection_the_program_imports_is_checked_for(self) -> None:
        """The checked list has to follow the code, in every module of it.

        A namespace imported anywhere is a namespace the build must have, and it
        arrives through ``requirements.txt``: this is the direction that catches
        a new import nobody added to the list, which is the fault that shipped
        a release that could not read a subscriber.
        """
        source = Path(build_exe.__file__).resolve().parents[2] / "winborder"
        imported = set()
        for module in sorted(source.glob("*.py")):
            for line in module.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(("from winrt.", "import winrt.")):
                    imported.add(line.split()[1].split(" import")[0])
        self.assertTrue(set(build_exe.RUNTIME_MODULES) >= imported,
                        imported - set(build_exe.RUNTIME_MODULES))


class TestBootstrap(unittest.TestCase):
    """The one command a fresh clone runs.

    These are about whose interpreter does the work: a build made with the system
    Python packages a Python that has none of the radio bindings, and the result
    starts and cannot reach the radio. The bootstrap exists so that cannot happen,
    so the tests are about the environment it prepares and the interpreter it
    hands the build to.
    """

    def test_the_build_runs_in_the_environment_it_set_up(self) -> None:
        python = Path(r"E:\project\.venv\Scripts\python.exe")
        calls: list[list[str]] = []

        def record(command, **_kwargs):
            calls.append(list(command))
            return mock.Mock(returncode=0)

        with mock.patch.object(bootstrap, "PYTHON", python), \
                mock.patch.object(bootstrap, "ready", return_value=True), \
                mock.patch.object(bootstrap.subprocess, "run", side_effect=record), \
                contextlib.redirect_stdout(io.StringIO()):
            code = bootstrap.main(["--console"])
        self.assertEqual(code, 0)
        build = calls[-1]
        self.assertEqual(build[0], str(python), "the venv builds, not this process")
        self.assertIn(str(bootstrap.BUILD_EXE), build)
        self.assertIn("--console", build)

    def test_a_fresh_environment_is_created_and_filled(self) -> None:
        python = Path(r"E:\project\.venv\Scripts\python.exe")
        calls: list[list[str]] = []

        def record(command, **_kwargs):
            calls.append(list(command))
            return mock.Mock(returncode=0)

        with mock.patch.object(bootstrap, "PYTHON", python), \
                mock.patch.object(bootstrap, "create", return_value=0) as created, \
                mock.patch.object(bootstrap, "ready", return_value=False), \
                mock.patch.object(bootstrap.subprocess, "run", side_effect=record), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.setup(), 0)
        created.assert_called_once()
        install = calls[-1]
        self.assertIn("-r", install)
        self.assertIn(str(bootstrap.REQUIREMENTS), install)
        self.assertIn("pyinstaller", install)

    def test_the_check_list_is_read_from_the_dependency_file(self) -> None:
        """One source of truth: what pip installs is what the build checks for.

        Keeping a second copy of the list is how the release came to ship without
        a projection that the source imports, so the list is derived instead.
        """
        modules = build_exe.runtime_modules([
            "# a comment",
            "",
            "winrt-runtime",
            "winrt-Windows.Devices.Bluetooth",
            "winrt-Windows.Foundation.Collections>=3",
            "pyinstaller",
        ])
        self.assertEqual(modules, (
            "winrt",
            "winrt.windows.devices.bluetooth",
            "winrt.windows.foundation.collections",
        ))

    def test_a_missing_inno_setup_is_explained_not_installed(self) -> None:
        err = io.StringIO()
        with mock.patch.object(bootstrap.build_installer, "compiler",
                               return_value=None), \
                mock.patch.object(bootstrap.subprocess, "run") as run, \
                contextlib.redirect_stderr(err):
            code = bootstrap.ensure_inno(install_it=False)
        self.assertEqual(code, 2)
        self.assertIn("winget install JRSoftware.InnoSetup", err.getvalue())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
