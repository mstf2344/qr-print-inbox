"""Bounded EXE acceptance test; isolated folders, labeled files, owned-process cleanup."""

import argparse
import hashlib
import io
import json
import os
import socket
import subprocess
import time
import uuid

import httpx
from PIL import Image

from backend.config import PROJECT_ROOT, Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Your HTTPS gateway ending in /desktop")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    executable = PROJECT_ROOT / "dist/QRPrintInbox-Kurulum.exe"
    trial = PROJECT_ROOT / "data/exe-acceptance" / uuid.uuid4().hex
    assert trial.resolve().is_relative_to((PROJECT_ROOT / "data").resolve())
    home, install, storage = (trial / name for name in ["home", "installed", "Gelen Dosyalar"])
    trial.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ | {
        "QR_INBOX_TEST_HOME": str(home),
        "QR_INBOX_TEST_PORT": str(port),
        "QR_INBOX_TEST_STORAGE": str(storage),
    }
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW}
    subprocess.run([str(executable), "/extract", str(install)], env=env, check=True, **flags)
    settings = Settings()
    connection = trial / "test.connection.json"
    connection.write_text(
        json.dumps(
            {"gateway_secret": settings.gateway_secret.get_secret_value(), "relay_url": base}
        ),
        encoding="utf-8",
    )
    app = install / "QRPrintInbox.exe"
    subprocess.run([str(app), "/import", str(connection)], env=env, check=True, **flags)
    assert (
        settings.gateway_secret.get_secret_value().encode()
        not in (home / "connection.bin").read_bytes()
    )
    process = subprocess.Popen([str(app), "/background"], env=env, cwd=install, **flags)
    try:
        with httpx.Client(base_url=base, timeout=12) as client:
            deadline = time.monotonic() + 65
            while True:
                try:
                    if client.get("/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    state = (home / "status.txt").read_text(encoding="utf-8-sig")
                    raise AssertionError("Packaged client did not become ready: " + state)
                time.sleep(1)
            assert client.get("/bridge/poll").status_code == 403
            assert client.get("/api/v1/config").status_code == 200
            token = client.post("/api/v1/sessions").json()["token"]
            path = f"/api/v1/sessions/{token}"
            buffer = io.BytesIO()
            Image.new("RGB", (16, 16), "white").save(buffer, "PNG")
            payload = buffer.getvalue()
            headers = {
                "Content-Type": "application/octet-stream",
                "X-File-Name": "sistem-testi-exe.png",
            }
            assert (
                client.post(path + "/files", headers=headers, content=b"MZ fake").status_code == 415
            )
            for _ in range(2):
                assert (
                    client.post(path + "/files", headers=headers, content=payload).status_code
                    == 201
                )
            receipt = client.post(path + "/finalize").json()
            assert receipt["status"] == "complete"
            assert client.post(path + "/finalize").json() == receipt
            folder = storage / receipt["date"] / f"{receipt['customer_number']:03d}"
            assert {p.name for p in folder.iterdir()} == {
                "sistem-testi-exe.png",
                "sistem-testi-exe_2.png",
            }
            for file in folder.iterdir():
                assert (
                    hashlib.sha256(file.read_bytes()).digest() == hashlib.sha256(payload).digest()
                )
            print(
                "PASS: actual x86 EXE, DPAPI settings, HTTP relay, content rejection, "
                "duplicate files, receipt retry and PC hashes"
            )
            (home / "stop.request").touch()
            process.wait(timeout=40)
            assert process.returncode == 0
            assert client.get("/api/v1/config").status_code == 503
            with socket.socket() as sock:
                assert sock.connect_ex(("127.0.0.1", port)) != 0
            print("PASS: EXE stop closes its owned backend")
    finally:
        (home / "stop.request").touch()
        if process.poll() is None:
            try:
                process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                # This Popen belongs only to this test; never stop a PID from a stale file.
                process.terminate()
                process.wait(timeout=10)
        connection.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
