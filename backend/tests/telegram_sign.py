"""Build initData strings signed exactly as Telegram does (shared by unit and integration tests).

Independent of app code on purpose: the signing below follows the Telegram docs directly, so a
bug in ``app.modules.auth.telegram`` cannot be mirrored here.
"""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from app.core.config import DEV_TG_BOT_TOKEN


def telegram_hash(fields: dict[str, str], bot_token: str) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def make_init_data(
    *,
    auth_date: datetime,
    user: dict[str, Any] | None = None,
    bot_token: str = DEV_TG_BOT_TOKEN,
    extra: dict[str, str] | None = None,
    include_user: bool = True,
) -> str:
    fields: dict[str, str] = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
    }
    if include_user:
        u = {"id": 279058397, "first_name": "Alice", "language_code": "en"} | (user or {})
        fields["user"] = json.dumps(u, separators=(",", ":"), ensure_ascii=False)
    fields.update(extra or {})
    fields["hash"] = telegram_hash(fields, bot_token)
    return urlencode(fields)
