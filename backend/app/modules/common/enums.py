"""Every shared enum, defined once (ARCHITECTURE §4).

Models map these to Postgres enum types via ``app.db.base.pg_enum`` and Pydantic schemas import
them from here, so a value is spelled in exactly one place. The Postgres type name is the
snake_case form of the class name (``QuestOccurrenceStatus`` -> ``quest_occurrence_status``).
"""

from enum import StrEnum


class Locale(StrEnum):
    EN = "en"
    UK = "uk"


class Attribute(StrEnum):
    PHYSICAL = "physical"
    INTELLECTUAL = "intellectual"
    DISCIPLINE = "discipline"
    SOCIAL = "social"
    CREATIVITY = "creativity"
    WELLBEING = "wellbeing"


class Difficulty(StrEnum):
    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"
    EPIC = "epic"


class Recurrence(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


class ConfirmationMode(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


class PartnershipStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class GoldTransactionType(StrEnum):
    QUEST_REWARD = "quest_reward"
    REWARD_PURCHASE = "reward_purchase"
    REWARD_REFUND = "reward_refund"
    ADJUSTMENT = "adjustment"


class QuestTemplateStatus(StrEnum):
    OFFERED = "offered"
    ACTIVE = "active"
    PAUSED = "paused"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class QuestRevisionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    SUPERSEDED = "superseded"


class QuestOccurrenceStatus(StrEnum):
    OFFERED = "offered"
    ACTIVE = "active"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SubmissionReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REDO = "redo"


class RewardStatus(StrEnum):
    ACTIVE = "active"
    HIDDEN = "hidden"
    SOLD_OUT = "sold_out"


class RewardPurchaseStatus(StrEnum):
    PURCHASED = "purchased"
    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class JournalVisibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class WishlistStatus(StrEnum):
    OPEN = "open"
    OFFERED = "offered"
    ARCHIVED = "archived"


class NotificationCategory(StrEnum):
    QUESTS = "quests"
    REVIEWS = "reviews"
    REWARDS = "rewards"
    REMINDERS = "reminders"
    SUMMARY = "summary"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    SKIPPED = "skipped"
    FAILED = "failed"


class FileKind(StrEnum):
    AVATAR = "avatar"
    QUEST_PHOTO = "quest_photo"
    REWARD_IMAGE = "reward_image"


ALL_ENUMS: tuple[type[StrEnum], ...] = (
    Locale,
    Attribute,
    Difficulty,
    Recurrence,
    ConfirmationMode,
    PartnershipStatus,
    InvitationStatus,
    GoldTransactionType,
    QuestTemplateStatus,
    QuestRevisionStatus,
    QuestOccurrenceStatus,
    SubmissionReviewStatus,
    RewardStatus,
    RewardPurchaseStatus,
    JournalVisibility,
    GoalStatus,
    WishlistStatus,
    NotificationCategory,
    NotificationStatus,
    FileKind,
)
