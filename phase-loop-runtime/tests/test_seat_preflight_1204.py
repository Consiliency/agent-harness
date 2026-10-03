"""agent-harness#1204: board-level pointer-brief preflight (maintainer ruling, policy (ii)).

A seat whose route cannot open a pointer brief's files is warned BEFORE any seat launches,
still runs, and its verdict is not source-grounded, so it never counts as a passing seat.
The treesitter-chunker#114 shape (agent-harness#1132 acceptance evidence) is the inverted
characterization test below.
"""

from __future__ import annotations

import io
import json
import types
from contextlib import redirect_stderr, redirect_stdout

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_preflight as sp
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult

from .harden_tdd_guard import harden_require, invoke_sanctioned_board_control

UNREADABLE = "seat_pointer_brief_unreadable"


def _seat(leg: str, key: str | None = None, model: str | None = "m"):
    return types.SimpleNamespace(harness=leg, seat_key=key or f"{leg}:a", model=model)


def _preflight(legs, *, staged=True, review=True, under_claude_code=False):
    return sp.pointer_brief_preflight(
        [_seat(leg) for leg in legs], staged_tree=staged,
        brokered=lambda leg: review,
        native_fill=lambda seat, leg: leg == "claude" and under_claude_code,
        sandbox_usable_by=pi.sandbox_usable_by,
    )


# --------------------------------------------------------------------------------------
# (A) Which seats cannot open the brief's files, decided from the route facts alone.
# --------------------------------------------------------------------------------------

def test_brokered_seats_without_file_tools_are_warned_on_a_staged_tree():
    notices = _preflight(["codex", "claude", "gemini", "grok"])
    assert [(n.leg, n.code) for n in notices] == [("claude", UNREADABLE), ("gemini", UNREADABLE)]


def test_a_native_fill_claude_seat_has_file_access():
    notices = _preflight(["claude", "gemini"], under_claude_code=True)
    assert [n.leg for n in notices] == ["gemini"]


def test_without_a_staged_tree_no_brokered_seat_can_open_the_files():
    notices = _preflight(["codex", "claude", "gemini", "grok"], staged=False)
    assert [n.leg for n in notices] == ["codex", "claude", "gemini", "grok"]


def test_a_non_brokered_route_with_a_tree_can_open_the_files():
    assert _preflight(["codex", "claude", "gemini", "grok"], review=False) == ()


def test_the_notice_is_a_closed_literal():
    with pytest.raises(ValueError):
        sp.SeatPreflightNotice("seat_pointer_brief_unreadable_x", "s", "claude")
    notice = sp.SeatPreflightNotice(UNREADABLE, "claude:a", "claude")
    assert notice.as_json() == {"code": UNREADABLE, "seat_key": "claude:a", "leg": "claude",
                                "what": sp.NOTICE_TEXT[UNREADABLE][0],
                                "why": sp.NOTICE_TEXT[UNREADABLE][1],
                                "fix": sp.NOTICE_TEXT[UNREADABLE][2]}


# --------------------------------------------------------------------------------------
# The chunker#114 shape, INVERTED: through the real invoker, the notice exists before the
# first seat launches, every seat still runs, and the two tool-less seats are ungrounded.
# --------------------------------------------------------------------------------------

def _chunker114_board(tmp_path, *, pointer_brief=True, verdict="PARTIALLY AGREE"):
    harden_require("review-leg-isolation")
    events: list[tuple[str, object]] = []

    def spawn(leg: str, artifact: str):
        events.append(("launch", leg))
        return "OK", f"{leg}: could not open the referenced files.\n{verdict}"

    kwargs = {"pointer_brief": True,
              "on_seat_preflight": lambda notices: events.append(
                  ("preflight", sorted(n.leg for n in notices)))} if pointer_brief else {}
    result = invoke_sanctioned_board_control(
        DEFAULT_BOARD, "short pointer brief: open the staged diff and plan",
        spawn=spawn, base_env={}, max_concurrency=1, **kwargs,
    )
    return result, events


@pytest.fixture
def staged_tree(monkeypatch, tmp_path):
    """The review stages an exact-head tree (the production default). The chunker#114 seats
    have no seat credential, so this host's own seat token, Claude login and jail passes are
    not read: with them, the preflight would put a Claude seat on the jailed route
    (agent-harness#1132)."""
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "no-seat-state"))
    # ... nor this host's Claude login (plan amendment A1): these seats have no credential.
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude-login"))


def test_chunker114_shape_the_preflight_warns_before_any_launch_and_the_seats_still_run(
        tmp_path, staged_tree, monkeypatch):
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    result, events = _chunker114_board(tmp_path)
    assert events[0] == ("preflight", ["claude", "gemini"])           # before ANY launch
    assert sorted(leg for kind, leg in events[1:] if kind == "launch") == sorted(
        s.harness for s in DEFAULT_BOARD.seats)                         # every seat still runs
    by_leg = {leg.leg: leg for leg in result.legs}
    assert all(leg.usable for leg in result.legs)
    assert not by_leg["claude"].source_grounded and not by_leg["gemini"].source_grounded
    assert by_leg["codex"].source_grounded and by_leg["grok"].source_grounded
    assert [n.code for n in by_leg["claude"].seat_preflight_notices] == [UNREADABLE]
    assert {leg.leg for leg in result.grounded_usable_legs} == {"codex", "grok"}


def test_without_a_pointer_brief_nothing_is_warned_or_marked(tmp_path, staged_tree):
    result, events = _chunker114_board(tmp_path, pointer_brief=False)
    assert [kind for kind, _ in events] == ["launch"] * len(DEFAULT_BOARD.seats)
    assert len(result.usable_legs) == len(DEFAULT_BOARD.seats)
    assert result.grounded_usable_legs == result.usable_legs
    assert all(leg.source_grounded and not leg.seat_preflight_notices for leg in result.legs)


# --------------------------------------------------------------------------------------
# (ii) Counting: an ungrounded seat never counts as a passing grounded seat, and marking
# never removes an objection.
# --------------------------------------------------------------------------------------

def _leg(leg: str, verdict: str, *, grounded: bool) -> PanelLegResult:
    result = PanelLegResult(leg=leg, status="OK", text=f"finding one\n\n{verdict}",
                            seat_key=f"{leg}:a")
    if not grounded:
        # A one-leg list: the leg is at position 0 of what it is attached against.
        pi.attach_seat_preflight_notices(
            [result], [sp.SeatPreflightNotice(UNREADABLE, f"{leg}:a", leg, 0)])
    return result


def test_president_input_does_not_count_an_ungrounded_pass_but_keeps_its_disagree():
    seats = [_seat("claude"), _seat("gemini"), _seat("codex")]
    legs = [_leg("claude", "AGREE", grounded=False), _leg("gemini", "DISAGREE", grounded=False),
            _leg("codex", "AGREE", grounded=True)]
    findings = pi.president_findings_from_legs(seats, legs)
    assert any(f.endswith(f"[claude:a] not counted (not source-grounded: {UNREADABLE})")
               for f in findings)
    assert any("[gemini:a,codex:a] finding one" in f or "[gemini:a" in f and "finding one" in f
               for f in findings)


def test_governed_landing_needs_a_grounded_seat():
    from phase_loop_runtime import governed_review as gr

    only_ungrounded = PanelResult(legs=(_leg("claude", "AGREE", grounded=False),
                                        _leg("gemini", "AGREE", grounded=False)))
    held = gr._gate_result_from_panel(only_ungrounded, reviewed_sha=None)
    assert not held.promoted and held.reason == "no_usable_review"
    assert sum(f.code == UNREADABLE for f in held.findings) == 2
    grounded = PanelResult(legs=(_leg("claude", "AGREE", grounded=True),))
    assert gr._gate_result_from_panel(grounded, reviewed_sha=None).promoted   # control


def test_governed_ungrounded_disagree_still_blocks():
    from phase_loop_runtime import governed_review as gr

    panel = PanelResult(legs=(_leg("codex", "AGREE", grounded=True),
                              _leg("gemini", "DISAGREE", grounded=False)))
    result = gr._gate_result_from_panel(panel, reviewed_sha=None)
    assert not result.promoted
    assert any(f.severity == "block" for f in result.findings)


def test_governed_notice_finding_is_rendered_from_literals_and_warns():
    from phase_loop_runtime import governed_review as gr

    panel = PanelResult(legs=(_leg("codex", "AGREE", grounded=True),
                              _leg("claude", "AGREE", grounded=False)))
    findings = [f for f in gr._findings_from_panel(panel) if f.code == UNREADABLE]
    assert len(findings) == 1 and findings[0].severity == "warn"
    assert sp.NOTICE_TEXT[UNREADABLE][0] in findings[0].reason


def test_reviewer_floor_counts_grounded_seats_only():
    panel = PanelResult(legs=(_leg("codex", "AGREE", grounded=True),
                              _leg("claude", "AGREE", grounded=False)))
    assert len(panel.usable_legs) == 2
    assert [leg.leg for leg in sp.grounded_usable_legs(panel)] == ["codex"]


# --------------------------------------------------------------------------------------
# The advisor-board CLI: stderr before launch, the floor, and the payload.
# --------------------------------------------------------------------------------------

_REAL_COMPOSE = None


def _run_cli(tmp_path, monkeypatch, legs, *, pointer_brief=True, modes=()):
    """Drive ``advisor-board`` with composition, authorization and dispatch patched, so the
    run does not depend on which vendor CLIs this host has installed."""
    import os

    from phase_loop_runtime import cli
    from phase_loop_runtime.advisor_board import backing as backing_mod
    from phase_loop_runtime.advisor_board import composition as comp_mod

    global _REAL_COMPOSE
    if _REAL_COMPOSE is None:
        _REAL_COMPOSE = comp_mod.compose_review_board
    board = _REAL_COMPOSE(is_available=lambda vendor: True)
    monkeypatch.setattr(comp_mod, "compose_review_board", lambda *a, **k: board)
    monkeypatch.setattr(backing_mod, "prepare_review_composition_authorization", lambda: None)
    monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                        lambda *a, **k: object())
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    captured: dict[str, object] = {}

    def fake_invoke_board(board, artifact, **kwargs):
        captured.update(kwargs)
        if kwargs.get("on_seat_preflight") is not None:
            kwargs["on_seat_preflight"](tuple(n for leg in legs for n in leg.seat_preflight_notices))
        if modes:
            kwargs["on_seat_modes"](tuple(modes))
        return PanelResult(legs=tuple(legs))

    monkeypatch.setattr(cli, "invoke_board", fake_invoke_board, raising=False)
    monkeypatch.setattr(pi, "invoke_board", fake_invoke_board)
    artifact = tmp_path / "bundle.md"
    artifact.write_text("pointer brief\n")
    argv = ["advisor-board", str(artifact), "--json", "--advisory"]
    if pointer_brief:
        argv.append("--pointer-brief")
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue(), captured


def test_cli_pointer_brief_prints_preflight_and_floors_on_grounded_seats(tmp_path, monkeypatch):
    legs = [_leg("codex", "AGREE", grounded=True), _leg("grok", "AGREE", grounded=True),
            _leg("claude", "PARTIALLY AGREE", grounded=False),
            _leg("gemini", "PARTIALLY AGREE", grounded=False)]
    code, out, err, captured = _run_cli(tmp_path, monkeypatch, legs)
    assert captured.get("pointer_brief") is True
    assert f"advisor-board: preflight: seat claude:a (claude): {UNREADABLE}" in err
    payload = json.loads(out)
    assert payload["delivered_seats"] == 4 and payload["grounded_seats"] == 2
    assert payload["usable"] is False and code == 1                  # 2 grounded < floor 3
    assert [n["seat_key"] for n in payload["notices"]] == ["claude:a", "gemini:a"]
    assert {e["leg"]: e["source_grounded"] for e in payload["legs"]} == {
        "codex": True, "grok": True, "claude": False, "gemini": False}


def test_cli_pointer_brief_keeps_the_seat_notices_beside_the_preflight_notices(
        tmp_path, monkeypatch):
    # agent-harness#1132: a leg's seat notice and its preflight notice are both published;
    # the preflight list is appended to the seat notices, never put in their place.
    legs = [_leg("codex", "AGREE", grounded=True), _leg("grok", "AGREE", grounded=True),
            _leg("claude", "PARTIALLY AGREE", grounded=False)]
    object.__setattr__(legs[2], "_seat_notice_codes", ("claude_seat_token_missing",))
    _code, out, _err, _captured = _run_cli(tmp_path, monkeypatch, legs)
    payload = json.loads(out)
    assert [n["code"] for n in payload["notices"]] == ["claude_seat_token_missing", UNREADABLE]
    claude = next(e for e in payload["legs"] if e["leg"] == "claude")
    assert [n["code"] for n in claude["notices"]] == ["claude_seat_token_missing", UNREADABLE]


def test_cli_without_pointer_brief_keeps_the_payload_unchanged(tmp_path, monkeypatch):
    legs = [_leg(leg, "AGREE", grounded=True) for leg in ("codex", "grok", "claude")]
    code, out, _err, captured = _run_cli(tmp_path, monkeypatch, legs, pointer_brief=False)
    assert "pointer_brief" not in captured and code == 0
    payload = json.loads(out)
    # The `notices` keys belong to the seat notices (agent-harness#1132) and are always
    # present; without the flag the preflight adds nothing to them.
    assert "grounded_seats" not in payload and payload["notices"] == []
    assert all("source_grounded" not in e and e["notices"] == [] for e in payload["legs"])


def test_the_stream_record_is_published_atomically(tmp_path):
    notices = _preflight(["codex", "claude"])
    path = sp.write_preflight_record(tmp_path / "stream", notices)
    record = json.loads(path.read_text())
    assert record == {"schema": sp.PREFLIGHT_SCHEMA, "pointer_brief": True,
                      "notices": [n.as_json() for n in notices]}
    assert not path.with_name(path.name + ".tmp").exists()


def test_premerge_reviewer_floor_does_not_count_an_ungrounded_seat():
    from phase_loop_runtime.governed_premerge import run_governed_premerge_loop
    from phase_loop_runtime.governed_review import governed_planning_gate

    def loop(panel):
        return run_governed_premerge_loop(
            artifact="ART", author_executor="claude", run_mode="governed",
            available_legs=("codex", "gemini"),
            invoke=lambda **kw: governed_planning_gate(
                **kw, invoke=lambda art, pool, spawn=None: panel))

    grounded = PanelResult(legs=(_leg("codex", "AGREE", grounded=True),
                                 _leg("gemini", "AGREE", grounded=True)))
    assert loop(grounded).mergeable                                    # control: 2 grounded
    one_grounded = PanelResult(legs=(_leg("codex", "AGREE", grounded=True),
                                     _leg("gemini", "AGREE", grounded=False)))
    held = loop(one_grounded)
    assert not held.mergeable and held.reason == "below_reviewer_floor"


# --------------------------------------------------------------------------------------
# Board round 1 (agent-harness#1205): a native president RESUME keeps the marks the
# deferral persisted, and the pointer_brief flag is part of the run binding.
# --------------------------------------------------------------------------------------

def _fable_president_run(tmp_path, gemini_verdict, *, resume_pointer_brief=True):
    """A Fable-president board deferred and resumed under Claude Code. The Claude seat is
    native-filled (file access) and grok can read the tree; the brokered gemini seat cannot."""
    harden_require("review-leg-isolation")
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
    from phase_loop_runtime.advisor_board.schema import Board

    board = Board(name="fable-president", purpose="premerge-review",
                  seats=tuple(seat for seat in DEFAULT_SEATS if seat.harness != "codex"))
    policy = pi.ReviewLandingPolicy(required_seats=("fable", "gemini", "grok"),
                                    requires_president=True)

    def spawn(leg, artifact):
        verdict = gemini_verdict if leg == "gemini" else "AGREE"
        return "OK", f"{leg} found: the {leg} concern\n{verdict}"

    def dispatch(pointer_brief, **extra):
        return invoke_sanctioned_board_control(
            board, "artifact", spawn=spawn, landing_tier=pi.ReviewLandingTier.PRODUCTION_CODE,
            review_policy=policy, base_env={"CLAUDECODE": "1"},
            **({"pointer_brief": True} if pointer_brief else {}), **extra)

    stream = tmp_path / "stream"
    deferred = dispatch(True, stream_dir=stream)
    pending = deferred.needs_native_president
    assert pending is not None and pending["rung"] == "fable"
    assert [leg.leg for leg in deferred.legs if not leg.source_grounded] == ["gemini"]
    text = "\n".join(f"FINDING {f.split(':', 1)[0]}: DEFERRED — ruled"
                     for f in deferred.president_findings) + "\nFORCING DECISION: LAND"
    fill = {"brief_digest": pending["brief_digest"], "findings_digest": pending["findings_digest"],
            "rung": "fable", "text": text}
    return dispatch(resume_pointer_brief, native_president_fill=fill, stream_dir=stream), deferred


@pytest.mark.parametrize("verdict", ["PARTIALLY AGREE", "DISAGREE"])
def test_r1_a_native_president_resume_keeps_the_ungrounded_mark(tmp_path, verdict):
    resumed, deferred = _fable_president_run(tmp_path, verdict)
    assert resumed.president is not None                    # PARTIALLY AGREE no longer refuses
    assert resumed.president_findings == deferred.president_findings
    by_leg = {leg.leg: leg for leg in resumed.legs}
    assert not by_leg["gemini"].source_grounded              # DISAGREE no longer fails open
    assert [n.code for n in by_leg["gemini"].seat_preflight_notices] == [UNREADABLE]
    assert by_leg["claude"].source_grounded and by_leg["grok"].source_grounded


def test_r1_a_resume_without_the_flag_is_refused(tmp_path):
    from phase_loop_runtime.panel_invoker import PresidentPolicyError

    with pytest.raises(PresidentPolicyError) as refused:
        _fable_president_run(tmp_path, "PARTIALLY AGREE", resume_pointer_brief=False)
    assert refused.value.code == "president_fill_digest_mismatch"
    assert not (tmp_path / "stream" / "president.ruling.json").exists()


def test_r1_the_binding_carries_the_flag_only_when_set():
    board = DEFAULT_BOARD
    plain = pi._president_run_binding(board, "a", mode="review", policy=None, landing_tier=None)
    flagged = pi._president_run_binding(board, "a", mode="review", policy=None, landing_tier=None,
                                        pointer_brief=True)
    assert "pointer_brief" not in plain and flagged == {**plain, "pointer_brief": True}


def test_r1_persisted_marks_are_inside_the_digest_and_absent_when_unmarked():
    marked = _leg("gemini", "AGREE", grounded=False)
    plain = _leg("codex", "AGREE", grounded=True)
    record = pi._president_legs_record([plain, marked])
    assert "seat_preflight" not in record[0]
    assert record[1]["seat_preflight"] == [UNREADABLE]
    tampered = [dict(record[0]), {k: v for k, v in record[1].items() if k != "seat_preflight"}]
    assert pi._president_legs_digest(tampered) != pi._president_legs_digest(record)


# --------------------------------------------------------------------------------------
# Board round 1, non-blocking items.
# --------------------------------------------------------------------------------------

def test_r1_governed_gate_passes_the_flag_and_prints_the_preflight(tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import governed_review as gr
    from phase_loop_runtime.advisor_board import backing as backing_mod

    seen: dict = {}
    notice = sp.SeatPreflightNotice(UNREADABLE, "gemini:a", "gemini", 1)

    def invoke(board, artifact, **kwargs):
        seen.update(kwargs)
        kwargs["on_seat_preflight"]((notice,))
        raise OSError("isolation unavailable after the preflight")

    monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                        lambda *a, **k: object())
    monkeypatch.setattr(backing_mod, "set_review_instruction_digest", lambda *a, **k: object())
    monkeypatch.setattr(backing_mod, "reset_review_instruction_digest", lambda *a, **k: None)
    gate = gr.governed_board_gate(
        artifact="# bundle\n", author_executor="train-coordinator", run_mode="governed",
        available_legs=("codex", "gemini", "grok"), canonical_repo_authority=tmp_path,
        compose=lambda: DEFAULT_BOARD, invoke=invoke, pointer_brief=True,
    )
    assert seen.get("pointer_brief") is True
    assert "governed board: preflight: seat gemini:a (gemini)" in capsys.readouterr().err
    assert not gate.promoted
    assert [f.code for f in gate.findings if f.code == UNREADABLE] == [UNREADABLE]


def test_r1_governed_gate_without_the_flag_passes_nothing(tmp_path, monkeypatch):
    from phase_loop_runtime import governed_review as gr
    from phase_loop_runtime.advisor_board import backing as backing_mod

    seen: dict = {}

    def invoke(board, artifact, **kwargs):
        seen.update(kwargs)
        return PanelResult(legs=(_leg("codex", "AGREE", grounded=True),))

    monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                        lambda *a, **k: object())
    monkeypatch.setattr(backing_mod, "set_review_instruction_digest", lambda *a, **k: object())
    monkeypatch.setattr(backing_mod, "reset_review_instruction_digest", lambda *a, **k: None)
    gr.governed_board_gate(
        artifact="# bundle\n", author_executor="train-coordinator", run_mode="governed",
        available_legs=("codex", "gemini", "grok"), canonical_repo_authority=tmp_path,
        compose=lambda: DEFAULT_BOARD, invoke=invoke,
    )
    assert "pointer_brief" not in seen and "on_seat_preflight" not in seen


def test_r1_the_falsifier_hold_keeps_the_marks():
    from phase_loop_runtime import governed_review as gr

    legs = (_leg("codex", "AGREE", grounded=True), _leg("gemini", "AGREE", grounded=False))
    object.__setattr__(legs[0], "_finding_falsifiers", object())
    held = gr._foreign_falsifier_hold(PanelResult(legs=legs), reviewed_sha=None,
                                      falsifier_policy="optional")
    assert held is not None and not held.promoted
    marked = [f for f in held.findings if f.code == UNREADABLE]
    assert len(marked) == 1 and "seat gemini:a (gemini)" in marked[0].reason


def test_r1_identical_seats_each_get_exactly_their_own_notice():
    seat = _seat("gemini", key="gemini:same")
    notices = sp.pointer_brief_preflight(
        [seat, seat], staged_tree=True, brokered=lambda leg: True,
        native_fill=lambda s, leg: False, sandbox_usable_by=pi.sandbox_usable_by)
    legs = [PanelLegResult(leg="gemini", status="OK", text="x\nAGREE", seat_key="gemini:same")
            for _ in range(2)]
    pi.attach_seat_preflight_notices(legs, notices)
    assert [len(leg.seat_preflight_notices) for leg in legs] == [1, 1]
    assert [n.position for leg in legs for n in leg.seat_preflight_notices] == [0, 1]


def test_r1_the_all_native_early_path_still_publishes_its_preflight(tmp_path, monkeypatch):
    """An all-Claude board under Claude Code launches nothing, but the caller's preflight
    still arrives: every seat is native-filled, so it warns none."""
    harden_require("review-leg-isolation")
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
    from phase_loop_runtime.advisor_board.schema import Board

    claude = next(seat for seat in DEFAULT_SEATS if seat.harness == "claude")
    board = Board(name="all-claude", purpose="premerge-review", seats=(claude,))
    published: list = []
    monkeypatch.setenv("CLAUDECODE", "1")
    result = invoke_sanctioned_board_control(
        board, "artifact", base_env={"CLAUDECODE": "1"}, pointer_brief=True,
        on_seat_preflight=published.append)
    assert published == [()]
    assert all(leg.status == "UNAVAILABLE" and leg.source_grounded for leg in result.legs)


# --------------------------------------------------------------------------------------
# agent-harness#1132: a jailed Claude seat has its tools in the staged tree, so it CAN read
# the pointer brief; the preflight reads the same jailed-route facts the launch acts on.
# --------------------------------------------------------------------------------------

def _jailed_route(leg, **_k):
    from phase_loop_runtime import seat_jail

    if leg == "claude":
        return seat_jail.SeatRoute(True)
    if leg == "gemini":
        return seat_jail.SeatRoute(False, "gemini_seat_egress_unconfined")
    return None


@pytest.mark.parametrize("qualified, unreadable", [
    (True, ["gemini"]),               # the jailed Claude seat reads its brief
    (False, ["claude", "gemini"]),    # a jail that cannot be qualified: the seat runs sealed
])
def test_a_jailed_claude_seat_is_not_marked_unreadable(monkeypatch, qualified, unreadable):
    from phase_loop_runtime import seat_jail_autoqualify as aq

    monkeypatch.setattr(pi._seat_jail, "decide_seat_route", _jailed_route)
    monkeypatch.setattr(pi._seat_jail_autoqualify, "ensure_qualified",
                        lambda leg: aq.Outcome(aq.QUALIFIED) if qualified
                        else aq.Outcome(aq.FAILED, "falsifiers_failed"))
    board = types.SimpleNamespace(seats=[_seat("claude"), _seat("gemini"), _seat("codex")])
    notices = pi._publish_seat_preflight(
        board, pointer_brief=True, mode="review",
        review_authorization=types.SimpleNamespace(staged_tree_sha256="a" * 64),
        base_env={}, stream_dir=None, on_seat_preflight=None)
    assert [n.leg for n in notices] == unreadable
    assert all(n.code == UNREADABLE for n in notices)


def test_cli_prints_every_seat_mode_and_carries_it_in_the_payload(tmp_path, monkeypatch):
    # agent-harness#1132 (plan amendment A1): no seat is silently left without tools.
    from phase_loop_runtime import seat_jail

    _what, why, fix = seat_jail.NOTICES["seat_sandbox_refused:jail_unqualified"]
    modes = (sp.SeatMode("claude:a", "claude", sp.MODE_DEGRADED,
                         "seat_sandbox_refused:jail_unqualified", why, fix, None, 0),
             sp.SeatMode("codex:a", "codex", sp.MODE_UNCONFINED, "seat_filesystem_unconfined",
                         "tools", "jail", None, 1))
    legs = [_leg(leg, "AGREE", grounded=True) for leg in ("codex", "grok", "claude")]
    _code, out, err, _captured = _run_cli(tmp_path, monkeypatch, legs, pointer_brief=False,
                                          modes=modes)
    assert ("advisor-board: seat mode: seat claude:a (claude): degraded "
            "[seat_sandbox_refused:jail_unqualified]") in err
    assert f"fix: {fix}" in err
    assert json.loads(out)["seat_modes"] == [m.as_json() for m in modes]
