"""Native protected-handle prerequisite witnesses, not full HOST acceptance."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import time

import pytest

from phase_loop_runtime.windows_storage import BoundDirectory


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native NTFS storage proof")


def test_private_directory_record_acl_and_restart(tmp_path):
    private = tmp_path / "private é"
    with BoundDirectory(private, create_private=True) as bound:
        identity = bound.create_record("record.json", b'{"complete":true}\n')
        assert len(identity) == 3
        assert bound.read_record("record.json") == b'{"complete":true}\n'
        with pytest.raises(OSError):
            bound.create_record("record.json", b"replacement must fail")
    assert (private / "record.json").read_bytes() == b'{"complete":true}\n'
    with BoundDirectory(private, create_private=True) as rebound:
        rebound.create_record("second.json", b"second")


def test_existing_inherited_acl_is_rejected_without_mutation(tmp_path):
    directory = tmp_path / "inherited"
    directory.mkdir()
    with pytest.raises(PermissionError, match="ACL|owner"):
        BoundDirectory(directory, create_private=True)
    assert list(directory.iterdir()) == []


def test_held_ancestor_cannot_be_renamed_or_deleted(tmp_path):
    private = tmp_path / "private"
    with BoundDirectory(private, create_private=True) as bound:
        with pytest.raises(OSError):
            private.rename(tmp_path / "replacement")
        with pytest.raises(OSError):
            private.rmdir()
        bound.create_record("safe", b"same directory")
    assert (private / "safe").read_bytes() == b"same directory"


def test_junction_is_rejected_without_external_write(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = tmp_path / "junction"
    result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    try:
        with pytest.raises(OSError, match="reparse"):
            BoundDirectory(junction, create_private=True)
        assert list(outside.iterdir()) == []
    finally:
        junction.rmdir()


def test_failed_flush_never_reports_success(tmp_path, monkeypatch):
    with BoundDirectory(tmp_path / "private", create_private=True) as bound:
        def failed(_):
            ctypes.set_last_error(5)
            return 0
        monkeypatch.setattr(bound.kernel, "FlushFileBuffers", failed)
        with pytest.raises(OSError):
            bound.create_record("unacknowledged", b"written but unacknowledged")


def test_handle_bound_replacement_and_failed_rename(tmp_path, monkeypatch):
    private = tmp_path / "private"
    with BoundDirectory(private, create_private=True) as bound:
        before = bound.create_record("record.json", b"before")
        after = bound.create_record("record.json", b"after", replace=True)
        assert before != after
        assert bound.read_record("record.json") == b"after"
        def failed(*_):
            return -1073741790  # STATUS_ACCESS_DENIED
        monkeypatch.setattr(bound.kernel, "NtSetInformationFile", failed)
        with pytest.raises(OSError):
            bound.create_record("record.json", b"must not publish", replace=True)
        assert bound.read_record("record.json") == b"after"


def test_namespace_flush_failure_is_not_acknowledged(tmp_path, monkeypatch):
    with BoundDirectory(tmp_path / "private", create_private=True) as bound:
        def failed():
            raise OSError("controlled directory flush failure")
        monkeypatch.setattr(bound, "flush", failed)
        with pytest.raises(OSError, match="directory flush"):
            bound.create_record("record.json", b"not acknowledged")


def test_broker_atomic_write_uses_private_nested_storage(tmp_path):
    from phase_loop_runtime.convergence.broker.live import _atomic_write_json
    target = tmp_path / "new" / "nested" / "record.json"
    _atomic_write_json(target, {"generation": 1})
    _atomic_write_json(target, {"generation": 2})
    with BoundDirectory(target.parent, create_private=True) as bound:
        assert json.loads(bound.read_record(target.name)) == {"generation": 2}


def test_event_log_repairs_torn_tail_and_replays_after_restart(tmp_path):
    from phase_loop_runtime.convergence.event_log import record_intent, record_outcome, read_convergence_events, recover_train_state
    from phase_loop_runtime.train_ledger import CoordinatorEventKind
    from test_convergence_event_log import _event
    target = tmp_path / "private" / "events.jsonl"
    intent = _event(CoordinatorEventKind.INTENT)
    outcome = _event(CoordinatorEventKind.OUTCOME)
    record_intent(target, intent)
    with target.open("ab") as stream:
        stream.write(b'{"torn":')
    record_outcome(target, outcome)
    record_outcome(target, outcome)
    events = read_convergence_events(target)
    assert events == (intent, outcome)
    assert not recover_train_state(events).pending_attempts


def test_event_writer_waits_for_other_process_binding(tmp_path):
    private = tmp_path / "private"
    ready = tmp_path / "ready"
    script = """
from pathlib import Path
import sys
from phase_loop_runtime.convergence.event_log import record_intent
from phase_loop_runtime.train_ledger import CoordinatorEventKind
from test_convergence_event_log import _event
Path(sys.argv[2]).touch()
record_intent(Path(sys.argv[1]), _event(CoordinatorEventKind.INTENT))
"""
    with BoundDirectory(private, create_private=True):
        child = subprocess.Popen([sys.executable, "-c", script, str(private / "events.jsonl"), str(ready)])
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        time.sleep(0.1)
        assert child.poll() is None
    assert child.wait(timeout=10) == 0


def test_pinned_directory_rejects_reparse_mutation(tmp_path):
    from ctypes import wintypes
    from phase_loop_runtime.windows_storage import _apis
    outside = tmp_path / "outside"
    outside.mkdir()
    kernel, _ = _apis()
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    substitute = ("\\??\\" + str(outside)).encode("utf-16le")
    display = str(outside).encode("utf-16le")
    names = substitute + b"\0\0" + display + b"\0\0"
    data = struct.pack("<IHHHHHH", 0xA0000003, 8 + len(names), 0, 0, len(substitute), len(substitute) + 2, len(display)) + names
    def mutate(path):
        handle = kernel.CreateFileW(str(path), 0x40000000, 3, None, 3, 0x02200000, None)
        assert handle != ctypes.c_void_p(-1).value
        try:
            count = wintypes.DWORD()
            success = kernel.DeviceIoControl(handle, 0x900A4, data, len(data), None, 0, ctypes.byref(count), None)
            return bool(success), ctypes.get_last_error()
        finally:
            kernel.CloseHandle(handle)
    control = tmp_path / "empty-control"
    control.mkdir()
    assert mutate(control)[0], "The negative control must be able to create a junction"
    control.rmdir()
    with BoundDirectory(tmp_path / "private", create_private=True) as bound:
        success, error = mutate(bound.path)
        assert not success and error == 145  # ERROR_DIR_NOT_EMPTY
        bound.create_record("safe", b"local")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("name", ["../escape", "stream:alternate", "trailing.", "bad\\name"])
def test_invalid_names_do_not_write(tmp_path, name):
    private = tmp_path / "private"
    with BoundDirectory(private, create_private=True) as bound:
        with pytest.raises(ValueError):
            bound.create_record(name, b"never written")
    assert [path.name for path in private.iterdir()] == [".directory-binding"]


@pytest.mark.parametrize("completed", [False, True])
def test_reclamation_requires_protected_completion_record(tmp_path, completed):
    from phase_loop_runtime.file_lock import open_generation_lease
    from phase_loop_runtime.phase_worktree_executor import LeaseAuthority, PhaseWorktreeHandle, reclaim_phase_worktree
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init",), ("config", "user.email", "test@example.invalid"),
                 ("config", "user.name", "Native proof"), ("commit", "--allow-empty", "-m", "fixture")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    worktree = tmp_path / "worktree"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "proof", str(worktree)], check=True, capture_output=True)
    lease = tmp_path / "generation.lock"
    fd = open_generation_lease(lease)
    info = os.fstat(fd)
    identity = f"generation:{info.st_dev}:{info.st_ino}"
    authority = LeaseAuthority(lease, fd, identity, "generation")
    authority.close()
    marker = lease.with_name(lease.name + ".supervision")
    with BoundDirectory(marker, create_private=True) as bound:
        pending = {"identity": identity, "nonce": "controlled-proof"}
        bound.create_record("pending.json", json.dumps(pending).encode())
        if completed:
            bound.create_record("complete.json", json.dumps({**pending, "quiescent": True}).encode())
    handle = PhaseWorktreeHandle("PROOF", worktree, "proof", "master", base, "generation", authority, identity)
    result = reclaim_phase_worktree(repo, handle)
    assert result.reclaimed is completed
    assert worktree.exists() is (not completed)
    if not completed:
        assert result.reason == "supervision_unproven"
