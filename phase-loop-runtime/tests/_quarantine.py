"""Pull-request deselection of known flakes (agent-harness#1029).

A test marked ``@pytest.mark.quarantine(reason="agent-harness#N")`` is a known flake. When
``PHASE_LOOP_DESELECT_QUARANTINE=1`` (set by test.yml on pull_request only), collection drops
exactly the marked items -- by marker, never by node-ID prefix -- and reports them as
deselected. More than ``QUARANTINE_CAP`` marked nodes (each parametrized case counts) aborts
collection: the register is debt, not an off switch. A mark inherited from a class or module
is refused on every run (``refuse_inherited_quarantine``). Any other value (test.yml passes ``0`` off pull requests; Gate A,
publish-pypi and the offload path never set it) runs them.
"""
from __future__ import annotations

import os

import pytest

QUARANTINE_ENV = "PHASE_LOOP_DESELECT_QUARANTINE"
QUARANTINE_CAP = 5


def _quarantined(item) -> bool:
    closest = getattr(item, "get_closest_marker", None)  # unit tests pass minimal items
    return closest is not None and closest("quarantine") is not None


def refuse_inherited_quarantine(items) -> None:
    """Every run: a quarantine mark must sit on the test itself (or its pytest.param),
    never be inherited from a class or module -- however it was spelled
    (agent-harness#1038 / #1044 r1: `m = mark.quarantine(...)` then `@m` on a class
    evades any text scan). pytest keeps a test's own and param marks in own_markers."""
    inherited = [item.nodeid for item in items if _quarantined(item)
                 and not any(m.name == "quarantine" for m in getattr(item, "own_markers", ()))]
    if inherited:
        raise pytest.UsageError(
            f"quarantine is inherited from a class or module by {len(inherited)} test(s), e.g. "
            f"{inherited[0]} -- quarantine one test at a time"
        )


def deselect_quarantined(config, items, environ=os.environ) -> list:
    """Remove quarantine-marked items in place when enabled; return the removed items."""
    refuse_inherited_quarantine(items)
    if environ.get(QUARANTINE_ENV) != "1":
        return []
    marked = [item for item in items if _quarantined(item)]
    if len(marked) > QUARANTINE_CAP:
        raise pytest.UsageError(
            f"{len(marked)} quarantined test nodes (cap {QUARANTINE_CAP}; every parametrized "
            "case counts) -- fix one before adding another"
        )
    if marked:
        dropped = {id(item) for item in marked}
        items[:] = [item for item in items if id(item) not in dropped]
        config.hook.pytest_deselected(items=marked)
    return marked
