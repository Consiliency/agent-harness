from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .discovery import PLAN_RE


SCHEMA_VERSION = 1
# Repo-relative default only; resolution always joins this against an explicit
# repo root supplied by the caller (see _manifest_path) -- never an implicit
# fleet-absolute hardcode (DECOUPLE SL-2).
MANIFEST_PATH = PurePosixPath("plans/manifest.json")
PLAN_TYPES = {"phase", "detailed"}
PLAN_STATUSES = {"imported", "committed", "executing", "completed", "failed", "orphaned"}
TRANSITIONS = {
    "imported": {"executing", "orphaned"},
    "committed": {"executing", "orphaned"},
    "executing": {"completed", "failed", "orphaned"},
}


@dataclass(frozen=True)
class DotfilesPlanRef:
    slug: str
    file: str
    type: str
    status: str


@dataclass(frozen=True)
class DotfilesPlanLifecycleEvent:
    transition: str
    by: str
    at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DotfilesPlanEntry:
    slug: str
    file: str
    type: str
    status: str
    created_at: str
    updated_at: str
    owner_skill: str
    handoff_ref: str | None = None
    reflection_ref: str | None = None
    task_summary: str | None = None
    acceptance_criteria_count: int | None = None
    roadmap_ref: DotfilesPlanRef | None = None
    phase_alias: str | None = None
    if_gates_produced: tuple[str, ...] = ()
    lanes: tuple[str, ...] = ()
    lifecycle: tuple[DotfilesPlanLifecycleEvent, ...] = ()


@dataclass(frozen=True)
class DotfilesPlanManifest:
    schema_version: int = SCHEMA_VERSION
    plans: tuple[DotfilesPlanEntry, ...] = ()


@dataclass(frozen=True)
class EntryValidationResult:
    """Per-entry verdict, aligned to the ``plans`` array by ``index``."""

    index: int
    slug: str | None
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    """Manifest validation verdict — IF-0-MANIFEST-1 (agent-harness#164).

    Backward-compatible: ``valid``/``errors`` remain the whole-manifest aggregate
    that pre-#164 callers relied on. ``structural_valid`` is the manifest-level
    verdict (JSON parses, top-level object, ``schema_version``, plans-is-array);
    when it is False no entry is trustworthy. When it is True, ``entries`` carries
    a per-entry verdict so a single stale/renamed/missing entry is skipped
    (treated orphaned) rather than degrading the whole manifest to regex
    discovery. Positional construction (``ValidationResult(False, (...))``) still
    records a structural failure, so the early structural returns are unchanged.
    """

    structural_valid: bool
    structural_errors: tuple[str, ...] = ()
    entries: tuple[EntryValidationResult, ...] = ()

    @property
    def valid(self) -> bool:
        return self.structural_valid and all(entry.valid for entry in self.entries)

    @property
    def errors(self) -> tuple[str, ...]:
        merged = list(self.structural_errors)
        for entry in self.entries:
            merged.extend(entry.errors)
        return tuple(merged)

    def valid_indices(self) -> frozenset[int]:
        """Indices into the ``plans`` array whose entry passed per-entry validation."""
        return frozenset(entry.index for entry in self.entries if entry.valid)


def read_manifest(repo: Path) -> DotfilesPlanManifest:
    manifest_path = _manifest_path(repo)
    if not manifest_path.exists():
        return DotfilesPlanManifest()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest JSON is malformed at line {exc.lineno} column {exc.colno}") from exc
    manifest = _manifest_from_json(data)
    if manifest.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported manifest schema_version: {manifest.schema_version}")
    return manifest


def append_entry(repo: Path, entry: DotfilesPlanEntry) -> None:
    manifest = read_manifest(repo)
    entries = {existing.slug: existing for existing in manifest.plans}
    entries[entry.slug] = entry
    _write_manifest(repo, DotfilesPlanManifest(plans=tuple(entries[slug] for slug in sorted(entries))))


def update_lifecycle(repo: Path, slug: str, transition: str, by: str, metadata: dict[str, Any]) -> None:
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    manifest = read_manifest(repo)
    now = _utc_now()
    entries: list[DotfilesPlanEntry] = []
    updated = False
    for entry in manifest.plans:
        if entry.slug != slug:
            entries.append(entry)
            continue
        allowed = TRANSITIONS.get(entry.status, set())
        if transition not in allowed:
            raise ValueError(f"invalid lifecycle transition for {slug}: {entry.status} -> {transition}")
        event = DotfilesPlanLifecycleEvent(transition=transition, by=by, at=now, metadata=metadata)
        entries.append(
            DotfilesPlanEntry(
                slug=entry.slug,
                file=entry.file,
                type=entry.type,
                status=transition,
                created_at=entry.created_at,
                updated_at=now,
                owner_skill=entry.owner_skill,
                handoff_ref=entry.handoff_ref,
                reflection_ref=entry.reflection_ref,
                task_summary=entry.task_summary,
                acceptance_criteria_count=entry.acceptance_criteria_count,
                roadmap_ref=entry.roadmap_ref,
                phase_alias=entry.phase_alias,
                if_gates_produced=entry.if_gates_produced,
                lanes=entry.lanes,
                lifecycle=(*entry.lifecycle, event),
            )
        )
        updated = True
    if not updated:
        raise ValueError(f"manifest entry not found: {slug}")
    _write_manifest(repo, DotfilesPlanManifest(plans=tuple(entries)))


def validate_manifest(manifest_path: Path) -> ValidationResult:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ValidationResult(False, ("manifest file does not exist",))
    except json.JSONDecodeError as exc:
        return ValidationResult(False, (f"manifest JSON is malformed at line {exc.lineno} column {exc.colno}",))
    return _validate_manifest_data(data, manifest_path.parent.parent)


def _validate_manifest_data(data: Any, repo: Path) -> ValidationResult:
    """Validate an ALREADY-PARSED manifest object. Split out from
    ``validate_manifest`` so ``valid_phase_entries`` can validate and materialize
    from the SAME in-memory snapshot — a concurrent manifest rewrite between two
    reads would otherwise misalign per-entry indices (single-writer TOCTOU)."""
    if not isinstance(data, dict):
        return ValidationResult(False, ("manifest must be an object",))
    # Structural errors invalidate the WHOLE manifest (nothing is trustworthy);
    # per-entry errors only skip the offending entry (IF-0-MANIFEST-1, #164).
    structural_errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        structural_errors.append("schema_version must be 1")
    plans = data.get("plans")
    if not isinstance(plans, list):
        structural_errors.append("plans must be an array")
        return ValidationResult(False, tuple(structural_errors))
    seen: set[str] = set()
    entry_results: list[EntryValidationResult] = []
    for index, raw_entry in enumerate(plans):
        label = f"plans[{index}]"
        entry_errors: list[str] = []
        if not isinstance(raw_entry, dict):
            entry_errors.append(f"{label} must be an object")
            entry_results.append(EntryValidationResult(index, None, False, tuple(entry_errors)))
            continue
        slug = raw_entry.get("slug")
        if not isinstance(slug, str) or not slug:
            entry_errors.append(f"{label}.slug is required")
        elif slug in seen:
            entry_errors.append(f"{label}.slug duplicates {slug}")
        else:
            seen.add(slug)
        _validate_common_entry(label, raw_entry, repo, entry_errors)
        if raw_entry.get("type") == "phase":
            _validate_phase_entry(label, raw_entry, entry_errors)
        elif raw_entry.get("type") == "detailed":
            _validate_detailed_entry(label, raw_entry, entry_errors)
        _validate_lifecycle(label, raw_entry.get("lifecycle"), entry_errors)
        entry_results.append(
            EntryValidationResult(
                index=index,
                slug=slug if isinstance(slug, str) and slug else None,
                valid=not entry_errors,
                errors=tuple(entry_errors),
            )
        )
    return ValidationResult(
        structural_valid=not structural_errors,
        structural_errors=tuple(structural_errors),
        entries=tuple(entry_results),
    )


def valid_phase_entries(manifest_path: Path) -> tuple[DotfilesPlanEntry, ...] | None:
    """Materialize ONLY the per-entry-VALID ``phase`` entries — IF-0-MANIFEST-1 (#164).

    Returns ``None`` when the manifest is STRUCTURALLY invalid (unparseable JSON,
    wrong ``schema_version``, non-array ``plans``): nothing in it is trustworthy, so
    the caller must consume no entry. Otherwise returns the valid phase entries,
    tolerating parse-hostile *sibling* rows (a non-dict entry / ``roadmap_ref`` /
    lifecycle event): those rows are per-entry INVALID (excluded from
    ``valid_indices``), and this materializes each surviving row on its own so one
    unparseable sibling cannot re-hide the valid entries the way the all-or-nothing
    ``read_manifest`` load would. Every index in ``valid_indices`` passed per-entry
    validation, so ``_entry_from_json`` never raises on it; the guarded ``except``
    is belt-and-suspenders.

    The manifest is read EXACTLY ONCE and both validated and materialized from that
    single in-memory snapshot, so a concurrent rewrite cannot desync the per-entry
    indices from the rows they select."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    result = _validate_manifest_data(data, manifest_path.parent.parent)
    if not result.structural_valid:
        return None
    valid = result.valid_indices()
    entries: list[DotfilesPlanEntry] = []
    for index, raw_entry in enumerate(data.get("plans", [])):
        if index not in valid:
            continue
        try:
            entry = _entry_from_json(raw_entry)
        except ValueError:
            continue
        if entry.type == "phase":
            entries.append(entry)
    return tuple(entries)


def import_existing_phase_plans(repo: Path) -> DotfilesPlanManifest:
    entries: list[DotfilesPlanEntry] = []
    for plan_path in sorted((repo / "plans").glob("phase-plan-v*-*.md")):
        match = PLAN_RE.search(plan_path.name)
        if not match:
            continue
        version, phase_alias = match.groups()
        rel_path = plan_path.relative_to(repo).as_posix()
        slug = f"{version}-{phase_alias}"
        timestamp = _timestamp_for_path(plan_path)
        roadmap_file = _frontmatter_value(plan_path, "roadmap")
        roadmap_ref = (
            DotfilesPlanRef(
                slug=Path(roadmap_file).stem,
                file=roadmap_file,
                type="phase",
                status="imported",
            )
            if roadmap_file
            else None
        )
        entries.append(
            DotfilesPlanEntry(
                slug=slug,
                file=rel_path,
                type="phase",
                status="imported",
                created_at=timestamp,
                updated_at=timestamp,
                owner_skill="codex-plan-phase",
                roadmap_ref=roadmap_ref,
                phase_alias=phase_alias,
                if_gates_produced=_extract_if_gates(plan_path),
                lanes=_extract_lanes(plan_path),
            )
        )
    return DotfilesPlanManifest(plans=tuple(entries))


def _manifest_path(repo: Path) -> Path:
    return Path(repo) / MANIFEST_PATH


def _write_manifest(repo: Path, manifest: DotfilesPlanManifest) -> None:
    manifest_path = _manifest_path(repo)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_manifest_to_json(manifest), indent=2, sort_keys=True) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") == payload:
        return
    manifest_path.write_text(payload, encoding="utf-8")


def _manifest_to_json(manifest: DotfilesPlanManifest) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "plans": [_entry_to_json(entry) for entry in manifest.plans],
    }


def _entry_to_json(entry: DotfilesPlanEntry) -> dict[str, Any]:
    return {
        "acceptance_criteria_count": entry.acceptance_criteria_count,
        "created_at": entry.created_at,
        "file": entry.file,
        "handoff_ref": entry.handoff_ref,
        "if_gates_produced": list(entry.if_gates_produced),
        "lanes": list(entry.lanes),
        "lifecycle": [_event_to_json(event) for event in entry.lifecycle],
        "owner_skill": entry.owner_skill,
        "phase_alias": entry.phase_alias,
        "reflection_ref": entry.reflection_ref,
        "roadmap_ref": _ref_to_json(entry.roadmap_ref) if entry.roadmap_ref else None,
        "slug": entry.slug,
        "status": entry.status,
        "task_summary": entry.task_summary,
        "type": entry.type,
        "updated_at": entry.updated_at,
    }


def _event_to_json(event: DotfilesPlanLifecycleEvent) -> dict[str, Any]:
    return {
        "at": event.at,
        "by": event.by,
        "metadata": event.metadata,
        "transition": event.transition,
    }


def _ref_to_json(ref: DotfilesPlanRef) -> dict[str, Any]:
    return {"file": ref.file, "slug": ref.slug, "status": ref.status, "type": ref.type}


def _manifest_from_json(data: Any) -> DotfilesPlanManifest:
    if not isinstance(data, dict):
        raise ValueError("manifest must be an object")
    plans = data.get("plans", [])
    if not isinstance(plans, list):
        raise ValueError("manifest plans must be an array")
    return DotfilesPlanManifest(
        schema_version=int(data.get("schema_version", 0)),
        plans=tuple(_entry_from_json(entry) for entry in plans),
    )


def _entry_from_json(data: Any) -> DotfilesPlanEntry:
    if not isinstance(data, dict):
        raise ValueError("manifest entry must be an object")
    roadmap_ref = data.get("roadmap_ref")
    return DotfilesPlanEntry(
        slug=str(data.get("slug", "")),
        file=str(data.get("file", "")),
        type=str(data.get("type", "")),
        status=str(data.get("status", "")),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
        owner_skill=str(data.get("owner_skill", "")),
        handoff_ref=data.get("handoff_ref"),
        reflection_ref=data.get("reflection_ref"),
        task_summary=data.get("task_summary"),
        acceptance_criteria_count=data.get("acceptance_criteria_count"),
        roadmap_ref=_ref_from_json(roadmap_ref) if roadmap_ref is not None else None,
        phase_alias=data.get("phase_alias"),
        if_gates_produced=tuple(data.get("if_gates_produced") or ()),
        lanes=tuple(data.get("lanes") or ()),
        lifecycle=tuple(_event_from_json(event) for event in data.get("lifecycle") or ()),
    )


def _event_from_json(data: Any) -> DotfilesPlanLifecycleEvent:
    if not isinstance(data, dict):
        raise ValueError("manifest lifecycle event must be an object")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("manifest lifecycle metadata must be an object")
    return DotfilesPlanLifecycleEvent(
        transition=str(data.get("transition", "")),
        by=str(data.get("by", "")),
        at=str(data.get("at", "")),
        metadata=metadata,
    )


def _ref_from_json(data: Any) -> DotfilesPlanRef:
    if not isinstance(data, dict):
        raise ValueError("manifest plan ref must be an object")
    return DotfilesPlanRef(
        slug=str(data.get("slug", "")),
        file=str(data.get("file", "")),
        type=str(data.get("type", "")),
        status=str(data.get("status", "")),
    )


def _validate_common_entry(label: str, entry: dict[str, Any], repo: Path, errors: list[str]) -> None:
    for field_name in ("file", "type", "status", "created_at", "updated_at", "owner_skill"):
        if not isinstance(entry.get(field_name), str) or not entry.get(field_name):
            errors.append(f"{label}.{field_name} is required")
    if entry.get("type") not in PLAN_TYPES:
        errors.append(f"{label}.type must be phase or detailed")
    if entry.get("status") not in PLAN_STATUSES:
        errors.append(f"{label}.status is invalid")
    file_value = entry.get("file")
    if isinstance(file_value, str) and file_value:
        if Path(file_value).is_absolute() or ".." in PurePosixPath(file_value).parts:
            errors.append(f"{label}.file must be repo-relative")
        elif not (repo / file_value).exists():
            errors.append(f"{label}.file does not exist")


def _validate_phase_entry(label: str, entry: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(entry.get("phase_alias"), str) or not entry.get("phase_alias"):
        errors.append(f"{label}.phase_alias is required for phase entries")
    if entry.get("task_summary") is not None or entry.get("acceptance_criteria_count") is not None:
        errors.append(f"{label} mixes detailed-only fields into a phase entry")
    if not isinstance(entry.get("if_gates_produced"), list):
        errors.append(f"{label}.if_gates_produced must be an array")
    if not isinstance(entry.get("lanes"), list):
        errors.append(f"{label}.lanes must be an array")
    roadmap_ref = entry.get("roadmap_ref")
    if roadmap_ref is not None and not isinstance(roadmap_ref, dict):
        errors.append(f"{label}.roadmap_ref must be an object or null")


def _validate_detailed_entry(label: str, entry: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(entry.get("task_summary"), str) or not entry.get("task_summary"):
        errors.append(f"{label}.task_summary is required for detailed entries")
    if not isinstance(entry.get("acceptance_criteria_count"), int):
        errors.append(f"{label}.acceptance_criteria_count is required for detailed entries")
    if entry.get("roadmap_ref") is not None or entry.get("phase_alias") is not None:
        errors.append(f"{label} mixes phase-only fields into a detailed entry")
    if entry.get("if_gates_produced") not in (None, []):
        errors.append(f"{label}.if_gates_produced must be empty for detailed entries")
    if entry.get("lanes") not in (None, []):
        errors.append(f"{label}.lanes must be empty for detailed entries")


def _validate_lifecycle(label: str, lifecycle: Any, errors: list[str]) -> None:
    if not isinstance(lifecycle, list):
        errors.append(f"{label}.lifecycle must be an array")
        return
    for index, event in enumerate(lifecycle):
        event_label = f"{label}.lifecycle[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{event_label} must be an object")
            continue
        for field_name in ("transition", "by", "at"):
            if not isinstance(event.get(field_name), str) or not event.get(field_name):
                errors.append(f"{event_label}.{field_name} is required")
        if not isinstance(event.get("metadata"), dict):
            errors.append(f"{event_label}.metadata must be an object")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp_for_path(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _frontmatter_value(path: Path, field_name: str) -> str | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    match = re.search(rf"^{re.escape(field_name)}:\s*(.+?)\s*$", text[4:end], re.MULTILINE)
    return match.group(1).strip() if match else None


def _extract_if_gates(path: Path) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    return tuple(dict.fromkeys(re.findall(r"\bIF-[A-Za-z0-9._-]+", text)))


def _extract_lanes(path: Path) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    return tuple(dict.fromkeys(re.findall(r"^###\s+(SL-\d+[A-Z]?)\b", text, re.MULTILINE)))


# ---------------------------------------------------------------------------
# ah#312: phase state lives in TWO stores with no reconciliation between them —
# the runner's snapshot (what `phase-loop status` prints) and this plan manifest.
# They share an execution vocabulary (`executing`, `completed`/`complete`), so when
# they disagree one of them is lying to whoever reads it. Observed on
# specs/phase-plans-convergence-v1.md: status printed `FREEZE: executing` while the
# manifest recorded that phase `completed`.
#
# A phase stuck at `executing` that is actually finished is exactly the state that
# makes resume/dispatch do the wrong thing, and it is indistinguishable — from status
# alone — from a genuinely in-flight phase. So SURFACE the disagreement rather than
# silently rendering one store and discarding the other.
#
# Deliberately CONSERVATIVE: only a DONE-vs-IN-FLIGHT pair is a contradiction. A plan
# that is merely `imported`/`committed` (document written, never executed) says nothing
# about execution state and must not warn — that is the normal case for a planned-but-
# unstarted phase and would drown the real signal.
_MANIFEST_DONE = {"completed"}
_MANIFEST_IN_FLIGHT = {"executing"}
_SNAPSHOT_DONE = {"complete"}
# `blocked` is IN-FLIGHT: the runner is saying work is outstanding / needs repair. A
# manifest that records the same phase `completed` is the motivating harm class exactly —
# resume/repair would act on a phase the other store believes finished, and status alone
# cannot tell it from a genuinely blocked one. (CR: omitting it left a real contradiction
# silent, which this detector's own bar rates worse than a false positive.)
#
# Deliberately still EXCLUDED: manifest `failed` vs a done snapshot. That is a DONE-vs-DONE
# outcome disagreement, outside this detector's declared done-vs-in-flight scope, and it
# has a legitimate staleness reading — a failed plan superseded by a re-plan should be
# marked orphaned rather than flagged here. Tracked separately rather than widened silently.
#
# `awaiting_phase_closeout` belongs with `blocked` for the same reason: resume acts on it
# (handoff.py), and handoff couples the two as a pair at three separate sites. Admitting
# one member of that pair and not its constant companion was a gap in the same matrix.
# `executed` is likewise RESUME-ACTIONABLE: runner.py relaunches the execute action for
# `status in {"planned", "executed"}`, i.e. acceptance/evidence is still unresolved. A
# manifest recording that same phase `completed` is the motivating harm class again.
# (Kept `awaiting_phase_closeout` here rather than on the done side: handoff.py treats it
# as needing action, pairing it with `blocked` at three sites.)
_SNAPSHOT_IN_FLIGHT = {
    "executing", "planned", "blocked", "awaiting_phase_closeout", "executed",
}


def phase_status_disagreements(
    snapshot_phases: Mapping[str, str],
    entries: Sequence[DotfilesPlanEntry],
    *,
    roadmap_slug: str | None = None,
) -> list[tuple[str, str, str]]:
    """Phases where the runner snapshot and the plan manifest CONTRADICT each other.

    Returns ``[(phase_alias, snapshot_status, manifest_status), ...]``, empty when the
    two stores agree or say nothing comparable. Pure — no I/O — so it is testable
    without a repo.
    """
    out: list[tuple[str, str, str]] = []
    _alias_counts: dict[str, int] = {}
    for e in entries:
        a = getattr(e, "phase_alias", None)
        if a:
            _alias_counts[a] = _alias_counts.get(a, 0) + 1
    _ambiguous_aliases = {a for a, n in _alias_counts.items() if n > 1}
    for entry in entries:
        alias = getattr(entry, "phase_alias", None)
        if not alias or alias not in snapshot_phases:
            continue
        if roadmap_slug is not None:
            ref = getattr(entry, "roadmap_ref", None)
            ref_slug = getattr(ref, "slug", None) if ref else None
            if ref_slug is not None:
                if ref_slug != roadmap_slug:
                    continue
            elif _ambiguous_aliases and alias in _ambiguous_aliases:
                # CR: legacy entries carry `roadmap_ref: null` (6 exist today, all from
                # v4). Admitting them keeps the signal for a legitimately-associated entry
                # whose frontmatter is missing — but if the SAME alias appears more than
                # once in the manifest we cannot tell which roadmap it belongs to, and
                # reporting it would name a phase from a DIFFERENT roadmap as contradicting
                # the active one. That is actively misleading, so require positive
                # association in exactly that ambiguous case.
                continue
        snap = snapshot_phases[alias]
        man = getattr(entry, "status", "")
        contradiction = (
            (man in _MANIFEST_DONE and snap in _SNAPSHOT_IN_FLIGHT)
            or (man in _MANIFEST_IN_FLIGHT and snap in _SNAPSHOT_DONE)
        )
        if contradiction:
            out.append((alias, snap, man))
    return out


# ---------------------------------------------------------------------------
# LEGIBLE (v10 SL-1) — exact HEAD/index/filesystem plan-manifest scope audit
#
# `canonical_plan_files` is the stable UNION of canonical phase-plan paths in
# the runner-captured HEAD tree, the stage-0 Git index, and a bounded direct
# physical scan of `plans/` -- never a read of plan CONTENT. See
# plans/phase-plan-v10-LEGIBLE.md ("The authoritative plan scope is frozen as
# follows").

MANIFEST_MALFORMED_KINDS = frozenset(
    {"noncanonical", "path-escape", "conflicted-index", "symlink", "non-regular", "undecodable-name"}
)
MANIFEST_ORIGIN_FLAGS = frozenset({"head", "index", "filesystem", "manifest"})

_CANONICAL_LOOKALIKE_RE = re.compile(r"^phase-plan-.*\.md$")


@dataclass(frozen=True)
class CanonicalPlanEntry:
    path: str
    origin: frozenset[str]


@dataclass(frozen=True)
class MalformedPlanFinding:
    path: str
    kind: str
    origin: frozenset[str]


@dataclass(frozen=True)
class MissingPlanFinding:
    path: str
    origin: str


@dataclass(frozen=True)
class CanonicalPlanFiles:
    entries: tuple[CanonicalPlanEntry, ...]
    malformed: tuple[MalformedPlanFinding, ...]

    def paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries)

    def origins_of(self, path: str) -> frozenset[str]:
        for entry in self.entries:
            if entry.path == path:
                return entry.origin
        return frozenset()


@dataclass(frozen=True)
class ManifestPresenceReport:
    canonical_count: int
    registered_count: int
    unregistered_count: int
    unregistered: tuple[str, ...]

    @classmethod
    def build(
        cls, repo: Path, canonical: CanonicalPlanFiles, registered_paths: Sequence[str] | set
    ) -> "ManifestPresenceReport":
        canonical_set = set(canonical.paths())
        registered_set = set(registered_paths)
        unregistered = tuple(sorted(canonical_set - registered_set))
        return cls(
            canonical_count=len(canonical_set),
            registered_count=len(canonical_set & registered_set),
            unregistered_count=len(unregistered),
            unregistered=unregistered,
        )


@dataclass(frozen=True)
class ManifestCheckResult:
    exit_code: int
    missing: tuple[MissingPlanFinding, ...]
    malformed: tuple[MalformedPlanFinding, ...]
    canonical_count: int
    registered_count: int


def _repo_relative_posix(repo: Path, raw_path: bytes | str) -> str | None:
    """Decode+normalize a Git/OS path to a repo-relative POSIX string, or
    ``None`` when it is undecodable, absolute, or contains ``.``/``..``."""
    if isinstance(raw_path, bytes):
        try:
            text = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        text = raw_path
    if text.startswith("/") or text.startswith("\\"):
        return None
    parts = PurePosixPath(text).parts
    if any(part in (".", "..") for part in parts):
        return None
    return text


def _classify_basename(basename: str) -> str:
    """``"canonical"`` (full-matches ``PLAN_RE``), ``"lookalike"`` (has the
    ``phase-plan-*.md`` shape but does not full-match), or ``"irrelevant"``
    (not plan-shaped at all -- silently excluded, never malformed)."""
    if PLAN_RE.fullmatch(basename):
        return "canonical"
    if _CANONICAL_LOOKALIKE_RE.match(basename):
        return "lookalike"
    return "irrelevant"


def _git_ls_tree_plans(repo: Path, tree_oid: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-z", "--name-only", tree_oid, "--", "plans/"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        return []
    return [chunk.decode("utf-8", "surrogateescape") for chunk in proc.stdout.split(b"\0") if chunk]


def _git_ls_files_stage_plans(repo: Path) -> list[tuple[str, str]]:
    """Stage-0 index entries under ``plans/`` as ``(rel_path, blob_oid)``."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--stage", "--", "plans/"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        return []
    out: list[tuple[str, str]] = []
    for chunk in proc.stdout.split(b"\0"):
        if not chunk:
            continue
        meta, _, path_bytes = chunk.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3 or fields[2] != b"0":
            continue  # not stage-0 (conflicted); handled separately
        out.append((path_bytes.decode("utf-8", "surrogateescape"), fields[1].decode("ascii")))
    return out


def _git_conflicted_index_plans(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--stage", "--", "plans/"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        return []
    conflicted: set[str] = set()
    for chunk in proc.stdout.split(b"\0"):
        if not chunk:
            continue
        meta, _, path_bytes = chunk.partition(b"\t")
        fields = meta.split()
        if len(fields) == 3 and fields[2] != b"0":
            conflicted.add(path_bytes.decode("utf-8", "surrogateescape"))
    return sorted(conflicted)


def _scan_plans_dir_physical(repo: Path) -> tuple[list[str], list[MalformedPlanFinding]]:
    """Direct-child physical scan of ``plans/`` -- filesystem-safe byte decoding,
    never following a directory-entry symlink, never reading plan content."""
    plans_dir = repo / "plans"
    if not plans_dir.is_dir() or plans_dir.is_symlink():
        return [], []
    canonical: list[str] = []
    malformed: list[MalformedPlanFinding] = []
    try:
        raw_entries = os.listdir(os.fsencode(plans_dir))
    except OSError:
        return [], []
    for raw_name in raw_entries:
        try:
            name = raw_name.decode("utf-8")
        except UnicodeDecodeError:
            rel_bytes = b"plans/" + raw_name
            malformed.append(
                MalformedPlanFinding(
                    path=os.fsdecode(rel_bytes), kind="undecodable-name", origin=frozenset({"filesystem"})
                )
            )
            continue
        classification = _classify_basename(name)
        if classification == "irrelevant":
            continue
        rel = f"plans/{name}"
        full_path = plans_dir / name
        try:
            entry_stat = full_path.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(entry_stat.st_mode):
            malformed.append(MalformedPlanFinding(path=rel, kind="symlink", origin=frozenset({"filesystem"})))
            continue
        if classification == "lookalike":
            malformed.append(MalformedPlanFinding(path=rel, kind="noncanonical", origin=frozenset({"filesystem"})))
            continue
        if not stat.S_ISREG(entry_stat.st_mode):
            malformed.append(MalformedPlanFinding(path=rel, kind="non-regular", origin=frozenset({"filesystem"})))
            continue
        canonical.append(rel)
    return canonical, malformed


def canonical_plan_files(repo: Path, tree_oid: str) -> CanonicalPlanFiles:
    """The stable union of canonical phase-plan paths across the runner-captured
    ``tree_oid`` (typically ``HEAD``), the stage-0 Git index, and a bounded
    direct physical scan of ``plans/`` -- retaining each path's source-origin
    flags. Also consults the LEGIBLE roadmap-status accessor (best-effort,
    non-fatal) so manifest reporting shares that coherence-checked read path."""
    repo = Path(repo).resolve()

    try:
        from . import roadmap_lint

        roadmap_lint.read_roadmap_status(repo, repo / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL)
    except Exception:
        pass  # best-effort: manifest scanning never depends on status coherence

    origins: dict[str, set[str]] = {}
    malformed: list[MalformedPlanFinding] = []

    for raw in _git_ls_tree_plans(repo, tree_oid):
        rel = _repo_relative_posix(repo, raw)
        if rel is None or "/" in rel[len("plans/"):]:
            continue
        basename = rel.rsplit("/", 1)[-1]
        classification = _classify_basename(basename)
        if classification == "canonical":
            origins.setdefault(rel, set()).add("head")
        elif classification == "lookalike":
            malformed.append(MalformedPlanFinding(path=rel, kind="noncanonical", origin=frozenset({"head"})))

    for raw, _blob in _git_ls_files_stage_plans(repo):
        rel = _repo_relative_posix(repo, raw)
        if rel is None or "/" in rel[len("plans/"):]:
            continue
        basename = rel.rsplit("/", 1)[-1]
        classification = _classify_basename(basename)
        if classification == "canonical":
            origins.setdefault(rel, set()).add("index")
        elif classification == "lookalike":
            malformed.append(MalformedPlanFinding(path=rel, kind="noncanonical", origin=frozenset({"index"})))

    for rel in _git_conflicted_index_plans(repo):
        clean_rel = _repo_relative_posix(repo, rel)
        if clean_rel is None:
            continue
        malformed.append(MalformedPlanFinding(path=clean_rel, kind="conflicted-index", origin=frozenset({"index"})))

    physical_canonical, physical_malformed = _scan_plans_dir_physical(repo)
    for rel in physical_canonical:
        origins.setdefault(rel, set()).add("filesystem")
    malformed.extend(physical_malformed)

    entries = tuple(
        CanonicalPlanEntry(path=path, origin=frozenset(flags)) for path, flags in sorted(origins.items())
    )
    return CanonicalPlanFiles(entries=entries, malformed=tuple(malformed))


def _manifest_entry_scope(repo: Path) -> tuple[set[str], list[MalformedPlanFinding]]:
    """Registered ``plans/`` entries from ``plans/manifest.json``, subjected to
    the same repo-relative/direct-child/full-match checks as canonical
    scanning, plus any malformed entry path (origin ``"manifest"``)."""
    manifest_path = repo / "plans" / "manifest.json"
    if not manifest_path.exists():
        return set(), []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), []
    if not isinstance(data, dict):
        return set(), []
    registered: set[str] = set()
    malformed: list[MalformedPlanFinding] = []
    for entry in data.get("plans", []):
        if not isinstance(entry, dict):
            continue
        file_value = entry.get("file")
        if not isinstance(file_value, str) or not file_value:
            continue
        normalized = file_value.replace("\\", "/")
        basename = normalized.rstrip("/").rsplit("/", 1)[-1]
        classification = _classify_basename(basename)
        if classification == "irrelevant":
            continue
        rel = _repo_relative_posix(repo, file_value)
        if rel is None:
            malformed.append(MalformedPlanFinding(path=file_value, kind="path-escape", origin=frozenset({"manifest"})))
            continue
        if not rel.startswith("plans/") or "\\" in rel or "/" in rel[len("plans/"):]:
            malformed.append(
                MalformedPlanFinding(path=file_value, kind="noncanonical", origin=frozenset({"manifest"}))
            )
            continue
        if classification == "canonical":
            if rel in registered:
                malformed.append(
                    MalformedPlanFinding(path=rel, kind="duplicate", origin=frozenset({"manifest"}))
                )
            else:
                registered.add(rel)
        elif classification == "lookalike":
            malformed.append(MalformedPlanFinding(path=rel, kind="noncanonical", origin=frozenset({"manifest"})))
    return registered, malformed


def check(repo: Path) -> ManifestCheckResult:
    """Read-only audit: names every missing, extra, duplicate, malformed,
    conflicted-index, symlink, non-regular, or escaping path. Never
    auto-registers, deletes, or silently ignores a plan."""
    repo = Path(repo).resolve(strict=True)
    canonical = canonical_plan_files(repo, "HEAD")
    registered, manifest_malformed = _manifest_entry_scope(repo)
    canonical_set = set(canonical.paths())

    missing = tuple(
        MissingPlanFinding(path=path, origin=sorted(canonical.origins_of(path))[0])
        for path in sorted(canonical_set - registered)
    )
    extra = tuple(
        MalformedPlanFinding(path=path, kind="extra", origin=frozenset({"manifest"}))
        for path in sorted(registered - canonical_set)
    )
    malformed = tuple(canonical.malformed) + tuple(manifest_malformed) + extra
    exit_code = 0 if not missing and not malformed else 1
    return ManifestCheckResult(
        exit_code=exit_code,
        missing=missing,
        malformed=malformed,
        canonical_count=len(canonical_set),
        registered_count=len(canonical_set & registered),
    )


def unregistered_plan_files(repo: Path) -> tuple[str, ...]:
    """Canonical plan paths that are NOT currently registered in
    ``plans/manifest.json``, stable path-sorted."""
    repo = Path(repo).resolve()
    canonical = canonical_plan_files(repo, "HEAD")
    registered, _malformed = _manifest_entry_scope(repo)
    return tuple(sorted(set(canonical.paths()) - registered))


def _git_first_add_commit_iso(repo: Path, rel_path: str) -> str:
    """The committer timestamp of the FIRST commit that added ``rel_path``
    (frozen Git evidence, never filesystem mtime or wall clock)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "log", "--diff-filter=A", "--format=%cI", "--follow", "--", rel_path],
        capture_output=True, text=True, check=False,
    )
    lines = [line for line in proc.stdout.strip().splitlines() if line]
    text = lines[-1] if lines else ""
    if not text:
        proc = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%cI", "--", rel_path],
            capture_output=True, text=True, check=False,
        )
        text = proc.stdout.strip()
    if not text:
        return "1970-01-01T00:00:00Z"
    # `%cI` carries the committer's ORIGINAL offset; normalize to UTC (frozen
    # Git evidence, never filesystem mtime or wall clock).
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def register_historical_plans(repo: Path, *, dry_run: bool = False) -> tuple[dict[str, Any], ...]:
    """Register the closed eleven-path historical plan set (LEGIBLE-B2) using
    the frozen seven-completed/four-orphaned lifecycle matrix. Idempotent:
    rerunning against an already-identical entry leaves it untouched, and
    ``dry_run=True`` computes byte-identical projected entries without writing.
    Never auto-registers arbitrary discoveries -- the registration set is the
    closed list below, not a scan result."""
    repo = Path(repo).resolve()
    projected: list[dict[str, Any]] = []
    for rel_path, status in sorted(HISTORICAL_PLAN_LIFECYCLE_MATRIX.items()):
        plan_path = repo / rel_path
        match = PLAN_RE.search(Path(rel_path).name)
        alias = match.group(2) if match else Path(rel_path).stem
        roadmap_file = _frontmatter_value(plan_path, "roadmap") if plan_path.exists() else None
        created_at = _git_first_add_commit_iso(repo, rel_path)
        entry_payload = {
            "acceptance_criteria_count": None,
            "created_at": created_at,
            "file": rel_path,
            "handoff_ref": None,
            "if_gates_produced": [],
            "lanes": [],
            "lifecycle": [],
            "owner_skill": "codex-plan-phase",
            "phase_alias": alias,
            "reflection_ref": None,
            "roadmap_ref": (
                {"file": roadmap_file, "slug": Path(roadmap_file).stem, "status": status, "type": "phase"}
                if roadmap_file
                else None
            ),
            "slug": Path(rel_path).stem.removeprefix("phase-plan-"),
            "status": status,
            "task_summary": None,
            "type": "phase",
            "updated_at": created_at,
        }
        projected.append(entry_payload)

    if dry_run:
        return tuple(projected)

    manifest = read_manifest(repo)
    existing = {entry.slug: entry for entry in manifest.plans}
    for payload in projected:
        slug = payload["slug"]
        roadmap_ref = (
            DotfilesPlanRef(**payload["roadmap_ref"]) if payload["roadmap_ref"] is not None else None
        )
        existing[slug] = DotfilesPlanEntry(
            slug=slug,
            file=payload["file"],
            type=payload["type"],
            status=payload["status"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            owner_skill=payload["owner_skill"],
            roadmap_ref=roadmap_ref,
            phase_alias=payload["phase_alias"],
        )
    _write_manifest(repo, DotfilesPlanManifest(plans=tuple(existing[slug] for slug in sorted(existing))))
    return tuple(projected)


# The frozen seven-completed/four-orphaned historical lifecycle matrix
# (plans/phase-plan-v10-LEGIBLE.md, "The historical lifecycle/evidence matrix
# is frozen as follows").
HISTORICAL_PLAN_LIFECYCLE_MATRIX: dict[str, str] = {
    "plans/phase-plan-v1-task-message-sourcebroker-SOURCEBROKER.md": "completed",
    "plans/phase-plan-v6-CTXFREEZE.md": "completed",
    "plans/phase-plan-v6-CTXIMPL.md": "completed",
    "plans/phase-plan-v6-CTXRELY.md": "completed",
    "plans/phase-plan-v6-CTXDOCS.md": "completed",
    "plans/phase-plan-v6-CTXVERIFY.md": "completed",
    "plans/phase-plan-v7-OAMOCK.md": "completed",
    "plans/phase-plan-v7-OACONTRACT.md": "orphaned",
    "plans/phase-plan-v7-OACORE.md": "orphaned",
    "plans/phase-plan-v7-OAREAL.md": "orphaned",
    "plans/phase-plan-v7-OARELEASE.md": "orphaned",
}


def historical_plan_lifecycle_matrix(repo: Path) -> dict[str, str]:
    """The truthful terminal status (``completed``/``orphaned``) of each of the
    eleven closed historical plans, read from ``plans/manifest.json`` when
    registered there and falling back to the frozen matrix otherwise (a
    synthetic fixture repo that only committed the plan files, with no
    registration yet, still reports the intended terminal disposition)."""
    repo = Path(repo).resolve()
    manifest = read_manifest(repo)
    by_file = {entry.file: entry.status for entry in manifest.plans}
    result: dict[str, str] = {}
    for rel_path, frozen_status in HISTORICAL_PLAN_LIFECYCLE_MATRIX.items():
        result[rel_path] = by_file.get(rel_path, frozen_status)
    return result


def _cli_main(argv: list[str]) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    import sys as _sys

    parser = argparse.ArgumentParser(prog="phase_loop_runtime.plan_manifest")
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    if args.command != "check":
        parser.error(f"unsupported command: {args.command}")
        return 2
    result = check(Path(args.repo))
    for item in result.missing:
        print(f"  missing: {item.path} (origin={item.origin})", file=_sys.stderr)
    for item in result.malformed:
        print(f"  malformed [{item.kind}]: {item.path} (origin={sorted(item.origin)})", file=_sys.stderr)
    if result.exit_code == 0:
        print(f"plan-manifest check: OK canonical={result.canonical_count} registered={result.registered_count} unregistered=0")
    else:
        print(
            f"plan-manifest check: FAIL canonical={result.canonical_count} registered={result.registered_count} "
            f"unregistered={len(result.missing)}",
            file=_sys.stderr,
        )
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _sys.exit(_cli_main(_sys.argv[1:]))
