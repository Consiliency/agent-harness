"""#183 companion (Bug 2 / ABDNATIVE) — the deferred claude/Fable seat surfaces a
typed, machine-readable native-fill request ON THE BOARD RESULT, and the board
reports a LOUD requested-vs-delivered shortfall.

Root cause this fixes (operator): a native harness kept running 3-vendor boards
without filling the deferred Fable seat, because the deferral lived only in a LOG
line + a bare ``{status:UNAVAILABLE, text:""}`` — it read as "vendor unavailable,"
not "YOUR seat to fill," and ``usable:true`` masked the requested-4/delivered-3 gap.

This module wires the AFFORDANCE (reusing the shipped #125 ``native_agent_leg_request``
builder) and is DECISION-INDEPENDENT of the #183 dispatch-gate question: it exercises
the under-Claude-Code (#92) deferral, which is preserved under either reconciliation.

Unmarked module (runs in CI; CI excludes only ``dotfiles_integration``).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from harden_tdd_guard import invoke_sanctioned_review_transport
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.advisor_board import Board, Seat
from phase_loop_runtime.advisor_board import composition as comp_mod
from phase_loop_runtime.cli import main as cli_main


def _claude_seat() -> Seat:
    return Seat(model="claude-fable-5", effort="max", harness="claude", lens="correctness")


def _claude_board() -> Board:
    return Board(name="claude-solo", purpose="premerge-review", seats=(_claude_seat(),))


class DeferredSeatSurfacesNativeFillRequest(unittest.TestCase):
    """Default Fable/Opus seats never bypass the subscription TUI policy."""

    def test_board_deferred_seat_carries_request_with_seat_cognition(self):
        session = unittest.mock.MagicMock()
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            scratch = Path(td) / "scratch"
            scratch.mkdir()
            with (
                unittest.mock.patch.object(
                    pi, "_claude_code_support_status", return_value=(True, "supported")
                ),
                unittest.mock.patch.object(pi, "_run_claude_tui_session", session),
            ):
                result = pi.invoke_board(
                    _claude_board(),
                    "",
                    artifact_ref=str(artifact.resolve()),
                    repo_dir=str(scratch),
                    base_env={"CLAUDECODE": "1", "PATH": os.environ.get("PATH", "")},
                )
        (leg,) = result.legs
        # No nested TUI and no native Task substitution.
        self.assertEqual(leg.status, "UNAVAILABLE")
        self.assertEqual(leg.text, "")
        self.assertEqual(leg.detail, "tui_adapter_required")
        session.assert_not_called()
        self.assertIsNone(leg.needs_native_agent)
        self.assertEqual(result.native_fill_requests, ())

    def test_ok_board_has_no_native_request(self):
        result = invoke_sanctioned_review_transport(
            _claude_board(),
            "x",
            spawn=lambda leg, art: ("OK", f"{leg}\nAGREE"),
            base_env={"CLAUDECODE": "1"},
        )
        (leg,) = result.legs
        self.assertEqual(leg.status, "OK")
        self.assertIsNone(leg.needs_native_agent)
        self.assertEqual(result.native_fill_requests, ())

    def _board_with_support(self, supported, base_env):
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            scratch = Path(td) / "scratch"
            scratch.mkdir()
            with unittest.mock.patch.object(
                pi, "_claude_code_support_status", return_value=supported
            ):
                return pi.invoke_board(
                    _claude_board(), "", artifact_ref=str(artifact.resolve()),
                    repo_dir=str(scratch), base_env=base_env,
                )

    def test_under_claude_code_requires_tui_adapter_even_without_local_cli(self):
        result = self._board_with_support(
            (False, "claude_code_version_below_minimum:2.1.196"),
            {"CLAUDECODE": "1", "PATH": os.environ.get("PATH", "")},
        )
        (leg,) = result.legs
        self.assertEqual(leg.status, "UNAVAILABLE")
        self.assertEqual(leg.text, "")
        self.assertEqual(leg.detail, "tui_adapter_required")
        self.assertIsNone(leg.needs_native_agent)

    def test_non_claude_support_missing_is_not_a_fillable_seat(self):
        # A genuine "no claude here" on a NON-Claude host (support missing →
        # UNAVAILABLE with NON-empty detail) is not a deferred seat: no native-fill
        # request (the runtime would have RUN it if the CLI were present).
        result = self._board_with_support(
            (False, "claude_code_version_below_minimum:2.1.196"),
            {"PATH": os.environ.get("PATH", "")},  # no CLAUDECODE
        )
        (leg,) = result.legs
        self.assertEqual(leg.status, "UNAVAILABLE")
        self.assertTrue(leg.text.strip())  # non-empty detail
        self.assertIsNone(leg.needs_native_agent)


class HeadlessNonClaudeRunsLeg(unittest.TestCase):
    """Bug 1 (#183 acceptance): a NON-Claude, non-TTY caller RUNS the one-seat
    Claude/Fable board leg (self-PTY) and gets OK with canonical file output — it
    is NOT deferred, so it carries no native-fill request."""

    def test_board_claude_seat_returns_ok_headless(self):
        # base_env WITHOUT CLAUDECODE == a headless non-Claude caller (e.g. Codex
        # Desktop). The self-PTY TUI runs; the parent's missing tty is irrelevant.
        session = unittest.mock.MagicMock(
            return_value=(0, "A complete advisory.\nAGREE", "claude_tui_file_output", "")
        )
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            scratch = Path(td) / "scratch"
            scratch.mkdir()
            with (
                unittest.mock.patch.object(
                    pi, "_claude_code_support_status", return_value=(True, "supported")
                ),
                unittest.mock.patch.object(
                    pi, "_claude_subscription_auth_ok", return_value=(True, "")
                ),
                unittest.mock.patch.object(pi, "_run_claude_tui_session", session),
            ):
                result = invoke_sanctioned_review_transport(
                    _claude_board(),
                    "",
                    artifact_ref=str(artifact.resolve()),
                    repo_dir=str(scratch),
                    base_env={"PATH": os.environ.get("PATH", "")},  # no CLAUDECODE
                )
        (leg,) = result.legs
        self.assertEqual(leg.status, "OK")
        self.assertIn("AGREE", leg.text)
        self.assertIsNone(leg.needs_native_agent)  # ran, not deferred
        self.assertEqual(result.native_fill_requests, ())
        session.assert_called_once()  # self-PTY session ran headless


_REAL_COMPOSE = comp_mod.compose_review_board


def _hermetic_board(*_a, **_k):
    return _REAL_COMPOSE(is_available=lambda v: v in {"codex", "gemini", "claude", "grok"})


class AdvisorBoardLoudShortfall(unittest.TestCase):
    """`advisor-board --json` reports requested-vs-delivered + the natively-fillable
    seats, rather than treating a 3-usable result as the requested 4-seat board."""

    def _canned_result(self):
        req = pi.native_agent_leg_request(
            leg="claude", mode="review", env={"CLAUDECODE": "1"},
            model="custom-reviewer", seat_key="claude:custom-reviewer:max:correctness",
            effort="max", lens="correctness",
        )
        # CR F2: attach the request post-creation (non-field), never a constructor kwarg.
        claude = pi.attach_native_agent_request(
            pi.PanelLegResult(
                leg="claude", status="UNAVAILABLE", text="", detail="deferred",
                seat_key="claude:claude-fable-5:max:correctness",
            ),
            req,
        )
        return pi.PanelResult(
            legs=(
                pi.PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:adversarial"),
                pi.PanelLegResult(leg="codex", status="OK", text="PARTIALLY AGREE", seat_key="codex:red-team"),
                pi.PanelLegResult(leg="gemini", status="OK", text="AGREE", seat_key="gemini:alt"),
                claude,
            )
        )

    def test_json_reports_shortfall_and_fill_request(self):
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            with (
                unittest.mock.patch.object(comp_mod, "compose_review_board", side_effect=_hermetic_board),
                unittest.mock.patch.object(pi, "invoke_board", return_value=self._canned_result()),
            ):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = cli_main(["advisor-board", str(artifact), "--json"])
        # Floor-based exit unchanged (3 usable == FLOOR_SEATS → 0), but shortfall reported.
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["usable"])
        self.assertEqual(payload["requested_seats"], 4)
        self.assertEqual(payload["delivered_seats"], 3)
        sf = payload["shortfall"]
        self.assertEqual(sf["natively_fillable_seats"], 1)
        self.assertEqual([s["leg"] for s in sf["unfilled_seats"]], ["claude"])
        native = sf["unfilled_seats"][0]["needs_native_agent"]
        self.assertEqual(native["model"], "custom-reviewer")
        self.assertEqual(native["effort"], "max")
        self.assertEqual(native["lens"], "correctness")
        self.assertIn("AGREE", native["verdict_contract"])
        # Per-leg entries also carry the request; OK legs carry None.
        claude_leg = [leg for leg in payload["legs"] if leg["leg"] == "claude"][0]
        self.assertEqual(claude_leg["needs_native_agent"]["seat_key"], native["seat_key"])
        grok_leg = [leg for leg in payload["legs"] if leg["leg"] == "grok"][0]
        self.assertIsNone(grok_leg["needs_native_agent"])

    def test_colliding_seat_keys_do_not_hide_a_failed_twin(self):
        # CR F3: schema permits byte-identical seats with the SAME seat_key. A
        # duplicate key where one seat is OK and its twin FAILED must still report
        # the failed twin — deriving unfilled per-leg (`not usable`), never by key
        # set (which would let the OK twin's key mask the failure = silent drop).
        dup = "codex:gpt-5.6-sol:max:red-team"
        collided = pi.PanelResult(
            legs=(
                pi.PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:adversarial"),
                pi.PanelLegResult(leg="gemini", status="OK", text="AGREE", seat_key="gemini:alt"),
                pi.PanelLegResult(leg="codex", status="OK", text="AGREE", seat_key=dup),
                pi.PanelLegResult(leg="codex", status="TIMEOUT", text="", detail="capped", seat_key=dup),
            )
        )
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            with (
                unittest.mock.patch.object(comp_mod, "compose_review_board", side_effect=_hermetic_board),
                unittest.mock.patch.object(pi, "invoke_board", return_value=collided),
            ):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    cli_main(["advisor-board", str(artifact), "--json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["requested_seats"], 4)
        self.assertEqual(payload["delivered_seats"], 3)
        # The failed twin (same key as an OK seat) is NOT hidden.
        self.assertEqual([s["status"] for s in payload["shortfall"]["unfilled_seats"]], ["TIMEOUT"])


class NativeFillRequestSerializationSafety(unittest.TestCase):
    """CR F2: the attached request is a non-field attribute → asdict / field-walking
    serializers can NEVER include it."""

    def test_asdict_does_not_leak_native_request(self):
        import dataclasses
        req = pi.native_agent_leg_request(
            leg="claude", mode="review", env={"CLAUDECODE": "1"}, model="custom-reviewer"
        )
        leg = pi.attach_native_agent_request(
            pi.PanelLegResult(leg="claude", status="UNAVAILABLE", text="", seat_key="claude:x"),
            req,
        )
        self.assertIsNotNone(leg.needs_native_agent)  # readable via the property
        d = dataclasses.asdict(leg)
        self.assertNotIn("needs_native_agent", d)
        self.assertNotIn("_needs_native_agent", d)
        # A plain leg (none attached) reads None, never AttributeError.
        self.assertIsNone(pi.PanelLegResult(leg="grok", status="OK", text="AGREE").needs_native_agent)

    def test_asdict_does_not_add_refusal_or_fallback_state(self):
        import dataclasses
        leg = pi.PanelLegResult(leg="claude", status="DEGRADED", text="")
        baseline = dataclasses.asdict(leg)
        pi.attach_provider_refusal_state(
            leg, provider_refusal_kind="classifier_refusal", adapter_originated=True
        )
        pi.attach_provider_refusal_state(leg, fallback_used=True)
        self.assertEqual(dataclasses.asdict(leg), baseline)
        self.assertEqual(leg.provider_refusal_kind, "classifier_refusal")
        self.assertTrue(leg.fallback_used)


class DefaultClaudeSeatNeverCarriesNativeFill(unittest.TestCase):

    def test_brief_ref_flows_into_the_request(self):
        session = unittest.mock.MagicMock()  # under Claude Code → never called
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            brief = Path(td) / "brief.md"
            brief.write_text("CUSTOM ACCEPTANCE CONTRACT — be adversarial.\n")
            scratch = Path(td) / "scratch"
            scratch.mkdir()
            with (
                unittest.mock.patch.object(
                    pi, "_claude_code_support_status", return_value=(True, "supported")
                ),
                unittest.mock.patch.object(pi, "_run_claude_tui_session", session),
            ):
                result = pi.invoke_board(
                    _claude_board(), "", artifact_ref=str(artifact.resolve()),
                    brief_ref=str(brief.resolve()), repo_dir=str(scratch),
                    base_env={"CLAUDECODE": "1", "PATH": os.environ.get("PATH", "")},
                )
        (leg,) = result.legs
        self.assertEqual(leg.status, "UNAVAILABLE")
        self.assertEqual(leg.detail, "tui_adapter_required")
        self.assertIsNone(leg.needs_native_agent)


class TypedDeferralReachesTheAttachGate(unittest.TestCase):
    """ah#538 — the gate must test the NORMALIZED body, not the raw spawn text.

    Regression shape matters here. The pre-existing tests in this module either use
    a Fable seat (policy-excluded from native fill, so ``None`` is the correct
    expectation either way) or construct ``PanelLegResult`` objects directly and
    attach the request by hand. Neither drives a NON-policy seat through
    ``_exec_leg``'s own result assembly, which is where the bug lived: the typed-
    detail branch moves ``tui_adapter_required`` out of the body into ``detail`` and
    blanks ``text_value``, but the gate re-read the pre-normalization ``text``, so it
    was False for every typed deferral — unreachable for exactly the cases it exists
    to catch, and no claude seat ever received a fill request.
    """

    @staticmethod
    def _seat(model: str) -> Seat:
        return Seat(model=model, effort="max", harness="claude", lens="correctness")

    def _run(self, model: str):
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            scratch = Path(td) / "scratch"
            scratch.mkdir()
            board = Board(
                name="claude-solo", purpose="premerge-review", seats=(self._seat(model),)
            )
            with unittest.mock.patch.object(
                pi, "_claude_code_support_status", return_value=(True, "supported")
            ):
                result = pi.invoke_board(
                    board,
                    "",
                    artifact_ref=str(artifact.resolve()),
                    repo_dir=str(scratch),
                    base_env={"CLAUDECODE": "1", "PATH": os.environ.get("PATH", "")},
                )
        (leg,) = result.legs
        return result, leg

    def test_non_policy_seat_typed_deferral_requests_a_native_fill(self):
        result, leg = self._run("claude-sonnet-5")
        # The deferral signature the gate documents: UNAVAILABLE, empty body, typed
        # reason relocated into detail.
        self.assertEqual(leg.status, "UNAVAILABLE")
        self.assertEqual(leg.text, "")
        self.assertEqual(leg.detail, "tui_adapter_required")
        # ...and therefore a fill request, carrying this seat's cognition so a
        # driving harness can honour it under the same acceptance contract.
        self.assertIsNotNone(leg.needs_native_agent)
        req = leg.needs_native_agent
        self.assertEqual(req.model, "claude-sonnet-5")
        self.assertEqual(req.effort, "max")
        self.assertEqual(req.lens, "correctness")
        self.assertEqual(len(result.native_fill_requests), 1)

    def test_policy_seat_still_never_requests_a_native_fill(self):
        # The other half of the gate is load-bearing SECURITY, not a nicety: a
        # Fable/Opus seat is subscription-TUI only and must never be substituted by
        # a native agent, even though its deferral has the identical typed shape.
        _result, leg = self._run("claude-fable-5")
        self.assertEqual(leg.status, "UNAVAILABLE")
        self.assertEqual(leg.detail, "tui_adapter_required")
        self.assertIsNone(leg.needs_native_agent)


if __name__ == "__main__":
    unittest.main()
