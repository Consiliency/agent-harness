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
def staged_tree(monkeypatch):
    """The review stages an exact-head tree (the production default)."""
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)


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
        pi.attach_seat_preflight_notices(
            [result], [sp.SeatPreflightNotice(UNREADABLE, f"{leg}:a", leg)])
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


def _run_cli(tmp_path, monkeypatch, legs, *, pointer_brief=True):
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


def test_cli_without_pointer_brief_keeps_the_payload_unchanged(tmp_path, monkeypatch):
    legs = [_leg(leg, "AGREE", grounded=True) for leg in ("codex", "grok", "claude")]
    code, out, _err, captured = _run_cli(tmp_path, monkeypatch, legs, pointer_brief=False)
    assert "pointer_brief" not in captured and code == 0
    payload = json.loads(out)
    assert not {"grounded_seats", "notices"} & set(payload)
    assert all("source_grounded" not in e and "notices" not in e for e in payload["legs"])


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
