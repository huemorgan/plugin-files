"""plans/002-fix18fails P1.7 — the store's READS are always available.

The file-storage skill unlocks tools on the NEXT turn, so a turn asked "what
is in my files?" could not read the store in the turn that asked. file_list,
file_read and file_storage_status now register ungated; the writes stay behind
the skill, and the skill text says so.
"""

from __future__ import annotations

import asyncio

from plugin_files import FilesPlugin

READS = {"file_list", "file_search", "file_read", "file_storage_status"}
WRITES = {"file_write", "file_mkdir", "file_delete", "file_move"}


class _GatedToolReg:
    """A core that knows skills: records the skill_gated kwarg per tool."""

    def __init__(self) -> None:
        self.gated: dict[str, bool] = {}

    def register(self, _plugin, defn, _handler, **kw) -> None:
        self.gated[defn.name] = bool(kw.get("skill_gated", False))


class _SkillReg:
    def __init__(self) -> None:
        self.defs: list = []

    def unregister_plugin(self, _name) -> None:
        pass

    def register(self, _plugin, defn) -> None:
        self.defs.append(defn)


class _ProviderReg:
    def has(self, key: str) -> bool:
        return False

    def register(self, key: str, impl: object) -> None:
        pass

    def replace(self, key: str, impl: object) -> None:
        pass


def _load(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    ctx = type("Ctx", (), {})()
    ctx.provider_registry = _ProviderReg()
    ctx.tool_registry = _GatedToolReg()
    ctx.skill_registry = _SkillReg()
    asyncio.run(FilesPlugin().on_load(ctx))
    return ctx


def test_reads_ungated_writes_gated(tmp_path, monkeypatch) -> None:
    ctx = _load(tmp_path, monkeypatch)
    gated = ctx.tool_registry.gated
    assert set(gated) == READS | WRITES
    assert {n for n in READS if gated[n]} == set(), "reads must never wait for a skill"
    assert {n for n in WRITES if not gated[n]} == set(), "writes stay behind the skill"


def test_skill_lists_only_the_gated_tools_and_says_reads_are_free(tmp_path, monkeypatch) -> None:
    ctx = _load(tmp_path, monkeypatch)
    (skill,) = ctx.skill_registry.defs
    assert skill.name == "file-storage"
    assert set(skill.tools) == WRITES
    assert "always available" in skill.description.lower()
    assert "file_list" in skill.body and "no skill needed" in skill.body
    assert "NEXT turn" not in skill.body


def test_core_without_skills_gets_everything_ungated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    ctx = type("Ctx", (), {})()
    ctx.provider_registry = _ProviderReg()
    ctx.tool_registry = _GatedToolReg()
    asyncio.run(FilesPlugin().on_load(ctx))
    assert set(ctx.tool_registry.gated) == READS | WRITES
    assert not any(ctx.tool_registry.gated.values())
