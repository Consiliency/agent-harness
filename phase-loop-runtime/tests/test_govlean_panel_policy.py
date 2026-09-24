"""GOVLEAN review-tier + PRESROUTE president-ladder falsifiers (SL-0 frozen corpus).

This file was frozen byte-equal from SL-0 landing until agent-harness#998 merged
(content_tdd_receipt.v1). The post-merge default-order amendment is agent-harness#1027.
The pinned ``-k`` node identifiers EC-PRESROUTE selects are ``ladder`` and
``requires_president_false_refused``; the remaining tests are order-agnostic
GOVLEAN invariants that stay green across the ladder reorder because they name
rungs by ``PRESIDENT_LADDER`` index, not by literal alias.

The pinned contracts were frozen for SL-1/SL-2; the post-merge default-order
amendment changes only the first assertion:

* ``panel_invoker.PRESIDENT_LADDER == ("fable", "sol", "grok", "gemini")`` — the
  amended EC-PRESROUTE-3 seat-alias order, each entry a bare alias resolving to
  its vendor's registry PIN (agent-harness#1027).
* ``panel_invoker.enforce_requires_president(tier, *, requires_president: bool)``
  raises ``PresidentPolicyError`` with code ``requires_president_override_refused``
  for a ``PLAN``/``PRODUCTION_CODE`` landing carrying ``requires_president=False``,
  and is a no-op otherwise (EC-PRESROUTE-4).
"""
from __future__ import annotations

import importlib

import pytest

from harden_tdd_guard import invoke_sanctioned_board_control
from president_fakes import deferring_president
from presroute_content_tdd_adapter import (
    require_attr,
    require_capability,
    run_presroute_contract,
)
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
from phase_loop_runtime.advisor_board.schema import Board

from .govlean_freeze_receipt import govlean_api_available


pytestmark = pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.panel_invoker", "ReviewLandingTier"),
    reason="GOVLEAN review-policy capability absent",
)

# The EC-PRESROUTE-3 ladder is written in exactly one place in the codebase
# (``PRESIDENT_LADDER``); this expectation is the pinned test referencing it.
EC_PRESROUTE_3_LADDER = ("fable", "sol", "grok", "gemini")
_SEAT_ALIASES = {"fable", "sol", "gemini", "grok"}


def _panel():
    return importlib.import_module("phase_loop_runtime.panel_invoker")


def _valid_ruling(decision: str = "block") -> str:
    return (
        "FINDING GOV-1: BLOCKING — validation evidence is required\n"
        f"FORCING DECISION: {decision}"
    )


def test_review_policy_uses_full_board_and_president_only_for_plan_or_production_code():
    panel = _panel()

    assert {tier.value for tier in panel.ReviewLandingTier} == {
        "plan",
        "production_code",
        "tests_only",
        "docs_only",
    }
    for tier in (panel.ReviewLandingTier.PLAN, panel.ReviewLandingTier.PRODUCTION_CODE):
        policy = panel.review_policy_for_tier(tier)
        assert policy.required_seats == ("fable", "sol", "gemini", "grok")
        assert policy.requires_president is True
    for tier in (panel.ReviewLandingTier.TESTS_ONLY, panel.ReviewLandingTier.DOCS_ONLY):
        policy = panel.review_policy_for_tier(tier)
        assert policy.required_seats == ("grounded",)
        assert policy.requires_president is False


def test_president_reasks_once_for_missing_terminal_grammar_without_consuming_a_substantive_round():
    panel = _panel()
    top = panel.PRESIDENT_LADDER[0]
    attempts: list[tuple[str, str]] = []
    responses = iter(
        (
            {"status": "ok", "text": "I agree without the required ledger."},
            {"status": "ok", "text": _valid_ruling()},
        )
    )

    def invoke(model: str, prompt: str):
        attempts.append((model, prompt))
        return next(responses)

    ruling = panel.invoke_president(
        findings=("GOV-1: validate evidence",),
        invoke=invoke,
        max_substantive_rounds=3,
    )

    assert [model for model, _prompt in attempts] == [top, top]
    assert ruling.model == top
    assert ruling.substantive_rounds == 1
    assert ruling.format_reasks == 1
    assert all("FINDING <id>" in prompt and "FORCING DECISION:" in prompt for _, prompt in attempts)
    assert all("critic template" not in prompt.lower() for _, prompt in attempts)


def test_president_descends_only_through_typed_availability_failures_and_never_on_a_blocking_ruling():
    panel = _panel()
    top, second = panel.PRESIDENT_LADDER[0], panel.PRESIDENT_LADDER[1]
    attempts: list[str] = []

    def availability_then_second(model: str, _prompt: str):
        attempts.append(model)
        if model == top:
            return {"status": "unavailable", "code": "president_unavailable"}
        return {"status": "ok", "text": _valid_ruling("proceed after repair")}

    ruling = panel.invoke_president(
        findings=("GOV-1: validate evidence",),
        invoke=availability_then_second,
        max_substantive_rounds=3,
    )
    assert attempts == [top, second]
    assert ruling.model == second

    no_descent_attempts: list[str] = []
    blocking = panel.invoke_president(
        findings=("GOV-1: validate evidence",),
        invoke=lambda model, _prompt: (
            no_descent_attempts.append(model) or {"status": "ok", "text": _valid_ruling("reject")}
        ),
        max_substantive_rounds=3,
    )
    assert no_descent_attempts == [top]
    assert blocking.model == top


def test_president_does_not_descend_on_an_untyped_or_nonavailability_failure():
    panel = _panel()
    attempts: list[str] = []

    with pytest.raises(panel.PresidentPolicyError):
        panel.invoke_president(
            findings=("GOV-1: validate evidence",),
            invoke=lambda model, _prompt: (
                attempts.append(model)
                or {"status": "error", "code": "provider_protocol_error"}
            ),
            max_substantive_rounds=3,
        )

    assert attempts == [panel.PRESIDENT_LADDER[0]]


def test_degraded_read_only_president_cannot_defer_validation_it_identified_as_necessary():
    panel = _panel()

    with pytest.raises(panel.PresidentPolicyError) as excinfo:
        panel.invoke_president(
            findings=("GOV-1: validate evidence",),
            invoke=lambda _model, _prompt: {
                "status": "degraded",
                "text": "FINDING GOV-1: DEFERRED — validation evidence is required\nFORCING DECISION: defer",
            },
            max_substantive_rounds=3,
        )

    assert excinfo.value.code == "degraded_president_validation_deferred"


# EC-PRESROUTE-3 (pinned ``-k ladder``): the president availability ladder is the
# seat-alias order, each alias resolving to its vendor's registry PIN, and the
# walk visits the rungs in that order, descending only on typed unavailability.
def test_president_ladder_is_the_ec_presroute_3_seat_alias_order():
    def contract() -> None:
        panel = _panel()
        president_adapter = importlib.import_module("phase_loop_runtime.president_adapter")
        from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

        # Capability gate: the ladder has been reordered to the seat-alias tuple.
        require_capability(
            tuple(panel.PRESIDENT_LADDER) == EC_PRESROUTE_3_LADDER,
            "PRESIDENT_LADDER is not yet the EC-PRESROUTE-3 seat-alias order",
        )
        # Each rung is a bare seat alias (not an inline model id) resolving THROUGH
        # its vendor's registry PIN: the seat's model must be a concrete registry
        # id the alias table maps back to this exact alias (round-trip identity),
        # never the alias itself.
        alias_table = panel.DEFAULT_REVIEW_SEAT_ALIASES
        for alias in panel.PRESIDENT_LADDER:
            assert alias in _SEAT_ALIASES
            seat = president_adapter.seat_for_rung(DEFAULT_BOARD, alias)
            assert seat is not None, f"ladder rung {alias!r} resolves to no seat"
            assert seat.model != alias, f"rung {alias!r} pins the alias, not a registry PIN"
            assert seat.model in alias_table, f"rung {alias!r} model {seat.model!r} is not a registry PIN"
            assert alias_table[seat.model] == alias, (
                f"rung {alias!r} PIN {seat.model!r} does not resolve back to {alias!r}"
            )

        attempts: list[str] = []
        last = panel.PRESIDENT_LADDER[-1]

        def invoke(model: str, _prompt: str):
            attempts.append(model)
            if model != last:
                return {"status": "unavailable", "code": "president_unavailable"}
            return {"status": "ok", "text": _valid_ruling("proceed")}

        ruling = panel.invoke_president(
            findings=("GOV-1: validate evidence",),
            invoke=invoke,
            max_substantive_rounds=3,
        )
        assert attempts == list(EC_PRESROUTE_3_LADDER)
        assert ruling.model == last

    run_presroute_contract("ladder", contract)


def _board() -> Board:
    return Board(name="full", purpose="premerge-review", seats=DEFAULT_SEATS)


def _ok_spawn(leg: str, artifact: str) -> tuple[str, str]:
    return "OK", f"{leg} found: the {leg} concern\nAGREE"


# EC-PRESROUTE-4 (pinned ``-k requires_president_false_refused``): a
# ``plan``/``production_code`` landing carrying ``requires_president=False`` is
# refused by the runtime with a typed reason, not merely documented -- and the
# guard is actually REACHED on a president-tier board landing, not a dead helper.
def test_plan_or_production_requires_president_false_refused():
    def contract() -> None:
        panel = _panel()
        enforce = require_attr(panel, "enforce_requires_president")
        president_tiers = (
            panel.ReviewLandingTier.PLAN,
            panel.ReviewLandingTier.PRODUCTION_CODE,
        )
        # 1. the guard refuses a False override with a typed reason ...
        for tier in president_tiers:
            with pytest.raises(panel.PresidentPolicyError) as excinfo:
                enforce(tier, requires_president=False)
            assert excinfo.value.code == "requires_president_override_refused"
        # ... and is a no-op for the honest value and the non-president tiers.
        for tier in president_tiers:
            assert enforce(tier, requires_president=True) is None
        for tier in (panel.ReviewLandingTier.TESTS_ONLY, panel.ReviewLandingTier.DOCS_ONLY):
            assert enforce(tier, requires_president=False) is None

        # 2. END-TO-END: a president-tier landing that CARRIES requires_president=False
        #    (through the review-policy override) is REFUSED by production dispatch,
        #    while the honest True proceeds. An implementation that hardcodes True or
        #    never wires the guard into the landing lets the False override through
        #    and fails here -- reachability alone is not enough.
        from president_fakes import ScriptedPresident

        def policy(requires_president: bool):
            return panel.ReviewLandingPolicy(
                required_seats=("fable", "sol", "gemini", "grok"),
                requires_president=requires_president,
            )

        for tier in president_tiers:
            with pytest.raises(panel.PresidentPolicyError) as excinfo:
                invoke_sanctioned_board_control(
                    _board(),
                    "artifact",
                    spawn=_ok_spawn,
                    landing_tier=tier,
                    review_policy=policy(False),
                    president_invoke=ScriptedPresident([deferring_president]),
                )
            assert excinfo.value.code == "requires_president_override_refused"
        for tier in president_tiers:
            invoke_sanctioned_board_control(
                _board(),
                "artifact",
                spawn=_ok_spawn,
                landing_tier=tier,
                review_policy=policy(True),
                president_invoke=ScriptedPresident([deferring_president]),
            )

    run_presroute_contract("requires_president_false_refused", contract)
