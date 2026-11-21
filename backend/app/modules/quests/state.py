"""Quest state machines: explicit transition tables (ARCHITECTURE §7 "State machine validity").

Every status change of a quest occurrence, template or revision goes through ``transition``,
which looks the ``(status, action)`` pair up in the table and raises ``InvalidTransitionError``
for anything not listed. Bulk side effects of ending a partnership (``partnerships.service``)
cancel open rows directly; that is the only exception.

Who may perform an action (assignee, creator, either) is checked by the service, not here.
"""

from enum import StrEnum
from typing import Literal, get_args

from app.modules.common.enums import (
    QuestOccurrenceStatus,
    QuestRevisionStatus,
    QuestTemplateStatus,
)

# A Literal, not an enum: StrEnums live only in common/enums.py and are all Postgres types.
Action = Literal[
    "accept",
    "decline",
    "cancel",
    "submit",
    "confirm",
    "request_redo",
    "expire",
    "pause",
    "resume",
    "complete",
    "supersede",
]
ACTIONS: tuple[Action, ...] = get_args(Action)


class InvalidTransitionError(Exception):
    def __init__(self, status: StrEnum, action: Action) -> None:
        super().__init__(f"cannot {action} a quest that is {status.value}")
        self.status = status
        self.action = action


_O = QuestOccurrenceStatus
_T = QuestTemplateStatus
_R = QuestRevisionStatus

OCCURRENCE_TRANSITIONS: dict[tuple[QuestOccurrenceStatus, Action], QuestOccurrenceStatus] = {
    (_O.OFFERED, "accept"): _O.ACTIVE,
    (_O.OFFERED, "decline"): _O.DECLINED,
    (_O.OFFERED, "cancel"): _O.CANCELLED,
    (_O.ACTIVE, "submit"): _O.IN_REVIEW,
    (_O.ACTIVE, "cancel"): _O.CANCELLED,
    (_O.ACTIVE, "expire"): _O.EXPIRED,
    (_O.IN_REVIEW, "confirm"): _O.COMPLETED,
    (_O.IN_REVIEW, "request_redo"): _O.ACTIVE,
}

TEMPLATE_TRANSITIONS: dict[tuple[QuestTemplateStatus, Action], QuestTemplateStatus] = {
    (_T.OFFERED, "accept"): _T.ACTIVE,
    (_T.OFFERED, "decline"): _T.DECLINED,
    (_T.OFFERED, "cancel"): _T.CANCELLED,
    (_T.ACTIVE, "pause"): _T.PAUSED,
    (_T.ACTIVE, "cancel"): _T.CANCELLED,
    (_T.ACTIVE, "complete"): _T.COMPLETED,
    (_T.PAUSED, "resume"): _T.ACTIVE,
    (_T.PAUSED, "cancel"): _T.CANCELLED,
}

REVISION_TRANSITIONS: dict[tuple[QuestRevisionStatus, Action], QuestRevisionStatus] = {
    (_R.PENDING, "accept"): _R.ACCEPTED,
    (_R.PENDING, "decline"): _R.DECLINED,
    (_R.PENDING, "supersede"): _R.SUPERSEDED,
}

#: Occurrence statuses that nothing can leave.
TERMINAL_OCCURRENCE = frozenset(
    s for s in QuestOccurrenceStatus if not any(k[0] == s for k in OCCURRENCE_TRANSITIONS)
)


def next_occurrence_status(status: QuestOccurrenceStatus, action: Action) -> QuestOccurrenceStatus:
    try:
        return OCCURRENCE_TRANSITIONS[(status, action)]
    except KeyError:
        raise InvalidTransitionError(status, action) from None


def next_template_status(status: QuestTemplateStatus, action: Action) -> QuestTemplateStatus:
    try:
        return TEMPLATE_TRANSITIONS[(status, action)]
    except KeyError:
        raise InvalidTransitionError(status, action) from None


def next_revision_status(status: QuestRevisionStatus, action: Action) -> QuestRevisionStatus:
    try:
        return REVISION_TRANSITIONS[(status, action)]
    except KeyError:
        raise InvalidTransitionError(status, action) from None
