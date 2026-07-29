"""Shared `.consiliency/` layout constants and lookup helpers (CS-0.5/CS-0.6).

Single source of truth for where the `.consiliency/` artifacts live and how a
manifest is composed against the vendored `consiliency_contract` package data.
The scaffolder (``consiliency_scaffold``), the L0 gates
(``consiliency_gates``), and the runner's consent check must all agree on
this path -- drift here would be a silent bug (an operator could scaffold a
manifest the gates never find).

Version-gated DUAL-READ (CS-0.5 scope): this module is purely additive. It
never reads or writes ``.phase-loop/`` or ``.pipeline/``, and nothing in the
existing runtime is rewired to prefer `.consiliency/` yet -- that fallback
seam is for CS-0.12 once the adoption-profile consent check lands. Today,
`.consiliency/` and legacy layouts simply coexist.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from consiliency_contract import CONTRACT_VERSION, load_registry, load_schema

#: Repo-relative root for all Consiliency-standard artifacts.
CONSILIENCY_DIR = ".consiliency"
#: Filenames within CONSILIENCY_DIR, pinned to the shapes used by the
#: contract's own conformance vectors (manifest-valid-product.json uses
#: ".consiliency/status.json" and ".consiliency/interfaces.json").
MANIFEST_FILENAME = "manifest.json"
STATUS_FILENAME = "status.json"
INTERFACES_FILENAME = "interfaces.json"
#: Stub documents the scaffolder is allowed to author live under this
#: sub-namespace so they can never collide with a repo's own doc layout.
STUB_DOCS_SUBDIR = "docs"

ARCHETYPE_IDS: tuple[str, ...] = ("product", "service", "library", "infra", "tooling-meta", "experiment", "document")
MODIFIER_IDS: tuple[str, ...] = ("data-bearing", "public", "regulated", "user-facing")


def consiliency_root(repo: Path) -> Path:
    return Path(repo) / CONSILIENCY_DIR


def manifest_path(repo: Path) -> Path:
    return consiliency_root(repo) / MANIFEST_FILENAME


def status_path(repo: Path) -> Path:
    return consiliency_root(repo) / STATUS_FILENAME


def interfaces_path(repo: Path) -> Path:
    return consiliency_root(repo) / INTERFACES_FILENAME


def find_consiliency_manifest(repo: str | Path) -> Path | None:
    """The one place that decides whether a repo has opted into Consiliency.

    Every consumer (scaffolder overwrite checks, all four L0 gates, and the
    runner's top-of-loop/closeout hooks) MUST call this rather than
    re-deriving the path, so the CS-0.6 consent gate ("act only on repos that
    HAVE a `.consiliency/manifest`") is enforced identically everywhere.
    """
    path = manifest_path(Path(repo))
    return path if path.is_file() else None


def load_consiliency_manifest(repo: str | Path) -> dict[str, Any] | None:
    """Parsed manifest, or ``None`` when absent OR unparsable.

    Unparsable is folded into "no consent" rather than raised -- a corrupt
    manifest must never crash the loop; the layout-validity gate is what
    reports that condition as a finding.
    """
    path = find_consiliency_manifest(repo)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class RequiredDocRow:
    id: str
    doc_class: str
    required: bool
    maturity_floor: str
    l0_stub_allowed: bool
    l0_note: str | None = None
    source: str = "baseline"  # baseline | archetype:<id> | modifier:<id>


class RequiredDocumentConflict(ValueError):
    """Two composed rows share an id but are not byte-identical."""


def compose_required_documents(
    *,
    mode: str,
    archetypes: tuple[str, ...] = (),
    modifiers: tuple[str, ...] = (),
) -> tuple[RequiredDocRow, ...]:
    """Compose the required-document set per the registry's own composition
    order: baseline first, then archetypes in REGISTRY order (not input
    order), then modifiers in registry order. Byte-identical duplicate ids are
    de-duplicated; conflicting duplicate ids fail (registry policy)."""
    if mode not in ("baseline-only", "archetyped"):
        raise ValueError(f"invalid declaration mode: {mode!r}")
    registry = load_registry("required_documents")
    archetype_registry = load_registry("archetypes")
    registry_archetype_order = [entry["id"] for entry in archetype_registry["archetypes"]]
    registry_modifier_order = [entry["id"] for entry in archetype_registry["modifiers"]]

    rows_by_id: dict[str, RequiredDocRow] = {}
    raw_by_id: dict[str, dict[str, Any]] = {}

    def _add(raw: Mapping[str, Any], source: str) -> None:
        doc_id = raw["id"]
        if doc_id in raw_by_id and raw_by_id[doc_id] != dict(raw):
            raise RequiredDocumentConflict(
                f"required-document id {doc_id!r} conflicts between {rows_by_id[doc_id].source!r} and {source!r}"
            )
        if doc_id in raw_by_id:
            return  # byte-identical duplicate -- de-dupe silently.
        raw_by_id[doc_id] = dict(raw)
        rows_by_id[doc_id] = RequiredDocRow(
            id=doc_id,
            doc_class=raw["class"],
            required=bool(raw.get("required", True)),
            maturity_floor=raw["maturity_floor"],
            l0_stub_allowed=bool(raw.get("l0_stub_allowed", False)),
            l0_note=raw.get("l0_note"),
            source=source,
        )

    for raw in registry["baseline"]:
        _add(raw, "baseline")
    if mode == "archetyped":
        for archetype_id in registry_archetype_order:
            if archetype_id not in archetypes:
                continue
            for raw in registry.get("archetypes", {}).get(archetype_id, ()):
                _add(raw, f"archetype:{archetype_id}")
        for modifier_id in registry_modifier_order:
            if modifier_id not in modifiers:
                continue
            for raw in registry.get("modifiers", {}).get(modifier_id, ()):
                _add(raw, f"modifier:{modifier_id}")
    return tuple(rows_by_id[doc_id] for doc_id in raw_by_id)


def installed_contract_version() -> str:
    return CONTRACT_VERSION


class ContractFloorError(RuntimeError):
    """The installed ``consiliency-contract`` distribution violates this package's
    declared floor (Consiliency/agent-harness#378). Raised only when the violation
    is PROVABLE from readable state -- see ``check_installed_contract_floor``."""


class ContractFloorUnverified(UserWarning):
    """The contract-floor check could not be run because a required operand was
    unreadable or its provenance was unprovable (Consiliency/agent-harness#382,
    board review). Emitted -- never silenced -- in the fail-open path so the
    guard's ABSENCE is visible: silence in a shadowed-runtime environment would
    reproduce the very opacity #378 exists to remove (~60 jsonschema failures with
    no indication a guard even ran)."""


def _dist_records_package(dist: Any, needle: str) -> bool:
    """True iff ``dist``'s OWN file manifest names ``needle`` (``<pkg>/__init__.py``).

    Tries the ``dist.files`` view first (RECORD for a wheel/dist-info; ``SOURCES.txt``
    for an ``.egg-info``) and, whenever that view does NOT match ``needle`` FOR ANY
    REASON, reads the ``RECORD`` and ``SOURCES.txt`` texts DIRECTLY before giving up.

    The direct read is load-bearing on Python 3.12+, and the fallback CONDITION -- "the
    files match failed" rather than "``.files`` was empty" -- is the load-bearing part
    (board #382 r2, lead). ``importlib.metadata`` under 3.12 FILTERS SOURCES.txt by
    on-disk existence: it returns only the entries that resolve relative to the egg-info
    parent, where <= 3.11 returned the manifest verbatim. So ``.files`` can be:
      * EMPTY -- when no listed path resolves (this repo: 817 entries under 3.10, 0
        under 3.12, because SOURCES.txt paths are project-root-relative and don't
        resolve from ``src/``); or
      * NON-EMPTY but PARTIAL -- a surviving sibling remains while the imported module
        itself is filtered out.
    A fallback gated on ``.files`` being empty would be BYPASSED in the partial case
    (non-empty) and the truncated view would false-reject a legitimate owner -- the
    original bug with the repair silently skipped. Gating on "match failed for any
    reason" subsumes both: empty, partial, and None all fall through to the text read.

    Finding 1 stays closed: an empty-record dist -- no ``.files`` match AND no readable
    RECORD/SOURCES.txt naming the package -- still fails here, so a same-root foreign
    floor cannot be carried past this gate (Consiliency/agent-harness#382 r1/r2)."""

    def _names_needle(entries: Any) -> bool:
        for entry in entries:
            # RECORD lines are ``path,hash,size``; SOURCES.txt / ``.files`` are bare
            # paths. Split on the first comma so both shapes reduce to the path.
            path = str(entry).split(",", 1)[0].strip().replace("\\", "/")
            if path.endswith(needle):
                return True
        return False

    # (1) files-based match. Returns True only on a hit; ANY miss -- None, empty, or a
    # partial list that dropped the module (py3.12 existence filter) -- falls through.
    try:
        if _names_needle(dist.files or ()):
            return True
    except Exception:
        pass
    # (2) direct text read -- fires on every files-miss, not only when files was empty.
    for meta in ("RECORD", "SOURCES.txt"):
        try:
            raw = dist.read_text(meta)
        except Exception:
            raw = None
        if raw and _names_needle(raw.splitlines()):
            return True
    return False


def _dist_owns_imported_runtime(dist: Any) -> bool:
    """True iff ``dist`` PROVABLY ships the imported ``phase_loop_runtime`` package.

    Provenance check (Consiliency/agent-harness#378; board #382 r1 Finding 1, r2
    Finding 1). ``importlib.metadata`` resolves a distribution by NAME, and a name
    can be answered by an install that is not the running code -- a site-packages
    ``phase-loop-runtime`` shadowed by this ``src/`` checkout, or a stale
    ``.egg-info`` left beside a real one. That install's declared floor need not
    match the running code, so trusting it by name lets the guard enforce a foreign
    floor: pass a changed floor silently, or abort a healthy checkout.

    A path comparison alone is UNSOUND (board #382 r2 Finding 1):
    ``PathDistribution.locate_file(p)`` merely joins the metadata directory's parent
    with ``p`` -- it never confirms the distribution RECORDS ``p``. An empty-RECORD
    distribution sharing the same root therefore satisfies a ``locate_file``-equality
    check, and its (foreign) floor gets enforced against a healthy contract -- a
    false collection abort, the exact outcome this guard exists to prevent.

    Ownership requires (A) AND (B):

      (A) RECORDED PACKAGE -- the dist's own file manifest names ``<pkg>/__init__.py``
          (``_dist_records_package``: ``dist.files``, else the RECORD / ``.egg-info``
          ``SOURCES.txt`` text read DIRECTLY whenever the ``.files`` match fails for
          any reason, because Python 3.12+ FILTERS an ``.egg-info`` SOURCES.txt by
          on-disk existence -- yielding an empty OR partial ``.files`` that can drop
          the module; see ``_dist_records_package``). An empty-RECORD or
          foreign-package dist fails here regardless of location, so a bare path-join
          can never carry a foreign floor past this gate.

      (B) BOUND TO THE IMPORTED INSTANCE -- either of:
          B1 CO-LOCATION: the metadata directory is a sibling of the imported
             top-level package dir. True for a wheel / regular install
             (``site-packages/pkg`` beside ``site-packages/pkg-*.dist-info``), a
             classic editable ``.egg-info`` (``src/pkg`` beside ``src/pkg.egg-info``),
             and the clean-room wheel. ``locate_file("")`` yields that parent. B1 is
             deliberately NOT version-gated: a co-located ``.dist-info`` is written
             atomically with the wheel it installs, and a co-located ``.egg-info`` is
             the build metadata for the very ``src/`` tree beside it -- if it lags that
             tree after a rebuild it names an OLDER floor, which is fail-open only
             (warn + skip), never a false abort, so the no-false-failure criterion
             holds. Gating B1 on a version match would instead red the owns-sentinel on
             ordinary dev egg-info/``src`` skew -- trading a documented boundary for a
             brittle assertion (board #382 r2, advisor).
          B2 INSTALL PROVENANCE: ``direct_url.json`` (PEP 610) records the local
             directory the dist was installed FROM; when that directory contains the
             imported ``__file__`` AND the dist's version equals the running module's
             ``__version__``, the resolved dist IS this code even though it lives in
             ``site-packages`` while the import resolves from ``src/``. This is the CI
             matrix (``pip install ./phase-loop-runtime`` then ``python -m pytest``
             with ``src`` on ``sys.path``): without B2 the guard would skip on a
             healthy checkout -- a self-inflicted false failure, the exact acceptance
             criterion this round protects. The version match is load-bearing for B2:
             its install-source link is weaker than co-location -- a STALE non-editable
             install of this same repo would name the tree yet carry an older floor.
             Requiring ``dist.version == __version__`` rejects that stale install (warn
             + skip, never a false abort) while a same-commit CI install matches. (B1
             needs no such gate for a different reason -- see B1 above -- not because
             versions there "cannot skew".) (board #382 r2, advisor).

    Soundness: a PyPI shadow's ``direct_url`` is absent or names a different tree, a
    wrong-location shadow fails B1, and a stale same-repo install fails B2's version
    match, so none passes B (board #382 r1/r2). An empty-RECORD dist fails A.

    Boundary (honest, board #382 r2): this ties the dist to the imported package by
    NAME + LOCATION/INSTALL-SOURCE, not recorded bytes to imported bytes -- hashing
    RECORD entries for byte identity is deliberately out of scope. And a PEP 660
    editable install (whose RECORD lists a ``.pth`` finder, not the package files)
    fails A and so fail-opens with a warning; this repo's CI is a non-editable dir
    install, so that path is a documented boundary, not a live gap.
    """
    try:
        import json
        from urllib.parse import unquote, urlparse

        import phase_loop_runtime

        imported = Path(phase_loop_runtime.__file__).resolve()
        pkg = phase_loop_runtime.__name__.split(".")[0]

        # (A) records the package -- required in every branch.
        needle = f"{pkg}/__init__.py"
        if not _dist_records_package(dist, needle):
            return False

        # (B1) co-location.
        try:
            if Path(dist.locate_file("")).resolve() == imported.parent.parent:
                return True
        except Exception:
            pass

        # (B2) install provenance via direct_url.json, gated on a version match so a
        # STALE non-editable install of this same repo (right tree, older floor) is
        # rejected rather than trusted (board #382 r2, advisor).
        try:
            raw = dist.read_text("direct_url.json")
            if raw:
                url = json.loads(raw).get("url") or ""
                parsed = urlparse(url)
                if parsed.scheme == "file":
                    tree = Path(unquote(parsed.path)).resolve()
                    running_version = getattr(phase_loop_runtime, "__version__", None)
                    if (
                        (tree == imported or tree in imported.parents)
                        and running_version is not None
                        and dist.version == running_version
                    ):
                        return True
        except Exception:
            pass

        return False
    except Exception:
        return False


def declared_contract_requirement() -> str | None:
    """The ``consiliency-contract`` requirement string this package declares, read
    from the dist metadata of the distribution PROVEN to own the imported
    ``phase_loop_runtime`` module (never re-encoded here).

    The floor lives in exactly one place -- ``phase-loop-runtime``'s ``pyproject``
    ``dependencies`` -- and this reads it back from that dist's own metadata so the
    guard cannot silently disagree with the pin it enforces. It returns ``None``
    when the metadata is unreadable OR cannot be shown to belong to the running
    code (``_dist_owns_imported_runtime``), so the caller treats the floor as
    unknowable rather than enforcing a floor that is not the running package's.
    """
    try:
        import importlib.metadata as md
        from packaging.requirements import Requirement

        dist = md.distribution("phase-loop-runtime")
        if not _dist_owns_imported_runtime(dist):
            return None
        for raw in dist.requires or ():
            try:
                req = Requirement(raw)
            except Exception:
                continue
            if req.name == "consiliency-contract":
                # Drop any environment marker; keep name + specifier.
                return raw.split(";", 1)[0].strip()
    except Exception:
        return None
    return None


def assert_contract_floor_satisfied(installed_version: str, requirement: str) -> None:
    """Raise ``ContractFloorError`` if ``installed_version`` does not satisfy the
    specifier in ``requirement`` (a ``name>=x,<y`` string).

    Pure: both inputs are explicit so the check is unit-testable with literals and
    the falsifier runs deterministically regardless of what is installed.
    """
    from packaging.requirements import Requirement
    from packaging.version import Version

    specifier = Requirement(requirement).specifier
    # ``prereleases=True`` so a legitimately-installed prerelease is judged against
    # the specifier's own rules rather than silently excluded.
    if not specifier.contains(Version(installed_version), prereleases=True):
        # Remedy command is DERIVED from ``requirement`` (the single declared floor),
        # never a second hardcoded copy of the specifier -- a second copy is exactly
        # the drift shape that produced this issue.
        raise ContractFloorError(
            f"installed consiliency-contract {installed_version} does not satisfy the "
            f"declared floor '{requirement}'. Reinstall a floor-satisfying contract: "
            f"pip install -U '{requirement}'  (a contract below this floor ships a "
            f"manifest schema that rejects its own version const, which fans out into "
            f"dozens of opaque jsonschema errors -- Consiliency/agent-harness#378)."
        )


def check_installed_contract_floor() -> None:
    """Raise ``ContractFloorError`` iff the installed ``consiliency-contract`` can be
    PROVEN to violate this package's declared floor.

    Fail-open on an unprovable state: if either the declared requirement or the
    installed version is unreadable, this does NOT raise -- the guard exists to
    convert a stale-dependency environment from ~60 opaque validation failures into
    one actionable line, and must never itself become a new false failure.

    But fail-open is not fail-SILENT (board #382, ruling): when the check is skipped
    it emits a ``ContractFloorUnverified`` warning rather than returning quietly.
    Silence here would recreate exactly what #378 removes -- in a shadowed-runtime
    environment the guard would go mute, the stale contract would survive, and the
    operator would face the ~60 opaque jsonschema failures with no sign a guard even
    ran. The condition is abnormal (unreadable metadata, or a distribution that does
    not own the imported module), not a per-run noise source, so the warning names a
    real, bounded gap: the floor is UNVERIFIED, not verified-clean.

    The installed operand is the IMPORTED ``consiliency_contract.CONTRACT_VERSION``
    (via ``installed_contract_version``), not the dist metadata version
    (Consiliency/agent-harness#378, board #382 r1): the manifest schema and version
    const that actually fan out #378's failures ship inside the imported module, so
    a contract-shadow (fresh metadata, stale imported module) must be judged on what
    will RUN, not on what the name resolves to.
    """
    requirement = declared_contract_requirement()
    installed = installed_contract_version()
    if requirement is None or installed is None:
        warnings.warn(
            "consiliency-contract floor check SKIPPED (fail-open): could not "
            "establish both operands for the RUNNING phase_loop_runtime -- the "
            "declared floor was unreadable or resolved to a distribution not proven "
            "to own the imported module, and/or the imported contract version was "
            "unreadable. The floor is therefore UNVERIFIED here: a stale or "
            "mismatched contract will NOT be reported and #378's opaque jsonschema "
            "failures can still occur (Consiliency/agent-harness#378, board #382).",
            ContractFloorUnverified,
            stacklevel=2,
        )
        return
    assert_contract_floor_satisfied(installed, requirement)


def manifest_schema() -> dict[str, Any]:
    return load_schema("manifest")


def contract_version_status_schema() -> dict[str, Any]:
    return load_schema("contract_version_status")


def interface_declaration_schema() -> dict[str, Any]:
    return load_schema("interface_declaration")


def version_skew_protocol() -> dict[str, Any]:
    return load_schema("version_skew_protocol")


def loop_gate_protocol() -> dict[str, Any]:
    return load_schema("loop_gate_protocol")
