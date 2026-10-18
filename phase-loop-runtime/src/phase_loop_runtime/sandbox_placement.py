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

import contextvars
from dataclasses import dataclass, field, replace
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import re
import socket
import threading
import time
from typing import Callable, Iterable, Mapping, NamedTuple, Protocol, Sequence, runtime_checkable

from . import review_stage, sandbox_policy, sandbox_retention

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
    "OperationBound",
    "PlacedSandbox",
    "PlacementBackend",
    "PlacementCancelled",
    "PlacementDecision",
    "PlacementReceipt",
    "PlacementRequest",
    "PlacementUnavailable",
    "Prepared",
    "applied_rule",
    "backend_for_scheme",
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
_WORKLOADS = frozenset({"leg", "qualification"})
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
    _TIMEOUT, _CAPABILITY_UNMET, _RELEASE_UNCONFIRMED,
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

    def __init__(self, code: str, reason: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.reason = reason

    def __str__(self) -> str:
        return self.code


class PlacementCancelled(RuntimeError):
    """The caller cancelled a walk, or a placed leg. ``str()`` is the fixed code a cancelled
    review operation carries everywhere else, and the trail is attached."""

    def __init__(self, trail: Sequence[Mapping[str, object]] = ()) -> None:
        super().__init__(_CANCELLED)
        self.trail = tuple(trail)

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
    #: ``leg`` or ``qualification`` (C10). Visible to the driver and to ``admit``.
    workload: str = "leg"
    #: What the backend must declare, and verify after ``commit`` (C5).
    required_capabilities: frozenset[str] = frozenset()
    #: The parsed, sanitized root and its configured backend name; :func:`place` sets it,
    #: with the owner id and the lease id (C6).
    root: "sandbox_policy.SandboxRootChoice | None" = None
    owner_id: str = ""
    lease_id: str = ""

    def __post_init__(self) -> None:
        if self.workload not in _WORKLOADS:
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
        return False, "a qualification workload is never an applied placement"
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
                "lifetime, a `leg` workload while the driver flag is false"
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
                "**The capacity bar is set for the attempt.** The far end's answer means it "
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
            "another_rung", "start_next",
            "Another remote rung exists and the budget is not spent",
            "Starts that rung",
        ),
        _AfterLeftRow(
            "last_local_unbarred", "launching_host",
            "Otherwise, the last rung is `local` and the capacity bar is not set",
            "Ends on **the launching host**",
        ),
        _AfterLeftRow(
            "last_local_barred", "not_run_capacity_exhausted",
            "Otherwise, the last rung is `local` and the capacity bar is set",
            "Ends **not run**, `sandbox_placement_capacity_exhausted`",
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


class _CallCancelled(Exception):
    """The caller cancelled while a bounded call was in flight."""


def _serve(jobs: "queue.SimpleQueue[object]", permits: threading.BoundedSemaphore) -> None:
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


class _Calls:
    """Runs a call so that it can outlast neither its bound nor a cancel (C4).

    One worker thread serves the calls of one walk in turn. A call that does not return in
    time is abandoned together with its queue. All live workers (idle, active and
    abandoned) hold permits until actual exit. The settings cap is per group: the walk,
    result wait and renewal each own a group, not a process-wide quota."""

    def __init__(self, *, settings: sandbox_policy.PlacementDriverSettings | None = None) -> None:
        settings = settings if settings is not None else sandbox_policy.placement_driver_settings(env={})
        self._permits = threading.BoundedSemaphore(settings.max_live_workers)
        self._jobs: "queue.SimpleQueue[object] | None" = None

    def ready(self) -> None:
        if self._jobs is not None:
            return
        if not self._permits.acquire(blocking=False):
            raise PlacementUnavailable(_TIMEOUT)
        jobs: queue.SimpleQueue[object] = queue.SimpleQueue()
        try:
            threading.Thread(
                target=_serve, args=(jobs, self._permits), name="placement-call", daemon=True,
            ).start()
        except Exception:
            self._permits.release()
            raise PlacementUnavailable(_TIMEOUT) from None
        self._jobs = jobs

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
    placement: "LegPlacement | None" = None
    spec: ExecSpec | None = None
    #: The code that sent the rung to "releasing".
    reason: str | None = None
    cancel: bool = False


class _Walk:
    """One attempt to place one seat. The transitions are :data:`LADDER_TABLE`'s; each
    ``_<state>`` method does that state's work and names the event that happened."""

    def __init__(
        self, prepared: Prepared, request_for: Callable[[object], PlacementRequest],
        open_lease: Callable[[str | None, object], object],
        seal: Callable[[PlacementRequest], "ExecSpec | None"],
        driver_enabled: bool, cancelled: threading.Event,
        settings: sandbox_policy.PlacementDriverSettings,
    ) -> None:
        self.prepared = prepared
        self.request_for = request_for
        self.open_lease = open_lease
        self.seal = seal
        self.driver_enabled = driver_enabled
        self.cancelled = cancelled
        self.settings = settings
        self.calls = _Calls(settings=settings)
        self.trail: list[Mapping[str, object]] = []
        self.notices: list[str] = []
        #: Set by the first capacity answer on any rung; nothing clears it.
        self.capacity_bar = False
        self.admit_wait_s = float(settings.admit_wait_s)
        self.budget_s = self.admit_wait_s + float(settings.transfer_allowance_s)
        self.waited_s = 0.0
        self.started = _monotonic()

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
            placed = self._rung(root)
            if placed is not None:
                return placed
            if self._after_left(index + 1 < len(rungs), last_rung) != "start_next":
                break
        return self._end(self._after_left(False, last_rung))

    def _after_left(self, another: bool, last_rung: str) -> str:
        facts = {
            "another_rung": another and not self._budget_spent(),
            "last_local_unbarred": last_rung == "local" and not self.capacity_bar,
            "last_local_barred": last_rung == "local" and self.capacity_bar,
            "last_none": last_rung == "none",
        }
        return next(row.walk for row in LADDER_TABLE.after_left if facts[row.condition])

    def _end(self, walk: str, code: str | None = None) -> PlacementDecision:
        trail, notices = tuple(self.trail), tuple(self.notices)
        if walk == "launching_host":
            return PlacementDecision(
                "launching_host", trail, code, tooled_route_required=True, notices=notices,
            )
        if walk == "not_run_capacity_exhausted":
            return PlacementDecision("not_run", trail, _CAPACITY_EXHAUSTED, notices=notices)
        if code is None and trail:
            code = trail[-1]["code"]  # type: ignore[assignment]
        if code is None or sandbox_policy.remote_required():
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
                return None
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
                self._record(rung, target[5:], code)
                return None
            state = target

    # -- the states ---------------------------------------------------------------------
    def _start(self, rung: _Rung) -> tuple[str | None, str | None]:
        failed = "local_check_failed"
        try:
            request = self.request_for(rung.root)
        except Exception:
            return failed, _REFUSED
        if not isinstance(request, PlacementRequest):
            return failed, _REFUSED
        # The root travels with the request; a placed seat has no private endpoint (C5, C6).
        request = replace(request, root=rung.root, egress_needs=EgressNeeds())  # type: ignore[arg-type]
        if request.workload == "leg" and not self.driver_enabled:
            # The execution gate (C10), before the backend is looked up or called.
            return failed, _DRIVER_UNAVAILABLE
        try:
            backend = backend_for_scheme(getattr(rung.root, "scheme", ""))
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
            timeout = min(sandbox_policy.probe_timeout_s(), self._budget_left())
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
        if self._budget_spent():
            return "budget_spent", _BUDGET_SPENT
        bound = _bound(min(ANSWER_BOUND_S, self._budget_left()), self.cancelled)
        backend, request = rung.backend, rung.request
        try:
            self.calls.run(lambda: backend.admit(request, bound), bound.timeout_s, self.cancelled)  # type: ignore[attr-defined]
        except _CallCancelled:
            return None, None
        except PlacementUnavailable as exc:
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
            return "no_answer", _REFUSED
        return "admitted", None

    def _at_capacity(self, rung: _Rung) -> None:
        self.capacity_bar = True
        if _WAITING_NOTICE not in self.notices:
            self.notices.append(_WAITING_NOTICE)
            logging.getLogger(__name__).warning(
                "seat placement [%s]: %s is at capacity; waiting up to %d s in all for a "
                "slot, and the seat will not run on this host", _WAITING_NOTICE, rung.label,
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
                # The bar is set by the first capacity answer on any rung (C7). Nothing
                # waits here: the slot is released as a failed transfer.
                self.capacity_bar = True
                return failed, _CAPACITY
            return failed, self._refusal_code(rung, exc.code, _COMMIT_REFUSALS)
        except Exception:
            return failed, _REFUSED
        try:
            sandbox_ref, receipts, verified = _commit_claims(rung.capabilities, result, prepared)
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
            if exc.code == _TIMEOUT:
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
    prepared: Prepared,
    request_for: Callable[["sandbox_policy.SandboxRootChoice"], PlacementRequest],
    open_lease: Callable[[str | None, "sandbox_policy.SandboxRootChoice"], object],
    *,
    preflight: Callable[[], str | None],
    seal: Callable[[PlacementRequest], "ExecSpec | None"],
    driver_enabled: bool,
    cancelled: threading.Event,
    settings: sandbox_policy.PlacementDriverSettings | None = None,
) -> PlacementDecision:
    """Decide where a candidate seat runs, and launch it there if a remote rung takes it.

    The walk of amendment C7. ``rungs`` are the configured remote roots in order
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
    """
    if last_rung not in _LAST_RUNGS:
        raise ValueError(f"unknown last rung {last_rung!r}")
    settings = settings if settings is not None else sandbox_policy.placement_driver_settings()
    refusal = preflight()
    walk = _Walk(prepared, request_for, open_lease, seal, bool(driver_enabled), cancelled, settings)
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
    was_cancelled = False
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
            if isinstance(got, ExecProgress) and got.sandbox_ref == sandbox_ref:
                if isinstance(got.seq, int) and got.seq > seq:
                    seq = got.seq
                    if on_progress is not None:
                        on_progress(got)
            elif (
                isinstance(got, ExecResult) and got.sandbox_ref == sandbox_ref
                and isinstance(got.result, bytes) and len(got.result) <= spec.output_cap_bytes
                and _echoes(got.result, spec.request)
            ):
                result = got
                placement._observed.add("completed")
                placement.record_runtime("completed")
            else:
                # `wait` returns only a result or progress (C12, before the reconnect plan).
                failure = _LOST_AFTER_LAUNCH
        if result is None:
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
