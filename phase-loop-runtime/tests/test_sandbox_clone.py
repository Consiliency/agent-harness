"""The sandbox is a writable, independent git clone -- not a file copy, not a worktree.

A panelist that can only read a flat copy cannot run `git log`, `git blame` or `git diff`,
which are the cheapest ways to answer "when did this change and why". Measured on this repo,
a depth-50 clone costs 34 MB total (14 MB of it `.git`) against 111 MB for full history,
and reaches 634 commits -- roughly four months. Against a ~150-250 MB used sandbox that is
close to free.

Three properties have to hold together, and each has a way of failing quietly:

* **Independent.** Never `--shared` and never a linked worktree: both leave the sandbox
  resolving objects through the LIVE gitdir, so the reviewed tree stops being a copy.
* **Writable.** `pytest` writes `__pycache__` before it does anything, so a read-only tree
  cannot host a test run. An earlier version hardened the stage to 0o500 and thereby made
  it useless for the one job it exists to do.
* **Faithful.** The sandbox must show what the reviewer is being shown. A bare clone shows
  the last COMMIT, so uncommitted work in the source would silently vanish from the copy.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


from phase_loop_runtime import review_stage


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    return root


def _commit(root: Path, message: str = "c") -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", message],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _seeded(root: Path) -> Path:
    _repo(root)
    (root / "src.py").write_text("first\n", encoding="utf-8")
    _commit(root, "first")
    (root / "src.py").write_text("second\n", encoding="utf-8")
    _commit(root, "second")
    return root


def test_the_sandbox_has_usable_git_history(tmp_path):
    """`log` and `blame` are the point of cloning rather than copying."""
    repo = _seeded(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    assert (staged / ".git").exists(), "a panelist needs git, not a flat copy"
    log = subprocess.run(
        ["git", "-C", str(staged), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "second" in log and "first" in log

    blame = subprocess.run(
        ["git", "-C", str(staged), "blame", "--porcelain", "src.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert blame.strip(), "blame must work inside the sandbox"


def test_the_clone_is_independent_of_the_live_gitdir(tmp_path):
    """Never `--shared`: alternates would resolve objects through the live repo."""
    repo = _seeded(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    alternates = staged / ".git" / "objects" / "info" / "alternates"
    assert not alternates.exists(), "an alternates file points at another object store"

    # A linked worktree keeps `.git` as a FILE pointing into the parent gitdir.
    assert (staged / ".git").is_dir(), ".git must be a real directory, not a worktree pointer"

    # Deleting the source must not break the sandbox.
    import shutil
    shutil.rmtree(repo)
    out = subprocess.run(
        ["git", "-C", str(staged), "log", "--oneline"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, "the sandbox must survive the source disappearing"


def test_the_sandbox_is_writable_so_a_test_can_actually_run(tmp_path):
    """The whole point: a panelist forms a hypothesis and RUNS it."""
    repo = _seeded(tmp_path / "repo")
    (repo / "test_thing.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    _commit(repo, "add test")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    # Writing must simply work -- no chmod dance, no PermissionError.
    (staged / "scratch.txt").write_text("panelist note\n", encoding="utf-8")
    (staged / "src.py").write_text("panelist experiment\n", encoding="utf-8")

    run = subprocess.run(
        ["python3", "-m", "pytest", "test_thing.py", "-q", "-p", "no:randomly"],
        cwd=staged, capture_output=True, text=True,
    )
    assert run.returncode == 0, f"a test must run inside the sandbox:\n{run.stdout}\n{run.stderr}"
    assert (staged / "__pycache__").exists() or ".pytest_cache" in os.listdir(staged), (
        "pytest writes caches; a read-only tree cannot host a run"
    )


def test_the_reviewed_tree_is_untouched_by_anything_the_panelist_does(tmp_path):
    """The sandbox protects the tree; that is the whole trust model."""
    repo = _seeded(tmp_path / "repo")
    before = review_stage.review_tree_manifest_sha256(repo)

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    (staged / "src.py").write_text("clobbered\n", encoding="utf-8")
    (staged / "new_file.py").write_text("added\n", encoding="utf-8")
    subprocess.run(["rm", "-rf", str(staged / ".git")], check=True)

    assert review_stage.review_tree_manifest_sha256(repo) == before
    assert (repo / "src.py").read_text(encoding="utf-8") == "second\n"


def test_uncommitted_work_reaches_the_sandbox(tmp_path):
    """A bare clone shows the last COMMIT; the reviewer is shown the working tree.

    If these diverge, a panelist reviews code nobody is proposing -- confidently, with
    citations. The stage must reflect what is actually under review.
    """
    repo = _seeded(tmp_path / "repo")
    (repo / "src.py").write_text("uncommitted edit\n", encoding="utf-8")
    (repo / "brand_new.py").write_text("untracked but not ignored\n", encoding="utf-8")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    assert (staged / "src.py").read_text(encoding="utf-8") == "uncommitted edit\n"
    assert (staged / "brand_new.py").read_text(encoding="utf-8") == "untracked but not ignored\n"


def test_ignored_paths_still_do_not_reach_the_sandbox(tmp_path):
    repo = _seeded(tmp_path / "repo")
    (repo / ".gitignore").write_text("secrets/\n", encoding="utf-8")
    (repo / "secrets").mkdir()
    (repo / "secrets" / "key.txt").write_text("do not copy\n", encoding="utf-8")
    _commit(repo, "ignore secrets")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert not (staged / "secrets" / "key.txt").exists()


def test_a_deleted_tracked_file_is_absent_from_the_sandbox(tmp_path):
    """The working tree is the truth, including deletions not yet staged."""
    repo = _seeded(tmp_path / "repo")
    (repo / "doomed.py").write_text("bye\n", encoding="utf-8")
    _commit(repo, "add doomed")
    (repo / "doomed.py").unlink()

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert not (staged / "doomed.py").exists(), "a file deleted in the source must not reappear"


def test_the_source_commit_is_recorded_for_staleness_detection(tmp_path):
    """Resuming an idle sandbox has to know whether the branch moved underneath it."""
    repo = _seeded(tmp_path / "repo")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert review_stage.staged_source_commit(staged) == head


def test_a_stale_sandbox_is_detected_when_the_branch_moves(tmp_path):
    repo = _seeded(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert not review_stage.is_stale(staged, repo)

    (repo / "src.py").write_text("moved on\n", encoding="utf-8")
    _commit(repo, "third")
    assert review_stage.is_stale(staged, repo), (
        "a panelist resumed against vanished code reports confident, cited, wrong findings"
    )


class TestStagingNeverWritesOutsideTheClone:
    """Board round 5, codex, BLOCKING — reproduced before the fix, outside sentinel clobbered.

    The clone recreates what the COMMIT held. So a committed symlink pointing outside the
    repo is sitting at the destination even when the working tree has since replaced it
    with a regular file. `_refuse_escaping_symlinks` inspects the SOURCE, where the symlink
    no longer exists, so it accepts -- and `shutil.copy2` follows the destination link and
    overwrites the victim with the parent process's permissions.

    Measured before the fix:

        before staging: victim = 'PRECIOUS ORIGINAL CONTENT'
        after  staging: victim = 'ATTACKER PAYLOAD'

    This fires during STAGING, before a reviewer acts at all, so it is not covered by any
    reasoning about what a sandboxed seat can reach. The sentinel lives OUTSIDE the repo,
    because a sentinel inside it would be staged and prove nothing.
    """

    def _victim_and_repo(self, tmp_path):
        victim = tmp_path / "VICTIM.txt"
        victim.write_text("PRECIOUS ORIGINAL CONTENT\n", encoding="utf-8")
        repo = _repo(tmp_path / "repo")
        return victim, repo

    def test_a_committed_symlink_replaced_by_a_regular_file_cannot_clobber_its_target(
        self, tmp_path,
    ):
        victim, repo = self._victim_and_repo(tmp_path)

        link = repo / "innocent.txt"
        link.symlink_to(victim)
        _commit(repo, "commit the symlink")

        link.unlink()
        link.write_text("ATTACKER PAYLOAD\n", encoding="utf-8")

        try:
            staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
        except Exception:
            # Refusing is also a correct outcome; what must never happen is the write.
            staged = None

        assert victim.read_text(encoding="utf-8") == "PRECIOUS ORIGINAL CONTENT\n", (
            "staging wrote OUTSIDE the clone"
        )
        if staged is not None:
            assert (staged / "innocent.txt").read_text(encoding="utf-8") == "ATTACKER PAYLOAD\n", (
                "the reviewer must still see the working tree's regular file"
            )
            assert not (staged / "innocent.txt").is_symlink()

    def test_the_content_shortcircuit_does_not_read_through_the_link(self, tmp_path):
        """`is_file()` follows symlinks, so the skip-if-identical check could compare the
        VICTIM's bytes and silently leave a link where a file belongs."""
        victim, repo = self._victim_and_repo(tmp_path)

        link = repo / "innocent.txt"
        link.symlink_to(victim)
        _commit(repo, "commit the symlink")

        link.unlink()
        # Byte-identical to the victim: the short-circuit would `continue` and keep a
        # symlink pointing out of the sandbox as if the file had been staged.
        link.write_text("PRECIOUS ORIGINAL CONTENT\n", encoding="utf-8")

        staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

        assert not (staged / "innocent.txt").is_symlink(), (
            "a link OUT of the sandbox survived staging as the reviewed file"
        )
        assert victim.read_text(encoding="utf-8") == "PRECIOUS ORIGINAL CONTENT\n"

    def test_a_symlink_to_a_directory_outside_is_replaced_not_followed(self, tmp_path):
        outside = tmp_path / "outside_dir"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep me\n", encoding="utf-8")
        repo = _repo(tmp_path / "repo")

        link = repo / "docs"
        link.symlink_to(outside, target_is_directory=True)
        _commit(repo, "commit a dir symlink")

        link.unlink()
        link.mkdir()
        (link / "keep.txt").write_text("staged content\n", encoding="utf-8")

        try:
            review_stage.stage_review_tree(repo, tmp_path / "stage")
        except Exception:
            pass

        assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep me\n", (
            "staging wrote through a directory symlink"
        )


class TestAnAncestorSymlinkCannotCarryAWriteOutside:
    """Board round 8, codex, BLOCKING — the round-7 fix covered only the LEAF.

    Reproduced before fixing, with a TAB in a committed directory symlink's name:

        committed as: "docs\\there"
        before: 'PRECIOUS ORIGINAL CONTENT'
        after : 'ATTACKER PAYLOAD'

    Two compounding causes. `git ls-files` QUOTES any name containing a tab or newline,
    while the source side used `ls-files -z`, so the clone set and the source set spelled
    the same path differently and stale removal never matched the real entry. And the
    escape sat at an ANCESTOR: `mkdir(parents=True, exist_ok=True)` accepts a symlink to an
    existing directory, and the leaf `is_symlink()` check sees an ordinary filename.

    The fix is containment on the RESOLVED parent rather than another shape check -- it
    covers every spelling and every depth, which is what two rounds of special cases did
    not.
    """

    def _outside_victim(self, tmp_path):
        outside = tmp_path / "OUTSIDE"
        outside.mkdir()
        victim = outside / "victim.txt"
        victim.write_text("PRECIOUS ORIGINAL CONTENT\n", encoding="utf-8")
        return outside, victim

    def test_a_tabbed_directory_symlink_cannot_be_written_through(self, tmp_path):
        outside, victim = self._outside_victim(tmp_path)
        repo = _repo(tmp_path / "repo")

        link = repo / "docs\there"
        link.symlink_to(outside, target_is_directory=True)
        _commit(repo, "commit a tabbed dir symlink")

        link.unlink()
        link.mkdir()
        (link / "victim.txt").write_text("ATTACKER PAYLOAD\n", encoding="utf-8")

        try:
            review_stage.stage_review_tree(repo, tmp_path / "stage")
        except Exception:
            pass   # refusing is a correct outcome; writing outside is not

        assert victim.read_text(encoding="utf-8") == "PRECIOUS ORIGINAL CONTENT\n", (
            "staging wrote outside the clone through an ANCESTOR symlink"
        )

    def test_a_plain_directory_symlink_cannot_be_written_through_either(self, tmp_path):
        """The same escape without the quoting trick, so the containment check is not
        mistaken for a quoting fix."""
        outside, victim = self._outside_victim(tmp_path)
        repo = _repo(tmp_path / "repo")

        link = repo / "docs"
        link.symlink_to(outside, target_is_directory=True)
        _commit(repo, "commit a dir symlink")

        link.unlink()
        link.mkdir()
        (link / "victim.txt").write_text("ATTACKER PAYLOAD\n", encoding="utf-8")

        try:
            review_stage.stage_review_tree(repo, tmp_path / "stage")
        except Exception:
            pass

        assert victim.read_text(encoding="utf-8") == "PRECIOUS ORIGINAL CONTENT\n"

    def test_ordinary_nested_files_still_stage(self, tmp_path):
        """The falsifier: containment must not refuse legitimate nested paths."""
        repo = _repo(tmp_path / "repo")
        nested = repo / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (nested / "deep.py").write_text("x = 1\n", encoding="utf-8")
        _commit(repo, "nested")

        staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
        assert (staged / "a" / "b" / "c" / "deep.py").read_text(encoding="utf-8") == "x = 1\n"


class TestTheContainmentCheckHasItsOwnFalsifier:
    """Board round 9: the resolved-parent check NEVER FIRED in 61 tests.

    Removing it left 177 green, because the `-z` quoting fix covers the same escape from
    the other side. Two fixes covering each other means neither is individually falsified,
    and the payload had called this one "the load-bearing change" — by execution it was the
    redundant half. A later refactor of the stale-removal loop would have silently rested
    the whole property on an unexercised branch.

    So this drives `_overlay_working_tree` DIRECTLY against a clone that already contains a
    directory symlink pointing outside — the state the quoting fix is what normally
    prevents. No git, no clone, nothing else able to catch it.
    """

    def test_the_check_refuses_a_destination_that_resolves_outside(self, tmp_path):
        outside = tmp_path / "OUTSIDE"
        outside.mkdir()
        victim = outside / "victim.txt"
        victim.write_text("PRECIOUS ORIGINAL CONTENT\n", encoding="utf-8")

        repo = _repo(tmp_path / "repo")
        (repo / "docs").mkdir()
        (repo / "docs" / "victim.txt").write_text("ATTACKER PAYLOAD\n", encoding="utf-8")
        _commit(repo, "a real docs dir in the source")

        # The clone already holds a directory symlink out of the tree. Reached normally
        # via a committed symlink the stale-removal loop failed to match; planted here so
        # the containment check is the ONLY thing standing between it and the victim.
        staged = tmp_path / "stage"
        staged.mkdir()
        (staged / "docs").symlink_to(outside, target_is_directory=True)

        try:
            review_stage._overlay_working_tree(repo, staged)
        except Exception:
            pass   # refusing is correct; writing outside is not

        assert victim.read_text(encoding="utf-8") == "PRECIOUS ORIGINAL CONTENT\n", (
            "the containment check did not stop a write through a planted ancestor symlink"
        )

    def test_it_refuses_rather_than_silently_skipping(self, tmp_path):
        """A silent skip would leave the reviewer a tree missing files, with no signal."""
        outside = tmp_path / "OUTSIDE"
        outside.mkdir()
        (outside / "victim.txt").write_text("keep\n", encoding="utf-8")

        repo = _repo(tmp_path / "repo")
        (repo / "docs").mkdir()
        (repo / "docs" / "victim.txt").write_text("payload\n", encoding="utf-8")
        _commit(repo, "c")

        staged = tmp_path / "stage"
        staged.mkdir()
        (staged / "docs").symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match="resolves outside the sandbox"):
            review_stage._overlay_working_tree(repo, staged)

    def test_ordinary_nested_paths_are_unaffected(self, tmp_path):
        """The falsifier: containment must not refuse legitimate nesting."""
        repo = _repo(tmp_path / "repo")
        (repo / "a" / "b").mkdir(parents=True)
        (repo / "a" / "b" / "deep.py").write_text("x = 1\n", encoding="utf-8")
        _commit(repo, "nested")

        staged = tmp_path / "stage"
        staged.mkdir()
        review_stage._overlay_working_tree(repo, staged)
        assert (staged / "a" / "b" / "deep.py").read_text(encoding="utf-8") == "x = 1\n"


class TestTheStageIsFaithfulToTheWorkingTree:
    """Board round 11, codex: two shapes where an HONEST tree failed its own validation.

    Both are the sandbox refusing a legitimate review of legitimate uncommitted work —
    the thing the stage exists to show. Neither is a security defect; both make the
    feature unusable for the case it was built for.
    """

    def test_a_committed_directory_replaced_by_a_file_stages_as_a_file(self, tmp_path):
        """Stale removal unlinked files and left their DIRECTORIES standing.

        `slot/old.txt` committed, `slot` now a regular file: the empty `slot/` survived
        and `copy2` wrote `slot/slot`. Measured before the fix — source and staged digests
        differed, so `_default_spawn` refused the review.
        """
        import shutil

        repo = _repo(tmp_path / "repo")
        (repo / "slot").mkdir()
        (repo / "slot" / "old.txt").write_text("old\n", encoding="utf-8")
        _commit(repo, "committed a directory")

        shutil.rmtree(repo / "slot")
        (repo / "slot").write_text("now a file\n", encoding="utf-8")

        source_digest = review_stage.review_tree_manifest_sha256(repo)
        staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

        assert (staged / "slot").is_file(), "the type transition did not reach the stage"
        assert not (staged / "slot" / "slot").exists() if (staged / "slot").is_dir() else True
        assert review_stage.review_tree_manifest_sha256(staged) == source_digest, (
            "the staged tree diverged from its source; the leg would refuse its own copy"
        )

    def test_a_force_added_ignored_file_survives_revalidation(self, tmp_path):
        """The stage is enumerated from the FILESYSTEM, not from the clone's index.

        `_selected_paths` used git selection on both sides. That was right when a stage
        was a file copy with no `.git`; once it became a CLONE, the clone's index
        described the COMMIT — so a file force-added but not committed reached the stage
        correctly and was then dropped from the stage-side digest alone.
        """
        import subprocess

        repo = _repo(tmp_path / "repo")
        (repo / ".gitignore").write_text("generated.py\n", encoding="utf-8")
        (repo / "a.py").write_text("x\n", encoding="utf-8")
        _commit(repo, "ignore generated.py")

        (repo / "generated.py").write_text("GENERATED CONTENT\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-f", "generated.py"], check=True)

        source_digest = review_stage.review_tree_manifest_sha256(repo)
        staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

        assert (staged / "generated.py").read_text(encoding="utf-8") == "GENERATED CONTENT\n"
        assert review_stage.review_tree_manifest_sha256(staged) == source_digest, (
            "a faithful copy was rejected because the two sides selected differently"
        )

    def test_an_ordinary_ignored_file_still_does_not_reach_the_stage(self, tmp_path):
        """The falsifier: switching the stage to a filesystem walk must not smuggle in
        genuinely ignored files, which was the point of git selection."""
        repo = _repo(tmp_path / "repo")
        (repo / ".gitignore").write_text("secrets/\n", encoding="utf-8")
        (repo / "secrets").mkdir()
        (repo / "secrets" / "key.txt").write_text("do not copy\n", encoding="utf-8")
        _commit(repo, "ignore secrets")

        staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
        assert not (staged / "secrets" / "key.txt").exists()
