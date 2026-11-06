from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import threading

import pytest

from phase_loop_runtime import sandbox_policy
from phase_loop_runtime import seat_host_namespace as hostns
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_uid


def test_operator_private_dir_creates_owner_only_state_and_atomic_files(tmp_path):
    target = tmp_path / "operator" / "seat-state"
    directory = hostns.operator_private_dir("seat_uid_leases", base=target)
    assert directory == target
    assert directory.stat().st_mode & 0o777 == 0o700

    hostns.write_private_atomic(directory, "record.json", b'{"ok":true}\n')
    record = directory / "record.json"
    assert record.read_bytes() == b'{"ok":true}\n'
    assert record.stat().st_mode & 0o777 == 0o600
    assert not list(directory.glob(".*.tmp-*"))


@pytest.mark.parametrize("shape", ["mode", "link"])
def test_foreign_or_linked_private_state_is_refused(tmp_path, shape):
    target = tmp_path / "state"
    if shape == "mode":
        target.mkdir(mode=0o755)
        target.chmod(0o755)
    else:
        real = tmp_path / "real"
        real.mkdir(mode=0o700)
        target.symlink_to(real, target_is_directory=True)
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        hostns.operator_private_dir("seat_uid_leases", base=target)
    assert refused.value.code == "seat_sandbox_refused:identity"


def test_planted_native_fill_link_is_refused(tmp_path):
    root = tmp_path / "output"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir(mode=0o700)
    (root / "native-fill").symlink_to(outside, target_is_directory=True)
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        hostns.operator_private_dir(
            "native_fill", base=root / "native-fill" / "request-id"
        )
    assert refused.value.code == "seat_sandbox_refused:identity"


def test_two_identity_namespaces_share_no_paths_locks_or_descriptors(tmp_path, monkeypatch):
    first = tmp_path / "one/state"
    second = tmp_path / "two/state"
    first_dir = hostns.operator_private_dir("seat_uid_leases", base=first)
    second_dir = hostns.operator_private_dir("seat_uid_leases", base=second)
    barrier = threading.Barrier(2)
    observed: list[tuple[Path, int, int]] = []

    def worker(directory: Path):
        with seat_uid.lease_seat_id(1, directory=directory) as seat_id:
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                barrier.wait(timeout=10)
                observed.append((directory, seat_id, descriptor))
            finally:
                os.close(descriptor)

    threads = [threading.Thread(target=worker, args=(path,)) for path in (first_dir, second_dir)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert len(observed) == 2
    assert observed[0][0] != observed[1][0]
    assert observed[0][2] != observed[1][2]
    assert {item[1] for item in observed} == {1}

    monkeypatch.setattr(hostns, "_euid", lambda: os.geteuid() + 1)
    with pytest.raises(seat_jail.SeatSandboxRefused):
        hostns.operator_private_dir("seat_uid_leases", base=first_dir)


def _account_inventory(monkeypatch, operator=1000):
    monkeypatch.setattr(hostns, "_uid", lambda: operator)
    monkeypatch.setattr(hostns.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_name="operator"))
    monkeypatch.setattr(
        hostns.pwd,
        "getpwall",
        lambda: [SimpleNamespace(pw_uid=0), SimpleNamespace(pw_uid=operator)],
    )
    monkeypatch.setattr(
        hostns.grp,
        "getgrall",
        lambda: [SimpleNamespace(gr_gid=0), SimpleNamespace(gr_gid=operator)],
    )


def test_subordinate_ranges_must_be_disjoint_from_accounts_and_other_ranges(
    tmp_path, monkeypatch
):
    _account_inventory(monkeypatch)
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    subuid.write_text("operator:100000:100\n1000:200000:100\nother:300000:100\n")
    subgid.write_text("operator:400000:100\n1000:500000:100\nother:600000:100\n")
    assert hostns.subordinate_ranges_disjoint(1000, subuid=subuid, subgid=subgid)

    subuid.write_text("operator:100000:100\nother:100050:100\n")
    assert not hostns.subordinate_ranges_disjoint(1000, subuid=subuid, subgid=subgid)

    monkeypatch.setattr(
        hostns.pwd,
        "getpwall",
        lambda: [SimpleNamespace(pw_uid=100020)],
    )
    subuid.write_text("operator:100000:100\nother:300000:100\n")
    assert not hostns.subordinate_ranges_disjoint(1000, subuid=subuid, subgid=subgid)


def test_malformed_subordinate_inventory_fails_closed(tmp_path, monkeypatch):
    _account_inventory(monkeypatch)
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    subuid.write_text("operator:not-an-int:100\n")
    subgid.write_text("operator:400000:100\n")
    assert not hostns.subordinate_ranges_disjoint(1000, subuid=subuid, subgid=subgid)


def test_seat_uid_availability_includes_the_disjointness_conjunct(tmp_path, monkeypatch):
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    subuid.write_text("operator:100000:100\n")
    subgid.write_text("operator:200000:100\n")
    monkeypatch.setattr(seat_uid, "_privileged_helper", lambda _path: True)
    monkeypatch.setattr(
        seat_uid,
        "subordinate_range",
        lambda _path, _uid=None: seat_uid.SubordinateRange(100000, 100),
    )
    monkeypatch.setattr(hostns, "subordinate_ranges_disjoint", lambda *_args, **_kwargs: False)
    assert not seat_uid.seat_uid_available(
        uid=1000, subuid=subuid, subgid=subgid, newuidmap="newuidmap", newgidmap="newgidmap"
    )


def test_seat_runtime_fallback_is_private(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(seat_uid.tempfile, "gettempdir", lambda: str(tmp_path))
    path = seat_uid.seat_runtime_dir()
    assert path == tmp_path / f"phase-loop-{os.getuid()}" / "phase-loop" / "seat-uid"
    assert path.stat().st_mode & 0o777 == 0o700


def test_scratch_roots_under_device_and_kernel_trees_are_skipped(tmp_path, monkeypatch):
    assert not hostns.scratch_root_allowed(Path("/dev/phase-loop"))
    assert not hostns.scratch_root_allowed(Path("/proc/phase-loop"))
    assert not hostns.scratch_root_allowed(Path("/sys/phase-loop"))
    assert hostns.scratch_root_allowed(tmp_path)

    monkeypatch.setattr(sandbox_policy, "_user_cache_dir", lambda: None)
    monkeypatch.setattr(sandbox_policy, "legacy_staging_root", lambda: Path("/dev"))
    assert sandbox_policy.child_scratch_candidates() == []


def test_agent_harness_1108_disposition_names_are_closed():
    assert tuple(hostns.ISSUE_1108_DISPOSITIONS) == (
        "Claude channel sidecar port",
        "Task-message broker port",
        "President native-fill files",
        "Staging free-space floor",
        "CI offload lock",
        "TMPDIR under /dev",
        "Seat-uid lease fallback directory",
        "Overlapping subordinate ranges",
    )
