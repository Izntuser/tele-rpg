"""Voucher state machine: one test per allowed and per forbidden (status, action, actor), plus
the 48h dispute window."""

from datetime import UTC, datetime, timedelta
from itertools import product

import pytest

from app.modules.common.enums import RewardPurchaseStatus as S
from app.modules.rewards import state

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
FULFILLED_AT = NOW - timedelta(hours=1)

ALLOWED = {
    (S.PURCHASED, "request", "buyer"): S.REQUESTED,
    (S.REQUESTED, "schedule", "provider"): S.SCHEDULED,
    (S.SCHEDULED, "schedule", "provider"): S.SCHEDULED,
    (S.SCHEDULED, "fulfill", "provider"): S.FULFILLED,
    (S.FULFILLED, "dispute", "buyer"): S.REQUESTED,
    (S.PURCHASED, "refund", "buyer"): S.REFUNDED,
    (S.PURCHASED, "refund", "provider"): S.REFUNDED,
    (S.REQUESTED, "refund", "provider"): S.REFUNDED,
    (S.SCHEDULED, "refund", "provider"): S.REFUNDED,
}

ALL = list(product(list(S), state.ACTIONS, state.ACTORS))
FORBIDDEN = [k for k in ALL if k not in ALLOWED]


def test_table_is_exactly_the_documented_flow() -> None:
    assert state.TRANSITIONS == ALLOWED


@pytest.mark.parametrize(("status", "action", "actor"), list(ALLOWED), ids=str)
def test_allowed_transition(status: S, action: state.Action, actor: state.Actor) -> None:
    got = state.next_status(status, action, actor, fulfilled_at=FULFILLED_AT, now=NOW)
    assert got == ALLOWED[(status, action, actor)]


@pytest.mark.parametrize(("status", "action", "actor"), FORBIDDEN, ids=str)
def test_forbidden_transition(status: S, action: state.Action, actor: state.Actor) -> None:
    expected: type[Exception] = (
        state.WrongActorError
        if actor not in state.ACTION_ACTORS[action]
        else state.InvalidTransitionError
    )
    with pytest.raises(expected):
        state.next_status(status, action, actor, fulfilled_at=FULFILLED_AT, now=NOW)


def test_actors_per_action() -> None:
    assert state.ACTION_ACTORS == {
        "request": {"buyer"},
        "schedule": {"provider"},
        "fulfill": {"provider"},
        "dispute": {"buyer"},
        "refund": {"buyer", "provider"},
    }


def test_buyer_refunds_only_while_purchased() -> None:
    for status in (S.REQUESTED, S.SCHEDULED, S.FULFILLED):
        with pytest.raises(state.InvalidTransitionError):
            state.next_status(status, "refund", "buyer")


def test_nobody_refunds_after_fulfilment() -> None:
    for actor in state.ACTORS:
        with pytest.raises(state.InvalidTransitionError):
            state.next_status(S.FULFILLED, "refund", actor)


def test_terminal_statuses() -> None:
    assert state.TERMINAL == {S.REFUNDED, S.CANCELLED}


@pytest.mark.parametrize(
    ("age", "ok"),
    [
        (timedelta(0), True),
        (timedelta(hours=47, minutes=59), True),
        (timedelta(hours=48), True),
        (timedelta(hours=48, seconds=1), False),
        (timedelta(days=5), False),
    ],
)
def test_dispute_window(age: timedelta, ok: bool) -> None:
    fulfilled_at = NOW - age
    assert state.can_dispute(fulfilled_at, NOW) is ok
    if ok:
        assert state.next_status(
            S.FULFILLED, "dispute", "buyer", fulfilled_at=fulfilled_at, now=NOW
        )
    else:
        with pytest.raises(state.DisputeWindowClosedError):
            state.next_status(S.FULFILLED, "dispute", "buyer", fulfilled_at=fulfilled_at, now=NOW)


def test_dispute_needs_a_fulfilment_time() -> None:
    assert state.can_dispute(None, NOW) is False
    with pytest.raises(state.DisputeWindowClosedError):
        state.next_status(S.FULFILLED, "dispute", "buyer", fulfilled_at=None, now=NOW)
    with pytest.raises(state.DisputeWindowClosedError):
        state.next_status(S.FULFILLED, "dispute", "buyer", fulfilled_at=FULFILLED_AT)
