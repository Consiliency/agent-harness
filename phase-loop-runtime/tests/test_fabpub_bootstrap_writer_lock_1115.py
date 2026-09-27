"""agent-harness#1115: the zero-history bootstrap and the run-train writer lock.

``run_train_generation_leases`` creates and flocks an empty
``<git-common-dir>/phase-loop-fabpub-broker-v1/run-train-writer.lock`` on every
attempt, before any receipt check.  The bootstrap must accept exactly that
residue (an empty regular file the operator owns), refuse anything else under the
name, and refuse to apply while a run-train holds the lock.

Every repository and authority root here lives under ``tmp_path``.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime.convergence import fencing
from phase_loop_runtime.convergence.broker import live


@pytest.fixture(autouse=True)
def _isolated_fabpub_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(tmp_path / "authority"))
    monkeypatch.delenv(live.FABPUB_LEGACY_ROOTS_ENV, raising=False)
    monkeypatch.delenv(live.FABPUB_CUTOVER_MANIFEST_ENV, raising=False)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


def _probe(tmp_path: Path, repo: Path) -> dict:
    return live.probe_zero_history_bootstrap(
        cutover_id="bootstrap-1115",
        authority_root=tmp_path / "authority",
        worktrees=(repo,),
        legacy_roots=(tmp_path / "legacy",),
        search_roots=(tmp_path,),
    )


def _writer_lock(repo: Path) -> Path:
    return live.repository_namespace_root(repo) / live.RUN_TRAIN_WRITER_LOCK


def _residue_only(repo: Path) -> Path:
    """The exact state a refused run-train leaves: a namespace holding one empty lock."""
    lock = _writer_lock(repo)
    lock.parent.mkdir(parents=True)
    lock.touch()
    return lock


def _assert_bootstrapped(repo: Path, result: dict) -> None:
    assert result["state"] == "ACTIVE"
    receipt = live.load_partition_receipt(live.repository_snapshot(repo).store_root)
    assert receipt is not None and receipt.zero_source
    assert live.WriterGenerationLatch.open(repo).read().generation_state == "ACTIVE"


def test_namespace_holding_only_an_empty_writer_lock_probes_and_applies(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    _residue_only(repo)

    inventory = _probe(tmp_path, repo)
    (row,) = inventory["worktrees"]
    assert row["classification"] == "empty"
    assert [item["path"] for item in row["files"]] == [live.RUN_TRAIN_WRITER_LOCK]

    _assert_bootstrapped(
        repo, live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    )


def test_non_empty_writer_lock_is_unattested(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    _residue_only(repo).write_text("{}\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="unattested canonical state"):
        _probe(tmp_path, repo)


def test_symlinked_writer_lock_refuses(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    target = tmp_path / "elsewhere.lock"
    target.touch()
    lock = _writer_lock(repo)
    lock.parent.mkdir(parents=True)
    lock.symlink_to(target)

    # The tree inventory refuses the symlink before classification; the residue
    # predicate refuses it independently.
    with pytest.raises(live.LegacyCutoverConflict, match="symlink"):
        _probe(tmp_path, repo)
    assert not live._is_run_train_lock_residue(lock)


def test_writer_lock_owned_by_another_user_is_unattested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    _residue_only(repo)
    foreign_uid = os.getuid() + 1
    monkeypatch.setattr(live.os, "getuid", lambda: foreign_uid)

    with pytest.raises(live.LegacyCutoverConflict, match="unattested canonical state"):
        _probe(tmp_path, repo)


def test_writer_lock_that_is_not_a_regular_file_is_unattested(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _writer_lock(repo)
    lock.parent.mkdir(parents=True)
    os.mkfifo(lock)

    assert not live._is_run_train_lock_residue(lock)
    with pytest.raises(live.LegacyCutoverConflict):
        _probe(tmp_path, repo)


def test_apply_refuses_while_a_run_train_holds_the_writer_lock(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _residue_only(repo)
    inventory = _probe(tmp_path, repo)

    # flock is per open file description, so a second descriptor in this
    # process contends exactly as another process's run-train would.
    with lock.open("a+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        with pytest.raises(live.LegacyCutoverConflict, match="a run-train holds the writer lock"):
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)

    assert not (tmp_path / "authority").exists()
    assert live.load_partition_receipt(live.repository_snapshot(repo).store_root) is None

    # Once the train releases it, the same sealed inventory applies.
    _assert_bootstrapped(
        repo, live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    )


def test_apply_holds_the_writer_lock_until_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _residue_only(repo)
    inventory = _probe(tmp_path, repo)
    observed: list[bool] = []
    onboard = live.onboard_zero_legacy_repository

    def probing_onboard(*args, **kwargs):
        with lock.open("a+") as contender:
            try:
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                observed.append(True)
            else:
                observed.append(False)
        return onboard(*args, **kwargs)

    monkeypatch.setattr(live, "onboard_zero_legacy_repository", probing_onboard)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)

    assert observed == [True]
    with lock.open("a+") as after:
        fcntl.flock(after, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_apply_does_not_create_an_absent_writer_lock(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)

    _assert_bootstrapped(
        repo, live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    )
    assert not _writer_lock(repo).exists()


def test_a_real_run_train_attempt_does_not_block_its_own_bootstrap(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    with fencing.run_train_generation_leases([repo]):
        assert _writer_lock(repo).exists()
    assert _writer_lock(repo).stat().st_size == 0

    inventory = _probe(tmp_path, repo)
    (row,) = inventory["worktrees"]
    assert live.RUN_TRAIN_WRITER_LOCK in {item["path"] for item in row["files"]}

    _assert_bootstrapped(
        repo, live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    )
