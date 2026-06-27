"""`object` backend — S3-compatible object storage (plan 002).

One backend, two vendor choices via endpoint + creds:

* **Tigris** (Fly-native, recommended on Fly) — co-located, low latency, durable.
* **Cloudflare R2** — the off-platform equivalent.

Durable and **independent of the machine** (survives even host loss), but it's
*object* storage: no real directories (prefixes only) and **no in-place edits**.
The capability flags advertise this honestly (``supports_inplace_edit=False``) so
the code engine never treats it as a live workspace — it's for
artifacts/attachments/archives/backups.

``boto3`` is imported lazily so the plugin loads fine on deployments that don't
use this backend.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
from datetime import datetime, timezone

from ..storage import FileEntry, StorageBackend, StorageState, sanitize_rel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def has_credentials() -> bool:
    """True when enough S3 env is present to build the backend."""
    return bool(
        os.environ.get("LUNA_FILES_S3_BUCKET")
        and os.environ.get("LUNA_FILES_S3_ACCESS_KEY_ID")
        and os.environ.get("LUNA_FILES_S3_SECRET_ACCESS_KEY")
    )


class ObjectBackend(StorageBackend):
    supports_dirs = True            # prefixes, browsable
    supports_move = True            # copy + delete

    def __init__(
        self,
        bucket: str,
        access_key: str,
        secret_key: str,
        *,
        endpoint_url: str | None = None,
        region: str = "auto",
        prefix: str = "",
        public_url_base: str | None = None,
        max_bytes: int = 50 * 1024 * 1024 * 1024,
        max_file_bytes: int = 200 * 1024 * 1024,
    ) -> None:
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._endpoint = endpoint_url
        self._region = region
        self._prefix = (prefix or "").strip("/")
        self._public = (public_url_base or "").rstrip("/") or None
        self._max_bytes = max_bytes
        self._max_file_bytes = max_file_bytes
        self._client = None  # lazily built

    @classmethod
    def from_env(cls) -> "ObjectBackend":
        max_gb = int(os.environ.get("LUNA_FILES_MAX_SIZE_GB", "50"))
        max_file_mb = int(os.environ.get("LUNA_FILES_MAX_FILE_MB", "200"))
        return cls(
            bucket=os.environ["LUNA_FILES_S3_BUCKET"],
            access_key=os.environ["LUNA_FILES_S3_ACCESS_KEY_ID"],
            secret_key=os.environ["LUNA_FILES_S3_SECRET_ACCESS_KEY"],
            endpoint_url=os.environ.get("LUNA_FILES_S3_ENDPOINT") or None,
            region=os.environ.get("LUNA_FILES_S3_REGION", "auto"),
            prefix=os.environ.get("LUNA_FILES_S3_PREFIX", ""),
            public_url_base=os.environ.get("LUNA_FILES_S3_PUBLIC_URL") or None,
            max_bytes=max_gb * 1024 * 1024 * 1024,
            max_file_bytes=max_file_mb * 1024 * 1024,
        )

    # ---- key helpers -------------------------------------------------------
    def _key(self, path: str) -> str:
        rel = sanitize_rel(path)
        if self._prefix:
            return f"{self._prefix}/{rel}" if rel else f"{self._prefix}/"
        return rel

    def _rel_from_key(self, key: str) -> str:
        base = f"{self._prefix}/" if self._prefix else ""
        return key[len(base):] if base and key.startswith(base) else key

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
            )
        return self._client

    async def _call(self, fn_name: str, **kwargs):
        client = self._get_client()
        return await asyncio.to_thread(getattr(client, fn_name), **kwargs)

    # ---- API ---------------------------------------------------------------
    async def list(self, path: str = "/") -> list[FileEntry]:
        rel = sanitize_rel(path)
        base = self._key(rel)
        if base and not base.endswith("/"):
            base += "/"
        resp = await self._call(
            "list_objects_v2", Bucket=self._bucket, Prefix=base, Delimiter="/"
        )
        out: list[FileEntry] = []
        for cp in resp.get("CommonPrefixes", []) or []:
            full = cp["Prefix"].rstrip("/")
            relp = self._rel_from_key(full)
            name = relp.rsplit("/", 1)[-1]
            if not name:
                continue
            out.append(FileEntry(relp, name, True, None, None, _now(), _now()))
        for obj in resp.get("Contents", []) or []:
            key = obj["Key"]
            if key == base or key.endswith("/"):
                continue  # the dir marker itself
            relp = self._rel_from_key(key)
            name = relp.rsplit("/", 1)[-1]
            out.append(FileEntry(
                relp, name, False, obj.get("Size", 0),
                mimetypes.guess_type(name)[0],
                obj.get("LastModified") or _now(), obj.get("LastModified") or _now(),
            ))
        out.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return out

    async def read(self, path: str) -> bytes:
        try:
            resp = await self._call("get_object", Bucket=self._bucket, Key=self._key(path))
        except Exception as e:  # noqa: BLE001 — map vendor NoSuchKey to FileNotFoundError
            if "NoSuchKey" in type(e).__name__ or "404" in str(e):
                raise FileNotFoundError(path) from e
            raise
        return await asyncio.to_thread(resp["Body"].read)

    async def write(self, path: str, content: bytes, mime_type: str | None = None) -> FileEntry:
        if len(content) > self._max_file_bytes:
            raise ValueError(f"File too large: {len(content)} bytes (max {self._max_file_bytes})")
        rel = sanitize_rel(path)
        if not rel:
            raise ValueError("cannot write to root")
        name = rel.rsplit("/", 1)[-1]
        ct = mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        await self._call(
            "put_object", Bucket=self._bucket, Key=self._key(rel), Body=content, ContentType=ct
        )
        return FileEntry(rel, name, False, len(content), ct, _now(), _now())

    async def mkdir(self, path: str) -> FileEntry:
        rel = sanitize_rel(path)
        if not rel:
            raise ValueError("cannot create root")
        await self._call("put_object", Bucket=self._bucket, Key=self._key(rel) + "/", Body=b"")
        return FileEntry(rel, rel.rsplit("/", 1)[-1], True, None, None, _now(), _now())

    async def delete(self, path: str) -> bool:
        rel = sanitize_rel(path)
        if not rel:
            return False
        key = self._key(rel)
        # Try the object first.
        head = await self._head(key)
        if head is not None:
            await self._call("delete_object", Bucket=self._bucket, Key=key)
            return True
        # Else treat as a prefix (directory) and bulk-delete.
        prefix = key + "/"
        resp = await self._call("list_objects_v2", Bucket=self._bucket, Prefix=prefix)
        contents = resp.get("Contents", []) or []
        if not contents:
            return False
        await self._call(
            "delete_objects",
            Bucket=self._bucket,
            Delete={"Objects": [{"Key": o["Key"]} for o in contents]},
        )
        return True

    async def move(self, src: str, dst: str) -> FileEntry:
        s = self._key(src)
        d = self._key(dst)
        if await self._head(s) is None:
            raise FileNotFoundError(src)
        await self._call(
            "copy_object", Bucket=self._bucket, CopySource={"Bucket": self._bucket, "Key": s}, Key=d
        )
        await self._call("delete_object", Bucket=self._bucket, Key=s)
        return await self.stat(dst)

    async def _head(self, key: str) -> dict | None:
        try:
            return await self._call("head_object", Bucket=self._bucket, Key=key)
        except Exception:  # noqa: BLE001
            return None

    async def stat(self, path: str) -> FileEntry:
        rel = sanitize_rel(path)
        key = self._key(rel)
        head = await self._head(key)
        if head is None:
            # Maybe a prefix (directory)?
            resp = await self._call(
                "list_objects_v2", Bucket=self._bucket, Prefix=key + "/", MaxKeys=1
            )
            if resp.get("KeyCount", 0) or resp.get("Contents"):
                return FileEntry(rel, rel.rsplit("/", 1)[-1], True, None, None, _now(), _now())
            raise FileNotFoundError(path)
        name = rel.rsplit("/", 1)[-1]
        return FileEntry(
            rel, name, False, head.get("ContentLength", 0),
            head.get("ContentType") or mimetypes.guess_type(name)[0],
            head.get("LastModified") or _now(), head.get("LastModified") or _now(),
        )

    async def exists(self, path: str) -> bool:
        key = self._key(path)
        if await self._head(key) is not None:
            return True
        resp = await self._call("list_objects_v2", Bucket=self._bucket, Prefix=key + "/", MaxKeys=1)
        return bool(resp.get("KeyCount", 0) or resp.get("Contents"))

    async def usage(self) -> dict[str, object]:
        prefix = f"{self._prefix}/" if self._prefix else ""
        total = 0
        token: str | None = None
        while True:
            kwargs = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = await self._call("list_objects_v2", **kwargs)
            for obj in resp.get("Contents", []) or []:
                total += obj.get("Size", 0)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return {"used_bytes": total, "max_bytes": self._max_bytes}

    def state(self) -> StorageState:
        loc = f"s3://{self._bucket}/{self._prefix}".rstrip("/")
        return StorageState(
            backend="object",
            durable=True,
            location=loc,
            durability_reason="S3-compatible object store (Tigris/R2)",
            max_bytes=self._max_bytes,
            max_file_bytes=self._max_file_bytes,
            supports_dirs=True,
            supports_inplace_edit=False,
        )
