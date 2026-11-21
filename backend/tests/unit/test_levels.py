import pytest

from app.modules.progression.levels import (
    level_for_xp,
    progress_for_xp,
    xp_for_level,
    xp_for_next_level,
)


def test_thresholds_match_the_brief() -> None:
    assert xp_for_level(1) == 0
    assert xp_for_level(2) == 100
    assert xp_for_level(3) == 250


# project.md §9: "XP required for the next level" by current level.
@pytest.mark.parametrize(
    ("level", "needed"),
    [(1, 100), (2, 150), (3, 200), (5, 300), (10, 550), (20, 1050), (50, 2550)],
)
def test_step_table_from_project_md(level: int, needed: int) -> None:
    assert xp_for_next_level(level) == needed


@pytest.mark.parametrize(
    ("xp", "level"),
    [(0, 1), (1, 1), (99, 1), (100, 2), (249, 2), (250, 3), (449, 3), (450, 4), (700, 5)],
)
def test_level_for_xp_boundaries(xp: int, level: int) -> None:
    assert level_for_xp(xp) == level


def test_level_for_xp_is_exact_on_every_threshold() -> None:
    for level in range(1, 500):
        threshold = xp_for_level(level)
        assert level_for_xp(threshold) == level
        if threshold:
            assert level_for_xp(threshold - 1) == level - 1


def test_level_for_xp_huge_values() -> None:
    level = 100_000
    assert level_for_xp(xp_for_level(level)) == level
    assert level_for_xp(xp_for_level(level) - 1) == level - 1
    assert level_for_xp(2**31 - 1) >= 1


def test_progress_carries_over() -> None:
    p = progress_for_xp(260)
    assert (p.level, p.total_xp, p.xp_into_level, p.xp_for_next_level, p.xp_to_next_level) == (
        3,
        260,
        10,
        200,
        190,
    )
    start = progress_for_xp(0)
    assert (start.level, start.xp_into_level, start.xp_to_next_level) == (1, 0, 100)


def test_invalid_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        level_for_xp(-1)
    with pytest.raises(ValueError):
        xp_for_level(0)
