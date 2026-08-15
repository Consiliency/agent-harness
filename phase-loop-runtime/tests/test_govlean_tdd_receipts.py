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
from .govlean_freeze_receipt import govlean_api_available
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
        f"def test_intentionally_red():\n    assert False, {freeze.RED_ANCHOR_MARKER!r}\n",
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
    assert payload["red_argv"] == shlex.split(_red_command(relative))
    assert payload["red_environment"] == {freeze.ACTIVATION_ENV: "1"}
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


def test_bootstrap_writer_refuses_a_nontest_pytest_exit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    relative = _write_red_test(repo)

    with pytest.raises(freeze.FreezeReceiptError) as excinfo:
        freeze.record_content_tdd_receipt(
            repo=repo,
            test_glob=relative,
            red_command=f"{_red_command(relative)} --not-a-real-pytest-option",
            landing_ref="HEAD",
            out=repo / "receipt.json",
        )

    assert excinfo.value.code == "red_command_invalid_exit"


def test_bootstrap_writer_requires_the_deliberate_red_anchor(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    relative = "test_unmarked_red.py"
    (repo / relative).write_text(
        "def test_unmarked_red():\n    assert False, 'unrelated failure'\n",
        encoding="utf-8",
    )
    _commit(repo, relative, "add unmarked red test")

    with pytest.raises(freeze.FreezeReceiptError) as excinfo:
        freeze.record_content_tdd_receipt(
            repo=repo,
            test_glob=relative,
            red_command=_red_command(relative),
            landing_ref="HEAD",
            out=repo / "receipt.json",
        )

    assert excinfo.value.code == "red_anchor_missing"


def test_bootstrap_writer_executes_every_frozen_pytest_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    anchor = _write_red_test(repo)
    second = "test_second_contract.py"
    (repo / second).write_text(
        "def test_second_contract():\n    assert False, 'second frozen contract'\n",
        encoding="utf-8",
    )
    _commit(repo, second, "add second frozen contract")

    _receipt, payload = _record_red_receipt(repo, "test_*.py")

    assert anchor in payload["red_argv"]
    assert second in payload["red_argv"]
    assert {nodeid.split("::", 1)[0] for nodeid in payload["red_nodeids"]} == {
        anchor,
        second,
    }


def test_forced_red_fires_the_intended_govlean_anchor() -> None:
    if freeze.govlean_forced():
        pytest.fail(freeze.RED_ANCHOR_MARKER)


def test_phase_lifecycle_makes_activation_monotonic_after_execution_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / "plans").mkdir(parents=True)
    manifest = repo / "plans" / "manifest.json"
    monkeypatch.delenv(freeze.ACTIVATION_ENV, raising=False)

    manifest.write_text(
        json.dumps({"plans": [{"slug": "v10-GOVLEAN", "status": "committed"}]}),
        encoding="utf-8",
    )
    assert not freeze.govlean_api_available(
        "phase_loop_runtime.not_yet_implemented", "Missing", repo_root=repo
    )

    manifest.write_text(
        json.dumps({"plans": [{"slug": "v10-GOVLEAN", "status": "executing"}]}),
        encoding="utf-8",
    )
    assert freeze.govlean_api_available(
        "phase_loop_runtime.not_yet_implemented", "Missing", repo_root=repo
    )


def test_bootstrap_freezes_the_complete_tests_only_landing() -> None:
    repo = Path(__file__).resolve().parents[2]
    files = dict(
        freeze._test_files(
            repo,
            "phase-loop-runtime/tests/test_govlean_*.py",
            freeze.DEFAULT_FROZEN_SUPPORT_PATHS,
        )
    )
    assert set(freeze.DEFAULT_FROZEN_SUPPORT_PATHS) <= set(files)
    assert set(files) == {
        *freeze.DEFAULT_FROZEN_SUPPORT_PATHS,
        *(
            path.relative_to(repo).as_posix()
            for path in (repo / "phase-loop-runtime" / "tests").glob("test_govlean_*.py")
        ),
    }


@pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.tdd_receipts", "ContentTddReceipt"),
    reason="GOVLEAN runtime TDD-receipt capability absent",
)
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


@pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.tdd_receipts", "ContentTddReceipt"),
    reason="GOVLEAN runtime TDD-receipt capability absent",
)
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
