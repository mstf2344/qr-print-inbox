"""Small stdlib bridges for the separately pinned Windows 7 runtime."""

import hashlib
from datetime import timezone

try:
    from zoneinfo import ZoneInfo as ZoneInfo
    from zoneinfo import ZoneInfoNotFoundError as ZoneInfoNotFoundError
except ImportError:
    from backports.zoneinfo import ZoneInfo as ZoneInfo
    from backports.zoneinfo import ZoneInfoNotFoundError as ZoneInfoNotFoundError

UTC = timezone.utc


def file_digest(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest


def is_junction(path):
    if hasattr(path, "is_junction"):
        return path.is_junction()
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def is_relative_to(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
