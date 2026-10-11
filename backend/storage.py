import logging
import os
import re
import secrets
import shutil
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from backend.compat import UTC, ZoneInfo, file_digest, is_junction, is_relative_to
from backend.config import Settings
from backend.database import Database
from backend.validation import InboxError, safe_name, validate_content


class Inbox:
    def __init__(self, config: Settings, database: Database):
        self.config = config
        self.database = database
        self.finalize_lock = threading.Lock()
        self.instance_file = None

    def start(self):
        self.config.storage_root.mkdir(parents=True, exist_ok=True)
        self.config.temporary_root.mkdir(parents=True, exist_ok=True)
        if self.config.storage_root.stat().st_dev != self.config.temporary_root.stat().st_dev:
            raise RuntimeError("Temporary and final storage must use the same filesystem.")
        self.instance_file = (self.config.temporary_root / ".instance.lock").open("a+b")
        self.instance_file.seek(0, 2)
        if self.instance_file.tell() == 0:
            self.instance_file.write(b"0")
            self.instance_file.flush()
        self.instance_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.instance_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.instance_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.recover()
            self.cleanup_expired()
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.instance_file is not None:
            self.instance_file.close()
            self.instance_file = None

    def session(self, connection, session_hash):
        row = connection.execute(
            "SELECT * FROM sessions WHERE token_hash = ?", (session_hash,)
        ).fetchone()
        if row is None or row["expires_at"] <= int(datetime.now(UTC).timestamp()):
            raise InboxError(404, "Oturum bulunamadı veya süresi doldu.")
        return row

    def paths(self, session_hash: str):
        root = self.config.temporary_root / session_hash
        return root / "parts", root / "ready"

    def check_disk(self, required=0):
        free = shutil.disk_usage(self.config.temporary_root).free
        if free < self.config.min_free_disk_mb * 1024 * 1024 + required:
            raise InboxError(507, "Dosya kabul etmek için yeterli disk alanı yok.")

    def reserve(self, token: str, filename: str) -> dict:
        session_hash = self.database.token_hash(token)
        name = safe_name(filename, set(self.config.allowed_extensions.split(",")))
        self.check_disk()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.session(connection, session_hash)
            active = connection.execute(
                "SELECT COUNT(*) FROM files WHERE state = 'pending'"
            ).fetchone()[0]
            if active >= self.config.max_active_uploads:
                raise InboxError(429, "Diğer yüklemeler bitince tekrar deneyin.")
            if connection.execute(
                "SELECT 1 FROM deliveries WHERE session_hash = ?", (session_hash,)
            ).fetchone():
                raise InboxError(409, "Tamamlanan teslimlere dosya eklenemez.")
            rows = connection.execute(
                "SELECT name_key, size FROM files WHERE session_hash = ?", (session_hash,)
            ).fetchall()
            if len(rows) >= self.config.max_files_per_session:
                raise InboxError(413, "Oturum için dosya sayısı sınırına ulaşıldı.")
            remaining = self.config.max_session_size_mb * 1024 * 1024 - sum(
                row["size"] for row in rows
            )
            capacity = min(self.config.max_file_size_mb * 1024 * 1024, remaining)
            if capacity <= 0:
                raise InboxError(413, "Oturumun toplam dosya boyutu sınırına ulaşıldı.")
            occupied = {row["name_key"] for row in rows}
            stem, suffix = Path(name).stem, Path(name).suffix
            index = 2
            while name.casefold() in occupied:
                name = f"{stem}_{index}{suffix}"
                index += 1
            file_id = secrets.token_hex(16)
            parts, ready = self.paths(session_hash)
            parts.mkdir(parents=True, exist_ok=True)
            ready.mkdir(parents=True, exist_ok=True)
            connection.execute(
                """INSERT INTO files (id, session_hash, name, name_key, size, state)
                VALUES (?, ?, ?, ?, ?, 'pending')""",
                (file_id, session_hash, name, name.casefold(), capacity),
            )
        return {
            "id": file_id,
            "name": name,
            "session_hash": session_hash,
            "capacity": capacity,
            "part": parts / (file_id + ".part"),
            "ready": ready / name,
        }

    def accept(self, reservation: dict, size: int, digest: str):
        if size == 0:
            raise InboxError(422, "Boş dosya yüklenemez.")
        validate_content(reservation["part"], reservation["name"])
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.session(connection, reservation["session_hash"])
            reservation["part"].rename(reservation["ready"])
            connection.execute(
                "UPDATE files SET size = ?, sha256 = ?, state = 'ready' WHERE id = ?",
                (size, digest, reservation["id"]),
            )
        return {"name": reservation["name"], "size": size, "status": "ready"}

    def discard(self, reservation: dict):
        # Only generated paths from this reservation are removed.
        reservation["part"].unlink(missing_ok=True)
        reservation["ready"].unlink(missing_ok=True)
        with self.database.connect() as connection:
            connection.execute("DELETE FROM files WHERE id = ?", (reservation["id"],))

    def finalize(self, token: str) -> dict:
        session_hash = self.database.token_hash(token)
        with self.finalize_lock:
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self.session(connection, session_hash)
                delivery = connection.execute(
                    "SELECT * FROM deliveries WHERE session_hash = ?", (session_hash,)
                ).fetchone()
                if delivery and delivery["state"] == "complete":
                    return self.receipt(delivery)
                if delivery is None:
                    files = connection.execute(
                        "SELECT * FROM files WHERE session_hash = ?", (session_hash,)
                    ).fetchall()
                    if not files:
                        raise InboxError(422, "Önce en az bir dosya yükleyin.")
                    if any(file["state"] != "ready" for file in files):
                        raise InboxError(409, "Devam eden yüklemenin tamamlanmasını bekleyin.")
                    now = datetime.now(ZoneInfo(self.config.timezone))
                    date = now.date().isoformat()
                    counter = connection.execute(
                        "SELECT value FROM counters WHERE date = ?", (date,)
                    ).fetchone()
                    number = counter["value"] + 1 if counter else 1
                    while True:
                        folder = f"{date}/{number:03d}"
                        if not (self.config.storage_root / folder).exists():
                            break
                        number += 1
                    connection.execute(
                        "INSERT INTO counters VALUES (?, ?) "
                        "ON CONFLICT(date) DO UPDATE SET value = ?",
                        (date, number, number),
                    )
                    connection.execute(
                        "INSERT INTO deliveries VALUES (?, ?, ?, ?, 'prepared')",
                        (session_hash, date, number, folder),
                    )
                    delivery = connection.execute(
                        "SELECT * FROM deliveries WHERE session_hash = ?", (session_hash,)
                    ).fetchone()
            # A durable intent precedes the atomic directory rename. A crash can be replayed.
            self.finish_delivery(delivery)
            return self.receipt(delivery)

    @staticmethod
    def receipt(delivery) -> dict:
        return {
            "status": "complete",
            "customer_number": delivery["number"],
            "date": delivery["date"],
        }

    def finish_delivery(self, delivery):
        session_hash = delivery["session_hash"]
        _, ready = self.paths(session_hash)
        target = self.config.storage_root / delivery["folder"]
        if ready.exists() and target.exists():
            raise InboxError(503, "Teslim klasörü çakışıyor; personel kontrolü gerekiyor.")
        source = ready if ready.exists() else target
        with self.database.connect() as connection:
            files = connection.execute(
                "SELECT name, size, sha256 FROM files WHERE session_hash = ? AND state = 'ready'",
                (session_hash,),
            ).fetchall()
        if not source.is_dir() or {file.name for file in source.iterdir()} != {
            row["name"] for row in files
        }:
            raise InboxError(503, "Teslim dosyaları eksik; personel kontrolü gerekiyor.")
        for row in files:
            path = source / row["name"]
            with path.open("rb") as content:
                digest = file_digest(content).hexdigest()
            if path.stat().st_size != row["size"] or digest != row["sha256"]:
                raise InboxError(503, "Teslim dosyası doğrulanamadı; personel kontrolü gerekiyor.")
        if source == ready:
            target.parent.mkdir(parents=True, exist_ok=True)
            ready.rename(target)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE deliveries SET state = 'complete' WHERE session_hash = ?", (session_hash,)
            )
            connection.execute(
                "UPDATE sessions SET status = 'complete' WHERE token_hash = ?", (session_hash,)
            )

    def recover(self):
        with self.database.connect() as connection:
            pending = connection.execute("SELECT * FROM files WHERE state = 'pending'").fetchall()
            deliveries = connection.execute(
                "SELECT * FROM deliveries WHERE state = 'prepared'"
            ).fetchall()
        for row in pending:
            parts, ready = self.paths(row["session_hash"])
            self.discard(
                {
                    "id": row["id"],
                    "part": parts / (row["id"] + ".part"),
                    "ready": ready / row["name"],
                }
            )
        for delivery in deliveries:
            self.finish_delivery(delivery)

    def cleanup_expired(self):
        # Serialize with delivery preparation; active/prepared uploads stay intact.
        # A crash leaves a retryable expired record or date folder.
        with self.finalize_lock, self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT token_hash FROM sessions WHERE expires_at <= ? "
                "AND token_hash NOT IN (SELECT session_hash FROM files WHERE state = 'pending') "
                "AND token_hash NOT IN "
                "(SELECT session_hash FROM deliveries WHERE state = 'prepared')",
                (int(datetime.now(UTC).timestamp()),),
            ).fetchall()
            for row in rows:
                session_hash = row["token_hash"]
                if len(session_hash) != 64 or any(
                    c not in "0123456789abcdef" for c in session_hash
                ):
                    raise RuntimeError("Invalid temporary session path.")
                target = self.config.temporary_root / session_hash
                if target.is_symlink() or is_junction(target):
                    raise RuntimeError("Temporary session must not be a linked directory.")
                if target.exists():
                    shutil.rmtree(target)
                connection.execute("DELETE FROM files WHERE session_hash = ?", (session_hash,))
                connection.execute("DELETE FROM deliveries WHERE session_hash = ?", (session_hash,))
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (session_hash,))
            self.cleanup_old_days(connection)

    def cleanup_old_days(self, connection):
        cutoff = datetime.now(ZoneInfo(self.config.timezone)).date() - timedelta(days=14)
        prepared = {
            row[0]
            for row in connection.execute("SELECT date FROM deliveries WHERE state = 'prepared'")
        }
        root = self.config.storage_root
        if root.is_symlink() or is_junction(root):
            raise RuntimeError("Customer storage must not be a linked directory.")
        for day in root.iterdir():
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day.name):
                continue
            try:
                folder_date = date.fromisoformat(day.name)
            except ValueError:
                continue
            if folder_date > cutoff or day.name in prepared:
                continue
            # Do not follow Windows junctions/symlinks, including nested entries.
            # Validate the resolved target before any recursive deletion.
            try:
                self.check_retention_tree(day, root.resolve())
                if day.is_dir():
                    shutil.rmtree(day)
            except (OSError, RuntimeError):
                logging.getLogger(__name__).error("Date folder cleanup needs staff attention.")

    @classmethod
    def check_retention_tree(cls, path, root):
        if path.is_symlink() or is_junction(path) or not is_relative_to(path.resolve(), root):
            raise RuntimeError("Retention cannot remove linked or external paths.")
        if path.is_dir():
            for child in path.iterdir():
                cls.check_retention_tree(child, root)
