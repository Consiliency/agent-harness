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
import re
import subprocess
import sys
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from phase_loop_runtime.convergence.contracts import (
    AdmissionRequest,
    DeltaReadmitAuthority,
    DeltaReadmitReceipt,
)
from phase_loop_runtime.convergence.provider_contracts import PROVIDER_COMPLETION_CLASSIFICATIONS

from .admission import BrokerAdmissionPolicy, LinearizableAdmissionStore
from .credsep import ALLOWED_ORIGIN_HOSTS, GitHubBrokerAdapter
from .evidence import BrokerEvidenceStore
from .verbs import BrokerClient, BrokerService

_CANONICAL_GITHUB_BROKER_ADAPTER = GitHubBrokerAdapter
_CANONICAL_PROVIDER_RUN = subprocess.run

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
#: Partition generations (ah#789 Workstream D): generation 0 is the container
#: ``repositories/<identity>/`` itself; generation ``n >= 1`` lives at
#: ``<container>/generations/<n>/`` and ``<container>/generations/ACTIVE`` is a
#: regular file naming the routable generation.  A rotation never moves bytes.
GENERATIONS_DIR = "generations"
ACTIVE_POINTER = "ACTIVE"
#: Per-authority rotation ceremony files: ``<authority>/partition-rotations/<identity>/``.
ROTATION_CEREMONY_DIR = "partition-rotations"

GENERATION_BLOCKER = "legacy_writer_after_fabpub_activation"
CUTOVER_BLOCKER = "legacy_cutover_conflict"
ROTATION_BLOCKER = "partition_rotation_refused"
ROUTING_BLOCKER = "partition_routing_refused"
RECEIPT_INCOMPATIBLE_BLOCKER = "partition_receipt_incompatible"


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


class PartitionRotationRefused(PermissionError):
    """A blocked-partition rotation ceremony refused before/without a durable step.

    Never a ``LegacyCutoverConflict``: a rotation refusal is a typed operator
    outcome, not an integrity failure of the existing authority.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(f"{ROTATION_BLOCKER}: {detail}")


class PartitionRoutingRefused(PermissionError):
    """The generation pointer cannot name a routable store; nothing falls back."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"{ROUTING_BLOCKER}: {detail}")


class PartitionReceiptIncompatible(PermissionError):
    """A partition receipt carries a schema this reader does not speak."""

    def __init__(self, schema: object, path: Path) -> None:
        self.schema = schema
        self.path = Path(path)
        super().__init__(
            f"{RECEIPT_INCOMPATIBLE_BLOCKER}: unknown partition receipt schema "
            f"{schema!r} at {path}"
        )


class SealedWorktreeFallbackWarning(RuntimeWarning):
    """A sealed inventory row's worktree was pruned; its recorded common dir stood in."""


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
    return _parse_strict_jsonl(path.read_text(encoding="utf-8"), label=label, path=path)


def _parse_strict_jsonl(body: str | None, *, label: str, path: Path) -> list[tuple[str, dict]]:
    """The parse half of :func:`read_strict_jsonl` over text already read.

    ``None`` is a missing log.  A rotation adjudicates a predecessor from the
    ONE snapshot it digested (:class:`_PredecessorSnapshot`), so the parse
    cannot be allowed to read the file again; ``path`` names the log in the
    refusal only.  The snapshot decodes raw bytes, so a ``\r``-terminated line
    the live reader's universal newlines would fold is a torn-append refusal
    here; no writer in the package emits ``\r`` and the divergence is
    fail-closed (fable r11 O2).
    """
    if body is None:
        return []
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
    def container(self) -> Path:
        """Generation 0: ``<namespace-root>/repositories/<identity>`` (never moves)."""
        return self.namespace_root / "repositories" / self.identity

    @property
    def store_root(self) -> Path:
        """The ACTIVE generation's store, resolved through the generation pointer.

        Raises ``PartitionRoutingRefused`` when the pointer cannot name a
        routable generation; there is no fallback to generation 0.
        """
        return active_store_root(self.container)


def _partition_layout(root: Path) -> tuple[Path, int]:
    """``(container, generation)`` for a generation-0 container or a ``generations/<n>`` store."""
    root = Path(root)
    if root.parent.name == GENERATIONS_DIR and root.name.isdigit():
        return root.parent.parent, int(root.name)
    return root, 0


def _is_canonical_container(container: Path) -> bool:
    return (
        container.parent.name == "repositories"
        and container.parent.parent.name == REPOSITORY_NAMESPACE_DIR
    )


def is_canonical_store_root(root: Path) -> bool:
    """Whether ``root`` is a canonical FABPUB store (generation 0 or a generation store)."""
    container, _generation = _partition_layout(root)
    return _is_canonical_container(container)


_ACTIVE_POINTER_BODY = re.compile(rb"[0-9]+\n")


def _read_active_generation(container: Path) -> int:
    """Read ``<container>/generations/ACTIVE``; every malformed state is a typed refusal."""
    container = Path(container)
    generations = container / GENERATIONS_DIR
    if not os.path.lexists(generations):
        return 0
    if generations.is_symlink() or not generations.is_dir():
        raise PartitionRoutingRefused(f"{generations} is not a generations directory")
    pointer = generations / ACTIVE_POINTER
    if pointer.is_symlink():
        raise PartitionRoutingRefused(f"generation pointer is a symlink: {pointer}")
    if not os.path.lexists(pointer):
        raise PartitionRoutingRefused(f"generation pointer is missing: {pointer}")
    if not pointer.is_file():
        raise PartitionRoutingRefused(f"generation pointer is not a regular file: {pointer}")
    try:
        with pointer.open("rb") as stream:
            body = stream.read()
    except OSError as error:
        raise PartitionRoutingRefused(f"generation pointer unreadable: {pointer}: {error}")
    if not _ACTIVE_POINTER_BODY.fullmatch(body):
        raise PartitionRoutingRefused(f"generation pointer is torn or non-integer: {pointer}")
    generation = int(body)
    if generation == 0:
        return 0
    store = generations / str(generation)
    if store.is_symlink() or not store.is_dir():
        raise PartitionRoutingRefused(
            f"generation pointer names a nonexistent generation {generation}: {pointer}"
        )
    receipt = store / RECEIPT_FILENAME
    if receipt.is_symlink() or not receipt.is_file():
        raise PartitionRoutingRefused(
            f"generation {generation} carries no partition receipt: {store}"
        )
    return generation


def active_store_root(container: Path) -> Path:
    """The ACTIVE generation's store root for ``container`` (generation 0 = the container)."""
    container = Path(container)
    generation = _read_active_generation(container)
    if generation == 0:
        return container
    return container / GENERATIONS_DIR / str(generation)


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
        """Derive the latch from a container OR a ``generations/<n>`` store under it."""
        container, _generation = _partition_layout(Path(store_root))
        return cls(container.parent.parent)

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
            if snapshot.generation_state != "DRAINING":
                raise LegacyCutoverConflict(
                    f"illegal generation transition {snapshot.generation_state} -> ACTIVE"
                )
            self._write(WriterGenerationSnapshot(_fresh_nonce(), "ACTIVE"))

    def resume_active(self) -> None:
        """``DRAINING -> ACTIVE`` preserving the nonce: undo a drain that changed nothing.

        Used ONLY by a rotation ceremony that refused after draining (its
        in-lock digest check failed).  No authority changed hands, so the
        generation nonce every live lease binds is kept; a fresh nonce here
        would revoke leases the ceremony never fenced.
        """
        with self.exclusive():
            snapshot = self.read()
            if snapshot.generation_state != "DRAINING":
                return
            self._write(WriterGenerationSnapshot(snapshot.generation, "ACTIVE"))

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
    _require_active_generation_root(store_root)


def _require_active_generation_root(root: Path) -> None:
    """A canonical store may only be written while it IS the ACTIVE generation.

    Generation 0 after a rotation, or a superseded ``generations/<n>``, keeps
    its bytes forever but accepts no append; a pointer that cannot resolve is
    the same refusal (``PartitionRoutingRefused`` is a ``PermissionError``).
    """
    root = Path(root)
    container, _generation = _partition_layout(root)
    if not _is_canonical_container(container):
        return
    active = active_store_root(container)
    if active != root:
        raise WriterGenerationBlocked(
            f"{root} is not the ACTIVE partition generation (active store is {active}); "
            "refusing to append to a superseded generation"
        )


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


ROTATION_STATES = ("DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE")
ROTATION_JOURNAL_SCHEMA = "PartitionRotationJournal.v1"
ROTATION_INVENTORY_SCHEMA = "PartitionRotationInventory.v1"
ROTATION_ATTESTATION_SCHEMA = "PartitionRotationAttestation.v1"
DISPOSITION_OBSERVED_LANDED = "observed_landed"
DISPOSITION_ATTESTED_NOT_LANDED = "attested_not_landed"
ROTATION_DIGESTED_FILES = (
    "admissions.jsonl",
    "evidence.jsonl",
    RECEIPT_FILENAME,
    "adapter-start-owner.json",
)
ROTATION_STORE_FILES = ROTATION_DIGESTED_FILES + (
    "admissions.lock",
    "legacy-promotions.jsonl",
)


def _sha256_file(path: Path) -> str:
    """sha256 of the file's bytes; a missing file digests as empty bytes."""
    path = Path(path)
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def _rotation_states_well_formed(states: list[str]) -> bool:
    return bool(states) and tuple(states) == ROTATION_STATES[: len(states)]


@dataclass(frozen=True)
class RotatedPartitionReceipt:
    """The receipt governing a rotated generation store (``generations/<n>``).

    A rotated generation is authenticated by a CHAIN: its own sealed rotation
    inventory + ARMED rotation journal reproduce these exact bytes, AND the
    predecessor generation's digested files still equal the digests sealed at
    rotation time, AND the predecessor itself still authenticates. Any drift
    anywhere in the chain refuses routing; nothing falls back.
    """

    cutover_id: str
    canonical_repository_identity: str
    target_namespace: str
    generation: int
    predecessor_generation: int
    predecessor_digests: dict
    adjudicated_effect_dispositions: dict
    attestation_sha256: str
    legacy_epoch_high_water: int
    legacy_completed_effect_keys: tuple
    global_journal_path: str
    inventory_sha256: str = ""
    partition_map_sha256: str = ""
    manifest_sha256: str = ""
    legacy_root_inventory: tuple = ()
    ambiguous: bool = False
    zero_source: bool = False

    SCHEMA = "LegacyRepositoryPartitionReceipt.v3"

    @property
    def rotation_cutover_id(self) -> str:
        return self.cutover_id

    def payload(self) -> dict:
        return {
            "schema": self.SCHEMA,
            "cutover_id": self.cutover_id,
            "rotation_cutover_id": self.cutover_id,
            "canonical_repository_identity": self.canonical_repository_identity,
            "target_namespace": self.target_namespace,
            "generation": self.generation,
            "predecessor_generation": self.predecessor_generation,
            "predecessor_digests": dict(self.predecessor_digests),
            "adjudicated_effect_dispositions": {
                key: dict(value) for key, value in self.adjudicated_effect_dispositions.items()
            },
            "attestation_sha256": self.attestation_sha256,
            "legacy_epoch_high_water": self.legacy_epoch_high_water,
            "legacy_completed_effect_keys": list(self.legacy_completed_effect_keys),
            "global_journal_path": self.global_journal_path,
            "inventory_sha256": self.inventory_sha256,
            "partition_map_sha256": self.partition_map_sha256,
            "manifest_sha256": self.manifest_sha256,
            "legacy_root_inventory": list(self.legacy_root_inventory),
            "ambiguous": self.ambiguous,
            "zero_source": self.zero_source,
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self.payload())).hexdigest()

    def file_bytes(self) -> bytes:
        return canonical_bytes(self.payload()) + b"\n"

    def write(self, root: Path) -> Path:
        """Write byte-exactly; an existing receipt must already be these bytes."""
        root = Path(root)
        path = root / RECEIPT_FILENAME
        expected = self.file_bytes()
        if path.exists():
            _require_no_ancestor_symlink(path)
            if path.read_bytes() != expected:
                raise LegacyCutoverConflict(
                    f"rotated partition receipt at {path} differs from the sealed rotation"
                )
            return path
        _atomic_write_json(path, json.loads(expected))
        return path


def _rotation_receipt_from_partition(
    cutover_id: str, partition: dict, sealed: dict, journal: Path
) -> RotatedPartitionReceipt:
    try:
        return RotatedPartitionReceipt(
            cutover_id=cutover_id,
            canonical_repository_identity=str(partition["canonical_repository_identity"]),
            target_namespace=str(Path(partition["target_namespace"])),
            generation=int(partition["generation"]),
            predecessor_generation=int(partition["predecessor_generation"]),
            predecessor_digests={
                str(name): str(digest) for name, digest in partition["predecessor_digests"].items()
            },
            adjudicated_effect_dispositions={
                str(key): dict(value)
                for key, value in partition["adjudicated_effect_dispositions"].items()
            },
            attestation_sha256=str(sealed.get("attestation_sha256", "")),
            legacy_epoch_high_water=int(partition["legacy_epoch_high_water"]),
            legacy_completed_effect_keys=tuple(partition["legacy_completed_effect_keys"]),
            global_journal_path=str(journal),
            inventory_sha256=str(sealed.get("inventory_sha256", "")),
            partition_map_sha256=str(sealed.get("partition_map_sha256", "")),
            manifest_sha256=str(sealed.get("manifest_sha256", "")),
            legacy_root_inventory=tuple(sealed.get("legacy_root_inventory", ())),
            ambiguous=bool(partition.get("ambiguous", False)),
            zero_source=False,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise LegacyCutoverConflict(
            f"the sealed rotation partition for {cutover_id!r} is malformed: {exc}"
        ) from exc


def _require_rotation_receipt_binds(
    expected: RotatedPartitionReceipt, container: Path, generation: int, path: Path
) -> Path:
    """The bindings a rotated receipt must carry to govern ``generation`` of ``container``.

    ONE definition, called by the loader on the receipt it read and by the
    ceremony on the receipt its sealed inventory would produce on resume
    (codex r6 P1): identity, container, chain, and the predecessor's bytes.
    The digests seal an inventory's CONSISTENCY, not its truth — a partition
    re-sealed under both digests is internally consistent and still binds
    nothing.  Returns the predecessor store.
    """
    if expected.canonical_repository_identity != container.name:
        raise LegacyCutoverConflict(
            "partition receipt is bound to a different canonical repository identity"
        )
    if Path(expected.target_namespace) != container:
        raise LegacyCutoverConflict(
            "rotated partition receipt is bound to a different repository container"
        )
    if expected.generation != generation or expected.predecessor_generation != generation - 1:
        raise LegacyCutoverConflict(
            f"rotated partition receipt at {path} does not chain to generation {generation - 1}"
        )
    predecessor = (
        container if generation == 1 else container / GENERATIONS_DIR / str(generation - 1)
    )
    for name in ROTATION_DIGESTED_FILES:
        if _sha256_file(predecessor / name) != expected.predecessor_digests.get(name):
            raise PartitionRoutingRefused(
                f"predecessor generation {generation - 1} of {container} drifted since "
                f"rotation {expected.cutover_id!r} sealed it ({name}); generation {generation} is "
                "not routable"
            )
    return predecessor


def _load_rotated_partition_receipt(
    store_root: Path, path: Path, raw: dict
) -> RotatedPartitionReceipt:
    """Authenticate a v3 receipt: own seal, exact bytes, then the predecessor chain."""
    container, generation = _partition_layout(store_root)
    if generation < 1:
        raise LegacyCutoverConflict(
            f"a rotated partition receipt may not govern the container store {store_root}"
        )
    cutover_id = raw.get("cutover_id", "")
    # The receipt's cutover_id names the journal and inventory paths below; a
    # receipt-controlled id that is absolute or traverses (``/x``, ``../x``)
    # would carry the lookup outside the governing authority (codex r2
    # finding 2).  The same grammar the ceremony enforces at entry applies.
    try:
        _validate_cutover_id(cutover_id)
    except LegacyCutoverConflict as exc:
        raise LegacyCutoverConflict(
            f"rotated partition receipt at {path} carries an invalid cutover_id: {exc}"
        ) from exc
    identity = raw.get("canonical_repository_identity", "")
    if identity != container.name:
        raise LegacyCutoverConflict(
            "partition receipt is bound to a different canonical repository identity"
        )
    if raw.get("generation") != generation:
        raise LegacyCutoverConflict(
            f"rotated partition receipt at {path} names generation {raw.get('generation')!r} "
            f"but governs generation {generation}"
        )
    if Path(str(raw.get("target_namespace", ""))) != container:
        raise LegacyCutoverConflict(
            "rotated partition receipt is bound to a different repository container"
        )
    journal = Path(raw.get("global_journal_path", ""))
    base = load_partition_receipt(container)
    if base is None or isinstance(base, RotatedPartitionReceipt):
        raise LegacyCutoverConflict(f"rotated partition {identity} has no container receipt")
    expected_journal = _expected_rotation_journal(base, identity, cutover_id)
    if expected_journal is None:
        raise LegacyCutoverConflict(
            f"rotated partition {identity} is not governed by a zero-history bootstrap container "
            "receipt; only bootstrap-governed partitions rotate"
        )
    if journal != expected_journal:
        raise LegacyCutoverConflict(
            f"the receipt's rotation journal {journal} is not the governing authority's "
            f"partition-rotations journal for {cutover_id!r}"
        )
    if journal.is_symlink() or not journal.is_file():
        raise LegacyCutoverConflict("the receipt's rotation journal is missing")
    states, ids = _journal_entries(journal)
    if not _rotation_states_well_formed(states) or "ARMED" not in states:
        raise LegacyCutoverConflict("the receipt's rotation ceremony is not ARMED")
    if set(ids) != {cutover_id}:
        raise LegacyCutoverConflict("the receipt's cutover_id does not match its rotation journal")
    inventory_path = journal.parent / f"{cutover_id}.inventory.json"
    if not inventory_path.exists():
        raise LegacyCutoverConflict("the receipt's sealed rotation inventory is missing")
    sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
    if sealed.get("schema") != ROTATION_INVENTORY_SCHEMA:
        raise LegacyCutoverConflict("the sealed rotation inventory carries an unknown schema")
    if _inventory_digest(sealed) != sealed.get("inventory_sha256"):
        raise LegacyCutoverConflict("the sealed rotation inventory digest drifted")
    partition = sealed.get("partitions", {}).get(identity)
    if partition is None:
        raise LegacyCutoverConflict(
            "the receipt's repository is absent from its own sealed rotation partition map"
        )
    if _partition_map_digest(sealed.get("partitions", {})) != sealed.get("partition_map_sha256"):
        raise LegacyCutoverConflict("the sealed rotation partition map digest drifted")
    expected = _rotation_receipt_from_partition(cutover_id, partition, sealed, journal)
    if path.read_bytes() != expected.file_bytes():
        raise LegacyCutoverConflict(
            f"rotated partition receipt bytes at {path} do not equal the bytes its sealed "
            "rotation partition produces"
        )
    predecessor = _require_rotation_receipt_binds(expected, container, generation, path)
    if load_partition_receipt(predecessor) is None:
        raise LegacyCutoverConflict(
            f"predecessor generation {generation - 1} of {container} has no receipt"
        )
    return expected


def _expected_rotation_journal(
    base: LegacyRepositoryPartitionReceipt, identity: str, cutover_id: str
) -> Path | None:
    """Where D1 places a rotation's journal: under the GOVERNING authority root.

    The authority root is taken from the container receipt's bootstrap claim,
    never from the rotated receipt itself, so a receipt cannot name a journal
    and inventory outside the authority that governs it (codex r1 finding 3).
    ``None`` when the container is not bootstrap-governed.
    """
    # ``Path / cutover_id`` would replace the authority root with an absolute
    # id and walk out of it with ``..``; the id grammar admits neither.
    _validate_cutover_id(cutover_id)
    claim = _receipt_bootstrap_claim(base) if base.zero_source else None
    if claim is None:
        return None
    return (
        Path(claim["authority_root"])
        / ROTATION_CEREMONY_DIR
        / identity
        / f"{cutover_id}{_ROTATION_JOURNAL_SUFFIX}"
    )


def _rotation_base_receipt(receipt):
    """The container's v2 receipt behind a v3 receipt (v2 receipts pass through)."""
    if not isinstance(receipt, RotatedPartitionReceipt):
        return receipt
    base = load_partition_receipt(Path(receipt.target_namespace))
    if base is None:
        raise LegacyCutoverConflict(
            f"rotated partition {receipt.canonical_repository_identity} has no container receipt"
        )
    return base


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


def load_partition_receipt(
    store_root: Path,
) -> LegacyRepositoryPartitionReceipt | RotatedPartitionReceipt | None:
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
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        # A receipt whose bytes are not JSON is a refusal of THIS partition like
        # every other authentication failure, never a bare ``ValueError`` that
        # escapes the fail-closed ``except LegacyCutoverConflict`` sites the
        # ceremony and the resolver share (fable r10 O2, closed at the loader).
        raise LegacyCutoverConflict(
            f"partition receipt bytes at {path} are not JSON: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise LegacyCutoverConflict(f"partition receipt at {path} is not a JSON object")
    schema = raw.get("schema")
    if schema == RotatedPartitionReceipt.SCHEMA:
        return _load_rotated_partition_receipt(store_root, path, raw)
    if schema != LegacyRepositoryPartitionReceipt.SCHEMA:
        raise PartitionReceiptIncompatible(schema, path)
    if _partition_layout(store_root)[1] != 0:
        raise PartitionRoutingRefused(
            f"a container partition receipt may not govern the generation store {store_root}"
        )
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
    except (LegacyCutoverConflict, PermissionError):
        return True
    return bool(receipt is not None and receipt.ambiguous)


def sealed_partition_effects(receipt: LegacyRepositoryPartitionReceipt) -> dict[str, dict]:
    """The authenticated legacy completed effects for a receipt's partition.

    The sealed inventory is read ONCE and the bytes read must digest to the
    ``inventory_sha256`` (and ``partition_map_sha256``) the receipt carries.
    The receipt object is bound to its bytes by ``load_partition_receipt`` and,
    inside a rotation, by ``_require_receipt_is_snapshot``; this equality
    carries that binding through to the provenance the receipt points at, so
    the carried map is a function of bytes the receipt digests, never of
    whatever the inventory file holds at read time (fable r11 P1).
    """
    journal = Path(receipt.global_journal_path)
    inventory_path = journal.parent / f"{receipt.cutover_id}.inventory.json"
    try:
        raw = inventory_path.read_bytes()
    except FileNotFoundError:
        raw = None
    if raw is None:
        if receipt.legacy_completed_effect_keys:
            # The loader refused a missing inventory when it authenticated this
            # receipt; one missing NOW is post-load drift.  Name it, instead of
            # the key-set disagreement an empty map would produce (fable r12 O2).
            raise LegacyCutoverConflict(
                f"the sealed inventory at {inventory_path} is missing; the partition receipt "
                f"names {len(receipt.legacy_completed_effect_keys)} completed effect key(s) it "
                "must carry"
            )
        effects: dict = {}
    else:
        try:
            sealed = json.loads(raw)
        except ValueError as error:
            raise LegacyCutoverConflict(
                f"the sealed inventory at {inventory_path} is not JSON: {error}"
            ) from error
        if (
            not isinstance(sealed, dict)
            or _inventory_digest(sealed) != receipt.inventory_sha256
            or _partition_map_digest(sealed.get("partitions", {})) != receipt.partition_map_sha256
        ):
            raise LegacyCutoverConflict(
                f"the sealed inventory at {inventory_path} is not the inventory the partition receipt "
                "digests (inventory_sha256 / partition_map_sha256)"
            )
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
            / str(provenance.get("archive_cutover_id", receipt.cutover_id))
            / provenance["source_id"]
            if provenance.get("legacy_root") is not None
            and provenance.get("source_id") is not None
            else None
        )
        for filename, expected in (
            ("admissions.jsonl", provenance.get("admissions_digest")),
            ("evidence.jsonl", provenance.get("evidence_digest")),
        ):
            if expected is None or archive is None:
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


# --- ah#789 Workstream D: partition-rotation crash scaffolding --------------
ROTATION_CRASH_STEPS = (
    "before_generations_rename",
    "after_generations_rename",
    "between_successor_files",
    "after_successor_receipt_before_flip",
    "after_journal_draining",
    "after_journal_inventory_sealed",
    "after_journal_armed",
)
#: Crash points AFTER the pointer flip.  Generation 0 is no longer the routable
#: store at these points (the successor is), so they are swept separately from
#: ``ROTATION_CRASH_STEPS``: the invariant is "the successor routes, the barrier
#: refuses until the ceremony is ACTIVE, and a resume finishes it".
ROTATION_POST_FLIP_CRASH_STEPS = (
    "after_pointer_flip",
    "after_journal_active",
)
_ROTATION_CRASH_STEP: str | None = None


class _RotationCrash(RuntimeError):
    """Test-only simulated process death inside a partition rotation."""


@contextlib.contextmanager
def crash_at_rotation_step(step: str):
    global _ROTATION_CRASH_STEP
    if step not in ROTATION_CRASH_STEPS + ROTATION_POST_FLIP_CRASH_STEPS:
        raise ValueError(f"unknown rotation crash step {step!r}")
    previous, _ROTATION_CRASH_STEP = _ROTATION_CRASH_STEP, step
    try:
        yield
    finally:
        _ROTATION_CRASH_STEP = previous


class _RotationCompletedElsewhere(Exception):
    """Raised INSIDE the predecessor lock when the pointer already names this
    ceremony's successor: the caller finishes under the successor's lock."""

    def __init__(self, receipt: "RotatedPartitionReceipt") -> None:
        super().__init__(receipt.cutover_id)
        self.receipt = receipt


def _maybe_rotation_crash(step: str) -> None:
    if _ROTATION_CRASH_STEP == step:
        raise _RotationCrash(step)


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
            latch = WriterGenerationLatch(
                repository_namespace_root(_inventory_row_repository(partition))
            )
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
                    repository_namespace_root(
                        _inventory_row_repository(self.partitions[identity])
                    )
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
        WriterGenerationLatch.open(_inventory_row_repository(partitions[i]))
        for i in ordered_identities
    ]
    with _hold_all([latch.lock_path for latch in latches]):
        for latch in latches:
            if latch.read().generation_state == "LEGACY_OPEN":
                latch.begin_draining()
    for identity, latch in zip(ordered_identities, latches):
        if latch.read().generation_state == "DRAINING":
            latch.await_quiescent(worktree=_inventory_row_repository(partitions[identity]))

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
#: Optional override for the persistent zero-history bootstrap authority.
FABPUB_AUTHORITY_ROOT_ENV = "PHASE_LOOP_FABPUB_AUTHORITY_ROOT"

ZERO_HISTORY_INVENTORY_SCHEMA = "ZeroHistoryBootstrapInventory.v1"
ZERO_HISTORY_STATES = ("DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE")
ZERO_SOURCE_ONBOARDING_CUTOVER_ID = "fabpub-zero-legacy-onboarding"
_CUTOVER_ID_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def _validate_cutover_id(cutover_id: str) -> str:
    if (
        not isinstance(cutover_id, str)
        or not 1 <= len(cutover_id) <= 128
        or cutover_id[0] not in _CUTOVER_ID_CHARACTERS - {".", "_", "-"}
        or any(character not in _CUTOVER_ID_CHARACTERS for character in cutover_id)
    ):
        raise LegacyCutoverConflict(
            "cutover_id must be 1-128 ASCII letters, digits, dots, underscores, or "
            "hyphens and must start with a letter or digit"
        )
    return cutover_id


def default_fabpub_authority_root() -> Path:
    """Return the dedicated persistent zero-history authority directory."""
    override = os.environ.get(FABPUB_AUTHORITY_ROOT_ENV)
    if override:
        root = Path(override).expanduser()
    else:
        state_home = Path(
            os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
        ).expanduser()
        root = state_home / "phase-loop" / "fabpub" / "authority-v1"
    if not root.is_absolute():
        raise LegacyCutoverConflict("the FABPUB authority root must be absolute")
    return root.resolve()


def _canonical_input_path(path: Path | str, *, label: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise LegacyCutoverConflict(f"{label} must be an absolute path: {candidate}")
    _require_no_ancestor_symlink(candidate)
    return candidate.resolve()


def _tree_file_inventory(root: Path) -> list[dict]:
    files: list[dict] = []
    if not root.exists():
        return files
    _require_no_ancestor_symlink(root)
    for candidate in sorted(root.rglob("*"), key=str):
        if candidate.is_symlink():
            raise LegacyCutoverConflict(f"inventory path is a symlink: {candidate}")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise LegacyCutoverConflict(f"inventory path has an unsupported type: {candidate}")
        body = candidate.read_bytes()
        files.append(
            {
                "path": str(candidate.relative_to(root)),
                "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return files


def _is_atomic_temp_name(name: str, target_name: str) -> bool:
    prefix = f".{target_name}."
    if not name.startswith(prefix) or not name.endswith(".tmp"):
        return False
    middle = name[len(prefix) : -len(".tmp")]
    try:
        pid, nonce = middle.split(".")
    except ValueError:
        return False
    return pid.isdigit() and len(nonce) == 8 and all(
        character in "0123456789abcdef" for character in nonce
    )


def _legacy_root_file_inventory(root: Path) -> list[dict]:
    return [
        item
        for item in _tree_file_inventory(root)
        if not (
            item["path"].startswith("fabpub-global-cutover/")
            and item["path"].endswith(".lock")
        )
    ]


def _is_onboarding_atomic_temp(path: str, snapshot: RepositorySnapshot, cutover_id: str) -> bool:
    candidate = Path(path)
    if candidate.parent == Path("zero-legacy-onboarding"):
        return _is_atomic_temp_name(candidate.name, f"{cutover_id}.inventory.json")
    expected_parent = Path("repositories") / snapshot.identity
    return candidate.parent == expected_parent and _is_atomic_temp_name(
        candidate.name, RECEIPT_FILENAME
    )


def _discover_hashed_legacy_roots(search_roots: tuple[Path, ...]) -> tuple[Path, ...]:
    discovered: dict[str, Path] = {}
    for search_root in search_roots:
        if not search_root.exists():
            continue
        _require_no_ancestor_symlink(search_root)
        for ledger in search_root.rglob(".train-ledger"):
            if ledger.is_symlink():
                raise LegacyCutoverConflict(f"search discovered a symlinked ledger: {ledger}")
            broker = ledger / "broker"
            if broker.is_dir():
                resolved = _canonical_input_path(broker, label="discovered legacy root")
                discovered.setdefault(str(resolved), resolved)
    return tuple(discovered[key] for key in sorted(discovered))


def _receipt_bootstrap_claim(
    receipt: LegacyRepositoryPartitionReceipt,
) -> dict | None:
    journal = Path(receipt.global_journal_path)
    expected_journal = (
        Path(receipt.target_namespace).parent.parent
        / "zero-legacy-onboarding"
        / f"{receipt.cutover_id}.journal.jsonl"
    )
    if journal != expected_journal:
        return None
    inventory_path = journal.parent / f"{receipt.cutover_id}.inventory.json"
    try:
        _require_no_ancestor_symlink(inventory_path)
        sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
        authority_root = _canonical_input_path(
            sealed["bootstrap_authority_root"], label="bootstrap authority root"
        )
    except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if (
        sealed.get("schema") != "LegacyBrokerCutoverInventory.v2"
        or sealed.get("cutover_id") != receipt.cutover_id
        or _inventory_digest(sealed) != sealed.get("inventory_sha256")
        or sealed.get("inventory_sha256") != receipt.inventory_sha256
        or not isinstance(sealed.get("bootstrap_inventory_sha256"), str)
    ):
        return None
    return {
        "authority_root": authority_root,
        "inventory_sha256": sealed["bootstrap_inventory_sha256"],
    }


def _classify_repository_namespace(
    snapshot: RepositorySnapshot,
    cutover_id: str,
    *,
    bootstrap_inventory_sha256: str | None = None,
) -> dict:
    root = snapshot.namespace_root
    files = _tree_file_inventory(root)
    # Bootstrap ownership is a property of the CONTAINER receipt; the generation
    # pointer is deliberately not resolved here so one repository's unroutable
    # pointer never turns its siblings' re-validation into a host-wide refusal.
    container = snapshot.container
    if not root.exists():
        state = "absent"
    elif (container / RECEIPT_FILENAME).exists():
        receipt = load_partition_receipt(container)
        bootstrap_claim = (
            _receipt_bootstrap_claim(receipt) if receipt is not None else None
        )
        if (
            receipt is None
            or not receipt.zero_source
            or receipt.cutover_id != cutover_id
            or bootstrap_inventory_sha256 is None
            or bootstrap_claim is None
            or bootstrap_claim["inventory_sha256"] != bootstrap_inventory_sha256
        ):
            raise LegacyCutoverConflict(
                f"repository {snapshot.identity} has a receipt not owned by bootstrap "
                f"{cutover_id!r}"
            )
        state = "bootstrap_owned"
    else:
        allowed = {"writer-generation.json", "writer-generation.lock"}
        onboarding = root / "zero-legacy-onboarding"
        inventory_path = onboarding / f"{cutover_id}.inventory.json"
        journal_path = onboarding / f"{cutover_id}.journal.jsonl"
        partial_paths = {
            str(inventory_path.relative_to(root)),
            str(journal_path.relative_to(root)),
            str((onboarding / "cutover.lock").relative_to(root)),
        }
        allowed.update(partial_paths)
        unexpected = [
            item["path"]
            for item in files
            if item["path"] not in allowed
            and not _is_onboarding_atomic_temp(item["path"], snapshot, cutover_id)
        ]
        if unexpected:
            raise LegacyCutoverConflict(
                f"unattested canonical state for {snapshot.identity}: {unexpected}"
            )
        if inventory_path.exists():
            sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
            if _inventory_digest(sealed) != sealed.get("inventory_sha256"):
                raise LegacyCutoverConflict(
                    f"interrupted onboarding inventory drifted for {snapshot.identity}"
                )
            partition = sealed.get("partitions", {}).get(snapshot.identity)
            if (
                partition is None
                or not partition.get("zero_source")
                or Path(partition.get("target_namespace", "")) != container
                or not _recorded_worktree_binds(partition.get("worktree", ""), snapshot)
                or _partition_map_digest(sealed.get("partitions", {}))
                != sealed.get("partition_map_sha256")
            ):
                raise LegacyCutoverConflict(
                    f"interrupted onboarding inventory is not bound to {snapshot.identity} "
                    f"(recorded worktree {(partition or {}).get('worktree', '')!r}, "
                    f"observed worktree {str(snapshot.worktree)!r})"
                )
            if journal_path.exists():
                states, ids = _journal_entries(journal_path)
                expected = LegacyBrokerCutoverTransaction.JOURNAL_STATES[:-1]
                if set(ids) != {cutover_id} or tuple(states) != expected[: len(states)]:
                    raise LegacyCutoverConflict(
                        f"interrupted onboarding journal is not a valid prefix for {cutover_id!r}"
                    )
            state = "bootstrap_in_progress"
        elif journal_path.exists():
            raise LegacyCutoverConflict(
                f"interrupted onboarding journal has no sealed inventory for {snapshot.identity}"
            )
        else:
            state = None
        latch_path = root / "writer-generation.json"
        if latch_path.exists():
            raw = json.loads(latch_path.read_text(encoding="utf-8"))
            if raw.get("schema") != "WriterGenerationLatch.v1" or raw.get(
                "generation_state"
            ) not in {"LEGACY_OPEN", "DRAINING"}:
                raise LegacyCutoverConflict(
                    f"repository {snapshot.identity} does not have a pristine bootstrap latch"
                )
            if (root / "generation-leases").exists() and any(
                (root / "generation-leases").iterdir()
            ):
                raise LegacyCutoverConflict(
                    f"repository {snapshot.identity} has held generation leases"
                )
            if state is None:
                state = "initialized_latch"
        elif state is None:
            state = "empty"
    return {
        "worktree": str(snapshot.worktree),
        "canonical_repository_identity": snapshot.identity,
        "namespace_root": str(root),
        "classification": state,
        "files": files,
    }


def _validate_historical_evidence_root(root: Path) -> dict:
    allowed = {"admissions.jsonl", "admissions.lock", "evidence.jsonl", "evidence.lock"}
    files = _tree_file_inventory(root)
    unexpected = [item["path"] for item in files if item["path"] not in allowed]
    if unexpected:
        raise LegacyCutoverConflict(
            f"historical evidence root {root} has unclassified files: {unexpected}"
        )
    for filename in ("admissions.jsonl", "evidence.jsonl"):
        path = root / filename
        if path.exists():
            read_strict_jsonl(path, label=f"historical {filename}")
    return {
        "path": str(root),
        "classification": "standalone_historical_evidence",
        "files": [item for item in files if not item["path"].endswith(".lock")],
    }


def probe_zero_history_bootstrap(
    *,
    cutover_id: str,
    authority_root: Path | str | None = None,
    worktrees: Iterable[Path | str],
    legacy_roots: Iterable[Path | str] = (),
    historical_evidence_roots: Iterable[Path | str] = (),
    search_roots: Iterable[Path | str] = (),
) -> dict:
    """Build a read-only, byte-sealed inventory for zero-history bootstrap."""
    cutover_id = _validate_cutover_id(cutover_id)
    authority = _canonical_input_path(
        authority_root or default_fabpub_authority_root(), label="authority root"
    )
    snapshots = tuple(repository_snapshot(worktree) for worktree in worktrees)
    if not snapshots:
        raise LegacyCutoverConflict("a zero-history bootstrap requires at least one worktree")
    if len({snapshot.identity for snapshot in snapshots}) != len(snapshots):
        raise LegacyCutoverConflict("a zero-history bootstrap may name each repository once")

    searches = tuple(
        dict.fromkeys(
            _canonical_input_path(path, label="search root") for path in search_roots
        )
    )
    explicit_roots = list(legacy_roots) + list(declared_legacy_roots())
    explicit_roots.extend(_discover_hashed_legacy_roots(searches))
    roots = tuple(
        dict.fromkeys(
            _canonical_input_path(path, label="legacy root") for path in explicit_roots
        )
    )
    legacy_entries = []
    for root in roots:
        files = _legacy_root_file_inventory(root)
        if files:
            raise LegacyCutoverConflict(
                f"zero-history bootstrap found allocator state in legacy root {root}"
            )
        legacy_entries.append(
            {"path": str(root), "classification": "absent" if not root.exists() else "empty"}
        )

    history = tuple(
        dict.fromkeys(
            _canonical_input_path(path, label="historical evidence root")
            for path in historical_evidence_roots
        )
    )
    authority_files = _tree_file_inventory(authority)
    authority_targets = (
        f"{cutover_id}.bootstrap-inventory.json",
        "ACTIVE_BOOTSTRAP",
    )
    unexpected_authority = [
        item["path"]
        for item in authority_files
        if item["path"] != "bootstrap.lock"
        and not any(_is_atomic_temp_name(item["path"], target) for target in authority_targets)
    ]
    if unexpected_authority:
        raise LegacyCutoverConflict(
            f"authority root {authority} is not fresh: {unexpected_authority}"
        )
    payload = {
        "schema": ZERO_HISTORY_INVENTORY_SCHEMA,
        "cutover_id": cutover_id,
        "authority_root": str(authority),
        "worktrees": [
            _classify_repository_namespace(snapshot, cutover_id) for snapshot in snapshots
        ],
        "legacy_roots": legacy_entries,
        "historical_evidence_roots": [
            _validate_historical_evidence_root(root) for root in history
        ],
        "search_roots": [str(root) for root in searches],
    }
    payload["inventory_sha256"] = _inventory_digest(payload)
    return payload


def _validate_zero_history_inventory(payload: dict) -> None:
    if payload.get("schema") != ZERO_HISTORY_INVENTORY_SCHEMA:
        raise LegacyCutoverConflict("unknown zero-history bootstrap inventory schema")
    if _inventory_digest(payload) != payload.get("inventory_sha256"):
        raise LegacyCutoverConflict("the zero-history bootstrap inventory digest drifted")


def write_zero_history_inventory(path: Path | str, payload: dict) -> Path:
    """Atomically persist one validated operator probe outside its authority root."""
    _validate_zero_history_inventory(payload)
    target = Path(path).expanduser().resolve()
    authority = Path(payload["authority_root"])
    if target == authority or authority in target.parents:
        raise LegacyCutoverConflict(
            "the operator probe inventory must be stored outside the authority root"
        )
    _atomic_write_json(target, payload)
    return target


def load_zero_history_inventory(path: Path | str) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    _validate_zero_history_inventory(payload)
    return payload


def _bootstrap_paths(authority_root: Path, cutover_id: str) -> tuple[Path, Path, Path]:
    cutover_id = _validate_cutover_id(cutover_id)
    return (
        authority_root / f"{cutover_id}.bootstrap-inventory.json",
        authority_root / f"{cutover_id}.bootstrap-journal.jsonl",
        authority_root / "ACTIVE_BOOTSTRAP",
    )


def _bootstrap_seal_lock_paths(inventory: dict) -> tuple[Path, ...]:
    authority = Path(inventory["authority_root"])
    paths = {
        authority / "bootstrap.lock",
        *(
            Path(row["path"]) / "fabpub-global-cutover" / "root.lock"
            for row in inventory["legacy_roots"]
        ),
        *(
            Path(row["path"]) / filename
            for row in inventory["historical_evidence_roots"]
            for filename in ("admissions.lock", "evidence.lock")
        ),
        *(
            authority
            / "search-locks"
            / f"{hashlib.sha256(row.encode('utf-8')).hexdigest()}.lock"
            for row in inventory["search_roots"]
        ),
    }
    return tuple(sorted(paths, key=str))


def _inventory_row_namespace_root(row: dict) -> Path:
    """The FABPUB namespace root a sealed row recorded.

    Bootstrap inventory rows carry it directly; legacy cutover partition rows
    carry the store root, exactly ``<namespace_root>/repositories/<identity>``.
    """
    if "namespace_root" in row:
        return Path(row["namespace_root"])
    return Path(row["target_namespace"]).parent.parent


def _recorded_worktree_binds(recorded: str, snapshot: RepositorySnapshot) -> bool:
    """Whether a sealed ``worktree`` string still names ``snapshot``'s repository.

    ``RepositorySnapshot.worktree`` is not identity-bearing: it is the
    recorded path while that is still a working tree, any working tree of the
    same common dir once the snapshot was taken elsewhere (the pruned-worktree
    fallback snapshots the common dir itself), or an already pruned path whose
    binding the identity-bearing ``target_namespace`` check carries alone.  A
    path that still exists but is neither is a foreign directory and does not
    bind.
    """
    if not recorded:
        return False
    path = Path(recorded)
    if path.resolve() == snapshot.worktree:
        return True
    if is_git_repository(path):
        return git_common_dir(path) == snapshot.common_dir
    return not path.exists()


def _discovered_common_dir(path: Path) -> Path | None:
    """The resolved Git common dir Git discovers from ``path``, or ``None`` when
    ``path`` is not a directory or Git discovers no repository from it.

    This is the same discovery ``repository_snapshot`` seals a row from: it
    succeeds inside a working tree, in a bare repository, in ``<repo>/.git``,
    and in Git's administrative subdirectories such as ``<repo>/.git/objects``.
    """
    if not path.is_dir():
        return None
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        return None
    return Path(completed.stdout.strip()).resolve()


def _path_discovers_repository(path: Path) -> bool:
    """True when Git still discovers a repository from ``path``: the health
    check for a recorded row path.  A sealed row was produced by
    ``repository_snapshot(path)``, so any path that still discovers a
    repository is exactly as healthy as it was at the seal; identity equality
    at the caller decides whether it is still the SAME repository.  False for
    a pruned worktree, a plain directory, and anything Git does not recognise.
    """
    return _discovered_common_dir(path) is not None


def _path_is_own_common_dir(path: Path) -> bool:
    """True when ``path`` is a Git directory that resolves to itself as the
    repository common dir: a bare repository or a ``<repo>/.git`` directory.
    Stricter than ``_path_discovers_repository``; it is the check for a
    FALLBACK candidate (the row's recorded common dir), which must be the
    common dir itself and not merely discover one.  False for a working tree,
    a linked worktree's ``.git`` file, ``<repo>/.git/objects``, and anything
    Git does not recognise."""
    common = _discovered_common_dir(path)
    return common is not None and common == path.resolve()


def _inventory_row_repository(row: dict) -> Path:
    """The Git directory a sealed inventory row still names.

    ``CanonicalRepositoryIdentity.v1`` never hashed the worktree path, only the
    Git common dir, so a row's ``worktree`` is a convenience and not the
    identity: while Git still discovers a repository from it (the same
    discovery the probe sealed it with) it is used as recorded; once it was
    pruned the row's recorded common dir stands in for it, with one warning;
    only a missing common dir fails closed.  Identity equality at the
    caller is unchanged, so a common dir that now belongs to a different
    repository still refuses there.
    """
    worktree = Path(row["worktree"])
    if _path_discovers_repository(worktree):
        # Any path the probe could seal (a working tree, a bare repository,
        # ``<repo>/.git``, ``<repo>/.git/objects``) still discovers a
        # repository: nothing was pruned.
        return worktree
    common = _inventory_row_namespace_root(row).parent
    identity = row["canonical_repository_identity"]
    if _path_is_own_common_dir(common):
        warnings.warn(
            f"sealed inventory row for {identity} names pruned worktree {worktree}; "
            f"using its recorded repository common dir {common} instead",
            SealedWorktreeFallbackWarning,
            stacklevel=2,
        )
        return common
    raise LegacyCutoverConflict(
        f"sealed inventory row for {identity} names pruned worktree {worktree} and its "
        f"repository common dir {common} is gone or is no longer a Git repository; "
        "restore the repository or rotate the authority"
    )


def _revalidate_bootstrap_sources(inventory: dict) -> None:
    legacy_paths = {row["path"] for row in inventory["legacy_roots"]}
    declared_now = {
        str(_canonical_input_path(path, label="legacy root"))
        for path in declared_legacy_roots()
    }
    discovered_now = {
        str(path)
        for path in _discover_hashed_legacy_roots(
            tuple(Path(path) for path in inventory["search_roots"])
        )
    }
    if not declared_now.issubset(legacy_paths) or not discovered_now.issubset(legacy_paths):
        raise LegacyCutoverConflict(
            "the complete legacy root set changed after the bootstrap inventory sealed"
        )
    for row in inventory["legacy_roots"]:
        if _legacy_root_file_inventory(Path(row["path"])):
            raise LegacyCutoverConflict(
                f"allocator state appeared in sealed legacy root {row['path']}"
            )
    for row in inventory["historical_evidence_roots"]:
        if _validate_historical_evidence_root(Path(row["path"])) != row:
            raise LegacyCutoverConflict(
                f"historical evidence bytes changed after seal at {row['path']}"
            )
    for row in inventory["worktrees"]:
        current = _classify_repository_namespace(
            repository_snapshot(_inventory_row_repository(row)),
            inventory["cutover_id"],
            bootstrap_inventory_sha256=inventory["inventory_sha256"],
        )
        if current["canonical_repository_identity"] != row["canonical_repository_identity"]:
            raise LegacyCutoverConflict(
                f"repository identity changed after seal for {row['worktree']}"
            )


def _bootstrap_journal_states(journal: Path, cutover_id: str) -> tuple[str, ...]:
    states, ids = _journal_entries(journal)
    if ids and set(ids) != {cutover_id}:
        raise LegacyCutoverConflict("bootstrap journal belongs to another cutover")
    expected = ZERO_HISTORY_STATES[: len(states)]
    if tuple(states) != expected:
        raise LegacyCutoverConflict(
            "bootstrap journal is not an exact monotonic state prefix"
        )
    return tuple(states)


def _record_bootstrap_state(journal: Path, cutover_id: str, state: str) -> None:
    states = _bootstrap_journal_states(journal, cutover_id)
    if state in states:
        return
    index = ZERO_HISTORY_STATES.index(state)
    if index != len(states):
        raise LegacyCutoverConflict(
            f"bootstrap state {state} is not the next monotonic state"
        )
    body = json.dumps(
        {"cutover_id": cutover_id, "state": state}, sort_keys=True, separators=(",", ":")
    ) + "\n"
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(journal.parent)


def _active_bootstrap_inventory(authority_root: Path | str | None = None) -> dict | None:
    authority = _canonical_input_path(
        authority_root or default_fabpub_authority_root(), label="authority root"
    )
    pointer = authority / "ACTIVE_BOOTSTRAP"
    if not pointer.exists():
        return None
    _require_no_ancestor_symlink(pointer)
    claim = json.loads(pointer.read_text(encoding="utf-8"))
    inventory_path, journal, _ = _bootstrap_paths(authority, claim["cutover_id"])
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    _validate_zero_history_inventory(inventory)
    if _canonical_input_path(
        inventory["authority_root"], label="sealed bootstrap authority root"
    ) != authority:
        raise LegacyCutoverConflict(
            "the sealed bootstrap inventory belongs to a different authority root"
        )
    _revalidate_bootstrap_sources(inventory)
    if inventory.get("inventory_sha256") != claim.get("inventory_sha256"):
        raise LegacyCutoverConflict("the active bootstrap pointer inventory digest drifted")
    states = _bootstrap_journal_states(journal, claim["cutover_id"])
    if states != ZERO_HISTORY_STATES:
        raise LegacyCutoverConflict("the persistent bootstrap authority is not ACTIVE")
    return inventory


def bootstrap_zero_history_authority(
    inventory: dict, *, confirmed_zero_history: bool = False
) -> dict:
    """Apply or resume one explicitly confirmed zero-history bootstrap."""
    if not confirmed_zero_history:
        raise LegacyCutoverConflict("zero-history bootstrap requires explicit confirmation")
    _validate_zero_history_inventory(inventory)
    cutover_id = str(inventory["cutover_id"])
    authority = _canonical_input_path(inventory["authority_root"], label="authority root")
    stored_path, journal, pointer = _bootstrap_paths(authority, cutover_id)
    lock = authority / "bootstrap.lock"
    with _reentrant_flock(lock):
        if stored_path.exists():
            stored = json.loads(stored_path.read_text(encoding="utf-8"))
            if stored != inventory:
                raise LegacyCutoverConflict(
                    "bootstrap resume inventory differs from the sealed authority inventory"
                )
            _revalidate_bootstrap_sources(inventory)
        else:
            # Nothing durable exists before the first apply's re-probe, so a
            # pruned row is re-probed rather than resolved through the fallback.
            for row in inventory["worktrees"]:
                recorded = Path(row["worktree"])
                if not _path_discovers_repository(recorded):
                    raise LegacyCutoverConflict(
                        f"sealed inventory row for {row['canonical_repository_identity']} "
                        f"names pruned worktree {row['worktree']} before its first apply; "
                        "re-run the zero-history probe"
                    )
            reprobe = probe_zero_history_bootstrap(
                cutover_id=cutover_id,
                authority_root=authority,
                worktrees=[row["worktree"] for row in inventory["worktrees"]],
                legacy_roots=[row["path"] for row in inventory["legacy_roots"]],
                historical_evidence_roots=[
                    row["path"] for row in inventory["historical_evidence_roots"]
                ],
                search_roots=inventory["search_roots"],
            )
            if reprobe != inventory:
                raise LegacyCutoverConflict(
                    "zero-history source inventory changed between probe and apply"
                )
            _atomic_write_json(stored_path, inventory)
        _record_bootstrap_state(journal, cutover_id, "DRAINING")

    worktrees = tuple(_inventory_row_repository(row) for row in inventory["worktrees"])
    latches = [WriterGenerationLatch.open(worktree) for worktree in worktrees]
    for latch in latches:
        if latch.read().generation_state == "LEGACY_OPEN":
            latch.begin_draining()
    for latch, worktree in zip(latches, worktrees):
        if latch.read().generation_state == "DRAINING":
            latch.await_quiescent(worktree=worktree)

    with _hold_all(_bootstrap_seal_lock_paths(inventory)):
        _revalidate_bootstrap_sources(inventory)
        _record_bootstrap_state(journal, cutover_id, "INVENTORY_SEALED")
        _record_bootstrap_state(journal, cutover_id, "ARMED")
        _record_bootstrap_state(journal, cutover_id, "ACTIVE")
        claim = {
            "schema": "ZeroHistoryBootstrapAuthority.v1",
            "cutover_id": cutover_id,
            "inventory_sha256": inventory["inventory_sha256"],
        }
        if pointer.exists():
            if json.loads(pointer.read_text(encoding="utf-8")) != claim:
                raise LegacyCutoverConflict("another zero-history bootstrap owns the authority")
        else:
            _atomic_write_json(pointer, claim)

    receipts = []
    for worktree, row in zip(worktrees, inventory["worktrees"]):
        receipt = onboard_zero_legacy_repository(
            worktree,
            cutover_id=cutover_id,
            authority_root=authority,
            recorded_worktree=row["worktree"],
        )
        receipts.append(receipt.canonical_repository_identity)
    return {
        "schema": "ZeroHistoryBootstrapResult.v1",
        "cutover_id": cutover_id,
        "authority_root": str(authority),
        "state": "ACTIVE",
        "inventory_sha256": inventory["inventory_sha256"],
        "repositories": receipts,
    }

ONBOARDING_SEAL_BOUNDARIES = (
    "before_zero_source_proof",
    "before_receipt_write",
    "before_receipt_fsync",
    "after_receipt_write",
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
    namespace = snapshot.container
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


def _zero_source_seal_lock_paths(
    roots: tuple[Path, ...], authority_root: Path | str | None
) -> tuple[Path, ...]:
    paths = set(_traditional_seal_lock_paths(roots))
    bootstrap_root = _canonical_input_path(
        authority_root or default_fabpub_authority_root(), label="authority root"
    )
    if (bootstrap_root / "ACTIVE_BOOTSTRAP").exists():
        paths.add(bootstrap_root / "bootstrap.lock")
    return tuple(sorted(paths, key=str))


def _traditional_seal_lock_paths(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for root in roots:
        paths.add(root / "fabpub-global-cutover" / "root.lock")
        pointer = root / "fabpub-global-cutover" / "ACTIVE_CUTOVER"
        if pointer.exists():
            claim = _read_pointer_claim(pointer)
            primary = Path(claim.get("primary_authority", pointer.parent))
            paths.add(primary / "cutover.lock")
    return tuple(sorted(paths, key=str))


def onboard_zero_legacy_repository(
    worktree: Path | str,
    *,
    cutover_id: str = ZERO_SOURCE_ONBOARDING_CUTOVER_ID,
    roots: tuple[Path, ...] | None = None,
    authority_root: Path | str | None = None,
    recorded_worktree: str | None = None,
) -> LegacyRepositoryPartitionReceipt:
    """Serialized, authenticated onboarding for a repository first seen post-ACTIVE.

    Not an empty-store fallback: exactly one receipt, written under the latch's
    exclusive activation lock, carrying a REAL zero-source proof. The global
    authority is validated before the repository drains, arms, and promotes its
    own fresh generation (SL1-SOL-01).
    """
    cutover_id = _validate_cutover_id(cutover_id)
    bootstrap_inventory_sha256 = None
    bootstrap_authority_root = None
    bootstrap_seal_locks = None
    if roots is None:
        bootstrap = _active_bootstrap_inventory(authority_root)
        if bootstrap is not None:
            bootstrap_id = bootstrap["cutover_id"]
            if cutover_id == ZERO_SOURCE_ONBOARDING_CUTOVER_ID:
                cutover_id = bootstrap_id
            elif cutover_id != bootstrap_id:
                raise LegacyCutoverConflict(
                    f"active bootstrap {bootstrap_id!r} may not onboard receipt "
                    f"{cutover_id!r}"
                )
            roots = tuple(Path(row["path"]) for row in bootstrap["legacy_roots"])
            bootstrap_inventory_sha256 = bootstrap["inventory_sha256"]
            bootstrap_authority_root = Path(bootstrap["authority_root"])
            bootstrap_seal_locks = _bootstrap_seal_lock_paths(bootstrap)
        else:
            roots = declared_legacy_roots()
    if not global_active_authority_exists(roots, authority_root=authority_root):
        raise LegacyCutoverConflict(
            "zero-source onboarding requires a persistent global ACTIVE authority"
        )
    seal_locks = bootstrap_seal_locks or _zero_source_seal_lock_paths(
        roots, authority_root
    )
    with _hold_all(seal_locks):
        return _onboard_zero_legacy_repository_under_seal(
            worktree,
            cutover_id=cutover_id,
            roots=roots,
            authority_root=authority_root,
            bootstrap_inventory_sha256=bootstrap_inventory_sha256,
            bootstrap_authority_root=bootstrap_authority_root,
            recorded_worktree=recorded_worktree,
        )


def _rotation_ceremony_dir(identity: str, authority_root: Path | str | None) -> Path:
    authority = _canonical_input_path(
        authority_root or default_fabpub_authority_root(), label="authority root"
    )
    return authority / ROTATION_CEREMONY_DIR / identity


def _require_no_rotation_in_progress(
    snapshot: RepositorySnapshot, authority_root: Path | str | None
) -> None:
    """Refuse while any rotation ceremony for this repository is not ACTIVE."""
    ceremony = _rotation_ceremony_dir(snapshot.identity, authority_root)
    if not ceremony.exists():
        return
    for journal in sorted(ceremony.glob("*.journal.jsonl")):
        rotation_id = journal.name[: -len(".journal.jsonl")]
        states, ids = _journal_entries(journal)
        if (
            not _rotation_states_well_formed(states)
            or states[-1] != "ACTIVE"
            or set(ids) != {rotation_id}
        ):
            raise LegacyCutoverConflict(
                f"partition rotation {rotation_id!r} for {snapshot.identity} is in "
                "progress; zero-source onboarding may not end a rotation drain"
            )


def _onboard_zero_legacy_repository_under_seal(
    worktree: Path | str,
    *,
    cutover_id: str,
    roots: tuple[Path, ...],
    authority_root: Path | str | None,
    bootstrap_inventory_sha256: str | None,
    bootstrap_authority_root: Path | None,
    recorded_worktree: str | None = None,
) -> LegacyRepositoryPartitionReceipt:
    if not global_active_authority_exists(roots, authority_root=authority_root):
        raise LegacyCutoverConflict(
            "zero-source onboarding requires a persistent global ACTIVE authority"
        )
    snapshot = repository_snapshot(worktree)
    namespace = snapshot.container
    # A partition rotation owns this namespace from its first journal row until
    # ACTIVE: onboarding must never end a drain it did not start, and a
    # rotated repository is not a zero-source one.
    _require_no_rotation_in_progress(snapshot, authority_root)
    active = snapshot.store_root
    for filename in ("admissions.jsonl", "evidence.jsonl"):
        if (namespace / filename).exists() and not (namespace / RECEIPT_FILENAME).exists():
            raise LegacyCutoverConflict(
                f"unattested canonical {filename} at {namespace}; zero-source onboarding "
                "may not adopt allocator state"
            )
    latch = WriterGenerationLatch.open(worktree)
    if latch.read().generation_state == "LEGACY_OPEN":
        latch.begin_draining()
    if latch.read().generation_state == "DRAINING":
        latch.await_quiescent(worktree=worktree)
    with latch.exclusive():
        existing = None
        if (namespace / RECEIPT_FILENAME).exists():
            existing = load_partition_receipt(namespace)
        if existing is not None:
            if existing.cutover_id != cutover_id:
                raise LegacyCutoverConflict(
                    f"existing zero-source receipt belongs to {existing.cutover_id!r}, "
                    f"not {cutover_id!r}"
                )
            if (
                bootstrap_inventory_sha256 is not None
                and (
                    (bootstrap_claim := _receipt_bootstrap_claim(existing)) is None
                    or bootstrap_claim["inventory_sha256"]
                    != bootstrap_inventory_sha256
                    or bootstrap_claim["authority_root"]
                    != bootstrap_authority_root
                )
            ):
                raise LegacyCutoverConflict(
                    "existing zero-source receipt is not bound to the active "
                    "bootstrap inventory"
                )
            _prove_zero_source(snapshot, roots, "before_zero_source_proof")
            latch.mark_armed()
            latch.activate()
            return existing
        if active != namespace:
            raise LegacyCutoverConflict(
                f"repository {snapshot.identity} has rotated to {active}; zero-source "
                "onboarding may not re-onboard a rotated repository"
            )
        zero_source_proof = _prove_zero_source(snapshot, roots, "before_zero_source_proof")
        identity = snapshot.identity
        authority = latch.root / "zero-legacy-onboarding"
        authority.mkdir(parents=True, exist_ok=True)
        journal_path = authority / f"{cutover_id}.journal.jsonl"
        inventory_path = authority / f"{cutover_id}.inventory.json"
        partition = {
            "canonical_repository_identity": identity,
            # The sealed bootstrap row's worktree, not the path this resume
            # happened to snapshot: under the pruned-worktree fallback that is
            # the common dir, which a restored worktree could never bind.
            "worktree": recorded_worktree or str(snapshot.worktree),
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
        if bootstrap_inventory_sha256 is not None:
            sealed["bootstrap_inventory_sha256"] = bootstrap_inventory_sha256
            sealed["bootstrap_authority_root"] = str(bootstrap_authority_root)
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
        # A final post-write proof runs before generation activation. A late
        # source may leave an immutable receipt, but it cannot make that receipt
        # routable while the latch remains DRAINING.
        _prove_zero_source(snapshot, roots, "before_receipt_fsync")
        receipt.write(
            namespace,
            zero_source_proof=sealed["partitions"][identity].get("zero_source_proof"),
        )
        _prove_zero_source(snapshot, roots, "after_receipt_write")
        latch.mark_armed()
        latch.activate()
        return receipt


# ---------------------------------------------------------------------------
# ah#789 Workstream D — blocked-partition rotation ceremony
#
# A repository whose active generation carries a permanently ambiguity-blocked
# publish never becomes writable again by clearing the block: the ceremony
# below opens a SUCCESSOR generation under the same container, seals an
# operator attestation that adjudicates every blocked effect, and flips the
# ``generations/ACTIVE`` pointer only after the successor receipt is durable.
# Nothing in the predecessor generation is moved, rewritten, or deleted.
# ---------------------------------------------------------------------------
_ROTATION_EFFECT_PREFIX = "publish_committed_branch\0"
_ROTATION_JOURNAL_SUFFIX = ".journal.jsonl"


@dataclass(frozen=True)
class PartitionRotationOutcome:
    """The durable result of :func:`rotate_blocked_partition`."""

    cutover_id: str
    state: str
    store_root: Path
    predecessor_store_root: Path
    generation: int
    receipt: RotatedPartitionReceipt


@dataclass(frozen=True)
class _PredecessorLedger:
    keys: tuple[str, ...]
    blocked: dict[str, str]
    terminals: dict[str, str]
    dangling: tuple[str, ...]


_SETTLED_EVIDENCE_STATES = frozenset(
    {
        "outcome_ambiguous_blocked",
        "effect_terminal_observed",
        "rejected_before_start",
        "no_effect_terminal_proven",
    }
)


@dataclass(frozen=True)
class _PredecessorSnapshot:
    """Every digested predecessor file read ONCE, and the digests of THOSE bytes.

    The adjudication used to hash the predecessor store and then parse it with
    separate reads; a writer that swapped a file between the hash and the
    parse and restored it before the in-lock re-check had the attestation
    bind bytes the derivation never saw, and the successor ACTIVATED without
    a terminal the honest ledger carried (codex r10 P1).  The snapshot is the
    only reader of a predecessor store inside an adjudication: the
    attestation's digests, the evidence ledger, the owner record, the
    admissions high water and the receipt binding are all functions of
    ``files``, and nothing under ``root`` is read again until the in-lock
    re-check compares the live bytes to ``digests``.
    """

    root: Path
    files: dict
    digests: dict

    def text(self, name: str) -> str | None:
        """The snapshot's bytes of ``name`` as text; ``None`` when the file was absent."""
        raw = self.files[name]
        if raw is None:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise LegacyCutoverConflict(f"{name} under {self.root} is not UTF-8: {error}") from error


def _snapshot_predecessor(store_root: Path) -> _PredecessorSnapshot:
    """Read every digested file of a predecessor store exactly once.

    A missing file digests as empty bytes, exactly as :func:`_sha256_file`
    digests it for the in-lock re-check.
    """
    root = Path(store_root)
    files: dict = {}
    for name in ROTATION_DIGESTED_FILES:
        try:
            files[name] = (root / name).read_bytes()
        except FileNotFoundError:
            files[name] = None
    digests = {
        name: hashlib.sha256(raw if raw is not None else b"").hexdigest() for name, raw in files.items()
    }
    return _PredecessorSnapshot(root, files, digests)


def _read_predecessor_ledger(snapshot: _PredecessorSnapshot) -> _PredecessorLedger:
    """Strict-parse the snapshot's predecessor evidence log into what a rotation adjudicates."""
    try:
        rows = _parse_strict_jsonl(
            snapshot.text("evidence.jsonl"),
            label="predecessor evidence",
            path=snapshot.root / "evidence.jsonl",
        )
    except LegacyCutoverConflict as error:
        raise PartitionRotationRefused(f"predecessor evidence is unreadable: {error}") from error
    order: list[str] = []
    # EVERY classification — blocked, terminal, dangling — is the key's LATEST
    # row in log order, the same view the store's own ``replay()`` (last row
    # wins) hands every other reader.  A ``provider_call_in_flight`` row after
    # a terminal is a fresh attempt that never settled (codex r4 finding 1); a
    # terminal after that re-attempt is the key's current word, not the
    # earlier one (fable r5 finding 1).  Only the contradiction check looks at
    # every row: a key that was EVER both blocked and terminal-observed refuses
    # regardless of order.
    latest: dict[str, tuple[str, str, dict]] = {}
    ever_blocked: set[str] = set()
    ever_terminal: set[str] = set()
    for line, raw in rows:
        key = raw.get("idempotency_key")
        state = raw.get("state")
        if not isinstance(key, str) or not isinstance(state, str):
            raise PartitionRotationRefused("predecessor evidence row lacks a key or state")
        if key not in order:
            order.append(key)
        latest[key] = (line, state, raw)
        if state == "outcome_ambiguous_blocked":
            ever_blocked.add(key)
        elif state == "effect_terminal_observed":
            ever_terminal.add(key)
    for key in order:
        if key in ever_blocked and key in ever_terminal:
            raise PartitionRotationRefused(
                f"predecessor evidence for {key!r} is both terminal-observed and blocked"
            )
    blocked = {
        key: hashlib.sha256(latest[key][0].encode("utf-8")).hexdigest()
        for key in order
        if latest[key][1] == "outcome_ambiguous_blocked"
    }
    terminals = {
        key: str(latest[key][2].get("evidence_reference", ""))
        for key in order
        if latest[key][1] == "effect_terminal_observed"
    }
    dangling = tuple(key for key in order if latest[key][1] not in _SETTLED_EVIDENCE_STATES)
    return _PredecessorLedger(tuple(order), blocked, terminals, dangling)


def _rotation_owner(snapshot: _PredecessorSnapshot, identity: str) -> dict | None:
    try:
        body = snapshot.text("adapter-start-owner.json")
        if body is None:
            return None
        raw = json.loads(body)
    except (LegacyCutoverConflict, ValueError) as error:
        raise PartitionRotationRefused(f"adapter-start owner record is unreadable: {error}") from error
    if not isinstance(raw, dict):
        raise PartitionRotationRefused("adapter-start owner record is not an object")
    if raw.get("repository_identity") != identity:
        raise PartitionRotationRefused("adapter-start ownership belongs to another repository")
    return raw


def _rotation_owner_identity(owner: dict | None, key: str) -> dict:
    if owner is None:
        return {}
    if owner.get("effect_key") == key or owner.get("idempotency_key") == key:
        return {"owner_nonce": owner.get("owner_nonce"), "transaction_id": owner.get("transaction_id")}
    return {}


def _rotation_admissions_high_water(snapshot: _PredecessorSnapshot) -> int:
    try:
        rows = _parse_strict_jsonl(
            snapshot.text("admissions.jsonl"),
            label="predecessor admissions",
            path=snapshot.root / "admissions.jsonl",
        )
    except LegacyCutoverConflict as error:
        raise PartitionRotationRefused(f"predecessor admissions are unreadable: {error}") from error
    high = 0
    for _line, raw in rows:
        try:
            high = max(high, int(raw.get("epoch", 0)))
        except (TypeError, ValueError) as error:
            raise PartitionRotationRefused(f"predecessor admission row has a non-integer epoch: {error}") from error
    return high


def _validate_rotation_attestation(attestation: object, generation: int) -> dict:
    if not isinstance(attestation, dict) or attestation.get("schema") != ROTATION_ATTESTATION_SCHEMA:
        raise PartitionRotationRefused(f"attestation must carry schema {ROTATION_ATTESTATION_SCHEMA!r}")
    attested_by = attestation.get("attested_by")
    if not isinstance(attested_by, str) or not attested_by:
        raise PartitionRotationRefused("attestation names no attesting operator")
    if attestation.get("predecessor_generation") != generation:
        raise PartitionRotationRefused(
            f"attestation adjudicates generation {attestation.get('predecessor_generation')!r}; "
            f"this ceremony adjudicates generation {generation}"
        )
    if not isinstance(attestation.get("predecessor_store_digests"), dict):
        raise PartitionRotationRefused("attestation carries no predecessor store digests")
    effects = attestation.get("effects")
    if not isinstance(effects, dict):
        raise PartitionRotationRefused("attestation carries no effects map")
    for key, entry in effects.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise PartitionRotationRefused("attestation effect entries must be keyed objects")
        disposition = entry.get("disposition")
        if disposition not in (DISPOSITION_OBSERVED_LANDED, DISPOSITION_ATTESTED_NOT_LANDED):
            raise PartitionRotationRefused(f"attestation disposition {disposition!r} for {key!r} is unknown")
        head = entry.get("observed_head")
        if disposition == DISPOSITION_OBSERVED_LANDED and not (isinstance(head, str) and head):
            raise PartitionRotationRefused(f"observed_landed effect {key!r} names no observed head")
        if disposition == DISPOSITION_ATTESTED_NOT_LANDED and head is not None:
            raise PartitionRotationRefused(f"attested_not_landed effect {key!r} may not name an observed head")
        url = entry.get("evidence_url")
        if not isinstance(url, str) or not url:
            raise PartitionRotationRefused(f"attestation effect {key!r} cites no evidence")
        if "ambiguity_digest" not in entry:
            raise PartitionRotationRefused(f"attestation effect {key!r} binds no ambiguity digest")
    return effects


def _rotation_own_journal(journal: Path, cutover_id: str) -> list[str]:
    """States of THIS rotation's journal; any malformation refuses, never rewrites."""
    if not journal.exists():
        return []
    try:
        states, ids = _journal_entries(journal)
    except LegacyCutoverConflict as error:
        raise PartitionRotationRefused(f"rotation journal for {cutover_id!r} is unreadable: {error}") from error
    if not _rotation_states_well_formed(states):
        raise PartitionRotationRefused(
            f"rotation journal for {cutover_id!r} is not a well-formed state prefix: {states}"
        )
    if set(ids) != {cutover_id}:
        raise PartitionRotationRefused(
            f"rotation journal for {cutover_id!r} carries foreign cutover ids "
            f"{sorted(set(ids) - {cutover_id})}"
        )
    return states


def _rotation_journal_append(journal: Path, cutover_id: str, state: str) -> None:
    import time

    journal.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": ROTATION_JOURNAL_SCHEMA,
        "cutover_id": cutover_id,
        "state": state,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(journal.parent)


def _load_rotation_inventory(inventory_path: Path, cutover_id: str, identity: str) -> dict:
    if not inventory_path.exists():
        raise PartitionRotationRefused(
            f"rotation {cutover_id!r} journaled INVENTORY_SEALED but its inventory is missing"
        )
    try:
        sealed = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PartitionRotationRefused(f"sealed rotation inventory is unreadable: {error}") from error
    if (
        not isinstance(sealed, dict)
        or sealed.get("schema") != ROTATION_INVENTORY_SCHEMA
        or sealed.get("cutover_id") != cutover_id
        or _inventory_digest(sealed) != sealed.get("inventory_sha256")
        or identity not in sealed.get("partitions", {})
    ):
        raise PartitionRotationRefused(f"sealed rotation inventory for {cutover_id!r} does not authenticate")
    # Authenticate the inventory the way ``load_partition_receipt`` will: BOTH
    # digests.  ``inventory_sha256`` alone admits a partition map re-sealed
    # under a stale ``partition_map_sha256``; a resume that accepted it would
    # ACTIVE a successor whose receipt then fails to load (codex r5 P1).
    if _partition_map_digest(sealed.get("partitions", {})) != sealed.get("partition_map_sha256"):
        raise PartitionRotationRefused(
            f"sealed rotation inventory for {cutover_id!r} carries a partition map digest that drifted"
        )
    return sealed


def _derive_rotation_inventory(
    *,
    cutover_id: str,
    identity: str,
    container: Path,
    predecessor_receipt,
    successor_generation: int,
    generation: int,
    predecessor_digests: dict,
    attestation: dict,
    digest: str,
    effects: dict,
    high_water: int,
    carried: dict,
) -> dict:
    """The inventory a rotation seals over a validated predecessor and attestation.

    ONE definition.  A fresh ceremony writes exactly this; a resume re-derives
    it from the predecessor bytes and attestation it has just validated and
    requires the sealed inventory to digest to the same body.  Every
    authority-bearing field a sealed inventory carries — the epoch floor, the
    adjudicated dispositions, the carried landed effects, the root inventory —
    is therefore bound to the predecessor and the operator's attestation, not
    merely to the inventory's own digests (codex r7 P1).
    """
    partition = {
        "canonical_repository_identity": identity,
        "target_namespace": str(container),
        "generation": successor_generation,
        "predecessor_generation": generation,
        "predecessor_digests": dict(predecessor_digests),
        "predecessor_receipt_sha256": predecessor_digests[RECEIPT_FILENAME],
        "adjudicated_effect_dispositions": {
            key: {
                "disposition": entry["disposition"],
                "observed_head": entry.get("observed_head"),
                "evidence_url": entry["evidence_url"],
                "attestation_digest": digest,
            }
            for key, entry in effects.items()
        },
        "legacy_epoch_high_water": high_water,
        "legacy_completed_effect_keys": sorted(carried),
        "legacy_completed_effects": carried,
        "ambiguous": False,
        "zero_source": False,
    }
    sealed = {
        "schema": ROTATION_INVENTORY_SCHEMA,
        "cutover_id": cutover_id,
        "attestation_sha256": digest,
        "attestation": attestation,
        "manifest_sha256": hashlib.sha256(
            canonical_bytes({"rotation": cutover_id, "repository": identity})
        ).hexdigest(),
        # Inherited from the SNAPSHOT-BOUND predecessor receipt (the container
        # receipt at 0->1, generation n-1's rotated receipt after), never from
        # the container receipt the ceremony loaded separately: at n >= 1 that
        # object is bound to nothing the attestation digests (codex r11 P1).
        "legacy_root_inventory": list(predecessor_receipt.legacy_root_inventory),
        "partitions": {identity: partition},
    }
    sealed["partition_map_sha256"] = _partition_map_digest(sealed["partitions"])
    sealed["inventory_sha256"] = _inventory_digest(sealed)
    return sealed


def _inventory_divergence(sealed: dict, derived: dict, prefix: str = "") -> list[str]:
    """Dotted paths at which ``sealed`` differs from ``derived`` (for the refusal)."""
    sealed = json.loads(canonical_bytes(sealed))
    derived = json.loads(canonical_bytes(derived))
    out: list[str] = []
    for key in sorted(set(sealed) | set(derived)):
        a, b = sealed.get(key), derived.get(key)
        if a == b:
            continue
        # The two seals differ whenever anything under them does; naming them
        # would hide the substantive path (fable r8 O1).
        if not prefix and key in ("inventory_sha256", "partition_map_sha256"):
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            out.extend(_inventory_divergence(a, b, f"{prefix}{key}."))
        else:
            out.append(f"{prefix}{key}")
    return out


def _write_active_pointer(generations: Path, generation: int) -> None:
    """Atomically publish ``generations/ACTIVE``; the temp name never matches ``ACTIVE*``."""
    target = generations / ACTIVE_POINTER
    temp = generations / f".{ACTIVE_POINTER}.{os.getpid()}.{_fresh_nonce()[:8]}.tmp"
    with temp.open("w", encoding="ascii") as stream:
        stream.write(f"{generation}\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, target)
    _fsync_dir(generations)


def _rotation_carried_effects(
    active_receipt, ledger: _PredecessorLedger, effects: dict, identity: str, generation: int, digest: str
) -> dict:
    try:
        carried = {key: dict(value) for key, value in sealed_partition_effects(active_receipt).items()}
    except LegacyCutoverConflict as error:
        raise PartitionRotationRefused(f"predecessor sealed effects do not authenticate: {error}") from error
    for key, reference in ledger.terminals.items():
        carried[key] = {
            "serialized_repository": identity,
            "evidence_reference": reference,
            "generation": generation,
            "disposition": "effect_terminal_observed",
        }
    for key, entry in effects.items():
        if entry["disposition"] == DISPOSITION_OBSERVED_LANDED:
            carried[key] = {
                "serialized_repository": identity,
                "evidence_reference": entry["evidence_url"],
                "observed_head": entry["observed_head"],
                "generation": generation,
                "disposition": DISPOSITION_OBSERVED_LANDED,
                "attestation_digest": digest,
            }
        else:
            carried.pop(key, None)
    return carried


@dataclass(frozen=True)
class _RotationAdjudication:
    """What ONE adjudication of a predecessor against an attestation yields:
    every input of the sealed inventory besides the layout."""

    effects: dict
    digest: str
    predecessor_digests: dict
    carried: dict
    high_water: int


def _require_receipt_is_snapshot(
    predecessor_receipt, snapshot: _PredecessorSnapshot, predecessor_generation: int
) -> None:
    """Bind the AUTHENTICATED predecessor receipt object to the snapshot's receipt bytes.

    ``load_partition_receipt`` authenticated the receipt through its own read
    and the attestation binds ``snapshot.digests[RECEIPT_FILENAME]``; the
    carried effects and the epoch floor derive from the OBJECT.  The object
    must therefore be exactly what the snapshot's bytes are, or a receipt
    swapped between the load and the snapshot would let the attestation bind
    bytes the derivation never used (codex r10 P1, receipt leg).  A legacy
    receipt's on-disk bytes carry the zero-source proof the object holds only
    by digest, so the proof is taken from the snapshot and required to digest
    to the object's ``zero_source_proof_sha256`` before the bytes compare.
    """
    raw = snapshot.files[RECEIPT_FILENAME]
    if raw is None:
        raise PartitionRotationRefused(
            f"predecessor generation {predecessor_generation} carries no receipt at {snapshot.root}"
        )
    if isinstance(predecessor_receipt, RotatedPartitionReceipt):
        expected = predecessor_receipt.file_bytes()
    else:
        try:
            on_disk = json.loads(raw)
        except ValueError as error:
            raise PartitionRotationRefused(
                f"predecessor generation {predecessor_generation} receipt at {snapshot.root} is not JSON: {error}"
            ) from error
        proof = on_disk.get("zero_source_proof") if isinstance(on_disk, dict) else None
        proof_digest = hashlib.sha256(canonical_bytes(proof)).hexdigest() if proof is not None else ""
        if proof_digest != predecessor_receipt.zero_source_proof_sha256:
            raise PartitionRotationRefused(
                f"predecessor generation {predecessor_generation} receipt bytes carry a zero-source proof "
                "the authenticated receipt does not digest"
            )
        expected = predecessor_receipt.file_bytes(proof)
    if raw != expected:
        raise PartitionRotationRefused(
            f"predecessor generation {predecessor_generation} receipt bytes are not the receipt that "
            "authenticated; the predecessor store changed under the ceremony"
        )


def _adjudicate_rotation_predecessor(
    attestation: dict,
    snapshot: _PredecessorSnapshot,
    predecessor_generation: int,
    predecessor_receipt,
    identity: str,
) -> _RotationAdjudication:
    """Adjudicate ``attestation`` over the predecessor generation, zero-write.

    ONE adjudication for every arm of the ceremony -- the fresh path, the
    pre-flip resume and the post-flip completion -- so no arm can accept
    sealed state that an adjudication of the same predecessor bytes and the
    same attestation would not derive.  Before this the post-flip arm reached
    ``_finish_rotation_after_flip`` on the successor receipt alone, without
    validating the attestation at all (codex r8 P1).  Every predecessor byte
    it derives from is the ONE ``snapshot`` the caller took: the attestation
    binds the snapshot's digests and the ledger, owner, high water and receipt
    binding parse the snapshot's bytes, never the store again (codex r10 P1).
    """
    effects = _validate_rotation_attestation(attestation, predecessor_generation)
    digest = hashlib.sha256(canonical_bytes(attestation)).hexdigest()
    expected_digests = dict(snapshot.digests)
    if attestation.get("predecessor_receipt_digest") != expected_digests[RECEIPT_FILENAME]:
        raise PartitionRotationRefused("attestation predecessor_receipt_digest does not match the predecessor receipt")
    if attestation["predecessor_store_digests"] != expected_digests:
        raise PartitionRotationRefused("attestation predecessor_store_digests do not match the predecessor store")
    _require_receipt_is_snapshot(predecessor_receipt, snapshot, predecessor_generation)
    if isinstance(predecessor_receipt, RotatedPartitionReceipt) and predecessor_receipt.attestation_sha256 == digest:
        raise PartitionRotationRefused(
            f"attestation {digest[:12]} already adjudicated generation {predecessor_generation}; a rotation "
            "requires a fresh attestation over the predecessor generation"
        )
    ledger = _read_predecessor_ledger(snapshot)
    foreign = [key for key in ledger.keys if not key.startswith(_ROTATION_EFFECT_PREFIX)]
    if foreign:
        raise PartitionRotationRefused(
            f"predecessor evidence carries non-publish effect keys {foreign!r}; rotation adjudicates "
            "publish_committed_branch effects only"
        )
    if ledger.dangling:
        raise PartitionRotationRefused(
            f"predecessor evidence has intents without a terminal {list(ledger.dangling)!r}"
        )
    owner = _rotation_owner(snapshot, identity)
    if owner is not None and not bool(owner.get("sealed", False)):
        owner_key = owner.get("effect_key") or owner.get("idempotency_key")
        if owner_key not in ledger.blocked and owner_key not in ledger.terminals:
            raise PartitionRotationRefused(
                "predecessor carries an unsealed adapter-start owner whose effect has no terminal"
            )
    if not ledger.blocked:
        raise PartitionRotationRefused(
            f"{identity} generation {predecessor_generation} has no ambiguity-blocked effect; nothing to rotate"
        )
    if set(effects) != set(ledger.blocked):
        raise PartitionRotationRefused(
            "attestation must adjudicate exactly the blocked effects: "
            f"missing {sorted(set(ledger.blocked) - set(effects))!r}, "
            f"extra {sorted(set(effects) - set(ledger.blocked))!r}"
        )
    for key, entry in effects.items():
        if entry.get("ambiguity_digest") != ledger.blocked[key]:
            raise PartitionRotationRefused(f"attestation ambiguity_digest for {key!r} does not bind the blocked row")
        expected_owner = _rotation_owner_identity(owner, key)
        for field in ("owner_nonce", "transaction_id"):
            if entry.get(field) != expected_owner.get(field):
                raise PartitionRotationRefused(
                    f"attestation {field} for {key!r} does not match the adapter-start owner record"
                )

    carried = _rotation_carried_effects(predecessor_receipt, ledger, effects, identity, predecessor_generation, digest)
    high_water = max(int(predecessor_receipt.legacy_epoch_high_water), _rotation_admissions_high_water(snapshot))
    return _RotationAdjudication(effects, digest, expected_digests, carried, high_water)


def _require_sealed_inventory_derives(
    inventory_path: Path,
    cutover_id: str,
    identity: str,
    digest: str,
    derived: dict,
    *,
    successor_generation: int,
    generation: int,
) -> dict:
    """Load the sealed inventory and require it to BE ``derived``, typed.

    The seals prove the inventory's CONSISTENCY, not its truth.  The inventory
    is a pure function of the validated predecessor bytes and the attestation
    the caller has just adjudicated, so the caller re-derived it; the sealed
    bytes must digest to exactly that body before anything is written.  This
    binds every field at once -- identity, container, chain, predecessor
    digests (codex r6 P1), and the authority-bearing epoch floor, adjudicated
    dispositions, carried landed effects and root inventory (codex r7 P1) --
    on EVERY arm that resumes or completes a sealed ceremony (codex r8 P1).
    """
    sealed = _load_rotation_inventory(inventory_path, cutover_id, identity)
    if sealed.get("attestation_sha256") != digest:
        raise PartitionRotationRefused(
            f"rotation {cutover_id!r} sealed a different attestation; resume with the sealed one"
        )
    # D7-2: a resume uses the successor number the ceremony RECORDED when it
    # sealed, never one re-derived from the pointer it finds today.
    recorded = sealed["partitions"][identity]
    if (
        recorded.get("generation") != successor_generation
        or recorded.get("predecessor_generation") != generation
    ):
        raise PartitionRotationRefused(
            f"rotation {cutover_id!r} sealed generation {recorded.get('generation')!r} over "
            f"predecessor {recorded.get('predecessor_generation')!r}, but the active generation "
            f"is {generation}; the sealed ceremony does not resume against this pointer"
        )
    if _inventory_digest(derived) != sealed["inventory_sha256"]:
        raise PartitionRotationRefused(
            f"sealed rotation inventory for {cutover_id!r} does not bind the partition it "
            "resumes: it is not the inventory this predecessor and attestation derive "
            f"(differs at {_inventory_divergence(sealed, derived)!r})"
        )
    return sealed


def rotate_blocked_partition(
    worktree: Path | str,
    *,
    cutover_id: str,
    attestation: dict,
    authority_root: Path | str | None = None,
) -> PartitionRotationOutcome:
    """Open the successor generation of an ambiguity-blocked repository partition.

    Every check that can refuse without writing runs before the ceremony takes
    the predecessor's ``admissions.lock``; once inside, the journal under the
    authority's ``partition-rotations/<identity>/`` drives an idempotent,
    crash-resumable sequence that ends with the atomic pointer flip.
    """
    import fcntl

    cutover_id = _validate_cutover_id(cutover_id)
    snapshot = repository_snapshot(worktree)
    container = snapshot.container
    identity = snapshot.identity
    active = snapshot.store_root
    _root, generation = _partition_layout(active)
    successor_generation = generation + 1
    generations = container / GENERATIONS_DIR
    successor = generations / str(successor_generation)
    authority = _canonical_input_path(
        authority_root or default_fabpub_authority_root(), label="authority root"
    )
    ceremony = authority / ROTATION_CEREMONY_DIR / identity
    journal = ceremony / f"{cutover_id}{_ROTATION_JOURNAL_SUFFIX}"
    inventory_path = ceremony / f"{cutover_id}.inventory.json"

    # -- the governing receipts (zero-write) ---------------------------------
    try:
        base = load_partition_receipt(container)
    except LegacyCutoverConflict as error:
        raise PartitionRotationRefused(
            f"container receipt for {identity} does not authenticate: {error}"
        ) from error
    if base is None or isinstance(base, RotatedPartitionReceipt):
        raise PartitionRotationRefused(f"no container partition receipt governs {container}")
    claim = _receipt_bootstrap_claim(base) if base.zero_source else None
    if claim is None or claim["authority_root"] != authority:
        raise PartitionRotationRefused(
            f"{identity} is not a zero-history bootstrap partition under {authority}; "
            "only bootstrap-governed partitions rotate"
        )
    if not _receipt_active_authority_exists(base, authority_root=authority):
        raise PartitionRotationRefused(f"the bootstrap authority governing {identity} is not ACTIVE")
    if base.ambiguous:
        raise PartitionRotationRefused(
            f"the container receipt of {identity} is ambiguity-blocked; rotation cannot lift an "
            "archived ambiguity"
        )
    if active == container:
        active_receipt = base
    else:
        try:
            active_receipt = load_partition_receipt(active)
        except LegacyCutoverConflict as error:
            raise PartitionRotationRefused(
                f"active generation {generation} of {identity} does not authenticate: {error}"
            ) from error
        if active_receipt is None:
            raise PartitionRotationRefused(f"active generation {generation} of {identity} carries no receipt")
    if bool(getattr(active_receipt, "ambiguous", False)):
        raise PartitionRotationRefused(f"active generation {generation} of {identity} is ambiguity-blocked")

    # -- ceremony state on disk (zero-write) ----------------------------------
    for candidate in sorted(container.glob(f"{GENERATIONS_DIR}.tmp.*")):
        if candidate.name != f"{GENERATIONS_DIR}.tmp.{cutover_id}":
            raise PartitionRotationRefused(f"foreign rotation staging debris at {candidate}")
    _refuse_other_rotations_in_progress(ceremony, journal, identity, cutover_id)
    states = _rotation_own_journal(journal, cutover_id)
    if isinstance(active_receipt, RotatedPartitionReceipt) and active_receipt.cutover_id == cutover_id:
        # The pointer already names THIS ceremony's successor: everything up to
        # the flip is durable, so only the ACTIVE row and the latch activation
        # can be outstanding (a crash after the flip, or a completed ceremony
        # re-run).  Both are idempotent; finish them under the SUCCESSOR's lock,
        # the one post-flip completion path every instance of this ceremony
        # shares (codex r3 finding 1).  The successor receipt authenticated,
        # but that proves the sealed inventory's CONSISTENCY only: adjudicate
        # the PREDECESSOR against the attestation this call supplies and require
        # the sealed inventory to be the one that adjudication derives -- exactly
        # what the pre-flip resume requires -- before the ACTIVE row and the
        # latch activation make the successor's authority final (codex r8 P1).
        predecessor = _rotation_predecessor_root(container, generation)
        if predecessor == container:
            predecessor_receipt = base
        else:
            try:
                predecessor_receipt = load_partition_receipt(predecessor)
            except LegacyCutoverConflict as error:
                raise PartitionRotationRefused(
                    f"predecessor generation {generation - 1} of {identity} does not authenticate: {error}"
                ) from error
            if predecessor_receipt is None:
                raise PartitionRotationRefused(
                    f"predecessor generation {generation - 1} of {identity} carries no receipt"
                )
        adjudicated = _adjudicate_rotation_predecessor(
            attestation, _snapshot_predecessor(predecessor), generation - 1, predecessor_receipt, identity
        )
        sealed = _require_sealed_inventory_derives(
            inventory_path,
            cutover_id,
            identity,
            adjudicated.digest,
            _derive_rotation_inventory(
                cutover_id=cutover_id,
                identity=identity,
                container=container,
                predecessor_receipt=predecessor_receipt,
                successor_generation=generation,
                generation=generation - 1,
                predecessor_digests=adjudicated.predecessor_digests,
                attestation=attestation,
                digest=adjudicated.digest,
                effects=adjudicated.effects,
                high_water=adjudicated.high_water,
                carried=adjudicated.carried,
            ),
            successor_generation=generation,
            generation=generation - 1,
        )
        # The finish activates the receipt the ADJUDICATED inventory produces,
        # never the one it happened to read from disk (codex r9 P1).
        return _finish_rotation_after_flip(
            snapshot,
            container,
            active,
            generation,
            journal,
            cutover_id,
            _rotation_receipt_from_partition(cutover_id, sealed["partitions"][identity], sealed, journal),
        )
    if states and states[-1] == "ACTIVE":
        raise PartitionRotationRefused(
            f"rotation {cutover_id!r} already completed but does not govern the active generation"
        )

    # -- the attestation (zero-write) -----------------------------------------
    adjudicated = _adjudicate_rotation_predecessor(
        attestation, _snapshot_predecessor(active), generation, active_receipt, identity
    )
    digest = adjudicated.digest
    expected_digests = adjudicated.predecessor_digests
    derived = _derive_rotation_inventory(
        cutover_id=cutover_id,
        identity=identity,
        container=container,
        predecessor_receipt=active_receipt,
        successor_generation=successor_generation,
        generation=generation,
        predecessor_digests=expected_digests,
        attestation=attestation,
        digest=digest,
        effects=adjudicated.effects,
        high_water=adjudicated.high_water,
        carried=adjudicated.carried,
    )

    sealed: dict | None = None
    if "INVENTORY_SEALED" in states:
        sealed = _require_sealed_inventory_derives(
            inventory_path,
            cutover_id,
            identity,
            digest,
            derived,
            successor_generation=successor_generation,
            generation=generation,
        )
    elif successor.exists():
        raise PartitionRotationRefused(
            f"successor generation {successor} exists but rotation {cutover_id!r} never sealed it"
        )

    # -- the ceremony: one critical section under the predecessor's lock -------
    latch = WriterGenerationLatch(snapshot.namespace_root)
    receipt: RotatedPartitionReceipt | None = None
    lock_path = active / "admissions.lock"
    try:
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                # Everything above was read WITHOUT the lock.  A ceremony that
                # completed while this one waited (the same or another cutover_id)
                # has moved the pointer, advanced a journal, or created the
                # successor; re-read all three here, before the latch is touched,
                # so a stale rotator refuses (or, for its own completed ceremony,
                # finishes idempotently) instead of journalling a second DRAINING
                # onto an ACTIVE ceremony or adopting another ceremony's successor.
                current_generation = _read_active_generation(container)
                if current_generation != generation:
                    fresh = _rotation_own_journal(journal, cutover_id)
                    # ARMED, not ACTIVE: another instance of THIS ceremony has
                    # flipped the pointer to our successor and may still be
                    # between releasing this lock and taking the successor's
                    # (fable r4 finding 1).  The finish below requires ARMED,
                    # appends ACTIVE only if absent and activates idempotently,
                    # so the same ceremony arriving late still returns ACTIVE.
                    if current_generation == successor_generation and "ARMED" in fresh:
                        completed = load_partition_receipt(successor)
                        if isinstance(completed, RotatedPartitionReceipt) and completed.cutover_id == cutover_id:
                            # THIS ceremony completed (or is completing) under
                            # another instance -- over the inventory THIS
                            # instance derives, or not at all (codex r8 P1).
                            elsewhere = _require_sealed_inventory_derives(
                                inventory_path,
                                cutover_id,
                                identity,
                                digest,
                                derived,
                                successor_generation=successor_generation,
                                generation=generation,
                            )
                            # The latch is not touched here:
                            # this lock is generation ``generation``'s, and a
                            # ceremony out of the successor drains the latch
                            # under the SUCCESSOR's lock (codex r2 finding 1).
                            # Finish under that lock, after this one, on the
                            # receipt the adjudicated inventory produces
                            # (codex r9 P1).
                            raise _RotationCompletedElsewhere(
                                _rotation_receipt_from_partition(
                                    cutover_id, elsewhere["partitions"][identity], elsewhere, journal
                                )
                            )
                    raise PartitionRotationRefused(
                        f"the active generation of {identity} moved from {generation} to "
                        f"{current_generation} while {cutover_id!r} waited for the predecessor lock; "
                        "re-run the ceremony against the active generation"
                    )
                if _rotation_own_journal(journal, cutover_id) != states:
                    raise PartitionRotationRefused(
                        f"rotation {cutover_id!r} advanced while it waited for the predecessor lock; "
                        "re-run to resume it"
                    )
                _refuse_other_rotations_in_progress(ceremony, journal, identity, cutover_id)
                if "INVENTORY_SEALED" not in states and successor.exists():
                    raise PartitionRotationRefused(
                        f"successor generation {successor} appeared while {cutover_id!r} waited for "
                        "the predecessor lock; another ceremony owns it"
                    )
                if not latch.exists():
                    raise PartitionRotationRefused(f"{identity} has no writer generation latch")
                latch_state = latch.read().generation_state
                if latch_state == "ACTIVE":
                    latch.begin_draining()
                elif latch_state != "DRAINING":
                    raise PartitionRotationRefused(
                        f"writer generation latch of {identity} is {latch_state}; rotation requires ACTIVE"
                    )
                if "DRAINING" not in states:
                    _rotation_journal_append(journal, cutover_id, "DRAINING")
                    states.append("DRAINING")
                _maybe_rotation_crash("after_journal_draining")
                try:
                    latch.await_quiescent(worktree=worktree)
                except WriterGenerationBlocked as error:
                    latch.resume_active()
                    raise PartitionRotationRefused(f"predecessor writers did not drain: {error}") from error
                current = {name: _sha256_file(active / name) for name in ROTATION_DIGESTED_FILES}
                if current != expected_digests:
                    latch.resume_active()
                    raise PartitionRotationRefused(
                        "the predecessor store changed between attestation and drain; re-attest over "
                        "the current bytes"
                    )
                if sealed is None:
                    sealed = derived
                    _atomic_write_json(inventory_path, sealed)
                if "INVENTORY_SEALED" not in states:
                    _rotation_journal_append(journal, cutover_id, "INVENTORY_SEALED")
                    states.append("INVENTORY_SEALED")
                _maybe_rotation_crash("after_journal_inventory_sealed")
                if not os.path.lexists(generations):
                    staging = container / f"{GENERATIONS_DIR}.tmp.{cutover_id}"
                    staging.mkdir(exist_ok=True)
                    _write_active_pointer(staging, generation)
                    _maybe_rotation_crash("before_generations_rename")
                    os.rename(staging, generations)
                    _fsync_dir(container)
                else:
                    _maybe_rotation_crash("before_generations_rename")
                _maybe_rotation_crash("after_generations_rename")
                successor.mkdir(parents=True, exist_ok=True)
                successor_lock = successor / "admissions.lock"
                if not successor_lock.exists():
                    successor_lock.touch()
                _maybe_rotation_crash("between_successor_files")
                successor_evidence = successor / "evidence.jsonl"
                if not successor_evidence.exists():
                    successor_evidence.touch()
                _fsync_dir(successor)
                receipt = _rotation_receipt_from_partition(
                    cutover_id, sealed["partitions"][identity], sealed, journal
                )
                try:
                    receipt.write(successor)
                except LegacyCutoverConflict as exc:
                    # A receipt already on disk that is not the sealed one is a
                    # resume refusal like every other, not a bare conflict
                    # (fable r7 F2): the pointer stays where it is.
                    raise PartitionRotationRefused(
                        f"cannot write the receipt rotation {cutover_id!r} sealed for successor "
                        f"generation {successor_generation} of {identity}; the pointer stays at "
                        f"{generation}: {exc}"
                    ) from exc
                _maybe_rotation_crash("after_successor_receipt_before_flip")
                if "ARMED" not in states:
                    _rotation_journal_append(journal, cutover_id, "ARMED")
                    states.append("ARMED")
                latch.mark_armed()
                _maybe_rotation_crash("after_journal_armed")
                # Backstop that closes the class by construction: before the
                # pointer names it, the successor must authenticate through the
                # EXACT loader every route will use, and load back as the
                # receipt just written.  Whatever the zero-write bindings above
                # miss — a check the loader gains later, an inventory swapped on
                # disk after it was read — refuses HERE, at the state an
                # ``after_journal_armed`` crash already resumes from, instead of
                # ACTIVE-ing an unroutable generation (fable r6 F1).
                try:
                    loaded = load_partition_receipt(successor)
                except (LegacyCutoverConflict, PermissionError) as exc:
                    raise PartitionRotationRefused(
                        f"successor generation {successor_generation} of {identity} does not "
                        f"authenticate before the flip; the pointer stays at {generation}: {exc}"
                    ) from exc
                if loaded is None:
                    raise PartitionRotationRefused(
                        f"successor generation {successor_generation} of {identity} carries no "
                        f"receipt before the flip; the pointer stays at {generation}"
                    )
                if loaded != receipt:
                    raise PartitionRotationRefused(
                        f"successor generation {successor_generation} of {identity} loads as a "
                        f"different receipt than rotation {cutover_id!r} wrote; the pointer stays "
                        f"at {generation}"
                    )
                _write_active_pointer(generations, successor_generation)
                _maybe_rotation_crash("after_pointer_flip")
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except _RotationCompletedElsewhere as done:
        receipt = done.receipt
    assert receipt is not None
    # The pointer names the successor and generation ``generation``'s lock is
    # released.  The ACTIVE row and the latch activation are ONE completion
    # path shared by every instance of this ceremony — the live original, a
    # crash-resume, a same-id retry that found the pointer already flipped —
    # and it runs under the SUCCESSOR's lock with the journal re-read there,
    # so two instances can never both append ACTIVE (codex r3 finding 1).
    return _finish_rotation_after_flip(
        snapshot, container, successor, successor_generation, journal, cutover_id, receipt
    )


def _refuse_other_rotations_in_progress(
    ceremony: Path, journal: Path, identity: str, cutover_id: str
) -> None:
    """A ceremony under another cutover_id that has not reached ACTIVE refuses this one."""
    if not ceremony.exists():
        return
    for other in sorted(ceremony.glob(f"*{_ROTATION_JOURNAL_SUFFIX}")):
        if other == journal:
            continue
        other_id = other.name[: -len(_ROTATION_JOURNAL_SUFFIX)]
        try:
            other_states, other_ids = _journal_entries(other)
        except LegacyCutoverConflict as error:
            raise PartitionRotationRefused(
                f"rotation journal {other_id!r} for {identity} is unreadable: {error}"
            ) from error
        if (
            not _rotation_states_well_formed(other_states)
            or other_states[-1] != "ACTIVE"
            or set(other_ids) != {other_id}
        ):
            raise PartitionRotationRefused(
                f"rotation {other_id!r} for {identity} is still in progress; resume it "
                f"under its own cutover_id before starting {cutover_id!r}"
            )


def _finish_rotation_after_flip(
    snapshot: RepositorySnapshot,
    container: Path,
    active: Path,
    generation: int,
    journal: Path,
    cutover_id: str,
    receipt: RotatedPartitionReceipt,
) -> PartitionRotationOutcome:
    """Complete a ceremony whose pointer already names its successor.

    The successor receipt authenticated (so the journal is at least ARMED and
    the sealed inventory produced these bytes); what may be missing is the
    ACTIVE row and the latch activation — a crash at either post-flip step.
    Both are idempotent and run under the ACTIVE generation's
    ``admissions.lock``: the latch is repository-common, and the next ceremony
    out of this generation drains it under exactly that lock, so a stale
    retry of THIS ceremony serialises behind it instead of activating the
    latch out from under its drain (codex r2 finding 1).  This is the ONLY
    post-flip completion path: the live original releases the predecessor's
    lock after the flip and comes here too, so a same-id retry racing it
    serialises on this lock and the journal re-read under it keeps the ACTIVE
    row single (codex r3 finding 1).  Under the lock the pointer and the
    other journals are re-read; a ceremony in progress under another
    ``cutover_id`` owns the latch and this finish refuses, typed.

    ``receipt`` is the receipt the ADJUDICATED inventory produces -- every
    arm builds it from the derivation it just validated, never from bytes it
    read.  The pre-flip backstop proved the successor loaded as that receipt
    under the PREDECESSOR's lock; between that lock's release and this one
    the successor store and the sealed inventory are unguarded, so the same
    proof is repeated HERE, under the lock that guards the ACTIVE row and the
    latch activation, and a forgery re-sealed in the window refuses typed
    instead of becoming the successor's authority (codex r9 P1).
    """
    import fcntl

    predecessor = _rotation_predecessor_root(container, generation)
    latch = WriterGenerationLatch(snapshot.namespace_root)
    lock_path = active / "admissions.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if _read_active_generation(container) != generation:
                raise PartitionRotationRefused(
                    f"the active generation of {snapshot.identity} moved while {cutover_id!r} "
                    "waited for the active generation's lock; re-run the ceremony"
                )
            _refuse_other_rotations_in_progress(journal.parent, journal, snapshot.identity, cutover_id)
            states = _rotation_own_journal(journal, cutover_id)
            if "ARMED" not in states:
                raise PartitionRotationRefused(
                    f"generation {generation} of {snapshot.identity} is routed but rotation "
                    f"{cutover_id!r} never reached ARMED: {states}"
                )
            try:
                loaded = load_partition_receipt(active)
            except (LegacyCutoverConflict, PermissionError) as exc:
                raise PartitionRotationRefused(
                    f"successor generation {generation} of {snapshot.identity} does not "
                    f"authenticate under its own lock; rotation {cutover_id!r} withholds the "
                    f"ACTIVE row and the latch activation: {exc}"
                ) from exc
            if loaded is None:
                raise PartitionRotationRefused(
                    f"successor generation {generation} of {snapshot.identity} carries no receipt "
                    f"under its own lock; rotation {cutover_id!r} withholds the ACTIVE row and the "
                    "latch activation"
                )
            if loaded != receipt:
                raise PartitionRotationRefused(
                    f"successor generation {generation} of {snapshot.identity} loads as a "
                    f"different receipt than the inventory rotation {cutover_id!r} adjudicated "
                    "produces; the ACTIVE row and the latch activation are withheld"
                )
            if "ACTIVE" not in states:
                _rotation_journal_append(journal, cutover_id, "ACTIVE")
            _maybe_rotation_crash("after_journal_active")
            if not latch.exists():
                raise PartitionRotationRefused(f"{snapshot.identity} has no writer generation latch")
            latch.mark_armed()
            latch.activate()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return PartitionRotationOutcome(cutover_id, "ACTIVE", active, predecessor, generation, receipt)


def _rotation_predecessor_root(container: Path, generation: int) -> Path:
    if generation <= 1:
        return container
    return container / GENERATIONS_DIR / str(generation - 1)


def _traditional_active_authority_exists(roots: tuple[Path, ...]) -> bool:
    roots = tuple(dict.fromkeys(sorted((Path(root) for root in roots), key=str)))
    if not roots:
        return False
    expected_root_set = _root_set_digest(roots)
    cutover_id = None
    primary_authority = None
    for root in roots:
        pointer = Path(root) / "fabpub-global-cutover" / "ACTIVE_CUTOVER"
        if not pointer.exists():
            return False
        claim = _read_pointer_claim(pointer)
        if claim.get("root_set_sha256") not in (None, expected_root_set):
            return False
        if cutover_id is None:
            cutover_id = claim["cutover_id"]
        elif claim["cutover_id"] != cutover_id:
            return False
        claim_primary = Path(claim.get("primary_authority", pointer.parent))
        if primary_authority is None:
            primary_authority = claim_primary
        elif claim_primary != primary_authority:
            return False
    if cutover_id is None or primary_authority is None:
        return False
    journal = primary_authority / f"{cutover_id}.journal.jsonl"
    return "ACTIVE" in _journal_states(journal)


def _receipt_active_authority_exists(
    receipt: LegacyRepositoryPartitionReceipt | RotatedPartitionReceipt,
    *,
    authority_root: Path | str | None = None,
) -> bool:
    if isinstance(receipt, RotatedPartitionReceipt):
        base = _rotation_base_receipt(receipt)
        journal = Path(receipt.global_journal_path)
        try:
            expected_journal = _expected_rotation_journal(
                base, receipt.canonical_repository_identity, receipt.cutover_id
            )
        except LegacyCutoverConflict:
            return False
        if journal != expected_journal:
            return False
        states, ids = _journal_entries(journal)
        if (
            not _rotation_states_well_formed(states)
            or states[-1] != "ACTIVE"
            or set(ids) != {receipt.cutover_id}
        ):
            return False
        receipt = base
    bootstrap_claim = _receipt_bootstrap_claim(receipt) if receipt.zero_source else None
    if bootstrap_claim is not None:
        requested_authority = (
            _canonical_input_path(authority_root, label="authority root")
            if authority_root is not None
            else bootstrap_claim["authority_root"]
        )
        if requested_authority == bootstrap_claim["authority_root"]:
            bootstrap = _active_bootstrap_inventory(requested_authority)
            if (
                bootstrap is not None
                and bootstrap["cutover_id"] == receipt.cutover_id
                and bootstrap_claim["inventory_sha256"]
                == bootstrap["inventory_sha256"]
            ):
                return True
        return False
    roots = tuple(Path(root) for root in receipt.legacy_root_inventory)
    if roots:
        if not _traditional_active_authority_exists(roots):
            return False
        if receipt.zero_source:
            return True
        states, ids = _journal_entries(Path(receipt.global_journal_path))
        return "ACTIVE" in states and set(ids) == {receipt.cutover_id}
    return False


def global_active_authority_exists(
    roots: tuple[Path, ...] | None = None,
    *,
    authority_root: Path | str | None = None,
) -> bool:
    """True when a traditional or persistent bootstrap authority is ACTIVE."""
    roots = declared_legacy_roots() if roots is None else roots
    if _traditional_active_authority_exists(roots):
        return True
    return _active_bootstrap_inventory(authority_root) is not None


def _receipt_seal_lock_paths(
    receipt: LegacyRepositoryPartitionReceipt | RotatedPartitionReceipt,
) -> tuple[Path, ...]:
    receipt = _rotation_base_receipt(receipt)
    bootstrap_claim = _receipt_bootstrap_claim(receipt) if receipt.zero_source else None
    if bootstrap_claim is not None:
        bootstrap = _active_bootstrap_inventory(bootstrap_claim["authority_root"])
        if bootstrap is None:
            return ()
        return _bootstrap_seal_lock_paths(bootstrap)
    roots = tuple(Path(root) for root in receipt.legacy_root_inventory)
    return _traditional_seal_lock_paths(roots)


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
    """Release every lease and authority lock the barrier retained; idempotent."""
    for lease in report.get("leases", ()):
        with contextlib.suppress(Exception):
            lease.release()
    report["leases"] = []
    authority_locks = report.pop("_authority_locks", None)
    if authority_locks is not None:
        authority_locks.close()


def fabpub_activation_barrier(worktrees: Iterable[Path | str] = ()) -> dict:
    """The one authenticated barrier every activated CLI entry runs FIRST.

    SL1-SOL-08: every named workspace must be a real Git repository and must end
    up with an authenticated receipt; a missing path, a non-Git path, or a
    failed Git probe all fail CLOSED rather than being skipped.  SL1-SOL-06/12:
    every lease acquired here is unwound if any later step raises.
    """
    worktrees = tuple(worktrees)
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
            transaction.activate()
            report["cutover"] = {
                "cutover_id": transaction.cutover_id,
                "state": transaction.state,
            }

        snapshots = []
        for worktree in worktrees:
            if not is_git_repository(worktree):
                raise LegacyCutoverConflict(
                    f"workspace {worktree} is missing, is not a Git repository, or its Git "
                    "probe failed; an activated train may not proceed over an "
                    "unauthenticated workspace"
                )
            snapshot = repository_snapshot(worktree)
            try:
                store_root = snapshot.store_root
            except PartitionRoutingRefused:
                # A torn generation pointer refuses THIS repository only; a
                # host-wide fault (a symlink or an unreadable file under the
                # sealed search roots) must still surface from the bootstrap
                # inventory walk exactly as it did before rotation existed.
                _active_bootstrap_inventory()
                raise
            receipt = load_partition_receipt(store_root)
            snapshots.append((snapshot, receipt))

        authority_lock_paths = {
            path
            for _snapshot, receipt in snapshots
            if receipt is not None
            for path in _receipt_seal_lock_paths(receipt)
        }
        if any(receipt is None for _snapshot, receipt in snapshots):
            bootstrap = _active_bootstrap_inventory()
            if bootstrap is not None:
                authority_lock_paths.update(_bootstrap_seal_lock_paths(bootstrap))
            else:
                roots = declared_legacy_roots()
                authority_lock_paths.update(_traditional_seal_lock_paths(roots))
        authority_locks = contextlib.ExitStack()
        report["_authority_locks"] = authority_locks
        for path in sorted(authority_lock_paths, key=str):
            authority_locks.enter_context(_reentrant_flock(path))

        for snapshot, prior_receipt in snapshots:
            receipt = load_partition_receipt(snapshot.store_root)
            if prior_receipt is not None and receipt != prior_receipt:
                raise LegacyCutoverConflict(
                    f"repository {snapshot.identity} receipt changed while entering the barrier"
                )
            if prior_receipt is None and receipt is not None:
                required_locks = set(_receipt_seal_lock_paths(receipt))
                if not required_locks.issubset(authority_lock_paths):
                    raise LegacyCutoverConflict(
                        f"repository {snapshot.identity} appeared under a different authority "
                        "while entering the barrier"
                    )
            if receipt is not None and not _receipt_active_authority_exists(receipt):
                raise LegacyCutoverConflict(
                    f"repository {snapshot.identity} has no matching global ACTIVE authority"
                )
            if receipt is None:
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
                receipt = load_partition_receipt(snapshot.store_root)
                if receipt is None or not _receipt_active_authority_exists(receipt):
                    raise LegacyCutoverConflict(
                        f"repository {snapshot.identity} could not be authenticated or onboarded"
                    )
            latch = WriterGenerationLatch(snapshot.namespace_root)
            if latch.read().generation_state != "ACTIVE":
                raise LegacyCutoverConflict(
                    f"repository {snapshot.identity} has no ACTIVE writer generation"
                )
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

    @property
    def requires_gh_auth_preflight(self) -> bool:
        """Whether the configured provider adapter depends on the GitHub CLI."""
        return (
            GitHubBrokerAdapter is _CANONICAL_GITHUB_BROKER_ADAPTER
            and self._run is _CANONICAL_PROVIDER_RUN
        )

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

    def _service_for(self, request_or_worktree) -> BrokerService:
        if isinstance(request_or_worktree, (str, Path)):
            worktree = str(request_or_worktree)
            request_repo = None
        else:
            worktree = getattr(request_or_worktree, "adapter_worktree", None)
            request_repo = getattr(request_or_worktree, "repository", getattr(request_or_worktree, "repo", None))

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
        if request_repo and request_repo != snapshot.identity:
            raise LegacyCutoverConflict(
                f"BrokerRequest.repo {request_repo!r} is not the canonical repository "
                f"identity {snapshot.identity!r} derived from {snapshot.worktree}"
            )
        # Stores are shared per REPOSITORY, but the adapter runs
        # `git -C <worktree>`: caching the service by identity alone would send a
        # second linked worktree's publish to the FIRST worktree's checkout.
        cache_key = (snapshot.identity, str(snapshot.worktree))
        service = self._services.get(cache_key)
        if service is None:
            admission_store, evidence_store = self._stores_for(snapshot)
            lease = self._leases[snapshot.identity]
            service = BrokerService(
                admission_store,
                evidence_store,
                GitHubBrokerAdapter(
                    snapshot.worktree,
                    run=self._run,
                    allowed_hosts=self._allowed_hosts,
                    generation_lease=lease,
                ),
                contracts=self._contracts,
            )
            self._services[cache_key] = service
        return service

    def execute(self, request):
        return self._service_for(request).execute(request)

    def readmit_advanced_head(self, auth: DeltaReadmitAuthority) -> DeltaReadmitReceipt | None:
        return self._service_for(auth).readmit_advanced_head(auth)


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
