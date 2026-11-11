"""Receipt reduction consumes observed producer artifacts, not text snapshots."""
import hashlib
import inspect
import json
from functools import lru_cache
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
pytestmark = pytest.mark.skipif(not (REPO / "plans/manifest.json").is_file(),
                                reason="repository evidence is absent in standalone clean-room")
PRODUCERS = ["test_supervised_launch.py", "test_supervised_launch_mutations.py",
             "test_supervised_launch_binding.py", "test_supervised_launch_route.py"]


@lru_cache(maxsize=1)
def current_producer_nodes():
    nodes = set()
    for filename in PRODUCERS:
        # Collect only one owned file at a time; never collect the repository.
        result = subprocess.run(
            ["timeout", "900", sys.executable, "-m", "pytest", "--collect-only", "-q",
             "-p", "no:cacheprovider", str(REPO / "phase-loop-runtime/tests" / filename)],
            cwd=REPO, capture_output=True, text=True, check=True)
        selected = {"tests/" + line.split("tests/", 1)[1] for line in result.stdout.splitlines()
                    if "tests/" + filename + "::" in line}
        assert selected
        nodes.update(selected)
    return nodes


def read_receipt(path):
    return json.loads(path.read_text().split("```json\n", 1)[1].split("\n```", 1)[0])


def validate_receipt(record):
    from historical_receipts import verify_historical_receipt
    verify_historical_receipt(RECEIPT, record=record, producer_nodes=current_producer_nodes(), mutation_controls=CONTROLS)
    assert record["authority"] == "synthetic_fixture_only"
    assert record["gate"] == "IF-0-ENVELOPE-1"
    assert set(CONTROLS) <= set(record["mutation_controls"])
    assert len(record["source_hashes"]) >= 8
    nodes = record["producer_nodes"]
    outcomes = record["producer_outcomes"]
    assert len(nodes) == len(set(nodes))
    assert set(outcomes) == set(nodes)
    assert record["producer_passed"] == sum(value == "passed" for value in outcomes.values())
    assert record["producer_skipped"] == sum(value == "skipped" for value in outcomes.values())
    assert outcomes and all(value == "passed" for value in outcomes.values())
    assert set(record["ec_status"]) == {"EC-ENVELOPE-1", "EC-ENVELOPE-2", "EC-ENVELOPE-3"}
    observed_files = {node.split("::")[0].split("/")[-1] for node in nodes}
    assert observed_files <= set(PRODUCERS)
    if record["final_tree_validated"]:
        assert observed_files == set(PRODUCERS)
        assert set(nodes) <= current_producer_nodes()
        assert all(value == "local_fixture_pass" for value in record["ec_status"].values())
    else:
        assert all(value == "pending_hosted_ci" for value in record["ec_status"].values())
        assert "final_tree_revalidation" in record["pending"]
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


def test_receipt_observed_producer_results():
    record = read_receipt(RECEIPT)
    validate_receipt(record)
    assert record["producer_outcomes"]


@pytest.mark.parametrize("live_state", ["missing", "different"])
def test_historical_validation_is_independent_of_live_sources(tmp_path, monkeypatch, live_state):
    record = read_receipt(RECEIPT)
    current_producer_nodes()
    if live_state == "different":
        for relative in record["source_hashes"]:
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"unrelated synthetic live source\n")
    monkeypatch.setattr(__import__(__name__, fromlist=["REPO"]), "REPO", tmp_path)
    validate_receipt(record)


@pytest.mark.parametrize("control", ["stale_binding", "missing_results", "false_authority", "failed_result", "false_readiness"])
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
    elif control == "failed_result":
        record["producer_outcomes"][record["producer_nodes"][0]] = "failed"
        record["producer_passed"] -= 1
    elif control == "false_readiness":
        record["ec_status"] = dict.fromkeys(record["ec_status"], "local_fixture_pass")
    else:
        record["authority"] = "authoritative_public_contract"
    temporary = tmp_path / "receipt.md"
    temporary.write_text("```json\n" + json.dumps(record) + "\n```\n")
    with pytest.raises(AssertionError):
        validate_receipt(read_receipt(temporary))


def test_receipt_current_inventory(monkeypatch):
    from historical_receipts import verify_historical_receipt
    record = read_receipt(RECEIPT)
    current = current_producer_nodes()
    verify_historical_receipt(RECEIPT, record=record, producer_nodes=current, mutation_controls=CONTROLS)
    node = record["producer_nodes"][0]
    with pytest.raises(AssertionError):
        verify_historical_receipt(RECEIPT, record=record, producer_nodes=current - {node}, mutation_controls=CONTROLS)
    source = inspect.getsource(verify_historical_receipt)
    needle = '    assert required <= {normalize(node) for node in producer_nodes}'
    assert source.count(needle) == 1
    import historical_receipts
    namespace = dict(vars(historical_receipts))
    exec(compile(source.replace(needle, '    pass'), __file__, "exec"), namespace)
    namespace["verify_historical_receipt"](RECEIPT, record=record, producer_nodes=current - {node}, mutation_controls=CONTROLS)

