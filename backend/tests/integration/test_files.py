"""S12 files: LocalStorage (path safety, atomic put), upload sanitizing (type by content, size,
pixels, EXIF/GPS stripped, re-encode), the 5/min upload limit, read authorization (owner or
active partner only, 404 for everyone else incl. the former partner), avatar, reward image,
photo proof on a photo_required quest, and stored bytes removed on account deletion."""

import asyncio
import io
import threading
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import ExifTags, Image
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock, ratelimit
from app.core.config import get_settings
from app.db.session import get_session
from app.modules.common.enums import FileKind, PartnershipStatus
from app.modules.files import service as files_service
from app.modules.files.models import File
from app.modules.users.models import User
from app.storage import images
from app.storage.base import InvalidKeyError, StoredFileNotFoundError, get_storage, new_key
from app.storage.local import LocalStorage
from tests import factories
from tests.integration.completion_support import active_quest, auth, ident, pair


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "files")


@pytest.fixture
async def files_client(
    session: AsyncSession, storage: LocalStorage
) -> AsyncIterator[httpx.AsyncClient]:
    from app.main import create_app

    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        # Uploads roll the session back before reading the body (no connection held during
        # the read): release the test's SAVEPOINT first, as if its setup had been committed.
        await session.commit()
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_storage] = lambda: storage
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- image fixtures ---------------------------------------------------------------------------


def jpeg_with_gps(size: tuple[int, int] = (64, 32), orientation: int | None = None) -> bytes:
    image = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "SpyCam"
    exif[ExifTags.Base.DateTime] = "2026:01:01 10:00:00"
    if orientation is not None:
        exif[ExifTags.Base.Orientation] = orientation
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (50.0, 27.0, 1.5)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (30.0, 31.0, 2.5)
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif, comment=b"secret comment")
    data = out.getvalue()
    assert dict(Image.open(io.BytesIO(data)).getexif().get_ifd(ExifTags.IFD.GPSInfo))
    return data


def encoded(fmt: str, mode: str = "RGB", size: tuple[int, int] = (40, 30), **kw: Any) -> bytes:
    color: Any = (10, 120, 200, 128) if mode == "RGBA" else (10, 120, 200)
    if mode == "L":
        color = 0
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, fmt, **kw)
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


async def upload(
    client: httpx.AsyncClient,
    user: User | int,
    data: bytes,
    *,
    path: str = "/files",
    content_type: str = "image/jpeg",
    filename: str = "photo.jpg",
) -> httpx.Response:
    files = {"file": (filename, data, content_type)}
    return await client.post(f"/api{path}", headers=auth(user), files=files)


async def stored(session: AsyncSession, file_id: int) -> File:
    file = await session.scalar(
        select(File).where(File.id == file_id).execution_options(populate_existing=True)
    )
    assert file is not None
    return file


# --- LocalStorage -----------------------------------------------------------------------------


async def test_local_storage_round_trip(storage: LocalStorage) -> None:
    key = new_key(FileKind.QUEST_PHOTO, "jpg")
    assert not await storage.exists(key)
    await storage.put(key, b"abc" * 50_000)
    assert await storage.exists(key)
    chunks = [chunk async for chunk in storage.open(key)]
    assert b"".join(chunks) == b"abc" * 50_000
    assert len(chunks) > 1  # streamed in chunks
    # Atomic write: nothing but the final file in the directory.
    assert [p.name for p in storage.path_for(key).parent.iterdir()] == [key.split("/")[1]]
    await storage.delete(key)
    assert not await storage.exists(key)
    await storage.delete(key)  # missing is fine
    with pytest.raises(StoredFileNotFoundError):
        storage.open(key)


@pytest.mark.parametrize(
    "key",
    [
        "../secret.jpg",
        "/etc/passwd",
        "avatar/../../etc/passwd",
        "avatar/../quest_photo/" + "a" * 32 + ".jpg",
        "avatar\\..\\x.jpg",
        "avatar/" + "a" * 32 + ".jpg/..",
        "avatar/" + "A" * 32 + ".jpg",
        "other/" + "a" * 32 + ".jpg",
        "avatar/" + "a" * 32 + ".php",
        "avatar/" + "a" * 32 + ".jpg\x00",
        "",
    ],
)
async def test_local_storage_rejects_unsafe_keys(storage: LocalStorage, key: str) -> None:
    with pytest.raises(InvalidKeyError):
        await storage.put(key, b"x")
    with pytest.raises(InvalidKeyError):
        storage.open(key)
    with pytest.raises(InvalidKeyError):
        await storage.delete(key)
    with pytest.raises(InvalidKeyError):
        await storage.exists(key)


async def test_new_keys_are_random_and_typed() -> None:
    keys = {new_key(FileKind.AVATAR, "webp") for _ in range(50)}
    assert len(keys) == 50
    assert all(k.startswith("avatar/") and k.endswith(".webp") for k in keys)


# --- image processing -------------------------------------------------------------------------


def test_process_strips_exif_and_gps() -> None:
    result = images.process_image(jpeg_with_gps())
    out = opened(result.data)
    assert result.mime == "image/jpeg" and out.format == "JPEG"
    exif = out.getexif()
    assert not dict(exif)
    assert not dict(exif.get_ifd(ExifTags.IFD.GPSInfo))
    assert "comment" not in out.info and "exif" not in out.info
    assert b"SpyCam" not in result.data and b"secret comment" not in result.data


def test_process_applies_orientation_then_drops_it() -> None:
    result = images.process_image(jpeg_with_gps(size=(64, 32), orientation=6))
    assert opened(result.data).size == (32, 64)


def test_process_keeps_transparency_as_webp_and_scales_down() -> None:
    result = images.process_image(encoded("PNG", "RGBA", size=(3000, 1000)))
    out = opened(result.data)
    assert result.mime == "image/webp" and out.format == "WEBP"
    assert out.size == (images.MAX_SIDE, 683)


@pytest.mark.parametrize(
    ("data_fn", "expected"),
    [
        (lambda: encoded("PNG"), "image/jpeg"),
        (lambda: encoded("WEBP"), "image/jpeg"),
        (lambda: encoded("HEIF"), "image/jpeg"),
    ],
)
def test_process_accepts_png_webp_heic(data_fn: Any, expected: str) -> None:
    assert images.process_image(data_fn()).mime == expected


@pytest.mark.parametrize(
    "data",
    [
        encoded("GIF"),
        encoded("BMP"),
        encoded("TIFF"),
        b"%PDF-1.7\n" + b"0" * 100,
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        b"\xff\xd8\xff\xe0" + b"garbage" * 20,  # JPEG magic, not a JPEG
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 30,
        b"",
    ],
)
def test_process_rejects_other_content(data: bytes) -> None:
    with pytest.raises(images.UnsupportedImageError):
        images.process_image(data)


def test_process_rejects_pixel_bombs() -> None:
    bomb = encoded("PNG", "L", size=(8000, 6000), optimize=True)
    assert len(bomb) < images.MAX_UPLOAD_BYTES
    with pytest.raises(images.ImageTooLargeError):
        images.process_image(bomb)


def test_process_rejects_too_many_decoded_pixels() -> None:
    """Under the 40 MP header cap, but a PNG cannot be decoded scaled down: 25 MP is refused."""
    big = encoded("PNG", "L", size=(5000, 5000), optimize=True)
    with pytest.raises(images.ImageTooLargeError):
        images.process_image(big)


def test_process_decodes_large_jpeg_scaled_down() -> None:
    """A 30 MP JPEG is over MAX_DECODED_PIXELS at full size but is decoded via draft at 1/2."""
    data = encoded("JPEG", size=(7500, 4000), quality=30)
    assert 7500 * 4000 > images.MAX_DECODED_PIXELS
    result = images.process_image(data)
    assert (result.width, result.height) == (images.MAX_SIDE, 1092)
    assert result.mime == "image/jpeg"


async def test_image_processing_concurrency_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    limit = get_settings().image_process_concurrency
    assert limit == 2
    lock = threading.Lock()
    running = 0
    peak = 0

    def slow(data: bytes) -> images.ProcessedImage:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return images.ProcessedImage(data, "image/jpeg", "jpg", 1, 1)

    monkeypatch.setattr(images, "process_image", slow)
    results = await asyncio.gather(*(images.process_image_bounded(b"x") for _ in range(7)))
    assert len(results) == 7
    assert peak == limit


async def test_cancelled_processing_keeps_its_slot_until_the_thread_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking(data: bytes) -> images.ProcessedImage:
        started.set()
        release.wait(5)
        return images.ProcessedImage(data, "image/jpeg", "jpg", 1, 1)

    monkeypatch.setattr(images, "process_image", blocking)
    first = asyncio.create_task(images.process_image_bounded(b"a"))
    await asyncio.to_thread(started.wait, 5)
    first.cancel()
    await asyncio.sleep(0.05)
    assert not first.done()  # still waiting for its thread, slot held
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first


# --- POST /files ------------------------------------------------------------------------------


async def test_upload_quest_photo_reencodes_and_strips_gps(
    files_client: httpx.AsyncClient, session: AsyncSession, storage: LocalStorage
) -> None:
    gm, player, partnership = await pair(session)
    response = await upload(files_client, player, jpeg_with_gps())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "quest_photo" and body["mime"] == "image/jpeg"
    assert set(body) == {"id", "kind", "mime", "size"}  # never the storage key
    file = await stored(session, body["id"])
    assert file.owner_id == player.id and file.partnership_id == partnership.id
    on_disk = storage.path_for(file.storage_key).read_bytes()
    assert len(on_disk) == file.size == body["size"]
    assert not dict(opened(on_disk).getexif().get_ifd(ExifTags.IFD.GPSInfo))
    assert not dict(opened(on_disk).getexif())

    read = await files_client.get(f"/api/files/{body['id']}", headers=auth(player))
    assert read.status_code == 200
    assert read.content == on_disk
    assert read.headers["content-type"] == "image/jpeg"
    assert read.headers["cache-control"] == "private, no-store"
    assert read.headers["x-content-type-options"] == "nosniff"
    assert not dict(opened(read.content).getexif().get_ifd(ExifTags.IFD.GPSInfo))


async def test_upload_type_is_checked_by_content_not_header(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    _, player, _ = await pair(session)
    pdf = b"%PDF-1.7\n" + b"0" * 200
    assert (await upload(files_client, player, pdf, content_type="image/jpeg")).status_code == 415
    gif = encoded("GIF")
    assert (await upload(files_client, player, gif, content_type="image/png")).status_code == 415
    # A real PNG sent as text/plain is still a PNG.
    png = encoded("PNG")
    ok = await upload(files_client, player, png, content_type="text/plain", filename="a.txt")
    assert ok.status_code == 201
    assert await session.scalar(select(File.id).where(File.owner_id == player.id)) is not None


async def test_upload_needs_multipart_with_a_file_part(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    _, player, _ = await pair(session)
    raw = await files_client.post(
        "/api/files",
        headers={**auth(player), "Content-Type": "image/jpeg"},
        content=encoded("JPEG"),
    )
    assert raw.status_code == 415
    missing = await files_client.post(
        "/api/files", headers=auth(player), files={"other": ("a.jpg", encoded("JPEG"))}
    )
    assert missing.status_code == 422


async def test_oversize_upload_is_413(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    _, player, _ = await pair(session)
    just_over = b"\xff\xd8\xff" + b"\x00" * (images.MAX_UPLOAD_BYTES - 2)
    assert (await upload(files_client, player, just_over)).status_code == 413
    way_over = b"\xff\xd8\xff" + b"\x00" * (images.MAX_UPLOAD_BYTES + 200_000)
    assert (await upload(files_client, player, way_over)).status_code == 413
    bomb = encoded("PNG", "L", size=(8000, 6000), optimize=True)
    assert (await upload(files_client, player, bomb)).status_code == 413
    assert await session.scalar(select(File.id).where(File.owner_id == player.id)) is None


def multipart_chunks(data: bytes, chunk: int = 64 * 1024) -> list[bytes]:
    boundary = "s12boundary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        'filename="p.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
    ).encode()
    body = head + data + f"\r\n--{boundary}--\r\n".encode()
    return [body[i : i + chunk] for i in range(0, len(body), chunk)]


MULTIPART = "multipart/form-data; boundary=s12boundary"


async def test_streamed_body_without_content_length_is_capped(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    _, player, _ = await pair(session)
    chunks = multipart_chunks(b"\xff\xd8\xff" + b"\x00" * (images.MAX_UPLOAD_BYTES + 200_000))
    sent = 0

    async def stream() -> AsyncIterator[bytes]:
        nonlocal sent
        for c in chunks:
            sent += 1
            yield c

    response = await files_client.post(
        "/api/files", headers=auth(player, **{"Content-Type": MULTIPART}), content=stream()
    )
    assert response.status_code == 413
    assert "content-length" not in response.request.headers
    assert sent < len(chunks)  # reading stopped at the cap, the rest was never pulled


async def test_lying_content_length_is_capped(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    _, player, _ = await pair(session)
    body = b"".join(
        multipart_chunks(b"\xff\xd8\xff" + b"\x00" * (images.MAX_UPLOAD_BYTES + 200_000))
    )

    async def stream() -> AsyncIterator[bytes]:
        for i in range(0, len(body), 64 * 1024):
            yield body[i : i + 64 * 1024]

    headers = auth(player, **{"Content-Type": MULTIPART, "Content-Length": "1000"})
    response = await files_client.post("/api/files", headers=headers, content=stream())
    assert response.request.headers["content-length"] == "1000"
    assert response.status_code == 413
    assert await session.scalar(select(File.id).where(File.owner_id == ident(player))) is None


async def test_no_db_connection_is_held_while_the_body_is_read(
    independent_sessions: async_sessionmaker[AsyncSession], storage: LocalStorage
) -> None:
    """``current_user`` opens a transaction; the upload must end it before reading the body, so
    a slow client holds no pooled connection (idle in transaction) while it trickles bytes."""
    from app.main import create_app

    async with independent_sessions() as s:
        _, player, _ = await pair(s)
        player_id = player.id
        await s.commit()

    request_sessions: list[AsyncSession] = []

    async def _session() -> AsyncIterator[AsyncSession]:
        async with independent_sessions() as s:
            request_sessions.append(s)
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_storage] = lambda: storage

    async def idle_in_transaction() -> int:
        async with independent_sessions() as probe:
            n = await probe.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
                )
            )
            return int(n or 0)

    observed: list[tuple[bool, int]] = []
    chunks = multipart_chunks(jpeg_with_gps(), chunk=256)

    async def slow_body() -> AsyncIterator[bytes]:
        for i, c in enumerate(chunks):
            if i == 1:  # the route has started reading the body
                await asyncio.sleep(0.05)
                observed.append((request_sessions[0].in_transaction(), await idle_in_transaction()))
            yield c

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post(
            "/api/files",
            headers=auth(player_id, **{"Content-Type": MULTIPART}),
            content=slow_body(),
        )
    assert response.status_code == 201, response.text
    assert observed == [(False, 0)]
    async with independent_sessions() as s:
        file = await s.scalar(select(File).where(File.owner_id == player_id))
        assert file is not None and file.kind == FileKind.QUEST_PHOTO


async def test_sixth_upload_in_a_minute_is_429(
    files_client: httpx.AsyncClient, session: AsyncSession, frozen_clock: Any
) -> None:
    _, player, _ = await pair(session)
    for _ in range(3):
        assert (await upload(files_client, player, encoded("JPEG"))).status_code == 201
    assert (
        await upload(files_client, player, encoded("PNG"), path="/character/avatar")
    ).status_code == 201
    assert (await upload(files_client, player, encoded("JPEG"))).status_code == 201
    limited = await upload(files_client, player, encoded("JPEG"))
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    frozen_clock.advance(timedelta(seconds=13))
    assert (await upload(files_client, player, encoded("JPEG"))).status_code == 201


async def test_upload_needs_auth_and_a_partnership(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    anonymous = await files_client.post("/api/files", files={"file": ("a.jpg", encoded("JPEG"))})
    assert anonymous.status_code == 401
    loner = await factories.create_user(session, onboarded_at=clock.now())
    assert (await upload(files_client, loner, encoded("JPEG"))).status_code == 409


# --- GET /files/{id} authorization ------------------------------------------------------------


async def test_only_owner_and_active_partner_can_read(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    stranger = await factories.create_user(session, onboarded_at=clock.now())
    other_gm = await factories.create_user(session, onboarded_at=clock.now())
    await factories.create_partnership(session, stranger, other_gm)
    file_id = (await upload(files_client, player, encoded("JPEG"))).json()["id"]

    assert (
        await files_client.get(f"/api/files/{file_id}", headers=auth(player))
    ).status_code == 200
    assert (await files_client.get(f"/api/files/{file_id}", headers=auth(gm))).status_code == 200
    for outsider in (stranger, other_gm):
        response = await files_client.get(f"/api/files/{file_id}", headers=auth(outsider))
        assert response.status_code == 404
    missing = await files_client.get(f"/api/files/{file_id + 1000}", headers=auth(player))
    assert missing.status_code == 404
    assert (await files_client.get(f"/api/files/{file_id}")).status_code == 401


async def test_former_partner_loses_access_when_the_partnership_ends(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    photo_id = (await upload(files_client, player, encoded("JPEG"))).json()["id"]
    avatar_id = (
        await upload(files_client, player, encoded("JPEG"), path="/character/avatar")
    ).json()["id"]
    left = await files_client.post(
        "/api/partnership/leave", headers=auth(gm), json={"confirm_text": "LEAVE"}
    )
    assert left.status_code == 204, left.text
    for file_id in (photo_id, avatar_id):
        assert (
            await files_client.get(f"/api/files/{file_id}", headers=auth(gm))
        ).status_code == 404
        owner = await files_client.get(f"/api/files/{file_id}", headers=auth(player))
        assert owner.status_code == 200


async def test_new_partner_cannot_read_photos_of_an_old_partnership(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    photo_id = (await upload(files_client, player, encoded("JPEG"))).json()["id"]
    avatar_id = (
        await upload(files_client, player, encoded("JPEG"), path="/character/avatar")
    ).json()["id"]
    partnership.status = PartnershipStatus.ENDED
    partnership.ended_at = clock.now()
    newcomer = await factories.create_user(session, onboarded_at=clock.now())
    await factories.create_partnership(session, player, newcomer)
    await session.flush()
    old_photo = await files_client.get(f"/api/files/{photo_id}", headers=auth(newcomer))
    assert old_photo.status_code == 404
    # The avatar is not tied to a partnership: the current partner sees it.
    avatar = await files_client.get(f"/api/files/{avatar_id}", headers=auth(newcomer))
    assert avatar.status_code == 200


async def test_missing_bytes_are_404(
    files_client: httpx.AsyncClient, session: AsyncSession, storage: LocalStorage
) -> None:
    _, player, _ = await pair(session)
    file_id = (await upload(files_client, player, encoded("JPEG"))).json()["id"]
    await storage.delete((await stored(session, file_id)).storage_key)
    assert (
        await files_client.get(f"/api/files/{file_id}", headers=auth(player))
    ).status_code == 404


# --- avatar -----------------------------------------------------------------------------------


async def test_avatar_upload_before_onboarding_and_replace(
    files_client: httpx.AsyncClient, session: AsyncSession, storage: LocalStorage
) -> None:
    newbie = await factories.create_user(session, with_character=False)
    first = await upload(files_client, newbie, jpeg_with_gps(), path="/character/avatar")
    assert first.status_code == 201, first.text
    assert first.json()["kind"] == "avatar"
    first_key = (await stored(session, first.json()["id"])).storage_key
    me = await files_client.get("/api/auth/me", headers=auth(newbie))
    assert me.json()["user"]["avatar_file_id"] == first.json()["id"]

    second = await upload(files_client, newbie, encoded("PNG", "RGBA"), path="/character/avatar")
    assert second.status_code == 201
    assert second.json()["mime"] == "image/webp"
    assert await session.get(File, first.json()["id"]) is None
    assert not await storage.exists(first_key)
    user = await session.scalar(
        select(User).where(User.id == newbie.id).execution_options(populate_existing=True)
    )
    assert user is not None and user.avatar_file_id == second.json()["id"]


async def test_character_shows_avatar_to_me_and_partner(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    avatar_id = (
        await upload(files_client, player, encoded("JPEG"), path="/character/avatar")
    ).json()["id"]
    character = await files_client.get("/api/character", headers=auth(player))
    assert character.json()["avatar_file_id"] == avatar_id
    companion = await files_client.get("/api/partnership/companion", headers=auth(gm))
    assert companion.json()["card"]["avatar_file_id"] == avatar_id
    assert (await files_client.get(f"/api/files/{avatar_id}", headers=auth(gm))).status_code == 200


async def test_avatar_rejects_bad_content(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    _, player, _ = await pair(session)
    bad = await upload(files_client, player, b"GIF89a" + b"0" * 50, path="/character/avatar")
    assert bad.status_code == 415


# --- reward image -----------------------------------------------------------------------------


async def test_reward_image_creator_only_and_visible_to_partner(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm_user, player_user, partnership = await pair(session)
    partnership_id = partnership.id
    reward_id = (await factories.create_reward(session, partnership, gm_user)).id
    stranger = (await factories.create_user(session, onboarded_at=clock.now())).id
    gm, player = gm_user.id, player_user.id
    await session.commit()  # a 4xx rolls the session back to here
    path = f"/rewards/{reward_id}/image"

    assert (await upload(files_client, player, encoded("JPEG"), path=path)).status_code == 403
    assert (await upload(files_client, stranger, encoded("JPEG"), path=path)).status_code == 404
    response = await upload(files_client, gm, jpeg_with_gps(), path=path)
    assert response.status_code == 200, response.text
    image_id = response.json()["image_file_id"]
    assert image_id is not None
    file = await stored(session, image_id)
    assert file.kind == FileKind.REWARD_IMAGE and file.partnership_id == partnership_id

    shop = await files_client.get("/api/rewards", headers=auth(player))
    assert [r["image_file_id"] for r in shop.json()] == [image_id]
    image = await files_client.get(f"/api/files/{image_id}", headers=auth(player))
    assert image.status_code == 200
    assert not dict(opened(image.content).getexif())
    outsider = await files_client.get(f"/api/files/{image_id}", headers=auth(stranger))
    assert outsider.status_code == 404


async def test_reward_image_on_ended_partnership_is_409(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm_user, _, partnership = await pair(session)
    reward_id = (await factories.create_reward(session, partnership, gm_user)).id
    partnership.status = PartnershipStatus.ENDED
    partnership.ended_at = clock.now()
    await session.flush()
    gm = gm_user.id
    await session.commit()
    path = f"/rewards/{reward_id}/image"
    assert (await upload(files_client, gm, encoded("JPEG"), path=path)).status_code == 409
    assert await session.scalar(select(File.id).where(File.owner_id == gm)) is None


# --- photo proof ------------------------------------------------------------------------------


async def test_photo_required_quest_submitted_with_an_uploaded_photo(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm_user, player_user, _ = await pair(session)
    occurrence_id = await active_quest(session, gm_user, player_user, photo_required=True)
    gm, player = gm_user.id, player_user.id
    await session.commit()
    submit = f"/api/quests/{occurrence_id}/submit"
    without = await files_client.post(submit, headers=auth(player), json={"comment": "done"})
    assert without.status_code == 422

    photo_id = (await upload(files_client, player, jpeg_with_gps())).json()["id"]
    done = await files_client.post(
        submit, headers=auth(player), json={"comment": "done", "attachment_id": photo_id}
    )
    assert done.status_code == 200, done.text
    assert done.json()["submissions"][0]["attachment_id"] == photo_id

    detail = await files_client.get(f"/api/quests/{occurrence_id}", headers=auth(gm))
    assert detail.json()["submissions"][0]["attachment_id"] == photo_id
    photo = await files_client.get(f"/api/files/{photo_id}", headers=auth(gm))
    assert photo.status_code == 200
    assert not dict(opened(photo.content).getexif().get_ifd(ExifTags.IFD.GPSInfo))


async def test_gm_cannot_submit_their_own_upload_as_proof(
    files_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = await active_quest(session, gm, player, photo_required=True)
    gm_photo = (await upload(files_client, gm, encoded("JPEG"))).json()["id"]
    response = await files_client.post(
        f"/api/quests/{occurrence_id}/submit",
        headers=auth(player),
        json={"attachment_id": gm_photo},
    )
    assert response.status_code == 422


# --- account deletion -------------------------------------------------------------------------


async def test_account_deletion_removes_rows_and_bytes(
    files_client: httpx.AsyncClient, session: AsyncSession, storage: LocalStorage
) -> None:
    gm, player, partnership = await pair(session)
    reward = await factories.create_reward(session, partnership, gm)
    reward_id = reward.id
    gm_photo = (await upload(files_client, gm, encoded("JPEG"))).json()["id"]
    await upload(files_client, gm, encoded("JPEG"), path="/character/avatar")
    await upload(files_client, gm, encoded("JPEG"), path=f"/rewards/{reward_id}/image")
    player_photo = (await upload(files_client, player, encoded("JPEG"))).json()["id"]
    gm_keys = list(await session.scalars(select(File.storage_key).where(File.owner_id == gm.id)))
    assert len(gm_keys) == 3
    player_key = (await stored(session, player_photo)).storage_key

    deleted = await files_client.request(
        "DELETE", "/api/account", headers=auth(gm), json={"confirm_text": "DELETE"}
    )
    assert deleted.status_code == 204, deleted.text
    assert await session.scalar(select(File.id).where(File.owner_id == gm.id)) is None
    for key in gm_keys:
        assert not await storage.exists(key)
    assert await storage.exists(player_key)
    assert await session.get(File, gm_photo) is None
    # The companion keeps their own file (the partnership ended, so only they can read it).
    assert (
        await files_client.get(f"/api/files/{player_photo}", headers=auth(player))
    ).status_code == 200
    gone = await files_client.get(f"/api/files/{gm_photo}", headers=auth(player))
    assert gone.status_code == 404


async def test_upload_for_a_deleted_owner_is_refused(session: AsyncSession) -> None:
    """The owner row is locked and re-read under the lock: an account deleted while the upload
    was in flight gets no file row (account deletion locks the same row)."""
    user = await factories.create_user(session, deleted_at=clock.now())
    with pytest.raises(files_service.OwnerGoneError):
        await files_service.lock_live_owner(session, user.id)
