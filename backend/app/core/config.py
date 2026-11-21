from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.common.enums import Difficulty

_DB = "postgresql+asyncpg://telerpg:telerpg@localhost:5432"
DEV_JWT_SECRET = "dev-jwt-secret-change-me"
# Fixed fake token for dev/test/e2e (initData is signed with it in tests); never valid in prod.
DEV_TG_BOT_TOKEN = "123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"
MIN_PROD_JWT_SECRET_LEN = 32
MIN_PROD_WEBHOOK_SECRET_LEN = 32


class Settings(BaseSettings):
    """Process configuration from environment variables (names are upper-cased fields).

    Secrets (and DATABASE_URL, which embeds the DB password) are ``SecretStr`` so they never
    appear in ``repr``/logs; read them with ``.get_secret_value()``.
    """

    model_config = SettingsConfigDict(extra="ignore")

    app_env: Literal["development", "test", "prod"] = "development"
    database_url: SecretStr = SecretStr(f"{_DB}/telerpg")
    db_pool_size: int = Field(default=10, ge=1)

    tg_bot_token: SecretStr = SecretStr(DEV_TG_BOT_TOKEN)
    tg_bot_username: str = ""
    tg_app_short_name: str = ""
    tg_webhook_secret: SecretStr = SecretStr("")

    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_ttl_seconds: int = Field(default=24 * 3600, gt=0)

    public_base_url: str = "http://localhost:3000"
    storage_dir: str = "./data/files"
    sentry_dsn: str = ""
    frontend_dist: str = ""

    difficulty_xp: dict[Difficulty, int] = {
        Difficulty.EASY: 20,
        Difficulty.NORMAL: 50,
        Difficulty.HARD: 100,
        Difficulty.EPIC: 250,
    }

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
            if errors:
                raise ValueError("; ".join(errors) + " when APP_ENV=prod")
        if set(self.difficulty_xp) != set(Difficulty):
            raise ValueError("difficulty_xp must define every Difficulty")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
