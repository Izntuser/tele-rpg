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


@pytest.fixture(autouse=True)
def _clean_railway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in [k for k in os.environ if k.startswith("RAILWAY_")]:
        monkeypatch.delenv(k)


def test_volume_path_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    check_storage_volume(str(tmp_path))


def test_volume_path_differs_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sub = tmp_path / "files"
    sub.mkdir()
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    with pytest.raises(StorageVolumeError) as exc:
        check_storage_volume(str(sub))
    assert str(tmp_path) in str(exc.value)
    assert str(sub) in str(exc.value)


def test_on_railway_without_volume_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    with pytest.raises(StorageVolumeError, match="no Railway volume attached"):
        check_storage_volume(str(tmp_path))


def test_not_on_railway_plain_dir_only_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        check_storage_volume(str(tmp_path))
    assert "not a mount point" in caplog.text


def test_ephemeral_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    check_storage_volume(str(tmp_path), allow_ephemeral=True)
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/elsewhere")
    check_storage_volume(str(tmp_path), allow_ephemeral=True)


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
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
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
