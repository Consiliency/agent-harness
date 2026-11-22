"""Native lock behavior; run unchanged on Linux, macOS and Windows."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from phase_loop_runtime.file_lock import (
    acquire_exclusive,
    open_generation_lease,
    release_exclusive,
)


CONTENDER = """
import os, sys
from pathlib import Path
from phase_loop_runtime.file_lock import acquire_exclusive, open_generation_lease
try:
    if sys.argv[2] == 'lease':
        fd = open_generation_lease(Path(sys.argv[1]))
    else:
        fd = os.open(sys.argv[1], os.O_RDWR)
        acquire_exclusive(fd, blocking=False)
except BlockingIOError:
    sys.exit(23)
os.close(fd)
"""


def contender(path, kind="record"):
    return subprocess.run(
        [sys.executable, "-c", CONTENDER, str(path), kind],
        capture_output=True, text=True, timeout=15,
    )


@pytest.mark.parametrize("payload", [b"", b'{"generation":"unchanged"}\n'])
def test_contention_preserves_bytes_and_offset(tmp_path, payload):
    path = tmp_path / "lock with spaces é"
    path.write_bytes(payload)
    with path.open("r+b", buffering=0) as handle:
        handle.seek(7)
        acquire_exclusive(handle, blocking=False)
        assert handle.tell() == 7
        result = contender(path)
        assert result.returncode == 23, result.stderr
        release_exclusive(handle)
        assert handle.tell() == 7
    assert path.read_bytes() == payload
    result = contender(path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["record", "lease"])
def test_process_death_releases_ownership(tmp_path, kind):
    path = tmp_path / "generation.lock"
    path.write_bytes(b"unchanged")
    ready = tmp_path / "ready"
    code = """
import os, sys, time
from pathlib import Path
from phase_loop_runtime.file_lock import acquire_exclusive, open_generation_lease
path = Path(sys.argv[1])
if sys.argv[3] == 'lease':
    fd = open_generation_lease(path)
else:
    fd = os.open(path, os.O_RDWR)
    acquire_exclusive(fd)
Path(sys.argv[2]).touch()
time.sleep(60)
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(path), str(ready), kind])
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "Lock holder did not become ready"
        result = contender(path, kind)
        assert result.returncode == 23, result.stderr
        child.kill()
        child.wait(timeout=10)
        result = contender(path, kind)
        assert result.returncode == 0, result.stderr
        assert path.read_bytes() == b"unchanged"
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)


def test_generation_lease_duplicate_retains_ownership(tmp_path):
    path = tmp_path / "lease"
    first = open_generation_lease(path)
    duplicate = os.dup(first)
    assert not os.get_inheritable(first)
    os.close(first)
    try:
        result = contender(path, "lease")
        assert result.returncode == 23, result.stderr
    finally:
        os.close(duplicate)
    result = contender(path, "lease")
    assert result.returncode == 0, result.stderr


def test_generation_lease_explicit_child_handoff(tmp_path):
    path = tmp_path / "inherited.lease"
    ready = tmp_path / "child.ready"
    fd = open_generation_lease(path)
    options = {}
    inherited = fd
    if os.name == "nt":
        import msvcrt
        inherited = msvcrt.get_osfhandle(fd)
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": [inherited]}
        options["startupinfo"] = startup
    else:
        options["pass_fds"] = (fd,)
    code = """
import os, sys, time
from pathlib import Path
fd = int(sys.argv[1])
if os.name == 'nt':
    import msvcrt
    fd = msvcrt.open_osfhandle(fd, os.O_RDWR)
os.fstat(fd)
Path(sys.argv[2]).touch()
time.sleep(60)
"""
    child = None
    try:
        os.set_inheritable(fd, True)
        child = subprocess.Popen([sys.executable, "-c", code, str(inherited), str(ready)], **options)
        os.set_inheritable(fd, False)
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        os.close(fd)
        fd = None
        result = contender(path, "lease")
        assert result.returncode == 23, result.stderr
    finally:
        if fd is not None:
            os.close(fd)
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
    result = contender(path, "lease")
    assert result.returncode == 0, result.stderr


def test_invalid_descriptor_is_not_contention(tmp_path):
    fd = os.open(tmp_path / "closed", os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    with pytest.raises(OSError) as caught:
        acquire_exclusive(fd, blocking=False)
    assert not isinstance(caught.value, BlockingIOError)


def test_generation_lease_access_error_is_not_contention(tmp_path):
    with pytest.raises(OSError) as caught:
        open_generation_lease(tmp_path)
    assert not isinstance(caught.value, BlockingIOError)


def test_broker_nested_lock_preserves_outer_ownership(tmp_path):
    from phase_loop_runtime.convergence.broker.live import _reentrant_flock

    path = tmp_path / "broker.lock"
    with _reentrant_flock(path):
        with _reentrant_flock(path):
            assert contender(path).returncode == 23
        assert contender(path).returncode == 23
    assert contender(path).returncode == 0


def test_blocking_contender_waits_for_release(tmp_path):
    path = tmp_path / "blocking.lock"
    ready = tmp_path / "waiting"
    acquired = tmp_path / "acquired"
    path.touch()
    code = """
import sys
from pathlib import Path
from phase_loop_runtime.file_lock import acquire_exclusive, release_exclusive
with open(sys.argv[1], 'r+b', buffering=0) as handle:
    Path(sys.argv[2]).touch()
    acquire_exclusive(handle)
    Path(sys.argv[3]).touch()
    release_exclusive(handle)
"""
    with path.open("r+b", buffering=0) as handle:
        acquire_exclusive(handle)
        child = subprocess.Popen([sys.executable, "-c", code, str(path), str(ready), str(acquired)])
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert ready.exists()
            assert child.poll() is None
            assert not acquired.exists()
            release_exclusive(handle)
            assert child.wait(timeout=10) == 0
            assert acquired.exists()
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def test_dispatch_explicit_identity_reenters_and_competitor_is_rejected(tmp_path):
    from phase_loop_runtime.dispatch_lock import DispatchLock, DispatchLockContention

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=15)
    roadmap = tmp_path / "roadmap.md"
    with DispatchLock(tmp_path, roadmap, caller_run_id="owner"):
        with DispatchLock(tmp_path, roadmap, caller_run_id="owner") as nested:
            assert nested.reentrant
        with pytest.raises(DispatchLockContention):
            DispatchLock(tmp_path, roadmap, caller_run_id="competitor").acquire()


def test_production_imports():
    result = subprocess.run(
        [sys.executable, "-c", "from phase_loop_runtime import runner, launcher, agy_qualification; "
         "from phase_loop_runtime.convergence.broker import live"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_unsupported_qualification_cannot_admit(monkeypatch):
    from phase_loop_runtime import agy_qualification as qualification

    # On Linux exercise the platform guard too; native Windows/macOS use their
    # actual platform and never replace any operating-system primitive.
    if sys.platform == "linux":
        monkeypatch.setattr(qualification.sys, "platform", "unsupported")
    def unexpected(*args, **kwargs):
        pytest.fail("Unsupported qualification reached executable admission")
    monkeypatch.setattr(qualification.gh, "admit", unexpected)
    with pytest.raises(ValueError, match=qualification.SELF_QUALIFICATION_UNAVAILABLE):
        qualification.ensure_admitted({})
    with pytest.raises(ValueError, match=qualification.SELF_QUALIFICATION_UNAVAILABLE):
        qualification.lookup({}, b"not executable", Path("unused"))
