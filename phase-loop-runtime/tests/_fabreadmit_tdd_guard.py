"""FABREADMIT (v10) tests-only activation guard — SL-0, immutable.

This module is the SINGLE source of truth for FABREADMIT's TDD contract:

* exact activation (``PHASE_LOOP_TDD_EXPECT_FABREADMIT=1``) and the production
  marker probe (``phase_loop_runtime.fabreadmit_capability.FABREADMIT_CAPABILITY_VERSION``);
* the frozen pytest selectors used by each lane;
* the exact new RED node inventory and integer counts;
* the unique RED assertion anchor for every activated falsifier;
* the skip reason used while the capability is inactive.

SL-1 .. SL-3 may not edit this file.
"""

from __future__ import annotations

import hashlib
import importlib
import os
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

FABREADMIT_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_FABREADMIT"

FABREADMIT_MARKER_MODULE = "phase_loop_runtime.fabreadmit_capability"
FABREADMIT_MARKER_ATTRIBUTE = "FABREADMIT_CAPABILITY_VERSION"
FABREADMIT_MARKER_VERSION = 1

FABREADMIT_SKIP_REASON = (
    "FABREADMIT production capability is absent (SL-0 tests-only boundary): "
    "set PHASE_LOOP_TDD_EXPECT_FABREADMIT=1 to run this falsifier against production"
)


def fabreadmit_marker_version() -> Any:
    """Return the installed marker version, or ``None`` when absent."""
    try:
        module = importlib.import_module(FABREADMIT_MARKER_MODULE)
    except Exception:
        return None
    return getattr(module, FABREADMIT_MARKER_ATTRIBUTE, None)


def fabreadmit_capability_active() -> bool:
    """Exact activation predicate."""
    if os.environ.get(FABREADMIT_ACTIVATION_ENV) == "1":
        return True
    return fabreadmit_marker_version() == FABREADMIT_MARKER_VERSION


def fabreadmit_explicitly_activated() -> bool:
    """True only for explicit env activation."""
    return os.environ.get(FABREADMIT_ACTIVATION_ENV) == "1"


# ---------------------------------------------------------------------------
# Lazy symbol probing — never an import error inside an activated falsifier
# ---------------------------------------------------------------------------


def fabreadmit_symbol(module_name: str, attribute: str) -> Any:
    """Return ``module.attribute`` or ``None`` when either is absent."""
    try:
        current: Any = importlib.import_module(module_name)
    except Exception:
        return None
    for part in attribute.split("."):
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


def fabreadmit_require(nodeid: str, condition: Any, detail: str = "") -> Any:
    """Assert ``condition`` with this nodeid's unique frozen RED anchor."""
    anchor = FABREADMIT_RED_ANCHORS.get(nodeid)
    if anchor is None:
        raise AssertionError(f"FABREADMIT anchor map has no entry for nodeid {nodeid!r}")
    if not condition:
        suffix = f" — {detail}" if detail else ""
        raise AssertionError(f"{anchor}{suffix}")
    return condition


# ---------------------------------------------------------------------------
# Nodeid inventories (repo-relative form)
# ---------------------------------------------------------------------------

_BROKER_FILE = "phase-loop-runtime/tests/test_fabreadmit_broker.py"
_ADM_FILE = "phase-loop-runtime/tests/test_convergence_broker_admission.py"
_VERBS_FILE = "phase-loop-runtime/tests/test_convergence_broker_verbs.py"
_RACE_FILE = "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py"
_CONSUMER_FILE = "phase-loop-runtime/tests/test_fab_delta_consumer.py"
_PROMOTION_FILE = "phase-loop-runtime/tests/test_fab_activation_promotion.py"
_LEAK_FILE = "phase-loop-runtime/tests/test_fab_flag_off_recovery_leak_299.py"
_TRAIN_FILE = "phase-loop-runtime/tests/test_train_runner.py"
_PREMERGE_FILE = "phase-loop-runtime/tests/test_governed_premerge.py"

FABREADMIT_NEW_PRODUCTION_NODEIDS = tuple(
    sorted((
        f"{_BROKER_FILE}::test_fabreadmit_broker_authority_receipt_contract",
        f"{_BROKER_FILE}::test_fabreadmit_broker_rediffs_head_range_and_rejects_scope_escape_without_adapter",
        f"{_ADM_FILE}::test_fabreadmit_prior_record_predicate_and_chained_readmit_binding",
        f"{_ADM_FILE}::test_fabreadmit_checkpoint_root_validation",
        f"{_ADM_FILE}::test_fabreadmit_linked_worktrees_share_canonical_repository_allocator",
        f"{_VERBS_FILE}::test_fabreadmit_readmit_advanced_head_verb",
        f"{_RACE_FILE}::test_fabreadmit_revocation_race_under_admission_lock",
        f"{_CONSUMER_FILE}::test_fabreadmit_commit_points_reach_commit_broker_readmitted_head",
        f"{_CONSUMER_FILE}::test_fabreadmit_append_site_inventory",
        f"{_CONSUMER_FILE}::test_fabreadmit_append_site_inventory_detects_third_site",
        f"{_CONSUMER_FILE}::test_fabreadmit_fresh_revocation_blocks_delta_merge",
        f"{_CONSUMER_FILE}::test_fabreadmit_crash_resume_revocation_rechecked_blocks",
        f"{_CONSUMER_FILE}::test_fabreadmit_real_git_shortcut_end_to_end",
        f"{_PROMOTION_FILE}::test_fabreadmit_hardcoded_epoch_publisher_interlock",
        f"{_PROMOTION_FILE}::test_fabreadmit_flag_reversal_kills_shortcut",
        f"{_LEAK_FILE}::test_fabreadmit_flag_off_recovery_leak_guard",
        f"{_TRAIN_FILE}::test_fabreadmit_train_runner_commit_broker_readmitted_head_routing",
        f"{_PREMERGE_FILE}::test_fabreadmit_governed_premerge_readiness_interlock",
    ))
)

FABREADMIT_RED_NODEIDS = FABREADMIT_NEW_PRODUCTION_NODEIDS
FABREADMIT_EXPECTED_NODEIDS = FABREADMIT_RED_NODEIDS

FABREADMIT_NEW_PRODUCTION_COUNT = len(FABREADMIT_NEW_PRODUCTION_NODEIDS)
FABREADMIT_RED_COUNT = len(FABREADMIT_RED_NODEIDS)
FABREADMIT_EXPECTED_COUNT = len(FABREADMIT_EXPECTED_NODEIDS)


def fabreadmit_inventory_digest(values: Iterable[str]) -> str:
    joined = "\n".join(sorted(values)) + "\n"
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


FABREADMIT_OWNED_PATHS = (
    "CHANGELOG.md",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py",
    "phase-loop-runtime/src/phase_loop_runtime/convergence/contracts.py",
    "phase-loop-runtime/src/phase_loop_runtime/fabreadmit_capability.py",
    "phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py",
    "phase-loop-runtime/src/phase_loop_runtime/train_runner.py",
    "phase-loop-runtime/tests/_fabreadmit_tdd_guard.py",
    "phase-loop-runtime/tests/test_convergence_broker_admission.py",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py",
    "phase-loop-runtime/tests/test_convergence_broker_verbs.py",
    "phase-loop-runtime/tests/test_fab_activation_promotion.py",
    "phase-loop-runtime/tests/test_fab_delta_consumer.py",
    "phase-loop-runtime/tests/test_fab_flag_off_recovery_leak_299.py",
    "phase-loop-runtime/tests/test_fabreadmit_broker.py",
    "phase-loop-runtime/tests/test_governed_premerge.py",
    "phase-loop-runtime/tests/test_train_runner.py",
)

FABREADMIT_TEST_PATHS = tuple(
    sorted(p for p in FABREADMIT_OWNED_PATHS if p.startswith("phase-loop-runtime/tests/"))
)

FABREADMIT_OWNED_PATHS_COUNT = len(FABREADMIT_OWNED_PATHS)
FABREADMIT_TEST_PATHS_COUNT = len(FABREADMIT_TEST_PATHS)

FABREADMIT_OWNED_PATHS_SHA256 = fabreadmit_inventory_digest(FABREADMIT_OWNED_PATHS)
FABREADMIT_TEST_PATHS_SHA256 = fabreadmit_inventory_digest(FABREADMIT_TEST_PATHS)
FABREADMIT_RED_NODEIDS_SHA256 = fabreadmit_inventory_digest(FABREADMIT_RED_NODEIDS)


# ---------------------------------------------------------------------------
# Unique RED anchors
# ---------------------------------------------------------------------------

def _anchor(slug: str) -> str:
    return f"FABREADMIT-RED-ANCHOR::{slug}"


FABREADMIT_RED_ANCHORS: dict[str, str] = {
    f"{_BROKER_FILE}::test_fabreadmit_broker_authority_receipt_contract": _anchor("broker_authority_receipt_contract"),
    f"{_BROKER_FILE}::test_fabreadmit_broker_rediffs_head_range_and_rejects_scope_escape_without_adapter": _anchor("broker_scope_rediff_no_adapter"),
    f"{_ADM_FILE}::test_fabreadmit_prior_record_predicate_and_chained_readmit_binding": _anchor("prior_record_predicate_chained_binding"),
    f"{_ADM_FILE}::test_fabreadmit_checkpoint_root_validation": _anchor("checkpoint_root_validation"),
    f"{_ADM_FILE}::test_fabreadmit_linked_worktrees_share_canonical_repository_allocator": _anchor("shared_canonical_allocator"),
    f"{_VERBS_FILE}::test_fabreadmit_readmit_advanced_head_verb": _anchor("readmit_advanced_head_verb"),
    f"{_RACE_FILE}::test_fabreadmit_revocation_race_under_admission_lock": _anchor("revocation_race_under_lock"),
    f"{_CONSUMER_FILE}::test_fabreadmit_commit_points_reach_commit_broker_readmitted_head": _anchor("commit_points_reach_commit_helper"),
    f"{_CONSUMER_FILE}::test_fabreadmit_append_site_inventory": _anchor("append_site_inventory"),
    f"{_CONSUMER_FILE}::test_fabreadmit_append_site_inventory_detects_third_site": _anchor("append_site_inventory_third_site"),
    f"{_CONSUMER_FILE}::test_fabreadmit_fresh_revocation_blocks_delta_merge": _anchor("fresh_revocation_blocks_merge"),
    f"{_CONSUMER_FILE}::test_fabreadmit_crash_resume_revocation_rechecked_blocks": _anchor("crash_resume_revocation_blocks"),
    f"{_CONSUMER_FILE}::test_fabreadmit_real_git_shortcut_end_to_end": _anchor("real_git_shortcut_end_to_end"),
    f"{_PROMOTION_FILE}::test_fabreadmit_hardcoded_epoch_publisher_interlock": _anchor("hardcoded_epoch_interlock"),
    f"{_PROMOTION_FILE}::test_fabreadmit_flag_reversal_kills_shortcut": _anchor("flag_reversal_kills_shortcut"),
    f"{_LEAK_FILE}::test_fabreadmit_flag_off_recovery_leak_guard": _anchor("flag_off_recovery_leak_guard"),
    f"{_TRAIN_FILE}::test_fabreadmit_train_runner_commit_broker_readmitted_head_routing": _anchor("train_runner_readmit_routing"),
    f"{_PREMERGE_FILE}::test_fabreadmit_governed_premerge_readiness_interlock": _anchor("governed_premerge_readiness_interlock"),
}

FABREADMIT_NODEID_PREFIX = "phase-loop-runtime/"


def fabreadmit_repo_relative_nodeid(nodeid: str) -> str:
    normalized = nodeid.replace("\\", "/")
    if normalized.startswith(FABREADMIT_NODEID_PREFIX):
        return normalized
    if normalized.startswith("tests/"):
        return FABREADMIT_NODEID_PREFIX + normalized
    return normalized


def fabreadmit_local_nodeid(nodeid: str) -> str:
    normalized = nodeid.replace("\\", "/")
    if normalized.startswith(FABREADMIT_NODEID_PREFIX):
        return normalized[len(FABREADMIT_NODEID_PREFIX) :]
    return normalized


def fabreadmit_this_nodeid(request) -> str:
    return fabreadmit_repo_relative_nodeid(request.node.nodeid)


# ---------------------------------------------------------------------------
# Guard integrity test (runs always, never skipped)
# ---------------------------------------------------------------------------


def test_fabreadmit_guard_inventory_and_digests():
    assert FABREADMIT_RED_COUNT == 18
    assert len(FABREADMIT_RED_ANCHORS) == FABREADMIT_RED_COUNT
    for nodeid in FABREADMIT_RED_NODEIDS:
        assert nodeid in FABREADMIT_RED_ANCHORS, f"Missing anchor for {nodeid}"
    assert fabreadmit_inventory_digest(FABREADMIT_OWNED_PATHS) == FABREADMIT_OWNED_PATHS_SHA256
    assert fabreadmit_inventory_digest(FABREADMIT_TEST_PATHS) == FABREADMIT_TEST_PATHS_SHA256
    assert fabreadmit_inventory_digest(FABREADMIT_RED_NODEIDS) == FABREADMIT_RED_NODEIDS_SHA256
