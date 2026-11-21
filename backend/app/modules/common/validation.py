"""Reusable Pydantic field types for user-entered text, timezones and path IDs.

Text is NFC-normalized, stripped and length-limited after stripping. Control characters and
bidi overrides are rejected (single-line fields also reject newlines). Blank optional text
becomes ``None``; blank required text fails ``min_length``.
"""

import re
import unicodedata
from functools import lru_cache
from typing import Annotated
from zoneinfo import available_timezones

from fastapi import Path
from pydantic import AfterValidator, BeforeValidator, Field

MAX_BIGINT = 2**63 - 1

_BIDI_CONTROLS = re.compile("[‪-‮⁦-⁩]")
_INVISIBLE = "​‌‍⁠﻿"


def _clean(value: object, *, multiline: bool) -> object:
    if not isinstance(value, str):
        return value
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").strip()
    if not text.strip(_INVISIBLE).strip():
        return ""
    allowed = {"\n", "\t"} if multiline else set()
    for ch in text:
        if ch not in allowed and unicodedata.category(ch) in ("Cc", "Cs"):
            raise ValueError("must not contain control characters")
    if _BIDI_CONTROLS.search(text):
        raise ValueError("must not contain bidirectional control characters")
    return text


def _single_line(value: object) -> object:
    return _clean(value, multiline=False)


def _multi_line(value: object) -> object:
    return _clean(value, multiline=True)


def _empty_to_none(value: object) -> object:
    return None if value == "" else value


# Annotated before-validators run right to left: clean first, then map "" to None.
Name = Annotated[str, BeforeValidator(_single_line), Field(min_length=1, max_length=64)]
Nickname = Annotated[
    Annotated[str, Field(max_length=64)] | None,
    BeforeValidator(_empty_to_none),
    BeforeValidator(_single_line),
]
Bio = Annotated[
    Annotated[str, Field(max_length=500)] | None,
    BeforeValidator(_empty_to_none),
    BeforeValidator(_multi_line),
]
Title = Annotated[str, BeforeValidator(_single_line), Field(min_length=1, max_length=200)]
Description = Annotated[
    Annotated[str, Field(max_length=1000)] | None,
    BeforeValidator(_empty_to_none),
    BeforeValidator(_multi_line),
]


@lru_cache
def _timezones() -> frozenset[str]:
    return frozenset(tz for tz in available_timezones() if not tz.startswith(("posix/", "right/")))


def _valid_timezone(value: str) -> str:
    # Only keys of the IANA tz database; "localtime", file paths and offsets are rejected.
    if value not in _timezones():
        raise ValueError("must be an IANA timezone such as Europe/Kyiv")
    return value


Timezone = Annotated[str, Field(min_length=1, max_length=64), AfterValidator(_valid_timezone)]

#: A bigint primary key in a URL path; out-of-range values get 422 instead of a DB error.
IdPath = Annotated[int, Path(gt=0, le=MAX_BIGINT)]
