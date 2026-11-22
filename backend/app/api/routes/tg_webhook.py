"""``POST /tg/webhook/{secret}``: Telegram updates for the aiogram dispatcher (outside /api).

The router is named ``tg_router`` (not ``router``) so the /api route discovery skips it;
``app/main.py`` mounts it at the root. A wrong or unset ``TG_WEBHOOK_SECRET`` answers 404, as
if the route did not exist. The handlers get the request's DB session.
"""

import hmac
import logging
from typing import Any

from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from app.bot.dispatcher import get_bot, get_dispatcher
from app.core.deps import SessionDep, SettingsDep

log = logging.getLogger(__name__)

#: Telegram updates are small; anything bigger is not from Telegram.
MAX_UPDATE_BYTES = 1 << 20

tg_router = APIRouter(prefix="/tg", include_in_schema=False)


@tg_router.post("/webhook/{secret}")
async def telegram_webhook(
    secret: str, request: Request, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    expected = settings.tg_webhook_secret.get_secret_value()
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    body = await request.body()
    if len(body) > MAX_UPDATE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    bot = get_bot()
    try:
        update = Update.model_validate_json(body, context={"bot": bot})
    except ValidationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from None
    try:
        await get_dispatcher().feed_update(bot, update, session=session)
    except Exception:
        # Telegram retries a failed delivery for hours; a broken update must not loop.
        log.exception("telegram update %s failed", update.update_id)
    return {"ok": True}
