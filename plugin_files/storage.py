"""FileStorage abstraction — disk-backed, with S3 future option."""

from __future__ import annotations

import mimetypes
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
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


class FileStorage(ABC):
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


class DiskFileStorage(FileStorage):
    def __init__(self, root: str | Path, max_bytes: int = 5 * 1024 * 1024 * 1024, max_file_bytes: int = 50 * 1024 * 1024):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._max_file_bytes = max_file_bytes

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


def make_storage_from_env() -> DiskFileStorage:
    """Build the disk store from env — the single source of config so the
    plugin entry (on_load) and the routes module agree without a registry
    lookup. Reads LUNA_FILES_ROOT / LUNA_FILES_MAX_SIZE_GB / LUNA_FILES_MAX_FILE_MB.
    """
    root = os.environ.get("LUNA_FILES_ROOT", _DEFAULT_ROOT)
    max_gb = int(os.environ.get("LUNA_FILES_MAX_SIZE_GB", "5"))
    max_file_mb = int(os.environ.get("LUNA_FILES_MAX_FILE_MB", "50"))
    return DiskFileStorage(
        root=root,
        max_bytes=max_gb * 1024 * 1024 * 1024,
        max_file_bytes=max_file_mb * 1024 * 1024,
    )
