"""Storage seam for plugin-files (plan 002).

``StorageBackend`` (historically ``FileStorage``) is the **single seam** every
caller in the plugin depends on — the six ``file_*`` tools, the 001
``FilesStorageProvider``, ``routes.py`` and the UI. Concrete backends
(``DiskFileStorage`` here; ``ObjectBackend`` / ``DbBackend`` under ``backends/``)
implement it, and each one **describes its own durability** via
:meth:`StorageBackend.state`. That is the "won't break easily" property: one
interface, many implementations, a single set of callers.
"""

from __future__ import annotations

import mimetypes
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = str(Path.home() / ".luna" / "files")


@dataclass
class FileEntry:
    path: str  # relative to root, e.g. "user/images/logo.png"
    name: str  # "logo.png"
    is_dir: bool
    size_bytes: int | None  # None for dirs
    mime_type: str | None
    created_at: datetime
    modified_at: datetime


@dataclass
class StorageState:
    """A backend's self-description — the answer to "is my data safe here?".

    Surfaced via ``usage()``, the ``file_storage_status`` tool, and a banner in
    the Files UI so durability is answerable at a glance, per backend.
    """

    backend: str            # "local" | "fly" | "object" | "db"
    durable: bool           # do bytes survive a deploy/restart of THIS host?
    location: str           # human string: "/workspace/files" | "s3://bucket/prefix" | "postgres:plugin_files_blobs"
    durability_reason: str  # WHY: "mounted Fly volume" | "ephemeral container disk" | "tenant Postgres" | …
    max_bytes: int
    max_file_bytes: int
    supports_dirs: bool = True       # real directories / key-prefixes the UI can browse
    supports_inplace_edit: bool = True  # can a file be rewritten in place (POSIX) — false for object stores

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sanitize_rel(path: str) -> str:
    """Normalize a path to a safe, root-relative POSIX path. Rejects traversal.

    Shared by the non-disk backends (object/db) which don't have a real
    filesystem to lean on for ``..`` rejection. Returns ``""`` for the root.
    """
    clean = (path or "").strip().replace("\\", "/").strip("/")
    if not clean or clean == ".":
        return ""
    parts: list[str] = []
    for seg in clean.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ValueError(f"Path traversal blocked: {path}")
        parts.append(seg)
    return "/".join(parts)


class StorageBackend(ABC):
    """The one seam. (Historically named ``FileStorage``.)"""

    # Capability flags — a tool can degrade gracefully instead of crashing on a
    # backend that can't do dirs / in-place edits (e.g. object stores).
    supports_dirs: bool = True
    supports_move: bool = True

    @abstractmethod
    async def list(self, path: str = "/") -> list[FileEntry]:
        ...

    @abstractmethod
    async def read(self, path: str) -> bytes:
        ...

    @abstractmethod
    async def write(self, path: str, content: bytes, mime_type: str | None = None) -> FileEntry:
        ...

    @abstractmethod
    async def mkdir(self, path: str) -> FileEntry:
        ...

    @abstractmethod
    async def delete(self, path: str) -> bool:
        ...

    @abstractmethod
    async def move(self, src: str, dst: str) -> FileEntry:
        ...

    @abstractmethod
    async def stat(self, path: str) -> FileEntry:
        ...

    @abstractmethod
    async def exists(self, path: str) -> bool:
        ...

    @abstractmethod
    async def usage(self) -> dict[str, Any]:
        """Return {used_bytes, max_bytes}."""
        ...

    @abstractmethod
    def state(self) -> StorageState:
        """Self-describe: kind, durability, location, limits, capabilities."""
        ...


# Back-compat alias: the seam used to be called ``FileStorage``. Keep the old
# name working for any importer (and existing tests).
FileStorage = StorageBackend


class DiskFileStorage(StorageBackend):
    """Local-filesystem backend. Covers the ``local`` (dev) and ``fly`` (mounted
    Fly volume) modes — same code, different root + a declared durability flag.
    """

    def __init__(
        self,
        root: str | Path,
        max_bytes: int = 5 * 1024 * 1024 * 1024,
        max_file_bytes: int = 50 * 1024 * 1024,
        *,
        backend_name: str = "local",
        durable: bool = False,
        durability_reason: str = "",
    ):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._max_file_bytes = max_file_bytes
        self._backend_name = backend_name
        self._durable = durable
        self._durability_reason = durability_reason or (
            "durable disk" if durable else "ephemeral container disk"
        )

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, path: str) -> Path:
        """Resolve a relative path to an absolute path within root. Rejects traversal."""
        clean = path.strip("/").replace("\\", "/")
        if not clean or clean == ".":
            return self._root
        resolved = (self._root / clean).resolve()
        if not str(resolved).startswith(str(self._root)):
            raise ValueError(f"Path traversal blocked: {path}")
        return resolved

    def _rel(self, absolute: Path) -> str:
        return str(absolute.relative_to(self._root)).replace("\\", "/")

    def _entry(self, p: Path) -> FileEntry:
        st = p.stat()
        return FileEntry(
            path=self._rel(p),
            name=p.name,
            is_dir=p.is_dir(),
            size_bytes=st.st_size if not p.is_dir() else None,
            mime_type=mimetypes.guess_type(p.name)[0] if not p.is_dir() else None,
            created_at=datetime.fromtimestamp(st.st_ctime, tz=timezone.utc),
            modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        )

    async def list(self, path: str = "/") -> list[FileEntry]:
        target = self._resolve(path)
        if not target.exists() or not target.is_dir():
            return []
        entries = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith("."):
                continue
            entries.append(self._entry(child))
        return entries

    async def read(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.exists() or target.is_dir():
            raise FileNotFoundError(path)
        return target.read_bytes()

    async def write(self, path: str, content: bytes, mime_type: str | None = None) -> FileEntry:
        if len(content) > self._max_file_bytes:
            raise ValueError(f"File too large: {len(content)} bytes (max {self._max_file_bytes})")
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return self._entry(target)

    async def mkdir(self, path: str) -> FileEntry:
        target = self._resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        return self._entry(target)

    async def delete(self, path: str) -> bool:
        target = self._resolve(path)
        if not target.exists():
            return False
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return True

    async def move(self, src: str, dst: str) -> FileEntry:
        src_path = self._resolve(src)
        dst_path = self._resolve(dst)
        if not src_path.exists():
            raise FileNotFoundError(src)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        return self._entry(dst_path)

    async def stat(self, path: str) -> FileEntry:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(path)
        return self._entry(target)

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    async def usage(self) -> dict[str, Any]:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(self._root):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return {"used_bytes": total, "max_bytes": self._max_bytes}

    def state(self) -> StorageState:
        return StorageState(
            backend=self._backend_name,
            durable=self._durable,
            location=str(self._root),
            durability_reason=self._durability_reason,
            max_bytes=self._max_bytes,
            max_file_bytes=self._max_file_bytes,
            supports_dirs=True,
            supports_inplace_edit=True,
        )
