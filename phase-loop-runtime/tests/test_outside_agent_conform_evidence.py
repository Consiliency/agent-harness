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
import textwrap
import xml.etree.ElementTree as element_tree
import zipfile
from pathlib import Path

import pytest

import _outside_agent_canonical as outside_agent_canonical

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
    EC_CONFORM_PROBES,
    EVIDENCE_VERIFIER_INTERFACE,
    EVIDENCE_VERIFIER_RECORD_IDS,
    EXPECTED_VENDOR_BYTES,
    FIXTURE_ROOT,
    LIVE_BLOCKER_CODE_BY_INVALID_CASE,
    REPO_ROOT,
    RUNNER_B2_EVIDENCE_ENV,
    SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS,
    SEALED_RELEASE_ARCHIVE_MEMBERS,
    SEALED_RELEASE_CANDIDATE_PARENT_BLOBS,
    SEALED_RELEASE_CANDIDATE_PATHS,
    SEALED_RELEASE_FINAL_PARENT_BLOBS,
    SEALED_RELEASE_FINAL_PATHS,
    assert_candidate_identity_only_document,
    assert_named_safety_mutations_rejected,
    assert_status_code_only_replacement_is_rejected,
    evidence_verifier_argv,
    find_non_enumerated_canonical_copies,
    fixture_paths,
    normalized_nodeid,
    runner_b2_evidence_enabled,
    route_verdict_entry,
    sealed_release_candidate_bytes,
    sealed_release_evidence,
    sealed_release_final_bytes,
    sealed_release_parent_bytes,
    submission_entries,
    _member_digests,
    _build_a2_package_evidence,
    _a2_package_evidence_sha256,
    _sealed_manifest_sha256,
    _normalized_archive_member_digests,
    node_source_path,
    vector_payload,
)


EVIDENCE_MODE_EXCLUSIVE_INPUTS = {
    "chronology": ("chronology",),
    "corpus": ("fixture_manifest",),
    "package": ("direct_wheel", "direct_sdist", "sdist_derived_wheel"),
    "compatibility": ("ec_matrix", "installed_package"),
}
EC_CONFORM_IDS = tuple(f"EC-CONFORM-{index}" for index in range(9))
EVIDENCE_SEMANTIC_OUTPUT_KEYS = {
    "bindings",
    "vendor",
    "chronology",
    "corpus",
    "package",
    "installed_package",
    "mode_specific",
}
PACKAGE_EXECUTION_VARIANTS = (
    "direct-wheel",
    "direct-sdist",
    "sdist-derived-wheel",
)
B1_ACCEPTED_DOCUMENT_COMMIT = "80d9a14c94785f81044d67b60e05d61242838a1b"
B1_ACCEPTED_DOCUMENT_PARENT = B1_ACCEPTED_DOCUMENT_COMMIT + "^"
B1_CANDIDATE_IDENTITY_PATHS = {
    "docs/releases/outside-agent-release-handoff.md",
    "specs/phase-plans-v7.md",
}
B1_REQUIRED_DOCUMENT_TERMS = {
    "CHANGELOG.md": (
        "outside-agent conformance runtime (oarelease)",
        "release handoff",
        "governed-pipeline pinning instructions",
        "maintainer-owned publish/tag/workflow-dispatch",
        "consiliency/spec@v0.2.1",
        "digest-enumerated",
        "0.5.0",
        "clean-room conform repository evidence",
    ),
    "docs/outside-agent-conformance.md": (
        "consiliency/spec@v0.2.1",
        "digest-enumerated",
        "test-only oracle",
        "source/mirror",
        "raw-byte",
        "no copied canonical",
        "not a production parser",
        "consiliency/spec remains",
    ),
    "docs/releases/outside-agent-release-handoff.md": (
        "phase-loop-runtime",
        "validator version",
        "governed_pipeline_validator",
        "outside-agent-preflight",
        "outside-agent-validate",
        "digest-enumerated",
        "direct-wheel",
        "sdist-derived-wheel",
        "maintainer",
        "not published",
        "not dispatched",
    ),
    "specs/phase-plans-v7.md": (
        "oacore-3",
        "oareal-2",
        "consiliency/spec@v0.2.1",
        "installed-package",
        "direct-wheel",
        "sdist-derived-wheel",
        "outside-agent-preflight",
        "outside-agent-validate",
        "three valid submissions",
        "route-verdict",
        "metadata_only",
        "not published",
        "not dispatched",
    ),
}


def _accepted_b1_document_addition(path: str) -> str:
    """Extract the accepted 80d9a14 documentation delta, never stale prose."""
    def document_at(revision: str) -> str:
        completed = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
        return completed.stdout.decode("utf-8")

    accepted_parent = document_at(B1_ACCEPTED_DOCUMENT_PARENT)
    accepted_document = document_at(B1_ACCEPTED_DOCUMENT_COMMIT)
    boundaries = {
        "CHANGELOG.md": (
            "### Outside-Agent Conformance Runtime (OARELEASE)",
            "### CI: run the frozen LEGIBLE files",
        ),
        "docs/outside-agent-conformance.md": ("## Consumer Mirror Policy", None),
        "docs/releases/outside-agent-release-handoff.md": (
            "## Sealed Implementation Evidence",
            "## Package Surface Inventory",
        ),
        "specs/phase-plans-v7.md": (
            "## CONFORM Final Disposition & Installed Behavior",
            None,
        ),
    }
    start, end = boundaries[path]
    assert start not in accepted_parent and start in accepted_document
    addition = accepted_document.split(start, 1)[1]
    if end is not None:
        assert end in addition
        addition = addition.split(end, 1)[0]
    return start + addition


def _transform_accepted_b1_addition(
    path: str,
    addition: str,
    *,
    candidate_commit: str,
    candidate_tree: str,
    a2_package_evidence: dict[str, object],
) -> str:
    """Replace only runner-only 80d9a14 values with candidate/A2 evidence."""
    archives = a2_package_evidence["archives"]
    a2_package_evidence_sha256 = a2_package_evidence[
        "a2_package_evidence_sha256"
    ]
    assert isinstance(archives, dict) and set(archives) == set(PACKAGE_EXECUTION_VARIANTS)
    assert isinstance(a2_package_evidence_sha256, str)
    if path == "docs/releases/outside-agent-release-handoff.md":
        original_identity_block = (
            "- candidate implementation commit: 6e333653a16de5f50c17e7649aa678898b6f0f48\n"
            "- candidate implementation tree: fe41dc8c31483b378c06155be6b07e8a091c8c8b\n"
            "- final implementation commit: 84a2095a56c20fe8aac198e60bc181709d31bb91\n"
            "- final implementation tree: 521c5a96c9ac8f60b6e8fa29cc3f0d35d5940980\n"
        )
        candidate_identity_block = (
            f"- candidate implementation commit: {candidate_commit}\n"
            f"- candidate implementation tree: {candidate_tree}\n"
        )
        assert original_identity_block in addition
        assert original_identity_block != candidate_identity_block
        addition = addition.replace(original_identity_block, candidate_identity_block)
        original_evidence_line = (
            "- sealed package evidence sha256: "
            "0740416fd7b434cd78420ec9321dbb7e5b59a743b3f12a8d094ad5ebe84e9c20"
        )
        candidate_evidence_line = (
            "- pre-doc A2 package evidence sha256: " + a2_package_evidence_sha256
        )
        assert addition.count(original_evidence_line) == 1
        assert original_evidence_line != candidate_evidence_line
        addition = addition.replace(original_evidence_line, candidate_evidence_line)
    elif path == "specs/phase-plans-v7.md":
        original_identity_block = (
            "- candidate implementation commit: `6e333653a16de5f50c17e7649aa678898b6f0f48`\n"
            "- candidate implementation tree: `fe41dc8c31483b378c06155be6b07e8a091c8c8b`\n"
            "- final implementation commit: `84a2095a56c20fe8aac198e60bc181709d31bb91`\n"
            "- final implementation tree: `521c5a96c9ac8f60b6e8fa29cc3f0d35d5940980`\n"
        )
        candidate_identity_block = (
            f"- candidate implementation commit: `{candidate_commit}`\n"
            f"- candidate implementation tree: `{candidate_tree}`\n"
        )
        assert original_identity_block in addition
        assert original_identity_block != candidate_identity_block
        addition = addition.replace(original_identity_block, candidate_identity_block)
    if path in B1_CANDIDATE_IDENTITY_PATHS:
        for label in PACKAGE_EXECUTION_VARIANTS:
            archive = archives[label]
            assert isinstance(archive, dict)
            archive_sha256 = archive["sha256"]
            assert isinstance(archive_sha256, str) and len(archive_sha256) == 64
            old_sha256 = {
                "direct-wheel": "17168b69109ecd032ab1c1230509b0c72c130d04fa4bdd79caaa913a0cc5d2cc",
                "direct-sdist": "c7e409c132e9a35965c0c80fc192c40c9646188183f18c8102e97445ad9f2acb",
                "sdist-derived-wheel": "17168b69109ecd032ab1c1230509b0c72c130d04fa4bdd79caaa913a0cc5d2cc",
            }[label]
            original_lines = (
                f"- {label} sha256: {old_sha256}",
                f"- `{label}` sha256: `{old_sha256}`",
            )
            original_line = next(
                (line for line in original_lines if line in addition), None
            )
            assert original_line is not None
            assert addition.count(original_line) == 1
            candidate_line = original_line.replace(old_sha256, archive_sha256)
            addition = addition.replace(original_line, candidate_line)
            assert candidate_line in addition
    return addition


def _render_b1_document_bytes(
    path: str,
    candidate_document: bytes,
    *,
    candidate_commit: str,
    candidate_tree: str,
    sealed_package_evidence: dict[str, object],
) -> bytes:
    """Replay the accepted B1 documentation content from candidate/A2 inputs."""
    assert path in SEALED_RELEASE_FINAL_PATHS
    assert candidate_document.endswith(b"\n") and b"\r" not in candidate_document
    candidate_text = candidate_document.decode("utf-8")
    assert set(sealed_package_evidence) == {
        "candidate_commit",
        "candidate_tree",
        "candidate_members",
        "archives",
        "a2_package_evidence_sha256",
    }
    assert sealed_package_evidence == _build_a2_package_evidence(
        candidate_commit=candidate_commit,
        candidate_tree=candidate_tree,
        candidate_members=sealed_package_evidence["candidate_members"],
        archives=sealed_package_evidence["archives"],
    )
    addition = _transform_accepted_b1_addition(
        path,
        _accepted_b1_document_addition(path),
        candidate_commit=candidate_commit,
        candidate_tree=candidate_tree,
        a2_package_evidence=sealed_package_evidence,
    ).rstrip("\n")
    if path == "CHANGELOG.md":
        anchor = "## [Unreleased]\n\n"
        assert anchor in candidate_text
        assert "### Clean-room CONFORM repository evidence" in candidate_text
        rendered = candidate_text.replace(anchor, anchor + addition + "\n\n", 1)
    elif path == "docs/releases/outside-agent-release-handoff.md":
        anchor = "## Package Surface Inventory\n"
        assert anchor in candidate_text
        rendered = candidate_text.replace(anchor, addition + "\n\n" + anchor, 1)
    else:
        rendered = candidate_text.rstrip("\n") + "\n\n" + addition + "\n"
    lowered = rendered.lower()
    assert all(term in lowered for term in B1_REQUIRED_DOCUMENT_TERMS[path])
    return rendered.rstrip("\n").encode("utf-8") + b"\n"


B2_COMMAND = (
    "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest "
    "phase-loop-runtime/tests -q -k outside_agent"
)
SUBMISSION_CLI_EXIT_BY_CASE = {
    "positive-work-request": 0,
    "positive-implementation-submission": 0,
    "positive-ambiguity-report": 0,
    "negative-raw-payload": 2,
    "negative-missing-digest": 2,
    "negative-source-bundle-mismatch": 6,
    "negative-unknown-producer-identity-posture": 2,
    "negative-path-traversal": 2,
    "negative-empty-evidence-refs": 2,
    "negative-git-object-id-length": 2,
}
CONFORM_IMMUTABLE_LIFECYCLE_PATHS = (
    "phase-loop-runtime/tests/_outside_agent_canonical.py",
    "phase-loop-runtime/tests/conftest.py",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/PROVENANCE.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/consiliency_spec/outside_agent_router.py",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/schemas/outside-agent-route-verdict.schema.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/schemas/outside-agent-submission.schema.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/invalid-empty-evidence-refs.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/invalid-git-object-id-length.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/invalid-missing-digest.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/invalid-path-traversal.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/invalid-raw-payload.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/invalid-source-bundle-mismatch.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/invalid-unknown-producer-identity-posture.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/invalid-unsupported-verdict.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/manifest.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/valid-ambiguity-report.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/valid-implementation-submission.json",
    "phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/valid-work-request.json",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py",
)


def _expected_execution_environment(execution_root: Path | str) -> dict[str, str]:
    execution_root = Path(execution_root)
    environment = {
        "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(execution_root / "phase-loop-runtime" / "src")
        + os.pathsep
        + str(execution_root / "phase-loop-runtime" / "tests"),
    }
    if runner_b2_evidence_enabled():
        environment[RUNNER_B2_EVIDENCE_ENV] = "1"
    return environment


def _source_execution_environment() -> dict[str, str]:
    return _expected_execution_environment(REPO_ROOT)


def _run_bound_child(
    command: list[str], *, input_text: str, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Execute without the mockable ``subprocess.run`` seam used by the SUT."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate(input_text)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _run_bound_child_bytes(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env={"PATH": os.environ.get("PATH", "")},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _extract_tar_archive(archive: tarfile.TarFile, destination: Path) -> None:
    """Apply the data-filter invariants on every supported Python version."""
    members = archive.getmembers()
    assert all(
        not Path(member.name).is_absolute()
        and ".." not in Path(member.name).parts
        and (member.isfile() or member.isdir())
        for member in members
    )
    archive.extractall(destination)


def _repo_candidate_identity() -> dict[str, object]:
    head = _run_bound_child(
        ["git", "rev-parse", "HEAD"],
        input_text="",
        cwd=REPO_ROOT,
        environment={"PATH": os.environ.get("PATH", "")},
    )
    if head.returncode != 0:
        return {
            "candidate_oid": None,
            "candidate_tree": None,
            "candidate_archive_sha256": None,
            "candidate_clean": False,
        }
    oid = head.stdout.strip()
    assert len(oid) == 40 and all(character in "0123456789abcdef" for character in oid)
    tree = _run_bound_child(
        ["git", "rev-parse", "HEAD^{tree}"],
        input_text="",
        cwd=REPO_ROOT,
        environment={"PATH": os.environ.get("PATH", "")},
    )
    status = _run_bound_child(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        input_text="",
        cwd=REPO_ROOT,
        environment={"PATH": os.environ.get("PATH", "")},
    )
    archive = _run_bound_child_bytes(
        ["git", "archive", "--format=tar", oid, "phase-loop-runtime"],
        cwd=REPO_ROOT,
    )
    assert tree.returncode == status.returncode == archive.returncode == 0
    tree_oid = tree.stdout.strip()
    assert len(tree_oid) == 40 and all(
        character in "0123456789abcdef" for character in tree_oid
    )
    return {
        "candidate_oid": oid,
        "candidate_tree": tree_oid,
        "candidate_archive_sha256": hashlib.sha256(archive.stdout).hexdigest(),
        "candidate_clean": status.stdout == "",
    }


def _b2_compatibility_evidence_due() -> bool:
    if not runner_b2_evidence_enabled():
        return False
    changed = []
    for path, parent_blob in SEALED_RELEASE_FINAL_PARENT_BLOBS.items():
        result = _run_bound_child(
            ["git", "rev-parse", f"HEAD:{path}"],
            input_text="",
            cwd=REPO_ROOT,
            environment={"PATH": os.environ.get("PATH", "")},
        )
        if result.returncode != 0:
            return False
        changed.append(result.stdout.strip() != parent_blob)
    assert not any(changed) or all(changed), (
        "CONFORM_RED::partial_sl2_compatibility_transition"
    )
    return all(changed)


def _candidate_mutation_source(definition) -> str:
    source_path = REPO_ROOT / definition.source_path
    assert source_path.is_file(), definition.source_path
    source = source_path.read_text(encoding="utf-8")
    assert source.count(definition.anchor) == 1, definition.source_path
    return source


_CAPTURED_OBSERVABLE_RUNNER = (
    "import json, sys\n"
    "result = json.load(sys.stdin)\n"
    "print(json.dumps(result, sort_keys=True))\n"
    "raise SystemExit(result['exit_code'])\n"
)
_EC_PROBE_NODEIDS = {
    "EC-CONFORM-0": (
        "test_outside_agent_conform_evidence.py::test_frozen_inventory_counts_and_set_equations",
        "test_outside_agent_conform_evidence.py::test_frozen_command_literals_and_selector_partition",
    ),
    "EC-CONFORM-1": (
        "test_outside_agent_canonical_corpus.py::test_canonical_manifest_partition_and_oracle_rows",
        "test_outside_agent_canonical_corpus.py::test_canonical_submission_api_accepts_three_valid_rows",
        "test_outside_agent_canonical_corpus.py::test_canonical_submission_cli_accepts_three_valid_rows",
    ),
    "EC-CONFORM-2": (
        "test_outside_agent_redaction_separation.py::test_closed_redaction_projection_inventory_is_exhaustive",
    ),
    "EC-CONFORM-3": (
        "test_outside_agent_redaction_separation.py::test_redaction_mutation_definitions_are_independent",
        "test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
        "test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
    ),
    "EC-CONFORM-4": (
        "test_outside_agent_canonical_corpus.py::test_canonical_fixture_provenance_and_digest_inventory",
        "test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
        "test_outside_agent_conform_evidence.py::test_planted_non_enumerated_copy_reports_its_exact_path",
    ),
    "EC-CONFORM-5": (
        "test_outside_agent_contract_imports.py::test_submission_schema_byte_change_with_manifest_hash_held_fails_closed",
        "test_outside_agent_contract_imports.py::test_verdict_schema_byte_change_with_manifest_hash_held_fails_closed",
    ),
    "EC-CONFORM-6": (
        "test_outside_agent_release_surface.py::test_v7_disposition_records_merged_contract_and_final_installed_behavior",
    ),
    "EC-CONFORM-7": (
        "test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors",
        "test_outside_agent_contract_drift.py::test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror",
        "test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
    ),
    "EC-CONFORM-8": (
        "test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes",
        "test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition",
        "test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli",
    ),
}
_MUTATION_OUTPUT_NORMALIZER_SOURCE = textwrap.dedent(
    """
    import re

    def normalize_mutation_output(text):
        text = re.sub(r"object at 0x[0-9a-fA-F]+", "object at <address>", text)
        text = re.sub(r"pytest-[0-9]+", "pytest-<run>", text)
        return re.sub(r" in [0-9.]+s(?: \\([0-9:]+\\))?", " in <duration>", text)

    def normalize_junit_tree(root):
        for node in root.iter():
            node.attrib.pop("time", None)
            node.attrib.pop("timestamp", None)
            if node.text:
                node.text = normalize_mutation_output(node.text)
            if node.tail:
                node.tail = normalize_mutation_output(node.tail)
    """
)
_MUTATION_PROBE_RUNNER = _MUTATION_OUTPUT_NORMALIZER_SOURCE + textwrap.dedent(
    """
    import hashlib, io, json, os, shutil, subprocess, sys, tarfile
    from pathlib import Path

    def extract_tar_archive(archive, destination):
        members = archive.getmembers()
        assert all(
            not Path(member.name).is_absolute()
            and ".." not in Path(member.name).parts
            and (member.isfile() or member.isdir())
            for member in members
        )
        archive.extractall(destination)

    payload = json.load(sys.stdin)
    repo_root = Path(payload["repo_root"]).resolve()
    execution_root = Path(payload["execution_root"]).resolve()
    sys.path.insert(0, str(repo_root / "phase-loop-runtime" / "tests"))
    from _outside_agent_canonical import CONFORM_MUTATION_DEFINITIONS

    mutation = CONFORM_MUTATION_DEFINITIONS[payload["mutation_id"]]
    assert (mutation.source_path, mutation.expected_nodeid, mutation.expected_anchor) == (
        payload["source_path"], payload["expected_nodeid"], payload["expected_anchor"]
    )
    if execution_root.exists():
        shutil.rmtree(execution_root)
    runtime = execution_root / "phase-loop-runtime"
    candidate_result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=False
    )
    candidate_oid = candidate_result.stdout.strip() if candidate_result.returncode == 0 else None
    candidate_tree = None
    candidate_archive_sha256 = None
    candidate_clean = False
    if candidate_oid is not None:
        assert len(candidate_oid) == 40 and all(character in "0123456789abcdef" for character in candidate_oid)
        tree_result = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=repo_root, capture_output=True, text=True, check=False
        )
        status_result = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=repo_root, capture_output=True, text=True, check=False,
        )
        archive_result = subprocess.run(
            ["git", "archive", "--format=tar", candidate_oid, "phase-loop-runtime"],
            cwd=repo_root, capture_output=True, check=False,
        )
        assert tree_result.returncode == status_result.returncode == archive_result.returncode == 0
        candidate_tree = tree_result.stdout.strip()
        assert len(candidate_tree) == 40 and all(character in "0123456789abcdef" for character in candidate_tree)
        candidate_archive_sha256 = hashlib.sha256(archive_result.stdout).hexdigest()
        candidate_clean = status_result.stdout == ""
        if candidate_clean:
            with tarfile.open(fileobj=io.BytesIO(archive_result.stdout), mode="r:") as archive:
                extract_tar_archive(archive, execution_root)
    if not candidate_clean:
        shutil.copytree(repo_root / "phase-loop-runtime", runtime, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    source_path = execution_root / mutation.source_path
    assert source_path.is_file(), mutation.source_path
    source = source_path.read_text(encoding="utf-8")
    assert source.count(mutation.anchor) == 1, mutation.source_path
    mutant = mutation.apply(source)
    environment = {
        "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(runtime / "src") + os.pathsep + str(runtime / "tests"),
    }
    if os.environ.get("PHASE_LOOP_CONFORM_B2_EVIDENCE") == "1":
        environment["PHASE_LOOP_CONFORM_B2_EVIDENCE"] = "1"
    def execute(argv):
        completed = subprocess.run(argv, cwd=execution_root, capture_output=True, text=True, check=False, env=environment)
        if completed.returncode != 0:
            classification = "failed"
        elif "skipped" in completed.stdout.lower():
            classification = "skipped"
        elif "passed" in completed.stdout.lower():
            classification = "passed"
        else:
            classification = "inconclusive"
        return {
            "argv": argv,
            "cwd": str(execution_root),
            "environment": environment,
            "exit_code": completed.returncode,
            "stdout_sha256": hashlib.sha256(normalize_mutation_output(completed.stdout).encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(normalize_mutation_output(completed.stderr).encode("utf-8")).hexdigest(),
            "classification": classification,
        }, completed

    baseline, baseline_raw = execute(list(mutation.argv))
    positive_control, positive_raw = execute(list(mutation.positive_control))
    companion_baseline = None
    if mutation.companion_argv is not None:
        companion_baseline, _ = execute(list(mutation.companion_argv))
    source_path.write_text(mutant, encoding="utf-8")
    mutant_result, mutant_raw = execute(list(mutation.argv))
    combined = mutant_raw.stdout + mutant_raw.stderr
    nodeid_matched = (
        mutation.expected_nodeid in combined
        or mutation.expected_nodeid.rsplit("::", 1)[-1] in combined
    )
    anchor_matched = mutation.expected_anchor in combined
    companion = None
    companion_killed = True
    if mutation.companion_argv is not None:
        companion_mutant, companion_raw = execute(list(mutation.companion_argv))
        companion_combined = companion_raw.stdout + companion_raw.stderr
        companion_nodeid_matched = (
            mutation.companion_expected_nodeid in companion_combined
            or mutation.companion_expected_nodeid.rsplit("::", 1)[-1]
            in companion_combined
        )
        companion_anchor_matched = (
            mutation.companion_expected_anchor in companion_combined
        )
        companion_killed = (
            companion_baseline["classification"] == "passed"
            and companion_mutant["classification"] == "failed"
            and companion_nodeid_matched
            and companion_anchor_matched
        )
        companion = {
            "argv": list(mutation.companion_argv),
            "expected_nodeid": mutation.companion_expected_nodeid,
            "expected_anchor": mutation.companion_expected_anchor,
            "nodeid_matched": companion_nodeid_matched,
            "anchor_matched": companion_anchor_matched,
            "baseline": companion_baseline,
            "mutant": companion_mutant,
        }
    killed = (
        baseline["classification"] == "passed"
        and positive_control["classification"] == "passed"
        and mutant_result["classification"] == "failed"
        and nodeid_matched
        and anchor_matched
        and companion_killed
    )
    killed = killed and candidate_clean
    observable = {
        "kind": "mutation-execution",
        "classification": "killed" if killed else "incomplete",
        "candidate_oid": candidate_oid,
        "candidate_tree": candidate_tree,
        "candidate_archive_sha256": candidate_archive_sha256,
        "candidate_clean": candidate_clean,
        "candidate_sha256": (
            hashlib.sha256((candidate_oid + "\\n").encode("utf-8")).hexdigest()
            if candidate_oid is not None
            else None
        ),
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "mutant_sha256": hashlib.sha256(mutant.encode("utf-8")).hexdigest(),
        "nodeid_matched": nodeid_matched,
        "anchor_matched": anchor_matched,
        "companion": companion,
        "baseline": baseline,
        "positive_control": positive_control,
        "mutant": mutant_result,
    }
    status = "blocked" if killed else "incomplete"
    print(json.dumps({"status": status, "anchor": mutation.expected_anchor, "observable": observable}, sort_keys=True))
    raise SystemExit(1)
    """
)
_EC_PROBE_RUNNER = _MUTATION_OUTPUT_NORMALIZER_SOURCE + textwrap.dedent(
    """
    import hashlib, json, os, re, subprocess, sys
    from pathlib import Path
    from xml.etree import ElementTree as element_tree

    payload = json.load(sys.stdin)
    probes = json.loads(payload["probe_nodes"])
    ec_id = payload["id"]
    assert ec_id == f"EC-CONFORM-{payload['ordinal']}" and 0 <= payload["ordinal"] <= 8
    nodeids = probes[ec_id]
    assert isinstance(nodeids, list) and nodeids
    repo_root = Path(payload["repo_root"]).resolve()
    execution_root = Path(payload["execution_root"]).resolve()
    assert execution_root == repo_root
    runtime = repo_root / "phase-loop-runtime"
    junit_path = Path(payload["criterion_junit_path"]).resolve()
    assert junit_path.parent.is_dir()
    environment = {
        "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(runtime / "src") + os.pathsep + str(runtime / "tests"),
    }
    if os.environ.get("PHASE_LOOP_CONFORM_B2_EVIDENCE") == "1":
        environment["PHASE_LOOP_CONFORM_B2_EVIDENCE"] = "1"
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--junitxml=" + str(junit_path),
        *("tests/" + nodeid for nodeid in nodeids),
    ]
    completed = subprocess.run(argv, cwd=runtime, capture_output=True, text=True, check=False, env=environment)
    junit_root = element_tree.parse(junit_path).getroot()
    normalize_junit_tree(junit_root)
    element_tree.ElementTree(junit_root).write(
        junit_path, encoding="utf-8", xml_declaration=True
    )
    if completed.returncode != 0:
        classification = "failed"
    elif "skipped" in completed.stdout.lower():
        classification = "skipped"
    elif "passed" in completed.stdout.lower():
        classification = "passed"
    else:
        classification = "inconclusive"
    observable = {
        "kind": "criterion-execution",
        "criterion": payload["criterion"],
        "nodeids": nodeids,
        "classification": classification,
        "execution": {
            "argv": argv,
            "cwd": str(runtime),
            "environment": environment,
            "exit_code": completed.returncode,
            "stdout_sha256": hashlib.sha256(normalize_mutation_output(completed.stdout).encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(normalize_mutation_output(completed.stderr).encode("utf-8")).hexdigest(),
            "junit_path": str(junit_path),
            "junit_sha256": hashlib.sha256(junit_path.read_bytes()).hexdigest(),
            "classification": classification,
        },
    }
    passed = classification == "passed"
    print(json.dumps({"status": "accepted" if passed else "blocked", "observable": observable}, sort_keys=True))
    raise SystemExit(0 if passed else 1)
    """
)
# Deliberately fictional negative control: never candidate-package evidence.
_TOY_NEGATIVE_PACKAGE_MEMBERS = {
    "phase_loop_runtime/__init__.py": b"",
    "phase_loop_runtime/conformance/__init__.py": b"",
    "phase_loop_runtime/conformance/outside_agent_schema.py": (
        b"import json\n\n"
        b"def validate(payload):\n"
        b"    if not isinstance(payload, dict):\n"
        b"        return {'status': 'blocked', 'observable': {'surface': 'api', 'accepted': False}}\n"
        b"    return {'status': 'accepted', 'observable': {'surface': 'api', 'accepted': True}}\n"
    ),
    "phase_loop_runtime/conformance/outside_agent_vectors.py": (
        b"import json\n"
        b"import sys\n\n"
        b"from .outside_agent_schema import validate\n\n"
        b"def run_vectors(payload):\n"
        b"    result = validate(payload)\n"
        b"    result['observable'] = {'surface': 'vector', 'accepted': result['status'] == 'accepted'}\n"
        b"    return result\n\n"
        b"def main():\n"
        b"    print(json.dumps(run_vectors(json.load(sys.stdin)), sort_keys=True))\n"
        b"    return 0\n\n"
        b"if __name__ == '__main__':\n"
        b"    raise SystemExit(main())\n"
    ),
    "phase_loop_runtime/cli.py": (
        b"import json\n"
        b"import sys\n\n"
        b"from phase_loop_runtime.conformance.outside_agent_schema import validate\n\n"
        b"def main(argv=None):\n"
        b"    argv = sys.argv[1:] if argv is None else argv\n"
        b"    assert argv == ['outside-agent-validate']\n"
        b"    result = validate(json.load(sys.stdin))\n"
        b"    result['observable'] = {'surface': 'cli', 'accepted': result['status'] == 'accepted'}\n"
        b"    print(json.dumps(result, sort_keys=True))\n"
        b"    return 0 if result['status'] == 'accepted' else 1\n\n"
        b"if __name__ == '__main__':\n"
        b"    raise SystemExit(main())\n"
    ),
}


def _write_tar_member(archive: tarfile.TarFile, name: str, contents: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(contents)
    archive.addfile(member, io.BytesIO(contents))


def _write_toy_wheel(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for member_name, contents in members.items():
            archive.writestr(member_name, contents)
        archive.writestr(
            "phase_loop_runtime-0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: phase-loop-runtime\n",
        )
        archive.writestr(
            "phase_loop_runtime-0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nTag: py3-none-any\n",
        )
        archive.writestr("phase_loop_runtime-0.0.dist-info/RECORD", "")


def _write_toy_sdist(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for member_name, contents in members.items():
            _write_tar_member(archive, "phase-loop-runtime/src/" + member_name, contents)
        _write_tar_member(
            archive,
            "phase-loop-runtime/PKG-INFO",
            b"Metadata-Version: 2.1\nName: phase-loop-runtime\n",
        )
        _write_tar_member(
            archive,
            "phase-loop-runtime/pyproject.toml",
            b"[build-system]\nrequires = []\nbuild-backend = 'setuptools.build_meta'\n",
        )


def _write_toy_negative_package_archives(
    root: Path, contract_members: dict[str, bytes]
) -> dict[str, Path]:
    """Create rejected toy archives; they cannot satisfy package evidence."""
    package_members = {**_TOY_NEGATIVE_PACKAGE_MEMBERS, **contract_members}
    archives = {
        "direct-wheel": root / "direct-wheel.whl",
        "direct-sdist": root / "direct-sdist.tar.gz",
        "sdist-derived-wheel": root / "sdist-derived-wheel.whl",
    }
    _write_toy_wheel(archives["direct-wheel"], package_members)
    _write_toy_sdist(archives["direct-sdist"], package_members)
    with tarfile.open(archives["direct-sdist"]) as archive:
        derived_members = {
            member.name.split("/src/", 1)[1]: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile() and "/src/phase_loop_runtime/" in member.name
        }
    assert derived_members == package_members
    _write_toy_wheel(archives["sdist-derived-wheel"], derived_members)
    return archives


def _build_candidate_package_archives(
    root: Path, candidate_commit: str
) -> dict[str, Path]:
    """Build all package routes from one exact committed candidate tree."""
    root.mkdir()
    exported = _run_bound_child_bytes(
        ["git", "archive", "--format=tar", candidate_commit], cwd=REPO_ROOT
    )
    assert exported.returncode == 0, exported.stderr.decode("utf-8", errors="replace")
    candidate_export = root / "candidate-export"
    candidate_export.mkdir()
    with tarfile.open(fileobj=io.BytesIO(exported.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            assert parts and not member.name.startswith("/") and ".." not in parts
            assert member.isfile() or member.isdir()
        _extract_tar_archive(archive, candidate_export)
    candidate_runtime = candidate_export / "phase-loop-runtime"
    source_date_epoch = _run_bound_child(
        ["git", "show", "-s", "--format=%ct", candidate_commit],
        input_text="",
        cwd=REPO_ROOT,
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert source_date_epoch.returncode == 0 and source_date_epoch.stdout.strip().isdecimal()
    environment = {
        **os.environ,
        "SOURCE_DATE_EPOCH": source_date_epoch.stdout.strip(),
    }
    direct_wheel_dist = root / "direct-wheel-dist"
    direct_sdist_dist = root / "direct-sdist-dist"
    for arguments, output in (
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
                str(output),
                str(candidate_runtime),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
    direct_wheel = next(direct_wheel_dist.glob("*.whl"))
    direct_sdist = next(direct_sdist_dist.glob("*.tar.gz"))
    sdist_export = root / "sdist-export"
    sdist_export.mkdir()
    with tarfile.open(direct_sdist) as archive:
        _extract_tar_archive(archive, sdist_export)
    sdist_roots = [path for path in sdist_export.iterdir() if path.is_dir()]
    assert len(sdist_roots) == 1
    derived_wheel_dist = root / "sdist-derived-wheel-dist"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(derived_wheel_dist),
            str(sdist_roots[0]),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return {
        "direct-wheel": direct_wheel,
        "direct-sdist": direct_sdist,
        "sdist-derived-wheel": next(derived_wheel_dist.glob("*.whl")),
    }


def _capture_subprocess_observable(
    root: Path,
    *,
    prefix: str,
    command: list[str],
    payload: dict[str, object],
    environment: dict[str, str],
    cwd: Path,
) -> dict[str, object]:
    """Capture raw command result bytes before deriving any semantic fields."""
    input_text = json.dumps(payload, sort_keys=True)
    completed = _run_bound_child(
        command,
        input_text=input_text,
        cwd=cwd,
        environment=environment,
    )
    result_path = root / f"{prefix}.result.json"
    captured = {
        "command": command,
        "cwd": str(cwd),
        "environment": environment,
        "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    result_path.write_text(json.dumps(captured, sort_keys=True), encoding="utf-8")
    assert completed.stdout, completed.stderr
    parsed = json.loads(completed.stdout)
    assert isinstance(parsed, dict)
    observable = parsed.get("observable")
    assert isinstance(observable, dict)
    return {
        "command": command,
        "cwd": str(cwd),
        "environment": environment,
        "input_sha256": hashlib.sha256(
            input_text.encode("utf-8")
        ).hexdigest(),
        "exit_code": completed.returncode,
        "status": parsed.get("status"),
        "anchor": parsed.get("anchor"),
        "output_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "result_path": str(result_path),
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "observable": observable,
    }


def _assert_captured_observable(
    record: dict[str, object],
    *,
    expected_command: list[str],
    expected_payload: dict[str, object],
    expected_exit: int,
    expected_status: str,
    expected_observable: dict[str, object],
    expected_anchor: str | None = None,
    environment: dict[str, str],
    cwd: Path,
) -> None:
    """Recompute a result artifact; manifest labels never prove behavior."""
    assert set(record) == {
        "command",
        "cwd",
        "environment",
        "input_sha256",
        "exit_code",
        "status",
        "anchor",
        "output_sha256",
        "result_path",
        "result_sha256",
        "observable",
    }
    assert record["command"] == expected_command
    assert record["cwd"] == str(cwd)
    assert record["environment"] == environment

    expected_input_bytes = json.dumps(expected_payload, sort_keys=True).encode("utf-8")
    expected_input_sha256 = hashlib.sha256(expected_input_bytes).hexdigest()
    assert record["input_sha256"] == expected_input_sha256
    assert record["input_sha256"] != "0" * 64

    result_path = Path(record["result_path"])
    assert result_path.is_file()
    raw_result = result_path.read_bytes()
    assert record["result_sha256"] == hashlib.sha256(raw_result).hexdigest()
    captured = json.loads(raw_result)
    assert set(captured) == {
        "command",
        "cwd",
        "environment",
        "input_sha256",
        "exit_code",
        "stdout",
        "stderr",
    }
    assert captured["command"] == expected_command
    assert captured["cwd"] == str(cwd)
    assert captured["environment"] == environment
    assert captured["input_sha256"] == expected_input_sha256
    assert captured["exit_code"] == record["exit_code"] == expected_exit
    assert isinstance(captured["stdout"], str)
    assert record["output_sha256"] == hashlib.sha256(
        captured["stdout"].encode("utf-8")
    ).hexdigest()
    rendered = json.loads(captured["stdout"])
    assert rendered["status"] == record["status"] == expected_status
    assert rendered.get("anchor") == record["anchor"] == expected_anchor
    rerun = _run_bound_child(
        expected_command,
        input_text=expected_input_bytes.decode("utf-8"),
        cwd=cwd,
        environment=environment,
    )
    assert rerun.returncode == expected_exit, f"Rerun exit code mismatch: got {rerun.returncode}, expected {expected_exit}"
    assert hashlib.sha256(rerun.stdout.encode("utf-8")).hexdigest() == record["output_sha256"], "Rerun stdout digest mismatch"
    assert rerun.stderr == captured["stderr"], "Rerun stderr mismatch"
    rerun_rendered = json.loads(rerun.stdout)
    assert rerun_rendered["status"] == expected_status
    assert rerun_rendered.get("anchor") == expected_anchor

    if expected_observable.get("kind") == "criterion-execution":
        cap_out = rendered["observable"]["execution"]["stdout_sha256"]
        cap_err = rendered["observable"]["execution"]["stderr_sha256"]
        cap_junit = rendered["observable"]["execution"]["junit_sha256"]
        rerun_out = rerun_rendered["observable"]["execution"]["stdout_sha256"]
        rerun_err = rerun_rendered["observable"]["execution"]["stderr_sha256"]
        rerun_junit = rerun_rendered["observable"]["execution"]["junit_sha256"]

        assert isinstance(cap_out, str) and len(cap_out) == 64 and all(c in "0123456789abcdef" for c in cap_out) and cap_out != "0" * 64
        assert isinstance(cap_err, str) and len(cap_err) == 64 and all(c in "0123456789abcdef" for c in cap_err) and cap_err != "0" * 64
        assert isinstance(cap_junit, str) and len(cap_junit) == 64 and all(c in "0123456789abcdef" for c in cap_junit) and cap_junit != "0" * 64
        assert isinstance(rerun_out, str) and len(rerun_out) == 64 and all(c in "0123456789abcdef" for c in rerun_out) and rerun_out != "0" * 64
        assert isinstance(rerun_err, str) and len(rerun_err) == 64 and all(c in "0123456789abcdef" for c in rerun_err) and rerun_err != "0" * 64
        assert isinstance(rerun_junit, str) and len(rerun_junit) == 64 and all(c in "0123456789abcdef" for c in rerun_junit) and rerun_junit != "0" * 64

        rendered_obs = copy.deepcopy(rendered["observable"])
        record_obs = copy.deepcopy(record["observable"])
        expected_obs = copy.deepcopy(expected_observable)
        rerun_obs = copy.deepcopy(rerun_rendered["observable"])

        sentinel_stdout = "FIXED_STDOUT_SHA256"
        sentinel_stderr = "FIXED_STDERR_SHA256"
        sentinel_junit = "FIXED_JUNIT_SHA256"

        rendered_obs["execution"]["stdout_sha256"] = sentinel_stdout
        rendered_obs["execution"]["stderr_sha256"] = sentinel_stderr
        rendered_obs["execution"]["junit_sha256"] = sentinel_junit
        record_obs["execution"]["stdout_sha256"] = sentinel_stdout
        record_obs["execution"]["stderr_sha256"] = sentinel_stderr
        record_obs["execution"]["junit_sha256"] = sentinel_junit
        expected_obs["execution"]["stdout_sha256"] = sentinel_stdout
        expected_obs["execution"]["stderr_sha256"] = sentinel_stderr
        expected_obs["execution"]["junit_sha256"] = sentinel_junit
        rerun_obs["execution"]["stdout_sha256"] = sentinel_stdout
        rerun_obs["execution"]["stderr_sha256"] = sentinel_stderr
        rerun_obs["execution"]["junit_sha256"] = sentinel_junit

        assert rendered_obs == record_obs == expected_obs
        assert rerun_obs == expected_obs
    else:
        assert rendered["observable"] == record["observable"] == expected_observable
        assert rerun_rendered["observable"] == expected_observable


_INSTALLED_PACKAGE_RUNNER = textwrap.dedent(
    """
    import json, subprocess, sys
    from pathlib import Path

    request = json.load(sys.stdin)
    surface = request["surface"]
    payload = request["payload"]
    case_id = request["case_id"]
    if surface == "api":
        from phase_loop_runtime.conformance.outside_agent_core import validate_outside_agent_submission
        verdict = validate_outside_agent_submission(payload)
        result = {"status": verdict.status.value, "blocker_codes": sorted(item.code for item in verdict.blockers)}
    elif surface == "route-schema":
        from phase_loop_runtime.conformance.outside_agent_schema import validate_outside_agent_route_verdict_schema
        verdict = validate_outside_agent_route_verdict_schema(payload, schema_target="outside_agent_route_verdict.v0.1")
        result = {"status": verdict.status.value, "blocker_codes": sorted(item.code for item in verdict.blockers), "dispatch_observation": getattr(verdict, "dispatch_observation", None)}
    elif surface == "vector":
        from phase_loop_runtime.conformance.outside_agent_vectors import run_outside_agent_vectors
        result_item = next(item for item in run_outside_agent_vectors() if item.vector_name == case_id)
        result = {"status": result_item.status.value, "blocker_codes": sorted(item.code for item in result_item.blockers), "dispatch_observation": getattr(result_item, "dispatch_observation", None)}
    else:
        input_path = Path.cwd() / (case_id + ".submission.json")
        output_path = Path.cwd() / (case_id + ".output.json")
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-m", "phase_loop_runtime.cli", "outside-agent-validate", str(input_path), "--output", str(output_path)], capture_output=True, text=True, check=False)
        rendered = json.loads(completed.stdout)
        result = {"status": rendered["status"], "blocker_codes": sorted(item["code"] for item in rendered["blockers"]), "cli_stdout": completed.stdout, "cli_stderr": completed.stderr, "output_bytes": output_path.read_text(encoding="utf-8"), "cli_exit": completed.returncode}
    print(json.dumps(result, sort_keys=True))
    """
)


def _capture_package_executions(root: Path, archives: dict[str, Path]) -> list[dict[str, object]]:
    """Exercise actual frozen interfaces from each installed candidate archive."""
    executions: list[dict[str, object]] = []
    rows = (*submission_entries(), route_verdict_entry())
    for variant in PACKAGE_EXECUTION_VARIANTS:
        archive_path = archives[variant]
        execution_root = root / f"{variant}-isolated"
        install_root = execution_root / "site-packages"
        execution_root.mkdir()
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(install_root),
        }
        install_command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-compile",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            str(install_root),
            str(archive_path),
        ]
        installed = _run_bound_child(
            install_command,
            input_text="",
            cwd=execution_root,
            environment=environment,
        )
        assert installed.returncode == 0, installed.stdout + installed.stderr
        assert (install_root / "phase_loop_runtime/conformance/outside_agent_core.py").is_file()
        install_raw_path = execution_root / "installation.raw.json"
        install_raw_path.write_text(
            json.dumps(
                {
                    "argv": install_command,
                    "environment": environment,
                    "exit_code": installed.returncode,
                    "stdout": installed.stdout,
                    "stderr": installed.stderr,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        install_observation = {
            "argv": install_command,
            "exit_code": installed.returncode,
            "target": str(install_root),
            "raw_path": str(install_raw_path),
            "raw_sha256": hashlib.sha256(install_raw_path.read_bytes()).hexdigest(),
        }
        cases = []
        oracle = __import__("_outside_agent_canonical").load_oracle()
        for row in rows:
            surfaces = ("route-schema", "vector") if row["schema_target"].endswith("route_verdict.v0.1") else ("api", "cli", "vector")
            for surface in surfaces:
                request = {"surface": surface, "case_id": row["case_id"], "payload": vector_payload(row)}
                command = [sys.executable, "-c", _INSTALLED_PACKAGE_RUNNER]
                completed = _run_bound_child(command, input_text=json.dumps(request, sort_keys=True), cwd=execution_root, environment=environment)
                raw_path = root / f"{variant}-{row['case_id']}-{surface}.raw.json"
                raw = {"argv": command, "environment": environment, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
                raw_path.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")
                assert completed.stdout, completed.stderr
                cases.append(
                    {
                        "case_id": row["case_id"],
                        "surface": surface,
                        "oracle_blocker_class": oracle.blocker_class_of(
                            oracle.route(vector_payload(row), row["schema_target"])
                        ),
                        "raw_path": str(raw_path),
                        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                        "result": json.loads(completed.stdout),
                    }
                )
        executions.append(
            {
                "variant": variant,
                "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                "installation_posture": "pip-target-no-deps-no-build-isolation",
                "installation": install_observation,
                "cases": cases,
            }
        )
    return executions


def _capture_rejected_observable(
    root: Path,
    *,
    case_id: str,
    mutation_id: str,
    source_path: str,
    nodeid: str,
    anchor: str,
) -> dict[str, object]:
    payload = {
        "mutation_id": mutation_id,
        "source_path": source_path,
        "expected_nodeid": nodeid,
        "expected_anchor": anchor,
        "repo_root": str(REPO_ROOT),
        "execution_root": str(root / f"{case_id}.execution"),
    }
    command = [sys.executable, "-c", _MUTATION_PROBE_RUNNER]
    return _capture_subprocess_observable(
        root,
        prefix=case_id,
        command=command,
        payload=payload,
        environment=_source_execution_environment(),
        cwd=REPO_ROOT,
    )


def _assert_mutation_execution(observable: object, definition) -> None:
    assert isinstance(observable, dict)
    assert set(observable) == {
        "kind",
        "classification",
        "candidate_oid",
        "candidate_tree",
        "candidate_archive_sha256",
        "candidate_clean",
        "candidate_sha256",
        "source_sha256",
        "mutant_sha256",
        "nodeid_matched",
        "anchor_matched",
        "companion",
        "baseline",
        "positive_control",
        "mutant",
    }
    source = _candidate_mutation_source(definition)
    mutant = definition.apply(source)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    candidate = _repo_candidate_identity()
    candidate_oid = candidate["candidate_oid"]
    assert observable["kind"] == "mutation-execution"
    assert observable["classification"] in {"killed", "incomplete"}
    assert observable["candidate_oid"] == candidate_oid
    assert observable["candidate_tree"] == candidate["candidate_tree"]
    assert observable["candidate_archive_sha256"] == candidate[
        "candidate_archive_sha256"
    ]
    assert observable["candidate_clean"] is candidate["candidate_clean"]
    if not candidate["candidate_clean"]:
        assert observable["classification"] == "incomplete"
    assert observable["candidate_sha256"] == (
        hashlib.sha256((candidate_oid + "\n").encode("utf-8")).hexdigest()
        if candidate_oid is not None
        else None
    )
    assert observable["source_sha256"] == source_sha256
    assert observable["mutant_sha256"] == hashlib.sha256(mutant.encode("utf-8")).hexdigest()
    assert isinstance(observable["nodeid_matched"], bool)
    assert isinstance(observable["anchor_matched"], bool)
    execution_root = None
    for name, argv in (
        ("baseline", list(definition.argv)),
        ("positive_control", list(definition.positive_control)),
        ("mutant", list(definition.argv)),
    ):
        result = observable[name]
        assert isinstance(result, dict)
        assert set(result) == {
            "argv",
            "cwd",
            "environment",
            "exit_code",
            "stdout_sha256",
            "stderr_sha256",
            "classification",
        }
        assert result["argv"] == argv
        assert result["classification"] in {
            "passed",
            "skipped",
            "failed",
            "inconclusive",
        }
        assert (result["exit_code"] == 0) != (result["classification"] == "failed")
        assert isinstance(result["cwd"], str)
        execution_root = execution_root or result["cwd"]
        assert result["cwd"] == execution_root
        assert result["environment"] == _expected_execution_environment(execution_root)
        assert all(
            isinstance(result[key], str)
            and len(result[key]) == 64
            and result[key] != "0" * 64
            for key in ("stdout_sha256", "stderr_sha256")
        )
    companion = observable["companion"]
    if definition.companion_argv is None:
        assert companion is None
    else:
        assert isinstance(companion, dict)
        assert set(companion) == {
            "argv",
            "expected_nodeid",
            "expected_anchor",
            "nodeid_matched",
            "anchor_matched",
            "baseline",
            "mutant",
        }
        assert companion["argv"] == list(definition.companion_argv)
        assert companion["expected_nodeid"] == definition.companion_expected_nodeid
        assert companion["expected_anchor"] == definition.companion_expected_anchor
        assert isinstance(companion["nodeid_matched"], bool)
        assert isinstance(companion["anchor_matched"], bool)
        for name in ("baseline", "mutant"):
            result = companion[name]
            assert isinstance(result, dict)
            assert set(result) == {
                "argv",
                "cwd",
                "environment",
                "exit_code",
                "stdout_sha256",
                "stderr_sha256",
                "classification",
            }
            assert result["argv"] == list(definition.companion_argv)
            assert result["cwd"] == execution_root
            assert result["environment"] == observable["baseline"]["environment"]
            assert result["classification"] in {
                "passed",
                "skipped",
                "failed",
                "inconclusive",
            }
            assert (result["exit_code"] == 0) != (
                result["classification"] == "failed"
            )
            assert all(
                isinstance(result[key], str)
                and len(result[key]) == 64
                and result[key] != "0" * 64
                for key in ("stdout_sha256", "stderr_sha256")
            )
    baseline = observable["baseline"]
    positive_control = observable["positive_control"]
    mutant_result = observable["mutant"]
    if observable["classification"] == "killed":
        assert baseline["classification"] == "passed"
        assert positive_control["classification"] == "passed"
        assert mutant_result["classification"] == "failed"
        assert observable["nodeid_matched"] is True
        assert observable["anchor_matched"] is True
        if companion is not None:
            assert companion["baseline"]["classification"] == "passed"
            assert companion["mutant"]["classification"] == "failed"
            assert companion["nodeid_matched"] is True
            assert companion["anchor_matched"] is True
    else:
        assert (
            not candidate["candidate_clean"]
            or baseline["classification"] != "passed"
            or positive_control["classification"] != "passed"
            or mutant_result["classification"] != "failed"
            or observable["nodeid_matched"] is not True
            or observable["anchor_matched"] is not True
            or (
                companion is not None
                and (
                    companion["baseline"]["classification"] != "passed"
                    or companion["mutant"]["classification"] != "failed"
                    or companion["nodeid_matched"] is not True
                    or companion["anchor_matched"] is not True
                )
            )
        )


def _assert_ec_criterion_execution(ec_id: str, criterion: str, observable: object) -> None:
    assert isinstance(observable, dict)
    assert set(observable) == {
        "kind",
        "criterion",
        "nodeids",
        "classification",
        "execution",
    }
    assert observable["kind"] == "criterion-execution"
    assert observable["criterion"] == criterion
    assert observable["nodeids"] == list(_EC_PROBE_NODEIDS[ec_id])
    execution = observable["execution"]
    assert isinstance(execution, dict)
    assert set(execution) == {
        "argv",
        "cwd",
        "environment",
        "exit_code",
        "stdout_sha256",
        "stderr_sha256",
        "junit_path",
        "junit_sha256",
        "classification",
    }
    runtime = Path(execution["cwd"])
    assert execution["argv"] == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--junitxml=" + execution["junit_path"],
        *("tests/" + nodeid for nodeid in _EC_PROBE_NODEIDS[ec_id]),
    ]
    assert execution["environment"] == _expected_execution_environment(runtime.parent)
    junit_path = Path(execution["junit_path"])
    assert junit_path.is_file()
    junit_bytes = junit_path.read_bytes()
    assert execution["junit_sha256"] == hashlib.sha256(junit_bytes).hexdigest()
    junit_root = element_tree.parse(junit_path).getroot()
    junit_cases = list(junit_root.iter("testcase"))
    assert junit_cases
    if any(
        case.find("failure") is not None or case.find("error") is not None
        for case in junit_cases
    ):
        primary_classification = "failed"
    elif any(case.find("skipped") is not None for case in junit_cases):
        primary_classification = "skipped"
    else:
        primary_classification = "passed"
    assert observable["classification"] in {"passed", "skipped", "failed", "inconclusive"}
    assert (
        execution["classification"]
        == observable["classification"]
        == primary_classification
    )
    if observable["classification"] == "passed":
        assert execution["exit_code"] == 0
    elif observable["classification"] == "skipped":
        assert execution["exit_code"] == 0
    else:
        assert execution["exit_code"] != 0 or execution["classification"] == "inconclusive"
    assert all(
        isinstance(execution[key], str)
        and len(execution[key]) == 64
        and execution[key] != "0" * 64
        for key in ("stdout_sha256", "stderr_sha256", "junit_sha256")
    )


def _assert_bound_mutation_observables(mutations: list[dict[str, object]]) -> None:
    assert tuple(mutation["id"] for mutation in mutations) == tuple(
        CONFORM_MUTATION_DEFINITIONS
    )
    for mutation_id, definition in CONFORM_MUTATION_DEFINITIONS.items():
        mutation = next(item for item in mutations if item["id"] == mutation_id)
        assert set(mutation) == {
            "id",
            "source_path",
            "expected_nodeid",
            "expected_anchor",
            "observable",
        }
        assert mutation["source_path"] == definition.source_path
        assert mutation["expected_nodeid"] == definition.expected_nodeid
        assert mutation["expected_anchor"] == definition.expected_anchor
        observable = mutation["observable"]
        assert isinstance(observable, dict)
        assert set(observable) == {
            "command",
            "cwd",
            "environment",
            "input_sha256",
            "exit_code",
            "status",
            "anchor",
            "output_sha256",
            "result_path",
            "result_sha256",
            "observable",
        }
        _assert_mutation_execution(observable["observable"], definition)
        expected_payload = {
            "mutation_id": mutation_id,
            "source_path": definition.source_path,
            "expected_nodeid": definition.expected_nodeid,
            "expected_anchor": definition.expected_anchor,
            "repo_root": str(REPO_ROOT),
            "execution_root": observable["observable"]["mutant"]["cwd"],
        }
        expected_command = [sys.executable, "-c", _MUTATION_PROBE_RUNNER]
        _assert_captured_observable(
            observable,
            expected_command=expected_command,
            expected_payload=expected_payload,
            expected_exit=1,
            expected_status=(
                "blocked"
                if observable["observable"]["classification"] == "killed"
                else "incomplete"
            ),
            expected_anchor=definition.expected_anchor,
            expected_observable=observable["observable"],
            environment=_source_execution_environment(),
            cwd=REPO_ROOT,
        )


def _assert_complete_mutation_observables(mutations: list[dict[str, object]]) -> None:
    _assert_bound_mutation_observables(mutations)
    assert all(
        mutation["observable"]["observable"]["classification"] == "killed"
        for mutation in mutations
    )


def _capture_ec_matrix_entries(root: Path) -> list[dict[str, object]]:
    entries = []
    command = [sys.executable, "-c", _EC_PROBE_RUNNER]
    for index, ec_id in enumerate(EC_CONFORM_IDS):
        probe_spec = EC_CONFORM_PROBES[ec_id]
        payload = {
            "id": ec_id,
            "ordinal": index,
            "criterion": probe_spec["criterion"],
            "probe_nodes": json.dumps(_EC_PROBE_NODEIDS, sort_keys=True),
            "repo_root": str(REPO_ROOT),
            "execution_root": str(REPO_ROOT),
            "criterion_junit_path": str(root / f"{ec_id}.criterion.junit.xml"),
        }
        observable = _capture_subprocess_observable(
            root,
            prefix=ec_id,
            command=command,
            payload=payload,
            environment=_source_execution_environment(),
            cwd=REPO_ROOT,
        )
        entries.append({"id": ec_id, "ordinal": index, "observable": observable})
    return entries


def _assert_bound_ec_observables(entries: list[dict[str, object]]) -> None:
    assert tuple(entry["id"] for entry in entries) == EC_CONFORM_IDS
    assert [entry["ordinal"] for entry in entries] == list(range(len(entries)))
    command = [sys.executable, "-c", _EC_PROBE_RUNNER]
    for entry in entries:
        assert set(entry) == {"id", "ordinal", "observable"}
        ec_id = entry["id"]
        probe_spec = EC_CONFORM_PROBES[ec_id]
        observable = entry["observable"]
        assert isinstance(observable, dict)
        _assert_ec_criterion_execution(ec_id, probe_spec["criterion"], observable["observable"])
        expected_payload = {
            "id": ec_id,
            "ordinal": entry["ordinal"],
            "criterion": probe_spec["criterion"],
            "probe_nodes": json.dumps(_EC_PROBE_NODEIDS, sort_keys=True),
            "repo_root": str(REPO_ROOT),
            "execution_root": observable["observable"]["execution"]["cwd"].removesuffix(
                "/phase-loop-runtime"
            ),
            "criterion_junit_path": observable["observable"]["execution"][
                "junit_path"
            ],
        }
        _assert_captured_observable(
            observable,
            expected_command=command,
            expected_payload=expected_payload,
            expected_exit=(
                0 if observable["observable"]["classification"] == "passed" else 1
            ),
            expected_status=(
                "accepted"
                if observable["observable"]["classification"] == "passed"
                else "blocked"
            ),
            expected_observable=observable["observable"],
            environment=_source_execution_environment(),
            cwd=REPO_ROOT,
        )


def _assert_complete_ec_observables(entries: list[dict[str, object]]) -> None:
    _assert_bound_ec_observables(entries)
    assert all(
        entry["observable"]["observable"]["classification"] == "passed"
        for entry in entries
    )


def _assert_f17ab557_label_trusting_compatibility_accepts(
    entries: list[dict[str, object]],
) -> None:
    """Freeze the shallow f17 acceptance predicate for the forged-pass control."""
    assert [entry.get("id") for entry in entries] == list(EC_CONFORM_IDS)
    assert [entry.get("ordinal") for entry in entries] == list(range(len(entries)))
    for entry in entries:
        captured = entry.get("observable")
        observable = captured.get("observable") if isinstance(captured, dict) else None
        assert isinstance(observable, dict)
        assert observable.get("classification") == "passed"
        assert captured.get("status") == "accepted"
        result_path = Path(captured["result_path"])
        assert result_path.is_file()
        assert captured.get("result_sha256") == hashlib.sha256(
            result_path.read_bytes()
        ).hexdigest()


def _assert_complete_package_executions(
    executions: list[dict[str, object]], archives: dict[str, object]
) -> None:
    assert tuple(execution["variant"] for execution in executions) == PACKAGE_EXECUTION_VARIANTS
    expected = {
        (row["case_id"], surface)
        for row in (*submission_entries(), route_verdict_entry())
        for surface in (("route-schema", "vector") if row["schema_target"].endswith("route_verdict.v0.1") else ("api", "cli", "vector"))
    }
    oracle = __import__("_outside_agent_canonical").load_oracle()
    for execution in executions:
        variant = execution["variant"]
        assert set(execution) == {
            "variant",
            "archive_sha256",
            "installation_posture",
            "installation",
            "cases",
        }
        assert execution["installation_posture"] == "pip-target-no-deps-no-build-isolation"
        installation = execution["installation"]
        assert set(installation) == {
            "argv",
            "exit_code",
            "target",
            "raw_path",
            "raw_sha256",
        }
        assert installation["exit_code"] == 0
        expected_install_argv = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-compile",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            installation["target"],
            str(Path(archives[variant]["path"])),
        ]
        assert installation["argv"] == expected_install_argv
        install_raw_path = Path(installation["raw_path"])
        assert installation["raw_sha256"] == hashlib.sha256(
            install_raw_path.read_bytes()
        ).hexdigest()
        install_raw = json.loads(install_raw_path.read_text(encoding="utf-8"))
        assert install_raw["argv"] == expected_install_argv
        assert install_raw["exit_code"] == 0
        assert install_raw["stdout"]
        assert install_raw["environment"]["PIP_NO_INDEX"] == "1"
        assert install_raw["environment"]["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
        assert install_raw["environment"]["PYTHONPATH"] == installation["target"]
        assert Path(installation["target"], "phase_loop_runtime").is_dir()
        assert tuple(Path(installation["target"]).glob("phase_loop_runtime-*.dist-info"))
        assert execution["archive_sha256"] == archives[variant]["sha256"]
        archive_path = Path(archives[variant]["path"])
        members = _normalized_archive_member_digests(archive_path)
        assert "phase_loop_runtime/conformance/outside_agent_core.py" in members
        assert {(case["case_id"], case["surface"]) for case in execution["cases"]} == expected
        assert not any(
            case["case_id"] == "negative-unsupported-verdict"
            and case["surface"] == "cli"
            for case in execution["cases"]
        )
        for case in execution["cases"]:
            assert set(case) == {
                "case_id",
                "surface",
                "oracle_blocker_class",
                "raw_path",
                "raw_sha256",
                "result",
            }
            raw_path = Path(case["raw_path"])
            assert case["raw_sha256"] == hashlib.sha256(raw_path.read_bytes()).hexdigest()
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            assert raw["argv"] == [sys.executable, "-c", _INSTALLED_PACKAGE_RUNNER]
            assert raw["environment"]["PHASE_LOOP_TDD_EXPECT_CONFORM"] == "0"
            row = next(row for row in (*submission_entries(), route_verdict_entry()) if row["case_id"] == case["case_id"])
            result = case["result"]
            assert raw["exit_code"] == 0
            assert json.loads(raw["stdout"]) == result
            assert result["status"] == ("pass" if row["expected_valid"] else "blocked")
            assert case["oracle_blocker_class"] == row["expected_blocker_class"]
            assert case["oracle_blocker_class"] == oracle.blocker_class_of(
                oracle.route(vector_payload(row), row["schema_target"])
            )
            blocker_codes = set(result["blocker_codes"])
            if row["expected_valid"]:
                assert blocker_codes == set()
            else:
                assert LIVE_BLOCKER_CODE_BY_INVALID_CASE[row["case_id"]] in blocker_codes
            if case["surface"] == "cli":
                assert raw["exit_code"] == 0
                assert result["cli_exit"] == SUBMISSION_CLI_EXIT_BY_CASE[row["case_id"]]
                assert result["cli_stdout"] == result["output_bytes"]
                rendered = json.loads(result["cli_stdout"])
                assert rendered["redaction_posture"] == "metadata_only"
                assert len(rendered["input_digest"]) == 64
                assert rendered["contract_pin"]["source_owner"] == "Consiliency/spec"
            elif case["surface"] == "route-schema":
                observation = result["dispatch_observation"]
                assert observation["schema_target"] == "outside_agent_route_verdict.v0.1"
                assert observation["validation_error_pointer"] == "/route"
                assert observation["validation_error_keyword"] == "enum"


def _write_synthetic_junit_rejection_fixture(path: Path, raw_log_path: Path) -> None:
    """Write a fully shaped but runner-unbacked lifecycle forgery."""
    suites = element_tree.Element("testsuites", {"name": "pytest tests"})
    suite = element_tree.SubElement(
        suites,
        "testsuite",
        {
            "name": "pytest",
            "tests": str(ALL_OUTSIDE_AGENT_NODE_COUNT),
            "failures": str(CONFORM_ACTIVATED_RED_NODE_COUNT),
            "skipped": "0",
            "errors": "0",
            "time": "1.000",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "hostname": "synthetic.invalid",
        },
    )
    for nodeid in ALL_OUTSIDE_AGENT_NODE_IDS:
        path_part, name = nodeid.split("::", 1)
        classname = path_part.removeprefix("phase-loop-runtime/").removesuffix(
            ".py"
        ).replace("/", ".")
        case = element_tree.SubElement(
            suite,
            "testcase",
            {"classname": classname, "name": name, "time": "0.001"},
        )
        properties = element_tree.SubElement(case, "properties")
        element_tree.SubElement(
            properties,
            "property",
            {"name": "conform_expected_node_id", "value": nodeid},
        )
        if nodeid in CONFORM_ACTIVATED_RED_NODE_IDS:
            failure = element_tree.SubElement(case, "failure")
            failure.text = CONFORM_ACTIVATED_RED_ANCHORS[nodeid]
    element_tree.ElementTree(suites).write(path, encoding="utf-8", xml_declaration=True)
    failure_count = CONFORM_ACTIVATED_RED_NODE_COUNT + 1
    raw_log_path.write_text(
        f"{failure_count} failed, "
        f"{ALL_OUTSIDE_AGENT_NODE_COUNT - failure_count} passed, "
        "0 skipped, 0 deselected in 1.00s\n",
        encoding="utf-8",
    )


def _assert_exact_frozen_activated_junit(path: Path, raw_log_path: Path) -> None:
    """Require correlated raw pytest node, property, summary, and anchor evidence."""
    root = element_tree.parse(path).getroot()
    assert root.tag == "testsuites" and root.attrib.get("name") == "pytest tests"
    suites = root.findall("testsuite")
    assert len(suites) == 1
    suite = suites[0]
    assert suite.attrib.get("name") == "pytest"
    assert suite.attrib.get("hostname") and suite.attrib.get("timestamp")
    all_cases = suite.findall("testcase")
    assert int(suite.attrib["tests"]) == len(all_cases)
    assert int(suite.attrib["errors"]) == 0
    cases: dict[str, element_tree.Element] = {}
    for case in all_cases:
        classname = case.attrib.get("classname", "")
        if not classname:
            continue
        nodeid = (
            "phase-loop-runtime/"
            + classname.replace(".", "/")
            + ".py::"
            + case.attrib["name"]
        )
        if nodeid in ALL_OUTSIDE_AGENT_NODE_IDS:
            assert nodeid not in cases
            properties = {
                prop.attrib.get("name"): prop.attrib.get("value")
                for prop in case.findall("./properties/property")
            }
            assert properties.get("conform_expected_node_id") == nodeid
            cases[nodeid] = case
    assert set(cases) == set(ALL_OUTSIDE_AGENT_NODE_IDS)
    failures = {
        nodeid: (case.find("failure").text or "")
        + " "
        + case.find("failure").attrib.get("message", "")
        for nodeid, case in cases.items()
        if case.find("failure") is not None
    }
    assert set(failures) == set(CONFORM_ACTIVATED_RED_NODE_IDS)
    assert all(
        CONFORM_ACTIVATED_RED_ANCHORS[nodeid] in failures[nodeid]
        for nodeid in CONFORM_ACTIVATED_RED_NODE_IDS
    )
    assert not any(
        case.find("skipped") is not None or case.find("error") is not None
        for case in cases.values()
    )
    suite_failures = int(suite.attrib["failures"])
    suite_skips = int(suite.attrib["skipped"])
    suite_passes = len(all_cases) - suite_failures - suite_skips
    raw_log = raw_log_path.read_text(encoding="utf-8")
    assert (
        f"{suite_failures} failed, {suite_passes} passed, "
        f"{suite_skips} skipped," in raw_log
    )
    for nodeid, failure_text in failures.items():
        assert f"FAILED {nodeid}" in raw_log
        assert CONFORM_ACTIVATED_RED_ANCHORS[nodeid] in failure_text


def _capture_immutable_lifecycle(root: Path, candidate_commit: str) -> dict[str, object]:
    """Run the committed frozen test blobs in clean, non-Git candidate exports."""
    test_paths = CONFORM_IMMUTABLE_LIFECYCLE_PATHS
    head_blobs = {
        path: _run_bound_child(["git", "rev-parse", f"HEAD:{path}"], input_text="", cwd=REPO_ROOT, environment={"PATH": os.environ.get("PATH", "")}).stdout.strip()
        for path in test_paths
    }
    walk_res = _run_bound_child(["git", "rev-list", candidate_commit], input_text="", cwd=REPO_ROOT, environment={"PATH": os.environ.get("PATH", "")})
    assert walk_res.returncode == 0
    walked_commits = [c.strip() for c in walk_res.stdout.splitlines() if c.strip()]
    assert len(walked_commits) > 0

    match_cache = {}

    def commit_matches(commit):
        if commit not in match_cache:
            object_exists = _run_bound_child(["git", "cat-file", "-e", f"{commit}^{{commit}}"], input_text="", cwd=REPO_ROOT, environment={"PATH": os.environ.get("PATH", "")})
            assert object_exists.returncode == 0
            matches = True
            for path, blob in head_blobs.items():
                res = _run_bound_child(["git", "rev-parse", f"{commit}:{path}"], input_text="", cwd=REPO_ROOT, environment={"PATH": os.environ.get("PATH", "")})
                if res.returncode != 0 or res.stdout.strip() != blob:
                    matches = False
            match_cache[commit] = matches
        return match_cache[commit]

    parent_vectors = {}
    for commit in walked_commits:
        parents_res = _run_bound_child(["git", "rev-list", "--parents", "-n", "1", commit], input_text="", cwd=REPO_ROOT, environment={"PATH": os.environ.get("PATH", "")})
        assert parents_res.returncode == 0
        tokens = parents_res.stdout.split()
        assert tokens[0] == commit
        parent_vectors[commit] = tokens[1:]

    for commit in walked_commits:
        commit_matches(commit)
        for parent in parent_vectors[commit]:
            commit_matches(parent)

    boundaries = []
    for commit in walked_commits:
        parents = parent_vectors[commit]
        if commit_matches(commit) and not any(commit_matches(parent) for parent in parents):
            assert len(parents) >= 1
            boundaries.append(commit)

    assert len(boundaries) == 1
    boundary = boundaries[0]

    ancestor_res = _run_bound_child(["git", "merge-base", "--is-ancestor", boundary, candidate_commit], input_text="", cwd=REPO_ROOT, environment={"PATH": os.environ.get("PATH", "")})
    assert ancestor_res.returncode == 0

    for commit in walked_commits:
        if commit != boundary and commit_matches(commit):
            match_ancestor_res = _run_bound_child(["git", "merge-base", "--is-ancestor", boundary, commit], input_text="", cwd=REPO_ROOT, environment={"PATH": os.environ.get("PATH", "")})
            assert match_ancestor_res.returncode == 0

    test_commit = boundary
    test_tree = _run_bound_child(
        ["git", "rev-parse", f"{test_commit}^{{tree}}"],
        input_text="",
        cwd=REPO_ROOT,
        environment={"PATH": os.environ.get("PATH", "")},
    ).stdout.strip()
    test_archive = _run_bound_child_bytes(
        ["git", "archive", "--format=tar", test_commit],
        cwd=REPO_ROOT,
    )
    assert test_archive.returncode == 0
    ancestry = _run_bound_child(
        ["git", "merge-base", "--is-ancestor", test_commit, candidate_commit],
        input_text="",
        cwd=REPO_ROOT,
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert ancestry.returncode == 0
    captures: dict[str, object] = {
        "test_commit": test_commit,
        "test_tree": test_tree,
        "test_archive_sha256": hashlib.sha256(test_archive.stdout).hexdigest(),
        "test_blobs": head_blobs,
    }
    for label, activated in (("default", False), ("activated", True)):
        execution_root = root / f"lifecycle-{label}"
        execution_root.mkdir()
        with tarfile.open(fileobj=io.BytesIO(test_archive.stdout), mode="r:") as archive:
            _extract_tar_archive(archive, execution_root)
        junit_path = execution_root / f"{label}.junit.xml"
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONWARNINGS": "ignore::SyntaxWarning",
            "PYTHONPATH": str(execution_root / "phase-loop-runtime/src")
            + os.pathsep
            + str(execution_root / "phase-loop-runtime/tests"),
        }
        if activated:
            environment["PHASE_LOOP_TDD_EXPECT_CONFORM"] = "1"
        command = [sys.executable, "-m", "pytest", "phase-loop-runtime/tests", "-q", "-k", "outside_agent", f"--junitxml={junit_path}"]
        completed = _run_bound_child(command, input_text="", cwd=execution_root, environment=environment)
        raw_log = (completed.stdout + "\n--- stderr ---\n" + completed.stderr).encode("utf-8")
        raw_log_path = execution_root / f"{label}.raw.log"
        raw_log_path.write_bytes(raw_log)
        frozen_cases: dict[str, element_tree.Element] = {}
        for case in element_tree.parse(junit_path).getroot().findall(".//testcase"):
            classname = case.attrib.get("classname", "")
            if not classname:
                continue
            nodeid = (
                "phase-loop-runtime/"
                + classname.replace(".", "/")
                + ".py::"
                + case.attrib["name"]
            )
            if nodeid in ALL_OUTSIDE_AGENT_NODE_IDS:
                assert nodeid not in frozen_cases
                frozen_cases[nodeid] = case
        assert set(frozen_cases) == set(ALL_OUTSIDE_AGENT_NODE_IDS)
        failures = [
            nodeid
            for nodeid in ALL_OUTSIDE_AGENT_NODE_IDS
            if frozen_cases[nodeid].find("failure") is not None
        ]
        skips = [
            nodeid
            for nodeid in ALL_OUTSIDE_AGENT_NODE_IDS
            if frozen_cases[nodeid].find("skipped") is not None
        ]
        failure_anchors = {
            nodeid: (
                (frozen_cases[nodeid].find("failure").text or "")
                + " "
                + frozen_cases[nodeid].find("failure").attrib.get("message", "")
            )
            for nodeid in failures
        }
        captures[label] = {
            "argv": command,
            "environment": environment,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "raw_log_path": str(raw_log_path),
            "raw_log_sha256": hashlib.sha256(raw_log).hexdigest(),
            "junit_path": str(junit_path),
            "junit_sha256": hashlib.sha256(junit_path.read_bytes()).hexdigest(),
            "node_ids": list(ALL_OUTSIDE_AGENT_NODE_IDS),
            "failures": failures,
            "failure_anchors": failure_anchors,
            "skips": skips,
        }
    default = captures["default"]
    activated = captures["activated"]
    assert default["exit_code"] == 0 and default["skips"] == list(
        CONFORM_NEW_PRODUCTION_NODE_IDS
    )
    assert not default["failures"]
    assert activated["exit_code"] != 0 and not activated["skips"]
    assert tuple(activated["node_ids"]) == ALL_OUTSIDE_AGENT_NODE_IDS
    assert set(activated["failures"]) == set(CONFORM_ACTIVATED_RED_NODE_IDS)
    assert all(
        CONFORM_ACTIVATED_RED_ANCHORS[nodeid]
        in activated["failure_anchors"][nodeid]
        for nodeid in CONFORM_ACTIVATED_RED_NODE_IDS
    )
    _assert_exact_frozen_activated_junit(
        Path(activated["junit_path"]), Path(activated["raw_log_path"])
    )
    return captures


def _assert_full_frozen_evidence_input(
    mode: str, records: list[dict[str, object]]
) -> None:
    """Validate full runner-owned inputs before any verifier positive can run."""
    assert tuple(record["record_id"] for record in records) == EVIDENCE_VERIFIER_RECORD_IDS[mode]
    assert [record["ordinal"] for record in records] == list(range(len(records)))
    artifact_paths = {record["artifact_path"] for record in records}
    assert len(artifact_paths) == 1
    facts = json.loads(Path(next(iter(artifact_paths))).read_text(encoding="utf-8"))
    bindings = {
        name: facts[name]
        for name in (
            "candidate_commit",
            "candidate_tree",
            "head_commit",
            "head_tree",
            "module_path",
        )
    }
    runner_manifest = json.loads(
        Path(facts["runner_manifest"]["path"]).read_text(encoding="utf-8")
    )
    assert runner_manifest["candidate_head_module"] == bindings
    assert runner_manifest["provenance"] == facts["vendor"]
    assert runner_manifest["activated_lifecycle"] == {
        "tests": ALL_OUTSIDE_AGENT_NODE_COUNT,
        "failures": CONFORM_ACTIVATED_RED_NODE_COUNT,
        "skipped": 0,
        "node_ids": list(ALL_OUTSIDE_AGENT_NODE_IDS),
        "red_node_ids": list(CONFORM_ACTIVATED_RED_NODE_IDS),
        "red_anchors": CONFORM_ACTIVATED_RED_ANCHORS,
    }
    lifecycle = runner_manifest["lifecycle"]
    assert lifecycle == facts["lifecycle"]
    assert lifecycle["test_commit"] == facts["parent_commit"]
    assert lifecycle["test_tree"] == facts["parent_tree"]
    assert lifecycle["default"]["exit_code"] == 0
    assert lifecycle["default"]["skips"] == list(CONFORM_NEW_PRODUCTION_NODE_IDS)
    assert lifecycle["default"]["failures"] == []
    assert lifecycle["activated"]["exit_code"] != 0
    assert set(lifecycle["activated"]["failures"]) == set(
        CONFORM_ACTIVATED_RED_NODE_IDS
    )
    assert lifecycle["activated"]["skips"] == []
    for stage in ("default", "activated"):
        assert lifecycle[stage]["raw_log_sha256"] == hashlib.sha256(
            Path(lifecycle[stage]["raw_log_path"]).read_bytes()
        ).hexdigest()
        assert lifecycle[stage]["junit_sha256"] == hashlib.sha256(
            Path(lifecycle[stage]["junit_path"]).read_bytes()
        ).hexdigest()
    _assert_exact_frozen_activated_junit(
        Path(facts["junit_path"]), Path(facts["runner_log_path"])
    )
    mutations = facts["mutation_records"]
    _assert_complete_mutation_observables(mutations)
    chronology = facts["chronology"]["stages"]
    assert chronology[0]["failing_node_ids"] == list(CONFORM_ACTIVATED_RED_NODE_IDS)
    assert chronology[0]["failing_anchors"] == CONFORM_ACTIVATED_RED_ANCHORS
    assert chronology[1]["mutation_outcomes"] == {
        mutation["id"]: "killed" for mutation in mutations
    }
    assert tuple(
        len(facts["corpus"]["partitions"][partition])
        for partition in (
            "valid_submissions",
            "invalid_submissions",
            "invalid_route_verdicts",
        )
    ) == (3, 7, 1)
    assert facts["package"]["contract_members"] == SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS
    assert facts["package"]["artifact_provenance"] == bindings
    installed_package = json.loads(
        Path(facts["installed_package"]["path"]).read_text(encoding="utf-8")
    )
    assert set(installed_package) == {
        "package",
        "module_path",
        "variants",
        "contract_members",
        "corpus_partitions",
        "executions",
    }
    assert installed_package["package"] == "phase-loop-runtime"
    assert installed_package["module_path"] == bindings["module_path"]
    assert tuple(installed_package["variants"]) == PACKAGE_EXECUTION_VARIANTS
    assert installed_package["contract_members"] == SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS
    assert installed_package["corpus_partitions"] == facts["corpus"]["partitions"]
    _assert_complete_package_executions(installed_package["executions"], facts["archives"])
    if mode == "compatibility":
        ec_matrix = json.loads(
            Path(facts["ec_matrix"]["path"]).read_text(encoding="utf-8")
        )
        assert set(ec_matrix) == {"candidate_commit", "candidate_tree", "entries"}
        assert ec_matrix["candidate_commit"] == bindings["candidate_commit"]
        assert ec_matrix["candidate_tree"] == bindings["candidate_tree"]
        _assert_complete_ec_observables(ec_matrix["entries"])
        assert "ec_matrix" in runner_manifest
    else:
        assert "ec_matrix" not in facts
        assert "ec_matrix" not in runner_manifest


def test_frozen_inventory_counts_and_set_equations() -> None:
    assert len(ALL_OUTSIDE_AGENT_NODE_IDS) == ALL_OUTSIDE_AGENT_NODE_COUNT == 93
    assert len(CONFORM_PREEXISTING_NODE_IDS) == CONFORM_PREEXISTING_NODE_COUNT == 71
    assert len(CONFORM_TEST_ONLY_INTEGRITY_NODE_IDS) == CONFORM_TEST_ONLY_INTEGRITY_NODE_COUNT == 12
    assert len(CONFORM_NEW_PRODUCTION_NODE_IDS) == CONFORM_NEW_PRODUCTION_NODE_COUNT == 10
    assert len(CONFORM_DIALECT_MIGRATED_NODE_IDS) == CONFORM_DIALECT_MIGRATED_NODE_COUNT == 42
    assert len(CONFORM_MIGRATED_EXISTING_NODE_IDS) == CONFORM_MIGRATED_EXISTING_NODE_COUNT == 45
    assert len(CONFORM_MIGRATED_RED_NODE_IDS) == CONFORM_MIGRATED_RED_NODE_COUNT == 38
    assert len(CONFORM_ACTIVATED_RED_NODE_IDS) == CONFORM_ACTIVATED_RED_NODE_COUNT == 48
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


def test_frozen_command_literals_and_selector_partition(
    tmp_path: Path, monkeypatch
) -> None:
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

    namespace: dict[str, object] = {}
    exec(_MUTATION_OUTPUT_NORMALIZER_SOURCE, namespace)
    normalize_junit_tree = namespace["normalize_junit_tree"]
    first = element_tree.fromstring(
        '<testsuite time="1.0"><testcase><failure>'
        'monkeypatch=&lt;MonkeyPatch object at 0xabc123&gt; pytest-41 in 0.42s'
        "</failure></testcase></testsuite>"
    )
    second = element_tree.fromstring(
        '<testsuite time="9.0"><testcase><failure>'
        'monkeypatch=&lt;MonkeyPatch object at 0xdef456&gt; pytest-99 in 8.75s'
        "</failure></testcase></testsuite>"
    )
    normalize_junit_tree(first)
    normalize_junit_tree(second)
    assert element_tree.tostring(first) == element_tree.tostring(second)
    first_junit_digest = hashlib.sha256(element_tree.tostring(first)).hexdigest()
    second_junit_digest = hashlib.sha256(element_tree.tostring(second)).hexdigest()
    assert first_junit_digest == second_junit_digest
    first_outer = json.dumps({"junit_sha256": first_junit_digest}, sort_keys=True)
    second_outer = json.dumps({"junit_sha256": second_junit_digest}, sort_keys=True)
    assert hashlib.sha256(first_outer.encode()).hexdigest() == hashlib.sha256(
        second_outer.encode()
    ).hexdigest()

    calls = []

    def planted_failing_seal_reader():
        calls.append("called")
        raise AssertionError("planted seal reader")

    monkeypatch.setattr(
        outside_agent_canonical,
        "sealed_release_evidence",
        planted_failing_seal_reader,
    )
    monkeypatch.delenv(RUNNER_B2_EVIDENCE_ENV, raising=False)
    assert outside_agent_canonical.runner_b2_evidence() is None
    assert calls == []
    monkeypatch.setenv(RUNNER_B2_EVIDENCE_ENV, "1")
    with pytest.raises(AssertionError, match="planted seal reader"):
        outside_agent_canonical.runner_b2_evidence()
    assert calls == ["called"]
    assert _source_execution_environment()[RUNNER_B2_EVIDENCE_ENV] == "1"

    transitioned_blobs = {
        path: ("0" * 40 if parent_blob != "0" * 40 else "1" * 40)
        for path, parent_blob in SEALED_RELEASE_FINAL_PARENT_BLOBS.items()
    }

    def transitioned_rev_parse(argv, **_kwargs):
        path = argv[-1].removeprefix("HEAD:")
        return subprocess.CompletedProcess(argv, 0, transitioned_blobs[path] + "\n", "")

    monkeypatch.setattr(
        sys.modules[__name__], "_run_bound_child", transitioned_rev_parse
    )
    monkeypatch.delenv(RUNNER_B2_EVIDENCE_ENV, raising=False)
    assert _sl2_compatibility_transitioned() is True
    assert _b2_compatibility_evidence_due() is False

    conform_source = Path(__file__).read_text(encoding="utf-8")
    release_source = (
        Path(__file__).with_name("test_outside_agent_release_surface.py")
    ).read_text(encoding="utf-8")
    canonical_source = (
        Path(__file__).with_name("_outside_agent_canonical.py")
    ).read_text(encoding="utf-8")
    assert "def _sl2_compatibility_transitioned() -> bool:" in conform_source
    assert "return runner_b2_evidence_enabled() and _sl2_compatibility_transitioned()" in conform_source
    assert "evidence = runner_b2_evidence()\n    if evidence is None:\n        return" in release_source
    assert "evidence = runner_b2_evidence()\n    if evidence is None:\n        return" in canonical_source
    assert 'RUNNER_B2_EVIDENCE_ENV = "PHASE_LOOP_CONFORM_B2_EVIDENCE"' in canonical_source


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
    planted.unlink()
    planted = planted.with_name("invalid-unsupported-verdict.json")
    planted.write_bytes(
        (
            FIXTURE_ROOT
            / "test-vectors/outside-agent/invalid-unsupported-verdict.json"
        ).read_bytes()
    )
    copied, scanned = find_non_enumerated_canonical_copies(tmp_path)
    assert scanned == 1
    assert copied == (
        "phase-loop-runtime/src/phase_loop_runtime/_sl0_planted/"
        "invalid-unsupported-verdict.json",
    )
    planted.write_text(
        planted.read_text(encoding="utf-8")
        .replace('"route": "accepted_for_merge"', '"route": "edited_route"')
        .replace('"notes": "Rejected because', '"notes": "Edited copy because'),
        encoding="utf-8",
    )
    copied, scanned = find_non_enumerated_canonical_copies(tmp_path)
    assert scanned == 1
    assert copied == (
        "phase-loop-runtime/src/phase_loop_runtime/_sl0_planted/"
        "invalid-unsupported-verdict.json",
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
    activated_hook = next(
        node
        for node in conftest_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "pytest_pyfunc_call"
    )
    strict_dispatches = [
        call
        for call in ast.walk(activated_hook)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "assert_named_canonical_capability"
    ]
    assert len(strict_dispatches) == 1
    assert not any(
        isinstance(attribute, ast.Attribute) and attribute.attr == "obj"
        for attribute in ast.walk(activated_hook)
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
        fixture_members["phase_loop_runtime/conformance/_contract/VENDOR.json"] = (
            EXPECTED_VENDOR_BYTES
        )
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
    git("commit", "-m", "full SL-1 transition")

    verifier_path = (
        release_repo
        / "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py"
    )
    verifier_path.write_bytes(
        verifier_path.read_bytes() + b"\n# CONFORM_SL1_VERIFIER_REPAIR: recompute-sealed-semantics\n"
    )
    git("add", str(verifier_path.relative_to(release_repo)))
    git("commit", "-m", "repair SL-1 verifier semantics")
    candidate_commit = git("rev-parse", "HEAD")
    candidate_tree = git("rev-parse", "HEAD^{tree}")
    candidate_bytes[
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py"
    ] = verifier_path.read_bytes()

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
        _extract_tar_archive(archive, sdist_export)
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
    a2_package_evidence = _build_a2_package_evidence(
        candidate_commit=candidate_commit,
        candidate_tree=candidate_tree,
        candidate_members=_member_digests(candidate_bytes),
        archives=archives,
    )
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
        "a2_package_evidence": {
            key: value
            for key, value in a2_package_evidence.items()
            if key != "a2_package_evidence_sha256"
        },
        "a2_package_evidence_sha256": a2_package_evidence[
            "a2_package_evidence_sha256"
        ],
    }
    sealed["manifest_sha256"] = _sealed_manifest_sha256(sealed)
    sealed_path = tmp_path / "sealed-release-evidence.json"
    sealed_path.write_text(json.dumps(sealed, sort_keys=True), encoding="utf-8")
    assert sealed_release_evidence(sealed_path, release_repo) == sealed
    repacked_wheel = tmp_path / "repacked-sdist-derived.whl"
    with zipfile.ZipFile(derived_wheel) as source, zipfile.ZipFile(
        repacked_wheel, "w", compression=zipfile.ZIP_STORED
    ) as target:
        for member in reversed(source.infolist()):
            if not member.is_dir():
                target.writestr(member.filename, source.read(member.filename))
    assert _normalized_archive_member_digests(repacked_wheel) == (
        _normalized_archive_member_digests(derived_wheel)
    )
    assert hashlib.sha256(repacked_wheel.read_bytes()).hexdigest() not in {
        hashlib.sha256(direct_wheel.read_bytes()).hexdigest(),
        hashlib.sha256(derived_wheel.read_bytes()).hexdigest(),
    }
    forged = copy.deepcopy(sealed)
    for label in ("direct-wheel", "sdist-derived-wheel"):
        forged["archives"][label] = copy.deepcopy(sealed["archives"][label])
        forged["archives"][label]["path"] = str(repacked_wheel)
        forged["archives"][label]["sha256"] = hashlib.sha256(
            Path(forged["archives"][label]["path"]).read_bytes()
        ).hexdigest()
    forged["manifest_sha256"] = _sealed_manifest_sha256(forged)
    sealed_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    # Refreshed caller hashes cannot make a semantically equivalent repack serve
    # as the exact runner-rebuilt output for either independently replayed route.
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


def test_mutation_definitions_are_frozen_but_not_executed_preimplementation(
    tmp_path, monkeypatch
) -> None:
    namespace: dict[str, object] = {}
    exec(_MUTATION_OUTPUT_NORMALIZER_SOURCE, namespace)
    normalize = namespace["normalize_mutation_output"]
    digest = "a1" * 32
    rendered = (
        "node=test_dispatch_bypass CONFORM_RED::dispatch_bypass "
        "monkeypatch=<MonkeyPatch object at 0x7f1FeC1993c0> "
        f"digest={digest} pytest-123 in 0.42s"
    )

    assert normalize(rendered) == (
        "node=test_dispatch_bypass CONFORM_RED::dispatch_bypass "
        "monkeypatch=<MonkeyPatch object at <address>> "
        f"digest={digest} pytest-<run> in <duration>"
    )
    assert normalize("1 passed in 196.00s (0:03:15)") == "1 passed in <duration>"
    assert _EC_PROBE_RUNNER.startswith(_MUTATION_OUTPUT_NORMALIZER_SOURCE)
    assert (
        "hashlib.sha256(normalize_mutation_output(completed.stdout).encode(\"utf-8\")).hexdigest()"
        in _EC_PROBE_RUNNER
    )
    assert (
        "hashlib.sha256(normalize_mutation_output(completed.stderr).encode(\"utf-8\")).hexdigest()"
        in _EC_PROBE_RUNNER
    )
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
    for mutation_id, expected_observable in (
        (
            "M-CONFORM-5-SUBMISSION-SCHEMA-BYTE",
            "submission_schema_sha256_mismatch",
        ),
        (
            "M-CONFORM-5-VERDICT-SCHEMA-BYTE",
            "verdict_schema_sha256_mismatch",
        ),
    ):
        mutation = CONFORM_MUTATION_DEFINITIONS[mutation_id]
        assert mutation.expected_anchor == "DID NOT RAISE"
        assert mutation.expected_observable == expected_observable
    for mutation_id, mutation in CONFORM_MUTATION_DEFINITIONS.items():
        assert mutation.source_path.startswith("phase-loop-runtime/src/")
        assert mutation.argv[1:4] == ("-m", "pytest", "-q")
        assert mutation.argv[-1] == mutation.expected_nodeid
        assert mutation.positive_control[-1] != mutation.expected_nodeid
        assert mutation.expected_observable
        if mutation_id == "M-CONFORM-1-RESTORE-ALLOWLIST":
            assert mutation.companion_argv is not None
            assert mutation.companion_argv[-1] == mutation.companion_expected_nodeid
            assert mutation.companion_expected_anchor == (
                "CONFORM_RED::canonical_submission_cli_accepts_three_valid_rows"
            )
        else:
            assert mutation.companion_argv is None
            assert mutation.companion_expected_nodeid is None
            assert mutation.companion_expected_anchor is None
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

    # Candidate-only identity controls must remain executable while SL-0 has no
    # verifier and the real B1 documents are deliberately stale.  These
    # synthetic documents use only candidate and sealed-package-shaped values.
    candidate_identity_anchor = "CONFORM_RED::candidate_only_identity_control"
    synthetic_candidate_commit = "1" * 40
    synthetic_candidate_tree = "2" * 40
    synthetic_forbidden_identity_values = {
        "final_commit": "3" * 40,
        "final_tree": "4" * 40,
        "final_candidate": "5" * 40,
        "final_candidate_tree": "6" * 40,
        "implementation_landing": "7" * 40,
        "implementation_landing_tree": "8" * 40,
        "canonical_main_head": "9" * 40,
        "canonical_main_head_tree": "a" * 40,
    }
    synthetic_archive_sha256 = {
        "direct-wheel": "b" * 64,
        "direct-sdist": "c" * 64,
        "sdist-derived-wheel": "d" * 64,
    }
    synthetic_candidate_documents = {
        path: "\n".join(
            (
                f"# Candidate-only evidence for {path}",
                *(
                    (
                        (
                            f"Candidate implementation commit: `{synthetic_candidate_commit}`",
                            f"Candidate implementation tree: `{synthetic_candidate_tree}`",
                        )
                        if path == "specs/phase-plans-v7.md"
                        else (
                            f"Candidate implementation commit: {synthetic_candidate_commit}",
                            f"Candidate implementation tree: {synthetic_candidate_tree}",
                        )
                    )
                    if path in B1_CANDIDATE_IDENTITY_PATHS
                    else ()
                ),
                "Sealed package evidence SHA256: " + "e" * 64,
                *(f"{label} SHA256: {digest}" for label, digest in synthetic_archive_sha256.items()),
                "",
            )
        )
        for path in SEALED_RELEASE_FINAL_PATHS
    }
    assert set(synthetic_candidate_documents) == set(SEALED_RELEASE_FINAL_PATHS)
    for path, document in synthetic_candidate_documents.items():
        assert_candidate_identity_only_document(
            document,
            candidate_commit=synthetic_candidate_commit,
            candidate_tree=synthetic_candidate_tree,
            forbidden_identity_values=synthetic_forbidden_identity_values,
            anchor=candidate_identity_anchor,
            require_candidate_identity=path in B1_CANDIDATE_IDENTITY_PATHS,
        )
        for forged_label, forged_value in (
            ("final implementation commit", synthetic_forbidden_identity_values["final_commit"]),
            ("final-candidate", synthetic_forbidden_identity_values["final_candidate"]),
            ("implementation-landing", synthetic_forbidden_identity_values["implementation_landing"]),
            ("canonical-main-head", synthetic_forbidden_identity_values["canonical_main_head"]),
        ):
            forged_document = document + f"{forged_label}: {forged_value}\n"
            assert forged_document != document
            with pytest.raises(AssertionError, match=candidate_identity_anchor):
                assert_candidate_identity_only_document(
                    forged_document,
                    candidate_commit=synthetic_candidate_commit,
                    candidate_tree=synthetic_candidate_tree,
                    forbidden_identity_values=synthetic_forbidden_identity_values,
                    anchor=candidate_identity_anchor,
                    require_candidate_identity=path in B1_CANDIDATE_IDENTITY_PATHS,
                )
    verifier_spec = importlib.util.find_spec(
        "phase_loop_runtime.conformance.outside_agent_conform_evidence"
    )
    for mutation_id in (
        "M-CONFORM-2-RAW-CONSTRUCTION-GUARD",
        "M-CONFORM-3-FINAL-SERIALIZER-GUARD",
    ):
        mutation = CONFORM_MUTATION_DEFINITIONS[mutation_id]
        source_path = REPO_ROOT / mutation.source_path
        if not source_path.exists():
            relative = Path(mutation.source_path).relative_to("phase-loop-runtime/src")
            spec = importlib.util.find_spec(".".join(relative.with_suffix("").parts))
            assert spec is not None and spec.origin is not None
            source_path = Path(spec.origin)
        actual_source = source_path.read_text(encoding="utf-8")
        # SL-0 has no future anchor.  Later candidate mutation must fail closed
        # on an absent or duplicated anchor; it may never fall back to this
        # test-only fixture when changing production bytes.
        if verifier_spec is None:
            assert actual_source.count(mutation.anchor) == 0
            with pytest.raises(AssertionError):
                _candidate_mutation_source(mutation)
            with pytest.raises(AssertionError):
                mutation.apply(actual_source)
        else:
            assert actual_source.count(mutation.anchor) == 1
            assert _candidate_mutation_source(mutation) == actual_source
            assert mutation.apply(actual_source) != actual_source
        with pytest.raises(AssertionError):
            mutation.apply(mutation.anchor + "\n" + mutation.anchor)
    assert set(CONFORM_CANONICAL_CASES) == set(CONFORM_MIGRATED_EXISTING_NODE_IDS)
    assert len({case.role for case in CONFORM_CANONICAL_CASES.values()}) == 45
    captured_mutation_ids: list[str] = []
    capture_rejected_observable = _capture_rejected_observable

    def capture_with_chronology_proof(root: Path, **kwargs) -> dict[str, object]:
        captured_mutation_ids.append(kwargs["mutation_id"])
        return capture_rejected_observable(root, **kwargs)

    monkeypatch.setattr(
        sys.modules[__name__],
        "_capture_rejected_observable",
        capture_with_chronology_proof,
    )
    if verifier_spec is not None:
        assert_status_code_only_replacement_is_rejected()
        assert_named_safety_mutations_rejected()
    for nodeid, case in CONFORM_CANONICAL_CASES.items():
        assert (nodeid in CONFORM_ACTIVATED_RED_ANCHORS) == (nodeid in CONFORM_ACTIVATED_RED_NODE_IDS)
        assert case.seam
        assert (case.mutation is None) == (case.expected_code is None)
        assert node_source_path(nodeid).exists()
    assert tuple(EVIDENCE_VERIFIER_INTERFACE) == ("chronology", "corpus", "package", "compatibility")
    assert EC_CONFORM_IDS == (
        "EC-CONFORM-0",
        "EC-CONFORM-1",
        "EC-CONFORM-2",
        "EC-CONFORM-3",
        "EC-CONFORM-4",
        "EC-CONFORM-5",
        "EC-CONFORM-6",
        "EC-CONFORM-7",
        "EC-CONFORM-8",
    )
    frozen_junit = tmp_path / "frozen-activated.junit.xml"
    frozen_log = tmp_path / "frozen-activated.raw.log"
    _write_synthetic_junit_rejection_fixture(frozen_junit, frozen_log)
    with pytest.raises(AssertionError):
        _assert_exact_frozen_activated_junit(frozen_junit, frozen_log)
    # This is the exact Sol reproducer shape.  It cannot become a positive by
    # refreshing its own digest fields because it omits 91 nodes and 47 REDs.
    undersized_junit = tmp_path / "undersized-activated.junit.xml"
    element_tree.ElementTree(
        element_tree.fromstring(
            '<testsuite name="outside-agent-activated-lifecycle" tests="2" '
            'failures="1" skipped="0"><testcase name="positive"/>'
            '<testcase name="mutation:M-CONFORM-8-SWAP-SCHEMA"><failure/>'
            "</testcase></testsuite>"
        )
    ).write(undersized_junit, encoding="utf-8", xml_declaration=True)
    with pytest.raises(AssertionError):
        _assert_exact_frozen_activated_junit(undersized_junit, frozen_log)
    # SL-0 executes only test-owned structural negative controls. Production
    # mutation and EC probes remain declarations until the verifier marks SL-1.
    direct_root = tmp_path / "direct-observable-controls"
    direct_root.mkdir()
    direct_archives = _write_toy_negative_package_archives(
        direct_root,
        {"phase_loop_runtime/conformance/_contract/VENDOR.json": b"{}"},
    )
    direct_archive_facts = {
        label: {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for label, path in direct_archives.items()
    }
    # These deliberately skeletal archives are a negative/unit control only.
    # Candidate package evidence must reject them before any interface execution.
    with pytest.raises(AssertionError):
        _capture_package_executions(direct_root, direct_archives)
    with zipfile.ZipFile(direct_archives["direct-wheel"], "w") as archive:
        archive.writestr("phase_loop_runtime/conformance/_contract/VENDOR.json", "{}")
        archive.writestr(
            "phase_loop_runtime-0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: phase-loop-runtime\n",
        )
        archive.writestr(
            "phase_loop_runtime-0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nTag: py3-none-any\n",
        )
        archive.writestr("phase_loop_runtime-0.0.dist-info/RECORD", "")
    direct_archive_facts["direct-wheel"]["sha256"] = hashlib.sha256(
        direct_archives["direct-wheel"].read_bytes()
    ).hexdigest()
    with pytest.raises(AssertionError):
        _assert_complete_package_executions([], direct_archive_facts)

    # Future-only locator-boundary anchors intentionally do not exist in SL-0.
    # They are frozen source fixtures until the candidate implements them; never
    # manufacture an executable mutant from the fixture against this baseline.
    available_direct_mutations = (
        {
            mutation_id: definition
            for mutation_id, definition in CONFORM_MUTATION_DEFINITIONS.items()
            if (REPO_ROOT / definition.source_path).is_file()
            and (REPO_ROOT / definition.source_path).read_text(encoding="utf-8").count(
                definition.anchor
            ) == 1
        }
        if verifier_spec is not None
        else {}
    )
    if verifier_spec is None:
        assert set(CONFORM_MUTATION_DEFINITIONS) - set(available_direct_mutations) >= {
            "M-CONFORM-2-RAW-CONSTRUCTION-GUARD",
            "M-CONFORM-3-FINAL-SERIALIZER-GUARD",
        }
    else:
        assert set(available_direct_mutations) == set(CONFORM_MUTATION_DEFINITIONS)
    direct_mutations = [
        {
            "id": mutation_id,
            "source_path": definition.source_path,
            "expected_nodeid": definition.expected_nodeid,
            "expected_anchor": definition.expected_anchor,
            "observable": _capture_rejected_observable(
                direct_root,
                case_id="direct-" + mutation_id,
                mutation_id=mutation_id,
                source_path=definition.source_path,
                nodeid=definition.expected_nodeid,
                anchor=definition.expected_anchor,
            ),
        }
        for mutation_id, definition in available_direct_mutations.items()
    ]
    assert captured_mutation_ids == (
        list(available_direct_mutations) if verifier_spec is not None else []
    )
    if len(direct_mutations) == len(CONFORM_MUTATION_DEFINITIONS):
        _assert_bound_mutation_observables(direct_mutations)
    else:
        for mutation in direct_mutations:
            _assert_mutation_execution(
                mutation["observable"]["observable"],
                available_direct_mutations[mutation["id"]],
            )
    if direct_mutations and all(
        mutation["observable"]["observable"]["classification"] == "killed"
        for mutation in direct_mutations
    ):
        _assert_complete_mutation_observables(direct_mutations)
    else:
        with pytest.raises(AssertionError):
            _assert_complete_mutation_observables(direct_mutations)
    if direct_mutations:
        for invalid_mutations in (
            direct_mutations[:-1],
            [*direct_mutations[1:], direct_mutations[0]],
            [*direct_mutations[:-1], direct_mutations[0]],
            [
                {**direct_mutations[0], "observable": {"outcome": "killed"}},
                *direct_mutations[1:],
            ],
        ):
            with pytest.raises(AssertionError):
                _assert_bound_mutation_observables(invalid_mutations)
        tampered_mutations = copy.deepcopy(direct_mutations)
        Path(tampered_mutations[0]["observable"]["result_path"]).write_text(
            "{}", encoding="utf-8"
        )
        with pytest.raises(AssertionError):
            _assert_bound_mutation_observables(tampered_mutations)
        zeroed_mutations = copy.deepcopy(direct_mutations)
        zeroed_mutations[0]["observable"]["input_sha256"] = "0" * 64
        with pytest.raises(AssertionError):
            _assert_bound_mutation_observables(zeroed_mutations)
        command_tampered_mutations = copy.deepcopy(direct_mutations)
        command_tampered_mutations[0]["observable"]["command"] = [
            sys.executable,
            "-c",
            "print('tampered')",
        ]
        with pytest.raises(AssertionError):
            _assert_bound_mutation_observables(command_tampered_mutations)

    # The absent verifier identifies SL-0, where test-owned EC controls run
    # only as frozen definitions. Once SL-1 installs the verifier, only B2 may
    # execute and capture the complete EC matrix.
    compatibility_due = (
        verifier_spec is not None and _b2_compatibility_evidence_due()
    )
    direct_ec_entries = None
    if compatibility_due:
        direct_ec_entries = _capture_ec_matrix_entries(direct_root)
        _assert_bound_ec_observables(direct_ec_entries)
        if all(
            entry["observable"]["observable"]["classification"] == "passed"
            for entry in direct_ec_entries
        ):
            _assert_complete_ec_observables(direct_ec_entries)
        else:
            with pytest.raises(AssertionError):
                _assert_complete_ec_observables(direct_ec_entries)
        for invalid_entries in (
            direct_ec_entries[:-1],
            [*direct_ec_entries[1:], direct_ec_entries[0]],
            [*direct_ec_entries[:-1], direct_ec_entries[0]],
            [
                {"id": direct_ec_entries[0]["id"], "ordinal": 0, "outcome": "passed"},
                *direct_ec_entries[1:],
            ],
        ):
            with pytest.raises(AssertionError):
                _assert_bound_ec_observables(invalid_entries)
        tampered_ec_entries = copy.deepcopy(direct_ec_entries)
        Path(tampered_ec_entries[0]["observable"]["result_path"]).write_text(
            "{}", encoding="utf-8"
        )
        with pytest.raises(AssertionError):
            _assert_bound_ec_observables(tampered_ec_entries)
        zeroed_ec_entries = copy.deepcopy(direct_ec_entries)
        zeroed_ec_entries[0]["observable"]["input_sha256"] = "0" * 64
        with pytest.raises(AssertionError):
            _assert_bound_ec_observables(zeroed_ec_entries)
        command_tampered_ec_entries = copy.deepcopy(direct_ec_entries)
        command_tampered_ec_entries[0]["observable"]["command"] = [
            sys.executable,
            "-c",
            "print('tampered')",
        ]
        with pytest.raises(AssertionError):
            _assert_bound_ec_observables(command_tampered_ec_entries)
    with pytest.raises(AssertionError):
        _assert_complete_package_executions([], direct_archive_facts)

    if direct_mutations:
        forged_mut_set = copy.deepcopy(direct_mutations)
        forged_mut_res = forged_mut_set[0]["observable"]
        forged_mut_res["output_sha256"] = hashlib.sha256(b"forged_mut").hexdigest()
        Path(forged_mut_res["result_path"]).write_text(
            json.dumps(
                {
                    "command": forged_mut_res["command"],
                    "exit_code": 1,
                    "stdout": json.dumps(
                        {
                            "status": "blocked",
                            "anchor": direct_mutations[0]["expected_anchor"],
                            "observable": {
                                "kind": "rejection",
                                "nodeid": direct_mutations[0]["expected_nodeid"],
                            },
                        }
                    ),
                    "stderr": "",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        forged_mut_res["result_sha256"] = hashlib.sha256(
            Path(forged_mut_res["result_path"]).read_bytes()
        ).hexdigest()
        with pytest.raises(AssertionError):
            _assert_complete_mutation_observables(forged_mut_set)

    if direct_ec_entries is not None:
        forged_ec_set = copy.deepcopy(direct_ec_entries)
        forged_ec_res = forged_ec_set[0]["observable"]
        forged_ec_res["output_sha256"] = hashlib.sha256(b"forged_ec").hexdigest()
        Path(forged_ec_res["result_path"]).write_text(
            json.dumps(
                {
                    "command": forged_ec_res["command"],
                    "exit_code": 0,
                    "stdout": json.dumps(
                        {
                            "status": "accepted",
                            "observable": {
                                "kind": "ec-conform",
                                "id": direct_ec_entries[0]["id"],
                                "criterion": EC_CONFORM_PROBES[
                                    direct_ec_entries[0]["id"]
                                ]["criterion"],
                            },
                        },
                    ),
                    "stderr": "",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        forged_ec_res["result_sha256"] = hashlib.sha256(
            Path(forged_ec_res["result_path"]).read_bytes()
        ).hexdigest()
        with pytest.raises(AssertionError):
            _assert_complete_ec_observables(forged_ec_set)
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
    # SL-0 deliberately has no verifier. Once SL-1 supplies it, A2 exercises only
    # its three allowed modes. Compatibility joins after all four pinned SL-2
    # documentation paths transition, so this immutable test cannot run it early.
    if os.environ.get("PHASE_LOOP_CONFORM_CHRONOLOGY_PROOF") == "1":
        if verifier_spec is None:
            raise AssertionError("CONFORM_RED::chronology_accepts_forged_git_topology")
    if verifier_spec is not None:
        module = importlib.import_module(verifier_spec.name)
        assert module.EVIDENCE_VERIFIER_INTERFACE == EVIDENCE_VERIFIER_INTERFACE
        verifier = getattr(module, "verify_conform_evidence_records")
        executable_modes = tuple(
            mode
            for mode, contract in EVIDENCE_VERIFIER_INTERFACE.items()
            if contract["timing"] == "A2" or compatibility_due
        )
        assert executable_modes == (
            ("chronology", "corpus", "package", "compatibility")
            if compatibility_due
            else ("chronology", "corpus", "package")
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mode_invocations = {mode: 0 for mode in EVIDENCE_VERIFIER_INTERFACE}
            repository = REPO_ROOT

            def git(*argv: str) -> str:
                completed = subprocess.run(["git", *argv], cwd=repository, capture_output=True, text=True, check=False)
                assert completed.returncode == 0, completed.stdout + completed.stderr
                return completed.stdout.strip()

            head_identity = _repo_candidate_identity()
            assert head_identity["candidate_clean"] is True
            head_commit = head_identity["candidate_oid"]
            head_tree = head_identity["candidate_tree"]
            assert isinstance(head_commit, str) and isinstance(head_tree, str)
            final_candidate = head_commit
            chronology_scope = "a2_candidate"
            if compatibility_due:
                head_line = git("rev-list", "--parents", "-n", "1", head_commit).split()
                if len(head_line) == 3:
                    final_candidate = head_line[2]
                    chronology_scope = "exact_main"
                else:
                    assert len(head_line) == 2
                    chronology_scope = "b2_premerge"
                candidate = git("rev-parse", f"{final_candidate}^")
                assert candidate != final_candidate
                assert set(git("diff", "--name-only", candidate, final_candidate).splitlines()) == set(
                    SEALED_RELEASE_FINAL_PATHS
                )
            else:
                candidate = head_commit
            candidate_tree = git("rev-parse", f"{candidate}^{{tree}}")
            final_candidate_tree = git("rev-parse", f"{final_candidate}^{{tree}}")
            parent = git("rev-parse", f"{candidate}^")
            parent_tree = git("rev-parse", f"{parent}^{{tree}}")
            fixture_manifest = json.loads(
                (FIXTURE_ROOT / "test-vectors/outside-agent/manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            corpus_rows = [
                {
                    key: row[key]
                    for key in (
                        "case_id",
                        "schema_target",
                        "submission_kind",
                        "expected_valid",
                        "expected_blocker_class",
                    )
                }
                for row in fixture_manifest["vectors"]
            ]
            corpus_partitions = {
                "valid_submissions": sorted(
                    row["case_id"]
                    for row in corpus_rows
                    if row["expected_valid"]
                    and row["schema_target"] == "outside_agent_submission.v0.1"
                ),
                "invalid_submissions": sorted(
                    row["case_id"]
                    for row in corpus_rows
                    if not row["expected_valid"]
                    and row["schema_target"] == "outside_agent_submission.v0.1"
                ),
                "invalid_route_verdicts": sorted(
                    row["case_id"]
                    for row in corpus_rows
                    if not row["expected_valid"]
                    and row["schema_target"] == "outside_agent_route_verdict.v0.1"
                ),
            }
            assert tuple(len(ids) for ids in corpus_partitions.values()) == (3, 7, 1)
            contract_members = {
                "phase_loop_runtime/conformance/_contract/VENDOR.json": EXPECTED_VENDOR_BYTES,
                **{
                    "phase_loop_runtime/conformance/_contract/" + relative: (
                        FIXTURE_ROOT / relative
                    ).read_bytes()
                    for relative in fixture_paths()
                },
            }
            contract_member_digests = _member_digests(contract_members)
            assert len(contract_member_digests) == 16
            vendor = json.loads(
                contract_members[
                    "phase_loop_runtime/conformance/_contract/VENDOR.json"
                ].decode("utf-8")
            )
            bindings = {
                "candidate_commit": candidate,
                "candidate_tree": candidate_tree,
                "head_commit": head_commit,
                "head_tree": head_tree,
                "module_path": (
                    "phase-loop-runtime/src/phase_loop_runtime/conformance/"
                    "outside_agent_schema.py"
                ),
            }
            observable_root = root / "captured-observables"
            observable_root.mkdir()
            mutation_records = [
                {
                    "id": mutation_id,
                    "source_path": definition.source_path,
                    "expected_nodeid": definition.expected_nodeid,
                    "expected_anchor": definition.expected_anchor,
                    "observable": _capture_rejected_observable(
                        observable_root,
                        case_id=mutation_id,
                        mutation_id=mutation_id,
                        source_path=definition.source_path,
                        nodeid=definition.expected_nodeid,
                        anchor=definition.expected_anchor,
                    ),
                }
                for mutation_id, definition in CONFORM_MUTATION_DEFINITIONS.items()
            ]
            lifecycle = _capture_immutable_lifecycle(root, candidate)
            parent = lifecycle["test_commit"]
            parent_tree = lifecycle["test_tree"]
            activated_lifecycle = {
                "tests": len(lifecycle["activated"]["node_ids"]),
                "failures": len(lifecycle["activated"]["failures"]),
                "skipped": len(lifecycle["activated"]["skips"]),
                "node_ids": lifecycle["activated"]["node_ids"],
                "red_node_ids": list(CONFORM_ACTIVATED_RED_NODE_IDS),
                "red_anchors": CONFORM_ACTIVATED_RED_ANCHORS,
            }
            chronology_stages = [
                    {
                        "stage": "preimplementation_red",
                        "commit": parent,
                        "tree": parent_tree,
                        "exit_code": 1,
                        "failing_node_ids": list(CONFORM_ACTIVATED_RED_NODE_IDS),
                        "failing_anchors": CONFORM_ACTIVATED_RED_ANCHORS,
                        "review": {
                            "plan_path": "plans/phase-plan-v10-CONFORM.md",
                            "plan_sha256": hashlib.sha256(
                                (REPO_ROOT / "plans/phase-plan-v10-CONFORM.md").read_bytes()
                            ).hexdigest(),
                            "required_seats": ["Fable", "Sol", "Gemini", "Grok"],
                            "outcomes": {
                                "Fable": "AGREE",
                                "Sol": "AGREE",
                                "Gemini": "AGREE",
                                "Grok": "AGREE",
                            },
                        },
                        "topology": {
                            "test_candidate": parent,
                            "test_candidate_tree": parent_tree,
                            "candidate_descends_from_test_candidate": True,
                        },
                    },
                    {
                        "stage": "postimplementation_pre_doc",
                        "commit": candidate,
                        "tree": candidate_tree,
                        "exit_code": 0,
                        "mutation_outcomes": {
                            mutation["id"]: "killed" for mutation in mutation_records
                        },
                        "topology": {
                            "test_candidate": parent,
                            "candidate_commit": candidate,
                            "candidate_tree": candidate_tree,
                            "candidate_descends_from_test_candidate": True,
                            "test_paths_unchanged": True,
                        },
                    },
                ]
            if compatibility_due:
                chronology_stages.append(
                    {
                        "stage": "final_doc_chronology",
                        "commit": final_candidate,
                        "tree": final_candidate_tree,
                        "b0": {
                            "commit": candidate,
                            "tree": candidate_tree,
                            "argv": B0_COMMAND,
                            "exit_code": 1,
                            "failing_node_ids": list(CONFORM_SL2_STALE_DOC_NODE_IDS),
                            "skipped_node_ids": [],
                            "xfail_node_ids": [],
                            "collection_errors": [],
                        },
                        "b1": {
                            "before_commit": candidate,
                            "before_tree": candidate_tree,
                            "after_commit": final_candidate,
                            "after_tree": final_candidate_tree,
                            "changed_paths": list(SEALED_RELEASE_FINAL_PATHS),
                            "test_paths_unchanged": True,
                        },
                        "b2": {
                            "commit": final_candidate,
                            "tree": final_candidate_tree,
                            "argv": B2_COMMAND,
                            "exit_code": 0,
                            "node_ids": list(ALL_OUTSIDE_AGENT_NODE_IDS),
                            "skipped_node_ids": [],
                            "failed_node_ids": [],
                        },
                        "topology": {
                            "scope": chronology_scope,
                            "test_candidate": parent,
                            "implementation_candidate": candidate,
                            "final_candidate": final_candidate,
                            **(
                                {"canonical_main_head": head_commit}
                                if chronology_scope in {"a2_candidate", "exact_main"}
                                else {}
                            ),
                            "candidate_descends_from_test_candidate": True,
                            "final_descends_from_candidate": True,
                        },
                    }
                )
            chronology = {
                "scope": chronology_scope,
                "stages": chronology_stages,
                "candidate_head_module": bindings,
            }
            package_facts = {
                "contract_members": contract_member_digests,
                "artifact_provenance": bindings,
                "artifact_labels": [
                    "direct-wheel",
                    "direct-sdist",
                    "sdist-derived-wheel",
                ],
            }
            facts = {
                "owner": "phase-loop-runner",
                **bindings,
                "parent_commit": parent,
                "parent_tree": parent_tree,
                "changed_paths": list(SEALED_RELEASE_CANDIDATE_PATHS),
                "argv": ["python3", "-m", "pytest", "-q", "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition"],
                "vendor": vendor,
                "lifecycle": lifecycle,
                "chronology": chronology,
                "corpus": {"rows": corpus_rows, "partitions": corpus_partitions},
                "package": package_facts,
                "mutation_records": mutation_records,
                "mutations": mutation_records,
            }
            candidate_archives = _build_candidate_package_archives(
                root / "candidate-package-build", candidate
            )

            def records_for(mode: str, force_forgery: bool = False) -> tuple[list[dict[str, object]], dict[str, Path]]:
                invocation = mode_invocations[mode]
                mode_invocations[mode] += 1
                mode_root = root / mode / f"invocation-{invocation:03d}"
                mode_root.mkdir(parents=True)
                mode_log = mode_root / "runner.log"
                mode_log.write_bytes(Path(lifecycle["activated"]["raw_log_path"]).read_bytes())
                mode_junit = mode_root / "controls.junit.xml"
                mode_junit.write_bytes(Path(lifecycle["activated"]["junit_path"]).read_bytes())
                mode_archives = {}
                for label, source in candidate_archives.items():
                    target = mode_root / label / source.name
                    target.parent.mkdir()
                    shutil.copy2(source, target)
                    mode_archives[label] = target
                installed_package_facts = {
                    "package": "phase-loop-runtime",
                    "module_path": bindings["module_path"],
                    "variants": list(PACKAGE_EXECUTION_VARIANTS),
                    "contract_members": contract_member_digests,
                    "corpus_partitions": corpus_partitions,
                    "executions": _capture_package_executions(mode_root, mode_archives),
                }
                ec_matrix_entries = (
                    _capture_ec_matrix_entries(mode_root)
                    if mode == "compatibility"
                    else None
                )
                def write_mode_fact(name: str, payload: dict[str, object]) -> dict[str, str]:
                    fact_path = mode_root / f"{name}.json"
                    fact_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
                    return {
                        "path": str(fact_path),
                        "sha256": hashlib.sha256(fact_path.read_bytes()).hexdigest(),
                    }

                ec_matrix_fact = (
                    write_mode_fact(
                        "ec-matrix",
                        {**bindings, "entries": ec_matrix_entries},
                    )
                    if ec_matrix_entries is not None
                    else None
                )
                installed_package_fact = write_mode_fact(
                    "installed-package", installed_package_facts
                )

                mode_chronology = copy.deepcopy(chronology)
                if mode == "chronology":
                    merges = []
                    curr = head_commit
                    base_oid = "54b5eb703324a9da97d849fee9c107cbeebb0d25"
                    while curr and curr != base_oid:
                        parents = git("rev-list", "--parents", "-n", "1", curr).split()
                        if len(parents) > 2:
                            merges.append((parents[0], parents[1:]))
                        if len(parents) > 1:
                            curr = parents[1]
                        else:
                            curr = None

                    test_landing, test_candidate, test_parent = None, None, None
                    repair_landing, repair_candidate, repair_parent = None, None, None
                    contract_bug_matches = []
                    contract_bug_landing, contract_bug_candidate, contract_bug_parent = None, None, None
                    ci_evidence_landing, ci_evidence_candidate, ci_evidence_parent = None, None, None
                    seal_repair_landing, seal_repair_candidate, seal_repair_parent = None, None, None
                    impl_landing, impl_candidate, impl_parent = None, None, None
                    repair_paths = {
                        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
                        "phase-loop-runtime/tests/test_outside_agent_contract_drift.py",
                        "phase-loop-runtime/tests/_outside_agent_canonical.py",
                    }
                    contract_bug_paths = {
                        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
                        "phase-loop-runtime/tests/test_outside_agent_release_surface.py",
                        "phase-loop-runtime/tests/_outside_agent_canonical.py",
                    }
                    seal_repair_paths = {
                        "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py",
                        "phase-loop-runtime/tests/_outside_agent_canonical.py",
                    }

                    for m, parents in merges:
                        p1, p2 = parents[0], parents[1]
                        files_changed = set(git("diff", "--name-only", p1, p2).splitlines())
                        if files_changed == repair_paths:
                            repair_landing = m
                            repair_candidate = p2
                            repair_parent = p1
                        elif files_changed == contract_bug_paths:
                            contract_bug_matches.append((m, p2, p1))
                        elif files_changed == seal_repair_paths:
                            seal_repair_landing = m
                            seal_repair_candidate = p2
                            seal_repair_parent = p1
                        elif "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py" in files_changed:
                            impl_landing = m
                            impl_candidate = p2
                            impl_parent = p1
                        elif "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py" in files_changed:
                            if m != repair_landing:
                                test_landing = m
                                test_candidate = p2
                                test_parent = p1

                    if test_landing is None or test_candidate is None or test_parent is None:
                        raise ValueError("Missing required test landing/candidate/parent")
                    if repair_landing is None or repair_candidate is None or repair_parent is None:
                        raise ValueError("Missing required repair landing/candidate/parent")
                    if len(contract_bug_matches) != 2:
                        raise ValueError("Expected distinct contract-bug and CI-evidence landings")
                    (
                        (ci_evidence_landing, ci_evidence_candidate, ci_evidence_parent),
                        (contract_bug_landing, contract_bug_candidate, contract_bug_parent),
                    ) = contract_bug_matches
                    if contract_bug_landing is None or contract_bug_candidate is None or contract_bug_parent is None:
                        raise ValueError("Missing required contract-bug test landing/candidate/parent")
                    ci_evidence_parent_vector = git(
                        "rev-list", "--parents", "-n", "1", ci_evidence_landing
                    ).split()
                    if ci_evidence_parent_vector != [
                        ci_evidence_landing,
                        ci_evidence_parent,
                        ci_evidence_candidate,
                    ]:
                        raise ValueError("CI-evidence landing must have exactly two ordered parents")
                    if seal_repair_landing is None or seal_repair_candidate is None or seal_repair_parent is None:
                        raise ValueError("Missing required seal-repair test landing/candidate/parent")
                    seal_repair_parent_vector = git(
                        "rev-list", "--parents", "-n", "1", seal_repair_landing
                    ).split()
                    if seal_repair_parent_vector != [
                        seal_repair_landing,
                        seal_repair_parent,
                        seal_repair_candidate,
                    ]:
                        raise ValueError("Seal-repair landing must have exactly two ordered parents")
                    if chronology_scope == "exact_main":
                        if impl_landing is None or impl_candidate is None or impl_parent is None:
                            raise ValueError("Missing required implementation landing/candidate/parent")
                    else:
                        impl_landing, impl_candidate, impl_parent = None, None, None

                    actual_repair_landing = repair_candidate if force_forgery else repair_landing
                    actual_repair_parent = git(
                        "rev-parse", f"{actual_repair_landing}^"
                    )
                    if force_forgery:
                        assert actual_repair_landing == repair_candidate
                        assert actual_repair_parent == repair_parent

                    def capture_paths(parent: str, candidate: str, paths: set[str]) -> dict[str, dict[str, str]]:
                        result = {}
                        for path in sorted(paths):
                            before_blob = git("rev-parse", f"{parent}:{path}")
                            after_blob = git("rev-parse", f"{candidate}:{path}")
                            patch = git("diff", "--no-color", "-U0", parent, candidate, "--", path)
                            result[path] = {
                                "before_blob": before_blob,
                                "after_blob": after_blob,
                                "patch": patch,
                                "patch_digest": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                            }
                        return result

                    repair_paths_dict = capture_paths(repair_parent, repair_candidate, repair_paths)
                    contract_bug_paths_dict = capture_paths(
                        contract_bug_parent, contract_bug_candidate, contract_bug_paths
                    )
                    seal_repair_paths_dict = capture_paths(
                        seal_repair_parent, seal_repair_candidate, seal_repair_paths
                    )
                    ci_evidence_paths_dict = capture_paths(
                        ci_evidence_parent, ci_evidence_candidate, contract_bug_paths
                    )

                    original_base = "287d447c37ce51b0ab5a7498e32d6c0c78c69027"
                    original_implementation_commits = [
                        "59cbf5a167bfc8bde4e5841fd977e542158aff3d",
                        "00dec41aa950f4d1affead3a9c7fdfea4e91099e",
                        "7df3cc74ec1ba2cb3e3216624f611009dbae2eca",
                        "974593899bbecfbe092ba0aec369e69eee1aabdd",
                    ]
                    reviewed_f17ab557 = "f17ab557c46acdaf748f0b46412a99062d98c3bf"
                    reviewed_f17ab557_commits = [
                        git("rev-parse", commit).lower()
                        for commit in git(
                            "rev-list",
                            "--reverse",
                            f"{actual_repair_landing}..{reviewed_f17ab557}",
                        ).splitlines()
                    ]
                    if len(original_implementation_commits) != 4:
                        raise ValueError(
                            "original implementation equals count mismatch: "
                            f"{len(original_implementation_commits)}"
                        )
                    if not force_forgery and len(reviewed_f17ab557_commits) != 5:
                        raise ValueError(
                            "reviewed f17ab557 vector count mismatch: "
                            f"{len(reviewed_f17ab557_commits)}"
                        )
                    historical_repair_range_diff = git(
                        "range-diff",
                        "--no-color",
                        f"{original_base}..{original_implementation_commits[-1]}",
                        f"{actual_repair_landing}..{reviewed_f17ab557}",
                    )
                    orig_head = "80d9a14c94785f81044d67b60e05d61242838a1b" if compatibility_due else original_implementation_commits[-1]
                    reb_head = final_candidate if compatibility_due else candidate
                    range_diff_output = git(
                        "range-diff", "--no-color", f"{original_base}..{orig_head}",
                        f"{ci_evidence_landing}..{reb_head}",
                    )

                    if compatibility_due:
                        original_commits = [
                            *original_implementation_commits,
                            "80d9a14c94785f81044d67b60e05d61242838a1b",
                        ]
                    else:
                        original_commits = list(original_implementation_commits)

                    rebased_commits = git(
                        "rev-list", "--reverse", f"{ci_evidence_landing}..{reb_head}"
                    ).splitlines()
                    rebased_commits = [git("rev-parse", c).lower() for c in rebased_commits]

                    if compatibility_due:
                        if len(original_commits) != 5:
                            raise ValueError(f"original_commits count mismatch: {len(original_commits)}")
                        if len(rebased_commits) != 6:
                            raise ValueError(f"rebased_commits count mismatch: {len(rebased_commits)}")
                    else:
                        if len(original_commits) != 4:
                            raise ValueError(f"original_commits count mismatch: {len(original_commits)}")
                        if len(rebased_commits) not in (4, 5):
                            raise ValueError(f"rebased_commits count mismatch: {len(rebased_commits)}")

                    has_inserted = False
                    inserted_commit = None
                    if chronology_scope == "a2_candidate":
                        if len(rebased_commits) == 5:
                            has_inserted = True
                            inserted_commit = rebased_commits[4]
                        elif len(rebased_commits) == 4:
                            has_inserted = False
                            inserted_commit = None
                        else:
                            raise ValueError(f"Unexpected rebased_commits count for a2_candidate: {len(rebased_commits)}")
                    else:  # exact_main or b2_premerge
                        if len(rebased_commits) == 6:
                            has_inserted = True
                            inserted_commit = rebased_commits[4]
                        else:
                            raise ValueError(f"Unexpected rebased_commits count for {chronology_scope}: {len(rebased_commits)}")

                    if has_inserted:
                        inserted_parents = git("rev-list", "--parents", "-n", "1", inserted_commit).split()
                        if len(inserted_parents) != 2:
                            raise ValueError(f"Chronology verifier commit {inserted_commit} must have exactly one parent, got: {inserted_parents}")
                        inserted_parent = inserted_parents[1]

                        inserted_files = set(git("diff", "--name-only", inserted_parent, inserted_commit).splitlines())
                        if inserted_files != {"phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py"}:
                            raise ValueError(f"Chronology verifier commit {inserted_commit} changed unexpected files: {inserted_files}")

                        impl_patch = git("diff", "--no-color", "-U0", inserted_parent, inserted_commit, "--", "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py")
                        if not impl_patch:
                            raise ValueError(f"Chronology verifier commit {inserted_commit} has an empty patch")
                        impl_patch_digest = hashlib.sha256(impl_patch.encode("utf-8")).hexdigest()
                        if impl_patch_digest == "0" * 64 or impl_patch_digest == hashlib.sha256(b"").hexdigest() or not impl_patch_digest:
                            raise ValueError(f"Chronology verifier commit {inserted_commit} has a zero or invalid digest")
                        implementation_patch_slot = {
                            "path": "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py",
                            "patch": impl_patch,
                            "patch_digest": impl_patch_digest,
                        }
                    else:
                        implementation_patch_slot = None

                    historical_repair_transition = {
                        "base_commit": actual_repair_landing,
                        "original_commits": original_implementation_commits,
                        "rebased_commits": reviewed_f17ab557_commits,
                        "range_diff": historical_repair_range_diff,
                    }
                    contract_bug_rebase_transition = {
                        "base_commit": ci_evidence_landing,
                        "original_commits": original_commits,
                        "reviewed_f17ab557_commits": reviewed_f17ab557_commits,
                        "rebased_commits": rebased_commits,
                        "range_diff": range_diff_output,
                    }

                    red_junit_path = lifecycle["activated"]["junit_path"]
                    red_raw_log_path = lifecycle["activated"]["raw_log_path"]
                    green_junit_path = lifecycle["default"]["junit_path"]
                    green_raw_log_path = lifecycle["default"]["raw_log_path"]

                    red_junit = {
                        "path": red_junit_path,
                        "sha256": hashlib.sha256(Path(red_junit_path).read_bytes()).hexdigest(),
                    }
                    red_raw_log = {
                        "path": red_raw_log_path,
                        "sha256": hashlib.sha256(Path(red_raw_log_path).read_bytes()).hexdigest(),
                    }
                    green_junit = {
                        "path": green_junit_path,
                        "sha256": hashlib.sha256(Path(green_junit_path).read_bytes()).hexdigest(),
                    }
                    green_raw_log = {
                        "path": green_raw_log_path,
                        "sha256": hashlib.sha256(Path(green_raw_log_path).read_bytes()).hexdigest(),
                    }

                    merge_inputs = {
                        "test_landing": (test_landing, test_parent, test_candidate),
                        "repair_landing": (
                            actual_repair_landing,
                            actual_repair_parent,
                            repair_candidate,
                        ),
                        "contract_bug_test_landing": (
                            contract_bug_landing,
                            contract_bug_parent,
                            contract_bug_candidate,
                        ),
                        "seal_repair_landing": (
                            seal_repair_landing,
                            seal_repair_parent,
                            seal_repair_candidate,
                        ),
                        "ci_evidence_landing": (
                            ci_evidence_landing,
                            ci_evidence_parent,
                            ci_evidence_candidate,
                        ),
                    }
                    if chronology_scope == "exact_main":
                        assert (
                            impl_landing is not None
                            and impl_candidate is not None
                            and impl_parent is not None
                        )
                        assert impl_candidate == final_candidate
                        merge_inputs["implementation_landing"] = (
                            impl_landing,
                            impl_parent,
                            impl_candidate,
                        )
                    merge_result_trees = {}
                    for label, (landing, first_parent, candidate_parent) in merge_inputs.items():
                        recomputed_tree = git("merge-tree", "--write-tree", first_parent, candidate_parent)
                        assert recomputed_tree == git("rev-parse", f"{landing}^{{tree}}")
                        merge_result_trees[label] = recomputed_tree

                    b1_content = {
                        "paths": list(SEALED_RELEASE_FINAL_PATHS),
                        "members": {
                            path: {
                                "blob_oid": git("rev-parse", f"{final_candidate}:{path}"),
                                "sha256": hashlib.sha256(
                                    subprocess.run(
                                        ["git", "show", f"{final_candidate}:{path}"],
                                        cwd=REPO_ROOT,
                                        capture_output=True,
                                        check=True,
                                    ).stdout
                                ).hexdigest(),
                            }
                            for path in SEALED_RELEASE_FINAL_PATHS
                        },
                    }
                    if compatibility_due:
                        candidate_a2_members = {
                            path: hashlib.sha256(
                                subprocess.run(
                                    ["git", "show", f"{candidate}:{path}"],
                                    cwd=REPO_ROOT,
                                    capture_output=True,
                                    check=True,
                                ).stdout
                            ).hexdigest()
                            for path in SEALED_RELEASE_CANDIDATE_PATHS
                        }
                        canonical_a2_package_evidence = _build_a2_package_evidence(
                            candidate_commit=candidate,
                            candidate_tree=candidate_tree,
                            candidate_members=candidate_a2_members,
                            archives={
                                label: {
                                    "sha256": hashlib.sha256(
                                        mode_archives[label].read_bytes()
                                    ).hexdigest(),
                                    "members": SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS,
                                }
                                for label in PACKAGE_EXECUTION_VARIANTS
                            },
                        )

                        full_member_a2_package_evidence = _build_a2_package_evidence(
                            candidate_commit=candidate,
                            candidate_tree=candidate_tree,
                            candidate_members=candidate_a2_members,
                            archives={
                                label: {
                                    "sha256": hashlib.sha256(
                                        mode_archives[label].read_bytes()
                                    ).hexdigest(),
                                    "members": _normalized_archive_member_digests(
                                        mode_archives[label]
                                    ),
                                }
                                for label in PACKAGE_EXECUTION_VARIANTS
                            },
                        )
                        assert all(
                            set(
                                full_member_a2_package_evidence["archives"][label][
                                    "members"
                                ]
                            )
                            > set(SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS)
                            for label in PACKAGE_EXECUTION_VARIANTS
                        )
                        assert (
                            full_member_a2_package_evidence
                            != canonical_a2_package_evidence
                        )
                        assert (
                            full_member_a2_package_evidence[
                                "a2_package_evidence_sha256"
                            ]
                            != canonical_a2_package_evidence[
                                "a2_package_evidence_sha256"
                            ]
                        )

                        def sealed_b1_package_evidence() -> dict[str, object]:
                            return _build_a2_package_evidence(
                                candidate_commit=candidate,
                                candidate_tree=candidate_tree,
                                candidate_members=candidate_a2_members,
                                archives={
                                    label: {
                                        "sha256": hashlib.sha256(
                                            mode_archives[label].read_bytes()
                                        ).hexdigest(),
                                        "members": SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS,
                                    }
                                    for label in PACKAGE_EXECUTION_VARIANTS
                                },
                            )

                        b1_sealed_package_evidence = sealed_b1_package_evidence()
                        b1_sealed_package_evidence_again = sealed_b1_package_evidence()
                        assert (
                            b1_sealed_package_evidence
                            == b1_sealed_package_evidence_again
                        )
                        assert b1_sealed_package_evidence == canonical_a2_package_evidence
                        assert (
                            b1_sealed_package_evidence["a2_package_evidence_sha256"]
                            == canonical_a2_package_evidence[
                                "a2_package_evidence_sha256"
                            ]
                        )
                        b1_candidate_documents = {
                            path: subprocess.run(
                                ["git", "show", f"{candidate}:{path}"],
                                cwd=REPO_ROOT,
                                capture_output=True,
                                check=True,
                            ).stdout
                            for path in SEALED_RELEASE_FINAL_PATHS
                        }
                        b1_candidate_documents_again = {
                            path: subprocess.run(
                                ["git", "show", f"{candidate}:{path}"],
                                cwd=REPO_ROOT,
                                capture_output=True,
                                check=True,
                            ).stdout
                            for path in SEALED_RELEASE_FINAL_PATHS
                        }
                        assert b1_candidate_documents == b1_candidate_documents_again
                        b1_rendered_documents = {
                            path: _render_b1_document_bytes(
                                path,
                                b1_candidate_documents[path],
                                candidate_commit=candidate,
                                candidate_tree=candidate_tree,
                                sealed_package_evidence=b1_sealed_package_evidence,
                            )
                            for path in SEALED_RELEASE_FINAL_PATHS
                        }
                        b1_rendered_documents_again = {
                            path: _render_b1_document_bytes(
                                path,
                                b1_candidate_documents_again[path],
                                candidate_commit=candidate,
                                candidate_tree=candidate_tree,
                                sealed_package_evidence=b1_sealed_package_evidence_again,
                            )
                            for path in SEALED_RELEASE_FINAL_PATHS
                        }
                        assert b1_rendered_documents == b1_rendered_documents_again
                        candidate_only_values = {
                            "final_commit": final_candidate,
                            "final_tree": final_candidate_tree,
                            "final_candidate": final_candidate,
                            "final_candidate_tree": final_candidate_tree,
                        }
                        if chronology_scope == "exact_main":
                            assert impl_landing is not None and impl_parent is not None
                            candidate_only_values.update(
                                {
                                    "implementation_landing": impl_landing,
                                    "implementation_landing_tree": git(
                                        "rev-parse", f"{impl_landing}^{{tree}}"
                                    ),
                                    "implementation_parent": impl_parent,
                                    "canonical_main_head": head_commit,
                                    "canonical_main_head_tree": head_tree,
                                }
                            )
                        assert all(value != candidate for value in candidate_only_values.values())
                        assert all(
                            value != candidate_tree
                            for value in candidate_only_values.values()
                        )
                        candidate_only_documents = {}
                        for path in SEALED_RELEASE_FINAL_PATHS:
                            actual_document = subprocess.run(
                                ["git", "show", f"{final_candidate}:{path}"],
                                cwd=REPO_ROOT,
                                capture_output=True,
                                check=True,
                            ).stdout
                            expected_document = b1_rendered_documents[path]
                            assert actual_document == expected_document
                            assert_candidate_identity_only_document(
                                expected_document.decode("utf-8"),
                                candidate_commit=candidate,
                                candidate_tree=candidate_tree,
                                forbidden_identity_values=candidate_only_values,
                                anchor="CONFORM_RED::b1_candidate_identity_only",
                                require_candidate_identity=(
                                    path in B1_CANDIDATE_IDENTITY_PATHS
                                ),
                            )
                            candidate_only_documents[path] = {
                                "candidate_commit": candidate,
                                "candidate_tree": candidate_tree,
                                "forbidden_identity_values": candidate_only_values,
                            }
                        assert set(candidate_only_documents) == set(
                            SEALED_RELEASE_FINAL_PATHS
                        )
                        b1_content["rendering"] = {
                            "template": "accepted-80d9a14-candidate-only-b2",
                            "accepted_document_commit": B1_ACCEPTED_DOCUMENT_COMMIT,
                            "candidate_commit": candidate,
                            "candidate_tree": candidate_tree,
                            "package_evidence": b1_sealed_package_evidence,
                            "documents": {
                                path: {
                                    "candidate_sha256": hashlib.sha256(
                                        b1_candidate_documents[path]
                                    ).hexdigest(),
                                    "body": b1_rendered_documents[path].decode("utf-8"),
                                    "sha256": hashlib.sha256(
                                        b1_rendered_documents[path]
                                    ).hexdigest(),
                                }
                                for path in SEALED_RELEASE_FINAL_PATHS
                            },
                        }
                        b1_content["candidate_only_documents"] = candidate_only_documents

                    identities = {
                        "test_parent": test_parent,
                        "test_parent_tree": git("rev-parse", f"{test_parent}^{{tree}}"),
                        "test_candidate": test_candidate,
                        "test_candidate_tree": git("rev-parse", f"{test_candidate}^{{tree}}"),
                        "test_landing": test_landing,
                        "test_landing_tree": git("rev-parse", f"{test_landing}^{{tree}}"),
                        "repair_parent": actual_repair_parent,
                        "repair_parent_tree": git("rev-parse", f"{actual_repair_parent}^{{tree}}"),
                        "repair_candidate": repair_candidate,
                        "repair_candidate_tree": git("rev-parse", f"{repair_candidate}^{{tree}}"),
                        "repair_landing": actual_repair_landing,
                        "repair_landing_tree": git("rev-parse", f"{actual_repair_landing}^{{tree}}"),
                        "contract_bug_test_parent": contract_bug_parent,
                        "contract_bug_test_parent_tree": git("rev-parse", f"{contract_bug_parent}^{{tree}}"),
                        "contract_bug_test_candidate": contract_bug_candidate,
                        "contract_bug_test_candidate_tree": git("rev-parse", f"{contract_bug_candidate}^{{tree}}"),
                        "contract_bug_test_landing": contract_bug_landing,
                        "contract_bug_test_landing_tree": git("rev-parse", f"{contract_bug_landing}^{{tree}}"),
                        "seal_repair_parent": seal_repair_parent,
                        "seal_repair_parent_tree": git("rev-parse", f"{seal_repair_parent}^{{tree}}"),
                        "seal_repair_candidate": seal_repair_candidate,
                        "seal_repair_candidate_tree": git("rev-parse", f"{seal_repair_candidate}^{{tree}}"),
                        "seal_repair_landing": seal_repair_landing,
                        "seal_repair_landing_tree": git("rev-parse", f"{seal_repair_landing}^{{tree}}"),
                        "ci_evidence_parent": ci_evidence_parent,
                        "ci_evidence_parent_tree": git("rev-parse", f"{ci_evidence_parent}^{{tree}}"),
                        "ci_evidence_candidate": ci_evidence_candidate,
                        "ci_evidence_candidate_tree": git("rev-parse", f"{ci_evidence_candidate}^{{tree}}"),
                        "ci_evidence_landing": ci_evidence_landing,
                        "ci_evidence_landing_tree": git("rev-parse", f"{ci_evidence_landing}^{{tree}}"),
                        "candidate_commit": candidate,
                        "candidate_tree": candidate_tree,
                        "final_candidate": final_candidate,
                        "final_candidate_tree": final_candidate_tree,
                    }
                    parent_vectors = {
                        "test_landing": git("rev-list", "--parents", "-n", "1", test_landing).split()[1:],
                        "repair_landing": git("rev-list", "--parents", "-n", "1", actual_repair_landing).split()[1:],
                        "contract_bug_test_landing": git("rev-list", "--parents", "-n", "1", contract_bug_landing).split()[1:],
                        "seal_repair_landing": seal_repair_parent_vector[1:],
                        "ci_evidence_landing": ci_evidence_parent_vector[1:],
                    }
                    if chronology_scope in {"a2_candidate", "exact_main"}:
                        identities.update(
                            {
                                "canonical_main_head": head_commit,
                                "canonical_main_head_tree": head_tree,
                            }
                        )
                    if chronology_scope == "exact_main":
                        assert impl_parent is not None and impl_landing is not None
                        identities.update(
                            {
                                "implementation_parent": impl_parent,
                                "implementation_parent_tree": git("rev-parse", f"{impl_parent}^{{tree}}"),
                                "implementation_landing": impl_landing,
                                "implementation_landing_tree": git("rev-parse", f"{impl_landing}^{{tree}}"),
                            }
                        )
                        parent_vectors["implementation_landing"] = git(
                            "rev-list", "--parents", "-n", "1", impl_landing
                        ).split()[1:]

                    git_proof = {
                        "identities": identities,
                        "parent_vectors": parent_vectors,
                        "merge_result_trees": merge_result_trees,
                        "repair_landing_two_parent": True,
                        "repair_diff_exact": True,
                        "single_rebase": True,
                        "range_diff_equivalent": True,
                        "repair_paths": repair_paths_dict,
                        "contract_bug_paths": contract_bug_paths_dict,
                        "seal_repair_paths": seal_repair_paths_dict,
                        "ci_evidence_paths": ci_evidence_paths_dict,
                        "implementation_patch_slot": implementation_patch_slot,
                        "b1_content": b1_content,
                        "transition": contract_bug_rebase_transition,
                        "historical_repair_transition": historical_repair_transition,
                        "contract_bug_rebase_transition": contract_bug_rebase_transition,
                        "red_references": {
                            "junit": red_junit,
                            "raw_log": red_raw_log,
                        },
                        "green_references": {
                            "junit": green_junit,
                            "raw_log": green_raw_log,
                        },
                    }
                    mode_chronology["git_proof"] = git_proof

                mode_exclusive_facts: dict[str, dict[str, object]] = {
                    "chronology": {
                        "chronology": mode_chronology
                    },
                    "corpus": {
                        "fixture_manifest": write_mode_fact(
                            "fixture-manifest",
                            {
                                "fixture_root": "outside_agent_contract_v0_2_1",
                                "source_repo": "Consiliency/spec",
                                "source_ref": "v0.2.1",
                                "source_commit": "b862f977897a7b87c4419680a3e83735d4ff07b0",
                                "manifest_sha256": hashlib.sha256(
                                    (FIXTURE_ROOT / "test-vectors/outside-agent/manifest.json").read_bytes()
                                ).hexdigest(),
                                "rows": corpus_rows,
                                "partitions": corpus_partitions,
                            },
                        )
                    },
                    "package": {
                        "direct_wheel": {
                            "path": str(mode_archives["direct-wheel"]),
                            "sha256": hashlib.sha256(
                                mode_archives["direct-wheel"].read_bytes()
                            ).hexdigest(),
                            "contract_members": contract_member_digests,
                            "provenance": {
                                "candidate_commit": candidate,
                                "candidate_tree": candidate_tree,
                                "source_repo": "Consiliency/spec",
                                "source_ref": "v0.2.1",
                                "source_commit": "b862f977897a7b87c4419680a3e83735d4ff07b0",
                            },
                        },
                        "direct_sdist": {
                            "path": str(mode_archives["direct-sdist"]),
                            "sha256": hashlib.sha256(
                                mode_archives["direct-sdist"].read_bytes()
                            ).hexdigest(),
                            "contract_members": contract_member_digests,
                            "provenance": {
                                "candidate_commit": candidate,
                                "candidate_tree": candidate_tree,
                                "source_repo": "Consiliency/spec",
                                "source_ref": "v0.2.1",
                                "source_commit": "b862f977897a7b87c4419680a3e83735d4ff07b0",
                            },
                        },
                        "sdist_derived_wheel": {
                            "path": str(mode_archives["sdist-derived-wheel"]),
                            "sha256": hashlib.sha256(
                                mode_archives["sdist-derived-wheel"].read_bytes()
                            ).hexdigest(),
                            "contract_members": contract_member_digests,
                            "provenance": {
                                "candidate_commit": candidate,
                                "candidate_tree": candidate_tree,
                                "source_repo": "Consiliency/spec",
                                "source_ref": "v0.2.1",
                                "source_commit": "b862f977897a7b87c4419680a3e83735d4ff07b0",
                            },
                        },
                    },
                    "compatibility": {},
                }
                runner_manifest_facts = {
                    "owner": "phase-loop-runner",
                    "evidence_mode": mode,
                    "candidate_commit": candidate,
                    "candidate_tree": candidate_tree,
                    "head_commit": head_commit,
                    "head_tree": head_tree,
                    "module_path": facts["module_path"],
                    "corpus_partitions": corpus_partitions,
                    "contract_member_digests": contract_member_digests,
                    "candidate_head_module": bindings,
                    "provenance": vendor,
                    "lifecycle": lifecycle,
                    "activated_lifecycle": activated_lifecycle,
                    "mutation_records": mutation_records,
                    "chronology": mode_chronology,
                    "package": package_facts,
                    "installed_package": installed_package_facts,
                    "corpus": {
                        "rows": corpus_rows,
                        "partitions": corpus_partitions,
                    },
                }
                if ec_matrix_entries is not None:
                    runner_manifest_facts["ec_matrix"] = {
                        "entries": ec_matrix_entries
                    }
                mode_facts = copy.deepcopy(facts)
                mode_facts.update(
                    {
                        "runner_manifest": write_mode_fact(
                            "runner-manifest",
                            runner_manifest_facts,
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
                        "installed_package": installed_package_fact,
                        **(
                            {"ec_matrix": ec_matrix_fact}
                            if ec_matrix_fact is not None
                            else {}
                        ),
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
                junit_suite = (
                    junit_root
                    if junit_root.tag == "testsuite"
                    else junit_root.find("testsuite")
                )
                assert junit_suite is not None
                outcome_facts = {
                    "junit": {
                        "tests": int(junit_suite.attrib["tests"]),
                        "failures": int(junit_suite.attrib["failures"]),
                        "skipped": int(junit_suite.attrib["skipped"]),
                        "cases": [
                            {
                                "name": case.attrib["name"],
                                "outcome": (
                                    "failed"
                                    if case.find("failure") is not None
                                    else "skipped"
                                    if case.find("skipped") is not None
                                    else "passed"
                                ),
                            }
                            for case in junit_suite.findall(".//testcase")
                        ],
                    },
                    "archive_members": {
                        name: _normalized_archive_member_digests(Path(details["path"]))
                        for name, details in mode_facts["archives"].items()
                    },
                    "mutations": mode_facts["mutation_records"],
                    "package_executions": json.loads(
                        Path(mode_facts["installed_package"]["path"]).read_text(
                            encoding="utf-8"
                        )
                    )["executions"],
                }
                if mode == "compatibility":
                    outcome_facts["ec_matrix"] = json.loads(
                        Path(mode_facts["ec_matrix"]["path"]).read_text(
                            encoding="utf-8"
                        )
                    )["entries"]
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

            for mode in executable_modes:
                mode_records, artifacts = records_for(mode)
                _assert_full_frozen_evidence_input(mode, mode_records)
                expected_input, expected_evidence = expected_digests(mode_records)
                verified = verifier(mode, mode_records)
                assert set(verified) == set(EVIDENCE_VERIFIER_INTERFACE[mode]["outputs"])
                assert verified["mode"] == mode
                assert verified["candidate_commit"] == candidate
                assert verified["head_commit"] == head_commit
                assert verified["module_path"] == facts["module_path"]
                assert verified["recomputed_input_digest"] == expected_input
                assert verified["recomputed_evidence_digest"] == expected_evidence
                assert isinstance(verified["evidence"], dict)
                if mode == "chronology":
                    git_proof = verified["evidence"]["chronology"]["git_proof"]
                    for key in ("red_references", "green_references"):
                        refs = git_proof[key]
                        assert set(refs) == {"junit", "raw_log"}
                        for ref in refs.values():
                            assert isinstance(ref, dict) and set(ref) == {"path", "sha256"}
                            assert isinstance(ref["path"], str) and ref["path"]
                            assert (
                                isinstance(ref["sha256"], str)
                                and len(ref["sha256"]) == 64
                                and set(ref["sha256"]) <= set("0123456789abcdef")
                                and ref["sha256"] != "0" * 64
                            )
                    identities = git_proof["identities"]
                    parent_vectors = git_proof["parent_vectors"]
                    merge_result_trees = git_proof["merge_result_trees"]
                    assert set(parent_vectors) == {
                        "test_landing",
                        "repair_landing",
                        "contract_bug_test_landing",
                        "seal_repair_landing",
                        "ci_evidence_landing",
                        *(
                            {"implementation_landing"}
                            if chronology_scope == "exact_main"
                            else set()
                        ),
                    }
                    assert set(merge_result_trees) == set(parent_vectors)
                    assert all(
                        isinstance(tree, str)
                        and len(tree) == 40
                        and set(tree) <= set("0123456789abcdef")
                        for tree in merge_result_trees.values()
                    )
                    historical_transition = git_proof["historical_repair_transition"]
                    contract_bug_transition = git_proof[
                        "contract_bug_rebase_transition"
                    ]
                    assert git_proof["transition"] == contract_bug_transition
                    assert historical_transition["base_commit"] == identities[
                        "repair_landing"
                    ]
                    assert contract_bug_transition["base_commit"] == identities[
                        "ci_evidence_landing"
                    ]
                    assert len(historical_transition["original_commits"]) == 4
                    assert len(contract_bug_transition["original_commits"][:4]) == 4
                    assert (
                        contract_bug_transition["reviewed_f17ab557_commits"]
                        == historical_transition["rebased_commits"]
                    )
                    assert len(contract_bug_transition["rebased_commits"]) == (
                        6 if compatibility_due else 4
                    ) or (
                        not compatibility_due
                        and len(contract_bug_transition["rebased_commits"]) == 5
                    )
                    if compatibility_due:
                        b1_content = git_proof["b1_content"]
                        candidate_only_documents = b1_content[
                            "candidate_only_documents"
                        ]
                        assert set(candidate_only_documents) == set(
                            SEALED_RELEASE_FINAL_PATHS
                        )
                        b1_rendering = b1_content["rendering"]
                        assert set(b1_rendering) == {
                            "template",
                            "accepted_document_commit",
                            "candidate_commit",
                            "candidate_tree",
                            "package_evidence",
                            "documents",
                        }
                        assert (
                            b1_rendering["template"]
                            == "accepted-80d9a14-candidate-only-b2"
                        )
                        assert (
                            b1_rendering["accepted_document_commit"]
                            == B1_ACCEPTED_DOCUMENT_COMMIT
                        )
                        assert b1_rendering["candidate_commit"] == candidate
                        assert b1_rendering["candidate_tree"] == candidate_tree
                        package_evidence = b1_rendering["package_evidence"]
                        assert isinstance(package_evidence, dict)
                        assert package_evidence[
                            "a2_package_evidence_sha256"
                        ] == _a2_package_evidence_sha256(
                            package_evidence
                        )
                        rendered_documents = b1_rendering["documents"]
                        assert set(rendered_documents) == set(SEALED_RELEASE_FINAL_PATHS)
                        for path in SEALED_RELEASE_FINAL_PATHS:
                            document = candidate_only_documents[path]
                            assert set(document) == {
                                "candidate_commit",
                                "candidate_tree",
                                "forbidden_identity_values",
                            }
                            assert document["candidate_commit"] == candidate
                            assert document["candidate_tree"] == candidate_tree
                            assert isinstance(
                                document["forbidden_identity_values"], dict
                            )
                            rendered = rendered_documents[path]
                            assert set(rendered) == {
                                "candidate_sha256",
                                "body",
                                "sha256",
                            }
                            candidate_document = subprocess.run(
                                ["git", "show", f"{candidate}:{path}"],
                                cwd=REPO_ROOT,
                                capture_output=True,
                                check=True,
                            ).stdout
                            expected_document = _render_b1_document_bytes(
                                path,
                                candidate_document,
                                candidate_commit=candidate,
                                candidate_tree=candidate_tree,
                                sealed_package_evidence=package_evidence,
                            )
                            assert rendered["candidate_sha256"] == hashlib.sha256(
                                candidate_document
                            ).hexdigest()
                            assert rendered["body"].encode("utf-8") == expected_document
                            assert rendered["sha256"] == hashlib.sha256(
                                expected_document
                            ).hexdigest()
                            assert subprocess.run(
                                ["git", "show", f"{final_candidate}:{path}"],
                                cwd=REPO_ROOT,
                                capture_output=True,
                                check=True,
                            ).stdout == expected_document
                            assert_candidate_identity_only_document(
                                rendered["body"],
                                candidate_commit=candidate,
                                candidate_tree=candidate_tree,
                                forbidden_identity_values=document[
                                    "forbidden_identity_values"
                                ],
                                anchor="CONFORM_RED::b1_candidate_identity_only",
                                require_candidate_identity=(
                                    path in B1_CANDIDATE_IDENTITY_PATHS
                                ),
                            )
                    implementation_identity_keys = {
                        "implementation_parent",
                        "implementation_parent_tree",
                        "implementation_landing",
                        "implementation_landing_tree",
                        "canonical_main_head",
                        "canonical_main_head_tree",
                    }
                    legacy_a2_identity_keys = {
                        "canonical_main_head",
                        "canonical_main_head_tree",
                    }
                    if chronology_scope == "b2_premerge":
                        assert not implementation_identity_keys & set(identities)
                        final_doc_topology = verified["evidence"]["chronology"][
                            "stages"
                        ][-1]["topology"]
                        assert not {
                            "canonical_main_head",
                            "canonical_main_head_tree",
                            "implementation_parent",
                            "implementation_parent_tree",
                            "implementation_landing",
                            "implementation_landing_tree",
                        } & set(final_doc_topology)
                    elif chronology_scope == "a2_candidate":
                        assert legacy_a2_identity_keys <= set(identities)
                        assert identities["canonical_main_head"] == head_commit
                        assert identities["canonical_main_head_tree"] == head_tree
                    elif chronology_scope == "exact_main":
                        assert implementation_identity_keys <= set(identities)
                        assert all(
                            isinstance(identities[key], str) and identities[key]
                            for key in implementation_identity_keys
                        )
                        final_doc_topology = verified["evidence"]["chronology"][
                            "stages"
                        ][-1]["topology"]
                        assert isinstance(final_doc_topology["canonical_main_head"], str)
                        assert final_doc_topology["canonical_main_head"] == head_commit
                else:
                    assert "raw_log" not in json.dumps(
                        verified["evidence"], sort_keys=True
                    )
                evidence = verified["evidence"]
                assert EVIDENCE_SEMANTIC_OUTPUT_KEYS <= set(evidence)
                assert ("ec_matrix" in evidence) == (mode == "compatibility")
                assert evidence["vendor"] == vendor
                assert evidence["bindings"] == {
                    "candidate_commit": candidate,
                    "candidate_tree": candidate_tree,
                    "head_commit": head_commit,
                    "head_tree": head_tree,
                    "module_path": facts["module_path"],
                }
                expected_chronology_stages = [
                    "preimplementation_red",
                    "postimplementation_pre_doc",
                ]
                if compatibility_due:
                    expected_chronology_stages.append("final_doc_chronology")
                assert evidence["chronology"]["scope"] == chronology_scope
                assert [stage["stage"] for stage in evidence["chronology"]["stages"]] == expected_chronology_stages
                assert evidence["corpus"]["rows"] == corpus_rows
                assert evidence["corpus"]["partitions"] == corpus_partitions
                assert evidence["package"]["contract_members"] == contract_member_digests
                assert evidence["package"]["artifact_provenance"] == bindings
                assert set(evidence["installed_package"]) == {
                    "package",
                    "module_path",
                    "variants",
                    "contract_members",
                    "corpus_partitions",
                    "executions",
                }
                verified_facts = json.loads(
                    Path(mode_records[0]["artifact_path"]).read_text(encoding="utf-8")
                )
                _assert_complete_package_executions(
                    evidence["installed_package"]["executions"],
                    verified_facts["archives"],
                )
                if mode == "compatibility":
                    _assert_complete_ec_observables(evidence["ec_matrix"]["entries"])
                assert evidence["mode_specific"] == {
                    "mode": mode,
                    "required_inputs": list(EVIDENCE_MODE_EXCLUSIVE_INPUTS[mode]),
                }
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
                for forged_field, forged_value in (
                    ("candidate_commit", "0" * 40),
                    ("candidate_tree", "0" * 40),
                    ("argv", ["python3", "-m", "pytest", "forged"]),
                ):
                    forged_facts = copy.deepcopy(mode_facts)
                    forged_facts[forged_field] = forged_value
                    Path(mode_records[0]["artifact_path"]).write_text(
                        json.dumps(forged_facts, sort_keys=True), encoding="utf-8"
                    )
                    refresh_mode_records(mode_records, artifacts)
                    with pytest.raises((ValueError, AssertionError)):
                        verifier(mode, mode_records)
                    assert_production_cli_rejects(mode_records)
                Path(mode_records[0]["artifact_path"]).write_text(
                    json.dumps(mode_facts, sort_keys=True), encoding="utf-8"
                )
                refresh_mode_records(mode_records, artifacts)
                if mode == "chronology":
                    verifier_source = Path(verifier_spec.origin).read_text(encoding="utf-8")
                    range_diff_calls = [
                        call
                        for call in ast.walk(ast.parse(verifier_source))
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "_run_git"
                        and call.args
                        and isinstance(call.args[0], ast.List)
                        and call.args[0].elts
                        and isinstance(call.args[0].elts[0], ast.Constant)
                        and call.args[0].elts[0].value == "range-diff"
                    ]
                    assert any(
                        any(
                            isinstance(argument, ast.Constant)
                            and argument.value == "--no-color"
                            for argument in call.args[0].elts
                        )
                        for call in range_diff_calls
                    ), "CONFORM_RED::range_diff_requires_no_color"
                    chronology_mutations = []
                    missing_review = copy.deepcopy(mode_facts)
                    missing_review["chronology"]["stages"][0].pop("review")
                    chronology_mutations.append(missing_review)
                    forged_topology = copy.deepcopy(mode_facts)
                    forged_topology["chronology"]["stages"][1]["topology"][
                        "candidate_descends_from_test_candidate"
                    ] = False
                    chronology_mutations.append(forged_topology)
                    if compatibility_due:
                        missing_final = copy.deepcopy(mode_facts)
                        missing_final["chronology"]["stages"].pop()
                        chronology_mutations.append(missing_final)
                        forged_b0 = copy.deepcopy(mode_facts)
                        forged_b0["chronology"]["stages"][2]["b0"][
                            "failing_node_ids"
                        ] = []
                        chronology_mutations.append(forged_b0)
                        forged_b2 = copy.deepcopy(mode_facts)
                        forged_b2["chronology"]["stages"][2]["b2"]["argv"] = A2_COMMAND
                        chronology_mutations.append(forged_b2)
                        aliased_candidates = copy.deepcopy(mode_facts)
                        aliased_candidates["chronology"]["stages"][2]["topology"][
                            "final_candidate"
                        ] = candidate
                        chronology_mutations.append(aliased_candidates)
                        forged_b0_commit = copy.deepcopy(mode_facts)
                        forged_b0_commit["chronology"]["stages"][2]["b0"][
                            "commit"
                        ] = final_candidate
                        chronology_mutations.append(forged_b0_commit)
                        forged_b1_transition = copy.deepcopy(mode_facts)
                        forged_b1_transition["chronology"]["stages"][2]["b1"][
                            "before_commit"
                        ] = final_candidate
                        chronology_mutations.append(forged_b1_transition)
                        missing_contract_bug_repair = copy.deepcopy(mode_facts)
                        missing_contract_bug_repair["chronology"]["git_proof"].pop(
                            "contract_bug_paths"
                        )
                        chronology_mutations.append(missing_contract_bug_repair)
                        missing_contract_bug_landing = copy.deepcopy(mode_facts)
                        missing_contract_bug_landing["chronology"]["git_proof"][
                            "identities"
                        ].pop("contract_bug_test_landing")
                        missing_contract_bug_landing["chronology"]["git_proof"][
                            "parent_vectors"
                        ].pop("contract_bug_test_landing")
                        chronology_mutations.append(missing_contract_bug_landing)
                        missing_seal_repair = copy.deepcopy(mode_facts)
                        missing_seal_repair["chronology"]["git_proof"].pop(
                            "seal_repair_paths"
                        )
                        chronology_mutations.append(missing_seal_repair)
                        missing_seal_repair_landing = copy.deepcopy(mode_facts)
                        missing_seal_repair_landing["chronology"]["git_proof"][
                            "identities"
                        ].pop("seal_repair_landing")
                        missing_seal_repair_landing["chronology"]["git_proof"][
                            "parent_vectors"
                        ].pop("seal_repair_landing")
                        chronology_mutations.append(missing_seal_repair_landing)
                        missing_ci_evidence = copy.deepcopy(mode_facts)
                        missing_ci_evidence["chronology"]["git_proof"].pop(
                            "ci_evidence_paths"
                        )
                        chronology_mutations.append(missing_ci_evidence)
                        missing_ci_evidence_landing = copy.deepcopy(mode_facts)
                        missing_ci_evidence_landing["chronology"]["git_proof"][
                            "identities"
                        ].pop("ci_evidence_landing")
                        missing_ci_evidence_landing["chronology"]["git_proof"][
                            "parent_vectors"
                        ].pop("ci_evidence_landing")
                        chronology_mutations.append(missing_ci_evidence_landing)
                        forged_merge_result = copy.deepcopy(mode_facts)
                        forged_merge_result["chronology"]["git_proof"][
                            "merge_result_trees"
                        ]["repair_landing"] = candidate_tree
                        chronology_mutations.append(forged_merge_result)
                        forged_seal_merge_result = copy.deepcopy(mode_facts)
                        forged_seal_merge_result["chronology"]["git_proof"][
                            "merge_result_trees"
                        ]["seal_repair_landing"] = candidate_tree
                        chronology_mutations.append(forged_seal_merge_result)
                        forged_ci_evidence_merge_result = copy.deepcopy(mode_facts)
                        forged_ci_evidence_merge_result["chronology"]["git_proof"][
                            "merge_result_trees"
                        ]["ci_evidence_landing"] = candidate_tree
                        chronology_mutations.append(forged_ci_evidence_merge_result)
                        forged_b1_content = copy.deepcopy(mode_facts)
                        b1_members = forged_b1_content["chronology"]["git_proof"][
                            "b1_content"
                        ]["members"]
                        forged_b1_path = SEALED_RELEASE_FINAL_PATHS[0]
                        alternate_b1_blob_oid = git(
                            "rev-parse",
                            f"{candidate}:phase-loop-runtime/tests/_outside_agent_canonical.py",
                        )
                        alternate_b1_sha256 = hashlib.sha256(
                            subprocess.run(
                                [
                                    "git",
                                    "show",
                                    f"{candidate}:phase-loop-runtime/tests/_outside_agent_canonical.py",
                                ],
                                cwd=REPO_ROOT,
                                capture_output=True,
                                check=True,
                            ).stdout
                        ).hexdigest()
                        assert alternate_b1_blob_oid != b1_members[forged_b1_path][
                            "blob_oid"
                        ]
                        assert alternate_b1_sha256 != b1_members[forged_b1_path][
                            "sha256"
                        ]
                        assert alternate_b1_blob_oid != "0" * 40
                        assert alternate_b1_sha256 != "0" * 64
                        b1_members[forged_b1_path]["blob_oid"] = alternate_b1_blob_oid
                        b1_members[forged_b1_path]["sha256"] = alternate_b1_sha256
                        chronology_mutations.append(forged_b1_content)
                        forged_b1_body = copy.deepcopy(mode_facts)
                        rendered_b1_document = forged_b1_body["chronology"][
                            "git_proof"
                        ]["b1_content"]["rendering"]["documents"][forged_b1_path]
                        original_b1_body = rendered_b1_document["body"]
                        wrong_b1_body = (
                            original_b1_body
                            + "\n<!-- candidate-only prose variant -->\n"
                        )
                        assert wrong_b1_body != original_b1_body
                        assert_candidate_identity_only_document(
                            wrong_b1_body,
                            candidate_commit=candidate,
                            candidate_tree=candidate_tree,
                            forbidden_identity_values=forged_b1_body["chronology"][
                                "git_proof"
                            ]["b1_content"]["candidate_only_documents"][
                                forged_b1_path
                            ]["forbidden_identity_values"],
                            anchor="CONFORM_RED::b1_candidate_identity_only",
                            require_candidate_identity=(
                                forged_b1_path in B1_CANDIDATE_IDENTITY_PATHS
                            ),
                        )
                        actual_b1_body = subprocess.run(
                            ["git", "show", f"{final_candidate}:{forged_b1_path}"],
                            cwd=REPO_ROOT,
                            capture_output=True,
                            check=True,
                        ).stdout
                        assert actual_b1_body == original_b1_body.encode("utf-8")
                        assert actual_b1_body != wrong_b1_body.encode("utf-8")
                        rendered_b1_document["body"] = wrong_b1_body
                        rendered_b1_document["sha256"] = hashlib.sha256(
                            wrong_b1_body.encode("utf-8")
                        ).hexdigest()
                        chronology_mutations.append(forged_b1_body)
                        if chronology_scope == "b2_premerge":
                            forged_premerge_exact_main = copy.deepcopy(mode_facts)
                            forged_premerge_exact_main["chronology"]["stages"][2][
                                "topology"
                            ]["canonical_main_head"] = head_commit
                            chronology_mutations.append(forged_premerge_exact_main)
                        if chronology_scope == "exact_main":
                            missing_exact_main_identity = copy.deepcopy(mode_facts)
                            missing_exact_main_identity["chronology"]["git_proof"][
                                "identities"
                            ]["implementation_landing"] = None
                            chronology_mutations.append(missing_exact_main_identity)
                            null_exact_main_topology = copy.deepcopy(mode_facts)
                            null_exact_main_topology["chronology"]["stages"][2][
                                "topology"
                            ]["canonical_main_head"] = None
                            chronology_mutations.append(null_exact_main_topology)
                            forged_exact_main_identity = copy.deepcopy(mode_facts)
                            forged_exact_main_identity["chronology"]["git_proof"][
                                "identities"
                            ]["canonical_main_head"] = forged_exact_main_identity[
                                "chronology"
                            ]["git_proof"]["identities"]["contract_bug_test_landing"]
                            chronology_mutations.append(forged_exact_main_identity)
                            forged_exact_main_vector = copy.deepcopy(mode_facts)
                            forged_exact_main_vector["chronology"]["git_proof"][
                                "parent_vectors"
                            ]["implementation_landing"] = forged_exact_main_vector[
                                "chronology"
                            ]["git_proof"]["parent_vectors"]["contract_bug_test_landing"]
                            chronology_mutations.append(forged_exact_main_vector)
                    for forged_facts in chronology_mutations:
                        Path(mode_records[0]["artifact_path"]).write_text(
                            json.dumps(forged_facts, sort_keys=True), encoding="utf-8"
                        )
                        refresh_mode_records(mode_records, artifacts)
                        with pytest.raises((ValueError, AssertionError)):
                            verifier(mode, mode_records)
                        assert_production_cli_rejects(mode_records)
                    Path(mode_records[0]["artifact_path"]).write_text(
                        json.dumps(mode_facts, sort_keys=True), encoding="utf-8"
                    )
                    refresh_mode_records(mode_records, artifacts)
                if mode == "corpus":
                    forged_facts = copy.deepcopy(mode_facts)
                    forged_rows = copy.deepcopy(forged_facts["corpus"]["rows"])
                    forged_row = next(
                        row
                        for row in forged_rows
                        if row["case_id"] == "negative-missing-digest"
                    )
                    assert forged_row["expected_valid"] is False
                    canonical_blocker_classes = {
                        row["expected_blocker_class"] for row in corpus_rows
                    }
                    replacement_blocker_class = next(
                        row["expected_blocker_class"]
                        for row in corpus_rows
                        if row["expected_valid"] is False
                        and row["expected_blocker_class"]
                        != forged_row["expected_blocker_class"]
                    )
                    assert replacement_blocker_class in canonical_blocker_classes
                    forged_row["expected_blocker_class"] = replacement_blocker_class
                    forged_facts["corpus"]["rows"] = forged_rows
                    fixture_reference = forged_facts["fixture_manifest"]
                    fixture_path = Path(fixture_reference["path"])
                    installed_reference = forged_facts["installed_package"]
                    installed_path = Path(installed_reference["path"])
                    runner_reference = forged_facts["runner_manifest"]
                    runner_path = Path(runner_reference["path"])
                    mode_manifest_path = Path(mode_records[0]["artifact_path"])
                    original_fixture = fixture_path.read_bytes()
                    original_installed_package = installed_path.read_bytes()
                    original_runner_manifest = runner_path.read_bytes()
                    original_mode_manifest = mode_manifest_path.read_bytes()
                    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
                    try:
                        fixture_payload["rows"] = forged_rows
                        fixture_path.write_text(
                            json.dumps(fixture_payload, sort_keys=True), encoding="utf-8"
                        )
                        fixture_reference["sha256"] = hashlib.sha256(
                            fixture_path.read_bytes()
                        ).hexdigest()
                        installed_payload = json.loads(
                            installed_path.read_text(encoding="utf-8")
                        )
                        for execution in installed_payload["executions"]:
                            case = next(
                                case
                                for case in execution["cases"]
                                if case["case_id"] == forged_row["case_id"]
                            )
                            assert case["oracle_blocker_class"] != replacement_blocker_class
                            case["oracle_blocker_class"] = replacement_blocker_class
                        installed_path.write_text(
                            json.dumps(installed_payload, sort_keys=True), encoding="utf-8"
                        )
                        installed_reference["sha256"] = hashlib.sha256(
                            installed_path.read_bytes()
                        ).hexdigest()
                        runner_payload = json.loads(
                            runner_path.read_text(encoding="utf-8")
                        )
                        runner_payload["corpus"]["rows"] = forged_rows
                        runner_payload["installed_package"] = installed_payload
                        runner_path.write_text(
                            json.dumps(runner_payload, sort_keys=True), encoding="utf-8"
                        )
                        runner_reference["sha256"] = hashlib.sha256(
                            runner_path.read_bytes()
                        ).hexdigest()
                        mode_manifest_path.write_text(
                            json.dumps(forged_facts, sort_keys=True), encoding="utf-8"
                        )
                        refresh_mode_records(mode_records, artifacts)
                        # A self-consistent canonical-class substitution cannot
                        # replace the immutable canonical rows or executions.
                        with pytest.raises((ValueError, AssertionError)):
                            verifier(mode, mode_records)
                        assert_production_cli_rejects(mode_records)
                    finally:
                        fixture_path.write_bytes(original_fixture)
                        installed_path.write_bytes(original_installed_package)
                        runner_path.write_bytes(original_runner_manifest)
                        mode_manifest_path.write_bytes(original_mode_manifest)
                        refresh_mode_records(mode_records, artifacts)
                if mode == "package":
                    forged_facts = copy.deepcopy(mode_facts)
                    original_archives = {
                        name: path.read_bytes()
                        for name, path in artifacts.items()
                        if name in {"direct-wheel", "direct-sdist", "sdist-derived-wheel"}
                    }
                    installed_reference = forged_facts["installed_package"]
                    installed_path = Path(installed_reference["path"])
                    runner_reference = forged_facts["runner_manifest"]
                    runner_path = Path(runner_reference["path"])
                    mode_manifest_path = Path(mode_records[0]["artifact_path"])
                    original_installed_package = installed_path.read_bytes()
                    original_runner_manifest = runner_path.read_bytes()
                    original_mode_manifest = mode_manifest_path.read_bytes()
                    extra_member = (
                        "phase_loop_runtime/conformance/_contract/forged-member.json"
                    )
                    try:
                        for archive_name in ("direct-wheel", "sdist-derived-wheel"):
                            with zipfile.ZipFile(artifacts[archive_name], "a") as archive:
                                archive.writestr(extra_member, "{}")
                        sdist_members = []
                        with tarfile.open(artifacts["direct-sdist"]) as archive:
                            for member in archive.getmembers():
                                if member.isfile():
                                    contents = archive.extractfile(member)
                                    assert contents is not None
                                    sdist_members.append((member.name, contents.read()))
                        with tarfile.open(artifacts["direct-sdist"], "w:gz") as archive:
                            for name, contents in sdist_members:
                                member = tarfile.TarInfo(name)
                                member.size = len(contents)
                                archive.addfile(member, io.BytesIO(contents))
                            member = tarfile.TarInfo(
                                "phase-loop-runtime/src/" + extra_member
                            )
                            member.size = 2
                            archive.addfile(member, io.BytesIO(b"{}"))
                        assert all(
                            extra_member in _normalized_archive_member_digests(path)
                            for path in (
                                artifacts["direct-wheel"],
                                artifacts["sdist-derived-wheel"],
                            )
                        )
                        assert (
                            extra_member in _normalized_archive_member_digests(
                                artifacts["direct-sdist"]
                            )
                        )
                        installed_payload = json.loads(
                            installed_path.read_text(encoding="utf-8")
                        )
                        for execution in installed_payload["executions"]:
                            execution["archive_sha256"] = hashlib.sha256(
                                artifacts[execution["variant"]].read_bytes()
                            ).hexdigest()
                        installed_path.write_text(
                            json.dumps(installed_payload, sort_keys=True), encoding="utf-8"
                        )
                        installed_reference["sha256"] = hashlib.sha256(
                            installed_path.read_bytes()
                        ).hexdigest()
                        runner_payload = json.loads(
                            runner_path.read_text(encoding="utf-8")
                        )
                        runner_payload["installed_package"] = installed_payload
                        runner_path.write_text(
                            json.dumps(runner_payload, sort_keys=True), encoding="utf-8"
                        )
                        runner_reference["sha256"] = hashlib.sha256(
                            runner_path.read_bytes()
                        ).hexdigest()
                        mode_manifest_path.write_text(
                            json.dumps(forged_facts, sort_keys=True), encoding="utf-8"
                        )
                        refresh_mode_records(mode_records, artifacts)
                        refreshed_facts = json.loads(
                            mode_manifest_path.read_text(encoding="utf-8")
                        )
                        refreshed_installed = json.loads(
                            installed_path.read_text(encoding="utf-8")
                        )
                        refreshed_runner = json.loads(
                            runner_path.read_text(encoding="utf-8")
                        )
                        assert all(
                            refreshed_facts["archives"][archive_name]["sha256"]
                            == hashlib.sha256(archive_path.read_bytes()).hexdigest()
                            for archive_name, archive_path in artifacts.items()
                            if archive_name
                            in {
                                "direct-wheel",
                                "direct-sdist",
                                "sdist-derived-wheel",
                            }
                        )
                        assert refreshed_facts["installed_package"]["sha256"] == hashlib.sha256(
                            installed_path.read_bytes()
                        ).hexdigest()
                        assert refreshed_facts["runner_manifest"]["sha256"] == hashlib.sha256(
                            runner_path.read_bytes()
                        ).hexdigest()
                        assert refreshed_runner["installed_package"] == refreshed_installed
                        assert all(
                            execution["archive_sha256"]
                            == refreshed_facts["archives"][execution["variant"]][
                                "sha256"
                            ]
                            for execution in refreshed_installed["executions"]
                        )
                        # Archive-member equality alone must reject this valid
                        # archive set; all caller-controlled digest references
                        # and installed outcomes remain self-consistent.
                        with pytest.raises((ValueError, AssertionError)):
                            verifier(mode, mode_records)
                        assert_production_cli_rejects(mode_records)
                    finally:
                        for archive_name, contents in original_archives.items():
                            artifacts[archive_name].write_bytes(contents)
                        installed_path.write_bytes(original_installed_package)
                        runner_path.write_bytes(original_runner_manifest)
                        mode_manifest_path.write_bytes(original_mode_manifest)
                        refresh_mode_records(mode_records, artifacts)

                    forged_facts = copy.deepcopy(mode_facts)
                    installed_reference = forged_facts["installed_package"]
                    installed_path = Path(installed_reference["path"])
                    runner_reference = forged_facts["runner_manifest"]
                    runner_path = Path(runner_reference["path"])
                    mode_manifest_path = Path(mode_records[0]["artifact_path"])
                    original_installed_package = installed_path.read_bytes()
                    original_runner_manifest = runner_path.read_bytes()
                    original_mode_manifest = mode_manifest_path.read_bytes()
                    raw_case_artifacts = {}
                    try:
                        assert all(
                            hashlib.sha256(path.read_bytes()).hexdigest()
                            == forged_facts["archives"][archive_name]["sha256"]
                            for archive_name, path in artifacts.items()
                            if archive_name
                            in {"direct-wheel", "direct-sdist", "sdist-derived-wheel"}
                        )
                        installed_payload = json.loads(
                            installed_path.read_text(encoding="utf-8")
                        )
                        for execution in installed_payload["executions"]:
                            case = next(
                                case
                                for case in execution["cases"]
                                if (
                                    case["case_id"],
                                    case["surface"],
                                ) == ("positive-work-request", "api")
                            )
                            assert case["oracle_blocker_class"] == "none"
                            assert case["result"]["status"] == "pass"
                            raw_path = Path(case["raw_path"])
                            raw_case_artifacts[raw_path] = raw_path.read_bytes()
                            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
                            replay_result = json.loads(raw_payload["stdout"])
                            assert replay_result == case["result"]
                            replay_result["status"] = "blocked"
                            replay_result["blocker_codes"] = [
                                "schema_validation_failed"
                            ]
                            assert replay_result != case["result"]
                            raw_payload["stdout"] = (
                                json.dumps(replay_result, sort_keys=True) + "\n"
                            )
                            raw_path.write_text(
                                json.dumps(raw_payload, sort_keys=True),
                                encoding="utf-8",
                            )
                            case["raw_sha256"] = hashlib.sha256(
                                raw_path.read_bytes()
                            ).hexdigest()
                        installed_path.write_text(
                            json.dumps(installed_payload, sort_keys=True), encoding="utf-8"
                        )
                        installed_reference["sha256"] = hashlib.sha256(
                            installed_path.read_bytes()
                        ).hexdigest()
                        runner_payload = json.loads(
                            runner_path.read_text(encoding="utf-8")
                        )
                        runner_payload["installed_package"] = installed_payload
                        runner_path.write_text(
                            json.dumps(runner_payload, sort_keys=True), encoding="utf-8"
                        )
                        runner_reference["sha256"] = hashlib.sha256(
                            runner_path.read_bytes()
                        ).hexdigest()
                        mode_manifest_path.write_text(
                            json.dumps(forged_facts, sort_keys=True), encoding="utf-8"
                        )
                        refresh_mode_records(mode_records, artifacts)
                        # Valid submitted labels and refreshed digests cannot
                        # replace replay of this known canonical positive case.
                        with pytest.raises(AssertionError):
                            _assert_complete_package_executions(
                                installed_payload["executions"],
                                forged_facts["archives"],
                            )
                        with pytest.raises((ValueError, AssertionError)):
                            verifier(mode, mode_records)
                        assert_production_cli_rejects(mode_records)
                    finally:
                        for raw_path, contents in raw_case_artifacts.items():
                            raw_path.write_bytes(contents)
                        installed_path.write_bytes(original_installed_package)
                        runner_path.write_bytes(original_runner_manifest)
                        mode_manifest_path.write_bytes(original_mode_manifest)
                        refresh_mode_records(mode_records, artifacts)
                if mode == "compatibility":
                    forged_facts = copy.deepcopy(mode_facts)
                    matrix_reference = forged_facts["ec_matrix"]
                    matrix_path = Path(matrix_reference["path"])
                    matrix_payload = json.loads(matrix_path.read_text(encoding="utf-8"))
                    runner_reference = forged_facts["runner_manifest"]
                    runner_path = Path(runner_reference["path"])
                    mode_manifest_path = Path(mode_records[0]["artifact_path"])
                    entry = matrix_payload["entries"][0]
                    ec_id = entry["id"]
                    assert ec_id in EC_CONFORM_PROBES
                    assert entry["ordinal"] == EC_CONFORM_PROBES[ec_id]["ordinal"]
                    observable_record = entry["observable"]
                    observable = observable_record["observable"]
                    assert observable["criterion"] == EC_CONFORM_PROBES[ec_id][
                        "criterion"
                    ]
                    assert observable["classification"] == "passed"
                    assert observable_record["status"] == "accepted"
                    accepted_observable = copy.deepcopy(observable)
                    accepted_output_sha256 = observable_record["output_sha256"]
                    result_path = Path(observable_record["result_path"])
                    original_matrix = matrix_path.read_bytes()
                    original_runner_manifest = runner_path.read_bytes()
                    original_mode_manifest = mode_manifest_path.read_bytes()
                    original_result = result_path.read_bytes()
                    junit_path = Path(accepted_observable["execution"]["junit_path"])
                    original_junit = junit_path.read_bytes()
                    try:
                        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
                        rendered = json.loads(result_payload["stdout"])
                        primary_observable = rendered["observable"]
                        assert primary_observable == observable
                        assert rendered["status"] == "accepted"
                        primary_execution = primary_observable["execution"]
                        assert primary_execution["junit_path"] == str(junit_path)
                        junit_root = element_tree.parse(junit_path).getroot()
                        junit_cases = list(junit_root.iter("testcase"))
                        assert junit_cases
                        assert not any(
                            case.find("failure") is not None
                            or case.find("error") is not None
                            for case in junit_cases
                        )
                        failure = element_tree.SubElement(
                            junit_cases[0],
                            "failure",
                            {"message": "forged criterion primary failure"},
                        )
                        failure.text = "EC-CONFORM primary criterion replay failed"
                        for suite in junit_root.iter("testsuite"):
                            suite.attrib["failures"] = str(
                                sum(
                                    case.find("failure") is not None
                                    or case.find("error") is not None
                                    for case in suite.iter("testcase")
                                )
                            )
                        junit_root.attrib["failures"] = "1"
                        element_tree.ElementTree(junit_root).write(
                            junit_path, encoding="utf-8", xml_declaration=True
                        )
                        primary_execution["junit_sha256"] = hashlib.sha256(
                            junit_path.read_bytes()
                        ).hexdigest()
                        assert primary_execution["junit_sha256"] != accepted_observable[
                            "execution"
                        ]["junit_sha256"]
                        expected_submitted_observable = copy.deepcopy(
                            accepted_observable
                        )
                        expected_submitted_observable["execution"][
                            "junit_sha256"
                        ] = primary_execution["junit_sha256"]
                        assert primary_observable == expected_submitted_observable
                        result_payload["stdout"] = (
                            json.dumps(rendered, sort_keys=True) + "\n"
                        )
                        result_path.write_text(
                            json.dumps(result_payload, sort_keys=True), encoding="utf-8"
                        )
                        observable_record["output_sha256"] = hashlib.sha256(
                            result_payload["stdout"].encode("utf-8")
                        ).hexdigest()
                        observable_record["result_sha256"] = hashlib.sha256(
                            result_path.read_bytes()
                        ).hexdigest()
                        observable_record["observable"] = primary_observable
                        assert observable_record["exit_code"] == 0
                        assert observable_record["status"] == "accepted"
                        assert observable_record["observable"] == primary_observable
                        assert (
                            observable_record["output_sha256"]
                            != accepted_output_sha256
                        )
                        submitted_result = json.loads(result_payload["stdout"])
                        assert submitted_result["status"] == observable_record["status"]
                        assert submitted_result["observable"] == observable_record[
                            "observable"
                        ]
                        assert result_payload["exit_code"] == observable_record[
                            "exit_code"
                        ] == 0
                        assert observable_record["output_sha256"] == hashlib.sha256(
                            result_payload["stdout"].encode("utf-8")
                        ).hexdigest()
                        assert observable_record["result_sha256"] == hashlib.sha256(
                            result_path.read_bytes()
                        ).hexdigest()
                        assert primary_observable["classification"] == "passed"
                        assert primary_execution["classification"] == "passed"
                        assert primary_execution["exit_code"] == 0
                        assert primary_execution["junit_sha256"] == hashlib.sha256(
                            junit_path.read_bytes()
                        ).hexdigest()
                        assert any(
                            case.find("failure") is not None
                            or case.find("error") is not None
                            for case in element_tree.parse(junit_path)
                            .getroot()
                            .iter("testcase")
                        )
                        assert entry["id"] == ec_id
                        assert observable_record["observable"]["criterion"] == (
                            EC_CONFORM_PROBES[ec_id]["criterion"]
                        )
                        matrix_path.write_text(
                            json.dumps(matrix_payload, sort_keys=True), encoding="utf-8"
                        )
                        matrix_reference["sha256"] = hashlib.sha256(
                            matrix_path.read_bytes()
                        ).hexdigest()
                        runner_payload = json.loads(
                            runner_path.read_text(encoding="utf-8")
                        )
                        runner_payload["ec_matrix"] = {
                            "entries": matrix_payload["entries"]
                        }
                        runner_path.write_text(
                            json.dumps(runner_payload, sort_keys=True), encoding="utf-8"
                        )
                        runner_reference["sha256"] = hashlib.sha256(
                            runner_path.read_bytes()
                        ).hexdigest()
                        assert runner_payload["ec_matrix"] == {
                            "entries": matrix_payload["entries"]
                        }
                        mode_manifest_path.write_text(
                            json.dumps(forged_facts, sort_keys=True), encoding="utf-8"
                        )
                        refresh_mode_records(mode_records, artifacts)
                        _assert_f17ab557_label_trusting_compatibility_accepts(
                            matrix_payload["entries"]
                        )
                        # The full result artifact and all submitted summaries
                        # remain a self-consistent pass.  Only replaying the
                        # bound primary JUnit proves this criterion failed.
                        with pytest.raises(AssertionError):
                            _assert_complete_ec_observables(matrix_payload["entries"])
                        with pytest.raises((ValueError, AssertionError)):
                            verifier(mode, mode_records)
                        assert_production_cli_rejects(mode_records)
                    finally:
                        junit_path.write_bytes(original_junit)
                        result_path.write_bytes(original_result)
                        matrix_path.write_bytes(original_matrix)
                        runner_path.write_bytes(original_runner_manifest)
                        mode_manifest_path.write_bytes(original_mode_manifest)
                        refresh_mode_records(mode_records, artifacts)
                original_junit = artifacts["junit"].read_bytes()
                element_tree.ElementTree(
                    element_tree.fromstring(
                        '<testsuite name="outside-agent-activated-lifecycle" tests="2" '
                        'failures="1" skipped="0"><testcase name="positive"/>'
                        '<testcase name="mutation:M-CONFORM-8-SWAP-SCHEMA"><failure/>'
                        "</testcase></testsuite>"
                    )
                ).write(artifacts["junit"], encoding="utf-8", xml_declaration=True)
                # Recompute every caller-controlled digest around the exact old
                # 2-test/1-failure fixture.  The verifier must parse the bytes
                # and reject it, rather than trusting the refreshed manifest.
                refresh_mode_records(mode_records, artifacts)
                with pytest.raises(AssertionError):
                    _assert_full_frozen_evidence_input(mode, mode_records)
                with pytest.raises((ValueError, AssertionError)):
                    verifier(mode, mode_records)
                assert_production_cli_rejects(mode_records)
                artifacts["junit"].write_bytes(original_junit)
                refresh_mode_records(mode_records, artifacts)
                mode_facts = json.loads(
                    Path(mode_records[0]["artifact_path"]).read_text(encoding="utf-8")
                )
                if mode == "package":
                    original_archives = {
                        name: path.read_bytes()
                        for name, path in artifacts.items()
                        if name in {"direct-wheel", "direct-sdist", "sdist-derived-wheel"}
                    }
                    for archive_name, archive_path in (
                        ("direct-wheel", artifacts["direct-wheel"]),
                        ("sdist-derived-wheel", artifacts["sdist-derived-wheel"]),
                    ):
                        with zipfile.ZipFile(archive_path, "w") as archive:
                            archive.writestr(
                                "phase_loop_runtime/conformance/_contract/VENDOR.json", "{}"
                            )
                    with tarfile.open(artifacts["direct-sdist"], "w:gz") as archive:
                        contents = b"{}"
                        member = tarfile.TarInfo(
                            "phase-loop-runtime/src/phase_loop_runtime/conformance/"
                            "_contract/VENDOR.json"
                        )
                        member.size = len(contents)
                        archive.addfile(member, io.BytesIO(contents))
                    refresh_mode_records(mode_records, artifacts)
                    refreshed_facts = json.loads(
                        Path(mode_records[0]["artifact_path"]).read_text(encoding="utf-8")
                    )
                    assert all(
                        refreshed_facts["archives"][name]["sha256"]
                        == hashlib.sha256(path.read_bytes()).hexdigest()
                        for name, path in artifacts.items()
                        if name in {"direct-wheel", "direct-sdist", "sdist-derived-wheel"}
                    )
                    # The old {} VENDOR archives now have caller-refreshed hashes.
                    # A digest-integrity-only verifier would accept them; semantic
                    # contract/provenance validation must still fail closed.
                    with pytest.raises((ValueError, AssertionError)):
                        verifier(mode, mode_records)
                    assert_production_cli_rejects(mode_records)
                    for archive_name, contents in original_archives.items():
                        artifacts[archive_name].write_bytes(contents)
                    refresh_mode_records(mode_records, artifacts)
                if mode == "compatibility":
                    matrix_fact = Path(mode_facts["ec_matrix"]["path"])
                    original_matrix = matrix_fact.read_bytes()
                    matrix_fact.write_text(
                        json.dumps(
                            {"candidate_tree": candidate_tree, "matrix": "ec-v0.2.1"},
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    mode_facts["ec_matrix"]["sha256"] = hashlib.sha256(
                        matrix_fact.read_bytes()
                    ).hexdigest()
                    Path(mode_records[0]["artifact_path"]).write_text(
                        json.dumps(mode_facts, sort_keys=True), encoding="utf-8"
                    )
                    refresh_mode_records(mode_records, artifacts)
                    refreshed_facts = json.loads(
                        Path(mode_records[0]["artifact_path"]).read_text(encoding="utf-8")
                    )
                    assert refreshed_facts["ec_matrix"]["sha256"] == hashlib.sha256(
                        matrix_fact.read_bytes()
                    ).hexdigest()
                    # A caller can refresh every hash around the former single
                    # string matrix.  That cannot substitute for EC-CONFORM-0..8.
                    with pytest.raises((ValueError, AssertionError)):
                        verifier(mode, mode_records)
                    assert_production_cli_rejects(mode_records)
                    matrix_fact.write_bytes(original_matrix)
                    Path(mode_records[0]["artifact_path"]).write_text(
                        json.dumps(mode_facts, sort_keys=True), encoding="utf-8"
                    )
                    refresh_mode_records(mode_records, artifacts)
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

            if os.environ.get("PHASE_LOOP_CONFORM_CHRONOLOGY_PROOF") == "1":
                forged_records, forged_artifacts = records_for("chronology", force_forgery=True)
                try:
                    verifier("chronology", forged_records)
                except Exception:
                    pass
                else:
                    raise AssertionError("CONFORM_RED::chronology_accepts_forged_git_topology")
    # The future package path deliberately has no mockable or toy replay seam:
    # only raw subprocess output from archives built from the candidate is input.
