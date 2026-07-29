"""Shared stash key proving the conftest contract-floor preflight actually RAN.

Consiliency/agent-harness#378 board #382 r3, Blocker 2 (wiring row). The floor guard
has three failure surfaces that must each be sentineled: the declared floor, the
installed version, AND the conftest wiring that invokes the check. A guard that is never
CALLED is indistinguishable from a guard that passes, so suppressing the
``pytest_configure`` invocation left all operand tests green. ``conftest.pytest_configure``
sets ``config.stash[CONTRACT_FLOOR_PREFLIGHT_RAN] = True`` immediately after the check
runs without aborting; ``test_conftest_actually_invokes_the_floor_preflight`` reads it
back. Deleting the invocation leaves the key unset and reds that test.

The key lives here, not in ``conftest.py``, because pytest can load ``conftest`` under
its own plugin machinery, and a separate ``import conftest`` from a test could bind a
DIFFERENT module object -- a distinct ``StashKey`` identity that never matches the one the
hook set. Both sides import the single key from this module, so the identity is shared.
"""
from __future__ import annotations

import pytest

# StashKey identity is what pairs the set (in conftest) with the read (in the test);
# both import THIS object, never re-construct it.
CONTRACT_FLOOR_PREFLIGHT_RAN: "pytest.StashKey[bool]" = pytest.StashKey()
