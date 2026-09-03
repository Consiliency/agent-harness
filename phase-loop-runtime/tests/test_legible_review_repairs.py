from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

legible_evidence = pytest.importorskip(
    "phase_loop_runtime.legible_evidence",
    reason="LEGIBLE implementation capability is not installed",
)
from phase_loop_runtime import (
    discovery,
    docs_freshness,
    plan_manifest,
    roadmap_assumptions,
    roadmap_lint,
    verification_evidence,
)
from phase_loop_runtime.docs_freshness import check_catalog
from phase_loop_runtime.plan_manifest import check
from phase_loop_runtime.roadmap_assumptions import _classify_reviewtruth_transition
from phase_loop_runtime.verification_evidence import (
    ARTIFACT_NAME,
    LOG_NAME,
    VerificationArtifactContractError,
    _artifact_seal_region_start,
    _bind_sidecar_extension,
    run_verification,
    validate_verification_artifact,
    validate_verification_artifact_for_plan,
)
from phase_loop_test_utils import make_repo


LEGIBLE_PROBE_IDS = (
    "LEGIBLE-A1-CONFORM-UNGATED",
    "LEGIBLE-A1-I118",
    "LEGIBLE-A1-PIN-SHA",
    "LEGIBLE-A1-PIN-TAG",
    "LEGIBLE-A1-PR102",
    "LEGIBLE-A1-PR377",
    "LEGIBLE-A1-SUBMISSION-DIGEST",
    "LEGIBLE-A1-TAG-DEREF",
    "LEGIBLE-A1-VERDICT-DIGEST",
    "LEGIBLE-A2-GP-PIN",
    "LEGIBLE-A2-I128",
    "LEGIBLE-A2-LOCAL-VERSION",
    "LEGIBLE-A2-NO-DEPENDENCY",
    "LEGIBLE-A3-EC14",
    "LEGIBLE-A3-EC4",
    "LEGIBLE-A3-NO-DEGRADED-GATE",
    "LEGIBLE-A3-REVIEWTRUTH-TRANSITION",
    "LEGIBLE-A4-DISCOVERY",
    "LEGIBLE-A4-PER-ENTRY",
    "LEGIBLE-A4-PR170",
    "LEGIBLE-A5-RATIFICATION",
    "LEGIBLE-A5-RETRACTION",
    "LEGIBLE-A5-SHARED-EPOCH",
)

LEGIBLE_OWNED_PATHS = (
    ".claude/docs-catalog.json",
    "phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md",
    "phase-loop-runtime/src/phase_loop_runtime/cli.py",
    "phase-loop-runtime/src/phase_loop_runtime/discovery.py",
    "phase-loop-runtime/src/phase_loop_runtime/docs_freshness.py",
    "phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py",
    "phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py",
    "phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py",
    "phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py",
    "phase-loop-runtime/src/phase_loop_runtime/runner.py",
    "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
    "phase-loop-runtime/tests/test_legible_evidence.py",
    "phase-loop-runtime/tests/test_legible_review_repairs.py",
    "phase-loop-runtime/tests/test_legible_roadmap_contract.py",
    "plans/manifest.json",
    "plans/phase-plan-v10-LEGIBLE.md",
    "specs/roadmap-assumption-probes-v10.json",
    "specs/roadmap-status.json",
)

LEGIBLE_CONTRACT_FIXED_FIELDS = {
    "absent_registry_selector_falsifier_nodeid": (
        "phase-loop-runtime/tests/test_legible_roadmap_contract.py::"
        "test_absent_registry_selector_rejects_recognized_non_active_banner_and_preserves_no_declaration_legacy"
    ),
    "absent_registry_selector_falsifier_nodeid_sha256": (
        "e65af55d0f3df427f8b1c1b001fbb69b92585f6790f2daa97f47a2f6adbab93a"
    ),
    "activation_env": "PHASE_LOOP_TDD_EXPECT_LEGIBLE",
    "capability_marker": "phase_loop_runtime.legible_evidence:LEGIBLE_CAPABILITY_VERSION=legible.v1",
    "expected_nodeids": 84,
    "legacy_selector_compatibility": "candidate_has_no_lifecycle_declaration",
    "lifecycle": "legible_tdd_candidate_main.v1",
    "log_sha256_scope": "complete_final_v3_sealed_log_bytes",
    "phase_dependencies": [],
    "selector_common_return_contract": (
        "parse_candidate_lifecycle_then_reject_recognized_non_active_with_or_without_registry"
    ),
    "v2_to_v3_preservation": "all_v2_json_values_except_schema_version_and_derived_log_sha256",
    "verification_evidence_contract": "verification_evidence.v3",
    "verification_extension_namespaces": {"phase_loop_runtime.legible_evidence": "LEGIBLE"},
    "verification_extension_registry_owner": "LEGIBLE",
    "verification_extension_reserved_downstream_namespace": "phase_loop_runtime.proofgate_evidence",
}

LEGIBLE_LOADED_RUNTIME_PATHS = (
    "phase-loop-runtime/src/phase_loop_runtime/cli.py",
    "phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md",
    "phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py",
    "phase-loop-runtime/src/phase_loop_runtime/runner.py",
    "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
)
LEGIBLE_ROADMAP_SHA256 = roadmap_assumptions.CANONICAL_ROADMAP_SHA256
LEGIBLE_SKIP_REASON = (
    "LEGIBLE capability absent (set PHASE_LOOP_TDD_EXPECT_LEGIBLE=1, or install "
    "phase_loop_runtime.legible_evidence with LEGIBLE_CAPABILITY_VERSION == 'legible.v1')"
)
LEGIBLE_REPAIRED_PLAN_EXCERPT = """\
the historical exact-tree publish is accepted as the
require the server-side merge commit to have `I` as its second parent
"""


def _commit_plan(repo: Path, name: str = "phase-plan-v1-RUNNER.md") -> str:
    rel = f"plans/{name}"
    (repo / rel).write_text("---\nphase: RUNNER\n---\n# Runner\n", encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add plan"], cwd=repo, check=True, capture_output=True)
    return rel


def _source_authority_manifest(source_repo: Path) -> dict:
    manifest_path = Path(
        os.environ.get(
            "PHASE_LOOP_LEGIBLE_AUTHORITY_MANIFEST",
            source_repo / "plans" / "manifest.json",
        )
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _source_binding_events(source_repo: Path, rel: str) -> list[dict]:
    manifest = _source_authority_manifest(source_repo)
    entry = next(item for item in manifest["plans"] if item["file"] == rel)
    return [
        json.loads(json.dumps(event))
        for event in entry["lifecycle"]
        if any(
            key in event.get("metadata", {})
            for key in ("legible_plan_contract", "digest_rebind")
        )
    ]


def _source_authority_history(source_repo: Path, rel: str) -> list[dict]:
    manifest = _source_authority_manifest(source_repo)
    entry = next(item for item in manifest["plans"] if item["file"] == rel)
    return json.loads(json.dumps(entry["plan_authority_history"]))


def _operational_fixture(
    repo: Path, *, stage: str = "candidate"
) -> tuple[str, dict[str, dict]]:
    source_repo = Path(__file__).resolve().parents[2]

    def git(*args: str, input_text: str | None = None) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            input=input_text,
        ).stdout.strip()

    def blob(commit: str, rel: str) -> str:
        return git("rev-parse", f"{commit}:{rel}")

    def tree(commit: str) -> str:
        return git("rev-parse", f"{commit}^{{tree}}")

    cli_path = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "cli.py"
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text("# fixture CLI\n", encoding="utf-8")
    roadmap_v1 = repo / "specs" / "phase-plans-v1.md"
    roadmap_v1.write_text(
        "# Roadmap\n\n> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v10.md` (2026-07-29)\n\n"
        "### Phase 0 - Old (OLD)\n",
        encoding="utf-8",
    )
    roadmap_v10 = repo / "specs" / "phase-plans-v10.md"
    roadmap_v10.write_bytes((source_repo / "specs" / "phase-plans-v10.md").read_bytes())
    sidecar_path = repo / roadmap_assumptions.PROBE_SIDECAR_REL
    sidecar_path.write_bytes(
        (
            source_repo
            / "phase-loop-runtime"
            / "tests"
            / "fixtures"
            / "roadmap-assumption-probes-v10.json"
        ).read_bytes()
    )
    plan_path = repo / "plans" / "phase-plan-v10-LEGIBLE.md"
    owned_digest = hashlib.sha256("".join(f"{path}\n" for path in LEGIBLE_OWNED_PATHS).encode()).hexdigest()
    plan_path.write_text(
        "---\nphase: LEGIBLE\nlegible_owned_paths_count: 18\n"
        f"legible_owned_paths_sha256: {owned_digest}\n---\n# LEGIBLE fixture\n",
        encoding="utf-8",
    )
    registry_path = repo / "specs" / "roadmap-status.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "roadmap_status_manifest.v1",
                "selected_roadmap": "specs/phase-plans-v10.md",
                "roadmaps": [
                    {"path": "specs/phase-plans-v1.md", "status": "superseded"},
                    {"path": "specs/phase-plans-v10.md", "status": "active"},
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for rel in LEGIBLE_OWNED_PATHS:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# fixture {rel}\n", encoding="utf-8")

    frozen_nodeids = tuple(
        f"phase-loop-runtime/tests/test_legible_{'roadmap_contract' if index < 64 else 'evidence'}.py::"
        f"test_fixture_{index:03d}"
        for index in range(84)
    )
    frozen_by_path = (
        ("phase-loop-runtime/tests/test_legible_roadmap_contract.py", frozen_nodeids[:64]),
        ("phase-loop-runtime/tests/test_legible_evidence.py", frozen_nodeids[64:]),
    )
    for rel, _nodeids in frozen_by_path:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# pre-landing test placeholder\n", encoding="utf-8")
    pr_delta_path = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "panel_invoker.py"
    pr_delta_path.write_text("# base panel invoker\n", encoding="utf-8")
    manifest_path = repo / "plans" / "manifest.json"
    plan_digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    roadmap_digest = hashlib.sha256(roadmap_v10.read_bytes()).hexdigest()
    frozen_binding_events = _source_binding_events(
        source_repo, "plans/phase-plan-v10-LEGIBLE.md"
    )
    frozen_authority_history = _source_authority_history(
        source_repo, "plans/phase-plan-v10-LEGIBLE.md"
    )
    manifest_path.write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "file": "plans/phase-plan-v10-LEGIBLE.md",
                        "phase_alias": "LEGIBLE",
                        "roadmap_ref": {"file": "specs/phase-plans-v10.md"},
                        "plan_authority_history": [
                            *frozen_authority_history,
                            {
                                "schema": "plan_current_authority.v1",
                                "source": "Consiliency/agent-harness#647",
                                "plan_sha256": plan_digest,
                                "roadmap_sha256": roadmap_digest,
                            }
                        ],
                        "lifecycle": [
                            *frozen_binding_events,
                            {
                                "metadata": {
                                    "legible_plan_contract": {
                                        **LEGIBLE_CONTRACT_FIXED_FIELDS,
                                        "plan_sha256": plan_digest,
                                        "roadmap_sha256": roadmap_digest,
                                        "owned_paths": list(LEGIBLE_OWNED_PATHS),
                                        "owned_paths_count": len(LEGIBLE_OWNED_PATHS),
                                        "owned_paths_sha256": owned_digest,
                                        "test_paths": [rel for rel, _ in frozen_by_path],
                                    }
                                }
                            },
                            {"metadata": {"note": "ordinary later lifecycle event"}},
                        ],
                    }
                ]
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "operational base"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    refresh_base = git("rev-parse", "HEAD")

    git("switch", "-c", "refresh-work", refresh_base)
    body_ancestors: list[str] = []
    for index in range(6):
        with pr_delta_path.open("a", encoding="utf-8") as stream:
            stream.write(f"# reviewed external delta {index + 1}\n")
        git("add", pr_delta_path.relative_to(repo).as_posix())
        git("commit", "-m", f"external PR row {index + 1}")
        body_ancestors.append(git("rev-parse", "HEAD"))
    refresh_parent = body_ancestors[-1]
    pr_head = git(
        "commit-tree",
        tree(refresh_parent),
        "-p",
        refresh_parent,
        "-p",
        refresh_base,
        input_text="refresh merge\n",
    )
    git("branch", "pr-head", pr_head)

    git("switch", "-c", "target", refresh_base)
    for rel, nodeids in frozen_by_path:
        (repo / rel).write_text(
            "import pytest\n"
            f"pytestmark = pytest.mark.skipif(True, reason={LEGIBLE_SKIP_REASON!r})\n"
            f"LEGIBLE_EXPECTED_NODEIDS_V1 = {nodeids!r}\n",
            encoding="utf-8",
        )
    git("add", *(rel for rel, _ in frozen_by_path))
    git("commit", "-m", "tests-only landing")
    original_tests_landing = git("rev-parse", "HEAD")
    corrective_path = repo / frozen_by_path[0][0]
    corrective_path.write_text(
        corrective_path.read_text(encoding="utf-8") + "# canonical roadmap fixture binding\n",
        encoding="utf-8",
    )
    git("add", corrective_path.relative_to(repo).as_posix())
    git("commit", "-m", "test-only corrective anchor")
    implementation_base = git("rev-parse", "HEAD")

    git("switch", "-c", "candidate", implementation_base)
    candidate_path = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "roadmap_assumptions.py"
    candidate_path.write_text("# fixture roadmap assumptions\nCAPABILITY = True\n", encoding="utf-8")
    capability_path = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "legible_evidence.py"
    capability_path.write_text('LEGIBLE_CAPABILITY_VERSION = "legible.v1"\n', encoding="utf-8")
    git(
        "add",
        candidate_path.relative_to(repo).as_posix(),
        capability_path.relative_to(repo).as_posix(),
    )
    git("commit", "-m", "phase candidate")
    candidate = git("rev-parse", "HEAD")

    git("switch", "target")
    subprocess.run(
        ["git", "merge", "--no-ff", "pr-head", "-m", "server merge"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    server_merge = git("rev-parse", "HEAD")

    subprocess.run(["git", "switch", "candidate"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "merge", "--no-ff", "target", "-m", "target integration"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    integration = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/codex/fixture", integration)
    implementation_merge = git(
        "commit-tree",
        tree(integration),
        "-p",
        server_merge,
        "-p",
        integration,
        input_text="implementation PR merge\n",
    )
    git("branch", "canonical-main", implementation_merge)
    expected_head = integration if stage == "candidate" else implementation_merge
    if stage == "canonical-main":
        subprocess.run(
            ["git", "switch", "canonical-main"], cwd=repo, check=True, capture_output=True
        )

    evidence_dir = repo / "evidence"
    evidence_dir.mkdir()

    def write_junit(path: Path, status: str) -> None:
        root = ET.Element("testsuite", tests="84")
        for index, nodeid in enumerate(frozen_nodeids):
            file_part, test_name = nodeid.split("::", 1)
            case = ET.SubElement(
                root,
                "testcase",
                classname=file_part.removesuffix(".py"),
                name=test_name,
            )
            if status == "skipped":
                ET.SubElement(case, "skipped", type="pytest.skip", message=LEGIBLE_SKIP_REASON)
            elif status == "failure":
                ET.SubElement(case, "failure", message=f"LEGIBLE_RED::fixture-{index:03d}: expected")
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    default_junit = evidence_dir / "default.junit.xml"
    forced_red_junit = evidence_dir / "forced-red.junit.xml"
    final_junit = evidence_dir / "final.junit.xml"
    write_junit(default_junit, "skipped")
    write_junit(forced_red_junit, "failure")
    write_junit(final_junit, "passed")
    default_log = evidence_dir / "default.log"
    forced_red_log = evidence_dir / "forced-red.log"
    final_log = evidence_dir / "final.log"
    default_log.write_text(
        "\n".join(f"{nodeid} SKIPPED LEGIBLE capability absent" for nodeid in frozen_nodeids) + "\n",
        encoding="utf-8",
    )
    forced_red_log.write_text(
        "\n".join(
            f"{nodeid} FAILED anchor_reached LEGIBLE_RED::fixture-{index:03d}"
            for index, nodeid in enumerate(frozen_nodeids)
        )
        + "\n",
        encoding="utf-8",
    )
    final_log.write_text(
        "\n".join(f"{nodeid} PASSED" for nodeid in frozen_nodeids) + "\n",
        encoding="utf-8",
    )
    bundle_path = evidence_dir / "implementation-review-bundle.md"
    bundle_path.write_text(f"exact head: {expected_head}\n", encoding="utf-8")
    panel_models = {
        "claude": "claude-fable-5-1",
        "codex": "gpt-5.6-sol",
        "gemini": "gemini-3.8-flash",
        "grok": "grok-4.6",
    }
    leg_records = []
    leg_paths: list[Path] = []
    for leg, model in panel_models.items():
        leg_path = evidence_dir / f"implementation-panel-{leg}.json"
        leg_payload = {
            "leg": leg,
            "model": model,
            "seat_key": f"{leg}:{model}:max:review",
            "status": "OK",
            "usable": True,
            "verdict": "AGREE",
            "text": "Exact-head review complete.\n\nAGREE",
        }
        leg_path.write_text(json.dumps(leg_payload, sort_keys=True) + "\n", encoding="utf-8")
        leg_paths.append(leg_path)
        leg_records.append(
            {
                **{key: leg_payload[key] for key in ("leg", "model", "seat_key", "status", "usable", "verdict")},
                "artifact_path": leg_path.relative_to(repo).as_posix(),
                "artifact_sha256": hashlib.sha256(leg_path.read_bytes()).hexdigest(),
            }
        )
    panel_path = evidence_dir / "implementation-panel.json"
    panel_path.write_text(
        json.dumps(
            {
                "schema": "advisor_board.v1",
                "head": expected_head,
                "bundle_path": bundle_path.relative_to(repo).as_posix(),
                "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
                "legs": leg_records,
                "verdicts": {model: "AGREE" for model in panel_models.values()},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    probe_declarations = json.loads(sidecar_path.read_text(encoding="utf-8"))["probes"]
    probe_by_id = {probe["id"]: probe for probe in probe_declarations}

    def passing_observation(probe: dict) -> dict:
        if probe["kind"] == "reviewtruth_fable_transition":
            return {
                "issue_state": "OPEN",
                "native_fill_request": False,
                "seat_result": "UNAVAILABLE/tui_adapter_required",
                "first_party_route_available": True,
                "fable_leg": "succeeded",
            }
        observation: dict[str, object] = {}
        expected = probe["expected"]
        for key, value in expected.items():
            if key == "required_present":
                observation.update({field: "present" for field in value})
            elif key == "required_atoms":
                observation.setdefault("atoms", []).extend(value)
            elif key == "forbidden_atoms":
                observation.setdefault("atoms", [])
            elif key == "required_edges":
                observation["edges"] = value
            elif key == "fields":
                observation["fields"] = value
            elif key == "must_agree":
                if value:
                    observation["values"] = [expected["agreed_value"]]
            elif key not in {"agreed_value", "declared_states"}:
                observation[key] = value
        return observation

    probe_records = []
    probe_paths: list[Path] = []
    for probe_id in LEGIBLE_PROBE_IDS:
        state = "pending" if probe_id == "LEGIBLE-A3-REVIEWTRUTH-TRANSITION" else "resolved"
        probe_path = evidence_dir / f"{probe_id.lower()}.json"
        probe_bytes = (
            json.dumps(
                {
                    "probe_id": probe_id,
                    "state": state,
                    "observation": passing_observation(probe_by_id[probe_id]),
                },
                sort_keys=True,
            )
            + "\n"
        ).encode()
        probe_path.write_bytes(probe_bytes)
        probe_paths.append(probe_path)
        probe_records.append(
            {
                "schema": "roadmap_assumption_probe.v1",
                "probe_id": probe_id,
                "state": state,
                "response_path": probe_path.relative_to(repo).as_posix(),
                "response_sha256": hashlib.sha256(probe_bytes).hexdigest(),
                "response_byte_length": len(probe_bytes),
            }
        )
    pr_snapshot_path = evidence_dir / "agent-harness-347-snapshot.json"
    changed_paths = [pr_delta_path.relative_to(repo).as_posix()]
    pr_body = "LEGIBLE exact transition"
    pr_snapshot = {
        "base": implementation_base,
        "refresh_base": refresh_base,
        "state": "MERGED",
        "merged_at": "2026-08-01T16:00:00Z",
        "body": pr_body,
        "body_ancestor_commits": body_ancestors,
        "changed_paths": changed_paths,
        "checks": ["SUCCESS"],
        "head": pr_head,
        "head_tree": tree(pr_head),
        "merge_commit": server_merge,
        "merge_tree": tree(server_merge),
        "review_decision": "APPROVED",
        "github_review_count": 1,
        "refresh_parents": [refresh_parent, refresh_base],
        "remote_head_oid": pr_head,
    }
    pr_snapshot_path.write_text(json.dumps(pr_snapshot, sort_keys=True) + "\n", encoding="utf-8")

    def file_record(path: Path) -> dict[str, object]:
        data = path.read_bytes()
        return {
            "path": path.relative_to(repo).as_posix(),
            "byte_length": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def execution_record(
        *,
        junit_path: Path,
        log_path: Path,
        execution_head: str,
        exit_code: int,
        marker_present: bool,
        passed: int,
        skipped: int,
        failed: int,
    ) -> dict[str, object]:
        log_bytes = log_path.read_bytes()
        return {
            "argv": [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_legible_roadmap_contract.py",
                "tests/test_legible_evidence.py",
                f"--junitxml={junit_path.resolve()}",
                "-q",
            ],
            "execution_head": execution_head,
            "exit_code": exit_code,
            "capability_marker_present": marker_present,
            "log_path": log_path.relative_to(repo).as_posix(),
            "log_byte_length": len(log_bytes),
            "log_sha256": hashlib.sha256(log_bytes).hexdigest(),
            "junit_path": junit_path.relative_to(repo).as_posix(),
            "passed": passed,
            "skipped": skipped,
            "failed": failed,
            "errors": 0,
        }

    sections = {
        "roadmap_status": legible_evidence.collect_roadmap_status(repo, required=True),
        "chronology": {
            "refresh_base": refresh_base,
            "original_tests_landing": original_tests_landing,
            "tests_landing": implementation_base,
            "implementation_base": implementation_base,
            "phase_candidate": candidate,
            "pr_head": pr_head,
            "server_merge": server_merge,
            "candidate_head": integration,
            "candidate_remote_ref": "refs/remotes/origin/codex/fixture",
            "candidate_remote_oid": integration,
            "implementation_pull_request": {
                "repository": "Consiliency/agent-harness",
                "number": 430,
                "state": "OPEN" if stage == "candidate" else "MERGED",
                "base_ref": "main",
                "head": integration,
                "body_sha256": hashlib.sha256(b"LEGIBLE implementation delivery").hexdigest(),
                "merged_at": None if stage == "candidate" else "2026-08-02T05:00:00Z",
                "merge_commit": None if stage == "candidate" else implementation_merge,
                "parents": [] if stage == "candidate" else [server_merge, integration],
            },
            "plan_path": "plans/phase-plan-v10-LEGIBLE.md",
            "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "roadmap_path": "specs/phase-plans-v10.md",
            "roadmap_sha256": hashlib.sha256(roadmap_v10.read_bytes()).hexdigest(),
            "owned_paths": list(LEGIBLE_OWNED_PATHS),
            "owned_paths_count": len(LEGIBLE_OWNED_PATHS),
            "owned_paths_sha256": owned_digest,
            "original_frozen_test_blobs": {
                rel: blob(original_tests_landing, rel) for rel, _ in frozen_by_path
            },
            "frozen_test_blobs": {
                rel: {
                    ref: blob(commit, rel)
                    for ref, commit in {
                        "tests_landing": implementation_base,
                        "implementation_base": implementation_base,
                        "phase_candidate": candidate,
                        "candidate_head": integration,
                    }.items()
                }
                for rel, _ in frozen_by_path
            },
        },
        "process_attestations": {
            "builder": {"run_id": "builder-1", "process_start_token": "builder-token"},
            "transition": {
                "run_id": "transition-1",
                "parent_run_id": "builder-1",
                "process_start_token": "transition-token",
            },
            "candidate": {
                "run_id": "candidate-1",
                "parent_run_id": "transition-1",
                "head": integration,
                "bootstrap_head": integration,
                "repo_realpath": str(repo.resolve()),
                "cli_path": str(cli_path),
                "cli_sha256": hashlib.sha256(cli_path.read_bytes()).hexdigest(),
                "python_executable": sys.executable,
                "process_start_token": "candidate-token",
                "loaded_runtime_blobs": {
                    rel: {
                        "path": rel,
                        "blob_oid": blob(integration, rel),
                        "byte_length": len((repo / rel).read_bytes()),
                        "sha256": hashlib.sha256((repo / rel).read_bytes()).hexdigest(),
                    }
                    for rel in LEGIBLE_LOADED_RUNTIME_PATHS
                },
            },
        },
        "test_execution": {
            "nodeid_count": 84,
            "nodeid_digest": hashlib.sha256("\n".join(sorted(frozen_nodeids)).encode()).hexdigest(),
            "default": execution_record(
                junit_path=default_junit,
                log_path=default_log,
                execution_head=implementation_base,
                exit_code=0,
                marker_present=False,
                passed=0,
                skipped=84,
                failed=0,
            ),
            "forced_red": execution_record(
                junit_path=forced_red_junit,
                log_path=forced_red_log,
                execution_head=implementation_base,
                exit_code=1,
                marker_present=False,
                passed=0,
                skipped=0,
                failed=84,
            )
            | {
                "failure_markers": {
                    nodeid: f"fixture-{index:03d}" for index, nodeid in enumerate(frozen_nodeids)
                },
                "anchor_nodeids": list(frozen_nodeids),
            },
            "final": execution_record(
                junit_path=final_junit,
                log_path=final_log,
                execution_head=expected_head,
                exit_code=0,
                marker_present=True,
                passed=84,
                skipped=0,
                failed=0,
            ),
        },
        "pull_request": {
            "repository": "Consiliency/agent-harness",
            "number": 347,
            "state": "MERGED",
            "merged_at": "2026-08-01T16:00:00Z",
            "review_decision": "APPROVED",
            "github_review_count": 1,
            "base": implementation_base,
            "refresh_base": refresh_base,
            "head": pr_head,
            "remote_head_oid": pr_head,
            "merge_commit": server_merge,
            "parents": [implementation_base, pr_head],
            "refresh_parents": [refresh_parent, refresh_base],
            "body_ancestor_commits": body_ancestors,
            "snapshot_path": pr_snapshot_path.relative_to(repo).as_posix(),
            "snapshot_sha256": hashlib.sha256(pr_snapshot_path.read_bytes()).hexdigest(),
            "body_sha256": hashlib.sha256(pr_body.encode()).hexdigest(),
            "changed_paths": changed_paths,
            "comment_tokens_equal": True,
            "external_blobs": {
                "refresh_base": blob(refresh_base, changed_paths[0]),
                "implementation_base": blob(implementation_base, changed_paths[0]),
                "phase_candidate": blob(candidate, changed_paths[0]),
                "head": blob(pr_head, changed_paths[0]),
                "server_merge": blob(server_merge, changed_paths[0]),
                "integration": blob(integration, changed_paths[0]),
            },
            "recomputed_trees": {
                "refresh": tree(pr_head),
                "server": tree(server_merge),
                "integration": tree(integration),
            },
        },
        "target_integration": {
            "candidate": candidate,
            "server_merge": server_merge,
            "integration": integration,
            "parents": [candidate, server_merge],
            "recomputed_tree": tree(integration),
        },
        "assumption_probes": {
            "execution_head": expected_head,
            "records": probe_records,
        },
        "artifacts": {
            "records": [
                file_record(registry_path),
                file_record(roadmap_v10),
                file_record(sidecar_path),
                file_record(plan_path),
                file_record(manifest_path),
                *(file_record(repo / rel) for rel in LEGIBLE_LOADED_RUNTIME_PATHS),
                *(file_record(repo / rel) for rel, _ in frozen_by_path),
                file_record(default_junit),
                file_record(forced_red_junit),
                file_record(final_junit),
                file_record(default_log),
                file_record(forced_red_log),
                file_record(final_log),
                file_record(bundle_path),
                file_record(panel_path),
                *(file_record(path) for path in leg_paths),
                *(file_record(path) for path in probe_paths),
                file_record(pr_snapshot_path),
            ]
        },
    }
    if stage == "canonical-main":
        candidate_process = sections["process_attestations"]["candidate"]
        sections["process_attestations"]["canonical_main"] = {
            **candidate_process,
            "run_id": "canonical-1",
            "parent_run_id": candidate_process["run_id"],
            "head": expected_head,
            "bootstrap_head": expected_head,
            "process_start_token": "canonical-token",
            "loaded_runtime_blobs": {
                rel: {
                    "path": rel,
                    "blob_oid": blob(expected_head, rel),
                    "byte_length": len((repo / rel).read_bytes()),
                    "sha256": hashlib.sha256((repo / rel).read_bytes()).hexdigest(),
                }
                for rel in LEGIBLE_LOADED_RUNTIME_PATHS
            },
        }
    return expected_head, sections


def test_legacy_fable_observation_without_external_status_remains_pending(tmp_path, monkeypatch):
    raw = {
        "issue": {"number": 396, "state": "OPEN", "stateReason": None},
        "route": {"provider": "first-party-claude", "capability": "ok"},
        "leg": {
            "status": "UNAVAILABLE",
            "final_verdict_token": "tui_adapter_required",
            "elapsed_ms": 1,
        },
        "response": {},
    }
    monkeypatch.setattr(legible_evidence, "_invoke_reviewtruth_fable_adapter", lambda *args, **kwargs: raw)

    record = legible_evidence.run_reviewtruth_fable_probe(
        tmp_path, repository="Consiliency/agent-harness", issue=396, model="claude-fable-5"
    )

    assert record.state == "pending"


def test_manifest_check_rejects_extra_registered_plan(tmp_path):
    repo = make_repo(tmp_path)
    canonical = _commit_plan(repo)
    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps({"plans": [{"file": canonical}, {"file": "plans/phase-plan-v1-GHOST.md"}]}),
        encoding="utf-8",
    )

    result = check(repo)

    assert result.exit_code == 1
    assert [(item.path, item.kind) for item in result.malformed] == [
        ("plans/phase-plan-v1-GHOST.md", "extra")
    ]


def test_manifest_check_rejects_duplicate_registered_plan_path(tmp_path):
    repo = make_repo(tmp_path)
    canonical = _commit_plan(repo)
    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps({"plans": [{"file": canonical}, {"file": canonical}]}),
        encoding="utf-8",
    )

    result = check(repo)

    assert result.exit_code == 1
    assert [(item.path, item.kind) for item in result.malformed] == [(canonical, "duplicate")]


def test_manifest_check_rejects_authoritative_plan_digest_drift(tmp_path):
    repo = make_repo(tmp_path)
    canonical = _commit_plan(repo)
    roadmap = repo / "specs" / "current-roadmap.md"
    roadmap.write_text("# Current roadmap\n", encoding="utf-8")
    roadmap_digest = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "plans": [
                        {
                            "file": canonical,
                            "phase_alias": "RUNNER",
                            "roadmap_ref": {"file": "specs/current-roadmap.md"},
                            "plan_authority_history": [
                            {
                                "schema": "plan_current_authority.v1",
                                "source": "agent-harness#620",
                                "plan_sha256": "0" * 64,
                                    "roadmap_sha256": roadmap_digest,
                            }
                        ],
                        "lifecycle": [
                            {
                                    "metadata": {
                                        "legible_plan_contract": {
                                            "plan_sha256": "1" * 64,
                                            "roadmap_sha256": roadmap_digest,
                                        }
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = check(repo)

    assert result.exit_code == 1
    assert (canonical, "plan-digest") in [(item.path, item.kind) for item in result.malformed]

    external = tmp_path / "external-roadmap.md"
    external.write_text("# External roadmap\n", encoding="utf-8")
    roadmap.unlink()
    roadmap.symlink_to(external)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["plans"][0]["roadmap_ref"] = {"file": "specs/current-roadmap.md"}
    payload["plans"][0]["plan_authority_history"][-1].update(
        {
            "plan_sha256": hashlib.sha256((repo / canonical).read_bytes()).hexdigest(),
            "roadmap_sha256": hashlib.sha256(external.read_bytes()).hexdigest(),
        }
    )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    symlink_result = check(repo)

    assert symlink_result.exit_code == 1
    assert (canonical, "plan-contract") in [
        (item.path, item.kind) for item in symlink_result.malformed
    ]


def test_regular_repo_file_hash_rejects_ancestor_swap(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    nested = repo / "authority"
    nested.mkdir()
    (nested / "bound.md").write_text("trusted bytes\n", encoding="utf-8")
    moved = tmp_path / "moved-authority"
    external = tmp_path / "external-authority"
    external.mkdir()
    (external / "bound.md").write_text("outside bytes\n", encoding="utf-8")
    real_open = os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "authority" and dir_fd is not None and not swapped:
            nested.rename(moved)
            nested.symlink_to(external, target_is_directory=True)
            swapped = True
        return descriptor

    monkeypatch.setattr(plan_manifest.os, "open", swapping_open)

    assert plan_manifest._regular_repo_file_sha256(repo, "authority/bound.md") is None
    assert swapped


def test_regular_repo_file_hash_rejects_ancestor_swap_after_hash(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    nested = repo / "authority"
    nested.mkdir()
    target = nested / "bound.md"
    target.write_text("trusted bytes\n", encoding="utf-8")
    target_inode = target.stat().st_ino
    moved = tmp_path / "moved-authority"
    external = tmp_path / "external-authority"
    external.mkdir()
    (external / "bound.md").write_text("outside bytes\n", encoding="utf-8")
    real_fstat = os.fstat
    target_fstats = 0

    def swapping_fstat(descriptor):
        nonlocal target_fstats
        result = real_fstat(descriptor)
        if result.st_ino == target_inode:
            target_fstats += 1
            if target_fstats == 2:
                nested.rename(moved)
                nested.symlink_to(external, target_is_directory=True)
        return result

    monkeypatch.setattr(plan_manifest.os, "fstat", swapping_fstat)

    assert plan_manifest._regular_repo_file_sha256(repo, "authority/bound.md") is None
    assert target_fstats >= 2


def test_regular_repo_file_hash_rejects_swap_after_final_child_stat(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path)
    nested = repo / "authority"
    nested.mkdir()
    (nested / "bound.md").write_text("trusted bytes\n", encoding="utf-8")
    moved = tmp_path / "moved-authority"
    external = tmp_path / "external-authority"
    external.mkdir()
    (external / "bound.md").write_text("outside bytes\n", encoding="utf-8")
    real_stat = os.stat
    directory_stats = 0

    def swapping_stat(path, *args, **kwargs):
        nonlocal directory_stats
        result = real_stat(path, *args, **kwargs)
        if path == "authority" and kwargs.get("dir_fd") is not None:
            directory_stats += 1
            if directory_stats == 3:
                nested.rename(moved)
                nested.symlink_to(external, target_is_directory=True)
        return result

    monkeypatch.setattr(plan_manifest.os, "stat", swapping_stat)

    assert plan_manifest._regular_repo_file_sha256(repo, "authority/bound.md") is None
    assert directory_stats >= 3


def test_regular_repo_file_hash_rejects_write_after_former_final_fstat(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path)
    authority = repo / "authority"
    authority.mkdir()
    target = authority / "bound.md"
    target.write_text("trusted bytes\n", encoding="utf-8")
    target_inode = target.stat().st_ino
    real_fstat = os.fstat
    target_fstats = 0

    def writing_fstat(descriptor):
        nonlocal target_fstats
        result = real_fstat(descriptor)
        if result.st_ino == target_inode:
            target_fstats += 1
            if target_fstats == 4:
                target.write_text("drifted bytes\n", encoding="utf-8")
        return result

    monkeypatch.setattr(plan_manifest.os, "fstat", writing_fstat)

    assert plan_manifest._regular_repo_file_sha256(repo, "authority/bound.md") is None
    assert target_fstats >= 4


def test_regular_repo_file_hash_rejects_fifo_without_blocking(tmp_path, monkeypatch):
    if not hasattr(os, "mkfifo") or not hasattr(signal, "SIGALRM"):
        pytest.skip("FIFO alarm regression requires POSIX")
    repo = make_repo(tmp_path)
    authority = repo / "authority"
    authority.mkdir()
    os.mkfifo(authority / "bound.md")
    real_open = os.open
    opened_fifo = False

    def tracking_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal opened_fifo
        if path == "bound.md" and dir_fd is not None:
            opened_fifo = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(plan_manifest.os, "open", tracking_open)
    previous_handler = signal.signal(
        signal.SIGALRM,
        lambda *_args: (_ for _ in ()).throw(TimeoutError("FIFO open blocked")),
    )
    signal.setitimer(signal.ITIMER_REAL, 2)
    started = time.monotonic()
    try:
        result = plan_manifest._regular_repo_file_sha256(repo, "authority/bound.md")
    finally:
        elapsed = time.monotonic() - started
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    assert result is None
    assert elapsed < 1
    assert not opened_fifo


def test_regular_repo_file_hash_rejects_device_swap_before_open(tmp_path, monkeypatch):
    if not hasattr(os, "mkfifo") or not hasattr(signal, "SIGALRM"):
        pytest.skip("device-swap alarm regression requires POSIX")
    repo = make_repo(tmp_path)
    authority = repo / "authority"
    authority.mkdir()
    target = authority / "bound.md"
    target.write_text("trusted bytes\n", encoding="utf-8")
    replacement = authority / "replacement"
    os.mkfifo(replacement)
    real_open = os.open
    swapped = False
    data_opened = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped, data_opened
        if path == "bound.md" and dir_fd is not None and not swapped:
            replacement.replace(target)
            swapped = True
        if isinstance(path, str) and path.startswith("/proc/self/fd/"):
            data_opened = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(plan_manifest.os, "open", swapping_open)
    previous_handler = signal.signal(
        signal.SIGALRM,
        lambda *_args: (_ for _ in ()).throw(TimeoutError("device open blocked")),
    )
    signal.setitimer(signal.ITIMER_REAL, 2)
    started = time.monotonic()
    try:
        result = plan_manifest._regular_repo_file_sha256(repo, "authority/bound.md")
    finally:
        elapsed = time.monotonic() - started
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    assert result is None
    assert elapsed < 1
    assert swapped
    assert not data_opened


def test_regular_repo_file_hash_uses_darwin_clone_without_data_open(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path)
    authority = repo / "authority"
    authority.mkdir()
    target = authority / "bound.md"
    target.write_text("portable bytes\n", encoding="utf-8")
    expected = target.read_bytes()
    real_open = os.open
    target_opened = False

    def tracking_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal target_opened
        if path == "bound.md" and dir_fd is not None:
            target_opened = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(plan_manifest.os, "open", tracking_open)
    monkeypatch.delattr(plan_manifest.os, "O_PATH", raising=False)
    monkeypatch.setattr(plan_manifest.sys, "platform", "darwin")
    monkeypatch.setattr(
        plan_manifest,
        "_darwin_clonefileat_bytes",
        lambda *_args, **_kwargs: expected,
    )

    digest = plan_manifest._regular_repo_file_sha256(repo, "authority/bound.md")

    assert digest == hashlib.sha256(expected).hexdigest()
    assert not target_opened


def test_required_roadmap_registry_absence_is_typed_failure(tmp_path):
    repo = make_repo(tmp_path)
    marker = repo / "plans" / "phase-plan-v10-LEGIBLE.md"
    marker.write_text("---\nphase: LEGIBLE\n---\n# LEGIBLE\n", encoding="utf-8")

    with pytest.raises(roadmap_lint.RoadmapStatusError):
        roadmap_lint.validate_roadmap_status_coherence(repo, required=True)


def test_manifest_scan_propagates_roadmap_status_failure(tmp_path):
    repo = make_repo(tmp_path)
    registry = repo / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("{}\n", encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    with pytest.raises(roadmap_lint.RoadmapStatusError):
        plan_manifest.canonical_plan_files(repo, head)


def test_docs_catalog_check_rejects_absence(tmp_path):
    repo = make_repo(tmp_path)

    result = docs_freshness.check_catalog(repo)

    assert result.exit_code == 1
    assert result.findings == ("catalog is absent",)


def test_legible_verify_rejects_head_that_does_not_resolve(tmp_path):
    repo = make_repo(tmp_path)
    args = SimpleNamespace(repo=str(repo), stage="candidate", head="0" * 40)
    status_record = {"roadmaps": []}

    with (
        patch.object(legible_evidence, "collect_roadmap_status", return_value=status_record),
        patch.object(legible_evidence, "validate_roadmap_status_evidence"),
    ):
        assert legible_evidence._cmd_verify(args) == 1


def test_legible_verify_rejects_missing_operational_aggregate(tmp_path):
    repo = make_repo(tmp_path)
    head, _sections = _operational_fixture(repo)
    args = SimpleNamespace(repo=str(repo), stage="candidate", head=head)

    assert legible_evidence._cmd_verify(args) == 1


def test_plan_aware_validation_reopens_bound_sidecar_bytes(tmp_path):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "probe"
    run_verification(repo, run_dir, [], None, None, 10, phase_alias="LEGIBLE")
    sidecar_path = run_dir / "legible-verification-sidecar.json"
    original = b'{"schema":"roadmap_assumption_probe.v1","state":"pending"}'
    sidecar_path.write_bytes(original)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    record = legible_evidence.bind_verification_sidecar(
        repo,
        run_dir=run_dir,
        stage="candidate",
        expected_head=head,
        bootstrap_head=head,
        process_start_token="fresh-process-token",
    )
    artifact_path = run_dir / ARTIFACT_NAME
    _bind_sidecar_extension(
        artifact_path,
        namespace=legible_evidence.EXTENSION_NAMESPACE,
        record=record.__dict__,
    )
    assert validate_verification_artifact_for_plan(
        artifact_path, (legible_evidence.EXTENSION_NAMESPACE,)
    ).ok

    sidecar_path.write_bytes(original.replace(b'"pending"', b'"resolve"'))

    result = validate_verification_artifact_for_plan(
        artifact_path, (legible_evidence.EXTENSION_NAMESPACE,)
    )
    assert not result.ok
    assert result.code == "sidecar_digest_drift"


def test_resolved_fable_observation_preserves_native_fill_binding_state():
    raw = {
        "issue": {"number": 396, "state": "CLOSED", "stateReason": "completed"},
        "route": {"provider": "first-party-claude", "capability": "ok"},
        "leg": {
            "status": "OK",
            "external_status": "OK",
            "native_fill_request": True,
            "verdict_bound": True,
            "seat_count": "FULL",
        },
        "response": {},
    }

    flattened = legible_evidence._flatten_reviewtruth_observation(raw)

    assert flattened["verdict_bound"] is True
    assert flattened["seat_count"] == "FULL"
    assert _classify_reviewtruth_transition(flattened) == "resolved"


@pytest.mark.parametrize(
    ("registered_path", "expected_kind"),
    [
        ("plans/nested/phase-plan-v1-GHOST.md", "noncanonical"),
        ("/plans/phase-plan-v1-GHOST.md", "path-escape"),
        (r"plans\\phase-plan-v1-GHOST.md", "noncanonical"),
    ],
)
def test_manifest_check_rejects_malformed_registered_plan_path(tmp_path, registered_path, expected_kind):
    repo = make_repo(tmp_path)
    canonical = _commit_plan(repo)
    (repo / "plans" / "manifest.json").write_text(
        json.dumps({"plans": [{"file": canonical}, {"file": registered_path}]}),
        encoding="utf-8",
    )

    result = check(repo)

    assert result.exit_code == 1
    assert (registered_path, expected_kind) in [(item.path, item.kind) for item in result.malformed]


def test_catalog_check_rejects_missing_current_rescan_entry(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "CHANGELOG.md").write_text("# Changes\n", encoding="utf-8")
    catalog = repo / ".claude" / "docs-catalog.json"
    catalog.parent.mkdir()
    catalog.write_text(json.dumps([{"path": "CHANGELOG.md"}]), encoding="utf-8")

    result = check_catalog(repo)

    assert result.exit_code == 1
    assert "README.md" in "\n".join(result.findings)


def test_sidecar_binder_rejects_invalid_v2_artifact_before_resealing(tmp_path):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "probe"
    run_verification(repo, run_dir, [], None, None, 10, phase_alias="LEGIBLE")
    artifact_path = run_dir / ARTIFACT_NAME
    log_path = run_dir / LOG_NAME
    log_path.write_bytes(b"tampered-before-bind\n" + log_path.read_bytes())
    assert validate_verification_artifact(artifact_path).code == "log_sha256_mismatch"
    sidecar_path = run_dir / "legible-verification-sidecar.json"
    sidecar_path.write_text("{}", encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    record = legible_evidence.bind_verification_sidecar(
        repo,
        run_dir=run_dir,
        stage="candidate",
        expected_head=head,
        bootstrap_head=head,
        process_start_token="fresh-process-token",
    )

    with pytest.raises(VerificationArtifactContractError) as excinfo:
        _bind_sidecar_extension(
            artifact_path,
            namespace=legible_evidence.EXTENSION_NAMESPACE,
            record=record.__dict__,
        )

    assert excinfo.value.code == "log_sha256_mismatch"


def test_sidecar_binder_allows_integrity_valid_nonzero_verification(tmp_path):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "probe"
    run_verification(
        repo,
        run_dir,
        [[sys.executable, "-c", "raise SystemExit(7)"]],
        None,
        None,
        10,
        phase_alias="LEGIBLE",
    )
    artifact_path = run_dir / ARTIFACT_NAME
    assert validate_verification_artifact(artifact_path).code == "nonzero_exit"
    sidecar_path = run_dir / "legible-verification-sidecar.json"
    sidecar_path.write_text("{}", encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    record = legible_evidence.bind_verification_sidecar(
        repo,
        run_dir=run_dir,
        stage="candidate",
        expected_head=head,
        bootstrap_head=head,
        process_start_token="fresh-process-token",
    )

    _bind_sidecar_extension(
        artifact_path,
        namespace=legible_evidence.EXTENSION_NAMESPACE,
        record=record.__dict__,
    )

    assert validate_verification_artifact_for_plan(
        artifact_path, (legible_evidence.EXTENSION_NAMESPACE,)
    ).code == "nonzero_exit"


def test_sidecar_binder_rejects_unsealed_v2_artifact(tmp_path):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "probe"
    run_verification(repo, run_dir, [], None, None, 10, phase_alias="LEGIBLE")
    artifact_path = run_dir / ARTIFACT_NAME
    log_path = run_dir / LOG_NAME
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    raw_log = log_path.read_bytes()
    seal_start = _artifact_seal_region_start(raw_log)
    assert seal_start is not None
    log_body = raw_log[:seal_start]
    log_path.write_bytes(log_body)
    payload["phase_alias"] = "ALTERED-BEFORE-BIND"
    payload["log_sha256"] = hashlib.sha256(log_body).hexdigest()
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert validate_verification_artifact(artifact_path).ok
    sidecar_path = run_dir / "legible-verification-sidecar.json"
    sidecar_path.write_text("{}", encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    record = legible_evidence.bind_verification_sidecar(
        repo,
        run_dir=run_dir,
        stage="candidate",
        expected_head=head,
        bootstrap_head=head,
        process_start_token="fresh-process-token",
    )

    with pytest.raises(VerificationArtifactContractError) as excinfo:
        _bind_sidecar_extension(
            artifact_path,
            namespace=legible_evidence.EXTENSION_NAMESPACE,
            record=record.__dict__,
        )

    assert excinfo.value.code == "artifact_seal_missing"


def test_plan_aware_validation_checks_sidecar_after_nonzero_exit(tmp_path):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "probe"
    run_verification(
        repo,
        run_dir,
        [[sys.executable, "-c", "raise SystemExit(7)"]],
        None,
        None,
        10,
        phase_alias="LEGIBLE",
    )
    sidecar_path = run_dir / "legible-verification-sidecar.json"
    sidecar_path.write_text("{}", encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    record = legible_evidence.bind_verification_sidecar(
        repo,
        run_dir=run_dir,
        stage="candidate",
        expected_head=head,
        bootstrap_head=head,
        process_start_token="fresh-process-token",
    )
    artifact_path = run_dir / ARTIFACT_NAME
    _bind_sidecar_extension(
        artifact_path,
        namespace=legible_evidence.EXTENSION_NAMESPACE,
        record=record.__dict__,
    )
    sidecar_path.write_text('{"drifted":true}', encoding="utf-8")

    result = validate_verification_artifact_for_plan(
        artifact_path, (legible_evidence.EXTENSION_NAMESPACE,)
    )

    assert not result.ok
    assert result.code == "sidecar_digest_drift"


def test_sidecar_binder_rejects_symlinked_declared_sidecar(tmp_path):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "probe"
    run_dir.mkdir(parents=True)
    target = repo / ".phase-loop" / "runs" / "other-sidecar.json"
    target.write_text("{}", encoding="utf-8")
    (run_dir / "legible-verification-sidecar.json").symlink_to(target)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    with pytest.raises(legible_evidence.LegibleSidecarError) as excinfo:
        legible_evidence.bind_verification_sidecar(
            repo,
            run_dir=run_dir,
            stage="candidate",
            expected_head=head,
            bootstrap_head=head,
            process_start_token="fresh-process-token",
        )

    assert excinfo.value.code == "sidecar_symlink"


def test_attest_command_is_registered_and_enforces_exact_head(tmp_path, capsys):
    from phase_loop_runtime import cli

    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    assert cli.main(
        [
            "attest",
            "--repo",
            str(repo),
            "--stage",
            "candidate",
            "--expected-head",
            head,
            "--builder-run-id",
            "builder-1",
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "candidate"
    assert payload["head"] == head


def test_attest_cli_without_repo_still_runs_preimport_bootstrap(tmp_path, monkeypatch):
    from phase_loop_runtime import cli

    repo = tmp_path / "repo"
    blobs = {}
    blob_by_rel = {}
    for index, rel in enumerate(cli._ATTEST_RUNTIME_PATHS, start=1):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# repo-local fixture {rel}\n", encoding="utf-8")
        blob_oid = f"{index:040x}"
        blobs[blob_oid] = path.read_bytes()
        blob_by_rel[rel] = blob_oid
    source_path = repo / cli._ATTEST_RUNTIME_PATHS[0]
    head = "a" * 40
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "__file__", str(source_path))

    def fake_run(argv, **kwargs):
        if "cat-file" in argv:
            return subprocess.CompletedProcess(argv, 0, blobs[argv[-1]], b"")
        if "rev-parse" in argv:
            revision = argv[-1]
            stdout = f"{blob_by_rel[revision.split(':', 1)[1]]}\n" if ":" in revision else f"{head}\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    payload = cli._preimport_attest_bootstrap(
        [
            "attest",
            "--stage",
            "candidate",
            "--expected-head",
            head,
            "--builder-run-id",
            "builder-no-repo",
        ]
    )

    assert payload is not None
    assert payload["bootstrap_head"] == head
    assert payload["repo_realpath"] == str(repo.resolve())
    assert set(payload["loaded_runtime_blobs"]) == set(cli._ATTEST_RUNTIME_PATHS)


def test_canonical_main_attest_rejects_nonexistent_candidate(tmp_path):
    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    with pytest.raises(legible_evidence.LegibleProcessBootstrapError):
        legible_evidence.attest(
            repo=repo,
            stage="canonical-main",
            expected_head=head,
            builder_run_id="candidate-run",
            candidate_head="0" * 40,
        )


def test_builder_attest_persists_captured_process_identity(tmp_path):
    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    result = legible_evidence.attest(
        repo=repo,
        stage="builder",
        expected_head=head,
        builder_run_id="builder-captured",
        process_start_token="a" * 64,
    )

    artifact = repo / result["builder_process_artifact"]
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert result["status"] == "builder_recorded"
    assert payload["schema"] == "legible_builder_process.v1"
    assert payload["run_id"] == "builder-captured"
    assert payload["head"] == head
    assert payload["process_start_token"] == "a" * 64
    assert payload["process_id"] == os.getpid()


def test_builder_process_loader_requires_captured_exact_head_record(tmp_path):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    run_dir = repo / ".phase-loop" / "runs" / "builder-captured"
    run_dir.mkdir(parents=True)
    record = {
        "schema": "legible_builder_process.v1",
        "run_id": "builder-captured",
        "stage": "builder",
        "head": head,
        "bootstrap_head": head,
        "repo_realpath": str(repo.resolve()),
        "cli_path": str(repo / "phase-loop-runtime/src/phase_loop_runtime/cli.py"),
        "cli_sha256": "1" * 64,
        "python_executable": sys.executable,
        "process_id": 123,
        "process_start_token": "a" * 64,
        "loaded_runtime_blobs": {},
    }
    path = run_dir / "legible-builder-process.json"
    path.write_text(json.dumps(record), encoding="utf-8")

    loaded = runner._load_legible_builder_process(
        repo, run_dir, "builder-captured", head
    )
    assert loaded["process_start_token"] == "a" * 64

    record["head"] = "0" * 40
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(
        legible_evidence.LegibleProcessBootstrapError,
        match="builder process identity",
    ):
        runner._load_legible_builder_process(repo, run_dir, "builder-captured", head)


def test_operational_evidence_round_trip_is_sealed_and_closed(tmp_path):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    run_dir = repo / ".phase-loop" / "runs" / "attest-1"

    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=run_dir,
        stage="candidate",
        expected_head=head,
        sections=sections,
    )

    validation = legible_evidence.validate_operational_evidence(
        repo=repo,
        path=path,
        stage="candidate",
        expected_head=head,
    )
    assert validation.ok
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "legible_evidence.v1"
    assert set(payload["sections"]) == set(sections)
    assert len(payload["seal_sha256"]) == 64


def test_operational_evidence_rejects_section_drift(tmp_path):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    run_dir = repo / ".phase-loop" / "runs" / "attest-1"
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=run_dir,
        stage="candidate",
        expected_head=head,
        sections=sections,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sections"]["chronology"]["head"] = "0" * 40
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = legible_evidence.validate_operational_evidence(
        repo=repo,
        path=path,
        stage="candidate",
        expected_head=head,
    )

    assert not validation.ok
    assert validation.code == "operational_evidence_seal_mismatch"


def test_operational_evidence_rejects_placeholder_sections(tmp_path):
    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    sections = {name: {"head": head} for name in legible_evidence._OPERATIONAL_EVIDENCE_SECTIONS}
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / "attest-placeholder",
        stage="candidate",
        expected_head=head,
        sections=sections,
    )

    validation = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="candidate", expected_head=head
    )

    assert not validation.ok
    assert validation.code == "operational_evidence_sections"


@pytest.mark.parametrize(
    "mutation",
    (
        "registry_digest",
        "chronology_ancestry",
        "pr_parent_identity",
        "probe_semantics",
        "artifact_inventory",
        "nodeid_digest",
        "junit_contents",
        "panel_semantics",
        "probe_payload_digest",
        "pr_changed_paths",
        "pr_merged_at",
    ),
)
def test_operational_evidence_rejects_fabricated_semantics(tmp_path, mutation):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    if mutation == "registry_digest":
        sections["roadmap_status"]["registry_sha256"] = "0" * 64
    elif mutation == "chronology_ancestry":
        sections["chronology"]["tests_landing"] = sections["chronology"]["pr_head"]
    elif mutation == "pr_parent_identity":
        sections["pull_request"]["parents"] = [
            sections["pull_request"]["base"],
            sections["pull_request"]["base"],
        ]
    elif mutation == "probe_semantics":
        sections["assumption_probes"]["records"] = [{"probe_id": "fixture"}]
    elif mutation == "artifact_inventory":
        readme = (repo / "README.md").read_bytes()
        sections["artifacts"]["records"] = [
            {
                "path": "README.md",
                "byte_length": len(readme),
                "sha256": hashlib.sha256(readme).hexdigest(),
            }
        ]
    elif mutation == "nodeid_digest":
        sections["test_execution"]["nodeid_digest"] = "0" * 64
    elif mutation == "junit_contents":
        path = repo / sections["test_execution"]["final"]["junit_path"]
        path.write_text('<testsuite tests="84" failures="0" errors="0" skipped="0"/>\n')
        record = next(item for item in sections["artifacts"]["records"] if item["path"] == path.relative_to(repo).as_posix())
        record["byte_length"] = len(path.read_bytes())
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif mutation == "panel_semantics":
        path = repo / "evidence" / "implementation-panel.json"
        path.write_text('{"head":"' + head + '","verdicts":{"gpt-5.6-sol":"DISAGREE"}}\n')
        record = next(item for item in sections["artifacts"]["records"] if item["path"] == path.relative_to(repo).as_posix())
        record["byte_length"] = len(path.read_bytes())
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif mutation == "probe_payload_digest":
        sections["assumption_probes"]["records"][0]["response_sha256"] = "0" * 64
    elif mutation == "pr_changed_paths":
        sections["pull_request"]["changed_paths"] = ["README.md"]
    else:
        sections["pull_request"]["merged_at"] = ""
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / f"attest-{mutation}",
        stage="candidate",
        expected_head=head,
        sections=sections,
    )

    validation = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="candidate", expected_head=head
    )

    assert not validation.ok
    assert validation.code == "operational_evidence_sections"


def test_operational_evidence_rejects_unbound_process_cli(tmp_path):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    sections["process_attestations"]["candidate"]["cli_sha256"] = "0" * 64
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / "attest-cli-drift",
        stage="candidate",
        expected_head=head,
        sections=sections,
    )

    validation = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="candidate", expected_head=head
    )

    assert not validation.ok
    assert validation.code == "operational_evidence_sections"


def test_finalize_operational_attestation_binds_aggregate_to_verification(tmp_path):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    run_dir = repo / ".phase-loop" / "runs" / "attest-final"
    run_verification(repo, run_dir, [], None, None, 10, phase_alias="LEGIBLE")
    for path in (run_dir / ARTIFACT_NAME, run_dir / LOG_NAME):
        data = path.read_bytes()
        sections["artifacts"]["records"].append(
            {
                "path": path.relative_to(repo).as_posix(),
                "byte_length": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    evidence_path = legible_evidence.finalize_operational_attestation(
        repo=repo,
        run_dir=run_dir,
        artifact_path=run_dir / ARTIFACT_NAME,
        stage="candidate",
        expected_head=head,
        bootstrap_head=head,
        process_start_token="candidate-token",
        sections=sections,
    )

    assert evidence_path.name == "legible-operational-evidence.json"
    result = validate_verification_artifact_for_plan(
        run_dir / ARTIFACT_NAME, (legible_evidence.EXTENSION_NAMESPACE,)
    )
    assert result.ok
    payload = json.loads((run_dir / ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert payload["extensions"][legible_evidence.EXTENSION_NAMESPACE]["path"].endswith(
        "/legible-operational-evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    recorded_paths = {record["path"] for record in evidence["sections"]["artifacts"]["records"]}
    assert (run_dir / ARTIFACT_NAME).relative_to(repo).as_posix() not in recorded_paths
    assert (run_dir / LOG_NAME).relative_to(repo).as_posix() not in recorded_paths
    assert legible_evidence.validate_operational_evidence(
        repo=repo,
        path=evidence_path,
        stage="candidate",
        expected_head=head,
    ).ok


def test_append_verification_command_reseals_and_records_result(tmp_path):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "append-command"
    run_verification(repo, run_dir, [], None, None, 10, phase_alias="LEGIBLE")
    argv = [sys.executable, "-c", "print('post-aggregate-wrapper')"]

    command = verification_evidence._append_verification_command(
        repo,
        run_dir / ARTIFACT_NAME,
        argv,
        10,
    )

    assert command.exit_code == 0
    assert list(command.argv) == argv
    assert validate_verification_artifact(run_dir / ARTIFACT_NAME).ok
    payload = json.loads((run_dir / ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert payload["commands"][-1]["argv"] == argv


def test_canonical_operational_evidence_requires_implementation_pr_merge(tmp_path):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo, stage="canonical-main")
    baseline = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / "canonical-implementation-baseline",
        stage="canonical-main",
        expected_head=head,
        sections=sections,
    )
    assert legible_evidence.validate_operational_evidence(
        repo=repo, path=baseline, stage="canonical-main", expected_head=head
    ).ok

    sections["chronology"].pop("implementation_pull_request")
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / "canonical-implementation-missing",
        stage="canonical-main",
        expected_head=head,
        sections=sections,
    )

    validation = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="canonical-main", expected_head=head
    )
    assert not validation.ok
    assert validation.code == "operational_evidence_sections"


@pytest.mark.parametrize("mutation", ("state", "base_ref", "head", "parents", "merge_commit"))
def test_canonical_operational_evidence_rejects_invalid_implementation_pr_merge(
    tmp_path, mutation
):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo, stage="canonical-main")
    implementation_pr = sections["chronology"]["implementation_pull_request"]
    if mutation == "state":
        implementation_pr["state"] = "OPEN"
    elif mutation == "base_ref":
        implementation_pr["base_ref"] = "release"
    elif mutation == "head":
        implementation_pr["head"] = sections["chronology"]["phase_candidate"]
    elif mutation == "parents":
        implementation_pr["parents"].reverse()
    else:
        implementation_pr["merge_commit"] = sections["chronology"]["server_merge"]
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / f"canonical-implementation-{mutation}",
        stage="canonical-main",
        expected_head=head,
        sections=sections,
    )

    validation = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="canonical-main", expected_head=head
    )
    assert not validation.ok
    assert validation.code == "operational_evidence_sections"


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_code"),
    [
        ("stage", "not-a-real-stage", "sidecar_stage_mismatch"),
        ("expected_head", "0" * 40, "sidecar_head_mismatch"),
        ("bootstrap_head", "f" * 40, "sidecar_bootstrap_mismatch"),
        ("process_start_token", "", "sidecar_process_token_missing"),
    ],
)
def test_plan_aware_validation_rejects_invalid_sidecar_identity_binding(
    tmp_path, field, invalid_value, expected_code
):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "probe"
    run_verification(repo, run_dir, [], None, None, 10, phase_alias="LEGIBLE")
    sidecar_path = run_dir / "legible-verification-sidecar.json"
    sidecar_path.write_text("{}", encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    values = {
        "stage": "candidate",
        "expected_head": head,
        "bootstrap_head": head,
        "process_start_token": "fresh-process-token",
    }
    values[field] = invalid_value
    record = legible_evidence.bind_verification_sidecar(repo, run_dir=run_dir, **values)
    artifact_path = run_dir / ARTIFACT_NAME
    _bind_sidecar_extension(
        artifact_path,
        namespace=legible_evidence.EXTENSION_NAMESPACE,
        record=record.__dict__,
    )

    result = validate_verification_artifact_for_plan(
        artifact_path, (legible_evidence.EXTENSION_NAMESPACE,)
    )

    assert not result.ok
    assert result.code == expected_code


def test_attest_delegates_to_runner_owned_operational_workflow(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    observed = {}

    def fake_attest(**kwargs):
        observed.update(kwargs)
        return {
            "status": "sealed",
            "head": kwargs["expected_head"],
            "evidence_path": ".phase-loop/runs/attest/legible-operational-evidence.json",
        }

    monkeypatch.setattr(runner, "run_legible_operational_attestation", fake_attest, raising=False)

    result = legible_evidence.attest(
        repo=repo,
        stage="candidate",
        expected_head=head,
        builder_run_id="builder-1",
    )

    assert result["status"] == "sealed"
    assert result["evidence_path"].endswith("legible-operational-evidence.json")
    assert observed["repo"] == repo.resolve()
    assert observed["stage"] == "candidate"
    assert observed["expected_head"] == head


@pytest.mark.parametrize(
    "mutation",
    (
        "owned_partition",
        "original_tests_landing",
        "frozen_test_blob",
        "remote_oid",
        "loaded_runtime_blob",
        "loaded_runtime_record",
        "remote_candidate_oid",
        "refresh_parents",
        "body_ancestors",
        "comment_tokens",
        "external_blob",
        "recomputed_tree",
        "probe_set",
        "raw_log_digest",
        "raw_red_semantics",
        "test_command",
        "test_exit_code",
        "marker_state",
        "failure_markers",
        "panel_legs",
    ),
)
def test_operational_evidence_rejects_unproven_frozen_semantics(tmp_path, mutation):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    baseline_path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / f"baseline-{mutation}",
        stage="candidate",
        expected_head=head,
        sections=sections,
    )
    assert legible_evidence.validate_operational_evidence(
        repo=repo, path=baseline_path, stage="candidate", expected_head=head
    ).ok

    if mutation == "owned_partition":
        sections["chronology"]["owned_paths"].pop()
    elif mutation == "original_tests_landing":
        sections["chronology"]["original_tests_landing"] = sections["chronology"]["pr_head"]
    elif mutation == "frozen_test_blob":
        first = next(iter(sections["chronology"]["frozen_test_blobs"].values()))
        first["candidate_head"] = "0" * 40
    elif mutation == "remote_oid":
        sections["pull_request"]["remote_head_oid"] = "0" * 40
    elif mutation == "loaded_runtime_blob":
        first_key = next(iter(sections["process_attestations"]["candidate"]["loaded_runtime_blobs"]))
        sections["process_attestations"]["candidate"]["loaded_runtime_blobs"][first_key]["blob_oid"] = "0" * 40
    elif mutation == "loaded_runtime_record":
        first = next(iter(sections["process_attestations"]["candidate"]["loaded_runtime_blobs"].values()))
        first["sha256"] = "0" * 64
    elif mutation == "remote_candidate_oid":
        sections["chronology"]["candidate_remote_oid"] = "0" * 40
    elif mutation == "refresh_parents":
        sections["pull_request"]["refresh_parents"].reverse()
    elif mutation == "body_ancestors":
        sections["pull_request"]["body_ancestor_commits"].pop()
    elif mutation == "comment_tokens":
        sections["pull_request"]["comment_tokens_equal"] = False
    elif mutation == "external_blob":
        sections["pull_request"]["external_blobs"]["head"] = "0" * 40
    elif mutation == "recomputed_tree":
        sections["pull_request"]["recomputed_trees"]["server"] = "0" * 40
    elif mutation == "probe_set":
        sections["assumption_probes"]["records"].pop(0)
    elif mutation == "raw_log_digest":
        sections["test_execution"]["forced_red"]["log_sha256"] = "0" * 64
    elif mutation == "raw_red_semantics":
        path = repo / sections["test_execution"]["forced_red"]["log_path"]
        path.write_text(path.read_text(encoding="utf-8").replace("LEGIBLE_RED::", "LEGIBLE_MASKED::", 1))
        data = path.read_bytes()
        sections["test_execution"]["forced_red"]["log_byte_length"] = len(data)
        sections["test_execution"]["forced_red"]["log_sha256"] = hashlib.sha256(data).hexdigest()
        record = next(
            item
            for item in sections["artifacts"]["records"]
            if item["path"] == path.relative_to(repo).as_posix()
        )
        record["byte_length"] = len(data)
        record["sha256"] = hashlib.sha256(data).hexdigest()
    elif mutation == "test_command":
        sections["test_execution"]["forced_red"]["argv"][-1] = "--collect-only"
    elif mutation == "test_exit_code":
        sections["test_execution"]["forced_red"]["exit_code"] = 0
    elif mutation == "marker_state":
        sections["test_execution"]["forced_red"]["capability_marker_present"] = True
    elif mutation == "failure_markers":
        sections["test_execution"]["forced_red"]["failure_markers"].popitem()
    else:
        panel_path = repo / "evidence" / "implementation-panel.json"
        panel = json.loads(panel_path.read_text(encoding="utf-8"))
        panel.pop("legs")
        panel_path.write_text(json.dumps(panel, sort_keys=True) + "\n", encoding="utf-8")
        panel_record = next(
            record
            for record in sections["artifacts"]["records"]
            if record["path"] == panel_path.relative_to(repo).as_posix()
        )
        panel_record["byte_length"] = len(panel_path.read_bytes())
        panel_record["sha256"] = hashlib.sha256(panel_path.read_bytes()).hexdigest()

    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / f"mutated-{mutation}",
        stage="candidate",
        expected_head=head,
        sections=sections,
    )
    result = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="candidate", expected_head=head
    )

    assert not result.ok, mutation
    assert result.code == "operational_evidence_sections"


def _write_legible_manifest_contract(repo: Path, *, include_contract: bool = True) -> tuple[str, dict]:
    rel = _commit_plan(repo, "phase-plan-v10-LEGIBLE.md")
    source_repo = Path(__file__).resolve().parents[2]
    roadmap_path = repo / roadmap_assumptions.CANONICAL_ROADMAP_REL
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    roadmap_path.write_bytes(
        (source_repo / roadmap_assumptions.CANONICAL_ROADMAP_REL).read_bytes()
    )
    subprocess.run(
        ["git", "add", roadmap_assumptions.CANONICAL_ROADMAP_REL],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "bind LEGIBLE roadmap snapshot"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    plan_digest = hashlib.sha256((repo / rel).read_bytes()).hexdigest()
    roadmap_digest = hashlib.sha256(roadmap_path.read_bytes()).hexdigest()
    owned_digest = hashlib.sha256("".join(f"{path}\n" for path in LEGIBLE_OWNED_PATHS).encode()).hexdigest()
    contract = {
        **LEGIBLE_CONTRACT_FIXED_FIELDS,
        "plan_sha256": plan_digest,
        "roadmap_sha256": LEGIBLE_ROADMAP_SHA256,
        "owned_paths": list(LEGIBLE_OWNED_PATHS),
        "owned_paths_count": len(LEGIBLE_OWNED_PATHS),
        "owned_paths_sha256": owned_digest,
        "test_paths": list(legible_evidence.FROZEN_TEST_PATHS),
    }
    lifecycle = _source_binding_events(source_repo, rel)
    frozen_authority_history = _source_authority_history(source_repo, rel)
    if include_contract:
        lifecycle.append({"metadata": {"legible_plan_contract": contract}})
    else:
        lifecycle[0]["metadata"].pop("legible_plan_contract")
    lifecycle.append({"metadata": {"note": "ordinary later event"}})
    (repo / "plans" / "manifest.json").write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "file": rel,
                        "phase_alias": "LEGIBLE",
                        "roadmap_ref": {
                            "file": roadmap_assumptions.CANONICAL_ROADMAP_REL
                        },
                        "plan_authority_history": [
                            *frozen_authority_history,
                            {
                                "schema": "plan_current_authority.v1",
                                "source": "agent-harness#620",
                                "plan_sha256": plan_digest,
                                "roadmap_sha256": roadmap_digest,
                            }
                        ],
                        "lifecycle": lifecycle,
                    }
                ]
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return rel, contract


def test_legible_current_authority_cannot_drop_roadmap_binding(tmp_path):
    repo = make_repo(tmp_path)
    rel, _contract = _write_legible_manifest_contract(repo)
    assert check(repo).exit_code == 0
    manifest_path = repo / "plans" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["plans"][0]["roadmap_ref"]
    manifest["plans"][0]["plan_authority_history"][-1]["roadmap_sha256"] = None
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]


@pytest.mark.parametrize(
    "lifecycle", ({}, None, [None], [{}], [{"metadata": None}])
)
def test_manifest_check_rejects_malformed_lifecycle_that_erases_authority(
    tmp_path, lifecycle
):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    (repo / "plans" / "manifest.json").write_text(
        json.dumps({"plans": [{"file": rel, "lifecycle": lifecycle}]}),
        encoding="utf-8",
    )

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_historical_digest_rebind_cannot_drop_current_roadmap_binding(tmp_path):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    roadmap = repo / "specs" / "current-roadmap.md"
    roadmap.parent.mkdir(exist_ok=True)
    roadmap.write_text("# Current roadmap\n", encoding="utf-8")
    subprocess.run(["git", "add", "specs/current-roadmap.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "bind roadmap snapshot"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    plan_digest = hashlib.sha256((repo / rel).read_bytes()).hexdigest()
    roadmap_digest = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    manifest_path = repo / "plans" / "manifest.json"
    manifest = {
        "plans": [
            {
                "file": rel,
                "roadmap_ref": {"file": "specs/current-roadmap.md"},
                "plan_authority_history": [
                    {
                        "schema": "plan_current_authority.v1",
                        "source": "agent-harness#620",
                        "plan_sha256": plan_digest,
                        "roadmap_sha256": roadmap_digest,
                    }
                ],
                "lifecycle": [
                    {
                        "metadata": {
                            "digest_rebind": {
                                "plan_sha256": plan_digest,
                                "roadmap_sha256": roadmap_digest,
                            }
                        }
                    }
                ],
            }
        ]
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert check(repo).exit_code == 0
    del manifest["plans"][0]["roadmap_ref"]
    manifest["plans"][0]["plan_authority_history"][-1]["roadmap_sha256"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]


def _write_generic_authority_manifest(repo: Path, rel: str) -> None:
    roadmap = repo / "specs" / "current-roadmap.md"
    roadmap.write_text("# Current roadmap\n", encoding="utf-8")
    plan_digest = hashlib.sha256((repo / rel).read_bytes()).hexdigest()
    roadmap_digest = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    (repo / "plans" / "manifest.json").write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "file": rel,
                        "roadmap_ref": {"file": "specs/current-roadmap.md"},
                        "plan_authority_history": [
                            {
                                "schema": "plan_current_authority.v1",
                                "source": "agent-harness#647",
                                "plan_sha256": plan_digest,
                                "roadmap_sha256": roadmap_digest,
                            }
                        ],
                        "lifecycle": [
                            {
                                "metadata": {
                                    "digest_rebind": {
                                        "plan_sha256": plan_digest,
                                        "roadmap_sha256": roadmap_digest,
                                    }
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_generic_ancestor_authority_survives_plan_and_manifest_deletion(tmp_path):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    _write_generic_authority_manifest(repo, rel)
    subprocess.run(
        ["git", "add", "plans/manifest.json", "specs/current-roadmap.md"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record generic authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert check(repo).exit_code == 0
    (repo / rel).unlink()
    (repo / "plans" / "manifest.json").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "delete generic authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_merge_checks_authority_from_every_parent(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "plans" / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "plans/.gitkeep"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "retain plans directory"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "switch", "-c", "authority-parent"], cwd=repo, check=True)
    rel = _commit_plan(repo)
    _write_generic_authority_manifest(repo, rel)
    subprocess.run(
        ["git", "add", "plans/manifest.json", "specs/current-roadmap.md"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record second-parent authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    authority_parent = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    base_tree = subprocess.run(
        ["git", "rev-parse", f"{base}^{{tree}}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    merge = subprocess.run(
        [
            "git",
            "commit-tree",
            base_tree,
            "-p",
            base,
            "-p",
            authority_parent,
            "-m",
            "merge without second-parent authority",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "switch", "--detach", merge], cwd=repo, check=True)

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]
    (repo / "README.md").write_text("successor\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "unrelated successor"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    successor_result = check(repo)

    assert successor_result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in successor_result.malformed
    ]


def test_shallow_history_fails_closed(tmp_path):
    source = make_repo(tmp_path / "source")
    rel = _commit_plan(source)
    _write_generic_authority_manifest(source, rel)
    subprocess.run(
        ["git", "add", "plans/manifest.json", "specs/current-roadmap.md"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record authority before shallow clone"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth", "1", f"file://{source}", str(shallow)],
        check=True,
        capture_output=True,
    )

    result = check(shallow)

    assert result.exit_code == 1
    assert ("plans/manifest.json", "history-incomplete") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_history_ignores_replace_refs_and_git_location_overrides(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path / "source")
    rel = _commit_plan(repo)
    _write_generic_authority_manifest(repo, rel)
    subprocess.run(
        ["git", "add", "plans/manifest.json", "specs/current-roadmap.md"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / rel).unlink()
    (repo / "plans" / "manifest.json").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "erase authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    replacement = subprocess.run(
        ["git", "commit-tree", head_tree, "-m", "forged root"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "replace", "HEAD", replacement], cwd=repo, check=True
    )
    plain_parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert len(plain_parents) == 1
    attacker = make_repo(tmp_path / "attacker")
    monkeypatch.setenv("GIT_DIR", str(attacker / ".git"))
    monkeypatch.setenv("GIT_GRAFT_FILE", str(attacker / "forged-grafts"))

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_GRAFT_FILE")
    subprocess.run(["git", "replace", "-d", "HEAD"], cwd=repo, check=True)
    graft_path = Path(
        subprocess.run(
            ["git", "rev-parse", "--git-path", "info/grafts"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    if not graft_path.is_absolute():
        graft_path = repo / graft_path
    graft_path.parent.mkdir(parents=True, exist_ok=True)
    graft_path.write_text(
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        + "\n",
        encoding="utf-8",
    )

    grafted = check(repo)

    assert grafted.exit_code == 1
    assert ("plans/manifest.json", "history-incomplete") in [
        (item.path, item.kind) for item in grafted.malformed
    ]


def test_trusted_git_disables_commit_graph(monkeypatch, tmp_path):
    captured: list[str] = []

    def recording_run(argv, **_kwargs):
        captured.extend(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(plan_manifest.subprocess, "run", recording_run)

    result = plan_manifest._git_history_capture(tmp_path, "rev-parse", "HEAD")

    assert result.returncode == 0
    assert captured[:5] == [
        "git",
        "--no-replace-objects",
        "-c",
        "core.commitGraph=false",
        "-C",
    ]


def test_late_graft_insertion_cannot_change_history(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    _write_generic_authority_manifest(repo, rel)
    subprocess.run(
        ["git", "add", "plans/manifest.json", "specs/current-roadmap.md"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / rel).unlink()
    (repo / "plans" / "manifest.json").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "erase authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    graft_path = Path(
        subprocess.run(
            ["git", "rev-parse", "--git-path", "info/grafts"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    if not graft_path.is_absolute():
        graft_path = repo / graft_path
    real_boundary = plan_manifest._history_boundary_complete
    inserted = False

    def insert_after_probe(repo_path):
        nonlocal inserted
        result = real_boundary(repo_path)
        if result and not inserted:
            graft_path.parent.mkdir(parents=True, exist_ok=True)
            graft_path.write_text(head + "\n", encoding="utf-8")
            inserted = True
        return result

    monkeypatch.setattr(
        plan_manifest, "_history_boundary_complete", insert_after_probe
    )

    result = check(repo)

    assert inserted
    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_late_shallow_insertion_cannot_change_history(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    _write_generic_authority_manifest(repo, rel)
    subprocess.run(
        ["git", "add", "plans/manifest.json", "specs/current-roadmap.md"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / rel).unlink()
    (repo / "plans" / "manifest.json").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "erase authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common_dir = Path(
        subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    shallow_path = common_dir / "shallow"
    real_boundary = plan_manifest._history_boundary_complete
    inserted = False

    def insert_after_probe(repo_path):
        nonlocal inserted
        result = real_boundary(repo_path)
        if result and not inserted:
            shallow_path.write_text(head + "\n", encoding="utf-8")
            inserted = True
        return result

    monkeypatch.setattr(
        plan_manifest, "_history_boundary_complete", insert_after_probe
    )

    result = check(repo)

    assert inserted
    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_head_move_and_restore_cannot_change_pinned_history(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    _write_generic_authority_manifest(repo, rel)
    subprocess.run(
        ["git", "add", "plans/manifest.json", "specs/current-roadmap.md"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / rel).unlink()
    (repo / "plans" / "manifest.json").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "erase authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    head_tree = subprocess.run(
        ["git", "rev-parse", f"{head}^{{tree}}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    forged_root = subprocess.run(
        ["git", "commit-tree", head_tree, "-m", "ancestry-free root"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    real_capture = plan_manifest._git_history_capture
    moved = False
    restored = False

    def move_and_restore(repo_path, *args, **kwargs):
        nonlocal moved, restored
        if args == ("rev-list", "--parents", "-n", "1", head) and not moved:
            subprocess.run(
                ["git", "update-ref", "HEAD", forged_root],
                cwd=repo,
                check=True,
            )
            moved = True
        result = real_capture(repo_path, *args, **kwargs)
        if moved and not restored and args and args[0] == "log":
            subprocess.run(
                ["git", "update-ref", "HEAD", head], cwd=repo, check=True
            )
            restored = True
        return result

    monkeypatch.setattr(plan_manifest, "_git_history_capture", move_and_restore)

    result = check(repo)

    assert moved and restored
    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_manifest_snapshot_rejects_swap_between_history_and_parse(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    _write_generic_authority_manifest(repo, rel)
    manifest_path = repo / "plans" / "manifest.json"
    subprocess.run(
        ["git", "add", "plans/manifest.json", "specs/current-roadmap.md"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    erased = json.loads(manifest_path.read_text(encoding="utf-8"))
    erased["plans"][0].pop("plan_authority_history")
    erased["plans"][0]["lifecycle"] = []
    replacement = repo / "plans" / "replacement.json"
    replacement.write_text(json.dumps(erased), encoding="utf-8")
    real_capture = plan_manifest._git_history_capture
    swapped = False

    def swapping_capture(repo_path, *args, **kwargs):
        nonlocal swapped
        if not swapped and args and args[0] == "log" and "--format=" in args:
            replacement.replace(manifest_path)
            swapped = True
        return real_capture(repo_path, *args, **kwargs)

    monkeypatch.setattr(plan_manifest, "_git_history_capture", swapping_capture)

    with pytest.raises(
        plan_manifest.ManifestSourceError, match="manifest changed during validation"
    ):
        check(repo)
    assert swapped


def test_manifest_snapshot_rejects_swap_after_final_plans_stat(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    manifest_path = repo / "plans" / "manifest.json"
    manifest_path.write_text(
        json.dumps({"plans": [{"file": rel, "lifecycle": []}]}),
        encoding="utf-8",
    )
    assert check(repo).exit_code == 0
    moved = tmp_path / "moved-plans"
    external = tmp_path / "external-plans"
    external.mkdir()
    (external / "manifest.json").write_text('{"plans": []}', encoding="utf-8")
    real_stat = os.stat
    plans_stats = 0

    def swapping_stat(path, *args, **kwargs):
        nonlocal plans_stats
        result = real_stat(path, *args, **kwargs)
        if path == "plans" and kwargs.get("dir_fd") is not None:
            plans_stats += 1
            if plans_stats == 3:
                (repo / "plans").rename(moved)
                (repo / "plans").symlink_to(external, target_is_directory=True)
        return result

    monkeypatch.setattr(plan_manifest.os, "stat", swapping_stat)

    with pytest.raises(
        plan_manifest.ManifestSourceError,
        match=(
            "manifest (ancestry )?changed during validation|"
            "physical plans ancestry changed during scan|"
            "physical plans source changed before scan|"
            "cannot scan physical plans source"
        ),
    ):
        check(repo)
    assert plans_stats >= 3


def test_manifest_snapshot_uses_darwin_clone_without_safe_anchor(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    manifest_path = repo / "plans" / "manifest.json"
    manifest_path.write_text(
        json.dumps({"plans": [{"file": rel, "lifecycle": []}]}),
        encoding="utf-8",
    )
    monkeypatch.delattr(plan_manifest.os, "O_PATH", raising=False)
    monkeypatch.setattr(plan_manifest.sys, "platform", "darwin")
    monkeypatch.setattr(
        plan_manifest,
        "_darwin_clonefileat_bytes",
        lambda *_args, **_kwargs: manifest_path.read_bytes(),
    )

    assert check(repo).exit_code == 0
    manifest_path.write_text('{"plans": []}', encoding="utf-8")
    assert check(repo).exit_code == 1


def test_darwin_clone_authority_rejects_working_plan_drift(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    plan_path = repo / rel
    plan_digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    (repo / "plans" / "manifest.json").write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "file": rel,
                        "plan_authority_history": [
                            {
                                "schema": "plan_current_authority.v1",
                                "source": "agent-harness#647",
                                "plan_sha256": plan_digest,
                                "roadmap_sha256": None,
                            }
                        ],
                        "lifecycle": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def clone_bytes(_repo, parent_fd, name):
        return Path(f"/proc/self/fd/{parent_fd}/{name}").read_bytes()

    monkeypatch.delattr(plan_manifest.os, "O_PATH", raising=False)
    monkeypatch.setattr(plan_manifest.sys, "platform", "darwin")
    monkeypatch.setattr(plan_manifest, "_darwin_clonefileat_bytes", clone_bytes)
    assert check(repo).exit_code == 0
    plan_path.write_text("---\nphase: RUNNER\n---\n# Drifted\n", encoding="utf-8")

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-digest") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_manifest_snapshot_rejects_write_after_former_final_fstat(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    manifest_path = repo / "plans" / "manifest.json"
    manifest_path.write_text(
        json.dumps({"plans": [{"file": rel, "lifecycle": []}]}),
        encoding="utf-8",
    )
    assert check(repo).exit_code == 0
    manifest_inode = manifest_path.stat().st_ino
    real_fstat = os.fstat
    manifest_fstats = 0

    def writing_fstat(descriptor):
        nonlocal manifest_fstats
        result = real_fstat(descriptor)
        if result.st_ino == manifest_inode:
            manifest_fstats += 1
            if manifest_fstats == 5:
                manifest_path.write_text('{"plans": []}', encoding="utf-8")
        return result

    monkeypatch.setattr(plan_manifest.os, "fstat", writing_fstat)

    with pytest.raises(plan_manifest.ManifestSourceError, match="manifest changed"):
        check(repo)
    assert manifest_fstats >= 5


def test_generic_ancestor_authority_cannot_be_removed_from_retained_row(tmp_path):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    plan_digest = hashlib.sha256((repo / rel).read_bytes()).hexdigest()
    manifest_path = repo / "plans" / "manifest.json"
    manifest = {
        "plans": [
            {
                "file": rel,
                "plan_authority_history": [
                    {
                        "schema": "plan_current_authority.v1",
                        "source": "agent-harness#647",
                        "plan_sha256": plan_digest,
                        "roadmap_sha256": None,
                    }
                ],
                "lifecycle": [],
            }
        ]
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "record unbound authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert check(repo).exit_code == 0
    authority_history = manifest["plans"][0]["plan_authority_history"]
    manifest["plans"][0]["plan_authority_history"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    null_authority = check(repo)
    assert null_authority.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in null_authority.malformed
    ]
    manifest["plans"][0]["plan_authority_history"] = authority_history
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert check(repo).exit_code == 0
    (repo / "README.md").write_text("successor\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "code-only successor"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert check(repo).exit_code == 0
    manifest["plans"][0].pop("plan_authority_history")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_unavailable_historical_manifest_blob_fails_closed(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    plan_digest = hashlib.sha256((repo / rel).read_bytes()).hexdigest()
    manifest_path = repo / "plans" / "manifest.json"
    first_authority = {
        "schema": "plan_current_authority.v1",
        "source": "agent-harness#647",
        "plan_sha256": plan_digest,
        "roadmap_sha256": None,
    }
    manifest = {
        "plans": [
            {
                "file": rel,
                "plan_authority_history": [first_authority],
                "lifecycle": [],
            }
        ]
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "record first authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    ancestor = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    ancestor_blob = subprocess.run(
        ["git", "rev-parse", f"{ancestor}:plans/manifest.json"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest["plans"][0]["plan_authority_history"].append(
        {**first_authority, "source": "agent-harness#648"}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "append current authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    real_capture = plan_manifest._git_history_capture

    def missing_blob(repo_path, *args, **kwargs):
        if args == ("cat-file", "blob", ancestor_blob):
            text_mode = kwargs.get("text", True)
            return subprocess.CompletedProcess(
                args,
                128,
                "" if text_mode else b"",
                "missing blob" if text_mode else b"missing blob",
            )
        return real_capture(repo_path, *args, **kwargs)

    monkeypatch.setattr(plan_manifest, "_git_history_capture", missing_blob)

    with pytest.raises(
        plan_manifest.ManifestSourceError,
        match=f"manifest blob is unavailable at {ancestor}",
    ):
        check(repo)


def test_composite_authority_revalidates_plan_after_roadmap_hash(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    plan_path = repo / rel
    roadmap = repo / "specs" / "current-roadmap.md"
    roadmap.write_text("# Current roadmap\n", encoding="utf-8")
    subprocess.run(["git", "add", "specs/current-roadmap.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "bind roadmap snapshot"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    plan_digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    roadmap_digest = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "file": rel,
                        "roadmap_ref": {"file": "specs/current-roadmap.md"},
                        "plan_authority_history": [
                            {
                                "schema": "plan_current_authority.v1",
                                "source": "agent-harness#620",
                                "plan_sha256": plan_digest,
                                "roadmap_sha256": roadmap_digest,
                            }
                        ],
                        "lifecycle": [
                            {
                                "metadata": {
                                    "digest_rebind": {
                                        "plan_sha256": plan_digest,
                                        "roadmap_sha256": roadmap_digest,
                                    }
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert check(repo).exit_code == 0
    real_open = os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "specs" and dir_fd is not None and not swapped:
            plan_path.write_text(
                "---\nphase: RUNNER\n---\n# Drifted plan\n", encoding="utf-8"
            )
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(plan_manifest.os, "open", swapping_open)

    result = check(repo)

    assert swapped
    assert result.exit_code == 1
    assert (rel, "plan-digest") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_composite_authority_requires_one_exact_git_tree(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    plan_path = repo / rel
    plan_a_digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    plan_path.write_text("---\nphase: RUNNER\n---\n# Plan C\n", encoding="utf-8")
    roadmap_rel = "specs/current-roadmap.md"
    roadmap = repo / roadmap_rel
    roadmap.write_text("# Roadmap B\n", encoding="utf-8")
    roadmap_b_digest = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    subprocess.run(["git", "add", rel, roadmap_rel], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "replace plan while adding roadmap"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manifest = {
        "plans": [
            {
                "file": rel,
                "roadmap_ref": {"file": roadmap_rel},
                "plan_authority_history": [
                    {
                        "schema": "plan_current_authority.v1",
                        "source": "agent-harness#647",
                        "plan_sha256": plan_a_digest,
                        "roadmap_sha256": roadmap_b_digest,
                    }
                ],
                "lifecycle": [
                    {
                        "metadata": {
                            "digest_rebind": {
                                "plan_sha256": plan_a_digest,
                                "roadmap_sha256": roadmap_b_digest,
                            }
                        }
                    }
                ],
            }
        ]
    }
    (repo / "plans" / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    monkeypatch.setattr(
        plan_manifest,
        "_regular_repo_files_sha256",
        lambda *_args, **_kwargs: {
            rel: plan_a_digest,
            roadmap_rel: roadmap_b_digest,
        },
    )

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-digest") in [
        (item.path, item.kind) for item in result.malformed
    ]


def test_frozen_historical_binding_cannot_be_deleted_with_authority(
    tmp_path, monkeypatch
):
    source_repo = Path(__file__).resolve().parents[2]
    source_manifest = _source_authority_manifest(source_repo)
    entry = next(
        item
        for item in source_manifest["plans"]
        if item["file"] == "plans/phase-plan-v10-FABPUB.md"
    )
    original_entry = json.loads(json.dumps(entry))
    repo = make_repo(tmp_path)
    plan_path = repo / entry["file"]
    plan_path.write_bytes((source_repo / entry["file"]).read_bytes())
    roadmap_rel = entry["roadmap_ref"]["file"]
    roadmap_path = repo / roadmap_rel
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    roadmap_path.write_bytes((source_repo / roadmap_rel).read_bytes())
    subprocess.run(
        ["git", "add", entry["file"], roadmap_rel], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "add FABPUB plan"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    manifest_path = repo / "plans" / "manifest.json"
    manifest_path.write_text(
        json.dumps({"plans": [entry]}, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert check(repo).exit_code == 0
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "record baseline authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    governed_append = json.loads(json.dumps(entry))
    governed_append["lifecycle"].append(
        next(
            json.loads(json.dumps(event))
            for event in entry["lifecycle"]
            if "digest_rebind" in event.get("metadata", {})
        )
    )
    governed_append["plan_authority_history"].append(
        json.loads(json.dumps(entry["plan_authority_history"][-1]))
    )
    manifest_path.write_text(
        json.dumps({"plans": [governed_append]}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "append governed authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert check(repo).exit_code == 0
    rewritten_append = json.loads(json.dumps(governed_append))
    rewritten_append["lifecycle"][-1]["metadata"]["digest_rebind"][
        "roadmap_sha256"
    ] = "0" * 64
    valid_current = json.loads(
        json.dumps(rewritten_append["plan_authority_history"][-1])
    )
    rewritten_append["plan_authority_history"][-1]["plan_sha256"] = "0" * 64
    rewritten_append["plan_authority_history"].append(valid_current)
    manifest_path.write_text(
        json.dumps({"plans": [rewritten_append]}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert check(repo).exit_code == 1
    deleted_append = json.loads(json.dumps(governed_append))
    deleted_append["lifecycle"].pop()
    deleted_append["plan_authority_history"].pop()
    manifest_path.write_text(
        json.dumps({"plans": [deleted_append]}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert check(repo).exit_code == 1
    original_authority = json.loads(json.dumps(entry["plan_authority_history"]))
    entry["plan_authority_history"][0]["plan_sha256"] = "0" * 64
    entry["plan_authority_history"].append(original_authority[0])
    manifest_path.write_text(
        json.dumps({"plans": [entry]}, sort_keys=True) + "\n", encoding="utf-8"
    )

    rewritten_authority = check(repo)

    assert rewritten_authority.exit_code == 1
    assert (entry["file"], "plan-contract") in [
        (item.path, item.kind) for item in rewritten_authority.malformed
    ]
    entry = json.loads(json.dumps(original_entry))
    entry["lifecycle"] = [
        event
        for event in entry["lifecycle"]
        if "digest_rebind" not in event.get("metadata", {})
    ]
    del entry["plan_authority_history"]
    manifest_path.write_text(
        json.dumps({"plans": [entry]}, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = check(repo)

    assert result.exit_code == 1
    assert (entry["file"], "plan-contract") in [
        (item.path, item.kind) for item in result.malformed
    ]
    plan_path.unlink()
    manifest_path.write_text('{"plans": []}\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "delete FABPUB plan and row"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    deleted_plan_and_row = check(repo)

    assert deleted_plan_and_row.exit_code == 1
    assert (entry["file"], "plan-contract") in [
        (item.path, item.kind) for item in deleted_plan_and_row.malformed
    ]
    for invalid_manifest in (None, "{", "[]"):
        if invalid_manifest is None:
            manifest_path.unlink()
        else:
            manifest_path.write_text(invalid_manifest, encoding="utf-8")
        erased_manifest = check(repo)
        assert erased_manifest.exit_code == 1
        assert (entry["file"], "plan-contract") in [
            (item.path, item.kind) for item in erased_manifest.malformed
        ]
    manifest_path.write_text('{"plans": []}\n', encoding="utf-8")
    real_open = plan_manifest.os.open
    denied = False

    def unreadable_manifest(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal denied
        if isinstance(path, str) and path.startswith("/proc/self/fd/") and not denied:
            denied = True
            raise PermissionError("denied")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(plan_manifest.os, "open", unreadable_manifest)
    unreadable = check(repo)
    assert denied
    assert unreadable.exit_code == 1
    assert (entry["file"], "plan-contract") in [
        (item.path, item.kind) for item in unreadable.malformed
    ]


def test_legible_manifest_contract_survives_later_ordinary_lifecycle_event(tmp_path):
    repo = make_repo(tmp_path)
    rel, _contract = _write_legible_manifest_contract(repo)
    (repo / rel).write_text((repo / rel).read_text(encoding="utf-8") + "drift\n", encoding="utf-8")

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-digest") in [(item.path, item.kind) for item in result.malformed]

    manifest_path = repo / "plans" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["plans"][0]["plan_authority_history"]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    missing_current_authority = check(repo)

    assert missing_current_authority.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in missing_current_authority.malformed
    ]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["plans"][0]["lifecycle"][0]["metadata"]["legible_plan_contract"] = "corrupt"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    corrupted_historical_binding = check(repo)

    assert corrupted_historical_binding.exit_code == 1
    assert (rel, "plan-contract") in [
        (item.path, item.kind) for item in corrupted_historical_binding.malformed
    ]


@pytest.mark.parametrize("defect", ("missing", "owned_paths", "owned_paths_count", "owned_paths_sha256", "test_paths"))
def test_legible_manifest_contract_is_mandatory_and_complete(tmp_path, defect):
    repo = make_repo(tmp_path)
    rel, contract = _write_legible_manifest_contract(repo, include_contract=defect != "missing")
    manifest_path = repo / "plans" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if defect != "missing":
        del manifest["plans"][0]["lifecycle"][0]["metadata"]["legible_plan_contract"][defect]
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [(item.path, item.kind) for item in result.malformed]


@pytest.mark.parametrize("mutation", ("roadmap_path", "missing_probe", "arbitrary_import", "extra_subject_key"))
def test_assumption_sidecar_is_exact_closed_v10_data_boundary(tmp_path, mutation):
    source_repo = Path(__file__).resolve().parents[2]
    source_sidecar = json.loads(
        (source_repo / roadmap_assumptions.PROBE_SIDECAR_REL).read_text(encoding="utf-8")
    )
    repo = tmp_path / "sidecar-repo"
    roadmap_bytes = (source_repo / "specs" / "phase-plans-v10.md").read_bytes()
    roadmap_path = repo / "specs" / "phase-plans-v10.md"
    roadmap_path.parent.mkdir(parents=True)
    roadmap_path.write_bytes(roadmap_bytes)
    if mutation == "roadmap_path":
        alternate = repo / "specs" / "alternate.md"
        alternate.write_bytes(roadmap_bytes)
        source_sidecar["roadmap"] = "specs/alternate.md"
    elif mutation == "missing_probe":
        source_sidecar["probes"].pop()
    else:
        probe = next(item for item in source_sidecar["probes"] if item["kind"] == "repo_constant")
        if mutation == "arbitrary_import":
            probe["subject"] = {
                "module": "test_legible_review_repairs",
                "attribute": "LEGIBLE_PROBE_IDS",
                "field": "count",
            }
        else:
            probe["subject"]["unexpected"] = "accepted-by-open-mapping"
    selected_roadmap = repo / source_sidecar["roadmap"]
    source_sidecar["roadmap_sha256"] = hashlib.sha256(selected_roadmap.read_bytes()).hexdigest()
    sidecar_path = repo / roadmap_assumptions.PROBE_SIDECAR_REL
    sidecar_path.write_text(json.dumps(source_sidecar, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(roadmap_assumptions.RoadmapAssumptionError) as excinfo:
        roadmap_assumptions.load_probe_sidecar(repo)

    assert excinfo.value.code in {"sidecar_contract_drift", "probe_contract_drift"}


def test_registry_free_selector_rejects_case_variant_status_like_banner(tmp_path):
    repo = make_repo(tmp_path)
    candidate = repo / "specs" / "phase-plans-v1.md"
    candidate.write_text(
        "# Roadmap\n\n> **STATUS (2026-08-01): ACTIVE - malformed declaration.**\n\n## Body\n",
        encoding="utf-8",
    )

    with pytest.raises(roadmap_lint.MalformedBannerError):
        discovery._return_selectable_roadmap(repo, candidate, "test")


@pytest.mark.parametrize(
    "declaration",
    (
        " > # SUPERSEDED - malformed declaration.",
        "> ## SUPERSEDED - malformed declaration.",
        "> # **SUPERSEDED** - malformed declaration.",
        "> ** Status (2026-08-01): SUPERSEDED - malformed declaration.**",
        "> *Status (2026-08-01): SUPERSEDED - malformed declaration.*",
        "> # ACTIVE - malformed declaration.",
        "> ACTIVE - malformed declaration.",
        "> DELIVERED - malformed declaration.",
        "> # STATUS (2026-08-02): ACTIVE - malformed declaration.",
        "> # STATUS (2026-08-01): SUPERSEDED - malformed declaration.",
    ),
)
def test_registry_free_selector_rejects_indented_status_like_banner(tmp_path, declaration):
    repo = make_repo(tmp_path)
    candidate = repo / "specs" / "phase-plans-v1.md"
    candidate.write_text(
        f"# Roadmap\n\n{declaration}\n\n## Body\n",
        encoding="utf-8",
    )

    with pytest.raises(roadmap_lint.MalformedBannerError):
        discovery._return_selectable_roadmap(repo, candidate, "test")


@pytest.mark.parametrize(
    "prose",
    (
        "> This roadmap remains active for migration context.",
        "> The delivered artifacts are retained for reference.",
    ),
)
def test_registry_free_selector_preserves_declaration_free_legacy_prose(tmp_path, prose):
    repo = make_repo(tmp_path)
    candidate = repo / "specs" / "phase-plans-v1.md"
    candidate.write_text(f"# Roadmap\n\n{prose}\n\n## Body\n", encoding="utf-8")

    assert discovery._return_selectable_roadmap(repo, candidate, "test") == candidate.resolve()


def test_registry_selector_rejects_unregistered_declaration_free_candidate(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    candidate = repo / "specs" / "phase-plans-unregistered.md"
    candidate.write_text("# Unregistered roadmap\n\n## Body\n", encoding="utf-8")
    monkeypatch.setattr(
        roadmap_lint,
        "validate_roadmap_status_coherence",
        lambda *_args, **_kwargs: {
            "schema": "roadmap_status_manifest.v1",
            "selected_roadmap": "specs/phase-plans-v10.md",
            "roadmaps": [{"path": "specs/phase-plans-v10.md", "status": "active"}],
        },
    )

    with pytest.raises(roadmap_lint.StatusCoherenceError, match="not registered"):
        discovery._return_selectable_roadmap(repo, candidate, "explicit")


def test_selector_read_failure_is_typed_not_selectable(tmp_path):
    repo = make_repo(tmp_path)
    candidate = repo / "specs" / "phase-plans-v1.md"
    candidate.write_text("# Roadmap\n", encoding="utf-8")

    with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
        with pytest.raises(roadmap_lint.RoadmapStatusError):
            discovery._return_selectable_roadmap(repo, candidate, "test")


def test_manifest_git_source_failure_is_typed(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    real_run = plan_manifest.subprocess.run

    def fail_ls_tree(argv, **kwargs):
        if "ls-tree" in argv:
            return subprocess.CompletedProcess(argv, 128, b"", b"fatal: unavailable")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(plan_manifest.subprocess, "run", fail_ls_tree)

    with pytest.raises(plan_manifest.ManifestSourceError):
        plan_manifest.canonical_plan_files(repo, head)


@pytest.mark.parametrize("defect", ("missing", "symlink", "unreadable"))
def test_manifest_physical_source_failure_is_typed(tmp_path, monkeypatch, defect):
    repo = make_repo(tmp_path)
    plans = repo / "plans"
    hidden = repo / "plans-hidden"
    plans.rename(hidden)
    if defect == "symlink":
        plans.symlink_to(hidden, target_is_directory=True)
    elif defect == "unreadable":
        plans.mkdir()
        monkeypatch.setattr(plan_manifest.os, "listdir", lambda _path: (_ for _ in ()).throw(PermissionError("denied")))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    with pytest.raises(plan_manifest.ManifestSourceError):
        plan_manifest.canonical_plan_files(repo, head)


def test_physical_scan_rejects_or_observes_plans_ancestor_swap(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path)
    _commit_plan(repo)
    hidden_rel = "plans/phase-plan-v2-HIDDEN.md"
    (repo / hidden_rel).write_text(
        "---\nphase: HIDDEN\n---\n# Hidden plan\n", encoding="utf-8"
    )
    plans = repo / "plans"
    moved = tmp_path / "moved-plans"
    external = tmp_path / "external-plans"
    external.mkdir()
    real_listdir = os.listdir
    swapped = False

    def swapping_listdir(path):
        nonlocal swapped
        if not swapped:
            plans.rename(moved)
            plans.symlink_to(external, target_is_directory=True)
            try:
                result = real_listdir(path)
            finally:
                plans.unlink()
                moved.rename(plans)
            swapped = True
            return result
        return real_listdir(path)

    monkeypatch.setattr(plan_manifest.os, "listdir", swapping_listdir)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    try:
        files = plan_manifest.canonical_plan_files(repo, head)
    except plan_manifest.ManifestSourceError:
        pass
    else:
        assert hidden_rel in files.paths()
    assert swapped


def test_check_rejects_root_change_between_physical_and_manifest_snapshots(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path / "initial")
    tracked_rel = _commit_plan(repo)
    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps({"plans": [{"file": tracked_rel}]}) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "register plan"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    replacement = tmp_path / "replacement"
    shutil.copytree(repo, replacement, symlinks=True)
    hidden_rel = "plans/phase-plan-v2-HIDDEN.md"
    (replacement / hidden_rel).write_text(
        "---\nphase: HIDDEN\n---\n# Hidden\n",
        encoding="utf-8",
    )

    manifest.write_text('{"plans":[]}\n', encoding="utf-8")
    assert check(repo).exit_code == 1
    assert check(replacement).exit_code == 1

    scanned_root = tmp_path / "scanned-root"
    real_scan = plan_manifest._scan_plans_dir_physical
    swapped = False

    def swap_after_physical_scan(scan_repo, **kwargs):
        nonlocal swapped
        result = real_scan(scan_repo, **kwargs)
        if not swapped:
            Path(scan_repo).rename(scanned_root)
            replacement.rename(repo)
            swapped = True
        return result

    monkeypatch.setattr(
        plan_manifest,
        "_scan_plans_dir_physical",
        swap_after_physical_scan,
    )

    try:
        result = check(repo)
    except plan_manifest.ManifestSourceError:
        pass
    else:
        assert result.exit_code != 0
    assert swapped


@pytest.mark.parametrize("operation", ("check", "unregistered"))
def test_manifest_inventory_rejects_temporary_parent_substitution(
    tmp_path, monkeypatch, operation
):
    active_parent = tmp_path / "active"
    repo = make_repo(active_parent)
    tracked_rel = _commit_plan(repo)

    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps({"plans": [{"file": tracked_rel}]}) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "register plan"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    alternate_parent = tmp_path / "alternate"
    shutil.copytree(active_parent, alternate_parent, symlinks=True)
    alternate_repo = alternate_parent / "repo"
    hidden_rel = "plans/phase-plan-v2-HIDDEN.md"

    (repo / hidden_rel).write_text(
        "---\nphase: HIDDEN\n---\n# Hidden\n",
        encoding="utf-8",
    )
    (alternate_repo / "plans" / "manifest.json").write_text(
        '{"plans":[]}\n',
        encoding="utf-8",
    )

    assert check(repo).exit_code == 1
    assert check(alternate_repo).exit_code == 1
    assert plan_manifest.unregistered_plan_files(repo) == (hidden_rel,)
    assert plan_manifest.unregistered_plan_files(alternate_repo) == (tracked_rel,)

    parked_active = tmp_path / "parked-active"
    real_scan = plan_manifest._scan_plans_dir_physical
    swaps = 0

    def scan_with_temporary_parent_substitution(scan_repo, **kwargs):
        nonlocal swaps
        active_parent.rename(parked_active)
        alternate_parent.rename(active_parent)
        try:
            return real_scan(scan_repo, **kwargs)
        finally:
            active_parent.rename(alternate_parent)
            parked_active.rename(active_parent)
            swaps += 1

    monkeypatch.setattr(
        plan_manifest,
        "_scan_plans_dir_physical",
        scan_with_temporary_parent_substitution,
    )

    if operation == "check":
        result = check(repo)
        assert result.exit_code != 0
        assert any(item.path == hidden_rel for item in result.missing)
    else:
        result = plan_manifest.unregistered_plan_files(repo)
        assert result == (hidden_rel,)
    assert swaps == 1


@pytest.mark.parametrize("operation", ("check", "unregistered"))
def test_manifest_inventory_binds_stage_zero_index_to_snapshot_root(
    tmp_path, monkeypatch, operation
):
    active_parent = tmp_path / "active"
    repo = make_repo(active_parent)
    tracked_rel = _commit_plan(repo)

    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps({"plans": [{"file": tracked_rel}]}) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "register plan"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    alternate_parent = tmp_path / "alternate"
    shutil.copytree(active_parent, alternate_parent, symlinks=True)
    alternate_repo = alternate_parent / "repo"
    (alternate_repo / "plans" / "manifest.json").write_text(
        '{"plans":[]}\n',
        encoding="utf-8",
    )

    staged_rel = "plans/phase-plan-v2-STAGED.md"
    staged_path = repo / staged_rel
    staged_path.write_text(
        "---\nphase: STAGED\n---\n# Staged\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", staged_rel], cwd=repo, check=True)
    staged_path.unlink()

    assert check(repo).exit_code == 1
    assert check(alternate_repo).exit_code == 1
    assert plan_manifest.unregistered_plan_files(repo) == (staged_rel,)
    assert plan_manifest.unregistered_plan_files(alternate_repo) == (tracked_rel,)

    parked_active = tmp_path / "parked-active"
    real_stage_scan = plan_manifest._git_ls_files_stage_plans
    swaps = 0

    def stage_scan_from_alternate(repo_arg, **kwargs):
        nonlocal swaps
        active_parent.rename(parked_active)
        alternate_parent.rename(active_parent)
        try:
            return real_stage_scan(repo_arg, **kwargs)
        finally:
            active_parent.rename(alternate_parent)
            parked_active.rename(active_parent)
            swaps += 1

    monkeypatch.setattr(
        plan_manifest,
        "_git_ls_files_stage_plans",
        stage_scan_from_alternate,
    )

    if operation == "check":
        result = check(repo)
        assert result.exit_code != 0
        assert any(item.path == staged_rel for item in result.missing)
    else:
        result = plan_manifest.unregistered_plan_files(repo)
        assert result == (staged_rel,)
    assert swaps == 1


def test_current_authority_hash_binds_working_files_to_snapshot_root(
    tmp_path, monkeypatch
):
    active_parent = tmp_path / "active"
    repo = make_repo(active_parent)
    plan_rel = _commit_plan(repo)
    plan_bytes = (repo / plan_rel).read_bytes()

    authority = {
        "schema": "plan_current_authority.v1",
        "source": "agent-harness#620",
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "roadmap_sha256": None,
    }
    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "file": plan_rel,
                        "plan_authority_history": [authority],
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "plans/manifest.json"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "bind current authority"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    alternate_parent = tmp_path / "alternate"
    shutil.copytree(active_parent, alternate_parent, symlinks=True)
    alternate_repo = alternate_parent / "repo"

    (repo / plan_rel).write_text(
        "---\nphase: RUNNER\n---\n# Drifted\n",
        encoding="utf-8",
    )
    (alternate_repo / "plans" / "manifest.json").write_text(
        '{"plans":[]}\n',
        encoding="utf-8",
    )

    state_a = check(repo)
    assert state_a.exit_code == 1
    assert any(
        item.path == plan_rel and item.kind == "plan-digest"
        for item in state_a.malformed
    )
    assert check(alternate_repo).exit_code == 1

    parked_active = tmp_path / "parked-active"
    real_hasher = plan_manifest._regular_repo_files_sha256
    swaps = 0

    def hash_from_alternate(repo_arg, rel_paths, **kwargs):
        nonlocal swaps
        active_parent.rename(parked_active)
        alternate_parent.rename(active_parent)
        try:
            return real_hasher(repo_arg, rel_paths, **kwargs)
        finally:
            active_parent.rename(alternate_parent)
            parked_active.rename(active_parent)
            swaps += 1

    monkeypatch.setattr(
        plan_manifest,
        "_regular_repo_files_sha256",
        hash_from_alternate,
    )

    result = check(repo)
    assert swaps == 1
    assert result.exit_code != 0
    assert any(
        item.path == plan_rel and item.kind == "plan-digest"
        for item in result.malformed
    )


_ACTIVE_BANNER = (
    "# Roadmap\n\n"
    "> **Status (2026-08-01): ACTIVE — created this date, nothing executed yet.**\n"
)
_SUPERSEDED_BANNER = (
    "# Roadmap\n\n"
    "> # SUPERSEDED — replaced by `specs/phase-plans-v1.md` (2026-08-01)\n"
)


def _roadmap_check_fixture(tmp_path, *, banners, statuses):
    repo = make_repo(tmp_path)
    plan_rel = _commit_plan(repo)

    for rel, banner in banners.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(banner, encoding="utf-8")

    registry_payload = {
        "schema": "roadmap_status_manifest.v1",
        "selected_roadmap": "specs/phase-plans-v1.md",
        "roadmaps": [
            {"path": rel, "status": status}
            for rel, status in sorted(statuses.items())
        ],
    }
    registry = repo / "specs" / "roadmap-status.json"
    registry.write_text(json.dumps(registry_payload) + "\n", encoding="utf-8")

    (repo / "plans" / "manifest.json").write_text(
        json.dumps({"plans": [{"file": plan_rel}]}) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "roadmap fixture"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo, registry, registry_payload


def _assert_check_fails_closed(repo):
    try:
        result = check(repo)
    except plan_manifest.ManifestSourceError:
        return
    assert result.exit_code != 0


def test_roadmap_coverage_ignores_ambient_git_index_file(tmp_path, monkeypatch):
    repo, _registry, _payload = _roadmap_check_fixture(
        tmp_path,
        banners={
            "specs/phase-plans-v1.md": _ACTIVE_BANNER,
            "specs/phase-plans-v2.md": _SUPERSEDED_BANNER,
        },
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    _assert_check_fails_closed(repo)

    alternate_index = tmp_path / "alternate-index"
    alternate_env = dict(os.environ)
    alternate_env["GIT_INDEX_FILE"] = str(alternate_index)
    subprocess.run(
        ["git", "read-tree", "HEAD"],
        cwd=repo,
        env=alternate_env,
        check=True,
    )
    subprocess.run(
        ["git", "update-index", "--force-remove", "specs/phase-plans-v2.md"],
        cwd=repo,
        env=alternate_env,
        check=True,
    )

    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate_index))
    _assert_check_fails_closed(repo)


def test_roadmap_registry_and_banners_are_one_pinned_snapshot(
    tmp_path, monkeypatch
):
    repo, registry, _payload = _roadmap_check_fixture(
        tmp_path,
        banners={"specs/phase-plans-v1.md": _SUPERSEDED_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    roadmap = repo / "specs" / "phase-plans-v1.md"
    _assert_check_fails_closed(repo)

    real_parse = roadmap_lint.parse_roadmap_status_manifest
    changed = False

    def parse_then_replace_sources(text):
        nonlocal changed
        parsed = real_parse(text)
        registry.write_text("not json\n", encoding="utf-8")
        roadmap.write_text(_ACTIVE_BANNER, encoding="utf-8")
        changed = True
        return parsed

    monkeypatch.setattr(
        roadmap_lint,
        "parse_roadmap_status_manifest",
        parse_then_replace_sources,
    )

    try:
        result = check(repo)
    except plan_manifest.ManifestSourceError:
        assert changed
        return
    assert changed
    assert result.exit_code != 0


def test_roadmap_status_registry_rejects_external_symlink(tmp_path):
    repo, registry, payload = _roadmap_check_fixture(
        tmp_path / "repo-state",
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )

    external_registry = tmp_path / "external-roadmap-status.json"
    external_registry.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    registry.unlink()
    registry.symlink_to(external_registry)

    assert registry.is_symlink()
    _assert_check_fails_closed(repo)


def test_manifest_check_requires_registry_committed_in_audited_tree(tmp_path):
    repo, registry, _payload = _roadmap_check_fixture(
        tmp_path,
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    assert check(repo).exit_code == 0
    assert not (repo / "plans" / "phase-plan-v10-LEGIBLE.md").exists()
    registry.unlink()

    with pytest.raises(
        plan_manifest.ManifestSourceError,
        match="committed roadmap-status registry is absent",
    ):
        check(repo)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(
        plan_manifest.ManifestSourceError,
        match="committed roadmap-status registry is absent",
    ):
        plan_manifest.canonical_plan_files(repo, head)


def test_public_roadmap_reader_honors_requested_path(tmp_path, monkeypatch):
    repo, registry, _payload = _roadmap_check_fixture(
        tmp_path / "repo-state",
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )

    assert roadmap_lint.read_roadmap_status(
        repo,
        repo / "specs" / "missing-roadmap-status.json",
    ) is None
    assert roadmap_lint.read_roadmap_status(repo, registry) is not None

    monkeypatch.chdir(tmp_path)
    relative_repo = repo.relative_to(tmp_path)
    relative_registry = relative_repo / "specs" / "roadmap-status.json"
    assert roadmap_lint.read_roadmap_status(
        relative_repo,
        relative_registry,
    ) is not None

    nested = repo / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    repo_from_child = Path("..")
    assert roadmap_lint.read_roadmap_status(
        repo_from_child,
        repo_from_child / "specs" / "roadmap-status.json",
    ) is not None
    assert roadmap_lint.read_roadmap_status(
        repo_from_child,
        Path("specs/roadmap-status.json"),
    ) is not None

    monkeypatch.chdir(tmp_path)
    repo_alias = tmp_path / "repo-alias"
    repo_alias.symlink_to(repo, target_is_directory=True)
    assert roadmap_lint.read_roadmap_status(
        repo_alias,
        repo_alias / "specs" / "roadmap-status.json",
    ) is not None
    relative_alias = repo_alias.relative_to(tmp_path)
    assert roadmap_lint.read_roadmap_status(
        relative_alias,
        relative_alias / "specs" / "roadmap-status.json",
    ) is not None


def test_public_roadmap_reader_rejects_path_outside_repo(tmp_path):
    repo, _registry, payload = _roadmap_check_fixture(
        tmp_path / "repo-state",
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    external = tmp_path / "external-roadmap-status.json"
    external.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    external_dir = tmp_path / "external-dir"
    external_dir.mkdir()
    linked_dir = repo / "specs" / "external-link"
    linked_dir.symlink_to(external_dir, target_is_directory=True)

    for requested in (
        external,
        repo / ".." / "missing-roadmap-status.json",
        linked_dir / "missing-roadmap-status.json",
    ):
        with pytest.raises(roadmap_lint.MalformedRegistryError):
            roadmap_lint.read_roadmap_status(repo, requested)


@pytest.mark.parametrize("source", ("registry", "banner"))
def test_direct_roadmap_validation_rejects_external_symlink_source(
    tmp_path, source
):
    repo, registry, payload = _roadmap_check_fixture(
        tmp_path / "repo-state",
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    banner = repo / "specs" / "phase-plans-v1.md"

    if source == "registry":
        external = tmp_path / "external-roadmap-status.json"
        external.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        registry.unlink()
        registry.symlink_to(external)
    else:
        external = tmp_path / "external-roadmap.md"
        external.write_text(_ACTIVE_BANNER, encoding="utf-8")
        banner.unlink()
        banner.symlink_to(external)

    with pytest.raises(roadmap_lint.RoadmapStatusError):
        roadmap_lint.validate_roadmap_status_coherence(repo, required=True)


@pytest.mark.parametrize("source", ("registry", "banner"))
def test_direct_roadmap_validation_rejects_fifo_without_blocking(
    tmp_path, source
):
    repo, registry, _payload = _roadmap_check_fixture(
        tmp_path,
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    target = (
        registry
        if source == "registry"
        else repo / "specs" / "phase-plans-v1.md"
    )
    target.unlink()
    os.mkfifo(target)

    def timeout_handler(_signum, _frame):
        raise TimeoutError("roadmap validation blocked on a FIFO")

    previous = signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, 1.0)
    try:
        with pytest.raises(roadmap_lint.RoadmapStatusError):
            roadmap_lint.validate_roadmap_status_coherence(repo, required=True)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_required_roadmap_marker_is_bound_to_absent_registry_snapshot(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path)
    marker = repo / "plans" / "phase-plan-v10-LEGIBLE.md"
    marker.write_text("---\nphase: LEGIBLE\n---\n# LEGIBLE\n", encoding="utf-8")
    registry = repo / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
    parked_marker = tmp_path / "parked-marker.md"
    real_validate = roadmap_lint._validate_roadmap_status_sources
    mutated = False

    def mutate_after_snapshot(repo_arg, required, **kwargs):
        nonlocal mutated
        registry.write_text("not json\n", encoding="utf-8")
        marker.rename(parked_marker)
        mutated = True
        try:
            return real_validate(repo_arg, required, **kwargs)
        finally:
            parked_marker.rename(marker)
            registry.unlink()

    monkeypatch.setattr(
        roadmap_lint,
        "_validate_roadmap_status_sources",
        mutate_after_snapshot,
    )

    with pytest.raises(roadmap_lint.RoadmapStatusError):
        roadmap_lint.validate_roadmap_status_coherence(repo, required=True)
    assert mutated
    assert marker.is_file()
    assert not registry.exists()


@pytest.mark.parametrize("source", ("registry", "banner"))
def test_roadmap_evidence_validation_rejects_external_symlink_source(
    tmp_path, source
):
    repo, registry, payload = _roadmap_check_fixture(
        tmp_path / "repo-state",
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    record = legible_evidence.collect_roadmap_status(repo, required=True)
    banner = repo / "specs" / "phase-plans-v1.md"

    if source == "registry":
        external = tmp_path / "external-roadmap-status.json"
        external.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        registry.unlink()
        registry.symlink_to(external)
    else:
        external = tmp_path / "external-roadmap.md"
        external.write_text(_ACTIVE_BANNER, encoding="utf-8")
        banner.unlink()
        banner.symlink_to(external)

    with pytest.raises(legible_evidence.LegibleStatusEvidenceError):
        legible_evidence.validate_roadmap_status_evidence(
            repo,
            record,
            required=True,
        )


@pytest.mark.parametrize("source", ("registry", "banner"))
def test_roadmap_evidence_validation_rejects_fifo_without_blocking(
    tmp_path, source
):
    repo, registry, _payload = _roadmap_check_fixture(
        tmp_path,
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    record = legible_evidence.collect_roadmap_status(repo, required=True)
    target = (
        registry
        if source == "registry"
        else repo / "specs" / "phase-plans-v1.md"
    )
    target.unlink()
    os.mkfifo(target)

    def timeout_handler(_signum, _frame):
        raise TimeoutError("roadmap evidence validation blocked on a FIFO")

    previous = signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, 1.0)
    try:
        with pytest.raises(legible_evidence.LegibleStatusEvidenceError):
            legible_evidence.validate_roadmap_status_evidence(
                repo,
                record,
                required=True,
            )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_roadmap_evidence_revalidates_full_banner_coherence(tmp_path):
    repo, _registry, _payload = _roadmap_check_fixture(
        tmp_path,
        banners={"specs/phase-plans-v1.md": _ACTIVE_BANNER},
        statuses={"specs/phase-plans-v1.md": "active"},
    )
    record = legible_evidence.collect_roadmap_status(repo, required=True)
    banner = repo / "specs" / "phase-plans-v1.md"
    banner.write_text(
        _ACTIVE_BANNER
        + "> **Status (2026-08-02): ACTIVE — created this date, nothing executed yet.**\n",
        encoding="utf-8",
    )

    with pytest.raises(legible_evidence.LegibleStatusEvidenceError) as excinfo:
        legible_evidence.validate_roadmap_status_evidence(
            repo,
            record,
            required=True,
        )
    assert excinfo.value.code == "roadmap_status_coherence_drift"


def test_cli_attest_passes_preimport_process_token_into_runner_workflow(tmp_path, monkeypatch):
    from phase_loop_runtime import cli

    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    observed = {}
    monkeypatch.setattr(
        cli,
        "_ATTEST_PREIMPORT_BOOTSTRAP",
        {
            "process_start_token": "preimport-token",
            "bootstrap_head": head,
            "repo_realpath": str(repo.resolve()),
            "cli_path": str(Path(cli.__file__).resolve()),
            "cli_sha256": "0" * 64,
            "python_executable": sys.executable,
        },
    )

    def fake_attest(**kwargs):
        observed.update(kwargs)
        return {"status": "sealed", "head": head}

    monkeypatch.setattr(legible_evidence, "attest", fake_attest)

    assert cli.main(
        [
            "attest",
            "--repo",
            str(repo),
            "--stage",
            "candidate",
            "--expected-head",
            head,
            "--builder-run-id",
            "builder-1",
            "--json",
        ]
    ) == 0
    assert observed["process_start_token"] == "preimport-token"
    assert observed["preimport_bootstrap"] == cli._ATTEST_PREIMPORT_BOOTSTRAP


def test_candidate_operational_evidence_requires_distinct_builder_transition_candidate_chain(tmp_path):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    sections["process_attestations"]["transition"]["process_start_token"] = "candidate-token"
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / "duplicate-process-token",
        stage="candidate",
        expected_head=head,
        sections=sections,
    )

    result = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="candidate", expected_head=head
    )

    assert not result.ok
    assert result.code == "operational_evidence_sections"


def test_probe_response_semantics_are_replayed_not_inferred_from_state():
    probe = {
        "id": "fixture-probe",
        "kind": "github_issue",
        "expected": {"state": "CLOSED"},
    }
    payload = {
        "probe_id": "fixture-probe",
        "state": "resolved",
        "observation": {"state": "OPEN"},
    }

    finding = legible_evidence._probe_response_finding(probe, payload)

    assert finding is not None


@pytest.mark.parametrize("field", (*LEGIBLE_CONTRACT_FIXED_FIELDS, "roadmap_sha256"))
def test_legible_manifest_contract_rejects_every_frozen_field_drift(tmp_path, field):
    repo = make_repo(tmp_path)
    rel, _contract = _write_legible_manifest_contract(repo)
    manifest_path = repo / "plans" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["plans"][0]["lifecycle"][0]["metadata"]["legible_plan_contract"][field]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    result = check(repo)

    assert result.exit_code == 1
    assert (rel, "plan-contract") in [(item.path, item.kind) for item in result.malformed]


def test_assumption_sidecar_rejects_coordinated_roadmap_and_digest_drift(tmp_path):
    source_repo = Path(__file__).resolve().parents[2]
    repo = tmp_path / "coordinated-roadmap-drift"
    roadmap_path = repo / roadmap_assumptions.CANONICAL_ROADMAP_REL
    roadmap_path.parent.mkdir(parents=True)
    roadmap_path.write_bytes(
        (source_repo / roadmap_assumptions.CANONICAL_ROADMAP_REL).read_bytes() + b"\n"
    )
    sidecar = json.loads(
        (
            source_repo
            / "phase-loop-runtime"
            / "tests"
            / "fixtures"
            / "roadmap-assumption-probes-v10.json"
        ).read_text(encoding="utf-8")
    )
    sidecar["roadmap_sha256"] = hashlib.sha256(roadmap_path.read_bytes()).hexdigest()
    sidecar_path = repo / roadmap_assumptions.PROBE_SIDECAR_REL
    sidecar_path.write_text(json.dumps(sidecar, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(roadmap_assumptions.RoadmapAssumptionError) as excinfo:
        roadmap_assumptions.load_probe_sidecar(repo)

    assert excinfo.value.code == "sidecar_contract_drift"


def test_manifest_plan_entry_stat_failure_is_typed(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    target = repo / _commit_plan(repo)
    real_stat = os.stat

    def fail_target(path, *args, **kwargs):
        if path == os.fsencode(target.name) and kwargs.get("dir_fd") is not None:
            raise PermissionError("denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(plan_manifest.os, "stat", fail_target)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    with pytest.raises(plan_manifest.ManifestSourceError):
        plan_manifest.canonical_plan_files(repo, head)


def test_attester_distinguishes_original_landing_from_corrective_anchor():
    from phase_loop_runtime import runner

    assert runner._LEGIBLE_ORIGINAL_TESTS_LANDING == "1c57cc43134506bfeb8f9c21220f8aeef32af384"
    assert runner._LEGIBLE_TESTS_LANDING == "a76b9f8bc305b9dd7f663c4a071c9ec4c154b5ea"


@pytest.mark.dotfiles_integration
def test_repaired_plan_has_no_stale_owned_set_contract():
    plan = (Path(__file__).parents[2] / "plans" / "phase-plan-v10-LEGIBLE.md").read_text(
        encoding="utf-8"
    )

    assert "exact 16-item" not in plan
    assert "01919736eb11d954a100d359b2cfdd31877de3459f486277983170ac96ff265b" not in plan


def test_pr_snapshot_collects_review_readiness(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner._legible_pr_view(tmp_path)

    requested = observed["argv"][observed["argv"].index("--json") + 1]
    assert "baseRefName" in requested
    assert "mergedAt" in requested
    assert "reviewDecision" in requested
    assert "reviews" in requested


def test_candidate_remote_binds_current_delivery_pr(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    expected_head = "1" * 40
    observed = []

    def fake_run(argv, **_kwargs):
        observed.append(argv)
        if argv[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "headRefName": "codex/v10-legible-chronology-repair",
                        "headRefOid": expected_head,
                        "state": "OPEN",
                    }
                ),
                "",
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_legible_git", lambda *_args: expected_head)

    remote_ref, remote_head = runner._legible_candidate_remote(tmp_path, expected_head)

    assert observed[0][:6] == [
        "gh", "pr", "view", "430", "--repo", "Consiliency/agent-harness"
    ]
    assert remote_ref == "refs/remotes/origin/codex/v10-legible-chronology-repair"
    assert remote_head == expected_head


def test_candidate_pr_snapshot_rejects_open_pr_at_canonical_stage(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    expected_head = "1" * 40
    payload = {
        "headRefName": "codex/v10-legible-c5-president-repair",
        "headRefOid": expected_head,
        "state": "OPEN",
        "baseRefName": "main",
        "mergeCommit": None,
        "mergedAt": None,
        "body": "LEGIBLE implementation delivery",
    }
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0, json.dumps(payload), ""),
    )

    with pytest.raises(legible_evidence.LegibleProcessBootstrapError, match="must be MERGED"):
        runner._legible_candidate_pr_snapshot(tmp_path, expected_head, require_merged=True)


def test_legible_verification_command_partition_defers_wrapper_only_for_candidate():
    from phase_loop_runtime import runner

    ordinary = ["python", "-m", "pytest", "-q"]
    wrapper = [
        "python",
        "-m",
        "phase_loop_runtime.legible_evidence",
        "verify",
        "--repo",
        ".",
        "--stage",
        "canonical-main",
        "--head",
        "HEAD",
    ]

    candidate_commands, candidate_post = runner._partition_legible_verification_commands(
        [ordinary, wrapper], "candidate"
    )
    canonical_commands, canonical_post = runner._partition_legible_verification_commands(
        [ordinary, wrapper], "canonical-main"
    )

    assert candidate_commands == [ordinary]
    assert candidate_post is None
    assert canonical_commands == [ordinary]
    assert canonical_post == wrapper


def test_legible_final_test_environment_uses_installed_marker_only(monkeypatch):
    from phase_loop_runtime import runner

    monkeypatch.setenv("PHASE_LOOP_TDD_EXPECT_LEGIBLE", "1")

    env = runner._legible_final_test_environment()

    assert "PHASE_LOOP_TDD_EXPECT_LEGIBLE" not in env
    assert env["PYTHONPATH"] == "src"


def test_legible_public_contract_and_plan_describe_repaired_forward_process():
    repo = Path(__file__).resolve().parents[2]
    contract = (
        Path(legible_evidence.__file__).resolve().parent
        / "_contract_docs/runtime/verification-evidence-contract.md"
    ).read_text(encoding="utf-8")
    plan_path = repo / "plans/phase-plan-v10-LEGIBLE.md"
    plan = (
        plan_path.read_text(encoding="utf-8")
        if plan_path.is_file()
        else LEGIBLE_REPAIRED_PLAN_EXCERPT
    )

    assert "exact 18-path LEGIBLE implementation/test partition" in contract
    assert "name the no-exemptions base form, not every legal v2 artifact" in contract
    assert "the historical exact-tree publish is accepted as the" in plan
    assert "require the server-side merge commit to have `I` as its second parent" in plan


@pytest.mark.parametrize(
    ("decision", "expected"),
    (
        ("", True),
        ("APPROVED", True),
        ("CHANGES_REQUESTED", False),
        ("REVIEW_REQUIRED", False),
    ),
)
def test_pr_review_readiness_rejects_unsatisfied_decisions(decision, expected):
    from phase_loop_runtime import runner

    assert runner._legible_reviews_ready({"reviewDecision": decision}) is expected


@pytest.mark.parametrize(
    (
        "merge_snapshot_drift",
        "main_advances_during_review",
        "main_advances_at_publish",
        "post_publish_failure",
        "durability_failure",
    ),
    (
        (False, False, False, None, False),
        (True, False, False, None, False),
        (False, True, False, None, False),
        (False, False, True, None, False),
        (False, False, False, "fetch", False),
        (False, False, False, "poll_error", False),
        (False, False, False, "poll_timeout", False),
        (False, False, False, None, True),
    ),
)
def test_pr_transition_persists_identity_and_reviews_before_mutation(
    tmp_path,
    monkeypatch,
    merge_snapshot_drift,
    main_advances_during_review,
    main_advances_at_publish,
    post_publish_failure,
    durability_failure,
):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    base = "1" * 40
    head = "2" * 40
    server_merge = "3" * 40
    expected_tree = "4" * 40
    body = "reviewed transition"
    events = []
    merged = False
    post_failure_pending = post_publish_failure
    poll_timeout_remaining = 30 if post_publish_failure == "poll_timeout" else 0

    monkeypatch.setattr(runner, "_LEGIBLE_REFRESH_BASE", base)
    monkeypatch.setattr(runner, "_LEGIBLE_REFRESH_HEAD", head)
    monkeypatch.setattr(runner, "_LEGIBLE_PR_BODY_SHA256", hashlib.sha256(body.encode()).hexdigest())
    def fake_pr_view(_repo):
        nonlocal post_failure_pending, poll_timeout_remaining
        events.append("snapshot")
        if merged and post_failure_pending == "poll_error":
            post_failure_pending = None
            raise legible_evidence.LegibleProcessBootstrapError("transient GitHub read failure")
        snapshot_merged = merged
        if merged and poll_timeout_remaining:
            poll_timeout_remaining -= 1
            snapshot_merged = False
            if poll_timeout_remaining == 0:
                post_failure_pending = None
        snapshot = {
            "state": "MERGED" if snapshot_merged else "OPEN",
            "isDraft": "ready" not in events,
            "headRefOid": head,
            "baseRefName": "main",
            "baseRefOid": base,
            "mergeCommit": {"oid": server_merge} if snapshot_merged else None,
            "mergedAt": "2026-08-01T16:00:00Z" if snapshot_merged else None,
            "body": body,
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            "reviewDecision": "",
            "reviews": [],
        }
        if merge_snapshot_drift and events.count("snapshot") == 2:
            snapshot["baseRefName"] = "release"
        return snapshot

    monkeypatch.setattr(runner, "_legible_pr_view", fake_pr_view)
    monkeypatch.setattr(
        runner,
        "_legible_candidate_remote",
        lambda _repo, candidate_head: (
            events.append("candidate-remote") or "refs/remotes/origin/candidate",
            candidate_head,
        ),
    )

    def fake_git(_repo, *args):
        if args == ("rev-parse", "origin/main"):
            if merged:
                return server_merge
            if main_advances_during_review and "panel" in events:
                return "5" * 40
            return base
        if args == ("rev-parse", f"{server_merge}^{{tree}}"):
            return expected_tree
        return base

    monkeypatch.setattr(runner, "_legible_git", fake_git)
    monkeypatch.setattr(runner, "_legible_body_ancestors", lambda *_args: [base] * 6)
    monkeypatch.setattr(runner, "_legible_successful_checks", lambda *_args: ["SUCCESS"])
    monkeypatch.setattr(legible_evidence, "_changed_paths", lambda *_args: [legible_evidence._FROZEN_AGENT_HARNESS_347_PATH])
    monkeypatch.setattr(legible_evidence, "_python_semantic_tokens", lambda *_args: ("same",))
    monkeypatch.setattr(legible_evidence, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(legible_evidence, "_recomputed_merge_tree", lambda *_args: expected_tree)
    monkeypatch.setattr(legible_evidence, "_commit_parents", lambda *_args: [base, head])

    def fake_early_prover(_repo, run_dir, expected_head, bundle_path):
        events.append("early-prover")
        prover = run_dir / "c4-early-prover.json"
        prover.write_text(
            json.dumps(
                {
                    "schema": "legible_c4_early_prover.v1",
                    "head": expected_head,
                    "bundle_path": bundle_path.relative_to(repo).as_posix(),
                    "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
                    "capability": "can_probe",
                    "binding_prover": False,
                    "outcome": "DEGRADED_NO_LAUNCH",
                    "status": "DEGRADED",
                    "usable": False,
                    "codex_process_count": 0,
                    "grok_process_count": 0,
                    "text": "write-capable preflight unavailable; no prover launched",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return prover

    monkeypatch.setattr(runner, "_run_legible_c4_early_prover", fake_early_prover, raising=False)

    def fake_panel(_repo, run_dir, _expected_head, bundle_path, *, brief_path):
        events.append("panel")
        staged = bundle_path.read_text(encoding="utf-8")
        assert "DEGRADED_NO_LAUNCH" in staged
        assert "codex_process_count: 0" in staged
        assert "grok_process_count: 0" in staged
        assert "ratified degraded-evidence path" in staged
        assert "specs/phase-plans-v10.md:702" in staged
        assert "does not rewrite `binding_prover=false`" in staged
        assert "only Fable can satisfy binding_prover" not in staged
        assert "Consiliency/agent-harness#347 transition slice" in brief_path.read_text(
            encoding="utf-8"
        )
        panel = run_dir / "implementation-panel.json"
        panel.write_text('{"verdict":"AGREE"}\n', encoding="utf-8")
        return panel

    monkeypatch.setattr(runner, "_run_legible_panel", fake_panel)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(runner, "_validate_legible_transition_panel", lambda *_args: None)
    monkeypatch.setattr(runner, "_validate_legible_early_prover", lambda *_args: None)

    def fake_durability_sync(_repo, _run_id):
        events.append("durable")
        if durability_failure:
            raise OSError("durability sync failed")

    monkeypatch.setattr(runner, "fsync_run_store_durable", fake_durability_sync, raising=False)

    def fake_run(argv, **kwargs):
        nonlocal merged, post_failure_pending
        if argv[:3] == ["gh", "pr", "ready"]:
            events.append("ready")
        elif argv[:3] == ["gh", "pr", "merge"]:
            pytest.fail("C4 must not use a head-only GitHub merge mutation")
        elif "commit-tree" in argv:
            return subprocess.CompletedProcess(argv, 0, server_merge + "\n", "")
        elif "push" in argv and any(str(item).endswith(":refs/heads/main") for item in argv):
            if main_advances_at_publish:
                events.append("push-rejected")
                raise subprocess.CalledProcessError(1, argv, stderr="non-fast-forward")
            events.append("merge")
            merged = True
        elif merged and post_failure_pending == "fetch" and argv[-2:] == ["origin", "main"]:
            post_failure_pending = None
            raise subprocess.CalledProcessError(1, argv, stderr="transient fetch failure")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    if (
        merge_snapshot_drift
        or main_advances_during_review
        or main_advances_at_publish
        or durability_failure
    ):
        with pytest.raises((legible_evidence.LegibleProcessBootstrapError, OSError)):
            runner._run_legible_pr_transition(
                repo=repo,
                expected_head=base,
                builder_run_id="builder-1",
                process_start_token="transition-token",
            )
        expected = [
            "candidate-remote", "snapshot", "early-prover", "panel",
            "candidate-remote", "snapshot",
        ]
        if main_advances_at_publish:
            expected.extend(("ready", "candidate-remote", "snapshot", "durable", "push-rejected"))
        elif durability_failure:
            expected.extend(("ready", "candidate-remote", "snapshot", "durable"))
        assert events == expected
        return

    if post_publish_failure:
        with pytest.raises((legible_evidence.LegibleProcessBootstrapError, subprocess.CalledProcessError)):
            runner._run_legible_pr_transition(
                repo=repo,
                expected_head=base,
                builder_run_id="builder-1",
                process_start_token="transition-token",
            )
        intent_paths = list(
            (repo / ".phase-loop" / "runs").glob("*/legible-pr-transition-intent.json")
        )
        assert len(intent_paths) == 1
        assert not list((repo / ".phase-loop" / "runs").glob("*/legible-pr-transition.json"))

        result = runner._run_legible_operational_attestation(
            repo=repo,
            plan=repo / "plans" / "phase-plan-v10-LEGIBLE.md",
            stage="candidate",
            expected_head=base,
            builder_run_id="builder-1",
            candidate_head=None,
            process_start_token="recovery-token",
            loaded_runtime_blobs={},
        )
        payload = json.loads((repo / result["transition_artifact"]).read_text(encoding="utf-8"))
        assert payload["status"] == "transition_sealed"
        assert payload["pr_state"] == "MERGED"
        assert payload["pr_merged_at"] == "2026-08-01T16:00:00Z"
        assert payload["pr_merge_commit"] == server_merge
        return

    result = runner._run_legible_pr_transition(
        repo=repo,
        expected_head=base,
        builder_run_id="builder-1",
        process_start_token="transition-token",
    )

    assert events == [
        "candidate-remote",
        "snapshot",
        "early-prover",
        "panel",
        "candidate-remote",
        "snapshot",
        "ready",
        "candidate-remote",
        "snapshot",
        "durable",
        "merge",
        "snapshot",
    ]
    assert result["run_id"].startswith("legible-transition-")
    transition_path = repo / result["transition_artifact"]
    assert transition_path.is_file()
    payload = json.loads(transition_path.read_text(encoding="utf-8"))
    assert payload["builder_run_id"] == "builder-1"
    assert payload["process_start_token"] == "transition-token"
    assert payload["pr_state"] == "MERGED"
    assert payload["pr_merged_at"] == "2026-08-01T16:00:00Z"
    assert payload["pr_merge_commit"] == server_merge


def test_merged_pr_transition_rebinds_fresh_candidate_without_mutation(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    refresh_base = "1" * 40
    raw_head = "2" * 40
    refresh_head = "3" * 40
    implementation_base = "4" * 40
    server_merge = "5" * 40
    candidate = "6" * 40
    expected_tree = "7" * 40
    external_path = legible_evidence._FROZEN_AGENT_HARNESS_347_PATH
    body = "reviewed merged transition"
    events = []
    snapshot = {
        "state": "MERGED",
        "isDraft": False,
        "headRefOid": refresh_head,
        "baseRefName": "main",
        "baseRefOid": refresh_base,
        "mergeCommit": {"oid": server_merge},
        "mergedAt": "2026-08-01T16:00:00Z",
        "body": body,
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        "reviewDecision": "APPROVED",
        "reviews": [{"state": "APPROVED"}],
    }
    monkeypatch.setattr(runner, "_LEGIBLE_REFRESH_BASE", refresh_base)
    monkeypatch.setattr(runner, "_LEGIBLE_REFRESH_HEAD", refresh_head)
    monkeypatch.setattr(
        runner, "_LEGIBLE_PR_BODY_SHA256", hashlib.sha256(body.encode()).hexdigest()
    )
    monkeypatch.setattr(
        runner,
        "_legible_candidate_remote",
        lambda _repo, head: events.append(("candidate-remote", head)),
    )
    monkeypatch.setattr(runner, "_legible_body_ancestors", lambda *_args: [refresh_base] * 6)
    monkeypatch.setattr(runner, "_legible_successful_checks", lambda *_args: ["SUCCESS"])
    monkeypatch.setattr(legible_evidence, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(
        legible_evidence,
        "_commit_parents",
        lambda _repo, commit: {
            server_merge: [implementation_base, refresh_head],
            refresh_head: [raw_head, refresh_base],
        }[commit],
    )
    monkeypatch.setattr(
        legible_evidence, "_changed_paths", lambda *_args: [external_path]
    )
    monkeypatch.setattr(
        legible_evidence, "_python_semantic_tokens", lambda *_args: ("same",)
    )
    monkeypatch.setattr(
        legible_evidence, "_recomputed_merge_tree", lambda *_args: expected_tree
    )
    monkeypatch.setattr(
        legible_evidence,
        "_blob_oid",
        lambda _repo, commit, _path: {
            raw_head: "8" * 40,
            refresh_head: "9" * 40,
            server_merge: "9" * 40,
        }.get(commit, "a" * 40),
    )

    def fake_git(_repo, *args):
        if args == ("rev-parse", "origin/main"):
            return server_merge
        if args == ("rev-parse", f"{server_merge}^{{tree}}"):
            return expected_tree
        raise AssertionError(args)

    monkeypatch.setattr(runner, "_legible_git", fake_git)

    def fake_early_prover(_repo, run_dir, expected_head, bundle_path):
        events.append(("early-prover", expected_head))
        path = run_dir / "c4-early-prover.json"
        path.write_text(
            json.dumps(
                    {
                        "head": expected_head,
                        "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
                        "capability": "can_probe",
                        "binding_prover": False,
                        "outcome": "DEGRADED_NO_LAUNCH",
                        "degraded_evidence_reason": "isolated executor unavailable",
                        "status": "DEGRADED",
                        "usable": False,
                        "codex_process_count": 0,
                        "grok_process_count": 0,
                    },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    monkeypatch.setattr(runner, "_run_legible_c4_early_prover", fake_early_prover)

    def fake_panel(_repo, run_dir, expected_head, bundle_path, *, brief_path):
        events.append(("panel", expected_head))
        staged = bundle_path.read_text(encoding="utf-8")
        assert "ratified degraded-evidence path" in staged
        assert "specs/phase-plans-v10.md:702" in staged
        assert "does not rewrite `binding_prover=false`" in staged
        assert "only Fable can satisfy binding_prover" not in staged
        assert "codex_process_count: 0" in staged
        assert "grok_process_count: 0" in staged
        assert "Consiliency/agent-harness#347 transition slice" in brief_path.read_text(
            encoding="utf-8"
        )
        path = run_dir / "implementation-panel.json"
        path.write_text('{"verdict":"AGREE"}\n', encoding="utf-8")
        return path

    monkeypatch.setattr(runner, "_run_legible_panel", fake_panel)
    monkeypatch.setattr(runner, "_validate_legible_transition_panel", lambda *_args: None)
    monkeypatch.setattr(
        runner,
        "fsync_run_store_durable",
        lambda _repo, run_id: events.append(("durable", run_id)),
    )

    def fake_run(argv, **_kwargs):
        assert "push" not in argv
        assert "commit-tree" not in argv
        assert argv[:3] not in (["gh", "pr", "ready"], ["gh", "pr", "merge"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner._run_legible_post_merge_transition(
        repo=repo,
        expected_head=candidate,
        builder_run_id="builder-2",
        process_start_token="rebind-token",
        snapshot=snapshot,
    )

    payload = json.loads((repo / result["transition_artifact"]).read_text(encoding="utf-8"))
    assert payload["status"] == "transition_rebound"
    assert payload["producer"] == "post_merge_rebind"
    assert payload["head"] == candidate
    assert payload["server_base"] == implementation_base
    assert payload["server_merge"] == server_merge
    assert payload["pr_head"] == refresh_head
    assert payload["merge_published_by"] == "Consiliency/agent-harness#347"
    assert events == [
        ("candidate-remote", candidate),
        ("early-prover", candidate),
        ("panel", candidate),
        ("durable", "builder-2"),
    ]


def test_merged_candidate_dispatches_to_rebind_without_builder_intent(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    observed = {}
    monkeypatch.setattr(runner, "_legible_pr_view", lambda _repo: {"state": "MERGED"})

    def fake_rebind(**kwargs):
        observed.update(kwargs)
        return {"status": "transition_rebound"}

    monkeypatch.setattr(runner, "_run_legible_post_merge_transition", fake_rebind)
    monkeypatch.setattr(
        runner,
        "_recover_legible_pr_transition",
        lambda *_args, **_kwargs: pytest.fail("no current-builder intent is recoverable"),
    )

    result = runner._run_legible_operational_attestation(
        repo=repo,
        plan=repo / "plans" / "phase-plan-v10-LEGIBLE.md",
        stage="candidate",
        expected_head="1" * 40,
        builder_run_id="builder-2",
        candidate_head=None,
        process_start_token="rebind-token",
        loaded_runtime_blobs={},
    )

    assert result == {"status": "transition_rebound"}
    assert observed["expected_head"] == "1" * 40
    assert observed["builder_run_id"] == "builder-2"
    assert observed["snapshot"] == {"state": "MERGED"}


def test_post_merge_transition_rejects_open_pr_before_staging(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    monkeypatch.setattr(runner, "_legible_candidate_remote", lambda *_args: None)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0, "", ""),
    )

    with pytest.raises(
        legible_evidence.LegibleProcessBootstrapError,
        match="cannot authorize a candidate rebind",
    ):
        runner._run_legible_post_merge_transition(
            repo=repo,
            expected_head="1" * 40,
            builder_run_id="builder-2",
            process_start_token="rebind-token",
            snapshot={"state": "OPEN"},
        )

    assert not (repo / ".phase-loop" / "runs" / "builder-2").exists()


def test_rebind_recovery_preserves_type_and_rejects_crossed_pairing(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    run_id = "builder-2"
    run_dir = repo / ".phase-loop" / "runs" / run_id
    run_dir.mkdir(parents=True)
    panel_path = run_dir / "implementation-panel.json"
    panel_path.write_text('{"verdict":"AGREE"}\n', encoding="utf-8")
    snapshot = {
        "state": "MERGED",
        "mergeCommit": {"oid": "3" * 40},
        "mergedAt": "2026-08-01T16:00:00Z",
    }
    intent_path = run_dir / "legible-pr-transition-intent.json"
    intent = {
        "schema": "legible_pr_transition_intent.v1",
        "run_id": run_id,
        "status": "transition_rebind_intent",
        "producer": "post_merge_rebind",
        "head": "1" * 40,
        "builder_run_id": run_id,
        "process_start_token": "rebind-token",
        "server_base": "2" * 40,
        "server_merge": "3" * 40,
        "pr_head": "4" * 40,
        "expected_tree": "5" * 40,
        "ready_snapshot": snapshot,
        "review_decision": "APPROVED",
        "github_review_count": 1,
        "review_panel_path": panel_path.relative_to(repo).as_posix(),
        "review_panel_sha256": hashlib.sha256(panel_path.read_bytes()).hexdigest(),
        "early_prover_path": (run_dir / "c4-early-prover.json").relative_to(repo).as_posix(),
        "early_prover_sha256": "6" * 64,
        "merge_published_by": "Consiliency/agent-harness#347",
    }
    intent["seal_sha256"] = runner._legible_transition_digest(intent)
    intent_path.write_text(json.dumps(intent, sort_keys=True) + "\n", encoding="utf-8")

    recovered = runner._seal_legible_transition(repo, intent_path, intent, snapshot)

    assert recovered["status"] == "transition_rebound"
    assert recovered["producer"] == "post_merge_rebind"
    assert recovered["expected_tree"] == "5" * 40
    assert recovered["merge_published_by"] == "Consiliency/agent-harness#347"

    transition_path = repo / recovered["transition_artifact"]
    crossed = json.loads(transition_path.read_text(encoding="utf-8"))
    crossed["status"] = "transition_sealed"
    crossed["seal_sha256"] = runner._legible_transition_digest(crossed)
    transition_path.write_text(json.dumps(crossed, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(runner, "_validate_legible_transition_panel", lambda *_args: None)
    monkeypatch.setattr(runner, "_validate_legible_early_prover", lambda *_args: None)

    with pytest.raises(
        legible_evidence.LegibleProcessBootstrapError,
        match="intent/transition type pairing",
    ):
        runner._load_legible_transition(repo, run_id)


def test_legible_panel_stages_small_bundle_contents(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker, runner
    from phase_loop_runtime.advisor_board.presets import CODE_REVIEW_BOARD

    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "panel"
    run_dir.mkdir(parents=True)
    bundle = run_dir / "bundle.md"
    bundle.write_text("staged transition evidence\n", encoding="utf-8")
    brief = runner._write_legible_transition_review_brief(run_dir, "1" * 40)
    observed = {}

    def fake_invoke(_board, artifact, **kwargs):
        observed["artifact"] = artifact
        observed.update(kwargs)
        return SimpleNamespace(
            legs=tuple(
                SimpleNamespace(
                    leg=seat.harness,
                    seat_key=seat.seat_key,
                    status="OK",
                    usable=True,
                    text="reviewed staged evidence\nAGREE",
                )
                for seat in CODE_REVIEW_BOARD.seats
            )
        )

    monkeypatch.setattr(panel_invoker, "invoke_board", fake_invoke)

    panel_path = runner._run_legible_panel(
        repo, run_dir, "1" * 40, bundle, brief_path=brief
    )

    assert observed["artifact"] == ""
    assert observed["artifact_ref"] == str(bundle)
    assert observed["brief_ref"] == str(brief)
    assert "context_refs" not in observed
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    assert panel["brief_path"] == brief.relative_to(repo).as_posix()
    assert panel["brief_sha256"] == hashlib.sha256(brief.read_bytes()).hexdigest()
    runner._validate_legible_transition_panel(repo, panel_path, "1" * 40)
    brief.write_text("drifted scope\n", encoding="utf-8")
    with pytest.raises(legible_evidence.LegibleProcessBootstrapError):
        runner._validate_legible_transition_panel(repo, panel_path, "1" * 40)


def test_legible_c4_early_prover_stages_degraded_zero_launch_audit(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker, runner

    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "early-prover"
    run_dir.mkdir(parents=True)
    bundle = run_dir / "bundle.md"
    bundle.write_text("verified transition evidence\n", encoding="utf-8")
    monkeypatch.setattr(
        panel_invoker,
        "invoke_board",
        lambda *_args, **_kwargs: pytest.fail("degraded preflight must launch no reviewer process"),
    )

    artifact = runner._run_legible_c4_early_prover(repo, run_dir, "1" * 40, bundle)

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["capability"] == "can_probe"
    assert payload["binding_prover"] is False
    assert payload["outcome"] == "DEGRADED_NO_LAUNCH"
    assert payload["status"] == "DEGRADED"
    assert payload["usable"] is False
    assert payload["codex_preflight"]["verdict"] == "FAIL"
    assert payload["codex_preflight"]["agent_launch_count"] == 0
    assert payload["codex_launch"]["launched"] is False
    assert payload["codex_launch"]["codex_process_count"] == 0
    assert payload["grok_fallback"]["os_confinement_available"] is False
    assert payload["grok_fallback"]["launched"] is False
    assert payload["grok_fallback"]["grok_process_count"] == 0


def test_pr_transition_loader_rejects_review_panel_drift(tmp_path):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    run_id = "legible-transition-fixture"
    run_dir = repo / ".phase-loop" / "runs" / run_id
    run_dir.mkdir(parents=True)
    from phase_loop_runtime.advisor_board.presets import CODE_REVIEW_BOARD

    bundle_path = run_dir / "implementation-review-bundle.md"
    bundle_prefix = b"exact-head review bundle\n"
    bundle_path.write_bytes(bundle_prefix + b"\n## Early prover evidence\n\nreceipt staged\n")
    brief_path = runner._write_legible_transition_review_brief(run_dir, "1" * 40)
    early_prover_path = run_dir / "c4-early-prover.json"
    early_prover_payload = {
        "schema": "legible_c4_early_prover.v1",
        "head": "1" * 40,
        "bundle_path": bundle_path.relative_to(repo).as_posix(),
        "bundle_sha256": hashlib.sha256(bundle_prefix).hexdigest(),
        "role": "early_prover",
        "binding_prover": False,
        "usable": False,
    }
    early_prover_path.write_text(
        json.dumps(early_prover_payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    legs = []
    verdicts = {}
    for seat in CODE_REVIEW_BOARD.seats:
        leg_path = run_dir / f"implementation-panel-{seat.harness}.json"
        leg_payload = {
            "leg": seat.harness,
            "model": seat.model,
            "seat_key": seat.seat_key,
            "status": "OK",
            "usable": True,
            "verdict": "AGREE",
            "text": "reviewed exact head\nAGREE",
        }
        leg_path.write_text(json.dumps(leg_payload, sort_keys=True) + "\n", encoding="utf-8")
        legs.append(
            {
                key: leg_payload[key]
                for key in ("leg", "model", "seat_key", "status", "usable", "verdict")
            }
            | {
                "artifact_path": leg_path.relative_to(repo).as_posix(),
                "artifact_sha256": hashlib.sha256(leg_path.read_bytes()).hexdigest(),
            }
        )
        verdicts[seat.model] = "AGREE"
    panel_path = run_dir / "implementation-panel.json"
    panel_path.write_text(
        json.dumps(
            {
                "schema": "advisor_board.v1",
                "head": "1" * 40,
                "bundle_path": bundle_path.relative_to(repo).as_posix(),
                "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
                "brief_path": brief_path.relative_to(repo).as_posix(),
                "brief_sha256": hashlib.sha256(brief_path.read_bytes()).hexdigest(),
                "legs": legs,
                "verdicts": verdicts,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    intent_path = run_dir / "legible-pr-transition-intent.json"
    intent_payload = {
        "schema": "legible_pr_transition_intent.v1",
        "run_id": run_id,
        "status": "transition_intent",
        "head": "1" * 40,
        "builder_run_id": "builder-1",
        "process_start_token": "transition-token",
        "server_base": "2" * 40,
        "server_merge": "3" * 40,
        "pr_head": "4" * 40,
        "expected_tree": "5" * 40,
        "ready_snapshot": {"state": "OPEN"},
        "review_decision": "",
        "github_review_count": 0,
        "review_panel_path": panel_path.relative_to(repo).as_posix(),
        "review_panel_sha256": hashlib.sha256(panel_path.read_bytes()).hexdigest(),
        "early_prover_path": early_prover_path.relative_to(repo).as_posix(),
        "early_prover_sha256": hashlib.sha256(early_prover_path.read_bytes()).hexdigest(),
    }
    intent_payload["seal_sha256"] = runner._legible_transition_digest(intent_payload)
    intent_path.write_text(json.dumps(intent_payload, sort_keys=True) + "\n", encoding="utf-8")
    payload = {
        "schema": "legible_pr_transition.v1",
        "run_id": run_id,
        "status": "transition_sealed",
        "head": "1" * 40,
        "builder_run_id": "builder-1",
        "process_start_token": "transition-token",
        "server_base": "2" * 40,
        "server_merge": "3" * 40,
        "pr_head": "4" * 40,
        "pr_state": "MERGED",
        "pr_merged_at": "2026-08-01T16:00:00Z",
        "pr_merge_commit": "3" * 40,
        "review_decision": "",
        "github_review_count": 0,
        "review_panel_path": panel_path.relative_to(repo).as_posix(),
        "review_panel_sha256": hashlib.sha256(panel_path.read_bytes()).hexdigest(),
        "early_prover_path": early_prover_path.relative_to(repo).as_posix(),
        "early_prover_sha256": hashlib.sha256(early_prover_path.read_bytes()).hexdigest(),
        "transition_intent_path": intent_path.relative_to(repo).as_posix(),
        "transition_intent_sha256": hashlib.sha256(intent_path.read_bytes()).hexdigest(),
        "candidate_requires_integration": True,
    }
    payload["seal_sha256"] = runner._legible_transition_digest(payload)
    transition_path = run_dir / "legible-pr-transition.json"
    transition_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    assert runner._load_legible_transition(repo, run_id)["run_id"] == run_id
    early_prover_path.write_text('{"usable":true}\n', encoding="utf-8")
    with pytest.raises(legible_evidence.LegibleProcessBootstrapError):
        runner._load_legible_transition(repo, run_id)
    early_prover_path.write_text(
        json.dumps(early_prover_payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    panel_path.write_text('{"verdict":"DISAGREE"}\n', encoding="utf-8")

    with pytest.raises(legible_evidence.LegibleProcessBootstrapError):
        runner._load_legible_transition(repo, run_id)


def test_pr_transition_loader_rejects_resealed_handwritten_panel(tmp_path):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    run_id = "legible-transition-handwritten"
    run_dir = repo / ".phase-loop" / "runs" / run_id
    run_dir.mkdir(parents=True)
    panel_path = run_dir / "implementation-panel.json"
    panel_path.write_text('{"verdict":"AGREE"}\n', encoding="utf-8")
    payload = {
        "schema": "legible_pr_transition.v1",
        "run_id": run_id,
        "status": "transition_sealed",
        "head": "1" * 40,
        "builder_run_id": "builder-1",
        "process_start_token": "transition-token",
        "server_base": "2" * 40,
        "server_merge": "3" * 40,
        "pr_head": "4" * 40,
        "pr_state": "MERGED",
        "pr_merged_at": "2026-08-01T16:00:00Z",
        "pr_merge_commit": "3" * 40,
        "review_decision": "",
        "github_review_count": 0,
        "review_panel_path": panel_path.relative_to(repo).as_posix(),
        "review_panel_sha256": hashlib.sha256(panel_path.read_bytes()).hexdigest(),
        "candidate_requires_integration": True,
    }
    payload["seal_sha256"] = runner._legible_transition_digest(payload)
    (run_dir / "legible-pr-transition.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(legible_evidence.LegibleProcessBootstrapError):
        runner._load_legible_transition(repo, run_id)


def test_transition_artifact_inventory_includes_panel(tmp_path):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    run_id = "legible-transition-inventory"
    run_dir = repo / ".phase-loop" / "runs" / run_id
    run_dir.mkdir(parents=True)
    transition = run_dir / "legible-pr-transition.json"
    panel = run_dir / "implementation-panel.json"
    transition.write_text("{}\n", encoding="utf-8")
    panel.write_text("{}\n", encoding="utf-8")

    assert runner._legible_transition_artifact_paths(repo, run_id) == (transition, panel)


def test_canonical_attest_rejects_direct_call_without_preimport_bootstrap(tmp_path, monkeypatch):
    from phase_loop_runtime import runner

    repo = make_repo(tmp_path)
    (repo / "plans" / "phase-plan-v10-LEGIBLE.md").write_text(
        "# LEGIBLE\nverification_sidecar: required\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add legible plan"], cwd=repo, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    called = False

    def fake_attest(**_kwargs):
        nonlocal called
        called = True
        return {"status": "sealed"}

    monkeypatch.setattr(runner, "run_legible_operational_attestation", fake_attest)

    with pytest.raises(legible_evidence.LegibleProcessBootstrapError):
        legible_evidence.attest(
            repo=repo,
            stage="candidate",
            expected_head=head,
            builder_run_id="builder-1",
            process_start_token="forged-direct-token",
        )
    assert not called


def test_roadmap_registry_rejects_two_coherent_active_roadmaps(tmp_path):
    repo = make_repo(tmp_path)
    first = repo / "specs" / "phase-plans-v1.md"
    second = repo / "specs" / "phase-plans-v2.md"
    active_banner = (
        "# Roadmap\n\n> **Status (2026-08-01): ACTIVE — created this date, nothing executed yet.**\n"
    )
    first.write_text(active_banner, encoding="utf-8")
    second.write_text(active_banner, encoding="utf-8")
    registry = repo / "specs" / "roadmap-status.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "roadmap_status_manifest.v1",
                "selected_roadmap": "specs/phase-plans-v2.md",
                "roadmaps": [
                    {"path": "specs/phase-plans-v1.md", "status": "active"},
                    {"path": "specs/phase-plans-v2.md", "status": "active"},
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "specs"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add roadmaps"], cwd=repo, check=True, capture_output=True)

    with pytest.raises(roadmap_lint.StatusCoherenceError):
        roadmap_lint.read_roadmap_status(repo, registry)


def test_manifest_rejects_index_symlink_with_regular_worktree_file(tmp_path):
    repo = make_repo(tmp_path)
    rel = _commit_plan(repo)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    target_blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo,
        input="phase-plan-v2-TARGET.md\n",
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--cacheinfo", "120000", target_blob, rel], cwd=repo, check=True
    )

    files = plan_manifest.canonical_plan_files(repo, head)

    assert (rel, "symlink-index") in [(item.path, item.kind) for item in files.malformed]


@pytest.mark.parametrize("mutation", ("wrong_reason", "xfail"))
def test_default_execution_rejects_non_guard_skip_semantics(tmp_path, mutation):
    source_repo = Path(__file__).resolve().parents[2]
    nodeids = legible_evidence._load_frozen_nodeids(source_repo)
    suite = ET.Element("testsuite", tests=str(len(nodeids)), skipped=str(len(nodeids)))
    for index, nodeid in enumerate(nodeids):
        file_part, test_name = nodeid.split("::", 1)
        case = ET.SubElement(
            suite,
            "testcase",
            classname=file_part.removesuffix(".py"),
            name=test_name,
        )
        skip_type = "pytest.xfail" if mutation == "xfail" and index == 0 else "pytest.skip"
        reason = "not the shared guard" if mutation == "wrong_reason" and index == 0 else LEGIBLE_SKIP_REASON
        ET.SubElement(case, "skipped", type=skip_type, message=reason)
    junit = tmp_path / f"{mutation}.xml"
    ET.ElementTree(suite).write(junit, encoding="utf-8", xml_declaration=True)

    with pytest.raises(legible_evidence.LegibleTestExecutionError):
        legible_evidence.collect_test_execution_evidence(
            source_repo,
            junit_path=junit,
            expected_total=84,
            mode="default",
        )


def test_forced_red_accepts_real_pytest_junit_failure_prefix(tmp_path):
    source_repo = Path(__file__).resolve().parents[2]
    nodeids = legible_evidence._load_frozen_nodeids(source_repo)
    suite = ET.Element("testsuite", tests=str(len(nodeids)), failures=str(len(nodeids)))
    for index, nodeid in enumerate(nodeids):
        file_part, test_name = nodeid.split("::", 1)
        case = ET.SubElement(
            suite,
            "testcase",
            classname=file_part.removesuffix(".py"),
            name=test_name,
        )
        ET.SubElement(
            case,
            "failure",
            message=f"Failed: LEGIBLE_RED::real-pytest-{index:03d}: expected",
        )
    junit = tmp_path / "real-pytest-red.xml"
    ET.ElementTree(suite).write(junit, encoding="utf-8", xml_declaration=True)

    evidence = legible_evidence.collect_test_execution_evidence(
        source_repo,
        junit_path=junit,
        expected_total=84,
        mode="forced_red",
    )

    assert evidence.failed == 84
    assert len(set(evidence.asserted_mutation_ids)) == 84


def _install_two_panel_artifact_inventory(repo: Path, sections: dict) -> Path:
    records = sections["artifacts"]["records"]
    old_record = next(record for record in records if record["path"] == "evidence/implementation-panel.json")
    old_panel = repo / old_record["path"]
    panel_bytes = old_panel.read_bytes()
    records.remove(old_record)

    candidate_run_id = sections["process_attestations"]["candidate"]["run_id"]
    current_panel = repo / ".phase-loop" / "runs" / candidate_run_id / "implementation-panel.json"
    transition_panel = repo / ".phase-loop" / "runs" / "transition-1" / "implementation-panel.json"
    for panel in (current_panel, transition_panel):
        panel.parent.mkdir(parents=True, exist_ok=True)
        panel.write_bytes(panel_bytes)
        records.append(
            {
                "path": panel.relative_to(repo).as_posix(),
                "byte_length": len(panel_bytes),
                "sha256": hashlib.sha256(panel_bytes).hexdigest(),
            }
        )
    return current_panel


def test_operational_evidence_selects_attester_panel_from_two_panel_inventory(tmp_path):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    _install_two_panel_artifact_inventory(repo, sections)
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / "two-panel-positive",
        stage="candidate",
        expected_head=head,
        sections=sections,
    )

    result = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="candidate", expected_head=head
    )

    assert result.ok, result.finding


def test_operational_evidence_rejects_duplicate_panel_in_attester_run(tmp_path):
    repo = make_repo(tmp_path)
    head, sections = _operational_fixture(repo)
    current_panel = _install_two_panel_artifact_inventory(repo, sections)
    duplicate = current_panel.parent / "duplicate" / "implementation-panel.json"
    duplicate.parent.mkdir()
    duplicate.write_bytes(current_panel.read_bytes())
    sections["artifacts"]["records"].append(
        {
            "path": duplicate.relative_to(repo).as_posix(),
            "byte_length": len(duplicate.read_bytes()),
            "sha256": hashlib.sha256(duplicate.read_bytes()).hexdigest(),
        }
    )
    path = legible_evidence._assemble_operational_evidence(
        repo=repo,
        run_dir=repo / ".phase-loop" / "runs" / "two-panel-duplicate",
        stage="candidate",
        expected_head=head,
        sections=sections,
    )

    result = legible_evidence.validate_operational_evidence(
        repo=repo, path=path, stage="candidate", expected_head=head
    )

    assert not result.ok
    assert result.finding == "artifacts: implementation panel inventory is ambiguous"
