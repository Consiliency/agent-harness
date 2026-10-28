"""Actual producer/CLI retention and signed historical custody: agent-harness#1772."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from phase_loop_runtime import artifact_retention as retention
from phase_loop_runtime.closeout_classifier import audit_ignored_outputs
from phase_loop_runtime.verification_evidence import run_verification


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], stderr=subprocess.PIPE, text=True
    ).strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / ".gitignore").write_text("/.dev-skills/\n/.phase-loop/\n")
    git(root, "add", ".gitignore")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return root


def produce(repo, code=0):
    return run_verification(
        repo,
        repo / ".dev-skills/runs/test-run",
        [[sys.executable, "-c", f"raise SystemExit({code})"]],
        None,
        None,
        10,
        phase_alias="TEST",
    )


def cli_audit(repo):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.closeout_classifier",
            "--repo",
            str(repo),
            "--phase",
            "TEST",
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("code", [0, 1])
def test_actual_producer_and_cli_record_success_or_failure_without_acceptance(
    repo, code
):
    result = produce(repo, code)
    assert result.commands[0].exit_code == code
    audit = audit_ignored_outputs(repo, "TEST")
    assert not audit["blocks"]
    assert len(audit["retained_artifact"]) == 2
    assert cli_audit(repo).returncode == 0
    (repo / ".dev-skills/notes.txt").write_text("unregistered")
    assert cli_audit(repo).returncode == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "missing",
        "sibling",
        "wrong_phase",
        "missing_phase",
        "wrong_run",
        "schema",
        "repo",
        "path",
        "symlink",
        "receipt_symlink",
        "log_binding",
        "unknown_field",
    ],
)
def test_fail_closed(repo, tmp_path, mutation):
    produce(repo)
    path = ".dev-skills/runs/test-run/verification.json"
    receipt = retention._record_path(repo, path)
    record = json.loads(receipt.read_text())
    phase = "TEST"
    if mutation == "bytes":
        (repo / path).write_text("modified")
    elif mutation == "missing":
        (repo / ".dev-skills/runs/test-run/verification.log").unlink()
    elif mutation == "sibling":
        (repo / ".dev-skills/runs/test-run/extra.txt").write_text("extra")
    elif mutation == "wrong_phase":
        phase = "OTHER"
    elif mutation == "missing_phase":
        phase = None
    elif mutation == "symlink":
        target = tmp_path / "outside"
        target.write_bytes((repo / path).read_bytes())
        (repo / path).unlink()
        (repo / path).symlink_to(target)
    elif mutation == "receipt_symlink":
        target = tmp_path / "receipt"
        target.write_bytes(receipt.read_bytes())
        receipt.unlink()
        receipt.symlink_to(target)
    else:
        if mutation == "wrong_run":
            record["statement"]["run_id"] = "different"
        elif mutation == "schema":
            record["statement"]["schema"] = "unsupported"
        elif mutation == "repo":
            record["statement"]["repo"]["root"] = str(tmp_path)
        elif mutation == "path":
            record["statement"]["files"][0]["path"] = "../outside"
        elif mutation == "unknown_field":
            record["statement"]["acceptance"] = True
        elif mutation == "log_binding":
            artifact = json.loads((repo / path).read_text())
            artifact["log_sha256"] = "0" * 64
            (repo / path).write_text(json.dumps(artifact))
            for entry in record["statement"]["files"]:
                if entry["path"] == path:
                    entry["bytes"], entry["sha256"] = retention._digest(repo / path)
        receipt.write_text(json.dumps(record))
    assert audit_ignored_outputs(repo, phase)["blocks"]


def legacy(repo):
    path = ".dev-skills/reviews/historical/failed.log"
    file = repo / path
    file.parent.mkdir(parents=True)
    file.write_bytes(b"")  # Empty/failed history is still retainable.
    return path


@pytest.fixture
def signer(tmp_path, monkeypatch):
    key = tmp_path / "test-only-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )
    allowed = tmp_path / "allowed_signers"
    allowed.write_text("custodian " + key.with_suffix(".pub").read_text())
    monkeypatch.setattr(retention, "_allowed_signers", lambda: allowed)
    return key, allowed


def propose(repo, tmp_path, path):
    output = tmp_path / "proposal.json"
    assert (
        retention.main(
            [
                "prepare",
                "--repo",
                str(repo),
                "--phase",
                "TEST",
                "--run-id",
                "historical",
                "--custodian",
                "custodian",
                "--limitations",
                "Original author unknown; custody only; failed review remains failed.",
                "--output",
                str(output),
                path,
            ]
        )
        == 0
    )
    return output


def sign(output, key, namespace=retention.NAMESPACE):
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", namespace, str(output)],
        check=True,
        capture_output=True,
    )
    return Path(str(output) + ".sig")


def adopt(repo, output, signature):
    return retention.main(
        [
            "adopt",
            "--repo",
            str(repo),
            "--statement",
            str(output),
            "--signature",
            str(signature),
        ]
    )


def test_signed_legacy_custody_and_revocation_preserve_bytes(repo, tmp_path, signer):
    path = legacy(repo)
    before = (repo / path).read_bytes()
    proposal = propose(repo, tmp_path, path)
    assert audit_ignored_outputs(repo, "TEST")[
        "blocks"
    ]  # A self-authored manifest grants nothing.
    signature = sign(proposal, signer[0])
    assert adopt(repo, proposal, signature) == 0
    assert not audit_ignored_outputs(repo, "TEST")["blocks"]
    assert (repo / path).read_bytes() == before
    assert audit_ignored_outputs(repo, "OTHER")["blocks"]
    signer[1].write_text("")
    assert audit_ignored_outputs(repo, "TEST")["blocks"]


@pytest.mark.parametrize(
    "mutation",
    [
        "unsigned",
        "wrong_namespace",
        "changed_statement",
        "changed_file",
        "untrusted",
        "repo_trust",
        "wrong_repo",
        "wrong_custodian",
        "wrong_phase",
    ],
)
def test_legacy_authorization_rejected(repo, tmp_path, signer, mutation):
    path = legacy(repo)
    proposal = propose(repo, tmp_path, path)
    signature = sign(
        proposal,
        signer[0],
        "other" if mutation == "wrong_namespace" else retention.NAMESPACE,
    )
    if mutation == "unsigned":
        signature.write_text("")
    elif mutation == "changed_file":
        (repo / path).write_text("new")
    elif mutation == "untrusted":
        signer[1].write_text("")
    elif mutation == "repo_trust":
        embedded = repo / "allowed_signers"
        embedded.write_bytes(signer[1].read_bytes())
        signer[1].unlink()
        signer[1].symlink_to(embedded)
    else:
        data = json.loads(proposal.read_text())
        if mutation == "wrong_repo":
            data["repo"]["root"] = str(tmp_path)
        elif mutation == "wrong_custodian":
            data["custodian"] = "other"
        elif mutation == "wrong_phase":
            data["phases"] = ["OTHER"]
        elif mutation == "changed_statement":
            data["limitations"] = "changed"
        proposal.write_bytes(retention._canonical(data))
    assert adopt(repo, proposal, signature) == 1
    assert audit_ignored_outputs(repo, "TEST")["blocks"]


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/absolute",
        ".dev-skills/runs/../outside",
        ".DEV-SKILLS/runs/r/file",
        ".dev-skills/runs/r/./file",
        ".dev-skills/runs/r//file",
        ".dev-skills/runs/r/\\file",
        ".git/config",
        ".dev-skills/notes.txt",
    ],
)
def test_invalid_paths_are_not_adoptable(repo, path):
    with pytest.raises(retention.RetentionError):
        retention._artifact_path(repo, path)


def test_receipts_survive_descendant_commit_but_not_unrelated_history(repo):
    produce(repo)
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "next",
    )
    assert not audit_ignored_outputs(repo, "TEST")["blocks"]
    git(repo, "checkout", "--orphan", "unrelated")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "unrelated",
    )
    assert audit_ignored_outputs(repo, "TEST")["blocks"]


def test_producer_recording_failure_is_surfaced(repo, monkeypatch):
    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(retention, "_store", fail)
    with pytest.raises(OSError, match="synthetic disk"):
        produce(repo)
    assert audit_ignored_outputs(repo, "TEST")["blocks"]


def test_no_receipt_when_head_moves_during_production(repo):
    run_dir = repo / ".dev-skills/runs/moved"
    command = [
        "git",
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "moved",
    ]
    with pytest.raises(retention.RetentionError, match="HEAD changed"):
        run_verification(repo, run_dir, [command], None, None, 10, phase_alias="TEST")
    assert audit_ignored_outputs(repo, "TEST")["blocks"]


def test_adoption_cli_does_not_overwrite_existing_output(repo, tmp_path):
    path = legacy(repo)
    proposal = propose(repo, tmp_path, path)
    before = hashlib.sha256(proposal.read_bytes()).hexdigest()
    assert (
        retention.main(
            [
                "prepare",
                "--repo",
                str(repo),
                "--phase",
                "TEST",
                "--run-id",
                "historical",
                "--custodian",
                "custodian",
                "--limitations",
                "unknown",
                "--output",
                str(proposal),
                path,
            ]
        )
        == 1
    )
    assert hashlib.sha256(proposal.read_bytes()).hexdigest() == before


def test_signed_adoption_and_audit_through_real_cli(repo, tmp_path, signer):
    import os

    path = legacy(repo)
    proposal = propose(repo, tmp_path, path)
    signature = sign(proposal, signer[0])
    home = tmp_path / "operator-home"
    trust = home / ".config/consiliency/artifact-adoption-allowed-signers"
    trust.parent.mkdir(parents=True)
    trust.write_bytes(signer[1].read_bytes())
    env = {**os.environ, "HOME": str(home)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.artifact_retention",
            "adopt",
            "--repo",
            str(repo),
            "--statement",
            str(proposal),
            "--signature",
            str(signature),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    before = {
        p.relative_to(repo): p.read_bytes()
        for p in (repo / ".dev-skills").rglob("*")
        if p.is_file()
    }
    audit = subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.closeout_classifier",
            "--repo",
            str(repo),
            "--phase",
            "TEST",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert audit.returncode == 0, audit.stdout + audit.stderr
    assert "historical_custody: retention only, not acceptance" in audit.stdout
    assert before == {
        p.relative_to(repo): p.read_bytes()
        for p in (repo / ".dev-skills").rglob("*")
        if p.is_file()
    }


def test_explicit_cross_phase_custody(repo, tmp_path, signer):
    path = legacy(repo)
    proposal = propose(repo, tmp_path, path)
    statement = json.loads(proposal.read_text())
    statement["phases"].append("CONSUMER")
    proposal.write_bytes(retention._canonical(statement))
    assert adopt(repo, proposal, sign(proposal, signer[0])) == 0
    assert not audit_ignored_outputs(repo, "CONSUMER")["blocks"]
    assert audit_ignored_outputs(repo, "UNDECLARED")["blocks"]


def test_cross_repository_receipt_copy_is_not_authority(repo, tmp_path):
    import shutil

    produce(repo)
    other = tmp_path / "other"
    git(repo, "clone", "-q", str(repo), str(other))
    shutil.copytree(repo / ".dev-skills", other / ".dev-skills")
    shutil.copytree(repo / ".phase-loop", other / ".phase-loop")
    assert audit_ignored_outputs(other, "TEST")["blocks"]


def test_partial_recording_failure_leaves_unmatched_output_blocking(repo, monkeypatch):
    original = retention.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        if "artifact-retention" in str(target):
            calls += 1
        if calls == 2:
            raise OSError("synthetic partial recording failure")
        return original(source, target)

    monkeypatch.setattr(retention.os, "replace", fail_second)
    with pytest.raises(OSError, match="synthetic partial"):
        produce(repo)
    assert audit_ignored_outputs(repo, "TEST")["blocks"]


def test_retention_cannot_satisfy_verification_acceptance(repo, tmp_path, signer):
    from phase_loop_runtime.verification_evidence import load_verification_artifact

    path = legacy(repo)
    proposal = propose(repo, tmp_path, path)
    assert adopt(repo, proposal, sign(proposal, signer[0])) == 0
    assert not audit_ignored_outputs(repo, "TEST")["blocks"]
    # The custody receipt is not a verification artifact, and the original empty
    # failed-review output does not become one through retention.
    with pytest.raises((ValueError, KeyError, TypeError)):
        load_verification_artifact(repo / path)
