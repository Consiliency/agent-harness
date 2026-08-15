"""GOVLEAN EC-GOVLEAN-2 content-bound TDD receipt falsifiers."""
from __future__ import annotations

import hashlib
import importlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from . import govlean_freeze_receipt as freeze
from .phase_loop_test_utils import make_repo


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, relative: str, message: str) -> str:
    subprocess.run(["git", "add", relative], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)
    return _git(repo, "rev-parse", "HEAD")


def _red_command(relative: str) -> str:
    return f"{shlex.quote(sys.executable)} -m pytest -q {shlex.quote(relative)}"


def _write_red_test(repo: Path) -> str:
    relative = "test_intentionally_red.py"
    (repo / relative).write_text(
        "def test_intentionally_red():\n    assert False, 'GOVLEAN deliberate RED anchor'\n",
        encoding="utf-8",
    )
    _commit(repo, relative, "add frozen red test")
    return relative


def _record_red_receipt(repo: Path, relative: str) -> tuple[Path, dict]:
    receipt = repo / ".phase-loop" / "evidence" / "content-tdd-receipt.json"
    payload = freeze.record_content_tdd_receipt(
        repo=repo,
        test_glob=relative,
        red_command=_red_command(relative),
        landing_ref="HEAD",
        out=receipt,
    )
    return receipt, payload


def test_bootstrap_writer_records_sorted_content_bound_red_evidence_and_raw_logs(tmp_path):
    repo = make_repo(tmp_path)
    relative = _write_red_test(repo)

    receipt, payload = _record_red_receipt(repo, relative)

    assert payload["schema"] == "content_tdd_receipt.v1"
    assert payload["test_files"] == [
        {
            "path": relative,
            "sha256": hashlib.sha256((repo / relative).read_bytes()).hexdigest(),
        }
    ]
    assert payload["red_command"] == _red_command(relative)
    assert payload["red_nodeids"] == [f"{relative}::test_intentionally_red"]
    assert payload["red_exit_status"] != 0
    assert payload["base_commit"] == _git(repo, "rev-parse", "HEAD")
    assert payload["base_tree_digest"] == _git(repo, "rev-parse", "HEAD^{tree}")
    assert payload["landing_commit"] == _git(repo, "rev-parse", "HEAD")
    assert payload["landing_tree_digest"] == _git(repo, "rev-parse", "HEAD^{tree}")

    stdout = receipt.parent / payload["red_stdout_path"]
    stderr = receipt.parent / payload["red_stderr_path"]
    assert stdout.exists() and stderr.exists()
    assert hashlib.sha256(stdout.read_bytes()).hexdigest() == payload["red_stdout_sha256"]
    assert hashlib.sha256(stderr.read_bytes()).hexdigest() == payload["red_stderr_sha256"]
    assert "GOVLEAN deliberate RED anchor" in stdout.read_text(encoding="utf-8")
    assert json.loads(receipt.read_text(encoding="utf-8")) == payload


def test_bootstrap_writer_refuses_to_freeze_a_green_command(tmp_path):
    repo = make_repo(tmp_path)
    relative = "test_intentionally_green.py"
    (repo / relative).write_text("def test_green():\n    assert True\n", encoding="utf-8")
    _commit(repo, relative, "add green test")

    with pytest.raises(freeze.FreezeReceiptError) as excinfo:
        freeze.record_content_tdd_receipt(
            repo=repo,
            test_glob=relative,
            red_command=_red_command(relative),
            landing_ref="HEAD",
            out=repo / "receipt.json",
        )

    assert excinfo.value.code == "red_command_succeeded"


def test_runtime_verifier_accepts_untouched_frozen_tests_after_an_unrelated_commit_then_rejects_mutation(tmp_path):
    receipts = importlib.import_module("phase_loop_runtime.tdd_receipts")
    repo = make_repo(tmp_path)
    relative = _write_red_test(repo)
    receipt, _payload = _record_red_receipt(repo, relative)

    clean = receipts.verify_content_tdd_receipt(receipt_path=receipt, repo=repo)
    assert clean.ok is True

    (repo / "unrelated.md").write_text("unrelated history is not an identity selector\n", encoding="utf-8")
    _commit(repo, "unrelated.md", "unrelated landing")
    rebased = receipts.verify_content_tdd_receipt(receipt_path=receipt, repo=repo)
    assert rebased.ok is True

    (repo / relative).write_text("def test_intentionally_red():\n    assert True\n", encoding="utf-8")
    with pytest.raises(receipts.ContentTddReceiptError) as excinfo:
        receipts.verify_content_tdd_receipt(receipt_path=receipt, repo=repo)
    assert excinfo.value.code == "frozen_test_drift"


def test_runtime_verifier_rejects_a_base_tree_not_contained_in_the_declared_landing(tmp_path):
    receipts = importlib.import_module("phase_loop_runtime.tdd_receipts")
    repo = make_repo(tmp_path)
    relative = _write_red_test(repo)
    receipt, _payload = _record_red_receipt(repo, relative)
    forged = json.loads(receipt.read_text(encoding="utf-8"))
    forged["base_tree_digest"] = "f" * 40
    receipt.write_text(json.dumps(forged, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(receipts.ContentTddReceiptError) as excinfo:
        receipts.verify_content_tdd_receipt(receipt_path=receipt, repo=repo)

    assert excinfo.value.code == "base_tree_not_in_landing"
