"""The strict verifier for a seat's machine-consumable reply (`panel_reply`).

The corpus includes the replies BAML v1's lenient `.parse` accepted in a 0.20.1 spike and that
must NOT verify: a truncated reply repaired into `AGREE` with its findings dropped, `summary: 5`
coerced to `"5"`, `findings: "none"` coerced to `[]`, and the first of two objects taken."""

from __future__ import annotations

import json

import pytest

from phase_loop_runtime import panel_reply as pr

BLOCKING = {"severity": "blocking", "title": "Race in the lease", "body": "Two seats can share a uid."}
MINOR = {"severity": "non_blocking", "title": "Nit", "body": "Name the constant.", "location": "a.py:10"}


def _reply(**fields):
    base = {"verdict": "AGREE", "summary": "Looks right.", "findings": []}
    base.update(fields)
    return {key: value for key, value in base.items() if value is not ...}


def _text(reply) -> str:
    return json.dumps(reply)


def _verify(text, mode="review"):
    return pr.extract_reply(text, mode)


def test_a_clean_review_reply_verifies_and_derives_its_verdict():
    outcome = _verify(_text(_reply(verdict="DISAGREE", findings=[BLOCKING, MINOR])))
    assert outcome.verified and not outcome.wrapped and outcome.failure is None
    assert pr.derive_terminal_verdict(outcome.reply) == "DISAGREE"
    assert [finding.severity for finding in outcome.reply.findings] == ["blocking", "non_blocking"]


def test_an_advisory_reply_has_no_verdict():
    outcome = _verify(_text(_reply(verdict=..., findings=[MINOR])), "advisory")
    assert outcome.verified and outcome.reply.verdict is None
    assert pr.derive_terminal_verdict(outcome.reply) is None


@pytest.mark.parametrize("text", [
    "```json\n" + _text(_reply()) + "\n```",                                   # fenced
    "Here is my review.\n\n" + json.dumps(_reply(), indent=2) + "\n\nThanks.",   # prose around it
    "x { not json } " + _text(_reply()),                                         # stray braces before it
])
def test_a_single_object_inside_surrounding_text_verifies_and_is_marked_wrapped(text):
    outcome = _verify(text)
    assert outcome.verified and outcome.wrapped


def test_braces_inside_a_string_do_not_confuse_the_extraction():
    reply = _reply(summary='Use {"a": 1} and a } in prose.', verdict="AGREE")
    outcome = _verify("note: " + _text(reply))
    assert outcome.verified and outcome.reply.summary.startswith("Use {")


@pytest.mark.parametrize("text, kind", [
    ("", "empty"),
    ("   \n\t ", "empty"),
    (None, "empty"),
    ("AGREE", "no_json"),                                                       # a bare verdict line
    ("no object here", "no_json"),
    (_text(_reply(verdict="DISAGREE", findings=[BLOCKING, MINOR]))[:-15], "no_json"),   # truncated
    ("[1, 2, 3]", "no_json"),                                                   # not an object
])
def test_text_without_a_complete_json_object_never_verifies(text, kind):
    outcome = _verify(text)
    assert not outcome.verified and outcome.failure == kind


def test_a_truncated_reply_is_not_repaired_into_an_agree_with_the_findings_dropped():
    full = _text(_reply(verdict="DISAGREE", findings=[BLOCKING]))
    cut = full[: full.index('"findings"') + len('"findings"') + 3]      # `..., "findings": [`
    assert not _verify(cut).verified


@pytest.mark.parametrize("fields", [
    {"summary": 5},                                  # BAML coerced this to "5"
    {"findings": "none"},                            # BAML coerced this to []
    {"findings": None},
    {"summary": ""},
    {"summary": "   "},
    {"verdict": "agree"},                            # not the exact vocabulary
    {"verdict": "MAYBE"},
    {"unknown": 1},                                  # an extra field
    {"summary": ...},                                # a missing field
    {"findings": [{"severity": "high", "title": "t", "body": "b"}]},
    {"findings": [{"severity": "blocking", "title": "", "body": "b"}]},
    {"findings": [{"severity": "blocking", "title": "t", "body": "  "}]},
    {"findings": [{"severity": "blocking", "title": "t", "body": "b", "extra": 1}]},
    {"findings": [{"severity": "blocking", "title": "t"}]},
    {"findings": [{"severity": "blocking", "title": 3, "body": "b"}]},
    {"findings": [BLOCKING] * (pr._MAX_FINDINGS + 1)},
])
def test_a_reply_that_does_not_match_the_schema_exactly_is_rejected_without_coercion(fields):
    outcome = _verify(_text(_reply(**fields)))
    assert not outcome.verified and outcome.failure == "schema_mismatch"


def test_the_failure_detail_names_fields_and_never_the_reply_text():
    secret = "SECRET-TOKEN-9f3a"
    outcome = _verify(_text(_reply(summary=secret, findings=[{"severity": "high", "title": secret, "body": secret}])))
    assert outcome.failure == "schema_mismatch"
    assert secret not in (outcome.detail or "") and "findings" in outcome.detail


def test_two_replies_are_ambiguous_and_nothing_is_taken_as_the_first():
    first = _reply(verdict="AGREE", summary="first")
    second = _reply(verdict="DISAGREE", summary="second", findings=[BLOCKING])
    outcome = _verify(_text(first) + "\n" + _text(second))
    assert not outcome.verified and outcome.failure == "ambiguous_reply"


def test_one_reply_and_one_unrelated_object_verifies_the_reply():
    outcome = _verify(_text({"note": "unrelated"}) + "\n" + _text(_reply()))
    assert outcome.verified


@pytest.mark.parametrize("reply, kind", [
    (_reply(verdict=...), "verdict_missing"),
    (_reply(verdict=None), "verdict_missing"),
    (_reply(verdict="DISAGREE", findings=[MINOR]), "verdict_inconsistent"),   # DISAGREE needs a blocking finding
    (_reply(verdict="DISAGREE", findings=[]), "verdict_inconsistent"),
    (_reply(verdict="AGREE", findings=[BLOCKING]), "verdict_inconsistent"),   # AGREE allows none
    (_reply(verdict="PARTIALLY AGREE", findings=[]), "verdict_inconsistent"),
])
def test_review_mode_requires_a_verdict_consistent_with_the_findings(reply, kind):
    outcome = _verify(_text(reply))
    assert not outcome.verified and outcome.failure == kind


def test_the_allowed_verdict_and_finding_combinations_verify():
    for reply in (
        _reply(verdict="AGREE", findings=[MINOR]),
        _reply(verdict="PARTIALLY AGREE", findings=[MINOR]),
        _reply(verdict="PARTIALLY AGREE", findings=[BLOCKING]),
        _reply(verdict="DISAGREE", findings=[BLOCKING]),
    ):
        assert _verify(_text(reply)).verified, reply


def test_advisory_mode_forbids_a_verdict():
    outcome = _verify(_text(_reply(verdict="AGREE")), "advisory")
    assert not outcome.verified and outcome.failure == "verdict_forbidden"


def test_an_unknown_mode_is_a_typed_failure_not_an_exception():
    assert _verify(_text(_reply()), "nonsense").failure == "invalid_mode"
    with pytest.raises(ValueError):
        pr.render_reply_instructions("nonsense")


def test_an_oversized_reply_is_refused_before_it_is_parsed():
    outcome = _verify("{" + " " * (pr._MAX_REPLY_BYTES + 10) + "}")
    assert outcome.failure == "too_large"


def test_non_utf8_looking_text_never_raises():
    assert _verify("\ud800 \x00 {\"a\": ").failure == "no_json"


def test_every_failure_the_verifier_returns_is_a_declared_kind():
    for text, mode in (("", "review"), ("x", "review"), ("[]", "review"), (_text({}), "review"),
                       (_text(_reply(verdict="AGREE")), "advisory"), (_text(_reply()), "bad")):
        outcome = _verify(text, mode)
        assert outcome.failure in pr.FAILURE_KINDS and not outcome.verified


@pytest.mark.parametrize("mode", pr.MODES)
def test_the_instructions_are_generated_from_the_verifying_model(mode):
    text = pr.render_reply_instructions(mode)
    schema_block = text.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    shown = json.loads(schema_block)
    assert shown["additionalProperties"] is False
    assert ("verdict" in shown["properties"]) == (mode == "review")
    assert set(shown["required"]) == ({"verdict", "summary", "findings"} if mode == "review" else {"summary", "findings"})
    assert "PanelFinding" in shown["$defs"]
    assert ("Do NOT include a `verdict`" in text) == (mode == "advisory")


def test_a_reply_following_the_instructions_verifies():
    """The example the instructions describe is itself verifiable in the mode it was rendered for."""
    assert _verify(_text(_reply(verdict="PARTIALLY AGREE", findings=[MINOR])), "review").verified
    assert _verify(_text(_reply(verdict=..., findings=[MINOR])), "advisory").verified


def test_the_models_stay_strict_and_closed():
    """Pydantic's default mode already refuses today's int-to-str and str-to-list coercions, so no
    behaviour test distinguishes strict mode; it matters for any field added later (a number, a
    boolean). Pin it, and the closed set of fields, so a loosening is a visible change."""
    for model in (pr.PanelSeatReply, pr.PanelFinding):
        assert model.model_config.get("strict") is True
        assert model.model_config.get("extra") == "forbid"
    assert set(pr.PanelSeatReply.model_fields) == {"verdict", "summary", "findings"}
    assert set(pr.PanelFinding.model_fields) == {"severity", "title", "body", "location"}
