"""Bot strings (ARCHITECTURE §7 i18n): ``en.json`` and ``uk.json`` next to this file.

``text(locale, "a.b")`` looks a dotted key up in the locale's catalog and falls back to
English. ``render`` fills plain ``{name}`` fields from the given values; a missing field
renders empty, so an old payload without that field still renders.
"""

import json
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import Any

LOCALES = ("en", "uk")
DEFAULT_LOCALE = "en"
_DIR = Path(__file__).resolve().parent


@lru_cache
def catalog(locale: str) -> dict[str, Any]:
    if locale not in LOCALES:
        locale = DEFAULT_LOCALE
    data: dict[str, Any] = json.loads((_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    return data


def flat_keys(tree: dict[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            keys |= flat_keys(value, f"{path}.")
        else:
            keys.add(path)
    return keys


def _lookup(tree: dict[str, Any], key: str) -> str | None:
    node: Any = tree
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def has(key: str) -> bool:
    return _lookup(catalog(DEFAULT_LOCALE), key) is not None


def text(locale: str | None, key: str) -> str:
    found = _lookup(catalog(locale or DEFAULT_LOCALE), key)
    if found is None:
        found = _lookup(catalog(DEFAULT_LOCALE), key)
    if found is None:
        raise KeyError(key)
    return found


def render(locale: str | None, key: str, values: dict[str, Any] | None = None) -> str:
    """The string for ``key`` with its ``{field}`` placeholders filled from ``values``.

    Only scalar values are used and fields are plain names, so a payload can never reach
    attribute or index lookups the way ``str.format`` would allow.
    """
    template = text(locale, key)
    safe = {
        k: v
        for k, v in (values or {}).items()
        if isinstance(v, str | int | float) and not isinstance(v, bool)
    }
    parts: list[str] = []
    for literal, field, _spec, _conversion in Formatter().parse(template):
        parts.append(literal)
        if field is not None:
            parts.append(str(safe.get(field, "")))
    return "".join(parts)
