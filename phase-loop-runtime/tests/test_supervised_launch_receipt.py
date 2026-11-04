"""Receipt reduction consumes observed producer artifacts, not text snapshots."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from phase_loop_runtime import supervised_launch as launch
from test_supervised_launch import case as _case, prepare, refused
from test_supervised_launch_mutations import CONTROLS

case = _case
REPO = Path(__file__).resolve().parents[2]
RECEIPT = REPO / "plans/evidence/supervised-worker/ENVELOPE.md"
PRODUCERS = ["test_supervised_launch.py", "test_supervised_launch_mutations.py",
             "test_supervised_launch_binding.py", "test_supervised_launch_route.py"]


def read_receipt(path):
    return json.loads(path.read_text().split("```json\n", 1)[1].split("\n```", 1)[0])


def validate_receipt(record):
    assert record["authority"] == "synthetic_fixture_only"
    assert record["gate"] == "IF-0-ENVELOPE-1"
    assert record["ec_status"] == {"EC-ENVELOPE-1": "local_fixture_pass",
                                    "EC-ENVELOPE-2": "local_fixture_pass", "EC-ENVELOPE-3": "local_fixture_pass"}
    assert set(CONTROLS) <= set(record["mutation_controls"])
    for relative, digest in record["source_hashes"].items():
        assert hashlib.sha256((REPO / relative).read_bytes()).hexdigest() == digest, relative
    assert len(record["source_hashes"]) >= 8
    nodes = record["producer_nodes"]
    assert len(nodes) == len(set(nodes)) == record["producer_passed"]
    assert {node.split("::")[0].split("/")[-1] for node in nodes} == set(PRODUCERS)
    assert record["producer_skipped"] == 0
    assert record["preimplementation_selected"] == 0
    assert set(record["pending"]) >= {"public_schema_reconciliation", "installed_tool_qualification", "registry_activation"}
    assert record["runner_stamp"]["observed_utc"]
    assert record["runner_stamp"]["source_tree_digest"] == hashlib.sha256(
        json.dumps(record["source_hashes"], sort_keys=True).encode()).hexdigest()


def test_receipt_production_single_use_and_refusal(case):
    result = prepare(case)
    assert isinstance(launch.consume_admission(result), launch.LaunchInputs)
    assert launch.consume_admission(result) == launch.Refused("token_spent")
    case.envelope["launch_inputs"]["tier"] = "os_enforced"
    refused(case, reason="tier_unsupported")
    validate_receipt(read_receipt(RECEIPT))


def test_receipt_collected_producer_results():
    record = read_receipt(RECEIPT)
    validate_receipt(record)
    env = dict(os.environ, PYTHONPATH=f"{REPO / 'phase-loop-runtime/src'}:{REPO / 'phase-loop-runtime/tests'}")
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                             *[f"phase-loop-runtime/tests/{name}" for name in PRODUCERS]],
                            cwd=REPO, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    nodes = sorted(line for line in result.stdout.splitlines() if "::" in line)
    assert nodes == sorted(record["producer_nodes"])


@pytest.mark.parametrize("control", ["stale_binding", "missing_results", "false_authority"])
def test_receipt_mutations_after_production_entry(case, tmp_path, control):
    result = prepare(case)
    assert isinstance(launch.consume_admission(result), launch.LaunchInputs)
    record = read_receipt(RECEIPT)
    validate_receipt(record)
    if control == "stale_binding":
        key = next(iter(record["source_hashes"]))
        record["source_hashes"][key] = "stale"
    elif control == "missing_results":
        record["producer_nodes"].pop()
    else:
        record["authority"] = "authoritative_public_contract"
    temporary = tmp_path / "receipt.md"
    temporary.write_text("```json\n" + json.dumps(record) + "\n```\n")
    with pytest.raises(AssertionError):
        validate_receipt(read_receipt(temporary))
