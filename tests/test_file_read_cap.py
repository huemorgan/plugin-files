"""046 phase01 — file_read inline cap + offset/limit/search slicing.

A large file must never land raw in history: a whole-file read over the cap
returns a bounded head+tail preview + a pointer, and the model re-fetches the
exact part with offset/limit (line range) or search (grep). Small files are
unchanged.
"""

from __future__ import annotations

import asyncio

import pytest

import plugin_files as files_init
from plugin_files import FilesPlugin


class _ToolReg:
    """Capture registered tool handlers by name (ungated path — no skill_registry)."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def register(self, _plugin, defn, handler, **_kw) -> None:
        self.handlers[defn.name] = handler


class _ProviderReg:
    def __init__(self) -> None:
        self._impls: dict[str, object] = {}

    def has(self, key: str) -> bool:
        return key in self._impls

    def register(self, key: str, impl: object) -> None:
        self._impls[key] = impl

    def replace(self, key: str, impl: object) -> None:
        self._impls[key] = impl

    def get(self, key: str, _type=None):
        return self._impls[key]


class _Ctx:
    def __init__(self) -> None:
        self.provider_registry = _ProviderReg()
        self.tool_registry = _ToolReg()
        # No skill_registry attribute → tools register ungated, handlers captured.


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    ctx = _Ctx()
    asyncio.run(FilesPlugin().on_load(ctx))
    return ctx.tool_registry.handlers


def _write(tools, path: str, content: str) -> None:
    asyncio.run(tools["file_write"](path=path, content=content))


def test_small_file_returns_full_content(tools) -> None:
    _write(tools, "/small.txt", "hello\nworld\n")
    out = asyncio.run(tools["file_read"](path="/small.txt"))
    assert out["content"] == "hello\nworld\n"
    assert "truncated" not in out
    assert out["total_lines"] == 2


def test_large_file_previews_head_tail_not_full_body(tools) -> None:
    cap = files_init._READ_CHAR_CAP
    body = "\n".join(f"line-{i:05d} " + "x" * 40 for i in range(2000))
    assert len(body) > cap
    _write(tools, "/big.txt", body)
    out = asyncio.run(tools["file_read"](path="/big.txt"))
    assert out.get("truncated") is True
    assert "content" not in out  # full body never returned raw
    assert out["preview_head"].startswith("line-00000")
    assert out["preview_tail"].endswith("x")
    assert len(out["preview_head"]) + len(out["preview_tail"]) <= cap
    assert "offset" in out["note"] and "search" in out["note"]
    assert out["size_bytes"] == len(body)


def test_offset_limit_returns_exact_slice(tools) -> None:
    body = "\n".join(f"L{i}" for i in range(1, 101))  # L1..L100
    _write(tools, "/lines.txt", body)
    out = asyncio.run(tools["file_read"](path="/lines.txt", offset=10, limit=3))
    assert out["content"] == "L10\nL11\nL12"
    assert out["offset"] == 10
    assert out["returned_lines"] == 3
    assert out["total_lines"] == 100


def test_search_returns_matching_lines_only(tools) -> None:
    body = "alpha\nbeta needle\ngamma\ndelta needle\n"
    _write(tools, "/s.txt", body)
    out = asyncio.run(tools["file_read"](path="/s.txt", search="needle"))
    assert out["match_count"] == 2
    assert [m["line"] for m in out["matches"]] == [2, 4]
    assert out["truncated"] is False
    assert all("needle" in m["text"] for m in out["matches"])


def test_search_caps_match_count(tools, monkeypatch) -> None:
    monkeypatch.setattr(files_init, "_SEARCH_MAX_MATCHES", 5)
    body = "\n".join("needle " + str(i) for i in range(50))
    _write(tools, "/many.txt", body)
    out = asyncio.run(tools["file_read"](path="/many.txt", search="needle"))
    assert out["match_count"] == 50
    assert len(out["matches"]) == 5
    assert out["truncated"] is True
