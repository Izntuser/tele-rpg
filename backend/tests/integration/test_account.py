from datetime import timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, ratelimit
from app.core.config import get_settings
from app.modules.auth.jwt import encode_token
from app.modules.common.enums import (
    GoldTransactionType,
    JournalVisibility,
    PartnershipStatus,
    QuestOccurrenceStatus,
    RewardStatus,
    SubmissionReviewStatus,
)
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.goals.models import DevelopmentGoal
from app.modules.journal.models import JournalEvent
from app.modules.notifications.models import Notification
from app.modules.partnerships.models import Partnership, PartnershipInvitation
from app.modules.quests.models import QuestOccurrence, QuestSubmission
from app.modules.rewards.models import Reward
from app.modules.users.models import Character, User
from app.modules.wishlist.models import WishlistItem
from tests import factories
from tests.telegram_sign import make_init_data


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


def auth(user: User) -> dict[str, str]:
    token = encode_token(user.id, get_settings().jwt_secret.get_secret_value(), timedelta(hours=1))
    return {"Authorization": f"Bearer {token}"}


async def delete(client: httpx.AsyncClient, user: User, text: str = "DELETE") -> httpx.Response:
    return await client.request(
        "DELETE", "/api/account", headers=auth(user), json={"confirm_text": text}
    )


async def onboarded(session: AsyncSession, **kw: Any) -> User:
    return await factories.create_user(session, onboarded_at=clock.now(), **kw)


async def _seed(session: AsyncSession) -> dict[str, object]:
    """Me (with nickname, bio, goals, wishes, a quest submission) paired with a companion who
    has their own data and gold earned from my quests."""
    me = await onboarded(session, display_name="Real Name", tg_user_id=5_550_001)
    companion = await onboarded(session, display_name="Companion")
    character = await session.scalar(select(Character).where(Character.user_id == me.id))
    assert character is not None
    character.nickname, character.bio = "Nick", "My secret bio"
    partnership = await factories.create_partnership(session, me, companion)
    my_wallet = await factories.create_wallet(session, me, partnership, balance=70)
    their_wallet = await factories.create_wallet(session, companion, partnership, balance=150)
    session.add_all(
        [
            DevelopmentGoal(user_id=me.id, title="My goal"),
            WishlistItem(user_id=me.id, title="My wish"),
            DevelopmentGoal(user_id=companion.id, title="Their goal"),
            WishlistItem(user_id=companion.id, title="Their wish"),
            JournalEvent(
                user_id=me.id,
                type="note",
                visibility=JournalVisibility.PRIVATE,
                payload={"text": "private"},
            ),
            JournalEvent(
                user_id=me.id,
                partnership_id=partnership.id,
                type="quest_completed",
                visibility=JournalVisibility.SHARED,
                payload={"title": "Shared"},
            ),
        ]
    )
    # A quest I did for my companion, and one they did for me (with my redo review).
    mine = await factories.create_quest_template(session, partnership, companion, me)
    my_occ = await factories.create_quest_occurrence(
        session, mine, status=QuestOccurrenceStatus.IN_REVIEW
    )
    theirs = await factories.create_quest_template(session, partnership, me, companion)
    their_occ = await factories.create_quest_occurrence(
        session, theirs, status=QuestOccurrenceStatus.COMPLETED
    )
    my_submission = QuestSubmission(
        occurrence_id=my_occ.id, submitted_by=me.id, comment="I did it at the park"
    )
    their_submission = QuestSubmission(
        occurrence_id=their_occ.id,
        submitted_by=companion.id,
        comment="Their comment",
        review_status=SubmissionReviewStatus.REDO,
        review_comment="My critique",
    )
    session.add_all([my_submission, their_submission])
    reward = await factories.create_reward(session, partnership, companion)
    session.add(
        GoldTransaction(
            wallet_id=their_wallet.id,
            user_id=companion.id,
            partnership_id=partnership.id,
            type=GoldTransactionType.QUEST_REWARD,
            amount=0,
            quest_occurrence_id=their_occ.id,
            idempotency_key=f"quest:{their_occ.id}",
        )
    )
    await session.flush()
    return {
        "me": me,
        "companion": companion,
        "partnership": partnership,
        "wallets": (my_wallet, their_wallet),
        "my_submission": my_submission,
        "their_submission": their_submission,
        "my_occurrence": my_occ,
        "reward": reward,
    }


# --- export ----------------------------------------------------------------------------------


async def test_export_contains_my_data_only(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    seeded = await _seed(session)
    me: User = seeded["me"]  # type: ignore[assignment]
    session.add(
        PartnershipInvitation(
            creator_id=me.id, token_hash="f" * 64, expires_at=clock.now() + timedelta(days=1)
        )
    )
    await session.flush()
    response = await client.get("/api/account/export", headers=auth(me))
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    data = response.json()
    assert data["user"]["display_name"] == "Real Name"
    assert data["character"]["bio"] == "My secret bio"
    assert len(data["character_attributes"]) == 6
    assert [g["title"] for g in data["development_goals"]] == ["My goal"]
    assert [w["title"] for w in data["wishlist"]] == ["My wish"]
    assert len(data["partnerships"]) == 1
    assert [w["balance"] for w in data["wallets"]] == [70]
    assert sum(t["amount"] for t in data["gold_transactions"]) == 70
    assert len(data["quest_templates"]) == 2
    assert [s["comment"] for s in data["quest_submissions"]] == ["I did it at the park"]
    assert len(data["journal_events"]) == 2
    assert len(data["invitations"]) == 1
    assert "token_hash" not in data["invitations"][0]
    text = response.text
    assert "Their goal" not in text and "Their wish" not in text and "f" * 64 not in text


# --- delete ----------------------------------------------------------------------------------


async def test_delete_requires_the_exact_confirmation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await onboarded(session)
    for text in ("delete", "", "LEAVE", "DELETE ME"):
        assert (await delete(client, me, text)).status_code == 400
    missing = await client.request("DELETE", "/api/account", headers=auth(me), json={})
    assert missing.status_code == 422
    await session.refresh(me)
    assert me.deleted_at is None


async def test_delete_scrubs_pii_ends_partnership_and_keeps_the_ledger(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    seeded = await _seed(session)
    me: User = seeded["me"]  # type: ignore[assignment]
    companion: User = seeded["companion"]  # type: ignore[assignment]
    partnership: Partnership = seeded["partnership"]  # type: ignore[assignment]
    ledger_before = await session.scalar(select(func.count()).select_from(GoldTransaction))

    response = await delete(client, me, " DELETE ")
    assert response.status_code == 204, response.text

    await session.refresh(me)
    assert me.deleted_at is not None
    assert me.display_name == "Deleted user"
    assert (me.tg_username, me.avatar_url, me.avatar_file_id) == (None, None, None)
    assert me.tg_user_id == -me.id
    character = await session.scalar(select(Character).where(Character.user_id == me.id))
    assert character is not None
    await session.refresh(character)
    assert (character.name, character.nickname, character.bio) == ("Deleted user", None, None)

    assert (
        await session.scalar(
            select(func.count())
            .select_from(DevelopmentGoal)
            .where(DevelopmentGoal.user_id == me.id)
        )
        == 0
    )
    assert (
        await session.scalar(
            select(func.count()).select_from(WishlistItem).where(WishlistItem.user_id == me.id)
        )
        == 0
    )
    # The companion's own lists are untouched.
    assert await session.scalar(select(func.count()).select_from(DevelopmentGoal)) == 1
    assert await session.scalar(select(func.count()).select_from(WishlistItem)) == 1

    my_submission: QuestSubmission = seeded["my_submission"]  # type: ignore[assignment]
    their_submission: QuestSubmission = seeded["their_submission"]  # type: ignore[assignment]
    await session.refresh(my_submission)
    await session.refresh(their_submission)
    assert my_submission.comment is None
    assert their_submission.comment == "Their comment"
    assert their_submission.review_comment == "[deleted]"

    journal = (await session.scalars(select(JournalEvent))).all()
    assert [j.visibility for j in journal] == [JournalVisibility.SHARED]

    # The partnership ended with all of leave's side effects.
    await session.refresh(partnership)
    assert (partnership.status, partnership.ended_by) == (PartnershipStatus.ENDED, me.id)
    occurrence: QuestOccurrence = seeded["my_occurrence"]  # type: ignore[assignment]
    await session.refresh(occurrence)
    assert occurrence.status == QuestOccurrenceStatus.CANCELLED
    reward: Reward = seeded["reward"]  # type: ignore[assignment]
    await session.refresh(reward)
    assert reward.status == RewardStatus.HIDDEN
    notes = (await session.scalars(select(Notification))).all()
    assert [(n.recipient_id, n.type, n.payload) for n in notes] == [
        (companion.id, "partnership_ended", {"reason": "account_deleted"})
    ]

    # Ledger rows stay and every wallet still equals its ledger.
    assert await session.scalar(select(func.count()).select_from(GoldTransaction)) == ledger_before
    for wallet in (await session.scalars(select(Wallet))).all():
        await session.refresh(wallet)
        total = await session.scalar(
            select(func.coalesce(func.sum(GoldTransaction.amount), 0)).where(
                GoldTransaction.wallet_id == wallet.id
            )
        )
        assert wallet.balance == total
    assert {w.balance for w in (await session.scalars(select(Wallet))).all()} == {70, 150}


async def test_deleted_account_loses_access(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    seeded = await _seed(session)
    me: User = seeded["me"]  # type: ignore[assignment]
    companion: User = seeded["companion"]  # type: ignore[assignment]
    headers = auth(me)  # a JWT issued before the deletion
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
    assert (await delete(client, me)).status_code == 204

    for method, path in (
        ("GET", "/api/auth/me"),
        ("GET", "/api/character"),
        ("GET", "/api/account/export"),
        ("GET", "/api/goals"),
        ("POST", "/api/partnership/invitations"),
    ):
        assert (await client.request(method, path, headers=headers)).status_code == 401, path
    assert (await delete(client, me)).status_code == 401

    # The companion no longer sees me anywhere.
    state = (await client.get("/api/partnership", headers=auth(companion))).json()
    assert state["partnership"] is None
    for path in ("/api/goals", "/api/wishlist", "/api/partnership/companion"):
        response = await client.get(path, params={"user": "companion"}, headers=auth(companion))
        assert response.status_code == 403, path


async def test_relogin_after_deletion_starts_a_new_account(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    seeded = await _seed(session)
    me: User = seeded["me"]  # type: ignore[assignment]
    old_id = me.id
    assert (await delete(client, me)).status_code == 204

    raw = make_init_data(
        auth_date=frozen_clock.now(), user={"id": 5_550_001, "first_name": "Again"}
    )
    response = await client.post("/api/auth/telegram", json={"init_data": raw})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["id"] != old_id
    assert body["user"]["onboarded_at"] is None
    fresh = {"Authorization": f"Bearer {body['jwt']}"}
    assert (await client.get("/api/goals", headers=fresh)).json() == []
    assert (await client.get("/api/partnership", headers=fresh)).json()["partnership"] is None
    old = await session.get(User, old_id)
    assert old is not None
    await session.refresh(old)
    assert old.deleted_at is not None and old.tg_user_id == -old_id


async def test_delete_without_partnership_revokes_my_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me, other = await onboarded(session), await onboarded(session)
    created = await client.post("/api/partnership/invitations", headers=auth(me))
    token = created.json()["token"]
    assert (await delete(client, me)).status_code == 204
    accepted = await client.post(
        "/api/partnership/invitations/accept", headers=auth(other), json={"token": token}
    )
    assert accepted.status_code in (404, 410)
    assert await session.scalar(select(func.count()).select_from(Partnership)) == 0
