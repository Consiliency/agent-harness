from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from . import roadmap_assumptions
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

_PINNED_REPO_ROOT_FD: ContextVar[int | None] = ContextVar(
    "pinned_repo_root_fd",
    default=None,
)


CLOSED_DISPOSITIONS = frozenset(
    {"closed", "folded_into_successor", "carried_with_owner"}
)
ISSUE_ID_RE = re.compile(r"^(?:[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+#[1-9][0-9]*$")


def _require_qualified_issue_id(issue_id: Any) -> str:
    if not isinstance(issue_id, str) or ISSUE_ID_RE.fullmatch(issue_id) is None:
        raise ValueError("issue_id must be repository-qualified (e.g. repo#123)")
    return issue_id


@dataclass
class IssueDisposition:
    issue_id: str
    phase: str
    disposition: str
    owner: str
    successor_plan: str | None = None

    def __post_init__(self) -> None:
        _require_qualified_issue_id(self.issue_id)
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise ValueError("phase must be a non-empty string")
        if self.disposition not in CLOSED_DISPOSITIONS:
            raise ValueError(f"disposition must be one of {sorted(CLOSED_DISPOSITIONS)}")
        if self.disposition == "folded_into_successor" and (
            not isinstance(self.successor_plan, str) or not self.successor_plan.strip()
        ):
            raise ValueError("folded_into_successor requires a non-empty successor_plan")
        if not isinstance(self.owner, str) or not self.owner.strip():
            raise ValueError("owner must be a non-empty string")


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
    extensions: dict[str, Any] = field(default_factory=dict)


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

        if entry.type == "phase" and transition == "completed":
            if "issue_inventory" not in metadata or not isinstance(metadata["issue_inventory"], list):
                raise ValueError("issue_inventory is required for phase completed lifecycle")
            if "issue_dispositions" not in metadata or not isinstance(metadata["issue_dispositions"], list):
                raise ValueError("issue_dispositions is required for phase completed lifecycle")

            inventory_ids = [_require_qualified_issue_id(item) for item in metadata["issue_inventory"]]
            if len(inventory_ids) != len(set(inventory_ids)):
                raise ValueError("duplicate issue_id in issue_inventory")

            expected_phase = entry.phase_alias or metadata.get("phase_alias")
            disposition_ids: list[str] = []
            normalized_dispositions: list[dict[str, Any]] = []
            allowed_fields = {"issue_id", "phase", "disposition", "owner", "successor_plan"}

            for item in metadata["issue_dispositions"]:
                if isinstance(item, IssueDisposition):
                    disposition = item
                    serialized = {
                        "issue_id": item.issue_id,
                        "phase": item.phase,
                        "disposition": item.disposition,
                        "owner": item.owner,
                    }
                    if item.successor_plan is not None:
                        serialized["successor_plan"] = item.successor_plan
                elif isinstance(item, dict):
                    extra_fields = set(item) - allowed_fields
                    if extra_fields:
                        raise ValueError(f"unknown field in issue_disposition: {sorted(extra_fields)}")
                    if "owner" not in item:
                        raise ValueError("missing owner field in issue_disposition")
                    try:
                        disposition = IssueDisposition(**item)
                    except TypeError as exc:
                        raise ValueError(f"invalid issue_disposition fields: {exc}") from exc
                    serialized = dict(item)
                else:
                    raise ValueError("issue_dispositions items must be IssueDisposition or dict")

                if expected_phase and disposition.phase != expected_phase:
                    raise ValueError(
                        f"phase mismatch in issue_disposition: expected {expected_phase}, got {disposition.phase}"
                    )
                disposition_ids.append(disposition.issue_id)
                normalized_dispositions.append(serialized)

            if len(disposition_ids) != len(set(disposition_ids)):
                raise ValueError("duplicate issue_id in issue_dispositions")
            if set(inventory_ids) != set(disposition_ids):
                raise ValueError(
                    f"issue_inventory {set(inventory_ids)} and issue_dispositions {set(disposition_ids)} do not match"
                )

            metadata = dict(metadata)
            metadata["issue_dispositions"] = normalized_dispositions

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
                extensions=entry.extensions,
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
    out = dict(entry.extensions)
    out.update({
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
    })
    return out


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
    known_keys = {
        "acceptance_criteria_count",
        "created_at",
        "file",
        "handoff_ref",
        "if_gates_produced",
        "lanes",
        "lifecycle",
        "owner_skill",
        "phase_alias",
        "reflection_ref",
        "roadmap_ref",
        "slug",
        "status",
        "task_summary",
        "type",
        "updated_at",
    }
    extensions = {key: value for key, value in data.items() if key not in known_keys}
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
        extensions=extensions,
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
    {
        "noncanonical", "path-escape", "conflicted-index", "symlink", "non-regular",
        "undecodable-name", "plan-contract", "plan-digest",
    }
)
MANIFEST_ORIGIN_FLAGS = frozenset({"head", "index", "filesystem", "manifest"})

_CANONICAL_LOOKALIKE_RE = re.compile(r"^phase-plan-.*\.md$")
_LEGIBLE_PLAN_REL = "plans/phase-plan-v10-LEGIBLE.md"
_FROZEN_HISTORICAL_BINDING_PREFIXES: dict[str, tuple[str, ...]] = {
    "plans/phase-plan-v10-CONFORM.md": (
        "b7a98e3754c9930e2237caf24f77737e9622121ae85ab4a346337add20c5634b",
        "6e6be20133d5674f843346cd80cff9e3db0dbd9c75a5df94d2f23a840324fa1d",
        "920099aa6454dc9d57660b59d99733c7864e6c53ad80fc8d41293ec2696b7c05",
        "3ac51f988cb4b1213771853733a879ce855087efa0df2558a69ecfe9aaeb178b",
        "57cd905f29214e85d4b7a64f7c861faa952e4861ed07023b7c26e870e65b618b",
    ),
    "plans/phase-plan-v10-FABPUB.md": (
        "82a54db92c084bcc12ca74cdd09d4ad4657e8cfca5c83300447ccbffb0a2c360",
    ),
    "plans/phase-plan-v10-HARDEN.md": (
        "9c4a22f664cd93a3c63b4ef616d9b654cc003e35f13df873e7c9e86a878abcfa",
    ),
    _LEGIBLE_PLAN_REL: (
        "15252d908e83cceda2cc38a3d20b59772b787af3df80b8ef68cb82b6f019e4ac",
    ),
    "plans/phase-plan-v10-PROOFGATE.md": (
        "999ea4240291f53e5a0fdf69c52a875647b7a1b550476263a2506d33dbceca52",
    ),
    "plans/phase-plan-v10-REVIEWTRUTH.md": (
        "fe57316a6a1f5b113ec93b742492522f649548941ff6d1b905ccd500014459dc",
    ),
}
_FROZEN_AUTHORITY_PREFIXES: dict[str, tuple[str, ...]] = {
    "plans/phase-plan-v10-CONFORM.md": (
        "12d4689b88e54a5175062e508959d7b2b943508c4b48a7aec38d12e15d090f5a",
    ),
    "plans/phase-plan-v10-FABPUB.md": (
        "10461e5b7a0dd6ff074f7951c95225c384ca4dfb4e68604683f641d9e727f59d",
    ),
    "plans/phase-plan-v10-HARDEN.md": (
        "8a0ee7e01f101f63f3e40b7a9acb32841d8d9cac8086851574dbf3be427d38d7",
    ),
    _LEGIBLE_PLAN_REL: (
        "7b4e578ca0dbb34e058e1771078d4698f0002161203277445d1810aa734ba16c",
    ),
    "plans/phase-plan-v10-PROOFGATE.md": (
        "08070ee7baff4f1313532c503f37bfd27f830cde6a19a6b8a96919d82b03e65d",
    ),
    "plans/phase-plan-v10-REVIEWTRUTH.md": (
        "5e90b3a53a26691801216a45ab816f45b98c5c2d76a2961300070f1cc79f78f3",
    ),
}
_LEGIBLE_OWNED_PATHS = (
    ".claude/docs-catalog.json",
    "phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md",
    "phase-loop-runtime/src/phase_loop_runtime/cli.py",
    "phase-loop-runtime/src/phase_loop_runtime/discovery.py",
    "phase-loop-runtime/src/phase_loop_runtime/docs_freshness.py",
    "phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py",
    "phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py",
    "phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py",
    "phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py",
    "phase-loop-runtime/src/phase_loop_runtime/runner.py",
    "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
    "phase-loop-runtime/tests/test_legible_evidence.py",
    "phase-loop-runtime/tests/test_legible_review_repairs.py",
    "phase-loop-runtime/tests/test_legible_roadmap_contract.py",
    "plans/manifest.json",
    "plans/phase-plan-v10-LEGIBLE.md",
    "specs/roadmap-assumption-probes-v10.json",
    "specs/roadmap-status.json",
)
_LEGIBLE_TEST_PATHS = (
    "phase-loop-runtime/tests/test_legible_evidence.py",
    "phase-loop-runtime/tests/test_legible_roadmap_contract.py",
)
_LEGIBLE_PLAN_CONTRACT_FIXED = {
    "absent_registry_selector_falsifier_nodeid": (
        "phase-loop-runtime/tests/test_legible_roadmap_contract.py::"
        "test_absent_registry_selector_rejects_recognized_non_active_banner_and_preserves_no_declaration_legacy"
    ),
    "absent_registry_selector_falsifier_nodeid_sha256": (
        "e65af55d0f3df427f8b1c1b001fbb69b92585f6790f2daa97f47a2f6adbab93a"
    ),
    "activation_env": "PHASE_LOOP_TDD_EXPECT_LEGIBLE",
    "capability_marker": "phase_loop_runtime.legible_evidence:LEGIBLE_CAPABILITY_VERSION=legible.v1",
    "expected_nodeids": 84,
    "legacy_selector_compatibility": "candidate_has_no_lifecycle_declaration",
    "lifecycle": "legible_tdd_candidate_main.v1",
    "log_sha256_scope": "complete_final_v3_sealed_log_bytes",
    "phase_dependencies": [],
    "selector_common_return_contract": (
        "parse_candidate_lifecycle_then_reject_recognized_non_active_with_or_without_registry"
    ),
    "v2_to_v3_preservation": "all_v2_json_values_except_schema_version_and_derived_log_sha256",
    "verification_evidence_contract": "verification_evidence.v3",
    "verification_extension_namespaces": {"phase_loop_runtime.legible_evidence": "LEGIBLE"},
    "verification_extension_registry_owner": "LEGIBLE",
    "verification_extension_reserved_downstream_namespace": "phase_loop_runtime.proofgate_evidence",
}
_LEGIBLE_PLAN_CONTRACT_KEYS = frozenset(
    {
        *_LEGIBLE_PLAN_CONTRACT_FIXED,
        "plan_sha256",
        "roadmap_sha256",
        "owned_paths",
        "owned_paths_count",
        "owned_paths_sha256",
        "test_paths",
    }
)
_PLAN_AUTHORITY_SCHEMA = "plan_current_authority.v1"
_PLAN_AUTHORITY_KEYS = frozenset(
    {"schema", "source", "plan_sha256", "roadmap_sha256"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestSourceError(RuntimeError):
    """A required HEAD, index, or physical-plan source could not be read."""


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


def _darwin_clonefileat_bytes(repo: Path, parent_fd: int, name: str) -> bytes | None:
    """Atomically clone and read one Darwin regular file without data-opening it."""
    if sys.platform != "darwin":
        return None
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or directory is None or nonblock is None:
        return None
    try:
        clonefileat = ctypes.CDLL(None, use_errno=True).clonefileat
        clonefileat.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint32,
        )
        clonefileat.restype = ctypes.c_int
        with tempfile.TemporaryDirectory(
            prefix=".plan-manifest-clone-", dir=repo.parent
        ) as temp_dir:
            cloexec = getattr(os, "O_CLOEXEC", 0)
            temp_fd = os.open(
                temp_dir, os.O_RDONLY | directory | nofollow | cloexec
            )
            try:
                clone_name = b"snapshot"
                if clonefileat(
                    parent_fd,
                    os.fsencode(name),
                    temp_fd,
                    clone_name,
                    0x0001,
                ) != 0:
                    return None
                clone_fd = os.open(
                    os.fsdecode(clone_name),
                    os.O_RDONLY | nonblock | nofollow | cloexec,
                    dir_fd=temp_fd,
                )
                try:
                    if not stat.S_ISREG(os.fstat(clone_fd).st_mode):
                        return None
                    with os.fdopen(os.dup(clone_fd), "rb") as stream:
                        return stream.read()
                finally:
                    os.close(clone_fd)
            finally:
                os.close(temp_fd)
    except (AttributeError, OSError, RuntimeError, ValueError):
        return None


def _regular_repo_files_sha256(
    repo: Path,
    rel_paths: Sequence[str],
    *,
    root_fd: int | None = None,
) -> dict[str, str] | None:
    """Hash stable repository files in one descriptor-pinned transaction."""
    root = Path(repo) if root_fd is not None else repo.resolve(strict=True)
    requested = tuple(rel_paths)
    if not requested or len(set(requested)) != len(requested):
        return None
    path_parts: dict[str, tuple[str, ...]] = {}
    for rel_path in requested:
        parts = PurePosixPath(rel_path).parts
        if not parts or _repo_relative_posix(root, rel_path) != rel_path:
            return None
        path_parts[rel_path] = parts
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    path_only = getattr(os, "O_PATH", None)
    proc_anchor = path_only is not None and Path("/proc/self/fd").is_dir()
    darwin_clone = sys.platform == "darwin"
    if (
        nofollow is None
        or directory is None
        or nonblock is None
        or not (proc_anchor or darwin_clone)
    ):
        return None
    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | directory | nofollow | cloexec
    file_flags = os.O_RDONLY | nonblock | cloexec
    anchor_flags = path_only | nofollow | cloexec if proc_anchor else 0

    def directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    def file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    try:
        with ExitStack() as opened:
            owns_root = root_fd is None
            if owns_root:
                root_before = os.stat(root, follow_symlinks=False)
                if not stat.S_ISDIR(root_before.st_mode):
                    return None
                root_fd = os.open(root, directory_flags)
                opened.callback(os.close, root_fd)
                root_identity = directory_identity(os.fstat(root_fd))
                if root_identity != directory_identity(root_before):
                    return None
            else:
                root_stat = os.fstat(root_fd)
                if not stat.S_ISDIR(root_stat.st_mode):
                    return None
                root_identity = directory_identity(root_stat)

            directory_entries: list[
                tuple[int, str, tuple[int, int, int, int, int]]
            ] = []
            file_entries: list[
                tuple[int, str, tuple[int, int, int, int, int, int], Any | None, str]
            ] = []
            digests: dict[str, str] = {}
            for rel_path in requested:
                parts = path_parts[rel_path]
                parent_fd = root_fd
                for part in parts[:-1]:
                    child_before = os.stat(
                        part, dir_fd=parent_fd, follow_symlinks=False
                    )
                    if not stat.S_ISDIR(child_before.st_mode):
                        return None
                    child_fd = os.open(part, directory_flags, dir_fd=parent_fd)
                    opened.callback(os.close, child_fd)
                    child_stat = os.fstat(child_fd)
                    child_identity = directory_identity(child_stat)
                    child_after = os.stat(
                        part, dir_fd=parent_fd, follow_symlinks=False
                    )
                    if (
                        not stat.S_ISDIR(child_stat.st_mode)
                        or child_identity != directory_identity(child_before)
                        or child_identity != directory_identity(child_after)
                    ):
                        return None
                    directory_entries.append((parent_fd, part, child_identity))
                    parent_fd = child_fd

                file_named_before = os.stat(
                    parts[-1], dir_fd=parent_fd, follow_symlinks=False
                )
                if not stat.S_ISREG(file_named_before.st_mode):
                    return None
                identity = file_identity(file_named_before)
                stream = None
                if proc_anchor:
                    anchor_fd = os.open(parts[-1], anchor_flags, dir_fd=parent_fd)
                    opened.callback(os.close, anchor_fd)
                    anchor_stat = os.fstat(anchor_fd)
                    anchor_identity = file_identity(anchor_stat)
                    file_named_after = os.stat(
                        parts[-1], dir_fd=parent_fd, follow_symlinks=False
                    )
                    if (
                        not stat.S_ISREG(anchor_stat.st_mode)
                        or anchor_identity != identity
                        or anchor_identity != file_identity(file_named_after)
                    ):
                        return None
                    file_fd = os.open(f"/proc/self/fd/{anchor_fd}", file_flags)
                    stream = opened.enter_context(os.fdopen(file_fd, "rb"))
                    file_before = os.fstat(stream.fileno())
                    identity = file_identity(file_before)
                    if not stat.S_ISREG(file_before.st_mode) or identity != anchor_identity:
                        return None
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                    if file_identity(os.fstat(stream.fileno())) != identity:
                        return None
                else:
                    cloned = _darwin_clonefileat_bytes(repo, parent_fd, parts[-1])
                    file_named_after = os.stat(
                        parts[-1], dir_fd=parent_fd, follow_symlinks=False
                    )
                    if cloned is None or file_identity(file_named_after) != identity:
                        return None
                    digest = hashlib.sha256(cloned)
                expected_digest = digest.hexdigest()
                file_entries.append(
                    (parent_fd, parts[-1], identity, stream, expected_digest)
                )
                digests[rel_path] = expected_digest

            # Revalidate every plan/roadmap entry only after the complete composite
            # has been hashed, through each entry's original pinned parent.
            def files_are_current() -> bool:
                for parent_fd, name, identity, stream, expected_digest in file_entries:
                    final = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    if file_identity(final) != identity or not stat.S_ISREG(final.st_mode):
                        return False
                    if stream is None:
                        cloned = _darwin_clonefileat_bytes(repo, parent_fd, name)
                        current_digest = (
                            hashlib.sha256(cloned).hexdigest()
                            if cloned is not None
                            else None
                        )
                    else:
                        if file_identity(os.fstat(stream.fileno())) != identity:
                            return False
                        stream.seek(0)
                        digest = hashlib.sha256()
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                        current_digest = digest.hexdigest()
                    named_after = os.stat(
                        name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    if (
                        current_digest != expected_digest
                        or file_identity(named_after) != identity
                    ):
                        return False
                return True

            if not files_are_current():
                return None
            # Revalidate from the deepest pinned directory back to the root.
            # Directory ctime makes a child replacement visible to its parent,
            # so a swap after a child check is caught by a later ancestor check.
            for entry_parent_fd, part, expected in reversed(directory_entries):
                current = os.stat(
                    part, dir_fd=entry_parent_fd, follow_symlinks=False
                )
                if directory_identity(current) != expected:
                    return None
            if owns_root and directory_identity(
                os.stat(root, follow_symlinks=False)
            ) != root_identity:
                return None
            if not files_are_current():
                return None
            for entry_parent_fd, part, expected in reversed(directory_entries):
                current = os.stat(
                    part, dir_fd=entry_parent_fd, follow_symlinks=False
                )
                if directory_identity(current) != expected:
                    return None
            if owns_root and directory_identity(
                os.stat(root, follow_symlinks=False)
            ) != root_identity:
                return None
            # A read-only verifier cannot freeze later writers. This terminal file
            # observation is the transaction's linearization point: every earlier
            # file and namespace observation has already been cross-checked twice.
            if not files_are_current():
                return None
            return digests
    except (OSError, RuntimeError, ValueError):
        return None


def _regular_repo_file_sha256(repo: Path, rel_path: str) -> str | None:
    """Hash one stable repository-relative regular file without following symlinks."""
    digests = _regular_repo_files_sha256(repo, (rel_path,))
    return digests.get(rel_path) if digests is not None else None


@dataclass(frozen=True)
class _ManifestSnapshot:
    data: bytes | None
    source_error: bool = False
    root_fd: int | None = None
    plans_fd: int | None = None


@contextmanager
def _pinned_manifest_snapshot(
    repo: Path, *, head_oid: str | None = None
) -> Iterator[_ManifestSnapshot]:
    """Keep the exact manifest bytes and path identity pinned through validation."""
    root = repo.resolve(strict=True)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    path_only = getattr(os, "O_PATH", None)
    proc_anchor = path_only is not None and Path("/proc/self/fd").is_dir()
    darwin_clone = sys.platform == "darwin"
    if not (proc_anchor or darwin_clone):
        raise ManifestSourceError("safe manifest snapshots are unavailable")
    if nofollow is None or directory is None or nonblock is None:
        raise ManifestSourceError("descriptor-pinned manifest reads are unavailable")
    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | directory | nofollow | cloexec
    file_flags = os.O_RDONLY | nonblock | cloexec
    anchor_flags = path_only | nofollow | cloexec if proc_anchor else 0

    def directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    def file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    try:
        with ExitStack() as opened:
            root_before = os.stat(root, follow_symlinks=False)
            root_fd = os.open(root, directory_flags)
            opened.callback(os.close, root_fd)
            root_identity = directory_identity(os.fstat(root_fd))
            if (
                not stat.S_ISDIR(root_before.st_mode)
                or root_identity != directory_identity(root_before)
            ):
                raise ManifestSourceError("repository root changed before manifest read")
            plans_before = os.stat("plans", dir_fd=root_fd, follow_symlinks=False)
            plans_fd = os.open("plans", directory_flags, dir_fd=root_fd)
            opened.callback(os.close, plans_fd)
            plans_identity = directory_identity(os.fstat(plans_fd))
            plans_after = os.stat("plans", dir_fd=root_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(plans_before.st_mode)
                or plans_identity != directory_identity(plans_before)
                or plans_identity != directory_identity(plans_after)
            ):
                raise ManifestSourceError("plans directory changed before manifest read")
            pinned_token = _PINNED_REPO_ROOT_FD.set(root_fd)
            opened.callback(_PINNED_REPO_ROOT_FD.reset, pinned_token)

            def ancestry_is_current() -> bool:
                return (
                    directory_identity(
                        os.stat("plans", dir_fd=root_fd, follow_symlinks=False)
                    )
                    == plans_identity
                    and directory_identity(os.stat(root, follow_symlinks=False))
                    == root_identity
                    and directory_identity(
                        os.stat("plans", dir_fd=root_fd, follow_symlinks=False)
                    )
                    == plans_identity
                    and directory_identity(os.stat(root, follow_symlinks=False))
                    == root_identity
                )

            try:
                named_before = os.stat(
                    "manifest.json", dir_fd=plans_fd, follow_symlinks=False
                )
            except FileNotFoundError:
                yield _ManifestSnapshot(None, root_fd=root_fd, plans_fd=plans_fd)
                try:
                    os.stat("manifest.json", dir_fd=plans_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ManifestSourceError("manifest appeared during validation")
                if not ancestry_is_current():
                    raise ManifestSourceError("manifest ancestry changed during validation")
                return

            expected_identity = file_identity(named_before)
            if not stat.S_ISREG(named_before.st_mode):
                yield _ManifestSnapshot(
                    None,
                    source_error=True,
                    root_fd=root_fd,
                    plans_fd=plans_fd,
                )
                named_final = os.stat(
                    "manifest.json", dir_fd=plans_fd, follow_symlinks=False
                )
                if file_identity(named_final) != expected_identity:
                    raise ManifestSourceError("manifest changed during validation")
                if not ancestry_is_current():
                    raise ManifestSourceError("manifest ancestry changed during validation")
                return

            if darwin_clone:
                expected_identity = file_identity(named_before)
                data = _darwin_clonefileat_bytes(repo, plans_fd, "manifest.json")
                named_after = os.stat(
                    "manifest.json", dir_fd=plans_fd, follow_symlinks=False
                )
                if data is None or file_identity(named_after) != expected_identity:
                    yield _ManifestSnapshot(
                        None,
                        source_error=True,
                        root_fd=root_fd,
                        plans_fd=plans_fd,
                    )
                    return

                yield _ManifestSnapshot(
                    data,
                    root_fd=root_fd,
                    plans_fd=plans_fd,
                )

                def cloned_manifest_is_current() -> bool:
                    named_current = os.stat(
                        "manifest.json", dir_fd=plans_fd, follow_symlinks=False
                    )
                    cloned = _darwin_clonefileat_bytes(
                        repo, plans_fd, "manifest.json"
                    )
                    named_final = os.stat(
                        "manifest.json", dir_fd=plans_fd, follow_symlinks=False
                    )
                    return (
                        file_identity(named_current) == expected_identity
                        and cloned == data
                        and file_identity(named_final) == expected_identity
                    )

                if not cloned_manifest_is_current() or not ancestry_is_current():
                    raise ManifestSourceError("manifest changed during validation")
                if not cloned_manifest_is_current() or not ancestry_is_current():
                    raise ManifestSourceError("manifest changed during validation")
                if not cloned_manifest_is_current():
                    raise ManifestSourceError("manifest changed during validation")
                return

            try:
                anchor_fd = os.open(
                    "manifest.json", anchor_flags, dir_fd=plans_fd
                )
                opened.callback(os.close, anchor_fd)
                anchor_identity = file_identity(os.fstat(anchor_fd))
                named_after = os.stat(
                    "manifest.json", dir_fd=plans_fd, follow_symlinks=False
                )
                if (
                    anchor_identity != expected_identity
                    or file_identity(named_after) != expected_identity
                ):
                    raise ManifestSourceError("manifest changed before pinned read")
                file_fd = os.open(f"/proc/self/fd/{anchor_fd}", file_flags)
                stream = opened.enter_context(os.fdopen(file_fd, "rb"))
                stream_identity = file_identity(os.fstat(stream.fileno()))
                if stream_identity != expected_identity:
                    raise ManifestSourceError("manifest changed before data read")
                data = stream.read()
                if file_identity(os.fstat(stream.fileno())) != expected_identity:
                    raise ManifestSourceError("manifest changed during data read")
            except OSError:
                yield _ManifestSnapshot(
                    None,
                    source_error=True,
                    root_fd=root_fd,
                    plans_fd=plans_fd,
                )
                named_final = os.stat(
                    "manifest.json", dir_fd=plans_fd, follow_symlinks=False
                )
                if file_identity(named_final) != expected_identity:
                    raise ManifestSourceError("manifest changed during validation")
                if not ancestry_is_current():
                    raise ManifestSourceError("manifest ancestry changed during validation")
                return

            yield _ManifestSnapshot(
                data,
                root_fd=root_fd,
                plans_fd=plans_fd,
            )
            def manifest_file_is_current() -> bool:
                named_final = os.stat(
                    "manifest.json", dir_fd=plans_fd, follow_symlinks=False
                )
                metadata_current = (
                    file_identity(os.fstat(stream.fileno())) == expected_identity
                    and file_identity(os.fstat(anchor_fd)) == expected_identity
                    and file_identity(named_final) == expected_identity
                )
                if not metadata_current:
                    return False
                stream.seek(0)
                return stream.read() == data

            if not manifest_file_is_current() or not ancestry_is_current():
                raise ManifestSourceError("manifest changed during validation")
            if not manifest_file_is_current() or not ancestry_is_current():
                raise ManifestSourceError("manifest changed during validation")
            # The terminal file observation is the linearization point; mutation
            # after it is subsequent repository state, not part of this snapshot.
            if not manifest_file_is_current():
                raise ManifestSourceError("manifest changed during validation")
    except ManifestSourceError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ManifestSourceError(f"manifest snapshot failed: {exc}") from exc


def _classify_basename(basename: str) -> str:
    """``"canonical"`` (full-matches ``PLAN_RE``), ``"lookalike"`` (has the
    ``phase-plan-*.md`` shape but does not full-match), or ``"irrelevant"``
    (not plan-shaped at all -- silently excluded, never malformed)."""
    if PLAN_RE.fullmatch(basename):
        return "canonical"
    if _CANONICAL_LOOKALIKE_RE.match(basename):
        return "lookalike"
    return "irrelevant"


def _descriptor_repo_path(root_fd: int) -> Path | None:
    for descriptor_root in (Path("/proc/self/fd"), Path("/dev/fd")):
        if descriptor_root.is_dir():
            return descriptor_root / str(root_fd)
    return None


def _git_history_capture(
    repo: Path,
    *args: str,
    text: bool = True,
    root_fd: int | None = None,
) -> subprocess.CompletedProcess:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_GRAFT_FILE"] = os.devnull
    env["GIT_SHALLOW_FILE"] = os.devnull
    effective_root_fd = (
        root_fd if root_fd is not None else _PINNED_REPO_ROOT_FD.get()
    )
    repo_path = str(repo)
    pass_fds: tuple[int, ...] = ()
    if effective_root_fd is not None:
        descriptor_repo = _descriptor_repo_path(effective_root_fd)
        if descriptor_repo is None:
            stdout: str | bytes = "" if text else b""
            stderr: str | bytes = (
                "descriptor-backed Git paths are unavailable"
                if text
                else b"descriptor-backed Git paths are unavailable"
            )
            return subprocess.CompletedProcess(args, 127, stdout, stderr)
        repo_path = str(descriptor_repo)
        pass_fds = (effective_root_fd,)
    try:
        return subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-c",
                "core.commitGraph=false",
                "-C",
                repo_path,
                *args,
            ],
            capture_output=True,
            check=False,
            text=text,
            env=env,
            pass_fds=pass_fds,
        )
    except OSError as exc:
        stdout: str | bytes = "" if text else b""
        stderr: str | bytes = str(exc) if text else str(exc).encode()
        return subprocess.CompletedProcess(args, 127, stdout, stderr)


def _git_error(proc: subprocess.CompletedProcess) -> str:
    stderr = proc.stderr
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace").strip()
    return str(stderr or "").strip()


def _resolve_head_oid(repo: Path) -> str:
    resolved = _git_history_capture(
        repo, "rev-parse", "--verify", "HEAD^{commit}"
    )
    oid = resolved.stdout.strip() if resolved.returncode == 0 else ""
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid) is None:
        raise ManifestSourceError(
            f"git HEAD resolution failed: {_git_error(resolved)}"
        )
    return oid


def _history_boundary_complete(repo: Path) -> bool:
    common_dir = _git_history_capture(
        repo, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    if common_dir.returncode != 0 or not common_dir.stdout.strip():
        raise ManifestSourceError(
            "git common-directory probe failed while resolving manifest history: "
            f"{_git_error(common_dir)}"
        )
    common_path = Path(common_dir.stdout.strip())
    try:
        return not any(
            path.exists() and path.stat().st_size > 0
            for path in (common_path / "shallow", common_path / "info" / "grafts")
        )
    except OSError:
        return False


def _manifest_blob_at_revision(repo: Path, revision: str) -> bytes | None:
    tree = _git_history_capture(
        repo,
        "ls-tree",
        "-z",
        revision,
        "--",
        "plans/manifest.json",
        text=False,
    )
    if tree.returncode != 0:
        raise ManifestSourceError(
            f"git ls-tree failed for manifest at {revision}: {_git_error(tree)}"
        )
    records = [record for record in tree.stdout.split(b"\0") if record]
    if not records:
        return None
    if len(records) != 1:
        raise ManifestSourceError(
            f"manifest tree entry is ambiguous at {revision}"
        )
    meta, separator, path = records[0].partition(b"\t")
    fields = meta.split()
    if (
        separator != b"\t"
        or path != b"plans/manifest.json"
        or len(fields) != 3
        or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob"
    ):
        raise ManifestSourceError(
            f"manifest is not a regular blob at {revision}"
        )
    blob = _git_history_capture(
        repo, "cat-file", "blob", fields[2].decode("ascii"), text=False
    )
    if blob.returncode != 0:
        raise ManifestSourceError(
            f"manifest blob is unavailable at {revision}: {_git_error(blob)}"
        )
    return blob.stdout


def _regular_blobs_sha256_at_revision(
    repo: Path, revision: str, rel_paths: tuple[str, ...]
) -> dict[str, str] | None:
    """Hash regular blobs from one immutable Git tree."""
    requested = tuple(dict.fromkeys(rel_paths))
    if not requested:
        return {}
    tree = _git_history_capture(
        repo,
        "ls-tree",
        "-z",
        revision,
        "--",
        *requested,
        text=False,
    )
    if tree.returncode != 0:
        raise ManifestSourceError(
            f"git ls-tree failed for authority at {revision}: {_git_error(tree)}"
        )
    blobs: dict[str, str] = {}
    for record in (item for item in tree.stdout.split(b"\0") if item):
        meta, separator, path_bytes = record.partition(b"\t")
        fields = meta.split()
        try:
            path = path_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if (
            separator != b"\t"
            or path not in requested
            or path in blobs
            or len(fields) != 3
            or fields[0] not in {b"100644", b"100755"}
            or fields[1] != b"blob"
        ):
            return None
        blob = _git_history_capture(
            repo, "cat-file", "blob", fields[2].decode("ascii"), text=False
        )
        if blob.returncode != 0:
            raise ManifestSourceError(
                f"authority blob is unavailable at {revision}: {_git_error(blob)}"
            )
        blobs[path] = hashlib.sha256(blob.stdout).hexdigest()
    return blobs if set(blobs) == set(requested) else None


def _frozen_paths_in_git_history(repo: Path, head_oid: str) -> set[str]:
    frozen_paths = sorted(_FROZEN_HISTORICAL_BINDING_PREFIXES)
    proc = _git_history_capture(
        repo,
        "log",
        "--full-history",
        "--format=",
        "--name-only",
        head_oid,
        "--",
        *frozen_paths,
    )
    if proc.returncode != 0:
        raise ManifestSourceError(
            f"git log failed while resolving frozen history: {_git_error(proc)}"
        )
    changed_paths = set(proc.stdout.splitlines())
    return set(frozen_paths) & changed_paths


def _ancestor_manifest_sequences(
    repo: Path,
    working_manifest: bytes | None,
    *,
    head_oid: str,
    history_complete: bool,
) -> tuple[
    dict[str, tuple[tuple[str, ...], ...]],
    dict[str, tuple[tuple[str, ...], ...]],
    bool,
]:
    if not history_complete:
        return {}, {}, False
    head_bytes = _manifest_blob_at_revision(repo, head_oid)
    if working_manifest != head_bytes:
        starts = [head_oid]
    else:
        parents = _git_history_capture(
            repo, "rev-list", "--parents", "-n", "1", head_oid
        )
        if parents.returncode != 0:
            raise ManifestSourceError(
                "git rev-list failed while resolving manifest history: "
                f"{_git_error(parents)}"
            )
        fields = parents.stdout.split()
        starts = fields[1:]
    if not starts:
        return {}, {}, history_complete
    revisions = _git_history_capture(
        repo,
        "log",
        "--full-history",
        "--format=%H",
        *starts,
        "--",
        "plans/manifest.json",
    )
    if revisions.returncode != 0:
        raise ManifestSourceError(
            "git log failed while resolving manifest history: "
            f"{_git_error(revisions)}"
        )
    binding_sequences: dict[str, set[tuple[str, ...]]] = {}
    authority_sequences: dict[str, set[tuple[str, ...]]] = {}
    for revision in revisions.stdout.splitlines():
        snapshot = _manifest_blob_at_revision(repo, revision)
        if snapshot is None:
            continue
        try:
            payload = json.loads(snapshot)
        except json.JSONDecodeError:
            continue
        plans = payload.get("plans") if isinstance(payload, dict) else None
        if not isinstance(plans, list):
            continue
        for entry in plans:
            if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
                continue
            authority_history = entry.get("plan_authority_history")
            if not isinstance(authority_history, list) or not authority_history:
                continue
            rel = entry["file"]
            authority_hashes = tuple(
                hashlib.sha256(
                    json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).hexdigest()
                for record in authority_history
                if isinstance(record, dict)
            )
            binding_hashes = tuple(
                hashlib.sha256(
                    json.dumps(event, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).hexdigest()
                for event in entry.get("lifecycle", [])
                if isinstance(event, dict)
                and isinstance(event.get("metadata"), dict)
                and any(
                    key in event["metadata"]
                    for key in ("legible_plan_contract", "digest_rebind")
                )
            )
            if authority_hashes:
                authority_sequences.setdefault(rel, set()).add(authority_hashes)
            if binding_hashes:
                binding_sequences.setdefault(rel, set()).add(binding_hashes)
    return (
        {rel: tuple(sorted(values)) for rel, values in binding_sequences.items()},
        {rel: tuple(sorted(values)) for rel, values in authority_sequences.items()},
        history_complete,
    )


def _git_ls_tree_plans(repo: Path, tree_oid: str) -> list[str]:
    proc = _git_history_capture(
        repo, "ls-tree", "-z", "--name-only", tree_oid, "--", "plans/", text=False
    )
    if proc.returncode != 0:
        raise ManifestSourceError(
            f"git ls-tree failed for {tree_oid}: {_git_error(proc)}"
        )
    return [chunk.decode("utf-8", "surrogateescape") for chunk in proc.stdout.split(b"\0") if chunk]


def _git_ls_files_stage_plans(
    repo: Path, *, root_fd: int | None = None
) -> list[tuple[str, str, str]]:
    """Stage-0 index entries under ``plans/`` as ``(rel_path, blob_oid, mode)``."""
    proc = _git_history_capture(
        repo,
        "ls-files",
        "-z",
        "--stage",
        "--",
        "plans/",
        text=False,
        root_fd=root_fd,
    )
    if proc.returncode != 0:
        raise ManifestSourceError(f"git ls-files failed: {_git_error(proc)}")
    out: list[tuple[str, str, str]] = []
    for chunk in proc.stdout.split(b"\0"):
        if not chunk:
            continue
        meta, _, path_bytes = chunk.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3 or fields[2] != b"0":
            continue  # not stage-0 (conflicted); handled separately
        out.append(
            (
                path_bytes.decode("utf-8", "surrogateescape"),
                fields[1].decode("ascii"),
                fields[0].decode("ascii"),
            )
        )
    return out


def _git_conflicted_index_plans(
    repo: Path, *, root_fd: int | None = None
) -> list[str]:
    proc = _git_history_capture(
        repo,
        "ls-files",
        "-z",
        "--stage",
        "--",
        "plans/",
        text=False,
        root_fd=root_fd,
    )
    if proc.returncode != 0:
        raise ManifestSourceError(
            f"git conflicted-index scan failed: {_git_error(proc)}"
        )
    conflicted: set[str] = set()
    for chunk in proc.stdout.split(b"\0"):
        if not chunk:
            continue
        meta, _, path_bytes = chunk.partition(b"\t")
        fields = meta.split()
        if len(fields) == 3 and fields[2] != b"0":
            conflicted.add(path_bytes.decode("utf-8", "surrogateescape"))
    return sorted(conflicted)


def _scan_plans_dir_physical(
    repo: Path,
    *,
    root_fd: int | None = None,
    plans_fd: int | None = None,
) -> tuple[list[str], list[MalformedPlanFinding]]:
    """Direct-child physical scan of ``plans/`` -- filesystem-safe byte decoding,
    never following a directory-entry symlink, never reading plan content."""
    plans_dir = repo / "plans"
    canonical: list[str] = []
    malformed: list[MalformedPlanFinding] = []
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise ManifestSourceError("descriptor-pinned plans scans are unavailable")
    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | directory | nofollow | cloexec

    def directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    try:
        with ExitStack() as opened:
            if (root_fd is None) != (plans_fd is None):
                raise ManifestSourceError("physical plans scan descriptors are incomplete")
            owns_descriptors = root_fd is None
            if owns_descriptors:
                root_before = os.stat(repo, follow_symlinks=False)
                root_fd = os.open(repo, directory_flags)
                opened.callback(os.close, root_fd)
                root_identity = directory_identity(os.fstat(root_fd))
                if (
                    not stat.S_ISDIR(root_before.st_mode)
                    or directory_identity(root_before) != root_identity
                ):
                    raise ManifestSourceError(
                        "physical repository root changed before scan"
                    )
            else:
                root_identity = directory_identity(os.fstat(root_fd))
                if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                    raise ManifestSourceError(
                        "physical repository descriptor is not a directory"
                    )
            plans_before = os.stat("plans", dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISDIR(plans_before.st_mode):
                raise ManifestSourceError(
                    f"physical plans source is missing or not a directory: {plans_dir}"
                )
            if owns_descriptors:
                plans_fd = os.open("plans", directory_flags, dir_fd=root_fd)
                opened.callback(os.close, plans_fd)
            plans_identity = directory_identity(os.fstat(plans_fd))
            plans_after = os.stat("plans", dir_fd=root_fd, follow_symlinks=False)
            if (
                plans_identity != directory_identity(plans_before)
                or plans_identity != directory_identity(plans_after)
            ):
                raise ManifestSourceError("physical plans source changed before scan")
            raw_entries = tuple(os.fsencode(name) for name in os.listdir(plans_fd))
            entry_stats: dict[bytes, os.stat_result] = {}
            for raw_name in raw_entries:
                entry_stats[raw_name] = os.stat(
                    raw_name, dir_fd=plans_fd, follow_symlinks=False
                )
            final_entries = tuple(
                os.fsencode(name) for name in os.listdir(plans_fd)
            )
            if sorted(raw_entries) != sorted(final_entries):
                raise ManifestSourceError("physical plans entries changed during scan")
            for raw_name, expected in entry_stats.items():
                current = os.stat(
                    raw_name, dir_fd=plans_fd, follow_symlinks=False
                )
                if (
                    current.st_dev,
                    current.st_ino,
                    current.st_mode,
                    current.st_size,
                    current.st_mtime_ns,
                    current.st_ctime_ns,
                ) != (
                    expected.st_dev,
                    expected.st_ino,
                    expected.st_mode,
                    expected.st_size,
                    expected.st_mtime_ns,
                    expected.st_ctime_ns,
                ):
                    raise ManifestSourceError(
                        "physical plans entry changed during scan"
                    )
            plans_is_current = (
                directory_identity(
                    os.stat("plans", dir_fd=root_fd, follow_symlinks=False)
                )
                == plans_identity
            )
            root_is_current = (
                not owns_descriptors
                or directory_identity(os.stat(repo, follow_symlinks=False))
                == root_identity
            )
            if not plans_is_current or not root_is_current:
                raise ManifestSourceError("physical plans ancestry changed during scan")
    except OSError as exc:
        raise ManifestSourceError(f"cannot scan physical plans source {plans_dir}: {exc}") from exc
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
        entry_stat = entry_stats[raw_name]
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


def canonical_plan_files(
    repo: Path,
    tree_oid: str,
    *,
    snapshot: _ManifestSnapshot | None = None,
) -> CanonicalPlanFiles:
    """The stable union of canonical phase-plan paths across the runner-captured
    ``tree_oid`` (typically ``HEAD``), the stage-0 Git index, and a bounded
    direct physical scan of ``plans/`` -- retaining each path's source-origin
    flags. Also consults the LEGIBLE roadmap-status accessor so a defective
    authority registry cannot be hidden by otherwise valid manifest paths."""
    repo = Path(repo).resolve()

    from . import roadmap_lint

    working_repo = repo
    if snapshot is not None and snapshot.root_fd is not None:
        descriptor_repo = _descriptor_repo_path(snapshot.root_fd)
        if descriptor_repo is None:
            raise ManifestSourceError("descriptor-backed repository paths are unavailable")
        working_repo = descriptor_repo
    roadmap_lint.validate_roadmap_status_coherence(
        working_repo,
        required=False,
        root_fd=snapshot.root_fd if snapshot is not None else None,
    )

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

    for raw, _blob, mode in _git_ls_files_stage_plans(
        repo,
        root_fd=snapshot.root_fd if snapshot is not None else None,
    ):
        rel = _repo_relative_posix(repo, raw)
        if rel is None or "/" in rel[len("plans/"):]:
            continue
        basename = rel.rsplit("/", 1)[-1]
        classification = _classify_basename(basename)
        if mode == "120000":
            malformed.append(MalformedPlanFinding(path=rel, kind="symlink-index", origin=frozenset({"index"})))
            continue
        if mode not in {"100644", "100755"}:
            malformed.append(
                MalformedPlanFinding(path=rel, kind="non-regular-index", origin=frozenset({"index"}))
            )
            continue
        if classification == "canonical":
            origins.setdefault(rel, set()).add("index")
        elif classification == "lookalike":
            malformed.append(MalformedPlanFinding(path=rel, kind="noncanonical", origin=frozenset({"index"})))

    for rel in _git_conflicted_index_plans(
        repo,
        root_fd=snapshot.root_fd if snapshot is not None else None,
    ):
        clean_rel = _repo_relative_posix(repo, rel)
        if clean_rel is None:
            continue
        malformed.append(MalformedPlanFinding(path=clean_rel, kind="conflicted-index", origin=frozenset({"index"})))

    physical_canonical, physical_malformed = _scan_plans_dir_physical(
        repo,
        root_fd=snapshot.root_fd if snapshot is not None else None,
        plans_fd=snapshot.plans_fd if snapshot is not None else None,
    )
    for rel in physical_canonical:
        origins.setdefault(rel, set()).add("filesystem")
    malformed.extend(physical_malformed)

    entries = tuple(
        CanonicalPlanEntry(path=path, origin=frozenset(flags)) for path, flags in sorted(origins.items())
    )
    return CanonicalPlanFiles(entries=entries, malformed=tuple(malformed))


def _manifest_entry_scope(
    repo: Path, *, head_oid: str | None = None
) -> tuple[set[str], list[MalformedPlanFinding]]:
    """Registered ``plans/`` entries from ``plans/manifest.json``, subjected to
    the same repo-relative/direct-child/full-match checks as canonical
    scanning, plus any malformed entry path (origin ``"manifest"``)."""
    expected_head = head_oid or _resolve_head_oid(repo)
    with _pinned_manifest_snapshot(repo, head_oid=expected_head) as snapshot:
        result = _manifest_entry_scope_from_snapshot(
            repo, snapshot, head_oid=expected_head
        )
    if _resolve_head_oid(repo) != expected_head:
        raise ManifestSourceError("HEAD changed during plan manifest validation")
    return result


def _manifest_entry_scope_from_snapshot(
    repo: Path, snapshot: _ManifestSnapshot, *, head_oid: str
) -> tuple[set[str], list[MalformedPlanFinding]]:
    history_complete = _history_boundary_complete(repo)
    frozen_history = (
        _frozen_paths_in_git_history(repo, head_oid) if history_complete else set()
    )
    ancestor_bindings, ancestor_authorities, history_complete = (
        _ancestor_manifest_sequences(
            repo,
            snapshot.data,
            head_oid=head_oid,
            history_complete=history_complete,
        )
    )
    frozen_history.update(ancestor_bindings)
    frozen_history.update(ancestor_authorities)

    history_findings: list[MalformedPlanFinding] = []
    if not history_complete:
        history_findings.append(
            MalformedPlanFinding(
                "plans/manifest.json",
                "history-incomplete",
                frozenset({"manifest"}),
            )
        )
    if snapshot.source_error:
        history_findings.append(
            MalformedPlanFinding(
                "plans/manifest.json",
                "manifest-source",
                frozenset({"manifest"}),
            )
        )

    def frozen_findings(registered: set[str]) -> list[MalformedPlanFinding]:
        return [
            *history_findings,
            *(
                MalformedPlanFinding(
                    required_rel, "plan-contract", frozenset({"manifest"})
                )
                for required_rel in sorted(frozen_history - registered)
            ),
        ]

    if snapshot.data is None:
        return set(), frozen_findings(set())
    try:
        data = json.loads(snapshot.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set(), frozen_findings(set())
    if not isinstance(data, dict):
        return set(), frozen_findings(set())
    registered: set[str] = set()
    malformed: list[MalformedPlanFinding] = list(history_findings)
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
            lifecycle = entry.get("lifecycle")
            contracts: list[dict[str, Any]] = []
            rebinds: list[dict[str, Any]] = []
            historical_binding_hashes: list[str] = []
            historical_binding_declared = False
            historical_binding_malformed = (
                "lifecycle" in entry and not isinstance(lifecycle, list)
            )
            if isinstance(lifecycle, list):
                for event in lifecycle:
                    if not isinstance(event, dict):
                        historical_binding_malformed = True
                        continue
                    metadata = event.get("metadata")
                    if not isinstance(metadata, dict):
                        historical_binding_malformed = True
                        continue
                    binding_in_event = False
                    for key, target in (
                        ("legible_plan_contract", contracts),
                        ("digest_rebind", rebinds),
                    ):
                        if key not in metadata:
                            continue
                        historical_binding_declared = True
                        binding_in_event = True
                        value = metadata[key]
                        if isinstance(value, dict):
                            target.append(value)
                        else:
                            historical_binding_malformed = True
                    if binding_in_event:
                        serialized = json.dumps(
                            event, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")
                        historical_binding_hashes.append(
                            hashlib.sha256(serialized).hexdigest()
                        )
            frozen_prefix = _FROZEN_HISTORICAL_BINDING_PREFIXES.get(rel)
            current_binding_hashes = tuple(historical_binding_hashes)
            if frozen_prefix is not None and current_binding_hashes[
                : len(frozen_prefix)
            ] != frozen_prefix:
                historical_binding_malformed = True
            if any(
                current_binding_hashes[: len(prefix)] != prefix
                for prefix in ancestor_bindings.get(rel, ())
            ):
                historical_binding_malformed = True
            if historical_binding_malformed:
                malformed.append(
                    MalformedPlanFinding(rel, "plan-contract", frozenset({"manifest"}))
                )
            contract = contracts[-1] if contracts else None
            if rel == _LEGIBLE_PLAN_REL:
                owned_digest = hashlib.sha256(
                    "".join(f"{path}\n" for path in _LEGIBLE_OWNED_PATHS).encode("utf-8")
                ).hexdigest()
                required_contract = (
                    isinstance(contract, dict)
                    and set(contract) == _LEGIBLE_PLAN_CONTRACT_KEYS
                    and all(contract.get(key) == value for key, value in _LEGIBLE_PLAN_CONTRACT_FIXED.items())
                    and contract.get("owned_paths") == list(_LEGIBLE_OWNED_PATHS)
                    and contract.get("owned_paths_count") == len(_LEGIBLE_OWNED_PATHS)
                    and contract.get("owned_paths_sha256") == owned_digest
                    and isinstance(contract.get("test_paths"), list)
                    and len(contract["test_paths"]) == len(_LEGIBLE_TEST_PATHS)
                    and set(contract["test_paths"]) == set(_LEGIBLE_TEST_PATHS)
                    and _SHA256_RE.fullmatch(str(contract.get("roadmap_sha256", "")))
                    and _SHA256_RE.fullmatch(str(contract.get("plan_sha256", "")))
                )
                if not required_contract:
                    malformed.append(
                        MalformedPlanFinding(rel, "plan-contract", frozenset({"manifest"}))
                    )
            digests = [item.get("plan_sha256") for item in (*contracts, *rebinds)]
            roadmap_digests = [
                item.get("roadmap_sha256") for item in (*contracts, *rebinds)
            ]
            # Lifecycle contracts and digest rebinds are immutable evidence of the
            # bytes reviewed at that historical event. Comparing every one of them
            # with today's plan makes a valid append-only history impossible after
            # any later amendment. Keep validating their digest syntax, but bind
            # current bytes only through the row-level append-only authority history.
            if any(not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None for digest in digests):
                malformed.append(
                    MalformedPlanFinding(rel, "plan-digest", frozenset({"manifest"}))
                )
            if any(
                not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None
                for digest in roadmap_digests
            ):
                malformed.append(
                    MalformedPlanFinding(rel, "plan-contract", frozenset({"manifest"}))
                )

            authority_history_declared = "plan_authority_history" in entry
            authority_history = entry.get("plan_authority_history")
            roadmap_authority_required = (
                frozen_prefix is not None
                or historical_binding_declared
            )
            authority_required = (
                roadmap_authority_required or rel in ancestor_authorities
            )
            if authority_history is None and (
                authority_history_declared or authority_required
            ):
                malformed.append(
                    MalformedPlanFinding(rel, "plan-contract", frozenset({"manifest"}))
                )
            elif authority_history is not None:
                authority_valid = isinstance(authority_history, list) and bool(authority_history)
                authority_hashes: list[str] = []
                roadmap_ref = entry.get("roadmap_ref")
                roadmap_value = roadmap_ref.get("file") if isinstance(roadmap_ref, dict) else None
                roadmap_rel = (
                    _repo_relative_posix(repo, roadmap_value)
                    if isinstance(roadmap_value, str)
                    else None
                )
                for authority in authority_history if isinstance(authority_history, list) else ():
                    if isinstance(authority, dict):
                        serialized = json.dumps(
                            authority, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")
                        authority_hashes.append(hashlib.sha256(serialized).hexdigest())
                    authority_valid = (
                        authority_valid
                        and isinstance(authority, dict)
                        and set(authority) == _PLAN_AUTHORITY_KEYS
                        and authority.get("schema") == _PLAN_AUTHORITY_SCHEMA
                        and isinstance(authority.get("source"), str)
                        and ISSUE_ID_RE.fullmatch(authority["source"]) is not None
                        and isinstance(authority.get("plan_sha256"), str)
                        and _SHA256_RE.fullmatch(authority["plan_sha256"]) is not None
                        and (
                            authority.get("roadmap_sha256") is None
                            or (
                                isinstance(authority.get("roadmap_sha256"), str)
                                and _SHA256_RE.fullmatch(authority["roadmap_sha256"]) is not None
                            )
                        )
                    )
                frozen_authority_prefix = _FROZEN_AUTHORITY_PREFIXES.get(rel)
                current_authority_hashes = tuple(authority_hashes)
                if frozen_authority_prefix is not None and current_authority_hashes[
                    : len(frozen_authority_prefix)
                ] != frozen_authority_prefix:
                    authority_valid = False
                if any(
                    current_authority_hashes[: len(prefix)] != prefix
                    for prefix in ancestor_authorities.get(rel, ())
                ):
                    authority_valid = False
                current_authority = authority_history[-1] if authority_valid else None
                roadmap_contract_valid = (
                    current_authority is not None
                    and (
                        not roadmap_authority_required
                        or (
                            isinstance(roadmap_ref, dict)
                            and isinstance(current_authority["roadmap_sha256"], str)
                        )
                    )
                    and (
                        (roadmap_ref is None and current_authority["roadmap_sha256"] is None)
                        or (
                            isinstance(roadmap_ref, dict)
                            and isinstance(roadmap_rel, str)
                            and roadmap_rel == roadmap_value
                            and isinstance(current_authority["roadmap_sha256"], str)
                        )
                    )
                )
                if not authority_valid or not roadmap_contract_valid:
                    malformed.append(
                        MalformedPlanFinding(rel, "plan-contract", frozenset({"manifest"}))
                    )
                else:
                    authority_paths = (
                        (rel, roadmap_rel)
                        if isinstance(roadmap_rel, str)
                        else (rel,)
                    )
                    committed_digests = _regular_blobs_sha256_at_revision(
                        repo, head_oid, authority_paths
                    )
                    actual_digests = _regular_repo_files_sha256(
                        repo,
                        authority_paths,
                        root_fd=snapshot.root_fd,
                    )
                    actual_plan = (
                        actual_digests.get(rel)
                        if actual_digests is not None
                        else None
                    )
                    committed_plan = (
                        committed_digests.get(rel)
                        if committed_digests is not None
                        else None
                    )
                    if (
                        current_authority["plan_sha256"] != actual_plan
                        or actual_plan != committed_plan
                    ):
                        malformed.append(
                            MalformedPlanFinding(rel, "plan-digest", frozenset({"manifest"}))
                        )
                    if isinstance(roadmap_rel, str):
                        actual_roadmap = (
                            actual_digests.get(roadmap_rel)
                            if actual_digests is not None
                            else None
                        )
                        committed_roadmap = (
                            committed_digests.get(roadmap_rel)
                            if committed_digests is not None
                            else None
                        )
                        canonical_roadmap = (
                            roadmap_assumptions.CANONICAL_ROADMAP_SHA256
                            if rel == _LEGIBLE_PLAN_REL
                            else actual_roadmap
                        )
                        if (
                            current_authority["roadmap_sha256"] != actual_roadmap
                            or actual_roadmap != committed_roadmap
                            or actual_roadmap != canonical_roadmap
                        ):
                            malformed.append(
                                MalformedPlanFinding(rel, "plan-contract", frozenset({"manifest"}))
                            )
        elif classification == "lookalike":
            malformed.append(MalformedPlanFinding(path=rel, kind="noncanonical", origin=frozenset({"manifest"})))
    malformed.extend(frozen_findings(registered))
    return registered, malformed


def check(repo: Path) -> ManifestCheckResult:
    """Read-only audit: names every missing, extra, duplicate, malformed,
    conflicted-index, symlink, non-regular, or escaping path. Never
    auto-registers, deletes, or silently ignores a plan."""
    repo = Path(repo).resolve(strict=True)
    head_oid = _resolve_head_oid(repo)
    with _pinned_manifest_snapshot(repo, head_oid=head_oid) as snapshot:
        canonical = canonical_plan_files(repo, head_oid, snapshot=snapshot)
        registered, manifest_malformed = _manifest_entry_scope_from_snapshot(
            repo, snapshot, head_oid=head_oid
        )
    if _resolve_head_oid(repo) != head_oid:
        raise ManifestSourceError("HEAD changed during plan manifest validation")
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
    head_oid = _resolve_head_oid(repo)
    with _pinned_manifest_snapshot(repo, head_oid=head_oid) as snapshot:
        canonical = canonical_plan_files(repo, head_oid, snapshot=snapshot)
        registered, _malformed = _manifest_entry_scope_from_snapshot(
            repo, snapshot, head_oid=head_oid
        )
    if _resolve_head_oid(repo) != head_oid:
        raise ManifestSourceError("HEAD changed during plan manifest validation")
    return tuple(sorted(set(canonical.paths()) - registered))


def _git_first_add_commit_iso(repo: Path, rel_path: str) -> str:
    """The committer timestamp of the FIRST commit that added ``rel_path``
    (frozen Git evidence, never filesystem mtime or wall clock)."""
    proc = _git_history_capture(
        repo, "log", "--diff-filter=A", "--format=%cI", "--follow", "--", rel_path
    )
    lines = [line for line in proc.stdout.strip().splitlines() if line]
    text = lines[-1] if lines else ""
    if not text:
        proc = _git_history_capture(
            repo, "log", "-1", "--format=%cI", "--", rel_path
        )
        text = proc.stdout.strip()
    if not text:
        return "1970-01-01T00:00:00Z"
    # `%cI` carries the committer's ORIGINAL offset; normalize to UTC (frozen
    # Git evidence, never filesystem mtime or wall clock).
    parsed = datetime.fromisoformat(text.removesuffix("Z") + ("+00:00" if text.endswith("Z") else ""))
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
