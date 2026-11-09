"""The reservation-scoped ForwardTcp-to-Unix bridge (v13 PLACECLI, ``x-placement-semantics.bridge_bytes``).

A ``pi-runner`` or ``leg`` reservation on OpenShell gets exactly one bridge: one directory
(mode 0700) under the runtime's own bridge root holding one Unix socket (mode 0600). The
socket is a bidirectional raw byte pipe of the admitted ForwardTcp stream; the requester's
credential proxy connects to it and keeps link framing, relay and credentials. The placement
service and the sandbox hold no provider credential, and nothing here reads, logs or records
the bytes.

The socket lives as long as the reservation, longer than the ``agent-harness-placement``
call that created it, so a helper serves it: this module run as ``__main__`` through
:func:`seat_uid.trusted_module_argv`, never ``-m``. The helper binds only the Unix socket (no
public listener), connects to the ForwardTcp stream's local end named by the trusted
:class:`BridgeExposure`, pipes bytes, and removes its socket and directory when it is told
to stop or the reservation expires. The caller supplies no path, service name, host or port.

The live ForwardTcp stream source arrives with activation; until then a reservation can only
reach a bridge through a backend that supplies an exposure, and no production backend is
registered.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping

from .placement_process_contract import BridgeDescriptor, LeaseFlags, Reservation

__all__ = [
    "BRIDGE_CODES",
    "BridgeExposure",
    "BridgeHandle",
    "BridgeUnavailable",
    "ForwardTcpUnixBridge",
    "default_bridge_root",
]

#: The closed codes a bridge failure carries.
BRIDGE_CODES = frozenset({
    "bridge_not_applicable", "bridge_root_unsafe", "bridge_path_too_long",
    "bridge_stale_socket", "bridge_exposure_invalid", "bridge_start_failed",
    "bridge_cancelled",
})
_SOCKET_NAME = "s"
_SUN_PATH_MAX = 107
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_SERVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_READY = b"R"
_CHUNK = 65536
_POLL_S = 0.05


class BridgeUnavailable(RuntimeError):
    """The bridge could not be opened. ``str()`` is a closed code."""

    def __init__(self, code: str) -> None:
        super().__init__(code if code in BRIDGE_CODES else "bridge_start_failed")
        self.code = str(self.args[0])

    def __str__(self) -> str:
        return self.code


@dataclass(frozen=True)
class BridgeExposure:
    """What the admitted rung's trusted backend exposes for the ForwardTcp stream: the
    service name and the absolute path of the stream's local end."""

    service_name: str
    upstream: str

    def __post_init__(self) -> None:
        if (not isinstance(self.service_name, str) or not _SERVICE.fullmatch(self.service_name)
                or not isinstance(self.upstream, str) or not os.path.isabs(self.upstream)
                or "\0" in self.upstream or len(os.fsencode(self.upstream)) > _SUN_PATH_MAX):
            raise BridgeUnavailable("bridge_exposure_invalid")


@dataclass(frozen=True)
class BridgeHandle:
    """A live bridge: its descriptor and the helper that serves it, journal-serializable."""

    descriptor: BridgeDescriptor
    reservation_id: str
    directory: str
    pid: int
    start_ticks: int | None

    def to_json(self) -> dict[str, Any]:
        return {"descriptor": self.descriptor.to_json(), "reservation_id": self.reservation_id,
                "directory": self.directory, "pid": self.pid, "start_ticks": self.start_ticks}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "BridgeHandle":
        return cls(BridgeDescriptor.from_json(value["descriptor"]), str(value["reservation_id"]),
                   str(value["directory"]), int(value["pid"]),
                   None if value["start_ticks"] is None else int(value["start_ticks"]))


def default_bridge_root() -> Path:
    """Short enough for a Unix socket path: the user's runtime directory, by uid."""
    return Path("/run/user") / str(os.geteuid()) / "agent-harness-placement"


def _private_directory(path: Path) -> None:
    """Create (0700) or accept an existing directory owned by this user, never a link."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError:
        raise BridgeUnavailable("bridge_root_unsafe") from None
    try:
        info = os.lstat(path)
    except OSError:
        raise BridgeUnavailable("bridge_root_unsafe") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise BridgeUnavailable("bridge_root_unsafe")


def _start_ticks(pid: int) -> int | None:
    """Field 22 of ``/proc/<pid>/stat``: tells a live helper from a reused pid."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        return int(text.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _helper_alive(pid: int, start_ticks: int | None) -> bool:
    current = _start_ticks(pid)
    if current is None or start_ticks is None or current != start_ticks:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        return state.rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def _spawn_helper(directory: Path, upstream: str, expires_epoch: float) -> "subprocess.Popen[bytes]":
    from .seat_uid import trusted_module_argv

    argv = trusted_module_argv("phase_loop_runtime.placement_bridge", "serve",
                               str(directory), upstream, repr(float(expires_epoch)))
    return subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        cwd="/", env={"PATH": "/usr/bin:/bin"}, close_fds=True, start_new_session=True,
    )


class ForwardTcpUnixBridge:
    """Opens and closes the one bridge of a reservation (LANEEXEC ``x-bridge.attach``
    consumes these two calls unchanged)."""

    def __init__(self, root: Path | None = None, *,
                 spawn: Callable[[Path, str, float], "subprocess.Popen[bytes]"] | None = None,
                 ready_timeout_s: float = 10.0) -> None:
        self.root = Path(root) if root is not None else default_bridge_root()
        self._spawn = spawn if spawn is not None else _spawn_helper
        self.ready_timeout_s = float(ready_timeout_s)
        self._children: dict[int, "subprocess.Popen[bytes]"] = {}
        self._lock = threading.Lock()

    def open(self, reservation: Reservation, exposure: BridgeExposure, *,
             cancelled: threading.Event) -> BridgeHandle:
        if (reservation.workload not in ("pi-runner", "leg")
                or reservation.target.kind != "openshell"):
            raise BridgeUnavailable("bridge_not_applicable")
        if not isinstance(exposure, BridgeExposure):
            raise BridgeUnavailable("bridge_exposure_invalid")
        if not _ID.fullmatch(reservation.reservation_id) or not _ID.fullmatch(reservation.client):
            raise BridgeUnavailable("bridge_not_applicable")
        if cancelled.is_set():
            raise BridgeUnavailable("bridge_cancelled")
        self.root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _private_directory(self.root)
        client_root = self.root / reservation.client
        _private_directory(client_root)
        directory = client_root / reservation.reservation_id
        socket_path = directory / _SOCKET_NAME
        if len(os.fsencode(str(socket_path))) > _SUN_PATH_MAX:
            raise BridgeUnavailable("bridge_path_too_long")
        if os.path.lexists(directory):
            # One socket per reservation: whatever is there is stale, never reused.
            raise BridgeUnavailable("bridge_stale_socket")
        expires = _expiry_epoch(reservation.expires_at)
        try:
            process = self._spawn(directory, exposure.upstream, expires)
        except OSError:
            raise BridgeUnavailable("bridge_start_failed") from None
        ready = self._await_ready(process, cancelled)
        if not ready or not _socket_is_private(directory, socket_path):
            self._stop(process.pid, _start_ticks(process.pid), process)
            _remove_directory(directory)
            raise BridgeUnavailable("bridge_cancelled" if cancelled.is_set() else "bridge_start_failed")
        with self._lock:
            self._children[process.pid] = process
        descriptor = BridgeDescriptor(exposure.service_name, str(socket_path))
        return BridgeHandle(descriptor, reservation.reservation_id, str(directory), process.pid,
                            _start_ticks(process.pid))

    def _await_ready(self, process: "subprocess.Popen[bytes]", cancelled: threading.Event) -> bool:
        stream = process.stdout
        if stream is None:
            return False
        deadline = time.monotonic() + self.ready_timeout_s
        try:
            while time.monotonic() < deadline and not cancelled.is_set():
                ready, _, _ = select.select([stream], [], [], _POLL_S)
                if ready:
                    return os.read(stream.fileno(), 1) == _READY
                if process.poll() is not None:
                    return False
            return False
        except (OSError, ValueError):
            return False
        finally:
            stream.close()

    def close(self, handle: BridgeHandle, *, cancelled: threading.Event) -> LeaseFlags:
        """Stop the helper and remove the socket and its directory. ``cancelled`` cannot
        interrupt teardown: leaving a reservation is always possible."""
        with self._lock:
            process = self._children.pop(handle.pid, None)
        self._stop(handle.pid, handle.start_ticks, process)
        gone = _remove_directory(Path(handle.directory))
        stopped = not _helper_alive(handle.pid, handle.start_ticks)
        if gone and stopped:
            return LeaseFlags(fenced=True, destruction_observed=True, barrier_confirmed=True)
        return LeaseFlags(reserved=True, fenced=True, cleanup_pending=True)

    def _stop(self, pid: int, start_ticks: int | None,
              process: "subprocess.Popen[bytes] | None") -> None:
        if process is not None:
            if process.poll() is None:
                try:
                    process.send_signal(signal.SIGTERM)
                    process.wait(timeout=self.ready_timeout_s)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.ready_timeout_s)
                except OSError:
                    pass
            return
        if not _helper_alive(pid, start_ticks):
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        deadline = time.monotonic() + self.ready_timeout_s
        while time.monotonic() < deadline and _helper_alive(pid, start_ticks):
            time.sleep(_POLL_S)
        if _helper_alive(pid, start_ticks):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _expiry_epoch(expires_at: str | None) -> float:
    from datetime import datetime

    if expires_at is None:
        return time.time() + 3600.0
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise BridgeUnavailable("bridge_not_applicable") from None


def _socket_is_private(directory: Path, socket_path: Path) -> bool:
    try:
        folder, entry = os.lstat(directory), os.lstat(socket_path)
        names = os.listdir(directory)
    except OSError:
        return False
    return (stat.S_ISDIR(folder.st_mode) and stat.S_IMODE(folder.st_mode) == 0o700
            and folder.st_uid == os.geteuid() and stat.S_ISSOCK(entry.st_mode)
            and stat.S_IMODE(entry.st_mode) == 0o600 and entry.st_uid == os.geteuid()
            and names == [_SOCKET_NAME])


def _remove_directory(directory: Path) -> bool:
    """Remove a bridge directory this user owns: its one socket, then the directory."""
    try:
        info = os.lstat(directory)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        return False
    try:
        for name in os.listdir(directory):
            entry = directory / name
            if stat.S_ISSOCK(os.lstat(entry).st_mode):
                os.unlink(entry)
        os.rmdir(directory)
    except FileNotFoundError:
        return not os.path.lexists(directory)
    except OSError:
        return False
    return True


# -- the helper ----------------------------------------------------------------------------

def _pump(left: socket.socket, right: socket.socket, stop: threading.Event, end: float) -> None:
    """Copy bytes both ways until either side closes, the helper is stopped, or the end."""
    peers = {left: right, right: left}
    open_sides = {left, right}
    while open_sides and not stop.is_set() and time.time() < end:
        try:
            readable, _, _ = select.select(list(open_sides), [], [], 0.5)
        except (OSError, ValueError):
            return
        for side in readable:
            try:
                data = side.recv(_CHUNK)
            except OSError:
                return
            if not data:
                try:
                    peers[side].shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                open_sides.discard(side)
                continue
            try:
                peers[side].sendall(data)
            except OSError:
                return


def serve(directory: str, upstream: str, expires_epoch: float) -> int:
    """Run the bridge helper until stopped or expired. Writes one ready byte to stdout."""
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
    folder = Path(directory)
    path = folder / _SOCKET_NAME
    previous = os.umask(0o077)
    try:
        os.mkdir(folder, 0o700)
    except OSError:
        return 1
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        os.umask(0o177)
        listener.bind(str(path))
        os.umask(previous)
        os.chmod(path, 0o600)
        listener.listen(1)
        os.write(1, _READY)
        os.close(1)
        while not stop.is_set() and time.time() < expires_epoch:
            readable, _, _ = select.select([listener], [], [], 0.5)
            if not readable:
                continue
            client, _ = listener.accept()
            with client:
                link = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    link.settimeout(10.0)
                    link.connect(upstream)
                    link.settimeout(None)
                except OSError:
                    link.close()
                    continue
                with link:
                    _pump(client, link, stop, expires_epoch)
        return 0
    except (OSError, ValueError):
        return 1
    finally:
        listener.close()
        try:
            os.unlink(path)
        except OSError:
            pass
        try:
            os.rmdir(folder)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4 or args[0] != "serve":
        return 2
    try:
        expires = float(args[3])
    except ValueError:
        return 2
    if not os.path.isabs(args[1]) or not os.path.isabs(args[2]):
        return 2
    return serve(args[1], args[2], expires)


if __name__ == "__main__":
    raise SystemExit(main())
