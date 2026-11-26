"""Fail-closed per-seat cgroup limits for local provider launches."""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
import hashlib
import json
import logging
import os
from pathlib import Path
import select
import stat
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Literal, Sequence

if TYPE_CHECKING:
    from . import provider_tree_proof as _tree_proof


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
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_CGROUP = Path("/proc/self/cgroup")
_SYSTEMD_RUN = Path("/usr/bin/systemd-run")
_SYSTEMCTL = Path("/usr/bin/systemctl")
_DEV_BLOCK = Path("/dev/block")
_TMPFS_MAGIC = 0x01021994
_DIAGNOSTIC_CAP = 4096


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
    if not hasattr(os, "O_NOFOLLOW"):
        _refuse("no-follow caps record open is unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
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
    if not (hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")):
        _refuse("no-follow caps directory open is unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
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
        manager = _manager_cgroup()
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
        "memory.swap.max": "0",
        "cpu.weight": str(caps.cpu_weight),
        "cpu.max": f"{caps.cpu_max_percent * 1000} {_CPU_PERIOD}",
        "io.weight": str(caps.io_weight),
        "io.max": io_rows,
        "pids.max": str(caps.pids_max),
    }
    return value


def _manager_cgroup() -> Path:
    return (_CGROUP_ROOT / "user.slice" / f"user-{os.getuid()}.slice"
            / f"user@{os.getuid()}.service")


def _seat_slice_chain(unit: str) -> tuple[Path, ...]:
    """Return the user-manager root through this generated seat slice."""
    if not unit.startswith("phase-loop-seat-") or not unit.endswith(".slice"):
        _refuse("the capped parent unit is invalid")
    parts = unit.removesuffix(".slice").split("-")
    current = _manager_cgroup()
    chain = [current]
    for index in range(1, len(parts) + 1):
        current /= "-".join(parts[:index]) + ".slice"
        chain.append(current)
    return tuple(chain)


def _realized_parent_ready(unit: str, carved: Sequence[Path]) -> bool:
    """Check controller propagation and files after systemd realizes the empty parent."""
    try:
        chain = _seat_slice_chain(unit)
        for path in chain:
            controllers = set((path / "cgroup.controllers").read_text(encoding="ascii").split())
            if not REQUIRED_CONTROLLERS <= controllers:
                return False
        for path in chain[:-1]:
            enabled = set((path / "cgroup.subtree_control").read_text(encoding="ascii").split())
            if not REQUIRED_CONTROLLERS <= enabled:
                return False
        names = {
            "memory.max", "memory.swap.max", "cpu.weight", "cpu.max",
            "io.weight", "io.max", "pids.max",
        }
        return all((chain[-1] / name).is_file() for name in names)
    except (CapsUnavailable, OSError, ValueError):
        return False


@dataclass
class _Parent:
    unit: str
    digest: str
    refs: int = 0
    children: int = 0
    owner: object | None = None
    fresh: bool = False
    shared: threading.Event = field(default_factory=threading.Event)


_PARENTS: dict[str, _Parent] = {}
_PARENT_LOCK = threading.RLock()


def _unit_key(seat_key: str) -> str:
    return hashlib.sha256(seat_key.encode()).hexdigest()[:24]


_MEMORY_READ_CAP = 4096
_MEMORY_COUNTER_MAX = (1 << 64) - 1
_MEMORY_SAMPLE_S = 1.0
_MEMORY_SAMPLER_JOIN_S = 1.0
SEAT_MEMORY_NOTICE_FULL_STALL_US = 1_000_000
SEAT_MEMORY_NOTICE = "seat_memory_max_reached"
_MEMORY_EVENTS = {"max": "max", "high": "high", "oom": "oom", "oom_kill": "oom_kill"}
_MEMORY_FILES = {
    "memory.events": _MEMORY_EVENTS,
    "memory.events.local": {"max": "local_max"},
    "memory.pressure": {"some": "some_stall_us", "full": "full_stall_us"},
}
_MEMORY_COLUMNS = tuple(field for fields in _MEMORY_FILES.values() for field in fields.values())
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)


def _open_memory_parent(path: Path) -> int:
    """Pin the exact cgroup, rejecting symlinks anywhere in the absolute chain."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise OSError("no no-follow support")
    flags = _DIRECTORY_FLAGS | os.O_NOFOLLOW
    directory = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return directory
    except OSError:
        os.close(directory)
        raise


def _memory_parent_absent(unit: str) -> bool:
    try:
        os.close(_open_memory_parent(_seat_slice_chain(unit)[-1]))
    except FileNotFoundError:
        return True
    except OSError:
        pass
    return False


def _memory_file(directory: int, name: str) -> str:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("unexpected cgroup file type")
        body = os.read(descriptor, _MEMORY_READ_CAP + 1)
        if len(body) > _MEMORY_READ_CAP or not body.endswith(b"\n"):
            raise ValueError("invalid cgroup file length")
        return body.decode("ascii")
    finally:
        os.close(descriptor)


def _memory_integer(value: str) -> int:
    if not value.isdecimal() or len(value) > 20:
        raise ValueError("invalid cgroup number")
    number = int(value)
    if number > _MEMORY_COUNTER_MAX:
        raise ValueError("cgroup counter overflow")
    return number


def _memory_rows(body: str, *, pressure: bool = False) -> dict[str, int]:
    rows: dict[str, int] = {}
    for line in body.splitlines():
        key, *values = line.split()
        if key in rows:
            raise ValueError("duplicate cgroup row")
        if pressure:
            assignments = _pairs(value.split("=") for value in values)
            if assignments.keys() != {"avg10", "avg60", "avg300", "total"}:
                raise ValueError("invalid pressure row")
            for name in ("avg10", "avg60", "avg300"):
                whole, dot, fraction = assignments[name].partition(".")
                if not dot or len(fraction) != 2 or _memory_integer(whole) > 100:
                    raise ValueError("invalid pressure average")
                _memory_integer(fraction)
            value = assignments["total"]
        else:
            value, = values
        rows[key] = _memory_integer(value)
    return rows


def _unavailable_memory() -> dict[str, object]:
    return {
        "max_bytes": None, "peak_bytes": None, "peak_source": None,
        **dict.fromkeys(_MEMORY_COLUMNS), "state": "unavailable",
    }


class _SeatMemoryObserver:
    def __init__(self, path: Path, *, fresh: bool, maximum: int, shared: threading.Event):
        self.path = path
        self.maximum = maximum
        self.max_bytes = None
        self.shared = shared
        self.directory = _open_memory_parent(path)
        self.baseline = self._counters()
        self.counters: dict[str, int] = {}
        self.regressed: set[str] = set()
        self.sampled_peak = self._number("memory.current")
        self.kernel_peak = self._number("memory.peak")
        self.attributable = fresh and self._empty() and self._owns_parent(())
        self._read_max()
        self.kernel = self.attributable and self.kernel_peak == 0

    def _number(self, name: str) -> int | None:
        try:
            return _memory_integer(_memory_file(self.directory, name).strip())
        except (OSError, ValueError):
            return None

    def _read_max(self) -> bool:
        if self._number("memory.max") != self.maximum:
            return False
        self.max_bytes = self.maximum
        return True

    def _rows(self, name: str) -> dict[str, int]:
        try:
            return _memory_rows(_memory_file(self.directory, name), pressure=name == "memory.pressure")
        except (OSError, ValueError):
            return {}

    def _empty(self) -> bool:
        return self._rows("cgroup.events").get("populated") == 0

    def _owns_parent(self, children) -> bool:
        if self.shared.is_set():
            return False
        try:
            live = _open_memory_parent(self.path)
            try:
                if not os.path.samestat(os.fstat(live), os.fstat(self.directory)):
                    return False
            finally:
                os.close(live)
            # Only the tracked scopes may be under the attempt's parent. The scan has
            # a hard bound even if a misconfigured or shared parent contains junk.
            with os.scandir(self.directory) as entries:
                return all(index < 256 and (not entry.is_dir(follow_symlinks=False)
                                             or entry.name in children)
                           for index, entry in enumerate(entries))
        except OSError:
            return False

    def _counters(self) -> dict[str, int]:
        counters = {}
        for file, fields in _MEMORY_FILES.items():
            rows = self._rows(file)
            counters.update({output: rows[key] for key, output in fields.items() if key in rows})
        return counters

    def sample(self, children, *, drained: bool = False) -> dict[str, object]:
        current = self._number("memory.current")
        if current is not None:
            self.sampled_peak = max(current, self.sampled_peak or 0)
        peak = self._number("memory.peak")
        if peak is None or peak < max(self.kernel_peak or 0, self.sampled_peak or 0):
            self.kernel = False
        self.kernel_peak = peak
        latest = self._counters()
        valid = 0
        for key, value in latest.items():
            if key not in self.baseline or key in self.regressed:
                continue
            if value < self.counters.get(key, self.baseline[key]):
                self.regressed.add(key)
                continue
            self.counters[key] = value
            valid += 1

        # Check after reading: a replaced parent or foreign scope cannot lend
        # attribution to the readings taken above.
        self.attributable = self.attributable and self._owns_parent(children)
        use_kernel = self.attributable and self.kernel and peak is not None
        peak_bytes = peak if use_kernel else self.sampled_peak
        deltas = {key: self.counters[key] - self.baseline[key] if key in self.counters else None
                  for key in _MEMORY_COLUMNS}
        valid_max = self._read_max()
        complete = (drained and self.attributable and self._empty() and
                    (use_kernel or current is not None) and valid == len(deltas)
                    and valid_max)
        usable = peak_bytes is not None or bool(self.counters)
        return {
            "max_bytes": self.max_bytes,
            "peak_bytes": peak_bytes,
            "peak_source": ("kernel" if use_kernel else "sampled") if peak_bytes is not None else None,
            **deltas,
            "state": "final" if complete else "partial" if usable else "unavailable",
        }

    def reached_memory_max(self, snapshot) -> bool:
        if not self.attributable or self.shared.is_set():
            return False
        # Use the last good cumulative readings. A bad or regressed input cannot
        # increase a delta, and a good OOM reading does not depend on PSI support.
        def delta(field: str) -> int:
            return 0 if field in self.regressed else snapshot[field] or 0

        return (delta("oom") > 0 or delta("oom_kill") > 0
                or (delta("local_max") > 0 and
                    delta("full_stall_us") > SEAT_MEMORY_NOTICE_FULL_STALL_US))


class _SeatMemoryAttempt:
    """Track capped launches until the memory observation is sealed."""
    def __init__(self):
        self.lock = threading.Lock()
        self.identity = object()
        self.stop = threading.Event()
        self.finished = False
        self.sampler_done = False
        self.closing = False
        self.parent = None
        self.seat_key = ""
        self.carved = ()
        self.observer = None
        self.sampler = None
        self.children: dict[str, subprocess.Popen[bytes]] = {}
        self.expected_scopes: set[str] = set()
        self.result = (_unavailable_memory(), False)
        self.drained = False
        self.sealed = False

    def retain(self, seat_key: str, parent: _Parent, carved: Sequence[Path], maximum: int):
        with self.lock:
            if self.sealed:
                return
            if self.parent is parent:
                return
            if self.parent is not None:
                # An unexpected second parent cannot be attributed to the first.
                self.parent.shared.set()
                return
            with _PARENT_LOCK:
                parent.refs += 1
            self.parent, self.seat_key, self.carved = parent, seat_key, tuple(carved)
            try:
                self.observer = _SeatMemoryObserver(
                    _seat_slice_chain(parent.unit)[-1],
                    fresh=parent.fresh, maximum=maximum, shared=parent.shared,
                )
            except (OSError, ValueError):
                pass

    def reserve_scope(self, child_unit: str) -> bool:
        with self.lock:
            if self.sealed:
                # A later launch may overlap the terminal read on the same parent.
                if self.parent is not None:
                    self.parent.shared.set()
                return False
            self.expected_scopes.add(child_unit)
            return True

    def abandon_scope(self, child_unit: str) -> None:
        with self.lock:
            self.expected_scopes.discard(child_unit)

    def started(self, child_unit: str, process: subprocess.Popen[bytes]) -> None:
        with self.lock:
            if self.sealed:
                return
            self.children[child_unit] = process
            if self.observer is not None and self.sampler is None:
                sampler = threading.Thread(target=self._sample_live, daemon=True, name="seat-memory")
                try:
                    sampler.start()
                except RuntimeError:
                    return  # A terminal read still works.
                self.sampler = sampler

    def _sample(self, *, terminal: bool = False) -> None:
        snapshot = self.observer.sample(self.expected_scopes, drained=terminal and self.drained)
        with self.lock:
            # Discard a sample whose attribution was lost just after the read.
            if self.finished or (self.observer.attributable and self.observer.shared.is_set()):
                return
            already_noticed = self.result[1]
            notice = not already_noticed and self.observer.reached_memory_max(snapshot)
            self.result = (snapshot, already_noticed or notice)
        if notice:
            logging.getLogger(__name__).warning("%s for seat %s", SEAT_MEMORY_NOTICE, _unit_key(self.seat_key))

    def _sample_live(self) -> None:
        try:
            while not self.stop.wait(_MEMORY_SAMPLE_S):
                self._sample()
        finally:
            with self.lock:
                self.sampler_done = True
                if self.closing:
                    os.close(self.observer.directory)

    def finish(self) -> tuple[dict[str, object] | None, bool]:
        from . import provider_tree_proof
        with self.lock:
            self.sealed = True
            pending = self.expected_scopes - self.children.keys()
            children = tuple(self.children.values())
        self.stop.set()
        if not children:
            return None, False
        deadline = time.monotonic() + provider_tree_proof.TEARDOWN_BUDGET_S
        proofs = [provider_tree_proof.proof_of(process) for process in children]
        drained = all([
            proof is not None and proof.kind == provider_tree_proof.CGROUP and proof.observe(deadline)
            for proof in proofs
        ])
        self.drained = drained and not pending
        if self.sampler is not None:
            self.sampler.join(min(_MEMORY_SAMPLER_JOIN_S, max(0.0, deadline - time.monotonic())))
        # A live sampler may still own the observer's mutable counters. Otherwise the
        # finalizing thread can read directly, independent of sampler scheduling.
        if self.observer is not None and (self.sampler is None or self.sampler_done):
            self._sample(terminal=True)
        with self.lock:
            self.finished = True
            return self.result

    def close(self) -> None:
        self.stop.set()
        with self.lock:
            self.sealed = True
            self.closing = True
            if self.observer is not None and (self.sampler is None or self.sampler_done):
                os.close(self.observer.directory)
        if self.parent is not None:
            _release_parent(self.seat_key, self.parent, self.carved)


_CURRENT_MEMORY_ATTEMPT: ContextVar[_SeatMemoryAttempt | None] = ContextVar(
    "seat_resource_caps_memory_attempt", default=None,
)


@contextmanager
def _seat_memory_attempt():
    attempt = _SeatMemoryAttempt()
    token = _CURRENT_MEMORY_ATTEMPT.set(attempt)
    try:
        yield attempt
    finally:
        _CURRENT_MEMORY_ATTEMPT.reset(token)
        attempt.close()


def _systemctl(*args: str, timeout: float = 15.0) -> None:
    # Parent-slice management needs the same user-manager connection as the
    # later systemd-run launch, including when the caller uses a clean env.
    runtime = _runtime_dir()
    manager_env = {**os.environ, "XDG_RUNTIME_DIR": str(runtime),
                   "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime / 'bus'}"}
    result = subprocess.run([str(_SYSTEMCTL), "--user", *args], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=False, env=manager_env)
    if result.returncode:
        _refuse("the capped parent could not be configured")


def _parent_properties(caps: SeatResourceCaps, devices: Sequence[str], carved: Sequence[Path]) -> list[str]:
    properties = [
        f"MemoryMax={caps.memory_max_bytes}", "MemorySwapMax=0",
        f"CPUWeight={caps.cpu_weight}",
        f"CPUQuota={caps.cpu_max_percent}%", f"IOWeight={caps.io_weight}",
        f"TasksMax={caps.pids_max}",
        # A stopped slice keeps its runtime drop-ins. Replace the previous I/O
        # device list in the same set-property call when the slice is reused.
        "IOReadBandwidthMax=", "IOWriteBandwidthMax=", "IOReadIOPSMax=", "IOWriteIOPSMax=",
    ]
    for device in devices:
        # systemd's resource-control properties take a device-node path.  The
        # kernel readback remains bound to the canonical MAJ:MIN.
        systemd_device = _DEV_BLOCK / device
        properties.extend((
            f"IOReadBandwidthMax={systemd_device} {caps.io_max.rbps}",
            f"IOWriteBandwidthMax={systemd_device} {caps.io_max.wbps}",
            f"IOReadIOPSMax={systemd_device} {caps.io_max.riops}",
            f"IOWriteIOPSMax={systemd_device} {caps.io_max.wiops}",
        ))
    return properties


def _helper_failure(process: "subprocess.Popen[bytes]", diagnostic_bytes: bytes) -> str:
    """Return only the helper's bounded, purpose-built failure diagnostic."""
    diagnostic = diagnostic_bytes.decode("utf-8", "replace").strip()
    _kind, _separator, diagnostic = diagnostic.partition("\n")
    stderr = ""
    if process.stderr is not None:
        captured = process.stderr.read(_DIAGNOSTIC_CAP)
        if isinstance(captured, bytes):
            captured = captured.decode("utf-8", "replace")
        if isinstance(captured, str) and captured.startswith("seat cap attestation failed:"):
            stderr = captured.strip()
    if stderr:
        return f"child stderr: {stderr}"
    if diagnostic:
        return f"child diagnostic: {diagnostic}"
    return ""


def _acquire_parent(seat_key: str, caps: SeatResourceCaps, devices: Sequence[str],
                    carved: Sequence[Path], *, child: bool) -> tuple[_Parent, str | None]:
    digest = caps_sha256(caps)
    attempt = _CURRENT_MEMORY_ATTEMPT.get()
    owner = None if attempt is None else attempt.identity
    with _PARENT_LOCK:
        parent = _PARENTS.get(seat_key)
        if parent is None:
            unit = f"phase-loop-seat-{_unit_key(seat_key)}.slice"
            fresh = attempt is not None and _memory_parent_absent(unit)
            _systemctl("set-property", "--runtime", unit,
                       *_parent_properties(caps, devices, carved))
            _systemctl("start", unit)
            if not _realized_parent_ready(unit, carved):
                try:
                    _systemctl("stop", unit)
                except CapsUnavailable:
                    logging.getLogger(__name__).warning(
                        "unready seat resource-cap parent collection failed for %s", unit,
                    )
                _refuse("the host does not provide delegated seat controllers")
            parent = _Parent(unit=unit, digest=digest, owner=owner, fresh=fresh)
            _PARENTS[seat_key] = parent
        elif parent.digest != digest:
            _refuse("a second independent capped parent was requested")
        elif not _realized_parent_ready(parent.unit, carved):
            _refuse("the host does not provide delegated seat controllers")
        parent.refs += 1
        if not child:
            return parent, None
        if parent.owner is not owner:
            parent.shared.set()
        parent.children += 1
        return parent, f"{parent.unit.removesuffix('.slice')}-{parent.children}.scope"


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


def _proc_cgroup_of(pid: int) -> str:
    """The unified (``0::``) cgroup path of ``pid`` as the kernel reports it."""
    text = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii")
    unified = [line[3:] for line in text.splitlines() if line.startswith("0::")]
    if len(unified) != 1:
        raise ValueError("unified cgroup line unavailable")
    return unified[0]


def _systemctl_kill_fallback(unit: str):
    """The bounded ``systemctl --user kill`` used where the kernel has no ``cgroup.kill``."""
    runtime = _runtime_dir()
    manager_env = {**os.environ, "XDG_RUNTIME_DIR": str(runtime),
                   "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime / 'bus'}"}
    argv = [str(_SYSTEMCTL), "--user", "kill", "--signal=SIGKILL", unit]

    def fallback(timeout: float) -> None:
        from . import provider_tree_proof as _tree_proof
        _tree_proof.run_bounded(argv, timeout, env=manager_env)

    return fallback


def _witness_scope(pid: int, parent_unit: str, child_unit: str) -> _tree_proof.TreeProof:
    """Hold the launch scope's ``cgroup.events`` (and ``cgroup.kill``) for unreaped ``pid``.

    The caller has started no reaper, so ``pid`` names its own child throughout.  The
    path must be exactly the generated scope below the seat slice, before and after the
    descriptors are opened, and the scope must read ``populated 1``.
    """
    # Imported here, not at module level: the jail profile digest's import graph (which
    # loads this module) stays exactly its declared sources.
    from . import provider_tree_proof as _tree_proof
    scope = _seat_slice_chain(parent_unit)[-1] / child_unit
    expected = "/" + scope.relative_to(_CGROUP_ROOT).as_posix()
    first = _proc_cgroup_of(pid)
    if first != expected:
        _refuse("the launch cgroup is not the expected scope")
    directory = os.open(scope, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    events = kill = None
    try:
        events = os.open("cgroup.events", os.O_RDONLY | os.O_CLOEXEC, dir_fd=directory)
        try:
            kill = os.open("cgroup.kill", os.O_WRONLY | os.O_CLOEXEC, dir_fd=directory)
        except FileNotFoundError:
            kill = None
        try:
            populated = not _tree_proof.parse_events(os.pread(events, 4096, 0))
        except _tree_proof.ProofFault as exc:
            _refuse("the launch cgroup events are malformed", exc)
        if not populated:
            _refuse("the launch cgroup is not populated")
        if _proc_cgroup_of(pid) != first:
            _refuse("the launch cgroup changed while it was witnessed")
        return _tree_proof.TreeProof.cgroup(
            events, kill, unit=child_unit,
            kill_fallback=None if kill is not None else _systemctl_kill_fallback(child_unit),
        )
    except BaseException:
        for descriptor in (events, kill):
            if descriptor is not None:
                os.close(descriptor)
        raise
    finally:
        os.close(directory)


def _await_refused_child(process: "subprocess.Popen[bytes]") -> None:
    """Wait for the helper's cooperative exit after its gate closed, then escalate."""
    try:
        process.wait(timeout=_ATTEST_TIMEOUT_S)
        return
    except subprocess.TimeoutExpired:
        pass
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _refused(reason: str, exc: BaseException | None = None):
    from . import seat_jail
    error = seat_jail.SeatSandboxRefused(CODE, reason)
    if exc is not None:
        raise error from exc
    raise error


def capped_popen(command, *, seat_key: str, before_spawn=None,
                 **popen_kwargs) -> "subprocess.Popen[bytes]":
    """Start one local seat child below its seat-key parent and prove every cap.

    ``before_spawn`` (grok tool-surface contract v1, erratum 4), when given, is called once
    after every preflight check here and immediately before the child is created; a refusal
    before it creates no child and never calls it."""
    scope = _CURRENT_SEAT_SCOPE.get()
    attempt = _CURRENT_MEMORY_ATTEMPT.get()
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
        if attempt is not None:
            attempt.retain(seat_key, parent, carved, caps.memory_max_bytes)
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
        diagnostic_read, diagnostic_write = os.pipe()
        # The helper execs the target only after this gate opens, and the parent opens it
        # only once it holds the launch cgroup's witness.
        gate_read, gate_write = os.pipe()
        expected = json.dumps(_expected(caps, devices, carved), sort_keys=True, separators=(",", ":"))
        helper = Path(__file__).with_name("seat_resource_caps_enter.py")
        argv = [
            str(_SYSTEMD_RUN), "--user", "--scope", "--quiet", "--collect",
            f"--unit={child_unit}", f"--slice={parent.unit}",
            # A fixed description: without one, systemd describes a scope by its full
            # command line. The unit's metadata names only the seat key's digest.
            f"--description=phase-loop seat {_unit_key(seat_key)}",
            "--same-dir", "--",
            "/usr/bin/python3", "-I", "-S", str(helper), "--attest-fd", str(write_fd),
            "--env-fd", str(env_read), "--diagnostic-fd", str(diagnostic_write),
            "--gate-fd", str(gate_read),
            "--expected", expected, "--cgroup-root", str(_CGROUP_ROOT),
            "--proc-cgroup", str(_PROC_CGROUP),
            "--", *[os.fsdecode(item) for item in command],
        ]
        pass_fds = set(popen_kwargs.get("pass_fds", ()))
        pass_fds.update((write_fd, env_read, diagnostic_write, gate_read))
        popen_kwargs["pass_fds"] = tuple(sorted(pass_fds))
        popen_kwargs.setdefault("close_fds", True)
        observing = False
        try:
            try:
                observing = attempt is not None and attempt.reserve_scope(child_unit)
                if before_spawn is not None:
                    before_spawn()
                process = subprocess.Popen(argv, **popen_kwargs)
            except BaseException:
                if observing:
                    attempt.abandon_scope(child_unit)
                os.close(read_fd)
                os.close(diagnostic_read)
                os.close(gate_write)
                raise
        finally:
            os.close(write_fd)
            os.close(env_read)
            os.close(diagnostic_write)
            os.close(gate_read)
        try:
            readable, _, _ = select.select([read_fd], [], [], _ATTEST_TIMEOUT_S)
            attested = bool(readable and os.read(read_fd, 1) == b"1")
        finally:
            os.close(read_fd)
        if not attested:
            os.close(gate_write)
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            try:
                diagnostic = os.read(diagnostic_read, _DIAGNOSTIC_CAP)
            finally:
                os.close(diagnostic_read)
            if diagnostic.startswith(b"controller_unavailable\n"):
                _refuse("the host does not provide delegated seat controllers")
            detail = _helper_failure(process, diagnostic)
            suffix = f"; {detail}" if detail else ""
            _refuse(f"the child did not attest its effective caps{suffix}")
        os.close(diagnostic_read)
        from . import provider_tree_proof as _tree_proof
        try:
            proof = _witness_scope(process.pid, parent.unit, child_unit)
            _tree_proof.attach(process, proof)
            try:
                os.write(gate_write, b"1")
            except BrokenPipeError:
                _refuse("the capped child exited before its gate opened")
        except (CapsUnavailable, OSError, ValueError) as exc:
            os.close(gate_write)
            _await_refused_child(process)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            _refuse("the launch cgroup could not be witnessed", exc)
        os.close(gate_write)
        # Until the gate opens, finalization sees a pending reservation and cannot
        # publish a final sample. The telemetry seal never controls the gate.
        if observing:
            attempt.started(child_unit, process)

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
