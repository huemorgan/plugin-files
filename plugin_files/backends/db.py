"""`db` backend — durable bytes in Postgres (plan 002).

Zero-infra durability for ephemeral hosts: the filesystem is modelled in one
plugin-owned table (``plugin_files_blobs``), a row per path with the bytes inline.
No volume, no bucket — if the agent has a database (it does), files survive image
swaps. Best for small files; big/hot data belongs on ``fly``/``object``.

Directories are virtual (rows with ``is_dir=True``); ``list`` is a prefix query;
``move`` rewrites path prefixes. Same traversal guard + size caps as every backend.
"""

from __future__ import annotations

import mimetypes
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import FileBlobRow
from ..storage import FileEntry, StorageBackend, StorageState, sanitize_rel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DbBackend(StorageBackend):
    supports_dirs = True
    supports_move = True

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        max_bytes: int = 1 * 1024 * 1024 * 1024,
        max_file_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        self._sf = session_factory
        self._max_bytes = max_bytes
        self._max_file_bytes = max_file_bytes

    # ---- helpers -----------------------------------------------------------
    def _entry(self, row: FileBlobRow) -> FileEntry:
        name = row.path.rsplit("/", 1)[-1] if row.path else ""
        return FileEntry(
            path=row.path,
            name=name,
            is_dir=row.is_dir,
            size_bytes=None if row.is_dir else (row.size_bytes or 0),
            mime_type=None if row.is_dir else (row.media_type or mimetypes.guess_type(name)[0]),
            created_at=row.created_at or _now(),
            modified_at=row.updated_at or _now(),
        )

    async def _get(self, session: AsyncSession, path: str) -> FileBlobRow | None:
        res = await session.execute(select(FileBlobRow).where(FileBlobRow.path == path))
        return res.scalar_one_or_none()

    async def _ensure_parents(self, session: AsyncSession, path: str) -> None:
        parts = path.split("/")[:-1]
        acc = ""
        for seg in parts:
            acc = f"{acc}/{seg}" if acc else seg
            if await self._get(session, acc) is None:
                session.add(FileBlobRow(path=acc, is_dir=True))

    # ---- API ---------------------------------------------------------------
    async def list(self, path: str = "/") -> list[FileEntry]:
        prefix = sanitize_rel(path)
        async with self._sf() as session:
            res = await session.execute(select(FileBlobRow))
            rows = res.scalars().all()
        out: list[FileEntry] = []
        base = f"{prefix}/" if prefix else ""
        for row in rows:
            if prefix and not row.path.startswith(base):
                continue
            rest = row.path[len(base):]
            if not rest or "/" in rest:
                continue  # not a direct child
            out.append(self._entry(row))
        out.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return out

    async def read(self, path: str) -> bytes:
        p = sanitize_rel(path)
        async with self._sf() as session:
            row = await self._get(session, p)
            if row is None or row.is_dir:
                raise FileNotFoundError(path)
            return bytes(row.data or b"")

    async def write(self, path: str, content: bytes, mime_type: str | None = None) -> FileEntry:
        if len(content) > self._max_file_bytes:
            raise ValueError(f"File too large: {len(content)} bytes (max {self._max_file_bytes})")
        p = sanitize_rel(path)
        if not p:
            raise ValueError("cannot write to root")
        name = p.rsplit("/", 1)[-1]
        async with self._sf() as session:
            await self._ensure_parents(session, p)
            row = await self._get(session, p)
            if row is None:
                row = FileBlobRow(path=p)
                session.add(row)
            row.is_dir = False
            row.data = content
            row.size_bytes = len(content)
            row.media_type = mime_type or mimetypes.guess_type(name)[0]
            row.updated_at = _now()
            await session.commit()
            await session.refresh(row)
            return self._entry(row)

    async def mkdir(self, path: str) -> FileEntry:
        p = sanitize_rel(path)
        if not p:
            raise ValueError("cannot create root")
        async with self._sf() as session:
            await self._ensure_parents(session, p)
            row = await self._get(session, p)
            if row is None:
                row = FileBlobRow(path=p, is_dir=True)
                session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._entry(row)

    async def delete(self, path: str) -> bool:
        p = sanitize_rel(path)
        if not p:
            return False
        async with self._sf() as session:
            row = await self._get(session, p)
            if row is None:
                return False
            await session.delete(row)
            if row.is_dir:
                await session.execute(
                    sa_delete(FileBlobRow).where(FileBlobRow.path.startswith(f"{p}/"))
                )
            await session.commit()
            return True

    async def move(self, src: str, dst: str) -> FileEntry:
        s = sanitize_rel(src)
        d = sanitize_rel(dst)
        if not s or not d:
            raise ValueError("src and dst required")
        async with self._sf() as session:
            row = await self._get(session, s)
            if row is None:
                raise FileNotFoundError(src)
            await self._ensure_parents(session, d)
            if row.is_dir:
                res = await session.execute(
                    select(FileBlobRow).where(FileBlobRow.path.startswith(f"{s}/"))
                )
                for child in res.scalars().all():
                    child.path = d + child.path[len(s):]
                    child.updated_at = _now()
            row.path = d
            row.updated_at = _now()
            await session.commit()
            await session.refresh(row)
            return self._entry(row)

    async def stat(self, path: str) -> FileEntry:
        p = sanitize_rel(path)
        async with self._sf() as session:
            row = await self._get(session, p)
            if row is None:
                raise FileNotFoundError(path)
            return self._entry(row)

    async def exists(self, path: str) -> bool:
        p = sanitize_rel(path)
        async with self._sf() as session:
            return (await self._get(session, p)) is not None

    async def usage(self) -> dict[str, object]:
        async with self._sf() as session:
            res = await session.execute(
                select(func.coalesce(func.sum(FileBlobRow.size_bytes), 0))
            )
            used = int(res.scalar_one() or 0)
        return {"used_bytes": used, "max_bytes": self._max_bytes}

    def state(self) -> StorageState:
        return StorageState(
            backend="db",
            durable=True,
            location="postgres:plugin_files_blobs",
            durability_reason="tenant Postgres (survives image swaps)",
            max_bytes=self._max_bytes,
            max_file_bytes=self._max_file_bytes,
            supports_dirs=True,
            supports_inplace_edit=True,
        )
