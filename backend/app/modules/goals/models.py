from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import Attribute, GoalStatus


class DevelopmentGoal(Base):
    __tablename__ = "development_goal"

    id: Mapped[int] = id_pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    attribute: Mapped[Attribute | None] = mapped_column(pg_enum(Attribute))
    status: Mapped[GoalStatus] = mapped_column(
        pg_enum(GoalStatus), server_default=GoalStatus.ACTIVE.value
    )
    created_at: Mapped[datetime] = created_at()
