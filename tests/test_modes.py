"""Luna plan 089 — every ToolDef declares agent-state modes.

Declared modes are honored exactly by core tool filtering. Write tools must
carry planning/building/fix_approve/fix_publish (so core can drop its interim
PLANNING_WRITE_ALLOWLIST); read-only tools additionally carry identify.
"""

from __future__ import annotations

import asyncio

from plugin_files import FilesPlugin

WRITE_MODES = ["planning", "building", "fix_approve", "fix_publish"]
READ_MODES = ["planning", "building", "identify", "fix_approve", "fix_publish"]

WRITE_TOOLS = {"file_write", "file_mkdir", "file_delete", "file_move"}
READ_TOOLS = {"file_list", "file_read", "file_storage_status"}


class _ToolReg:
    """Capture registered ToolDefs by name (ungated path — no skill_registry)."""

    def __init__(self) -> None:
        self.defs: dict[str, object] = {}

    def register(self, _plugin, defn, _handler, **_kw) -> None:
        self.defs[defn.name] = defn


class _ProviderReg:
    def has(self, key: str) -> bool:
        return False

    def register(self, key: str, impl: object) -> None:
        pass

    def replace(self, key: str, impl: object) -> None:
        pass


def _load_defs(tmp_path, monkeypatch) -> dict[str, object]:
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    ctx = type("Ctx", (), {})()
    ctx.provider_registry = _ProviderReg()
    ctx.tool_registry = _ToolReg()
    asyncio.run(FilesPlugin().on_load(ctx))
    return ctx.tool_registry.defs


def test_all_tools_declare_modes(tmp_path, monkeypatch) -> None:
    defs = _load_defs(tmp_path, monkeypatch)
    assert set(defs) == WRITE_TOOLS | READ_TOOLS
    for name, defn in defs.items():
        assert defn.modes, f"{name} must declare modes"


def test_write_tools_declare_write_modes(tmp_path, monkeypatch) -> None:
    defs = _load_defs(tmp_path, monkeypatch)
    for name in WRITE_TOOLS:
        assert defs[name].modes == WRITE_MODES, name


def test_read_tools_declare_all_five_modes(tmp_path, monkeypatch) -> None:
    defs = _load_defs(tmp_path, monkeypatch)
    for name in READ_TOOLS:
        assert defs[name].modes == READ_MODES, name
