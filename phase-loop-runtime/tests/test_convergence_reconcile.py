"""SL-2 falsifiers for exact-state reconciliation (EC-RUNTIME-2)."""

from __future__ import annotations

from phase_loop_runtime.convergence.contracts import AuthoritySource, InvalidationTrigger
from phase_loop_runtime.convergence.event_log import RecoveredTrainState
from phase_loop_runtime.convergence.reconcile import ExactStateProbes, reconcile_train_state
from phase_loop_runtime.train_ledger import CoordinatorEvent, CoordinatorEventKind

from _runtime_tdd_guard import RuntimeCapabilityMissing
from runtime_content_tdd_adapter import run_mapped_case

_SECRET = "ghp_0000000000000000000000000000000000"


def _outcome(**overrides) -> CoordinatorEvent:
    value = dict(
        kind=CoordinatorEventKind.OUTCOME, train_id="t", node_id="n", roadmap_path="r",
        roadmap_digest="d", workspace_id="w", branch="b", base_ref="main", base_sha="base",
        head_sha="head", phase="RUNTIME", action="execute", attempt_id="a", epoch=1,
        verification_digest="digest", seat_outcomes=("seat",),
    )
    value.update(overrides)
    return CoordinatorEvent(**value)


def _state(**overrides) -> RecoveredTrainState:
    value = dict(train_id="t", node_states={"n": _outcome()}, verification_valid=True, approval_valid=True)
    value.update(overrides)
    return RecoveredTrainState(**value)


def _probes(**overrides) -> ExactStateProbes:
    value = {
        "git": lambda _s: {},
        "github": lambda _s: {},
        "provider": lambda _s: {},
        "registry": lambda _s: {},
    }
    value.update(overrides)
    return ExactStateProbes(**value)


# ---------------------------------------------------------------------------
# Retained skeleton behaviour and the EC-RUNTIME-2 path-entered control


def test_reconcile_requires_all_authority_and_reports_invalidation():
    state = RecoveredTrainState("t")
    missing = reconcile_train_state(state, ExactStateProbes())
    assert missing.blocker_reason and "git" in missing.blocker_reason
    verdict = reconcile_train_state(state, _probes(git=lambda _s: {"head_changed": "true"}))
    assert InvalidationTrigger.EFFECTIVE_CODE_CHANGED in verdict.binding.invalidation_triggers


def test_fresh_matching_four_domain_observation_emits_authority_with_no_invalidations():
    """EC-RUNTIME-2 path-entered control: an unchanged world must stay valid."""
    verdict = reconcile_train_state(_state(), _probes())
    assert verdict.binding.authority is AuthoritySource.GIT_HEAD
    assert verdict.binding.invalidation_triggers == ()
    assert verdict.blocker_reason is None
    assert verdict.valid and verdict.checked_at


def test_every_normative_trigger_is_emitted_exactly_once():
    verdict = reconcile_train_state(_state(), _probes(
        git=lambda _s: {"head_changed": "true", "base_changed": "true"},
        github=lambda _s: {"roadmap_changed": "true"},
        provider=lambda _s: {"dependency_changed": "true", "verification_plan_changed": "true"},
    ))
    triggers = verdict.binding.invalidation_triggers
    assert set(triggers) == set(InvalidationTrigger)
    assert len(triggers) == len(set(triggers))


def test_probes_are_invoked_freshly_for_every_decision():
    calls: list[str] = []
    probes = _probes(git=lambda _s: calls.append("git") or {})
    state = _state()
    reconcile_train_state(state, probes)
    reconcile_train_state(state, probes)
    assert calls == ["git", "git"], "cached observations are never authority"


# ---------------------------------------------------------------------------
# SL-2 mapped falsifiers


def test_observed_merge_selects_merged_sha_authority():
    """The five-way IF-0-FREEZE-5 split must reach its merged-state arm."""
    verdict = reconcile_train_state(
        _state(node_states={"n": _outcome(merge_sha="merged-sha")}),
        _probes(github=lambda _s: {"merged_sha": "merged-sha"}),
    )

    def probe():
        if verdict.binding.authority is not AuthoritySource.MERGED_SHA:
            raise RuntimeCapabilityMissing("MERGED_SHA authority is never selected")

    def assertion():
        assert verdict.binding.authority is AuthoritySource.MERGED_SHA
        assert verdict.binding.invalidation_triggers == ()

    run_mapped_case("reconcile.authority-split-is-complete", probe=probe, assertion=assertion)


def test_errored_probe_fails_closed_instead_of_propagating():
    def exploding(_state):
        raise RuntimeError("probe backend unreachable")

    outcome: dict[str, object] = {}
    try:
        outcome["verdict"] = reconcile_train_state(_state(), _probes(provider=exploding))
    except Exception as exc:  # noqa: BLE001 - the falsified behaviour is the escape itself
        outcome["raised"] = exc

    def probe():
        if "raised" in outcome:
            raise RuntimeCapabilityMissing("an errored probe escapes instead of failing closed")

    def assertion():
        verdict = outcome["verdict"]
        assert not verdict.valid
        assert verdict.blocker_reason and "provider" in verdict.blocker_reason
        assert _SECRET not in str(verdict.blocker_reason)

    run_mapped_case("reconcile.errored-probe-fails-closed", probe=probe, assertion=assertion)


def test_malformed_probe_observation_fails_closed():
    outcome: dict[str, object] = {}
    try:
        outcome["verdict"] = reconcile_train_state(
            _state(), _probes(git=lambda _s: ["not", "a", "mapping"])
        )
    except Exception as exc:  # noqa: BLE001
        outcome["raised"] = exc

    def probe():
        verdict = outcome.get("verdict")
        if "raised" in outcome or (verdict is not None and verdict.valid):
            raise RuntimeCapabilityMissing("a malformed observation is not rejected")

    def assertion():
        verdict = outcome["verdict"]
        assert not verdict.valid
        assert verdict.blocker_reason

    run_mapped_case("reconcile.malformed-observation-fails-closed", probe=probe, assertion=assertion)


def test_observations_never_carry_credential_material():
    verdict = reconcile_train_state(
        _state(), _probes(github=lambda _s: {"GH_TOKEN": _SECRET, "head_changed": "false"})
    )
    rendered = repr(verdict.observations)

    def probe():
        if _SECRET in rendered:
            raise RuntimeCapabilityMissing("probe observations are not kept metadata-only")

    def assertion():
        assert _SECRET not in repr(verdict.observations)
        assert _SECRET not in str(verdict.blocker_reason)

    run_mapped_case("reconcile.observations-stay-metadata-only", probe=probe, assertion=assertion)


def test_registry_divergence_invalidates_the_released_state():
    """A registry release that disagrees with the ledger must not read as valid."""
    verdict = reconcile_train_state(
        _state(node_states={"n": _outcome(release_identity="v1.0.0")}),
        _probes(registry=lambda _s: {"released_identity": "v9.9.9"}),
    )

    def probe():
        if verdict.binding.invalidation_triggers or not verdict.valid:
            return
        raise RuntimeCapabilityMissing("registry divergence is never observed")

    def assertion():
        assert not verdict.valid
        assert verdict.binding.invalidation_triggers

    run_mapped_case("reconcile.registry-divergence-invalidates", probe=probe, assertion=assertion)
