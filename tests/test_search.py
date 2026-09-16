"""plans/002-fix18fails P3.1 — file_search + file_list(recursive=true).

The captured failure: "do we have notes on X?" → one top-level file_list, the
note two folders down, "nothing in the store". A recursive walk and a search
tool make "not in the store" a claim the agent can actually back.
"""

from __future__ import annotations

import asyncio

import pytest

from plugin_files import FilesPlugin
from plugin_files.storage import DiskFileStorage, StorageBackend



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


class _ToolReg:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.defs: dict[str, object] = {}
        self.gated: dict[str, bool] = {}

    def register(self, _plugin, defn, handler, **kw) -> None:
        self.handlers[defn.name] = handler
        self.defs[defn.name] = defn
        self.gated[defn.name] = bool(kw.get("skill_gated", False))


def _seed(root):
    (root / "reports" / "2026").mkdir(parents=True)
    (root / "notes").mkdir()
    (root / "reports" / "2026" / "q3-review.md").write_text("Q3 review\nrevenue up 12%\nchurn flat\n")
    (root / "reports" / "summary.txt").write_text("all reports live under 2026/\n")
    (root / "notes" / "berlin-office.md").write_text("Berlin office: lease renews in March\n")
    (root / "notes" / "logo.png").write_bytes(b"\x89PNG\x00\xff")
    (root / ".hidden.md").write_text("Berlin secret")
    (root / "top.md").write_text("nothing here\n")


def _load(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    ctx = type("Ctx", (), {})()
    ctx.provider_registry = _ProviderReg()
    ctx.tool_registry = _ToolReg()
    ctx.skill_registry = _SkillReg()
    asyncio.run(FilesPlugin().on_load(ctx))
    return ctx


# ---------------------------------------------------------------- walk


@pytest.mark.asyncio
async def test_disk_walk_returns_every_depth_parents_first(tmp_path):
    _seed(tmp_path)
    st = DiskFileStorage(root=tmp_path)
    paths = [e.path for e in await st.walk("/")]
    assert "reports/2026/q3-review.md" in paths
    assert "notes/berlin-office.md" in paths
    assert ".hidden.md" not in paths, "dotfiles stay hidden, as in list()"
    assert paths.index("reports") < paths.index("reports/2026") < paths.index("reports/2026/q3-review.md")
    sub = [e.path for e in await st.walk("reports")]
    assert set(sub) == {"reports/2026", "reports/2026/q3-review.md", "reports/summary.txt"}
    assert sub.index("reports/2026") < sub.index("reports/2026/q3-review.md")
    assert await st.walk("nope") == []


@pytest.mark.asyncio
async def test_generic_walk_composes_list_for_any_backend(tmp_path):
    _seed(tmp_path)
    disk = DiskFileStorage(root=tmp_path)

    class ListOnly(StorageBackend):
        """A backend that implements only list(): walk() must still work."""

        async def list(self, path="/"):
            return await disk.list(path)

        async def read(self, path):
            return await disk.read(path)

        async def write(self, *a, **k):
            raise NotImplementedError

        async def mkdir(self, *a, **k):
            raise NotImplementedError

        async def delete(self, *a, **k):
            raise NotImplementedError

        async def move(self, *a, **k):
            raise NotImplementedError

        async def stat(self, *a, **k):
            raise NotImplementedError

        async def exists(self, *a, **k):
            raise NotImplementedError

        async def usage(self):
            return {}

        def state(self):
            return disk.state()

    generic = sorted(e.path for e in await ListOnly().walk("/"))
    native = sorted(e.path for e in await disk.walk("/"))
    assert generic == native


# ---------------------------------------------------------------- tools


def test_file_list_recursive_flag(tmp_path, monkeypatch):
    ctx = _load(tmp_path, monkeypatch)
    lst = ctx.tool_registry.handlers["file_list"]
    top = asyncio.run(lst("/"))
    assert {e["name"] for e in top["entries"]} == {"notes", "reports", "top.md"}
    assert "recursive" not in top
    deep = asyncio.run(lst("/", recursive=True))
    assert deep["recursive"] is True
    assert "reports/2026/q3-review.md" in {e["path"] for e in deep["entries"]}
    assert deep["count"] > top["count"]
    props = ctx.tool_registry.defs["file_list"].parameters["properties"]
    assert props["recursive"]["type"] == "boolean"


def test_file_search_by_name_walks_the_whole_tree(tmp_path, monkeypatch):
    ctx = _load(tmp_path, monkeypatch)
    search = ctx.tool_registry.handlers["file_search"]
    r = asyncio.run(search("q3"))
    assert [m["path"] for m in r["matches"]] == ["reports/2026/q3-review.md"]
    assert r["matches"][0]["match"] == "name" and r["count"] == 1 and r["note"] == ""
    glob = asyncio.run(search("*.md", path="notes"))
    assert [m["path"] for m in glob["matches"]] == ["notes/berlin-office.md"]
    folder = asyncio.run(search("2026"))
    assert {m["path"] for m in folder["matches"]} == {"reports/2026", "reports/2026/q3-review.md"}


def test_file_search_in_content_greps_text_and_skips_binary(tmp_path, monkeypatch):
    ctx = _load(tmp_path, monkeypatch)
    search = ctx.tool_registry.handlers["file_search"]
    r = asyncio.run(search("berlin", in_content=True))
    paths = {m["path"]: m for m in r["matches"]}
    assert set(paths) == {"notes/berlin-office.md"}
    m = paths["notes/berlin-office.md"]
    assert m["match"] == "name+content", "name hit enriched with the content lines"
    assert m["lines"][0]["line"] == 1 and "lease" in m["lines"][0]["text"]
    r2 = asyncio.run(search("churn", in_content=True))
    assert [m["path"] for m in r2["matches"]] == ["reports/2026/q3-review.md"]
    assert r2["matches"][0]["match"] == "content" and r2["matches"][0]["line_matches"] == 1
    assert r2["files_scanned"] >= 4 and r2["truncated"] is False


def test_file_search_miss_says_so_and_hints_content(tmp_path, monkeypatch):
    ctx = _load(tmp_path, monkeypatch)
    search = ctx.tool_registry.handlers["file_search"]
    r = asyncio.run(search("pricing"))
    assert r["count"] == 0 and r["matches"] == []
    assert "try in_content=true" in r["note"]
    r2 = asyncio.run(search("pricing", in_content=True))
    assert r2["count"] == 0 and "or content" in r2["note"]
    assert asyncio.run(search("   "))["error"] == "query is required"


def test_file_search_caps_results(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_FILE_SEARCH_MAX_RESULTS", "2")
    import importlib

    import plugin_files

    importlib.reload(plugin_files)
    try:
        ctx = _load(tmp_path, monkeypatch)
        search = ctx.tool_registry.handlers["file_search"]
        r = asyncio.run(search(".md"))
        assert r["count"] == 2 and r["truncated"] is True
    finally:
        monkeypatch.delenv("LUNA_FILE_SEARCH_MAX_RESULTS")
        importlib.reload(plugin_files)


def test_search_is_ungated_and_manifest_counts_eight(tmp_path, monkeypatch):
    ctx = _load(tmp_path, monkeypatch)
    assert ctx.tool_registry.gated["file_search"] is False
    assert ctx.tool_registry.gated["file_write"] is True
    import tomllib
    from pathlib import Path

    man = tomllib.loads((Path(__file__).parents[1] / "plugin_files" / "luna-plugin.toml").read_text())
    names = [t["name"] for t in man["tools"]]
    assert man["requires"]["tools"] == len(names) == 8
    assert "file_search" in names
    assert man["version"] == "0.15.0" == FilesPlugin().manifest.version
    skill = ctx.skill_registry.defs[0]
    assert "file_search" in skill.description and "file_search" in skill.body
