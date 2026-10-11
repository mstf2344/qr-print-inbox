import pytest

from backend.supervisor import InstanceLock
from scripts.manage import running


def test_duplicate_supervisor_is_rejected_and_lock_is_released(tmp_path):
    lock = tmp_path / "supervisor.lock"
    assert not running(tmp_path)
    with InstanceLock(lock):
        assert running(tmp_path)
        with pytest.raises(OSError), InstanceLock(lock):
            pass
    assert not running(tmp_path)
