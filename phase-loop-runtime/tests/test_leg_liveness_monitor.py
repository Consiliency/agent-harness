"""Behavior tests for the stall-aware leg-liveness runner (`_run_leg_with_liveness`).

These use REAL `subprocess.Popen` (no mock) with small thresholds to prove the
load-bearing behaviors on the review-gating path:
- a silent+idle leg is reclaimed on HEARTBEAT EXTINCTION (~stall_threshold), NOT at
  the wall-clock deadline;
- a CPU-active-but-silent leg is NOT false-killed by the stall timer (the secondary
  CPU heartbeat extends its life) — it dies only at the deadline backstop;
- a streaming leg survives to normal exit via its stdout heartbeat;
- stdin is fed deadlock-safely by the writer thread.

The CPU-sample cadence constant is monkeypatched below its default (5s) only where a
test needs the secondary CPU heartbeat to fire faster than a short test stall window;
production keeps 5s << 180s so CPU is sampled dozens of times per stall window.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from phase_loop_runtime import panel_invoker as pi

# Children launched by the runner use start_new_session=True (pgid == child pid), so
# group_cpu_ticks works for THEM even though this test process isn't a group leader.
# Availability is therefore a plain /proc (linux) check, not a self-pid probe.
_CPU_AVAILABLE = sys.platform.startswith("linux") and os.path.isdir("/proc")


def _run(cmd, *, deadline_s, stall_threshold_s, input_text=None):
    return pi._run_leg_with_liveness(
        cmd,
        cwd=".",
        env=os.environ,
        deadline_s=deadline_s,
        stall_threshold_s=stall_threshold_s,
        input_text=input_text,
    )


def test_silent_idle_leg_is_reclaimed_on_stall_not_deadline():
    # sleep: no stdout, no CPU. Must die ~stall_threshold, FAR before the deadline.
    t0 = time.monotonic()
    result = _run(["sleep", "600"], deadline_s=60, stall_threshold_s=2)
    elapsed = time.monotonic() - t0
    assert "[leg-liveness] stalled" in result.stderr
    assert elapsed < 15, f"took {elapsed:.1f}s — should be ~stall_threshold (2s), not the 60s deadline"


@pytest.mark.skipif(not _CPU_AVAILABLE, reason="process-group CPU sampling needs linux /proc")
def test_cpu_active_silent_leg_survives_stall_and_dies_at_deadline(monkeypatch):
    # A busy-loop emits NO stdout but burns CPU. The secondary CPU heartbeat must keep
    # resetting last_heartbeat so the stall timer never fires; it dies only at the
    # wall-clock deadline. Speed the CPU sampler so it beats the short test stall window.
    monkeypatch.setattr(pi, "_LEG_LIVENESS_CPU_SAMPLE_S", 0.3)
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run([sys.executable, "-c", "while True: pass"], deadline_s=4, stall_threshold_s=1)
    elapsed = time.monotonic() - t0
    # survived WELL past the 1s stall window (CPU heartbeat), died at the ~4s deadline.
    assert elapsed >= 3.5, f"died at {elapsed:.1f}s — CPU heartbeat should have carried it to the deadline"


def test_streaming_leg_survives_to_exit_via_stdout_heartbeat():
    # emits a line every 0.3s for ~3s; the stdout heartbeat must keep it alive to exit.
    result = _run(
        ["bash", "-c", "for i in $(seq 10); do echo tick; sleep 0.3; done"],
        deadline_s=30,
        stall_threshold_s=2,
    )
    assert result.returncode == 0
    assert result.stdout.count("tick") == 10
    assert "[leg-liveness] stalled" not in result.stderr


@pytest.mark.skipif(not _CPU_AVAILABLE, reason="process-group CPU sampling needs linux /proc")
def test_deadline_backstop_fires_even_when_cpu_active(monkeypatch):
    # deadline below the stall window: the wall-clock backstop must still fire (raise).
    monkeypatch.setattr(pi, "_LEG_LIVENESS_CPU_SAMPLE_S", 0.3)
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run([sys.executable, "-c", "while True: pass"], deadline_s=2, stall_threshold_s=30)
    assert time.monotonic() - t0 < 6


def test_deadline_backstop_preserves_best_available_streams():
    with pytest.raises(subprocess.TimeoutExpired) as captured:
        _run(
            [
                sys.executable, "-c",
                "print('partial-output', flush=True);\nwhile True: pass",
            ],
            deadline_s=2,
            stall_threshold_s=30,
        )
    assert "partial-output" in str(captured.value.stdout)


def test_stdin_is_fed_by_writer_thread_without_deadlock():
    # cat echoes stdin then exits on EOF — proves the daemon writer thread feeds stdin
    # and closes it (no deadlock, correct stdout capture).
    result = _run(["cat"], deadline_s=15, stall_threshold_s=10, input_text="hello-from-stdin\n")
    assert result.returncode == 0
    assert "hello-from-stdin" in result.stdout


def test_normal_fast_exit_returns_captured_output():
    result = _run(["bash", "-c", "echo done; exit 0"], deadline_s=15, stall_threshold_s=10)
    assert result.returncode == 0
    assert "done" in result.stdout
    assert "[leg-liveness] stalled" not in result.stderr


# --- Concern 1: an EXPLICIT per-leg timeout override is honored as the hard deadline ---

def test_leg_deadline_from_honors_explicit_and_raises_default(tmp_path):
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    # explicit override → honored as-is (even below the backstop): frozen contract.
    assert pi._leg_deadline_from(300, review_dir) == (300, 300)
    assert pi._leg_deadline_from(2400, review_dir) == (2400, 2400)  # above backstop honored too
    # default (None) → input-scaled reference, deadline raised to the _MAX backstop.
    ref, deadline = pi._leg_deadline_from(None, review_dir)
    assert ref == pi._leg_timeout_for(review_dir)
    assert deadline == pi._MAX_LEG_TIMEOUT_S


def test_exec_leg_threads_explicit_override_as_deadline(tmp_path, monkeypatch):
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("bundle")
    (review_dir / "review-instructions.md").write_text("instr")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    captured = {}

    def fake_liveness(cmd, **k):
        captured["deadline_s"] = k.get("deadline_s")
        (out_dir / "panel-codex.txt").write_text("AGREE")
        return pi._LegRun(0, "", "")

    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)

    # explicit 300 override reaches the runner as a 300s deadline — NOT raised to 1800.
    pi._exec_leg("codex", review_dir, out_dir, 300, "artifact")
    assert captured["deadline_s"] == 300
    # unset (None) → raised to the _MAX backstop so a slow-but-streaming default isn't cut off.
    pi._exec_leg("codex", review_dir, out_dir, None, "artifact")
    assert captured["deadline_s"] == pi._MAX_LEG_TIMEOUT_S


def test_default_spawn_threads_explicit_backstop_to_claude_tui(tmp_path, monkeypatch):
    # End-to-end pin of concern-1 on the CLAUDE TUI path: _default_spawn is the sole
    # resolver, so an explicit per-leg override must reach _run_claude_tui_session as
    # ``backstop_s`` (the print path is already pinned by the test above).
    captured = {}

    def fake_tui(**kwargs):
        captured["backstop_s"] = kwargs.get("backstop_s")
        return 0, "Looks good.\nAGREE", "", ""

    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda *a, **k: False)
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(pi, "_run_claude_tui_session", fake_tui)

    pi._default_spawn("claude", "artifact", repo_dir=tmp_path, timeout_s=300)
    assert captured["backstop_s"] == 300  # explicit override honored, not raised to _MAX
    pi._default_spawn("claude", "artifact", repo_dir=tmp_path, timeout_s=None)
    assert captured["backstop_s"] == pi._MAX_LEG_TIMEOUT_S  # default raised to the backstop


# --- Concern 2: leader exits while a descendant still holds the pipe → reclaim, not hang ---

@pytest.mark.skipif(not _CPU_AVAILABLE, reason="process-group kill needs a POSIX process group")
def test_leader_exit_with_child_holding_pipe_is_reclaimed_not_deadline(monkeypatch):
    # bash leader backgrounds `sleep 600` (which inherits + holds stdout open, idle) then
    # exits 0. Neither clean-exit (pipe still open) nor stall (leader exited) fires — the
    # OLD code burned the full deadline. Must now reclaim ~post-exit-grace after the
    # leader exits, killing the lingering group member.
    monkeypatch.setattr(pi, "_LEG_POST_EXIT_GRACE_S", 2.0)
    t0 = time.monotonic()
    result = _run(
        ["bash", "-c", "sleep 600 & echo started; exit 0"],
        deadline_s=60,
        stall_threshold_s=120,
    )
    elapsed = time.monotonic() - t0
    assert "started" in result.stdout
    assert elapsed < 15, f"took {elapsed:.1f}s — should reclaim ~post-exit-grace, not the 60s deadline"


@pytest.mark.skipif(not _CPU_AVAILABLE, reason="process-group kill needs a POSIX process group")
def test_termination_kills_ignoring_descendant_before_cleanup(monkeypatch, tmp_path):
    marker = tmp_path / "descendant.pid"
    child_code = (
        "import os, signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "open(sys.argv[1], 'w').write(str(os.getpid())); "
        "time.sleep(600)"
    )
    leader_code = (
        "import signal, subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]]); "
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
        "time.sleep(600)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", leader_code, str(marker), child_code],
        start_new_session=True,
    )
    pi._anchor_process_group(proc)
    monkeypatch.setattr(pi, "_PROCESS_GROUP_TERM_GRACE_S", 0.2)
    monkeypatch.setattr(pi, "_PROCESS_GROUP_KILL_GRACE_S", 3.0)
    monkeypatch.setattr(pi, "_PROCESS_GROUP_POLL_S", 0.02)
    deadline = time.monotonic() + 5
    try:
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        descendant_pid = int(marker.read_text())
        cleanup_called = False

        pi._terminate_process_group(proc)

        def cleanup_callback() -> None:
            nonlocal cleanup_called
            cleanup_called = True
            with pytest.raises(ProcessLookupError):
                os.kill(descendant_pid, 0)
            assert not pi._process_group_exists(proc.pid)

        cleanup_callback()
        assert cleanup_called
        assert proc.poll() == 0
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def test_process_group_termination_escalates_after_leader_exit(monkeypatch):
    class ReapedLeader:
        pid = 12345

        @staticmethod
        def poll():
            return 0

    signals: list[int] = []
    waits = iter((False, True))
    monkeypatch.setattr(pi, "_process_group_exists", lambda _pgid: True)
    monkeypatch.setattr(
        pi, "_wait_for_process_group_exit",
        lambda *_args, **_kwargs: next(waits),
    )
    monkeypatch.setattr(
        pi.os, "killpg", lambda _pgid, sent: signals.append(sent),
    )

    pi._terminate_process_group(ReapedLeader(), force_group=True)

    assert signals == [signal.SIGTERM, signal.SIGKILL]


@pytest.mark.skipif(not _CPU_AVAILABLE, reason="provider group registry needs POSIX groups")
def test_quiescence_latch_closes_launch_registration_race(tmp_path):
    latch = pi._ProviderQuiescenceLatch()
    primary = pi.ProviderProcessGroupQuiescenceError("fatal quiescence")
    factory_entered = threading.Event()
    allow_popen = threading.Event()
    launched: list[subprocess.Popen[bytes]] = []
    trip_results: list[BaseException] = []

    def factory() -> subprocess.Popen[bytes]:
        factory_entered.set()
        assert allow_popen.wait(5)
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"],
            cwd=tmp_path,
            start_new_session=True,
        )

    def launch() -> None:
        launched.append(latch.launch(factory))

    def trip() -> None:
        try:
            trip_results.append(latch.trip(primary))
        except BaseException as exc:  # captured for deterministic thread assertion
            trip_results.append(exc)

    launch_thread = threading.Thread(target=launch)
    trip_thread = threading.Thread(target=trip)
    launch_thread.start()
    assert factory_entered.wait(5)
    trip_thread.start()
    allow_popen.set()
    launch_thread.join(5)
    trip_thread.join(5)

    assert not launch_thread.is_alive()
    assert not trip_thread.is_alive()
    assert trip_results == [primary]
    assert len(launched) == 1
    proc = launched[0]
    assert proc.poll() is not None
    assert not pi._process_group_exists(proc.pid)
    latch.release(proc)


@pytest.mark.skipif(not _CPU_AVAILABLE, reason="provider group registry needs POSIX groups")
def test_quiescence_latch_rejects_deregistering_live_group(tmp_path):
    latch = pi._ProviderQuiescenceLatch()
    proc = latch.launch(lambda: subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)"],
        cwd=tmp_path,
        start_new_session=True,
    ))
    try:
        with pytest.raises(
            pi.ProviderProcessGroupQuiescenceError,
            match="deregistration preceded quiescence",
        ):
            latch.release(proc)
    finally:
        pi._terminate_process_group(proc)
    latch.release(proc)


def test_process_group_termination_fails_if_group_survives_sigkill(monkeypatch):
    class ReapedLeader:
        pid = 12345

        @staticmethod
        def poll():
            return 0

    monkeypatch.setattr(pi, "_process_group_exists", lambda _pgid: True)
    monkeypatch.setattr(
        pi, "_wait_for_process_group_exit",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(pi.os, "killpg", lambda *_args: None)

    with pytest.raises(
        pi.AgyCanaryEvidenceError,
        match="provider process group did not terminate",
    ):
        pi._terminate_process_group(ReapedLeader(), force_group=True)


@pytest.mark.parametrize("disappears", ["before_term", "at_term"])
def test_process_group_termination_accepts_disappearance_races(
    monkeypatch, disappears,
):
    class ReapedLeader:
        pid = 12345
        polls = 0

        def poll(self):
            self.polls += 1
            return 0

    proc = ReapedLeader()
    signals: list[int] = []
    monkeypatch.setattr(
        pi, "_process_group_exists",
        lambda _pgid: disappears != "before_term",
    )

    def disappearing_killpg(_pgid, sent):
        signals.append(sent)
        raise ProcessLookupError

    monkeypatch.setattr(pi.os, "killpg", disappearing_killpg)

    pi._terminate_process_group(proc, force_group=True)

    assert signals == ([] if disappears == "before_term" else [signal.SIGTERM])
    assert proc.polls >= 2
