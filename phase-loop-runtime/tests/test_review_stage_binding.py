"""Panel review seats read a staged copy, and what they read is ATTESTED.

The cross-vendor board previously staged a bundle and nothing else, so a CLI seat
could not open the code it was reviewing. It had to be handed whole source files
inlined into the bundle, which is what drives 200-340 KiB bundles against the
512 KiB transport cap (Consiliency/agent-harness#848).

`advisor_board/backing.py` already launches review legs under
`bwrap --unshare-all --clearenv` with the staged dir `--ro-bind`ed, so a staged
tree placed there reaches the seat read-only with no new isolation mechanism.
The gap these tests close is EVIDENCE: `revalidate_review_isolation_authorization`
digest-bound only `review-bundle.md` and `review-instructions.md`, so any tree in
the staged dir was unattested -- nothing recorded which bytes the seat read.

These tests are the RED lane for that binding. They assert the staged tree is
(a) a copy and never the live tree, (b) selected like a reviewer's working tree,
(c) refused when it escapes its root, and (d) bound by a digest the authorization
carries, so a post-mint swap fails closed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import review_stage


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "src.py").write_text("live tree file\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "ignored").mkdir()
    (root / "ignored" / "artifact.bin").write_text("build junk\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "src.py", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
        check=True,
    )
    return root


def test_stage_is_a_copy_and_never_the_live_tree(tmp_path):
    """The seat must never be handed a path into the reviewed working tree."""
    repo = _git_repo(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    assert staged.resolve() != repo.resolve()
    assert repo.resolve() not in staged.resolve().parents
    assert (staged / "src.py").read_text(encoding="utf-8") == "live tree file\n"

    # The stage is WRITABLE by design -- a panelist has to run tests in it. The
    # load-bearing assertion is the one that always mattered: writing the copy cannot
    # reach the reviewed tree.
    (staged / "src.py").write_text("seat scribbled\n", encoding="utf-8")
    assert (repo / "src.py").read_text(encoding="utf-8") == "live tree file\n"


def test_stage_carries_an_independent_git_and_no_ignored_paths(tmp_path):
    """`.git` is now PRESENT but independent: a panelist needs history to reason with.

    The property that always mattered is unchanged -- no link to the live object store.
    A `--shared` clone or a linked worktree would leave the sandbox resolving objects
    through the reviewed repo, at which point it is not a copy.
    """
    repo = _git_repo(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    assert (staged / ".git").is_dir(), "a real gitdir, not a worktree pointer file"
    assert not (staged / ".git" / "objects" / "info" / "alternates").exists()
    assert not (staged / "ignored" / "artifact.bin").exists()
    assert (staged / ".gitignore").is_file()


def test_stage_includes_uncommitted_work_a_reviewer_would_see(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    (repo / "src.py").write_text("uncommitted edit\n", encoding="utf-8")
    (repo / "new_untracked.py").write_text("new file\n", encoding="utf-8")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")

    assert (staged / "src.py").read_text(encoding="utf-8") == "uncommitted edit\n"
    assert (staged / "new_untracked.py").read_text(encoding="utf-8") == "new file\n"


@pytest.mark.parametrize("kind", ["absolute", "escaping"])
def test_stage_refuses_symlinks_that_leave_the_tree(tmp_path, kind):
    """Path containment is a safety floor: staging must fail closed, not copy."""
    repo = _git_repo(tmp_path / "repo")
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do not copy me\n", encoding="utf-8")

    target = str(outside) if kind == "absolute" else os.path.join("..", outside.name)
    os.symlink(target, repo / "leak")

    with pytest.raises(ValueError):
        review_stage.stage_review_tree(repo, tmp_path / "stage")


def test_manifest_digest_is_content_bound_and_creation_order_independent(tmp_path):
    """The digest must change when reviewed BYTES change, and not otherwise.

    The old name claimed order independence while only hashing the same repo twice, so
    it could not have caught an order-dependent digest (ah#890 board, fable finding 9).
    Two trees with identical content created in OPPOSITE order now pin it.
    """
    repo = _git_repo(tmp_path / "repo")

    first = review_stage.review_tree_manifest_sha256(repo)
    again = review_stage.review_tree_manifest_sha256(repo)
    assert first == again, "digest must be deterministic for identical content"

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert review_stage.review_tree_manifest_sha256(staged) == first, (
        "a faithful stage must hash identically to its source"
    )

    (repo / "src.py").write_text("changed\n", encoding="utf-8")
    assert review_stage.review_tree_manifest_sha256(repo) != first

    # Actually permute: same content, opposite creation order, must hash identically.
    forward = _git_repo(tmp_path / "forward")
    for name in ("aaa.py", "mmm.py", "zzz.py"):
        (forward / name).write_text(name, encoding="utf-8")
    backward = _git_repo(tmp_path / "backward")
    for name in ("zzz.py", "mmm.py", "aaa.py"):
        (backward / name).write_text(name, encoding="utf-8")
    for r in (forward, backward):
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    assert review_stage.review_tree_manifest_sha256(forward) == \
        review_stage.review_tree_manifest_sha256(backward)


def test_manifest_digest_detects_a_swapped_file_of_equal_length(tmp_path):
    """Length-preserving tampering must still move the digest."""
    repo = _git_repo(tmp_path / "repo")
    before = review_stage.review_tree_manifest_sha256(repo)

    original = (repo / "src.py").read_text(encoding="utf-8")
    swapped = "LIVE TREE FILE\n"
    assert len(swapped) == len(original)
    (repo / "src.py").write_text(swapped, encoding="utf-8")

    assert review_stage.review_tree_manifest_sha256(repo) != before


def test_manifest_digest_detects_a_renamed_path(tmp_path):
    """Content alone is not enough: the path set is part of what the seat read."""
    repo = _git_repo(tmp_path / "repo")
    before = review_stage.review_tree_manifest_sha256(repo)

    (repo / "src.py").rename(repo / "renamed.py")
    assert review_stage.review_tree_manifest_sha256(repo) != before


def test_a_readonly_stage_is_actually_removable(tmp_path):
    """Regression: `shutil.rmtree` cannot unlink through a 0o500 directory.

    The stage is deliberately read-only, so naive cleanup leaves it on disk and
    every board round leaks ~28 MB. `remove_review_stage` restores the mode on the
    way down; this test fails if that is ever reverted to a bare rmtree.
    """
    repo = _git_repo(tmp_path / "repo")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "deep.py").write_text("nested\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "pkg/deep.py"], check=True)

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert (staged / "pkg" / "deep.py").is_file()

    review_stage.remove_review_stage(staged)
    assert not staged.exists(), "a read-only stage must still be removable"


def test_remove_review_stage_is_quiet_on_a_missing_path(tmp_path):
    """Cleanup runs on failure paths; it must never mask the original error."""
    review_stage.remove_review_stage(tmp_path / "never-created")


def test_remove_review_stage_handles_deep_readonly_tree(tmp_path):
    staged = tmp_path / "deep-stage"
    staged.mkdir()
    directory_fd = os.open(staged, os.O_RDONLY | os.O_DIRECTORY)
    depth = 1100
    try:
        for _ in range(depth):
            os.mkdir("d", dir_fd=directory_fd)
            child_fd = os.open("d", os.O_RDONLY | os.O_DIRECTORY, dir_fd=directory_fd)
            os.fchmod(directory_fd, 0o500)
            os.close(directory_fd)
            directory_fd = child_fd
    finally:
        os.close(directory_fd)
    try:
        review_stage.remove_review_stage(staged)
        assert not staged.exists()
    finally:
        if staged.exists():
            for level in range(depth, -1, -1):
                directory = staged.joinpath(*(["d"] * level))
                if directory.exists():
                    directory.chmod(0o700)
                    if level < depth:
                        (directory / "d").rmdir()
            staged.rmdir()


def test_remove_review_stage_does_not_chmod_symlink_target(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n", encoding="utf-8")
    outside.chmod(0o500)
    staged = tmp_path / "stage"
    staged.mkdir()
    (staged / "link").symlink_to(outside, target_is_directory=True)

    review_stage.remove_review_stage(staged)

    assert not staged.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert outside.stat().st_mode & 0o777 == 0o500


def test_remove_review_stage_handles_unreadable_directory(tmp_path):
    staged = tmp_path / "stage"
    locked = staged / "locked"
    locked.mkdir(parents=True)
    (locked / "file.txt").write_text("seat residue\n", encoding="utf-8")
    locked.chmod(0o000)
    staged.chmod(0o000)

    try:
        review_stage.remove_review_stage(staged)
        assert not staged.exists()
    finally:
        if staged.exists():
            staged.chmod(0o700)
            locked.chmod(0o700)
            review_stage.remove_review_stage(staged)


def test_falsifier_cleanup_residue_is_an_error(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    entry = SimpleNamespace(
        finding_id="F001", new_test_path="phase-loop-runtime/tests/test_finding_F001.py",
        expected_nodeid="phase-loop-runtime/tests/test_finding_F001.py::test_trigger",
        diff="not a diff",
    )
    staged_paths = []
    original_stage = review_stage.stage_review_tree
    original_remove = review_stage.remove_review_stage

    def capture_stage(source):
        staged = original_stage(source)
        staged_paths.append(staged)
        return staged

    monkeypatch.setattr(review_stage, "stage_review_tree", capture_stage)
    monkeypatch.setattr(review_stage, "remove_review_stage", lambda _staged: None)
    try:
        result = falsifier.run_finding_falsifier(
            falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
            authorization=authorization, repo=repo, wall_clock_s=10,
            output_cap_bytes=65536,
        )
        assert result.outcome == "error"
        assert result.red_output_digest is None
        assert "cleanup" in (result.detail or "")
        assert staged_paths and staged_paths[0].exists()
        with pytest.raises(ValueError):
            backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)
    finally:
        for staged in staged_paths:
            original_remove(staged)


def test_deep_authenticated_report_does_not_crash_parent(tmp_path, monkeypatch):
    if not Path("/usr/bin/bwrap").is_file():
        pytest.skip("canonical falsifier launcher absent")
    original_popen = subprocess.Popen
    emitter = (
        "import hashlib,hmac,sys\n"
        "key=sys.stdin.buffer.readline().rstrip(b'\\n')\n"
        "payload=(b'{\"schema\":\"falsifier_pytest_report.v1\",\"deep\":'"
        "+b'['*1200+b'0'+b']'*1200+b'}')\n"
        "signature=hmac.new(key,payload,hashlib.sha256).hexdigest().encode()\n"
        "sys.stdout.buffer.write(b'\\nFALSIFIER_RESULT::'+sys.argv[1].encode()"
        "+b':'+signature+b':'+payload+b'\\n')\n"
    )

    def launch(_argv, *args, **kwargs):
        return original_popen(["/usr/bin/python3", "-c", emitter, _argv[-1]], *args, **kwargs)

    monkeypatch.setattr(review_stage.subprocess, "Popen", launch)
    code, _stdout, _stderr, failure, report = review_stage._run_bounded_falsifier_node(
        staged=tmp_path, dependencies=tmp_path, nodeid="test_finding_F001.py::test_trigger",
        wall_clock_s=5, output_cap_bytes=65536,
    )
    assert code == 0 and failure is None
    assert report is None


def test_falsifier_records_parent_recursion_as_error(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    source = "def test_trigger():\n    assert True\n"
    diff = (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,2 @@\n"
        "+def test_trigger():\n+    assert True\n"
    )
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff=diff,
    )
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)

    def overflow(**_kwargs):
        raise RecursionError("nested seat report")

    monkeypatch.setattr(review_stage, "run_bounded_falsifier_node", overflow)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10,
        output_cap_bytes=65536,
    )
    assert result.outcome == "error"
    assert "nested seat report" in (result.detail or "")
    assert result.red_output_digest is None
    assert not (repo / path).exists()
    with pytest.raises(ValueError):
        backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)
