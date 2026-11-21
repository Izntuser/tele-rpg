from datetime import timedelta
from types import ModuleType
from typing import Any

import jwt as pyjwt
import pytest

from app.modules.auth.jwt import (
    ALGORITHM,
    AUDIENCE,
    ISSUER,
    TokenError,
    decode_token,
    encode_token,
)

SECRET = "s" * 64
DAY = timedelta(hours=24)


def claims(clock: ModuleType, **overrides: Any) -> dict[str, Any]:
    now = int(clock.now().timestamp())
    base: dict[str, Any] = {
        "sub": "7",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 3600,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_round_trip(frozen_clock: ModuleType) -> None:
    token = encode_token(7, SECRET, DAY)
    decoded = decode_token(token, SECRET)
    assert decoded.user_id == 7
    assert decoded.expires_at - decoded.issued_at == DAY
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "HS256"


def test_expires_after_ttl(frozen_clock: ModuleType) -> None:
    token = encode_token(7, SECRET, DAY)
    frozen_clock.advance(DAY - timedelta(seconds=1))
    assert decode_token(token, SECRET).user_id == 7
    frozen_clock.advance(timedelta(seconds=1))
    with pytest.raises(TokenError, match="expired"):
        decode_token(token, SECRET)


def test_wrong_secret_is_rejected(frozen_clock: ModuleType) -> None:
    token = encode_token(7, "other" * 10, DAY)
    with pytest.raises(TokenError):
        decode_token(token, SECRET)


def test_alg_none_is_rejected(frozen_clock: ModuleType) -> None:
    token = pyjwt.encode(claims(frozen_clock), key="", algorithm="none")
    with pytest.raises(TokenError):
        decode_token(token, SECRET)


def test_other_hmac_algorithm_is_rejected(frozen_clock: ModuleType) -> None:
    token = pyjwt.encode(claims(frozen_clock), SECRET, algorithm="HS512")
    with pytest.raises(TokenError):
        decode_token(token, SECRET)


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "someone-else"},
        {"iss": "someone-else"},
        {"aud": None},
        {"iss": None},
        {"exp": None},
        {"iat": None},
        {"sub": None},
        {"sub": "abc"},
        {"sub": "0"},
        {"sub": "-1"},
        {"sub": "²"},
        {"exp": True},
        {"exp": 10**20},
        {"iat": "now"},
    ],
    ids=lambda o: ",".join(f"{k}={v}" for k, v in o.items()),
)
def test_bad_claims_are_rejected(frozen_clock: ModuleType, overrides: dict[str, Any]) -> None:
    token = pyjwt.encode(claims(frozen_clock, **overrides), SECRET, algorithm=ALGORITHM)
    with pytest.raises(TokenError):
        decode_token(token, SECRET)


def test_token_issued_in_the_future_is_rejected(frozen_clock: ModuleType) -> None:
    now = int(frozen_clock.now().timestamp())
    token = pyjwt.encode(
        claims(frozen_clock, iat=now + 3600, exp=now + 7200), SECRET, algorithm=ALGORITHM
    )
    with pytest.raises(TokenError):
        decode_token(token, SECRET)


def test_garbage_is_rejected() -> None:
    with pytest.raises(TokenError):
        decode_token("not.a.jwt", SECRET)


def test_error_message_does_not_contain_token(frozen_clock: ModuleType) -> None:
    token = encode_token(7, "other" * 10, DAY)
    with pytest.raises(TokenError) as excinfo:
        decode_token(token, SECRET)
    assert token not in str(excinfo.value)
