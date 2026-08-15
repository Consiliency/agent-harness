"""GOVLEAN EC-GOVLEAN-3 declared commit-identity falsifiers."""
from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

from .govlean_freeze_receipt import govlean_api_available
from .phase_loop_test_utils import make_repo


pytestmark = pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.declared_identity", "DeclaredCommitIdentity"),
    reason="GOVLEAN declared-identity capability absent",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, label: str, identity: str | None = None) -> str:
    path = repo / "history.txt"
    prior = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(f"{prior}{label}\n", encoding="utf-8")
    subprocess.run(["git", "add", "history.txt"], cwd=repo, check=True)
    message = label if identity is None else f"{label}\n\nPhase-Loop-Identity: {identity}"
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)
    return _git(repo, "rev-parse", "HEAD")


def test_declared_identity_selects_the_one_trailer_match_despite_unrelated_commits_before_and_after(tmp_path):
    identity = importlib.import_module("phase_loop_runtime.declared_identity")
    repo = make_repo(tmp_path)
    _commit(repo, "unrelated before")
    expected = _commit(repo, "tests-only landing", "govlean-tests-freeze")
    _commit(repo, "unrelated after")

    selected = identity.select_declared_commit(repo, "HEAD", "govlean-tests-freeze")

    assert selected == expected


def test_declared_identity_fails_closed_when_the_requested_trailer_is_absent(tmp_path):
    identity = importlib.import_module("phase_loop_runtime.declared_identity")
    repo = make_repo(tmp_path)
    _commit(repo, "unrelated")

    with pytest.raises(identity.DeclaredIdentityError) as excinfo:
        identity.select_declared_commit(repo, "HEAD", "missing-identity")

    assert excinfo.value.code == "declared_identity_not_found"


def test_declared_identity_fails_closed_when_two_commits_declare_the_same_identity(tmp_path):
    identity = importlib.import_module("phase_loop_runtime.declared_identity")
    repo = make_repo(tmp_path)
    _commit(repo, "first declaration", "duplicate-identity")
    _commit(repo, "second declaration", "duplicate-identity")

    with pytest.raises(identity.DeclaredIdentityError) as excinfo:
        identity.select_declared_commit(repo, "HEAD", "duplicate-identity")

    assert excinfo.value.code == "declared_identity_ambiguous"
