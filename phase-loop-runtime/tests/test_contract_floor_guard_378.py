"""Consiliency/agent-harness#378: guard that the installed ``consiliency-contract``
satisfies this package's declared floor, failing readably instead of fanning a
stale-dependency mismatch out into dozens of opaque ``jsonschema`` errors.

The failure #378 documents is dependency-state-dependent, not code-dependent.
An installed ``consiliency-contract`` below the repo's declared floor
(``pyproject`` ``>=0.6.5,<0.7``) can be internally inconsistent -- e.g. ``0.6.0``
ships ``CONTRACT_VERSION="0.6.0"`` against a bundled manifest schema still pinned
to ``^0\\.4\\.\\d+$`` -- and one ``ValidationError`` fans out across ~60 node IDs.
That is why the reporter saw it on a docs-only branch: a stale package in
``~/.local`` fails every checkout identically. On ``main`` in CI (which installs
``0.6.5`` from ``pyproject``) the count is 0.

These tests pin the PURE floor check with literals so the falsifier runs
deterministically in CI regardless of which contract version happens to be
installed there.
"""
from __future__ import annotations

import pytest

from phase_loop_runtime.consiliency_layout import (
    ContractFloorError,
    assert_contract_floor_satisfied,
    check_installed_contract_floor,
    declared_contract_requirement,
)

# The exact requirement this repo declares (name + specifier). Held as a literal
# here so the discrimination test does not depend on ambient metadata.
_REQ = "consiliency-contract>=0.6.5,<0.7"


def test_below_floor_raises_with_actionable_message():
    # 0.6.0 is the exact stale version that produced #378's 74-failure baseline.
    with pytest.raises(ContractFloorError) as exc:
        assert_contract_floor_satisfied("0.6.0", _REQ)
    msg = str(exc.value)
    assert "0.6.0" in msg  # names the offending installed version
    assert "0.6.5" in msg  # names the floor so the reader knows the fix


def test_at_floor_passes():
    # 0.6.5 is the only floor-satisfying version on PyPI; it must NOT raise.
    assert assert_contract_floor_satisfied("0.6.5", _REQ) is None


def test_above_floor_within_range_passes():
    assert assert_contract_floor_satisfied("0.6.9", _REQ) is None


def test_at_ceiling_raises():
    # The ``<0.7`` ceiling must fail closed too: a guard that only catches the
    # lower bound would silently admit an out-of-range major/minor.
    with pytest.raises(ContractFloorError):
        assert_contract_floor_satisfied("0.7.0", _REQ)


def test_declared_requirement_read_from_metadata_not_hardcoded():
    # The floor must come from the package's declared dependency metadata so the
    # guard cannot drift from pyproject. In every environment the suite runs
    # (CI pip-install, clean-room wheel, editable source) the dist is installed.
    req = declared_contract_requirement()
    assert req is not None
    assert "consiliency-contract" in req.lower()
    assert ">=0.6.5" in req.replace(" ", "")


def test_check_fires_on_a_stale_ambient_install(monkeypatch):
    # Injection-anchor proof for the wiring the conftest hook depends on: feed the
    # check a stale ambient version and a readable floor, and it must raise. This
    # is the env-independent stand-in for the collection-time abort.
    import phase_loop_runtime.consiliency_layout as cl

    monkeypatch.setattr(cl, "_installed_contract_dist_version", lambda: "0.6.0")
    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: _REQ)
    with pytest.raises(ContractFloorError):
        cl.check_installed_contract_floor()


def test_check_is_noop_when_state_is_unprovable(monkeypatch):
    # Never fail on an unprovable state: if the declared floor or the installed
    # version cannot be read, the guard is a silent no-op (fail-open), because it
    # cannot demonstrate a violation.
    import phase_loop_runtime.consiliency_layout as cl

    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: None)
    assert cl.check_installed_contract_floor() is None

    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: _REQ)
    monkeypatch.setattr(cl, "_installed_contract_dist_version", lambda: None)
    assert cl.check_installed_contract_floor() is None
