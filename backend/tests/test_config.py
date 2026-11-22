import pytest
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from app.core.config import (
    DEV_JWT_SECRET,
    DEV_TG_BOT_TOKEN,
    HIDDEN_INPUT,
    Settings,
    _redact_validation_error,
)
from app.modules.common.enums import Difficulty

STRONG = "x" * 48
REAL_TOKEN = "987654321:AAREALREALREALREALREALREALREALREALRE"
WEBHOOK_SECRET = "w" * 32


def prod_env(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    """APP_ENV=prod with every secret valid, then apply overrides (None = unset)."""
    values: dict[str, str | None] = {
        "APP_ENV": "prod",
        "JWT_SECRET": STRONG,
        "TG_BOT_TOKEN": REAL_TOKEN,
        "TG_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "TG_BOT_USERNAME": "telerpg_bot",
        "TG_APP_SHORT_NAME": "app",
        "PUBLIC_BASE_URL": "https://telerpg.example.com",
    }
    values.update(overrides)
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def test_defaults_are_dev_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "JWT_SECRET", "TG_BOT_TOKEN", "TG_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    s = Settings()
    assert s.app_env == "development"
    assert s.jwt_secret.get_secret_value() == DEV_JWT_SECRET
    assert s.tg_bot_token.get_secret_value() == DEV_TG_BOT_TOKEN
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
    prod_env(monkeypatch, JWT_SECRET=secret)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings()


@pytest.mark.parametrize("token", [None, DEV_TG_BOT_TOKEN, ""])
def test_prod_refuses_fake_or_missing_bot_token(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    prod_env(monkeypatch, TG_BOT_TOKEN=token)
    with pytest.raises(ValidationError, match="TG_BOT_TOKEN"):
        Settings()


@pytest.mark.parametrize("secret", [None, "", "w" * 31])
def test_prod_requires_long_webhook_secret(
    monkeypatch: pytest.MonkeyPatch, secret: str | None
) -> None:
    prod_env(monkeypatch, TG_WEBHOOK_SECRET=secret)
    with pytest.raises(ValidationError, match="TG_WEBHOOK_SECRET"):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TG_BOT_USERNAME", None),
        ("TG_BOT_USERNAME", ""),
        ("TG_APP_SHORT_NAME", None),
        ("TG_APP_SHORT_NAME", ""),
        ("PUBLIC_BASE_URL", "http://telerpg.example.com"),
        ("PUBLIC_BASE_URL", None),
    ],
)
def test_prod_requires_bot_and_app_names_and_https_base_url(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str | None
) -> None:
    prod_env(monkeypatch, **{name: value})
    with pytest.raises(ValidationError, match=name):
        Settings()


def test_prod_accepts_strong_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    prod_env(monkeypatch)
    s = Settings()
    assert s.jwt_secret.get_secret_value() == STRONG
    assert s.tg_bot_token.get_secret_value() == REAL_TOKEN
    assert s.tg_webhook_secret.get_secret_value() == WEBHOOK_SECRET


def test_non_prod_allows_default_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    for name in ("JWT_SECRET", "TG_BOT_TOKEN", "TG_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    s = Settings()
    assert s.jwt_secret.get_secret_value() == DEV_JWT_SECRET
    assert s.tg_bot_token.get_secret_value() == DEV_TG_BOT_TOKEN


def test_secrets_never_appear_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    db_password = "pg-pass-0f3c9a"
    db_url = f"postgresql+asyncpg://someone:{db_password}@db.internal:5432/telerpg"
    prod_env(monkeypatch, DATABASE_URL=db_url)
    s = Settings()
    rendered = repr(s) + str(s) + repr(s.model_dump())
    for value in (STRONG, REAL_TOKEN, WEBHOOK_SECRET, db_password, db_url):
        assert value not in rendered
    assert s.database_url.get_secret_value() == db_url


def test_unknown_app_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValidationError):
        Settings()


def test_difficulty_xp_must_cover_every_difficulty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIFFICULTY_XP", '{"easy": 20}')
    with pytest.raises(ValidationError, match="difficulty_xp"):
        Settings()


LEAK_JWT = "leak-jwt-secret-7d1e5b2c9a4f8e3d6b0a1c5f9e2d4b8a"
LEAK_TOKEN = "555000111:AALEAKLEAKLEAKLEAKLEAKLEAKLEAKLEAKLE"
LEAK_HOOK_LONG = "leak-webhook-secret-3a9f1c7e5b2d8f4a6c"
LEAK_HOOK_SHORT = "leak-hook-short-91"
LEAK_DB_PASSWORD = "pg-leak-pass-4e8b2f"
LEAK_DB_URL = f"postgresql+asyncpg://someone:{LEAK_DB_PASSWORD}@db.internal:5432/telerpg"


@pytest.mark.parametrize(
    "overrides",
    [
        # _prod_guards (model validator) fails: webhook secret too short.
        {"TG_WEBHOOK_SECRET": LEAK_HOOK_SHORT},
        # field validation fails while every secret is present in the input.
        {"DB_POOL_SIZE": "0"},
        {"JWT_TTL_SECONDS": "-1"},
        # difficulty_xp check (same model validator) fails.
        {"DIFFICULTY_XP": '{"easy": 20}'},
    ],
    ids=["prod-guard", "pool-size", "jwt-ttl", "difficulty-xp"],
)
def test_validation_errors_never_leak_secrets(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str]
) -> None:
    prod_env(
        monkeypatch,
        JWT_SECRET=LEAK_JWT,
        TG_BOT_TOKEN=LEAK_TOKEN,
        TG_WEBHOOK_SECRET=LEAK_HOOK_LONG,
        DATABASE_URL=LEAK_DB_URL,
    )
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    exc = excinfo.value
    assert exc.__cause__ is None and exc.__context__ is None
    assert exc.errors() and all(e["input"] == HIDDEN_INPUT for e in exc.errors())
    rendered = str(exc) + repr(exc) + repr(exc.errors()) + exc.json()
    for secret in (LEAK_JWT, LEAK_TOKEN, LEAK_HOOK_LONG, LEAK_HOOK_SHORT, LEAK_DB_PASSWORD):
        assert secret not in rendered


def test_redaction_falls_back_for_custom_error_types() -> None:
    original = ValidationError.from_exception_data(
        "Settings",
        [
            {
                "type": PydanticCustomError("my_check", "bad {thing}", {"thing": "x"}),
                "loc": ("jwt_secret",),
                "input": LEAK_JWT,
            }
        ],
    )
    redacted = _redact_validation_error(original)
    [err] = redacted.errors()
    assert err["type"] == "my_check"
    assert err["msg"] == "bad x"
    assert err["input"] == HIDDEN_INPUT
    assert LEAK_JWT not in str(redacted) + repr(redacted.errors()) + redacted.json()


def test_redacted_ctx_error_has_no_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    # The prod-guard ValueError's traceback would reference _prod_guards' locals (secrets).
    prod_env(monkeypatch, JWT_SECRET=LEAK_JWT, TG_WEBHOOK_SECRET=LEAK_HOOK_SHORT)
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    errors = excinfo.value.errors()
    ctx_errors = [e["ctx"]["error"] for e in errors if "error" in e.get("ctx", {})]
    assert ctx_errors
    for err in ctx_errors:
        assert type(err) is ValueError
        assert err.__traceback__ is None
        assert err.__cause__ is None and err.__context__ is None
        assert LEAK_JWT not in str(err) and LEAK_HOOK_SHORT not in str(err)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
        ("postgresql://u:p@h:5432/d?x=1", "postgresql+asyncpg://u:p@h:5432/d?x=1"),
        ("postgresql+asyncpg://u:p@h/d", "postgresql+asyncpg://u:p@h/d"),
    ],
)
def test_database_url_is_normalized_to_asyncpg(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", raw)
    assert Settings().database_url.get_secret_value() == expected


def test_prod_reports_every_missing_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scheduler builds the same Settings, so it passes (or fails) the same guards."""
    prod_env(monkeypatch, PUBLIC_BASE_URL="http://x", TG_BOT_USERNAME=None, TG_APP_SHORT_NAME=None)
    with pytest.raises(ValidationError) as exc:
        Settings()
    for needle in ("PUBLIC_BASE_URL", "TG_BOT_USERNAME", "TG_APP_SHORT_NAME"):
        assert needle in str(exc.value)
