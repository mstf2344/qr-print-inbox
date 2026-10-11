"""Run shared behavior checks inside the real Python 3.8 x86 payload."""

import struct
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "build/windows7/test-deps"))
sys.path.insert(0, str(root))
assert sys.version_info[:2] == (3, 8) and struct.calcsize("P") == 4

import pytest  # noqa: E402

raise SystemExit(
    pytest.main(
        [
            "-q",
            str(root / "tests/test_delivery.py"),
            str(root / "tests/test_protection.py"),
            str(root / "tests/test_retention.py"),
        ]
    )
)
