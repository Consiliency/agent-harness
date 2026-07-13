"""Provider-completion contracts frozen before broker enforcement is introduced."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderCompletionClassification(str, Enum):
    """Evidence-backed classification of a provider operation."""

    SUPPORTED = "supported"
    HUMAN_EXECUTED = "human-executed"
    UNSUPPORTED = "unsupported"


class ProviderAutomationDisposition(str, Enum):
    """Whether the future broker may automate a classified operation."""

    AUTOMATED = "automated"
    HUMAN_EXECUTED = "human-executed"
    BLOCKED = "blocked"


class TerminalOutcomeState(str, Enum):
    """Terminal-outcome state machine for a provider operation."""

    REJECTED_BEFORE_START = "rejected_before_start"
    PROVIDER_CALL_IN_FLIGHT = "provider_call_in_flight"
    EFFECT_TERMINAL_OBSERVED = "effect_terminal_observed"
    NO_EFFECT_TERMINAL_PROVEN = "no_effect_terminal_proven"
    OUTCOME_AMBIGUOUS_BLOCKED = "outcome_ambiguous_blocked"


@dataclass(frozen=True)
class ProviderCompletionContract:
    """Completion evidence required before a provider operation becomes automatable."""

    verb: str
    provider: str
    classification: ProviderCompletionClassification
    disposition: ProviderAutomationDisposition
    status_endpoint: str
    idempotency_key_supported: str
    terminal_success_evidence: str
    terminal_no_effect_evidence: str
    non_late_commit_guarantee: str
    guaranteed_processing_horizon: str
    expected_version_predicate: str
    revocation_affects_accepted: str
    stabilization_drain_interval: str

    def __post_init__(self) -> None:
        if not self.verb or not self.provider:
            raise ValueError("provider contracts require verb and provider")
        if not all(
            (
                self.status_endpoint,
                self.idempotency_key_supported,
                self.terminal_success_evidence,
                self.terminal_no_effect_evidence,
                self.non_late_commit_guarantee,
                self.guaranteed_processing_horizon,
                self.expected_version_predicate,
                self.revocation_affects_accepted,
                self.stabilization_drain_interval,
            )
        ):
            raise ValueError("provider completion evidence fields must be explicit")
        if self.classification is ProviderCompletionClassification.SUPPORTED:
            if self.disposition is not ProviderAutomationDisposition.AUTOMATED:
                raise ValueError("supported provider operations must be automatable")
            if "N/A" in {self.status_endpoint, self.terminal_success_evidence, self.terminal_no_effect_evidence}:
                raise ValueError("supported operations require terminal evidence")


# Repository-derived mutation inventory.  The full pair-space stays enumerated so
# inventory-completeness tests keep every verb×provider explicitly classified.
AUTOMATED_PROVIDER_VERBS = frozenset(
    (verb, "github")
    for verb in ("publish", "merge", "release", "package", "publish_committed_branch")
)

# The ONE live-enabled verb.  ``publish_committed_branch``/``github`` is SUPPORTED
# because ``GitHubBrokerAdapter`` supplies contractually-sufficient terminal
# evidence: after a by-name (non-force) push it READS the remote and only reports
# the effect terminally observed when the remote branch head equals the pushed
# head_sha AND the PR's ``headRefOid`` equals it — resolving the real PR url.  Any
# read-failure / mismatch / ambiguous push fails closed to
# ``outcome_ambiguous_blocked`` (never inferred as no-effect, never fabricated as
# success — v5 rule).  ``BrokerService`` de-dups on the canonical
# ``(repo, branch, head_sha)`` triple with idempotent replay recovery.
_SUPPORTED_GITHUB_PUBLISH = ProviderCompletionContract(
    verb="publish_committed_branch",
    provider="github",
    classification=ProviderCompletionClassification.SUPPORTED,
    disposition=ProviderAutomationDisposition.AUTOMATED,
    status_endpoint="gh pr list --head <branch> --json headRefOid,url (+ git ls-remote origin refs/heads/<branch>)",
    idempotency_key_supported="canonical (repo, branch, head_sha) triple; repeat under a fresh admission key replays the prior result",
    terminal_success_evidence="remote branch head == pushed head_sha AND PR headRefOid == pushed head_sha -> effect_terminal_observed with the real PR url",
    terminal_no_effect_evidence="ONLY a provider-confirmed rejection is no-effect; a failed/ambiguous push is NOT no-effect and fails closed to outcome_ambiguous_blocked (v5)",
    non_late_commit_guarantee="by-name non-force push linearizes onto origin/<branch> or is rejected; there is no delayed/late apply after the ls-remote read",
    guaranteed_processing_horizon="N/A — synchronous git push + gh reads; no asynchronous provider processing queue to drain",
    expected_version_predicate="origin/<branch> head == pushed head_sha (exact-published-head match)",
    revocation_affects_accepted="no — an accepted (linearized) push observed at head_sha is not revoked by the broker; only ambiguity fails closed",
    stabilization_drain_interval="N/A — verification is synchronous; no stabilization/drain window",
)

# Every OTHER verb×provider stays HUMAN_EXECUTED (merge, release, package, publish
# on github, and — by absence — all non-github providers) so the broker refuses it.
_HUMAN_EXECUTED_VERBS = tuple(
    ProviderCompletionContract(
        verb=verb,
        provider=provider,
        classification=ProviderCompletionClassification.HUMAN_EXECUTED,
        disposition=ProviderAutomationDisposition.HUMAN_EXECUTED,
        status_endpoint="N/A",
        idempotency_key_supported="N/A",
        terminal_success_evidence="N/A",
        terminal_no_effect_evidence="N/A",
        non_late_commit_guarantee="N/A",
        guaranteed_processing_horizon="N/A",
        expected_version_predicate="required before future dispatch",
        revocation_affects_accepted="N/A",
        stabilization_drain_interval="N/A",
    )
    for verb, provider in sorted(AUTOMATED_PROVIDER_VERBS)
    if (verb, provider) != ("publish_committed_branch", "github")
)

PROVIDER_COMPLETION_CLASSIFICATIONS = (_SUPPORTED_GITHUB_PUBLISH, *_HUMAN_EXECUTED_VERBS)


def validate_terminal_transition(
    current: TerminalOutcomeState,
    target: TerminalOutcomeState,
    *,
    pre_linearization_proven: bool = False,
) -> bool:
    """Return whether a terminal transition preserves the fail-closed outcome rule."""
    if current is TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT:
        return target in {
            TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
            TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN,
            TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED,
        }
    return (
        current is TerminalOutcomeState.REJECTED_BEFORE_START
        and pre_linearization_proven
        and target is TerminalOutcomeState.REJECTED_BEFORE_START
    )
