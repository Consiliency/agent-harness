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

The launch site still refuses every non-local backend before ``prepare`` and before any of
its methods (``panel_invoker._NONLOCAL_EXECUTION_DRIVER`` is false). Registering one changes
nothing about where a seat runs.

**The execution driver** (:func:`place`, :func:`run_placed`) is here and is not called by
the launch site yet. :func:`place` walks the configured remote rungs by one state machine,
:data:`LADDER_TABLE`, which is amendment C7 of the contract as data: the walk looks every
transition up in it. Reachability is the driver's own connection attempt; admission is the
backend's answer; every backend call is bounded; a rung that may hold something is fenced
and released by lease id; ``execute`` is reached from one state and ends the walk.
:func:`run_placed` is everything after ``execute``.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
import contextvars
import errno
import stat
import struct
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import secrets
import socket
import threading
import time
from typing import TYPE_CHECKING, Callable, Iterable, Literal, Mapping, NamedTuple, Protocol, Sequence, runtime_checkable

from . import review_stage, sandbox_policy, sandbox_retention

if TYPE_CHECKING:
    from .launch_process_contract import LaunchRequest, PreparedPaths

__all__ = [
    "ANSWER_BOUND_S",
    "BUILTIN_SCHEMES",
    "CAPABILITIES",
    "EGRESS_RESIDUAL_KINDS",
    "ENTRY_POINT_GROUP",
    "LADDER_TABLE",
    "PLACEMENT_CODES",
    "RECEIPT_STEPS",
    "VERIFICATION_METHODS",
    "BackendReceipt",
    "Declaration",
    "EgressNeeds",
    "ExecProgress",
    "ExecResult",
    "ExecSpec",
    "ExecutingBackend",
    "LOCAL_BACKEND",
    "LegPlacement",
    "LocalBackend",
    "LocalReservation",
    "LocalAdmission",
    "LocalHeadroom",
    "OperationBound",
    "PlacedSandbox",
    "PlacementBackend",
    "PlacementCancelled",
    "PlacementDecision",
    "PlacementLifecycle",
    "PlacementReceipt",
    "PlacementRequest",
    "PlacementUnavailable",
    "Prepared",
    "RungReservation",
    "applied_rule",
    "effective_egress",
    "backend_for_scheme",
    "openshell_launch_refusal",
    "openshell_route_state",
    "is_local",
    "lifetime_at_floor",
    "lifetime_sufficient",
    "place",
    "prepare_local_stage",
    "register_backend",
    "resolve_backend",
    "run_placed",
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
#: What a request asks a backend to run (C1, C10). Never an argv.
_WORKLOADS = frozenset({"leg", "qualification", "implementation"})
#: Workloads a request may carry only when the placement lifecycle maps it (v13 PLACECLI):
#: ``pi-runner`` is reserved, never executed, by this driver.
_LIFECYCLE_WORKLOADS = frozenset({"pi-runner"})
_LIFECYCLE_SEAL = object()
_LAST_RUNGS = frozenset({"local", "none"})

_CAPACITY = "sandbox_placement_at_capacity"
_TIMEOUT = "sandbox_placement_operation_timeout"
_REFUSED = "sandbox_placement_refused"
_BUDGET_SPENT = "sandbox_placement_budget_spent"
_UNREACHABLE = "sandbox_placement_unreachable"
_DRIVER_UNAVAILABLE = "sandbox_placement_driver_unavailable"
_REQUIRED_UNAVAILABLE = "sandbox_placement_required_unavailable"
_CAPABILITY_UNMET = "sandbox_placement_capability_unmet"
_CAPACITY_EXHAUSTED = "sandbox_placement_capacity_exhausted"
_CODE_INVALID = "sandbox_placement_code_invalid"
_RELEASE_UNCONFIRMED = "sandbox_placement_release_unconfirmed"
_LOCAL_RELEASE_UNCONFIRMED = "sandbox_placement_local_release_unconfirmed"
_LOST_AFTER_LAUNCH = "sandbox_placement_lost_after_launch"
_END_REACHED = "sandbox_placement_end_reached"
_WAITING_NOTICE = "seat_placement_waiting"
_CANCELLED = "review_operation_cancelled"

#: The runtime's placement codes: a closed list (C7). Each is a member of the leg-detail
#: vocabulary and has a notice row with a fix line. There is ONE capacity code and it is the
#: runtime's; a backend's own registered codes are never members.
PLACEMENT_CODES: frozenset[str] = frozenset({
    _REQUIRED_UNAVAILABLE, _DRIVER_UNAVAILABLE,
    # raised by the seam since plan 1a
    "sandbox_placement_ref_invalid", "sandbox_placement_capability_undeclared",
    "sandbox_placement_plugin_unavailable", "sandbox_placement_backend_unregistered",
    # the walk
    _UNREACHABLE, _BUDGET_SPENT, _CAPACITY, _CAPACITY_EXHAUSTED, _REFUSED, _CODE_INVALID,
    _TIMEOUT, _CAPABILITY_UNMET, _RELEASE_UNCONFIRMED, _LOCAL_RELEASE_UNCONFIRMED,
    "sandbox_placement_not_enrolled", "sandbox_placement_identity_mismatch",
    "sandbox_placement_workload_unsupported",
    # after `execute`
    _LOST_AFTER_LAUNCH, _END_REACHED,
    # shown while a rung is in "waiting"
    _WAITING_NOTICE,
})
#: The runtime's codes a backend may pass on as the far end's refusal (C7, class "refused").
_BACKEND_REFUSALS = frozenset({
    "sandbox_placement_not_enrolled", "sandbox_placement_identity_mismatch",
    "sandbox_placement_workload_unsupported",
})
#: `commit` may also fail with the two codes this seam raises for a bad reference or claim.
_COMMIT_REFUSALS = _BACKEND_REFUSALS | {
    "sandbox_placement_ref_invalid", "sandbox_placement_capability_undeclared",
}
_BACKEND_CODE = re.compile(r"[a-z][a-z0-9_]{2,63}")
_FIX_LINE_MAX = 200

#: How long one request to a far end may go unanswered (admission, `execute`, a kill, a
#: listing, a cancel, a renewal). A constant, not a setting: it is not a deployment's choice
#: but the line between "slow" and "not answering" for a request that does no work, and it
#: must stay far below the admission wait so that a host which accepts a connection and then
#: stops answering costs seconds, not the budget. A transfer (`commit`) is bounded by what
#: is left of the budget instead.
ANSWER_BOUND_S = 30.0
#: How long the walk pauses between two admission requests to a rung that is at capacity.
#: Short against the admission wait (so a freed slot is taken soon) and long against the
#: answer bound's order of magnitude (so a full host is not polled in a loop).
_ADMIT_BACKOFF_S = 15.0
#: The longest one `wait` call is asked to block before it reports progress. It bounds how
#: stale the liveness signal can be and how late the fixed end is noticed.
_WAIT_SLICE_S = 30.0
_POLL_S = 0.05
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

    :func:`run_placed` raises it too, for a leg that was launched and then lost or ended
    (``sandbox_placement_lost_after_launch``, ``sandbox_placement_end_reached``). Nothing
    falls back after ``execute``: that leg is over, on every rung.
    """

    def __init__(self, code: str, reason: str = "", *, uncertain: bool | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.reason = reason
        # Explicit transport evidence; None preserves the pre-existing adapter seam.
        self.uncertain = uncertain

    def __str__(self) -> str:
        return self.code


class PlacementCancelled(RuntimeError):
    """The caller cancelled a walk, or a placed leg. ``str()`` is the fixed code a cancelled
    review operation carries everywhere else, and the trail is attached."""

    def __init__(self, trail: Sequence[Mapping[str, object]] = (), *,
                 local_reservation: LocalReservation | None = None,
                 pending_local_reservation: LocalReservationPending | None = None) -> None:
        super().__init__(_CANCELLED)
        self.trail = tuple(trail)
        self.local_reservation = local_reservation
        self.pending_local_reservation = pending_local_reservation

    def __str__(self) -> str:
        return _CANCELLED


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
    #: ``None`` for a leg with no deadline (C2).
    deadline_s: float | None
    #: Empty for every non-local candidate (C5): :func:`place` sends it empty.
    egress_needs: EgressNeeds
    #: The decided CD1 channel: the same one-shot channel as the local route.
    one_shot_secret: bool = True
    #: ``leg``, ``implementation`` or ``qualification``. Only qualification is gate-exempt.
    workload: str = "leg"
    #: What the backend must declare, and verify after ``commit`` (C5).
    required_capabilities: frozenset[str] = frozenset()
    #: The parsed, sanitized root and its configured backend name; :func:`place` sets it,
    #: with the owner id and the lease id (C6).
    root: "sandbox_policy.SandboxRootChoice | None" = None
    owner_id: str = ""
    lease_id: str = ""
    #: Set only by :class:`PlacementLifecycle`'s workload mapping.
    _mapping: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.workload not in _WORKLOADS and not (
            self.workload in _LIFECYCLE_WORKLOADS and self._mapping is _LIFECYCLE_SEAL
        ):
            raise ValueError(f"unknown workload {self.workload!r}")
        required = frozenset(self.required_capabilities)
        if not required <= CAPABILITIES:
            raise ValueError("unknown required capability")
        object.__setattr__(self, "required_capabilities", required)


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
    #: The mark of a ``qualification`` workload (C10): such a receipt never counts as an
    #: applied placement.
    workload: str = "leg"

    def __post_init__(self) -> None:
        if self.step not in RECEIPT_STEPS:
            raise ValueError(f"unknown receipt step {self.step!r}")
        if self.attested_by not in _ATTESTERS:
            raise ValueError(f"unknown attester {self.attested_by!r}")
        if self.workload not in _WORKLOADS:
            raise ValueError(f"unknown workload {self.workload!r}")
        if self.attested_by == "runtime" and self._seal is not _RUNTIME_SEAL:
            raise ValueError("only the runtime's own driver attests a receipt as runtime")
        _check_ref(self.sandbox_ref)

    @classmethod
    def from_backend(cls, receipt: BackendReceipt) -> "PlacementReceipt":
        return cls(receipt.step, receipt.sandbox_ref, receipt.snapshot_sha256, "backend")

    def to_dict(self) -> dict[str, str]:
        record = {
            "step": self.step,
            "sandbox_ref": self.sandbox_ref,
            "snapshot_sha256": self.snapshot_sha256,
            "attested_by": self.attested_by,
        }
        if self.workload != "leg":
            record["workload"] = self.workload
        return record


def _runtime_receipt(
    step: str, sandbox_ref: str, snapshot_sha256: str, workload: str = "leg",
) -> PlacementReceipt:
    return PlacementReceipt(
        step, sandbox_ref, snapshot_sha256, "runtime", _RUNTIME_SEAL, workload,
    )


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
class OperationBound:
    """The bound on one blocking backend call (C4). A backend returns, or raises
    ``sandbox_placement_operation_timeout``, within ``timeout_s``, and checks ``cancelled``
    while it waits. The driver enforces both itself as well."""

    timeout_s: float
    cancelled: threading.Event


@dataclass(frozen=True)
class ExecSpec:
    """What a non-local backend is asked to run: a workload the runtime owns, never an argv,
    a path or an environment built on the launching host (C1).

    ``request`` travels only on the backend's one-shot channel. ``must_end_within_s`` is
    seconds from the start, fixed when ``execute`` is called and never extended (C2); it is
    ``None`` only when neither a deadline nor an expiry exists.
    """

    workload: str
    request: bytes = field(repr=False)
    deadline_s: float | None
    must_end_within_s: float | None
    output_cap_bytes: int

    def __post_init__(self) -> None:
        if self.workload not in _WORKLOADS:
            raise ValueError(f"unknown workload {self.workload!r}")
        if not isinstance(self.request, bytes):
            raise TypeError("an ExecSpec request is bytes")
        if type(self.output_cap_bytes) is not int or self.output_cap_bytes < 0:
            raise ValueError("invalid output cap")


@dataclass(frozen=True)
class ExecResult:
    sandbox_ref: str
    exit_status: int
    result: bytes = field(repr=False)
    truncated: bool


@dataclass(frozen=True)
class ExecProgress:
    """Not a result yet. A rising ``seq`` is a liveness claim for the review monitor and
    nothing else (C4)."""

    sandbox_ref: str
    seq: int


@runtime_checkable
class PlacementBackend(Protocol):
    name: str

    def capabilities(self) -> frozenset[str]: ...

    def declaration(self) -> Declaration: ...

    def available(self, request: PlacementRequest) -> bool: ...

    def commit(
        self, prepared: Prepared, request: PlacementRequest, bound: OperationBound | None = None,
    ) -> "BackendReceipt | PlacedSandbox | None":
        """Transfer the REVALIDATED stage. Owns any partial remote state until it returns,
        and removes it on any exception. A recomputed digest that does not match refuses.

        A non-local backend returns its ``committed`` receipt, or a :class:`PlacedSandbox`
        when it also claims capabilities verified for this placement (C5)."""
        ...

    def release(self, prepared: Prepared, bound: OperationBound | None = None) -> None: ...


@runtime_checkable
class ExecutingBackend(PlacementBackend, Protocol):
    """A backend the driver can run a workload on. Every blocking call takes an
    :class:`OperationBound` (C4); everything a backend creates or reserves for a request is
    tagged with the request's owner id and lease id from the moment the admission request
    arrives (C6)."""

    def endpoint(self, root: "sandbox_policy.SandboxRootChoice") -> tuple[str, int] | None:
        """The host and port this backend would dial for ``root``, as a name or an address
        literal, WITHOUT resolving anything and without any network use; ``None`` only for
        a backend with no network far side (C3). The driver does the dialling."""
        ...

    def admit(self, request: PlacementRequest, bound: OperationBound) -> None:
        """Send the admission request. Raise ``PlacementUnavailable(code)`` only to pass on
        an answer received from the far end; anything else is "no answer" (C3)."""
        ...

    def execute(self, sandbox_ref: str, spec: ExecSpec, bound: OperationBound) -> BackendReceipt: ...

    def wait(self, sandbox_ref: str, wait_s: float) -> "ExecResult | ExecProgress": ...

    def cancel(self, sandbox_ref: str, bound: OperationBound) -> None: ...

    def renew(self, sandbox_ref: str, until_s: float, bound: OperationBound) -> None:
        """Keep the sandbox alive for ``until_s`` more seconds, counted from this call."""
        ...

    def list_owned(self, owner_id: str, bound: OperationBound) -> Sequence[tuple[str, str]]:
        """``(sandbox_ref, lease_id)`` for everything of this owner, reservations included."""
        ...

    def kill(self, lease_id: str, bound: OperationBound) -> None:
        """Remove what exists for this lease id and FENCE it: never complete an admission
        or a transfer for it, never start a workload for it (C6)."""
        ...


def verified_from_backend(
    backend: PlacementBackend, claimed: Mapping[str, str],
) -> dict[str, str]:
    """A backend's verification claims, as recorded: never wider than what it can enforce,
    and never ``runtime_end_to_end`` -- only the runtime writes that method."""
    return _verified(frozenset(backend.capabilities()), claimed)


def _verified(capabilities: frozenset[str], claimed: Mapping[str, str]) -> dict[str, str]:
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

    def commit(
        self, prepared: Prepared, request: PlacementRequest, bound: OperationBound | None = None,
    ) -> None:
        return None

    def release(self, prepared: Prepared, bound: OperationBound | None = None) -> None:
        review_stage.remove_review_stage(prepared.local_tree)


LOCAL_BACKEND = LocalBackend()

_REGISTRY: dict[str, PlacementBackend] = {}
#: scheme -> {a backend's own refusal code: its fix line}. The codes only supply fix lines;
#: they are never members of :data:`PLACEMENT_CODES` or of the leg-detail vocabulary.
_BACKEND_CODES: dict[str, dict[str, str]] = {}
_REGISTRY_LOCK = threading.Lock()


def is_local(backend: object) -> bool:
    """Bound to the built-in instance, never declared: a plugin cannot claim to be local."""
    return backend is LOCAL_BACKEND


def register_backend(
    scheme: str, backend: PlacementBackend, codes: Mapping[str, str] | None = None,
) -> None:
    """Register a backend for a URL scheme. A protocol check only -- registration never
    makes a backend execute; ``panel_invoker._NONLOCAL_EXECUTION_DRIVER`` decides that.

    ``codes`` maps the backend's OWN refusal codes to their fix lines. A code is a short
    lower-case identifier that is not one of the runtime's; a fix line is one printable
    line. Anything a backend raises that is neither the runtime's nor registered here is
    recorded as ``sandbox_placement_code_invalid`` and its text is dropped."""
    scheme = str(scheme).lower()
    if not _SCHEME.fullmatch(scheme):
        raise ValueError(f"invalid placement scheme {scheme!r}")
    if scheme in BUILTIN_SCHEMES:
        raise ValueError(f"placement scheme {scheme!r} is built in")
    if not isinstance(backend, ExecutingBackend):
        raise TypeError(
            f"a non-local placement backend must implement ExecutingBackend ({scheme!r})"
        )
    own: dict[str, str] = {}
    for code, fix in dict(codes or {}).items():
        if not isinstance(code, str) or not _BACKEND_CODE.fullmatch(code) or code in PLACEMENT_CODES:
            raise ValueError("invalid backend placement code")
        if (
            not isinstance(fix, str) or not fix.strip() or len(fix) > _FIX_LINE_MAX
            or not fix.isprintable()
        ):
            raise ValueError("invalid fix line for a backend placement code")
        own[code] = fix
    with _REGISTRY_LOCK:
        _REGISTRY[scheme] = backend
        _BACKEND_CODES[scheme] = own


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
    if any(r.workload != "leg" for r in receipts):
        return False, "a non-leg workload is never an applied placement"
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
        #: Codes a placed leg carries beside its result (C11).
        self.notices: list[str] = []
        self.workload = "leg"
        # What the driver observed, in order. Only :func:`place` and :func:`run_placed`
        # write these; `record_runtime` attests nothing they did not observe.
        self._observed: set[str] = set()
        self._lease: object = None
        self._spec: ExecSpec | None = None
        self._driver_settings: sandbox_policy.PlacementDriverSettings | None = None
        self._launched_at: float | None = None
        self._launch_failed = False
        self._trail: tuple[Mapping[str, object], ...] = ()

    def record_backend_receipt(self, receipt: BackendReceipt | None) -> None:
        if receipt is not None:
            self.receipts.append(PlacementReceipt.from_backend(receipt))

    def record_runtime(self, step: str) -> PlacementReceipt:
        """The only builder of a runtime-attested ``committed``, ``launched`` or
        ``completed`` receipt for a non-local placement (C9).

        Each is built once, and only for a step the driver performed and observed:
        ``committed`` when ``commit`` returned for the digest the runtime computed,
        ``launched`` when the driver called ``execute``, ``completed`` when it received a
        terminal result for the same ``sandbox_ref`` that echoes the request's digest."""
        if is_local(self.backend):
            raise ValueError("a local placement's receipts are built by receipts_for")
        if step not in ("committed", "launched", "completed") or step not in self._observed:
            raise ValueError(f"the runtime did not observe {step!r} for this placement")
        for receipt in self.receipts:
            if receipt.step == step and receipt.attested_by == "runtime":
                return receipt
        receipt = _runtime_receipt(
            step, self.sandbox_ref, self.prepared.snapshot_sha256, self.workload,
        )
        self.receipts.append(receipt)
        return receipt

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


# ----------------------------------------------------------------------------------------
# The execution driver (agent-harness#896, amendments C1-C12 of the contract).
# ----------------------------------------------------------------------------------------

class _LadderRow(NamedTuple):
    state: str
    event: str
    next: str
    #: The contract's own words for the event and for what it means.
    when: str
    means: str


class _AfterLeftRow(NamedTuple):
    condition: str
    walk: str
    when: str
    then: str


class _Ladder(NamedTuple):
    rung: tuple[_LadderRow, ...]
    after_left: tuple[_AfterLeftRow, ...]


#: Amendment C7 as data: the states of the rung in hand with what moves them, and what the
#: walk does after a rung is left (first matching row). :func:`place` looks every
#: transition up here, so a change to a row is a change to the walk. ``next`` is a state,
#: ``left:<class>`` or ``execute``. A cancel is not a row: it is accepted in every state.
LADDER_TABLE = _Ladder(
    rung=(
        _LadderRow(
            "start", "local_check_failed", "left:failed_locally",
            (
                "a local check fails: no backend is registered for the root's scheme or its "
                "plugin does not load, `available()` is false, `endpoint` raises, a required "
                "capability is not declared, the deadline exceeds the backend's maximum "
                "lifetime, a `leg` or `implementation` workload while the driver flag is false"
            ),
            "Nothing was sent",
        ),
        _LadderRow(
            "start", "local_checks_passed", "connecting",
            "the local checks pass",
            "",
        ),
        _LadderRow(
            "connecting", "connect_failed", "left:unreachable",
            "the driver's own resolution or connection fails",
            "Nothing was sent",
        ),
        _LadderRow(
            "connecting", "lease_unwritable", "left:failed_locally",
            "connected, but the lease entry cannot be written",
            "Nothing was sent",
        ),
        _LadderRow(
            "connecting", "budget_spent", "left:out_of_time",
            "budget spent",
            (
                "Nothing was sent. Running out of time is not evidence that the host is "
                "unreachable"
            ),
        ),
        _LadderRow(
            "connecting", "connected", "admitting",
            "connected, lease entry fsynced",
            "The admission request is sent",
        ),
        _LadderRow(
            "admitting", "admitted", "committing",
            "admitted",
            "A slot is held on the far side",
        ),
        _LadderRow(
            "admitting", "at_capacity", "waiting",
            "the backend raises the runtime's capacity code",
            (
                "The far end's answer means it "
                "holds nothing."
            ),
        ),
        _LadderRow(
            "admitting", "refused", "left:refused",
            "any other code except the time-out code",
            (
                "The far end's own refusal means it holds nothing; the lease entry is cleared"
            ),
        ),
        _LadderRow(
            "admitting", "no_answer", "releasing",
            (
                "no answer: the time-out code (`sandbox_placement_operation_timeout`), a lost "
                "answer, or any exception that is not a refusal"
            ),
            "Something may be held",
        ),
        _LadderRow(
            "admitting", "budget_spent", "releasing",
            "budget spent",
            "The request is abandoned in flight; something may be held",
        ),
        _LadderRow(
            "waiting", "backoff_elapsed", "admitting",
            "back-off elapsed, while the wait is not spent",
            "The admission request is sent again",
        ),
        _LadderRow(
            "waiting", "wait_spent", "left:capacity",
            (
                "wait spent (now, or already on an earlier rung, in which case at once), or "
                "budget spent"
            ),
            "The lease entry is cleared",
        ),
        _LadderRow(
            "committing", "committed", "sealing",
            "committed, digest equal, required capabilities verified",
            "",
        ),
        _LadderRow(
            "committing", "commit_failed", "releasing",
            (
                "the transfer fails or times out, a capability is not verified, or budget spent"
            ),
            "",
        ),
        _LadderRow(
            "sealing", "sealed", "execute",
            "the caller's seal step returns the request (its guard passed)",
            "Final: the attempt is **placed**",
        ),
        _LadderRow(
            "sealing", "seal_failed", "releasing",
            "the guard fails, or sealing raises",
            "",
        ),
        _LadderRow(
            "sealing", "budget_spent", "releasing",
            "budget spent before the seal step returns",
            "`execute` is not called",
        ),
        _LadderRow(
            "releasing", "release_confirmed", "left:refused",
            (
                "the kill by lease id is acknowledged and `list_owned` shows nothing for it"
            ),
            "The lease entry is cleared",
        ),
        _LadderRow(
            "releasing", "release_unconfirmed", "left:refused_unconfirmed",
            "the kill or the confirmation times out or fails",
            (
                "`sandbox_placement_release_unconfirmed` is recorded; **the lease entry is kept "
                "for the reaper; the lease stays fenced** (C6)"
            ),
        ),
    ),
    after_left=(
        _AfterLeftRow(
            "release_unconfirmed", "not_run_release_unconfirmed",
            "A previous target may still hold capacity",
            "Stops without overflow; retains the fenced lease for cleanup",
        ),
        _AfterLeftRow(
            "another_rung", "start_next",
            "Another ranked target exists and the budget is not spent",
            "Starts that rung",
        ),
        _AfterLeftRow(
            "last_local", "launching_host",
            "Otherwise, a compatibility local target remains",
            "Attempts local with fresh headroom and authoritative admission",
        ),
        _AfterLeftRow(
            "last_none", "not_run_last_code",
            "Otherwise (the last rung is `none`)",
            (
                "Ends **not run**, with the code of the last rung left, or "
                "`sandbox_placement_required_unavailable` under the knob"
            ),
        ),
    ),
)

_NEXT: Mapping[tuple[str, str], str] = {(row.state, row.event): row.next for row in LADDER_TABLE.rung}
_MAY_HOLD = frozenset({"admitting", "committing", "sealing"})

# Seams the tests replace: the walk's clock, its pause between two admission requests, and
# the driver's own connection attempt.
_monotonic = time.monotonic


def _sleep(seconds: float) -> None:
    """The lock-retry pause, a seam like ``_monotonic``: tests patch this name, never the
    process-wide ``time.sleep`` that other threads also call. It looks ``time.sleep`` up at
    call time, so a patch of ``time.sleep`` still reaches it."""
    time.sleep(seconds)


def _pause(cancelled: threading.Event, seconds: float) -> None:
    cancelled.wait(max(0.0, seconds))


def _open_connection(host: str, port: int, timeout_s: float) -> None:
    """The driver's own reachability attempt (C3): resolve the name, connect, close."""
    socket.create_connection((host, port), timeout=max(timeout_s, 0.001)).close()


def lifetime_sufficient(
    remaining_s: float, floor_s: float, *,
    settings: sandbox_policy.PlacementDriverSettings | None = None,
) -> bool:
    """The preflight's comparison, used ONCE, before the walk: is what is left of a
    credential's life at least the floor plus the WHOLE budget (the admission wait and the
    transfer allowance)? Because the walk cannot outlast the budget, a credential that
    passes here still passes :func:`lifetime_at_floor` on whichever rung seals."""
    settings = settings if settings is not None else sandbox_policy.placement_driver_settings()
    budget = settings.admit_wait_s + settings.transfer_allowance_s
    return remaining_s >= floor_s + budget


def lifetime_at_floor(remaining_s: float, floor_s: float) -> bool:
    """The guard of the sealing step, on fresh numbers: at least the floor is left."""
    return remaining_s >= floor_s


@dataclass(frozen=True)
class PlacementDecision:
    """Where a seat may run. ``trail`` is carried on every exit: one record per rung the
    walk was on, in order, with its ``rung`` name, its ``class`` and its ``code``."""

    #: ``placed`` (``execute`` has been called), ``launching_host`` or ``not_run``.
    outcome: str
    trail: tuple[Mapping[str, object], ...]
    code: str | None = None
    placement: "LegPlacement | None" = None
    #: A candidate seat that ends on the launching host never runs sealed: its local route
    #: must be a tooled one. The plan that wires the launch site honours this mark.
    tooled_route_required: bool = False
    #: Notice codes the walk raised, e.g. ``seat_placement_waiting``.
    notices: tuple[str, ...] = ()
    #: Local slot owned by the caller on launch, or retained for unconfirmed cleanup.
    local_reservation: LocalReservation | None = field(default=None, repr=False)
    pending_local_reservation: LocalReservationPending | None = field(default=None, repr=False)
    #: The reservation-only exit's binding (``outcome == "reserved"``): the admitted rung,
    #: its backend and its held lease. Nothing was committed, sealed or executed.
    reservation: "RungReservation | None" = field(default=None, repr=False)


@dataclass(frozen=True)
class RungReservation:
    """What a reservation-only walk hands to its caller when a remote rung admits."""

    root: object
    label: str
    backend: object = field(repr=False)
    lease: object = field(repr=False)
    request: PlacementRequest = field(repr=False)


class _CallCancelled(Exception):
    """The caller cancelled while a bounded call was in flight."""


# A process-wide ceiling, independent of per-walk settings and _Calls lifetimes.
_PROCESS_WORKER_LIMIT = 32
_PROCESS_WORKERS = threading.BoundedSemaphore(_PROCESS_WORKER_LIMIT)


class _WorkerCapacity(PlacementUnavailable):
    """No process-wide worker slot is available."""


def _serve(jobs: "queue.SimpleQueue[object]", permits: threading.BoundedSemaphore,
           process_permits: threading.BoundedSemaphore) -> None:
    try:
        while True:
            job = jobs.get()
            if job is None:
                return
            call, context, box, done = job  # type: ignore[misc]
            try:
                box.append((True, context.run(call)))
            except BaseException as exc:  # handed to the caller, which re-raises it
                box.append((False, exc))
            done.release()
            del job, call, context, box, done
    finally:
        permits.release()
        process_permits.release()


class _Calls:
    """Runs a call so that it can outlast neither its bound nor a cancel (C4).

    One worker thread serves the calls of one walk in turn. A call that does not return in
    time is abandoned together with its queue. All live workers (idle, active and
    abandoned) hold permits until actual exit. The settings cap is per group: the walk,
    result wait and renewal each own a group. A shared process-wide quota also
    bounds workers across groups, including abandoned local cleanup calls."""

    def __init__(self, *, settings: sandbox_policy.PlacementDriverSettings | None = None) -> None:
        settings = settings if settings is not None else sandbox_policy.placement_driver_settings(env={})
        self._permits = threading.BoundedSemaphore(settings.max_live_workers)
        self._jobs: "queue.SimpleQueue[object] | None" = None

    def ready(self) -> None:
        if self._jobs is not None:
            return
        group_acquired = process_acquired = start_called = False
        process_permits = _PROCESS_WORKERS
        jobs: queue.SimpleQueue[object] | None = None
        try:
            if not self._permits.acquire(blocking=False):
                raise PlacementUnavailable(_TIMEOUT)
            group_acquired = True
            if not process_permits.acquire(blocking=False):
                raise _WorkerCapacity(_LOCAL_RELEASE_UNCONFIRMED)
            process_acquired = True
            jobs = queue.SimpleQueue()
            worker = threading.Thread(
                target=_serve, args=(jobs, self._permits, process_permits), name="placement-call", daemon=True,
            )
            # Any exception from start can follow OS thread creation. Once
            # called, only the worker may return these permits.
            start_called = True
            worker.start()
            self._jobs = jobs
        except BaseException as exc:
            if start_called:
                # The worker (or CPython's limbo entry) owns this queue. Queue
                # shutdown and detach so a retry never reuses uncertain startup.
                jobs.put(None)
                self._jobs = None
            else:
                self._jobs = None
                if process_acquired:
                    process_permits.release()
                if group_acquired:
                    self._permits.release()
            if isinstance(exc, PlacementUnavailable):
                raise
            if isinstance(exc, Exception):
                raise PlacementUnavailable(_TIMEOUT) from None
            raise

    def run(
        self, call: Callable[[], object], timeout_s: float,
        cancelled: threading.Event | None = None,
    ) -> object:
        if cancelled is not None and cancelled.is_set():
            raise _CallCancelled()
        self.ready()
        box: list[tuple[bool, object]] = []
        done = threading.Lock()  # released by the worker when the call has returned
        done.acquire()
        self._jobs.put((call, contextvars.copy_context(), box, done))
        deadline = time.monotonic() + max(0.0, timeout_s)
        while not done.acquire(timeout=min(_POLL_S, max(0.0, deadline - time.monotonic()))):
            if cancelled is not None and cancelled.is_set():
                self.close()
                raise _CallCancelled()
            if time.monotonic() >= deadline:
                self.close()
                raise PlacementUnavailable(_TIMEOUT)
        ok, value = box[0]
        if ok:
            return value
        raise value  # type: ignore[misc]

    def close(self) -> None:
        jobs, self._jobs = self._jobs, None
        if jobs is not None:
            jobs.put(None)


def _bound(timeout_s: float, cancelled: threading.Event | None = None) -> OperationBound:
    return OperationBound(max(0.0, timeout_s), cancelled if cancelled is not None else threading.Event())


def _root_text(root: object) -> str:
    """A root as recorded: rebuilt from its parsed parts, never from the configured text."""
    host = getattr(root, "host", None) or ""
    return f"{getattr(root, 'scheme', '')}://{host}{Path(getattr(root, 'path', '/')).as_posix()}"


def _checked_endpoint(endpoint: object) -> tuple[str, int] | None:
    if endpoint is None:
        return None
    host, port = endpoint  # type: ignore[misc]
    if (
        not isinstance(host, str) or not host or any(ch.isspace() for ch in host)
        or isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536
    ):
        raise ValueError("a backend endpoint is a host and a port")
    return host, port


def _release(calls: _Calls, backend: object, lease: object) -> bool:
    """Release what a rung may hold: kill by lease id, then absent from ``list_owned``.

    True only when the kill was acknowledged AND nothing is listed for the lease. It has
    its own bound, outside the walk's budget, and a cancel does not interrupt it, so that
    leaving a rung is always possible. The caller has already fenced the lease."""
    lease_id, owner_id = lease.lease_id, lease.owner_id  # type: ignore[attr-defined]
    try:
        calls.run(lambda: backend.kill(lease_id, _bound(ANSWER_BOUND_S)), ANSWER_BOUND_S)  # type: ignore[attr-defined]
        lease.note_killed()  # type: ignore[attr-defined]
        owned = calls.run(
            # Read to the end inside the bound: a listing may arrive in pages.
            lambda: [tuple(pair) for pair in backend.list_owned(owner_id, _bound(ANSWER_BOUND_S))],  # type: ignore[attr-defined]
            ANSWER_BOUND_S,
        )
        return all(pair[1] != lease_id for pair in owned)  # type: ignore[union-attr]
    except Exception:
        return False


@dataclass
class _Rung:
    root: object
    label: str
    backend: object = None
    request: PlacementRequest | None = None
    endpoint: tuple[str, int] | None = None
    #: What the backend declared it can enforce, read once by the local checks.
    capabilities: frozenset[str] = frozenset()
    lease: object = None
    live_adapter: object = None
    placement: "LegPlacement | None" = None
    spec: ExecSpec | None = None
    #: The code that sent the rung to "releasing".
    reason: str | None = None
    cancel: bool = False
    uncertain_admission: bool = False
    reserve_unreachable: bool = False
    admission_reason: str | None = None


@dataclass(frozen=True)
class LocalHeadroom:
    """Local inventory snapshot; missing or stale dimensions fail closed.

    CPU-relative load is 100 * one-minute load / online CPU count. The live
    count includes all local sandboxes, not just this process's reservations.
    """

    memory_available_bytes: int | None
    load_per_cpu_percent: float | None
    live_sandboxes: int | None
    observed_monotonic: float
    #: Read only against the placement protocol's thresholds (v13 PLACECLI).
    memory_total_bytes: int | None = None
    io_full_avg10: float | None = None
    memory_some_avg10: float | None = None

    def admits(self, settings: "sandbox_policy.PlacementDriverSettings | object") -> bool:
        """Against the driver settings, or against a host's effective
        ``LocalHeadroomConfig`` when one is given."""
        if hasattr(settings, "memory_available_bytes_minimum_floor"):
            return self._admits_thresholds(settings)
        try:
            age = _monotonic() - self.observed_monotonic
            return (
                math.isfinite(age) and 0 <= age <= settings.capacity_max_age_s
                and type(self.memory_available_bytes) is int
                and self.memory_available_bytes >= settings.local_min_memory_bytes
                and type(self.live_sandboxes) is int
                and 0 <= self.live_sandboxes < settings.local_max_live_sandboxes
                and type(self.load_per_cpu_percent) in (int, float)
                and math.isfinite(self.load_per_cpu_percent)
                and 0 <= self.load_per_cpu_percent < settings.local_max_load_per_cpu_percent
            )
        except (TypeError, ValueError, OverflowError):
            return False

    def _admits_thresholds(self, limits: object) -> bool:
        """One observation, no older than the maximum age, satisfies every threshold; any
        unknown or stale dimension is at capacity (``x-placement-semantics``)."""
        def number(value: object) -> bool:
            return type(value) in (int, float) and math.isfinite(value)  # type: ignore[arg-type]

        try:
            age = _monotonic() - self.observed_monotonic
            floor = max(int(limits.memory_available_bytes_minimum_floor),  # type: ignore[attr-defined]
                        math.ceil(self.memory_total_bytes  # type: ignore[operator]
                                  * limits.memory_available_total_ram_fraction_minimum))  # type: ignore[attr-defined]
            return (
                math.isfinite(age) and 0 <= age <= limits.observation_age_seconds_maximum  # type: ignore[attr-defined]
                and type(self.memory_available_bytes) is int
                and type(self.memory_total_bytes) is int and self.memory_total_bytes > 0
                and self.memory_available_bytes >= floor
                and number(self.load_per_cpu_percent) and self.load_per_cpu_percent >= 0  # type: ignore[operator]
                and self.load_per_cpu_percent < limits.load_per_cpu_percent_maximum_exclusive  # type: ignore[attr-defined, operator]
                and number(self.io_full_avg10) and self.io_full_avg10 >= 0  # type: ignore[operator]
                and self.io_full_avg10 < limits.io_pressure_full_avg10_percent_maximum_exclusive  # type: ignore[attr-defined, operator]
                and number(self.memory_some_avg10) and self.memory_some_avg10 >= 0  # type: ignore[operator]
                and self.memory_some_avg10 < limits.memory_pressure_some_avg10_percent_maximum_exclusive  # type: ignore[attr-defined, operator]
                and type(self.live_sandboxes) is int and self.live_sandboxes >= 0
                and self.live_sandboxes < limits.live_sandboxes_maximum_exclusive  # type: ignore[attr-defined]
            )
        except (TypeError, ValueError, OverflowError, AttributeError):
            return False


@dataclass(frozen=True)
class LocalReservation:
    """Opaque adapter-issued handle for a reserved local slot, never telemetry."""

    token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.token, str) or not _SANDBOX_REF.fullmatch(self.token):
            raise ValueError("invalid local reservation")


class LocalReservationPending:
    """Thread-safe ownership record for an admission that outlives its caller.

    ``inspect`` returns (state, handle); ``wait(timeout_s)`` waits at most the
    supplied bound. Pending transitions exactly once to released, retained or
    none_returned. A retained handle remains available for reconciliation even
    if the abandoned release worker subsequently finishes.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._state = "pending"
        self._handle: LocalReservation | None = None

    def inspect(self) -> tuple[str, LocalReservation | None]:
        with self._condition:
            return self._state, self._handle

    def wait(self, timeout_s: float) -> tuple[str, LocalReservation | None]:
        if not math.isfinite(timeout_s) or timeout_s < 0:
            raise ValueError("wait requires a finite nonnegative bound")
        with self._condition:
            self._condition.wait_for(lambda: self._state != "pending", timeout_s)
            return self._state, self._handle

    def _finish(self, state: str, handle: LocalReservation | None = None) -> None:
        with self._condition:
            if self._state != "pending":
                raise RuntimeError("local reservation already resolved")
            self._state, self._handle = state, handle
            self._condition.notify_all()


@dataclass(frozen=True)
class LocalAdmission:
    """An authoritative local reservation and its pre-reservation headroom.

    Returning no valid handle is a definitive refusal with nothing held. Adapters
    must never discard a held slot by returning a missing or invalid handle.
    """

    handle: LocalReservation | None
    reading: LocalHeadroom | None


def _local_handle(result: object) -> LocalReservation | None:
    if isinstance(result, LocalAdmission) and isinstance(result.handle, LocalReservation):
        return result.handle
    return None


class _Walk:
    """One attempt to place one seat. The transitions are :data:`LADDER_TABLE`'s; each
    ``_<state>`` method does that state's work and names the event that happened."""

    def __init__(
        self, prepared: Prepared, request_for: Callable[[object], PlacementRequest],
        open_lease: Callable[[str | None, object], object],
        seal: Callable[[PlacementRequest], "ExecSpec | None"],
        driver_enabled: bool, cancelled: threading.Event,
        settings: sandbox_policy.PlacementDriverSettings,
        local_capacity: Callable[[], LocalHeadroom | None] | None = None,
        local_admit: Callable[[sandbox_policy.PlacementDriverSettings, OperationBound], LocalAdmission] | None = None,
        local_release: Callable[[LocalReservation], None] | None = None,
        *, reserve_only: bool = False, headroom: object = None, budget_s: float | None = None,
        local_preflight: Callable[[str], str | None] | None = None,
        honour_remote_required: bool = True, probe_timeout_s: float | None = None,
        backend_for: Callable[[object], object] | None = None,
    ) -> None:
        self.reserve_only = bool(reserve_only)
        self.headroom = headroom
        self.local_preflight = local_preflight
        self.honour_remote_required = bool(honour_remote_required)
        self.probe_timeout_s = probe_timeout_s
        self.backend_for = backend_for
        self.prepared = prepared
        self.request_for = request_for
        self.open_lease = open_lease
        self.seal = seal
        self.driver_enabled = driver_enabled
        self.cancelled = cancelled
        self.settings = settings
        self.local_capacity = local_capacity
        self.local_admit = local_admit
        self.local_release = local_release
        self.calls = _Calls(settings=settings)
        self.trail: list[Mapping[str, object]] = []
        self.notices: list[str] = []
        self.admit_wait_s = float(settings.admit_wait_s)
        self.budget_s = self.admit_wait_s + float(settings.transfer_allowance_s)
        if budget_s is not None:
            # A caller's own bound (the reserve request's deadline) only ever shortens it.
            self.budget_s = max(0.0, min(self.budget_s, float(budget_s)))
            self.admit_wait_s = min(self.admit_wait_s, self.budget_s)
        self.waited_s = 0.0
        self.started = _monotonic()

    def _remote_required(self) -> bool:
        return self.honour_remote_required and sandbox_policy.remote_required()

    def _admits(self, reading: object) -> bool:
        return isinstance(reading, LocalHeadroom) and reading.admits(
            self.headroom if self.headroom is not None else self.settings)

    # -- the budget ---------------------------------------------------------------------
    def _budget_left(self) -> float:
        return self.budget_s - (_monotonic() - self.started)

    def _budget_spent(self) -> bool:
        return self._budget_left() <= 0

    def _wait_spent(self) -> bool:
        return self.waited_s >= self.admit_wait_s

    # -- the walk -----------------------------------------------------------------------
    def run(self, rungs: Sequence[object], last_rung: str) -> PlacementDecision:
        for index, root in enumerate(rungs):
            if getattr(root, "scheme", "") == "local":
                placed = self._local(getattr(root, "name", None) or "local")
            else:
                placed = self._rung(root)
            if placed is not None:
                return placed
            if self._after_left(index + 1 < len(rungs), last_rung) != "start_next":
                break
        return self._end(self._after_left(False, last_rung))

    def _local_left(self, label: str, code: str,
                    handle: LocalReservation | None = None,
                    pending: LocalReservationPending | None = None) -> PlacementDecision | None:
        self.trail.append({"rung": label, "class": "capacity" if code == _CAPACITY else "refused",
                           "code": code})
        if code == _LOCAL_RELEASE_UNCONFIRMED:
            return PlacementDecision("not_run", tuple(self.trail), code, notices=tuple(self.notices),
                                     local_reservation=handle, pending_local_reservation=pending)
        return None

    def _local_cancel(self, label: str, *, released: bool | None = None,
                      uncertain: bool = False, handle: LocalReservation | None = None,
                      pending: LocalReservationPending | None = None) -> None:
        self.trail.append({"rung": label, "class": "cancelled",
                           "code": _LOCAL_RELEASE_UNCONFIRMED if uncertain else None,
                           "release_needed": released is not None or uncertain,
                           "release_confirmed": released})
        raise PlacementCancelled(self.trail, local_reservation=handle if uncertain else None,
                                 pending_local_reservation=pending if uncertain else None)

    def _release_local(self, handle: LocalReservation) -> bool:
        # Cleanup has its own bound, outside the exhausted admission budget, and
        # cannot be short-circuited by the caller's cancellation.
        cleanup = _Calls(settings=self.settings)
        try:
            cleanup.run(lambda: self.local_release(handle), ANSWER_BOUND_S)
            return True
        except Exception:
            return False
        finally:
            cleanup.close()

    def _local(self, label: str) -> PlacementDecision | None:
        if self.cancelled.is_set():
            self._local_cancel(label)
        if self._remote_required():
            return self._local_left(label, _REQUIRED_UNAVAILABLE)
        if self._budget_spent():
            return self._local_left(label, _BUDGET_SPENT)
        if any(hook is None for hook in (self.local_capacity, self.local_admit, self.local_release)):
            return self._local_left(label, _REFUSED)
        if self.local_preflight is not None:
            # The lifecycle's checks for this target, before any capacity probe.
            refusal = self.local_preflight(label)
            if refusal is not None:
                return self._local_left(label, refusal)
        try:
            reading = self.calls.run(self.local_capacity,
                                     min(ANSWER_BOUND_S, self._budget_left()), self.cancelled)
        except _CallCancelled:
            self._local_cancel(label)
        except Exception:
            # An advisory failure is unknown telemetry, never a held reservation.
            reading = None
        if self.cancelled.is_set():
            self._local_cancel(label)
        if self._budget_spent():
            return self._local_left(label, _BUDGET_SPENT)
        if not self._admits(reading):
            return self._local_left(label, _CAPACITY)

        # Keep the adapter's cancellation separate from the caller's event:
        # an admission timeout must cancel the operation, not cancel the caller.
        allowance = min(ANSWER_BOUND_S, self._budget_left())
        if allowance <= 0:
            return self._local_left(label, _BUDGET_SPENT)
        bound = _bound(allowance)
        handoff = threading.Lock()
        results: list[object] = []
        abandoned = False
        pending = LocalReservationPending()

        def reserve() -> object:
            try:
                result = self.local_admit(self.settings, bound)
            except BaseException:
                pending._finish("none_returned")
                raise
            with handoff:
                if not abandoned:
                    results.append(result)
                    return result
            # The bounded caller has already stopped. A late returned handle is
            # still owned here, so release it rather than losing it in _Calls.
            handle = _local_handle(result)
            if handle is not None:
                released = self._release_local(handle)
                pending._finish("released" if released else "retained",
                                None if released else handle)
            else:
                pending._finish("none_returned")
            return result

        try:
            result = self.calls.run(reserve, bound.timeout_s, self.cancelled)
        except Exception as exc:
            bound.cancelled.set()
            with handoff:
                abandoned = True
                completed = bool(results)
                result = results.pop() if completed else None
            handle = _local_handle(result)
            released = self._release_local(handle) if handle is not None else None
            if completed:
                pending._finish("none_returned" if handle is None else
                                "released" if released else "retained",
                                handle if released is False else None)
            safe_refusal = (isinstance(exc, PlacementUnavailable)
                            and exc.code in {_CAPACITY, _REFUSED} and handle is None)
            uncertain = not safe_refusal
            if self.cancelled.is_set() or isinstance(exc, _CallCancelled):
                self._local_cancel(label, released=released,
                                   uncertain=uncertain and released is not True, handle=handle,
                                   pending=pending)
            code = _LOCAL_RELEASE_UNCONFIRMED if uncertain else (
                exc.code if safe_refusal else _REFUSED)
            return self._local_left(label, code, handle if released is not True else None, pending)

        handle = _local_handle(result)
        if handle is None:
            # Contract: no valid handle means refused, with nothing held.
            if self.cancelled.is_set():
                bound.cancelled.set()
                self._local_cancel(label)
            return self._local_left(label, _REFUSED)
        transferred = False
        try:
            fresh = self._admits(result.reading)
            if self.cancelled.is_set():
                code = _CANCELLED
            elif self._budget_spent():
                code = _BUDGET_SPENT
            elif self._remote_required():
                code = _REQUIRED_UNAVAILABLE
            elif not fresh:
                code = _CAPACITY
            else:
                row = {"rung": label, "class": "admitted", "code": None}
                decision = PlacementDecision("launching_host", (*self.trail, row), None,
                                             tooled_route_required=True, notices=tuple(self.notices),
                                             local_reservation=handle)
                self.trail.append(row)
                transferred = True
                return decision
        except Exception:
            code = _REFUSED
        finally:
            if not transferred:
                bound.cancelled.set()
                released = self._release_local(handle)
        if self.cancelled.is_set():
            self._local_cancel(label, released=released, uncertain=not released, handle=handle)
        return self._local_left(label, code if released else _LOCAL_RELEASE_UNCONFIRMED,
                                handle if not released else None)

    def _after_left(self, another: bool, last_rung: str) -> str:
        facts = {
            "release_unconfirmed": any(entry.get("release") == _RELEASE_UNCONFIRMED
                                       for entry in self.trail),
            "another_rung": another and not self._budget_spent(),
            "last_local": last_rung == "local",
            "last_none": last_rung == "none",
        }
        return next(row.walk for row in LADDER_TABLE.after_left if facts[row.condition])

    def _end(self, walk: str, code: str | None = None) -> PlacementDecision:
        trail, notices = tuple(self.trail), tuple(self.notices)
        if walk == "not_run_release_unconfirmed":
            return PlacementDecision("not_run", trail, _RELEASE_UNCONFIRMED, notices=notices)
        if walk == "launching_host":
            local = self._local("local")
            if local is not None:
                return replace(local, code=code) if code is not None and local.outcome == "launching_host" else local
            trail = tuple(self.trail)
        if code is None and trail:
            code = trail[-1]["code"]  # type: ignore[assignment]
        if code is None or self._remote_required():
            code = _REQUIRED_UNAVAILABLE
        return PlacementDecision("not_run", trail, code, notices=notices)

    def _record(self, rung: _Rung, klass: str, code: str | None, **extra: object) -> None:
        self.trail.append({"rung": rung.label, "class": klass, "code": code, **extra})

    def _cancelled(self, rung: _Rung, *, release: bool | None) -> PlacementCancelled:
        self._record(
            rung, "cancelled", None,
            release_needed=release is not None, release_confirmed=release,
        )
        return PlacementCancelled(self.trail)

    def _rung(self, root: object) -> PlacementDecision | None:
        """Walk one rung to the end. ``None`` when it was left; a decision when the seat
        was placed on it; raises when the attempt was cancelled."""
        rung = _Rung(root, getattr(root, "name", None) or _root_text(root))
        state = "start"
        while True:
            if state == "releasing":
                event, code = self._releasing(rung)
            elif self.cancelled.is_set():
                event, code = None, None
            else:
                event, code = getattr(self, "_" + state)(rung)
            if state != "releasing" and (event is None or self.cancelled.is_set()):
                # A cancel is accepted in every state and never moves the walk on.
                if state in _MAY_HOLD:
                    rung.cancel = True
                    rung.lease.fence()  # type: ignore[attr-defined]
                    state = "releasing"
                    continue
                if rung.lease is not None:
                    rung.lease.clear()  # type: ignore[attr-defined]
                raise self._cancelled(rung, release=None)
            target = _NEXT[(state, event)]  # type: ignore[index]
            if state == "releasing":
                kept = target == "left:refused_unconfirmed"
                if kept:
                    # Abandoned: the entry stays for the reaper and the lock is given up.
                    rung.lease.abandon()  # type: ignore[attr-defined]
                else:
                    rung.lease.clear()  # type: ignore[attr-defined]
                if rung.cancel or self.cancelled.is_set():
                    raise self._cancelled(rung, release=not kept)
                extra = {"release": _RELEASE_UNCONFIRMED} if kept else {}
                self._record(rung, target[5:], rung.reason, **extra)
                if rung.uncertain_admission:
                    # OSCOORD2 revision 7: cleanup never authorizes replay elsewhere.
                    return self._end('not_run_release_unconfirmed' if kept else 'not_run_last_code',
                                     rung.reason)
                return None
            if target == "committing" and self.reserve_only:
                # The reservation-only exit (v13 PLACECLI): stop after admission, before
                # `commit`, `seal` and `execute`. The lease stays held; the caller owns it.
                row = {"rung": rung.label, "class": "admitted", "code": None}
                self.trail.append(row)
                return PlacementDecision(
                    "reserved", tuple(self.trail), notices=tuple(self.notices),
                    reservation=RungReservation(rung.root, rung.label, rung.backend, rung.lease,
                                                rung.request),  # type: ignore[arg-type]
                )
            if target == "releasing":
                # Entering "releasing" always fences the lease first.
                rung.reason = code
                rung.lease.fence()  # type: ignore[attr-defined]
            elif target == "execute":
                if self.cancelled.is_set() or self._budget_spent():
                    rung.cancel = self.cancelled.is_set()
                    rung.reason = _BUDGET_SPENT
                    rung.lease.fence()  # type: ignore[attr-defined]
                    state = "releasing"
                    continue
                return self._execute(rung)
            elif target.startswith("left:"):
                if rung.lease is not None:
                    rung.lease.clear()  # type: ignore[attr-defined]
                if rung.reserve_unreachable:
                    self._record(rung, 'unreachable', code, reason=rung.admission_reason)
                else:
                    self._record(rung, target[5:], code)
                return None
            state = target

    # -- the states ---------------------------------------------------------------------
    def _start(self, rung: _Rung) -> tuple[str | None, str | None]:
        failed = "local_check_failed"
        try:
            request = self.request_for(rung.root)
        except PlacementUnavailable as exc:
            if self.reserve_only:
                from .placement_process_contract import placement_codes

                if exc.code in placement_codes():
                    # The lifecycle's refusal of this target, recorded before any probe.
                    return failed, exc.code
            return failed, _REFUSED
        except Exception:
            return failed, _REFUSED
        if not isinstance(request, PlacementRequest):
            return failed, _REFUSED
        # The root travels with the request; a placed seat has no private endpoint (C5, C6).
        request = replace(request, root=rung.root, egress_needs=EgressNeeds())  # type: ignore[arg-type]
        if request.workload != "qualification" and not self.driver_enabled:
            # The execution gate (C10), before the backend is looked up or called.
            return failed, _DRIVER_UNAVAILABLE
        try:
            backend = (self.backend_for(rung.root) if self.backend_for is not None
                       else backend_for_scheme(getattr(rung.root, "scheme", "")))
        except PlacementUnavailable:
            return failed, "sandbox_placement_plugin_unavailable"
        if backend is None or is_local(backend):
            # Anything else in the registry passed the protocol check when it registered.
            return failed, "sandbox_placement_backend_unregistered"
        try:
            if not backend.available(request):
                return failed, _REFUSED
            if self.cancelled.is_set():
                return None, None
            endpoint = _checked_endpoint(backend.endpoint(rung.root))  # type: ignore[arg-type]
            if self.cancelled.is_set():
                return None, None
            declared = frozenset(backend.capabilities())
            if not request.required_capabilities <= declared:
                return failed, _CAPABILITY_UNMET
            if self.cancelled.is_set():
                return None, None
            limit = backend.declaration().max_lifetime_s
            if request.deadline_s is not None and limit is not None and request.deadline_s > limit:
                return failed, _REFUSED
        except Exception:
            return failed, _REFUSED
        try:
            self.calls.ready()
        except PlacementUnavailable:
            if self.cancelled.is_set():
                return None, None
            return failed, _REFUSED
        rung.backend, rung.request, rung.endpoint = backend, request, endpoint
        rung.capabilities = declared
        return "local_checks_passed", None

    def _connecting(self, rung: _Rung) -> tuple[str | None, str | None]:
        if self._budget_spent():
            return "budget_spent", _BUDGET_SPENT
        if rung.endpoint is not None:
            # Reachability is the driver's (C3): a backend with no endpoint is never
            # "unreachable", and nothing but this attempt is.
            host, port = rung.endpoint
            probe = (self.probe_timeout_s if self.probe_timeout_s is not None
                     else sandbox_policy.probe_timeout_s())
            timeout = min(probe, self._budget_left())
            reached = True
            try:
                self.calls.run(
                    lambda: _open_connection(host, port, timeout), timeout, self.cancelled,
                )
            except _CallCancelled:
                return None, None
            except Exception:
                reached = False
            if self._budget_spent():
                # The budget wins a tie: running out of time is not evidence that the host
                # is unreachable.
                return "budget_spent", _BUDGET_SPENT
            if not reached:
                return "connect_failed", _UNREACHABLE
        if self.cancelled.is_set():
            return None, None
        try:
            # Allocated and fsynced BEFORE `admit`, the first call with a remote effect.
            lease = self.open_lease(getattr(rung.root, "name", None), rung.root)
        except Exception:
            return "lease_unwritable", _REFUSED
        rung.lease = lease
        rung.request = replace(
            rung.request, owner_id=lease.owner_id, lease_id=lease.lease_id,  # type: ignore[type-var, attr-defined]
        )
        return "connected", None

    def _admitting(self, rung: _Rung) -> tuple[str | None, str | None]:
        from .placement_lease import LiveLeaseBackend

        if self._budget_spent():
            return "budget_spent", _BUDGET_SPENT
        bound = _bound(min(ANSWER_BOUND_S, self._budget_left()), self.cancelled)
        backend, request = rung.backend, rung.request
        try:
            if isinstance(backend, LiveLeaseBackend) and rung.live_adapter is None:
                adapter = backend.bind_live_lease(rung.lease)
                rung.lease.validate_live_binding(adapter)
                rung.live_adapter = adapter
            self.calls.run(lambda: backend.admit(request, bound), bound.timeout_s, self.cancelled)  # type: ignore[attr-defined]
        except _CallCancelled:
            return None, None
        except PlacementUnavailable as exc:
            if (exc.uncertain is True or exc.uncertain is not False
                    and getattr(rung.lease, 'reserve_attempted', False)):
                rung.uncertain_admission = True
                return "no_answer", _TIMEOUT
            if exc.code == _UNREACHABLE and exc.uncertain is False:
                # Only explicit nothing-sent evidence bypasses the registered-code
                # check, for this one closed code, at admission only.
                rung.reserve_unreachable = True
                if exc.reason in ('recovering', 'telemetry_stale', 'slice_unbounded',
                                  'untracked_vms', 'ledger_restored', 'internal'):
                    rung.admission_reason = exc.reason
                return "refused", _UNREACHABLE
            if exc.code == _CAPACITY:
                self._at_capacity(rung)
                return "at_capacity", _CAPACITY
            if exc.code == _TIMEOUT:
                # No answer. Something may be held.
                if self._budget_spent():
                    return "budget_spent", _BUDGET_SPENT
                return "no_answer", _TIMEOUT
            return "refused", self._refusal_code(rung, exc.code, _BACKEND_REFUSALS)
        except Exception:
            if getattr(rung.lease, 'reserve_attempted', False):
                rung.uncertain_admission = True
            return "no_answer", _REFUSED
        return "admitted", None

    def _at_capacity(self, rung: _Rung) -> None:
        if _WAITING_NOTICE not in self.notices:
            self.notices.append(_WAITING_NOTICE)
            logging.getLogger(__name__).warning(
                "seat placement [%s]: %s is at capacity; waiting up to %d s in all for a "
                "slot before trying the next ranked target", _WAITING_NOTICE, rung.label,
                int(self.admit_wait_s),
            )

    def _refusal_code(self, rung: _Rung, code: object, runtime_codes: frozenset[str]) -> str:
        """A backend's refusal as recorded: one of the runtime's refusal codes, or one this
        backend registered. Anything else is ``sandbox_placement_code_invalid``, and the
        text it carried reaches no record and no log."""
        own = _BACKEND_CODES.get(str(getattr(rung.root, "scheme", "")).lower(), {})
        if type(code) is str and (code in runtime_codes or code in own):
            return code
        return _CODE_INVALID

    def _waiting(self, rung: _Rung) -> tuple[str | None, str | None]:
        if self._budget_spent() or self._wait_spent():
            return "wait_spent", _CAPACITY
        before = _monotonic()
        _pause(self.cancelled, min(
            _ADMIT_BACKOFF_S, self.admit_wait_s - self.waited_s, self._budget_left(),
        ))
        self.waited_s += max(0.0, _monotonic() - before)
        if self.cancelled.is_set():
            return None, None
        if self._budget_spent() or self._wait_spent():
            return "wait_spent", _CAPACITY
        return "backoff_elapsed", None

    def _committing(self, rung: _Rung) -> tuple[str | None, str | None]:
        failed = "commit_failed"
        if self._budget_spent():
            return failed, _BUDGET_SPENT
        bound = _bound(self._budget_left(), self.cancelled)
        backend, request, prepared = rung.backend, rung.request, self.prepared
        try:
            result = self.calls.run(
                lambda: backend.commit(prepared, request, bound),  # type: ignore[attr-defined]
                bound.timeout_s, self.cancelled,
            )
        except _CallCancelled:
            return None, None
        except PlacementUnavailable as exc:
            if exc.code == _TIMEOUT:
                return failed, _BUDGET_SPENT if self._budget_spent() else _TIMEOUT
            if exc.code == _CAPACITY:
                # A failed transfer releases before another ranked target is tried.
                return failed, _CAPACITY
            return failed, self._refusal_code(rung, exc.code, _COMMIT_REFUSALS)
        except Exception:
            return failed, _REFUSED
        try:
            sandbox_ref, receipts, verified = _commit_claims(rung.capabilities, result, prepared)
            if rung.live_adapter is not None:
                if self.cancelled.is_set():
                    rung.lease.fence()
                    return None, None
                rung.lease.confirm_commit_ref(rung.live_adapter, sandbox_ref)
            else:
                rung.lease.record_sandbox_ref(sandbox_ref)  # type: ignore[attr-defined]
        except PlacementUnavailable as exc:
            return failed, exc.code
        except Exception:
            return failed, _REFUSED
        if not request.required_capabilities <= frozenset(verified):  # type: ignore[union-attr]
            return failed, _CAPABILITY_UNMET
        placement = LegPlacement(
            backend, prepared, scheme=str(getattr(rung.root, "scheme", "")),  # type: ignore[arg-type]
            authorization_sha256=None,
        )
        placement.sandbox_ref = sandbox_ref
        placement.workload = request.workload  # type: ignore[union-attr]
        placement.receipts.extend(receipts)
        placement.verified.update(verified)
        placement._lease = rung.lease
        placement._driver_settings = self.settings
        placement._observed.add("committed")
        placement.record_runtime("committed")
        rung.placement = placement
        return "committed", None

    def _sealing(self, rung: _Rung) -> tuple[str | None, str | None]:
        if self._budget_spent():
            return "budget_spent", _BUDGET_SPENT
        request = rung.request
        try:
            spec = self.calls.run(
                lambda: self.seal(request), self._budget_left(), self.cancelled,
            )
        except _CallCancelled:
            return None, None
        except PlacementUnavailable as exc:
            if exc.code == _TIMEOUT and self._budget_spent():
                return "budget_spent", _BUDGET_SPENT
            return "seal_failed", _REFUSED
        except Exception:
            return "seal_failed", _REFUSED
        if (
            not isinstance(spec, ExecSpec) or spec.workload != request.workload  # type: ignore[union-attr]
            or not _end_is_fixed(spec)
            or type(spec.output_cap_bytes) is not int or spec.output_cap_bytes < 0
        ):
            return "seal_failed", _REFUSED
        if self._budget_spent():
            # Before the seal step returned: `execute` is not called, even if the guard passed.
            return "budget_spent", _BUDGET_SPENT
        rung.spec = spec
        return "sealed", None

    def _releasing(self, rung: _Rung) -> tuple[str, str | None]:
        confirmed = _release(self.calls, rung.backend, rung.lease)
        return ("release_confirmed" if confirmed else "release_unconfirmed"), rung.reason

    def _execute(self, rung: _Rung) -> PlacementDecision:
        """`execute` is reached from one state and ends the walk: the attempt is placed,
        whatever the call then does, and nothing here ever tries another rung."""
        placement, spec, lease = rung.placement, rung.spec, rung.lease
        assert placement is not None and spec is not None
        _send_execute(
            self.calls, placement, spec, lease, min(ANSWER_BOUND_S, self._budget_left()),
            self.cancelled,
        )
        self._record(rung, "placed", None)
        placement._trail = tuple(self.trail)
        return PlacementDecision(
            "placed", tuple(self.trail), placement=placement, notices=tuple(self.notices),
        )


def _end_is_fixed(spec: ExecSpec) -> bool:
    """A workload with a deadline has an end, and the end is not after the deadline (C2)."""
    if spec.deadline_s is None:
        return True
    return spec.must_end_within_s is not None and spec.must_end_within_s <= spec.deadline_s


def _commit_claims(
    capabilities: frozenset[str], result: object, prepared: Prepared,
) -> tuple[str, list[PlacementReceipt], dict[str, str]]:
    """What ``commit`` returned, checked: the reference, the backend's receipts, and its
    verification claims (never wider than its capabilities, never ``runtime_end_to_end``).
    The transfer counts only when the backend's digest equals the runtime's."""
    if isinstance(result, PlacedSandbox):
        sandbox_ref = _check_ref(result.sandbox_ref)
        receipts = [
            receipt for receipt in result.receipts
            if isinstance(receipt, PlacementReceipt) and receipt.attested_by == "backend"
        ]
        verified = _verified(capabilities, result.verified)
    elif isinstance(result, BackendReceipt):
        sandbox_ref = result.sandbox_ref
        receipts, verified = [PlacementReceipt.from_backend(result)], {}
    else:
        raise PlacementUnavailable(_REFUSED)
    committed = [r for r in receipts if r.step == "committed"]
    if not committed or any(
        r.sandbox_ref != sandbox_ref or r.snapshot_sha256 != prepared.snapshot_sha256
        for r in receipts
    ):
        raise PlacementUnavailable(_REFUSED)
    return sandbox_ref, receipts, verified


def _send_execute(
    calls: _Calls, placement: "LegPlacement", spec: ExecSpec, lease: object,
    timeout_s: float = ANSWER_BOUND_S, cancelled: threading.Event | None = None,
) -> None:
    """The one place `execute` is sent from. Never for a fenced lease (C6).

    The caller's cancel reaches the backend through `execute`'s bound (C4). The driver
    itself still waits for the answer within the bound: launch is final."""
    if getattr(lease, "fenced", True):
        raise RuntimeError("execute is never sent for a fenced lease")
    backend, sandbox_ref = placement.backend, placement.sandbox_ref
    placement._spec = spec
    # The end is counted from here and nothing moves it (C2).
    placement._launched_at = _monotonic()
    placement._observed.add("launched")
    placement.record_runtime("launched")
    try:
        receipt = calls.run(
            lambda: backend.execute(sandbox_ref, spec, _bound(timeout_s, cancelled)),  # type: ignore[attr-defined]
            timeout_s,
        )
        if (
            isinstance(receipt, BackendReceipt) and receipt.step == "launched"
            and receipt.sandbox_ref == sandbox_ref
            and receipt.snapshot_sha256 == placement.prepared.snapshot_sha256
        ):
            # Anything else is dropped: a backend's receipt is recorded only when it names
            # this sandbox and the runtime's own digest.
            placement.record_backend_receipt(receipt)
    except Exception:
        # Launch is final: even if `execute` raised, the attempt is launched.
        placement._launch_failed = True


def place(
    rungs: Sequence["sandbox_policy.SandboxRootChoice"],
    last_rung: str,
    prepared: Prepared | None,
    request_for: Callable[["sandbox_policy.SandboxRootChoice"], PlacementRequest],
    open_lease: Callable[[str | None, "sandbox_policy.SandboxRootChoice"], object],
    *,
    preflight: Callable[[], str | None],
    seal: Callable[[PlacementRequest], "ExecSpec | None"] | None,
    driver_enabled: bool,
    cancelled: threading.Event,
    settings: sandbox_policy.PlacementDriverSettings | None = None,
    local_capacity: Callable[[], LocalHeadroom | None] | None = None,
    local_admit: Callable[[sandbox_policy.PlacementDriverSettings, OperationBound], LocalAdmission] | None = None,
    local_release: Callable[[LocalReservation], None] | None = None,
    reserve_only: bool = False,
    headroom: object = None,
    budget_s: float | None = None,
    local_preflight: Callable[[str], str | None] | None = None,
    honour_remote_required: bool = True,
    probe_timeout_s: float | None = None,
    backend_for: Callable[[object], object] | None = None,
) -> PlacementDecision:
    """Decide where a candidate seat runs, and launch it there if a remote rung takes it.

    The walk of amendment C7 (agent-harness#1791). Local roots may occur anywhere.
    ``local_capacity`` supplies advisory headroom; ``local_admit`` atomically
    checks all three thresholds and returns a LocalAdmission containing an explicit
    LocalReservation handle and the pre-reservation reading. A reading alone never
    admits. A missing/invalid handle promises nothing is held. A definitive
    at-capacity/refused exception also promises nothing held; every other admission
    exception is uncertain, cancels its OperationBound and stops without overflow.
    `local_release(handle)` must complete release within ANSWER_BOUND_S or raise.
    Every known handle is released before a non-launch exit, including cancellation;
    uncertain release uses sandbox_placement_local_release_unconfirmed. Late returned
    handles are released by the abandoned admission worker. On launch the handle is
    transferred in decision.local_reservation; the caller owns subsequent cleanup.
    A failed release retains its known handle on the decision or cancellation exception
    for reconciliation. An admission that outlives the caller exposes
    pending_local_reservation on its decision or cancellation exception. Its
    inspect() and wait(timeout_s) report pending, released, retained(handle), or
    none_returned; cleanup that exceeds its bound retains the handle. An unknown
    handle remains explicitly uncertain.
    These hooks remain unwired at launch sites; missing hooks refuse local.

    ``rungs`` are the configured roots in order
    (:func:`sandbox_policy.candidate_roots`) and ``last_rung`` is ``local`` or ``none``
    (:func:`sandbox_policy.last_rung`). ``prepared`` is the runtime's revalidated local
    stage: this is called where ``commit`` is called today.

    * ``preflight()`` runs once, on facts the launching host already has, and returns a
      code when the seat may not be placed; then no remote rung is tried and the last rung
      is resolved at once with that code.
    * ``request_for(root)`` builds the rung's request. The walk sets its root, owner id and
      lease id, and sends ``egress_needs`` empty.
    * ``open_lease(name, root)`` is :func:`placement_lease.open_lease`: each rung that is
      asked gets its own lease, fsynced before ``admit``.
    * ``seal(request)`` applies the caller's guard on fresh numbers and returns the
      :class:`ExecSpec` to run, or ``None`` when the guard failed. The walk calls it in
      the sealing state and then calls ``execute`` itself, so nothing sits between "placed"
      and ``execute`` (C8).
    * ``driver_enabled`` is the launch module's flag, passed in. While it is false every
      ``leg`` request is refused on every rung before its backend is looked up; a
      ``qualification`` request is exempt (C10).

    Returns a :class:`PlacementDecision`: ``placed`` (``execute`` has been called; its
    ``placement`` goes to :func:`run_placed`), ``launching_host``, or ``not_run`` with its
    code. Raises :class:`PlacementCancelled` on a cancel. Every exit carries the trail.
    The walk owns one budget of time: the admission wait plus the transfer allowance.

    **Reservation-only exit** (``reserve_only=True``, v13 PLACECLI): the same walk, with no
    ``Prepared`` stage and no ``seal``. A remote rung that admits ends the walk with outcome
    ``reserved`` and :attr:`PlacementDecision.reservation` (its root, backend and HELD lease)
    before ``commit``, ``seal`` or ``execute``; the caller journals and owns that lease. A
    local rung ends ``launching_host`` with its slot, as before. ``headroom`` is the host's
    effective local-admission thresholds, ``budget_s`` shortens the walk's budget,
    ``local_preflight(label)`` may refuse the local rung before any capacity probe, a
    ``request_for`` refusal with a placement code records that code, and ``backend_for(root)``
    replaces the registry lookup. ``honour_remote_required=False`` ignores the environment
    knob, so no variable steers a reservation.
    """
    if last_rung not in _LAST_RUNGS:
        raise ValueError(f"unknown last rung {last_rung!r}")
    if not reserve_only and (prepared is None or seal is None):
        raise ValueError("a launching walk needs its prepared stage and its seal step")
    settings = settings if settings is not None else sandbox_policy.placement_driver_settings()
    refusal = preflight()
    walk = _Walk(prepared, request_for, open_lease, seal, bool(driver_enabled), cancelled, settings,  # type: ignore[arg-type]
                 local_capacity, local_admit, local_release, reserve_only=reserve_only,
                 headroom=headroom, budget_s=budget_s, local_preflight=local_preflight,
                 honour_remote_required=honour_remote_required, probe_timeout_s=probe_timeout_s,
                 backend_for=backend_for)
    try:
        if refusal is not None:
            return walk._end(walk._after_left(False, last_rung), str(refusal))
        return walk.run(tuple(rungs), last_rung)
    finally:
        walk.calls.close()


def _echoes(result: bytes, request: bytes) -> bool:
    """Does a result echo the digest of the request the runtime sent (C9)? The result is a
    JSON object whose ``request_sha256`` is the SHA-256 of the request bytes."""
    try:
        echoed = json.loads(result)
    except (TypeError, ValueError):
        return False
    return isinstance(echoed, dict) and echoed.get("request_sha256") == hashlib.sha256(request).hexdigest()


def run_placed(
    placement: "LegPlacement", *,
    on_progress: Callable[[ExecProgress], None] | None,
    cancelled: threading.Event,
) -> ExecResult:
    """Everything after ``execute``, for a placement :func:`place` returned as ``placed``.

    Waits for the result; while it waits, a no-deadline leg is renewed for as long as this
    process holds its lease, and the workload is cancelled at ``must_end_within_s`` whatever
    the backend does and whatever renewals arrived (C2). Then the sandbox is released:
    killed by lease id and confirmed absent (C11).

    * A terminal result for the same sandbox that echoes the request's digest is returned,
      with a runtime ``completed`` receipt. If the release could not be confirmed the
      result is KEPT: the placement carries ``sandbox_placement_release_unconfirmed`` and
      the lease entry stays for the reaper.
    * Anything else -- ``wait`` raised, the connection was lost, the result is not this
      leg's -- raises ``sandbox_placement_lost_after_launch``; the fixed end raises
      ``sandbox_placement_end_reached``; a cancel raises :class:`PlacementCancelled`.

    Nothing here starts the seat again or tries another rung.
    """
    spec, lease, launched_at = placement._spec, placement._lease, placement._launched_at
    if is_local(placement.backend) or spec is None or lease is None or launched_at is None:
        raise ValueError("run_placed takes a placement that place() launched")
    backend, sandbox_ref = placement.backend, placement.sandbox_ref
    settings = placement._driver_settings
    calls, renewals = _Calls(settings=settings), _Calls(settings=settings)
    result: ExecResult | None = None
    failure = _LOST_AFTER_LAUNCH if placement._launch_failed else None
    was_cancelled = cancelled.is_set()
    stop_renewing: Callable[[], None] = lambda: None  # noqa: E731
    try:
        if failure is None and spec.deadline_s is None:
            limit = _max_lifetime(backend)
            if limit is not None:
                # Without a deadline a backend's maximum lifetime is a liveness bound: the
                # leg is renewed while, and only while, this process holds the lease lock.
                stop_renewing = lease.heartbeat(  # type: ignore[attr-defined]
                    lambda: renewals.run(
                        lambda: backend.renew(sandbox_ref, limit, _bound(ANSWER_BOUND_S)),  # type: ignore[attr-defined]
                        ANSWER_BOUND_S,
                    ),
                    limit / 3.0,
                )
        seq = -1
        while failure is None and result is None:
            if cancelled.is_set():
                was_cancelled = True
                break
            wait_s = _WAIT_SLICE_S
            call_bound = wait_s + ANSWER_BOUND_S
            if spec.must_end_within_s is not None:
                left = spec.must_end_within_s - (_monotonic() - launched_at)
                if left <= 0:
                    failure = _END_REACHED
                    break
                wait_s = min(wait_s, left)
                # The call in flight never runs past the end (C2).
                call_bound = min(call_bound, left)
            try:
                got = calls.run(
                    lambda: backend.wait(sandbox_ref, wait_s),  # type: ignore[attr-defined]
                    call_bound, cancelled,
                )
            except _CallCancelled:
                continue
            except PlacementUnavailable as exc:
                if exc.code == _END_REACHED or (
                    exc.code == _TIMEOUT and spec.must_end_within_s is not None
                    # Decided from the clock now, not from the planned bound: a time-out
                    # before the end is a lost leg (C11, C12).
                    and _monotonic() - launched_at >= spec.must_end_within_s
                ):
                    failure = _END_REACHED
                else:
                    failure = _LOST_AFTER_LAUNCH
                break
            except Exception:
                failure = _LOST_AFTER_LAUNCH
                break
            if cancelled.is_set():
                was_cancelled = True
                break
            if isinstance(got, ExecProgress) and got.sandbox_ref == sandbox_ref:
                if isinstance(got.seq, int) and got.seq > seq:
                    seq = got.seq
                    if on_progress is not None:
                        on_progress(got)
            elif (
                isinstance(got, ExecResult) and got.sandbox_ref == sandbox_ref
                and type(got.result) is bytes and got.truncated is False
                and len(got.result) <= spec.output_cap_bytes
                and _echoes(got.result, spec.request)
            ):
                result = got
                placement._observed.add("completed")
                placement.record_runtime("completed")
            else:
                # `wait` returns only a result or progress (C12, before the reconnect plan).
                failure = _LOST_AFTER_LAUNCH
        if result is None:
            was_cancelled = was_cancelled or cancelled.is_set()
            try:
                calls.run(lambda: backend.cancel(sandbox_ref, _bound(ANSWER_BOUND_S)), ANSWER_BOUND_S)  # type: ignore[attr-defined]
            except Exception:
                pass
    finally:
        stop_renewing()
        lease.fence()  # type: ignore[attr-defined]
        confirmed = _release(calls, backend, lease)
        if confirmed:
            lease.clear()  # type: ignore[attr-defined]
        else:
            lease.abandon()  # type: ignore[attr-defined]
            placement.notices.append(_RELEASE_UNCONFIRMED)
        calls.close()
        renewals.close()
    if was_cancelled:
        raise PlacementCancelled(placement._trail)
    if result is not None:
        return result
    if not confirmed:
        # Without a result, an unconfirmed kill is a lost leg, whatever ended the wait.
        failure = _LOST_AFTER_LAUNCH
    raise PlacementUnavailable(failure or _LOST_AFTER_LAUNCH)


def _max_lifetime(backend: object) -> float | None:
    try:
        limit = backend.declaration().max_lifetime_s  # type: ignore[attr-defined]
    except Exception:
        return None
    return float(limit) if limit is not None and limit > 0 else None


# ----------------------------------------------------------------------------------------
# The placement process lifecycle (v13 PLACECLI, IF-0-PLACECLI-2).
#
# One restart-safe, per-client lifecycle behind `agent-harness-placement`. The `--client`
# flag selects one operator configuration, one certificate OU and one inventory directory;
# every reservation, same-request response, release tombstone, cleanup entry and
# `(client, reservation)` barrier is journaled in that inventory and nowhere else. LANEEXEC
# extends this class rather than forking it (binding §4.2).
# ----------------------------------------------------------------------------------------

#: ``x-placement-semantics.replay_settle_allowance_ms``.
REPLAY_SETTLE_ALLOWANCE_MS = 300_000
#: How long a released reservation's tombstone answers a repeated release with `released`.
TOMBSTONE_RETENTION_S = 86_400
_JOURNAL_MAX = 1 << 20
_PI_RUNNER_BINDINGS = {"openshell": "full-remote-pi-runner", "local": "minimal-without-app"}
_PROVIDER_REFUSED = "sandbox_placement_provider_refused"
_WORKLOAD_UNSUPPORTED = "sandbox_placement_workload_unsupported"
_PREFLIGHT = "preflight"
#: The only reservation ids this lifecycle issues; anything else was never ours.
_ISSUED_RESERVATION = re.compile(r"rsv-[0-9a-f]{32}")

# LaneExec (v13 LANEEXEC SL-3) lifecycle hooks.
#: ``x-prepare.constants.prepare_deadline_ms``.
PREPARE_DEADLINE_MS = 30_000
#: The code an unreadable caps record gives ``prepare`` (coordinator ruling 1). The ruling
#: names ``sandbox_placement_capability_unmet``, which the frozen ``PrepareResponse`` refused
#: enum does not admit; until that sentence is amended prepare refuses with the wire's
#: generic refusal, state ``refused``, exit 10, nothing changed.
PREPARE_CAPS_UNREADABLE_CODE = "sandbox_launch_refused"
#: ``patch_return.CANCEL_WAIT_SECONDS``: the longest one verified-owner cancel waits.
CANCEL_WAIT_S = 10.0
_PREPARE_MIN_WAIT_S = 0.5
_LAUNCH_REFUSED = "sandbox_launch_refused"
_LAUNCH_UNKNOWN = "sandbox_launch_reservation_unknown"
_LAUNCH_MISMATCH = "sandbox_launch_reservation_mismatch"
_LAUNCH_CLAIMED = "sandbox_launch_exec_claimed"
_LAUNCH_INPUT_MISMATCH = "sandbox_launch_input_mismatch"
_LAUNCH_DIRS = ("prepare", "prepare-requests", "claims", "launches", "cancels", "heartbeats",
                "cleanup", "runs", "returns", "stages", "ctl", "operations", "leases",
                "requests", "dispositions", "disposition-index", "stage-intents", "scratch-intents", "implicit",
                "renewals")
#: The run ids prepare assigns (they satisfy the envelope and JOURNAL identifier grammars).
_RUN_ID = re.compile(r"run-[0-9a-f]{32}")
#: A LaneExec journal key: a reservation id, a request id or a run id.
_LAUNCH_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
#: ``_settle_committed`` outcomes that are not a response: the settle bound was reached
#: under the lock, or the committed effect was removed or handed to cleanup.
_AT_BOUND = object()
_REMOVED = object()


class LifecycleError(RuntimeError):
    """An internal failure (exit class 70). ``str()`` is a closed code."""

    def __init__(self, code: str = "placement_internal") -> None:
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:
        return self.code


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_tree(path: Path) -> None:
    """Create (0700) or accept a directory this user owns that nobody else can open."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = os.lstat(path)
    if not os.path.isdir(path) or os.path.islink(path) or info.st_uid != os.geteuid():
        raise LifecycleError("placement_inventory_unsafe")
    if info.st_mode & 0o077:
        os.chmod(path, 0o700)


def _write_journal(path: Path, value: Mapping[str, object]) -> None:
    """Atomically replace one journal record: temporary file, fsync, rename, directory fsync."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    _fsync_directory(path.parent)


def _read_journal(path: Path) -> dict[str, object] | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        data = os.read(fd, _JOURNAL_MAX + 1)
    finally:
        os.close(fd)
    try:
        value = json.loads(data.decode("utf-8")) if len(data) <= _JOURNAL_MAX else None
    except (UnicodeDecodeError, ValueError):
        value = None
    if not isinstance(value, dict):
        raise LifecycleError("placement_journal_corrupt")
    return value


def _remove_journal(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


_GENERATION = re.compile("[a-f0-9]{32}")
_ROLLBACK_CAUSES = frozenset(("snapshot_expired", "upload_refused_empty", "scratch_unprovisioned",
                              "link_socket_creation_failed", "caps_recheck_refused"))
_DEBT_CAUSES = frozenset(("release", "cancel", "renewal_lost", "owner_gone", "allocation_unknown",
                          "rollback_unknown", "start_unknown", "collection_unknown"))
_EVIDENCE = ("descendants_ended", "parent_collected", "remote_barrier", "allocations_collected")


class Owner(NamedTuple):
    pid: int
    start: str


class FileId(NamedTuple):
    device: int
    inode: int


AllocationKind = Literal["stage", "scratch"]
_HELD_LOCKS = contextvars.ContextVar("placement_held_locks", default=frozenset())


@dataclass(frozen=True, slots=True)
class Debt:
    cause: str
    descendants_ended: bool | str
    parent_collected: bool | str
    remote_barrier: bool | str
    allocations_collected: bool | str

    def __post_init__(self) -> None:
        if self.cause not in _DEBT_CAUSES or any(
            type(getattr(self, k)) is not bool and getattr(self, k) != "inapplicable" for k in _EVIDENCE
        ):
            raise ValueError("invalid cleanup debt")


def _identity_fields(reservation_id: str, request_id: str, generation: str) -> dict:
    if not (_ISSUED_RESERVATION.fullmatch(reservation_id) and _LAUNCH_KEY.fullmatch(request_id)
            and _GENERATION.fullmatch(generation)):
        raise LifecycleError("placement_internal")
    return dict(version=1, reservation_id=reservation_id, request_id=request_id, generation=generation)


def _matches(row, key) -> bool:
    return row is not None and all(type(row.get(k)) is type(v) and row[k] == v for k, v in key.items())


class _Deadline:
    """One lifecycle operation's monotonic end: every blocking step uses what is left."""

    def __init__(self, end: float) -> None:
        self.end = end

    @classmethod
    def after(cls, seconds: float) -> "_Deadline":
        return cls(_monotonic() + max(0.0, float(seconds)))

    def left(self) -> float:
        return max(0.0, self.end - _monotonic())

    def expired(self) -> bool:
        return _monotonic() >= self.end


def _stopped(deadline: "_Deadline | None", cancelled: threading.Event | None) -> bool:
    """Whether the calling operation's deadline has passed or its caller cancelled."""
    return (cancelled is not None and cancelled.is_set()) or (deadline is not None and deadline.expired())


class _FileLock:
    """``flock`` on a 0600 lock file; ``blocking=False`` reports whether it was taken.
    With a ``deadline`` the lock is retried until that deadline, then reported not held;
    with ``retry=False`` as well it is tried once, and not at all once the deadline passed.
    A ``cancelled`` event ends the retrying the same way: the first try always happens,
    and once the event is set a contended lock is reported not held without waiting."""

    def __init__(self, path: Path, *, blocking: bool, deadline: "_Deadline | None" = None,
                 retry: bool = True, cancelled: threading.Event | None = None) -> None:
        self.path, self.blocking, self.fd, self.held = path, blocking, None, False
        self.deadline, self.retry, self.cancelled = deadline, retry, cancelled

    def __enter__(self) -> bool:
        import fcntl

        if self.deadline is not None and self.deadline.expired():
            return False
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        # With a deadline the kernel lock is never waited on: it is retried non-blocking.
        nonblocking = self.deadline is not None or not self.blocking
        while True:
            if self.deadline is not None and self.deadline.expired():
                return False
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
                self.held = True
                self._token = _HELD_LOCKS.set(_HELD_LOCKS.get() | {self.path})
                return True
            except BlockingIOError:
                if (not self.retry or self.deadline is None or self.deadline.expired()
                        or (self.cancelled is not None and self.cancelled.is_set())):
                    self.held = False
                    return False
                _sleep(min(_POLL_S, self.deadline.left()))

    def __exit__(self, *_exc: object) -> None:
        if self.held:
            _HELD_LOCKS.reset(self._token)
            self.held = False
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(text: object) -> float | None:
    from datetime import datetime

    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass(frozen=True)
class _TargetPlan:
    """One target's admission terms, decided before any probe."""

    target: "sandbox_policy.PlacementTargetConfig"
    vector: str | None
    policy_digest: str | None
    egress_sha256: str | None
    refusal: str | None

    @property
    def needs_bridge(self) -> bool:
        return self.target.kind == "openshell"


def effective_egress(
    providers: Sequence[str], baseline: Iterable[tuple[str, int]],
    endpoints: Mapping[str, Sequence[tuple[str, int]]],
) -> tuple[dict[str, object], str]:
    """The effective egress grant and ``Reservation.egress_sha256``: exactly the policy
    vector's baseline union every declared provider's allowlisted endpoints, provider names
    and endpoint records sorted and de-duplicated, digested over RFC 8785 bytes. No
    credential or credential-derived value enters it."""
    from .placement_process_contract import canonical_bytes

    rules = sorted({(str(host), int(port)) for host, port in baseline}
                   | {(str(host), int(port)) for name in providers for host, port in endpoints[name]})
    grant = {"providers": sorted(set(providers)),
             "rules": [{"host": host, "port": port} for host, port in rules]}
    return grant, "sha256:" + hashlib.sha256(canonical_bytes(grant)).hexdigest()


# -- the openshell route and providers reached only through the link ----------------------

#: LANEEXEC launch codes (``x-activation.remote``, ``x-launch-inputs``; PLACECLI
#: ``x-provider-egress.launch_binding``). No new code is added.
_LAUNCH_ROUTE_DISABLED = "sandbox_launch_route_disabled"
_LAUNCH_INPUT_MISMATCH = "sandbox_launch_input_mismatch"
_LAUNCH_INPUT_UNBOUND = "launch_input_unbound"
_PENDING_QUALIFICATION = "pending_qualification"


def openshell_route_state() -> str:
    """``"disabled"``, ``"enabled"`` or ``"unknown"``: the one implementation of the three
    conditions of LANEEXEC ``x-activation.remote``. The route is enabled only when the
    packaged policy status is no longer pending, ``panel_invoker._NONLOCAL_EXECUTION_DRIVER``
    is true and a production ``openshell`` backend is registered. The status is read first,
    so the invoker is never imported while it is pending. An unreadable status, an invoker
    import failure or a failing registry lookup is ``"unknown"``, which never counts as
    disabled for enforcement or as enabled for a launch."""
    try:
        status = sandbox_policy.placement_policy_status()
    except sandbox_policy.PlacementConfigError:
        return "unknown"
    if status == _PENDING_QUALIFICATION:
        return "disabled"
    try:
        import importlib

        flag = importlib.import_module(f"{__package__}.panel_invoker")._NONLOCAL_EXECUTION_DRIVER
    except Exception:
        return "unknown"
    if flag is not True:
        return "disabled"
    try:
        backend = backend_for_scheme("openshell")
    except Exception:
        return "unknown"
    return "disabled" if backend is None else "enabled"


def _launch_config_bound(config: "sandbox_policy.PlacementClientConfig", config_sha256: str) -> bool:
    return config_sha256 == config.config_sha256


def _launch_grant_refusal(config: "sandbox_policy.PlacementClientConfig", providers: Sequence[str],
                          baseline: Iterable[tuple[str, int]], egress_sha256: str) -> str | None:
    """The recomputed grant must carry no rule and equal the reservation's digest."""
    registry = config.providers
    grant, digest = effective_egress(providers, baseline, {name: registry[name].endpoints for name in providers})
    if grant["rules"] or digest != egress_sha256:
        return _LAUNCH_INPUT_UNBOUND
    return None


def _openshell_pi_runner_providers_refusal(config: "sandbox_policy.PlacementClientConfig") -> bool:
    """True while the configuration keeps the openshell ``pi-runner`` route closed: some
    ``pi-runner`` provider grants sandbox egress, or the remote vector's baseline is not
    empty."""
    try:
        return bool(sandbox_policy.placement_sandbox_egress_providers(config)
                    or sandbox_policy.placement_policy_baseline(_PI_RUNNER_BINDINGS["openshell"]))
    except sandbox_policy.PlacementConfigError:
        return True


def openshell_launch_refusal(
    config: "sandbox_policy.PlacementClientConfig", *, workload: str, target_kind: str,
    providers: Sequence[str], config_sha256: str, egress_sha256: str,
    route_state: Callable[[], str] | None = None,
) -> str | None:
    """The launch-boundary check for an openshell launch; ``None`` admits it.

    ``config`` is the effective configuration loaded for this launch, and the other values
    come from the reservation being launched. Checked in LANEEXEC's frozen order, binding
    before activation:

    1. ``config_sha256`` must equal the loaded configuration's digest
       (``sandbox_launch_input_mismatch``);
    2. for every openshell workload, the route state must be ``"enabled"``
       (``sandbox_launch_route_disabled``);
    3. for ``pi-runner`` only: no ``pi-runner`` provider in the configuration may grant
       sandbox egress, the remote vector's baseline must be empty, and every declared name
       must be a configured link-only provider (``sandbox_launch_route_disabled``);
    4. for ``pi-runner`` only: the recomputed grant must carry no rule and equal
       ``egress_sha256`` (``launch_input_unbound``).

    Launches on other targets are outside this check. ``route_state`` defaults to
    :func:`openshell_route_state`.
    """
    if target_kind != "openshell":
        return None
    if not _launch_config_bound(config, config_sha256):
        return _LAUNCH_INPUT_MISMATCH
    state = (route_state if route_state is not None else openshell_route_state)()
    if state != "enabled":
        return _LAUNCH_ROUTE_DISABLED
    if workload != "pi-runner":
        return None
    if _openshell_pi_runner_providers_refusal(config):
        return _LAUNCH_ROUTE_DISABLED
    names = tuple(providers)
    registry = config.providers
    if not names or any(name not in registry or not registry[name].link_only for name in names):
        return _LAUNCH_ROUTE_DISABLED
    return _launch_grant_refusal(config, names, (), egress_sha256)


def _openshell_pi_runner_refusal(config: "sandbox_policy.PlacementClientConfig",
                                 providers: Sequence[str]) -> str | None:
    """The reserve-time gate for ``pi-runner`` on openshell while the route state is not
    ``"disabled"`` (defence in depth; the launch check is the enforcing boundary). A declared
    provider that is not link-only is not permitted by the target's vector; otherwise a
    configuration that keeps the route closed makes the driver unavailable."""
    registry = config.providers
    if any(not registry[name].link_only for name in providers):
        return _PROVIDER_REFUSED
    if _openshell_pi_runner_providers_refusal(config):
        return _DRIVER_UNAVAILABLE
    return None


def _default_route_state() -> str:
    return openshell_route_state()


class PlacementLifecycle:
    """Reserve, release and reap for one placement client (``--client``).

    Every collaborator with an effect or a host reading is injected here, with the landed
    or production default: ``caps_loader``/``caps_readiness`` (``seat_resource_caps``),
    ``observe`` (the host's memory, load and PSI), ``backend_for`` (the backend registry,
    where no production OpenShell backend is registered), ``reconcile`` (the read-only
    replay check), ``bridge``, ``clock`` and ``route_state`` (:func:`openshell_route_state`).
    Nothing is read from the environment.
    """

    def __init__(
        self, client: str, *,
        state_root: Path | None = None, config_root: Path | None = None,
        caps_loader: Callable[[], object] | None = None,
        caps_readiness: Callable[[], str | None] | None = None,
        observe: Callable[[], Mapping[str, object]] | None = None,
        backend_for: Callable[[object], object] | None = None,
        reconcile: Callable[[Mapping[str, object], float], str] | None = None,
        bridge: object = None,
        clock: Callable[[], float] | None = None,
        settings: sandbox_policy.PlacementDriverSettings | None = None,
        new_id: Callable[[], str] | None = None,
        route_state: Callable[[], str] | None = None,
        launch_cancel: Callable[[Mapping[str, object], float], str] | None = None,
        launch_owner: Callable[[Mapping[str, object]], str] | None = None,
    ) -> None:
        from .placement_process_contract import CLIENTS

        if client not in CLIENTS:
            raise ValueError("unknown placement client")
        self.client = client
        self.state_root = Path(state_root) if state_root is not None else sandbox_policy.placement_state_root()
        self.inventory = self.state_root / client
        self.config_root = Path(config_root) if config_root is not None else sandbox_policy.placement_config_root()
        self.caps_loader = caps_loader if caps_loader is not None else _landed_caps_loader
        self.caps_readiness = caps_readiness if caps_readiness is not None else _landed_caps_readiness
        self.observe = observe if observe is not None else sandbox_policy.observe_local_pressure
        self.backend_for = backend_for if backend_for is not None else _registry_backend
        self.reconcile = reconcile if reconcile is not None else self._default_reconcile
        self._bridge = bridge
        self.clock = clock if clock is not None else time.time
        self._settings = settings
        self.new_id = new_id if new_id is not None else (lambda: secrets.token_hex(16))
        self.route_state = route_state if route_state is not None else _default_route_state
        # LaneExec (v13 LANEEXEC SL-3): cancel through the verified owning launcher, and
        # whether a claim's recorded owner process is still the same live process.
        self.launch_cancel = launch_cancel if launch_cancel is not None else _landed_launch_cancel
        self.launch_owner = launch_owner if launch_owner is not None else _landed_launch_owner

    # -- configuration -------------------------------------------------------------------
    @property
    def bridge(self) -> object:
        if self._bridge is None:
            from .placement_bridge import ForwardTcpUnixBridge, default_bridge_root

            # Under the inventory when the socket path fits, else the runtime directory.
            self._bridge = ForwardTcpUnixBridge(self.state_root / "b",
                                                fallback_root=default_bridge_root())
        return self._bridge

    @property
    def settings(self) -> sandbox_policy.PlacementDriverSettings:
        if self._settings is None:
            self._settings = sandbox_policy.placement_driver_settings(env={})
        return self._settings

    def caps_state(self) -> tuple[bool, str]:
        """``(readable, seat_caps_sha256)``; the documented sentinel when unreadable."""
        try:
            caps = self.caps_loader()
            from . import seat_resource_caps

            return True, seat_resource_caps.caps_sha256(caps)  # type: ignore[arg-type]
        except Exception:
            return False, sandbox_policy.SEAT_CAPS_UNAVAILABLE_SHA256

    def config(self, seat_caps_sha256: str | None = None) -> "sandbox_policy.PlacementClientConfig":
        if seat_caps_sha256 is None:
            seat_caps_sha256 = self.caps_state()[1]
        try:
            return sandbox_policy.load_placement_client_config(
                self.client, config_root=self.config_root, seat_caps_sha256=seat_caps_sha256)
        except sandbox_policy.PlacementConfigError:
            raise LifecycleError("placement_config_invalid") from None

    def version_response(self) -> object:
        from .placement_cli import version_response

        return version_response(self.config())

    # -- inventory -----------------------------------------------------------------------
    def _dir(self, name: str) -> Path:
        return self.inventory / name

    def _prepare(self) -> None:
        try:
            _private_tree(self.state_root)
            _private_tree(self.inventory)
            for name in ("attempts", "reservations", "tombstones", "cleanup"):
                _private_tree(self._dir(name))
            _private_tree(self._slots_dir())
        except OSError:
            raise LifecycleError("placement_inventory_unsafe") from None

    def _slots_dir(self) -> Path:
        # Host-wide: both clients' local reservations count toward live_sandboxes.
        return self.state_root / "local-slots"

    def _ids(self, name: str) -> list[str]:
        return [entry[:-5] for entry in sorted(os.listdir(self._dir(name)))
                if entry.endswith(".json") and not entry.startswith(".")]

    def _records(self, name: str) -> list[tuple[str, dict[str, object]]]:
        records = []
        for key in self._ids(name):
            record = _read_journal(self._dir(name) / f"{key}.json")
            if record is not None:
                records.append((key, record))
        return records

    def _try_lock(self, path: Path, deadline: "_Deadline | None") -> _FileLock:
        """One non-blocking try, refused once the deadline has passed: what start-up uses,
        so that an operation never waits on another process's lock."""
        return _FileLock(path, blocking=False, deadline=deadline, retry=False)

    def _startup(self, deadline: "_Deadline | None" = None,
                 cancelled: threading.Event | None = None) -> None:
        """Lifecycle start-up, within the calling operation's deadline and cancellation:
        settle every unsettled attempt at its bound, resume every unfinished cleanup
        transfer (settled attempts included), then collect the destroyed cleanup owners
        whose attempts have journaled their completion and prune expired tombstones no
        recovery still needs. LaneExec prepare attempts at their settle bound are settled
        first (``x-prepare.replay`` step 3). Enumeration only selects request ids; each
        attempt is read again under its own lock. Locks are only tried, never waited for, so an attempt or
        file another process holds is left for a later start-up. The deadline and
        cancellation are checked before each attempt and again once its lock is held;
        when either has fired, start-up stops and leaves everything it has not begun as it
        was.

        The collection pass lists destroyed owners and expired tombstones first and, only
        when either list is non-empty, reads the attempts once, without their locks (the
        lock order is attempt, then reservation), after both listings. Settlement and
        completion are never undone, so this snapshot can only keep a file longer than
        needed, never remove one still referenced. The attempts directory is synced once
        before the first removal, so every journal rename the snapshot saw is durable;
        when that sync fails nothing is removed in this pass. Each removal re-reads its own
        file under that file's lock; the attempts are not read again."""
        self._prepare()
        self._launch_startup(deadline, cancelled)
        for request_id in self._ids("attempts"):
            if _stopped(deadline, cancelled):
                return
            path = self._dir("attempts") / f"{request_id}.json"
            with self._try_lock(self._dir("attempts") / f"{request_id}.lock", deadline) as held:
                if not held:
                    continue
                if _stopped(deadline, cancelled):
                    return
                record = _read_journal(path)
                if record is None:
                    continue
                if not record.get("settled") and self._at_bound(record, self.clock()):
                    self._settle_end_reached(record, None, deadline, cancelled, wait=False)
                elif self._transfer_unfinished(record):
                    self._resume_transfer(record, deadline, cancelled, wait=False)
        if _stopped(deadline, cancelled):
            return
        destroyed = self._destroyed_owners(deadline, cancelled)
        expired = self._expired_tombstones(deadline, cancelled)
        if _stopped(deadline, cancelled) or not (destroyed or expired):
            return
        unfinished, completed = self._attempt_references(deadline, cancelled)
        # A stopped snapshot is partial; an unreadable attempt only sets ``unfinished`` to
        # None. Both stop conditions are permanent once true, so this tells them apart.
        if _stopped(deadline, cancelled):
            return
        owners = [key for key in destroyed if key in completed]
        tombstones = [] if unfinished is None else [rid for rid in expired if rid not in unfinished]
        if not (owners or tombstones):
            return
        try:
            _fsync_directory(self._dir("attempts"))
        except OSError:
            return
        self._prune_completed_owners(owners, completed, deadline, cancelled)
        self._prune_tombstones(tombstones, deadline, cancelled)

    @staticmethod
    def _tombstone_expired(tombstone: Mapping[str, object], now: float) -> bool:
        expires = tombstone.get("tombstone_expires")
        return not isinstance(expires, (int, float)) or now >= expires

    def _live_tombstone(self, path: Path) -> dict[str, object] | None:
        """The tombstone a release may answer from: present and not yet expired. An
        expired tombstone is publicly absent even while recovery still keeps it."""
        tombstone = _read_journal(path)
        if tombstone is None or self._tombstone_expired(tombstone, self.clock()):
            return None
        return tombstone

    def _destroyed_owners(self, deadline: "_Deadline | None",
                          cancelled: threading.Event | None) -> list[str]:
        """The keys of the cleanup owners in state ``destroyed``, from the directory
        listing. An entry that cannot be read is skipped and stays."""
        keys = []
        for key in self._ids("cleanup"):
            if _stopped(deadline, cancelled):
                return keys
            try:
                owner = _read_journal(self._dir("cleanup") / f"{key}.json")
            except (LifecycleError, OSError):
                continue
            if owner is not None and owner.get("state") == "destroyed":
                keys.append(key)
        return keys

    def _expired_tombstones(self, deadline: "_Deadline | None",
                            cancelled: threading.Event | None) -> list[str]:
        now = self.clock()
        expired = []
        for reservation_id in self._ids("tombstones"):
            if _stopped(deadline, cancelled):
                return expired
            tombstone = _read_journal(self._dir("tombstones") / f"{reservation_id}.json")
            if tombstone is not None and self._tombstone_expired(tombstone, now):
                expired.append(reservation_id)
        return expired

    def _prune_completed_owners(self, keys: Sequence[str], completed: Mapping[str, str],
                                deadline: "_Deadline | None",
                                cancelled: threading.Event | None) -> None:
        """Remove destroyed cleanup owners whose attempt has journaled the entry as
        completed (``completed``, from :meth:`_attempt_references`). Once the entry reads
        completed, no recovery reads the owner again. ``keys`` come from the ``cleanup``
        directory listing, never from journal content. Each owner is removed only under the
        lock its entry names, after being read again there, and only while it is still
        destroyed and records that same lock. The deadline and cancellation are checked per
        item; a lock not obtained leaves the owner for a later pass."""
        for key in keys:
            if _stopped(deadline, cancelled):
                return
            lock = completed[key]
            path = self._dir("cleanup") / f"{key}.json"
            with self._try_lock(self._dir(lock) / f"{key}.lock", deadline) as held:
                if not held:
                    continue
                if _stopped(deadline, cancelled):
                    return
                try:
                    owner = _read_journal(path)
                except (LifecycleError, OSError):
                    continue
                if owner is not None and owner.get("state") == "destroyed" and owner.get("lock") == lock:
                    _remove_journal(path)

    def _prune_tombstones(self, reservation_ids: Sequence[str], deadline: "_Deadline | None",
                          cancelled: threading.Event | None) -> None:
        """Remove expired tombstones that no recovery can still need.

        A tombstone's public expiry ends only what a repeated release answers. The file is
        also the durable proof that a committed effect was destroyed, which a planned
        transfer of that reservation relies on (``_materialize``). It is removed only
        under its reservation's lock, after being read again there, and only while no
        attempt that committed that reservation is unsettled and no transfer entry of it
        is unfinished (``reservation_ids`` are the expired tombstones that the start-up
        snapshot found unreferenced; a reference to a tombstoned reservation was journaled
        before it was destroyed). Any unreadable attempt keeps every tombstone. The
        deadline and cancellation are checked per item; a lock not obtained leaves the
        tombstone for a later pass."""
        for reservation_id in reservation_ids:
            if _stopped(deadline, cancelled):
                return
            path = self._dir("tombstones") / f"{reservation_id}.json"
            with self._try_lock(self._dir("reservations") / f"{reservation_id}.lock", deadline) as held:
                if not held:
                    continue
                if _stopped(deadline, cancelled):
                    return
                tombstone = _read_journal(path)
                if tombstone is not None and self._tombstone_expired(tombstone, self.clock()):
                    _remove_journal(path)

    _OWNER_LOCKS = ("reservations", "cleanup")

    def _attempt_references(self, deadline: "_Deadline | None", cancelled: threading.Event | None
                            ) -> tuple[set[str] | None, dict[str, str]]:
        """One lock-free read of every attempt: ``(unfinished, completed)``.

        ``unfinished`` is the reservation ids a recovery may still resolve: committed by an
        unsettled attempt, or keyed by a transfer entry that is not completed. It is
        ``None`` when any attempt could not be read, or the deadline or cancellation fired
        first. ``completed`` maps the key of each completed transfer entry to the lock its
        entry names (only ``reservations`` or ``cleanup``). It is decided per attempt: an
        attempt contributes only once it has been read in full, and never a key it still
        references itself, such as the reservation its commit holds while it is unsettled.
        A cleanup key belongs to the one attempt that planned it (its commit's reservation
        id, or a key prefixed by its request id), so an unreadable attempt cannot hold a
        reference to another attempt's completed key. A key named with two locks is left
        out."""
        unfinished: set[str] = set()
        completed: dict[str, str] = {}
        conflicting: set[str] = set()
        readable = True
        for request_id in self._ids("attempts"):
            if _stopped(deadline, cancelled):
                return None, completed
            try:
                record = _read_journal(self._dir("attempts") / f"{request_id}.json")
                if record is None:
                    continue
                own_unfinished: set[str] = set()
                own_completed: dict[str, str] = {}
                commit = record.get("commit")
                if commit is not None and not record.get("settled"):
                    own_unfinished.add(str(commit["reservation"]["reservation_id"]))  # type: ignore[index]
                transfer = record.get("transfer") or {}
                for entry in transfer.get("entries") or []:  # type: ignore[union-attr]
                    key = str(entry["key"])
                    if entry["state"] != "completed":
                        own_unfinished.add(key)
                    elif entry.get("lock") in self._OWNER_LOCKS:
                        own_completed[key] = str(entry["lock"])
            except (LifecycleError, OSError, KeyError, TypeError, AttributeError):
                readable = False
                continue
            unfinished |= own_unfinished
            for key, lock in own_completed.items():
                if key in own_unfinished:
                    continue
                if completed.setdefault(key, lock) != lock:
                    conflicting.add(key)
        for key in conflicting:
            completed.pop(key, None)
        return (unfinished if readable else None), completed

    @staticmethod
    def _settle_bound(record: Mapping[str, object]) -> float | None:
        start, deadline = record.get("started_at"), record.get("deadline_ms")
        if (type(start) not in (int, float) or not math.isfinite(start)  # type: ignore[arg-type]
                or type(deadline) is not int):
            return None
        return float(start) + (deadline + REPLAY_SETTLE_ALLOWANCE_MS) / 1000.0  # type: ignore[operator]

    def _at_bound(self, record: Mapping[str, object], now: float) -> bool:
        bound = self._settle_bound(record)
        return bound is None or now < float(record["started_at"]) or now >= bound  # type: ignore[arg-type]

    # -- responses -----------------------------------------------------------------------
    def _reserve_response(self, request: object, outcome: str, code: str | None,
                          trail: Sequence[object], reservation: object = None,
                          reason: str | None = None) -> object:
        from .placement_process_contract import ReserveResponse, TrailEntry

        entries = tuple(trail) or (TrailEntry(_PREFLIGHT, outcome, code, None),)
        if len(entries) > 16:
            entries = entries[:15] + entries[-1:]
        return ReserveResponse(request.request_id, outcome, code, reason, reservation,  # type: ignore[attr-defined]
                               entries, request.caller_context)  # type: ignore[attr-defined]

    def _refusal(self, request: object, code: str) -> object:
        from .placement_process_contract import TrailEntry

        return self._reserve_response(request, "refused", code,
                                      (TrailEntry(_PREFLIGHT, "refused", code, None),))

    def _settle(self, record: dict[str, object], response: object) -> object:
        from .placement_process_contract import encode_response, exit_class

        record["settled"] = True
        record["response"] = encode_response(response).decode("utf-8")  # type: ignore[arg-type]
        record["exit"] = exit_class(response)  # type: ignore[arg-type]
        _write_journal(self._dir("attempts") / f"{record['request_id']}.json", record)
        return response

    def _journal_attempt(self, record: dict[str, object]) -> None:
        _write_journal(self._dir("attempts") / f"{record['request_id']}.json", record)

    def _stored(self, record: Mapping[str, object]) -> object:
        from .placement_process_contract import ProtocolError, decode_response, encode_response

        raw = str(record.get("response", "")).encode("utf-8")
        try:
            response = decode_response("reserve", raw)
        except ProtocolError:
            raise LifecycleError("placement_journal_corrupt") from None
        if encode_response(response) != raw:
            raise LifecycleError("placement_journal_corrupt")
        return response

    # -- reserve -------------------------------------------------------------------------
    def reserve(self, request: object, *, cancelled: threading.Event) -> object:
        """``PlacementLifecycle.reserve(request, *, cancelled) -> ReserveResponse``."""
        from .placement_process_contract import canonical_bytes

        deadline = _Deadline.after(request.deadline_ms / 1000.0)  # type: ignore[attr-defined]
        self._startup(deadline, cancelled)
        body_sha256 = hashlib.sha256(canonical_bytes(request.to_json())).hexdigest()  # type: ignore[attr-defined]
        request_id = request.request_id  # type: ignore[attr-defined]
        path = self._dir("attempts") / f"{request_id}.json"
        with _FileLock(self._dir("attempts") / f"{request_id}.lock", blocking=False) as held:
            record = _read_journal(path)
            if record is not None and record.get("body_sha256") != body_sha256:
                # Same request_id, different body: refused, and nothing is created.
                return self._refusal(request, _REFUSED)
            if record is not None and record.get("settled"):
                return self._stored(record)
            if not held:
                # The original attempt is still running: nothing to reconcile yet.
                return self._indeterminate(request, record)
            if record is not None:
                return self._replay(request, record, cancelled, deadline)
            return self._reserve_new(request, body_sha256, cancelled, deadline)

    def _indeterminate(self, request: object, record: Mapping[str, object] | None) -> object:
        return self._reserve_response(request, "timeout", _TIMEOUT, self._journaled_trail(record))

    def _journaled_trail(self, record: Mapping[str, object] | None) -> tuple[object, ...]:
        from .placement_process_contract import TrailEntry

        rows = (record or {}).get("trail") or []
        return tuple(TrailEntry.from_json(row) for row in rows)  # type: ignore[union-attr]

    def _targets(self, config: object, request: object) -> list[object] | str:
        workload = request.workload  # type: ignore[attr-defined]
        if workload == "pi-runner":
            return list(config.targets)  # type: ignore[attr-defined]
        name = config.seat_route.get(workload)  # type: ignore[attr-defined]
        target = config.target(name) if name is not None else None  # type: ignore[attr-defined]
        return [target] if target is not None else _WORKLOAD_UNSUPPORTED

    def _plan(self, config: object, request: object, target: object, local_ready: bool) -> _TargetPlan:
        kind = target.kind  # type: ignore[attr-defined]
        providers = tuple(request.providers)  # type: ignore[attr-defined]
        if kind == "e2b":
            # A third-party target needs a current OD-7 clearance for every declared
            # provider; and it stays disabled until a later account-and-spend activation.
            refusal = (_PROVIDER_REFUSED if not set(providers) <= target.od7_providers  # type: ignore[attr-defined]
                       else _DRIVER_UNAVAILABLE)
            return _TargetPlan(target, None, None, None, refusal)  # type: ignore[arg-type]
        vector = (_PI_RUNNER_BINDINGS[kind] if request.workload == "pi-runner"  # type: ignore[attr-defined]
                  else request.policy_vector)  # type: ignore[attr-defined]
        registry = config.providers  # type: ignore[attr-defined]
        refusal = None
        if any(vector not in registry[name].policy_vectors for name in providers):
            refusal = _PROVIDER_REFUSED
        elif kind == "openshell" and not set(providers) <= target.probe_receipt_providers:  # type: ignore[attr-defined]
            # An owned host needs the generic egress-and-credential probe receipt.
            refusal = _PROVIDER_REFUSED
        elif (kind == "openshell" and request.workload == "pi-runner"  # type: ignore[attr-defined]
              and self.route_state() != "disabled"):
            # Once the route may be live (or its state is unknown), pi-runner on openshell
            # admits only providers reached through the link (defence in depth).
            refusal = _openshell_pi_runner_refusal(config, providers)
        elif kind == "local" and not local_ready:
            refusal = _CAPABILITY_UNMET
        try:
            baseline = sandbox_policy.placement_policy_baseline(vector)
        except sandbox_policy.PlacementConfigError:
            raise LifecycleError("placement_config_invalid") from None
        _grant, digest = effective_egress(
            providers, baseline, {name: registry[name].endpoints for name in providers})
        return _TargetPlan(target, vector, config.policy_digests[vector], digest, refusal)  # type: ignore[arg-type, attr-defined]

    def _binding(self, request: object, record: Mapping[str, object], plan: _TargetPlan,
                 config_sha256: str) -> dict[str, object]:
        target = plan.target
        return {
            "schema": "placement.reservation.v1",
            "reservation_id": record["reservation_id"],
            "workload": request.workload,  # type: ignore[attr-defined]
            "target": {"name": target.name, "kind": target.kind, "rank": target.rank},
            "transport_id": target.transport_id,
            "image_digest": request.image_digest,  # type: ignore[attr-defined]
            "policy_vector": plan.vector,
            "policy_digest": plan.policy_digest,
            "providers": list(request.providers),  # type: ignore[attr-defined]
            "egress_sha256": plan.egress_sha256,
            "client": self.client,
            "inventory": self.client,
            "rank_policy": "agent_executor" if request.workload == "pi-runner" else "seats_single_target",  # type: ignore[attr-defined]
            "lease_id": None,
            "expires_at": None,
            "config_sha256": config_sha256,
            "bridge": None,
            "ttl_s": request.ttl_s,  # type: ignore[attr-defined]
            "root": None if target.root is None else sandbox_policy._root_text(target.root),
        }

    def _reserve_new(self, request: object, body_sha256: str, cancelled: threading.Event,
                     deadline: "_Deadline") -> object:
        from .placement_process_contract import CLIENT_WORKLOADS, LocalHeadroomConfig

        record: dict[str, object] = {
            "request_id": request.request_id, "body_sha256": body_sha256,  # type: ignore[attr-defined]
            "client": self.client, "settled": False, "pending": [], "trail": [],
            "barrier": "none", "caller_context": dict(request.caller_context),  # type: ignore[attr-defined]
        }
        readable, caps_sha256 = self.caps_state()
        if not readable:
            # Coordinator ruling 1: an unreadable caps record refuses every reservation.
            return self._settle(record, self._refusal(request, _CAPABILITY_UNMET))
        config = self.config(caps_sha256)
        workload = request.workload  # type: ignore[attr-defined]
        if workload not in CLIENT_WORKLOADS[self.client]:
            return self._settle(record, self._refusal(request, _WORKLOAD_UNSUPPORTED))
        for name in request.providers:  # type: ignore[attr-defined]
            provider = config.providers.get(name)
            if provider is None or workload not in provider.workloads:
                return self._settle(record, self._refusal(request, _PROVIDER_REFUSED))
        targets = self._targets(config, request)
        if isinstance(targets, str):
            return self._settle(record, self._refusal(request, targets))
        if not targets:
            return self._settle(record, self._refusal(request, _REQUIRED_UNAVAILABLE))
        try:
            local_ready = self.caps_readiness() is None
        except Exception:
            local_ready = False
        plans = {t.name: self._plan(config, request, t, local_ready) for t in targets}  # type: ignore[attr-defined]
        record.update({
            "started_at": self.clock(), "deadline_ms": request.deadline_ms,  # type: ignore[attr-defined]
            "reservation_id": "rsv-" + self.new_id(),
        })
        self._journal_attempt(record)
        thresholds = LocalHeadroomConfig.from_json(config.local_headroom)
        bindings = {name: self._binding(request, record, plan, config.config_sha256)
                    for name, plan in plans.items() if plan.refusal is None}
        walk = _ReserveWalk(self, request, record, plans, bindings, thresholds)
        rungs = [self._root_for(t) for t in targets]
        try:
            decision = place(
                rungs, "none", None, walk.request_for, walk.open_lease,
                preflight=lambda: None, seal=None, driver_enabled=True, cancelled=cancelled,
                settings=self.settings, local_capacity=walk.local_capacity,
                local_admit=walk.local_admit, local_release=walk.local_release,
                reserve_only=True, headroom=thresholds, budget_s=deadline.left(),
                local_preflight=walk.local_preflight, honour_remote_required=False,
                probe_timeout_s=min(5.0, max(0.0, deadline.left())),
                backend_for=self.backend_for,
            )
        except PlacementCancelled as exc:
            uncertain = exc.local_reservation is not None or exc.pending_local_reservation is not None or any(
                entry.get("release_confirmed") is False for entry in exc.trail)
            trail = self._trail(exc.trail, plans)
            if uncertain:
                return self._unsettled(record, request, trail, _RELEASE_UNCONFIRMED)
            return self._settle(record, self._reserve_response(request, "refused", _REFUSED, trail))
        return self._decided(record, request, decision, plans, bindings, cancelled, deadline)

    @staticmethod
    def _root_for(target: object) -> object:
        root = target.root  # type: ignore[attr-defined]
        if root is None:
            return sandbox_policy.SandboxRootChoice(None, Path("/"), False, scheme=target.kind,  # type: ignore[attr-defined]
                                                    name=target.name)  # type: ignore[attr-defined]
        return root

    def _trail(self, trail: Sequence[Mapping[str, object]], plans: Mapping[str, _TargetPlan]) -> tuple[object, ...]:
        from .placement_process_contract import TrailEntry, admission_reasons, result_codes

        codes, reasons = result_codes(), admission_reasons()
        entries = []
        for row in trail:
            label, klass, code = str(row.get("rung", "")), row.get("class"), row.get("code")
            plan = plans.get(label)
            local = plan is not None and plan.target.kind == "local"
            mapped = code if code in codes else (_CODE_INVALID if isinstance(code, str) and _BACKEND_CODE.fullmatch(code)
                                                 and code not in PLACEMENT_CODES else _REFUSED)
            reason = row.get("reason") if row.get("reason") in reasons else None
            if klass == "admitted":
                entries.append(TrailEntry(label, "admitted", None, None))
            elif klass == "capacity":
                entries.append(TrailEntry(label, "at_capacity", mapped,
                                          "pressure" if local else "no_capacity"))
            elif klass == "unreachable":
                entries.append(TrailEntry(label, "unreachable", mapped, reason))
            elif (klass == "refused_unconfirmed" or code == _LOCAL_RELEASE_UNCONFIRMED
                  or row.get("release_confirmed") is False):
                entries.append(TrailEntry(label, "timeout",
                                          mapped if code in codes else _RELEASE_UNCONFIRMED, None))
            elif code == _TIMEOUT:
                # Released and confirmed absent: a certain failure with nothing held.
                entries.append(TrailEntry(label, "unreachable", _TIMEOUT, None))
            else:
                entries.append(TrailEntry(label, "refused", mapped, None))
        return tuple(entries)

    def _decided(self, record: dict[str, object], request: object, decision: PlacementDecision,
                 plans: Mapping[str, _TargetPlan], bindings: Mapping[str, dict[str, object]],
                 cancelled: threading.Event, deadline: "_Deadline") -> object:
        trail = self._trail(decision.trail, plans)
        if decision.outcome == "reserved" and decision.reservation is not None:
            held = decision.reservation
            return self._admit(record, request, bindings[held.label], trail, cancelled, deadline,
                               backend=held.backend, lease=held.lease)
        if decision.outcome == "launching_host" and decision.local_reservation is not None:
            label = next(str(row["rung"]) for row in reversed(decision.trail) if row.get("class") == "admitted")
            return self._admit(record, request, bindings[label], trail, cancelled, deadline,
                               slot=decision.local_reservation.token)
        code = decision.code or _REQUIRED_UNAVAILABLE
        if code in (_RELEASE_UNCONFIRMED, _LOCAL_RELEASE_UNCONFIRMED):
            return self._unsettled(record, request, trail, code)
        from .placement_process_contract import result_codes

        decisive = [entry for entry in trail  # type: ignore[attr-defined]
                    if not (plans.get(entry.target) is not None  # type: ignore[attr-defined]
                            and plans[entry.target].target.kind == "e2b"  # type: ignore[attr-defined]
                            and entry.code == _DRIVER_UNAVAILABLE)]  # type: ignore[attr-defined]
        if decisive and len(decisive) < len(trail):
            # A disabled E2B target is recorded, but the last real target decides.
            code = decisive[-1].code or code  # type: ignore[attr-defined]
        reason = decisive[-1].reason if decisive else None  # type: ignore[attr-defined]
        if code in (_CAPACITY, _CAPACITY_EXHAUSTED):
            outcome = "at_capacity"
        elif code in (_UNREACHABLE, _TIMEOUT):
            outcome = "unreachable"
        else:
            outcome = "refused"
        if code not in result_codes():
            code = _REFUSED
        return self._settle(record, self._reserve_response(request, outcome, code, trail, reason=reason))

    def _unsettled(self, record: dict[str, object], request: object, trail: Sequence[object],
                   code: str) -> object:
        """An effect may be held: arm the `(client, request)` barrier and keep the attempt
        unsettled, so a replay reconciles it (``reserve_replay``)."""
        record["trail"] = [entry.to_json() for entry in trail]  # type: ignore[attr-defined]
        record["barrier"] = "armed"
        _write_journal(self._dir("attempts") / f"{record['request_id']}.json", record)
        return self._reserve_response(request, "timeout", code, trail)

    def _reservation(self, binding: Mapping[str, object], *, lease_id: str | None,
                     expires_epoch: float, bridge: object = None) -> object:
        from .placement_process_contract import Reservation

        value = {key: binding[key] for key in binding if key not in ("ttl_s", "root")}
        value.update({"lease_id": lease_id, "expires_at": _iso(expires_epoch),
                      "bridge": None if bridge is None else bridge.to_json()})  # type: ignore[attr-defined]
        return Reservation.from_json(value)

    def _admit(self, record: dict[str, object], request: object, binding: Mapping[str, object],
               trail: Sequence[object], cancelled: threading.Event, deadline: "_Deadline", *,
               backend: object = None, lease: object = None, slot: str | None = None) -> object:
        """Commit one admitted rung, recoverably.

        1. The commit intent is journaled in the attempt record, under its lock: the exact
           reservation (expiry fixed now) and its complete cleanup effect, including the
           bridge directory a bridged reservation will use. It replaces the walk's pending
           effect, so the effect has one owner.
        2. A bridged reservation opens its bridge within the remaining deadline, then the
           commit is journaled again, complete, with the bridge handle.
        3. Under the reservation's lock, cancellation and the deadline are checked again;
           when either fired, the effects stay owned by the commit and the attempt stays
           unsettled. Otherwise the active reservation is published and the attempt
           settled, still under that lock. A restart between any two steps recovers the
           commit without allocating anything."""
        from .placement_process_contract import TrailEntry

        now = self.clock()
        expires = now + float(binding["ttl_s"])  # type: ignore[arg-type]
        label = str(binding["target"]["name"])  # type: ignore[index]
        lease_id = None if lease is None else str(lease.lease_id)  # type: ignore[attr-defined]
        reservation = self._reservation(binding, lease_id=lease_id, expires_epoch=expires)
        bridged = binding["workload"] in ("pi-runner", "leg") and binding["target"]["kind"] == "openshell"  # type: ignore[index]
        effect: dict[str, object] = (
            {"kind": "local", "slot": slot, "target": label, "root": None, "bridge": None}
            if lease is None else
            {"kind": "remote", "lease_id": lease_id, "target": label, "root": binding["root"],
             "bridge": None})
        if bridged:
            directory = self.bridge.directory_for(reservation)  # type: ignore[attr-defined]
            effect["bridge_directory"] = None if directory is None else str(directory)
        commit: dict[str, object] = {
            "reservation": reservation.to_json(), "effect": effect, "ttl_s": binding["ttl_s"], "complete": not bridged,  # type: ignore[attr-defined]
            "created_at": now, "trail": [entry.to_json() for entry in trail],  # type: ignore[attr-defined]
        }
        self._journal_commit(record, commit)
        timeout_trail = (*trail[:-1], TrailEntry(label, "timeout", _TIMEOUT, None))
        if bridged:
            if cancelled.is_set() or deadline.expired():
                return self._commit_left_held(record, request, lease, timeout_trail)
            try:
                handle = self._open_bridge(reservation, backend, lease, cancelled, deadline)
            except Exception:
                # No route, transport or bridge fallback after admission: release this rung.
                return self._bridge_failed(record, request, commit, backend, lease, trail, deadline,
                                           cancelled)
            reservation = self._reservation(binding, lease_id=lease_id, expires_epoch=expires,
                                            bridge=handle.descriptor)  # type: ignore[attr-defined]
            effect = {**effect, "bridge": handle.to_json()}  # type: ignore[attr-defined]
            commit = {**commit, "reservation": reservation.to_json(), "effect": effect,  # type: ignore[attr-defined]
                      "complete": True}
            self._journal_commit(record, commit)
        rid = reservation.reservation_id  # type: ignore[attr-defined]
        with _FileLock(self._dir("reservations") / f"{rid}.lock", blocking=False, deadline=deadline,
                       cancelled=cancelled) as held:
            if not held or cancelled.is_set() or deadline.expired():
                return self._commit_left_held(record, request, lease, timeout_trail)
            self._publish_reservation(commit, str(record["request_id"]))
            if lease is not None:
                lease.detach()  # type: ignore[attr-defined]
            return self._settle(record, self._reserve_response(request, "admitted", None, trail, reservation))

    def _journal_commit(self, record: dict[str, object], commit: Mapping[str, object]) -> None:
        record["commit"] = dict(commit)
        record["pending"] = []
        self._journal_attempt(record)

    def _commit_left_held(self, record: dict[str, object], request: object, lease: object,
                          trail: Sequence[object]) -> object:
        """Time ran out, or the caller cancelled, after admission: no admission is reported;
        the committed effects stay owned by the attempt for replay or terminal cleanup."""
        if lease is not None:
            lease.detach()  # type: ignore[attr-defined]
        return self._unsettled(record, request, trail, _TIMEOUT)

    def _bridge_failed(self, record: dict[str, object], request: object, commit: Mapping[str, object],
                       backend: object, lease: object, trail: Sequence[object],
                       deadline: "_Deadline", cancelled: threading.Event) -> object:
        """The bridge could not be opened after admission: release this rung within the
        caller's deadline and cancellation. Once the caller has cancelled, the bridge
        reclaim still runs but no remote cleanup call starts; the lease reference is then
        abandoned, the commit is kept and the attempt stays unsettled, so a replay or the
        terminal cleanup removes the effect."""
        from .placement_process_contract import TrailEntry

        effect = commit["effect"]  # type: ignore[index]
        label = str(effect["target"])  # type: ignore[index]
        lease.fence()  # type: ignore[attr-defined]
        if self._cleanup(effect, deadline, cancelled):  # type: ignore[arg-type]
            lease.clear()  # type: ignore[attr-defined]
            record.pop("commit", None)
            trail = (*trail[:-1], TrailEntry(label, "refused", _REFUSED, None))
            return self._settle(record, self._reserve_response(request, "refused", _REFUSED, trail))
        lease.abandon()  # type: ignore[attr-defined]
        trail = (*trail[:-1], TrailEntry(label, "timeout", _RELEASE_UNCONFIRMED, None))
        return self._unsettled(record, request, trail, _RELEASE_UNCONFIRMED)

    def _publish_reservation(self, commit: Mapping[str, object], request_id: str) -> None:
        """The committed reservation becomes the active record, the effect's owner."""
        reservation = commit["reservation"]  # type: ignore[index]
        entry = {"reservation": reservation, "state": "active", "created_at": commit["created_at"],
                 "effect": commit["effect"], "request_id": request_id}
        if "ttl_s" in commit:
            entry["ttl_s"] = commit["ttl_s"]
        _write_journal(self._dir("reservations") / f"{reservation['reservation_id']}.json", entry)  # type: ignore[index]


    def _open_bridge(self, reservation: object, backend: object, lease: object,
                     cancelled: threading.Event, deadline: "_Deadline") -> object:
        from .placement_bridge import BridgeExposure, BridgeUnavailable, operation_deadline

        exposure_of = getattr(backend, "forward_exposure", None)
        if exposure_of is None:
            raise BridgeUnavailable("bridge_exposure_invalid")
        timeout_s = min(ANSWER_BOUND_S, deadline.left())
        if timeout_s <= 0:
            raise BridgeUnavailable("bridge_cancelled")
        calls = _Calls(settings=self.settings)
        try:
            raw = calls.run(lambda: exposure_of(lease.lease_id, _bound(timeout_s, cancelled)),  # type: ignore[attr-defined]
                            timeout_s, cancelled)
        finally:
            calls.close()
        if not isinstance(raw, Mapping) or set(raw) != {"service_name", "upstream"}:
            raise BridgeUnavailable("bridge_exposure_invalid")
        exposure = BridgeExposure(raw["service_name"], raw["upstream"])
        with operation_deadline(deadline.end):
            return self.bridge.open(reservation, exposure, cancelled=cancelled)  # type: ignore[attr-defined]

    def _replay(self, request: object, record: dict[str, object], cancelled: threading.Event,
                deadline: "_Deadline") -> object:
        """``reserve_replay`` steps 3 to 5 for an unsettled attempt of the same body.

        Settlement comes only from what is already durable: a complete commit becomes the
        admitted response with its original reservation, expiry and bridge. Besides the one
        bounded read-only reconciliation, no target, lease, slot, bridge or exposure call is
        made, and expiry is never recomputed. Cancellation, the remaining time and the
        settle bound are checked before the reconciliation and again after every wait."""
        from .placement_process_contract import TrailEntry

        now = self.clock()
        if self._at_bound(record, now):
            return self._settle_end_reached(record, request, deadline, cancelled)
        if cancelled.is_set() or deadline.expired():
            return self._indeterminate(request, record)
        bound = self._settle_bound(record)
        timeout_s = max(0.0, min(deadline.left(), bound - now))  # type: ignore[operator]
        try:
            verdict = self.reconcile(record, timeout_s)
        except Exception:
            verdict = "indeterminate"
        if self._at_bound(record, self.clock()):
            return self._settle_end_reached(record, request, deadline, cancelled)
        if cancelled.is_set() or deadline.expired():
            return self._indeterminate(request, record)
        trail = self._journaled_trail(record)
        commit = record.get("commit") if isinstance(record.get("commit"), dict) else None
        if (verdict == "held_ready" and commit is not None and commit.get("complete")
                and not record.get("transfer")):
            settled = self._settle_committed(record, request, commit, cancelled, deadline)
            if settled is _AT_BOUND:
                return self._settle_end_reached(record, request, deadline, cancelled)
            if settled is not _REMOVED:
                return settled
            verdict = "nothing_held"
        if verdict == "nothing_held":
            effects = self._owned_effects(record)
            transfer = record.get("transfer") or {}
            entries = transfer.get("entries") or []  # type: ignore[union-attr]
            label = (str(commit["effect"]["target"]) if commit is not None  # type: ignore[index]
                     else str(effects[-1]["target"]) if effects
                     else str(entries[-1]["effect"]["target"]) if entries else _PREFLIGHT)
            self._plan_transfer(record)
            self._resume_transfer(record, deadline, cancelled)
            entries_ = (*trail, TrailEntry(label, "unreachable", _TIMEOUT, None))
            return self._settle(record, self._reserve_response(request, "unreachable", _TIMEOUT, entries_))
        return self._indeterminate(request, record)

    def _settle_committed(self, record: dict[str, object], request: object,
                          commit: Mapping[str, object], cancelled: threading.Event,
                          deadline: "_Deadline") -> object:
        """Settle a complete, durable commit as admitted, under its reservation's lock (the
        lock every consumer of that effect holds). Inside the lock, immediately before
        publication: a tombstone, a cleanup owner or a planned transfer means the effect was
        removed or handed on (``_REMOVED``); the settle bound reached means the terminal rule
        applies (``_AT_BOUND``); cancellation or an exhausted deadline answers indeterminate
        and keeps the commit. Otherwise the record is published if the interruption came
        before publication, and the attempt settles under the same lock."""
        from .placement_process_contract import Reservation, TrailEntry

        reservation = Reservation.from_json(commit["reservation"])  # type: ignore[arg-type]
        rid = reservation.reservation_id
        with _FileLock(self._dir("reservations") / f"{rid}.lock", blocking=False,
                       deadline=deadline, cancelled=cancelled) as held:
            if not held or cancelled.is_set() or deadline.expired():
                return self._indeterminate(request, record)
            if self._at_bound(record, self.clock()):
                return _AT_BOUND
            if (record.get("transfer")
                    or os.path.lexists(self._dir("tombstones") / f"{rid}.json")
                    or os.path.lexists(self._dir("cleanup") / f"{rid}.json")):
                return _REMOVED
            if _read_journal(self._dir("reservations") / f"{rid}.json") is None:
                self._publish_reservation(commit, str(record["request_id"]))
            rows = commit.get("trail") or []
            trail = tuple(TrailEntry.from_json(row) for row in rows)  # type: ignore[union-attr]
            return self._settle(record, self._reserve_response(request, "admitted", None, trail, reservation))

    def _owned_effects(self, record: Mapping[str, object]) -> list[dict[str, object]]:
        """The effects this attempt still owns directly: its commit's complete effect, or
        the walk's pending effects when no commit was journaled. Once a cleanup transfer is
        planned, the transfer owns them and this is empty."""
        if record.get("transfer"):
            return []
        commit = record.get("commit")
        if isinstance(commit, dict):
            return [dict(commit["effect"])]  # type: ignore[arg-type]
        return [dict(row) for row in record.get("pending") or [] if isinstance(row, dict)]  # type: ignore[union-attr]

    def _ownership(self, record: Mapping[str, object], effect: Mapping[str, object],
                   index: int) -> tuple[str, str]:
        """The stable ``(key, lock)`` of one effect. A committed effect is owned under its
        reservation id and serialized on that reservation's lock, the lock every consumer
        of the reservation takes; a pending effect is owned under its attempt and lease or
        slot, serialized on its own cleanup lock."""
        commit = record.get("commit")
        if isinstance(commit, dict):
            return str(commit["reservation"]["reservation_id"]), "reservations"  # type: ignore[index]
        identity = effect.get("lease_id") or effect.get("slot") or str(index)
        return f"{record['request_id']}--{identity}", "cleanup"

    def _owner_lock(self, key: str, lock: str, deadline: "_Deadline | None", *,
                    wait: bool = True, cancelled: threading.Event | None = None) -> "_FileLock":
        return _FileLock(self._dir(lock) / f"{key}.lock", blocking=False, deadline=deadline,
                         retry=wait, cancelled=cancelled)

    def _plan_transfer(self, record: dict[str, object]) -> None:
        """Durably record, in the attempt, the hand-over of its effects to cleanup owners
        under stable keys, before any owner is materialized. Idempotent."""
        if record.get("transfer"):
            return
        entries = []
        for index, effect in enumerate(self._owned_effects(record)):
            key, lock = self._ownership(record, effect, index)
            entries.append({"key": key, "lock": lock, "effect": effect, "state": "planned"})
        record["transfer"] = {"entries": entries}
        record["pending"] = []
        self._journal_attempt(record)

    def _transfer_unfinished(self, record: Mapping[str, object]) -> bool:
        transfer = record.get("transfer") or {}
        return any(entry.get("state") != "completed"  # type: ignore[union-attr]
                   for entry in transfer.get("entries") or [])  # type: ignore[union-attr]

    def _resume_transfer(self, record: dict[str, object], deadline: "_Deadline | None",
                         cancelled: threading.Event | None = None, *, wait: bool = True) -> None:
        """Materialize or complete each entry under its owner lock, within the deadline and
        cancellation, and journal the new states; an entry whose lock is not obtained
        stays as it is for a later start-up. The deadline and cancellation are checked
        before each entry and again once its lock is held: when either has fired, no
        further entry is materialized and the states reached so far are journaled. A
        completed entry's destroyed owner is removed only after the attempt journals that
        completion, so nothing is ever resurrected. ``wait=False`` only tries each lock."""
        entries = (record.get("transfer") or {}).get("entries") or []  # type: ignore[union-attr]
        changed = False
        for entry in entries:
            if entry["state"] == "completed":
                continue
            if _stopped(deadline, cancelled):
                break
            with self._owner_lock(entry["key"], entry["lock"], deadline, wait=wait,
                                  cancelled=cancelled) as held:
                if not held or _stopped(deadline, cancelled):
                    continue
                state = self._materialize(entry)
            if state != entry["state"]:
                entry["state"] = state
                changed = True
        if changed:
            self._journal_attempt(record)
        for entry in entries:
            if entry["state"] == "completed":
                if _stopped(deadline, cancelled):
                    return
                with self._owner_lock(entry["key"], entry["lock"], deadline, wait=wait,
                                      cancelled=cancelled) as held:
                    held = held and not _stopped(deadline, cancelled)
                    owner = _read_journal(self._dir("cleanup") / f"{entry['key']}.json") if held else None
                    if owner is not None and owner.get("state") == "destroyed":
                        _remove_journal(self._dir("cleanup") / f"{entry['key']}.json")

    def _materialize(self, entry: Mapping[str, object]) -> str:
        """Under the owner lock: give one planned effect its single cleanup owner. An
        existing owner (owned or destroyed) is recognized, never rewritten; a committed
        effect already destroyed by a consumer (its tombstone) completes the entry; an
        active record of the same reservation is retired as its owner materializes."""
        key = str(entry["key"])
        existing = _read_journal(self._dir("cleanup") / f"{key}.json")
        committed = entry["lock"] == "reservations"
        if existing is not None:
            if committed:
                self._retire_active(key)
            return "completed" if existing.get("state") == "destroyed" else "materialized"
        if committed and os.path.lexists(self._dir("tombstones") / f"{key}.json"):
            self._retire_active(key)
            return "completed"
        self._write_cleanup_owner(key, str(entry["lock"]), entry["effect"])  # type: ignore[arg-type]
        if committed:
            self._retire_active(key)
        return "materialized"

    def _write_cleanup_owner(self, key: str, lock: str, effect: Mapping[str, object]) -> None:
        _write_journal(self._dir("cleanup") / f"{key}.json",
                       {"key": key, "lock": lock, "state": "owned", "created_at": self.clock(),
                        "effect": dict(effect)})

    def _retire_active(self, reservation_id: str) -> None:
        _remove_journal(self._dir("reservations") / f"{reservation_id}.json")

    def _claimed_by_transfer(self, reservation_id: str, active: Mapping[str, object]) -> bool:
        """Under the reservation lock: whether a cleanup transfer owns this reservation's
        effect. If so the active record is not cleaned or admitted separately; it is
        retired as the transfer's owner materializes."""
        if os.path.lexists(self._dir("cleanup") / f"{reservation_id}.json"):
            self._retire_active(reservation_id)
            return True
        request_id = active.get("request_id")
        if not isinstance(request_id, str):
            return False
        attempt = _read_journal(self._dir("attempts") / f"{request_id}.json")
        for entry in ((attempt or {}).get("transfer") or {}).get("entries") or []:  # type: ignore[union-attr]
            if entry.get("key") == reservation_id and entry.get("state") != "completed":
                self._materialize(entry)
                return True
        return False

    @staticmethod
    def _parsed_root(text: str, name: str) -> object:
        location = sandbox_policy.parse_location(text)
        return sandbox_policy.SandboxRootChoice(location.host, location.path, False,
                                                scheme=location.scheme, name=name)

    def _settle_end_reached(self, record: dict[str, object], request: object = None,
                            deadline: "_Deadline | None" = None,
                            cancelled: threading.Event | None = None, *,
                            wait: bool = True) -> object:
        """Step 3: settle terminally at the bound and arm the barrier for this walk only.
        The attempt's effects (the complete committed effect when there is one) are first
        durably planned for transfer to cleanup owners, then materialized as far as the
        deadline and cancellation allow; an unfinished transfer is resumed by a later
        start-up. Planning and the terminal settlement are journaled even when the deadline
        or cancellation has fired, so a touched attempt never settles without its plan."""
        from .placement_process_contract import TrailEntry

        trail = self._journaled_trail(record)
        effects = self._owned_effects(record)
        entries = ((record.get("transfer") or {}).get("entries") or [])  # type: ignore[union-attr]
        if not trail:
            label = (str(effects[-1]["target"]) if effects
                     else str(entries[-1]["effect"]["target"]) if entries else _PREFLIGHT)
            trail = (TrailEntry(label, "timeout", _END_REACHED, None),)
        if request is None:
            context = record.get("caller_context")
            request = _RequestEcho(str(record["request_id"]),
                                   dict(context) if isinstance(context, dict) else {})
        self._plan_transfer(record)
        self._resume_transfer(record, deadline, cancelled, wait=wait)
        record["barrier"] = "armed"
        return self._settle(record, self._reserve_response(request, "timeout", _END_REACHED, trail))

    def _default_reconcile(self, record: Mapping[str, object], timeout_s: float) -> str:
        """One read-only check of the journaled uncertain effect. A local slot is held iff
        its file exists; a remote lease is held iff its owner listing names it. Either is
        ready only when the attempt's commit is complete."""
        effects = self._owned_effects(record)
        if not effects:
            return "nothing_held"
        effect = effects[-1]
        commit = record.get("commit")
        complete = isinstance(commit, dict) and bool(commit.get("complete"))
        if effect.get("kind") == "local":
            if not (self._slots_dir() / f"{effect.get('slot')}.json").exists():
                return "nothing_held"
            return "held_ready" if complete else "indeterminate"
        try:
            root = effect.get("root") or (effect.get("binding") or {}).get("root")  # type: ignore[union-attr]
            backend = self.backend_for(self._parsed_root(str(root), str(effect["target"])))
            if backend is None:
                return "indeterminate"
            from . import placement_lease

            owner = placement_lease.owner_id(self.inventory)
            calls = _Calls(settings=self.settings)
            try:
                owned = calls.run(lambda: [tuple(pair) for pair in backend.list_owned(owner, _bound(timeout_s))],  # type: ignore[attr-defined]
                                  timeout_s)
            finally:
                calls.close()
            listed = any(pair[1] == effect.get("lease_id") for pair in owned)  # type: ignore[union-attr]
        except Exception:
            return "indeterminate"
        if not listed:
            return "nothing_held"
        return "held_ready" if complete else "indeterminate"

    def _flags(self, entry: Mapping[str, object] | None, *, tombstone: bool = False) -> object:
        from .placement_process_contract import LeaseFlags

        if entry is None:
            return LeaseFlags(barrier_confirmed=True)
        expires = _epoch(entry.get("reservation", {}).get("expires_at"))  # type: ignore[union-attr]
        expired = expires is not None and self.clock() >= expires
        if tombstone:
            return LeaseFlags(create_settled=True, fenced=True, destruction_observed=True,
                              barrier_confirmed=True, expired=expired)
        claimed = self._launch_claimed(entry)
        if (entry.get("state") == "cleanup_pending" or self._generation_closed(
                self.launch_claim_record(entry["reservation"]["reservation_id"]))):
            return LeaseFlags(reserved=True, create_settled=True, fenced=True, exec_claimed=claimed,
                              cleanup_pending=True, expired=expired)
        return LeaseFlags(reserved=True, create_settled=True, ready=True, exec_claimed=claimed,
                          barrier_confirmed=True, expired=expired)

    @contextmanager
    def _teardown_lock(self, reservation_id, deadline, cancelled, *, echo=None, reap=False):
        """Snapshot the claim, fence outside the journal, then take lease before journal."""
        with self._owner_lock(reservation_id, "reservations", deadline, cancelled=cancelled) as held:
            try:
                claim = self.launch_claim_record(reservation_id) if held else None
            except (OSError, LifecycleError):
                yield False
                return
            if not claim or not claim.get("claimed") or claim.get("generation") is None:
                yield held
                return
            active = _read_journal(self._dir("reservations") / (reservation_id + ".json"))
            if (not active or self._claimed_by_transfer(reservation_id, active)
                    or echo is not None and active["reservation"] != echo):
                yield held
                return
            generation = claim["generation"]
            key = _identity_fields(reservation_id, claim["request_id"], generation)
            gone = reap and self.launch_owner(claim) == "gone"
            if reap and not gone and active["state"] != "cleanup_pending":
                expires = _epoch(active["reservation"]["expires_at"])
                if not self._generation_reap_due(claim, expired=expires is not None and self.clock() >= expires):
                    # A candidate observed during a renewal may be healthy by the
                    # time reap obtains the journal. Leave that owner in place.
                    yield False
                    return
            cause = "owner_gone" if gone else "release"
        try:
            fenced = self.fence_launch(reservation_id, claim["request_id"], generation,
                                       cause=cause, deadline=deadline.end)
        except (LifecycleError, OSError):
            fenced = False
        if not fenced or _stopped(deadline, cancelled):
            yield False
            return
        try:
            terminal = self.launch_terminal(claim["request_id"])
        except (OSError, LifecycleError):
            yield False
            return
        if not terminal and self.launch_owner(claim) != "gone":
            outcome = self.cancel_launch_owner(reservation_id, claim["request_id"], generation,
                                               deadline=deadline.end)
            from .launch_return import map_cancel
            mapped = map_cancel(outcome, record_present=True, claim_held=True)
            if mapped.local_outcome is not None:
                try:
                    self.journal_local_cancel(claim["request_id"], mapped.local_outcome, deadline=deadline)
                except (OSError, LifecycleError):
                    yield False
                    return
        with self.launch_lease_lock(reservation_id, timeout_s=deadline.left()) as leased:
            if not leased or _stopped(deadline, cancelled):
                yield False
                return
            with self.launch_operation_lock(reservation_id, generation, timeout_s=deadline.left()) as op:
                if not op:
                    yield False
                    return
                with self._owner_lock(reservation_id, "reservations", deadline, cancelled=cancelled) as held:
                    if not held or not self._owned_claim(key):
                        yield False
                        return
                    if self._generation_collectible(claim, deadline, check_allocations=False):
                        debt = Debt(**self._disposition(key)["debt"])
                        if debt.allocations_collected is False and self._recover_allocations(
                                reservation_id, deadline, except_generation=generation):
                            self.write_cleanup_debt_locked(reservation_id, claim["request_id"], generation,
                                                           debt=replace(debt, allocations_collected=True),
                                                           deadline=deadline.end)
                    yield True

    def _generation_reap_due(self, claim, *, expired: bool) -> bool:
        if not claim or not claim.get("claimed") or not claim.get("generation"):
            return expired
        try:
            key = _identity_fields(claim["reservation_id"], claim["request_id"], claim["generation"])
            row = self._disposition(key)
            if self._disposition_closed(row):
                return True
            # Open renewal debt becomes eligible only after the confirmed lease window.
            return (expired or row["debt"] is not None) and not self._renewal_current(key, row)
        except (ValueError, TypeError, KeyError, LifecycleError, OSError):
            return True

    def _renewal_fence_at(self, key, disposition) -> float | None:
        confirmed = self._confirmed_renewal(key, disposition)
        if confirmed is None:
            return None
        return confirmed["heartbeat_at"] + confirmed["ttl_s"] * 2 / 3

    def _renewal_current(self, key, disposition) -> bool:
        fence_at = self._renewal_fence_at(key, disposition)
        return fence_at is not None and _monotonic() < fence_at

    def _generation_collectible(self, claim, deadline, *, check_allocations=True) -> bool:
        key = _identity_fields(claim["reservation_id"], claim["request_id"], claim["generation"])
        try:
            row = self._disposition(key)
            debt = row["debt"]
            required = _EVIDENCE if check_allocations else _EVIDENCE[:-1]
            if not row["fenced"] or not debt or any(debt[k] is False for k in required):
                return False
            launch = self.launch_record(claim["request_id"])
            if (self.launch_owner(claim) != "gone" and
                    (not _matches(launch, key) or self.launch_terminal(claim["request_id"]) is None)):
                return False
            return not deadline.expired()
        except (LifecycleError, OSError, ValueError):
            return False

    def _prior_debt(self, reservation_id, current=None) -> bool:
        # The claim publishes its reservation-scoped index entry before the claim CAS.
        # Each immutable entry names one generation, including after rollback/re-claim.
        directory = f"disposition-index/{reservation_id}"
        try:
            for generation in self._launch_ids(directory):
                if generation == current:
                    continue
                index = self._launch_read(directory, generation)
                key = _identity_fields(reservation_id, index["request_id"], generation)
                if not _matches(index, key):
                    return True
                debt = self._disposition(key)["debt"]
                if debt and any(debt[k] is False for k in _EVIDENCE):
                    return True
        except (KeyError, TypeError, ValueError, LifecycleError, OSError):
            return True
        return False

    def _recover_allocations(self, reservation_id, deadline, *, except_generation=None) -> bool:
        try:
            return self._recover_allocations_locked(reservation_id, deadline, except_generation)
        except (LifecycleError, OSError, ValueError, KeyError, TypeError):
            return False

    def _recover_allocations_locked(self, reservation_id, deadline, except_generation) -> bool:
        if _stopped(deadline, None) or self._prior_debt(reservation_id, except_generation):
            return False
        scratch_slots = set()
        claim = self.launch_claim_record(reservation_id)
        if claim and claim.get("generation") and _RUN_ID.fullmatch(claim["run_id"]):
            scratch_slots.add(self.launch_run_dir(claim["run_id"]) / "scratch")
        for kind in ("stage", "scratch"):
            directory = kind + "-intents"
            for generation in self._launch_ids(directory):
                row = self._launch_read(directory, generation)
                if not row or row["reservation_id"] != reservation_id:
                    continue
                if kind == "scratch":
                    run = self.launch_run_dir(row["run_id"])
                    scratch_slots.update((run / generation, run / "scratch"))
                if row["phase"] != "collected":
                    if self.launch_owner(row) != "gone":
                        return False
                    if not self.collect_allocation(reservation_id, row["request_id"], generation,
                                                   kind=kind, deadline=deadline.end):
                        return False
        # Removing the run tree would otherwise unlink a replacement at the old
        # scratch pathname even after the matching inode was positively collected.
        if any(os.path.lexists(slot) for slot in scratch_slots):
            return False
        for req in self._launch_ids("implicit"):
            row = self._launch_read("implicit", req)
            if row and row["reservation_id"] == reservation_id and row["state"] == "planned":
                self._retire_planned(row, (self.launch_prepare_record(reservation_id) or {}).get("run_id"))
                self._launch_write("implicit", req, dict(row, state="retired"))
        return True

    def release(self, request: object, *, cancelled: threading.Event) -> object:
        """``PlacementLifecycle.release(request, *, cancelled) -> ReleaseResponse``. One
        deadline bounds start-up, the lock wait, bridge teardown, kill and owner listing.
        The client and id are always validated; the echo is compared once the reservation
        lock is held. When the lock is not obtained before the deadline or cancellation,
        the answer is ``cleanup_pending`` with no comparison, and nothing is released.
        When the deadline or cancellation has fired before teardown starts, nothing is
        torn down and the active record keeps the effect (``cleanup_pending``); a
        teardown already started finishes only its bounded part, and its outcome is
        recorded. An expired tombstone answers as absent (``unknown_reservation``) even
        while recovery still keeps it."""
        from .placement_process_contract import LeaseFlags, ReleaseResponse, canonical_bytes

        deadline = _Deadline.after(request.deadline_ms / 1000.0)  # type: ignore[attr-defined]
        self._startup(deadline, cancelled)
        supplied = request.reservation  # type: ignore[attr-defined]
        reservation_id = supplied.reservation_id

        def response(state: str, code: str | None, flags: object) -> object:
            return ReleaseResponse(request.request_id, reservation_id, state, code, flags,  # type: ignore[attr-defined, arg-type]
                                   request.caller_context)  # type: ignore[attr-defined]

        pending_flags = LeaseFlags(reserved=True, create_settled=True, fenced=True, cleanup_pending=True)
        if supplied.client != self.client or supplied.inventory != self.client:
            # Another client's reservation is never looked up, let alone released.
            return response("rejected", _REFUSED, self._flags(None))
        if not _ISSUED_RESERVATION.fullmatch(reservation_id):
            return response("unknown_reservation", _REFUSED, self._flags(None))
        active_path = self._dir("reservations") / f"{reservation_id}.json"
        tomb_path = self._dir("tombstones") / f"{reservation_id}.json"
        if not os.path.lexists(active_path) and self._live_tombstone(tomb_path) is None:
            return response("unknown_reservation", _REFUSED, self._flags(None))
        with self._teardown_lock(reservation_id, deadline, cancelled,
                                 echo=dict(request.reservation_json)) as held:
            if not held:
                # Another operation holds this reservation: its effect may remain.
                return response("cleanup_pending", _RELEASE_UNCONFIRMED, pending_flags)
            active = _read_journal(active_path)
            tombstone = self._live_tombstone(tomb_path) if active is None else None
            stored = active or tombstone
            if stored is None:
                return response("unknown_reservation", _REFUSED, self._flags(None))
            echo = canonical_bytes(dict(request.reservation_json))  # type: ignore[attr-defined]
            if echo != canonical_bytes(stored["reservation"]):
                # Rejected: nothing released, no flag changed, no barrier armed.
                return response("rejected", _REFUSED, self._flags(stored, tombstone=active is None))
            if active is None:
                return response("released", None, self._flags(tombstone, tombstone=True))
            if cancelled.is_set() or deadline.expired():
                # No teardown has started: the active record keeps the effect.
                return response("cleanup_pending", _RELEASE_UNCONFIRMED, pending_flags)
            if self._claimed_by_transfer(reservation_id, active):
                # Its cleanup owner removes the effect; the active record is retired.
                return response("cleanup_pending", _RELEASE_UNCONFIRMED, pending_flags)
            if not self._launch_release_gate(reservation_id, deadline, cancelled):
                # A LaneExec attempt is not terminal by the release deadline: the lease
                # stays held and nothing is torn down (``x-release-reap.release``).
                active["state"] = "cleanup_pending"
                _write_journal(active_path, active)
                return response("cleanup_pending", _RELEASE_UNCONFIRMED, self._flags(active))
            if self._cleanup(active["effect"], deadline, cancelled):  # type: ignore[arg-type]
                self._tombstone(reservation_id, active)
                return response("released", None, self._flags(active, tombstone=True))
            active["state"] = "cleanup_pending"
            _write_journal(active_path, active)
            return response("cleanup_pending", _RELEASE_UNCONFIRMED, self._flags(active))

    def _tombstone(self, reservation_id: str, active: Mapping[str, object]) -> None:
        tombstone = {"reservation": active["reservation"], "state": "released",
                     "released_at": self.clock(),
                     "tombstone_expires": self.clock() + TOMBSTONE_RETENTION_S}
        _write_journal(self._dir("tombstones") / f"{reservation_id}.json", tombstone)
        _remove_journal(self._dir("reservations") / f"{reservation_id}.json")

    def _cleanup(self, effect: Mapping[str, object], deadline: "_Deadline",
                 cancelled: threading.Event | None = None) -> bool:
        """Remove one journaled effect within the operation's deadline: its bridge (by
        handle, or by its known directory when the handle was never recorded), then its
        local slot or remote lease. True only when every part is confirmed gone. The
        caller's event reaches the bridge, whose bounded teardown it does not interrupt;
        once it is set, no further remote cleanup call starts and the effect stays owned
        as unconfirmed. Every operation passes its caller's event, the walk's rung release
        after a bridge failure included; without an event nothing cancels."""
        from .placement_bridge import operation_deadline

        cancelled = cancelled if cancelled is not None else threading.Event()
        confirmed = True
        with operation_deadline(deadline.end):
            if effect.get("bridge"):
                from .placement_bridge import BridgeHandle

                try:
                    flags = self.bridge.close(BridgeHandle.from_json(effect["bridge"]),  # type: ignore[attr-defined, arg-type]
                                              cancelled=cancelled)
                    confirmed = not flags.cleanup_pending
                except Exception:
                    confirmed = False
            elif effect.get("bridge_directory"):
                try:
                    flags = self.bridge.reclaim(str(effect["bridge_directory"]),  # type: ignore[attr-defined]
                                                cancelled=cancelled)
                    confirmed = not flags.cleanup_pending
                except Exception:
                    confirmed = False
        if effect.get("kind") == "local":
            try:
                os.unlink(self._slots_dir() / f"{effect['slot']}.json")
            except FileNotFoundError:
                pass
            except OSError:
                return False
            return confirmed
        if cancelled.is_set():
            # The bridge part has run; the remote lease is kept for a later cleanup.
            return False
        root = effect.get("root") or (effect.get("binding") or {}).get("root")  # type: ignore[union-attr]
        try:
            backend = self.backend_for(self._parsed_root(str(root), str(effect.get("target"))))
        except Exception:
            backend = None
        if backend is None:
            return False
        return self._release_remote(backend, str(effect["lease_id"]), deadline, cancelled) and confirmed

    def _release_remote(self, backend: object, lease_id: str, deadline: "_Deadline",
                        cancelled: threading.Event | None = None) -> bool:
        """Kill by lease id, then confirm the owner listing no longer names it, both within
        what is left of the operation's deadline. ``cancelled`` is checked again after the
        lease is recovered and fenced: once it is set, neither a kill nor a listing starts.
        A kill that has started is not interrupted, and the listing itself is cancellable.
        Either way the lease is unconfirmed and stays recorded."""
        from . import placement_lease

        try:
            lease = placement_lease.recover_lease(lease_id, inventory=self.inventory)
        except (OSError, ValueError):
            lease = _LeaseRef(lease_id, placement_lease.owner_id(self.inventory))
        calls = _Calls(settings=self.settings)
        try:
            lease.fence()
            if cancelled is not None and cancelled.is_set():
                # Cancelled before the kill was dispatched: none starts.
                raise PlacementUnavailable(_TIMEOUT)
            left = min(ANSWER_BOUND_S, deadline.left())
            if left <= 0:
                raise PlacementUnavailable(_TIMEOUT)
            calls.run(lambda: backend.kill(lease_id, _bound(left)), left)  # type: ignore[attr-defined]
            lease.note_killed()
            owner = lease.owner_id
            left = min(ANSWER_BOUND_S, deadline.left())
            if left <= 0:
                raise PlacementUnavailable(_TIMEOUT)
            owned = calls.run(lambda: [tuple(pair) for pair in backend.list_owned(owner, _bound(left, cancelled))],  # type: ignore[attr-defined]
                              left, cancelled)
            confirmed = all(pair[1] != lease_id for pair in owned)  # type: ignore[union-attr]
        except Exception:
            confirmed = False
        finally:
            calls.close()
        if confirmed:
            lease.clear()
        else:
            lease.abandon()
        return confirmed

    def reap(self, request: object, *, cancelled: threading.Event) -> object:
        """``PlacementLifecycle.reap(request, *, cancelled) -> ReapResponse``: only the
        selected client's inventory, eligible entries by ``created_at`` then id, all within
        one deadline. Every consumer of a reservation's effect, its active record or its
        cleanup owner, holds that reservation's lock; a consumed cleanup owner is kept as a
        destroyed completion record until its attempt journals the completion. An effect
        listed both as an active record and as a cleanup owner is one item, locked once
        and counted once, so ``max_items`` bounds distinct effects. The deadline and
        cancellation are checked before each item and again once its lock is held,
        including while its lock is awaited; an item not begun stays pending, with its
        owner unchanged."""
        from .placement_process_contract import InventoryReapResult, ReapResponse

        deadline = _Deadline.after(request.deadline_ms / 1000.0)  # type: ignore[attr-defined]
        self._startup(deadline, cancelled)
        now = self.clock()
        # One item per logical effect: ``(lock, key)`` -> [created_at, active?, owner?].
        items: dict[tuple[str, str], list[object]] = {}

        def candidate(lock: str, key: str, created: float, *, active: bool) -> None:
            item = items.setdefault((lock, key), [created, False, False])
            item[0] = min(item[0], created)  # type: ignore[type-var]
            item[1 if active else 2] = True

        unreadable = set()
        for reservation_id, entry in self._records("reservations"):
            expires = _epoch(entry.get("reservation", {}).get("expires_at"))  # type: ignore[union-attr]
            try:
                claim = self.launch_claim_record(reservation_id)
                generation = claim.get("generation") if claim and claim.get("claimed") else None
                eligible = (entry.get("state") == "cleanup_pending"
                            or generation and self.launch_owner(claim) == "gone"
                            or self._generation_reap_due(claim, expired=expires is not None and now >= expires)
                            or self._prior_debt(reservation_id, generation))
            except (KeyError, TypeError, ValueError, LifecycleError, OSError):
                unreadable.add(reservation_id)
                eligible = True
            if eligible:
                candidate("reservations", reservation_id, float(entry.get("created_at", 0.0)), active=True)
        for entry_id, entry in self._records("cleanup"):
            if entry.get("state", "owned") == "owned":
                lock = "reservations" if entry.get("lock") == "reservations" else "cleanup"
                candidate(lock, entry_id, float(entry.get("created_at", 0.0)), active=False)  # type: ignore[arg-type]
        eligible = sorted(items.items(), key=lambda item: (item[1][0], item[0][1], item[0][0]))
        examined = destroyed = pending = 0
        for (lock, key), (_created, active, owned) in eligible[: request.max_items]:  # type: ignore[attr-defined]
            if deadline.expired() or cancelled.is_set():
                pending += 1
                continue
            examined += 1
            if active and key in unreadable:
                pending += 1
                continue
            guard = (self._teardown_lock(key, deadline, cancelled, reap=True) if active
                     else self._owner_lock(key, lock, deadline, cancelled=cancelled))
            with guard as held:
                if not held or _stopped(deadline, cancelled):
                    pending += 1
                    continue
                outcome = (self._reap_active(key, deadline, cancelled, owned=bool(owned)) if active
                           else self._reap_owner(key, deadline, cancelled))
            if outcome is None or outcome:
                destroyed += 1
            else:
                pending += 1
        self._launch_sweep(deadline, cancelled)
        state = "complete" if pending == 0 else "cleanup_pending"
        result = InventoryReapResult(self.client, self.client, examined, destroyed, pending,
                                     None if pending == 0 else _RELEASE_UNCONFIRMED)
        return ReapResponse(request.request_id, state, result, request.caller_context)  # type: ignore[attr-defined]

    def _reap_active(self, reservation_id: str, deadline: "_Deadline",
                     cancelled: threading.Event | None = None, *, owned: bool = False) -> bool | None:
        """Under the reservation lock: consume an active record, unless a cleanup transfer
        owns its effect, in which case the transfer's owner is consumed instead. When the
        same effect was also listed as a cleanup owner (``owned``) and the active record is
        already gone, that owner is consumed under the same lock."""
        current = _read_journal(self._dir("reservations") / f"{reservation_id}.json")
        if current is None:
            return self._reap_owner(reservation_id, deadline, cancelled) if owned else None
        if self._claimed_by_transfer(reservation_id, current):
            return self._reap_owner(reservation_id, deadline, cancelled)
        if not self._launch_reap_gate(reservation_id, deadline, cancelled):
            current["state"] = "cleanup_pending"
            _write_journal(self._dir("reservations") / f"{reservation_id}.json", current)
            return False
        if self._cleanup(current["effect"], deadline, cancelled):  # type: ignore[arg-type]
            self._tombstone(reservation_id, current)
            return True
        current["state"] = "cleanup_pending"
        _write_journal(self._dir("reservations") / f"{reservation_id}.json", current)
        return False

    def _reap_owner(self, key: str, deadline: "_Deadline",
                    cancelled: threading.Event | None = None) -> bool | None:
        """Under the owner lock: consume one cleanup owner and keep it as a destroyed
        completion record."""
        path = self._dir("cleanup") / f"{key}.json"
        owner = _read_journal(path)
        if owner is None or owner.get("state") == "destroyed":
            return None
        if not self._cleanup(owner["effect"], deadline, cancelled):  # type: ignore[arg-type]
            return False
        owner["state"] = "destroyed"
        owner["destroyed_at"] = self.clock()
        _write_journal(path, owner)
        return True

    # -- LaneExec hooks (v13 LANEEXEC SL-3) ----------------------------------------------
    #
    # The client's LaneExec state directory is ``<inventory>/laneexec`` (binding §6 E2-4).
    # Every record there is a whole-file journal written by ``_write_journal``:
    #
    # * ``prepare/<reservation_id>.json``: the one prepare record of a reservation
    #   (``x-prepare.journal``), values assigned once;
    # * ``prepare-requests/<request_id>.json``: one prepare attempt, its retained settled
    #   response and the ``run_id`` it planned (``x-prepare.replay``);
    # * ``claims/<reservation_id>.json``: the exec claim, set and cleared only by the
    #   compare-and-set and the rollback below, under the reservation lock (L-S2);
    # * ``launches/<launch request_id>.json``: the launch record status and cancel read,
    #   holding the terminal LaunchResponse once one is written (L-S4);
    # * ``cancels/<launch request_id>.json``: local cancel outcomes journaled without a
    #   signal (L-S4);
    # * ``heartbeats/<reservation_id>.json``: the last durable local heartbeat;
    # * ``cleanup/<run_id>.json``: an uncertain prepare write left for release or reap;
    # * ``runs/<run_id>/``: the execution allocations a run owns, removed only through its
    #   record;
    # * ``returns/<reservation_id>/<run_id>/``: retained return bytes, outside ``runs/``;
    #   they outlive release and are pruned by reap once the reservation's tombstone has
    #   expired.
    #
    # The reservation's journal lock (``reservations/<id>.lock``) serializes prepare, the
    # launch steps through the claim, release and reap (``x-prepare.lock``).

    @property
    def launch_root(self) -> Path:
        """The client's LaneExec state directory, under this inventory."""
        return self.inventory / "laneexec"

    def _launch_dir(self, name: str) -> Path:
        return self.launch_root / name

    def _launch_prepare(self) -> None:
        self._prepare()
        try:
            _private_tree(self.launch_root)
            for name in _LAUNCH_DIRS:
                _private_tree(self._launch_dir(name))
                if name in ("stages", "ctl") and stat.S_IMODE(self._launch_dir(name).stat().st_mode) != 0o700:
                    os.chmod(self._launch_dir(name), 0o700)
        except OSError:
            raise LifecycleError("placement_inventory_unsafe") from None

    def _launch_ids(self, name: str) -> list[str]:
        try:
            entries = os.listdir(self._launch_dir(name))
        except FileNotFoundError:
            return []
        return [entry[:-5] for entry in sorted(entries)
                if entry.endswith(".json") and not entry.startswith(".")]

    def _launch_read(self, name: str, key: str) -> dict[str, object] | None:
        if not _LAUNCH_KEY.fullmatch(key):
            return None
        return _read_journal(self._launch_dir(name) / f"{key}.json")

    def _launch_write(self, name: str, key: str, value: Mapping[str, object]) -> None:
        if not _LAUNCH_KEY.fullmatch(key):
            raise LifecycleError("placement_internal")
        self._launch_prepare()
        _write_journal(self._launch_dir(name) / f"{key}.json", value)

    def _check_launch_lock_order(self, level: int) -> None:
        ranks = {self._launch_dir("leases"): 0, self._launch_dir("operations"): 1,
                 self._dir("reservations"): 2, self._launch_dir("requests"): 3}
        if any(ranks.get(path.parent, -1) > level for path in _HELD_LOCKS.get()):
            raise LifecycleError("placement_lock_order")

    def _generation_lock(self, directory: str, key: str, timeout_s: float) -> _FileLock:
        self._check_launch_lock_order({"leases": 0, "operations": 1, "requests": 3}[directory])
        deadline = _Deadline.after(timeout_s)
        self._launch_prepare()
        return _FileLock(self._launch_dir(directory) / (key + ".lock"), blocking=False,
                         deadline=deadline)

    def launch_request_lock(self, request_id: str, *, timeout_s: float) -> _FileLock:
        if not _LAUNCH_KEY.fullmatch(request_id):
            raise LifecycleError("placement_internal")
        return self._generation_lock("requests", request_id, timeout_s)

    def launch_lease_lock(self, reservation_id: str, *, timeout_s: float) -> _FileLock:
        if not _ISSUED_RESERVATION.fullmatch(reservation_id):
            raise LifecycleError("placement_internal")
        return self._generation_lock("leases", reservation_id, timeout_s)

    def launch_operation_lock(self, reservation_id: str, generation: str, *,
                              timeout_s: float) -> _FileLock:
        if not (_ISSUED_RESERVATION.fullmatch(reservation_id) and _GENERATION.fullmatch(generation)):
            raise LifecycleError("placement_internal")
        return self._generation_lock("operations", f"{reservation_id}.{generation}", timeout_s)

    def _holds_operation(self, rid, generation):
        return self._launch_dir("operations") / f"{rid}.{generation}.lock" in _HELD_LOCKS.get()

    def _allocation_guard(self, key, kind, deadline):
        held = _HELD_LOCKS.get()
        if (kind == "scratch" and self._dir("reservations") /
                (key["reservation_id"] + ".lock") not in held):
            raise LifecycleError("placement_lock_required")
        if self._launch_dir("requests") / (key["request_id"] + ".lock") in held:
            return nullcontext(True)
        return self.launch_request_lock(key["request_id"], timeout_s=_Deadline(deadline).left())

    def _disposition(self, key: dict) -> dict:
        row = self._launch_read("dispositions", key["generation"])
        if not _matches(row, key) or not all(type(row.get(k)) is bool for k in
                                             ("start_intent", "release_requested", "fenced")):
            raise LifecycleError("placement_journal_corrupt")
        try:
            if row["debt"] is not None:
                Debt(**row["debt"])
        except (KeyError, TypeError, ValueError):
            raise LifecycleError("placement_journal_corrupt") from None
        return row

    def _owned_claim(self, key: dict) -> dict | None:
        row = self.launch_claim_record(key["reservation_id"])
        return row if _matches(row, key) and row["claimed"] is True else None

    def mark_start_intent(self, reservation_id: str, request_id: str, generation: str, *,
                          deadline: float) -> bool:
        if not self._holds_operation(reservation_id, generation):
            raise LifecycleError("placement_lock_required")
        key = _identity_fields(reservation_id, request_id, generation)
        bound = _Deadline(deadline)
        with self.launch_lock(reservation_id, timeout_s=bound.left()) as lock:
            claim = self._owned_claim(key) if lock.held else None
            if not claim or claim["owner"] != _own_identity() or claim.get("rollback_cause"):
                return False
            code, active = lock.window(None)
            if code or not active:
                return False
            row = self._disposition(key)
            local = active["effect"]["kind"] == "local"
            if row["start_intent"] or (local and not self._renewal_current(key, row)) or bound.expired():
                return False
            row["start_intent"] = True
            self._launch_write("dispositions", generation, row)
            return (not local or self._renewal_current(key, row)) and not bound.expired()

    def read_cleanup_debt(self, reservation_id: str, request_id: str, generation: str) -> Debt | None:
        key = _identity_fields(reservation_id, request_id, generation)
        with (nullcontext(True) if self._holds_operation(reservation_id, generation) else
              self.launch_operation_lock(reservation_id, generation, timeout_s=ANSWER_BOUND_S)) as held:
            if not held:
                raise LifecycleError("placement_operation_timeout")
            if self._launch_read("dispositions", generation) is None and not self._owned_claim(key):
                return None
            row = self._disposition(key)
        return None if row["debt"] is None else Debt(**row["debt"])

    def write_cleanup_debt(self, reservation_id: str, request_id: str, generation: str, *,
                           debt: Debt, deadline: float) -> bool:
        with self.launch_operation_lock(reservation_id, generation,
                                        timeout_s=_Deadline(deadline).left()) as held:
            return held and self.write_cleanup_debt_locked(reservation_id, request_id, generation,
                                                           debt=debt, deadline=deadline)

    def write_cleanup_debt_locked(self, reservation_id: str, request_id: str, generation: str, *,
                                  debt: Debt, deadline: float) -> bool:
        row = self._disposition(_identity_fields(reservation_id, request_id, generation))
        if not self._holds_operation(reservation_id, generation):
            raise LifecycleError("placement_lock_required")
        if _monotonic() >= deadline or not isinstance(debt, Debt):
            return False
        before = row["debt"]
        if before is not None and before["cause"] != debt.cause:
            return False
        if before is not None and any(
            before[k] != getattr(debt, k) and (before[k] is not False or getattr(debt, k) is not True)
            for k in _EVIDENCE
        ):
            return False
        row["debt"] = asdict(debt)
        self._launch_write("dispositions", generation, row)
        return _monotonic() < deadline

    def _fence_locked(self, key: dict, cause: str, *, remote: bool) -> None:
        row = self._disposition(key)
        row["fenced"] = True
        row["release_requested"] |= cause == "release"
        if row["debt"] is None:
            row["debt"] = asdict(Debt(cause, False, False, False if remote else "inapplicable", False))
        self._launch_write("dispositions", key["generation"], row)

    def fence_launch(self, reservation_id: str, request_id: str, generation: str, *,
                     cause: str, deadline: float) -> bool:
        key = _identity_fields(reservation_id, request_id, generation)
        if cause not in _DEBT_CAUSES:
            return False
        bound = _Deadline(deadline)
        with self.launch_operation_lock(reservation_id, generation, timeout_s=bound.left()) as held:
            if not held:
                return False
            with self.launch_lock(reservation_id, timeout_s=bound.left()) as lock:
                if not lock.held or not self._owned_claim(key):
                    return False
                active = _read_journal(self._dir("reservations") / (reservation_id + ".json"))
                if not active:
                    return False
                self._fence_locked(key, cause, remote=active["effect"]["kind"] != "local")
                return not bound.expired()

    def _confirm_slot(self, key: dict, active: dict, count: int, attempt: int, bound: _Deadline) -> bool:
        """Only a timely, joined writer can update the confirmed renewal. A late helper
        can touch only its open slot inode and generation-specific acknowledgement."""
        effect = active["effect"]
        ttl = active.get("ttl_s")
        if ttl is None:
            # Old reserve records store an integral TTL through their truncated UTC expiry.
            ttl = int(_epoch(active["reservation"]["expires_at"]) - math.floor(active["created_at"]))
        if effect["kind"] != "local" or type(ttl) is not int or ttl <= 0:
            return False
        slot = self._slots_dir() / (effect["slot"] + ".json")
        # <generation>.<attempt> candidates use monotonic time for the lease bounds.
        # Only confirmed_attempt in the disposition selects a candidate. Store wall
        # time separately for the legacy launch_heartbeat accessor.
        row = dict(**key, heartbeat_at=_monotonic(), wall_heartbeat_at=self.clock(),
                   confirmation_count=count, ttl_s=ttl)
        def write() -> bool:
            import fcntl

            try:
                # Pin the slot before writing. Even a blocked writer cannot mutate a
                # replacement inode. Concurrent writers to the old inode are excluded.
                with open(slot, "r+b", opener=lambda path, flags: os.open(path, flags | os.O_NOFOLLOW)) as stream:
                    fd = stream.fileno()
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    existing = json.loads(os.pread(fd, _JOURNAL_MAX, 0))
                    if (existing.get("client") != self.client
                            or existing.get("reservation_id") != key["reservation_id"] or bound.expired()):
                        return False
                    data = json.dumps(dict(row, client=self.client)).encode()
                    if os.pwrite(fd, data, 0) != len(data):
                        return False
                    os.ftruncate(fd, len(data))
                    os.fsync(fd)
                    if bound.expired():
                        return False
                    # A timed-out write can publish only an unselected candidate.
                    self._launch_write("renewals", f"{key['generation']}.{attempt}", row)
                    return not bound.expired()
            except (OSError, ValueError, LifecycleError):
                return False

        calls = _Calls()
        try:
            return calls.run(write, bound.left()) is True and not bound.expired()
        except PlacementUnavailable:
            return False
        finally:
            calls.close()

    def _confirmed_renewal(self, key, disposition):
        count = disposition.get("confirmed_count")
        attempt = disposition.get("confirmed_attempt", count)
        if type(count) is not int or count < 0 or type(attempt) is not int or attempt < count:
            return None
        row = self._launch_read("renewals", f"{key['generation']}.{attempt}")
        if not (_matches(row, key) and row.get("confirmation_count") == count):
            return None
        heartbeat = row.get("heartbeat_at")
        ttl = row.get("ttl_s")
        if (type(heartbeat) not in (int, float) or not math.isfinite(heartbeat)
                or type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0):
            return None
        return row

    def renew_launch(self, reservation_id: str, request_id: str, generation: str, *,
                     deadline: float) -> bool:
        self._check_launch_lock_order(1)
        if self._holds_operation(reservation_id, generation):
            raise LifecycleError("placement_lock_order")
        bound = _Deadline(deadline)
        calls = _Calls()
        try:
            # The worker retains its locks until the durable decision is settled.
            # This also bounds the caller when the disposition journal itself stalls.
            return calls.run(lambda: self._renew_transaction(reservation_id, request_id, generation,
                                                           deadline=deadline), bound.left()) is True
        except (PlacementUnavailable, OSError, LifecycleError):
            return False
        finally:
            calls.close()

    def _renew_transaction(self, reservation_id: str, request_id: str, generation: str, *,
                           deadline: float) -> bool:
        key = _identity_fields(reservation_id, request_id, generation)
        bound = _Deadline(deadline)
        with self.launch_operation_lock(reservation_id, generation, timeout_s=bound.left()) as held:
            if not held:
                return False
            with self.launch_lock(reservation_id, timeout_s=bound.left()) as lock:
                if not lock.held or not self._owned_claim(key):
                    return False
                active = _read_journal(self._dir("reservations") / (reservation_id + ".json"))
                if (not active or active["state"] != "active" or active["effect"]["kind"] != "local"
                        or self._generation_closed(self._owned_claim(key))):
                    return False
                disposition = self._disposition(key)
                previous = self._confirmed_renewal(key, disposition)
                if not _matches(previous, key):
                    return False
                bound = _Deadline(min(deadline, _monotonic() + previous["ttl_s"] / 3,
                                      previous["heartbeat_at"] + previous["ttl_s"] * 2 / 3))
                previous_count = previous["confirmation_count"]
                previous_attempt = disposition.get("confirmed_attempt", previous_count)
                last_attempt = disposition.get("renewal_attempt")
                if "renewal_attempt" not in disposition:
                    # Old rows used the confirmation count as the candidate key.
                    # A failed legacy renewal may already have written the next key.
                    last_attempt = previous_attempt + int(disposition["debt"] is not None)
                if type(last_attempt) is not int or last_attempt < previous_attempt:
                    return False
                attempt = last_attempt + 1
                count = previous_count + 1
                # Keep cleanup debt if confirmation fails. The supervisor owns the
                # renewal fence at the lease boundary through fence_launch.
                debt = asdict(Debt("renewal_lost", False, False, "inapplicable", False))
                # Reserve a unique candidate before the writer can outlive its deadline.
                disposition.update(renewal_attempt=attempt, debt=debt)
                self._launch_write("dispositions", generation, disposition)
                if bound.expired() or not self._confirm_slot(key, active, count, attempt, bound):
                    return False
                disposition.update(confirmed_count=count, confirmed_attempt=attempt, debt=None)
                self._launch_write("dispositions", generation, disposition)
                if not bound.expired():
                    return True
                disposition.update(confirmed_count=previous_count, confirmed_attempt=previous_attempt, debt=debt)
                self._launch_write("dispositions", generation, disposition)
                return False

    def cancel_launch_owner(self, reservation_id: str, request_id: str, generation: str, *,
                            deadline: float) -> str:
        key = _identity_fields(reservation_id, request_id, generation)
        bound = _Deadline(deadline)
        try:
            with self.launch_lock(reservation_id, timeout_s=bound.left()) as lock:
                if not lock.held:
                    return "cancel_pending"
                claim = self._owned_claim(key)
                if not claim:
                    return "unknown_attempt"
                started = self._disposition(key)["start_intent"]
        except (OSError, LifecycleError):
            return "owner_unverified"
        outcome = _supervisor_cancel(self.launch_root / "ctl", key, claim, bound)
        if bound.expired():
            return "cancel_pending"
        # The supervisor exchange takes the operation lock on the server side.
        # Acquire it locally afterward, and drop the journal before calling WORKER.
        try:
            operation = (self.launch_operation_lock(reservation_id, generation, timeout_s=bound.left())
                         if started else nullcontext(True))
            with operation as held:
                if not held:
                    return "cancel_pending"
                with self.launch_lock(reservation_id, timeout_s=bound.left()) as lock:
                    if not lock.held or self._owned_claim(key) != claim:
                        return "owner_unverified"
                    # WORKER addresses a reusable attempt ID. Durable start intent
                    # rules out rollback for the generation authorizing this call.
                    row = self._disposition(key)
                    worker_allowed = started and row["start_intent"]
                    cap_to_fence = (
                        worker_allowed
                        and not row["fenced"]
                        and row.get("confirmed_count") is not None
                    )
                    fence_at = self._renewal_fence_at(key, row) if cap_to_fence else None
                if bound.expired():
                    return "cancel_pending"
                if not worker_allowed:
                    return outcome
                now = _monotonic()
                cancel_deadline = min(bound.end, now + CANCEL_WAIT_S)
                if cap_to_fence:
                    cancel_deadline = now if fence_at is None else min(cancel_deadline, fence_at)
                wait = min(CANCEL_WAIT_S, cancel_deadline - now)
                if wait <= 0:
                    return "cancel_pending"
                try:
                    worker = _invoke_launch_cancel(self.launch_cancel, claim, wait, cancel_deadline)
                except Exception:
                    return "cancel_pending"
        except (OSError, LifecycleError):
            return "owner_unverified"
        if bound.expired():
            return "cancel_pending"
        if outcome in ("cancelled", "already_terminal") and worker == "cancel_pending":
            return "cancel_pending"
        return outcome

    def record_allocation(self, reservation_id: str, request_id: str, generation: str, *,
                          kind: AllocationKind, run_id: str, owner: Owner | Mapping[str, object], basename: str,
                          file_id: tuple[int, int] | None, deadline: float) -> bool:
        key = _identity_fields(reservation_id, request_id, generation)
        if isinstance(owner, Owner):
            owner = owner._asdict()
        if (kind not in ("stage", "scratch") or not _RUN_ID.fullmatch(run_id) or generation != basename
                or not _valid_owner(owner)):
            return False
        directory = kind + "-intents"
        with self._allocation_guard(key, kind, deadline) as held:
            if not held:
                return False
            if kind == "scratch" and (self.launch_prepare_record(reservation_id) or {}).get("run_id") != run_id:
                return False
            row = self._launch_read(directory, generation)
            values = dict(**key, kind=kind, run_id=run_id, basename=basename)
            if row is None:
                if file_id is not None or dict(owner) != _own_identity():
                    return False
                row = dict(**values, owner=dict(owner), file_id=None, phase="intent")
            elif not _matches(row, values) or row["phase"] == "collected":
                return False
            else:
                # The live recorded owner alone may identify or hand off a stage.
                if row["owner"] != _own_identity() or (kind == "scratch" and owner != row["owner"]):
                    return False
                if file_id is None or any(type(x) is not int for x in file_id):
                    return False
                root = self._launch_dir("stages") if kind == "stage" else self.launch_run_dir(run_id)
                try:
                    info = (root / basename).lstat()
                except OSError:
                    return False
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o700
                        or (info.st_dev, info.st_ino) != file_id
                        or row["file_id"] not in (None, list(file_id))
                        or _landed_launch_owner({"owner": owner}) != "live"):
                    return False
                row.update(file_id=list(file_id), phase="identified", owner=dict(owner))
            self._launch_write(directory, generation, row)
            return _monotonic() < deadline

    def collect_allocation(self, reservation_id: str, request_id: str, generation: str, *,
                           kind: AllocationKind, deadline: float) -> bool:
        key = _identity_fields(reservation_id, request_id, generation)
        if kind not in ("stage", "scratch"):
            return False
        with self._allocation_guard(key, kind, deadline) as held:
            row = self._launch_read(kind + "-intents", generation) if held else None
            if not _matches(row, key) or row["basename"] != generation or not _RUN_ID.fullmatch(row["run_id"]):
                return False
            if row["phase"] == "collected":
                return True
            if row["phase"] not in ("intent", "identified"):
                return False
            gone = self.launch_owner(row) == "gone"
            if row["owner"] != _own_identity() and not gone:
                return False
            for adopter in (self._owned_claim(key), self.launch_record(request_id)):
                if (adopter and adopter.get("generation") == generation and adopter.get("owner") != row["owner"]
                        and self.launch_owner(adopter) != "gone"):
                    return False
            paths = [self._launch_dir("stages") / generation]
            if kind == "scratch":
                run = self.launch_run_dir(row["run_id"])
                paths = [run / generation, run / "scratch"]
            present = False
            for path in paths:
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                present = True
                if (row["phase"] == "identified" and [info.st_dev, info.st_ino] == row["file_id"]
                        and stat.S_ISDIR(info.st_mode)):
                    _remove_tree(path)
                    break
            else:
                if present or not gone:
                    return False
                # The owner died before mkdir, or after unlink but before recording
                # collection. Re-establish durability of the observed absence.
                parent = paths[0].parent
                try:
                    _fsync_directory(parent)
                except FileNotFoundError:
                    # A removed run parent also proves absence of both scratch aliases.
                    _fsync_directory(parent.parent)
            row["phase"] = "collected"
            self._launch_write(kind + "-intents", generation, row)
            return _monotonic() < deadline

    def launch_return_dir(self, reservation_id: str, run_id: str, *,
                          timeout_s: float = ANSWER_BOUND_S) -> Path:
        """``returns/<reservation_id>/<run_id>``: where a run's retained return bytes live,
        the ``return_dir`` that ``launch_return.collect_return`` takes. Its parent
        ``returns/<reservation_id>`` is provisioned 0700 under the reservation lock while
        the reservation is held; the run directory itself is SL-2's to create. It is
        outside ``runs/``, so release and reap of the execution allocations never remove
        it; it outlives release until the reservation's tombstone expires
        (``x-release-reap.release``), when reap's sweep removes it. A caller already holding
        the lock uses :meth:`ReservationLock.return_dir`."""
        with self.launch_lock(reservation_id, timeout_s=timeout_s) as lock:
            if not lock.held:
                raise LifecycleError(_TIMEOUT)
            return lock.return_dir(run_id)

    def _return_dir_locked(self, reservation_id: str, run_id: str) -> Path:
        if not _ISSUED_RESERVATION.fullmatch(reservation_id) or not _RUN_ID.fullmatch(run_id):
            raise LifecycleError("placement_internal")
        if not os.path.lexists(self._dir("reservations") / f"{reservation_id}.json"):
            # A reservation no longer held is swept; nothing is provisioned for it.
            raise LifecycleError("placement_internal")
        parent = self._launch_dir("returns") / reservation_id
        self._launch_prepare()
        try:
            _private_tree(parent)
        except OSError:
            raise LifecycleError("placement_inventory_unsafe") from None
        return parent / run_id

    def launch_run_dir(self, run_id: str) -> Path:
        """``runs/<run_id>``: the directory that owns a run's local allocations."""
        if not _RUN_ID.fullmatch(run_id):
            raise LifecycleError("placement_internal")
        return self._launch_dir("runs") / run_id

    def launch_prepare_record(self, reservation_id: str) -> dict[str, object] | None:
        return self._launch_read("prepare", reservation_id)

    def launch_claim_record(self, reservation_id: str) -> dict[str, object] | None:
        return self._launch_read("claims", reservation_id)

    def launch_record(self, request_id: str) -> dict[str, object] | None:
        """The LaneExec launch record of one launch ``request_id``, if any."""
        return self._launch_read("launches", request_id)

    def write_launch_record(self, request_id: str, value: Mapping[str, object]) -> None:
        """Durably replace the launch record of ``request_id`` (the launch order's own
        record: reservation id, run id, paths, claim state and counters)."""
        self._launch_write("launches", request_id, dict(value))

    def write_launch_terminal(self, request_id: str, response: object) -> None:
        """Journal LaneExec's terminal LaunchResponse in the launch record before it is
        returned (L-S4). The bytes are the strict encoding; status replays them."""
        from .launch_process_contract import encode_launch_response

        record = self.launch_record(request_id)
        if record is None:
            raise LifecycleError("placement_internal")
        record["terminal"] = encode_launch_response(response).decode("utf-8")  # type: ignore[arg-type]
        self._launch_write("launches", request_id, record)

    def launch_terminal(self, request_id: str) -> object:
        """The terminal LaunchResponse journaled for ``request_id``, or None."""
        from .launch_process_contract import decode_launch_response, encode_launch_response

        record = self.launch_record(request_id)
        raw = None if record is None else record.get("terminal")
        if raw is None:
            return None
        try:
            data = str(raw).encode("utf-8")
            response = decode_launch_response("launch", data)
        except Exception:
            raise LifecycleError("placement_journal_corrupt") from None
        if (encode_launch_response(response) != data or response.request_id != request_id
                or response.reservation_id != record.get("reservation_id")):
            raise LifecycleError("placement_journal_corrupt")
        return response

    def journal_local_cancel(self, request_id: str, outcome: str, *, deadline: _Deadline | None = None) -> None:
        """Append one zero-signal cancel outcome for a launch (L-S4); never a success."""
        deadline = deadline or _Deadline.after(ANSWER_BOUND_S)
        self._launch_prepare()
        with _FileLock(self._launch_dir("cancels") / f"{request_id}.lock", blocking=False,
                       deadline=deadline) as held:
            if not held:
                raise LifecycleError("placement_operation_timeout")
            current = self._launch_read("cancels", request_id) or {"request_id": request_id,
                                                                   "outcomes": []}
            outcomes = current.get("outcomes")
            if current.get("request_id") != request_id or not isinstance(outcomes, list):
                raise LifecycleError("placement_journal_corrupt")
            outcomes.append({"outcome": str(outcome), "at": self.clock()})
            self._launch_write("cancels", request_id, {"request_id": request_id,
                                                       "outcomes": outcomes})

    def launch_local_cancels(self, request_id: str) -> list[str]:
        record = self._launch_read("cancels", request_id) or {}
        return [str(item.get("outcome")) for item in record.get("outcomes") or []]  # type: ignore[union-attr]

    def launch_lock(self, reservation_id: str, *, timeout_s: float,
                    cancelled: threading.Event | None = None) -> "ReservationLock":
        """The reservation's journal lock, waited on for at most ``timeout_s``. Use as a
        context manager and check ``held``."""
        return ReservationLock(self, reservation_id, _Deadline.after(timeout_s), cancelled)

    def _launch_window(self, reservation_id: str, echo: Mapping[str, object] | None
                       ) -> tuple[str | None, dict[str, object] | None]:
        """Under the reservation lock: whether the reservation is held, unexpired, not
        fenced and equal to ``echo`` field by field (``x-launch-inputs.reservation_echo``).
        Returns ``(code, active record)``; the code is None when the window is open."""
        from .placement_process_contract import canonical_bytes

        if not _ISSUED_RESERVATION.fullmatch(reservation_id):
            return _LAUNCH_UNKNOWN, None
        active = _read_journal(self._dir("reservations") / f"{reservation_id}.json")
        if active is None or active.get("state") == "cleanup_pending":
            return _LAUNCH_UNKNOWN, None
        reservation = active.get("reservation")
        if not isinstance(reservation, dict):
            raise LifecycleError("placement_journal_corrupt")
        expires = _epoch(reservation.get("expires_at"))
        if expires is None or self.clock() >= expires:
            return _LAUNCH_UNKNOWN, None
        if (reservation.get("client") != self.client or reservation.get("inventory") != self.client):
            return _LAUNCH_UNKNOWN, None
        if echo is not None and canonical_bytes(dict(echo)) != canonical_bytes(reservation):
            return _LAUNCH_MISMATCH, active
        claim = self.launch_claim_record(reservation_id)
        if (self._generation_closed(claim) or
                self._prior_debt(reservation_id, (claim or {}).get("generation") if claim and claim.get("claimed") else None)):
            return _LAUNCH_UNKNOWN, active
        return None, active

    def _generation_closed(self, claim) -> bool:
        if not claim or not claim.get("claimed") or "generation" not in claim:
            return False
        try:
            row = self._disposition(_identity_fields(claim["reservation_id"], claim["request_id"],
                                                     claim["generation"]))
            return self._disposition_closed(row)
        except (LifecycleError, OSError, TypeError, ValueError, KeyError):
            return True

    @staticmethod
    def _disposition_closed(row: dict) -> bool:
        debt = row["debt"]
        return row["fenced"] or row["release_requested"] or (debt is not None and debt["cause"] != "renewal_lost")

    def _launch_claimed(self, entry: Mapping[str, object]) -> bool:
        """Whether a LaneExec claim is held on the reservation an active entry names."""
        try:
            reservation_id = str(entry["reservation"]["reservation_id"])  # type: ignore[index]
            claim = self.launch_claim_record(reservation_id)
        except (KeyError, TypeError, LifecycleError, OSError):
            return False
        return bool(claim and claim.get("claimed") is True)

    def _claim_locked(self, reservation_id: str, request_id: str, run_id: str,
                      owner: Mapping[str, object] | None, generation: str | None = None,
                      deadline: _Deadline | None = None) -> str | None:
        """The exec claim's compare-and-set; the caller holds the reservation lock. One
        durable write sets the claim (``LeaseFlags.exec_claimed``) and records the launch
        ``request_id``; it never touches the worker JOURNAL (L-S2)."""
        if not _LAUNCH_KEY.fullmatch(request_id) or not _RUN_ID.fullmatch(run_id):
            raise LifecycleError("placement_internal")
        code, _active = self._launch_window(reservation_id, None)
        if code is not None:
            return code
        current = self.launch_claim_record(reservation_id)
        if current is not None and current.get("claimed") is not False:
            return _LAUNCH_CLAIMED
        identity = (owner._asdict() if isinstance(owner, Owner) else
                    dict(owner) if owner is not None else _own_identity())
        if not _valid_owner(identity):
            # A claim is committed only with an owner reap can later verify: without a
            # readable start identity nothing is written and the claim is refused.
            return _CAPABILITY_UNMET
        fields = {}
        if generation is not None:
            key = _identity_fields(reservation_id, request_id, generation)
            if (self._launch_read("dispositions", generation) is not None
                    or _landed_launch_owner({"owner": identity}) != "live"):
                return _CAPABILITY_UNMET
            if _active["effect"]["kind"] == "local":
                if not self._confirm_slot(key, _active, 0, 0, deadline or _Deadline.after(ANSWER_BOUND_S)):
                    # No claim selected this candidate. A late writer can touch
                    # only its pinned slot and its unselected renewal record.
                    return _CAPABILITY_UNMET
            self._launch_write("dispositions", generation, {
                **key, "fenced": False, "start_intent": False, "release_requested": False, "debt": None,
                "confirmed_count": 0 if _active["effect"]["kind"] == "local" else None})
            index = self._launch_dir("disposition-index") / reservation_id
            _private_tree(index)
            _fsync_directory(index.parent)
            _write_journal(index / (generation + ".json"), key)
            fields = {**key, "rollback_cause": None,
                      "completed_rollback": (current or {}).get("completed_rollback")}
        self._launch_write("claims", reservation_id, {
            **fields,
            "reservation_id": reservation_id, "request_id": request_id, "run_id": run_id,
            "claimed": True, "claimed_at": self.clock(),
            "owner": identity,
            "rolled_back": list((current or {}).get("rolled_back") or []),  # type: ignore[arg-type]
        })
        return None

    def _rollback_locked(self, reservation_id: str, request_id: str, generation: str | None = None) -> bool:
        """``x-exec.claim_rollback``: one durable write that clears the claim and journals
        ``claim_rolled_back`` for that launch ``request_id``. Only the claim that request
        took is cleared."""
        current = self.launch_claim_record(reservation_id)
        if current is None or current.get("claimed") is not True or current.get("request_id") != request_id:
            return False
        if current.get("generation") != generation:
            return False
        if generation is not None:
            if current["owner"] != _own_identity():
                return False
            row = self._disposition(_identity_fields(reservation_id, request_id, generation))
            # Once start intent is durable, WORKER may be addressing this attempt ID.
            if (row["start_intent"] or current.get("rollback_cause") not in _ROLLBACK_CAUSES
                    or row["fenced"] or row["debt"] is not None):
                return False
            current["completed_rollback"] = dict(request_id=request_id, generation=generation,
                                                 cause=current["rollback_cause"])
        current["claimed"] = False
        current["rolled_back"] = [*list(current.get("rolled_back") or []), request_id]  # type: ignore[arg-type]
        current["rolled_back_at"] = self.clock()
        self._launch_write("claims", reservation_id, current)
        return True

    def claim_exec(self, reservation_id: str, request_id: str, run_id: str, *,
                   timeout_s: float, owner: Mapping[str, object] | None = None,
                   cancelled: threading.Event | None = None) -> str | None:
        """Take the exec claim under the reservation lock. None when claimed, else the
        refusal code (``sandbox_launch_exec_claimed`` for a held claim)."""
        with self.launch_lock(reservation_id, timeout_s=timeout_s, cancelled=cancelled) as lock:
            if not lock.held:
                return _TIMEOUT
            return lock.claim(request_id, run_id, owner=owner)

    def rollback_claim(self, reservation_id: str, request_id: str, *, timeout_s: float) -> bool:
        with self.launch_lock(reservation_id, timeout_s=timeout_s) as lock:
            return bool(lock.held) and lock.rollback(request_id)

    def record_heartbeat(self, reservation_id: str, request_id: str) -> bool:
        """The local durable heartbeat (``x-lifetime.liveness``): the slot heartbeat, then
        the journal heartbeat. True only when both writes completed for the claim this
        launch holds. A removed slot is never recreated, so a released reservation can
        never be confirmed; any failure is reported, never swallowed."""
        try:
            claim = self.launch_claim_record(reservation_id)
            if (claim is None or claim.get("claimed") is not True
                    or claim.get("request_id") != request_id or claim.get("generation") is not None):
                return False
            active = _read_journal(self._dir("reservations") / f"{reservation_id}.json")
            effect = (active or {}).get("effect") or {}
            if effect.get("kind") != "local" or not isinstance(effect.get("slot"), str):  # type: ignore[union-attr]
                return False
            now = self.clock()
            slot = self._slots_dir() / f"{effect['slot']}.json"  # type: ignore[index]
            data = json.dumps({"client": self.client, "reservation_id": reservation_id,
                               "request_id": request_id, "heartbeat_at": now},
                              sort_keys=True, separators=(",", ":")).encode("utf-8")
            fd = os.open(slot, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                os.ftruncate(fd, 0)
                view = memoryview(data)
                while view:
                    view = view[os.pwrite(fd, view, len(data) - len(view)):]
                os.fsync(fd)
            finally:
                os.close(fd)
            self._launch_write("heartbeats", reservation_id, {
                "reservation_id": reservation_id, "request_id": request_id, "heartbeat_at": now})
        except (OSError, LifecycleError):
            return False
        return True

    def launch_heartbeat(self, reservation_id: str) -> float | None:
        claim = self.launch_claim_record(reservation_id)
        if claim and claim.get("generation") is not None and claim.get("claimed"):
            key = _identity_fields(reservation_id, claim["request_id"], claim["generation"])
            record = self._confirmed_renewal(key, self._disposition(key))
            value = (record or {}).get("wall_heartbeat_at")
            if record and value is None:
                # Earlier generation rows stored only monotonic time. The claim
                # provides a durable wall-clock anchor for the initial confirmation.
                initial = self._confirmed_renewal(key, {"confirmed_count": 0})
                if (initial and type(initial.get("heartbeat_at")) in (int, float)
                        and type(record.get("heartbeat_at")) in (int, float)
                        and type(claim.get("claimed_at")) in (int, float)):
                    value = claim["claimed_at"] + (record["heartbeat_at"] - initial["heartbeat_at"])
        else:
            record = self._launch_read("heartbeats", reservation_id)
            value = (record or {}).get("heartbeat_at")
        return float(value) if type(value) in (int, float) else None  # type: ignore[arg-type]

    # -- LaneExec prepare (``x-prepare``) -------------------------------------------------
    def launch_prepare(self, request: object, *, caps_readable: bool) -> object:
        """``x-prepare``: assign ``run_id``, ``scratch_path`` and ``tree_path`` once per
        reservation, journaled under the reservation lock before the response; replay as
        ``x-prepare.replay``. Raises :class:`LifecycleError` for an internal failure."""
        from .placement_process_contract import canonical_bytes

        self._launch_prepare()
        self._launch_startup(None, None)
        body_sha256 = hashlib.sha256(canonical_bytes(request.to_json())).hexdigest()  # type: ignore[attr-defined]
        request_id = request.request_id  # type: ignore[attr-defined]
        directory = self._launch_dir("prepare-requests")
        with _FileLock(directory / f"{request_id}.lock", blocking=False) as held:
            record = _read_journal(directory / f"{request_id}.json")
            if record is not None and record.get("body_sha256") != body_sha256:
                # Same request_id, another body: refused, and nothing is created or journaled.
                return self._prepare_response(request, "refused", _LAUNCH_REFUSED)
            if record is not None and record.get("settled"):
                return self._stored_prepare(record)
            if not held:
                return self._prepare_response(request, "timeout", _TIMEOUT)
            if record is not None:
                # Step 3, then step 4: the clock is read before the journal.
                if self._at_bound(record, self.clock()):
                    return self._settle_prepare_end_reached(record)
                if not caps_readable:
                    # Gated before any reservation read or allocation; a run the attempt
                    # already planned stays owned through a cleanup entry.
                    self._retire_planned(record, None)
                    return self._settle_prepare(record, self._prepare_response(
                        request, "refused", PREPARE_CAPS_UNREADABLE_CODE))
                return self._prepare_locked(request, record)
            record = {
                "request_id": request_id, "body_sha256": body_sha256,
                "reservation_id": request.reservation.reservation_id,  # type: ignore[attr-defined]
                "caller_context": dict(request.caller_context),  # type: ignore[attr-defined]
                "started_at": self.clock(), "deadline_ms": PREPARE_DEADLINE_MS,
                "settled": False, "run_id": None,
            }
            self._launch_write("prepare-requests", request_id, record)
            if not caps_readable:
                # Coordinator ruling 1: an unreadable caps record refuses prepare.
                return self._settle_prepare(record, self._prepare_response(
                    request, "refused", PREPARE_CAPS_UNREADABLE_CODE))
            return self._prepare_locked(request, record)

    def _prepare_response(self, request: object, state: str, code: str | None,
                          paths: Mapping[str, object] | None = None) -> object:
        from .launch_process_contract import PreparedPaths, PrepareResponse

        if isinstance(request, Mapping):
            request_id, reservation_id = str(request["request_id"]), str(request["reservation_id"])
            context = request.get("caller_context") or {}
        else:
            request_id = request.request_id  # type: ignore[attr-defined]
            reservation_id = request.reservation.reservation_id  # type: ignore[attr-defined]
            context = request.caller_context  # type: ignore[attr-defined]
        values = None if paths is None else PreparedPaths(
            str(paths["run_id"]), str(paths["scratch_path"]), str(paths["tree_path"]))
        return PrepareResponse(request_id, reservation_id, state, code, values,
                               dict(context))  # type: ignore[arg-type]

    def _settle_prepare(self, record: dict[str, object], response: object) -> object:
        from .launch_process_contract import encode_launch_response, launch_exit_class

        record["settled"] = True
        record["response"] = encode_launch_response(response).decode("utf-8")  # type: ignore[arg-type]
        record["exit"] = launch_exit_class(response)  # type: ignore[arg-type]
        self._launch_write("prepare-requests", str(record["request_id"]), record)
        return response

    def _stored_prepare(self, record: Mapping[str, object]) -> object:
        from .launch_process_contract import decode_launch_response, encode_launch_response
        from .placement_process_contract import ProtocolError

        raw = str(record.get("response", "")).encode("utf-8")
        try:
            response = decode_launch_response("prepare", raw)
        except ProtocolError:
            raise LifecycleError("placement_journal_corrupt") from None
        if encode_launch_response(response) != raw:
            raise LifecycleError("placement_journal_corrupt")
        return response

    def _retire_planned(self, record: Mapping[str, object], winning_run: object) -> None:
        """Durably hand the ``run_id`` an attempt planned, when it is not the run the
        reservation's prepare record names, to a cleanup entry for that reservation, so
        release or reap removes its allocation. Written before the attempt settles."""
        run_id = record.get("run_id")
        if isinstance(run_id, str) and _RUN_ID.fullmatch(run_id) and run_id != winning_run:
            self._launch_write("cleanup", run_id, {
                "reservation_id": record.get("reservation_id"), "run_id": run_id,
                "request_id": record.get("request_id"), "created_at": self.clock()})

    def _settle_prepare_end_reached(self, record: dict[str, object]) -> object:
        """Step 3: settle terminally (``timeout``, ``sandbox_placement_end_reached``,
        paths null, exit 20) and turn the attempt's uncertain prepare write, the
        ``run_id`` it planned, into a cleanup entry for that reservation and run id."""
        self._retire_planned(record, None)
        return self._settle_prepare(record, self._prepare_response(record, "timeout", _END_REACHED))

    def _launch_startup(self, deadline: "_Deadline | None",
                        cancelled: threading.Event | None) -> None:
        """Lifecycle start-up for LaneExec: step 3 applied to every unsettled prepare
        attempt at its bound. Locks are only tried; a held attempt is left for later."""
        directory = self._launch_dir("prepare-requests")
        for request_id in self._launch_ids("prepare-requests"):
            if _stopped(deadline, cancelled):
                return
            with self._try_lock(directory / f"{request_id}.lock", deadline) as held:
                if not held:
                    continue
                try:
                    record = _read_journal(directory / f"{request_id}.json")
                except LifecycleError:
                    continue
                if record is not None and not record.get("settled") and self._at_bound(record, self.clock()):
                    self._settle_prepare_end_reached(record)

    def _prepare_locked(self, request: object, record: dict[str, object]) -> object:
        """Steps 4 and 5 for a replay, and the whole of a fresh prepare: one read of the
        reservation's journal under its lock. A lock not obtained, or a journal that
        cannot be read, is indeterminate: nothing is journaled and the answer is
        ``timeout``/``sandbox_placement_operation_timeout``."""
        reservation_id = request.reservation.reservation_id  # type: ignore[attr-defined]
        echo = request.reservation_json or request.reservation.to_json()  # type: ignore[attr-defined]
        left = float(record["started_at"]) + PREPARE_DEADLINE_MS / 1000.0 - self.clock()  # type: ignore[arg-type]
        wait = max(_PREPARE_MIN_WAIT_S, min(left, ANSWER_BOUND_S))
        with self.launch_lock(reservation_id, timeout_s=wait) as lock:
            if not lock.held:
                return self._prepare_response(request, "timeout", _TIMEOUT)
            try:
                code, active = lock.window(echo)
                claim = None if code is not None else self.launch_claim_record(reservation_id)
                existing = None if code is not None else self.launch_prepare_record(reservation_id)
            except (LifecycleError, OSError):
                return self._prepare_response(request, "timeout", _TIMEOUT)
            winning = None if existing is None else existing.get("run_id")
            if code is not None:
                self._retire_planned(record, winning)
                return self._settle_prepare(record, self._prepare_response(request, "refused", code))
            if claim is not None and claim.get("claimed") is not False:
                self._retire_planned(record, winning)
                return self._settle_prepare(record, self._prepare_response(request, "refused",
                                                                           _LAUNCH_CLAIMED))
            snapshot_root = request.snapshot_root  # type: ignore[attr-defined]
            if existing is not None:
                # Another attempt published the reservation's run: this attempt's planned
                # run, if any, is not it and passes to cleanup under this lock.
                self._retire_planned(record, winning)
                if existing.get("snapshot_root") != snapshot_root:
                    return self._settle_prepare(record, self._prepare_response(
                        request, "refused", _LAUNCH_INPUT_MISMATCH))
                return self._settle_prepare(record, self._prepare_response(
                    request, "prepared", None, existing))
            kind = ((active or {}).get("reservation") or {}).get("target", {}).get("kind")  # type: ignore[union-attr]
            if kind not in ("local", "openshell"):
                self._retire_planned(record, None)
                return self._settle_prepare(record, self._prepare_response(
                    request, "refused", _LAUNCH_REFUSED))
            try:
                run_id = record.get("run_id")
                if not (isinstance(run_id, str) and _RUN_ID.fullmatch(run_id)):
                    # The run id is journaled in the attempt before anything is allocated,
                    # so no replay of this attempt ever assigns a second one.
                    run_id = f"run-{self.new_id()}"
                    if not _RUN_ID.fullmatch(run_id):
                        raise LifecycleError("placement_internal")
                    record["run_id"] = run_id
                    self._launch_write("prepare-requests", str(record["request_id"]), record)
                values = self._publish_prepare(reservation_id, record["request_id"], kind, run_id,
                                               snapshot_root)
            except OSError:
                raise LifecycleError("placement_internal") from None
            return self._settle_prepare(record, self._prepare_response(request, "prepared", None, values))

    def _publish_prepare(self, reservation_id, request_id, kind, run_id, snapshot_root):
        paths = self._prepared_paths(kind, run_id, snapshot_root)
        _private_tree(self.launch_run_dir(run_id))
        _fsync_directory(self._launch_dir("runs"))
        values = dict(reservation_id=reservation_id, request_id=request_id, target_kind=kind,
                      snapshot_root=snapshot_root, created_at=self.clock(), **paths)
        self._launch_write("prepare", reservation_id, values)
        return values

    def _prepared_paths(self, kind: str, run_id: str, snapshot_root: str) -> dict[str, str]:
        """``x-prepare.values``: openshell ``/work/<run_id>/scratch`` and ``/work/<run_id>/fs``
        followed by ``snapshot_root``; local, the run's private scratch directory and
        ``snapshot_root`` (the local ``tree_dest``)."""
        if kind == "openshell":
            base = f"/work/{run_id}"
            return {"run_id": run_id, "scratch_path": f"{base}/scratch",
                    "tree_path": f"{base}/fs{snapshot_root}"}
        return {"run_id": run_id, "scratch_path": str(self.launch_run_dir(run_id) / "scratch"),
                "tree_path": snapshot_root}

    # -- LaneExec release and reap (``x-release-reap``) -----------------------------------
    def _launch_terminal_present(self, request_id: object) -> bool:
        if not isinstance(request_id, str):
            return False
        record = self.launch_record(request_id)
        return record is not None and record.get("terminal") is not None

    def _launch_cancel_owner(self, claim: Mapping[str, object], deadline: _Deadline) -> str | None:
        """Cancel the claimed attempt through its verified owning launcher only, and
        journal a zero-signal outcome locally (L-S4)."""
        from .launch_return import map_cancel

        try:
            outcome = self.launch_cancel(claim, max(_POLL_S, min(deadline.left(), CANCEL_WAIT_S)))
        except Exception:
            outcome = None
        mapping = map_cancel(outcome if isinstance(outcome, str) else None,
                             record_present=True, claim_held=True)
        if mapping.local_outcome is not None and isinstance(claim.get("request_id"), str):
            try:
                self.journal_local_cancel(str(claim["request_id"]), mapping.local_outcome, deadline=deadline)
            except (OSError, LifecycleError):
                pass
        return outcome if isinstance(outcome, str) else None

    def _launch_release_gate(self, reservation_id: str, deadline: "_Deadline",
                             cancelled: threading.Event | None) -> bool:
        """Under the reservation lock, before release tears anything down. A held claim
        whose launch has no terminal record is cancelled first through the verified owner;
        release then waits for the terminal within its deadline. True when teardown may
        proceed, after the run's allocations (prepare record, run directory, cleanup
        entries) are removed; False leaves everything in place (``cleanup_pending``)."""
        claim = self.launch_claim_record(reservation_id)
        if claim and claim.get("claimed") and claim.get("generation"):
            if not self._generation_collectible(claim, deadline):
                return False
        elif claim is not None and claim.get("claimed") is True:
            request_id = claim.get("request_id")
            if not self._launch_terminal_present(request_id):
                self._launch_cancel_owner(claim, deadline)
                while not self._launch_terminal_present(request_id):
                    if _stopped(deadline, cancelled):
                        return False
                    _sleep(min(_POLL_S, deadline.left()))
        if not self._recover_allocations(reservation_id, deadline):
            return False
        self._remove_launch_allocations(reservation_id)
        return True

    def _launch_reap_gate(self, reservation_id: str, deadline: "_Deadline",
                          cancelled: threading.Event | None) -> bool:
        """Under the reservation lock, before reap tears anything down. A held claim with
        no terminal record is settled only when its owning launcher is verifiably gone:
        it is cancelled through the verified owner and marked reaped, and reap never
        writes or replaces a LaunchResponse. A live or unverified owner keeps everything."""
        claim = self.launch_claim_record(reservation_id)
        if claim and claim.get("claimed") and claim.get("generation"):
            if not self._generation_collectible(claim, deadline):
                return False
        elif (claim is not None and claim.get("claimed") is True
                and not self._launch_terminal_present(claim.get("request_id"))
                and claim.get("reaped_at") is None):
            try:
                owner = self.launch_owner(claim)
            except Exception:
                owner = "unverified"
            if owner != "gone" or _stopped(deadline, cancelled):
                return False
            self._launch_cancel_owner(claim, deadline)
            claim["reaped_at"] = self.clock()
            self._launch_write("claims", reservation_id, claim)
        if not self._recover_allocations(reservation_id, deadline):
            return False
        self._remove_launch_allocations(reservation_id)
        return True

    def _remove_launch_allocations(self, reservation_id: str) -> None:
        """``x-prepare.cleanup`` under the reservation lock: the prepare record and the
        allocations owned by this reservation's run ids (its prepare record's, its claim's
        and its cleanup entries'). Nothing of another run id is touched."""
        run_ids: list[str] = []
        prepare = self.launch_prepare_record(reservation_id)
        claim = self.launch_claim_record(reservation_id)
        for source in (prepare, claim):
            if source is not None and isinstance(source.get("run_id"), str):
                run_ids.append(str(source["run_id"]))
        entries = []
        for key in self._launch_ids("cleanup"):
            entry = self._launch_read("cleanup", key)
            if entry is not None and entry.get("reservation_id") == reservation_id:
                entries.append(key)
                run_ids.append(str(entry.get("run_id")))
        for run_id in dict.fromkeys(run_ids):
            if _RUN_ID.fullmatch(run_id):
                _remove_tree(self.launch_run_dir(run_id))
        for key in entries:
            _remove_journal(self._launch_dir("cleanup") / f"{key}.json")
        _remove_journal(self._launch_dir("prepare") / f"{reservation_id}.json")

    def _launch_sweep(self, deadline: "_Deadline", cancelled: threading.Event | None) -> None:
        """Reap, caller-scoped: cleanup entries and prepare records of reservations this
        inventory no longer holds (no active record) are removed under that reservation's
        lock, and so are retained returns once that reservation's tombstone has expired.
        Launch, claim and cancel records stay for status."""
        reservation_ids = {str((self._launch_read("cleanup", key) or {}).get("reservation_id"))
                           for key in self._launch_ids("cleanup")}
        reservation_ids |= set(self._launch_ids("prepare"))
        for name in ("stage-intents", "scratch-intents", "implicit"):
            for key in self._launch_ids(name):
                row = self._launch_read(name, key)
                if row and (row.get("phase") in ("intent", "identified") or row.get("state") == "planned"):
                    reservation_ids.add(str(row["reservation_id"]))
        for reservation_id in sorted(reservation_ids):
            if _stopped(deadline, cancelled) or not _ISSUED_RESERVATION.fullmatch(reservation_id):
                continue
            if os.path.lexists(self._dir("reservations") / f"{reservation_id}.json"):
                continue
            with self._try_lock(self._dir("reservations") / f"{reservation_id}.lock", deadline) as held:
                if (held and not os.path.lexists(self._dir("reservations") / f"{reservation_id}.json")
                        and self._recover_allocations(reservation_id, deadline)):
                    self._remove_launch_allocations(reservation_id)
        try:
            retained = sorted(os.listdir(self._launch_dir("returns")))
        except FileNotFoundError:
            retained = []
        for reservation_id in retained:
            if _stopped(deadline, cancelled) or not _ISSUED_RESERVATION.fullmatch(reservation_id):
                continue
            with self._try_lock(self._dir("reservations") / f"{reservation_id}.lock", deadline) as held:
                if (held and not os.path.lexists(self._dir("reservations") / f"{reservation_id}.json")
                        and self._live_tombstone(self._dir("tombstones") / f"{reservation_id}.json") is None):
                    _remove_tree(self._launch_dir("returns") / reservation_id)


class _RequestEcho(NamedTuple):
    """What a response echoes of the request it answers, rebuilt from the journal."""

    request_id: str
    caller_context: Mapping[str, object]


class _LeaseRef:
    """A lease known only by id (its journal entry is gone): kill and list still work."""

    def __init__(self, lease_id: str, owner_id: str = "") -> None:
        self.lease_id, self.owner_id = lease_id, owner_id

    def fence(self) -> None:
        pass

    def note_killed(self) -> None:
        pass

    def clear(self) -> None:
        pass

    def abandon(self) -> None:
        pass


class _ReserveWalk:
    """The walk's hooks for one reserve attempt: per-target requests, journaled leases and
    the host-wide local slot registry."""

    def __init__(self, lifecycle: PlacementLifecycle, request: object, record: dict[str, object],
                 plans: Mapping[str, _TargetPlan], bindings: Mapping[str, dict[str, object]],
                 thresholds: object) -> None:
        self.lifecycle, self.request, self.record = lifecycle, request, record
        self.plans, self.bindings, self.thresholds = plans, bindings, thresholds
        self._journal_lock = threading.Lock()

    def _note_pending(self, effect: dict[str, object]) -> None:
        with self._journal_lock:
            pending = list(self.record.get("pending") or [])  # type: ignore[arg-type]
            pending.append(effect)
            self.record["pending"] = pending
            _write_journal(self.lifecycle._dir("attempts") / f"{self.record['request_id']}.json", self.record)

    def request_for(self, root: object) -> PlacementRequest:
        plan = self.plans[getattr(root, "name", "")]
        if plan.refusal is not None:
            raise PlacementUnavailable(plan.refusal)
        return PlacementRequest(
            leg=str(self.request.request_id), round_id=str(self.record["reservation_id"]),  # type: ignore[attr-defined]
            repo="", snapshot_sha256="", deadline_s=float(self.request.ttl_s),  # type: ignore[attr-defined]
            egress_needs=EgressNeeds(), workload=self.request.workload,  # type: ignore[attr-defined]
            _mapping=_LIFECYCLE_SEAL,
        )

    def open_lease(self, name: str | None, root: object) -> object:
        from . import placement_lease

        lease = placement_lease.open_lease(name, root, inventory=self.lifecycle.inventory)
        try:
            self._note_pending({"kind": "remote", "target": name, "lease_id": lease.lease_id,
                                "binding": self.bindings[str(name)]})
        except BaseException:
            lease.clear()
            raise
        return lease

    def local_preflight(self, label: str) -> str | None:
        return self.plans[label].refusal

    def _reading(self) -> LocalHeadroom:
        values = self.lifecycle.observe()
        live = len([name for name in os.listdir(self.lifecycle._slots_dir())
                    if name.endswith(".json") and not name.startswith(".")])
        return LocalHeadroom(
            memory_available_bytes=values.get("memory_available_bytes"),  # type: ignore[arg-type]
            load_per_cpu_percent=values.get("load_per_cpu_percent"),  # type: ignore[arg-type]
            live_sandboxes=live, observed_monotonic=_monotonic(),
            memory_total_bytes=values.get("memory_total_bytes"),  # type: ignore[arg-type]
            io_full_avg10=values.get("io_full_avg10"),  # type: ignore[arg-type]
            memory_some_avg10=values.get("memory_some_avg10"),  # type: ignore[arg-type]
        )

    def local_capacity(self) -> LocalHeadroom:
        return self._reading()

    def local_admit(self, _settings: object, bound: OperationBound) -> LocalAdmission:
        """Atomically observe and reserve one host-wide live-sandbox slot, within the
        walk's bound for this call: the slot lock is never waited on past it, and a call
        whose bound was cancelled (it timed out) never journals or writes a slot."""
        label = next(name for name, plan in self.plans.items()
                     if plan.target.kind == "local" and plan.refusal is None)
        slots = self.lifecycle._slots_dir()
        lock = _FileLock(self.lifecycle.state_root / "local-slots.lock", blocking=False,
                         deadline=_Deadline.after(bound.timeout_s), cancelled=bound.cancelled)
        with lock as held:
            if not held or bound.cancelled.is_set():
                raise PlacementUnavailable(_CAPACITY)
            reading = self._reading()
            if bound.cancelled.is_set() or not reading.admits(self.thresholds):
                raise PlacementUnavailable(_CAPACITY)
            token = self.lifecycle.new_id()
            if bound.cancelled.is_set():
                raise PlacementUnavailable(_CAPACITY)
            self._note_pending({"kind": "local", "target": label, "slot": token,
                                "binding": self.bindings[label]})
            if bound.cancelled.is_set():
                raise PlacementUnavailable(_CAPACITY)
            _write_journal(slots / f"{token}.json", {
                "client": self.lifecycle.client, "request_id": self.request.request_id,  # type: ignore[attr-defined]
                "reservation_id": self.record["reservation_id"], "created_at": self.lifecycle.clock(),
            })
        return LocalAdmission(LocalReservation(token), reading)

    def local_release(self, handle: LocalReservation) -> None:
        try:
            os.unlink(self.lifecycle._slots_dir() / f"{handle.token}.json")
        except FileNotFoundError:
            pass


class ReservationLock:
    """The reservation's journal lock (``x-prepare.lock``), held by one LaneExec step.

    ``held`` says whether it was obtained. The window check, the exec claim's
    compare-and-set and its rollback run only while it is held."""

    def __init__(self, lifecycle: PlacementLifecycle, reservation_id: str,
                 deadline: _Deadline, cancelled: threading.Event | None) -> None:
        if not _LAUNCH_KEY.fullmatch(reservation_id):
            raise LifecycleError("placement_internal")
        lifecycle._check_launch_lock_order(2)
        lifecycle._prepare()
        self.lifecycle, self.reservation_id, self.held = lifecycle, reservation_id, False
        self._lock = _FileLock(lifecycle._dir("reservations") / f"{reservation_id}.lock",
                               blocking=False, deadline=deadline, cancelled=cancelled)

    def __enter__(self) -> "ReservationLock":
        self.held = bool(self._lock.__enter__())
        return self

    def __exit__(self, *exc: object) -> None:
        self.held = False
        self._lock.__exit__(*exc)

    def _require(self) -> None:
        if not self.held:
            raise LifecycleError("placement_internal")

    def window(self, echo: Mapping[str, object] | None) -> tuple[str | None, dict[str, object] | None]:
        self._require()
        return self.lifecycle._launch_window(self.reservation_id, echo)

    def claim(self, request_id: str, run_id: str, *,
              owner: Mapping[str, object] | None = None, generation: str | None = None) -> str | None:
        self._require()
        return self.lifecycle._claim_locked(self.reservation_id, request_id, run_id, owner, generation,
                                            self._lock.deadline)

    def rollback(self, request_id: str, *, generation: str | None = None) -> bool:
        self._require()
        return self.lifecycle._rollback_locked(self.reservation_id, request_id, generation)

    def record_rollback_intent(self, request_id: str, generation: str, *, cause: str) -> bool:
        self._require()
        key = _identity_fields(self.reservation_id, request_id, generation)
        claim = self.lifecycle._owned_claim(key)
        if (not claim or cause not in _ROLLBACK_CAUSES or claim["rollback_cause"] not in (None, cause)
                or claim["owner"] != _own_identity()):
            return False
        row = self.lifecycle._disposition(key)
        if row["start_intent"] or row["fenced"] or row["debt"] is not None:
            return False
        claim["rollback_cause"] = cause
        self.lifecycle._launch_write("claims", self.reservation_id, claim)
        return True

    def ensure_prepare(self, request: LaunchRequest) -> PreparedPaths | str:
        from .launch_process_contract import PreparedPaths

        self._require()
        life, rid = self.lifecycle, self.reservation_id
        if any(path.parent == life._launch_dir("requests") for path in _HELD_LOCKS.get()):
            raise LifecycleError("placement_lock_order")
        code, active = self.window(request.reservation_json or request.reservation.to_json())
        if code:
            return code
        if (life.launch_claim_record(rid) or {}).get("claimed"):
            return _LAUNCH_CLAIMED
        req, root = request.request_id, request.snapshot.root
        existing = life.launch_prepare_record(rid)
        intent = life._launch_read("implicit", req)
        if intent and (intent["reservation_id"] != rid or intent["snapshot_root"] != root):
            return _LAUNCH_INPUT_MISMATCH
        if existing:
            paths = PreparedPaths.from_json(existing)
            if intent and intent["state"] == "planned":
                life._retire_planned(intent, paths.run_id)
                intent["state"] = "published" if intent["run_id"] == paths.run_id else "retired"
                life._launch_write("implicit", req, intent)
            if (existing["snapshot_root"] != root or request.paths not in (None, paths)
                    or request.workload == "pi-runner" and request.paths != paths):
                return _LAUNCH_INPUT_MISMATCH
            return paths
        if request.workload == "pi-runner" or request.paths is not None:
            return _LAUNCH_INPUT_MISMATCH
        kind = active["reservation"]["target"]["kind"]
        if kind not in ("local", "openshell"):
            return _LAUNCH_REFUSED
        election = life.launch_record(req)
        if not election or election.get("reservation_id") != rid:
            return _LAUNCH_REFUSED
        key = _identity_fields(rid, req, election["generation"])
        if intent is None:
            intent = dict(**key, snapshot_root=root, state="planned", run_id="run-" + life.new_id())
            life._launch_write("implicit", req, intent)
        if not _matches(intent, key) or intent["state"] != "planned":
            return _LAUNCH_REFUSED
        values = life._publish_prepare(rid, req, kind, intent["run_id"], root)
        life._launch_write("implicit", req, dict(intent, state="published"))
        return PreparedPaths.from_json(values)

    def return_dir(self, run_id: str) -> Path:
        self._require()
        return self.lifecycle._return_dir_locked(self.reservation_id, run_id)


def _supervisor_cancel(ctl: Path, key: dict, claim: dict, bound: _Deadline) -> str:
    from . import run_status

    if (not ctl.is_absolute() or ".." in ctl.parts or not hasattr(socket, "SO_PEERCRED")
            or not hasattr(os, "O_PATH")):
        return "owner_unverified"
    flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("duplicate cancel frame key")
        return result

    try:
        fd = os.open("/", flags)
        try:
            for part in ctl.parts[1:]:
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            name = key["generation"] + ".sock"
            node = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700
                    or node.st_uid != os.geteuid() or not stat.S_ISSOCK(node.st_mode)
                    or stat.S_IMODE(node.st_mode) != 0o600):
                return "owner_unverified"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(bound.left())
                conn.connect(f"/proc/self/fd/{fd}/{name}")
                peer = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                pid, uid, _ = struct.unpack("3i", peer)
                owner = claim["owner"]
                if (uid != os.geteuid() or pid != owner["pid"] or not _valid_owner(owner)
                        or run_status.process_start_identity(pid) != owner["start"]):
                    return "owner_unverified"
                sender = _own_identity()
                if not _valid_owner(sender):
                    return "owner_unverified"
                body = json.dumps(dict(**key, op="cancel", sender_pid=sender["pid"],
                                       sender_start=sender["start"]), allow_nan=False).encode("utf-8")
                if len(body) > 4096:
                    return "owner_unverified"
                conn.settimeout(bound.left())
                conn.sendall(struct.pack(">I", len(body)) + body)
                conn.shutdown(socket.SHUT_WR)

                def read(size):
                    data = bytearray()
                    while len(data) < size:
                        conn.settimeout(bound.left())
                        chunk = conn.recv(size - len(data))
                        if not chunk:
                            raise ValueError("short cancel frame")
                        data.extend(chunk)
                    return bytes(data)

                length, = struct.unpack(">I", read(4))
                if not 0 < length <= 4096:
                    return "owner_unverified"
                reply = json.loads(read(length).decode("utf-8"), object_pairs_hook=unique)
                conn.settimeout(bound.left())
                if (conn.recv(1) or bound.expired() or type(reply) is not dict
                        or reply.keys() != {"version", "generation", "outcome"}
                        or type(reply["version"]) is not int or reply["version"] != 1
                        or reply["generation"] != key["generation"]
                        or reply["outcome"] not in ("cancelled", "already_terminal", "cancel_pending",
                                                   "unknown_attempt", "owner_unverified", "owner_not_live")):
                    return "owner_unverified"
                return reply["outcome"]
        finally:
            os.close(fd)
    except OSError as error:
        if error.errno == errno.ENAMETOOLONG:
            raise LifecycleError("placement_control_socket_invariant") from error
        return "cancel_pending" if isinstance(error, TimeoutError) else "owner_unverified"
    except (ValueError, TypeError, RecursionError):
        return "owner_unverified"


def _own_identity() -> dict[str, object]:
    """The claiming process: pid and its start identity (``run_status``)."""
    from . import run_status

    return {"pid": os.getpid(), "start": run_status.process_start_identity(os.getpid())}


def _valid_owner(owner: Mapping[str, object]) -> bool:
    pid, start = owner.get("pid"), owner.get("start")
    return type(pid) is int and pid >= 1 and isinstance(start, str) and bool(start)


def _observed_exited(pid: int) -> bool:
    """Whether ``/proc/<pid>/stat`` was read and shows an exited state. A read that
    fails is not evidence either way."""
    try:
        fd = os.open(f"/proc/{pid}/stat", os.O_RDONLY | os.O_CLOEXEC)
        try:
            data = os.read(fd, 4096)
        finally:
            os.close(fd)
        state = data.decode("ascii", "replace").rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state in ("Z", "X", "x")


def _landed_launch_owner(claim: Mapping[str, object]) -> str:
    """Classify the claim's recorded owner process. ``gone`` needs affirmative evidence:
    the pid no longer exists (ESRCH, also for a claim that recorded no start identity), a
    readable start identity names another process, or procfs shows the process exited
    (state ``Z``, ``X`` or ``x``). ``live`` is a readable identity equal to the recorded
    one. Everything else, an owner the record does not name or a process whose state
    cannot be read, is ``unverified``."""
    from . import run_status

    owner = claim.get("owner")
    if not isinstance(owner, Mapping):
        return "unverified"
    pid, start = owner.get("pid"), owner.get("start")
    if type(pid) is not int or pid < 1:
        return "unverified"
    recorded = start if isinstance(start, str) and start else None
    try:
        identity = run_status.process_start_identity(pid)
    except Exception:
        identity = None
    if identity is not None and recorded is not None:
        return "live" if identity == recorded else "gone"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "gone"  # ESRCH: the recorded pid no longer exists
    except OSError:
        return "unverified"
    if _observed_exited(pid):
        return "gone"  # procfs shows the process exited (zombie or dead)
    return "unverified"


def _invoke_launch_cancel(
    fn: Callable[..., str], claim: Mapping[str, object], wait_s: float, deadline: float,
) -> str:
    """Invoke ``launch_cancel``, forwarding the absolute monotonic ``deadline`` when supported."""
    import inspect

    try:
        params = inspect.signature(fn).parameters
        accepts_deadline = "deadline" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
    except (TypeError, ValueError):
        accepts_deadline = False
    if accepts_deadline:
        return fn(claim, wait_s, deadline=deadline)
    return fn(claim, wait_s)


def _landed_launch_cancel(
    claim: Mapping[str, object], wait_s: float, *, deadline: float | None = None,
) -> str:
    """``cancel_attempt`` on the claimed run, through its verified owning launcher only."""
    from .convergence.adapters.patch_return import cancel_attempt, default_state_root

    run_id = claim.get("run_id")
    if not isinstance(run_id, str):
        return "unknown_attempt"
    wait = min(CANCEL_WAIT_S, max(0.001, float(wait_s)))
    return cancel_attempt(
        state_root=default_state_root(), attempt_id=run_id, wait_seconds=wait, deadline=deadline,
    )


def _remove_tree(path: Path) -> None:
    """Remove one run directory without following a link planted in its place."""
    import shutil

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    import stat as _stat

    if not _stat.S_ISDIR(info.st_mode):
        os.unlink(path)
    else:
        shutil.rmtree(path)
    _fsync_directory(path.parent)


def _landed_caps_loader() -> object:
    from . import seat_resource_caps

    return seat_resource_caps.load_caps()


def _landed_caps_readiness() -> str | None:
    from . import seat_resource_caps

    return seat_resource_caps.readiness_code()


def _registry_backend(root: object) -> object:
    """The registered backend for an OpenShell target's scheme; none is registered in
    production, so every remote rung refuses ``sandbox_placement_backend_unregistered``."""
    if getattr(root, "scheme", "") != "openshell":
        return None
    return backend_for_scheme("openshell")
