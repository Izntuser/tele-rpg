"""Level maths (project.md §9, ARCHITECTURE §4).

Total XP needed to reach level ``L`` is ``100(L-1) + 25(L-1)(L-2)``, so the step from ``L`` to
``L+1`` costs ``100 + 50(L-1)``. Levels start at 1, are unbounded and never decrease. The same
curve is used for the character level and for every attribute level.
"""

from dataclasses import dataclass
from math import isqrt

MIN_LEVEL = 1


def xp_for_level(level: int) -> int:
    """Total accumulated XP required to reach ``level`` (level 1 needs 0)."""
    if level < MIN_LEVEL:
        raise ValueError("level must be >= 1")
    n = level - 1
    return 100 * n + 25 * n * (n - 1)


def xp_for_next_level(level: int) -> int:
    """XP needed to go from ``level`` to ``level + 1`` (100, 150, 200, ...)."""
    return xp_for_level(level + 1) - xp_for_level(level)


def level_for_xp(xp: int) -> int:
    """The highest level whose threshold is <= ``xp``.

    With ``n = L - 1`` the threshold is ``25n^2 + 75n``; solving ``25n^2 + 75n <= xp`` gives
    ``n = floor((-3 + sqrt(9 + 4xp/25)) / 2)``. The integer square root can be off by one at
    the boundaries, so the result is nudged until it is exact.
    """
    if xp < 0:
        raise ValueError("xp must be >= 0")
    n = max(0, (isqrt(9 * 25 * 25 + 4 * 25 * xp) // 25 - 3) // 2)
    while xp_for_level(n + 2) <= xp:
        n += 1
    while n > 0 and xp_for_level(n + 1) > xp:
        n -= 1
    return n + 1


@dataclass(frozen=True, slots=True)
class LevelProgress:
    level: int
    total_xp: int
    #: XP earned since the current level's threshold.
    xp_into_level: int
    #: Size of the current level (threshold of next level minus threshold of this one).
    xp_for_next_level: int
    #: XP still missing to reach the next level.
    xp_to_next_level: int


def progress_for_xp(xp: int) -> LevelProgress:
    level = level_for_xp(xp)
    into = xp - xp_for_level(level)
    span = xp_for_next_level(level)
    return LevelProgress(
        level=level,
        total_xp=xp,
        xp_into_level=into,
        xp_for_next_level=span,
        xp_to_next_level=span - into,
    )
