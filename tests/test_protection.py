import hashlib
import io

import anyio
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.config import Settings
from backend.database import Database
from backend.main import create_app
from backend.protection import Protection
from backend.storage import Inbox
from backend.validation import InboxError


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, storage_root=tmp_path / "inbox", data_root=tmp_path / "data")


def test_gateway_auth_and_forwarded_ip_cannot_be_spoofed(settings):
    settings.gateway_secret = "a" * 40
    # Assignment is intentionally converted by constructing settings again.
    settings = Settings(_env_file=None, **settings.model_dump())
    headers = {"x-inbox-gateway": "a" * 40, "x-inbox-client-ip": "192.0.2.1"}
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/sessions").status_code == 403
        assert (
            client.post("/api/v1/sessions", headers={"x-inbox-client-ip": "192.0.2.1"}).status_code
            == 403
        )
        assert client.post("/api/v1/sessions", headers=headers).status_code == 201
        assert (
            client.get("/healthz", headers={**headers, "x-inbox-client-ip": "bad"}).status_code
            == 403
        )


def test_rate_limit_survives_restart_and_does_not_store_ip(settings):
    settings.sessions_per_minute = 1
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/sessions").status_code == 201
        assert client.post("/api/v1/sessions").status_code == 429
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/sessions")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
    with Database(settings.database_path).connect() as connection:
        keys = [row[0] for row in connection.execute("SELECT key FROM limits")]
        assert all("testclient" not in key for key in keys)


def test_daily_budget_durable_and_includes_rejected_files(settings):
    settings.daily_upload_mb = 1
    with TestClient(create_app(settings)) as client:
        token = client.post("/api/v1/sessions").json()["token"]
        response = client.post(
            f"/api/v1/sessions/{token}/files",
            content=b"x" * 1048576,
            headers={"Content-Type": "application/octet-stream", "X-File-Name": "bad.png"},
        )
        assert response.status_code == 415
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                f"/api/v1/sessions/{token}/files",
                content=b"x",
                headers={"Content-Type": "application/octet-stream", "X-File-Name": "bad.png"},
            ).status_code
            == 429
        )
        assert not list(settings.temporary_root.rglob("*.part"))


def test_daily_session_quota_and_minute_reset(settings, monkeypatch):
    from backend import protection

    settings.sessions_per_minute = 1
    settings.sessions_per_day = 2
    now = protection.time.time()
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/sessions").status_code == 201
        monkeypatch.setattr(protection.time, "time", lambda: now + 120)
        assert client.post("/api/v1/sessions").status_code == 201
        monkeypatch.setattr(protection.time, "time", lambda: now + 240)
        assert client.post("/api/v1/sessions").status_code == 429


def test_cleanup_retains_completed_folders_and_active_uploads(settings):
    database = Database(settings.database_path)
    database.initialize()
    inbox = Inbox(settings, database)
    inbox.start()
    try:
        complete, expired, active = [database.create_session(60)["token"] for _ in range(3)]
        for token in [complete, expired]:
            item = inbox.reserve(token, "test.png")
            buffer = io.BytesIO()
            Image.new("RGB", (8, 8)).save(buffer, "PNG")
            content = buffer.getvalue()
            item["part"].write_bytes(content)
            inbox.accept(item, len(content), hashlib.sha256(content).hexdigest())
        inbox.finalize(complete)
        pending = inbox.reserve(active, "test.png")
        pending["part"].write_bytes(b"unfinished")
        with database.connect() as connection:
            connection.execute("UPDATE sessions SET expires_at = 0")
        inbox.cleanup_expired()
        assert len(list(settings.storage_root.rglob("*.png"))) == 1
        assert not inbox.paths(database.token_hash(expired))[1].exists()
        assert pending["part"].exists()
    finally:
        inbox.stop()


def test_concurrent_upload_admission_and_timeout_cleanup(settings, monkeypatch):
    from starlette.requests import Request

    settings.max_active_uploads = 1
    database = Database(settings.database_path)
    database.initialize()
    inbox = Inbox(settings, database)
    inbox.start()
    try:
        token = database.create_session(60)["token"]
        reservation = inbox.reserve(token, "test.png")
        with pytest.raises(InboxError, match="Diğer"):
            inbox.reserve(token, "other.png")
        inbox.discard(reservation)
    finally:
        inbox.stop()
    settings.upload_timeout_seconds = 0.03

    async def slow_stream(self):
        yield b"partial"
        await anyio.sleep(1)

    with TestClient(create_app(settings)) as client:
        monkeypatch.setattr(Request, "stream", slow_stream)
        assert (
            client.post(
                f"/api/v1/sessions/{token}/files",
                content=b"x",
                headers={"Content-Type": "application/octet-stream", "X-File-Name": "test.png"},
            ).status_code
            == 408
        )
        assert not list(settings.temporary_root.rglob("*.part"))


def test_daily_budget_rolls_over(settings, monkeypatch):
    database = Database(settings.database_path)
    database.initialize()
    guard = Protection(settings, database)
    guard.initialize()
    settings.daily_upload_mb = 1
    monkeypatch.setattr(guard, "day", lambda: "2026-10-10")
    guard.upload_bytes(1048576)
    with pytest.raises(InboxError):
        guard.upload_bytes(1)
    monkeypatch.setattr(guard, "day", lambda: "2026-10-11")
    guard.upload_bytes(1048576)
