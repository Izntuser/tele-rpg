"""Quest completion: submit, confirm, request-redo and auto-confirm (ARCHITECTURE §4 "Confirm
transaction", project.md §8, DECISIONS #16).

Who may do what (403 otherwise; non-members get 404):

- the assignee submits (an ``active`` occurrence, before its ``due_at``);
- the creator confirms or requests a redo (an ``in_review`` occurrence); the assignee can never
  confirm their own quest.

``complete_occurrence`` is the only code that pays a quest out, used by both ``confirm`` and
the auto-confirm path of ``submit``. In one transaction it moves the occurrence to
``completed`` (and a one-time template to ``completed``), credits the assignee's wallet with
ledger key ``quest:{occurrence_id}``, writes the ``xp_transaction``, adds the XP to the
character and the quest's attribute, updates a daily quest's streak, and writes journal events
(``quest_completed``, ``level_up``, ``attribute_level_up``) and the notification.

Exactly once: the occurrence row lock plus the state machine (only ``in_review`` can be
confirmed) serialize racing confirms; the unique ledger key and the unique
``xp_transaction.quest_occurrence_id`` are a second, database-level guard. Gold and XP come
only from the occurrence's ``terms_snapshot``, never from the request.

Lock order (extends ``quests.service``): partnership ``FOR SHARE`` -> template -> occurrence ->
its pending revision / submission -> wallet -> character -> character attribute -> streak.
With an ``Idempotency-Key`` the ``idempotency_key`` row is claimed first (``core.idempotency``).
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.idempotency import Claim
from app.modules.common.enums import (
    ConfirmationMode,
    FileKind,
    NotificationCategory,
    PartnershipStatus,
    QuestOccurrenceStatus,
    Recurrence,
    SubmissionReviewStatus,
)
from app.modules.economy import service as economy
from app.modules.economy.models import Wallet
from app.modules.files.models import File
from app.modules.journal.service import record_event
from app.modules.notifications.service import enqueue, quest_deep_link
from app.modules.partnerships.models import Partnership
from app.modules.progression import service as progression
from app.modules.quests import service, state
from app.modules.quests.models import QuestOccurrence, QuestStreak, QuestSubmission, QuestTemplate
from app.modules.quests.schemas import (
    CompletionOut,
    ConfirmIn,
    QuestActionResult,
    QuestTerms,
    RedoIn,
    SubmitIn,
)
from app.modules.users.models import User


def _payload(
    template: QuestTemplate, occurrence: QuestOccurrence, terms: QuestTerms
) -> dict[str, object]:
    return {
        "template_id": template.id,
        "occurrence_id": occurrence.id,
        "title": terms.title,
        "recurrence": template.recurrence.value,
        "difficulty": terms.difficulty.value,
        "attribute": terms.attribute.value,
        "gold": terms.gold,
        "xp": terms.xp,
    }


async def _latest_pending_submission(
    session: AsyncSession, occurrence: QuestOccurrence
) -> QuestSubmission | None:
    submission: QuestSubmission | None = await session.scalar(
        select(QuestSubmission)
        .where(
            QuestSubmission.occurrence_id == occurrence.id,
            QuestSubmission.review_status == SubmissionReviewStatus.PENDING,
        )
        .order_by(QuestSubmission.id.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return submission


async def _ensure_payable(
    session: AsyncSession, partnership: Partnership, template: QuestTemplate
) -> None:
    """Never pay out on an ended partnership or to / from a deleted member (409)."""
    if partnership.status != PartnershipStatus.ACTIVE:
        raise service.PartnershipInactiveError
    for user_id in (template.creator_id, template.assignee_id):
        member = await session.get(User, user_id, populate_existing=True)
        if member is None or member.deleted_at is not None:
            raise service.PartnershipInactiveError


async def _update_streak(session: AsyncSession, template: QuestTemplate, day: date) -> None:
    """Daily quests only: consecutive completed days (by scheduled date). Completing an older
    day late (a slow review) never moves the streak backwards."""
    await session.execute(
        insert(QuestStreak)
        .values(template_id=template.id, current=0, best=0)
        .on_conflict_do_nothing(index_elements=[QuestStreak.template_id])
    )
    streak = await session.scalar(
        select(QuestStreak)
        .where(QuestStreak.template_id == template.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert streak is not None
    last = streak.last_completed_date
    if last is not None and day <= last:
        return
    consecutive = last is not None and last + timedelta(days=1) == day
    streak.current = streak.current + 1 if consecutive else 1
    streak.best = max(streak.best, streak.current)
    streak.last_completed_date = day


async def complete_occurrence(
    session: AsyncSession,
    *,
    partnership: Partnership,
    template: QuestTemplate,
    occurrence: QuestOccurrence,
    submission: QuestSubmission | None,
    actor_id: int,
    feedback: str | None = None,
) -> CompletionOut:
    """Complete a locked ``in_review`` occurrence and pay it out (no commit)."""
    await _ensure_payable(session, partnership, template)
    now = clock.now()
    try:
        occurrence.status = state.next_occurrence_status(occurrence.status, "confirm")
        if template.recurrence == Recurrence.ONCE:
            template.status = state.next_template_status(template.status, "complete")
    except state.InvalidTransitionError as exc:
        raise service.QuestStateError(str(exc)) from None
    occurrence.completed_at = now
    if template.recurrence == Recurrence.ONCE:
        await service.supersede_pending(session, template)
    if submission is not None:
        submission.review_status = SubmissionReviewStatus.APPROVED
        submission.review_comment = feedback
        submission.reviewed_at = now
    await session.flush()

    terms = QuestTerms.model_validate(occurrence.terms_snapshot)
    assignee_id = occurrence.assignee_id
    try:
        ledger = await economy.credit_quest_reward(
            session,
            user_id=assignee_id,
            partnership_id=partnership.id,
            occurrence_id=occurrence.id,
            gold=terms.gold,
        )
        award = await progression.award_quest_xp(
            session,
            user_id=assignee_id,
            occurrence_id=occurrence.id,
            xp=terms.xp,
            attribute=terms.attribute,
        )
    except (economy.DuplicateLedgerEntryError, progression.DuplicateXpAwardError):
        raise service.QuestStateError("the quest was already rewarded") from None
    except progression.NoCharacterError:  # pragma: no cover - players are onboarded
        raise service.QuestStateError("the player has no character") from None
    if template.recurrence == Recurrence.DAILY:
        await _update_streak(session, template, occurrence.scheduled_date)

    wallet = await session.get(Wallet, ledger.wallet_id)
    assert wallet is not None
    auto = actor_id == assignee_id
    payload = {**_payload(template, occurrence, terms), "auto_confirmed": auto}
    record_event(
        session,
        user_id=assignee_id,
        type="quest_completed",
        partnership_id=partnership.id,
        entity_type="quest_occurrence",
        entity_id=occurrence.id,
        payload=payload,
    )
    if award.level.gained:
        record_event(
            session,
            user_id=assignee_id,
            type="level_up",
            partnership_id=partnership.id,
            entity_type="quest_occurrence",
            entity_id=occurrence.id,
            payload={
                "occurrence_id": occurrence.id,
                "previous_level": award.level.before,
                "level": award.level.after,
            },
        )
    if award.attribute_level.gained:
        record_event(
            session,
            user_id=assignee_id,
            type="attribute_level_up",
            partnership_id=partnership.id,
            entity_type="quest_occurrence",
            entity_id=occurrence.id,
            payload={
                "occurrence_id": occurrence.id,
                "attribute": award.attribute.value,
                "previous_level": award.attribute_level.before,
                "level": award.attribute_level.after,
            },
        )
    # The other side learns about it: the player that it was confirmed, the creator that an
    # auto-confirm quest was completed.
    enqueue(
        session,
        recipient_id=template.creator_id if auto else assignee_id,
        type="quest_completed" if auto else "quest_confirmed",
        category=NotificationCategory.QUESTS if auto else NotificationCategory.REVIEWS,
        entity_type="quest_occurrence",
        entity_id=occurrence.id,
        payload=payload,
        deep_link=quest_deep_link(occurrence.id),
    )
    await session.flush()
    return CompletionOut(
        gold=ledger.amount,
        xp=award.xp,
        attribute=award.attribute,
        attribute_xp=award.attribute_xp,
        total_xp=award.total_xp,
        level_before=award.level.before,
        level=award.level.after,
        attribute_level_before=award.attribute_level.before,
        attribute_level=award.attribute_level.after,
        balance=wallet.balance,
    )


async def _finish(
    session: AsyncSession,
    user: User,
    occurrence_id: int,
    completion: CompletionOut | None,
    idempotency: Claim | None,
) -> QuestActionResult:
    """Build the response inside the transaction, store it for the Idempotency-Key, commit."""
    detail = await service.get_occurrence(session, user, occurrence_id)
    result = QuestActionResult(**detail.model_dump(), completion=completion)
    if idempotency is not None:
        await idempotency.store(session, 200, result.model_dump(mode="json"))
    await session.commit()
    return result


async def submit(
    session: AsyncSession,
    user: User,
    occurrence_id: int,
    data: SubmitIn,
    *,
    idempotency: Claim | None = None,
) -> QuestActionResult:
    """Assignee: report an active occurrence as done. Manual quests go to review; auto-confirm
    quests are completed and paid out right away by ``complete_occurrence``."""
    locked = await service.lock_quest(session, user, occurrence_id=occurrence_id)
    template, occurrence = locked.template, locked.occurrence
    assert occurrence is not None
    if locked.role != "player" or occurrence.assignee_id != user.id:
        raise service.WrongRoleError
    now = clock.now()
    try:
        next_status = state.next_occurrence_status(occurrence.status, "submit")
    except state.InvalidTransitionError as exc:
        raise service.QuestStateError(str(exc)) from None
    if occurrence.due_at is not None and occurrence.due_at <= now:
        raise service.QuestStateError("the quest's deadline has passed")
    terms = QuestTerms.model_validate(occurrence.terms_snapshot)
    if data.attachment_id is not None:
        attachment = await session.get(File, data.attachment_id)
        if (
            attachment is None
            or attachment.owner_id != user.id
            or attachment.kind != FileKind.QUEST_PHOTO
        ):
            raise service.InvalidAttachmentError
    elif terms.photo_required:
        raise service.PhotoRequiredError

    occurrence.status = next_status
    occurrence.submitted_at = now
    submission = QuestSubmission(
        occurrence_id=occurrence.id,
        submitted_by=user.id,
        comment=data.comment,
        attachment_id=data.attachment_id,
        review_status=SubmissionReviewStatus.PENDING,
    )
    session.add(submission)
    if template.recurrence == Recurrence.ONCE:
        # The player submitted against the accepted terms; a proposal still pending for this
        # (only) occurrence can no longer apply to it (DECISIONS #16).
        await service.supersede_pending(session, template)
    await session.flush()

    completion: CompletionOut | None = None
    if terms.confirmation == ConfirmationMode.AUTO:
        completion = await complete_occurrence(
            session,
            partnership=locked.partnership,
            template=template,
            occurrence=occurrence,
            submission=submission,
            actor_id=user.id,
        )
    else:
        # Free text (the comment) stays on the submission row, never in payloads.
        service.quest_event(
            session,
            user.id,
            "quest_submitted",
            template,
            occurrence,
            terms,
            category=NotificationCategory.REVIEWS,
        )
    return await _finish(session, user, occurrence.id, completion, idempotency)


async def _lock_for_review(
    session: AsyncSession, user: User, occurrence_id: int
) -> tuple[service.Locked, QuestOccurrence]:
    locked = await service.lock_quest(session, user, occurrence_id=occurrence_id)
    occurrence = locked.occurrence
    assert occurrence is not None
    if locked.role != "gm" or locked.template.creator_id != user.id:
        raise service.WrongRoleError
    return locked, occurrence


async def confirm(
    session: AsyncSession,
    user: User,
    occurrence_id: int,
    data: ConfirmIn,
    *,
    idempotency: Claim | None = None,
) -> QuestActionResult:
    """Creator: approve the submission of an in-review occurrence and pay it out."""
    locked, occurrence = await _lock_for_review(session, user, occurrence_id)
    if occurrence.status != QuestOccurrenceStatus.IN_REVIEW:
        raise service.QuestStateError(f"cannot confirm a quest that is {occurrence.status.value}")
    submission = await _latest_pending_submission(session, occurrence)
    completion = await complete_occurrence(
        session,
        partnership=locked.partnership,
        template=locked.template,
        occurrence=occurrence,
        submission=submission,
        actor_id=user.id,
        feedback=data.feedback,
    )
    return await _finish(session, user, occurrence.id, completion, idempotency)


async def request_redo(
    session: AsyncSession, user: User, occurrence_id: int, data: RedoIn
) -> QuestActionResult:
    """Creator: send an in-review occurrence back to ``active`` with a reason (kept on the
    submission row, never in payloads). No Gold or XP changes."""
    locked, occurrence = await _lock_for_review(session, user, occurrence_id)
    template = locked.template
    try:
        occurrence.status = state.next_occurrence_status(occurrence.status, "request_redo")
    except state.InvalidTransitionError as exc:
        raise service.QuestStateError(str(exc)) from None
    submission = await _latest_pending_submission(session, occurrence)
    if submission is not None:
        submission.review_status = SubmissionReviewStatus.REDO
        submission.review_comment = data.reason
        submission.reviewed_at = clock.now()
    await session.flush()
    service.quest_event(
        session,
        user.id,
        "quest_redo_requested",
        template,
        occurrence,
        QuestTerms.model_validate(occurrence.terms_snapshot),
        category=NotificationCategory.REVIEWS,
    )
    return await _finish(session, user, occurrence.id, None, None)
