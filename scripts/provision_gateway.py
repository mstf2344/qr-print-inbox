"""Set the same secret locally and on the existing Worker, without printing it."""

import os
import secrets
import shutil
import subprocess

from backend.config import PROJECT_ROOT, Settings


def main():
    settings = Settings()
    env_file = PROJECT_ROOT / ".env"
    if settings.gateway_secret:
        secret = settings.gateway_secret.get_secret_value()
    else:
        secret = secrets.token_urlsafe(48)
        with env_file.open("a", encoding="utf-8") as output:
            output.write("\nGATEWAY_SECRET=" + secret + "\n")
    node = shutil.which("node")
    wrangler = PROJECT_ROOT / "worker/node_modules/wrangler/bin/wrangler.js"
    if not node or not wrangler.exists():
        raise SystemExit("Install Node and run npm ci in worker first.")
    result = subprocess.run(
        [node, str(wrangler), "secret", "put", "GATEWAY_SECRET"],
        input=secret + "\n",
        text=True,
        cwd=PROJECT_ROOT / "worker",
        env=os.environ | {"WRANGLER_SEND_METRICS": "false"},
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        # Do not echo CLI diagnostics which might contain account or secret data.
        raise SystemExit("Secret setup failed. Check Wrangler login and retry.")
    print("Gateway secret configured locally and on the existing Worker.")


if __name__ == "__main__":
    main()
