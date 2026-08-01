from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from phase_loop_runtime import legible_evidence
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


def _commit_plan(repo: Path, name: str = "phase-plan-v1-RUNNER.md") -> str:
    rel = f"plans/{name}"
    (repo / rel).write_text("---\nphase: RUNNER\n---\n# Runner\n", encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add plan"], cwd=repo, check=True, capture_output=True)
    return rel


def _operational_sections(repo: Path, head: str) -> dict[str, dict]:
    artifact_path = "README.md"
    artifact_bytes = (repo / artifact_path).read_bytes()
    cli_path = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "cli.py"
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text("# fixture CLI\n", encoding="utf-8")
    cli_bytes = cli_path.read_bytes()
    return {
        "roadmap_status": {
            "registry_path": "specs/roadmap-status.json",
            "registry_sha256": "1" * 64,
            "registry_byte_length": 1,
            "selected_roadmap": "specs/phase-plans-v10.md",
            "tracked_path_set_sha256": "2" * 64,
            "roadmaps": [{"path": "specs/phase-plans-v10.md"}],
        },
        "chronology": {
            "tests_landing": head,
            "implementation_base": head,
            "candidate_head": head,
            "plan_sha256": "3" * 64,
            "roadmap_sha256": "4" * 64,
        },
        "process_attestations": {
            "builder": {"run_id": "builder-1", "process_start_token": "builder-token"},
            "attester": {
                "head": head,
                "bootstrap_head": head,
                "repo_realpath": str(repo.resolve()),
                "cli_path": str(cli_path),
                "cli_sha256": hashlib.sha256(cli_bytes).hexdigest(),
                "python_executable": sys.executable,
                "process_start_token": "attester-token",
            },
        },
        "test_execution": {
            "nodeid_count": 84,
            "nodeid_digest": "8b6d153cd009bdc68ebf0f3eca2f60c505386f9d164afca3aafead981a84be22",
            "final": {"passed": 84, "skipped": 0, "failed": 0, "errors": 0},
        },
        "pull_request": {
            "repository": "Consiliency/agent-harness",
            "number": 347,
            "state": "MERGED",
            "head": head,
            "merge_commit": head,
        },
        "target_integration": {
            "candidate": head,
            "server_merge": head,
            "integration": head,
            "parents": [head, head],
        },
        "assumption_probes": {"execution_head": head, "records": [{"probe_id": "fixture"}]},
        "artifacts": {
            "records": [
                {
                    "path": artifact_path,
                    "byte_length": len(artifact_bytes),
                    "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                }
            ]
        },
    }


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


def test_legible_verify_rejects_head_that_does_not_resolve(tmp_path):
    repo = make_repo(tmp_path)
    args = SimpleNamespace(repo=str(repo), stage="candidate", head="0" * 40)
    status_record = {"roadmaps": []}

    with (
        patch.object(legible_evidence, "collect_roadmap_status", return_value=status_record),
        patch.object(legible_evidence, "validate_roadmap_status_evidence"),
    ):
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


def test_attest_cli_without_repo_still_runs_preimport_bootstrap(monkeypatch):
    from phase_loop_runtime import cli

    repo = Path(__file__).resolve().parents[2]
    head = "a" * 40
    monkeypatch.chdir(repo)

    def fake_run(argv, **kwargs):
        stdout = f"{head}\n" if "rev-parse" in argv else ""
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


def test_operational_evidence_round_trip_is_sealed_and_closed(tmp_path):
    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    run_dir = repo / ".phase-loop" / "runs" / "attest-1"
    sections = _operational_sections(repo, head)

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
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    run_dir = repo / ".phase-loop" / "runs" / "attest-1"
    sections = _operational_sections(repo, head)
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


def test_operational_evidence_rejects_unbound_process_cli(tmp_path):
    repo = make_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    sections = _operational_sections(repo, head)
    sections["process_attestations"]["attester"]["cli_sha256"] = "0" * 64
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
    run_dir = repo / ".phase-loop" / "runs" / "attest-final"
    run_verification(repo, run_dir, [], None, None, 10, phase_alias="LEGIBLE")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    evidence_path = legible_evidence.finalize_operational_attestation(
        repo=repo,
        run_dir=run_dir,
        artifact_path=run_dir / ARTIFACT_NAME,
        stage="candidate",
        expected_head=head,
        bootstrap_head=head,
        process_start_token="attester-token",
        sections=_operational_sections(repo, head),
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
