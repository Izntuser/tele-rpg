"""Access tokens: HS256 JWTs carrying the user id.

- the algorithm is pinned on decode (``algorithms=[HS256]``), so ``none``/RS*/ES* tokens and
  algorithm-confusion attacks are rejected;
- ``exp``, ``iat``, ``sub``, ``iss`` and ``aud`` are required; ``iss``/``aud`` must match;
- expiry is checked against ``app.core.clock`` (not the wall clock) so tests can freeze time;
  PyJWT's own exp/iat checks are replaced by ``_check_times`` rather than skipped silently.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

from app.core import clock

ALGORITHM = "HS256"
ISSUER = "tele-rpg"
AUDIENCE = "tele-rpg-api"
REQUIRED_CLAIMS = ["exp", "iat", "sub", "iss", "aud"]
# Tokens minted slightly in the "future" (clock skew) are still accepted within this window.
IAT_LEEWAY = timedelta(seconds=30)


class TokenError(Exception):
    """The token is invalid. Message is generic and never contains the token."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: int
    issued_at: datetime
    expires_at: datetime


def encode_token(user_id: int, secret: str, ttl: timedelta) -> str:
    now = clock.now()
    payload = {
        "sub": str(user_id),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def _check_times(iat: object, exp: object) -> tuple[datetime, datetime]:
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise TokenError("invalid token")
    if isinstance(iat, bool) or isinstance(exp, bool):
        raise TokenError("invalid token")
    now = clock.now()
    try:
        issued = datetime.fromtimestamp(iat, now.tzinfo)
        expires = datetime.fromtimestamp(exp, now.tzinfo)
    except (OverflowError, OSError, ValueError):
        raise TokenError("invalid token") from None
    if expires <= now:
        raise TokenError("token expired")
    if issued - now > IAT_LEEWAY or issued >= expires:
        raise TokenError("invalid token")
    return issued, expires


def decode_token(token: str, secret: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={
                "require": REQUIRED_CLAIMS,
                "verify_signature": True,
                # Checked by _check_times against app.core.clock instead.
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
    except jwt.PyJWTError:
        raise TokenError("invalid token") from None
    issued, expires = _check_times(payload.get("iat"), payload.get("exp"))
    sub = payload.get("sub")
    if not isinstance(sub, str) or not (sub.isascii() and sub.isdigit()) or int(sub) <= 0:
        raise TokenError("invalid token")
    return TokenClaims(user_id=int(sub), issued_at=issued, expires_at=expires)
