"""The aiogram side of the app: the ``Bot`` client, the ``Dispatcher`` and Mini App links.

- ``get_bot()`` is the only place that builds a ``Bot``. With ``APP_ENV=test`` or the public
  fake dev token it returns a ``FakeBot`` (``app/bot/fake.py``) that records calls and never
  touches the network; otherwise a real ``Bot`` without a parse mode (texts carry user-written
  quest titles and are sent as plain text).
- ``build_dispatcher()`` registers the handlers. The webhook route passes the request's DB
  session into ``feed_update``; polling opens one per update (``SessionMiddleware``).
- ``startapp_url`` builds ``https://t.me/<bot>/<app>?startapp=<payload>`` from
  ``TG_BOT_USERNAME`` and ``TG_APP_SHORT_NAME`` (required in prod, ``core/config.py``).
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, TelegramObject, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.fake import FakeBot
from app.core.config import DEV_TG_BOT_TOKEN, Settings, get_settings

#: Bot API request timeout (seconds): the API process sends right after a commit.
REQUEST_TIMEOUT = 10

#: What may follow ``startapp=``: Telegram allows ``[A-Za-z0-9_-]`` up to 512 characters, and
#: the app only understands these kinds (lib/deeplink.ts).
START_PARAM = re.compile(r"^(invite|q|qt|r|rq|rw|p)_[A-Za-z0-9_-]{1,64}$")

_bot: Bot | None = None


def uses_fake_bot(settings: Settings) -> bool:
    token = settings.tg_bot_token.get_secret_value()
    return settings.app_env == "test" or not token or token == DEV_TG_BOT_TOKEN


def get_bot() -> Bot:
    """The process-wide bot client (created on first use)."""
    global _bot
    if _bot is None:
        settings = get_settings()
        if uses_fake_bot(settings):
            _bot = FakeBot()
        else:  # pragma: no cover - needs a real token
            _bot = Bot(
                token=settings.tg_bot_token.get_secret_value(),
                session=AiohttpSession(timeout=REQUEST_TIMEOUT),
                default=DefaultBotProperties(parse_mode=None),
            )
    return _bot


def set_bot(bot: Bot | None) -> None:
    """Replace the process bot (tests install a fresh ``FakeBot``)."""
    global _bot
    _bot = bot


async def close_bot() -> None:
    global _bot
    if _bot is not None:
        await _bot.session.close()
        _bot = None


def valid_start_param(value: str | None) -> str | None:
    return value if value and START_PARAM.fullmatch(value) else None


def startapp_url(start_param: str | None, settings: Settings | None = None) -> str | None:
    """Direct Mini App link (opens the app with ``start_param``); None when the bot or app
    name is not configured (development)."""
    settings = settings or get_settings()
    if not settings.tg_bot_username or not settings.tg_app_short_name:
        return None
    url = f"https://t.me/{quote(settings.tg_bot_username)}/{quote(settings.tg_app_short_name)}"
    param = valid_start_param(start_param)
    return f"{url}?startapp={param}" if param else url


def open_button(
    text: str, start_param: str | None, settings: Settings | None = None
) -> InlineKeyboardMarkup:
    """One inline button that opens the Mini App. With a start parameter (and configured
    names) it is the ``t.me`` direct link, the only way to pass ``startapp``; otherwise a
    ``web_app`` button on PUBLIC_BASE_URL."""
    settings = settings or get_settings()
    param = valid_start_param(start_param)
    url = startapp_url(param, settings) if param else None
    if url is not None:
        button = InlineKeyboardButton(text=text, url=url)
    else:
        button = InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.public_base_url))
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def notification_button(
    text: str, deep_link: str | None, settings: Settings | None = None
) -> InlineKeyboardMarkup:
    """A notification's button: the ``t.me`` direct link (with ``startapp`` when the row has
    a deep link, else the app's start screen); a ``web_app`` button only when the names are
    not configured (development)."""
    settings = settings or get_settings()
    url = startapp_url(deep_link, settings)
    if url is None:
        return open_button(text, None, settings)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


class SessionMiddleware(BaseMiddleware):
    """Polling: give each update handler its own DB session (the webhook passes the
    request's session instead)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if "session" in data:
            return await handler(event, data)
        async with self._sessions() as session:
            data["session"] = session
            return await handler(event, data)


def build_dispatcher() -> Dispatcher:
    from app.bot.handlers import start

    dp = Dispatcher()
    dp.include_router(start.build_router())
    return dp


_dispatcher: Dispatcher | None = None


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = build_dispatcher()
    return _dispatcher


def webhook_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    base = settings.public_base_url.rstrip("/")
    return f"{base}/tg/webhook/{settings.tg_webhook_secret.get_secret_value()}"


async def setup_webhook(bot: Bot, settings: Settings | None = None) -> None:
    """Prod startup: point Telegram at this API's webhook route."""
    settings = settings or get_settings()
    await bot.set_webhook(webhook_url(settings), allowed_updates=["message"])
