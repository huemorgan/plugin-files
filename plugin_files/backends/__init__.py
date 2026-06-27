"""Backend factory for plugin-files (plan 002).

``make_storage_from_env(ctx)`` selects one :class:`StorageBackend` from env. The
plugin never *pretends* to be durable or fast — durability is **declared** by the
deployment (`LUNA_FILES_DURABLE` / picking `object`/`db`) and the chosen backend
**reports the truth** via ``state()``.

    LUNA_FILES_BACKEND = auto (default) | local | fly | object | db

`auto` resolution order (each step honest about durability):
  1. fly/local **durable** — LUNA_FILES_ROOT set AND LUNA_FILES_DURABLE=1
  2. object       — S3 creds present (Tigris/R2; machine-independent)
  3. db           — a usable ctx.engine/session factory is present
  4. local **ephemeral** — default root; durable=false + loud warning (never lose function)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..storage import StorageBackend
from .disk import _is_durable_env, make_disk_from_env
from .object import ObjectBackend, has_credentials

log = logging.getLogger("plugin-files")


def _db_available(ctx: Any | None) -> bool:
    return ctx is not None and getattr(ctx, "engine", None) is not None and (
        getattr(ctx, "db_session_factory", None) is not None
    )


def _make_db(ctx: Any) -> StorageBackend:
    from .db import DbBackend  # lazy: only import models/SQLAlchemy wiring when used

    max_gb = int(os.environ.get("LUNA_FILES_MAX_SIZE_GB", "1"))
    max_file_mb = int(os.environ.get("LUNA_FILES_MAX_FILE_MB", "20"))
    return DbBackend(
        ctx.db_session_factory,
        max_bytes=max_gb * 1024 * 1024 * 1024,
        max_file_bytes=max_file_mb * 1024 * 1024,
    )


def make_storage_from_env(ctx: Any | None = None) -> StorageBackend:
    """Build the active backend from env (+ optional plugin context for `db`)."""
    choice = os.environ.get("LUNA_FILES_BACKEND", "auto").strip().lower()

    if choice == "local":
        return make_disk_from_env(backend_name="local")
    if choice == "fly":
        return make_disk_from_env(backend_name="fly", durable=True)
    if choice == "object":
        if not has_credentials():
            log.warning("LUNA_FILES_BACKEND=object but S3 creds missing; falling back to local")
            return make_disk_from_env(backend_name="local")
        return ObjectBackend.from_env()
    if choice == "db":
        if not _db_available(ctx):
            log.warning("LUNA_FILES_BACKEND=db but no ctx.engine; falling back to local")
            return make_disk_from_env(backend_name="local")
        return _make_db(ctx)

    # ---- auto ----
    root_set = bool(os.environ.get("LUNA_FILES_ROOT"))
    if root_set and _is_durable_env():
        return make_disk_from_env(backend_name="fly")  # declared durable disk/volume
    if has_credentials():
        return ObjectBackend.from_env()
    if _db_available(ctx):
        return _make_db(ctx)
    store = make_disk_from_env(backend_name="local")
    if not store.state().durable:
        log.warning(
            "plugin-files: using EPHEMERAL local disk (%s) — files may be lost on "
            "deploy/restart. Set LUNA_FILES_DURABLE=1 on a persistent disk, or use "
            "LUNA_FILES_BACKEND=object|db for durability.",
            store.state().location,
        )
    return store


__all__ = ["make_storage_from_env", "make_disk_from_env", "ObjectBackend"]
