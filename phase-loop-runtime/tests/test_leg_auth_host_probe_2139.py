"""agent-harness#2139: a failed leg's host auth probe runs with the caller's host env, never
the env the leg recorded from its jail, and an auth outcome never replaces a leg's own typed
failure detail."""

from __future__ import annotations

import json

import pytest

from phase_loop_runtime import panel_invoker as pi

_HOST_ENV = {"PATH": "/host/bin:/usr/bin:/bin", "HOME": "/host/home",
             "CLAUDE_CONFIG_DIR": "/host/home/.claude"}
_JAIL_ENV = {"PATH": "/seat/bin:/usr/bin:/bin", "HOME": "/seat/home",
             "CLAUDE_CONFIG_DIR": "/seat/home/.claude"}


def _turnless_leg(detail, *, notices=()):
    """A leg that ran in a jail and ended non-zero before any model turn."""
    @pi._retained_leg_exec
    def run(leg, artifact, *, env=None):
        observation = pi._EXEC_OBSERVATION.get()
        pi._note_exec_result(-15, ["claude"], dict(_JAIL_ENV), actual=True)
        observation.update(model_turn=False, verdict=False)
        return pi._BrokeredSpawnResult("DEGRADED", "", detail, seat_notices=notices)
    return run


def _records(tmp_path):
    return [json.loads(p.read_text()) for p in (tmp_path / "state").rglob("leg-*.json")]


@pytest.fixture
def probes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    seen: list = []

    def probe(leg, env=None):
        # A host probe only answers from the host's own paths.
        seen.append(None if env is None else dict(env))
        return "healthy" if env is not None and env.get("HOME") == "/host/home" else "unavailable"
    monkeypatch.setattr(pi, "_parent_auth_state", probe)
    return seen


@pytest.mark.parametrize("leg", ["claude", "codex", "gemini", "grok"])
def test_the_host_probe_gets_the_host_env_not_the_jail_env(tmp_path, probes, leg):
    result = _turnless_leg(None)(leg, "artifact", env=dict(_HOST_ENV))
    assert probes == [_HOST_ENV]
    assert not str(result[2] if len(result) > 2 else "").startswith("leg_auth_")
    (record,) = _records(tmp_path)
    assert record["auth_state"] == "healthy"
    assert not record["outcome"].startswith("leg_auth_")


def test_a_typed_tui_detail_survives_an_unavailable_probe(tmp_path, probes):
    failure = pi._LegFailure(template="claude_tui_editor_not_ready")
    run = _turnless_leg(failure, notices=("claude_tui_editor_not_ready",))
    # A caller env the probe cannot answer from: the record's outcome is an auth one.
    result = run("claude", "artifact", env={"HOME": "/elsewhere"})
    (record,) = _records(tmp_path)
    assert record["outcome"] == "leg_auth_unavailable"
    assert result[2] is failure
    assert result.seat_notices == ("claude_tui_editor_not_ready",)
    board = pi.invoke_panel("ARTIFACT", ["claude"], spawn=lambda leg, art: result)
    (panel_leg,) = board.legs
    assert panel_leg.status == "DEGRADED"
    assert panel_leg.detail == "claude_tui_editor_not_ready"


@pytest.mark.parametrize("detail", [None, pi._LegFailure(template="auth_failure"),
                                    pi._LegFailure(template="x", unknown=True, rc=1)])
def test_a_genuine_signed_out_leg_still_reads_as_signed_out(tmp_path, monkeypatch, detail):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda leg, env=None: "signed_out")
    result = _turnless_leg(detail)("claude", "artifact", env=dict(_HOST_ENV))
    assert result[2] == "leg_auth_signed_out"
    (record,) = _records(tmp_path)
    assert record["outcome"] == "leg_auth_signed_out"


# --------------------------------------------------------------------------------------
# A detail is typed by the stored-detail rules: provenance and the registry decide.
# --------------------------------------------------------------------------------------

_ROUTE = pi._HarnessCode("claude_tui_pty_eof_no_output")


@pytest.mark.parametrize("detail, typed", [
    (pi._LegFailure(template="claude_tui_workspace_trust_blocked"), True),
    (pi._HarnessCode("claude_tui_stalled"), True),
    ("claude_tui_stalled", True),                      # our own literal, as a plain str
    ("timeout", True),
    (pi._LegFailure(template="x", unknown=True, rc=1, prefix=_ROUTE), True),
    (pi._LegFailure(template=""), False),
    (pi._LegFailure(template="not_a_registered_code"), False),
    ("some text a CLI printed", False),
    (pi._LegFailure(template="auth_failure"), False),
    ("auth_failure", False),
    (pi._HarnessCode("claude_tui_pty_eof_no_output: auth_failure"), False),
    (pi._LegFailure(template="auth_failure", prefix=_ROUTE), False),
    (pi._LegFailure(template="x", unknown=True, rc=1), False),
    (pi._UNKNOWN_DETAIL, False),
    (pi._HarnessCode("leg_auth_unavailable"), False),
    (None, False),
], ids=lambda value: repr(getattr(value, "template", value))[:40])
def test_only_a_typed_detail_survives_a_signed_out_leg(tmp_path, monkeypatch, detail, typed):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda leg, env=None: "signed_out")
    result = _turnless_leg(detail)("claude", "artifact", env=dict(_HOST_ENV))
    assert (result[2] if len(result) > 2 else None) == (detail if typed else "leg_auth_signed_out")


# --------------------------------------------------------------------------------------
# The real jailed call site: `_default_spawn` -> `launch_jailed` -> the login proof -> the
# real jailed TUI leg. Only the proof and the TUI session boundaries are stand-ins.
# --------------------------------------------------------------------------------------

_AUTH_TAIL = "Invalid API key · Please run /login"


def _attempt(monkeypatch, tmp_path, *, proof="pass", log_text=None, tail="", rc=1,
             source=None, expires_at=None):
    from phase_loop_runtime import claude_seat_transport as ct
    from phase_loop_runtime import seat_credentials as sc
    from test_seat_login_wait_a3_1166 import _spawn
    from test_seat_notices import _FakeSeat

    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv(ct.ROUTE_ENV, "tui")
    before = set(state.rglob("leg-*.json"))
    probes: list = []
    tui: list = []
    monkeypatch.setattr(pi, "_parent_auth_state",
                        lambda leg, env=None: probes.append(leg) or "signed_out")
    monkeypatch.setattr(pi._seat_uid, "read_in_h", lambda *a, **k: b"")
    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", lambda *a, **k: [])
    monkeypatch.setattr(pi._seat_jail, "close_jail_fds", lambda jail: None)
    monkeypatch.setattr(pi, "_broker_claude_tui_command", lambda **k: ["/seat/bin/claude"])
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, **k: None)

    def _session(**kwargs):
        tui.append(kwargs)
        return rc, "", pi._HarnessCode(log_text) if log_text else "", tail

    def _real_leg(seat, **kwargs):
        # The TUI session is swapped only inside the real jailed leg: swapped for the whole
        # spawn, it would read as an injected execution seam and take another route.
        production = pi._run_claude_tui_session
        pi._run_claude_tui_session = _session
        try:
            return _REAL_JAILED_CLAUDE_LEG(seat, **kwargs)
        finally:
            pi._run_claude_tui_session = production

    def _proof(seat, *a, **k):
        if proof != "pass":
            raise ct.TransportRefused(sc.LOGIN_UNPROVEN)
        return sc.LoginProof(sc.SOURCE_LOGIN, "oauth_token", "none")

    spawned, _calls = _spawn(monkeypatch, tmp_path, sc.LOGIN_READY,
                             jailed_leg=_real_leg, login_proof=_proof,
                             prepare=lambda *a, **k: _route_seat(_FakeSeat(tmp_path),
                                                                 source, expires_at))
    (record,) = [json.loads(p.read_text()) for p in set(state.rglob("leg-*.json")) - before]
    detail = tuple(spawned)[2] if len(tuple(spawned)) > 2 else None
    return spawned, record, str(getattr(detail, "template", detail)), probes, tui


_REAL_JAILED_CLAUDE_LEG = pi._exec_jailed_claude_leg


def _route_seat(seat, source=None, expires_at=None):
    # The route's own jails are bound to the seat, so the route qualification holds.
    del seat.jail, seat.probe_jail
    if source is not None:
        seat.source, seat.expires_at = source, expires_at
    return seat


def _tui_failure(monkeypatch, tmp_path):
    return _attempt(monkeypatch, tmp_path, log_text="claude_tui_workspace_trust_blocked",
                    tail="Do you trust the files in this folder?")


def _auth_rejection(monkeypatch, tmp_path):
    return _attempt(monkeypatch, tmp_path, log_text="claude_tui_pty_eof_no_output",
                    tail=_AUTH_TAIL)


def test_a_proven_seat_keeps_its_tui_failure_and_probes_no_host(monkeypatch, tmp_path):
    spawned, record, detail, probes, tui = _tui_failure(monkeypatch, tmp_path)
    assert len(tui) == 1 and probes == []
    assert record["auth_state"] == "healthy" and record["outcome"] == "leg_execution_failed"
    assert detail == "claude_tui_workspace_trust_blocked"
    assert not any(code.endswith(("_rejected", "_signed_out", "_unavailable"))
                   for code in spawned.seat_notices)


def test_a_refused_proof_launches_nothing_and_is_never_healthy(monkeypatch, tmp_path):
    spawned, record, detail, probes, tui = _attempt(monkeypatch, tmp_path, proof="refuse")
    assert tui == [] and probes == []
    assert tuple(spawned)[0] == "DEGRADED"
    assert detail == "claude_seat_login_unproven"
    assert record["auth_state"] != "healthy"


def _board(spawned):
    from phase_loop_runtime.cli import _board_notices_json

    board = pi.invoke_panel("ARTIFACT", ["claude"], spawn=lambda leg, art: spawned)
    (leg,) = board.legs
    return (leg, [n.code for n in pi.refused_seat_notices(board.legs)],
            [n["code"] for n in _board_notices_json(board.legs)])


def test_a_seat_token_rejection_names_the_token_not_the_host_login(monkeypatch, tmp_path):
    spawned, record, detail, probes, tui = _auth_rejection(monkeypatch, tmp_path)
    assert len(tui) == 1 and probes == []
    # The proof decided the auth state; the rejection is the credential's own outcome.
    assert record["auth_state"] == "healthy" and record["outcome"] == "leg_execution_failed"
    assert detail == "claude_seat_token_rejected"
    leg, refused, codes = _board(spawned)
    assert leg.detail == "claude_seat_token_rejected"
    assert refused == ["claude_seat_token_rejected"]
    assert not any(code.startswith("leg_auth_") for code in codes)
    (notice,) = pi.refused_seat_notices([leg])
    assert "seat token override was rejected" in notice.why
    assert "store-token" in notice.fix and "claude auth login" not in notice.fix


def test_echoed_instructions_quoting_an_auth_banner_then_a_stall_are_no_rejection(
        monkeypatch, tmp_path):
    # The terminal shows the echoed prompt, which quotes an auth banner, and then the editor
    # never readies: the harness ends the session (the CLI did not exit on its own).
    echoed = ("> Review the staged tree. If you see \"Invalid API key · Please run /login\", "
              "report it.\n")
    for code in ("claude_tui_editor_not_ready", "claude_tui_stalled"):
        spawned, record, detail, probes, _tui = _attempt(
            monkeypatch, tmp_path, log_text=code, tail=echoed)
        assert probes == [] and record["auth_state"] == "healthy"
        assert record["outcome"] == "leg_execution_failed"
        assert detail == code
        assert not any(n.endswith(("_rejected", "_signed_out")) for n in spawned.seat_notices)


def test_an_expired_login_keeps_its_typed_outcome_and_the_proofs_auth_state(
        monkeypatch, tmp_path):
    import time

    spawned, record, detail, probes, _tui = _attempt(
        monkeypatch, tmp_path, log_text="claude_tui_stalled", tail="",
        source="login", expires_at=time.time() - 5)
    assert probes == [] and record["auth_state"] == "healthy"
    assert detail == "claude_seat_login_token_expired"
    assert "claude_seat_login_token_expired" in spawned.seat_notices
    assert _board(spawned)[1] == ["claude_seat_login_token_expired"]


def test_attempts_in_sequence_decide_auth_each_on_their_own(monkeypatch, tmp_path):
    _s, rejected, rejected_detail, *_ = _auth_rejection(monkeypatch, tmp_path)
    spawned, failed, detail, probes, _t = _tui_failure(monkeypatch, tmp_path)
    assert rejected_detail == "claude_seat_token_rejected"
    assert failed["auth_state"] == "healthy" and probes == []
    assert detail == "claude_tui_workspace_trust_blocked"
    assert "claude_seat_token_rejected" not in spawned.seat_notices
    _s, again, again_detail, *_ = _auth_rejection(monkeypatch, tmp_path)
    assert again_detail == "claude_seat_token_rejected"
    assert {r["auth_state"] for r in (rejected, failed, again)} == {"healthy"}


def test_the_board_keeps_a_registered_tui_refusal_without_an_auth_notice(monkeypatch, tmp_path):
    from phase_loop_runtime.cli import _board_notices_json

    spawned, _record, detail, _probes, _tui = _tui_failure(monkeypatch, tmp_path)
    assert detail == "claude_tui_workspace_trust_blocked"
    board = pi.invoke_panel("ARTIFACT", ["claude"], spawn=lambda leg, art: spawned)
    (leg,) = board.legs
    assert leg.status == "DEGRADED" and leg.detail == "claude_tui_workspace_trust_blocked"
    assert [n.code for n in pi.refused_seat_notices(board.legs)] == [
        "claude_tui_workspace_trust_blocked"]
    codes = [n["code"] for n in _board_notices_json(board.legs)]
    assert "claude_tui_workspace_trust_blocked" in codes
    assert not any(code.startswith("leg_auth_") or code.endswith("_rejected") for code in codes)
