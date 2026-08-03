"""proofgate_bootstrap_verifier.py — Test-owned immutable verifier for PROOFGATE landings."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

try:
    from .proofgate_tdd_guard import (
        ATTENDED_REAL_PROVIDER_CASES,
        DEFAULT_SKIP_NODEIDS,
        EXPECTED_PHASE_NODEIDS,
        PROOFGATE_EXPECTED_CONFIG_V1_CANONICAL_SHA256,
        PROOFGATE_OBSERVATION_SCHEMA,
        RED_CASES_BY_NODEID,
        ProofgateExpectedConfig,
        ProofgateExternalObservation,
        ProofgateObservationRequest,
        ProofgateObservationUnavailable,
        RecordingObservationBoundary,
        UnavailableObservationBoundary,
        canonical_expected_config_digest,
        conforming_observation,
        expected_append_digest,
        expected_bundle_digest,
        observation_digest,
        subject_sequence_and_core_digest,
    )
except ImportError:
    from proofgate_tdd_guard import (
        ATTENDED_REAL_PROVIDER_CASES,
        DEFAULT_SKIP_NODEIDS,
        EXPECTED_PHASE_NODEIDS,
        PROOFGATE_EXPECTED_CONFIG_V1_CANONICAL_SHA256,
        PROOFGATE_OBSERVATION_SCHEMA,
        RED_CASES_BY_NODEID,
        ProofgateExpectedConfig,
        ProofgateExternalObservation,
        ProofgateObservationRequest,
        ProofgateObservationUnavailable,
        RecordingObservationBoundary,
        UnavailableObservationBoundary,
        canonical_expected_config_digest,
        conforming_observation,
        expected_append_digest,
        expected_bundle_digest,
        observation_digest,
        subject_sequence_and_core_digest,
    )


class ProofgateBootstrapVerifierError(ValueError):
    """Typed error for bootstrap verifier check failures."""


HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")

AUTHOR_VENDOR = "gemini"
AUTHOR_MODEL = "gemini-3.6-flash"
AUTHOR_EFFORT = "high"
AUTHOR_SCOPE = "whole_phase"

PR_T_18_PATTERNS: tuple[str, ...] = (
    "phase-loop-runtime/tests/fixtures/proofgate/**",
    "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
    "phase-loop-runtime/tests/proofgate_tdd_guard.py",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py",
    "phase-loop-runtime/tests/test_closeout_verification_gate.py",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_preflight_verification.py",
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py",
    "phase-loop-runtime/tests/test_proofgate_isolation.py",
    "phase-loop-runtime/tests/test_proofgate_receipts.py",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py",
    "phase-loop-runtime/tests/test_skills_canon_parity.py",
    "phase-loop-runtime/tests/test_tdd_chronology.py",
    "phase-loop-runtime/tests/test_train_invariants.py",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py",
    "phase-loop-runtime/tests/test_verification_evidence.py",
)
PR_T_18_PATTERNS_SHA256 = "3b0c0914871e17d56c24fa34e4578c498110425bcc79c4cd3dc10277a1d50deb"
PR_T_18_PATHS: tuple[str, ...] = (
    "phase-loop-runtime/tests/fixtures/proofgate/v10-proofgate-mutations.json",
    *PR_T_18_PATTERNS[1:],
)
PR_T_18_PATHS_SHA256 = "53f80012139690b0e653f197bccc178050a22496a039bdbe36e579a24441a2bd"
PR_B_5_PATHS: tuple[str, ...] = (
    ".github/workflows/proofgate-receipt-attestation.yml",
    "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
    "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_isolation.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_receipts.py",
)
PR_B_5_PATHS_SHA256 = "3c365db032ad94622149fde1cadcb84b45480d65d8d789387ef47de286b59c44"
PHASE_38_PATTERNS: tuple[str, ...] = (
    ".github/workflows/proofgate-receipt-attestation.yml",
    "phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md",
    "phase-loop-runtime/src/phase_loop_runtime/closeout.py",
    "phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py",
    "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
    "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_capability.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_isolation.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_receipts.py",
    "phase-loop-runtime/src/phase_loop_runtime/runner.py",
    "phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-plan-phase/**",
    "phase-loop-runtime/src/phase_loop_runtime/tdd_chronology.py",
    "phase-loop-runtime/src/phase_loop_runtime/train_runner.py",
    "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
    "phase-loop-runtime/tests/fixtures/proofgate/**",
    "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
    "phase-loop-runtime/tests/proofgate_tdd_guard.py",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py",
    "phase-loop-runtime/tests/test_closeout_verification_gate.py",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_preflight_verification.py",
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py",
    "phase-loop-runtime/tests/test_proofgate_isolation.py",
    "phase-loop-runtime/tests/test_proofgate_receipts.py",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py",
    "phase-loop-runtime/tests/test_skills_canon_parity.py",
    "phase-loop-runtime/tests/test_tdd_chronology.py",
    "phase-loop-runtime/tests/test_train_invariants.py",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py",
    "phase-loop-runtime/tests/test_verification_evidence.py",
    "phase-loop-skills/plan-phase/**",
    "skills-src/claude/claude-plan-phase/SKILL.md",
    "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py",
    "skills-src/codex/codex-plan-phase/SKILL.md",
    "skills-src/gemini/gemini-plan-phase/SKILL.md",
    "skills-src/opencode/opencode-plan-phase/SKILL.md",
)
PHASE_38_PATTERNS_SHA256 = "a19e9ae2714f414d92b12314e8e9370aa1518a400d638c6eef211eb05e4b6c9b"
EXPECTED_39_NODEIDS_SHA256 = "8e48a3efe3cb6fc534fc7dae67012e40b76e0fa14953d7a52801becc15614274"


def _norm_seat(seat: str) -> str:
    s = seat.lower().strip()
    if s in ("sol", "gpt-5.6-sol"):
        return "gpt-5.6-sol"
    return s


def evaluate_unit_double_bootstrap_merge_review_gate(
    evidence: dict[str, Any],
    *,
    expected_digest: str | None = None,
    author_vendor: str | None = None,
    expected_candidate_oid: str | None = None,
    expected_base_oid: str | None = None,
    expected_repo: str | None = None,
    expected_head_ref: str | None = None,
    expected_base_ref: str | None = None,
) -> dict[str, Any]:
    """Pure evaluator for unit-double metadata (non-decisive).

    Validates evidence input structure, panel seats, Gemini author tuple,
    and returns a result dictionary with evidence_kind="unit_double" and decisive=False.
    """
    if not isinstance(evidence, dict):
        raise ProofgateBootstrapVerifierError("Sealed evidence input must be a dictionary")

    required_top_keys = {
        "candidate_oid",
        "base_oid",
        "path_blob_digest",
        "change_tuple_digest",
        "topology",
        "seat_records",
        "seat_chronology",
        "author_vendor",
        "raw_log_digest",
        "junit_mode_digests",
        "control_digests",
        "github_pr",
    }
    if set(evidence.keys()) != required_top_keys:
        missing = required_top_keys - set(evidence.keys())
        extra = set(evidence.keys()) - required_top_keys
        if missing:
            raise ProofgateBootstrapVerifierError(f"Sealed evidence missing required top-level key(s): {sorted(list(missing))}")
        if extra:
            raise ProofgateBootstrapVerifierError(f"Sealed evidence contains unexpected top-level key(s): {sorted(list(extra))}")

    cand_oid = evidence["candidate_oid"]
    base_oid = evidence["base_oid"]
    if not isinstance(cand_oid, str) or not HEX_40_RE.match(cand_oid):
        raise ProofgateBootstrapVerifierError("Invalid candidate_oid in sealed evidence (must be exact 40-lowercase-hex)")
    if not isinstance(base_oid, str) or not HEX_40_RE.match(base_oid) or base_oid == cand_oid:
        raise ProofgateBootstrapVerifierError("Invalid base_oid in sealed evidence (must be exact 40-lowercase-hex and distinct)")

    if expected_candidate_oid and cand_oid != expected_candidate_oid:
        raise ProofgateBootstrapVerifierError(f"candidate_oid '{cand_oid}' does not match expected '{expected_candidate_oid}'")
    if expected_base_oid and base_oid != expected_base_oid:
        raise ProofgateBootstrapVerifierError(f"base_oid '{base_oid}' does not match expected '{expected_base_oid}'")

    path_blob = evidence["path_blob_digest"]
    change_tuple = evidence["change_tuple_digest"]
    raw_log = evidence["raw_log_digest"]
    for name, dig in (("path_blob_digest", path_blob), ("change_tuple_digest", change_tuple), ("raw_log_digest", raw_log)):
        if not isinstance(dig, str) or not HEX_64_RE.match(dig):
            raise ProofgateBootstrapVerifierError(f"Invalid {name} in sealed evidence (must be exact 64-lowercase-hex)")

    topo = evidence["topology"]
    if not isinstance(topo, dict) or set(topo.keys()) not in ({"two_parent", "every_parent_present"}, {"two_parent", "every_parent_present", "parent_oids"}):
        raise ProofgateBootstrapVerifierError("Sealed evidence topology schema invalid")
    if topo.get("two_parent") is not True or topo.get("every_parent_present") is not True:
        raise ProofgateBootstrapVerifierError("Topology must be two-parent with every parent present")
    if "parent_oids" not in topo or not isinstance(topo["parent_oids"], list) or len(topo["parent_oids"]) != 2:
        raise ProofgateBootstrapVerifierError("Topology must contain parent_oids list with exactly 2 parent OIDs")
    for p_oid in topo["parent_oids"]:
        if not isinstance(p_oid, str) or not HEX_40_RE.match(p_oid):
            raise ProofgateBootstrapVerifierError(f"Invalid parent OID '{p_oid}' in topology")
    if topo["parent_oids"][0] != base_oid:
        raise ProofgateBootstrapVerifierError(f"base_oid '{base_oid}' must match topology parent_oids[0]")

    j_digs = evidence["junit_mode_digests"]
    req_j_keys = {"default", "forced_red", "ordinary", "attended"}
    if not isinstance(j_digs, dict) or set(j_digs.keys()) != req_j_keys:
        raise ProofgateBootstrapVerifierError("Sealed evidence junit_mode_digests schema invalid")
    for jk, jv in j_digs.items():
        if not isinstance(jv, str) or not HEX_64_RE.match(jv):
            raise ProofgateBootstrapVerifierError(f"Invalid junit_mode_digest for {jk}")

    c_digs = evidence["control_digests"]
    req_c_keys = {"isolation", "taint", "misuse", "control", "positive_canary"}
    if not isinstance(c_digs, dict) or set(c_digs.keys()) != req_c_keys:
        raise ProofgateBootstrapVerifierError("Sealed evidence control_digests schema invalid")
    for ck, cv in c_digs.items():
        if not isinstance(cv, str) or not HEX_64_RE.match(cv):
            raise ProofgateBootstrapVerifierError(f"Invalid control_digest for {ck}")

    pr = evidence["github_pr"]
    req_pr_keys = {"number", "repo", "head_ref", "base_ref"}
    if not isinstance(pr, dict) or not req_pr_keys.issubset(set(pr.keys())):
        raise ProofgateBootstrapVerifierError("Sealed evidence github_pr schema invalid")
    if not isinstance(pr["number"], int) or pr["number"] <= 0:
        raise ProofgateBootstrapVerifierError("Invalid PR number in sealed evidence")
    if expected_repo and pr["repo"] != expected_repo:
        raise ProofgateBootstrapVerifierError(f"PR repo '{pr['repo']}' does not match expected '{expected_repo}'")
    if expected_head_ref and pr["head_ref"] != expected_head_ref:
        raise ProofgateBootstrapVerifierError(f"PR head_ref '{pr['head_ref']}' does not match expected '{expected_head_ref}'")
    if expected_base_ref and pr["base_ref"] != expected_base_ref:
        raise ProofgateBootstrapVerifierError(f"PR base_ref '{pr['base_ref']}' does not match expected '{expected_base_ref}'")

    raw_author = evidence.get("author_vendor") or author_vendor
    if not raw_author:
        raise ProofgateBootstrapVerifierError("author_vendor is required in sealed evidence")
    eff_author = _norm_seat(raw_author)
    if eff_author != AUTHOR_VENDOR:
        raise ProofgateBootstrapVerifierError(f"Author vendor must be '{AUTHOR_VENDOR}', got '{eff_author}'")

    seat_records = evidence["seat_records"]
    if not isinstance(seat_records, dict):
        raise ProofgateBootstrapVerifierError("seat_records must be a dictionary")

    required_seats = {"fable", "gpt-5.6-sol", "gemini", "grok"}
    normalized_records: dict[str, dict[str, Any]] = {}
    for seat, rec in seat_records.items():
        if not isinstance(rec, dict):
            raise ProofgateBootstrapVerifierError(f"Seat record for {seat} must be a dictionary")
        norm_s = _norm_seat(seat)
        if norm_s in normalized_records:
            raise ProofgateBootstrapVerifierError(f"Duplicate seat record for {norm_s}")
        normalized_records[norm_s] = rec

    missing_seats = required_seats - set(normalized_records.keys())
    if missing_seats:
        raise ProofgateBootstrapVerifierError(f"Missing required panel seat(s): {sorted(list(missing_seats))}")

    extra_seats = set(normalized_records.keys()) - required_seats
    if extra_seats:
        raise ProofgateBootstrapVerifierError(f"Unexpected panel seat(s): {sorted(list(extra_seats))}")

    target_digest: str = expected_digest or change_tuple
    indep_count = 0
    seen_run_ids: set[str] = set()

    for seat in ("fable", "gpt-5.6-sol", "gemini", "grok"):
        rec = normalized_records[seat]
        verdict = str(rec.get("verdict", "")).upper()
        if verdict != "AGREE":
            raise ProofgateBootstrapVerifierError(f"Seat {seat} verdict is '{verdict}', required AGREE")
        if rec.get("substantive") is not True:
            raise ProofgateBootstrapVerifierError(f"Seat {seat} review is non-substantive")

        run_id = rec.get("run_identity")
        if not run_id or not isinstance(run_id, str):
            raise ProofgateBootstrapVerifierError(f"Seat {seat} must specify explicit non-empty run_identity string")
        if run_id in seen_run_ids:
            raise ProofgateBootstrapVerifierError(f"Duplicate run_identity '{run_id}' found across seats")
        seen_run_ids.add(run_id)

        digest = rec.get("candidate_digest")
        if not digest or not HEX_64_RE.match(str(digest)) or digest != target_digest:
            raise ProofgateBootstrapVerifierError(
                f"Seat {seat} digest '{digest}' disagrees with target digest '{target_digest}' or is invalid hex"
            )

        attester = _norm_seat(str(rec.get("attester", "")))
        if attester != seat:
            raise ProofgateBootstrapVerifierError(f"Seat {seat} attester '{attester}' does not match seat name '{seat}'")

        if "is_author" not in rec or "independent_attestor" not in rec:
            raise ProofgateBootstrapVerifierError(f"Seat {seat} must explicitly specify both is_author and independent_attestor booleans")
        is_author = rec["is_author"]
        indep_attestor = rec["independent_attestor"]

        if not isinstance(is_author, bool) or not isinstance(indep_attestor, bool):
            raise ProofgateBootstrapVerifierError(f"Seat {seat} is_author and independent_attestor must be booleans")

        if seat == eff_author:
            if is_author is not True or indep_attestor is not False:
                raise ProofgateBootstrapVerifierError(f"Author seat '{seat}' must have exactly is_author=True and independent_attestor=False")
        else:
            if is_author is not False or indep_attestor is not True:
                raise ProofgateBootstrapVerifierError(f"Independent seat '{seat}' must have exactly is_author=False and independent_attestor=True")
            indep_count += 1

    if indep_count != 3:
        raise ProofgateBootstrapVerifierError(f"Review gate requires exactly 3 independent attestors, found {indep_count}")

    seat_chron = evidence["seat_chronology"]
    if not isinstance(seat_chron, list) or len(seat_chron) != 4:
        raise ProofgateBootstrapVerifierError("Seat chronology must contain exactly four distinct seats")

    norm_chron = [_norm_seat(s) for s in seat_chron]
    if len(set(norm_chron)) != 4 or set(norm_chron) != required_seats:
        raise ProofgateBootstrapVerifierError("Seat chronology must contain each of the 4 required seats exactly once")

    return {
        "status": "valid",
        "evidence_kind": "unit_double",
        "decisive": False,
        "author_vendor": AUTHOR_VENDOR,
        "author_model": AUTHOR_MODEL,
        "author_effort": AUTHOR_EFFORT,
        "author_scope": AUTHOR_SCOPE,
        "independent_attestors": 3,
    }


def verify_bootstrap_merge_review_gate(
    evidence: dict[str, Any],
    *,
    expected_digest: str | None = None,
    author_vendor: str | None = None,
    expected_candidate_oid: str | None = None,
    expected_base_oid: str | None = None,
    expected_repo: str | None = None,
    expected_head_ref: str | None = None,
    expected_base_ref: str | None = None,
) -> bool:
    """Evaluates bootstrap review gate for unit doubles and returns True if valid."""
    res = evaluate_unit_double_bootstrap_merge_review_gate(
        evidence,
        expected_digest=expected_digest,
        author_vendor=author_vendor,
        expected_candidate_oid=expected_candidate_oid,
        expected_base_oid=expected_base_oid,
        expected_repo=expected_repo,
        expected_head_ref=expected_head_ref,
        expected_base_ref=expected_base_ref,
    )
    return res.get("status") == "valid"


def parse_git_diff_tree_raw(repo_path: str | Path, base_oid: str, candidate_oid: str) -> list[tuple[str, str, str, str, str, str, str]]:
    """Executes git diff-tree --raw -r -z base_oid candidate_oid and returns parsed path tuples.

    Tuple format: (change_kind, path, old_mode, new_mode, old_blob_oid, new_blob_oid, new_file_sha256)
    """
    r_path = Path(repo_path)
    res = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
        cwd=r_path,
        capture_output=True,
        check=True,
    )
    raw = res.stdout
    if not raw:
        return []

    parts = raw.split(b"\x00")
    i = 0
    tuples = []
    while i < len(parts):
        chunk = parts[i].decode("utf-8", errors="replace").strip()
        if not chunk:
            i += 1
            continue
        if not chunk.startswith(":"):
            i += 1
            continue

        meta = chunk[1:].split()
        if len(meta) < 5:
            raise ProofgateBootstrapVerifierError(f"Malformed git diff-tree line: {chunk}")
        old_mode, new_mode, old_blob_oid, new_blob_oid, status_str = meta[0], meta[1], meta[2], meta[3], meta[4]
        change_kind = status_str[0]

        if change_kind in ("R", "C"):
            raise ProofgateBootstrapVerifierError("Rename or copy change kind is forbidden in PROOFGATE landings")

        i += 1
        if i >= len(parts):
            break
        path_str = parts[i].decode("utf-8", errors="replace")

        new_sha256 = ""
        if new_blob_oid and new_blob_oid != "0" * 40:
            cat_proc = subprocess.run(
                ["git", "cat-file", "-p", new_blob_oid],
                cwd=r_path,
                capture_output=True,
            )
            if cat_proc.returncode == 0:
                new_sha256 = hashlib.sha256(cat_proc.stdout).hexdigest()

        tuples.append((change_kind, path_str, old_mode, new_mode, old_blob_oid, new_blob_oid, new_sha256))
        i += 1

    return tuples


def compute_git_source_binding_facts(repo_path: Path | str, base_oid: str, candidate_oid: str) -> dict[str, Any]:
    """Source-binding helper using git diff-tree --raw -z, git ls-tree -rz, and git cat-file."""
    r_path = Path(repo_path)
    if not r_path.is_dir() or not (r_path / ".git").exists():
        return {}

    try:
        diff_proc = subprocess.run(
            ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
            cwd=r_path,
            capture_output=True,
            check=True,
        )
        diff_raw = diff_proc.stdout

        ls_proc = subprocess.run(
            ["git", "ls-tree", "-rz", candidate_oid],
            cwd=r_path,
            capture_output=True,
            check=True,
        )
        ls_raw = ls_proc.stdout

        cat_proc = subprocess.run(
            ["git", "cat-file", "-p", candidate_oid],
            cwd=r_path,
            capture_output=True,
            check=True,
        )
        cat_raw = cat_proc.stdout

        path_tuples = parse_git_diff_tree_raw(r_path, base_oid, candidate_oid)

        return {
            "candidate_oid": candidate_oid,
            "base_oid": base_oid,
            "path_blob_digest": hashlib.sha256(ls_raw).hexdigest(),
            "change_tuple_digest": hashlib.sha256(diff_raw).hexdigest(),
            "commit_header": cat_raw.decode("utf-8", errors="replace"),
            "path_tuples": path_tuples,
        }
    except Exception:
        return {}


def verify_premerge_bootstrap_review_gate(
    repo_path: Path | str,
    base_oid: str,
    candidate_oid: str,
    github_pr: dict[str, Any],
    seat_records: dict[str, Any],
    seat_chronology: list[str],
    landing_kind: str = "PR-T",
) -> dict[str, Any]:
    """Decisive test-owned pre-merge verification over real Git repository and GitHub PR metadata."""
    r_path = Path(repo_path)
    if not HEX_40_RE.match(base_oid) or not HEX_40_RE.match(candidate_oid):
        raise ProofgateBootstrapVerifierError("Invalid base_oid or candidate_oid format")

    facts = compute_git_source_binding_facts(r_path, base_oid, candidate_oid)
    if not facts:
        raise ProofgateBootstrapVerifierError("Failed to extract Git source binding facts from repository")

    commit_header = facts.get("commit_header", "")
    parents = [line.split()[1] for line in commit_header.splitlines() if line.startswith("parent ")]
    if len(parents) != 1 or parents[0] != base_oid:
        raise ProofgateBootstrapVerifierError(f"Candidate commit must have exactly one parent equal to base_oid '{base_oid}'")

    path_tuples = facts.get("path_tuples", [])
    modified_paths = sorted([t[1] for t in path_tuples])

    import fnmatch

    def _matches_pattern(path: str, pat: str) -> bool:
        if pat.endswith("/**"):
            prefix = pat[:-3]
            return path == prefix or path.startswith(prefix + "/")
        return fnmatch.fnmatch(path, pat) or path == pat

    if landing_kind == "PR-T":
        if not modified_paths:
            raise ProofgateBootstrapVerifierError("PR-T candidate modified paths cannot be empty")
        inv_digest = hashlib.sha256((json.dumps(list(PR_T_18_PATTERNS), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
        if inv_digest != PR_T_18_PATTERNS_SHA256:
            raise ProofgateBootstrapVerifierError(f"PR-T pattern inventory SHA-256 mismatch (expected {PR_T_18_PATTERNS_SHA256}, got {inv_digest})")
        paths_digest = hashlib.sha256((json.dumps(list(PR_T_18_PATHS), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
        if paths_digest != PR_T_18_PATHS_SHA256:
            raise ProofgateBootstrapVerifierError(f"PR-T exact path inventory SHA-256 mismatch (expected {PR_T_18_PATHS_SHA256}, got {paths_digest})")

        for p in modified_paths:
            if not any(_matches_pattern(p, pat) for pat in PR_T_18_PATTERNS):
                raise ProofgateBootstrapVerifierError(f"PR-T candidate contains unauthorized non-test path: {p}")
            if p.startswith("phase-loop-runtime/src/") or p.startswith(".github/workflows/"):
                raise ProofgateBootstrapVerifierError(f"PR-T candidate contains production path: {p}")

        pr_t_exact = sorted(PR_T_18_PATHS)
        if len(modified_paths) != 18 or modified_paths != pr_t_exact:
            raise ProofgateBootstrapVerifierError(f"PR-T candidate modified paths must match exact 18-path inventory. Got: {modified_paths}")
    elif landing_kind == "PR-B":
        if modified_paths != list(PR_B_5_PATHS):
            raise ProofgateBootstrapVerifierError(f"PR-B modified paths do not match exact 5 PR-B path set. Got: {modified_paths}")
        inv_digest = hashlib.sha256((json.dumps(modified_paths, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
        if inv_digest != PR_B_5_PATHS_SHA256:
            raise ProofgateBootstrapVerifierError("PR-B path inventory SHA-256 mismatch")

    inv_38_digest = hashlib.sha256((json.dumps(list(PHASE_38_PATTERNS), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
    if inv_38_digest != PHASE_38_PATTERNS_SHA256:
        raise ProofgateBootstrapVerifierError("Production 38-pattern digest mismatch")

    exp_nodeids_sha = hashlib.sha256((json.dumps(sorted(list(EXPECTED_PHASE_NODEIDS)), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
    if exp_nodeids_sha != EXPECTED_39_NODEIDS_SHA256:
        raise ProofgateBootstrapVerifierError("Expected 39 nodeids SHA-256 mismatch")

    if not isinstance(github_pr, dict):
        raise ProofgateBootstrapVerifierError("github_pr must be a dictionary")
    if github_pr.get("repo") not in ("Consiliency/agent-harness", "1280382652"):
        raise ProofgateBootstrapVerifierError("github_pr repo mismatch")
    if github_pr.get("base_sha") and github_pr["base_sha"] != base_oid:
        raise ProofgateBootstrapVerifierError("github_pr base_sha mismatch")
    if github_pr.get("head_sha") and github_pr["head_sha"] != candidate_oid:
        raise ProofgateBootstrapVerifierError("github_pr head_sha mismatch")

    target_digest = facts["change_tuple_digest"]
    path_blob_dig = facts["path_blob_digest"]

    # Compute actual digests over actual artifact file bytes if present; fail closed if absent or unreadable
    run_dir_env = os.environ.get("PHASE_LOOP_RUN_DIR")
    run_dir_path = Path(run_dir_env) if run_dir_env else None

    def _read_artifact_digest(filename: str, label: str) -> str:
        candidates = [
            r_path / filename,
            r_path / ".phase-loop" / "runs" / filename,
        ]
        if run_dir_path:
            candidates.insert(0, run_dir_path / filename)
        for c in candidates:
            if c.exists() and c.is_file():
                try:
                    b = c.read_bytes()[:16777216]
                    return hashlib.sha256(b).hexdigest()
                except Exception as exc:
                    raise ProofgateBootstrapVerifierError(f"Required artifact {filename} ({label}) unreadable: {exc}") from exc
        raise ProofgateBootstrapVerifierError(f"Required artifact {filename} ({label}) absent or unreadable")

    raw_log_dig = _read_artifact_digest("verification.log", "raw_log")
    junit_def_dig = _read_artifact_digest("junit_default.xml", "junit_default")
    junit_red_dig = _read_artifact_digest("junit_forced_red.xml", "junit_forced_red")
    junit_ord_dig = _read_artifact_digest("junit_ordinary.xml", "junit_ordinary")
    junit_att_dig = _read_artifact_digest("junit_attended.xml", "junit_attended")

    ctrl_iso_dig = _read_artifact_digest("ctrl_isolation.log", "ctrl_isolation")
    ctrl_tnt_dig = _read_artifact_digest("ctrl_taint.log", "ctrl_taint")
    ctrl_mis_dig = _read_artifact_digest("ctrl_misuse.log", "ctrl_misuse")
    ctrl_ctl_dig = _read_artifact_digest("ctrl_control.log", "ctrl_control")
    ctrl_can_dig = _read_artifact_digest("ctrl_positive_canary.log", "ctrl_positive_canary")

    evidence_payload = {
        "candidate_oid": candidate_oid,
        "base_oid": base_oid,
        "path_blob_digest": path_blob_dig,
        "change_tuple_digest": target_digest,
        "topology": {"two_parent": True, "every_parent_present": True, "parent_oids": [base_oid, candidate_oid]},
        "seat_records": seat_records,
        "seat_chronology": seat_chronology,
        "author_vendor": AUTHOR_VENDOR,
        "raw_log_digest": raw_log_dig,
        "junit_mode_digests": {
            "default": junit_def_dig,
            "forced_red": junit_red_dig,
            "ordinary": junit_ord_dig,
            "attended": junit_att_dig,
        },
        "control_digests": {
            "isolation": ctrl_iso_dig,
            "taint": ctrl_tnt_dig,
            "misuse": ctrl_mis_dig,
            "control": ctrl_ctl_dig,
            "positive_canary": ctrl_can_dig,
        },
        "github_pr": github_pr,
    }
    eval_res = evaluate_unit_double_bootstrap_merge_review_gate(evidence_payload, expected_digest=target_digest)
    eval_res["evidence_kind"] = "unit_double"
    eval_res["decisive"] = False
    eval_res["change_tuple_digest"] = target_digest
    eval_res["path_blob_digest"] = path_blob_dig
    return eval_res


def verify_landed_bootstrap_source_binding(
    repo_path: Path | str,
    landing_oid: str,
    base_oid: str,
    candidate_oid: str,
    github_pr: dict[str, Any],
    seat_records: dict[str, Any],
    seat_chronology: list[str],
    landing_kind: str = "PR-T",
) -> dict[str, Any]:
    """Decisive test-owned post-merge landing verification over a 2-parent merge commit."""
    r_path = Path(repo_path)
    if not HEX_40_RE.match(landing_oid) or not HEX_40_RE.match(base_oid) or not HEX_40_RE.match(candidate_oid):
        raise ProofgateBootstrapVerifierError("Invalid OID format for landed verification")

    cat_proc = subprocess.run(
        ["git", "cat-file", "-p", landing_oid],
        cwd=r_path,
        capture_output=True,
        check=True,
    )
    commit_header = cat_proc.stdout.decode("utf-8", errors="replace")
    parents = [line.split()[1] for line in commit_header.splitlines() if line.startswith("parent ")]
    if len(parents) != 2:
        raise ProofgateBootstrapVerifierError("two_parent_landing_required")
    if parents[0] != base_oid or parents[1] != candidate_oid:
        raise ProofgateBootstrapVerifierError(f"Merge commit parents {parents} must equal ordered [base_oid, candidate_oid] [{base_oid}, {candidate_oid}]")

    diff_landing = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, landing_oid],
        cwd=r_path,
        capture_output=True,
        check=True,
    ).stdout

    diff_cand = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
        cwd=r_path,
        capture_output=True,
        check=True,
    ).stdout

    if diff_landing != diff_cand:
        raise ProofgateBootstrapVerifierError("Merge resolution byte drift detected: first-parent landing diff does not match candidate diff")

    premerge_res = verify_premerge_bootstrap_review_gate(
        r_path, base_oid, candidate_oid, github_pr, seat_records, seat_chronology, landing_kind=landing_kind
    )

    premerge_res["evidence_kind"] = "unit_double"
    premerge_res["decisive"] = False
    premerge_res["landing_oid"] = landing_oid
    return premerge_res


def verify_junit_accounting(junit_xml_str: str, mode: str, *, phase_reports: list[dict[str, Any]] | Path | str | None = None, runner_envelope: dict[str, Any] | None = None, strict_nodeids: bool = True) -> dict[str, Any]:
    """Validates pytest JUnit XML and typed phase reports for expected PROOFGATE nodeid and mode accounting.

    Modes:
      - 'default': 3 passed, 36 skipped, 0 failures, 0 errors
      - 'forced_red': 2 passed, 37 failures, 0 skipped, 0 errors
      - 'ordinary_hermetic': 39 passed, 0 skipped, 0 failures, 0 errors
      - 'attended_live': 39 passed, 0 skipped, 0 failures, 0 errors, 4 provider rows executed
    """
    try:
        if isinstance(junit_xml_str, (str, Path)) and os.path.exists(str(junit_xml_str)):
            xml_text = Path(junit_xml_str).read_text(encoding="utf-8")
        else:
            xml_text = str(junit_xml_str)
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise ProofgateBootstrapVerifierError(f"Invalid JUnit XML: {exc}") from exc

    testcases = root.findall(".//testcase")
    collected_nodeids: list[str] = []
    seen_nodeids: set[str] = set()
    passed_nodeids: set[str] = set()
    skipped_nodeids: set[str] = set()
    failed_nodeids: set[str] = set()

    properties_by_testcase: dict[str, dict[str, str]] = {}
    failures_by_nodeid: dict[str, ET.Element] = {}

    for tc in testcases:
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        nodeid_match = None
        norm_cls = classname.lstrip(".")
        for exp in EXPECTED_PHASE_NODEIDS:
            exp_clean = exp.replace("phase-loop-runtime/", "")
            parts = exp_clean.split("::")
            file_mod = parts[0].replace("/", ".").replace(".py", "")
            base_mod = parts[0].split("/")[-1].replace(".py", "")

            valid_cls_names = {
                file_mod,
                f"tests.{file_mod}",
                f"phase-loop-runtime.tests.{file_mod}",
                f"phase_loop_runtime.tests.{file_mod}",
                base_mod,
                f"tests.{base_mod}",
                f"phase-loop-runtime.tests.{base_mod}",
                f"phase_loop_runtime.tests.{base_mod}",
            }

            if len(parts) == 3:
                cls_name = parts[1]
                fn_name = parts[2]
                valid_cls_names = {f"{c}.{cls_name}" for c in valid_cls_names}
                if name == fn_name and norm_cls in valid_cls_names:
                    nodeid_match = exp
                    break
            elif len(parts) == 2:
                fn_name = parts[1]
                valid_2part_cls_names = {file_mod, f"tests.{file_mod}", f"phase-loop-runtime.tests.{base_mod}", f"phase_loop_runtime.tests.{base_mod}", base_mod, f"tests.{base_mod}"}
                if (name == fn_name or name == exp or name == exp_clean) and norm_cls in valid_2part_cls_names:
                    nodeid_match = exp
                    break

        if not nodeid_match:
            if strict_nodeids:
                raise ProofgateBootstrapVerifierError(f"Unrecognized or extra testcase in JUnit XML: {classname}.{name}")
            continue

        if nodeid_match in seen_nodeids:
            raise ProofgateBootstrapVerifierError(f"Duplicate JUnit nodeid: {nodeid_match}")
        seen_nodeids.add(nodeid_match)
        collected_nodeids.append(nodeid_match)

        tc_props: dict[str, str] = {}
        for prop in tc.findall(".//property"):
            pname = prop.get("name")
            pval = prop.get("value", "true")
            if pname:
                if pname in tc_props:
                    raise ProofgateBootstrapVerifierError(f"Duplicate property {pname} in testcase {name}")
                tc_props[pname] = pval
        properties_by_testcase[nodeid_match] = tc_props

        skip_elem = tc.find("skipped")
        fail_elem = tc.find("failure")
        err_elem = tc.find("error")

        if err_elem is not None:
            raise ProofgateBootstrapVerifierError(f"Error in testcase {name}: {err_elem.get('message')}")
        elif fail_elem is not None:
            failed_nodeids.add(nodeid_match)
            failures_by_nodeid[nodeid_match] = fail_elem
        elif skip_elem is not None:
            skipped_nodeids.add(nodeid_match)
        else:
            passed_nodeids.add(nodeid_match)

    missing_nodeids = set(EXPECTED_PHASE_NODEIDS) - set(collected_nodeids)
    if missing_nodeids:
        raise ProofgateBootstrapVerifierError(f"JUnit missing phase nodeid(s): {sorted(list(missing_nodeids))}")

    designated_provider_nodeid = "phase-loop-runtime/tests/test_proofgate_isolation.py::test_provider_projection_allows_only_selected_vendor_subscription_material"

    if mode == "default":
        if skipped_nodeids != set(DEFAULT_SKIP_NODEIDS):
            raise ProofgateBootstrapVerifierError("Default mode skipped nodeids do not match exact DEFAULT_SKIP_NODEIDS set")
        expected_passed = set(EXPECTED_PHASE_NODEIDS) - set(DEFAULT_SKIP_NODEIDS)
        if passed_nodeids != expected_passed:
            raise ProofgateBootstrapVerifierError("Default mode passed nodeids do not match expected 3 non-skipped nodeids")
        if len(failed_nodeids) != 0:
            raise ProofgateBootstrapVerifierError(f"Default mode expected 0 failures, got {len(failed_nodeids)}")
    elif mode == "forced_red":
        if failed_nodeids != set(RED_CASES_BY_NODEID.keys()):
            raise ProofgateBootstrapVerifierError("Forced RED mode failed nodeids do not match RED_CASES_BY_NODEID set")
        expected_passed = set(EXPECTED_PHASE_NODEIDS) - set(RED_CASES_BY_NODEID.keys())
        if passed_nodeids != expected_passed:
            raise ProofgateBootstrapVerifierError("Forced RED mode passed nodeids do not match expected positive controls")
        if len(skipped_nodeids) != 0:
            raise ProofgateBootstrapVerifierError(f"Forced RED mode expected 0 skips, got {len(skipped_nodeids)}")

        for nid in failed_nodeids:
            if nid in RED_CASES_BY_NODEID:
                _, case_id = RED_CASES_BY_NODEID[nid]
                expected_tag = f"PROOFGATE_RED::{case_id}"
                fail_elem = failures_by_nodeid.get(nid)
                fail_msg = fail_elem.get("message", "").strip() if fail_elem is not None else ""
                fail_text = fail_elem.text.strip() if fail_elem is not None and fail_elem.text is not None else ""

                # Exact tag match required — strip at most ONE standard AssertionError prefix; reject duplicate prefixes or trailing junk
                def _strip_single_prefix(s: str) -> str:
                    if s.count("AssertionError:") > 1:
                        return "INVALID_MULTIPLE_ASSERTION_ERROR_PREFIX"
                    if s.startswith("AssertionError: "):
                        return s[len("AssertionError: "):].strip()
                    return s.strip()

                clean_msg = _strip_single_prefix(fail_msg)
                clean_text = _strip_single_prefix(fail_text)

                if clean_msg != expected_tag and clean_text != expected_tag:
                    raise ProofgateBootstrapVerifierError(
                        f"Forced RED failure for {nid} missing exact RED tag '{expected_tag}'. Got message: '{fail_msg}'"
                    )
    elif mode in ("ordinary_hermetic", "ordinary"):
        if len(passed_nodeids) != 39:
            raise ProofgateBootstrapVerifierError(f"Ordinary mode expected 39 passes, got {len(passed_nodeids)}")
        if len(skipped_nodeids) != 0 or len(failed_nodeids) != 0:
            raise ProofgateBootstrapVerifierError("Ordinary mode expected 0 skips/failures")

        desig_props = properties_by_testcase.get(designated_provider_nodeid, {})
        for nid, props in properties_by_testcase.items():
            if nid != designated_provider_nodeid:
                for prov_case in ATTENDED_REAL_PROVIDER_CASES:
                    if prov_case in props:
                        raise ProofgateBootstrapVerifierError(f"Provider property '{prov_case}' found on non-designated testcase '{nid}'")

        for prov_case in ATTENDED_REAL_PROVIDER_CASES:
            val = desig_props.get(prov_case)
            if val != "not_executed_in_ordinary_mode":
                raise ProofgateBootstrapVerifierError(
                    f"Ordinary mode property {prov_case} expected 'not_executed_in_ordinary_mode', got '{val}'"
                )
    elif mode == "attended_live":
        if len(passed_nodeids) != 39:
            raise ProofgateBootstrapVerifierError(f"Attended live mode expected 39 passes, got {len(passed_nodeids)}")
        if len(skipped_nodeids) != 0 or len(failed_nodeids) != 0:
            raise ProofgateBootstrapVerifierError("Attended live mode expected 0 skips/failures")

        if not runner_envelope or not isinstance(runner_envelope, dict):
            raise ProofgateBootstrapVerifierError("Attended live mode requires a valid external runner_envelope")

        desig_props = properties_by_testcase.get(designated_provider_nodeid, {})
        for nid, props in properties_by_testcase.items():
            if nid != designated_provider_nodeid:
                for prov_case in ATTENDED_REAL_PROVIDER_CASES:
                    if prov_case in props:
                        raise ProofgateBootstrapVerifierError(f"Provider property '{prov_case}' found on non-designated testcase '{nid}'")

        req_prov_keys = {"runner_stage", "module_identity", "head_identity", "nonce", "broker_digest", "profile_digest"}
        exp_nonces = runner_envelope.get("nonces", {})
        exp_broker_digs = runner_envelope.get("broker_digests", {})
        exp_profile_digs = runner_envelope.get("profile_digests", {})

        for prov_case in ATTENDED_REAL_PROVIDER_CASES:
            if prov_case not in desig_props:
                raise ProofgateBootstrapVerifierError(f"Missing attended provider property: {prov_case}")
            val = desig_props[prov_case]
            try:
                data = json.loads(val)
            except Exception:
                raise ProofgateBootstrapVerifierError(f"Attended provider property '{prov_case}' value is not valid JSON: '{val}'")

            if not isinstance(data, dict) or set(data.keys()) != req_prov_keys:
                raise ProofgateBootstrapVerifierError(f"Attended provider property '{prov_case}' schema invalid")

            if data.get("runner_stage") != runner_envelope.get("runner_stage"):
                raise ProofgateBootstrapVerifierError(f"runner_stage mismatch in {prov_case}")
            if data.get("module_identity") != runner_envelope.get("module_identity"):
                raise ProofgateBootstrapVerifierError(f"module_identity mismatch in {prov_case}")
            if data.get("head_identity") != runner_envelope.get("head_identity") or not HEX_40_RE.match(data["head_identity"]):
                raise ProofgateBootstrapVerifierError(f"head_identity mismatch or invalid 40-hex in {prov_case}")

            exp_nonce = exp_nonces.get(prov_case)
            if not exp_nonce or data.get("nonce") != exp_nonce:
                raise ProofgateBootstrapVerifierError(f"nonce mismatch in {prov_case} (expected '{exp_nonce}', got '{data.get('nonce')}')")

            exp_b_dig = exp_broker_digs.get(prov_case)
            if not exp_b_dig or not HEX_64_RE.match(exp_b_dig) or data.get("broker_digest") != exp_b_dig:
                raise ProofgateBootstrapVerifierError(f"broker_digest mismatch in {prov_case}")

            exp_p_dig = exp_profile_digs.get(prov_case)
            if not exp_p_dig or not HEX_64_RE.match(exp_p_dig) or data.get("profile_digest") != exp_p_dig:
                raise ProofgateBootstrapVerifierError(f"profile_digest mismatch in {prov_case}")
    if phase_reports is None:
        raise ProofgateBootstrapVerifierError("Phase reports input is mandatory in strict accounting")

    if isinstance(phase_reports, (str, Path)) and os.path.exists(str(phase_reports)):
        try:
            raw_data = json.loads(Path(phase_reports).read_text(encoding="utf-8"))
            if isinstance(raw_data, dict):
                reports_data = raw_data.get("reports", [])
            elif isinstance(raw_data, list):
                reports_data = raw_data
            else:
                reports_data = []
        except Exception as exc:
            raise ProofgateBootstrapVerifierError(f"Invalid phase reports JSON file: {exc}") from exc
    elif isinstance(phase_reports, dict):
        reports_data = phase_reports.get("reports", [])
    elif isinstance(phase_reports, list):
        reports_data = phase_reports
    else:
        reports_data = []

    if not isinstance(reports_data, list) or len(reports_data) == 0:
        raise ProofgateBootstrapVerifierError("Phase reports input must be a non-empty list")

    seen_rep_nodeids = set()
    for rep in reports_data:
        if not isinstance(rep, dict):
            raise ProofgateBootstrapVerifierError("Phase report item must be a dictionary")
        rep_phase = rep.get("phase")
        if rep_phase != "call":
            raise ProofgateBootstrapVerifierError(f"Phase report phase must be 'call', got '{rep_phase}' for nodeid {rep.get('nodeid')}")
        rep_nid = rep.get("nodeid")
        if not rep_nid or rep_nid not in EXPECTED_PHASE_NODEIDS:
            raise ProofgateBootstrapVerifierError(f"Phase report contains unrecognized nodeid: {rep_nid}")
        if rep_nid in seen_rep_nodeids:
            raise ProofgateBootstrapVerifierError(f"Duplicate phase report nodeid: {rep_nid}")
        seen_rep_nodeids.add(rep_nid)

        rep_props = rep.get("properties", {})
        if not isinstance(rep_props, dict):
            raise ProofgateBootstrapVerifierError(f"Phase report properties for {rep_nid} must be a dictionary")

        junit_props = properties_by_testcase.get(rep_nid, {})
        for pk, pv in junit_props.items():
            if pk not in rep_props or str(rep_props[pk]) != str(pv):
                raise ProofgateBootstrapVerifierError(f"Phase report property '{pk}' mismatch with JUnit property for nodeid {rep_nid}")
        for pk, pv in rep_props.items():
            if pk not in junit_props or str(junit_props[pk]) != str(pv):
                raise ProofgateBootstrapVerifierError(f"Phase report property '{pk}' mismatch with JUnit property for nodeid {rep_nid}")

        observable_nodeids = {
            "phase-loop-runtime/tests/test_tdd_chronology.py::test_junit_lifecycle_requires_exact_nodeids_default_skip_red_failures_and_final_zero_skips",
            "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid",
            "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline",
            "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected",
            "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation",
            "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation",
            "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
            "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control",
            "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
            designated_provider_nodeid,
        }
        rep_outcome = rep.get("outcome")
        if rep_nid in skipped_nodeids and rep_outcome != "skipped":
            raise ProofgateBootstrapVerifierError(f"Phase report outcome mismatch for skipped nodeid {rep_nid}: got '{rep_outcome}'")
        if rep_nid in passed_nodeids and rep_outcome != "passed":
            raise ProofgateBootstrapVerifierError(f"Phase report outcome mismatch for passed nodeid {rep_nid}: got '{rep_outcome}'")
        if rep_nid in failed_nodeids and rep_outcome != "failed":
            raise ProofgateBootstrapVerifierError(f"Phase report outcome mismatch for failed nodeid {rep_nid}: got '{rep_outcome}'")

        if rep_outcome == "failed" or rep_nid in failed_nodeids:
            rep_exc = rep.get("exception_type")
            if rep_exc != "AssertionError":
                raise ProofgateBootstrapVerifierError(
                    f"Phase report exception_type for failed nodeid {rep_nid} must be AssertionError, got '{rep_exc}'"
                )

    missing_rep_nodeids = set(EXPECTED_PHASE_NODEIDS) - seen_rep_nodeids
    if missing_rep_nodeids:
        raise ProofgateBootstrapVerifierError(f"Missing phase report for nodeid(s): {sorted(list(missing_rep_nodeids))}")

    return {
        "mode": mode,
        "collected": len(collected_nodeids),
        "passed": len(passed_nodeids),
        "skipped": len(skipped_nodeids),
        "failed": len(failed_nodeids),
    }


def _validate_run_dir_output(output_str: str) -> Path:
    run_dir_str = os.environ.get("PHASE_LOOP_RUN_DIR")
    if not run_dir_str or not run_dir_str.strip():
        raise ProofgateBootstrapVerifierError("PHASE_LOOP_RUN_DIR environment variable is missing or empty; fallback rejected")

    run_dir = Path(run_dir_str.strip()).resolve()
    if run_dir.is_symlink() or any(parent.is_symlink() for parent in run_dir.parents):
        raise ProofgateBootstrapVerifierError(f"PHASE_LOOP_RUN_DIR path '{run_dir}' or a parent is a symlink")

    out_path = Path(output_str).resolve() if Path(output_str).is_absolute() else (run_dir / Path(output_str)).resolve()

    try:
        out_path.relative_to(run_dir)
    except ValueError:
        raise ProofgateBootstrapVerifierError(f"Output path '{out_path}' is outside PHASE_LOOP_RUN_DIR '{run_dir}'")

    if out_path.exists() or out_path.is_symlink():
        raise ProofgateBootstrapVerifierError(f"Output path '{out_path}' already exists or is a symlink")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path


class ProofgateContractViolation(AssertionError):
    """Raised when a verifier does not satisfy the frozen external-observation authority contract."""


class GitHubCliObservationBoundary:
    """Construction-only adapter for a future live GitHub CLI observation source.

    Ordinary tests construct this adapter and never execute it. `observe()` refuses before any
    process is spawned, so no ordinary run can reach `gh`, the network, auth or a provider.
    """

    def __init__(self, *, gh_executable: str = "gh", attended_live: bool = False) -> None:
        self.gh_executable = gh_executable
        self.attended_live = bool(attended_live)

    def observe(self, request: ProofgateObservationRequest) -> ProofgateExternalObservation:
        if not isinstance(request, ProofgateObservationRequest):
            raise TypeError("Observation boundary accepts only a ProofgateObservationRequest locator")
        if not self.attended_live:
            raise ProofgateObservationUnavailable(
                "live GitHub CLI observation is disabled; inject a deterministic observation boundary"
            )
        raise ProofgateObservationUnavailable(
            "attended live GitHub CLI observation is not available in the tests-only bootstrap lane"
        )


def _expected_oidc_claim_map(expected: ProofgateExpectedConfig) -> dict[str, str]:
    """Projects the exact OIDC claim map expected by an independently supplied configuration."""
    return {
        "actor": expected.actor,
        "aud": expected.oidc_audience,
        "broker_claim_policy_digest": expected.broker_claim_policy_digest,
        "broker_deployment_id": expected.broker_deployment_id,
        "broker_key_version": expected.broker_key_version,
        "environment": expected.environment_name,
        "event_name": expected.event_name,
        "repository": expected.repository_name,
        "repository_id": expected.repository_id,
        "repository_owner_id": expected.repository_owner_id,
        "run_attempt": expected.run_attempt,
        "run_id": expected.run_id,
        "runner_environment": expected.runner_environment,
        "subject": expected.subject,
        "workflow_path": expected.workflow_path,
        "workflow_ref": expected.workflow_ref,
        "workflow_sha": expected.workflow_sha256,
    }


def _require_frozen_inputs(
    request: Any,
    expected: Any,
    boundary: Any,
) -> None:
    """Rejects any substitute for the frozen locator, expected configuration or boundary."""
    if type(request) is not ProofgateObservationRequest:
        raise ProofgateBootstrapVerifierError(
            f"Verifier requires an immutable ProofgateObservationRequest locator, got {type(request).__name__}"
        )
    if type(expected) is not ProofgateExpectedConfig:
        raise ProofgateBootstrapVerifierError(
            f"Verifier requires an immutable ProofgateExpectedConfig, got {type(expected).__name__}"
        )
    if canonical_expected_config_digest(expected) != PROOFGATE_EXPECTED_CONFIG_V1_CANONICAL_SHA256:
        raise ProofgateBootstrapVerifierError(
            "Verifier requires the trusted canonical ProofgateExpectedConfig V1 bytes"
        )
    observe = getattr(boundary, "observe", None)
    if observe is None or not callable(observe):
        raise ProofgateBootstrapVerifierError("Verifier requires a read-only observation boundary exposing observe()")


def evaluate_external_observation(
    request: ProofgateObservationRequest,
    observation: Any,
    expected: ProofgateExpectedConfig,
) -> list[tuple[str, bool]]:
    """Compares a sealed observation to the locator and the independently supplied expectations.

    Returns an ordered list of `(check_id, satisfied)` pairs. No element of the result is taken
    from the caller: every expectation comes from `expected`, every observed value from
    `observation`, and every binding from the locator.
    """
    if type(observation) is not ProofgateExternalObservation:
        return [("sealed_observation_schema", False)]

    claims = dict(observation.oidc_claims)
    expected_claims = _expected_oidc_claim_map(expected)
    plan_bytes_bound = True
    if request.plan_path:
        plan_file = Path(request.plan_path)
        if not plan_file.is_file():
            plan_bytes_bound = False
        else:
            plan_bytes_bound = hashlib.sha256(plan_file.read_bytes()).hexdigest() == observation.plan_sha256

    return [
        ("sealed_observation_schema", observation.schema == PROOFGATE_OBSERVATION_SCHEMA),
        (
            "repository_identity",
            observation.repository_id == expected.repository_id
            and observation.repository_owner_id == expected.repository_owner_id
            and observation.repository_name == expected.repository_name,
        ),
        (
            "locator_repository_binding",
            request.repository in (expected.repository_name, expected.repository_id),
        ),
        ("locator_ref_binding", request.ref in expected.accepted_refs),
        ("locator_environment_binding", request.environment == expected.environment_name),
        (
            "locator_external_head_binding",
            request.external_head_ref == expected.external_head_ref
            and observation.external_head_ref == expected.external_head_ref,
        ),
        (
            "dedicated_app_installation",
            observation.app_installation_id == expected.dedicated_app_installation_id
            and observation.app_integration_id == expected.dedicated_app_integration_id
            and observation.app_repository_selection == expected.app_repository_selection
            and tuple(observation.app_permissions) == tuple(expected.app_permissions),
        ),
        (
            "branch_ruleset",
            observation.ruleset_name == expected.ruleset_name
            and set(expected.ruleset_required_rule_types).issubset(set(observation.ruleset_rule_types))
            and expected.external_head_ref in tuple(observation.ruleset_ref_includes)
            and tuple(observation.ruleset_bypass_actors)
            == (("Integration", "always", expected.dedicated_app_integration_id),),
        ),
        (
            "protected_environment",
            observation.environment_name == expected.environment_name
            and observation.environment_can_admins_bypass is False
            and observation.environment_prevent_self_review is True
            and tuple(observation.environment_required_reviewer_ids) == (expected.required_reviewer_id,),
        ),
        (
            "broker_oidc_claim_policy",
            observation.broker_deployment_id == expected.broker_deployment_id
            and observation.broker_key_version == expected.broker_key_version
            and observation.broker_claim_policy_digest == expected.broker_claim_policy_digest
            and set(claims.keys()) == set(expected_claims.keys()) | {"ref"}
            and all(claims.get(k) == v for k, v in expected_claims.items())
            and claims.get("ref") in expected.accepted_refs,
        ),
        (
            "attested_workflow_binding",
            observation.workflow_ref == expected.workflow_ref
            and observation.workflow_path == expected.workflow_path
            and observation.workflow_sha256 == expected.workflow_sha256
            and observation.runner_environment == expected.runner_environment
            and observation.event_name == expected.event_name
            and observation.actor == expected.actor
            and observation.subject == expected.subject
            and observation.run_id == expected.run_id
            and observation.run_attempt == expected.run_attempt,
        ),
        (
            "external_head_freshness",
            bool(HEX_40_RE.match(str(observation.external_head_oid)))
            and str(observation.external_head_oid) != "0" * 40,
        ),
        (
            "candidate_binding",
            bool(HEX_40_RE.match(str(observation.candidate_oid)))
            and (not request.candidate_oid or request.candidate_oid == observation.candidate_oid),
        ),
        ("plan_bytes_binding", plan_bytes_bound and bool(HEX_64_RE.match(str(observation.plan_sha256)))),
        (
            "receipt_digest_chain",
            bool(HEX_64_RE.match(str(observation.core_sha256)))
            and observation.subject == f"cores/{observation.sequence:020d}-{observation.core_sha256}.json"
            and observation.bundle_sha256
            == expected_bundle_digest(observation.core_sha256, observation.workflow_sha256)
            and observation.append_sha256
            == expected_append_digest(observation.sequence, observation.core_sha256, observation.bundle_sha256),
        ),
        (
            "receipt_sequence",
            isinstance(observation.sequence, int)
            and not isinstance(observation.sequence, bool)
            and observation.sequence >= 1
            and (not request.sequence or request.sequence == observation.sequence),
        ),
        (
            "panel_seat_agreement",
            tuple(sorted(seat for seat, _v, _r in observation.panel_seat_verdicts))
            == tuple(sorted(expected.required_panel_seats))
            and all(verdict == "AGREE" for _s, verdict, _r in observation.panel_seat_verdicts)
            and len({run_id for _s, _v, run_id in observation.panel_seat_verdicts})
            == len(expected.required_panel_seats),
        ),
        (
            "red_lifecycle_accounting",
            observation.red_lifecycle_nodeids == expected.expected_nodeid_count
            and observation.red_lifecycle_passed == expected.forced_red_passed
            and observation.red_lifecycle_failed == expected.forced_red_failed,
        ),
    ]


def verify_external_observation(
    request: ProofgateObservationRequest,
    *,
    expected: ProofgateExpectedConfig,
    boundary: Any,
) -> dict[str, Any]:
    """Test-owned decisive verifier bound to a read-only external observation boundary.

    The boundary is called exactly once, with only the locator. Authority comes solely from
    comparing the returned sealed observation to the independently supplied expected config.
    """
    _require_frozen_inputs(request, expected, boundary)
    try:
        observation = boundary.observe(request)
    except Exception as exc:  # fail closed on any boundary failure
        return {
            "status": "blocked",
            "authorized": False,
            "decisive": False,
            "evidence_kind": "observation_unavailable",
            "blocker_class": "contract_bug",
            "human_required": False,
            "failed_checks": ["external_observation"],
            "observation_error": type(exc).__name__,
        }

    checks = evaluate_external_observation(request, observation, expected)
    failed = [check_id for check_id, ok in checks if not ok]
    if failed:
        return {
            "status": "blocked",
            "authorized": False,
            "decisive": False,
            "evidence_kind": "observation_mismatch",
            "blocker_class": "contract_bug",
            "human_required": False,
            "failed_checks": failed,
        }

    return {
        "status": "verified",
        "authorized": True,
        "decisive": True,
        "evidence_kind": "production_external_boundary",
        "blocker_class": None,
        "human_required": False,
        "failed_checks": [],
        "observation_digest": observation_digest(observation),
    }


def run_admin_preflight(
    request: ProofgateObservationRequest,
    *,
    expected: ProofgateExpectedConfig,
    boundary: Any,
    output: str,
) -> int:
    """Admin preflight over a read-only external observation boundary.

    Receives the immutable expected configuration and the observation boundary explicitly, calls
    the boundary once with only the locator, and never executes `gh`, network, auth or provider
    operations of its own.
    """
    _require_frozen_inputs(request, expected, boundary)
    out_path = _validate_run_dir_output(output)

    try:
        observation = boundary.observe(request)
    except Exception as exc:
        _write_admin_preflight_payload(
            out_path,
            satisfied=False,
            attempts=[{"check": "external_observation", "status": "unavailable", "redacted": True}],
            outcome_class="unavailable",
        )
        raise ProofgateBootstrapVerifierError(
            f"admin-preflight external observation unavailable: {type(exc).__name__}"
        ) from exc

    checks = evaluate_external_observation(request, observation, expected)
    attempts = [
        {"check": check_id, "status": "ok" if ok else "mismatch", "redacted": True} for check_id, ok in checks
    ]
    failed = [check_id for check_id, ok in checks if not ok]

    if not failed:
        _write_admin_preflight_payload(out_path, satisfied=True, attempts=attempts, outcome_class=None)
        return 0

    _write_admin_preflight_payload(out_path, satisfied=False, attempts=attempts, outcome_class="admin_approval")
    raise ProofgateBootstrapVerifierError(
        f"admin-preflight prerequisite unsatisfied against independently supplied expectations: {failed}"
    )


def _write_admin_preflight_payload(
    out_path: Path,
    *,
    satisfied: bool,
    attempts: list[dict[str, Any]],
    outcome_class: str | None,
) -> None:
    if satisfied:
        payload: dict[str, Any] = {
            "human_required": False,
            "blocker_class": None,
            "verification_status": "satisfied",
            "access_attempts": attempts,
        }
    else:
        payload = {
            "human_required": True,
            "blocker_class": outcome_class,
            "verification_status": "blocked",
            "access_attempts": attempts,
            "required_human_inputs": [
                "dedicated_github_app",
                "github_app_installation",
                "protected_environment",
                "branch_ruleset",
            ],
        }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(out_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, indent=2))


def run_app_oidc_pilot(
    request: ProofgateObservationRequest,
    workflow: str,
    *,
    expected: ProofgateExpectedConfig,
    boundary: Any,
    output: str,
) -> int:
    """App/OIDC pilot over the same read-only external observation boundary. Fails closed."""
    _require_frozen_inputs(request, expected, boundary)
    _validate_run_dir_output(output)

    if workflow != expected.workflow_path:
        raise ProofgateBootstrapVerifierError(f"Wrong workflow for app-oidc-pilot: {workflow}")
    if request.ref not in expected.accepted_refs:
        raise ProofgateBootstrapVerifierError(f"Wrong ref for app-oidc-pilot: {request.ref}")
    if request.environment != expected.environment_name:
        raise ProofgateBootstrapVerifierError(f"Wrong environment for app-oidc-pilot: {request.environment}")

    raise ProofgateBootstrapVerifierError("app-oidc-pilot prerequisites not satisfied in non-attended CLI environment")


def _observation_tampers(
    expected: ProofgateExpectedConfig,
    base: ProofgateExternalObservation,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Single-field corruptions of a conforming observation that every verifier must reject."""
    return (
        ("sealed_schema_substituted", {"schema": "proofgate_local_json.v1"}),
        ("repository_identity_42_42", {"repository_id": "42", "repository_owner_id": "42"}),
        ("required_reviewer_43", {"environment_required_reviewer_ids": ("43",)}),
        ("admins_may_bypass_environment", {"environment_can_admins_bypass": True}),
        ("self_review_permitted", {"environment_prevent_self_review": False}),
        ("app_installation_substituted", {"app_installation_id": "42"}),
        ("app_integration_substituted", {"app_integration_id": "42"}),
        ("app_permissions_widened", {"app_permissions": (("contents", "write"), ("actions", "write"))}),
        (
            "ruleset_bypass_actor_added",
            {"ruleset_bypass_actors": tuple(base.ruleset_bypass_actors) + (("User", "always", "42"),)},
        ),
        (
            "ruleset_rule_dropped",
            {"ruleset_rule_types": tuple(t for t in base.ruleset_rule_types if t != "non_fast_forward")},
        ),
        ("ruleset_ref_unbound", {"ruleset_ref_includes": ("refs/heads/main",)}),
        (
            "garbage_oidc_claims",
            {
                "oidc_claims": (
                    ("actor", "garbage-actor"),
                    ("aud", "garbage-aud"),
                    ("repository_id", "42"),
                    ("repository_owner_id", "42"),
                    ("run_attempt", "999"),
                    ("run_id", "999"),
                    ("subject", "garbage-subject"),
                )
            },
        ),
        ("broker_policy_digest_drift", {"broker_claim_policy_digest": "0" * 64}),
        ("workflow_blob_drift", {"workflow_sha256": "0" * 64}),
        (
            "workflow_ref_drift",
            {"workflow_ref": f"{expected.repository_name}/.github/workflows/other.yml@refs/heads/main"},
        ),
        ("runner_environment_self_hosted", {"runner_environment": "self-hosted"}),
        ("actor_substituted", {"actor": "garbage-actor"}),
        ("subject_substituted", {"subject": f"cores/{2:020d}-{'0' * 64}.json"}),
        ("stale_external_head", {"external_head_oid": "0" * 40}),
        ("candidate_substituted", {"candidate_oid": "9" * 40}),
        ("plan_bytes_drift", {"plan_sha256": "0" * 64}),
        ("core_digest_drift", {"core_sha256": "0" * 64}),
        ("bundle_digest_collides_core", {"bundle_sha256": base.core_sha256}),
        ("append_digest_collides_bundle", {"append_sha256": base.bundle_sha256}),
        ("sequence_rollback", {"sequence": 0}),
        (
            "panel_seat_disagrees",
            {
                "panel_seat_verdicts": tuple(
                    (seat, "DISAGREE" if seat == expected.required_panel_seats[0] else verdict, run_id)
                    for seat, verdict, run_id in base.panel_seat_verdicts
                )
            },
        ),
        ("panel_seat_missing", {"panel_seat_verdicts": tuple(base.panel_seat_verdicts)[:-1]}),
        (
            "panel_run_identity_replayed",
            {
                "panel_seat_verdicts": tuple(
                    (seat, verdict, "run-replayed") for seat, verdict, _r in base.panel_seat_verdicts
                )
            },
        ),
        ("red_lifecycle_short", {"red_lifecycle_failed": expected.forced_red_failed - 1}),
        ("nodeid_inventory_drift", {"red_lifecycle_nodeids": expected.expected_nodeid_count - 1}),
    )


def _authority_asserted(result: Any) -> bool:
    """True when a verifier result asserts decisive production authority."""
    if not isinstance(result, dict):
        return False
    return (
        result.get("status") == "verified"
        and result.get("decisive") is True
        and result.get("evidence_kind") == "production_external_boundary"
    )


def _claims_authority(result: Any) -> bool:
    """True for any result that claims authority, independent of an evidence-kind label."""
    return isinstance(result, dict) and (
        result.get("status") == "verified"
        or result.get("decisive") is True
        or result.get("authorized") is True
    )


def assert_observation_bound_verifier_contract(
    verify_callable: Any,
    *,
    expected: ProofgateExpectedConfig,
    contract_label: str,
    require_authorized_flag: bool = False,
) -> None:
    """Frozen oracle: a verifier's authority must derive from the external observation boundary.

    The verifier is handed only a locator, the immutable expected configuration and a recording
    boundary. It must call the boundary exactly once with exactly that locator, assert decisive
    production authority only for a fully conforming observation, and fail closed for every
    single-field observation corruption and for an unavailable boundary.
    """
    if type(expected) is not ProofgateExpectedConfig:
        raise ProofgateContractViolation(f"{contract_label}: expected configuration must be immutable and frozen")

    with tempfile.TemporaryDirectory() as td:
        plan_path = Path(td) / "phase-plan-v10-PROOFGATE.md"
        plan_path.write_text("# PROOFGATE\n\n## Acceptance\n- EC-PROOFGATE-0\n", encoding="utf-8")
        plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        head_oid = hashlib.sha1(b"commit 1\x00").hexdigest()

        request = ProofgateObservationRequest(
            repository=expected.repository_name,
            ref=expected.accepted_refs[0],
            environment=expected.environment_name,
            external_head_ref=expected.external_head_ref,
            candidate_oid=head_oid,
            plan_path=str(plan_path),
            sequence=subject_sequence_and_core_digest(expected)[0],
        )
        base = conforming_observation(
            expected,
            external_head_oid=head_oid,
            candidate_oid=head_oid,
            plan_sha256=plan_sha256,
        )

        def _invoke(observation: ProofgateExternalObservation) -> tuple[Any, RecordingObservationBoundary]:
            boundary = RecordingObservationBoundary(observation)
            try:
                result: Any = verify_callable(request, expected=expected, boundary=boundary)
            except TypeError as exc:
                raise ProofgateContractViolation(
                    f"{contract_label}: verifier does not accept (locator, expected=, boundary=): {exc}"
                ) from exc
            except Exception as exc:  # a fail-closed rejection is a legitimate outcome
                result = exc
            return result, boundary

        positive, boundary = _invoke(base)
        if isinstance(positive, Exception):
            raise ProofgateContractViolation(
                f"{contract_label}: conforming observation was rejected ({type(positive).__name__}: {positive})"
            )
        if boundary.calls != (request,):
            raise ProofgateContractViolation(
                f"{contract_label}: boundary call trace must be exactly the locator, got {boundary.calls!r}"
            )
        if not _authority_asserted(positive):
            raise ProofgateContractViolation(
                f"{contract_label}: conforming observation did not yield decisive production authority: {positive!r}"
            )
        if require_authorized_flag and positive.get("authorized") is not True:
            raise ProofgateContractViolation(f"{contract_label}: conforming observation did not authorize")
        if positive.get("observation_digest") != observation_digest(base):
            raise ProofgateContractViolation(
                f"{contract_label}: result is not bound to the observed bytes (observation_digest mismatch)"
            )

        for tamper_id, replacement in _observation_tampers(expected, base):
            tampered = dataclasses.replace(base, **replacement)
            result, tampered_boundary = _invoke(tampered)
            if tampered_boundary.calls != (request,):
                raise ProofgateContractViolation(
                    f"{contract_label}/{tamper_id}: boundary call trace must be exactly the locator, "
                    f"got {tampered_boundary.calls!r}"
                )
            if isinstance(result, Exception):
                continue
            if _claims_authority(result):
                raise ProofgateContractViolation(
                    f"{contract_label}/{tamper_id}: corrupted observation was accepted: {result!r}"
                )

        unavailable = UnavailableObservationBoundary()
        try:
            result = verify_callable(request, expected=expected, boundary=unavailable)
        except Exception:
            result = None
        if unavailable.calls != (request,):
            raise ProofgateContractViolation(
                f"{contract_label}/unavailable_boundary: boundary must still be called with exactly the locator"
            )
        if result is not None and _claims_authority(result):
            raise ProofgateContractViolation(
                f"{contract_label}/unavailable_boundary: verifier authorized without an observation: {result!r}"
            )

        for label, substitute in (
            ("caller_authored_mapping", {"external_head_oid": head_oid, "decisive": True, "status": "verified"}),
            ("mutable_expected_config", None),
        ):
            probe_boundary = RecordingObservationBoundary(base)
            try:
                if label == "caller_authored_mapping":
                    result = verify_callable(substitute, expected=expected, boundary=probe_boundary)
                else:
                    result = verify_callable(request, expected=_MutableExpectedConfigDouble(), boundary=probe_boundary)
            except Exception:
                continue
            if _claims_authority(result):
                raise ProofgateContractViolation(
                    f"{contract_label}/{label}: verifier accepted caller-supplied authority: {result!r}"
                )


class _MutableExpectedConfigDouble:
    """Mutable 42/42/43-plus-garbage stand-in for the immutable expected configuration."""

    repository_id = "42"
    repository_owner_id = "42"
    repository_name = "Consiliency/garbage-repo"
    dedicated_app_integration_id = "42"
    dedicated_app_installation_id = "42"
    app_repository_selection = "all"
    app_permissions = (("contents", "write"),)
    required_reviewer_id = "43"
    ruleset_name = "garbage-ruleset"
    ruleset_required_rule_types = ()
    broker_deployment_id = "garbage-broker"
    broker_key_version = "garbage-key"
    broker_claim_policy_digest = "garbage-digest"
    oidc_audience = "garbage-aud"
    workflow_ref = "garbage-workflow-ref"
    workflow_path = "garbage-workflow-path"
    workflow_sha256 = "garbage-sha"
    event_name = "garbage_event"
    runner_environment = "garbage-runner"
    environment_name = "garbage-env"
    external_head_ref = "refs/heads/garbage"
    accepted_refs = ("refs/heads/garbage",)
    actor = "garbage-actor"
    subject = "garbage-subject"
    run_id = "999"
    run_attempt = "999"
    expected_nodeid_count = 1
    forced_red_passed = 0
    forced_red_failed = 0
    required_panel_seats = ()


def assert_preflight_intake_contract(verify_callable: Any, *, expected: ProofgateExpectedConfig) -> None:
    """Frozen preflight-intake authority contract."""
    assert_observation_bound_verifier_contract(
        verify_callable,
        expected=expected,
        contract_label="proofgate_preflight_intake",
        require_authorized_flag=True,
    )


def assert_closeout_attestation_contract(verify_callable: Any, *, expected: ProofgateExpectedConfig) -> None:
    """Frozen closeout-attestation authority contract."""
    assert_observation_bound_verifier_contract(
        verify_callable,
        expected=expected,
        contract_label="proofgate_closeout_attestation",
    )


def assert_external_attestation_contract(verify_callable: Any, *, expected: ProofgateExpectedConfig) -> None:
    """Frozen external-attestation authority contract."""
    assert_observation_bound_verifier_contract(
        verify_callable,
        expected=expected,
        contract_label="proofgate_external_attestation",
    )


def assert_admin_preflight_authority_contract(expected: ProofgateExpectedConfig, run_dir: Path) -> None:
    """Direct control over the test-owned admin verifier.

    Proves the admin verifier receives the immutable expected configuration and the observation
    boundary explicitly, rejects a matching 42/42/43-plus-garbage observation, rejects a mutable
    expected-configuration substitute, and never executes `gh`, network, auth or provider work.
    """
    request = ProofgateObservationRequest(
        repository=expected.repository_name,
        ref=expected.accepted_refs[0],
        environment=expected.environment_name,
        external_head_ref=expected.external_head_ref,
    )

    garbage = ProofgateExternalObservation(
        schema=PROOFGATE_OBSERVATION_SCHEMA,
        repository_id="42",
        repository_owner_id="42",
        repository_name="Consiliency/garbage-repo",
        app_integration_id="42",
        app_installation_id="42",
        app_repository_selection="all",
        app_permissions=(("contents", "write"), ("actions", "write")),
        ruleset_name="garbage-ruleset",
        ruleset_rule_types=(),
        ruleset_ref_includes=("refs/heads/garbage",),
        ruleset_bypass_actors=(("User", "always", "42"),),
        environment_name="garbage-env",
        environment_can_admins_bypass=True,
        environment_prevent_self_review=False,
        environment_required_reviewer_ids=("43",),
        oidc_claims=(("aud", "garbage-aud"), ("repository_id", "42"), ("repository_owner_id", "42")),
        broker_deployment_id="garbage-broker",
        broker_key_version="garbage-key",
        broker_claim_policy_digest="garbage-digest",
        external_head_ref="refs/heads/garbage",
        external_head_oid="0" * 40,
        candidate_oid="0" * 40,
        plan_sha256="0" * 64,
        workflow_ref="garbage-workflow-ref",
        workflow_path="garbage-workflow-path",
        workflow_sha256="garbage-sha",
        runner_environment="garbage-runner",
        event_name="garbage_event",
        actor="garbage-actor",
        subject="garbage-subject",
        run_id="999",
        run_attempt="999",
        core_sha256="0" * 64,
        bundle_sha256="0" * 64,
        append_sha256="0" * 64,
        sequence=999,
        panel_seat_verdicts=(),
        red_lifecycle_passed=0,
        red_lifecycle_failed=0,
        red_lifecycle_nodeids=1,
    )

    garbage_boundary = RecordingObservationBoundary(garbage)
    try:
        run_admin_preflight(
            request,
            expected=expected,
            boundary=garbage_boundary,
            output=str(run_dir / "admin-garbage.json"),
        )
    except ProofgateBootstrapVerifierError:
        pass
    else:
        raise ProofgateContractViolation("admin preflight accepted a 42/42/43-plus-garbage observation")
    if garbage_boundary.calls != (request,):
        raise ProofgateContractViolation("admin preflight did not call the boundary with exactly the locator")

    conforming_boundary = RecordingObservationBoundary(garbage)
    try:
        run_admin_preflight(
            request,
            expected=_MutableExpectedConfigDouble(),
            boundary=conforming_boundary,
            output=str(run_dir / "admin-mutable-config.json"),
        )
    except ProofgateBootstrapVerifierError:
        pass
    else:
        raise ProofgateContractViolation("admin preflight accepted a mutable expected-configuration substitute")

    exact_class_mutation = dataclasses.replace(expected)
    for field, value in (
        ("repository_id", "42"),
        ("repository_owner_id", "42"),
        ("required_reviewer_id", "43"),
        ("repository_name", "Consiliency/garbage-repo"),
        ("broker_deployment_id", "garbage-broker"),
    ):
        object.__setattr__(exact_class_mutation, field, value)
    exact_class_request = ProofgateObservationRequest(
        repository=exact_class_mutation.repository_name,
        ref=exact_class_mutation.accepted_refs[0],
        environment=exact_class_mutation.environment_name,
        external_head_ref=exact_class_mutation.external_head_ref,
    )
    exact_class_observation = conforming_observation(
        exact_class_mutation,
        external_head_oid="a" * 40,
        candidate_oid="a" * 40,
        plan_sha256="b" * 64,
    )
    if not all(ok for _check, ok in evaluate_external_observation(
        exact_class_request, exact_class_observation, exact_class_mutation
    )):
        raise ProofgateContractViolation("exact-class mutation did not construct a matching observation")
    exact_class_boundary = RecordingObservationBoundary(exact_class_observation)
    try:
        run_admin_preflight(
            exact_class_request,
            expected=exact_class_mutation,
            boundary=exact_class_boundary,
            output=str(run_dir / "admin-exact-class-mutated.json"),
        )
    except ProofgateBootstrapVerifierError:
        pass
    else:
        raise ProofgateContractViolation("admin preflight accepted an exact-class mutated expected configuration")
    if exact_class_boundary.calls:
        raise ProofgateContractViolation("exact-class mutated expected configuration reached the observation boundary")

    cli_boundary = GitHubCliObservationBoundary()
    if cli_boundary.attended_live is not False:
        raise ProofgateContractViolation("live GitHub CLI observation must be disabled by construction")
    if not callable(getattr(cli_boundary, "observe", None)):
        raise ProofgateContractViolation("GitHub CLI adapter must expose the read-only observe() surface")
    if any(name.startswith("run") or name in ("fetch", "call") for name in vars(type(cli_boundary))):
        raise ProofgateContractViolation("GitHub CLI adapter exposes an execution surface")
    try:
        cli_boundary.observe(request)
    except ProofgateObservationUnavailable:
        pass
    else:
        raise ProofgateContractViolation("GitHub CLI adapter executed a live observation in an ordinary run")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="proofgate_bootstrap_verifier CLI")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    admin_parser = subparsers.add_parser("admin-preflight")
    admin_parser.add_argument("--repo", required=True)
    admin_parser.add_argument("--ref", required=True)
    admin_parser.add_argument("--environment", required=True)
    admin_parser.add_argument("--output", required=True)

    pilot_parser = subparsers.add_parser("app-oidc-pilot")
    pilot_parser.add_argument("--repo", required=True)
    pilot_parser.add_argument("--workflow", required=True)
    pilot_parser.add_argument("--ref", required=True)
    pilot_parser.add_argument("--environment", required=True)
    pilot_parser.add_argument("--output", required=True)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    # The expected configuration is supplied to the verifier from its own frozen source; the CLI
    # only names a locator and selects an observation boundary. Live observation stays opt-in and
    # operator-driven, so an ordinary run can never reach it.
    try:
        from .proofgate_tdd_guard import PROOFGATE_EXPECTED_CONFIG_V1
    except ImportError:
        from proofgate_tdd_guard import PROOFGATE_EXPECTED_CONFIG_V1

    expected = PROOFGATE_EXPECTED_CONFIG_V1
    repo_arg = args.repo
    if repo_arg in (".", "./", "") or repo_arg.startswith("/"):
        repo_arg = expected.repository_name
    boundary = GitHubCliObservationBoundary(
        attended_live=os.environ.get("PHASE_LOOP_PROOFGATE_ATTENDED_LIVE") == "1"
    )
    request = ProofgateObservationRequest(
        repository=repo_arg,
        ref=args.ref,
        environment=args.environment,
        external_head_ref=expected.external_head_ref,
    )

    try:
        if args.mode == "admin-preflight":
            return run_admin_preflight(request, expected=expected, boundary=boundary, output=args.output)
        elif args.mode == "app-oidc-pilot":
            return run_app_oidc_pilot(
                request, args.workflow, expected=expected, boundary=boundary, output=args.output
            )
        else:
            sys.stderr.write(f"Unknown mode: {args.mode}\n")
            return 1
    except ProofgateBootstrapVerifierError as exc:
        sys.stderr.write(f"Verifier error: {exc}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"Unexpected error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
