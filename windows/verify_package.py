"""Check shipped paths, hashes, PE architecture and exclusion of the actual key."""

import hashlib
import json
import struct
from zipfile import ZipFile

from backend.config import PROJECT_ROOT, Settings


def machine(content):
    assert content[:2] == b"MZ"
    offset = struct.unpack_from("<I", content, 0x3C)[0]
    assert content[offset : offset + 4] == b"PE\0\0"
    return struct.unpack_from("<H", content, offset + 4)[0]


def main():
    executable = PROJECT_ROOT / "dist/QRPrintInbox-Kurulum.exe"
    secret = Settings().gateway_secret
    key = secret.get_secret_value().encode() if secret else None
    content = executable.read_bytes()
    assert (not key or key not in content) and machine(content) == 0x14C
    with ZipFile(PROJECT_ROOT / "build/windows7/payload.zip") as archive:
        files = json.loads(archive.read("manifest.json"))["files"]
        assert set(archive.namelist()) == set(files) | {"manifest.json"}
        for name, expected in files.items():
            assert name.startswith(("backend/", "web/", "runtime/"))
            assert not name.endswith((".env", ".sqlite3", ".db", ".connection.json"))
            body = archive.read(name)
            assert hashlib.sha256(body).hexdigest() == expected and (not key or key not in body)
            if name.endswith((".exe", ".pyd", ".dll")):
                assert machine(body) == 0x14C
    print("PASS: complete payload manifest, x86 binaries, no database/customer config/key")
    print("EXE SHA256: " + hashlib.sha256(content).hexdigest())


if __name__ == "__main__":
    main()
