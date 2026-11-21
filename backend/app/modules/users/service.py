"""Character read model, profile edits and onboarding.

Every function acts on the calling ``user`` only; no function takes a user or character id
from the client. XP, level and gold are never written here (they change only through the
quest and economy services).
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.auth.schemas import UserOut
from app.modules.common.enums import Attribute, PartnershipStatus
from app.modules.economy.models import Wallet
from app.modules.goals.models import DevelopmentGoal
from app.modules.goals.schemas import MAX_GOALS
from app.modules.partnerships.models import Partnership
from app.modules.progression.levels import progress_for_xp
from app.modules.users.models import Character, CharacterAttribute, User
from app.modules.users.schemas import (
    AttributeOut,
    CharacterOut,
    CharacterUpdate,
    OnboardingIn,
    OnboardingOut,
)


class CharacterNotFoundError(Exception):
    """The user has no character yet (onboarding not completed)."""


class AlreadyOnboardedError(Exception):
    pass


async def active_partnership(session: AsyncSession, user_id: int) -> Partnership | None:
    partnership: Partnership | None = await session.scalar(
        select(Partnership).where(
            Partnership.status == PartnershipStatus.ACTIVE,
            or_(Partnership.user_a_id == user_id, Partnership.user_b_id == user_id),
        )
    )
    return partnership


async def active_companion_id(session: AsyncSession, user_id: int) -> int | None:
    """The other member of ``user_id``'s active partnership, or None."""
    partnership = await active_partnership(session, user_id)
    if partnership is None:
        return None
    return partnership.user_b_id if partnership.user_a_id == user_id else partnership.user_a_id


async def active_gold(session: AsyncSession, user_id: int) -> int:
    balance = await session.scalar(
        select(Wallet.balance)
        .join(Partnership, Partnership.id == Wallet.partnership_id)
        .where(Wallet.user_id == user_id, Partnership.status == PartnershipStatus.ACTIVE)
    )
    return int(balance or 0)


async def get_character(session: AsyncSession, user: User) -> Character | None:
    character: Character | None = await session.scalar(
        select(Character).where(Character.user_id == user.id)
    )
    return character


async def character_out(session: AsyncSession, user: User, character: Character) -> CharacterOut:
    rows = await session.execute(
        select(CharacterAttribute.attribute, CharacterAttribute.xp).where(
            CharacterAttribute.character_id == character.id
        )
    )
    xp_by_attribute = {attribute: xp for attribute, xp in rows.all()}
    attributes = []
    for attribute in Attribute:
        xp = xp_by_attribute.get(attribute, 0)
        p = progress_for_xp(xp)
        attributes.append(
            AttributeOut(
                attribute=attribute,
                xp=xp,
                level=p.level,
                xp_into_level=p.xp_into_level,
                xp_for_next_level=p.xp_for_next_level,
            )
        )
    progress = progress_for_xp(character.total_xp)
    return CharacterOut(
        id=character.id,
        name=character.name,
        nickname=character.nickname,
        bio=character.bio,
        avatar_url=user.avatar_url,
        level=progress.level,
        total_xp=character.total_xp,
        xp_into_level=progress.xp_into_level,
        xp_for_next_level=progress.xp_for_next_level,
        xp_to_next_level=progress.xp_to_next_level,
        attributes=attributes,
        gold=await active_gold(session, user.id),
        locale=user.locale,
        timezone=user.timezone,
        onboarded_at=user.onboarded_at,
    )


async def read_character(session: AsyncSession, user: User) -> CharacterOut:
    character = await get_character(session, user)
    if character is None:
        raise CharacterNotFoundError
    return await character_out(session, user, character)


async def update_character(
    session: AsyncSession, user: User, data: CharacterUpdate
) -> CharacterOut:
    """Apply only the fields the client actually sent (``model_fields_set``)."""
    character = await get_character(session, user)
    if character is None:
        raise CharacterNotFoundError
    sent = data.model_fields_set
    if "name" in sent and data.name is not None:
        character.name = data.name
    if "nickname" in sent:
        character.nickname = data.nickname
    if "bio" in sent:
        character.bio = data.bio
    if "locale" in sent and data.locale is not None:
        user.locale = data.locale
    if "timezone" in sent and data.timezone is not None:
        user.timezone = data.timezone
    if sent & {"locale", "timezone"}:
        user.updated_at = clock.now()
    await session.commit()
    return await character_out(session, user, character)


async def _create_character(session: AsyncSession, user: User, data: OnboardingIn) -> Character:
    character = Character(user_id=user.id, name=data.name, nickname=data.nickname, bio=data.bio)
    session.add(character)
    await session.flush()
    session.add_all(
        CharacterAttribute(character_id=character.id, attribute=attribute, xp=0)
        for attribute in Attribute
    )
    return character


async def complete_onboarding(
    session: AsyncSession, user: User, data: OnboardingIn
) -> OnboardingOut:
    """Create the character (+6 attribute rows) and the chosen goals, set the timezone and
    mark the user onboarded, in one transaction.

    The user row is locked first, so two concurrent calls cannot both create a character:
    the second one waits, then sees ``onboarded_at`` and gets AlreadyOnboardedError.
    """
    locked = await session.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:  # pragma: no cover - current_user just loaded it
        raise CharacterNotFoundError
    if locked.onboarded_at is not None:
        raise AlreadyOnboardedError

    character = await get_character(session, locked)
    if character is None:
        character = await _create_character(session, locked, data)
    else:
        character.name, character.nickname, character.bio = data.name, data.nickname, data.bio

    existing = {
        title.casefold()
        for title in await session.scalars(
            select(DevelopmentGoal.title).where(DevelopmentGoal.user_id == locked.id)
        )
    }
    for goal in data.goals:
        key = goal.title.casefold()
        if key in existing or len(existing) >= MAX_GOALS:
            continue
        existing.add(key)
        session.add(DevelopmentGoal(user_id=locked.id, title=goal.title, attribute=goal.attribute))

    now = clock.now()
    locked.timezone = data.timezone
    locked.onboarded_at = now
    locked.updated_at = now
    await session.commit()
    return OnboardingOut(
        user=UserOut.model_validate(locked),
        character=await character_out(session, locked, character),
    )


class NotPartneredError(Exception):
    """``?user=companion`` was asked for without an active partnership."""


async def resolve_owner(session: AsyncSession, user: User, who: str) -> int:
    """Whose goals/wishlist to read: ``me`` or the active companion (else NotPartneredError)."""
    if who == "me":
        return user.id
    companion_id = await active_companion_id(session, user.id)
    if companion_id is None:
        raise NotPartneredError
    return companion_id


async def lock_user(session: AsyncSession, user_id: int) -> None:
    """Serialize a user's writes that check a per-user count (row lock until commit)."""
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())
