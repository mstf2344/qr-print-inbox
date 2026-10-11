"""Live release checks. Creates labeled files; optional service interruption is explicit."""

import argparse
import hashlib
import io
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from PIL import Image

from backend.config import PROJECT_ROOT, Settings
from scripts.smoke_test import wait_online


def service(action):
    app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/QRPrintInbox/QRPrintInbox.exe"
    if app.exists():
        subprocess.run(
            [str(app), "/" + action], check=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        if action == "stop":
            lock = Path(os.environ["LOCALAPPDATA"]) / "QRPrintInbox/desktop/service.lock"
            for _ in range(40):
                try:
                    with lock.open("a+b"):
                        return
                except OSError:
                    time.sleep(1)
            raise RuntimeError("Native client did not stop.")
        return
    subprocess.run([sys.executable, "-m", "scripts.manage", action], cwd=PROJECT_ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interrupt-service", action="store_true")
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, "PNG")
    payload = buffer.getvalue()
    headers = {
        "Content-Type": "application/octet-stream",
        "X-File-Name": "sistem-testi-paralel.png",
    }
    settings = Settings()
    with httpx.Client(base_url=args.base_url, timeout=40) as client:
        wait_online(client)
        # The origin is intentionally inaccessible even when callers bypass the
        # zrok visitor page; possession of the URL is not gateway authentication.
        agent = client.get("/desktop/bridge/poll")
        assert agent.status_code == 403
        assert (
            client.get("/api/v1/config", headers={"Origin": "https://example.invalid"}).status_code
            == 403
        )
        tokens = []
        for _ in range(10):
            created = client.post("/api/v1/sessions")
            assert created.status_code == 201
            token = created.json()["token"]
            assert (
                client.post(
                    f"/api/v1/sessions/{token}/files", headers=headers, content=payload
                ).status_code
                == 201
            )
            tokens.append(token)

        def finalize(token):
            response = client.post(f"/api/v1/sessions/{token}/finalize")
            assert response.status_code == 200, f"Finalize HTTP {response.status_code}"
            return response.json()

        with ThreadPoolExecutor(max_workers=10) as executor:
            receipts = list(executor.map(finalize, tokens))
        numbers = {receipt["customer_number"] for receipt in receipts}
        assert len(numbers) == 10
        with ThreadPoolExecutor(max_workers=10) as executor:
            retries = list(executor.map(lambda _: finalize(tokens[0]), range(10)))
        assert all(receipt == receipts[0] for receipt in retries)
        for receipt in receipts:
            folder = settings.storage_root / receipt["date"] / f"{receipt['customer_number']:03d}"
            assert folder.is_dir()
            actual = (folder / "sistem-testi-paralel.png").read_bytes()
            assert hashlib.sha256(actual).digest() == hashlib.sha256(payload).digest()
        print(
            "PASS: live 10 concurrent deliveries + 10 finalize retries; "
            "unique numbers and PC hashes"
        )
        if args.interrupt_service:
            try:
                service("stop")
                assert client.get("/").status_code == 200
                assert client.get("/api/v1/config").status_code == 503
            finally:
                service("start")
            wait_online(client)
            assert finalize(tokens[0]) == receipts[0]
            new_token = client.post("/api/v1/sessions").json()["token"]
            assert (
                client.post(
                    f"/api/v1/sessions/{new_token}/files", headers=headers, content=payload
                ).status_code
                == 201
            )
            assert finalize(new_token)["customer_number"] > max(numbers)
            print(
                "PASS: offline 503, online recovery, receipt persistence; next number after restart"
            )


if __name__ == "__main__":
    main()
