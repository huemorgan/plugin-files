"""005.910 — DiskFileStorage unit tests."""

from __future__ import annotations

import asyncio
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

    async def test_two_instances_share_a_quota_decision(self, tmp_path, monkeypatch) -> None:
        first = DiskFileStorage(root=tmp_path, max_bytes=10, max_file_bytes=10)
        second = DiskFileStorage(root=tmp_path, max_bytes=10, max_file_bytes=10)
        original_usage = DiskFileStorage.usage
        ready = asyncio.Event()
        probes = 0

        async def delayed_usage(instance):
            nonlocal probes
            result = await original_usage(instance)
            probes += 1
            if probes == 2:
                ready.set()
            try:
                await asyncio.wait_for(ready.wait(), timeout=0.1)
            except TimeoutError:
                pass
            return result

        monkeypatch.setattr(DiskFileStorage, "usage", delayed_usage)
        outcomes = await asyncio.gather(first.write("one", b"123456"),
                                        second.write("two", b"abcdef"),
                                        return_exceptions=True)
        assert sum(not isinstance(x, Exception) for x in outcomes) == 1
        assert sum(isinstance(x, ValueError) for x in outcomes) == 1
        assert (await original_usage(first))["used_bytes"] == 6

    async def test_quota_lock_file_cannot_be_moved_or_deleted(self, storage) -> None:
        await storage.write("first", b"one")
        with pytest.raises(ValueError, match="Reserved"):
            await storage.delete(".luna-quota.lock")
        with pytest.raises(ValueError, match="Reserved"):
            await storage.move(".luna-quota.lock", "elsewhere")

    async def test_symlinked_quota_lock_is_not_followed(self, storage, tmp_path) -> None:
        outside = tmp_path.parent / "outside-lock-target"
        (tmp_path / ".luna-quota.lock").symlink_to(outside)
        with pytest.raises(OSError):
            await storage.write("first", b"one")
        assert not outside.exists()

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

    async def test_read_range_native_slice(self, storage) -> None:
        await storage.write("movie.bin", b"0123456789")
        assert await storage.read_range("movie.bin", 2, 5) == b"2345"
        assert await storage.read_range("movie.bin", 0, 0) == b"0"
        assert await storage.read_range("movie.bin", 8, 9) == b"89"

    async def test_read_range_missing_raises(self, storage) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.read_range("nope.bin", 0, 3)

    async def test_stream_chunks_concatenate_to_full(self, storage) -> None:
        payload = b"x" * 3000
        await storage.write("blob.bin", payload)
        collected = b"".join([chunk async for chunk in storage.stream("blob.bin", chunk_size=1024)])
        assert collected == payload

    async def test_mime_type_detection(self, storage) -> None:
        await storage.write("image.png", b"fakepng")
        entry = await storage.stat("image.png")
        assert entry.mime_type == "image/png"

        await storage.write("doc.pdf", b"fakepdf")
        entry = await storage.stat("doc.pdf")
        assert entry.mime_type == "application/pdf"
