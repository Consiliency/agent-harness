"""Availability-aware 4-vendor board composition — the load-bearing behavior.

Proves the core requirement: a panel NEVER collapses to one or two reviewers just
because one or two vendors are down. For 4 / 3 / 2 / 1 available vendors the
composer produces a full ``target`` (=4) seats, never below the floor (=3), with
NO duplicate ``(vendor, model, lens)`` seat and lens diversity when backfilling.
The 1-vendor case yields 4 distinct-lens seats on that one vendor.

Availability is SIMULATED via an injected probe (``is_available``), the same seam
the live composer defaults to ``DEFAULT_HARNESS_REGISTRY.is_available`` — so these
tests exercise the exact fallback the runtime uses, without touching the network
or PATH.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harden_tdd_guard import harden_require
from phase_loop_runtime.advisor_board import (
    DEFAULT_TARGET_SEATS,
    FLOOR_SEATS,
    LENS_CYCLE,
    board_independence,
    compose_review_board,
    default_board_auth_ok,
    default_matrix,
    validate_board,
)
from phase_loop_runtime.advisor_board import composition as _composition

ALL_VENDORS = ("grok", "claude", "codex", "gemini")


def _probe(up):
    up = set(up)
    return lambda vendor: vendor in up


def _keys(board):
    """Dedup identity per seat = (vendor-lane, model, lens)."""
    return [(s.harness, s.model, s.lens) for s in board.seats]


def test_review_leg_isolation_refuses_unbound_direct_invocation():
    harden_require("review-leg-isolation")
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    from phase_loop_runtime.panel_invoker import invoke_board

    effects: list[object] = []

    def direct_effect(*args, **kwargs):
        effects.append((args, kwargs))
        return "OK", "unexpected direct provider effect"

    result = invoke_board(DEFAULT_BOARD, "review bundle", spawn=direct_effect, mode="review")
    assert not effects
    assert all(leg.status in {"DEGRADED", "UNAVAILABLE"} for leg in result.legs)


def test_derived_review_refuses_missing_or_forged_authority_before_callback():
    """A mode-omitted premerge board cannot spend either execution seam unbound."""

    harden_require("review-leg-isolation")
    import subprocess

    from phase_loop_runtime import panel_invoker as invoker
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    canonical_repo = Path(
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    ).resolve()
    callback_effects: list[str] = []

    def callback(*_args, **_kwargs):
        callback_effects.append("callback")
        return "OK", "unexpected unbound callback\nAGREE"

    with tempfile.TemporaryDirectory() as td:
        scratch = Path(td) / "private-scratch"
        scratch.mkdir()
        with patch.object(
            invoker,
            "_default_spawn_via_provider",
            side_effect=AssertionError("provider path ran before authorization"),
        ) as provider_spy:
            missing = invoker.invoke_board(
                DEFAULT_BOARD,
                "bounded derived-review fixture",
                spawn=callback,
                repo_dir=scratch,
                canonical_repo_authority=canonical_repo,
            )
            forged = invoker.invoke_board(
                DEFAULT_BOARD,
                "bounded derived-review fixture",
                spawn=callback,
                repo_dir=scratch,
                canonical_repo_authority=canonical_repo,
                review_authorization=object(),
            )

    provider_spy.assert_not_called()
    assert not callback_effects
    assert all(leg.status == "UNAVAILABLE" for leg in missing.legs)
    assert all(leg.status == "UNAVAILABLE" for leg in forged.legs)


class AvailabilitySimulationTests(unittest.TestCase):
    def _assert_full_and_clean(self, board, *, expect_vendors):
        # (a) exactly the target seat count …
        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        # (b) … which is never below the floor (target ≥ floor, and we hit target).
        self.assertGreaterEqual(len(board.seats), FLOOR_SEATS)
        # (c) NO duplicate (vendor, model, lens) seat.
        keys = _keys(board)
        self.assertEqual(len(keys), len(set(keys)), f"duplicate seat: {keys}")
        # every seat runs on an AVAILABLE vendor (never a down one).
        self.assertTrue(all(s.harness in expect_vendors for s in board.seats))
        # every lens on a given vendor is distinct (lens diversity on backfill).
        by_vendor: dict[str, list[str]] = {}
        for s in board.seats:
            by_vendor.setdefault(s.harness, []).append(s.lens)
        for vendor, lenses in by_vendor.items():
            self.assertEqual(len(lenses), len(set(lenses)), f"{vendor} repeats a lens: {lenses}")
            for lens in lenses:
                self.assertIn(lens, LENS_CYCLE)

    def test_four_vendors_up_one_pure_seat_each(self) -> None:
        board = compose_review_board(is_available=_probe(ALL_VENDORS))
        self._assert_full_and_clean(board, expect_vendors=set(ALL_VENDORS))
        # all four vendors seated, exactly once, distinct lenses.
        self.assertEqual({s.harness for s in board.seats}, set(ALL_VENDORS))
        self.assertEqual(len({s.lens for s in board.seats}), 4)

    def test_three_vendors_up_three_pure_plus_one_backfill(self) -> None:
        up = ("claude", "codex", "gemini")  # grok down
        board = compose_review_board(is_available=_probe(up))
        self._assert_full_and_clean(board, expect_vendors=set(up))
        self.assertNotIn("grok", {s.harness for s in board.seats})
        # one vendor carries 2 seats (the backfill), the rest carry 1 — total 4.
        counts = {v: sum(1 for s in board.seats if s.harness == v) for v in up}
        self.assertEqual(sorted(counts.values()), [1, 1, 2])

    def test_two_vendors_up_two_pure_plus_two_backfill(self) -> None:
        up = ("grok", "codex")  # claude + gemini down
        board = compose_review_board(is_available=_probe(up))
        self._assert_full_and_clean(board, expect_vendors=set(up))
        counts = {v: sum(1 for s in board.seats if s.harness == v) for v in up}
        self.assertEqual(sorted(counts.values()), [2, 2])  # backfilled evenly

    def test_one_vendor_up_yields_four_distinct_lens_seats(self) -> None:
        board = compose_review_board(is_available=_probe(("grok",)))
        self._assert_full_and_clean(board, expect_vendors={"grok"})
        # ALL four seats on the single available vendor, each a DIFFERENT lens.
        self.assertEqual({s.harness for s in board.seats}, {"grok"})
        self.assertEqual(len({s.lens for s in board.seats}), 4)
        self.assertEqual({s.model for s in board.seats}, {"grok-4.6"})

    def test_never_below_floor_for_any_nonempty_availability(self) -> None:
        # Exhaustively: every non-empty subset of vendors reaches the target and is
        # never below the floor — the panel can't be "choked" to 1–2 reviewers.
        from itertools import combinations

        for r in range(1, len(ALL_VENDORS) + 1):
            for up in combinations(ALL_VENDORS, r):
                board = compose_review_board(is_available=_probe(up))
                self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS, up)
                self.assertGreaterEqual(len(board.seats), FLOOR_SEATS, up)
                keys = _keys(board)
                self.assertEqual(len(keys), len(set(keys)), up)

    def test_zero_vendors_up_is_an_empty_board(self) -> None:
        # No vendor available ⇒ nothing to seat (the run degrades wholesale). The
        # floor is a count of reviewers to seat on AVAILABLE vendors; with none up
        # there is no reviewer to seat.
        board = compose_review_board(is_available=_probe(()))
        self.assertEqual(len(board.seats), 0)

    def test_composed_board_is_deterministic(self) -> None:
        a = compose_review_board(is_available=_probe(("grok", "codex")))
        b = compose_review_board(is_available=_probe(("grok", "codex")))
        self.assertEqual(_keys(a), _keys(b))

    def test_every_composed_board_passes_matrix_validation(self) -> None:
        # A composed board is only useful if its seats are all VALID (grok-4.6 on the
        # grok lane, gpt on codex, …) — validate each availability scenario.
        from itertools import combinations

        matrix = default_matrix()
        for r in range(1, len(ALL_VENDORS) + 1):
            for up in combinations(ALL_VENDORS, r):
                validate_board(compose_review_board(is_available=_probe(up)), matrix)

    def test_default_probe_is_the_registry_path_probe(self) -> None:
        # With no injected probe the composer uses the advisor-board's canonical PATH
        # probe (DEFAULT_HARNESS_REGISTRY.is_available), so composition is
        # registration-driven. We can't assert which vendors are on PATH here, but
        # the board must still be well-formed (≤ target, no dup, all seats valid).
        # Pin auth to pass-through so this exercises the PATH probe ONLY and never
        # shells out to the real, subprocess-backed auth gate (the auth dimension is
        # proven in AuthAwareCompositionTests).
        board = compose_review_board(auth_ok=lambda _v: True)
        self.assertLessEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        keys = _keys(board)
        self.assertEqual(len(keys), len(set(keys)))
        if board.seats:
            validate_board(board, default_matrix())

    def test_target_below_floor_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compose_review_board(is_available=_probe(ALL_VENDORS), target=2, floor=3)


class AuthAwareCompositionTests(unittest.TestCase):
    """REVIEWGOV-W1 / #151 — composition gates on ``is_available ∧ auth_ok``, so a
    PATH-present-but-UNAUTHENTICATED vendor is treated as down (dropped +
    backfilled), exactly like a PATH-absent one. This closes the hole where the
    board composed on PATH alone and seated a vendor whose leg would then
    fail-closed to DEGRADED."""

    def test_unauthed_grok_is_not_seated_and_is_backfilled(self) -> None:
        # grok's CLI is on PATH (available) but it is NOT authenticated. It must be
        # dropped and its seat backfilled onto an authed vendor — never seated to
        # then fail-closed.
        board = compose_review_board(
            is_available=_probe(ALL_VENDORS),          # all four CLIs present
            auth_ok=_probe(("claude", "codex", "gemini")),  # grok unauthed
        )
        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)     # still a full board
        self.assertNotIn("grok", {s.harness for s in board.seats})   # unauthed vendor dropped
        self.assertTrue(all(s.harness in {"claude", "codex", "gemini"} for s in board.seats))
        keys = _keys(board)
        self.assertEqual(len(keys), len(set(keys)))                  # no duplicate seat
        # exactly one authed vendor carries the backfilled 4th seat.
        counts = {v: sum(1 for s in board.seats if s.harness == v) for v in ("claude", "codex", "gemini")}
        self.assertEqual(sorted(counts.values()), [1, 1, 2])

    def test_all_authed_is_identical_to_availability_only(self) -> None:
        # With every available vendor authed, the auth gate is a no-op: the board is
        # byte-identical to the availability-only 4-vendor board.
        avail_only = compose_review_board(is_available=_probe(ALL_VENDORS))
        authed = compose_review_board(
            is_available=_probe(ALL_VENDORS), auth_ok=_probe(ALL_VENDORS)
        )
        self.assertEqual(_keys(avail_only), _keys(authed))

    def test_unavailable_and_unauthed_both_drop(self) -> None:
        # grok is DOWN (not on PATH) and codex is UP-but-UNAUTHED — both are treated
        # as down; the board backfills onto the two remaining authed-and-up vendors.
        board = compose_review_board(
            is_available=_probe(("claude", "codex", "gemini")),  # grok absent
            auth_ok=_probe(("claude", "gemini")),                # codex unauthed
        )
        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        self.assertEqual({s.harness for s in board.seats}, {"claude", "gemini"})

    def test_injected_availability_alone_defaults_auth_passthrough(self) -> None:
        # Documented test affordance: injecting availability WITHOUT auth_ok defaults
        # auth to pass-through (so a simulation caller never shells out). All four
        # available vendors are seated even though no real auth ran.
        board = compose_review_board(is_available=_probe(ALL_VENDORS))
        self.assertEqual({s.harness for s in board.seats}, set(ALL_VENDORS))

    def test_no_vendor_authed_is_an_empty_board(self) -> None:
        board = compose_review_board(
            is_available=_probe(ALL_VENDORS), auth_ok=_probe(())
        )
        self.assertEqual(len(board.seats), 0)

    def test_production_default_gates_on_both_availability_and_auth(self) -> None:
        # The bare production call (no injected probes) must gate on
        # is_available ∧ auth_ok. Patch BOTH seams — grok on PATH but unauthed — so
        # it is dropped + backfilled, with NO real subprocess auth probe.
        with patch.object(_composition.DEFAULT_HARNESS_REGISTRY, "is_available", lambda _v: True), \
                patch.object(_composition, "default_board_auth_ok", lambda v: v != "grok"):
            board = compose_review_board()
        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        self.assertNotIn("grok", {s.harness for s in board.seats})

    def test_harden_preflight_authorizes_before_every_capability_auth_ok(self) -> None:
        """The default composer uses one real, validated preflight before probes."""
        harden_require("review-leg-isolation")
        real_preflight = _composition.prepare_review_composition_authorization
        real_revalidate = _composition.revalidate_review_composition_authorization
        effects: list[tuple[str, str] | tuple[str]] = []
        prepared: list[object] = []
        validated: list[object] = []

        def preflight(*args, **kwargs):
            self.assertFalse(effects, "preflight itself must precede every probe")
            authorization = real_preflight(*args, **kwargs)
            self.assertIsNotNone(authorization)
            prepared.append(authorization)
            effects.append(("preflight",))
            return authorization

        def revalidate(authorization, *args, **kwargs):
            self.assertEqual(prepared, [authorization])
            self.assertFalse(
                any(kind in {"availability", "auth_session_provider"} for kind, *_ in effects)
            )
            result = real_revalidate(authorization, *args, **kwargs)
            validated.append(authorization)
            effects.append(("validated",))
            return result

        def available(vendor: str) -> bool:
            self.assertTrue(validated and validated[-1] is prepared[0])
            effects.append(("availability", vendor))
            return True

        def authenticated(vendor: str) -> bool:
            self.assertTrue(validated and validated[-1] is prepared[0])
            effects.append(("auth_session_provider", vendor))
            return True

        with patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=preflight,
        ), patch.object(
            _composition,
            "revalidate_review_composition_authorization",
            side_effect=revalidate,
        ), patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY, "is_available", available
        ), patch.object(_composition, "default_board_auth_ok", authenticated):
            board = compose_review_board()

        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        self.assertEqual(len(prepared), 1)
        self.assertTrue(validated)
        self.assertTrue(all(value is prepared[0] for value in validated))
        self.assertLess(
            next(i for i, effect in enumerate(effects) if effect[0] == "validated"),
            next(i for i, effect in enumerate(effects) if effect[0] == "availability"),
        )
        self.assertEqual(
            {entry[1] for entry in effects if entry[0] == "availability"},
            set(ALL_VENDORS),
        )
        self.assertEqual(
            {entry[1] for entry in effects if entry[0] == "auth_session_provider"},
            set(ALL_VENDORS),
        )

    def test_harden_preflight_denial_blocks_compose_before_every_probe(self) -> None:
        """A failed or forged composer preflight cannot reach a probe seam."""
        harden_require("review-leg-isolation")
        effects: list[tuple[str, str] | tuple[str]] = []

        def forbidden(kind: str):
            def probe(vendor: str) -> bool:
                effects.append((kind, vendor))
                self.fail(f"{kind} effect reached after failed HARDEN preflight")

            return probe

        def denied(*_args, **_kwargs):
            effects.append(("preflight_denied",))
            raise ValueError("denied HARDEN composition preflight")

        with patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=denied,
        ), patch.object(
            _composition,
            "revalidate_review_composition_authorization",
            side_effect=AssertionError("a denied preflight must not be revalidated"),
        ) as validate_spy, patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            forbidden("availability"),
        ), patch.object(
            _composition,
            "default_board_auth_ok",
            forbidden("auth_session_provider"),
        ):
            with self.assertRaisesRegex(ValueError, "denied HARDEN composition preflight"):
                compose_review_board()

        validate_spy.assert_not_called()
        self.assertEqual(effects, [("preflight_denied",)])

        effects.clear()

        def forged(*_args, **_kwargs):
            effects.append(("preflight_forged",))
            return object()

        with patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=forged,
        ), patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            forbidden("availability"),
        ), patch.object(
            _composition,
            "default_board_auth_ok",
            forbidden("auth_session_provider"),
        ):
            with self.assertRaises(ValueError):
                compose_review_board()

        self.assertEqual(effects, [("preflight_forged",)])

    def test_harden_preflight_covers_default_load_boards_probes(self) -> None:
        """``load_boards`` uses the same real, validated preflight boundary."""
        harden_require("review-leg-isolation")
        from phase_loop_runtime.advisor_board import config as config_mod

        real_preflight = _composition.prepare_review_composition_authorization
        real_revalidate = _composition.revalidate_review_composition_authorization
        effects: list[tuple[str, str] | tuple[str]] = []
        prepared: list[object] = []
        validated: list[object] = []

        def preflight(*args, **kwargs):
            self.assertFalse(effects, "preflight itself must precede every probe")
            authorization = real_preflight(*args, **kwargs)
            self.assertIsNotNone(authorization)
            prepared.append(authorization)
            effects.append(("preflight",))
            return authorization

        def revalidate(authorization, *args, **kwargs):
            self.assertEqual(prepared, [authorization])
            self.assertFalse(
                any(kind in {"availability", "auth_session_provider"} for kind, *_ in effects)
            )
            result = real_revalidate(authorization, *args, **kwargs)
            validated.append(authorization)
            effects.append(("validated",))
            return result

        def available(vendor: str) -> bool:
            self.assertTrue(validated and validated[-1] is prepared[0])
            effects.append(("availability", vendor))
            return True

        def authenticated(vendor: str) -> bool:
            self.assertTrue(validated and validated[-1] is prepared[0])
            effects.append(("auth_session_provider", vendor))
            return True

        with tempfile.TemporaryDirectory() as td, patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=preflight,
        ), patch.object(
            _composition,
            "revalidate_review_composition_authorization",
            side_effect=revalidate,
        ), patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY, "is_available", available
        ), patch.object(config_mod, "default_board_auth_ok", authenticated):
            loaded = config_mod.load_boards(
                path=Path(td) / "missing.toml", validate=False
            )

        self.assertIn("code-review", loaded.boards)
        self.assertEqual(len(prepared), 1)
        self.assertTrue(validated)
        self.assertTrue(all(value is prepared[0] for value in validated))
        self.assertLess(
            next(i for i, effect in enumerate(effects) if effect[0] == "validated"),
            next(i for i, effect in enumerate(effects) if effect[0] == "availability"),
        )
        self.assertTrue(any(kind == "availability" for kind, *_ in effects))
        self.assertTrue(any(kind == "auth_session_provider" for kind, *_ in effects))

    def test_harden_preflight_denial_blocks_load_boards_before_every_probe(self) -> None:
        """``load_boards`` fails closed before capability/auth/session effects."""
        harden_require("review-leg-isolation")
        from phase_loop_runtime.advisor_board import config as config_mod

        effects: list[tuple[str, str] | tuple[str]] = []

        def forbidden(kind: str):
            def probe(vendor: str) -> bool:
                effects.append((kind, vendor))
                self.fail(f"{kind} effect reached after failed HARDEN preflight")

            return probe

        def denied(*_args, **_kwargs):
            effects.append(("preflight_denied",))
            raise ValueError("denied HARDEN load_boards preflight")

        with tempfile.TemporaryDirectory() as td, patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=denied,
        ), patch.object(
            _composition,
            "revalidate_review_composition_authorization",
            side_effect=AssertionError("a denied preflight must not be revalidated"),
        ) as validate_spy, patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            forbidden("availability"),
        ), patch.object(
            config_mod,
            "default_board_auth_ok",
            forbidden("auth_session_provider"),
        ):
            with self.assertRaisesRegex(ValueError, "denied HARDEN load_boards preflight"):
                config_mod.load_boards(path=Path(td) / "missing.toml", validate=False)

        validate_spy.assert_not_called()
        self.assertEqual(effects, [("preflight_denied",)])

        effects.clear()

        def forged(*_args, **_kwargs):
            effects.append(("preflight_forged",))
            return object()

        with tempfile.TemporaryDirectory() as td, patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=forged,
        ), patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            forbidden("availability"),
        ), patch.object(
            config_mod,
            "default_board_auth_ok",
            forbidden("auth_session_provider"),
        ):
            with self.assertRaises(ValueError):
                config_mod.load_boards(path=Path(td) / "missing.toml", validate=False)

        self.assertEqual(effects, [("preflight_forged",)])

    def test_default_board_auth_ok_fails_closed_on_unknown_vendor(self) -> None:
        # An unregistered vendor (or any lookup/probe error) fails CLOSED — treated
        # as unauthed, never an optimistic pass.
        self.assertFalse(default_board_auth_ok("no-such-vendor"))


class BoardIndependenceReportingTests(unittest.TestCase):
    """The composed board must REPORT cross-vendor independence (independent vs
    degraded) so a governed gate (gp's degraded_independence) can fire on a
    backfilled panel instead of trusting it as cross-vendor — the unanimous
    4-vendor CR finding on #134."""

    def test_four_distinct_vendors_is_independent(self) -> None:
        ind = board_independence(compose_review_board(is_available=_probe(ALL_VENDORS)))
        self.assertEqual(ind.level, "independent")
        self.assertEqual(ind.distinct_vendors, 4)
        self.assertEqual(ind.seats, DEFAULT_TARGET_SEATS)

    def test_backfilled_boards_report_degraded(self) -> None:
        for up in (("grok", "claude"), ("grok",)):
            ind = board_independence(compose_review_board(is_available=_probe(up)))
            self.assertEqual(ind.seats, DEFAULT_TARGET_SEATS)   # never choked below target
            self.assertEqual(ind.level, "degraded")             # but honestly degraded
            self.assertEqual(ind.distinct_vendors, len(up))

    def test_no_vendors_is_none(self) -> None:
        ind = board_independence(compose_review_board(is_available=_probe(())))
        self.assertEqual(ind.level, "none")
        self.assertEqual(ind.seats, 0)


if __name__ == "__main__":
    unittest.main()
