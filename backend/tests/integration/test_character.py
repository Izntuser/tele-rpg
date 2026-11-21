import asyncio
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import ratelimit
from app.core.config import get_settings
from app.modules.auth.jwt import encode_token
from app.modules.common.enums import Attribute, Locale, PartnershipStatus
from app.modules.goals.models import DevelopmentGoal
from app.modules.users import service
from app.modules.users.models import Character, CharacterAttribute, User
from app.modules.users.schemas import OnboardingIn
from tests import factories


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


def auth(user: User) -> dict[str, str]:
    token = encode_token(user.id, get_settings().jwt_secret.get_secret_value(), timedelta(hours=1))
    return {"Authorization": f"Bearer {token}"}


ONBOARDING: dict[str, Any] = {
    "name": "Aria",
    "nickname": "The Brave",
    "bio": "Learning to run.",
    "timezone": "Europe/Kyiv",
    "goals": [
        {"title": "Exercise more", "attribute": "physical"},
        {"title": "Read more books"},
    ],
}


# --- GET /character ------------------------------------------------------------------------


async def test_get_character_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/character")).status_code == 401


async def test_get_character_404_before_onboarding(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(session, with_character=False)
    response = await client.get("/api/character", headers=auth(user))
    assert response.status_code == 404


async def test_get_character_derives_levels_attributes_and_gold(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(
        session, with_character=False, avatar_url="https://t.me/a.jpg"
    )
    character = await factories.create_character(session, user, name="Aria", total_xp=260)
    attr = await session.get(CharacterAttribute, (character.id, Attribute.DISCIPLINE))
    assert attr is not None
    attr.xp = 120
    companion = await factories.create_user(session)
    partnership = await factories.create_partnership(session, user, companion)
    await factories.create_wallet(session, user, partnership, balance=75)
    await session.flush()

    response = await client.get("/api/character", headers=auth(user))
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Aria"
    assert body["avatar_url"] == "https://t.me/a.jpg"
    assert (body["level"], body["total_xp"]) == (3, 260)
    assert (body["xp_into_level"], body["xp_for_next_level"], body["xp_to_next_level"]) == (
        10,
        200,
        190,
    )
    assert body["gold"] == 75
    assert [a["attribute"] for a in body["attributes"]] == [a.value for a in Attribute]
    discipline = next(a for a in body["attributes"] if a["attribute"] == "discipline")
    assert discipline == {
        "attribute": "discipline",
        "xp": 120,
        "level": 2,
        "xp_into_level": 20,
        "xp_for_next_level": 150,
    }
    assert all(a["level"] == 1 for a in body["attributes"] if a["attribute"] != "discipline")


async def test_gold_is_zero_without_an_active_wallet(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(session)
    other = await factories.create_user(session)
    ended = await factories.create_partnership(session, user, other, status=PartnershipStatus.ENDED)
    await factories.create_wallet(session, user, ended, balance=40)
    response = await client.get("/api/character", headers=auth(user))
    assert response.json()["gold"] == 0


async def test_get_character_never_shows_another_users_gold(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await factories.create_user(session)
    companion = await factories.create_user(session)
    partnership = await factories.create_partnership(session, me, companion)
    await factories.create_wallet(session, companion, partnership, balance=999)
    body = (await client.get("/api/character", headers=auth(me))).json()
    assert body["gold"] == 0
    assert body["name"] == me.display_name


# --- PATCH /character ----------------------------------------------------------------------


async def test_patch_updates_profile_fields(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(session)
    response = await client.patch(
        "/api/character",
        headers=auth(user),
        json={
            "name": "  New Name  ",
            "nickname": "Nick",
            "bio": "line one\nline two",
            "locale": "uk",
            "timezone": "America/New_York",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["nickname"], body["bio"]) == (
        "New Name",
        "Nick",
        "line one\nline two",
    )
    assert (body["locale"], body["timezone"]) == ("uk", "America/New_York")
    await session.refresh(user)
    assert (user.locale, user.timezone) == (Locale.UK, "America/New_York")


async def test_patch_omitted_fields_are_kept_and_empty_clears(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(session)
    await client.patch("/api/character", headers=auth(user), json={"nickname": "N", "bio": "B"})
    body = (
        await client.patch("/api/character", headers=auth(user), json={"nickname": "  "})
    ).json()
    assert body["nickname"] is None
    assert body["bio"] == "B"
    assert body["name"] == user.display_name


@pytest.mark.parametrize(
    "payload",
    [
        {"timezone": "Mars/Olympus"},
        {"timezone": "localtime"},
        {"timezone": "../../etc/passwd"},
        {"timezone": "posix/Europe/Kyiv"},
        {"timezone": "+02:00"},
        {"timezone": None},
        {"locale": "de"},
        {"locale": None},
        {"name": ""},
        {"name": "   "},
        {"name": None},
        {"name": "x" * 65},
        {"name": "bad\x00name"},
        {"name": "two\nlines"},
        {"name": "evil‮txt"},
        {"nickname": "n" * 65},
        {"bio": "b" * 501},
    ],
)
async def test_patch_rejects_invalid_input(
    client: httpx.AsyncClient, session: AsyncSession, payload: dict[str, Any]
) -> None:
    user = await factories.create_user(session)
    response = await client.patch("/api/character", headers=auth(user), json=payload)
    assert response.status_code == 422, payload


async def test_patch_ignores_xp_level_and_gold(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(session)
    response = await client.patch(
        "/api/character",
        headers=auth(user),
        json={
            "name": "Hacker",
            "total_xp": 999_999,
            "level": 99,
            "gold": 5000,
            "xp": 1,
            "id": 12345,
            "user_id": 1,
            "onboarded_at": "2020-01-01T00:00:00Z",
            "attributes": [{"attribute": "physical", "xp": 9999}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["total_xp"], body["level"], body["gold"]) == ("Hacker", 0, 1, 0)
    assert all(a["xp"] == 0 for a in body["attributes"])
    character = await session.scalar(select(Character).where(Character.user_id == user.id))
    assert character is not None and character.total_xp == 0
    await session.refresh(user)
    assert user.onboarded_at is None


async def test_patch_404_without_character(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(session, with_character=False)
    response = await client.patch("/api/character", headers=auth(user), json={"name": "A"})
    assert response.status_code == 404


async def test_patch_only_touches_my_character(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await factories.create_user(session)
    other = await factories.create_user(session, display_name="Other")
    await client.patch("/api/character", headers=auth(me), json={"name": "Me"})
    other_char = await session.scalar(select(Character).where(Character.user_id == other.id))
    assert other_char is not None and other_char.name == "Other"


async def test_patch_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.patch("/api/character", json={"name": "x"})).status_code == 401


# --- POST /character/onboarding/complete ---------------------------------------------------


async def test_onboarding_creates_character_attributes_goals(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: Any
) -> None:
    user = await factories.create_user(session, with_character=False)
    response = await client.post(
        "/api/character/onboarding/complete", headers=auth(user), json=ONBOARDING
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["onboarded_at"] is not None
    assert body["user"]["timezone"] == "Europe/Kyiv"
    character = body["character"]
    assert (character["name"], character["nickname"], character["bio"]) == (
        "Aria",
        "The Brave",
        "Learning to run.",
    )
    assert (character["level"], character["total_xp"], character["gold"]) == (1, 0, 0)
    assert len(character["attributes"]) == 6

    db_char = await session.scalar(select(Character).where(Character.user_id == user.id))
    assert db_char is not None
    attr_count = await session.scalar(
        select(func.count())
        .select_from(CharacterAttribute)
        .where(CharacterAttribute.character_id == db_char.id)
    )
    assert attr_count == 6
    titles = list(
        await session.scalars(
            select(DevelopmentGoal.title)
            .where(DevelopmentGoal.user_id == user.id)
            .order_by(DevelopmentGoal.id)
        )
    )
    assert titles == ["Exercise more", "Read more books"]
    await session.refresh(user)
    assert user.onboarded_at == frozen_clock.now()

    me = (await client.get("/api/auth/me", headers=auth(user))).json()
    assert me["character"]["name"] == "Aria"
    assert me["user"]["onboarded_at"] is not None


async def test_onboarding_twice_is_409(client: httpx.AsyncClient, session: AsyncSession) -> None:
    user = await factories.create_user(session, with_character=False)
    first = await client.post(
        "/api/character/onboarding/complete", headers=auth(user), json=ONBOARDING
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/character/onboarding/complete", headers=auth(user), json=ONBOARDING
    )
    assert second.status_code == 409
    count = await session.scalar(
        select(func.count()).select_from(Character).where(Character.user_id == user.id)
    )
    assert count == 1


async def test_onboarding_dedupes_goals_and_ignores_privileged_fields(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await factories.create_user(session, with_character=False)
    payload = {
        **ONBOARDING,
        "goals": [{"title": "Sleep"}, {"title": " sleep "}, {"title": "Sleep", "user_id": 1}],
        "total_xp": 5000,
        "gold": 100,
        "level": 7,
        "onboarded_at": "2000-01-01T00:00:00Z",
    }
    response = await client.post(
        "/api/character/onboarding/complete", headers=auth(user), json=payload
    )
    assert response.status_code == 200, response.text
    character = response.json()["character"]
    assert (character["total_xp"], character["level"], character["gold"]) == (0, 1, 0)
    count = await session.scalar(
        select(func.count()).select_from(DevelopmentGoal).where(DevelopmentGoal.user_id == user.id)
    )
    assert count == 1


@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"name": None},
        {"timezone": "Nowhere/Land"},
        {"timezone": None},
        {"goals": [{"title": f"g{i}"} for i in range(11)]},
        {"goals": [{"title": ""}]},
        {"goals": [{"title": "x" * 201}]},
        {"goals": [{"title": "ok", "attribute": "magic"}]},
    ],
)
async def test_onboarding_validates(
    client: httpx.AsyncClient, session: AsyncSession, change: dict[str, Any]
) -> None:
    user = await factories.create_user(session, with_character=False)
    response = await client.post(
        "/api/character/onboarding/complete", headers=auth(user), json={**ONBOARDING, **change}
    )
    assert response.status_code == 422, change
    await session.refresh(user)
    assert user.onboarded_at is None


async def test_onboarding_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/character/onboarding/complete", json=ONBOARDING)
    assert response.status_code == 401


async def test_concurrent_onboarding_creates_one_character(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_sessions() as s:
        user = await factories.create_user(s, with_character=False)
        await s.commit()
        user_id = user.id
    data = OnboardingIn.model_validate(ONBOARDING)

    async def attempt() -> str:
        async with independent_sessions() as s:
            me = await s.get(User, user_id)
            assert me is not None
            try:
                await service.complete_onboarding(s, me, data)
            except service.AlreadyOnboardedError:
                return "conflict"
            return "ok"

    results = sorted(await asyncio.gather(*(attempt() for _ in range(4))))
    assert results == ["conflict", "conflict", "conflict", "ok"]
    async with independent_sessions() as s:
        characters = await s.scalar(
            select(func.count()).select_from(Character).where(Character.user_id == user_id)
        )
        goals = await s.scalar(
            select(func.count())
            .select_from(DevelopmentGoal)
            .where(DevelopmentGoal.user_id == user_id)
        )
    assert (characters, goals) == (1, 2)
