"""Create public archives from tracked sources only; private transfer is separate."""

import hashlib
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    dist = ROOT / "dist"
    exe = dist / "QRPrintInbox-Kurulum.exe"
    if not exe.exists():
        raise SystemExit("Run windows/Build-Exe.ps1 first.")
    public = dist / "QRPrintInbox-Public.zip"
    source = dist / "qr-print-inbox-source.zip"
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        for name in sorted(filter(None, names)):
            path = Path(name)
            if (
                any(
                    part in {"data", "dist", "build", ".venv", "node_modules", "docs"}
                    for part in path.parts
                )
                or name.endswith((".connection.json", ".local.jsonc", ".db", ".sqlite3", ".log"))
                or name == "windows/activate_local.py"
                or (path.name.startswith(".env") and path.name != ".env.example")
            ):
                raise ValueError("Private/generated file tracked; refusing release: " + name)
            archive.write(ROOT / path, "qr-print-inbox/" + name)
    with ZipFile(public, "w", ZIP_DEFLATED) as archive:
        archive.write(exe, exe.name)
        for name in ("README.md", "LICENSE", "SECURITY.md", "connection.example.json"):
            archive.write(ROOT / name, name)
        for name in ("Install-Here.cmd", "Disable-Local.ps1"):
            archive.write(ROOT / "windows" / name, name)
    hashes = []
    for path in (exe, public, source):
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
    (dist / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    print("Public archives and SHA256SUMS.txt created in dist. No private connection included.")


if __name__ == "__main__":
    main()
