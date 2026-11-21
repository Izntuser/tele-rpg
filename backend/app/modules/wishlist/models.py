from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, id_pk, pg_enum
from app.modules.common.enums import WishlistStatus


class WishlistItem(Base):
    __tablename__ = "wishlist_item"

    id: Mapped[int] = id_pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[WishlistStatus] = mapped_column(
        pg_enum(WishlistStatus), server_default=WishlistStatus.OPEN.value
    )
    linked_reward_id: Mapped[int | None] = mapped_column(ForeignKey("reward.id"))
