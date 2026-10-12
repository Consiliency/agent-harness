"""Every host path a review seat's argv names is in that seat's view (agent-harness#1441).

agent-harness#1336 happened because two things in ``panel_invoker`` drifted apart with no
test between them: a seat's argv builder named the staged review tree with one flag, and
``_seat_command_profile`` bound into the seat only the paths named by a fixed set of flags,
which did not include it. The seat started in a view where the directory its own argv
named did not exist.

The check here knows no flag name. It takes the argv the product really builds (for codex
and grok, the argv captured at the launch boundary, ``_run_leg_with_liveness``, with the cwd
it is launched in), finds every operand that is a host path, and asks the profile the real
``_seat_command_profile`` returns whether the seat can see it. A flag that names a host
path and is not bound fails it, whatever the flag is called.

The provider binary is replaced by ``/bin/sh`` (the vendor CLIs are not installed where
this runs, and binding reads the flags, never ``argv[0]``); everything after it is the
product's argv, verbatim.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import review_stage

TREE = review_stage.REVIEW_STAGE_TREE_DIRNAME

needs_owner = pytest.mark.skipif(
    not (os.path.exists("/usr/bin/bwrap") and shutil.which("python3")) or os.getuid() == 0,
    reason="needs bubblewrap and a non-root operator")


def _staged_tree(tmp_path: Path) -> Path:
    """A sandbox the runtime really staged: ``<review>/reviewed-tree`` with its marker."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "source.txt").write_text("TREE-CONTENT\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
                   check=True)
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    staged = review_stage.stage_review_tree(repo, tmp_path / "scratch")
    staged.rename(review_dir / TREE)
    return review_dir / TREE


def _named_host_paths(argv, root: Path) -> list[tuple[str, Path]]:
    """``(flag, path)`` for every argv operand that is a path below ``root``.

    Every host path these tests hand a builder is below ``tmp_path``, so "an absolute
    operand below the root" IS "a host path the argv names". Both ``--flag value`` and
    ``--flag=value`` are read."""
    named: list[tuple[str, Path]] = []
    for index, item in enumerate(argv):
        if index == 0:
            continue
        flag, value = argv[index - 1], item
        if item.startswith("-") and "=" in item:
            flag, value = item.split("=", 1)
        if os.path.isabs(value) and (Path(value) == root or root in Path(value).parents):
            named.append((flag, Path(value)))
    return named


def _in_view(path: Path, profile, cwd: Path) -> bool:
    """The seat can see ``path``: it is its cwd, a bound input or output, or below one."""
    visible = [Path(cwd), *map(Path, profile.readonly_paths), *map(Path, profile.outputs)]
    return any(path == entry or entry in path.parents for entry in visible)


# ``/bin/sh -c <script> seat <the product's argv after argv[0]>``: the flags reach
# ``_seat_command_profile`` exactly as the product wrote them.
_EXISTS_IN_SEAT = 'for a in "$@"; do case "$a" in "$ROOT"|"$ROOT"/*) [ -e "$a" ] || { echo "MISSING $a"; exit 3; };; esac; done'


def _stand_in(argv, root: Path) -> list[str]:
    script = f'ROOT="{root}"; ' + _EXISTS_IN_SEAT
    return ["/bin/sh", "-c", script, "seat", *argv[1:]]


def _assert_every_named_path_is_bound(argv, *, cwd: Path, root: Path) -> list[tuple[str, Path]]:
    named = _named_host_paths(argv, root)
    with pi._seat_command_profile(_stand_in(argv, root), env={"PATH": "/usr/bin:/bin"}, cwd=cwd,
                                  role=pi.SeatLaunchRole.PROVIDER_ADMIN) as (_owned, profile):
        unbound = [(flag, str(path)) for flag, path in named if not _in_view(path, profile, cwd)]
    assert not unbound, (
        f"the seat's argv names host paths its profile does not bind (flag, path): {unbound}; "
        f"argv: {list(argv)}")
    return named


def _captured_launches(monkeypatch, leg: str, review_dir: Path, out_dir: Path):
    """The argv and cwd the product hands the launch boundary for a brokered ``leg``."""
    seen: list[tuple[list[str], Path]] = []

    def fake_liveness(cmd, **kwargs):
        seen.append((list(cmd), Path(kwargs["cwd"])))
        return pi._LegRun(0, "AGREE", "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    pi._exec_leg(leg, review_dir, out_dir, broker_prompt="P", broker_evidence={})
    assert seen, f"the brokered {leg} leg launched nothing"
    return seen


# --- codex and grok: the argv captured at the real launch boundary ---------------------------

@pytest.mark.parametrize("leg", ["codex", "grok"])
@pytest.mark.parametrize("sandboxed", [True, False], ids=["staged-tree", "no-tree"])
def test_a_brokered_seat_can_see_every_host_path_its_launch_argv_names(tmp_path, monkeypatch,
                                                                       leg, sandboxed):
    if sandboxed:
        tree = _staged_tree(tmp_path)
        review_dir = tree.parent
    else:
        tree, review_dir = None, tmp_path / "sealed-review"
        review_dir.mkdir()
    for argv, cwd in _captured_launches(monkeypatch, leg, review_dir, tmp_path / f"out-{leg}"):
        assert argv[0] == leg
        named = _assert_every_named_path_is_bound(argv, cwd=cwd, root=tmp_path)
        if tree is not None:
            # The instrument's own check: it does find the staged tree in this argv, so a
            # pass above is a statement about that path and not about an empty list.
            assert tree in [path for _flag, path in named], (leg, argv)


# --- the builders the other seats are launched from ------------------------------------------

def _builder_cases(tmp_path: Path):
    tree = _staged_tree(tmp_path)
    review_dir, out_dir = tree.parent, tmp_path / "out"
    out_dir.mkdir()
    live_repo = tmp_path / "live-repo"
    live_repo.mkdir()
    session = "00000000-0000-4000-8000-000000000000"
    return tree, out_dir, {
        "codex-builder-tree": (pi._brokered_codex_command(
            model=None, out_dir=out_dir, out_file=out_dir / "x.txt", codex_effort_args=(),
            staged_tree=tree), True),
        "grok-builder-tree": (pi._brokered_grok_command(
            model=None, out_dir=out_dir, grok_effort_args=(), staged_tree=tree), True),
        "gemini-bounded-tree": (pi._brokered_gemini_command(
            model="gemini-3.8-flash", deadline_s=900.0, staged_tree=tree), True),
        "gemini-bounded-no-tree": (pi._brokered_gemini_command(
            model="gemini-3.8-flash", deadline_s=900.0), False),
        "gemini-heartbeat": (pi._brokered_gemini_command(
            model="gemini-3.8-flash", deadline_s=0.0, monitoring_policy="heartbeat_only"), False),
        "claude-tui-brokered": (pi._broker_claude_tui_command(
            model=None, effort=None, session_id=session), False),
        "claude-print-brokered": (pi._claude_print_seat_command(None, None, brokered=True), False),
        "claude-tui-direct": (pi._claude_tui_command(review_dir, live_repo), True),
        "claude-print-direct": (pi._claude_print_seat_command(
            None, None, brokered=False, add_dirs=(review_dir, tree)), True),
    }


_BUILDER_IDS = (
    "codex-builder-tree", "grok-builder-tree", "gemini-bounded-tree", "gemini-bounded-no-tree",
    "gemini-heartbeat", "claude-tui-brokered", "claude-print-brokered", "claude-tui-direct",
    "claude-print-direct",
)


@pytest.mark.parametrize("case", _BUILDER_IDS)
def test_a_seat_argv_builder_names_only_host_paths_the_profile_binds(tmp_path, case):
    tree, out_dir, cases = _builder_cases(tmp_path)
    assert tuple(cases) == _BUILDER_IDS
    argv, names_the_tree = cases[case]
    named = _assert_every_named_path_is_bound(argv, cwd=out_dir, root=tmp_path)
    assert (tree in [path for _flag, path in named]) is names_the_tree, (case, argv)


# --- and the seat itself agrees, inside the real sandbox ------------------------------------

@needs_owner
@pytest.mark.parametrize("case", ["codex-builder-tree", "grok-builder-tree", "gemini-bounded-tree",
                                  "claude-tui-direct", "claude-print-direct"])
def test_the_launched_seat_finds_every_host_path_its_argv_names(tmp_path, case):
    """Not the profile's own bookkeeping: a process started in the seat's view stats each
    host path the argv names. An unbound flag leaves its path absent there."""
    _tree, out_dir, cases = _builder_cases(tmp_path)
    argv, _names_the_tree = cases[case]
    assert _named_host_paths(argv, tmp_path)
    with pi._seat_command_profile(_stand_in(argv, tmp_path), env={"PATH": "/usr/bin:/bin"},
                                  cwd=out_dir,
                                  role=pi.SeatLaunchRole.PROVIDER_ADMIN) as (owned, profile):
        process = pi.launch_owned(owned, role=pi.SeatLaunchRole.PROVIDER_ADMIN, profile=profile,
                                  cwd=str(out_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  start_new_session=True)
        try:
            out, err = process.communicate(timeout=60)
        finally:
            pi._terminate_process_group(process)
    assert process.returncode == 0, (case, out, err)


def test_the_instrument_reports_a_host_path_named_through_an_unbound_flag(tmp_path):
    """The falsifier of the check itself: a path named through a flag the profile does not
    bind is reported, in both spellings, and a bound one is not."""
    out_dir, tree = tmp_path / "out", tmp_path / "elsewhere" / "tree"
    out_dir.mkdir()
    tree.mkdir(parents=True)
    for argv in (["x", "--no-such-path-flag", str(tree), "-"],
                 ["x", f"--no-such-path-flag={tree}", "-"]):
        assert _named_host_paths(argv, tmp_path) == [("--no-such-path-flag", tree)]
        with pytest.raises(AssertionError, match="names host paths its profile does not bind"):
            _assert_every_named_path_is_bound(argv, cwd=out_dir, root=tmp_path)
    assert _assert_every_named_path_is_bound(
        ["x", "--add-dir", str(tree), "-"], cwd=out_dir, root=tmp_path) == [("--add-dir", tree)]
