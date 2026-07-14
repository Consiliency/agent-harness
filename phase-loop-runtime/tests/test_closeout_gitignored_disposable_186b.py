"""Regression tests for agent-harness#186b: safe gitignore handling at closeout.

Two guarantees, both end-to-end through ``_perform_phase_closeout`` on a real git
repo:

* **#215 data-loss guard** — a TRACKED-then-ignored OWNED file (real committed
  work that now also matches a .gitignore pattern) is committed at closeout, never
  silently dropped. `git add` stages a tracked file regardless of ignore rules.
* **EXTRACT disposable over-report** — when the executor self-reports only
  disposable byproducts (untracked+ignored `build/`, `*.egg-info/`, `.phase-loop/`)
  as dirty and the real tree is clean and verification passed, the closeout
  finalizes as a no-op instead of a false `dirty_worktree_conflict`.

"Can it fail?" bar: on the pre-fix runner the tracked-ignored owned file was
excluded from `phase_owned_dirty_paths` (dropped), and the disposable-only report
tripped `dirty_worktree_conflict`. Both are revert-verified.
"""

from __future__ import annotations

import subprocess

from phase_loop_runtime.models import StateSnapshot, utc_now
from phase_loop_runtime.profiles import resolve_profile
from phase_loop_runtime.provenance import snapshot_provenance
from phase_loop_runtime import runner as runner_mod
from phase_loop_runtime.runner import (
    _perform_phase_closeout,
    _tracked_paths,
    _untracked_gitignored_paths,
)
from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan


def _git(repo, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_tracked_then_ignored_owned_file_commits_not_dropped(tmp_path):
    # #215 data-loss guard, end-to-end.
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "GEN", roadmap, owned_files=("gen/out.py",))

    gen = repo / "gen"
    gen.mkdir()
    (gen / "out.py").write_text("v1\n", encoding="utf-8")
    # Track it (real committed work), THEN start ignoring gen/.
    _git(repo, "add", "-f", "gen/out.py")
    _git(repo, "commit", "-m", "track gen/out.py")
    (repo / ".gitignore").write_text("gen/\n", encoding="utf-8")
    commit_fixture_paths(repo, "plan + ignore gen/", plan, repo / ".gitignore")
    # Now modify the tracked-then-ignored owned file — real work to commit.
    (gen / "out.py").write_text("v2 — real work\n", encoding="utf-8")
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # Sanity: it is tracked (so NOT a disposable — must never be dropped).
    assert _untracked_gitignored_paths(repo, ["gen/out.py"]) == set()

    snapshot = StateSnapshot(
        timestamp=utc_now(),
        repo=str(repo),
        roadmap=str(roadmap),
        phases={"GEN": "awaiting_phase_closeout"},
        current_phase="GEN",
        phase_owned_dirty=False,
        phase_owned_dirty_paths=(),
        dirty_paths=("gen/out.py",),
        closeout_terminal_status="complete",
        **snapshot_provenance(roadmap),
    )

    status, event = _perform_phase_closeout(
        repo, roadmap, "GEN", snapshot, resolve_profile("execute"),
        action="execute", closeout_mode="commit",
    )

    assert event.blocker is None, f"expected no blocker, got {event.blocker!r}"
    assert status == "complete", f"expected complete, got {status}"
    head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head_after != head_before, "the owned tracked-then-ignored file must commit"
    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout
    assert "gen/out.py" in committed
    assert "gen/out.py" not in _git(repo, "status", "--short").stdout


def test_disposable_only_report_finalizes_noop_not_conflict(tmp_path):
    # EXTRACT: executor over-reports untracked+ignored byproducts as its only dirt.
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "EXTRACT", roadmap, owned_files=("src/lib.py",))
    (repo / ".gitignore").write_text("build/\n*.egg-info/\n.phase-loop/\n.dev-skills/\n", encoding="utf-8")
    commit_fixture_paths(repo, "plan + ignores", plan, repo / ".gitignore")

    # Real, on-disk disposable byproducts — untracked AND gitignored.
    for rel in ("build/lib.txt", "pkg.egg-info/PKG-INFO", ".phase-loop/scratch", ".dev-skills/note"):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("byproduct\n", encoding="utf-8")

    # The runtime's own git status hides them — the tree is genuinely clean.
    assert _git(repo, "status", "--short").stdout.strip() == ""
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    snapshot = StateSnapshot(
        timestamp=utc_now(),
        repo=str(repo),
        roadmap=str(roadmap),
        phases={"EXTRACT": "awaiting_phase_closeout"},
        current_phase="EXTRACT",
        phase_owned_dirty=False,
        phase_owned_dirty_paths=(),
        # Executor over-reports the disposables (git status would have hidden them).
        dirty_paths=("build/lib.txt", "pkg.egg-info/PKG-INFO", ".phase-loop/scratch", ".dev-skills/note"),
        closeout_terminal_status="complete",
        **snapshot_provenance(roadmap),
    )

    status, event = _perform_phase_closeout(
        repo, roadmap, "EXTRACT", snapshot, resolve_profile("execute"),
        action="execute", closeout_mode="commit",
    )

    assert event.blocker is None, f"expected no blocker, got {event.blocker!r}"
    assert status == "complete", f"expected complete, got {status}"
    assert event.metadata["closeout"]["closeout_action"] == "noop_disposable_only"
    # No commit — nothing real to commit.
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_disposable_filter_never_drops_tracked_even_if_ignored(tmp_path):
    # Unit-level safety: a tracked file that also matches an ignore pattern is
    # NEVER classified disposable (the #215 non-negotiable). An untracked+ignored
    # sibling IS.
    repo = make_repo(tmp_path)
    (repo / "tracked.log").write_text("real\n", encoding="utf-8")
    _git(repo, "add", "-f", "tracked.log")
    _git(repo, "commit", "-m", "track tracked.log")
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore logs")
    (repo / "untracked.log").write_text("byproduct\n", encoding="utf-8")

    disposable = _untracked_gitignored_paths(repo, ["tracked.log", "untracked.log", "src/main.py"])
    assert disposable == {"untracked.log"}


def test_tracked_paths_returns_none_on_probe_failure(tmp_path):
    # agent-harness#220 round-4 (codex): `_tracked_paths` must DISTINGUISH a
    # probe failure (git ls-files errored) from "genuinely nothing tracked". A
    # non-git directory makes `git ls-files` exit 128 -> None, not an empty set.
    non_repo = tmp_path / "not-a-git-repo"
    non_repo.mkdir()
    assert _tracked_paths(non_repo, ["anything.py"]) is None


def test_disposable_filter_fails_closed_on_tracked_probe_failure(tmp_path, monkeypatch):
    # agent-harness#220 round-4 (codex): a TRANSIENT `git ls-files` failure must
    # not make a genuinely untracked+ignored path look "not tracked" and get
    # dropped — the tracked-status probe is unknown, so drop NOTHING (fail closed).
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore logs")
    (repo / "untracked.log").write_text("byproduct\n", encoding="utf-8")

    # Sanity: without a probe failure this path IS disposable.
    assert _untracked_gitignored_paths(repo, ["untracked.log"]) == {"untracked.log"}

    # Now fail the `git ls-files` probe (check_output) while `git check-ignore`
    # (subprocess.run) still succeeds, so `_tracked_paths` returns None.
    def _boom(*args, **kwargs):
        raise subprocess.CalledProcessError(128, args[0] if args else "git")

    monkeypatch.setattr(runner_mod.subprocess, "check_output", _boom)
    # Fail closed: drop nothing rather than misclassify a possibly-tracked file.
    assert _untracked_gitignored_paths(repo, ["untracked.log"]) == set()


def test_bare_directory_entry_never_dropped_as_disposable(tmp_path):
    # agent-harness#220 round-4 (git_ops.py:45 defused at the filter): a collapsed
    # bare "build/" reaches this filter only when `expand_dir_dirty_paths` could
    # not expand it (its git probe failed). `git ls-files -- build/` lists MEMBER
    # files, never the bare-dir string, so membership can't prove the directory
    # holds no modified tracked-then-ignored file. It must be KEPT (blocks), never
    # classified disposable and dropped (the #215 class under a probe failure).
    repo = make_repo(tmp_path)
    build = repo / "build"
    build.mkdir()
    (build / "keep.py").write_text("real committed work\n", encoding="utf-8")
    _git(repo, "add", "-f", "build/keep.py")
    _git(repo, "commit", "-m", "track build/keep.py")
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore build/")

    # The bare directory string is gitignored but holds a TRACKED file; it must
    # not be dropped. (Revert-verify: without the bare-dir guard, `_tracked_paths`
    # returns {"build/keep.py"}, the string "build/" is not in it -> dropped.)
    assert _untracked_gitignored_paths(repo, ["build/"]) == set()


def test_trusted_path_untracked_ignored_reported_owned_still_blocks(tmp_path):
    # Fail-closed guard: on the TRUSTED path (phase_owned_dirty=True) the fallback
    # disposable filter is skipped, so closeout_dirty_paths is the executor's raw
    # report. An untracked+ignored path wrongly reported as phase-owned (e.g. a
    # gitignored secret) must NOT be force-committed — the scoped `-f` (tracked
    # subset only) leaves it to a plain add, which errors -> fail-closed block.
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "LEAK", roadmap, owned_files=("secret.env",))
    (repo / ".gitignore").write_text("secret.env\n", encoding="utf-8")
    commit_fixture_paths(repo, "plan + ignore secret", plan, repo / ".gitignore")
    (repo / "secret.env").write_text("API_TOKEN=leak\n", encoding="utf-8")  # untracked + ignored
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    snapshot = StateSnapshot(
        timestamp=utc_now(),
        repo=str(repo),
        roadmap=str(roadmap),
        phases={"LEAK": "awaiting_phase_closeout"},
        current_phase="LEAK",
        phase_owned_dirty=True,  # TRUSTED path: fallback/disposable-filter skipped
        phase_owned_dirty_paths=("secret.env",),
        dirty_paths=("secret.env",),
        closeout_terminal_status="complete",
        **snapshot_provenance(roadmap),
    )

    status, event = _perform_phase_closeout(
        repo, roadmap, "LEAK", snapshot, resolve_profile("execute"),
        action="execute", closeout_mode="commit",
    )

    # Fail closed: the phase does NOT reach complete and the ignored path is not
    # force-committed (commit_failed on the plain add, not a silent force-commit).
    assert status != "complete", "an untracked+ignored 'owned' path must fail closed"
    assert event.metadata["closeout"]["closeout_action"] == "commit_failed"
    # It was NOT committed into history.
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert "secret.env" not in _git(repo, "show", "--name-only", "--format=", "HEAD").stdout
