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

The pure-mechanics tests (below/at/above/ceiling) drive ``assert_contract_floor_satisfied``
with a SYNTHETIC specifier that is deliberately NOT this repo's floor, so they test
the checker's logic without duplicating the declared floor (board #382 r1 Finding 2:
a second literal copy of the real floor is a fossil that keeps passing when the floor
moves). The one test that pins the REAL floor derives it from ``pyproject.toml`` (the
single source of truth) and compares the runtime's metadata-derived answer against it
-- two independent artifacts, so it catches both a stale ``.egg-info`` and a runtime
extraction bug.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from phase_loop_runtime.consiliency_layout import (
    ContractFloorError,
    ContractFloorUnverified,
    assert_contract_floor_satisfied,
    declared_contract_requirement,
)

# A synthetic requirement for the pure-checker tests. It is NOT the repo floor:
# these tests probe the specifier-matching mechanics, not the declared version, so
# they must not carry a second copy of the real floor (which would fossilise).
_SYNTHETIC_REQ = "consiliency-contract>=2.0,<3"


def _requirement_from_pyproject() -> str | None:
    """The ``consiliency-contract`` requirement declared in the SOURCE
    ``pyproject.toml`` -- the single source of truth the runtime must agree with.
    Returns ``None`` when ``pyproject`` is not adjacent to the imported module
    (the extracted clean-room wheel does not ship it), mirroring the conftest's
    standalone-layout handling."""
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        import tomli as tomllib  # 3.10 backport (a dev/test dependency)

    import phase_loop_runtime

    # src/phase_loop_runtime/__init__.py -> ../../pyproject.toml
    pyproject = Path(phase_loop_runtime.__file__).resolve().parents[2] / "pyproject.toml"
    if not pyproject.is_file():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    for dep in data.get("project", {}).get("dependencies", ()):
        if dep.replace(" ", "").lower().startswith("consiliency-contract"):
            return dep
    return None


def test_below_floor_raises_with_actionable_message():
    # Pure mechanics: a version below the synthetic floor raises, and the message
    # names both the offending version and the specifier so the reader knows the fix.
    with pytest.raises(ContractFloorError) as exc:
        assert_contract_floor_satisfied("1.9", _SYNTHETIC_REQ)
    msg = str(exc.value)
    assert "1.9" in msg  # names the offending installed version
    assert _SYNTHETIC_REQ in msg  # echoes the (derived, not re-encoded) floor


def test_at_floor_passes():
    assert assert_contract_floor_satisfied("2.0", _SYNTHETIC_REQ) is None


def test_above_floor_within_range_passes():
    assert assert_contract_floor_satisfied("2.5", _SYNTHETIC_REQ) is None


def test_at_ceiling_raises():
    # The upper bound must fail closed too: a guard that only catches the lower
    # bound would silently admit an out-of-range major/minor.
    with pytest.raises(ContractFloorError):
        assert_contract_floor_satisfied("3.0", _SYNTHETIC_REQ)


def test_declared_requirement_matches_pyproject_source():
    # Board #382 r1 Finding 2: the floor has ONE source (pyproject). The runtime
    # reads it back from provenance-verified dist metadata; this asserts that
    # metadata-derived answer equals the pyproject declaration. Non-vacuous because
    # the two sides are independent artifacts (metadata is built FROM pyproject, but
    # a stale .egg-info or an extraction bug makes them disagree).
    from packaging.requirements import Requirement

    pyproject_req = _requirement_from_pyproject()
    if pyproject_req is None:
        pytest.skip("pyproject.toml not adjacent (extracted clean-room wheel)")
    runtime_req = declared_contract_requirement()
    if runtime_req is None:
        pytest.skip("declared floor unprovable in this env (metadata/module divergence)")
    # Compare on parsed specifier + name, not raw string, so formatting differences
    # (ordering, spaces) do not mask or manufacture a mismatch.
    assert Requirement(runtime_req).name == Requirement(pyproject_req).name
    assert str(Requirement(runtime_req).specifier) == str(Requirement(pyproject_req).specifier)


def test_check_fires_on_a_stale_ambient_install(monkeypatch):
    # Injection-anchor proof for the wiring the conftest hook depends on: feed the
    # check a stale ambient version and a readable floor, and it must raise. This
    # is the env-independent stand-in for the collection-time abort.
    import phase_loop_runtime.consiliency_layout as cl

    # Below the synthetic floor; the installed operand is the IMPORTED contract
    # version (see test_floor_is_checked_against_imported_contract_version...).
    monkeypatch.setattr(cl, "installed_contract_version", lambda: "1.0")
    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: _SYNTHETIC_REQ)
    with pytest.raises(ContractFloorError):
        cl.check_installed_contract_floor()


def test_check_warns_and_noops_when_state_is_unprovable(monkeypatch):
    # Never fail on an unprovable state -- but never SILENTLY no-op either (board
    # #382 ruling). If the declared floor or the installed version cannot be read,
    # the guard does not raise (fail-open) AND emits ContractFloorUnverified, so the
    # check's absence is visible instead of masquerading as a clean pass.
    import phase_loop_runtime.consiliency_layout as cl

    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: None)
    with pytest.warns(ContractFloorUnverified):
        assert cl.check_installed_contract_floor() is None

    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: _SYNTHETIC_REQ)
    monkeypatch.setattr(cl, "installed_contract_version", lambda: None)
    with pytest.warns(ContractFloorUnverified):
        assert cl.check_installed_contract_floor() is None


def test_check_does_not_warn_when_floor_is_verified(monkeypatch):
    # Non-vacuity for the warning: it must be CONDITIONAL on the unprovable state,
    # not unconditional. With both operands readable and the floor satisfied, the
    # guard runs cleanly -- no raise and NO ContractFloorUnverified. This is what
    # keeps the warning off the normal in-tree suite (where provenance holds).
    import warnings

    import phase_loop_runtime.consiliency_layout as cl

    monkeypatch.setattr(cl, "installed_contract_version", lambda: "2.5")
    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: _SYNTHETIC_REQ)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ContractFloorUnverified)
        assert cl.check_installed_contract_floor() is None


# ---------------------------------------------------------------------------
# Board #382 r1 Finding 1 — metadata-vs-imported-module provenance.
# ---------------------------------------------------------------------------
class _ForeignDist:
    """A ``phase-loop-runtime`` distribution whose recorded files live somewhere
    OTHER than the imported ``phase_loop_runtime`` package — i.e. an installed
    dist shadowed by a src/ checkout (the board's env: src 0.7.13, installed
    0.7.10). Its ``requires`` names an obviously-foreign floor so a guard that
    trusts it by NAME is caught red-handed."""

    _FOREIGN_ROOT = Path("/nonexistent/site-packages")

    @property
    def requires(self):
        return ["consiliency-contract>=9.9,<10"]

    def locate_file(self, path):
        return self._FOREIGN_ROOT / path


def _install_metadata_module_divergence(monkeypatch):
    """Make ONLY ``phase-loop-runtime`` metadata resolve to a dist that does NOT
    own the imported module; every OTHER name (notably ``consiliency-contract``,
    read by ``md.version`` for the installed-version operand) passes through to
    the real resolver. Scoping by name matters: a blanket patch would also hijack
    the contract-version read and make the false-failure assertion pass for the
    WRONG reason. Patches BOTH access seams so the assertion discriminates old
    (name-based ``md.requires``) from fixed (provenance-checked ``md.distribution``)."""
    import importlib.metadata as md

    _real_requires = md.requires
    _real_distribution = md.distribution

    def _requires(name):
        if name == "phase-loop-runtime":
            return _ForeignDist().requires
        return _real_requires(name)

    def _distribution(name):
        if name == "phase-loop-runtime":
            return _ForeignDist()
        return _real_distribution(name)

    monkeypatch.setattr(md, "requires", _requires, raising=True)
    monkeypatch.setattr(md, "distribution", _distribution, raising=True)


def test_declared_requirement_is_none_when_metadata_does_not_own_imported_module(monkeypatch):
    # FALSIFIER for Finding 1. The declared floor must come from the dist that
    # PROVABLY owns the imported code, never from whatever install answers to the
    # name. Under divergence the guard cannot know the running code's floor, so it
    # returns None (fail-open) rather than a foreign specifier.
    # RED on be92ae2: name-based md.requires returns "consiliency-contract>=9.9,<10".
    import phase_loop_runtime.consiliency_layout as cl

    _install_metadata_module_divergence(monkeypatch)
    assert cl.declared_contract_requirement() is None


def test_check_does_not_spuriously_abort_under_metadata_module_divergence(monkeypatch):
    # The false-failure half of #378's acceptance, driven through the CONFTEST
    # COLLECTION SURFACE (check_installed_contract_floor), not just the helper.
    # A stale-shadow env must not make a healthy checkout abort collection -- and
    # per the board #382 ruling it must WARN rather than pass silently, so the
    # operator sees the floor went unverified in exactly the shadowed-runtime case.
    # RED on be92ae2: the foreign >=9.9 floor is not satisfied by the real
    # CONTRACT_VERSION, so the guard raised ContractFloorError spuriously.
    import phase_loop_runtime.consiliency_layout as cl

    _install_metadata_module_divergence(monkeypatch)
    with pytest.warns(ContractFloorUnverified):
        assert cl.check_installed_contract_floor() is None  # warn + no-op, not a raise


def test_floor_is_checked_against_imported_contract_version_not_dist_metadata(monkeypatch):
    # FALSIFIER for the same class on the higher-stakes operand (board #382 r1
    # advisor note): the schemas that fan out #378's failures come from the
    # IMPORTED consiliency_contract module (CONTRACT_VERSION), not its dist
    # metadata. In a contract-shadow the IMPORTED version is stale (0.6.0) while
    # the dist metadata reads fresh. The guard must fire on what will RUN.
    # RED on be92ae2: that code read the DIST-metadata version (fresh, satisfies
    # the floor) and missed the stale imported contract -- it ignores this patch
    # of installed_contract_version entirely.
    import phase_loop_runtime.consiliency_layout as cl

    monkeypatch.setattr(cl, "installed_contract_version", lambda: "0.6.0")
    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: "consiliency-contract>=0.6.5,<0.7")
    with pytest.raises(ContractFloorError):
        cl.check_installed_contract_floor()
