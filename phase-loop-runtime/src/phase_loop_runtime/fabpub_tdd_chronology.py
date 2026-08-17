"""FABPUB (v10) TDD chronology + evidence reducer — SL-0, immutable.

Stdlib-only, and deliberately independent of every production module FABPUB
changes: it imports NO ``phase_loop_runtime.convergence``, ``publishing``,
``train_runner``, ``cli``, or ``fabpub_capability`` symbol.  The frozen
inventories come from ``phase-loop-runtime/tests/_fabpub_tdd_guard.py``, loaded
BY FILE PATH (never as a package import), so this reducer can audit the guard's
own digest.

Modes
-----
``--mode tests-only``
    Audit the SL-0 boundary: the guard/test-tree digests, the four inline
    canonical vectors, the frozen nodeid inventories and their counts, the
    ownership/test-path inventories, the ``B -> T`` git topology, and the
    activated-RED plus default-green JUnit evidence.

    These are **mandatory** (Consiliency/agent-harness#578 F2).  An unstamped
    ``B``/``T``, a missing RED or default JUnit artifact, a missing RED raw log,
    or an activated exit code that is not exactly ``1`` is a reduction FAILURE —
    never a silently skipped section.  This reducer is SL-0-owned and immutable
    after merge, so a fail-open gate here could not be repaired in SL-1..SL-4.

``--mode final-junit``
    Reduce BOTH required pass gates (Consiliency/agent-harness#578 F5): the
    PREACTIVATION run (activated, marker still absent — plan:323) and the FINAL
    run (unactivated, marker installed — plan:326).  Each requires every expected
    nodeid present once, active and passing, zero phase skips / errors / xfails,
    zero failures OUTSIDE ``FABPUB_EXPECTED_NODEIDS``, and JUnit totals that
    corroborate the reduction.  It also binds the required legacy-cutover /
    writer-generation and shared adapter-start-owner evidence records.

``--mode final``
    ``tests-only`` plus ``final-junit`` plus the full
    ``B -> T -> I -> P -> C -> M -> H -> L`` lifecycle audit.

Every SHA the reducer trusts arrives through runner-stamped metadata (explicit
CLI flags or the exact frozen environment names below) — never a moving ref, a
``git log`` scrape, or a self-reported current head.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

GUARD_RELATIVE_PATH = "phase-loop-runtime/tests/_fabpub_tdd_guard.py"
FALSIFIER_RELATIVE_PATH = "phase-loop-runtime/tests/test_fabpub_shared_epoch.py"
CHRONOLOGY_RELATIVE_PATH = (
    "phase-loop-runtime/src/phase_loop_runtime/fabpub_tdd_chronology.py"
)
MARKER_RELATIVE_PATH = "phase-loop-runtime/src/phase_loop_runtime/fabpub_capability.py"
PLAN_RELATIVE_PATH = "plans/phase-plan-v10-FABPUB.md"
ROADMAP_RELATIVE_PATH = "specs/phase-plans-v10.md"

#: Exact frozen environment names for runner-stamped lifecycle metadata.
LIFECYCLE_ENV = {
    "B": "FABPUB_PREIMPLEMENTATION_BASE_SHA",
    "T": "FABPUB_TESTS_ONLY_COMMIT_SHA",
    "I": "FABPUB_IMPLEMENTATION_BASE_SHA",
    "P": "FABPUB_FIRST_PRODUCTION_COMMIT_SHA",
    "C": "FABPUB_PREACTIVATION_HEAD_SHA",
    "M": "FABPUB_MARKER_COMMIT_SHA",
    "H": "FABPUB_CANDIDATE_HEAD_SHA",
    "L": "FABPUB_LANDED_SHA",
}

EVIDENCE_ENV = {
    "red_junit": "FABPUB_RED_JUNIT",
    "red_raw_log": "FABPUB_RED_RAW_LOG",
    "red_invocation": "FABPUB_RED_INVOCATION",
    "red_exit_code": "FABPUB_RED_EXIT_CODE",
    "default_junit": "FABPUB_DEFAULT_JUNIT",
    "default_invocation": "FABPUB_DEFAULT_INVOCATION",
    "preactivation_junit": "FABPUB_PREACTIVATION_JUNIT",
    "preactivation_invocation": "FABPUB_PREACTIVATION_INVOCATION",
    "final_junit": "FABPUB_FINAL_JUNIT",
    "final_invocation": "FABPUB_FINAL_INVOCATION",
    "cutover_evidence": "FABPUB_LEGACY_CUTOVER_EVIDENCE",
    "cutover_evidence_sha256": "FABPUB_LEGACY_CUTOVER_EVIDENCE_SHA256",
    "start_owner_evidence": "FABPUB_START_OWNER_EVIDENCE",
    "start_owner_evidence_sha256": "FABPUB_START_OWNER_EVIDENCE_SHA256",
    "test_panel_record": "FABPUB_TEST_PANEL_RECORD",
    "test_panel_record_sha256": "FABPUB_TEST_PANEL_RECORD_SHA256",
    "predecessor_inventory": "FABPUB_SUPERSEDED_BASELINE_INVENTORY",
}
FABPUB_ACTIVATION_ASSIGNMENT = "PHASE_LOOP_TDD_EXPECT_FABPUB=1"

#: The four inline canonical vectors and the guard constant each one freezes.
VECTOR_BINDINGS = {
    "FABPUB_REPOSITORY_IDENTITY_VECTOR": "FABPUB_REPOSITORY_IDENTITY_VECTOR_SHA256",
    "FABPUB_IDENTITY_VECTOR": "FABPUB_IDENTITY_VECTOR_SHA256",
    "FABPUB_COMMIT_OBJECT_VECTOR": "FABPUB_COMMIT_OBJECT_VECTOR_SHA256",
    "FABPUB_LEGACY_CUTOVER_VECTOR": "FABPUB_LEGACY_CUTOVER_VECTOR_SHA256",
}


class ChronologyError(Exception):
    """A reduction failure — always fatal, never downgraded to a warning."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_guard(repo: Path):
    """Load the frozen guard BY FILE PATH (never as an installed package)."""
    guard_path = repo / GUARD_RELATIVE_PATH
    if not guard_path.is_file():
        raise ChronologyError(f"frozen guard is missing: {GUARD_RELATIVE_PATH}")
    spec = importlib.util.spec_from_file_location("_fabpub_tdd_guard_reducer", guard_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ChronologyError(f"frozen guard is not loadable: {GUARD_RELATIVE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory_digest(values) -> str:
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode("utf-8")).hexdigest()


def canonical_vector_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


#: Members of ``PublishPreTrailerIntent.v1`` that are DERIVED from the literal
#: original-message bytes rather than declared (Consiliency/agent-harness#578
#: round 3, item 2).  The reducer re-derives them from the message literal itself,
#: so it never trusts a caller-supplied length or digest.
MESSAGE_DERIVED_MEMBERS = ("original_commit_message_length", "original_commit_message_sha256")
IDENTITY_MESSAGE_LITERAL = "FABPUB_IDENTITY_ORIGINAL_MESSAGE"


def extract_literal_vectors(path: Path) -> dict[str, Any]:
    """Parse the falsifier module's inline vector literals with ``ast`` only.

    The identity vector's message-derived members are re-derived here from the
    literal ``FABPUB_IDENTITY_ORIGINAL_MESSAGE`` bytes, matching how the test
    module computes them.  A vector that declared them opaquely would therefore
    disagree with this reduction.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, Any] = {}
    message: bytes | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id in VECTOR_BINDINGS:
            found[target.id] = ast.literal_eval(node.value)
        elif target.id == IDENTITY_MESSAGE_LITERAL:
            message = ast.literal_eval(node.value)

    identity = found.get("FABPUB_IDENTITY_VECTOR")
    if isinstance(identity, dict) and set(MESSAGE_DERIVED_MEMBERS) <= set(identity):
        if message is None:
            raise ChronologyError(
                f"{IDENTITY_MESSAGE_LITERAL} is absent; the identity vector's message-derived "
                "members cannot be independently re-derived"
            )
        identity["original_commit_message_length"] = len(message)
        identity["original_commit_message_sha256"] = hashlib.sha256(message).hexdigest()
    return found


# ---------------------------------------------------------------------------
# Git (read-only, runner-stamped SHAs only)
# ---------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60
    )
    if completed.returncode != 0:
        raise ChronologyError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def blob_sha(repo: Path, rev: str, relative: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{rev}:{relative}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


# ---------------------------------------------------------------------------
# JUnit reduction
# ---------------------------------------------------------------------------


def _nodeid_from_testcase(repo: Path, testcase: ET.Element) -> str | None:
    """Rebuild a repo-relative nodeid from ``classname``/``name``.

    ``classname`` is the dotted module path plus any class nesting, so the module
    boundary is the longest dotted prefix that resolves to a real file under
    ``phase-loop-runtime/``.
    """
    classname = testcase.get("classname") or ""
    name = testcase.get("name") or ""
    if not classname or not name:
        return None
    parts = classname.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = "phase-loop-runtime/" + "/".join(parts[:cut]) + ".py"
        if (repo / candidate).is_file():
            trailing = parts[cut:]
            return "::".join([candidate, *trailing, name])
    return None


def reduce_junit(repo: Path, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ChronologyError(f"JUnit artifact is missing: {path}")
    root = ET.parse(path).getroot()
    passed: set[str] = set()
    failed: dict[str, str] = {}
    skipped: set[str] = set()
    errored: set[str] = set()
    duplicates: list[str] = []
    seen: set[str] = set()
    xfails: list[str] = []

    unresolved: list[dict[str, str]] = []
    for testcase in root.iter("testcase"):
        nodeid = _nodeid_from_testcase(repo, testcase)
        if nodeid is None:
            # pytest emits collection-level records (module skips) with an EMPTY
            # classname; they carry no nodeid but they DO count toward the suite
            # totals.  Track them explicitly so the totals comparison stays exact
            # instead of reporting phantom drift (Consiliency/agent-harness#578 F-C3).
            unresolved.append(
                {
                    "classname": testcase.get("classname") or "",
                    "name": testcase.get("name") or "",
                    "outcome": (
                        "error"
                        if testcase.find("error") is not None
                        else "failure"
                        if testcase.find("failure") is not None
                        else "skipped"
                        if testcase.find("skipped") is not None
                        else "passed"
                    ),
                }
            )
            continue
        if nodeid in seen:
            duplicates.append(nodeid)
        seen.add(nodeid)
        failure = testcase.find("failure")
        error = testcase.find("error")
        skip = testcase.find("skipped")
        if error is not None:
            errored.add(nodeid)
        elif failure is not None:
            message = (failure.get("message") or "") + "\n" + (failure.text or "")
            failed[nodeid] = message
        elif skip is not None:
            reason = (skip.get("message") or "") + (skip.get("type") or "")
            if "xfail" in reason.lower():
                xfails.append(nodeid)
            skipped.add(nodeid)
        else:
            passed.add(nodeid)

    # Suite-level totals as the JUnit document itself reports them.  Comparing the
    # reduced counts against these catches drift the per-nodeid audits cannot see:
    # a truncated document, a silently dropped module, or an extra suite.
    declared = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in root.iter("testsuite"):
        for key in declared:
            try:
                declared[key] += int(suite.get(key) or 0)
            except ValueError:  # pragma: no cover - malformed attribute
                pass

    return {
        "artifact": str(path),
        "artifact_sha256": sha256_file(path),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errored": errored,
        "duplicates": duplicates,
        "xfails": xfails,
        "declared_totals": declared,
        "resolved_total": len(seen),
        "unresolved": unresolved,
        "unresolved_total": len(unresolved),
    }


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------


def _predecessor_inventory_evidence(path: Path | None, guard) -> tuple[set[str], dict[str, Any], list[str]]:
    """Load runner-stamped predecessor nodeids for the mandatory ``+12`` delta."""
    errors: list[str] = []
    report: dict[str, Any] = {"artifact": str(path) if path else None}
    if path is None:
        return set(), report, [
            "the cumulative nodeid delta requires runner-stamped predecessor inventory evidence"
        ]
    if not path.is_file():
        return set(), report, [f"the predecessor inventory evidence is missing: {path}"]
    report["artifact_sha256"] = sha256_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return set(), report, [f"the predecessor inventory evidence is unreadable: {exc}"]
    if not isinstance(payload, dict):
        return set(), report, ["the predecessor inventory evidence must be a JSON object"]
    if payload.get("schema") != getattr(guard, "FABPUB_PREDECESSOR_INVENTORY_SCHEMA", None):
        errors.append("the predecessor inventory evidence schema is not the frozen schema")
    nodeids = payload.get("nodeids")
    if not isinstance(nodeids, list) or not all(isinstance(nodeid, str) and nodeid for nodeid in nodeids):
        errors.append("the predecessor inventory evidence must carry a non-empty nodeids list")
        return set(), report, errors
    predecessor = set(nodeids)
    if len(predecessor) != len(nodeids):
        errors.append("the predecessor inventory evidence contains duplicate nodeids")
    digest = inventory_digest(predecessor)
    report.update({"nodeid_count": len(predecessor), "nodeids_sha256": digest})
    if digest != getattr(guard, "FABPUB_SUPERSEDED_BASELINE_INVENTORY_SHA256", None):
        errors.append("the predecessor inventory digest does not match the frozen superseded digest")
    return predecessor, report, errors


def audit_frozen_inventories(repo: Path, guard, predecessor_inventory: Path | None) -> dict[str, Any]:
    errors: list[str] = []

    new = set(guard.FABPUB_NEW_PRODUCTION_NODEIDS)
    migrated = set(guard.FABPUB_MIGRATED_NODEIDS)
    if new & migrated:
        errors.append("new and migrated nodeid inventories overlap")
    if set(guard.FABPUB_RED_NODEIDS) != new | migrated:
        errors.append("FABPUB_RED_NODEIDS is not the union of the new and migrated sets")
    if set(guard.FABPUB_EXPECTED_NODEIDS) != set(guard.FABPUB_RED_NODEIDS):
        errors.append("FABPUB_EXPECTED_NODEIDS drifted from FABPUB_RED_NODEIDS")
    if guard.FABPUB_DEFAULT_SKIP_COUNT != len(new):
        errors.append("default_skip_count != len(FABPUB_NEW_PRODUCTION_NODEIDS)")

    anchors = [guard.FABPUB_RED_ANCHORS.get(n) for n in guard.FABPUB_RED_NODEIDS]
    if any(a is None for a in anchors):
        errors.append("a RED nodeid has no frozen anchor")
    elif len(set(anchors)) != len(anchors):
        errors.append("RED anchors are not unique")
    if set(guard.FABPUB_RED_ANCHORS) != set(guard.FABPUB_RED_NODEIDS):
        errors.append("the anchor map and the RED inventory disagree")

    expected_sub = {
        "identity": (guard.FABPUB_IDENTITY_NODEIDS, 2, guard.FABPUB_IDENTITY_NODEIDS_SHA256),
        "shared_allocator": (
            guard.FABPUB_SHARED_ALLOCATOR_NODEIDS,
            2,
            guard.FABPUB_SHARED_ALLOCATOR_NODEIDS_SHA256,
        ),
        "adapter_start_fence": (
            guard.FABPUB_ADAPTER_START_FENCE_NODEIDS,
            1,
            guard.FABPUB_ADAPTER_START_FENCE_NODEIDS_SHA256,
        ),
        "writer_generation_fence": (
            guard.FABPUB_WRITER_GENERATION_FENCE_NODEIDS,
            1,
            guard.FABPUB_WRITER_GENERATION_FENCE_NODEIDS_SHA256,
        ),
        "legacy_cutover": (
            guard.FABPUB_LEGACY_CUTOVER_NODEIDS,
            8,
            guard.FABPUB_LEGACY_CUTOVER_NODEIDS_SHA256,
        ),
        "run_train_recovery": (guard.FABPUB_RUN_TRAIN_RECOVERY_NODEIDS, 1, None),
    }
    for label, (inventory, count, digest) in expected_sub.items():
        if len(inventory) != count or len(set(inventory)) != count:
            errors.append(f"{label} inventory is not exactly {count} unique nodeids")
        if not set(inventory) <= new:
            errors.append(f"{label} inventory is not a subset of the new-production set")
        if digest is not None and inventory_digest(inventory) != digest:
            errors.append(f"{label} inventory digest drifted")

    # The sub-inventory sizes remain useful structural checks, but they are never
    # evidence for the predecessor-relative delta.
    contributions = dict(getattr(guard, "FABPUB_FROZEN_SUBINVENTORY_CONTRIBUTIONS", {}))
    expected_contributions = {
        "shared_allocator": 2,
        "adapter_start_fence": 1,
        "writer_generation_fence": 1,
        "legacy_cutover": 8,
    }
    if contributions != expected_contributions:
        errors.append("the frozen sub-inventory contributions drifted from the plan")
    if getattr(guard, "FABPUB_FROZEN_SUBINVENTORY_TOTAL", None) != 12:
        errors.append("the frozen sub-inventory contributions do not total 12")
    predecessor, predecessor_report, predecessor_errors = _predecessor_inventory_evidence(
        predecessor_inventory, guard
    )
    errors.extend(predecessor_errors)
    candidate_new = set(guard.FABPUB_NEW_PRODUCTION_NODEIDS)
    added = candidate_new - predecessor
    removed = predecessor - candidate_new
    required_delta = getattr(guard, "FABPUB_REQUIRED_NEW_NODEID_DELTA", None)
    if not isinstance(required_delta, int) or required_delta < 0:
        errors.append("the frozen predecessor-relative nodeid delta is invalid")
    elif predecessor and (removed or len(added) != required_delta):
        errors.append(
            "candidate new-production inventory is not the frozen predecessor inventory plus "
            f"exactly {required_delta} nodeids; added={len(added)} removed={len(removed)}"
        )

    if len(guard.FABPUB_OWNED_PATHS) != 25:
        errors.append("the execution-owned write set is not exactly 25 paths")
    if len(guard.FABPUB_TEST_PATHS) != 12:
        errors.append("the test inventory is not exactly 12 paths")
    if inventory_digest(guard.FABPUB_OWNED_PATHS) != guard.FABPUB_OWNED_PATHS_SHA256:
        errors.append("ownership inventory digest drifted")
    if inventory_digest(guard.FABPUB_TEST_PATHS) != guard.FABPUB_TEST_PATHS_SHA256:
        errors.append("test-path inventory digest drifted")

    return {
        "new_production_count": len(new),
        "migrated_count": len(migrated),
        "red_count": len(guard.FABPUB_RED_NODEIDS),
        "sl2_red_count": len(guard.FABPUB_SL2_RED_NODEIDS),
        "expected_count": len(guard.FABPUB_EXPECTED_NODEIDS),
        "default_skip_count": guard.FABPUB_DEFAULT_SKIP_COUNT,
        "owned_paths_sha256": guard.FABPUB_OWNED_PATHS_SHA256,
        "test_paths_sha256": guard.FABPUB_TEST_PATHS_SHA256,
        "frozen_subinventory_contributions": contributions,
        "predecessor_inventory": predecessor_report,
        "required_new_nodeid_delta": required_delta,
        "added_nodeids": sorted(added),
        "removed_nodeids": sorted(removed),
        "errors": errors,
    }


def audit_vectors(repo: Path, guard) -> dict[str, Any]:
    errors: list[str] = []
    falsifier = repo / FALSIFIER_RELATIVE_PATH
    if not falsifier.is_file():
        raise ChronologyError(f"frozen falsifier module is missing: {FALSIFIER_RELATIVE_PATH}")
    literals = extract_literal_vectors(falsifier)
    recomputed: dict[str, str] = {}
    for vector_name, guard_constant in VECTOR_BINDINGS.items():
        if vector_name not in literals:
            errors.append(f"inline vector {vector_name} is missing from the falsifier module")
            continue
        digest = canonical_vector_digest(literals[vector_name])
        recomputed[guard_constant] = digest
        if digest != getattr(guard, guard_constant):
            errors.append(f"{guard_constant} does not match its inline vector")

    identity = literals.get("FABPUB_IDENTITY_VECTOR", {})
    forbidden = {
        "transaction_id",
        "final_commit_message_sha256",
        "expected_commit_oid",
        "committed_head_sha",
        "final_commit_object_sha256",
    }
    if forbidden & set(identity):
        errors.append("PublishPreTrailerIntent.v1 vector carries a self- or post-object field")

    return {"recomputed": recomputed, "errors": errors}


def audit_test_tree(repo: Path, guard) -> dict[str, Any]:
    errors: list[str] = []
    entries: list[str] = []
    for relative in guard.FABPUB_TEST_PATHS:
        path = repo / relative
        if not path.is_file():
            errors.append(f"frozen test path is missing: {relative}")
            continue
        entries.append(f"{relative}\0{sha256_file(path)}")
    chronology = repo / CHRONOLOGY_RELATIVE_PATH
    if not chronology.is_file():
        errors.append(f"chronology reducer is missing: {CHRONOLOGY_RELATIVE_PATH}")
    return {
        "test_tree_sha256": inventory_digest(entries) if not errors else None,
        "guard_sha256": sha256_file(repo / GUARD_RELATIVE_PATH),
        "chronology_sha256": sha256_file(chronology) if chronology.is_file() else None,
        "errors": errors,
    }


def audit_plan_manifest_binding(repo: Path, guard) -> dict[str, Any]:
    """Cross-check the guard's frozen inventories against ``plans/manifest.json``.

    The manifest is the planning registry (never an execution-owned lane path), so
    agreement between it and the test-owned guard is an INDEPENDENT check that the
    frozen nodeid/ownership inventories did not drift from the ratified plan.
    """
    manifest_path = repo / "plans" / "manifest.json"
    if not manifest_path.is_file():
        # The manifest is the ONLY independent corroboration of the frozen
        # inventories; its absence is a failure, never a skipped section
        # (Consiliency/agent-harness#578 F-O2).
        return {
            "evaluated": False,
            "reason": "plans/manifest.json is absent",
            "errors": [
                "plans/manifest.json is required as the independent inventory binding; "
                "refusing to pass without it"
            ],
        }

    errors: list[str] = []
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = [e for e in payload.get("plans", []) if e.get("file") == PLAN_RELATIVE_PATH]
    if len(rows) != 1:
        return {"evaluated": True, "errors": ["plans/manifest.json has no unique FABPUB row"]}

    lifecycle = rows[0].get("lifecycle") or []
    if not lifecycle:
        return {"evaluated": True, "errors": ["the FABPUB manifest row has no lifecycle entries"]}
    original = lifecycle[0].get("metadata", {}).get("fabpub_plan_contract", {})
    rebinds = [
        event.get("metadata", {}).get("fabpub_plan_contract_rebind", {})
        for event in lifecycle
    ]
    contract_sources = [*reversed([item for item in rebinds if item]), original]

    def source(name: str):
        return next((item[name] for item in contract_sources if name in item), None)

    for field, relative in (
        ("plan_sha256", PLAN_RELATIVE_PATH),
        ("roadmap_sha256", ROADMAP_RELATIVE_PATH),
    ):
        declared = source(field)
        path = repo / relative
        if not path.is_file():
            errors.append(f"{relative} is missing")
        elif declared != sha256_file(path):
            errors.append(f"{field} does not match {relative}")

    bindings = {
        "owned_paths": guard.FABPUB_OWNED_PATHS,
        "test_paths": guard.FABPUB_TEST_PATHS,
        "shared_allocator_nodeids": guard.FABPUB_SHARED_ALLOCATOR_NODEIDS,
        "legacy_cutover_nodeids": guard.FABPUB_LEGACY_CUTOVER_NODEIDS,
        "adapter_start_fence_nodeids": guard.FABPUB_ADAPTER_START_FENCE_NODEIDS,
        "writer_generation_fence_nodeids": guard.FABPUB_WRITER_GENERATION_FENCE_NODEIDS,
    }
    for name, frozen in bindings.items():
        declared = source(name)
        if declared is None:
            errors.append(f"the manifest declares no {name} inventory")
            continue
        if sorted(declared) != sorted(frozen):
            errors.append(f"{name} drifted between the plan manifest and the frozen guard")
        if source(f"{name}_sha256") not in (None, inventory_digest(frozen)):
            errors.append(f"{name}_sha256 drifted between the plan manifest and the frozen guard")

    return {"evaluated": True, "record_id": source("plan_sha256"), "errors": errors}


def audit_digest_bound_artifact(
    path: Path | None, expected_sha256: str | None, *, label: str
) -> dict[str, Any]:
    errors: list[str] = []
    if path is None:
        errors.append(f"the {label} artifact was not runner-stamped")
        return {"evaluated": False, "errors": errors}
    if not path.is_file():
        errors.append(f"the stamped {label} artifact is missing: {path}")
        return {"evaluated": False, "artifact": str(path), "errors": errors}
    actual = sha256_file(path)
    if expected_sha256 is None:
        errors.append(f"the {label} expected SHA-256 was not runner-stamped")
    elif not _is_digest(expected_sha256):
        errors.append(f"the {label} expected SHA-256 is not a 64-hex digest")
    elif actual != expected_sha256:
        errors.append(f"the {label} artifact SHA-256 does not match its runner stamp")
    return {
        "evaluated": True,
        "artifact": str(path),
        "artifact_sha256": actual,
        "expected_sha256": expected_sha256,
        "errors": errors,
    }


def audit_pytest_invocation_receipt(
    receipt: Path | None,
    junit: Path | None,
    *,
    expected_head: str | None,
    expected_test_tree_sha256: str | None,
    expected_activation_env: str | None,
    expected_marker_present: bool,
    label: str,
) -> dict[str, Any]:
    """Bind a passing pytest artifact to its exact lifecycle stage."""
    errors: list[str] = []
    if receipt is None:
        return {
            "evaluated": False,
            "errors": [f"the {label} invocation receipt was not runner-stamped"],
        }
    if not receipt.is_file():
        return {
            "evaluated": False,
            "artifact": str(receipt),
            "errors": [f"the stamped {label} invocation receipt is missing: {receipt}"],
        }
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "evaluated": False,
            "artifact": str(receipt),
            "errors": [f"the {label} invocation receipt is unreadable: {exc}"],
        }
    if payload.get("schema") != "fabpub_pytest_invocation.v1":
        errors.append(f"the {label} invocation receipt has the wrong schema")
    if payload.get("exit_code") != 0:
        errors.append(f"the {label} pytest run did not exit exactly 0")
    argv = payload.get("argv")
    joined = ""
    if not isinstance(argv, list) or not argv:
        errors.append(f"the {label} invocation receipt carries no argv")
    else:
        joined = " ".join(str(part) for part in argv)
        if "--junitxml" not in joined:
            errors.append(f"the {label} invocation did not emit JUnit")
    if junit is None or not junit.is_file():
        errors.append(f"the {label} JUnit artifact is missing")
    else:
        if Path(str(payload.get("junit", ""))).resolve() != junit.resolve():
            errors.append(f"the {label} invocation names a different JUnit artifact")
        if payload.get("junit_sha256") != sha256_file(junit):
            errors.append(f"the {label} invocation JUnit digest does not match")
    if expected_head is None:
        errors.append(f"the {label} expected head was not runner-stamped")
    elif payload.get("head") != expected_head:
        errors.append(f"the {label} invocation head does not match its lifecycle stage")
    if payload.get("test_tree_sha256") != expected_test_tree_sha256:
        errors.append(f"the {label} invocation test-tree digest does not match")
    if payload.get("activation_env") != expected_activation_env:
        errors.append(f"the {label} activation environment does not match")
    argv_is_activated = FABPUB_ACTIVATION_ASSIGNMENT in joined
    if argv_is_activated != (expected_activation_env == FABPUB_ACTIVATION_ASSIGNMENT):
        errors.append(f"the {label} argv activation does not match its lifecycle stage")
    if payload.get("marker_present") is not expected_marker_present:
        errors.append(f"the {label} marker-presence binding does not match")
    return {
        "evaluated": True,
        "artifact": str(receipt),
        "artifact_sha256": sha256_file(receipt),
        "errors": errors,
    }


def audit_test_panel_envelope(
    path: Path | None,
    expected_sha256: str | None,
    *,
    expected_bindings: dict[str, str | None],
) -> dict[str, Any]:
    """Validate the runner-owned semantic envelope without parsing review prose."""
    report = audit_digest_bound_artifact(path, expected_sha256, label="test-panel")
    errors = list(report["errors"])
    if path is None or not path.is_file():
        return {**report, "errors": errors}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"the test-panel envelope is unreadable: {exc}")
        return {**report, "errors": errors}
    if payload.get("schema") != "fabpub_test_panel.v1":
        errors.append("the test-panel envelope has the wrong schema")
    for name, expected in expected_bindings.items():
        if expected is None:
            errors.append(f"the expected test-panel {name} binding is absent")
        elif payload.get(name) != expected:
            errors.append(f"the test-panel {name} binding does not match")
    if not isinstance(payload.get("usable_count"), int) or payload["usable_count"] < 4:
        errors.append("the test-panel envelope must attest at least four usable seats")
    return {**report, "errors": errors}


def audit_marker(repo: Path, expect_present: bool) -> dict[str, Any]:
    marker = repo / MARKER_RELATIVE_PATH
    present = marker.is_file()
    errors: list[str] = []
    if present != expect_present:
        errors.append(
            "the FABPUB capability marker is "
            + ("present but must be absent" if present else "absent but must be present")
        )
    return {"marker_present": present, "errors": errors}


def audit_sl0_git_boundary(
    repo: Path,
    guard,
    base: str | None,
    tests_only: str | None,
    expected_head: str | None = None,
) -> dict[str, Any]:
    """``T^ == B``; ``B..T`` touches only SL-0 paths; no production/doc blob moves.

    MANDATORY at every gate (Consiliency/agent-harness#578 F2).  An unstamped
    ``B``/``T`` is a reduction FAILURE, never a silently skipped section: the
    reducer is SL-0-owned and becomes immutable after merge, so a fail-open
    tests-only path could never be repaired downstream.
    """
    if not base or not tests_only:
        return {
            "evaluated": False,
            "reason": "runner did not stamp B/T",
            "errors": [
                "the SL-0 boundary requires runner-stamped "
                f"{LIFECYCLE_ENV['B']} and {LIFECYCLE_ENV['T']}; refusing to pass on absent evidence"
            ],
        }

    errors: list[str] = []
    sl0_paths = set(guard.FABPUB_TEST_PATHS) | {CHRONOLOGY_RELATIVE_PATH}
    non_sl0 = set(guard.FABPUB_OWNED_PATHS) - sl0_paths

    resolved_tests_only = git(repo, "rev-parse", tests_only)
    parent = git(repo, "rev-parse", f"{resolved_tests_only}^")
    resolved_base = git(repo, "rev-parse", base)
    if parent != resolved_base:
        errors.append(f"T^ ({parent}) != B ({resolved_base})")

    if expected_head is not None and resolved_tests_only != expected_head:
        errors.append(
            "--head does not name the runner-stamped tests-only candidate: "
            f"head={expected_head} T={resolved_tests_only}"
        )

    changed = [
        p for p in git(repo, "diff", "--name-only", resolved_base, resolved_tests_only).splitlines() if p
    ]
    if not changed:
        errors.append("B..T changed no path; the tests-only commit is empty")
    outside = sorted(set(changed) - sl0_paths)
    if outside:
        errors.append(f"B..T touched non-SL-0 paths: {outside}")

    for relative in sorted(non_sl0):
        if blob_sha(repo, resolved_base, relative) != blob_sha(repo, resolved_tests_only, relative):
            errors.append(f"production/doc blob moved across B..T: {relative}")

    return {
        "evaluated": True,
        "base": resolved_base,
        "tests_only": resolved_tests_only,
        "changed_paths": sorted(changed),
        "errors": errors,
    }


def audit_red_evidence(
    repo: Path,
    guard,
    junit: Path | None,
    raw_log: Path | None,
    invocation: Path | None = None,
    exit_code: int | None = None,
) -> dict[str, Any]:
    """The activated-RED reduction.  MANDATORY, and bound to a trusted exit code.

    The plan requires proof that the ACTIVATED pytest run exited exactly 1.  An
    exit code is not derivable from a JUnit document, so the runner stamps it —
    either directly or through an invocation record carrying the exact argv.
    """
    if junit is None:
        return {
            "evaluated": False,
            "reason": "runner did not stamp the RED JUnit path",
            "errors": [
                "the activated-RED JUnit artifact is required; refusing to pass on absent evidence"
            ],
        }
    errors: list[str] = []
    reduced = reduce_junit(repo, junit)
    red = set(guard.FABPUB_RED_NODEIDS)

    # --- trusted argv / exit-code binding ---------------------------------
    record: dict[str, Any] = {}
    if invocation is not None:
        if not invocation.is_file():
            errors.append(f"the stamped RED invocation record is missing: {invocation}")
        else:
            try:
                record = json.loads(invocation.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - malformed stamp
                errors.append(f"the RED invocation record is unreadable: {exc}")
    stamped_exit = exit_code if exit_code is not None else record.get("exit_code")
    if stamped_exit is None:
        errors.append(
            "no trusted activated-RED exit code was stamped; the plan requires proof that the "
            "activated pytest run exited exactly 1"
        )
    elif int(stamped_exit) != 1:
        errors.append(f"the activated-RED run must exit exactly 1; stamped exit code was {stamped_exit}")

    argv = record.get("argv")
    if invocation is not None and not argv:
        errors.append("the RED invocation record carries no argv")
    if argv:
        joined = " ".join(str(part) for part in argv)
        if f"{guard.FABPUB_ACTIVATION_ENV}=1" not in joined:
            errors.append(
                f"the RED invocation argv does not carry {guard.FABPUB_ACTIVATION_ENV}=1; "
                "the reduced artifact is not an ACTIVATED run"
            )
        if "--junitxml" not in joined:
            errors.append("the RED invocation argv did not emit the reduced JUnit artifact")
        stamped_junit = record.get("junit")
        if stamped_junit and Path(stamped_junit).resolve() != junit.resolve():
            errors.append("the RED invocation record names a different JUnit artifact")
    if raw_log is None:
        errors.append("the activated-RED raw evidence log is required")
    elif not raw_log.is_file():
        errors.append(f"the stamped activated-RED raw evidence log is missing: {raw_log}")
    elif raw_log.stat().st_size == 0:
        errors.append(f"the stamped activated-RED raw evidence log is empty: {raw_log}")
    stamped_raw = record.get("raw_log")
    if stamped_raw and raw_log is not None:
        if Path(stamped_raw).resolve() != raw_log.resolve():
            errors.append(
                "the RED invocation record names a different raw log "
                f"({stamped_raw}) than the stamped artifact ({raw_log})"
            )
    elif record and not stamped_raw:
        errors.append("the RED invocation record carries no raw_log binding")

    missing = sorted(red - set(reduced["failed"]))
    if missing:
        errors.append(f"RED nodeids did not fail: {missing}")
    wrongly_passed = sorted(red & reduced["passed"])
    if wrongly_passed:
        errors.append(f"RED nodeids passed under activation: {wrongly_passed}")
    wrongly_skipped = sorted(red & reduced["skipped"])
    if wrongly_skipped:
        errors.append(f"RED nodeids skipped under activation: {wrongly_skipped}")
    if reduced["errored"]:
        errors.append(f"collection/errored testcases are forbidden: {sorted(reduced['errored'])}")
    if reduced["xfails"]:
        errors.append(f"xfail is forbidden: {reduced['xfails']}")
    duplicates = sorted(set(reduced["duplicates"]) & red)
    if duplicates:
        errors.append(f"RED nodeids appeared more than once: {duplicates}")

    unexpected = sorted(set(reduced["failed"]) - red)
    if unexpected:
        errors.append(f"unexpected RED nodeids: {unexpected}")
    errors.extend(_totals_errors(reduced, "activated-RED"))

    raw = (
        raw_log.read_text(encoding="utf-8", errors="replace")
        if raw_log is not None and raw_log.is_file()
        else ""
    )
    for nodeid in sorted(red & set(reduced["failed"])):
        anchor = guard.FABPUB_RED_ANCHORS[nodeid]
        if anchor not in reduced["failed"][nodeid]:
            errors.append(f"{nodeid} did not fail at its intended anchor {anchor}")
        elif anchor not in raw:
            # An empty/absent raw log lands here rather than silently passing.
            errors.append(f"{anchor} is absent from the raw activated-RED output")

    return {
        "evaluated": True,
        "artifact": reduced["artifact"],
        "artifact_sha256": reduced["artifact_sha256"],
        "raw_log_sha256": sha256_file(raw_log) if raw_log and raw_log.is_file() else None,
        "failed_count": len(reduced["failed"]),
        "errors": errors,
    }


def audit_default_evidence(repo: Path, guard, junit: Path | None) -> dict[str, Any]:
    """The default-green reduction.  MANDATORY at every gate."""
    if junit is None:
        return {
            "evaluated": False,
            "reason": "runner did not stamp the default JUnit path",
            "errors": [
                "the default-green JUnit artifact is required; refusing to pass on absent evidence"
            ],
        }
    errors: list[str] = []
    reduced = reduce_junit(repo, junit)
    new = set(guard.FABPUB_NEW_PRODUCTION_NODEIDS)
    migrated = set(guard.FABPUB_MIGRATED_NODEIDS)

    phase_skipped = reduced["skipped"] & (new | migrated)
    if phase_skipped != new:
        errors.append(
            "the inactive skip set is not exactly FABPUB_NEW_PRODUCTION_NODEIDS "
            f"(missing={sorted(new - phase_skipped)}, extra={sorted(phase_skipped - new)})"
        )
    migrated_skipped = sorted(migrated & reduced["skipped"])
    if migrated_skipped:
        errors.append(f"migrated nodeids must never skip: {migrated_skipped}")
    migrated_not_passed = sorted(migrated - reduced["passed"])
    if migrated_not_passed:
        errors.append(f"migrated nodeids must pass their legacy branch: {migrated_not_passed}")
    if reduced["failed"]:
        errors.append(f"default CI must be GREEN; failures: {sorted(reduced['failed'])}")
    if reduced["errored"]:
        errors.append(f"collection/errored testcases are forbidden: {sorted(reduced['errored'])}")
    if reduced["xfails"]:
        errors.append(f"xfail is forbidden: {reduced['xfails']}")
    errors.extend(_totals_errors(reduced, "default-green"))
    declared = reduced["declared_totals"]
    if declared["failures"]:
        errors.append(
            f"default CI must be GREEN; the JUnit declares {declared['failures']} failure(s)"
        )
    if declared["errors"]:
        errors.append(
            f"default CI must be GREEN; the JUnit declares {declared['errors']} error(s)"
        )

    return {
        "evaluated": True,
        "artifact": reduced["artifact"],
        "artifact_sha256": reduced["artifact_sha256"],
        "skip_count": len(phase_skipped),
        "declared_totals": declared,
        "resolved_total": reduced["resolved_total"],
        "unresolved_total": reduced["unresolved_total"],
        "errors": errors,
    }


def _totals_errors(reduced: dict[str, Any], label: str) -> list[str]:
    """Declared-total reconciliation + unresolved-non-skip rejection.

    Applied to EVERY gate — default-green and activated-RED included
    (Consiliency/agent-harness#578 round 3, item 4) — not just the pass gates.
    """
    errors: list[str] = []
    declared = reduced["declared_totals"]
    accounted = reduced["resolved_total"] + reduced["unresolved_total"]
    if declared["tests"] and declared["tests"] != accounted:
        errors.append(
            f"{label}: total drift — the JUnit declares {declared['tests']} testcases but "
            f"{reduced['resolved_total']} resolved plus {reduced['unresolved_total']} "
            f"collection records account for only {accounted}"
        )
    bad_unresolved = [u for u in reduced["unresolved"] if u["outcome"] != "skipped"]
    if bad_unresolved:
        errors.append(
            f"{label}: unresolved testcases must be collection skips only; got {bad_unresolved}"
        )
    return errors


def audit_activated_pass_junit(repo: Path, guard, junit: Path | None, *, label: str) -> dict[str, Any]:
    """The preactivation / final reduction (plan:323, plan:326).

    Both gates reduce a run in which EVERY expected nodeid is active and PASSING.
    Beyond that, the reduction must reject:

    * any failure outside ``FABPUB_EXPECTED_NODEIDS`` — a green phase inventory
      inside a red suite is not a pass;
    * total drift — the JUnit's own declared totals must agree with the resolved
      testcases and report zero failures/errors;
    * any phase skip, xfail, duplicate, or errored testcase.
    """
    if junit is None:
        # A pass gate may NOT pass on absent evidence: "no artifact" is a failure,
        # never a silently-skipped section.
        return {
            "evaluated": False,
            "reason": f"runner did not stamp the {label} JUnit path",
            "errors": [f"the {label} JUnit artifact is required at this gate but was not stamped"],
        }
    errors: list[str] = []
    reduced = reduce_junit(repo, junit)
    expected = set(guard.FABPUB_EXPECTED_NODEIDS)

    not_passed = sorted(expected - reduced["passed"])
    if not_passed:
        errors.append(f"{label}: expected nodeids did not pass: {not_passed}")
    phase_skipped = sorted(expected & reduced["skipped"])
    if phase_skipped:
        errors.append(f"{label}: zero phase skips are permitted: {phase_skipped}")
    if reduced["errored"]:
        errors.append(f"{label}: zero errors are permitted: {sorted(reduced['errored'])}")
    if reduced["xfails"]:
        errors.append(f"{label}: zero xfails are permitted: {reduced['xfails']}")
    duplicates = sorted(set(reduced["duplicates"]) & expected)
    if duplicates:
        errors.append(f"{label}: expected nodeids appeared more than once: {duplicates}")

    # UNEXPECTED failures: a phase gate may not pass while the reduced suite is red.
    unexpected = sorted(set(reduced["failed"]) - expected)
    if unexpected:
        errors.append(f"{label}: failures outside FABPUB_EXPECTED_NODEIDS: {unexpected}")

    # TOTAL drift: the document's own totals must corroborate the reduction.
    declared = reduced["declared_totals"]
    if declared["failures"]:
        errors.append(f"{label}: the JUnit declares {declared['failures']} failure(s); zero are permitted")
    if declared["errors"]:
        errors.append(f"{label}: the JUnit declares {declared['errors']} error(s); zero are permitted")
    errors.extend(_totals_errors(reduced, label))
    if reduced["resolved_total"] < len(expected):
        errors.append(
            f"{label}: the reduction resolved {reduced['resolved_total']} testcases, fewer than "
            f"the {len(expected)} expected nodeids"
        )

    return {
        "evaluated": True,
        "artifact": reduced["artifact"],
        "artifact_sha256": reduced["artifact_sha256"],
        "expected_count": len(expected),
        "declared_totals": declared,
        "resolved_total": reduced["resolved_total"],
        "errors": errors,
    }


#: Keys the legacy-cutover / writer-generation evidence record must bind (plan:323).
CUTOVER_EVIDENCE_KEYS = (
    "cutover_id",
    "manifest_sha256",
    "legacy_roots",
    "target_namespaces",
    "serialized_repository_preimages",
    "resolution_contexts",
    "source_digests",
    "archive_digests",
    "retirement_tombstones",
    "partition_receipts",
    "onboarding_receipts",
    "quiescence_inventory",
    "activation_lease",
    "writer_generation_states",
    "per_repository_high_water",
    "per_repository_ambiguity",
    "transaction_digests",
    "counts",
)

#: Keys the shared adapter-start ownership evidence record must bind (plan:323).
START_OWNER_EVIDENCE_KEYS = (
    "repository_identity",
    "idempotency_key",
    "transaction_id",
    "attempt_id",
    "committed_head",
    "adapter_operation",
    "owner_nonce",
    "permanent_ambiguity",
)

#: Bindings that may legitimately be empty: a cutover with no post-ACTIVE
#: onboarding has no onboarding receipts, and an attested inventory that found no
#: live pre-FABPUB writer is legitimately the empty list.  Their SHAPE is still
#: checked; only the non-empty rule is relaxed.
_LEGITIMATELY_EMPTY = frozenset({"onboarding_receipts", "quiescence_inventory"})

#: Substrings that must never appear in metadata-only phase evidence.
_CREDENTIAL_MARKERS = ("GH_TOKEN", "GITHUB_TOKEN", "authorization", "password", "private_key")


def audit_phase_evidence(
    repo: Path,
    cutover: Path | None,
    cutover_sha256: str | None,
    start_owner: Path | None,
    start_owner_sha256: str | None,
) -> dict[str, Any]:
    """Bind the cutover/generation and shared start-owner evidence (plan:323).

    Both are REQUIRED at the preactivation and final gates, must carry every
    frozen key, and must stay metadata-only — no raw credential values.
    """
    errors: list[str] = []
    reported: dict[str, Any] = {}

    for label, path, expected_sha256, keys in (
        ("legacy-cutover", cutover, cutover_sha256, CUTOVER_EVIDENCE_KEYS),
        ("adapter-start-owner", start_owner, start_owner_sha256, START_OWNER_EVIDENCE_KEYS),
    ):
        binding = audit_digest_bound_artifact(path, expected_sha256, label=f"{label} evidence")
        errors.extend(binding["errors"])
        if not binding["evaluated"]:
            continue
        raw = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except Exception as exc:
            errors.append(f"the {label} evidence artifact is unreadable: {exc}")
            continue
        missing = [key for key in keys if key not in payload]
        if missing:
            errors.append(f"the {label} evidence omits required bindings: {missing}")
        empty = [
            key
            for key in keys
            if key in payload and _is_empty(payload[key]) and key not in _LEGITIMATELY_EMPTY
        ]
        if empty:
            errors.append(f"the {label} evidence carries empty bindings: {empty}")
        leaked = [marker for marker in _CREDENTIAL_MARKERS if marker.lower() in raw.lower()]
        if leaked:
            errors.append(f"the {label} evidence is not metadata-only; it mentions {leaked}")
        errors.extend(f"{label}: {message}" for message in _semantic_errors(label, payload))
        reported[label] = binding

    return {"evaluated": True, "artifacts": reported, "errors": errors}


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


_HEX64 = set("0123456789abcdef")


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


def _semantic_errors(label: str, payload: dict[str, Any]) -> list[str]:
    """Check VALUES, digests, counts, and cross-bindings — not key presence.

    Consiliency/agent-harness#578 F-C3: a key-presence check accepts
    ``{"manifest_sha256": "metadata"}``.  These rules assert the shape each
    binding must actually have and that the declared counts agree with the
    collections they count.
    """
    problems: list[str] = []

    if label == "legacy-cutover":
        for digest_key in ("manifest_sha256",):
            if not _is_digest(payload.get(digest_key)):
                problems.append(f"{digest_key} is not a 64-hex digest")
        for mapping_key in (
            "source_digests",
            "archive_digests",
            "transaction_digests",
            "per_repository_high_water",
            "per_repository_ambiguity",
        ):
            value = payload.get(mapping_key)
            if not isinstance(value, dict) or not value:
                problems.append(f"{mapping_key} must be a non-empty mapping")
        for list_key in (
            "legacy_roots",
            "target_namespaces",
            "serialized_repository_preimages",
            "resolution_contexts",
            "retirement_tombstones",
            "partition_receipts",
        ):
            value = payload.get(list_key)
            if not isinstance(value, list) or not value:
                problems.append(f"{list_key} must be a non-empty list")
        for mapping_key in ("source_digests", "archive_digests", "transaction_digests"):
            value = payload.get(mapping_key)
            if isinstance(value, dict):
                bad = sorted(k for k, v in value.items() if not _is_digest(v))
                if bad:
                    problems.append(f"{mapping_key} has non-digest values for {bad}")

        counts = payload.get("counts")
        if not isinstance(counts, dict) or not counts:
            problems.append("counts must be a non-empty mapping")
        else:
            for count_key, collection_key in (
                ("legacy_roots", "legacy_roots"),
                ("partition_receipts", "partition_receipts"),
                ("target_namespaces", "target_namespaces"),
                ("retirement_tombstones", "retirement_tombstones"),
            ):
                declared = counts.get(count_key)
                collection = payload.get(collection_key)
                if declared is None:
                    problems.append(f"counts omits {count_key}")
                elif isinstance(collection, list) and declared != len(collection):
                    problems.append(
                        f"counts.{count_key}={declared} disagrees with {collection_key} "
                        f"({len(collection)} entries)"
                    )

        # Cross-binding: every partition receipt needs a target namespace and a
        # high-water entry; ambiguity must be declared for the same partitions.
        receipts = payload.get("partition_receipts")
        namespaces = payload.get("target_namespaces")
        if isinstance(receipts, list) and isinstance(namespaces, list):
            if len(receipts) != len(namespaces):
                problems.append(
                    f"partition_receipts ({len(receipts)}) and target_namespaces "
                    f"({len(namespaces)}) must be 1:1"
                )
        high_water = payload.get("per_repository_high_water")
        ambiguity = payload.get("per_repository_ambiguity")
        if isinstance(high_water, dict) and isinstance(ambiguity, dict):
            if set(high_water) != set(ambiguity):
                problems.append(
                    "per_repository_high_water and per_repository_ambiguity cover different "
                    "repository partitions"
                )
            bad_floor = sorted(
                k for k, v in high_water.items() if not isinstance(v, int) or v < 0
            )
            if bad_floor:
                problems.append(f"per_repository_high_water must be non-negative ints; {bad_floor}")

        states = payload.get("writer_generation_states")
        if not isinstance(states, list) or list(states) != ["LEGACY_OPEN", "DRAINING", "ACTIVE"]:
            problems.append(
                "writer_generation_states must be exactly ['LEGACY_OPEN','DRAINING','ACTIVE']"
            )
        if not isinstance(payload.get("cutover_id"), str) or not payload.get("cutover_id"):
            problems.append("cutover_id must be a non-empty string")
        lease = payload.get("activation_lease")
        if not isinstance(lease, dict) or "holder" not in lease:
            problems.append("activation_lease must be a mapping naming its holder")
        quiescence = payload.get("quiescence_inventory")
        if not isinstance(quiescence, list):
            problems.append("quiescence_inventory must be a list")

    if label == "adapter-start-owner":
        for digest_key in ("idempotency_key", "transaction_id", "owner_nonce"):
            value = payload.get(digest_key)
            if not isinstance(value, str) or len(value) < 16:
                problems.append(f"{digest_key} must be an opaque identifier of >= 16 chars")
        head = payload.get("committed_head")
        if not isinstance(head, str) or len(head) not in (40, 64):
            problems.append("committed_head must be a full 40/64-hex object id")
        if payload.get("adapter_operation") != "publish_committed_branch":
            problems.append("adapter_operation must be publish_committed_branch")
        if not _is_digest(payload.get("repository_identity")):
            problems.append("repository_identity must be a 64-hex CanonicalRepositoryIdentity.v1")
        ambiguity = payload.get("permanent_ambiguity")
        if not isinstance(ambiguity, bool):
            problems.append("permanent_ambiguity must be a boolean")

    return problems


def audit_lifecycle(
    repo: Path, guard, stamped: dict[str, str | None], expected_head: str
) -> dict[str, Any]:
    errors: list[str] = []
    missing = [key for key, value in stamped.items() if not value]
    if missing:
        return {
            "evaluated": False,
            "reason": f"runner did not stamp: {sorted(missing)}",
            "errors": [f"the final gate requires runner-stamped lifecycle SHAs; missing {sorted(missing)}"],
        }

    resolved = {key: git(repo, "rev-parse", value) for key, value in stamped.items()}
    if resolved["L"] != expected_head:
        errors.append(
            "--head does not name the runner-stamped landed lifecycle SHA: "
            f"head={expected_head} L={resolved['L']}"
        )

    def ancestor(older: str, newer: str) -> bool:
        completed = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", resolved[older], resolved[newer]],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return completed.returncode == 0

    # Complete chain, including the P -> C continuity the earlier subset omitted
    # (Consiliency/agent-harness#578 F-C3).
    for older, newer in (
        ("B", "T"), ("T", "I"), ("I", "P"), ("P", "C"), ("C", "M"), ("M", "H"), ("H", "L")
    ):
        if not ancestor(older, newer):
            errors.append(f"{older} is not an ancestor of {newer}")
    # T and I must both be ancestors of P's PARENT: no production change may sneak
    # into the tests-only or implementation-base commits.
    parent_of_p = git(repo, "rev-parse", f"{resolved['P']}^")
    for key in ("T", "I"):
        probe = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", resolved[key], parent_of_p],
            capture_output=True, text=True, timeout=60,
        )
        if probe.returncode != 0:
            errors.append(f"{key} is not an ancestor of P^")

    if git(repo, "rev-parse", f"{resolved['M']}^") != resolved["C"]:
        errors.append("M^ != C; the marker commit is not rooted at the pre-activation head")

    marker_changes = [
        p for p in git(repo, "diff", "--name-only", resolved["C"], resolved["M"]).splitlines() if p
    ]
    if marker_changes != [MARKER_RELATIVE_PATH]:
        errors.append(f"C..M must contain ONLY the marker; got {marker_changes}")

    for rev in ("B", "T", "I", "C"):
        if blob_sha(repo, resolved[rev], MARKER_RELATIVE_PATH) is not None:
            errors.append(f"the marker must be absent at {rev}")
    marker_blobs = {}
    for rev in ("M", "H", "L"):
        marker_blobs[rev] = blob_sha(repo, resolved[rev], MARKER_RELATIVE_PATH)
        if marker_blobs[rev] is None:
            errors.append(f"the marker must be present at {rev}")
    # EXACT marker bytes: the marker installed at M must be byte-identical at H and L.
    if all(marker_blobs.values()) and len(set(marker_blobs.values())) != 1:
        errors.append(f"the marker blob is not byte-identical across M/H/L: {marker_blobs}")

    # FIRST-PRODUCTION-COMMIT identity: P must be the first first-parent commit after
    # I that changes any of the twelve production/doc paths.
    sl0_paths = set(guard.FABPUB_TEST_PATHS) | {CHRONOLOGY_RELATIVE_PATH}
    production_paths = set(guard.FABPUB_OWNED_PATHS) - sl0_paths
    revs = [
        line
        for line in git(
            repo, "rev-list", "--first-parent", "--reverse", f"{resolved['I']}..{resolved['C']}"
        ).splitlines()
        if line
    ]
    first_production = None
    for rev in revs:
        changed = {
            path
            for path in git(repo, "diff", "--name-only", f"{rev}^", rev).splitlines()
            if path
        }
        if changed & production_paths:
            first_production = rev
            break
    if first_production is None:
        errors.append("no first-parent commit in I..C changes a production/doc path")
    elif first_production != resolved["P"]:
        errors.append(
            f"P is not the FIRST production commit after I; the first is {first_production}"
        )

    # SL-0 BLOB IMMUTABILITY: every SL-0 blob must be byte-identical from T through L.
    for relative in sorted(sl0_paths):
        reference = blob_sha(repo, resolved["T"], relative)
        if reference is None:
            errors.append(f"SL-0 path missing at T: {relative}")
            continue
        for rev in ("I", "P", "C", "M", "H", "L"):
            if blob_sha(repo, resolved[rev], relative) != reference:
                errors.append(f"SL-0 blob mutated after T at {rev}: {relative}")

    # H -> L BLOB EQUALITY: every phase-owned blob at L equals the reviewed candidate.
    for relative in sorted(guard.FABPUB_OWNED_PATHS):
        if blob_sha(repo, resolved["H"], relative) != blob_sha(repo, resolved["L"], relative):
            errors.append(f"phase-owned blob differs between H and L: {relative}")

    return {
        "evaluated": True,
        "resolved": resolved,
        "first_production_commit": first_production,
        "marker_blobs": marker_blobs,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _stamped_path(explicit: str | None, env_name: str) -> Path | None:
    value = explicit or os.environ.get(env_name)
    return Path(value) if value else None


def audit_head_binding(repo: Path, requested_head: str) -> dict[str, Any]:
    """Resolve ``--head`` once and bind it to this checked-out candidate."""
    resolved_head = git(repo, "rev-parse", requested_head)
    checkout_head = git(repo, "rev-parse", "HEAD")
    errors: list[str] = []
    if resolved_head != checkout_head:
        errors.append(
            "--head does not resolve to the checked-out candidate: "
            f"head={resolved_head} checkout={checkout_head}"
        )
    return {
        "requested": requested_head,
        "resolved": resolved_head,
        "checkout": checkout_head,
        "errors": errors,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).resolve()
    guard = load_guard(repo)
    head_binding = audit_head_binding(repo, args.head)

    report: dict[str, Any] = {
        "schema": "fabpub_tdd_chronology.v1",
        "mode": args.mode,
        "repo": str(repo),
        "requested_head": args.head,
        "head": head_binding["resolved"],
    }

    sections: dict[str, Any] = {"head_binding": head_binding}
    sections["inventories"] = audit_frozen_inventories(
        repo,
        guard,
        _stamped_path(args.predecessor_inventory, EVIDENCE_ENV["predecessor_inventory"]),
    )
    sections["vectors"] = audit_vectors(repo, guard)
    sections["test_tree"] = audit_test_tree(repo, guard)
    sections["plan_manifest"] = audit_plan_manifest_binding(repo, guard)
    sections["marker"] = audit_marker(repo, expect_present=(args.mode != "tests-only"))
    sections["sl0_git_boundary"] = audit_sl0_git_boundary(
        repo,
        guard,
        args.base or os.environ.get(LIFECYCLE_ENV["B"]),
        args.tests_only or os.environ.get(LIFECYCLE_ENV["T"]),
        head_binding["resolved"] if args.mode == "tests-only" else None,
    )
    stamped_exit = args.red_exit_code
    if stamped_exit is None and os.environ.get(EVIDENCE_ENV["red_exit_code"]):
        stamped_exit = int(os.environ[EVIDENCE_ENV["red_exit_code"]])
    sections["activated_red"] = audit_red_evidence(
        repo,
        guard,
        _stamped_path(args.red_junit, EVIDENCE_ENV["red_junit"]),
        _stamped_path(args.red_raw_log, EVIDENCE_ENV["red_raw_log"]),
        _stamped_path(args.red_invocation, EVIDENCE_ENV["red_invocation"]),
        stamped_exit,
    )
    sections["default_green"] = audit_default_evidence(
        repo, guard, _stamped_path(args.default_junit, EVIDENCE_ENV["default_junit"])
    )
    sections["default_green"]["invocation"] = audit_pytest_invocation_receipt(
        _stamped_path(args.default_invocation, EVIDENCE_ENV["default_invocation"]),
        _stamped_path(args.default_junit, EVIDENCE_ENV["default_junit"]),
        expected_head=sections["sl0_git_boundary"].get("tests_only"),
        expected_test_tree_sha256=sections["test_tree"].get("test_tree_sha256"),
        expected_activation_env=None,
        expected_marker_present=False,
        label="default-green",
    )
    sections["default_green"]["errors"].extend(
        sections["default_green"]["invocation"]["errors"]
    )

    if args.mode in ("final-junit", "final"):
        # plan:323 — the PREACTIVATION reduction (activated, marker still absent)
        # is a distinct required artifact, not an alias of the final one.
        sections["preactivation_junit"] = audit_activated_pass_junit(
            repo,
            guard,
            _stamped_path(args.preactivation_junit, EVIDENCE_ENV["preactivation_junit"]),
            label="preactivation",
        )
        sections["preactivation_junit"]["invocation"] = audit_pytest_invocation_receipt(
            _stamped_path(
                args.preactivation_invocation, EVIDENCE_ENV["preactivation_invocation"]
            ),
            _stamped_path(args.preactivation_junit, EVIDENCE_ENV["preactivation_junit"]),
            expected_head=args.sha_c or os.environ.get(LIFECYCLE_ENV["C"]),
            expected_test_tree_sha256=sections["test_tree"].get("test_tree_sha256"),
            expected_activation_env=f"{guard.FABPUB_ACTIVATION_ENV}=1",
            expected_marker_present=False,
            label="preactivation",
        )
        sections["preactivation_junit"]["errors"].extend(
            sections["preactivation_junit"]["invocation"]["errors"]
        )
        # plan:326 — the FINAL reduction runs unactivated with the marker installed.
        sections["final_junit"] = audit_activated_pass_junit(
            repo,
            guard,
            _stamped_path(args.final_junit, EVIDENCE_ENV["final_junit"]),
            label="final",
        )
        sections["final_junit"]["invocation"] = audit_pytest_invocation_receipt(
            _stamped_path(args.final_invocation, EVIDENCE_ENV["final_invocation"]),
            _stamped_path(args.final_junit, EVIDENCE_ENV["final_junit"]),
            expected_head=head_binding["resolved"],
            expected_test_tree_sha256=sections["test_tree"].get("test_tree_sha256"),
            expected_activation_env=None,
            expected_marker_present=True,
            label="final",
        )
        sections["final_junit"]["errors"].extend(
            sections["final_junit"]["invocation"]["errors"]
        )
        preactivation_digest = sections["preactivation_junit"].get("artifact_sha256")
        final_digest = sections["final_junit"].get("artifact_sha256")
        if preactivation_digest is not None and preactivation_digest == final_digest:
            sections["final_junit"]["errors"].append(
                "preactivation and final must use distinct JUnit artifacts"
            )
        sections["phase_evidence"] = audit_phase_evidence(
            repo,
            _stamped_path(args.cutover_evidence, EVIDENCE_ENV["cutover_evidence"]),
            args.cutover_evidence_sha256
            or os.environ.get(EVIDENCE_ENV["cutover_evidence_sha256"]),
            _stamped_path(args.start_owner_evidence, EVIDENCE_ENV["start_owner_evidence"]),
            args.start_owner_evidence_sha256
            or os.environ.get(EVIDENCE_ENV["start_owner_evidence_sha256"]),
        )
        sections["test_panel"] = audit_test_panel_envelope(
            _stamped_path(args.test_panel_record, EVIDENCE_ENV["test_panel_record"]),
            args.test_panel_record_sha256
            or os.environ.get(EVIDENCE_ENV["test_panel_record_sha256"]),
            expected_bindings={
                "head": sections["sl0_git_boundary"].get("tests_only"),
                "test_tree_sha256": sections["test_tree"].get("test_tree_sha256"),
                "guard_sha256": sections["test_tree"].get("guard_sha256"),
                "red_junit_sha256": sections["activated_red"].get("artifact_sha256"),
                "default_junit_sha256": sections["default_green"].get("artifact_sha256"),
            },
        )

    if args.mode == "final":
        sections["lifecycle"] = audit_lifecycle(
            repo,
            guard,
            {
                key: getattr(args, f"sha_{key.lower()}", None) or os.environ.get(env)
                for key, env in LIFECYCLE_ENV.items()
            },
            head_binding["resolved"],
        )

    # NOTE: `sl0_git_boundary`, `activated_red`, and `default_green` are mandatory in
    # EVERY mode (Consiliency/agent-harness#578 F2); each already fails closed on an
    # absent stamp, so there is no mode-specific promotion here.

    errors: list[str] = []
    for name, section in sections.items():
        for message in section.get("errors", []):
            errors.append(f"{name}: {message}")

    report["sections"] = sections
    report["errors"] = errors
    report["ok"] = not errors
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase_loop_runtime.fabpub_tdd_chronology")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--mode", choices=("tests-only", "final-junit", "final"), required=True)
    parser.add_argument("--base", default=None, help=f"runner-stamped {LIFECYCLE_ENV['B']}")
    parser.add_argument("--tests-only", default=None, help=f"runner-stamped {LIFECYCLE_ENV['T']}")
    parser.add_argument("--red-junit", default=None)
    parser.add_argument("--red-raw-log", default=None)
    parser.add_argument(
        "--red-invocation",
        default=None,
        help="runner-stamped JSON record: {argv, exit_code, junit, raw_log}",
    )
    parser.add_argument(
        "--red-exit-code",
        type=int,
        default=None,
        help=f"runner-stamped activated pytest exit code (must be 1); env {EVIDENCE_ENV['red_exit_code']}",
    )
    parser.add_argument("--default-junit", default=None)
    parser.add_argument("--default-invocation", default=None)
    parser.add_argument("--preactivation-junit", default=None)
    parser.add_argument("--preactivation-invocation", default=None)
    parser.add_argument("--final-junit", default=None)
    parser.add_argument("--final-invocation", default=None)
    parser.add_argument("--cutover-evidence", default=None)
    parser.add_argument("--cutover-evidence-sha256", default=None)
    parser.add_argument("--start-owner-evidence", default=None)
    parser.add_argument("--start-owner-evidence-sha256", default=None)
    parser.add_argument("--test-panel-record", default=None)
    parser.add_argument("--test-panel-record-sha256", default=None)
    parser.add_argument("--predecessor-inventory", default=None)
    for key in LIFECYCLE_ENV:
        parser.add_argument(f"--sha-{key.lower()}", default=None)
    args = parser.parse_args(argv)

    try:
        report = build_report(args)
    except ChronologyError as exc:
        print(json.dumps({"schema": "fabpub_tdd_chronology.v1", "ok": False, "errors": [str(exc)]}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(report, indent=2, sort_keys=True, default=sorted))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
