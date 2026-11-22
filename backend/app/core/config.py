from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.common.enums import Difficulty

_DB = "postgresql+asyncpg://telerpg:telerpg@localhost:5432"
DEV_JWT_SECRET = "dev-jwt-secret-change-me"
# Fixed fake token for dev/test/e2e (initData is signed with it in tests); never valid in prod.
DEV_TG_BOT_TOKEN = "123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"
MIN_PROD_JWT_SECRET_LEN = 32
MIN_PROD_WEBHOOK_SECRET_LEN = 32
HIDDEN_INPUT = "[hidden]"


def _translate_sslmode(raw: str) -> str:
    """Rewrite ``sslmode=X`` to ``ssl=X`` in the query (asyncpg has no ``sslmode`` kwarg).

    Other params and their order are kept. If ``ssl`` is also present it wins and ``sslmode``
    is dropped. Text before the ``?`` (including the password) is never touched.
    """
    base, sep, query = raw.partition("?")
    if not sep:
        return raw
    pairs = query.split("&")
    has_ssl = any(p.split("=", 1)[0] == "ssl" for p in pairs)
    out: list[str] = []
    for pair in pairs:
        key, eq, val = pair.partition("=")
        if key == "sslmode":
            if has_ssl:
                continue
            pair = f"ssl{eq}{val}"
        out.append(pair)
    return base + "?" + "&".join(out) if out else base


def normalize_database_url(value: Any) -> Any:
    """postgres(ql):// becomes postgresql+asyncpg:// and ``sslmode`` becomes ``ssl``.

    Anything else is unchanged. Alembic reads the URL from Settings, so it gets the same form.
    """
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    if not isinstance(raw, str):
        return value
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            raw = "postgresql+asyncpg://" + raw[len(prefix) :]
            break
    return _translate_sslmode(raw)


def _redact_validation_error(exc: ValidationError) -> ValidationError:
    """Copy of ``exc`` with every error's ``input`` replaced by HIDDEN_INPUT.

    ``hide_input_in_errors`` only scrubs ``str(exc)``; ``exc.errors()`` and ``exc.json()``
    still carry the raw input, which for model-level errors is the whole env dict (secrets).
    """
    known: list[InitErrorDetails] = []
    custom: list[InitErrorDetails] = []
    for err in exc.errors():
        loc = err["loc"]
        detail: InitErrorDetails = {"type": err["type"], "loc": loc, "input": HIDDEN_INPUT}
        if "ctx" in err:
            ctx = dict(err["ctx"])
            if isinstance(ctx.get("error"), BaseException):
                # A fresh exception carries no __traceback__ (whose frames could hold secrets).
                ctx["error"] = ValueError(str(ctx["error"]))
            detail["ctx"] = ctx
        known.append(detail)
        # Fallback when an error type is not a built-in one: keep type name and message.
        message = err["msg"].replace("{", "{{").replace("}", "}}")
        custom.append(
            {"type": PydanticCustomError(err["type"], message), "loc": loc, "input": HIDDEN_INPUT}
        )
    try:
        return ValidationError.from_exception_data(exc.title, known, hide_input=True)
    except (KeyError, TypeError, ValueError):
        return ValidationError.from_exception_data(exc.title, custom, hide_input=True)


class Settings(BaseSettings):
    """Process configuration from environment variables (names are upper-cased fields).

    Secrets (and DATABASE_URL, which embeds the DB password) are ``SecretStr`` so they never
    appear in ``repr``/logs; read them with ``.get_secret_value()``.
    """

    # hide_input_in_errors: a failed validation must not echo raw env input (secrets) in errors.
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "prod"] = "development"
    database_url: SecretStr = SecretStr(f"{_DB}/telerpg")
    #: Pooled engine of the api process only (the scheduler, healthz and migrations use NullPool).
    db_pool_size: int = Field(default=10, ge=1)
    #: Extra connections above db_pool_size under load; 10 is SQLAlchemy's own default.
    db_max_overflow: int = Field(default=10, ge=0)

    tg_bot_token: SecretStr = SecretStr(DEV_TG_BOT_TOKEN)
    tg_bot_username: str = ""
    tg_app_short_name: str = ""
    tg_webhook_secret: SecretStr = SecretStr("")

    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_ttl_seconds: int = Field(default=24 * 3600, gt=0)

    public_base_url: str = "http://localhost:3000"
    #: A volume mount in prod (the image sets STORAGE_DIR=/data/files).
    storage_dir: str = "./data/files"
    #: Uploads decoded at once per process (each decode can take ~100-200 MB).
    image_process_concurrency: int = Field(default=2, ge=1)
    sentry_dsn: str = ""
    frontend_dist: str = ""

    difficulty_xp: dict[Difficulty, int] = {
        Difficulty.EASY: 20,
        Difficulty.NORMAL: 50,
        Difficulty.HARD: 100,
        Difficulty.EPIC: 250,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        redacted: ValidationError | None = None
        try:
            super().__init__(*args, **kwargs)
        except ValidationError as exc:
            redacted = _redact_validation_error(exc)
        if redacted is not None:
            # Raised outside `except` so neither __cause__ nor __context__ keeps the raw input.
            raise redacted

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: Any) -> Any:
        """Railway and Supabase hand out postgres:// or postgresql://; the app needs asyncpg."""
        return normalize_database_url(value)

    @model_validator(mode="after")
    def _prod_guards(self) -> "Settings":
        if self.app_env == "prod":
            errors = []
            jwt = self.jwt_secret.get_secret_value()
            if jwt == DEV_JWT_SECRET or len(jwt) < MIN_PROD_JWT_SECRET_LEN:
                errors.append(
                    "JWT_SECRET must be set to a non-default value of at least "
                    f"{MIN_PROD_JWT_SECRET_LEN} characters"
                )
            token = self.tg_bot_token.get_secret_value()
            if not token or token == DEV_TG_BOT_TOKEN:
                # initData HMAC is keyed on the bot token: the public fake one allows forged logins.
                errors.append("TG_BOT_TOKEN must be set to the real bot token")
            if len(self.tg_webhook_secret.get_secret_value()) < MIN_PROD_WEBHOOK_SECRET_LEN:
                errors.append(
                    f"TG_WEBHOOK_SECRET must be at least {MIN_PROD_WEBHOOK_SECRET_LEN} characters"
                )
            # Invite links and notification buttons are t.me/<bot>/<app> links (DECISIONS 20).
            if not self.tg_bot_username:
                errors.append("TG_BOT_USERNAME must be set")
            if not self.tg_app_short_name:
                errors.append("TG_APP_SHORT_NAME must be set")
            if not self.public_base_url.startswith("https://"):
                errors.append("PUBLIC_BASE_URL must be an https:// URL (the webhook and Mini App)")
            if errors:
                raise ValueError("; ".join(errors) + " when APP_ENV=prod")
        if set(self.difficulty_xp) != set(Difficulty):
            raise ValueError("difficulty_xp must define every Difficulty")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
