"""Tests for the build metadata.

The version and the publisher end up in the executable, in the installer and in
the name of the release assets, so they are worth checking without running a
build.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from winborder import __version__

# The build and release scripts live under .github/tools because they are only
# used when publishing, so this loads the version module by path rather than by
# package name: where the directory sits is then not something the test depends
# on, and .github is not on sys.path.
_TOOLS = Path(__file__).resolve().parents[1] / ".github" / "tools"
_spec = importlib.util.spec_from_file_location("winborder_build_version",
                                               _TOOLS / "version.py")
version = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = version
_spec.loader.exec_module(version)


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


class TestStamping(unittest.TestCase):
    """A release takes its number from its tag, so the file has to take one."""

    def setUp(self) -> None:
        original = version.__version__
        self.addCleanup(setattr, version, "__version__", original)

    def source(self, text: str = '__version__ = "0.1.0"\n') -> Path:
        """A file written as bytes, so a test can name its line endings."""
        path = Path(tempfile.mkdtemp(prefix="winborder_stamp_")) / "__init__.py"
        path.write_bytes(text.encode("utf-8"))
        return path

    def test_it_writes_the_number(self) -> None:
        path = self.source()
        self.assertEqual(version.set_version("2.5.1", path), "2.5.1")
        self.assertIn('__version__ = "2.5.1"', path.read_text(encoding="utf-8"))

    def test_it_leaves_the_rest_of_the_file_alone(self) -> None:
        path = self.source('"""Doc."""\n\nfrom __future__ import annotations\n\n'
                           '__version__ = "0.1.0"\n\n__all__ = ["__version__"]\n')
        version.set_version("2.5.1", path)
        text = path.read_text(encoding="utf-8")
        self.assertIn('"""Doc."""', text)
        self.assertIn('__all__ = ["__version__"]', text)
        self.assertEqual(text.count("__version__"), 2)

    def test_it_moves_the_version_the_build_reads(self) -> None:
        """One process may read the version after writing it."""
        version.set_version("2.5.1", self.source())
        self.assertEqual(version.version(), "2.5.1")
        self.assertEqual(version.file_version(), "2.5.1.0")

    def test_a_number_that_is_not_a_version_is_refused(self) -> None:
        path = self.source()
        for bad in ("2.5", "v2.5.1", "latest", "", "2.5.1.0", "2.5.1-"):
            with self.subTest(number=bad):
                with self.assertRaises(ValueError):
                    version.set_version(bad, path)
        self.assertIn("0.1.0", path.read_text(encoding="utf-8"))

    def test_a_second_line_is_refused(self) -> None:
        path = self.source('__version__ = "0.1.0"\n__version__ = "0.2.0"\n')
        with self.assertRaises(ValueError):
            version.set_version("2.5.1", path)

    def test_it_keeps_the_line_endings(self) -> None:
        """A stamp must not turn one line into a whole-file diff."""
        path = self.source('"""Doc."""\r\n\r\n__version__ = "0.1.0"\r\n')
        version.set_version("2.5.1", path)
        raw = path.read_bytes()
        self.assertEqual(raw.count(b"\r\n"), 3)
        self.assertEqual(raw.count(b"\n"), 3)

    def test_a_prerelease_tag_survives(self) -> None:
        path = self.source()
        version.set_version("2.5.1-rc1", path)
        self.assertIn('"2.5.1-rc1"', path.read_text(encoding="utf-8"))

    def test_the_source_itself_carries_one_line(self) -> None:
        found = version.LINE.findall(version.SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
