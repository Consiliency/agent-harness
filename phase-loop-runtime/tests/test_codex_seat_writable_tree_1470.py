"""agent-harness#1470: a workspace-write codex seat gets ITS OWN staged tree writable.

Since the seat-launch owner (0.7.25) every path a provider names with ``--cd`` was bound
read-only into the seat's view. The codex board seat runs ``--sandbox workspace-write`` rooted
at its staged tree, and codex's sandbox must create its mount points in the workspace root
before any command can start, so on a read-only tree the seat could run nothing.

The rule these tests pin (maintainer ruling 2026-10-10):

* the ONE directory that is this leg's own disposable staged clone is bound writable, and
  only for a codex seat whose argv says ``--sandbox workspace-write`` and names that tree
  with ``--cd``;
* the grant is explicit (the code that staged the tree passes it down) AND checked again
  where the view is built: a staged tree by provenance, marked as a sandbox by THIS process,
  a real directory of the operator's, never a link;
* a grant that fails any check REFUSES the launch; it never falls back to another path,
  and nothing else in the view changes -- the unbrokered (read-only) codex route, grok's
  ``--cwd``, ``--add-dir`` and every other bind stay exactly as they were;
* everything the seat leaves in the tree is removed by the leg's teardown, and nothing the
  runtime records after the run is read from the tree.
"""
from __future__ import annotations

import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import review_stage, sandbox_egress, sandbox_retention
from phase_loop_runtime.advisor_board import backing

needs_owner = pytest.mark.skipif(not os.path.exists("/usr/bin/bwrap") or os.getuid() == 0,
                                 reason="needs an unprivileged /usr/bin/bwrap")

REFUSED = "seat_bind_source_unavailable"


# --------------------------------------------------------------------------------------
# Fixtures: a staged tree as `prepare_local_stage` leaves it, and stand-in CLIs.
# --------------------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    (path / "SOURCE.py").write_text("value = 41\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "-c", "commit.gpgsign=false", "commit", "-qm", "c")
    return path


def _stage(base: Path, *, marked: bool = True) -> Path:
    """``base/review/reviewed-tree``: a real clone with the stage marker, in a directory this
    process marked as its sandbox -- what ``prepare_local_stage`` produces for a leg."""
    tree = _repo(base / "review" / review_stage.REVIEW_STAGE_TREE_DIRNAME)
    (tree / ".git" / "phase-loop-source-commit").write_text(_git(tree, "rev-parse", "HEAD") + "\n",
                                                            encoding="utf-8")
    (base / "out").mkdir()
    if marked:
        sandbox_retention.mark_as_sandbox(base, owner_pid=os.getpid())
    return tree


def _clis(tmp_path: Path, monkeypatch, *, codex: str = "#!/bin/sh\nexit 0\n") -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("codex", codex), ("grok", "#!/bin/sh\nexit 0\n")):
        cli = bin_dir / name
        cli.write_text(body, encoding="utf-8")
        cli.chmod(0o755)
    home = tmp_path / "operator"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text('{"tokens": {"access_token": "synthetic-access"}}',
                                               encoding="utf-8")
    (home / ".grok").mkdir()
    (home / ".grok" / "auth.json").write_text('{"x": {"key": "synthetic-grok-key"}}', encoding="utf-8")
    (home / ".grok" / "agent_id").write_text("synthetic-agent", encoding="utf-8")
    path = f"{bin_dir}{os.pathsep}/usr/bin:/bin"
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", path)
    pi._recorded_provider_hashes.cache_clear()
    return {"HOME": str(home), "PATH": path}


def _codex_argv(tree: Path, out: Path, *, sandbox: str = "workspace-write") -> list[str]:
    return ["codex", "exec", "--cd", str(tree), "--skip-git-repo-check", "--sandbox", sandbox,
            "--model", "m", "--output-last-message", str(out / "panel-codex.txt"), "-"]


def _view(command, *, env, cwd, **grant) -> list[str]:
    """The bubblewrap view the seat-launch owner would build for this command."""
    with pi._seat_command_profile(command, env=env, cwd=cwd, **grant) as (_owned, profile):
        return pi._seat_filesystem_view(
            cwd, readonly_paths=profile.readonly_paths, outputs=profile.outputs,
            output_dirs=profile.output_dirs,
            profile_mounts=profile.mount_args, broker_socket=profile.broker_socket,
            writable_trees=profile.writable_trees)


def _binds(view: list[str], path: Path) -> list[str]:
    """Every bind flag whose DESTINATION is ``path``."""
    return [view[i] for i in range(len(view) - 2)
            if view[i] in ("--bind", "--ro-bind", "--ro-bind-try", "--tmpfs") and (
                view[i + 2] == str(path) or (view[i] == "--tmpfs" and view[i + 1] == str(path)))]


def _without(view: list[str], flag: str, path: Path) -> list[str]:
    """``view`` minus the one ``flag path path`` bind (which must be there exactly once)."""
    triple = [flag, str(path), str(path)]
    hits = [i for i in range(len(view) - 2) if view[i:i + 3] == triple]
    assert len(hits) == 1, (triple, hits)
    return view[:hits[0]] + view[hits[0] + 3:]


# --------------------------------------------------------------------------------------
# The view: exactly one writable tree, and only under every condition.
# --------------------------------------------------------------------------------------

def test_the_granted_staged_tree_is_bound_writable_and_nothing_else_changes(tmp_path, monkeypatch):
    env = _clis(tmp_path, monkeypatch)
    tree = _stage(tmp_path / "leg")
    out = tmp_path / "leg" / "out"
    command = _codex_argv(tree, out)
    plain = _view(command, env=env, cwd=out)
    granted = _view(command, env=env, cwd=out, writable_tree=tree)
    assert _binds(plain, tree) == ["--ro-bind"], "without the grant the tree stays read-only"
    assert _binds(granted, tree) == ["--bind"]
    # The ONLY difference between the two views is that one bind.
    assert _without(granted, "--bind", tree) == _without(plain, "--ro-bind", tree)
    at = next(i for i in range(len(granted)) if granted[i:i + 3] == ["--bind", str(tree), str(tree)])
    assert at < granted.index("--remount-ro"), "bound before the root is sealed"


def test_the_sandbox_probe_is_shown_the_same_writable_tree(tmp_path, monkeypatch):
    """The probe answers for the seat's view only if it gets the seat's view: the probe argv
    derived from a workspace-write launch is granted the same tree, and the probe derived
    from a read-only launch is not."""
    env = _clis(tmp_path, monkeypatch)
    tree = _stage(tmp_path / "leg")
    out = tmp_path / "leg" / "out"
    probe = pi._codex_sandbox_probe_command(_codex_argv(tree, out))
    assert probe[:6] == ["codex", "sandbox", "--permission-profile", ":workspace", "--cd", str(tree)]
    assert _binds(_view(probe, env=env, cwd=out, writable_tree=tree), tree) == ["--bind"]
    read_only_probe = pi._codex_sandbox_probe_command(_codex_argv(tree, out, sandbox="read-only"))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        _view(read_only_probe, env=env, cwd=out, writable_tree=tree)


def test_the_grant_is_refused_for_a_read_only_seat(tmp_path, monkeypatch):
    """`--sandbox read-only` is a seat that must not write: a grant for it is a defect in
    the caller, refused rather than honoured or ignored."""
    env = _clis(tmp_path, monkeypatch)
    tree = _stage(tmp_path / "leg")
    out = tmp_path / "leg" / "out"
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        _view(_codex_argv(tree, out, sandbox="read-only"), env=env, cwd=out, writable_tree=tree)


def test_the_grant_is_refused_when_the_argv_names_another_tree(tmp_path, monkeypatch):
    """Bind the WRONG tree: the grant names one leg's tree, the argv another's. Neither
    becomes writable; the launch is refused."""
    env = _clis(tmp_path, monkeypatch)
    mine, other = _stage(tmp_path / "leg-a"), _stage(tmp_path / "leg-b")
    out = tmp_path / "leg-a" / "out"
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        _view(_codex_argv(other, out), env=env, cwd=out, writable_tree=mine)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        _view(_codex_argv(mine, out)[:2] + ["--skip-git-repo-check", "--sandbox", "workspace-write", "-"],
              env=env, cwd=out, writable_tree=mine)  # no --cd at all


def test_a_tree_that_is_not_this_process_s_staged_sandbox_is_refused(tmp_path, monkeypatch):
    env = _clis(tmp_path, monkeypatch)
    cases = {}
    # (1) a staged-looking tree in a directory nobody marked as a sandbox
    cases["unmarked"] = _stage(tmp_path / "unmarked", marked=False)
    # (2) marked, but by another process
    foreign = _stage(tmp_path / "foreign", marked=False)
    sandbox_retention.mark_as_sandbox(tmp_path / "foreign", owner_pid=os.getppid())
    cases["another process's"] = foreign
    # (2b) marked with this pid but another start time: a recycled pid is not this process
    recycled = _stage(tmp_path / "recycled", marked=False)
    (tmp_path / "recycled" / sandbox_retention.SANDBOX_MARKER).write_text(
        f"created by phase-loop review staging; safe to reap\npid={os.getpid()} start=1\n",
        encoding="utf-8")
    cases["a recycled pid's"] = recycled
    # (3) the operator's real repository: right content, no stage marker, wrong name
    cases["a live checkout"] = _repo(tmp_path / "live" / "review" / "checkout")
    sandbox_retention.mark_as_sandbox(tmp_path / "live", owner_pid=os.getpid())
    # (4) the right name and a marker file, but the recorded commit is not in the repository
    forged = _stage(tmp_path / "forged")
    (forged / ".git" / "phase-loop-source-commit").write_text("0" * 40 + "\n", encoding="utf-8")
    cases["a forged marker"] = forged
    for label, tree in cases.items():
        out = tree.parent.parent / "out"
        out.mkdir(exist_ok=True)
        try:
            _view(_codex_argv(tree, out), env=env, cwd=out, writable_tree=tree)
        except sandbox_egress.SeatIdentityUnverified as refusal:
            assert REFUSED in str(refusal), label
        else:
            pytest.fail(f"{label} tree was bound writable")


def test_a_grant_for_a_path_that_is_also_bound_read_only_is_refused(tmp_path, monkeypatch):
    """A seat launched IN its review directory has the tree bound read-only as part of that
    directory. A grant for the same path would leave two binds for one destination; the
    launch is refused instead of letting bind order decide."""
    env = _clis(tmp_path, monkeypatch)
    tree = _stage(tmp_path / "leg")
    review_dir = tree.parent
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        _view(_codex_argv(tree, tmp_path / "leg" / "out"), env=env, cwd=review_dir,
              writable_tree=tree)
    # Without the grant that launch is what it always was: the tree read-only.
    assert _binds(_view(_codex_argv(tree, tmp_path / "leg" / "out"), env=env, cwd=review_dir),
                  tree) == ["--ro-bind", "--ro-bind"]


def test_a_linked_tree_is_refused(tmp_path, monkeypatch):
    """The path the argv names must BE the staged directory, not a link to one (or to
    anything else)."""
    env = _clis(tmp_path, monkeypatch)
    real = _stage(tmp_path / "real")
    link_base = tmp_path / "linked"
    (link_base / "review").mkdir(parents=True)
    (link_base / "out").mkdir()
    sandbox_retention.mark_as_sandbox(link_base, owner_pid=os.getpid())
    link = link_base / "review" / review_stage.REVIEW_STAGE_TREE_DIRNAME
    link.symlink_to(real)
    command, out = _codex_argv(link, link_base / "out"), link_base / "out"
    # Refused where the grant is checked, before any view is built ...
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        with pi._seat_command_profile(command, env=env, cwd=out, writable_tree=link):
            pytest.fail("a linked tree was granted")
    # ... and again by the view builder, should a profile ever carry one.
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        pi._seat_filesystem_view(out, writable_trees=(link,))


def test_only_codex_may_be_granted_a_writable_tree(tmp_path, monkeypatch):
    """grok names its tree with `--cwd`; it stays read-only (agent-harness#1336's known
    limit is not changed here), and a grant for it is refused."""
    env = _clis(tmp_path, monkeypatch)
    tree = _stage(tmp_path / "leg")
    out = tmp_path / "leg" / "out"
    grok = ["grok", "--prompt-file", "/dev/stdin", "--output-format", "plain", "--cwd", str(tree),
            "--sandbox", "workspace-write", "--tools", "read_file"]
    assert _binds(_view(grok, env=env, cwd=out), tree) == ["--ro-bind"]
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        _view(grok, env=env, cwd=out, writable_tree=tree)
    as_cd = ["grok", "--cd", str(tree), "--sandbox", "workspace-write", "-"]
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        _view(as_cd, env=env, cwd=out, writable_tree=tree)


def test_add_dir_is_never_writable(tmp_path, monkeypatch):
    """Only the path `--cd` names can be the granted tree. The same tree named by
    `--add-dir` stays read-only, and a second directory beside the granted one too."""
    env = _clis(tmp_path, monkeypatch)
    tree = _stage(tmp_path / "leg")
    extra = tmp_path / "leg" / "extra"
    extra.mkdir()
    out = tmp_path / "leg" / "out"
    command = _codex_argv(tree, out)
    command[2:2] = ["--add-dir", str(extra)]
    view = _view(command, env=env, cwd=out, writable_tree=tree)
    assert _binds(view, tree) == ["--bind"] and _binds(view, extra) == ["--ro-bind"]
    only_add_dir = ["codex", "exec", "--add-dir", str(tree), "--sandbox", "workspace-write", "-"]
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
        _view(only_add_dir, env=env, cwd=out, writable_tree=tree)


def test_the_view_refuses_a_writable_tree_that_is_not_a_directory(tmp_path):
    """The view builder's own check, behind the profile's: a file or a link is never bound
    writable as a tree."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    plain_file = tmp_path / "file"
    plain_file.write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(cwd)
    for bad in (plain_file, link, tmp_path / "missing"):
        with pytest.raises(sandbox_egress.SeatIdentityUnverified, match=REFUSED):
            pi._seat_filesystem_view(cwd, writable_trees=(bad,))


# --------------------------------------------------------------------------------------
# The whole brokered spawn, with a stand-in CLI that really uses the tree.
# --------------------------------------------------------------------------------------

_SEAT_CLI = """#!/usr/bin/python3
import json, os, sys, time
args = sys.argv[1:]
if "login" in args:
    sys.exit(0)
tree = args[args.index("--cd") + 1]
if args and args[0] == "sandbox":
    # What codex's launcher does first on the workspace-write route: make its mount point in
    # the workspace root. Where it cannot, it dies with this line.
    if args[args.index("--permission-profile") + 1] == ":workspace":
        target = os.path.join(tree, ".agents")
        try:
            os.mkdir(target)
        except OSError as exc:
            sys.stderr.write("bwrap: Can't mkdir %s: %s\\n" % (target, exc.strerror))
            sys.exit(1)
        os.rmdir(target)
    sys.exit(0)
sys.stdin.read()
report = {{}}
def attempt(name, action):
    try:
        report[name] = action()
    except OSError as exc:
        report[name] = "ERR " + (exc.strerror or str(exc))
def write(path, text="written by the seat\\n"):
    with open(path, "w") as handle:
        handle.write(text)
    return "ok"
attempt("read", lambda: open(os.path.join(tree, "SOURCE.py")).read().strip())
attempt("write", lambda: write(os.path.join(tree, "written-by-seat.txt")))
attempt("overwrite", lambda: write(os.path.join(tree, "SOURCE.py"), "value = 'changed by the seat'\\n"))
for label, path in {probes!r}.items():
    report["sees " + label] = os.path.lexists(path)
    attempt("writes " + label, lambda path=path: write(os.path.join(path, "seat-was-here")))
if {residue!r}:
    # What a seat can leave behind: codex's mount point, a read-only directory with content,
    # a link out of the tree, and a deep path.
    os.mkdir(os.path.join(tree, ".agents"))
    deep = os.path.join(tree, "ro", "deep", "er")
    os.makedirs(deep)
    write(os.path.join(deep, "file"))
    os.symlink({outside!r}, os.path.join(tree, "link-out"))
    for path in (deep, os.path.dirname(deep), os.path.join(tree, "ro")):
        os.chmod(path, 0o500)
if {hang!r}:
    time.sleep(120)
sys.stderr.write("exec\\n/bin/sh -lc 'cat SOURCE.py' in %s\\n succeeded in 0ms:\\nvalue = 41\\n\\n" % tree)
last = json.dumps(report, sort_keys=True) + "\\n\\nAGREE"
sys.stdout.write(last)
with open(args[args.index("--output-last-message") + 1], "w") as handle:
    handle.write(last)
"""


class _FakeBroker:
    """Only the transport is faked: the REAL ``_parent_infer`` closure runs in-process."""

    invoked = 0

    def __init__(self, *_a, **_k):
        self.evidence: dict[str, object] = {}

    def run_credentialless_client(self, adapter, *, deadline_s, cancel_event=None):
        type(self).invoked += 1
        status, text = adapter.invoke()
        return {"schema": "parent_unix_broker_v1", "status": status, "text": text}, {"fake": True}

    def close(self):
        return None


class _Spawn:
    def __init__(self, tmp_path: Path):
        self.repo = _repo(tmp_path / "operator-repo")
        self.staging = tmp_path / "staging"
        self.outside = tmp_path / "outside-file"
        self.outside.write_text("the operator's file\n", encoding="utf-8")
        self.other_leg = _stage(tmp_path / "staging" / "pl-panel-other-leg")
        self.authorization = backing.ReviewIsolationAuthorization(
            operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
            instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
            routes=(), readonly_tools=("Read",), child_credentialless=True,
            child_network_egress=False, live_tree_exposed=False, api_fallback=False,
            canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
            _seal=backing._AUTHORIZATION_SEAL,
            staged_tree_sha256=review_stage.review_tree_manifest_sha256(self.repo),
        )

    def run(self, tmp_path, monkeypatch, *, residue=False, hang=False, timeout_s=None):
        cli = _SEAT_CLI.format(
            probes={"the operator's repository": str(self.repo),
                    "another leg's tree": str(self.other_leg)},
            residue=residue, hang=hang, outside=str(self.outside))
        _clis(tmp_path, monkeypatch, codex=cli)
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(self.staging))
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_ROOT", raising=False)
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", raising=False)
        monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
        monkeypatch.setattr(pi, "derive_review_leg_authorization",
                            lambda *a, **k: types.SimpleNamespace(expires_monotonic_ns=1))
        monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
        monkeypatch.setattr(_FakeBroker, "invoked", 0)
        assert not pi._has_injected_review_execution_seam(leg="codex")
        spawned = pi._default_spawn(
            "codex", "REVIEW BUNDLE BODY", repo_dir=self.repo,
            review_authorization=self.authorization, canonical_repo_authority=self.repo,
            **({"timeout_s": timeout_s} if timeout_s is not None else {}))
        assert _FakeBroker.invoked == 1, f"the brokered branch never ran: {spawned!r}"
        return spawned

    def leftovers(self) -> list[str]:
        """What is left under the staging root besides the other leg's stage."""
        return sorted(p.name for p in self.staging.iterdir() if p.name != "pl-panel-other-leg")


@needs_owner
def test_the_codex_seat_reads_and_writes_its_own_tree_and_nothing_else(tmp_path, monkeypatch,
                                                                       owned_review_network):
    """Through the real owner: the probe passes by itself, the seat runs, reads a file of the
    staged tree and writes into it; the operator's repository and another leg's stage are not
    in its view at all."""
    spawn = _Spawn(tmp_path)
    spawned = spawn.run(tmp_path, monkeypatch)
    assert spawned[0] == "OK", tuple(spawned)
    # Three launches: the login check, the PROBE (it ran and passed; a probe that could not
    # be launched is not counted and would only be inconclusive) and the seat.
    assert spawned.sandbox_placement_evidence["sandbox_local_provider_spawns"] == 3
    report = json.loads(spawned[1].split("\n\n")[0])
    assert report == {
        "read": "value = 41", "write": "ok", "overwrite": "ok",
        "sees the operator's repository": False,
        "writes the operator's repository": "ERR No such file or directory",
        "sees another leg's tree": False,
        "writes another leg's tree": "ERR No such file or directory",
    }
    # The operator's files are exactly as they were.
    assert (spawn.repo / "SOURCE.py").read_text(encoding="utf-8") == "value = 41\n"
    assert _git(spawn.repo, "status", "--porcelain") == ""
    assert (spawn.other_leg / "SOURCE.py").read_text(encoding="utf-8") == "value = 41\n"
    assert sorted(p.name for p in spawn.other_leg.iterdir()) == [".git", "SOURCE.py"]


@needs_owner
def test_what_the_runtime_records_is_not_read_from_the_tree_the_seat_wrote(tmp_path, monkeypatch,
                                                                           owned_review_network):
    """The seat overwrote a reviewed file. The placement record still carries the digest
    taken when the tree was staged, which is the digest the authorization approved."""
    spawn = _Spawn(tmp_path)
    spawned = spawn.run(tmp_path, monkeypatch)
    assert json.loads(spawned[1].split("\n\n")[0])["overwrite"] == "ok"
    placement = spawned.sandbox_placement_evidence
    approved = spawn.authorization.staged_tree_sha256
    assert placement["sandbox_snapshot_sha256"] == approved
    assert {r["snapshot_sha256"] for r in placement["sandbox_placement_receipts"]} == {approved}
    assert placement["sandbox_root_applied"] is True


@needs_owner
def test_teardown_removes_everything_the_seat_left_in_its_tree(tmp_path, monkeypatch,
                                                               owned_review_network):
    """A mount-point directory, a read-only directory tree, a link out of the tree: all gone
    with the stage, and the link's target is untouched."""
    spawn = _Spawn(tmp_path)
    spawned = spawn.run(tmp_path, monkeypatch, residue=True)
    assert spawned[0] == "OK", tuple(spawned)
    assert spawn.leftovers() == []
    assert spawn.outside.read_text(encoding="utf-8") == "the operator's file\n"


@needs_owner
def test_teardown_removes_the_tree_of_a_seat_that_was_killed(tmp_path, monkeypatch,
                                                             owned_review_network):
    """The seat leaves its residue and never returns; the leg times out and is killed. The
    stage is still removed."""
    spawn = _Spawn(tmp_path)
    spawned = spawn.run(tmp_path, monkeypatch, residue=True, hang=True, timeout_s=6)
    assert spawned[0] == "TIMEOUT", tuple(spawned)
    assert spawn.leftovers() == []
    assert spawn.outside.read_text(encoding="utf-8") == "the operator's file\n"


# --------------------------------------------------------------------------------------
# The routes that must NOT change.
# --------------------------------------------------------------------------------------

@needs_owner
def test_the_unbrokered_read_only_codex_seat_still_cannot_write_its_tree(tmp_path, monkeypatch,
                                                                         owned_review_network):
    """`--sandbox read-only`, the advisory route: the staged tree stays read-only in the
    seat's view (bind writable for a read-only seat is the mutation this pins)."""
    cli = _SEAT_CLI.format(probes={}, residue=False, hang=False, outside="")
    # The unbrokered route names the review DIR with --cd; the tree is the directory in it.
    cli = cli.replace('tree = args[args.index("--cd") + 1]',
                      'tree = os.path.join(args[args.index("--cd") + 1], "reviewed-tree")')
    env = _clis(tmp_path, monkeypatch, codex=cli)
    tree = _stage(tmp_path / "leg")
    review_dir, out_dir = tree.parent, tmp_path / "leg" / "out"
    (review_dir / "review-bundle.md").write_text("bundle", encoding="utf-8")
    rc, text, _log = pi._exec_leg("codex", review_dir, out_dir, timeout_s=60, artifact="A", env=env)
    assert rc == 0
    report = json.loads(text.split("\n\n")[0])
    assert report["read"] == "value = 41"
    assert report["write"] == report["overwrite"] == "ERR Read-only file system"
    assert sorted(p.name for p in tree.iterdir()) == [".git", "SOURCE.py"]
