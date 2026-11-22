"""Files: upload a quest photo, stream a file to someone allowed to see it.

Uploads (here, ``/character/avatar`` and ``/rewards/{id}/image``) share ``read_image``:

1. the per-user upload bucket (5/min, on top of the 30/min write bucket) -> 429;
2. the body is read with a hard cap, before any multipart parsing spools it anywhere; a body
   (or the ``file`` part) above 10 MB -> 413, whatever ``Content-Length`` claims;
3. the bytes are identified by content, never by the client's ``Content-Type`` or file name:
   only JPEG / PNG / WebP / HEIC that Pillow decodes as that format pass, anything else -> 415;
4. the image is re-encoded from its pixels (EXIF incl. GPS stripped, ``storage.images``).

``GET /files/{id}`` needs the bearer token like every other route, so an ``<img src>`` URL is
useless on its own; the client fetches the bytes and shows a blob URL. Files are served with
``Cache-Control: private, no-store`` so a revoked partner keeps no copy in an HTTP cache.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.deps import CurrentUser, SessionDep, enforce
from app.core.ratelimit import upload_limiter
from app.modules.common.enums import FileKind
from app.modules.common.validation import IdPath
from app.modules.files import service
from app.modules.files.models import File
from app.modules.partnerships.service import find_active
from app.storage.base import StorageBackend, StoredFileNotFoundError, get_storage
from app.storage.images import (
    MAX_UPLOAD_BYTES,
    ImageTooLargeError,
    ProcessedImage,
    UnsupportedImageError,
    process_image,
)

router = APIRouter(tags=["files"])

StorageDep = Annotated[StorageBackend, Depends(get_storage)]

#: Room for the multipart boundaries and part headers around a 10 MB file.
MULTIPART_OVERHEAD = 64 * 1024
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD
FILE_FIELD = "file"
TOO_LARGE_DETAIL = "File too large (max 10 MB)"
UNSUPPORTED_DETAIL = "Unsupported file type (JPEG, PNG, WebP or HEIC only)"

#: OpenAPI for the hand-parsed multipart body (FastAPI would otherwise parse it before auth).
UPLOAD_OPENAPI: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": [FILE_FIELD],
                    "properties": {FILE_FIELD: {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}
UPLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"description": "Larger than 10 MB (or than 40 megapixels)"},
    415: {"description": "Not a JPEG, PNG, WebP or HEIC image (checked by content)"},
    429: {"description": "More than 5 uploads per minute"},
}


class FileOut(BaseModel):
    id: int
    kind: FileKind
    mime: str
    size: int


class _BodyTooLargeError(Exception):
    pass


def too_large() -> HTTPException:
    return HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE_DETAIL)


def unsupported() -> HTTPException:
    return HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, UNSUPPORTED_DETAIL)


def file_out(file: File) -> FileOut:
    return FileOut(id=file.id, kind=file.kind, mime=file.mime, size=file.size)


async def _capped(request: Request, limit: int) -> AsyncGenerator[bytes]:
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise _BodyTooLargeError
        yield chunk


async def _read_file_part(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise unsupported()
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise too_large()
    parser = MultiPartParser(
        request.headers,
        _capped(request, MAX_BODY_BYTES),
        max_files=1,
        max_fields=0,
        max_part_size=1024,
    )
    try:
        form = await parser.parse()
    except _BodyTooLargeError:
        raise too_large() from None
    except MultiPartException:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Malformed upload") from None
    try:
        part = form.get(FILE_FIELD)
        if not isinstance(part, UploadFile):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Missing '{FILE_FIELD}' part"
            )
        data = await part.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await form.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise too_large()
    return data


async def read_image(request: Request, user_id: int) -> ProcessedImage:
    """Rate-limit, read, validate and re-encode the ``file`` part of an upload request."""
    enforce(upload_limiter, f"user:{user_id}")
    data = await _read_file_part(request)
    try:
        return await asyncio.to_thread(process_image, data)
    except ImageTooLargeError:
        raise too_large() from None
    except UnsupportedImageError:
        raise unsupported() from None


def owner_gone() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


@router.post(
    "/files",
    response_model=FileOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=UPLOAD_OPENAPI,
    responses={**UPLOAD_RESPONSES, 409: {"description": "No active partnership"}},
)
async def upload_quest_photo(
    request: Request, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> FileOut:
    """Upload a quest photo (multipart field ``file``) for the active partnership; send its
    ``id`` as ``attachment_id`` to ``POST /quests/{id}/submit``."""
    image = await read_image(request, user.id)
    user_id = user.id
    try:
        await service.lock_live_owner(session, user_id)
    except service.OwnerGoneError:
        await session.rollback()
        raise owner_gone() from None
    partnership = await find_active(session, user_id)
    if partnership is None:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "No active partnership")
    file = await service.save_image(
        session,
        storage,
        owner_id=user_id,
        kind=FileKind.QUEST_PHOTO,
        partnership_id=partnership.id,
        image=image,
    )
    out = file_out(file)
    await service.commit_or_discard(session, storage, file)
    return out


@router.get(
    "/files/{file_id}",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"image/jpeg": {}, "image/webp": {}}, "description": "The image"},
        404: {"description": "No such file, or not mine / my active partner's"},
    },
)
async def read_file(
    file_id: IdPath, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> StreamingResponse:
    """Stream a file to its owner or the owner's active partner; 404 for anyone else."""
    file = await service.readable_file(session, user, file_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    try:
        chunks = storage.open(file.storage_key)
    except StoredFileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None
    return StreamingResponse(
        chunks,
        media_type=file.mime,
        headers={
            "Content-Length": str(file.size),
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )
