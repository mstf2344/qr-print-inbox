import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.config import Settings
from backend.database import Database
from backend.main import create_app
from backend.protection import Protection
from backend.validation import InboxError


def test_crossing_chunk_closes_the_daily_budget_before_next_body_read(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        storage_root=tmp_path / "inbox",
        data_root=tmp_path / "data",
        daily_upload_mb=1,
    )
    with TestClient(create_app(settings)) as client:
        token = client.post("/api/v1/sessions").json()["token"]
        guard = Protection(settings, Database(settings.database_path))
        guard.upload_bytes(1048570)
        with pytest.raises(InboxError):
            guard.upload_bytes(10)

        async def must_not_read_body(self):
            raise AssertionError("Exhausted budget must stop before reading the upload.")
            yield b""  # pragma: no cover

        monkeypatch.setattr(Request, "stream", must_not_read_body)
        response = client.post(
            f"/api/v1/sessions/{token}/files",
            content=b"x",
            headers={"Content-Type": "application/octet-stream", "X-File-Name": "test.png"},
        )
        assert response.status_code == 429
