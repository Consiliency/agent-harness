"""FABPUB (v10) tests-only activation guard — SL-0, immutable.

This module is the SINGLE source of truth for FABPUB's TDD contract:

* exact activation (``PHASE_LOOP_TDD_EXPECT_FABPUB=1``) and the production
  marker probe (``phase_loop_runtime.fabpub_capability.FABPUB_CAPABILITY_VERSION``);
* the frozen pytest selectors used by each lane;
* the exact new / migrated / RED / expected nodeid inventories and their
  independently collected integer counts;
* the unique RED assertion anchor for every activated falsifier;
* the four frozen canonical vector digests;
* the one skip reason used while the capability is inactive.

SL-1 .. SL-4 may not edit this file.  A test repair returns to SL-0, recomputes
every affected count/digest, and re-runs the RED + default-green evidence.

Design rules this file encodes (plan ``Tests-first activation freeze``):

* A missing marker module must be handled WITHOUT a collection failure.
* Only the exact newly added production-dependent nodeids may ``skipif`` while
  the capability is inactive.  There is no module-level skip and no ``xfail``.
* Guard-control tests never skip.
* Every activated falsifier fails with an ``AssertionError`` carrying its unique
  frozen RED anchor — never an ``ImportError`` / collection error.  New symbols
  are therefore probed lazily through :func:`fabpub_symbol` inside the test body,
  after the guard.
"""

from __future__ import annotations

import hashlib
import importlib
import os
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

#: The ONLY explicit activation switch.  Anything other than the exact string
#: ``"1"`` is not activation.
FABPUB_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_FABPUB"

#: The production capability marker installed by SL-4 in a marker-only commit.
FABPUB_MARKER_MODULE = "phase_loop_runtime.fabpub_capability"
FABPUB_MARKER_ATTRIBUTE = "FABPUB_CAPABILITY_VERSION"
FABPUB_MARKER_VERSION = 1

#: The one skip reason permitted while the capability is inactive.
FABPUB_SKIP_REASON = (
    "FABPUB production capability is absent (SL-0 tests-only boundary): "
    "set PHASE_LOOP_TDD_EXPECT_FABPUB=1 to run this falsifier against production"
)


def fabpub_marker_version() -> Any:
    """Return the installed marker version, or ``None`` when absent.

    A missing marker module is the ORDINARY pre-SL-4 state and must never
    surface as a collection/import error.
    """
    try:
        module = importlib.import_module(FABPUB_MARKER_MODULE)
    except Exception:  # pragma: no cover - exercised by the absent-marker path
        return None
    return getattr(module, FABPUB_MARKER_ATTRIBUTE, None)


def fabpub_capability_active() -> bool:
    """Exact activation predicate.

    Active when ``PHASE_LOOP_TDD_EXPECT_FABPUB`` is exactly ``"1"``, otherwise
    active only when the marker module yields exactly
    ``FABPUB_CAPABILITY_VERSION == 1``.
    """
    if os.environ.get(FABPUB_ACTIVATION_ENV) == "1":
        return True
    return fabpub_marker_version() == FABPUB_MARKER_VERSION


def fabpub_explicitly_activated() -> bool:
    """True only for the explicit env activation (marker state ignored)."""
    return os.environ.get(FABPUB_ACTIVATION_ENV) == "1"


# ---------------------------------------------------------------------------
# Lazy symbol probing — never an import error inside an activated falsifier
# ---------------------------------------------------------------------------


def fabpub_symbol(module_name: str, attribute: str) -> Any:
    """Return ``module.attribute`` or ``None`` when either is absent.

    Used by every activated falsifier so a not-yet-implemented FABPUB symbol
    produces an ``AssertionError`` at the test's frozen RED anchor rather than
    an ``ImportError`` at collection time.
    """
    try:
        current: Any = importlib.import_module(module_name)
    except Exception:
        return None
    # A dotted attribute walks into a class (e.g. "LinearizableAdmissionStore.admit_next")
    # so a falsifier can probe a not-yet-added METHOD, not just a module-level name.
    for part in attribute.split("."):
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


def fabpub_require(nodeid: str, condition: Any, detail: str = "") -> Any:
    """Assert ``condition`` with this nodeid's unique frozen RED anchor.

    The raised message ALWAYS contains the anchor so the chronology reducer can
    match structured failure data and raw output to the intended assertion.
    """
    anchor = FABPUB_RED_ANCHORS.get(nodeid)
    if anchor is None:
        # A frozen-inventory drift, surfaced as an assertion rather than a KeyError
        # so it can never look like a collection failure.
        raise AssertionError(f"FABPUB anchor map has no entry for nodeid {nodeid!r}")
    if not condition:
        suffix = f" — {detail}" if detail else ""
        raise AssertionError(f"{anchor}{suffix}")
    return condition


#: The default replacement contract a migrated fresh-publish node requires.
FABPUB_ENVELOPE_SYMBOL = ("phase_loop_runtime.convergence.contracts", "PreAdmissionEnvelope")


def fabpub_migrated_activated(
    request,
    *,
    symbol: tuple[str, str] = FABPUB_ENVELOPE_SYMBOL,
    detail: str = "",
) -> bool:
    """Decide which branch a MIGRATED node runs, failing at its anchor when RED.

    Returns ``False`` while the capability is inactive — the node then runs its
    unchanged legacy-compatible branch and stays GREEN against
    production-identical ``main``.  Under explicit activation (or the final
    marker) it first asserts the replacement contract exists at this node's
    unique frozen RED anchor, so a migrated node fails at its anchor instead of
    silently passing a legacy assertion the phase has retired.
    """
    if not fabpub_capability_active():
        return False
    module, attribute = symbol
    fabpub_require(fabpub_this_nodeid(request), fabpub_symbol(module, attribute) is not None, detail)
    return True


# ---------------------------------------------------------------------------
# Frozen selectors
# ---------------------------------------------------------------------------

FABPUB_RED_SELECTOR = (
    "fabpub_ or test_convergence_broker_admission or test_convergence_broker_verbs "
    "or test_convergence_broker_revocation_race or test_convergence_broker_credsep "
    "or test_convergence_live_enable or test_convergence_fencing or test_publishing "
    "or test_train_prebuilt or test_convergence_train_integration or test_train_runner"
)

FABPUB_SL2_RED_SELECTOR = (
    "fabpub_broker or fabpub_legacy_cutover_replays_terminal_completed_effect "
    "or fabpub_shared_adapter_start_fence "
    "or fabpub_fresh_finalized_publish_rejected_before_admission_and_adapter "
    "or fabpub_intent or fabpub_expected_commit or fabpub_checkpoint or fabpub_transaction "
    "or fabpub_dual_path or fabpub_faithful_retry or fabpub_terminal_replay "
    "or fabpub_different_head or fabpub_conflicting_resume or fabpub_genuine_resume "
    "or test_convergence_broker_verbs or test_convergence_broker_revocation_race "
    "or test_convergence_broker_credsep or test_convergence_live_enable or test_publishing"
)

#: The final (marker-installed, unactivated) selector — identical to the
#: frontmatter ``automation.suite_command`` selector.
FABPUB_FINAL_SELECTOR = FABPUB_RED_SELECTOR


# ---------------------------------------------------------------------------
# Nodeid inventories (repo-relative form, exactly as the plan writes them)
# ---------------------------------------------------------------------------

_SHARED = "phase-loop-runtime/tests/test_fabpub_shared_epoch.py"
_TRAIN_RUNNER = "phase-loop-runtime/tests/test_train_runner.py"
_VERBS = "phase-loop-runtime/tests/test_convergence_broker_verbs.py"
_RACE = "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py"
_CREDSEP = "phase-loop-runtime/tests/test_convergence_broker_credsep.py"
_LIVE = "phase-loop-runtime/tests/test_convergence_live_enable.py"
_PUBLISHING = "phase-loop-runtime/tests/test_publishing.py"
_PREBUILT = "phase-loop-runtime/tests/test_train_prebuilt.py"
_TRAIN_INTEGRATION = "phase-loop-runtime/tests/test_convergence_train_integration.py"

#: Exactly the two transaction-identity falsifiers.
FABPUB_IDENTITY_NODEIDS = (
    f"{_SHARED}::test_fabpub_intent_identity_pre_trailer_vector_rejects_self_or_final_message_derivation",
    f"{_SHARED}::test_fabpub_intent_identity_retry_is_deterministic_and_commit_bound_separately",
)

#: Exactly the two shared-allocator falsifiers: the linked-worktree/injected-root
#: positive control and the real no-injection default-CLI falsifier.
FABPUB_SHARED_ALLOCATOR_NODEIDS = (
    f"{_SHARED}::test_fabpub_allocator_shared_repository_epoch_across_linked_worktrees_and_train_roots",
    f"{_SHARED}::test_fabpub_default_cli_train_roots_share_git_common_repository_allocator_without_root_injection",
)

#: The exact singleton repository-visible adapter-start ownership falsifier.
FABPUB_ADAPTER_START_FENCE_NODEIDS = (
    f"{_SHARED}::test_fabpub_shared_adapter_start_fence_blocks_competing_train_before_and_after_possible_provider_effect",
)

#: The exact singleton post-activation writer-generation lifecycle falsifier.
FABPUB_WRITER_GENERATION_FENCE_NODEIDS = (
    f"{_SHARED}::test_fabpub_post_activation_writer_generation_fence_blocks_direct_and_old_cli_restarts",
)

#: The complete eight-node legacy / quiescence / onboarding cutover inventory.
FABPUB_LEGACY_CUTOVER_NODEIDS = (
    f"{_SHARED}::test_fabpub_legacy_cutover_conflict_collision_and_idempotent_resume_before_activation",
    f"{_SHARED}::test_fabpub_legacy_cutover_preserves_exact_serialized_repo_preimages_and_resolution_context_before_activation",
    f"{_SHARED}::test_fabpub_legacy_cutover_preserves_high_water_before_activation",
    f"{_SHARED}::test_fabpub_legacy_cutover_preserves_outcome_ambiguous_block_before_activation",
    f"{_SHARED}::test_fabpub_legacy_cutover_replays_terminal_completed_effect_before_activation",
    f"{_SHARED}::test_fabpub_global_legacy_cutover_partitions_multiple_repositories_crash_idempotently_before_activation",
    f"{_SHARED}::test_fabpub_legacy_writer_quiescence_blocks_armed_activation_and_fences_supported_restarts",
    f"{_SHARED}::test_fabpub_post_armed_zero_legacy_repository_onboarding_is_serialized_and_fail_closed",
)

#: The sole default-``run_train`` crash-recovery falsifier.
FABPUB_RUN_TRAIN_RECOVERY_NODEIDS = (
    f"{_TRAIN_RUNNER}::test_fabpub_train_resume_post_commit_pre_checkpoint",
)

#: Every newly added production-dependent nodeid.  These are the ONLY nodeids
#: permitted to skip while the capability is inactive.
FABPUB_NEW_PRODUCTION_NODEIDS = tuple(
    sorted(
        (
            # --- allocator ---------------------------------------------------
            f"{_SHARED}::test_fabpub_allocator_stale_epoch",
            f"{_SHARED}::test_fabpub_allocator_epoch_equality",
            f"{_SHARED}::test_fabpub_allocator_attempt_equality",
            *FABPUB_SHARED_ALLOCATOR_NODEIDS,
            # --- legacy cutover / quiescence / onboarding --------------------
            *FABPUB_LEGACY_CUTOVER_NODEIDS,
            # --- repository-visible fences -----------------------------------
            *FABPUB_ADAPTER_START_FENCE_NODEIDS,
            *FABPUB_WRITER_GENERATION_FENCE_NODEIDS,
            # --- broker fresh-publish gate -----------------------------------
            f"{_SHARED}::test_fabpub_fresh_finalized_publish_rejected_before_admission_and_adapter",
            f"{_SHARED}::test_fabpub_broker_envelope_publish_allocates_through_admit_next",
            # --- acyclic transaction identity --------------------------------
            *FABPUB_IDENTITY_NODEIDS,
            # --- pre-ref expected-commit state machine -----------------------
            f"{_SHARED}::test_fabpub_expected_commit_object_is_durable_before_ref_cas",
            f"{_SHARED}::test_fabpub_checkpoint_conflict_blocks_alternate_oid_before_admission",
            f"{_SHARED}::test_fabpub_transaction_state_machine_enforces_ordered_projection",
            f"{_SHARED}::test_fabpub_intent_conflict_never_overwrites_active_mismatch",
            f"{_SHARED}::test_fabpub_intent_cleanup_tombstone_precedes_pointer_clear",
            f"{_SHARED}::test_fabpub_dual_path_normal_and_prebuilt_share_one_transaction_contract",
            f"{_SHARED}::test_fabpub_faithful_retry_preserves_every_identity_binding",
            f"{_SHARED}::test_fabpub_terminal_replay_returns_prior_result_without_admission_or_adapter",
            f"{_SHARED}::test_fabpub_different_head_allocates_the_next_epoch",
            f"{_SHARED}::test_fabpub_conflicting_resume_is_refused_before_admission",
            f"{_SHARED}::test_fabpub_genuine_resume_dedups_one_admission_and_one_effect",
            # --- live train authority handoff / resume -----------------------
            f"{_SHARED}::test_fabpub_train_handoff_returns_publish_authority_preimages_only",
            f"{_SHARED}::test_fabpub_train_resume_normal_recovers_exact_oid",
            f"{_SHARED}::test_fabpub_train_resume_prebuilt_never_rewrites_a_commit",
            *FABPUB_RUN_TRAIN_RECOVERY_NODEIDS,
            # --- SL-4 documentation retraction -------------------------------
            f"{_SHARED}::test_fabpub_changelog_records_publish_byte_neutrality_retraction",
        )
    )
)

#: Pre-existing nodeids migrated in place.  These NEVER skip: while inactive they
#: run their unchanged legacy-compatible branch and stay GREEN against
#: production-identical ``main``; under activation (or the final marker) they run
#: the replacement ``PreAdmissionEnvelope`` + transaction branch.
FABPUB_MIGRATED_NODEIDS = tuple(
    sorted(
        (
            f"{_VERBS}::test_same_triple_twice_single_effect_and_identical_result",
            f"{_RACE}::test_execute_refuses_publish_when_revocation_becomes_durable_before_admit",
            f"{_RACE}::test_concurrent_revocation_cannot_land_during_the_admission_lock",
            f"{_CREDSEP}::test_scope_reject_is_a_valid_terminal_through_the_broker_service",
            f"{_LIVE}::test_matching_remote_head_yields_effect_terminal_observed_with_real_url",
            f"{_LIVE}::test_idempotent_replay_returns_prior_result",
            f"{_LIVE}::test_live_broker_builder_constructs_working_client",
            f"{_LIVE}::test_remote_head_mismatch_fails_closed_to_ambiguous_not_success",
            f"{_LIVE}::test_routing_broker_binds_each_request_to_its_own_repo",
            f"{_LIVE}::test_routing_broker_dedups_within_a_repo_not_across",
            f"{_LIVE}::test_one_repo_ambiguous_outcome_does_not_poison_other_repos",
            f"{_VERBS}::test_replay_after_complete_returns_prior_result_not_none",
            f"{_PUBLISHING}::test_successful_publish_returns_if_0_p1_1_shape",
            f"{_PUBLISHING}::test_draft_pr_passes_draft_flag",
            f"{_PUBLISHING}::test_ready_pr_passes_draft_false",
            f"{_PREBUILT}::TestPrebuiltBrokerRouting::test_prebuilt_publish_passes_the_runtimes_broker_client",
            f"{_PREBUILT}::TestPrebuiltPreflightRealGit::test_default_build_admission_does_not_raise_on_invalid_utf8_owned_path",
            f"{_PREBUILT}::TestPrebuiltPreflightRealGit::test_default_build_admission_digest_unchanged_for_ascii_owned_paths",
            f"{_TRAIN_INTEGRATION}::test_broker_and_admission_threaded_into_publish_when_runtime_present",
            f"{_TRAIN_RUNNER}::TestCLIRegistration::test_cli_main_run_train_wires_a_routing_broker",
            f"{_TRAIN_RUNNER}::TestCLIRegistration::test_cli_same_stem_trains_get_distinct_broker_roots",
        )
    )
)

#: Every nodeid that must fail its intended anchor under explicit activation
#: against production-identical ``main``.
FABPUB_RED_NODEIDS = tuple(sorted(FABPUB_NEW_PRODUCTION_NODEIDS + FABPUB_MIGRATED_NODEIDS))

#: The exact collection result of ``FABPUB_SL2_RED_SELECTOR`` restricted to the
#: phase's RED inventory — the set whose FIRST green boundary is ``FABPUB-2-T3``.
#:
#: This is an explicit LITERAL, not a token filter over ``FABPUB_RED_NODEIDS``
#: (Consiliency/agent-harness#578 F-O6): a derived set silently absorbs whatever a
#: later edit happens to name, so it could never disagree with the tree it is
#: supposed to constrain.  ``FABPUB-2-T1`` must reproduce this set exactly.
FABPUB_SL2_RED_NODEIDS = (
    f"{_CREDSEP}::test_scope_reject_is_a_valid_terminal_through_the_broker_service",
    f"{_RACE}::test_concurrent_revocation_cannot_land_during_the_admission_lock",
    f"{_RACE}::test_execute_refuses_publish_when_revocation_becomes_durable_before_admit",
    f"{_VERBS}::test_replay_after_complete_returns_prior_result_not_none",
    f"{_VERBS}::test_same_triple_twice_single_effect_and_identical_result",
    f"{_LIVE}::test_matching_remote_head_yields_effect_terminal_observed_with_real_url",
    f"{_LIVE}::test_idempotent_replay_returns_prior_result",
    f"{_LIVE}::test_live_broker_builder_constructs_working_client",
    f"{_LIVE}::test_one_repo_ambiguous_outcome_does_not_poison_other_repos",
    f"{_LIVE}::test_remote_head_mismatch_fails_closed_to_ambiguous_not_success",
    f"{_LIVE}::test_routing_broker_binds_each_request_to_its_own_repo",
    f"{_LIVE}::test_routing_broker_dedups_within_a_repo_not_across",
    f"{_SHARED}::test_fabpub_broker_envelope_publish_allocates_through_admit_next",
    f"{_SHARED}::test_fabpub_checkpoint_conflict_blocks_alternate_oid_before_admission",
    f"{_SHARED}::test_fabpub_conflicting_resume_is_refused_before_admission",
    f"{_SHARED}::test_fabpub_different_head_allocates_the_next_epoch",
    f"{_SHARED}::test_fabpub_dual_path_normal_and_prebuilt_share_one_transaction_contract",
    f"{_SHARED}::test_fabpub_expected_commit_object_is_durable_before_ref_cas",
    f"{_SHARED}::test_fabpub_faithful_retry_preserves_every_identity_binding",
    f"{_SHARED}::test_fabpub_fresh_finalized_publish_rejected_before_admission_and_adapter",
    f"{_SHARED}::test_fabpub_genuine_resume_dedups_one_admission_and_one_effect",
    f"{_SHARED}::test_fabpub_intent_cleanup_tombstone_precedes_pointer_clear",
    f"{_SHARED}::test_fabpub_intent_conflict_never_overwrites_active_mismatch",
    f"{_SHARED}::test_fabpub_intent_identity_pre_trailer_vector_rejects_self_or_final_message_derivation",
    f"{_SHARED}::test_fabpub_intent_identity_retry_is_deterministic_and_commit_bound_separately",
    f"{_SHARED}::test_fabpub_legacy_cutover_replays_terminal_completed_effect_before_activation",
    f"{_SHARED}::test_fabpub_shared_adapter_start_fence_blocks_competing_train_before_and_after_possible_provider_effect",
    f"{_SHARED}::test_fabpub_terminal_replay_returns_prior_result_without_admission_or_adapter",
    f"{_SHARED}::test_fabpub_transaction_state_machine_enforces_ordered_projection",
    f"{_PUBLISHING}::test_draft_pr_passes_draft_flag",
    f"{_PUBLISHING}::test_ready_pr_passes_draft_false",
    f"{_PUBLISHING}::test_successful_publish_returns_if_0_p1_1_shape",
)

#: Every phase-owned nodeid that must be present exactly once, active, and
#: PASSING in the preactivation and final JUnit reductions.
FABPUB_EXPECTED_NODEIDS = FABPUB_RED_NODEIDS

# Independently collected integer counts (recomputed from the candidate tree).
FABPUB_NEW_PRODUCTION_COUNT = len(FABPUB_NEW_PRODUCTION_NODEIDS)
FABPUB_MIGRATED_COUNT = len(FABPUB_MIGRATED_NODEIDS)
FABPUB_RED_COUNT = len(FABPUB_RED_NODEIDS)
FABPUB_SL2_RED_COUNT = len(FABPUB_SL2_RED_NODEIDS)
FABPUB_EXPECTED_COUNT = len(FABPUB_EXPECTED_NODEIDS)
FABPUB_IDENTITY_COUNT = len(FABPUB_IDENTITY_NODEIDS)
FABPUB_SHARED_ALLOCATOR_COUNT = len(FABPUB_SHARED_ALLOCATOR_NODEIDS)
FABPUB_ADAPTER_START_FENCE_COUNT = len(FABPUB_ADAPTER_START_FENCE_NODEIDS)
FABPUB_WRITER_GENERATION_FENCE_COUNT = len(FABPUB_WRITER_GENERATION_FENCE_NODEIDS)
FABPUB_LEGACY_CUTOVER_COUNT = len(FABPUB_LEGACY_CUTOVER_NODEIDS)
FABPUB_RUN_TRAIN_RECOVERY_COUNT = len(FABPUB_RUN_TRAIN_RECOVERY_NODEIDS)

#: ``default_skip_count`` must equal exactly this while the capability is inactive.
FABPUB_DEFAULT_SKIP_COUNT = FABPUB_NEW_PRODUCTION_COUNT

#: The plan's cumulative ``+12`` is relative to this exact superseded nodeid
#: inventory.  The predecessor list is runner-stamped evidence rather than a
#: candidate-derived composition; the chronology reducer must hash the complete
#: list against this value before it computes the delta.
FABPUB_SUPERSEDED_BASELINE_INVENTORY_SHA256 = (
    "f23c2edfbda40b6044c49c82636e02e0cecdffe37fc34869891fa2d1b651f366"
)
#: Compatibility-only indicator retained for the frozen falsifier import
#: surface.  It is NOT an acceptance switch: reducer acceptance requires the
#: verified predecessor evidence below.
FABPUB_BASELINE_INVENTORY_AVAILABLE = False

#: Runner-stamped predecessor evidence is a compact JSON object with exactly
#: this schema name and a complete ``nodeids`` list.  Its sorted-LF digest must
#: equal ``FABPUB_SUPERSEDED_BASELINE_INVENTORY_SHA256`` before the reducer
#: accepts the exact candidate-relative delta.
FABPUB_PREDECESSOR_INVENTORY_SCHEMA = "fabpub_predecessor_nodeid_inventory.v1"
FABPUB_PREDECESSOR_INVENTORY_ENV = "FABPUB_SUPERSEDED_BASELINE_INVENTORY"
FABPUB_REQUIRED_NEW_NODEID_DELTA = 12

#: The frozen sub-inventory contributions the plan enumerates.  These ARE
#: reproducible and are enforced by both the guard-control test and the reducer.
FABPUB_FROZEN_SUBINVENTORY_CONTRIBUTIONS = {
    "shared_allocator": FABPUB_SHARED_ALLOCATOR_COUNT,
    "adapter_start_fence": FABPUB_ADAPTER_START_FENCE_COUNT,
    "writer_generation_fence": FABPUB_WRITER_GENERATION_FENCE_COUNT,
    "legacy_cutover": FABPUB_LEGACY_CUTOVER_COUNT,
}
FABPUB_FROZEN_SUBINVENTORY_TOTAL = sum(FABPUB_FROZEN_SUBINVENTORY_CONTRIBUTIONS.values())


# ---------------------------------------------------------------------------
# Ownership / inventory framing
# ---------------------------------------------------------------------------


def fabpub_inventory_digest(values: Iterable[str]) -> str:
    """LF-joined sorted values plus a terminal LF, SHA-256.

    The single framing used by every FABPUB inventory digest (ownership, test
    paths, and each frozen nodeid inventory).
    """
    joined = "\n".join(sorted(values)) + "\n"
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


#: The complete execution-owned write set: the sorted 25-path disjoint union of
#: SL-0 .. SL-4.
FABPUB_OWNED_PATHS = (
    "CHANGELOG.md",
    "phase-loop-runtime/src/phase_loop_runtime/cli.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/credsep.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/evidence.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/contracts.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py",
    "phase-loop-runtime/src/phase_loop_runtime/fabpub_capability.py",
    "phase-loop-runtime/src/phase_loop_runtime/fabpub_tdd_chronology.py",
    "phase-loop-runtime/src/phase_loop_runtime/publishing.py",
    "phase-loop-runtime/src/phase_loop_runtime/train_runner.py",
    "phase-loop-runtime/tests/_fabpub_tdd_guard.py",
    "phase-loop-runtime/tests/test_convergence_broker_admission.py",
    "phase-loop-runtime/tests/test_convergence_broker_credsep.py",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py",
    "phase-loop-runtime/tests/test_convergence_broker_verbs.py",
    "phase-loop-runtime/tests/test_convergence_fencing.py",
    "phase-loop-runtime/tests/test_convergence_live_enable.py",
    "phase-loop-runtime/tests/test_convergence_train_integration.py",
    "phase-loop-runtime/tests/test_fabpub_shared_epoch.py",
    "phase-loop-runtime/tests/test_publishing.py",
    "phase-loop-runtime/tests/test_train_prebuilt.py",
    "phase-loop-runtime/tests/test_train_runner.py",
)

#: The sorted 12-path test inventory (SL-0's owned test tree).
FABPUB_TEST_PATHS = tuple(
    sorted(p for p in FABPUB_OWNED_PATHS if p.startswith("phase-loop-runtime/tests/"))
)

FABPUB_OWNED_PATHS_COUNT = len(FABPUB_OWNED_PATHS)
FABPUB_TEST_PATHS_COUNT = len(FABPUB_TEST_PATHS)

# The inventory digests below are LITERAL frozen constants, not expressions over
# the tuples above (Consiliency/agent-harness#578 F-O2).  Computing them from the
# same tuple the check compares against makes the check unfalsifiable: it can
# never disagree with the inventory it is supposed to pin.  Frozen as literals,
# any edit to an inventory must ALSO restate its digest here, and both the
# guard-control test and the chronology reducer recompute independently.
FABPUB_OWNED_PATHS_SHA256 = (
    "61daa359547a2672f36a27b0af21a56f5f761cf840d42efce43859b35d3677c3"
)
FABPUB_TEST_PATHS_SHA256 = (
    "c7c498a73c76364dee1d02b0ee73eb6b6fae5ed4311d135d82ed17c4fec18e51"
)
FABPUB_IDENTITY_NODEIDS_SHA256 = (
    "a1da3c3dc443bfe3a8d9392ce86c954bfdaa18d269589f3e3efd9f0d98333e89"
)
FABPUB_SHARED_ALLOCATOR_NODEIDS_SHA256 = (
    "4d2d6a3751424be367696d18abeb316c365e4e7d2028f5fdd4d3898738e2364b"
)
FABPUB_ADAPTER_START_FENCE_NODEIDS_SHA256 = (
    "7dac57ecb3d2d22bfc4bda1ffe5f6330e9a47cee41e33c84134e743655c18497"
)
FABPUB_WRITER_GENERATION_FENCE_NODEIDS_SHA256 = (
    "22a35748a15f1109a71965f972b1662042b8779dd383c8a2f267c8b8220c72b5"
)
FABPUB_LEGACY_CUTOVER_NODEIDS_SHA256 = (
    "51b89f38436c06fa7a51120140b508251a39d4a2b42671021b68af5d29e2cafe"
)


# ---------------------------------------------------------------------------
# Frozen canonical vector digests
#
# Each digest is the SHA-256 of the canonical serialization
# ``json.dumps(vector, sort_keys=True, separators=(",", ":"),
# ensure_ascii=True).encode("ascii")`` of the corresponding inline literal
# vector defined in ``test_fabpub_shared_epoch.py``.  A guard-control test
# recomputes each one and fails if the inline vector drifts.
# ---------------------------------------------------------------------------

FABPUB_IDENTITY_VECTOR_SHA256 = (
    "4032fdd3a4bcbc1c6192580239a48929352344605240327aa01a3cf6879a2687"
)
FABPUB_COMMIT_OBJECT_VECTOR_SHA256 = (
    "e0394f7602c0e43b7e5383dd1576473343d9ee58592e9cfc4062335f46e6bffd"
)
FABPUB_REPOSITORY_IDENTITY_VECTOR_SHA256 = (
    "d508160ccf16d5fe3ceca1ecd58317f20e178b636b097b3d918397afa52b5031"
)
FABPUB_LEGACY_CUTOVER_VECTOR_SHA256 = (
    "95f35fa933aecb60f1a81659049a1b052636e43832246bbd9dc64bebb468088d"
)


# ---------------------------------------------------------------------------
# Unique RED anchors — one per activated falsifier
# ---------------------------------------------------------------------------


def _anchor(slug: str) -> str:
    return f"FABPUB-RED-ANCHOR::{slug}"


FABPUB_RED_ANCHORS: dict[str, str] = {
    # --- allocator ---------------------------------------------------------
    f"{_SHARED}::test_fabpub_allocator_stale_epoch": _anchor("allocator_stale_epoch_floor"),
    f"{_SHARED}::test_fabpub_allocator_epoch_equality": _anchor("allocator_request_record_epoch_equality"),
    f"{_SHARED}::test_fabpub_allocator_attempt_equality": _anchor("allocator_request_record_attempt_equality"),
    FABPUB_SHARED_ALLOCATOR_NODEIDS[0]: _anchor("allocator_shared_repository_epoch_space"),
    FABPUB_SHARED_ALLOCATOR_NODEIDS[1]: _anchor("allocator_default_cli_git_common_dir_route"),
    # --- legacy cutover / quiescence / onboarding --------------------------
    f"{_SHARED}::test_fabpub_legacy_cutover_preserves_high_water_before_activation": _anchor(
        "legacy_cutover_high_water_floor"
    ),
    f"{_SHARED}::test_fabpub_legacy_cutover_replays_terminal_completed_effect_before_activation": _anchor(
        "legacy_cutover_completed_effect_replay"
    ),
    f"{_SHARED}::test_fabpub_legacy_cutover_preserves_outcome_ambiguous_block_before_activation": _anchor(
        "legacy_cutover_permanent_ambiguity"
    ),
    f"{_SHARED}::test_fabpub_legacy_cutover_conflict_collision_and_idempotent_resume_before_activation": _anchor(
        "legacy_cutover_conflict_and_idempotent_resume"
    ),
    f"{_SHARED}::test_fabpub_legacy_cutover_preserves_exact_serialized_repo_preimages_and_resolution_context_before_activation": _anchor(
        "legacy_cutover_serialized_preimage_and_context"
    ),
    f"{_SHARED}::test_fabpub_global_legacy_cutover_partitions_multiple_repositories_crash_idempotently_before_activation": _anchor(
        "legacy_cutover_global_multi_repository_partition"
    ),
    f"{_SHARED}::test_fabpub_legacy_writer_quiescence_blocks_armed_activation_and_fences_supported_restarts": _anchor(
        "legacy_writer_not_quiesced_or_restart_fenced"
    ),
    f"{_SHARED}::test_fabpub_post_armed_zero_legacy_repository_onboarding_is_serialized_and_fail_closed": _anchor(
        "post_armed_repository_onboarding_bypassed"
    ),
    # --- repository-visible fences -----------------------------------------
    FABPUB_ADAPTER_START_FENCE_NODEIDS[0]: _anchor("shared_adapter_start_ownership_fence"),
    FABPUB_WRITER_GENERATION_FENCE_NODEIDS[0]: _anchor("post_activation_writer_generation_fence"),
    # --- broker fresh-publish gate -----------------------------------------
    f"{_SHARED}::test_fabpub_fresh_finalized_publish_rejected_before_admission_and_adapter": _anchor(
        "fresh_finalized_publish_not_rejected"
    ),
    f"{_SHARED}::test_fabpub_broker_envelope_publish_allocates_through_admit_next": _anchor(
        "broker_envelope_publish_admit_next_route"
    ),
    # --- acyclic transaction identity --------------------------------------
    FABPUB_IDENTITY_NODEIDS[0]: _anchor("intent_identity_pre_trailer_vector"),
    FABPUB_IDENTITY_NODEIDS[1]: _anchor("intent_identity_deterministic_retry"),
    # --- pre-ref expected-commit state machine -----------------------------
    f"{_SHARED}::test_fabpub_expected_commit_object_is_durable_before_ref_cas": _anchor(
        "expected_commit_object_durable_before_cas"
    ),
    f"{_SHARED}::test_fabpub_checkpoint_conflict_blocks_alternate_oid_before_admission": _anchor(
        "checkpoint_alternate_oid_conflict"
    ),
    f"{_SHARED}::test_fabpub_transaction_state_machine_enforces_ordered_projection": _anchor(
        "transaction_ordered_projection"
    ),
    f"{_SHARED}::test_fabpub_intent_conflict_never_overwrites_active_mismatch": _anchor(
        "intent_active_mismatch_never_overwritten"
    ),
    f"{_SHARED}::test_fabpub_intent_cleanup_tombstone_precedes_pointer_clear": _anchor(
        "intent_cleanup_tombstone_ordering"
    ),
    f"{_SHARED}::test_fabpub_dual_path_normal_and_prebuilt_share_one_transaction_contract": _anchor(
        "dual_path_transaction_contract"
    ),
    f"{_SHARED}::test_fabpub_faithful_retry_preserves_every_identity_binding": _anchor(
        "faithful_retry_identity_bindings"
    ),
    f"{_SHARED}::test_fabpub_terminal_replay_returns_prior_result_without_admission_or_adapter": _anchor(
        "terminal_replay_zero_side_effects"
    ),
    f"{_SHARED}::test_fabpub_different_head_allocates_the_next_epoch": _anchor(
        "different_head_next_epoch"
    ),
    f"{_SHARED}::test_fabpub_conflicting_resume_is_refused_before_admission": _anchor(
        "conflicting_resume_refused"
    ),
    f"{_SHARED}::test_fabpub_genuine_resume_dedups_one_admission_and_one_effect": _anchor(
        "genuine_resume_dedup"
    ),
    # --- live train authority handoff / resume -----------------------------
    f"{_SHARED}::test_fabpub_train_handoff_returns_publish_authority_preimages_only": _anchor(
        "train_handoff_preimages_only"
    ),
    f"{_SHARED}::test_fabpub_train_resume_normal_recovers_exact_oid": _anchor(
        "train_resume_normal_exact_oid"
    ),
    f"{_SHARED}::test_fabpub_train_resume_prebuilt_never_rewrites_a_commit": _anchor(
        "train_resume_prebuilt_no_rewrite"
    ),
    FABPUB_RUN_TRAIN_RECOVERY_NODEIDS[0]: _anchor("default_run_train_transaction_recovery"),
    # --- SL-4 documentation retraction -------------------------------------
    f"{_SHARED}::test_fabpub_changelog_records_publish_byte_neutrality_retraction": _anchor(
        "changelog_byte_neutrality_retraction"
    ),
    # --- migrated nodes ----------------------------------------------------
    f"{_VERBS}::test_same_triple_twice_single_effect_and_identical_result": _anchor(
        "migrated_verbs_canonical_triple_envelope"
    ),
    f"{_VERBS}::test_replay_after_complete_returns_prior_result_not_none": _anchor(
        "migrated_verbs_terminal_replay_shape_agnostic"
    ),
    f"{_RACE}::test_execute_refuses_publish_when_revocation_becomes_durable_before_admit": _anchor(
        "migrated_race_revocation_before_admit_next"
    ),
    f"{_RACE}::test_concurrent_revocation_cannot_land_during_the_admission_lock": _anchor(
        "migrated_race_concurrent_revocation_admit_next"
    ),
    f"{_CREDSEP}::test_scope_reject_is_a_valid_terminal_through_the_broker_service": _anchor(
        "migrated_credsep_scope_reject_envelope"
    ),
    f"{_LIVE}::test_matching_remote_head_yields_effect_terminal_observed_with_real_url": _anchor(
        "migrated_live_matching_remote_head_envelope"
    ),
    f"{_LIVE}::test_idempotent_replay_returns_prior_result": _anchor(
        "migrated_live_completed_terminal_replay"
    ),
    f"{_LIVE}::test_live_broker_builder_constructs_working_client": _anchor(
        "migrated_live_production_root_injection_rejected"
    ),
    f"{_LIVE}::test_remote_head_mismatch_fails_closed_to_ambiguous_not_success": _anchor(
        "migrated_live_remote_head_mismatch_envelope"
    ),
    f"{_LIVE}::test_routing_broker_binds_each_request_to_its_own_repo": _anchor(
        "migrated_live_routing_worktree_binding"
    ),
    f"{_LIVE}::test_routing_broker_dedups_within_a_repo_not_across": _anchor(
        "migrated_live_routing_repository_dedup"
    ),
    f"{_LIVE}::test_one_repo_ambiguous_outcome_does_not_poison_other_repos": _anchor(
        "migrated_live_repository_scoped_ambiguity"
    ),
    f"{_PUBLISHING}::test_successful_publish_returns_if_0_p1_1_shape": _anchor(
        "migrated_publishing_envelope_handoff"
    ),
    f"{_PUBLISHING}::test_draft_pr_passes_draft_flag": _anchor(
        "migrated_publishing_draft_authority_handoff"
    ),
    f"{_PUBLISHING}::test_ready_pr_passes_draft_false": _anchor(
        "migrated_publishing_ready_authority_handoff"
    ),
    f"{_PREBUILT}::TestPrebuiltBrokerRouting::test_prebuilt_publish_passes_the_runtimes_broker_client": _anchor(
        "migrated_prebuilt_publish_authority_preimages"
    ),
    f"{_PREBUILT}::TestPrebuiltPreflightRealGit::test_default_build_admission_does_not_raise_on_invalid_utf8_owned_path": _anchor(
        "migrated_prebuilt_surrogate_owned_path_digest"
    ),
    f"{_PREBUILT}::TestPrebuiltPreflightRealGit::test_default_build_admission_digest_unchanged_for_ascii_owned_paths": _anchor(
        "migrated_prebuilt_ascii_owned_path_digest"
    ),
    f"{_TRAIN_INTEGRATION}::test_broker_and_admission_threaded_into_publish_when_runtime_present": _anchor(
        "migrated_train_integration_publish_authority"
    ),
    f"{_TRAIN_RUNNER}::TestCLIRegistration::test_cli_main_run_train_wires_a_routing_broker": _anchor(
        "migrated_cli_no_allocator_root_injection"
    ),
    f"{_TRAIN_RUNNER}::TestCLIRegistration::test_cli_same_stem_trains_get_distinct_broker_roots": _anchor(
        "migrated_cli_shared_repository_namespace"
    ),
}


# ---------------------------------------------------------------------------
# Nodeid normalization
# ---------------------------------------------------------------------------

#: pytest's rootdir is ``phase-loop-runtime`` (it owns the pyproject), so
#: collected nodeids are ``tests/<file>::<test>``.  The frozen inventories above
#: are repo-relative, exactly as the plan writes them.
FABPUB_NODEID_PREFIX = "phase-loop-runtime/"


def fabpub_repo_relative_nodeid(nodeid: str) -> str:
    """Normalize a collected pytest nodeid to the frozen repo-relative form."""
    normalized = nodeid.replace("\\", "/")
    if normalized.startswith(FABPUB_NODEID_PREFIX):
        return normalized
    if normalized.startswith("tests/"):
        return FABPUB_NODEID_PREFIX + normalized
    return normalized


def fabpub_local_nodeid(nodeid: str) -> str:
    """Inverse of :func:`fabpub_repo_relative_nodeid` (rootdir-relative form)."""
    normalized = nodeid.replace("\\", "/")
    if normalized.startswith(FABPUB_NODEID_PREFIX):
        return normalized[len(FABPUB_NODEID_PREFIX) :]
    return normalized


def fabpub_this_nodeid(request) -> str:
    """Return the frozen repo-relative nodeid for the running test."""
    return fabpub_repo_relative_nodeid(request.node.nodeid)
