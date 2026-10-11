from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings
from backend.database import Database
from backend.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, storage_root=tmp_path / "inbox", data_root=tmp_path / "data")


def test_customer_page_only_exposes_explicit_assets_and_safe_limits(settings):
    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Dosyalarınızı gönderin." in page.text
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"
        for path, content_type in [("/app.js", "text/javascript"), ("/style.css", "text/css")]:
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(content_type)
        assert client.get("/api/v1/config").json() == {
            "max_file_size_mb": settings.max_file_size_mb,
            "max_session_size_mb": settings.max_session_size_mb,
            "max_files_per_session": settings.max_files_per_session,
            "allowed_extensions": settings.allowed_extensions.split(","),
        }
        for path in ["/data/inbox.sqlite3", "/.env", "/web/../backend/config.py", "/inbox/"]:
            assert client.get(path).status_code == 404


def test_session_persists_across_restarts_without_storing_token(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/sessions")
        assert response.status_code == 201
        token = response.json()["token"]
        assert response.headers["cache-control"] == "no-store"
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/api/v1/sessions/{token}/status")
        assert response.status_code == 200
        assert response.json()["status"] == "uploading"
        assert "token" not in response.json()
        assert client.get("/healthz").json() == {"status": "ok"}
    database = Database(settings.database_path)
    with database.connect() as connection:
        rows = connection.execute("SELECT token_hash FROM sessions").fetchall()
        assert rows[0]["token_hash"] != token
        assert rows[0]["token_hash"] == database.token_hash(token)


def test_expired_and_unknown_sessions_have_same_response(settings):
    with TestClient(create_app(settings)) as client:
        token = client.post("/api/v1/sessions").json()["token"]
        with Database(settings.database_path).connect() as connection:
            connection.execute("UPDATE sessions SET expires_at = 0")
        expired = client.get(f"/api/v1/sessions/{token}/status")
        unknown = client.get(f"/api/v1/sessions/{'x' * 43}/status")
        assert expired.status_code == unknown.status_code == 404
        assert expired.json() == unknown.json()


def test_concurrent_sessions_are_distinct_and_durable(settings):
    database = Database(settings.database_path)
    database.initialize()
    with ThreadPoolExecutor(max_workers=10) as executor:
        sessions = list(executor.map(lambda _: database.create_session(60), range(10)))
    assert len({session["token"] for session in sessions}) == 10
    assert all(database.get_session(session["token"]) for session in sessions)


@pytest.mark.parametrize(
    "overrides",
    [
        {"storage_root": "relative/path"},
        {"timezone": "invalid/timezone"},
        {"host": "0.0.0.0"},
        {"session_ttl_minutes": 0},
        {"max_file_size_mb": 0},
    ],
)
def test_unsafe_settings_fail_early(settings, overrides):
    values = settings.model_dump() | overrides
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
