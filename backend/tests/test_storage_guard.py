import os
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.main import lifespan
from app.storage.guard import StorageVolumeError, check_storage_volume


def test_missing_dir_fails(tmp_path: Path) -> None:
    with pytest.raises(StorageVolumeError, match="does not exist"):
        check_storage_volume(str(tmp_path / "nope"), allow_ephemeral=True)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_unwritable_dir_fails(tmp_path: Path) -> None:
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(StorageVolumeError, match="not writable"):
            check_storage_volume(str(tmp_path), allow_ephemeral=True)
    finally:
        tmp_path.chmod(0o700)


def test_plain_dir_fails_unless_ephemeral_allowed(tmp_path: Path) -> None:
    with pytest.raises(StorageVolumeError, match="not a mounted volume"):
        check_storage_volume(str(tmp_path))
    check_storage_volume(str(tmp_path), allow_ephemeral=True)


def test_mount_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os.path, "ismount", lambda p: p == str(tmp_path))
    check_storage_volume(str(tmp_path))


async def test_prod_lifespan_fails_fast_without_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:REALTOKENREALTOKENREALTOKENREAL")
    monkeypatch.setenv("JWT_SECRET", "j" * 40)
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "w" * 40)
    monkeypatch.setenv("TG_BOT_USERNAME", "bot")
    monkeypatch.setenv("TG_APP_SHORT_NAME", "app")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("STORAGE_ALLOW_EPHEMERAL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(StorageVolumeError):
            async with lifespan(FastAPI()):
                pass
    finally:
        get_settings.cache_clear()


async def test_non_prod_lifespan_ignores_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_DIR", "/definitely/not/here")
    get_settings.cache_clear()
    try:
        async with lifespan(FastAPI()):
            pass
    finally:
        get_settings.cache_clear()
