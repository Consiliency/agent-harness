"""Kernel-provided completion evidence for one launched provider process tree.

A launch site that starts a contained tree attaches one :class:`TreeProof` to its
``Popen`` before the process object leaves that site.  Cleanup then reports success
only after the proof observes completion:

* ``cgroup``: the launch's own scope cgroup reads ``populated 0`` (recursive), or the
  held ``cgroup.events`` descriptor reports ``ENODEV`` (the node was removed, which
  the kernel refuses while it is populated);
* ``bwrap_init``: the pidfd of the authenticated PID-namespace init is readable.

A proof is sticky: once ``UNKNOWN`` it never becomes ``PROVEN``.  This module is
stdlib-only and imports no package module, so the caps launcher and the broker can
both use it.
"""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import threading
import time
from typing import Callable
import weakref


PENDING = "PENDING"
INCOMPLETE = "INCOMPLETE"
UNKNOWN = "UNKNOWN"
PROVEN = "PROVEN"
CGROUP = "cgroup"
BWRAP_INIT = "bwrap_init"

#: One observation slice; matches the panel's process-group poll interval.
SLICE_S = 0.05
#: The pin's info-fd read bound and the teardown budget a failed pin starts.
PIN_TIMEOUT_S = 10.0
TEARDOWN_BUDGET_S = 5.0
_INFO_CAP = 4096
_EVENTS_CAP = 4096
_EVENTS_LINE = re.compile(r"([a-z_]+) ([0-9]+)")
#: ``None`` where ``select`` has no ``poll`` (native Windows): the module still imports,
#: and every witness read there fails closed (``UNKNOWN``, ``poll_unavailable``).
_PIDFD_READY = (select.POLLIN | select.POLLHUP | select.POLLERR
                if hasattr(select, "poll") else None)


class ProofFault(Exception):
    """A witness read that cannot be interpreted; the proof becomes ``UNKNOWN``."""


def parse_events(body: bytes) -> bool:
    """``True`` for ``populated 0``, ``False`` for ``populated 1``; anything else raises.

    Every line must be ``<key> <integer>``; the ``populated`` key must occur exactly once
    with the value ``0`` or ``1``.
    """
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProofFault("events_malformed") from exc
    populated: list[str] = []
    for line in text.split("\n"):
        if not line:
            continue
        match = _EVENTS_LINE.fullmatch(line)
        if match is None:
            raise ProofFault("events_malformed")
        if match.group(1) == "populated":
            populated.append(match.group(2))
    if len(populated) != 1 or populated[0] not in {"0", "1"}:
        raise ProofFault("events_malformed")
    return populated[0] == "0"


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _slice_deadline(deadline: float | None) -> float:
    return time.monotonic() + SLICE_S if deadline is None else deadline


class TreeProof:
    """Completion evidence for one launched tree (see the module docstring).

    Every ``_lock`` acquisition on a caller's path is timed at ``min(remaining, SLICE_S)``
    against one absolute monotonic deadline the caller passes down; a standalone call
    takes one slice from its entry.  No read, poll, write, signal or subprocess runs
    under ``_lock``: each works on a private ``dup`` of the held descriptor that lives
    for that one operation, so a concurrent :meth:`close` cannot invalidate it.
    """

    def __init__(self, kind: str, *, status: str = INCOMPLETE, events_fd: int = -1,
                 kill_fd: int = -1, init_fd: int = -1, unit: str | None = None,
                 kill_fallback: Callable[[float], object] | None = None) -> None:
        if kind not in {CGROUP, BWRAP_INIT} or status not in {PENDING, INCOMPLETE}:
            raise ValueError("invalid tree proof")
        self.kind = kind
        self.status = status
        self.reason = ""
        self.closed = False
        self.events_fd = events_fd
        self.kill_fd = kill_fd
        self.init_fd = init_fd
        self.unit = unit
        self.kill_fallback = kill_fallback
        self.state_lock_busy = 0
        self.kill_errors: list[str] = []
        self._lock = threading.Lock()
        self.cleanup_lock = threading.Lock()

    @classmethod
    def cgroup(cls, events_fd: int, kill_fd: int | None, *, unit: str,
               kill_fallback: Callable[[float], object] | None = None) -> "TreeProof":
        return cls(CGROUP, events_fd=events_fd, kill_fd=-1 if kill_fd is None else kill_fd,
                   unit=unit, kill_fallback=kill_fallback)

    @classmethod
    def bwrap_init(cls, init_fd: int) -> "TreeProof":
        return cls(BWRAP_INIT, init_fd=init_fd)

    @classmethod
    def pending(cls) -> "TreeProof":
        return cls(BWRAP_INIT, status=PENDING)

    def describe(self) -> str:
        detail = f":{self.reason}" if self.reason else ""
        return f"{self.kind}:{self.status}{detail}"

    # -- locking -------------------------------------------------------------------

    def _acquire(self, deadline: float) -> bool:
        remaining = _remaining(deadline)
        if remaining <= 0:
            acquired = self._lock.acquire(blocking=False)
        else:
            acquired = self._lock.acquire(timeout=min(remaining, SLICE_S))
        if not acquired:
            self.state_lock_busy += 1
        return acquired

    def _witness_fd(self) -> int:
        return self.events_fd if self.kind == CGROUP else self.init_fd

    def _dup_witness(self, deadline: float) -> int | None:
        """A private duplicate of the held witness, or ``None`` when no read applies."""
        if not self._acquire(deadline):
            return None
        try:
            # PENDING has no witness: no descriptor operation and no transition.
            if self.status != INCOMPLETE or self.closed:
                return None
            fd = self._witness_fd()
            if fd < 0:
                return None
            try:
                return os.dup(fd)
            except OSError:
                return None
        finally:
            self._lock.release()

    def _close_locked(self) -> None:
        """Close the held originals exactly once.  The caller holds ``_lock``."""
        for name in ("events_fd", "kill_fd", "init_fd"):
            fd = getattr(self, name)
            if fd >= 0:
                setattr(self, name, -1)
                try:
                    os.close(fd)
                except OSError:
                    pass

    # -- observation ---------------------------------------------------------------

    def _read(self, fd: int) -> tuple[bool, str]:
        if _PIDFD_READY is None:
            raise ProofFault("poll_unavailable")
        if self.kind == CGROUP:
            try:
                body = os.pread(fd, _EVENTS_CAP, 0)
            except OSError as exc:
                if exc.errno == errno.ENODEV:
                    return True, "enodev"
                raise ProofFault("events_unreadable") from exc
            return parse_events(body), "unpopulated"
        poller = select.poll()
        poller.register(fd, select.POLLIN)
        events = poller.poll(0)
        mask = 0
        for _fd, revents in events:
            mask |= revents
        if mask & select.POLLNVAL:
            raise ProofFault("init_unreadable")
        return bool(mask & _PIDFD_READY), "init_exited"

    def observe(self, deadline: float | None = None) -> bool:
        """``True`` only when the proof is ``PROVEN``, after at most one bounded read."""
        deadline = _slice_deadline(deadline)
        if not self._acquire(deadline):
            return False
        try:
            if self.status == PROVEN:
                return True
        finally:
            self._lock.release()
        private = self._dup_witness(deadline)
        if private is None:
            return False
        fault: str | None = None
        positive = False
        reason = ""
        try:
            positive, reason = self._read(private)
        except ProofFault as exc:
            fault = str(exc)
        except OSError:
            fault = "witness_unreadable"
        finally:
            os.close(private)
        if not self._acquire(deadline):
            return False
        try:
            if self.status != INCOMPLETE or self.closed:
                return self.status == PROVEN
            if fault is not None:
                self.status, self.reason = UNKNOWN, fault
                return False
            if positive:
                self.status, self.reason = PROVEN, reason
                self._close_locked()
                return True
            return False
        finally:
            self._lock.release()

    def wait(self, deadline: float) -> bool:
        """Poll a private duplicate for at most one slice before ``deadline``, then observe."""
        remaining = _remaining(deadline)
        if remaining <= 0:
            return self.observe(deadline)
        private = self._dup_witness(deadline)
        if private is not None:
            try:
                if _PIDFD_READY is not None:  # no poll here; observe() fails closed
                    poller = select.poll()
                    poller.register(private, (select.POLLPRI | select.POLLERR)
                                    if self.kind == CGROUP else select.POLLIN)
                    timeout = min(SLICE_S, _remaining(deadline))
                    if timeout > 0:
                        poller.poll(int(timeout * 1000) or 1)
            except OSError:
                pass
            finally:
                os.close(private)
        elif self.status != PROVEN:
            # Nothing to poll (PENDING, UNKNOWN, closed or a busy lock): spend the slice.
            timeout = min(SLICE_S, _remaining(deadline))
            if timeout > 0:
                time.sleep(timeout)
        return self.observe(deadline)

    # -- kill ----------------------------------------------------------------------

    def kill(self, deadline: float) -> None:
        """Kill the witnessed tree; errors are recorded, never raised.  The proof decides."""
        if not self._acquire(deadline):
            return
        private = None
        fallback = None
        try:
            if self.closed or self.status in {PROVEN, PENDING}:
                return
            if self.kind == CGROUP and self.kill_fd < 0:
                fallback = self.kill_fallback
            else:
                fd = self.kill_fd if self.kind == CGROUP else self.init_fd
                if fd >= 0:
                    try:
                        private = os.dup(fd)
                    except OSError as exc:
                        self.kill_errors.append(f"dup:{exc.errno}")
        finally:
            self._lock.release()
        if private is not None:
            try:
                if self.kind == CGROUP:
                    os.write(private, b"1")
                else:
                    signal.pidfd_send_signal(private, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                self.kill_errors.append(f"kill:{exc.errno}")
            finally:
                os.close(private)
        elif fallback is not None:
            timeout = _remaining(deadline)
            if timeout <= 0:
                return
            try:
                fallback(timeout)
            except Exception as exc:  # the proof decides; a fallback fault is a note
                self.kill_errors.append(f"fallback:{type(exc).__name__}")

    # -- state transitions ---------------------------------------------------------

    def mark_witness_missing(self, deadline: float) -> bool:
        """``PENDING`` -> ``UNKNOWN("witness_missing")``; ``False`` when the lock is busy."""
        if not self._acquire(deadline):
            return False
        try:
            if self.status == PENDING:
                self.status, self.reason = UNKNOWN, "witness_missing"
            return True
        finally:
            self._lock.release()

    def mark_unknown(self, reason: str, deadline: float) -> bool:
        if not self._acquire(deadline):
            return False
        try:
            if self.status != PROVEN:
                self.status, self.reason = UNKNOWN, reason
            return True
        finally:
            self._lock.release()

    def adopt_init(self, fd: int, deadline: float | None = None) -> bool:
        """Adopt an init pidfd into a ``PENDING`` proof.  Any refusal closes ``fd``."""
        deadline = _slice_deadline(deadline)
        adopted = False
        try:
            if not self._acquire(deadline):
                return False
            try:
                if self.status == PENDING and not self.closed:
                    self.init_fd, self.status = fd, INCOMPLETE
                    adopted = True
                return adopted
            finally:
                self._lock.release()
        finally:
            if not adopted:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _close_body(self) -> None:
        self.closed = True
        if self.status != PROVEN:
            if self.status != UNKNOWN:
                self.reason = "closed"
            self.status = UNKNOWN
        self._close_locked()

    def close(self, deadline: float | None = None) -> bool:
        """Close with a bounded acquisition; on contention ownership is retained."""
        if not self._acquire(_slice_deadline(deadline)):
            return False
        try:
            self._close_body()
            return True
        finally:
            self._lock.release()

    def _close_blocking(self) -> None:
        with self._lock:
            self._close_body()

    def _finalize(self) -> None:
        """The finalizer's closure.  It never blocks the collecting thread."""
        if self._lock.acquire(blocking=False):
            try:
                self._close_body()
            finally:
                self._lock.release()
            return
        threading.Thread(target=self._close_blocking, daemon=True,
                         name="tree-proof-close").start()


def attach(proc: object, proof: TreeProof) -> TreeProof:
    """Bind ``proof`` to ``proc`` once; the descriptors close when ``proc`` is collected."""
    if isinstance(getattr(proc, "_phase_loop_proof", None), TreeProof):
        raise ValueError("a launch carries one tree proof")
    setattr(proc, "_phase_loop_proof", proof)
    weakref.finalize(proc, proof._finalize)
    return proof


def proof_of(proc: object) -> TreeProof | None:
    proof = getattr(proc, "_phase_loop_proof", None)
    return proof if isinstance(proof, TreeProof) else None


# -- bounded subprocess (the systemctl kill fallback) ----------------------------------

def run_bounded(argv: list[str], timeout: float, *, env: dict[str, str] | None = None) -> None:
    """Run ``argv`` for at most ``timeout`` seconds; never leave it untracked."""
    deadline = time.monotonic() + max(0.0, timeout)
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    try:
        process.wait(timeout=_remaining(deadline))
        return
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.wait(timeout=min(_remaining(deadline), SLICE_S))
        except BaseException:
            threading.Thread(target=process.wait, daemon=True, name="tree-proof-reaper").start()
        raise


# -- bwrap init witness and its gate ---------------------------------------------------

#: Block-fd writers held until the gate opens or no reader remains.  No finalizer, weak
#: reference or ``__del__`` reaches an entry: only :func:`_open_gate` and
#: :func:`_release_if_no_reader` remove and close one.
_HELD_GATES: dict[int, tuple[object, str]] = {}
_HELD_GATES_LOCK = threading.Lock()


class PinFailure(ValueError):
    """The bwrap init could not be authenticated at ``stage``.  ``kill_fd`` is a pidfd of a
    ppid-verified direct child (or ``-1``); the receiver owns and closes it."""

    def __init__(self, stage: str, reason: str, kill_fd: int = -1) -> None:
        super().__init__(reason)
        self.stage, self.kill_fd = stage, kill_fd


class WitnessUnavailable(ValueError):
    """A witnessed bwrap launch could not be established; the gate never opened."""

    def __init__(self, stage: str, reason: str, *, retained: bool) -> None:
        super().__init__(reason)
        self.stage, self.retained = stage, retained


def _hold_gate(block_w: int, reason: str) -> None:
    with _HELD_GATES_LOCK:
        _HELD_GATES[block_w] = (None, reason)


def _bind_gate(block_w: int, proc: object, reason: str) -> None:
    with _HELD_GATES_LOCK:
        if block_w in _HELD_GATES:
            _HELD_GATES[block_w] = (proc, reason)


def _drop_gate(block_w: int) -> None:
    with _HELD_GATES_LOCK:
        _HELD_GATES.pop(block_w, None)
    os.close(block_w)


def _open_gate(block_w: int) -> bool:
    """Release the blocked child.  ``False`` (and closed) when no reader remained."""
    try:
        os.write(block_w, b"1")
    except BrokenPipeError:
        _drop_gate(block_w)
        return False
    _drop_gate(block_w)
    return True


def _release_if_no_reader(block_w: int, deadline: float) -> bool:
    """Close ``block_w`` only once its pipe has no reader (``POLLERR`` on the write end)."""
    poller = select.poll()
    poller.register(block_w, 0)
    while True:
        events = poller.poll(int(min(SLICE_S, _remaining(deadline)) * 1000))
        mask = 0
        for _fd, revents in events:
            mask |= revents
        if mask & select.POLLERR:
            _drop_gate(block_w)
            return True
        if mask & select.POLLNVAL or _remaining(deadline) <= 0:
            return False


def _proc_stat(pid: int) -> tuple[str, int]:
    raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    fields = raw[raw.rindex(")") + 2:].split()
    return fields[0], int(fields[1])


def _nspid(pid: int) -> str:
    """The innermost namespace pid of ``pid`` (its last ``NSpid`` field)."""
    line = next(line for line in Path(f"/proc/{pid}/status").read_text(
        encoding="ascii").splitlines() if line.startswith("NSpid:"))
    return line.split()[-1]


def _read_info(info_read: int, deadline: float) -> dict:
    data = bytearray()
    while True:
        remaining = _remaining(deadline)
        if remaining <= 0:
            raise PinFailure("S2", "bwrap_info_deadline")
        if not select.select([info_read], [], [], min(SLICE_S, remaining))[0]:
            continue
        chunk = os.read(info_read, _INFO_CAP + 1)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > _INFO_CAP:
            raise PinFailure("S2", "bwrap_info_oversize")
    if not data:
        raise PinFailure("S2", "bwrap_info_empty")
    try:
        info = json.loads(bytes(data))
    except ValueError as exc:
        raise PinFailure("S2", "bwrap_info_malformed") from exc
    if not isinstance(info, dict):
        raise PinFailure("S2", "bwrap_info_malformed")
    return info


def pin_bwrap_init(leader_pid: int, info_read: int, *, deadline: float) -> int:
    """Authenticate the PID-namespace init a bwrap leader reports; return its pidfd.

    The leader is never polled or waited on here, so it stays an unreaped child and its
    pid names it throughout.  Raises :class:`PinFailure` naming the failed stage.
    """
    info = _read_info(info_read, deadline)
    child = info.get("child-pid")
    if type(child) is not int or child <= 0:
        raise PinFailure("S2", "bwrap_info_child_pid")
    pidfd_open = getattr(os, "pidfd_open", None)
    if pidfd_open is None:
        raise PinFailure("S3", "bwrap_init_pidfd")
    try:
        init_fd = pidfd_open(child)
    except OSError as exc:
        raise PinFailure("S3", "bwrap_init_pidfd") from exc
    try:
        _state, ppid = _proc_stat(child)
    except (OSError, ValueError, IndexError) as exc:
        os.close(init_fd)
        raise PinFailure("S3", "bwrap_init_stat") from exc
    if ppid != leader_pid:
        os.close(init_fd)
        raise PinFailure("S3", "bwrap_init_parent")
    try:
        held = os.stat(f"/proc/{child}/ns/pid")
        own = os.stat("/proc/self/ns/pid")
        if (held.st_dev, held.st_ino) == (own.st_dev, own.st_ino):
            raise PinFailure("S4", "bwrap_init_namespace", init_fd)
        if _nspid(child) != "1":
            raise PinFailure("S4", "bwrap_init_nspid", init_fd)
        if select.select([init_fd], [], [], 0)[0]:
            raise PinFailure("S4", "bwrap_init_exited", init_fd)
    except PinFailure:
        raise
    except (OSError, ValueError, IndexError, StopIteration) as exc:
        raise PinFailure("S4", "bwrap_init_unverifiable", init_fd) from exc
    return init_fd


def _teardown(proc: object | None, block_w: int, *, kill_fd: int, proof: TreeProof | None,
              stage: str) -> bool:
    """Kill every available target, then release the gate only once no reader remains.

    Returns ``False`` (gate, outer and proof retained) when ``POLLERR`` does not arrive
    within the teardown budget.  Nothing here closes ``block_w`` but the no-reader path.
    """
    deadline = time.monotonic() + TEARDOWN_BUDGET_S
    if proc is not None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.kill()
        except OSError:
            pass
    if kill_fd >= 0:
        try:
            signal.pidfd_send_signal(kill_fd, signal.SIGKILL)
        except OSError:
            pass
    try:
        released = _release_if_no_reader(block_w, deadline)
    finally:
        if kill_fd >= 0:
            os.close(kill_fd)
    if not released and proof is not None:
        proof.mark_unknown("gate_retained", time.monotonic() + SLICE_S)
    if proc is not None:
        try:
            proc.wait(timeout=_remaining(deadline))
        except Exception:
            pass
    return released


class BwrapLaunch:
    """One bwrap launch whose PID-namespace init is pinned before its command runs.

    The caller performs the one ``Popen`` itself, in its own frame, with
    ``--info-fd info_fd --block-fd block_fd`` among bwrap's options and
    :meth:`popen_kwargs`; then it calls :meth:`complete` (or :meth:`abandon` when the
    ``Popen`` raised).  The block writer is entered in :data:`_HELD_GATES` before the
    ``Popen`` and leaves it only through the gate write or the no-reader release.
    """

    def __init__(self) -> None:
        self.info_r, self.info_fd = os.pipe()
        try:
            self.block_fd, self.block_w = os.pipe()
        except BaseException:
            os.close(self.info_r)
            os.close(self.info_fd)
            raise
        _hold_gate(self.block_w, "S0")
        self.stage = "S1"
        self._child_ends_open = True

    def popen_kwargs(self, kwargs: dict) -> dict:
        launch = dict(kwargs)
        launch["pass_fds"] = tuple(sorted({*kwargs.get("pass_fds", ()), self.info_fd,
                                           self.block_fd}))
        return launch

    def _close_child_ends(self) -> None:
        if self._child_ends_open:
            self._child_ends_open = False
            os.close(self.info_fd)
            os.close(self.block_fd)

    def abandon(self) -> bool:
        """The ``Popen`` raised: no process exists, so the gate releases at once."""
        self._close_child_ends()
        try:
            return _teardown(None, self.block_w, kill_fd=-1, proof=None, stage="S1")
        finally:
            os.close(self.info_r)

    def complete(self, proc: object, *, timeout: float = PIN_TIMEOUT_S,
                 on_spawn: Callable[[object], None] | None = None,
                 before_gate: Callable[[object], None] | None = None) -> object:
        """Pin the init within ``timeout``, attach its proof, run ``before_gate``, then
        open the gate.

        Any failure tears the tree down by the teardown protocol and raises
        :class:`WitnessUnavailable`; a ``BaseException`` is re-raised as is.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        self._close_child_ends()
        block_w = self.block_w
        proof: TreeProof | None = None
        stage = "S2"
        kill_fd = -1
        try:
            _bind_gate(block_w, proc, stage)
            if on_spawn is not None:
                on_spawn(proc)
            try:
                init_fd = pin_bwrap_init(proc.pid, self.info_r, deadline=deadline)
            except PinFailure as failure:
                stage, kill_fd = failure.stage, failure.kill_fd
                raise
            stage = "S5"
            proof = TreeProof.bwrap_init(init_fd)
            attach(proc, proof)
            if before_gate is not None:
                before_gate(proc)
            stage = "S6"
            if not _open_gate(block_w):
                # EPIPE: no reader remains, so nothing can be released; refuse the launch.
                proof.mark_unknown("gate_failed", time.monotonic() + SLICE_S)
                _teardown_after_gate(proc)
                raise WitnessUnavailable(stage, "bwrap_gate_failed", retained=False)
            self.stage = "S7"
            return proc
        except WitnessUnavailable:
            raise
        except BaseException as exc:
            self.stage = stage
            if kill_fd < 0 and proof is not None:
                kill_fd = _dup_or_none(proof)
            released = _teardown(proc, block_w, kill_fd=kill_fd, proof=proof, stage=stage)
            if not isinstance(exc, Exception):
                raise
            error = WitnessUnavailable(stage, "bwrap_witness_unavailable", retained=not released)
            if not released:
                error.add_note(f"gate_retained:{stage}")
            raise error from exc
        finally:
            os.close(self.info_r)


def _dup_or_none(proof: TreeProof) -> int:
    deadline = time.monotonic() + SLICE_S
    if not proof._acquire(deadline):
        return -1
    try:
        return os.dup(proof.init_fd) if proof.init_fd >= 0 else -1
    except OSError:
        return -1
    finally:
        proof._lock.release()


def _teardown_after_gate(proc: object) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    proof = proof_of(proc)
    if proof is not None:
        proof.kill(time.monotonic() + TEARDOWN_BUDGET_S)


__all__ = [
    "PENDING", "INCOMPLETE", "UNKNOWN", "PROVEN", "CGROUP", "BWRAP_INIT", "TreeProof",
    "attach", "proof_of", "parse_events", "pin_bwrap_init", "BwrapLaunch",
    "PinFailure", "WitnessUnavailable", "run_bounded",
]
