"""Keep the procfs oracle truthful when its owned process disappears."""

import errno
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import pytest

import test_runtime_adapter_output_720 as oracle


@pytest.fixture(scope="session", autouse=True)
def identity_provenance(record_testsuite_property):
    source = Path(oracle.__file__).resolve()
    assert source == Path(__file__).with_name("test_runtime_adapter_output_720.py").resolve()
    for name, value in {
        "procfs_870_python": sys.version,
        "procfs_870_executable": sys.executable,
        "procfs_870_oracle": str(source),
        "procfs_870_oracle_sha256": sha256(source.read_bytes()).hexdigest(),
    }.items():
        record_testsuite_property(name, value)


@pytest.fixture
def owned_child():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_live_identity_and_wrong_start_are_distinguished(owned_child):
    identity = oracle._identity(owned_child.pid)
    assert identity is not None
    assert identity[1].isdigit()
    assert oracle._alive(owned_child.pid, identity[1])
    assert not oracle._alive(owned_child.pid, str(int(identity[1]) + 1))
    assert owned_child.poll() is None


@pytest.mark.parametrize("helper", ["identity", "alive"])
def test_reaped_before_open_is_absent(owned_child, helper):
    identity = oracle._identity(owned_child.pid)
    assert identity is not None
    owned_child.kill()
    owned_child.wait(timeout=5)
    if helper == "identity":
        assert oracle._identity(owned_child.pid) is None
    else:
        assert oracle._alive(owned_child.pid, identity[1]) is False


@pytest.mark.parametrize("helper", ["identity", "alive"])
def test_reaped_after_open_is_absent(owned_child, monkeypatch, helper):
    identity = oracle._identity(owned_child.pid)
    assert identity is not None
    target = Path(f"/proc/{owned_child.pid}/stat")
    real_open = Path.open
    events = []

    def exit_after_open(file, *args, **kwargs):
        stream = real_open(file, *args, **kwargs)
        if file != target and file != str(target):
            return stream
        events.append("opened")
        try:
            owned_child.kill()
            owned_child.wait(timeout=5)
            events.append("reaped_before_read")
        except BaseException:
            stream.close()
            raise
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", exit_after_open)
        try:
            if helper == "identity":
                assert oracle._identity(owned_child.pid) is None
            else:
                assert oracle._alive(owned_child.pid, identity[1]) is False
        finally:
            assert events == ["opened", "reaped_before_read"]
            assert owned_child.poll() is not None


@pytest.mark.parametrize("helper", ["identity", "alive"])
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_non_disappearance_errors_propagate(monkeypatch, helper, error_number):
    failure = OSError(error_number, "synthetic non-disappearance failure")

    def fail_read(path, *args, **kwargs):
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", fail_read)
        with pytest.raises(type(failure)) as observed:
            if helper == "identity":
                oracle._identity(123)
            else:
                oracle._alive(123, "synthetic-start")
    assert observed.value is failure
