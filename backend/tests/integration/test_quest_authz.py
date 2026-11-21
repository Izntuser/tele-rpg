"""Quest authorization matrix: non-members get 404 for every quest route (no IDOR), the wrong
member gets 403, a right member in the wrong state gets 409, and no route trusts a client id."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, ratelimit
from app.modules.common.enums import PartnershipStatus, QuestOccurrenceStatus
from app.modules.quests.models import QuestOccurrence, QuestTemplate
from app.modules.users.models import User
from tests import factories
from tests.integration.test_quest_offer_flow import auth, create_quest, pair, post


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def request(
    client: httpx.AsyncClient,
    user: User | None,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    headers = auth(user) if user is not None else {}
    return await client.request(method, f"/api{path}", headers=headers, json=body)


def occurrence_routes(occurrence_id: int) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", f"/quests/{occurrence_id}", None),
        ("PATCH", f"/quests/{occurrence_id}", {"gold": 1}),
        ("POST", f"/quests/{occurrence_id}/accept", None),
        ("POST", f"/quests/{occurrence_id}/decline", {"reason": "no"}),
        ("POST", f"/quests/{occurrence_id}/cancel", None),
    ]


def template_routes(template_id: int) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", f"/quest-templates/{template_id}", None),
        ("PATCH", f"/quest-templates/{template_id}", {"gold": 1}),
        ("POST", f"/quest-templates/{template_id}/accept", None),
        ("POST", f"/quest-templates/{template_id}/decline", None),
        ("POST", f"/quest-templates/{template_id}/cancel", None),
    ]


async def test_non_members_get_404_everywhere_and_change_nothing(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    created = await create_quest(client, gm)
    occurrence_id, template_id = created["occurrence"]["id"], created["template"]["id"]
    # A stranger in another active partnership, and one with no partnership at all.
    stranger, their_partner, _ = await pair(session)
    loner = await factories.create_user(session, onboarded_at=clock.now())

    for outsider in (stranger, their_partner, loner):
        for method, path, body in occurrence_routes(occurrence_id) + template_routes(template_id):
            response = await request(client, outsider, method, path, body)
            assert response.status_code == 404, (outsider.id, method, path, response.text)
            assert response.json()["detail"] == "Quest not found"
        for query in ("", "?role=player", "?role=gm"):
            listed = await request(client, outsider, "GET", f"/quests{query}")
            assert occurrence_id not in [i["id"] for i in listed.json()]
            listed = await request(client, outsider, "GET", f"/quest-templates{query}")
            assert template_id not in [i["id"] for i in listed.json()]

    occurrence = await session.get(QuestOccurrence, occurrence_id, populate_existing=True)
    assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.OFFERED
    assert occurrence.terms_snapshot["gold"] == 50


async def test_missing_ids_are_404_and_bad_ids_422(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, _, _ = await pair(session)
    for method, path, body in occurrence_routes(987_654) + template_routes(987_654):
        assert (await request(client, gm, method, path, body)).status_code == 404
    for bad in ("0", "-1", str(2**63), "abc"):
        ratelimit.reset_all()  # 40 write requests in this test, over the 30/min bucket
        for method, path, body in occurrence_routes(0) + template_routes(0):
            path = path.replace("/0", f"/{bad}")
            assert (await request(client, gm, method, path, body)).status_code == 422, path


async def test_every_route_needs_a_token(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, _, _ = await pair(session)
    created = await create_quest(client, gm)
    routes = occurrence_routes(created["occurrence"]["id"]) + template_routes(
        created["template"]["id"]
    )
    routes += [("GET", "/quests", None), ("POST", "/quests", {}), ("GET", "/quest-templates", None)]
    for method, path, body in routes:
        assert (await request(client, None, method, path, body)).status_code == 401, path


async def test_creator_cannot_accept_or_decline(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, _, _ = await pair(session)
    created = await create_quest(client, gm)
    recurring = await create_quest(client, gm, recurrence="daily")
    for path in (
        f"/quests/{created['occurrence']['id']}/accept",
        f"/quests/{created['occurrence']['id']}/decline",
        f"/quest-templates/{recurring['template']['id']}/accept",
        f"/quest-templates/{recurring['template']['id']}/decline",
    ):
        response = await post(client, gm, path)
        assert response.status_code == 403, path
    template = await session.get(QuestTemplate, recurring["template"]["id"], populate_existing=True)
    assert template is not None and template.status.value == "offered"


async def test_creator_cannot_accept_their_own_revision(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{occurrence_id}/accept")
    await request(client, gm, "PATCH", f"/quests/{occurrence_id}", {"gold": 99})
    assert (await post(client, gm, f"/quests/{occurrence_id}/accept")).status_code == 403
    assert (await post(client, gm, f"/quests/{occurrence_id}/decline")).status_code == 403


async def test_assignee_cannot_edit(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    created = await create_quest(client, gm)
    for path in (
        f"/quests/{created['occurrence']['id']}",
        f"/quest-templates/{created['template']['id']}",
    ):
        response = await request(client, player, "PATCH", path, {"gold": 1000})
        assert response.status_code == 403
    occurrence_id = created["occurrence"]["id"]
    await post(client, player, f"/quests/{occurrence_id}/accept")
    response = await request(client, player, "PATCH", f"/quests/{occurrence_id}", {"gold": 1000})
    assert response.status_code == 403
    occurrence = await session.get(QuestOccurrence, occurrence_id, populate_existing=True)
    assert occurrence is not None and occurrence.terms_snapshot["gold"] == 50


async def test_right_role_wrong_state_is_409(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{occurrence_id}/accept")
    # Active with no pending revision: nothing to accept or decline.
    assert (await post(client, player, f"/quests/{occurrence_id}/accept")).status_code == 409
    assert (await post(client, player, f"/quests/{occurrence_id}/decline")).status_code == 409
    await post(client, gm, f"/quests/{occurrence_id}/cancel")
    for user, path in (
        (player, f"/quests/{occurrence_id}/accept"),
        (player, f"/quests/{occurrence_id}/decline"),
        (gm, f"/quests/{occurrence_id}/cancel"),
        (player, f"/quests/{occurrence_id}/cancel"),
    ):
        assert (await post(client, user, path)).status_code == 409, path
    response = await request(client, gm, "PATCH", f"/quests/{occurrence_id}", {"gold": 2})
    assert response.status_code == 409


async def test_both_members_may_read(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    created = await create_quest(client, gm)
    for user, role in ((gm, "gm"), (player, "player")):
        detail = await request(client, user, "GET", f"/quests/{created['occurrence']['id']}")
        assert detail.status_code == 200 and detail.json()["role"] == role
        template = await request(
            client, user, "GET", f"/quest-templates/{created['template']['id']}"
        )
        assert template.status_code == 200 and template.json()["role"] == role


async def test_new_partner_cannot_see_quests_of_an_ended_partnership(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """After A and B split and A pairs with C, C never sees A+B quests, and A keeps read-only
    access to them as history."""
    a = await factories.create_user(session, onboarded_at=clock.now())
    b = await factories.create_user(session, onboarded_at=clock.now())
    old = await factories.create_partnership(session, a, b)
    occurrence_id = (await create_quest(client, a))["occurrence"]["id"]
    old.status = PartnershipStatus.ENDED
    old.ended_at = clock.now()
    await session.flush()
    c = await factories.create_user(session, onboarded_at=clock.now())
    await factories.create_partnership(session, a, c)

    for method, path, body in occurrence_routes(occurrence_id):
        assert (await request(client, c, method, path, body)).status_code == 404, path
    assert (await request(client, a, "GET", f"/quests/{occurrence_id}")).status_code == 200
    assert (await post(client, b, f"/quests/{occurrence_id}/accept")).status_code == 409
    listed = await request(client, a, "GET", "/quests")
    assert occurrence_id not in [i["id"] for i in listed.json()]
    # New quests go to the new partner only.
    created = await create_quest(client, a)
    assert created["template"]["assignee_id"] == c.id


async def test_deleted_member_token_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    player.deleted_at = clock.now()
    await session.flush()
    assert (await post(client, player, f"/quests/{occurrence_id}/accept")).status_code == 401
    assert (await request(client, player, "GET", f"/quests/{occurrence_id}")).status_code == 401


async def test_ids_in_bodies_never_change_ownership(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    await request(
        client,
        gm,
        "PATCH",
        f"/quests/{occurrence_id}",
        {"assignee_id": gm.id, "creator_id": player.id, "status": "completed", "xp": 5000},
    )
    template = await session.scalar(
        select(QuestTemplate)
        .join(QuestOccurrence, QuestOccurrence.template_id == QuestTemplate.id)
        .where(QuestOccurrence.id == occurrence_id)
        .execution_options(populate_existing=True)
    )
    assert template is not None
    assert (template.creator_id, template.assignee_id) == (gm.id, player.id)
    assert template.status.value == "offered"
