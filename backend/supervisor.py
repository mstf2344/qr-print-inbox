"""One hidden Windows supervisor, with bounded logs that never contain request paths."""

import json
import logging
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.request import Request, urlopen

from backend.config import PROJECT_ROOT, Settings


class InstanceLock:
    def __init__(self, path):
        self.path = path
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise
        return self

    def __exit__(self, *args):
        self.file.close()


def runtime_root(settings):
    return settings.data_root / "runtime"


def healthy(settings):
    if not settings.gateway_secret:
        return False
    request = Request(
        f"http://127.0.0.1:{settings.port}/healthz",
        headers={
            "X-Inbox-Gateway": settings.gateway_secret.get_secret_value(),
            "X-Inbox-Client-IP": "127.0.0.1",
        },
    )
    try:
        with urlopen(request, timeout=2) as response:
            return (
                response.headers.get("X-Inbox-Service") == "qr-print-inbox"
                and json.load(response).get("status") == "ok"
            )
    except (OSError, ValueError):
        return False


def hidden_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def terminate_tree(process):
    if process is None or process.poll() is not None:
        return
    # The venv interpreter on Windows may spawn a redirector child. Kill only
    # the tree rooted at our own Popen handle, never an arbitrary saved PID.
    if os.name == "nt":
        subprocess.run(
            [
                str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden_options(),
        )
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def spawn(command):
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden_options(),
    )


def run(settings):
    if not settings.gateway_secret:
        raise RuntimeError("Configure the gateway secret before starting public uploads.")
    share = os.environ.get("ZROK_SHARE_NAME", "")
    if not share or not share.startswith("public:"):
        raise RuntimeError("Set ZROK_SHARE_NAME to your own reserved public share.")
    zrok = Path(os.environ.get("LOCALAPPDATA", "")) / "QRPrintInbox/tools/zrok2/2.0.8/zrok2.exe"
    if not zrok.is_file():
        raise RuntimeError("Install the verified zrok2 binary first.")
    root = runtime_root(settings)
    with InstanceLock(root / "supervisor.lock"):
        if healthy(settings):
            raise RuntimeError("An unmanaged backend is already running; stop it first.")
        handler = RotatingFileHandler(
            root / "service.log", maxBytes=512000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger = logging.getLogger("inbox-service")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        stop = root / "stop.request"
        stop.unlink(missing_ok=True)
        backend = tunnel = None
        last_healthy = time.monotonic()
        backend_retries = tunnel_retries = 0
        try:
            logger.info("Service started")
            while not stop.exists():
                if backend is None or backend.poll() is not None:
                    terminate_tree(backend)
                    backend = spawn([sys.executable, "-m", "backend"])
                    backend_retries += 1
                    last_healthy = time.monotonic()
                    logger.info("Backend started (attempt %d)", backend_retries)
                ok = healthy(settings)
                if ok:
                    last_healthy = time.monotonic()
                    if tunnel is None or tunnel.poll() is not None:
                        terminate_tree(tunnel)
                        try:
                            # Remove only this application's stale share, not its reserved name.
                            subprocess.run(
                                [str(zrok), "delete", "share", share],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=20,
                                **hidden_options(),
                            )
                        except subprocess.TimeoutExpired:
                            logger.info("Tunnel controller not responding; will retry")
                        tunnel = spawn(
                            [
                                str(zrok),
                                "share",
                                "public",
                                f"http://127.0.0.1:{settings.port}",
                                "--headless",
                                "--force-local",
                                "-n",
                                share,
                            ]
                        )
                        tunnel_retries += 1
                        logger.info("Tunnel started (attempt %d)", tunnel_retries)
                elif time.monotonic() - last_healthy > 30:
                    terminate_tree(tunnel)
                    terminate_tree(backend)
                    backend = tunnel = None
                    logger.info("Backend health failed; restarting owned processes")
                state = {
                    "pid": os.getpid(),
                    "backend_pid": backend.pid if backend else None,
                    "tunnel_pid": tunnel.pid if tunnel else None,
                    "healthy": ok,
                    "backend_starts": backend_retries,
                    "tunnel_starts": tunnel_retries,
                    "running": True,
                }
                pending = root / "state.tmp"
                pending.write_text(json.dumps(state), encoding="utf-8")
                pending.replace(root / "state.json")
                for _ in range(30):
                    if stop.exists():
                        break
                    time.sleep(0.1)
        finally:
            terminate_tree(tunnel)
            terminate_tree(backend)
            (root / "state.json").write_text(json.dumps({"running": False}), encoding="utf-8")
            logger.info("Service stopped")
            handler.close()
            logger.removeHandler(handler)


if __name__ == "__main__":
    try:
        run(Settings())
    except OSError:
        # A second invocation exits without touching the running instance.
        sys.exit(1)
