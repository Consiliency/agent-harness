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
    if root.tag != "testsuites" or root.attrib.get("name") != "pytest tests":
        raise ValueError("JUnit envelope mismatch")
    suites = root.findall("testsuite")
    if len(suites) != 1 or suites[0].attrib.get("name") != "pytest" or not suites[0].attrib.get("hostname") or not suites[0].attrib.get("timestamp"):
        raise ValueError("JUnit suite envelope mismatch")
    suite = suites[0]
    cases = suite.findall("testcase")
    try:
        summary = {
            "tests": int(suite.attrib["tests"]),
            "errors": int(suite.attrib["errors"]),
            "failures": int(suite.attrib["failures"]),
            "skipped": int(suite.attrib["skipped"]),
        }
    except (KeyError, ValueError) as error:
        raise ValueError("JUnit summary malformed") from error
    if summary["tests"] != len(cases) or summary["errors"] != 0:
        raise ValueError("JUnit global summary mismatch")
    if min(summary.values()) < 0 or summary["failures"] + summary["skipped"] > summary["tests"]:
        raise ValueError("JUnit global summary bounds invalid")
    expected = runner_manifest.get("activated_lifecycle")
    if not isinstance(expected, dict):
        raise ValueError("frozen lifecycle missing")
    expected_node_ids = expected.get("node_ids")
    expected_failed_ids = expected.get("red_node_ids")
    anchors = expected.get("red_anchors", {})
    if (
        not isinstance(expected_node_ids, list)
        or not all(isinstance(nodeid, str) for nodeid in expected_node_ids)
        or len(expected_node_ids) != len(set(expected_node_ids))
        or not isinstance(expected_failed_ids, list)
        or not all(isinstance(nodeid, str) for nodeid in expected_failed_ids)
        or len(expected_failed_ids) != len(set(expected_failed_ids))
        or not set(expected_failed_ids).issubset(expected_node_ids)
        or not isinstance(anchors, dict)
        or set(anchors) != set(expected_failed_ids)
        or not all(isinstance(anchor, str) and anchor for anchor in anchors.values())
        or any(not isinstance(expected.get(name), int) or isinstance(expected.get(name), bool) for name in ("tests", "failures", "skipped"))
        or {"tests": expected["tests"], "failures": expected["failures"], "skipped": expected["skipped"]}
        != {"tests": len(expected_node_ids), "failures": len(expected_failed_ids), "skipped": expected["skipped"]}
    ):
        raise ValueError("frozen lifecycle malformed")
    expected_node_id_set = set(expected_node_ids)
    governed_cases: dict[str, element_tree.Element] = {}
    failed_ids, skipped_ids, outcomes = [], [], []
    global_failures = global_skips = 0
    for case in cases:
        failure, skipped = case.find("failure"), case.find("skipped")
        if case.find("error") is not None or sum(item is not None for item in (failure, skipped)) > 1:
            raise ValueError("JUnit case outcome malformed")
        outcome = "failed" if failure is not None else "skipped" if skipped is not None else "passed"
        global_failures += failure is not None
        global_skips += skipped is not None
        name = case.attrib.get("name")
        if not name:
            raise ValueError("JUnit case name missing")
        classname = case.attrib.get("classname", "")
        nodeid = "phase-loop-runtime/" + classname.replace(".", "/") + ".py::" + name if classname else None
        tagged_properties = [item for item in case.findall("./properties/property") if item.attrib.get("name") == "conform_expected_node_id"]
        if len(tagged_properties) > 1:
            raise ValueError("JUnit node binding property duplicated")
        if tagged_properties:
            tagged_nodeid = tagged_properties[0].attrib.get("value")
            if tagged_nodeid not in expected_node_id_set:
                raise ValueError("JUnit node binding property unknown")
            if nodeid != tagged_nodeid:
                raise ValueError("JUnit node binding property spoofed")
            if nodeid in governed_cases:
                raise ValueError("JUnit expected case duplicated")
            governed_cases[nodeid] = case
            if failure is not None:
                failed_ids.append(nodeid)
            if skipped is not None:
                skipped_ids.append(nodeid)
        elif nodeid in expected_node_id_set:
            raise ValueError("JUnit node binding property missing")
        elif outcome != "skipped":
            raise ValueError("JUnit unrelated case did not skip")
        outcomes.append({"name": name, "outcome": outcome})
    if global_failures != summary["failures"] or global_skips != summary["skipped"]:
        raise ValueError("JUnit global case summary mismatch")
    lifecycle_summary = {"tests": len(governed_cases), "failures": len(failed_ids), "skipped": len(skipped_ids)}
    if lifecycle_summary != {"tests": expected["tests"], "failures": expected["failures"], "skipped": expected["skipped"]}:
        raise ValueError("JUnit summary does not match the frozen lifecycle")
    if set(governed_cases) != expected_node_id_set or set(failed_ids) != set(expected_failed_ids):
        raise ValueError("JUnit case inventory mismatch")
    for nodeid in failed_ids:
        failure = governed_cases[nodeid].find("failure")
        if failure is None or anchors[nodeid] not in ((failure.text or "") + " " + failure.attrib.get("message", "")):
            raise ValueError("JUnit failure anchor mismatch")
    raw_log = _read_verified(facts["runner_log"]["path"], facts["runner_log"]["sha256"]).decode("utf-8")
    if facts.get("runner_log_path") != facts["runner_log"]["path"] or facts.get("runner_log_sha256") != facts["runner_log"]["sha256"]:
        raise ValueError("runner log aliases disagree")
    passed = summary["tests"] - summary["failures"] - summary["skipped"]
    if f"{summary['failures']} failed, {passed} passed, {summary['skipped']} skipped," not in raw_log or any(f"FAILED {nodeid}" not in raw_log for nodeid in failed_ids):
        raise ValueError("runner log summary mismatch")
    return {"tests": summary["tests"], "failures": summary["failures"], "skipped": summary["skipped"], "cases": outcomes}


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

    if facts.get("evidence_mode") != "chronology":
        return chronology

    import os
    import re
    import shutil
    import subprocess

    if any(k.startswith("GIT_") and k != "GIT_PAGER" for k in os.environ):
        raise ValueError("GIT_* environment variables forbidden")

    module_file = Path(__file__).resolve()
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    clean_env.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "HOME": os.devnull,
            "PATH": os.defpath,
            "XDG_CONFIG_HOME": os.devnull,
        }
    )
    git_executable = shutil.which("git", path=os.defpath)
    if git_executable is None:
        raise ValueError("trusted git executable unavailable")
    git_executable = str(Path(git_executable).resolve())

    def _run_git(args: list[str], cwd: Path | str | None = None) -> str:
        try:
            proc = subprocess.run(
                [git_executable, "-c", "core.attributesFile=/dev/null", "-c", "diff.external="] + args,
                cwd=cwd or repo_root,
                capture_output=True,
                text=True,
                env=clean_env,
                check=True,
            )
            return proc.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as err:
            raise ValueError(f"git command failed: {git_executable} {' '.join(args)}") from err

    try:
        toplevel_str = _run_git(["rev-parse", "--show-toplevel"], cwd=module_file.parent)
        repo_root = Path(toplevel_str).resolve()
    except ValueError as err:
        raise ValueError("installed-wheel or no git repository available") from err

    if not module_file.is_relative_to(repo_root):
        raise ValueError("module file is not within git repository root")

    if _run_git(["rev-parse", "--is-shallow-repository"]) != "false":
        raise ValueError("shallow repository forbidden")

    common_dir = Path(_run_git(["rev-parse", "--git-common-dir"]))
    if not common_dir.is_absolute():
        common_dir = (repo_root / common_dir).resolve()
    grafts_path = common_dir / "info" / "grafts"
    if grafts_path.exists() and grafts_path.stat().st_size > 0:
        raise ValueError("git grafts forbidden")

    if _run_git(["replace", "-l"]):
        raise ValueError("git replacement objects forbidden")

    if _run_git(["status", "--porcelain"]):
        raise ValueError("git worktree is not clean")

    head_commit = _run_git(["rev-parse", "HEAD"]).lower()
    head_tree = _run_git(["rev-parse", "HEAD^{tree}"]).lower()
    if head_commit != bindings["head_commit"] or head_tree != bindings["head_tree"]:
        raise ValueError("HEAD commit or tree binding mismatch")

    git_proof = chronology.get("git_proof")
    if not isinstance(git_proof, dict):
        raise ValueError("git_proof missing or invalid")

    if (
        git_proof.get("repair_landing_two_parent") is not True
        or git_proof.get("repair_diff_exact") is not True
        or git_proof.get("single_rebase") is not True
        or git_proof.get("range_diff_equivalent") is not True
    ):
        raise ValueError("git_proof booleans invalid")

    identities = git_proof.get("identities")
    if not isinstance(identities, dict):
        raise ValueError("git_proof identities missing")

    def _val_oid(oid: Any, kind: str) -> str:
        if not isinstance(oid, str) or len(oid) != 40 or oid != oid.lower() or any(c not in "0123456789abcdef" for c in oid):
            raise ValueError(f"invalid OID format: {oid}")
        try:
            actual_kind = _run_git(["cat-file", "-t", oid])
        except ValueError as err:
            raise ValueError(f"git object missing: {oid}") from err
        if actual_kind != kind:
            raise ValueError(f"git object type mismatch for {oid}: expected {kind}, got {actual_kind}")
        return oid

    required_commit_keys = [
        "test_parent",
        "test_candidate",
        "test_landing",
        "repair_parent",
        "repair_candidate",
        "repair_landing",
        "candidate_commit",
        "final_candidate",
        "canonical_main_head",
    ]
    if len(stages) == 3:
        required_commit_keys.extend(["implementation_parent", "implementation_landing"])

    for key in ("implementation_parent", "implementation_landing"):
        if identities.get(key) is not None:
            _val_oid(identities[key], "commit")
        elif identities.get("implementation_parent") is not None or identities.get("implementation_landing") is not None:
            raise ValueError("implementation landing identities must be provided together")

    for key in required_commit_keys:
        val = identities.get(key)
        if val is None and key.startswith("implementation_"):
            continue
        _val_oid(val, "commit")
        if key == "candidate_commit":
            tree_key = "candidate_tree"
        elif key == "canonical_main_head":
            tree_key = "canonical_main_head_tree"
        elif key.endswith("_commit"):
            tree_key = key.replace("_commit", "_tree")
        else:
            tree_key = f"{key}_tree"
        tree_val = identities.get(tree_key)
        _val_oid(tree_val, "tree")
        actual_tree = _run_git(["rev-parse", f"{val}^{{tree}}"]).lower()
        if actual_tree != tree_val:
            raise ValueError(f"commit tree mismatch for {key}")

    if identities["candidate_commit"] != bindings["candidate_commit"] or identities["candidate_tree"] != bindings["candidate_tree"]:
        raise ValueError("identities candidate binding mismatch")
    if identities["canonical_main_head"] != bindings["head_commit"] or identities["canonical_main_head_tree"] != bindings["head_tree"]:
        raise ValueError("identities HEAD binding mismatch")
    parent_vectors = git_proof.get("parent_vectors")
    if not isinstance(parent_vectors, dict):
        raise ValueError("parent_vectors missing")

    test_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["test_landing"]]).split()[1:]]
    if test_landing_pv != [identities["test_parent"], identities["test_candidate"]] or parent_vectors.get("test_landing") != test_landing_pv:
        raise ValueError("test_landing parent vector mismatch")

    repair_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["repair_landing"]]).split()[1:]]
    if repair_landing_pv != [identities["repair_parent"], identities["repair_candidate"]] or parent_vectors.get("repair_landing") != repair_landing_pv:
        raise ValueError("repair_landing parent vector mismatch")

    repair_cand_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["repair_candidate"]]).split()[1:]]
    if repair_cand_pv != [identities["repair_parent"]]:
        raise ValueError("repair_candidate must have exactly one parent")

    impl_landing = identities.get("implementation_landing")
    if impl_landing is not None:
        impl_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", impl_landing]).split()[1:]]
        if impl_landing_pv != [identities["implementation_parent"], identities["final_candidate"]] or parent_vectors.get("implementation_landing") != impl_landing_pv:
            raise ValueError("implementation_landing parent vector mismatch")
    elif parent_vectors.get("implementation_landing") != []:
        raise ValueError("implementation_landing parent vector must be empty when unset")

    def _check_ancestor(a: str, b: str) -> None:
        try:
            _run_git(["merge-base", "--is-ancestor", a, b])
        except ValueError as err:
            raise ValueError(f"ancestry check failed: {a} is not ancestor of {b}") from err

    _check_ancestor(identities["test_parent"], identities["test_candidate"])
    _check_ancestor(identities["test_landing"], identities["repair_parent"])
    _check_ancestor(identities["repair_landing"], identities["candidate_commit"])
    if identities["final_candidate"] != identities["candidate_commit"]:
        _check_ancestor(identities["candidate_commit"], identities["final_candidate"])
    if chronology.get("scope") == "exact_main":
        _check_ancestor(identities["final_candidate"], identities["canonical_main_head"])

    repair_paths = git_proof.get("repair_paths")
    expected_repair_paths = {
        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
        "phase-loop-runtime/tests/test_outside_agent_contract_drift.py",
        "phase-loop-runtime/tests/_outside_agent_canonical.py",
    }
    if not isinstance(repair_paths, dict) or set(repair_paths.keys()) != expected_repair_paths:
        raise ValueError("repair_paths inventory mismatch")

    changed_repair_files = set(_run_git(["diff", "--name-only", identities["repair_parent"], identities["repair_candidate"]]).splitlines())
    if changed_repair_files != expected_repair_paths:
        raise ValueError("repair commit changed files mismatch")

    for path, info in repair_paths.items():
        if not isinstance(info, dict) or set(info.keys()) != {"before_blob", "after_blob", "patch", "patch_digest"}:
            raise ValueError(f"repair_paths info shape mismatch for {path}")
        before_blob = _val_oid(info["before_blob"], "blob")
        after_blob = _val_oid(info["after_blob"], "blob")
        actual_before = _run_git(["rev-parse", f"{identities['repair_parent']}:{path}"]).lower()
        actual_after = _run_git(["rev-parse", f"{identities['repair_candidate']}:{path}"]).lower()
        if before_blob != actual_before or after_blob != actual_after:
            raise ValueError(f"repair blob mismatch for {path}")
        patch = _run_git(["diff", "--no-ext-diff", "--no-textconv", "--no-color", "-U0", identities["repair_parent"], identities["repair_candidate"], "--", path])
        if info["patch"] != patch:
            raise ValueError(f"repair patch mismatch for {path}")
        patch_digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        if info["patch_digest"] != patch_digest or patch_digest == "0" * 64 or not patch_digest:
            raise ValueError(f"repair patch digest mismatch for {path}")

    impl_slot = git_proof.get("implementation_patch_slot")
    if impl_slot is not None:
        if not isinstance(impl_slot, dict) or set(impl_slot.keys()) != {"path", "patch", "patch_digest"}:
            raise ValueError("implementation_patch_slot shape mismatch")
        if impl_slot["path"] != "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py":
            raise ValueError("implementation_patch_slot path mismatch")
        impl_patch_digest = hashlib.sha256(impl_slot["patch"].encode("utf-8")).hexdigest()
        if impl_slot["patch_digest"] != impl_patch_digest or impl_patch_digest == "0" * 64 or not impl_patch_digest:
            raise ValueError("implementation_patch_slot digest mismatch")

    red_refs = git_proof.get("red_references")
    green_refs = git_proof.get("green_references")
    if not isinstance(red_refs, dict) or set(red_refs.keys()) != {"junit", "raw_log"}:
        raise ValueError("red_references shape mismatch")
    if not isinstance(green_refs, dict) or set(green_refs.keys()) != {"junit", "raw_log"}:
        raise ValueError("green_references shape mismatch")

    for ref in (red_refs["junit"], red_refs["raw_log"], green_refs["junit"], green_refs["raw_log"]):
        if not isinstance(ref, dict) or set(ref.keys()) != {"path", "sha256"}:
            raise ValueError("reference shape mismatch")
        _read_verified(ref["path"], ref["sha256"])

    activated_lc = facts["lifecycle"]["activated"]
    default_lc = facts["lifecycle"]["default"]
    if red_refs["junit"]["path"] != activated_lc["junit_path"] or red_refs["junit"]["sha256"] != activated_lc["junit_sha256"]:
        raise ValueError("RED junit reference mismatch")
    if red_refs["raw_log"]["path"] != activated_lc["raw_log_path"] or red_refs["raw_log"]["sha256"] != activated_lc["raw_log_sha256"]:
        raise ValueError("RED raw_log reference mismatch")
    if green_refs["junit"]["path"] != default_lc["junit_path"] or green_refs["junit"]["sha256"] != default_lc["junit_sha256"]:
        raise ValueError("GREEN junit reference mismatch")
    if green_refs["raw_log"]["path"] != default_lc["raw_log_path"] or green_refs["raw_log"]["sha256"] != default_lc["raw_log_sha256"]:
        raise ValueError("GREEN raw_log reference mismatch")

    transition = git_proof.get("transition")
    if not isinstance(transition, dict) or set(transition.keys()) != {"original_commits", "rebased_commits", "range_diff"}:
        raise ValueError("transition shape mismatch")

    if len(stages) == 3:
        expected_original = [
            "59cbf5a167bfc8bde4e5841fd977e542158aff3d",
            "00dec41aa950f4d1affead3a9c7fdfea4e91099e",
            "7df3cc74ec1ba2cb3e3216624f611009dbae2eca",
            "974593899bbecfbe092ba0aec369e69eee1aabdd",
            "80d9a14c94785f81044d67b60e05d61242838a1b",
        ]
    else:
        expected_original = [
            "59cbf5a167bfc8bde4e5841fd977e542158aff3d",
            "00dec41aa950f4d1affead3a9c7fdfea4e91099e",
            "7df3cc74ec1ba2cb3e3216624f611009dbae2eca",
            "974593899bbecfbe092ba0aec369e69eee1aabdd",
        ]

    if transition.get("original_commits") != expected_original:
        raise ValueError("transition original_commits mismatch")

    orig_base = "287d447c37ce51b0ab5a7498e32d6c0c78c69027"
    orig_head = expected_original[-1]
    reb_head = identities["final_candidate"] if len(stages) == 3 else identities["candidate_commit"]
    repair_landing = identities["repair_landing"]

    actual_rebased = [c.lower() for c in _run_git(["rev-list", "--reverse", f"{repair_landing}..{reb_head}"]).splitlines()]
    if transition.get("rebased_commits") != actual_rebased:
        raise ValueError("transition rebased_commits mismatch")

    if len(stages) == 3:
        if len(actual_rebased) != 6:
            raise ValueError(f"unexpected rebased_commits count for final scope: {len(actual_rebased)}")
    else:
        if len(actual_rebased) not in (4, 5):
            raise ValueError(f"unexpected rebased_commits count for pre-doc scope: {len(actual_rebased)}")

    if len(actual_rebased) in (5, 6):
        inserted_commit = actual_rebased[4]
        inserted_parents = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", inserted_commit]).split()[1:]]
        if inserted_parents != [actual_rebased[3]]:
            raise ValueError("inserted verifier commit parent mismatch")
        inserted_files = set(_run_git(["diff", "--name-only", actual_rebased[3], inserted_commit]).splitlines())
        if inserted_files != {"phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py"}:
            raise ValueError("inserted verifier commit modified unexpected files")
        inserted_patch = _run_git(["diff", "--no-ext-diff", "--no-textconv", "--no-color", "-U0", actual_rebased[3], inserted_commit, "--", "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py"])
        inserted_digest = hashlib.sha256(inserted_patch.encode("utf-8")).hexdigest()
        if impl_slot is None or impl_slot.get("patch") != inserted_patch or impl_slot.get("patch_digest") != inserted_digest:
            raise ValueError("inserted verifier commit patch slot mismatch")
    elif impl_slot is not None:
        raise ValueError("implementation_patch_slot present when no inserted commit exists")

    actual_range_diff = _run_git(["range-diff", "--no-ext-diff", "--no-textconv", f"{orig_base}..{orig_head}", f"{repair_landing}..{reb_head}"])
    if transition.get("range_diff") != actual_range_diff:
        raise ValueError("transition range_diff mismatch")

    eq_matches = set()
    diff_matches = set()
    add_matches = set()
    authorized_diff_body = False
    for line in actual_range_diff.splitlines():
        line_str = line.strip()
        if not line_str:
            continue
        if authorized_diff_body:
            if not re.match(r"^(?:\d+:|-\s+:)", line):
                continue
            authorized_diff_body = False
        m_del = re.search(r"^\s*\d+:\s+[0-9a-fA-F]+\s+<\s+-\s*:\s*-+", line_str)
        if m_del:
            raise ValueError("range-diff contains dropped commit (<)")
        m_eq = re.search(r"^\s*(\d+):\s+([0-9a-fA-F]+)\s+=\s+(\d+):\s+([0-9a-fA-F]+)", line_str)
        if m_eq:
            old_idx, old_sha, new_idx, new_sha = int(m_eq.group(1)), m_eq.group(2).lower(), int(m_eq.group(3)), m_eq.group(4).lower()
            if old_idx != new_idx or old_idx < 1 or old_idx > 4:
                raise ValueError(f"range-diff equality out of bounds: {line_str}")
            if not expected_original[old_idx - 1].startswith(old_sha) or not actual_rebased[new_idx - 1].startswith(new_sha):
                raise ValueError(f"range-diff equality commit SHA mismatch: {line_str}")
            eq_matches.add(old_idx)
            authorized_diff_body = False
            continue
        m_diff = re.search(r"^\s*(\d+):\s+([0-9a-fA-F]+)\s+!\s+(\d+):\s+([0-9a-fA-F]+)", line_str)
        if m_diff:
            old_idx, old_sha, new_idx, new_sha = int(m_diff.group(1)), m_diff.group(2).lower(), int(m_diff.group(3)), m_diff.group(4).lower()
            if len(stages) != 3 or old_idx != 5 or new_idx != 6:
                raise ValueError(f"unauthorized range-diff patch modification (!): {line_str}")
            if not expected_original[4].startswith(old_sha) or not actual_rebased[5].startswith(new_sha):
                raise ValueError(f"range-diff doc commit SHA mismatch: {line_str}")
            diff_matches.add((old_idx, new_idx))
            authorized_diff_body = True
            continue
        m_add = re.search(r"^\s*-\s*:\s*-+\s+>\s+(\d+):\s+([0-9a-fA-F]+)", line_str)
        if m_add:
            new_idx, new_sha = int(m_add.group(1)), m_add.group(2).lower()
            if new_idx != 5 or len(actual_rebased) not in (5, 6):
                raise ValueError(f"unauthorized range-diff added commit (>): {line_str}")
            if not actual_rebased[4].startswith(new_sha):
                raise ValueError(f"range-diff added commit SHA mismatch: {line_str}")
            add_matches.add(new_idx)
            authorized_diff_body = False
            continue
        raise ValueError(f"unrecognized range-diff line: {line_str}")

    if eq_matches != {1, 2, 3, 4}:
        raise ValueError("first four original implementation commits must map with = in order")

    if len(stages) == 3:
        if len(diff_matches) != 1:
            raise ValueError("final scope requires exactly one ! mapping for docs commit")
    elif diff_matches:
        raise ValueError("pre-doc scope forbids ! mappings in range-diff")

    if len(actual_rebased) in (5, 6):
        if len(add_matches) != 1:
            raise ValueError("inserted verifier commit must map with > in range-diff")
    elif add_matches:
        raise ValueError("no added commits allowed when verifier commit is absent")

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


def _wheel_payload_members(members: dict[str, str]) -> dict[str, str]:
    dist_info_roots = {member.split("/", 1)[0] for member in members if member.split("/", 1)[0].endswith(".dist-info")}
    if len(dist_info_roots) != 1:
        raise ValueError("wheel must contain one dist-info root")
    dist_info_root = next(iter(dist_info_roots))
    if not dist_info_root.startswith("phase_loop_runtime-") or dist_info_root == "phase_loop_runtime-.dist-info":
        raise ValueError("wheel dist-info root does not match phase-loop-runtime")
    data_member = f"{dist_info_root[:-len('.dist-info')]}.data/data/share/phase-loop-runtime/protocol/protocol.md"
    if any(not (member.startswith("phase_loop_runtime/") or member.startswith(f"{dist_info_root}/") or member == data_member) for member in members):
        raise ValueError("wheel contains an unexpected top-level member")
    return {member: digest for member, digest in members.items() if member.startswith("phase_loop_runtime/") or member == data_member}


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
    direct_payload = _wheel_payload_members(archive_members["direct-wheel"])
    derived_payload = _wheel_payload_members(archive_members["sdist-derived-wheel"])
    if direct_payload != derived_payload:
        raise ValueError("wheel variants contain different runtime bytes")
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
