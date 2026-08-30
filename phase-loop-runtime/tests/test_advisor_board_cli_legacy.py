"""LEGACY (CLEANSHIP P7) — `phase-loop advisor-board <artifact>` is the RUNNABLE
agent-facing default for the 4-vendor board.

Pins that the CLI subcommand:
  - composes AVAILABILITY-AWARE via `compose_review_board` (REVIEWGOV IF-0-REVIEWGOV-1),
  - dispatches through `invoke_board` (NOT the legacy `invoke_panel`), staging the
    artifact by-reference, and
  - fails closed on a missing artifact / an empty (no authed vendor) board.

Hermetic: the real `compose_review_board` default shells out to `default_board_auth_ok`
(live auth probes), so the tests inject `is_available` (auth defaults to pass-through
per the documented test affordance) to build a real board without shelling out, and
patch `invoke_board` so no vendor CLI is spawned.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from harden_tdd_guard import (
    assert_exact_unavailable,
    harden_require,
    invoke_sanctioned_board_control,
)
from phase_loop_runtime import panel_invoker as pi_mod
from phase_loop_runtime.advisor_board import composition as comp_mod
from phase_loop_runtime.cli import main as cli_main
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult


# Bind the REAL composer at import time so the hermetic helper never re-enters the
# patched name (which would recurse infinitely under side_effect).
_REAL_COMPOSE = comp_mod.compose_review_board


def _hermetic_board(*_a, **_k):
    # Real composition, injected availability → auth pass-through (no live probe).
    return _REAL_COMPOSE(is_available=lambda v: v in {"codex", "gemini", "claude", "grok"})


# A realistic composed-board result: 4 seats, 3 usable OK verdicts + the claude leg
# deferring to a native Agent (UNAVAILABLE) — exactly the Claude-Code shape. Usable
# count 3 == FLOOR_SEATS, so this is a usable board (exit 0).
_CANNED = PanelResult(
    legs=(
        PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:adversarial"),
        PanelLegResult(leg="codex", status="OK", text="PARTIALLY AGREE", seat_key="codex:red-team"),
        PanelLegResult(leg="gemini", status="OK", text="AGREE", seat_key="gemini:alt"),
        PanelLegResult(leg="claude", status="UNAVAILABLE", text="", detail="deferred to native Agent", seat_key="claude:corr"),
    )
)


class AdvisorBoardCliTest(unittest.TestCase):
    def test_cli_composes_auth_aware_and_dispatches_board(self):
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            with unittest.mock.patch.object(
                comp_mod, "compose_review_board", side_effect=_hermetic_board
            ) as compose_spy, unittest.mock.patch.object(
                pi_mod, "invoke_board", return_value=_CANNED
            ) as invoke_spy:
                rc = cli_main(["advisor-board", str(artifact)])
            self.assertEqual(rc, 0)
            # The board path is the entry — availability-aware composition, then dispatch.
            # No-kwargs pin (Fable nit): the CLI must call compose_review_board with NO
            # arguments so it relies on the auth-aware production default
            # (auth_ok=default_board_auth_ok). Passing a predicate here would silently
            # opt into the PATH-only test-affordance. This guards that default.
            compose_spy.assert_called_once_with()
            invoke_spy.assert_called_once()
            # The artifact is staged BY REFERENCE (absolute path) into the board.
            _pos, kwargs = invoke_spy.call_args
            self.assertEqual(kwargs.get("artifact_ref"), str(artifact.resolve()))
            # Write boundary (item 5): the spawn cwd is constrained to a scratch dir,
            # not the process CWD.
            self.assertIsNotNone(kwargs.get("repo_dir"))
            self.assertNotEqual(Path(kwargs["repo_dir"]).resolve(), Path.cwd().resolve())
            # It dispatched the composed board (invoke_board's first positional).
            self.assertTrue(getattr(invoke_spy.call_args.args[0], "seats", None))

    def test_cli_harden_preflight_authorizes_before_compose_and_invoke(self):
        """The live entrypoint binds pre-composition and final review authority.

        Composition's availability/auth probes are executable capability effects, so
        the CLI needs a fresh preflight before invoking the no-kwargs production
        composer.  The final isolation authorization is intentionally minted only
        after the final composed board exists, and it must bind that exact board plus
        a canonical Git authority rather than the temporary provider scratch dir.
        """
        harden_require("review-leg-isolation")
        from phase_loop_runtime.advisor_board import backing as backing_mod

        events: list[str] = []
        precomposition_authority = object()
        final_authority = object()
        composed = _hermetic_board()
        canonical_repo = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], text=True
            ).strip()
        ).resolve()

        def prepare_composition(*_args, **_kwargs):
            events.append("precomposition_authorization")
            return precomposition_authority

        def compose():
            self.assertIn("precomposition_authorization", events)
            self.assertNotIn("final_authorization", events)
            events.append("compose")
            return composed

        def prepare_final(board, artifact, *, mode, canonical_repo_authority):
            self.assertIs(board, composed)
            self.assertEqual(artifact, "review me\n")
            self.assertEqual(mode, "review")
            self.assertEqual(Path(canonical_repo_authority).resolve(), canonical_repo)
            events.append("final_authorization")
            return final_authority

        def invoke(board, _artifact, **kwargs):
            self.assertIs(board, composed)
            self.assertIn("precomposition_authorization", events)
            self.assertIn("final_authorization", events)
            self.assertIs(kwargs.get("review_authorization"), final_authority)
            self.assertEqual(
                Path(kwargs["canonical_repo_authority"]).resolve(), canonical_repo
            )
            self.assertNotEqual(
                Path(kwargs["repo_dir"]).resolve(), canonical_repo
            )
            events.append("invoke")
            return _CANNED

        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            with unittest.mock.patch.object(
                backing_mod,
                "prepare_review_composition_authorization",
                side_effect=prepare_composition,
            ), unittest.mock.patch.object(
                backing_mod,
                "prepare_review_isolation_authorization",
                side_effect=prepare_final,
            ), unittest.mock.patch.object(
                comp_mod, "compose_review_board", side_effect=compose
            ) as compose_spy, unittest.mock.patch.object(
                pi_mod, "invoke_board", side_effect=invoke
            ) as invoke_spy:
                rc = cli_main(["advisor-board", str(artifact)])

        self.assertEqual(rc, 0)
        compose_spy.assert_called_once_with()
        invoke_spy.assert_called_once()
        self.assertLess(
            events.index("precomposition_authorization"), events.index("compose")
        )
        self.assertLess(events.index("compose"), events.index("final_authorization"))
        self.assertLess(events.index("final_authorization"), events.index("invoke"))

    def test_harden_real_invoker_revalidates_canonical_repository_authority(self):
        """A governed review validates canonical Git authority before a pure spawn.

        Supplying a review authorization makes this a governed review path: the real
        invoker must independently bind the canonical Git authority while retaining
        a distinct private ``repo_dir`` scratch.  A scratch substitution, another
        valid Git repository, or forged authorization must refuse before a callback
        can execute.  Every call deliberately omits ``mode`` so the check covers the
        derived ``code-review`` mode rather than only an explicit override.
        """
        harden_require("review-leg-isolation")
        from phase_loop_runtime.advisor_board import backing as backing_mod
        from phase_loop_runtime.advisor_board import matrix as matrix_mod
        from phase_loop_runtime.advisor_board.matrix import default_matrix
        from phase_loop_runtime.advisor_board.schema import Board, Seat

        canonical_repo = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], text=True
            ).strip()
        ).resolve()
        board = Board(
            name="harden-canonical-authority",
            purpose="code-review",
            seats=(
                Seat(
                    model=backing_mod.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["codex"],
                    effort="max",
                    harness="codex",
                ),
            ),
        )
        artifact = "bounded canonical-authority fixture\n"
        matrix = default_matrix(env={}, probe=lambda _vendor: True)

        def authorization():
            return backing_mod.prepare_review_isolation_authorization(
                board,
                artifact,
                mode="review",
                canonical_repo_authority=canonical_repo,
            )

        with tempfile.TemporaryDirectory() as td:
            scratch = Path(td) / "provider-scratch"
            scratch.mkdir()
            alternate_repo = Path(td) / "different-valid-git-repository"
            subprocess.run(["git", "init", "-q", str(alternate_repo)], check=True)
            self.assertNotEqual(alternate_repo.resolve(), canonical_repo)
            self.assertNotEqual(alternate_repo.resolve(), scratch.resolve())
            effects: list[str] = []
            revalidated_authorities: list[Path] = []
            real_revalidate = pi_mod.revalidate_review_isolation_authorization

            def revalidate(auth, review_board, review_artifact, **kwargs):
                if review_board == board:
                    self.assertEqual(review_artifact, artifact)
                    self.assertEqual(kwargs.get("mode"), "review")
                    canonical = Path(kwargs["canonical_repo_authority"]).resolve()
                    self.assertEqual(canonical, canonical_repo)
                    self.assertNotEqual(canonical, scratch.resolve())
                    revalidated_authorities.append(canonical)
                    effects.append("revalidated")
                return real_revalidate(auth, review_board, review_artifact, **kwargs)

            def hermetic_spawn(*_args, **_kwargs):
                self.assertTrue(revalidated_authorities)
                effects.append("spawn")
                return "OK", "bounded hermetic control\nAGREE"

            with unittest.mock.patch.object(
                pi_mod,
                "revalidate_review_isolation_authorization",
                side_effect=revalidate,
            ):
                result = invoke_sanctioned_board_control(
                    board,
                    artifact,
                    spawn=hermetic_spawn,
                    repo_dir=scratch,
                    base_env={},
                    matrix=matrix,
                    max_concurrency=1,
                )

            self.assertEqual([leg.status for leg in result.legs], ["OK"])
            self.assertEqual(effects[-1], "spawn")
            self.assertTrue(revalidated_authorities)

            raw_matrix_calls: list[object] = []
            raw_availability_calls: list[object] = []
            raw_writer_calls: list[object] = []
            raw_provider_calls: list[object] = []
            raw_child_calls: list[object] = []
            raw_completion_calls: list[object] = []
            raw_sink_calls: list[object] = []
            raw_leg_auth_calls: list[object] = []
            raw_claude_auth_calls: list[object] = []
            raw_claude_support_calls: list[object] = []
            original_default_matrix = pi_mod.default_matrix
            original_writer = pi_mod._write_incremental_verdict

            def raw_default_matrix(*args, **kwargs):
                raw_matrix_calls.append((args, kwargs))
                deterministic_kwargs = dict(kwargs)
                deterministic_kwargs["env"] = {}
                return original_default_matrix(*args, **deterministic_kwargs)

            def raw_live_availability(*args, **kwargs):
                raw_availability_calls.append((args, kwargs))
                return True

            def raw_writer(*args, **kwargs):
                raw_writer_calls.append((args, kwargs))
                return original_writer(*args, **kwargs)

            def raw_provider(*args, **kwargs):
                raw_provider_calls.append((args, kwargs))
                return "OK", "unexpected raw provider effect"

            def raw_child(*args, **kwargs):
                raw_child_calls.append((args, kwargs))
                return "OK", "unexpected raw child effect"

            def raw_leg_auth_ok(*args, **kwargs):
                raw_leg_auth_calls.append((args, kwargs))
                return True, ""

            def raw_claude_subscription_auth_ok(*args, **kwargs):
                raw_claude_auth_calls.append((args, kwargs))
                return True, ""

            def raw_claude_code_support_status(*args, **kwargs):
                raw_claude_support_calls.append((args, kwargs))
                return True, ""

            class RawRefusalSink:
                def emit(self, event) -> None:
                    raw_sink_calls.append(event)

            scratch_effects: list[str] = []

            def scratch_spawn(*_args, **_kwargs):
                scratch_effects.append("spawn")
                return "OK", "unexpected scratch authority\nAGREE"

            alternate_effects: list[str] = []

            def alternate_spawn(*_args, **_kwargs):
                alternate_effects.append("spawn")
                return "OK", "unexpected alternate repository authority\nAGREE"

            forged_effects: list[str] = []

            def forged_spawn(*_args, **_kwargs):
                forged_effects.append("spawn")
                return "OK", "unexpected forged authority\nAGREE"

            stream_dir = Path(td) / "raw-refusal-stream"
            with unittest.mock.patch.object(
                pi_mod,
                "default_matrix",
                side_effect=raw_default_matrix,
            ), unittest.mock.patch.object(
                matrix_mod.DEFAULT_HARNESS_REGISTRY,
                "is_available",
                side_effect=raw_live_availability,
            ), unittest.mock.patch.object(
                pi_mod,
                "_write_incremental_verdict",
                side_effect=raw_writer,
            ), unittest.mock.patch.object(
                pi_mod,
                "_default_spawn_via_provider",
                side_effect=raw_provider,
            ), unittest.mock.patch.object(
                pi_mod,
                "_default_spawn",
                side_effect=raw_child,
            ), unittest.mock.patch.object(
                pi_mod,
                "_leg_auth_ok",
                side_effect=raw_leg_auth_ok,
            ), unittest.mock.patch.object(
                pi_mod,
                "_claude_subscription_auth_ok",
                side_effect=raw_claude_subscription_auth_ok,
            ), unittest.mock.patch.object(
                pi_mod,
                "_claude_code_support_status",
                side_effect=raw_claude_code_support_status,
            ):
                scratch_result = pi_mod.invoke_board(
                    board,
                    artifact,
                    spawn=scratch_spawn,
                    repo_dir=scratch,
                    canonical_repo_authority=scratch,
                    review_authorization=authorization(),
                    base_env={},
                    max_concurrency=1,
                    on_leg_complete=raw_completion_calls.append,
                    sink=RawRefusalSink(),
                    stream_dir=stream_dir,
                )
                alternate_result = pi_mod.invoke_board(
                    board,
                    artifact,
                    spawn=alternate_spawn,
                    repo_dir=scratch,
                    canonical_repo_authority=alternate_repo,
                    review_authorization=authorization(),
                    base_env={},
                    max_concurrency=1,
                    on_leg_complete=raw_completion_calls.append,
                    sink=RawRefusalSink(),
                    stream_dir=stream_dir,
                )
                forged_result = pi_mod.invoke_board(
                    board,
                    artifact,
                    spawn=forged_spawn,
                    repo_dir=scratch,
                    canonical_repo_authority=canonical_repo,
                    review_authorization=object(),
                    base_env={},
                    max_concurrency=1,
                    on_leg_complete=raw_completion_calls.append,
                    sink=RawRefusalSink(),
                    stream_dir=stream_dir,
                )

            self.assertFalse(scratch_effects)
            self.assertFalse(alternate_effects)
            self.assertFalse(forged_effects)
            self.assertFalse(raw_matrix_calls)
            self.assertFalse(raw_availability_calls)
            self.assertFalse(raw_writer_calls)
            self.assertFalse(raw_provider_calls)
            self.assertFalse(raw_child_calls)
            self.assertFalse(raw_completion_calls)
            self.assertFalse(raw_sink_calls)
            self.assertFalse(raw_leg_auth_calls)
            self.assertFalse(raw_claude_auth_calls)
            self.assertFalse(raw_claude_support_calls)
            self.assertFalse(list(stream_dir.glob("*.verdict.json")))
            assert_exact_unavailable(board, scratch_result)
            assert_exact_unavailable(board, alternate_result)
            assert_exact_unavailable(board, forged_result)

    def test_compose_drops_unauthed_vendor_at_the_seam(self):
        # Item 1: the auth-aware seam the CLI uses drops an on-PATH-but-UNAUTHED vendor
        # at COMPOSE and backfills onto authed vendors (board stays 4 seats, all authed
        # families). Exercises compose_review_board(auth_ok=...) directly (hermetic).
        board = comp_mod.compose_review_board(
            is_available=lambda v: True,  # every vendor on PATH
            auth_ok=lambda v: v != "grok",  # ...but grok is NOT authenticated
        )
        families = {seat.harness for seat in board.seats}
        self.assertNotIn("grok", families, "an unauthed on-PATH vendor must be dropped at compose")
        self.assertEqual(len(board.seats), 4, "the freed seat must be backfilled to a full board")

    def test_cli_below_floor_board_exits_nonzero(self):
        # Item 4: a board with FEWER than FLOOR_SEATS (3) usable OK legs is below its
        # independence floor → nonzero exit (pins floor semantics, not just zero-usable):
        # here 2 OK + 2 failed = 2 usable < 3.
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("x\n")
            below_floor = PanelResult(
                legs=(
                    PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:adv"),
                    PanelLegResult(leg="codex", status="OK", text="DISAGREE", seat_key="codex:red"),
                    PanelLegResult(leg="gemini", status="DEGRADED", text="", detail="capped", seat_key="gemini:alt"),
                    PanelLegResult(leg="claude", status="UNAVAILABLE", text="", detail="deferred", seat_key="claude:corr"),
                )
            )
            with unittest.mock.patch.object(
                comp_mod, "compose_review_board", side_effect=_hermetic_board
            ), unittest.mock.patch.object(pi_mod, "invoke_board", return_value=below_floor):
                rc = cli_main(["advisor-board", str(artifact)])
            self.assertEqual(rc, 1, "usable legs below the floor → nonzero exit")

    def test_cli_json_emits_independence_and_legs(self):
        import json

        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            with unittest.mock.patch.object(
                comp_mod, "compose_review_board", side_effect=_hermetic_board
            ), unittest.mock.patch.object(pi_mod, "invoke_board", return_value=_CANNED):
                import contextlib
                import io

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = cli_main(["advisor-board", str(artifact), "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertIn("independence", payload)
            # 3 OK legs == FLOOR_SEATS → usable (the 4th, claude, defers UNAVAILABLE).
            self.assertTrue(payload["usable"])
            self.assertEqual(
                [leg["status"] for leg in payload["legs"]], ["OK", "OK", "OK", "UNAVAILABLE"]
            )
            # The reviewer's actual verdict TEXT must be preserved (CR codex, major):
            # a board whose output drops the verdicts cannot be reconciled.
            self.assertEqual(
                [leg["text"] for leg in payload["legs"]], ["AGREE", "PARTIALLY AGREE", "AGREE", ""]
            )

    def test_cli_human_output_includes_verdict_text(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            with unittest.mock.patch.object(
                comp_mod, "compose_review_board", side_effect=_hermetic_board
            ), unittest.mock.patch.object(pi_mod, "invoke_board", return_value=_CANNED):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = cli_main(["advisor-board", str(artifact)])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("AGREE", out)
            self.assertIn("PARTIALLY AGREE", out)

    def test_cli_missing_artifact_fails_closed(self):
        rc = cli_main(["advisor-board", "/no/such/artifact.md"])
        self.assertEqual(rc, 2)

    def test_cli_empty_board_fails_closed(self):
        # No vendor both available and authed → empty board → nothing to compose.
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("x\n")
            empty = _REAL_COMPOSE(is_available=lambda v: False)
            with unittest.mock.patch.object(
                comp_mod, "compose_review_board", return_value=empty
            ), unittest.mock.patch.object(pi_mod, "invoke_board") as invoke_spy:
                rc = cli_main(["advisor-board", str(artifact)])
            self.assertEqual(rc, 2)
            invoke_spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
