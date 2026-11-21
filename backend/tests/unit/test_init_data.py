import hmac
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode

import pytest

from app.core.config import DEV_TG_BOT_TOKEN
from app.modules.auth import telegram
from app.modules.auth.telegram import InitDataError, validate_init_data
from tests.telegram_sign import make_init_data, telegram_hash

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
TOKEN = DEV_TG_BOT_TOKEN


def fields_of(raw: str) -> dict[str, str]:
    return dict(parse_qsl(raw, keep_blank_values=True))


def resign(fields: dict[str, str], token: str = TOKEN) -> str:
    unsigned = {k: v for k, v in fields.items() if k != "hash"}
    return urlencode({**unsigned, "hash": telegram_hash(unsigned, token)})


def validate(raw: str, **kwargs: Any) -> telegram.InitData:
    return validate_init_data(raw, TOKEN, now=NOW, **kwargs)


def test_valid_init_data_is_parsed() -> None:
    raw = make_init_data(
        auth_date=NOW - timedelta(minutes=5),
        user={
            "id": 42,
            "first_name": "Олена",
            "last_name": "K",
            "username": "olena",
            "language_code": "uk",
            "photo_url": "https://t.me/i/userpic/320/x.jpg",
        },
        extra={"start_param": "invite_abc", "chat_type": "private"},
    )
    data = validate(raw)
    assert data.user.id == 42
    assert data.user.first_name == "Олена"
    assert data.user.last_name == "K"
    assert data.user.username == "olena"
    assert data.user.language_code == "uk"
    assert data.user.photo_url == "https://t.me/i/userpic/320/x.jpg"
    assert data.start_param == "invite_abc"
    expected_ts = int((NOW - timedelta(minutes=5)).timestamp())
    assert data.auth_date == datetime.fromtimestamp(expected_ts, UTC)


def test_signature_field_is_part_of_the_data_check_string() -> None:
    # Newer clients add `signature` (Ed25519 third-party check); it is still hashed like any field.
    raw = make_init_data(auth_date=NOW, extra={"signature": "c2lnbmF0dXJl"})
    assert validate(raw).user.id == 279058397


def test_uses_clock_when_now_not_given(frozen_clock: Any) -> None:
    raw = make_init_data(auth_date=frozen_clock.now() - timedelta(hours=1))
    assert validate_init_data(raw, TOKEN).user.first_name == "Alice"
    frozen_clock.advance(timedelta(hours=24))
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(raw, TOKEN)


@pytest.mark.parametrize("field", ["user", "auth_date", "query_id"])
def test_tampered_field_is_rejected(field: str) -> None:
    fields = fields_of(make_init_data(auth_date=NOW))
    fields[field] = fields[field].replace("1", "2").replace("Alice", "Mallory") + "x"
    with pytest.raises(InitDataError, match="signature mismatch"):
        validate(urlencode(fields))


def test_added_field_is_rejected() -> None:
    fields = fields_of(make_init_data(auth_date=NOW))
    fields["start_param"] = "injected"
    with pytest.raises(InitDataError, match="signature mismatch"):
        validate(urlencode(fields))


def test_tampered_hash_is_rejected() -> None:
    fields = fields_of(make_init_data(auth_date=NOW))
    last = fields["hash"][-1]
    fields["hash"] = fields["hash"][:-1] + ("0" if last != "0" else "1")
    with pytest.raises(InitDataError, match="signature mismatch"):
        validate(urlencode(fields))


def test_wrong_bot_token_is_rejected() -> None:
    raw = make_init_data(auth_date=NOW, bot_token="111:OTHERTOKENOTHERTOKENOTHERTOKEN")
    with pytest.raises(InitDataError, match="signature mismatch"):
        validate(raw)


@pytest.mark.parametrize("hash_value", [None, "", "abc", "Z" * 64, "A" * 64, "a" * 63, "a" * 65])
def test_missing_or_malformed_hash_is_rejected(hash_value: str | None) -> None:
    fields = fields_of(make_init_data(auth_date=NOW))
    if hash_value is None:
        del fields["hash"]
    else:
        fields["hash"] = hash_value
    with pytest.raises(InitDataError, match="hash is missing or malformed"):
        validate(urlencode(fields))


def test_auth_date_older_than_24h_is_rejected() -> None:
    raw = make_init_data(auth_date=NOW - timedelta(hours=24, seconds=1))
    with pytest.raises(InitDataError, match="expired"):
        validate(raw)


def test_auth_date_just_inside_24h_is_accepted() -> None:
    raw = make_init_data(auth_date=NOW - timedelta(hours=23, minutes=59))
    assert validate(raw).user.id == 279058397


def test_auth_date_in_the_future_is_rejected() -> None:
    raw = make_init_data(auth_date=NOW + timedelta(hours=1))
    with pytest.raises(InitDataError, match="future"):
        validate(raw)


def test_small_future_skew_is_accepted() -> None:
    raw = make_init_data(auth_date=NOW + timedelta(seconds=30))
    assert validate(raw).user.id == 279058397


@pytest.mark.parametrize("auth_date", ["", "abc", "1.5", "99999999999999999999"])
def test_invalid_auth_date_is_rejected(auth_date: str) -> None:
    fields = fields_of(make_init_data(auth_date=NOW))
    fields["auth_date"] = auth_date
    with pytest.raises(InitDataError, match="auth_date is invalid"):
        validate(resign(fields))


def test_compares_hash_with_compare_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return bool(real(a, b))

    monkeypatch.setattr(hmac, "compare_digest", spy)
    validate(make_init_data(auth_date=NOW))
    assert len(calls) == 1


def test_duplicate_fields_are_rejected() -> None:
    raw = make_init_data(auth_date=NOW)
    with pytest.raises(InitDataError, match="duplicate"):
        validate(raw + "&auth_date=1")


@pytest.mark.parametrize("raw", ["", "x" * (telegram.MAX_INIT_DATA_LEN + 1)])
def test_empty_or_oversized_is_rejected(raw: str) -> None:
    with pytest.raises(InitDataError, match="empty or too long"):
        validate(raw)


def test_garbage_is_rejected() -> None:
    with pytest.raises(InitDataError):
        validate("not a query string")


def test_missing_user_is_rejected() -> None:
    raw = make_init_data(auth_date=NOW, include_user=False)
    with pytest.raises(InitDataError, match="no user"):
        validate(raw)


@pytest.mark.parametrize(
    "user_json",
    [
        "not json",
        "[1, 2]",
        '{"first_name": "A"}',
        '{"id": "42", "first_name": "A"}',
        '{"id": true, "first_name": "A"}',
        '{"id": -5, "first_name": "A"}',
        '{"id": 42}',
    ],
)
def test_invalid_user_is_rejected(user_json: str) -> None:
    fields = fields_of(make_init_data(auth_date=NOW))
    fields["user"] = user_json
    with pytest.raises(InitDataError, match="user"):
        validate(resign(fields))


def test_error_messages_never_contain_secrets_or_data() -> None:
    raw = make_init_data(auth_date=NOW, bot_token="999:WRONG")
    received_hash = fields_of(raw)["hash"]
    with pytest.raises(InitDataError) as excinfo:
        validate(raw)
    message = str(excinfo.value)
    for secret in (TOKEN, received_hash, raw, "Alice"):
        assert secret not in message
