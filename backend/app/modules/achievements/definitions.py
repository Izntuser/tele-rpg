"""Code-defined achievements (ARCHITECTURE §4: only unlocks are rows).

Each definition measures one number for a user (``metric``) and unlocks once it reaches
``target``. Metrics are synchronous queries on a ``Session`` because they run inside the
commit (``achievements.service``); async callers go through ``AsyncSession.run_sync``.
``triggers`` are the journal event types that can move the metric: a commit is evaluated only
for definitions whose triggers it recorded. Titles and descriptions live in the frontend
catalogs (``stats.json`` -> ``achievements.<code>``); codes are stable, never rename one.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.common.enums import GoldTransactionType, QuestOccurrenceStatus
from app.modules.economy.models import GoldTransaction
from app.modules.journal.models import JournalEvent
from app.modules.progression.levels import level_for_xp
from app.modules.progression.models import XpTransaction
from app.modules.quests.models import QuestOccurrence, QuestStreak, QuestTemplate
from app.modules.users.models import Character, CharacterAttribute

Metric = Callable[[Session, int], int]


@dataclass(frozen=True, slots=True)
class Achievement:
    code: str
    icon: str
    target: int
    triggers: frozenset[str]
    metric: Metric


def _events(type_: str) -> Metric:
    def metric(session: Session, user_id: int) -> int:
        count = session.scalar(
            select(func.count())
            .select_from(JournalEvent)
            .where(JournalEvent.user_id == user_id, JournalEvent.type == type_)
        )
        return int(count or 0)

    return metric


def _completed(session: Session, user_id: int) -> int:
    count = session.scalar(
        select(func.count()).select_from(XpTransaction).where(XpTransaction.user_id == user_id)
    )
    return int(count or 0)


def _level(session: Session, user_id: int) -> int:
    xp = session.scalar(select(Character.total_xp).where(Character.user_id == user_id))
    return level_for_xp(int(xp or 0))


def _best_attribute_level(session: Session, user_id: int) -> int:
    xp = session.scalar(
        select(func.max(CharacterAttribute.xp))
        .join(Character, Character.id == CharacterAttribute.character_id)
        .where(Character.user_id == user_id)
    )
    return level_for_xp(int(xp or 0))


def _attributes_played(session: Session, user_id: int) -> int:
    count = session.scalar(
        select(func.count(func.distinct(XpTransaction.attribute))).where(
            XpTransaction.user_id == user_id
        )
    )
    return int(count or 0)


def _best_streak(session: Session, user_id: int) -> int:
    best = session.scalar(
        select(func.max(QuestStreak.best))
        .join(QuestTemplate, QuestTemplate.id == QuestStreak.template_id)
        .where(QuestTemplate.assignee_id == user_id)
    )
    return int(best or 0)


def _gold_earned(session: Session, user_id: int) -> int:
    total = session.scalar(
        select(func.coalesce(func.sum(GoldTransaction.amount), 0)).where(
            GoldTransaction.user_id == user_id,
            GoldTransaction.type == GoldTransactionType.QUEST_REWARD,
        )
    )
    return int(total or 0)


def _confirmed_as_gm(session: Session, user_id: int) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(QuestOccurrence)
        .join(QuestTemplate, QuestTemplate.id == QuestOccurrence.template_id)
        .where(
            QuestTemplate.creator_id == user_id,
            QuestOccurrence.status == QuestOccurrenceStatus.COMPLETED,
        )
    )
    return int(count or 0)


_COMPLETED = frozenset({"quest_completed"})
_LEVELS = frozenset({"quest_completed", "level_up", "attribute_level_up"})

ACHIEVEMENTS: tuple[Achievement, ...] = (
    Achievement("first_quest", "sword", 1, _COMPLETED, _completed),
    Achievement("quests_10", "swords", 10, _COMPLETED, _completed),
    Achievement("quests_50", "crown", 50, _COMPLETED, _completed),
    Achievement("level_5", "star", 5, _LEVELS, _level),
    Achievement("level_10", "sparkles", 10, _LEVELS, _level),
    Achievement("attribute_5", "dumbbell", 5, _LEVELS, _best_attribute_level),
    Achievement("all_attributes", "compass", 6, _COMPLETED, _attributes_played),
    Achievement("streak_7", "flame", 7, _COMPLETED, _best_streak),
    Achievement("gold_100", "coins", 100, _COMPLETED, _gold_earned),
    Achievement(
        "first_purchase",
        "shopping-bag",
        1,
        frozenset({"reward_purchased"}),
        _events("reward_purchased"),
    ),
    Achievement("quest_giver", "scroll", 1, frozenset({"quest_offered"}), _events("quest_offered")),
    Achievement("mentor", "shield", 10, _COMPLETED, _confirmed_as_gm),
    Achievement("shopkeeper", "store", 1, frozenset({"reward_created"}), _events("reward_created")),
    Achievement(
        "generous", "gift", 1, frozenset({"reward_fulfilled"}), _events("reward_fulfilled")
    ),
)

BY_CODE: dict[str, Achievement] = {a.code: a for a in ACHIEVEMENTS}

#: Every event type that can unlock something; other types are never evaluated.
TRIGGER_TYPES: frozenset[str] = frozenset().union(*(a.triggers for a in ACHIEVEMENTS))
