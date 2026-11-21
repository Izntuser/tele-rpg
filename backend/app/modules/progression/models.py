from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import Attribute


class XpTransaction(Base):
    """One row per completed quest occurrence (unique ``quest_occurrence_id``)."""

    __tablename__ = "xp_transaction"
    __table_args__ = (
        CheckConstraint("xp >= 0", name="xp_non_negative"),
        CheckConstraint("attribute_xp >= 0", name="attribute_xp_non_negative"),
    )

    id: Mapped[int] = id_pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    quest_occurrence_id: Mapped[int] = mapped_column(ForeignKey("quest_occurrence.id"), unique=True)
    xp: Mapped[int] = mapped_column(Integer)
    attribute: Mapped[Attribute] = mapped_column(pg_enum(Attribute))
    attribute_xp: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at()
