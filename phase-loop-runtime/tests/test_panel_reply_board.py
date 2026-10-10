"""`advisor-board --reply-format json`: a machine-consumable, verified reply per seat.

`panel_reply` is the strict verifier (its own tests). These tests pin the wiring around it:

- the flag, its refusals, and the brief it builds (the brief is bound by the HARDEN instruction
  digest and the sealed prompt envelope, so the runtime extends the brief itself and mints the
  digest from exactly those bytes);
- `invoke_board(reply_format="json")`: a reply that verifies is attached, one that does not is
  DEGRADED with a typed `panel_reply_<kind>` detail and its text kept, and every seat is checked
  before a streaming consumer can see it;
- the default path (no flag) is byte-for-byte what it was.

Hermetic: composition and dispatch are patched; no vendor CLI is spawned.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import pytest

from harden_tdd_guard import invoke_sanctioned_board_control
from phase_loop_runtime import cli
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import panel_reply as pr
from phase_loop_runtime.advisor_board import backing as backing_mod
from phase_loop_runtime.advisor_board import matrix as matrix_module
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.advisor_board.schema import Board, Seat
from phase_loop_runtime.panel_invoker import PanelLegResult

# The CLI harness of the advisory tests: composition and dispatch patched, the brief file read.
from test_advisor_board_advisory_cli_802 import (  # noqa: E402
    _DEFAULT_JSON_KEYS,
    _REVIEW_BRIEF,
    _Run,
    _repo_root,
    bundle,  # noqa: F401  (fixture)
    no_git_env,  # noqa: F401  (fixture)
    outside_git,  # noqa: F401  (fixture)
)

FINDING = {"severity": "blocking", "title": "Race in the lease", "body": "Two seats can share a uid."}
NIT = {"severity": "non_blocking", "title": "Nit", "body": "Name the constant."}


def _reply(text_verdict: str | None = None, **fields) -> str:
    """A seat's whole reply: the JSON object, then the legacy last line."""
    body = {"verdict": "AGREE", "summary": "Looks right.", "findings": []}
    body.update(fields)
    last = text_verdict if text_verdict is not None else body.get("verdict")
    return json.dumps(body, indent=1) + (f"\n{last}" if last else "")


GOOD = _reply()
GOOD_DISAGREE = _reply(verdict="DISAGREE", findings=[FINDING])


# --- the brief the flag builds ---------------------------------------------------------------

def test_the_flag_parses_and_defaults_off():
    parser = cli.build_parser()
    assert parser.parse_args(["advisor-board", "b.md"]).reply_format is None
    assert parser.parse_args(["advisor-board", "b.md", "--reply-format", "json"]).reply_format == "json"
    with pytest.raises(SystemExit):
        parser.parse_args(["advisor-board", "b.md", "--reply-format", "xml"])


def test_the_default_run_is_untouched_by_the_flag(monkeypatch, bundle):  # noqa: F811
    monkeypatch.chdir(_repo_root())
    run = _Run(monkeypatch)
    rc, out, _err = run(["advisor-board", str(bundle), "--json"])
    assert rc == 0
    [invoked] = run.invoke_calls
    assert "reply_format" not in invoked and "brief_ref" not in invoked
    assert set(json.loads(out)) == _DEFAULT_JSON_KEYS
    assert all("reply" not in leg for leg in json.loads(out)["legs"])


def test_the_flag_stages_the_review_brief_plus_the_format_as_one_digest_bound_brief(monkeypatch, bundle):  # noqa: F811
    monkeypatch.chdir(_repo_root())
    run = _Run(monkeypatch)
    digests: list[str] = []
    real_set = backing_mod.set_review_instruction_digest
    monkeypatch.setattr(backing_mod, "set_review_instruction_digest",
                        lambda text: (digests.append(text), real_set(text))[1])
    rc, out, err = run(["advisor-board", str(bundle), "--json", "--reply-format", "json"])
    assert rc == 0, err
    expected = _REVIEW_BRIEF.rstrip("\n") + "\n\n" + pr.render_reply_instructions("review")
    [invoked] = run.invoke_calls
    assert invoked["reply_format"] == "json"
    assert invoked["_brief_text"] == expected                        # the file every seat's brief is
    assert digests == [expected]                                     # the digest is minted from the same bytes
    assert _REVIEW_BRIEF in expected and "JSON Schema of the JSON object" in expected
    payload = json.loads(out)
    assert set(payload) == _DEFAULT_JSON_KEYS | {"reply_format"} and payload["reply_format"] == "json"


def test_the_json_payload_carries_each_verified_reply_and_only_those(monkeypatch, bundle):  # noqa: F811
    from phase_loop_runtime.panel_invoker import PanelResult

    monkeypatch.chdir(_repo_root())
    run = _Run(monkeypatch)
    verified = PanelLegResult(leg="codex", status="OK", text=GOOD, seat_key="codex:red-team")
    pi.attach_panel_reply(verified, pr.PanelSeatReply(
        verdict="DISAGREE", summary="Two seats can share a uid.", findings=[FINDING]))
    held = PanelLegResult(leg="gemini", status="DEGRADED", text="Fine.\nAGREE",
                          detail="panel_reply_no_json", seat_key="gemini:alt")
    plain = PanelLegResult(leg="grok", status="OK", text=GOOD, seat_key="grok:adversarial")
    other = PanelLegResult(leg="claude", status="OK", text=GOOD, seat_key="claude:corr")
    monkeypatch.setattr(pi, "invoke_board", lambda board, artifact, **kw: PanelResult(
        legs=(verified, held, plain, other)))
    rc, out, err = run(["advisor-board", str(bundle), "--json", "--reply-format", "json"])
    assert rc in (0, 1), err
    legs = {leg["leg"]: leg for leg in json.loads(out)["legs"]}
    assert legs["codex"]["reply"] == {
        "verdict": "DISAGREE", "summary": "Two seats can share a uid.",
        "findings": [{**FINDING, "location": None}]}
    assert legs["gemini"]["status"] == "DEGRADED" and legs["gemini"]["detail"] == "panel_reply_no_json"
    assert all("reply" not in legs[k] for k in ("gemini", "grok", "claude"))     # nothing is invented


def test_the_brief_file_does_not_outlive_the_run(monkeypatch, bundle):  # noqa: F811
    monkeypatch.chdir(_repo_root())
    run = _Run(monkeypatch)
    run(["advisor-board", str(bundle), "--json", "--reply-format", "json"])
    assert not Path(run.invoke_calls[0]["brief_ref"]).exists()


def test_reply_format_is_refused_with_advisory_before_any_probe(monkeypatch, bundle, outside_git):  # noqa: F811
    """An advisory run is recognised by the exact digest of its contract, so extending that brief
    could make a non-landing review stop looking like one."""
    run = _Run(monkeypatch)
    rc, _out, err = run(["advisor-board", str(bundle), "--advisory", "--reply-format", "json"])
    assert rc == 2 and "cannot be combined with --advisory" in err
    assert run.compose_calls == [] and run.invoke_calls == [] and run.prepare_calls == []


def test_the_advisory_contract_recognition_is_not_loosened():
    from phase_loop_runtime.advisor_board.advisory_contract import ADVISORY_CONTRACT, is_advisory_brief

    assert is_advisory_brief(ADVISORY_CONTRACT)
    extended = ADVISORY_CONTRACT.rstrip("\n") + "\n\n" + pr.render_reply_instructions("review")
    assert not is_advisory_brief(extended)        # which is why the CLI refuses to build it


def test_invoke_board_rejects_an_unknown_reply_format():
    with pytest.raises(ValueError, match="reply_format"):
        pi.invoke_board(DEFAULT_BOARD, "A", reply_format="xml")


# --- verifying a seat's reply ----------------------------------------------------------------

@pytest.mark.parametrize("text, kind", [
    (GOOD, None),
    (GOOD_DISAGREE, None),
    ("```json\n" + json.dumps({"verdict": "AGREE", "summary": "ok", "findings": []}) + "\n```\nAGREE", None),
    ("I reviewed it. AGREE", "no_json"),                                       # the legacy reply, no JSON
    (GOOD + "\nDISAGREE", "terminal_mismatch"),                               # the JSON says AGREE
    (_reply(text_verdict="DISAGREE"), "terminal_mismatch"),
    (_reply(text_verdict=""), "terminal_mismatch"),                           # no last line at all
    (_reply(verdict="DISAGREE", findings=[NIT]), "verdict_inconsistent"),
    (_reply(summary=5), "schema_mismatch"),
    (GOOD + "\n" + GOOD, "ambiguous_reply"),
])
def test_review_replies_are_verified_with_the_legacy_last_line(text, kind):
    outcome = pi._structured_reply_outcome(text, "review")
    assert outcome.failure == kind and outcome.verified == (kind is None)


@pytest.mark.parametrize("text, kind", [
    (json.dumps({"summary": "Go with B.", "findings": [NIT]}) + "\nRECOMMENDATION: option B", None),
    (json.dumps({"summary": "Go with B.", "findings": []}), "recommendation_missing"),
    (json.dumps({"summary": "Go with B.", "findings": []}) + "\nOption B is best.", "recommendation_missing"),
    (json.dumps({"verdict": "AGREE", "summary": "x", "findings": []}) + "\nRECOMMENDATION: B", "verdict_forbidden"),
])
def test_advisory_replies_are_verified_with_the_recommendation_line(text, kind):
    outcome = pi._structured_reply_outcome(text, "advisory")
    assert outcome.failure == kind and outcome.verified == (kind is None)


def test_a_verified_reply_is_attached_and_the_result_is_otherwise_untouched():
    leg = PanelLegResult(leg="claude", status="OK", text=GOOD, seat_key="claude:m:high:a")
    leg = pi.attach_seat_notices(leg, ())
    pi._verify_structured_reply_result(leg, "review")
    assert leg.status == "OK" and leg.usable and leg.detail is None and leg.text == GOOD
    assert leg.panel_reply is not None and leg.panel_reply.verdict == "AGREE"
    assert "panel_reply" not in asdict(leg)                                    # a non-field attachment


def test_a_reply_that_does_not_verify_is_degraded_keeps_its_text_and_its_attachments():
    leg = PanelLegResult(leg="claude", status="OK", text="Fine. AGREE", seat_key="claude:x")
    pi.attach_harden_isolation_evidence(leg, {"provider_harness": "claude"})
    pi._verify_structured_reply_result(leg, "review")
    assert (leg.status, str(leg.detail)) == ("DEGRADED", "panel_reply_no_json")
    assert not leg.usable and leg.text == "Fine. AGREE" and leg.panel_reply is None
    assert leg.harden_isolation_evidence == {"provider_harness": "claude"}     # nothing was rebuilt


def test_a_seat_that_already_failed_is_left_exactly_as_it_was():
    leg = PanelLegResult(leg="codex", status="TIMEOUT", text="", detail="timeout")
    pi._verify_structured_reply_result(leg, "review")
    assert (leg.status, leg.detail, leg.panel_reply) == ("TIMEOUT", "timeout", None)


def test_the_check_runs_once_per_result():
    leg = PanelLegResult(leg="claude", status="OK", text=GOOD)
    pi._verify_structured_reply_result(leg, "review")
    object.__setattr__(leg, "_panel_reply", None)                              # tamper with the outcome
    pi._verify_structured_reply_result(leg, "review")
    assert leg.panel_reply is None                                             # not re-derived


def test_every_panel_reply_detail_is_in_the_closed_vocabulary():
    assert {f"panel_reply_{kind}" for kind in pr.SEAT_FAILURE_KINDS} <= pi._HARNESS_DETAIL_CODES
    assert "panel_reply_empty" not in pi._HARNESS_DETAIL_CODES and "panel_reply_invalid_mode" not in pi._HARNESS_DETAIL_CODES


# --- through the real board ------------------------------------------------------------------

def _board_by_leg(texts: dict[str, str], *, reply_format: str | None, **kwargs):
    seen_calls: list[str] = []

    def provider(leg, artifact, *, mode="review", **kw):
        seen_calls.append(leg)
        return "OK", texts[leg]

    with (
        tempfile.TemporaryDirectory(prefix="reply-format-repo-") as td,
        patch.object(matrix_module.DEFAULT_HARNESS_REGISTRY, "is_available", return_value=True),
        patch.object(pi, "_default_spawn_via_provider", side_effect=provider),
    ):
        extra = {"reply_format": reply_format} if reply_format is not None else {}
        result = invoke_sanctioned_board_control(
            DEFAULT_BOARD, "STAGED-ARTIFACT", repo_dir=Path(td), require_live_matrix_probe=True,
            **extra, **kwargs,
        )
    return result, seen_calls


MIXED = {
    "codex": GOOD,                                        # verifies
    "gemini": "Looks fine to me.\nAGREE",                 # the legacy reply: valid today, no JSON
    "claude": GOOD + "\nDISAGREE",                        # JSON and last line disagree
    "grok": _reply(verdict="DISAGREE", findings=[NIT]),   # DISAGREE with no blocking finding
}


def _by_leg(result) -> dict:
    return {leg.leg: leg for leg in result.legs}


def test_a_board_attaches_what_verifies_and_degrades_what_does_not():
    result, _calls = _board_by_leg(MIXED, reply_format="json")
    legs = _by_leg(result)
    assert legs["codex"].status == "OK" and legs["codex"].panel_reply.verdict == "AGREE"
    assert [(legs[k].status, str(legs[k].detail)) for k in ("gemini", "claude", "grok")] == [
        ("DEGRADED", "panel_reply_no_json"),
        ("DEGRADED", "panel_reply_terminal_mismatch"),
        ("DEGRADED", "panel_reply_verdict_inconsistent"),
    ]
    for key in ("gemini", "claude", "grok"):
        assert legs[key].text == MIXED[key] and not legs[key].usable and legs[key].panel_reply is None


def test_the_same_board_without_the_flag_is_unchanged():
    result, _calls = _board_by_leg(MIXED, reply_format=None)
    assert {leg.status for leg in result.legs} == {"OK"}
    assert all(leg.detail is None and leg.panel_reply is None for leg in result.legs)
    assert {leg.leg: leg.text for leg in result.legs} == MIXED


def test_a_streaming_consumer_never_sees_an_unverified_reply_as_ok(tmp_path):
    """The check runs inside the per-seat worker, before the callback and the verdict file."""
    seen: dict[str, tuple[str, str | None]] = {}
    result, _calls = _board_by_leg(
        MIXED, reply_format="json", stream_dir=tmp_path,
        on_leg_complete=lambda leg: seen.__setitem__(leg.leg, (leg.status, leg.detail and str(leg.detail))),
    )
    assert seen["codex"] == ("OK", None)
    assert seen["gemini"] == ("DEGRADED", "panel_reply_no_json")
    files = {json.loads(p.read_text())["leg"]: json.loads(p.read_text()) for p in tmp_path.glob("leg-*.verdict.json")}
    assert files["codex"]["reply"]["verdict"] == "AGREE" and files["codex"]["status"] == "OK"
    assert all("reply" not in files[k] and files[k]["status"] == "DEGRADED" for k in ("gemini", "claude", "grok"))


def test_the_per_seat_verdict_file_has_no_reply_key_by_default(tmp_path):
    _board_by_leg(MIXED, reply_format=None, stream_dir=tmp_path)
    files = [json.loads(p.read_text()) for p in tmp_path.glob("leg-*.verdict.json")]
    assert files and all("reply" not in f for f in files)


def test_advisory_boards_are_verified_in_advisory_mode():
    board = Board(name="two", purpose="brainstorm", seats=tuple(
        Seat(model="claude-opus-5-5", effort="high", harness="claude", lens=lens) for lens in ("a", "b")))
    texts = iter([
        json.dumps({"summary": "Go with B.", "findings": []}) + "\nRECOMMENDATION: option B",
        json.dumps({"summary": "Go with B.", "findings": []}) + "\nOption B.",
    ])

    def provider(leg, artifact, **kw):
        return "OK", next(texts)

    with (
        tempfile.TemporaryDirectory(prefix="reply-format-repo-") as td,
        patch.object(matrix_module.DEFAULT_HARNESS_REGISTRY, "is_available", return_value=True),
        patch.object(pi, "_default_spawn_via_provider", side_effect=provider),
    ):
        result = invoke_sanctioned_board_control(
            board, "ARTIFACT", repo_dir=Path(td), require_live_matrix_probe=True,
            reply_format="json", max_concurrency=1)
    assert [(leg.status, str(leg.detail)) for leg in result.legs] == [
        ("OK", "None"), ("DEGRADED", "panel_reply_recommendation_missing")]
    assert result.legs[0].panel_reply.verdict is None


# --- a natively filled seat is held to the same format ---------------------------------------

def _native_fill_run(tmp_path, monkeypatch, fill_text: str):
    """One Claude seat deferred to the driving session (under Claude Code) and filled natively, with
    the brief the CLI would stage: the review brief plus the reply format, as a brief file."""
    import hashlib

    from phase_loop_runtime.advisor_board.composition import composition_digest
    from test_native_claude_seat_fill import CC, _fill, _seat

    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    brief = _REVIEW_BRIEF.rstrip("\n") + "\n\n" + pr.render_reply_instructions("review")
    brief_path = tmp_path / "brief.md"
    brief_path.write_text(brief, encoding="utf-8")
    seat = _seat()
    board = Board(name="claude-solo", purpose="premerge-review", seats=(seat,))
    fill = _fill(
        pi.NativeLegFill, seat, text=fill_text,
        artifact_sha256=hashlib.sha256("review me\n".encode()).hexdigest(),
        brief_sha256=hashlib.sha256(brief.encode()).hexdigest(),
        composition_sha256=composition_digest(board),
    )
    with patch.object(pi, "_claude_code_support_status", return_value=(True, "supported")):
        return invoke_sanctioned_board_control(
            board, "", artifact_ref=str(artifact), repo_dir=str(tmp_path), base_env=dict(CC),
            brief_ref=str(brief_path), native_leg_fills=[fill], reply_format="json",
        )


def test_a_native_fill_that_is_a_verified_structured_reply_is_attached(tmp_path, monkeypatch):
    result = _native_fill_run(tmp_path, monkeypatch, GOOD)
    (leg,) = result.legs
    assert leg.status == "OK" and leg.usable and leg.panel_reply is not None
    assert leg.panel_reply.verdict == "AGREE"


def test_a_native_fill_in_the_legacy_format_is_degraded_under_the_flag(tmp_path, monkeypatch):
    """A fill whose last line is a conforming verdict is OK today; under `reply_format` it must also
    be the structured reply, or the machine-consumable guarantee has a hole at the native route."""
    result = _native_fill_run(tmp_path, monkeypatch, "Reviewed.\nAGREE")
    (leg,) = result.legs
    assert (leg.status, str(leg.detail), leg.panel_reply) == ("DEGRADED", "panel_reply_no_json", None)
    assert leg.text == "Reviewed.\nAGREE" and not leg.usable


def test_a_native_fill_on_the_per_seat_path_is_held_to_the_format_too(tmp_path):
    """The other binding site: a board with other seats that ran (so the early all-deferred path
    is not taken). The runtime seats return the legacy reply here, so they degrade; the fill is
    judged on its own text."""
    import hashlib

    from phase_loop_runtime.advisor_board.composition import composition_digest
    from test_native_claude_seat_fill import CC, _fill, _mixed_board, _typed_deferral_spawn

    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    brief = _REVIEW_BRIEF.rstrip("\n") + "\n\n" + pr.render_reply_instructions("review")
    brief_path = tmp_path / "brief.md"
    brief_path.write_text(brief, encoding="utf-8")
    board = _mixed_board()
    claude = next(seat for seat in board.seats if str(seat.harness).lower() == "claude")
    results = {}
    for name, text in (("structured", GOOD), ("legacy", "Reviewed.\nAGREE")):
        fill = _fill(
            pi.NativeLegFill, claude, text=text,
            artifact_sha256=hashlib.sha256(b"review me\n").hexdigest(),
            brief_sha256=hashlib.sha256(brief.encode()).hexdigest(),
            composition_sha256=composition_digest(board),
        )
        with patch.object(pi, "_claude_code_support_status", return_value=(True, "supported")):
            result = invoke_sanctioned_board_control(
                board, "", spawn=_typed_deferral_spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path),
                base_env=dict(CC), brief_ref=str(brief_path), native_leg_fills=[fill], reply_format="json",
            )
        results[name] = next(leg for leg in result.legs if leg.leg == "claude")
    assert results["structured"].status == "OK" and results["structured"].panel_reply is not None
    assert (results["legacy"].status, str(results["legacy"].detail)) == ("DEGRADED", "panel_reply_no_json")
