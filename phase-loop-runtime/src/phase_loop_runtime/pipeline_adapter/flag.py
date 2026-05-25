from __future__ import annotations

import os


def branchgov_enabled() -> bool:
    return os.environ.get("PHASE_LOOP_BRANCHGOV_ENABLE") != "false"


def trust_executor_evidence_enabled() -> bool:
    return os.environ.get("PHASE_LOOP_TRUST_EXECUTOR_EVIDENCE") == "true"
