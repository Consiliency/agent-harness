"""Regressions for the findings the codex seat raised on the ah#890 board, round 1.

Three were confirmed by execution and fixed: the manifest collision, the source/stage
selection mismatch, and the cleanup leak. Each of those tests fails against the pre-fix
implementation. They share one theme -- a check that looked right at the SOURCE but was
not invariant under the encoding or the selection basis.

One was REFUTED by execution and is kept here as a control rather than deleted, so the
refutation stays visible and the rule is not silently tightened later: see
`test_a_relative_symlink_that_leaves_and_reenters_is_allowed`.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import review_stage


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_a_newline_in_a_filename_cannot_forge_manifest_records(tmp_path):
    """Finding 1 (BLOCKING): the delimited record was not injective.

    `<kind> <sha> <len> <path>\\n` lets a single file whose NAME contains a newline
    serialize byte-identically to two files. Git permits newlines in paths and
    `ls-files -z` preserves them, so two materially different trees hashed the same.
    """
    empty = hashlib.sha256(b"").hexdigest()

    two = _repo(tmp_path / "two")
    (two / "a").write_text("", encoding="utf-8")
    (two / "b").write_text("", encoding="utf-8")

    forged = _repo(tmp_path / "forged")
    (forged / f"a\nblob {empty} 0 b").write_text("", encoding="utf-8")

    for r in (two, forged):
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)

    assert review_stage.review_tree_manifest_sha256(two) != \
        review_stage.review_tree_manifest_sha256(forged), (
        "two empty files must not hash like one newline-named file"
    )


def test_a_tracked_but_deleted_file_does_not_break_an_honest_tree(tmp_path):
    """Finding 3 (BLOCKING): source and stage disagreed on the selection basis.

    The source hashes via `git ls-files`, which still lists a tracked file deleted from
    the working tree. The stage has no `.git`, so it enumerated by walking. The source
    recorded a tombstone the stage could not reproduce, and an unchanged, approved tree
    failed validation.
    """
    repo = _repo(tmp_path / "repo")
    (repo / "keep.py").write_text("keep\n", encoding="utf-8")
    (repo / "doomed.py").write_text("bye\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "i"],
        check=True,
    )
    (repo / "doomed.py").unlink()  # tracked, deleted, index not updated

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert review_stage.review_tree_manifest_sha256(repo) == \
        review_stage.review_tree_manifest_sha256(staged), (
        "a faithful stage of an honest tree must still match its source digest"
    )
    # The deletion is still bound: the path leaves the set.
    assert not (staged / "doomed.py").exists()


def test_a_symlink_traversing_above_the_tree_root_is_refused(tmp_path):
    """Finding 2, as REFUTED and then narrowed.

    The codex seat reported that `proc/sys/kernel/leak -> ../../../proc/sys/kernel/hostname`
    escapes once the stage is bind-mounted. Measured, it does NOT: from a link three
    directories below the root, `../../../` lands exactly ON the root and the remaining
    path re-enters the tree, both at the source and after relocation. The scenario reads
    `approved bytes` in both places. That finding is not reproducible as stated.

    A real escape needs MORE `..` components than the link's depth. Containment is
    decided textually so the verdict does not depend on where the tree is mounted or on
    resolving through intermediate symlinks.
    """
    repo = _repo(tmp_path / "repo")
    deep = repo / "a" / "b" / "c"
    deep.mkdir(parents=True)
    os.symlink(os.path.join("..", "..", "..", "..", "etc", "passwd"), deep / "leak")

    with pytest.raises(ValueError, match="escaping source tree"):
        review_stage.stage_review_tree(repo, tmp_path / "stage")


def test_a_relative_symlink_that_leaves_and_reenters_is_allowed(tmp_path):
    """The refuted scenario, kept as a control so the rule is not silently tightened.

    It normalizes back inside the tree, so it is in-tree under ANY mount point.
    """
    repo = _repo(tmp_path / "repo")
    deep = repo / "proc" / "sys" / "kernel"
    deep.mkdir(parents=True)
    (deep / "hostname").write_text("approved bytes\n", encoding="utf-8")
    os.symlink("../../../proc/sys/kernel/hostname", deep / "leak")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert (staged / "proc" / "sys" / "kernel" / "leak").is_symlink()


def test_an_in_tree_relative_symlink_is_still_allowed(tmp_path):
    """The textual rule must not refuse ordinary in-tree links (negative control)."""
    repo = _repo(tmp_path / "repo")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "real.py").write_text("real\n", encoding="utf-8")
    os.symlink("real.py", repo / "pkg" / "alias.py")
    os.symlink(os.path.join("..", "pkg", "real.py"), repo / "pkg" / "sideways.py")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert (staged / "pkg" / "alias.py").is_symlink()
    assert (staged / "pkg" / "sideways.py").is_symlink()


def test_a_partially_hardened_stage_is_cleaned_up_on_failure(tmp_path, monkeypatch):
    """Finding 6 (BLOCKING): the failure path used a bare rmtree.

    `stage_review_tree` hardens to 0o500/0o400 and then may raise; a bare
    `rmtree(ignore_errors=True)` cannot unlink through those directories, so the stage
    leaked silently on every failure.
    """
    repo = _repo(tmp_path / "repo")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "a.py").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    parent = tmp_path / "stage"
    boom = RuntimeError("hardening blew up")

    def _explode(staged):
        # Harden for real, then fail: the exact shape that used to leak.
        for path in sorted(Path(staged).rglob("*"), key=lambda p: len(p.parts), reverse=True):
            path.chmod(0o500 if path.is_dir() else 0o400)
        raise boom

    monkeypatch.setattr(review_stage, "_harden_modes", _explode)
    with pytest.raises(RuntimeError):
        review_stage.stage_review_tree(repo, parent)

    leaked = list(parent.glob(review_stage.REVIEW_STAGE_DIR_PREFIX + "*"))
    assert leaked == [], f"a partially hardened stage leaked: {leaked}"


def test_remove_review_stage_never_chmods_through_a_symlinked_root(tmp_path):
    """Cleanup must not change permissions on a directory outside the stage."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n", encoding="utf-8")
    before = outside.stat().st_mode

    link = tmp_path / "stage-link"
    os.symlink(outside, link)

    review_stage.remove_review_stage(link)

    assert outside.is_dir(), "cleanup must not delete through a symlinked root"
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert outside.stat().st_mode == before, "cleanup must not chmod outside the stage"
    assert not link.exists()


def test_a_submodule_gitlink_does_not_crash_staging(tmp_path):
    """Grok finding: `git ls-files` lists a submodule gitlink, but it is a DIRECTORY.

    Copying the raw git list ran `shutil.copy2` on it and raised IsADirectoryError.
    Staging and hashing must share one filtered selection.
    """
    inner = _repo(tmp_path / "inner")
    (inner / "x.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(inner), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(inner), "-c", "commit.gpgsign=false", "commit", "-qm", "i"],
        check=True,
    )

    outer = _repo(tmp_path / "outer")
    (outer / "top.py").write_text("top\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(outer), "-c", "protocol.file.allow=always",
         "submodule", "add", "-q", str(inner), "sub"],
        check=True, capture_output=True,
    )

    staged = review_stage.stage_review_tree(outer, tmp_path / "stage")
    assert (staged / "top.py").is_file()
    # The gitlink is not a reviewable blob; it must not appear as a copied file.
    assert not (staged / "sub").is_file()
    assert review_stage.review_tree_manifest_sha256(outer) == \
        review_stage.review_tree_manifest_sha256(staged)


def test_a_planted_tree_is_refused_even_when_the_lease_approves_none(tmp_path):
    """Grok finding: the spawn-site check sat inside the `digest is not None` branch.

    A lease approving NO tree, plus a tree planted in the staged dir, was therefore
    uncaught at the spawn site on an injected-seam path. The spawn site now calls this
    validator whenever a lease exists, not only when the lease names a tree.
    """
    from phase_loop_runtime.advisor_board import backing

    repo = _repo(tmp_path / "repo")
    (repo / "SOURCE.py").write_text("code\n", encoding="utf-8")

    staged_dir = tmp_path / "staged"
    staged_dir.mkdir()
    planted = review_stage.stage_review_tree(repo, tmp_path / "scratch")
    planted.rename(staged_dir / review_stage.REVIEW_STAGE_TREE_DIRNAME)

    lease_approving_no_tree = backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL, staged_tree_sha256=None,
    )
    with pytest.raises(ValueError, match="without authorization"):
        backing._revalidate_staged_tree(lease_approving_no_tree, staged_dir)


def test_gc_reclaims_a_killed_rounds_readonly_stage(tmp_path):
    """Fable finding: `_gc_stale_panel_scratch` used the exact bare rmtree this module
    documents as unable to unlink through its own 0o500 directories.

    A round killed before its `finally` therefore leaked the whole stage PERMANENTLY --
    the GC that exists to reclaim it silently failed on every later pass.
    """
    from phase_loop_runtime import panel_invoker

    repo = _repo(tmp_path / "repo")
    (repo / "pkg" / "deep").mkdir(parents=True)
    (repo / "pkg" / "deep" / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    scratch = tmp_path / "scratch"
    base = scratch / "pl-panel-killed"
    (base / "review").mkdir(parents=True)
    staged = review_stage.stage_review_tree(repo, base / "review")
    staged.rename(base / "review" / review_stage.REVIEW_STAGE_TREE_DIRNAME)

    os.utime(base, (0, 0))  # older than any cutoff
    panel_invoker._gc_stale_panel_scratch(root=scratch, max_age_s=1)

    assert not base.exists(), (
        "a killed round's read-only stage must be reclaimable by the GC"
    )


def test_an_ignored_venv_symlink_does_not_block_staging(tmp_path):
    """Fable finding 4: containment scanned paths staging would never copy.

    `python -m venv .venv` leaves `.venv/bin/python -> /usr/bin/python3`, which is
    absolute and gitignored. Scanning the whole tree refused the ENTIRE stage over a file
    that is never copied, degrading every seat in the round -- on this repo, whose
    `.gitignore` carries `.venv`.
    """
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (repo / "src.py").write_text("code\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    (repo / ".venv" / "bin").mkdir(parents=True)
    os.symlink("/usr/bin/python3", repo / ".venv" / "bin" / "python")

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert (staged / "src.py").is_file()
    assert not (staged / ".venv").exists(), "ignored paths must not be staged"


def test_a_dangling_in_tree_symlink_is_staged_not_refused(tmp_path):
    """Fable finding 4(b): `resolve(strict=True)` raises on a dangling link.

    A tracked `link.so -> build/out.so` whose target is gitignored or not yet built was
    reported as "escaping source tree". The stage is a partial copy by design, so an
    absent target is expected and is not an escape.
    """
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    os.symlink(os.path.join("build", "out.so"), repo / "link.so")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    staged = review_stage.stage_review_tree(repo, tmp_path / "stage")
    assert (staged / "link.so").is_symlink()
