"""JOURNAL receipt reduction: observed producer results and bindings, never text snapshots."""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

import _run_status_vectors as vectors
from phase_loop_runtime import run_status as rs
from phase_loop_runtime import run_status_projection as projection
from test_run_status import CONTROLS as SL0_CONTROLS
from test_run_status_projection import CONTROLS as SL1_CONTROLS

REPO = Path(__file__).resolve().parents[2]
RECEIPT = REPO / "plans/evidence/supervised-worker/JOURNAL.md"
SCHEMA_RECEIPT = REPO / "plans/evidence/supervised-worker/SCHEMA.md"
ARTIFACT = "plans/artifacts/v12-JOURNAL-interface.md"
PRODUCERS = ("test_run_status.py", "test_run_status_projection.py")
EC_IDS = ("EC-JOURNAL-1", "EC-JOURNAL-2", "EC-JOURNAL-3", "EC-JOURNAL-4")
INTERPRETERS = ("3.12", "3.14")
REQUIRED_SOURCES = {
    "phase-loop-runtime/src/phase_loop_runtime/run_status.py",
    "phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py",
    "phase-loop-runtime/tests/_run_status_vectors.py",
    "phase-loop-runtime/tests/test_run_status.py",
    "phase-loop-runtime/tests/test_run_status_projection.py",
    "phase-loop-runtime/tests/test_run_status_receipt.py",
    "phase-loop-runtime/tests/data/seat_launch_references.json",
    "phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/run-status.schema.json",
    "phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/conformance/run-status.vectors.json",
    "docs/supervised-run-status.md",
    ARTIFACT,
}
PENDING = {"final_tree_revalidation", "hosted_ci", "full_repository_suite", "exact_head_gate_a",
           "independent_review", "closeout_v2_reconciliation", "registry_activation"}
pytestmark = pytest.mark.skipif(not (REPO / "plans/manifest.json").is_file(),
                                reason="repository evidence is absent in standalone clean-room")


def read_receipt(path=RECEIPT):
    blocks = re.findall(r"```json\n(.*?)\n```", path.read_text(), re.S)
    assert len(blocks) == 1
    return json.loads(blocks[0])


def digest(relative):
    return sha256((REPO / relative).read_bytes()).hexdigest()


def manifest_seal():
    manifest = json.loads((REPO / "plans/manifest.json").read_text())
    [entry] = [item for item in manifest["plans"] if item["slug"] == "v12-JOURNAL"]
    return entry["frozen_inputs"][ARTIFACT]["sha256"]


def schema_obligations():
    record = read_receipt(SCHEMA_RECEIPT)
    named = sorted(row["id"] for row in record["semantic_inventory"] if "JOURNAL" in row["owner"])
    cases = sorted(row["id"] for row in record["semantic_cases"] if "JOURNAL" in row["owner"])
    return named, cases


def consumer_obligation_counts():
    text = (REPO / ARTIFACT).read_text().split("## 11.", 1)[1].split("## 12.", 1)[0]
    counts, owner = {}, None
    for line in text.splitlines():
        match = re.fullmatch(r"- \*\*([A-Z]+)\*\*", line)
        if match:
            owner = match.group(1)
            counts[owner] = 0
        elif owner and line.startswith("  - "):
            counts[owner] += 1
    return counts


@lru_cache(maxsize=1)
def current_producer_nodes():
    nodes = set()
    for filename in PRODUCERS:
        # Collect one owned file at a time; never collect the repository.
        result = subprocess.run(
            ["timeout", "900", sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
             str(REPO / "phase-loop-runtime/tests" / filename)],
            cwd=REPO, capture_output=True, text=True, check=True)
        selected = {"tests/" + line.split("tests/", 1)[1] for line in result.stdout.splitlines()
                    if "tests/" + filename + "::" in line}
        assert selected, filename
        nodes |= selected
    return nodes


def validate_receipt(record):
    assert record["authority"] == "local_reconciliation_evidence"
    assert record["gate"] == "IF-0-JOURNAL-1" and record["phase"] == "JOURNAL"
    hashes = record["source_hashes"]
    assert REQUIRED_SOURCES <= set(hashes)
    for relative, value in hashes.items():
        assert digest(relative) == value, relative
    assert record["frozen_artifact"] == {"path": ARTIFACT, "sha256": manifest_seal()}
    assert digest(ARTIFACT) == manifest_seal()
    nodes, outcomes = record["producer_nodes"], record["producer_outcomes"]
    assert nodes and len(nodes) == len(set(nodes)) and set(outcomes) == set(nodes)
    assert all(value == "passed" for value in outcomes.values())
    assert {node.split("::")[0].rsplit("/", 1)[-1] for node in nodes} == set(PRODUCERS)
    assert set(record["producer_runs"]) == set(INTERPRETERS)
    for run in record["producer_runs"].values():
        assert run["passed"] == len(nodes) and run["skipped"] == 0 and run["failed"] == 0
        assert re.fullmatch(r"[0-9a-f]{64}", run["junit_sha256"])
    assert record["mutation_outcomes"] == dict.fromkeys([*SL0_CONTROLS, *SL1_CONTROLS], "killed")
    for prefix, controls, killed in (("tests/test_run_status.py", SL0_CONTROLS, "test_run_status_mutation_killed"),
                                     ("tests/test_run_status_projection.py", SL1_CONTROLS,
                                      "test_run_status_projection_mutation_killed")):
        for control in controls:
            assert outcomes[f"{prefix}::{killed}[{control}]"] == "passed", control
            assert outcomes[f"{prefix}::test_production_control_witness[{control}]"] == "passed", control
    assert record["vector_outcomes"] == dict.fromkeys(sorted(c["id"] for c in vectors.cases()), "passed")
    for case_id in record["vector_outcomes"]:
        assert any(node.endswith(f"[{case_id}]") for node in nodes), case_id
    assert set(record["ec_status"]) == set(EC_IDS)
    if record["final_tree_validated"]:
        assert all(value == "local_pass" for value in record["ec_status"].values())
    else:
        assert all(value == "pending_hosted_ci" for value in record["ec_status"].values())
        assert "final_tree_revalidation" in record["pending"]
    assert PENDING - {"final_tree_revalidation"} <= set(record["pending"])
    named, cases = schema_obligations()
    deferred = record["deferred_obligations"]
    assert sorted(row["id"] for row in deferred["schema_named"]) == named and named
    assert sorted(row["id"] for row in deferred["schema_cases"]) == cases and len(cases) == 35
    for row in deferred["schema_named"] + deferred["schema_cases"]:
        assert row["owner"] == "CLOSEOUT" and row["status"] == "upstream_phase_unmet"
    consumers = deferred["consumer_obligations"]
    assert {owner: len(rows) for owner, rows in consumers.items()} == consumer_obligation_counts()
    for owner, rows in consumers.items():
        for position, row in enumerate(rows, 1):
            assert row == {"pointer": f"{ARTIFACT}#11/{owner}/{position}", "status": "deferred_to_owner"}
    assert record["preimplementation_selected"] == 0
    assert record["runner_stamp"]["observed_utc"]
    assert record["runner_stamp"]["source_tree_digest"] == sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


A = sha256(b"receipt-assignment").hexdigest()


def production_entry(tmp_path):
    previous = os.umask(0o077)
    try:
        root = rs.open_journal_root(tmp_path / "journal", create=True)
        assert isinstance(root, rs.JournalRoot), root
        identity = rs.AttemptIdentity(A, A, "run-1", "attempt-1")
        reservation = rs.reserve_attempt(root, identity, units=rs.Units(("unit:target",), (), A),
                                         launch_digest=A, caller_context_sha256=A)
        assert isinstance(reservation, rs.Reservation)
        writer = rs.open_writer(root, reservation)
        assert isinstance(writer, rs.AttemptWriter)
        writer.state("queued", worker_invocations=0)
        writer.state("running", worker_invocations=1)
        head = writer.terminal("finished", worker_invocations=1, termination=rs.Termination("completed", None, "worker"),
                               refusal=None, result_binding=rs.ResultBinding(A, "run-1", "attempt-1", None, A))
        writer.close()
        assert isinstance(head, rs.ChainHead)
        result = projection.project_assignment(root, A)
        assert [item["state"] for item in result.projection["attempts"]] == ["finished"]
        assert result.projection["attempts"][0]["journal_seq"] == head.last_seq
        assert projection.check_projection(result.projection, root) == ()
        with open(root.path / "attempts/attempt-1/0000.jsonl", "ab") as handle:
            handle.write(b'{"attempt":')
        assert rs.read_attempt(root, "attempt-1").diagnostics == ("journal_torn_line",)
    finally:
        os.umask(previous)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the journal writer is Linux-only")
def test_receipt_production_round_trip_and_torn_read(tmp_path):
    production_entry(tmp_path)
    validate_receipt(read_receipt())


def test_receipt_observed_producer_results():
    record = read_receipt()
    validate_receipt(record)
    assert record["observed_checks"]


def test_receipt_matches_current_collection():
    assert set(read_receipt()["producer_nodes"]) == current_producer_nodes()


FALSIFICATIONS = ["stale_binding", "missing_results", "skipped_only", "failed_result", "false_authority",
                  "stale_artifact_seal", "missing_obligation", "missing_mutation", "false_readiness"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the journal writer is Linux-only")
@pytest.mark.parametrize("control", FALSIFICATIONS)
def test_receipt_falsified_after_production_entry(tmp_path, control):
    production_entry(tmp_path)
    record = read_receipt()
    validate_receipt(record)
    if control == "stale_binding":
        record["source_hashes"][next(iter(record["source_hashes"]))] = "0" * 64
    elif control == "missing_results":
        record["producer_outcomes"].pop(record["producer_nodes"].pop())
    elif control == "skipped_only":
        record["producer_outcomes"] = dict.fromkeys(record["producer_nodes"], "skipped")
        for run in record["producer_runs"].values():
            run["passed"], run["skipped"] = 0, len(record["producer_nodes"])
    elif control == "failed_result":
        record["producer_outcomes"][record["producer_nodes"][0]] = "failed"
    elif control == "false_authority":
        record["authority"] = "authoritative_public_contract"
    elif control == "stale_artifact_seal":
        record["frozen_artifact"]["sha256"] = "0" * 64
    elif control == "missing_obligation":
        record["deferred_obligations"]["schema_named"].pop()
    elif control == "missing_mutation":
        record["mutation_outcomes"].pop(next(iter(SL1_CONTROLS)))
    else:
        record["ec_status"] = dict.fromkeys(EC_IDS, "local_pass")
    temporary = tmp_path / "JOURNAL.md"
    temporary.write_text("```json\n" + json.dumps(record) + "\n```\n")
    with pytest.raises(AssertionError):
        validate_receipt(read_receipt(temporary))
