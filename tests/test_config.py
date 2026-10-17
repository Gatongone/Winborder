"""Tests for the settings file and the key tables it is written against."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unittest
from pathlib import Path

from winborder import cli, config, hid, keymap, model


def write(settings: dict) -> Path:
    directory = tempfile.mkdtemp(prefix="winborder_config_")
    path = Path(directory) / "winborder.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


class TestKeyTables(unittest.TestCase):
    def test_every_name_round_trips(self) -> None:
        for name, (vk, usage) in keymap.KEY_NAMES.items():
            with self.subTest(name=name):
                self.assertEqual(keymap.vk_from_name(name), vk)
                self.assertEqual(keymap.usage_from_name(name), usage)
                self.assertEqual(keymap.describe_vk(vk), name)

    def test_numbers_are_accepted_as_virtual_keys(self) -> None:
        self.assertEqual(keymap.vk_from_name("0x70"), 0x70)
        self.assertEqual(keymap.vk_from_name("112"), 112)

    def test_unknown_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            keymap.vk_from_name("Nope")
        with self.assertRaises(ValueError):
            keymap.usage_from_name("Nope")

    def test_modifier_keys_are_bits_not_slots(self) -> None:
        for name in ("LeftCtrl", "RightShift", "LeftAlt", "RightWin"):
            vk, _ = keymap.KEY_NAMES[name]
            with self.subTest(name=name):
                self.assertIn(vk, keymap.VK_TO_MODIFIER)
                self.assertNotIn(vk, keymap.VK_TO_HID)
        self.assertEqual(keymap.VK_TO_MODIFIER[0xA2], keymap.MOD_LEFT_CTRL)
        self.assertEqual(keymap.VK_TO_MODIFIER[0xA3], keymap.MOD_RIGHT_CTRL)

    def test_modifier_bit_only_for_modifiers(self) -> None:
        self.assertEqual(keymap.modifier_bit(keymap.usage_from_name("LeftShift")), 0x02)
        self.assertIsNone(keymap.modifier_bit(keymap.usage_from_name("A")))


class TestSettingsFile(unittest.TestCase):
    def test_defaults_cover_every_setting(self) -> None:
        written = config.defaults()
        for field in dataclasses.fields(model.Config):
            self.assertIn(field.name, written)

    def test_defaults_carry_no_link_settings(self) -> None:
        """The port, baud rate and transport went with the serial bridge."""
        written = config.defaults()
        for name in ("port", "baudrate", "transport"):
            with self.subTest(name=name):
                self.assertNotIn(name, written)

    def test_written_defaults_load_back_as_defaults(self) -> None:
        path = write(config.defaults())
        settings = config.read(path)
        self.assertEqual(config.build(settings), model.Config())

    def test_keys_are_written_by_name(self) -> None:
        written = config.defaults()
        self.assertEqual(written["panic_keys"], ["F1"])
        self.assertEqual(written["toggle_edge_keys"], ["F2"])

    def test_values_are_applied(self) -> None:
        path = write({"side": "top", "pullback_distance": 250, "accel": 0.25,
                      "panic_keys": ["F12", "LeftCtrl"]})
        built = config.build(config.read(path))
        self.assertIs(built.side, model.Side.TOP)
        self.assertEqual(built.pullback_distance, 250)
        self.assertEqual(built.accel, 0.25)
        self.assertEqual(built.panic_keys,
                         (keymap.vk_from_name("F12"), keymap.VK_CTRL_LEFT))

    def test_remap_is_built_from_names(self) -> None:
        path = write({"remap": {"CapsLock": "Escape"}})
        built = config.build(config.read(path))
        self.assertEqual(built.remap,
                         ((keymap.vk_from_name("CapsLock"),
                           keymap.usage_from_name("Escape")),))

    def test_unknown_setting_is_rejected(self) -> None:
        path = write({"pullback_distanse": 300})
        with self.assertRaises(config.ConfigError):
            config.read(path)

    def test_wrong_type_is_rejected(self) -> None:
        for settings in ({"pullback_distance": "300"}, {"pullback_exit": "yes"},
                         {"accel": True}, {"sensitivity": "fast"}):
            with self.subTest(settings=settings):
                with self.assertRaises(config.ConfigError):
                    config.build(config.read(write(settings)))

    def test_bad_names_are_rejected(self) -> None:
        for settings in ({"side": "middle"}, {"panic_keys": ["Nope"]},
                         {"panic_keys": "F1"}, {"remap": {"Nope": "Escape"}},
                         {"remap": {"CapsLock": "Nope"}}, {"remap": []}):
            with self.subTest(settings=settings):
                with self.assertRaises(config.ConfigError):
                    config.build(config.read(write(settings)))

    def test_missing_file_is_reported(self) -> None:
        with self.assertRaises(config.ConfigError):
            config.read(Path(tempfile.gettempdir()) / "winborder-absent.json")

    def test_the_serial_settings_are_gone(self) -> None:
        """They belonged to the bridge board, which no longer exists.

        A file still carrying one is a file from the old version, and the answer
        is to say so rather than to keep accepting it: nothing here is a runtime
        setting any more.
        """
        for name in ("port", "baudrate", "transport"):
            with self.subTest(name=name):
                with self.assertRaises(config.ConfigError):
                    config.read(write({name: "COM7"}))

    def test_defaults_carry_no_serial_setting(self) -> None:
        written = config.defaults()
        for name in ("port", "baudrate", "transport"):
            with self.subTest(name=name):
                self.assertNotIn(name, written)


class TestCommandLinePrecedence(unittest.TestCase):
    """Defaults, then the settings file, then the command line."""

    def build(self, settings: dict, argv: list[str]) -> model.Config:
        args = cli.build_parser().parse_args(["--config", str(write(settings)), *argv])
        return cli.make_config(cli.load_settings(args), args)

    def test_file_overrides_defaults(self) -> None:
        built = self.build({"side": "left", "pullback_distance": 500}, [])
        self.assertIs(built.side, model.Side.LEFT)
        self.assertEqual(built.pullback_distance, 500)

    def test_flags_override_the_file(self) -> None:
        built = self.build({"side": "left", "pullback_distance": 500},
                           ["--side", "top", "--pullback-distance", "111"])
        self.assertIs(built.side, model.Side.TOP)
        self.assertEqual(built.pullback_distance, 111)

    def test_default_file_may_be_absent(self) -> None:
        """Running without a settings file is normal; naming a missing one is not."""
        args = cli.build_parser().parse_args([])
        self.assertEqual(args.config, config.DEFAULT_FILENAME)
        with tempfile.TemporaryDirectory() as directory:
            here = os.getcwd()
            os.chdir(directory)
            try:
                self.assertEqual(cli.load_settings(args), {})
            finally:
                os.chdir(here)

    def test_named_file_must_exist(self) -> None:
        args = cli.build_parser().parse_args(
            ["--config", str(Path(tempfile.gettempdir()) / "winborder-absent.json")])
        with self.assertRaises(config.ConfigError):
            cli.load_settings(args)

    def test_flag_only_negation(self) -> None:
        built = self.build({"pullback_exit": True, "edge_trigger_enabled": True},
                           ["--no-pullback-exit", "--no-edge"])
        self.assertFalse(built.pullback_exit)
        self.assertFalse(built.edge_trigger_enabled)


class TestRemap(unittest.TestCase):
    """A remapped key must reach the target as the key it was mapped to."""

    def states(self, effects: list[model.Effect]) -> list[bytes]:
        return [e.payload for e in effects
                if isinstance(e, model.SendFrame) and e.kind == hid.KEYBOARD]

    def router(self, remap: tuple[tuple[int, int], ...]) -> model.Router:
        cfg = model.Config(side=model.Side.RIGHT, remap=remap)
        router = model.Router(config=cfg, screen=(1920, 1080))
        router.note_link_ok(1000.0)
        router.tick([model.MouseMove(0, 0)], 1000.0, (1919, 540))
        return router

    def test_remapped_key_sends_the_new_usage(self) -> None:
        router = self.router(((keymap.vk_from_name("CapsLock"),
                               keymap.usage_from_name("Escape")),))
        effects = router.tick([model.KeyPress(0x14, True)], 1000.1, (1919, 540))
        # The report is [modifiers][k0..k6], so the first key is at index 1.
        self.assertEqual(self.states(effects)[-1][1], keymap.usage_from_name("Escape"))

    def test_remap_can_target_a_modifier(self) -> None:
        router = self.router(((keymap.vk_from_name("CapsLock"),
                               keymap.usage_from_name("LeftCtrl")),))
        effects = router.tick([model.KeyPress(0x14, True)], 1000.1, (1919, 540))
        state = self.states(effects)[-1]
        self.assertEqual(state[0], keymap.MOD_LEFT_CTRL)
        # A modifier is a bit rather than a slot, so every slot stays empty.
        self.assertEqual(state[1:], b"\x00" * hid.KEY_SLOTS)

    def test_unmapped_keys_are_untouched(self) -> None:
        router = self.router(())
        effects = router.tick([model.KeyPress(0x41, True)], 1000.1, (1919, 540))
        self.assertEqual(self.states(effects)[-1][1], 0x04)


if __name__ == "__main__":
    unittest.main()
