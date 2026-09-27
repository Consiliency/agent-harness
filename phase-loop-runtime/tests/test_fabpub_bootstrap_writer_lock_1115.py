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
import shutil
import socket
import stat
import subprocess
import sys
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

    with pytest.raises(live.LegacyCutoverConflict, match="is a regular file holding 3 bytes, not runtime writer-lock residue"):
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

    with pytest.raises(live.LegacyCutoverConflict, match="is a symlink, not runtime writer-lock residue"):
        _probe(tmp_path, repo)
    assert not live._is_run_train_lock_residue(lock)


def test_hardlinked_writer_lock_is_unattested(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _residue_only(repo)
    os.link(lock, tmp_path / "second-name.lock")

    with pytest.raises(live.LegacyCutoverConflict, match="is a regular file with 2 hard links, not runtime writer-lock residue"):
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
    real_lock_status = live._lock_status_in
    foreign_uid = os.getuid() + 1

    def foreign_lock_status(dir_fd):
        status = real_lock_status(dir_fd)
        if status is None:
            return None
        fields = list(status)
        fields[stat.ST_UID] = foreign_uid
        return os.stat_result(fields)

    # Only the lock entry is foreign; the namespace root stays the operator's.
    monkeypatch.setattr(live, "_lock_status_in", foreign_lock_status)
    with pytest.raises(
        live.LegacyCutoverConflict, match=f"is a regular file owned by uid {foreign_uid}"
    ):
        _probe(tmp_path, repo)


def test_writer_lock_that_is_not_a_regular_file_is_unattested(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _writer_lock(repo)
    lock.parent.mkdir(parents=True)
    os.mkfifo(lock)

    assert not live._is_run_train_lock_residue(lock)
    with pytest.raises(live.LegacyCutoverConflict, match="is a FIFO, not runtime writer-lock residue"):
        _probe(tmp_path, repo)


def test_empty_directory_under_the_lock_name_is_unattested_at_probe(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    _writer_lock(repo).mkdir(parents=True)

    with pytest.raises(live.LegacyCutoverConflict, match="is a directory, not runtime writer-lock residue"):
        _probe(tmp_path, repo)


def test_socket_under_the_lock_name_refuses_at_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _writer_lock(repo)
    lock.parent.mkdir(parents=True)
    monkeypatch.chdir(lock.parent)  # a relative bind keeps the socket path short
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(live.RUN_TRAIN_WRITER_LOCK)
        assert not live._is_run_train_lock_residue(lock)
        with pytest.raises(live.LegacyCutoverConflict, match="is a socket, not runtime writer-lock residue"):
            _probe(tmp_path, repo)


def test_impostor_refusal_names_the_entry_and_a_non_destructive_recovery(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    lock = _writer_lock(repo)
    lock.mkdir(parents=True)

    with pytest.raises(live.LegacyCutoverConflict) as raised:
        _probe(tmp_path, repo)
    message = str(raised.value)
    assert str(lock) in message
    assert "remove it only after confirming it is not yours" in message
    assert lock.is_dir()  # nothing was removed


def test_namespace_holds_nothing_only_for_absence_or_the_true_residue(tmp_path: Path) -> None:
    """The ``absent`` decision itself, independent of the earlier impostor refusal."""
    root = tmp_path / live.REPOSITORY_NAMESPACE_DIR
    assert live._namespace_holds_nothing(None, [])

    def holds_nothing() -> bool:
        dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return live._namespace_holds_nothing(dir_fd, [])
        finally:
            os.close(dir_fd)

    root.mkdir()
    assert holds_nothing()
    (root / live.RUN_TRAIN_WRITER_LOCK).mkdir()
    assert not holds_nothing()
    (root / live.RUN_TRAIN_WRITER_LOCK).rmdir()
    (root / live.RUN_TRAIN_WRITER_LOCK).touch()
    assert holds_nothing()
    (root / "stray").mkdir()
    assert not holds_nothing()


def test_dangling_symlink_namespace_root_is_unattested(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    live.repository_namespace_root(repo).symlink_to(tmp_path / "missing")

    with pytest.raises(live.LegacyCutoverConflict, match="is not a directory"):
        _probe(tmp_path, repo)


def test_symlink_to_a_directory_as_namespace_root_refuses(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    target = tmp_path / "real-namespace"
    target.mkdir()
    live.repository_namespace_root(repo).symlink_to(target)

    with pytest.raises(live.LegacyCutoverConflict, match="symlink"):
        _probe(tmp_path, repo)


def test_symlink_root_is_refused_even_when_its_target_holds_a_receipt(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    _assert_bootstrapped(repo, _apply(inventory))
    root = live.repository_namespace_root(repo)
    moved = tmp_path / "elsewhere" / live.REPOSITORY_NAMESPACE_DIR
    moved.parent.mkdir()
    root.rename(moved)
    root.symlink_to(moved)
    snapshot = live.repository_snapshot(repo)
    assert (snapshot.container / live.RECEIPT_FILENAME).exists()  # through the link

    with pytest.raises(live.LegacyCutoverConflict, match=r"is not a directory \(a symlink"):
        live._classify_repository_namespace(
            snapshot,
            inventory["cutover_id"],
            bootstrap_inventory_sha256=inventory["inventory_sha256"],
        )


def _swap_root_during_enumeration(
    monkeypatch: pytest.MonkeyPatch, root: Path, clean: Path, *, restore: bool
) -> list[bool]:
    """Swap the namespace root for a symlink to ``clean`` exactly while the
    ``absent`` decision enumerates it; optionally swap it back (A-B-A)."""
    swapped: list[bool] = []
    real_scandir = os.scandir
    moved = root.with_name(root.name + ".original")

    def swapping_scandir(target=None, *args, **kwargs):
        if sys._getframe(1).f_code.co_name != "_namespace_holds_nothing" or swapped:
            return real_scandir(target, *args, **kwargs) if target is not None else real_scandir()
        swapped.append(True)
        root.rename(moved)
        root.symlink_to(clean)
        try:
            entries = list(real_scandir(target, *args, **kwargs))
        finally:
            if restore:
                root.unlink()
                moved.rename(root)

        class _Listing:
            def __enter__(self):
                return iter(entries)

            def __exit__(self, *_exc):
                return False

            def __iter__(self):
                return iter(entries)

        return _Listing()

    monkeypatch.setattr(os, "scandir", swapping_scandir)
    return swapped


def test_root_swapped_for_a_symlink_during_the_probe_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    root = live.repository_namespace_root(repo)
    root.mkdir()
    clean = tmp_path / "clean"
    clean.mkdir()
    swapped = _swap_root_during_enumeration(monkeypatch, root, clean, restore=False)

    with pytest.raises(live.LegacyCutoverConflict, match="changed during the probe"):
        _probe(tmp_path, repo)
    assert swapped == [True]


def test_classification_binds_to_the_directory_it_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-B-A: the path points at a clean directory only while it is enumerated.
    The decision must describe the opened directory (which holds a stray entry),
    not whatever the path named mid-enumeration."""
    repo = _git_repo(tmp_path / "repo")
    root = live.repository_namespace_root(repo)
    (root / "stray").mkdir(parents=True)
    clean = tmp_path / "clean"
    clean.mkdir()
    swapped = _swap_root_during_enumeration(monkeypatch, root, clean, restore=True)

    (row,) = _probe(tmp_path, repo)["worktrees"]
    assert swapped == [True]
    assert row["classification"] == "empty"


def test_receipt_less_namespace_root_owned_by_another_user_is_unattested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    live.repository_namespace_root(repo).mkdir()
    foreign_uid = os.getuid() + 1
    monkeypatch.setattr(live.os, "getuid", lambda: foreign_uid)

    with pytest.raises(live.LegacyCutoverConflict, match="namespace root .* is owned by uid"):
        _probe(tmp_path, repo)


def test_namespace_root_that_is_a_file_is_unattested(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    live.repository_namespace_root(repo).write_text("", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="is not a directory"):
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


def test_apply_refuses_a_writer_lock_that_is_not_a_regular_file(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    lock = _writer_lock(repo)
    lock.parent.mkdir(parents=True)
    os.mkfifo(lock)  # opens O_RDWR|O_NONBLOCK without blocking; fstat must refuse it

    with pytest.raises(live.LegacyCutoverConflict, match="singly linked regular file"):
        _apply(inventory)
    assert not (tmp_path / "authority").exists()


def test_apply_refuses_a_writer_lock_owned_by_another_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    foreign_uid = os.getuid() + 1
    monkeypatch.setattr(live.os, "getuid", lambda: foreign_uid)

    with pytest.raises(live.LegacyCutoverConflict, match="owned by the operator"):
        _apply(inventory)
    assert not (tmp_path / "authority").exists()


def _interrupt_after_draining(inventory: dict, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Crash the first apply right after DRAINING is journaled; return the journal."""
    with monkeypatch.context() as patcher:
        patcher.setattr(
            live.WriterGenerationLatch,
            "open",
            classmethod(lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("crash"))),
        )
        with pytest.raises(RuntimeError, match="crash"):
            _apply(inventory)
    journal = Path(inventory["authority_root"]) / "bootstrap-1115.bootstrap-journal.jsonl"
    assert live._bootstrap_journal_states(journal, "bootstrap-1115") == ("DRAINING",)
    return journal


def test_resume_refuses_while_a_run_train_holds_the_writer_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    journal = _interrupt_after_draining(inventory, monkeypatch)
    journal_before = journal.read_bytes()

    with _writer_lock(repo).open("a+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        with pytest.raises(live.LegacyCutoverConflict, match="holds the writer lock"):
            _apply(inventory)

    assert journal.read_bytes() == journal_before
    assert not (Path(inventory["authority_root"]) / "ACTIVE_BOOTSTRAP").exists()
    _assert_bootstrapped(repo, _apply(inventory))


def test_first_apply_of_a_deleted_repository_names_the_re_probe_remedy(tmp_path: Path) -> None:
    main = _git_repo(tmp_path / "main")
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", "-b", "linked", str(linked)],
        check=True,
    )
    inventory = _probe(tmp_path, linked)
    shutil.rmtree(linked)
    shutil.rmtree(main)

    with pytest.raises(live.LegacyCutoverConflict) as raised:
        _apply(inventory)
    message = str(raised.value)
    assert "before its first apply" in message and "re-run the zero-history probe" in message
    assert not (tmp_path / "authority").exists()


def test_resume_of_a_deleted_repository_names_the_resume_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = _git_repo(tmp_path / "main")
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", "-b", "linked", str(linked)],
        check=True,
    )
    inventory = _probe(tmp_path, linked)
    journal = _interrupt_after_draining(inventory, monkeypatch)
    journal_before = journal.read_bytes()
    shutil.rmtree(linked)
    shutil.rmtree(main)

    with pytest.raises(live.LegacyCutoverConflict) as raised:
        _apply(inventory)
    message = str(raised.value)
    assert "re-run apply with the same inventory" in message
    assert "re-run the zero-history probe" not in message
    assert journal.read_bytes() == journal_before


def test_apply_refuses_a_repository_outside_the_namespaces_it_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    stranger = _git_repo(tmp_path / "stranger")
    inventory = _probe(tmp_path, repo)
    monkeypatch.setattr(live, "_inventory_row_repository", lambda _row: stranger)

    with pytest.raises(live.LegacyCutoverConflict, match="writer lock this apply holds"):
        _apply(inventory)
    assert not (live.repository_namespace_root(stranger) / "writer-generation.json").exists()


def test_apply_creates_nothing_under_a_sealed_root_that_is_not_a_fabpub_namespace(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    inventory["worktrees"][0]["namespace_root"] = str(elsewhere)
    inventory["inventory_sha256"] = live._inventory_digest(inventory)

    with pytest.raises(live.LegacyCutoverConflict, match="is not a phase-loop-fabpub-broker-v1"):
        _apply(inventory)
    assert list(elsewhere.iterdir()) == []


def _race_a_run_train_against(
    inventory: dict, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[str], dict]:
    """Start a real run-train entry from a thread inside apply's onboarding and
    record, by event order, whether it blocked behind apply's writer lock."""
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
    return events, result


def test_absent_lock_race_a_run_train_that_starts_during_apply_cannot_enter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock is absent when apply starts; a real run-train entry is attempted
    after apply holds its locks (inside onboarding, past ``await_quiescent``).
    It must block until apply's hold ends, never run concurrently with it."""
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    assert not _writer_lock(repo).exists()

    events, result = _race_a_run_train_against(inventory, repo, monkeypatch)

    _assert_bootstrapped(repo, result)
    assert events == ["train-blocked-during-apply", "onboarding-done", "train-entered"]


def test_resume_race_a_run_train_that_starts_during_resume_cannot_enter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    _interrupt_after_draining(inventory, monkeypatch)

    events, result = _race_a_run_train_against(inventory, repo, monkeypatch)

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
