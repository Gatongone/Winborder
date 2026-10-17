"""Read and write one interface language as a JSON file, for reviewing the wording.

The window's text is keyed by its English source, so a translator or a reviewer
needs the two side by side. This exports the table of one language as a JSON
object in the table's own order, and applies an edited copy back into the module:
only the values that changed are rewritten, so wrapping, comments and the order
around them survive, and a key that did not exist before is refused instead of
quietly adding an entry nothing uses.

    python .github/tools/i18n_table.py --export i18n.zh.json --language zh
    python .github/tools/i18n_table.py --apply i18n.zh.json --language zh

Placeholders such as ``{name}`` are part of the message and are checked by
``tests/test_i18n.py``; keep them exactly as they are.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from winborder import i18n  # noqa: E402 - after the path is set


def section_bounds(text: str, code: str) -> tuple[int, int]:
    """Where one language's table starts and ends inside the module."""
    marker = f'    "{code}": {{'
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"no table for {code!r} in winborder/i18n.py")
    end = text.find("\n    },\n", start)
    if end < 0:
        raise SystemExit(f"the table for {code!r} has no end")
    return start, end + len("\n    },\n")


def export(path: Path, code: str) -> int:
    table = i18n.TRANSLATIONS.get(code)
    if table is None:
        raise SystemExit(f"{code!r} is not a translated language")
    path.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return len(table)


def entries(section: str) -> list[tuple[str, int, int]]:
    """Every key with the line span of its whole entry, found by parsing.

    A regular expression cannot do this: a long key is written as several adjacent
    string literals over several lines, and its value can be wrapped the same way.
    Parsing the section as a dict literal gives the exact line span of each entry,
    whatever shape the author wrapped it into.
    """
    import ast

    start = section.index("{")
    end = section.rindex("}")
    body = section[start + 1:end]
    # Keep the line numbering: the body starts on the section's first line.
    padding = "\n" * (section[:start + 1].count("\n"))
    tree = ast.parse("{" + padding + body + "}")
    literal = tree.body[0].value            # the Expr that wraps the dict
    found = []
    for key_node, value_node in zip(literal.keys, literal.values):
        if not isinstance(key_node, ast.Constant):
            raise SystemExit("a table key is not a plain string")
        found.append((key_node.value, key_node.lineno, value_node.end_lineno))
    return found


def apply(path: Path, code: str) -> tuple[int, list[str]]:
    """Write the edited values back, and report what still differs."""
    edited = json.loads(path.read_text(encoding="utf-8"))
    current = i18n.TRANSLATIONS.get(code)
    if current is None:
        raise SystemExit(f"{code!r} is not a translated language")

    added = sorted(set(edited) - set(current))
    if added:
        raise SystemExit("these keys are not in the window any more: "
                         + ", ".join(added))
    missing = sorted(set(current) - set(edited))
    if missing:
        raise SystemExit("these keys are missing from the file: "
                         + ", ".join(missing))
    empty = sorted(key for key, value in edited.items() if not str(value).strip())
    if empty:
        raise SystemExit("these keys have no text: " + ", ".join(empty))

    module = Path(i18n.__file__)
    text = module.read_text(encoding="utf-8")
    start, end = section_bounds(text, code)
    section = text[start:end]

    spans = entries(section)
    known = {key for key, _first, _last in spans}
    if set(edited) != known:
        raise SystemExit(f"the module's {code!r} table does not match its own words")

    changed = 0
    lines = section.splitlines(keepends=True)
    # Bottom up, so the line numbers of the entries above stay valid.
    for key, first, last in sorted(spans, key=lambda item: item[1], reverse=True):
        if current[key] == edited[key]:
            continue
        line = f'        {json.dumps(key, ensure_ascii=False)}: '
        line += f'{json.dumps(edited[key], ensure_ascii=False)},\n'
        lines[first - 1:last] = [line]
        changed += 1

    module.write_text(text[:start] + "".join(lines) + text[end:], encoding="utf-8")
    return changed, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="i18n.zh.json")
    parser.add_argument("--language", default="zh")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", action="store_true",
                       help="write the table out as JSON")
    group.add_argument("--apply", action="store_true",
                       help="write an edited JSON file back into the module")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if args.export:
        count = export(path, args.language)
        print(f"wrote {count} entries for {args.language} to {path}")
        return 0
    changed, _ = apply(path, args.language)
    print(f"applied {changed} changed entries for {args.language}")
    print("now run: python -m unittest discover -s tests -t .")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
