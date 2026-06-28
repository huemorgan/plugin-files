"""plugin-files — file storage and browser.

Provides agent tools for file management and a standalone file browser
UI served in an iframe via the 005.909 plugin architecture.
"""

from __future__ import annotations

import logging
from typing import Any

from luna_sdk import LunaPlugin, PluginContext, PluginManifest, SidebarSection, ToolDef

from .backends import make_storage_from_env
from .provider import FilesStorageProvider

log = logging.getLogger("plugin-files")


class FilesPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="plugin-files",
        version="0.6.1",
        description="File storage and browser.",
        category="system",
        # 001: plugin-files is the StorageProvider — the one sanctioned way any
        # plugin persists bytes (registry key "storage", same field plugin-memory
        # / plugin-vault use to advertise "memory" / "vault").
        provider="storage",
        sidebar_sections=[
            SidebarSection(id="files", label="Files", icon="folder", sort_order=35),
        ],
        routes_module="routes",
    )

    def __init__(self) -> None:
        self.storage: Any | None = None

    async def on_load(self, ctx: PluginContext) -> None:
        # 002: pick the backend from env (local | fly | object | db), passing ctx
        # so the `db` backend can use the per-agent Postgres (ctx.engine / sessions).
        self.storage = make_storage_from_env(ctx)
        storage = self.storage
        state = storage.state()

        # 002: the `db` backend owns one table (plugin_files_blobs). Create it
        # idempotently against ctx.engine (E4 — isolated metadata, never touches core).
        if state.backend == "db" and getattr(ctx, "engine", None) is not None:
            from .models import ALL_TABLES

            async with ctx.engine.begin() as conn:
                for table in ALL_TABLES:
                    await conn.run_sync(table.create, checkfirst=True)

        # 001: register the StorageProvider so any plugin can persist via
        # ctx.storage into a per-plugin folder (e.g. browser → /browser).
        # Guarded for older cores without a provider registry; replace-or-register
        # mirrors plugin-memory so a reload doesn't trip the "two impls" guard.
        registry = getattr(ctx, "provider_registry", None)
        if registry is not None:
            provider = FilesStorageProvider(storage)
            if registry.has("storage"):
                registry.replace("storage", provider)
            else:
                registry.register("storage", provider)
            log.info("plugin-files registered StorageProvider (key=storage)")

        async def _file_list(path: str = "/") -> dict[str, Any]:
            entries = await storage.list(path)
            return {
                "path": path,
                "entries": [
                    {
                        "path": e.path, "name": e.name, "is_dir": e.is_dir,
                        "size_bytes": e.size_bytes, "mime_type": e.mime_type,
                    }
                    for e in entries
                ],
                "count": len(entries),
            }

        async def _file_read(path: str) -> dict[str, Any]:
            try:
                entry = await storage.stat(path)
            except FileNotFoundError:
                return {"error": f"File not found: {path}"}
            if entry.is_dir:
                return {"error": f"Cannot read a directory: {path}"}
            if entry.size_bytes and entry.size_bytes > 100_000:
                return {
                    "path": path, "size_bytes": entry.size_bytes,
                    "mime_type": entry.mime_type,
                    "note": "File too large to return as text. Use the file browser UI.",
                }
            content = await storage.read(path)
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                return {
                    "path": path, "size_bytes": len(content),
                    "mime_type": entry.mime_type,
                    "note": "Binary file. Use the file browser UI to preview.",
                }
            return {"path": path, "content": text, "size_bytes": len(content)}

        async def _file_write(path: str, content: str) -> dict[str, Any]:
            try:
                entry = await storage.write(path, content.encode("utf-8"))
            except ValueError as e:
                return {"error": str(e)}
            return {"written": True, "path": entry.path, "size_bytes": entry.size_bytes}

        async def _file_mkdir(path: str) -> dict[str, Any]:
            entry = await storage.mkdir(path)
            return {"created": True, "path": entry.path}

        async def _file_delete(path: str) -> dict[str, Any]:
            ok = await storage.delete(path)
            if not ok:
                return {"error": f"Not found: {path}"}
            return {"deleted": True, "path": path}

        async def _file_move(src: str, dst: str) -> dict[str, Any]:
            try:
                entry = await storage.move(src, dst)
            except FileNotFoundError:
                return {"error": f"Source not found: {src}"}
            return {"moved": True, "from": src, "to": entry.path}

        async def _file_storage_status() -> dict[str, Any]:
            # 002: the documented durability "state" — backend kind, durable?,
            # location, capabilities, and live usage. Answers "is my data safe here?".
            s = storage.state().to_dict()
            try:
                s.update(await storage.usage())
            except Exception:  # noqa: BLE001 — usage is best-effort, never fail status
                pass
            return s

        ctx.tool_registry.register(self.manifest.name, ToolDef(
            name="file_list", description="List files and folders in a directory.",
            parameters={"type": "object", "properties": {"path": {"type": "string", "description": "Directory path (default: /)"}}, "required": []},
            policy="auto_approve", risk_level="low",
        ), _file_list)

        ctx.tool_registry.register(self.manifest.name, ToolDef(
            name="file_read", description="Read a text file's content.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            policy="auto_approve", risk_level="low",
        ), _file_read)

        ctx.tool_registry.register(self.manifest.name, ToolDef(
            name="file_write", description="Write text content to a file. Creates parent directories if needed.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            policy="prompt_always", risk_level="low",
        ), _file_write)

        ctx.tool_registry.register(self.manifest.name, ToolDef(
            name="file_mkdir", description="Create a directory (and any parent directories).",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            policy="auto_approve", risk_level="low",
        ), _file_mkdir)

        ctx.tool_registry.register(self.manifest.name, ToolDef(
            name="file_delete", description="Delete a file or directory. Requires owner approval.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            policy="prompt_always", risk_level="high",
        ), _file_delete)

        ctx.tool_registry.register(self.manifest.name, ToolDef(
            name="file_move", description="Move or rename a file or directory.",
            parameters={"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]},
            policy="prompt_always", risk_level="low",
        ), _file_move)

        ctx.tool_registry.register(self.manifest.name, ToolDef(
            name="file_storage_status",
            description="Report the file store's backend, durability, location and usage.",
            parameters={"type": "object", "properties": {}, "required": []},
            policy="auto_approve", risk_level="low",
        ), _file_storage_status)

        log.info(
            "plugin-files loaded (backend=%s durable=%s location=%s)",
            state.backend, state.durable, state.location,
        )
