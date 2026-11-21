"""Telegram Mini App ``initData`` validation (https://core.telegram.org/bots/webapps).

The data-check-string is every received field except ``hash``, as ``key=value`` sorted by key
and joined with ``\\n``. The secret key is ``HMAC_SHA256(key="WebAppData", msg=bot_token)`` and
the expected hash is ``hex(HMAC_SHA256(key=secret_key, msg=data_check_string))``.

Security notes:
- the hash is compared with ``hmac.compare_digest`` (constant time);
- duplicate keys, a missing/malformed hash, a missing user and an ``auth_date`` older than
  ``max_age`` (24h) or in the future (beyond a small clock skew) are rejected;
- error messages never contain the raw initData, the hash or the bot token.
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

from app.core import clock

MAX_AGE = timedelta(hours=24)
# Telegram clients and our server clocks may differ slightly; anything further ahead is forged.
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_INIT_DATA_LEN = 8192
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class InitDataError(ValueError):
    """initData is malformed, unsigned, wrongly signed or stale. Message is safe to log."""


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class InitData:
    user: TelegramUser
    auth_date: datetime
    start_param: str | None
    query_id: str | None


def secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def data_check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields) if k != "hash")


def sign(fields: dict[str, str], bot_token: str) -> str:
    """Hex hash for ``fields`` (used by tests and the e2e fixture's Python twin)."""
    return hmac.new(
        secret_key(bot_token), data_check_string(fields).encode(), hashlib.sha256
    ).hexdigest()


def _parse(raw: str) -> dict[str, str]:
    if not raw or len(raw) > MAX_INIT_DATA_LEN:
        raise InitDataError("initData is empty or too long")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, errors="strict")
    except ValueError:
        raise InitDataError("initData is not a valid query string") from None
    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            raise InitDataError("initData has a duplicate field")
        fields[key] = value
    return fields


def _str_or_none(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def _parse_user(raw_user: str | None) -> TelegramUser:
    if not raw_user:
        raise InitDataError("initData has no user")
    try:
        data = json.loads(raw_user)
    except ValueError:
        raise InitDataError("initData user is not JSON") from None
    if not isinstance(data, dict):
        raise InitDataError("initData user is not an object")
    user_id = data.get("id")
    first_name = data.get("first_name")
    # bool is an int subclass; reject it explicitly.
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise InitDataError("initData user id is invalid")
    if not isinstance(first_name, str):
        raise InitDataError("initData user first_name is invalid")
    return TelegramUser(
        id=user_id,
        first_name=first_name,
        last_name=_str_or_none(data, "last_name"),
        username=_str_or_none(data, "username"),
        language_code=_str_or_none(data, "language_code"),
        photo_url=_str_or_none(data, "photo_url"),
    )


def validate_init_data(
    raw: str,
    bot_token: str,
    *,
    max_age: timedelta = MAX_AGE,
    now: datetime | None = None,
) -> InitData:
    """Validate Telegram initData and return its parsed content, or raise InitDataError."""
    fields = _parse(raw)

    received = fields.get("hash", "")
    if not _HASH_RE.fullmatch(received):
        raise InitDataError("initData hash is missing or malformed")
    expected = sign(fields, bot_token)
    if not hmac.compare_digest(expected.encode(), received.encode()):
        raise InitDataError("initData signature mismatch")

    # Only signed data is interpreted from here on.
    try:
        auth_ts = int(fields.get("auth_date", ""))
        auth_date = datetime.fromtimestamp(auth_ts, UTC)
    except (ValueError, OverflowError, OSError):
        raise InitDataError("initData auth_date is invalid") from None
    current = now or clock.now()
    if current - auth_date > max_age:
        raise InitDataError("initData is expired")
    if auth_date - current > MAX_FUTURE_SKEW:
        raise InitDataError("initData auth_date is in the future")

    return InitData(
        user=_parse_user(fields.get("user")),
        auth_date=auth_date,
        start_param=fields.get("start_param") or None,
        query_id=fields.get("query_id") or None,
    )
