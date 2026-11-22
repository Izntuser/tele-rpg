"""Life Balance maths (project.md §11): pure functions, no database.

Each attribute has a weekly XP target owned by the user (``life_balance_target``, default 100).
For a period of ``days`` the target is scaled to ``weekly * days / 7`` and

    score = min(100, earned attribute XP / target attribute XP * 100)

rounded down to an integer. A target of 0 means "no goal for this attribute": its score is 100
and it never produces a suggestion. The score measures progress toward an agreed activity
target, not the person's quality of life, so suggestions are encouraging and optional.

Suggestion rules: every attribute scoring below ``SUGGEST_BELOW`` is a candidate, lowest score
first (ties in the fixed attribute order), at most ``MAX_SUGGESTIONS``. ``no_activity`` when
nothing was earned, ``below_target`` otherwise. ``balanced`` is true when no attribute is a
candidate.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.modules.common.enums import Attribute

DEFAULT_WEEKLY_TARGET = 100
MAX_WEEKLY_TARGET = 10_000
SUGGEST_BELOW = 50
MAX_SUGGESTIONS = 3
PERIOD_DAYS: dict[str, int] = {"7d": 7, "30d": 30}

ATTRIBUTE_ORDER: tuple[Attribute, ...] = tuple(Attribute)


#: ``no_activity``: nothing earned in the period; ``below_target``: some, but under the bar.
SuggestionReason = Literal["no_activity", "below_target"]


@dataclass(frozen=True, slots=True)
class AttributeScore:
    attribute: Attribute
    earned_xp: int
    weekly_target: int
    period_target: int
    score: int


@dataclass(frozen=True, slots=True)
class Suggestion:
    attribute: Attribute
    reason: SuggestionReason
    score: int


def period_target(weekly_target: int, days: int) -> int:
    """The weekly target scaled to ``days`` (rounded half up, never below 0)."""
    if weekly_target < 0 or days <= 0:
        raise ValueError("weekly_target must be >= 0 and days > 0")
    return (weekly_target * days * 2 + 7) // 14


def activity_score(earned_xp: int, target_xp: int) -> int:
    """``min(100, earned / target * 100)``, floored; a zero target scores 100."""
    if earned_xp < 0 or target_xp < 0:
        raise ValueError("earned_xp and target_xp must be >= 0")
    if target_xp == 0:
        return 100
    return min(100, earned_xp * 100 // target_xp)


def scores(
    earned: Mapping[Attribute, int], weekly_targets: Mapping[Attribute, int], days: int
) -> list[AttributeScore]:
    """One score per attribute in the fixed order; missing entries mean 0 XP / default target."""
    out: list[AttributeScore] = []
    for attribute in ATTRIBUTE_ORDER:
        weekly = weekly_targets.get(attribute, DEFAULT_WEEKLY_TARGET)
        target = period_target(weekly, days)
        xp = earned.get(attribute, 0)
        out.append(
            AttributeScore(
                attribute=attribute,
                earned_xp=xp,
                weekly_target=weekly,
                period_target=target,
                score=activity_score(xp, target),
            )
        )
    return out


def suggestions(items: list[AttributeScore]) -> list[Suggestion]:
    """Rule-based suggestions for the weakest attributes (see the module docstring)."""
    order = {a: i for i, a in enumerate(ATTRIBUTE_ORDER)}
    candidates = sorted(
        (s for s in items if s.period_target > 0 and s.score < SUGGEST_BELOW),
        key=lambda s: (s.score, order[s.attribute]),
    )
    return [
        Suggestion(
            attribute=s.attribute,
            reason="no_activity" if s.earned_xp == 0 else "below_target",
            score=s.score,
        )
        for s in candidates[:MAX_SUGGESTIONS]
    ]
