from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import JournalVisibility


class JournalEvent(Base):
    """Adventure Journal entry. ``payload`` denormalizes titles and amounts so history
    survives later edits and deletions of the referenced entity."""

    __tablename__ = "journal_event"
    __table_args__ = (Index(None, "partnership_id", "created_at"),)

    id: Mapped[int] = id_pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    partnership_id: Mapped[int | None] = mapped_column(ForeignKey("partnership.id"))
    type: Mapped[str] = mapped_column(String(64))
    visibility: Mapped[JournalVisibility] = mapped_column(pg_enum(JournalVisibility))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = created_at()
