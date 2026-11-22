from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.telegram import MAX_INIT_DATA_LEN
from app.modules.common.enums import Locale


class TelegramAuthIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    init_data: str = Field(min_length=1, max_length=MAX_INIT_DATA_LEN)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tg_user_id: int
    tg_username: str | None
    display_name: str
    avatar_url: str | None
    #: Custom avatar (``GET /files/{id}``); shown instead of ``avatar_url`` when set.
    avatar_file_id: int | None
    locale: Locale
    timezone: str
    onboarded_at: datetime | None


class CharacterSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    nickname: str | None
    total_xp: int


class CompanionSummary(BaseModel):
    id: int
    display_name: str
    avatar_url: str | None


class PartnershipSummary(BaseModel):
    id: int
    companion: CompanionSummary


class AuthOut(BaseModel):
    jwt: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut
    start_param: str | None


class MeOut(BaseModel):
    user: UserOut
    character: CharacterSummary | None
    partnership: PartnershipSummary | None
