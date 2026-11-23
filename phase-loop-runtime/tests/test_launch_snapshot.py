"""LANEEXEC SL-1: snapshot and seed construction (obligation C3, C10 source cases).

Every case enters through the production builders ``build_snapshot`` and ``build_seed`` on
generated temporary repositories and seed trees. Git commands that *set up* a fixture run here
with a clean environment; the builders never run git against the source.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import stat
import subprocess
import time

import pytest
import rfc8785

from phase_loop_runtime import launch_snapshot as ls
from phase_loop_runtime.launch_process_contract import (
    SeedDeclaration,
    SeedLimits,
    Snapshot,
    validate_launch_message,
)

FIXTURES = Path(__file__).parent / "fixtures" / "launch-snapshot"
GIT_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@invalid",
           "GIT_AUTHOR_DATE": "@1 +0000", "GIT_COMMITTER_DATE": "@1 +0000"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                             "-c", "protocol.file.allow=always", *args],
                            cwd=cwd, env=GIT_ENV, capture_output=True, check=check, timeout=60)
    return result.stdout.decode()


def make_repo(root: Path, files: dict[str, str | bytes], *, executable=(), symlinks=None,
              gitignore: str | None = None) -> Path:
    root.mkdir(parents=True)
    git(root, "init", "-q", "--initial-branch=main")
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore)
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body.encode() if isinstance(body, str) else body)
        path.chmod(0o755 if rel in executable else 0o644)
    for rel, target in (symlinks or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, root / rel)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def spec(root: Path, mode: str = "git", masks=(), mask_dirs=(), cwd: str = ".") -> Snapshot:
    return Snapshot(str(root), mode, tuple(masks), tuple(mask_dirs), cwd)


def policy(workload="pi-runner", result_kind="result", **kw) -> ls.SnapshotPolicy:
    return ls.SnapshotPolicy(workload=workload, result_kind=result_kind, **kw)


def never() -> bool:
    return False


def build(tmp: Path, s: Snapshot, p: ls.SnapshotPolicy | None = None, name="attempt") -> ls.SnapshotHandle:
    return ls.build_snapshot(s, policy=p or policy(), scratch=tmp / name, cancelled=never)


def refused(reason: str, fn, *args, **kw):
    with pytest.raises(ls.SnapshotRefused) as info:
        fn(*args, **kw)
    assert info.value.reason == reason
    assert info.value.code == "sandbox_launch_snapshot_refused"
    return info.value


def exec_git(handle: ls.SnapshotHandle, *args: str, check=True) -> str:
    return git(handle.tree, *args, check=check)


def _trusted_chain(path: Path) -> bool:
    """Whether no component of ``path`` is a symlink or group- or other-writable (x-seed.source)."""
    current = Path("/")
    for part in path.parts[1:]:
        if os.stat(current).st_mode & 0o022:
            return False
        current = current / part
        if os.path.islink(current):
            return False
    return True


@pytest.fixture
def tmp(tmp_path: Path):
    """A private working directory whose ancestor chain meets the seed-root trust rules.

    ``tmp_path`` usually lives under a sticky, world-writable ``/tmp``; seed roots and scratch
    ancestors there are refused by design, so fall back to a private directory under HOME.
    """
    base = tmp_path.resolve()
    if _trusted_chain(base):
        yield base
        return
    home = Path.home().resolve()
    if not home.is_dir() or not _trusted_chain(home):
        pytest.skip("no private temporary directory with a trusted ancestor chain")
    import shutil
    import tempfile
    private = Path(tempfile.mkdtemp(prefix="laneexec-snapshot-", dir=home))
    try:
        yield private
    finally:
        shutil.rmtree(private, ignore_errors=True)


# -- C3: git mode ---------------------------------------------------------------------------

def test_git_mode_classes_self_contained_git_and_input_commit(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n", "dir/b.txt": "b\n"}, gitignore="*.log\nbuild/\n")
    (repo / "notes.txt").write_text("untracked\n")
    (repo / "debug.log").write_text("ignored\n")
    (repo / "build").mkdir()
    (repo / "build" / "out.o").write_text("obj\n")
    # An object unreachable from B must not travel.
    unreachable = subprocess.run(["/usr/bin/git", "hash-object", "-w", "--stdin"], cwd=repo, env=GIT_ENV,
                                 input=b"unreachable secret blob\n", capture_output=True, check=True).stdout.decode().strip()
    git(repo, "remote", "add", "origin", "https://example.invalid/repo.git")
    (repo / ".git" / "hooks" / "post-checkout").write_text("#!/bin/sh\ntouch /nonexistent\n")
    handle = build(tmp, spec(repo))
    classes = {e["path"]: e["class"] for e in handle.inventory}
    assert classes["a.txt"] == classes["dir/b.txt"] == classes[".gitignore"] == "tracked"
    assert classes["notes.txt"] == "untracked"
    assert classes["debug.log"] == "omitted" and classes["build"] == "omitted"
    assert handle.counts.to_json() == {"tracked": 3, "untracked": 1, "ignored": 0, "omitted": 2,
                                       "masked": 0, "special": 0}
    tree = handle.tree
    assert (tree / "notes.txt").read_text() == "untracked\n"
    assert not (tree / "debug.log").exists() and not (tree / "build").exists()
    # Self-contained .git: no hooks, remotes, alternates; only B-reachable objects.
    hooks = tree / ".git" / "hooks"
    assert not hooks.exists() or not any(hooks.iterdir())
    assert not (tree / ".git" / "objects" / "info" / "alternates").exists()
    assert "remote" not in (tree / ".git" / "config").read_text()
    assert exec_git(handle, "for-each-ref", "--format=%(refname)").split() == ["refs/heads/laneexec"]
    assert subprocess.run(["/usr/bin/git", "cat-file", "-e", unreachable], cwd=tree, env=GIT_ENV).returncode != 0
    base = git(repo, "rev-parse", "HEAD").strip()
    assert handle.base_commit == base
    assert handle.input_commit != base and handle.envelope_base_commit == handle.input_commit
    assert exec_git(handle, "rev-parse", "HEAD^").strip() == base
    assert exec_git(handle, "diff", "--name-only", "HEAD").strip() == ""
    assert handle.overlay_sha256 is None
    evidence = handle.evidence().to_json()
    assert validate_launch_message("SnapshotEvidence", evidence)
    assert handle.inventory_sha256 == sha(rfc8785.dumps([dict(e) for e in handle.inventory]))
    assert stat.S_IMODE(os.stat(tree).st_mode) == 0o700
    assert not (tmp / "attempt" / "work").exists()


def test_git_mode_without_untracked_input_has_s_equal_b(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})
    handle = build(tmp, spec(repo))
    assert handle.input_commit == handle.base_commit == git(repo, "rev-parse", "HEAD").strip()


def test_tree_manifest_matches_the_closeout_reducer(tmp):
    from phase_loop_runtime import supervised_capture_v2 as capture  # reference reducer
    repo = make_repo(tmp / "src", {"a.txt": "a\n", "x/run": "#!/bin/sh\n"}, executable={"x/run"},
                     symlinks={"l": "a.txt"})
    handle = build(tmp, spec(repo))
    rows = capture._walk_tree(os.fspath(handle.tree), 1 << 30)  # noqa: SLF001 - cross-check only
    assert sha(rfc8785.dumps(rows)) == handle.content_sha256
    handle.recheck()


def test_dirty_tracked_or_staged_source_refuses_dirty_source(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n", "b.txt": "b\n"})
    (repo / "a.txt").write_text("edited\n")
    refused("dirty_source", build, tmp, spec(repo))
    git(repo, "checkout", "--", "a.txt")
    (repo / "b.txt").write_text("staged\n")
    git(repo, "add", "b.txt")
    refused("dirty_source", build, tmp, spec(repo), name="again")
    assert not (tmp / "attempt").exists() and not (tmp / "again").exists()


def test_patch_with_untracked_input_refuses_untracked_input(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})
    (repo / "new.txt").write_text("n\n")
    refused("untracked_input", build, tmp, spec(repo), policy("implementation", "patch"))


def test_not_a_work_tree(tmp):
    plain = tmp / "plain"
    plain.mkdir()
    (plain / "f").write_text("x")
    refused("not_a_work_tree", build, tmp, spec(plain))
    refused("not_a_work_tree", build, tmp, spec(plain, "git_overlay"), name="b")
    repo = make_repo(tmp / "src", {"sub/a.txt": "a\n"})
    refused("not_a_work_tree", build, tmp, spec(repo / "sub"), name="c")


# -- C3: hostile source configuration -------------------------------------------------------

@pytest.mark.parametrize("mode", ["git", "git_overlay"])
def test_hostile_git_config_is_never_executed(tmp, mode):
    marker = tmp / "MARKER"
    repo = make_repo(tmp / "src", {"a.txt": "a\n", ".gitattributes": "* filter=evil diff=evil\n"})
    script = tmp / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    script.chmod(0o755)
    with open(repo / ".git" / "config", "a") as config:
        config.write(f"[core]\n\tfsmonitor = {script}\n\thooksPath = {tmp}\n\tpager = {script}\n"
                     f"\tsshCommand = {script}\n[filter \"evil\"]\n\tclean = {script}\n\tsmudge = {script}\n"
                     f"\tprocess = {script}\n[diff \"evil\"]\n\ttextconv = {script}\n"
                     f"[include]\n\tpath = {tmp}/included\n")
    (tmp / "included").write_text(f"[core]\n\tfsmonitor = {script}\n")
    for hook in ("post-checkout", "post-index-change", "reference-transaction", "fsmonitor-watchman"):
        path = repo / ".git" / "hooks" / hook
        path.write_text(f"#!/bin/sh\ntouch {marker}\n")
        path.chmod(0o755)
    (repo / "u.txt").write_text("u\n")
    handle = build(tmp, spec(repo, mode))
    assert not marker.exists()
    assert (handle.tree / "a.txt").read_text() == "a\n"
    assert "evil" not in (handle.tree / ".git" / "config").read_text()


# -- C3: masks and the secret matcher -------------------------------------------------------

def test_masks_are_absent_and_skip_worktree_and_secret_matcher_always_applies(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n", "private.txt": "p\n", "vault/k.txt": "k\n",
                                   ".env": "TOKEN=sentinel\n", "keys/server.pem": "pem\n"})
    (repo / "id_ed25519").write_text("untracked secret\n")
    handle = build(tmp, spec(repo, masks=["private.txt"], mask_dirs=["vault"]))
    for rel in ("private.txt", "vault/k.txt", ".env", "keys/server.pem", "id_ed25519"):
        assert not (handle.tree / rel).exists(), rel
    flags = dict(line.split(" ", 1)[::-1] for line in exec_git(handle, "ls-files", "-v").splitlines())
    assert flags["private.txt"] == "S" and flags[".env"] == "S" and flags["vault/k.txt"] == "S"
    assert flags["a.txt"] == "H"
    assert exec_git(handle, "status", "--porcelain").strip() == ""
    assert handle.counts.masked == 5
    # The masks digest covers files, dirs and the matcher identity.
    other = ls.SecretMatcher(dirs=(), names=(".env",), patterns=())
    again = build(tmp, spec(repo, masks=["private.txt"], mask_dirs=["vault"]), policy(secrets=other), name="b")
    assert again.masks_sha256 != handle.masks_sha256
    assert (again.tree / "keys/server.pem").exists()
    assert not (again.tree / ".env").exists()


def test_mask_through_a_symlinked_directory_refuses_mask_outside_root(tmp):
    outside = tmp / "outside"
    outside.mkdir()
    repo = make_repo(tmp / "src", {"a.txt": "a\n"}, symlinks={"out": str(outside)})
    refused("mask_outside_root", build, tmp, spec(repo, masks=["out/secret"]))


# -- C3: full mode --------------------------------------------------------------------------

def test_full_mode_only_where_permitted_and_adds_ignored_files(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"}, gitignore="cache/\n")
    (repo / "cache" / "deep").mkdir(parents=True)
    (repo / "cache" / "deep" / "x.bin").write_text("x\n")
    refused("mode_unpermitted", build, tmp, spec(repo, "full"), policy("pi-runner"))
    refused("mode_unpermitted", build, tmp, spec(repo, "full"), policy("implementation"), name="i")
    handle = build(tmp, spec(repo, "full"), policy("leg"), name="leg")
    assert (handle.tree / "cache/deep/x.bin").read_text() == "x\n"
    assert {e["path"]: e["class"] for e in handle.inventory}["cache/deep/x.bin"] == "ignored"
    assert exec_git(handle, "status", "--porcelain").strip() == ""
    op = build(tmp, spec(repo, "full"), policy("pi-runner", operator_modes=frozenset({"full"})), name="op")
    assert (op.tree / "cache/deep/x.bin").exists()


def test_full_mode_non_work_tree_root_is_uploaded_whole_without_git(tmp):
    plain = tmp / "plain"
    (plain / "d").mkdir(parents=True)
    (plain / "d" / "f.txt").write_text("f\n")
    (plain / "top.sh").write_text("#!/bin/sh\n")
    (plain / "top.sh").chmod(0o755)
    os.mkfifo(plain / "d" / "pipe")
    refused("mode_unpermitted", build, tmp, spec(plain, "full"), policy("pi-runner"))
    handle = build(tmp, spec(plain, "full"), policy("qualification"), name="q")
    assert not (handle.tree / ".git").exists()
    assert handle.base_commit is None and handle.input_commit is None and handle.envelope_base_commit is None
    assert (handle.tree / "d/f.txt").read_text() == "f\n"
    assert {e["path"]: e["class"] for e in handle.inventory}["d/pipe"] == "special"
    assert not os.path.lexists(handle.tree / "d/pipe")
    assert stat.S_IMODE(os.stat(handle.tree / "top.sh").st_mode) == 0o700
    assert validate_launch_message("SnapshotEvidence", handle.evidence().to_json())


def test_full_mode_refuses_a_nested_repository_in_an_ignored_tree(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"}, gitignore="vendor/\n")
    (repo / "vendor" / "lib" / ".git").mkdir(parents=True)
    (repo / "vendor" / "lib" / "f").write_text("f")
    refused("nested_repository", build, tmp, spec(repo, "full"), policy("leg"))


# -- C3: caps -------------------------------------------------------------------------------

def test_too_large_at_each_cap(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a" * 100, "b.txt": "b" * 100})
    (repo / "u.bin").write_bytes(b"u" * 50)
    refused("too_large", build, tmp, spec(repo), policy(limits=ls.SnapshotLimits(max_entries=2)), name="e")
    refused("too_large", build, tmp, spec(repo), policy(limits=ls.SnapshotLimits(max_bytes=200)), name="b")
    refused("too_large", build, tmp, spec(repo), policy(limits=ls.SnapshotLimits(untracked_blob_max_bytes=49)),
            name="u")
    ok = build(tmp, spec(repo), policy(limits=ls.SnapshotLimits(max_entries=3, max_bytes=250,
                                                                untracked_blob_max_bytes=50)), name="ok")
    assert ok.byte_total == 250
    with pytest.raises(ValueError):
        ls.SnapshotLimits(max_bytes=536870913)


def test_timeout_and_cancel(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})
    refused("timeout", ls.build_snapshot, spec(repo), policy=policy(), scratch=tmp / "t", cancelled=never,
            deadline=time.monotonic() - 1)
    with pytest.raises(ls.ConstructionCancelled):
        ls.build_snapshot(spec(repo), policy=policy(), scratch=tmp / "c", cancelled=lambda: True)
    assert not (tmp / "t").exists() and not (tmp / "c").exists()


# -- C3: recheck ----------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["git", "git_overlay"])
def test_mid_copy_source_mutation_refuses_source_changed(tmp, monkeypatch, mode):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})
    (repo / "u.txt").write_text("u\n")
    monkeypatch.setattr(ls, "_after_copy", lambda tree: (repo / "u.txt").write_text("changed\n"))
    refused("source_changed", build, tmp, spec(repo, mode))
    assert not (tmp / "attempt").exists()


@pytest.mark.parametrize("mutation", ["head", "index", "untracked"])
def test_head_index_and_listing_rechecked(tmp, monkeypatch, mutation):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})

    def mutate(tree):
        if mutation == "head":
            git(repo, "commit", "-q", "--allow-empty", "-m", "moved")
        elif mutation == "index":
            git(repo, "update-index", "--chmod=+x", "a.txt")
        else:
            (repo / "late.txt").write_text("late\n")
    monkeypatch.setattr(ls, "_after_copy", mutate)
    refused("source_changed", build, tmp, spec(repo))


def test_overlay_captured_tree_mutation_refuses_and_recheck_detects_later_change(tmp, monkeypatch):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})
    (repo / "a.txt").write_text("edited\n")
    monkeypatch.setattr(ls, "_after_copy", lambda tree: (tree / "a.txt").write_text("tampered\n"))
    refused("source_changed", build, tmp, spec(repo, "git_overlay"))
    monkeypatch.setattr(ls, "_after_copy", lambda tree: None)
    handle = build(tmp, spec(repo, "git_overlay"), name="ok")
    handle.recheck()
    (handle.tree / "a.txt").write_text("tampered\n")
    refused("source_changed", handle.recheck)


# -- C3: path rules -------------------------------------------------------------------------

def test_submodule_refuses_unsupported_repository(tmp):
    inner = make_repo(tmp / "inner", {"x": "x\n"})
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})
    git(repo, "submodule", "add", "-q", str(inner), "mod")
    git(repo, "commit", "-q", "-m", "sub")
    refused("unsupported_repository", build, tmp, spec(repo))
    refused("unsupported_repository", build, tmp, spec(repo, "git_overlay"), name="o")


def test_gitmodules_file_alone_refuses_unsupported_repository(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n", ".gitmodules": "[submodule]\n"})
    refused("unsupported_repository", build, tmp, spec(repo))


def test_nested_repository_refuses(tmp):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})
    make_repo(repo / "nested", {"n": "n\n"})
    refused("nested_repository", build, tmp, spec(repo))
    refused("nested_repository", build, tmp, spec(repo, "git_overlay"), name="o")


@pytest.mark.parametrize("name", ["café.txt", "ctl\x01name", "sub/.GIT/x", "back\\slash"])
def test_unsafe_untracked_names_refuse_unsafe_path(tmp, name):
    repo = make_repo(tmp / "src", {"a.txt": "a\n"})
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    refused("unsafe_path", build, tmp, spec(repo))


def test_unsafe_tracked_name_refuses_unsupported_repository(tmp):
    repo = make_repo(tmp / "src", {"café.txt": "a\n"})
    refused("unsupported_repository", build, tmp, spec(repo))


# -- C3: linked worktree --------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["git", "git_overlay"])
def test_linked_worktree_root_gets_a_self_contained_git(tmp, mode):
    repo = make_repo(tmp / "main", {"a.txt": "a\n"})
    git(repo, "branch", "other")
    git(repo, "commit", "-q", "--allow-empty", "-m", "main only")
    other_head = git(repo, "rev-parse", "HEAD").strip()
    (repo / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n")
    git(repo, "config", "user.secretish", "sentinel-config-value")
    linked = tmp / "linked"
    git(repo, "worktree", "add", "-q", str(linked), "other")
    assert (linked / ".git").is_file()
    (linked / "u.txt").write_text("u\n")
    handle = build(tmp, spec(linked, mode))
    gitdir = handle.tree / ".git"
    assert gitdir.is_dir()
    assert not (gitdir / "commondir").exists() and not (gitdir / "worktrees").exists()
    assert "sentinel-config-value" not in (gitdir / "config").read_text()
    assert exec_git(handle, "for-each-ref", "--format=%(refname)").split() == ["refs/heads/laneexec"]
    assert subprocess.run(["/usr/bin/git", "cat-file", "-e", other_head], cwd=handle.tree,
                          env=GIT_ENV).returncode != 0
    assert handle.base_commit == git(linked, "rev-parse", "HEAD").strip()
    assert (handle.tree / "u.txt").read_text() == "u\n"


# -- C3: git_overlay ------------------------------------------------------------------------

def overlay_repo(tmp: Path) -> Path:
    return make_repo(tmp / "src", {"keep.txt": "keep\n", "mod.txt": "old\n", "staged.txt": "s0\n",
                                   "gone.txt": "gone\n", "old_name.txt": "renamed\n", "tool.sh": "#!/bin/sh\n"},
                     gitignore="*.log\n")


def test_git_overlay_contents_and_modes(tmp):
    repo = overlay_repo(tmp)
    base = git(repo, "rev-parse", "HEAD").strip()
    base_tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    (repo / "mod.txt").write_text("new\n")
    (repo / "staged.txt").write_text("s1\n")
    git(repo, "add", "staged.txt")
    (repo / "staged.txt").write_text("s2 edited\n")
    (repo / "untracked.txt").write_text("u\n")
    (repo / "debug.log").write_text("ignored\n")
    (repo / "gone.txt").unlink()
    git(repo, "mv", "old_name.txt", "new_name.txt")
    (repo / "tool.sh").chmod(0o755)
    handle = build(tmp, spec(repo, "git_overlay"))
    tree = handle.tree
    assert (tree / "mod.txt").read_text() == "new\n"
    assert (tree / "staged.txt").read_text() == "s2 edited\n"
    assert (tree / "untracked.txt").read_text() == "u\n"
    assert not (tree / "debug.log").exists()
    assert not (tree / "gone.txt").exists() and not (tree / "old_name.txt").exists()
    assert (tree / "new_name.txt").read_text() == "renamed\n"
    assert stat.S_IMODE(os.stat(tree / "tool.sh").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(tree / "keep.txt").st_mode) == 0o600
    assert handle.base_commit == base and handle.envelope_base_commit == base
    assert exec_git(handle, "write-tree").strip() == base_tree
    assert exec_git(handle, "rev-parse", "HEAD").strip() == base
    expected = [
        ["gone.txt", "deleted", None],
        ["mod.txt", "file", sha(b"new\n")],
        ["new_name.txt", "file", sha(b"renamed\n")],
        ["old_name.txt", "deleted", None],
        ["staged.txt", "file", sha(b"s2 edited\n")],
        ["tool.sh", "executable_file", sha(b"#!/bin/sh\n")],
        ["untracked.txt", "file", sha(b"u\n")],
    ]
    assert handle.overlay == rfc8785.dumps(expected)
    assert handle.overlay_sha256 == sha(rfc8785.dumps(expected))
    evidence = handle.evidence().to_json()
    assert evidence["overlay_sha256"] == handle.overlay_sha256
    assert validate_launch_message("SnapshotEvidence", evidence)
    assert handle.descriptor()["overlay_sha256"] == handle.overlay_sha256


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_git_overlay_single_change_succeeds_without_the_diff_check(tmp, change):
    repo = overlay_repo(tmp)
    if change == "modify":
        (repo / "mod.txt").write_text("changed\n")
    else:
        (repo / "gone.txt").unlink()
    handle = build(tmp, spec(repo, "git_overlay"))
    assert exec_git(handle, "diff", "--name-only").strip() == ("mod.txt" if change == "modify" else "gone.txt")
    refused("dirty_source", build, tmp, spec(repo, "git"), name="plain")


def test_git_overlay_permissions(tmp):
    repo = overlay_repo(tmp)
    refused("mode_unpermitted", build, tmp, spec(repo, "git_overlay"), policy("implementation"))
    refused("mode_unpermitted", build, tmp, spec(repo, "git_overlay"), policy("pi-runner", "patch"), name="p")
    refused("mode_unpermitted", build, tmp, spec(repo, "git_overlay"),
            policy("implementation", "patch", operator_modes=frozenset({"git_overlay"})), name="q")
    ok = build(tmp, spec(repo, "git_overlay"),
               policy("implementation", "result", operator_modes=frozenset({"git_overlay"})), name="r")
    assert ok.mode == "git_overlay"


def test_git_overlay_changed_gitlink_refuses(tmp):
    repo = overlay_repo(tmp)
    oid = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{oid},vendored")
    refused("unsupported_repository", build, tmp, spec(repo, "git_overlay"))


def test_git_overlay_masks_secrets_and_caps(tmp):
    repo = overlay_repo(tmp)
    (repo / "mod.txt").write_text("x" * 64)
    (repo / ".env").write_text("TOKEN=sentinel\n")
    handle = build(tmp, spec(repo, "git_overlay", masks=["keep.txt"]))
    assert not (handle.tree / ".env").exists() and not (handle.tree / "keep.txt").exists()
    assert b".env" not in handle.overlay
    refused("too_large", build, tmp, spec(repo, "git_overlay"),
            policy(limits=ls.SnapshotLimits(untracked_blob_max_bytes=63)), name="blob")
    refused("too_large", build, tmp, spec(repo, "git_overlay"), policy(limits=ls.SnapshotLimits(max_entries=3)),
            name="entries")
    refused("too_large", build, tmp, spec(repo, "git_overlay"), policy(limits=ls.SnapshotLimits(max_bytes=10)),
            name="bytes")


def test_overlay_digest_changes_with_each_entry_kind_and_symlink_target_is_never_opened(tmp):
    repo = make_repo(tmp / "src", {"f.txt": "f\n"}, symlinks={"l": "f.txt"})
    digests = {build(tmp, spec(repo, "git_overlay"), name="clean").overlay_sha256}
    os.unlink(repo / "l")
    sentinel = tmp / "fifo-target"
    os.mkfifo(sentinel)  # opening it would block; the target bytes are read, never the target
    os.symlink(str(sentinel), repo / "l")
    first = build(tmp, spec(repo, "git_overlay"), name="link1")
    os.unlink(repo / "l")
    os.symlink(str(sentinel) + "x", repo / "l")
    second = build(tmp, spec(repo, "git_overlay"), name="link2")
    assert len({first.overlay_sha256, second.overlay_sha256} | digests) == 3
    assert os.readlink(first.tree / "l") == str(sentinel)
    (repo / "f.txt").chmod(0o755)
    third = build(tmp, spec(repo, "git_overlay"), name="exec")
    (repo / "f.txt").unlink()
    fourth = build(tmp, spec(repo, "git_overlay"), name="del")
    assert len({first.overlay_sha256, second.overlay_sha256, third.overlay_sha256, fourth.overlay_sha256}) == 4


def test_overlay_sha256_null_outside_git_overlay(tmp):
    repo = overlay_repo(tmp)
    handle = build(tmp, spec(repo))
    assert handle.overlay is None and handle.evidence().overlay_sha256 is None


# -- C3: canonical fixtures and enumeration order -------------------------------------------

def _apply(repo: Path, op):
    kind, rel, *rest = op
    if kind == "write":
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(rest[0])
    elif kind == "delete":
        (repo / rel).unlink()
    elif kind == "chmod":
        (repo / rel).chmod(rest[0])
    elif kind == "symlink":
        os.unlink(repo / rel)
        os.symlink(rest[0], repo / rel)


CANONICAL = json.loads((FIXTURES / "overlay-canonical.json").read_text())


@pytest.mark.parametrize("case", sorted(CANONICAL["cases"]))
def test_canonical_overlay_fixtures(tmp, case):
    files = {rel: body for rel, (kind, body) in CANONICAL["base"].items() if kind == "file"}
    links = {rel: body for rel, (kind, body) in CANONICAL["base"].items() if kind == "symlink"}
    repo = make_repo(tmp / "src", files, executable=set(CANONICAL["base_executable"]), symlinks=links)
    for op in CANONICAL["cases"][case]["ops"]:
        _apply(repo, op)
    handle = build(tmp, spec(repo, "git_overlay"))
    assert handle.overlay == CANONICAL["cases"][case]["overlay_bytes"].encode("utf-8")
    assert handle.overlay_sha256 == CANONICAL["cases"][case]["overlay_sha256"]


def test_enumeration_order_does_not_change_overlay_bytes(tmp):
    rows = [("b/z", "file", sha(b"1")), ("a", "deleted", None), ("b/a", "symlink", sha(b"t")),
            ("é", "executable_file", sha(b"2")), ("B", "file", sha(b"3"))]
    expected = ls.overlay_bytes(rows)
    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        assert ls.overlay_bytes(shuffled) == expected
    names = [f"n{i}.txt" for i in range(12)]
    results = []
    for index, order in enumerate((names, list(reversed(names)))):
        repo = make_repo(tmp / f"src{index}", {"base.txt": "b\n"})
        for name in order:
            (repo / name).write_text(name)
        results.append(build(tmp, spec(repo, "git_overlay"), name=f"o{index}").overlay)
    assert results[0] == results[1]


# -- C10: seed source cases through build_seed ----------------------------------------------

REQUEST_ID = "req-1"


def seed_tree(tmp: Path, files: dict[str, bytes], *, executable=(), manifest_override: bytes | None = None,
              request_id: str = REQUEST_ID, extra: dict[str, bytes] | None = None):
    root = tmp / "seed-root"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    entry_dir = root / request_id
    entry_dir.mkdir(mode=0o700)
    for rel, data in {**files, **(extra or {})}.items():
        path = entry_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    entries = []
    for rel in sorted(files, key=lambda p: p.encode()):
        entry = {"relpath": rel, "sha256": sha(files[rel]), "size": len(files[rel])}
        if rel in executable:
            entry["executable"] = True
        entries.append(entry)
    manifest = manifest_override if manifest_override is not None else rfc8785.dumps(
        {"schema": "laneexec.seed.manifest.v1", "request_id": request_id, "entries": entries})
    (root / f"{request_id}.seed.json").write_bytes(manifest)
    (root / f"{request_id}.seed.json").chmod(0o600)
    decl = SeedDeclaration(sha(manifest), len(entries), sum(len(v) for v in files.values()))
    return root, decl, manifest


def capture(tmp: Path, root: Path, decl: SeedDeclaration, *, limits: SeedLimits = ls.DEFAULT_SEED_LIMITS,
            request_id: str = REQUEST_ID, name: str = "staging") -> ls.SeedHandle:
    return ls.build_seed(decl, request_id=request_id, seed_root=root, limits=limits, staging=tmp / name,
                         cancelled=never)


def seed_refused(reason: str, fn, *args, **kw):
    with pytest.raises(ls.SeedRefused) as info:
        fn(*args, **kw)
    assert info.value.reason == reason
    assert info.value.code == "sandbox_launch_seed_refused"


@pytest.fixture
def opened(monkeypatch):
    """Descriptor trace: every name passed to os.open while a builder runs."""
    names: list[str] = []
    real = os.open

    def tracing(path, flags, mode=0o777, *, dir_fd=None):
        names.append(os.fsdecode(path))
        return real(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "open", tracing)
    return names


def test_seed_capture_happy_path_and_binding(tmp, opened):
    files = {"home/u/.pi/settings.json": b"{}", "home/u/bin/tool": b"#!/bin/sh\n"}
    root, decl, manifest = seed_tree(tmp, files, executable={"home/u/bin/tool"},
                                     extra={"undeclared.txt": b"never read"})
    handle = capture(tmp, root, decl)
    assert "undeclared.txt" not in opened
    assert handle.manifest_sha256 == decl.manifest_sha256
    assert handle.reference() == {"role": "config", "sha256": decl.manifest_sha256,
                                  "byte_length": len(manifest),
                                  "source": {"namespace": "declared_root", "root": "laneexec_seed",
                                             "path": f"{REQUEST_ID}.seed.json"}}
    staged = sorted(str(p.relative_to(handle.staging)) for p in handle.staging.rglob("*") if p.is_file())
    assert staged == sorted(files)
    assert stat.S_IMODE(os.stat(handle.staging).st_mode) == 0o700
    for rel in files:
        assert stat.S_IMODE(os.stat(handle.staging / rel).st_mode) == 0o600
    handle.recheck()
    # manifest_sha256 changes with the executable flag.
    (tmp / "b").mkdir()
    _, decl2, _ = seed_tree(tmp / "b", files)
    assert decl2.manifest_sha256 != decl.manifest_sha256


def test_unseeded_launch_returns_the_empty_handle(tmp):
    handle = ls.build_seed(None, request_id=REQUEST_ID, seed_root=None, limits=ls.DEFAULT_SEED_LIMITS,
                           staging=tmp / "s", cancelled=never)
    assert handle.reference() is None and handle.entries == () and not (tmp / "s").exists()


def test_manifest_digest_mismatch_opens_no_entry(tmp, opened):
    root, decl, _ = seed_tree(tmp, {"a": b"a"})
    bad = SeedDeclaration("0" * 64, decl.entries, decl.total_bytes)
    seed_refused("digest_mismatch", capture, tmp, root, bad)
    assert "a" not in opened and REQUEST_ID not in opened


def _manifest(entries, request_id=REQUEST_ID, schema="laneexec.seed.manifest.v1"):
    return {"schema": schema, "request_id": request_id, "entries": entries}


def _entry(rel, data=b"x", **extra):
    return {"relpath": rel, "sha256": sha(data), "size": len(data), **extra}


@pytest.mark.parametrize("raw", [
    json.dumps(_manifest([_entry("a")]), indent=1).encode(),                         # whitespace
    json.dumps(_manifest([_entry("a")]), separators=(",", ":")).encode(),             # reordered keys
    rfc8785.dumps(_manifest([_entry("b"), _entry("a")])),                              # unsorted entries
    rfc8785.dumps(_manifest([_entry("a")])) + b"\n",                                   # trailing newline
    rfc8785.dumps(_manifest([_entry("a")], schema="other")),                           # schema violation
    rfc8785.dumps(_manifest([_entry("a")], request_id="req-2")),                       # request id
    rfc8785.dumps(_manifest([_entry("a", extra_member=1)])),                           # unknown member
], ids=["whitespace", "reordered", "unsorted", "newline", "schema", "request_id", "member"])
def test_non_canonical_or_invalid_manifest_refuses_manifest_invalid(tmp, raw):
    root, decl, _ = seed_tree(tmp, {"a": b"x", "b": b"x"}, manifest_override=raw)
    count = len(json.loads(raw)["entries"])
    seed_refused("manifest_invalid", capture, tmp, root, SeedDeclaration(sha(raw), count, count))


@pytest.mark.parametrize("entries,total", [(2, 1), (1, 2)])
def test_count_or_size_disagreement_refuses_manifest_invalid(tmp, entries, total):
    root, decl, manifest = seed_tree(tmp, {"a": b"x"})
    seed_refused("manifest_invalid", capture, tmp, root, SeedDeclaration(decl.manifest_sha256, entries, total))


def test_manifest_trust_rules(tmp, monkeypatch):
    root, decl, manifest = seed_tree(tmp, {"a": b"x"})
    (root / f"{REQUEST_ID}.seed.json").chmod(0o620)
    seed_refused("seed_root_untrusted", capture, tmp, root, decl)
    (root / f"{REQUEST_ID}.seed.json").chmod(0o600)
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    seed_refused("seed_root_untrusted", capture, tmp, root, decl, name="uid")


def test_symlinked_manifest_refuses_symlink(tmp):
    root, decl, manifest = seed_tree(tmp, {"a": b"x"})
    real = tmp / "elsewhere.json"
    real.write_bytes(manifest)
    (root / f"{REQUEST_ID}.seed.json").unlink()
    os.symlink(real, root / f"{REQUEST_ID}.seed.json")
    seed_refused("symlink", capture, tmp, root, decl)


def test_manifest_over_manifest_max_bytes(tmp, opened):
    root, decl, manifest = seed_tree(tmp, {"a": b"x"})
    limits = SeedLimits(4096, 16777216, 67108864, len(manifest) - 1)
    seed_refused("too_large", capture, tmp, root, decl, limits=limits)
    ok = capture(tmp, root, decl, limits=SeedLimits(4096, 16777216, 67108864, len(manifest)), name="ok")
    assert ok.manifest == manifest


def test_4096_short_entries_accepted_and_long_relpaths_overflow_the_manifest_bound(tmp):
    files = {f"f{i:04d}": b"" for i in range(4096)}
    root, decl, manifest = seed_tree(tmp, files)
    assert len(manifest) <= 1048576
    assert len(capture(tmp, root, decl).entries) == 4096
    long_files = {f"{'d' * 250}/{i:04d}-{'x' * 200}": b"" for i in range(2400)}
    (tmp / "long").mkdir()
    root2, decl2, manifest2 = seed_tree(tmp / "long", long_files)
    assert len(manifest2) > 1048576
    seed_refused("too_large", capture, tmp, root2, decl2, name="long-staging")


def test_request_id_ending_in_seed_json_refuses_unsafe_path(tmp):
    root, decl, _ = seed_tree(tmp, {"a": b"x"})
    seed_refused("unsafe_path", capture, tmp, root, decl, request_id="abc.seed.json")


@pytest.mark.parametrize("rel", ["/abs", "./a", "a/../b", "a//b", "a/" + "x" * 256, "/".join(["y" * 200] * 6)],
                         ids=["absolute", "dot", "dotdot", "empty", "segment", "length"])
def test_relpath_confinement_refuses_manifest_invalid(tmp, rel):
    raw = rfc8785.dumps(_manifest([_entry(rel)]))
    root, _, _ = seed_tree(tmp, {}, manifest_override=raw)
    seed_refused("manifest_invalid", capture, tmp, root, SeedDeclaration(sha(raw), 1, 1))


def test_1024_character_relpath_of_255_character_segments_is_valid(tmp):
    rel = "/".join(["a" * 255, "b" * 255, "c" * 255, "d" * 254, "e"])
    assert len(rel) == 1024
    root, decl, _ = seed_tree(tmp, {rel: b"ok"})
    assert capture(tmp, root, decl).entries[0].relpath == rel


@pytest.mark.parametrize("entries", [
    [_entry("café")],
    [_entry("a", b"1"), _entry("a", b"2")],
    [_entry("a"), _entry("a/b")],
], ids=["nfc", "duplicate", "prefix"])
def test_unsafe_relpaths_refuse_unsafe_path(tmp, entries):
    raw = rfc8785.dumps(_manifest(entries))
    root, _, _ = seed_tree(tmp, {}, manifest_override=raw)
    total = sum(e["size"] for e in entries)
    seed_refused("unsafe_path", capture, tmp, root, SeedDeclaration(sha(raw), len(entries), total))


@pytest.mark.parametrize("where", ["file", "intermediate", "request_dir", "seed_root"])
def test_symlinks_refuse_and_the_target_is_never_opened(tmp, opened, where):
    sentinel_dir = tmp / "sentinel"
    sentinel_dir.mkdir(mode=0o700)
    (sentinel_dir / "d").mkdir()
    (sentinel_dir / "d" / "f").write_bytes(b"x")
    (sentinel_dir / "SENTINEL").write_bytes(b"x")
    root, decl, _ = seed_tree(tmp, {"d/f": b"x"})
    target_root = root
    if where == "file":
        (root / REQUEST_ID / "d" / "f").unlink()
        os.symlink(sentinel_dir / "SENTINEL", root / REQUEST_ID / "d" / "f")
    elif where == "intermediate":
        (root / REQUEST_ID / "d" / "f").unlink()
        (root / REQUEST_ID / "d").rmdir()
        os.symlink(sentinel_dir / "d", root / REQUEST_ID / "d")
    elif where == "request_dir":
        os.rename(root / REQUEST_ID, sentinel_dir / "req")
        os.symlink(sentinel_dir / "req", root / REQUEST_ID)
    else:
        target_root = tmp / "root-link"
        os.symlink(root, target_root)
    opened.clear()
    seed_refused("symlink", capture, tmp, target_root, decl)
    assert "SENTINEL" not in opened and "f" not in opened


def test_fifo_refuses_not_regular_file_without_blocking(tmp):
    root, decl, _ = seed_tree(tmp, {"p": b"x"})
    (root / REQUEST_ID / "p").unlink()
    os.mkfifo(root / REQUEST_ID / "p")
    seed_refused("not_regular_file", capture, tmp, root, decl)


def test_seed_root_ownership_and_mode(tmp, monkeypatch):
    root, decl, _ = seed_tree(tmp, {"a": b"x"})
    root.chmod(0o750)
    seed_refused("seed_root_untrusted", capture, tmp, root, decl)
    root.chmod(0o700)
    tmp.chmod(stat.S_IMODE(os.stat(tmp).st_mode) | 0o020)
    try:
        seed_refused("seed_root_untrusted", capture, tmp, root, decl, name="anc")
    finally:
        tmp.chmod(stat.S_IMODE(os.stat(tmp).st_mode) & ~0o022)
    real_fstat = os.fstat

    def foreign(fd):
        info = real_fstat(fd)
        if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (os.stat(root).st_dev, os.stat(root).st_ino):
            values = list(info)
            values[4] = info.st_uid + 1
            return os.stat_result(values)
        return info
    monkeypatch.setattr(os, "fstat", foreign)
    seed_refused("seed_root_untrusted", capture, tmp, root, decl, name="own")


@pytest.mark.parametrize("change", ["byte", "short", "long"])
def test_entry_digest_or_size_mismatch(tmp, change):
    root, decl, _ = seed_tree(tmp, {"a": b"abc"})
    path = root / REQUEST_ID / "a"
    path.write_bytes({"byte": b"abd", "short": b"ab", "long": b"abcd"}[change])
    seed_refused("digest_mismatch", capture, tmp, root, decl)
    assert not (tmp / "staging").exists()


@pytest.mark.parametrize("swap", ["file_content", "manifest_identity", "manifest_content", "request_dir",
                                  "seed_root"])
def test_changes_between_capture_and_recheck_refuse_source_changed(tmp, swap):
    root, decl, manifest = seed_tree(tmp, {"a": b"abc"})
    handle = capture(tmp, root, decl)
    if swap == "file_content":
        (root / REQUEST_ID / "a").write_bytes(b"abd")
    elif swap == "manifest_identity":
        fresh = root / "fresh.json"
        fresh.write_bytes(manifest)
        fresh.chmod(0o600)
        os.replace(fresh, root / f"{REQUEST_ID}.seed.json")
    elif swap == "manifest_content":
        (root / f"{REQUEST_ID}.seed.json").write_bytes(manifest.replace(b"abc", b"abc"[::-1]) + b" ")
    elif swap == "request_dir":
        os.rename(root / REQUEST_ID, root / "old")
        (root / REQUEST_ID).mkdir(mode=0o700)
        (root / REQUEST_ID / "a").write_bytes(b"abc")
    else:
        os.rename(root, tmp / "old-root")
        os.makedirs(root, mode=0o700)
        root.chmod(0o700)
        os.rename(tmp / "old-root" / REQUEST_ID, root / REQUEST_ID)
        os.rename(tmp / "old-root" / f"{REQUEST_ID}.seed.json", root / f"{REQUEST_ID}.seed.json")
    seed_refused("source_changed", handle.recheck)


def test_staging_isolation_and_provisioning(tmp):
    files = {"bin/tool": b"#!/bin/sh\n", "conf/settings.json": b"{}"}
    root, decl, _ = seed_tree(tmp, files, executable={"bin/tool"})
    handle = capture(tmp, root, decl)
    (root / REQUEST_ID / "conf" / "settings.json").write_bytes(b"{\"mutated\":1}")
    attempt = tmp / "attempt"
    attempt.mkdir(mode=0o700)
    scratch = attempt / "scratch"
    handle.provision(scratch, image_links=("/opt/pi/node_modules",))
    assert (scratch / "conf/settings.json").read_bytes() == b"{}"
    assert stat.S_IMODE(os.stat(scratch).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(scratch / "bin/tool").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(scratch / "conf/settings.json").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(scratch / "opt").st_mode) == 0o700
    assert os.readlink(scratch / "opt/pi/node_modules") == "/opt/pi/node_modules"
    # A run modifying its seeded copy changes neither the staging nor a later attempt.
    (scratch / "conf/settings.json").write_bytes(b"run edit")
    assert (handle.staging / "conf/settings.json").read_bytes() == b"{}"
    seed_refused("scratch_unprovisioned", handle.provision, scratch)  # never reused
    second = attempt / "scratch2"
    handle.provision(second)
    assert (second / "conf/settings.json").read_bytes() == b"{}"
    handle.discard()
    assert not handle.staging.exists()


@pytest.mark.parametrize("rel", ["opt/pi/node_modules", "opt/pi/node_modules/x", "opt/pi"],
                         ids=["at", "under", "ancestor_file"])
def test_image_link_conflicts(tmp, rel):
    root, decl, _ = seed_tree(tmp, {rel: b"x"})
    handle = capture(tmp, root, decl)
    seed_refused("image_link_conflict", handle.check_image_links, ("/opt/pi/node_modules",))


@pytest.mark.parametrize("ancestor", ["group_writable", "other_writable", "symlink"])
def test_scratch_ancestor_chain_refuses_scratch_unprovisioned(tmp, ancestor):
    root, decl, _ = seed_tree(tmp, {"a": b"x"})
    handle = capture(tmp, root, decl)
    parent = tmp / "attempt"
    parent.mkdir(mode=0o700)
    if ancestor == "symlink":
        os.symlink(parent, tmp / "via-link")
        target = tmp / "via-link" / "scratch"
    else:
        parent.chmod(0o720 if ancestor == "group_writable" else 0o702)
        target = parent / "scratch"
    seed_refused("scratch_unprovisioned", handle.provision, target)
    assert not (parent / "scratch").exists()


def test_seed_size_caps(tmp, opened):
    root, decl, _ = seed_tree(tmp, {"a": b"0123456789", "b": b"0123456789"})
    lowered = dict(max_entries=2, entry_max_bytes=10, max_bytes=20, manifest_max_bytes=1048576)
    capture(tmp, root, decl, limits=SeedLimits(**lowered), name="exact")
    for name, value in (("max_entries", 1), ("max_bytes", 19)):
        opened.clear()
        seed_refused("too_large", capture, tmp, root, decl, limits=SeedLimits(**{**lowered, name: value}),
                     name=name)
        assert f"{REQUEST_ID}.seed.json" not in opened
    opened.clear()
    seed_refused("too_large", capture, tmp, root, decl, limits=SeedLimits(**{**lowered, "entry_max_bytes": 9}),
                 name="entry")
    assert "a" not in opened and "b" not in opened
    # Default ceilings: an entry of entry_max_bytes + 1, and a declaration over max_bytes.
    big = b"z" * 16777217
    (tmp / "big").mkdir()
    root2, decl2, _ = seed_tree(tmp / "big", {"big": big})
    seed_refused("too_large", capture, tmp, root2, decl2, name="big-staging")
    seed_refused("too_large", capture, tmp, root, SeedDeclaration(decl.manifest_sha256, 2, 67108865),
                 name="over")


def test_default_entry_cap_launches_exactly_at_the_cap(tmp):
    root, decl, _ = seed_tree(tmp, {"cap": b"c" * 16777216})
    assert capture(tmp, root, decl).entries[0].size == 16777216


def test_seed_timeout_and_cancel(tmp):
    root, decl, _ = seed_tree(tmp, {"a": b"x"})
    seed_refused("timeout", ls.build_seed, decl, request_id=REQUEST_ID, seed_root=root,
                 limits=ls.DEFAULT_SEED_LIMITS, staging=tmp / "t", cancelled=never,
                 deadline=time.monotonic() - 1)
    with pytest.raises(ls.ConstructionCancelled):
        ls.build_seed(decl, request_id=REQUEST_ID, seed_root=root, limits=ls.DEFAULT_SEED_LIMITS,
                      staging=tmp / "c", cancelled=lambda: True)
