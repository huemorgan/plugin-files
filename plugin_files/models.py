"""SQLAlchemy row for the `db` storage backend (plan 002).

One table, ``plugin_files_blobs``, modelling a filesystem: a row per path, with
the bytes inline (``LargeBinary``) for files and ``data=NULL`` for directories.
Bound to its **own** metadata via the SDK's ``declarative_base`` (E4), so a stray
``create_all`` can never touch core tables. Mirrors the 008.6 ``PluginArtifactRow``
precedent of storing durable bytes in Postgres on ephemeral hosts.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from luna_sdk import UUID, declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FileBlobRow(Base):
    __tablename__ = "plugin_files_blobs"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    # Root-relative POSIX path, e.g. "browser/shot-ab12.png". Unique per store.
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True, index=True)
    is_dir: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


ALL_TABLES = (FileBlobRow.__table__,)
