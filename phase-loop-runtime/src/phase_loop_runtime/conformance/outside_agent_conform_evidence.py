"""Verify runner-owned evidence for the CONFORM phase."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import xml.etree.ElementTree as element_tree
import zipfile
from pathlib import Path
from typing import Any


EVIDENCE_VERIFIER_INTERFACE = {
    "chronology": {
        "timing": "A2",
        "inputs": ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path", "runner_manifest", "runner_log", "junit_xml", "chronology"),
        "outputs": ("mode", "candidate_commit", "head_commit", "module_path", "recomputed_input_digest", "recomputed_evidence_digest", "evidence"),
    },
    "corpus": {
        "timing": "A2",
        "inputs": ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path", "runner_manifest", "runner_log", "junit_xml", "fixture_manifest", "mutations"),
        "outputs": ("mode", "candidate_commit", "head_commit", "module_path", "recomputed_input_digest", "recomputed_evidence_digest", "evidence"),
    },
    "package": {
        "timing": "A2",
        "inputs": ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path", "runner_manifest", "runner_log", "junit_xml", "direct_wheel", "direct_sdist", "sdist_derived_wheel", "mutations"),
        "outputs": ("mode", "candidate_commit", "head_commit", "module_path", "recomputed_input_digest", "recomputed_evidence_digest", "evidence"),
    },
    "compatibility": {
        "timing": "B2-only",
        "inputs": ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path", "runner_manifest", "runner_log", "junit_xml", "ec_matrix", "mutations", "installed_package"),
        "outputs": ("mode", "candidate_commit", "head_commit", "module_path", "recomputed_input_digest", "recomputed_evidence_digest", "evidence"),
    },
}
_RECORD_IDS = {"chronology": ("preimplementation", "postimplementation"), "corpus": ("source-fixture", "package-mirror"), "package": ("direct-wheel", "sdist-derived-wheel"), "compatibility": ("ec-matrix", "installed-package")}
_RECORD_KEYS = {"record_id", "ordinal", "artifact_path", "artifact_sha256", "raw_log_path", "raw_log_sha256", "evidence"}
_EXCLUSIVE_INPUTS = {"chronology": ("chronology",), "corpus": ("fixture_manifest",), "package": ("direct_wheel", "direct_sdist", "sdist_derived_wheel"), "compatibility": ("ec_matrix", "installed_package")}
_PACKAGE_VARIANTS = ("direct-wheel", "direct-sdist", "sdist-derived-wheel")
_EXPECTED_PROBE_ARGV = ["python3", "-m", "pytest", "-q", "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition"]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_digest(value: object) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _read_verified(path_value: object, digest_value: object) -> bytes:
    if not isinstance(path_value, str) or not isinstance(digest_value, str):
        raise ValueError("evidence path and digest must be strings")
    contents = Path(path_value).read_bytes()
    if _sha256_bytes(contents) != digest_value:
        raise ValueError(f"evidence digest mismatch: {path_value}")
    return contents


def _read_json_fact(reference: object) -> dict[str, Any]:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ValueError("linked evidence fact must contain path and sha256")
    value = json.loads(_read_verified(reference["path"], reference["sha256"]))
    if not isinstance(value, dict):
        raise ValueError("linked evidence fact must be an object")
    return value


def _archive_member_digests(path: Path) -> dict[str, str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return {name: _sha256_bytes(archive.read(name)) for name in archive.namelist() if not name.endswith("/")}
    with tarfile.open(path) as archive:
        result: dict[str, str] = {}
        for member in archive.getmembers():
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValueError(f"unreadable archive member: {member.name}")
                name = member.name.split("/src/", 1)[1] if "/src/" in member.name else member.name
                result[name] = _sha256_bytes(extracted.read())
        return result


def _expected_contract_members() -> tuple[dict[str, str], dict[str, Any]]:
    root = Path(__file__).with_name("_contract")
    members = {"phase_loop_runtime/conformance/_contract/" + path.relative_to(root).as_posix(): _sha256_bytes(path.read_bytes()) for path in sorted(root.rglob("*")) if path.is_file()}
    return members, json.loads((root / "VENDOR.json").read_text(encoding="utf-8"))


def _validate_records(mode: str, records: list[dict[str, object]]) -> tuple[dict[str, Any], bytes]:
    if mode not in EVIDENCE_VERIFIER_INTERFACE:
        raise ValueError(f"unsupported evidence mode: {mode}")
    if not isinstance(records, list) or len(records) != len(_RECORD_IDS[mode]):
        raise ValueError("wrong evidence record count")
    if tuple(record.get("record_id") for record in records) != _RECORD_IDS[mode]:
        raise ValueError("wrong evidence record ordering")
    if [record.get("ordinal") for record in records] != list(range(len(records))):
        raise ValueError("wrong evidence record ordinals")
    if any(set(record) != _RECORD_KEYS for record in records):
        raise ValueError("wrong evidence record shape")
    artifact_paths = {record["artifact_path"] for record in records}
    if len(artifact_paths) != 1:
        raise ValueError("records must bind one runner manifest")
    manifest_path = next(iter(artifact_paths))
    manifest_digest = records[0]["artifact_sha256"]
    manifest_bytes = _read_verified(manifest_path, manifest_digest)
    if any(record["artifact_sha256"] != manifest_digest for record in records):
        raise ValueError("records disagree on runner manifest digest")
    facts = json.loads(manifest_bytes)
    if not isinstance(facts, dict) or facts.get("owner") != "phase-loop-runner":
        raise ValueError("runner-owned manifest required")
    for record in records:
        if record["evidence"] != {"owner": "phase-loop-runner", "candidate_commit": facts.get("candidate_commit"), "candidate_tree": facts.get("candidate_tree")}:
            raise ValueError("record binding does not match runner manifest")
        _read_verified(record["raw_log_path"], record["raw_log_sha256"])
    return facts, manifest_bytes


def _validate_bindings(facts: dict[str, Any], runner_manifest: dict[str, Any]) -> dict[str, Any]:
    names = ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path")
    bindings = {name: facts.get(name) for name in names}
    for name in names[:-1]:
        value = bindings[name]
        if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"invalid {name}")
    if bindings["module_path"] != "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_schema.py":
        raise ValueError("unexpected bound module")
    if runner_manifest.get("candidate_head_module") != bindings:
        raise ValueError("runner manifest binding mismatch")
    if facts.get("argv") != _EXPECTED_PROBE_ARGV:
        raise ValueError("unexpected runner probe command")
    return bindings


def _parse_junit(facts: dict[str, Any], runner_manifest: dict[str, Any]) -> dict[str, Any]:
    junit_bytes = _read_verified(facts["junit_xml"]["path"], facts["junit_xml"]["sha256"])
    if facts.get("junit_path") != facts["junit_xml"]["path"] or facts.get("junit_sha256") != facts["junit_xml"]["sha256"]:
        raise ValueError("JUnit aliases disagree")
    root = element_tree.fromstring(junit_bytes)
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise ValueError("JUnit suite missing")
    cases = suite.findall(".//testcase")
    summary = {"tests": int(suite.attrib["tests"]), "failures": int(suite.attrib["failures"]), "skipped": int(suite.attrib["skipped"])}
    expected = runner_manifest.get("activated_lifecycle")
    if not isinstance(expected, dict) or summary != {"tests": expected.get("tests"), "failures": expected.get("failures"), "skipped": expected.get("skipped")} or summary["tests"] != len(cases):
        raise ValueError("JUnit summary does not match the frozen lifecycle")
    node_ids, failed_ids, outcomes = [], [], []
    anchors = expected.get("red_anchors", {})
    for case in cases:
        failure, skipped = case.find("failure"), case.find("skipped")
        outcomes.append({"name": case.attrib["name"], "outcome": "failed" if failure is not None else "skipped" if skipped is not None else "passed"})
        classname = case.attrib.get("classname")
        if classname:
            nodeid = "phase-loop-runtime/" + classname.replace(".", "/") + ".py::" + case.attrib["name"]
            node_ids.append(nodeid)
            properties = {item.attrib.get("name"): item.attrib.get("value") for item in case.findall("./properties/property")}
            if properties.get("conform_expected_node_id") != nodeid:
                raise ValueError("JUnit node binding property missing")
            if failure is not None:
                failed_ids.append(nodeid)
                if anchors.get(nodeid) not in ((failure.text or "") + " " + failure.attrib.get("message", "")):
                    raise ValueError("JUnit failure anchor mismatch")
    if node_ids != expected.get("node_ids") or set(failed_ids) != set(expected.get("red_node_ids", [])):
        raise ValueError("JUnit case inventory mismatch")
    raw_log = _read_verified(facts["runner_log"]["path"], facts["runner_log"]["sha256"]).decode("utf-8")
    if facts.get("runner_log_path") != facts["runner_log"]["path"] or facts.get("runner_log_sha256") != facts["runner_log"]["sha256"]:
        raise ValueError("runner log aliases disagree")
    passed = summary["tests"] - summary["failures"] - summary["skipped"]
    if f"{summary['failures']} failed, {passed} passed, {summary['skipped']} skipped," not in raw_log or any(f"FAILED {nodeid}" not in raw_log for nodeid in failed_ids):
        raise ValueError("runner log summary mismatch")
    return {**summary, "cases": outcomes}


def _validate_mutations(facts: dict[str, Any]) -> list[dict[str, Any]]:
    mutations = facts.get("mutation_records")
    if not isinstance(mutations, list) or not mutations or facts.get("mutations") != mutations:
        raise ValueError("complete mutation evidence required")
    ids = [item.get("id") for item in mutations if isinstance(item, dict)]
    if len(ids) != len(mutations) or len(set(ids)) != len(ids):
        raise ValueError("mutation IDs must be unique")
    for mutation in mutations:
        if set(mutation) != {"id", "source_path", "expected_nodeid", "expected_anchor", "observable"}:
            raise ValueError("mutation evidence shape mismatch")
        captured = mutation["observable"]
        if not isinstance(captured, dict) or captured.get("status") != "blocked" or captured.get("anchor") != mutation["expected_anchor"]:
            raise ValueError("mutation capture did not fail closed")
        _read_verified(captured.get("result_path"), captured.get("result_sha256"))
        observable = captured.get("observable")
        if not isinstance(observable, dict) or observable.get("classification") != "killed" or observable.get("candidate_clean") is not True or observable.get("nodeid_matched") is not True or observable.get("anchor_matched") is not True:
            raise ValueError("mutation was not killed against a clean candidate")
        for key, classification in (("baseline", "passed"), ("positive_control", "passed"), ("mutant", "failed")):
            if not isinstance(observable.get(key), dict) or observable[key].get("classification") != classification:
                raise ValueError("mutation controls are incomplete")
    return mutations


def _validate_chronology(facts: dict[str, Any], bindings: dict[str, Any], mutations: list[dict[str, Any]]) -> dict[str, Any]:
    chronology = facts.get("chronology")
    if not isinstance(chronology, dict) or chronology.get("candidate_head_module") != bindings:
        raise ValueError("chronology binding mismatch")
    stages = chronology.get("stages")
    if not isinstance(stages, list):
        raise ValueError("chronology stages missing")
    expected_names = ["preimplementation_red", "postimplementation_pre_doc"]
    if len(stages) == 3:
        expected_names.append("final_doc_chronology")
    if [stage.get("stage") for stage in stages] != expected_names:
        raise ValueError("chronology stage ordering mismatch")
    pre, implementation = stages[:2]
    if not isinstance(pre.get("review"), dict) or pre.get("commit") != facts.get("parent_commit") or pre.get("tree") != facts.get("parent_tree"):
        raise ValueError("preimplementation review binding missing")
    if pre.get("exit_code") == 0 or pre.get("topology", {}).get("candidate_descends_from_test_candidate") is not True:
        raise ValueError("preimplementation RED evidence invalid")
    if implementation.get("commit") != bindings["candidate_commit"] or implementation.get("tree") != bindings["candidate_tree"] or implementation.get("exit_code") != 0 or implementation.get("topology", {}).get("candidate_descends_from_test_candidate") is not True or implementation.get("topology", {}).get("test_paths_unchanged") is not True:
        raise ValueError("implementation candidate binding mismatch")
    if implementation.get("mutation_outcomes") != {mutation["id"]: "killed" for mutation in mutations}:
        raise ValueError("chronology mutation outcomes mismatch")
    if len(stages) == 3:
        final = stages[2]
        b0, b1, b2, topology = final.get("b0", {}), final.get("b1", {}), final.get("b2", {}), final.get("topology", {})
        if not b0.get("failing_node_ids") or b0.get("commit") != bindings["candidate_commit"] or b0.get("exit_code") == 0:
            raise ValueError("final chronology B0 evidence invalid")
        if b1.get("before_commit") != bindings["candidate_commit"] or b1.get("after_commit") != final.get("commit") or b1.get("test_paths_unchanged") is not True:
            raise ValueError("final chronology B1 transition invalid")
        if b2.get("commit") != final.get("commit") or b2.get("exit_code") != 0 or b2.get("skipped_node_ids") or b2.get("failed_node_ids"):
            raise ValueError("final chronology B2 evidence invalid")
        if topology.get("implementation_candidate") != bindings["candidate_commit"] or topology.get("final_candidate") != final.get("commit") or topology.get("final_descends_from_candidate") is not True:
            raise ValueError("final chronology topology invalid")
        if chronology.get("scope") == "exact_main" and topology.get("canonical_main_head") != bindings["head_commit"]:
            raise ValueError("exact-main chronology is not bound to HEAD")
    elif chronology.get("scope") != "a2_candidate":
        raise ValueError("pre-document chronology must use a2_candidate scope")
    return chronology


def _validate_corpus(facts: dict[str, Any]) -> dict[str, Any]:
    corpus = facts.get("corpus")
    if not isinstance(corpus, dict) or set(corpus) != {"rows", "partitions"} or not isinstance(corpus["rows"], list) or not isinstance(corpus["partitions"], dict):
        raise ValueError("corpus evidence missing")
    rows, partitions = corpus["rows"], corpus["partitions"]
    expected = {"valid_submissions": sorted(row["case_id"] for row in rows if row["expected_valid"] and row["schema_target"] == "outside_agent_submission.v0.1"), "invalid_submissions": sorted(row["case_id"] for row in rows if not row["expected_valid"] and row["schema_target"] == "outside_agent_submission.v0.1"), "invalid_route_verdicts": sorted(row["case_id"] for row in rows if not row["expected_valid"] and row["schema_target"] == "outside_agent_route_verdict.v0.1")}
    if partitions != expected or tuple(map(len, expected.values())) != (3, 7, 1):
        raise ValueError("corpus partition mismatch")
    return corpus


def _validate_packages(facts: dict[str, Any], bindings: dict[str, Any], corpus: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, str]]]:
    expected_contract, _ = _expected_contract_members()
    package, archives = facts.get("package"), facts.get("archives")
    if not isinstance(package, dict) or package.get("contract_members") != expected_contract or package.get("artifact_provenance") != bindings or package.get("artifact_labels") != list(_PACKAGE_VARIANTS):
        raise ValueError("package provenance mismatch")
    if not isinstance(archives, dict) or set(archives) != set(_PACKAGE_VARIANTS):
        raise ValueError("complete package archive set required")
    archive_members: dict[str, dict[str, str]] = {}
    for name, reference in archives.items():
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            raise ValueError("archive reference malformed")
        _read_verified(reference["path"], reference["sha256"])
        members = _archive_member_digests(Path(reference["path"]))
        if any(members.get(member) != digest for member, digest in expected_contract.items()):
            raise ValueError("archive contract mirror differs from packaged contract")
        archive_members[name] = members
    direct_runtime = {k: v for k, v in archive_members["direct-wheel"].items() if k.startswith("phase_loop_runtime/")}
    derived_runtime = {k: v for k, v in archive_members["sdist-derived-wheel"].items() if k.startswith("phase_loop_runtime/")}
    if direct_runtime != derived_runtime:
        raise ValueError("wheel variants contain different runtime bytes")
    if any(any(not (member.startswith("phase_loop_runtime/") or ".dist-info/" in member) for member in archive_members[name]) for name in ("direct-wheel", "sdist-derived-wheel")):
        raise ValueError("wheel contains an unexpected top-level member")
    installed = _read_json_fact(facts.get("installed_package"))
    if set(installed) != {"package", "module_path", "variants", "contract_members", "corpus_partitions", "executions"} or installed["package"] != "phase-loop-runtime" or installed["module_path"] != bindings["module_path"] or installed["variants"] != list(_PACKAGE_VARIANTS) or installed["contract_members"] != expected_contract or installed["corpus_partitions"] != corpus["partitions"]:
        raise ValueError("installed-package evidence binding mismatch")
    executions = installed["executions"]
    if not isinstance(executions, list) or [item.get("variant") for item in executions] != list(_PACKAGE_VARIANTS):
        raise ValueError("installed-package variants incomplete")
    for execution in executions:
        variant = execution["variant"]
        if execution.get("archive_sha256") != archives[variant]["sha256"] or execution.get("installation_posture") != "pip-target-no-deps-no-build-isolation":
            raise ValueError("installed-package archive binding mismatch")
        installation = execution.get("installation")
        if not isinstance(installation, dict) or installation.get("exit_code") != 0:
            raise ValueError("package installation did not succeed")
        _read_verified(installation.get("raw_path"), installation.get("raw_sha256"))
        cases = execution.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ValueError("installed package cases missing")
        for case in cases:
            _read_verified(case.get("raw_path"), case.get("raw_sha256"))
            if not isinstance(case.get("result"), dict) or case["result"].get("status") not in {"pass", "blocked"}:
                raise ValueError("installed package case inconclusive")
    return package, installed, archive_members


def _validate_mode_specific(mode: str, facts: dict[str, Any], bindings: dict[str, Any], runner_manifest: dict[str, Any]) -> dict[str, Any] | None:
    for required in _EXCLUSIVE_INPUTS[mode]:
        if required not in facts:
            raise ValueError(f"missing {mode} evidence input: {required}")
    if facts.get("evidence_mode") != mode:
        raise ValueError("semantic evidence mode mismatch")
    if mode == "corpus":
        fixture = _read_json_fact(facts["fixture_manifest"])
        if fixture.get("rows") != facts["corpus"]["rows"] or fixture.get("partitions") != facts["corpus"]["partitions"]:
            raise ValueError("fixture manifest differs from corpus evidence")
    if mode == "package":
        for field, label in {"direct_wheel": "direct-wheel", "direct_sdist": "direct-sdist", "sdist_derived_wheel": "sdist-derived-wheel"}.items():
            reference = facts[field]
            if reference.get("path") != facts["archives"][label]["path"] or reference.get("sha256") != facts["archives"][label]["sha256"] or reference.get("contract_members") != facts["package"]["contract_members"] or reference.get("provenance", {}).get("candidate_commit") != bindings["candidate_commit"] or reference.get("provenance", {}).get("candidate_tree") != bindings["candidate_tree"]:
                raise ValueError("mode-specific archive binding mismatch")
    if mode != "compatibility":
        if "ec_matrix" in facts or "ec_matrix" in runner_manifest:
            raise ValueError("compatibility evidence appeared before B2")
        return None
    matrix = _read_json_fact(facts["ec_matrix"])
    if set(matrix) != {"candidate_commit", "candidate_tree", "entries"} or matrix["candidate_commit"] != bindings["candidate_commit"] or matrix["candidate_tree"] != bindings["candidate_tree"]:
        raise ValueError("EC matrix binding mismatch")
    entries = matrix["entries"]
    if not isinstance(entries, list) or [entry.get("id") for entry in entries] != [f"EC-CONFORM-{i}" for i in range(9)] or [entry.get("ordinal") for entry in entries] != list(range(9)):
        raise ValueError("EC matrix is incomplete")
    for entry in entries:
        captured = entry.get("observable")
        observable = captured.get("observable") if isinstance(captured, dict) else None
        if not isinstance(observable, dict) or observable.get("classification") != "passed" or captured.get("status") != "accepted":
            raise ValueError("EC probe did not pass")
        _read_verified(captured.get("result_path"), captured.get("result_sha256"))
    if runner_manifest.get("ec_matrix") != {"entries": entries}:
        raise ValueError("runner manifest EC matrix mismatch")
    return {"entries": entries}


def verify_conform_evidence_records(mode: str, records: list[dict[str, object]]) -> dict[str, object]:
    facts, manifest_bytes = _validate_records(mode, records)
    if any(name not in facts for name in EVIDENCE_VERIFIER_INTERFACE[mode]["inputs"]):
        raise ValueError("runner manifest lacks a required verifier input")
    runner_manifest = _read_json_fact(facts["runner_manifest"])
    bindings = _validate_bindings(facts, runner_manifest)
    expected_contract, vendor = _expected_contract_members()
    if facts.get("vendor") != vendor or runner_manifest.get("provenance") != vendor or runner_manifest.get("contract_member_digests") != expected_contract:
        raise ValueError("vendor provenance differs from packaged contract")
    lifecycle = facts.get("lifecycle")
    if runner_manifest.get("lifecycle") != lifecycle or not isinstance(lifecycle, dict):
        raise ValueError("lifecycle evidence mismatch")
    for stage in ("default", "activated"):
        stage_facts = lifecycle.get(stage, {})
        _read_verified(stage_facts.get("raw_log_path"), stage_facts.get("raw_log_sha256"))
        _read_verified(stage_facts.get("junit_path"), stage_facts.get("junit_sha256"))
    junit = _parse_junit(facts, runner_manifest)
    mutations = _validate_mutations(facts)
    chronology = _validate_chronology(facts, bindings, mutations)
    corpus = _validate_corpus(facts)
    package, installed, archive_members = _validate_packages(facts, bindings, corpus)
    ec_matrix = _validate_mode_specific(mode, facts, bindings, runner_manifest)
    archive_bytes = {name: _sha256_bytes(Path(details["path"]).read_bytes()) for name, details in facts["archives"].items()}
    input_facts = {name: facts[name] for name in EVIDENCE_VERIFIER_INTERFACE[mode]["inputs"]}
    input_facts.update(manifest=_sha256_bytes(manifest_bytes), archive_bytes=archive_bytes)
    outcome_facts: dict[str, object] = {"junit": junit, "archive_members": archive_members, "mutations": mutations, "package_executions": installed["executions"]}
    if ec_matrix is not None:
        outcome_facts["ec_matrix"] = ec_matrix["entries"]
    evidence: dict[str, object] = {"bindings": bindings, "vendor": vendor, "chronology": chronology, "corpus": corpus, "package": package, "installed_package": installed, "mode_specific": {"mode": mode, "required_inputs": list(_EXCLUSIVE_INPUTS[mode])}}
    if ec_matrix is not None:
        evidence["ec_matrix"] = ec_matrix
    return {"mode": mode, "candidate_commit": bindings["candidate_commit"], "head_commit": bindings["head_commit"], "module_path": bindings["module_path"], "recomputed_input_digest": _canonical_digest(input_facts), "recomputed_evidence_digest": _canonical_digest(outcome_facts), "evidence": evidence}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify sealed outside-agent CONFORM evidence.")
    parser.add_argument("mode", choices=tuple(EVIDENCE_VERIFIER_INTERFACE))
    parser.add_argument("--records", type=Path)
    args = parser.parse_args(argv)
    try:
        records_path = args.records or _default_records_path(args.mode)
        records = json.loads(records_path.read_text(encoding="utf-8"))
        result = verify_conform_evidence_records(args.mode, records)
    except (AssertionError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, element_tree.ParseError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"CONFORM evidence rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


def _default_records_path(mode: str) -> Path:
    root = Path(".phase-loop/artifacts/CONFORM")
    candidates = (
        root / f"{mode}-records.json",
        root / mode / "records.json",
        root / f"records-{mode}.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError(f"runner-owned {mode} evidence records are unavailable")


if __name__ == "__main__":
    raise SystemExit(main())
