from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys
import threading

import pytest

from phase_loop_runtime import panel_invoker
from phase_loop_runtime import president_adapter
from phase_loop_runtime import sandbox_policy
from phase_loop_runtime import seat_host_namespace as hostns
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_uid


def test_operator_private_dir_creates_owner_only_state_and_atomic_files(tmp_path):
    target = tmp_path / "operator" / "seat-state"
    directory = hostns.operator_private_dir("seat_uid_leases", base=target)
    assert directory == target / "phase-loop" / "seat-uid"
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
    real_uid = os.getuid()
    real_stat, real_lstat, real_fstat = os.stat, os.lstat, os.fstat
    identity = threading.local()
    identities = []
    for index, name in enumerate(("one", "two"), start=1):
        root = tmp_path / name
        env = {
            "HOME": str(root / "home"),
            "XDG_RUNTIME_DIR": str(root / "run"),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "TMPDIR": str(root / "tmp"),
        }
        identities.append({"uid": real_uid + index, "root": root, "env": env})

    def current_uid():
        return getattr(identity, "uid", real_uid)

    def owner_for(path):
        if isinstance(path, int):
            return None
        try:
            resolved = Path(path).absolute()
        except TypeError:
            return None
        for item in identities:
            if resolved == item["root"] or resolved.is_relative_to(item["root"]):
                return item["uid"]
        return None

    def reowned(info, owner):
        if owner is None:
            return info
        fields = list(info)
        fields[4] = owner
        return os.stat_result(fields)

    def fake_stat(path, *args, **kwargs):
        return reowned(real_stat(path, *args, **kwargs), owner_for(path))

    def fake_lstat(path, *args, **kwargs):
        return reowned(real_lstat(path, *args, **kwargs), owner_for(path))

    def fake_fstat(descriptor):
        try:
            path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        except OSError:
            path = None
        return reowned(real_fstat(descriptor), owner_for(path))

    monkeypatch.setattr(os, "getuid", current_uid)
    monkeypatch.setattr(os, "geteuid", current_uid)
    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(os, "lstat", fake_lstat)
    monkeypatch.setattr(os, "fstat", fake_fstat)
    def current_env(name):
        return next(item["env"][name] for item in identities if item["uid"] == current_uid())

    monkeypatch.setattr(
        sandbox_policy, "_user_cache_dir", lambda: Path(current_env("XDG_CACHE_HOME"))
    )
    monkeypatch.setattr(
        sandbox_policy, "legacy_staging_root", lambda: Path(current_env("TMPDIR"))
    )
    monkeypatch.setattr(
        sandbox_policy, "is_ram_backed", lambda path: os.fspath(path) == "/tmp"
    )
    monkeypatch.setattr(sandbox_policy, "_free_bytes", lambda _path: 10**12)
    monkeypatch.setattr(sandbox_policy, "effective_floor_bytes", lambda _path: 0)

    barrier = threading.Barrier(2)
    observed = []
    failures = []

    def worker(index):
        item = identities[index]
        identity.uid = item["uid"]
        env = item["env"]
        runtime_base = Path(env["TMPDIR"]) / f"phase-loop-{item['uid']}"
        runtime_dir = hostns.operator_private_dir("seat_uid_leases", base=runtime_base)
        scratch = sandbox_policy._child_tmp_dir()
        decided = sandbox_policy.child_scratch_env(
            {name: value for name, value in env.items() if name != "TMPDIR"},
            sandbox_policy.CHILD_SCRATCH_RELOCATE,
        )
        native_dir = hostns.operator_private_dir(
            "native_fill", base=Path(env["XDG_STATE_HOME"]) / "native-fill" / "request"
        )
        hostns.write_private_atomic(native_dir, "request.json", b"{}")
        record = panel_invoker.leg_exec_record("gemini", 0, ["agy"], auth_state="healthy")
        record_root = Path(env["XDG_STATE_HOME"]) / "agent-harness" / "seat-records"
        record_path = president_adapter.write_private_record(
            f"leg-{index}.json", record, root=record_root
        )

        with seat_uid.lease_seat_id(1, directory=runtime_dir) as seat_id:
            descriptor = os.open(runtime_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                barrier.wait(timeout=10)
                observed.append({
                    "uid": item["uid"],
                    "env": env,
                    "runtime": runtime_dir,
                    "lock": runtime_dir / f"{seat_id}.lock",
                    "descriptor_target": os.readlink(f"/proc/self/fd/{descriptor}"),
                    "descriptor_inode": real_fstat(descriptor).st_ino,
                    "scratch": scratch.path,
                    "decided_tmp": decided.get("TMPDIR"),
                    "native": native_dir,
                    "record": record_path,
                    "seat_id": seat_id,
                })
                barrier.wait(timeout=10)
                other = identities[1 - index]
                with pytest.raises(seat_jail.SeatSandboxRefused):
                    hostns.operator_private_dir(
                        "seat_uid_leases",
                        base=Path(other["env"]["TMPDIR"]) / f"phase-loop-{other['uid']}",
                    )
                with pytest.raises(ValueError):
                    president_adapter.write_private_record(
                        f"cross-{index}.json",
                        record,
                        root=Path(other["env"]["XDG_STATE_HOME"])
                        / "agent-harness"
                        / "seat-records",
                    )
            finally:
                os.close(descriptor)
                identity.uid = real_uid

    def guarded_worker(index):
        try:
            worker(index)
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=guarded_worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads)
    assert not failures
    assert len(observed) == 2
    assert {item["uid"] for item in observed} == {entry["uid"] for entry in identities}
    for name in ("HOME", "XDG_RUNTIME_DIR", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"):
        assert observed[0]["env"][name] != observed[1]["env"][name]
    for name in ("runtime", "lock", "descriptor_target", "descriptor_inode", "scratch", "native", "record"):
        assert observed[0][name] != observed[1][name]
    assert {item["seat_id"] for item in observed} == {1}
    assert all(item["decided_tmp"] == str(item["scratch"]) for item in observed)
    assert all(item["record"].is_file() for item in observed)


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

    monkeypatch.setattr(
        hostns.pwd,
        "getpwall",
        lambda: [SimpleNamespace(pw_uid=0), SimpleNamespace(pw_uid=1000)],
    )
    subgid.write_text("operator:400000:100\nother:400050:100\n")
    assert not hostns.subordinate_ranges_disjoint(1000, subuid=subuid, subgid=subgid)

    subgid.write_text("operator:400000:100\nother:600000:100\n")
    monkeypatch.setattr(hostns.grp, "getgrall", lambda: [SimpleNamespace(gr_gid=400020)])
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
    _account_inventory(monkeypatch)
    subuid.write_text("1000:100000:100\nother:100050:100\n")
    subgid.write_text("1000:200000:100\nother:300000:100\n")
    monkeypatch.setattr(seat_uid, "_privileged_helper", lambda _path: True)
    assert not seat_uid.seat_uid_available(
        uid=1000, subuid=subuid, subgid=subgid, newuidmap="newuidmap", newgidmap="newgidmap"
    )
    assert seat_jail.seat_sandbox_capable(
        host_capable=lambda: True,
        tiocsti=lambda: True,
        seat_uid_available=lambda: seat_uid.seat_uid_available(
            uid=1000,
            subuid=subuid,
            subgid=subgid,
            newuidmap="newuidmap",
            newgidmap="newgidmap",
        ),
    ) == "seat_sandbox_unavailable_seat_uid"


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

    fallback = tmp_path / "fallback"
    monkeypatch.setattr(sandbox_policy, "_user_cache_dir", lambda: Path("/dev"))
    monkeypatch.setattr(sandbox_policy, "legacy_staging_root", lambda: fallback)
    monkeypatch.setattr(sandbox_policy, "is_ram_backed", lambda _path: False)
    monkeypatch.setattr(sandbox_policy, "_free_bytes", lambda _path: 10**12)
    monkeypatch.setattr(sandbox_policy, "effective_floor_bytes", lambda _path: 0)
    location = sandbox_policy._child_tmp_dir()
    assert location.path == fallback / f"phase-loop-{os.getuid()}" / "tmp"
    assert not location.degraded


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


def test_precreated_fallback_directory_is_refused_at_every_private_component(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(seat_uid.tempfile, "gettempdir", lambda: str(tmp_path))
    fallback = tmp_path / f"phase-loop-{os.getuid()}"
    fallback.mkdir(mode=0o755)
    fallback.chmod(0o755)
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        seat_uid.seat_runtime_dir()
    assert refused.value.code == "seat_sandbox_refused:identity"


def test_concurrent_first_use_creates_one_private_directory(tmp_path):
    for index in range(50):
        barrier = threading.Barrier(4)
        refused: list[BaseException] = []

        def worker():
            barrier.wait(timeout=10)
            try:
                hostns.operator_private_dir("seat_uid_leases", base=tmp_path / str(index))
            except seat_jail.SeatSandboxRefused as exc:
                refused.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert not refused


def test_native_fill_request_directory_keeps_the_operator_chosen_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    root.chmod(0o775)
    request = root / "native-fill" / "request-id"
    assert hostns.operator_private_dir("native_fill", base=request) == request
    hostns.write_private_atomic(request, "request.json", b"{}")
    assert (request / "request.json").stat().st_mode & 0o777 == 0o600

    existing = tmp_path / "older" / "native-fill" / "request-id"
    existing.mkdir(parents=True)
    existing.chmod(0o755)
    assert hostns.operator_private_dir("native_fill", base=existing) == existing

    shared = tmp_path / "shared" / "native-fill" / "request-id"
    shared.mkdir(parents=True)
    shared.chmod(0o775)
    with pytest.raises(seat_jail.SeatSandboxRefused):
        hostns.operator_private_dir("native_fill", base=shared)


def test_scratch_helpers_import_without_account_databases():
    code = (
        "import sys\nsys.modules['pwd'] = None\nsys.modules['grp'] = None\n"
        "from phase_loop_runtime import seat_host_namespace as h\n"
        "assert h.scratch_root_allowed(__import__('pathlib').Path('/var'))\n"
        "assert not h.subordinate_ranges_disjoint(1000)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=os.environ)
