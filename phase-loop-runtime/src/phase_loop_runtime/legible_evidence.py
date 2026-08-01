"""LEGIBLE (v10 SL-2) — chronology/PR-evidence reducer, roadmap-status evidence,
and the fresh-process verification-sidecar binder.

See ``plans/phase-plan-v10-LEGIBLE.md`` for the ratified contract. This module
is the ``legible_evidence.v1`` reducer plus the installed-capability marker
consumed by the shared activation rule in both frozen test files:

    forced = os.environ.get("PHASE_LOOP_TDD_EXPECT_LEGIBLE") == "1"
    installed = (
        importlib.util.find_spec("phase_loop_runtime.legible_evidence") is not None
        and legible_evidence.LEGIBLE_CAPABILITY_VERSION == "legible.v1"
    )

``LEGIBLE_CAPABILITY_VERSION`` is installed only once every lane's production
surface (SL-0, SL-1, and this module) is complete.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import panel_invoker, roadmap_lint

LEGIBLE_CAPABILITY_VERSION = "legible.v1"

# The two frozen test paths, repo-relative to the TOP-LEVEL monorepo root
# (the same constant test_legible_evidence.py calls ``TEST_PATHS``).
FROZEN_TEST_PATHS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_legible_roadmap_contract.py",
    "phase-loop-runtime/tests/test_legible_evidence.py",
)
_FROZEN_AGENT_HARNESS_347_PATH = "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py"

_SIDECAR_RECORD_SCHEMA = "verification_evidence_sidecar.v1"
_SIDECAR_RECORD_FIELDS = (
    "schema", "path", "byte_length", "sha256", "stage", "expected_head", "bootstrap_head", "process_start_token",
)
_SIDECAR_FILE_NAME = "legible-verification-sidecar.json"
_SIDECAR_PROBE_RECORD_MAX_BYTES = 16 * 1024
_FABLE_PROBE_RESPONSE_MAX_BYTES = 64 * 1024
_OPERATIONAL_EVIDENCE_SCHEMA = "legible_evidence.v1"
_OPERATIONAL_EVIDENCE_FILE_NAME = "legible-operational-evidence.json"
_OPERATIONAL_EVIDENCE_MAX_BYTES = 4 * 1024 * 1024
_OPERATIONAL_EVIDENCE_SECTIONS = frozenset(
    {
        "roadmap_status",
        "chronology",
        "process_attestations",
        "test_execution",
        "pull_request",
        "target_integration",
        "assumption_probes",
        "artifacts",
    }
)
_OPERATIONAL_SECTION_FIELDS = {
    "roadmap_status": frozenset(
        {
            "registry_path",
            "registry_sha256",
            "registry_byte_length",
            "selected_roadmap",
            "tracked_path_set_sha256",
            "roadmaps",
        }
    ),
    "chronology": frozenset(
        {
            "tests_landing",
            "implementation_base",
            "phase_candidate",
            "pr_head",
            "server_merge",
            "candidate_head",
            "plan_path",
            "plan_sha256",
            "roadmap_path",
            "roadmap_sha256",
        }
    ),
    "process_attestations": frozenset({"builder", "attester"}),
    "test_execution": frozenset({"nodeid_count", "nodeid_digest", "default", "forced_red", "final"}),
    "pull_request": frozenset(
        {
            "repository",
            "number",
            "state",
            "base",
            "head",
            "merge_commit",
            "parents",
            "snapshot_path",
            "snapshot_sha256",
            "body_sha256",
            "changed_paths",
        }
    ),
    "target_integration": frozenset({"candidate", "server_merge", "integration", "parents"}),
    "assumption_probes": frozenset({"execution_head", "records"}),
    "artifacts": frozenset({"records"}),
}


# ---------------------------------------------------------------------------
# Typed error hierarchy


class LegibleChronologyError(RuntimeError):
    pass


class LegiblePrEvidenceError(RuntimeError):
    pass


class LegibleSidecarError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LegibleStatusEvidenceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LegibleTestExecutionError(RuntimeError):
    pass


class LegibleProcessBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class OperationalEvidenceValidation:
    ok: bool
    code: str = "ok"
    finding: str | None = None


# ---------------------------------------------------------------------------
# Git plumbing helpers


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise LegibleChronologyError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _git_ok(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def _first_parent_changed_paths(repo: Path, commit: str) -> tuple[str, ...]:
    proc = _git_ok(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent", commit)
    if proc.returncode != 0:
        raise LegibleChronologyError(f"cannot resolve first-parent diff for {commit}: {proc.stderr.strip()}")
    return tuple(sorted(line for line in proc.stdout.splitlines() if line))


def _is_ancestor(repo: Path, sha: str, of: str) -> bool:
    proc = _git_ok(repo, "merge-base", "--is-ancestor", sha, of)
    return proc.returncode == 0


def _rev_parse(repo: Path, ref: str) -> str | None:
    proc = _git_ok(repo, "rev-parse", ref)
    return proc.stdout.strip() if proc.returncode == 0 else None


# ---------------------------------------------------------------------------
# Chronology (5 nodeids)
#
# ``validate_chronology`` is a single, generically-keyworded gate: each concern
# below is checked INDEPENDENTLY, based on which keyword arguments the caller
# supplies (mirroring the frozen suite's independent per-concern call shape),
# so one call can exercise exactly one clause without requiring every other
# clause's real ancestry to exist yet.


def validate_chronology(
    repo: Path,
    *,
    landing_commit: str | None = None,
    allowed_paths: Sequence[str] | None = None,
    base_branch: str | None = None,
    tests_branch: str | None = None,
    impl_branch: str | None = None,
    tests_landing_ancestor_of_base: bool | None = None,
    implementation_range_changed_paths: Sequence[str] | None = None,
    test_blob_oid_at_landing: str | None = None,
    test_blob_oid_at_candidate: str | None = None,
) -> None:
    repo = Path(repo)

    if landing_commit is not None and allowed_paths is not None:
        changed = _first_parent_changed_paths(repo, landing_commit)
        if changed != tuple(sorted(allowed_paths)):
            raise LegibleChronologyError(
                f"{landing_commit}: first-parent diff {list(changed)} is not exactly {sorted(allowed_paths)}"
            )

    if base_branch is not None and tests_branch is not None and impl_branch is not None:
        if base_branch == tests_branch == impl_branch:
            raise LegibleChronologyError(
                f"same-branch base -> tests -> implementation sequence: {base_branch!r}"
            )

    if tests_landing_ancestor_of_base is False:
        raise LegibleChronologyError("the tests-only landing is not an ancestor of the implementation base")

    if implementation_range_changed_paths is not None:
        overlap = sorted(set(implementation_range_changed_paths) & set(FROZEN_TEST_PATHS))
        if overlap:
            raise LegibleChronologyError(f"implementation range changes frozen test path(s): {overlap}")

    if test_blob_oid_at_landing is not None and test_blob_oid_at_candidate is not None:
        if test_blob_oid_at_landing != test_blob_oid_at_candidate:
            raise LegibleChronologyError(
                f"frozen test blob drifted: {test_blob_oid_at_landing} != {test_blob_oid_at_candidate}"
            )


# ---------------------------------------------------------------------------
# PR / ancestry evidence (4 nodeids)


def _resolve_pr_head(repo_slug: str, number: int) -> str:
    proc = subprocess.run(
        ["gh", "pr", "view", str(number), "--repo", repo_slug, "--json", "headRefOid"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    if proc.returncode != 0:
        raise LegiblePrEvidenceError(f"cannot resolve PR {repo_slug}#{number} head via gh: {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)["headRefOid"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise LegiblePrEvidenceError(f"malformed gh pr view response for {repo_slug}#{number}") from exc


def collect_pr_evidence(
    repo: Path,
    *,
    repo_slug: str,
    number: int,
    body_shas: Sequence[str] | None = None,
    snapshot_head: str | None = None,
    observed_head: str | None = None,
    state: str | None = None,
    merged_at: str | None = None,
) -> dict[str, Any]:
    repo = Path(repo)

    if body_shas is not None:
        head = _resolve_pr_head(repo_slug, number)
        for sha in body_shas:
            if not _is_ancestor(repo, sha, head):
                raise LegiblePrEvidenceError(f"{sha} is not an ancestor of PR head {head}")

    if snapshot_head is not None and observed_head is not None:
        if snapshot_head != observed_head:
            raise LegiblePrEvidenceError(
                f"head or body changed before merge: snapshot {snapshot_head} != observed {observed_head}"
            )

    if state is not None:
        if state != "MERGED" or not merged_at:
            raise LegiblePrEvidenceError(f"PR is not merged: state={state!r} merged_at={merged_at!r}")

    return {"repo_slug": repo_slug, "number": number}


def collect_target_integration_evidence(
    repo: Path,
    *,
    candidate: str,
    server_merge: str,
    integration_parents: Sequence[str],
) -> dict[str, Any]:
    """LEGIBLE-C5: the target-integration merge ``I`` must have ordered parents
    EXACTLY ``[P, M]`` (phase-authored candidate, then the server merge) --
    never an unbound/partial delta."""
    repo = Path(repo)
    if tuple(integration_parents) != (candidate, server_merge):
        raise LegiblePrEvidenceError(
            f"target-integration parents {tuple(integration_parents)!r} != (candidate, server_merge)"
        )
    return {"candidate": candidate, "server_merge": server_merge}


# ---------------------------------------------------------------------------
# Roadmap-status evidence (used by test_status_evidence_rejects_registry_banner_drift_or_path_set_change)


@dataclass(frozen=True)
class RoadmapStatusEvidenceValidation:
    ok: bool


def collect_roadmap_status(repo: Path, *, required: bool = True) -> dict[str, Any]:
    repo = Path(repo)
    registry_path = repo / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
    try:
        status = roadmap_lint.validate_roadmap_status_coherence(repo, required=required)
    except roadmap_lint.RoadmapStatusError as exc:
        # A present-but-defective registry is always a coherence-class defect
        # from this reducer's point of view; only a changed tracked-path SET
        # gets its own more specific code.
        message = str(exc)
        if "path coverage drift" in message:
            raise LegibleStatusEvidenceError("roadmap_status_path_set_drift", message) from exc
        raise LegibleStatusEvidenceError("roadmap_status_coherence_drift", message) from exc
    if status is None:
        raise LegibleStatusEvidenceError("roadmap_status_registry_absent", f"no registry at {registry_path}")

    registry_bytes = registry_path.read_bytes()
    tracked_paths = sorted(entry["path"] for entry in status["roadmaps"])
    tracked_digest = hashlib.sha256("\n".join(tracked_paths).encode("utf-8")).hexdigest()

    roadmaps: list[dict[str, Any]] = []
    for entry in status["roadmaps"]:
        rel = entry["path"]
        text = (repo / rel).read_text(encoding="utf-8")
        banner_status = roadmap_lint.parse_roadmap_banner_status(text, rel)
        lines = text.splitlines()
        line3 = lines[2] if len(lines) > 2 else ""
        roadmaps.append(
            {
                "path": rel,
                "registry_status": entry["status"],
                "banner_status": banner_status,
                "declaration_line": 3,
                "declaration_sha256": hashlib.sha256(line3.encode("utf-8")).hexdigest(),
            }
        )

    return {
        "registry_path": roadmap_lint.ROADMAP_STATUS_REGISTRY_REL,
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "registry_byte_length": len(registry_bytes),
        "selected_roadmap": status["selected_roadmap"],
        "tracked_path_set_sha256": tracked_digest,
        "roadmaps": roadmaps,
    }


def validate_roadmap_status_evidence(
    repo: Path, record: Mapping[str, Any], *, required: bool = True
) -> RoadmapStatusEvidenceValidation:
    """Re-verify a PREVIOUSLY-COLLECTED record's registry/path-set/declaration
    digests against the repo's CURRENT bytes -- independent of full banner
    re-parsing, so a since-corrupted declaration reports digest drift rather
    than a different (also-true but less specific) parse failure."""
    repo = Path(repo)
    registry_path = repo / record["registry_path"]
    registry_bytes = registry_path.read_bytes()
    if hashlib.sha256(registry_bytes).hexdigest() != record["registry_sha256"]:
        raise LegibleStatusEvidenceError("roadmap_status_registry_drift", "registry bytes drifted since collection")

    recorded_paths = sorted(entry["path"] for entry in record["roadmaps"])
    current_tracked = roadmap_lint._tracked_roadmap_paths(repo)
    if current_tracked != recorded_paths:
        raise LegibleStatusEvidenceError(
            "roadmap_status_path_set_drift", "tracked roadmap path set drifted since collection"
        )

    for entry in record["roadmaps"]:
        rel = entry["path"]
        text = (repo / rel).read_text(encoding="utf-8")
        lines = text.splitlines()
        line3 = lines[2] if len(lines) > 2 else ""
        digest = hashlib.sha256(line3.encode("utf-8")).hexdigest()
        if digest != entry["declaration_sha256"]:
            raise LegibleStatusEvidenceError("roadmap_status_digest_drift", f"{rel}: declaration bytes drifted")

    return RoadmapStatusEvidenceValidation(ok=True)


# ---------------------------------------------------------------------------
# Fresh-process / sidecar (7 nodeids)


@dataclass(frozen=True)
class SidecarRecord:
    schema: str
    path: str
    byte_length: int
    sha256: str
    stage: str
    expected_head: str
    bootstrap_head: str
    process_start_token: str


@dataclass(frozen=True)
class SidecarValidation:
    ok: bool


def bind_verification_sidecar(
    repo: Path,
    *,
    run_dir: Path,
    stage: str,
    expected_head: str,
    bootstrap_head: str,
    process_start_token: str,
    probe_evidence: Mapping[str, Any] | None = None,
) -> SidecarRecord:
    """Stamp the runner-owned sidecar's repo-relative path/length/digest/stage/
    head/token. ``probe_evidence`` exists only to REJECT a self-reported/
    handwritten payload -- real evidence must come from the fixed adapter
    (:func:`run_reviewtruth_fable_probe`), never a caller-supplied argument."""
    if probe_evidence is not None:
        raise LegibleSidecarError(
            "self_reported_probe_evidence",
            "probe evidence must come from the fixed adapter, not a handwritten/self-reported payload",
        )
    repo = Path(repo).resolve()
    run_dir = Path(run_dir)
    sidecar_path = run_dir / _SIDECAR_FILE_NAME
    if sidecar_path.is_symlink():
        raise LegibleSidecarError("sidecar_symlink", f"sidecar must not be a symlink: {sidecar_path}")
    if not sidecar_path.is_file():
        raise LegibleSidecarError("sidecar_missing", f"sidecar not found: {sidecar_path}")
    resolved = sidecar_path.resolve()
    try:
        rel_path = resolved.relative_to(repo).as_posix()
    except ValueError as exc:
        raise LegibleSidecarError("sidecar_path_escape", f"sidecar path escapes repo: {sidecar_path}") from exc
    sidecar_bytes = sidecar_path.read_bytes()
    return SidecarRecord(
        schema=_SIDECAR_RECORD_SCHEMA,
        path=rel_path,
        byte_length=len(sidecar_bytes),
        sha256=hashlib.sha256(sidecar_bytes).hexdigest(),
        stage=stage,
        expected_head=expected_head,
        bootstrap_head=bootstrap_head,
        process_start_token=process_start_token,
    )


def validate_verification_sidecar(repo: Path, *, sidecar: Mapping[str, Any]) -> SidecarValidation:
    repo = Path(repo).resolve()
    rel_path = sidecar["path"]
    full_path = repo / rel_path
    resolved = full_path.resolve()
    try:
        resolved.relative_to(repo)
    except ValueError as exc:
        raise LegibleSidecarError("sidecar_path_escape", f"sidecar path escapes repo: {rel_path}") from exc
    if full_path.is_symlink():
        raise LegibleSidecarError("sidecar_symlink", f"sidecar must not be a symlink: {rel_path}")
    if not full_path.is_file():
        raise LegibleSidecarError("sidecar_missing", f"sidecar file missing: {rel_path}")
    data = full_path.read_bytes()
    if len(data) != sidecar["byte_length"] or hashlib.sha256(data).hexdigest() != sidecar["sha256"]:
        raise LegibleSidecarError("sidecar_digest_drift", f"{rel_path}: bytes do not match recorded length/digest")
    is_operational_evidence = full_path.name == _OPERATIONAL_EVIDENCE_FILE_NAME
    max_bytes = _OPERATIONAL_EVIDENCE_MAX_BYTES if is_operational_evidence else _SIDECAR_PROBE_RECORD_MAX_BYTES
    if len(data) > max_bytes:
        raise LegibleSidecarError("sidecar_oversize", f"{rel_path}: exceeds {max_bytes} bytes")
    if sidecar.get("schema") != _SIDECAR_RECORD_SCHEMA:
        raise LegibleSidecarError("sidecar_schema_mismatch", f"unexpected sidecar schema: {sidecar.get('schema')!r}")
    if sidecar.get("stage") not in {"candidate", "canonical-main", "phase_execute"}:
        raise LegibleSidecarError("sidecar_stage_mismatch", f"unsupported sidecar stage: {sidecar.get('stage')!r}")
    current_head = _rev_parse(repo, "HEAD")
    if sidecar.get("expected_head") != current_head:
        raise LegibleSidecarError(
            "sidecar_head_mismatch",
            f"sidecar expected_head {sidecar.get('expected_head')!r} != repository HEAD {current_head!r}",
        )
    if sidecar.get("bootstrap_head") != sidecar.get("expected_head"):
        raise LegibleSidecarError(
            "sidecar_bootstrap_mismatch",
            "sidecar bootstrap_head does not match expected_head",
        )
    process_start_token = sidecar.get("process_start_token")
    if not isinstance(process_start_token, str) or not process_start_token.strip():
        raise LegibleSidecarError("sidecar_process_token_missing", "sidecar process_start_token is empty")
    if is_operational_evidence:
        validation = validate_operational_evidence(
            repo=repo,
            path=full_path,
            stage=sidecar["stage"],
            expected_head=sidecar["expected_head"],
        )
        if not validation.ok:
            raise LegibleSidecarError(validation.code, validation.finding or validation.code)
    return SidecarValidation(ok=True)


@dataclass(frozen=True)
class FableProbeRecord:
    schema: str
    probe_id: str
    state: str
    model: str
    route: str
    response_sha256: str
    response_byte_length: int
    elapsed_ms: int
    activity_bound_s: int
    hard_bound_s: int
    serialized_bytes: bytes

    def to_json(self) -> str:
        return self.serialized_bytes.decode("utf-8")


_REVIEWTRUTH_PROBE_ARTIFACT = (
    "# reviewtruth_fable_transition capability probe\n\n"
    "This is a bounded LEGIBLE assumption-probe leg (agent-harness#396), not a code "
    "review. No AGREE/DISAGREE verdict is required; the probe only observes whether a "
    "Claude seat driven under the asserted Fable marker produces a native-fill request "
    "or remains unavailable."
)


def _invoke_reviewtruth_fable_adapter(subject: Mapping[str, Any], *, repo: Path | None = None) -> dict[str, Any]:
    """The ONE fixed adapter boundary :func:`run_reviewtruth_fable_probe`
    crosses. Performs exactly the three closed live observations the plan
    requires: a metadata-only GitHub issue snapshot, a metadata-only
    first-party Claude subscription capability probe
    (:func:`panel_invoker._claude_subscription_auth_ok`), and one canonical
    Fable self-PTY leg through the existing bounded
    :func:`panel_invoker._default_spawn` helper -- the same 600-second
    activity bound / 1,800-second hard backstop an ordinary small-artifact
    panel leg gets. No caller-supplied command/route/env/timeout ever reaches
    this boundary; ``subject`` is the closed four-key schema below. Raw auth
    JSON, account/subscription identity, and prompt/transcript/stdout/stderr
    are read only transiently by the panel-invoker leg itself and are never
    returned from here -- the caller (:func:`run_reviewtruth_fable_probe`)
    reads only the typed ``issue``/``route``/``leg``/``bounds``/``response``
    shape produced below."""
    allowed_keys = {"repository", "issue", "model", "source_anchor"}
    if set(subject) - allowed_keys:
        raise LegibleSidecarError(
            "closed_subject_violation",
            f"unexpected reviewtruth_fable_transition subject keys: {set(subject) - allowed_keys}",
        )

    # (1) Metadata-only live GitHub issue snapshot.
    issue_state = None
    issue_reason = None
    try:
        proc = subprocess.run(
            ["gh", "issue", "view", str(subject["issue"]), "--repo", subject["repository"],
             "--json", "state,stateReason"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if proc.returncode == 0:
            payload = json.loads(proc.stdout)
            issue_state = payload.get("state")
            issue_reason = payload.get("stateReason")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        issue_state = None
        issue_reason = None

    # (2) Metadata-only first-party Claude subscription capability probe.
    env = panel_invoker._subscription_env()
    authed, _auth_detail = panel_invoker._claude_subscription_auth_ok(env)

    # (3) Observe the issue's under-Claude-Code behavior through the same
    # adapter with the asserted marker, then prove the external first-party
    # route independently with one real Fable self-PTY leg. These are separate
    # facts in the transition contract: the nested seat may remain unavailable
    # while the subscription route itself succeeds.
    marker_env = dict(env)
    marker_env["CLAUDECODE"] = "1"
    marker_status, marker_text = panel_invoker._default_spawn(
        "claude",
        _REVIEWTRUTH_PROBE_ARTIFACT,
        repo_dir=repo,
        mode="review",
        model=subject["model"],
        env=marker_env,
    )
    started = time.monotonic()
    leg_result = panel_invoker._default_spawn(
        "claude",
        _REVIEWTRUTH_PROBE_ARTIFACT,
        repo_dir=repo,
        mode="review",
        model=subject["model"],
        env=env,
    )
    external_status, leg_text = leg_result[0], leg_result[1]
    elapsed_ms = int((time.monotonic() - started) * 1000)
    final_verdict_token = marker_text if marker_status != "OK" else None

    return {
        "issue": {"number": subject["issue"], "state": issue_state, "stateReason": issue_reason},
        "route": {
            "provider": "first-party-claude",
            "model": subject["model"],
            "capability": "ok" if authed else "unavailable",
        },
        "leg": {
            "status": marker_status,
            "final_verdict_token": final_verdict_token,
            "external_status": external_status,
            "elapsed_ms": elapsed_ms,
        },
        "bounds": {"activity_s": 600, "hard_s": 1800},
        "response": {"text": leg_text if external_status == "OK" else ""},
    }


def _flatten_reviewtruth_observation(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce the fixed adapter's nested raw observation to the flat
    classification vocabulary :func:`roadmap_assumptions._classify_reviewtruth_transition`
    consumes. The ONE seam that reads ``raw``'s nested ``leg``/``route``/``issue``
    keys, so both the sidecar-probe caller (:func:`run_reviewtruth_fable_probe`)
    and the assumption-probe caller (``roadmap_assumptions._observe_reviewtruth_fable_transition``)
    classify identically from the same live observation."""
    leg = raw.get("leg", {}) if isinstance(raw, Mapping) else {}
    route_info = raw.get("route", {}) if isinstance(raw, Mapping) else {}
    issue_info = raw.get("issue", {}) if isinstance(raw, Mapping) else {}

    native_fill_request = bool(leg.get("native_fill_request", False)) if isinstance(leg, Mapping) else False
    seat_result = leg.get("status", "") if isinstance(leg, Mapping) else ""
    final_verdict_token = leg.get("final_verdict_token") if isinstance(leg, Mapping) else None
    seat_result_label = f"{seat_result}/{final_verdict_token}" if final_verdict_token else str(seat_result)

    if isinstance(leg, Mapping) and "external_status" in leg:
        fable_leg_succeeded = leg.get("external_status") == "OK"
    else:
        # Backward-compatible raw adapter observations predate the split
        # external-status field. Their typed UNAVAILABLE seat result means the
        # adapter ran successfully and observed the under-Claude marker.
        fable_leg_succeeded = isinstance(leg, Mapping) and leg.get("status") not in (None, "", "ERROR")

    return {
        "issue_state": issue_info.get("state") if isinstance(issue_info, Mapping) else raw.get("issue_state"),
        "issue_disposition": issue_info.get("stateReason") if isinstance(issue_info, Mapping) else None,
        "native_fill_request": native_fill_request,
        "seat_result": seat_result_label,
        "first_party_route_available": route_info.get("capability") == "ok" if isinstance(route_info, Mapping) else False,
        "fable_leg": "succeeded" if fable_leg_succeeded else "failed",
        "verdict_bound": bool(leg.get("verdict_bound", False)) if isinstance(leg, Mapping) else False,
        "seat_count": leg.get("seat_count", "degraded") if isinstance(leg, Mapping) else "degraded",
    }


def run_reviewtruth_fable_probe(repo: Path, *, repository: str, issue: int, model: str) -> FableProbeRecord:
    """Bounded, redacted capture of the fixed ``reviewtruth_fable_transition``
    adapter's raw observation. Caps retained response metadata at 64 KiB and
    the serialized probe record at 16 KiB; raw auth JSON, account/subscription
    identity, prompt/transcript/stdout/stderr, and provider payloads are never
    retained regardless of what the raw observation carries."""
    repo = Path(repo)
    subject = {"repository": repository, "issue": issue, "model": model, "source_anchor": "agent-harness#396"}
    raw = _invoke_reviewtruth_fable_adapter(subject, repo=repo)

    leg = raw.get("leg", {}) if isinstance(raw, Mapping) else {}
    route_info = raw.get("route", {}) if isinstance(raw, Mapping) else {}
    bounds = raw.get("bounds", {}) if isinstance(raw, Mapping) else {}

    response_source = json.dumps(raw.get("response", {}), sort_keys=True, default=str) if isinstance(raw, Mapping) else ""
    response_bytes = response_source.encode("utf-8")[:_FABLE_PROBE_RESPONSE_MAX_BYTES]

    classification_input = _flatten_reviewtruth_observation(raw)
    from .roadmap_assumptions import _classify_reviewtruth_transition

    state = _classify_reviewtruth_transition(classification_input)
    if state is None:
        raise LegibleSidecarError(
            "unrecognized_transition_state",
            "reviewtruth_fable_transition matched neither the pending nor resolved contract",
        )

    record_fields = {
        "schema": "roadmap_assumption_probe.v1",
        "probe_id": "LEGIBLE-A3-REVIEWTRUTH-TRANSITION",
        "state": state,
        "model": model,
        "route": (route_info.get("provider") if isinstance(route_info, Mapping) else None) or "first-party-claude",
        "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "response_byte_length": len(response_bytes),
        "elapsed_ms": int(leg.get("elapsed_ms", 0)) if isinstance(leg, Mapping) else 0,
        "activity_bound_s": 600,
        "hard_bound_s": 1800,
    }
    serialized = json.dumps(record_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    serialized = serialized[:_SIDECAR_PROBE_RECORD_MAX_BYTES]
    return FableProbeRecord(serialized_bytes=serialized, **record_fields)


# LEGIBLE (v10 SL-2, IF-0-LEGIBLE-2): the closed extension namespace this
# module owns inside ``verification_evidence.v3.extensions``.
EXTENSION_NAMESPACE = "phase_loop_runtime.legible_evidence"


def capture_fresh_process_verification_sidecar(
    repo: Path,
    *,
    run_dir: Path,
    stage: str,
    expected_head: str,
    process_start_token: str,
    repository: str = "Consiliency/agent-harness",
    issue: int = 396,
    model: str = panel_invoker.DEFAULT_LEG_MODELS["claude"],  # model-id-source: SSOT constant reference
) -> SidecarRecord:
    """Runner-owned (never executor-owned) capture: runs the fixed
    ``reviewtruth_fable_transition`` probe adapter through
    :func:`run_reviewtruth_fable_probe`, writes its already-bounded/redacted
    record as the run-owned sidecar file, and stamps the pointer
    :class:`SidecarRecord` that :func:`bind_verification_sidecar` computes
    from those exact bytes. Called only by the fresh phase-loop runner after
    ``run_verification`` returns and before it seals ``verification.json`` --
    never by an executor, and never accepting caller-supplied probe evidence
    (probe evidence always comes from the fixed adapter, see
    ``bind_verification_sidecar``'s own ``probe_evidence`` rejection)."""
    repo = Path(repo)
    run_dir = Path(run_dir)
    probe = run_reviewtruth_fable_probe(repo, repository=repository, issue=issue, model=model)
    sidecar_path = run_dir / _SIDECAR_FILE_NAME
    sidecar_path.write_bytes(probe.serialized_bytes)
    return bind_verification_sidecar(
        repo,
        run_dir=run_dir,
        stage=stage,
        expected_head=expected_head,
        bootstrap_head=expected_head,
        process_start_token=process_start_token,
    )


# ---------------------------------------------------------------------------
# Process bootstrap and final operational evidence


def _operational_evidence_digest(payload: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "seal_sha256"}
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_commit(repo: Path, value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}", value) is not None
        and _rev_parse(repo, f"{value}^{{commit}}") == value
    )


def _commit_parents(repo: Path, commit: str) -> list[str] | None:
    proc = _git_ok(repo, "rev-list", "--parents", "-n", "1", commit)
    if proc.returncode != 0:
        return None
    fields = proc.stdout.strip().split()
    return fields[1:] if fields and fields[0] == commit else None


def _bound_repo_file(repo: Path, path_value: Any, sha256_value: Any, expected_head: str) -> bool:
    if not isinstance(path_value, str) or not path_value or not _is_sha256(sha256_value):
        return False
    path = repo / path_value
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(repo)
        data = path.read_bytes()
    except (OSError, ValueError):
        return False
    if path.is_symlink() or not path.is_file() or hashlib.sha256(data).hexdigest() != sha256_value:
        return False
    committed = subprocess.run(
        ["git", "-C", str(repo), "show", f"{expected_head}:{path_value}"],
        capture_output=True,
        check=False,
    )
    return committed.returncode == 0 and committed.stdout == data


def _validate_operational_sections(
    repo: Path, sections: Mapping[str, Any], *, stage: str, expected_head: str
) -> str | None:
    if set(sections) != _OPERATIONAL_EVIDENCE_SECTIONS:
        return "section inventory mismatch"
    for name, required_fields in _OPERATIONAL_SECTION_FIELDS.items():
        section = sections.get(name)
        if not isinstance(section, Mapping) or not required_fields.issubset(section):
            present_fields = set(section) if isinstance(section, Mapping) else set()
            return f"{name}: missing required fields {sorted(required_fields - present_fields)}"

    artifact_records = sections["artifacts"]["records"]
    if not isinstance(artifact_records, list) or not artifact_records:
        return "artifacts: records are absent"
    artifact_data: dict[str, bytes] = {}
    for record in artifact_records:
        if not isinstance(record, Mapping) or not {"path", "byte_length", "sha256"}.issubset(record):
            return "artifacts: malformed record"
        rel = record["path"]
        if not isinstance(rel, str) or not rel or rel in artifact_data:
            return "artifacts: malformed or duplicate path"
        artifact_path = repo / rel
        try:
            artifact_path.resolve(strict=True).relative_to(repo)
        except (OSError, ValueError):
            return f"artifacts: path escapes or is missing: {rel}"
        if artifact_path.is_symlink() or not artifact_path.is_file():
            return f"artifacts: path is not a regular file: {rel}"
        data = artifact_path.read_bytes()
        if record["byte_length"] != len(data) or record["sha256"] != hashlib.sha256(data).hexdigest():
            return f"artifacts: digest drift: {rel}"
        artifact_data[rel] = data

    roadmap_status = sections["roadmap_status"]
    roadmap_records = roadmap_status["roadmaps"]
    if (
        roadmap_status["registry_path"] != roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
        or not isinstance(roadmap_status["registry_byte_length"], int)
        or roadmap_status["registry_byte_length"] < 0
        or not isinstance(roadmap_status["selected_roadmap"], str)
        or not _is_sha256(roadmap_status["tracked_path_set_sha256"])
        or not isinstance(roadmap_records, list)
        or not roadmap_records
        or any(
            not isinstance(record, Mapping)
            or not {
                "path",
                "registry_status",
                "banner_status",
                "declaration_line",
                "declaration_sha256",
            }.issubset(record)
            for record in roadmap_records
        )
    ):
        return "roadmap_status: malformed registry evidence"
    registry_path = repo / roadmap_status["registry_path"]
    try:
        registry_bytes = registry_path.read_bytes()
        current_status = roadmap_lint.validate_roadmap_status_coherence(repo, required=True)
        validate_roadmap_status_evidence(repo, roadmap_status, required=True)
    except (OSError, roadmap_lint.RoadmapStatusError, LegibleStatusEvidenceError, KeyError, TypeError):
        return "roadmap_status: registry or banner coherence failed"
    if (
        current_status is None
        or len(registry_bytes) != roadmap_status["registry_byte_length"]
        or hashlib.sha256(registry_bytes).hexdigest() != roadmap_status["registry_sha256"]
        or current_status["selected_roadmap"] != roadmap_status["selected_roadmap"]
    ):
        return "roadmap_status: registry identity drift"
    recorded_paths = [record["path"] for record in roadmap_records]
    if (
        recorded_paths != sorted(set(recorded_paths))
        or hashlib.sha256("\n".join(recorded_paths).encode()).hexdigest()
        != roadmap_status["tracked_path_set_sha256"]
    ):
        return "roadmap_status: tracked path-set identity drift"
    status_by_path = {entry["path"]: entry["status"] for entry in current_status["roadmaps"]}
    if any(
        status_by_path.get(record["path"]) != record["registry_status"]
        or record["registry_status"] != record["banner_status"]
        for record in roadmap_records
    ):
        return "roadmap_status: recorded status disagrees with the coherent registry"

    chronology = sections["chronology"]
    chronology_commits = (
        "tests_landing",
        "implementation_base",
        "phase_candidate",
        "pr_head",
        "server_merge",
        "candidate_head",
    )
    if any(not _is_commit(repo, chronology[field]) for field in chronology_commits):
        return "chronology: unresolved commit identity"
    if (
        not _bound_repo_file(repo, chronology["plan_path"], chronology["plan_sha256"], expected_head)
        or not _bound_repo_file(repo, chronology["roadmap_path"], chronology["roadmap_sha256"], expected_head)
    ):
        return "chronology: plan or roadmap bytes are not bound to expected HEAD"
    if (
        not _is_ancestor(repo, chronology["tests_landing"], chronology["implementation_base"])
        or not _is_ancestor(repo, chronology["implementation_base"], chronology["phase_candidate"])
        or not _is_ancestor(repo, chronology["phase_candidate"], chronology["candidate_head"])
        or not _is_ancestor(repo, chronology["pr_head"], chronology["server_merge"])
        or not _is_ancestor(repo, chronology["server_merge"], chronology["candidate_head"])
        or (stage == "candidate" and chronology["candidate_head"] != expected_head)
        or (stage == "canonical-main" and not _is_ancestor(repo, chronology["candidate_head"], expected_head))
    ):
        return "chronology: required ancestry is absent"

    attestations = sections["process_attestations"]
    builder = attestations["builder"]
    attester = attestations["attester"]
    if not isinstance(builder, Mapping) or not isinstance(attester, Mapping):
        return "process_attestations: builder and attester must be records"
    builder_token = builder.get("process_start_token")
    attester_token = attester.get("process_start_token")
    cli_path = Path(str(attester.get("cli_path", "")))
    expected_cli_path = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "cli.py"
    try:
        cli_bytes = cli_path.read_bytes()
        cli_is_bound = (
            not cli_path.is_symlink()
            and cli_path.resolve() == expected_cli_path.resolve()
            and hashlib.sha256(cli_bytes).hexdigest() == attester.get("cli_sha256")
        )
    except OSError:
        cli_is_bound = False
    if (
        not builder.get("run_id")
        or not isinstance(builder_token, str)
        or not builder_token
        or not isinstance(attester_token, str)
        or not attester_token
        or builder_token == attester_token
        or attester.get("head") != expected_head
        or attester.get("bootstrap_head") != expected_head
        or Path(str(attester.get("repo_realpath", ""))).resolve() != repo
        or not _is_sha256(attester.get("cli_sha256"))
        or not cli_is_bound
        or not attester.get("python_executable")
    ):
        return "process_attestations: malformed or unbound process identity"

    test_execution = sections["test_execution"]
    default = test_execution["default"]
    forced_red = test_execution["forced_red"]
    final = test_execution["final"]
    if (
        test_execution["nodeid_count"] != 84
        or not _is_sha256(test_execution["nodeid_digest"])
        or not all(isinstance(record, Mapping) for record in (default, forced_red, final))
        or {key: default.get(key) for key in ("passed", "skipped", "failed", "errors")}
        != {"passed": 0, "skipped": 84, "failed": 0, "errors": 0}
        or {key: forced_red.get(key) for key in ("passed", "skipped", "failed", "errors")}
        != {"passed": 0, "skipped": 0, "failed": 84, "errors": 0}
        or {key: final.get(key) for key in ("passed", "skipped", "failed", "errors")}
        != {"passed": 84, "skipped": 0, "failed": 0, "errors": 0}
    ):
        return "test_execution: frozen default/RED/final inventory is invalid"
    try:
        expected_nodeids = _load_frozen_nodeids(repo)
    except (OSError, AttributeError, ImportError, LegibleTestExecutionError) as exc:
        return f"test_execution: cannot load frozen inventory: {exc}"
    expected_digest = hashlib.sha256("\n".join(expected_nodeids).encode()).hexdigest()
    if len(expected_nodeids) != 84 or test_execution["nodeid_digest"] != expected_digest:
        return "test_execution: nodeid digest is not bound to the frozen inventory"
    for mode, record in (("default", default), ("forced_red", forced_red), ("final", final)):
        junit_rel = record.get("junit_path")
        if not isinstance(junit_rel, str) or junit_rel not in artifact_data:
            return f"test_execution: {mode} JUnit is not in the artifact inventory"
        try:
            observed = collect_test_execution_evidence(
                repo,
                junit_path=repo / junit_rel,
                expected_total=84,
                mode=mode,
            )
        except (ET.ParseError, LegibleTestExecutionError, OSError) as exc:
            return f"test_execution: {mode} JUnit failed semantic validation: {exc}"
        if {
            "passed": observed.passed,
            "skipped": observed.skipped,
            "failed": observed.failed,
            "errors": observed.errors,
        } != {key: record.get(key) for key in ("passed", "skipped", "failed", "errors")}:
            return f"test_execution: {mode} counts disagree with JUnit"

    pull_request = sections["pull_request"]
    snapshot_rel = pull_request["snapshot_path"]
    snapshot_bytes = artifact_data.get(snapshot_rel) if isinstance(snapshot_rel, str) else None
    try:
        snapshot = json.loads(snapshot_bytes) if snapshot_bytes is not None else None
    except json.JSONDecodeError:
        snapshot = None
    changed_proc = _git_ok(repo, "diff", "--name-only", pull_request["base"], pull_request["head"])
    actual_changed_paths = sorted(changed_proc.stdout.splitlines()) if changed_proc.returncode == 0 else None
    if (
        pull_request["repository"] != "Consiliency/agent-harness"
        or pull_request["number"] != 347
        or pull_request["state"] != "MERGED"
        or not _is_commit(repo, pull_request["base"])
        or not _is_commit(repo, pull_request["head"])
        or not _is_commit(repo, pull_request["merge_commit"])
        or pull_request["parents"] != [pull_request["base"], pull_request["head"]]
        or _commit_parents(repo, pull_request["merge_commit"]) != pull_request["parents"]
        or pull_request["base"] != chronology["implementation_base"]
        or pull_request["head"] != chronology["pr_head"]
        or pull_request["merge_commit"] != chronology["server_merge"]
        or snapshot_bytes is None
        or hashlib.sha256(snapshot_bytes).hexdigest() != pull_request["snapshot_sha256"]
        or not isinstance(snapshot, Mapping)
        or snapshot.get("base") != pull_request["base"]
        or snapshot.get("head") != pull_request["head"]
        or snapshot.get("merge_commit") != pull_request["merge_commit"]
        or snapshot.get("head_tree") != _rev_parse(repo, f"{pull_request['head']}^{{tree}}")
        or snapshot.get("merge_tree") != _rev_parse(repo, f"{pull_request['merge_commit']}^{{tree}}")
        or snapshot.get("changed_paths") != pull_request["changed_paths"]
        or pull_request["changed_paths"] != actual_changed_paths
        or pull_request["changed_paths"] != [_FROZEN_AGENT_HARNESS_347_PATH]
        or not isinstance(snapshot.get("body"), str)
        or hashlib.sha256(snapshot["body"].encode()).hexdigest() != pull_request["body_sha256"]
        or not isinstance(snapshot.get("checks"), list)
        or not snapshot["checks"]
        or any(check != "SUCCESS" for check in snapshot["checks"])
    ):
        return "pull_request: exact merged agent-harness#347 identity is absent"

    integration = sections["target_integration"]
    integration_commits = (integration["candidate"], integration["server_merge"], integration["integration"])
    if (
        any(not _is_commit(repo, value) for value in integration_commits)
        or integration["parents"] != [integration["candidate"], integration["server_merge"]]
        or _commit_parents(repo, integration["integration"]) != integration["parents"]
        or integration["candidate"] != chronology["phase_candidate"]
        or integration["server_merge"] != chronology["server_merge"]
        or integration["integration"] != chronology["candidate_head"]
        or (stage == "candidate" and integration["integration"] != expected_head)
        or (stage == "canonical-main" and not _is_ancestor(repo, integration["integration"], expected_head))
    ):
        return "target_integration: commit or ordered-parent binding is invalid"

    assumption_probes = sections["assumption_probes"]
    probe_records = assumption_probes["records"]
    if (
        assumption_probes["execution_head"] != expected_head
        or not isinstance(probe_records, list)
        or not probe_records
        or any(
            not isinstance(record, Mapping)
            or record.get("schema") != "roadmap_assumption_probe.v1"
            or not record.get("probe_id")
            or record.get("state") not in {"pending", "resolved"}
            or not isinstance(record.get("response_path"), str)
            or not _is_sha256(record.get("response_sha256"))
            or not isinstance(record.get("response_byte_length"), int)
            or record["response_byte_length"] < 0
            for record in probe_records
        )
        or len({record["probe_id"] for record in probe_records}) != len(probe_records)
        or "LEGIBLE-A3-REVIEWTRUTH-TRANSITION" not in {record["probe_id"] for record in probe_records}
    ):
        return "assumption_probes: execution-head-bound records are absent"
    for record in probe_records:
        response_bytes = artifact_data.get(record["response_path"])
        if (
            response_bytes is None
            or len(response_bytes) != record["response_byte_length"]
            or hashlib.sha256(response_bytes).hexdigest() != record["response_sha256"]
        ):
            return f"assumption_probes: response payload drift: {record['probe_id']}"
        try:
            response = json.loads(response_bytes)
        except json.JSONDecodeError:
            return f"assumption_probes: malformed response payload: {record['probe_id']}"
        if not isinstance(response, Mapping) or response.get("state") != record["state"]:
            return f"assumption_probes: response state drift: {record['probe_id']}"

    artifact_paths = set(artifact_data)
    cli_rel = Path(str(attester["cli_path"])).resolve().relative_to(repo).as_posix()
    required_artifacts = {
        roadmap_status["registry_path"],
        chronology["plan_path"],
        chronology["roadmap_path"],
        cli_rel,
    }
    if (
        not required_artifacts.issubset(artifact_paths)
        or not any(path.endswith(".junit.xml") for path in artifact_paths)
        or not any("panel" in Path(path).name and path.endswith(".json") for path in artifact_paths)
    ):
        return "artifacts: required registry/source/JUnit/panel inventory is incomplete"
    panel_paths = [path for path in artifact_paths if "panel" in Path(path).name and path.endswith(".json")]
    if len(panel_paths) != 1:
        return "artifacts: implementation panel inventory is ambiguous"
    try:
        panel = json.loads(artifact_data[panel_paths[0]])
    except json.JSONDecodeError:
        return "artifacts: implementation panel is malformed"
    required_models = {"claude-fable-5", "gemini-3.6-flash", "gpt-5.6-sol", "grok-4.5"}
    if (
        not isinstance(panel, Mapping)
        or panel.get("head") != expected_head
        or not isinstance(panel.get("verdicts"), Mapping)
        or set(panel["verdicts"]) != required_models
        or any(verdict != "AGREE" for verdict in panel["verdicts"].values())
    ):
        return "artifacts: implementation panel is not exact-head unanimous"
    return None


def _assemble_operational_evidence(
    *,
    repo: Path,
    run_dir: Path,
    stage: str,
    expected_head: str,
    sections: Mapping[str, Mapping[str, Any]],
) -> Path:
    """Assemble the closed final envelope from runner-collected section records.

    This internal codec does not collect or authorize evidence. C4/C5/C7 supply
    records produced by the fixed collectors, then validate the sealed result
    before it can satisfy an execution criterion.
    """
    repo = Path(repo).resolve()
    run_dir = Path(run_dir).resolve()
    try:
        run_dir.relative_to(repo / ".phase-loop" / "runs")
    except ValueError as exc:
        raise LegibleProcessBootstrapError(f"operational evidence run directory escapes runner root: {run_dir}") from exc
    if stage not in {"candidate", "canonical-main"}:
        raise LegibleProcessBootstrapError(f"unsupported attestation stage: {stage!r}")
    if set(sections) != _OPERATIONAL_EVIDENCE_SECTIONS:
        raise LegibleProcessBootstrapError(
            f"operational evidence sections {sorted(sections)} != {sorted(_OPERATIONAL_EVIDENCE_SECTIONS)}"
        )
    if any(not isinstance(value, Mapping) or not value for value in sections.values()):
        raise LegibleProcessBootstrapError("every operational evidence section must be a nonempty mapping")
    payload: dict[str, Any] = {
        "schema": _OPERATIONAL_EVIDENCE_SCHEMA,
        "stage": stage,
        "expected_head": expected_head,
        "sections": {key: dict(sections[key]) for key in sorted(sections)},
    }
    payload["seal_sha256"] = _operational_evidence_digest(payload)
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = run_dir / _OPERATIONAL_EVIDENCE_FILE_NAME
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=run_dir, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(output_path)
    return output_path


def validate_operational_evidence(
    *, repo: Path, path: Path, stage: str, expected_head: str
) -> OperationalEvidenceValidation:
    repo = Path(repo).resolve()
    path = Path(path)
    if path.is_symlink():
        return OperationalEvidenceValidation(False, "operational_evidence_symlink", str(path))
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(repo / ".phase-loop" / "runs")
    except (OSError, ValueError) as exc:
        return OperationalEvidenceValidation(False, "operational_evidence_path", str(exc))
    if resolved.name != _OPERATIONAL_EVIDENCE_FILE_NAME:
        return OperationalEvidenceValidation(False, "operational_evidence_path", str(resolved))
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return OperationalEvidenceValidation(False, "operational_evidence_malformed", str(exc))
    if not isinstance(payload, dict) or set(payload) != {
        "schema", "stage", "expected_head", "sections", "seal_sha256"
    }:
        return OperationalEvidenceValidation(False, "operational_evidence_malformed", "closed field inventory mismatch")
    if payload.get("schema") != _OPERATIONAL_EVIDENCE_SCHEMA:
        return OperationalEvidenceValidation(False, "operational_evidence_schema", str(payload.get("schema")))
    if payload.get("stage") != stage or payload.get("expected_head") != expected_head:
        return OperationalEvidenceValidation(False, "operational_evidence_identity", "stage/head mismatch")
    sections = payload.get("sections")
    if not isinstance(sections, dict) or set(sections) != _OPERATIONAL_EVIDENCE_SECTIONS:
        return OperationalEvidenceValidation(False, "operational_evidence_sections", "section inventory mismatch")
    if any(not isinstance(value, dict) or not value for value in sections.values()):
        return OperationalEvidenceValidation(False, "operational_evidence_sections", "empty or malformed section")
    if payload.get("seal_sha256") != _operational_evidence_digest(payload):
        return OperationalEvidenceValidation(False, "operational_evidence_seal_mismatch", "payload digest drift")
    if _rev_parse(repo, "HEAD") != expected_head:
        return OperationalEvidenceValidation(False, "operational_evidence_head_mismatch", "repository HEAD drift")
    section_finding = _validate_operational_sections(repo, sections, stage=stage, expected_head=expected_head)
    if section_finding is not None:
        return OperationalEvidenceValidation(False, "operational_evidence_sections", section_finding)
    return OperationalEvidenceValidation(True)


def finalize_operational_attestation(
    *,
    repo: Path,
    run_dir: Path,
    artifact_path: Path,
    stage: str,
    expected_head: str,
    bootstrap_head: str,
    process_start_token: str,
    sections: Mapping[str, Mapping[str, Any]],
) -> Path:
    """Seal, validate, and bind the C5/C7 aggregate to verification.json."""
    repo = Path(repo).resolve()
    run_dir = Path(run_dir).resolve()
    artifact_path = Path(artifact_path).resolve()
    if artifact_path.parent != run_dir:
        raise LegibleProcessBootstrapError("verification artifact must belong to the attestation run directory")
    if bootstrap_head != expected_head:
        raise LegibleProcessBootstrapError("attestation bootstrap head does not match expected head")
    if not process_start_token.strip():
        raise LegibleProcessBootstrapError("attestation process start token is empty")
    output_path = _assemble_operational_evidence(
        repo=repo,
        run_dir=run_dir,
        stage=stage,
        expected_head=expected_head,
        sections=sections,
    )
    validation = validate_operational_evidence(
        repo=repo,
        path=output_path,
        stage=stage,
        expected_head=expected_head,
    )
    if not validation.ok:
        raise LegibleProcessBootstrapError(
            f"operational evidence validation failed [{validation.code}]: {validation.finding}"
        )
    evidence_bytes = output_path.read_bytes()
    sidecar = SidecarRecord(
        schema=_SIDECAR_RECORD_SCHEMA,
        path=output_path.relative_to(repo).as_posix(),
        byte_length=len(evidence_bytes),
        sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        stage=stage,
        expected_head=expected_head,
        bootstrap_head=bootstrap_head,
        process_start_token=process_start_token,
    )
    from .verification_evidence import _bind_sidecar_extension

    _bind_sidecar_extension(
        artifact_path,
        namespace=EXTENSION_NAMESPACE,
        record=sidecar.__dict__,
    )
    return output_path


def attest(*, repo: Path, stage: str, expected_head: str, builder_run_id: str, candidate_head: str | None = None) -> dict[str, Any]:
    """Runner-owned attestation bootstrap: resolves the clean repo/worktree
    and exact HEAD, and requires it to equal ``expected_head`` before
    importing any phase-owned attestation helper. This is only the LOCAL
    bootstrap-identity gate; the full candidate/canonical-main attestation
    chain (broad suite, implementation panel, PR/merge evidence) is a
    coordinator-run operational process outside this function's scope."""
    repo = Path(repo).resolve()
    if stage not in {"candidate", "canonical-main"}:
        raise LegibleProcessBootstrapError(f"unsupported attestation stage: {stage!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise LegibleProcessBootstrapError(f"expected head is not a lowercase 40-hex commit: {expected_head!r}")
    if not builder_run_id.strip():
        raise LegibleProcessBootstrapError("builder run identity is empty")
    if stage == "canonical-main" and not candidate_head:
        raise LegibleProcessBootstrapError("canonical-main attestation requires candidate_head")
    if candidate_head is not None:
        if not re.fullmatch(r"[0-9a-f]{40}", candidate_head):
            raise LegibleProcessBootstrapError(
                f"candidate head is not a lowercase 40-hex commit: {candidate_head!r}"
            )
        resolved_candidate = _rev_parse(repo, f"{candidate_head}^{{commit}}")
        if resolved_candidate != candidate_head:
            raise LegibleProcessBootstrapError(f"candidate head does not resolve to a commit: {candidate_head!r}")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0 or status.stdout:
        raise LegibleProcessBootstrapError(f"attestation requires a clean git worktree: {repo}")
    actual_head = _rev_parse(repo, "HEAD")
    if actual_head is None or actual_head != expected_head:
        raise LegibleProcessBootstrapError(
            f"expected HEAD {expected_head!r}, found {actual_head!r} in {repo} (stage={stage!r}, "
            f"builder_run_id={builder_run_id!r})"
        )
    if candidate_head is not None and not _is_ancestor(repo, candidate_head, actual_head):
        raise LegibleProcessBootstrapError(
            f"candidate head {candidate_head!r} is not an ancestor of {actual_head!r}"
        )
    return {
        "repo": str(repo),
        "stage": stage,
        "status": "awaiting_phase_closeout",
        "head": actual_head,
        "builder_run_id": builder_run_id,
        "candidate_head": candidate_head,
        "process_id": os.getpid(),
        "process_start_token": secrets.token_hex(32),
    }


# ---------------------------------------------------------------------------
# Frozen 84-nodeid inventory + JUnit reduction


def _load_frozen_nodeids(repo: Path) -> tuple[str, ...]:
    """The exact frozen 84-nodeid union, read from the two frozen test files'
    own ``LEGIBLE_EXPECTED_NODEIDS_V1`` literal tuples -- never re-derived
    from a live pytest collection or hand-typed placeholders."""
    repo = Path(repo)
    nodeids: set[str] = set()
    for rel in FROZEN_TEST_PATHS:
        path = repo / rel
        spec = importlib.util.spec_from_file_location(f"_legible_frozen_{Path(rel).stem}", path)
        if spec is None or spec.loader is None:
            raise LegibleTestExecutionError(f"cannot load frozen test module: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(path.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            if str(path.parent) in sys.path:
                sys.path.remove(str(path.parent))
        nodeids.update(module.LEGIBLE_EXPECTED_NODEIDS_V1)
    return tuple(sorted(nodeids))


@dataclass(frozen=True)
class TestExecutionEvidence:
    nodeids: tuple[str, ...]
    passed: int
    skipped: int
    failed: int
    errors: int
    skip_reasons: tuple[str, ...]
    asserted_mutation_ids: tuple[str, ...] = ()


def _parse_junit(junit_path: Path) -> dict[str, tuple[str, str]]:
    observed: dict[str, tuple[str, str]] = {}
    root = ET.parse(junit_path).getroot()
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        nodeid = f"{classname.replace('.', '/')}.py::{name}"
        children = list(case)
        if not children:
            status, message = "passed", ""
        else:
            child = children[0]
            status = child.tag
            message = child.get("message", "")
        observed[nodeid] = (status, message)
    return observed


def collect_test_execution_evidence(
    repo: Path, *, junit_path: Path, expected_total: int, mode: str = "default"
) -> TestExecutionEvidence:
    repo = Path(repo)
    expected_nodeids = _load_frozen_nodeids(repo)
    if len(expected_nodeids) != expected_total:
        raise LegibleTestExecutionError(
            f"frozen nodeid count {len(expected_nodeids)} != expected_total {expected_total}"
        )
    observed = _parse_junit(Path(junit_path))
    observed_set = set(observed)
    expected_set = set(expected_nodeids)
    if observed_set != expected_set:
        missing = sorted(expected_set - observed_set)
        extra = sorted(observed_set - expected_set)
        raise LegibleTestExecutionError(f"nodeid set mismatch: missing={missing} extra={extra}")

    required_status = {"default": "skipped", "forced_red": "failure", "final": "passed"}.get(mode)
    if required_status is None:
        raise LegibleTestExecutionError(f"unsupported mode: {mode!r}")

    passed = skipped = failed = errors = 0
    skip_reasons: set[str] = set()
    mutation_ids: list[str] = []
    for nodeid in expected_nodeids:
        status, message = observed[nodeid]
        if status != required_status:
            raise LegibleTestExecutionError(f"{nodeid}: expected status {required_status!r}, found {status!r}")
        if status == "passed":
            passed += 1
        elif status == "skipped":
            skipped += 1
            skip_reasons.add(message)
        elif status == "failure":
            failed += 1
            if not message.startswith("LEGIBLE_RED::"):
                raise LegibleTestExecutionError(f"{nodeid}: failure message missing LEGIBLE_RED:: prefix: {message!r}")
            mutation_id = message.split(":", 2)[0] + "::" + message.split("::", 1)[1].split(":", 1)[0]
            mutation_ids.append(mutation_id)
        else:  # pragma: no cover - only reachable via a genuinely new status kind
            errors += 1

    if mode == "forced_red" and len(set(mutation_ids)) != len(mutation_ids):
        raise LegibleTestExecutionError("forced-RED mutation ids are not one-to-one over the frozen inventory")

    return TestExecutionEvidence(
        nodeids=expected_nodeids,
        passed=passed,
        skipped=skipped,
        failed=failed,
        errors=errors,
        skip_reasons=tuple(sorted(skip_reasons)),
        asserted_mutation_ids=tuple(mutation_ids),
    )


# ---------------------------------------------------------------------------
# CLI (staged, local-only verification; the full candidate/canonical-main
# attestation chain is coordinator-run and out of this module's scope)


def _cmd_verify(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if args.stage not in {"candidate", "canonical-main"}:
        print(f"legible_evidence verify: FAIL [unsupported_stage] {args.stage}", file=sys.stderr)
        return 1
    expected_head = _rev_parse(repo, args.head)
    actual_head = _rev_parse(repo, "HEAD")
    if expected_head is None:
        print(f"legible_evidence verify: FAIL [unresolved_head] {args.head}", file=sys.stderr)
        return 1
    if actual_head != expected_head:
        print(
            f"legible_evidence verify: FAIL [head_mismatch] expected={expected_head} actual={actual_head}",
            file=sys.stderr,
        )
        return 1
    try:
        record = collect_roadmap_status(repo, required=True)
        validate_roadmap_status_evidence(repo, record, required=True)
    except LegibleStatusEvidenceError as exc:
        print(f"legible_evidence verify: FAIL [{exc.code}] {exc}", file=sys.stderr)
        return 1
    evidence_arg = getattr(args, "evidence", None)
    candidates = (
        [Path(evidence_arg)]
        if evidence_arg
        else sorted((repo / ".phase-loop" / "runs").glob(f"*/{_OPERATIONAL_EVIDENCE_FILE_NAME}"))
    )
    valid_paths: list[Path] = []
    findings: list[str] = []
    for candidate in candidates:
        validation = validate_operational_evidence(
            repo=repo,
            path=candidate,
            stage=args.stage,
            expected_head=expected_head,
        )
        if validation.ok:
            valid_paths.append(candidate)
        else:
            findings.append(f"{candidate}: [{validation.code}] {validation.finding}")
    if len(valid_paths) != 1:
        detail = "; ".join(findings) if findings else "no sealed operational aggregate found"
        print(
            f"legible_evidence verify: FAIL [operational_evidence] expected one valid aggregate, "
            f"found {len(valid_paths)}: {detail}",
            file=sys.stderr,
        )
        return 1
    print(
        f"legible_evidence verify: OK (stage={args.stage}, head={expected_head}, "
        f"evidence={valid_paths[0]})"
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="phase_loop_runtime.legible_evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--repo", default=".")
    verify.add_argument("--stage", default="candidate")
    verify.add_argument("--head", default="HEAD")
    verify.add_argument("--evidence")
    args = parser.parse_args(argv)
    if args.command == "verify":
        return _cmd_verify(args)
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
