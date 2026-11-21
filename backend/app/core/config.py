from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_DB = "postgresql+asyncpg://telerpg:telerpg@localhost:5432"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_env: str = "development"
    database_url: str = f"{_DB}/telerpg"
    tg_bot_token: str = "123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"
    jwt_secret: str = "dev-jwt-secret-change-me"
    frontend_dist: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
