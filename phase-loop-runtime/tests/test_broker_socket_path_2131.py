"""A long TMPDIR never fails a brokered leg opaquely (agent-harness#2131).

The broker binds an AF_UNIX socket, whose path Linux caps at 107 bytes. Its private root
is created under the first safe, short base: a private ``$XDG_RUNTIME_DIR``, else the
temp dir, else a root-owned sticky ``/tmp``. A base is safe only when no other account
can replace or redirect any part of its path, and it is measured exactly as it is bound.
With no such base the leg is refused with a typed code before anything is staged. A
standalone ``advisor-board`` keeps a failing leg's private log, and nothing else, in a
bounded private run directory.
"""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import re
import shutil
import stat
import tempfile
import time
import types
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from phase_loop_runtime import leg_log_runs
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

CODE = "seat_broker_socket_path_too_long"
#: The fixed part of the bound pathname: "/" + prefix + 8 hex + "/" + socket name.
SUFFIX_BYTES = len(f"/phase-loop-broker-{'0' * 8}/intended-inference.sock")


@pytest.fixture
def long_tmpdir(tmp_path, monkeypatch):
    path = tmp_path / ("long-tmpdir-" + "x" * 64)
    path.mkdir(mode=0o700)
    assert len(str(path)) >= 80
    monkeypatch.setenv("TMPDIR", str(path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    assert tempfile.gettempdir() == str(path)
    return path


@pytest.fixture
def short_root():
    """A short private directory under ``/tmp`` (root-owned and sticky), for bases."""
    root = Path(tempfile.mkdtemp(prefix="b2131-", dir="/tmp"))
    try:
        yield root
    finally:
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)
        shutil.rmtree(root, ignore_errors=True)


@contextmanager
def _real_broker(tmp_path, **kwargs):
    board = replace(DEFAULT_BOARD, seats=tuple(
        seat for seat in DEFAULT_BOARD.seats if seat.harness != "gemini"))
    token = backing.set_review_instruction_digest("instructions")
    auth = backing.prepare_review_isolation_authorization(
        board, "input", mode="review", monitoring_policy="heartbeat_only")
    backing.activate_review_isolation_authorization(auth, board, "input", mode="review")
    seat = board.seats[0]
    model = backing.harden_subscription_model(seat.harness, seat.model, seat.effort)
    leg = backing.derive_review_leg_authorization(
        auth, "input", harness=seat.harness, model=model, deadline_s=None,
        mode="review", canonical_repo_authority=Path.cwd())
    stage = tmp_path / "stage"
    stage.mkdir()
    for name, content in (("review-bundle.md", "input"), ("review-instructions.md", "instructions")):
        (stage / name).write_text(content)
        (stage / name).chmod(0o400)
    broker = None
    try:
        broker = backing.ParentUnixBroker(leg, harness=seat.harness, model=model,
                                          staged_dir=stage, canonical_repo=Path.cwd(), **kwargs)
        yield broker
    finally:
        if broker is not None:
            broker.close()
        backing.close_review_isolation_authorization(auth)
        backing.reset_review_instruction_digest(token)


def _private(path: Path) -> Path:
    path.mkdir(mode=0o700)
    return path


# -- the socket base -----------------------------------------------------------------


def test_a_long_tmpdir_broker_binds_through_a_short_root(long_tmpdir, tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with _real_broker(tmp_path) as broker:
        assert stat.S_ISSOCK(os.lstat(broker.path).st_mode)
        assert len(os.fsencode(str(broker.path))) <= 107
        assert str(broker.root.parent) == "/tmp"
        assert stat.S_IMODE(broker.root.stat().st_mode) == 0o700
        root = broker.root
    # The cleanup semantics are unchanged: no client launched, so the root is removed.
    assert not root.exists() and broker.evidence["cleanup_root_removed"] is True


def test_a_short_temp_dir_is_used_ahead_of_tmp(short_root, tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("TMPDIR", str(short_root))
    monkeypatch.setattr(tempfile, "tempdir", None)
    assert backing.broker_socket_base() == str(short_root)
    with _real_broker(tmp_path) as broker:
        assert broker.root.parent == short_root and broker.path.is_socket()


def test_a_private_runtime_dir_is_preferred(long_tmpdir, short_root, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short_root))
    with _real_broker(tmp_path) as broker:
        assert broker.root.parent == short_root and broker.path.is_socket()


def _unsafe(kind: str, root: Path) -> tuple[str, str]:
    """(variable, value) naming an unsafe base of ``kind`` under ``root``."""
    real = _private(root / "real")
    if kind == "linked-leaf":
        (root / "link").symlink_to(real)
        return "XDG_RUNTIME_DIR", str(root / "link")
    if kind == "linked-ancestor":
        _private(real / "sub")
        (root / "link").symlink_to(real)
        return "XDG_RUNTIME_DIR", str(root / "link" / "sub")
    if kind == "writable-ancestor":
        open_dir = root / "open"
        open_dir.mkdir()
        _private(open_dir / "priv")
        open_dir.chmod(0o777)
        return "XDG_RUNTIME_DIR", str(open_dir / "priv")
    if kind == "group-readable-runtime":
        real.chmod(0o750)
        return "XDG_RUNTIME_DIR", str(real)
    assert kind == "group-writable-tmpdir"
    real.chmod(0o770)
    return "TMPDIR", str(real)


@pytest.mark.parametrize("kind", ["linked-leaf", "linked-ancestor", "writable-ancestor",
                                  "group-readable-runtime", "group-writable-tmpdir"])
def test_an_unsafe_base_is_passed_over_for_the_next_safe_one(kind, long_tmpdir, short_root,
                                                             monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    variable, value = _unsafe(kind, short_root)
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(tempfile, "tempdir", None)
    assert len(os.fsencode(value)) + SUFFIX_BYTES <= 107  # short: refused for safety alone
    assert backing.broker_socket_base() == "/tmp"


def _base_of(root: Path, total_bytes: int, *, multibyte: bool) -> Path:
    """A private directory under ``root`` whose pathname is exactly ``total_bytes``."""
    need = total_bytes - len(os.fsencode(str(root))) - 1
    name = ("é" * 4 + "a" * (need - 8)) if multibyte else "a" * need
    path = _private(root / name)
    assert len(os.fsencode(str(path))) == total_bytes
    return path


@pytest.mark.parametrize("multibyte", [False, True])
def test_the_exact_byte_boundary_binds_at_107_and_passes_over_108(multibyte, long_tmpdir,
                                                                   short_root, tmp_path,
                                                                   monkeypatch):
    fits = _base_of(short_root, 107 - SUFFIX_BYTES, multibyte=multibyte)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(fits))
    assert backing.broker_socket_base() == str(fits)
    with _real_broker(tmp_path) as broker:
        assert len(os.fsencode(str(broker.path))) == 107 and broker.path.is_socket()
    over = _base_of(short_root, 108 - SUFFIX_BYTES, multibyte=multibyte)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(over))
    assert backing.broker_socket_base() == "/tmp"


def test_a_normalized_spelling_is_measured_and_bound_as_one_pathname(long_tmpdir, short_root,
                                                                     tmp_path, monkeypatch):
    fits = _base_of(short_root, 107 - SUFFIX_BYTES, multibyte=False)
    # 107 bytes only once `/./` and the trailing `/` are collapsed.
    monkeypatch.setenv("XDG_RUNTIME_DIR", f"{short_root}/./{fits.name}/")
    assert backing.broker_socket_base() == str(fits)
    with _real_broker(tmp_path) as broker:
        assert str(broker.path).startswith(str(fits) + "/")
        assert len(os.fsencode(str(broker.path))) == 107 and broker.path.is_socket()


@pytest.mark.parametrize("variable", ["XDG_RUNTIME_DIR", "TMPDIR"])
def test_a_link_before_a_parent_step_is_refused_and_falls_through(variable, long_tmpdir,
                                                                   short_root, monkeypatch):
    """`link/..` reaches the link target's parent in the kernel, not `short_root`: the
    lexical collapse would admit `short_root/runtime`, a directory the variable never
    names. A spelling with `..` is refused and the next safe base is used."""
    elsewhere = _private(_private(short_root / "elsewhere") / "deeper")
    (short_root / "link").symlink_to(elsewhere)
    _private(short_root / "runtime")
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv(variable, f"{short_root}/link/../runtime")
    monkeypatch.setattr(tempfile, "tempdir", None)
    assert backing.broker_socket_base() == "/tmp"


def _no_short_base(tmp_path, monkeypatch):
    runtime = _private(tmp_path / ("long-runtime-" + "y" * 64))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(backing, "_sticky_tmp", lambda: None)


def test_no_short_base_is_the_typed_refusal_with_its_fix(long_tmpdir, tmp_path, monkeypatch):
    _no_short_base(tmp_path, monkeypatch)
    with pytest.raises(ValueError) as caught:
        backing.broker_socket_base()
    assert caught.value.args == (CODE,)
    assert pi._exception_failure(caught.value) == CODE
    assert pi._finalize_leg_detail(pi._exception_failure(caught.value)) == CODE
    notice = seat_jail.render_notice(CODE, "codex:a")
    assert notice is not None and "107-byte" in notice.why and "no usable short base" in notice.why
    assert "56 bytes" in notice.fix and "TMPDIR" in notice.fix and "XDG_RUNTIME_DIR" in notice.fix


def test_a_carried_base_is_rechecked_and_leaves_no_root(long_tmpdir, short_root, tmp_path,
                                                        monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    stale = _private(short_root / "stale")
    with pytest.raises(ValueError) as caught, _real_broker(tmp_path, socket_base=str(stale)):
        pass
    assert caught.value.args == (CODE,)
    assert not list(stale.iterdir())


def test_a_brokered_leg_is_refused_before_any_staging_setup(long_tmpdir, tmp_path, monkeypatch):
    """The leg carries the typed code, refused before a staging root is chosen, never the
    opaque ``AF_UNIX path too long`` once the broker binds."""
    _no_short_base(tmp_path, monkeypatch)

    def staged(*_a, **_k):
        raise AssertionError("staging setup ran before the socket refusal")

    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_policy, "staging_root", staged)
    monkeypatch.setattr(pi, "ParentUnixBroker", staged)
    from phase_loop_runtime.seat_resource_caps import _seat_scope

    with _seat_scope("test:broker-socket-path"):
        spawned = pi._default_spawn(
            "codex", "ARTIFACT", mode="review", model="gpt-test",
            review_authorization=types.SimpleNamespace(staged_tree_sha256=None),
            canonical_repo_authority=tmp_path,
        )
    assert spawned == ("DEGRADED", "", CODE)
    assert pi._finalize_leg_detail(spawned[2]) == CODE


# -- the standalone board keeps only the failing leg's log ------------------------------

OTHER_SEAT_TEXT = "OTHER-SEAT-CONFIDENTIAL-QUOTE"
_REAL_PREPARE = backing.prepare_review_isolation_authorization


_BOARDS: list = []


def _hermetic_board():
    # Composed once, before any test patches the composition authorization seam.
    if not _BOARDS:
        from phase_loop_runtime.advisor_board import composition as comp_mod

        _BOARDS.append(comp_mod.compose_review_board(
            is_available=lambda v: v in {"codex", "gemini", "claude", "grok"}))
    return _BOARDS[0]


def _board_run(where: Path, monkeypatch, *, failing: set[str], spawn_claude=None, json_output=False):
    """Run ``advisor-board --advisory`` through the real CLI, board dispatch and report.
    Only the seat spawn boundary is replaced, under the sanctioned factory control (the
    board's own authorization, minted once and returned again by the factory)."""
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    def spawn(leg, artifact, **_kw):
        if leg == "claude" and spawn_claude is not None:
            return spawn_claude()
        if leg in failing:
            raise OSError("AF_UNIX path too long")
        return ("OK", f"{OTHER_SEAT_TEXT}\nAGREE")

    board = _hermetic_board()
    monkeypatch.setattr(backing, "prepare_review_composition_authorization", lambda: None)
    monkeypatch.setattr(comp_mod, "compose_review_board", lambda *a, **k: board)
    real_prepare = _REAL_PREPARE
    minted: list = []

    def prepare(*a, **k):
        if not minted:
            minted.append(real_prepare(*a, **k))
        return minted[0]

    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", prepare)
    monkeypatch.setattr(pi, "_default_spawn_via_provider", spawn)
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    cwd = where / "no-repo"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    artifact = where / "bundle.md"
    artifact.write_text("review me\n")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        cli_main(["advisor-board", str(artifact), "--advisory", *(["--json"] if json_output else [])])
    return out.getvalue(), err.getvalue()


def test_advisor_board_keeps_only_the_failing_legs_log(tmp_path, monkeypatch):
    out, err = _board_run(tmp_path / "failing", monkeypatch, failing={"codex"})
    [line] = [line for line in err.splitlines() if "[DEGRADED] codex:" in line]
    assert "not retained" not in line, err
    ref = re.search(r"leg-logs/codex-[0-9a-f]{24}\.log", line)
    assert ref is not None, line
    kept = re.search(r"leg failure logs kept in (\S+)", err)
    assert kept is not None, err
    run = Path(kept.group(1))
    assert run.parent == leg_log_runs.runs_parent()
    assert run.is_relative_to(seat_jail.state_home())
    # The run holds the one diagnostic the board output names and its empty completion
    # marker, and nothing else.
    files = sorted(p.relative_to(run).as_posix() for p in run.rglob("*") if not p.is_dir())
    assert files == [".done", ref.group(0)] and (run / ".done").stat().st_size == 0
    assert stat.S_IMODE(run.stat().st_mode) == 0o700
    assert stat.S_IMODE((run / "leg-logs").stat().st_mode) == 0o700
    assert stat.S_IMODE((run / ref.group(0)).stat().st_mode) == 0o600
    assert "AF_UNIX path too long" in (run / ref.group(0)).read_text()
    # No other seat's response is persisted anywhere under the state dir.
    for path in seat_jail.state_home().rglob("*"):
        if path.is_file():
            assert OTHER_SEAT_TEXT not in path.read_text(errors="replace"), path
    # A later board with no failing leg keeps no run of its own.
    _out, err = _board_run(tmp_path / "passing", monkeypatch, failing=set())
    assert "leg failure logs kept" not in err
    assert [p.name for p in leg_log_runs.runs_parent().iterdir() if p.is_dir()] == [run.name]


@pytest.fixture
def jailed_claude_tui(tmp_path, monkeypatch):
    jail = types.SimpleNamespace(leg="claude", provider_argv0="claude", env={})
    seat = pi._JailedSeat(jail=jail, probe_jail=jail, holder_pid=1,
                          token=b"fixture-seat-credential-cY78Nqv51", review_dir=tmp_path,
                          seat_dir=tmp_path)
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, *, snapshots, **kw:
                        shutil.rmtree(snapshots))

    def with_tail(tail, *, code="claude_tui_stalled", model_turn=False):
        journal = b'{"message":{"role":"assistant","model":"fixture"}}\n' if model_turn else b""
        monkeypatch.setattr(pi._seat_uid, "read_in_h", lambda *args: journal)
        monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw:
                            (1, "", pi._HarnessCode(code), tail))

        def spawn():
            sink = []
            status, text = pi._exec_jailed_claude_leg(
                seat, timeout_s=10, backstop_s=20, model=None, effort=None,
                prompt="review", broker_evidence=None, failure_detail_sink=sink)
            return status, text, sink[-1]

        return spawn

    return seat, with_tail


def test_advisor_board_retains_the_screen_tail_for_a_typed_stall(
        tmp_path, monkeypatch, jailed_claude_tui):
    _seat, with_tail = jailed_claude_tui
    screen = "Waiting at the editor"
    private_path = str(tmp_path / "seat-only")
    tail = pi._sanitized_pty_tail(f"\x1b[31m{screen}\x1b[0m {private_path}".encode(),
                                  known=(private_path,))
    out, err = _board_run(tmp_path / "stalled", monkeypatch, failing=set(),
                          spawn_claude=with_tail(tail))
    match = re.search(r"\[DEGRADED\] claude:.*claude_tui_stalled; CLI output: "
                      r"(leg-logs/claude-[0-9a-f]{24}\.log)", err)
    assert match is not None, err
    run, = (p for p in leg_log_runs.runs_parent().iterdir() if p.is_dir())
    log = run / match[1]
    assert sorted(p for p in run.rglob("*") if p.is_file()) == [run / ".done", log]
    assert stat.S_IMODE(log.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert screen in log.read_text()
    assert "\x1b" not in log.read_text() and private_path not in log.read_text()
    assert OTHER_SEAT_TEXT not in log.read_text()
    assert screen not in out + err


def test_advisor_board_refuses_an_unscreened_stall_tail(tmp_path, monkeypatch, jailed_claude_tui):
    seat, with_tail = jailed_claude_tui
    monkeypatch.setattr(pi, "_write_private_leg_log",
                        lambda *args: pytest.fail("refused tail reached the log writer"))
    out, err = _board_run(tmp_path / "refused", monkeypatch, failing=set(),
                          spawn_claude=with_tail(f"Editor: {seat.token.decode()}"))
    assert "claude_seat_token_in_output" in err
    assert "leg-logs/" not in err
    assert seat.token.decode() not in out + err
    assert not any(p.is_dir() for p in leg_log_runs.runs_parent().iterdir())


def test_advisor_board_keeps_the_stall_code_when_no_log_can_be_written(
        tmp_path, monkeypatch, jailed_claude_tui):
    _seat, with_tail = jailed_claude_tui
    monkeypatch.setattr(pi, "_write_private_leg_log", lambda *args: None)
    _out, err = _board_run(tmp_path / "unretained", monkeypatch, failing=set(),
                           spawn_claude=with_tail("Waiting at the editor"))
    assert any(line.endswith(" — claude_tui_stalled") for line in err.splitlines())
    assert "leg-logs/" not in err


def test_workspace_trust_block_preserves_the_board_notice(tmp_path, monkeypatch, jailed_claude_tui):
    _seat, with_tail = jailed_claude_tui
    code = "claude_tui_workspace_trust_blocked"
    out, _err = _board_run(tmp_path / "trust", monkeypatch, failing=set(), json_output=True,
                           spawn_claude=with_tail("Do you trust this folder?", code=code))
    board = json.loads(out)
    claude, = (leg for leg in board["legs"] if leg["leg"] == "claude")
    assert any(n["code"] == code and n["seat_key"] == claude["seat_key"] for n in board["notices"])
    assert any(n["code"] == code and n["seat_key"] == claude["seat_key"] for n in board["refused_seats"])
    assert claude["detail"] == code


def test_typed_log_reference_cannot_suffix_a_mode_line_code(monkeypatch):
    code = "claude_tui_stalled"
    mode_codes = pi._claude_seat_transport.mode_line_codes() | {code}
    monkeypatch.setattr(pi._claude_seat_transport, "mode_line_codes", lambda: mode_codes)
    assert pi._LegFailure(code).rendered(f"leg-logs/claude-{'a' * 24}.log") == code


@pytest.mark.parametrize("code", ["claude_tui_stalled", "claude_tui_missing_canonical_output"])
@pytest.mark.parametrize("model_turn", [False, True], ids=["before-turn", "after-turn"])
def test_jailed_claude_retains_selected_tails_only_before_a_model_turn(
        tmp_path, jailed_claude_tui, code, model_turn):
    _seat, with_tail = jailed_claude_tui
    screen = "Review screen excerpt"
    status, text, failure = with_tail(screen, code=code, model_turn=model_turn)()
    assert (status, text) == ("DEGRADED", "")
    detail = pi._resolve_leg_detail(failure, tmp_path, "claude")
    if model_turn:
        assert detail == code
        assert not (tmp_path / "leg-logs").exists()
    else:
        marker, ref = detail.split("; CLI output: ")
        assert marker == code
        assert (tmp_path / ref).read_text() == screen


def test_prefixed_typed_tail_is_redacted_capped_and_retained(jailed_claude_tui):
    _seat, with_tail = jailed_claude_tui
    credential_shape = "sk-ant-api03-" + "abcdefghij0123456789"
    tail = "discarded start\n" + "ordinary status\n" * 5000 + f"credential: {credential_shape}"
    status, text, failure = with_tail(tail)()
    run = leg_log_runs.LegLogRun.start()
    assert run is not None
    failure = replace(failure, prefix=pi._HarnessCode("leg_execution_failed"))
    leg = pi.PanelLegResult(leg="claude", status=status, text=text,
                            detail=pi._resolve_leg_detail(failure, run.path, "claude"))
    assert leg.detail.startswith("leg_execution_failed: claude_tui_stalled; CLI output: ")
    ref = leg.detail.split("; CLI output: ")[1]
    assert run.finish([leg.detail]) == run.path
    payload = (run.path / ref).read_bytes()
    assert len(payload) == 64 * 1024
    assert payload.endswith(b"credential: <redacted>")
    assert credential_shape.encode() not in payload and b"discarded start" not in payload


def test_an_unpublished_log_is_not_kept(tmp_path):
    run = leg_log_runs.LegLogRun.start()
    assert run is not None
    (run.path / "leg-logs").mkdir(mode=0o700)
    (run.path / "leg-logs" / "codex-partial.log").write_text("half")
    assert run.finish(["unknown failure; CLI output not retained"]) is None
    assert not run.path.exists()


def test_an_unsafe_state_parent_gets_no_run(tmp_path, monkeypatch):
    open_dir = tmp_path / "open"
    open_dir.mkdir()
    open_dir.chmod(0o777)
    try:
        monkeypatch.setenv("XDG_STATE_HOME", str(open_dir / "state"))
        assert leg_log_runs.LegLogRun.start() is None
    finally:
        open_dir.chmod(0o700)


def test_a_state_path_with_a_parent_step_gets_no_run(tmp_path, monkeypatch):
    target = _private(_private(tmp_path / "elsewhere") / "deeper")
    (tmp_path / "link").symlink_to(target)
    monkeypatch.setenv("XDG_STATE_HOME", f"{tmp_path}/link/../state")
    assert leg_log_runs.LegLogRun.start() is None
    assert not (tmp_path / "state").exists() and not (tmp_path / "elsewhere" / "state").exists()


def test_a_linked_state_home_creates_nothing_through_the_link(tmp_path, monkeypatch):
    target = _private(tmp_path / "target")
    (tmp_path / "state-link").symlink_to(target)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state-link"))
    assert leg_log_runs.LegLogRun.start() is None
    assert list(target.iterdir()) == []


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_a_lock_failure_runs_the_board_without_retention(tmp_path, monkeypatch):
    def refuse(*_a, **_k):
        raise OSError(38, "locks not supported")

    monkeypatch.setattr(leg_log_runs, "fcntl", types.SimpleNamespace(
        flock=refuse, LOCK_EX=fcntl.LOCK_EX, LOCK_NB=fcntl.LOCK_NB))
    before = _fd_count()
    assert leg_log_runs.LegLogRun.start() is None
    assert _fd_count() == before
    parent = leg_log_runs.runs_parent()
    assert not parent.exists() or not [p for p in parent.iterdir() if p.is_dir()]
    _out, err = _board_run(tmp_path / "board", monkeypatch, failing={"codex"})
    [line] = [line for line in err.splitlines() if "[DEGRADED] codex:" in line]
    assert "CLI output not retained" in line and "leg failure logs kept" not in err


def test_a_held_parent_lock_bounds_the_wait_and_the_board_still_runs(tmp_path, monkeypatch):
    """A holder that never releases (a stopped process) costs only retention: start and
    finish each give up after the bounded wait instead of blocking the board."""
    first = leg_log_runs.LegLogRun.start()
    assert first is not None
    first.finish([])  # no log named: the run is removed, the parent stays
    parent = leg_log_runs.runs_parent()
    holder = os.open(parent / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        monkeypatch.setattr(leg_log_runs, "PARENT_LOCK_WAIT_S", 0.2)
        began = time.monotonic()
        assert leg_log_runs.LegLogRun.start() is None
        assert time.monotonic() - began < 5
        _out, err = _board_run(tmp_path / "board", monkeypatch, failing={"codex"})
        assert "[DEGRADED] codex:" in err
    finally:
        os.close(holder)


def test_the_finishing_run_counts_toward_the_cap(tmp_path):
    parent = leg_log_runs.runs_parent()
    run = leg_log_runs.LegLogRun.start()
    assert run is not None
    _completed_runs(parent, leg_log_runs.KEEP_RUNS, newest=time.time() - 60)
    (run.path / "leg-logs").mkdir(mode=0o700)
    (run.path / "leg-logs" / "codex-0.log").write_text("failed")
    kept = run.finish(["failed; CLI output: leg-logs/codex-0.log"])
    assert kept is not None
    runs = [p for p in parent.iterdir() if p.is_dir() and p.name.startswith("advisor-board-")]
    assert len(runs) == leg_log_runs.KEEP_RUNS and kept in runs


def _completed_runs(parent: Path, count: int, *, newest: float) -> list[Path]:
    runs = []
    for index in range(count):
        run = _private(parent / f"advisor-board-done{index:04d}")
        (run / ".done").touch()
        stamp = newest - index * 60
        os.utime(run / ".done", (stamp, stamp))
        os.utime(run, (stamp, stamp))
        runs.append(run)
    return runs


def test_a_pruner_never_removes_a_run_that_completes_during_its_pass(tmp_path, monkeypatch):
    """The pruner lists while the board is running (its directory old, ranked last); the
    board then completes. Under the parent lock the completion waits for the pass, the
    running board is skipped, and it is ranked by completion afterwards."""
    import threading

    run = leg_log_runs.LegLogRun.start()
    assert run is not None
    (run.path / "leg-logs").mkdir(mode=0o700)
    (run.path / "leg-logs" / "codex-0.log").write_text("AF_UNIX path too long")
    old = time.time() - 3600
    os.utime(run.path, (old, old))
    _completed_runs(run.path.parent, leg_log_runs.KEEP_RUNS, newest=time.time() - 60)
    reached, release = threading.Event(), threading.Event()
    real_held = leg_log_runs._held

    def paused_held(candidate):
        if candidate == run.path and not reached.is_set():
            reached.set()
            release.wait(5)
        return real_held(candidate)

    monkeypatch.setattr(leg_log_runs, "_held", paused_held)
    pruner = threading.Thread(target=leg_log_runs.prune, args=(run.path.parent,),
                              kwargs={"keep": leg_log_runs.KEEP_RUNS,
                                      "max_age_s": leg_log_runs.MAX_AGE_S})
    pruner.start()
    assert reached.wait(5)
    kept: list = []
    finisher = threading.Thread(target=lambda: kept.append(
        run.finish(["unknown failure; CLI output: leg-logs/codex-0.log"])))
    finisher.start()
    finisher.join(0.5)
    release.set()
    pruner.join(5)
    finisher.join(5)
    assert kept == [run.path] and (run.path / "leg-logs" / "codex-0.log").is_file()


def test_a_pruner_never_sees_a_half_registered_run(tmp_path, monkeypatch):
    """Between creating a run directory and locking its marker, a pruner (here keeping
    none) waits on the parent lock instead of taking the new run for an abandoned one."""
    import threading

    reached, release = threading.Event(), threading.Event()
    real_os = os

    class PausingOs:
        def __getattr__(self, name):
            return getattr(real_os, name)

        @staticmethod
        def mkdir(path, *args, **kwargs):
            real_os.mkdir(path, *args, **kwargs)
            if real_os.path.basename(real_os.fspath(path)).startswith("advisor-board-"):
                reached.set()
                release.wait(5)

    leg_log_runs.runs_parent().mkdir(mode=0o700, parents=True)
    monkeypatch.setattr(leg_log_runs, "os", PausingOs())
    started: list = []
    starter = threading.Thread(target=lambda: started.append(leg_log_runs.LegLogRun.start()))
    starter.start()
    assert reached.wait(5)
    pruner = threading.Thread(target=leg_log_runs.prune, args=(leg_log_runs.runs_parent(),),
                              kwargs={"keep": 0, "max_age_s": leg_log_runs.MAX_AGE_S})
    pruner.start()
    pruner.join(0.5)
    release.set()
    starter.join(5)
    pruner.join(5)
    [run] = started
    assert run is not None and run.path.is_dir() and (run.path / ".active").exists()
    run.finish([])


def test_kept_runs_are_bounded_and_a_held_run_is_never_removed(tmp_path):
    parent = _private(tmp_path / "board-runs")
    now = time.time()
    runs = []
    for index in range(leg_log_runs.KEEP_RUNS + 5):
        run = _private(parent / f"advisor-board-{index:04d}")
        os.utime(run, (now - index * 60, now - index * 60))
        runs.append(run)
    old = _private(parent / "advisor-board-old")
    os.utime(old, (now - leg_log_runs.MAX_AGE_S - 60,) * 2)
    held = runs[-1]
    fd = os.open(held / ".active", os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    stamp = now - (len(runs) - 1) * 60
    os.utime(held, (stamp, stamp))  # creating its lock moved it; it stays the oldest kept
    try:
        leg_log_runs.prune(parent, keep=leg_log_runs.KEEP_RUNS, max_age_s=leg_log_runs.MAX_AGE_S)
    finally:
        os.close(fd)
    left = {p.name for p in parent.iterdir()} - {".lock"}
    assert {r.name for r in runs[:leg_log_runs.KEEP_RUNS]} <= left
    assert held.name in left and old.name not in left
    assert len(left) == leg_log_runs.KEEP_RUNS + 1
