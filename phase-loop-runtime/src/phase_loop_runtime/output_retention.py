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
import sys
import time

from .sandbox_retention import _process_start, _recorded_owner_alive

DEFAULT_DAYS = 30
REGISTRY = ".phase-loop-output-retention"
TOKEN = ".phase-loop-retention-token"
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
        try:
            registry_fd = _directory(REGISTRY, dir_fd=root_fd)
        except FileNotFoundError:
            if create:
                raise
            yield root_fd, None
            return
        lock_fd = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=registry_fd)
        st = os.fstat(lock_fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o022:
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
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_size > 4096 or st.st_nlink != 1 or st.st_mode & 0o022:
            raise ValueError("invalid retention record")
        try:
            record = json.loads(os.read(record_fd, 4097))
        except RecursionError as exc:
            raise ValueError("retention record is too deeply nested") from exc
    finally:
        os.close(record_fd)
    if not isinstance(record, dict) or set(record) != {"version", "device", "inode", "state", "completed_at", "owner", "token"}:
        raise ValueError("invalid retention record")
    if (type(record["version"]) is not int or record["version"] != 2 or record["state"] not in STATES
            or type(record["device"]) is not int or type(record["inode"]) is not int):
        raise ValueError("invalid retention record")
    token = record["token"]
    if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("invalid retention token")
    owner = record["owner"]
    if owner is not None and (not isinstance(owner, dict) or set(owner) != {"pid", "start"}
                              or type(owner["pid"]) is not int or owner["pid"] <= 0
                              or not isinstance(owner["start"], str)):
        raise ValueError("invalid retention owner")
    completed = record["completed_at"]
    if completed is not None and (type(completed) not in (float, int) or not 0 < completed < 1e12 or not math.isfinite(completed)):
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
        previous = None
        try:
            previous = _read(registry_fd, run)
        except FileNotFoundError:
            pass
        run_fd = _directory(run, dir_fd=root_fd)
        try:
            st = os.fstat(run_fd)
            if ".git" in os.listdir(run_fd):
                raise ValueError("Git checkouts are not retention outputs")
            if previous:
                if not _matches(run_fd, previous):
                    raise ValueError("run directory identity changed; retained record requires operator reconciliation")
                token = previous["token"]
            else:
                token = secrets.token_hex(32)
                fd = os.open(TOKEN, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=run_fd)
                with os.fdopen(fd, "w") as handle:
                    handle.write(token)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.fsync(run_fd)
        finally:
            os.close(run_fd)
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
        record = dict(version=2, device=st.st_dev, inode=st.st_ino, state=state, completed_at=completed, owner=owner, token=token)
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


def retention_days(days: int | None = None) -> int:
    if days is None:
        days = int(os.environ.get("PHASE_LOOP_OUTPUT_RETENTION_DAYS", str(DEFAULT_DAYS)))
    if type(days) is not int or days < 1:
        raise ValueError("retention days must be a positive integer")
    try:
        float(days * 86400)
    except OverflowError as exc:
        raise ValueError("retention days exceed the supported numeric range") from exc
    return days


def _matches(fd: int, record: dict) -> bool:
    st = os.fstat(fd)
    if (st.st_dev, st.st_ino) != (record["device"], record["inode"]):
        return False
    token_fd = os.open(TOKEN, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        st = os.fstat(token_fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1
                or st.st_mode & 0o022 or st.st_size != 64):
            return False
        return os.read(token_fd, 65) == record["token"].encode("ascii")
    finally:
        os.close(token_fd)


def _mount_id(fd: int) -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    with open(f"/proc/self/fdinfo/{fd}", encoding="ascii") as handle:
        for line in handle:
            if line.startswith("mnt_id:"):
                return line.split()[1]
    raise ValueError("cannot establish output filesystem mount")


def _check_tree(fd: int, parent_fd: int) -> None:
    # Finished outputs must stay quiescent throughout deletion. The private
    # quarantine isolates the top-level name from ordinary root-level renames.
    device = os.fstat(parent_fd).st_dev
    mount = _mount_id(parent_fd)
    def failed(error):
        raise error
    for _path, dirs, files, child_fd in os.fwalk(".", dir_fd=fd, follow_symlinks=False, onerror=failed):
        if os.fstat(child_fd).st_dev != device or _mount_id(child_fd) != mount:
            raise ValueError("mounted directories are not retention outputs")
        if ".git" in dirs or ".git" in files:
            raise ValueError("Git checkouts are not retention outputs")


def _retire(root_fd: int, registry_fd: int, run: str, record: dict) -> None:
    if not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError("platform lacks safe directory removal")
    quarantine = ".retiring-" + secrets.token_hex(16)
    os.mkdir(quarantine, 0o700, dir_fd=registry_fd)
    quarantine_fd = _directory(quarantine, dir_fd=registry_fd)
    try:
        # The durable receipt exists before either rename. Crashes or mismatches
        # leave a recoverable, non-eligible entry; never guess or auto-restore.
        receipt_fd = os.open("recovery.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=quarantine_fd)
        with os.fdopen(receipt_fd, "w") as handle:
            json.dump(dict(run=run, record=record), handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(quarantine_fd)
        os.fsync(registry_fd)
        os.rename(run + ".json", "record.json", src_dir_fd=registry_fd, dst_dir_fd=quarantine_fd)
        os.fsync(registry_fd)
        os.fsync(quarantine_fd)
        os.rename(run, "output", src_dir_fd=root_fd, dst_dir_fd=quarantine_fd)
        os.fsync(root_fd)
        os.fsync(quarantine_fd)
        acquired_fd = _directory("output", dir_fd=quarantine_fd)
        try:
            if not _matches(acquired_fd, record):
                raise ValueError("output changed before retirement")
            _check_tree(acquired_fd, quarantine_fd)
        finally:
            os.close(acquired_fd)
        shutil.rmtree("output", dir_fd=quarantine_fd)
        os.unlink("record.json", dir_fd=quarantine_fd)
        os.unlink("recovery.json", dir_fd=quarantine_fd)
    except (OSError, ValueError) as exc:
        raise ValueError(f"retirement incomplete; preserved {REGISTRY}/{quarantine}: {exc}") from exc
    finally:
        os.close(quarantine_fd)
    os.rmdir(quarantine, dir_fd=registry_fd)
    os.fsync(registry_fd)


def prune(root: Path, *, days: int | None = None, apply: bool = False, now: float | None = None) -> list[str]:
    """Return eligible immediate children, deleting only with apply=True.

    Per-entry failures are diagnosed and preserved; they do not starve siblings.
    """
    cutoff = (time.time() if now is None else now) - retention_days(days) * 86400
    result = []
    with _locked(root, create=False) as (root_fd, registry_fd):
        if registry_fd is None:
            return result
        for entry in sorted(os.listdir(registry_fd)):
            if not entry.endswith(".json") or entry.startswith("."):
                continue
            run = entry[:-5]
            try:
                _name(run)
                record = _read(registry_fd, run)
                try:
                    run_fd = _directory(run, dir_fd=root_fd)
                except FileNotFoundError:
                    if apply:
                        os.rename(entry, ".missing-" + secrets.token_hex(16), src_dir_fd=registry_fd, dst_dir_fd=registry_fd)
                        os.fsync(registry_fd)
                    continue
                try:
                    if (not _matches(run_fd, record) or record["owner"] is not None
                            or record["state"] not in ("sealed", "published")
                            or record["completed_at"] is None or record["completed_at"] > cutoff):
                        continue
                    _check_tree(run_fd, root_fd)
                finally:
                    os.close(run_fd)
                if apply:
                    _retire(root_fd, registry_fd, run, record)
                result.append(run)
            except (OSError, ValueError, TypeError) as exc:
                print(f"phase-loop output retention preserved {root / run}: {exc}", file=sys.stderr)
    return result


def _best_effort_sweep(root: Path, days: int) -> None:
    try:
        removed = prune(root, days=days, apply=True)
        if removed:
            print(f"phase-loop output retention: removed {len(removed)} completed run(s) from {root}", file=sys.stderr)
    except (OSError, ValueError, ImportError) as exc:
        print(f"phase-loop output retention skipped {root}: {exc}", file=sys.stderr)


def configured_sweep() -> None:
    """Best-effort startup sweep of explicitly configured output roots only."""
    import sys

    roots = os.environ.get("PHASE_LOOP_OUTPUT_ROOTS", "")
    if not roots:
        return
    try:
        days = retention_days()
    except ValueError as exc:
        print(f"phase-loop output retention skipped: {exc}", file=sys.stderr)
        return
    for root in roots.split(os.pathsep):
        if root:
            _best_effort_sweep(Path(root), days)


def run_managed(root: Path, run: str, command: list[str], *, finish_state: str, days: int | None = None) -> int:
    """Own a NEW output directory for one foreground producer; keep failures held."""
    _name(run)
    days = retention_days(days)
    if not command or finish_state not in ("sealed", "published"):
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
    _best_effort_sweep(root, days)
    return code if code >= 0 else 128 - code


def register_parser(subparsers):
    parser = subparsers.add_parser("output-retention", help="Manage completed evidence/review output retention")
    parser.add_argument("action", choices=("mark", "prune", "run"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--run")
    parser.add_argument("--state", choices=STATES)
    parser.add_argument("--days", type=int, default=None)
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
