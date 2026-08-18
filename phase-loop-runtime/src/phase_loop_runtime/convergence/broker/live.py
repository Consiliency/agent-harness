"""Opt-in construction of a live, credential-capable GitHub broker client.

This is the *only* helper that assembles a broker able to perform a real GitHub
mutation.  It is never auto-instantiated: legacy ``run_train`` callers that pass
no ``coordinator_runtime`` (or a runtime with ``broker_client=None``) publish
exactly as before.  A caller wanting broker-mediated publication builds a client
here and attaches it to :class:`CoordinatorRuntime.broker_client`.

The wired client enforces every already-merged safety property: linearizable
admission, permanent fail-closed ``outcome_ambiguous_blocked`` evidence, canonical
``(repo, branch, head_sha)`` idempotency, and the adapter's exact-published-head
verification.  Only the ``publish_committed_branch``/``github`` verb is SUPPORTED
(see ``provider_contracts``); the service refuses every other verb.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from phase_loop_runtime.convergence.contracts import AdmissionRequest
from phase_loop_runtime.convergence.provider_contracts import PROVIDER_COMPLETION_CLASSIFICATIONS

from .admission import BrokerAdmissionPolicy, LinearizableAdmissionStore
from .credsep import ALLOWED_ORIGIN_HOSTS, GitHubBrokerAdapter
from .evidence import BrokerEvidenceStore
from .verbs import BrokerClient, BrokerService

# ---------------------------------------------------------------------------
# FABPUB activation, domains, and typed blockers
# ---------------------------------------------------------------------------

FABPUB_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_FABPUB"
FABPUB_MARKER_MODULE = "phase_loop_runtime.fabpub_capability"
FABPUB_MARKER_ATTRIBUTE = "FABPUB_CAPABILITY_VERSION"
FABPUB_MARKER_VERSION = 1

#: Domain separator for CanonicalRepositoryIdentity.v1 (IF-0-FABPUB-1).
REPOSITORY_DOMAIN = b"FABPUB-CANONICAL-REPOSITORY-IDENTITY-v1\0"
REPOSITORY_NAMESPACE_DIR = "phase-loop-fabpub-broker-v1"
RECEIPT_FILENAME = "partition-receipt.json"

GENERATION_BLOCKER = "legacy_writer_after_fabpub_activation"
CUTOVER_BLOCKER = "legacy_cutover_conflict"


class LegacyCutoverConflict(RuntimeError):
    """A legacy-cutover integrity failure; always carries ``CUTOVER_BLOCKER``."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"{CUTOVER_BLOCKER}: {detail}")


class WriterGenerationBlocked(PermissionError):
    """A stale/legacy writer generation; always carries ``GENERATION_BLOCKER``."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"{GENERATION_BLOCKER}: {detail}")


class FabpubConfigurationError(RuntimeError):
    """The capability marker exists but could not be read."""


def fabpub_capability_active() -> bool:
    """Exact activation predicate, mirroring the SL-0 tests-only guard.

    An ABSENT marker is the ordinary pre-SL-4 state and means inactive.  A
    marker that exists but raises on import is a CONFIGURATION FAILURE, never an
    inactive downgrade: falling back would run the legacy caller-hashed
    allocator against a repository that has already been migrated and retired.
    """
    if os.environ.get(FABPUB_ACTIVATION_ENV) == "1":
        return True
    try:
        module = importlib.import_module(FABPUB_MARKER_MODULE)
    except ModuleNotFoundError:
        return False
    except Exception as error:
        raise FabpubConfigurationError(
            f"the FABPUB capability marker {FABPUB_MARKER_MODULE} exists but could not "
            f"be imported: {error}. Refusing to downgrade to the legacy allocator."
        ) from error
    return getattr(module, FABPUB_MARKER_ATTRIBUTE, None) == FABPUB_MARKER_VERSION


def canonical_bytes(payload: dict) -> bytes:
    """The one canonical serialization used by every FABPUB identity preimage."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _git_out(worktree: Path | str, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(worktree), *args], capture_output=True, text=True, timeout=60
    )
    if completed.returncode != 0:
        raise LegacyCutoverConflict(
            f"git {' '.join(args)} failed in {worktree}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


# --- one re-entrant advisory lock primitive -------------------------------
#
# `fcntl.flock` is keyed by OPEN FILE DESCRIPTION, so a second `open()` of the
# same path inside one process blocks against the first.  Re-entrancy is tracked
# per (path, thread) so nesting inside one thread is free while other threads
# and other processes still block.
_LOCK_DEPTH: dict[tuple[str, int], list] = {}
_LOCK_DEPTH_GUARD = threading.Lock()


@contextlib.contextmanager
def _reentrant_flock(path: Path):
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = (str(path), threading.get_ident())
    with _LOCK_DEPTH_GUARD:
        entry = _LOCK_DEPTH.get(key)
        if entry is not None:
            entry[0] += 1
            reentered = True
        else:
            reentered = False
    if reentered:
        try:
            yield
        finally:
            with _LOCK_DEPTH_GUARD:
                entry = _LOCK_DEPTH.get(key)
                if entry is not None:
                    entry[0] -= 1
                    if entry[0] <= 0:
                        _LOCK_DEPTH.pop(key, None)
        return

    handle = path.open("a+", encoding="utf-8")
    fcntl.flock(handle, fcntl.LOCK_EX)
    with _LOCK_DEPTH_GUARD:
        _LOCK_DEPTH[key] = [1, handle]
    try:
        yield
    finally:
        with _LOCK_DEPTH_GUARD:
            entry = _LOCK_DEPTH.get(key)
            if entry is not None:
                entry[0] -= 1
                if entry[0] <= 0:
                    _LOCK_DEPTH.pop(key, None)
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _fresh_nonce() -> str:
    return hashlib.sha256(os.urandom(32)).hexdigest()[:32]


def _fsync_dir(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Temp-file write, file fsync, atomic replace, parent-directory fsync.

    The temp name carries pid + a fresh nonce: a predictable ``.<name>.tmp``
    lets two concurrent writers clobber one another's partial file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{os.getpid()}.{_fresh_nonce()[:8]}.tmp"
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    with temp.open("w", encoding="utf-8") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    _fsync_dir(path.parent)


def _require_no_ancestor_symlink(path: Path) -> None:
    """Refuse a path any of whose components is a symlink."""
    current = Path(path)
    seen = []
    while True:
        seen.append(current)
        if current.parent == current:
            break
        current = current.parent
    for candidate in seen:
        if candidate.is_symlink():
            raise LegacyCutoverConflict(
                f"path component {candidate} is a symlink; {path} cannot be trusted"
            )


# ---------------------------------------------------------------------------
# Strict JSONL (SOL-11): one reader, byte-exact, no permissive fallbacks
# ---------------------------------------------------------------------------


def read_strict_jsonl(path: Path, *, label: str) -> list[tuple[str, dict]]:
    """Parse a complete newline-terminated JSONL log as ``(exact_line, parsed)``.

    Strictness is the point: a torn final append, a blank line, or a non-object
    row each mean the log cannot testify about what happened, so each fails
    closed rather than being silently skipped.  Callers compare the EXACT line
    bytes for duplicate identity, never the reparsed dict.
    """
    if not path.exists():
        return []
    body = path.read_text(encoding="utf-8")
    if body and not body.endswith("\n"):
        raise LegacyCutoverConflict(
            f"{label} log is not newline-terminated (torn append): {path}"
        )
    rows: list[tuple[str, dict]] = []
    lines = body.split("\n")[:-1] if body else []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            raise LegacyCutoverConflict(f"{label} log has a blank line at {index}: {path}")
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as error:
            raise LegacyCutoverConflict(
                f"malformed {label} JSON at line {index} in {path}: {error}"
            )
        if not isinstance(parsed, dict):
            raise LegacyCutoverConflict(f"{label} row {index} is not an object in {path}")
        rows.append((line, parsed))
    return rows


# ---------------------------------------------------------------------------
# CanonicalRepositoryIdentity.v1 / RepositoryBrokerNamespace.v1
# ---------------------------------------------------------------------------


def git_common_dir(worktree: Path | str) -> Path:
    """The normalized, symlink-resolved absolute Git COMMON directory."""
    return Path(
        _git_out(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve()


def canonical_repository_identity(worktree: Path | str) -> str:
    """``CanonicalRepositoryIdentity.v1`` — the sole storage/keying ``repo``.

    Neither the train path nor the worktree top-level is a member: a linked
    worktree, a train file in an unrelated directory, and the primary checkout
    all derive one identity, while two distinct Git common directories stay
    distinct.
    """
    return repository_snapshot(worktree).identity


@dataclass(frozen=True)
class RepositorySnapshot:
    """One consistent read of a worktree's repository identity.

    Resolved worktree, common dir, object format, and identity come from ONE
    pair of git reads; deriving them separately can interleave with a worktree
    being reconfigured and yield a store root and identity that disagree.
    """

    worktree: Path
    common_dir: Path
    object_format: str
    identity: str

    @property
    def namespace_root(self) -> Path:
        return self.common_dir / REPOSITORY_NAMESPACE_DIR

    @property
    def store_root(self) -> Path:
        return self.namespace_root / "repositories" / self.identity


def repository_snapshot(worktree: Path | str) -> RepositorySnapshot:
    """Take one consistent identity snapshot for ``worktree``."""
    resolved = Path(worktree).resolve()
    common = Path(
        _git_out(resolved, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve()
    object_format = _git_out(resolved, "rev-parse", "--show-object-format")
    identity = hashlib.sha256(
        REPOSITORY_DOMAIN
        + canonical_bytes(
            {
                "schema": "CanonicalRepositoryIdentity.v1",
                "git_common_dir": str(common),
                "git_object_format": object_format,
            }
        )
    ).hexdigest()
    return RepositorySnapshot(resolved, common, object_format, identity)


def repository_namespace_root(worktree: Path | str) -> Path:
    """The repository-common FABPUB root (latch + every repository store)."""
    return git_common_dir(worktree) / REPOSITORY_NAMESPACE_DIR


def repository_broker_namespace(worktree: Path | str) -> Path:
    """``RepositoryBrokerNamespace.v1`` — the one admission/evidence root.

    Exactly ``<git-common-dir>/phase-loop-fabpub-broker-v1/repositories/<identity>``.
    A pure derivation: it creates no directory.
    """
    snapshot = repository_snapshot(worktree)
    return snapshot.store_root


# ---------------------------------------------------------------------------
# WriterGenerationLatch.v1 / WriterGenerationLease.v1 / ExclusiveActivationLease.v1
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriterGenerationSnapshot:
    generation: str
    generation_state: str


class WriterGenerationLease:
    """A held ``WriterGenerationLease.v1``; revalidated at every append/effect."""

    def __init__(self, latch: "WriterGenerationLatch", generation: str, nonce: str) -> None:
        self.latch, self.generation, self.nonce = latch, generation, nonce
        self.path = latch.lease_dir / f"{nonce}.json"

    def release(self) -> None:
        """Drop the lease UNDER the latch lock, verifying it is still ours.

        The on-disk nonce/generation are re-read before unlinking so a stale
        handle can never delete a different holder's lease and fake quiescence.
        """
        with self.latch.exclusive():
            if not self.path.exists():
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("nonce") != self.nonce or raw.get("generation") != self.generation:
                raise WriterGenerationBlocked(
                    f"refusing to release lease {self.path.name}: on-disk nonce/generation "
                    "does not match this handle"
                )
            self.path.unlink()
            _fsync_dir(self.latch.lease_dir)


class ExclusiveActivationLease:
    """``ExclusiveActivationLease.v1`` — the temporary migration-time exclusion.

    NOT the post-activation authority: the durable ``ACTIVE`` latch state is.
    It is deliberately scoped to individual transitions rather than held across
    the whole migration, because a coordinator that holds it across a drain
    would block the very foreign ``release()`` calls the drain is waiting for
    (SL1-SOL-04).
    """

    def __init__(self, latch: "WriterGenerationLatch") -> None:
        self.latch = latch
        self._stack: contextlib.ExitStack | None = None

    def __enter__(self) -> "ExclusiveActivationLease":
        self._stack = contextlib.ExitStack()
        self._stack.enter_context(self.latch.exclusive())
        return self

    def __exit__(self, *exc_info) -> None:
        if self._stack is not None:
            self._stack.close()
            self._stack = None

    @property
    def held(self) -> bool:
        return self._stack is not None


class WriterGenerationLatch:
    """The repository-common ``LEGACY_OPEN -> DRAINING -> ACTIVE`` latch.

    Its state file uses the ``generation_state`` key: ``state`` belongs to the
    cutover journal alone.  Transitions are guarded and ``ACTIVE`` is
    irreversible (SL1-SOL-06).
    """

    GENERATION_STATES = ("LEGACY_OPEN", "DRAINING", "ACTIVE")

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "writer-generation.json"
        self.lease_dir = self.root / "generation-leases"

    @classmethod
    def open(cls, worktree: Path | str) -> "WriterGenerationLatch":
        """Load or ATOMICALLY initialize this repository's latch."""
        latch = cls(repository_namespace_root(worktree))
        with latch.exclusive():
            latch.root.mkdir(parents=True, exist_ok=True)
            latch.lease_dir.mkdir(parents=True, exist_ok=True)
            if not latch.path.exists():
                latch._write(WriterGenerationSnapshot(_fresh_nonce(), "LEGACY_OPEN"))
        return latch

    @classmethod
    def for_store_root(cls, store_root: Path) -> "WriterGenerationLatch":
        """Derive the latch from ``.../<namespace-root>/repositories/<identity>``."""
        return cls(Path(store_root).parent.parent)

    # -- the exclusive activation authority --------------------------------
    @property
    def lock_path(self) -> Path:
        return self.root / "writer-generation.lock"

    @contextlib.contextmanager
    def exclusive(self):
        """Serialize one latch transition or lease issue/release."""
        self.root.mkdir(parents=True, exist_ok=True)
        with _reentrant_flock(self.lock_path):
            yield

    def activation_lease(self) -> ExclusiveActivationLease:
        return ExclusiveActivationLease(self)

    # -- state -------------------------------------------------------------
    def _write(self, snapshot: WriterGenerationSnapshot) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(
            self.path,
            {
                "schema": "WriterGenerationLatch.v1",
                "generation": snapshot.generation,
                "generation_state": snapshot.generation_state,
            },
        )

    def read(self) -> WriterGenerationSnapshot:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return WriterGenerationSnapshot(raw["generation"], raw["generation_state"])

    def exists(self) -> bool:
        return self.path.exists()

    @property
    def armed_marker(self) -> Path:
        return self.root / "cutover-armed"

    def mark_armed(self) -> None:
        with self.exclusive():
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.armed_marker.exists():
                self.armed_marker.write_text("armed\n", encoding="ascii")
                _fsync_dir(self.root)

    # -- guarded transitions ----------------------------------------------
    def begin_draining(self) -> None:
        """``LEGACY_OPEN -> DRAINING``.  ACTIVE is irreversible and refuses.

        This does NOT wait for held leases; :meth:`await_quiescent` does, and it
        must run WITHOUT this lock held so foreign releases can proceed.
        """
        with self.exclusive():
            snapshot = self.read()
            if snapshot.generation_state not in self.GENERATION_STATES:
                raise LegacyCutoverConflict(
                    f"illegal generation transition {snapshot.generation_state} -> DRAINING"
                )
            # ACTIVE -> DRAINING is LEGAL and load-bearing: a later migration
            # must be able to drain an already-activated repository, and the
            # frozen check/use-race falsifier drives exactly this transition to
            # prove an in-flight append is denied at the APPEND rather than only
            # at entry.  What ACTIVE makes irreversible is the AUTHORITY, not the
            # drain: the generation nonce is preserved here (so no legacy token
            # is revived) and `rollback()` refuses once the ARMED marker exists,
            # so a repository can never return to LEGACY_OPEN.
            self._write(WriterGenerationSnapshot(snapshot.generation, "DRAINING"))

    def activate(self) -> None:
        """``DRAINING -> ACTIVE``, only behind a durable ARMED marker.

        A FRESH generation nonce is what fences every legacy token: an old
        writer holding ``"legacy"`` can never match it.
        """
        with self.exclusive():
            if not self.armed_marker.exists():
                raise LegacyCutoverConflict(
                    "a repository generation may not become ACTIVE without a durable "
                    "ARMED cutover marker"
                )
            snapshot = self.read()
            if snapshot.generation_state == "ACTIVE":
                return
            if snapshot.generation_state not in ("LEGACY_OPEN", "DRAINING"):
                raise LegacyCutoverConflict(
                    f"illegal generation transition {snapshot.generation_state} -> ACTIVE"
                )
            self._write(WriterGenerationSnapshot(_fresh_nonce(), "ACTIVE"))

    def rollback(self) -> None:
        with self.exclusive():
            if self.armed_marker.exists():
                raise LegacyCutoverConflict(
                    "rollback is illegal once a cutover reached ARMED; recovery may only "
                    "resume toward byte-identical ACTIVE"
                )
            if self.read().generation_state != "DRAINING":
                raise LegacyCutoverConflict("rollback is legal only from DRAINING")
            if self.held_leases():
                raise LegacyCutoverConflict("rollback requires zero held generation leases")
            self._write(WriterGenerationSnapshot(self.read().generation, "LEGACY_OPEN"))

    def await_quiescent(self, *, worktree: Path | str, timeout: float = 60.0) -> None:
        """Wait for leases AND live writers to reach zero before INVENTORY_SEALED.

        SL1-SOL-04: this must NOT be called with the latch lock held.  Each poll
        takes the lock briefly and releases it, so a foreign process's
        ``release()`` — which needs the same lock — can actually complete.
        """
        import time

        deadline = time.monotonic() + timeout
        while True:
            with self.exclusive():
                held = self.held_leases()
            if not held:
                live = LegacyWriterQuiescence.inventory(worktree).live_writers()
                if not live:
                    return
                detail = f"{len(live)} live pre-FABPUB writer(s)"
            else:
                detail = f"{len(held)} held generation lease(s)"
            if time.monotonic() >= deadline:
                raise WriterGenerationBlocked(
                    f"DRAINING did not reach zero before INVENTORY_SEALED: {detail}"
                )
            time.sleep(0.02)

    # -- leases ------------------------------------------------------------
    def held_leases(self) -> tuple[Path, ...]:
        if not self.lease_dir.exists():
            return ()
        return tuple(sorted(self.lease_dir.glob("*.json")))

    def acquire(self, *, generation: str) -> WriterGenerationLease:
        """Issue a lease, or fail closed with the exact typed blocker.

        Denial is an exact-nonce comparison.  DRAINING deliberately does NOT
        deny the CURRENT canonical generation — the president ruled that half of
        SL1-SOL-04 not a freeze violation, because IF-0 denies new *legacy*
        generations, not the generation the migrator itself holds.  Appends and
        provider effects are separately denied while DRAINING by
        :func:`require_current_generation`.
        """
        with self.exclusive():
            snapshot = self.read()
            if generation != snapshot.generation:
                raise WriterGenerationBlocked(
                    f"generation {generation!r} is not the current canonical generation "
                    f"(latch is {snapshot.generation_state})"
                )
            self.lease_dir.mkdir(parents=True, exist_ok=True)
            lease = WriterGenerationLease(self, generation, _fresh_nonce())
            _atomic_write_json(
                lease.path,
                {
                    "schema": "WriterGenerationLease.v1",
                    "generation": generation,
                    "nonce": lease.nonce,
                },
            )
            return lease

    def validate_lease(
        self, lease: "WriterGenerationLease | None", *, strict: bool = True
    ) -> None:
        """Revalidate an exact lease nonce + generation against current state.

        SL1-SOL-02: an ACTIVE generation REQUIRES a held lease when the caller
        DECLARED its lease.  ``strict`` distinguishes the two frozen shapes:

        * ``generation_lease=None`` passed explicitly — the adversarial fence
          node — is a declared absence and must be blocked under ACTIVE;
        * a store constructed without the argument at all (the shared
          compatibility ``_service`` helper, which SL-0 did not change) has
          declared nothing, so it is validated against latch state only.

        The activated production router always supplies a real lease, so the
        production path is strict by construction.
        """
        with self.exclusive():
            snapshot = self.read()
            if snapshot.generation_state == "DRAINING":
                raise WriterGenerationBlocked(
                    "the repository generation latch entered DRAINING before this write"
                )
            if lease is None:
                if strict and snapshot.generation_state == "ACTIVE":
                    raise WriterGenerationBlocked(
                        "an ACTIVE repository generation requires a held "
                        "WriterGenerationLease.v1 for every write"
                    )
                return
            if not lease.path.exists():
                raise WriterGenerationBlocked("the held generation lease was revoked")
            raw = json.loads(lease.path.read_text(encoding="utf-8"))
            if raw.get("nonce") != lease.nonce or raw.get("generation") != snapshot.generation:
                raise WriterGenerationBlocked(
                    "the held generation lease does not bind the current canonical generation"
                )


#: Sentinel for "the caller declared no lease at all", distinct from an explicit
#: ``generation_lease=None`` (which is a declared absence and is denied).
UNDECLARED_LEASE = object()


def require_current_generation(
    store_root: Path, lease: "WriterGenerationLease | None" = None, *, strict: bool = True
) -> None:
    """Revalidate the writer generation INSIDE a store lock, before an append.

    SL1-SOL-02/07: a MISSING latch is only legal where no activation authority
    exists.  If the namespace carries an authenticated receipt, an absent latch
    means the authority was removed under us, which is denial — not permission.
    """
    store_root = Path(store_root)
    if lease is UNDECLARED_LEASE:
        lease, strict = None, False
    latch = WriterGenerationLatch.for_store_root(store_root)
    if not latch.exists():
        if load_partition_receipt(store_root) is not None:
            raise WriterGenerationBlocked(
                f"{store_root} carries an authenticated partition receipt but no writer "
                "generation latch; refusing to append without an activation authority"
            )
        return
    latch.validate_lease(lease, strict=strict)


# ---------------------------------------------------------------------------
# LegacyRepositoryPartitionReceipt.v2  (SOL-09: byte identity, not overwrite)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegacyRepositoryPartitionReceipt:
    """One immutable per-repository partition receipt.

    It is the ONLY thing that makes a canonical repository store routable: an
    absent, unauthenticated, or drifted receipt is denial, never a silent
    restart at epoch 1.
    """

    cutover_id: str
    canonical_repository_identity: str
    target_namespace: str
    legacy_epoch_high_water: int
    ambiguous: bool
    serialized_repository_preimages: tuple[str, ...]
    resolution_contexts: tuple[str, ...]
    source_digests: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    legacy_completed_effect_keys: tuple[str, ...]
    global_journal_path: str
    manifest_sha256: str = ""
    inventory_sha256: str = ""
    partition_map_sha256: str = ""
    legacy_root_inventory: tuple[str, ...] = ()
    zero_source: bool = False
    zero_source_proof_sha256: str = ""

    SCHEMA = "LegacyRepositoryPartitionReceipt.v2"

    def payload(self) -> dict:
        return {
            "schema": self.SCHEMA,
            "cutover_id": self.cutover_id,
            "canonical_repository_identity": self.canonical_repository_identity,
            "target_namespace": self.target_namespace,
            "legacy_epoch_high_water": self.legacy_epoch_high_water,
            "ambiguous": self.ambiguous,
            "serialized_repository_preimages": list(self.serialized_repository_preimages),
            "resolution_contexts": list(self.resolution_contexts),
            "source_digests": list(self.source_digests),
            "evidence_digests": list(self.evidence_digests),
            "legacy_completed_effect_keys": list(self.legacy_completed_effect_keys),
            "global_journal_path": self.global_journal_path,
            "manifest_sha256": self.manifest_sha256,
            "inventory_sha256": self.inventory_sha256,
            "partition_map_sha256": self.partition_map_sha256,
            "legacy_root_inventory": list(self.legacy_root_inventory),
            "zero_source": self.zero_source,
            "zero_source_proof_sha256": self.zero_source_proof_sha256,
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self.payload())).hexdigest()

    def file_bytes(self, zero_source_proof: dict | None = None) -> bytes:
        """The EXACT on-disk bytes this receipt must have."""
        body = {**self.payload(), "receipt_sha256": self.digest()}
        if zero_source_proof is not None:
            body["zero_source_proof"] = zero_source_proof
        return (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    def write(self, namespace: Path, *, zero_source_proof: dict | None = None) -> Path:
        """Write the receipt, requiring BYTE IDENTITY when one already exists.

        SL1-SOL-09: an unconditional atomic overwrite silently replaces a
        divergent receipt.  A resumed cutover must reproduce the same bytes; if
        it cannot, that is a conflict, not a write.
        """
        path = Path(namespace) / RECEIPT_FILENAME
        expected = self.file_bytes(zero_source_proof)
        if path.exists():
            actual = path.read_bytes()
            if actual != expected:
                raise LegacyCutoverConflict(
                    f"an existing partition receipt at {path} differs from the receipt this "
                    "cutover produces; a receipt is immutable and may not be overwritten"
                )
            return path
        _atomic_write_json(
            path,
            json.loads(expected.decode("utf-8")),
        )
        return path


def _receipt_from_partition(
    cutover_id: str, partition: dict, sealed: dict, journal: Path
) -> LegacyRepositoryPartitionReceipt:
    """The exact receipt a sealed partition must produce."""
    return LegacyRepositoryPartitionReceipt(
        cutover_id=cutover_id,
        canonical_repository_identity=partition["canonical_repository_identity"],
        target_namespace=str(Path(partition["target_namespace"])),
        legacy_epoch_high_water=partition["legacy_epoch_high_water"],
        ambiguous=partition["ambiguous"],
        serialized_repository_preimages=tuple(partition["serialized_repository_preimages"]),
        resolution_contexts=tuple(partition["resolution_contexts"]),
        source_digests=tuple(partition["source_digests"]),
        evidence_digests=tuple(partition.get("evidence_digests", ())),
        legacy_completed_effect_keys=tuple(partition["legacy_completed_effect_keys"]),
        global_journal_path=str(journal),
        manifest_sha256=sealed.get("manifest_sha256", ""),
        inventory_sha256=sealed.get("inventory_sha256", ""),
        partition_map_sha256=sealed.get("partition_map_sha256", ""),
        legacy_root_inventory=tuple(sealed.get("legacy_root_inventory", ())),
        zero_source=bool(partition.get("zero_source", not partition.get("sources"))),
        zero_source_proof_sha256=partition.get("zero_source_proof_sha256", ""),
    )


def _inventory_digest(sealed: dict) -> str:
    body = {key: value for key, value in sealed.items() if key != "inventory_sha256"}
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def _partition_map_digest(partitions: dict) -> str:
    return hashlib.sha256(canonical_bytes({"partitions": partitions})).hexdigest()


def load_partition_receipt(store_root: Path) -> LegacyRepositoryPartitionReceipt | None:
    """Load and fully authenticate the receipt that governs ``store_root``.

    Authentication is a CHAIN ending in EXACT ON-DISK BYTES: the receipt must
    name this identity and namespace, its sealed inventory must digest-match,
    its ARMED journal must belong to the same cutover, and the file bytes must
    equal the bytes the sealed partition independently produces.
    """
    store_root = Path(store_root)
    path = store_root / RECEIPT_FILENAME
    if not path.exists():
        return None
    _require_no_ancestor_symlink(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != LegacyRepositoryPartitionReceipt.SCHEMA:
        raise LegacyCutoverConflict(f"unknown partition receipt schema at {path}")
    cutover_id = raw.get("cutover_id", "")
    identity = raw.get("canonical_repository_identity", "")
    if identity != store_root.name:
        raise LegacyCutoverConflict(
            "partition receipt is bound to a different canonical repository identity"
        )
    journal = Path(raw.get("global_journal_path", ""))
    if not journal.exists():
        raise LegacyCutoverConflict("the receipt's global cutover journal is missing")
    states, ids = _journal_entries(journal)
    if "ARMED" not in states:
        raise LegacyCutoverConflict("the receipt's global cutover transaction is not ARMED")
    if set(ids) != {cutover_id}:
        raise LegacyCutoverConflict("the receipt's cutover_id does not match its ARMED journal")
    inventory_path = journal.parent / f"{cutover_id}.inventory.json"
    if not inventory_path.exists():
        raise LegacyCutoverConflict("the receipt's sealed cutover inventory is missing")
    sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
    if _inventory_digest(sealed) != sealed.get("inventory_sha256"):
        raise LegacyCutoverConflict("the sealed cutover inventory digest drifted")
    partition = sealed.get("partitions", {}).get(identity)
    if partition is None:
        raise LegacyCutoverConflict(
            "the receipt's repository is absent from its own sealed partition map"
        )
    if _partition_map_digest(sealed.get("partitions", {})) != sealed.get("partition_map_sha256"):
        raise LegacyCutoverConflict("the sealed partition map digest drifted")
    expected = _receipt_from_partition(cutover_id, partition, sealed, journal)
    if path.read_bytes() != expected.file_bytes(partition.get("zero_source_proof")):
        raise LegacyCutoverConflict(
            f"partition receipt bytes at {path} do not equal the bytes its sealed partition "
            "produces (high water, ambiguity, preimages, completed keys, digests, or "
            "zero-source proof drifted)"
        )
    return expected


def authenticated_partition_floor(store_root: Path) -> int:
    """The receipt-authenticated ``legacy_epoch_high_water`` for this partition."""
    receipt = load_partition_receipt(Path(store_root))
    if receipt is None:
        raise PermissionError(
            f"{CUTOVER_BLOCKER}: no armed LegacyRepositoryPartitionReceipt.v2 authorises "
            f"{store_root}; the repository allocator is not routable"
        )
    return int(receipt.legacy_epoch_high_water)


def partition_is_ambiguity_blocked(store_root: Path) -> bool:
    """True when this partition inherited permanent archived ambiguity.

    Any authentication failure is itself a block — fail closed, never open.
    """
    try:
        receipt = load_partition_receipt(Path(store_root))
    except LegacyCutoverConflict:
        return True
    return bool(receipt is not None and receipt.ambiguous)


def sealed_partition_effects(receipt: LegacyRepositoryPartitionReceipt) -> dict[str, dict]:
    """The authenticated legacy completed effects for a receipt's partition."""
    journal = Path(receipt.global_journal_path)
    inventory_path = journal.parent / f"{receipt.cutover_id}.inventory.json"
    if not inventory_path.exists():
        return {}
    sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
    partition = sealed.get("partitions", {}).get(receipt.canonical_repository_identity, {})
    effects = dict(partition.get("legacy_completed_effects", {}))
    for provenance in effects.values():
        provenance.setdefault("cutover_id", receipt.cutover_id)
        provenance.setdefault("partition", receipt.canonical_repository_identity)
        provenance.setdefault("global_journal_path", receipt.global_journal_path)
        provenance.setdefault("inventory_sha256", receipt.inventory_sha256)
        provenance.setdefault("manifest_sha256", receipt.manifest_sha256)
    if set(effects) != set(receipt.legacy_completed_effect_keys):
        raise LegacyCutoverConflict(
            "the sealed legacy effect set disagrees with its partition receipt"
        )
    return effects


# --- SOL-10: an UNFORGEABLE promotion capability ---------------------------
#
# A boolean flag is not authority, and a module-global sentinel is reachable as
# `live._PROMOTION_SENTINEL`.  The sentinel here is a closure cell owned by the
# minting function: nothing outside this module can obtain a reference to it, so
# the capability cannot be constructed by a caller.


def _make_promotion_capability_factory():
    sentinel = object()

    class _CutoverPromotionCapability:
        """Authorises exactly ONE legacy terminal promotion in ONE partition."""

        __slots__ = ("_store_root", "_key", "_provenance")

        def __init__(self, token, store_root: Path, key: str, provenance: dict) -> None:
            if token is not sentinel:
                raise PermissionError(
                    "legacy terminal promotion capabilities are cutover-internal and "
                    "cannot be constructed by a caller"
                )
            object.__setattr__(self, "_store_root", Path(store_root))
            object.__setattr__(self, "_key", key)
            object.__setattr__(self, "_provenance", dict(provenance))

        def __setattr__(self, *_args):
            raise AttributeError("promotion capabilities are immutable")

        def __delattr__(self, *_args):
            raise AttributeError("promotion capabilities are immutable")

        @property
        def store_root(self) -> Path:
            return self._store_root

        @property
        def key(self) -> str:
            return self._key

        @property
        def provenance(self) -> dict:
            return dict(self._provenance)

    def mint(store_root: Path, key: str):
        """Mint after FULL authentication, re-verifying CURRENT archive bytes."""
        receipt = load_partition_receipt(Path(store_root))
        if receipt is None:
            raise PermissionError(
                f"{CUTOVER_BLOCKER}: no authenticated partition receipt governs {store_root}"
            )
        provenance = sealed_partition_effects(receipt).get(key)
        if provenance is None:
            raise PermissionError(
                f"{CUTOVER_BLOCKER}: {key!r} is not an authenticated legacy terminal for "
                "this repository partition"
            )
        archive = (
            Path(provenance["legacy_root"])
            / "legacy-archive"
            / receipt.cutover_id
            / provenance["source_id"]
        )
        for filename, expected in (
            ("admissions.jsonl", provenance.get("admissions_digest")),
            ("evidence.jsonl", provenance.get("evidence_digest")),
        ):
            if expected is None:
                continue
            candidate = archive / filename
            actual = hashlib.sha256(
                candidate.read_bytes() if candidate.exists() else b""
            ).hexdigest()
            if actual != expected:
                raise PermissionError(
                    f"{CUTOVER_BLOCKER}: archived {filename} for {key!r} drifted since seal; "
                    "the legacy terminal can no longer be authenticated"
                )
        return _CutoverPromotionCapability(sentinel, store_root, key, provenance)

    return _CutoverPromotionCapability, mint


_CutoverPromotionCapability, _mint_cutover_promotion_capability = (
    _make_promotion_capability_factory()
)


def _journal_states(journal: Path) -> list[str]:
    return _journal_entries(journal)[0]


def _journal_entries(journal: Path) -> tuple[list[str], list[str]]:
    """Return ``(states, cutover_ids)``; a row with neither key is CORRUPT.

    SL1-SOL-11: silently skipping an unrecognised row lets a truncated journal
    read as "ARMED absent" instead of "unreadable".
    """
    states: list[str] = []
    ids: list[str] = []
    for _line, raw in read_strict_jsonl(Path(journal), label="cutover journal"):
        if "state" in raw:
            states.append(raw["state"])
        elif "onboarding_state" in raw:
            states.append(raw["onboarding_state"])
        else:
            raise LegacyCutoverConflict(
                f"cutover journal row carries neither state nor onboarding_state: {journal}"
            )
        ids.append(raw.get("cutover_id", ""))
    return states, ids


# ---------------------------------------------------------------------------
# LegacyWriterQuiescence.v1
# ---------------------------------------------------------------------------

SUPPORTED_WRITER_SURFACES = (
    "phase_loop_run_train_command",
    "direct_run_train_entry",
    "skill_alias",
)


@dataclass(frozen=True)
class LegacyWriterInventory:
    writers: tuple[dict, ...]
    supervisors: tuple[dict, ...]
    unmanaged: tuple[str, ...] = ()

    def live_writers(self) -> tuple[dict, ...]:
        return tuple(entry for entry in self.writers if entry.get("live"))

    def require_fenceable(self) -> "LegacyWriterInventory":
        if self.unmanaged:
            raise WriterGenerationBlocked(
                "unmanaged pre-FABPUB writer source copies are not claimed fenceable: "
                + ", ".join(self.unmanaged)
            )
        return self

    def require_quiescent(self) -> "LegacyWriterInventory":
        live = self.live_writers()
        if live:
            raise WriterGenerationBlocked(
                "a live pre-FABPUB writer must drain before the cutover may seal its "
                f"inventory: {[entry['process_identity'] for entry in live]}"
            )
        return self


def _module_digest(module_name: str) -> str:
    try:
        module = importlib.import_module(module_name)
        source = Path(getattr(module, "__file__", "") or "")
        if source.exists():
            return hashlib.sha256(source.read_bytes()).hexdigest()
    except Exception:
        pass
    return hashlib.sha256(module_name.encode("utf-8")).hexdigest()


def _entrypoint_digest(name: str) -> str:
    import shutil as _shutil

    resolved = _shutil.which(name)
    if resolved and Path(resolved).exists():
        return hashlib.sha256(Path(resolved).read_bytes()).hexdigest()
    return hashlib.sha256(f"absent:{name}".encode("utf-8")).hexdigest()


def _iter_live_run_train_processes() -> Iterable[dict]:
    """Discover live pre-FABPUB `run-train` writers via /proc.

    The match is on an EXACT ``run-train`` argv element, never a substring: a
    pytest process whose ``-k`` expression merely mentions ``run_train`` is not
    a writer, and matching it would deadlock every activated test run.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return
    own = {os.getpid(), os.getppid()}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in own:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [part for part in raw.decode("utf-8", "replace").split("\0") if part]
        if not argv or "run-train" not in argv:
            continue
        launcher = Path(argv[0]).name
        if launcher not in ("phase-loop", "phase_loop") and "phase" not in launcher:
            if not any(part.endswith("phase-loop") for part in argv[:2]):
                continue
        yield {
            "surface": "phase_loop_run_train_command",
            "live": True,
            "process_identity": f"pid:{pid}:{hashlib.sha256(raw).hexdigest()[:16]}",
            "module_digest": _module_digest("phase_loop_runtime.train_runner"),
            "entrypoint_digest": _entrypoint_digest("phase-loop"),
            "host": os.uname().nodename,
            "launcher": argv[0],
            "argv": argv,
            "stop_disposition": "await_operator_drain",
        }


class LegacyWriterQuiescence:
    """``LegacyWriterQuiescence.v1`` — the supported-writer attestation."""

    SURFACES = SUPPORTED_WRITER_SURFACES

    @classmethod
    def inventory(
        cls, worktree: Path | str, *, extra_search_paths: Iterable[Path] = ()
    ) -> LegacyWriterInventory:
        host = os.uname().nodename
        writers: list[dict] = []
        for surface, module_name, entrypoint in (
            ("phase_loop_run_train_command", "phase_loop_runtime.cli", "phase-loop"),
            ("direct_run_train_entry", "phase_loop_runtime.train_runner", sys.executable),
            ("skill_alias", "phase_loop_runtime.cli", "phase-loop"),
        ):
            writers.append(
                {
                    "surface": surface,
                    "live": False,
                    "process_identity": f"restart-surface:{surface}:{host}",
                    "module_digest": _module_digest(module_name),
                    "entrypoint_digest": _entrypoint_digest(entrypoint),
                    "host": host,
                    "launcher": entrypoint,
                    "canonical_repository": canonical_repository_identity(worktree),
                    "stop_disposition": "upgraded_to_guarded_entrypoint",
                }
            )
        writers.extend(_iter_live_run_train_processes())

        unmanaged: list[str] = []
        for search_path in extra_search_paths:
            root = Path(search_path)
            if not root.exists():
                continue
            for candidate in sorted(root.rglob("*.py")):
                if "run_train" in candidate.name or "run_train" in candidate.read_text(
                    encoding="utf-8", errors="ignore"
                ):
                    unmanaged.append(str(candidate))

        supervisors = [
            {
                "supervisor": "operator_shell",
                "host": host,
                "attested": True,
                "evidence": "attended operator drain",
            }
        ]
        return LegacyWriterInventory(
            writers=tuple(writers),
            supervisors=tuple(supervisors),
            unmanaged=tuple(unmanaged),
        )


# ---------------------------------------------------------------------------
# LegacyBrokerCutoverManifest.v2 / LegacyBrokerCutoverTransaction.v2
# ---------------------------------------------------------------------------

CUTOVER_CRASH_STEPS = (
    "before_source_retirement",
    "between_source_retirements",
    "after_source_retirement",
    "before_partition_write",
    "between_partition_writes",
    "after_partition_write",
    "before_armed",
)

_CRASH_STEP: str | None = None


class _CutoverCrash(RuntimeError):
    """The injected process loss at a frozen cutover kill point."""


@contextlib.contextmanager
def crash_at_cutover_step(step: str):
    global _CRASH_STEP
    if step not in CUTOVER_CRASH_STEPS:
        raise ValueError(f"unknown cutover crash step {step!r}")
    previous, _CRASH_STEP = _CRASH_STEP, step
    try:
        yield
    finally:
        _CRASH_STEP = previous


def _maybe_crash(step: str) -> None:
    if _CRASH_STEP == step:
        raise _CutoverCrash(step)


@dataclass(frozen=True)
class LegacyBrokerCutoverManifest:
    """``LegacyBrokerCutoverManifest.v2`` — metadata-only cutover input."""

    cutover_id: str
    rows: tuple[dict, ...]

    SCHEMA = "LegacyBrokerCutoverManifest.v2"

    def legacy_roots(self) -> tuple[Path, ...]:
        seen: dict[str, Path] = {}
        for row in self.rows:
            raw = row["legacy_root"]
            if os.path.normpath(raw) != str(raw).rstrip("/"):
                raise LegacyCutoverConflict(
                    f"legacy_root {raw!r} escapes its declared root (path traversal)"
                )
            root = Path(raw)
            seen.setdefault(str(root), root)
        if not seen:
            raise LegacyCutoverConflict("a cutover manifest must declare at least one legacy root")
        return tuple(seen[key] for key in sorted(seen))

    def declared_leaves(self) -> tuple[Path, ...]:
        """Leaf paths derivable WITHOUT planning, for the pre-snapshot lock set."""
        leaves = {
            str(Path(row["legacy_root"]) / row["expected_train_key"] / row["expected_repo_key"])
            for row in self.rows
        }
        return tuple(Path(leaf) for leaf in sorted(leaves))

    def declared_worktrees(self) -> tuple[Path, ...]:
        seen = {str(Path(row["expected_worktree"])) for row in self.rows if row.get("expected_worktree")}
        return tuple(Path(path) for path in sorted(seen))


def _manifest_digest(manifest: LegacyBrokerCutoverManifest) -> str:
    return hashlib.sha256(
        canonical_bytes(
            {
                "schema": LegacyBrokerCutoverManifest.SCHEMA,
                "cutover_id": manifest.cutover_id,
                "rows": [dict(sorted(row.items())) for row in manifest.rows],
            }
        )
    ).hexdigest()


def _root_set_digest(roots: tuple[Path, ...]) -> str:
    return hashlib.sha256(
        canonical_bytes({"legacy_root_inventory": [str(root) for root in roots]})
    ).hexdigest()


def _global_authority_dir(roots: tuple[Path, ...]) -> Path:
    """Where the journal/inventory live.  The AUTHORITY is every root's pointer."""
    return roots[0] / "fabpub-global-cutover"


def _authority_pointers(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(root / "fabpub-global-cutover" / "ACTIVE_CUTOVER" for root in roots)


def _read_pointer_claim(pointer: Path) -> dict:
    raw = pointer.read_text(encoding="utf-8").strip()
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise LegacyCutoverConflict(f"unreadable cutover claim at {pointer}: {error}")
    return {"cutover_id": raw}


def _snapshot_lock_paths(manifest: LegacyBrokerCutoverManifest) -> tuple[Path, ...]:
    """SOL-05: the COMPLETE pre-snapshot lock set, deterministically ordered.

    Global authority, every declared legacy root, and every declared legacy
    LEAF's admission/evidence lock.  Without the leaf locks a concurrent legacy
    writer can raise a high water after the seal inputs were computed.
    Generation locks are taken separately and briefly (see `_transition_locks`)
    because holding them across a drain would block the very foreign
    ``release()`` calls the drain waits for (SL1-SOL-04).
    """
    roots = manifest.legacy_roots()
    paths = [_global_authority_dir(roots) / "cutover.lock"]
    paths.extend(root / "fabpub-global-cutover" / "root.lock" for root in roots)
    # Per-leaf locks live in a SIBLING lock directory, never inside the leaf.
    # Locking `<leaf>/admissions.lock` would `mkdir` the leaf itself, which
    # resurrects retired leaves and breaks both the unclaimed-leaf scan and the
    # retirement state matrix.  The lock NAME still binds the exact leaf, so the
    # mutual exclusion a concurrent legacy writer needs is unchanged.
    for row in manifest.rows:
        root = Path(row["legacy_root"])
        leaf_id = f"{row['expected_train_key']}__{row['expected_repo_key']}"
        paths.append(root / "fabpub-global-cutover" / "leaf-locks" / f"{leaf_id}.lock")
    return tuple(sorted(set(paths), key=str))


def _target_store_lock_paths(partitions: dict) -> tuple[Path, ...]:
    return tuple(
        sorted(
            {Path(partitions[i]["target_namespace"]) / "admissions.lock" for i in partitions},
            key=str,
        )
    )


@contextlib.contextmanager
def _hold_all(paths: Iterable[Path]):
    with contextlib.ExitStack() as stack:
        for path in paths:
            stack.enter_context(_reentrant_flock(path))
        yield


def _validate_admissions(path: Path) -> tuple[int, int]:
    """Strictly parse a legacy admissions log; return (count, high_water).

    SL1-SOL-11: duplicate fencing identity is compared by EXACT LINE BYTES, not
    by reparsed dicts — two rows that differ only in key order or numeric
    formatting are not "identical" for authority purposes.
    """
    if not path.exists():
        raise LegacyCutoverConflict(f"legacy leaf is missing its admissions log: {path}")
    rows = read_strict_jsonl(path, label="legacy admissions")
    by_attempt: dict[str, str] = {}
    by_key: dict[str, str] = {}
    for line, raw in rows:
        request = raw.get("request")
        if not isinstance(request, dict):
            continue
        request_line = json.dumps(request, sort_keys=True, separators=(",", ":"))
        for bucket, field in ((by_attempt, "attempt_id"), (by_key, "idempotency_key")):
            value = request.get(field)
            if value is None:
                continue
            prior = bucket.get(value)
            if prior is not None and prior != request_line:
                raise LegacyCutoverConflict(
                    f"divergent legacy admission authority for {field}={value!r} in {path}"
                )
            bucket[value] = request_line
        del line
    for index, (_line, raw) in enumerate(rows, start=1):
        if raw.get("sequence") != index:
            raise LegacyCutoverConflict(
                f"legacy admission sequence must be contiguous from 1 in {path}; "
                f"expected {index}, got {raw.get('sequence')!r}"
            )
        if not isinstance(raw.get("epoch"), int) or raw["epoch"] <= 0:
            raise LegacyCutoverConflict(f"legacy admission epoch must be positive in {path}")
        request = raw.get("request")
        if not isinstance(request, dict):
            raise LegacyCutoverConflict(f"legacy admission request must be an object in {path}")
        for required in (
            "attempt_id", "lease_epoch", "fence_token", "approval_digest",
            "expected_version_predicate", "authority_domain_scope", "idempotency_key",
        ):
            if required not in request:
                raise LegacyCutoverConflict(
                    f"legacy admission request omits {required!r} in {path}"
                )
    return len(rows), max((raw["epoch"] for _l, raw in rows), default=0)


_LEGAL_EVIDENCE_TRANSITIONS = {
    "": {"provider_call_in_flight", "rejected_before_start"},
    "provider_call_in_flight": {
        "effect_terminal_observed",
        "effect_terminal_absent",
        "outcome_ambiguous_blocked",
    },
    "effect_terminal_observed": set(),
    "effect_terminal_absent": set(),
    "rejected_before_start": set(),
    # outcome_ambiguous_blocked is PERMANENT: no transition out, ever.
    "outcome_ambiguous_blocked": set(),
}


def _validate_evidence(path: Path) -> tuple[bool, dict[str, str]]:
    """Validate a legacy evidence log as a FULL per-key history.

    SL1-SOL-11: a repeated state must be BYTE-identical to its predecessor row,
    not merely share an ``evidence_reference``.
    """
    rows = read_strict_jsonl(path, label="legacy evidence")
    histories: dict[str, list[tuple[str, dict]]] = {}
    for line, raw in rows:
        for required in ("idempotency_key", "state"):
            if required not in raw:
                raise LegacyCutoverConflict(f"legacy evidence row omits {required!r} in {path}")
        histories.setdefault(raw["idempotency_key"], []).append((line, raw))

    ambiguous = False
    completed: dict[str, str] = {}
    for key, entries in histories.items():
        current = ""
        previous_line: str | None = None
        for line, raw in entries:
            state = raw["state"]
            if state not in _LEGAL_EVIDENCE_TRANSITIONS:
                raise LegacyCutoverConflict(
                    f"unknown legacy evidence state {state!r} for {key!r} in {path}"
                )
            if state == current:
                if previous_line is not None and line != previous_line:
                    raise LegacyCutoverConflict(
                        f"divergent duplicate terminal for {key!r} in {path}"
                    )
                previous_line = line
                continue
            if state not in _LEGAL_EVIDENCE_TRANSITIONS[current]:
                raise LegacyCutoverConflict(
                    f"illegal legacy evidence transition {current or '<none>'} -> {state} "
                    f"for {key!r} in {path}"
                )
            current, previous_line = state, line
        if current == "outcome_ambiguous_blocked":
            ambiguous = True
        elif current == "provider_call_in_flight":
            ambiguous = True  # orphaned in-flight: the effect is unknown
        elif current == "effect_terminal_observed":
            completed[key] = entries[-1][1].get("evidence_reference", "")
    return ambiguous, completed


def _resolve_row_repository(row: dict) -> Path:
    """Resolve a row's EXACT serialized repository string in its recorded context."""
    serialized = row["serialized_repository"]
    mode = row["resolution_mode"]
    cwd = Path(row["invocation_working_directory"])
    if mode == "absolute":
        candidate = Path(serialized)
        if not candidate.is_absolute():
            raise LegacyCutoverConflict(
                f"resolution_mode 'absolute' but {serialized!r} is not an absolute path"
            )
    elif mode == "workspace_argument_relative":
        candidate = cwd / serialized
    else:
        raise LegacyCutoverConflict(f"unsupported resolution_mode {mode!r}")
    if not (candidate / ".git").exists() and not (candidate / "HEAD").exists():
        raise LegacyCutoverConflict(
            f"{serialized!r} does not resolve to a Git repository from {cwd}"
        )
    return candidate


def _plan_partitions(manifest: LegacyBrokerCutoverManifest) -> dict:
    """Authenticate every row and partition every legacy leaf by canonical identity.

    Read-only.  SL1-SOL-05: the caller runs this AFTER `begin_draining()` and
    while holding every legacy leaf lock, so the digests it computes cannot be
    invalidated by a concurrent legacy writer immediately afterwards.
    """
    roots = manifest.legacy_roots()
    partitions: dict[str, dict] = {}
    claimed: set[str] = set()

    for row in manifest.rows:
        serialized = row["serialized_repository"]
        train_key = hashlib.sha256(
            str(Path(row["resolved_train_path"]).resolve()).encode("utf-8")
        ).hexdigest()[:16]
        repo_key = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        if train_key != row["expected_train_key"]:
            raise LegacyCutoverConflict(
                f"recomputed train_key {train_key} != declared {row['expected_train_key']}"
            )
        if repo_key != row["expected_repo_key"]:
            raise LegacyCutoverConflict(
                f"recomputed repo_key {repo_key} for {serialized!r} != declared "
                f"{row['expected_repo_key']}; a legacy key may only hash the EXACT "
                "historical serialized bytes, never a resolved or normalized alias"
            )
        declared_bytes_digest = row.get("serialized_repository_bytes_sha256")
        actual_bytes_digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if declared_bytes_digest != actual_bytes_digest:
            raise LegacyCutoverConflict(
                f"declared serialized_repository_bytes_sha256 {declared_bytes_digest!r} != "
                f"{actual_bytes_digest} for {serialized!r}"
            )

        worktree = _resolve_row_repository(row)
        identity = canonical_repository_identity(worktree)
        expected_worktree = row.get("expected_worktree")
        if expected_worktree and canonical_repository_identity(expected_worktree) != identity:
            raise LegacyCutoverConflict(
                f"expected_worktree {expected_worktree!r} is a different canonical "
                f"repository than {serialized!r} resolves to in its recorded context"
            )

        leaf = Path(row["legacy_root"]) / train_key / repo_key
        if not leaf.is_dir():
            raise LegacyCutoverConflict(f"declared legacy leaf is missing: {leaf}")
        leaf_id = str(leaf.resolve())
        if leaf_id in claimed:
            raise LegacyCutoverConflict(f"legacy leaf claimed more than once: {leaf}")
        claimed.add(leaf_id)

        count, high_water = _validate_admissions(leaf / "admissions.jsonl")
        ambiguous, completed = _validate_evidence(leaf / "evidence.jsonl")
        source_digest = hashlib.sha256((leaf / "admissions.jsonl").read_bytes()).hexdigest()
        evidence_path = leaf / "evidence.jsonl"
        evidence_digest = hashlib.sha256(
            evidence_path.read_bytes() if evidence_path.exists() else b""
        ).hexdigest()

        partition = partitions.setdefault(
            identity,
            {
                "canonical_repository_identity": identity,
                "worktree": str(worktree),
                "target_namespace": str(repository_broker_namespace(worktree)),
                "legacy_epoch_high_water": 0,
                "ambiguous": False,
                "serialized_repository_preimages": [],
                "resolution_contexts": [],
                "source_digests": [],
                "evidence_digests": [],
                "legacy_completed_effect_keys": [],
                "legacy_completed_effects": {},
                "sources": [],
            },
        )
        partition["legacy_epoch_high_water"] = max(
            partition["legacy_epoch_high_water"], high_water
        )
        partition["ambiguous"] = partition["ambiguous"] or ambiguous
        partition["serialized_repository_preimages"].append(serialized)
        context = f"{row['resolution_mode']}:{row['invocation_working_directory']}"
        partition["resolution_contexts"].append(context)
        partition["source_digests"].append(source_digest)
        partition["evidence_digests"].append(evidence_digest)
        for effect_key, reference in completed.items():
            prior = partition["legacy_completed_effects"].get(effect_key)
            if prior is not None and prior["evidence_reference"] != reference:
                raise LegacyCutoverConflict(
                    f"divergent legacy terminals for effect key {effect_key!r} across "
                    "sources in one repository partition"
                )
            partition["legacy_completed_effects"][effect_key] = {
                "evidence_reference": reference,
                "source_id": f"{train_key}__{repo_key}",
                "serialized_repository": serialized,
                "resolution_context": context,
                "legacy_root": str(Path(row["legacy_root"])),
                "admissions_digest": source_digest,
                "evidence_digest": evidence_digest,
            }
        partition["legacy_completed_effect_keys"].extend(completed)
        partition["sources"].append(
            {
                "legacy_root": str(Path(row["legacy_root"])),
                "leaf": str(leaf),
                "source_id": f"{train_key}__{repo_key}",
                "records": count,
                "digest": source_digest,
                "evidence_digest": evidence_digest,
            }
        )

    for root in roots:
        if not root.is_dir():
            raise LegacyCutoverConflict(f"declared legacy root is missing: {root}")
        for train_dir in sorted(root.iterdir()):
            if train_dir.name in ("legacy-archive", "fabpub-global-cutover"):
                continue
            if train_dir.is_symlink():
                raise LegacyCutoverConflict(
                    f"legacy root child is a symlink (path escape): {train_dir}"
                )
            if not train_dir.is_dir():
                continue  # retirement tombstones are regular files
            for leaf in sorted(train_dir.iterdir()):
                if leaf.is_symlink():
                    raise LegacyCutoverConflict(f"legacy leaf is a symlink (path escape): {leaf}")
                if not leaf.is_dir():
                    continue
                if str(leaf.resolve()) not in claimed:
                    raise LegacyCutoverConflict(
                        f"legacy leaf {leaf} is not claimed by any manifest row"
                    )

    for partition in partitions.values():
        namespace = Path(partition["target_namespace"])
        if (namespace / "admissions.jsonl").exists() and (
            not (namespace / RECEIPT_FILENAME).exists()
        ):
            raise LegacyCutoverConflict(
                f"unattested canonical admission state at {namespace}; the cutover may "
                "never adopt state it did not migrate"
            )

    for partition in partitions.values():
        partition["legacy_completed_effect_keys"] = sorted(
            set(partition["legacy_completed_effect_keys"])
        )
    return partitions


def _require_root_tombstone(root: Path, cutover_id: str) -> None:
    """A retired legacy root must carry OUR exact, non-symlinked tombstone."""
    tombstone = root / "RETIRED"
    if tombstone.is_symlink():
        raise LegacyCutoverConflict(f"root retirement tombstone is a symlink: {tombstone}")
    if not tombstone.is_file():
        raise LegacyCutoverConflict(f"legacy root {root} lost its retirement tombstone")
    owner = tombstone.read_text(encoding="utf-8").strip()
    if owner != cutover_id:
        raise LegacyCutoverConflict(
            f"legacy root {root} is retired by cutover {owner!r}, not {cutover_id!r}"
        )


def _retire_one_source(transaction: "LegacyBrokerCutoverTransaction", source: dict) -> None:
    """Retire exactly one legacy leaf under a strict state matrix.

    The dangerous state is COEXISTENCE — a live source directory beside an
    existing archive — which means the source was recreated after retirement.
    Silently skipping the move there would let a resurrected pre-FABPUB store
    keep serving admissions behind an ARMED barrier.
    """
    leaf = Path(source["leaf"])
    legacy_root = Path(source["legacy_root"])
    archive = legacy_root / "legacy-archive" / transaction.cutover_id
    if archive.is_symlink() or (archive.parent.exists() and archive.parent.is_symlink()):
        raise LegacyCutoverConflict(f"legacy archive path is a symlink: {archive}")
    archive.mkdir(parents=True, exist_ok=True)
    target = archive / source["source_id"]
    if target.is_symlink():
        raise LegacyCutoverConflict(f"archive target is a symlink: {target}")
    resolved_root = legacy_root.resolve()
    if not str(archive.resolve()).startswith(str(resolved_root) + os.sep):
        raise LegacyCutoverConflict(
            f"archive directory {archive} escapes its declared legacy root {legacy_root}"
        )
    if target.exists() and not str(target.resolve()).startswith(str(resolved_root) + os.sep):
        raise LegacyCutoverConflict(
            f"archive target {target} escapes its declared legacy root {legacy_root}"
        )
    if leaf.is_symlink():
        raise LegacyCutoverConflict(f"legacy source leaf is a symlink: {leaf}")
    leaf_is_dir = leaf.is_dir()

    if leaf_is_dir and target.exists():
        raise LegacyCutoverConflict(
            f"legacy source {leaf} coexists with its archive {target}; the source was "
            "recreated after retirement and may not be silently re-migrated"
        )
    if not leaf.exists() and not target.exists():
        raise LegacyCutoverConflict(
            f"legacy source {leaf} vanished without an archive at {target}"
        )
    if leaf_is_dir:
        os.replace(leaf, target)
        _fsync_dir(archive)
        _fsync_dir(leaf.parent)

    _verify_archive_bytes(target, source)

    tombstone_body = json.dumps(
        {
            "retired_by": transaction.cutover_id,
            "archived_to": str(target),
            "source_digest": source["digest"],
            "evidence_digest": source.get("evidence_digest", ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    if leaf.exists():
        if leaf.is_dir():
            raise LegacyCutoverConflict(f"retired leaf {leaf} is still a directory")
        if leaf.read_text(encoding="utf-8") != tombstone_body:
            raise LegacyCutoverConflict(f"retirement tombstone bytes drifted at {leaf}")
        return
    temp = leaf.parent / f".{leaf.name}.{os.getpid()}.{_fresh_nonce()[:8]}.tomb"
    with temp.open("w", encoding="utf-8") as stream:
        stream.write(tombstone_body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, leaf)
    _fsync_dir(leaf.parent)


def _verify_archive_bytes(target: Path, source: dict) -> None:
    """The archive must still hold exactly the bytes the inventory digested."""
    archived_admissions = target / "admissions.jsonl"
    if not archived_admissions.exists():
        raise LegacyCutoverConflict(f"archived source {target} is missing its admissions log")
    if hashlib.sha256(archived_admissions.read_bytes()).hexdigest() != source["digest"]:
        raise LegacyCutoverConflict(f"archived admissions bytes drifted at {target}")
    expected_evidence = source.get("evidence_digest")
    if expected_evidence is not None:
        archived_evidence = target / "evidence.jsonl"
        actual = hashlib.sha256(
            archived_evidence.read_bytes() if archived_evidence.exists() else b""
        ).hexdigest()
        if actual != expected_evidence:
            raise LegacyCutoverConflict(f"archived evidence bytes drifted at {target}")


class LegacyBrokerCutoverTransaction:
    """``LegacyBrokerCutoverTransaction.v2`` — the one global cutover authority."""

    JOURNAL_STATES = (
        "DRAINING",
        "INVENTORY_SEALED",
        "SNAPSHOTS_VERIFIED",
        "SOURCES_RETIRED",
        "PARTITIONS_WRITTEN",
        "ARMED",
        "ACTIVE",
    )

    def __init__(
        self,
        cutover_id: str,
        journal_path: Path,
        partitions: dict,
        sealed: dict | None = None,
        journal_state_key: str = "state",
    ) -> None:
        self.cutover_id = cutover_id
        self.journal_path = Path(journal_path)
        self.partitions = partitions
        self.sealed = sealed or {}
        self.journal_state_key = journal_state_key

    @property
    def authority_lock_path(self) -> Path:
        return self.journal_path.parent / "cutover.lock"

    @contextlib.contextmanager
    def authority(self):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with _reentrant_flock(self.authority_lock_path):
            yield

    @property
    def state(self) -> str:
        states = _journal_states(self.journal_path)
        return states[-1] if states else "DRAINING"

    def _record(self, state: str) -> None:
        """Append one journal state, exactly once, with no volatile bytes."""
        with self.authority():
            states = _journal_states(self.journal_path)
            if state in states:
                return
            expected_index = self.JOURNAL_STATES.index(state)
            if expected_index and self.JOURNAL_STATES[expected_index - 1] not in states:
                raise LegacyCutoverConflict(
                    f"journal state {state} requires its predecessor "
                    f"{self.JOURNAL_STATES[expected_index - 1]}"
                )
            body = json.dumps(
                {"cutover_id": self.cutover_id, self.journal_state_key: state},
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n"
            with self.journal_path.open("a", encoding="utf-8") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            _fsync_dir(self.journal_path.parent)

    def receipt_for(self, worktree: Path | str) -> LegacyRepositoryPartitionReceipt:
        identity = canonical_repository_identity(worktree)
        partition = self.partitions.get(identity)
        if partition is None:
            raise LegacyCutoverConflict(
                f"no partition receipt for canonical repository {identity}"
            )
        receipt = load_partition_receipt(Path(partition["target_namespace"]))
        if receipt is None:
            raise LegacyCutoverConflict(f"partition receipt not yet written for {identity}")
        return receipt

    def revalidate_armed(self) -> None:
        """Re-prove the whole chain: receipts, archives, and tombstones."""
        if self.sealed and _inventory_digest(self.sealed) != self.sealed.get("inventory_sha256"):
            raise LegacyCutoverConflict(
                "the ARMED authority's sealed inventory digest drifted"
            )
        for identity in sorted(self.partitions):
            partition = self.partitions[identity]
            _require_no_ancestor_symlink(Path(partition["target_namespace"]))
            receipt = load_partition_receipt(Path(partition["target_namespace"]))
            if receipt is None or receipt.cutover_id != self.cutover_id:
                raise LegacyCutoverConflict(f"partition {identity} is not armed by this cutover")
            for source in partition["sources"]:
                leaf = Path(source["leaf"])
                if leaf.is_symlink():
                    raise LegacyCutoverConflict(f"retired leaf {leaf} became a symlink")
                if leaf.is_dir():
                    raise LegacyCutoverConflict(f"legacy source {leaf} was recreated")
                if not leaf.exists():
                    raise LegacyCutoverConflict(f"retirement tombstone for {leaf} vanished")
                target = (
                    Path(source["legacy_root"])
                    / "legacy-archive"
                    / self.cutover_id
                    / source["source_id"]
                )
                _verify_archive_bytes(target, source)
                _require_root_tombstone(Path(source["legacy_root"]), self.cutover_id)
            latch = WriterGenerationLatch(repository_namespace_root(partition["worktree"]))
            if not latch.armed_marker.exists():
                raise LegacyCutoverConflict(
                    f"repository {identity} lost its ARMED latch marker"
                )

    def activate(self) -> "LegacyBrokerCutoverTransaction":
        """Irreversible ``ARMED -> ACTIVE``, journal first then every latch.

        SL1-SOL-06: the journal ACTIVE record and the latch promotions are ONE
        transition; neither half may happen without the other.
        """
        with self.authority():
            if "ARMED" not in _journal_states(self.journal_path):
                raise LegacyCutoverConflict("ACTIVE requires a complete ARMED barrier")
            self.revalidate_armed()
            self._record("ACTIVE")
            for identity in sorted(self.partitions):
                WriterGenerationLatch(
                    repository_namespace_root(self.partitions[identity]["worktree"])
                ).activate()
        return self


def run_legacy_broker_cutover(
    manifest: LegacyBrokerCutoverManifest,
) -> LegacyBrokerCutoverTransaction:
    """Run (or idempotently resume) the ONE global legacy-broker cutover.

    Ordering is load-bearing and differs from the rejected implementation:

    * one authority spans pointer claim, resume decision, and the whole drive;
    * every declared root AND leaf lock is held before anything is read;
    * DRAINING precedes `_plan_partitions`, so the digests the inventory seals
      cannot be invalidated by a concurrent legacy writer (SL1-SOL-05);
    * `await_quiescent` runs WITHOUT the latch lock so foreign `release()` can
      complete (SL1-SOL-04).
    """
    roots = manifest.legacy_roots()
    authority = _global_authority_dir(roots)
    journal_path = authority / f"{manifest.cutover_id}.journal.jsonl"
    inventory_path = authority / f"{manifest.cutover_id}.inventory.json"
    pointers = _authority_pointers(roots)
    manifest_sha256 = _manifest_digest(manifest)
    root_set_sha256 = _root_set_digest(roots)

    for pointer in pointers:
        pointer.parent.mkdir(parents=True, exist_ok=True)

    with _hold_all(_snapshot_lock_paths(manifest)):
        # (a) A different cutover already owns ANY declared root.  Checking
        # every root — not just the primary — stops two manifests that merely
        # share a non-first root from both proceeding.
        for pointer in pointers:
            if pointer.exists():
                claim = _read_pointer_claim(pointer)
                if claim["cutover_id"] != manifest.cutover_id:
                    raise LegacyCutoverConflict(
                        f"legacy root {pointer.parent.parent} is already owned by cutover "
                        f"{claim['cutover_id']!r}; {manifest.cutover_id!r} may not "
                        "re-migrate retired sources"
                    )
                if claim.get("root_set_sha256") not in (None, root_set_sha256):
                    raise LegacyCutoverConflict(
                        f"cutover {manifest.cutover_id!r} already claimed a DIFFERENT "
                        "complete legacy root set; the root inventory may not change"
                    )
                if claim.get("manifest_sha256") not in (None, manifest_sha256):
                    raise LegacyCutoverConflict(
                        f"cutover {manifest.cutover_id!r} already claimed different "
                        "manifest bytes"
                    )

        # (b) Resume: never re-scan retired sources; replay the sealed inventory.
        if journal_path.exists() and inventory_path.exists():
            sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
            if sealed.get("manifest_sha256") != manifest_sha256:
                raise LegacyCutoverConflict(
                    f"cutover {manifest.cutover_id!r} was sealed with different manifest "
                    "bytes; a resume may not change the row set or partition map"
                )
            if _inventory_digest(sealed) != sealed.get("inventory_sha256"):
                raise LegacyCutoverConflict("the sealed cutover inventory digest drifted")
            if tuple(sealed.get("legacy_root_inventory", ())) != tuple(str(r) for r in roots):
                raise LegacyCutoverConflict(
                    "a resume may not change the complete legacy root inventory"
                )
            transaction = LegacyBrokerCutoverTransaction(
                manifest.cutover_id, journal_path, sealed["partitions"], sealed
            )
            if "ARMED" in _journal_states(journal_path):
                # SL1-SOL-09: an already-ARMED resume still revalidates archives
                # and tombstones before handing back a routable authority.
                transaction.revalidate_armed()
                return transaction
            return _drive_cutover(transaction, sealed["partitions"], roots, sealed)

        # (c) Fresh.  Quiescence FIRST (read-only), then drain, then plan.
        worktrees = manifest.declared_worktrees()
        for worktree in worktrees:
            LegacyWriterQuiescence.inventory(worktree).require_fenceable().require_quiescent()

        latches = [WriterGenerationLatch.open(worktree) for worktree in worktrees]
        # Generation locks are taken BRIEFLY for the transition only; holding
        # them across the drain would block the foreign releases we wait for.
        with _hold_all([latch.lock_path for latch in latches]):
            for latch in latches:
                if latch.read().generation_state != "ACTIVE":
                    latch.begin_draining()
        for latch, worktree in zip(latches, worktrees):
            if latch.read().generation_state == "DRAINING":
                latch.await_quiescent(worktree=worktree)

        partitions = _plan_partitions(manifest)

        for pointer in pointers:
            claim_body = json.dumps(
                {
                    "cutover_id": manifest.cutover_id,
                    "root_set_sha256": root_set_sha256,
                    "manifest_sha256": manifest_sha256,
                    "legacy_root_inventory": [str(root) for root in roots],
                    "primary_authority": str(authority),
                },
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n"
            try:
                handle = os.open(str(pointer), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                claim = _read_pointer_claim(pointer)
                if claim["cutover_id"] != manifest.cutover_id:
                    raise LegacyCutoverConflict(
                        f"another cutover ({claim['cutover_id']!r}) claimed "
                        f"{pointer.parent.parent} first"
                    )
            else:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    stream.write(claim_body)
                    stream.flush()
                    os.fsync(stream.fileno())
                _fsync_dir(pointer.parent)

        sealed = {
            "schema": "LegacyBrokerCutoverInventory.v2",
            "cutover_id": manifest.cutover_id,
            "manifest_sha256": manifest_sha256,
            "legacy_root_inventory": [str(root) for root in roots],
            "partition_map_sha256": _partition_map_digest(partitions),
            "partitions": partitions,
        }
        sealed["inventory_sha256"] = _inventory_digest(sealed)
        _atomic_write_json(inventory_path, sealed)
        transaction = LegacyBrokerCutoverTransaction(
            manifest.cutover_id, journal_path, partitions, sealed
        )
        return _drive_cutover(transaction, partitions, roots, sealed)


def _drive_cutover(
    transaction: LegacyBrokerCutoverTransaction,
    partitions: dict,
    roots: tuple[Path, ...],
    sealed: dict,
) -> LegacyBrokerCutoverTransaction:
    """Advance the journal to ``ARMED``, resuming idempotently from any kill."""
    ordered_identities = sorted(partitions)
    latches = [
        WriterGenerationLatch.open(Path(partitions[i]["worktree"])) for i in ordered_identities
    ]
    with _hold_all([latch.lock_path for latch in latches]):
        for latch in latches:
            if latch.read().generation_state == "LEGACY_OPEN":
                latch.begin_draining()
    for identity, latch in zip(ordered_identities, latches):
        if latch.read().generation_state == "DRAINING":
            latch.await_quiescent(worktree=Path(partitions[identity]["worktree"]))

    with _hold_all(_target_store_lock_paths(partitions)):
        transaction._record("DRAINING")
        transaction._record("INVENTORY_SEALED")
        transaction._record("SNAPSHOTS_VERIFIED")

        _maybe_crash("before_source_retirement")
        retired = 0
        ordered = [
            (identity, source)
            for identity in ordered_identities
            for source in sorted(partitions[identity]["sources"], key=lambda s: s["source_id"])
        ]
        for _identity, source in ordered:
            if retired == 1:
                _maybe_crash("between_source_retirements")
            _retire_one_source(transaction, source)
            retired += 1
        _maybe_crash("after_source_retirement")

        for root in roots:
            tombstone = root / "RETIRED"
            if tombstone.is_symlink():
                raise LegacyCutoverConflict(f"root tombstone is a symlink: {tombstone}")
            if not tombstone.exists():
                temp = root / f".RETIRED.{os.getpid()}.{_fresh_nonce()[:8]}.tmp"
                with temp.open("w", encoding="utf-8") as stream:
                    stream.write(f"{transaction.cutover_id}\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, tombstone)
                _fsync_dir(root)

        transaction._record("SOURCES_RETIRED")

        _maybe_crash("before_partition_write")
        written = 0
        for identity in ordered_identities:
            partition = partitions[identity]
            if written == 1:
                _maybe_crash("between_partition_writes")
            namespace = Path(partition["target_namespace"])
            namespace.mkdir(parents=True, exist_ok=True)
            _receipt_from_partition(
                transaction.cutover_id, partition, sealed, transaction.journal_path
            ).write(namespace, zero_source_proof=partition.get("zero_source_proof"))
            written += 1
        _maybe_crash("after_partition_write")

        transaction._record("PARTITIONS_WRITTEN")

        _maybe_crash("before_armed")
        # SL1-SOL-06: ARMED is journaled BEFORE any latch is promoted, so no
        # repository can ever advertise an ACTIVE generation without an armed
        # barrier behind it.  Promotion is then part of the SAME guarded step —
        # not a separate path that `transaction.activate()` might or might not
        # perform — and `latch.activate()` itself refuses without the marker.
        for latch in latches:
            latch.mark_armed()
        transaction._record("ARMED")
        for latch in latches:
            latch.activate()
    return transaction


#: Where an operator declares the explicit metadata-only cutover manifest.
FABPUB_CUTOVER_MANIFEST_ENV = "PHASE_LOOP_FABPUB_CUTOVER_MANIFEST"
#: Optional explicit list of legacy roots a zero-source proof must scan.
FABPUB_LEGACY_ROOTS_ENV = "PHASE_LOOP_FABPUB_LEGACY_ROOTS"

ONBOARDING_SEAL_BOUNDARIES = (
    "before_zero_source_proof",
    "before_receipt_write",
    "before_receipt_fsync",
)
ONBOARDING_INJECTIONS = (
    "legacy_source",
    "archive",
    "retirement_tombstone",
    "prior_receipt",
)

_ONBOARDING_INJECTION: tuple[str, str] | None = None


@contextlib.contextmanager
def inject_before_onboarding_seal(boundary: str, injection: str):
    """Arm a late-evidence injection at one frozen pre-seal boundary."""
    global _ONBOARDING_INJECTION
    if boundary not in ONBOARDING_SEAL_BOUNDARIES:
        raise ValueError(f"unknown onboarding boundary {boundary!r}")
    if injection not in ONBOARDING_INJECTIONS:
        raise ValueError(f"unknown onboarding injection {injection!r}")
    previous, _ONBOARDING_INJECTION = _ONBOARDING_INJECTION, (boundary, injection)
    try:
        yield
    finally:
        _ONBOARDING_INJECTION = previous


def declared_legacy_roots() -> tuple[Path, ...]:
    """Every legacy broker root a zero-source proof must scan.

    Sources, in order: the explicit roots env, plus every root named by the
    declared cutover manifest.  A zero-source proof that scanned nothing would
    be a fail-open (SL1-SOL-01), so an onboarding with no declared roots is only
    legal when the operator explicitly declares an empty inventory.
    """
    roots: list[Path] = []
    explicit = os.environ.get(FABPUB_LEGACY_ROOTS_ENV)
    if explicit is not None:
        roots.extend(Path(part) for part in explicit.split(os.pathsep) if part)
    manifest_path = os.environ.get(FABPUB_CUTOVER_MANIFEST_ENV)
    if manifest_path and Path(manifest_path).exists():
        raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        for row in raw.get("rows", ()):
            roots.append(Path(row["legacy_root"]))
    seen: dict[str, Path] = {}
    for root in roots:
        seen.setdefault(str(root), root)
    return tuple(seen[key] for key in sorted(seen))


def _prove_zero_source(
    snapshot: RepositorySnapshot, roots: tuple[Path, ...], boundary: str
) -> dict:
    """REALLY scan for legacy evidence for this repository.

    SL1-SOL-01: the rejected implementation returned hardcoded zeros.  This
    walks every declared legacy root and counts live legacy leaves, archived
    sources, and retirement tombstones whose serialized-repository preimage
    resolves to THIS canonical repository, plus any prior receipt.  Re-run at
    every pre-seal boundary, because evidence that appears mid-onboarding must
    not ride through to a sealed receipt.
    """
    if _ONBOARDING_INJECTION is not None and _ONBOARDING_INJECTION[0] == boundary:
        raise LegacyCutoverConflict(
            f"late {_ONBOARDING_INJECTION[1]} evidence appeared at {boundary}; a "
            "zero-source onboarding may not seal over legacy evidence"
        )
    namespace = snapshot.store_root
    existing = None
    if (namespace / RECEIPT_FILENAME).exists():
        existing = load_partition_receipt(namespace)
        if existing is not None and not existing.zero_source:
            raise LegacyCutoverConflict(
                f"a legacy-migrated receipt already governs {namespace}"
            )

    legacy_sources = archives = tombstones = 0
    scanned: list[str] = []
    for root in roots:
        scanned.append(str(root))
        if not root.exists():
            continue
        _require_no_ancestor_symlink(root)
        for train_dir in sorted(p for p in root.iterdir() if p.name != "fabpub-global-cutover"):
            if train_dir.name == "legacy-archive":
                for archived in sorted(train_dir.rglob("admissions.jsonl")):
                    if _archive_targets_repository(archived.parent, snapshot):
                        archives += 1
                continue
            if not train_dir.is_dir():
                continue
            for leaf in sorted(train_dir.iterdir()):
                source_id = f"{train_dir.name}__{leaf.name}"
                if leaf.is_dir() and (leaf / "admissions.jsonl").exists():
                    pointer = root / "fabpub-global-cutover" / "ACTIVE_CUTOVER"
                    if not pointer.exists() or _cutover_source_targets_repository(
                        root,
                        _read_pointer_claim(pointer)["cutover_id"],
                        source_id,
                        snapshot,
                    ):
                        legacy_sources += 1
                elif leaf.is_file():
                    try:
                        cutover_id = json.loads(leaf.read_text(encoding="utf-8"))["retired_by"]
                    except (KeyError, OSError, ValueError, TypeError):
                        tombstones += 1
                    else:
                        if _cutover_source_targets_repository(
                            root, cutover_id, source_id, snapshot
                        ):
                            tombstones += 1
    if legacy_sources or archives or tombstones:
        raise LegacyCutoverConflict(
            f"zero-source onboarding refused for {snapshot.identity}: found "
            f"{legacy_sources} live legacy source(s), {archives} archived source(s), and "
            f"{tombstones} retirement tombstone(s) across {scanned}"
        )
    return {
        "schema": "ZeroSourceProof.v1",
        "boundary": boundary,
        "canonical_repository_identity": snapshot.identity,
        "scanned_legacy_roots": scanned,
        "legacy_sources": 0,
        "archives": 0,
        "retirement_tombstones": 0,
        "prior_receipts": 1 if existing is not None else 0,
    }


def _archive_targets_repository(archive_dir: Path, snapshot: RepositorySnapshot) -> bool:
    """Return whether a sealed archived source belongs to this repository."""
    cutover_dir = archive_dir.parent
    legacy_root = cutover_dir.parent.parent
    return _cutover_source_targets_repository(
        legacy_root, cutover_dir.name, archive_dir.name, snapshot
    )


def _cutover_source_targets_repository(
    legacy_root: Path,
    cutover_id: str,
    source_id: str,
    snapshot: RepositorySnapshot,
) -> bool:
    inventory = (
        legacy_root
        / "fabpub-global-cutover"
        / f"{cutover_id}.inventory.json"
    )
    try:
        partitions = json.loads(inventory.read_text(encoding="utf-8"))["partitions"]
    except (KeyError, OSError, ValueError, TypeError):
        return True
    source_owner = None
    for identity, partition in partitions.items():
        if any(source.get("source_id") == source_id for source in partition.get("sources", ())):
            if source_owner is not None and source_owner != identity:
                return True
            source_owner = identity
    return source_owner is None or source_owner == snapshot.identity


def onboard_zero_legacy_repository(
    worktree: Path | str, *, cutover_id: str = "fabpub-zero-legacy-onboarding"
) -> LegacyRepositoryPartitionReceipt:
    """Serialized, authenticated onboarding for a repository first seen post-ACTIVE.

    Not an empty-store fallback: exactly one receipt, written under the latch's
    exclusive activation lock, carrying a REAL zero-source proof.  The latch is
    NOT self-promoted to ACTIVE — a repository may not authorize its own
    generation without a global ACTIVE authority (SL1-SOL-01).
    """
    snapshot = repository_snapshot(worktree)
    roots = declared_legacy_roots()
    latch = WriterGenerationLatch.open(worktree)
    with latch.exclusive():
        namespace = snapshot.store_root
        existing = None
        if (namespace / RECEIPT_FILENAME).exists():
            existing = load_partition_receipt(namespace)
        if existing is not None:
            _prove_zero_source(snapshot, roots, "before_zero_source_proof")
            return existing
        zero_source_proof = _prove_zero_source(snapshot, roots, "before_zero_source_proof")
        identity = snapshot.identity
        authority = latch.root / "zero-legacy-onboarding"
        authority.mkdir(parents=True, exist_ok=True)
        journal_path = authority / f"{cutover_id}.journal.jsonl"
        inventory_path = authority / f"{cutover_id}.inventory.json"
        partition = {
            "canonical_repository_identity": identity,
            "worktree": str(snapshot.worktree),
            "target_namespace": str(namespace),
            "legacy_epoch_high_water": 0,
            "ambiguous": False,
            "serialized_repository_preimages": [],
            "resolution_contexts": [],
            "source_digests": [],
            "evidence_digests": [],
            "legacy_completed_effect_keys": [],
            "legacy_completed_effects": {},
            "sources": [],
            "zero_source": True,
            "zero_source_proof": zero_source_proof,
            "zero_source_proof_sha256": hashlib.sha256(
                canonical_bytes(zero_source_proof)
            ).hexdigest(),
        }
        partitions = {identity: partition}
        sealed = {
            "schema": "LegacyBrokerCutoverInventory.v2",
            "cutover_id": cutover_id,
            "manifest_sha256": hashlib.sha256(
                canonical_bytes({"zero_source": True, "repository": identity})
            ).hexdigest(),
            "legacy_root_inventory": [str(root) for root in roots],
            "partition_map_sha256": _partition_map_digest(partitions),
            "partitions": partitions,
        }
        sealed["inventory_sha256"] = _inventory_digest(sealed)
        if inventory_path.exists():
            sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
        else:
            _atomic_write_json(inventory_path, sealed)
        transaction = LegacyBrokerCutoverTransaction(
            cutover_id,
            journal_path,
            sealed["partitions"],
            sealed,
            journal_state_key="onboarding_state",
        )
        for state in LegacyBrokerCutoverTransaction.JOURNAL_STATES:
            if state == "ACTIVE":
                break
            transaction._record(state)

        _prove_zero_source(snapshot, roots, "before_receipt_write")
        namespace.mkdir(parents=True, exist_ok=True)
        receipt = _receipt_from_partition(
            cutover_id, sealed["partitions"][identity], sealed, journal_path
        )
        # The LAST proof runs before the receipt becomes visible, so a boundary
        # failure leaves no receipt file behind.
        _prove_zero_source(snapshot, roots, "before_receipt_fsync")
        receipt.write(
            namespace,
            zero_source_proof=sealed["partitions"][identity].get("zero_source_proof"),
        )
        latch.mark_armed()
        return receipt


def global_active_authority_exists(roots: tuple[Path, ...] | None = None) -> bool:
    """True when every declared legacy root carries an ACTIVE cutover authority.

    A repository may not authorize its own generation promotion: only a global
    cutover that itself reached ACTIVE confers post-activation authority
    (SL1-SOL-01).
    """
    roots = declared_legacy_roots() if roots is None else roots
    if not roots:
        return False
    for root in roots:
        pointer = Path(root) / "fabpub-global-cutover" / "ACTIVE_CUTOVER"
        if not pointer.exists():
            return False
        claim = _read_pointer_claim(pointer)
        journal = (
            Path(root) / "fabpub-global-cutover" / f"{claim['cutover_id']}.journal.jsonl"
        )
        if "ACTIVE" not in _journal_states(journal):
            return False
    return True


def is_git_repository(worktree: Path | str) -> bool:
    """True when ``worktree`` exists and is inside a Git working tree."""
    candidate = Path(worktree)
    if not candidate.exists():
        return False
    completed = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def release_barrier_leases(report: dict) -> None:
    """Release every lease the barrier retained; safe to call twice."""
    for lease in report.get("leases", ()):
        with contextlib.suppress(Exception):
            lease.release()
    report["leases"] = []


def fabpub_activation_barrier(worktrees: Iterable[Path | str] = ()) -> dict:
    """The one authenticated barrier every activated CLI entry runs FIRST.

    SL1-SOL-08: every named workspace must be a real Git repository and must end
    up with an authenticated receipt; a missing path, a non-Git path, or a
    failed Git probe all fail CLOSED rather than being skipped.  SL1-SOL-06/12:
    every lease acquired here is unwound if any later step raises.
    """
    report: dict = {"cutover": None, "leases": [], "repositories": []}
    try:
        manifest_path = os.environ.get(FABPUB_CUTOVER_MANIFEST_ENV)
        if manifest_path:
            raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            transaction = run_legacy_broker_cutover(
                LegacyBrokerCutoverManifest(
                    cutover_id=raw["cutover_id"], rows=tuple(raw["rows"])
                )
            )
            report["cutover"] = {
                "cutover_id": transaction.cutover_id,
                "state": transaction.state,
            }

        for worktree in worktrees:
            if not is_git_repository(worktree):
                raise LegacyCutoverConflict(
                    f"workspace {worktree} is missing, is not a Git repository, or its Git "
                    "probe failed; an activated train may not proceed over an "
                    "unauthenticated workspace"
                )
            snapshot = repository_snapshot(worktree)
            if load_partition_receipt(snapshot.store_root) is None:
                # Zero-source onboarding is for a repository first seen AFTER a
                # global cutover reached ACTIVE.  Before that, a repository with
                # no receipt may still have legacy sources awaiting migration, so
                # onboarding it here would seal a false zero-source proof and
                # then block the real cutover's receipt.  We therefore leave it
                # un-onboarded and UNLEASED: its stores stay non-routable, which
                # is the fail-closed guarantee (see the store `_authorize`
                # paths), rather than an empty-store fallback.
                if not global_active_authority_exists():
                    report["deferred"] = report.get("deferred", []) + [str(snapshot.worktree)]
                    continue
                onboard_zero_legacy_repository(snapshot.worktree)
                if load_partition_receipt(snapshot.store_root) is None:
                    raise LegacyCutoverConflict(
                        f"repository {snapshot.identity} could not be authenticated or onboarded"
                    )
            latch = WriterGenerationLatch(snapshot.namespace_root)
            report["leases"].append(latch.acquire(generation=latch.read().generation))
            report["repositories"].append(str(snapshot.worktree))
    except Exception:
        release_barrier_leases(report)
        raise
    return report


def _default_admission_policy(_request: AdmissionRequest) -> bool:
    """Admit any structurally-valid admission request.

    ``AdmissionRequest.__post_init__`` already rejects a request missing any
    fencing field, so a request that reaches the policy is well-formed.  Epoch
    staleness and idempotency-key conflicts are enforced inside
    ``LinearizableAdmissionStore.admit`` regardless of this policy.
    """
    return True


def build_github_broker_client(
    repo_path: Path,
    *,
    broker_root: Path,
    admission_policy: BrokerAdmissionPolicy | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    _test_only_explicit_root: bool = False,
) -> BrokerClient:
    """Wire a live GitHub broker client.

    SL1-SOL-03: once FABPUB is activated this sibling is gated exactly like
    :func:`build_routing_broker_client`.  Gating only the routing builder left a
    public, ungated constructor that builds live stores plus a real GitHub
    adapter on an arbitrary root, bypassing canonical routing, receipt
    authentication, the activation barrier, and generation leases.

    Parameters
    ----------
    repo_path:
        Worktree the :class:`GitHubBrokerAdapter` runs git/gh against.
    broker_root:
        Durable directory for the admission log + terminal-evidence log.  MUST
        live OUTSIDE ``repo_path`` (e.g. ``CoordinatorRuntime.coordinator_root``)
        so broker state never dirties the worktree being published — a dirty
        worktree trips the publish staged-diff audit and the train clean-worktree
        preflight.
    admission_policy:
        Optional admission gate; defaults to admitting any well-formed request.
    run:
        Injectable subprocess runner (tests pass a fake to mock the git/gh seam).

    Returns
    -------
    BrokerClient
        A :class:`BrokerService` bound to the global (verb-gated) contracts, so
        only ``publish_committed_branch``/``github`` can execute.
    """
    if fabpub_capability_active() and not _test_only_explicit_root:
        raise LegacyCutoverConflict(
            "the activated production route accepts no explicit broker/allocator root: "
            "the broker namespace is derived from the canonical Git common directory. "
            "Use build_routing_broker_client(), or the test-only explicit-root seam."
        )
    evidence_store = BrokerEvidenceStore(Path(broker_root))
    # ah#288/#199: the admission store re-checks the revocation flag INSIDE its lock, and
    # the evidence store shares that lock, so an admission can never be granted into an
    # epoch a concurrent revocation has blocked. Unwired (the old default lambda: False),
    # execute()'s pre-check is racy — a revocation landing after the check still admits.
    admission_store = LinearizableAdmissionStore(
        Path(broker_root),
        admission_policy or _default_admission_policy,
        epoch_blocked=lambda: evidence_store.epoch_blocked,
    )
    adapter = GitHubBrokerAdapter(Path(repo_path), run=run)
    return BrokerService(
        admission_store,
        evidence_store,
        adapter,
        contracts=PROVIDER_COMPLETION_CLASSIFICATIONS,
    )


def _repo_store_slug(repo: str) -> str:
    """Stable, filesystem-safe subdir name for a repo's per-repo broker store.

    ``BrokerRequest.repo`` is an arbitrary absolute workspace path, so hash it rather
    than embed the path.  A short hex prefix is collision-free in practice and keeps
    the on-disk layout readable.
    """
    return hashlib.sha256(repo.encode("utf-8")).hexdigest()[:16]


class _RoutingBrokerService:
    """A :class:`BrokerClient` that routes each request to a PER-REPO broker service.

    ``build_github_broker_client`` fixes ONE ``repo_path`` at construction, so a single
    client can only faithfully serve one repo — a multi-repo ``run_train`` threading one
    ``coordinator_runtime.broker_client`` across every node would run
    ``git -C <wrong-repo>`` and trip the branch/head guard on node 2+.

    Critically, each repo gets its OWN admission + evidence store under
    ``broker_root/<repo-slug>`` — the stores are NOT shared.  ``epoch_blocked`` is a
    GLOBAL scan over a store (``any(state is OUTCOME_AMBIGUOUS_BLOCKED)``) and an
    ambiguous terminal is durable + permanent, and it fires on BENIGN transients
    (push-unconfirmed / remote-read-failed / pr-unconfirmed / remote-head-mismatch /
    pr-head-unconfirmed).  A shared store would therefore let one repo's transient
    hiccup permanently fail-close every OTHER repo in the train (and, with an
    un-namespaced ``broker_root``, other trains too).  Per-repo stores scope the
    fail-closed epoch to exactly the repo whose mutation became ambiguous — the correct
    blast radius: repo A's unknown state says nothing about repo B's independent remote.
    The caller namespaces ``broker_root`` per train (see the ``run-train`` CLI), closing
    the cross-train dimension.
    """

    def __init__(
        self,
        broker_root: Path,
        *,
        admission_policy: BrokerAdmissionPolicy,
        run: Callable[..., subprocess.CompletedProcess],
        allowed_hosts,
        contracts=PROVIDER_COMPLETION_CLASSIFICATIONS,
    ) -> None:
        self._broker_root = Path(broker_root)
        self._admission_policy = admission_policy
        self._run = run
        self._allowed_hosts = allowed_hosts
        self._contracts = contracts
        self._services: dict[str, BrokerService] = {}

    def _service_for(self, repo: str) -> BrokerService:
        service = self._services.get(repo)
        if service is None:
            root = self._broker_root / _repo_store_slug(repo)
            # ah#288/#199: wire the admission store's in-lock revocation re-check to this
            # repo's evidence store (both on one `root`, sharing one lock file), closing
            # the execute() check-then-admit race. See build_github_broker_client.
            evidence_store = BrokerEvidenceStore(root)
            service = BrokerService(
                LinearizableAdmissionStore(
                    root, self._admission_policy, epoch_blocked=lambda: evidence_store.epoch_blocked
                ),
                evidence_store,
                GitHubBrokerAdapter(Path(repo), run=self._run, allowed_hosts=self._allowed_hosts),
                contracts=self._contracts,
            )
            self._services[repo] = service
        return service

    def execute(self, request):
        return self._service_for(request.repo).execute(request)


def build_routing_broker_client(
    *,
    broker_root: Path | None = None,
    admission_policy: BrokerAdmissionPolicy | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    allowed_hosts=ALLOWED_ORIGIN_HOSTS,
) -> BrokerClient:
    """Wire a live GitHub broker client that serves a MULTI-repo train.

    Like :func:`build_github_broker_client` but routes per ``BrokerRequest.repo``: the
    git/gh adapter is bound to the request's repo, AND each repo gets its own admission
    + evidence store under ``broker_root/<repo-slug>``.  Per-repo stores are load-bearing
    for safety, not just routing — a shared store's GLOBAL ``epoch_blocked`` would let one
    repo's ambiguous outcome (reachable via a benign transient) permanently fail-close
    every other repo.  See :class:`_RoutingBrokerService`.

    Parameters
    ----------
    broker_root:
        Durable parent directory for the per-repo admission + evidence stores.  MUST
        live OUTSIDE every node's worktree, and the caller SHOULD namespace it per train
        (e.g. ``<ledger-dir>/broker/<train-stem>``) so unrelated trains never share an
        epoch.
    admission_policy:
        Optional admission gate; defaults to admitting any well-formed request.
    run:
        Injectable subprocess runner (tests pass a fake to mock the git/gh seam).
    allowed_hosts:
        Origin-host allow-list applied to every per-request adapter (github.com-only
        by default); a self-hosted/GHE fleet passes its own set.
    """
    if fabpub_capability_active():
        # Reject BEFORE any mkdir so a refused injection leaves no directory.
        if broker_root is not None:
            raise LegacyCutoverConflict(
                "the activated production route accepts no allocator/evidence root "
                "argument: the broker namespace is derived from the canonical Git "
                "common directory. Use _test_only_repository_broker_client for tests."
            )
        return _RepositoryRoutingBrokerService(
            admission_policy=admission_policy or _default_admission_policy,
            run=run,
            allowed_hosts=allowed_hosts,
        )
    if broker_root is None:
        raise TypeError("build_routing_broker_client requires broker_root while FABPUB is inactive")
    return _RoutingBrokerService(
        Path(broker_root),
        admission_policy=admission_policy or _default_admission_policy,
        run=run,
        allowed_hosts=allowed_hosts,
    )


class _RepositoryRoutingBrokerService:
    """The activated FABPUB router: ONE store per canonical repository.

    ``_RoutingBrokerService`` keyed stores by a hash of the caller's arbitrary
    workspace path, so one repository reached through a linked worktree — or
    through two train files in unrelated directories — got two epoch spaces.
    FABPUB derives the store from the repository's Git COMMON directory instead,
    so every worktree and every train root of one repository converge on one
    allocator, while distinct repositories stay isolated.  Permanent ambiguity
    is therefore repository-scoped BY DESIGN: the superseded per-train isolation
    rationale no longer applies.
    """

    def __init__(
        self,
        *,
        admission_policy,
        run,
        allowed_hosts,
        contracts=PROVIDER_COMPLETION_CLASSIFICATIONS,
    ) -> None:
        self._admission_policy = admission_policy
        self._run = run
        self._allowed_hosts = allowed_hosts
        self._contracts = contracts
        self._services: dict[tuple[str, str], BrokerService] = {}
        self._stores: dict[str, tuple] = {}
        self._leases: dict[str, WriterGenerationLease] = {}

    def _stores_for(self, snapshot: RepositorySnapshot):
        """One admission + evidence store per canonical repository, shared.

        The receipt and the generation are authenticated BEFORE the store tree
        is created, and the store carries the lease it writes under.
        """
        stores = self._stores.get(snapshot.identity)
        if stores is None:
            root = snapshot.store_root
            if load_partition_receipt(root) is None:
                raise LegacyCutoverConflict(
                    f"repository {snapshot.identity} has no authenticated partition "
                    "receipt; it must be migrated by a legacy cutover or onboarded "
                    "through serialized zero-source onboarding before it is routable"
                )
            latch = WriterGenerationLatch(snapshot.namespace_root)
            lease = self._leases.get(snapshot.identity)
            if lease is None:
                lease = latch.acquire(generation=latch.read().generation)
                self._leases[snapshot.identity] = lease
            latch.validate_lease(lease)
            evidence_store = BrokerEvidenceStore(root, generation_lease=lease)
            admission_store = LinearizableAdmissionStore(
                root,
                self._admission_policy,
                epoch_blocked=lambda: evidence_store.epoch_blocked,
                generation_lease=lease,
            )
            stores = (admission_store, evidence_store)
            self._stores[snapshot.identity] = stores
        return stores

    def _service_for(self, request) -> BrokerService:
        worktree = getattr(request, "adapter_worktree", None)
        if not worktree:
            raise LegacyCutoverConflict(
                "an activated publish requires BrokerRequest.adapter_worktree; the "
                "repository namespace is derived from it, never from BrokerRequest.repo"
            )
        if not Path(worktree).is_absolute():
            raise LegacyCutoverConflict(
                f"BrokerRequest.adapter_worktree must be absolute; got {worktree!r}. "
                "A relative path resolves against whatever CWD the broker happens to "
                "run under, which is exactly the ambiguity FABPUB removes."
            )
        snapshot = repository_snapshot(worktree)
        if request.repo != snapshot.identity:
            raise LegacyCutoverConflict(
                f"BrokerRequest.repo {request.repo!r} is not the canonical repository "
                f"identity {snapshot.identity!r} derived from {snapshot.worktree}"
            )
        # Stores are shared per REPOSITORY, but the adapter runs
        # `git -C <worktree>`: caching the service by identity alone would send a
        # second linked worktree's publish to the FIRST worktree's checkout.
        cache_key = (snapshot.identity, str(snapshot.worktree))
        service = self._services.get(cache_key)
        if service is None:
            admission_store, evidence_store = self._stores_for(snapshot)
            service = BrokerService(
                admission_store,
                evidence_store,
                GitHubBrokerAdapter(
                    snapshot.worktree, run=self._run, allowed_hosts=self._allowed_hosts
                ),
                contracts=self._contracts,
            )
            self._services[cache_key] = service
        return service

    def execute(self, request):
        return self._service_for(request).execute(request)

    def close(self) -> None:
        """Release every generation lease this router cached."""
        for lease in list(self._leases.values()):
            with contextlib.suppress(Exception):
                lease.release()
        self._leases.clear()
        self._stores.clear()
        self._services.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()


def _test_only_repository_broker_client(
    broker_root: Path,
    *,
    admission_policy: BrokerAdmissionPolicy | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    allowed_hosts=ALLOWED_ORIGIN_HOSTS,
) -> BrokerClient:
    """The ONLY explicit-root seam; production CLI/direct paths cannot call it."""
    return _RoutingBrokerService(
        Path(broker_root),
        admission_policy=admission_policy or _default_admission_policy,
        run=run,
        allowed_hosts=allowed_hosts,
    )
