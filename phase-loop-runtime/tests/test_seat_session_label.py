"""A readable session name for Claude panel seats (`seat_session_label`).

An unnamed seat's title in the Claude app is a model's summary of its whole review prompt. These
tests pin the label, where it is and is not applied, that the retained evidence never carries it,
and that the sealed route (whose argv the HARDEN verifier holds token-for-token) is untouched.
No Claude CLI is run."""

from __future__ import annotations

import datetime
import hashlib
import types
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_credentials as sc
from phase_loop_runtime import seat_session_label as label

NOW = datetime.datetime(2026, 10, 9, 10, 42, tzinfo=datetime.timezone.utc)
STAMP = "10-09 10:42Z"


def _build(**kw):
    kw.setdefault("repo", Path("/work/agent-harness"))
    kw.setdefault("mode", "review")
    kw.setdefault("seat", "claude")
    kw.setdefault("environ", {})
    kw.setdefault("now", NOW)
    return label.build_label(**kw)


# --- the label ------------------------------------------------------------------------------

def test_the_label_names_the_repo_mode_seat_and_time():
    assert _build() == f"agent-harness · review · claude · {STAMP}"


def test_the_repo_is_the_directory_name_so_a_worktree_is_told_apart():
    assert _build(repo=Path("/home/u/workspace/worktrees/agent-harness-pytest-1357")).startswith(
        "agent-harness-pytest-1357 · review")


def test_advisory_mode_and_a_seat_key_show_in_the_label():
    assert _build(mode="advisory", seat="anthropic") == f"agent-harness · advisory · anthropic · {STAMP}"


def test_a_topic_appears_only_when_the_operator_sets_it():
    assert "topic" not in _build()
    named = _build(environ={label.ENV_TOPIC: "pytest runtime dependency"})
    assert named == f"agent-harness · review · pytest runtime dependency · claude · {STAMP}"


def test_the_topic_is_never_scraped_from_the_bundle_or_the_brief():
    """The label is in the seat's command line, readable by any local user on a shared host, and an
    advisory board's material can be sensitive. build_label has no way to receive material."""
    import inspect

    assert set(inspect.signature(label.build_label).parameters) == {"repo", "mode", "seat", "environ", "now"}
    assert "artifact" not in inspect.getsource(pi._seat_session_name)


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", " Off "])
def test_the_operator_can_turn_naming_off(value):
    assert _build(environ={label.ENV_SWITCH: value}) is None


@pytest.mark.parametrize("value", ["", "1", "true", "yes", "anything-else"])
def test_naming_is_on_by_default_and_for_any_other_value(value):
    assert _build(environ={label.ENV_SWITCH: value}) is not None


def test_the_label_is_bounded_and_the_topic_shrinks_first():
    long_topic = "x" * 500
    text = _build(repo=Path("/w/" + "r" * 60), environ={label.ENV_TOPIC: long_topic})
    assert text is not None and len(text) <= label.MAX_LABEL
    assert text.endswith(f"claude · {STAMP}") or STAMP in text      # the time is not what gets cut
    short = _build(environ={label.ENV_TOPIC: "x" * 500})
    assert len(short) <= label.MAX_LABEL and short.count("x") <= 40


@pytest.mark.parametrize("hostile, expected_start", [
    ("--model evil", "model evil"),                 # never read as an option
    ("-n x", "n x"),
    ("\x1b]0;owned\x07title", "0;owned title"),     # no terminal escape reaches a title
    ("line one\nline two\r\n", "line one line two"),
    ("a · b", "a b"),                               # the separator cannot be forged
    ("   ", ""),
])
def test_sanitising_removes_what_could_break_an_argument_or_a_terminal(hostile, expected_start):
    cleaned = label.sanitize(hostile)
    assert cleaned == expected_start
    assert not cleaned.startswith("-") and all(ch.isprintable() for ch in cleaned)


def test_a_label_always_starts_with_a_letter_or_digit():
    text = _build(repo=Path("/w/---"), environ={label.ENV_TOPIC: "--tools default"})
    assert text[0].isalnum() and not text.startswith("-")


def test_nothing_usable_gives_no_label_and_never_raises():
    assert _build(repo=None, mode="", seat="") is not None          # the time alone still names it
    assert label.build_label(repo=object(), mode="review", seat="x", environ={}) is None
    assert label.build_label(repo=Path("/w/r"), mode="review", seat="x", environ=None) is not None


def test_the_helper_derives_the_name_from_the_repo_the_mode_and_the_seat():
    named = pi._seat_session_name(Path("/work/agent-harness"), "review", "anthropic", "claude")
    assert named.startswith("agent-harness · review · anthropic · ")
    assert pi._seat_session_name(Path("/work/r"), "review", None, "claude").startswith("r · review · claude · ")


# --- where it is applied --------------------------------------------------------------------

LABEL = f"agent-harness · review · claude · {STAMP}"


def _jail():
    return types.SimpleNamespace(leg="claude", provider_argv0="/seat/bin/claude")


def test_the_non_brokered_builder_adds_the_name_and_is_otherwise_unchanged(tmp_path):
    plain = pi._claude_tui_command(tmp_path, tmp_path)
    named = pi._claude_tui_command(tmp_path, tmp_path, session_name=LABEL)
    assert named == [*plain, "--name", LABEL]
    assert "--name" not in plain


def test_the_jailed_builder_adds_the_name_and_is_otherwise_unchanged():
    plain = pi._broker_claude_tui_command(model=None, effort=None, session_id="s", sandboxed=_jail())
    named = pi._broker_claude_tui_command(model=None, effort=None, session_id="s", sandboxed=_jail(),
                                          session_name=LABEL)
    assert named == [*plain, "--name", LABEL] and "--name" not in plain


def test_the_sealed_argv_is_never_renamed():
    """The HARDEN evidence verifier holds the sealed Claude argv token-for-token
    (scripts/verify_harden_evidence.py broker_argv_grammar); a name would fail it."""
    plain = pi._broker_claude_tui_command(model=None, effort=None, session_id="s")
    named = pi._broker_claude_tui_command(model=None, effort=None, session_id="s", session_name=LABEL)
    assert named == plain and "--name" not in named


def test_a_default_name_is_none_so_every_existing_caller_is_unchanged(tmp_path):
    assert "--name" not in pi._claude_tui_command(tmp_path, tmp_path, "claude-opus-5-5", "high")
    assert pi._claude_tui_command(tmp_path, tmp_path, session_name=None) == pi._claude_tui_command(tmp_path, tmp_path)


def _drive_jailed_leg(monkeypatch, tmp_path, *, session_name):
    """Run the real jailed leg with the jail, the PTY session and the in-H readers faked."""
    jail = types.SimpleNamespace(
        leg="claude", provider_argv0="/seat/bin/claude", env={"HOME": "/seat/home"},
        profile_digest="d" * 64, profile_id="jail", filter_digest="f" * 64,
        redacted_owner=lambda: ["bwrap", "--"], seccomp_fd=-1)
    seat = types.SimpleNamespace(
        jail=jail, probe_jail=jail, seat_dir=tmp_path / "seat", review_dir=tmp_path / "review",
        holder_pid=1, token=b"TOKEN", notices=[])
    seen: dict[str, object] = {}

    def run(**kwargs):
        seen["command"] = kwargs["command"]
        return 0, "a review text", "", ""

    monkeypatch.setattr(pi, "_run_claude_tui_session", run)
    monkeypatch.setattr(pi._seat_jail, "close_jail_fds", lambda _j: None)
    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", lambda *_a: [])
    monkeypatch.setattr(pi._seat_uid, "read_in_h", lambda *_a: b"")
    evidence: dict[str, object] = {}
    pi._exec_jailed_claude_leg(
        seat, timeout_s=60, backstop_s=60, model=None, effort=None, prompt="P",
        broker_evidence=evidence, session_name=session_name)
    return seen["command"], evidence


def test_the_jailed_leg_launches_with_the_name_but_retains_only_a_placeholder(monkeypatch, tmp_path):
    command, evidence = _drive_jailed_leg(monkeypatch, tmp_path, session_name=LABEL)
    assert command[-2:] == ["--name", LABEL]
    shape = evidence["provider_argv_shape"]
    assert shape[-2:] == ("--name", "<CLAUDE_SESSION_NAME>")
    assert LABEL not in shape and "agent-harness" not in "\0".join(shape)         # nothing about the repo
    assert evidence["provider_argv_sha256"] == hashlib.sha256("\0".join(shape).encode()).hexdigest()


def test_the_jailed_leg_without_a_name_retains_the_shape_it_always_did(monkeypatch, tmp_path):
    command, evidence = _drive_jailed_leg(monkeypatch, tmp_path, session_name=None)
    assert "--name" not in command and "--name" not in evidence["provider_argv_shape"]


# --- through the real spawn -----------------------------------------------------------------

def test_the_jailed_route_through_the_production_spawn_passes_the_name(monkeypatch, tmp_path):
    from test_seat_login_wait_a3_1166 import _spawn

    captured: dict[str, object] = {}

    def jailed_leg(seat, **kwargs):
        captured.update(kwargs)
        return "OK", "a review"

    monkeypatch.delenv(label.ENV_SWITCH, raising=False)
    monkeypatch.delenv(label.ENV_TOPIC, raising=False)
    _spawn(monkeypatch, tmp_path, sc.LOGIN_READY, jailed_leg=jailed_leg)
    name = captured["session_name"]
    assert name.startswith(f"{tmp_path.name} · review · claude · ") and len(name) <= label.MAX_LABEL


def test_turning_naming_off_reaches_the_jailed_route(monkeypatch, tmp_path):
    from test_seat_login_wait_a3_1166 import _spawn

    captured: dict[str, object] = {}
    monkeypatch.setenv(label.ENV_SWITCH, "0")
    _spawn(monkeypatch, tmp_path, sc.LOGIN_READY,
           jailed_leg=lambda seat, **kw: (captured.update(kw), ("OK", "x"))[1])
    assert captured["session_name"] is None


def test_the_non_brokered_route_through_the_spawn_passes_the_name(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def tui(review_dir, out_dir, timeout_s, artifact, **kwargs):
        captured.update(kwargs)
        return "OK", "advice"

    repo = tmp_path / "client-repo"
    repo.mkdir()
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path / "staging"))
    monkeypatch.setattr(pi, "_exec_claude_tui_leg", tui)
    monkeypatch.setenv(label.ENV_TOPIC, "ratify the plan")
    pi._default_spawn("claude", "ARTIFACT", mode="advisory", repo_dir=repo, seat_key="anthropic")
    name = captured["session_name"]
    assert name.startswith("client-repo · advisory · ratify the plan · anthropic · ")
