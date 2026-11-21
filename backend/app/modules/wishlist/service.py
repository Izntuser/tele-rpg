"""Reward wishlist.

Writes only ever touch rows whose ``user_id`` is the caller: an item id that belongs to
someone else is indistinguishable from a missing one (WishlistItemNotFoundError -> 404).
``offered`` and ``linked_reward_id`` are owned by the reward shop and never set here.
"""

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.common.enums import WishlistStatus
from app.modules.rewards.models import Reward
from app.modules.users.models import User
from app.modules.users.service import lock_user
from app.modules.wishlist.models import WishlistItem
from app.modules.wishlist.schemas import (
    MAX_WISHLIST_ITEMS,
    WishlistItemCreate,
    WishlistItemUpdate,
)


class WishlistItemNotFoundError(Exception):
    pass


class WishlistLimitError(Exception):
    pass


class WishlistItemLinkedError(Exception):
    """The item is tied to a shop reward; it can be archived but not deleted or reopened."""


async def list_items(
    session: AsyncSession, owner_id: int, *, include_archived: bool
) -> list[WishlistItem]:
    query = select(WishlistItem).where(WishlistItem.user_id == owner_id)
    if not include_archived:
        query = query.where(WishlistItem.status != WishlistStatus.ARCHIVED)
    result = await session.scalars(query.order_by(WishlistItem.id))
    return list(result)


async def create_item(session: AsyncSession, user: User, data: WishlistItemCreate) -> WishlistItem:
    await lock_user(session, user.id)
    count = await session.scalar(
        select(func.count()).select_from(WishlistItem).where(WishlistItem.user_id == user.id)
    )
    if (count or 0) >= MAX_WISHLIST_ITEMS:
        raise WishlistLimitError
    item = WishlistItem(user_id=user.id, title=data.title, description=data.description)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def _own_item(session: AsyncSession, user: User, item_id: int) -> WishlistItem:
    item: WishlistItem | None = await session.scalar(
        select(WishlistItem)
        .where(WishlistItem.id == item_id, WishlistItem.user_id == user.id)
        .with_for_update()
    )
    if item is None:
        raise WishlistItemNotFoundError
    return item


async def _is_linked(session: AsyncSession, item: WishlistItem) -> bool:
    if item.linked_reward_id is not None or item.status == WishlistStatus.OFFERED:
        return True
    referenced = await session.scalar(
        select(exists().where(Reward.source_wishlist_item_id == item.id))
    )
    return bool(referenced)


async def update_item(
    session: AsyncSession, user: User, item_id: int, data: WishlistItemUpdate
) -> WishlistItem:
    item = await _own_item(session, user, item_id)
    sent = data.model_fields_set
    if "title" in sent and data.title is not None:
        item.title = data.title
    if "description" in sent:
        item.description = data.description
    if "status" in sent and data.status is not None:
        target = WishlistStatus(data.status)
        if target == WishlistStatus.OPEN and item.status != WishlistStatus.OPEN:
            # Re-opening an item the shop turned into a reward would desync the two.
            if await _is_linked(session, item):
                raise WishlistItemLinkedError
        item.status = target
    await session.commit()
    return item


async def delete_item(session: AsyncSession, user: User, item_id: int) -> None:
    item = await _own_item(session, user, item_id)
    if await _is_linked(session, item):
        raise WishlistItemLinkedError
    await session.delete(item)
    await session.commit()
