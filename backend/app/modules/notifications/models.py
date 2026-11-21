from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import NotificationCategory, NotificationStatus


class Notification(Base):
    """Transactional outbox row (sent by the dispatcher after commit) and inbox entry.

    Reminders and summaries are deduplicated per (recipient, type, entity, UTC day of
    ``send_after``). ``NULLS NOT DISTINCT`` makes entity-less rows (the daily summary) collide
    too, and ``AT TIME ZONE 'UTC'`` keeps the index expression immutable.
    """

    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index(
            "ux_notification_dedupe",
            "recipient_id",
            "type",
            "entity_id",
            text("((send_after AT TIME ZONE 'UTC')::date)"),
            unique=True,
            postgresql_where=text("category IN ('reminders', 'summary')"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = id_pk()
    recipient_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    type: Mapped[str] = mapped_column(String(64))
    category: Mapped[NotificationCategory] = mapped_column(pg_enum(NotificationCategory))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    deep_link: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus), server_default=NotificationStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    read_at: Mapped[datetime | None]
    send_after: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[datetime] = created_at()
    delivered_at: Mapped[datetime | None]
