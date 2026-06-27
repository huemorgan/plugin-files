"""002 — ObjectBackend: S3-compatible (Tigris/R2), exercised against moto.

Skipped automatically where boto3/moto aren't installed (the `object` extra);
CI that wants this coverage installs the `dev`/`object` extras.
"""

from __future__ import annotations

import pytest

moto = pytest.importorskip("moto")
pytest.importorskip("boto3")

from moto import mock_aws  # noqa: E402

from plugin_files.backends.object import ObjectBackend  # noqa: E402

BUCKET = "luna-tenants"


@pytest.fixture
def backend():
    with mock_aws():
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield ObjectBackend(
            bucket=BUCKET,
            access_key="test",
            secret_key="test",
            region="us-east-1",
            prefix="tenant/acme",
            max_bytes=1024 * 1024,
            max_file_bytes=10_000,
        )


@pytest.mark.asyncio
class TestObjectBackend:
    async def test_write_read_roundtrip(self, backend):
        entry = await backend.write("note.txt", b"hello", mime_type="text/plain")
        assert entry.path == "note.txt"
        assert await backend.read("note.txt") == b"hello"

    async def test_folder_aware_keys_and_list(self, backend):
        await backend.write("browser/shot.png", b"\x89PNG", mime_type="image/png")
        await backend.write("browser/two.png", b"\x89PNG")
        kids = await backend.list("browser")
        assert sorted(e.name for e in kids) == ["shot.png", "two.png"]
        top = await backend.list("/")
        assert any(e.name == "browser" and e.is_dir for e in top)

    async def test_move_copy_delete(self, backend):
        await backend.write("old.txt", b"x")
        await backend.move("old.txt", "new.txt")
        assert not await backend.exists("old.txt")
        assert await backend.read("new.txt") == b"x"

    async def test_delete_prefix(self, backend):
        await backend.write("d/a.txt", b"1")
        await backend.write("d/b.txt", b"2")
        assert await backend.delete("d")
        assert not await backend.exists("d/a.txt")

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

    async def test_state_object_not_inplace(self, backend):
        st = backend.state()
        assert st.backend == "object"
        assert st.durable is True
        assert st.supports_inplace_edit is False
