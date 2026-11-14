"""Local, fixture-qualified patch return; the controller owns acceptance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import fcntl
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import threading
import time
from types import MappingProxyType
from typing import Literal

import rfc8785

from ... import output_retention as retention
from ... import sandbox_policy, seat_uid
from ... import run_status as journal
from ... import run_status_projection as projection
from ...supervised_launch import Refused, consume_admission, classify_workspace, trusted_bytes
from .base import (PROPOSAL_CAP_MAX, CaptureRequest, SpawnRefused,
                   run_bounded_capture, worker_child_environment, _descriptor_image)

CANCEL_WAIT_SECONDS = 10
PRODUCTION_LAUNCHER_COMMANDS = (tuple(seat_uid.trusted_module_argv(
    "phase_loop_runtime.supervised_worker_cli", "launch")[1:]),)


@dataclass(frozen=True)
class WorkerSettings:
    proposal_cap: int
    audit_entry_cap: int
    audit_byte_cap: int
    environment_allow: frozenset[str]
    retention_days: int | None
    reference_roots: tuple[Path, ...]


@dataclass(frozen=True)
class WorkerAttemptIdentity:
    assignment_digest: str
    envelope_digest: str
    launch_digest: str
    raw_digest: str
    run_id: str
    attempt_id: str
    target_unit_ids: tuple[str, ...]
    readonly_neighbor_unit_ids: tuple[str, ...]
    snapshot_ref: str
    caller_context_sha256: str


@dataclass(frozen=True)
class BaselineIdentity:
    path: str
    git_blob_sha1: str | None
    sha256: str | None


@dataclass(frozen=True)
class ProposalReturn:
    status: str
    proposal_bytes_digest: str | None
    byte_length: int
    baselines: tuple[BaselineIdentity, ...]
    locator: str | None


@dataclass(frozen=True)
class JournalAnchor:
    terminal_seq: int
    chain_head_sha256: str


@dataclass(frozen=True)
class WorkerResult:
    identity: WorkerAttemptIdentity | None
    state: str
    termination: journal.Termination | None
    refusal: str | None
    worker_invocations: int
    proposal: ProposalReturn | None
    evidence_envelope_digest: str | None
    journal_anchor: JournalAnchor | None
    journal_complete: bool


CancelOutcome = Literal["cancelled", "already_terminal", "cancel_pending", "unknown_attempt",
                        "owner_unverified", "owner_not_live"]


def default_state_root() -> Path:
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".local/state/agent-harness/supervised-worker"


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _plain(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _run(identity):
    return "a-" + sha256("\0".join((identity.assignment_digest, identity.run_id,
                                 identity.attempt_id)).encode()).hexdigest()[:32]


def _private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = _directory_fd(path)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("directory_mode")
    finally:
        os.close(fd)


def _directory_fd(path):
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute_path_required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _write(path, content):
    parent = _directory_fd(path.parent)
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            view = memoryview(content)
            while view:
                size = os.write(fd, view)
                if size <= 0:
                    raise OSError("short_write")
                view = view[size:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent)
    finally:
        os.close(parent)


def evidence_resolver(state_root: Path) -> projection.EvidenceResolver:
    def resolve(identity, ref):
        run = _run(identity)
        try:
            ledger = json.loads(trusted_bytes(state_root / "evidence-ledger" / (run + ".json")))
            if ledger.get(ref.kind) != ref.sha256:
                return "unknown"
            if (state_root / "evidence-ledger" / (run + ".retired")).exists():
                return "retention_dropped"
            root = state_root / "evidence"
            with retention._locked(root, create=False) as (root_fd, registry_fd):
                record = retention._read(registry_fd, run)
                fd = retention._directory(run, dir_fd=root_fd)
                try:
                    if record["state"] == "sealed" and retention._matches(fd, record):
                        return "present"
                finally:
                    os.close(fd)
        except (OSError, ValueError):
            pass
        return "unknown"
    return resolve


def _executable_digest(path):
    parent = _directory_fd(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                or info.st_mode & 0o022):
            raise ValueError("executable_identity")
        digest = sha256()
        while chunk := os.read(fd, 65536):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(fd)


def _settings(raw):
    config = json.loads(raw)
    cap = config.get("worker_proposal_cap", PROPOSAL_CAP_MAX)
    entries, size = config["worker_audit_entry_cap"], config["worker_audit_byte_cap"]
    days = config.get("worker_retention_days")
    allow = config.get("worker_environment_allow", [])
    if (any(type(x) is not int or x < 1 for x in (cap, entries, size))
            or cap > PROPOSAL_CAP_MAX or (days is not None and (type(days) is not int or days < 1))
            or type(allow) is not list or not all(type(x) is str for x in allow)):
        raise ValueError("worker_settings_invalid")
    roots = tuple(Path(x) for x in config["reference_roots"])
    if any(not x.is_absolute() or ".." in x.parts for x in roots):
        raise ValueError("worker_settings_invalid")
    return WorkerSettings(cap, entries, size, frozenset(allow), days, roots)


def _audit(inputs, settings):
    snapshots, baselines = [], {}
    count = size = 0

    def walk(fd, relative, scope):
        nonlocal count, size
        for name in sorted(os.listdir(fd)):
            path = relative + "/" + name if relative else name
            if path == ".git/objects" or path.startswith(".git/objects/"):
                continue
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            count += 1
            if count > settings.audit_entry_cap:
                raise ValueError("audit_entry_cap")
            if scope == "target" and ((path == ".git" and not stat.S_ISDIR(info.st_mode)) or
                    (stat.S_ISLNK(info.st_mode) and path.startswith((".git/HEAD", ".git/packed-refs", ".git/refs")))):
                raise ValueError("gitfile_escape")
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                kind, content = "symlink", os.readlink(name, dir_fd=fd)
                size += len(content.encode())
            elif stat.S_ISDIR(info.st_mode):
                kind, content = "dir", None
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    walk(child, path, scope)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                kind = "file"
                if scope == "target" and path == ".git":
                    raise ValueError("gitfile_escape")
                reader = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    opened = os.fstat(reader)
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError("audit_entry_changed")
                    h256, h1 = sha256(), sha1()
                    h1.update(b"blob " + str(info.st_size).encode() + b"\0")
                    while chunk := os.read(reader, 65536):
                        size += len(chunk)
                        if size > settings.audit_byte_cap:
                            raise ValueError("audit_byte_cap")
                        h256.update(chunk)
                        h1.update(chunk)
                    closed = os.fstat(reader)
                    if (closed.st_size, closed.st_mtime_ns, closed.st_ctime_ns) != (
                            opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
                        raise ValueError("audit_entry_changed")
                    content = h256.hexdigest()
                    if scope == "workspace":
                        baselines[path] = BaselineIdentity(path, h1.hexdigest(), content)
                finally:
                    os.close(reader)
            else:
                raise ValueError("audit_special_file")
            if size > settings.audit_byte_cap:
                raise ValueError("audit_byte_cap")
            snapshots.append((scope, path, kind, mode, info.st_size, content))
    for scope, path in (("workspace", inputs.workspace), ("target", inputs.target)):
        fd = _directory_fd(Path(path))
        try:
            walk(fd, "", scope)
        finally:
            os.close(fd)
    return sorted(snapshots), baselines


def _paths(proposal):
    paths, found = [], False
    def check(text, header=False):
        if text == "/dev/null" and not header:
            return
        if not (text.startswith("a/") or text.startswith("b/")):
            raise ValueError("proposal_path")
        text = text[2:]
        if (not text or "\0" in text or text.startswith("/") or len(text.encode()) > 4096
                or any(x in ("", ".", "..") or x.lower() == ".git" for x in text.split("/"))):
            raise ValueError("proposal_path")
        if header and text not in paths:
            paths.append(text)
    for line in proposal.decode("utf-8").splitlines():
        if line.startswith("diff --git "):
            a, b = line[len("diff --git "):].split(" ")
            if not a.startswith("a/") or not b.startswith("b/"):
                raise ValueError("proposal_header")
            check(a, True)
            check(b, True)
            found = True
        elif line.startswith(("--- ", "+++ ")):
            check(line[4:])
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            check("a/" + line.split(" ", 2)[2], True)
    if not found:
        raise ValueError("proposal_header_missing")
    return paths


class _Writer:
    def __init__(self, writer):
        self.writer, self.failed = writer, isinstance(writer, journal.JournalRefused)

    def call(self, name, *args, **kwargs):
        if self.failed:
            return None
        try:
            result = getattr(self.writer, name)(*args, **kwargs)
            if isinstance(result, journal.JournalRefused):
                if name != "event" or result.code != "event_cap_reached":
                    self.failed = True
                return None
            return result
        except BaseException:
            self.failed = True
            return None

    def close(self):
        if not isinstance(self.writer, journal.JournalRefused):
            try:
                self.writer.close()
            except BaseException:
                self.failed = True


def run_patch_return(prepared, *, config_bytes: bytes, state_root: Path,
                     cancel: threading.Event | None = None) -> WorkerResult:
    inputs = consume_admission(prepared)
    identity = None
    def refused(reason, complete=True, anchor=None):
        if getattr(prepared, "_capture", None) is not None:
            prepared._capture.close()
        return WorkerResult(identity, "refused", None, reason, 0, None, None, anchor, complete)
    if isinstance(inputs, Refused):
        return refused(inputs.reason)
    if sha256(config_bytes).hexdigest() != inputs.config_digest:
        return refused("config_changed")
    try:
        settings = _settings(config_bytes)
    except (ValueError, KeyError, TypeError):
        return refused("worker_settings_invalid")
    try:
        if prepared.attempt_binding is not None:
            from ...supervised_envelope_v2 import canonicalize_v2
            context_payload = canonicalize_v2(prepared.view.envelope["caller_context"])
            context_digest = sha256(context_payload).hexdigest()
            envelope = prepared.view.envelope
            attempt, units = prepared.attempt_binding, envelope["units"]
            identity = WorkerAttemptIdentity(attempt.assignment_digest, prepared.view.envelope_digest,
                prepared.view.launch_digest, prepared.view.raw_digest, attempt.run_id, attempt.attempt_id,
                tuple(units["target_unit_ids"]), tuple(units["readonly_neighbor_unit_ids"]), units["snapshot_ref"], context_digest)
        else:
            context_digest = sha256(rfc8785.dumps(_plain(prepared.view.envelope["caller_context"]))).hexdigest()
            envelope = prepared.view.envelope
            identity = WorkerAttemptIdentity(envelope["assignment_digest"], prepared.view.envelope_digest,
                prepared.view.launch_digest, prepared.view.raw_digest, envelope["run_id"], envelope["attempt_id"],
                tuple(envelope["target_unit_ids"]), tuple(envelope["readonly_neighbor_unit_ids"]),
                envelope["snapshot_reference"], context_digest)
    except (ValueError, TypeError):
        return refused("caller_context_unencodable")
    excluded = (Path(inputs.workspace), Path(inputs.target), *settings.reference_roots)
    try:
        resolved = state_root.resolve()
        if any(resolved == path.resolve() or path.resolve() in resolved.parents for path in excluded):
            return refused("state_root_unsafe")
        _private_directory(state_root)
    except (OSError, ValueError):
        return refused("state_root_unsafe")
    if prepared.attempt_binding is not None:
        from ...supervised_echo import EchoRefused, write_echo
        published = write_echo(state_root, context_payload)
        if isinstance(published, EchoRefused) or published != context_digest:
            return refused("echo_unavailable")
    root = journal.open_journal_root(state_root / "journal", create=True, excluded=excluded)
    if isinstance(root, journal.JournalRefused):
        return refused(root.code)
    jid = journal.AttemptIdentity(identity.assignment_digest, identity.envelope_digest,
                                  identity.run_id, identity.attempt_id)
    try:
        reservation = journal.reserve_attempt(root, jid,
            units=journal.Units(identity.target_unit_ids, identity.readonly_neighbor_unit_ids, identity.snapshot_ref),
            launch_digest=identity.launch_digest, caller_context_sha256=context_digest)
    except BaseException:
        return refused("journal_unavailable", False)
    if isinstance(reservation, journal.JournalRefused):
        return refused(reservation.code)
    try:
        writer = _Writer(journal.open_writer(root, reservation))
    except BaseException:
        return refused("journal_unavailable", False)
    writer.call("state", "queued", worker_invocations=0)
    cancel = cancel if cancel is not None else threading.Event()
    lock_fd = None
    previous = None
    def healthy_refusal(reason):
        head = writer.call("terminal", "refused", worker_invocations=0, termination=None,
                           refusal=journal.TerminalRefusal(reason, None, inputs.tier), result_binding=None)
        anchor = JournalAnchor(head.last_seq, head.segment_sha256) if head else None
        return refused("journal_unavailable" if writer.failed else reason, not writer.failed, anchor)
    try:
        if writer.failed:
            return refused("journal_unavailable", False)
        try:
            _private_directory(state_root / "launchers")
            record_path = state_root / "launchers" / (identity.attempt_id + ".json")
            cmdline = Path("/proc/self/cmdline").read_bytes()
            exe = str(Path("/proc/self/exe").resolve())
            record = dict(run_id=identity.run_id, attempt_id=identity.attempt_id,
                          assignment_digest=identity.assignment_digest, pid=os.getpid(),
                          process_start_time=journal.process_start_identity(os.getpid()), exe_realpath=exe,
                          exe_sha256=sha256(Path(exe).read_bytes()).hexdigest(),
                          cmdline_sha256=sha256(cmdline).hexdigest(), nonce=reservation.writer.writer_instance_id)
            if threading.current_thread() is threading.main_thread():
                previous = signal.signal(signal.SIGTERM, lambda *_args: cancel.set())
            _write(record_path, _bytes(record))
            lock_fd = os.open(record_path, os.O_RDWR | os.O_NOFOLLOW)
            fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError):
            return healthy_refusal("launcher_record_unavailable")
        try:
            before, baselines = _audit(inputs, settings)
        except (OSError, ValueError, RecursionError):
            return healthy_refusal("audit_error")

        def before_spawn():
            if prepared.attempt_binding is not None:
                from ...supervised_capture_v2 import recheck_launch_v2
                check = recheck_launch_v2(prepared._capture, context=prepared._capture.context)
                if isinstance(check, Refused):
                    return SpawnRefused(check.reason)
            if cancel.is_set():
                return SpawnRefused("cancelled_before_start")
            try:
                observed = classify_workspace(Path(inputs.workspace), Path(inputs.target), inputs.tier)
            except Exception:
                return SpawnRefused("workspace_changed")
            for actual, expected, reason in zip(observed,
                    (inputs.workspace_class, inputs.root_device, inputs.root_inode),
                    ("workspace_changed", "device_changed", "inode_changed")):
                if actual != expected:
                    return SpawnRefused(reason)
            for executable, reason in ((inputs.executable, "executable_changed"),
                                        *((item, "wrapper_changed") for item in inputs.wrappers)):
                try:
                    if _executable_digest(Path(executable.path)) != executable.digest:
                        return SpawnRefused(reason)
                except (OSError, ValueError):
                    return SpawnRefused(reason)
            writer.call("state", "running", worker_invocations=1)
            return SpawnRefused("journal_unavailable") if writer.failed else None

        class CancelObserver:
            reported = False
            def is_set(self):
                if cancel.is_set():
                    if not self.reported:
                        self.reported = True
                        writer.call("state", "cancelling", worker_invocations=1)
                        writer.call("event", "cancellation requested")
                    return True
                return False
        if prepared.attempt_binding is not None:
            exec_binding = "descriptor"
            environment = dict(prepared._capture.spec.non_secret_environment)
            captured = run_bounded_capture(CaptureRequest(identity.attempt_id, inputs.argv,
                Path(inputs.workspace), inputs.timeout,
                inputs.instruction if prepared._capture.spec.stdin == "input" else b"", settings.proposal_cap,
                environment), before_spawn=before_spawn, cancel=CancelObserver(), spawn_capability=inputs.spawn_capability)
        else:
            image = _descriptor_image(inputs.argv[0])
            exec_binding = "descriptor" if image is not None else "path_recheck"
            if image is not None:
                os.close(image)
            try:
                environment = worker_child_environment(settings.environment_allow)
            except sandbox_policy.SandboxSpaceError:
                return healthy_refusal("scratch_unavailable")
            captured = run_bounded_capture(CaptureRequest(identity.attempt_id, inputs.argv,
                Path(inputs.workspace), inputs.timeout, inputs.instruction, settings.proposal_cap,
                environment), before_spawn=before_spawn, cancel=CancelObserver())
        if isinstance(captured, SpawnRefused):
            if writer.failed:
                return refused("journal_unavailable", False)
            return healthy_refusal(captured.reason)
        termination = journal.Termination(captured.termination, captured.signal, captured.terminated_by)
        audit_error, unexplained, writes = False, 0, 0
        after = []
        try:
            after, _ = _audit(inputs, settings)
            old = {(row[0], row[1]): row for row in before}
            new = {(row[0], row[1]): row for row in after}
            for key in old.keys() | new.keys():
                if old.get(key) != new.get(key):
                    if key[0] == "target" or inputs.tier == "provider_readonly_patch_return_audit":
                        unexplained += 1
                    else:
                        writes += 1
        except (OSError, ValueError, RecursionError):
            audit_error = True
        data = captured.proposal or b""
        paths = []
        if termination.reason != "completed" or captured.exit_code != 0 or not captured.streams_complete:
            status = "withheld_incomplete"
        elif captured.proposal_overflow:
            status = "withheld_oversized"
        elif audit_error:
            status = "withheld_audit_error"
        elif unexplained:
            status = "withheld_unexplained_change"
        elif not data:
            status = "absent"
        else:
            try:
                paths = _paths(data)
                status = "returned"
            except ValueError:
                status = "withheld_malformed"
        run = _run(identity)
        proposal = ProposalReturn(status, sha256(data).hexdigest() if status == "returned" else None,
            captured.stdout.byte_count, tuple(baselines.get(path, BaselineIdentity(path, None, None)) for path in paths),
            run + "/proposal.bin" if status == "returned" else None)
        digest = None
        evidence_root = state_root / "evidence"
        run_root = evidence_root / run
        refs = {}
        try:
            _private_directory(evidence_root)
            _private_directory(run_root)
            retention.mark(evidence_root, run, "active", owner_pid=os.getpid())
            record = dict(local_record="agent-harness.supervised-worker.evidence", version=0, fixture_labelled=True,
                identity=asdict(identity), argv=inputs.argv, instruction_digest=inputs.instruction_digest,
                executable=dict(realpath=inputs.executable.path, sha256=inputs.executable.digest,
                    version=json.loads(config_bytes).get("qualified_version") if inputs.qualification_digest else None),
                version_source="qualified" if inputs.qualification_digest else "unqualified",
                wrappers=[dict(realpath=x.path, sha256=x.digest) for x in inputs.wrappers],
                config_digest=inputs.config_digest, template_digest=inputs.template_digest,
                qualification_digest=inputs.qualification_digest, workspace_kind=inputs.workspace_class,
                device=inputs.root_device, inode=inputs.root_inode, tier=inputs.tier,
                environment_names=sorted(environment), exec_binding=exec_binding,
                termination=asdict(termination), exit_code=captured.exit_code, worker_invocations=captured.spawn_count,
                stdout=asdict(captured.stdout), stderr=asdict(captured.stderr), streams_complete=captured.streams_complete,
                duration_ns=captured.duration_ns, stdin_delivered=captured.stdin_delivered, proposal=asdict(proposal),
                audit=dict(status="error" if audit_error else "complete", before_sha256=sha256(_bytes(before)).hexdigest(),
                    after_sha256=sha256(_bytes(after)).hexdigest(), workspace_writes_detected=writes, unexplained_count=unexplained))
            evidence = _bytes(record)
            if status == "returned":
                _write(run_root / "proposal.bin", data)
            _write(run_root / "evidence.json", evidence)
            retention.mark(evidence_root, run, "sealed")
            refs["evidence_envelope"] = sha256(evidence).hexdigest()
            if status == "returned":
                refs["proposal_bytes"] = proposal.proposal_bytes_digest
            _private_directory(state_root / "evidence-ledger")
            _write(state_root / "evidence-ledger" / (run + ".json"), _bytes(refs))
            digest = refs["evidence_envelope"]
        except (OSError, ValueError):
            try:
                (run_root / "proposal.bin").unlink(missing_ok=True)
            except OSError:
                pass
            proposal = ProposalReturn("withheld_evidence_error", None, captured.stdout.byte_count, (), None)
        binding = None
        if digest:
            writer.call("event", "attempt evidence bound", refs=(journal.make_ref("evidence_envelope", evidence, None),))
            if proposal.status == "returned":
                writer.call("event", "proposal bytes captured", refs=(journal.make_ref("proposal_bytes", data, None),))
            binding = journal.ResultBinding(identity.envelope_digest, identity.run_id, identity.attempt_id,
                                            proposal.proposal_bytes_digest, digest)
        if proposal.status.startswith("withheld_"):
            phrase = ("workspace audit failed; proposal withheld" if proposal.status in
                      ("withheld_audit_error", "withheld_unexplained_change") else "proposal withheld")
            writer.call("event", phrase)
        head = writer.call("terminal", "finished", worker_invocations=captured.spawn_count,
                           termination=termination, refusal=None, result_binding=binding)
        anchor = JournalAnchor(head.last_seq, head.segment_sha256) if head else None
        writer.close()
        try:
            for retired in retention.prune(evidence_root, days=settings.retention_days, apply=True):
                try:
                    _write(state_root / "evidence-ledger" / (retired + ".retired"), b"")
                except (OSError, ValueError):
                    continue
        except (OSError, ValueError):
            pass
        return WorkerResult(identity, "finished", termination, None, captured.spawn_count,
                            proposal, digest, anchor, not writer.failed)
    finally:
        writer.close()
        if lock_fd is not None:
            os.close(lock_fd)
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def cancel_attempt(*, state_root: Path, run_id: str | None = None, attempt_id: str | None = None,
                   wait_seconds: float = CANCEL_WAIT_SECONDS,
                   launcher_commands: tuple[tuple[str, ...], ...] = PRODUCTION_LAUNCHER_COMMANDS) -> CancelOutcome:
    if not 0 < wait_seconds <= CANCEL_WAIT_SECONDS:
        raise ValueError("cancel_wait_invalid")
    if (run_id is None) == (attempt_id is None):
        raise ValueError("cancel_target_invalid")
    root = journal.open_journal_root(state_root / "journal", create=False)
    if isinstance(root, journal.JournalRefused):
        return "unknown_attempt"
    if run_id is not None:
        ids = journal.resolve_run(root, run_id)
        if isinstance(ids, journal.JournalRefused) or not ids:
            return "unknown_attempt"
        attempt_id = ids[-1]
    read = journal.read_attempt(root, attempt_id)
    if read.identity is None:
        return "unknown_attempt"
    status = projection.attempt_status(root, attempt_id)
    if status.state in ("finished", "refused"):
        return "already_terminal"
    if status.display == "stale_unknown":
        return "owner_not_live"
    fd = pidfd = None
    try:
        parent = _directory_fd(state_root / "launchers")
        try:
            fd = os.open(attempt_id + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384):
            return "owner_unverified"
        record = json.loads(os.read(fd, 16385))
        pid = record["pid"]
        if (type(pid) is not int or pid < 1 or read.writer is None
                or (read.writer.owner_pid, read.writer.process_start_time, read.writer.writer_instance_id)
                != (pid, record["process_start_time"], record["nonce"])
                or record["attempt_id"] != attempt_id or record["run_id"] != read.identity.run_id
                or record["assignment_digest"] != read.identity.assignment_digest):
            return "owner_unverified"
        pidfd = os.pidfd_open(pid)
        if journal.process_start_identity(pid) != record["process_start_time"]:
            return "owner_unverified"
        exe = str(Path(f"/proc/{pid}/exe").resolve())
        if exe != record["exe_realpath"] or exe != str(Path("/proc/self/exe").resolve()):
            return "owner_unverified"
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        if sha256(cmdline).hexdigest() != record["cmdline_sha256"]:
            return "owner_unverified"
        args = tuple(x.decode() for x in cmdline.rstrip(b"\0").split(b"\0"))
        if not any(args[1:1 + len(command)] == command for command in launcher_commands):
            return "owner_unverified"
        import struct
        request = struct.pack("hhqqi", fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0)
        lock = fcntl.fcntl(fd, fcntl.F_GETLK, request)
        lock_type, _, _, _, owner = struct.unpack("hhqqi", lock)
        if lock_type == fcntl.F_UNLCK or owner != pid:
            return "owner_unverified"
        signal.pidfd_send_signal(pidfd, signal.SIGTERM)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "owner_unverified"
    finally:
        if fd is not None:
            os.close(fd)
        if pidfd is not None:
            os.close(pidfd)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        status = projection.attempt_status(root, attempt_id)
        if status.state in ("finished", "refused"):
            if ((status.termination and status.termination.reason == "cancelled")
                    or (status.refusal and status.refusal.reason == "cancelled_before_start")):
                return "cancelled"
            return "already_terminal"
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    return "cancel_pending"
