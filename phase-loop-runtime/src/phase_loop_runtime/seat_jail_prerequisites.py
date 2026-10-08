"""Prerequisites of the seat jail's qualification that live in the runtime's own environment.

The qualification runs a real falsifier run (agent-harness#1132), and the run's trusted wrapper
imports `pytest`. The run executes without site processing, so its dependencies are copied from
the runtime's environment (or the system interpreter's site-packages) by
`review_stage._snapshot_falsifier_dependencies`, which skips what it cannot find and leaves the
failure to the run. Until `pytest` became a runtime dependency (agent-harness#1357), a host
installed from the published package had no `pytest` anywhere, so the qualification could not
start and the failure read as "report a defect".

This module is the one place that knows what is needed and what to tell the operator, so the
qualification, the typed reason and `phase-loop doctor` cannot disagree. Its text carries no
absolute path: `doctor` output is metadata-only.
"""

from __future__ import annotations

import subprocess
from typing import Any

#: What the operator should run when `pytest` is missing from the runtime's environment.
PYTEST_FIX = (
    "pytest is not installed in the runtime's environment, and the seat jail's falsifier run "
    "needs it (releases after 0.7.25 depend on it). Upgrade the runtime: "
    "`uv tool upgrade phase-loop-runtime` for a uv tool install, or "
    "`pip install --upgrade phase-loop-runtime` in the runtime's environment. For an earlier "
    "release, add it: `uv tool install --reinstall --with 'pytest>=8,<9' phase-loop-runtime`, "
    "or `pip install 'pytest>=8,<9'`. Then run `phase-loop seat-sandbox qualify`"
)

_UNLOCKS = "seat-jail qualification (jailed Claude review seats)"


def pytest_status() -> str:
    """``present``, ``missing`` or ``unknown`` (the dependency inventory could not run)."""
    from . import review_stage

    try:
        return "present" if review_stage.falsifier_distribution_available("pytest") else "missing"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown"


def missing() -> list[str]:
    """The names of the prerequisites known to be missing (never raises)."""
    return ["pytest"] if pytest_status() == "missing" else []


def check() -> list[dict[str, Any]]:
    """The prerequisite report `phase-loop doctor` embeds. Metadata-only: no paths."""
    status = pytest_status()
    entry: dict[str, Any] = {"name": "pytest", "status": status, "unlocks": _UNLOCKS}
    if status == "missing":
        entry["fix"] = PYTEST_FIX
    return [entry]
