from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database import Database
from backend.main import create_app
from backend.storage import Inbox


@pytest.fixture
def setup(tmp_path, monkeypatch):
    import backend.storage as storage

    class Clock(datetime):
        instant = datetime.fromisoformat("2026-10-24T20:59:59+00:00")

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)

    monkeypatch.setattr(storage, "datetime", Clock)
    settings = Settings(
        _env_file=None, storage_root=tmp_path / "Gelen Dosyalar", data_root=tmp_path / "data"
    )
    database = Database(settings.database_path)
    database.initialize()
    settings.storage_root.mkdir()
    return settings, database, Inbox(settings, database), Clock


def put(settings, name):
    path = settings.storage_root / name / "001/belge.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"customer document")
    return path


def test_exact_fourteen_calendar_days_at_istanbul_midnight(setup):
    settings, _, inbox, clock = setup
    older = put(settings, "2026-10-10")
    boundary = put(settings, "2026-10-11")
    recent = put(settings, "2026-10-12")
    future = put(settings, "2026-11-01")
    unexpected = put(settings, "not-a-date")
    invalid = put(settings, "2026-02-30")
    inbox.cleanup_expired()
    assert not older.parent.parent.exists()
    assert boundary.exists()
    clock.instant = datetime.fromisoformat("2026-10-24T21:00:00+00:00")
    inbox.cleanup_expired()
    assert not boundary.parent.parent.exists()
    assert all(p.exists() for p in [recent, future, unexpected, invalid])
    inbox.cleanup_expired()  # Repeating cleanup is safe.


def test_missed_cleanup_runs_on_startup_and_does_not_reset_counters(setup):
    settings, database, _, _ = setup
    old = put(settings, "2026-10-01")
    with database.connect() as connection:
        connection.execute("INSERT INTO counters VALUES ('2026-10-01', 42)")
    with TestClient(create_app(settings)):
        assert not old.parent.parent.exists()
    with database.connect() as connection:
        assert connection.execute("SELECT value FROM counters").fetchone()[0] == 42


def test_pending_delivery_date_is_preserved(setup):
    settings, database, inbox, _ = setup
    old = put(settings, "2026-10-01")
    token = database.create_session(60)["token"]
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO deliveries VALUES (?, '2026-10-01', 1, '2026-10-01/001', 'prepared')",
            (database.token_hash(token),),
        )
    inbox.cleanup_expired()
    assert old.exists()


def test_retention_never_follows_linked_paths(setup, monkeypatch, tmp_path):
    settings, _, inbox, _ = setup
    linked_day = put(settings, "2026-10-01")
    nested_link = put(settings, "2026-10-02")
    good = put(settings, "2026-10-03")
    external = tmp_path / "outside.txt"
    external.write_bytes(b"must remain")
    # Windows commonly disallows symlink creation without developer mode/admin.
    # Exercise both the platform junction checks and the containment check explicitly.
    from pathlib import Path

    original = getattr(Path, "is_junction", lambda p: False)
    monkeypatch.setattr(
        Path, "is_junction",
        lambda p: p in [linked_day.parent.parent, nested_link] or original(p),
        raising=False,
    )
    inbox.cleanup_expired()
    assert linked_day.exists() and nested_link.exists() and external.exists()
    assert not good.parent.parent.exists()
    with pytest.raises(RuntimeError, match="external"):
        inbox.check_retention_tree(external, settings.storage_root.resolve())


def test_locked_folder_is_retried_on_next_maintenance(setup, monkeypatch):
    import backend.storage as storage

    settings, _, inbox, _ = setup
    old = put(settings, "2026-10-01")
    with monkeypatch.context() as patch:
        blocked = Mock(side_effect=PermissionError("open file"))
        patch.setattr(storage.shutil, "rmtree", blocked)
        inbox.cleanup_expired()
        assert old.exists() and blocked.call_count == 1
    inbox.cleanup_expired()
    assert not old.parent.parent.exists()
