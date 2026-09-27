"""agent-harness#1115: the zero-history bootstrap and the run-train writer lock.

``run_train_generation_leases`` creates and flocks an empty
``<git-common-dir>/phase-loop-fabpub-broker-v1/run-train-writer.lock`` on every
attempt, before any receipt check.  The bootstrap treats exactly that residue (an
empty, singly linked regular file the operator owns) as non-state, refuses
anything else under the name, and always holds the writer lock for the whole
apply so no run-train can run concurrently with it.

Every repository and authority root here lives under ``tmp_path``.
"""

from __future__ import annotations

import errno
import fcntl
import os
import subprocess
import threading
from pathlib import Path

import pytest

from phase_loop_runtime.convergence import fencing
from phase_loop_runtime.convergence.broker import live

# A failure guard only: every correctness decision below is event-ordered.
_GUARD_SECONDS = 30


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


def _probe(tmp_path: Path, *repos: Path) -> dict:
    return live.probe_zero_history_bootstrap(
        cutover_id="bootstrap-1115",
        authority_root=tmp_path / "authority",
        worktrees=repos,
        legacy_roots=(tmp_path / "legacy",),
        search_roots=(tmp_path,),
    )


def _apply(inventory: dict) -> dict:
    return live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)


def _writer_lock(repo: Path) -> Path:
    return live.repository_namespace_root(repo) / live.RUN_TRAIN_WRITER_LOCK


def _residue_only(repo: Path) -> Path:
    """The exact state a refused run-train leaves: a namespace holding one empty lock."""
    lock = _writer_lock(repo)
    lock.parent.mkdir(parents=True)
    lock.touch()
    return lock


def _lock_is_free(lock: Path) -> bool:
    with lock.open("a+") as contender:
        try:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def _assert_bootstrapped(repo: Path, result: dict) -> None:
    assert result["state"] == "ACTIVE"
    receipt = live.load_partition_receipt(live.repository_snapshot(repo).store_root)
    assert receipt is not None and receipt.zero_source
    assert live.WriterGenerationLatch.open(repo).read().generation_state == "ACTIVE"


def test_residue_is_not_inventory_state(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    without = _probe(tmp_path, repo)
    _residue_only(repo)
    with_residue = _probe(tmp_path, repo)

    assert with_residue == without
    assert with_residue["inventory_sha256"] == without["inventory_sha256"]
    (row,) = with_residue["worktrees"]
    assert row["classification"] == "absent" and row["files"] == []


def test_namespace_holding_only_an_empty_writer_lock_probes_and_applies(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    _residue_only(repo)

    _assert_bootstrapped(repo, _apply(_probe(tmp_path, repo)))


def test_non_empty_writer_lock_is_unattested(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    _residue_only(repo).write_text("{}\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="unattested canonical state"):
        _probe(tmp_path, repo)


def test_residue_predicate_refuses_a_non_empty_file(tmp_path: Path) -> None:
    lock = tmp_path / live.RUN_TRAIN_WRITER_LOCK
    lock.write_text("x", encoding="utf-8")

    assert not live._is_run_train_lock_residue(lock)
    lock.write_text("", encoding="utf-8")
    assert live._is_run_train_lock_residue(lock)


def test_acceptance_and_attestation_come_from_one_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row captured with content stays state even if the file is empty by the
    time the residue predicate looks (a truncate between hash and lstat)."""
    repo = _git_repo(tmp_path / "repo")
    _residue_only(repo)
    real_inventory = live._tree_file_inventory

    def captured_non_empty(root):
        return [
            {**item, "size": 3, "sha256": "0" * 64}
            if item["path"] == live.RUN_TRAIN_WRITER_LOCK
            else item
            for item in real_inventory(root)
        ]

    monkeypatch.setattr(live, "_tree_file_inventory", captured_non_empty)
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


def test_hardlinked_writer_lock_is_unattested(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _residue_only(repo)
    os.link(lock, tmp_path / "second-name.lock")

    with pytest.raises(live.LegacyCutoverConflict, match="unattested canonical state"):
        _probe(tmp_path, repo)


def test_apply_refuses_a_writer_lock_hardlinked_after_the_probe(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _residue_only(repo)
    inventory = _probe(tmp_path, repo)
    os.link(lock, tmp_path / "second-name.lock")

    with pytest.raises(live.LegacyCutoverConflict, match="singly linked regular file"):
        _apply(inventory)
    assert not (tmp_path / "authority").exists()


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
        with pytest.raises(
            live.LegacyCutoverConflict,
            match="a run-train or another bootstrap apply holds the writer lock",
        ):
            _apply(inventory)

    assert not (tmp_path / "authority").exists()
    assert live.load_partition_receipt(live.repository_snapshot(repo).store_root) is None
    _assert_bootstrapped(repo, _apply(inventory))


def test_apply_creates_an_absent_writer_lock_and_holds_it_until_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    assert not _writer_lock(repo).exists()
    held_during_onboarding: list[bool] = []
    onboard = live.onboard_zero_legacy_repository

    def probing_onboard(*args, **kwargs):
        held_during_onboarding.append(not _lock_is_free(_writer_lock(repo)))
        return onboard(*args, **kwargs)

    monkeypatch.setattr(live, "onboard_zero_legacy_repository", probing_onboard)
    _assert_bootstrapped(repo, _apply(inventory))

    assert held_during_onboarding == [True]
    assert live._is_run_train_lock_residue(_writer_lock(repo))
    assert _lock_is_free(_writer_lock(repo))


def test_apply_opens_the_writer_lock_read_write_without_following_or_truncating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    calls: list[int] = []
    real_open = os.open

    def recording_open(path, flags, *args, **kwargs):
        if Path(path).name == live.RUN_TRAIN_WRITER_LOCK:
            calls.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(live.os, "open", recording_open)
    _apply(inventory)

    (flags,) = calls
    assert flags & os.O_ACCMODE == os.O_RDWR
    assert flags & os.O_CREAT and flags & os.O_NOFOLLOW
    assert not flags & (os.O_TRUNC | os.O_EXCL)


def test_absent_lock_race_a_run_train_that_starts_during_apply_cannot_enter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock is absent when apply starts; a real run-train entry is attempted
    after apply holds its locks (inside onboarding, past ``await_quiescent``).
    It must block until apply returns, never run concurrently with it."""
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    assert not _writer_lock(repo).exists()

    decided = threading.Event()
    outcome: list[str] = []
    events: list[str] = []
    real_flock = fcntl.flock

    def observing_flock(handle, operation):
        # Fencing's blocking writer-lock acquisition: record whether it would
        # have had to wait before it actually waits.
        if operation == fcntl.LOCK_EX and str(getattr(handle, "name", "")).endswith(
            live.RUN_TRAIN_WRITER_LOCK
        ):
            try:
                real_flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                outcome.append("blocked")
                decided.set()
                return real_flock(handle, operation)
            outcome.append("acquired")
            decided.set()
            return None
        return real_flock(handle, operation)

    monkeypatch.setattr(fencing.fcntl, "flock", observing_flock)

    def train() -> None:
        with fencing.run_train_generation_leases([repo]):
            events.append("train-entered")

    worker = threading.Thread(target=train, daemon=True)
    onboard = live.onboard_zero_legacy_repository

    def racing_onboard(*args, **kwargs):
        worker.start()
        assert decided.wait(_GUARD_SECONDS), "the run-train attempt never reached the lock"
        events.append(f"train-{outcome[0]}-during-apply")
        receipt = onboard(*args, **kwargs)
        # Still inside apply's writer-lock hold.
        events.append("onboarding-done")
        return receipt

    monkeypatch.setattr(live, "onboard_zero_legacy_repository", racing_onboard)
    result = _apply(inventory)
    worker.join(_GUARD_SECONDS)

    assert not worker.is_alive()
    _assert_bootstrapped(repo, result)
    assert events == ["train-blocked-during-apply", "onboarding-done", "train-entered"]


def test_multi_repository_partial_acquisition_is_released(tmp_path: Path) -> None:
    first = _git_repo(tmp_path / "a-repo")
    second = _git_repo(tmp_path / "b-repo")
    inventory = _probe(tmp_path, first, second)
    ordered = sorted(
        (live.repository_namespace_root(repo).resolve(), repo) for repo in (first, second)
    )
    earlier, later = ordered[0][1], ordered[1][1]
    _residue_only(later)

    with _writer_lock(later).open("a+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        with pytest.raises(live.LegacyCutoverConflict, match="holds the writer lock"):
            _apply(inventory)
        # Apply took the earlier lock before refusing on the later one, and
        # released it.
        assert _writer_lock(earlier).exists()
        assert _lock_is_free(_writer_lock(earlier))

    result = _apply(inventory)
    assert result["state"] == "ACTIVE" and len(result["repositories"]) == 2


def test_writer_lock_open_error_is_typed(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    _writer_lock(repo).mkdir(parents=True)  # the name now opens as a directory

    with pytest.raises(live.LegacyCutoverConflict, match="cannot open the run-train writer lock"):
        _apply(inventory)


def test_writer_lock_flock_error_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)

    def failing_flock(handle, operation):
        raise OSError(errno.ENOLCK, os.strerror(errno.ENOLCK))

    monkeypatch.setattr(fcntl, "flock", failing_flock)
    with pytest.raises(live.LegacyCutoverConflict, match="cannot lock the run-train writer lock"):
        _apply(inventory)


def test_a_real_run_train_attempt_does_not_block_its_own_bootstrap(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    with fencing.run_train_generation_leases([repo]):
        assert _writer_lock(repo).exists()
    assert _writer_lock(repo).stat().st_size == 0

    inventory = _probe(tmp_path, repo)
    (row,) = inventory["worktrees"]
    assert live.RUN_TRAIN_WRITER_LOCK not in {item["path"] for item in row["files"]}

    _assert_bootstrapped(repo, _apply(inventory))
