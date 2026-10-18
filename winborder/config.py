"""User settings, read from a JSON file.

The file is written in the field names of :class:`winborder.model.Config` plus the
link settings, so a value can be changed without touching the code. Keys are
written by name (``"F1"``, ``"LeftCtrl"``) and everything else keeps the JSON
type of the field it sets.

Precedence, lowest first: built in defaults, the settings file, the command
line. ``--write-config`` writes the built in defaults out as a starting point.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import fields
from pathlib import Path

from . import i18n, keymap, model, startup

log = logging.getLogger("winborder.config")

DEFAULT_FILENAME = "winborder.json"

# Settings Windows owns; they live in the same file but not in the bridge config.
APP_FIELDS = startup.APP_FIELDS

# The language the window is shown in.
LOCALE_FIELD = "language"

# Fields whose JSON form is not the field value itself.
KEY_LIST_FIELDS = ("panic_keys", "toggle_edge_keys", "type_clipboard_keys")
REMAP_FIELD = "remap"


class ConfigError(ValueError):
    """A settings file that cannot be used as written."""


def default_path() -> str:
    """Where the settings file is looked for when none is named.

    A built executable is normally started from a shortcut or at logon, where
    the working directory is somewhere else entirely, so it looks beside itself.
    """
    if startup.is_frozen():
        return str(Path(sys.executable).parent / DEFAULT_FILENAME)
    return DEFAULT_FILENAME


def complete(settings: dict[str, object] | None = None) -> dict[str, object]:
    """Fill in anything a settings file did not set.

    A missing file is a normal way to run: every value then comes from the built
    in defaults, which is also what the window has to show.
    """
    out = defaults()
    for name, value in (settings or {}).items():
        if value is not None:
            out[name] = value
    return out


def read(path: str | Path) -> dict[str, object]:
    """Read and validate a settings file. Missing file yields no settings."""
    file = Path(path)
    if not file.exists():
        raise ConfigError(i18n.t("msg_settings_file_not_found_path").format(path=file))
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(i18n.t("msg_path_not_valid_json_error").format(
            path=file, error=exc)) from None
    if not isinstance(raw, dict):
        raise ConfigError(i18n.t("msg_path_must_contain_json_object").format(path=file))

    known = ({f.name for f in fields(model.Config)}
             | set(APP_FIELDS) | {LOCALE_FIELD})
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(i18n.t("msg_path_unknown_setting_s_names").format(
            path=file, names=", ".join(unknown)))
    _check_extra(raw, file)
    return raw


def _check_extra(settings: dict[str, object], file: str | Path) -> None:
    """Type check the settings that are not part of the bridge config."""
    for name in APP_FIELDS:
        if name in settings and not isinstance(settings[name], bool):
            raise ConfigError(i18n.t("msg_path_name_must_be_true").format(
                path=file, name=name))
    if LOCALE_FIELD in settings and not i18n.is_supported(settings[LOCALE_FIELD]):
        raise ConfigError(i18n.t("msg_path_language_must_be_one").format(
            path=file, options=", ".join(i18n.codes())))


def build(settings: dict[str, object]) -> model.Config:
    """Build a Config from validated settings, over the built in defaults."""
    values: dict[str, object] = {}
    for field in fields(model.Config):
        if field.name not in settings:
            continue
        values[field.name] = _coerce(field.name, str(field.type), settings[field.name])
    try:
        return model.Config(**values)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ConfigError(str(exc)) from None


def app_settings(settings: dict[str, object]) -> dict[str, object]:
    """Pick out the settings Windows owns."""
    out = dict(startup.DEFAULTS)
    for name in APP_FIELDS:
        value = settings.get(name)
        if isinstance(value, bool):
            out[name] = value
    return out


def defaults() -> dict[str, object]:
    """Every setting at its built in default, in file form."""
    config = model.Config()
    out: dict[str, object] = {LOCALE_FIELD: i18n.DEFAULT_LANGUAGE}
    out.update(startup.DEFAULTS)
    for field in fields(model.Config):
        if field.name in KEY_LIST_FIELDS:
            out[field.name] = [keymap.describe_vk(vk) for vk in getattr(config, field.name)]
        elif field.name == REMAP_FIELD:
            out[field.name] = {}
        elif field.name == "side":
            out[field.name] = config.side.value
        else:
            out[field.name] = getattr(config, field.name)
    return out


def write(path: str | Path, settings: dict[str, object]) -> Path:
    """Write settings out in file form."""
    file = Path(path)
    file.write_text(json.dumps(in_file_form(settings), indent=2) + "\n",
                    encoding="utf-8")
    return file


def write_default(path: str | Path) -> Path:
    """Write every setting at its default value."""
    return write(path, defaults())


def in_file_form(settings: dict[str, object]) -> dict[str, object]:
    """Turn the values of a form or a Config into what the file should hold."""
    out: dict[str, object] = {}
    for name, value in settings.items():
        if name in KEY_LIST_FIELDS:
            out[name] = [keymap.describe_vk(vk) if isinstance(vk, int) else str(vk)
                         for vk in value]                 # type: ignore[union-attr]
        elif name == REMAP_FIELD:
            out[name] = _remap_in_file_form(value)
        elif name == "side" and isinstance(value, model.Side):
            out[name] = value.value
        else:
            out[name] = value
    return out


def _remap_in_file_form(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(source): str(target) for source, target in value.items()}
    if isinstance(value, (tuple, list)):
        return {keymap.describe_vk(vk): keymap.describe_usage(usage)
                for vk, usage in value}                   # type: ignore[misc]
    raise ConfigError(i18n.t("msg_remap_must_be_object_from"))


def _coerce(name: str, kind: str, value: object) -> object:
    if name == "side":
        if not isinstance(value, str):
            raise ConfigError(i18n.t("msg_side_must_be_string_got").format(
                kind=type(value).__name__))
        try:
            return model.Side(value)
        except ValueError:
            options = ", ".join(side.value for side in model.Side)
            raise ConfigError(i18n.t("msg_side_must_be_one_options")
                              .format(options=options, value=repr(value))) from None
    if name in KEY_LIST_FIELDS:
        return _key_tuple(name, value)
    if name == REMAP_FIELD:
        return _remap(value)
    if kind == "bool":
        if not isinstance(value, bool):
            raise ConfigError(i18n.t("msg_name_must_be_true_false").format(name=name))
        return value
    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(i18n.t("msg_name_must_be_number").format(name=name))
        return value
    if kind == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConfigError(i18n.t("msg_name_must_be_number").format(name=name))
        return float(value)
    raise ConfigError(i18n.t("msg_name_cannot_be_set_from")
                      .format(name=name))


def _key_tuple(name: str, value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ConfigError(i18n.t("msg_name_must_be_list_key").format(name=name))
    keys = []
    for entry in value:
        if not isinstance(entry, str):
            raise ConfigError(i18n.t("msg_name_must_be_list_key")
                              .format(name=name))
        try:
            keys.append(keymap.vk_from_name(entry))
        except ValueError as exc:
            raise ConfigError(f"{name}: {exc}") from None
    return tuple(keys)


def _remap(value: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, dict):
        raise ConfigError(i18n.t("msg_remap_must_be_object_from"))
    pairs = []
    for source, target in value.items():
        if not isinstance(target, str):
            raise ConfigError(i18n.t("msg_remap_values_must_be_key"))
        try:
            pairs.append((keymap.vk_from_name(source), keymap.usage_from_name(target)))
        except ValueError as exc:
            raise ConfigError(f"remap: {exc}") from None
    return tuple(sorted(pairs))
