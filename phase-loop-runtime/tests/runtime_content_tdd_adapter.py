"""RUNTIME SL-0 bounded content-TDD adapter (``runtime_content_tdd_adapter.v1``).

Tests-only wrapper over an unchanged ``phase_loop_runtime.tdd_receipts``. It adds
no production capability marker and no replacement receipt API: the generic
recorder still produces the ``content_tdd_receipt.v1`` receipt, and this adapter
writes a digest-bound companion that binds what the generic schema cannot express
-- RUNTIME activation, the typed anchor inventory, the exact node/test/target
inventories, the default and RED JUnit/raw digests, base and landing identity and
ancestry, plan and roadmap digests, and the declared tests landing as the expected
first-production parent.

Subcommands
-----------
``preflight``  run the default-GREEN and activated-RED legs from the current tree
``record``     preflight, then record the generic receipt plus the companion
``verify``     re-verify receipt, companion, inventories, and TDD chronology
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from phase_loop_runtime.declared_identity import select_declared_commit
from phase_loop_runtime.tdd_receipts import (
    RED_ANCHOR_MARKER,
    record_content_tdd_receipt,
    verify_content_tdd_receipt,
)

from _runtime_tdd_guard import (  # noqa: E402  (tests-only sibling import)
    RUNTIME_ACTIVATION_ENV,
    RUNTIME_RED_ANCHOR_PREFIX,
    enter_production_symbol,
    run_runtime_case,
)

BINDING_SCHEMA = "runtime_content_tdd_adapter.v1"
PHASE = "RUNTIME"

DEFAULT_PLAN_PATH = "plans/phase-plan-v10-RUNTIME.md"
DEFAULT_ROADMAP_PATH = "specs/phase-plans-v10.md"
DEFAULT_RECEIPT_PATH = ".phase-loop/evidence/RUNTIME/tdd/content-tdd-receipt.json"
DEFAULT_BINDING_PATH = ".phase-loop/evidence/RUNTIME/tdd/runtime-content-tdd-binding.json"

_SRC = "phase-loop-runtime/src/phase_loop_runtime"
_TESTS = "phase-loop-runtime/tests"

#: The closed SL-0 inventory: this adapter, the guard, and the six focused modules.
RUNTIME_INVENTORY: tuple[str, ...] = (
    f"{_TESTS}/_runtime_tdd_guard.py",
    f"{_TESTS}/runtime_content_tdd_adapter.py",
    f"{_TESTS}/test_cli_train_status_45.py",
    f"{_TESTS}/test_convergence_adapters.py",
    f"{_TESTS}/test_convergence_event_log.py",
    f"{_TESTS}/test_convergence_reconcile.py",
    f"{_TESTS}/test_convergence_runtime_imports.py",
    f"{_TESTS}/test_convergence_status.py",
)

#: The six focused modules RUNTIME's default/RED legs collect.
RUNTIME_TEST_MODULES: tuple[str, ...] = tuple(
    path for path in RUNTIME_INVENTORY if Path(path).name.startswith("test_")
)

SL1_PRODUCTION: tuple[str, ...] = (f"{_SRC}/convergence/event_log.py",)
SL2_PRODUCTION: tuple[str, ...] = (f"{_SRC}/convergence/reconcile.py",)
SL3_PRODUCTION: tuple[str, ...] = (
    f"{_SRC}/convergence/adapters/__init__.py",
    f"{_SRC}/convergence/adapters/base.py",
    f"{_SRC}/convergence/adapters/codex.py",
    f"{_SRC}/convergence/adapters/claude.py",
    f"{_SRC}/convergence/adapters/outside_agent.py",
    f"{_SRC}/convergence/status.py",
    f"{_SRC}/cli.py",
)
PRODUCTION_UNION: dict[str, tuple[str, ...]] = {
    "SL-1": SL1_PRODUCTION,
    "SL-2": SL2_PRODUCTION,
    "SL-3": SL3_PRODUCTION,
}


@dataclass(frozen=True)
class RuntimeCase:
    """One mapped falsifier: exactly one lane, production path, symbol, and anchor."""

    lane: str
    production_path: str
    symbol: str
    anchor: str


#: The closed per-case map. Every entry names one production construction site in
#: the SL-1/SL-2/SL-3 owned unions. Test, helper, and guard targets are rejected.
RUNTIME_CASES: dict[str, RuntimeCase] = {
    # -- SL-1: durable convergence event log --------------------------------
    "event-log.full-drain-append": RuntimeCase(
        "SL-1",
        f"{_SRC}/convergence/event_log.py",
        "_append",
        "RUNTIME-RED-ANCHOR::event-log.full-drain-append",
    ),
    "event-log.parent-directory-durability": RuntimeCase(
        "SL-1",
        f"{_SRC}/convergence/event_log.py",
        "_append",
        "RUNTIME-RED-ANCHOR::event-log.parent-directory-durability",
    ),
    "event-log.cross-process-single-writer": RuntimeCase(
        "SL-1",
        f"{_SRC}/convergence/event_log.py",
        "_append",
        "RUNTIME-RED-ANCHOR::event-log.cross-process-single-writer",
    ),
    "event-log.torn-tail-repair-allows-clean-append": RuntimeCase(
        "SL-1",
        f"{_SRC}/convergence/event_log.py",
        "read_convergence_events",
        "RUNTIME-RED-ANCHOR::event-log.torn-tail-repair-allows-clean-append",
    ),
    "event-log.conflicting-duplicate-intent-fails-closed": RuntimeCase(
        "SL-1",
        f"{_SRC}/convergence/event_log.py",
        "record_intent",
        "RUNTIME-RED-ANCHOR::event-log.conflicting-duplicate-intent-fails-closed",
    ),
    "event-log.mixed-version-is-distinct-ambiguity": RuntimeCase(
        "SL-1",
        f"{_SRC}/convergence/event_log.py",
        "recover_train_state",
        "RUNTIME-RED-ANCHOR::event-log.mixed-version-is-distinct-ambiguity",
    ),
    # -- SL-2: exact-state reconciliation ------------------------------------
    "reconcile.authority-split-is-complete": RuntimeCase(
        "SL-2",
        f"{_SRC}/convergence/reconcile.py",
        "reconcile_train_state",
        "RUNTIME-RED-ANCHOR::reconcile.authority-split-is-complete",
    ),
    "reconcile.errored-probe-fails-closed": RuntimeCase(
        "SL-2",
        f"{_SRC}/convergence/reconcile.py",
        "reconcile_train_state",
        "RUNTIME-RED-ANCHOR::reconcile.errored-probe-fails-closed",
    ),
    "reconcile.malformed-observation-fails-closed": RuntimeCase(
        "SL-2",
        f"{_SRC}/convergence/reconcile.py",
        "reconcile_train_state",
        "RUNTIME-RED-ANCHOR::reconcile.malformed-observation-fails-closed",
    ),
    "reconcile.observations-stay-metadata-only": RuntimeCase(
        "SL-2",
        f"{_SRC}/convergence/reconcile.py",
        "reconcile_train_state",
        "RUNTIME-RED-ANCHOR::reconcile.observations-stay-metadata-only",
    ),
    "reconcile.registry-divergence-invalidates": RuntimeCase(
        "SL-2",
        f"{_SRC}/convergence/reconcile.py",
        "reconcile_train_state",
        "RUNTIME-RED-ANCHOR::reconcile.registry-divergence-invalidates",
    ),
    # -- SL-3: adapter envelopes and transcript-free status ------------------
    "adapters.exact-executable-identity": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/adapters/base.py",
        "run_bounded",
        "RUNTIME-RED-ANCHOR::adapters.exact-executable-identity",
    ),
    "adapters.environment-is-credential-stripped": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/adapters/base.py",
        "run_bounded",
        "RUNTIME-RED-ANCHOR::adapters.environment-is-credential-stripped",
    ),
    "adapters.timeout-reclaims-process-group": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/adapters/base.py",
        "run_bounded",
        "RUNTIME-RED-ANCHOR::adapters.timeout-reclaims-process-group",
    ),
    "adapters.expected-version-predicate-is-bound": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/adapters/base.py",
        "AdapterExecutionRequest.__post_init__",
        "RUNTIME-RED-ANCHOR::adapters.expected-version-predicate-is-bound",
    ),
    "adapters.malformed-output-is-not-success": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/adapters/base.py",
        "run_bounded",
        "RUNTIME-RED-ANCHOR::adapters.malformed-output-is-not-success",
    ),
    "adapters.outside-agent-requires-conformance": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/adapters/outside_agent.py",
        "run_outside_agent_adapter",
        "RUNTIME-RED-ANCHOR::adapters.outside-agent-requires-conformance",
    ),
    "adapters.codex-binds-provider-identity": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/adapters/codex.py",
        "run_codex_adapter",
        "RUNTIME-RED-ANCHOR::adapters.codex-binds-provider-identity",
    ),
    "adapters.claude-binds-provider-identity": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/adapters/claude.py",
        "run_claude_adapter",
        "RUNTIME-RED-ANCHOR::adapters.claude-binds-provider-identity",
    ),
    "status.replay-derived-validity-is-labelled": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/status.py",
        "render_train_status",
        "RUNTIME-RED-ANCHOR::status.replay-derived-validity-is-labelled",
    ),
    "status.pending-attempts-stay-distinguishable": RuntimeCase(
        "SL-3",
        f"{_SRC}/convergence/status.py",
        "build_train_status",
        "RUNTIME-RED-ANCHOR::status.pending-attempts-stay-distinguishable",
    ),
    "cli.event-log-mode-fails-closed": RuntimeCase(
        "SL-3",
        f"{_SRC}/cli.py",
        "_run_train_status_command",
        "RUNTIME-RED-ANCHOR::cli.event-log-mode-fails-closed",
    ),
}


def _validate_case_map() -> None:
    """Reject any case that does not bind exactly one in-scope production site."""

    union = {path for paths in PRODUCTION_UNION.values() for path in paths}
    anchors: dict[str, str] = {}
    for case_id, case in RUNTIME_CASES.items():
        assert case.lane in PRODUCTION_UNION, f"{case_id}: unknown lane {case.lane}"
        assert case.production_path in PRODUCTION_UNION[case.lane], (
            f"{case_id}: {case.production_path} is not owned by {case.lane}"
        )
        assert case.production_path in union, f"{case_id}: target outside the production union"
        assert not case.production_path.startswith(f"{_TESTS}/"), (
            f"{case_id}: test targets are rejected"
        )
        assert case.production_path not in RUNTIME_INVENTORY, (
            f"{case_id}: SL-0 helper/guard targets are rejected"
        )
        assert "tdd_guard" not in case.production_path and "tdd_adapter" not in (
            case.production_path
        ), f"{case_id}: guard/adapter targets are rejected"
        assert case.anchor == f"{RUNTIME_RED_ANCHOR_PREFIX}{case_id}", (
            f"{case_id}: anchor is not this case's unique typed marker"
        )
        assert case.anchor not in anchors, f"{case_id}: anchor duplicates {anchors[case.anchor]}"
        anchors[case.anchor] = case_id
    assert len(anchors) == len(RUNTIME_CASES), "the typed anchor inventory is not one-per-case"
    covered = {case.production_path for case in RUNTIME_CASES.values()}
    uncovered = union - covered
    # ``adapters/__init__.py`` is a pure re-export surface with no construction
    # site of its own; every other production path in the union carries a case.
    assert uncovered == {f"{_SRC}/convergence/adapters/__init__.py"}, (
        f"unexpected uncovered production paths: {sorted(uncovered)}"
    )


_validate_case_map()

RUNTIME_CASE_IDS: tuple[str, ...] = tuple(sorted(RUNTIME_CASES))
EXPECTED_RED_MARKERS: tuple[str, ...] = tuple(
    f"{RUNTIME_RED_ANCHOR_PREFIX}{case_id}" for case_id in RUNTIME_CASE_IDS
)


def run_mapped_case(case_id: str, *, probe, assertion) -> None:
    """Run one mapped falsifier by id, threading its frozen production binding."""

    case = RUNTIME_CASES[case_id]
    run_runtime_case(
        case_id,
        production_path=case.production_path,
        symbol=case.symbol,
        anchor=case.anchor,
        probe=probe,
        assertion=assertion,
    )


def assert_all_production_anchors() -> None:
    """Prove every mapped case still enters its declared production symbol."""

    for case_id, case in RUNTIME_CASES.items():
        try:
            enter_production_symbol(case_id, case.production_path, case.symbol, case.anchor)
        except AssertionError as exc:  # pragma: no cover - surfaced verbatim
            raise AssertionError(f"{case_id}: {exc}") from exc


# ---------------------------------------------------------------------------
# JUnit accounting


def verify_runtime_junit(
    junit_path: str | Path,
    *,
    expected_paths: Sequence[str],
    require_no_skips: bool,
) -> dict[str, Any]:
    """Exact collected-node accounting over one RUNTIME leg's JUnit report."""

    path = Path(junit_path)
    if not path.is_file():
        return {"ok": False, "error": f"JUnit report not found: {path}"}
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        return {"ok": False, "error": f"unparseable JUnit report: {exc}"}

    nodeids: list[str] = []
    passed = failed = skipped = errored = xfailed = xpassed = 0
    for testcase in root.findall(".//testcase"):
        file_attr = testcase.attrib.get("file", "")
        classname = testcase.attrib.get("classname", "")
        name = testcase.attrib.get("name", "")
        base = file_attr or classname.replace(".", "/")
        if base and not base.startswith("phase-loop-runtime/"):
            base = f"phase-loop-runtime/{base}"
        nodeids.append(f"{base}::{name}")
        skipped_elem = testcase.find("skipped")
        if testcase.find("failure") is not None:
            failed += 1
        elif testcase.find("error") is not None:
            errored += 1
        elif skipped_elem is not None:
            if "xfail" in skipped_elem.attrib.get("type", "").lower():
                xfailed += 1
            else:
                skipped += 1
        else:
            passed += 1

    counts = {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errored": errored,
        "xfailed": xfailed,
        "xpassed": xpassed,
        "collected": sorted(nodeids),
    }
    if len(nodeids) != len(set(nodeids)):
        return {"ok": False, "error": "duplicate collected node ids", **counts}
    observed_paths = {nodeid.split("::", 1)[0] for nodeid in nodeids}
    expected = set(expected_paths)
    if observed_paths != expected:
        return {
            "ok": False,
            "error": f"collected module set differs: {sorted(observed_paths ^ expected)}",
            **counts,
        }
    if errored or xfailed or xpassed:
        return {"ok": False, "error": "errored/xfailed/xpassed items are never valid", **counts}
    if passed < 1:
        return {"ok": False, "error": "at least one passing item is required", **counts}
    if require_no_skips and skipped:
        return {"ok": False, "error": f"{skipped} skipped items in a no-skip leg", **counts}
    return {"ok": True, "error": None, **counts}


# ---------------------------------------------------------------------------
# Leg execution


def _env(repo: Path, *, activated: bool) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{repo}/phase-loop-runtime/src:{repo}/phase-loop-runtime/tests"
    if activated:
        env[RUNTIME_ACTIVATION_ENV] = "1"
    else:
        env.pop(RUNTIME_ACTIVATION_ENV, None)
    return env


def _pytest_argv(repo: Path, junit: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        *RUNTIME_TEST_MODULES,
        "-o",
        "junit_family=legacy",
        f"--junitxml={junit}",
        "-rsxX",
        "-q",
    ]


def _run_leg(repo: Path, evidence_dir: Path, *, activated: bool) -> dict[str, Any]:
    label = "red" if activated else "default"
    junit = evidence_dir / f"runtime-{label}.junit.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        _pytest_argv(repo, junit),
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(repo, activated=activated),
    )
    output = completed.stdout + completed.stderr
    (evidence_dir / f"runtime-{label}.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (evidence_dir / f"runtime-{label}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    return {
        "label": label,
        "returncode": completed.returncode,
        "output": output,
        "junit": junit,
        "junit_sha256": _sha256_bytes(junit.read_bytes()) if junit.is_file() else None,
        "raw_sha256": _sha256_bytes(output.encode("utf-8")),
    }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def preflight(repo: Path, evidence_dir: Path) -> tuple[int, dict[str, Any]]:
    """Run the default-GREEN and activated-RED legs and account for both exactly."""

    assert_all_production_anchors()

    default = _run_leg(repo, evidence_dir, activated=False)
    if default["returncode"] != 0:
        return 1, {"error": f"default leg must exit 0, got {default['returncode']}", **default}
    default_junit = verify_runtime_junit(
        default["junit"], expected_paths=RUNTIME_TEST_MODULES, require_no_skips=False
    )
    if not default_junit["ok"]:
        return 1, {"error": f"default leg accounting failed: {default_junit['error']}"}
    if RED_ANCHOR_MARKER in default["output"] or RUNTIME_RED_ANCHOR_PREFIX in default["output"]:
        return 1, {"error": "default leg must not emit any RED anchor"}

    red = _run_leg(repo, evidence_dir, activated=True)
    if red["returncode"] != 1:
        return 1, {"error": f"activated leg must exit 1, got {red['returncode']}", **red}
    if RED_ANCHOR_MARKER not in red["output"]:
        return 1, {"error": "activated leg is missing the generic RED anchor marker"}
    for marker in EXPECTED_RED_MARKERS:
        count = red["output"].count(marker)
        if count != 1:
            return 1, {"error": f"expected {marker} exactly once in the activated leg, got {count}"}
    red_junit = verify_runtime_junit(
        red["junit"], expected_paths=RUNTIME_TEST_MODULES, require_no_skips=True
    )
    if not red_junit["ok"]:
        return 1, {"error": f"activated leg accounting failed: {red_junit['error']}"}
    if red_junit["failed"] != len(RUNTIME_CASES):
        return 1, {
            "error": (
                f"activated leg must fail exactly at the {len(RUNTIME_CASES)} typed anchors, "
                f"got {red_junit['failed']}"
            )
        }
    return 0, {
        "default": {
            "returncode": default["returncode"],
            "junit_sha256": default["junit_sha256"],
            "raw_sha256": default["raw_sha256"],
            "counts": {k: default_junit[k] for k in ("passed", "failed", "skipped")},
        },
        "red": {
            "returncode": red["returncode"],
            "junit_sha256": red["junit_sha256"],
            "raw_sha256": red["raw_sha256"],
            "counts": {k: red_junit[k] for k in ("passed", "failed", "skipped")},
        },
    }


# ---------------------------------------------------------------------------
# Git helpers


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def _landing_ref(remote: str, branch: str) -> str:
    return f"{remote}/{branch}" if remote else branch


def _first_production_commit(repo: Path, landing_commit: str, head: str) -> str | None:
    """The first commit after ``landing_commit`` touching any mapped production path."""

    production_paths = sorted({case.production_path for case in RUNTIME_CASES.values()})
    revs = _git(
        repo, "rev-list", "--reverse", f"{landing_commit}..{head}", "--", *production_paths
    )
    lines = [line for line in revs.splitlines() if line.strip()]
    return lines[0] if lines else None


def _changed_paths(repo: Path, start: str, end: str) -> set[str]:
    diff = _git(repo, "diff", "--name-only", f"{start}..{end}")
    return {line.strip() for line in diff.splitlines() if line.strip()}


def _landing_blob_digest(repo: Path, landing_commit: str, relative: str) -> str | None:
    """The sha256 of ``relative`` as it was frozen in ``landing_commit``, or None."""

    completed = subprocess.run(
        ["git", "show", f"{landing_commit}:{relative}"], cwd=repo, capture_output=True
    )
    if completed.returncode:
        return None
    return _sha256_bytes(completed.stdout)


# ---------------------------------------------------------------------------
# SL-0 immutability

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def verify_sl0_landing_bytes(
    repo: Path,
    landing_commit: str,
    *,
    companion_inventory: Sequence[Any],
    receipt_files: Sequence[tuple[str, str]],
) -> str | None:
    """Return the first SL-0 immutability defect, or ``None`` when every byte holds.

    The frozen ``RUNTIME_INVENTORY`` -- never the companion and never the receipt --
    drives the walk, and every digest is compared against the *landing blob* rather
    than against either mutable record. Both records are ordinary files that anyone
    editing an SL-0 byte can rewrite in the same breath, so refreshing them around a
    later mutation, or dropping the mutated path from the companion's inventory, has
    to fail here rather than verify. The companion inventory must therefore be the
    exact closed cover of the SL-0 inventory: no missing, extra, or duplicated row.
    """

    declared: dict[str, str] = {}
    for item in companion_inventory:
        if not isinstance(item, dict):
            return f"companion inventory entry is not an object: {item!r}"
        relative = item.get("path")
        digest = item.get("sha256")
        if not isinstance(relative, str) or relative not in RUNTIME_INVENTORY:
            return f"companion inventory lists an out-of-inventory path: {relative!r}"
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            return f"companion inventory digest is malformed: {relative}"
        if relative in declared:
            return f"companion inventory duplicates {relative}"
        declared[relative] = digest
    uncovered = [relative for relative in RUNTIME_INVENTORY if relative not in declared]
    if uncovered:
        return f"companion inventory is not a closed SL-0 cover; missing: {uncovered}"

    recorded: dict[str, str] = {}
    for relative, digest in receipt_files:
        if relative in recorded:
            return f"receipt inventory duplicates {relative}"
        recorded[relative] = digest
    if tuple(sorted(recorded)) != RUNTIME_INVENTORY:
        return (
            "receipt inventory is not the closed SL-0 cover: "
            f"{sorted(set(recorded) ^ set(RUNTIME_INVENTORY))}"
        )

    for relative in RUNTIME_INVENTORY:
        landed = _landing_blob_digest(repo, landing_commit, relative)
        if landed is None:
            return f"{relative} is absent from the declared landing {landing_commit}"
        path = repo / relative
        if not path.is_file() or path.is_symlink():
            return f"SL-0 path is missing or is not a regular file: {relative}"
        if _sha256_path(path) != landed:
            return f"SL-0 byte changed after landing: {relative}"
        if declared[relative] != landed:
            return f"companion digest is not the landed byte: {relative}"
        if recorded[relative] != landed:
            return f"receipt digest is not the landed byte: {relative}"
    return None


# ---------------------------------------------------------------------------
# record / verify


def _companion_payload(
    *,
    repo: Path,
    receipt_path: Path,
    legs: dict[str, Any],
    landing_ref: str,
    landing_commit: str,
    base_commit: str,
    plan_path: str,
    roadmap_path: str,
    identity: str,
) -> dict[str, Any]:
    return {
        "schema": BINDING_SCHEMA,
        "phase": PHASE,
        "activation_env": RUNTIME_ACTIVATION_ENV,
        "red_anchor_prefix": RUNTIME_RED_ANCHOR_PREFIX,
        "generic_red_anchor_marker": RED_ANCHOR_MARKER,
        "typed_red_markers": list(EXPECTED_RED_MARKERS),
        "case_map": {
            case_id: {
                "lane": case.lane,
                "production_path": case.production_path,
                "symbol": case.symbol,
                "anchor": case.anchor,
            }
            for case_id, case in sorted(RUNTIME_CASES.items())
        },
        "sl0_inventory": [
            {"path": path, "sha256": _sha256_path(repo / path)} for path in RUNTIME_INVENTORY
        ],
        "test_modules": list(RUNTIME_TEST_MODULES),
        "production_union": {lane: list(paths) for lane, paths in PRODUCTION_UNION.items()},
        "legs": legs,
        "receipt_path": receipt_path.relative_to(repo).as_posix(),
        "receipt_sha256": _sha256_path(receipt_path),
        "identity": identity,
        "landing_ref": landing_ref,
        "landing_commit": landing_commit,
        "landing_tree_digest": _git(repo, "rev-parse", f"{landing_commit}^{{tree}}"),
        "base_commit": base_commit,
        "base_tree_digest": _git(repo, "rev-parse", f"{base_commit}^{{tree}}"),
        "base_is_ancestor_of_landing": True,
        "expected_first_production_parent": landing_commit,
        "plan_path": plan_path,
        "plan_sha256": _sha256_path(repo / plan_path),
        "roadmap_path": roadmap_path,
        "roadmap_sha256": _sha256_path(repo / roadmap_path),
    }


def _cmd_preflight(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    evidence_dir = repo / Path(args.receipt).parent
    code, detail = preflight(repo, evidence_dir)
    if code:
        print(f"runtime_content_tdd_adapter: preflight failed: {detail['error']}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "legs": detail}, indent=2, sort_keys=True))
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    receipt_path = repo / args.receipt
    binding_path = repo / args.binding
    evidence_dir = receipt_path.parent
    evidence_dir.mkdir(parents=True, exist_ok=True)

    code, legs = preflight(repo, evidence_dir)
    if code:
        print(f"runtime_content_tdd_adapter: preflight failed: {legs['error']}", file=sys.stderr)
        return 1

    landing_ref = _landing_ref(args.landing_remote, args.landing_branch)
    try:
        landing_commit = select_declared_commit(repo, landing_ref, args.identity)
    except Exception as exc:
        print(
            f"runtime_content_tdd_adapter: declared identity {args.identity!r} "
            f"not resolvable on {landing_ref}: {exc}",
            file=sys.stderr,
        )
        return 1

    red_command = " ".join(
        ["python3", "-m", "pytest", *RUNTIME_TEST_MODULES, "-q"]
    )
    previous = os.environ.get(RUNTIME_ACTIVATION_ENV)
    os.environ[RUNTIME_ACTIVATION_ENV] = "1"
    try:
        receipt = record_content_tdd_receipt(
            repo=repo,
            test_glob=RUNTIME_TEST_MODULES[0],
            red_command=red_command,
            landing_ref=landing_commit,
            out=receipt_path,
            support_paths=RUNTIME_INVENTORY,
        )
    except Exception as exc:
        print(f"runtime_content_tdd_adapter: receipt recording failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if previous is None:
            os.environ.pop(RUNTIME_ACTIVATION_ENV, None)
        else:
            os.environ[RUNTIME_ACTIVATION_ENV] = previous

    payload = _companion_payload(
        repo=repo,
        receipt_path=receipt_path,
        legs=legs,
        landing_ref=landing_ref,
        landing_commit=landing_commit,
        base_commit=receipt.base_commit,
        plan_path=args.plan,
        roadmap_path=args.roadmap,
        identity=args.identity,
    )
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "landing_commit": landing_commit}, sort_keys=True))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    receipt_path = repo / args.receipt
    binding_path = repo / args.binding

    for path in (receipt_path, binding_path):
        if not path.is_file():
            print(f"runtime_content_tdd_adapter: missing evidence: {path}", file=sys.stderr)
            return 1

    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"runtime_content_tdd_adapter: unparseable companion: {exc}", file=sys.stderr)
        return 1
    if binding.get("schema") != BINDING_SCHEMA:
        print("runtime_content_tdd_adapter: unsupported companion schema", file=sys.stderr)
        return 1

    landing_ref = _landing_ref(args.landing_remote, args.landing_branch)
    try:
        landing_commit = select_declared_commit(repo, landing_ref, args.identity)
    except Exception as exc:
        print(
            f"runtime_content_tdd_adapter: declared identity {args.identity!r} "
            f"not resolvable on {landing_ref}: {exc}",
            file=sys.stderr,
        )
        return 1
    if binding.get("landing_commit") != landing_commit:
        print("runtime_content_tdd_adapter: companion landing drift", file=sys.stderr)
        return 1

    try:
        receipt = verify_content_tdd_receipt(receipt_path=receipt_path, repo=repo)
    except Exception as exc:
        print(f"runtime_content_tdd_adapter: receipt verification failed: {exc}", file=sys.stderr)
        return 1
    if receipt.landing_commit != landing_commit:
        print("runtime_content_tdd_adapter: receipt landing drift", file=sys.stderr)
        return 1

    # The companion seals the exact receipt it was recorded against, so refreshed
    # receipt digests cannot be laundered past a companion that stayed still.
    declared_receipt = binding.get("receipt_path")
    if not isinstance(declared_receipt, str) or (
        repo / declared_receipt
    ).resolve() != receipt_path.resolve():
        print("runtime_content_tdd_adapter: companion seals a different receipt", file=sys.stderr)
        return 1
    if _sha256_path(receipt_path) != binding.get("receipt_sha256"):
        print("runtime_content_tdd_adapter: receipt digest drift from the companion",
              file=sys.stderr)
        return 1

    # The SL-0 bytes are immutable after their landing: no later edit is allowed,
    # and neither mutable record may stand in for the frozen landing blob.
    inventory = binding.get("sl0_inventory")
    defect = verify_sl0_landing_bytes(
        repo,
        landing_commit,
        companion_inventory=inventory if isinstance(inventory, list) else (),
        receipt_files=receipt.test_files,
    )
    if defect is not None:
        print(f"runtime_content_tdd_adapter: {defect}", file=sys.stderr)
        return 1

    # The case map, plan seal, and roadmap seal must all still hold.
    expected_map = {
        case_id: {
            "lane": case.lane,
            "production_path": case.production_path,
            "symbol": case.symbol,
            "anchor": case.anchor,
        }
        for case_id, case in RUNTIME_CASES.items()
    }
    if binding.get("case_map") != expected_map:
        print("runtime_content_tdd_adapter: case-map drift", file=sys.stderr)
        return 1
    for key, path_key in (("plan_sha256", "plan_path"), ("roadmap_sha256", "roadmap_path")):
        relative = binding.get(path_key, "")
        if _sha256_path(repo / relative) != binding.get(key):
            print(f"runtime_content_tdd_adapter: {relative} digest drift", file=sys.stderr)
            return 1

    # TDD chronology: no mapped production path may change at or before the landing,
    # and the first production commit's parent must be the declared landing itself.
    base_commit = binding.get("base_commit", "")
    touched_before = _changed_paths(repo, base_commit, landing_commit) & {
        case.production_path for case in RUNTIME_CASES.values()
    }
    if touched_before:
        print(
            f"runtime_content_tdd_adapter: production changed before the landing: "
            f"{sorted(touched_before)}",
            file=sys.stderr,
        )
        return 1
    first_production = _first_production_commit(repo, landing_commit, args.head)
    if first_production is not None:
        parents = _git(repo, "rev-list", "--parents", "-n", "1", first_production).split()[1:]
        if landing_commit not in parents:
            print(
                f"runtime_content_tdd_adapter: first production commit {first_production} "
                f"does not parent the declared landing {landing_commit}",
                file=sys.stderr,
            )
            return 1

    assert_all_production_anchors()
    print(
        json.dumps(
            {"ok": True, "landing_commit": landing_commit, "cases": len(RUNTIME_CASES)},
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RUNTIME SL-0 content-TDD adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "record", "verify"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--repo", type=Path, default=Path("."))
        sub.add_argument("--receipt", default=DEFAULT_RECEIPT_PATH)
        sub.add_argument("--binding", default=DEFAULT_BINDING_PATH)
        sub.add_argument("--plan", default=DEFAULT_PLAN_PATH)
        sub.add_argument("--roadmap", default=DEFAULT_ROADMAP_PATH)
        if name != "preflight":
            sub.add_argument("--landing-remote", default="origin")
            sub.add_argument("--landing-branch", default="main")
            sub.add_argument("--identity", required=True)
        if name == "verify":
            sub.add_argument("--head", default="HEAD")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {"preflight": _cmd_preflight, "record": _cmd_record, "verify": _cmd_verify}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
