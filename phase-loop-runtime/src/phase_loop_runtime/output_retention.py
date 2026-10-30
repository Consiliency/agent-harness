"""Explicit lifecycle and age retention for dedicated evidence/review run folders.

Completion is an operator/producer declaration, not an evidence acceptance vote.
Unregistered directories never become eligible based on their names or mtimes.
"""
from __future__ import annotations

from contextlib import contextmanager
import argparse
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import stat
import time

from .sandbox_retention import _process_start, _recorded_owner_alive

DEFAULT_DAYS = 30
REGISTRY = ".phase-loop-output-retention"
STATES = ("active", "held", "sealed", "published")


def _name(value: str) -> str:
    if not value or value.startswith(".") or Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError("run must be a non-hidden immediate child name")
    return value


def _directory(path, *, dir_fd=None):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    st = os.fstat(fd)
    if st.st_uid != os.getuid() or st.st_mode & 0o022:
        os.close(fd)
        raise ValueError("retention directories must be owned by this account and not group/world writable")
    return fd


@contextmanager
def _locked(root: Path, *, create: bool):
    # POSIX only: refuse rather than silently proceeding without serialization.
    import fcntl

    root_fd = _directory(root)
    registry_fd = lock_fd = None
    try:
        if create:
            try:
                os.mkdir(REGISTRY, 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        registry_fd = _directory(REGISTRY, dir_fd=root_fd)
        lock_fd = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=registry_fd)
        st = os.fstat(lock_fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1:
            raise ValueError("invalid retention lock")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield root_fd, registry_fd
    finally:
        for fd in (lock_fd, registry_fd, root_fd):
            if fd is not None:
                os.close(fd)


def _read(fd: int, name: str):
    record_fd = os.open(name + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        st = os.fstat(record_fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_size > 4096:
            raise ValueError("invalid retention record")
        record = json.loads(os.read(record_fd, 4097))
    finally:
        os.close(record_fd)
    if not isinstance(record, dict) or set(record) != {"version", "device", "inode", "state", "completed_at", "owner"}:
        raise ValueError("invalid retention record")
    if (record["version"] != 1 or record["state"] not in STATES
            or type(record["device"]) is not int or type(record["inode"]) is not int):
        raise ValueError("invalid retention record")
    owner = record["owner"]
    if owner is not None and (not isinstance(owner, dict) or set(owner) != {"pid", "start"}
                              or type(owner["pid"]) is not int or owner["pid"] <= 0
                              or not isinstance(owner["start"], str)):
        raise ValueError("invalid retention owner")
    completed = record["completed_at"]
    if completed is not None and (type(completed) not in (float, int) or not math.isfinite(completed) or completed <= 0):
        raise ValueError("invalid completion time")
    return record


def mark(root: Path, run: str, state: str, *, owner_pid: int | None = None) -> dict:
    """Declare a dedicated run active, held, or finished; never infer completion.

    Call active BEFORE resuming a finished run. Sealed/published must only be set
    once all writers are done and retention is permitted by the evidence owner.
    """
    _name(run)
    if state not in STATES:
        raise ValueError("invalid retention state")
    with _locked(root, create=True) as (root_fd, registry_fd):
        run_fd = _directory(run, dir_fd=root_fd)
        try:
            st = os.fstat(run_fd)
        finally:
            os.close(run_fd)
        previous = None
        try:
            previous = _read(registry_fd, run)
        except FileNotFoundError:
            pass
        identity = (st.st_dev, st.st_ino)
        if previous and (previous["device"], previous["inode"]) != identity:
            raise ValueError("run directory identity changed; retained record requires operator reconciliation")
        owner = (previous or {}).get("owner")
        if owner and owner["pid"] != os.getpid() and _recorded_owner_alive(
                f"pid={owner['pid']} start={owner['start']}"):
            raise ValueError("managed producer is still active")
        completed = None
        if state in ("sealed", "published"):
            completed = (previous or {}).get("completed_at") or time.time()
        elif state == "held":
            completed = (previous or {}).get("completed_at")
        owner = None
        if owner_pid is not None:
            if state != "active" or owner_pid != os.getpid():
                raise ValueError("only the active producer may record its owner")
            owner = dict(pid=owner_pid, start=_process_start(owner_pid) or "")
        record = dict(version=1, device=st.st_dev, inode=st.st_ino, state=state, completed_at=completed, owner=owner)
        temporary = secrets.token_hex(16) + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=registry_fd)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(record, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, run + ".json", src_dir_fd=registry_fd, dst_dir_fd=registry_fd)
            os.fsync(registry_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=registry_fd)
            except FileNotFoundError:
                pass
        return record


def prune(root: Path, *, days: int = DEFAULT_DAYS, apply: bool = False, now: float | None = None) -> list[str]:
    """Return eligible immediate children, deleting only with apply=True."""
    if type(days) is not int or days < 1:
        raise ValueError("retention days must be a positive integer")
    cutoff = (time.time() if now is None else now) - days * 86400
    result = []
    try:
        with _locked(root, create=False) as (root_fd, registry_fd):
            for entry in sorted(os.listdir(registry_fd)):
                if not entry.endswith(".json"):
                    continue
                run = entry[:-5]
                try:
                    _name(run)
                    record = _read(registry_fd, run)
                    st = os.stat(run, dir_fd=root_fd, follow_symlinks=False)
                except (OSError, ValueError, TypeError):
                    continue
                if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid()
                        or (st.st_dev, st.st_ino) != (record["device"], record["inode"])
                        or record["owner"] is not None
                        or record["state"] not in ("sealed", "published")
                        or record["completed_at"] is None or record["completed_at"] > cutoff):
                    continue
                if apply:
                    if not shutil.rmtree.avoids_symlink_attacks:
                        raise ValueError("platform lacks safe directory removal")
                    shutil.rmtree(run, dir_fd=root_fd)
                    os.unlink(entry, dir_fd=registry_fd)
                result.append(run)
    except FileNotFoundError:
        # No registry means nothing has opted in, including a nonexistent root.
        pass
    return result


def configured_sweep() -> None:
    """Best-effort startup sweep of explicitly configured output roots only."""
    import sys

    roots = os.environ.get("PHASE_LOOP_OUTPUT_ROOTS", "")
    if not roots:
        return
    try:
        days = int(os.environ.get("PHASE_LOOP_OUTPUT_RETENTION_DAYS", str(DEFAULT_DAYS)))
        if days < 1:
            raise ValueError("retention days must be positive")
    except ValueError as exc:
        print(f"phase-loop output retention skipped: {exc}", file=sys.stderr)
        return
    for root in roots.split(os.pathsep):
        if not root:
            continue
        try:
            removed = prune(Path(root), days=days, apply=True)
            if removed:
                print(f"phase-loop output retention: removed {len(removed)} completed run(s) from {root}", file=sys.stderr)
        except (OSError, ValueError, ImportError) as exc:
            print(f"phase-loop output retention skipped {root}: {exc}", file=sys.stderr)


def run_managed(root: Path, run: str, command: list[str], *, finish_state: str, days: int = DEFAULT_DAYS) -> int:
    """Own a NEW output directory for one foreground producer; keep failures held."""
    _name(run)
    if not command or finish_state not in ("sealed", "published") or days < 1:
        raise ValueError("run requires a command, completion state and positive retention days")
    # Exclusive creation prevents commandeering a prior or concurrent run.
    with _locked(root, create=True) as (root_fd, _registry_fd):
        os.mkdir(run, 0o700, dir_fd=root_fd)
    mark(root, run, "active", owner_pid=os.getpid())
    try:
        env = dict(os.environ, PHASE_LOOP_OUTPUT_DIR=str(root.absolute() / run))
        from .panel_invoker import run_provider

        # Explicit operator producer, using the shared owner and scratch policy.
        # This wrapper does not confer review-seat qualification or isolation.
        code = run_provider(command, executor=True, env=env).returncode
    except BaseException:
        mark(root, run, "held")
        raise
    mark(root, run, finish_state if code == 0 else "held")
    prune(root, days=days, apply=True)
    return code if code >= 0 else 128 - code


def register_parser(subparsers):
    parser = subparsers.add_parser("output-retention", help="Manage completed evidence/review output retention")
    parser.add_argument("action", choices=("mark", "prune", "run"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--run")
    parser.add_argument("--state", choices=STATES)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--finish-state", choices=("sealed", "published"))
    parser.add_argument("--apply", action="store_true", help="Delete eligible outputs; otherwise preview")

    parser.add_argument("--exec", dest="producer", nargs=argparse.REMAINDER, help="Foreground producer command (run only; last option)")


def cli_main(args) -> int:
    import sys

    try:
        if args.action == "run":
            if not args.run or not args.finish_state or not args.producer or args.apply or args.state:
                raise ValueError("run requires --run, --finish-state and --exec command")
            return run_managed(args.root, args.run, args.producer, finish_state=args.finish_state, days=args.days)
        if args.producer or args.finish_state:
            raise ValueError("--exec and --finish-state require run")
        if args.action == "mark":
            if not args.run or not args.state or args.apply:
                raise ValueError("mark requires --run and --state; --apply is only for prune")
            result = mark(args.root, args.run, args.state)
        else:
            if args.run or args.state:
                raise ValueError("prune does not accept --run or --state")
            result = {"removed" if args.apply else "eligible": prune(args.root, days=args.days, apply=args.apply)}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print(f"phase-loop output-retention: {exc}", file=sys.stderr)
        return 1
