"""My reward wishlist. Reads may target the active companion (``?user=companion``); writes
only ever act on the caller's own items (another user's id answers 404)."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.deps import CurrentUser, SessionDep
from app.modules.common.validation import IdPath
from app.modules.users.service import NotPartneredError, resolve_owner
from app.modules.wishlist import service
from app.modules.wishlist.schemas import WishlistItemCreate, WishlistItemOut, WishlistItemUpdate

router = APIRouter(prefix="/wishlist", tags=["wishlist"])

Who = Annotated[Literal["me", "companion"], Query(alias="user")]


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Wishlist item not found")


def _linked() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "Item is linked to a shop reward; archive it instead"
    )


@router.get("", response_model=list[WishlistItemOut])
async def list_items(
    user: CurrentUser, session: SessionDep, who: Who = "me"
) -> list[WishlistItemOut]:
    """My items (all statuses), or the active companion's non-archived items (403 when there
    is no active partnership)."""
    try:
        owner_id = await resolve_owner(session, user, who)
    except NotPartneredError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No active partnership") from None
    items = await service.list_items(session, owner_id, include_archived=who == "me")
    return [WishlistItemOut.model_validate(i) for i in items]


@router.post("", response_model=WishlistItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    body: WishlistItemCreate, user: CurrentUser, session: SessionDep
) -> WishlistItemOut:
    try:
        item = await service.create_item(session, user, body)
    except service.WishlistLimitError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Too many wishlist items") from None
    return WishlistItemOut.model_validate(item)


@router.patch("/{item_id}", response_model=WishlistItemOut)
async def update_item(
    item_id: IdPath, body: WishlistItemUpdate, user: CurrentUser, session: SessionDep
) -> WishlistItemOut:
    try:
        item = await service.update_item(session, user, item_id, body)
    except service.WishlistItemNotFoundError:
        raise _not_found() from None
    except service.WishlistItemLinkedError:
        raise _linked() from None
    return WishlistItemOut.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: IdPath, user: CurrentUser, session: SessionDep) -> Response:
    try:
        await service.delete_item(session, user, item_id)
    except service.WishlistItemNotFoundError:
        raise _not_found() from None
    except service.WishlistItemLinkedError:
        raise _linked() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
