"""GDPR-lite: export my data, delete my account (ARCHITECTURE §4 "Account deletion").

Deletion keeps the ``user`` row (ledger, quests, purchases and the companion's history point at
it) but scrubs it, so the account is gone in every way that matters:

- ``deleted_at`` is set: ``current_user`` rejects every JWT already issued for the account;
- ``tg_user_id`` becomes ``-id`` (Telegram ids are positive, so it can never collide) and the
  Telegram fields are cleared: the same Telegram account logging in again gets a brand-new
  user, with nothing linking it to the deleted one (DECISIONS #13);
- display_name / character name become "Deleted user"; nickname, bio, goals, wishlist, my
  submission comments, my decline reasons, my review comments, my file rows and their stored
  bytes are removed;
- the active partnership is ended exactly like ``leave`` (quests cancelled, rewards hidden,
  wallets frozen, partner notified);
- ledger rows (gold and XP) are never touched, so ``wallet.balance == sum(ledger)`` still holds.
"""

from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import ColumnElement, case, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.core import clock
from app.modules.achievements.models import AchievementUnlock
from app.modules.common.enums import InvitationStatus, JournalVisibility, SubmissionReviewStatus
from app.modules.common.models import IdempotencyKey
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.files import service as files
from app.modules.files.models import File
from app.modules.goals.models import DevelopmentGoal
from app.modules.journal.models import JournalEvent
from app.modules.notifications.models import Notification
from app.modules.partnerships import service as partnerships
from app.modules.partnerships.models import Partnership, PartnershipInvitation
from app.modules.progression.models import XpTransaction
from app.modules.quests.models import (
    QuestOccurrence,
    QuestRevision,
    QuestSubmission,
    QuestTemplate,
    SavedQuestTemplate,
)
from app.modules.rewards.models import Reward, RewardPurchase
from app.modules.stats.models import LifeBalanceTarget
from app.modules.users.models import Character, CharacterAttribute, User
from app.modules.wishlist.models import WishlistItem
from app.storage.base import StorageBackend, get_storage

DELETE_CONFIRM_TEXT = "DELETE"
DELETED_NAME = "Deleted user"
REDACTED = "[deleted]"
EXPORT_VERSION = 1

#: Columns never exported: secrets, or another person's data.
_EXPORT_EXCLUDE = {"token_hash", "storage_key"}


class WrongConfirmationError(Exception):
    pass


def _row(obj: DeclarativeBase) -> dict[str, Any]:
    data = {
        attr.key: getattr(obj, attr.key)
        for attr in obj.__mapper__.column_attrs
        if attr.key not in _EXPORT_EXCLUDE
    }
    encoded: dict[str, Any] = jsonable_encoder(data)
    return encoded


async def _rows(
    session: AsyncSession, model: type[DeclarativeBase], *where: ColumnElement[bool]
) -> list[dict[str, Any]]:
    pk = model.__mapper__.primary_key
    result = await session.scalars(select(model).where(*where).order_by(*pk))
    return [_row(obj) for obj in result]


async def export(session: AsyncSession, user: User) -> dict[str, Any]:
    """Everything stored about me or written by me. Other people appear only as ids."""
    me = user.id
    character = await session.scalar(select(Character).where(Character.user_id == me))
    character_id = character.id if character else -1
    my_partnerships = or_(Partnership.user_a_id == me, Partnership.user_b_id == me)
    my_templates = or_(QuestTemplate.creator_id == me, QuestTemplate.assignee_id == me)
    return {
        "format": "tele-rpg-export",
        "version": EXPORT_VERSION,
        "exported_at": clock.now().isoformat(),
        "user": _row(user),
        "character": _row(character) if character else None,
        "character_attributes": await _rows(
            session, CharacterAttribute, CharacterAttribute.character_id == character_id
        ),
        "development_goals": await _rows(session, DevelopmentGoal, DevelopmentGoal.user_id == me),
        "wishlist": await _rows(session, WishlistItem, WishlistItem.user_id == me),
        "partnerships": await _rows(session, Partnership, my_partnerships),
        "invitations": await _rows(
            session, PartnershipInvitation, PartnershipInvitation.creator_id == me
        ),
        "wallets": await _rows(session, Wallet, Wallet.user_id == me),
        "gold_transactions": await _rows(session, GoldTransaction, GoldTransaction.user_id == me),
        "xp_transactions": await _rows(session, XpTransaction, XpTransaction.user_id == me),
        "quest_templates": await _rows(session, QuestTemplate, my_templates),
        "quest_occurrences": await _rows(
            session,
            QuestOccurrence,
            QuestOccurrence.template_id.in_(select(QuestTemplate.id).where(my_templates)),
        ),
        "quest_submissions": await _rows(
            session, QuestSubmission, QuestSubmission.submitted_by == me
        ),
        "saved_quest_templates": await _rows(
            session, SavedQuestTemplate, SavedQuestTemplate.owner_id == me
        ),
        "rewards": await _rows(session, Reward, Reward.creator_id == me),
        "reward_purchases": await _rows(
            session,
            RewardPurchase,
            or_(RewardPurchase.buyer_id == me, RewardPurchase.provider_id == me),
        ),
        "journal_events": await _rows(session, JournalEvent, JournalEvent.user_id == me),
        "achievements": await _rows(session, AchievementUnlock, AchievementUnlock.user_id == me),
        "life_balance_targets": await _rows(
            session, LifeBalanceTarget, LifeBalanceTarget.user_id == me
        ),
        "notifications": await _rows(session, Notification, Notification.recipient_id == me),
        "files": await _rows(session, File, File.owner_id == me),
    }


async def _scrub(session: AsyncSession, user: User) -> list[str]:
    """Scrub the account; returns the storage keys of the deleted file rows."""
    me = user.id
    now = clock.now()
    my_files = select(File.id).where(File.owner_id == me)
    my_wishes = select(WishlistItem.id).where(WishlistItem.user_id == me)
    templates_by_me = select(QuestTemplate.id).where(QuestTemplate.creator_id == me)
    occurrences_by_me = select(QuestOccurrence.id).where(
        QuestOccurrence.template_id.in_(templates_by_me)
    )

    # Reward rows before purchase rows, the order refund uses (reward -> purchase).
    await session.execute(
        update(Reward).where(Reward.image_file_id.in_(my_files)).values(image_file_id=None)
    )
    await session.execute(
        update(Reward)
        .where(Reward.source_wishlist_item_id.in_(my_wishes))
        .values(source_wishlist_item_id=None)
    )
    await session.execute(
        update(RewardPurchase)
        .where(RewardPurchase.provider_id == me, RewardPurchase.schedule_note.is_not(None))
        .values(schedule_note=None)
    )

    # Free text I wrote on shared records.
    await session.execute(
        update(QuestSubmission).where(QuestSubmission.submitted_by == me).values(comment=None)
    )
    await session.execute(
        update(QuestSubmission)
        .where(
            QuestSubmission.occurrence_id.in_(occurrences_by_me),
            QuestSubmission.review_comment.is_not(None),
        )
        .values(review_comment=None)
        .where(QuestSubmission.review_status != SubmissionReviewStatus.REDO)
    )
    await session.execute(
        update(QuestSubmission)
        .where(
            QuestSubmission.occurrence_id.in_(occurrences_by_me),
            QuestSubmission.review_status == SubmissionReviewStatus.REDO,
        )
        .values(review_comment=REDACTED)  # ck_redo_requires_comment needs some text
    )
    await session.execute(
        update(QuestOccurrence)
        .where(QuestOccurrence.assignee_id == me, QuestOccurrence.decline_reason.is_not(None))
        .values(decline_reason=None)
    )
    await session.execute(
        update(QuestRevision)
        .where(
            QuestRevision.template_id.in_(
                select(QuestTemplate.id).where(QuestTemplate.assignee_id == me)
            ),
            QuestRevision.decline_reason.is_not(None),
        )
        .values(decline_reason=None)
    )

    # Files: drop every reference, then the rows; the caller deletes the bytes after commit.
    await session.execute(
        update(QuestSubmission)
        .where(QuestSubmission.attachment_id.in_(my_files))
        .values(attachment_id=None)
    )
    user.avatar_file_id = None
    await session.flush()
    storage_keys = list(await session.scalars(select(File.storage_key).where(File.owner_id == me)))
    await session.execute(delete(File).where(File.owner_id == me))

    # Personal lists and private data.
    await session.execute(delete(WishlistItem).where(WishlistItem.user_id == me))
    await session.execute(delete(DevelopmentGoal).where(DevelopmentGoal.user_id == me))
    await session.execute(delete(SavedQuestTemplate).where(SavedQuestTemplate.owner_id == me))
    await session.execute(delete(LifeBalanceTarget).where(LifeBalanceTarget.user_id == me))
    await session.execute(delete(Notification).where(Notification.recipient_id == me))
    # Stored Idempotency-Key responses (quest details) carry free text of both members, so the
    # rows of everyone I was ever partnered with go too, not only mine (DECISIONS #16).
    companions = select(
        case((Partnership.user_a_id == me, Partnership.user_b_id), else_=Partnership.user_a_id)
    ).where(or_(Partnership.user_a_id == me, Partnership.user_b_id == me))
    await session.execute(
        delete(IdempotencyKey).where(
            or_(IdempotencyKey.user_id == me, IdempotencyKey.user_id.in_(companions))
        )
    )
    await session.execute(
        delete(JournalEvent).where(
            JournalEvent.user_id == me, JournalEvent.visibility == JournalVisibility.PRIVATE
        )
    )
    await session.execute(
        update(PartnershipInvitation)
        .where(
            PartnershipInvitation.creator_id == me,
            PartnershipInvitation.status == InvitationStatus.PENDING,
        )
        .values(status=InvitationStatus.REVOKED)
    )

    character = await session.scalar(
        select(Character).where(Character.user_id == me).with_for_update()
    )
    if character is not None:
        character.name = DELETED_NAME
        character.nickname = None
        character.bio = None

    user.tg_user_id = -me
    user.tg_username = None
    user.display_name = DELETED_NAME
    user.avatar_url = None
    user.can_message = False
    user.notification_prefs = {}
    user.deleted_at = now
    user.updated_at = now
    return storage_keys


async def delete_account(
    session: AsyncSession,
    user: User,
    confirm_text: str,
    storage: StorageBackend | None = None,
) -> None:
    """One transaction: end the partnership (as ``leave`` does), then scrub. After the commit
    the stored bytes of my files are deleted (best effort: a failure leaves an orphan blob that
    no row points at, never a row without consent)."""
    if confirm_text.strip() != DELETE_CONFIRM_TEXT:
        raise WrongConfirmationError
    partnership, users = await partnerships.lock_active_partnership(session, user)
    me = users[user.id]
    if me.deleted_at is not None:  # pragma: no cover - current_user rejects deleted users
        return
    if partnership is not None:
        await partnerships.end_partnership(
            session, partnership, me, payload={"reason": "account_deleted"}
        )
    storage_keys = await _scrub(session, me)
    await session.commit()
    await files.discard(storage or get_storage(), storage_keys)
