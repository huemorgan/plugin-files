"""001 — the /share route: guards before publishing, honest expiry after.

Sharing puts a document on the public internet, so the guards (directory, size
cap, non-text) matter more than the happy path. md.page itself is stubbed —
we assert on what we send it and what we hand back, not on their uptime.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import plugin_files.routes as routes_mod
from plugin_files.storage import FileEntry

NOW = datetime.now(tz=timezone.utc)


class FakeStorage:
    """Just the two methods /share touches."""

    def __init__(self, files: dict[str, bytes], dirs: tuple[str, ...] = ()):
        self.files = files
        self.dirs = dirs
        self.reads: list[str] = []

    async def stat(self, path: str) -> FileEntry:
        if path in self.dirs:
            return FileEntry(path, path.split("/")[-1], True, None, None, NOW, NOW)
        if path not in self.files:
            raise FileNotFoundError(path)
        raw = self.files[path]
        return FileEntry(path, path.split("/")[-1], False, len(raw), "text/markdown", NOW, NOW)

    async def read(self, path: str) -> bytes:
        self.reads.append(path)
        return self.files[path]


@pytest.fixture
def client(monkeypatch):
    """Factory: (storage, transport) -> TestClient over this plugin's router."""

    def build(storage, transport=None):
        monkeypatch.setattr(routes_mod, "make_storage_from_env", lambda ctx: storage)
        if transport is not None:
            real = httpx.AsyncClient
            monkeypatch.setattr(
                httpx, "AsyncClient",
                lambda *a, **kw: real(*a, **{**kw, "transport": transport}),
            )
        app = FastAPI()
        routes_mod.register_routes(app, ctx=None)
        return TestClient(app)

    return build


def md_page_stub(status=201, payload=None, seen=None):
    default = {"url": "https://md.page/abc123", "expires_at": "2026-08-06T10:00:00Z"}

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=default if payload is None else payload)

    return httpx.MockTransport(handler)


class TestShareGuards:
    def test_path_required(self, client):
        c = client(FakeStorage({}))
        assert c.post("/api/p/plugin-files/share", json={}).status_code == 400

    def test_missing_file_is_404(self, client):
        c = client(FakeStorage({}))
        assert c.post("/api/p/plugin-files/share", json={"path": "nope.md"}).status_code == 404

    def test_directory_refused(self, client):
        c = client(FakeStorage({}, dirs=("docs",)))
        assert c.post("/api/p/plugin-files/share", json={"path": "docs"}).status_code == 400

    def test_oversized_refused_without_reading_the_bytes(self, client):
        store = FakeStorage({"big.md": b"x" * (routes_mod.SHARE_MAX_BYTES + 1)})
        c = client(store)
        assert c.post("/api/p/plugin-files/share", json={"path": "big.md"}).status_code == 413
        assert store.reads == []

    def test_binary_refused(self, client):
        c = client(FakeStorage({"logo.png": b"\x89PNG\r\n\x1a\n\xff\xfe"}))
        assert c.post("/api/p/plugin-files/share", json={"path": "logo.png"}).status_code == 400


class TestSharePublish:
    def test_sends_markdown_and_returns_link_with_expiry(self, client):
        seen: list[httpx.Request] = []
        c = client(FakeStorage({"notes.md": b"# Hello\n\nworld"}), md_page_stub(seen=seen))
        r = c.post("/api/p/plugin-files/share", json={"path": "notes.md"})
        assert r.status_code == 200
        body = r.json()
        assert body["url"] == "https://md.page/abc123"
        # The expiry is passed through untouched — the UI has to be able to say
        # when the link dies rather than let the owner assume permanence.
        assert body["expires_at"] == "2026-08-06T10:00:00Z"
        assert len(seen) == 1
        assert str(seen[0].url) == routes_mod.MD_PAGE_API
        assert json.loads(seen[0].read()) == {"markdown": "# Hello\n\nworld"}

    def test_upstream_failure_is_502_not_500(self, client):
        c = client(FakeStorage({"notes.md": b"# Hi"}), md_page_stub(status=500, payload={}))
        assert c.post("/api/p/plugin-files/share", json={"path": "notes.md"}).status_code == 502


class TestVersionStamps:
    """A version that lives in four places has to agree in all four."""

    ROOT = Path(__file__).resolve().parents[1]

    def _grep(self, rel: str, pattern: str) -> str:
        m = re.search(pattern, (self.ROOT / rel).read_text())
        assert m, f"no version found in {rel}"
        return m.group(1)

    def test_all_stamps_agree(self):
        pyproject = self._grep("pyproject.toml", r'(?m)^version\s*=\s*"([^"]+)"')
        manifest = self._grep("plugin_files/luna-plugin.toml", r'(?m)^version\s*=\s*"([^"]+)"')
        in_code = self._grep("plugin_files/__init__.py", r'version="([^"]+)"')
        assert pyproject == manifest == in_code

    def test_ui_footer_matches(self):
        """The footer label is what a user reads to know what they're running."""
        version = self._grep("plugin_files/__init__.py", r'version="([^"]+)"')
        html = (self.ROOT / "plugin_files/ui/index.html").read_text()
        assert f'class="version">v{version}<' in html
