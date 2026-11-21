from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.common.enums import Difficulty

_DB = "postgresql+asyncpg://telerpg:telerpg@localhost:5432"
DEV_JWT_SECRET = "dev-jwt-secret-change-me"
MIN_PROD_JWT_SECRET_LEN = 32


class Settings(BaseSettings):
    """Process configuration from environment variables (names are upper-cased fields)."""

    model_config = SettingsConfigDict(extra="ignore")

    app_env: Literal["development", "test", "prod"] = "development"
    database_url: str = f"{_DB}/telerpg"
    db_pool_size: int = Field(default=10, ge=1)

    tg_bot_token: str = "123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"
    tg_bot_username: str = ""
    tg_app_short_name: str = ""
    tg_webhook_secret: str = ""

    jwt_secret: str = DEV_JWT_SECRET
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
        if self.app_env == "prod" and (
            self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < MIN_PROD_JWT_SECRET_LEN
        ):
            raise ValueError(
                "JWT_SECRET must be set to a non-default value of at least "
                f"{MIN_PROD_JWT_SECRET_LEN} characters when APP_ENV=prod"
            )
        if set(self.difficulty_xp) != set(Difficulty):
            raise ValueError("difficulty_xp must define every Difficulty")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
