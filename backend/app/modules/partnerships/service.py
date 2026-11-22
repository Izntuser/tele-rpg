"""Invitations, pairing, leaving and the companion read model (ARCHITECTURE §4 "Partnership end").

Security rules kept here:

- an invite token is 256 random bits (``secrets.token_urlsafe(32)``); only its sha256 is stored
  and the raw token is returned exactly once, by ``create_invitation``. It is never logged;
- a token is single-use (``pending`` -> ``accepted``), expires after 7 days, is revoked by the
  creator's next invite, and cannot be accepted by its creator;
- lock order is always "user rows by ascending id, then the invitation / partnership row", so
  accept, create, leave and account deletion serialize per user without deadlocking. The
  ``partnership_one_active_per_user`` trigger stays as the last line of defence.
"""

import hashlib
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import Settings
from app.modules.common.enums import (
    Attribute,
    GoalStatus,
    InvitationStatus,
    NotificationCategory,
    PartnershipStatus,
    QuestOccurrenceStatus,
    QuestRevisionStatus,
    QuestTemplateStatus,
    RewardStatus,
    WishlistStatus,
)
from app.modules.economy.models import Wallet
from app.modules.goals.models import DevelopmentGoal
from app.modules.notifications.models import Notification
from app.modules.partnerships.models import Partnership, PartnershipInvitation
from app.modules.partnerships.schemas import (
    LEAVE_CONFIRM_TEXT,
    AcceptOut,
    ActivePartnershipOut,
    CompanionCard,
    CompanionGoalOut,
    CompanionProfileOut,
    CompanionWishOut,
    InvitationCreated,
    InvitationPreview,
    PartnershipStateOut,
    PendingInvitationOut,
)
from app.modules.progression.levels import level_for_xp, progress_for_xp
from app.modules.quests.models import QuestOccurrence, QuestRevision, QuestTemplate
from app.modules.rewards.models import Reward
from app.modules.users.models import Character, CharacterAttribute, User
from app.modules.users.schemas import AttributeOut
from app.modules.wishlist.models import WishlistItem

INVITE_TTL = timedelta(days=7)
TOKEN_BYTES = 32
INVITE_START_PREFIX = "invite_"
# Used outside prod when TG_BOT_USERNAME / TG_APP_SHORT_NAME are not configured.
FALLBACK_BOT_USERNAME = "telerpg_dev_bot"
FALLBACK_APP_SHORT_NAME = "app"

OPEN_TEMPLATE_STATUSES = (
    QuestTemplateStatus.OFFERED,
    QuestTemplateStatus.ACTIVE,
    QuestTemplateStatus.PAUSED,
)
OPEN_OCCURRENCE_STATUSES = (
    QuestOccurrenceStatus.OFFERED,
    QuestOccurrenceStatus.ACTIVE,
    QuestOccurrenceStatus.IN_REVIEW,
)


class PartnershipError(Exception):
    """Base class; each subclass maps to one HTTP status in the route."""


class InvitationNotFoundError(PartnershipError):
    pass


class InvitationExpiredError(PartnershipError):
    pass


class InvitationUsedError(PartnershipError):
    """Accepted or revoked."""


class OwnInvitationError(PartnershipError):
    pass


class AlreadyPartneredError(PartnershipError):
    pass


class NotOnboardedError(PartnershipError):
    pass


class NotPartneredError(PartnershipError):
    pass


class WrongConfirmationError(PartnershipError):
    pass


class InviteLinkNotConfiguredError(PartnershipError):
    pass


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def invite_link(settings: Settings, token: str) -> str:
    bot, app = settings.tg_bot_username.strip(), settings.tg_app_short_name.strip()
    if not (bot and app):
        if settings.app_env == "prod":
            raise InviteLinkNotConfiguredError
        bot, app = bot or FALLBACK_BOT_USERNAME, app or FALLBACK_APP_SHORT_NAME
    return f"https://t.me/{bot}/{app}?startapp={INVITE_START_PREFIX}{token}"


def companion_of(partnership: Partnership, user_id: int) -> int:
    return partnership.user_b_id if partnership.user_a_id == user_id else partnership.user_a_id


async def lock_users(session: AsyncSession, user_ids: Iterable[int]) -> dict[int, User]:
    """Lock the user rows in ascending id order and return fresh copies of them.

    ``FOR NO KEY UPDATE``, never plain ``FOR UPDATE``: a quest write that already holds the
    partnership ``FOR SHARE`` inserts rows referencing these users, and each FK check takes
    ``FOR KEY SHARE`` on the user row. A full ``FOR UPDATE`` here would make ``leave`` (waiting
    for the partnership) and that write (waiting for the user row) deadlock. No caller changes
    a user key column (``tg_user_id``'s unique index is partial, so account deletion's rewrite
    is not a key update either; migration 0005, DECISIONS #16).
    """
    users: dict[int, User] = {}
    for user_id in sorted(set(user_ids)):
        user = await session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if user is not None:
            users[user_id] = user
    return users


async def find_active(
    session: AsyncSession, user_id: int, *, lock: bool = False
) -> Partnership | None:
    query = select(Partnership).where(
        Partnership.status == PartnershipStatus.ACTIVE,
        or_(Partnership.user_a_id == user_id, Partnership.user_b_id == user_id),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    partnership: Partnership | None = await session.scalar(query)
    return partnership


async def companion_card(session: AsyncSession, user: User) -> CompanionCard:
    character = await session.scalar(select(Character).where(Character.user_id == user.id))
    return CompanionCard(
        user_id=user.id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        avatar_file_id=user.avatar_file_id,
        character_name=character.name if character else None,
        nickname=character.nickname if character else None,
        level=level_for_xp(character.total_xp) if character else 1,
    )


def _notify(
    session: AsyncSession,
    recipient_id: int,
    type_: str,
    partnership_id: int,
    payload: dict[str, str],
) -> None:
    session.add(
        Notification(
            recipient_id=recipient_id,
            type=type_,
            category=NotificationCategory.QUESTS,
            entity_type="partnership",
            entity_id=partnership_id,
            payload=payload,
        )
    )


async def _revoke_pending(session: AsyncSession, creator_id: int) -> None:
    await session.execute(
        update(PartnershipInvitation)
        .where(
            PartnershipInvitation.creator_id == creator_id,
            PartnershipInvitation.status == InvitationStatus.PENDING,
        )
        .values(status=InvitationStatus.REVOKED)
    )


# --- invitations -----------------------------------------------------------------------------


async def create_invitation(
    session: AsyncSession, user: User, settings: Settings
) -> InvitationCreated:
    """Revoke my pending invite (if any) and issue a new one."""
    locked = (await lock_users(session, [user.id]))[user.id]
    if locked.onboarded_at is None:
        raise NotOnboardedError
    if await find_active(session, user.id) is not None:
        raise AlreadyPartneredError
    token = secrets.token_urlsafe(TOKEN_BYTES)
    link = invite_link(settings, token)
    await _revoke_pending(session, user.id)
    expires_at = clock.now() + INVITE_TTL
    session.add(
        PartnershipInvitation(
            creator_id=user.id,
            token_hash=hash_token(token),
            status=InvitationStatus.PENDING,
            expires_at=expires_at,
        )
    )
    await session.commit()
    return InvitationCreated(token=token, link=link, expires_at=expires_at)


async def revoke_invitation(session: AsyncSession, user: User) -> None:
    await lock_users(session, [user.id])
    await _revoke_pending(session, user.id)
    await session.commit()


async def _usable_invitation(
    session: AsyncSession, token: str, user: User, *, lock: bool
) -> PartnershipInvitation:
    query = select(PartnershipInvitation).where(
        PartnershipInvitation.token_hash == hash_token(token)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    invitation: PartnershipInvitation | None = await session.scalar(query)
    if invitation is None:
        raise InvitationNotFoundError
    if invitation.creator_id == user.id:
        raise OwnInvitationError
    if invitation.status == InvitationStatus.EXPIRED:
        raise InvitationExpiredError
    if invitation.status != InvitationStatus.PENDING:
        raise InvitationUsedError
    if invitation.expires_at <= clock.now():
        raise InvitationExpiredError
    return invitation


async def preview_invitation(session: AsyncSession, user: User, token: str) -> InvitationPreview:
    invitation = await _usable_invitation(session, token, user, lock=False)
    inviter = await session.get(User, invitation.creator_id)
    if inviter is None or inviter.deleted_at is not None:
        raise InvitationNotFoundError
    return InvitationPreview(
        inviter=await companion_card(session, inviter), expires_at=invitation.expires_at
    )


async def _restore_rewards(session: AsyncSession, partnership_id: int) -> None:
    """Undo ``end_partnership``'s hiding, and only that: rewards it hid (flagged) go back to
    active, or sold_out when nothing is left. Rewards hidden by their creator stay hidden."""
    rewards = await session.scalars(
        select(Reward)
        .where(
            Reward.partnership_id == partnership_id,
            Reward.status == RewardStatus.HIDDEN,
            Reward.hidden_by_partnership_end.is_(True),
        )
        .with_for_update()
    )
    for reward in rewards:
        sold_out = reward.quantity_remaining is not None and reward.quantity_remaining <= 0
        reward.status = RewardStatus.SOLD_OUT if sold_out else RewardStatus.ACTIVE
        reward.hidden_by_partnership_end = False


async def accept_invitation(session: AsyncSession, user: User, token: str) -> AcceptOut:
    """Pair me with the invitation's creator: a new partnership, or the reactivated row of our
    earlier one (with its wallets, rewards and history). One transaction."""
    probe = await _usable_invitation(session, token, user, lock=False)
    users = await lock_users(session, [probe.creator_id, user.id])
    invitation = await _usable_invitation(session, token, user, lock=True)
    me, creator = users.get(user.id), users.get(invitation.creator_id)
    if me is None or me.deleted_at is not None:  # pragma: no cover - current_user checked it
        raise NotOnboardedError
    if creator is None or creator.deleted_at is not None:
        raise InvitationNotFoundError
    if me.onboarded_at is None:
        raise NotOnboardedError
    if await find_active(session, me.id) or await find_active(session, creator.id):
        raise AlreadyPartneredError

    now = clock.now()
    a, b = sorted((me.id, creator.id))
    partnership: Partnership | None = await session.scalar(
        select(Partnership)
        .where(Partnership.user_a_id == a, Partnership.user_b_id == b)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    reactivated = partnership is not None
    try:
        if partnership is None:
            partnership = Partnership(
                user_a_id=a, user_b_id=b, status=PartnershipStatus.ACTIVE, accepted_at=now
            )
            session.add(partnership)
        else:
            partnership.status = PartnershipStatus.ACTIVE
            partnership.accepted_at = now
            partnership.ended_at = None
            partnership.ended_by = None
        await session.flush()
    except IntegrityError:
        # partnership_one_active_per_user: a concurrent pairing won the race.
        await session.rollback()
        raise AlreadyPartneredError from None
    if reactivated:
        await _restore_rewards(session, partnership.id)
    await session.execute(
        insert(Wallet)
        .values(
            [{"user_id": uid, "partnership_id": partnership.id, "balance": 0} for uid in (a, b)]
        )
        .on_conflict_do_nothing(index_elements=[Wallet.user_id, Wallet.partnership_id])
    )
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_by = me.id
    invitation.accepted_at = now
    await _revoke_pending(session, me.id)
    _notify(session, creator.id, "partnership_accepted", partnership.id, {})
    await session.commit()
    return AcceptOut(
        partnership=ActivePartnershipOut(
            id=partnership.id,
            accepted_at=partnership.accepted_at,
            companion=await companion_card(session, creator),
        ),
        reactivated=reactivated,
    )


# --- leaving ---------------------------------------------------------------------------------


async def end_partnership(
    session: AsyncSession, partnership: Partnership, by: User, *, payload: dict[str, str]
) -> None:
    """Every side effect of ending a (locked, active) partnership, without committing."""
    now = clock.now()
    partnership.status = PartnershipStatus.ENDED
    partnership.ended_at = now
    partnership.ended_by = by.id
    templates = select(QuestTemplate.id).where(QuestTemplate.partnership_id == partnership.id)
    await session.execute(
        update(QuestOccurrence)
        .where(
            QuestOccurrence.template_id.in_(templates),
            QuestOccurrence.status.in_(OPEN_OCCURRENCE_STATUSES),
        )
        .values(status=QuestOccurrenceStatus.CANCELLED, cancelled_by=by.id)
    )
    await session.execute(
        update(QuestTemplate)
        .where(
            QuestTemplate.partnership_id == partnership.id,
            QuestTemplate.status.in_(OPEN_TEMPLATE_STATUSES),
        )
        .values(status=QuestTemplateStatus.CANCELLED)
    )
    # Pending revisions (and pending offer revisions) die with their quests: superseded, so a
    # later re-pair cannot accept or decline terms on a closed quest (DECISIONS #15).
    await session.execute(
        update(QuestRevision)
        .where(
            QuestRevision.template_id.in_(templates),
            QuestRevision.status == QuestRevisionStatus.PENDING,
        )
        .values(status=QuestRevisionStatus.SUPERSEDED, decided_at=now)
    )
    await session.execute(
        update(Reward)
        .where(Reward.partnership_id == partnership.id, Reward.status != RewardStatus.HIDDEN)
        .values(status=RewardStatus.HIDDEN, hidden_by_partnership_end=True, updated_at=now)
    )
    # Wallets are frozen by the partnership status itself: purchases require an active
    # partnership; refunds may still credit them. Ledger rows are never touched.
    _notify(session, companion_of(partnership, by.id), "partnership_ended", partnership.id, payload)
    await session.flush()


async def lock_active_partnership(
    session: AsyncSession, user: User
) -> tuple[Partnership | None, dict[int, User]]:
    """Lock both members (by id) and then my active partnership row; re-checked after locking."""
    found = await find_active(session, user.id)
    ids = [user.id] if found is None else [found.user_a_id, found.user_b_id]
    users = await lock_users(session, ids)
    partnership = await find_active(session, user.id, lock=True)
    if partnership is not None and partnership.id != (found.id if found else None):
        # Changed between the probe and the lock (practically impossible): lock the new pair.
        users |= await lock_users(session, [partnership.user_a_id, partnership.user_b_id])
    return partnership, users


async def leave(session: AsyncSession, user: User, confirm_text: str) -> None:
    if confirm_text.strip() != LEAVE_CONFIRM_TEXT:
        raise WrongConfirmationError
    partnership, users = await lock_active_partnership(session, user)
    if partnership is None:
        raise NotPartneredError
    # No names in the payload: the partner's inbox must not keep my PII after a deletion.
    await end_partnership(session, partnership, users[user.id], payload={"reason": "left"})
    await session.commit()


# --- read models -----------------------------------------------------------------------------


async def state(session: AsyncSession, user: User) -> PartnershipStateOut:
    partnership = await find_active(session, user.id)
    active: ActivePartnershipOut | None = None
    if partnership is not None:
        companion = await session.get(User, companion_of(partnership, user.id))
        if companion is not None and companion.deleted_at is None:
            active = ActivePartnershipOut(
                id=partnership.id,
                accepted_at=partnership.accepted_at,
                companion=await companion_card(session, companion),
            )
    pending_expires: datetime | None = await session.scalar(
        select(PartnershipInvitation.expires_at).where(
            PartnershipInvitation.creator_id == user.id,
            PartnershipInvitation.status == InvitationStatus.PENDING,
            PartnershipInvitation.expires_at > clock.now(),
        )
    )
    return PartnershipStateOut(
        partnership=active,
        pending_invitation=PendingInvitationOut(expires_at=pending_expires)
        if pending_expires
        else None,
    )


@dataclass(frozen=True, slots=True)
class _Companion:
    user: User
    character: Character | None


async def _active_companion(session: AsyncSession, user: User) -> _Companion:
    partnership = await find_active(session, user.id)
    if partnership is None:
        raise NotPartneredError
    companion = await session.get(User, companion_of(partnership, user.id))
    if companion is None or companion.deleted_at is not None:
        raise NotPartneredError
    character = await session.scalar(select(Character).where(Character.user_id == companion.id))
    return _Companion(companion, character)


async def companion_profile(session: AsyncSession, user: User) -> CompanionProfileOut:
    found = await _active_companion(session, user)
    companion, character = found.user, found.character
    xp_by_attribute: dict[Attribute, int] = {}
    if character is not None:
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
    total_xp = character.total_xp if character else 0
    progress = progress_for_xp(total_xp)
    goals = await session.scalars(
        select(DevelopmentGoal)
        .where(DevelopmentGoal.user_id == companion.id, DevelopmentGoal.status == GoalStatus.ACTIVE)
        .order_by(DevelopmentGoal.id)
    )
    wishes = await session.scalars(
        select(WishlistItem)
        .where(WishlistItem.user_id == companion.id, WishlistItem.status != WishlistStatus.ARCHIVED)
        .order_by(WishlistItem.id)
    )
    return CompanionProfileOut(
        card=await companion_card(session, companion),
        bio=character.bio if character else None,
        total_xp=total_xp,
        xp_into_level=progress.xp_into_level,
        xp_for_next_level=progress.xp_for_next_level,
        attributes=attributes,
        goals=[CompanionGoalOut.model_validate(g) for g in goals],
        wishlist=[CompanionWishOut.model_validate(w) for w in wishes],
    )
