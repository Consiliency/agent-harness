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

import unittest

from phase_loop_runtime.advisor_board import (
    DEFAULT_TARGET_SEATS,
    FLOOR_SEATS,
    LENS_CYCLE,
    compose_review_board,
    default_matrix,
    validate_board,
)

ALL_VENDORS = ("grok", "claude", "codex", "gemini")


def _probe(up):
    up = set(up)
    return lambda vendor: vendor in up


def _keys(board):
    """Dedup identity per seat = (vendor-lane, model, lens)."""
    return [(s.harness, s.model, s.lens) for s in board.seats]


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
        self.assertEqual({s.model for s in board.seats}, {"grok-4.5"})

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
        # A composed board is only useful if its seats are all VALID (grok-4.5 on the
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
        board = compose_review_board()
        self.assertLessEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        keys = _keys(board)
        self.assertEqual(len(keys), len(set(keys)))
        if board.seats:
            validate_board(board, default_matrix())

    def test_target_below_floor_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compose_review_board(is_available=_probe(ALL_VENDORS), target=2, floor=3)


if __name__ == "__main__":
    unittest.main()
