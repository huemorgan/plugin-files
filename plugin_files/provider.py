"""StorageProvider face over DiskFileStorage (plan 001 — files mapping).

`FilesStorageProvider` is the one sanctioned way any plugin persists bytes: it
satisfies luna-core's ``StorageProvider`` capability (``save`` / ``read`` /
``url_for``) on top of plugin-files' existing disk store, and registers under the
provider-registry key ``"storage"``.

Duck-typed on purpose: the v0 ``luna_sdk`` does not yet re-export the
``StorageProvider`` ABC (that lands with core 008.95). We implement the contract
shape so callers like plugin-browser (``ctx.storage.save(...)``) work the moment
core exposes ``ctx.storage`` — no import of an as-yet-missing symbol, no
``import luna.*``.

The provider is **folder-aware**: a ``filename`` that contains a relative path
(``"browser/shot-ab12.png"``) is stored under that subfolder, so each producer
gets its own top-level directory in the Files UI (``/browser``, ``/attachments``,
…) without any change to the contract signature.
"""

from __future__ import annotations

from dataclasses import dataclass

from .storage import StorageBackend


@dataclass
class StoredFile:
    """Return shape of ``StorageProvider.save`` (mirrors core's ``StoredFile``)."""

    ref: str          # storage-root-relative handle, e.g. "browser/shot-ab12.png"
    url: str          # browser-fetchable serve-back URL (this provider's read route)
    filename: str     # base name, e.g. "shot-ab12.png"
    media_type: str
    size_bytes: int


def _clean_ref(filename: str) -> str:
    """Normalize a (possibly path-bearing) filename into a safe relative ref.

    Strips leading slashes and Windows separators. Traversal (``..``) is left for
    ``DiskFileStorage`` to reject at write time (its ``_resolve`` raises), so this
    function never needs to silently mangle a malicious path into a valid one.
    """
    ref = (filename or "").strip().replace("\\", "/").lstrip("/")
    if not ref or ref.endswith("/"):
        raise ValueError(f"invalid filename for storage: {filename!r}")
    return ref


class FilesStorageProvider:
    """``StorageProvider`` over any ``StorageBackend`` (disk / object / db)."""

    def __init__(
        self,
        storage: StorageBackend,
        url_prefix: str = "/api/p/plugin-files/read",
    ) -> None:
        self._s = storage
        self._url = url_prefix.rstrip("/")

    async def save(
        self, data: bytes, *, filename: str, media_type: str | None = None
    ) -> StoredFile:
        ref = _clean_ref(filename)
        entry = await self._s.write(ref, data, mime_type=media_type)
        return StoredFile(
            ref=entry.path,
            url=self.url_for(entry.path),
            filename=entry.name,
            media_type=media_type or entry.mime_type or "application/octet-stream",
            size_bytes=entry.size_bytes if entry.size_bytes is not None else len(data),
        )

    async def read(self, ref: str) -> bytes:
        return await self._s.read(ref)

    def url_for(self, ref: str) -> str:
        return f"{self._url}/{ref.lstrip('/')}"
