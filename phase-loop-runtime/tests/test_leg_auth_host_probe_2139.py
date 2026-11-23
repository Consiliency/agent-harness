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
