"""XP awards (ARCHITECTURE §4 "Progression", project.md §9-10).

``award_quest_xp`` runs inside the quest completion transaction: it locks the assignee's
character and the quest attribute's row ``FOR UPDATE`` (after the wallet: see
``economy.service`` for the lock order), inserts the one ``xp_transaction`` of the occurrence
(unique ``quest_occurrence_id``; a second award raises ``DuplicateXpAwardError``) and adds the
same XP to ``character.total_xp`` and the attribute, so ``total_xp == sum(xp_transaction.xp)``
and each attribute's ``xp == sum(attribute_xp)`` for that attribute.

XP comes from the occurrence's ``terms_snapshot`` (difficulty-based, set by the server when the
terms were created); it is never read from a request. Levels are derived from XP
(``progression.levels``) and can only go up.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.common.enums import Attribute
from app.modules.progression.levels import level_for_xp
from app.modules.progression.models import XpTransaction
from app.modules.users.models import Character, CharacterAttribute


class ProgressionError(Exception):
    pass


class DuplicateXpAwardError(ProgressionError):
    """The occurrence already has its xp_transaction."""


class NoCharacterError(ProgressionError):
    """The assignee has no character (cannot happen for an onboarded player)."""


@dataclass(frozen=True, slots=True)
class LevelChange:
    before: int
    after: int

    @property
    def gained(self) -> int:
        return self.after - self.before


@dataclass(frozen=True, slots=True)
class XpAward:
    xp: int
    attribute: Attribute
    attribute_xp: int
    total_xp: int
    attribute_total_xp: int
    level: LevelChange
    attribute_level: LevelChange


def level_change(xp_before: int, gained: int) -> LevelChange:
    """Character or attribute level before and after adding ``gained`` (>= 0) XP. A large award
    may cross several levels at once; leftover XP carries over."""
    if gained < 0:
        raise ValueError("XP awards are never negative")
    return LevelChange(level_for_xp(xp_before), level_for_xp(xp_before + gained))


def quest_award(xp: int) -> tuple[int, int]:
    """(general XP, attribute XP) for a quest worth ``xp``: the same amount to both."""
    if xp < 0:
        raise ValueError("quest XP is never negative")
    return xp, xp


async def award_quest_xp(
    session: AsyncSession, *, user_id: int, occurrence_id: int, xp: int, attribute: Attribute
) -> XpAward:
    general, attribute_xp = quest_award(xp)
    character = await session.scalar(
        select(Character)
        .where(Character.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if character is None:
        raise NoCharacterError
    row = await session.scalar(
        select(CharacterAttribute)
        .where(
            CharacterAttribute.character_id == character.id,
            CharacterAttribute.attribute == attribute,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:  # pragma: no cover - the 6 rows are created with the character
        row = CharacterAttribute(character_id=character.id, attribute=attribute, xp=0)
        session.add(row)
        await session.flush()
    inserted = await session.scalar(
        insert(XpTransaction)
        .values(
            user_id=user_id,
            quest_occurrence_id=occurrence_id,
            xp=general,
            attribute=attribute,
            attribute_xp=attribute_xp,
        )
        .on_conflict_do_nothing(index_elements=[XpTransaction.quest_occurrence_id])
        .returning(XpTransaction.id)
    )
    if inserted is None:
        raise DuplicateXpAwardError(occurrence_id)
    level = level_change(character.total_xp, general)
    attribute_level = level_change(row.xp, attribute_xp)
    character.total_xp += general
    row.xp += attribute_xp
    await session.flush()
    return XpAward(
        xp=general,
        attribute=attribute,
        attribute_xp=attribute_xp,
        total_xp=character.total_xp,
        attribute_total_xp=row.xp,
        level=level,
        attribute_level=attribute_level,
    )
