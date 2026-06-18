"""plugin-files API routes + standalone UI serving."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

from luna_sdk import get_current_user

from .storage import make_storage_from_env


def register_routes(app, ctx):
    router = APIRouter(prefix="/api/p/plugin-files", tags=["files"])

    # Build storage from the same env config the plugin entry uses (no registry
    # lookup — keeps routes decoupled from the loader). Disk storage is
    # stateless over its root, so this instance is equivalent to the entry's.
    _store = make_storage_from_env()

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
    async def read_file(path: str, user=Depends(get_current_user)):
        storage = _storage()
        if storage is None:
            raise HTTPException(503, "plugin-files not loaded")
        try:
            content = await storage.read(path)
        except FileNotFoundError:
            raise HTTPException(404, "File not found")
        entry = await storage.stat(path)
        return StreamingResponse(
            iter([content]),
            media_type=entry.mime_type or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{entry.name}"'},
        )

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
