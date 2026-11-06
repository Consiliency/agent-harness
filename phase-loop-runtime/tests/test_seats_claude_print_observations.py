"""SEATS CLAUDE lane B: the print transport's observations are bounded and metadata-only,
and never change admission."""

from __future__ import annotations

import json

import pytest

from phase_loop_runtime import claude_print_observations as obs
from phase_loop_runtime import claude_seat_print as cp

TOKEN = b"fake-seat-token-" + b"o" * 32
SESSION = "s-1"
SECRET_TEXT = "private review body that names /home/someone/project"


def _frames(*events) -> bytes:
    return b"".join(json.dumps(event).encode() + b"\n" for event in events)


def _init(**extra):
    return {"type": "system", "subtype": "init", "apiKeySource": "none",
            "session_id": SESSION, "model": "claude-opus-5-5", **extra}


def _assistant(content, **extra):
    return {"type": "assistant", "session_id": SESSION,
            "message": {"role": "assistant", "model": "claude-opus-5-5", "content": content},
            **extra}


def _user(content):
    return {"type": "user", "session_id": SESSION, "message": {"role": "user", "content": content}}


def _result(text="Fine.\n\nAGREE"):
    return {"type": "result", "subtype": "success", "is_error": False, "result": text,
            "session_id": SESSION}


def _admission(data: bytes, observations) -> tuple:
    stream = cp.StreamAdmission(token=TOKEN, session_id=SESSION, observations=observations)
    stream.feed(data)
    stream.finish()
    return (stream.violation, stream.admitted(0), stream.result_text, stream.results)


def _observations():
    return obs.ClaudePrintObservations(SESSION, "claude-opus-5-5", lambda _t: "unknown")


READ = [{"type": "tool_use", "id": "toolu_1", "name": "Read",
         "input": {"file_path": "/seat/tree/a.txt"}}]
READ_DONE = [{"type": "tool_result", "tool_use_id": "toolu_1", "content": SECRET_TEXT}]


def test_a_completed_read_of_the_staged_tree_is_observed_as_a_digest_only():
    data = _frames(_init(), _assistant(READ), _user(READ_DONE),
                   _assistant([{"type": "text", "text": SECRET_TEXT}]), _result())
    observations = _observations()
    assert _admission(data, observations)[:2] == (None, True)
    snapshot = observations.snapshot()
    assert snapshot["model_status"] == "match"
    assert snapshot["tools"][0]["read_completed"] is True
    rendered = json.dumps(snapshot)
    for leaked in (SECRET_TEXT, "/seat/tree/a.txt", "toolu_1", "someone"):
        assert leaked not in rendered


@pytest.mark.parametrize("events", [
    # malformed and replayed observation frames
    (_init(), _assistant(READ), _assistant(READ), _result()),
    (_init(), _user(READ_DONE), _result()),
    (_init(), _assistant([{"type": "mystery"}]), _result()),
    (_init(), _assistant(READ, parent_tool_use_id="toolu_9"), _result()),
    (_init(), {"type": "assistant", "session_id": SESSION, "message": "not a dict"}, _result()),
    (_init(), _assistant(READ, uuid="u-1"), _user(READ_DONE) | {"uuid": "u-1"}, _result()),
])
def test_invalid_observations_never_change_admission(events):
    data = _frames(*events)
    with_obs = _admission(data, _observations())
    without = _admission(data, None)
    assert with_obs == without
    assert with_obs[:2] == (None, True)


def test_a_wrong_model_is_a_diagnostic_never_a_refusal():
    other = {"role": "assistant", "model": "claude-haiku-4-5", "content": [{"type": "text", "text": "x"}]}
    data = _frames(_init(model="claude-haiku-4-5"),
                   _assistant([]) | {"message": other}, _result())
    observations = _observations()
    assert _admission(data, observations)[:2] == (None, True)
    assert observations.snapshot()["model_status"] == "mismatch"


def test_observations_are_bounded():
    observations = _observations()
    frames = [_init()] + [_assistant([{"type": "text", "text": f"n{i}"}])
                          for i in range(obs.MAX_EVENTS + 20)] + [_result()]
    _admission(_frames(*frames), observations)
    snapshot = observations.snapshot()
    assert snapshot["truncated"] is True and snapshot["valid"] is False
    assert snapshot["event_count"] <= obs.MAX_EVENTS
    assert len(json.dumps(snapshot)) < 64 << 10


def test_an_observation_crash_is_contained():
    class Broken(obs.ClaudePrintObservations):
        def event(self, event):
            raise RuntimeError("observer bug")

    observations = Broken(SESSION, "claude-opus-5-5", lambda _t: "unknown")
    data = _frames(_init(), _result())
    assert _admission(data, observations)[:2] == (None, True)
    assert observations.snapshot()["valid"] is False


def test_the_fable_model_family_is_a_known_model():
    observations = obs.ClaudePrintObservations(SESSION, "claude-fable-5-1", lambda _t: "unknown")
    _admission(_frames(_init(model="claude-fable-5-1"),
                       _assistant([{"type": "text", "text": "x"}]) | {
                           "message": {"role": "assistant", "model": "claude-fable-5-1",
                                       "content": [{"type": "text", "text": "x"}]}},
                       _result()), observations)
    assert observations.snapshot()["model_status"] == "match"
