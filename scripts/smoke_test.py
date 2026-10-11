"""Exercise the public gateway and verify real PC files. Creates labeled test deliveries."""

import argparse
import hashlib
import io
import time
from pathlib import Path

import httpx
from PIL import Image

from backend.config import Settings


def wait_online(client):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if client.get("/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise AssertionError("Public gateway did not recover within 60 seconds.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, "PNG")
    content = buffer.getvalue()
    with httpx.Client(base_url=base, timeout=40, follow_redirects=False) as client:
        wait_online(client)
        response = client.get("/")
        assert response.status_code == 200 and "Dosyalarınızı gönderin." in response.text
        assert "Visit Share" not in response.text
        for path in ["/.env", "/data/inbox.sqlite3", "/api/v1/sessions/bad/status"]:
            assert client.get(path).status_code == 404
        assert client.get("/api/v1/config").status_code == 200
        response = client.post("/api/v1/sessions")
        assert response.status_code == 201
        token = response.json()["token"]
        path = f"/api/v1/sessions/{token}"
        # Reject a disguised executable and do not leave it in the receipt.
        headers = {"Content-Type": "application/octet-stream", "X-File-Name": "sistem-testi.png"}
        assert client.post(path + "/files", headers=headers, content=b"MZ fake").status_code == 415
        names = []
        for _ in range(2):
            response = client.post(path + "/files", headers=headers, content=content)
            assert response.status_code == 201
            names.append(response.json()["name"])
        assert names == ["sistem-testi.png", "sistem-testi_2.png"]
        receipt = client.post(path + "/finalize").json()
        assert receipt["status"] == "complete"
        assert client.post(path + "/finalize").json() == receipt
        assert client.get(path + "/status").json()["customer_number"] == receipt["customer_number"]
        assert client.post(path + "/files", headers=headers, content=content).status_code == 409
    settings = Settings()
    folder = settings.storage_root / receipt["date"] / f"{receipt['customer_number']:03d}"
    assert folder.is_dir()
    for name in names:
        assert (
            hashlib.sha256((folder / name).read_bytes()).digest()
            == hashlib.sha256(content).digest()
        )
    # Token stays local and ignored, for restart/idempotency checks during release testing.
    import json

    Path("data").mkdir(exist_ok=True)
    Path("data/smoke-receipt.json").write_text(
        json.dumps({"token": token, "receipt": receipt}), encoding="utf-8"
    )
    print("PASS: public upload, content rejection, duplicate names, receipt retry, PC hashes; "
          f"number {receipt['customer_number']:03d}")


if __name__ == "__main__":
    main()
