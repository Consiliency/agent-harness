"""ah#736: ``requires_president`` executes president synthesis, fail-closed.

Acceptance (issue Consiliency/agent-harness#736):
1. a production-code board calls ``invoke_president`` after all four seats and
   before a landing result is returned (spied on the PRODUCTION call path);
2. ``requires_president=True`` never reaches a normal return without a ruling;
3. every seat's findings, including a codex (Sol) fill, reach the prompt with
   stable positional IDs;
4. duplicate findings are represented deterministically;
5. typed ``president_unavailable`` descends the ladder, ordinary errors do not
   (they are the board's typed refusal);
6. invalid grammar gets ONE same-session re-ask, then fails closed;
7. BLOCKING/DEFERRED rulings are durable and drive the runner's landing;
8. ``requires_president=False`` is byte-neutral.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from harden_tdd_guard import invoke_sanctioned_board_control
from president_fakes import (
    ScriptedPresident,
    blocking_president,
    deferring_president,
    finding_ids_in_prompt,
)
from phase_loop_runtime import legible_evidence, panel_invoker, president_adapter, runner
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD, DEFAULT_SEATS
from phase_loop_runtime.advisor_board.presets import CODE_REVIEW_BOARD
from phase_loop_runtime.advisor_board.schema import Board, Seat
from phase_loop_runtime.panel_invoker import (
    PRESIDENT_LADDER,
    PanelLegResult,
    PresidentPolicyError,
    PresidentRuling,
    ReviewLandingTier,
    president_blocks_landing,
    president_finding_rulings,
    president_findings_from_legs,
    president_forcing_decision,
)
from test_legible_review_repairs import make_repo


def _ok_spawn(leg: str, artifact: str) -> tuple[str, str]:
    return "OK", f"{leg} found: the {leg} concern\nAGREE"


def _board() -> Board:
    return Board(name="full", purpose="premerge-review", seats=DEFAULT_SEATS)


# 1 + 9: the production call path invokes the president AFTER every seat.
def test_production_board_invokes_president_after_all_seats_and_before_return(monkeypatch):
    order: list[str] = []
    real = panel_invoker.invoke_president

    def spy(**kwargs):
        order.append("president")
        return real(**kwargs)

    monkeypatch.setattr(panel_invoker, "invoke_president", spy)
    president = ScriptedPresident([deferring_president])
    result = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=president,
        on_leg_complete=lambda leg: order.append(f"leg:{leg.leg}"),
    )
    assert order[-1] == "president"
    assert sorted(order[:-1]) == sorted(f"leg:{seat.harness}" for seat in DEFAULT_SEATS)
    assert order.count("president") == 1
    assert result.president is not None
    assert result.president.model == "fable"
    assert [leg.status for leg in result.legs] == ["OK"] * 4
    # 3: every seat's body reached the prompt with a stable positional id.
    _, prompt = president.calls[0]
    assert finding_ids_in_prompt(prompt) == ["F001", "F002", "F003", "F004"]
    for seat in DEFAULT_SEATS:
        assert f"the {seat.harness} concern" in prompt
    assert result.president_findings == tuple(
        line for line in prompt.splitlines() if line.startswith("F0")
    )


# 2: no seam → refused before any seat runs.
def test_president_tier_without_seam_is_refused_before_any_seat_runs():
    spawned: list[str] = []

    def spawn(leg: str, artifact: str) -> tuple[str, str]:
        spawned.append(leg)
        return "OK", "AGREE"

    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_sanctioned_board_control(
            _board(),
            "artifact",
            spawn=spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        )
    assert excinfo.value.code == "president_seam_missing"
    assert spawned == []


# 2: an exhausted ladder never yields a ruling-less success.
def test_exhausted_ladder_refuses_every_leg_with_a_typed_reason():
    unavailable = {"status": "unavailable", "code": "president_unavailable"}
    president = ScriptedPresident([unavailable] * len(PRESIDENT_LADDER))
    result = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=president,
    )
    assert result.president is None
    assert [leg.status for leg in result.legs] == ["UNAVAILABLE"] * 4
    assert {leg.detail for leg in result.legs} == {
        "president_ruling_missing:president_unavailable"
    }
    assert [rung for rung, _ in president.calls] == list(PRESIDENT_LADDER)
    # the findings the president never ruled on stay attached for the operator
    assert len(result.president_findings) == 4


# 5: typed unavailability descends; an ordinary error does not descend -- it is
# the board's typed refusal (the production seam answers every seated rung with
# one, so the governed caller must receive it as a result it can persist).
def test_typed_unavailable_descends_and_ordinary_error_refuses_without_descent():
    president = ScriptedPresident(
        [{"status": "unavailable", "code": "president_unavailable"}, deferring_president]
    )
    result = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=president,
    )
    assert result.president is not None
    assert result.president.model == PRESIDENT_LADDER[1]
    assert [rung for rung, _ in president.calls] == list(PRESIDENT_LADDER[:2])

    failing = ScriptedPresident([{"status": "failed", "code": "transport_broke"}])
    refused = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=failing,
    )
    assert refused.president is None
    assert [leg.status for leg in refused.legs] == ["UNAVAILABLE"] * 4
    assert {leg.detail for leg in refused.legs} == {
        "president_ruling_missing:president_invocation_failed"
    }
    assert [rung for rung, _ in failing.calls] == [PRESIDENT_LADDER[0]]
    assert len(refused.president_findings) == 4


def test_degraded_president_deferring_validation_is_refused():
    def degraded(model: str, prompt: str):
        ids = finding_ids_in_prompt(prompt)
        lines = [f"FINDING {fid}: DEFERRED — needs validation I cannot run" for fid in ids]
        return {"status": "degraded", "text": "\n".join(lines + ["FORCING DECISION: LAND"])}

    result = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=ScriptedPresident([degraded]),
    )
    assert result.president is None
    assert {leg.detail for leg in result.legs} == {
        "president_ruling_missing:degraded_president_validation_deferred"
    }


def test_caller_contract_error_is_not_a_board_refusal():
    # ``president_round_limit`` is a caller bug, not a ladder outcome: it must
    # surface as the exception, never as a persisted-looking refusal.
    with pytest.raises(PresidentPolicyError) as excinfo:
        panel_invoker.invoke_president(
            findings=("F001: [x] y",), invoke=deferring_president, max_substantive_rounds=0
        )
    assert excinfo.value.code == "president_round_limit"
    assert excinfo.value.code not in panel_invoker._PRESIDENT_REFUSAL_CODES


# 6: one format re-ask, then fail closed.
def test_invalid_grammar_gets_one_reask_then_fails_closed():
    president = ScriptedPresident(
        [
            {"status": "ok", "text": "I think it is fine"},
            {"status": "ok", "text": "still no grammar"},
        ]
    )
    result = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=president,
    )
    assert result.president is None
    assert {leg.detail for leg in result.legs} == {
        "president_ruling_missing:president_ruling_format_missing"
    }
    assert len(president.calls) == 2
    assert "omitted the mandatory terminal grammar" in president.calls[1][1]
    assert president.calls[0][0] == president.calls[1][0] == PRESIDENT_LADDER[0]

    recovered = ScriptedPresident(
        [{"status": "ok", "text": "I think it is fine"}, deferring_president]
    )
    ok = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=recovered,
    )
    assert ok.president is not None and ok.president.format_reasks == 1


# 8: requires_president=False is byte-neutral.
def test_tests_only_tier_needs_no_seam_and_carries_no_ruling():
    board = Board(
        name="grounded",
        purpose="premerge-review",
        seats=(Seat(model="gpt-5.6-sol", effort="max", harness="codex"),),
    )
    result = invoke_sanctioned_board_control(
        board, "artifact", spawn=_ok_spawn, landing_tier=ReviewLandingTier.TESTS_ONLY
    )
    assert result.president is None
    assert result.president_findings == ()
    assert [leg.status for leg in result.legs] == ["OK"]


# 3 + 4: finding extraction is positional, deduplicated, and includes every seat.
def _leg(seat: Seat, status: str, text: str = "") -> PanelLegResult:
    return PanelLegResult(leg=seat.harness or "", status=status, text=text, seat_key=seat.seat_key)


def test_findings_are_positional_and_verdict_free():
    seats = DEFAULT_SEATS
    legs = (
        _leg(seats[0], "OK", "first claude issue\n\nsecond claude issue\nAGREE"),
        _leg(seats[1], "OK", "codex native fill: the sol issue\n\nDISAGREE"),
        _leg(seats[2], "OK", "gemini says\nsomething\n\nPARTIALLY AGREE"),
        _leg(seats[3], "OK", "AGREE"),
    )
    findings = president_findings_from_legs(seats, legs)
    assert [f.split(":", 1)[0] for f in findings] == ["F001", "F002", "F003", "F004", "F005"]
    assert findings[0] == f"F001: [{seats[0].seat_key}] first claude issue"
    assert findings[2] == f"F003: [{seats[1].seat_key}] codex native fill: the sol issue"
    assert findings[3] == f"F004: [{seats[2].seat_key}] gemini says something"
    assert findings[4] == f"F005: [{seats[3].seat_key}] usable seat returned no findings body ({seats[3].seat_key})"
    assert not any(line.endswith(("AGREE", "DISAGREE")) for line in findings)


def test_duplicate_findings_merge_deterministically():
    seats = DEFAULT_SEATS
    text_a = "The   lock is\nnever released\nAGREE"
    text_b = "the lock is never RELEASED\nDISAGREE"
    legs_ab = (
        _leg(seats[0], "OK", text_a),
        _leg(seats[1], "OK", text_b),
        _leg(seats[2], "TIMEOUT"),
        _leg(seats[3], "UNAVAILABLE"),
    )
    findings = president_findings_from_legs(seats, legs_ab)
    assert findings[0] == f"F001: [{seats[0].seat_key},{seats[1].seat_key}] The lock is never released"
    assert findings[1] == f"F002: [{seats[2].seat_key}] unusable (TIMEOUT)"
    assert findings[2] == f"F003: [{seats[3].seat_key}] unusable (UNAVAILABLE)"
    assert len(findings) == 3
    assert president_findings_from_legs(seats, legs_ab) == findings
    with pytest.raises(ValueError):
        president_findings_from_legs(seats, legs_ab[:3])


# 7: rulings are machine-readable and drive the runner's landing.
def _ruling(text: str) -> PresidentRuling:
    return PresidentRuling(model="fable", text=text, substantive_rounds=1, format_reasks=0)


def test_ruling_parsers():
    ruling = _ruling(
        "FINDING F001: BLOCKING — lock never released\n"
        "FINDING F002: DEFERRED - cosmetic\n"
        "FORCING DECISION: REJECT until F001 is repaired"
    )
    assert president_finding_rulings(ruling) == (
        panel_invoker.PresidentFindingRuling("F001", "BLOCKING", "lock never released"),
        panel_invoker.PresidentFindingRuling("F002", "DEFERRED", "cosmetic"),
    )
    assert president_forcing_decision(ruling) == "REJECT until F001 is repaired"
    assert president_blocks_landing(ruling)
    assert not president_blocks_landing(_ruling("FINDING F001: DEFERRED — later\nFORCING DECISION: LAND"))


def _stub_board_result(ruling: PresidentRuling | None, *, findings=("F001: [claude] x",)):
    return SimpleNamespace(
        legs=tuple(
            SimpleNamespace(
                leg=seat.harness,
                seat_key=seat.seat_key,
                status="OK",
                usable=True,
                text="reviewed\nAGREE",
                detail=None,
            )
            for seat in CODE_REVIEW_BOARD.seats
        ),
        president=ruling,
        president_findings=findings,
    )


def _switch_govlean_authority(repo: Path) -> None:
    # Same shape ``_govlean_authority_switched`` reads: a ``v10-GOVLEAN`` plan
    # whose lifecycle carries the ``authority_switch`` transition.
    (repo / "plans").mkdir(exist_ok=True)
    (repo / "plans" / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "plans": [
                    {
                        "slug": "v10-GOVLEAN",
                        "lifecycle": [
                            {
                                "transition": "authority_switch",
                                "by": "codex-execute-phase",
                                "at": "2026-08-15T00:00:00Z",
                                "metadata": {"verification_status": "passed"},
                            }
                        ],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _runner_fixture(tmp_path: Path, *, switched: bool = True):
    # The runner declares the production-code tier (and the president seam)
    # only once the target repo has crossed the GOVLEAN authority switch --
    # the same predicate the invoker uses to refuse tierless calls.
    repo = make_repo(tmp_path)
    if switched:
        _switch_govlean_authority(repo)
    run_dir = repo / ".phase-loop" / "runs" / "panel"
    run_dir.mkdir(parents=True)
    bundle = run_dir / "bundle.md"
    bundle.write_text("staged transition evidence\n", encoding="utf-8")
    return repo, run_dir, bundle


def test_runner_blocking_ruling_fails_landing_and_persists_ruling(tmp_path, monkeypatch):
    repo, run_dir, bundle = _runner_fixture(tmp_path)
    ruling = _ruling("FINDING F001: BLOCKING — lock never released\nFORCING DECISION: REJECT")
    monkeypatch.setattr(
        panel_invoker, "invoke_board", lambda *_a, **_k: _stub_board_result(ruling)
    )
    with pytest.raises(legible_evidence.LegibleProcessBootstrapError, match="BLOCKING"):
        runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert not (run_dir / "implementation-panel.json").exists()
    record = json.loads((run_dir / "implementation-panel-president.json").read_text(encoding="utf-8"))
    assert record["rulings"] == [
        {"finding_id": "F001", "disposition": "BLOCKING", "reason": "lock never released"}
    ]
    assert record["forcing_decision"] == "REJECT"
    assert record["findings"] == ["F001: [claude] x"]
    assert record["head"] == "1" * 40


def test_runner_missing_ruling_fails_landing(tmp_path, monkeypatch):
    repo, run_dir, bundle = _runner_fixture(tmp_path)
    monkeypatch.setattr(
        panel_invoker, "invoke_board", lambda *_a, **_k: _stub_board_result(None)
    )
    with pytest.raises(legible_evidence.LegibleProcessBootstrapError, match="no president ruling"):
        runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert not (run_dir / "implementation-panel.json").exists()
    record = json.loads((run_dir / "implementation-panel-president.json").read_text(encoding="utf-8"))
    assert record["model"] is None and record["text"] is None
    assert record["rulings"] == [] and record["forcing_decision"] is None
    assert record["findings"] == ["F001: [claude] x"]
    assert record["refusal"] is None


def test_runner_president_refusal_names_the_reason(tmp_path, monkeypatch):
    repo, run_dir, bundle = _runner_fixture(tmp_path)

    def refused(*_a, **_k):
        return SimpleNamespace(
            legs=tuple(
                SimpleNamespace(
                    leg=seat.harness, seat_key=seat.seat_key, status="UNAVAILABLE",
                    usable=False, text="", detail="president_ruling_missing:president_unavailable",
                )
                for seat in CODE_REVIEW_BOARD.seats
            ),
            president=None,
            president_findings=(),
        )

    monkeypatch.setattr(panel_invoker, "invoke_board", refused)
    with pytest.raises(
        legible_evidence.LegibleProcessBootstrapError,
        match=r"president_ruling_missing:president_unavailable",
    ):
        runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert not (run_dir / "implementation-panel.json").exists()
    record = json.loads((run_dir / "implementation-panel-president.json").read_text(encoding="utf-8"))
    assert record["refusal"] == "president_ruling_missing:president_unavailable"
    assert record["model"] is None


def test_runner_rerun_in_the_same_run_dir_invalidates_the_prior_landing(tmp_path, monkeypatch):
    # CR r2 (codex): a landing attempt followed by a refused attempt in the SAME
    # run directory must not leave the first attempt's ``implementation-panel.json``
    # beside the second attempt's president refusal -- the run would carry both
    # a landing and a refusal for one head.
    repo, run_dir, bundle = _runner_fixture(tmp_path)
    landing = _ruling("FINDING F001: DEFERRED — later\nFORCING DECISION: LAND")
    monkeypatch.setattr(
        panel_invoker, "invoke_board", lambda *_a, **_k: _stub_board_result(landing)
    )
    panel_path = runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert panel_path.is_file()
    first = json.loads(panel_path.read_text(encoding="utf-8"))
    assert first["head"] == "1" * 40
    # a stray partial write from an interrupted attempt is invalidated too
    (run_dir / "implementation-panel.json.tmp").write_text("{", encoding="utf-8")

    blocking = _ruling("FINDING F001: BLOCKING — lock never released\nFORCING DECISION: REJECT")
    monkeypatch.setattr(
        panel_invoker, "invoke_board", lambda *_a, **_k: _stub_board_result(blocking)
    )
    with pytest.raises(legible_evidence.LegibleProcessBootstrapError, match="BLOCKING"):
        runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert not (run_dir / "implementation-panel.json").exists()
    assert not (run_dir / "implementation-panel.json.tmp").exists()
    record = json.loads((run_dir / "implementation-panel-president.json").read_text(encoding="utf-8"))
    assert record["forcing_decision"] == "REJECT"
    # only this attempt's records remain: the four leg artifacts + the refusal
    assert sorted(p.name for p in run_dir.glob("implementation-panel*.json*")) == sorted(
        [f"implementation-panel-{seat.harness}.json" for seat in CODE_REVIEW_BOARD.seats]
        + ["implementation-panel-president.json"]
    )

    # and the reverse order: a refusal followed by a landing leaves only the landing
    monkeypatch.setattr(
        panel_invoker, "invoke_board", lambda *_a, **_k: _stub_board_result(landing)
    )
    runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    record = json.loads((run_dir / "implementation-panel-president.json").read_text(encoding="utf-8"))
    assert record["forcing_decision"] == "LAND"
    assert (run_dir / "implementation-panel.json").is_file()
    assert not list(run_dir.glob("*.tmp"))


def test_runner_board_records_are_published_atomically(tmp_path, monkeypatch):
    # A failed rename leaves no record at all -- never a partial file a later
    # reader could take for a landing.
    repo, run_dir, bundle = _runner_fixture(tmp_path)
    landing = _ruling("FINDING F001: DEFERRED — later\nFORCING DECISION: LAND")
    monkeypatch.setattr(
        panel_invoker, "invoke_board", lambda *_a, **_k: _stub_board_result(landing)
    )

    def broken_replace(src, dst):
        raise OSError("rename failed")

    monkeypatch.setattr(runner.os, "replace", broken_replace)
    with pytest.raises(OSError, match="rename failed"):
        runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert not (run_dir / "implementation-panel-president.json").exists()
    assert not (run_dir / "implementation-panel.json").exists()


def test_runner_switched_repo_reaches_the_real_board_and_seam_and_fails_closed(tmp_path, monkeypatch):
    # No stub result: the runner's kwargs go through the sanctioned executable
    # control into the REAL ``invoke_board`` president tail and the REAL adapter.
    # Post-HARDEN the seated top rung has no execution route, so the landing must
    # fail closed as the typed refusal -- with the ladder walk persisted.
    repo, run_dir, bundle = _runner_fixture(tmp_path)
    seen: dict[str, object] = {}
    real_invoke_board = panel_invoker.invoke_board

    def via_control(board, artifact, **kwargs):
        seen.update(kwargs)
        # The control looks ``invoke_board`` up dynamically too: hand it the
        # real one back so the runner's seam reaches production, not this shim.
        monkeypatch.setattr(panel_invoker, "invoke_board", real_invoke_board)
        return invoke_sanctioned_board_control(
            board,
            artifact,
            spawn=_ok_spawn,
            landing_tier=kwargs["landing_tier"],
            president_invoke=kwargs["president_invoke"],
        )

    monkeypatch.setattr(panel_invoker, "invoke_board", via_control)
    with _NO_SPAWN, pytest.raises(
        legible_evidence.LegibleProcessBootstrapError,
        match=r"president_ruling_missing:president_invocation_failed",
    ):
        runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert not (run_dir / "implementation-panel.json").exists()
    seam = seen["president_invoke"]
    assert isinstance(seam, president_adapter.PresidentInvoke)
    record = json.loads((run_dir / "implementation-panel-president.json").read_text(encoding="utf-8"))
    assert record["refusal"] == "president_ruling_missing:president_invocation_failed"
    assert record["attempts"] == [a.as_record() for a in seam.attempts]
    assert [a["rung"] for a in record["attempts"]] == [PRESIDENT_LADDER[0]]
    assert record["attempts"][0]["status"] == "failed"
    assert record["attempts"][0]["code"] == president_adapter.PRESIDENT_ROUTE_UNAVAILABLE
    assert record["attempts"][0]["leg"] == "claude"
    assert len(record["findings"]) == 4
    assert record["head"] == "1" * 40


def test_runner_declares_the_tier_and_a_live_seam(tmp_path, monkeypatch):
    repo, run_dir, bundle = _runner_fixture(tmp_path)
    observed: dict[str, object] = {}

    def fake(_board, _artifact, **kwargs):
        observed.update(kwargs)
        return _stub_board_result(_ruling("FINDING F001: DEFERRED — x\nFORCING DECISION: LAND"))

    monkeypatch.setattr(panel_invoker, "invoke_board", fake)
    panel_path = runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert observed["landing_tier"] is ReviewLandingTier.PRODUCTION_CODE
    seam = observed["president_invoke"]
    assert isinstance(seam, president_adapter.PresidentInvoke)
    assert seam.board is CODE_REVIEW_BOARD
    assert seam.repo_dir == repo
    assert seam.stream_dir == run_dir / "implementation-panel-stream"
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    assert panel["bundle_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    record = json.loads((run_dir / "implementation-panel-president.json").read_text(encoding="utf-8"))
    assert record["attempts"] == []  # the stub board never called the seam
    assert record["refusal"] is None
    assert record["forcing_decision"] == "LAND"


def test_runner_pre_switch_repo_is_byte_neutral(tmp_path, monkeypatch):
    # Before the authority switch the invoker applies no landing policy, so the
    # runner must not newly gate the landing: no tier, no seam, no ruling file.
    repo, run_dir, bundle = _runner_fixture(tmp_path, switched=False)
    observed: dict[str, object] = {}

    def fake(_board, _artifact, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            legs=tuple(
                SimpleNamespace(
                    leg=seat.harness, seat_key=seat.seat_key, status="OK",
                    usable=True, text="reviewed\nAGREE", detail=None,
                )
                for seat in CODE_REVIEW_BOARD.seats
            )
        )

    monkeypatch.setattr(panel_invoker, "invoke_board", fake)
    panel_path = runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert "landing_tier" not in observed
    assert "president_invoke" not in observed
    assert panel_path.exists()
    assert not (run_dir / "implementation-panel-president.json").exists()


# Adapter: ladder rung → board seat → typed president response.
def test_every_ladder_rung_resolves_to_one_review_board_seat():
    seats = [president_adapter.seat_for_rung(CODE_REVIEW_BOARD, rung) for rung in PRESIDENT_LADDER]
    assert all(seat is not None for seat in seats)
    assert len({seat.model for seat in seats if seat}) == len(PRESIDENT_LADDER)
    assert [seat.harness for seat in seats if seat] == ["claude", "codex", "grok", "gemini"]
    assert president_adapter.seat_for_rung(CODE_REVIEW_BOARD, "nobody") is None


def _no_claude_board() -> Board:
    return Board(
        name="no-claude",
        purpose="premerge-review",
        seats=tuple(seat for seat in DEFAULT_SEATS if seat.harness != "claude"),
    )


_NO_SPAWN = patch(
    "phase_loop_runtime.panel_invoker._default_spawn_via_provider",
    side_effect=AssertionError("the president adapter must not spawn a leg"),
)


def test_adapter_seated_rung_fails_closed_without_a_president_operation(tmp_path):
    # Post-HARDEN the only production execution operation is the governed
    # review (frozen AGREE grammar); advisory execution is refused and a
    # FORCING DECISION ruling cannot ride the review operation. A seated rung
    # therefore reports a typed structural failure -- it never spawns, and it
    # never launders the seat through a review leg.
    seam = president_adapter.build_president_invoke(
        DEFAULT_BOARD, repo_dir=tmp_path, base_env={}
    )
    with _NO_SPAWN:
        response = seam("sol", "F001: [claude] x\nF002: [codex] y")
    assert response["status"] == "failed"
    assert response["code"] == president_adapter.PRESIDENT_ROUTE_UNAVAILABLE
    assert "HARDEN-authorized president execution operation" in response["detail"]
    attempt = seam.attempts[-1]
    assert attempt.rung == "sol"
    seat = president_adapter.seat_for_rung(DEFAULT_BOARD, "sol")
    assert seat is not None and seat.harness == "codex"
    assert attempt.seat_model == seat.model
    assert attempt.leg == "codex"
    assert attempt.status == "failed"
    assert attempt.code == president_adapter.PRESIDENT_ROUTE_UNAVAILABLE
    assert attempt.as_record()["code"] == president_adapter.PRESIDENT_ROUTE_UNAVAILABLE


def test_adapter_route_failure_is_not_a_ladder_descent(tmp_path):
    # The route failure is ordinary (not typed unavailability), so the ladder
    # stops at the first seated rung instead of walking every seat.
    seam = president_adapter.build_president_invoke(
        DEFAULT_BOARD, repo_dir=tmp_path, base_env={}
    )
    with _NO_SPAWN, pytest.raises(PresidentPolicyError) as excinfo:
        panel_invoker.invoke_president(
            findings=("F001: [claude] the lock",), invoke=seam, max_substantive_rounds=3
        )
    assert excinfo.value.code == "president_invocation_failed"
    assert [a.rung for a in seam.attempts] == ["fable"]


def test_adapter_reports_unseated_rung_as_typed_unavailable(tmp_path):
    seam = president_adapter.build_president_invoke(
        _no_claude_board(), repo_dir=tmp_path, base_env={}
    )
    with _NO_SPAWN:
        response = seam("fable", "F001: [x] y")
    assert response["status"] == "unavailable"
    assert response["code"] == "president_unavailable"
    assert seam.attempts[-1].seat_model is None
    assert seam.attempts[-1].status == "unavailable"


def test_adapter_end_to_end_ladder_descends_past_an_unseated_rung(tmp_path):
    # Unseated top rung -> typed unavailability -> descend; the first seated
    # rung then fails closed on the missing execution route.
    seam = president_adapter.build_president_invoke(
        _no_claude_board(), repo_dir=tmp_path, base_env={}
    )
    with _NO_SPAWN, pytest.raises(PresidentPolicyError) as excinfo:
        panel_invoker.invoke_president(
            findings=("F001: [claude] the lock",), invoke=seam, max_substantive_rounds=3
        )
    assert excinfo.value.code == "president_invocation_failed"
    assert [a.rung for a in seam.attempts] == ["fable", "sol"]
    assert seam.attempts[0].status == "unavailable"
    assert seam.attempts[1].status == "failed"


def test_blocking_president_refuses_nothing_at_board_level_but_marks_the_ruling():
    # The board returns the ruling; applying BLOCKING to the landing is the
    # governed caller's job (runner), so the seats stay OK here.
    result = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=blocking_president,
    )
    assert [leg.status for leg in result.legs] == ["OK"] * 4
    assert result.president is not None and president_blocks_landing(result.president)
