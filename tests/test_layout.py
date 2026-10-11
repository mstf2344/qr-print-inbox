from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.config import Settings
from backend.database import Database
from backend.supervisor import InstanceLock
from scripts.migrate_layout import migrate


def setup_layout(tmp_path):
    settings = Settings(
        _env_file=None, storage_root=tmp_path / "Gelen Dosyalar", data_root=tmp_path / "data"
    )
    database = Database(settings.database_path)
    database.initialize()
    old = tmp_path / "Gelen_Dosyalar"
    day = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    folder = old / day / "001_12-34-56"
    folder.mkdir(parents=True)
    (folder / "belge.pdf").write_bytes(b"customer bytes")
    token = database.create_session(60)["token"]
    with database.connect() as connection:
        connection.execute("INSERT INTO counters VALUES (?, ?)", (day, 1))
        connection.execute(
            "INSERT INTO deliveries VALUES (?, ?, 1, ?, 'complete')",
            (database.token_hash(token), day, f"{day}/001_12-34-56"),
        )
    temp = tmp_path / ".Gelen_Dosyalar-temporary" / ("a" * 64) / "ready"
    temp.mkdir(parents=True)
    (temp / "bekleyen.png").write_bytes(b"pending bytes")
    return settings, database, old, day


def test_migration_preserves_customer_bytes_pending_sessions_and_counters(tmp_path):
    settings, database, old, day = setup_layout(tmp_path)
    assert migrate(settings, old) == 1
    assert (settings.storage_root / day / "001/belge.pdf").read_bytes() == b"customer bytes"
    pending = settings.temporary_root / ("a" * 64) / "ready/bekleyen.png"
    assert pending.read_bytes() == b"pending bytes"
    with database.connect() as connection:
        assert connection.execute("SELECT folder FROM deliveries").fetchone()[0] == f"{day}/001"
        assert connection.execute("SELECT value FROM counters").fetchone()[0] == 1
    assert not old.exists()
    assert not (tmp_path / ".Gelen_Dosyalar-temporary").exists()
    assert migrate(settings, old) == 0


def test_migration_rejects_collisions_without_moving_any_customer_files(tmp_path):
    settings, _, old, day = setup_layout(tmp_path)
    (old / day / "001_23-45-00").mkdir()
    with pytest.raises(ValueError, match="collision"):
        migrate(settings, old)
    assert (old / day / "001_12-34-56/belge.pdf").exists()
    assert not settings.storage_root.exists()


def test_migration_replays_folder_rename_after_interruption(tmp_path):
    settings, database, old, day = setup_layout(tmp_path)
    old.rename(settings.storage_root)
    (settings.storage_root / day / "001_12-34-56").rename(settings.storage_root / day / "001")
    assert migrate(settings, old) == 0
    with database.connect() as connection:
        assert connection.execute("SELECT folder FROM deliveries").fetchone()[0] == f"{day}/001"


def test_migration_refuses_a_running_backend(tmp_path):
    settings, _, old, _ = setup_layout(tmp_path)
    lock = old.parent / ".Gelen_Dosyalar-temporary/.instance.lock"
    with InstanceLock(lock):
        with pytest.raises(OSError):
            migrate(settings, old)
    assert old.exists()
    assert not settings.storage_root.exists()
