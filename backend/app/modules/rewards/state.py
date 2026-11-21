"""Voucher (reward purchase) state machine: one explicit transition table (ARCHITECTURE §4
"Purchase", "Refund", "Dispute", §7 "State machine validity").

Every status change of a ``reward_purchase`` goes through ``next_status``, which looks the
``(status, action, actor)`` triple up in ``TRANSITIONS`` and raises for anything not listed:

- ``WrongActorError`` (403) when the actor may never perform the action (a provider requesting,
  a buyer scheduling, ...);
- ``InvalidTransitionError`` (409) when the actor may perform it, but not from this status
  (e.g. a buyer refunding a requested voucher);
- ``DisputeWindowClosedError`` (409) for a dispute later than ``DISPUTE_WINDOW`` after
  ``fulfilled_at``.

Flow: purchased -> requested (buyer) -> scheduled (provider; re-scheduling allowed) ->
fulfilled (provider). A dispute (buyer, within 48h of fulfilment) returns the voucher to
requested. Refunds: the provider from any status before fulfilled, the buyer only while
purchased. ``cancelled`` is reserved: nothing transitions into it.
"""

from datetime import datetime, timedelta
from typing import Literal, get_args

from app.modules.common.enums import RewardPurchaseStatus

# Literals, not enums: StrEnums live only in common/enums.py and are all Postgres types.
Action = Literal["request", "schedule", "fulfill", "dispute", "refund"]
Actor = Literal["buyer", "provider"]
ACTIONS: tuple[Action, ...] = get_args(Action)
ACTORS: tuple[Actor, ...] = get_args(Actor)

DISPUTE_WINDOW = timedelta(hours=48)

_P = RewardPurchaseStatus

TRANSITIONS: dict[tuple[RewardPurchaseStatus, Action, Actor], RewardPurchaseStatus] = {
    (_P.PURCHASED, "request", "buyer"): _P.REQUESTED,
    (_P.REQUESTED, "schedule", "provider"): _P.SCHEDULED,
    (_P.SCHEDULED, "schedule", "provider"): _P.SCHEDULED,
    (_P.SCHEDULED, "fulfill", "provider"): _P.FULFILLED,
    (_P.FULFILLED, "dispute", "buyer"): _P.REQUESTED,
    (_P.PURCHASED, "refund", "buyer"): _P.REFUNDED,
    (_P.PURCHASED, "refund", "provider"): _P.REFUNDED,
    (_P.REQUESTED, "refund", "provider"): _P.REFUNDED,
    (_P.SCHEDULED, "refund", "provider"): _P.REFUNDED,
}

#: Who may ever perform each action (derived from the table).
ACTION_ACTORS: dict[Action, frozenset[Actor]] = {
    action: frozenset(k[2] for k in TRANSITIONS if k[1] == action) for action in ACTIONS
}

#: Statuses that nothing can leave.
TERMINAL = frozenset(s for s in RewardPurchaseStatus if not any(k[0] == s for k in TRANSITIONS))


class VoucherTransitionError(Exception):
    pass


class WrongActorError(VoucherTransitionError):
    def __init__(self, action: Action, actor: Actor) -> None:
        super().__init__(f"the {actor} cannot {action} a voucher")
        self.action = action
        self.actor = actor


class InvalidTransitionError(VoucherTransitionError):
    def __init__(self, status: RewardPurchaseStatus, action: Action, actor: Actor) -> None:
        super().__init__(f"the {actor} cannot {action} a voucher that is {status.value}")
        self.status = status
        self.action = action
        self.actor = actor


class DisputeWindowClosedError(VoucherTransitionError):
    def __init__(self) -> None:
        super().__init__("a voucher can be disputed only within 48 hours of fulfilment")


def can_dispute(fulfilled_at: datetime | None, now: datetime) -> bool:
    return fulfilled_at is not None and now - fulfilled_at <= DISPUTE_WINDOW


def next_status(
    status: RewardPurchaseStatus,
    action: Action,
    actor: Actor,
    *,
    fulfilled_at: datetime | None = None,
    now: datetime | None = None,
) -> RewardPurchaseStatus:
    """The status after ``actor`` performs ``action`` on a voucher in ``status``.

    A dispute also needs ``fulfilled_at`` and ``now``.
    """
    if actor not in ACTION_ACTORS[action]:
        raise WrongActorError(action, actor)
    try:
        target = TRANSITIONS[(status, action, actor)]
    except KeyError:
        raise InvalidTransitionError(status, action, actor) from None
    if action == "dispute":
        if now is None or not can_dispute(fulfilled_at, now):
            raise DisputeWindowClosedError
    return target
