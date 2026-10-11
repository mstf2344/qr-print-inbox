"""Build a secret-free x86 Windows 7 SP1 payload from official Python and locked wheels."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build/windows7"
PYTHON_URL = "https://www.python.org/ftp/python/3.8.10/python-3.8.10-embed-win32.zip"
PYTHON_SHA256 = "760dc79bcb434ee80b1001a30bb6f798287881851bac6d8137867894d40ef1fc"


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    archive = BUILD / "python-3.8.10-embed-win32.zip"
    if not archive.exists():
        urlretrieve(PYTHON_URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PYTHON_SHA256:
        raise ValueError("Python runtime checksum mismatch.")
    payload = BUILD / "payload"
    if payload.exists():
        if (
            payload.is_symlink()
            or payload.is_junction()
            or payload.resolve().parent != BUILD.resolve()
        ):
            raise ValueError("Unsafe generated payload directory.")
        shutil.rmtree(payload)
    runtime = payload / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as package:
        package.extractall(runtime)
    # Verify the executable's vendor signature before packaging any downloaded runtime.
    command = (
        "Import-Module ($env:SystemRoot + "
        r"'\System32\WindowsPowerShell\v1.0\Modules\Microsoft.PowerShell.Security"
        r"\Microsoft.PowerShell.Security.psd1'); "
        "$s=Get-AuthenticodeSignature -LiteralPath '"
        + str(runtime / "python.exe").replace("'", "''")
        + "'; if ($s.Status -ne 'Valid' -or "
        "$s.SignerCertificate.Subject -notlike '*Python Software Foundation*') { exit 1 }"
    )
    powershell = Path(__import__("os").environ["SystemRoot"]) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    subprocess.run([str(powershell), "-NoProfile", "-Command", command], check=True)
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv.exe")
    subprocess.run(
        [
            str(uv),
            "pip",
            "install",
            "--target",
            str(runtime / "Lib/site-packages"),
            "--python-version",
            "3.8",
            "--python-platform",
            "i686-pc-windows-msvc",
            "--only-binary",
            ":all:",
            "--require-hashes",
            "-r",
            str(ROOT / "windows/requirements-win7.lock"),
        ],
        check=True,
    )
    (runtime / "python38._pth").write_text(
        "python38.zip\n.\nLib/site-packages\n..\nimport site\n", encoding="utf-8"
    )
    # uv creates CLI launchers for the build host, even with cross-platform wheels.
    # The application uses python.exe -m backend; these launchers are never needed.
    launchers = runtime / "Lib/site-packages/bin"
    if launchers.exists():
        for launcher in launchers.iterdir():
            if launcher.name not in {"dotenv.exe", "fastapi.exe", "uvicorn.exe"}:
                raise ValueError("Unexpected generated CLI launcher.")
            launcher.unlink()
        launchers.rmdir()
    shutil.copytree(
        ROOT / "backend",
        payload / "backend",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(ROOT / "web", payload / "web", dirs_exist_ok=True)
    files = {}
    for path in payload.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            name = path.relative_to(payload).as_posix()
            assert name.startswith(("backend/", "web/", "runtime/"))
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "version": 1,
        "python_url": PYTHON_URL,
        "python_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": files,
    }
    (BUILD / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with ZipFile(BUILD / "payload.zip", "w", compression=8) as package:
        for name in sorted(files):
            package.write(payload / name, name)
        package.writestr("manifest.json", json.dumps(manifest))
    subprocess.run(
        [
            str(runtime / "python.exe"),
            "-c",
            "import struct; from backend.main import create_app; "
            "assert struct.calcsize('P') == 4; print('PASS: x86 bundled backend imports')",
        ],
        cwd=payload,
        check=True,
    )
    print("Payload built. No configuration, credentials, customer data or zrok included.")


if __name__ == "__main__":
    main()
