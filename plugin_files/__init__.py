"""plugin-files — file storage and browser.

Provides agent tools for file management and a standalone file browser
UI served in an iframe via the 005.909 plugin architecture.
"""

from __future__ import annotations

import logging
import os
from typing import Any

# 046 phase01 — cap file_read at the source so a big file never lands raw in
# history. Whole-file reads over the cap return head+tail preview + a pointer;
# the model re-fetches the exact part with offset/limit (line range) or search.
_READ_CHAR_CAP = int(os.environ.get("LUNA_FILE_READ_CHAR_CAP", "16000"))
_READ_HEAD = (_READ_CHAR_CAP * 3) // 4
_READ_TAIL = _READ_CHAR_CAP - _READ_HEAD
_READ_LINE_LIMIT = int(os.environ.get("LUNA_FILE_READ_LINE_LIMIT", "2000"))
_SEARCH_MAX_MATCHES = int(os.environ.get("LUNA_FILE_READ_SEARCH_MAX", "100"))
# Hard ceiling: never pull a multi-MB blob into memory just to slice it.
_READ_BYTE_CEILING = int(os.environ.get("LUNA_FILE_READ_BYTE_CEILING", "5000000"))

from luna_sdk import LunaPlugin, PluginContext, PluginManifest, SidebarSection, ToolDef

try:  # cores with the skill system export it
    from luna_sdk import SkillDef
except ImportError:  # pragma: no cover - older core: tools register ungated
    SkillDef = None

from .backends import make_storage_from_env
from .provider import FilesStorageProvider

log = logging.getLogger("plugin-files")


class FilesPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="plugin-files",
        shown_name="Files",
        icon="folder",
        image="assets/icon.png",
        version="0.13.0",
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

        async def _file_read(
            path: str,
            offset: int | None = None,
            limit: int | None = None,
            search: str | None = None,
        ) -> dict[str, Any]:
            try:
                entry = await storage.stat(path)
            except FileNotFoundError:
                return {"error": f"File not found: {path}"}
            if entry.is_dir:
                return {"error": f"Cannot read a directory: {path}"}
            if entry.size_bytes and entry.size_bytes > _READ_BYTE_CEILING:
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

            lines = text.splitlines()
            total_lines = len(lines)
            size = len(content)

            # search: grep-style, return only matching lines with 1-based nums.
            if search:
                matches = [
                    {"line": i + 1, "text": ln}
                    for i, ln in enumerate(lines)
                    if search in ln
                ]
                capped = matches[:_SEARCH_MAX_MATCHES]
                return {
                    "path": path, "search": search,
                    "matches": capped, "match_count": len(matches),
                    "truncated": len(matches) > len(capped),
                    "total_lines": total_lines, "size_bytes": size,
                }

            # offset/limit: 1-based line slice (also char-capped for safety).
            if offset is not None or limit is not None:
                start = max(0, (offset or 1) - 1)
                span = limit if limit is not None else _READ_LINE_LIMIT
                slice_lines = lines[start:start + span]
                slice_text = "\n".join(slice_lines)
                clipped = len(slice_text) > _READ_CHAR_CAP
                if clipped:
                    slice_text = slice_text[:_READ_CHAR_CAP]
                return {
                    "path": path, "content": slice_text,
                    "offset": start + 1, "returned_lines": len(slice_lines),
                    "total_lines": total_lines, "size_bytes": size,
                    "clipped": clipped,
                }

            # whole-file read, capped: over the budget → head+tail + pointer.
            if len(text) > _READ_CHAR_CAP:
                return {
                    "path": path, "size_bytes": size, "total_lines": total_lines,
                    "preview_head": text[:_READ_HEAD],
                    "preview_tail": text[-_READ_TAIL:],
                    "truncated": True,
                    "note": (
                        f"File is {size} bytes / {total_lines} lines — larger than "
                        f"the {_READ_CHAR_CAP}-char inline cap. Showing head+tail. "
                        "Re-read with offset+limit (line range) or search='<text>' "
                        "to load the exact part you need."
                    ),
                }
            return {
                "path": path, "content": text,
                "size_bytes": size, "total_lines": total_lines,
            }

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

        # 0.8.0: all 7 tools ride behind the file-storage skill — file work is
        # occasional, and 7 schemas in every turn's prompt is pure flooding.
        # Cores without a skill registry get the tools ungated.
        gate = getattr(ctx, "skill_registry", None) is not None and SkillDef is not None

        def _register(defn: ToolDef, handler: Any) -> None:
            nonlocal gate
            if gate:
                try:
                    ctx.tool_registry.register(
                        self.manifest.name, defn, handler, skill_gated=True
                    )
                    return
                except TypeError:  # core knows skills but not the kwarg
                    gate = False
            ctx.tool_registry.register(self.manifest.name, defn, handler)

        _register(ToolDef(
            name="file_list", description="List files and folders in a directory.",
            parameters={"type": "object", "properties": {"path": {"type": "string", "description": "Directory path (default: /)"}}, "required": []},
            policy="auto_approve", risk_level="low",
            modes=["planning", "building", "identify", "fix_approve", "fix_publish"],
        ), _file_list)

        _register(ToolDef(
            name="file_read",
            description=(
                "Read a text file. Large files return a head+tail preview and a "
                "size — re-read a slice with offset+limit (1-based line range) "
                "or search='<text>' to grep matching lines. Load only the part "
                "you need; the whole file is rarely necessary."
            ),
            parameters={"type": "object", "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "1-based start line for a slice."},
                "limit": {"type": "integer", "description": "Number of lines to return from offset."},
                "search": {"type": "string", "description": "Return only lines containing this substring, with line numbers."},
            }, "required": ["path"]},
            policy="auto_approve", risk_level="low",
            modes=["planning", "building", "identify", "fix_approve", "fix_publish"],
        ), _file_read)

        _register(ToolDef(
            name="file_write", description="Write text content to a file. Creates parent directories if needed.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            policy="prompt_always", risk_level="low",
            modes=["planning", "building", "fix_approve", "fix_publish"],
        ), _file_write)

        _register(ToolDef(
            name="file_mkdir", description="Create a directory (and any parent directories).",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            policy="auto_approve", risk_level="low",
            modes=["planning", "building", "fix_approve", "fix_publish"],
        ), _file_mkdir)

        _register(ToolDef(
            name="file_delete", description="Delete a file or directory. Requires owner approval.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            policy="prompt_always", risk_level="high",
            modes=["planning", "building", "fix_approve", "fix_publish"],
        ), _file_delete)

        _register(ToolDef(
            name="file_move", description="Move or rename a file or directory.",
            parameters={"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]},
            policy="prompt_always", risk_level="low",
            modes=["planning", "building", "fix_approve", "fix_publish"],
        ), _file_move)

        _register(ToolDef(
            name="file_storage_status",
            description="Report the file store's backend, durability, location and usage.",
            parameters={"type": "object", "properties": {}, "required": []},
            policy="auto_approve", risk_level="low",
            modes=["planning", "building", "identify", "fix_approve", "fix_publish"],
        ), _file_storage_status)

        if gate:
            try:
                ctx.skill_registry.unregister_plugin(self.manifest.name)
            except Exception:  # noqa: BLE001 — stale-sweep is best effort
                pass
            ctx.skill_registry.register(
                self.manifest.name,
                SkillDef(
                    name="file-storage",
                    description=(
                        "Browse, read, write, move, and delete files in the "
                        "owner's file store. Load when the owner mentions "
                        "their files or you need to save/read a document; the "
                        "file_* tools unlock on your next turn."
                    ),
                    body=(
                        "# File storage\n\n"
                        "Tools (unlock on your NEXT turn after loading this "
                        "skill): file_list, file_read, file_write, "
                        "file_mkdir, file_delete, file_move, "
                        "file_storage_status.\n\n"
                        "- Paths are absolute from the store root, e.g. "
                        "`/reports/q3.md`; file_write creates parent folders.\n"
                        "- file_read previews large files (head+tail) and takes "
                        "offset+limit (line range) or search to load a slice; "
                        "binary files are for the Files pane in the sidebar.\n"
                        "- file_write, file_delete, and file_move raise an "
                        "approval card for the owner.\n"
                        "- file_storage_status answers 'is my data safe "
                        "here?' (backend, durability, usage)."
                    ),
                    tools=[
                        "file_list", "file_read", "file_write", "file_mkdir",
                        "file_delete", "file_move", "file_storage_status",
                    ],
                ),
            )

        log.info(
            "plugin-files loaded (backend=%s durable=%s location=%s)",
            state.backend, state.durable, state.location,
        )
