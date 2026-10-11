import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from backend.config import PROJECT_ROOT, Settings
from backend.supervisor import InstanceLock, healthy, hidden_options, runtime_root


def running(root):
    try:
        with InstanceLock(root / "supervisor.lock"):
            return False
    except OSError:
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    settings = Settings()
    root = runtime_root(settings)
    if args.action == "status":
        state = (
            json.loads((root / "state.json").read_text()) if (root / "state.json").exists() else {}
        )
        print(json.dumps({**state, "running": running(root), "healthy": healthy(settings)}))
        return
    if args.action == "stop":
        if running(root):
            (root / "stop.request").touch()
            for _ in range(400):
                if not running(root):
                    print("Service stopped.")
                    return
                time.sleep(0.1)
            raise SystemExit("Service is still stopping; check status before retrying.")
        print("Service is already stopped.")
        return
    if not settings.gateway_secret:
        raise SystemExit("Run python -m scripts.provision_gateway first.")
    if not running(root):
        if healthy(settings):
            raise SystemExit("Stop the manually started backend first.")
        python = (
            Path(sys.executable).with_name("pythonw.exe")
            if os.name == "nt"
            else Path(sys.executable)
        )
        subprocess.Popen(
            [str(python), "-m", "backend.supervisor"],
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden_options(),
        )
    for _ in range(200):
        if running(root) and healthy(settings):
            print("Service started. Open your configured public gateway URL.")
            return
        time.sleep(0.1)
    raise SystemExit("Service did not become healthy. Check data/runtime/service.log.")


if __name__ == "__main__":
    main()
