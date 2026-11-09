"""WORKER receipt binds observed producer results and deferred SCHEMA ownership."""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from phase_loop_runtime import supervised_launch
from test_supervised_launch import case as _case, prepare
from test_convergence_adapters import CAPTURE_CONTROLS
from test_supervised_worker import WORKER_CONTROLS, CANCEL_CONTROLS
from test_supervised_worker_cli import CLI_CONTROLS

case = _case
REPO = Path(__file__).resolve().parents[2]
RECEIPT = REPO / "plans/evidence/supervised-worker/WORKER.md"
SCHEMA = REPO / "plans/evidence/supervised-worker/SCHEMA.md"
PRODUCERS = ("test_convergence_adapters.py", "test_supervised_worker.py", "test_supervised_worker_cli.py")
PENDING = {"public_reconciliation", "installed_tool_qualification", "registry_activation", "closeout_codec_wiring"}
pytestmark = pytest.mark.skipif(not (REPO / "plans/manifest.json").is_file(),
                                reason="repository evidence is absent in standalone clean-room")


def read_receipt(path=RECEIPT):
    return json.loads(path.read_text().split("```json\n", 1)[1].split("\n```", 1)[0])


def deferred_obligations():
    schema = read_receipt(SCHEMA)
    return sorted((section, row["id"]) for section in
        ("coverage_inventory", "semantic_cases", "semantic_inventory") for row in schema[section]
        if "WORKER" in row["owner"])


@lru_cache(maxsize=1)
def current_nodes():
    nodes = set()
    for filename in PRODUCERS:
        result = subprocess.run(["timeout", "900", sys.executable, "-m", "pytest", "--collect-only", "-q",
            "-p", "no:cacheprovider", str(REPO / "phase-loop-runtime/tests" / filename)],
            cwd=REPO, capture_output=True, text=True, check=True)
        selected = {"tests/" + line.split("tests/", 1)[1] for line in result.stdout.splitlines()
                    if "tests/" + filename + "::" in line}
        assert selected
        nodes.update(selected)
    return nodes


def validate_receipt(record, *, inventory=True):
    assert record["authority"] == "synthetic_fixture_only"
    assert record["phase"] == "WORKER" and record["gate"] == "IF-0-WORKER-1"
    assert not record["public_conformance"] and not record["installed_provider_qualified"]
    assert PENDING <= set(record["pending"])
    hashes = record["source_hashes"]
    assert {"CHANGELOG.md", "phase-loop-runtime/tests/data/seat_launch_references.json"}.isdisjoint(hashes)
    for relative, digest in hashes.items():
        assert sha256((REPO / relative).read_bytes()).hexdigest() == digest, relative
    assert len(hashes) >= 12
    assert record["runner_stamp"]["source_tree_digest"] == sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    assert record["runner_stamp"]["host"] == "ai" and record["runner_stamp"]["observed_commit"]
    outcomes = record["producer_outcomes"]
    assert outcomes and all(value == "passed" for value in outcomes.values())
    assert record["producer_passed"] == len(outcomes) and record["producer_skipped"] == 0
    if inventory:
        assert set(outcomes) == current_nodes()
    expected = {"capture": sorted(CAPTURE_CONTROLS), "worker": sorted(WORKER_CONTROLS),
                "cancel": sorted(CANCEL_CONTROLS), "cli": sorted(CLI_CONTROLS), "codex": ["provider-basename"]}
    assert record["mutation_controls"] == expected
    for control in expected["capture"]:
        for kind in ("intact", "killed"):
            assert outcomes[f"tests/test_convergence_adapters.py::test_worker_capture_source_controls[{kind}-{control}]"] == "passed"
    for family, function, filename in (("worker", "test_worker_source_controls", "test_supervised_worker.py"),
            ("cancel", "test_cancel_source_controls", "test_supervised_worker.py"),
            ("cli", "test_cli_source_controls", "test_supervised_worker_cli.py")):
        for control in expected[family]:
            for kind in ("intact", "killed"):
                assert outcomes[f"tests/{filename}::{function}[{kind}-{control}]"] == "passed"
    for kind in ("intact", "killed"):
        assert outcomes[f"tests/test_supervised_worker.py::test_codex_basename_source_control[{kind}]"] == "passed"
    deferred = record["deferred_obligations"]
    assert sorted((row["section"], row["id"]) for row in deferred) == deferred_obligations()
    assert len(deferred) == 113
    assert all(row["owner"] == "CLOSEOUT" and row["status"] == "upstream_phase_unmet" for row in deferred)
    assert set(record["journal_reconciliation"]) == {"J1", "J2", "J3", "J4", "J5", "J6"}
    assert set(record["ec_status"]) == {f"EC-WORKER-{n}" for n in range(1, 5)}
    assert all(value == "local_fixture_pass_pending_closeout" for value in record["ec_status"].values())
    durations = record["producer_duration_seconds"]
    assert set(durations) == set(outcomes) and all(value >= 0 for value in durations.values())
    assert record["slow_nodes_over_300_seconds"] == sorted(node for node, value in durations.items() if value > 300)


def test_receipt_observed_results_and_current_inventory(case):
    prepared = prepare(case)
    assert isinstance(supervised_launch.consume_admission(prepared), supervised_launch.LaunchInputs)
    validate_receipt(read_receipt())


@pytest.mark.parametrize("control", ["stale-binding", "missing-results", "failed-result", "false-authority",
    "false-qualification", "resolved-deferred", "missing-deferred", "missing-mutation", "false-count"])
def test_receipt_falsifiers_after_production_entry(case, control):
    prepared = prepare(case)
    assert isinstance(supervised_launch.consume_admission(prepared), supervised_launch.LaunchInputs)
    record = read_receipt()
    validate_receipt(record, inventory=False)
    if control == "stale-binding":
        record["source_hashes"][next(iter(record["source_hashes"]))] = "stale"
    elif control == "missing-results":
        record["producer_outcomes"] = {}
    elif control == "failed-result":
        record["producer_outcomes"][next(iter(record["producer_outcomes"]))] = "failed"
    elif control == "false-authority":
        record["authority"] = "public_conformance"
    elif control == "false-qualification":
        record["installed_provider_qualified"] = True
    elif control == "resolved-deferred":
        record["deferred_obligations"][0]["status"] = "resolved"
    elif control == "missing-deferred":
        record["deferred_obligations"].pop()
    elif control == "missing-mutation":
        record["mutation_controls"]["capture"].pop()
    elif control == "false-count":
        record["producer_passed"] += 1
    with pytest.raises(AssertionError):
        validate_receipt(record, inventory=False)
