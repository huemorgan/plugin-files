"""005.910 — DiskFileStorage unit tests."""

from __future__ import annotations

import pytest

from plugin_files.storage import DiskFileStorage


@pytest.fixture
def storage(tmp_path):
    return DiskFileStorage(root=tmp_path, max_bytes=1024 * 1024, max_file_bytes=10_000)


@pytest.mark.asyncio
class TestDiskFileStorage:
    async def test_mkdir_and_list(self, storage) -> None:
        await storage.mkdir("docs")
        entries = await storage.list("/")
        assert any(e.name == "docs" and e.is_dir for e in entries)

    async def test_write_and_read(self, storage) -> None:
        await storage.write("hello.txt", b"Hello World")
        content = await storage.read("hello.txt")
        assert content == b"Hello World"

    async def test_stat(self, storage) -> None:
        await storage.write("test.py", b"print('hi')")
        entry = await storage.stat("test.py")
        assert entry.name == "test.py"
        assert entry.size_bytes == 11
        assert not entry.is_dir

    async def test_delete_file(self, storage) -> None:
        await storage.write("temp.txt", b"data")
        assert await storage.exists("temp.txt")
        ok = await storage.delete("temp.txt")
        assert ok
        assert not await storage.exists("temp.txt")

    async def test_delete_dir(self, storage) -> None:
        await storage.mkdir("subdir")
        await storage.write("subdir/file.txt", b"data")
        ok = await storage.delete("subdir")
        assert ok
        assert not await storage.exists("subdir")

    async def test_move(self, storage) -> None:
        await storage.write("old.txt", b"content")
        entry = await storage.move("old.txt", "new.txt")
        assert entry.name == "new.txt"
        assert not await storage.exists("old.txt")
        assert await storage.exists("new.txt")

    async def test_path_traversal_blocked(self, storage) -> None:
        with pytest.raises(ValueError, match="traversal"):
            await storage.read("../../etc/passwd")

    async def test_file_too_large(self, storage) -> None:
        with pytest.raises(ValueError, match="too large"):
            await storage.write("big.bin", b"x" * 20_000)

    async def test_usage(self, storage) -> None:
        await storage.write("a.txt", b"hello")
        usage = await storage.usage()
        assert usage["used_bytes"] == 5
        assert usage["max_bytes"] == 1024 * 1024

    async def test_list_sorted_dirs_first(self, storage) -> None:
        await storage.write("z_file.txt", b"data")
        await storage.mkdir("a_folder")
        entries = await storage.list("/")
        assert entries[0].name == "a_folder"
        assert entries[0].is_dir
        assert entries[1].name == "z_file.txt"

    async def test_nested_write_creates_parents(self, storage) -> None:
        await storage.write("deep/nested/file.txt", b"data")
        assert await storage.exists("deep/nested/file.txt")

    async def test_read_nonexistent_raises(self, storage) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.read("nope.txt")

    async def test_mime_type_detection(self, storage) -> None:
        await storage.write("image.png", b"fakepng")
        entry = await storage.stat("image.png")
        assert entry.mime_type == "image/png"

        await storage.write("doc.pdf", b"fakepdf")
        entry = await storage.stat("doc.pdf")
        assert entry.mime_type == "application/pdf"
