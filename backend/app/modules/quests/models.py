from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import (
    Attribute,
    ConfirmationMode,
    Difficulty,
    QuestOccurrenceStatus,
    QuestRevisionStatus,
    QuestTemplateStatus,
    Recurrence,
    SubmissionReviewStatus,
)

GOLD_RANGE_SQL = "gold >= 0 AND gold <= 1000"


class QuestTemplate(Base):
    __tablename__ = "quest_template"
    __table_args__ = (
        Index(None, "partnership_id"),
        CheckConstraint("assignee_id <> creator_id", name="assignee_not_creator"),
        CheckConstraint(GOLD_RANGE_SQL, name="gold_range"),
        CheckConstraint(
            "deadline_at IS NULL OR recurrence = 'once'", name="deadline_only_for_once"
        ),
    )

    id: Mapped[int] = id_pk()
    partnership_id: Mapped[int] = mapped_column(ForeignKey("partnership.id"))
    creator_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    assignee_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    attribute: Mapped[Attribute] = mapped_column(pg_enum(Attribute))
    difficulty: Mapped[Difficulty] = mapped_column(pg_enum(Difficulty))
    gold: Mapped[int] = mapped_column(Integer)
    recurrence: Mapped[Recurrence] = mapped_column(pg_enum(Recurrence))
    deadline_at: Mapped[datetime | None]
    confirmation: Mapped[ConfirmationMode] = mapped_column(
        pg_enum(ConfirmationMode), server_default=ConfirmationMode.MANUAL.value
    )
    photo_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[QuestTemplateStatus] = mapped_column(
        pg_enum(QuestTemplateStatus), server_default=QuestTemplateStatus.OFFERED.value
    )
    # Circular with quest_revision.template_id, hence created by ALTER after both tables.
    current_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "quest_revision.id",
            use_alter=True,
            name="fk_quest_template_current_revision_id_quest_revision",
        )
    )
    created_at: Mapped[datetime] = created_at()


class QuestRevision(Base):
    __tablename__ = "quest_revision"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint("template_id", "version"),
        # At most one revision awaiting the assignee per template (0003).
        Index(
            "ux_quest_revision_one_pending",
            "template_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = id_pk()
    template_id: Mapped[int] = mapped_column(ForeignKey("quest_template.id"))
    version: Mapped[int] = mapped_column(Integer)
    # title, description, attribute, difficulty, gold, xp, deadline, confirmation, photo_required
    terms: Mapped[dict[str, Any]]
    status: Mapped[QuestRevisionStatus] = mapped_column(
        pg_enum(QuestRevisionStatus), server_default=QuestRevisionStatus.PENDING.value
    )
    proposed_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = created_at()
    decided_at: Mapped[datetime | None]
    # Why the assignee declined this revision (or the recurring offer it carried); scrubbed on
    # the assignee's account deletion.
    decline_reason: Mapped[str | None] = mapped_column(Text)


class QuestOccurrence(Base):
    __tablename__ = "quest_occurrence"
    __table_args__ = (
        UniqueConstraint("template_id", "scheduled_date"),
        Index(None, "assignee_id", "status"),
    )

    id: Mapped[int] = id_pk()
    template_id: Mapped[int] = mapped_column(ForeignKey("quest_template.id"))
    assignee_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    status: Mapped[QuestOccurrenceStatus] = mapped_column(pg_enum(QuestOccurrenceStatus))
    # Local date in the assignee's timezone; the Monday of the ISO week for weekly quests.
    scheduled_date: Mapped[date] = mapped_column(Date)
    due_at: Mapped[datetime | None]
    # Accepted terms incl. xp and gold; completion reads these, never the live template.
    terms_snapshot: Mapped[dict[str, Any]]
    accepted_at: Mapped[datetime | None]
    submitted_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    decline_reason: Mapped[str | None] = mapped_column(Text)


class QuestSubmission(Base):
    __tablename__ = "quest_submission"
    __table_args__ = (
        CheckConstraint(
            "review_status <> 'redo'"
            " OR (review_comment IS NOT NULL AND btrim(review_comment) <> '')",
            name="redo_requires_comment",
        ),
    )

    id: Mapped[int] = id_pk()
    occurrence_id: Mapped[int] = mapped_column(ForeignKey("quest_occurrence.id"))
    submitted_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    attachment_id: Mapped[int | None] = mapped_column(ForeignKey("file.id"))
    created_at: Mapped[datetime] = created_at()
    review_status: Mapped[SubmissionReviewStatus] = mapped_column(
        pg_enum(SubmissionReviewStatus), server_default=SubmissionReviewStatus.PENDING.value
    )
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None]


class QuestStreak(Base):
    """Display-only streak for daily templates."""

    __tablename__ = "quest_streak"
    __table_args__ = (
        CheckConstraint("current >= 0", name="current_non_negative"),
        CheckConstraint("best >= current", name="best_at_least_current"),
    )

    template_id: Mapped[int] = mapped_column(ForeignKey("quest_template.id"), primary_key=True)
    current: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    best: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_completed_date: Mapped[date | None] = mapped_column(Date)


class SavedQuestTemplate(Base):
    """User-saved preset. Built-in presets are static data in ``app.modules.quests.presets``."""

    __tablename__ = "saved_quest_template"
    __table_args__ = (CheckConstraint(GOLD_RANGE_SQL, name="gold_range"),)

    id: Mapped[int] = id_pk()
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    attribute: Mapped[Attribute] = mapped_column(pg_enum(Attribute))
    difficulty: Mapped[Difficulty] = mapped_column(pg_enum(Difficulty))
    gold: Mapped[int] = mapped_column(Integer)
    recurrence: Mapped[Recurrence] = mapped_column(pg_enum(Recurrence))
    confirmation: Mapped[ConfirmationMode] = mapped_column(
        pg_enum(ConfirmationMode), server_default=ConfirmationMode.MANUAL.value
    )
    photo_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
