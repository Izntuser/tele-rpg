from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import InvitationStatus, PartnershipStatus


class Partnership(Base):
    """A pair of users, stored with ``user_a_id < user_b_id`` so the pair has one spelling.

    "At most one active partnership per user" is enforced by two partial unique indexes
    (the user as ``user_a`` / as ``user_b``) plus the ``partnership_one_active_per_user``
    trigger from migration 0001, which covers the cross case (user is ``a`` in one active row
    and ``b`` in another). Triggers are invisible to autogenerate, so the model only declares
    the indexes.
    """

    __tablename__ = "partnership"
    __table_args__ = (
        CheckConstraint("user_a_id < user_b_id", name="users_ordered"),
        UniqueConstraint("user_a_id", "user_b_id"),
        Index(
            "ux_partnership_active_user_a",
            "user_a_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ux_partnership_active_user_b",
            "user_b_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = id_pk()
    user_a_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    user_b_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    status: Mapped[PartnershipStatus] = mapped_column(
        pg_enum(PartnershipStatus), server_default=PartnershipStatus.ACTIVE.value
    )
    created_at: Mapped[datetime] = created_at()
    accepted_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    ended_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))


class PartnershipInvitation(Base):
    __tablename__ = "partnership_invitation"
    __table_args__ = (
        Index(
            "ux_partnership_invitation_pending_creator",
            "creator_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = id_pk()
    creator_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    # hex sha256 of the invite token; the raw token is never stored
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[InvitationStatus] = mapped_column(
        pg_enum(InvitationStatus), server_default=InvitationStatus.PENDING.value
    )
    expires_at: Mapped[datetime]
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    accepted_at: Mapped[datetime | None]
