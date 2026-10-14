"""agent-harness#1321 (REPORT 3.2 Slice B): criterion->command links in
verification.json and their export to spec E(C) ``acceptance_evidence`` records."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import validate

from phase_loop_runtime.acceptance_evidence import (
    EXTENSION_NAMESPACE,
    AcceptanceEvidenceError,
    acceptance_authority,
    bind_acceptance_evidence,
    export_acceptance_evidence,
    main,
)
from phase_loop_runtime.verification_evidence import (
    ARTIFACT_NAME,
    LOG_NAME,
    _bind_sidecar_extension,
    run_verification,
    validate_verification_artifact,
    validate_verification_artifact_for_plan,
)

from phase_loop_test_utils import make_repo

CRITERION_A = "a" * 64
CRITERION_B = "b" * 64
RECORD_FIELDS = {
    "criterion_logical_id", "argv", "exit_code", "log_sha256",
    "pipeline_mode", "pipeline_engaged", "authority",
}


def _verified_run(tmp_path, commands=None):
    repo = make_repo(tmp_path)
    run_dir = repo / ".phase-loop" / "runs" / "acceptance"
    run_verification(
        repo,
        run_dir,
        commands or [
            [sys.executable, "-c", "print('criterion a holds')"],
            [sys.executable, "-c", "print('criterion b fails'); raise SystemExit(3)"],
        ],
        None,
        None,
        30,
        phase_alias="ACCEPT",
    )
    return repo, run_dir, run_dir / ARTIFACT_NAME


def _links():
    return [
        {"criterion_logical_id": CRITERION_A, "command_index": 0},
        {"criterion_logical_id": CRITERION_B, "command_index": 1},
    ]


@pytest.mark.parametrize(
    ("mode", "engaged", "authority"),
    [
        ("standalone", False, "producer"),
        ("pipeline_optional", False, "producer"),
        ("pipeline_optional", True, "pipeline"),
        ("pipeline_required", False, "pipeline"),
        ("pipeline_required", True, "pipeline"),
    ],
)
def test_authority_follows_mode_and_actual_engagement(mode, engaged, authority):
    assert acceptance_authority(mode, engaged) == authority


@pytest.mark.parametrize(("mode", "engaged"), [
    ("standalone", False),
    ("pipeline_optional", False),
    ("pipeline_optional", True),
    ("pipeline_required", False),
    ("pipeline_required", True),
])
def test_exports_conform_to_the_merged_spec_schema(tmp_path, mode, engaged):
    fixture = json.loads((Path(__file__).parent / "data" / "acceptance-evidence-schema.json").read_text())
    _, _, artifact = _verified_run(tmp_path)
    bind_acceptance_evidence(artifact, links=_links(), pipeline_mode=mode, pipeline_engaged=engaged)

    validate(export_acceptance_evidence(artifact), fixture["schema"])


def test_export_emits_one_spec_record_per_linked_criterion(tmp_path):
    _, run_dir, artifact = _verified_run(tmp_path)
    bind_acceptance_evidence(artifact, links=_links(), pipeline_mode="standalone", pipeline_engaged=False)

    assert validate_verification_artifact(artifact).code == "nonzero_exit"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    log_bytes = (run_dir / LOG_NAME).read_bytes()
    records = export_acceptance_evidence(artifact)

    assert [set(record) for record in records] == [RECORD_FIELDS, RECORD_FIELDS]
    assert [record["criterion_logical_id"] for record in records] == [CRITERION_A, CRITERION_B]
    assert [record["exit_code"] for record in records] == [0, 3]
    for record, command in zip(records, payload["commands"]):
        assert record["argv"] == command["argv"]
        own_bytes = log_bytes[command["log_offset"]:command["log_end_offset"]]
        assert record["log_sha256"] == hashlib.sha256(own_bytes).hexdigest()
        assert record["authority"] == "producer"
        assert record["pipeline_mode"] == "standalone" and record["pipeline_engaged"] is False
    assert records[0]["log_sha256"] != records[1]["log_sha256"]


def test_pipeline_required_evidence_is_never_harness_authority(tmp_path):
    _, _, artifact = _verified_run(tmp_path)
    bind_acceptance_evidence(artifact, links=_links(), pipeline_mode="pipeline_required", pipeline_engaged=False)

    assert {record["authority"] for record in export_acceptance_evidence(artifact)} == {"pipeline"}


def test_artifact_without_links_exports_nothing(tmp_path):
    _, _, artifact = _verified_run(tmp_path)

    assert export_acceptance_evidence(artifact) == []


@pytest.mark.parametrize(
    ("links", "mode", "engaged"),
    [
        (_links(), "standalone", True),
        (_links(), "pipeline_sometimes", False),
        (_links(), "pipeline_optional", "yes"),
        ([], "standalone", False),
        ([{"criterion_logical_id": "A" * 64, "command_index": 0}], "standalone", False),
        ([{"criterion_logical_id": CRITERION_A, "command_index": 0}] * 2, "standalone", False),
        ([{"criterion_logical_id": CRITERION_A, "command_index": True}], "standalone", False),
        ([{"criterion_logical_id": CRITERION_A, "command_index": 2}], "standalone", False),
        ([{"criterion_logical_id": CRITERION_A, "command_index": 0, "note": "x"}], "standalone", False),
    ],
)
def test_bind_refuses_records_spec_would_reject(tmp_path, links, mode, engaged):
    _, _, artifact = _verified_run(tmp_path)
    before = artifact.read_bytes()

    with pytest.raises(AcceptanceEvidenceError):
        bind_acceptance_evidence(artifact, links=links, pipeline_mode=mode, pipeline_engaged=engaged)
    assert artifact.read_bytes() == before


def test_rebinding_the_namespace_is_refused(tmp_path):
    _, _, artifact = _verified_run(tmp_path)
    bind_acceptance_evidence(artifact, links=_links(), pipeline_mode="standalone", pipeline_engaged=False)

    with pytest.raises(AcceptanceEvidenceError, match="already bound"):
        bind_acceptance_evidence(artifact, links=_links(), pipeline_mode="pipeline_required", pipeline_engaged=True)


def test_editing_the_bound_mode_breaks_the_seal(tmp_path):
    _, _, artifact = _verified_run(tmp_path)
    bind_acceptance_evidence(artifact, links=_links(), pipeline_mode="pipeline_required", pipeline_engaged=False)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["extensions"][EXTENSION_NAMESPACE]["pipeline_mode"] = "standalone"
    artifact.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(AcceptanceEvidenceError):
        export_acceptance_evidence(artifact)


def test_binds_alongside_an_existing_legible_extension(tmp_path):
    legible_evidence = pytest.importorskip("phase_loop_runtime.legible_evidence")
    repo, run_dir, artifact = _verified_run(tmp_path)
    (run_dir / "legible-verification-sidecar.json").write_text("{}", encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    sidecar = legible_evidence.bind_verification_sidecar(
        repo,
        run_dir=run_dir,
        stage="candidate",
        expected_head=head,
        bootstrap_head=head,
        process_start_token="fresh-process-token",
    )
    _bind_sidecar_extension(artifact, namespace=legible_evidence.EXTENSION_NAMESPACE, record=sidecar.__dict__)
    legible_record = json.loads(artifact.read_text(encoding="utf-8"))["extensions"]

    bind_acceptance_evidence(artifact, links=_links(), pipeline_mode="pipeline_optional", pipeline_engaged=True)

    extensions = json.loads(artifact.read_text(encoding="utf-8"))["extensions"]
    assert extensions[legible_evidence.EXTENSION_NAMESPACE] == legible_record[legible_evidence.EXTENSION_NAMESPACE]
    assert validate_verification_artifact_for_plan(
        artifact, (legible_evidence.EXTENSION_NAMESPACE, EXTENSION_NAMESPACE)
    ).code == "nonzero_exit"
    assert {record["authority"] for record in export_acceptance_evidence(artifact)} == {"pipeline"}


def test_cli_prints_records(tmp_path, capsys):
    _, _, artifact = _verified_run(tmp_path)
    bind_acceptance_evidence(artifact, links=_links(), pipeline_mode="standalone", pipeline_engaged=False)

    assert main([str(artifact)]) == 0
    assert json.loads(capsys.readouterr().out) == export_acceptance_evidence(artifact)
