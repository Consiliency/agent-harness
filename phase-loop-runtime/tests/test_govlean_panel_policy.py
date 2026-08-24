"""GOVLEAN EC-GOVLEAN-5 review-tier and president-policy falsifiers."""
from __future__ import annotations

import importlib

import pytest

from .govlean_freeze_receipt import govlean_api_available


pytestmark = pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.panel_invoker", "ReviewLandingTier"),
    reason="GOVLEAN review-policy capability absent",
)


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

    assert [model for model, _prompt in attempts] == ["fable", "fable"]
    assert ruling.model == "fable"
    assert ruling.substantive_rounds == 1
    assert ruling.format_reasks == 1
    assert all("FINDING <id>" in prompt and "FORCING DECISION:" in prompt for _, prompt in attempts)
    assert all("critic template" not in prompt.lower() for _, prompt in attempts)


def test_president_descends_only_through_typed_availability_failures_and_never_on_a_blocking_ruling():
    panel = _panel()
    attempts: list[str] = []

    def availability_then_sol(model: str, _prompt: str):
        attempts.append(model)
        if model == "fable":
            return {"status": "unavailable", "code": "president_unavailable"}
        return {"status": "ok", "text": _valid_ruling("proceed after repair")}

    ruling = panel.invoke_president(
        findings=("GOV-1: validate evidence",),
        invoke=availability_then_sol,
        max_substantive_rounds=3,
    )
    assert attempts == ["fable", "sol"]
    assert ruling.model == "sol"

    no_descent_attempts: list[str] = []
    blocking = panel.invoke_president(
        findings=("GOV-1: validate evidence",),
        invoke=lambda model, _prompt: (
            no_descent_attempts.append(model) or {"status": "ok", "text": _valid_ruling("reject")}
        ),
        max_substantive_rounds=3,
    )
    assert no_descent_attempts == ["fable"]
    assert blocking.model == "fable"


def test_president_ladder_reaches_gemini_without_skipping_a_rung():
    panel = _panel()
    attempts: list[str] = []
    expected = ("fable", "sol", "grok-4.6", "gemini-3.7-flash")

    def invoke(model: str, _prompt: str):
        attempts.append(model)
        if model != expected[-1]:
            return {"status": "unavailable", "code": "president_unavailable"}
        return {"status": "ok", "text": _valid_ruling("proceed")}

    ruling = panel.invoke_president(
        findings=("GOV-1: validate evidence",),
        invoke=invoke,
        max_substantive_rounds=3,
    )

    assert tuple(panel.PRESIDENT_LADDER) == expected
    assert attempts == list(expected)
    assert ruling.model == "gemini-3.7-flash"


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

    assert attempts == ["fable"]


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
