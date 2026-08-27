"""Read-only exact-state reconciliation for recovered convergence events.

Every decision re-probes all four authority domains -- Git, GitHub, provider,
and registry -- from scratch. A cached observation is never authority: the whole
point of reconciliation is that the world may have moved since the ledger was
written, so a probe result is used once and discarded.

Two properties hold on every path:

* **Metadata-only.** An observation is reduced to the exact fields a
  reconciliation decision reads (:data:`_OBSERVED_FIELDS`) and each value is
  bounded. Everything else a probe hands back -- including anything
  credential-shaped -- is dropped before it can reach a verdict, a repr, or a
  log line. The retained set is an allow-list, so a probe that grows a new
  field cannot silently widen what is retained.
* **Fail closed.** A required probe that is absent, errors, returns nothing,
  returns a non-mapping, or declares itself stale yields a blocked verdict
  naming the domain, never an exception and never a valid verdict. So does an
  ambiguous or mid-flight ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping

from .contracts import AuthoritySource, InvalidationTrigger, ReconciliationBinding
from .event_log import RecoveredTrainState

#: The exact observation fields reconciliation reads. Retaining only these is
#: what keeps observations metadata-only *by construction* rather than by
#: enumerating the credential shapes of the day.
_OBSERVED_FIELDS: tuple[str, ...] = (
    "head_changed",
    "roadmap_changed",
    "base_changed",
    "dependency_changed",
    "verification_plan_changed",
    "head_sha",
    "merged_sha",
    "released_identity",
    "stale",
)

#: Metadata values are short identities and flags; anything longer is not
#: metadata and is truncated rather than carried into a verdict.
_MAX_OBSERVATION_VALUE = 256

#: The four domains a decision must resolve afresh, in probe order.
_REQUIRED_DOMAINS: tuple[str, ...] = ("git", "github", "provider", "registry")

#: Changed-flag to normative trigger. Each fires at most once per decision.
_TRIGGER_FLAGS: tuple[tuple[str, InvalidationTrigger], ...] = (
    ("head_changed", InvalidationTrigger.EFFECTIVE_CODE_CHANGED),
    ("roadmap_changed", InvalidationTrigger.ROADMAP_CHANGED),
    ("base_changed", InvalidationTrigger.BASE_SHA_CHANGED),
    ("dependency_changed", InvalidationTrigger.DEPENDENCY_SHA_CHANGED),
    ("verification_plan_changed", InvalidationTrigger.VERIFICATION_PLAN_DIGEST_CHANGED),
)

_AUTHORITY_VERSION = "1"
_INVALIDATION_MODEL_VERSION = "1"


@dataclass(frozen=True)
class ExactStateProbes:
    git: Callable[[RecoveredTrainState], Mapping[str, str] | None] | None = None
    github: Callable[[RecoveredTrainState], Mapping[str, str] | None] | None = None
    provider: Callable[[RecoveredTrainState], Mapping[str, str] | None] | None = None
    registry: Callable[[RecoveredTrainState], Mapping[str, str] | None] | None = None


@dataclass(frozen=True)
class ReconciliationVerdict:
    binding: ReconciliationBinding
    observations: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    blocker_reason: str | None = None
    checked_at: str = ""

    @property
    def valid(self) -> bool:
        return self.blocker_reason is None and not self.binding.invalidation_triggers


@dataclass(frozen=True)
class SupportedConvergenceVersions:
    event_schema_version: str = "1"
    transition_model_version: str = "1"
    invalidation_model_version: str = "1"


@dataclass(frozen=True)
class ActionReconciliation:
    action: str
    verdict: ReconciliationVerdict
    verification_valid: bool
    approval_valid: bool

    @property
    def admitted(self) -> bool:
        return self.verdict.valid and self.verification_valid and self.approval_valid


def _flag(observation: Mapping[str, str], key: str) -> bool:
    return str(observation.get(key, "")).strip().lower() == "true"


def _metadata_only(value: Mapping[str, str]) -> dict[str, str]:
    """Reduce a probe result to the bounded metadata fields a decision reads."""

    reduced: dict[str, str] = {}
    for name in _OBSERVED_FIELDS:
        if name in value:
            reduced[name] = str(value[name])[:_MAX_OBSERVATION_VALUE]
    return reduced


def _observe(
    state: RecoveredTrainState, probes: ExactStateProbes
) -> tuple[dict[str, Mapping[str, str]], str | None]:
    """Probe all four domains afresh; return the observations or a blocker reason."""

    observations: dict[str, Mapping[str, str]] = {}
    for name in _REQUIRED_DOMAINS:
        probe = getattr(probes, name)
        if probe is None:
            return {}, f"required {name} authority unavailable"
        try:
            value = probe(state)
        except Exception:  # noqa: BLE001 - any probe failure is an unresolved authority
            # The exception text is never interpolated: a probe backend is free
            # to put a credential in its own message, and this reason is public.
            return {}, f"required {name} authority probe failed"
        if value is None:
            return {}, f"required {name} authority unavailable"
        if not isinstance(value, Mapping):
            return {}, f"required {name} authority returned a malformed observation"
        reduced = _metadata_only(value)
        if _flag(reduced, "stale"):
            return {}, f"required {name} authority observation is stale"
        observations[name] = reduced
    return observations, None


def _ledgered(state: RecoveredTrainState, attribute: str) -> str | None:
    """The last non-empty ``attribute`` recorded for any node, in replay order."""

    found: str | None = None
    for event in state.node_states.values():
        value = getattr(event, attribute, None)
        if value:
            found = str(value)
    return found


def _select_authority(
    state: RecoveredTrainState, observations: Mapping[str, Mapping[str, str]]
) -> AuthoritySource:
    """The IF-0-FREEZE-5 authority split, resolved against ledger and observation.

    An in-flight attempt wins outright: the operation may still be changing the
    world, so the log -- not any settled artifact -- is the live authority.
    Otherwise authority is whichever stage the work has actually reached.
    """

    if state.pending_attempts:
        return AuthoritySource.EVENT_LOG
    if observations.get("registry", {}).get("released_identity") or _ledgered(
        state, "release_identity"
    ):
        return AuthoritySource.REGISTRY_MANIFEST
    if observations.get("github", {}).get("merged_sha") or _ledgered(state, "merge_sha"):
        return AuthoritySource.MERGED_SHA
    if observations.get("git", {}).get("head_sha") or _ledgered(state, "head_sha"):
        return AuthoritySource.GIT_HEAD
    return AuthoritySource.ROADMAP


def _divergences(
    state: RecoveredTrainState, observations: Mapping[str, Mapping[str, str]]
) -> list[InvalidationTrigger]:
    """Triggers implied by an observation disagreeing with the ledgered value.

    Only a *disagreement* fires. A domain that reports nothing about a field
    has observed nothing, which is not a divergence -- otherwise an unchanged
    world would invalidate itself on every decision.
    """

    triggers: list[InvalidationTrigger] = []
    for domain, key, attribute in (
        ("registry", "released_identity", "release_identity"),
        ("github", "merged_sha", "merge_sha"),
        ("git", "head_sha", "head_sha"),
    ):
        observed = observations.get(domain, {}).get(key)
        ledgered = _ledgered(state, attribute)
        if observed and ledgered and observed != ledgered:
            triggers.append(InvalidationTrigger.EFFECTIVE_CODE_CHANGED)
    return triggers


def reconcile_train_state(state: RecoveredTrainState, probes: ExactStateProbes) -> ReconciliationVerdict:
    checked_at = datetime.now(timezone.utc).isoformat()
    observations, blocker = _observe(state, probes)
    if blocker is not None:
        return _blocked(blocker, checked_at)
    if not state.train_id:
        return _blocked("recovered state carries no train identity", checked_at)
    if state.ambiguities:
        return _blocked(state.ambiguities[0], checked_at, observations)
    authority = _select_authority(state, observations)
    triggers: list[InvalidationTrigger] = []
    for observation in observations.values():
        for key, trigger in _TRIGGER_FLAGS:
            if _flag(observation, key):
                triggers.append(trigger)
    triggers.extend(_divergences(state, observations))
    binding = ReconciliationBinding(
        authority,
        _AUTHORITY_VERSION,
        _INVALIDATION_MODEL_VERSION,
        tuple(dict.fromkeys(triggers)),
    )
    blocker_reason: str | None = None
    if binding.invalidation_triggers:
        blocker_reason = "state invalidated"
    elif state.pending_attempts:
        # An active operation is a real authority, and it is also a reason not to
        # admit a new action on top of it until that attempt terminates.
        blocker_reason = "an attempt is still in flight"
    return ReconciliationVerdict(binding, observations, blocker_reason, checked_at)


def invalidate_action_evidence(state: RecoveredTrainState, verdict: ReconciliationVerdict) -> ActionReconciliation:
    """Clear replay-derived verification/approval whenever the verdict is not valid."""

    carried = verdict.valid
    return ActionReconciliation(
        "",
        verdict,
        state.verification_valid and carried,
        state.approval_valid and carried,
    )


def reconcile_before_action(state: RecoveredTrainState, probes: ExactStateProbes, action: str, *, supported_versions: SupportedConvergenceVersions = SupportedConvergenceVersions()) -> ActionReconciliation:
    verdict = reconcile_train_state(state, probes)
    if (verdict.binding.authority_version, verdict.binding.invalidation_model_version) != (
        supported_versions.event_schema_version,
        supported_versions.invalidation_model_version,
    ):
        verdict = ReconciliationVerdict(
            verdict.binding, verdict.observations, "unsupported convergence version", verdict.checked_at
        )
    invalidated = invalidate_action_evidence(state, verdict)
    return ActionReconciliation(action, verdict, invalidated.verification_valid, invalidated.approval_valid)


def _blocked(
    reason: str,
    checked_at: str,
    observations: Mapping[str, Mapping[str, str]] | None = None,
) -> ReconciliationVerdict:
    """A fail-closed verdict: the log is all that can be trusted, and it is not enough."""

    return ReconciliationVerdict(
        ReconciliationBinding(
            AuthoritySource.EVENT_LOG, _AUTHORITY_VERSION, _INVALIDATION_MODEL_VERSION
        ),
        dict(observations or {}),
        reason,
        checked_at,
    )
