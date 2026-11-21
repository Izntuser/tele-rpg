from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, ratelimit
from app.core.config import get_settings
from app.modules.auth.jwt import encode_token
from app.modules.common.enums import GoalStatus, PartnershipStatus, WishlistStatus
from app.modules.goals.models import DevelopmentGoal
from app.modules.goals.schemas import MAX_GOALS
from app.modules.users.models import User
from app.modules.wishlist.models import WishlistItem
from app.modules.wishlist.schemas import MAX_WISHLIST_ITEMS
from tests import factories


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


def auth(user: User) -> dict[str, str]:
    token = encode_token(user.id, get_settings().jwt_secret.get_secret_value(), timedelta(hours=1))
    return {"Authorization": f"Bearer {token}"}


RESOURCES = ["/api/goals", "/api/wishlist"]


async def add_goal(session: AsyncSession, user: User, title: str = "Goal", **kw: Any) -> int:
    goal = DevelopmentGoal(user_id=user.id, title=title, **kw)
    session.add(goal)
    await session.flush()
    return goal.id


async def add_item(session: AsyncSession, user: User, title: str = "Item", **kw: Any) -> int:
    item = WishlistItem(user_id=user.id, title=title, **kw)
    session.add(item)
    await session.flush()
    return item.id


async def add(session: AsyncSession, base: str, user: User, title: str = "Thing") -> int:
    if base == "/api/goals":
        return await add_goal(session, user, title)
    return await add_item(session, user, title)


async def fetch(session: AsyncSession, base: str, row_id: int) -> tuple[int, str]:
    """(owner id, title) of a goal or wishlist row, straight from the database."""
    row: DevelopmentGoal | WishlistItem | None
    if base == "/api/goals":
        row = await session.get(DevelopmentGoal, row_id)
    else:
        row = await session.get(WishlistItem, row_id)
    assert row is not None
    await session.refresh(row)
    return row.user_id, row.title


# --- CRUD on my own items ------------------------------------------------------------------


async def test_goal_crud(client: httpx.AsyncClient, session: AsyncSession) -> None:
    me = await factories.create_user(session)
    h = auth(me)
    created = await client.post(
        "/api/goals",
        headers=h,
        json={"title": " Run more ", "description": "3x a week", "attribute": "physical"},
    )
    assert created.status_code == 201, created.text
    goal = created.json()
    assert goal["title"] == "Run more"
    assert (goal["attribute"], goal["status"]) == ("physical", "active")

    patched = await client.patch(
        f"/api/goals/{goal['id']}",
        headers=h,
        json={"title": "Run daily", "attribute": None, "status": "archived"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "Run daily"
    assert patched.json()["attribute"] is None
    assert patched.json()["status"] == "archived"
    assert patched.json()["description"] == "3x a week"

    listed = (await client.get("/api/goals", headers=h)).json()
    assert [g["id"] for g in listed] == [goal["id"]]

    deleted = await client.delete(f"/api/goals/{goal['id']}", headers=h)
    assert deleted.status_code == 204
    assert (await client.get("/api/goals", headers=h)).json() == []


async def test_wishlist_crud(client: httpx.AsyncClient, session: AsyncSession) -> None:
    me = await factories.create_user(session)
    h = auth(me)
    created = await client.post(
        "/api/wishlist", headers=h, json={"title": "Massage", "description": ""}
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert (item["title"], item["description"], item["status"]) == ("Massage", None, "open")
    assert item["linked_reward_id"] is None

    patched = await client.patch(
        f"/api/wishlist/{item['id']}", headers=h, json={"status": "archived", "title": "Spa"}
    )
    assert patched.status_code == 200
    assert (patched.json()["title"], patched.json()["status"]) == ("Spa", "archived")
    reopened = await client.patch(f"/api/wishlist/{item['id']}", headers=h, json={"status": "open"})
    assert reopened.json()["status"] == "open"

    assert [i["id"] for i in (await client.get("/api/wishlist", headers=h)).json()] == [item["id"]]
    assert (await client.delete(f"/api/wishlist/{item['id']}", headers=h)).status_code == 204
    assert (await client.get("/api/wishlist", headers=h)).json() == []


async def test_lists_only_contain_my_items(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await factories.create_user(session)
    stranger = await factories.create_user(session)
    await add_goal(session, me, "mine")
    await add_goal(session, stranger, "theirs")
    await add_item(session, me, "mine")
    await add_item(session, stranger, "theirs")
    for base in RESOURCES:
        titles = [x["title"] for x in (await client.get(base, headers=auth(me))).json()]
        assert titles == ["mine"], base


# --- Authorization / IDOR --------------------------------------------------------------------


@pytest.mark.parametrize("base", RESOURCES)
async def test_editing_or_deleting_another_users_item_is_404(
    client: httpx.AsyncClient, session: AsyncSession, base: str
) -> None:
    me = await factories.create_user(session)
    other = await factories.create_user(session)
    await factories.create_partnership(session, me, other)  # even my companion's items
    their_id = await add(session, base, other, "theirs")

    patch = await client.patch(f"{base}/{their_id}", headers=auth(me), json={"title": "pwned"})
    delete = await client.delete(f"{base}/{their_id}", headers=auth(me))
    missing = await client.patch(f"{base}/987654321", headers=auth(me), json={"title": "x"})
    assert (patch.status_code, delete.status_code, missing.status_code) == (404, 404, 404)
    assert patch.json() == missing.json()  # no existence oracle

    assert await fetch(session, base, their_id) == (other.id, "theirs")


@pytest.mark.parametrize("base", RESOURCES)
@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", str(2**63), "1.5"])
async def test_invalid_ids_are_422(
    client: httpx.AsyncClient, session: AsyncSession, base: str, bad_id: str
) -> None:
    me = await factories.create_user(session)
    response = await client.delete(f"{base}/{bad_id}", headers=auth(me))
    assert response.status_code == 422


@pytest.mark.parametrize("base", RESOURCES)
async def test_routes_require_auth(client: httpx.AsyncClient, base: str) -> None:
    assert (await client.get(base)).status_code == 401
    assert (await client.post(base, json={"title": "x"})).status_code == 401
    assert (await client.patch(f"{base}/1", json={"title": "x"})).status_code == 401
    assert (await client.delete(f"{base}/1")).status_code == 401


@pytest.mark.parametrize("base", RESOURCES)
async def test_create_ignores_owner_and_server_fields(
    client: httpx.AsyncClient, session: AsyncSession, base: str
) -> None:
    me = await factories.create_user(session)
    victim = await factories.create_user(session)
    response = await client.post(
        base,
        headers=auth(me),
        json={
            "title": "x",
            "user_id": victim.id,
            "id": 424242,
            "status": "offered",
            "linked_reward_id": 1,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] != 424242
    assert body["status"] in ("active", "open")
    assert (await fetch(session, base, body["id"]))[0] == me.id
    model: type[DevelopmentGoal] | type[WishlistItem] = (
        DevelopmentGoal if base == "/api/goals" else WishlistItem
    )
    victim_count = await session.scalar(
        select(func.count()).select_from(model).where(model.user_id == victim.id)
    )
    assert victim_count == 0


async def test_wishlist_status_offered_is_not_client_settable(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await factories.create_user(session)
    item_id = await add_item(session, me)
    response = await client.patch(
        f"/api/wishlist/{item_id}",
        headers=auth(me),
        json={"status": "offered", "linked_reward_id": 5},
    )
    assert response.status_code == 422
    ignored = await client.patch(
        f"/api/wishlist/{item_id}", headers=auth(me), json={"linked_reward_id": 5}
    )
    assert ignored.status_code == 200
    assert ignored.json()["linked_reward_id"] is None


async def test_wishlist_item_linked_to_a_reward_cannot_be_deleted_or_reopened(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await factories.create_user(session)
    companion = await factories.create_user(session)
    partnership = await factories.create_partnership(session, me, companion)
    item_id = await add_item(session, me, status=WishlistStatus.OFFERED)
    reward = await factories.create_reward(
        session, partnership, companion, source_wishlist_item_id=item_id
    )
    item = await session.get(WishlistItem, item_id)
    assert item is not None
    item.linked_reward_id = reward.id
    await session.flush()

    assert (await client.delete(f"/api/wishlist/{item_id}", headers=auth(me))).status_code == 409
    archived = await client.patch(
        f"/api/wishlist/{item_id}", headers=auth(me), json={"status": "archived"}
    )
    assert archived.status_code == 200
    reopen = await client.patch(
        f"/api/wishlist/{item_id}", headers=auth(me), json={"status": "open"}
    )
    assert reopen.status_code == 409


# --- Validation and limits -------------------------------------------------------------------


@pytest.mark.parametrize("base", RESOURCES)
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": None},
        {"title": "t" * 201},
        {"title": "a\x07b"},
        {"title": "ok", "description": "d" * 1001},
        {"title": 123},
    ],
)
async def test_create_validates(
    client: httpx.AsyncClient, session: AsyncSession, base: str, payload: dict[str, Any]
) -> None:
    me = await factories.create_user(session)
    assert (await client.post(base, headers=auth(me), json=payload)).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [{"title": None}, {"status": None}, {"status": "done"}, {"attribute": "magic"}, {"title": ""}],
)
async def test_goal_patch_validates(
    client: httpx.AsyncClient, session: AsyncSession, payload: dict[str, Any]
) -> None:
    me = await factories.create_user(session)
    goal_id = await add_goal(session, me)
    response = await client.patch(f"/api/goals/{goal_id}", headers=auth(me), json=payload)
    assert response.status_code == 422


async def test_goal_limit(client: httpx.AsyncClient, session: AsyncSession) -> None:
    me = await factories.create_user(session)
    session.add_all(DevelopmentGoal(user_id=me.id, title=f"g{i}") for i in range(MAX_GOALS))
    await session.flush()
    response = await client.post("/api/goals", headers=auth(me), json={"title": "one more"})
    assert response.status_code == 409


async def test_wishlist_limit(client: httpx.AsyncClient, session: AsyncSession) -> None:
    me = await factories.create_user(session)
    session.add_all(WishlistItem(user_id=me.id, title=f"w{i}") for i in range(MAX_WISHLIST_ITEMS))
    await session.flush()
    response = await client.post("/api/wishlist", headers=auth(me), json={"title": "one more"})
    assert response.status_code == 409


# --- ?user=companion -------------------------------------------------------------------------


@pytest.mark.parametrize("base", RESOURCES)
async def test_companion_items_visible_only_while_partnership_is_active(
    client: httpx.AsyncClient, session: AsyncSession, base: str
) -> None:
    me = await factories.create_user(session)
    companion = await factories.create_user(session)
    stranger = await factories.create_user(session)
    partnership = await factories.create_partnership(session, me, companion)
    await add(session, base, companion, "companion's")
    await add(session, base, stranger, "stranger's")
    await add(session, base, me, "mine")

    response = await client.get(base, params={"user": "companion"}, headers=auth(me))
    assert response.status_code == 200
    assert [x["title"] for x in response.json()] == ["companion's"]

    partnership.status = PartnershipStatus.ENDED
    await session.flush()
    ended = await client.get(base, params={"user": "companion"}, headers=auth(me))
    assert ended.status_code == 403


@pytest.mark.parametrize("base", RESOURCES)
@pytest.mark.parametrize("state", ["pending", "left", "ended", "companion_deleted"])
async def test_companion_403_unless_partnership_is_active(
    client: httpx.AsyncClient, session: AsyncSession, base: str, state: str
) -> None:
    """pending: only an unaccepted invitation; left: ended through POST /partnership/leave;
    ended: an ENDED row; companion_deleted: an (inconsistent) active row whose other member
    is deleted (resolve_owner's defence in depth)."""
    now = clock.now()
    me = await factories.create_user(session, onboarded_at=now)
    companion = await factories.create_user(session, onboarded_at=now)
    await add(session, base, companion, "companion's")
    if state == "pending":
        await factories.create_invitation(session, companion)
    elif state == "left":
        await factories.create_partnership(session, me, companion)
        left = await client.post(
            "/api/partnership/leave", headers=auth(companion), json={"confirm_text": "LEAVE"}
        )
        assert left.status_code == 204
    elif state == "ended":
        await factories.create_partnership(session, me, companion, status=PartnershipStatus.ENDED)
    else:
        await factories.create_partnership(session, me, companion)
        companion.deleted_at = now
        await session.flush()
    response = await client.get(base, params={"user": "companion"}, headers=auth(me))
    assert response.status_code == 403


@pytest.mark.parametrize("base", RESOURCES)
async def test_companion_without_partnership_is_403(
    client: httpx.AsyncClient, session: AsyncSession, base: str
) -> None:
    me = await factories.create_user(session)
    response = await client.get(base, params={"user": "companion"}, headers=auth(me))
    assert response.status_code == 403


@pytest.mark.parametrize("base", RESOURCES)
@pytest.mark.parametrize("who", ["1", "other", "COMPANION", ""])
async def test_user_param_only_accepts_me_or_companion(
    client: httpx.AsyncClient, session: AsyncSession, base: str, who: str
) -> None:
    me = await factories.create_user(session)
    response = await client.get(base, params={"user": who}, headers=auth(me))
    assert response.status_code == 422


async def test_companion_does_not_see_archived(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await factories.create_user(session)
    companion = await factories.create_user(session)
    await factories.create_partnership(session, me, companion)
    await add_goal(session, companion, "visible")
    await add_goal(session, companion, "archived", status=GoalStatus.ARCHIVED)
    await add_item(session, companion, "open")
    await add_item(session, companion, "archived", status=WishlistStatus.ARCHIVED)
    goals = (await client.get("/api/goals?user=companion", headers=auth(me))).json()
    items = (await client.get("/api/wishlist?user=companion", headers=auth(me))).json()
    assert [g["title"] for g in goals] == ["visible"]
    assert [i["title"] for i in items] == ["open"]
    mine = (await client.get("/api/goals?user=me", headers=auth(companion))).json()
    assert {g["title"] for g in mine} == {"visible", "archived"}


async def test_writes_cannot_target_the_companion(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await factories.create_user(session)
    companion = await factories.create_user(session)
    await factories.create_partnership(session, me, companion)
    response = await client.post(
        "/api/goals?user=companion", headers=auth(me), json={"title": "for you"}
    )
    assert response.status_code == 201
    row = await session.get(DevelopmentGoal, response.json()["id"])
    assert row is not None and row.user_id == me.id
