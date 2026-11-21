"""Quest presets, saved templates (own rows only) and the gold estimate."""

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, ratelimit
from app.modules.common.enums import Attribute, Locale
from app.modules.quests import presets
from app.modules.quests.models import SavedQuestTemplate
from tests import factories
from tests.integration.completion_support import auth, ident


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


def saved_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "title": "Evening walk",
        "attribute": "wellbeing",
        "difficulty": "easy",
        "gold": 30,
        "recurrence": "daily",
    }
    body.update(overrides)
    return body


async def test_builtins_cover_every_attribute_and_are_localized(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    en = await factories.create_user(session, onboarded_at=clock.now(), locale=Locale.EN)
    uk = await factories.create_user(session, onboarded_at=clock.now(), locale=Locale.UK)
    got_en = (await client.get("/api/quest-presets", headers=auth(en))).json()
    got_uk = (await client.get("/api/quest-presets", headers=auth(uk))).json()
    assert len(got_en["builtin"]) == 24 == len(presets.BUILTINS)
    assert {p["attribute"] for p in got_en["builtin"]} == {a.value for a in Attribute}
    assert len({p["key"] for p in got_en["builtin"]}) == 24
    assert got_en["builtin"][0]["title"] == "Go for a run"
    assert got_uk["builtin"][0]["title"] == "Піти на пробіжку"
    assert all(p["builtin"] and p["saved_id"] is None for p in got_en["builtin"])
    assert all(0 <= p["gold"] <= 1000 for p in got_en["builtin"])
    assert got_en["saved"] == []


async def test_save_list_and_delete_only_my_templates(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    alice = await factories.create_user(session, onboarded_at=clock.now())
    bob = await factories.create_user(session, onboarded_at=clock.now())
    created = await client.post("/api/quest-presets", headers=auth(alice), json=saved_body())
    assert created.status_code == 201
    saved_id = created.json()["saved_id"]
    assert created.json()["builtin"] is False

    mine = (await client.get("/api/quest-presets", headers=auth(alice))).json()["saved"]
    assert [p["saved_id"] for p in mine] == [saved_id]
    assert (await client.get("/api/quest-presets", headers=auth(bob))).json()["saved"] == []

    # Bob cannot delete it (404, not 403: ids of others are not revealed) and it survives.
    foreign = await client.delete(f"/api/quest-presets/{saved_id}", headers=auth(bob))
    assert foreign.status_code == 404
    assert await session.scalar(select(func.count()).select_from(SavedQuestTemplate)) == 1

    assert (
        await client.delete(f"/api/quest-presets/{saved_id}", headers=auth(alice))
    ).status_code == 204
    assert (
        await client.delete(f"/api/quest-presets/{saved_id}", headers=auth(alice))
    ).status_code == 404
    assert await session.scalar(select(func.count()).select_from(SavedQuestTemplate)) == 0


async def test_save_ignores_client_owner_and_validates_input(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    alice = await factories.create_user(session, onboarded_at=clock.now())
    bob = await factories.create_user(session, onboarded_at=clock.now())
    response = await client.post(
        "/api/quest-presets", headers=auth(alice), json=saved_body(owner_id=ident(bob))
    )
    assert response.status_code == 201
    row = await session.scalar(select(SavedQuestTemplate))
    assert row is not None and row.owner_id == ident(alice)
    for bad in (
        saved_body(gold=1001),
        saved_body(gold=-1),
        saved_body(title=""),
        saved_body(attribute="x"),
    ):
        assert (
            await client.post("/api/quest-presets", headers=auth(alice), json=bad)
        ).status_code == 422


async def test_saved_templates_are_capped(client: httpx.AsyncClient, session: AsyncSession) -> None:
    alice = await factories.create_user(session, onboarded_at=clock.now())
    session.add_all(
        SavedQuestTemplate(
            owner_id=ident(alice),
            title=f"t{i}",
            attribute=Attribute.PHYSICAL,
            difficulty="easy",
            gold=1,
            recurrence="once",
        )
        for i in range(presets.MAX_SAVED)
    )
    await session.commit()
    response = await client.post("/api/quest-presets", headers=auth(alice), json=saved_body())
    assert response.status_code == 409


async def test_presets_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/quest-presets")).status_code == 401
    assert (await client.post("/api/quest-presets", json=saved_body())).status_code == 401
    assert (await client.delete("/api/quest-presets/1")).status_code == 401
    assert (await client.get("/api/quests/estimate?gold=5")).status_code == 401


@pytest.mark.parametrize(
    ("gold", "recurrence", "weekly", "monthly"),
    [
        (50, "daily", 350, 1500),
        (50, "weekly", 50, 200),
        (50, "once", 50, 50),
        (0, "daily", 0, 0),
    ],
)
async def test_estimate(
    client: httpx.AsyncClient,
    session: AsyncSession,
    gold: int,
    recurrence: str,
    weekly: int,
    monthly: int,
) -> None:
    user = await factories.create_user(session, onboarded_at=clock.now())
    response = await client.get(
        f"/api/quests/estimate?gold={gold}&recurrence={recurrence}", headers=auth(user)
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "gold": gold,
        "recurrence": recurrence,
        "weekly": weekly,
        "monthly": monthly,
    }


async def test_estimate_rejects_bad_input_and_is_not_shadowed_by_quest_id(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(session, onboarded_at=clock.now())
    for query in ("", "?gold=1001", "?gold=-1", "?gold=5&recurrence=hourly", "?gold=x"):
        response = await client.get(f"/api/quests/estimate{query}", headers=auth(user))
        assert response.status_code == 422, (query, response.text)
