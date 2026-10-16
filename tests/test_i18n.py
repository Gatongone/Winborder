"""Tests for the interface languages.

Every string the window can show has to be translated in every language: a
missing entry is not an error at run time, it just shows English, which is
exactly the kind of thing that goes unnoticed.
"""

from __future__ import annotations

import json
import re
import tempfile
import textwrap
import unittest
from pathlib import Path

from winborder import cli, config, i18n, startup, theme, ui

PACKAGE = Path(ui.__file__).parent

# Any call that translates a literal, so a string added to the window is found
# without the test having to know where it was added.
CALL = re.compile(r"i18n\.t\(\s*\"((?:[^\"\\]|\\.)*)\"\s*\)")

# Text that reaches the translator through a variable rather than a literal, so
# the scan above cannot see it.
INDIRECT = set(ui.VALUE_LABELS.values()) | {
    "pc", "target", "up", "down", "written", "bad",     # the status values
    "executable",                                       # startup.describe
}


def source_strings() -> set[str]:
    """Every literal handed to the translator anywhere in the package."""
    found: set[str] = set(INDIRECT)
    for path in sorted(PACKAGE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        found.update(match.group(1) for match in CALL.finditer(text))
    return found


def table_strings() -> set[str]:
    """Every string the tables decide the text of."""
    found: set[str] = set()
    for field in ui.FIELDS:
        found.add(field.label)
        if field.hint:
            found.add(field.hint)
    for _key, title, _icon, text, groups in ui.PAGES:
        found.update((title, text))
        for group, _rows in groups:
            found.add(group)
    for rows in (ui.STATUS_ROWS, ui.ABOUT_ROWS):
        for _key, title, description in rows:
            found.update((title, description))
    return found


class TestTables(unittest.TestCase):
    def test_the_offered_languages_are_the_translated_ones(self) -> None:
        self.assertIn(i18n.DEFAULT_LANGUAGE, i18n.codes())
        for code in i18n.codes():
            with self.subTest(code=code):
                if code == i18n.DEFAULT_LANGUAGE:
                    self.assertNotIn(code, i18n.TRANSLATIONS,
                                     "English is the source, not a table")
                else:
                    self.assertIn(code, i18n.TRANSLATIONS)

    def test_every_language_translates_the_same_strings(self) -> None:
        reference = set(i18n.TRANSLATIONS["zh"])
        for code, table in i18n.TRANSLATIONS.items():
            with self.subTest(code=code):
                self.assertEqual(set(table), reference,
                                 "the tables have to cover the same strings")

    def test_no_translation_is_blank(self) -> None:
        for code, table in i18n.TRANSLATIONS.items():
            for source, text in table.items():
                with self.subTest(code=code, source=source):
                    self.assertTrue(text.strip())

    def test_placeholders_survive_translation(self) -> None:
        """A message is formatted after it is translated."""
        for code, table in i18n.TRANSLATIONS.items():
            for source, text in table.items():
                wanted = set(re.findall(r"\{(\w+)", source))
                got = set(re.findall(r"\{(\w+)", text))
                if not wanted:
                    continue
                with self.subTest(code=code, source=source):
                    self.assertEqual(got, wanted,
                                     "the translated message names other fields")

    def test_every_string_of_the_window_is_translated(self) -> None:
        wanted = source_strings() | table_strings()
        self.assertGreater(len(wanted), 80)
        for code, table in i18n.TRANSLATIONS.items():
            missing = sorted(wanted - set(table))
            with self.subTest(code=code):
                self.assertEqual(missing, [], "untranslated interface text")

    def test_the_tables_carry_nothing_that_is_gone(self) -> None:
        """A string no longer in the window is a translation left behind."""
        used = source_strings() | table_strings()
        for code, table in i18n.TRANSLATIONS.items():
            unused = sorted(set(table) - used)
            with self.subTest(code=code):
                self.assertEqual(unused, [])


class TestLookup(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_english_needs_no_table(self) -> None:
        i18n.set_language("en")
        self.assertEqual(i18n.t("Status"), "Status")

    def test_a_translation_is_used(self) -> None:
        i18n.set_language("ja")
        self.assertEqual(i18n.t("Status"), "状態")

    def test_unknown_text_is_returned_unchanged(self) -> None:
        i18n.set_language("ko")
        self.assertEqual(i18n.t("not a string of this window"),
                         "not a string of this window")

    def test_an_unknown_language_leaves_english(self) -> None:
        self.assertEqual(i18n.set_language("klingon"), i18n.DEFAULT_LANGUAGE)
        self.assertEqual(i18n.language(), i18n.DEFAULT_LANGUAGE)
        self.assertEqual(i18n.set_language(None), i18n.DEFAULT_LANGUAGE)

    def test_names_are_native_and_reversible(self) -> None:
        for code in i18n.codes():
            with self.subTest(code=code):
                name = i18n.native_name(code)
                self.assertEqual(i18n.code_for_name(name), code)
                self.assertEqual(i18n.name_for_code(code), name)
        self.assertIsNone(i18n.code_for_name("Klingon"))


class TestChoiceLabels(unittest.TestCase):
    """A dropdown shows words; the value behind it stays as the file has it."""

    def tearDown(self) -> None:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_labels_line_up_with_values(self) -> None:
        for field in ui.FIELDS:
            if field.kind != "choice":
                continue
            with self.subTest(field=field.name):
                labels = ui.choice_labels(field)
                self.assertEqual(len(labels), len(field.choices))
                for label, value in zip(labels, field.choices):
                    self.assertEqual(ui.choice_value(field, label), value)

    def test_the_side_is_shown_in_the_language(self) -> None:
        field = ui.FIELDS_BY_NAME["side"]
        i18n.set_language("zh")
        self.assertEqual(ui.choice_labels(field),
                         tuple(i18n.t(word) for word in ("Left", "Right", "Top",
                                                         "Bottom")))
        self.assertEqual(ui.choice_value(field, i18n.t("Bottom")), "bottom")

    def test_the_language_names_are_native_in_every_language(self) -> None:
        field = ui.FIELDS_BY_NAME[config.LOCALE_FIELD]
        for code in i18n.codes():
            with self.subTest(code=code):
                i18n.set_language(code)
                self.assertEqual(ui.choice_labels(field),
                                 tuple(i18n.native_name(name)
                                       for name in i18n.codes()))

    def test_a_label_that_stands_for_nothing_is_rejected(self) -> None:
        field = ui.FIELDS_BY_NAME["side"]
        self.assertIsNone(ui.choice_value(field, "Sideways"))
        self.assertIsNone(ui.choice_value(field, None))


class TestLanguageSetting(unittest.TestCase):
    """The language travels in the settings file like anything else."""

    def tearDown(self) -> None:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_the_default_is_english(self) -> None:
        self.assertEqual(config.defaults()[config.LOCALE_FIELD],
                         i18n.DEFAULT_LANGUAGE)
        self.assertEqual(config.complete({})[config.LOCALE_FIELD], "en")

    def test_it_survives_a_round_trip(self) -> None:
        directory = tempfile.mkdtemp(prefix="winborder_lang_")
        path = Path(directory) / "winborder.json"
        settings = config.defaults()
        settings[config.LOCALE_FIELD] = "zh"
        config.write(path, settings)
        self.assertEqual(config.read(path)[config.LOCALE_FIELD], "zh")

    def test_a_language_that_does_not_exist_is_rejected(self) -> None:
        directory = tempfile.mkdtemp(prefix="winborder_lang_")
        path = Path(directory) / "winborder.json"
        path.write_text(json.dumps({config.LOCALE_FIELD: "klingon"}),
                        encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            config.read(path)

    def test_it_is_shown_on_the_generic_page(self) -> None:
        self.assertIn(config.LOCALE_FIELD, ui.FIELDS_BY_NAME)
        pages = {key: groups for key, _t, _i, _d, groups in ui.PAGES}
        shown = [name for _group, rows in pages["generic"]
                 for row in rows for name in row]
        self.assertIn(config.LOCALE_FIELD, shown)


class TestPageOrder(unittest.TestCase):
    def test_generic_sits_under_status(self) -> None:
        self.assertEqual([key for key, *_rest in ui.PAGES][:2],
                         ["status", "generic"])

    def test_every_field_is_shown_once(self) -> None:
        """Every setting is on a page, as a row or as the header switch."""
        shown = [name for _key, _t, _i, _d, groups in ui.PAGES
                 for _group, rows in groups for row in rows for name in row]
        self.assertEqual(len(shown), len(set(shown)), "a field is shown twice")
        self.assertEqual(sorted(set(shown) | set(ui.PAGE_SWITCHES.values())),
                         sorted(field.name for field in ui.FIELDS))


class TestFonts(unittest.TestCase):
    """A language is drawn with a family that has its glyphs."""

    def test_every_language_names_a_family(self) -> None:
        for code in i18n.codes():
            with self.subTest(code=code):
                self.assertIn(code, theme.FAMILIES)
                self.assertTrue(theme.FAMILIES[code][-1] == "Segoe UI")

    def test_the_family_is_chosen_without_a_display(self) -> None:
        class Broken:
            def winfo_fpixels(self, _what):
                raise RuntimeError("no display")

        for code in i18n.codes():
            with self.subTest(code=code):
                self.assertIn(theme.use_language(code, Broken()),
                              theme.FAMILIES[code])

    def test_the_monospaced_font_is_left_alone(self) -> None:
        """The log and the columns of numbers beside it stay aligned."""
        class Broken:
            def winfo_fpixels(self, _what):
                raise RuntimeError("no display")

        for code in i18n.codes():
            with self.subTest(code=code):
                theme.use_language(code, Broken())
                self.assertEqual(theme.MONO_FONT[0], "Consolas")
        theme.use_language("en", Broken())


class TestConsoleStrings(unittest.TestCase):
    def test_the_command_line_errors_are_translated(self) -> None:
        i18n.set_language("zh")
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)
        source = textwrap.dedent(
            Path(cli.__file__).read_text(encoding="utf-8"))
        self.assertIn('i18n.t("settings file not found: {path}")', source)

    def test_the_startup_facts_are_translated(self) -> None:
        facts = startup.describe()
        self.assertEqual(set(facts), {"version", "runtime"})
        self.assertEqual(facts["runtime"], i18n.t(facts["runtime"]))


class StubService:
    """Enough of the service for the window to be built."""

    def status(self) -> dict[str, object]:
        return {"mode": "pc", "side": "bottom", "cursor": (0.5, 1.0),
                "pointer": (0.5, 0.5), "travel": 0.0, "frames": 0, "written": 0,
                "bad": 0, "connected": True}

    def apply_config(self, config) -> None:
        pass

    def request_stop(self) -> None:
        pass

    def run(self) -> None:
        pass


class TestLanguageSwitch(unittest.TestCase):
    """Choosing a language in the window shows it, without a restart."""

    def setUp(self) -> None:
        import tkinter as tk

        self.directory = tempfile.mkdtemp(prefix="winborder_switch_")
        self.path = str(Path(self.directory) / "winborder.json")
        try:
            self.window = ui.SettingsWindow(StubService(), {"language": "en"},
                                            self.path)
        except tk.TclError as exc:            # no display available
            self.skipTest(f"no display: {exc}")
        self.addCleanup(self.window.root.destroy)
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)
        # The startup entry belongs to whoever is running the tests.
        self.window._windows_settings = config.app_settings(self.window.settings)

    def choose(self, code: str) -> None:
        """Pick a language the way the dropdown does."""
        self.window._variables[config.LOCALE_FIELD].set(i18n.native_name(code))
        self.window._commit()

    def test_the_window_is_shown_in_the_new_language(self) -> None:
        self.choose("ja")
        self.assertEqual(i18n.language(), "ja")
        self.assertEqual(self.window.sidebar.items["generic"].label.cget("text"),
                         i18n.TRANSLATIONS["ja"]["Generic"])
        self.assertEqual(self.window.message.cget("text"),
                         i18n.TRANSLATIONS["ja"]["Saved"])

    def test_the_choice_is_written_down(self) -> None:
        self.choose("ko")
        self.assertEqual(json.loads(Path(self.path).read_text(encoding="utf-8"))
                         [config.LOCALE_FIELD], "ko")
        self.assertEqual(self.window.settings[config.LOCALE_FIELD], "ko")

    def test_the_dropdown_still_shows_the_choice(self) -> None:
        self.choose("ru")
        self.assertEqual(self.window._variables[config.LOCALE_FIELD].get(),
                         i18n.native_name("ru"))

    def test_going_back_to_english(self) -> None:
        self.choose("zh")
        self.choose("en")
        self.assertEqual(self.window.sidebar.items["generic"].label.cget("text"),
                         "Generic")
        self.assertEqual(i18n.language(), "en")
