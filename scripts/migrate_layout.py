"""Offline, repeatable migration of the previous inbox layout without deleting files."""

import re
from datetime import date
from pathlib import Path

from backend.config import Settings
from backend.database import Database
from backend.supervisor import InstanceLock, runtime_root
from scripts.manage import running

LEGACY_NUMBER = re.compile(r"([0-9]{3,})_[0-9]{2}-[0-9]{2}-[0-9]{2}")


def unlinked_tree(root):
    if root.is_symlink() or root.is_junction():
        raise ValueError("Linked directories cannot be migrated.")
    if root.exists():
        for child in root.iterdir():
            if child.is_symlink() or child.is_junction():
                raise ValueError("Linked paths cannot be migrated.")
            if child.is_dir():
                unlinked_tree(child)


def migrate(settings, previous_root):
    previous_root = Path(previous_root).absolute()
    previous_temp = previous_root.parent / ("." + previous_root.name + "-temporary")
    if running(runtime_root(settings)):
        raise RuntimeError("Stop the service before migrating folders.")
    if previous_root == settings.storage_root:
        raise ValueError("Old and new storage must differ.")
    if previous_root.exists() and settings.storage_root.exists():
        raise ValueError("Both inbox roots exist; no files were overwritten.")
    if previous_temp.exists() and settings.temporary_root.exists():
        old_names = {p.name for p in previous_temp.iterdir()} - {".instance.lock"}
        new_names = {p.name for p in settings.temporary_root.iterdir()} - {".instance.lock"}
        if old_names & new_names:
            raise ValueError("Temporary session collision; no files were overwritten.")
    source = previous_root if previous_root.exists() else settings.storage_root
    for root in [source, previous_temp, settings.temporary_root]:
        unlinked_tree(root)
    changes = []
    if source.exists():
        for day in source.iterdir():
            if not day.is_dir() or date.fromisoformat(day.name).isoformat() != day.name:
                raise ValueError("Unexpected inbox date folder.")
            targets = set()
            for folder in day.iterdir():
                match = LEGACY_NUMBER.fullmatch(folder.name)
                number = match[1] if match else folder.name
                if not folder.is_dir() or not re.fullmatch(r"[0-9]{3,}", number):
                    raise ValueError("Unexpected delivery folder.")
                if number in targets:
                    raise ValueError("Delivery number collision; no files were overwritten.")
                targets.add(number)
                if match:
                    changes.append((Path(day.name) / folder.name, Path(day.name) / number))
    # Lock the old backend as well as the new backend, including manual launches.
    with (
        InstanceLock(previous_temp / ".instance.lock"),
        InstanceLock(settings.temporary_root / ".instance.lock"),
    ):
        if source.exists() and source.stat().st_dev != settings.temporary_root.stat().st_dev:
            raise ValueError("Temporary and customer storage must use the same filesystem.")
        if previous_root.exists():
            previous_root.rename(settings.storage_root)
        # Move sessions individually; the two lock files stay in place until unlocked.
        for entry in previous_temp.iterdir():
            if entry.name != ".instance.lock":
                target = settings.temporary_root / entry.name
                if target.exists():
                    raise ValueError("Temporary session collision.")
                entry.rename(target)
        for old, new in changes:
            (settings.storage_root / old).rename(settings.storage_root / new)
        database = Database(settings.database_path)
        with database.connect() as connection:
            rows = connection.execute("SELECT session_hash, folder FROM deliveries").fetchall()
            for row in rows:
                folder = Path(row["folder"])
                match = LEGACY_NUMBER.fullmatch(folder.name)
                if match:
                    connection.execute(
                        "UPDATE deliveries SET folder = ? WHERE session_hash = ?",
                        ((folder.parent / match[1]).as_posix(), row["session_hash"]),
                    )
    (previous_temp / ".instance.lock").unlink()
    previous_temp.rmdir()
    return len(changes)


def main():
    settings = Settings()
    old = settings.storage_root.with_name("Gelen_Dosyalar")
    count = migrate(settings, old)
    print(f"Inbox layout migrated: {count} delivery folders. Files and counters preserved.")


if __name__ == "__main__":
    main()
