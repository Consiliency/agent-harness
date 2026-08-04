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
    REPO_ROOT,
    SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS,
    SEALED_RELEASE_ARCHIVE_MEMBERS,
    SEALED_RELEASE_CANDIDATE_PARENT_BLOBS,
    SEALED_RELEASE_CANDIDATE_PATHS,
    SEALED_RELEASE_FINAL_PARENT_BLOBS,
    SEALED_RELEASE_FINAL_PATHS,
    assert_named_safety_mutations_rejected,
    assert_status_code_only_replacement_is_rejected,
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
EC_CONFORM_IDS = tuple(f"EC-CONFORM-{index}" for index in range(9))
EVIDENCE_SEMANTIC_OUTPUT_KEYS = {
    "bindings",
    "vendor",
    "chronology",
    "corpus",
    "package",
    "ec_matrix",
    "installed_package",
    "mode_specific",
}
PACKAGE_EXECUTION_VARIANTS = (
    "direct-wheel",
    "direct-sdist",
    "sdist-derived-wheel",
)
PACKAGE_EXECUTION_CASES = ("api", "cli", "vector")


def _source_execution_environment() -> dict[str, str]:
    return {
        "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(REPO_ROOT / "phase-loop-runtime" / "src")
        + os.pathsep
        + str(REPO_ROOT / "phase-loop-runtime" / "tests"),
    }


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
_MUTATION_PROBE_RUNNER = textwrap.dedent(
    """
    import hashlib, io, json, os, re, shutil, subprocess, sys, tarfile
    from pathlib import Path

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
                for member in archive.getmembers():
                    parts = Path(member.name).parts
                    assert parts and parts[0] == "phase-loop-runtime" and ".." not in parts
                    assert member.isfile() or member.isdir()
                archive.extractall(execution_root)
    if not candidate_clean:
        shutil.copytree(repo_root / "phase-loop-runtime", runtime, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    source_path = execution_root / mutation.source_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source = source_path.read_text(encoding="utf-8") if source_path.is_file() else mutation.complete_source()
    source_path.write_text(source, encoding="utf-8")
    mutant = mutation.apply(source)
    environment = {
        "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(runtime / "src") + os.pathsep + str(runtime / "tests"),
    }
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
        def normalize(text):
            text = re.sub(r"pytest-[0-9]+", "pytest-<run>", text)
            return re.sub(r" in [0-9.]+s", " in <duration>", text)
        return {
            "argv": argv,
            "cwd": str(execution_root),
            "environment": environment,
            "exit_code": completed.returncode,
            "stdout_sha256": hashlib.sha256(normalize(completed.stdout).encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(normalize(completed.stderr).encode("utf-8")).hexdigest(),
            "classification": classification,
        }, completed

    baseline, baseline_raw = execute(list(mutation.argv))
    positive_control, positive_raw = execute(list(mutation.positive_control))
    source_path.write_text(mutant, encoding="utf-8")
    mutant_result, mutant_raw = execute(list(mutation.argv))
    combined = mutant_raw.stdout + mutant_raw.stderr
    nodeid_matched = (
        mutation.expected_nodeid in combined
        or mutation.expected_nodeid.rsplit("::", 1)[-1] in combined
    )
    killed = (
        baseline["classification"] == "passed"
        and positive_control["classification"] == "passed"
        and mutant_result["classification"] == "failed"
        and nodeid_matched
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
        "baseline": baseline,
        "positive_control": positive_control,
        "mutant": mutant_result,
    }
    status = "blocked" if killed else "incomplete"
    print(json.dumps({"status": status, "anchor": mutation.expected_anchor, "observable": observable}, sort_keys=True))
    raise SystemExit(1)
    """
)
_EC_PROBE_RUNNER = textwrap.dedent(
    """
    import hashlib, json, os, re, subprocess, sys
    from pathlib import Path

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
    environment = {
        "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(runtime / "src") + os.pathsep + str(runtime / "tests"),
    }
    argv = [sys.executable, "-m", "pytest", "-q", *("tests/" + nodeid for nodeid in nodeids)]
    completed = subprocess.run(argv, cwd=runtime, capture_output=True, text=True, check=False, env=environment)
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
            "stdout_sha256": hashlib.sha256(re.sub(r" in [0-9.]+s", " in <duration>", completed.stdout).encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(re.sub(r" in [0-9.]+s", " in <duration>", completed.stderr).encode("utf-8")).hexdigest(),
            "classification": classification,
        },
    }
    passed = classification == "passed"
    print(json.dumps({"status": "accepted" if passed else "blocked", "observable": observable}, sort_keys=True))
    raise SystemExit(0 if passed else 1)
    """
)
_RUNNABLE_PACKAGE_MEMBERS = {
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


def _write_runnable_wheel(path: Path, members: dict[str, bytes]) -> None:
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


def _write_runnable_sdist(path: Path, members: dict[str, bytes]) -> None:
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


def _write_runnable_package_archives(
    root: Path, contract_members: dict[str, bytes]
) -> dict[str, Path]:
    """Create three extractable package variants with executable surfaces."""
    package_members = {**_RUNNABLE_PACKAGE_MEMBERS, **contract_members}
    archives = {
        "direct-wheel": root / "direct-wheel.whl",
        "direct-sdist": root / "direct-sdist.tar.gz",
        "sdist-derived-wheel": root / "sdist-derived-wheel.whl",
    }
    _write_runnable_wheel(archives["direct-wheel"], package_members)
    _write_runnable_sdist(archives["direct-sdist"], package_members)
    with tarfile.open(archives["direct-sdist"]) as archive:
        derived_members = {
            member.name.split("/src/", 1)[1]: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile() and "/src/phase_loop_runtime/" in member.name
        }
    assert derived_members == package_members
    _write_runnable_wheel(archives["sdist-derived-wheel"], derived_members)
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
        archive.extractall(candidate_export, filter="data")
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
        archive.extractall(sdist_export, filter="data")
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
    assert rendered["observable"] == record["observable"] == expected_observable

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
    assert rerun_rendered["observable"] == expected_observable


def _capture_package_executions(
    root: Path,
    archives: dict[str, Path],
) -> list[dict[str, object]]:
    """Extract each archive and capture API, CLI, and vector behavior in isolation."""
    executions = []
    payload = {"submission_schema_version": "outside_agent_submission.v0.1"}
    commands = {
        "api": [
            sys.executable,
            "-c",
            "import json, sys; from phase_loop_runtime.conformance.outside_agent_schema import validate; print(json.dumps(validate(json.load(sys.stdin)), sort_keys=True))",
        ],
        "cli": [sys.executable, "-m", "phase_loop_runtime.cli", "outside-agent-validate"],
        "vector": [
            sys.executable,
            "-m",
            "phase_loop_runtime.conformance.outside_agent_vectors",
        ],
    }
    for variant in PACKAGE_EXECUTION_VARIANTS:
        archive_path = archives[variant]
        extraction_root = root / f"{variant}-isolated"
        extraction_root.mkdir()
        if variant == "direct-sdist":
            with tarfile.open(archive_path) as archive:
                archive.extractall(extraction_root, filter="data")
            import_root = extraction_root / "phase-loop-runtime" / "src"
        else:
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extraction_root)
            import_root = extraction_root
        assert (import_root / "phase_loop_runtime/conformance/outside_agent_schema.py").is_file()
        environment = {
            "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(import_root),
        }
        cases = []
        for case_id in PACKAGE_EXECUTION_CASES:
            observable = _capture_subprocess_observable(
                root,
                prefix=f"{variant}-{case_id}",
                command=commands[case_id],
                payload=payload,
                environment=environment,
                cwd=extraction_root,
            )
            _assert_captured_observable(
                observable,
                expected_command=commands[case_id],
                expected_payload=payload,
                expected_exit=0,
                expected_status="accepted",
                expected_observable={"surface": case_id, "accepted": True},
                environment=environment,
                cwd=extraction_root,
            )
            cases.append({"case_id": case_id, "result": observable})
        executions.append(
            {
                "variant": variant,
                "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                "extraction_posture": "isolated-subprocess",
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
        "baseline",
        "positive_control",
        "mutant",
    }
    source = definition.complete_source()
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
        assert result["environment"] == {
            "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(Path(execution_root) / "phase-loop-runtime" / "src")
            + os.pathsep
            + str(Path(execution_root) / "phase-loop-runtime" / "tests"),
        }
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
    else:
        assert (
            not candidate["candidate_clean"]
            or baseline["classification"] != "passed"
            or positive_control["classification"] != "passed"
            or mutant_result["classification"] != "failed"
            or observable["nodeid_matched"] is not True
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
        "classification",
    }
    runtime = Path(execution["cwd"])
    assert execution["argv"] == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *("tests/" + nodeid for nodeid in _EC_PROBE_NODEIDS[ec_id]),
    ]
    assert execution["environment"] == {
        "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(runtime / "src")
        + os.pathsep
        + str(runtime / "tests"),
    }
    assert observable["classification"] in {"passed", "skipped", "failed", "inconclusive"}
    assert execution["classification"] == observable["classification"]
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
        for key in ("stdout_sha256", "stderr_sha256")
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


def _assert_complete_package_executions(
    executions: list[dict[str, object]], archives: dict[str, object]
) -> None:
    assert tuple(execution["variant"] for execution in executions) == PACKAGE_EXECUTION_VARIANTS
    payload = {"submission_schema_version": "outside_agent_submission.v0.1"}
    commands = {
        "api": [
            sys.executable,
            "-c",
            "import json, sys; from phase_loop_runtime.conformance.outside_agent_schema import validate; print(json.dumps(validate(json.load(sys.stdin)), sort_keys=True))",
        ],
        "cli": [sys.executable, "-m", "phase_loop_runtime.cli", "outside-agent-validate"],
        "vector": [
            sys.executable,
            "-m",
            "phase_loop_runtime.conformance.outside_agent_vectors",
        ],
    }
    for execution in executions:
        variant = execution["variant"]
        assert set(execution) == {
            "variant",
            "archive_sha256",
            "extraction_posture",
            "cases",
        }
        assert execution["extraction_posture"] == "isolated-subprocess"
        assert execution["archive_sha256"] == archives[variant]["sha256"]
        archive_path = Path(archives[variant]["path"])
        members = _normalized_archive_member_digests(archive_path)
        for member_name, contents in _RUNNABLE_PACKAGE_MEMBERS.items():
            assert members.get(member_name) == hashlib.sha256(contents).hexdigest()
        assert tuple(case["case_id"] for case in execution["cases"]) == PACKAGE_EXECUTION_CASES
        for case in execution["cases"]:
            case_id = case["case_id"]
            root = Path(case["result"]["result_path"]).parent
            if variant == "direct-sdist":
                import_root = root / f"{variant}-isolated" / "phase-loop-runtime" / "src"
            else:
                import_root = root / f"{variant}-isolated"
            environment = {
                "PHASE_LOOP_TDD_EXPECT_CONFORM": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(import_root),
            }
            _assert_captured_observable(
                case["result"],
                expected_command=commands[case_id],
                expected_payload=payload,
                expected_exit=0,
                expected_status="accepted",
                expected_observable={"surface": case_id, "accepted": True},
                environment=environment,
                cwd=root / f"{variant}-isolated",
            )


def _write_exact_frozen_activated_junit(path: Path) -> None:
    """Write the one accepted 93-node/54-RED activated lifecycle artifact."""
    suite = element_tree.Element(
        "testsuite",
        {
            "name": "outside-agent-activated-lifecycle",
            "tests": str(ALL_OUTSIDE_AGENT_NODE_COUNT),
            "failures": str(CONFORM_ACTIVATED_RED_NODE_COUNT),
            "skipped": "0",
        },
    )
    for nodeid in ALL_OUTSIDE_AGENT_NODE_IDS:
        case = element_tree.SubElement(suite, "testcase", {"name": nodeid})
        if nodeid in CONFORM_ACTIVATED_RED_NODE_IDS:
            failure = element_tree.SubElement(case, "failure")
            failure.text = CONFORM_ACTIVATED_RED_ANCHORS[nodeid]
    element_tree.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _assert_exact_frozen_activated_junit(path: Path) -> None:
    """Reject lifecycle summaries that omit nodes, REDs, or named anchors."""
    suite = element_tree.parse(path).getroot()
    assert suite.attrib == {
        "name": "outside-agent-activated-lifecycle",
        "tests": "93",
        "failures": "54",
        "skipped": "0",
    }
    cases = suite.findall("testcase")
    assert len(cases) == ALL_OUTSIDE_AGENT_NODE_COUNT
    assert tuple(case.attrib["name"] for case in cases) == ALL_OUTSIDE_AGENT_NODE_IDS
    failures = {
        case.attrib["name"]: (case.find("failure").text or "")
        for case in cases
        if case.find("failure") is not None
    }
    assert failures == {
        nodeid: CONFORM_ACTIVATED_RED_ANCHORS[nodeid]
        for nodeid in CONFORM_ACTIVATED_RED_NODE_IDS
    }


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
        "tests": 93,
        "failures": 54,
        "skipped": 0,
        "node_ids": list(ALL_OUTSIDE_AGENT_NODE_IDS),
        "red_node_ids": list(CONFORM_ACTIVATED_RED_NODE_IDS),
        "red_anchors": CONFORM_ACTIVATED_RED_ANCHORS,
    }
    _assert_exact_frozen_activated_junit(Path(facts["junit_path"]))
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
    ec_matrix = json.loads(
        Path(facts["ec_matrix"]["path"]).read_text(encoding="utf-8")
    )
    assert set(ec_matrix) == {"candidate_commit", "candidate_tree", "entries"}
    assert ec_matrix["candidate_commit"] == bindings["candidate_commit"]
    assert ec_matrix["candidate_tree"] == bindings["candidate_tree"]
    _assert_complete_ec_observables(ec_matrix["entries"])


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


def test_frozen_command_literals_and_selector_partition(tmp_path: Path) -> None:
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
    _write_exact_frozen_activated_junit(frozen_junit)
    _assert_exact_frozen_activated_junit(frozen_junit)
    # This is the exact Sol reproducer shape.  It cannot become a positive by
    # refreshing its own digest fields because it omits 91 nodes and 53 REDs.
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
        _assert_exact_frozen_activated_junit(undersized_junit)
    # The SL-0 test contract executes its package/observable evidence directly,
    # before the future production verifier exists.  This makes skeletal
    # metadata-only packages and caller-authored outcome labels locally
    # reproducible rejections instead of deferred verifier wishes.
    direct_root = tmp_path / "direct-observable-controls"
    direct_root.mkdir()
    direct_archives = _write_runnable_package_archives(
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
    direct_executions = _capture_package_executions(direct_root, direct_archives)
    _assert_complete_package_executions(direct_executions, direct_archive_facts)
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
        _assert_complete_package_executions(direct_executions, direct_archive_facts)

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
        for mutation_id, definition in CONFORM_MUTATION_DEFINITIONS.items()
    ]
    _assert_bound_mutation_observables(direct_mutations)
    if all(
        mutation["observable"]["observable"]["classification"] == "killed"
        for mutation in direct_mutations
    ):
        _assert_complete_mutation_observables(direct_mutations)
    else:
        with pytest.raises(AssertionError):
            _assert_complete_mutation_observables(direct_mutations)
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
    command_tampered_mutations[0]["observable"]["command"] = [sys.executable, "-c", "print('tampered')"]
    with pytest.raises(AssertionError):
        _assert_bound_mutation_observables(command_tampered_mutations)

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
    command_tampered_ec_entries[0]["observable"]["command"] = [sys.executable, "-c", "print('tampered')"]
    with pytest.raises(AssertionError):
        _assert_bound_ec_observables(command_tampered_ec_entries)
    zeroed_executions = copy.deepcopy(direct_executions)
    zeroed_executions[0]["cases"][0]["result"]["input_sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        _assert_complete_package_executions(zeroed_executions, direct_archive_facts)
    command_tampered_executions = copy.deepcopy(direct_executions)
    command_tampered_executions[0]["cases"][0]["result"]["command"] = [sys.executable, "-c", "print('tampered')"]
    with pytest.raises(AssertionError):
        _assert_complete_package_executions(command_tampered_executions, direct_archive_facts)

    forged_pkg_executions = copy.deepcopy(direct_executions)
    forged_pkg_res = forged_pkg_executions[0]["cases"][0]["result"]
    forged_pkg_res["output_sha256"] = hashlib.sha256(b"forged_pkg").hexdigest()
    Path(forged_pkg_res["result_path"]).write_text(
        json.dumps(
            {
                "command": forged_pkg_res["command"],
                "exit_code": 0,
                "stdout": json.dumps({"status": "accepted", "observable": {"surface": "api", "accepted": True}}),
                "stderr": "",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    forged_pkg_res["result_sha256"] = hashlib.sha256(Path(forged_pkg_res["result_path"]).read_bytes()).hexdigest()
    with pytest.raises(AssertionError):
        _assert_complete_package_executions(forged_pkg_executions, direct_archive_facts)

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
                        "observable": {"kind": "rejection", "nodeid": direct_mutations[0]["expected_nodeid"]},
                    }
                ),
                "stderr": "",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    forged_mut_res["result_sha256"] = hashlib.sha256(Path(forged_mut_res["result_path"]).read_bytes()).hexdigest()
    with pytest.raises(AssertionError):
        _assert_complete_mutation_observables(forged_mut_set)

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
                            "criterion": EC_CONFORM_PROBES[direct_ec_entries[0]["id"]]["criterion"],
                        },
                    }
                ),
                "stderr": "",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    forged_ec_res["result_sha256"] = hashlib.sha256(Path(forged_ec_res["result_path"]).read_bytes()).hexdigest()
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
            repository = REPO_ROOT

            def git(*argv: str) -> str:
                completed = subprocess.run(["git", *argv], cwd=repository, capture_output=True, text=True, check=False)
                assert completed.returncode == 0, completed.stdout + completed.stderr
                return completed.stdout.strip()

            candidate_identity = _repo_candidate_identity()
            assert candidate_identity["candidate_clean"] is True
            candidate = candidate_identity["candidate_oid"]
            candidate_tree = candidate_identity["candidate_tree"]
            assert isinstance(candidate, str) and isinstance(candidate_tree, str)
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
                "head_commit": candidate,
                "head_tree": candidate_tree,
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
            activated_lifecycle = {
                "tests": 93,
                "failures": 54,
                "skipped": 0,
                "node_ids": list(ALL_OUTSIDE_AGENT_NODE_IDS),
                "red_node_ids": list(CONFORM_ACTIVATED_RED_NODE_IDS),
                "red_anchors": CONFORM_ACTIVATED_RED_ANCHORS,
            }
            chronology = {
                "stages": [
                    {
                        "stage": "preimplementation_red",
                        "commit": parent,
                        "tree": parent_tree,
                        "exit_code": 1,
                        "failing_node_ids": list(CONFORM_ACTIVATED_RED_NODE_IDS),
                        "failing_anchors": CONFORM_ACTIVATED_RED_ANCHORS,
                    },
                    {
                        "stage": "postimplementation_pre_doc",
                        "commit": candidate,
                        "tree": candidate_tree,
                        "exit_code": 0,
                        "mutation_outcomes": {
                            mutation["id"]: "killed" for mutation in mutation_records
                        },
                    },
                ],
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
                "chronology": chronology,
                "corpus": {"rows": corpus_rows, "partitions": corpus_partitions},
                "package": package_facts,
                "mutation_records": mutation_records,
                "mutations": mutation_records,
            }
            candidate_archives = _build_candidate_package_archives(
                root / "candidate-package-build", candidate
            )

            def records_for(mode: str) -> tuple[list[dict[str, object]], dict[str, Path]]:
                mode_root = root / mode
                mode_root.mkdir()
                mode_log = mode_root / "runner.log"
                mode_log.write_text(f"runner-owned:{mode}\n", encoding="utf-8")
                mode_junit = mode_root / "controls.junit.xml"
                _write_exact_frozen_activated_junit(mode_junit)
                mode_archives = {}
                for label, source in candidate_archives.items():
                    target = mode_root / source.name
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
                ec_matrix_entries = _capture_ec_matrix_entries(mode_root)
                def write_mode_fact(name: str, payload: dict[str, object]) -> dict[str, str]:
                    fact_path = mode_root / f"{name}.json"
                    fact_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
                    return {
                        "path": str(fact_path),
                        "sha256": hashlib.sha256(fact_path.read_bytes()).hexdigest(),
                    }

                ec_matrix_fact = write_mode_fact(
                    "ec-matrix",
                    {**bindings, "entries": ec_matrix_entries},
                )
                installed_package_fact = write_mode_fact(
                    "installed-package", installed_package_facts
                )

                mode_exclusive_facts: dict[str, dict[str, object]] = {
                    "chronology": {
                        "chronology": chronology
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
                                "head_commit": candidate,
                                "head_tree": candidate_tree,
                                "module_path": facts["module_path"],
                                "corpus_partitions": corpus_partitions,
                                "contract_member_digests": contract_member_digests,
                                "candidate_head_module": bindings,
                                "provenance": vendor,
                                "activated_lifecycle": activated_lifecycle,
                                "mutation_records": mutation_records,
                                "chronology": chronology,
                                "package": package_facts,
                                "installed_package": installed_package_facts,
                                "corpus": {
                                    "rows": corpus_rows,
                                    "partitions": corpus_partitions,
                                },
                                "ec_matrix": {"entries": ec_matrix_entries},
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
                        "ec_matrix": ec_matrix_fact,
                        "installed_package": installed_package_fact,
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
                    "mutations": mode_facts["mutation_records"],
                    "package_executions": json.loads(
                        Path(mode_facts["installed_package"]["path"]).read_text(
                            encoding="utf-8"
                        )
                    )["executions"],
                    "ec_matrix": json.loads(
                        Path(mode_facts["ec_matrix"]["path"]).read_text(
                            encoding="utf-8"
                        )
                    )["entries"],
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
                _assert_full_frozen_evidence_input(mode, mode_records)
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
                evidence = verified["evidence"]
                assert EVIDENCE_SEMANTIC_OUTPUT_KEYS <= set(evidence)
                assert evidence["vendor"] == vendor
                assert evidence["bindings"] == {
                    "candidate_commit": candidate,
                    "candidate_tree": candidate_tree,
                    "head_commit": candidate,
                    "head_tree": candidate_tree,
                    "module_path": facts["module_path"],
                }
                assert [stage["stage"] for stage in evidence["chronology"]["stages"]] == [
                    "preimplementation_red",
                    "postimplementation_pre_doc",
                ]
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
    # A mockable replay seam must not bless refreshed forged result artifacts.
    root = tmp_path / "forged-observables"
    root.mkdir()
    archives = _write_runnable_package_archives(
        root,
        {"phase_loop_runtime/conformance/_contract/VENDOR.json": b"{}"},
    )
    archive_facts = {
        label: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for label, path in archives.items()
    }
    executions = _capture_package_executions(root, archives)
    mutations = [
        {
            "id": mutation_id,
            "source_path": definition.source_path,
            "expected_nodeid": definition.expected_nodeid,
            "expected_anchor": definition.expected_anchor,
            "observable": _capture_rejected_observable(
                root,
                case_id="forged-" + mutation_id,
                mutation_id=mutation_id,
                source_path=definition.source_path,
                nodeid=definition.expected_nodeid,
                anchor=definition.expected_anchor,
            ),
        }
        for mutation_id, definition in CONFORM_MUTATION_DEFINITIONS.items()
    ]
    entries = _capture_ec_matrix_entries(root)
    observables = [
        *(case["result"] for execution in executions for case in execution["cases"]),
        *(mutation["observable"] for mutation in mutations),
        *(entry["observable"] for entry in entries),
    ]
    responses = {}
    for observable in observables:
        result_path = Path(observable["result_path"])
        forged = json.loads(result_path.read_text(encoding="utf-8"))
        forged["stderr"] = "fully-resealed-forged-child-result\n"
        result_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
        observable["result_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
        observable["output_sha256"] = hashlib.sha256(
            forged["stdout"].encode("utf-8")
        ).hexdigest()
        responses[
            (
                tuple(observable["command"]),
                observable["cwd"],
                observable["input_sha256"],
            )
        ] = forged

    real_run = subprocess.run
    def mocked_run(command, **kwargs):
        input_text = kwargs.get("input")
        if input_text is None:
            return real_run(command, **kwargs)
        key = (
            tuple(command),
            str(kwargs["cwd"]),
            hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
        )
        forged = responses[key]
        return subprocess.CompletedProcess(
            command, forged["exit_code"], forged["stdout"], forged["stderr"]
        )

    monkeypatch.setattr(subprocess, "run", mocked_run)
    with pytest.raises(AssertionError):
        _assert_complete_package_executions(executions, archive_facts)
    with pytest.raises(AssertionError):
        _assert_bound_mutation_observables(mutations)
    with pytest.raises(AssertionError):
        _assert_bound_ec_observables(entries)
