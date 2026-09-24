"""Pull-request deselection of known flakes (agent-harness#1029).

A test marked ``@pytest.mark.quarantine(reason="agent-harness#N")`` is a known flake. When
``PHASE_LOOP_DESELECT_QUARANTINE=1`` (set by test.yml on pull_request only), collection drops
exactly the marked items -- by marker, never by node-ID prefix -- and reports them as
deselected. More than ``QUARANTINE_CAP`` marked nodes aborts collection: the register is
debt, not an off switch. Push, nightly and Gate A leave the variable unset and run them.
"""
from __future__ import annotations

import os

import pytest

QUARANTINE_ENV = "PHASE_LOOP_DESELECT_QUARANTINE"
QUARANTINE_CAP = 5


def deselect_quarantined(config, items, environ=os.environ) -> list:
    """Remove quarantine-marked items in place when enabled; return the removed items."""
    if environ.get(QUARANTINE_ENV) != "1":
        return []
    marked = [item for item in items if item.get_closest_marker("quarantine") is not None]
    if len(marked) > QUARANTINE_CAP:
        raise pytest.UsageError(
            f"{len(marked)} quarantined test nodes (cap {QUARANTINE_CAP}; a class or module "
            "mark counts per node) -- fix one before adding another"
        )
    if marked:
        dropped = {id(item) for item in marked}
        items[:] = [item for item in items if id(item) not in dropped]
        config.hook.pytest_deselected(items=marked)
    return marked
