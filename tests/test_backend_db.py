"""002 — DbBackend: bytes-in-Postgres (tested on aiosqlite), durable=true."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from plugin_files.backends.db import DbBackend
from plugin_files.models import ALL_TABLES


@pytest_asyncio.fixture
async def backend(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'files.db'}")
    async with engine.begin() as conn:
        for table in ALL_TABLES:
            await conn.run_sync(table.create, checkfirst=True)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield DbBackend(sf, max_bytes=1024 * 1024, max_file_bytes=10_000)
    await engine.dispose()


@pytest.mark.asyncio
class TestDbBackend:
    async def test_write_read_roundtrip(self, backend):
        entry = await backend.write("note.txt", b"hello", mime_type="text/plain")
        assert entry.path == "note.txt"
        assert entry.size_bytes == 5
        assert await backend.read("note.txt") == b"hello"

    async def test_folder_aware_write_creates_parents(self, backend):
        await backend.write("browser/shot.png", b"\x89PNG", mime_type="image/png")
        assert await backend.exists("browser")
        entries = await backend.list("/")
        assert any(e.name == "browser" and e.is_dir for e in entries)
        kids = await backend.list("browser")
        assert [e.name for e in kids] == ["shot.png"]

    async def test_mkdir_and_list(self, backend):
        await backend.mkdir("docs")
        entries = await backend.list("/")
        assert any(e.name == "docs" and e.is_dir for e in entries)

    async def test_move_file(self, backend):
        await backend.write("old.txt", b"x")
        await backend.move("old.txt", "new.txt")
        assert not await backend.exists("old.txt")
        assert await backend.read("new.txt") == b"x"

    async def test_move_dir_rewrites_children(self, backend):
        await backend.write("a/one.txt", b"1")
        await backend.write("a/two.txt", b"2")
        await backend.move("a", "b")
        assert await backend.read("b/one.txt") == b"1"
        assert await backend.read("b/two.txt") == b"2"
        assert not await backend.exists("a/one.txt")

    async def test_delete_dir_cascades(self, backend):
        await backend.write("d/f.txt", b"x")
        assert await backend.delete("d")
        assert not await backend.exists("d/f.txt")

    async def test_usage(self, backend):
        await backend.write("a.txt", b"hello")
        usage = await backend.usage()
        assert usage["used_bytes"] == 5

    async def test_too_large_rejected(self, backend):
        with pytest.raises(ValueError, match="too large"):
            await backend.write("big.bin", b"x" * 20_000)

    async def test_traversal_rejected(self, backend):
        with pytest.raises(ValueError, match="traversal"):
            await backend.write("../escape.txt", b"x")

    async def test_read_missing_raises(self, backend):
        with pytest.raises(FileNotFoundError):
            await backend.read("nope.txt")

    async def test_list_direct_children_only(self, backend):
        # Prefix-query listing must return only direct children, not descendants.
        await backend.write("a/one.txt", b"1")
        await backend.write("a/sub/deep.txt", b"2")
        await backend.write("top.txt", b"3")
        root = {e.name for e in await backend.list("/")}
        assert root == {"a", "top.txt"}
        a_kids = {(e.name, e.is_dir) for e in await backend.list("a")}
        assert a_kids == {("one.txt", False), ("sub", True)}

    async def test_read_range_default_slice(self, backend):
        await backend.write("data.bin", b"0123456789")
        assert await backend.read_range("data.bin", 3, 6) == b"3456"

    async def test_state_is_durable(self, backend):
        st = backend.state()
        assert st.backend == "db"
        assert st.durable is True
        assert st.supports_inplace_edit is True
