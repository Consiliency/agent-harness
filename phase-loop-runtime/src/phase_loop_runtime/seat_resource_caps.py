"""Fail-closed per-seat cgroup limits for local provider launches."""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import select
import stat
import subprocess
import threading
from typing import Literal, Sequence


SCHEMA = "seat_resource_caps.v1"
CODE = "seat_resource_caps_unavailable"
REQUIRED_CONTROLLERS = frozenset({"cpu", "io", "memory", "pids"})
MANAGED_RECORD = Path("/etc/consiliency/tooling/seat-resource-caps.json")

_OPERATOR_RECORD = "seat-resource-caps.json"
_RECORD_CAP = 64 * 1024
_CPU_PERIOD = 100000
_ATTEST_TIMEOUT_S = 15.0
_ENV_PAYLOAD_CAP = 60 * 1024  # below the default pipe capacity, so the write never blocks
_CGROUP_ROOT = Path("/sys/fs/cgroup")
_SYS_DEV_BLOCK = Path("/sys/dev/block")
_MOUNTINFO = Path("/proc/self/mountinfo")
_PROC_SWAPS = Path("/proc/swaps")
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_CGROUP = Path("/proc/self/cgroup")
_SYSTEMD_RUN = Path("/usr/bin/systemd-run")
_SYSTEMCTL = Path("/usr/bin/systemctl")
_TMPFS_MAGIC = 0x01021994


@dataclass(frozen=True)
class IoMax:
    rbps: int
    wbps: int
    riops: int
    wiops: int


@dataclass(frozen=True)
class SeatResourceCaps:
    schema: Literal["seat_resource_caps.v1"]
    memory_max_bytes: int
    cpu_weight: int
    cpu_max_percent: int
    io_weight: int
    io_max: IoMax
    io_paths: tuple[str, ...]
    pids_max: int


DEFAULT_CAPS = SeatResourceCaps(
    schema=SCHEMA,
    memory_max_bytes=4294967296,
    cpu_weight=50,
    cpu_max_percent=200,
    io_weight=50,
    io_max=IoMax(rbps=104857600, wbps=52428800, riops=2000, wiops=1000),
    io_paths=(),
    pids_max=512,
)


class CapsUnavailable(RuntimeError):
    """Private cause for the single public caps refusal code."""


@dataclass
class _SeatScope:
    seat_key: str
    parent: _Parent | None = None
    carved: tuple[Path, ...] = ()


_CURRENT_SEAT_SCOPE: ContextVar[_SeatScope | None] = ContextVar(
    "seat_resource_caps_current_seat_scope", default=None
)
_UNCAPPED_NONSEAT_PROBE: ContextVar[bool] = ContextVar(
    "seat_resource_caps_uncapped_nonseat_probe", default=False
)


@contextmanager
def _seat_scope(seat_key: str):
    """Carry one seat identity and lazily retain its parent through the whole attempt."""
    if not isinstance(seat_key, str) or not seat_key:
        _refuse("a live seat key is required")
    existing = _CURRENT_SEAT_SCOPE.get()
    if existing is not None:
        if existing.seat_key != seat_key:
            _refuse("one launch context cannot carry two seat keys")
        yield
        return
    scope = _SeatScope(seat_key)
    token = _CURRENT_SEAT_SCOPE.set(scope)
    try:
        yield
    finally:
        _CURRENT_SEAT_SCOPE.reset(token)
        if scope.parent is not None:
            _release_parent(scope.seat_key, scope.parent, scope.carved)


def live_seat_key() -> str:
    """The seat key of the attempt running in this context, or empty outside one."""
    scope = _CURRENT_SEAT_SCOPE.get()
    return "" if scope is None else scope.seat_key


@contextmanager
def _uncapped_nonseat_probe():
    """Select the §4 Exempt path for a fixed measurement that is not a seat attempt."""
    token = _UNCAPPED_NONSEAT_PROBE.set(True)
    try:
        yield
    finally:
        _UNCAPPED_NONSEAT_PROBE.reset(token)


def nonseat_probe_active() -> bool:
    return _UNCAPPED_NONSEAT_PROBE.get()


def _refuse(reason: str, exc: BaseException | None = None):
    error = CapsUnavailable(reason)
    if exc is not None:
        raise error from exc
    raise error


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _read_regular(path: Path, *, owner: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner
                or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > _RECORD_CAP):
            _refuse("caps record is unsafe")
        data = os.read(fd, _RECORD_CAP + 1)
        if len(data) > _RECORD_CAP:
            _refuse("caps record is too large")
        return data
    finally:
        os.close(fd)


def _mem_total() -> int:
    for line in _PROC_MEMINFO.read_text(encoding="ascii").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    _refuse("MemTotal is unavailable")


def _integer(value: object, *, low: int, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        _refuse("caps record value is outside its bound")
    return value


def _decode_record(raw: bytes) -> SeatResourceCaps:
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        _refuse("caps record is malformed", exc)
    allowed = {"schema", "memory_max_bytes", "cpu_weight", "cpu_max_percent", "io_weight",
               "io_max", "io_paths", "pids_max"}
    if not isinstance(value, dict) or set(value) - allowed or value.get("schema", SCHEMA) != SCHEMA:
        _refuse("caps record shape is invalid")
    io_raw = value.get("io_max", {})
    if not isinstance(io_raw, dict) or set(io_raw) - {"rbps", "wbps", "riops", "wiops"}:
        _refuse("caps io_max shape is invalid")
    paths = value.get("io_paths", DEFAULT_CAPS.io_paths)
    if (not isinstance(paths, list) and not isinstance(paths, tuple)) or any(
            not isinstance(item, str) or not item or not Path(item).is_absolute()
            for item in paths):
        _refuse("caps io_paths are invalid")
    cpus = os.cpu_count() or 1
    base_io = DEFAULT_CAPS.io_max
    return SeatResourceCaps(
        schema=SCHEMA,
        memory_max_bytes=_integer(value.get("memory_max_bytes", DEFAULT_CAPS.memory_max_bytes),
                                  low=268435456, high=_mem_total()),
        cpu_weight=_integer(value.get("cpu_weight", DEFAULT_CAPS.cpu_weight), low=1, high=10000),
        cpu_max_percent=_integer(value.get("cpu_max_percent", DEFAULT_CAPS.cpu_max_percent),
                                 low=10, high=100 * cpus),
        io_weight=_integer(value.get("io_weight", DEFAULT_CAPS.io_weight), low=1, high=10000),
        io_max=IoMax(*(
            _integer(io_raw.get(name, getattr(base_io, name)), low=1)
            for name in ("rbps", "wbps", "riops", "wiops")
        )),
        io_paths=tuple(paths),
        pids_max=_integer(value.get("pids_max", DEFAULT_CAPS.pids_max), low=16),
    )


def _operator_record() -> Path:
    from . import seat_jail
    return seat_jail.state_home() / "phase-loop" / _OPERATOR_RECORD


def load_caps() -> SeatResourceCaps:
    """Load the first applicable strict record, or the finite packaged defaults."""
    try:
        if os.path.lexists(MANAGED_RECORD):
            return _decode_record(_read_regular(MANAGED_RECORD, owner=0))
        operator = _operator_record()
        if os.path.lexists(operator):
            from . import seat_jail
            for directory in (seat_jail.state_home(), operator.parent):
                if seat_jail.pass_store_dir_problem(directory) is not None:
                    _refuse("caps record directory is unsafe")
            return _decode_record(_read_regular(operator, owner=os.geteuid()))
        # Validate the defaults against this host too; a two-CPU quota cannot silently
        # exceed a one-CPU host's explicit upper bound.
        return _decode_record(json.dumps(asdict(DEFAULT_CAPS), separators=(",", ":")).encode())
    except CapsUnavailable:
        raise
    except (OSError, ValueError, TypeError) as exc:
        _refuse("caps record could not be read", exc)


def caps_sha256(caps: SeatResourceCaps) -> str:
    document = json.dumps(asdict(caps), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(document).hexdigest()


def _automatic_paths() -> tuple[Path, Path]:
    from . import sandbox_policy
    return (Path(sandbox_policy.staging_root()), Path(sandbox_policy._child_tmp_dir().path))


def _mount_type(device: tuple[int, int]) -> str | None:
    marker = f"{device[0]}:{device[1]}"
    best: str | None = None
    try:
        for line in _MOUNTINFO.read_text(encoding="utf-8").splitlines():
            before, separator, after = line.partition(" - ")
            fields = before.split()
            if separator and len(fields) >= 3 and fields[2] == marker:
                fstype = after.split()[0] if after.split() else ""
                best = fstype or best
    except OSError:
        return None
    return best


def _fstatfs_magic(fd: int) -> int:
    class _StatFs(ctypes.Structure):
        _fields_ = [("f_type", ctypes.c_long), ("rest", ctypes.c_byte * 248)]
    result = _StatFs()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.fstatfs(fd, ctypes.byref(result)) != 0:
        raise OSError(ctypes.get_errno(), "fstatfs")
    return int(result.f_type)


def _tmpfs_carveout(path: Path, device: tuple[int, int]) -> bool:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        actual = (os.major(info.st_dev), os.minor(info.st_dev))
        return actual == device and _mount_type(device) == "tmpfs" and _fstatfs_magic(fd) == _TMPFS_MAGIC
    finally:
        os.close(fd)


def _dev_number(path: Path) -> tuple[int, int]:
    info = os.stat(path)
    return os.major(info.st_dev), os.minor(info.st_dev)


def _read_dev(path: Path) -> tuple[int, int]:
    major, minor = path.read_text(encoding="ascii").strip().split(":", 1)
    return int(major), int(minor)


def _whole_device(device: tuple[int, int], seen: frozenset[tuple[int, int]] = frozenset()) -> tuple[int, int]:
    if device in seen:
        _refuse("block-device cycle")
    node = _SYS_DEV_BLOCK / f"{device[0]}:{device[1]}"
    try:
        resolved = node.resolve(strict=True)
    except OSError as exc:
        _refuse("block device is unresolvable", exc)
    next_seen = seen | {device}
    if (resolved / "partition").exists():
        try:
            return _whole_device(_read_dev(resolved.parent / "dev"), next_seen)
        except OSError as exc:
            _refuse("partition parent is unresolvable", exc)
    if (resolved / "dm").exists() or resolved.name.startswith("dm-"):
        try:
            slaves = tuple((resolved / "slaves").iterdir())
        except OSError as exc:
            _refuse("device-mapper slaves are unavailable", exc)
        if len(slaves) != 1:
            _refuse("device-mapper node does not have one slave")
        try:
            slave = _read_dev(slaves[0].resolve(strict=True) / "dev")
        except OSError as exc:
            _refuse("device-mapper slave is unresolvable", exc)
        return _whole_device(slave, next_seen)
    return device


def _device_plan(caps: SeatResourceCaps) -> tuple[tuple[str, ...], tuple[Path, ...]]:
    devices: list[str] = []
    carved: list[Path] = []
    automatic = _automatic_paths()
    for path, is_automatic in (*((item, True) for item in automatic),
                               *((Path(item), False) for item in caps.io_paths)):
        try:
            device = _dev_number(path)
            if device[0] == 0:
                if is_automatic and _tmpfs_carveout(path, device):
                    _refuse("tmpfs carve-out cleanup is not wired")
                _refuse("anonymous filesystem cannot carry io.max")
            whole = _whole_device(device)
        except CapsUnavailable:
            raise
        except OSError as exc:
            _refuse("caps path is unavailable", exc)
        rendered = f"{whole[0]}:{whole[1]}"
        if rendered not in devices:
            devices.append(rendered)
    return tuple(devices), tuple(carved)


def io_devices(caps: SeatResourceCaps) -> tuple[str, ...]:
    return _device_plan(caps)[0]


def _runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    return Path(value) if value and Path(value).is_absolute() else Path(f"/run/user/{os.getuid()}")


def _systemd_run_ready() -> bool:
    info = os.stat(_SYSTEMD_RUN, follow_symlinks=False)
    return (stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and bool(stat.S_IMODE(info.st_mode) & 0o111))


def readiness_code() -> str | None:
    try:
        if not (_CGROUP_ROOT / "cgroup.controllers").is_file():
            return CODE
        manager = (_CGROUP_ROOT / "user.slice" / f"user-{os.getuid()}.slice"
                   / f"user@{os.getuid()}.service")
        controllers = set((manager / "cgroup.controllers").read_text(encoding="ascii").split())
        if not REQUIRED_CONTROLLERS <= controllers:
            return CODE
        if not _systemd_run_ready():
            return CODE
        if not (_runtime_dir() / "bus").exists():
            return CODE
        io_devices(load_caps())
        return None
    except (CapsUnavailable, OSError, ValueError):
        return CODE


def _expected(caps: SeatResourceCaps, devices: Sequence[str], carved: Sequence[Path]) -> dict[str, object]:
    io_rows = {
        device: {"rbps": str(caps.io_max.rbps), "wbps": str(caps.io_max.wbps),
                 "riops": str(caps.io_max.riops), "wiops": str(caps.io_max.wiops)}
        for device in devices
    }
    value: dict[str, object] = {
        "memory.max": str(caps.memory_max_bytes),
        "cpu.weight": str(caps.cpu_weight),
        "cpu.max": f"{caps.cpu_max_percent * 1000} {_CPU_PERIOD}",
        "io.weight": str(caps.io_weight),
        "io.max": io_rows,
        "pids.max": str(caps.pids_max),
    }
    if carved:
        value["memory.swap.max"] = "0"
    return value


@dataclass
class _Parent:
    unit: str
    digest: str
    refs: int = 0
    children: int = 0


_PARENTS: dict[str, _Parent] = {}
_PARENT_LOCK = threading.RLock()


def _unit_key(seat_key: str) -> str:
    return hashlib.sha256(seat_key.encode()).hexdigest()[:24]


def _systemctl(*args: str, timeout: float = 15.0) -> None:
    result = subprocess.run([str(_SYSTEMCTL), "--user", *args], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=False)
    if result.returncode:
        _refuse("the capped parent could not be configured")


def _parent_properties(caps: SeatResourceCaps, devices: Sequence[str], carved: Sequence[Path]) -> list[str]:
    properties = [
        f"MemoryMax={caps.memory_max_bytes}", f"CPUWeight={caps.cpu_weight}",
        f"CPUQuota={caps.cpu_max_percent}%", f"IOWeight={caps.io_weight}",
        f"TasksMax={caps.pids_max}",
    ]
    if carved:
        properties.append("MemorySwapMax=0")
    for device in devices:
        properties.extend((
            f"IOReadBandwidthMax={device} {caps.io_max.rbps}",
            f"IOWriteBandwidthMax={device} {caps.io_max.wbps}",
            f"IOReadIOPSMax={device} {caps.io_max.riops}",
            f"IOWriteIOPSMax={device} {caps.io_max.wiops}",
        ))
    return properties


def _acquire_parent(seat_key: str, caps: SeatResourceCaps, devices: Sequence[str],
                    carved: Sequence[Path], *, child: bool) -> tuple[_Parent, str | None]:
    digest = caps_sha256(caps)
    with _PARENT_LOCK:
        parent = _PARENTS.get(seat_key)
        if parent is None:
            unit = f"phase-loop-seat-{_unit_key(seat_key)}.slice"
            _systemctl("set-property", "--runtime", unit,
                       *_parent_properties(caps, devices, carved))
            parent = _Parent(unit=unit, digest=digest)
            _PARENTS[seat_key] = parent
        elif parent.digest != digest:
            _refuse("a second independent capped parent was requested")
        parent.refs += 1
        if not child:
            return parent, None
        parent.children += 1
        return parent, f"phase-loop-seat-{_unit_key(seat_key)}-{parent.children}.scope"


def _release_parent(seat_key: str, parent: _Parent, _carved: Sequence[Path]) -> None:
    unit: str | None = None
    with _PARENT_LOCK:
        current = _PARENTS.get(seat_key)
        if current is parent:
            current.refs -= 1
            if current.refs == 0:
                unit = current.unit
                del _PARENTS[seat_key]
    if unit is not None:
        try:
            _systemctl("stop", unit)
        except CapsUnavailable:
            logging.getLogger(__name__).warning(
                "seat resource-cap parent collection failed for %s", unit,
            )


def _refused(reason: str, exc: BaseException | None = None):
    from . import seat_jail
    error = seat_jail.SeatSandboxRefused(CODE, reason)
    if exc is not None:
        raise error from exc
    raise error


def capped_popen(command, *, seat_key: str, **popen_kwargs) -> "subprocess.Popen[bytes]":
    """Start one local seat child below its seat-key parent and prove every cap."""
    scope = _CURRENT_SEAT_SCOPE.get()
    if not isinstance(seat_key, str) or not seat_key:
        _refused("a live seat key is required")
    if scope is not None and scope.seat_key != seat_key:
        _refused("the launch seat key disagrees with its live seat scope")
    parent: _Parent | None = None
    carved: tuple[Path, ...] = ()
    try:
        caps = load_caps()
        devices, carved = _device_plan(caps)
        if readiness_code() is not None:
            _refuse("the host does not provide delegated seat controllers")
        if scope is not None:
            with _PARENT_LOCK:
                if scope.parent is None:
                    scope.parent, _unused = _acquire_parent(
                        seat_key, caps, devices, carved, child=False,
                    )
                    scope.carved = tuple(carved)
                elif scope.parent.digest != caps_sha256(caps):
                    _refuse("the live seat's caps record changed")
        parent, child_unit = _acquire_parent(
            seat_key, caps, devices, carved, child=True,
        )
        assert child_unit is not None
        # systemd-run must reach the user manager, so it runs with the bus address; the
        # helper hands the target the exact caller-selected environment, read from a pipe
        # (never argv), so the target environment equals an uncapped launch's.
        selected = popen_kwargs.get("env")
        target_env = {os.fsdecode(key): os.fsdecode(value) for key, value in
                      (os.environ if selected is None else selected).items()}
        payload = json.dumps(target_env, sort_keys=True, separators=(",", ":")).encode()
        if len(payload) > _ENV_PAYLOAD_CAP:
            _refuse("the target environment is too large to hand over")
        runtime = _runtime_dir()
        popen_kwargs["env"] = {**target_env, "XDG_RUNTIME_DIR": str(runtime),
                               "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime / 'bus'}"}
        env_read, env_write = os.pipe()
        try:
            os.write(env_write, payload)
        finally:
            os.close(env_write)
        read_fd, write_fd = os.pipe()
        expected = json.dumps(_expected(caps, devices, carved), sort_keys=True, separators=(",", ":"))
        helper = Path(__file__).with_name("seat_resource_caps_enter.py")
        argv = [
            str(_SYSTEMD_RUN), "--user", "--scope", "--quiet", "--collect",
            f"--unit={child_unit}", f"--slice={parent.unit}", "--same-dir", "--",
            "/usr/bin/python3", "-I", "-S", str(helper), "--attest-fd", str(write_fd),
            "--env-fd", str(env_read),
            "--expected", expected, "--cgroup-root", str(_CGROUP_ROOT),
            "--proc-cgroup", str(_PROC_CGROUP), "--proc-swaps", str(_PROC_SWAPS),
            "--", *[os.fsdecode(item) for item in command],
        ]
        pass_fds = set(popen_kwargs.get("pass_fds", ()))
        pass_fds.update((write_fd, env_read))
        popen_kwargs["pass_fds"] = tuple(sorted(pass_fds))
        popen_kwargs.setdefault("close_fds", True)
        try:
            try:
                process = subprocess.Popen(argv, **popen_kwargs)
            except BaseException:
                os.close(read_fd)
                raise
        finally:
            os.close(write_fd)
            os.close(env_read)
        try:
            readable, _, _ = select.select([read_fd], [], [], _ATTEST_TIMEOUT_S)
            attested = bool(readable and os.read(read_fd, 1) == b"1")
        finally:
            os.close(read_fd)
        if not attested:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            _refuse("the child did not attest its effective caps")

        def reap() -> None:
            try:
                process.wait()
            finally:
                _release_parent(seat_key, parent, carved)

        threading.Thread(target=reap, daemon=True, name=f"seat-caps-{_unit_key(seat_key)}").start()
        return process
    except CapsUnavailable as exc:
        if parent is not None:
            _release_parent(seat_key, parent, carved)
        _refused(str(exc), exc)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if parent is not None:
            _release_parent(seat_key, parent, carved)
        _refused("the capped launch could not start", exc)


__all__ = [
    "SCHEMA", "CODE", "REQUIRED_CONTROLLERS", "MANAGED_RECORD", "IoMax",
    "SeatResourceCaps", "load_caps", "caps_sha256", "io_devices", "readiness_code",
    "capped_popen",
]
