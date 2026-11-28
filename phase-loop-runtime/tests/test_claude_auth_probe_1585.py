"""agent-harness#1585: transient `claude auth status` retry + closed-field private 0600
probe diagnostic retention (bounded retention, zero raw CLI text or identity PII).
"""

from __future__ import annotations

import json
import stat
import subprocess
import time

import pytest

from phase_loop_runtime import executor_availability as ea
from phase_loop_runtime.advisor_board import composition


_CLAUDE_PROBES = ("claude --version", "claude --help", "claude auth status")


@pytest.fixture(autouse=True)
def _fresh_auth_cache():
    ea.clear_auth_cache()
    yield
    ea.clear_auth_cache()


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args="probe", returncode=returncode, stdout=stdout, stderr=stderr)


def _probe_records(state_dir):
    return sorted(state_dir.rglob("probe-*.json"))


def test_claude_auth_status_transient_exit_recovers_on_single_retry_and_retains_private_diag(
    tmp_path, monkeypatch,
):
    """Exact reproduction of the 2026-11-09 transient `claude auth status` exit-1 race on `ai`:
    one bounded retry recovers composition and records a closed-field private 0600 diagnostic."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    calls: list[str] = []
    sleeps: list[float] = []

    def runner(probe: str):
        calls.append(probe)
        if probe == "claude auth status":
            if calls.count(probe) == 1:
                return _completed(
                    1,
                    stdout="",
                    stderr=(
                        "token refresh lock busy for müller@example.invalid "
                        "orgId=org-secret-stderr orgName='Private Org Stderr' "
                        "/tmp/user/.claude/.credentials.json "
                        "Bearer sk-ant-secretvalue1234567890"
                    ),
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
    assert record["first_stderr_class"] == "token_refresh_or_expiry"
    assert record["first_stderr_bytes"] > 0
    assert record["final_stderr_class"] == "empty"
    # Secrets, paths, internationalized emails, and org identifiers from BOTH stdout and
    # stderr must never appear in the persisted record.
    for forbidden in (
        "sk-ant-secretvalue1234567890",
        "private@example.invalid",
        "müller@example.invalid",
        "org-secret-id",
        "org-secret-stderr",
        "Private Org",
        ".credentials.json",
    ):
        assert forbidden not in raw


def test_malformed_or_truncated_stdout_never_opens_auth_gate_on_first_or_retry_attempt(
    tmp_path, monkeypatch,
):
    """P1 regression: malformed JSON containing `"loggedIn":true` must never admit on
    either the first attempt or a retry attempt, and must never emit `recovered_on_retry`."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))

    # First attempt rc=0 with truncated JSON.
    def truncated_first(probe: str):
        if probe == "claude auth status":
            return _completed(0, stdout='{"loggedIn": true')
        return _completed(0)

    assert ea.auth_ok_for("claude", _CLAUDE_PROBES, runner=truncated_first, sleep=lambda _s: None) is False
    assert ea.auth_refusal_for("claude", _CLAUDE_PROBES) == ea.ProbeRefusal(
        "not_logged_in", "claude auth status"
    )

    # First attempt rc=1, retry rc=0 with non-JSON error text quoting `"loggedIn":true`.
    ea.clear_auth_cache()
    attempt = 0

    def bogus_retry(probe: str):
        nonlocal attempt
        if probe == "claude auth status":
            attempt += 1
            if attempt == 1:
                return _completed(1, stderr="transient failure")
            return _completed(0, stdout='error: last known status "loggedIn":true')
        return _completed(0)

    assert ea.auth_ok_for("claude", _CLAUDE_PROBES, runner=bogus_retry, sleep=lambda _s: None) is False
    assert ea.auth_refusal_for("claude", _CLAUDE_PROBES) == ea.ProbeRefusal(
        "not_logged_in", "claude auth status"
    )
    records = [json.loads(p.read_text(encoding="utf-8")) for p in _probe_records(state)]
    assert all(r["outcome"] == "not_logged_in" for r in records)
    assert not any(r["outcome"] == "recovered_on_retry" for r in records)


def test_claude_auth_status_persistent_nonzero_exit_fails_closed_and_retains_diag(
    tmp_path, monkeypatch,
):
    """Two consecutive non-zero exits without `loggedIn: false` fail closed as `nonzero_exit`,
    keep `ProbeRefusal` free of CLI text, and retain closed stderr class privately."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
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
    assert record["final_stderr_class"] == "credential_store"


def test_claude_auth_status_exit_1_with_logged_in_false_classifies_not_logged_in(
    tmp_path, monkeypatch,
):
    """Claude Code 2.1.x exits 1 with `{"loggedIn": false, "authMethod": "none"}` when
    signed out; after confirming on retry, report `not_logged_in` -> `board_seat_not_logged_in`."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))

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
    attempt = 0

    def runner(probe: str):
        nonlocal attempt
        if probe == "claude auth status":
            attempt += 1
            if attempt == 1:
                return _completed(1, stderr="transient lock failure")
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
    assert record["first_stderr_class"] == "lock_or_transient"


def test_stderr_classification_is_bounded_and_linear_on_large_input():
    """P2 regression: huge non-matching stderr classifies in bounded linear time."""
    huge = "a" * 100_000
    t0 = time.monotonic()
    category, byte_count = ea._classify_probe_stderr(huge)
    assert (time.monotonic() - t0) < 0.1
    assert category == "unclassified"
    assert byte_count == 100_000


def test_probe_diagnostics_retention_is_bounded_and_preserves_leg_records(tmp_path, monkeypatch):
    """P3 regression: `probe-*.json` files are pruned to `_PROBE_DIAG_KEEP` without touching
    sibling `leg-*.json` records."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setattr(ea, "_PROBE_DIAG_KEEP", 3)

    from phase_loop_runtime.president_adapter import write_private_record

    sibling = write_private_record("leg-keepme.json", {"schema": "leg_exec.v1"})
    for idx in range(5):
        ea._record_probe_diagnostic(
            executor="claude",
            probe="claude auth status",
            outcome="nonzero_exit",
            attempts=2,
            first_returncode=1,
            final_returncode=1,
            final_stderr=f"lock busy {idx}",
        )
    assert sibling.is_file(), "sibling leg-*.json record must never be pruned"
    assert len(_probe_records(state)) == 3


def test_healthy_claude_probe_does_not_retry_or_write_diagnostic(tmp_path, monkeypatch):
    """A passing first attempt performs zero retries, zero sleep, and writes no diagnostic."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    sleeps: list[float] = []

    def runner(probe: str):
        if probe == "claude auth status":
            return _completed(0, stdout='{"loggedIn": true, "authMethod": "claude.ai"}')
        return _completed(0)

    assert ea.auth_ok_for("claude", _CLAUDE_PROBES, runner=runner, sleep=sleeps.append) is True
    assert sleeps == []
    assert _probe_records(state) == []
