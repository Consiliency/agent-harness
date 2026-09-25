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
import sys
import tempfile
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


def _replaced_source_repo(root: Path) -> tuple[Path, str]:
    repo = _git_repo(root)
    reviewed = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    (repo / "src.py").write_text("substituted bytes\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "src.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "replacement"],
        check=True,
    )
    replacement = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(repo), "replace", reviewed, replacement], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "--quiet", "--detach", reviewed], check=True)
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"]).strip() == b""
    return repo, reviewed


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


def test_stage_clone_does_not_run_host_git_filter(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    (repo / ".gitattributes").write_text("src.py filter=probe\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitattributes"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "attributes"],
        check=True,
    )
    marker = tmp_path / "host-filter-ran"
    config = tmp_path / "global.gitconfig"
    config.write_text(
        f'[filter "probe"]\n smudge = touch {marker}; cat\n required = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert (staged / "src.py").is_file()
    assert not marker.exists()


def test_stage_clone_does_not_run_tracked_git_hook(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    marker = tmp_path / "host-hook-ran"
    hook = repo / ".githooks" / "post-checkout"
    hook.parent.mkdir()
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    subprocess.run(["git", "-C", str(repo), "add", ".githooks/post-checkout"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "hook"],
        check=True,
    )
    config = tmp_path / "global.gitconfig"
    config.write_text('[core]\n hooksPath = .githooks\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert (staged / "src.py").is_file()
    assert not marker.exists()


def test_stage_path_selection_does_not_run_host_fsmonitor(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    marker = tmp_path / "host-fsmonitor-ran"
    hook = tmp_path / "fsmonitor"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    config = tmp_path / "global.gitconfig"
    config.write_text(f"[core]\n fsmonitor = {hook}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

    assert "src.py" in review_stage.review_tree_paths(repo)
    assert not marker.exists()


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


def test_remove_review_stage_walk_is_linear_in_depth(tmp_path, monkeypatch):
    staged = tmp_path / "linear-stage"
    staged.mkdir()
    depth = 160
    directory_fd = os.open(staged, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for _ in range(depth):
            os.mkdir("d", dir_fd=directory_fd)
            child_fd = os.open("d", os.O_RDONLY | os.O_DIRECTORY, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
    finally:
        os.close(directory_fd)
    original_open = os.open
    opens = 0

    def counted_open(*args, **kwargs):
        nonlocal opens
        opens += 1
        return original_open(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(review_stage.os, "open", counted_open)
        patch.setattr(review_stage.os, "supports_dir_fd", os.supports_dir_fd | {counted_open})
        review_stage.remove_review_stage(staged)
    assert not staged.exists()
    assert opens < 5 * depth, f"cleanup opened {opens} directories at depth {depth}"


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
        "+b'['*10000+b'0'+b']'*10000+b'}')\n"
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


def test_falsifier_expired_authorization_records_error_and_closes(tmp_path, monkeypatch):
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
    original_revalidate = backing.revalidate_falsifier_isolation_authorization
    monkeypatch.setattr(
        backing, "revalidate_falsifier_isolation_authorization",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("lease expired")),
    )
    try:
        result = falsifier.run_finding_falsifier(
            falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
            authorization=authorization, repo=repo, wall_clock_s=10,
            output_cap_bytes=65536,
        )
        assert result.outcome == "error"
        assert result.record["outcome"] == "error"
        assert "lease expired" in (result.detail or "")
        monkeypatch.setattr(backing, "revalidate_falsifier_isolation_authorization", original_revalidate)
        with pytest.raises(ValueError):
            backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)
    finally:
        monkeypatch.setattr(backing, "revalidate_falsifier_isolation_authorization", original_revalidate)
        backing.close_falsifier_isolation_authorization(authorization)


def test_forged_falsifier_authorization_raises_before_record(tmp_path):
    from dataclasses import replace
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
    forged = replace(authorization, _seal=object())
    try:
        with pytest.raises(ValueError, match="forged"):
            falsifier.run_finding_falsifier(
                falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
                authorization=forged, repo=repo, wall_clock_s=10,
                output_cap_bytes=65536,
            )
        backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)
    finally:
        backing.close_falsifier_isolation_authorization(authorization)


def test_project_without_declared_dependencies_keeps_pytest_available(tmp_path):
    stage = tmp_path / "stage"
    (stage / "phase-loop-runtime").mkdir(parents=True)
    (stage / "phase-loop-runtime" / "pyproject.toml").write_text(
        '[project]\nname = "empty-dependencies"\n', encoding="utf-8",
    )
    dependencies = tmp_path / "dependencies"
    review_stage._snapshot_falsifier_dependencies(stage, dependencies)
    assert (dependencies / "pytest" / "__init__.py").is_file()


@pytest.mark.parametrize("project_value", ['"not-a-table"', "[]"])
def test_malformed_project_metadata_returns_falsifier_error_receipt(tmp_path, project_value):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    runtime = repo / "phase-loop-runtime"
    runtime.mkdir()
    (runtime / "pyproject.toml").write_text(
        f"project = {project_value}\n", encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "phase-loop-runtime/pyproject.toml"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "metadata"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger",
        diff=(f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
              f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n"
              "+def test_trigger(): pass\n"),
    )
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10,
        output_cap_bytes=65536,
    )
    assert result.outcome == "error"
    assert result.record["outcome"] == "error"
    assert "project metadata" in (result.detail or "")
    with pytest.raises(ValueError):
        backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)


@pytest.mark.parametrize("kind", ["leaf", "parent"])
def test_falsifier_inventory_refuses_project_symlink_outside_stage(tmp_path, kind):
    outside = tmp_path / "outside"
    outside.mkdir()
    project = outside / "pyproject.toml"
    project.write_text('[project]\nname = "outside"\n', encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()
    if kind == "leaf":
        runtime = stage / "phase-loop-runtime"
        runtime.mkdir()
        (runtime / "pyproject.toml").symlink_to(project)
    else:
        (stage / "phase-loop-runtime").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside staged tree"):
        review_stage._snapshot_falsifier_dependencies(stage, tmp_path / "dependencies")


def test_falsifier_new_test_does_not_run_host_git_filter(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    (repo / ".gitattributes").write_text(f"{path} filter=probe\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitattributes"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "attributes"],
        check=True,
    )
    marker = tmp_path / "host-filter-ran"
    config = tmp_path / "global.gitconfig"
    config.write_text(
        f'[filter "probe"]\n smudge = touch {marker}; cat\n required = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    diff = (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+def test_trigger(): pass\n"
    )
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff=diff,
    )
    seen = []

    def capture_test(*, staged, **_kwargs):
        seen.append((staged / path).read_text(encoding="utf-8"))
        return 1, b"", b"", "probe stop", None

    monkeypatch.setattr(review_stage, "run_bounded_falsifier_node", capture_test)
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10, output_cap_bytes=65536,
    )
    assert result.outcome == "error"
    assert not marker.exists()
    assert seen == ["def test_trigger(): pass\n"]


def test_falsifier_stage_overlay_does_not_run_host_fsmonitor(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    marker = tmp_path / "host-fsmonitor-ran"
    hook = repo / ".githooks" / "fsmonitor"
    hook.parent.mkdir()
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    subprocess.run(["git", "-C", str(repo), "add", ".githooks/fsmonitor"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "fsmonitor"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    config = tmp_path / "global.gitconfig"
    config.write_text('[core]\n fsmonitor = .githooks/fsmonitor\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    diff = (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+def test_trigger(): pass\n"
    )
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff=diff,
    )
    seen = []

    def capture_test(*, staged, **_kwargs):
        seen.append((staged / path).read_text(encoding="utf-8"))
        return 1, b"", b"", "probe stop", None

    monkeypatch.setattr(review_stage, "run_bounded_falsifier_node", capture_test)
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10, output_cap_bytes=65536,
    )
    assert result.outcome == "error"
    assert not marker.exists()
    assert seen == ["def test_trigger(): pass\n"]


def test_falsifier_source_check_does_not_run_host_git_filter(tmp_path, monkeypatch):
    from phase_loop_runtime import falsifier

    repo = _git_repo(tmp_path / "repo")
    (repo / ".gitattributes").write_text("src.py filter=probe\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitattributes"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "attributes"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    marker = tmp_path / "host-filter-ran"
    config = tmp_path / "global.gitconfig"
    config.write_text(
        f'[filter "probe"]\n clean = touch {marker}; cat\n required = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    (repo / "src.py").write_text("live tree file\n", encoding="utf-8")

    falsifier._clean_exact_source(repo, head)
    assert not marker.exists()


def test_falsifier_source_check_does_not_run_host_fsmonitor(tmp_path, monkeypatch):
    from phase_loop_runtime import falsifier

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    marker = tmp_path / "host-fsmonitor-ran"
    hook = tmp_path / "fsmonitor"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    config = tmp_path / "global.gitconfig"
    config.write_text(f"[core]\n fsmonitor = {hook}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

    falsifier._clean_exact_source(repo, head)
    assert not marker.exists()


@pytest.mark.parametrize("target_minor_delta", [0, 1])
def test_inventory_uses_invoking_install_when_system_python_lacks_pytest(
    tmp_path, monkeypatch, target_minor_delta,
):
    prefix = tmp_path / "toolcache"
    site = prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    package = site / "pytest"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# installed pytest\n", encoding="utf-8")
    (package / "native.so").write_bytes(b"native extension")
    metadata = site / "pytest-9.1.1.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: pytest\nVersion: 9.1.1\n", encoding="utf-8")
    (metadata / "RECORD").write_text(
        "pytest/__init__.py,,\npytest/native.so,,\n", encoding="utf-8",
    )
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "path", [str(site), *sys.path])
    original_run = subprocess.run

    def empty_system_inventory(argv, *args, **kwargs):
        if argv[0] == "/usr/bin/python3" and "-c" in argv:
            version = f"{sys.version_info.major},{sys.version_info.minor + target_minor_delta},0"
            return subprocess.CompletedProcess(
                argv, 0, stdout=f'{{"paths":[],"version":[{version}]}}', stderr="",
            )
        return original_run(argv, *args, **kwargs)

    monkeypatch.setattr(review_stage.subprocess, "run", empty_system_inventory)
    stage = tmp_path / "stage"
    stage.mkdir()
    dependencies = tmp_path / "dependencies"
    review_stage._snapshot_falsifier_dependencies(stage, dependencies)

    assert (dependencies / "pytest" / "__init__.py").read_text() == "# installed pytest\n"
    assert (dependencies / "pytest" / "native.so").exists() is (target_minor_delta == 0)


def test_falsifier_inventory_does_not_run_editable_usercustomize(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    marker = tmp_path / "host-marker"
    source = repo / "src"
    source.mkdir()
    (source / "usercustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "src/usercustomize.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "customize"],
        check=True,
    )
    home = tmp_path / "home"
    site = home / ".local" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    site.mkdir(parents=True)
    (site / "editable.pth").write_text(
        f"{source}\nimport usercustomize\n", encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(repo)
    stage = review_stage.stage_review_tree(repo, tmp_path / "stage")

    review_stage._snapshot_falsifier_dependencies(stage, tmp_path / "dependencies")

    assert not marker.exists()


def test_falsifier_inventory_does_not_import_reviewed_json_from_cwd(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    marker = tmp_path / "host-marker"
    (repo / "json.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "json.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "shadow"],
        check=True,
    )
    stage = review_stage.stage_review_tree(repo, tmp_path / "stage")
    monkeypatch.chdir(repo)

    review_stage._snapshot_falsifier_dependencies(stage, tmp_path / "dependencies")

    assert not marker.exists()


def test_empty_reason_xpass_is_not_recorded_as_green(tmp_path):
    if not Path("/usr/bin/bwrap").is_file():
        pytest.skip("canonical falsifier launcher absent")
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    source = (
        "import pytest\n"
        '@pytest.mark.xfail(reason="")\n'
        "def test_trigger():\n"
        "    assert True\n"
    )
    diff = (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,4 @@\n"
        + "".join(f"+{line}\n" for line in source.splitlines())
    )
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff=diff,
    )
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=30,
        output_cap_bytes=65536,
    )
    assert result.outcome == "error", result.detail
    assert result.red_output_digest is None


@pytest.mark.parametrize("source, expected", [
    ("import definitely_missing_execfind_module\ndef test_trigger():\n    assert True\n", "error"),
    ("def test_other():\n    assert False\n", "node_missing"),
])
def test_falsifier_distinguishes_collection_failure_from_missing_node(tmp_path, source, expected):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    lines = source.splitlines()
    diff = (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
        + "".join(f"+{line}\n" for line in lines)
    )
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff=diff,
    )
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=30,
        output_cap_bytes=65536,
    )
    assert result.outcome == result.record["outcome"] == expected
    assert result.red_output_digest is None
    assert backing._falsifier_authorization_lease(authorization).closed


@pytest.mark.parametrize("source, selector", [
    (
        "class TestGroup:\n"
        "    def test_a(self):\n        print('EXECUTED_A')\n"
        "    def test_b(self):\n        print('EXECUTED_B')\n",
        "TestGroup",
    ),
    (
        "import pytest\n"
        "@pytest.mark.parametrize('case', [1, 2])\n"
        "def test_cases(case):\n    print('EXECUTED_CASE')\n",
        "test_cases",
    ),
])
def test_falsifier_rejects_selector_expansion_before_call(tmp_path, source, selector):
    from phase_loop_runtime import falsifier

    stage = tmp_path / "stage"
    tests = stage / "phase-loop-runtime" / "tests"
    tests.mkdir(parents=True)
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    (stage / path).write_text(source, encoding="utf-8")
    nodeid = f"{path}::{selector}"

    returncode, stdout, _stderr, failure, report = review_stage.run_bounded_falsifier_node(
        staged=stage, nodeid=nodeid, wall_clock_s=30, output_cap_bytes=65536,
    )

    assert failure is None
    assert report is not None
    assert report["calls"] == []
    assert b"EXECUTED_" not in stdout
    assert falsifier._outcome_from_report(report, nodeid, returncode) == "error"


@pytest.mark.parametrize("conftest_source", [
    "import definitely_missing_execfind_conftest_dependency\n",
    (
        "import pytest\n"
        "def pytest_configure(config):\n"
        "    raise pytest.UsageError('startup configuration failed')\n"
    ),
    (
        "import pytest\n"
        "class BrokenCollection:\n"
        "    def pytest_collectstart(self, collector):\n"
        "        raise pytest.UsageError('collection startup failed')\n"
        "def pytest_configure(config):\n"
        "    config.pluginmanager.register(BrokenCollection())\n"
    ),
    (
        "import pytest\n"
        "def pytest_collection_modifyitems(session, config, items):\n"
        "    items.clear()\n"
        "    raise pytest.UsageError('collection selection failed')\n"
    ),
])
def test_falsifier_startup_failure_is_not_node_missing(tmp_path, conftest_source):
    from phase_loop_runtime import falsifier

    stage = tmp_path / "stage"
    tests = stage / "phase-loop-runtime" / "tests"
    tests.mkdir(parents=True)
    (tests / "conftest.py").write_text(conftest_source, encoding="utf-8")
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    (stage / path).write_text("def test_trigger():\n    assert True\n", encoding="utf-8")
    nodeid = f"{path}::test_trigger"

    returncode, _stdout, _stderr, failure, report = review_stage.run_bounded_falsifier_node(
        staged=stage, nodeid=nodeid, wall_clock_s=30, output_cap_bytes=65536,
    )

    assert failure is None
    assert report is not None
    assert falsifier._outcome_from_report(report, nodeid, returncode) == "error"


def test_falsifier_skipped_collection_is_not_node_missing(tmp_path):
    from phase_loop_runtime import falsifier

    stage = tmp_path / "stage"
    tests = stage / "phase-loop-runtime" / "tests"
    tests.mkdir(parents=True)
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    (stage / path).write_text(
        "import pytest\npytest.skip('unavailable', allow_module_level=True)\n",
        encoding="utf-8",
    )
    nodeid = f"{path}::test_trigger"

    returncode, _stdout, _stderr, failure, report = review_stage.run_bounded_falsifier_node(
        staged=stage, nodeid=nodeid, wall_clock_s=30, output_cap_bytes=65536,
    )

    assert failure is None
    assert report is not None
    assert falsifier._outcome_from_report(report, nodeid, returncode) == "error"


def test_unencodable_falsifier_diff_closes_authorization(tmp_path):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff="\ud800",
    )
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    with pytest.raises(ValueError):
        falsifier.run_finding_falsifier(
            falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
            authorization=authorization, repo=repo, wall_clock_s=30,
            output_cap_bytes=65536,
        )
    assert backing._falsifier_authorization_lease(authorization).closed


def test_falsifier_exec_bit_validation_survives_noexec_mount(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    source = repo / "src.py"
    source.chmod(0o755)
    subprocess.run(["git", "-C", str(repo), "add", "src.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "executable"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    staged = review_stage.stage_review_tree(repo)
    try:
        assert (staged / "src.py").stat().st_mode & 0o111
        with monkeypatch.context() as patch:
            patch.setattr(review_stage.os, "access", lambda *_args, **_kwargs: False)
            review_stage.revalidate_falsifier_staged_tree(staged=staged, reviewed_sha=head)
    finally:
        review_stage.remove_review_stage(staged)


def test_falsifier_source_rejects_removed_owner_execute_bit(tmp_path):
    from phase_loop_runtime import falsifier

    repo = _git_repo(tmp_path / "repo")
    source = repo / "src.py"
    source.chmod(0o755)
    subprocess.run(["git", "-C", str(repo), "add", "src.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "executable"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    source.chmod(0o655)

    with pytest.raises(ValueError, match="not clean"):
        falsifier._clean_exact_source(repo, head)


def test_falsifier_stage_rejects_removed_owner_execute_bit(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    source = repo / "src.py"
    source.chmod(0o755)
    subprocess.run(["git", "-C", str(repo), "add", "src.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "executable"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    staged = review_stage.stage_review_tree(repo)
    try:
        (staged / "src.py").chmod(0o655)
        with pytest.raises(ValueError, match="executable bit changed"):
            review_stage.revalidate_falsifier_staged_tree(staged=staged, reviewed_sha=head)
    finally:
        review_stage.remove_review_stage(staged)


@pytest.mark.parametrize("kind", ["blob", "mode"])
def test_falsifier_source_rejects_dirty_index_even_with_clean_worktree(tmp_path, kind):
    from phase_loop_runtime import falsifier

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    source = repo / "src.py"
    if kind == "blob":
        source.write_text("staged replacement\n", encoding="utf-8")
    else:
        source.chmod(0o755)
    subprocess.run(["git", "-C", str(repo), "add", "src.py"], check=True)
    if kind == "blob":
        source.write_text("live tree file\n", encoding="utf-8")
    else:
        source.chmod(0o644)
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"]).strip()

    with pytest.raises(ValueError, match="not clean"):
        falsifier._clean_exact_source(repo, head)


def test_falsifier_source_does_not_accept_alternate_git_index(tmp_path, monkeypatch):
    from phase_loop_runtime import falsifier

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    source = repo / "src.py"
    source.write_text("staged replacement\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "src.py"], check=True)
    source.write_text("live tree file\n", encoding="utf-8")
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"]).strip()
    alternate = tmp_path / "alternate-index"
    subprocess.run(
        ["git", "-C", str(repo), "read-tree", "HEAD"], check=True,
        env={**os.environ, "GIT_INDEX_FILE": str(alternate)},
    )
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))

    with pytest.raises(ValueError, match="not clean"):
        falsifier._clean_exact_source(repo, head)


def test_falsifier_source_rejects_tracked_file_through_ancestor_symlink(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("ignored\n", encoding="utf-8")
    tracked = repo / "ignored" / "tracked.py"
    tracked.write_text("committed bytes\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-f", "ignored/tracked.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "tracked"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    outside = tmp_path / "outside"
    (repo / "ignored").rename(outside)
    (repo / "ignored").symlink_to(outside, target_is_directory=True)
    assert b" D " in subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"])

    with pytest.raises(ValueError, match="not clean"):
        falsifier._clean_exact_source(repo, head)
    monkeypatch.setattr(review_stage, "stage_review_tree", lambda _repo: pytest.fail("stage was launched"))
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    entry = SimpleNamespace(
        finding_id="F001", new_test_path="phase-loop-runtime/tests/test_finding_F001.py",
        expected_nodeid="phase-loop-runtime/tests/test_finding_F001.py::test_trigger",
        diff="not a diff",
    )
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10, output_cap_bytes=65536,
    )
    assert result.outcome == "error"
    assert backing._falsifier_authorization_lease(authorization).closed


def test_falsifier_source_ignores_local_replace_ref(tmp_path):
    from phase_loop_runtime import falsifier

    repo, reviewed = _replaced_source_repo(tmp_path / "repo")
    with pytest.raises(ValueError, match="not clean"):
        falsifier._clean_exact_source(repo, reviewed)


def test_falsifier_stage_ignores_ambient_git_dir_and_replace_ref(tmp_path, monkeypatch):
    repo, reviewed = _replaced_source_repo(tmp_path / "repo")
    staged = review_stage.stage_review_tree(repo)
    try:
        assert (staged / "src.py").read_text(encoding="utf-8") == "substituted bytes\n"
        monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
        with pytest.raises(ValueError, match="staged bytes differ"):
            review_stage.revalidate_falsifier_staged_tree(staged=staged, reviewed_sha=reviewed)
    finally:
        review_stage.remove_review_stage(staged)


def test_falsifier_stage_refuses_unenumerable_extra_directory(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    staged = review_stage.stage_review_tree(repo)
    hidden = staged / "hidden_extra"
    hidden.mkdir()
    (hidden / "injected.py").write_text("hostile bytes\n", encoding="utf-8")
    real_scandir = os.scandir

    def refuse_hidden(path):
        if Path(path) == hidden:
            raise PermissionError("cannot enumerate staged directory")
        return real_scandir(path)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(review_stage.os, "scandir", refuse_hidden)
            with pytest.raises(ValueError, match="enumerat"):
                review_stage.revalidate_falsifier_staged_tree(staged=staged, reviewed_sha=head)
    finally:
        review_stage.remove_review_stage(staged)


def test_falsifier_authorization_ignores_ambient_git_repository_controls(tmp_path, monkeypatch):
    from phase_loop_runtime.advisor_board import backing

    repo_a = _git_repo(tmp_path / "repo-a")
    repo_b = tmp_path / "repo-b"
    subprocess.run(["git", "clone", "-q", str(repo_a), str(repo_b)], check=True)
    head = subprocess.check_output(["git", "-C", str(repo_a), "rev-parse", "HEAD"], text=True).strip()
    authorization_a = backing.prepare_falsifier_isolation_authorization(repo=repo_a, reviewed_sha=head)
    try:
        monkeypatch.setenv("GIT_DIR", str(repo_a / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(repo_a))
        with pytest.raises(ValueError, match="repository drifted"):
            backing.revalidate_falsifier_isolation_authorization(authorization_a, repo=repo_b)

        authorization_b = backing.prepare_falsifier_isolation_authorization(repo=repo_b, reviewed_sha=head)
        try:
            monkeypatch.delenv("GIT_DIR")
            monkeypatch.delenv("GIT_WORK_TREE")
            backing.revalidate_falsifier_isolation_authorization(authorization_b, repo=repo_b)
        finally:
            backing.close_falsifier_isolation_authorization(authorization_b)
    finally:
        backing.close_falsifier_isolation_authorization(authorization_a)


@pytest.mark.parametrize("variable", ["extras", "dependency_groups"])
def test_falsifier_unsupported_dependency_marker_records_error(tmp_path, variable):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    project = repo / "phase-loop-runtime" / "pyproject.toml"
    project.parent.mkdir()
    project.write_text(
        f'''[project]\nname = "marker-probe"\nversion = "0.1.0"\ndependencies = ['pytest; {variable} == "test"']\n''',
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "phase-loop-runtime/pyproject.toml"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "marker"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    path = "phase-loop-runtime/tests/test_finding_F001.py"
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
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10, output_cap_bytes=65536,
    )
    assert result.outcome == result.record["outcome"] == "error"
    assert "marker" in (result.detail or "")
    assert result.red_output_digest is None
    assert backing._falsifier_authorization_lease(authorization).closed


def test_falsifier_missing_source_records_error_and_closes_authorization(tmp_path):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    moved = tmp_path / "moved"
    repo.rename(moved)
    entry = SimpleNamespace(
        finding_id="F001", new_test_path="phase-loop-runtime/tests/test_finding_F001.py",
        expected_nodeid="phase-loop-runtime/tests/test_finding_F001.py::test_trigger",
        diff="not a diff",
    )

    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10, output_cap_bytes=65536,
    )
    assert result.outcome == result.record["outcome"] == "error"
    assert result.red_output_digest is None
    assert backing._falsifier_authorization_lease(authorization).closed


def test_falsifier_refuses_repo_exposed_by_system_mount_before_staging(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    assert review_stage._falsifier_repo_exposed_by_system_mount(Path("/usr/src/project"))
    assert not review_stage._falsifier_repo_exposed_by_system_mount(tmp_path)
    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    monkeypatch.setattr(review_stage, "_falsifier_repo_exposed_by_system_mount", lambda _repo: True)
    monkeypatch.setattr(review_stage, "stage_review_tree", lambda _repo: pytest.fail("stage was launched"))
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff="not a diff",
    )
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10,
        output_cap_bytes=65536,
    )
    assert result.outcome == "error"
    assert "system mount" in (result.detail or "")
    with pytest.raises(ValueError):
        backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)


def test_falsifier_rejected_stage_inside_repo_is_cleaned(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    stage_parent = repo / "ignored"
    monkeypatch.setattr(tempfile, "tempdir", str(stage_parent))
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff="not a diff",
    )
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=10,
        output_cap_bytes=65536,
    )
    assert result.outcome == "error"
    assert "not an independent clone" in (result.detail or "")
    assert not list(stage_parent.glob(f"{review_stage.REVIEW_STAGE_DIR_PREFIX}*"))
    with pytest.raises(ValueError):
        backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)


@pytest.mark.parametrize("expected", ["green_on_head", "red_on_head"])
def test_falsifier_real_bwrap_reports_outcome_and_isolation(tmp_path, monkeypatch, expected):
    if not Path("/usr/bin/bwrap").is_file():
        pytest.skip("canonical falsifier launcher absent")
    from types import SimpleNamespace

    from phase_loop_runtime import falsifier
    from phase_loop_runtime.advisor_board import backing

    repo = _git_repo(tmp_path / "repo")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    host_net_inode = (Path("/proc/self/ns/net")).stat().st_ino
    monkeypatch.setenv("FALSIFIER_HOST_SENTINEL", "host-only")
    path = "phase-loop-runtime/tests/test_finding_F001.py"
    source = (
        "import os\n"
        "from pathlib import Path\n"
        "def test_trigger():\n"
        "    assert 'FALSIFIER_HOST_SENTINEL' not in os.environ\n"
        "    assert os.environ['HOME'] == '/home/falsifier'\n"
        f"    assert Path('/proc/self/ns/net').stat().st_ino != {host_net_inode}\n"
        f"    assert {expected == 'green_on_head'}\n"
    )
    diff = (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,7 @@\n"
        + "".join(f"+{line}\n" for line in source.splitlines())
    )
    entry = SimpleNamespace(
        finding_id="F001", new_test_path=path,
        expected_nodeid=f"{path}::test_trigger", diff=diff,
    )
    authorization = backing.prepare_falsifier_isolation_authorization(repo=repo, reviewed_sha=head)
    result = falsifier.run_finding_falsifier(
        falsifier=entry, seat_key="claude:claude-opus-5-5:max:correctness",
        authorization=authorization, repo=repo, wall_clock_s=30,
        output_cap_bytes=65536,
    )
    assert result.outcome == expected, result.detail
    assert (result.red_output_digest is not None) == (expected == "red_on_head")
    assert not (repo / path).exists()
    with pytest.raises(ValueError):
        backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)


def test_early_broken_stdin_close_still_reaps_falsifier_child(tmp_path, monkeypatch):
    if not Path("/usr/bin/bwrap").is_file():
        pytest.skip("canonical falsifier launcher absent")
    original_popen = subprocess.Popen
    launched = []

    class BrokenStdin:
        def __init__(self, stream):
            self.stream = stream

        def write(self, _data):
            raise BrokenPipeError("child closed stdin")

        def close(self):
            self.stream.close()
            raise BrokenPipeError("buffered close failed")

    def launch(_argv, *args, **kwargs):
        proc = original_popen(["/usr/bin/python3", "-c", "raise SystemExit(1)"], *args, **kwargs)
        proc.stdin = BrokenStdin(proc.stdin)
        launched.append(proc)
        return proc

    monkeypatch.setattr(review_stage.subprocess, "Popen", launch)
    try:
        code, _stdout, _stderr, failure, report = review_stage._run_bounded_falsifier_node(
            staged=tmp_path, dependencies=tmp_path,
            nodeid="test_finding_F001.py::test_trigger",
            wall_clock_s=5, output_cap_bytes=65536,
        )
        assert code == 1 and failure is None and report is None
        assert launched[0].returncode == 1
        assert launched[0].stdout.closed and launched[0].stderr.closed
    finally:
        for proc in launched:
            proc.wait(timeout=5)
