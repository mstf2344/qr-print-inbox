import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from backend.config import Settings
from backend.database import Database
from backend.main import create_app
from backend.storage import Inbox
from backend.validation import OFFICE_NAMESPACES, OFFICE_TYPES, InboxError


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, storage_root=tmp_path / "inbox", data_root=tmp_path / "data")


def image_bytes(format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format=format)
    return buffer.getvalue()


def pdf_bytes():
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()


def office_bytes(suffix, malicious=False):
    main, content_type, root = OFFICE_TYPES[suffix]
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(main, f'<{root} xmlns="{OFFICE_NAMESPACES[suffix]}"/>')
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" '
            f'Target="{main}"/></Relationships>',
        )
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            f'<Override PartName="/{main}" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            f'{content_type}"/></Types>',
        )
        if malicious:
            archive.writestr("word/vbaProject.bin", b"macro")
    return buffer.getvalue()


def session(client):
    return client.post("/api/v1/sessions").json()["token"]


def upload(client, token, name="test.png", content=None):
    return client.post(
        f"/api/v1/sessions/{token}/files",
        headers={"Content-Type": "application/octet-stream", "X-File-Name": quote(name)},
        content=image_bytes() if content is None else content,
    )


def test_delivery_multiple_files_names_and_idempotency(settings):
    with TestClient(create_app(settings)) as client:
        token = session(client)
        assert upload(client, token, "../../CON.png").json()["name"] == "_CON.png"
        assert upload(client, token, "_con.PNG").json()["name"] == "_con_2.png"
        assert not list(settings.storage_root.rglob("*.png"))
        response = client.post(f"/api/v1/sessions/{token}/finalize")
        assert response.status_code == 200
        receipt = response.json()
        assert receipt["customer_number"] == 1
        assert client.post(f"/api/v1/sessions/{token}/finalize").json() == receipt
        assert upload(client, token).status_code == 409
        status = client.get(f"/api/v1/sessions/{token}/status").json()
        assert status["status"] == "complete"
        assert len(status["files"]) == 2
        assert status["customer_number"] == 1
        assert str(settings.storage_root) not in response.text
        delivered = list(settings.storage_root.rglob("*.png"))
        assert len(delivered) == 2
        assert delivered[0].parent == delivered[1].parent
        assert delivered[0].parent.name == "001"
        assert all(path.read_bytes() == image_bytes() for path in delivered)
        assert (
            client.get(f"/{receipt['date']}/{delivered[0].parent.name}/_CON.png").status_code == 404
        )
    with TestClient(create_app(settings)) as client:
        assert client.post(f"/api/v1/sessions/{token}/finalize").json() == receipt
        new_token = session(client)
        assert upload(client, new_token).status_code == 201
        assert client.post(f"/api/v1/sessions/{new_token}/finalize").json()["customer_number"] == 2


@pytest.mark.parametrize(
    "name,content",
    [
        ("real.pdf", pdf_bytes()),
        ("real.jpg", image_bytes("JPEG")),
        ("real.docx", office_bytes(".docx")),
        ("real.xlsx", office_bytes(".xlsx")),
        ("real.pptx", office_bytes(".pptx")),
    ],
)
def test_supported_content(settings, name, content):
    with TestClient(create_app(settings)) as client:
        token = session(client)
        assert upload(client, token, name, content).status_code == 201
        assert client.post(f"/api/v1/sessions/{token}/finalize").status_code == 200


@pytest.mark.parametrize(
    "name,content,expected",
    [
        ("program.exe", b"MZ executable", 415),
        ("fake.pdf", b"MZ executable", 415),
        ("fake.png", b"%PDF-1.7", 415),
        ("wrong.jpg", image_bytes(), 415),
        ("empty.png", b"", 422),
        ("macro.docx", office_bytes(".docx", malicious=True), 415),
        ("wrong.docx", office_bytes(".xlsx"), 415),
    ],
)
def test_rejected_files_leave_no_delivery_or_temporary_file(settings, name, content, expected):
    with TestClient(create_app(settings)) as client:
        token = session(client)
        assert upload(client, token, name, content).status_code == expected
        assert client.post(f"/api/v1/sessions/{token}/finalize").status_code == 422
        assert client.get(f"/api/v1/sessions/{token}/status").json()["files"] == []
        assert not list(settings.temporary_root.rglob("*.part"))
        assert not list(settings.storage_root.iterdir())


def test_size_and_count_limits(settings):
    settings.max_file_size_mb = 1
    settings.max_session_size_mb = 1
    settings.max_files_per_session = 1
    with TestClient(create_app(settings)) as client:
        token = session(client)
        assert upload(client, token, content=b"x" * (1024 * 1024 + 1)).status_code == 413
        assert not list(settings.temporary_root.rglob("*.part"))
        assert upload(client, token).status_code == 201
        assert upload(client, token).status_code == 413


def test_session_total_limit_checks_actual_streamed_bytes(settings):
    settings.max_file_size_mb = 2
    settings.max_session_size_mb = 1
    with TestClient(create_app(settings)) as client:
        token = session(client)
        first = image_bytes()
        assert upload(client, token, content=first).status_code == 201
        response = upload(client, token, content=b"x" * (1024 * 1024 - len(first) + 1))
        assert response.status_code == 413
        assert len(client.get(f"/api/v1/sessions/{token}/status").json()["files"]) == 1


def test_disconnect_releases_reservation_and_partial_file(settings, monkeypatch):
    from starlette.requests import ClientDisconnect, Request

    async def interrupted_stream(self):
        yield image_bytes()[:20]
        raise ClientDisconnect()

    with TestClient(create_app(settings)) as client:
        token = session(client)
        with monkeypatch.context() as patch:
            patch.setattr(Request, "stream", interrupted_stream)
            assert upload(client, token).status_code == 400
        assert not list(settings.temporary_root.rglob("*.part"))
        assert client.get(f"/api/v1/sessions/{token}/status").json()["files"] == []
        assert upload(client, token).status_code == 201


def test_low_disk_rejected_without_paths(settings, monkeypatch):
    import shutil

    with TestClient(create_app(settings)) as client:
        token = session(client)
        monkeypatch.setattr(shutil, "disk_usage", lambda _: type("Disk", (), {"free": 0})())
        response = upload(client, token)
        assert response.status_code == 507
        assert str(settings.storage_root) not in response.text


def test_second_backend_cannot_recover_active_uploads(settings):
    database = Database(settings.database_path)
    database.initialize()
    first, second = Inbox(settings, database), Inbox(settings, database)
    first.start()
    try:
        with pytest.raises(OSError):
            second.start()
    finally:
        second.stop()
        first.stop()


def test_concurrent_ten_deliveries_and_same_session_retries(settings):
    with TestClient(create_app(settings)) as client:
        tokens = [session(client) for _ in range(10)]
        for token in tokens:
            assert upload(client, token).status_code == 201
        with ThreadPoolExecutor(max_workers=10) as executor:
            responses = list(
                executor.map(
                    lambda token: client.post(f"/api/v1/sessions/{token}/finalize"), tokens
                )
            )
        assert all(response.status_code == 200 for response in responses)
        assert {response.json()["customer_number"] for response in responses} == set(range(1, 11))
        with ThreadPoolExecutor(max_workers=10) as executor:
            retries = list(
                executor.map(
                    lambda _: client.post(f"/api/v1/sessions/{tokens[0]}/finalize").json(),
                    range(10),
                )
            )
        assert all(receipt == responses[0].json() for receipt in retries)
        assert len(list(settings.storage_root.rglob("*.png"))) == 10


def ready_file(inbox, token):
    reservation = inbox.reserve(token, "test.png")
    content = image_bytes()
    reservation["part"].write_bytes(content)
    inbox.accept(reservation, len(content), hashlib.sha256(content).hexdigest())


@pytest.mark.parametrize("renamed", [False, True])
def test_recovery_after_crash_before_or_after_rename(settings, monkeypatch, renamed):
    database = Database(settings.database_path)
    database.initialize()
    inbox = Inbox(settings, database)
    inbox.start()
    token = database.create_session(60)["token"]
    ready_file(inbox, token)
    original = inbox.finish_delivery

    def fail(delivery):
        if renamed:
            _, ready = inbox.paths(delivery["session_hash"])
            target = settings.storage_root / delivery["folder"]
            target.parent.mkdir(parents=True, exist_ok=True)
            ready.rename(target)
        raise OSError("simulated crash")

    monkeypatch.setattr(inbox, "finish_delivery", fail)
    with pytest.raises(OSError):
        inbox.finalize(token)
    inbox.stop()
    monkeypatch.setattr(inbox, "finish_delivery", original)
    restarted = Inbox(settings, database)
    restarted.start()
    try:
        assert restarted.finalize(token)["customer_number"] == 1
        assert len(list(settings.storage_root.rglob("*.png"))) == 1
        assert database.get_session(token)["status"] == "complete"
    finally:
        restarted.stop()


def test_incomplete_upload_rejects_finalize_and_is_cleaned_on_restart(settings):
    database = Database(settings.database_path)
    database.initialize()
    inbox = Inbox(settings, database)
    inbox.start()
    token = database.create_session(60)["token"]
    reservation = inbox.reserve(token, "test.png")
    reservation["part"].write_bytes(b"partial")
    with pytest.raises(InboxError) as error:
        inbox.finalize(token)
    assert error.value.status_code == 409
    inbox.stop()
    inbox.start()
    try:
        assert not reservation["part"].exists()
        assert database.get_session(token)["files"] == []
    finally:
        inbox.stop()


def test_daily_counter_uses_configured_timezone(settings, monkeypatch):
    import backend.database as database_module
    import backend.storage as storage

    class Clock(datetime):
        instant = datetime.fromisoformat("2026-10-10T20:59:59+00:00")

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)

    monkeypatch.setattr(storage, "datetime", Clock)
    monkeypatch.setattr(database_module, "datetime", Clock)
    with TestClient(create_app(settings)) as client:
        first = session(client)
        upload(client, first)
        one = client.post(f"/api/v1/sessions/{first}/finalize").json()
        Clock.instant = datetime.fromisoformat("2026-10-10T21:00:00+00:00")
        second = session(client)
        upload(client, second)
        two = client.post(f"/api/v1/sessions/{second}/finalize").json()
        assert one["date"] == "2026-10-10"
        assert two["date"] == "2026-10-11"
        assert one["customer_number"] == two["customer_number"] == 1
