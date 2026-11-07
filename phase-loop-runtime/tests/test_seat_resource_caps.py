from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import time
from types import MappingProxyType, SimpleNamespace

import pytest

from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_profiles
from phase_loop_runtime import seat_route
from phase_loop_runtime import seat_resource_caps as caps
from phase_loop_runtime import seat_resource_caps_enter as enter
from phase_loop_runtime import panel_invoker
from phase_loop_runtime.seat_route_contract import Precondition, RoutePolicy
from phase_loop_runtime.seat_route_contract import DESCEND_CODES, OD10_CLASSES, REMOTE_DESCEND_CODES


pytestmark = pytest.mark.real_seat_caps
_REAL_WHOLE_DEVICE = caps._whole_device


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    state = tmp_path / "state"
    phase = state / "phase-loop"
    phase.mkdir(parents=True, mode=0o700)
    state.chmod(0o700)
    phase.chmod(0o700)
    managed = tmp_path / "managed-missing.json"
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       33554432 kB\n")
    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    staging.mkdir()
    scratch.mkdir()
    monkeypatch.setattr(seat_jail, "state_home", lambda: state)
    monkeypatch.setattr(caps, "MANAGED_RECORD", managed)
    monkeypatch.setattr(caps, "_PROC_MEMINFO", meminfo)
    monkeypatch.setattr(caps, "_automatic_paths", lambda: (staging, scratch))
    monkeypatch.setattr(caps, "_dev_number", lambda _path: (8, 0))
    monkeypatch.setattr(caps, "_whole_device", lambda device, seen=frozenset(): device)
    caps._PARENTS.clear()
    yield phase, staging, scratch
    caps._PARENTS.clear()


def _write_record(path: Path, value, mode: int = 0o600):
    path.write_text(json.dumps(value))
    path.chmod(mode)


def test_defaults_are_the_frozen_finite_table(isolated):
    assert caps.load_caps() == caps.SeatResourceCaps(
        schema="seat_resource_caps.v1",
        memory_max_bytes=4294967296,
        cpu_weight=50,
        cpu_max_percent=200,
        io_weight=50,
        io_max=caps.IoMax(rbps=104857600, wbps=52428800, riops=2000, wiops=1000),
        io_paths=(),
        pids_max=512,
    )
    assert all(value > 0 for key, value in vars(caps.DEFAULT_CAPS).items()
               if key not in {"schema", "io_max", "io_paths"})


def test_operator_record_overrides_and_digest_binds_effective_record(isolated):
    phase, *_ = isolated
    _write_record(phase / "seat-resource-caps.json", {
        "schema": caps.SCHEMA, "memory_max_bytes": 536870912,
        "io_max": {"rbps": 1234}, "io_paths": ["/var/tmp"],
    })
    loaded = caps.load_caps()
    assert loaded.memory_max_bytes == 536870912
    assert loaded.io_max.rbps == 1234
    assert loaded.io_max.wbps == caps.DEFAULT_CAPS.io_max.wbps
    assert caps.caps_sha256(loaded) != caps.caps_sha256(caps.DEFAULT_CAPS)


def test_managed_record_wins_and_never_falls_through(monkeypatch, isolated):
    phase, *_ = isolated
    managed = caps.MANAGED_RECORD
    managed.touch()
    operator = phase / "seat-resource-caps.json"
    _write_record(operator, {"cpu_weight": 999})
    documents = {
        managed: json.dumps({"cpu_weight": 7}).encode(),
        operator: json.dumps({"cpu_weight": 999}).encode(),
    }
    seen = []

    def read(path, *, owner):
        seen.append((path, owner))
        return documents[path]

    monkeypatch.setattr(caps, "_read_regular", read)
    loaded = caps.load_caps()
    assert loaded.cpu_weight == 7
    assert seen == [(managed, 0)]

    monkeypatch.setattr(caps, "_read_regular", lambda *_a, **_k: caps._refuse("unsafe"))
    with pytest.raises(caps.CapsUnavailable):
        caps.load_caps()


@pytest.mark.parametrize("value", [
    {"unknown": 1}, {"memory_max_bytes": "max"}, {"memory_max_bytes": 0},
    {"memory_max_bytes": -1}, {"memory_max_bytes": True}, {"memory_max_bytes": 1.5},
    {"memory_max_bytes": 268435455}, {"cpu_weight": 10001}, {"cpu_max_percent": 9},
    {"io_weight": 0}, {"io_max": {"rbps": 0}}, {"pids_max": 15},
    {"io_paths": ["relative"]}, {"schema": "other"},
])
def test_invalid_record_values_refuse(isolated, value):
    phase, *_ = isolated
    _write_record(phase / "seat-resource-caps.json", value)
    with pytest.raises(caps.CapsUnavailable):
        caps.load_caps()


def test_duplicate_trailing_link_and_writable_records_refuse(isolated):
    phase, *_ = isolated
    record = phase / "seat-resource-caps.json"
    record.write_text('{"cpu_weight":1,"cpu_weight":2}')
    with pytest.raises(caps.CapsUnavailable):
        caps.load_caps()
    record.write_text('{} trailing')
    with pytest.raises(caps.CapsUnavailable):
        caps.load_caps()
    record.unlink()
    target = phase / "target"
    _write_record(target, {})
    record.symlink_to(target)
    with pytest.raises(caps.CapsUnavailable):
        caps.load_caps()
    record.unlink()
    _write_record(record, {}, 0o622)
    with pytest.raises(caps.CapsUnavailable):
        caps.load_caps()


def _readiness_tree(monkeypatch, tmp_path, isolated):
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.controllers").write_text("cpu io memory pids")
    manager = root / "user.slice" / f"user-{os.getuid()}.slice" / f"user@{os.getuid()}.service"
    manager.mkdir(parents=True)
    (manager / "cgroup.controllers").write_text("cpu io memory pids")
    runtime = tmp_path / "run"
    runtime.mkdir()
    (runtime / "bus").touch()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(caps, "_CGROUP_ROOT", root)
    monkeypatch.setattr(caps, "_systemd_run_ready", lambda: True)
    return root, manager, runtime


def test_readiness_requires_hierarchy_manager_controllers_runner_bus_and_devices(monkeypatch,
                                                                                  tmp_path,
                                                                                  isolated):
    root, manager, runtime = _readiness_tree(monkeypatch, tmp_path, isolated)
    assert caps.readiness_code() is None
    for controller in sorted(caps.REQUIRED_CONTROLLERS):
        (manager / "cgroup.controllers").write_text(
            " ".join(sorted(caps.REQUIRED_CONTROLLERS - {controller})))
        assert caps.readiness_code() == caps.CODE
    (manager / "cgroup.controllers").write_text("cpu io memory pids")
    (root / "cgroup.controllers").unlink()
    assert caps.readiness_code() == caps.CODE
    (root / "cgroup.controllers").touch()
    monkeypatch.setattr(caps, "_systemd_run_ready", lambda: False)
    assert caps.readiness_code() == caps.CODE
    monkeypatch.setattr(caps, "_systemd_run_ready", lambda: True)
    (runtime / "bus").unlink()
    assert caps.readiness_code() == caps.CODE
    (runtime / "bus").touch()
    monkeypatch.setattr(caps, "_dev_number", lambda _path: (_ for _ in ()).throw(OSError()))
    assert caps.readiness_code() == caps.CODE


def _sys_node(root: Path, device: str, relative: str) -> Path:
    destination = root / "devices" / relative
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "dev").write_text(device)
    link = root / "dev" / "block" / device
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(destination)
    return destination


def test_device_resolution_whole_partition_and_one_slave_dm(monkeypatch, tmp_path, isolated):
    sysroot = tmp_path / "sys"
    whole = _sys_node(sysroot, "8:0", "block/sda")
    part = _sys_node(sysroot, "8:1", "block/sda/sda1")
    (part / "partition").write_text("1")
    dm = _sys_node(sysroot, "253:0", "virtual/block/dm-0")
    (dm / "dm").mkdir()
    (dm / "slaves").mkdir()
    (dm / "slaves" / "sda1").symlink_to(part)
    monkeypatch.setattr(caps, "_SYS_DEV_BLOCK", sysroot / "dev" / "block")
    monkeypatch.setattr(caps, "_whole_device", _REAL_WHOLE_DEVICE)
    assert caps._whole_device((8, 0)) == (8, 0)
    assert caps._whole_device((8, 1)) == (8, 0)
    assert caps._whole_device((253, 0)) == (8, 0)
    assert whole.exists()


def test_device_mapper_zero_multi_cycle_and_unresolvable_refuse(monkeypatch, tmp_path, isolated):
    sysroot = tmp_path / "sys"
    dm0 = _sys_node(sysroot, "253:0", "virtual/block/dm-0")
    (dm0 / "dm").mkdir(); (dm0 / "slaves").mkdir()
    monkeypatch.setattr(caps, "_SYS_DEV_BLOCK", sysroot / "dev" / "block")
    monkeypatch.setattr(caps, "_whole_device", _REAL_WHOLE_DEVICE)
    with pytest.raises(caps.CapsUnavailable):
        caps._whole_device((253, 0))
    one = _sys_node(sysroot, "8:0", "block/sda")
    two = _sys_node(sysroot, "8:16", "block/sdb")
    (dm0 / "slaves" / "sda").symlink_to(one)
    (dm0 / "slaves" / "sdb").symlink_to(two)
    with pytest.raises(caps.CapsUnavailable):
        caps._whole_device((253, 0))
    (dm0 / "slaves" / "sda").unlink(); (dm0 / "slaves" / "sdb").unlink()
    (dm0 / "slaves" / "self").symlink_to(dm0)
    with pytest.raises(caps.CapsUnavailable):
        caps._whole_device((253, 0))
    with pytest.raises(caps.CapsUnavailable):
        caps._whole_device((9, 9))


def test_major_zero_refuses_even_beside_block_io_path(monkeypatch, isolated):
    _phase, staging, scratch = isolated
    monkeypatch.setattr(caps, "_dev_number", lambda path: (0, 52) if path == staging else (8, 0))
    monkeypatch.setattr(caps, "_tmpfs_carveout", lambda *_: False)
    with pytest.raises(caps.CapsUnavailable):
        caps.io_devices(replace(caps.DEFAULT_CAPS, io_paths=("/var/tmp",)))


@pytest.mark.parametrize("fstype", ["ramfs", "devtmpfs", "overlay", "nfs", "fuse", "btrfs"])
def test_tmpfs_carveout_refuses_every_other_major_zero_type(
    monkeypatch, tmp_path, isolated, fstype,
):
    automatic = tmp_path / "automatic"
    automatic.mkdir()
    device = (0, 52)
    monkeypatch.setattr(caps, "_mount_type", lambda _device: fstype)
    monkeypatch.setattr(caps, "_fstatfs_magic", lambda _fd: caps._TMPFS_MAGIC)
    assert caps._tmpfs_carveout(automatic, device) is False


def test_tmpfs_carveout_requires_matching_descriptor_magic_and_no_symlink(
    monkeypatch, tmp_path, isolated,
):
    automatic = tmp_path / "automatic"
    automatic.mkdir()
    device = (os.major(automatic.stat().st_dev), os.minor(automatic.stat().st_dev))
    monkeypatch.setattr(caps, "_mount_type", lambda _device: "tmpfs")
    monkeypatch.setattr(caps, "_fstatfs_magic", lambda _fd: 0xDEADBEEF)
    assert caps._tmpfs_carveout(automatic, device) is False
    link = tmp_path / "automatic-link"
    link.symlink_to(automatic, target_is_directory=True)
    with pytest.raises(OSError):
        caps._tmpfs_carveout(link, device)


def _parent_files(parent: Path, expected: dict[str, object]):
    parent.mkdir(parents=True, exist_ok=True)
    for name in ("memory.max", "cpu.weight", "cpu.max", "io.weight", "pids.max"):
        (parent / name).write_text(str(expected[name]))
    rows = []
    for device, limits in expected["io.max"].items():
        rows.append(device + " " + " ".join(f"{key}={value}" for key, value in limits.items()))
    (parent / "io.max").write_text("\n".join(rows))
    if expected.get("memory.swap.max") is not None:
        (parent / "memory.swap.max").write_text(str(expected["memory.swap.max"]))


def test_real_helper_refuses_each_missing_or_differing_readback(tmp_path):
    root = tmp_path / "cgroup"
    parent = root / "parent.slice"
    child = parent / "child.scope"
    child.mkdir(parents=True)
    proc = tmp_path / "proc-cgroup"
    proc.write_text("0::/parent.slice/child.scope\n")
    swaps = tmp_path / "swaps"
    swaps.write_text("Filename Type Size Used Priority\n")
    expected = caps._expected(caps.DEFAULT_CAPS, ("8:0",), ())
    _parent_files(parent, expected)
    enter.verify(expected, root=root, proc_cgroup=proc, proc_swaps=swaps)
    for name in ("memory.max", "cpu.weight", "cpu.max", "io.weight", "io.max", "pids.max"):
        original = (parent / name).read_text()
        (parent / name).write_text("different")
        with pytest.raises((ValueError, KeyError)):
            enter.verify(expected, root=root, proc_cgroup=proc, proc_swaps=swaps)
        (parent / name).write_text(original)
        (parent / name).unlink()
        with pytest.raises(OSError):
            enter.verify(expected, root=root, proc_cgroup=proc, proc_swaps=swaps)
        (parent / name).write_text(original)


def _fake_systemd_run(path: Path, root: Path, proc_cgroup: Path, log: Path | None = None):
    log_line = (
        f"pathlib.Path({str(log)!r}).open('a').write(unit + '\\n')"
        if log is not None else ""
    )
    path.write_text(textwrap.dedent(f"""\
        #!/usr/bin/python3
        import os, pathlib, sys
        unit = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--unit='))
        parent = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--slice='))
        {log_line}
        pathlib.Path({str(proc_cgroup)!r}).write_text('0::/' + parent + '/' + unit + '\\n')
        marker = sys.argv.index('--')
        os.execv(sys.argv[marker + 1], sys.argv[marker + 1:])
    """))
    path.chmod(0o755)


def _install_fake_cap_host(monkeypatch, tmp_path, isolated, *, runner_body=None, log=None):
    root, _manager, _runtime = _readiness_tree(monkeypatch, tmp_path, isolated)
    proc_cgroup = tmp_path / "proc-cgroup"
    swaps = tmp_path / "swaps"
    swaps.write_text("Filename Type Size Used Priority\n")
    runner = tmp_path / "systemd-run"
    if runner_body is None:
        _fake_systemd_run(runner, root, proc_cgroup, log=log)
    else:
        runner.write_text(textwrap.dedent(runner_body))
        runner.chmod(0o755)
    monkeypatch.setattr(caps, "_SYSTEMD_RUN", runner)
    monkeypatch.setattr(caps, "_PROC_CGROUP", proc_cgroup)
    monkeypatch.setattr(caps, "_PROC_SWAPS", swaps)
    configured: list[str] = []
    stopped: list[str] = []

    def systemctl(*args, **_kwargs):
        if args[0] == "stop":
            stopped.append(args[1])
            return
        assert args[:2] == ("set-property", "--runtime")
        unit = args[2]
        effective = caps.load_caps()
        devices, carved = caps._device_plan(effective)
        _parent_files(root / unit, caps._expected(effective, devices, carved))
        configured.append(unit)

    monkeypatch.setattr(caps, "_systemctl", systemctl)
    monkeypatch.setattr(caps, "readiness_code", lambda: None)
    return root, proc_cgroup, configured, stopped


def test_capped_popen_real_helper_pid_fd_env_and_one_parent(monkeypatch, tmp_path, isolated):
    root, _manager, _runtime = _readiness_tree(monkeypatch, tmp_path, isolated)
    proc_cgroup = tmp_path / "proc-cgroup"
    swaps = tmp_path / "swaps"; swaps.write_text("Filename Type Size Used Priority\n")
    runner = tmp_path / "systemd-run"
    _fake_systemd_run(runner, root, proc_cgroup)
    monkeypatch.setattr(caps, "_SYSTEMD_RUN", runner)
    monkeypatch.setattr(caps, "_PROC_CGROUP", proc_cgroup)
    monkeypatch.setattr(caps, "_PROC_SWAPS", swaps)
    configured = []

    def systemctl(*args, **_kwargs):
        assert args[:2] == ("set-property", "--runtime") or args[0] == "stop"
        if args[0] == "stop":
            return
        unit = args[2]
        expected = caps._expected(caps.DEFAULT_CAPS, ("8:0",), ())
        _parent_files(root / unit, expected)
        configured.append(unit)

    monkeypatch.setattr(caps, "_systemctl", systemctl)
    monkeypatch.setattr(caps, "readiness_code", lambda: None)
    marker = tmp_path / "marker"
    read_fd, write_fd = os.pipe()
    environment = {"PATH": os.environ.get("PATH", ""), "CAPS_ENV": "exact"}
    script = (
        "import os,sys,pathlib; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())+' '+os.environ['CAPS_ENV']); "
        "os.write(int(sys.argv[2]), b'fd')"
    )
    process = caps.capped_popen(
        [sys.executable, "-c", script, str(marker), str(write_fd)],
        seat_key="gemini:review", env=environment, pass_fds=(write_fd,),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    os.close(write_fd)
    assert os.read(read_fd, 2) == b"fd"
    os.close(read_fd)
    assert process.wait(timeout=10) == 0
    pid, value = marker.read_text().split()
    assert int(pid) == process.pid
    assert value == "exact"
    deadline = time.monotonic() + 5
    while caps._PARENTS and time.monotonic() < deadline:
        time.sleep(0.01)
    assert configured == ["phase-loop-seat-" + caps._unit_key("gemini:review") + ".slice"]


@pytest.mark.parametrize("behavior", ["fail", "hang", "exit-zero"])
def test_capped_popen_reaps_runner_that_never_attests(
    monkeypatch, tmp_path, isolated, behavior,
):
    pid_file = tmp_path / "runner.pid"
    action = {
        "fail": "raise SystemExit(9)",
        "hang": "time.sleep(60)",
        "exit-zero": "raise SystemExit(0)",
    }[behavior]
    runner = f"""\
        #!/usr/bin/python3
        import os, pathlib, time
        pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))
        {action}
    """
    _root, _proc, _configured, stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated, runner_body=runner,
    )
    monkeypatch.setattr(caps, "_ATTEST_TIMEOUT_S", 0.05)
    target = tmp_path / "target-ran"
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        caps.capped_popen(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(target)!r}).touch()"],
            seat_key=f"runner-{behavior}",
        )
    assert refused.value.code == caps.CODE
    assert not target.exists()
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not Path(f"/proc/{pid}").exists()
    assert stopped


def test_concurrent_children_share_one_parent_and_use_distinct_scopes(
    monkeypatch, tmp_path, isolated,
):
    launches = tmp_path / "launches"
    _root, _proc, configured, _stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated, log=launches,
    )
    sleeper = [sys.executable, "-c", "import time; time.sleep(.3)"]
    first = caps.capped_popen(sleeper, seat_key="claude:review")
    second = caps.capped_popen(sleeper, seat_key="claude:review")
    parent = caps._PARENTS["claude:review"]
    assert parent.refs == 2
    assert configured == [parent.unit]
    scopes = launches.read_text().splitlines()
    assert len(scopes) == 2 and len(set(scopes)) == 2
    assert first.wait(timeout=5) == second.wait(timeout=5) == 0


def test_sequential_children_keep_the_same_parent_for_the_live_seat_scope(
    monkeypatch, tmp_path, isolated,
):
    launches = tmp_path / "launches"
    _root, _proc, configured, stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated, log=launches,
    )
    command = [sys.executable, "-c", "pass"]
    with caps._seat_scope("claude:attempt"):
        first = caps.capped_popen(command, seat_key="")
        assert first.wait(timeout=5) == 0
        deadline = time.monotonic() + 5
        while caps._PARENTS["claude:attempt"].refs != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert caps._PARENTS["claude:attempt"].refs == 1
        second = caps.capped_popen(command, seat_key="")
        assert second.wait(timeout=5) == 0
        assert len(configured) == 1 and stopped == []
    deadline = time.monotonic() + 5
    while not stopped and time.monotonic() < deadline:
        time.sleep(0.01)
    assert stopped == configured
    scopes = launches.read_text().splitlines()
    assert len(scopes) == 2 and len(set(scopes)) == 2


def test_live_seat_refuses_a_second_independent_caps_record(
    monkeypatch, tmp_path, isolated,
):
    _install_fake_cap_host(monkeypatch, tmp_path, isolated)
    selected = caps.DEFAULT_CAPS
    monkeypatch.setattr(caps, "load_caps", lambda: selected)
    first = caps.capped_popen(
        [sys.executable, "-c", "import time; time.sleep(.3)"], seat_key="gemini:same",
    )
    selected = replace(caps.DEFAULT_CAPS, cpu_weight=51)
    marker = tmp_path / "second-ran"
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        caps.capped_popen(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
            seat_key="gemini:same",
        )
    assert refused.value.code == caps.CODE and not marker.exists()
    assert first.wait(timeout=5) == 0


def test_tmpfs_carveout_accepts_only_automatic_paths_and_swap_proof(monkeypatch, tmp_path,
                                                                    isolated):
    _phase, staging, scratch = isolated
    monkeypatch.setattr(caps, "_dev_number", lambda _path: (0, 52))
    monkeypatch.setattr(caps, "_tmpfs_carveout", lambda path, _device: path in {staging, scratch})
    devices, carved = caps._device_plan(caps.DEFAULT_CAPS)
    assert devices == ()
    assert carved == (staging, scratch)
    with pytest.raises(caps.CapsUnavailable):
        caps._device_plan(replace(caps.DEFAULT_CAPS, io_paths=(str(tmp_path),)))

    root = tmp_path / "cg"; parent = root / "p"; child = parent / "c"; child.mkdir(parents=True)
    proc = tmp_path / "pc"; proc.write_text("0::/p/c\n")
    swaps = tmp_path / "sw"; swaps.write_text("Filename Type Size Used Priority\n")
    expected = caps._expected(caps.DEFAULT_CAPS, (), carved)
    _parent_files(parent, expected)
    enter.verify(expected, root=root, proc_cgroup=proc, proc_swaps=swaps)
    (parent / "memory.swap.max").write_text("1")
    with pytest.raises(ValueError):
        enter.verify(expected, root=root, proc_cgroup=proc, proc_swaps=swaps)
    (parent / "memory.swap.max").unlink()
    swaps.write_text("Filename Type Size Used Priority\n/dev/zram0 partition 1 0 -2\n")
    with pytest.raises(ValueError):
        enter.verify(expected, root=root, proc_cgroup=proc, proc_swaps=swaps)
    swaps.write_text("Filename Type Size Used Priority\n")
    enter.verify(expected, root=root, proc_cgroup=proc, proc_swaps=swaps)
    (parent / "memory.max").write_text("different")
    with pytest.raises(ValueError):
        enter.verify(expected, root=root, proc_cgroup=proc, proc_swaps=swaps)


def test_tmpfs_refusal_is_typed_and_never_starts_the_target(monkeypatch, tmp_path, isolated):
    monkeypatch.setattr(caps, "_dev_number", lambda _path: (0, 52))
    monkeypatch.setattr(caps, "_tmpfs_carveout", lambda *_a: False)
    started = []
    monkeypatch.setattr(caps.subprocess, "Popen", lambda *_a, **_k: started.append(True))
    marker = tmp_path / "target"
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        caps.capped_popen(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
            seat_key="tmpfs-refusal",
        )
    assert refused.value.code == caps.CODE
    assert started == [] and not marker.exists()


def test_carved_content_cleanup_precedes_parent_collection(monkeypatch, tmp_path, isolated):
    events = []
    carved = (tmp_path / "scratch",)
    parent = caps._Parent("fixture.slice", "digest", refs=1)
    caps._PARENTS["seat"] = parent
    monkeypatch.setattr(caps, "_cleanup_carved_paths", lambda paths: events.append(("clean", paths)))
    monkeypatch.setattr(caps, "_systemctl", lambda *args, **_k: events.append(("stop", args)))
    caps._release_parent("seat", parent, carved)
    assert events == [("clean", carved), ("stop", ("stop", "fixture.slice"))]


def test_code_is_terminal_ordinary_and_every_profile_carries_caps_last():
    from phase_loop_runtime import seat_profiles
    assert OD10_CLASSES[caps.CODE] == "ordinary"
    assert caps.CODE not in DESCEND_CODES | REMOTE_DESCEND_CODES
    for leg in seat_profiles.registered_legs():
        profile = seat_profiles.profile_for(leg)
        assert profile is not None
        assert profile.preconditions[-1].name == "resource_caps"
        assert caps.CODE in profile.notice_codes


def test_caps_refusal_path_enters_the_real_resolver_and_no_later_rung(monkeypatch):
    profile = replace(
        seat_profiles.profile_for("gemini"),
        credential_present=lambda: True,
        variant=None,
        preconditions=(Precondition("resource_caps", lambda: caps.CODE),),
    )
    monkeypatch.setitem(seat_profiles._REGISTRY, "gemini", profile)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    policy = RoutePolicy(
        schema="seat_route_policy.v1", routed_remote=frozenset(),
        exceptions=MappingProxyType({}), capacity_offload=(),
    )
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy)

    class NeverRemote:
        def admit(self, _request):
            raise AssertionError("the remote rung was entered")

    class NeverNative:
        def offer(self, _seat_key, _leg):
            raise AssertionError("the native rung was entered")

    class NeverCapacity:
        def try_lease(self):
            raise AssertionError("the capacity rung was entered")

    monkeypatch.setattr(seat_route, "INACTIVE_REMOTE_RUNG", NeverRemote())
    monkeypatch.setattr(panel_invoker._seat_uid, "SeatIdCapacity", NeverCapacity)
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "gemini", SimpleNamespace(staged_tree_sha256="a" * 64), eligible=True,
        seat_key="gemini:capped", env={}, native=NeverNative(),
    )
    assert route is not None and route.decision.mode == "degraded"
    assert route.decision.steps[-1].step == "L6"
    assert notices == [] and refusal == caps.CODE


def test_launch_boundary_carries_the_live_seat_key_into_capped_popen(
    monkeypatch, tmp_path,
):
    seen = []

    def capped(command, *, seat_key, **kwargs):
        scope = caps._CURRENT_SEAT_SCOPE.get()
        seen.append(seat_key or (None if scope is None else scope.seat_key))
        return subprocess.Popen(command, **kwargs)

    monkeypatch.setattr(caps, "capped_popen", capped)
    with caps._seat_scope("gemini:boundary"):
        process = panel_invoker.launch_provider(
            [sys.executable, "-c", "pass"], seat_caps="", cwd=tmp_path,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    assert process.wait(timeout=5) == 0
    assert seen == ["gemini:boundary"]


def test_sdk_worker_launch_reference_is_owned_and_fixture_digest_is_pinned():
    inventory = json.loads(
        (Path(__file__).parent / "data" / "seat_launch_references.json").read_text()
    )
    assert {
        "count": 1, "function": "_launch_claude_sdk_worker", "module": "panel_invoker",
        "primitive": "subprocess.Popen", "role": "owned",
    } in inventory
    expected = "84c486a669cddd7cc70be8105bb16abd98cf2036835ce5dbd5e96c14fae5a9cb"
    fixture_paths = (
        Path(panel_invoker.__file__).parent / "data" / "claude_sdk" / "launch-v1.json",
        Path(__file__).parent / "data" / "seats_claude_sdk" / "launch-v1.json",
    )
    assert {hashlib.sha256(path.read_bytes()).hexdigest() for path in fixture_paths} == {expected}


def test_sdk_worker_path_enters_caps_with_the_cli_seat_key(monkeypatch):
    from phase_loop_runtime import claude_seat_sdk as sdk
    from phase_loop_runtime import claude_seat_transport as transport

    seen = []

    def refused_start(_argv, *, seat_key, **_kwargs):
        scope = caps._CURRENT_SEAT_SCOPE.get()
        seen.append(seat_key or (None if scope is None else scope.seat_key))
        raise OSError("fixture stops after the capped boundary")

    monkeypatch.setattr(caps, "capped_popen", refused_start)
    monkeypatch.setattr(panel_invoker.os, "access", lambda *_a, **_k: True)
    monkeypatch.setattr(
        panel_invoker, "_claude_sdk_worker_argv",
        lambda *_a, **_k: [sys.executable, "-c", "raise SystemExit(99)"],
    )
    prepared = SimpleNamespace(payload_bytes={name: b"fixture" for name in sdk.WORKER_PAYLOAD})
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(("nsenter", "setpriv"))
    try:
        with caps._seat_scope("claude:sdk"):
            with pytest.raises(transport.TransportRefused):
                panel_invoker._launch_claude_sdk_worker(
                    object(), worker_id=2, prepared=prepared, seat_key="",
                )
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    assert seen == ["claude:sdk"]


def test_source_has_no_disable_environment_or_flag():
    source = Path(caps.__file__).read_text()
    assert "PHASE_LOOP_SEAT_CAPS_DISABLE" not in source
    assert "disable_caps" not in source


def _wait_for_parent_collection(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while caps._PARENTS and time.monotonic() < deadline:
        time.sleep(0.01)
    assert caps._PARENTS == {}


def test_host_probe(monkeypatch):
    if os.environ.get("PHASE_LOOP_SEAT_CAPS_PROBE") != "1":
        pytest.skip("set PHASE_LOOP_SEAT_CAPS_PROBE=1 on the designated seat host")
    if caps.readiness_code() is not None:
        pytest.skip("the designated host has not delegated the required controllers")
    probe_caps = replace(
        caps.DEFAULT_CAPS,
        memory_max_bytes=64 << 20,
        io_max=caps.IoMax(rbps=2 << 20, wbps=2 << 20, riops=2000, wiops=1000),
        pids_max=16,
    )
    devices, carved = caps._device_plan(probe_caps)
    assert devices or carved
    monkeypatch.setattr(caps, "load_caps", lambda: probe_caps)

    def run(argv, seat_key, *, timeout=45, cleanup=()):
        started = time.monotonic()
        with caps._seat_scope(seat_key):
            process = caps.capped_popen(
                argv, seat_key="", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, stderr = process.communicate(timeout=timeout)
            for path in cleanup:
                path.unlink(missing_ok=True)
        elapsed = time.monotonic() - started
        _wait_for_parent_collection()
        return process.returncode, stdout, stderr, elapsed

    staging = caps._automatic_paths()[0]
    stem = f"seat-caps-probe-{os.getpid()}-{time.time_ns()}"
    direct = staging / f"{stem}-direct"
    buffered = staging / f"{stem}-buffered"
    completed = staging / f"{stem}-completed"
    dd = shutil.which("dd")
    if dd is None:
        pytest.fail("the designated seat host has no dd for the direct-I/O cap probe")
    try:
        rc, _stdout, stderr, elapsed = run(
            [dd, "if=/dev/zero", f"of={direct}", "bs=4M", "count=1", "oflag=direct",
             "conv=fsync", "status=none"],
            "host-probe-direct",
        )
        assert rc == 0, stderr
        assert elapsed >= 1.0

        buffered_script = (
            "import os,sys; f=open(sys.argv[1],'wb'); f.write(b'x'*(4<<20)); "
            "f.flush(); os.fsync(f.fileno()); f.close()"
        )
        rc, _stdout, stderr, elapsed = run(
            [sys.executable, "-c", buffered_script, str(buffered)],
            "host-probe-buffered",
        )
        assert rc == 0, stderr
        assert elapsed >= 1.0

        memory_script = (
            "import pathlib,sys,time; x=bytearray(96<<20); "
            "pathlib.Path(sys.argv[1]).touch(); time.sleep(.1)"
        )
        rc, _stdout, _stderr, _elapsed = run(
            [sys.executable, "-c", memory_script, str(completed)],
            "host-probe-memory",
        )
        assert rc != 0 and not completed.exists()

        pids_script = textwrap.dedent("""\
            import os, signal
            children = []
            refused = False
            try:
                for _ in range(64):
                    pid = os.fork()
                    if pid == 0:
                        signal.pause()
                    children.append(pid)
            except OSError:
                refused = True
            finally:
                print('refused' if refused else 'not-refused', flush=True)
                for pid in children:
                    try: os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                for pid in children:
                    try: os.waitpid(pid, 0)
                    except ChildProcessError: pass
        """)
        rc, stdout, stderr, _elapsed = run(
            [sys.executable, "-c", pids_script], "host-probe-pids",
        )
        assert rc == 0, stderr
        assert stdout == b"refused\n"

        if carved:
            tmpfs_output = carved[0] / f"{stem}-tmpfs"
            tmpfs_script = textwrap.dedent("""\
                import pathlib, sys
                relative = next(line.split(':', 2)[2].strip().lstrip('/')
                                for line in pathlib.Path('/proc/self/cgroup').read_text().splitlines()
                                if line.startswith('0::'))
                parent = pathlib.Path('/sys/fs/cgroup') / relative
                swap = (parent.parent / 'memory.swap.current').read_text().strip()
                print('swap=' + swap, flush=True)
                with open(sys.argv[1], 'wb') as target:
                    for _ in range(96):
                        target.write(b'x' * (1 << 20))
                    target.flush()
                pathlib.Path(sys.argv[2]).touch()
            """)
            rc, stdout, _stderr, _elapsed = run(
                [sys.executable, "-c", tmpfs_script, str(tmpfs_output), str(completed)],
                "host-probe-tmpfs", cleanup=(tmpfs_output,),
            )
            assert stdout.startswith(b"swap=0\n")
            assert rc != 0 and not completed.exists()
    finally:
        for path in (direct, buffered, completed):
            path.unlink(missing_ok=True)
