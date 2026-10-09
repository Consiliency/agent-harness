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


def test_the_label_is_bounded_and_the_topic_is_what_gives_way_first():
    seat = "claude:claude-opus-5-5:high:correctness"
    plain = _build(seat=seat)
    topical = _build(seat=seat, environ={label.ENV_TOPIC: "x" * 500})
    for text in (plain, topical):
        assert len(text) <= label.MAX_LABEL and text.endswith(STAMP)
    # Only the topic is shortened; the repo, the mode and the whole seat part survive it.
    assert topical.startswith("agent-harness · review · ") and "claude-opus-5-5:high:correctness" in topical
    assert topical.count("x") < 40 and plain.count("x") == 0


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
    keyed = pi._seat_session_name(Path("/work/r"), "review", "claude:claude-opus-5-5:high:correctness", "claude")
    assert keyed.startswith("r · review · claude-opus-5-5:high:correctness · ")


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


# --- the seat part, and the length budget (president ruling on agent-harness#1404) ---------------

SEAT_A = "claude:claude-opus-5-5:high:correctness"
SEAT_B = "claude:claude-opus-5-5:high:adversarial"


def test_the_seat_part_drops_the_leading_harness_segment():
    assert _build(seat=SEAT_A) == f"agent-harness · review · claude-opus-5-5:high:correctness · {STAMP}"
    assert _build(seat="@openai:gpt-6-astra:max") == f"agent-harness · review · gpt-6-astra:max · {STAMP}"
    assert _build(seat="claude") == f"agent-harness · review · claude · {STAMP}"          # no segment to drop
    assert _build(seat="claude:") == f"agent-harness · review · claude · {STAMP}"         # nothing left: keep it


def test_provider_seam_preserves_distinct_claude_seat_names(monkeypatch):
    """Codex's F007 falsifier, ported: two Claude seats launched through the provider seam in the
    same minute must not get the same name. Red before the seat identity reached the spawn."""
    names = []
    build = label.build_label
    monkeypatch.setattr(label, "build_label", lambda **kwargs: build(**kwargs, environ={}, now=NOW))

    def spawn(leg, artifact, **kwargs):
        names.append(pi._seat_session_name(kwargs["repo_dir"], kwargs["mode"], kwargs.get("seat_key"), leg))
        return "OK", "AGREE"

    monkeypatch.setattr(pi, "_default_spawn", spawn)
    direct = [pi._seat_session_name(Path("/work/r"), "review", key, "claude") for key in (SEAT_A, SEAT_B)]
    assert direct[0] != direct[1]
    for key in (SEAT_B, SEAT_A):
        result = pi._default_spawn_via_provider(
            "claude", "ARTIFACT", repo_dir=Path("/work/r"), mode="review",
            model="claude-opus-5-5", effort="high", seat_key=key,
        )
        assert result == ("OK", "AGREE")
    assert len(names) == 2
    assert names[0] != names[1], names


def _run_board_of_two_claude_seats(monkeypatch, spawn):
    """invoke_board over two Claude seats that differ only in lens, through the sanctioned seam,
    with `_default_spawn` replaced by ``spawn`` (so the real provider wrapper and worker run)."""
    import tempfile
    from unittest.mock import patch

    from harden_tdd_guard import invoke_sanctioned_board_control
    from phase_loop_runtime.advisor_board import matrix as matrix_module
    from phase_loop_runtime.advisor_board.schema import Board, Seat

    build = label.build_label
    monkeypatch.setattr(label, "build_label", lambda **kwargs: build(**kwargs, environ={}, now=NOW))
    board = Board(name="two-claude", purpose="brainstorm", seats=tuple(
        Seat(model="claude-opus-5-5", effort="high", harness="claude", lens=lens)
        for lens in ("correctness", "adversarial")))
    assert {seat.seat_key for seat in board.seats} == {SEAT_A, SEAT_B}
    with (
        tempfile.TemporaryDirectory(prefix="seat-name-repo-") as td,
        patch.object(matrix_module.DEFAULT_HARNESS_REGISTRY, "is_available", return_value=True),
        patch.object(pi, "_default_spawn", side_effect=spawn),
    ):
        invoke_sanctioned_board_control(board, "ARTIFACT", repo_dir=Path(td), require_live_matrix_probe=True)


def test_a_board_of_two_claude_seats_that_differ_only_in_lens_gets_two_names(monkeypatch):
    """The production path: invoke_board -> its per-seat worker -> the provider seam -> _default_spawn.
    `_default_spawn` must not be handed a seat_key (the CS-0.8 same-signature guard and the placement
    round id are pinned to that call), so the seat identity has to travel another way."""
    calls: list[tuple[dict, str | None]] = []

    def spawn(leg, artifact, **kwargs):
        calls.append((dict(kwargs), pi._seat_session_name(kwargs["repo_dir"], kwargs["mode"],
                                                          kwargs.get("seat_key"), leg)))
        return "OK", "Concrete advice for the question."

    _run_board_of_two_claude_seats(monkeypatch, spawn)
    names = [name for _kwargs, name in calls]
    assert len(names) == 2, names
    assert names[0] != names[1], names
    assert all(name.endswith(STAMP) for name in names)
    assert any(name.endswith(f"claude-opus-5-5:high:correctness · {STAMP}") for name in names)
    assert any(name.endswith(f"claude-opus-5-5:high:adversarial · {STAMP}") for name in names)
    assert all("seat_key" not in kwargs for kwargs, _name in calls)       # the call shape is unchanged


class _CountingVar:
    """The seat variable with its sets and resets counted, so a leak shows."""

    def __init__(self, inner):
        self.inner, self.sets, self.resets = inner, 0, 0

    def get(self, *default):
        return self.inner.get(*default)

    def set(self, value):
        self.sets += 1
        return self.inner.set(value)

    def reset(self, token):
        self.resets += 1
        return self.inner.reset(token)


def test_every_set_of_the_seat_variable_is_matched_by_a_reset_through_a_board(monkeypatch):
    """A pool thread keeps its context across tasks, so a value left behind by one seat would be read
    by the next. Counts every set and reset on the real board path, success and failure."""
    counting = _CountingVar(pi._SEAT_SESSION_SEAT)
    monkeypatch.setattr(pi, "_SEAT_SESSION_SEAT", counting)
    outcomes = iter(["ok", "boom"])

    def spawn(leg, artifact, **kwargs):
        if next(outcomes) == "boom":
            raise RuntimeError("seat failed")
        return "OK", "Concrete advice for the question."

    _run_board_of_two_claude_seats(monkeypatch, spawn)
    assert counting.sets == 2 and counting.resets == counting.sets, (counting.sets, counting.resets)
    assert counting.inner.get() is None


def test_the_seat_variable_never_outlives_the_spawn_that_set_it(monkeypatch):
    seen = []

    def spawn(leg, artifact, **kwargs):
        seen.append(pi._SEAT_SESSION_SEAT.get())
        if kwargs.get("model") == "boom":
            raise RuntimeError("seat failed")
        return "OK", "x"

    monkeypatch.setattr(pi, "_default_spawn", spawn)
    assert pi._SEAT_SESSION_SEAT.get() is None
    pi._default_spawn_via_provider("claude", "A", repo_dir=Path("/w/r"), mode="review", seat_key=SEAT_A)
    assert seen == [SEAT_A] and pi._SEAT_SESSION_SEAT.get() is None
    try:
        pi._default_spawn_via_provider("claude", "A", repo_dir=Path("/w/r"), mode="review",
                                       model="boom", seat_key=SEAT_B)
    except Exception:
        pass
    assert pi._SEAT_SESSION_SEAT.get() is None                              # reset on the failure path too


def test_no_seat_key_means_the_variable_stays_unset(monkeypatch):
    seen = []
    monkeypatch.setattr(pi, "_default_spawn",
                        lambda leg, artifact, **kw: (seen.append(pi._SEAT_SESSION_SEAT.get()), ("OK", "x"))[1])
    pi._default_spawn_via_provider("claude", "A", repo_dir=Path("/w/r"), mode="review")
    assert seen == [None]


def test_the_spawn_call_keeps_its_exact_signature_on_the_non_capture_path():
    """Nothing but the variable carries the seat: `_default_spawn` is called exactly as before."""
    from unittest.mock import patch

    with patch.object(pi, "_default_spawn", return_value=("OK", "AGREE")) as spawn:
        pi._default_spawn_via_provider("claude", "bundle", repo_dir="/tmp/repo", mode="review",
                                       model="m1", seat_key=SEAT_A)
    spawn.assert_called_once_with("claude", "bundle", repo_dir="/tmp/repo", mode="review", model="m1")


# (c) the budget: the label is at most 80 characters and always ends with the stamp.

def test_a_long_repo_and_a_long_seat_still_end_with_the_stamp():
    repo = Path("/w/agent-harness-claude-seat-session-names-1404")
    assert len(repo.name) == 44
    text = _build(repo=repo, mode="advisory", seat="claude:claude-opus-5-5:high:authority-verification")
    assert len(text) <= label.MAX_LABEL and text.endswith(STAMP)
    # The seat part is what is kept: the repo gives way before it does.
    assert "claude-opus-5-5:high:authority-verification" in text and " · advisory · " in text


def test_a_forty_character_repo_and_a_forty_character_seat_fit():
    text = _build(repo=Path("/w/" + "r" * 40), mode="review", seat="s" * 40)
    assert len(text) <= label.MAX_LABEL and text.endswith(STAMP) and "s" * 40 in text


@pytest.mark.parametrize("repo_len", [0, 1, 8, 20, 44, 90])
@pytest.mark.parametrize("seat_len", [0, 6, 33, 43, 90])
@pytest.mark.parametrize("topic_len", [0, 12, 200])
@pytest.mark.parametrize("mode", ["review", "advisory"])
def test_the_label_is_always_within_budget_and_ends_with_the_stamp(repo_len, seat_len, topic_len, mode):
    text = _build(
        repo=Path("/w/" + ("r" * repo_len)) if repo_len else Path("/"),
        mode=mode, seat=("claude:" + "s" * seat_len) if seat_len else "",
        environ={label.ENV_TOPIC: "t" * topic_len} if topic_len else {})
    assert text is not None and len(text) <= label.MAX_LABEL
    assert text.endswith(f" · {STAMP}") and text[0].isalnum() and text.isprintable()
    assert mode in text.split(" · ")                                        # the mode is reserved


def test_the_order_in_which_the_label_gives_way_is_topic_then_repo_then_seat():
    seat = "claude:" + "s" * 26
    base = dict(repo=Path("/w/" + "r" * 20), mode="review", seat=seat)
    no_topic = _build(**base)                                                # 73 characters: it all fits
    assert "r" * 20 in no_topic and "s" * 26 in no_topic and len(no_topic) < label.MAX_LABEL
    topical = _build(**base, environ={label.ENV_TOPIC: "t" * 40})            # 116 untrimmed
    assert len(topical) <= label.MAX_LABEL and topical.endswith(STAMP)
    assert "r" * 20 in topical and "s" * 26 in topical and 0 < topical.count("t") < 40   # the topic gave way alone
    tight = _build(repo=Path("/w/" + "r" * 44), mode="advisory", seat="claude:" + "s" * 43)
    assert "s" * 43 in tight and 0 < tight.count("r") < 44                   # the repo was cut, the seat was not
    over = _build(repo=Path("/w/" + "r" * 44), mode="advisory", seat="claude:" + "s" * 64)
    assert len(over) <= label.MAX_LABEL and over.endswith(STAMP)
    parts = over.split(" · ")
    assert parts[0] == "advisory" and parts[-1] == STAMP and len(parts) == 3   # the repo went altogether
    assert 0 < parts[1].count("s") < 64                                      # and the seat was cut last, from its front


def test_seats_that_differ_only_in_their_lens_keep_distinct_names_when_the_seat_must_be_cut():
    common = "claude-opus-5-5-with-a-very-long-descriptive-model-name-that-forces-a-cut:high:"
    a = _build(repo=Path("/w/" + "r" * 44), mode="advisory", seat=f"claude:{common}correctness")
    b = _build(repo=Path("/w/" + "r" * 44), mode="advisory", seat=f"claude:{common}adversarial")
    assert a != b and len(a) <= label.MAX_LABEL and len(b) <= label.MAX_LABEL
    assert a.endswith(STAMP) and b.endswith(STAMP)


def test_each_part_has_its_own_ceiling_even_when_there_is_room():
    """Without the per-part ceilings the budget would hand all the room to whichever part is long."""
    long = "x" * 100
    topical = _build(repo=Path("/w/r"), mode="review", seat="", environ={label.ENV_TOPIC: long})
    assert topical.split(" · ")[2] == "x" * 40                                   # the topic, capped at 40
    wide_repo = _build(repo=Path("/w/" + "r" * 100), mode="review", seat="")
    assert wide_repo.split(" · ")[0] == "r" * 40                                 # the repo, capped at 40
    wide_mode = _build(repo=Path("/w/r"), mode="m" * 50, seat="")
    assert wide_mode.split(" · ")[1] == "m" * 12                                 # the mode, capped at 12
    wide_seat = _build(repo=None, mode="review", seat="claude:" + "s" * 200)
    assert len(wide_seat.split(" · ")[1]) <= 120 and wide_seat.endswith(STAMP)   # the seat, capped before the budget


def test_the_reserved_parts_alone_always_fit():
    """The mode and the stamp are never trimmed, so they must fit with room to spare."""
    text = _build(repo=None, mode="m" * 200, seat="")
    assert text == f"{'m' * 12} · {STAMP}" and len(text) < label.MAX_LABEL
