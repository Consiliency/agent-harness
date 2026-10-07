"""Stop a finished Agent View session only after its closeout is verified.

No live Claude: a fake adapter records the stop calls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from phase_loop_runtime import agent_view_cleanup as cleanup

SESSION = "5e271479"
VERIFIED = {"automation_status": "complete", "native_closeout_payload": {"terminal_status": "complete"}}


class _Adapter:
    def __init__(self, stop_result="stopped", raises=None):
        self.calls: list[tuple[str, object]] = []
        self._stop_result, self._raises = stop_result, raises

    def stop(self, agent_id, *, cwd=None):
        self.calls.append((agent_id, cwd))
        if self._raises:
            raise self._raises
        return SimpleNamespace(stop_result=self._stop_result)


def _result(**overrides):
    route = {
        "route": "claude_agent_view", "session_id": SESSION, "status": "done",
        "artifacts": [{"kind": "claude_agent_view_lifecycle", "session_id": SESSION, "state": "done"}],
    }
    route.update(overrides.pop("route", {}))
    fields = {"dry_run": False, "claude_route": "claude_agent_view", "claude_route_result": route}
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _stop(result, automation=VERIFIED, adapter=None, environ=None):
    adapter = adapter or _Adapter()
    return cleanup.stop_verified_session(result, automation, cwd="/work", adapter=adapter, environ=environ or {}), adapter


def test_a_verified_closeout_stops_the_session_exactly_once():
    outcome, adapter = _stop(_result())
    assert outcome == {"session_id": SESSION, "action": "stopped", "reason": "verified"}
    assert adapter.calls == [(SESSION, "/work")]


@pytest.mark.parametrize("automation, reason", [
    ({}, "closeout_not_verified"),                                                  # no closeout at all
    (None, "closeout_not_verified"),
    ({"native_closeout_payload": {}}, "closeout_not_verified"),                     # empty payload
    ({"native_closeout_payload": "x"}, "closeout_not_verified"),                    # not a mapping
    ({**VERIFIED, "automation_parse_error": "bad literal"}, "closeout_not_verified"),
    ({**VERIFIED, "native_closeout_extraction_failure": {"reason": "malformed"}}, "closeout_not_verified"),
    ({**VERIFIED, "baml_worker_outage": "died"}, "closeout_not_evaluated"),         # NOT evaluated
])
def test_a_closeout_that_failed_schema_verification_leaves_the_session_visible(automation, reason):
    outcome, adapter = _stop(_result(), automation)
    assert outcome["action"] == "kept" and outcome["reason"] == reason
    assert adapter.calls == []


@pytest.mark.parametrize("overrides, reason", [
    ({"dry_run": True}, "dry_run"),
    ({"claude_route": "claude_print"}, "not_agent_view"),
    ({"claude_route_result": None}, "no_route_result"),
    ({"route": {"status": "blocked"}}, "route_not_done"),
    ({"route": {"session_id": "preflight"}}, "no_session_id"),
    ({"route": {"session_id": "unknown"}}, "no_session_id"),
    ({"route": {"session_id": "a b; rm -rf /"}}, "no_session_id"),
    ({"route": {"artifacts": []}}, "lifecycle_not_done"),
    ({"route": {"artifacts": [{"kind": "claude_agent_view_lifecycle", "session_id": SESSION, "state": "blocked"}]}},
     "lifecycle_not_done"),
    ({"route": {"artifacts": [{"kind": "claude_agent_view_lifecycle", "session_id": "other", "state": "done"}]}},
     "lifecycle_not_done"),
])
def test_only_a_finished_agent_view_launch_is_eligible(overrides, reason):
    outcome, adapter = _stop(_result(**overrides))
    assert outcome["action"] == "kept" and outcome["reason"] == reason
    assert adapter.calls == []


def test_the_environment_can_keep_finished_sessions_for_debugging():
    outcome, adapter = _stop(_result(), environ={cleanup.KEEP_ENV: "1"})
    assert outcome == {"session_id": SESSION, "action": "kept", "reason": "kept_by_environment"}
    assert adapter.calls == []


def test_a_failed_stop_is_reported_and_never_raises():
    outcome, _ = _stop(_result(), adapter=_Adapter(stop_result="failed"))
    assert outcome == {"session_id": SESSION, "action": "stop_failed", "reason": "stop_command_failed"}
    outcome, _ = _stop(_result(), adapter=_Adapter(raises=OSError("boom")))
    assert outcome["action"] == "stop_failed" and outcome["reason"] == "OSError"


def test_the_session_is_stopped_and_never_removed():
    class _Strict(_Adapter):
        def remove(self, *a, **k):
            raise AssertionError("claude rm deletes the conversation; cleanup must only stop")

    outcome, _ = _stop(_result(), adapter=_Strict())
    assert outcome["action"] == "stopped"


def test_the_runner_stops_the_session_right_after_it_parses_the_closeout():
    """Wiring guard: the one call site sits directly after the closeout is parsed, so the stop can
    never run before verification, and removing the call cannot go unnoticed."""
    import inspect

    from phase_loop_runtime import runner

    lines = inspect.getsource(runner).splitlines()
    calls = [i for i, line in enumerate(lines) if "stop_verified_agent_view_session(result, child_automation" in line]
    assert len(calls) == 1
    window = "\n".join(lines[max(0, calls[0] - 4):calls[0]])
    assert "child_automation = _parsed_child_automation(result, spec)" in window
