import asyncio
import hashlib
import logging
import re
from datetime import timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock, ratelimit
from app.core.config import get_settings
from app.modules.auth.jwt import encode_token
from app.modules.common.enums import (
    GoalStatus,
    InvitationStatus,
    PartnershipStatus,
    QuestOccurrenceStatus,
    QuestTemplateStatus,
    RewardStatus,
    WishlistStatus,
)
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.goals.models import DevelopmentGoal
from app.modules.notifications.models import Notification
from app.modules.partnerships import service
from app.modules.partnerships.models import Partnership, PartnershipInvitation
from app.modules.quests.models import QuestOccurrence, QuestTemplate
from app.modules.rewards.models import Reward
from app.modules.users.models import User
from app.modules.wishlist.models import WishlistItem
from tests import factories

LINK = re.compile(
    r"^https://t\.me/([A-Za-z0-9_]+)/([A-Za-z0-9_]+)\?startapp=invite_([A-Za-z0-9_-]+)$"
)


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


def auth(user: User) -> dict[str, str]:
    token = encode_token(user.id, get_settings().jwt_secret.get_secret_value(), timedelta(hours=1))
    return {"Authorization": f"Bearer {token}"}


async def onboarded(session: AsyncSession, **kw: Any) -> User:
    return await factories.create_user(session, onboarded_at=clock.now(), **kw)


async def invite(client: httpx.AsyncClient, user: User) -> str:
    response = await client.post("/api/partnership/invitations", headers=auth(user))
    assert response.status_code == 201, response.text
    token: str = response.json()["token"]
    return token


async def accept(client: httpx.AsyncClient, user: User, token: str) -> httpx.Response:
    return await client.post(
        "/api/partnership/invitations/accept", headers=auth(user), json={"token": token}
    )


async def leave(client: httpx.AsyncClient, user: User, text: str = "LEAVE") -> httpx.Response:
    return await client.post(
        "/api/partnership/leave", headers=auth(user), json={"confirm_text": text}
    )


async def pair(client: httpx.AsyncClient, inviter: User, invitee: User) -> int:
    response = await accept(client, invitee, await invite(client, inviter))
    assert response.status_code == 200, response.text
    partnership_id: int = response.json()["partnership"]["id"]
    return partnership_id


# --- invitations -----------------------------------------------------------------------------


async def test_invitation_link_and_only_the_token_hash_is_stored(
    client: httpx.AsyncClient,
    session: AsyncSession,
    frozen_clock: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "tg_bot_username", "rpg_bot")
    monkeypatch.setattr(get_settings(), "tg_app_short_name", "play")
    me = await onboarded(session)
    response = await client.post("/api/partnership/invitations", headers=auth(me))
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    match = LINK.match(body["link"])
    assert match, body["link"]
    assert match.group(1, 2) == ("rpg_bot", "play")
    token = body["token"]
    assert match.group(3) == token
    assert len(token) >= 43  # 32 random bytes

    rows = (await session.scalars(select(PartnershipInvitation))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in {str(getattr(row, c.key)) for c in row.__mapper__.column_attrs}
    assert row.status == InvitationStatus.PENDING
    assert row.expires_at == frozen_clock.now() + timedelta(days=7)


async def test_link_falls_back_outside_prod_and_fails_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "tg_bot_username", "")
    monkeypatch.setattr(settings, "tg_app_short_name", "")
    assert LINK.match(service.invite_link(settings, "abcDEF_-123"))
    monkeypatch.setattr(settings, "app_env", "prod")
    with pytest.raises(service.InviteLinkNotConfiguredError):
        service.invite_link(settings, "abcDEF_-123")


async def test_new_invitation_revokes_the_previous_pending_one(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me, other = await onboarded(session), await onboarded(session)
    first = await invite(client, me)
    second = await invite(client, me)
    assert first != second
    statuses = (
        await session.execute(
            select(PartnershipInvitation.status).order_by(PartnershipInvitation.id)
        )
    ).scalars()
    assert list(statuses) == [InvitationStatus.REVOKED, InvitationStatus.PENDING]
    assert (await accept(client, other, first)).status_code == 410
    assert (await accept(client, other, second)).status_code == 200


async def test_revoke_current_invitation(client: httpx.AsyncClient, session: AsyncSession) -> None:
    me, other = await onboarded(session), await onboarded(session)
    token = await invite(client, me)
    state = (await client.get("/api/partnership", headers=auth(me))).json()
    assert state["pending_invitation"] is not None
    response = await client.delete("/api/partnership/invitations/current", headers=auth(me))
    assert response.status_code == 204
    assert (await client.get("/api/partnership", headers=auth(me))).json() == {
        "partnership": None,
        "pending_invitation": None,
    }
    assert (await accept(client, other, token)).status_code == 410


async def test_cannot_invite_before_onboarding_or_while_paired(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    fresh = await factories.create_user(session)
    response = await client.post("/api/partnership/invitations", headers=auth(fresh))
    assert response.status_code == 409
    a, b = await onboarded(session), await onboarded(session)
    await factories.create_partnership(session, a, b)
    response = await client.post("/api/partnership/invitations", headers=auth(a))
    assert response.status_code == 409


async def test_preview_shows_the_inviter_without_telegram_identity(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    inviter = await onboarded(session, display_name="Alice A")
    me = await onboarded(session)
    token = await invite(client, inviter)
    response = await client.post(
        "/api/partnership/invitations/preview", headers=auth(me), json={"token": token}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inviter"]["display_name"] == "Alice A"
    assert body["inviter"]["level"] == 1
    assert "tg_user_id" not in str(body) and "tg_username" not in str(body)
    own = await client.post(
        "/api/partnership/invitations/preview", headers=auth(inviter), json={"token": token}
    )
    assert own.status_code == 409


# --- accept ----------------------------------------------------------------------------------


async def test_accept_creates_an_active_partnership_with_two_wallets(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    inviter, me = await onboarded(session), await onboarded(session)
    my_own_pending = await invite(client, me)
    token = await invite(client, inviter)
    response = await accept(client, me, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reactivated"] is False
    assert body["partnership"]["companion"]["user_id"] == inviter.id

    partnership = await session.get(Partnership, body["partnership"]["id"])
    assert partnership is not None
    assert partnership.status == PartnershipStatus.ACTIVE
    assert (partnership.user_a_id, partnership.user_b_id) == tuple(sorted((inviter.id, me.id)))
    wallets = (
        await session.scalars(select(Wallet).where(Wallet.partnership_id == partnership.id))
    ).all()
    assert sorted(w.user_id for w in wallets) == sorted((inviter.id, me.id))
    assert all(w.balance == 0 for w in wallets)

    invitation = await session.scalar(
        select(PartnershipInvitation).where(PartnershipInvitation.creator_id == inviter.id)
    )
    assert invitation is not None
    assert (invitation.status, invitation.accepted_by) == (InvitationStatus.ACCEPTED, me.id)
    # Pairing revokes the invitee's own pending invite.
    assert (await accept(client, await onboarded(session), my_own_pending)).status_code == 410
    note = await session.scalar(select(Notification).where(Notification.recipient_id == inviter.id))
    assert note is not None and note.type == "partnership_accepted"

    for who, other in ((me, inviter), (inviter, me)):
        state = (await client.get("/api/partnership", headers=auth(who))).json()
        assert state["partnership"]["companion"]["user_id"] == other.id
        summary = (await client.get("/api/auth/me", headers=auth(who))).json()["partnership"]
        assert summary["companion"]["id"] == other.id


async def test_accept_rejects_bad_tokens(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    inviter, me, third = (
        await onboarded(session),
        await onboarded(session),
        await onboarded(session),
    )

    unknown = await accept(client, me, "x" * 43)
    assert unknown.status_code == 404
    malformed = await accept(client, me, "bad token!")
    assert malformed.status_code == 422

    token = await invite(client, inviter)
    assert (await accept(client, inviter, token)).status_code == 409  # own invitation

    frozen_clock.advance(timedelta(days=7, seconds=1))
    assert (await accept(client, me, token)).status_code == 410  # expired
    frozen_clock.advance(-timedelta(days=7, seconds=1))

    assert (await accept(client, me, token)).status_code == 200
    assert (await accept(client, third, token)).status_code == 410  # already used


async def test_accept_while_already_partnered_is_409(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    inviter, me, current = (
        await onboarded(session),
        await onboarded(session),
        await onboarded(session),
    )
    token = await invite(client, inviter)
    await factories.create_partnership(session, me, current)
    assert (await accept(client, me, token)).status_code == 409

    # ... and when the inviter got paired after creating the link.
    other_inviter, newcomer, partner = (
        await onboarded(session),
        await onboarded(session),
        await onboarded(session),
    )
    token2 = await invite(client, other_inviter)
    await factories.create_partnership(session, other_inviter, partner)
    assert (await accept(client, newcomer, token2)).status_code == 409
    count = await session.scalar(
        select(func.count())
        .select_from(Partnership)
        .where(Partnership.status == PartnershipStatus.ACTIVE)
    )
    assert count == 2


async def test_accept_requires_onboarding(client: httpx.AsyncClient, session: AsyncSession) -> None:
    inviter = await onboarded(session)
    fresh = await factories.create_user(session, with_character=False)
    token = await invite(client, inviter)
    assert (await accept(client, fresh, token)).status_code == 409


async def test_invitation_of_a_deleted_inviter_is_404(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    inviter, me = await onboarded(session), await onboarded(session)
    token = await invite(client, inviter)
    inviter.deleted_at = clock.now()
    await session.flush()
    assert (await accept(client, me, token)).status_code == 404


async def test_invite_token_is_never_logged(
    client: httpx.AsyncClient, session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    inviter, me = await onboarded(session), await onboarded(session)
    token = await invite(client, inviter)
    await accept(client, me, token)
    await accept(client, me, token)
    assert token not in caplog.text
    assert hashlib.sha256(token.encode()).hexdigest() not in caplog.text


async def test_parallel_accepts_of_one_token_pair_exactly_once(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_sessions() as s:
        inviter = await onboarded(s)
        takers = [await onboarded(s) for _ in range(4)]
        await s.commit()
        inviter_id, taker_ids = inviter.id, [t.id for t in takers]
    async with independent_sessions() as s:
        created = await service.create_invitation(
            s, await s.get(User, inviter_id) or inviter, get_settings()
        )

    async def attempt(user_id: int) -> str:
        async with independent_sessions() as s:
            user = await s.get(User, user_id)
            assert user is not None
            try:
                await service.accept_invitation(s, user, created.token)
            except service.PartnershipError as exc:
                return type(exc).__name__
            return "ok"

    results = await asyncio.gather(*(attempt(uid) for uid in taker_ids))
    assert sorted(results).count("ok") == 1
    assert set(results) - {"ok"} <= {"InvitationUsedError", "AlreadyPartneredError"}
    async with independent_sessions() as s:
        assert await s.scalar(select(func.count()).select_from(Partnership)) == 1
        assert await s.scalar(select(func.count()).select_from(Wallet)) == 2


async def test_parallel_accepts_of_two_invitations_by_one_user(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_sessions() as s:
        inviters = [await onboarded(s) for _ in range(3)]
        me = await onboarded(s)
        await s.commit()
        inviter_ids, me_id = [u.id for u in inviters], me.id
    tokens = []
    for inviter_id in inviter_ids:
        async with independent_sessions() as s:
            user = await s.get(User, inviter_id)
            assert user is not None
            tokens.append((await service.create_invitation(s, user, get_settings())).token)

    async def attempt(token: str) -> str:
        async with independent_sessions() as s:
            user = await s.get(User, me_id)
            assert user is not None
            try:
                await service.accept_invitation(s, user, token)
            except service.AlreadyPartneredError:
                return "conflict"
            return "ok"

    results = sorted(await asyncio.gather(*(attempt(t) for t in tokens)))
    assert results == ["conflict", "conflict", "ok"]
    async with independent_sessions() as s:
        active = await s.scalar(
            select(func.count())
            .select_from(Partnership)
            .where(Partnership.status == PartnershipStatus.ACTIVE)
        )
        assert active == 1


# --- leave -----------------------------------------------------------------------------------


async def test_leave_rejects_wrong_confirmation_and_unpaired(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a, b = await onboarded(session), await onboarded(session)
    partnership = await factories.create_partnership(session, a, b)
    for text in ("leave", "", "LEAVE NOW", "DELETE"):
        assert (await leave(client, a, text)).status_code == 400
    await session.refresh(partnership)
    assert partnership.status == PartnershipStatus.ACTIVE
    loner = await onboarded(session)
    assert (await leave(client, loner)).status_code == 403


async def _seed_shared_life(
    session: AsyncSession, a: User, b: User, partnership: Partnership
) -> dict[str, object]:
    wallet_a = await factories.create_wallet(session, a, partnership, balance=120)
    wallet_b = await factories.create_wallet(session, b, partnership, balance=30)
    templates = {
        status: await factories.create_quest_template(session, partnership, a, b, status=status)
        for status in QuestTemplateStatus
    }
    open_template = templates[QuestTemplateStatus.ACTIVE]
    occurrences = {}
    for i, status in enumerate(QuestOccurrenceStatus):
        occurrences[status] = await factories.create_quest_occurrence(
            session,
            open_template,
            status=status,
            scheduled_date=clock.now().date() - timedelta(days=i),
        )
    rewards = {
        status: await factories.create_reward(session, partnership, b, status=status)
        for status in RewardStatus
    }
    return {
        "wallets": (wallet_a, wallet_b),
        "templates": templates,
        "occurrences": occurrences,
        "rewards": rewards,
    }


async def test_leave_ends_everything_in_one_go(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a, b = await onboarded(session), await onboarded(session)
    partnership = await factories.create_partnership(session, a, b)
    seeded = await _seed_shared_life(session, a, b, partnership)

    response = await leave(client, a, " LEAVE ")
    assert response.status_code == 204, response.text

    await session.refresh(partnership)
    assert partnership.status == PartnershipStatus.ENDED
    assert partnership.ended_by == a.id and partnership.ended_at is not None

    templates: dict[QuestTemplateStatus, QuestTemplate] = seeded["templates"]  # type: ignore[assignment]
    for status, template in templates.items():
        await session.refresh(template)
        expected = (
            QuestTemplateStatus.CANCELLED if status in service.OPEN_TEMPLATE_STATUSES else status
        )
        assert template.status == expected, status
    occurrences: dict[QuestOccurrenceStatus, QuestOccurrence] = seeded["occurrences"]  # type: ignore[assignment]
    for occ_status, occurrence in occurrences.items():
        await session.refresh(occurrence)
        if occ_status in service.OPEN_OCCURRENCE_STATUSES:
            assert (occurrence.status, occurrence.cancelled_by) == (
                QuestOccurrenceStatus.CANCELLED,
                a.id,
            )
        else:
            assert occurrence.status == occ_status
    rewards: dict[RewardStatus, Reward] = seeded["rewards"]  # type: ignore[assignment]
    for reward in rewards.values():
        await session.refresh(reward)
        assert reward.status == RewardStatus.HIDDEN

    # Wallets are frozen (partnership ended), balances and ledger untouched.
    for wallet in seeded["wallets"]:  # type: ignore[attr-defined]
        await session.refresh(wallet)
        ledger = await session.scalar(
            select(func.sum(GoldTransaction.amount)).where(GoldTransaction.wallet_id == wallet.id)
        )
        assert wallet.balance == ledger
    assert [w.balance for w in seeded["wallets"]] == [120, 30]  # type: ignore[attr-defined]
    assert (await client.get("/api/character", headers=auth(a))).json()["gold"] == 0

    notes = (await session.scalars(select(Notification))).all()
    assert [(n.recipient_id, n.type) for n in notes] == [(b.id, "partnership_ended")]
    assert notes[0].payload == {"reason": "left"}

    for who in (a, b):
        state = (await client.get("/api/partnership", headers=auth(who))).json()
        assert state["partnership"] is None
        assert (
            await client.get("/api/partnership/companion", headers=auth(who))
        ).status_code == 403
    assert (await leave(client, b)).status_code == 403


async def test_leave_is_atomic(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = await onboarded(session), await onboarded(session)
    partnership = await factories.create_partnership(session, a, b)
    reward = await factories.create_reward(session, partnership, b)
    template = await factories.create_quest_template(session, partnership, a, b)
    await session.commit()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("notification insert failed")

    monkeypatch.setattr(service, "_notify", boom)
    with pytest.raises(RuntimeError):
        await service.leave(session, a, "LEAVE")
    await session.rollback()
    for row in (partnership, reward, template):
        await session.refresh(row)
    assert partnership.status == PartnershipStatus.ACTIVE
    assert reward.status == RewardStatus.ACTIVE
    assert template.status == QuestTemplateStatus.ACTIVE


# --- re-pair ---------------------------------------------------------------------------------


async def test_repair_reactivates_the_old_partnership(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a, b = await onboarded(session), await onboarded(session)
    partnership_id = await pair(client, a, b)
    partnership = await session.get(Partnership, partnership_id)
    assert partnership is not None
    wallet_ids = set(
        (
            await session.scalars(select(Wallet.id).where(Wallet.partnership_id == partnership_id))
        ).all()
    )
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == b.id))
    assert wallet is not None
    wallet.balance = 80
    session.add(
        GoldTransaction(
            wallet_id=wallet.id,
            user_id=b.id,
            partnership_id=partnership_id,
            type="adjustment",
            amount=80,
            idempotency_key="test:repair",
        )
    )
    unlimited = await factories.create_reward(session, partnership, a)
    empty = await factories.create_reward(session, partnership, a, quantity_limit=1)
    empty.quantity_remaining = 0
    withdrawn = await factories.create_reward(session, partnership, a, status=RewardStatus.HIDDEN)
    edited = await factories.create_reward(session, partnership, a)
    old_quest = await factories.create_quest_template(session, partnership, a, b)
    await session.flush()

    assert (await leave(client, b)).status_code == 204
    for reward in (unlimited, empty, withdrawn, edited):
        await session.refresh(reward)
    assert [r.hidden_by_partnership_end for r in (unlimited, empty, withdrawn, edited)] == [
        True,
        True,
        False,
        True,
    ]
    # The creator edits a leave-hidden reward while the partnership is ended: updated_at moves
    # past ended_at, which must not matter for restoring it.
    await session.refresh(partnership)
    ended_at = partnership.ended_at
    assert ended_at is not None
    edited.title = "Edited while ended"
    edited.updated_at = ended_at + timedelta(hours=1)
    await session.commit()

    second = await accept(client, a, await invite(client, b))
    assert second.status_code == 200, second.text
    assert second.json()["reactivated"] is True
    assert second.json()["partnership"]["id"] == partnership_id

    assert await session.scalar(select(func.count()).select_from(Partnership)) == 1
    await session.refresh(partnership)
    assert partnership.status == PartnershipStatus.ACTIVE
    assert (partnership.ended_at, partnership.ended_by) == (None, None)
    assert set((await session.scalars(select(Wallet.id))).all()) == wallet_ids
    await session.refresh(wallet)
    assert wallet.balance == 80
    assert (await client.get("/api/character", headers=auth(b))).json()["gold"] == 80
    await session.refresh(unlimited)
    await session.refresh(empty)
    assert (unlimited.status, empty.status) == (RewardStatus.ACTIVE, RewardStatus.SOLD_OUT)
    await session.refresh(edited)
    assert (edited.status, edited.title) == (RewardStatus.ACTIVE, "Edited while ended")
    await session.refresh(withdrawn)
    assert withdrawn.status == RewardStatus.HIDDEN  # hidden by its creator before the leave
    for reward in (unlimited, empty, withdrawn, edited):
        assert reward.hidden_by_partnership_end is False
    await session.refresh(old_quest)
    assert old_quest.status == QuestTemplateStatus.CANCELLED  # history stays history


# --- companion -------------------------------------------------------------------------------


async def test_companion_profile(client: httpx.AsyncClient, session: AsyncSession) -> None:
    me, companion = await onboarded(session), await onboarded(session, display_name="Bo")
    assert (await client.get("/api/partnership/companion", headers=auth(me))).status_code == 403
    await factories.create_partnership(session, me, companion)
    session.add_all(
        [
            DevelopmentGoal(user_id=companion.id, title="Run"),
            DevelopmentGoal(user_id=companion.id, title="Old", status=GoalStatus.ARCHIVED),
            DevelopmentGoal(user_id=me.id, title="Mine"),
            WishlistItem(user_id=companion.id, title="Cake"),
            WishlistItem(user_id=companion.id, title="Gone", status=WishlistStatus.ARCHIVED),
        ]
    )
    await session.flush()
    response = await client.get("/api/partnership/companion", headers=auth(me))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["card"]["user_id"] == companion.id
    assert body["card"]["display_name"] == "Bo"
    assert len(body["attributes"]) == 6
    assert [g["title"] for g in body["goals"]] == ["Run"]
    assert [w["title"] for w in body["wishlist"]] == ["Cake"]
    assert "tg_user_id" not in response.text
