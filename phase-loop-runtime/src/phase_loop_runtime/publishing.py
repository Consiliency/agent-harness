"""The bounded worktree-to-broker publication transaction.

The transaction deliberately separates making a commit object from moving a
branch reference.  The former is checkpointed before the latter, which makes a
restart an exact ref-CAS retry rather than a second commit attempt.
"""
from __future__ import annotations

import ast
import base64
import contextlib
import hashlib
import json
import os
import subprocess
import threading
import warnings
from importlib.metadata import version
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .convergence.broker.verbs import BrokerClient, PublicationRecoveryRequired
from .convergence.contracts import AdmissionRequest, BrokerRequest, BrokerVerb, PreAdmissionEnvelope
from .convergence.provider_contracts import TerminalOutcomeState
from .convergence.broker.live import canonical_repository_identity
from .git_topology import collect_git_topology
from .credential_redaction import redact_text, redaction_identity


PROTECTED_BRANCHES: frozenset[str] = frozenset({"main", "master", "develop", "release"})
_TRANSACTION_DOMAIN = b"FABPUB-PUBLISH-TRANSACTION-v1\0"
_TRAILER_PREFIX = b"\n\nFABPUB-Intent-ID: "
FABPUB_CRASH_ANCHORS = (
    "after_commit_object_checkpoint_before_ref_cas",
    "after_git_commit_success_before_committed_checkpoint",
    "after_committed_checkpoint_before_broker_execute",
    "after_broker_intent_before_adapter_started",
)
#: agent-harness#1591: broker seams after the provider returned.  Kept apart
#: from the frozen four above, which the train runner's resume contract pins.
FABPUB_POST_PROVIDER_CRASH_ANCHORS = (
    "after_provider_return_before_terminal",
    "after_post_ambiguity_observation",
)
_CRASH_STATE = threading.local()
_FORBIDDEN_IDENTITY_FIELDS = frozenset(
    {
        "transaction_id",
        "final_commit_message_sha256",
        "expected_commit_oid",
        "committed_head_sha",
        "final_commit_object_sha256",
    }
)


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, payload: dict, *, mode: int = 0o666) -> None:
    """Replace ``path`` atomically.  The temporary file is created exclusively and
    no-follow under a unique name, so neither a stale nor a planted temporary is
    ever written through.  ``mode`` passes through the umask; the default keeps
    the historical permissions of every existing writer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(
        str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    descriptor = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_bytes_nofollow(path: Path) -> bytes | None:
    """``None`` when ``path`` is absent; its bytes when it is a regular file.

    A symlink, a non-regular file (a FIFO included, without blocking), or bytes
    that cannot be read refuse with ``PublishTransactionConflict``
    (agent-harness#1296 recovery records).
    """
    try:
        # O_NONBLOCK: a FIFO planted at ``path`` must not block the open (and the
        # transaction lock with it); the type check below then refuses it.
        descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise PublishTransactionConflict(f"{path} is not a regular file: {error}") from error
    import stat

    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise PublishTransactionConflict(f"{path} is not a regular file")
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read()


def _read_json_nofollow(path: Path) -> dict | None:
    raw = _read_bytes_nofollow(path)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError as error:
        raise PublishTransactionConflict(f"{path} is not JSON: {error}") from error
    if not isinstance(value, dict):
        raise PublishTransactionConflict(f"{path} is not a JSON object")
    return value


def _git(repo: Path, *args: str, input: bytes | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input,
        capture_output=True,
        env=env,
        timeout=60,
    )


def _git_output(repo: Path, *args: str) -> str | None:
    completed = _git(repo, *args)
    if completed.returncode:
        return None
    return completed.stdout.decode("utf-8", "surrogateescape").strip() or None


def _git_bytes(repo: Path, *args: str) -> bytes | None:
    completed = _git(repo, *args)
    return completed.stdout if not completed.returncode else None


class PublishTransactionState:
    PREPARED = "PREPARED"
    COMMIT_OBJECT_DURABLE = "COMMIT_OBJECT_DURABLE"
    COMMITTED_HEAD_RESOLVED = "COMMITTED_HEAD_RESOLVED"
    ADMISSION_DURABLE = "ADMISSION_DURABLE"
    BROKER_INTENT_DURABLE = "BROKER_INTENT_DURABLE"
    ADAPTER_STARTED = "ADAPTER_STARTED"
    TERMINAL_SEALED = "TERMINAL_SEALED"
    ABANDONED = "ABANDONED"
    CONFLICTED = "CONFLICTED"
    ORDERED = (
        PREPARED,
        COMMIT_OBJECT_DURABLE,
        COMMITTED_HEAD_RESOLVED,
        ADMISSION_DURABLE,
        BROKER_INTENT_DURABLE,
        ADAPTER_STARTED,
        TERMINAL_SEALED,
    )


@dataclass(frozen=True)
class PublishPreTrailerIntent:
    pre_trailer_intent_bytes: bytes
    pre_trailer_intent_sha256: str
    transaction_id: str
    original_commit_message_sha256: str
    final_commit_message_bytes: bytes
    final_commit_message_sha256: str


@dataclass(frozen=True)
class CommitConstructionInputs:
    parent_head_sha: str
    tree_oid: str
    git_object_format: str
    author_name: str
    author_email: str
    author_date: str
    committer_name: str
    committer_email: str
    committer_date: str
    encoding_header: str | None = None
    extra_headers: tuple[str, ...] = ()
    signing_mode: str = "disabled"
    signing_key: str | None = None
    signing_format: str | None = None
    signer_input_policy: str = "none"
    constructor_argv: tuple[str, ...] = ("git", "commit-tree")
    constructor_config: tuple[str, ...] = ("core.abbrev=40", "commit.gpgsign=false")
    constructor_environment: tuple[str, ...] = (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_COMMITTER_DATE",
    )


@dataclass(frozen=True)
class PublishIntent:
    transaction_id: str
    pre_trailer_intent_sha256: str
    original_commit_message_sha256: str
    final_commit_message_sha256: str


@dataclass(frozen=True)
class PublishCheckpoint:
    state: str
    transaction_id: str
    checkpoint_path: Path


@dataclass(frozen=True)
class PublishResumeCandidate:
    state: str
    transaction: "PublishTransaction | None" = None

    def __getattr__(self, name: str):
        transaction = object.__getattribute__(self, "transaction")
        if transaction is None:
            raise AttributeError(name)
        return getattr(transaction, name)


class PublishCrashInjected(RuntimeError):
    pass


class PublishTransactionConflict(RuntimeError):
    pass


class UnadmittedPrebuiltConflict(PublishTransactionConflict):
    provider_call_made = False


class RecoveryRecordConflict(PublishTransactionConflict):
    """An existing recovery record refuses this re-admission (agent-harness#1576).

    ``record_path`` names the ``<transaction_id>.recovery.<generation>.json``
    file, so the human handoff can point an operator at what is stuck.
    """

    def __init__(self, message: str, *, record_path: Path) -> None:
        super().__init__(message)
        self.record_path = Path(record_path)


# agent-harness#1310 fields of a recovery record.  They carry information only
# when a rotation intervened between the disposition and the re-admission.
_RECOVERY_ROTATION_FIELDS = ("disposing_generation", "readmitting_generation", "intervening_rotations")


def _recovery_record_core(record: dict) -> dict:
    """The record minus the rotation fields when they say "no rotation intervened".

    agent-harness#1576: an agent-harness#1296 runtime writes no rotation fields; the
    agent-harness#1550 runtime wrote all three even with no rotation
    (``intervening_rotations == []``, both generations equal to ``generation``).
    Those two records state the same authorization, so they compare equal here.
    Any other value of the fields, or only some of them, is kept and compared.
    """
    if not all(name in record for name in _RECOVERY_ROTATION_FIELDS):
        return record
    generation = record.get("generation")
    if (
        record["intervening_rotations"] == []
        and type(generation) is int
        and type(record["disposing_generation"]) is int
        and type(record["readmitting_generation"]) is int
        and record["disposing_generation"] == generation
        and record["readmitting_generation"] == generation
    ):
        return {key: value for key, value in record.items() if key not in _RECOVERY_ROTATION_FIELDS}
    return record


@contextlib.contextmanager
def crash_after(anchor: str):
    if anchor not in FABPUB_CRASH_ANCHORS + FABPUB_POST_PROVIDER_CRASH_ANCHORS:
        raise ValueError(f"unknown FABPUB crash anchor: {anchor}")
    previous = getattr(_CRASH_STATE, "anchor", None)
    _CRASH_STATE.anchor = anchor
    try:
        yield
    finally:
        _CRASH_STATE.anchor = previous


def _crash_at(anchor: str) -> None:
    if getattr(_CRASH_STATE, "anchor", None) == anchor:
        raise PublishCrashInjected(f"FABPUB crash injected at {anchor}")


@dataclass(frozen=True)
class PublishAuthorityPreimages:
    """The train-to-publisher handoff; it deliberately contains no admission."""

    checkpoint_root: Path
    envelope_authority_preimage: dict[str, str]

    @property
    def owned_paths_digest(self) -> str:
        return self.envelope_authority_preimage["effective_code_digest"]


def derive_publish_transaction_id(pre_trailer_intent_bytes: bytes) -> str:
    return _sha256(_TRANSACTION_DOMAIN + pre_trailer_intent_bytes)


def publish_attempt_id(repo: str, branch: str, head_sha: str) -> str:
    return _sha256(b"FABPUB-PUBLISH-ATTEMPT-v1\0" + f"{repo}\0{branch}\0{head_sha}".encode())


def _reject_identity_cycles(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _FORBIDDEN_IDENTITY_FIELDS:
                raise ValueError("circular_transaction_identity")
            _reject_identity_cycles(nested)
    elif isinstance(value, (tuple, list)):
        for nested in value:
            _reject_identity_cycles(nested)


def build_pre_trailer_intent(inputs: dict, *, original_message: bytes) -> PublishPreTrailerIntent:
    """Canonicalize the acyclic pre-trailer identity and append its one trailer."""
    _reject_identity_cycles(inputs)
    if b"FABPUB-Intent-ID:" in original_message:
        raise ValueError("caller message already contains FABPUB intent trailer")
    authority = inputs.get("envelope_authority_preimage")
    if not isinstance(authority, dict):
        raise ValueError("envelope_authority_preimage is required")
    _reject_identity_cycles(authority)
    declared_length = inputs.get("original_commit_message_length")
    declared_digest = inputs.get("original_commit_message_sha256")
    if declared_length != len(original_message) or declared_digest != _sha256(original_message):
        raise ValueError("original_commit_message_binding_mismatch")
    authority_digest = _sha256(_canonical_bytes(authority))
    declared_authority = inputs.get("envelope_authority_preimage_sha256")
    if declared_authority is not None and declared_authority != authority_digest:
        raise ValueError("envelope_authority_preimage_binding_mismatch")
    preimage = dict(inputs)
    preimage.pop("envelope_authority_preimage", None)
    preimage["envelope_authority_preimage_sha256"] = authority_digest
    pre_trailer = _canonical_bytes(preimage)
    transaction_id = derive_publish_transaction_id(pre_trailer)
    final_message = original_message + _TRAILER_PREFIX + transaction_id.encode("ascii") + b"\n"
    return PublishPreTrailerIntent(
        pre_trailer,
        _sha256(pre_trailer),
        transaction_id,
        _sha256(original_message),
        final_message,
        _sha256(final_message),
    )


#: Re-entrant advisory locking for the train-local transaction store.  `flock`
#: is keyed by OPEN FILE DESCRIPTION, so a second `open()` inside one process
#: blocks against the first; nesting is tracked per (path, thread) so a
#: transition may safely call another transition while other threads and other
#: processes still block.
_TXN_LOCK_DEPTH: dict[tuple[str, int], list] = {}
_TXN_LOCK_GUARD = threading.Lock()


@contextlib.contextmanager
def _transaction_flock(path: Path):
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = (str(path), threading.get_ident())
    with _TXN_LOCK_GUARD:
        entry = _TXN_LOCK_DEPTH.get(key)
        if entry is not None:
            entry[0] += 1
            reentered = True
        else:
            reentered = False
    if reentered:
        try:
            yield
        finally:
            with _TXN_LOCK_GUARD:
                entry = _TXN_LOCK_DEPTH.get(key)
                if entry is not None:
                    entry[0] -= 1
                    if entry[0] <= 0:
                        _TXN_LOCK_DEPTH.pop(key, None)
        return
    handle = path.open("a+", encoding="utf-8")
    fcntl.flock(handle, fcntl.LOCK_EX)
    with _TXN_LOCK_GUARD:
        _TXN_LOCK_DEPTH[key] = [1, handle]
    try:
        yield
    finally:
        with _TXN_LOCK_GUARD:
            entry = _TXN_LOCK_DEPTH.get(key)
            if entry is not None:
                entry[0] -= 1
                if entry[0] <= 0:
                    _TXN_LOCK_DEPTH.pop(key, None)
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def resolve_transaction_node_id(authority: dict | None, node_id: str | None = None) -> str:
    """The explicit coordinator/node context this transaction is scoped to.

    B2: the node identity must be the SAME on the preparing side and the
    resuming side, otherwise two nodes under one ``checkpoint_root`` collide on
    one active pointer.  The envelope authority pre-image is the one context
    both sides already carry, so it is the canonical source; an explicit
    argument selects it, and ``"node"`` remains the deterministic default. The
    authority's logical node identifier is identity material, not storage
    routing: callers may legitimately inspect that transaction as ``node``.
    """
    if node_id:
        return node_id
    return "node"


class PublishTransactionStore:
    """One train-local transaction pointer and its durable, immutable checkpoint."""

    def __init__(self, checkpoint_root: Path, node_id: str = "node") -> None:
        self.node_id = node_id or "node"
        # B2: the store root is NODE-SCOPED.  Two nodes sharing a checkpoint
        # root previously shared one `active.json`, so one node's transaction
        # was the other node's "active" transaction.
        self.root = Path(checkpoint_root).resolve() / "publish-transactions" / self.node_id

    @property
    def lock_path(self) -> Path:
        return self.root / "transactions.lock"

    @contextlib.contextmanager
    def exclusive(self):
        """B1: serialize every local transition against this node's store."""
        self.root.mkdir(parents=True, exist_ok=True)
        with _transaction_flock(self.lock_path):
            yield

    def sibling_active_pointers(self) -> tuple[Path, ...]:
        """Every other node's active pointer under the same checkpoint root."""
        parent = self.root.parent
        if not parent.exists():
            return ()
        return tuple(
            sorted(
                candidate / "active.json"
                for candidate in parent.iterdir()
                if candidate.is_dir() and (candidate / "active.json").exists()
            )
        )

    @property
    def active_pointer_path(self) -> Path:
        return self.root / "active.json"

    def checkpoint_path(self, transaction_id: str) -> Path:
        return self.root / f"{transaction_id}.json"

    def tombstone_path(self, transaction_id: str) -> Path:
        return self.root / f"{transaction_id}.tombstone.json"

    def recovery_path(self, transaction_id: str, generation: int) -> Path:
        return self.root / f"{transaction_id}.recovery.{int(generation)}.json"

    def load_active(self) -> dict | None:
        if not self.active_pointer_path.exists():
            return None
        return json.loads(self.active_pointer_path.read_text(encoding="utf-8"))

    def write_active(self, transaction_id: str) -> None:
        with self.exclusive():
            _atomic_json(
                self.active_pointer_path,
                {
                    "schema": "PublishTransactionPointer.v1",
                    "transaction_id": transaction_id,
                    "node_id": self.node_id,
                },
            )

    def clear_active(self, transaction_id: str) -> None:
        with self.exclusive():
            active = self.load_active()
            if active is not None and active.get("transaction_id") != transaction_id:
                raise PublishTransactionConflict(
                    "transaction pointer belongs to another transaction"
                )
            if self.active_pointer_path.exists():
                self.active_pointer_path.unlink()
                descriptor = os.open(str(self.active_pointer_path.parent), os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)


class PublishTransaction:
    def __init__(self, repo: Path, store: PublishTransactionStore, payload: dict) -> None:
        self.repo = Path(repo).resolve()
        self.store = store
        self._load(payload)

    def _load(self, payload: dict) -> None:
        self._payload = payload
        for key, value in payload.items():
            if key in {"original_message_b64", "final_message_b64", "repo"}:
                continue
            setattr(self, key, value)
        self.recorded_repo = Path(payload["repo"]).resolve()
        self.checkpoint_root = Path(payload["checkpoint_root"])
        self.owned_paths = tuple(payload["owned_paths"])
        self.final_commit_message_bytes = base64.b64decode(payload["final_message_b64"])
        self.original_commit_message_bytes = base64.b64decode(payload["original_message_b64"])
        self.checkpoint_path = self.store.checkpoint_path(self.transaction_id)
        self.active_pointer_path = self.store.active_pointer_path
        self.tombstone_path = self.store.tombstone_path(self.transaction_id)

    def _write(self) -> None:
        self._payload["state"] = self.state
        _atomic_json(self.checkpoint_path, self._payload)

    def project(self, state: str) -> "PublishTransaction":
        # B1: the ordering check and the durable write are ONE critical section;
        # split, two writers can both read the same current state and both
        # advance it.
        with self.store.exclusive():
            self._require_no_tombstone()
            durable = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if durable.get("transaction_id") != self.transaction_id:
                raise PublishTransactionConflict(
                    "durable checkpoint belongs to another transaction"
                )
            durable_state = durable.get("state")
            if durable_state == state:
                self._load(durable)
                return self
            if durable_state != self.state:
                raise PublishTransactionConflict(
                    f"stale transaction projection {self.state} over durable {durable_state}"
                )
            if self.state in (PublishTransactionState.ABANDONED, PublishTransactionState.CONFLICTED):
                raise PublishTransactionConflict("tombstoned transaction cannot advance")
            try:
                current_index = PublishTransactionState.ORDERED.index(self.state)
                requested_index = PublishTransactionState.ORDERED.index(state)
            except ValueError as error:
                raise ValueError("unknown publish transaction state") from error
            if requested_index != current_index + 1:
                raise PublishTransactionConflict(
                    f"illegal transaction projection {self.state} -> {state}"
                )
            self.state = state
            self._write()
            return self

    def write_tombstone(self, state: str) -> None:
        if state not in (PublishTransactionState.ABANDONED, PublishTransactionState.CONFLICTED):
            raise ValueError("only terminal tombstones may clear an active transaction")
        with self.store.exclusive():
            _atomic_json(
                self.tombstone_path,
                {"schema": "PublishTransactionTombstone.v1", "transaction_id": self.transaction_id, "state": state},
            )

    def clear_active_pointer(self) -> None:
        self.store.clear_active(self.transaction_id)

    def record_recovery(self, record: dict) -> Path:
        """Write-once provenance for re-admitting this transaction (agent-harness#1296).

        The broker never moves the checkpoint during a recovery; the SDK
        closeout (``publish_from_worktree``) seals it after the observed
        terminal, which releases the active pointer.  The state the transaction
        was recovered FROM is kept here, beside it, one file per re-admitting
        generation, written BEFORE the broker writes an owner or admission, so
        the history reads: admitted, outcome ambiguous, adjudicated not-landed
        by rotation X, re-admission authorized in generation N.  The outcome
        itself lives in that generation's evidence.

        The record is owner-only (0600), written atomically through an
        exclusive no-follow temporary file, and read back no-follow.  A second
        write for the same generation must carry the same bytes; an existing
        record that is not a regular file, or not JSON, refuses typed.

        agent-harness#1576: "the same bytes" is judged on the record's core.  The
        rotation fields are written only when a rotation intervened, and an
        existing record that carries them with their no-rotation values (the
        agent-harness#1550 runtime's shape) is the same authorization.  An
        existing record is never rewritten.  Every refusal here is a
        ``RecoveryRecordConflict`` naming the record path.
        """
        if self.state not in PublishTransactionState.ORDERED[3:]:
            raise PublishTransactionConflict("only an admitted transaction is recovered")
        path = self.store.recovery_path(self.transaction_id, record["generation"])
        payload = {"schema": "PublishTransactionRecovery.v1", **record}
        with self.store.exclusive():
            try:
                existing = _read_json_nofollow(path)
            except PublishTransactionConflict as error:
                raise RecoveryRecordConflict(str(error), record_path=path) from error
            if existing is not None:
                if _recovery_record_core(existing) != _recovery_record_core(payload):
                    raise RecoveryRecordConflict(
                        f"a different recovery is already recorded at {path}; nothing was "
                        "admitted and no provider call was made",
                        record_path=path,
                    )
                return path
            _atomic_json(path, payload, mode=0o600)
        return path

    def abandon(self) -> None:
        # Tombstone first, THEN clear the pointer, all under one lock hold, so a
        # concurrent reader can never see a cleared pointer with no tombstone.
        with self.store.exclusive():
            self.write_tombstone(PublishTransactionState.ABANDONED)
            self.clear_active_pointer()
            self.state = PublishTransactionState.ABANDONED
            self._write()

    def _conflict(self, detail: str) -> None:
        with self.store.exclusive():
            self._require_no_tombstone()
            self.write_tombstone(PublishTransactionState.CONFLICTED)
            self.clear_active_pointer()
            self.state = PublishTransactionState.CONFLICTED
            self._write()
        raise PublishTransactionConflict(f"CONFLICTED: {detail}")

    def _require_no_tombstone(self) -> None:
        if _read_json_nofollow(self.tombstone_path) is not None:
            raise PublishTransactionConflict("tombstoned transaction cannot advance")

    def resume(self) -> "PublishTransaction":
        self._require_no_tombstone()
        if self.state in (PublishTransactionState.ABANDONED, PublishTransactionState.CONFLICTED):
            raise PublishTransactionConflict("tombstoned transaction cannot resume")
        _validate_transaction_source_audit(self.repo, self)
        if self.state == PublishTransactionState.PREPARED:
            validate_transaction_owned_workspace(self.repo, self)
            _persist_commit_object(self)
        if self.state == PublishTransactionState.COMMIT_OBJECT_DURABLE:
            raw = _git_bytes(self.repo, "cat-file", "commit", self.expected_commit_oid)
            if raw is None or _sha256(raw) != self.final_commit_object_sha256:
                self._conflict("durable commit object is missing or changed")
            current = _git_output(self.repo, "rev-parse", self.exact_ref)
            if current == self.parent_head_sha:
                symbolic_head = _git_output(self.repo, "symbolic-ref", "-q", "HEAD")
                if symbolic_head != self.exact_ref:
                    self._conflict("HEAD is not the recorded symbolic branch")
                updated = _git(self.repo, "update-ref", self.exact_ref, self.expected_commit_oid, self.parent_head_sha)
                if updated.returncode:
                    self._conflict("exact ref CAS failed")
                _crash_at("after_git_commit_success_before_committed_checkpoint")
                current = _git_output(self.repo, "rev-parse", self.exact_ref)
            if current != self.expected_commit_oid:
                self._conflict("branch ref does not equal the expected commit object")
            self.committed_head_sha = self.expected_commit_oid
            self._payload["committed_head_sha"] = self.committed_head_sha
            self.project(PublishTransactionState.COMMITTED_HEAD_RESOLVED)
        if self.state in PublishTransactionState.ORDERED[2:]:
            symbolic_head = _git_output(self.repo, "symbolic-ref", "-q", "HEAD")
            if symbolic_head != self.exact_ref:
                self._conflict("HEAD is not the recorded symbolic branch")
            current = _git_output(self.repo, "rev-parse", self.exact_ref)
            if current != self.expected_commit_oid:
                self._conflict("resolved branch ref no longer equals the expected commit object")
        return self


def _construction_inputs(repo: Path, parent: str, tree: str) -> CommitConstructionInputs:
    return CommitConstructionInputs(
        parent,
        tree,
        _git_output(repo, "rev-parse", "--show-object-format") or "sha1",
        "Phase Loop",
        "phase-loop@example.invalid",
        "@1750000000 +0000",
        "Phase Loop",
        "phase-loop@example.invalid",
        "@1750000000 +0000",
    )


def _redact_publication_body(repo: Path, body: str | None, checkpoint_root: Path | None = None) -> str:
    known = [Path(repo).resolve()]
    if Path(repo).is_absolute():
        known.append(repo)
    if checkpoint_root is not None:
        known.append(Path(checkpoint_root).resolve())
        if Path(checkpoint_root).is_absolute():
            known.append(checkpoint_root)
    sanitized = body or ""
    identity = redaction_identity()
    seen = {sanitized}
    for _ in range(len(sanitized) + 1):
        updated = redact_text(sanitized, known=known, identity=identity)
        if updated == sanitized:
            return updated
        if updated in seen:
            break
        seen.add(updated)
        sanitized = updated
    raise PublishTransactionConflict("Publication body redaction did not stabilize")


def _transaction_payload(
    *,
    repo: Path,
    checkpoint_root: Path,
    branch: str,
    base: str,
    owned_paths: tuple[str, ...],
    draft: bool,
    pr_body: str,
    authority: dict,
    original_message: bytes,
    mode: str,
    publication_audit: dict | None = None,
) -> dict:
    pr_body = _redact_publication_body(repo, pr_body, checkpoint_root)
    parent = (
        _git_output(repo, "rev-parse", f"refs/heads/{branch}")
        or _git_output(repo, "rev-parse", branch)
        or _git_output(repo, "rev-parse", "HEAD")
    )

    if not parent:
        raise ValueError("branch reference cannot be resolved")
    tree = _git_output(repo, "write-tree")
    if not tree:
        raise ValueError("staged tree cannot be resolved")
    if publication_audit is not None and (
        publication_audit["tree_oid"] != tree or publication_audit["parent_head_sha"] != parent
    ):
        raise ValueError("publication audit no longer matches the staged tree and parent")
    # The legacy primitive defaults to ``base="main"`` even for a freshly
    # initialized repository whose default branch is named ``master``.  The
    # commit parent is the only stable base-tip available in that compatibility
    # shape; live routed callers still resolve their explicit base ref.
    base_tip = _git_output(repo, "rev-parse", base) or parent
    staged_diff = _git_bytes(repo, "diff", "--cached", "--binary")
    if staged_diff is None:
        raise ValueError("staged diff cannot be read")
    identity = canonical_repository_identity(repo)
    intent_inputs = {
        "schema": "PublishPreTrailerIntent.v1",
        "canonical_repository_identity": identity,
        "branch": branch,
        "base": base,
        "base_tip_sha": base_tip,
        "mode": mode,
        "parent_head_sha": parent,
        "staged_tree_oid": tree,
        "owned_paths": list(owned_paths),
        "staged_diff_sha256": _sha256(staged_diff),
        "original_commit_message_length": len(original_message),
        "original_commit_message_sha256": _sha256(original_message),
        "draft": draft,
        "pr_body_sha256": _sha256(pr_body.encode("utf-8")),
        "envelope_authority_preimage": authority,
    }
    intent = build_pre_trailer_intent(intent_inputs, original_message=original_message)
    construction = _construction_inputs(repo, parent, tree)
    payload = {
        "schema": "PublishCheckpoint.v1",
        "state": PublishTransactionState.PREPARED,
        "checkpoint_root": str(Path(checkpoint_root).resolve()),
        "repo": str(repo.resolve()),
        "canonical_repository_identity": identity,
        "branch": branch,
        "base": base,
        "base_tip_sha": base_tip,
        "exact_ref": f"refs/heads/{branch}",
        "owned_paths": list(owned_paths),
        "tree_oid": tree,
        "staged_diff_sha256": _sha256(staged_diff),
        "transaction_id": intent.transaction_id,
        "pre_trailer_intent_sha256": intent.pre_trailer_intent_sha256,
        "original_commit_message_sha256": intent.original_commit_message_sha256,
        "final_commit_message_sha256": intent.final_commit_message_sha256,
        "original_message_b64": base64.b64encode(original_message).decode("ascii"),
        "final_message_b64": base64.b64encode(intent.final_commit_message_bytes).decode("ascii"),
        "parent_head_sha": parent,
        "expected_commit_oid": "",
        "committed_head_sha": "",
        "final_commit_object_sha256": "",
        "mode": mode,
        "draft": draft,
        "pr_body": pr_body,
        "envelope_authority_preimage": authority,
        "construction_inputs": asdict(construction),
    }
    if publication_audit and publication_audit["source_exceptions"]:
        payload["publication_audit"] = publication_audit
    return payload


def _load_transaction(
    repo: Path, checkpoint_root: Path, transaction_id: str, node_id: str = "node"
) -> PublishTransaction | None:
    store = PublishTransactionStore(checkpoint_root, node_id)
    path = store.checkpoint_path(transaction_id)
    if not path.exists():
        return None
    return PublishTransaction(repo, store, json.loads(path.read_text(encoding="utf-8")))


def _persist_commit_object(transaction: PublishTransaction) -> None:
    inputs = transaction._payload["construction_inputs"]
    object_format = _git_output(transaction.repo, "rev-parse", "--show-object-format")
    if object_format != inputs.get("git_object_format"):
        raise RuntimeError("repository object format differs from frozen construction inputs")
    if inputs.get("signing_mode") != "disabled":
        raise ValueError("unsupported commit signing mode")
    if inputs.get("encoding_header") is not None or inputs.get("extra_headers"):
        raise ValueError("unsupported implicit commit headers")
    expected_config = ("core.abbrev=40", "commit.gpgsign=false")
    if tuple(inputs.get("constructor_config", ())) != expected_config:
        raise ValueError("unsupported commit constructor config")
    environment = {
        "GIT_AUTHOR_NAME": inputs["author_name"],
        "GIT_AUTHOR_EMAIL": inputs["author_email"],
        "GIT_AUTHOR_DATE": inputs["author_date"],
        "GIT_COMMITTER_NAME": inputs["committer_name"],
        "GIT_COMMITTER_EMAIL": inputs["committer_email"],
        "GIT_COMMITTER_DATE": inputs["committer_date"],
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": os.devnull,
        "LC_ALL": "C",
    }
    created = _git(
        transaction.repo,
        "-c",
        "core.abbrev=40",
        "-c",
        "commit.gpgsign=false",
        "commit-tree",
        transaction.tree_oid,
        "-p",
        transaction.parent_head_sha,
        input=transaction.final_commit_message_bytes,
        env=environment,
    )
    if created.returncode:
        raise RuntimeError("commit object construction failed")
    expected = created.stdout.decode("ascii").strip()
    raw = _git_bytes(transaction.repo, "cat-file", "commit", expected)
    if raw is None:
        raise RuntimeError("constructed commit object is unreadable")
    computed = _git(
        transaction.repo,
        "hash-object",
        "-t",
        "commit",
        "--stdin",
        input=raw,
    )
    if computed.returncode or computed.stdout.decode("ascii").strip() != expected:
        raise RuntimeError("constructed commit object OID does not match its raw bytes")
    transaction.expected_commit_oid = expected
    transaction.final_commit_object_sha256 = _sha256(raw)
    transaction._payload["expected_commit_oid"] = expected
    transaction._payload["final_commit_object_sha256"] = transaction.final_commit_object_sha256
    transaction.project(PublishTransactionState.COMMIT_OBJECT_DURABLE)


def prepare_publish_transaction(
    repo: Path,
    *,
    owned_paths: Sequence[str],
    checkpoint_root: Path,
    branch: str,
    envelope_authority_preimage: dict,
    base: str = "main",
    draft: bool = True,
    pr_body: str = "",
    commit_message: str | bytes | None = None,
    node_id: str | None = None,
    publication_audit: dict | None = None,
) -> PublishTransaction:
    """Stage-owned normal publish preparation through durable object construction."""
    original = (
        commit_message.encode("utf-8")
        if isinstance(commit_message, str)
        else commit_message
        if isinstance(commit_message, bytes)
        else b"chore: publish plan changes"
    )
    canonical_owned = tuple(sorted(owned_paths))
    payload = _transaction_payload(
        repo=Path(repo), checkpoint_root=Path(checkpoint_root), branch=branch, base=base,
        owned_paths=canonical_owned, draft=draft, pr_body=pr_body,
        authority=dict(envelope_authority_preimage), original_message=original, mode="normal",
        publication_audit=publication_audit,
    )
    node = resolve_transaction_node_id(envelope_authority_preimage, node_id)
    store = PublishTransactionStore(Path(checkpoint_root), node)
    # B1: the active-pointer probe, the checkpoint write, and the pointer write
    # are ONE critical section.  Split, two preparers both observe "no active"
    # and the second silently overwrites the first's pointer.
    with store.exclusive():
        active = store.load_active()
        if active is not None:
            existing = _load_transaction(
                Path(repo), Path(checkpoint_root), active.get("transaction_id", ""), node
            )
            if existing is not None and existing.state not in (PublishTransactionState.ABANDONED, PublishTransactionState.CONFLICTED, PublishTransactionState.TERMINAL_SEALED):
                if existing.transaction_id != payload["transaction_id"]:
                    raise PublishTransactionConflict(
                        "transaction conflict: active checkpoint has different pre-trailer identity"
                    )
                return existing
        transaction = PublishTransaction(Path(repo), store, payload)
        _validate_transaction_source_audit(Path(repo), transaction)
        transaction._write()
        store.write_active(transaction.transaction_id)
        _persist_commit_object(transaction)
        _crash_at("after_commit_object_checkpoint_before_ref_cas")
        return transaction


def prepare_prebuilt_transaction(
    repo: Path,
    *,
    owned_paths: Sequence[str],
    checkpoint_root: Path,
    branch: str,
    envelope_authority_preimage: dict,
    base: str = "main",
    draft: bool = True,
    pr_body: str = "",
    node_id: str | None = None,
) -> PublishTransaction:
    """Checkpoint an already-existing commit; this path never writes a ref/object."""
    head = _git_output(Path(repo), "rev-parse", f"refs/heads/{branch}")
    if not head:
        raise ValueError("prebuilt branch reference cannot be resolved")
    raw = _git_bytes(Path(repo), "cat-file", "commit", head)
    if raw is None or b"FABPUB-Intent-ID:" in raw:
        raise ValueError("prebuilt commit has an invalid FABPUB trailer")
    tree = _git_output(Path(repo), "rev-parse", f"{head}^{{tree}}")
    if not tree:
        raise ValueError("prebuilt tree cannot be resolved")
    # Prebuilt has no staged mutation.  Its identity binds the existing exact head
    # and the coordinator-derived branch diff that the broker must enforce.
    original = _git_bytes(Path(repo), "log", "-1", "--format=%B", head) or b"prebuilt"
    payload = _transaction_payload(
        repo=Path(repo), checkpoint_root=Path(checkpoint_root), branch=branch, base=base,
        owned_paths=tuple(sorted(owned_paths)), draft=draft, pr_body=pr_body,
        authority=dict(envelope_authority_preimage),
        original_message=original, mode="prebuilt",
    )
    payload.update(
        {
            "parent_head_sha": head,
            "tree_oid": tree,
            "expected_commit_oid": head,
            "committed_head_sha": head,
            "final_commit_object_sha256": _sha256(raw),
            "state": PublishTransactionState.COMMITTED_HEAD_RESOLVED,
        }
    )
    node = resolve_transaction_node_id(envelope_authority_preimage, node_id)
    store = PublishTransactionStore(Path(checkpoint_root), node)
    with store.exclusive():
        active = store.load_active()
        if active is not None:
            existing = _load_transaction(
                Path(repo), Path(checkpoint_root), active.get("transaction_id", ""), node
            )
            if existing is not None and existing.state not in (PublishTransactionState.ABANDONED, PublishTransactionState.CONFLICTED, PublishTransactionState.TERMINAL_SEALED):
                if existing.transaction_id != payload["transaction_id"]:
                    raise PublishTransactionConflict(
                        "transaction conflict: active checkpoint has different pre-trailer identity"
                    )
                return existing
        transaction = PublishTransaction(Path(repo), store, payload)
        transaction._write()
        store.write_active(transaction.transaction_id)
        return transaction


def _validate_transaction_source_audit(repo: Path, transaction: PublishTransaction) -> None:
    # Prebuilt commits retain their existing publication contract; this exception
    # applies only to normal staged publication, including direct preparation.
    if transaction.mode != "normal":
        return
    changed = _git_bytes(repo, "diff", "--name-only", "--no-renames", "-z",
                         transaction.parent_head_sha, transaction.tree_oid)
    if changed is None:
        raise RuntimeError("cannot enumerate frozen publication diff")
    suspect_paths = sorted(os.fsdecode(path) for path in changed.split(b"\0")
                           if path and _is_secret_path(os.fsdecode(path)))
    if suspect_paths:
        audit = transaction._payload.get("publication_audit")
        if not audit or (
            audit.get("tree_oid") != transaction.tree_oid
            or audit.get("parent_head_sha") != transaction.parent_head_sha
        ):
            raise RuntimeError("source exception requires a matching normal publication audit")
        try:
            expected = [_source_path_evidence(repo, path, transaction.parent_head_sha, transaction.tree_oid)
                        for path in sorted(suspect_paths)]
            valid = all(expected) and expected == audit.get("source_exceptions")
        except Exception:
            valid = False
        if not valid:
            raise RuntimeError("frozen source publication audit failed")


def validate_transaction_owned_workspace(repo: Path, transaction: PublishTransaction) -> None:
    """Validate the only workspace state from which this transaction may resume."""
    repo = Path(repo).resolve()
    if repo != transaction.repo:
        raise RuntimeError("transaction workspace mismatch")
    _validate_transaction_source_audit(repo, transaction)
    status = _git_bytes(repo, "status", "--porcelain=v1", "-z")
    if status is None:
        raise RuntimeError("cannot inspect transaction workspace")
    if transaction.state == PublishTransactionState.COMMIT_OBJECT_DURABLE and not status:
        current = _git_output(repo, "rev-parse", transaction.exact_ref)
        if current == transaction.expected_commit_oid:
            return
    if transaction.state in (
        PublishTransactionState.PREPARED,
        PublishTransactionState.COMMIT_OBJECT_DURABLE,
    ):
        staged = _git_bytes(repo, "diff", "--cached", "--name-only", "-z")
        staged_paths = tuple(sorted(os.fsdecode(path) for path in (staged or b"").split(b"\0") if path))
        if staged_paths != tuple(sorted(transaction.owned_paths)):
            raise RuntimeError("transaction staged paths differ from the frozen owned set")
        tree = _git_output(repo, "write-tree")
        diff = _git_bytes(repo, "diff", "--cached", "--binary")
        if tree != transaction.tree_oid or diff is None or _sha256(diff) != transaction.staged_diff_sha256:
            raise RuntimeError("transaction index no longer matches the durable checkpoint")
        for record in status.split(b"\0"):
            if not record:
                continue
            # only index-only staged changes to the frozen paths are recoverable
            if record[:2] == b"??" or record[1:2] != b" ":
                raise RuntimeError("transaction workspace has unstaged or untracked drift")
    elif status:
        raise RuntimeError("resolved transaction workspace must be clean")


def _unused_prebuilt_transaction(
    repo: Path, store: PublishTransactionStore, transaction_id: str, identity: str,
    *, complete: bool = True,
) -> PublishTransaction:
    payload = _read_json_nofollow(store.checkpoint_path(transaction_id))
    tombstone = _read_json_nofollow(store.tombstone_path(transaction_id))
    expected_tombstone = {
        "schema": "PublishTransactionTombstone.v1", "transaction_id": transaction_id,
        "state": PublishTransactionState.ABANDONED,
    }
    if payload is None or (tombstone != expected_tombstone and (complete or tombstone is not None)):
        raise UnadmittedPrebuiltConflict("no exact unused prebuilt transaction pair")
    required_state = PublishTransactionState.ABANDONED if complete else PublishTransactionState.COMMITTED_HEAD_RESOLVED
    if (
        payload.get("schema") != "PublishCheckpoint.v1"
        or payload.get("transaction_id") != transaction_id
        or payload.get("canonical_repository_identity") != identity
        or payload.get("repo") != str(Path(repo).resolve())
        or payload.get("checkpoint_root") != str(store.root.parent.parent)
        or payload.get("envelope_authority_preimage", {}).get("node_id") != store.node_id
        or payload.get("node_id", store.node_id) != store.node_id
        or payload.get("state") != required_state
        or payload.get("mode") != "prebuilt"
        or not isinstance(payload.get("staged_diff_sha256"), str)
        or len(payload["staged_diff_sha256"]) != 64
        or payload["staged_diff_sha256"] == _sha256(b"")
        or not payload.get("base_tip_sha")
        or any(payload.get(name) != payload["base_tip_sha"] for name in (
            "parent_head_sha", "expected_commit_oid", "committed_head_sha",
        ))
        or payload.get("exact_ref") != f"refs/heads/{payload.get('branch')}"
    ):
        raise UnadmittedPrebuiltConflict("transaction is not an unused-base prebuilt checkpoint")
    raw = _git_bytes(Path(repo), "cat-file", "commit", payload["expected_commit_oid"])
    if raw is None or _sha256(raw) != payload.get("final_commit_object_sha256"):
        raise UnadmittedPrebuiltConflict("unused prebuilt commit object differs")
    return PublishTransaction(Path(repo), store, payload)


def _retired_prebuilt_remainder(repo: Path, store: PublishTransactionStore, tombstones: tuple[Path, ...]):
    triggered = False
    for path in tombstones:
        try:
            tombstone = _read_json_nofollow(path)
            payload = _read_json_nofollow(store.checkpoint_path(path.name.removesuffix(".tombstone.json")))
            triggered = triggered or bool(
                tombstone and payload and tombstone.get("state") == PublishTransactionState.ABANDONED
                and tombstone.get("transaction_id") == payload.get("transaction_id")
                and tombstone.get("transaction_id") == path.name.removesuffix(".tombstone.json")
                and payload.get("mode") == "prebuilt"
            )
        except Exception:
            continue
    if not triggered:
        return None
    from .convergence.broker import live
    from .convergence.broker.verbs import require_unadmitted_prebuilt_witnesses

    remaining = list(tombstones)
    try:
        snapshot = live.repository_snapshot(repo)
        root = live.active_store_root(snapshot.container)
        for path in tombstones:
            try:
                transaction = _unused_prebuilt_transaction(
                    repo, store, path.name.removesuffix(".tombstone.json"), snapshot.identity,
                )
                require_unadmitted_prebuilt_witnesses(root, transaction)
            except Exception:
                continue
            remaining.remove(path)
    except Exception:
        pass
    if not remaining:
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED)
    if len(remaining) == 1:
        try:
            payload = _read_json_nofollow(store.checkpoint_path(remaining[0].name.removesuffix(".tombstone.json")))
            if payload is not None:
                return PublishResumeCandidate(PublishTransactionState.CONFLICTED, PublishTransaction(repo, store, payload))
        except Exception as error:
            raise PublishTransactionConflict("remaining publication checkpoint is unreadable") from error
    raise PublishTransactionConflict("retired prebuilt history has conflicting remaining transactions")


def inspect_publish_resume_candidate(repo: Path, *, checkpoint_root: Path, node_id: str) -> PublishResumeCandidate:
    """Read-only resume inspection; it never chooses a semantic substitute OID."""
    store = PublishTransactionStore(Path(checkpoint_root), node_id)
    pointers = store.sibling_active_pointers()
    if len(pointers) > 1:
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED)
    active = store.load_active()
    if active is None:
        tombstones = tuple(sorted(store.root.glob("*.tombstone.json"))) if store.root.exists() else ()
        remainder = _retired_prebuilt_remainder(Path(repo), store, tombstones)
        if remainder is not None:
            return remainder
        if len(tombstones) == 1:
            transaction_id = tombstones[0].name.removesuffix(".tombstone.json")
            transaction = _load_transaction(
                Path(repo), Path(checkpoint_root), transaction_id, store.node_id
            )
            return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED)
    transaction = _load_transaction(
        Path(repo), Path(checkpoint_root), active.get("transaction_id", ""), store.node_id
    )
    if transaction is None or transaction.tombstone_path.exists():
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
    if transaction.canonical_repository_identity != canonical_repository_identity(Path(repo)):
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED)
    if (
        transaction._payload.get("node_id", store.node_id) != store.node_id
        or transaction._payload.get(
            "repository", transaction.canonical_repository_identity
        )
        != transaction.canonical_repository_identity
        or transaction.recorded_repo != Path(repo).resolve()
    ):
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
    if transaction.checkpoint_root.resolve() != Path(checkpoint_root).resolve():
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
    if (
        transaction.state == PublishTransactionState.TERMINAL_SEALED
        and _git_output(Path(repo), "rev-parse", transaction.exact_ref) != transaction.expected_commit_oid
    ):
        # agent-harness#906: a SEALED transaction whose head the workspace has ADVANCED
        # PAST is a completed prior publication attempt, not in-flight work. The HEAD and
        # workspace checks below describe an in-flight publish (or its crash-after-seal
        # replay, which still takes them: same head, same checks, unchanged) and must not
        # run against it -- reporting it CONFLICTED failed the whole train at preflight
        # (board PR #907 r1, claude seat, executed). It is returned ATTACHED: the
        # post-accept path in `publish_from_worktree` needs the transaction to finish
        # sealing, and `prepare_*_transaction` already treats a sealed transaction as not
        # active. Whether it counts as PUBLISHED is not the inspector's call -- the broker
        # seals on every terminal class -- the coordinator decides from the evidence store
        # (`train_runner._sealed_publish_disposition`).
        return PublishResumeCandidate(PublishTransactionState.TERMINAL_SEALED, transaction)
    if transaction.state in (
        PublishTransactionState.PREPARED,
        PublishTransactionState.COMMIT_OBJECT_DURABLE,
    ):
        symbolic_head = _git_output(Path(repo), "symbolic-ref", "-q", "HEAD")
        if symbolic_head != transaction.exact_ref:
            return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
    try:
        validate_transaction_owned_workspace(Path(repo), transaction)
    except RuntimeError:
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
    ref = _git_output(Path(repo), "rev-parse", transaction.exact_ref)
    if transaction.state == PublishTransactionState.PREPARED:
        if ref != transaction.parent_head_sha:
            return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
    if transaction.state in PublishTransactionState.ORDERED[1:]:
        raw = _git_bytes(Path(repo), "cat-file", "commit", transaction.expected_commit_oid)
        if raw is None or _sha256(raw) != transaction.final_commit_object_sha256:
            return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
        if transaction.mode == "normal":
            _, separator, message = raw.partition(b"\n\n")
            trailer = b"FABPUB-Intent-ID: " + transaction.transaction_id.encode("ascii")
            if (
                not separator
                or message != transaction.final_commit_message_bytes
                or message.count(trailer) != 1
            ):
                return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
    if transaction.state == PublishTransactionState.COMMIT_OBJECT_DURABLE:
        if ref not in (transaction.parent_head_sha, transaction.expected_commit_oid):
            return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
        if ref == transaction.expected_commit_oid:
            return PublishResumeCandidate(PublishTransactionState.COMMITTED_HEAD_RESOLVED, transaction)
    elif transaction.state in PublishTransactionState.ORDERED[2:] and ref != transaction.expected_commit_oid:
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED, transaction)
    return PublishResumeCandidate(transaction.state, transaction)


def _is_secret_path(path: str) -> bool:
    name = Path(path).name.lower()
    return name.startswith(".env") or any(fragment in name for fragment in ("credential", "secret", ".key", "private"))


def _source_path_evidence(repo: Path, path: str, parent: str, tree: str) -> dict | None:
    """Classify existing Python modules, never merely a Python-looking filename."""
    candidate = Path(path)
    if candidate.suffix != ".py" or any(
        part.lower().startswith(".env") or ".key" in part.lower()
        or part.lower().endswith((".pem", ".p12", ".pfx"))
        for part in candidate.parts
    ):
        return None
    blobs = []
    for ref in (parent, tree):
        entry = _git_bytes(repo, "--literal-pathspecs", "ls-tree", "-z", ref, "--", path)
        if not entry or len(entry.split(b"\0")) != 2:
            return None
        metadata, _, returned_path = entry.partition(b"\t")
        if returned_path != os.fsencode(path) + b"\0":
            return None
        fields = metadata.split()
        if len(fields) != 3 or fields[0] not in (b"100644", b"100755") or fields[1] != b"blob":
            return None
        oid = fields[2].decode("ascii")
        size = _git_output(repo, "cat-file", "-s", oid)
        if size is None or int(size) > 1_048_576:
            return None
        blob = _git_bytes(repo, "cat-file", "blob", oid)
        if blob is None:
            return None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                module = ast.parse(blob, filename="<publication-source>")
                compile(module, "<publication-source>", "exec", dont_inherit=True)
        except (SyntaxError, ValueError, Warning):
            return None
        if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in module.body):
            return None
        blobs.append((oid, blob))
    # Instantiate only the pinned built-in detectors: no repo config, allowlist,
    # verification requests, or filters that can suppress a finding.
    if version("detect-secrets") != "1.5.0":
        raise ValueError("unsupported publication scanner version")
    from detect_secrets.core.plugins.util import get_mapping_from_secret_type_to_class

    plugins = [kind() for kind in get_mapping_from_secret_type_to_class().values()]
    if not plugins:
        raise ValueError("publication scanner has no detectors")
    oid, blob = blobs[-1]
    # ast.parse accepts source encoding declarations; scanning must use the same decoding.
    import io
    import tokenize

    encoding, _ = tokenize.detect_encoding(io.BytesIO(blob).readline)
    for number, line in enumerate(blob.decode(encoding).splitlines(), 1):
        if any(plugin.analyze_line(filename=path, line=line, line_number=number) for plugin in plugins):
            return None
    return {"path": path, "parent_blob_oid": blobs[0][0], "blob_oid": oid,
            "blob_sha256": _sha256(blob), "policy": "tracked-python-detect-secrets-1.5.0-v1"}


def _blocked(reason: str, detail: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"status": "publication_blocked", "reason": reason}
    if detail:
        result["detail"] = detail
    return result


def _check_gh_auth() -> str | None:
    """Return a non-secret diagnostic when the GitHub CLI cannot authenticate."""
    try:
        completed = subprocess.run(
            ["gh", "auth", "status", "--active"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"gh auth status unavailable: {type(error).__name__}"
    if completed.returncode:
        return "gh auth status failed: not authenticated"
    return None


def _check_publish_origin(repo: Path) -> str | None:
    """Validate the exact origin shape the GitHub broker will later consume."""
    from .convergence.broker.credsep import (
        resolve_git_origin_url,
        resolve_host_qualified_repo_slug,
    )

    try:
        origin_url = resolve_git_origin_url(repo)
        resolve_host_qualified_repo_slug(origin_url)
    except (OSError, subprocess.SubprocessError, ValueError):
        return "origin is missing or is not a supported GitHub repository URL"
    return None


def _audit_staged_diff(repo: Path, owned_paths: Sequence[str], *, evidence: dict | None = None) -> dict[str, Any] | None:
    owned_set = {Path(path).as_posix() for path in owned_paths}
    parent = _git_output(repo, "rev-parse", "HEAD")
    tree = _git_output(repo, "write-tree")
    if not parent or not tree:
        return _blocked("staged_audit_failed", "Cannot freeze the staged tree and parent")
    staged_raw = _git_bytes(repo, "diff", "--name-only", "--no-renames", "-z", parent, tree)
    if staged_raw is None:
        return _blocked("staged_audit_failed", "Cannot enumerate the staged diff")
    staged_paths = [os.fsdecode(path) for path in staged_raw.split(b"\0") if path]
    if not staged_paths:
        return _blocked("nothing_staged", "No changes were staged after git add")
    source_exceptions = []
    for path in sorted(staged_paths):
        if Path(path).as_posix() not in owned_set:
            return _blocked("out_of_scope_staged_path", f"Staged path {path!r} is not in the owned-paths set")
        if _is_secret_path(path):
            try:
                source = _source_path_evidence(repo, path, parent, tree) if evidence is not None else None
            except Exception:
                # Do not expose scanner exception text; it may contain source or secret bytes.
                return _blocked("source_scan_failed", "Cannot establish staged source safety")
            if source is None:
                return _blocked("secret_staged_path", f"Staged path {path!r} matches a secret/credential/.env pattern")
            source_exceptions.append(source)
    if _git(repo, "diff", "--cached", "--check").returncode:
        return _blocked("staged_check_failed", "git diff --cached --check found whitespace errors")
    if _git_output(repo, "write-tree") != tree or _git_output(repo, "rev-parse", "HEAD") != parent:
        return _blocked("staged_audit_changed", "Staged tree or parent changed during audit")
    if evidence is not None:
        evidence.update(tree_oid=tree, parent_head_sha=parent, source_exceptions=source_exceptions)
    return None


def _default_build_publish_authority(runtime, node, workspace: Path, owned_paths: Sequence[str]) -> PublishAuthorityPreimages:
    branch = _git_output(Path(workspace), "branch", "--show-current") or "detached"
    identity = canonical_repository_identity(Path(workspace))
    owned_digest = _sha256(os.fsencode("\0".join(sorted(owned_paths))))
    roadmap_digest = getattr(runtime, "roadmap_digest", "") or _sha256(str(getattr(node, "roadmap", "")).encode())
    authority = {
        "schema": "PublishEnvelopeAuthorityPreimage.v1",
        "train_id": str(getattr(runtime, "train_id", "train")),
        "node_id": str(getattr(node, "node_id", "node")),
        "action": "publish_committed_branch",
        "roadmap_digest": roadmap_digest,
        "effective_code_digest": owned_digest,
        "dependency_digest": _sha256(b""),
        "verification_plan_digest": roadmap_digest,
        "expected_version_predicate": "head == expected_commit_oid",
        "authority_domain_scope": f"repository:{identity}",
        "operation_identity": f"publish:{branch}",
    }
    return PublishAuthorityPreimages(Path(getattr(runtime, "coordinator_root")), authority)


def _envelope_from_transaction(transaction: PublishTransaction, authority: dict, repo: Path) -> PreAdmissionEnvelope:
    values = {key: value for key, value in authority.items() if key != "schema"}
    return PreAdmissionEnvelope(
        **values,
        canonical_repository_identity=transaction.canonical_repository_identity,
        original_commit_message_sha256=transaction.original_commit_message_sha256,
        pre_trailer_intent_sha256=transaction.pre_trailer_intent_sha256,
        transaction_id=transaction.transaction_id,
        final_commit_message_sha256=transaction.final_commit_message_sha256,
        expected_commit_oid=transaction.expected_commit_oid,
        committed_head_sha=transaction.committed_head_sha,
        final_commit_object_sha256=transaction.final_commit_object_sha256,
        adapter_worktree=str(repo.resolve()),
        checkpoint_root=str(transaction.checkpoint_root),
    )


def _partition_rotation_command(worktree: Path) -> list[str]:
    """The operator rotation argv for ``worktree``; the attestation is operator input."""
    return [
        "phase-loop",
        "fabpub-rotate-partition",
        "--worktree",
        str(worktree),
        "--attestation",
        "<operator attestation outside the ceremony directory>",
        "--cutover-id",
        "<new rotation id>",
        "--json",
    ]


#: agent-harness#1574 ask 2: the rotation must authenticate the same partition.
_ROTATION_AUTHORITY_ROOT = (
    "run the rotation with the same authority root this route used: the same "
    "FABPUB_AUTHORITY_ROOT environment value, or pass it as --authority-root"
)

#: agent-harness#1574 ask 2 (SG-F3): the warning runbook 8a carries.
_SECOND_ATTESTATION_WARNING = (
    "do not attest attested_not_landed a second time without new evidence: two "
    "ambiguous pushes are not evidence of no effect"
)


def _observed_after_ambiguity_handoff(
    snapshot, observation: Mapping[str, Any]
) -> dict[str, Any]:
    """agent-harness#1591: the rotation fields for a provider outcome on an ambiguous key.

    An effect requires ``observed_landed`` and forbids ``attested_not_landed``
    (new runtimes refuse it); its attestation inputs are the observation's.  A
    no-effect observation only supports ``attested_not_landed``: the judgement
    stays the operator's.
    """
    if observation.get("observed_state") != TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED.value:
        return {
            "required_disposition": None,
            "supporting_evidence": {
                "observed_state": observation.get("observed_state"),
                "evidence_reference": observation.get("evidence_reference"),
                "note": (
                    "the provider reported no effect after the key was blocked; this supports "
                    "attested_not_landed but does not prove it"
                ),
            },
        }
    key = str(observation.get("idempotency_key", ""))
    suffix = key.split("\0", 1)[1] if "\0" in key else key
    inputs = {
        "observed_head": observation.get("head_sha"),
        "evidence_url": observation.get("evidence_reference"),
        "effect_key_suffix": suffix,
        "owner_nonce": observation.get("owner_nonce"),
        "transaction_id": observation.get("transaction_id"),
    }
    fields: dict[str, Any] = {
        "required_disposition": "observed_landed",
        "forbidden_disposition": "attested_not_landed",
        "attestation_inputs": inputs,
        "rotate_requires": (
            "a reviewed PartitionRotationAttestation.v1 disposing the blocked effect "
            f"observed_landed with observed_head {inputs['observed_head']} and evidence_url "
            f"{inputs['evidence_url']} (the provider reported this effect after the key was "
            "blocked), and a read-only preflight verdict of ready; attested_not_landed is "
            "refused for this key, and a later remote absence is not proof that the effect "
            "did not land"
        ),
    }
    if Path(snapshot.store_root) == Path(snapshot.container):
        # The stdlib builder digests the generation-0 container only.
        fields["attestation_builder_command"] = [
            "python3",
            "phase-loop-runtime/scripts/fabpub_rotation_attestation.py",
            "--container",
            str(snapshot.container),
            "--out",
            "<operator attestation path outside the broker namespace>",
            "--attested-by",
            "<operator>",
            "--effect-key-suffix",
            suffix,
            "--observed-head",
            str(inputs["observed_head"]),
            "--evidence-url",
            str(inputs["evidence_url"]),
        ]
    return fields


def _human_publication_handoff(
    repo: Path,
    *,
    next_step: str,
    required_inputs: Sequence[str] = (),
    conflicting_recovery_record: Path | None = None,
    refusal: Mapping[str, Any] | None = None,
    observed_after_ambiguity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the actionable, non-authorizing handoff for a human publish refusal.

    ``refusal`` carries the typed broker refusal's fields (agent-harness#1573,
    agent-harness#1578, agent-harness#1594): the blocking key and transaction for
    a rotation, or this attempt's key and transaction for a pre-provider refusal
    (with ``provider_call_made: True`` for the post-entry generation refusal,
    agent-harness#1628).
    """
    refusal = dict(refusal or {})
    handoff: dict[str, Any] = {
        "schema": "HumanPublicationHandoff.v1",
        "repository": str(Path(repo).resolve()),
        "next_step": next_step,
        "human_required": True,
    }
    if required_inputs:
        handoff["required_inputs"] = list(required_inputs)
    if conflicting_recovery_record is not None:
        # agent-harness#1576: name the write-once record that refused the
        # re-admission, so the operator knows what is stuck.
        handoff.update(
            conflicting_recovery_record=str(conflicting_recovery_record),
            recovery_procedure="docs/fabpub-partition-rotation-runbook.md section 8a",
            next_step_source=(
                "the recovery record authorizes a re-admission in its generation and is "
                "written before the owner; it does not prove an admission happened. Compare "
                "it with this runtime's refusal detail and with that generation's broker "
                "evidence and adapter-start owner for the key before changing anything"
            ),
        )
    try:
        from .convergence.broker.live import repository_snapshot

        snapshot = repository_snapshot(repo)
    except Exception:
        return handoff
    handoff.update(
        canonical_repository_identity=snapshot.identity,
        repository_common_dir=str(snapshot.common_dir),
        resume="retry publish_human_invoked_from_worktree with the same plan and verification artifact",
    )
    if next_step in ("inspect_scope_correction_predecessor", "review_scope_correction_outcome"):
        handoff.update(
            recovery_procedure="docs/fabpub-partition-rotation-runbook.md section 8b",
            resume=(
                "preserve the original and successor checkpoints and broker evidence; "
                "review the successor outcome before any further provider attempt. "
                "PublishScopeCorrection.v1 authenticates its predecessor only in the "
                "active generation and does not support rotate-then-retry recovery. "
                "A later generation requires supported predecessor-chain recovery; "
                "do not replace receipts or infer no effect from remote absence."
            ),
        )
    if next_step == "resolve_publication_recovery_refusal":
        handoff.update(
            recovery_procedure="docs/fabpub-partition-rotation-runbook.md section 8a",
            next_step_source=(
                "the refusal detail: it names what did not bind and the next step for that case; "
                "a new rotation applies only while the key is blocked in the active generation; "
                "an earlier attested_not_landed disposition stays valid across later rotations "
                "until the key gains evidence in a later generation"
            ),
            rotate_command_when_key_blocked=[
                "phase-loop",
                "fabpub-rotate-partition",
                "--worktree",
                str(snapshot.worktree),
                "--attestation",
                "<operator attestation outside the ceremony directory>",
                "--cutover-id",
                "<new rotation id>",
                "--json",
            ],
            rotate_requires=(
                "a reviewed PartitionRotationAttestation.v1 disposing the blocked effect "
                "attested_not_landed with the predecessor owner's transaction_id, and a "
                "read-only preflight verdict of ready; later remote absence is not proof "
                "that the historical attempt had no effect"
            ),
            after_rotation="restart any broker process, then retry with the same plan and verification artifact",
        )
    if next_step == "adjudicate_publication_by_partition_rotation":
        # agent-harness#1312: the key's evidence is outcome_ambiguous_blocked in
        # the active generation; only an operator rotation adjudicates it.
        blocking_keys = list(refusal.get("blocking_effect_keys") or ())
        handoff.update(
            recovery_procedure=(
                "docs/fabpub-partition-rotation-runbook.md sections 1, 3, 4, 6, 7 and 8a"
            ),
            next_step_source=(
                "the key's evidence in the active partition generation is "
                "outcome_ambiguous_blocked, which is permanent there: a retry before a "
                "rotation replays the same block with no provider call"
            ),
            rotate_command=_partition_rotation_command(snapshot.worktree),
            rotate_requires=(
                "a reviewed PartitionRotationAttestation.v1 disposing the blocked effect "
                "observed_landed (naming the observed head) or attested_not_landed (with "
                "the predecessor owner's transaction_id, which for this publication's own "
                "key is the transaction_id of its checkpoint under checkpoint_root), and a "
                "read-only preflight verdict of ready; later remote absence is not proof "
                "that the historical attempt had no effect; "
                + _SECOND_ATTESTATION_WARNING
            ),
            authority_root=_ROTATION_AUTHORITY_ROOT,
            after_rotation="restart any broker process, then retry with the same plan and verification artifact",
            resume=(
                "only after the rotation: retry publish_human_invoked_from_worktree "
                "with the same plan and verification artifact"
            ),
        )
        if blocking_keys:
            # agent-harness#1573: a refusal raised for the partition, not replayed
            # for this key; the rotation disposes the BLOCKING key(s).
            handoff["blocking_effect_keys"] = blocking_keys
            owner_transaction = refusal.get("blocking_transaction_id")
            if owner_transaction:
                handoff["blocking_transaction_id"] = owner_transaction
            handoff["next_step_source"] = (
                "the active partition generation is blocked by outcome_ambiguous_blocked "
                "evidence for the effect key(s) in blocking_effect_keys"
                + (
                    ", promoted from an unsealed adapter-start owner of transaction "
                    f"{owner_transaction}"
                    if owner_transaction
                    else ""
                )
                + "; every publish to the partition refuses before the provider until a "
                "rotation adjudicates them, whichever key it publishes"
            )
            handoff["rotate_requires"] = (
                "the attestation disposes every key in blocking_effect_keys (which may "
                "not be this publication's key); " + handoff["rotate_requires"]
            )
        if observed_after_ambiguity is not None:
            handoff.update(_observed_after_ambiguity_handoff(snapshot, observed_after_ambiguity))
    if next_step == "rebuild_broker_client_and_retry":
        # agent-harness#1573 ask 4: a routing client built before a rotation.
        handoff.update(
            recovery_procedure="docs/fabpub-partition-rotation-runbook.md section 8 step 1",
            next_step_source=(
                "this call's routing client is bound to a partition generation that a "
                "rotation retired: the rotation moved the ACTIVE generation after the "
                "client was built (agent-harness#1315); nothing was read or written and "
                "no provider call was made, and no rotation or authority change is needed"
            ),
            resume=(
                "close the routing client and build a new one with "
                "build_routing_broker_client() (or restart the broker process that holds "
                "it), then retry publish_human_invoked_from_worktree with the same plan "
                "and verification artifact"
            ),
        )
    if next_step == "retry_after_inflight_publication":
        # agent-harness#1578 ask 5 (SA-F5): contention, not ambiguity.
        handoff.update(
            next_step_source=(
                "another publication of this repository is still running and holds the "
                "partition's adapter-start owner (agent-harness#1313); this is contention, "
                "not ambiguity: nothing was written and no provider call was made"
            ),
            resume=(
                "retry publish_human_invoked_from_worktree shortly with the same plan and "
                "verification artifact, after the in-flight publication ends; this "
                "refusal needs no partition rotation and no authority change"
            ),
        )
    if next_step == "retry_once_before_partition_rotation":
        # agent-harness#1594 ask 1 (SA-F2): the in-flight row must become
        # ambiguous before a rotation can adjudicate it.
        handoff.update(
            effect_key=refusal.get("effect_key"),
            transaction_id=refusal.get("transaction_id"),
            recovery_procedure=(
                "docs/fabpub-pre-admission-ambiguity.md \"Provider entry and failures "
                "around it\"; docs/fabpub-partition-rotation-runbook.md section 8a"
            ),
            next_step_source=(
                "refused after this attempt's admission became durable and before the "
                "provider was entered, so no provider call was made; the attempt's "
                "unsealed adapter-start owner (and its provider_call_in_flight intent, "
                "when recorded) stays, and a rotation now refuses with \"intents without "
                "a terminal\" until one retry promotes the owner to "
                "outcome_ambiguous_blocked"
            ),
            resume=(
                "retry once with the same plan and verification artifact; if that retry "
                "reports outcome_ambiguous_blocked or next step "
                "adjudicate_publication_by_partition_rotation, follow its rotation "
                "handoff; otherwise follow whatever handoff the retry returns"
            ),
            attestation_evidence=(
                "keep this result: its provider_call_made false and refusal detail are "
                "the evidence that this attempt never entered the provider; the "
                "ambiguous row the retry leaves cannot be told apart from a crash "
                "during the provider call"
            ),
        )
        if refusal.get("provider_call_made"):
            # agent-harness#1628: the same stored shape, but the provider WAS
            # entered.  Nothing here supports attested_not_landed by construction.
            # agent-harness#1684: an adapter that returned is not reported as
            # failed, and its pull request URL is carried, not discarded.
            execute_returned = refusal.get("execute_returned")
            pr_url = refusal.get("pr_url")
            head_sha = refusal.get("head_sha")
            if execute_returned:
                returned = f"PR {pr_url}" if pr_url else "no pull request URL"
                source = (
                    f"the provider returned ({returned}) but its terminal record was "
                    "refused by the generation fence (a DRAINING writer latch or a revoked "
                    "generation lease), so the outcome is not recorded (provider_call_made "
                    "true); the fence then refused the outcome_ambiguous_blocked record too"
                )
            else:
                failed = (
                    "the adapter failed"
                    if execute_returned is False
                    else "the adapter failed, or its outcome could not be recorded"
                )
                source = (
                    f"the provider was entered and {failed}, so the outcome is "
                    "unknown (provider_call_made true); the generation fence (a DRAINING "
                    "writer latch or a revoked generation lease) then refused the "
                    "outcome_ambiguous_blocked record"
                )
            if pr_url:
                rotate_requires = (
                    "the provider returned a pull request for this attempt, so dispose "
                    f"this key observed_landed with evidence_url {pr_url} and observed_head "
                    f"{head_sha} (this result's pr_url and head_sha; confirm them at the "
                    "provider), never attested_not_landed; a later remote absence is not "
                    "proof that the effect did not land"
                )
            else:
                rotate_requires = (
                    "the provider was entered, so the disposition of this key is the "
                    "operator's judgement: observed_landed (naming the observed head) if "
                    "the head is on the remote branch or a pull request exists for it; "
                    "otherwise attested_not_landed with this result's transaction_id, "
                    "where later remote absence is not proof that the attempt had no "
                    "effect; " + _SECOND_ATTESTATION_WARNING
                )
            handoff.update(
                execute_returned=execute_returned,
                next_step_source=(
                    source + ", so no terminal was written: the attempt's unsealed "
                    "adapter-start owner and its provider_call_in_flight intent stay, and "
                    "a rotation now refuses with \"intents without a terminal\" until one "
                    "retry promotes the owner to outcome_ambiguous_blocked"
                ),
                resume=(
                    "retry once with the same plan and verification artifact, after any "
                    "partition rotation ceremony in progress has finished or rolled back; "
                    "if that retry reports outcome_ambiguous_blocked or next step "
                    "adjudicate_publication_by_partition_rotation, follow its rotation "
                    "handoff; otherwise follow whatever handoff the retry returns"
                ),
                rotate_requires=rotate_requires,
                attestation_evidence=(
                    "keep this result: its provider_call_made true and refusal detail "
                    "record that this attempt entered the provider"
                    + (
                        ", and its pr_url is the provider's returned pull request, which "
                        "the retry's handoff does not repeat"
                        if pr_url
                        else " with an unknown outcome"
                    )
                    + "; it is not evidence that the provider was never entered"
                ),
            )
            if execute_returned:
                handoff.update(pr_url=pr_url, head_sha=head_sha, branch=refusal.get("branch"))
    if next_step == "probe_and_confirm_fabpub_authority":
        inventory = (
            snapshot.common_dir
            / "phase-loop-fabpub-bootstrap-v1"
            / f"{snapshot.identity}.inventory.json"
        )
        handoff.update(
            probe_command=[
                "phase-loop",
                "fabpub-bootstrap",
                "--probe",
                "--inventory",
                str(inventory),
                "--worktree",
                str(snapshot.worktree),
            ],
            operator_must_supply=[
                "--legacy-root",
                "--historical-evidence-root",
                "--search-root",
            ],
            apply_command=[
                "phase-loop",
                "fabpub-bootstrap",
                "--apply",
                "--inventory",
                str(inventory),
                "--confirm-zero-history",
            ],
            apply_requires=(
                "operator review that the inventory covers every authoritative legacy, "
                "historical-evidence, and search root"
            ),
        )
    return handoff


def _human_publication_context_digest(
    identity: str,
    branch: str,
    owned_paths: Sequence[str],
    plan_sha256: str,
    verification_artifact_sha256: str,
) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "schema": "HumanPublicationContext.v1",
                "canonical_repository_identity": identity,
                "branch": branch,
                "owned_paths": sorted(owned_paths),
                "plan_sha256": plan_sha256,
                "verification_artifact_sha256": verification_artifact_sha256,
            }
        )
    )


def _human_publication_authority(
    repo: Path,
    owned_paths: Sequence[str],
    *,
    plan_sha256: str,
    verification_artifact_sha256: str,
    branch: str,
    checkpoint_root: Path,
) -> PublishAuthorityPreimages:
    identity = canonical_repository_identity(repo)
    context_digest = _human_publication_context_digest(
        identity,
        branch,
        owned_paths,
        plan_sha256,
        verification_artifact_sha256,
    )
    verification_digest = _sha256(
        _canonical_bytes(
            {
                "schema": "HumanVerificationBinding.v1",
                "plan_sha256": plan_sha256,
                "verification_artifact_sha256": verification_artifact_sha256,
            }
        )
    )
    authority = {
        "schema": "PublishEnvelopeAuthorityPreimage.v1",
        "train_id": f"human-publication-{context_digest[:24]}",
        "node_id": f"human-{context_digest[:24]}",
        "action": "publish_committed_branch",
        "roadmap_digest": plan_sha256,
        "effective_code_digest": _sha256(os.fsencode("\0".join(sorted(owned_paths)))),
        "dependency_digest": _sha256(b""),
        "verification_plan_digest": verification_digest,
        "expected_version_predicate": "head == expected_commit_oid",
        "authority_domain_scope": f"repository:{identity}",
        "operation_identity": f"publish:{branch}",
    }
    return PublishAuthorityPreimages(checkpoint_root, authority)


def _typed_refusal_handoffs() -> tuple[tuple[Any, Any], ...]:
    """Broker refusal type -> ``(next_step, refusal fields)`` or ``None``.

    Keyed on the exception type only, never on message text.  A handler that
    returns ``None`` leaves the refusal to ``repair_fabpub_authority``.  The
    refusal fields carry ``provider_call_made: True`` only for a refusal raised
    after provider entry (agent-harness#1628); every other handler is pre-entry.
    See ``plans/fabpub-typed-handoffs.md`` for the table.
    """
    from .convergence.broker import live, verbs

    def rotation_for_partition(error):
        keys = list(error.blocking_keys)
        if not keys:
            # The block is carried by the partition receipt, not by a key here.
            return None
        return (
            "adjudicate_publication_by_partition_rotation",
            {"blocking_effect_keys": keys},
        )

    return (
        (
            live.RoutingClientGenerationRetired,
            lambda _error: ("rebuild_broker_client_and_retry", {}),
        ),
        (
            (verbs.AdapterStartOwnerLive, verbs.AdapterStartOwnerContended),
            lambda _error: ("retry_after_inflight_publication", {}),
        ),
        (
            verbs.UnsealedOwnerBlocksPartition,
            lambda error: (
                "adjudicate_publication_by_partition_rotation",
                {
                    "blocking_effect_keys": [error.effect_key],
                    "blocking_transaction_id": error.transaction_id,
                },
            ),
        ),
        (verbs.PartitionEpochBlocked, rotation_for_partition),
        (
            verbs.ProviderEntryRefused,
            lambda error: (
                "retry_once_before_partition_rotation",
                {"effect_key": error.effect_key, "transaction_id": error.transaction_id},
            ),
        ),
        (
            # agent-harness#1628: the provider WAS entered; the generation fence
            # refused the ambiguity record, so the row is still in flight.
            # agent-harness#1684: whether the adapter returned, and its result.
            live.ProviderEffectGenerationRefused,
            lambda error: (
                "retry_once_before_partition_rotation",
                {
                    "effect_key": error.effect_key,
                    "transaction_id": error.transaction_id,
                    "provider_call_made": True,
                    "execute_returned": error.execute_returned,
                    "pr_url": error.pr_url,
                    "head_sha": error.head_sha,
                    "branch": error.branch,
                },
            ),
        ),
    )


def _typed_refusal_handoff(error: BaseException) -> tuple[str, dict[str, Any]] | None:
    from .publish_scope_correction import ScopeCorrectionPredecessorUnavailable

    if isinstance(error, ScopeCorrectionPredecessorUnavailable):
        return "inspect_scope_correction_predecessor", {}
    for types, handler in _typed_refusal_handoffs():
        if isinstance(error, types):
            return handler(error)
    return None


def _human_publication_scope_precheck(
    repo: Path, owned_paths: Sequence[str], *, base: str, branch: str,
) -> str | None:
    """Catch omitted committed companion paths before creating a new commit.

    The broker still checks the final branch independently. This early check
    cannot authorize publication; it avoids creating a sticky rejected head
    when a human caller supplies only its currently dirty paths.
    """
    from .convergence.broker.credsep import GitHubBrokerAdapter

    if GitHubBrokerAdapter._base_invalid(base, branch):
        return "owned-scope-invalid-base"
    changed = _git_bytes(
        repo, "diff", "--name-only", "-z", "--no-renames", f"origin/{base}...HEAD",
    )
    if changed is None:
        return "owned-scope-diff-failed"
    uncovered = sorted(
        os.fsdecode(path) for path in changed.split(b"\0") if path
        and not GitHubBrokerAdapter._covered_by_owned(os.fsdecode(path), owned_paths)
    )
    if uncovered:
        return "owned-scope-exceeded:" + ",".join(uncovered[:20])
    # An empty committed diff is normal before the first staged publication.
    return None


def publish_human_invoked_from_worktree(
    repo: Path,
    owned_paths: Sequence[str],
    *,
    plan_path: Path | None = None,
    verification_artifact_path: Path | None = None,
    draft: bool = True,
    pr_body: str | None = None,
    commit_message: str | None = None,
    protected_branches: frozenset[str] = PROTECTED_BRANCHES,
    prebuilt: bool = False,
    base: str = "main",
    scope_correction_from: tuple[Path, str] | None = None,
    abandon_unadmitted_prebuilt: str | None = None,
) -> dict[str, Any]:
    """Publish a human-invoked detailed-plan run through authenticated FABPUB.

    This adapter derives only pre-admission authority. The broker still allocates
    all fencing fields, and repository routing remains receipt- and lease-gated.
    """
    if abandon_unadmitted_prebuilt is not None and (
        prebuilt or scope_correction_from is not None or not isinstance(abandon_unadmitted_prebuilt, str)
        or len(abandon_unadmitted_prebuilt) != 64
        or any(character not in "0123456789abcdef" for character in abandon_unadmitted_prebuilt)
    ):
        result = _blocked("publication_transaction_conflicted", "recovery requires one exact lowercase transaction ID and normal publication")
        result["provider_call_made"] = False
        return result
    required = [
        name
        for name, value in (
            ("plan_path", plan_path),
            ("verification_artifact_path", verification_artifact_path),
        )
        if value is None
    ]
    if required:
        result = _blocked(
            "human_publication_context_required",
            "human publication requires the detailed plan and verification artifact",
        )
        result["handoff"] = _human_publication_handoff(
            repo, next_step="supply_publication_context", required_inputs=required
        )
        return result

    artifacts: dict[str, Path] = {
        "plan_path": Path(plan_path),
        "verification_artifact_path": Path(verification_artifact_path),
    }
    invalid = [name for name, path in artifacts.items() if not path.is_file()]
    if invalid:
        result = _blocked(
            "human_publication_context_invalid",
            f"human publication context is not a regular file: {', '.join(invalid)}",
        )
        result["handoff"] = _human_publication_handoff(
            repo, next_step="repair_publication_context", required_inputs=invalid
        )
        return result

    from .convergence.broker import live

    try:
        active = live.fabpub_capability_active()
    except live.FabpubConfigurationError as error:
        result = _blocked("repository_publication_authority_refused", str(error))
        result["handoff"] = _human_publication_handoff(
            repo, next_step="repair_fabpub_configuration"
        )
        return result
    if not active:
        result = _blocked(
            "fabpub_inactive",
            "the supported human publication route requires active FABPUB",
        )
        result["handoff"] = _human_publication_handoff(
            repo, next_step="activate_or_upgrade_fabpub"
        )
        return result

    topology = collect_git_topology(repo)
    if not topology.get("available"):
        result = _blocked("not_a_git_worktree", "Repo is not a git worktree")
        result["handoff"] = _human_publication_handoff(
            repo, next_step="repair_git_worktree"
        )
        return result
    branch = str(topology.get("branch", ""))
    if not branch or branch.startswith("detached@"):
        result = _blocked("detached_head", "Cannot publish from detached HEAD state")
        result["handoff"] = _human_publication_handoff(
            repo, next_step="checkout_publish_branch"
        )
        return result
    if branch in protected_branches:
        result = _blocked(
            "branch_protected", f"Cannot publish from protected branch {branch!r}"
        )
        result["handoff"] = _human_publication_handoff(
            repo, next_step="checkout_unprotected_branch"
        )
        return result

    origin_error = _check_publish_origin(repo)
    if origin_error is not None:
        result = _blocked("publication_origin_required", origin_error)
        result["handoff"] = _human_publication_handoff(
            repo, next_step="configure_supported_publication_origin"
        )
        return result

    auth_error = _check_gh_auth()
    if auth_error is not None:
        result = _blocked("github_cli_authentication_required", auth_error)
        result["handoff"] = _human_publication_handoff(
            repo, next_step="authenticate_github_cli_and_retry"
        )
        return result

    scope_error = _human_publication_scope_precheck(
        repo, owned_paths, base=base, branch=branch,
    )
    if scope_error is not None:
        result = _blocked("publication_scope_precheck_failed", scope_error)
        result["handoff"] = _human_publication_handoff(
            repo, next_step="repair_publication_scope_and_retry"
        )
        return result

    try:
        plan_sha256 = _sha256(artifacts["plan_path"].read_bytes())
        verification_sha256 = _sha256(
            artifacts["verification_artifact_path"].read_bytes()
        )
        snapshot = live.repository_snapshot(repo)
    except (OSError, live.LegacyCutoverConflict, PermissionError) as error:
        result = _blocked("human_publication_context_invalid", str(error))
        result["handoff"] = _human_publication_handoff(
            repo, next_step="repair_publication_context"
        )
        return result
    context_digest = _human_publication_context_digest(
        snapshot.identity,
        branch,
        owned_paths,
        plan_sha256,
        verification_sha256,
    )
    checkpoint_root = (
        snapshot.common_dir / "phase-loop-human-publication-v1" / context_digest
    )
    barrier_report: dict[str, Any] | None = None
    broker_client = None
    try:
        pr_body = _redact_publication_body(repo, pr_body, checkpoint_root)
        if abandon_unadmitted_prebuilt is not None:
            from .convergence.broker.verbs import capture_unadmitted_prebuilt_history

            capture_unadmitted_prebuilt_history(live.active_store_root(snapshot.container))
        barrier_report = live.fabpub_activation_barrier([repo])
        authenticated = {
            str(Path(worktree).resolve())
            for worktree in barrier_report.get("repositories", ())
        }
        if str(snapshot.worktree) not in authenticated:
            result = _blocked(
                "repository_publication_authority_required",
                "the repository has no authenticated FABPUB partition receipt",
            )
            result["handoff"] = _human_publication_handoff(
                repo, next_step="probe_and_confirm_fabpub_authority"
            )
            return result

        checkpoint_root.mkdir(parents=True, exist_ok=True)
        authority = _human_publication_authority(
            repo,
            owned_paths,
            plan_sha256=plan_sha256,
            verification_artifact_sha256=verification_sha256,
            branch=branch,
            checkpoint_root=checkpoint_root,
        )
        broker_client = live.build_routing_broker_client()
        if abandon_unadmitted_prebuilt is not None:
            broker_client.abandon_unadmitted_prebuilt(
                repo, abandon_unadmitted_prebuilt, checkpoint_root=checkpoint_root,
                node_id=resolve_transaction_node_id(authority.envelope_authority_preimage, authority.envelope_authority_preimage.get("node_id")),
                authority=authority.envelope_authority_preimage, branch=branch,
                owned_paths=tuple(sorted(owned_paths)), base=base, draft=draft, pr_body=pr_body,
            )
        result = publish_from_worktree(
            repo,
            owned_paths,
            draft=draft,
            pr_body=pr_body,
            commit_message=commit_message,
            topology=topology,
            protected_branches=protected_branches,
            prebuilt=prebuilt,
            scope_correction_from=scope_correction_from,
            broker_client=broker_client,
            base=base,
            publish_authority=authority,
            checkpoint_root=checkpoint_root,
        )
        if result.get("status") == "publication_blocked" and "handoff" not in result:
            # agent-harness#1312: an ambiguous terminal (first attempt or its
            # replay) blocks the key until a partition rotation adjudicates it;
            # no retry can succeed before that.
            ambiguous = (
                result.get("terminal_state")
                == TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value
            )
            result["handoff"] = _human_publication_handoff(
                repo,
                next_step=(
                    "review_scope_correction_outcome"
                    if ambiguous and scope_correction_from is not None
                    else "adjudicate_publication_by_partition_rotation"
                    if ambiguous
                    else "repair_publication_precheck_and_retry"
                ),
                observed_after_ambiguity=(
                    result.get("observed_after_ambiguity") if ambiguous else None
                ),
            )
            result["checkpoint_root"] = str(checkpoint_root)
        return result
    except PublicationRecoveryRequired as error:
        # agent-harness#1296: the current head's transaction was already
        # admitted and no rotation adjudicated its effect; nothing was written.
        result = _blocked("publication_recovery_required", str(error))
        result["handoff"] = _human_publication_handoff(
            repo, next_step="resolve_publication_recovery_refusal"
        )
        result["checkpoint_root"] = str(checkpoint_root)
        return result
    except PublishTransactionConflict as error:
        result = _blocked("publication_transaction_conflicted", str(error))
        if isinstance(error, UnadmittedPrebuiltConflict):
            result["provider_call_made"] = False
        result["handoff"] = _human_publication_handoff(
            repo,
            next_step="resolve_publication_transaction_conflict",
            conflicting_recovery_record=getattr(error, "record_path", None),
        )
        result["checkpoint_root"] = str(checkpoint_root)
        return result
    except (
        live.FabpubConfigurationError,
        live.LegacyCutoverConflict,
        PermissionError,
    ) as error:
        result = _blocked("repository_publication_authority_refused", str(error))
        typed = _typed_refusal_handoff(error)
        if typed is None:
            result["handoff"] = _human_publication_handoff(
                repo, next_step="repair_fabpub_authority"
            )
        else:
            next_step, refusal = typed
            if scope_correction_from is not None and next_step in (
                "adjudicate_publication_by_partition_rotation", "retry_once_before_partition_rotation",
            ):
                next_step = "review_scope_correction_outcome"
            result["handoff"] = _human_publication_handoff(
                repo, next_step=next_step, refusal=refusal
            )
            # Per handler: every typed refusal is raised before provider entry
            # (agent-harness#1593) except the post-entry generation refusal
            # (agent-harness#1628).
            result["provider_call_made"] = bool(refusal.get("provider_call_made", False))
            if refusal.get("pr_url"):
                # agent-harness#1684: the provider returned a pull request whose
                # terminal record was refused; keep its URL (status stays blocked).
                result["pr_url"] = refusal["pr_url"]
        if checkpoint_root.exists():
            result["checkpoint_root"] = str(checkpoint_root)
        return result
    except OSError as error:
        result = _blocked("human_publication_environment_failed", str(error))
        result["handoff"] = _human_publication_handoff(
            repo, next_step="repair_publication_environment"
        )
        if checkpoint_root.exists():
            result["checkpoint_root"] = str(checkpoint_root)
        return result
    except PublishCrashInjected:
        raise
    except Exception as error:
        result = _blocked(
            "human_publication_execution_failed",
            f"{type(error).__name__}: publication adapter failed",
        )
        result["handoff"] = _human_publication_handoff(
            repo, next_step="inspect_publication_failure_and_retry"
        )
        if checkpoint_root.exists():
            result["checkpoint_root"] = str(checkpoint_root)
        return result
    finally:
        try:
            if broker_client is not None and hasattr(broker_client, "close"):
                broker_client.close()
        finally:
            if barrier_report is not None:
                live.release_barrier_leases(barrier_report)


def publish_from_worktree(
    repo: Path,
    owned_paths: Sequence[str],
    *,
    draft: bool = True,
    pr_title: str | None = None,
    pr_body: str | None = None,
    commit_message: str | None = None,
    topology: dict[str, Any] | None = None,
    protected_branches: frozenset[str] = PROTECTED_BRANCHES,
    prebuilt: bool = False,
    broker_client: BrokerClient | None = None,
    admission: AdmissionRequest | None = None,
    base: str = "main",
    scope_correction_from: tuple[Path, str] | None = None,
    publish_authority: PublishAuthorityPreimages | None = None,
    checkpoint_root: Path | None = None,
) -> dict[str, Any]:
    """Publish only through the broker; FABPUB inputs construct an envelope post-commit."""
    try:
        pr_body = _redact_publication_body(repo, pr_body, checkpoint_root)
    except PublishTransactionConflict as error:
        return _blocked("publication_transaction_conflicted", str(error))
    topo = dict(topology or collect_git_topology(repo))
    if not topo.get("available"):
        return _blocked("not_a_git_worktree", "Repo is not a git worktree")
    branch = topo.get("branch", "")
    if not branch or branch.startswith("detached@"):
        return _blocked("detached_head", "Cannot publish from detached HEAD state")
    if branch in protected_branches:
        return _blocked("branch_protected", f"Cannot publish from protected branch {branch!r}")
    if pr_title is not None:
        return _blocked("custom_title_unsupported", "BrokerRequest has no pr_title field")
    from .convergence.broker.live import fabpub_capability_active

    active = fabpub_capability_active()
    authority = publish_authority.envelope_authority_preimage if publish_authority else None
    node_id = (
        resolve_transaction_node_id(authority, authority.get("node_id"))
        if authority is not None
        else "node"
    )
    candidate = (
        inspect_publish_resume_candidate(
            repo,
            checkpoint_root=Path(checkpoint_root),
            node_id=node_id,
        )
        if active and authority is not None and checkpoint_root is not None
        else PublishResumeCandidate(PublishTransactionState.CONFLICTED)
    )
    # agent-harness#906: a sealed transaction for an OLD head (the workspace advanced past
    # it) is a completed prior publication -- never resumed, a fresh one is prepared. A
    # sealed transaction for the CURRENT head is the crash-after-seal replay and resumes;
    # the broker replays its terminal, or (agent-harness#1296) re-admits it once under an
    # authenticated attested_not_landed rotation, or refuses typed with no write.
    sealed_prior = (
        candidate.transaction is not None
        and candidate.state == PublishTransactionState.TERMINAL_SEALED
        and candidate.transaction.committed_head_sha != _git_output(repo, "rev-parse", "HEAD")
    )
    resuming = (
        candidate.transaction is not None
        and candidate.state != PublishTransactionState.CONFLICTED
        and not sealed_prior
    )
    if resuming:
        try:
            frozen_body = _redact_publication_body(repo, candidate.transaction.pr_body, checkpoint_root)
        except PublishTransactionConflict as error:
            return _blocked("publication_transaction_conflicted", str(error))
        if frozen_body != candidate.transaction.pr_body:
            return _blocked(
                "publication_transaction_conflicted",
                "The frozen publication body requires redaction; preserve the checkpoint "
                "and resolve its transaction before preparing sanitized publication text",
            )
    if candidate.transaction is not None and candidate.state == PublishTransactionState.CONFLICTED:
        raise PublishTransactionConflict("active publish transaction is conflicted")
    if prebuilt and scope_correction_from is not None:
        return _blocked("scope_correction_prebuilt_conflict", "scope correction is a distinct operation")
    if not prebuilt and not owned_paths:
        return _blocked("no_owned_paths", "No owned paths to stage; nothing to publish")
    if not prebuilt and not resuming and scope_correction_from is None and _git(repo, "add", "--", *owned_paths).returncode:
        return _blocked("stage_failed", "git add -- <owned_paths> failed")
    publication_audit = {} if active and authority is not None else None
    audit = None if prebuilt or resuming or scope_correction_from is not None else _audit_staged_diff(repo, owned_paths, evidence=publication_audit)
    if audit is not None:
        return audit
    if broker_client is None:
        return _blocked("broker_required", "publish mutation requires an admitted broker client")
    if active and authority is not None and not resuming:
        if prebuilt:
            staged = _git_bytes(repo, "diff", "--cached", "--binary")
            if staged is None or staged:
                return _blocked("publication_workspace_invalid", "prebuilt publication requires a readable empty staged index")
        unstaged = _git_bytes(repo, "diff", "--name-only", "-z")
        untracked = _git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z")
        if unstaged is None or untracked is None:
            return _blocked("publication_workspace_invalid", "Cannot inspect publication workspace")
        if unstaged or untracked:
            return _blocked(
                "publication_workspace_invalid",
                "Publication workspace has unstaged or untracked changes; repair the workspace and ensure private evidence is Git-ignored before retrying",
            )

    if not active:
        if scope_correction_from is not None:
            return _blocked("scope_correction_requires_fabpub", "scope correction requires active FABPUB")
        if admission is None:
            return _blocked("broker_required", "publish mutation requires an admitted broker client")
        if not prebuilt and _git(repo, "commit", "-m", commit_message or "chore: publish plan changes").returncode:
            return _blocked("commit_failed", "git commit failed")
        head = _git_output(repo, "rev-parse", "HEAD")
        if not head:
            return _blocked("head_sha_missing", "Could not resolve HEAD")
        execution = broker_client.execute(BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, admission, str(repo), branch, head, tuple(owned_paths), base=base, draft=draft, pr_body=pr_body or ""))
    else:
        if publish_authority is None or checkpoint_root is None:
            return _blocked("publish_authority_required", "FABPUB publish requires authority preimages and checkpoint_root")
        authority = publish_authority.envelope_authority_preimage
        if Path(checkpoint_root).resolve() != Path(publish_authority.checkpoint_root).resolve():
            return _blocked("checkpoint_root_mismatch", "checkpoint_root must equal the authority handoff root")
        if scope_correction_from is not None:
            from .publish_scope_correction import prepare

            transaction = prepare(
                Path(repo), original_checkpoint_root=scope_correction_from[0],
                original_node_id=scope_correction_from[1], checkpoint_root=Path(checkpoint_root),
                owned_paths=owned_paths, branch=branch, authority=authority,
                base=base, draft=draft, pr_body=pr_body or "",
            )
        elif candidate.transaction is not None and not sealed_prior:
            transaction = candidate.transaction
            if (
                transaction.envelope_authority_preimage != authority
                or transaction.branch != branch
                or transaction.mode != ("prebuilt" if prebuilt else "normal")
            ):
                raise PublishTransactionConflict(
                    "active publish transaction differs from the requested authority"
                )
        else:
            transaction = (
                prepare_prebuilt_transaction(repo, owned_paths=owned_paths, checkpoint_root=Path(checkpoint_root), branch=branch, envelope_authority_preimage=authority, base=base, draft=draft, pr_body=pr_body or "", node_id=node_id)
                if prebuilt
                else prepare_publish_transaction(repo, owned_paths=owned_paths, checkpoint_root=Path(checkpoint_root), branch=branch, envelope_authority_preimage=authority, base=base, draft=draft, pr_body=pr_body or "", commit_message=commit_message, node_id=node_id, publication_audit=publication_audit)
            )
        transaction.resume()
        _crash_at("after_committed_checkpoint_before_broker_execute")
        envelope = _envelope_from_transaction(transaction, authority, repo)
        execution = broker_client.execute(BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, envelope, transaction.canonical_repository_identity, branch, transaction.committed_head_sha, transaction.owned_paths, base=base, draft=draft, pr_body=transaction.pr_body, adapter_worktree=str(Path(repo).resolve()), scope_correction_of=transaction._payload.get("scope_correction", {}).get("predecessor_id", "")))
        if execution.accepted:
            candidate = inspect_publish_resume_candidate(
                repo,
                checkpoint_root=Path(checkpoint_root),
                node_id=transaction.store.node_id,
            )
            if candidate.transaction is None or candidate.state == PublishTransactionState.CONFLICTED:
                raise RuntimeError("broker accepted publish without a recoverable transaction")
            transaction = candidate.transaction
            # The SDK closeout seals the checkpoint after an observed terminal; the
            # seal releases the active pointer for the next head.  A recovered
            # transaction is sealed here too (agent-harness#1296): its recovered
            # state is kept by the write-once recovery record, not the checkpoint.
            while transaction.state != PublishTransactionState.TERMINAL_SEALED:
                transaction.project(PublishTransactionState.ORDERED[PublishTransactionState.ORDERED.index(transaction.state) + 1])
    if not execution.accepted or execution.publish_result is None:
        blocked = _blocked(execution.reason or execution.evidence.terminal_state, execution.evidence.evidence_reference)
        # agent-harness#1312: the typed terminal state, which ``reason`` hides
        # whenever the broker also names a reason.
        blocked["terminal_state"] = execution.evidence.terminal_state
        # agent-harness#1577 (D3): whether THIS call entered the provider adapter;
        # false for a replay of stored evidence and for a refusal before entry.
        blocked["provider_call_made"] = bool(getattr(execution, "provider_call_made", False))
        # agent-harness#1591: a provider outcome on a key already ambiguous.
        observation = getattr(execution, "observed_after_ambiguity", None)
        if observation is not None:
            blocked["observed_after_ambiguity"] = {**observation.row(), "durable": observation.durable}
        return blocked
    return {"status": "published", "branch": execution.publish_result.branch, "head_sha": execution.publish_result.head_sha, "pr_url": execution.publish_result.pr_url}
