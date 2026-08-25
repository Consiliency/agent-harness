"""The bounded worktree-to-broker publication transaction.

The transaction deliberately separates making a commit object from moving a
branch reference.  The former is checkpointed before the latter, which makes a
restart an exact ref-CAS retry rather than a second commit attempt.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import subprocess
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .convergence.broker.verbs import BrokerClient
from .convergence.contracts import AdmissionRequest, BrokerRequest, BrokerVerb, PreAdmissionEnvelope
from .convergence.broker.live import canonical_repository_identity
from .git_topology import collect_git_topology


PROTECTED_BRANCHES: frozenset[str] = frozenset({"main", "master", "develop", "release"})
_TRANSACTION_DOMAIN = b"FABPUB-PUBLISH-TRANSACTION-v1\0"
_TRAILER_PREFIX = b"\n\nFABPUB-Intent-ID: "
FABPUB_CRASH_ANCHORS = (
    "after_commit_object_checkpoint_before_ref_cas",
    "after_git_commit_success_before_committed_checkpoint",
    "after_committed_checkpoint_before_broker_execute",
    "after_broker_intent_before_adapter_started",
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


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


@contextlib.contextmanager
def crash_after(anchor: str):
    if anchor not in FABPUB_CRASH_ANCHORS:
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
                raise RuntimeError("transaction pointer belongs to another transaction")
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
            durable = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if durable.get("transaction_id") != self.transaction_id:
                raise RuntimeError("durable checkpoint belongs to another transaction")
            durable_state = durable.get("state")
            if durable_state == state:
                self._load(durable)
                return self
            if durable_state != self.state:
                raise RuntimeError(
                    f"stale transaction projection {self.state} over durable {durable_state}"
                )
            if self.state in (PublishTransactionState.ABANDONED, PublishTransactionState.CONFLICTED):
                raise RuntimeError("tombstoned transaction cannot advance")
            try:
                current_index = PublishTransactionState.ORDERED.index(self.state)
                requested_index = PublishTransactionState.ORDERED.index(state)
            except ValueError as error:
                raise ValueError("unknown publish transaction state") from error
            if requested_index != current_index + 1:
                raise RuntimeError(f"illegal transaction projection {self.state} -> {state}")
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
            self.write_tombstone(PublishTransactionState.CONFLICTED)
            self.clear_active_pointer()
            self.state = PublishTransactionState.CONFLICTED
            self._write()
        raise RuntimeError(f"CONFLICTED: {detail}")

    def resume(self) -> "PublishTransaction":
        if self.state in (PublishTransactionState.ABANDONED, PublishTransactionState.CONFLICTED):
            raise RuntimeError("tombstoned transaction cannot resume")
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
) -> dict:
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
    return {
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
                    raise RuntimeError("transaction conflict: active checkpoint has different pre-trailer identity")
                return existing
        transaction = PublishTransaction(Path(repo), store, payload)
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
                    raise RuntimeError("transaction conflict: active checkpoint has different pre-trailer identity")
                return existing
        transaction = PublishTransaction(Path(repo), store, payload)
        transaction._write()
        store.write_active(transaction.transaction_id)
        return transaction


def validate_transaction_owned_workspace(repo: Path, transaction: PublishTransaction) -> None:
    """Validate the only workspace state from which this transaction may resume."""
    repo = Path(repo).resolve()
    if repo != transaction.repo:
        raise RuntimeError("transaction workspace mismatch")
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


def inspect_publish_resume_candidate(repo: Path, *, checkpoint_root: Path, node_id: str) -> PublishResumeCandidate:
    """Read-only resume inspection; it never chooses a semantic substitute OID."""
    store = PublishTransactionStore(Path(checkpoint_root), node_id)
    pointers = store.sibling_active_pointers()
    if len(pointers) > 1:
        return PublishResumeCandidate(PublishTransactionState.CONFLICTED)
    active = store.load_active()
    if active is None:
        tombstones = tuple(sorted(store.root.glob("*.tombstone.json"))) if store.root.exists() else ()
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


def _blocked(reason: str, detail: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"status": "publication_blocked", "reason": reason}
    if detail:
        result["detail"] = detail
    return result


def _audit_staged_diff(repo: Path, owned_paths: Sequence[str]) -> dict[str, Any] | None:
    owned_set = {Path(path).as_posix() for path in owned_paths}
    staged_raw = _git_output(repo, "diff", "--cached", "--name-only")
    staged_paths = [path.strip() for path in (staged_raw or "").splitlines() if path.strip()]
    if not staged_paths:
        return _blocked("nothing_staged", "No changes were staged after git add")
    for path in staged_paths:
        if Path(path).as_posix() not in owned_set:
            return _blocked("out_of_scope_staged_path", f"Staged path {path!r} is not in the owned-paths set")
        if _is_secret_path(path):
            return _blocked("secret_staged_path", f"Staged path {path!r} matches a secret/credential/.env pattern")
    if _git(repo, "diff", "--cached", "--check").returncode:
        return _blocked("staged_check_failed", "git diff --cached --check found whitespace errors")
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


def _install_train_runner_authority_surface() -> None:
    # SL-2 owns the transaction surface while the legacy runner remains untouched
    # until SL-3.  Exporting these two handoff helpers here keeps the handoff
    # type single-sourced without changing the runner's legacy execution path.
    try:
        from . import train_runner
    except Exception:
        return
    setattr(train_runner, "PublishAuthorityPreimages", PublishAuthorityPreimages)
    setattr(train_runner, "_default_build_publish_authority", _default_build_publish_authority)


_install_train_runner_authority_surface()


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
    publish_authority: PublishAuthorityPreimages | None = None,
    checkpoint_root: Path | None = None,
) -> dict[str, Any]:
    """Publish only through the broker; FABPUB inputs construct an envelope post-commit."""
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
    resuming = candidate.transaction is not None and candidate.state != PublishTransactionState.CONFLICTED
    if not prebuilt and not owned_paths:
        return _blocked("no_owned_paths", "No owned paths to stage; nothing to publish")
    if not prebuilt and not resuming and _git(repo, "add", "--", *owned_paths).returncode:
        return _blocked("stage_failed", "git add -- <owned_paths> failed")
    audit = None if prebuilt or resuming else _audit_staged_diff(repo, owned_paths)
    if audit is not None:
        return audit
    if broker_client is None:
        return _blocked("broker_required", "publish mutation requires an admitted broker client")

    if not active:
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
        if candidate.transaction is not None:
            if candidate.state == PublishTransactionState.CONFLICTED:
                raise RuntimeError("active publish transaction is conflicted")
            transaction = candidate.transaction
            if (
                transaction.envelope_authority_preimage != authority
                or transaction.branch != branch
                or transaction.mode != ("prebuilt" if prebuilt else "normal")
            ):
                raise RuntimeError("active publish transaction differs from the requested authority")
        else:
            transaction = (
                prepare_prebuilt_transaction(repo, owned_paths=owned_paths, checkpoint_root=Path(checkpoint_root), branch=branch, envelope_authority_preimage=authority, base=base, draft=draft, pr_body=pr_body or "", node_id=node_id)
                if prebuilt
                else prepare_publish_transaction(repo, owned_paths=owned_paths, checkpoint_root=Path(checkpoint_root), branch=branch, envelope_authority_preimage=authority, base=base, draft=draft, pr_body=pr_body or "", commit_message=commit_message, node_id=node_id)
            )
        transaction.resume()
        _crash_at("after_committed_checkpoint_before_broker_execute")
        envelope = _envelope_from_transaction(transaction, authority, repo)
        execution = broker_client.execute(BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, envelope, transaction.canonical_repository_identity, branch, transaction.committed_head_sha, transaction.owned_paths, base=base, draft=draft, pr_body=pr_body or "", adapter_worktree=str(Path(repo).resolve())))
        if execution.accepted:
            candidate = inspect_publish_resume_candidate(
                repo,
                checkpoint_root=Path(checkpoint_root),
                node_id=transaction.store.node_id,
            )
            if candidate.transaction is None or candidate.state == PublishTransactionState.CONFLICTED:
                raise RuntimeError("broker accepted publish without a recoverable transaction")
            transaction = candidate.transaction
            while transaction.state != PublishTransactionState.TERMINAL_SEALED:
                transaction.project(PublishTransactionState.ORDERED[PublishTransactionState.ORDERED.index(transaction.state) + 1])
    if not execution.accepted or execution.publish_result is None:
        return _blocked(execution.reason or execution.evidence.terminal_state, execution.evidence.evidence_reference)
    return {"status": "published", "branch": execution.publish_result.branch, "head_sha": execution.publish_result.head_sha, "pr_url": execution.publish_result.pr_url}
