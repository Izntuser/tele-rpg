from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import Attribute, Locale


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        # Partial on purpose (migration 0005): Postgres treats only non-partial unique indexes
        # as row "keys", so account deletion rewriting tg_user_id to -id is a no-key update
        # and never conflicts with the FOR KEY SHARE that FK checks take (DECISIONS #16).
        # Live Telegram ids are positive, deleted rows hold -id (unique by construction).
        Index(
            "ux_user_tg_user_id_live",
            "tg_user_id",
            unique=True,
            postgresql_where=text("tg_user_id > 0"),
        ),
        Index(None, "tg_user_id"),
    )

    id: Mapped[int] = id_pk()
    tg_user_id: Mapped[int] = mapped_column(BigInteger)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    avatar_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("file.id", use_alter=True, name="fk_user_avatar_file_id_file")
    )
    locale: Mapped[Locale] = mapped_column(pg_enum(Locale), server_default=Locale.EN.value)
    timezone: Mapped[str] = mapped_column(String(64), server_default="UTC")
    can_message: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # categories, quiet_hours_start/end, daily_summary
    notification_prefs: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    onboarded_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Character(Base):
    __tablename__ = "character"
    __table_args__ = (CheckConstraint("total_xp >= 0", name="total_xp_non_negative"),)

    id: Mapped[int] = id_pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    nickname: Mapped[str | None] = mapped_column(String(64))
    bio: Mapped[str | None] = mapped_column(Text)
    total_xp: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = created_at()


class CharacterAttribute(Base):
    __tablename__ = "character_attribute"
    __table_args__ = (CheckConstraint("xp >= 0", name="xp_non_negative"),)

    character_id: Mapped[int] = mapped_column(ForeignKey("character.id"), primary_key=True)
    attribute: Mapped[Attribute] = mapped_column(pg_enum(Attribute), primary_key=True)
    xp: Mapped[int] = mapped_column(Integer, server_default=text("0"))
