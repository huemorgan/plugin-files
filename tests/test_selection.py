"""002 — backend selection: LUNA_FILES_BACKEND + `auto` resolution order."""

from __future__ import annotations

import pytest

from plugin_files.backends import make_storage_from_env

_ENV_KEYS = [
    "LUNA_FILES_BACKEND", "LUNA_FILES_ROOT", "LUNA_FILES_DURABLE",
    "LUNA_FILES_S3_BUCKET", "LUNA_FILES_S3_ACCESS_KEY_ID", "LUNA_FILES_S3_SECRET_ACCESS_KEY",
    "LUNA_FILES_S3_ENDPOINT", "LUNA_FILES_S3_PREFIX",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


class _FakeCtx:
    """Minimal ctx exposing engine + db_session_factory (truthy) for `db`."""

    def __init__(self) -> None:
        self.engine = object()
        self.db_session_factory = lambda: None


def _set_s3(monkeypatch):
    monkeypatch.setenv("LUNA_FILES_S3_BUCKET", "b")
    monkeypatch.setenv("LUNA_FILES_S3_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("LUNA_FILES_S3_SECRET_ACCESS_KEY", "s")


def test_explicit_local(monkeypatch, tmp_path):
    monkeypatch.setenv("LUNA_FILES_BACKEND", "local")
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    s = make_storage_from_env(None)
    assert s.state().backend == "local"
    assert s.state().durable is False


def test_explicit_fly_is_durable(monkeypatch, tmp_path):
    monkeypatch.setenv("LUNA_FILES_BACKEND", "fly")
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    s = make_storage_from_env(None)
    assert s.state().backend == "fly"
    assert s.state().durable is True
    assert s.state().supports_inplace_edit is True


def test_explicit_object(monkeypatch):
    monkeypatch.setenv("LUNA_FILES_BACKEND", "object")
    _set_s3(monkeypatch)
    s = make_storage_from_env(None)
    st = s.state()
    assert st.backend == "object"
    assert st.durable is True
    assert st.supports_inplace_edit is False


def test_explicit_object_without_creds_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("LUNA_FILES_BACKEND", "object")
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    s = make_storage_from_env(None)
    assert s.state().backend == "local"


def test_explicit_db(monkeypatch):
    monkeypatch.setenv("LUNA_FILES_BACKEND", "db")
    s = make_storage_from_env(_FakeCtx())
    assert s.state().backend == "db"
    assert s.state().durable is True


def test_explicit_db_without_ctx_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("LUNA_FILES_BACKEND", "db")
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    s = make_storage_from_env(None)
    assert s.state().backend == "local"


def test_auto_durable_disk_first(monkeypatch, tmp_path):
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    monkeypatch.setenv("LUNA_FILES_DURABLE", "1")
    s = make_storage_from_env(_FakeCtx())  # even with ctx, durable disk wins
    assert s.state().backend == "fly"
    assert s.state().durable is True


def test_auto_object_when_creds_present(monkeypatch):
    _set_s3(monkeypatch)
    s = make_storage_from_env(_FakeCtx())  # creds beat db in auto order
    assert s.state().backend == "object"


def test_auto_db_when_engine_present(monkeypatch):
    s = make_storage_from_env(_FakeCtx())
    assert s.state().backend == "db"


def test_auto_ephemeral_local_last(monkeypatch, tmp_path):
    # No durable flag, no creds, no ctx → ephemeral local, durable=False.
    monkeypatch.setenv("LUNA_FILES_ROOT", str(tmp_path))
    s = make_storage_from_env(None)
    assert s.state().backend == "local"
    assert s.state().durable is False
