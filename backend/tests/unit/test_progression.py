"""Progression maths used by quest completion (project.md §9-10): XP per quest, level changes
(multi-level jumps, carry-over, never down), and the difficulty XP table."""

import pytest

from app.core.config import Settings
from app.modules.common.enums import Difficulty
from app.modules.progression.levels import level_for_xp, xp_for_level
from app.modules.progression.service import LevelChange, level_change, quest_award


def test_quest_award_gives_the_same_xp_to_general_and_attribute() -> None:
    assert quest_award(50) == (50, 50)
    assert quest_award(0) == (0, 0)


def test_quest_award_rejects_negative_xp() -> None:
    with pytest.raises(ValueError):
        quest_award(-1)


def test_difficulty_xp_table_matches_the_spec() -> None:
    assert Settings().difficulty_xp == {
        Difficulty.EASY: 20,
        Difficulty.NORMAL: 50,
        Difficulty.HARD: 100,
        Difficulty.EPIC: 250,
    }


@pytest.mark.parametrize(
    ("before", "gained", "levels"),
    [
        (0, 0, (1, 1)),
        (0, 50, (1, 1)),
        (0, 99, (1, 1)),
        (0, 100, (1, 2)),  # exactly the threshold
        (50, 50, (1, 2)),
        (99, 1, (1, 2)),
        (100, 149, (2, 2)),
        (100, 150, (2, 3)),
        (0, 250, (1, 3)),  # an epic quest from scratch crosses two levels
        (0, 1000, (1, 6)),  # 1000 XP: level 6 needs 875, level 7 needs 1200
        (xp_for_level(10) - 1, 1, (9, 10)),
    ],
)
def test_level_change(before: int, gained: int, levels: tuple[int, int]) -> None:
    change = level_change(before, gained)
    assert (change.before, change.after) == levels
    assert change.gained == levels[1] - levels[0]


def test_level_change_carries_over_leftover_xp() -> None:
    # 90 + 50 = 140: level 2 with 40 XP into it, nothing lost.
    change = level_change(90, 50)
    assert change == LevelChange(1, 2)
    assert 140 - xp_for_level(change.after) == 40


def test_levels_never_go_down() -> None:
    with pytest.raises(ValueError):
        level_change(500, -1)
    for before in range(0, 3000, 37):
        for gained in (0, 20, 50, 100, 250):
            change = level_change(before, gained)
            assert change.after >= change.before
            assert change.after == level_for_xp(before + gained)
