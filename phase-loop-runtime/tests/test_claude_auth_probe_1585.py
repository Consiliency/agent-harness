"""agent-harness#1585: transient `claude auth status` retry + private 0600 probe
diagnostic retention (redacted, zero PII/secrets, never leaking into ProbeRefusal).
"""

from __future__ import annotations

import json
import stat
import subprocess

from phase_loop_runtime import executor_availability as ea
from phase_loop_runtime.advisor_board import composition


_CLAUDE_PROBES = ("claude --version", "claude --help", "claude auth status")


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args="probe", returncode=returncode, stdout=stdout, stderr=stderr)


def _probe_records(state_dir):
    return sorted(state_dir.rglob("probe-*.json"))


def test_claude_auth_status_transient_exit_recovers_on_single_retry_and_retains_private_diag(
    tmp_path, monkeypatch,
):
    """Exact reproduction of the 2026-11-09 transient `claude auth status` exit-1 race on `ai`:
    one bounded retry recovers composition and records a private 0600 diagnostic."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    ea.clear_auth_cache()
    calls: list[str] = []
    sleeps: list[float] = []

    def runner(probe: str):
        calls.append(probe)
        if probe == "claude auth status":
            if calls.count(probe) == 1:
                return _completed(
                    1,
                    stdout="",
                    stderr="token refresh lock busy for private@example.invalid Bearer sk-ant-secretvalue1234567890",
                )
            return _completed(
                0,
                stdout=json.dumps({
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "email": "private@example.invalid",
                    "orgId": "org-secret-id",
                    "orgName": "Private Org",
                }),
            )
        return _completed(0, stdout="2.1.319 (Claude Code)\n")

    assert ea.auth_ok_for("claude", _CLAUDE_PROBES, runner=runner, sleep=sleeps.append) is True
    assert ea.auth_refusal_for("claude", _CLAUDE_PROBES) is None
    assert calls.count("claude auth status") == 2
    assert sleeps == [ea._CLAUDE_AUTH_RETRY_DELAY_S]

    (record_path,) = _probe_records(state)
    assert stat.S_IMODE(record_path.stat().st_mode) == 0o600
    raw = record_path.read_text(encoding="utf-8")
    record = json.loads(raw)
    assert record["schema"] == "auth_probe_diag.v1"
    assert record["executor"] == "claude"
    assert record["probe"] == "claude auth status"
    assert record["outcome"] == "recovered_on_retry"
    assert record["attempts"] == 2
    assert record["first_returncode"] == 1
    assert record["final_returncode"] == 0
    assert record["claude_logged_in"] is True
    assert record["claude_auth_method"] == "claude.ai"
    assert "token refresh lock busy" in record["first_stderr_excerpt"]
    # Secrets and identity PII must never appear in the persisted record.
    for forbidden in ("sk-ant-secretvalue1234567890", "private@example.invalid", "org-secret-id", "Private Org"):
        assert forbidden not in raw


def test_claude_auth_status_persistent_nonzero_exit_fails_closed_and_retains_diag(
    tmp_path, monkeypatch,
):
    """Two consecutive non-zero exits without `loggedIn: false` fail closed as `nonzero_exit`,
    keep `ProbeRefusal` free of CLI text, and retain redacted stderr privately."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    ea.clear_auth_cache()
    calls: list[str] = []

    def runner(probe: str):
        calls.append(probe)
        if probe == "claude auth status":
            return _completed(1, stdout="", stderr="Error: credential helper exited 1")
        return _completed(0)

    assert ea.auth_ok_for("claude", _CLAUDE_PROBES, runner=runner, sleep=lambda _s: None) is False
    assert calls.count("claude auth status") == 2
    refusal = ea.auth_refusal_for("claude", _CLAUDE_PROBES)
    assert refusal == ea.ProbeRefusal("nonzero_exit", "claude auth status", returncode=1)

    (record_path,) = _probe_records(state)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["outcome"] == "nonzero_exit"
    assert record["attempts"] == 2
    assert record["first_returncode"] == 1
    assert record["final_returncode"] == 1
    assert "credential helper exited 1" in record["final_stderr_excerpt"]


def test_claude_auth_status_exit_1_with_logged_in_false_classifies_not_logged_in(
    tmp_path, monkeypatch,
):
    """Claude Code 2.1.x exits 1 with `{"loggedIn": false, "authMethod": "none"}` when
    signed out; after confirming on retry, report `not_logged_in` -> `board_seat_not_logged_in`."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    ea.clear_auth_cache()

    def runner(probe: str):
        if probe == "claude auth status":
            return _completed(
                1,
                stdout=json.dumps({"loggedIn": False, "authMethod": "none"}),
                stderr="",
            )
        return _completed(0)

    assert ea.auth_ok_for("claude", _CLAUDE_PROBES, runner=runner, sleep=lambda _s: None) is False
    refusal = ea.auth_refusal_for("claude", _CLAUDE_PROBES)
    assert refusal == ea.ProbeRefusal("not_logged_in", "claude auth status", returncode=1)

    monkeypatch.setattr(ea, "auth_refusal_for", lambda _e, _p: refusal)
    excluded = composition.default_board_auth_refusal("claude")
    assert excluded.code == composition.SEAT_NOT_LOGGED_IN
    assert "claude auth status" in excluded.why

    (record_path,) = _probe_records(state)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["outcome"] == "not_logged_in"
    assert record["claude_logged_in"] is False
    assert record["claude_auth_method"] == "none"


def test_claude_auth_status_retry_timeout_fails_closed(tmp_path, monkeypatch):
    """If the retry attempt times out, the gate fails closed as `timed_out`."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    ea.clear_auth_cache()
    attempt = 0

    def runner(probe: str):
        nonlocal attempt
        if probe == "claude auth status":
            attempt += 1
            if attempt == 1:
                return _completed(1, stderr="transient failure")
            raise subprocess.TimeoutExpired(cmd=probe, timeout=ea._PROBE_TIMEOUT_SECONDS)
        return _completed(0)

    ok, refusal = ea._probes_verdict("claude", _CLAUDE_PROBES, runner, sleep=lambda _s: None)
    assert ok is False
    assert refusal == ea.ProbeRefusal("timed_out", "claude auth status", exception="TimeoutExpired")
    (record_path,) = _probe_records(state)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["outcome"] == "timed_out"
    assert record["attempts"] == 2
    assert record["first_returncode"] == 1
    assert record["final_returncode"] is None


def test_healthy_claude_probe_does_not_retry_or_write_diagnostic(tmp_path, monkeypatch):
    """A passing first attempt performs zero retries, zero sleep, and writes no diagnostic."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    ea.clear_auth_cache()
    sleeps: list[float] = []

    def runner(probe: str):
        if probe == "claude auth status":
            return _completed(0, stdout='{"loggedIn": true, "authMethod": "claude.ai"}')
        return _completed(0)

    assert ea.auth_ok_for("claude", _CLAUDE_PROBES, runner=runner, sleep=sleeps.append) is True
    assert sleeps == []
    assert _probe_records(state) == []
