"""Stats and Life Balance reads plus my Life Balance targets (ARCHITECTURE §5 "stats").

Periods are local calendar days in the owner's timezone, today included: ``7d`` covers today
and the 6 days before it, ``30d`` the last 30 days. ``all`` counts everything; its daily series
starts at the first activity but never more than ``ALL_SERIES_DAYS`` days back.

Sources: ``xp_transaction`` (one row per completed quest: completions and XP), the Gold ledger
(earned = quest rewards, spent = purchases minus refunds), ``reward_purchase`` (bought and
fulfilled vouchers as the buyer) and ``character.total_xp``.
"""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Date, case, cast, func, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core import clock
from app.modules.common.enums import Attribute, GoldTransactionType, RewardPurchaseStatus
from app.modules.economy.models import GoldTransaction
from app.modules.progression.models import XpTransaction
from app.modules.rewards.models import RewardPurchase
from app.modules.stats import life_balance as lb
from app.modules.stats.models import LifeBalanceTarget
from app.modules.users.models import Character, User
from app.modules.users.service import active_gold

Period = Literal["7d", "30d", "all"]
BalancePeriod = Literal["7d", "30d"]
PERIOD_DAYS: dict[str, int | None] = {"7d": 7, "30d": 30, "all": None}
ALL_SERIES_DAYS = 90


class DayValue(BaseModel):
    date: date
    value: int


class StatsOut(BaseModel):
    period: Period
    #: First local day of the period (the series start for ``all``).
    since: date
    quests_completed: int
    quests_completed_total: int
    quests_completed_week: int
    quests_completed_month: int
    xp_total: int
    xp_period: int
    gold_earned: int
    gold_spent: int
    gold_earned_total: int
    gold_spent_total: int
    gold_balance: int
    rewards_purchased: int
    rewards_fulfilled: int
    xp_per_day: list[DayValue]
    quests_per_day: list[DayValue]


class AttributeScoreOut(BaseModel):
    attribute: Attribute
    earned_xp: int
    weekly_target: int
    period_target: int
    score: int


class SuggestionOut(BaseModel):
    attribute: Attribute
    reason: lb.SuggestionReason
    score: int


class LifeBalanceOut(BaseModel):
    period: BalancePeriod
    user: Literal["me", "companion"]
    attributes: list[AttributeScoreOut]
    suggestions: list[SuggestionOut]
    #: No attribute is below the suggestion threshold.
    balanced: bool


WeeklyTarget = Annotated[int, Field(ge=0, le=lb.MAX_WEEKLY_TARGET)]


class TargetsIn(BaseModel):
    """Weekly XP targets to set; attributes left out keep their current target."""

    targets: Annotated[dict[Attribute, WeeklyTarget], Field(min_length=1)]


class TargetsOut(BaseModel):
    targets: dict[Attribute, int]


def zone_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_today(now: datetime, zone: ZoneInfo) -> date:
    return now.astimezone(zone).date()


def day_start(day: date, zone: ZoneInfo) -> datetime:
    """The UTC instant of local midnight starting ``day``."""
    return datetime.combine(day, time(0), tzinfo=zone).astimezone(ZoneInfo("UTC"))


def window_start(now: datetime, zone: ZoneInfo, days: int) -> datetime:
    """Start of the last ``days`` local calendar days (today included)."""
    return day_start(local_today(now, zone) - timedelta(days=days - 1), zone)


def _fill(start: date, end: date, values: dict[date, int]) -> list[DayValue]:
    out: list[DayValue] = []
    day = start
    while day <= end:
        out.append(DayValue(date=day, value=values.get(day, 0)))
        day += timedelta(days=1)
    return out


async def stats(session: AsyncSession, user: User, period: Period) -> StatsOut:
    now = clock.now()
    zone = zone_of(user.timezone)
    today = local_today(now, zone)
    days = PERIOD_DAYS[period]
    week_start = window_start(now, zone, 7)
    month_start = window_start(now, zone, 30)
    since_at = window_start(now, zone, days) if days is not None else None

    def in_period(
        column: InstrumentedAttribute[datetime] | InstrumentedAttribute[datetime | None],
    ) -> ColumnElement[bool]:
        return true() if since_at is None else column >= since_at

    xp = XpTransaction
    totals = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(xp.created_at >= week_start),
                func.count().filter(xp.created_at >= month_start),
                func.count().filter(in_period(xp.created_at)),
                func.coalesce(func.sum(xp.xp).filter(in_period(xp.created_at)), 0),
            ).where(xp.user_id == user.id)
        )
    ).one()
    total, week, month, completed, xp_period = (int(v) for v in totals)

    gt = GoldTransaction

    def gold_sum(kind: GoldTransactionType, period_only: bool) -> ColumnElement[int]:
        cond: ColumnElement[bool] = gt.type == kind
        if period_only and since_at is not None:
            cond = cond & (gt.created_at >= since_at)
        return func.coalesce(func.sum(case((cond, gt.amount), else_=0)), 0)

    gold = (
        await session.execute(
            select(
                gold_sum(GoldTransactionType.QUEST_REWARD, True),
                gold_sum(GoldTransactionType.REWARD_PURCHASE, True),
                gold_sum(GoldTransactionType.REWARD_REFUND, True),
                gold_sum(GoldTransactionType.QUEST_REWARD, False),
                gold_sum(GoldTransactionType.REWARD_PURCHASE, False),
                gold_sum(GoldTransactionType.REWARD_REFUND, False),
            ).where(gt.user_id == user.id)
        )
    ).one()
    earned, bought, refunded, earned_total, bought_total, refunded_total = (int(v) for v in gold)

    rp = RewardPurchase
    rewards = (
        await session.execute(
            select(
                func.count().filter(
                    rp.status != RewardPurchaseStatus.REFUNDED,
                    in_period(rp.purchased_at),
                ),
                func.count().filter(
                    rp.status == RewardPurchaseStatus.FULFILLED,
                    in_period(rp.fulfilled_at),
                ),
            ).where(rp.buyer_id == user.id)
        )
    ).one()

    local_day = cast(func.timezone(zone.key, xp.created_at), Date)
    if days is not None:
        series_start = today - timedelta(days=days - 1)
    else:
        first = await session.scalar(select(func.min(local_day)).where(xp.user_id == user.id))
        floor = today - timedelta(days=ALL_SERIES_DAYS - 1)
        series_start = max(first, floor) if first is not None else today
    rows = (
        await session.execute(
            select(local_day, func.sum(xp.xp), func.count())
            .where(xp.user_id == user.id, xp.created_at >= day_start(series_start, zone))
            .group_by(local_day)
        )
    ).all()
    xp_by_day = {d: int(s) for d, s, _ in rows}
    quests_by_day = {d: int(c) for d, _, c in rows}

    total_xp = await session.scalar(select(Character.total_xp).where(Character.user_id == user.id))
    return StatsOut(
        period=period,
        since=series_start,
        quests_completed=completed,
        quests_completed_total=total,
        quests_completed_week=week,
        quests_completed_month=month,
        xp_total=int(total_xp or 0),
        xp_period=xp_period,
        gold_earned=earned,
        gold_spent=max(0, -bought - refunded),
        gold_earned_total=earned_total,
        gold_spent_total=max(0, -bought_total - refunded_total),
        gold_balance=await active_gold(session, user.id),
        rewards_purchased=int(rewards[0]),
        rewards_fulfilled=int(rewards[1]),
        xp_per_day=_fill(series_start, today, xp_by_day),
        quests_per_day=_fill(series_start, today, quests_by_day),
    )


async def weekly_targets(session: AsyncSession, user_id: int) -> dict[Attribute, int]:
    """Every attribute's weekly target (the default where no row exists)."""
    rows = (
        await session.execute(
            select(LifeBalanceTarget.attribute, LifeBalanceTarget.weekly_xp_target).where(
                LifeBalanceTarget.user_id == user_id
            )
        )
    ).all()
    stored = {attribute: int(target) for attribute, target in rows}
    return {a: stored.get(a, lb.DEFAULT_WEEKLY_TARGET) for a in lb.ATTRIBUTE_ORDER}


async def life_balance(
    session: AsyncSession, owner: User, period: BalancePeriod, who: Literal["me", "companion"]
) -> LifeBalanceOut:
    """``owner``'s recent attribute XP against their targets, in the owner's timezone."""
    days = lb.PERIOD_DAYS[period]
    start = window_start(clock.now(), zone_of(owner.timezone), days)
    rows = (
        await session.execute(
            select(XpTransaction.attribute, func.sum(XpTransaction.attribute_xp))
            .where(XpTransaction.user_id == owner.id, XpTransaction.created_at >= start)
            .group_by(XpTransaction.attribute)
        )
    ).all()
    earned = {attribute: int(total) for attribute, total in rows}
    items = lb.scores(earned, await weekly_targets(session, owner.id), days)
    tips = lb.suggestions(items)
    return LifeBalanceOut(
        period=period,
        user=who,
        attributes=[
            AttributeScoreOut(
                attribute=s.attribute,
                earned_xp=s.earned_xp,
                weekly_target=s.weekly_target,
                period_target=s.period_target,
                score=s.score,
            )
            for s in items
        ],
        suggestions=[
            SuggestionOut(attribute=s.attribute, reason=s.reason, score=s.score) for s in tips
        ],
        balanced=not tips,
    )


async def set_targets(session: AsyncSession, user: User, body: TargetsIn) -> TargetsOut:
    """Upsert my own weekly targets (never anyone else's); commits."""
    stmt = insert(LifeBalanceTarget).values(
        [
            {"user_id": user.id, "attribute": attribute, "weekly_xp_target": target}
            for attribute, target in body.targets.items()
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[LifeBalanceTarget.user_id, LifeBalanceTarget.attribute],
        set_={"weekly_xp_target": stmt.excluded.weekly_xp_target},
    )
    user_id = user.id
    await session.execute(stmt)
    await session.commit()
    return TargetsOut(targets=await weekly_targets(session, user_id))
