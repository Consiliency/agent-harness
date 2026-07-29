"""Consiliency/agent-harness#378: guard that the installed ``consiliency-contract``
satisfies this package's declared floor, failing readably instead of fanning a
stale-dependency mismatch out into dozens of opaque ``jsonschema`` errors.

The failure #378 documents is dependency-state-dependent, not code-dependent.
An installed ``consiliency-contract`` below the repo's declared floor can be
internally inconsistent -- e.g. the reporter's stale ``0.6.0`` shipped
``CONTRACT_VERSION="0.6.0"`` against a bundled manifest schema still pinned to
``^0\\.4\\.\\d+$`` -- and one ``ValidationError`` fans out across ~60 node IDs.
That is why the reporter saw it on a docs-only branch: a stale package in
``~/.local`` fails every checkout identically. On ``main`` in CI (which installs the
floor-satisfying contract from ``pyproject``) the count is 0. The floor VALUE lives
in exactly one place -- ``pyproject.toml`` ``[project.dependencies]`` -- and this
file never re-encodes it as an authority (board #382 r1/r2 Finding 2).

The pure-mechanics tests (below/at/above/ceiling) drive ``assert_contract_floor_satisfied``
with a SYNTHETIC specifier that is deliberately NOT this repo's floor, so they test
the checker's logic without carrying a copy of the declared floor. The single-source
invariant is NOT enforced by counting literal copies (a scenario constant in a
``monkeypatch`` is not a source of truth, and would keep passing correctly if the
real floor moved); it is enforced by ONE live comparison -- the runtime's
metadata-derived floor vs the ``pyproject`` declaration -- and board #382 r2 Finding 3
showed that comparison could ``pytest.skip`` itself into vacuity. So that comparison
now FAILS (never skips) whenever provenance is provable, which is exactly when the
guard could have run. See ``test_declared_floor_is_provable_and_single_sourced``.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from phase_loop_runtime.consiliency_layout import (
    ContractFloorError,
    ContractFloorMetadataDivergence,
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


def _provenance_provable() -> bool:
    """The INDEPENDENT licensing condition for the anti-hollow assertions below:
    the resolved ``phase-loop-runtime`` distribution provably owns the imported
    module. Computed via ``_dist_owns_imported_runtime`` -- a DIFFERENT function
    from ``declared_contract_requirement``, so an always-``None`` regression on the
    latter leaves this ``True`` and the assertion still fires (non-vacuous)."""
    import importlib.metadata as md

    import phase_loop_runtime.consiliency_layout as cl

    try:
        return cl._dist_owns_imported_runtime(md.distribution("phase-loop-runtime"))
    except Exception:
        return False


def test_real_dist_owns_imported_module():
    # ANTI-HOLLOW sentinel (board #382 r2 Finding 3), False-direction. In EVERY env
    # this suite runs -- local src ``.egg-info``, the CI wheel matrix, the clean-room
    # wheel -- the resolved distribution MUST own the imported module (both verified
    # empirically: co-located dist-info/egg-info + a RECORD/SOURCES entry for the
    # package). Catches a regression that disables provenance by making
    # ``_dist_owns_imported_runtime`` always return False -- which would make the
    # guard silently skip everywhere while the None-direction test below just skips.
    assert _provenance_provable() is True


def test_declared_floor_is_provable_and_single_sourced():
    # ANTI-HOLLOW sentinel (board #382 r2 Finding 3), None-direction. Round 1 skipped
    # when ``declared_contract_requirement()`` returned None; codex showed that let an
    # always-None regression -- a guard that never runs -- pass CI green (10 passed,
    # 1 skipped). The fix: when provenance is provable (the exact condition under which
    # the guard COULD run), a None floor is a FAILURE, not a skip. This is the layer
    # this sentinel binds: floor-is-readable-when-the-guard-could-run; the layer above
    # (that the readable floor IS the pin, not stale metadata) is bound by the r5
    # divergence falsifiers below, not here.
    #
    # WHAT THE r5 FIX CHANGED THIS SENTINEL TO TRUST (discipline #2): pre-r5 this test
    # also compared the runtime floor to ``_requirement_from_pyproject()`` -- a live,
    # non-vacuous check, because ``declared_contract_requirement()`` returned the DIST
    # METADATA floor, an independent artifact that a stale .egg-info could make disagree
    # with pyproject. Under the r5 maintainer ruling ``declared_contract_requirement()``
    # RETURNS the adjacent pin by construction (the pin governs, metadata is
    # corroboration), so that equality is now a tautology (pin == pin) and is REMOVED
    # rather than left as a silent-green check. The non-vacuous single-source binding --
    # that the pin OVERRIDES divergent metadata in both directions -- now lives in
    # test_floor_governed_by_pyproject_over_stale_{newer,older}_metadata, which feed
    # metadata that DISAGREES with the pin and assert the pin wins.
    if not _provenance_provable():
        # Provenance genuinely unprovable here; test_real_dist_owns_imported_module
        # is the sentinel that flags that as an env regression, so skipping here is
        # safe (it cannot hide a hollow guard).
        pytest.skip("provenance not provable in this env (flagged by the owns-sentinel)")
    runtime_req = declared_contract_requirement()
    # The anti-hollow core: provable provenance but a None floor == the guard is
    # hollow (never runs). This is what goes RED under the always-None mutation.
    assert runtime_req is not None, (
        "provenance is provable but declared_contract_requirement() is None -- the "
        "contract-floor guard is HOLLOW (it never runs). See board #382 r2 Finding 3."
    )


class _StaleMetadataDist:
    """A dist whose ``.requires`` declares a contract floor DIFFERENT from the pin.

    Models the gitignored, install-stale co-located ``.egg-info`` at the heart of
    board #382 r5 Blocker 1: it can name a floor the pyproject pin never set.
    Ownership is forced True by the tests (via monkeypatch) so the fake metadata is
    consulted through the real ``declared_contract_requirement`` code path, while the
    REAL adjacent pyproject on disk supplies the governing pin.
    """

    version = "0.0-test"

    def __init__(self, floor: str):
        self._floor = floor

    @property
    def requires(self):
        return [self._floor]


def _pyproject_pin() -> str:
    from packaging.requirements import Requirement

    pin = _requirement_from_pyproject()
    if pin is None:  # clean-room wheel: no adjacent pyproject to govern
        pytest.skip("pyproject.toml not adjacent (clean-room wheel); pin not comparable")
    return str(Requirement(pin).specifier)


def test_floor_governed_by_pyproject_over_stale_newer_metadata(monkeypatch):
    # BLOCKER 1 FALSIFIER -- stale-NEWER direction (board #382 r5, maintainer ruling
    # 2026-07-29). LAYER this binds: floor SOURCE-of-authority -- when the co-located
    # egg-info metadata disagrees with the adjacent pin, the PIN governs. The layer it
    # replaces: the r4 metadata-only floor, which trusted whatever the (gitignored,
    # install-stale) egg-info said. A stale-NEWER metadata floor (>=9.9) there would
    # FALSE-ABORT a healthy checkout; warn-and-skip (the alternative the ruling
    # rejected) would instead go silent. Ruling: enforce the pin, warn on divergence.
    # RED before the fix (metadata governed): declared_contract_requirement() -> >=9.9,
    # the guard aborts a healthy 0.6.5 install.
    from packaging.requirements import Requirement

    import phase_loop_runtime.consiliency_layout as cl

    import importlib.metadata as md

    pin_spec = _pyproject_pin()  # real pin, e.g. >=0.6.5,<0.7
    monkeypatch.setattr(cl, "_dist_owns_imported_runtime", lambda dist: True)
    monkeypatch.setattr(
        md,
        "distribution",
        lambda name: _StaleMetadataDist("consiliency-contract>=9.9,<10"),
        raising=True,
    )

    # Divergence is named (never silenced) and the returned floor is the PIN, not 9.9.
    with pytest.warns(ContractFloorMetadataDivergence):
        req = cl.declared_contract_requirement()
    assert req is not None
    assert str(Requirement(req).specifier) == pin_spec, (
        "stale-NEWER metadata must not govern -- the adjacent pyproject pin does. "
        "Board #382 r5 Blocker 1."
    )

    # End to end: a healthy install that SATISFIES the pin must NOT abort, even though
    # the stale metadata floor (>=9.9) would have. (The check re-emits the divergence
    # warning; catching it here also asserts it stays non-silent on the enforce path.)
    with pytest.warns(ContractFloorMetadataDivergence):
        assert cl.check_installed_contract_floor() is None


def test_floor_governed_by_pyproject_over_stale_older_metadata(monkeypatch):
    # BLOCKER 1 FALSIFIER -- stale-OLDER direction (board #382 r5, maintainer ruling).
    # LAYER this binds: the SILENT-UNDER-ENFORCEMENT hole warn-and-skip would have left
    # open. A stale-OLDER metadata floor (>=0.6.0) with a below-pin installed contract
    # (0.6.0, under the real >=0.6.5 pin) is the case where warn-and-skip returns None
    # and the guard PASSES a contract #378 exists to reject. Enforcing the pin makes the
    # guard FIRE. RED if the pin does not govern (metadata >=0.6.0 is satisfied by 0.6.0
    # -> no error).
    import phase_loop_runtime.consiliency_layout as cl

    from packaging.requirements import Requirement

    import importlib.metadata as md

    from phase_loop_runtime.consiliency_layout import assert_contract_floor_satisfied

    pin_spec = _pyproject_pin()  # skip in the clean-room wheel where no pin governs
    monkeypatch.setattr(cl, "_dist_owns_imported_runtime", lambda dist: True)
    monkeypatch.setattr(
        md,
        "distribution",
        lambda name: _StaleMetadataDist("consiliency-contract>=0.6.0"),
        raising=True,
    )

    # The GOVERNED floor is the PIN, not the stale-OLDER metadata (>=0.6.0) and NOT None
    # (warn-and-skip returned None here -> the guard never fired -- the silent-under-
    # enforcement hole this closes). This is bound DIRECTLY on declared_contract_requirement
    # + assert_contract_floor_satisfied, NOT through check_installed_contract_floor(), so an
    # upstream installed-version operand mutation (rows 2/2b) does not spuriously red this
    # enforcement falsifier; the NEWER falsifier carries the end-to-end check() path.
    req = cl.declared_contract_requirement()
    assert req is not None and str(Requirement(req).specifier) == pin_spec, (
        "stale-OLDER metadata must not govern (and must not warn-skip to None) -- the "
        "adjacent pyproject pin governs. Board #382 r5 Blocker 1."
    )
    # An installed contract BELOW the pin (0.6.0) fires on the governed floor -- the exact
    # case warn-and-skip silently passed.
    with pytest.raises(ContractFloorError):
        assert_contract_floor_satisfied("0.6.0", req)


def test_requirements_equivalent_normalizes_specifier_order():
    # DIVERGENCE-CORROBORATION sentinel (board #382 r5, advisor). The pin governs, but
    # metadata AGREEING must corroborate -- NOT spuriously warn -- and metadata / pyproject
    # legitimately serialise the SAME specifier in different orders (this repo's live case:
    # metadata 'consiliency-contract<0.7,>=0.6.5' vs pyproject '...>=0.6.5,<0.7'). LAYER this
    # binds: the corroboration compare is SEMANTIC (parsed name+specifier), not textual, so a
    # formatting-only difference does not manufacture divergence. Without it the compare could
    # regress to raw ``a == b`` and every real run would warn (or, under filterwarnings=error,
    # abort collection) on healthy, agreeing metadata. Reds under the ``a == b`` mutation.
    from phase_loop_runtime.consiliency_layout import _requirements_equivalent

    assert _requirements_equivalent(
        "consiliency-contract<0.7,>=0.6.5", "consiliency-contract>=0.6.5,<0.7"
    ), "specifier-order-only difference must corroborate, not diverge"
    assert not _requirements_equivalent(
        "consiliency-contract>=9.9,<10", "consiliency-contract>=0.6.5,<0.7"
    ), "a genuinely different floor must diverge"


def test_floor_falls_back_to_metadata_when_no_adjacent_pyproject(monkeypatch):
    # INSTALLED-CASE sentinel (board #382 r5). A wheel / clean-room install ships no adjacent
    # pyproject, so the ruling leaves that path unchanged: the dist METADATA floor governs and
    # NO divergence warning fires (there is no pin to disagree with). Binds the
    # ``return metadata_req`` branch, which every in-tree / CI layout (pyproject always
    # adjacent) never exercises. Reds if that branch regresses to None.
    from packaging.requirements import Requirement

    import phase_loop_runtime.consiliency_layout as cl
    import importlib.metadata as md

    monkeypatch.setattr(cl, "_dist_owns_imported_runtime", lambda dist: True)
    monkeypatch.setattr(cl, "_requirement_from_adjacent_pyproject", lambda: None)
    monkeypatch.setattr(
        md,
        "distribution",
        lambda name: _StaleMetadataDist("consiliency-contract>=1.2,<2"),
        raising=True,
    )
    # No pin to govern -> metadata is the floor, and NO divergence warning fires here.
    with warnings.catch_warnings():
        warnings.simplefilter("error", ContractFloorMetadataDivergence)
        req = cl.declared_contract_requirement()
    assert req is not None
    assert str(Requirement(req).specifier) == str(Requirement("x>=1.2,<2").specifier), (
        "with no adjacent pyproject the metadata floor must govern unchanged. Board #382 r5."
    )


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
    # metadata. The discriminator is that the code reads the IMPORTED version via
    # ``installed_contract_version`` -- so this monkeypatches that seam below a
    # SYNTHETIC floor (not the real one: a scenario constant, board #382 r2
    # Finding 2) and requires a raise. RED on be92ae2: that code read the
    # DIST-metadata version and ignored this patch of installed_contract_version.
    import phase_loop_runtime.consiliency_layout as cl

    monkeypatch.setattr(cl, "installed_contract_version", lambda: "1.0")  # below the synthetic floor
    monkeypatch.setattr(cl, "declared_contract_requirement", lambda: _SYNTHETIC_REQ)
    with pytest.raises(ContractFloorError):
        cl.check_installed_contract_floor()


# ---------------------------------------------------------------------------
# Board #382 r2 Finding 1 — locate_file() is a bare path-join; a same-root dist
# that RECORDS NOTHING must not be accepted as owner (the r2 counterexample).
# ---------------------------------------------------------------------------
class _SameRootEmptyRecordDist:
    """A ``phase-loop-runtime`` dist CO-LOCATED with the imported package (so a bare
    ``locate_file`` path-join accepts it) but recording NO files, and declaring a
    FOREIGN floor. The unsound r1 predicate (``located == imported`` via a path join)
    accepted it and enforced ``>=9.9`` against a healthy contract -> a false
    collection abort. A sound predicate rejects it on the missing RECORD."""

    files = None  # empty RECORD -> the records-package arm must reject this

    @property
    def requires(self):
        return ["consiliency-contract>=9.9,<10"]

    def read_text(self, name):
        # No RECORD and no SOURCES.txt either: the r2-py3.12 direct-read fallback
        # (_dist_records_package) must find nothing here, so an empty-record dist is
        # rejected whether importlib surfaces .files or the text is read directly.
        # Finding 1 stays closed against BOTH read paths.
        return None

    def locate_file(self, path):
        import phase_loop_runtime

        # Same parent as the imported package dir -> co-location passes; only the
        # RECORD check stands between this foreign floor and a false abort.
        root = Path(phase_loop_runtime.__file__).resolve().parent.parent
        return root / str(path)


def _install_same_root_empty_record(monkeypatch):
    import importlib.metadata as md

    _real_distribution = md.distribution

    def _distribution(name):
        if name == "phase-loop-runtime":
            return _SameRootEmptyRecordDist()
        return _real_distribution(name)

    monkeypatch.setattr(md, "distribution", _distribution, raising=True)


def test_declared_requirement_rejects_same_root_dist_that_records_nothing(monkeypatch):
    # FALSIFIER for r2 Finding 1 (records-package arm). Co-located but empty RECORD
    # -> NOT owner -> None (fail-open), never the foreign >=9.9 floor.
    # RED on a1a2cba: locate_file path-join made located == imported, so the guard
    # trusted the empty-RECORD dist and returned its foreign requirement.
    import phase_loop_runtime.consiliency_layout as cl

    _install_same_root_empty_record(monkeypatch)
    assert cl.declared_contract_requirement() is None


def test_check_does_not_abort_on_same_root_empty_record(monkeypatch):
    # The false-COLLECTION-ABORT r2 built end to end: a healthy installed contract,
    # a foreign >=9.9 floor from an empty-RECORD co-located dist. The guard must
    # warn + no-op, never raise (which the conftest turns into a UsageError that
    # aborts collection on correct code). RED on a1a2cba: raised ContractFloorError.
    import phase_loop_runtime.consiliency_layout as cl

    _install_same_root_empty_record(monkeypatch)
    with pytest.warns(ContractFloorUnverified):
        assert cl.check_installed_contract_floor() is None


# ---------------------------------------------------------------------------
# Board #382 r2 — py3.12 egg-info: importlib.metadata surfaces an .egg-info
# SOURCES.txt as an EMPTY .files under 3.12 (817 entries under 3.10, 0 under 3.12
# for this repo's egg-info). The records-package arm must therefore read RECORD /
# SOURCES.txt DIRECTLY; reading only .files false-SKIPS the guard on py3.12, which
# the Finding-3 owns-sentinel caught live in CI (pytest (py3.12) RED at 4a4d4bb).
# ---------------------------------------------------------------------------
class _EmptyFilesButSourcesCoLocatedDist:
    """A CO-LOCATED egg-info whose ``.files`` is EMPTY (the py3.12 behaviour) but whose
    ``SOURCES.txt`` text lists the package. Ownership must resolve TRUE: the direct
    read recovers the record, then B1 co-location binds it. Distinct from
    ``_SameRootEmptyRecordDist`` (which records NOTHING anywhere and must stay
    rejected) -- the only difference is a readable SOURCES.txt, which is exactly the
    line between a real in-tree egg-info and a bare same-root path-join."""

    version = "0.0-test"  # B1 is not version-gated, so this is irrelevant to ownership
    files = []  # py3.12: importlib returns an empty .files for .egg-info SOURCES.txt

    def read_text(self, name):
        if name == "SOURCES.txt":
            return "setup.py\nsrc/phase_loop_runtime/__init__.py\nsrc/phase_loop_runtime/consiliency_layout.py\n"
        return None

    def locate_file(self, path):
        import phase_loop_runtime

        root = Path(phase_loop_runtime.__file__).resolve().parent.parent
        return root / str(path)


def test_owns_via_sources_text_when_files_is_empty_egginfo():
    # FALSIFIER for the r2 py3.12 fix. RED at 4a4d4bb: arm A read only ``dist.files``
    # (empty here), so a co-located egg-info was judged NOT-owner and the guard
    # false-skipped. GREEN after: _dist_records_package reads SOURCES.txt directly.
    import phase_loop_runtime.consiliency_layout as cl

    assert cl._dist_owns_imported_runtime(_EmptyFilesButSourcesCoLocatedDist()) is True
    # And the empty-record sibling with NO readable SOURCES.txt stays rejected, so the
    # direct-read fallback did not reopen Finding 1's foreign-floor hole.
    assert cl._dist_owns_imported_runtime(_SameRootEmptyRecordDist()) is False


class _PartialFilesCoLocatedDist:
    """The py3.12 mechanism is FILTER-BY-EXISTENCE, not "empty for egg-info": under 3.12
    ``importlib.metadata`` returns only the SOURCES.txt entries that RESOLVE on disk, so
    ``.files`` can be NON-EMPTY yet PARTIAL -- missing the imported module (whose path
    did not resolve at the egg-info's parent) while retaining a surviving sibling. A
    fallback gated on ``.files`` being EMPTY would be bypassed here (non-empty) and the
    truncated list would false-reject a legitimate owner (board #382 r2, lead). This
    dist reproduces that: ``.files`` lists a sibling but NOT ``__init__.py``, while
    SOURCES.txt text still lists the module."""

    version = "0.0-test"

    @property
    def files(self):
        # Non-empty, but the imported package's __init__.py is filtered out.
        return [Path("phase_loop_runtime/consiliency_layout.py")]

    def read_text(self, name):
        if name == "SOURCES.txt":
            return (
                "setup.py\n"
                "src/phase_loop_runtime/__init__.py\n"
                "src/phase_loop_runtime/consiliency_layout.py\n"
            )
        return None

    def locate_file(self, path):
        import phase_loop_runtime

        root = Path(phase_loop_runtime.__file__).resolve().parent.parent
        return root / str(path)


def test_owns_when_files_is_nonempty_but_partial_missing_module():
    # FALSIFIER for the PARTIAL arm (board #382 r2, lead). CI never produces this on a
    # fixed matrix, so it is synthetic. It goes RED under the WRONG condition (fall back
    # to text ONLY when ``.files`` is empty) -- the partial list is non-empty, so the
    # fallback is skipped and the truncated match false-rejects the owner. It is GREEN
    # under the correct condition (fall back whenever the files-based match FAILED, for
    # any reason), which is what _dist_records_package implements: the ``.files`` check
    # not returning True falls through to the RECORD/SOURCES.txt text read.
    import phase_loop_runtime.consiliency_layout as cl

    assert cl._dist_owns_imported_runtime(_PartialFilesCoLocatedDist()) is True


# ---------------------------------------------------------------------------
# Board #382 r2 — the CI-layout guard: import resolves from src/ while the dist
# lives in site-packages (pip install ./dir + pytest with src on sys.path). The
# co-location arm alone FALSE-FAILS here (empirically reproduced); direct_url
# (PEP 610) proves the dist was installed FROM the tree that contains __file__.
# ---------------------------------------------------------------------------
class _DirInstallDist:
    """A dist NOT co-located with the import (site-packages vs src), recording the
    package, with a PEP 610 ``direct_url.json`` naming a local dir it was installed
    FROM. ``_tree`` is that dir: when it contains the imported ``__file__`` the dist
    IS this code (owner); a foreign tree is a shadow. ``_records`` toggles the
    records-package gate."""

    def __init__(self, tree, records=True, version=None):
        import phase_loop_runtime

        self._tree = str(tree)
        self._records = records
        # Default to the RUNNING version so the honest-owner case matches; override
        # to simulate a stale same-repo install (right tree, older build).
        self._version = version if version is not None else getattr(phase_loop_runtime, "__version__", "0")

    @property
    def version(self):
        return self._version

    @property
    def files(self):
        return [Path("phase_loop_runtime/__init__.py")] if self._records else []

    def locate_file(self, path):
        return Path("/nonexistent/site-packages") / str(path)  # deliberately NOT co-located

    def read_text(self, name):
        if name == "direct_url.json":
            return json.dumps({"url": f"file://{self._tree}", "dir_info": {}})
        return None


def _imported_repo_tree() -> Path:
    import phase_loop_runtime

    # .../phase-loop-runtime/src/phase_loop_runtime/__init__.py -> .../phase-loop-runtime
    return Path(phase_loop_runtime.__file__).resolve().parents[2]


def test_owns_via_direct_url_when_installed_from_tree_containing_import():
    # B2 acceptance: not co-located, but direct_url names a dir that contains the
    # imported file -> owner. This is the CI matrix layout; without it a healthy
    # checkout would skip the guard (false failure).
    import phase_loop_runtime.consiliency_layout as cl

    assert cl._dist_owns_imported_runtime(_DirInstallDist(_imported_repo_tree())) is True


def test_not_owned_when_direct_url_names_a_foreign_tree():
    # B2 soundness: a dist installed from a DIFFERENT tree (a PyPI/foreign shadow)
    # is not tied to the imported instance -> not owner. Guards against B2 blindly
    # trusting any direct_url.
    import phase_loop_runtime.consiliency_layout as cl

    assert cl._dist_owns_imported_runtime(_DirInstallDist(Path("/opt/other-checkout"))) is False


def test_direct_url_arm_still_requires_recorded_package():
    # A gates B2: an install-from-this-tree dist that records NOTHING is still
    # rejected (the records-package arm is required in every branch).
    import phase_loop_runtime.consiliency_layout as cl

    assert cl._dist_owns_imported_runtime(_DirInstallDist(_imported_repo_tree(), records=False)) is False


def test_direct_url_arm_rejects_stale_same_repo_install_by_version(monkeypatch):
    # B2 SOUNDNESS (board #382 r2, advisor): the advisor's false-OWN counterexample.
    # A non-editable install of THIS repo (records the package, direct_url names the
    # tree that contains the import) but a STALE build carrying an OLDER floor must
    # NOT be trusted -- otherwise it enforces a foreign floor and aborts collection on
    # healthy code, codex's r2 counterexample one arm over. The version gate rejects
    # it. Paired end-to-end with a foreign floor: warn + no-op, never a raise.
    import phase_loop_runtime.consiliency_layout as cl

    stale = _DirInstallDist(_imported_repo_tree(), version="0.0.1-stale")
    assert cl._dist_owns_imported_runtime(stale) is False

    # end-to-end: a stale dist with a foreign >=9.9 floor must not abort collection.
    import importlib.metadata as md

    _real = md.distribution

    class _StaleForeign(_DirInstallDist):
        @property
        def requires(self):
            return ["consiliency-contract>=9.9,<10"]

    monkeypatch.setattr(
        md,
        "distribution",
        lambda name: _StaleForeign(_imported_repo_tree(), version="0.0.1-stale")
        if name == "phase-loop-runtime"
        else _real(name),
        raising=True,
    )
    assert cl.declared_contract_requirement() is None
    with pytest.warns(ContractFloorUnverified):
        assert cl.check_installed_contract_floor() is None


# ---------------------------------------------------------------------------
# Board #382 r3 — enumerate the preflight's DEPENDENCY CLASS and sentinel each member.
#
# Both r3 blockers are the same failure at two levels: a specific instance was fixed and
# the CLASS was declared closed. r2 closed ONE hollow-guard instance (declared floor);
# the class had three operand/wiring members and two were unsentineled. The r2 py3.12
# fix broadened arm A's fallback and, doing so, reopened r2 Finding 1 through a manifest
# it now consults. So the class is written down here and every member gets a row with a
# named mutation and a test that reds under it:
#
#   ROW  member                     mutation                              sentinel (reds)
#   ---  -------------------------  ------------------------------------  ------------------------------
#   1a   arm A: manifest PRECEDENCE  RECORD miss falls through to a stray  test_record_authority_rejects_
#        (RECORD authoritative)      SOURCES.txt (the 2f67c7a behaviour)   dist_info_with_stray_sources
#   1b   arm A end-to-end           foreign floor from the stray-sources   test_check_does_not_abort_on_
#                                    dist aborts collection                dist_info_with_stray_sources
#   1c   arm A: EMPTY-RECORD, on a   files-first ordering serves the stray test_records_package_rejects_
#        REAL PathDistribution       SOURCES.txt THROUGH .files (r4)       real_empty_record_dist_with_stray_sources
#   f2   arm A: path BOUNDARY        bare path.endswith(needle) accepts a  test_records_package_rejects_
#                                    foreign suffix collision (r4)         suffix_collision_foreign_package
#   2    operand: installed version installed_contract_version() -> None   test_installed_version_operand_
#        (SHAPE)                     (guard fail-opens, never enforces)    is_provable
#   2b   operand: installed version accessor returns a hardcoded constant  test_installed_version_operand_
#        (BINDING)                   / module global hardcoded (r4)        is_bound_not_hardcoded
#   3a   wiring: check is INVOKED    delete pytest_configure's invocation  test_conftest_actually_invokes_
#                                                                          the_floor_preflight
#   3b   wiring: structural          delete the call line specifically     test_conftest_source_calls_the_
#                                                                          floor_preflight
#   3c   wiring: ENFORCEMENT         except ContractFloorError -> except   test_conftest_floor_error_
#        handler re-raises           Exception: pass (swallow, r4)         handler_reraises
#   3d   wiring: 3c is SCOPE-SOUND    handler swallows but hides a raise in test_conftest_floor_error_
#        (own-scope raise only)      a NESTED def (ast.walk crossed scopes) handler_reraises (r5)
#   B1a  floor AUTHORITY (governance) pin governance reverted: declared_*() test_floor_governed_by_pyproject_
#        pin overrides metadata      returns metadata_req not pyproject_req over_stale_{newer,older}_metadata
#   B1b  floor DIVERGENCE is VISIBLE  drop the divergence warnings.warn     test_floor_governed_by_pyproject_
#        (never silent)              (pin still governs, but silently)      over_stale_newer_metadata
#   B1c  corroboration is SEMANTIC    _requirements_equivalent -> raw a==b  test_requirements_equivalent_
#        (specifier-normalized)      (format-only diff manufactures warn)  normalizes_specifier_order
#   B1d  installed case (no pin)      metadata branch return None           test_floor_falls_back_to_metadata_
#        (metadata governs unchanged)                                       when_no_adjacent_pyproject
#   (declared floor, the third operand, is sentineled above by
#    test_declared_floor_is_provable_and_single_sourced -- reds on declared_*() -> None.)
#
# r4 (board #382, codex+fable) added 1c/f2/2b/3c. r5 (codex Blocker 2 + maintainer ruling on
# Blocker 1) added 3d/B1a/B1b. Discipline for each row: name the LAYER the sentinel binds and
# the layer ABOVE it. 1a-1c bind manifest PRECEDENCE; the layer above is importlib's own
# .files->SOURCES fallback, now gated by reading RECORD first. 2 binds operand SHAPE; 2b binds
# the layer above (accessor is BOUND to the contract version, and that binding IS the contract
# package's object). 3a binds block-executed; 3b binds call-present; 3c binds the ENFORCEMENT
# handler re-raises; 3d binds that 3c is SCOPE-SOUND -- a nested-def raise (which never runs when
# the handler swallows) does not count, so the layer above 3c (ast.walk crossing lexical scopes)
# is closed. B1a binds floor AUTHORITY -- when the gitignored, install-stale egg-info metadata
# disagrees with the adjacent pin, the PIN governs enforcement (the layer above: the r4
# metadata-only floor, which trusted a stale egg-info); B1a's one governance lever backs BOTH
# stale-direction falsifiers (newer -> false-abort, older -> silent under-enforce), so reverting
# it reds both -- a real, correct coupling, not a defect (the falsifiers guard the one lever from
# opposite sides). B1b binds that divergence stays VISIBLE (the warn is never silenced), isolable
# from B1a because dropping only the warn reds just the stale-NEWER falsifier's warns-assertion.
# B1c binds that corroboration is SEMANTIC -- _requirements_equivalent compares parsed
# (name, specifier), so a raw ``a == b`` regression (which would warn on this repo's own
# order-only-different metadata vs pin) reds a dedicated unit sentinel rather than passing
# vacuously. B1d binds the installed-case ``return metadata_req`` branch that no in-tree /
# CI layout (pyproject always adjacent) exercises. The stale-OLDER falsifier is bound DIRECTLY
# on declared + assert_contract_floor_satisfied (not through check()), so an upstream
# installed-version operand mutation (rows 2/2b) no longer spuriously reds it -- the only
# residual couplings are 2->2b (2b binds the layer ABOVE 2, so null fails both) and
# B1a->{newer,older} (one governance lever guarded from both stale directions), both correct.
# ---------------------------------------------------------------------------
class _DistInfoRecordForeignSourcesOursDist:
    """A same-root ``.dist-info`` whose AUTHORITATIVE ``RECORD`` lists only an unrelated
    package, but which ALSO carries a stray ``SOURCES.txt`` naming OUR package. Co-located
    (so B1 would bind it the instant arm A accepted it) and declaring a FOREIGN floor.

    Before the r3 RECORD-authority fix, ``_dist_records_package`` fell through the
    non-matching RECORD to the stray SOURCES.txt, accepted ownership, and the foreign
    ``>=9.9`` floor aborted collection on a healthy contract -- r2 Finding 1 reopened by
    the r2 py3.12 broadening of arm A (board #382 r3, codex). A ``.dist-info``'s RECORD is
    the complete installed manifest; a readable RECORD that omits the package is a decisive
    not-owned, and the stray SOURCES.txt must never be consulted alongside it."""

    version = "0.0-test"

    @property
    def requires(self):
        return ["consiliency-contract>=9.9,<10"]

    @property
    def files(self):
        # A real .dist-info's .files derives from RECORD -> names the FOREIGN package.
        return [Path("otherpkg/__init__.py"), Path("otherpkg-1.0.dist-info/RECORD")]

    def read_text(self, name):
        if name == "RECORD":
            # Authoritative manifest: the foreign package, NOT ours (path,hash,size).
            return "otherpkg/__init__.py,sha256=deadbeef,10\notherpkg-1.0.dist-info/RECORD,,\n"
        if name == "SOURCES.txt":
            # Stray egg-info manifest that DOES name ours -- must not be consulted while
            # an authoritative RECORD is present.
            return "setup.py\nsrc/phase_loop_runtime/__init__.py\n"
        return None

    def locate_file(self, path):
        import phase_loop_runtime

        root = Path(phase_loop_runtime.__file__).resolve().parent.parent
        return root / str(path)


def test_record_authority_rejects_dist_info_with_stray_sources():
    # ROW 1a FALSIFIER (board #382 r3). RED on 2f67c7a: the RECORD miss fell through to
    # the stray SOURCES.txt and accepted the foreign-floor dist as owner.
    import phase_loop_runtime.consiliency_layout as cl

    dist = _DistInfoRecordForeignSourcesOursDist()
    # A readable RECORD that omits our package is decisive not-owned, even though a stray
    # SOURCES.txt names us.
    assert cl._dist_records_package(dist, "phase_loop_runtime/__init__.py") is False
    # Co-located, so B1 would bind it -> arm A is the ONLY thing that can reject it.
    assert cl._dist_owns_imported_runtime(dist) is False


def test_check_does_not_abort_on_dist_info_with_stray_sources(monkeypatch):
    # ROW 1b, the false-COLLECTION-ABORT built end to end (codex's r3 exploit): a healthy
    # installed contract, a foreign >=9.9 floor from a same-root .dist-info whose
    # authoritative RECORD names an unrelated package but whose stray SOURCES.txt names
    # ours. Must warn + no-op, never raise. RED on 2f67c7a: raised ContractFloorError.
    import importlib.metadata as md

    import phase_loop_runtime.consiliency_layout as cl

    _real = md.distribution
    monkeypatch.setattr(
        md,
        "distribution",
        lambda name: _DistInfoRecordForeignSourcesOursDist()
        if name == "phase-loop-runtime"
        else _real(name),
        raising=True,
    )
    assert cl.declared_contract_requirement() is None
    with pytest.warns(ContractFloorUnverified):
        assert cl.check_installed_contract_floor() is None


# ---------------------------------------------------------------------------
# Board #382 r4 Finding 1 (codex + fable) — the EMPTY-RECORD sub-case, built on a
# REAL importlib PathDistribution. The r2/r3 synthetic dists above hand-author
# ``.files`` UNFAITHFULLY: ``_SameRootEmptyRecordDist`` sets ``files = None`` and
# ``_DistInfoRecordForeignSourcesOursDist`` returns a RECORD-derived foreign list --
# neither is the shape a REAL empty-RECORD dist takes. importlib derives ``.files``
# via ``_read_files_distinfo() or ... or _read_files_egginfo_sources()``, so a real
# EMPTY (falsy) RECORD serves the dist's stray SOURCES.txt THROUGH ``.files``. A
# files-first probe accepted that stray manifest as ownership. This falsifier uses a
# real PathDistribution over on-disk metadata so any future drift between our synthetic
# dists and importlib surfaces here generically.
# ---------------------------------------------------------------------------
def _real_dist_info(tmp_path, *, dist_name, record_text, sources_text=None,
                    make_pkg="phase_loop_runtime"):
    """Build a real on-disk ``.dist-info`` and return its ``md.PathDistribution``.

    ``make_pkg`` (if set) also writes ``<root>/<make_pkg>/__init__.py`` so the SOURCES
    entry RESOLVES on disk and survives the py3.12 existence filter -- without it the
    3.12 filter would drop the stray entry and the falsifier would not fire on 3.12.
    """
    import importlib.metadata as md

    if make_pkg:
        pkg = tmp_path / make_pkg
        pkg.mkdir(exist_ok=True)
        (pkg / "__init__.py").write_text("# real, exists on disk\n", encoding="utf-8")
    dinfo = tmp_path / f"{dist_name}.dist-info"
    dinfo.mkdir()
    (dinfo / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {dist_name.rsplit('-', 1)[0]}\nVersion: 0.0.0\n",
        encoding="utf-8",
    )
    (dinfo / "RECORD").write_text(record_text, encoding="utf-8")
    if sources_text is not None:
        (dinfo / "SOURCES.txt").write_text(sources_text, encoding="utf-8")
    return md.PathDistribution(dinfo)


def test_records_package_rejects_real_empty_record_dist_with_stray_sources(tmp_path):
    # ROW 1c FALSIFIER (board #382 r4). A REAL empty-RECORD .dist-info + stray SOURCES.txt
    # naming ours + the package file on disk. importlib serves SOURCES through ``.files``
    # (empty RECORD is falsy), so a files-first probe wrongly accepted it. RED on 6ef93a6
    # (files-first): _dist_records_package returned True. GREEN with RECORD read first: an
    # empty-but-present RECORD is a decisive "not owned". Fires on 3.10 AND 3.12.
    import phase_loop_runtime.consiliency_layout as cl

    needle = "phase_loop_runtime/__init__.py"
    dist = _real_dist_info(
        tmp_path, dist_name="foreignpkg-1.0", record_text="", sources_text=needle + "\n"
    )
    assert cl._dist_records_package(dist, needle) is False


def test_records_package_rejects_suffix_collision_foreign_package(tmp_path):
    # FINDING 2 FALSIFIER (board #382 r4). A co-located foreign package whose name merely
    # ENDS with ours -- ``other_phase_loop_runtime`` -- recorded in an authoritative RECORD.
    # RED on 6ef93a6: bare ``path.endswith(needle)`` matched, so the foreign dist was read as
    # owner. GREEN with exact-or-slash-delimited matching.
    import phase_loop_runtime.consiliency_layout as cl

    needle = "phase_loop_runtime/__init__.py"
    dist = _real_dist_info(
        tmp_path,
        dist_name="other-plr-1.0",
        record_text="other_phase_loop_runtime/__init__.py,sha256=x,10\n",
        make_pkg="other_phase_loop_runtime",
    )
    assert cl._dist_records_package(dist, needle) is False


def test_installed_version_operand_is_provable():
    # ROW 2 ANTI-HOLLOW sentinel, installed-version operand (board #382 r3, Blocker 2).
    # check_installed_contract_floor fail-opens when installed_contract_version() is None;
    # an always-None regression there makes the guard silently never enforce, and no other
    # test caught it (codex mutated it -> 20 green). In every env this suite runs the
    # imported contract version MUST be readable and parseable, so that regression reds
    # here. Parallel to the declared-floor sentinel; the two together with the wiring
    # sentinel cover all three preflight dependencies.
    from packaging.version import Version

    import phase_loop_runtime.consiliency_layout as cl

    v = cl.installed_contract_version()
    assert v is not None, (
        "installed_contract_version() is None -- the floor guard fail-opens and never "
        "enforces. See board #382 r3 Blocker 2 (installed-version operand)."
    )
    # Parseable, not merely non-None: '' or garbage slips a bare `is not None` yet breaks
    # assert_contract_floor_satisfied's Version() call at collection time.
    Version(v)


def test_installed_version_operand_is_bound_not_hardcoded(monkeypatch):
    # ROW 2 BINDING sentinel (board #382 r4, codex finding 3; remedy CORRECTED by lead+me).
    # test_installed_version_operand_is_provable proves the operand is SHAPE-right (non-None,
    # parseable); it does NOT prove it is BOUND to consiliency_contract.CONTRACT_VERSION.
    # codex's constant-"0.6.5" mutation stayed green under shape alone -- same one-notch-
    # deeper hollow as the 3b-isolate case. codex's literal remedy ("patch
    # consiliency_contract.CONTRACT_VERSION") does NOT work: consiliency_layout captured the
    # value via ``from consiliency_contract import CONTRACT_VERSION`` at import, so patching
    # the SOURCE module never propagates (verified) and that sentinel would red on a healthy
    # accessor. Two layers instead:
    import consiliency_contract as cc

    import phase_loop_runtime.consiliency_layout as cl

    # (layer above) the module binding IS the contract package's object -- a source-level
    # hardcode of the module global reds here. Checked BEFORE the patch below.
    assert cl.CONTRACT_VERSION is cc.CONTRACT_VERSION, (
        "consiliency_layout.CONTRACT_VERSION is not consiliency_contract.CONTRACT_VERSION -- "
        "the module global was hardcoded rather than imported. Board #382 r4 finding 3."
    )
    # (accessor layer) the accessor returns that binding, not a literal: patch the binding the
    # accessor actually READS and assert it tracks. Kills ``return "0.6.5"``.
    sentinel = "9999.0.1-binding-probe"
    monkeypatch.setattr(cl, "CONTRACT_VERSION", sentinel, raising=True)
    assert cl.installed_contract_version() == sentinel, (
        "installed_contract_version() ignores the module CONTRACT_VERSION binding -- a "
        "hardcoded literal passes the shape test yet never tracks the real contract version. "
        "Board #382 r4 finding 3 (installed-version operand BINDING)."
    )


def test_conftest_actually_invokes_the_floor_preflight(pytestconfig):
    # ROW 3a WIRING sentinel (board #382 r3, Blocker 2). A guard that is never CALLED is
    # indistinguishable from a guard that passes: every operand test calls
    # check_installed_contract_floor() directly, so suppressing the conftest
    # pytest_configure invocation left all 20 green. conftest sets this stash key right
    # after the preflight runs in THIS collection; deleting the invocation leaves it unset
    # and reds here.
    from _contract_floor_wiring import CONTRACT_FLOOR_PREFLIGHT_RAN

    assert pytestconfig.stash.get(CONTRACT_FLOOR_PREFLIGHT_RAN, False) is True


def test_conftest_source_calls_the_floor_preflight():
    # ROW 3b, second wiring arm, STRUCTURAL. Parse the real conftest and assert
    # pytest_configure contains a call to check_installed_contract_floor. Kills the exact
    # "delete the call" mutation directly, independent of the runtime stash (which a
    # hyper-narrow mutation could leave set while removing only the call). Board #382 r3.
    import ast
    from pathlib import Path

    conftest = Path(__file__).resolve().parent / "conftest.py"
    tree = ast.parse(conftest.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "pytest_configure"
    )
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "check_installed_contract_floor" in called, (
        "conftest.pytest_configure no longer calls check_installed_contract_floor -- the "
        "floor preflight is unwired. See board #382 r3 Blocker 2 (wiring)."
    )


def test_conftest_floor_error_handler_reraises():
    # ROW 3c WIRING sentinel (board #382 r4, fable F1). The REALISTIC neutered-call is not
    # ``if False:`` -- it is broadening ``except ContractFloorError`` to ``except Exception:
    # pass`` (or dropping the ``raise``), which neuters ENFORCEMENT while 3a stays green (the
    # stash is set on the healthy path) and 3b stays green (the call is still present).
    # Reachable by ordinary refactoring, not sabotage -- strictly more realistic than the
    # documented ``if False:`` residual. Parse the real conftest and assert the handler that
    # catches a ContractFloorError CONTAINS a ``raise``, so a swallow reds here.
    import ast
    from pathlib import Path

    conftest = Path(__file__).resolve().parent / "conftest.py"
    tree = ast.parse(conftest.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "pytest_configure"
    )

    def _handler_exc_names(handler):
        t = handler.type
        if t is None:
            return set()  # bare ``except:`` -- names nothing specific
        elts = t.elts if isinstance(t, ast.Tuple) else [t]
        return {e.id for e in elts if isinstance(e, ast.Name)}

    def _raises_in_own_scope(node):
        # A ``raise`` counts only if it is in the handler's OWN lexical scope. Board
        # #382 r5 Blocker 2 (codex): a plain ``ast.walk`` descends into nested defs, so
        # ``except ContractFloorError as exc:\n    def convert():\n        raise ...``
        # satisfies it while the handler itself SWALLOWS -- a nested-scope raise never
        # runs when the handler returns. Prune nested-scope bodies (FunctionDef /
        # AsyncFunctionDef / Lambda / ClassDef) from the walk so only raises that
        # execute in this handler count. Nested ``try``/``if``/``with``/``for`` are NOT
        # new scopes, so a raise inside them still counts (3c asserts a raise EXISTS in
        # the handler's own scope, not that it aborts -- see the ROW-3 residual note).
        stack = list(ast.iter_child_nodes(node))
        while stack:
            child = stack.pop()
            if isinstance(child, ast.Raise):
                return True
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
            ):
                continue  # a nested scope -- its raises do not run in THIS handler
            stack.extend(ast.iter_child_nodes(child))
        return False

    floor_handlers = [
        h
        for h in ast.walk(fn)
        if isinstance(h, ast.ExceptHandler)
        and "ContractFloorError" in _handler_exc_names(h)
    ]
    assert floor_handlers, (
        "conftest.pytest_configure no longer has an `except ContractFloorError` handler -- a "
        "floor violation is no longer caught and re-raised as a collection abort. Board "
        "#382 r4 fable F1 (enforcement wiring)."
    )
    for h in floor_handlers:
        assert _raises_in_own_scope(h), (
            "an `except ContractFloorError` handler in conftest.pytest_configure does not "
            "RAISE in its own scope -- a swallowed floor error neuters enforcement while the "
            "wiring sentinels (3a/3b) stay green. The handler must re-raise (as a UsageError). "
            "A raise buried in a nested def/lambda/class inside the handler does not count -- it "
            "never runs when the handler swallows. Board #382 r4 fable F1 / r5 Blocker 2."
        )


# ---------------------------------------------------------------------------
# ROW 3 -- RESIDUAL BOUNDARY (board #382 r3, lead ruling: accept the two wiring
# arms; do NOT add a call-counter). Recorded here so a future reader inherits
# what these sentinels prove -- and the one thing neither proves -- along with
# the table above:
#
#   * 3a (dynamic stash) proves pytest_configure's preflight block EXECUTED in
#     THIS process -- a real side effect, not static-satisfiable. Catches
#     hook-not-invoked / block-not-run.
#   * 3b (static ast) proves the call is PRESENT in the block. Catches the
#     surgical "delete only the call" mutation that 3a structurally cannot see.
#   * Together they close BOTH removal paths. Demonstrated by the 3b-isolate
#     mutation (delete the call but KEEP the stash write): 3a stays GREEN, only
#     3b reds -- i.e. the stash is a side effect of the block reaching the line
#     AFTER the call, not proof the call itself ran.
#   * 3c (static ast, r4 fable F1) proves the ENFORCEMENT handler re-raises. The
#     REALISTIC neuter is not `if False:` -- it is broadening `except
#     ContractFloorError` to `except Exception: pass` (a well-meant refactor),
#     which swallows a real violation while 3a stays GREEN (stash set on the
#     healthy path) and 3b stays GREEN (call present). 3c reds exactly that, so
#     the refactoring-reachable hole is no longer in the residual. What 3c
#     asserts is narrow (board #382 r5 F-2): the handler CONTAINS a `raise` in its
#     OWN lexical scope -- nested def/lambda/class bodies are pruned from the walk
#     (Blocker 2), because a raise buried in a nested def never runs when the
#     handler swallows. It does NOT assert the raise ABORTS: `raise SystemExit(0)`,
#     or a `raise` caught by a nested `try` inside the handler, still satisfy 3c and
#     remain in the deliberate-sabotage residual below.
#   * NEITHER 3a/3b/3c proves the call's BODY executed. The residual is now only
#     a DELIBERATE in-place neuter (`if False: check_installed_contract_floor()`,
#     stash still set, handler intact) -- present but never run. That is not
#     reachable by ordinary refactoring (3c took that case); it is sabotage. The
#     check's CORRECTNESS when it DOES run is covered separately by the direct-
#     invocation tests -- ROW 2 (SHAPE + BINDING),
#     test_declared_floor_is_provable_and_single_sourced, and
#     test_check_does_not_abort_on_dist_info_with_stray_sources -- which call
#     check_installed_contract_floor() and assert its behaviour. Coverage =
#     block-ran (3a) + call-present (3b) + handler-reraises (3c) + check-correct-
#     when-called (direct tests); the residual is only "call present, handler
#     intact, but neutered in place by a deliberate edit".
#
# The DISPOSITION -- document this residual rather than close it with production
# coupling -- was ruled correct by the lead (r3) and independently endorsed by
# the fable seat (r4: both alternatives below are worse trades). Two ways to
# close it were weighed and REJECTED:
#   - a production call-counter in check_installed_contract_floor couples
#     shipped code to test observability (a field that exists only to be looked
#     at -> the next tidy-up removes the thing the proof rests on);
#   - a pytester end-to-end exercises a SYNTHETIC conftest, proving the
#     mechanism in a fixture we wrote rather than in the real one.
# Neither is worth the coupling; the boundary is left documented instead.
# ---------------------------------------------------------------------------
