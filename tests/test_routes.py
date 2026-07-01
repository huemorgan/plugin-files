"""005 — read-route helpers: HTTP Range parsing + ETag shape."""

from __future__ import annotations

from datetime import datetime, timezone

from plugin_files.routes import _etag, _parse_range
from plugin_files.storage import FileEntry


def _entry(size: int, ts: int) -> FileEntry:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return FileEntry("a.bin", "a.bin", False, size, "application/octet-stream", dt, dt)


class TestParseRange:
    def test_none_when_absent(self):
        assert _parse_range("", 100) is None
        assert _parse_range("bytes=0-10", 0) is None  # empty file

    def test_basic_range(self):
        assert _parse_range("bytes=0-99", 1000) == (0, 99)
        assert _parse_range("bytes=100-199", 1000) == (100, 199)

    def test_open_ended_range(self):
        assert _parse_range("bytes=500-", 1000) == (500, 999)

    def test_suffix_range(self):
        assert _parse_range("bytes=-200", 1000) == (800, 999)

    def test_clamped_to_size(self):
        assert _parse_range("bytes=0-99999", 1000) == (0, 999)

    def test_unsatisfiable(self):
        assert _parse_range("bytes=2000-3000", 1000) is None

    def test_only_first_of_multi_range(self):
        assert _parse_range("bytes=0-9,20-29", 1000) == (0, 9)


class TestEtag:
    def test_shape_and_stability(self):
        e = _entry(1234, 1_700_000_000)
        tag = _etag(e)
        assert tag.startswith('"') and tag.endswith('"')
        assert tag == _etag(_entry(1234, 1_700_000_000))

    def test_changes_with_bytes(self):
        assert _etag(_entry(1, 100)) != _etag(_entry(2, 100))
        assert _etag(_entry(1, 100)) != _etag(_entry(1, 200))
