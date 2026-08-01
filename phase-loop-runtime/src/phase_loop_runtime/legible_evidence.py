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
import subprocess
import sys
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
    if not full_path.is_file():
        raise LegibleSidecarError("sidecar_missing", f"sidecar file missing: {rel_path}")
    data = full_path.read_bytes()
    if len(data) != sidecar["byte_length"] or hashlib.sha256(data).hexdigest() != sidecar["sha256"]:
        raise LegibleSidecarError("sidecar_digest_drift", f"{rel_path}: bytes do not match recorded length/digest")
    if len(data) > _SIDECAR_PROBE_RECORD_MAX_BYTES:
        raise LegibleSidecarError("sidecar_oversize", f"{rel_path}: exceeds {_SIDECAR_PROBE_RECORD_MAX_BYTES} bytes")
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
        "verdict_bound": False,
        "seat_count": "degraded",
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
# Process bootstrap (attest) — activation/JUnit/digest group


def attest(*, repo: Path, stage: str, expected_head: str, builder_run_id: str, candidate_head: str | None = None) -> dict[str, Any]:
    """Runner-owned attestation bootstrap: resolves the clean repo/worktree
    and exact HEAD, and requires it to equal ``expected_head`` before
    importing any phase-owned attestation helper. This is only the LOCAL
    bootstrap-identity gate; the full candidate/canonical-main attestation
    chain (broad suite, implementation panel, PR/merge evidence) is a
    coordinator-run operational process outside this function's scope."""
    repo = Path(repo).resolve()
    actual_head = _rev_parse(repo, "HEAD")
    if actual_head is None or actual_head != expected_head:
        raise LegibleProcessBootstrapError(
            f"expected HEAD {expected_head!r}, found {actual_head!r} in {repo} (stage={stage!r}, "
            f"builder_run_id={builder_run_id!r})"
        )
    return {"repo": str(repo), "stage": stage, "head": actual_head, "builder_run_id": builder_run_id}


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
    print(f"legible_evidence verify: roadmap_status OK (stage={args.stage}, head={expected_head})")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="phase_loop_runtime.legible_evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--repo", default=".")
    verify.add_argument("--stage", default="candidate")
    verify.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    if args.command == "verify":
        return _cmd_verify(args)
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
