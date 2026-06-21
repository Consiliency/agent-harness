from __future__ import annotations

import os


def branchgov_enabled() -> bool:
    return os.environ.get("PHASE_LOOP_BRANCHGOV_ENABLE") != "false"


def trust_executor_evidence_enabled() -> bool:
    return os.environ.get("PHASE_LOOP_TRUST_EXECUTOR_EVIDENCE") != "false"


def allow_lane_ir_override_enabled() -> bool:
    return os.environ.get("PHASE_LOOP_ALLOW_LANE_IR_OVERRIDE") != "false"


def dispatch_lock_enabled() -> bool:
    return os.environ.get("PHASE_LOOP_DISPATCH_LOCK") != "false"


def parallel_dispatch_enabled() -> bool:
    return os.environ.get("PHASE_LOOP_PARALLEL_DISPATCH") != "false"


def reconcile_git_reality_enabled() -> bool:
    # SAFE CUTOVER: defaults OFF (opt-in), unlike the flags above. The active body
    # wires into classify_phase — the universal classifier — so on our own runtime
    # the feature lands inert and is flipped on deliberately after validation.
    return os.environ.get("PHASE_LOOP_RECONCILE_GIT_REALITY") == "true"
