from __future__ import annotations

import ast
import copy
import hashlib
import io
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as element_tree
import zipfile
from pathlib import Path

import pytest

from _outside_agent_canonical import (
    A2_COMMAND,
    A2_COLLECT_COMMAND,
    A2_GREEN_NODE_COUNT,
    A2_GREEN_NODE_IDS,
    ALL_OUTSIDE_AGENT_NODE_COUNT,
    ALL_OUTSIDE_AGENT_NODE_IDS,
    B0_COLLECT_COMMAND,
    B0_COMMAND,
    BROAD_COLLECT_COMMAND,
    CONFORM_ACTIVATED_RED_ANCHORS,
    CONFORM_ACTIVATED_RED_NODE_COUNT,
    CONFORM_ACTIVATED_RED_NODE_IDS,
    CONFORM_CANONICAL_CASES,
    CONFORM_DIALECT_MIGRATED_NODE_COUNT,
    CONFORM_DIALECT_MIGRATED_NODE_IDS,
    CONFORM_MIGRATED_EXISTING_NODE_COUNT,
    CONFORM_MIGRATED_EXISTING_NODE_IDS,
    CONFORM_MIGRATED_RED_NODE_COUNT,
    CONFORM_MIGRATED_RED_NODE_IDS,
    CONFORM_MUTATION_DEFINITIONS,
    CONFORM_NEW_PRODUCTION_NODE_COUNT,
    CONFORM_NEW_PRODUCTION_NODE_IDS,
    CONFORM_PREEXISTING_NODE_COUNT,
    CONFORM_PREEXISTING_NODE_IDS,
    CONFORM_SL2_STALE_DOC_NODE_COUNT,
    CONFORM_SL2_STALE_DOC_NODE_IDS,
    CONFORM_TEST_ONLY_INTEGRITY_NODE_COUNT,
    CONFORM_TEST_ONLY_INTEGRITY_NODE_IDS,
    EVIDENCE_VERIFIER_INTERFACE,
    EVIDENCE_VERIFIER_RECORD_IDS,
    FIXTURE_ROOT,
    IMMUTABLE_SPEC_V0_2_1_FILES,
    REPO_ROOT,
    SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS,
    SEALED_RELEASE_ARCHIVE_MEMBERS,
    SEALED_RELEASE_CANDIDATE_PARENT_BLOBS,
    SEALED_RELEASE_CANDIDATE_PATHS,
    SEALED_RELEASE_FINAL_PARENT_BLOBS,
    SEALED_RELEASE_FINAL_PATHS,
    evidence_verifier_argv,
    find_non_enumerated_canonical_copies,
    fixture_paths,
    normalized_nodeid,
    sealed_release_candidate_bytes,
    sealed_release_evidence,
    sealed_release_final_bytes,
    sealed_release_parent_bytes,
    _member_digests,
    _sealed_manifest_sha256,
    _normalized_archive_member_digests,
    node_source_path,
)


EVIDENCE_MODE_EXCLUSIVE_INPUTS = {
    "chronology": ("chronology",),
    "corpus": ("fixture_manifest",),
    "package": ("direct_wheel", "direct_sdist", "sdist_derived_wheel"),
    "compatibility": ("ec_matrix", "installed_package"),
}


def test_frozen_inventory_counts_and_set_equations() -> None:
    assert len(ALL_OUTSIDE_AGENT_NODE_IDS) == ALL_OUTSIDE_AGENT_NODE_COUNT == 93
    assert len(CONFORM_PREEXISTING_NODE_IDS) == CONFORM_PREEXISTING_NODE_COUNT == 71
    assert len(CONFORM_TEST_ONLY_INTEGRITY_NODE_IDS) == CONFORM_TEST_ONLY_INTEGRITY_NODE_COUNT == 12
    assert len(CONFORM_NEW_PRODUCTION_NODE_IDS) == CONFORM_NEW_PRODUCTION_NODE_COUNT == 10
    assert len(CONFORM_DIALECT_MIGRATED_NODE_IDS) == CONFORM_DIALECT_MIGRATED_NODE_COUNT == 42
    assert len(CONFORM_MIGRATED_EXISTING_NODE_IDS) == CONFORM_MIGRATED_EXISTING_NODE_COUNT == 45
    assert len(CONFORM_MIGRATED_RED_NODE_IDS) == CONFORM_MIGRATED_RED_NODE_COUNT == 44
    assert len(CONFORM_ACTIVATED_RED_NODE_IDS) == CONFORM_ACTIVATED_RED_NODE_COUNT == 54
    assert len(CONFORM_SL2_STALE_DOC_NODE_IDS) == CONFORM_SL2_STALE_DOC_NODE_COUNT == 4
    assert len(A2_GREEN_NODE_IDS) == A2_GREEN_NODE_COUNT == 89
    assert len(set(ALL_OUTSIDE_AGENT_NODE_IDS)) == len(ALL_OUTSIDE_AGENT_NODE_IDS)
    assert set(ALL_OUTSIDE_AGENT_NODE_IDS) == (
        set(CONFORM_PREEXISTING_NODE_IDS)
        | set(CONFORM_TEST_ONLY_INTEGRITY_NODE_IDS)
        | set(CONFORM_NEW_PRODUCTION_NODE_IDS)
    )
    assert set(CONFORM_PREEXISTING_NODE_IDS).isdisjoint(CONFORM_TEST_ONLY_INTEGRITY_NODE_IDS)
    assert set(CONFORM_PREEXISTING_NODE_IDS).isdisjoint(CONFORM_NEW_PRODUCTION_NODE_IDS)
    assert set(CONFORM_TEST_ONLY_INTEGRITY_NODE_IDS).isdisjoint(CONFORM_NEW_PRODUCTION_NODE_IDS)
    assert set(CONFORM_DIALECT_MIGRATED_NODE_IDS) <= set(CONFORM_MIGRATED_EXISTING_NODE_IDS)
    assert set(CONFORM_MIGRATED_EXISTING_NODE_IDS) <= set(CONFORM_PREEXISTING_NODE_IDS)
    assert set(CONFORM_MIGRATED_RED_NODE_IDS) <= set(CONFORM_MIGRATED_EXISTING_NODE_IDS)
    assert set(CONFORM_ACTIVATED_RED_NODE_IDS) == (
        set(CONFORM_NEW_PRODUCTION_NODE_IDS) | set(CONFORM_MIGRATED_RED_NODE_IDS)
    )
    stale_new = set(CONFORM_SL2_STALE_DOC_NODE_IDS) & set(CONFORM_NEW_PRODUCTION_NODE_IDS)
    stale_migrated = set(CONFORM_SL2_STALE_DOC_NODE_IDS) & set(CONFORM_MIGRATED_EXISTING_NODE_IDS)
    assert len(stale_new) == len(stale_migrated) == 2
    assert set(CONFORM_SL2_STALE_DOC_NODE_IDS) == stale_new | stale_migrated
    assert set(A2_GREEN_NODE_IDS) == set(ALL_OUTSIDE_AGENT_NODE_IDS) - set(CONFORM_SL2_STALE_DOC_NODE_IDS)
    no_copy = (
        "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::"
        "test_no_copied_canonical_outside_agent_schema_or_vectors"
    )
    archive = (
        "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::"
        "test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror"
    )
    assert hashlib.sha256((no_copy + "\n").encode()).hexdigest() == (
        "7755a4d356a9f285e8dd621e74dc14297901b1b5a44bd60198028809eecd73fe"
    )
    assert hashlib.sha256((archive + "\n").encode()).hexdigest() == (
        "ccb295db192a045c224dc7f74819f8b83adb6db348d8d8b2d155a5c4f73005c0"
    )


def test_frozen_command_literals_and_selector_partition() -> None:
    assert BROAD_COLLECT_COMMAND == (
        "PYTHONPATH=phase-loop-runtime/src python3 -m pytest "
        "phase-loop-runtime/tests -q --collect-only -k outside_agent"
    )
    assert A2_COMMAND.endswith(
        "test_public_docs_point_to_handoff_without_claiming_release_dispatch)\""
    )
    assert A2_COLLECT_COMMAND == A2_COMMAND + " --collect-only"
    assert B0_COLLECT_COMMAND == B0_COMMAND + " --collect-only"
    for nodeid in CONFORM_SL2_STALE_DOC_NODE_IDS:
        assert nodeid.rsplit("::", 1)[1] in B0_COMMAND
    assert all(nodeid not in CONFORM_SL2_STALE_DOC_NODE_IDS for nodeid in A2_GREEN_NODE_IDS)
    standalone_nodeid = CONFORM_NEW_PRODUCTION_NODE_IDS[0]
    standalone_path = "/tmp/standalone/" + standalone_nodeid
    assert normalized_nodeid(standalone_path) == standalone_nodeid
    assert normalized_nodeid(standalone_nodeid) == standalone_nodeid


def test_planted_non_enumerated_copy_reports_its_exact_path(tmp_path) -> None:
    planted = (
        tmp_path
        / "phase-loop-runtime"
        / "src"
        / "phase_loop_runtime"
        / "_sl0_planted"
        / "outside-agent-submission.schema.json"
    )
    planted.parent.mkdir(parents=True)
    planted.write_bytes(
        (FIXTURE_ROOT / "schemas" / "outside-agent-submission.schema.json").read_bytes()
    )
    copied, scanned = find_non_enumerated_canonical_copies(tmp_path)
    assert scanned == 1
    assert copied == (
        "phase-loop-runtime/src/phase_loop_runtime/_sl0_planted/"
        "outside-agent-submission.schema.json",
    )
    planted.write_text(
        (FIXTURE_ROOT / "schemas" / "outside-agent-submission.schema.json").read_text(
            encoding="utf-8"
        )
        .replace(
            '"$id": "https://spec.consiliency/schemas/outside-agent-submission.schema.json"',
            '"$id": "https://example.test/changed-copy.json"',
        )
        .replace('"title": "Outside-agent submission contract"', '"title": "modified copy"')
        .replace('"submission_id": {', '"submission_id": {\n      "description": "changed property",'),
        encoding="utf-8",
    )
    copied, scanned = find_non_enumerated_canonical_copies(tmp_path)
    assert scanned == 1
    assert copied == (
        "phase-loop-runtime/src/phase_loop_runtime/_sl0_planted/"
        "outside-agent-submission.schema.json",
    )


def test_conform_red_assertion_catalog_is_literal(tmp_path) -> None:
    assert set(CONFORM_ACTIVATED_RED_ANCHORS) == set(CONFORM_ACTIVATED_RED_NODE_IDS)
    assert all(anchor.startswith("CONFORM_RED::") for anchor in CONFORM_ACTIVATED_RED_ANCHORS.values())
    nodeid = (
        "phase-loop-runtime/tests/test_outside_agent_core_api.py::"
        "test_public_core_api_returns_typed_metadata_only_verdict"
    )
    test_path = node_source_path(nodeid)
    source_root = REPO_ROOT / "phase-loop-runtime" / "src"
    pythonpath = [str(test_path.parent)]
    if source_root.is_dir():
        pythonpath.insert(0, str(source_root))
    inherited_pythonpath = os.environ.get("PYTHONPATH")
    if inherited_pythonpath:
        pythonpath.extend(path for path in inherited_pythonpath.split(os.pathsep) if path)
    counter_path = tmp_path / "migrated-body-count.json"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(test_path) + "::" + nodeid.rsplit("::", 1)[1]],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(pythonpath),
            "PHASE_LOOP_TDD_EXPECT_CONFORM": "1",
            "PHASE_LOOP_CONFORM_BODY_COUNTER": str(counter_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(counter_path.read_text(encoding="utf-8")) == {nodeid: 1}
    conftest_tree = ast.parse(
        (REPO_ROOT / "phase-loop-runtime/tests/conftest.py").read_text(encoding="utf-8")
    )
    assert not any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "runtest"
        for call in ast.walk(conftest_tree)
    )
    if completed.returncode:
        assert CONFORM_ACTIVATED_RED_ANCHORS[nodeid] in completed.stdout + completed.stderr

    # Runner-owned pre-freeze evidence opts into the checkout/archive reconstruction.
    # Ordinary pytest and Gate A always prove the sealed fixture members directly.
    source_release_proof = (
        os.environ.get("PHASE_LOOP_CONFORM_SOURCE_RELEASE_PROOF") == "1"
        and (REPO_ROOT / "phase-loop-runtime/pyproject.toml").is_file()
        and (REPO_ROOT / "CHANGELOG.md").is_file()
        and (REPO_ROOT / "docs").is_dir()
        and (REPO_ROOT / "specs").is_dir()
        and importlib.util.find_spec("build") is not None
    )
    if not source_release_proof:
        installed_conformance = importlib.util.find_spec("phase_loop_runtime.conformance")
        assert installed_conformance is not None and installed_conformance.origin is not None
        assert Path(installed_conformance.origin).is_file()
        fixture_members = {
            "phase_loop_runtime/conformance/_contract/" + relative: (
                FIXTURE_ROOT / relative
            ).read_bytes()
            for relative in fixture_paths()
        }
        vendor_bytes = json.dumps(
            {
                "files": [
                    {
                        "source_path": source_path,
                        "mirror_path": mirror_path,
                        "raw_byte_sha256": digest,
                    }
                    for source_path, mirror_path, digest in IMMUTABLE_SPEC_V0_2_1_FILES
                ]
            },
            sort_keys=True,
        ).encode("utf-8")
        fixture_members["phase_loop_runtime/conformance/_contract/VENDOR.json"] = vendor_bytes
        assert _member_digests(fixture_members) == SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS
        return

    release_repo = tmp_path / "sealed-release-history"
    release_repo.mkdir()

    def git(*argv: str) -> str:
        result = subprocess.run(
            ["git", *argv], cwd=release_repo, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    parent_bytes = sealed_release_parent_bytes()
    candidate_bytes = sealed_release_candidate_bytes()
    final_bytes = sealed_release_final_bytes(candidate_bytes)
    assert set(parent_bytes) == set(candidate_bytes) == set(SEALED_RELEASE_CANDIDATE_PATHS)
    assert set(final_bytes) == set(candidate_bytes) | set(SEALED_RELEASE_FINAL_PATHS)
    assert all(b"CAPABILITY = 'candidate'" not in value for value in candidate_bytes.values())

    git("init")
    git("config", "user.email", "conform@example.test")
    git("config", "user.name", "CONFORM release runner")
    shutil.copytree(
        REPO_ROOT / "phase-loop-runtime",
        release_repo / "phase-loop-runtime",
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    for relative in ("CHANGELOG.md", "docs", "specs"):
        source = REPO_ROOT / relative
        destination = release_repo / relative
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    for path, contents in parent_bytes.items():
        if contents is None:
            (release_repo / path).unlink(missing_ok=True)
            continue
        materialized = release_repo / path
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_bytes(contents)
    for path in SEALED_RELEASE_FINAL_PATHS:
        marker = f"\n<!-- CONFORM_SL2_TRANSITION:{path}:".encode("utf-8")
        materialized = release_repo / path
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_bytes(final_bytes[path].split(marker, 1)[0])
    git("add", "-A")
    git("commit", "-m", "ratified SL-1 parent")

    for path, contents in candidate_bytes.items():
        materialized = release_repo / path
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_bytes(contents)
    git("add", "-A")
    git("commit", "-m", "full SL-1 candidate")
    candidate_commit = git("rev-parse", "HEAD")
    candidate_tree = git("rev-parse", "HEAD^{tree}")

    for path in SEALED_RELEASE_FINAL_PATHS:
        (release_repo / path).write_bytes(final_bytes[path])
    git("add", "-A")
    git("commit", "-m", "exact SL-2 final transition")
    final_commit = git("rev-parse", "HEAD")
    final_tree = git("rev-parse", "HEAD^{tree}")

    assert tuple(sorted(SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS)) == SEALED_RELEASE_ARCHIVE_MEMBERS
    candidate_export = tmp_path / "candidate-export"
    candidate_export.mkdir()
    exported = subprocess.run(
        ["git", "archive", "--format=tar", candidate_commit],
        cwd=release_repo,
        capture_output=True,
        check=False,
    )
    assert exported.returncode == 0
    with tarfile.open(fileobj=io.BytesIO(exported.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            assert member.isfile() and ".." not in Path(member.name).parts
            destination = candidate_export / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            assert extracted is not None
            destination.write_bytes(extracted.read())
    candidate_runtime = candidate_export / "phase-loop-runtime"
    direct_wheel_dist = tmp_path / "direct-wheel-dist"
    direct_sdist_dist = tmp_path / "direct-sdist-dist"
    for arguments, dist_root in (
        (("--wheel",), direct_wheel_dist),
        (("--sdist",), direct_sdist_dist),
    ):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                *arguments,
                "--no-isolation",
                "--outdir",
                str(dist_root),
                str(candidate_runtime),
            ],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "SOURCE_DATE_EPOCH": "315532800"},
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
    direct_wheel = next(direct_wheel_dist.glob("*.whl"))
    direct_sdist = next(direct_sdist_dist.glob("*.tar.gz"))
    sdist_export = tmp_path / "sdist-export"
    sdist_export.mkdir()
    with tarfile.open(direct_sdist) as archive:
        archive.extractall(sdist_export, filter="data")
    sdist_root = next(path for path in sdist_export.iterdir() if path.is_dir())
    derived_wheel_dist = tmp_path / "sdist-derived-wheel-dist"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(derived_wheel_dist),
            str(sdist_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SOURCE_DATE_EPOCH": "315532800"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    derived_wheel = next(derived_wheel_dist.glob("*.whl"))
    archives = {
        label: {
            "path": str(archive_path),
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "members": SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS,
        }
        for label, archive_path in (
            ("direct-wheel", direct_wheel),
            ("direct-sdist", direct_sdist),
            ("sdist-derived-wheel", derived_wheel),
        )
    }
    sealed = {
        "owner": "phase-loop-runner",
        "source_date_epoch": "315532800",
        "candidate_commit": candidate_commit,
        "candidate_tree": candidate_tree,
        "candidate_paths": list(SEALED_RELEASE_CANDIDATE_PATHS),
        "candidate_members": _member_digests(candidate_bytes),
        "candidate_parent_blobs": SEALED_RELEASE_CANDIDATE_PARENT_BLOBS,
        "final_commit": final_commit,
        "final_tree": final_tree,
        "final_paths": list(SEALED_RELEASE_FINAL_PATHS),
        "final_members": _member_digests(
            {path: final_bytes[path] for path in SEALED_RELEASE_FINAL_PATHS}
        ),
        "final_parent_blobs": SEALED_RELEASE_FINAL_PARENT_BLOBS,
        "archives": archives,
    }
    sealed["manifest_sha256"] = _sealed_manifest_sha256(sealed)
    sealed_path = tmp_path / "sealed-release-evidence.json"
    sealed_path.write_text(json.dumps(sealed, sort_keys=True), encoding="utf-8")
    assert sealed_release_evidence(sealed_path, release_repo) == sealed
    forged = copy.deepcopy(sealed)
    for label in ("direct-wheel", "sdist-derived-wheel"):
        forged["archives"][label] = copy.deepcopy(
            sealed["archives"]["sdist-derived-wheel"]
        )
        forged["archives"][label]["sha256"] = hashlib.sha256(
            Path(forged["archives"][label]["path"]).read_bytes()
        ).hexdigest()
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    # Freeze Sol's alias: refreshed caller hashes cannot make the derived wheel
    # serve as evidence of a direct build from the exact candidate tree.
    with pytest.raises(AssertionError, match="sealed_release_evidence_archive_provenance"):
        sealed_release_evidence(sealed_path, release_repo)
    forged = copy.deepcopy(sealed)
    forged["final_tree"] = candidate_tree
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    with pytest.raises(AssertionError, match="sealed_release_evidence_git_tree_mismatch"):
        sealed_release_evidence(sealed_path, release_repo)
    forged = copy.deepcopy(sealed)
    forged["candidate_paths"] = forged["candidate_paths"][1:]
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    with pytest.raises(AssertionError, match="sealed_release_evidence_candidate_inventory"):
        sealed_release_evidence(sealed_path, release_repo)
    forged = copy.deepcopy(sealed)
    forged["candidate_parent_blobs"]["phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_schema.py"] = None
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    with pytest.raises(AssertionError, match="sealed_release_evidence_candidate_inventory"):
        sealed_release_evidence(sealed_path, release_repo)
    forged = copy.deepcopy(sealed)
    toy_path = "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_schema.py"
    toy = release_repo / toy_path
    toy.write_text("CAPABILITY = 'candidate'\n", encoding="utf-8")
    git("add", toy_path)
    git("commit", "-m", "toy candidate")
    forged["candidate_commit"] = git("rev-parse", "HEAD")
    forged["candidate_tree"] = git("rev-parse", "HEAD^{tree}")
    forged["candidate_members"][toy_path] = hashlib.sha256(toy.read_bytes()).hexdigest()
    forged["final_commit"] = forged["candidate_commit"]
    forged["final_tree"] = forged["candidate_tree"]
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    with pytest.raises(AssertionError, match="sealed_release_evidence_candidate_inventory|sealed_release_evidence_candidate_toy"):
        sealed_release_evidence(sealed_path, release_repo)
    forged = copy.deepcopy(sealed)
    archive_member = "phase_loop_runtime/conformance/_contract/VENDOR.json"
    forged["archives"]["direct-wheel"]["members"][archive_member] = "0" * 64
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    with pytest.raises(AssertionError):
        sealed_release_evidence(sealed_path, release_repo)
    forged = copy.deepcopy(sealed)
    forged_path = Path(forged["archives"]["direct-wheel"]["path"])
    with zipfile.ZipFile(forged_path, "a") as archive:
        archive.writestr(
            "phase_loop_runtime/conformance/_contract/EXTRA.json", b"{}"
        )
    forged["archives"]["direct-wheel"]["sha256"] = hashlib.sha256(
        forged_path.read_bytes()
    ).hexdigest()
    forged["archives"]["direct-wheel"]["members"] = _normalized_archive_member_digests(
        forged_path
    )
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    with pytest.raises(AssertionError):
        sealed_release_evidence(sealed_path, release_repo)
    forged = copy.deepcopy(sealed)
    forged_path = Path(forged["archives"]["direct-wheel"]["path"])
    with zipfile.ZipFile(derived_wheel) as archive:
        vendor_bytes = archive.read(archive_member)
    contract_only_bytes = {
        archive_member: vendor_bytes,
        **{
            "phase_loop_runtime/conformance/_contract/" + relative: (
                FIXTURE_ROOT / relative
            ).read_bytes()
            for member in SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS
            if member != archive_member
            for relative in [
                member.removeprefix("phase_loop_runtime/conformance/_contract/")
            ]
        },
    }
    assert _member_digests(contract_only_bytes) == SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS
    with zipfile.ZipFile(forged_path, "w") as archive:
        for member, contents in contract_only_bytes.items():
            archive.writestr(member, contents)
    forged["archives"]["direct-wheel"]["sha256"] = hashlib.sha256(
        forged_path.read_bytes()
    ).hexdigest()
    forged["archives"]["direct-wheel"]["members"] = SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    # Freeze the reproduced bypass: a hand-built archive can carry the exact
    # 16 contract bytes and caller-refreshed hashes, but is not a candidate build.
    with pytest.raises(AssertionError, match="direct-wheel"):
        sealed_release_evidence(sealed_path, release_repo)


def test_mutation_definitions_are_frozen_but_not_executed_preimplementation(tmp_path) -> None:
    assert set(CONFORM_MUTATION_DEFINITIONS) == {
        "M-CONFORM-1-RESTORE-ALLOWLIST",
        "M-CONFORM-2-RAW-CONSTRUCTION-GUARD",
        "M-CONFORM-3-FINAL-SERIALIZER-GUARD",
        "M-CONFORM-4-MISSING-MIRROR",
        "M-CONFORM-4-EXTRA-MIRROR",
        "M-CONFORM-4-DUPLICATE-MIRROR",
        "M-CONFORM-4-FIXED-VENDOR-BYTE",
        "M-CONFORM-5-SUBMISSION-SCHEMA-BYTE",
        "M-CONFORM-5-VERDICT-SCHEMA-BYTE",
        "M-CONFORM-8-SWAP-SCHEMA",
        "M-CONFORM-8-DISPATCH-BYPASS",
    }
    for mutation in CONFORM_MUTATION_DEFINITIONS.values():
        assert mutation.source_path.startswith("phase-loop-runtime/src/")
        assert mutation.argv[1:4] == ("-m", "pytest", "-q")
        assert mutation.argv[-1] == mutation.expected_nodeid
        assert mutation.positive_control[-1] != mutation.expected_nodeid
        assert mutation.expected_observable
        source = mutation.complete_source()
        assert source.count(mutation.anchor) == 1
        mutated = mutation.apply(source)
        assert mutated != source
        assert mutation.replacement != mutation.anchor
        if mutation.parse_python:
            source_tree = ast.parse(source)
            mutated_tree = ast.parse(mutated)
            assert ast.dump(source_tree, include_attributes=False) != ast.dump(
                mutated_tree,
                include_attributes=False,
            )
        else:
            assert json.loads(source) != json.loads(mutated)
        with pytest.raises(AssertionError):
            mutation.apply(source.replace(mutation.anchor, "missing-anchor"))
        target_source = node_source_path(mutation.expected_nodeid).read_text(encoding="utf-8")
        assert mutation.expected_observable in target_source
    assert set(CONFORM_CANONICAL_CASES) == set(CONFORM_MIGRATED_EXISTING_NODE_IDS)
    assert len({case.role for case in CONFORM_CANONICAL_CASES.values()}) == 45
    for nodeid, case in CONFORM_CANONICAL_CASES.items():
        assert (nodeid in CONFORM_ACTIVATED_RED_ANCHORS) == (nodeid in CONFORM_ACTIVATED_RED_NODE_IDS)
        assert case.seam
        assert (case.mutation is None) == (case.expected_code is None)
        assert node_source_path(nodeid).exists()
    assert tuple(EVIDENCE_VERIFIER_INTERFACE) == ("chronology", "corpus", "package", "compatibility")
    assert set(EVIDENCE_VERIFIER_RECORD_IDS) == set(EVIDENCE_VERIFIER_INTERFACE)
    for mode, contract in EVIDENCE_VERIFIER_INTERFACE.items():
        assert contract["timing"] == ("B2-only" if mode == "compatibility" else "A2")
        assert contract["inputs"][:5] == (
            "candidate_commit",
            "candidate_tree",
            "head_commit",
            "head_tree",
            "module_path",
        )
        assert {"runner_manifest", "runner_log", "junit_xml"} <= set(contract["inputs"])
        assert contract["outputs"][:4] == (
            "mode",
            "candidate_commit",
            "head_commit",
            "module_path",
        )
        assert contract["outputs"][4:6] == (
            "recomputed_input_digest",
            "recomputed_evidence_digest",
        )
        assert "verified" not in contract["inputs"] + contract["outputs"]
        assert evidence_verifier_argv(mode)[-1] == mode
    # SL-0 deliberately has no verifier.  Once SL-1 supplies it, this test gives
    # it runner-owned Git, JUnit, log, mutation, and package facts; a self-authored
    # boolean or a digest-only summary is never an acceptable substitute.
    spec = importlib.util.find_spec(
        "phase_loop_runtime.conformance.outside_agent_conform_evidence"
    )
    if spec is not None:
        module = importlib.import_module(spec.name)
        assert module.EVIDENCE_VERIFIER_INTERFACE == EVIDENCE_VERIFIER_INTERFACE
        verifier = getattr(module, "verify_conform_evidence_records")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "runner-history"
            repository.mkdir()

            def git(*argv: str) -> str:
                completed = subprocess.run(["git", *argv], cwd=repository, capture_output=True, text=True, check=False)
                assert completed.returncode == 0, completed.stdout + completed.stderr
                return completed.stdout.strip()

            git("init")
            git("config", "user.email", "conform@example.test")
            git("config", "user.name", "CONFORM runner")
            runner_parent = sealed_release_parent_bytes()
            runner_candidate = sealed_release_candidate_bytes()
            for path, contents in runner_parent.items():
                if contents is None:
                    continue
                materialized = repository / path
                materialized.parent.mkdir(parents=True, exist_ok=True)
                materialized.write_bytes(contents)
            git("add", ".")
            git("commit", "-m", "parent")
            parent = git("rev-parse", "HEAD")
            parent_tree = git("rev-parse", "HEAD^{tree}")
            for path, contents in runner_candidate.items():
                materialized = repository / path
                materialized.parent.mkdir(parents=True, exist_ok=True)
                materialized.write_bytes(contents)
            git("add", ".")
            git("commit", "-m", "full candidate")
            candidate = git("rev-parse", "HEAD")
            candidate_tree = git("rev-parse", "HEAD^{tree}")
            facts = {
                "owner": "phase-loop-runner", "candidate_commit": candidate, "candidate_tree": candidate_tree,
                "head_commit": candidate, "head_tree": candidate_tree, "parent_commit": parent, "parent_tree": parent_tree,
                "module_path": "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_schema.py",
                "changed_paths": list(SEALED_RELEASE_CANDIDATE_PATHS),
                "argv": ["python3", "-m", "pytest", "-q", "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition"],
                "mutations": [{"id": "M-CONFORM-8-SWAP-SCHEMA"}],
            }

            def records_for(mode: str) -> tuple[list[dict[str, object]], dict[str, Path]]:
                mode_root = root / mode
                mode_root.mkdir()
                mode_log = mode_root / "runner.log"
                mode_log.write_text(f"runner-owned:{mode}\n", encoding="utf-8")
                mode_junit = mode_root / "controls.junit.xml"
                element_tree.ElementTree(
                    element_tree.fromstring(
                        f'<testsuite name="{mode}" tests="2" failures="1">'
                        f'<testcase name="positive:{mode}"/>'
                        '<testcase name="mutation:M-CONFORM-8-SWAP-SCHEMA"><failure/>'
                        "</testcase></testsuite>"
                    )
                ).write(mode_junit, encoding="utf-8", xml_declaration=True)
                mode_archives: dict[str, Path] = {}
                for archive_name, suffix in (
                    ("direct-wheel", ".whl"),
                    ("direct-sdist", ".tar.gz"),
                    ("sdist-derived-wheel", ".whl"),
                ):
                    archive_path = mode_root / f"{archive_name}{suffix}"
                    if suffix == ".whl":
                        with zipfile.ZipFile(archive_path, "w") as archive:
                            archive.writestr(
                                "phase_loop_runtime/conformance/_contract/VENDOR.json", "{}"
                            )
                            archive.writestr("mode-control.txt", mode)
                    else:
                        import io

                        with tarfile.open(archive_path, "w:gz") as archive:
                            for member_name, contents in (
                                (
                                    "phase-loop-runtime/src/phase_loop_runtime/"
                                    "conformance/_contract/VENDOR.json",
                                    b"{}",
                                ),
                                ("phase-loop-runtime/src/mode-control.txt", mode.encode()),
                            ):
                                member = tarfile.TarInfo(member_name)
                                member.size = len(contents)
                                archive.addfile(member, io.BytesIO(contents))
                    mode_archives[archive_name] = archive_path
                def write_mode_fact(name: str, payload: dict[str, object]) -> dict[str, str]:
                    fact_path = mode_root / f"{name}.json"
                    fact_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
                    return {
                        "path": str(fact_path),
                        "sha256": hashlib.sha256(fact_path.read_bytes()).hexdigest(),
                    }

                mode_exclusive_facts: dict[str, dict[str, object]] = {
                    "chronology": {
                        "chronology": {
                            "parent_commit": parent,
                            "parent_tree": parent_tree,
                            "candidate_commit": candidate,
                            "candidate_tree": candidate_tree,
                        }
                    },
                    "corpus": {
                        "fixture_manifest": write_mode_fact(
                            "fixture-manifest",
                            {
                                "fixture_root": "outside_agent_contract_v0_2_1",
                                "manifest_sha256": hashlib.sha256(
                                    (FIXTURE_ROOT / "test-vectors/outside-agent/manifest.json").read_bytes()
                                ).hexdigest(),
                            },
                        )
                    },
                    "package": {
                        "direct_wheel": {
                            "path": str(mode_archives["direct-wheel"]),
                            "sha256": hashlib.sha256(
                                mode_archives["direct-wheel"].read_bytes()
                            ).hexdigest(),
                        },
                        "direct_sdist": {
                            "path": str(mode_archives["direct-sdist"]),
                            "sha256": hashlib.sha256(
                                mode_archives["direct-sdist"].read_bytes()
                            ).hexdigest(),
                        },
                        "sdist_derived_wheel": {
                            "path": str(mode_archives["sdist-derived-wheel"]),
                            "sha256": hashlib.sha256(
                                mode_archives["sdist-derived-wheel"].read_bytes()
                            ).hexdigest(),
                        },
                    },
                    "compatibility": {
                        "ec_matrix": write_mode_fact(
                            "ec-matrix",
                            {"candidate_tree": candidate_tree, "matrix": "ec-v0.2.1"},
                        ),
                        "installed_package": write_mode_fact(
                            "installed-package",
                            {"candidate_commit": candidate, "package": "phase-loop-runtime"},
                        ),
                    },
                }
                mode_facts = copy.deepcopy(facts)
                mode_facts.update(
                    {
                        "runner_manifest": write_mode_fact(
                            "runner-manifest",
                            {
                                "owner": "phase-loop-runner",
                                "evidence_mode": mode,
                                "candidate_commit": candidate,
                                "candidate_tree": candidate_tree,
                            },
                        ),
                        "runner_log": {
                            "path": str(mode_log),
                            "sha256": hashlib.sha256(mode_log.read_bytes()).hexdigest(),
                        },
                        "junit_xml": {
                            "path": str(mode_junit),
                            "sha256": hashlib.sha256(mode_junit.read_bytes()).hexdigest(),
                        },
                        "runner_log_path": str(mode_log),
                        "runner_log_sha256": hashlib.sha256(mode_log.read_bytes()).hexdigest(),
                        "junit_path": str(mode_junit),
                        "junit_sha256": hashlib.sha256(mode_junit.read_bytes()).hexdigest(),
                        "archives": {
                            name: {
                                "path": str(path),
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            }
                            for name, path in mode_archives.items()
                        },
                        "evidence_mode": mode,
                        **mode_exclusive_facts[mode],
                    }
                )
                mode_manifest = mode_root / "runner-owned-manifest.json"
                mode_manifest.write_text(json.dumps(mode_facts, sort_keys=True), encoding="utf-8")
                digest = hashlib.sha256(mode_manifest.read_bytes()).hexdigest()
                records = [
                    {
                        "record_id": record_id,
                        "ordinal": ordinal,
                        "artifact_path": str(mode_manifest),
                        "artifact_sha256": digest,
                        "raw_log_path": str(mode_log),
                        "raw_log_sha256": hashlib.sha256(mode_log.read_bytes()).hexdigest(),
                        "evidence": {
                            "owner": "phase-loop-runner",
                            "candidate_commit": candidate,
                            "candidate_tree": candidate_tree,
                        },
                    }
                    for ordinal, record_id in enumerate(EVIDENCE_VERIFIER_RECORD_IDS[mode])
                ]
                return records, {"log": mode_log, "junit": mode_junit, **mode_archives}

            def expected_digests(records: list[dict[str, object]]) -> tuple[str, str]:
                mode_facts = json.loads(Path(records[0]["artifact_path"]).read_text(encoding="utf-8"))
                archive_bytes = {
                    name: hashlib.sha256(Path(details["path"]).read_bytes()).hexdigest()
                    for name, details in mode_facts["archives"].items()
                }
                input_facts = {
                    name: mode_facts[name]
                    for name in EVIDENCE_VERIFIER_INTERFACE[mode]["inputs"]
                }
                input_facts["manifest"] = hashlib.sha256(
                    Path(records[0]["artifact_path"]).read_bytes()
                ).hexdigest()
                input_facts["archive_bytes"] = archive_bytes
                junit_root = element_tree.parse(mode_facts["junit_path"]).getroot()
                outcome_facts = {
                    "junit": {
                        "tests": int(junit_root.attrib["tests"]),
                        "failures": int(junit_root.attrib["failures"]),
                        "cases": [
                            {
                                "name": case.attrib["name"],
                                "outcome": "failed" if case.find("failure") is not None else "passed",
                            }
                            for case in junit_root.findall("testcase")
                        ],
                    },
                    "archive_members": {
                        name: _normalized_archive_member_digests(Path(details["path"]))
                        for name, details in mode_facts["archives"].items()
                    },
                    "mutations": [
                        {
                            "id": case.attrib["name"].removeprefix("mutation:"),
                            "outcome": "killed" if case.find("failure") is not None else "survived",
                        }
                        for case in junit_root.findall("testcase")
                        if case.attrib["name"].startswith("mutation:")
                    ],
                }
                encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
                return hashlib.sha256(encode(input_facts)).hexdigest(), hashlib.sha256(encode(outcome_facts)).hexdigest()

            def refresh_mode_records(
                records: list[dict[str, object]], artifacts: dict[str, Path]
            ) -> None:
                manifest_path = Path(records[0]["artifact_path"])
                mode_facts = json.loads(manifest_path.read_text(encoding="utf-8"))
                mode_facts["runner_log_sha256"] = hashlib.sha256(
                    artifacts["log"].read_bytes()
                ).hexdigest()
                mode_facts["runner_log"]["sha256"] = mode_facts["runner_log_sha256"]
                mode_facts["junit_sha256"] = hashlib.sha256(
                    artifacts["junit"].read_bytes()
                ).hexdigest()
                mode_facts["junit_xml"]["sha256"] = mode_facts["junit_sha256"]
                for name in ("direct-wheel", "direct-sdist", "sdist-derived-wheel"):
                    mode_facts["archives"][name]["sha256"] = hashlib.sha256(
                        artifacts[name].read_bytes()
                    ).hexdigest()
                package_facts = {
                    "direct-wheel": "direct_wheel",
                    "direct-sdist": "direct_sdist",
                    "sdist-derived-wheel": "sdist_derived_wheel",
                }
                for archive_name, fact_name in package_facts.items():
                    if fact_name in mode_facts:
                        mode_facts[fact_name]["sha256"] = mode_facts["archives"][archive_name]["sha256"]
                manifest_path.write_text(json.dumps(mode_facts, sort_keys=True), encoding="utf-8")
                artifact_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                raw_log_digest = hashlib.sha256(artifacts["log"].read_bytes()).hexdigest()
                for record in records:
                    record["artifact_sha256"] = artifact_digest
                    record["raw_log_sha256"] = raw_log_digest

            for mode in EVIDENCE_VERIFIER_INTERFACE:
                mode_records, artifacts = records_for(mode)
                expected_input, expected_evidence = expected_digests(mode_records)
                verified = verifier(mode, mode_records)
                assert set(verified) == set(EVIDENCE_VERIFIER_INTERFACE[mode]["outputs"])
                assert verified["mode"] == mode
                assert verified["candidate_commit"] == candidate
                assert verified["head_commit"] == candidate
                assert verified["module_path"] == facts["module_path"]
                assert verified["recomputed_input_digest"] == expected_input
                assert verified["recomputed_evidence_digest"] == expected_evidence
                assert isinstance(verified["evidence"], dict)
                assert "raw_log" not in json.dumps(verified["evidence"], sort_keys=True)
                records_path = root / f"{mode}-records.json"
                records_path.write_text(json.dumps(mode_records, sort_keys=True), encoding="utf-8")
                completed = subprocess.run(evidence_verifier_argv(mode, records_path), capture_output=True, text=True, check=False)
                assert completed.returncode == 0, completed.stdout + completed.stderr
                assert json.loads(completed.stdout) == verified

                def assert_production_cli_rejects(records: list[dict[str, object]]) -> None:
                    records_path.write_text(json.dumps(records, sort_keys=True), encoding="utf-8")
                    rejected = subprocess.run(
                        evidence_verifier_argv(mode, records_path),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    assert rejected.returncode != 0, rejected.stdout + rejected.stderr

                mode_facts = json.loads(
                    Path(mode_records[0]["artifact_path"]).read_text(encoding="utf-8")
                )
                assert mode_facts["evidence_mode"] == mode
                assert set(EVIDENCE_MODE_EXCLUSIVE_INPUTS[mode]) <= set(mode_facts)
                for input_name in EVIDENCE_MODE_EXCLUSIVE_INPUTS[mode]:
                    missing_facts = copy.deepcopy(mode_facts)
                    missing_facts.pop(input_name)
                    Path(mode_records[0]["artifact_path"]).write_text(
                        json.dumps(missing_facts, sort_keys=True), encoding="utf-8"
                    )
                    refresh_mode_records(mode_records, artifacts)
                    with pytest.raises((ValueError, AssertionError)):
                        verifier(mode, mode_records)
                    assert_production_cli_rejects(mode_records)
                Path(mode_records[0]["artifact_path"]).write_text(
                    json.dumps(mode_facts, sort_keys=True), encoding="utf-8"
                )
                refresh_mode_records(mode_records, artifacts)
                for other_mode, other_inputs in EVIDENCE_MODE_EXCLUSIVE_INPUTS.items():
                    if other_mode == mode:
                        continue
                    cross_mode_facts = copy.deepcopy(mode_facts)
                    for input_name in EVIDENCE_MODE_EXCLUSIVE_INPUTS[mode]:
                        cross_mode_facts.pop(input_name)
                    cross_mode_facts.update(
                        {
                            input_name: {"cross_mode": other_mode}
                            for input_name in other_inputs
                        }
                    )
                    Path(mode_records[0]["artifact_path"]).write_text(
                        json.dumps(cross_mode_facts, sort_keys=True), encoding="utf-8"
                    )
                    refresh_mode_records(mode_records, artifacts)
                    with pytest.raises((ValueError, AssertionError)):
                        verifier(mode, mode_records)
                    assert_production_cli_rejects(mode_records)
                Path(mode_records[0]["artifact_path"]).write_text(
                    json.dumps(mode_facts, sort_keys=True), encoding="utf-8"
                )
                refresh_mode_records(mode_records, artifacts)

                for other_mode in EVIDENCE_VERIFIER_INTERFACE:
                    if other_mode == mode:
                        continue
                    other_records, _ = records_for(other_mode)
                    mode_agnostic_records = copy.deepcopy(other_records)
                    for ordinal, record in enumerate(mode_agnostic_records):
                        record["record_id"] = EVIDENCE_VERIFIER_RECORD_IDS[mode][ordinal]
                        record["ordinal"] = ordinal
                    with pytest.raises((ValueError, AssertionError)):
                        verifier(mode, mode_agnostic_records)
                    # Re-labelling record IDs cannot turn a corpus, package, or
                    # compatibility fact payload into this mode.  The CLI must
                    # inspect the semantic evidence_mode and literal facts too.
                    assert_production_cli_rejects(mode_agnostic_records)

                if len(EVIDENCE_MODE_EXCLUSIVE_INPUTS[mode]) > 1:
                    same_label_facts = copy.deepcopy(mode_facts)
                    names = EVIDENCE_MODE_EXCLUSIVE_INPUTS[mode]
                    swapped = [same_label_facts[name] for name in names]
                    for name, value in zip(names, reversed(swapped), strict=True):
                        same_label_facts[name] = value
                    Path(mode_records[0]["artifact_path"]).write_text(
                        json.dumps(same_label_facts, sort_keys=True), encoding="utf-8"
                    )
                    refresh_mode_records(mode_records, artifacts)
                    with pytest.raises((ValueError, AssertionError)):
                        verifier(mode, mode_records)
                    assert_production_cli_rejects(mode_records)
                    Path(mode_records[0]["artifact_path"]).write_text(
                        json.dumps(mode_facts, sort_keys=True), encoding="utf-8"
                    )
                    refresh_mode_records(mode_records, artifacts)

                original_log = artifacts["log"].read_bytes()
                original_junit = artifacts["junit"].read_bytes()
                original_wheel = artifacts["direct-wheel"].read_bytes()
                artifacts["log"].write_text("tampered-runner-owned-log\n", encoding="utf-8")
                with pytest.raises((ValueError, AssertionError)):
                    verifier(mode, mode_records)
                artifacts["log"].write_bytes(original_log)

                artifacts["junit"].write_text("<testsuite>", encoding="utf-8")
                with pytest.raises((ValueError, AssertionError)):
                    verifier(mode, mode_records)
                artifacts["junit"].write_bytes(original_junit)

                with zipfile.ZipFile(artifacts["direct-wheel"], "a") as archive:
                    archive.writestr("CONFORM-TAMPERED.txt", "not runner-sealed")
                refresh_mode_records(mode_records, artifacts)
                with pytest.raises((ValueError, AssertionError)):
                    verifier(mode, mode_records)
                artifacts["direct-wheel"].write_bytes(original_wheel)
                refresh_mode_records(mode_records, artifacts)

                element_tree.ElementTree(
                    element_tree.fromstring(
                        '<testsuite tests="2" failures="0"><testcase name="positive"/>'
                        '<testcase name="mutation:M-CONFORM-8-SWAP-SCHEMA"/>'
                        "</testsuite>"
                    )
                ).write(artifacts["junit"], encoding="utf-8", xml_declaration=True)
                refresh_mode_records(mode_records, artifacts)
                with pytest.raises((ValueError, AssertionError)):
                    verifier(mode, mode_records)
