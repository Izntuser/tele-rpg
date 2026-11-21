"""Login (initData -> user upsert -> JWT) and the /auth/me read model."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import Settings
from app.modules.auth.jwt import encode_token
from app.modules.auth.schemas import (
    CharacterSummary,
    CompanionSummary,
    MeOut,
    PartnershipSummary,
    UserOut,
)
from app.modules.auth.telegram import TelegramUser, validate_init_data
from app.modules.common.enums import Locale, PartnershipStatus
from app.modules.partnerships.models import Partnership
from app.modules.users.models import Character, User

MAX_PHOTO_URL_LEN = 2048


class AccountDeletedError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LoginResult:
    token: str
    expires_at: datetime
    user: User
    start_param: str | None


def locale_for(language_code: str | None) -> Locale:
    primary = (language_code or "").split("-", 1)[0].strip().lower()
    return Locale.UK if primary == "uk" else Locale.EN


def display_name_for(tg: TelegramUser) -> str:
    name = " ".join(p for p in (tg.first_name.strip(), (tg.last_name or "").strip()) if p)
    return (name or tg.username or f"user{tg.id}")[:128]


def safe_photo_url(url: str | None) -> str | None:
    """Only plain https URLs are stored (the value ends up in an <img src>)."""
    if url and url.startswith("https://") and len(url) <= MAX_PHOTO_URL_LEN:
        return url
    return None


async def upsert_user(session: AsyncSession, tg: TelegramUser) -> User:
    """Insert or refresh the user keyed by ``tg_user_id`` (NOT NULL unique).

    Telegram-owned fields (username, display name, photo) are refreshed on every login;
    ``locale`` is only set on first login so a later in-app choice is kept.
    """
    values = {
        "tg_user_id": tg.id,
        "tg_username": (tg.username or None) and tg.username[:64],
        "display_name": display_name_for(tg),
        "avatar_url": safe_photo_url(tg.photo_url),
    }
    base = insert(User).values(**values, locale=locale_for(tg.language_code))
    upsert = base.on_conflict_do_update(
        index_elements=[User.tg_user_id],
        set_={
            **{k: base.excluded[k] for k in values if k != "tg_user_id"},
            "updated_at": clock.now(),
        },
    ).returning(User)
    result = await session.execute(
        select(User).from_statement(upsert).execution_options(populate_existing=True)
    )
    user: User = result.scalar_one()
    return user


async def login(session: AsyncSession, init_data: str, settings: Settings) -> LoginResult:
    """Validate initData (raises InitDataError), upsert the user and mint a JWT."""
    data = validate_init_data(init_data, settings.tg_bot_token.get_secret_value())
    user = await upsert_user(session, data.user)
    if user.deleted_at is not None:
        await session.rollback()
        raise AccountDeletedError
    await session.commit()
    ttl = timedelta(seconds=settings.jwt_ttl_seconds)
    token = encode_token(user.id, settings.jwt_secret.get_secret_value(), ttl)
    return LoginResult(
        token=token,
        expires_at=clock.now() + ttl,
        user=user,
        start_param=data.start_param,
    )


async def get_active_user(session: AsyncSession, user_id: int) -> User | None:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return None
    return user


async def me(session: AsyncSession, user: User) -> MeOut:
    character = await session.scalar(select(Character).where(Character.user_id == user.id))
    partnership = await session.scalar(
        select(Partnership).where(
            Partnership.status == PartnershipStatus.ACTIVE,
            or_(Partnership.user_a_id == user.id, Partnership.user_b_id == user.id),
        )
    )
    summary: PartnershipSummary | None = None
    if partnership is not None:
        companion_id = (
            partnership.user_b_id if partnership.user_a_id == user.id else partnership.user_a_id
        )
        companion = await session.get(User, companion_id)
        if companion is not None:
            summary = PartnershipSummary(
                id=partnership.id,
                companion=CompanionSummary(
                    id=companion.id,
                    display_name=companion.display_name,
                    avatar_url=companion.avatar_url,
                ),
            )
    return MeOut(
        user=UserOut.model_validate(user),
        character=CharacterSummary.model_validate(character) if character else None,
        partnership=summary,
    )
