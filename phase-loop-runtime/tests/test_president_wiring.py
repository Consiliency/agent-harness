"""PRESROUTE president wiring falsifiers (SL-0 frozen corpus, agent-harness#952).

This file is frozen byte-equal from SL-0 landing until merge (content_tdd_receipt.v1);
SL-1 (Lane A) consumes it and SL-2 (Lane B impl) may not edit it.

Two kinds of test live here:

* **Order-agnostic GOVLEAN/board invariants** — they name president rungs by
  ``PRESIDENT_LADDER`` index, never by literal alias, so they stay green across
  the EC-PRESROUTE-3 ladder reorder. They are NOT wrapped in the RED contract.
* **PRESROUTE post-implementation contracts** — wrapped in
  ``run_presroute_contract`` so they are RED on the pre-implementation base and
  green once SL-1/SL-2 land. The node handles a later EC can select by ``-k`` are:
  ``operation``, ``authorization``, ``refuses_a_review_authorization``,
  ``launch_provider``, ``native_fable``, ``heartbeat``, ``brief_binding``,
  ``ruling_record``, ``findings_digest``, ``ruling_record_matches_frozen_contract``,
  and ``route_failure``. This list describes the contracts in THIS file; the plan's
  own verification ``-k`` recipe lives in the plan document (the plan owner's file,
  not part of SL-0's frozen four) and is that owner's to keep in step.

The frozen contract SL-1/SL-2 must satisfy (they may not edit this file):

* ``phase_loop_runtime.president_operation`` module (SL-1) with:
  - ``run_president_operation(*, brief, findings, authorization, invoke,
    max_substantive_rounds) -> PresidentOperationResult`` — walks
    ``PRESIDENT_LADDER`` via ``invoke``, binds the HARDEN authorization identity
    and the two digests. ``PresidentOperationResult`` carries ``ruling``
    (``PresidentRuling``), ``authorization_identity``, ``rung_index``,
    ``brief_digest``, ``findings_digest`` (IF-0-PRESROUTE-1).
  - ``brief_digest = sha256(brief)``, ``findings_digest =
    sha256("\\n".join(findings))``, lowercase hex.
  - ``president_ruling_record(result) -> dict`` — the ``president.ruling.v1``
    record shape matching ``data/president_ruling_v1.golden.json``.
  - the codes ``PRESIDENT_FILL_HEARTBEAT_REFUSED``, ``PRESIDENT_FILL_DIGEST_MISMATCH``
    and ``PRESIDENT_OPERATION_AUTHORIZATION_MISMATCH`` (the last raised as a
    ``PresidentPolicyError`` when the supplied authorization's operation is not
    ``public_board_president.v1`` — the operation refuses a foreign authorization
    at its own boundary, as ``spawn`` revalidates before it launches).
* ``advisor_board.backing.prepare_president_isolation_authorization(board, brief)``
  (SL-1) — mints operation ``public_board_president.v1`` with
  ``child_credentialless=True``, ``child_network_egress=False``,
  ``live_tree_exposed=False``.
* ``president_adapter.build_president_invoke`` (SL-2), accepting a
  ``monitoring_policy`` keyword (the only signature element a frozen test probes) —
  the per-rung production seam ``invoke_board`` calls: every non-native rung (``sol``/Astra,
  ``grok``, ``gemini``) launches through ``panel_invoker.launch_provider`` and
  nowhere else; the Fable rung under Claude Code returns a deferred native fill
  (``status="native_fill_deferred"``) carrying ``brief_digest``/``findings_digest``
  and never spawns, and on a non-Claude-Code host runs through the self-PTY adapter
  (``_run_claude_tui_session``); under ``monitoring_policy="heartbeat_only"`` the
  native fill is refused with ``PRESIDENT_FILL_HEARTBEAT_REFUSED``.
* ``panel_invoker.invoke_board`` (SL-2): the Fable rung deferring under Claude Code
  exposes ``PanelResult.needs_native_president`` (``{"rung": "fable", brief_digest,
  findings_digest}``); PERSISTS the ruling (a president-tier landing with a
  ``stream_dir`` writes ``<stream_dir>/president.ruling.json`` in the
  ``president.ruling.v1`` shape whose contents reproduce the actual ruling); REFUSES
  a ``requires_president=False`` override via ``enforce_requires_president``; and
  takes an optional ``native_president_fill`` (the durable resume/join) whose brief
  AND findings digests it compares against the deferred pending request BEFORE
  accepting or persisting — a mismatch is refused with
  ``PRESIDENT_FILL_DIGEST_MISMATCH`` and persists nothing (EC-PRESROUTE-2/-4/-5).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from harden_tdd_guard import invoke_sanctioned_board_control
from test_legible_review_repairs import make_repo
from president_fakes import (
    ScriptedPresident,
    blocking_president,
    deferring_president,
    finding_ids_in_prompt,
)
from presroute_content_tdd_adapter import (
    require_attr,
    require_capability,
    require_module,
    run_presroute_contract,
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


_GOLDEN_PATH = Path(__file__).resolve().parent / "data" / "president_ruling_v1.golden.json"

# Inputs the golden fixture's digests were computed over; the golden carries both
# ``sha256(GOLDEN_BRIEF)`` and ``sha256("\n".join(GOLDEN_FINDINGS))``.
GOLDEN_BRIEF = "Rule on each PRESROUTE production-code board finding, then force a decision."
GOLDEN_FINDINGS = (
    "F001: [sol] the dispatch lock is never released",
    "F002: [fable] the president ladder skipped a rung",
)
_BRIEF = "brief text for one president operation"
_FINDINGS = ("F001: [sol] the dispatch lock is never released",)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _duck_authorization() -> SimpleNamespace:
    # ``run_president_operation`` reads only ``authorization.operation`` for the
    # identity it binds; a duck-typed value keeps the operation tests off the
    # heavy real mint (exercised separately by the ``authorization`` node).
    return SimpleNamespace(operation="public_board_president.v1")


def _ok_spawn(leg: str, artifact: str) -> tuple[str, str]:
    return "OK", f"{leg} found: the {leg} concern\nAGREE"


def _board() -> Board:
    return Board(name="full", purpose="premerge-review", seats=DEFAULT_SEATS)


# ---------------------------------------------------------------------------
# Order-agnostic invariants (unwrapped: green on base and post-implementation).
# ---------------------------------------------------------------------------


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
    assert result.president.model == PRESIDENT_LADDER[0]
    assert [leg.status for leg in result.legs] == ["OK"] * 4
    _, prompt = president.calls[0]
    assert finding_ids_in_prompt(prompt) == ["F001", "F002", "F003", "F004"]
    for seat in DEFAULT_SEATS:
        assert f"the {seat.harness} concern" in prompt
    assert result.president_findings == tuple(
        line for line in prompt.splitlines() if line.startswith("F0")
    )


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
    assert len(result.president_findings) == 4


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
    with pytest.raises(PresidentPolicyError) as excinfo:
        panel_invoker.invoke_president(
            findings=("F001: [x] y",), invoke=deferring_president, max_substantive_rounds=0
        )
    assert excinfo.value.code == "president_round_limit"
    assert excinfo.value.code not in panel_invoker._PRESIDENT_REFUSAL_CODES


def test_invalid_grammar_gets_one_reask_then_fails_closed():
    top = PRESIDENT_LADDER[0]
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
    assert president.calls[0][0] == president.calls[1][0] == top

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


def test_blocking_president_refuses_nothing_at_board_level_but_marks_the_ruling():
    result = invoke_sanctioned_board_control(
        _board(),
        "artifact",
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=blocking_president,
    )
    assert [leg.status for leg in result.legs] == ["OK"] * 4
    assert result.president is not None and president_blocks_landing(result.president)


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


def test_adapter_reports_unseated_rung_as_typed_unavailable(tmp_path):
    # An UNSEATED rung (no matching board seat) stays typed unavailable so the
    # ladder descends -- SL-1 replaces only the SEATED-rung branch.
    seam = president_adapter.build_president_invoke(
        _no_claude_board(), repo_dir=tmp_path, base_env={}
    )
    with _NO_SPAWN:
        response = seam("fable", "F001: [x] y")
    assert response["status"] == "unavailable"
    assert response["code"] == "president_unavailable"
    assert seam.attempts[-1].seat_model is None
    assert seam.attempts[-1].status == "unavailable"


# ---------------------------------------------------------------------------
# PRESROUTE post-implementation contracts (RED on base, green post-impl).
# ---------------------------------------------------------------------------


# EC-PRESROUTE-1 (``-k operation``): a HARDEN-authorized operation exists and a
# seated rung routes through it, carrying the president authorization identity.
def test_president_operation_routes_seated_rung_through_public_board_president():
    def contract() -> None:
        po = require_module("phase_loop_runtime.president_operation")
        run = require_attr(po, "run_president_operation")
        result = run(
            brief=_BRIEF,
            findings=_FINDINGS,
            authorization=_duck_authorization(),
            invoke=deferring_president,
            max_substantive_rounds=3,
        )
        assert result.authorization_identity == "public_board_president.v1"
        assert result.rung_index == 0
        assert result.ruling.model == PRESIDENT_LADDER[0]
        assert isinstance(result.ruling, PresidentRuling)

    run_presroute_contract("operation", contract)


# EC-PRESROUTE-1 (``-k authorization``): the identity is minted the same way
# review isolation is minted for ``spawn`` and surfaces on the operation result.
def test_president_authorization_identity_minted_like_review_isolation():
    def contract() -> None:
        backing = require_module("phase_loop_runtime.advisor_board.backing")
        mint = require_attr(backing, "prepare_president_isolation_authorization")
        auth = mint(DEFAULT_BOARD, _BRIEF)
        assert auth.operation == "public_board_president.v1"
        assert auth.child_credentialless is True
        assert auth.child_network_egress is False
        assert auth.live_tree_exposed is False

        po = require_module("phase_loop_runtime.president_operation")
        run = require_attr(po, "run_president_operation")
        result = run(
            brief=_BRIEF,
            findings=_FINDINGS,
            authorization=auth,
            invoke=deferring_president,
            max_substantive_rounds=3,
        )
        assert result.authorization_identity == "public_board_president.v1"

    run_presroute_contract("authorization", contract)


# EC-PRESROUTE-1 (``-k refuses_a_review_authorization``): the president operation
# refuses an authorization minted for another operation. Supplying a
# ``public_board_review.v1`` identity is rejected BEFORE any ruling, so a seated
# launch cannot borrow the review authorization -- the binding is witnessed by the
# refusal, not by the identity the RESULT reports about itself (which an adapter
# could record while still consuming the wrong authorization).
#
# This is the negative half of "``PresidentIsolationAuthorization`` ... bound to
# the seam like ``spawn``" (IF-0-PRESROUTE-1): ``spawn``'s bind is a revalidation
# that REFUSES a non-review operation before it launches, so the president
# operation must refuse a non-president operation at its own boundary. The review
# seam ``revalidate_review_isolation_authorization`` cannot host this witness --
# it type-rejects the additive president authorization at its first ``isinstance``
# check and hardcodes the review mode and the ``public_board_review.v1`` operation
# in both branches, so a correct president route cannot pass its OWN authorization
# through it. The refusal therefore lives on ``run_president_operation``, which the
# corpus already documents reads ``authorization.operation`` for the identity it
# binds. The refusal code is frozen the same way the other operation codes are.
def test_president_operation_refuses_a_review_authorization():
    def contract() -> None:
        po = require_module("phase_loop_runtime.president_operation")
        run = require_attr(po, "run_president_operation")
        code = require_attr(po, "PRESIDENT_OPERATION_AUTHORIZATION_MISMATCH")
        # The node witnesses that these SPECIFIC foreign identities are refused
        # BEFORE use. It is a finite set of negative probes, NOT the universal
        # "refuses anything that is not the president identity": exhaustive coverage
        # of the complement is unavailable, while individual further identities remain
        # testable, so a finite set is the right instrument and the node claims only
        # what it probes. Each identity is chosen to defeat one hollow shape a smaller
        # set would miss:
        #  * ``public_board_review.v1`` -- the real other operation; a by-name denylist
        #    refusing only this one is not enough, which is why the others follow.
        #  * ``not_the_president_operation.v1`` -- a wholly unrelated identity that still
        #    contains "president", so an implementation matching on that substring fails.
        #  * ``public_board_president.v2`` -- the president STEM with a different version,
        #    so an implementation matching the president stem as a prefix (version-
        #    agnostically), which a wholly-unrelated string would not catch, fails.
        #  * ``public_board_president.v1.extra`` -- the full president identity with a
        #    trailing suffix, so an implementation matching the full ``.v1`` identity as
        #    a prefix (``startswith`` the whole string), which the stem near-miss alone
        #    does not catch, fails.
        # TIMING: "bound to the seam like spawn" means refusing a foreign operation
        # BEFORE use, exactly as spawn revalidates before it launches, so the spy in
        # place of the invoke must stay empty after the refusal -- an implementation
        # that invokes the president, obtains a ruling, and only THEN checks the
        # authorization fails here rather than passing on the code alone.
        foreign_authorizations = (
            SimpleNamespace(operation="public_board_review.v1"),
            SimpleNamespace(operation="not_the_president_operation.v1"),
            SimpleNamespace(operation="public_board_president.v2"),
            SimpleNamespace(operation="public_board_president.v1.extra"),
        )
        for authorization in foreign_authorizations:
            invoked: list[tuple[str, str]] = []

            def spy_invoke(model: str, prompt: str):
                invoked.append((model, prompt))
                return deferring_president(model, prompt)

            with pytest.raises(PresidentPolicyError) as excinfo:
                run(
                    brief=_BRIEF,
                    findings=_FINDINGS,
                    authorization=authorization,
                    invoke=spy_invoke,
                    max_substantive_rounds=3,
                )
            assert excinfo.value.code == code
            assert not invoked, (
                "the operation invoked the president before refusing "
                f"the foreign authorization {authorization.operation!r}"
            )

    run_presroute_contract("review_authorization_refused", contract)


# EC-PRESROUTE-2 (``-k launch_provider``): a non-native seated rung launches
# through the single launch site ``launch_provider`` and nowhere else.
def test_non_native_rung_launches_only_through_launch_provider(tmp_path):
    def contract() -> None:
        class _Reached(Exception):
            pass

        # EVERY non-native rung EC-PRESROUTE-2 names -- Astra (``sol``), Grok and
        # Gemini -- launches through the single launch site and nowhere else.
        for rung in ("sol", "grok", "gemini"):
            launched: list[object] = []
            forbidden: list[object] = []

            def only_launch_provider(argv, **kwargs):
                launched.append(argv)
                raise _Reached()

            def forbidden_spawn(*args, **kwargs):
                forbidden.append(args)
                raise AssertionError(f"the {rung!r} rung spawned outside launch_provider")

            with patch.object(panel_invoker, "launch_provider", only_launch_provider), patch.object(
                panel_invoker, "_default_spawn_via_provider", forbidden_spawn
            ):
                seam = president_adapter.build_president_invoke(
                    DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={"CLAUDECODE": "1"}
                )
                response = None
                try:
                    response = seam(rung, f"F001: [{rung}] the dispatch lock is never released")
                except _Reached:
                    pass
            assert not forbidden, f"the {rung!r} rung spawned outside launch_provider"
            route_unavailable = bool(response) and (
                response.get("code") == president_adapter.PRESIDENT_ROUTE_UNAVAILABLE
            )
            require_capability(
                launched or not route_unavailable,
                f"the seated {rung!r} rung is not yet routed through launch_provider",
            )
            assert launched, f"the non-native {rung!r} rung did not launch through launch_provider"

        # The Fable rung on a NON-Claude-Code host is driven by the self-PTY adapter
        # (``_run_claude_tui_session``), never launch_provider and never route-unavailable.
        pty: list[object] = []
        lp: list[object] = []

        def spy_pty(*args, **kwargs):
            pty.append(args)
            raise _Reached()

        def forbid_lp(*args, **kwargs):
            lp.append(args)
            raise AssertionError("the Fable self-PTY route must not go through launch_provider")

        with patch.object(panel_invoker, "_run_claude_tui_session", spy_pty), patch.object(
            panel_invoker, "launch_provider", forbid_lp
        ):
            seam = president_adapter.build_president_invoke(
                DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}
            )
            response = None
            try:
                response = seam("fable", "F001: [fable] the dispatch lock is never released")
            except _Reached:
                pass
        assert not lp, "the Fable non-Claude route went through launch_provider"
        route_unavailable = bool(response) and (
            response.get("code") == president_adapter.PRESIDENT_ROUTE_UNAVAILABLE
        )
        require_capability(
            pty or not route_unavailable,
            "the Fable rung on a non-Claude-Code host is not yet routed through the self-PTY adapter",
        )
        assert pty, "the Fable non-Claude rung did not run through the self-PTY adapter"

    run_presroute_contract("launch_provider", contract)


# EC-PRESROUTE-2 (``-k native_fable``): PRODUCTION DISPATCH fills the Fable rung
# natively under Claude Code -- the president adapter seam ``invoke_board`` calls
# per rung returns a deferred native fill (digests binding brief and findings) and
# never spawns. An unwired helper leaves the seated rung route-unavailable here.
def test_native_fable_rung_filled_under_claude_code_without_second_tui(tmp_path):
    def contract() -> None:
        spawned: list[object] = []

        def forbid(*args, **kwargs):
            spawned.append(args)
            raise AssertionError("native Fable fill must not spawn a second Claude TUI")

        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={"CLAUDECODE": "1"}
        )
        prompt = panel_invoker._president_prompt(_FINDINGS)
        with patch.object(panel_invoker, "launch_provider", forbid), patch.object(
            panel_invoker, "_default_spawn_via_provider", forbid
        ):
            response = seam("fable", prompt)
        # Capability gate: pre-implementation the seated fable rung is route-unavailable.
        require_capability(
            response.get("code") != president_adapter.PRESIDENT_ROUTE_UNAVAILABLE,
            "the fable rung is not yet filled natively (route-unavailable)",
        )
        assert not spawned, "the native fable fill spawned instead of deferring"
        # a DEFERRED native fill whose digest VALUES bind the brief (the exact
        # prompt) and the findings it carried -- two arbitrary hex strings fail.
        assert response.get("status") == "native_fill_deferred"
        assert response.get("brief_digest") == _sha(prompt)
        assert response.get("findings_digest") == _sha("\n".join(_FINDINGS))

    run_presroute_contract("native_fable", contract)


# EC-PRESROUTE-2 (``-k heartbeat``): PRODUCTION DISPATCH refuses a native president
# fill under heartbeat_only -- the seam built with that monitoring policy raises
# rather than deferring a fill an excluded policy could bind as usable.
def test_native_president_fill_refused_under_heartbeat_only(tmp_path):
    def contract() -> None:
        import inspect

        po = require_module("phase_loop_runtime.president_operation")
        code = require_attr(po, "PRESIDENT_FILL_HEARTBEAT_REFUSED")
        require_capability(
            "monitoring_policy"
            in inspect.signature(president_adapter.build_president_invoke).parameters,
            "build_president_invoke does not accept monitoring_policy for the native fill",
        )
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD,
            repo_dir=str(tmp_path),
            base_env={"CLAUDECODE": "1"},
            monitoring_policy="heartbeat_only",
        )
        with pytest.raises(PresidentPolicyError) as excinfo:
            seam("fable", "F001: [fable] the dispatch lock is never released")
        assert excinfo.value.code == code

    run_presroute_contract("heartbeat", contract)


# EC-PRESROUTE-2 (``-k brief_binding``): the durable defer->resume/join. Each
# scenario DEFERS a pending native president request into its own stream directory
# and then RESUMES against that same directory; ``invoke_board`` compares BOTH the
# fill's brief and findings digests against the deferred pending before accepting
# or persisting. The unchanged fill is accepted (the supplied ruling is returned
# and persisted, contents asserted); an independently changed brief OR findings is
# refused and persists nothing. Sharing one durable context per scenario means a
# correct implementation that reloads the outstanding request is not rejected.
def test_brief_binding_rejects_changed_brief_at_resume_and_accepts_control(tmp_path):
    def contract() -> None:
        import inspect

        po = require_module("phase_loop_runtime.president_operation")
        mismatch_code = require_attr(po, "PRESIDENT_FILL_DIGEST_MISMATCH")
        require_capability(
            "native_president_fill"
            in inspect.signature(panel_invoker.invoke_board).parameters,
            "invoke_board does not accept native_president_fill for resume verification",
        )

        # A board whose president rung is FABLE: the codex seat is absent, so the
        # ladder's ``sol`` rung is unseated and the president descends to Fable,
        # which defers natively under Claude Code. The fill is only valid for the
        # rung that actually deferred.
        board = Board(
            name="fable-president",
            purpose="premerge-review",
            seats=tuple(seat for seat in DEFAULT_SEATS if seat.harness != "codex"),
        )
        env = {"CLAUDECODE": "1"}
        # a policy matching this board's seats (codex/sol absent), president required.
        policy = panel_invoker.ReviewLandingPolicy(
            required_seats=("fable", "gemini", "grok"), requires_president=True
        )

        def _dispatch(**extra):
            return invoke_sanctioned_board_control(
                board,
                "artifact",
                spawn=_ok_spawn,
                landing_tier=ReviewLandingTier.PRODUCTION_CODE,
                review_policy=policy,
                base_env=env,
                **extra,
            )

        def _defer_then_resume(scenario_dir, fill_digests):
            # Each scenario runs its OWN defer->resume pair sharing ONE durable
            # context (scenario_dir): the defer establishes the pending request
            # there, the resume joins to it. A correct implementation that reloads
            # the outstanding request from the stream sees the pending the defer
            # left, so the positive control does not reject correct code.
            deferred = _dispatch(stream_dir=scenario_dir)
            pending = getattr(deferred, "needs_native_president", None)
            require_capability(
                pending is not None,
                "the Fable rung did not defer a pending native president request",
            )
            assert pending["rung"] == "fable"
            ruling_text = (
                "\n".join(
                    f"FINDING {f.split(':', 1)[0]}: DEFERRED — ruled"
                    for f in deferred.president_findings
                )
                + "\nFORCING DECISION: LAND"
            )
            bd, fd = fill_digests(pending)
            fill = {"brief_digest": bd, "findings_digest": fd, "rung": "fable", "text": ruling_text}
            return _dispatch(native_president_fill=fill, stream_dir=scenario_dir), ruling_text

        # Positive control: the matching fill is ACCEPTED -- the SUPPLIED ruling is
        # returned AND persisted, and the persisted file's CONTENTS reproduce that
        # ruling (file existence alone would not prove the fill was accepted).
        ok_dir = tmp_path / "ok"
        accepted, ruling_text = _defer_then_resume(
            ok_dir, lambda p: (p["brief_digest"], p["findings_digest"])
        )
        assert accepted.president is not None
        assert accepted.president.text == ruling_text
        record = json.loads((ok_dir / "president.ruling.json").read_text(encoding="utf-8"))
        assert record["forcing_decision"] == "LAND"
        assert record["finding_rulings"] == [
            {"id": r.finding_id, "disposition": r.disposition, "reason": r.reason}
            for r in president_finding_rulings(accepted.president)
        ]
        assert record["finding_rulings"] and all(
            r["disposition"] == "DEFERRED" and r["reason"] == "ruled"
            for r in record["finding_rulings"]
        )

        # Its own defer->resume pair: an independently changed brief is refused and
        # persists NOTHING (no ruling file, only whatever the defer left).
        bad_brief = tmp_path / "bad_brief"
        with pytest.raises(PresidentPolicyError) as excinfo:
            _defer_then_resume(bad_brief, lambda p: (_sha("an unrelated brief"), p["findings_digest"]))
        assert excinfo.value.code == mismatch_code
        assert not (bad_brief / "president.ruling.json").exists()

        # Its own defer->resume pair: an independently changed findings is refused
        # and persists nothing.
        bad_findings = tmp_path / "bad_findings"
        with pytest.raises(PresidentPolicyError) as excinfo:
            _defer_then_resume(bad_findings, lambda p: (p["brief_digest"], _sha("unrelated findings")))
        assert excinfo.value.code == mismatch_code
        assert not (bad_findings / "president.ruling.json").exists()

    run_presroute_contract("brief_binding", contract)


# EC-PRESROUTE-5 (``-k ruling_record``): PRODUCTION DISPATCH persists the ruling
# to the review stream as ``president.ruling.json``. Driving the real board (not a
# helper in isolation) means an implementation that never writes the file fails.
def test_ruling_record_written_to_review_stream_with_identity(tmp_path):
    def contract() -> None:
        run_dir = tmp_path / "implementation-panel-stream"
        run_dir.mkdir(parents=True)
        result = invoke_sanctioned_board_control(
            _board(),
            "artifact",
            spawn=_ok_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE,
            president_invoke=ScriptedPresident([blocking_president]),
            stream_dir=run_dir,
        )
        ruling_file = run_dir / "president.ruling.json"
        # Capability gate: pre-implementation dispatch does not persist the file.
        require_capability(
            ruling_file.is_file(),
            "production dispatch did not persist president.ruling.json to the review stream",
        )
        record = json.loads(ruling_file.read_text(encoding="utf-8"))
        # the record must reproduce the ACTUAL ruling, not merely a well-shaped one
        # with correct digests: a serializer that keeps the digests but falsifies
        # the decision, dispositions, rung, or model must fail.
        ruling = result.president
        seat = president_adapter.seat_for_rung(DEFAULT_BOARD, ruling.model)
        expected_finding_rulings = [
            {"id": fr.finding_id, "disposition": fr.disposition, "reason": fr.reason}
            for fr in president_finding_rulings(ruling)
        ]
        assert record["schema"] == "president.ruling.v1"
        assert record["authorization_identity"] == "public_board_president.v1"
        assert record["rung_index"] == list(PRESIDENT_LADDER).index(ruling.model)
        assert record["model_id"] == (seat.model if seat is not None else ruling.model)
        assert record["format_reask_count"] == ruling.format_reasks
        assert record["forcing_decision"] == president_forcing_decision(ruling)
        assert record["finding_rulings"] == expected_finding_rulings
        # both persisted digests bind their input by VALUE.
        assert record["findings_digest"] == _sha("\n".join(result.president_findings))
        assert record["brief_digest"] == _sha(
            panel_invoker._president_prompt(result.president_findings)
        )

    run_presroute_contract("ruling_record", contract)


# EC-PRESROUTE-5 (``-k findings_digest``): the findings digest is over the exact
# findings the prompt carried; the brief digest is separate.
def test_findings_digest_recomputes_from_prompt_findings():
    def contract() -> None:
        po = require_module("phase_loop_runtime.president_operation")
        run = require_attr(po, "run_president_operation")
        auth = _duck_authorization()
        result = run(
            brief=_BRIEF,
            findings=_FINDINGS,
            authorization=auth,
            invoke=deferring_president,
            max_substantive_rounds=3,
        )
        assert result.findings_digest == _sha("\n".join(_FINDINGS))
        assert result.brief_digest == _sha(_BRIEF)

        amended = run(
            brief=_BRIEF + " (amended)",
            findings=_FINDINGS,
            authorization=auth,
            invoke=deferring_president,
            max_substantive_rounds=3,
        )
        assert amended.findings_digest == result.findings_digest
        assert amended.brief_digest != result.brief_digest

    run_presroute_contract("findings_digest", contract)


# IF-0-PRESROUTE-1 (``-k ruling_record_matches_frozen_contract``): a built record
# equals the golden fixture's keys/types, and each digest recomputes from input.
def test_ruling_record_matches_frozen_contract():
    def contract() -> None:
        po = require_module("phase_loop_runtime.president_operation")
        run = require_attr(po, "run_president_operation")
        build_record = require_attr(po, "president_ruling_record")
        golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
        result = run(
            brief=GOLDEN_BRIEF,
            findings=GOLDEN_FINDINGS,
            authorization=_duck_authorization(),
            invoke=blocking_president,
            max_substantive_rounds=3,
        )
        record = build_record(result)
        assert set(record.keys()) == set(golden.keys())
        for key in golden:
            assert type(record[key]) is type(golden[key]), key
        for finding_ruling in record["finding_rulings"]:
            assert set(finding_ruling) == set(golden["finding_rulings"][0])
        # the golden carries BOTH digests, each recomputing from its input.
        assert golden["findings_digest"] == _sha("\n".join(GOLDEN_FINDINGS))
        assert golden["brief_digest"] == _sha(GOLDEN_BRIEF)
        assert record["findings_digest"] == golden["findings_digest"]
        assert record["brief_digest"] == golden["brief_digest"] == _sha(GOLDEN_BRIEF)
        # the record must reproduce the ACTUAL ruling's CONTENTS, not merely the
        # golden's structure: a record that keeps the digests but falsifies the
        # decision or dispositions must fail.
        assert record["forcing_decision"] == president_forcing_decision(result.ruling)
        assert record["finding_rulings"] == [
            {"id": fr.finding_id, "disposition": fr.disposition, "reason": fr.reason}
            for fr in president_finding_rulings(result.ruling)
        ]
        assert record["rung_index"] == result.rung_index

    run_presroute_contract("ruling_record_matches_frozen_contract", contract)


# ---------------------------------------------------------------------------
# Restored consumer-side runner safety invariants (agent-harness#961 round-7).
# These stub ``invoke_board`` and exercise ``runner._run_legible_panel`` directly,
# so they assert the RUNNER's landing/persistence guarantees independent of how a
# ruling is obtained. PRESROUTE changes the president EXECUTION route, not the
# runner (``runner.py`` is not a PRESROUTE-owned file), so they stay green on base
# AND post-implementation. They were dropped in the initial rewrite and are
# restored here byte-equal to their ``origin/main`` source.
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Round-8 additions (agent-harness#961): a carrier for the route-failure property
# codex+grok found uncovered, the ladder-resolution invariants the deleted node
# uniquely asserted, and the environment-keying constraint grok surfaced.
# ---------------------------------------------------------------------------


# EC-PRESROUTE-2 (``-k route_failure``): a route/execution FAILURE at a seated rung
# is an ORDINARY error (not typed ``president_unavailable``), so the REAL adapter +
# ladder stop at the first seated rung instead of descending. This is a RED contract,
# not an invariant: the injected launch failure must actually be REACHED, so the node
# cannot pass by taking a route-unavailable path that never launches (the vacuity
# codex and grok split on -- neither reading is decidable before the route exists, so
# the node is made non-vacuous by construction). RED on base (nothing launches),
# green only once the route is wired AND the adapter types the failure as ordinary.
def test_adapter_route_failure_is_not_a_ladder_descent(tmp_path):
    def contract() -> None:
        launched: list[object] = []

        def _boom(*args, **kwargs):
            launched.append(args)
            raise RuntimeError("launch failed")

        with patch.object(panel_invoker, "launch_provider", _boom):
            seam = president_adapter.build_president_invoke(
                DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}
            )
            with pytest.raises(PresidentPolicyError) as excinfo:
                panel_invoker.invoke_president(
                    findings=("F001: [claude] the lock",), invoke=seam, max_substantive_rounds=3
                )
        # Non-vacuity: the injected failure must have been reached through the launch
        # route -- otherwise the node proves nothing about how the adapter classifies
        # a real failure.
        require_capability(
            bool(launched),
            "the seated rung did not reach the launch route (route not wired)",
        )
        assert excinfo.value.code == "president_invocation_failed"
        assert [attempt.rung for attempt in seam.attempts] == [PRESIDENT_LADDER[0]]

    run_presroute_contract("route_failure", contract)


def test_every_president_rung_resolves_on_the_code_review_board(tmp_path):
    # Restores the deleted node's uniquely-asserted invariants: every ladder rung
    # resolves to exactly one seat on the PRODUCTION code-review board, an unknown
    # rung resolves to none, and each rung carries a known harness. Order-agnostic
    # (named by ``PRESIDENT_LADDER``), so it survives the EC-PRESROUTE-3 reorder.
    seats = [president_adapter.seat_for_rung(CODE_REVIEW_BOARD, rung) for rung in PRESIDENT_LADDER]
    assert all(seat is not None for seat in seats)
    assert len({seat.model for seat in seats}) == len(PRESIDENT_LADDER)
    assert {seat.harness for seat in seats} == {"claude", "codex", "grok", "gemini"}
    assert president_adapter.seat_for_rung(CODE_REVIEW_BOARD, "nobody") is None


def test_native_fable_auto_wiring_keys_on_passed_env_not_process_env(monkeypatch):
    # grok's constraint, frozen as a node. The native-fable adapter may be
    # auto-wired only from the PASSED ``base_env``, never the process environment:
    # the board tooling forwards CLAUDECODE=1 into the processes it launches, so an
    # implementation keyed on ``os.environ`` would auto-wire the adapter and run
    # seats HERE (no base_env, no seam) and break this refusal, while behaving
    # differently in CI. Freezing it as a node is stronger than a lane requirement
    # and pins no storage strategy.
    #
    # DISCLOSURE -- inert on base: today no auto-wiring exists, so the refusal holds
    # regardless of any environment; it becomes load-bearing once SL-2 adds the
    # native-fable auto-wire, which must consult the passed env only.
    monkeypatch.setenv("CLAUDECODE", "1")
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
