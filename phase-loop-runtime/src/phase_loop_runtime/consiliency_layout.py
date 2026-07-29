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


def _dist_owns_imported_runtime(dist: Any) -> bool:
    """True iff ``dist`` records the ``phase_loop_runtime`` package at the exact
    path the interpreter actually imported.

    This is the provenance check (Consiliency/agent-harness#378, board #382 r1
    Finding 1). ``importlib.metadata`` resolves a distribution by NAME, and a name
    can be answered by an install that is not the code being run -- e.g. a
    site-packages ``phase-loop-runtime 0.7.10`` shadowed by this ``src/`` checkout
    (0.7.13). That install's declared floor need not match the running code, so
    trusting it by name lets the guard enforce a foreign floor: it could pass a
    changed floor silently, or abort a healthy checkout. Comparing the dist's
    recorded ``phase_loop_runtime/__init__.py`` against the imported module's
    ``__file__`` proves the metadata belongs to what runs.
    """
    try:
        import phase_loop_runtime

        imported = Path(phase_loop_runtime.__file__).resolve()
        located = Path(dist.locate_file("phase_loop_runtime/__init__.py")).resolve()
        return located == imported
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
