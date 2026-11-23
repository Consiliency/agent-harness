"""A long TMPDIR never fails a brokered leg opaquely (agent-harness#2131).

The broker binds an AF_UNIX socket, whose path Linux caps at 107 bytes. Its private root
is created under a short base (a private ``$XDG_RUNTIME_DIR``, else the temp dir, else
``/tmp``) chosen by the socket path's length, and when no base fits, the leg is refused
with a typed code before anything is staged. A standalone ``advisor-board`` gives its legs
a private run directory, so an unknown failure's reason is kept in a leg log.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import stat
import tempfile
import types
import unittest.mock
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

CODE = "seat_broker_socket_path_too_long"


def _long_private_dir(tmp_path: Path) -> Path:
    path = tmp_path / ("long-tmpdir-" + "x" * 64)
    path.mkdir(mode=0o700)
    assert len(str(path)) >= 80
    return path


@pytest.fixture
def long_tmpdir(tmp_path, monkeypatch):
    path = _long_private_dir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    assert tempfile.gettempdir() == str(path)
    return path


@contextmanager
def _real_broker(tmp_path):
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
                                          staged_dir=stage, canonical_repo=Path.cwd())
        yield broker
    finally:
        if broker is not None:
            broker.close()
        backing.close_review_isolation_authorization(auth)
        backing.reset_review_instruction_digest(token)


def test_a_long_tmpdir_broker_binds_through_a_short_root(long_tmpdir, tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with _real_broker(tmp_path) as broker:
        assert stat.S_ISSOCK(os.lstat(broker.path).st_mode)
        assert len(os.fsencode(str(broker.path))) <= 107
        assert not str(broker.root).startswith(str(long_tmpdir))
        assert stat.S_IMODE(broker.root.stat().st_mode) == 0o700
        root = broker.root
    # The cleanup semantics are unchanged: no client launched, so the root is removed.
    assert not root.exists() and broker.evidence["cleanup_root_removed"] is True


def test_a_private_runtime_dir_is_preferred(long_tmpdir, tmp_path, monkeypatch):
    runtime = Path(tempfile.mkdtemp(prefix="rt-", dir="/tmp"))
    try:
        runtime.chmod(0o700)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        with _real_broker(tmp_path) as broker:
            assert broker.root.parent == runtime and broker.path.is_socket()
        # A runtime dir others can write is never used.
        runtime.chmod(0o755)
        assert backing.broker_socket_base() != str(runtime)
    finally:
        runtime.chmod(0o700)
        for child in runtime.iterdir():
            child.rmdir()
        runtime.rmdir()


def _no_short_base(tmp_path, monkeypatch):
    runtime = tmp_path / ("long-runtime-" + "y" * 64)
    runtime.mkdir(mode=0o700)
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
    assert notice is not None and "107" in notice.why
    assert "TMPDIR" in notice.fix and "XDG_RUNTIME_DIR" in notice.fix


def test_a_brokered_leg_is_refused_before_staging(long_tmpdir, tmp_path, monkeypatch):
    """The leg carries the typed code, refused before anything is staged, never the
    opaque ``AF_UNIX path too long`` once the broker binds."""
    _no_short_base(tmp_path, monkeypatch)

    def staged(*_a, **_k):
        raise AssertionError("staged before the socket refusal")

    def public_entry_only(*_a, staged_dir=None, **_k):
        # The public-entry check runs first; the post-staging one names a staged dir.
        if staged_dir is not None:
            staged()

    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    monkeypatch.setattr(pi._sandbox_policy, "staging_root", lambda: staging)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", staged)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", public_entry_only)
    monkeypatch.setattr(pi, "ParentUnixBroker", staged)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (None, [], None))
    from phase_loop_runtime.seat_resource_caps import _seat_scope

    with _seat_scope("test:broker-socket-path"):
        spawned = pi._default_spawn(
            "codex", "ARTIFACT", mode="review", model="gpt-test",
            review_authorization=types.SimpleNamespace(staged_tree_sha256=None),
            canonical_repo_authority=tmp_path,
        )
    assert spawned == ("DEGRADED", "", CODE)
    assert pi._finalize_leg_detail(spawned[2]) == CODE
    assert not list(staging.rglob("review-bundle.md"))


def test_advisor_board_keeps_a_failing_legs_reason(tmp_path, monkeypatch):
    """The board's exception path (``_resolve_leg_detail(_exception_failure(exc),
    stream_dir, ...)``) gets a private stream dir from the standalone command, so the
    reason lands in a 0600 leg log named by the board output."""
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    seen: dict[str, object] = {}

    def fake_invoke_board(board, artifact, **kwargs):
        stream_dir = kwargs.get("stream_dir")
        seen["stream_dir"] = stream_dir
        detail = pi._resolve_leg_detail(
            pi._exception_failure(OSError("AF_UNIX path too long")), stream_dir, "codex:a")
        return pi.PanelResult(legs=(
            pi.PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:a"),
            pi.PanelLegResult(leg="gemini", status="OK", text="AGREE", seat_key="gemini:a"),
            pi.PanelLegResult(leg="claude", status="OK", text="AGREE", seat_key="claude:a"),
            pi.PanelLegResult(leg="codex", status="ERROR", text="", detail=detail,
                              seat_key="codex:a"),
        ))

    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    real_compose = comp_mod.compose_review_board
    with (
        unittest.mock.patch.object(comp_mod, "compose_review_board", side_effect=lambda *a, **k: real_compose(
            is_available=lambda v: v in {"codex", "gemini", "claude", "grok"})),
        unittest.mock.patch.object(pi, "invoke_board", side_effect=fake_invoke_board),
    ):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            cli_main(["advisor-board", str(artifact)])
    stream_dir = seen["stream_dir"]
    assert stream_dir is not None, "advisor-board gave its legs no stream dir"
    stream_dir = Path(stream_dir)
    assert stat.S_IMODE(stream_dir.stat().st_mode) == 0o700
    assert stream_dir.is_relative_to(seat_jail.state_home())
    lines = [line for line in err.getvalue().splitlines() if "codex:a" in line]
    assert lines and "not retained" not in err.getvalue(), err.getvalue()
    ref = re.search(r"leg-logs/codex-[0-9a-f]{24}\.log", lines[0])
    assert ref is not None, lines[0]
    log = stream_dir / ref.group(0)
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert "AF_UNIX path too long" in log.read_text()
    assert str(stream_dir) in err.getvalue()


def test_a_board_with_no_leg_log_leaves_no_run_dir(tmp_path):
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    seen: dict[str, object] = {}

    def fake_invoke_board(board, artifact, **kwargs):
        seen["stream_dir"] = kwargs.get("stream_dir")
        return pi.PanelResult(legs=tuple(
            pi.PanelLegResult(leg=leg, status="OK", text="AGREE", seat_key=f"{leg}:a")
            for leg in ("grok", "gemini", "claude", "codex")))

    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    real_compose = comp_mod.compose_review_board
    with (
        unittest.mock.patch.object(comp_mod, "compose_review_board", side_effect=lambda *a, **k: real_compose(
            is_available=lambda v: v in {"codex", "gemini", "claude", "grok"})),
        unittest.mock.patch.object(pi, "invoke_board", side_effect=fake_invoke_board),
    ):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli_main(["advisor-board", str(artifact)])
    assert seen["stream_dir"] is not None and not Path(seen["stream_dir"]).exists()
