from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import FileKind


class File(Base):
    """Stored upload; bytes live in ``StorageBackend`` under ``storage_key``. Served only via
    ``/api/files/{id}`` after an owner / active-partner check."""

    __tablename__ = "file"
    __table_args__ = (CheckConstraint("size >= 0", name="size_non_negative"),)

    id: Mapped[int] = id_pk()
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    partnership_id: Mapped[int | None] = mapped_column(ForeignKey("partnership.id"))
    kind: Mapped[FileKind] = mapped_column(pg_enum(FileKind))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    mime: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at()
