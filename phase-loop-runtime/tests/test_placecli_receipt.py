"""PLACECLI receipt: observed producer results bound to the phase's own sources.

The receipt (``plans/evidence/placement/PLACECLI.md``) is reduced from JUnit per-node
outcomes copied back from ``ai``; ``scripts/stamp_evidence_receipt.py`` refreshes its source
bindings, and this validator runs last. Following agent-harness#1955 it pins no shared or
frequently changed file: only sources, tests, fixtures and frozen artifacts this phase
created.
"""

from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
RECEIPT = REPO / "plans/evidence/placement/PLACECLI.md"
PRODUCERS = ("test_placement_process_contract.py", "test_placement_lifecycle_process.py",
             "test_placement_bridge.py", "test_placement_cli.py")
GROUPS = ("V0", "V1", "V2", "V3")
PENDING = {"live_activation", "toolkit_cutover", "e2b_activation", "laneexec_launch"}
#: Shared or frequently changed files a receipt may never pin (ownership map receipt rule).
SHARED = {
    "CHANGELOG.md", "plans/manifest.json", ".doc-decisions.json", "README.md",
    "phase-loop-runtime/README.md", "phase-loop-runtime/pyproject.toml", "phase-loop-runtime/uv.lock",
    "phase-loop-runtime/tests/data/seat_launch_references.json",
    "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py",
    "phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py",
    "phase-loop-runtime/tests/test_seat_reference_inventory.py",
    "phase-loop-runtime/tests/test_gate_a_wheel_isolation.py",
    "phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py",
    "phase-loop-runtime/src/phase_loop_runtime/placement_lease.py",
    "phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py",
    "phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py",
    "phase-loop-runtime/src/phase_loop_runtime/cli.py",
    "phase-loop-runtime/tests/test_sandbox_placement.py",
    "phase-loop-runtime/tests/test_placement_lease.py",
    "phase-loop-runtime/tests/test_openshell_backend.py",
}
pytestmark = pytest.mark.skipif(not (REPO / "plans/manifest.json").is_file(),
                                reason="repository evidence is absent in standalone clean-room")


def read_receipt(path: Path = RECEIPT) -> dict:
    return json.loads(path.read_text().split("```json\n", 1)[1].split("\n```", 1)[0])


def shared(relative: str) -> bool:
    return (relative in SHARED or relative.startswith(".github/workflows/")
            or (relative.startswith("docs/") and relative.endswith(".md")))


@lru_cache(maxsize=1)
def current_nodes() -> frozenset[str]:
    nodes = set()
    for filename in PRODUCERS:
        result = subprocess.run(
            ["timeout", "900", sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
             str(REPO / "phase-loop-runtime/tests" / filename)],
            cwd=REPO / "phase-loop-runtime", capture_output=True, text=True, check=True)
        selected = {"tests/" + line.split("tests/", 1)[1] for line in result.stdout.splitlines()
                    if "tests/" + filename + "::" in line}
        assert selected, filename
        nodes.update(selected)
    return frozenset(nodes)


def validate_receipt(record: dict, *, inventory: bool = True) -> None:
    from test_placement_bridge import BRIDGE_CONTROLS
    from test_placement_lifecycle_process import MUTATION_CONTROLS

    assert record["authority"] == "synthetic_fixture_only"
    assert record["phase"] == "PLACECLI"
    assert record["gates"] == ["IF-0-PLACECLI-1", "IF-0-PLACECLI-2"]
    assert record["live_activation"] is False and record["public_conformance"] is False
    assert PENDING <= set(record["pending"])
    hashes = record["source_hashes"]
    assert hashes and not [relative for relative in hashes if shared(relative)]
    for relative, digest in hashes.items():
        assert sha256((REPO / relative).read_bytes()).hexdigest() == digest, relative
    assert {f"phase-loop-runtime/tests/{name}" for name in PRODUCERS} <= set(hashes)
    assert "plans/artifacts/v13-PLACECLI-contract-v1.schema.json" in hashes
    assert record["runner_stamp"]["source_tree_digest"] == sha256(
        json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    assert record["runner_stamp"]["host"] == "ai" and record["runner_stamp"]["observed_commit"]
    outcomes = record["producer_outcomes"]
    assert outcomes, "missing producer results"
    assert all(value == "passed" for value in outcomes.values()), "a producer did not pass"
    assert record["producer_passed"] == len(outcomes) and record["producer_skipped"] == 0
    if inventory:
        assert set(outcomes) == current_nodes()
    groups = record["groups"]
    assert list(groups) == list(GROUPS)
    for name in GROUPS:
        counts = groups[name]
        assert counts["passed"] > 0 and counts["failed"] == 0 and counts["errors"] == 0, name
    expected = {"lifecycle": sorted(MUTATION_CONTROLS), "bridge": sorted(BRIDGE_CONTROLS),
                "cli": ["stdout-refusal"]}
    assert record["mutation_controls"] == expected
    for control in expected["lifecycle"]:
        for kind in ("intact", "killed"):
            node = f"tests/test_placement_lifecycle_process.py::test_lifecycle_mutation_controls[{control}-{kind}]"
            assert outcomes[node] == "passed", node
    for control in expected["bridge"]:
        for kind in ("intact", "killed"):
            node = f"tests/test_placement_bridge.py::test_bridge_mutation_controls[{control}-{kind}]"
            assert outcomes[node] == "passed", node
    for kind in ("intact", "killed"):
        node = f"tests/test_placement_cli.py::test_t2_mutation_control_a_json_refusal_on_stdout_is_caught[{kind}]"
        assert outcomes[node] == "passed", node
    assert set(record["ec_status"]) == {f"EC-PLACECLI-{n}" for n in range(1, 6)}
    assert all(value == "local_fixture_pass_pending_activation" for value in record["ec_status"].values())
    durations = record["producer_duration_seconds"]
    assert set(durations) == set(outcomes) and all(value >= 0 for value in durations.values())
    assert record["slow_nodes_over_300_seconds"] == sorted(n for n, v in durations.items() if v > 300)


def test_receipt_observed_results_and_current_inventory():
    validate_receipt(read_receipt())


@pytest.mark.parametrize("control", ["missing-results", "skipped-only", "failed-result", "stale-hash",
                                     "shared-pin", "workflow-pin", "doc-pin", "live-claim",
                                     "false-authority", "missing-mutation", "false-count", "wrong-host"])
def test_receipt_falsifiers(control):
    record = read_receipt()
    validate_receipt(record, inventory=False)
    if control == "missing-results":
        record["producer_outcomes"] = {}
    elif control == "skipped-only":
        record["producer_outcomes"] = {node: "skipped" for node in record["producer_outcomes"]}
        record["producer_skipped"] = len(record["producer_outcomes"])
    elif control == "failed-result":
        record["producer_outcomes"][next(iter(record["producer_outcomes"]))] = "failed"
    elif control == "stale-hash":
        record["source_hashes"][next(iter(record["source_hashes"]))] = "0" * 64
    elif control == "shared-pin":
        record["source_hashes"]["CHANGELOG.md"] = sha256((REPO / "CHANGELOG.md").read_bytes()).hexdigest()
    elif control == "workflow-pin":
        record["source_hashes"][".github/workflows/test.yml"] = "0" * 64
    elif control == "doc-pin":
        record["source_hashes"]["docs/placement-process-cli.md"] = sha256(
            (REPO / "docs/placement-process-cli.md").read_bytes()).hexdigest()
    elif control == "live-claim":
        record["live_activation"] = True
    elif control == "false-authority":
        record["authority"] = "live_qualification"
    elif control == "missing-mutation":
        record["mutation_controls"]["lifecycle"].pop()
    elif control == "false-count":
        record["producer_passed"] += 1
    elif control == "wrong-host":
        record["runner_stamp"]["host"] = "dev0"
    with pytest.raises(AssertionError):
        validate_receipt(record, inventory=False)
