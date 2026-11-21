from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at


class IdempotencyKey(Base):
    """Stored response for an ``Idempotency-Key`` request header; purged after 24h."""

    __tablename__ = "idempotency_key"
    # Purge of rows older than the TTL (core.idempotency.purge_expired).
    __table_args__ = (Index(None, "created_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(255))
    response: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = created_at()
