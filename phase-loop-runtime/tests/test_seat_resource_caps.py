from __future__ import annotations

import ast
from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from types import MappingProxyType, SimpleNamespace

import pytest

from tree_proof_fakes import attach_pipe_proof
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
    (manager / "cgroup.controllers").unlink()
    manager.rmdir()
    assert caps.readiness_code() == caps.CODE
    manager.mkdir()
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


def test_realized_parent_requires_every_controller_level_and_cap_file(
    monkeypatch, tmp_path, isolated,
):
    _readiness_tree(monkeypatch, tmp_path, isolated)
    unit = "phase-loop-seat-0123456789abcdef01234567.slice"
    expected = caps._expected(caps.DEFAULT_CAPS, ("8:0",), ())
    parent = _realized_parent_files(unit, expected)
    chain = caps._seat_slice_chain(unit)
    assert parent == chain[-1]
    assert caps._realized_parent_ready(unit, ())

    for path in chain:
        original = (path / "cgroup.controllers").read_text()
        (path / "cgroup.controllers").write_text(original.replace("io", ""))
        assert not caps._realized_parent_ready(unit, ())
        (path / "cgroup.controllers").write_text(original)
    for path in chain[:-1]:
        original = (path / "cgroup.subtree_control").read_text()
        (path / "cgroup.subtree_control").write_text(original.replace("io", ""))
        assert not caps._realized_parent_ready(unit, ())
        (path / "cgroup.subtree_control").write_text(original)
    for name in (
        "memory.max", "memory.swap.max", "cpu.weight", "cpu.max",
        "io.weight", "io.max", "pids.max",
    ):
        target = parent / name
        original = target.read_text()
        target.unlink()
        assert not caps._realized_parent_ready(unit, ())
        target.write_text(original)


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
    device = (os.major(automatic.stat().st_dev), os.minor(automatic.stat().st_dev))
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


def test_device_number_follows_a_staging_symlink(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    calls = []
    real_stat = os.stat

    def stat_path(path, **kwargs):
        calls.append((path, kwargs))
        return real_stat(target)

    monkeypatch.setattr(caps.os, "stat", stat_path)
    caps._dev_number(link)
    assert calls == [(link, {})]


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


def _expected_from_properties(properties: tuple[str, ...], *, io_limits=None) -> dict[str, object]:
    values = dict(item.split("=", 1) for item in properties)
    expected: dict[str, object] = {
        "memory.max": values["MemoryMax"],
        "cpu.weight": values["CPUWeight"],
        "cpu.max": f"{int(values['CPUQuota'].removesuffix('%')) * 1000} {caps._CPU_PERIOD}",
        "io.weight": values["IOWeight"],
        "io.max": {},
        "pids.max": values["TasksMax"],
    }
    if "MemorySwapMax" in values:
        expected["memory.swap.max"] = values["MemorySwapMax"]
    io_names = {
        "IOReadBandwidthMax": "rbps", "IOWriteBandwidthMax": "wbps",
        "IOReadIOPSMax": "riops", "IOWriteIOPSMax": "wiops",
    }
    if io_limits is None:
        io_limits = {}
    for property_value in properties:
        name, _, setting = property_value.partition("=")
        if name not in io_names:
            continue
        limits = io_limits.setdefault(name, {})
        if not setting:
            limits.clear()
            continue
        device, limit = setting.split(" ", 1)
        limits[Path(device).name] = limit
    rows: dict[str, dict[str, str]] = {}
    for name, limits in io_limits.items():
        for device, limit in limits.items():
            rows.setdefault(device, {})[io_names[name]] = limit
    expected["io.max"] = rows
    return expected


def _realized_parent_files(unit: str, expected: dict[str, object]) -> Path:
    chain = caps._seat_slice_chain(unit)
    rendered = " ".join(sorted(caps.REQUIRED_CONTROLLERS))
    for path in chain:
        path.mkdir(parents=True, exist_ok=True)
        (path / "cgroup.controllers").write_text(rendered)
    for path in chain[:-1]:
        (path / "cgroup.subtree_control").write_text(rendered)
    _parent_files(chain[-1], expected)
    return chain[-1]


def test_parent_requests_io_before_systemd_realizes_the_slice(
    monkeypatch, tmp_path, isolated,
):
    _readiness_tree(monkeypatch, tmp_path, isolated)
    calls = []

    def systemctl(*args, **_kwargs):
        calls.append(args)
        if args[:2] == ("set-property", "--runtime"):
            _realized_parent_files(args[2], _expected_from_properties(args[3:]))

    monkeypatch.setattr(caps, "_systemctl", systemctl)
    parent, child = caps._acquire_parent(
        "io-propagation", caps.DEFAULT_CAPS, ("8:0",), (), child=False,
    )
    try:
        assert child is None
        assert calls[0][:3] == ("set-property", "--runtime", parent.unit)
        properties = calls[0][3:]
        assert f"IOWeight={caps.DEFAULT_CAPS.io_weight}" in properties
        assert {
            "IOReadBandwidthMax", "IOWriteBandwidthMax",
            "IOReadIOPSMax", "IOWriteIOPSMax",
        } == {item.split("=", 1)[0] for item in properties if item.startswith("IO") and
              not item.startswith("IOWeight=")}
        assert calls[1] == ("start", parent.unit)
    finally:
        caps._release_parent(parent)


def test_real_helper_refuses_each_missing_or_differing_readback(tmp_path):
    root = tmp_path / "cgroup"
    parent = root / "parent.slice"
    child = parent / "child.scope"
    child.mkdir(parents=True)
    proc = tmp_path / "proc-cgroup"
    proc.write_text("0::/parent.slice/child.scope\n")
    expected = caps._expected(caps.DEFAULT_CAPS, ("8:0",), ())
    _parent_files(parent, expected)
    enter.verify(expected, root=root, proc_cgroup=proc)
    for name in (
        "memory.max", "memory.swap.max", "cpu.weight", "cpu.max",
        "io.weight", "io.max", "pids.max",
    ):
        original = (parent / name).read_text()
        (parent / name).write_text("different")
        with pytest.raises((ValueError, KeyError)):
            enter.verify(expected, root=root, proc_cgroup=proc)
        (parent / name).write_text(original)
        (parent / name).unlink()
        with pytest.raises(enter.ControllerUnavailable):
            enter.verify(expected, root=root, proc_cgroup=proc)
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
        parts = parent.removesuffix('.slice').split('-')
        parent_path = pathlib.Path('user.slice', 'user-{os.getuid()}.slice',
                                   'user@{os.getuid()}.service')
        for index in range(1, len(parts) + 1):
            parent_path /= '-'.join(parts[:index]) + '.slice'
        pathlib.Path({str(proc_cgroup)!r}).write_text(
            '0::/' + str(parent_path / unit) + '\\n')
        # The scope systemd would create, and this pid's own /proc/<pid>/cgroup view.
        scope = pathlib.Path({str(root)!r}, parent_path, unit)
        scope.mkdir(parents=True, exist_ok=True)
        (scope / 'cgroup.events').write_text('populated 1\\nfrozen 0\\n')
        (scope / 'cgroup.kill').touch()
        pathlib.Path({str(proc_cgroup)!r} + '.' + str(os.getpid())).write_text(
            '0::/' + str(parent_path / unit) + '\\n')
        marker = sys.argv.index('--')
        os.execv(sys.argv[marker + 1], sys.argv[marker + 1:])
    """))
    path.chmod(0o755)


def _seam_proc_cgroup(monkeypatch, proc_cgroup: Path) -> None:
    """Read the fake runner's per-pid ``/proc/<pid>/cgroup`` view."""
    def proc_cgroup_of(pid):
        text = Path(f"{proc_cgroup}.{pid}").read_text()
        return next(line[3:] for line in text.splitlines() if line.startswith("0::"))

    monkeypatch.setattr(caps, "_proc_cgroup_of", proc_cgroup_of, raising=False)


def _install_fake_cap_host(monkeypatch, tmp_path, isolated, *, runner_body=None, log=None):
    root, _manager, _runtime = _readiness_tree(monkeypatch, tmp_path, isolated)
    proc_cgroup = tmp_path / "proc-cgroup"
    runner = tmp_path / "systemd-run"
    if runner_body is None:
        _fake_systemd_run(runner, root, proc_cgroup, log=log)
    else:
        runner.write_text(textwrap.dedent(runner_body))
        runner.chmod(0o755)
    monkeypatch.setattr(caps, "_SYSTEMD_RUN", runner)
    monkeypatch.setattr(caps, "_PROC_CGROUP", proc_cgroup)
    _seam_proc_cgroup(monkeypatch, proc_cgroup)
    configured: list[str] = []
    stopped: list[str] = []

    runtime_control = _runtime / "systemd/user.control"
    runtime_control.mkdir(parents=True)

    def systemctl(*args, **_kwargs):
        if args[:2] == ("show", "--property=UnitPath"):
            return SimpleNamespace(returncode=0, stdout=str(runtime_control).encode())
        if args[0] == "show":
            active = args[-1] not in stopped
            return SimpleNamespace(returncode=0, stdout=(
                b"LoadState=loaded\nJob=\nActiveState=" + (b"active" if active else b"inactive")
            ))
        if args[0] == "stop":
            unit = args[1]
            stopped.append(unit)
            if caps._ISOLATED_UNIT.fullmatch(unit):
                shutil.rmtree(caps._seat_slice_chain(unit)[-1], ignore_errors=True)
            return SimpleNamespace(returncode=0)
        if args[0] == "start":
            return
        assert args[:2] == ("set-property", "--runtime")
        unit = args[2]
        _realized_parent_files(unit, _expected_from_properties(args[3:]))
        configured.append(unit)

    monkeypatch.setattr(caps, "_systemctl", systemctl)
    monkeypatch.setattr(caps, "readiness_code", lambda: None)
    return root, proc_cgroup, configured, stopped


def test_capped_popen_real_helper_pid_fd_env_and_one_parent(monkeypatch, tmp_path, isolated):
    root, _manager, _runtime = _readiness_tree(monkeypatch, tmp_path, isolated)
    proc_cgroup = tmp_path / "proc-cgroup"
    runner = tmp_path / "systemd-run"
    _fake_systemd_run(runner, root, proc_cgroup)
    monkeypatch.setattr(caps, "_SYSTEMD_RUN", runner)
    monkeypatch.setattr(caps, "_PROC_CGROUP", proc_cgroup)
    _seam_proc_cgroup(monkeypatch, proc_cgroup)
    configured = []

    def systemctl(*args, **_kwargs):
        assert args[:2] == ("set-property", "--runtime") or args[0] in {"start", "stop"}
        if args[0] in {"start", "stop"}:
            return
        unit = args[2]
        io_properties = [value for value in args[3:] if value.startswith(("IORead", "IOWrite"))]
        assert all(value.endswith("=") or f"={caps._DEV_BLOCK / '8:0'} " in value
                   for value in io_properties)
        expected = caps._expected(caps.DEFAULT_CAPS, ("8:0",), ())
        _realized_parent_files(unit, expected)
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
    action = {
        "fail": "raise SystemExit(9)",
        "hang": "time.sleep(60)",
        "exit-zero": "raise SystemExit(0)",
    }[behavior]
    runner = f"""\
        #!/usr/bin/python3
        import time
        {action}
    """
    _root, _proc, _configured, stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated, runner_body=runner,
    )
    # Only the hung runner needs the short timeout. Exit cases must reach their
    # explicit exit, rather than be terminated during interpreter startup.
    monkeypatch.setattr(caps, "_ATTEST_TIMEOUT_S", 0.05 if behavior == "hang" else 5)
    processes = []
    real_popen = subprocess.Popen

    def record_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(caps.subprocess, "Popen", record_popen)
    target = tmp_path / "target-ran"
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        caps.capped_popen(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(target)!r}).touch()"],
            seat_key=f"runner-{behavior}",
        )
    assert refused.value.code == caps.CODE
    assert not target.exists()
    (process,) = processes
    # Popen supplies the PID even if timeout kills the runner before Python starts.
    # Check the stored status before polling so this test cannot reap it itself.
    assert process.returncode is not None
    if behavior != "hang":
        assert process.returncode == (9 if behavior == "fail" else 0)
    pid = process.pid
    deadline = time.monotonic() + 5
    while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not Path(f"/proc/{pid}").exists()
    assert stopped


def test_capped_popen_surfaces_the_helpers_readback_failure(
    monkeypatch, tmp_path, isolated,
):
    root, _proc, _configured, _stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated,
    )

    def systemctl(*args, **_kwargs):
        if args[0] == "stop":
            return
        if args[0] == "start":
            return
        expected = _expected_from_properties(args[3:])
        parent = _realized_parent_files(args[2], expected)
        (parent / "io.max").write_text("")

    monkeypatch.setattr(caps, "_systemctl", systemctl)
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        caps.capped_popen(
            [sys.executable, "-c", "raise AssertionError('target must not run')"],
            seat_key="helper-diagnostic", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    assert refused.value.code == caps.CODE
    assert str(refused.value).endswith(
        "child stderr: seat cap attestation failed: io.max readback mismatch"
    )


@pytest.mark.parametrize("missing", ["io.weight", "memory.swap.max"])
def test_missing_realized_cap_refuses_before_the_child_launch(
    monkeypatch, tmp_path, isolated, missing,
):
    _root, _proc, _configured, stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated,
    )
    launches = []

    def systemctl(*args, **_kwargs):
        if args[0] == "stop":
            stopped.append(args[1])
            return
        if args[0] == "start":
            return
        parent = _realized_parent_files(args[2], _expected_from_properties(args[3:]))
        (parent / missing).unlink()

    monkeypatch.setattr(caps, "_systemctl", systemctl)
    monkeypatch.setattr(
        caps.subprocess, "Popen", lambda *_args, **_kwargs: launches.append(True),
    )
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        caps.capped_popen(
            [sys.executable, "-c", "pass"], seat_key=f"unready-parent-{missing}",
        )
    assert refused.value.code == caps.CODE
    assert str(refused.value) == "the host does not provide delegated seat controllers"
    assert launches == [] and stopped


@pytest.mark.parametrize("missing", ["io.weight", "memory.swap.max"])
def test_helper_missing_cap_maps_to_the_readiness_refusal(
    monkeypatch, tmp_path, isolated, missing,
):
    _install_fake_cap_host(monkeypatch, tmp_path, isolated)
    ready = caps._realized_parent_ready

    def remove_after_check(unit, carved):
        result = ready(unit, carved)
        if result:
            (caps._seat_slice_chain(unit)[-1] / missing).unlink()
        return result

    monkeypatch.setattr(caps, "_realized_parent_ready", remove_after_check)
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        caps.capped_popen(
            [sys.executable, "-c", "raise AssertionError('target must not run')"],
            seat_key=f"cap-race-{missing}", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    assert refused.value.code == caps.CODE
    assert str(refused.value) == "the host does not provide delegated seat controllers"


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
    parent = caps._PARENTS[f"phase-loop-seat-{caps._unit_key('claude:review')}.slice"]
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
        first = caps.capped_popen(command, seat_key=caps.live_seat_key())
        assert first.wait(timeout=5) == 0
        deadline = time.monotonic() + 5
        while caps._CURRENT_SEAT_SCOPE.get().parent.refs != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert caps._CURRENT_SEAT_SCOPE.get().parent.refs == 1
        second = caps.capped_popen(command, seat_key=caps.live_seat_key())
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
    launches = tmp_path / "launches"
    _install_fake_cap_host(monkeypatch, tmp_path, isolated, log=launches)
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
    assert launches.read_text().splitlines() == [
        "phase-loop-seat-" + caps._unit_key("gemini:same") + "-1.scope"
    ]
    assert first.wait(timeout=5) == 0


def test_tmpfs_carveout_refuses_until_cleanup_is_wired(monkeypatch, tmp_path, isolated):
    _phase, staging, scratch = isolated
    monkeypatch.setattr(caps, "_dev_number", lambda _path: (0, 52))
    monkeypatch.setattr(caps, "_tmpfs_carveout", lambda path, _device: path in {staging, scratch})
    with pytest.raises(caps.CapsUnavailable, match="cleanup is not wired"):
        caps._device_plan(caps.DEFAULT_CAPS)


def test_io_paths_are_never_carved_out(monkeypatch, tmp_path, isolated):
    _phase, staging, scratch = isolated
    extra = tmp_path / "extra"
    extra.mkdir()
    monkeypatch.setattr(
        caps, "_dev_number", lambda path: (8, 0) if path in {staging, scratch} else (0, 52),
    )
    monkeypatch.setattr(caps, "_tmpfs_carveout", lambda *_args: True)
    with pytest.raises(caps.CapsUnavailable, match="anonymous filesystem"):
        caps._device_plan(replace(caps.DEFAULT_CAPS, io_paths=(str(extra),)))


def test_every_parent_disables_swap_and_attests_zero(tmp_path, isolated):
    assert "MemorySwapMax=0" in caps._parent_properties(caps.DEFAULT_CAPS, (), ())

    root = tmp_path / "cg"; parent = root / "p"; child = parent / "c"; child.mkdir(parents=True)
    proc = tmp_path / "pc"; proc.write_text("0::/p/c\n")
    expected = caps._expected(caps.DEFAULT_CAPS, (), ())
    assert expected["memory.swap.max"] == "0"
    _parent_files(parent, expected)
    enter.verify(expected, root=root, proc_cgroup=proc)
    (parent / "memory.swap.max").write_text("1")
    with pytest.raises(ValueError, match="memory.swap.max readback mismatch"):
        enter.verify(expected, root=root, proc_cgroup=proc)
    (parent / "memory.swap.max").unlink()
    with pytest.raises(enter.ControllerUnavailable, match="memory.swap.max readback unavailable"):
        enter.verify(expected, root=root, proc_cgroup=proc)


def test_tmpfs_refusal_is_typed_and_never_starts_the_target(monkeypatch, tmp_path, isolated):
    monkeypatch.setattr(caps, "_dev_number", lambda _path: (0, 52))
    monkeypatch.setattr(caps, "_tmpfs_carveout", lambda *_a: True)
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


def test_parent_collection_failure_is_logged(monkeypatch, tmp_path, isolated, caplog):
    parent = caps._Parent("fixture.slice", "digest", refs=1)
    caps._PARENTS[parent.unit] = parent

    def fail_stop(*_args, **_kwargs):
        caps._refuse("fixture stop failed")

    monkeypatch.setattr(caps, "_systemctl", fail_stop)
    with caplog.at_level("WARNING", logger=caps.__name__):
        caps._release_parent(parent)
    assert "parent collection failed for fixture.slice" in caplog.text


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
        seen.append(seat_key)
        process = subprocess.Popen(command, **kwargs)
        attach_pipe_proof(process)
        return process

    monkeypatch.setattr(caps, "capped_popen", capped)
    with caps._seat_scope("gemini:boundary"):
        process = panel_invoker.launch_provider(
            [sys.executable, "-c", "pass"], seat_caps=caps.live_seat_key(), cwd=tmp_path,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    assert process.wait(timeout=5) == 0
    assert seen == ["gemini:boundary"]


_PROCESS_START_PRIMITIVES = frozenset({
    "launch_owned", "launch_provider", "run_provider", "subprocess.Popen", "subprocess.run",
})
_PANEL_LAUNCH_CLASSIFICATION = {
    ("<module>", "launch_provider", "host-helper", 1):
        ("Exempt", "production identity binding; no process starts"),
    ("_ProviderQuiescenceLatch.__init__", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "process type inventory only"),
    ("_ProviderQuiescenceLatch.launch", "subprocess.Popen", "host-helper", 2):
        ("Exempt", "process registry and return type only"),
    ("_ProviderQuiescenceLatch.release", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "process registry type only"),
    ("_anchor_process_group", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "post-launch helper"),
    ("_await_tree", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "post-launch cleanup helper"),
    ("_complete_bwrap_witness", "subprocess.Popen", "host-helper", 2):
        ("Exempt", "post-launch witness pin; no process starts"),
    ("_require_launch_proof", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "post-launch witness check"),
    ("_terminate_proofed_tree", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "post-launch cleanup helper"),
    ("_tree_quiescent", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "post-launch cleanup predicate"),
    ("_claude_code_support_status", "run_provider", "owned", 1):
        ("Exempt", "short capability probe"),
    ("_claude_subscription_auth_ok", "run_provider", "owned", 1):
        ("Exempt", "short authentication probe"),
    ("_launch_claude_sdk_worker", "subprocess.Popen", "owned", 1):
        ("Capped", "SDK worker of the live seat attempt"),
    ("_leg_auth_ok", "run_provider", "owned", 1):
        ("Exempt", "short authentication probe"),
    ("_refresh_gemini_credential", "launch_provider", "host-helper", 1):
        ("Capped", "credential provider CLI is a seat attempt"),
    ("_require_seat_identity", "subprocess.run", "host-helper", 1):
        ("Exempt", "identity probe"),
    ("_run_claude_tui_session", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "process type inventory only"),
    ("_run_claude_tui_session._popen", "launch_owned", "owned", 1):
        ("Capped", "owned TUI seat launch"),
    ("_run_claude_tui_session._popen", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "nested launch return type only"),
    ("_run_leg_with_liveness._popen", "launch_owned", "owned", 1):
        ("Capped", "owned CLI seat launch"),
    ("_run_leg_with_liveness._popen", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "nested launch return type only"),
    ("_terminate_process_group", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "post-launch termination helper"),
    ("_terminate_process_group_windows", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "post-launch termination helper"),
    ("_wait_for_process_group_exit", "subprocess.Popen", "host-helper", 1):
        ("Exempt", "post-launch wait helper"),
    ("launch_owned", "launch_provider", "owned", 1):
        ("Capped", "key-preserving seat launch boundary"),
    ("launch_provider", "subprocess.Popen", "owned", 1):
        ("Exempt", "raw branch is selected only for a classified unkeyed non-seat"),
    ("run_provider", "launch_owned", "owned", 2):
        ("Exempt", "administrative or executor launch; not a seat attempt"),
    ("run_provider", "launch_provider", "host-helper", 1):
        ("Exempt", "qualification observer helper"),
    ("_require_jailed_seat_identity", "subprocess.run", "host-helper", 1):
        ("Exempt", "identity probe"),
    ("_run_claude_tui_session._popen", "launch_provider", "owned", 1):
        ("Capped", "jailed TUI seat launch"),
    ("_run_leg_with_liveness._popen", "launch_provider", "owned", 1):
        ("Capped", "jailed CLI seat launch"),
    ("_parent_auth_state", "run_provider", "owned", 1):
        ("Exempt", "short authentication probe"),
    ("probe_grok_tools", "run_provider", "owned", 1):
        ("Exempt", "short tool capability probe"),
}
_NON_PANEL_LAUNCH_CLASSIFICATION = {
    "agy_qualification._run_help": ("Exempt", "help measurement; not a seat attempt"),
    "legible_evidence._invoke_reviewtruth_fable_adapter":
        ("Exempt", "legible-evidence probe; not a seat attempt"),
    "skill_eval_runner.verify_executable":
        ("Exempt", "pinned executable version check; not a seat attempt"),
    "panel_invoker._spawn_2tuple": ("Capped", "invoke_panel leg is a seat attempt"),
    "panel_invoker.window_control_launch":
        ("Capped", "window control launch is a jailed seat attempt"),
    "panel_invoker._WindowBoardLegRuntime.start":
        ("Capped", "window board sentinel inherits the board seat scope"),
    "president_adapter.PresidentInvoke._launch_gemini:heartbeat":
        ("Capped", "president rung is a seat attempt"),
    "president_adapter.PresidentInvoke._launch_gemini:bounded":
        ("Capped", "president rung is a seat attempt"),
    "president_adapter.PresidentInvoke._launch_claude:print":
        ("Capped", "president rung is a seat attempt"),
    "president_adapter.PresidentInvoke._launch_claude:tui":
        ("Capped", "president rung is a seat attempt"),
}


def test_every_panel_launch_reference_is_classified_capped_or_exempt():
    inventory = json.loads(
        (Path(__file__).parent / "data" / "seat_launch_references.json").read_text()
    )
    rows = {
        (row["function"], row["primitive"], row["role"], row["count"])
        for row in inventory
        if row["module"] == "panel_invoker" and row["primitive"] in _PROCESS_START_PRIMITIVES
    }
    assert rows == set(_PANEL_LAUNCH_CLASSIFICATION)
    for classification, reason in (
        *_PANEL_LAUNCH_CLASSIFICATION.values(), *_NON_PANEL_LAUNCH_CLASSIFICATION.values(),
    ):
        assert classification in {"Capped", "Exempt"} and reason


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
        seen.append(seat_key)
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
                    object(), worker_id=2, prepared=prepared, seat_key=caps.live_seat_key(),
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

    def run(argv, seat_key, *, timeout=45, cleanup=(), observe_oom=False):
        started = time.monotonic()
        oom_kills = 0
        with caps._seat_scope(seat_key, caps._LaunchClass.TEST):
            process = caps.capped_popen(
                argv, seat_key=seat_key, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, stderr = process.communicate(timeout=timeout)
            if observe_oom:
                parent = caps._CURRENT_SEAT_SCOPE.get().parent
                events = dict(
                    line.split() for line in
                    (caps._seat_slice_chain(parent.unit)[-1] / "memory.events")
                    .read_text(encoding="ascii").splitlines()
                )
                oom_kills = int(events["oom_kill"])
            for path in cleanup:
                path.unlink(missing_ok=True)
        elapsed = time.monotonic() - started
        _wait_for_parent_collection()
        return process.returncode, stdout, stderr, elapsed, oom_kills

    staging = caps._automatic_paths()[0]
    stem = f"seat-caps-probe-{os.getpid()}-{time.time_ns()}"
    direct = staging / f"{stem}-direct"
    buffered = staging / f"{stem}-buffered"
    completed = staging / f"{stem}-completed"
    dd = shutil.which("dd")
    if dd is None:
        pytest.fail("the designated seat host has no dd for the direct-I/O cap probe")
    try:
        rc, _stdout, stderr, elapsed, _oom_kills = run(
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
        rc, _stdout, stderr, elapsed, _oom_kills = run(
            [sys.executable, "-c", buffered_script, str(buffered)],
            "host-probe-buffered",
        )
        assert rc == 0, stderr
        assert elapsed >= 1.0

        memory_script = (
            "import pathlib,sys,time; x=bytearray(96<<20); "
            "pathlib.Path(sys.argv[1]).touch(); time.sleep(.1)"
        )
        rc, _stdout, stderr, _elapsed, oom_kills = run(
            [sys.executable, "-c", memory_script, str(completed)],
            "host-probe-memory", observe_oom=True,
        )
        assert rc in {-signal.SIGKILL, 128 + signal.SIGKILL}, stderr
        assert oom_kills >= 1
        assert not completed.exists()

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
        rc, stdout, stderr, _elapsed, _oom_kills = run(
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
            rc, stdout, _stderr, _elapsed, _oom_kills = run(
                [sys.executable, "-c", tmpfs_script, str(tmpfs_output), str(completed)],
                "host-probe-tmpfs", cleanup=(tmpfs_output,),
            )
            assert stdout.startswith(b"swap=0\n")
            assert rc != 0 and not completed.exists()
    finally:
        for path in (direct, buffered, completed):
            path.unlink(missing_ok=True)


def test_capped_popen_takes_the_key_explicitly_and_never_from_context(monkeypatch, tmp_path,
                                                                    isolated):
    _install_fake_cap_host(monkeypatch, tmp_path, isolated)
    marker = tmp_path / "ran"
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
    with caps._seat_scope("claude:explicit"):
        for key in ("", "claude:other"):
            with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
                caps.capped_popen(command, seat_key=key)
            assert refused.value.code == caps.CODE
    assert not marker.exists()


def test_runner_reaches_the_bus_and_the_target_env_is_exact(monkeypatch, tmp_path, isolated):
    runner_env = tmp_path / "runner-env.json"
    root, proc_cgroup, _configured, _stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated)
    runner = tmp_path / "systemd-run"
    body = runner.read_text().replace(
        "import os, pathlib, sys\n",
        "import os, pathlib, sys, json\n"
        f"pathlib.Path({str(runner_env)!r}).write_text(json.dumps(dict(os.environ)))\n", 1)
    runner.write_text(body)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    seat_env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/dev/null"}
    target = tmp_path / "target-env.json"
    process = caps.capped_popen(
        [sys.executable, "-I", "-c",
         "import json,os,sys; open(sys.argv[1],'w').write(json.dumps(dict(os.environ)))",
         str(target)],
        seat_key="gemini:env", env=seat_env,
    )
    assert process.wait(timeout=10) == 0
    seen_by_runner = json.loads(runner_env.read_text())
    assert seen_by_runner["XDG_RUNTIME_DIR"] == str(tmp_path / "run")
    assert seen_by_runner["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={tmp_path / 'run' / 'bus'}"
    observed = json.loads(target.read_text())
    observed.pop("LC_CTYPE", None)  # the interpreter may coerce the C locale
    assert observed == seat_env


def test_the_seat_scope_has_a_fixed_description(monkeypatch, tmp_path, isolated):
    """The scope's unit metadata is fixed: systemd-run gets a description naming only the
    seat key's digest, and no option before the target carries an argv or env value."""
    runner_argv = tmp_path / "runner-argv.jsonl"
    _root, _proc_cgroup, _configured, _stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated)
    runner = tmp_path / "systemd-run"
    body = runner.read_text().replace(
        "import os, pathlib, sys\n",
        "import os, pathlib, sys, json\n"
        f"pathlib.Path({str(runner_argv)!r}).open('a').write(json.dumps(sys.argv) + '\\n')\n", 1)
    runner.write_text(body)
    properties: list[str] = []
    recorded = caps._systemctl

    def systemctl(*args, **kwargs):
        properties.extend(args)
        return recorded(*args, **kwargs)

    monkeypatch.setattr(caps, "_systemctl", systemctl)
    value = "fixture-argv-value-0123456789"
    key = "gemini:gemini-4-argon:medium:alternative-approach"
    commands = (
        [sys.executable, "-I", "-c", "pass", "--setenv", "SEAT_FIXTURE", value],
        [sys.executable, "-I", "-c", "pass", "--other-shape"],
    )
    for command in commands:
        process = caps.capped_popen(command, seat_key=key,
                                    env={"PATH": "/usr/bin:/bin", "SEAT_FIXTURE": value})
        assert process.wait(timeout=10) == 0
    launches = [json.loads(line) for line in runner_argv.read_text().splitlines()]
    assert len(launches) == len(commands)
    descriptions = set()
    for argv, command in zip(launches, commands):
        options = argv[1:argv.index("--")]
        described = [item for item in options if item.startswith("--description=")]
        assert described == [f"--description=phase-loop seat {caps._unit_key(key)}"]
        descriptions.update(described)
        metadata = " ".join([*options, *properties])
        for absent in (value, "SEAT_FIXTURE", key, "--setenv", "--other-shape", sys.executable):
            assert absent not in metadata, absent
        assert argv[argv.index("--") + 1:][-len(command):] == command  # the target is unchanged
    assert len(descriptions) == 1  # the same for every command of the seat


def _stub_owned_launch_view(monkeypatch, seen):
    from phase_loop_runtime import seat_seccomp
    monkeypatch.setattr(panel_invoker, "_filtered_holder_namespace", lambda: 0)
    monkeypatch.setattr(panel_invoker, "_seat_bind_source", lambda path: str(path))
    monkeypatch.setattr(panel_invoker, "_seat_filesystem_view", lambda *a, **k: ())
    monkeypatch.setattr(panel_invoker, "_seat_owner", lambda *a, **k: ())
    monkeypatch.setattr(panel_invoker, "_seat_fd_closer", lambda *a, **k: [])
    monkeypatch.setattr(seat_seccomp, "sealed_keyring_filter",
                        lambda: os.open(os.devnull, os.O_RDONLY))

    def launch_provider(_command, *, seat_caps=None, **_kwargs):
        seen.append(seat_caps)
        return "launched"

    monkeypatch.setattr(panel_invoker, "launch_provider", launch_provider)


def test_launch_owned_caps_exactly_what_a_capped_site_keys(monkeypatch, tmp_path):
    seen = []
    _stub_owned_launch_view(monkeypatch, seen)
    profile = panel_invoker.SeatProfile(env={"HOME": str(tmp_path)})
    for seat_caps in (None, "codex:review"):
        panel_invoker.launch_owned(
            [sys.executable, "-c", "pass"], role=panel_invoker.SeatLaunchRole.PROVIDER_REVIEW,
            profile=profile, cwd=str(tmp_path), seat_caps=seat_caps,
        )
    # None: an Exempt caller (launcher.*, skill_eval_runner.*) stays on its own seam.
    assert seen == [None, "codex:review"]


class _StopAtBoundary(Exception):
    pass


@pytest.mark.parametrize("jailed", [False, True])
@pytest.mark.parametrize("exempt", [False, True])
def test_leg_runner_popen_hands_the_classified_key_to_the_boundary(
    monkeypatch, tmp_path, jailed, exempt,
):
    import contextlib
    seen = []

    def boundary(_command, *, seat_caps=None, **_kwargs):
        seen.append(seat_caps)
        raise _StopAtBoundary()

    monkeypatch.setattr(panel_invoker, "launch_provider", boundary)
    monkeypatch.setattr(panel_invoker, "launch_owned", boundary)
    monkeypatch.setattr(panel_invoker, "_await_gemini_login", lambda *a, **k: 0.0)

    @contextlib.contextmanager
    def profile(cmd, **_kwargs):
        yield list(cmd), SimpleNamespace(evidence={})

    monkeypatch.setattr(panel_invoker, "_seat_command_profile", profile)
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(("prefix",))
    try:
        with caps._seat_scope("codex:leg"):
            manager = panel_invoker._uncapped_nonseat_probe() if exempt else contextlib.nullcontext()
            with manager:
                with pytest.raises(_StopAtBoundary):
                    panel_invoker._run_leg_with_liveness(
                        [sys.executable, "-c", "pass"], cwd=tmp_path, env={}, deadline_s=5,
                        seat_jail=object() if jailed else None,
                        probe_jail=object() if jailed else None,
                    )
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    assert seen == [None if exempt else "codex:leg"]


@pytest.mark.parametrize("jailed", [False, True])
def test_tui_popen_hands_the_live_seat_key_to_the_boundary(monkeypatch, tmp_path, jailed):
    import contextlib
    seen = []

    def boundary(_command, *, seat_caps=None, **_kwargs):
        seen.append(seat_caps)
        raise _StopAtBoundary()

    @contextlib.contextmanager
    def profile(command, **_kwargs):
        yield list(command), panel_invoker.SeatProfile(env={"HOME": str(tmp_path)})

    monkeypatch.setattr(panel_invoker, "launch_provider", boundary)
    monkeypatch.setattr(panel_invoker, "launch_owned", boundary)
    monkeypatch.setattr(panel_invoker, "_seat_command_profile", profile)
    with caps._seat_scope("claude:tui"):
        result = panel_invoker._run_claude_tui_session(
            command=[sys.executable, "-c", "pass"], cwd=tmp_path, prompt="review",
            output_file=tmp_path / "out", timeout_s=1, env={"PATH": "/usr/bin:/bin"},
            backstop_s=1, seat_jail=object() if jailed else None,
            probe_jail=object() if jailed else None,
        )
    assert seen == ["claude:tui"]
    assert result[2] == "claude_tui_launch_error:_StopAtBoundary"


def test_sdk_leg_hands_the_live_key_to_the_real_worker_boundary(monkeypatch, tmp_path):
    import contextlib
    from phase_loop_runtime import claude_seat_sdk as sdk
    from phase_loop_runtime import claude_seat_transport as transport

    seen = []

    def stop_at_caps(_command, *, seat_key, **_kwargs):
        seen.append(seat_key)
        raise OSError("stop at capped worker boundary")

    @contextlib.contextmanager
    def lease(_count):
        yield 2

    monkeypatch.setattr(caps, "capped_popen", stop_at_caps)
    monkeypatch.setattr(panel_invoker, "_claude_sdk_worker_count", lambda: 4)
    monkeypatch.setattr(panel_invoker._seat_uid, "lease_seat_id", lease)
    monkeypatch.setattr(panel_invoker.os, "access", lambda *_a, **_k: True)
    monkeypatch.setattr(
        panel_invoker, "_claude_sdk_worker_argv",
        lambda *_a, **_k: [sys.executable, "-c", "raise SystemExit(99)"],
    )
    prepared = SimpleNamespace(
        payload_bytes={name: b"fixture" for name in sdk.WORKER_PAYLOAD},
        install=SimpleNamespace(),
    )
    seat = SimpleNamespace(jail=SimpleNamespace(seat_ids=None), probe_jail=None)
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(("nsenter", "setpriv"))
    try:
        with caps._seat_scope("claude:sdk-leg"):
            with pytest.raises(transport.TransportRefused):
                panel_invoker._run_claude_sdk_leg(
                    [], spec=object(), bridge=object(), prepared=prepared, options={},
                    cwd=tmp_path, env={}, deadline_s=1, seat=seat,
                )
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    assert seen == ["claude:sdk-leg"]


def test_invoke_panel_legs_get_distinct_live_keys(monkeypatch):
    seen = []

    def spawn(leg, _artifact, **_kwargs):
        seen.append(caps.live_seat_key())
        return "OK", "review\nAGREE"

    monkeypatch.setattr(panel_invoker, "_default_spawn", spawn)
    first = panel_invoker.invoke_panel("artifact", ("codex",), max_concurrency=1)
    second = panel_invoker.invoke_panel("artifact", ("codex",), max_concurrency=1)
    assert first.legs[0].usable and second.legs[0].usable
    assert len(seen) == 2 and len(set(seen)) == 2
    assert all(key.startswith("panel:codex:") for key in seen)


def test_provider_seam_reuses_an_owning_board_seat_key(monkeypatch):
    seen = []

    def spawn(leg, _artifact, **_kwargs):
        seen.append((leg, caps.live_seat_key()))
        return "OK", "review\nAGREE"

    monkeypatch.setattr(panel_invoker, "_default_spawn", spawn)
    with caps._seat_scope("codex:board-seat"):
        result = panel_invoker._default_spawn_via_provider("codex", "artifact")

    assert result == ("OK", "review\nAGREE")
    assert seen == [("codex", "codex:board-seat")]


def test_only_ruled_nonseat_callers_select_the_uncapped_probe_context():
    target = "_uncapped_nonseat_probe"
    counts = Counter()
    source_root = Path(panel_invoker.__file__).parent

    class ProbeUseVisitor(ast.NodeVisitor):
        def __init__(self, module):
            self.module = module
            self.functions = []

        def visit_FunctionDef(self, node):
            self.functions.append(node.name)
            if node.name == target:
                counts[(self.module, node.name)] += 1
            self.generic_visit(node)
            self.functions.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            name = (
                node.func.id if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute)
                else None
            )
            if name == target:
                counts[(self.module, self.functions[-1] if self.functions else "<module>")] += 1
            self.generic_visit(node)

    for path in source_root.rglob("*.py"):
        ProbeUseVisitor(path.stem).visit(ast.parse(path.read_text(encoding="utf-8")))

    assert counts == Counter({
        ("agy_qualification", "_run_help"): 1,
        ("legible_evidence", "_invoke_reviewtruth_fable_adapter"): 2,
        ("skill_eval_runner", "verify_executable"): 1,
        ("panel_invoker", "_uncapped_nonseat_probe"): 1,
        ("seat_resource_caps", "_uncapped_nonseat_probe"): 1,
    })


def test_each_gemini_president_route_has_its_own_live_seat_key(monkeypatch, tmp_path):
    import contextlib
    from phase_loop_runtime import executable_dependency_startup, gemini_heartbeat
    from phase_loop_runtime import president_adapter
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    seen = []

    def run_leg(*_args, **_kwargs):
        assert caps._CURRENT_SEAT_SCOPE.get().launch_class is caps._LaunchClass.BOARD
        seen.append(caps.live_seat_key())
        return panel_invoker._LegRun(1, "", "")

    @contextlib.contextmanager
    def agy_environment(_env):
        yield {}

    @contextlib.contextmanager
    def owned_profile(*_args, **_kwargs):
        yield SimpleNamespace(executable="agy", env={})

    monkeypatch.setattr(
        president_adapter, "_president_gemini_stream_protocol",
        lambda _prompt: SimpleNamespace(transport="prompt"),
    )
    monkeypatch.setattr(panel_invoker, "_brokered_gemini_command", lambda **_kwargs: ["agy"])
    monkeypatch.setattr(panel_invoker, "_broker_subscription_env", lambda _env: {})
    monkeypatch.setattr(panel_invoker, "_broker_leg_env", lambda *_args: {})
    monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", run_leg)
    monkeypatch.setattr(president_adapter, "_president_agy_environment", agy_environment)
    monkeypatch.setattr(gemini_heartbeat, "require_capability", lambda _env: None)
    monkeypatch.setattr(gemini_heartbeat, "owned_profile", owned_profile)
    monkeypatch.setattr(
        executable_dependency_startup, "refuse_unwired_dependency_route", lambda _route: None,
    )
    seam = president_adapter.PresidentInvoke(DEFAULT_BOARD, base_env={})
    seam._launch_gemini("model", "prompt", tmp_path)
    seam._launch_gemini("model", "prompt", tmp_path, monitor=object())
    assert len(seen) == 2 and len(set(seen)) == 2
    assert all(key.startswith(f"president:gemini:{seam.invocation}:") for key in seen)


def test_each_claude_president_route_has_its_own_live_seat_key(monkeypatch, tmp_path):
    from phase_loop_runtime import president_adapter
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    seen = []

    def print_session(*_args, **_kwargs):
        assert caps._CURRENT_SEAT_SCOPE.get().launch_class is caps._LaunchClass.BOARD
        seen.append(caps.live_seat_key())
        return 1, "", "", ""

    def tui_session(**_kwargs):
        assert caps._CURRENT_SEAT_SCOPE.get().launch_class is caps._LaunchClass.BOARD
        seen.append(caps.live_seat_key())
        return 1, "", "", ""

    monkeypatch.setattr(panel_invoker, "_claude_code_support_status", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(panel_invoker, "_claude_subscription_auth_ok", lambda _env: (True, ""))
    monkeypatch.setattr(panel_invoker, "_claude_print_seat_command", lambda *_args, **_kwargs: ["claude"])
    monkeypatch.setattr(panel_invoker, "_broker_claude_tui_command", lambda **_kwargs: ["claude"])
    monkeypatch.setattr(panel_invoker, "_broker_leg_env", lambda *_args: {})
    monkeypatch.setattr(panel_invoker, "_leg_timeout_for", lambda _path: 1)
    monkeypatch.setattr(panel_invoker, "_broker_claude_stall_threshold", lambda *_args: 1.0)
    monkeypatch.setattr(panel_invoker, "_run_claude_print_session", print_session)
    monkeypatch.setattr(panel_invoker, "_run_claude_tui_session", tui_session)
    monkeypatch.setattr(panel_invoker, "_cleanup_broker_claude_transcript", lambda *_args: None)
    seam = president_adapter.PresidentInvoke(DEFAULT_BOARD, base_env={})
    for route in (panel_invoker._PANEL_CLAUDE_ROUTE_PRINT, panel_invoker._PANEL_CLAUDE_ROUTE_TUI):
        monkeypatch.setattr(panel_invoker, "_resolve_claude_transport", lambda route=route: (route, None))
        seam._launch_claude("model", "prompt", tmp_path)
    assert len(seen) == 2 and len(set(seen)) == 2
    assert all(key.startswith(f"president:claude:{seam.invocation}:") for key in seen)


def _bare_jail():
    jail = object.__new__(seat_jail.SeatJail)
    object.__setattr__(jail, "dependency", None)
    object.__setattr__(jail, "pass_fds", ())
    return jail


def test_jailed_launch_without_a_seat_key_refuses_and_never_starts(monkeypatch, tmp_path):
    monkeypatch.setattr(panel_invoker, "_compose_launch_prefix", lambda *a, **k: [])
    monkeypatch.setattr(panel_invoker, "_compose_seat_jail_prefix", lambda *a, **k: [])
    monkeypatch.setattr(panel_invoker, "_require_qualified_jail", lambda *_a: None)
    monkeypatch.setattr(panel_invoker, "_require_jailed_seat_identity", lambda *a, **k: None)
    monkeypatch.setattr(caps, "readiness_code", lambda: None)
    marker = tmp_path / "jailed-ran"
    jail = _bare_jail()
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        panel_invoker.launch_provider(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
            process_owner=jail, probe_owner=jail, stdout=subprocess.DEVNULL,
        )
    assert refused.value.code == caps.CODE
    time.sleep(0.2)
    assert not marker.exists()


@pytest.mark.parametrize("runtime", [None, "/run/custom-seat-user"])
@pytest.mark.parametrize("returncode", [0, 1])
def test_systemctl_connects_from_clean_environment(monkeypatch, runtime, returncode):
    environment = {"HOME": "/isolated/home", "PATH": "/usr/bin:/bin"}
    if runtime is not None:
        environment.update(XDG_RUNTIME_DIR=runtime,
                           DBUS_SESSION_BUS_ADDRESS="unix:path=/wrong/bus")
    monkeypatch.setattr(caps.os, "environ", environment)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(caps.subprocess, "run", run)
    before = dict(environment)
    if returncode:
        with pytest.raises(caps.CapsUnavailable):
            caps._systemctl("start", "phase-loop-seat-test.slice")
    else:
        caps._systemctl("start", "phase-loop-seat-test.slice")
    assert environment == before  # management settings never mutate caller env
    command, kwargs = calls[0]
    expected = runtime or f"/run/user/{os.getuid()}"
    assert command == [str(caps._SYSTEMCTL), "--user", "start", "phase-loop-seat-test.slice"]
    assert kwargs["env"] == {**before, "XDG_RUNTIME_DIR": expected,
                             "DBUS_SESSION_BUS_ADDRESS": f"unix:path={expected}/bus"}
    assert kwargs["timeout"] == 15.0


def _memory_readings(parent, *, current=0, peak=0, high=4, maximum=10, local=5,
                     oom=1, oom_kill=2, some=200, full=100):
    (parent / "memory.current").write_text(f"{current}\n")
    (parent / "memory.peak").write_text(f"{peak}\n")
    (parent / "memory.events").write_text(
        f"low 0\nhigh {high}\nmax {maximum}\noom {oom}\noom_kill {oom_kill}\n")
    (parent / "memory.events.local").write_text(f"max {local}\n")
    (parent / "memory.pressure").write_text(
        f"some avg10=0.02 avg60=0.00 avg300=0.00 total={some}\n"
        f"full avg10=0.01 avg60=0.00 avg300=0.00 total={full}\n")


@pytest.fixture
def memory_host(monkeypatch, tmp_path, isolated):
    root, _proc, configured, stopped = _install_fake_cap_host(monkeypatch, tmp_path, isolated)
    systemctl = caps._systemctl

    def prepare(*args, **kwargs):
        result = systemctl(*args, **kwargs)
        if args[0] == "set-property":
            parent = caps._seat_slice_chain(args[2])[-1]
            cap_file = parent / "memory.max"
            cap_file.write_text(cap_file.read_text() + "\n")
            (parent / "cgroup.events").write_text("populated 0\nfrozen 0\n")
            _memory_readings(parent)
        return result

    monkeypatch.setattr(caps, "_systemctl", prepare)

    def launch(leg, script="pass", **kwargs):
        kwargs.pop("cwd", None)
        return caps.capped_popen([sys.executable, "-c", script], seat_key=leg, **kwargs)

    def scope(process):
        return root / caps._proc_cgroup_of(process.pid).lstrip("/")

    def drain(process):
        (scope(process) / "cgroup.events").write_text("populated 0\nfrozen 0\n")

    return SimpleNamespace(root=root, launch=launch, scope=scope, drain=drain,
                           configured=configured, stopped=stopped)


@pytest.mark.parametrize(("expected_state", "proof_state"), [
    ("final", "empty"), ("final", "removed"), ("partial", "populated"), ("partial", "missing"),
])
def test_seat_memory_terminal_read_requires_every_witness(
    memory_host, monkeypatch, caplog, expected_state, proof_state,
):
    import errno
    from phase_loop_runtime import provider_tree_proof as proof

    with caps._seat_memory_attempt() as attempt:
        first = memory_host.launch("fixture", "import time; time.sleep(.15)")
        second = memory_host.launch("fixture")
        parent = memory_host.scope(first).parent
        assert memory_host.scope(second).parent == parent
        first.wait(timeout=5)
        second.wait(timeout=5)
        memory_host.drain(first)
        if proof_state == "empty":
            memory_host.drain(second)
        elif proof_state == "removed":
            def removed(_fd):
                raise OSError(errno.ENODEV, "removed")
            # Use the real TreeProof transition for the removal witness.
            second_proof = proof.proof_of(second)
            pread = os.pread

            def pread_scope(fd, amount, offset):
                if os.path.samestat(os.fstat(fd), (memory_host.scope(second) / "cgroup.events").stat()):
                    return removed(fd)
                return pread(fd, amount, offset)
            monkeypatch.setattr(os, "pread", pread_scope)
        elif proof_state == "missing":
            monkeypatch.delattr(second, "_phase_loop_proof")
        _memory_readings(parent, current=120, peak=888, high=6, maximum=20, local=9,
                         some=3_000_000, full=1_000_101)
        snapshot, notice = attempt.finish()
        assert memory_host.stopped == []
        assert snapshot == {
            "max_bytes": 4294967296, "peak_bytes": 888, "peak_source": "kernel",
            "max": 10, "high": 2, "local_max": 4, "oom": 0, "oom_kill": 0,
            "some_stall_us": 2_999_800, "full_stall_us": 1_000_001, "state": expected_state,
        }
        if proof_state == "removed":
            assert second_proof.reason == "enodev"
        assert notice and caplog.text.count("seat_memory_max_reached") == 1


def test_seat_memory_seal_does_not_close_the_parent_to_later_attempts(memory_host):
    with caps._seat_scope("fixture"):
        with caps._seat_memory_attempt() as attempt:
            first = memory_host.launch("fixture")
            first.wait(timeout=5)
            memory_host.drain(first)
            _memory_readings(memory_host.scope(first).parent, current=10, peak=300)
            assert attempt.finish()[0]["peak_source"] == "kernel"
            child = memory_host.launch("fixture")
            assert child.wait(timeout=5) == 0
            memory_host.drain(child)
        # Cleanup launches and later recorded attempts can reuse the retained slice.
        cleanup = memory_host.launch("fixture")
        cleanup.wait(timeout=5)
        memory_host.drain(cleanup)
        with caps._seat_memory_attempt() as later:
            child = memory_host.launch("fixture")
            child.wait(timeout=5)
            memory_host.drain(child)
            _memory_readings(memory_host.scope(child).parent, current=20, peak=305)
            snapshot, notice = later.finish()
        assert snapshot["peak_source"] == "sampled"
        assert snapshot["peak_bytes"] == 20
        assert snapshot["state"] == "partial"
        assert not notice
        assert len(memory_host.configured) == 1


def test_seat_memory_can_finish_between_scope_reservation_and_attestation(memory_host):
    with caps._seat_scope("fixture"), caps._seat_memory_attempt() as attempt:
        first = memory_host.launch("fixture")
        assert first.wait(timeout=5) == 0
        memory_host.drain(first)
        snapshots = []
        second = memory_host.launch("fixture", before_spawn=lambda: snapshots.append(attempt.finish()[0]))
        assert second.wait(timeout=5) == 0
        memory_host.drain(second)
        assert [snapshot["state"] for snapshot in snapshots] == ["partial"]


def test_reused_seat_slice_replaces_stale_scratch_device_limits(memory_host, monkeypatch):
    # systemd retains set-property drop-ins even when the qualification slice stops.
    # Model its per-device property merge and verify the result with the real cap helper.
    systemctl = caps._systemctl
    io_limits = {}

    def persistent_systemctl(*args, **kwargs):
        result = systemctl(*args, **kwargs)
        if args[:2] == ("set-property", "--runtime"):
            parent = caps._seat_slice_chain(args[2])[-1]
            expected = _expected_from_properties(args[3:], io_limits=io_limits)
            _parent_files(parent, expected)
        return result

    monkeypatch.setattr(caps, "_systemctl", persistent_systemctl)
    key = "gemini:qualification"
    for device in ("7:0", "8:0"):
        monkeypatch.setattr(caps, "_device_plan", lambda caps: ((device,), ()))
        with caps._seat_memory_attempt():
            child = memory_host.launch(key, stderr=subprocess.PIPE)
            _, stderr = child.communicate(timeout=5)
            assert child.returncode == 0, stderr
        _wait_for_parent_collection()
    assert sum(len(limits) for limits in io_limits.values()) == 4


@pytest.mark.parametrize(("local_delta", "full_delta", "oom_delta", "kill_delta", "notice"), [
    (1, 0, 0, 0, False),
    (1, 1_000_000, 0, 0, False),
    (1, 1_000_001, 0, 0, True),
    (0, 2_000_000, 0, 0, False),
    (0, 0, 1, 0, True),
    (0, 0, 0, 1, True),
])
def test_seat_memory_notice_threshold_and_terminal_read(
    memory_host, caplog, local_delta, full_delta, oom_delta, kill_delta, notice,
):
    with caps._seat_memory_attempt() as attempt:
        child = memory_host.launch("fixture")
        child.wait(timeout=5)
        memory_host.drain(child)
        _memory_readings(memory_host.scope(child).parent, current=299, peak=300, maximum=20,
                         local=5 + local_delta, full=100 + full_delta, oom=1 + oom_delta,
                         oom_kill=2 + kill_delta)
        result, emitted = attempt.finish()
    assert result["max"] == 10
    assert result["local_max"] == local_delta
    assert emitted is notice
    assert caplog.text.count("seat_memory_max_reached") == int(notice)


def test_seat_memory_live_sample_fallback_preserves_last_good(memory_host, caplog, monkeypatch):
    monkeypatch.setattr(caps, "_MEMORY_SAMPLE_S", 0.01)
    with caps._seat_memory_attempt() as attempt:
        child = memory_host.launch("fixture")
        parent = memory_host.scope(child).parent
        _memory_readings(parent, current=512, peak=0, maximum=17, local=8, full=1_000_101)
        (parent / "memory.peak").unlink()
        deadline = time.monotonic() + 3
        while "seat_memory_max_reached" not in caplog.text and time.monotonic() < deadline:
            time.sleep(0.01)
        assert caplog.text.count("seat_memory_max_reached") == 1
        child.wait(timeout=5)
        memory_host.drain(child)
        _memory_readings(parent, current=64, peak=0, maximum=15, local=7, full=1_000_001)
        (parent / "memory.events.local").write_text("max 8\nmax 9\n")
        (parent / "memory.peak").write_text("18446744073709551616\n")
        (parent / "memory.pressure").write_text("some PRIVATE_FIXTURE_SENTINEL\n")
        snapshot, notice = attempt.finish()
    assert snapshot["state"] == "partial" and notice
    assert (snapshot["peak_source"], snapshot["peak_bytes"]) == ("sampled", 512)
    assert snapshot["max"] == 7
    assert snapshot["local_max"] == 3
    assert snapshot["full_stall_us"] == 1_000_001
    assert caplog.text.count("seat_memory_max_reached") == 1
    assert "PRIVATE_FIXTURE_SENTINEL" not in json.dumps(snapshot) + caplog.text


@pytest.mark.parametrize("damage", ["foreign_scope", "preexisting", "symlink", "unreadable"])
def test_seat_memory_unattributed_or_unavailable_does_not_break_launch(
    memory_host, caplog, monkeypatch, damage, tmp_path,
):
    configure = caps._systemctl

    def setup(*args, **kwargs):
        configure(*args, **kwargs)
        if args[0] == "start" and damage == "unreadable":
            parent = caps._seat_slice_chain(args[1])[-1]
            for name in ("memory.events", "memory.events.local", "memory.pressure",
                         "memory.peak", "memory.current"):
                (parent / name).unlink()

    monkeypatch.setattr(caps, "_systemctl", setup)
    if damage == "preexisting":
        unit = f"phase-loop-seat-{caps._unit_key('fixture')}.slice"
        caps._seat_slice_chain(unit)[-1].mkdir(parents=True)
    if damage == "symlink":
        real_root = memory_host.root.rename(tmp_path / "cgroup-moved")
        memory_host.root.symlink_to(real_root, target_is_directory=True)
    with caps._seat_memory_attempt() as attempt:
        child = memory_host.launch("fixture")
        assert child.wait(timeout=5) == 0
        memory_host.drain(child)
        parent = memory_host.scope(child).parent
        if damage != "unreadable":
            _memory_readings(parent, current=321, peak=654, oom=8)
        if damage == "foreign_scope":
            (parent / "foreign.scope").mkdir()
        if damage == "unreadable":
            # A symlink in place of an optional metric never lends its target to the observer.
            unrelated = parent / "memory.max"
            (parent / "memory.current").symlink_to(unrelated)
        snapshot, notice = attempt.finish()
    assert not notice and "seat_memory_max_reached" not in caplog.text
    if damage in {"foreign_scope", "preexisting"}:
        assert snapshot["state"] == "partial"
        assert (snapshot["peak_source"], snapshot["peak_bytes"]) == ("sampled", 321)
    else:
        assert snapshot["state"] == "unavailable"
        assert snapshot["peak_bytes"] is None


def test_seat_memory_finish_uses_the_finalizing_thread(memory_host, monkeypatch):
    from threading import current_thread

    reads = []
    real_sample = caps._SeatMemoryObserver.sample

    def sample(observer, children, *, drained=False):
        if drained:
            reads.append(current_thread())
            time.sleep(0.06)
        return real_sample(observer, children, drained=drained)

    monkeypatch.setattr(caps._SeatMemoryObserver, "sample", sample)
    with caps._seat_memory_attempt() as attempt:
        child = memory_host.launch("fixture")
        assert child.wait(timeout=5) == 0
        memory_host.drain(child)
        snapshot, _notice = attempt.finish()
    assert reads == [current_thread()]
    assert snapshot["state"] == "final"


def test_seat_memory_finish_retains_last_sample_when_sampler_is_blocked(
    memory_host, monkeypatch, caplog,
):
    from threading import Event

    blocked = Event()
    release = Event()
    real_sample = caps._SeatMemoryObserver.sample
    monkeypatch.setattr(caps, "_MEMORY_SAMPLE_S", 0.01)
    monkeypatch.setattr(caps, "_MEMORY_SAMPLER_JOIN_S", 0.05)
    reads = 0

    def controlled_sample(observer, children, *, drained=False):
        nonlocal reads
        reads += 1
        if reads == 2:
            blocked.set()
            release.wait(timeout=5)
        return real_sample(observer, children, drained=drained)

    monkeypatch.setattr(caps._SeatMemoryObserver, "sample", controlled_sample)
    with caps._seat_memory_attempt() as attempt:
        try:
            child = memory_host.launch("fixture")
            assert child.wait(timeout=5) == 0
            memory_host.drain(child)
            assert blocked.wait(timeout=3)
            snapshot, notice = attempt.finish()
            assert attempt.sampler.is_alive()
            assert snapshot["state"] == "partial"
            assert snapshot["peak_bytes"] == 0
            assert not notice
            _memory_readings(memory_host.scope(child).parent, oom=9)
        finally:
            release.set()
            attempt.sampler.join(timeout=3)
        assert not attempt.sampler.is_alive()
    assert "seat_memory_max_reached" not in caplog.text


def test_seat_memory_spawn_hook_can_start_another_scoped_child(memory_host):
    children = []
    with caps._seat_memory_attempt() as attempt:
        outer = memory_host.launch(
            "fixture", before_spawn=lambda: children.append(memory_host.launch("fixture")),
        )
        for child in (outer, *children):
            assert child.wait(timeout=5) == 0
            memory_host.drain(child)
        assert len(children) == 1
        assert attempt.finish()[0]["state"] == "final"


def _owner_record(unit):
    with caps._owner_directory(create=True) as directory:
        return Path(f"/proc/self/fd/{directory}").resolve() / unit


def _runtime_dropins(unit):
    return caps._runtime_dir() / "systemd/user.control" / (unit + ".d")


def _wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.02)


@pytest.fixture(params=[
    pytest.param("fake", id="fake"),
    pytest.param("systemd", id="systemd"),
])
def namespace_manager(request, monkeypatch, tmp_path):
    if request.param == "systemd":
        if os.environ.get("PHASE_LOOP_SEAT_CAPS_PROBE") != "1":
            pytest.skip("set PHASE_LOOP_SEAT_CAPS_PROBE=1 on the designated systemd host")
        assert caps.readiness_code() is None
        from contextlib import contextmanager
        import tempfile

        # The manager is shared. Make even the test sweeper see only our records.
        with tempfile.TemporaryDirectory(prefix="seat-probe-", dir=caps._runtime_dir()) as records:
            @contextmanager
            def owner_directory(*, create=False):
                fd = os.open(records, os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    yield fd
                finally:
                    os.close(fd)

            monkeypatch.setattr(caps, "_owner_directory", owner_directory)
            yield
        return

    # A fake manager with persistent drop-ins and cgroup files shared by all owners.
    request.getfixturevalue("isolated")
    _install_fake_cap_host(monkeypatch, tmp_path, None)
    systemctl = caps._systemctl

    def persistent_dropins(*args, **kwargs):
        if args[:2] == ("--no-reload", "revert"):
            shutil.rmtree(_runtime_dropins(args[2]))
            return SimpleNamespace(returncode=0)
        if args[0] == "set-property":
            unit = args[2]
            assert _owner_record(unit).is_file()
            dropins = _runtime_dropins(unit)
            dropins.mkdir()
            (dropins / "50-MemoryMax.conf").write_text(args[3])
        return systemctl(*args, **kwargs)

    monkeypatch.setattr(caps, "_systemctl", persistent_dropins)
    yield


def _overlap_owner(connection, launch_class):
    key = "same-logical-seat"
    with caps._seat_scope(key, launch_class):
        with caps._seat_memory_attempt():
            child = caps.capped_popen(["/usr/bin/sleep", "30"], seat_key=key)
            parent = caps._CURRENT_SEAT_SCOPE.get().parent
            child_unit = Path(caps._proc_cgroup_of(child.pid)).name
            connection.send((parent.unit, child_unit, child.pid))
            try:
                if connection.poll(20):
                    connection.recv()
            finally:
                child.terminate()
                child.wait(timeout=5)
    _wait_until(lambda: not _owner_record(parent.unit).exists())


@pytest.mark.parametrize("classes", [("BOARD", "BOARD"), ("TEST", "TEST"),
                                    ("BOARD", "QUALIFICATION")])
@pytest.mark.parametrize("first", [0, 1])
def test_per_attempt_namespaces_overlap(namespace_manager, classes, first, monkeypatch):
    import multiprocessing

    if not sys.platform.startswith("linux"):
        pytest.skip("seat caps require Linux")
    process_context = multiprocessing.get_context("fork")
    children = []
    receivers = []
    owners = []
    limits = (64 << 20, 96 << 20)
    try:
        for name, maximum in zip(classes, limits):
            selected = replace(caps.DEFAULT_CAPS, memory_max_bytes=maximum)
            monkeypatch.setattr(caps, "load_caps", lambda: selected)
            receiver, sender = process_context.Pipe()
            owner = process_context.Process(
                target=_overlap_owner, args=(sender, getattr(caps._LaunchClass, name)),
            )
            owner.start()
            sender.close()
            owners.append(owner)
            receivers.append(receiver)
            assert receiver.poll(10), f"{name} owner failed to start its capped child"
            children.append(receiver.recv())
        assert len({unit for unit, _, _ in children}) == 2
        assert len({child for _, child, _ in children}) == 2
        for (unit, child, pid), maximum in zip(children, limits):
            assert _runtime_dropins(unit).is_dir()
            assert child.startswith(unit.removesuffix(".slice") + "-")
            assert (caps._seat_slice_chain(unit)[-1] / "memory.max").read_text().strip() == str(maximum)
            os.kill(pid, 0)
        receivers[first].send("collect")
        owners[first].join(10)
        assert owners[first].exitcode == 0
        collected = children[first][0]
        assert not _runtime_dropins(collected).exists()
        assert not _owner_record(collected).exists()
        second = 1 - first
        survivor, child, pid = children[second]
        os.kill(pid, 0)
        assert Path(caps._proc_cgroup_of(pid)).name == child
        assert _runtime_dropins(survivor).exists()
        assert (caps._seat_slice_chain(survivor)[-1] / "memory.max").read_text().strip() == str(limits[second])
    finally:
        for owner, receiver in zip(owners, receivers):
            if owner.is_alive():
                receiver.send("collect")
                owner.join(5)
            if owner.is_alive():
                owner.kill()
                owner.join(5)
            receiver.close()
    for unit, _, _ in children:
        assert not _owner_record(unit).exists()
        assert not _runtime_dropins(unit).exists()


def test_attempt_class_is_internal_and_uses_one_hex_leaf(monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_SEAT_LAUNCH_CLASS", "test")
    key = "qualification:../../test"
    with caps._seat_scope(key):
        scope = caps._CURRENT_SEAT_SCOPE.get()
        assert scope.launch_class is caps._LaunchClass.BOARD
        assert caps._ISOLATED_UNIT.fullmatch(scope.unit)[1] == "01"
        legacy = f"phase-loop-seat-{caps._unit_key(key)}.slice"
        assert caps._seat_slice_chain(scope.unit)[:-1] == caps._seat_slice_chain(legacy)[:-1]
        with caps._seat_scope(key):
            assert caps._CURRENT_SEAT_SCOPE.get() is scope
        with pytest.raises(caps.CapsUnavailable, match="two launch classes"):
            with caps._seat_scope(key, caps._LaunchClass.TEST):
                pytest.fail("an explicit nested mismatch reached the launch")
    with caps._seat_scope(key):
        assert caps._CURRENT_SEAT_SCOPE.get().unit != scope.unit


def test_isolated_memory_attempts_start_fresh(memory_host):
    units = []
    for peak in (123, 456):
        with caps._seat_memory_attempt() as attempt, caps._seat_scope("same-key"):
            child = memory_host.launch("same-key")
            assert child.wait(timeout=5) == 0
            memory_host.drain(child)
            parent = memory_host.scope(child).parent
            units.append(parent.name)
            _memory_readings(parent, current=10, peak=peak)
            assert attempt.finish()[0]["peak_source"] == "kernel"
            assert attempt.finish()[0]["peak_bytes"] == peak
        _wait_for_parent_collection()
    assert units[0] != units[1]


def test_reaper_collects_crashed_owner_and_preserves_live_owner(namespace_manager):
    import multiprocessing

    process_context = multiprocessing.get_context("fork")
    owners = []
    try:
        launched = []
        for _ in range(2):
            receiver, sender = process_context.Pipe()
            owner = process_context.Process(
                target=_overlap_owner, args=(sender, caps._LaunchClass.BOARD),
            )
            owner.start()
            sender.close()
            owners.append((owner, receiver))
            assert receiver.poll(10)
            launched.append(receiver.recv())
        dead, live = launched
        owners[0][0].kill()
        owners[0][0].join(5)
        assert caps._reap_dead_seats(caps._LaunchClass.BOARD, dry_run=True) == {
            "stale": 1, "unknown": 0,
        }
        assert caps._reap_dead_seats(caps._LaunchClass.BOARD) == {"stale": 1, "unknown": 0}
        assert not _owner_record(dead[0]).exists()
        assert not _runtime_dropins(dead[0]).exists()
        assert _owner_record(live[0]).exists()
        assert _runtime_dropins(live[0]).exists()
        assert Path(caps._proc_cgroup_of(live[2])).name == live[1]
        assert (caps._seat_slice_chain(live[0])[-1] / "memory.max").read_text().strip() == str(
            caps.DEFAULT_CAPS.memory_max_bytes)
    finally:
        for owner, receiver in owners:
            if owner.is_alive():
                receiver.send("collect")
                owner.join(5)
            if owner.is_alive():
                owner.kill()
                owner.join(5)
            receiver.close()
        # The fake manager does not send stop signals to its fake cgroup members.
        if len(launched) == 2 and caps._CGROUP_ROOT != Path("/sys/fs/cgroup"):
            try:
                os.kill(launched[0][2], signal.SIGTERM)
            except ProcessLookupError:
                pass


def _record_existing_owner(unit, *, pid=None, started=None, launch_class="board"):
    pid = os.getpid() if pid is None else pid
    if started is None:
        started = caps._owner_stat(pid)[1]
    owner = caps._SeatOwner(unit, launch_class, pid, started, caps._boot_id())
    with caps._owner_directory(create=True) as directory, caps._register_owner(directory, owner):
        pass
    return owner


def test_reaper_handles_pid_reuse_unknowns_and_unloaded_records(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    runtime_control = runtime / "systemd/user.control"
    runtime_control.mkdir(parents=True)
    start = caps._owner_stat(os.getpid())[1]
    reused, unknown, forged, unloaded = [
        f"phase-loop-seat-01{index:032x}.slice" for index in range(4)
    ]
    _record_existing_owner(reused, started=start + 1)
    _record_existing_owner(unknown, pid=13, started=1)
    _record_existing_owner(forged, started=start + 1, launch_class="test")
    _record_existing_owner(unloaded, started=start + 1)
    for unit in (reused, unloaded):
        _runtime_dropins(unit).mkdir()
        (_runtime_dropins(unit) / "50-MemoryMax.conf").touch()
    read_stat = caps._owner_stat

    def read_owner(pid):
        if pid == 13:
            raise PermissionError
        return read_stat(pid)

    monkeypatch.setattr(caps, "_owner_stat", read_owner)
    calls = []

    def systemctl(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("show", "--property=UnitPath"):
            return SimpleNamespace(returncode=0, stdout=str(runtime_control).encode())
        if args[0] == "show":
            status = "not-found" if args[-1] == unloaded or ("stop", reused) in calls else "loaded"
            return SimpleNamespace(
                returncode=int(status == "not-found"),
                stdout=f"LoadState={status}\nActiveState=inactive\nJob=\n".encode(),
            )
        if args[0] == "stop":
            assert args[-1] == reused and kwargs["check"] is False
            return SimpleNamespace(returncode=1)  # systemd unloaded it before the stop call
        assert args[:2] == ("--no-reload", "revert")
        shutil.rmtree(_runtime_dropins(args[-1]))

    monkeypatch.setattr(caps, "_systemctl", systemctl)
    assert caps._reap_dead_seats(caps._LaunchClass.BOARD) == {"stale": 2, "unknown": 2}
    assert not _owner_record(reused).exists() and not _runtime_dropins(reused).exists()
    assert not _owner_record(unloaded).exists() and not _runtime_dropins(unloaded).exists()
    assert _owner_record(unknown).is_file() and _owner_record(forged).is_file()
    assert not any(unknown in args or forged in args for args in calls)


def test_two_reapers_collect_an_owner_record_once(monkeypatch, tmp_path):
    import multiprocessing

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with caps._seat_scope("reap-race"):
        unit = caps._CURRENT_SEAT_SCOPE.get().unit
    _record_existing_owner(unit, started=caps._owner_stat(os.getpid())[1] + 1)
    context = multiprocessing.get_context("fork")
    entered, release = context.Event(), context.Event()

    def collect(directory, fd, exact_unit):
        assert exact_unit == unit
        entered.set()
        assert release.wait(5)
        os.unlink(unit, dir_fd=directory)

    monkeypatch.setattr(caps, "_collect_owner", collect)
    first = context.Process(target=caps._reap_dead_seats, args=(caps._LaunchClass.BOARD,))
    first.start()
    try:
        assert entered.wait(5)
        assert caps._reap_dead_seats(caps._LaunchClass.BOARD) == {"stale": 0, "unknown": 0}
    finally:
        release.set()
        first.join(5)
        if first.is_alive():
            first.kill()
            first.join(5)
    assert first.exitcode == 0
    assert not _owner_record(unit).exists()
    assert caps._reap_dead_seats(caps._LaunchClass.BOARD) == {"stale": 0, "unknown": 0}


def test_scoped_refusal_cleans_exact_record_and_dropins(namespace_manager):
    with pytest.raises(seat_jail.SeatSandboxRefused):
        with caps._seat_scope("refused-seat"):
            unit = caps._CURRENT_SEAT_SCOPE.get().unit

            def refuse():
                assert _owner_record(unit).is_file()
                assert _runtime_dropins(unit).is_dir()
                raise OSError("refusal at spawn gate")

            caps.capped_popen(["/usr/bin/false"], seat_key="refused-seat", before_spawn=refuse)
    assert not _owner_record(unit).exists()
    assert not _runtime_dropins(unit).exists()


def test_failed_reap_retains_the_record_and_board_launch_continues(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with caps._seat_scope("dead-previous-board"):
        unit = caps._CURRENT_SEAT_SCOPE.get().unit
    _record_existing_owner(unit, started=caps._owner_stat(os.getpid())[1] + 1)

    def fail_collect(*args):
        raise OSError("test collection failure")

    monkeypatch.setattr(caps, "_collect_owner", fail_collect)
    monkeypatch.setattr(panel_invoker, "_default_spawn", lambda *a, **k: ("OK", "review\nAGREE"))
    result = panel_invoker.invoke_panel("artifact", ("codex",), max_concurrency=1)
    assert result.legs[0].usable
    assert _owner_record(unit).is_file()
    assert "test collection failure" in caplog.text


def test_reaper_never_exclusively_locks_live_or_unverifiable_records(monkeypatch, tmp_path):
    from phase_loop_runtime import file_lock

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with caps._seat_scope("live-and-unverifiable"):
        live = caps._CURRENT_SEAT_SCOPE.get().unit
    _record_existing_owner(live)
    with caps._seat_scope("different-boot"):
        different_boot = caps._CURRENT_SEAT_SCOPE.get().unit
    owner = caps._SeatOwner(different_boot, "board", os.getpid(), 1, "different-boot")
    with caps._owner_directory() as directory, caps._register_owner(directory, owner):
        pass
    with caps._seat_scope("wrong-uid"):
        wrong_uid = caps._CURRENT_SEAT_SCOPE.get().unit
    _record_existing_owner(wrong_uid, started=caps._owner_stat(os.getpid())[1] + 1)
    wrong_ino = _owner_record(wrong_uid).stat().st_ino
    fstat = os.fstat

    def foreign_owner(fd):
        info = fstat(fd)
        if info.st_ino == wrong_ino:
            return SimpleNamespace(st_uid=os.geteuid() + 1)
        return info

    def refuse_lock(*args, **kwargs):
        pytest.fail("sweep tried to lock an unverified owner")

    monkeypatch.setattr(caps.os, "fstat", foreign_owner)
    monkeypatch.setattr(file_lock, "acquire_exclusive", refuse_lock)
    assert caps._reap_dead_seats(caps._LaunchClass.BOARD) == {"stale": 0, "unknown": 2}
    assert all(_owner_record(unit).exists() for unit in (live, different_boot, wrong_uid))
