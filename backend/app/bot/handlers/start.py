"""``/start [payload]``: a localized welcome with one button that opens the Mini App.

The payloads ``invite_<token>`` and ``q_<id>`` (any kind lib/deeplink.ts knows) are passed
through unchanged to the Mini App ``startapp``; the app validates them, the bot never looks
them up. The user is found by Telegram id among live accounts only (``tg_user_id > 0`` and
not deleted; deleted rows hold ``-id``, DECISIONS #13/#16).
"""

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import i18n
from app.bot.dispatcher import open_button, valid_start_param
from app.modules.users.models import User


def locale_for(language_code: str | None, user: User | None) -> str:
    if user is not None:
        return user.locale.value
    return "uk" if (language_code or "").lower().startswith("uk") else "en"


async def live_user(session: AsyncSession, tg_user_id: int) -> User | None:
    if tg_user_id <= 0:
        return None
    user: User | None = await session.scalar(
        select(User).where(
            User.tg_user_id == tg_user_id, User.tg_user_id > 0, User.deleted_at.is_(None)
        )
    )
    return user


def welcome_key(user: User | None, start_param: str | None) -> str:
    if start_param and start_param.startswith("invite_"):
        return "start.invite"
    if start_param and start_param.startswith("q_"):
        return "start.quest"
    return "start.welcome_back" if user is not None and user.onboarded_at else "start.welcome"


async def start(message: Message, command: CommandObject, session: AsyncSession) -> None:
    sender = message.from_user
    user = await live_user(session, sender.id) if sender is not None else None
    locale = locale_for(sender.language_code if sender else None, user)
    start_param = valid_start_param(command.args.strip() if command.args else None)
    await message.answer(
        i18n.text(locale, welcome_key(user, start_param)),
        reply_markup=open_button(i18n.text(locale, "start.open_app"), start_param),
    )


def build_router() -> Router:
    router = Router(name="start")
    router.message.register(start, CommandStart())
    return router
