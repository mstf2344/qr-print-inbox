import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from backend.compat import UTC


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("Database schema is newer than this application.")
            if version == 0:
                connection.execute(
                    """CREATE TABLE sessions (
                        token_hash TEXT PRIMARY KEY,
                        status TEXT NOT NULL DEFAULT 'uploading'
                            CHECK (status IN ('uploading', 'complete')),
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL
                    )"""
                )
                connection.execute("PRAGMA user_version = 1")
            if version < 2:
                connection.execute(
                    """CREATE TABLE files (
                        id TEXT PRIMARY KEY,
                        session_hash TEXT NOT NULL REFERENCES sessions(token_hash),
                        name TEXT NOT NULL,
                        name_key TEXT NOT NULL,
                        size INTEGER NOT NULL CHECK (size >= 0),
                        sha256 TEXT,
                        state TEXT NOT NULL CHECK (state IN ('pending', 'ready')),
                        UNIQUE(session_hash, name_key)
                    )"""
                )
                connection.execute(
                    "CREATE TABLE counters (date TEXT PRIMARY KEY, value INTEGER NOT NULL)"
                )
                connection.execute(
                    """CREATE TABLE deliveries (
                        session_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash),
                        date TEXT NOT NULL,
                        number INTEGER NOT NULL,
                        folder TEXT NOT NULL UNIQUE,
                        state TEXT NOT NULL CHECK (state IN ('prepared', 'complete')),
                        UNIQUE(date, number)
                    )"""
                )
                connection.execute("PRAGMA user_version = 2")

    def create_session(self, ttl_minutes: int) -> dict:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = int((now + timedelta(minutes=ttl_minutes)).timestamp())
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions (token_hash, created_at, expires_at) VALUES (?, ?, ?)",
                (self.token_hash(token), int(now.timestamp()), expires_at),
            )
        return {
            "token": token,
            "status": "uploading",
            "expires_at": datetime.fromtimestamp(expires_at, UTC),
        }

    def get_session(self, token: str) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status, expires_at FROM sessions WHERE token_hash = ?",
                (self.token_hash(token),),
            ).fetchone()
            files = connection.execute(
                "SELECT name, size FROM files "
                "WHERE session_hash = ? AND state = 'ready' ORDER BY rowid",
                (self.token_hash(token),),
            ).fetchall()
            delivery = connection.execute(
                "SELECT date, number, state FROM deliveries WHERE session_hash = ?",
                (self.token_hash(token),),
            ).fetchone()
        if row is None or row["expires_at"] <= int(datetime.now(UTC).timestamp()):
            return None
        result = {
            "status": row["status"],
            "expires_at": datetime.fromtimestamp(row["expires_at"], UTC),
            "files": [dict(file) for file in files],
        }
        if delivery and delivery["state"] == "complete":
            result.update(date=delivery["date"], customer_number=delivery["number"])
        return result

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
