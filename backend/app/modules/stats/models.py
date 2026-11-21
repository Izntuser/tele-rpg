from sqlalchemy import CheckConstraint, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum
from app.modules.common.enums import Attribute


class LifeBalanceTarget(Base):
    __tablename__ = "life_balance_target"
    __table_args__ = (
        CheckConstraint("weekly_xp_target >= 0", name="weekly_xp_target_non_negative"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    attribute: Mapped[Attribute] = mapped_column(pg_enum(Attribute), primary_key=True)
    weekly_xp_target: Mapped[int] = mapped_column(Integer, server_default=text("100"))
