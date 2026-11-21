import pytest
from pydantic import ValidationError

from app.core.config import DEV_JWT_SECRET, Settings
from app.modules.common.enums import Difficulty

STRONG = "x" * 48


def test_defaults_are_dev_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    s = Settings()
    assert s.app_env == "development"
    assert s.jwt_secret == DEV_JWT_SECRET
    assert s.db_pool_size == 10
    assert s.difficulty_xp == {
        Difficulty.EASY: 20,
        Difficulty.NORMAL: 50,
        Difficulty.HARD: 100,
        Difficulty.EPIC: 250,
    }


@pytest.mark.parametrize("secret", [None, DEV_JWT_SECRET, "short-secret"])
def test_prod_refuses_default_or_weak_jwt_secret(
    monkeypatch: pytest.MonkeyPatch, secret: str | None
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    if secret is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings()


def test_prod_accepts_strong_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", STRONG)
    assert Settings().jwt_secret == STRONG


def test_non_prod_allows_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    assert Settings().jwt_secret == DEV_JWT_SECRET


def test_unknown_app_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValidationError):
        Settings()


def test_difficulty_xp_must_cover_every_difficulty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIFFICULTY_XP", '{"easy": 20}')
    with pytest.raises(ValidationError, match="difficulty_xp"):
        Settings()
