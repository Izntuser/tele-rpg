"""Uploaded files: storing a sanitized image with its ``file`` row, and the read check.

Who may read a file (``readable_file``): its owner, or the owner's *active* partner, and for a
file tied to a partnership (quest photo, reward image) only within that same partnership.
Everyone else, the former partner included, gets the same answer as for a missing id (404),
so ids reveal nothing. Bytes are stored under a random key (``storage.base.new_key``); the
key never leaves the server.

Lock order: the owner's user row ``FOR NO KEY UPDATE`` first (``users.service.lock_user``),
so an upload serializes with account deletion (which locks the same row before scrubbing)
and can never leave a file behind for a deleted account; then whatever the caller locks
(partnership ``FOR SHARE`` -> reward for a reward image), as everywhere else (DECISIONS #16).
"""

import logging
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.common.enums import FileKind
from app.modules.files.models import File
from app.modules.partnerships.service import companion_of, find_active
from app.modules.users.models import User
from app.modules.users.service import lock_user
from app.storage.base import StorageBackend, new_key
from app.storage.images import ProcessedImage

log = logging.getLogger(__name__)


class OwnerGoneError(Exception):
    """The uploader's account was deleted while the upload was in flight."""


async def lock_live_owner(session: AsyncSession, user_id: int) -> User:
    """Lock the uploader's user row and re-read it; ``OwnerGoneError`` when deleted."""
    await lock_user(session, user_id)
    user = await session.scalar(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    if user is None or user.deleted_at is not None:
        raise OwnerGoneError
    return user


async def save_image(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    owner_id: int,
    kind: FileKind,
    partnership_id: int | None,
    image: ProcessedImage,
) -> File:
    """Write the bytes, then add (and flush) the ``file`` row. The caller holds the owner's
    lock (``lock_live_owner``) and commits through ``commit_or_discard``."""
    key = new_key(kind, image.extension)
    await storage.put(key, image.data)
    file = File(
        owner_id=owner_id,
        partnership_id=partnership_id,
        kind=kind,
        storage_key=key,
        mime=image.mime,
        size=len(image.data),
    )
    session.add(file)
    try:
        await session.flush()
    except BaseException:
        await discard(storage, [key])
        raise
    return file


async def commit_or_discard(session: AsyncSession, storage: StorageBackend, file: File) -> None:
    """Commit; if that fails, remove the bytes just written so nothing is orphaned."""
    key = file.storage_key
    try:
        await session.commit()
    except BaseException:
        await discard(storage, [key])
        raise


async def discard(storage: StorageBackend, keys: Iterable[str]) -> None:
    """Best-effort removal of stored bytes (after the rows are gone or were never committed)."""
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:  # pragma: no cover - logged, the row is already gone
            log.exception("could not delete stored file %s", key)


async def replace_avatar(
    session: AsyncSession, storage: StorageBackend, user_id: int, image: ProcessedImage
) -> File:
    """Store a new avatar, point ``user.avatar_file_id`` at it and drop the previous avatar
    (row now, bytes after the commit). Commits. Works before onboarding (no character)."""
    user = await lock_live_owner(session, user_id)
    previous_id = user.avatar_file_id
    file = await save_image(
        session, storage, owner_id=user_id, kind=FileKind.AVATAR, partnership_id=None, image=image
    )
    user.avatar_file_id = file.id
    stale: list[str] = []
    if previous_id is not None:
        previous = await session.get(File, previous_id)
        if previous is not None and previous.owner_id == user_id:
            await session.flush()  # user no longer points at it
            stale.append(previous.storage_key)
            await session.delete(previous)
    await commit_or_discard(session, storage, file)
    await discard(storage, stale)
    return file


async def readable_file(session: AsyncSession, viewer: User, file_id: int) -> File | None:
    """The file if ``viewer`` may read it (see the module docstring), else None."""
    file = await session.get(File, file_id)
    if file is None:
        return None
    if file.owner_id == viewer.id:
        return file
    partnership = await find_active(session, viewer.id)
    if partnership is None or companion_of(partnership, viewer.id) != file.owner_id:
        return None
    if file.partnership_id is not None and file.partnership_id != partnership.id:
        return None
    owner = await session.get(User, file.owner_id)
    if owner is None or owner.deleted_at is not None:
        return None
    return file
