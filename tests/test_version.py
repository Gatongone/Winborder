"""Tests for the build metadata.

The version and the publisher end up in the executable, in the installer and in
the name of the release assets, so they are worth checking without running a
build.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import version
from winborder import __version__


class TestVersion(unittest.TestCase):
    def test_the_source_is_the_only_version(self) -> None:
        self.assertEqual(version.version(), __version__)

    def test_windows_gets_four_numbers(self) -> None:
        parts = version.parts()
        self.assertEqual(len(parts), 4)
        for number in parts:
            with self.subTest(number=number):
                self.assertIsInstance(number, int)
                self.assertGreaterEqual(number, 0)
        self.assertEqual(version.file_version(), ".".join(str(n) for n in parts))

    def test_a_missing_component_becomes_zero(self) -> None:
        original = version.__version__
        version.__version__ = "2.1"
        self.addCleanup(setattr, version, "__version__", original)
        self.assertEqual(version.parts(), (2, 1, 0, 0))

    def test_a_suffix_is_dropped(self) -> None:
        original = version.__version__
        version.__version__ = "2.1.0-rc1"
        self.addCleanup(setattr, version, "__version__", original)
        self.assertEqual(version.parts(), (2, 1, 0, 0))

    def test_the_publisher_is_named(self) -> None:
        self.assertEqual(version.COMPANY, "Gatongone")
        self.assertIn(version.COMPANY, version.copyright_line())
        self.assertIn(version.COMPANY, version.DESCRIPTION + version.PRODUCT
                      + version.copyright_line())


class TestVersionResource(unittest.TestCase):
    """PyInstaller evaluates the file, so it has to be one valid expression."""

    def written(self) -> str:
        directory = tempfile.mkdtemp(prefix="winborder_version_")
        return version.version_file(Path(directory) / "version_info.txt").read_text(
            encoding="utf-8")

    def test_it_names_the_right_call(self) -> None:
        text = self.written()
        self.assertTrue(text.startswith("VSVersionInfo("))
        for name in ("CompanyName", "FileVersion", "ProductVersion",
                     "LegalCopyright", "ProductName", "OriginalFilename"):
            with self.subTest(name=name):
                self.assertIn(f"StringStruct('{name}'", text)

    def test_it_carries_the_version_and_the_publisher(self) -> None:
        text = self.written()
        self.assertIn(f"filevers={version.parts()}", text)
        self.assertIn(f"prodvers={version.parts()}", text)
        self.assertIn(f"'{version.file_version()}'", text)
        self.assertIn(f"'{version.version()}'", text)
        self.assertIn(version.COMPANY, text)

    def test_it_is_evaluable(self) -> None:
        """The names PyInstaller supplies are stubbed in, the rest is Python."""
        class Stub:
            def __init__(self, *args, **kwargs) -> None:
                self.args = args
                self.kwargs = kwargs

        text = self.written()
        namespace = {name: type(name, (Stub,), {})
                     for name in ("VSVersionInfo", "FixedFileInfo", "StringFileInfo",
                                  "StringTable", "StringStruct", "VarFileInfo",
                                  "VarStruct")}
        built = eval(text, namespace)                 # noqa: S307 - our own file
        self.assertIsInstance(built, namespace["VSVersionInfo"])


if __name__ == "__main__":
    unittest.main()
