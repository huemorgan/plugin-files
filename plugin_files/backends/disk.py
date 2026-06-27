"""`local` / `fly` backend — the local filesystem (plan 002).

Both modes are the same :class:`DiskFileStorage`; they differ only in the root
and whether the deployment *declares* that root durable (``LUNA_FILES_DURABLE``).
A Fly volume mounted at ``/workspace`` is fast local NVMe and persists across
deploys, so ``fly`` is just ``local`` with ``durable=True`` and a clearer label.
"""

from __future__ import annotations

import os

from ..storage import _DEFAULT_ROOT, DiskFileStorage

# Public name per the plan; identical to the historical DiskFileStorage.
DiskBackend = DiskFileStorage

_TRUTHY = {"1", "true", "yes", "on"}


def _is_durable_env() -> bool:
    return os.environ.get("LUNA_FILES_DURABLE", "").strip().lower() in _TRUTHY


def make_disk_from_env(*, backend_name: str = "local", durable: bool | None = None) -> DiskFileStorage:
    """Build the disk store from env.

    Reads ``LUNA_FILES_ROOT`` / ``LUNA_FILES_MAX_SIZE_GB`` / ``LUNA_FILES_MAX_FILE_MB``.
    Durability is **declared** (never guessed): ``durable`` arg wins, else
    ``LUNA_FILES_DURABLE``.
    """
    root = os.environ.get("LUNA_FILES_ROOT", _DEFAULT_ROOT)
    max_gb = int(os.environ.get("LUNA_FILES_MAX_SIZE_GB", "5"))
    max_file_mb = int(os.environ.get("LUNA_FILES_MAX_FILE_MB", "50"))
    is_durable = _is_durable_env() if durable is None else durable
    reason = (
        "mounted Fly volume" if backend_name == "fly"
        else ("declared durable disk" if is_durable else "ephemeral container disk")
    )
    return DiskFileStorage(
        root=root,
        max_bytes=max_gb * 1024 * 1024 * 1024,
        max_file_bytes=max_file_mb * 1024 * 1024,
        backend_name=backend_name,
        durable=is_durable,
        durability_reason=reason,
    )
