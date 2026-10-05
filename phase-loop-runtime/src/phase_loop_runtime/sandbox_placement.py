"""Where a review sandbox is placed: one vendor-neutral seam, several backends (agent-harness#896).

A configured sandbox root used to be resolved and then ignored -- the tree was staged and
the seat run locally regardless. This module is the seam that placement goes through, so a
remote host or a cloud sandbox is an adapter rather than a fork of the launch path. Core
names no vendor: a backend registers itself under a URL scheme, either directly or through
the ``phase_loop_runtime.placement_backends`` entry-point group of an optional extra.

**Phases, in order, for every backend** (the contract is in ``advisor_board/CONTRACTS.md``):

1. ``prepare`` -- RUNTIME code (:func:`prepare_local_stage`), never a backend method. The
   tree is staged locally for every backend, so it is revalidated before it can leave the
   operator's custody, by construction.
2. The runtime's revalidations, unchanged, against that local stage.
3. ``commit`` -- a no-op locally; for a remote backend, the transfer of the REVALIDATED stage.
4. ``execute`` / ``wait`` / ``cancel`` / ``renew`` -- the runtime's own launch branches
   locally; backend-executed remotely. Once ``execute`` is called the attempt is launched:
   it never falls back to local.
5. ``release``.

**Receipts.** A backend returns :class:`BackendReceipt` values only. A
:class:`PlacementReceipt` with ``attested_by="runtime"`` is built only by the runtime, for a
step it performed and observed; a backend's claim is wrapped as ``attested_by="backend"`` and
never on its own supports ``sandbox_root_applied``.

This release (plan 1a) has no driver that executes on a non-local backend, so the runtime
refuses every non-local backend before ``prepare`` and before any of its methods
(``panel_invoker._NONLOCAL_EXECUTION_DRIVER``). Registering one changes nothing about where
a seat runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import threading
from typing import Iterable, Mapping, Protocol, Sequence, runtime_checkable

from . import review_stage, sandbox_policy, sandbox_retention

__all__ = [
    "BUILTIN_SCHEMES",
    "CAPABILITIES",
    "EGRESS_RESIDUAL_KINDS",
    "ENTRY_POINT_GROUP",
    "RECEIPT_STEPS",
    "VERIFICATION_METHODS",
    "BackendReceipt",
    "Declaration",
    "EgressNeeds",
    "ExecResult",
    "ExecSpec",
    "ExecutingBackend",
    "LOCAL_BACKEND",
    "LegPlacement",
    "LocalBackend",
    "PlacedSandbox",
    "PlacementBackend",
    "PlacementReceipt",
    "PlacementRequest",
    "PlacementUnavailable",
    "Prepared",
    "applied_rule",
    "backend_for_scheme",
    "is_local",
    "prepare_local_stage",
    "register_backend",
    "resolve_backend",
    "verified_from_backend",
]

ENTRY_POINT_GROUP = "phase_loop_runtime.placement_backends"

#: Schemes the runtime owns. Both resolve to :data:`LOCAL_BACKEND`: ``host:path`` is
#: recorded, never applied (RD6, record-only), and a plugin may never claim either.
BUILTIN_SCHEMES: frozenset[str] = frozenset({"local", "hostpath"})

#: What a backend CAN enforce. Closed: a backend may not invent a capability.
CAPABILITIES: frozenset[str] = frozenset({
    # network
    "private_ranges_unreachable", "public_egress", "private_allowlist", "inbound_closed",
    # confinement
    "filesystem_confined", "uid_isolated", "bounding_set_empty", "seccomp_filtered",
    # other
    "resource_bounded", "one_shot_secret_channel", "operator_custody",
})

#: How a capability was verified FOR THIS PLACEMENT. Only the runtime writes
#: ``runtime_end_to_end``, and only for a destination-level result it observed itself.
VERIFICATION_METHODS: frozenset[str] = frozenset({"runtime_end_to_end", "backend_attested"})

#: Egress a backend admits it cannot close. Closed, like the capabilities.
EGRESS_RESIDUAL_KINDS: frozenset[str] = frozenset({
    "resolver_allowed", "udp_unfiltered_by_name",
})

RECEIPT_STEPS: tuple[str, ...] = ("prepared", "committed", "launched", "completed")
_ATTESTERS = frozenset({"runtime", "backend"})
_SANDBOX_REF = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*")
_HEX64 = re.compile(r"[0-9a-f]{64}")

# Only this module's driver holds the seal; a receipt built without it cannot claim to be
# runtime-attested. Same pattern as `backing._AUTHORIZATION_SEAL`.
_RUNTIME_SEAL = object()


class PlacementUnavailable(RuntimeError):
    """A placement refused BEFORE launch. It falls back, or fails closed under the knob.

    ``str()`` is the bare ``code`` and nothing else: a leg's detail keeps a message only when
    it equals one of the runtime's fixed codes, so a reason in the message would turn every
    refusal into an unknown failure. The reason is kept on :attr:`reason`.
    """

    def __init__(self, code: str, reason: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.reason = reason

    def __str__(self) -> str:
        return self.code


def _check_ref(sandbox_ref: str) -> str:
    if not isinstance(sandbox_ref, str) or not _SANDBOX_REF.fullmatch(sandbox_ref):
        raise PlacementUnavailable("sandbox_placement_ref_invalid")
    return sandbox_ref


@dataclass(frozen=True)
class EgressNeeds:
    """The ``host:port`` endpoints a seat must reach beyond the public internet."""

    allow: tuple[tuple[str, int], ...] = ()

    @classmethod
    def from_policy(cls, policy: "sandbox_policy.EgressPolicy | None" = None) -> "EgressNeeds":
        # The global allowlist is the only source today.
        policy = policy if policy is not None else sandbox_policy.egress_allowlist()
        return cls(tuple(policy.allow))


@dataclass(frozen=True)
class PlacementRequest:
    leg: str
    round_id: str
    repo: str
    snapshot_sha256: str
    deadline_s: float
    egress_needs: EgressNeeds
    #: The decided CD1 channel: the same one-shot channel as the local route.
    one_shot_secret: bool = True


@dataclass(frozen=True)
class BackendReceipt:
    """What a backend CLAIMS happened. Never receipt-class on its own."""

    step: str
    sandbox_ref: str
    snapshot_sha256: str

    def __post_init__(self) -> None:
        if self.step not in RECEIPT_STEPS:
            raise ValueError(f"unknown receipt step {self.step!r}")
        _check_ref(self.sandbox_ref)


@dataclass(frozen=True)
class PlacementReceipt:
    step: str
    sandbox_ref: str
    snapshot_sha256: str
    attested_by: str
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.step not in RECEIPT_STEPS:
            raise ValueError(f"unknown receipt step {self.step!r}")
        if self.attested_by not in _ATTESTERS:
            raise ValueError(f"unknown attester {self.attested_by!r}")
        if self.attested_by == "runtime" and self._seal is not _RUNTIME_SEAL:
            raise ValueError("only the runtime's own driver attests a receipt as runtime")
        _check_ref(self.sandbox_ref)

    @classmethod
    def from_backend(cls, receipt: BackendReceipt) -> "PlacementReceipt":
        return cls(receipt.step, receipt.sandbox_ref, receipt.snapshot_sha256, "backend")

    def to_dict(self) -> dict[str, str]:
        return {
            "step": self.step,
            "sandbox_ref": self.sandbox_ref,
            "snapshot_sha256": self.snapshot_sha256,
            "attested_by": self.attested_by,
        }


def _runtime_receipt(step: str, sandbox_ref: str, snapshot_sha256: str) -> PlacementReceipt:
    return PlacementReceipt(step, sandbox_ref, snapshot_sha256, "runtime", _RUNTIME_SEAL)


@dataclass(frozen=True)
class Declaration:
    """What a backend states about itself, recorded as stated."""

    #: ``(kind, closed_in_guest)`` per residual, kinds from :data:`EGRESS_RESIDUAL_KINDS`.
    egress_residuals: tuple[tuple[str, bool], ...] = ()
    #: Names of control-plane variables injected into the guest; their VALUES are redacted
    #: from evidence and logs.
    guest_control_env: tuple[str, ...] = ()
    max_lifetime_s: float | None = None

    def __post_init__(self) -> None:
        for kind, closed in self.egress_residuals:
            if kind not in EGRESS_RESIDUAL_KINDS or not isinstance(closed, bool):
                raise ValueError(f"unknown egress residual {kind!r}")


@dataclass(frozen=True)
class Prepared:
    """The runtime's local stage, before any backend sees it."""

    review_dir: Path
    local_tree: Path
    snapshot_sha256: str
    sandbox_ref: str
    receipt: PlacementReceipt


@dataclass(frozen=True)
class PlacedSandbox:
    backend: str
    sandbox_ref: str
    staged_at: str
    receipts: tuple[PlacementReceipt, ...]
    #: capability -> verification method; always a subset of the backend's capabilities.
    verified: Mapping[str, str]


@dataclass(frozen=True)
class ExecSpec:
    """What a non-local backend is asked to run (the driver is plan 1b)."""

    argv: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]
    one_shot_secret: bytes | None
    deadline_s: float
    output_cap_bytes: int


@dataclass(frozen=True)
class ExecResult:
    sandbox_ref: str
    exit_status: int
    stdout: bytes
    stderr: bytes
    truncated: bool


@runtime_checkable
class PlacementBackend(Protocol):
    name: str

    def capabilities(self) -> frozenset[str]: ...

    def declaration(self) -> Declaration: ...

    def available(self, request: PlacementRequest) -> bool: ...

    def commit(self, prepared: Prepared, request: PlacementRequest) -> BackendReceipt | None:
        """Transfer the REVALIDATED stage. Owns any partial remote state until it returns,
        and removes it on any exception. A recomputed digest that does not match refuses."""
        ...

    def release(self, prepared: Prepared) -> None: ...


@runtime_checkable
class ExecutingBackend(PlacementBackend, Protocol):
    def execute(self, sandbox_ref: str, spec: ExecSpec) -> BackendReceipt: ...

    def wait(self, sandbox_ref: str, deadline_s: float) -> ExecResult: ...

    def cancel(self, sandbox_ref: str) -> None: ...

    def renew(self, sandbox_ref: str, until_s: float) -> None: ...

    def list_owned(self, owner_id: str) -> Sequence[str]: ...

    def kill(self, sandbox_ref: str) -> None: ...


def verified_from_backend(
    backend: PlacementBackend, claimed: Mapping[str, str],
) -> dict[str, str]:
    """A backend's verification claims, as recorded: never wider than what it can enforce,
    and never ``runtime_end_to_end`` -- only the runtime writes that method."""
    capabilities = frozenset(backend.capabilities())
    verified: dict[str, str] = {}
    for capability, method in claimed.items():
        if capability not in CAPABILITIES or capability not in capabilities:
            raise PlacementUnavailable("sandbox_placement_capability_undeclared")
        if method not in VERIFICATION_METHODS:
            raise PlacementUnavailable("sandbox_placement_capability_undeclared")
        verified[capability] = "backend_attested"
    return verified


class LocalBackend:
    """Today's placement: stage, launch and release on this host. Enforces nothing itself --
    local egress and uid facts stay in their own fields, recorded by the code that enforces
    them."""

    name = "local"

    def capabilities(self) -> frozenset[str]:
        return frozenset()

    def declaration(self) -> Declaration:
        return Declaration()

    def available(self, request: PlacementRequest) -> bool:
        return True

    def commit(self, prepared: Prepared, request: PlacementRequest) -> None:
        return None

    def release(self, prepared: Prepared) -> None:
        review_stage.remove_review_stage(prepared.local_tree)


LOCAL_BACKEND = LocalBackend()

_REGISTRY: dict[str, PlacementBackend] = {}
_REGISTRY_LOCK = threading.Lock()


def is_local(backend: object) -> bool:
    """Bound to the built-in instance, never declared: a plugin cannot claim to be local."""
    return backend is LOCAL_BACKEND


def register_backend(scheme: str, backend: PlacementBackend) -> None:
    """Register a backend for a URL scheme. A protocol check only -- registration never
    makes a backend execute; ``panel_invoker._NONLOCAL_EXECUTION_DRIVER`` decides that."""
    scheme = str(scheme).lower()
    if not _SCHEME.fullmatch(scheme):
        raise ValueError(f"invalid placement scheme {scheme!r}")
    if scheme in BUILTIN_SCHEMES:
        raise ValueError(f"placement scheme {scheme!r} is built in")
    if not isinstance(backend, ExecutingBackend):
        raise TypeError(
            f"a non-local placement backend must implement ExecutingBackend ({scheme!r})"
        )
    with _REGISTRY_LOCK:
        _REGISTRY[scheme] = backend


def _entry_points() -> Iterable[object]:
    from importlib.metadata import entry_points

    return entry_points(group=ENTRY_POINT_GROUP)


def _load_plugins(scheme: str) -> None:
    """Load the entry points registered under ``scheme`` only. A failure is a pre-launch
    refusal for that scheme alone."""
    for entry in _entry_points():
        if getattr(entry, "name", None) != scheme:
            continue
        try:
            loaded = entry.load()
            if callable(loaded):
                loaded()
        except Exception as exc:
            raise PlacementUnavailable(
                "sandbox_placement_plugin_unavailable",
                f"placement plugin for {scheme!r} failed to load: {type(exc).__name__}",
            ) from exc


def backend_for_scheme(scheme: str) -> PlacementBackend | None:
    """The backend for a scheme, loading its plugin on first use. ``None`` when nothing is
    registered. Called only when a configured root names that scheme."""
    scheme = str(scheme).lower()
    if scheme in BUILTIN_SCHEMES:
        return LOCAL_BACKEND
    with _REGISTRY_LOCK:
        backend = _REGISTRY.get(scheme)
    if backend is not None:
        return backend
    _load_plugins(scheme)
    with _REGISTRY_LOCK:
        return _REGISTRY.get(scheme)


def resolve_backend(choice: "sandbox_policy.SandboxRootChoice") -> PlacementBackend:
    scheme = getattr(choice, "scheme", "local")
    if scheme in BUILTIN_SCHEMES:
        return LOCAL_BACKEND
    with _REGISTRY_LOCK:
        backend = _REGISTRY.get(scheme)
    if backend is None:
        raise PlacementUnavailable("sandbox_placement_backend_unregistered")
    return backend


def prepare_local_stage(
    repo: Path, review_dir: Path, *, floor_bytes: int, mark: Path,
) -> Prepared:
    """The runtime-owned ``prepare``, run for EVERY backend: today's local staging sequence.

    It owns the partial state until it returns. On any exception it removes whatever it
    created -- the hardened tree under its pre-rename name, or under the final one -- and
    re-raises; a bare ``rmtree`` cannot unlink through the stage's 0o500 directories.
    """
    sandbox_policy.ensure_staging_space(review_dir, floor_bytes)
    staged = review_stage.stage_review_tree(repo, review_dir)
    current = staged
    try:
        final = review_dir / review_stage.REVIEW_STAGE_TREE_DIRNAME
        staged.rename(final)
        current = final
        # Claim the scratch dir as ours, or retention will never reap it. Identity is a
        # marker this runtime writes, precisely so a bystander directory that merely LOOKS
        # like a sandbox is never deleted.
        sandbox_retention.mark_as_sandbox(mark, owner_pid=os.getpid())
        digest = review_stage.review_tree_manifest_sha256(final)
    except BaseException:
        review_stage.remove_review_stage(current)
        raise
    sandbox_ref = "local:" + _local_ref_name(mark)
    return Prepared(
        review_dir=review_dir, local_tree=final, snapshot_sha256=digest,
        sandbox_ref=sandbox_ref, receipt=_runtime_receipt("prepared", sandbox_ref, digest),
    )


def _local_ref_name(path: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(path).name)[:120]
    return name or "stage"


def applied_rule(
    *,
    backend: object,
    host: str | None,
    path: Path | str,
    staged_at: Path | str,
    receipts: Sequence[PlacementReceipt],
    authorization_sha256: str | None,
    local_spawns: int,
) -> tuple[bool, str | None]:
    """``sandbox_root_applied`` and, when false, why.

    Local: the built-in backend, no host, and the root really is the stage's parent -- the
    rule this record has always used. Non-local: runtime-attested ``committed`` and
    ``completed`` receipts share one ``sandbox_ref`` and both carry the authorization's
    digest, nothing was spawned locally, and any backend receipts agree. Backend receipts
    alone never make it true.
    """
    if is_local(backend):
        if host is None and Path(path) == Path(staged_at).parent:
            return True, None
        return False, (
            "the selected root is recorded but NOT used for placement; remote "
            "co-location is not implemented, so this sandbox was staged locally "
            "(agent-harness#896)"
        )
    runtime = {r.step: r for r in receipts if r.attested_by == "runtime"}
    committed, completed = runtime.get("committed"), runtime.get("completed")
    if committed is None or completed is None:
        return False, "no runtime-attested commit and completion for this placement"
    if committed.sandbox_ref != completed.sandbox_ref:
        return False, "the runtime's commit and completion name different sandboxes"
    if authorization_sha256 is None or not (
        committed.snapshot_sha256 == completed.snapshot_sha256 == authorization_sha256
    ):
        return False, "the placed snapshot is not the authorized tree"
    if local_spawns != 0:
        return False, "a provider was spawned locally for a remotely placed leg"
    for receipt in receipts:
        if receipt.attested_by == "backend" and (
            receipt.sandbox_ref != committed.sandbox_ref
            or receipt.snapshot_sha256 != authorization_sha256
        ):
            return False, "the backend's receipts disagree with the runtime's"
    return True, None


class LegPlacement:
    """One leg's placement state: what was resolved, what the runtime observed."""

    def __init__(
        self, backend: PlacementBackend, prepared: Prepared, *,
        scheme: str, authorization_sha256: str | None,
    ) -> None:
        self.backend = backend
        self.prepared = prepared
        self.scheme = scheme
        self.authorization_sha256 = authorization_sha256
        self.receipts: list[PlacementReceipt] = [prepared.receipt]
        self.verified: dict[str, str] = {}
        self.sandbox_ref = prepared.sandbox_ref

    def record_backend_receipt(self, receipt: BackendReceipt | None) -> None:
        if receipt is not None:
            self.receipts.append(PlacementReceipt.from_backend(receipt))

    def receipts_for(self, local_spawns: int) -> list[PlacementReceipt]:
        receipts = list(self.receipts)
        if is_local(self.backend) and local_spawns > 0 and not any(
            r.step == "launched" and r.attested_by == "runtime" for r in receipts
        ):
            # The runtime spawned the provider itself, and counted it doing so.
            receipts.append(_runtime_receipt(
                "launched", self.prepared.sandbox_ref, self.prepared.snapshot_sha256,
            ))
        return receipts

    def staged_at(self) -> str:
        if is_local(self.backend):
            return str(self.prepared.local_tree)
        return f"{self.scheme}:{self.sandbox_ref}"
