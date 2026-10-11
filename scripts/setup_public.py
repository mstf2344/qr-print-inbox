"""Prepare an independent Cloudflare deployment without publishing any credentials."""

import argparse
import json
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def prepare(public_url, worker_name, relay_name):
    url = urlsplit(public_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.port not in (None, 443)
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError("Use your public HTTPS origin, e.g. https://shop.account.workers.dev")
    for name in (worker_name, relay_name):
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", name):
            raise ValueError("Worker names must be 3-63 lowercase letters, digits or hyphens.")
    if worker_name == relay_name:
        raise ValueError("Gateway and relay must have different names.")
    origin = public_url.rstrip("/")
    connection = ROOT / "dist/My-PC.connection.json"
    connection.parent.mkdir(parents=True, exist_ok=True)
    if connection.exists():
        config = json.loads(connection.read_text(encoding="utf-8"))
        if config["relay_url"] != origin + "/desktop":
            raise ValueError("Existing connection belongs to a different URL; move it first.")
    else:
        config = {"gateway_secret": secrets.token_urlsafe(48), "relay_url": origin + "/desktop"}
        connection.write_text(json.dumps(config, indent=2), encoding="utf-8")
    gateway = json.loads((ROOT / "worker/wrangler.jsonc").read_text(encoding="utf-8"))
    relay = json.loads((ROOT / "legacy-worker/wrangler.jsonc").read_text(encoding="utf-8"))
    gateway["name"] = worker_name
    gateway["services"][0]["service"] = relay_name
    relay["name"] = relay_name
    for folder, config_body in (("worker", gateway), ("legacy-worker", relay)):
        (ROOT / folder / "wrangler.local.jsonc").write_text(
            json.dumps(config_body, indent=2), encoding="utf-8"
        )
    return connection, config["gateway_secret"]


def deploy(secret):
    node = shutil.which("node")
    wrangler = ROOT / "worker/node_modules/wrangler/bin/wrangler.js"
    if not node or not wrangler.exists():
        raise RuntimeError("Install Node.js and run npm --prefix worker ci first.")
    for folder in ("legacy-worker", "worker"):
        args = [node, str(wrangler), "--config", "wrangler.local.jsonc"]
        subprocess.run(args + ["deploy"], cwd=ROOT / folder, check=True)
        result = subprocess.run(
            args + ["secret", "put", "GATEWAY_SECRET"],
            input=secret + "\n", text=True, cwd=ROOT / folder, capture_output=True,
        )
        if result.returncode:
            raise RuntimeError("Secret setup failed. Check your Wrangler account and retry.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--worker-name", required=True)
    parser.add_argument("--relay-name", required=True)
    parser.add_argument("--deploy", action="store_true", help="Deploy to your logged-in account")
    args = parser.parse_args()
    connection, secret = prepare(args.public_url, args.worker_name, args.relay_name)
    if args.deploy:
        deploy(secret)
    print("Private connection saved: " + str(connection))
    print("Keep this file private. No credentials were written to tracked files.")


if __name__ == "__main__":
    main()
