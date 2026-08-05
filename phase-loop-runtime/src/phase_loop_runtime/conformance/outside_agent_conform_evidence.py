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
        if scope == "exact_main":
            if topology.get("canonical_main_head") != bindings["head_commit"]:
                raise ValueError("exact-main chronology is not bound to HEAD")
        elif {"canonical_main_head", "canonical_main_head_tree", "implementation_parent", "implementation_parent_tree", "implementation_landing", "implementation_landing_tree"} & set(topology):
            raise ValueError("pre-merge chronology contains exact-main topology")

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
        "contract_bug_test_parent",
        "contract_bug_test_candidate",
        "contract_bug_test_landing",
        "seal_repair_parent",
        "seal_repair_candidate",
        "seal_repair_landing",
        "ci_evidence_parent",
        "ci_evidence_candidate",
        "ci_evidence_landing",
        "candidate_commit",
        "final_candidate",
    ]
    if scope in {"a2_candidate", "exact_main"}:
        required_commit_keys.append("canonical_main_head")
    if scope == "exact_main":
        required_commit_keys.extend(["implementation_parent", "implementation_landing"])

    expected_identity_keys = {
        *(item for key in required_commit_keys for item in (key, f"{key}_tree")),
    }
    expected_identity_keys.remove("candidate_commit_tree")
    expected_identity_keys.remove("final_candidate_tree")
    expected_identity_keys.update({"candidate_tree", "final_candidate_tree"})
    if "canonical_main_head" in required_commit_keys:
        expected_identity_keys.remove("canonical_main_head_tree")
        expected_identity_keys.add("canonical_main_head_tree")
    if set(identities) != expected_identity_keys:
        raise ValueError("git_proof identity inventory mismatch")

    for key in required_commit_keys:
        val = identities.get(key)
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
    if scope in {"a2_candidate", "exact_main"} and (identities["canonical_main_head"] != bindings["head_commit"] or identities["canonical_main_head_tree"] != bindings["head_tree"]):
        raise ValueError("identities HEAD binding mismatch")
    parent_vectors = git_proof.get("parent_vectors")
    if not isinstance(parent_vectors, dict):
        raise ValueError("parent_vectors missing")

    test_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["test_landing"]]).split()[1:]]
    if test_landing_pv != [identities["test_parent"], identities["test_candidate"]] or parent_vectors.get("test_landing") != test_landing_pv:
        raise ValueError("test_landing parent vector mismatch")

    test_candidate_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["test_candidate"]]).split()[1:]]
    if len(test_candidate_pv) != 1:
        raise ValueError("test_candidate must have exactly one parent")

    repair_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["repair_landing"]]).split()[1:]]
    if repair_landing_pv != [identities["repair_parent"], identities["repair_candidate"]] or parent_vectors.get("repair_landing") != repair_landing_pv:
        raise ValueError("repair_landing parent vector mismatch")

    repair_cand_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["repair_candidate"]]).split()[1:]]
    if repair_cand_pv != [identities["repair_parent"]]:
        raise ValueError("repair_candidate must have exactly one parent")

    contract_bug_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["contract_bug_test_landing"]]).split()[1:]]
    if contract_bug_landing_pv != [identities["contract_bug_test_parent"], identities["contract_bug_test_candidate"]] or parent_vectors.get("contract_bug_test_landing") != contract_bug_landing_pv:
        raise ValueError("contract_bug_test_landing parent vector mismatch")

    contract_bug_candidate_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["contract_bug_test_candidate"]]).split()[1:]]
    if contract_bug_candidate_pv != [identities["contract_bug_test_parent"]]:
        raise ValueError("contract_bug_test_candidate must have exactly one parent")

    seal_repair_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["seal_repair_landing"]]).split()[1:]]
    if seal_repair_landing_pv != [identities["seal_repair_parent"], identities["seal_repair_candidate"]] or parent_vectors.get("seal_repair_landing") != seal_repair_landing_pv:
        raise ValueError("seal_repair_landing parent vector mismatch")

    seal_repair_candidate_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["seal_repair_candidate"]]).split()[1:]]
    if seal_repair_candidate_pv != [identities["seal_repair_parent"]]:
        raise ValueError("seal_repair_candidate must have exactly one parent")

    ci_evidence_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["ci_evidence_landing"]]).split()[1:]]
    if ci_evidence_landing_pv != [identities["ci_evidence_parent"], identities["ci_evidence_candidate"]] or parent_vectors.get("ci_evidence_landing") != ci_evidence_landing_pv:
        raise ValueError("ci_evidence_landing parent vector mismatch")

    ci_evidence_candidate_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", identities["ci_evidence_candidate"]]).split()[1:]]
    if ci_evidence_candidate_pv != [identities["ci_evidence_parent"]]:
        raise ValueError("ci_evidence_candidate must have exactly one parent")

    expected_parent_vectors = {"test_landing", "repair_landing", "contract_bug_test_landing", "seal_repair_landing", "ci_evidence_landing"}
    if scope == "exact_main":
        expected_parent_vectors.add("implementation_landing")
    if set(parent_vectors) != expected_parent_vectors:
        raise ValueError("parent vector inventory mismatch")

    if scope == "exact_main":
        impl_landing = identities["implementation_landing"]
        impl_landing_pv = [p.lower() for p in _run_git(["rev-list", "--parents", "-n", "1", impl_landing]).split()[1:]]
        if impl_landing_pv != [identities["implementation_parent"], identities["final_candidate"]] or parent_vectors.get("implementation_landing") != impl_landing_pv:
            raise ValueError("implementation_landing parent vector mismatch")
        if impl_landing != identities["canonical_main_head"]:
            raise ValueError("exact-main implementation landing is not canonical main")

    def _check_ancestor(a: str, b: str) -> None:
        try:
            _run_git(["merge-base", "--is-ancestor", a, b])
        except ValueError as err:
            raise ValueError(f"ancestry check failed: {a} is not ancestor of {b}") from err

    _check_ancestor(identities["test_parent"], identities["test_candidate"])
    _check_ancestor(identities["test_landing"], identities["repair_parent"])
    _check_ancestor(identities["repair_landing"], identities["contract_bug_test_parent"])
    _check_ancestor(identities["contract_bug_test_landing"], identities["seal_repair_parent"])
    _check_ancestor(identities["seal_repair_landing"], identities["ci_evidence_parent"])
    _check_ancestor(identities["ci_evidence_landing"], identities["candidate_commit"])
    if identities["final_candidate"] != identities["candidate_commit"]:
        _check_ancestor(identities["candidate_commit"], identities["final_candidate"])
    if scope == "exact_main":
        _check_ancestor(identities["final_candidate"], identities["canonical_main_head"])

    expected_repair_paths = {
        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
        "phase-loop-runtime/tests/test_outside_agent_contract_drift.py",
        "phase-loop-runtime/tests/_outside_agent_canonical.py",
    }
    expected_contract_bug_paths = {
        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
        "phase-loop-runtime/tests/test_outside_agent_release_surface.py",
        "phase-loop-runtime/tests/_outside_agent_canonical.py",
    }
    expected_seal_repair_paths = {
        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
        "phase-loop-runtime/tests/_outside_agent_canonical.py",
    }
    expected_ci_evidence_paths = {
        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
        "phase-loop-runtime/tests/test_outside_agent_release_surface.py",
        "phase-loop-runtime/tests/_outside_agent_canonical.py",
    }

    def _validate_exact_patch(
        proof_key: str,
        parent_key: str,
        candidate_key: str,
        expected_paths: set[str],
    ) -> None:
        path_proofs = git_proof.get(proof_key)
        if not isinstance(path_proofs, dict) or set(path_proofs) != expected_paths:
            raise ValueError(f"{proof_key} inventory mismatch")
        parent, candidate = identities[parent_key], identities[candidate_key]
        changed_paths = set(_run_git(["diff", "--name-only", parent, candidate]).splitlines())
        if changed_paths != expected_paths:
            raise ValueError(f"{proof_key} changed files mismatch")
        for path, info in path_proofs.items():
            if not isinstance(info, dict) or set(info) != {"before_blob", "after_blob", "patch", "patch_digest"}:
                raise ValueError(f"{proof_key} info shape mismatch for {path}")
            before_blob = _val_oid(info["before_blob"], "blob")
            after_blob = _val_oid(info["after_blob"], "blob")
            if before_blob != _run_git(["rev-parse", f"{parent}:{path}"]).lower() or after_blob != _run_git(["rev-parse", f"{candidate}:{path}"]).lower():
                raise ValueError(f"{proof_key} blob mismatch for {path}")
            patch = _run_git(["diff", "--no-ext-diff", "--no-textconv", "--no-color", "-U0", parent, candidate, "--", path])
            patch_digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
            if info["patch"] != patch or info["patch_digest"] != patch_digest or patch_digest == "0" * 64:
                raise ValueError(f"{proof_key} patch mismatch for {path}")

    _validate_exact_patch(
        "repair_paths",
        "repair_parent",
        "repair_candidate",
        expected_repair_paths,
    )
    _validate_exact_patch(
        "contract_bug_paths",
        "contract_bug_test_parent",
        "contract_bug_test_candidate",
        expected_contract_bug_paths,
    )
    _validate_exact_patch(
        "seal_repair_paths",
        "seal_repair_parent",
        "seal_repair_candidate",
        expected_seal_repair_paths,
    )
    _validate_exact_patch(
        "ci_evidence_paths",
        "ci_evidence_parent",
        "ci_evidence_candidate",
        expected_ci_evidence_paths,
    )

    impl_slot = git_proof.get("implementation_patch_slot")
    if impl_slot is not None:
        if not isinstance(impl_slot, dict) or set(impl_slot.keys()) != {"path", "patch", "patch_digest"}:
            raise ValueError("implementation_patch_slot shape mismatch")
        if impl_slot["path"] != "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py":
            raise ValueError("implementation_patch_slot path mismatch")
        impl_patch_digest = hashlib.sha256(impl_slot["patch"].encode("utf-8")).hexdigest()
        if impl_slot["patch_digest"] != impl_patch_digest or impl_patch_digest == "0" * 64 or not impl_patch_digest:
            raise ValueError("implementation_patch_slot digest mismatch")

    merge_result_trees = git_proof.get("merge_result_trees")
    if not isinstance(merge_result_trees, dict) or set(merge_result_trees) != expected_parent_vectors:
        raise ValueError("merge-result tree inventory mismatch")
    for landing_key in expected_parent_vectors:
        landing = identities[landing_key]
        parents = parent_vectors[landing_key]
        result_tree = _val_oid(merge_result_trees[landing_key], "tree")
        recomputed_tree = _run_git(["merge-tree", "--write-tree", *parents]).lower()
        landing_tree = _run_git(["rev-parse", f"{landing}^{{tree}}"]).lower()
        if result_tree != recomputed_tree or result_tree != landing_tree:
            raise ValueError(f"merge-result tree mismatch for {landing_key}")

    b1_paths = (
        "CHANGELOG.md",
        "docs/outside-agent-conformance.md",
        "docs/releases/outside-agent-release-handoff.md",
        "specs/phase-plans-v7.md",
    )

    def _git_blob_bytes(commit: str, path: str) -> tuple[str, bytes]:
        blob_oid = _val_oid(_run_git(["rev-parse", f"{commit}:{path}"]).lower(), "blob")
        try:
            completed = subprocess.run(
                [git_executable, "-c", "core.attributesFile=/dev/null", "-c", "diff.external=", "cat-file", "blob", blob_oid],
                cwd=repo_root,
                capture_output=True,
                env=clean_env,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as err:
            raise ValueError(f"unable to read B1 blob: {path}") from err
        return blob_oid, completed.stdout

    b1_content = git_proof.get("b1_content")
    if not isinstance(b1_content, dict) or b1_content.get("paths") != list(b1_paths):
        raise ValueError("B1 content map missing or unordered")
    members = b1_content.get("members")
    if not isinstance(members, dict) or set(members) != set(b1_paths):
        raise ValueError("B1 member inventory mismatch")
    final_document_bytes: dict[str, bytes] = {}
    for path in b1_paths:
        entry = members[path]
        if not isinstance(entry, dict) or set(entry) != {"blob_oid", "sha256"}:
            raise ValueError(f"B1 member shape mismatch for {path}")
        blob_oid, contents = _git_blob_bytes(identities["final_candidate"], path)
        if entry["blob_oid"] != blob_oid or entry["sha256"] != _sha256_bytes(contents):
            raise ValueError(f"B1 member content mismatch for {path}")
        final_document_bytes[path] = contents

    if scope in {"b2_premerge", "exact_main"}:
        if set(b1_content) != {"paths", "members", "rendering", "candidate_only_documents"}:
            raise ValueError("B1 content binding shape mismatch")
        rendering = b1_content["rendering"]
        candidate_only = b1_content["candidate_only_documents"]
        if not isinstance(rendering, dict) or set(rendering) != {"template", "accepted_document_commit", "candidate_commit", "candidate_tree", "package_evidence", "documents"}:
            raise ValueError("B1 rendering shape mismatch")
        if rendering["template"] != "accepted-80d9a14-candidate-only-b2" or rendering["accepted_document_commit"] != "80d9a14c94785f81044d67b60e05d61242838a1b" or rendering["candidate_commit"] != identities["candidate_commit"] or rendering["candidate_tree"] != identities["candidate_tree"]:
            raise ValueError("B1 rendering provenance mismatch")
        if not isinstance(candidate_only, dict) or set(candidate_only) != set(b1_paths) or not isinstance(rendering["documents"], dict) or set(rendering["documents"]) != set(b1_paths):
            raise ValueError("B1 document inventory mismatch")
        package_evidence = rendering["package_evidence"]
        if not isinstance(package_evidence, dict) or set(package_evidence) != {"candidate_commit", "candidate_tree", "candidate_members", "archives", "a2_package_evidence_sha256"}:
            raise ValueError("B1 package evidence shape mismatch")
        package_digest = _canonical_digest({key: value for key, value in package_evidence.items() if key != "a2_package_evidence_sha256"})
        if package_evidence["candidate_commit"] != identities["candidate_commit"] or package_evidence["candidate_tree"] != identities["candidate_tree"] or package_evidence["a2_package_evidence_sha256"] != package_digest:
            raise ValueError("B1 package evidence mismatch")
        expected_contract, _ = _expected_contract_members()
        expected_archives = {
            label: {
                "sha256": facts["archives"][label]["sha256"],
                "members": expected_contract,
            }
            for label in _PACKAGE_VARIANTS
        }
        if package_evidence["archives"] != expected_archives or not isinstance(package_evidence["candidate_members"], dict) or not package_evidence["candidate_members"]:
            raise ValueError("B1 sealed package inputs mismatch")
        for candidate_path, digest in package_evidence["candidate_members"].items():
            if not isinstance(candidate_path, str) or not isinstance(digest, str):
                raise ValueError("B1 candidate member malformed")
            _, candidate_member = _git_blob_bytes(
                identities["candidate_commit"], candidate_path
            )
            if digest != _sha256_bytes(candidate_member):
                raise ValueError("B1 candidate member digest mismatch")
        for path in b1_paths:
            candidate_blob, candidate_bytes = _git_blob_bytes(identities["candidate_commit"], path)
            del candidate_blob
            rendered = rendering["documents"][path]
            candidate_record = candidate_only[path]
            if not isinstance(rendered, dict) or set(rendered) != {"candidate_sha256", "body", "sha256"} or not isinstance(candidate_record, dict) or set(candidate_record) != {"candidate_commit", "candidate_tree", "forbidden_identity_values"}:
                raise ValueError(f"B1 document shape mismatch for {path}")
            if candidate_record["candidate_commit"] != identities["candidate_commit"] or candidate_record["candidate_tree"] != identities["candidate_tree"] or rendered["candidate_sha256"] != _sha256_bytes(candidate_bytes) or not isinstance(rendered["body"], str):
                raise ValueError(f"B1 candidate binding mismatch for {path}")
            rendered_bytes = rendered["body"].encode("utf-8")
            if rendered_bytes != final_document_bytes[path] or rendered["sha256"] != _sha256_bytes(rendered_bytes):
                raise ValueError(f"B1 rendered bytes mismatch for {path}")
            forbidden_values = candidate_record["forbidden_identity_values"]
            if not isinstance(forbidden_values, dict) or not forbidden_values or any(
                not isinstance(value, str)
                or not value
                or value in {identities["candidate_commit"], identities["candidate_tree"]}
                or value in rendered["body"]
                for value in forbidden_values.values()
            ):
                raise ValueError(f"B1 candidate-only identity mismatch for {path}")
            lowered_body = rendered["body"].lower()
            forbidden_labels = (
                "final implementation commit",
                "final implementation tree",
                "final_commit",
                "final_tree",
                "final-candidate",
                "final_candidate",
                "implementation-landing",
                "implementation_landing",
                "canonical-main",
                "canonical_main",
                "exact-main",
                "exact_main",
            )
            if any(label in lowered_body for label in forbidden_labels):
                raise ValueError(f"B1 document contains runner-only identity: {path}")
    elif set(b1_content) != {"paths", "members"}:
        raise ValueError("pre-document B1 content must not contain final bindings")

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
    transition_keys = {
        "base_commit",
        "original_commits",
        "reviewed_f17ab557_commits",
        "rebased_commits",
        "range_diff",
    }
    if not isinstance(transition, dict) or set(transition) != transition_keys:
        raise ValueError("transition shape mismatch")
    if transition.get("base_commit") != identities["ci_evidence_landing"]:
        raise ValueError("transition base mismatch")

    historical = git_proof.get("historical_repair_transition")
    historical_keys = {"base_commit", "original_commits", "rebased_commits", "range_diff"}
    if not isinstance(historical, dict) or set(historical) != historical_keys:
        raise ValueError("historical transition shape mismatch")
    if historical.get("base_commit") != identities["repair_landing"]:
        raise ValueError("historical transition base mismatch")
    historical_original = [
        "59cbf5a167bfc8bde4e5841fd977e542158aff3d",
        "00dec41aa950f4d1affead3a9c7fdfea4e91099e",
        "7df3cc74ec1ba2cb3e3216624f611009dbae2eca",
        "974593899bbecfbe092ba0aec369e69eee1aabdd",
    ]
    reviewed_head = "f17ab557c46acdaf748f0b46412a99062d98c3bf"
    reviewed_commits = [
        commit.lower()
        for commit in _run_git(
            ["rev-list", "--reverse", f'{identities["repair_landing"]}..{reviewed_head}']
        ).splitlines()
    ]
    if historical.get("original_commits") != historical_original:
        raise ValueError("historical original_commits mismatch")
    if historical.get("rebased_commits") != reviewed_commits:
        raise ValueError("historical rebased_commits mismatch")
    historical_range_diff = _run_git([
        "range-diff", "--no-color", "--no-ext-diff", "--no-textconv",
        f"287d447c37ce51b0ab5a7498e32d6c0c78c69027..{historical_original[-1]}",
        f'{identities["repair_landing"]}..{reviewed_head}',
    ])
    if historical.get("range_diff") != historical_range_diff:
        raise ValueError("historical range_diff mismatch")
    if transition.get("reviewed_f17ab557_commits") != reviewed_commits:
        raise ValueError("reviewed f17ab557 vector mismatch")

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
    transition_base = identities["ci_evidence_landing"]

    actual_rebased = [c.lower() for c in _run_git(["rev-list", "--reverse", f"{transition_base}..{reb_head}"]).splitlines()]
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

    actual_range_diff = _run_git(["range-diff", "--no-color", "--no-ext-diff", "--no-textconv", f"{orig_base}..{orig_head}", f"{transition_base}..{reb_head}"])
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
