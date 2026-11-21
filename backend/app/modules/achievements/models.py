from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at


class AchievementUnlock(Base):
    """Definitions are code (``app.modules.achievements.definitions``); only unlocks are rows."""

    __tablename__ = "achievement_unlock"

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    unlocked_at: Mapped[datetime] = created_at()
