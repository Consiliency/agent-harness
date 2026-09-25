"""agent-harness#1001: president rung launches run under the review seats' isolation.

Every non-native rung launch goes through egress isolation, a single-use broker
capability carrying the PRESIDENT operation, and the real ``ParentUnixBroker``; under
``heartbeat_only`` it runs with a ``_ReviewMonitor`` (no model-thinking deadline, no
silence kill). The provider transport is observed at ``PresidentInvoke._transport``,
which sits INSIDE the broker (not part of the injected-seam predicate), so the broker,
egress and lease below are all real.

Not part of the PRESROUTE SL-0 frozen corpus.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from phase_loop_runtime import panel_invoker, president_adapter, sandbox_egress
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

RULING = "FINDING F001: DEFERRED — ok\nFORCING DECISION: LAND"
# fable = the Claude rung outside Claude Code (base_env={} here), brokered like the rest.
PROVIDER_RUNGS = ("sol", "fable", "grok", "gemini")


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("repo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    return repo


needs_egress = pytest.mark.skipif(
    not sandbox_egress.egress_isolation_available(),
    reason="this host cannot enforce egress isolation (sandbox_egress.egress_isolation_available() is False)",
)


def _observe(seen: list[dict[str, object]]):
    def transport(self, harness, route_model, prompt, stage, out_dir, *, monitor=None, latch=None):
        seen.append({
            "harness": harness,
            "monitor": monitor,
            "latch": latch,
            "prefix": tuple(panel_invoker._EGRESS_LAUNCH_PREFIX.get()),
            "thread": threading.current_thread().name,
            "stage": sorted(p.name for p in stage.iterdir()),
        })
        return 0, RULING, ""
    return transport


@needs_egress
@pytest.mark.parametrize("rung", PROVIDER_RUNGS)
def test_a_heartbeat_rung_launches_under_monitor_broker_and_egress(tmp_path, rung):
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    brokers: list[backing.ParentUnixBroker] = []
    real_broker = backing.ParentUnixBroker

    def spy_broker(leg, **kwargs):
        broker = real_broker(leg, **kwargs)
        brokers.append(broker)
        return broker

    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)), patch.object(
        backing, "ParentUnixBroker", spy_broker
    ):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), stream_dir=tmp_path / "stream",
            base_env={}, monitoring_policy="heartbeat_only",
        )
        response = seam(rung, "F001: [x] the lock is never released")
    assert response["status"] == "ok" and response["text"] == RULING
    assert len(seen) == 1 and len(brokers) == 1
    observed = seen[0]
    monitor = observed["monitor"]
    # heartbeat: a monitor, no model deadline, no silence deadline
    assert isinstance(monitor, panel_invoker._ReviewMonitor)
    assert monitor.record["model_deadline_s"] is None and monitor.record["silence_deadline_s"] is None
    # isolation: a non-empty egress prefix reached the transport, inside the broker
    assert observed["prefix"], "the rung launched without an egress prefix"
    assert observed["latch"] is not None
    # the broker's capability carries the PRESIDENT operation, never the review one
    leg = brokers[0].authorization
    assert leg.operation == backing.PRESIDENT_OPERATION_V1
    assert leg.monitoring_policy == "heartbeat_only"
    assert brokers[0].evidence["child_quiescent"] is True
    # the monitor record is filed under the stream
    assert list((tmp_path / "stream" / "president-monitoring").rglob("rung-*.json"))


@needs_egress
def test_a_bounded_rung_is_brokered_and_isolated_too(tmp_path):
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), base_env={}, monitoring_policy="bounded",
        )
        response = seam("grok", "F001: [x] y")
    assert response["status"] == "ok"
    assert seen[0]["monitor"] is None and seen[0]["prefix"]


def test_no_canonical_repository_is_a_typed_refusal_before_any_launch(tmp_path):
    seen: list[dict[str, object]] = []
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(tmp_path / "not-a-repo"), base_env={},
            monitoring_policy="heartbeat_only",
        )
        response = seam("sol", "F001: [x] y")
    assert seen == []
    assert response["status"] == "failed" and response["code"] == "president_invocation_failed"
    assert "canonical repository" in response["detail"]


def test_unavailable_egress_is_a_typed_refusal_before_any_launch(tmp_path, monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), base_env={}, monitoring_policy="heartbeat_only",
        )
        response = seam("grok", "F001: [x] y")
    assert seen == []
    assert response["status"] == "failed"
    assert "egress" in response["detail"].lower()


@needs_egress
def test_a_cancelled_operation_never_launches(tmp_path):
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    cancel = threading.Event()
    cancel.set()
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), base_env={}, monitoring_policy="heartbeat_only",
        )
        seam.cancel_event = cancel
        with pytest.raises(panel_invoker.PresidentPolicyError) as excinfo:
            seam("grok", "F001: [x] y")
    assert seen == []
    # a cancelled operation stops the walk: a typed refusal, never a descent to the next rung
    assert excinfo.value.code == president_adapter.PRESIDENT_OPERATION_CANCELLED
    assert excinfo.value.code in panel_invoker._PRESIDENT_REFUSAL_CODES


def test_the_president_leg_capability_is_single_use_and_policy_bound(tmp_path):
    repo = _git_repo(tmp_path)
    brief = "F001: [x] y"
    auth = backing.prepare_president_isolation_authorization(
        DEFAULT_BOARD, brief, canonical_repo_authority=repo, monitoring_policy="heartbeat_only",
    )
    route = dict(auth.routes)["grok"]
    with pytest.raises(ValueError, match="not active"):
        backing.derive_president_leg_authorization(
            auth, DEFAULT_BOARD, brief, harness="grok", model=route, deadline_s=None,
            instructions_sha256="0" * 64, canonical_repo_authority=repo,
        )
    backing.activate_president_isolation_authorization(
        auth, DEFAULT_BOARD, brief, canonical_repo_authority=repo
    )
    with pytest.raises(ValueError, match="invalid HARDEN president leg authority"):
        backing.derive_president_leg_authorization(  # a deadline under heartbeat_only
            auth, DEFAULT_BOARD, brief, harness="grok", model=route, deadline_s=1800.0,
            instructions_sha256="0" * 64, canonical_repo_authority=repo,
        )
    leg = backing.derive_president_leg_authorization(
        auth, DEFAULT_BOARD, brief, harness="grok", model=route, deadline_s=None,
        instructions_sha256="0" * 64, canonical_repo_authority=repo,
    )
    assert leg.operation == backing.PRESIDENT_OPERATION_V1
    with pytest.raises(ValueError, match="already consumed"):
        backing.derive_president_leg_authorization(
            auth, DEFAULT_BOARD, brief, harness="grok", model=route, deadline_s=None,
            instructions_sha256="0" * 64, canonical_repo_authority=repo,
        )
    backing.close_president_isolation_authorization(auth)
    with pytest.raises(ValueError):
        backing.activate_president_isolation_authorization(
            auth, DEFAULT_BOARD, brief, canonical_repo_authority=repo
        )


def test_invoke_board_binds_its_operation_cancel_to_the_president_seam(tmp_path):
    # The board's cancellation reaches the president's heartbeat monitor.
    seen: dict[str, object] = {}
    real = president_adapter.build_president_invoke

    def capture(*args, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after wiring")

    cancel = threading.Event()
    with patch.object(president_adapter, "build_president_invoke", capture):
        with pytest.raises(RuntimeError, match="stop after wiring"):
            panel_invoker.invoke_board(
                DEFAULT_BOARD, "artifact", landing_tier="production_code",
                base_env={"CLAUDECODE": "1"}, repo_dir=str(tmp_path), cancel_event=cancel,
            )
    assert seen.get("cancel_event") is cancel
    assert real is president_adapter.build_president_invoke


def test_the_claude_rung_hands_the_broker_latch_to_the_tui_session(tmp_path):
    # native seat r1 B1: the broker's stop path must reach the Claude process.
    latch = panel_invoker._ProviderQuiescenceLatch()
    monitor = panel_invoker._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event())
    seen: dict[str, object] = {}

    def spy_session(**kwargs):
        seen.update(kwargs)
        return 0, RULING, "", ""

    seam = president_adapter.build_president_invoke(DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={})
    with patch.object(panel_invoker, "_run_claude_tui_session", spy_session):
        seam._launch_claude("claude-opus-5-5", "F001: [x] y", tmp_path, monitor=monitor, latch=latch)
    assert seen["quiescence_latch"] is latch and seen["review_monitor"] is monitor
    # and the brokered transport routes the latch to the Claude launch
    handed: dict[str, object] = {}

    def spy_launch(self, route, prompt, out_dir, *, monitor=None, latch=None):
        handed.update(monitor=monitor, latch=latch)
        return 0, RULING, ""

    with patch.object(president_adapter.PresidentInvoke, "_launch_claude", spy_launch):
        seam._transport("claude", "claude-opus-5-5", "F001: [x] y", tmp_path, tmp_path,
                        monitor=monitor, latch=latch)
    assert handed == {"monitor": monitor, "latch": latch}


@pytest.mark.parametrize("mode,stop_reason,expected_log", [
    ("president", "end_turn", "claude_tui_broker_terminal_nonconforming"),
    ("president", None, "review_operation_cancelled"),
    ("review", "end_turn", "review_operation_cancelled"),
])
def test_terminal_nonconforming_claude_turn_reaches_president_reask(
    tmp_path, monkeypatch, mode, stop_reason, expected_log,
):
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_SUBMIT_DELAY_S", .1)
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_READY_QUIESCENCE_S", .05)
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_TRANSCRIPT_INTERVAL_S", .05)
    cancel = threading.Event()
    monitor = panel_invoker._ReviewMonitor(tmp_path / "monitor.json", "fixture", 0, cancel)
    marker = tmp_path / "terminal-written"
    controller_fired = threading.Event()
    script = r'''
import json, os, sys, time, tty
from pathlib import Path
tty.setraw(0)
print("Claude Code ready for your message", flush=True)
wire = b""
while not wire.endswith(b"\x1bOM"):
    wire += os.read(0, 65536)
Path("owned.jsonl").write_text(json.dumps({"type": "assistant", "uuid": "fixture-record",
    "message": {"id": "fixture-message", "role": "assistant", "stop_reason": None if sys.argv[1] == "null" else sys.argv[1],
                "content": [{"type": "text", "text": "I think it is fine"}]}}) + "\n")
Path("terminal-written").touch()
while True: time.sleep(.1)
'''

    def cancel_if_not_returned():
        until = time.monotonic() + 5  # synthetic fixture startup only
        while not marker.exists() and time.monotonic() < until:
            time.sleep(.01)
        if not cancel.wait(.5):
            controller_fired.set()
            cancel.set()

    controller = threading.Thread(target=cancel_if_not_returned)
    controller.start()
    launched = []
    real_launch = panel_invoker.launch_provider

    def capture_launch(*args, **kwargs):
        proc = real_launch(*args, **kwargs)
        launched.append(proc)
        return proc

    try:
        with patch.object(panel_invoker, "launch_provider", capture_launch):
            rc, text, log, _ = panel_invoker._run_claude_tui_session(
                command=[sys.executable, "-c", script, "null" if stop_reason is None else stop_reason],
                cwd=tmp_path, prompt="rule on F001", output_file=tmp_path / "president.txt",
                timeout_s=1, env={"PATH": "/usr/bin:/bin"}, mode=mode, backstop_s=1,
                review_monitor=monitor, allow_transcript_final=True,
                broker_transcript_path=tmp_path / "owned.jsonl",
            )
    finally:
        cancel.set()
        controller.join(5)
    assert marker.exists()
    assert len(launched) == 1 and launched[0].poll() is not None
    assert log == expected_log
    if expected_log == "claude_tui_broker_terminal_nonconforming":
        assert rc == 0 and text == "I think it is fine"
        assert not controller_fired.is_set()
    else:
        assert rc != 0


def test_cancel_wins_over_terminal_nonconforming_process_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_SUBMIT_DELAY_S", .1)
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_READY_QUIESCENCE_S", .05)
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_TRANSCRIPT_INTERVAL_S", 60)
    cancel = threading.Event()
    monitor = panel_invoker._ReviewMonitor(tmp_path / "monitor.json", "fixture", 0, cancel)
    marker = tmp_path / "terminal-written"
    real_select = panel_invoker.select.select
    real_extract = panel_invoker._final_assistant_text_from_jsonl
    real_launch = panel_invoker.launch_provider
    launched = []

    def capture_launch(*args, **kwargs):
        proc = real_launch(*args, **kwargs)
        launched.append(proc)
        return proc

    def no_eof_after_terminal(readers, writers, errors, timeout):
        if marker.exists():
            time.sleep(.01)
            return [], [], []
        return real_select(readers, writers, errors, timeout)

    def cancel_at_final_read(path, *, require_terminal=False):
        text = real_extract(path, require_terminal=require_terminal)
        if require_terminal and text:
            cancel.set()
        return text

    script = r'''
import json, os, sys, time, tty
from pathlib import Path
tty.setraw(0)
print("Claude Code ready for your message", flush=True)
wire = b""
while not wire.endswith(b"\x1bOM"):
    wire += os.read(0, 65536)
Path("owned.jsonl").write_text(json.dumps({"type": "assistant", "uuid": "fixture-record",
    "message": {"id": "fixture-message", "role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "I think it is fine"}]}}) + "\n")
Path("terminal-written").touch()
time.sleep(.05)
'''
    with patch.object(panel_invoker.select, "select", no_eof_after_terminal), patch.object(
        panel_invoker, "_final_assistant_text_from_jsonl", cancel_at_final_read,
    ), patch.object(
        panel_invoker, "launch_provider", capture_launch,
    ):
        rc, text, log, _ = panel_invoker._run_claude_tui_session(
            command=[sys.executable, "-c", script], cwd=tmp_path, prompt="rule on F001",
            output_file=tmp_path / "president.txt", timeout_s=10, env={"PATH": "/usr/bin:/bin"},
            mode="president", backstop_s=10, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=tmp_path / "owned.jsonl",
        )
    assert marker.exists()
    assert rc != 0 and text == "" and log == "review_operation_cancelled", (rc, text, log)
    assert len(launched) == 1 and launched[0].poll() is not None


def test_the_seam_predicate_does_not_depend_on_import_order():
    # native seat r1 F1: the production launch site is captured in panel_invoker itself.
    assert panel_invoker._PRODUCTION_LAUNCH_PROVIDER is panel_invoker.launch_provider
    assert not president_adapter._injected_president_seam()
    with patch.object(panel_invoker, "launch_provider", lambda *a, **k: None):
        assert president_adapter._injected_president_seam()
    assert not president_adapter._injected_president_seam()


@needs_egress
@pytest.mark.parametrize("rung", PROVIDER_RUNGS)
def test_heartbeat_never_bypasses_the_broker_for_a_forwarding_launch_site(tmp_path, rung):
    # board r1 codex B1 / grok B1: a wrapper around launch_provider must not buy an
    # unbrokered, unmonitored heartbeat launch.
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    real = panel_invoker.launch_provider
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)), patch.object(
        panel_invoker, "launch_provider", lambda *a, **k: real(*a, **k)
    ):
        assert president_adapter._injected_president_seam()
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), base_env={}, monitoring_policy="heartbeat_only",
        )
        response = seam(rung, "F001: [x] y")
    assert response["status"] == "ok"
    assert isinstance(seen[0]["monitor"], panel_invoker._ReviewMonitor) and seen[0]["prefix"]


def test_an_empty_egress_prefix_is_refused_even_when_egress_is_optional(tmp_path, monkeypatch):
    # board r1 codex B2: the authorization declares no network egress.
    from contextlib import contextmanager

    @contextmanager
    def no_namespace(*args, **kwargs):
        yield ()

    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: False)
    monkeypatch.setattr(sandbox_egress, "isolated_network", no_namespace)
    repo = _git_repo(tmp_path)
    seen: list[dict[str, object]] = []
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(repo), base_env={}, monitoring_policy="bounded",
        )
        response = seam("grok", "F001: [x] y")
    assert seen == []
    assert response["status"] == "failed" and "egress isolation unavailable" in response["detail"]


@pytest.mark.parametrize("policy", ["bounded", "heartbeat_only"])
def test_a_cancelled_operation_refuses_before_any_launch_under_either_policy(tmp_path, policy):
    # board r1 grok B2: bounded cancellation refuses too, typed, before any effect.
    seen: list[dict[str, object]] = []
    cancel = threading.Event()
    cancel.set()
    with patch.object(president_adapter.PresidentInvoke, "_transport", _observe(seen)):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(_git_repo(tmp_path)), base_env={},
            monitoring_policy=policy, cancel_event=cancel,
        )
        with pytest.raises(panel_invoker.PresidentPolicyError) as excinfo:
            seam("grok", "F001: [x] y")
    assert seen == [] and excinfo.value.code == president_adapter.PRESIDENT_OPERATION_CANCELLED


@pytest.mark.parametrize("policy", ["bounded", "heartbeat_only"])
def test_a_cancelled_operation_refuses_before_a_native_fill(tmp_path, policy):
    # board r2 codex B1: the native (Claude Code) Claude rung is behind the same guard.
    cancel = threading.Event()
    cancel.set()
    seam = president_adapter.build_president_invoke(
        DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={"CLAUDECODE": "1"},
        monitoring_policy=policy, cancel_event=cancel,
    )
    with pytest.raises(panel_invoker.PresidentPolicyError) as excinfo:
        seam("fable", "F001: [x] y")
    assert excinfo.value.code == president_adapter.PRESIDENT_OPERATION_CANCELLED
    assert [a.status for a in seam.attempts] == ["cancelled"]


def test_a_launch_ended_by_cancellation_is_a_cancellation_not_a_rung_failure(tmp_path):
    cancel = threading.Event()

    def cancelled_launch(self, rung, seat, harness, prompt):
        cancel.set()  # the board cancels while the rung runs
        return {"status": "failed", "code": "president_invocation_failed", "detail": "ended"}

    seam = president_adapter.build_president_invoke(
        DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}, cancel_event=cancel,
    )
    with patch.object(president_adapter.PresidentInvoke, "_launch", cancelled_launch):
        with pytest.raises(panel_invoker.PresidentPolicyError) as excinfo:
            seam("grok", "F001: [x] y")
    assert excinfo.value.code == president_adapter.PRESIDENT_OPERATION_CANCELLED


_TERMINAL_CHILD = r'''
import json, os, sys, time, tty
from pathlib import Path
tty.setraw(0)
print("Claude Code ready for your message", flush=True)
wire = b""
while not wire.endswith(b"\x1bOM"):
    wire += os.read(0, 65536)
Path("owned.jsonl").write_text(json.dumps({"type": "assistant", "uuid": "fixture-record",
    "message": {"id": "fixture-message", "role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "I think it is fine"}]}}) + "\n")
Path("terminal-written").touch()
if sys.argv[1] == "eof":
    sys.exit(0)  # the PTY hangs up; the read path sees EOF before the loop polls the process
while True:
    time.sleep(.1)
'''


def _run_terminal_child(tmp_path, monkeypatch, *, shape, interval_s, cancel_on_final_read):
    # agent-harness#1017 r1: pin the PTY-EOF nonconforming return and the cancellation
    # re-checks at the EOF and idle-poll broker-final sites.
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_SUBMIT_DELAY_S", .1)
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_READY_QUIESCENCE_S", .05)
    monkeypatch.setattr(panel_invoker, "_CLAUDE_TUI_TRANSCRIPT_INTERVAL_S", interval_s)
    cancel = threading.Event()
    monitor = panel_invoker._ReviewMonitor(tmp_path / "monitor.json", "fixture", 0, cancel)
    real_extract = panel_invoker._final_assistant_text_from_jsonl
    real_launch = panel_invoker.launch_provider
    launched = []

    def capture_launch(*args, **kwargs):
        proc = real_launch(*args, **kwargs)
        launched.append(proc)
        return proc

    def extract(path, *, require_terminal=False):
        text = real_extract(path, require_terminal=require_terminal)
        if cancel_on_final_read and require_terminal and text:
            cancel.set()  # cancellation lands during the final read
        return text

    with patch.object(panel_invoker, "_final_assistant_text_from_jsonl", extract), patch.object(
        panel_invoker, "launch_provider", capture_launch,
    ):
        result = panel_invoker._run_claude_tui_session(
            command=[sys.executable, "-c", _TERMINAL_CHILD, shape], cwd=tmp_path, prompt="rule on F001",
            output_file=tmp_path / "president.txt", timeout_s=10, env={"PATH": "/usr/bin:/bin"},
            mode="president", backstop_s=10, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=tmp_path / "owned.jsonl",
        )
    assert (tmp_path / "terminal-written").exists()
    assert len(launched) == 1 and launched[0].poll() is not None  # reaped
    return result


def test_terminal_nonconforming_turn_is_returned_at_pty_eof(tmp_path, monkeypatch):
    rc, text, log, _ = _run_terminal_child(
        tmp_path, monkeypatch, shape="eof", interval_s=60, cancel_on_final_read=False)
    assert (rc, text, log) == (0, "I think it is fine", "claude_tui_broker_terminal_nonconforming")


def test_cancel_wins_over_terminal_nonconforming_at_pty_eof(tmp_path, monkeypatch):
    rc, text, log, _ = _run_terminal_child(
        tmp_path, monkeypatch, shape="eof", interval_s=60, cancel_on_final_read=True)
    assert rc != 0 and text == "" and log == "review_operation_cancelled", (rc, text, log)


def test_cancel_wins_over_terminal_nonconforming_at_idle_poll(tmp_path, monkeypatch):
    rc, text, log, _ = _run_terminal_child(
        tmp_path, monkeypatch, shape="alive", interval_s=.05, cancel_on_final_read=True)
    assert rc != 0 and text == "" and log == "review_operation_cancelled", (rc, text, log)
