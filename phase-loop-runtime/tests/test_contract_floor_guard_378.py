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
    # ANTI-HOLLOW sentinel (board #382 r2 Findings 3 & 2), None-direction + the ONE
    # single-source enforcer. Round 1 skipped when ``declared_contract_requirement()``
    # returned None; codex showed that let an always-None regression -- a guard that
    # never runs -- pass CI green (10 passed, 1 skipped). The fix: when provenance is
    # provable (the exact condition under which the guard COULD run), a None floor is
    # a FAILURE, not a skip. It also asserts the runtime's floor equals pyproject's
    # single source -- the live comparison that actually enforces single-source
    # (duplicate literals never did; a scenario constant is not a source of truth).
    from packaging.requirements import Requirement

    if not _provenance_provable():
        # Provenance genuinely unprovable here; test_real_dist_owns_imported_module
        # is the sentinel that flags that as an env regression, so skipping the
        # value comparison here is safe (it cannot hide a hollow guard).
        pytest.skip("provenance not provable in this env (flagged by the owns-sentinel)")
    runtime_req = declared_contract_requirement()
    # The anti-hollow core: provable provenance but a None floor == the guard is
    # hollow (never runs). This is what goes RED under the always-None mutation.
    assert runtime_req is not None, (
        "provenance is provable but declared_contract_requirement() is None -- the "
        "contract-floor guard is HOLLOW (it never runs). See board #382 r2 Finding 3."
    )
    pyproject_req = _requirement_from_pyproject()
    if pyproject_req is None:
        # Clean-room wheel ships no pyproject; the floor VALUE is not comparable here,
        # but the non-None assertion above already proved the guard is not hollow.
        pytest.skip("pyproject.toml not adjacent (clean-room wheel); value not comparable")
    # Compare parsed name + specifier, not raw string, so formatting (ordering,
    # spaces) neither masks nor manufactures a mismatch. Non-vacuous: pyproject and
    # the dist metadata are independent artifacts (metadata is BUILT from pyproject,
    # but a stale .egg-info or extraction bug makes them disagree).
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
#   2    operand: installed version installed_contract_version() -> None   test_installed_version_operand_
#                                    (guard fail-opens, never enforces)    is_provable
#   3a   wiring: check is INVOKED    delete pytest_configure's invocation  test_conftest_actually_invokes_
#                                                                          the_floor_preflight
#   3b   wiring: structural          delete the call line specifically     test_conftest_source_calls_the_
#                                                                          floor_preflight
#   (declared floor, the third operand, is sentineled above by
#    test_declared_floor_is_provable_and_single_sourced -- reds on declared_*() -> None.)
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
#   * NEITHER proves the call's BODY executed. A present-but-neutered call
#     (`if False: check_installed_contract_floor()`, stash still set) reds
#     neither wiring sentinel. The check's CORRECTNESS is covered separately by
#     the direct-invocation tests -- ROW 2, test_declared_floor_is_provable_
#     and_single_sourced, and test_check_does_not_abort_on_dist_info_with_stray_
#     sources -- which call check_installed_contract_floor() and assert its
#     behaviour. Coverage = block-ran (3a) + call-present (3b) + check-correct-
#     when-called (direct tests); the residual is only "call present but
#     neutered in place".
#
# Two ways to close that residual were weighed and REJECTED as worse trades:
#   - a production call-counter in check_installed_contract_floor couples
#     shipped code to test observability (a field that exists only to be looked
#     at -> the next tidy-up removes the thing the proof rests on);
#   - a pytester end-to-end exercises a SYNTHETIC conftest, proving the
#     mechanism in a fixture we wrote rather than in the real one.
# Neither is worth the coupling; the boundary is left documented instead.
# ---------------------------------------------------------------------------
