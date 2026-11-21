"""Quest offer flow: create, edit / propose a revision, accept, decline, cancel, and the read
models for lists and details (ARCHITECTURE §2 "Quests", §4, DECISIONS #15).

Rules kept here:

- only the two members of a quest's partnership ever see it: anyone else gets
  ``QuestNotFoundError`` (404), never a hint that the id exists;
- the assignee accepts and declines, the creator edits, either may cancel (403 otherwise);
- every status change goes through ``quests.state`` (409 for a forbidden one);
- writes need the partnership to be active;
- lock order: the partnership row ``FOR SHARE`` (so ``leave`` / account deletion, which lock it
  ``FOR UPDATE``, serialize with us and see our rows), then the template, then its occurrence /
  revision ``FOR UPDATE``. Two racing commands on one quest serialize on the template row and
  the loser re-reads the committed status;
- each transition writes a journal event and a notification in the same transaction.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import Settings, get_settings
from app.modules.common.enums import (
    NotificationCategory,
    PartnershipStatus,
    QuestOccurrenceStatus,
    QuestRevisionStatus,
    QuestTemplateStatus,
    Recurrence,
)
from app.modules.journal.service import record_event
from app.modules.notifications.service import enqueue, quest_deep_link
from app.modules.partnerships.models import Partnership
from app.modules.partnerships.service import find_active
from app.modules.quests import state
from app.modules.quests.models import (
    QuestOccurrence,
    QuestRevision,
    QuestStreak,
    QuestSubmission,
    QuestTemplate,
)
from app.modules.quests.occurrences import ensure_occurrence
from app.modules.quests.schemas import (
    MAX_OPEN_TEMPLATES,
    OccurrenceDetail,
    OccurrenceOut,
    QuestCreate,
    QuestCreated,
    QuestTerms,
    QuestUpdate,
    RevisionOut,
    Role,
    StreakOut,
    SubmissionOut,
    TemplateDetail,
    TemplateOut,
)
from app.modules.users.models import User
from app.modules.users.service import lock_user

OPEN_TEMPLATE_STATUSES = (
    QuestTemplateStatus.OFFERED,
    QuestTemplateStatus.ACTIVE,
    QuestTemplateStatus.PAUSED,
)
#: Template statuses in which the creator may propose a revision.
REVISABLE_TEMPLATE_STATUSES = (QuestTemplateStatus.ACTIVE, QuestTemplateStatus.PAUSED)
#: Occurrences of a recurring template that cancelling the template cancels too.
CANCELLABLE_OCCURRENCE_STATUSES = (QuestOccurrenceStatus.OFFERED, QuestOccurrenceStatus.ACTIVE)
LIST_LIMIT_MAX = 200


class QuestError(Exception):
    """Base class; each subclass maps to one HTTP status in the route."""


class QuestNotFoundError(QuestError):
    """Missing, or the caller is not one of its two members."""


class WrongRoleError(QuestError):
    """The caller is a member but this action belongs to the other one."""


class NotPartneredError(QuestError):
    """Creating a quest needs an active partnership."""


class PartnershipInactiveError(QuestError):
    """The quest's partnership has ended; it is read-only history now."""


class QuestStateError(QuestError):
    """The action is not allowed in the quest's current state."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TooManyQuestsError(QuestError):
    pass


class DeadlineNotAllowedError(QuestError):
    """A deadline on a recurring quest (the create schema rejects it; PATCH lands here)."""


class InvalidAttachmentError(QuestError):
    """``attachment_id`` is not a quest photo uploaded by the submitting assignee for this
    quest's partnership."""


class PhotoRequiredError(QuestError):
    """The quest's terms require a photo and the submission has none."""


# --- helpers ---------------------------------------------------------------------------------


def _role(template: QuestTemplate, user_id: int) -> Role:
    return "gm" if template.creator_id == user_id else "player"


def _other(template: QuestTemplate, user_id: int) -> int:
    return template.assignee_id if template.creator_id == user_id else template.creator_id


def _terms(settings: Settings, values: dict[str, Any]) -> QuestTerms:
    return QuestTerms(
        title=values["title"],
        description=values["description"],
        attribute=values["attribute"],
        difficulty=values["difficulty"],
        gold=values["gold"],
        xp=settings.difficulty_xp[values["difficulty"]],
        deadline=values["deadline"],
        confirmation=values["confirmation"],
        photo_required=values["photo_required"],
    )


def _template_terms(settings: Settings, template: QuestTemplate) -> QuestTerms:
    return _terms(
        settings,
        {
            "title": template.title,
            "description": template.description,
            "attribute": template.attribute,
            "difficulty": template.difficulty,
            "gold": template.gold,
            "deadline": template.deadline_at,
            "confirmation": template.confirmation,
            "photo_required": template.photo_required,
        },
    )


def _apply_terms(template: QuestTemplate, terms: QuestTerms) -> None:
    template.title = terms.title
    template.description = terms.description
    template.attribute = terms.attribute
    template.difficulty = terms.difficulty
    template.gold = terms.gold
    template.deadline_at = terms.deadline
    template.confirmation = terms.confirmation
    template.photo_required = terms.photo_required


def _transition_error(exc: state.InvalidTransitionError) -> QuestStateError:
    return QuestStateError(str(exc))


def _check_revisable(
    template: QuestTemplate, occurrence: QuestOccurrence | None, action: str
) -> None:
    """A pending revision can be decided only on an open quest: an active / paused template
    and, for a one-time quest, its still-active occurrence (409 otherwise)."""
    if template.status not in REVISABLE_TEMPLATE_STATUSES:
        raise QuestStateError(f"cannot {action} a quest that is {template.status.value}")
    if template.recurrence == Recurrence.ONCE and (
        occurrence is None or occurrence.status != QuestOccurrenceStatus.ACTIVE
    ):
        status = occurrence.status.value if occurrence is not None else "missing"
        raise QuestStateError(f"cannot {action} a quest that is {status}")


def _event(
    session: AsyncSession,
    actor_id: int,
    type_: str,
    template: QuestTemplate,
    occurrence: QuestOccurrence | None,
    terms: QuestTerms,
    extra: dict[str, Any] | None = None,
    *,
    category: NotificationCategory = NotificationCategory.QUESTS,
) -> None:
    """Journal event (shared, by the actor) + notification to the other member."""
    entity_type, entity_id = (
        ("quest_occurrence", occurrence.id)
        if occurrence is not None
        else ("quest_template", template.id)
    )
    base: dict[str, Any] = {
        "template_id": template.id,
        "occurrence_id": occurrence.id if occurrence is not None else None,
        "title": terms.title,
        "recurrence": template.recurrence.value,
        "difficulty": terms.difficulty.value,
        "attribute": terms.attribute.value,
        "gold": terms.gold,
        "xp": terms.xp,
        **(extra or {}),
    }
    record_event(
        session,
        user_id=actor_id,
        type=type_,
        partnership_id=template.partnership_id,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=base,
    )
    enqueue(
        session,
        recipient_id=_other(template, actor_id),
        type=type_,
        category=category,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=base,
        deep_link=quest_deep_link(occurrence.id) if occurrence is not None else None,
    )


@dataclass(slots=True)
class _Locked:
    partnership: Partnership
    template: QuestTemplate
    #: The addressed occurrence, or (template-addressed) the single one of a one-time quest.
    occurrence: QuestOccurrence | None
    role: Role


async def _probe_template_id(
    session: AsyncSession, user: User, *, occurrence_id: int | None, template_id: int | None
) -> int:
    query = select(QuestTemplate.id).where(
        or_(QuestTemplate.creator_id == user.id, QuestTemplate.assignee_id == user.id)
    )
    if occurrence_id is not None:
        query = query.join(QuestOccurrence, QuestOccurrence.template_id == QuestTemplate.id).where(
            QuestOccurrence.id == occurrence_id
        )
    else:
        query = query.where(QuestTemplate.id == template_id)
    found: int | None = await session.scalar(query)
    if found is None:
        raise QuestNotFoundError
    return found


async def _lock(
    session: AsyncSession,
    user: User,
    *,
    occurrence_id: int | None = None,
    template_id: int | None = None,
) -> _Locked:
    """Membership check, then locks in the documented order, re-reading committed state."""
    tid = await _probe_template_id(
        session, user, occurrence_id=occurrence_id, template_id=template_id
    )
    partnership_id = await session.scalar(
        select(QuestTemplate.partnership_id).where(QuestTemplate.id == tid)
    )
    partnership = await session.scalar(
        select(Partnership)
        .where(Partnership.id == partnership_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if partnership is None or partnership.status != PartnershipStatus.ACTIVE:
        raise PartnershipInactiveError
    template = await session.scalar(
        select(QuestTemplate)
        .where(QuestTemplate.id == tid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert template is not None
    occurrence_query = select(QuestOccurrence).where(QuestOccurrence.template_id == tid)
    if occurrence_id is not None:
        occurrence_query = occurrence_query.where(QuestOccurrence.id == occurrence_id)
    occurrence: QuestOccurrence | None = None
    if occurrence_id is not None or template.recurrence == Recurrence.ONCE:
        occurrence = await session.scalar(
            occurrence_query.with_for_update().execution_options(populate_existing=True)
        )
    return _Locked(partnership, template, occurrence, _role(template, user.id))


async def _pending_revision(
    session: AsyncSession, template: QuestTemplate, *, lock: bool = False
) -> QuestRevision | None:
    """The revision awaiting the assignee after acceptance (not the offer's revision 1). Only a
    revisable (active / paused) template has one; a closed template never shows a stale one."""
    if template.status not in REVISABLE_TEMPLATE_STATUSES:
        return None
    query = select(QuestRevision).where(
        QuestRevision.template_id == template.id,
        QuestRevision.status == QuestRevisionStatus.PENDING,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    revision: QuestRevision | None = await session.scalar(query)
    return revision


async def _current_revision(session: AsyncSession, template: QuestTemplate) -> QuestRevision:
    revision = await session.scalar(
        select(QuestRevision)
        .where(QuestRevision.id == template.current_revision_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert revision is not None, "every template has a current revision"
    return revision


async def _supersede_pending(session: AsyncSession, template: QuestTemplate) -> list[QuestRevision]:
    """Close the template's pending revision(s); returns the ones it superseded."""
    pending = await session.scalars(
        select(QuestRevision)
        .where(
            QuestRevision.template_id == template.id,
            QuestRevision.status == QuestRevisionStatus.PENDING,
        )
        .with_for_update()
    )
    now = clock.now()
    superseded = list(pending)
    for revision in superseded:
        revision.status = state.next_revision_status(revision.status, "supersede")
        revision.decided_at = now
    await session.flush()
    return superseded


# Shared with ``quests.completion`` (submit / confirm / request-redo): one lock order, one
# event writer, one place that closes a quest's pending revisions.
Locked = _Locked
lock_quest = _lock
quest_event = _event
supersede_pending = _supersede_pending


# --- create ----------------------------------------------------------------------------------


async def create(
    session: AsyncSession, user: User, settings: Settings, data: QuestCreate
) -> QuestCreated:
    """A template offered to my active companion, with revision 1 (the offered terms) and, for
    a one-time quest, its offered occurrence."""
    await lock_user(session, user.id)
    me = await session.get(User, user.id, populate_existing=True)
    if me is None or me.deleted_at is not None:
        raise NotPartneredError
    probe = await find_active(session, user.id)
    if probe is None:
        raise NotPartneredError
    partnership = await session.scalar(
        select(Partnership)
        .where(Partnership.id == probe.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if partnership is None or partnership.status != PartnershipStatus.ACTIVE:
        raise NotPartneredError
    assignee_id = (
        partnership.user_b_id if partnership.user_a_id == user.id else partnership.user_a_id
    )
    assignee = await session.get(User, assignee_id)
    if assignee is None or assignee.deleted_at is not None:  # pragma: no cover - leave ends it
        raise NotPartneredError
    open_count = await session.scalar(
        select(func.count())
        .select_from(QuestTemplate)
        .where(
            QuestTemplate.partnership_id == partnership.id,
            QuestTemplate.creator_id == user.id,
            QuestTemplate.status.in_(OPEN_TEMPLATE_STATUSES),
        )
    )
    if (open_count or 0) >= MAX_OPEN_TEMPLATES:
        raise TooManyQuestsError

    terms = _terms(
        settings,
        {
            "title": data.title,
            "description": data.description,
            "attribute": data.attribute,
            "difficulty": data.difficulty,
            "gold": data.gold,
            "deadline": data.deadline_at,
            "confirmation": data.confirmation,
            "photo_required": data.photo_required,
        },
    )
    template = QuestTemplate(
        partnership_id=partnership.id,
        creator_id=user.id,
        assignee_id=assignee.id,
        recurrence=data.recurrence,
        status=QuestTemplateStatus.OFFERED,
    )
    _apply_terms(template, terms)
    session.add(template)
    await session.flush()
    revision = QuestRevision(
        template_id=template.id,
        version=1,
        terms=terms.to_json(),
        status=QuestRevisionStatus.PENDING,
        proposed_by=user.id,
    )
    session.add(revision)
    await session.flush()
    template.current_revision_id = revision.id
    await session.flush()
    occurrence: QuestOccurrence | None = None
    if template.recurrence == Recurrence.ONCE:
        occurrence, _ = await ensure_occurrence(session, template, assignee.timezone)
    _event(session, user.id, "quest_offered", template, occurrence, terms)
    await session.commit()
    return QuestCreated(
        template=await _template_out(session, template, user.id),
        occurrence=await _occurrence_out(session, occurrence, template, user.id)
        if occurrence is not None
        else None,
    )


# --- edit / revisions ------------------------------------------------------------------------


def _merged_terms(
    settings: Settings, template: QuestTemplate, current: QuestTerms, data: QuestUpdate
) -> QuestTerms:
    values = current.model_dump()
    changes = {
        "deadline" if field == "deadline_at" else field: getattr(data, field)
        for field in data.model_fields_set
    }
    if changes.get("deadline") is not None and template.recurrence != Recurrence.ONCE:
        raise DeadlineNotAllowedError
    values.update(changes)
    return _terms(settings, values)


async def update(
    session: AsyncSession,
    user: User,
    settings: Settings,
    data: QuestUpdate,
    *,
    occurrence_id: int | None = None,
    template_id: int | None = None,
) -> None:
    """Creator only. Offered: edit the offer in place. Active or paused: propose a revision
    (replacing an earlier pending one) that the assignee must accept. Changes are applied to
    the current accepted terms, not to a pending proposal; unchanged terms are a no-op."""
    locked = await _lock(session, user, occurrence_id=occurrence_id, template_id=template_id)
    template, occurrence = locked.template, locked.occurrence
    if locked.role != "gm":
        raise WrongRoleError
    current_revision = await _current_revision(session, template)
    current = QuestTerms.model_validate(current_revision.terms)
    terms = _merged_terms(settings, template, current, data)
    once_occurrence = occurrence if template.recurrence == Recurrence.ONCE else None

    if template.status == QuestTemplateStatus.OFFERED:
        if terms == current:
            return
        _apply_terms(template, terms)
        current_revision.terms = terms.to_json()
        if once_occurrence is not None:
            once_occurrence.terms_snapshot = terms.to_json()
            once_occurrence.due_at = terms.deadline
        enqueue(
            session,
            recipient_id=template.assignee_id,
            type="quest_offer_updated",
            category=NotificationCategory.QUESTS,
            entity_type="quest_occurrence" if once_occurrence else "quest_template",
            entity_id=once_occurrence.id if once_occurrence else template.id,
            payload={"template_id": template.id, "title": terms.title},
            deep_link=quest_deep_link(once_occurrence.id) if once_occurrence else None,
        )
        await session.commit()
        return

    if template.status not in REVISABLE_TEMPLATE_STATUSES:
        raise QuestStateError(f"cannot edit a quest that is {template.status.value}")
    if once_occurrence is not None and once_occurrence.status != QuestOccurrenceStatus.ACTIVE:
        raise QuestStateError(f"cannot edit a quest that is {once_occurrence.status.value}")
    pending = await _pending_revision(session, template, lock=True)
    if terms == current or (
        pending is not None and terms == QuestTerms.model_validate(pending.terms)
    ):
        return
    await _supersede_pending(session, template)
    last_version = await session.scalar(
        select(func.max(QuestRevision.version)).where(QuestRevision.template_id == template.id)
    )
    revision = QuestRevision(
        template_id=template.id,
        version=(last_version or 0) + 1,
        terms=terms.to_json(),
        status=QuestRevisionStatus.PENDING,
        proposed_by=user.id,
    )
    session.add(revision)
    await session.flush()
    _event(
        session,
        user.id,
        "quest_revision_proposed",
        template,
        occurrence,
        terms,
        {"version": revision.version},
    )
    await session.commit()


# --- accept / decline ------------------------------------------------------------------------


async def accept(
    session: AsyncSession,
    user: User,
    *,
    occurrence_id: int | None = None,
    template_id: int | None = None,
) -> int | None:
    """Assignee only: accept the offer, or else the pending revision. Returns the id of the
    occurrence the offer produced (today's, for a recurring quest), if any."""
    locked = await _lock(session, user, occurrence_id=occurrence_id, template_id=template_id)
    template, occurrence = locked.template, locked.occurrence
    if locked.role != "player":
        raise WrongRoleError
    now = clock.now()
    try:
        if template.status == QuestTemplateStatus.OFFERED:
            if occurrence is not None:
                if occurrence.due_at is not None and occurrence.due_at <= now:
                    raise QuestStateError("the offer's deadline has passed")
                occurrence.status = state.next_occurrence_status(occurrence.status, "accept")
                occurrence.accepted_at = now
            template.status = state.next_template_status(template.status, "accept")
            revision = await _current_revision(session, template)
            revision.status = state.next_revision_status(revision.status, "accept")
            revision.decided_at = now
            await session.flush()
            if template.recurrence != Recurrence.ONCE:
                assignee = await session.get(User, template.assignee_id)
                assert assignee is not None
                occurrence, _ = await ensure_occurrence(session, template, assignee.timezone)
            terms = QuestTerms.model_validate(revision.terms)
            _event(session, user.id, "quest_accepted", template, occurrence, terms)
        else:
            _check_revisable(template, occurrence, "accept")
            pending = await _pending_revision(session, template, lock=True)
            if pending is None:
                raise QuestStateError("nothing to accept")
            pending.status = state.next_revision_status(pending.status, "accept")
            pending.decided_at = now
            terms = QuestTerms.model_validate(pending.terms)
            _apply_terms(template, terms)
            template.current_revision_id = pending.id
            # Revisions apply to future occurrences only. A one-time quest has none, so its
            # single occurrence takes the new terms while it is still active (DECISIONS #15).
            if (
                template.recurrence == Recurrence.ONCE
                and occurrence is not None
                and occurrence.status == QuestOccurrenceStatus.ACTIVE
            ):
                occurrence.terms_snapshot = terms.to_json()
                occurrence.due_at = terms.deadline
            _event(
                session,
                user.id,
                "quest_revision_accepted",
                template,
                occurrence,
                terms,
                {"version": pending.version},
            )
    except state.InvalidTransitionError as exc:
        raise _transition_error(exc) from None
    await session.commit()
    return occurrence.id if occurrence is not None else None


async def decline(
    session: AsyncSession,
    user: User,
    reason: str | None,
    *,
    occurrence_id: int | None = None,
    template_id: int | None = None,
) -> None:
    """Assignee only: decline the offer, or else the pending revision."""
    locked = await _lock(session, user, occurrence_id=occurrence_id, template_id=template_id)
    template, occurrence = locked.template, locked.occurrence
    if locked.role != "player":
        raise WrongRoleError
    now = clock.now()
    try:
        if template.status == QuestTemplateStatus.OFFERED:
            if occurrence is not None:
                occurrence.status = state.next_occurrence_status(occurrence.status, "decline")
                occurrence.decline_reason = reason
            template.status = state.next_template_status(template.status, "decline")
            revision = await _current_revision(session, template)
            revision.status = state.next_revision_status(revision.status, "decline")
            revision.decided_at = now
            revision.decline_reason = reason
            type_ = "quest_declined"
            terms = QuestTerms.model_validate(revision.terms)
            extra: dict[str, Any] = {}
        else:
            _check_revisable(template, occurrence, "decline")
            pending = await _pending_revision(session, template, lock=True)
            if pending is None:
                raise QuestStateError("nothing to decline")
            pending.status = state.next_revision_status(pending.status, "decline")
            pending.decided_at = now
            pending.decline_reason = reason
            type_ = "quest_revision_declined"
            terms = QuestTerms.model_validate(pending.terms)
            extra = {"version": pending.version}
    except state.InvalidTransitionError as exc:
        raise _transition_error(exc) from None
    # The reason is free text by the assignee: it stays on the row (scrubbed on deletion) and
    # is never copied into journal or notification payloads.
    _event(session, user.id, type_, template, occurrence, terms, extra)
    await session.commit()


# --- cancel ----------------------------------------------------------------------------------


async def cancel(
    session: AsyncSession,
    user: User,
    *,
    occurrence_id: int | None = None,
    template_id: int | None = None,
) -> None:
    """Either member. An occurrence: that offered/active occurrence (and the template of a
    one-time quest). A template: the template and its offered/active occurrences; an
    occurrence already in review is left to its review."""
    locked = await _lock(session, user, occurrence_id=occurrence_id, template_id=template_id)
    template, occurrence = locked.template, locked.occurrence
    try:
        if occurrence is not None:
            occurrence.status = state.next_occurrence_status(occurrence.status, "cancel")
            occurrence.cancelled_by = user.id
        cancel_template = template_id is not None or template.recurrence == Recurrence.ONCE
        if cancel_template:
            template.status = state.next_template_status(template.status, "cancel")
            if template.recurrence != Recurrence.ONCE:
                others = await session.scalars(
                    select(QuestOccurrence)
                    .where(
                        QuestOccurrence.template_id == template.id,
                        QuestOccurrence.status.in_(CANCELLABLE_OCCURRENCE_STATUSES),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                for other in others:
                    other.status = state.next_occurrence_status(other.status, "cancel")
                    other.cancelled_by = user.id
            await _supersede_pending(session, template)
    except state.InvalidTransitionError as exc:
        raise _transition_error(exc) from None
    revision = await session.get(QuestRevision, template.current_revision_id)
    assert revision is not None
    _event(
        session,
        user.id,
        "quest_cancelled",
        template,
        occurrence,
        QuestTerms.model_validate(
            occurrence.terms_snapshot if occurrence is not None else revision.terms
        ),
    )
    await session.commit()


# --- pause / resume --------------------------------------------------------------------------


async def set_paused(session: AsyncSession, user: User, template_id: int, *, paused: bool) -> None:
    """Creator only, recurring quests only: pause stops the scheduler from generating new
    occurrences (an existing active one stays playable); resume restarts generation and
    creates the current period's occurrence right away (never earlier ones)."""
    locked = await _lock(session, user, template_id=template_id)
    template = locked.template
    if locked.role != "gm":
        raise WrongRoleError
    if template.recurrence == Recurrence.ONCE:
        raise QuestStateError("a one-time quest cannot be paused")
    action: state.Action = "pause" if paused else "resume"
    try:
        template.status = state.next_template_status(template.status, action)
    except state.InvalidTransitionError as exc:
        raise _transition_error(exc) from None
    if not paused:
        assignee = await session.get(User, template.assignee_id)
        assert assignee is not None
        if assignee.deleted_at is None:
            await ensure_occurrence(session, template, assignee.timezone)
    revision = await session.get(QuestRevision, template.current_revision_id)
    assert revision is not None
    _event(
        session,
        user.id,
        "quest_paused" if paused else "quest_resumed",
        template,
        None,
        QuestTerms.model_validate(revision.terms),
    )
    await session.commit()


# --- read models -----------------------------------------------------------------------------


async def _pending_by_template(
    session: AsyncSession, templates: Iterable[QuestTemplate]
) -> dict[int, QuestRevision]:
    ids = [t.id for t in templates if t.status in REVISABLE_TEMPLATE_STATUSES]
    if not ids:
        return {}
    rows = await session.scalars(
        select(QuestRevision).where(
            QuestRevision.template_id.in_(ids),
            QuestRevision.status == QuestRevisionStatus.PENDING,
        )
    )
    return {r.template_id: r for r in rows}


async def _declined_by_template(
    session: AsyncSession, template_ids: Iterable[int]
) -> dict[int, QuestRevision]:
    """The newest declined revision of each template (its reason is shown to both members)."""
    ids = list(template_ids)
    if not ids:
        return {}
    rows = await session.scalars(
        select(QuestRevision)
        .where(
            QuestRevision.template_id.in_(ids),
            QuestRevision.status == QuestRevisionStatus.DECLINED,
        )
        .order_by(QuestRevision.version)
    )
    return {r.template_id: r for r in rows}  # the last (highest version) wins


async def _template_out(
    session: AsyncSession,
    template: QuestTemplate,
    user_id: int,
    pending: QuestRevision | None = None,
    declined: QuestRevision | None = None,
    *,
    lookup_pending: bool = True,
) -> TemplateOut:
    current = (
        await session.get(QuestRevision, template.current_revision_id)
        if template.current_revision_id is not None
        else None
    )
    if current is not None:
        terms, version = QuestTerms.model_validate(current.terms), current.version
    else:  # pragma: no cover - rows written outside this service (fixtures, manual SQL)
        terms, version = _template_terms(get_settings(), template), 0
    if lookup_pending:
        if pending is None:
            pending = await _pending_revision(session, template)
        if declined is None:
            declined = (await _declined_by_template(session, [template.id])).get(template.id)
    # A declined proposal stays visible until a newer revision is accepted; a declined offer is
    # the current revision itself.
    if declined is not None and declined.version < version:
        declined = None
    streak: StreakOut | None = None
    if template.recurrence == Recurrence.DAILY:
        row = await session.get(QuestStreak, template.id)
        streak = (
            StreakOut(
                current=row.current, best=row.best, last_completed_date=row.last_completed_date
            )
            if row is not None
            else StreakOut(current=0, best=0, last_completed_date=None)
        )
    return TemplateOut(
        id=template.id,
        partnership_id=template.partnership_id,
        creator_id=template.creator_id,
        assignee_id=template.assignee_id,
        role=_role(template, user_id),
        status=template.status,
        recurrence=template.recurrence,
        terms=terms,
        version=version,
        pending_revision=RevisionOut.model_validate(pending) if pending is not None else None,
        last_declined_revision=RevisionOut.model_validate(declined)
        if declined is not None
        else None,
        streak=streak,
        created_at=template.created_at,
    )


def _occurrence_fields(
    occurrence: QuestOccurrence, template: QuestTemplate, user_id: int, has_pending: bool
) -> dict[str, Any]:
    return {
        "id": occurrence.id,
        "template_id": template.id,
        "creator_id": template.creator_id,
        "assignee_id": occurrence.assignee_id,
        "role": _role(template, user_id),
        "status": occurrence.status,
        "template_status": template.status,
        "recurrence": template.recurrence,
        "scheduled_date": occurrence.scheduled_date,
        "due_at": occurrence.due_at,
        "terms": QuestTerms.model_validate(occurrence.terms_snapshot),
        "accepted_at": occurrence.accepted_at,
        "submitted_at": occurrence.submitted_at,
        "completed_at": occurrence.completed_at,
        "cancelled_by": occurrence.cancelled_by,
        "decline_reason": occurrence.decline_reason,
        "has_pending_revision": has_pending,
    }


async def _occurrence_out(
    session: AsyncSession, occurrence: QuestOccurrence, template: QuestTemplate, user_id: int
) -> OccurrenceOut:
    pending = await _pending_revision(session, template)
    return OccurrenceOut(**_occurrence_fields(occurrence, template, user_id, pending is not None))


async def _visible_template(session: AsyncSession, user: User, template_id: int) -> QuestTemplate:
    template = await session.scalar(
        select(QuestTemplate)
        .where(
            QuestTemplate.id == template_id,
            or_(QuestTemplate.creator_id == user.id, QuestTemplate.assignee_id == user.id),
        )
        .execution_options(populate_existing=True)
    )
    if template is None:
        raise QuestNotFoundError
    return template


async def get_occurrence(session: AsyncSession, user: User, occurrence_id: int) -> OccurrenceDetail:
    """A member's view of one occurrence (also after the partnership ended: it is history)."""
    row = (
        await session.execute(
            select(QuestOccurrence, QuestTemplate)
            .join(QuestTemplate, QuestTemplate.id == QuestOccurrence.template_id)
            .where(
                QuestOccurrence.id == occurrence_id,
                or_(QuestTemplate.creator_id == user.id, QuestTemplate.assignee_id == user.id),
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise QuestNotFoundError
    occurrence, template = row
    template_out = await _template_out(session, template, user.id)
    submissions = await session.scalars(
        select(QuestSubmission)
        .where(QuestSubmission.occurrence_id == occurrence.id)
        .order_by(QuestSubmission.id)
    )
    return OccurrenceDetail(
        **_occurrence_fields(
            occurrence, template, user.id, template_out.pending_revision is not None
        ),
        template=template_out,
        submissions=[SubmissionOut.model_validate(s) for s in submissions],
    )


async def get_template(session: AsyncSession, user: User, template_id: int) -> TemplateDetail:
    template = await _visible_template(session, user, template_id)
    out = await _template_out(session, template, user.id)
    latest = await session.scalar(
        select(QuestOccurrence)
        .where(QuestOccurrence.template_id == template.id)
        .order_by(QuestOccurrence.scheduled_date.desc(), QuestOccurrence.id.desc())
        .limit(1)
    )
    return TemplateDetail(
        **out.model_dump(),
        latest_occurrence=OccurrenceOut(
            **_occurrence_fields(latest, template, user.id, out.pending_revision is not None)
        )
        if latest is not None
        else None,
    )


def _role_filter(user: User, role: Role | None) -> Any:
    if role == "player":
        return QuestTemplate.assignee_id == user.id
    if role == "gm":
        return QuestTemplate.creator_id == user.id
    return or_(QuestTemplate.creator_id == user.id, QuestTemplate.assignee_id == user.id)


async def list_occurrences(
    session: AsyncSession,
    user: User,
    *,
    role: Role | None,
    statuses: Sequence[QuestOccurrenceStatus],
    limit: int,
) -> list[OccurrenceOut]:
    """Occurrences in my active partnership (none without one), newest first."""
    partnership = await find_active(session, user.id)
    if partnership is None:
        return []
    query = (
        select(QuestOccurrence, QuestTemplate)
        .join(QuestTemplate, QuestTemplate.id == QuestOccurrence.template_id)
        .where(QuestTemplate.partnership_id == partnership.id, _role_filter(user, role))
        .order_by(QuestOccurrence.id.desc())
        .limit(limit)
    )
    if statuses:
        query = query.where(QuestOccurrence.status.in_(statuses))
    rows = (await session.execute(query)).all()
    pending = await _pending_by_template(session, {t.id: t for _, t in rows}.values())
    return [OccurrenceOut(**_occurrence_fields(o, t, user.id, t.id in pending)) for o, t in rows]


async def list_templates(
    session: AsyncSession,
    user: User,
    *,
    role: Role | None,
    statuses: Sequence[QuestTemplateStatus],
    recurrence: Recurrence | None,
    limit: int,
) -> list[TemplateOut]:
    """Templates in my active partnership (recurring offers and the Recurring tab)."""
    partnership = await find_active(session, user.id)
    if partnership is None:
        return []
    query = (
        select(QuestTemplate)
        .where(QuestTemplate.partnership_id == partnership.id, _role_filter(user, role))
        .order_by(QuestTemplate.id.desc())
        .limit(limit)
    )
    if statuses:
        query = query.where(QuestTemplate.status.in_(statuses))
    if recurrence is not None:
        query = query.where(QuestTemplate.recurrence == recurrence)
    templates = list(await session.scalars(query))
    pending = await _pending_by_template(session, templates)
    declined = await _declined_by_template(session, [t.id for t in templates])
    return [
        await _template_out(
            session, t, user.id, pending.get(t.id), declined.get(t.id), lookup_pending=False
        )
        for t in templates
    ]
