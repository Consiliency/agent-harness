"""Receipt checks and explicit post-suite runner stamp (no predicted outcomes)."""
from collections import Counter
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest

import phase_loop_runtime.supervised_contracts as production
import test_supervised_contracts as intake
import test_supervised_contracts_mutations as mutations
import test_supervised_contracts_vectors as vectors

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "plans/evidence/supervised-worker/SCHEMA.md"
GROUPS = {"test_supervised_contracts": "intake_results", "test_supervised_contracts_vectors": "schema_results",
          "test_supervised_contracts_mutations": "mutation_results"}


def read_receipt(path=RECEIPT):
    text = path.read_text()
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
    assert len(blocks) == 1
    return json.loads(blocks[0])


def named_inventory():
    text = intake.INPUT.read_text().split("## Named coverage obligations\n", 1)[1].split("## Verification requirements", 1)[0]
    return [{"id": "named:" + name, "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/" + name,
             "vector_ids": [], "owner": owner.strip(), "status": "upstream_phase_unmet",
             "required_proof": "owner publication reconciliation and production proof at CLOSEOUT"}
            for name, owner in re.findall(r"^\| ([a-z][a-z-]+) \| [^\n]+? \| ([^|]+) \|$", text, re.M)]


def case_inventory():
    return [{"id": c["id"], "family": family, "expected_diagnostics": c["expected"],
             "expected_effect": c.get("expected_effect"), "classification": "schema_only",
             "status": "upstream_phase_unmet", "owner": "ENVELOPE/WORKER" if family == vectors.ENVELOPE else "JOURNAL/WORKER"}
            for family in vectors.FILES for c in vectors.corpus(family)]


def tier_inventory(bundle):
    tiers = json.loads(bundle.resource_bytes("admitted-launch-envelope.schema.json"))["x-enforcement-tiers"]
    return {name: {key: value[key] for key in ("qualified", "workspace_kinds", "constraints")} for name, value in tiers.items()}


def coverage_inventory():
    # Each claimed absence has a resolvable parent pointer and explicit absent keys.
    dimensions = {
        "instruction-reference": ("/properties", ["instruction_digest", "reference_digests"]),
        "argv": ("/properties", ["argv", "argv_digest"]),
        "executable-wrapper": ("/properties/executable_dependencies/properties", ["executable_digest", "wrapper_digest"]),
        "workspace-source-baseline": ("/properties/workspace/properties", ["source_digest", "baseline_digest"]),
        "timeout": ("/properties", ["timeout_seconds", "declared_bound"]),
        "effective-environment": ("/properties", ["effective_environment_digest"]),
        "policy-qualification": ("/properties/enforcement/properties", ["policy_digest", "qualification_digest"]),
        "action-route-delivery": ("/properties", ["action", "route", "delivery"]),
        "execution-view-egress": ("/properties", ["execution_view_digest", "egress_grant_digest"]),
    }
    return [{"id": name, "source_pointer": "admitted-launch-envelope.schema.json#" + pointer,
             "absent_keys": keys, "status": "upstream_phase_unmet", "owner": "ENVELOPE/WORKER; CLOSEOUT"}
            for name, (pointer, keys) in dimensions.items()]


def expected_functions(module):
    counts = {}
    for name, function in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("test_") or function.__module__ != module.__name__:
            continue
        count = 1
        for marker in getattr(function, "pytestmark", []):
            if marker.name == "parametrize":
                count *= len(marker.args[1])
        counts[name] = count
    return Counter(counts)


def check_results(data):
    for module in (intake, vectors, mutations):
        group = GROUPS[module.__name__]
        rows = data[group]
        assert rows
        counts = Counter()
        nodes = set()
        for row in rows:
            assert set(row) == {"group", "test_node_id", "case_or_control_id", "resource_sha256", "outcome", "runner_artifact_ref"}
            assert row["group"] == group and row["outcome"] == "passed"
            assert row["resource_sha256"] == data["resource_sha256"]
            node = row["test_node_id"]
            assert node.startswith("phase-loop-runtime/tests/" + module.__name__ + ".py::test_")
            assert node not in nodes
            nodes.add(node)
            counts[node.split("::", 1)[1].split("[", 1)[0]] += 1
            assert row["case_or_control_id"] == node.split("::", 1)[1]
            assert row["runner_artifact_ref"] == "schema-suite-junit.xml#" + node
        assert counts == expected_functions(module)
    schema_nodes = {r["test_node_id"].split("::", 1)[1] for r in data["schema_results"]}
    assert {"test_published_schema_only[" + c["id"] + "]" for c in case_inventory()} <= schema_nodes
    mutation_nodes = {r["case_or_control_id"] for r in data["mutation_results"]}
    assert {"test_production_control[" + c + "]" for c in mutations.CONTROLS} <= mutation_nodes
    assert {"test_every_definition_selector_control[" + c + "]" for c in production._DEFINITIONS} <= mutation_nodes
    assert {"test_vector_helper_control[patch]", "test_vector_helper_control[rehash]",
            "test_reference_integrity_complete_repin", "test_offline_reference_control"} <= mutation_nodes


def verify(data):
    bundle = intake.anchor()
    production.validate_record(bundle, vectors.ENVELOPE, vectors.encoded(vectors.expand(vectors.ENVELOPE, "E-admitted")["envelope"]))
    assert data["byte_pin_authority"] is False
    assert data["input_artifact_sha256"] == production.INPUT_ARTIFACT_SHA256
    assert data["source_commit"] == production.SOURCE_COMMIT
    assert data["resource_sha256"] == {n: sha256(bundle.resource_bytes(n)).hexdigest() for n in production._NAMES}
    assert data["module_sha256"] == sha256(Path(production.__file__).read_bytes()).hexdigest()
    assert data["module_origin"] == "phase_loop_runtime/supervised_contracts.py"
    assert data["semantic_cases"] == case_inventory()
    assert data["semantic_inventory"] == vectors.semantic_inventory() + named_inventory()
    assert len(named_inventory()) == 10
    assert data["coverage_inventory"] == coverage_inventory()
    for row in data["coverage_inventory"]:
        name, _, path = row["source_pointer"].partition("#")
        parent = vectors.pointer(json.loads(bundle.resource_bytes(name)), path)
        assert isinstance(parent, dict)
        assert not set(row["absent_keys"]) & parent.keys()
    for row in vectors.semantic_inventory():
        name, _, path = row["source_pointer"].partition("#")
        vectors.pointer(json.loads(bundle.resource_bytes(name)), path)
    assert data["tier_basis"] == tier_inventory(bundle)
    assert data["named_controls"] == ["E-admitted", "E-echo", "E-dependency-declared"]
    assert data["opaque_fields_do_not_prove_coverage"] == ["caller_context", "units.snapshot_ref", "units.crosswalk_ref", "obligations.definition_digests"]
    assert re.fullmatch(r"[0-9a-f]{64}", data["suite_artifact_sha256"])
    check_results(data)
    hosted = data["hosted_publication"]
    if hosted is None:
        assert data["intake_gate_status"] == "awaiting_hosted_verification"
        assert data["hosted_run_id"] is None
    else:
        assert data["intake_gate_status"] == "verified"
        assert hosted["outcome"] == "passed"
        assert hosted["hosted_run_id"] == data["hosted_run_id"]
        assert hosted["hosted_job"] == "publication"
        assert re.fullmatch(r"[0-9a-f]{40}", hosted["hosted_head"])
        assert re.fullmatch(r"[0-9a-f]{64}", data["hosted_result_artifact_sha256"])
        assert hosted["source_commit"] == production.SOURCE_COMMIT
        assert hosted["input_artifact_sha256"] == production.INPUT_ARTIFACT_SHA256
        assert hosted["protected"] is True and hosted["default_branch"] == "main"
        assert hosted["resources"] == {n: {"sha256": d, "blob": b} for n, (d, b) in production.PUBLICATION_PINS.items()}
        evidence = data["hosted_job_evidence"]
        assert evidence["run_id"] == hosted["hosted_run_id"] and evidence["head"] == hosted["hosted_head"]
        assert evidence["conclusion"] == "success" and evidence["job_id"] > 0
        assert evidence["wheel_tests_passed"] == sum(expected_functions(intake).values())
        assert re.fullmatch(r"[0-9a-f]{64}", evidence["wheel_junit_sha256"])


def test_receipt_bindings_and_inventory():
    verify(read_receipt())


@pytest.mark.parametrize("control", ["authority", "inventory", "case", "result", "coverage", "input", "runner"])
def test_receipt_controls(control):
    data = read_receipt()
    verify(data)  # enter production before a temporary receipt mutation
    if control == "authority": data["byte_pin_authority"] = True
    elif control == "inventory": data["semantic_inventory"].pop()
    elif control == "case": data["semantic_cases"].pop()
    elif control == "result": data["intake_results"].pop()
    elif control == "coverage": data["coverage_inventory"][0]["absent_keys"] = ["caller_context"]
    elif control == "input": data["input_artifact_sha256"] = "0" * 64
    elif control == "runner": data["schema_results"][0]["outcome"] = "skipped"
    with pytest.raises(AssertionError):
        verify(data)


def test_runtime_consumers_remain_independent():
    intake.anchor()
    root = Path(production.__file__).parent
    for path in root.rglob("*.py"):
        if path.name == "supervised_contracts.py":
            continue
        assert not re.search(r"(?:from\s+[^\n]*supervised_contracts|import\s+[^\n]*supervised_contracts)", path.read_text()), path.name


def junit_rows(paths):
    rows = {name: [] for name in GROUPS.values()}
    combined = ET.Element("testsuites")
    for path in paths:
        tree = ET.fromstring(path.read_bytes())
        combined.extend(list(tree) if tree.tag == "testsuites" else [tree])
        for case in tree.iter("testcase"):
            assert case.find("failure") is None and case.find("error") is None and case.find("skipped") is None
            classname = case.attrib["classname"].split(".")[-1]
            if classname not in GROUPS:
                assert classname == "test_supervised_contracts_receipt"
                continue
            node = "phase-loop-runtime/tests/" + classname + ".py::" + case.attrib["name"]
            group = GROUPS[classname]
            rows[group].append({"group": group, "test_node_id": node, "case_or_control_id": case.attrib["name"],
                                "resource_sha256": {}, "outcome": "passed", "runner_artifact_ref": "schema-suite-junit.xml#" + node})
    return rows, ET.tostring(combined, encoding="utf-8", xml_declaration=True)


def stamp(paths, suite_path, hosted_path=None, bootstrap=False, hosted_run_path=None):
    rows, suite_bytes = junit_rows(paths)
    bundle = intake.anchor()
    resource_hashes = {n: sha256(bundle.resource_bytes(n)).hexdigest() for n in production._NAMES}
    for group in rows.values():
        for row in group: row["resource_sha256"] = resource_hashes
    if not bootstrap:
        previous = read_receipt()
        for group in rows:
            assert previous[group] == rows[group]
    hosted = json.loads(hosted_path.read_bytes()) if hosted_path else None
    job_evidence = None
    if hosted is not None:
        assert hosted_run_path is not None
        run = json.loads(hosted_run_path.read_bytes())
        assert run["status"] == "completed" and run["conclusion"] == "success"
        assert str(run["databaseId"]) == hosted["hosted_run_id"] and run["headSha"] == hosted["hosted_head"]
        job = next(j for j in run["jobs"] if j["name"] == "supervised contract publication")
        assert job["conclusion"] == "success"
        assert any(s["name"] == "Verify extracted package" and s["conclusion"] == "success" for s in job["steps"])
        wheel_path = hosted_path.with_name("schema-wheel.xml")
        wheel_cases = list(ET.fromstring(wheel_path.read_bytes()).iter("testcase"))
        assert len(wheel_cases) == sum(expected_functions(intake).values())
        assert all(not any(c.find(tag) is not None for tag in ("failure", "error", "skipped")) for c in wheel_cases)
        job_evidence = {"run_id": str(run["databaseId"]), "head": run["headSha"], "job_id": job["databaseId"],
                        "conclusion": run["conclusion"], "wheel_tests_passed": len(wheel_cases),
                        "wheel_junit_sha256": sha256(wheel_path.read_bytes()).hexdigest()}
    data = {**rows, "source_commit": production.SOURCE_COMMIT, "byte_pin_authority": False,
            "input_artifact_sha256": production.INPUT_ARTIFACT_SHA256, "resource_sha256": resource_hashes,
            "module_sha256": sha256(Path(production.__file__).read_bytes()).hexdigest(),
            "module_origin": "phase_loop_runtime/supervised_contracts.py",
            "semantic_cases": case_inventory(), "semantic_inventory": vectors.semantic_inventory() + named_inventory(),
            "coverage_inventory": coverage_inventory(), "tier_basis": tier_inventory(bundle),
            "named_controls": ["E-admitted", "E-echo", "E-dependency-declared"],
            "opaque_fields_do_not_prove_coverage": ["caller_context", "units.snapshot_ref", "units.crosswalk_ref", "obligations.definition_digests"],
            "suite_artifact_sha256": sha256(suite_bytes).hexdigest(),
            "hosted_publication": hosted, "hosted_run_id": hosted["hosted_run_id"] if hosted else None,
            "hosted_job_evidence": job_evidence,
            "hosted_result_artifact_sha256": sha256(hosted_path.read_bytes()).hexdigest() if hosted else None,
            "intake_gate_status": "verified" if hosted else "awaiting_hosted_verification"}
    verify(data)
    suite_path.write_bytes(suite_bytes)
    assert sha256(suite_path.read_bytes()).hexdigest() == data["suite_artifact_sha256"]
    text = """# SCHEMA intake receipt

Runner-observed v1 structural intake for agent-harness#1818. This receipt grants
no launch, journal or byte-pin authority. IF-0-SCHEMA-1 completion additionally
requires a green hosted publication and extracted-wheel job; a null hosted
identity explicitly withholds that completion. Every semantic row remains
upstream_phase_unmet for production proof at CLOSEOUT, including zero-vector
obligations and positive controls' effects. No v2 bytes are pinned.

Local checks run as individual targeted files, serially, under timeout 900 with
no cacheprovider, after shared-host load and I/O pressure checks. Intermediate
JUnit stays runner-owned scratch. The separate stamp step compares producer
rows with actual JUnit outcomes, refuses missing/skipped/failed nodes and records
the combined suite artifact digest. The digest identifies that run before this
stamp; it makes no claim about a later head. V3 checks shape and completeness
without requiring scratch to exist in a fresh checkout.

Full regression, required CI checks, Gate A and independent review are outside
these local observations. Spec closeout: canonical_spec_update, metadata_only;
targets are the vendored schema directory and docs/supervised-worker-contracts.md.

```json
""" + json.dumps(data, indent=2, sort_keys=True) + "\n```\n"
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(text)
    return data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stamp", type=Path, nargs="+", required=True)
    parser.add_argument("--suite-artifact", type=Path, required=True)
    parser.add_argument("--hosted", type=Path)
    parser.add_argument("--hosted-run", type=Path)
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()
    stamp(args.stamp, args.suite_artifact, args.hosted, args.bootstrap, args.hosted_run)
