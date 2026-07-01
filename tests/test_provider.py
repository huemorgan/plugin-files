"""001 — FilesStorageProvider: StorageProvider contract + folder-aware mapping."""

from __future__ import annotations

import asyncio

import pytest

from plugin_files.provider import FilesStorageProvider, _clean_ref
from plugin_files.storage import DiskFileStorage


@pytest.fixture
def provider(tmp_path):
    store = DiskFileStorage(root=tmp_path, max_bytes=1024 * 1024, max_file_bytes=10_000)
    return FilesStorageProvider(store)


@pytest.mark.asyncio
class TestFilesStorageProvider:
    async def test_save_read_roundtrip(self, provider) -> None:
        stored = await provider.save(b"hello", filename="note.txt", media_type="text/plain")
        assert stored.ref == "note.txt"
        assert stored.filename == "note.txt"
        assert stored.media_type == "text/plain"
        assert stored.size_bytes == 5
        assert await provider.read(stored.ref) == b"hello"

    async def test_folder_aware_filename(self, provider) -> None:
        # The headline of plan 001: a path-bearing filename lands in that subfolder.
        stored = await provider.save(b"\x89PNG", filename="browser/shot-ab12.png", media_type="image/png")
        assert stored.ref == "browser/shot-ab12.png"
        assert stored.filename == "shot-ab12.png"
        assert stored.url == "/api/p/plugin-files/read/browser/shot-ab12.png"
        assert await provider.read("browser/shot-ab12.png") == b"\x89PNG"

    async def test_url_for_matches_read_route(self, provider) -> None:
        assert provider.url_for("browser/x.png") == "/api/p/plugin-files/read/browser/x.png"
        assert provider.url_for("/leading.png") == "/api/p/plugin-files/read/leading.png"

    async def test_leading_slash_normalized(self, provider) -> None:
        stored = await provider.save(b"x", filename="/attachments/a.bin", media_type="application/octet-stream")
        assert stored.ref == "attachments/a.bin"

    async def test_traversal_rejected(self, provider) -> None:
        with pytest.raises(ValueError):
            await provider.save(b"x", filename="../../etc/passwd", media_type="text/plain")

    async def test_media_type_defaults_from_extension(self, provider) -> None:
        stored = await provider.save(b"x", filename="browser/x.png")
        assert stored.media_type == "image/png"


def test_clean_ref_rejects_empty() -> None:
    for bad in ("", "   ", "/", "dir/"):
        with pytest.raises(ValueError):
            _clean_ref(bad)
    assert _clean_ref("a/b.txt") == "a/b.txt"
    assert _clean_ref("\\win\\path.txt") == "win/path.txt"


# ---------------- registration under "storage" ----------------
class _FakeRegistry:
    """Mirrors luna.providers.registry.ProviderRegistry (has/register/replace)."""

    def __init__(self) -> None:
        self._impls: dict[str, object] = {}

    def has(self, key: str) -> bool:
        return key in self._impls

    def register(self, key: str, impl: object) -> None:
        if key in self._impls:
            raise RuntimeError("two impls")
        self._impls[key] = impl

    def replace(self, key: str, impl: object) -> None:
        self._impls[key] = impl

    def get(self, key: str, _type=None):
        return self._impls[key]


class _Ctx:
    def __init__(self, registry) -> None:
        self.provider_registry = registry

        class _ToolReg:
            def register(self, *_a, **_k):
                pass

        self.tool_registry = _ToolReg()


def test_on_load_registers_storage_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    from plugin_files import FilesPlugin

    reg = _FakeRegistry()
    asyncio.run(FilesPlugin().on_load(_Ctx(reg)))
    assert reg.has("storage")
    assert isinstance(reg.get("storage"), FilesStorageProvider)


def test_on_load_replaces_existing_storage_provider(tmp_path, monkeypatch) -> None:
    # A reload must not trip the registry's "two impls" guard.
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    from plugin_files import FilesPlugin

    reg = _FakeRegistry()
    reg.register("storage", object())
    asyncio.run(FilesPlugin().on_load(_Ctx(reg)))
    assert isinstance(reg.get("storage"), FilesStorageProvider)


def test_manifest_declares_storage_provider() -> None:
    from plugin_files import FilesPlugin

    assert FilesPlugin.manifest.provider == "storage"
    assert FilesPlugin.manifest.version == "0.7.0"
