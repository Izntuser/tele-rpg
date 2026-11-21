"""Every (status, action) pair of the three quest state machines: the allowed ones go where the
table says, every other pair raises InvalidTransitionError."""

import itertools
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import pytest

from app.modules.common.enums import (
    QuestOccurrenceStatus as O,
)
from app.modules.common.enums import (
    QuestRevisionStatus as R,
)
from app.modules.common.enums import (
    QuestTemplateStatus as T,
)
from app.modules.quests import state
from app.modules.quests.state import ACTIONS, Action

EXPECTED_OCCURRENCE = {
    (O.OFFERED, "accept"): O.ACTIVE,
    (O.OFFERED, "decline"): O.DECLINED,
    (O.OFFERED, "cancel"): O.CANCELLED,
    (O.ACTIVE, "submit"): O.IN_REVIEW,
    (O.ACTIVE, "cancel"): O.CANCELLED,
    (O.ACTIVE, "expire"): O.EXPIRED,
    (O.IN_REVIEW, "confirm"): O.COMPLETED,
    (O.IN_REVIEW, "request_redo"): O.ACTIVE,
}
EXPECTED_TEMPLATE = {
    (T.OFFERED, "accept"): T.ACTIVE,
    (T.OFFERED, "decline"): T.DECLINED,
    (T.OFFERED, "cancel"): T.CANCELLED,
    (T.ACTIVE, "pause"): T.PAUSED,
    (T.ACTIVE, "cancel"): T.CANCELLED,
    (T.ACTIVE, "complete"): T.COMPLETED,
    (T.PAUSED, "resume"): T.ACTIVE,
    (T.PAUSED, "cancel"): T.CANCELLED,
}
EXPECTED_REVISION = {
    (R.PENDING, "accept"): R.ACCEPTED,
    (R.PENDING, "decline"): R.DECLINED,
    (R.PENDING, "supersede"): R.SUPERSEDED,
}

Machine = tuple[str, type[StrEnum], dict[Any, Any], Callable[..., Any]]
MACHINES: list[Machine] = [
    ("occurrence", O, dict(EXPECTED_OCCURRENCE), state.next_occurrence_status),
    ("template", T, dict(EXPECTED_TEMPLATE), state.next_template_status),
    ("revision", R, dict(EXPECTED_REVISION), state.next_revision_status),
]


def _cases(allowed: bool) -> list[tuple[str, StrEnum, Action]]:
    cases = []
    for name, statuses, expected, _ in MACHINES:
        for status, action in itertools.product(statuses, ACTIONS):
            if ((status, action) in expected) == allowed:
                cases.append((name, status, action))
    return cases


def _machine(name: str) -> tuple[dict[Any, Any], Callable[..., Any]]:
    for n, _, expected, fn in MACHINES:
        if n == name:
            return expected, fn
    raise AssertionError(name)


def test_tables_match_the_documented_transitions() -> None:
    assert state.OCCURRENCE_TRANSITIONS == EXPECTED_OCCURRENCE
    assert state.TEMPLATE_TRANSITIONS == EXPECTED_TEMPLATE
    assert state.REVISION_TRANSITIONS == EXPECTED_REVISION


@pytest.mark.parametrize(("machine", "status", "action"), _cases(allowed=True))
def test_allowed_transition(machine: str, status: StrEnum, action: Action) -> None:
    expected, fn = _machine(machine)
    assert fn(status, action) == expected[(status, action)]


@pytest.mark.parametrize(("machine", "status", "action"), _cases(allowed=False))
def test_forbidden_transition(machine: str, status: StrEnum, action: Action) -> None:
    _, fn = _machine(machine)
    with pytest.raises(state.InvalidTransitionError) as info:
        fn(status, action)
    assert info.value.status == status
    assert info.value.action == action
    assert action in str(info.value) and status.value in str(info.value)


def test_terminal_occurrence_statuses() -> None:
    assert state.TERMINAL_OCCURRENCE == {O.COMPLETED, O.DECLINED, O.EXPIRED, O.CANCELLED}


def test_every_case_is_covered() -> None:
    """Allowed + forbidden partition the full product for each machine."""
    total = sum(len(statuses) * len(ACTIONS) for _, statuses, _, _ in MACHINES)
    assert len(_cases(True)) + len(_cases(False)) == total
    assert len(_cases(True)) == len(EXPECTED_OCCURRENCE) + len(EXPECTED_TEMPLATE) + len(
        EXPECTED_REVISION
    )
