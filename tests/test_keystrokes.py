"""Tests for turning text into keystrokes.

The link carries key usages, so a character exists only if a US layout can type
it. These tests pin that mapping and the accounting for what it cannot type,
because the failure they prevent is a paste that silently types two thirds of a
sentence.
"""

from __future__ import annotations

import unittest

from winborder import keymap, keystrokes


def usages(plan: keystrokes.Plan) -> list[tuple[int, bool]]:
    return [(stroke.usage, stroke.shifted) for stroke in plan.strokes]


class TestLayout(unittest.TestCase):
    def test_letters_are_their_own_usage_with_shift_for_the_capital(self) -> None:
        self.assertEqual(usages(keystrokes.plan("aA")), [(0x04, False), (0x04, True)])
        self.assertEqual(usages(keystrokes.plan("zZ")), [(0x1D, False), (0x1D, True)])

    def test_the_digit_row_is_one_key_per_digit(self) -> None:
        self.assertEqual(usages(keystrokes.plan("10")), [(0x1E, False), (0x27, False)])
        self.assertEqual(usages(keystrokes.plan("!0")), [(0x1E, True), (0x27, False)])
        self.assertEqual(usages(keystrokes.plan(")")), [(0x27, True)])

    def test_a_punctuation_key_types_both_its_characters(self) -> None:
        for plain, shifted in (("-", "_"), ("=", "+"), ("[", "{"), ("]", "}"),
                               ("\\", "|"), (";", ":"), ("'", '"'), ("`", "~"),
                               (",", "<"), (".", ">"), ("/", "?")):
            with self.subTest(pair=plain + shifted):
                (first, first_shift), (second, second_shift) = usages(
                    keystrokes.plan(plain + shifted))
                self.assertEqual(first, second, "the same key serves both")
                self.assertFalse(first_shift)
                self.assertTrue(second_shift)

    def test_only_the_letters_digits_and_punctuation_of_a_us_layout_are_known(self) -> None:
        # 52 letters, 10 digits, 32 punctuation, space, Enter and Tab.
        self.assertEqual(len(keystrokes.US_LAYOUT), 97)

    def test_every_usage_is_a_key_a_us_layout_has(self) -> None:
        known = {usage for _vk, usage in keymap.KEY_NAMES.values()}
        for char, (usage, shift) in keystrokes.US_LAYOUT.items():
            with self.subTest(char=char):
                self.assertIn(usage, known, "not a key any layout names")
                self.assertTrue(0x04 <= usage <= 0x38)
                self.assertIn(shift, (True, False))

    def test_only_shift_is_ever_held(self) -> None:
        for stroke in keystrokes.plan("ABC!123-").strokes:
            with self.subTest(stroke=stroke):
                self.assertIn(stroke.modifiers, (0, keymap.MOD_LEFT_SHIFT))


class TestPlan(unittest.TestCase):
    def test_a_line_break_is_enter_and_a_tab_is_tab(self) -> None:
        self.assertEqual(usages(keystrokes.plan("a\nb")),
                         [(0x04, False), (0x28, False), (0x05, False)])
        self.assertEqual(usages(keystrokes.plan("\t")), [(0x2B, False)])

    def test_a_windows_line_break_is_one_enter(self) -> None:
        """The clipboard holds CRLF, and Enter is one key."""
        self.assertEqual(usages(keystrokes.plan("a\r\nb")),
                         [(0x04, False), (0x28, False), (0x05, False)])
        self.assertEqual(usages(keystrokes.plan("a\rb")), usages(keystrokes.plan("a\nb")))

    def test_text_a_us_layout_cannot_type_is_counted_and_named(self) -> None:
        plan = keystrokes.plan("a中b")
        self.assertEqual(usages(plan), [(0x04, False), (0x05, False)])
        self.assertEqual(plan.skipped, 1)
        self.assertEqual(plan.examples, ("中",))

    def test_an_emoji_is_skipped_rather_than_crashing(self) -> None:
        plan = keystrokes.plan("🙂ok")
        self.assertEqual(plan.skipped, 1)
        self.assertEqual(len(plan.strokes), 2)

    def test_the_limit_stops_typing_and_is_reported(self) -> None:
        plan = keystrokes.plan("abcd", limit=2)
        self.assertEqual(len(plan.strokes), 2)
        self.assertEqual(plan.truncated, 2)

    def test_a_limit_of_zero_types_nothing(self) -> None:
        plan = keystrokes.plan("abcd", limit=0)
        self.assertEqual(plan.strokes, ())
        self.assertEqual(plan.truncated, 4)
        self.assertFalse(plan)

    def test_only_the_first_few_skipped_characters_are_named(self) -> None:
        plan = keystrokes.plan("中文日本語한국어")
        self.assertEqual(plan.skipped, 8)
        self.assertEqual(len(plan.examples), 5)

    def test_an_empty_clipboard_is_an_empty_plan(self) -> None:
        self.assertFalse(keystrokes.plan(""))


if __name__ == "__main__":
    unittest.main()
