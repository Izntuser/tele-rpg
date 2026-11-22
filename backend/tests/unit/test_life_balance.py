"""Life Balance maths (project.md §11): score = min(100, earned / target * 100), targets scaled
from weekly to the period, and the rule-based suggestions."""

import pytest

from app.modules.common.enums import Attribute
from app.modules.stats import life_balance as lb


@pytest.mark.parametrize(
    ("earned", "target", "expected"),
    [
        (0, 100, 0),
        (50, 100, 50),
        (99, 100, 99),
        (100, 100, 100),
        (250, 100, 100),
        (1, 3, 33),
        (2, 3, 66),
        (0, 0, 100),
        (40, 0, 100),
    ],
)
def test_activity_score(earned: int, target: int, expected: int) -> None:
    assert lb.activity_score(earned, target) == expected


def test_activity_score_rejects_negative() -> None:
    with pytest.raises(ValueError):
        lb.activity_score(-1, 100)
    with pytest.raises(ValueError):
        lb.activity_score(10, -1)


@pytest.mark.parametrize(
    ("weekly", "days", "expected"),
    [
        (100, 7, 100),
        (100, 30, 429),  # 428.57 rounds half up
        (70, 30, 300),
        (0, 30, 0),
        (1, 7, 1),
        (1, 3, 0),  # 0.43 rounds down
        (7, 1, 1),
        (3, 7, 3),
    ],
)
def test_period_target(weekly: int, days: int, expected: int) -> None:
    assert lb.period_target(weekly, days) == expected


def test_period_target_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        lb.period_target(-1, 7)
    with pytest.raises(ValueError):
        lb.period_target(100, 0)


def test_scores_cover_every_attribute_in_fixed_order_with_defaults() -> None:
    items = lb.scores({Attribute.PHYSICAL: 50}, {}, 7)
    assert [s.attribute for s in items] == list(Attribute)
    physical = items[0]
    assert (physical.earned_xp, physical.weekly_target, physical.period_target) == (50, 100, 100)
    assert physical.score == 50
    assert all(s.score == 0 and s.earned_xp == 0 for s in items[1:])


def test_scores_use_targets_scaled_to_period() -> None:
    items = lb.scores(
        {Attribute.SOCIAL: 150, Attribute.CREATIVITY: 600},
        {Attribute.SOCIAL: 35, Attribute.CREATIVITY: 140},
        30,
    )
    by = {s.attribute: s for s in items}
    assert by[Attribute.SOCIAL].period_target == 150
    assert by[Attribute.SOCIAL].score == 100
    assert by[Attribute.CREATIVITY].period_target == 600
    assert by[Attribute.CREATIVITY].score == 100
    assert by[Attribute.PHYSICAL].period_target == 429


def test_zero_target_scores_full_and_never_suggests() -> None:
    items = lb.scores({}, {a: 0 for a in Attribute}, 7)
    assert all(s.score == 100 for s in items)
    assert lb.suggestions(items) == []


def test_suggestions_lowest_first_capped_with_reasons() -> None:
    targets = {a: 100 for a in Attribute}
    earned = {
        Attribute.PHYSICAL: 100,
        Attribute.INTELLECTUAL: 49,
        Attribute.DISCIPLINE: 10,
        Attribute.SOCIAL: 50,
        Attribute.CREATIVITY: 0,
        Attribute.WELLBEING: 0,
    }
    tips = lb.suggestions(lb.scores(earned, targets, 7))
    assert len(tips) == lb.MAX_SUGGESTIONS
    assert [(t.attribute, t.reason, t.score) for t in tips] == [
        (Attribute.CREATIVITY, "no_activity", 0),
        (Attribute.WELLBEING, "no_activity", 0),
        (Attribute.DISCIPLINE, "below_target", 10),
    ]


def test_score_at_threshold_is_not_a_suggestion() -> None:
    earned = {a: 50 for a in Attribute}
    assert lb.suggestions(lb.scores(earned, {}, 7)) == []
    earned[Attribute.SOCIAL] = 49
    tips = lb.suggestions(lb.scores(earned, {}, 7))
    assert [(t.attribute, t.reason) for t in tips] == [(Attribute.SOCIAL, "below_target")]


def test_permanent_levels_do_not_matter_only_period_xp() -> None:
    # Nothing earned in the window: every attribute is at 0 regardless of history.
    items = lb.scores({}, {}, 30)
    assert all(s.score == 0 for s in items)
    assert [t.attribute for t in lb.suggestions(items)] == list(Attribute)[: lb.MAX_SUGGESTIONS]
