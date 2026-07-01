"""plugin-files API routes + standalone UI serving."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

from luna_sdk import get_current_user

from .backends import make_storage_from_env


def _etag(entry) -> str:
    """Weak-ish validator from size + mtime — cheap and stable per byte-version."""
    mt = int(entry.modified_at.timestamp()) if entry.modified_at else 0
    return f'"{entry.size_bytes or 0}-{mt}"'


def _parse_range(header: str, size: int):
    """Parse a single-range `bytes=start-end` header → (start, end) inclusive.

    Returns None if absent/unsatisfiable/multi-range (caller serves full body).
    """
    if not header or not header.startswith("bytes=") or size <= 0:
        return None
    spec = header[len("bytes="):].split(",")[0].strip()
    if "-" not in spec:
        return None
    lo, _, hi = spec.partition("-")
    try:
        if lo == "":  # suffix range: last N bytes
            n = int(hi)
            if n <= 0:
                return None
            start = max(0, size - n)
            end = size - 1
        else:
            start = int(lo)
            end = int(hi) if hi else size - 1
    except ValueError:
        return None
    end = min(end, size - 1)
    if start > end or start < 0:
        return None
    return start, end


def register_routes(app, ctx):
    router = APIRouter(prefix="/api/p/plugin-files", tags=["files"])

    # Build storage from the same env config the plugin entry uses (no registry
    # lookup — keeps routes decoupled from the loader). Backends are stateless
    # over their store (disk root / bucket / shared engine), so this instance is
    # equivalent to the entry's. `ctx` lets the `db` backend reach ctx.engine.
    _store = make_storage_from_env(ctx)

    def _storage():
        return _store

    @router.get("/list")
    async def list_files(path: str = "/", user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        entries = await storage.list(path)
        return {
            "path": path,
            "entries": [
                {
                    "path": e.path, "name": e.name, "is_dir": e.is_dir,
                    "size_bytes": e.size_bytes, "mime_type": e.mime_type,
                    "created_at": e.created_at.isoformat(),
                    "modified_at": e.modified_at.isoformat(),
                }
                for e in entries
            ],
        }

    @router.get("/read/{path:path}")
    async def read_file(request: Request, path: str, user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        try:
            entry = await storage.stat(path)
        except FileNotFoundError:
            raise HTTPException(404, "File not found")
        if entry.is_dir:
            raise HTTPException(400, "Cannot read a directory")

        # Prefer the stored mime, but fall back to the extension when it's absent
        # or a generic octet-stream — otherwise <video>/<audio>/<img> tags won't
        # render files whose type wasn't captured on upload (e.g. db backend).
        media = entry.mime_type
        if not media or media == "application/octet-stream":
            media = mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
        etag = _etag(entry)
        size = entry.size_bytes or 0
        last_mod = entry.modified_at.strftime("%a, %d %b %Y %H:%M:%S GMT") if entry.modified_at else None

        base_headers = {
            "Accept-Ranges": "bytes",
            "ETag": etag,
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f'inline; filename="{entry.name}"',
        }
        if last_mod:
            base_headers["Last-Modified"] = last_mod

        # Not modified? (browser/media element revalidation)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=base_headers)

        # Range request → 206 partial, only the requested slice (native on disk/S3).
        rng = _parse_range(request.headers.get("range", ""), size)
        if rng is not None:
            start, end = rng
            try:
                chunk = await storage.read_range(path, start, end)
            except FileNotFoundError:
                raise HTTPException(404, "File not found")
            headers = {
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(len(chunk)),
            }
            return Response(content=chunk, status_code=206, media_type=media, headers=headers)

        # Full body → streamed in chunks (disk streams; others yield once).
        headers = dict(base_headers)
        if size:
            headers["Content-Length"] = str(size)
        return StreamingResponse(storage.stream(path), media_type=media, headers=headers)

    @router.post("/write/{path:path}")
    async def write_file(path: str, content: bytes = File(...), user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        try:
            entry = await storage.write(path, content)
        except ValueError as e:
            raise HTTPException(413, str(e))
        return {"written": True, "path": entry.path, "size_bytes": entry.size_bytes}

    @router.post("/upload")
    async def upload_file(
        path: str = "/",
        file: UploadFile = File(...),
        user=Depends(get_current_user),
    ):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        content = await file.read()
        target = f"{path.rstrip('/')}/{file.filename}"
        try:
            entry = await storage.write(target, content, mime_type=file.content_type)
        except ValueError as e:
            raise HTTPException(413, str(e))
        return {"uploaded": True, "path": entry.path, "size_bytes": entry.size_bytes, "name": entry.name}

    @router.post("/mkdir/{path:path}")
    async def mkdir(path: str, user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        entry = await storage.mkdir(path)
        return {"created": True, "path": entry.path}

    @router.delete("/delete/{path:path}")
    async def delete_file(path: str, user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        ok = await storage.delete(path)
        if not ok:
            raise HTTPException(404, "Not found")
        return {"deleted": True, "path": path}

    @router.post("/move")
    async def move_file(body: dict, user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        src = body.get("src", "")
        dst = body.get("dst", "")
        if not src or not dst:
            raise HTTPException(400, "src and dst required")
        try:
            entry = await storage.move(src, dst)
        except FileNotFoundError:
            raise HTTPException(404, f"Source not found: {src}")
        return {"moved": True, "from": src, "to": entry.path}

    @router.get("/stat/{path:path}")
    async def stat_file(path: str, user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        try:
            entry = await storage.stat(path)
        except FileNotFoundError:
            raise HTTPException(404, "Not found")
        return {
            "path": entry.path, "name": entry.name, "is_dir": entry.is_dir,
            "size_bytes": entry.size_bytes, "mime_type": entry.mime_type,
            "created_at": entry.created_at.isoformat(),
            "modified_at": entry.modified_at.isoformat(),
        }

    @router.get("/usage")
    async def storage_usage(user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        return await storage.usage()

    @router.get("/status")
    async def storage_status(user=Depends(get_current_user)):
        # 002: the durability "state" (backend, durable?, location, caps) + usage,
        # for the Files-UI banner.
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        out = storage.state().to_dict()
        try:
            out.update(await storage.usage())
        except Exception:  # noqa: BLE001
            pass
        return out

    # Serve the standalone plugin UI
    ui_dir = Path(__file__).parent / "ui"

    @router.get("/ui/{path:path}")
    async def serve_ui(path: str):
        if not path or path == "/":
            path = "index.html"
        target = (ui_dir / path).resolve()
        if not str(target).startswith(str(ui_dir.resolve())):
            raise HTTPException(403, "Forbidden")
        if not target.exists():
            # SPA fallback
            index = ui_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))
            raise HTTPException(404, "Not found")
        return FileResponse(str(target))

    @router.get("/ui/")
    async def serve_ui_root():
        index = ui_dir / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return Response(content="<h1>plugin-files UI not built</h1>", media_type="text/html")

    app.include_router(router)
