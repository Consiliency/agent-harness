"""REVIEWGOV IF-0-REVIEWGOV-2 — opt-in streaming verdict delivery on the SHARED
``_run_legs_ordered`` helper (which drives both ``invoke_panel`` and
``invoke_board``).

The load-bearing design point: streaming is strictly additive. When neither
``on_leg_complete`` nor ``review_dir`` is set, the consolidated return is the exact
historical submission-ordered result — so ``invoke_panel``'s byte-identical golden
is untouched. When opted in, each leg is delivered THE MOMENT IT LANDS (callback +
an incremental per-leg verdict file), while the consolidated return is still
re-sorted to submission order.

ONE shared out-of-order-completion fixture (``_out_of_order_fixture``) proves both
halves, so neither can pass trivially:

* The DEFAULT-path (golden) assertion runs UNDER a fixture whose legs COMPLETE in
  the reverse of submission order (``fast`` always lands before ``slow``, by a
  handshake — no sleeps, no wall-clock). If ``_run_legs_ordered`` returned
  completion order it would be ``[fast, slow]``; the golden asserts it is still the
  submission order ``[slow, fast]``. So the default path is proven order-preserving
  under genuine out-of-order completion, not merely when legs happen to finish in
  order.
* The STREAMING assertion uses the SAME fixture and asserts the fast leg's callback
  fires AND its verdict file is on disk BEFORE the slow leg finishes (no
  head-of-line blocking), while the consolidated return is still ``[slow, fast]``.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD


class _Leg:
    """A fake leg whose COMPLETION order is deterministic regardless of thread
    scheduling: the ``slow`` leg blocks until the ``fast`` leg signals it has run,
    so ``fast`` ALWAYS lands before ``slow`` — the reverse of submission order
    ``[slow, fast]``. No sleeps ⇒ no wall-clock flakiness."""

    def __init__(self, name: str, fast_done: threading.Event, *, is_fast: bool):
        self.name = name
        self._fast_done = fast_done
        self._is_fast = is_fast

    def __call__(self) -> pi.PanelLegResult:
        if self._is_fast:
            self._fast_done.set()
        else:
            if not self._fast_done.wait(timeout=5.0):  # slow cannot land before fast
                raise TimeoutError("fast leg never signalled — fixture deadlock")
        return pi.PanelLegResult(
            leg=self.name, status="OK", text=f"{self.name}\nAGREE", seat_key=self.name
        )


def _out_of_order_fixture():
    """Return ``(items, run_one)`` in SUBMISSION order ``[slow, fast]`` where ``fast``
    is guaranteed to COMPLETE before ``slow`` (a two-worker fan-out)."""
    fast_done = threading.Event()
    items = [_Leg("slow", fast_done, is_fast=False), _Leg("fast", fast_done, is_fast=True)]

    def run_one(item: "_Leg") -> pi.PanelLegResult:
        return item()

    return items, run_one


class SharedOutOfOrderFixtureTests(unittest.TestCase):
    def test_default_path_returns_submission_order_under_out_of_order_completion(self) -> None:
        # GOLDEN half: default path (no streaming params) — the byte-identical
        # historical behavior. ``fast`` lands first (by construction), yet the
        # consolidated result is submission order ``[slow, fast]``, so the ordered
        # contract survives genuine out-of-order completion (cannot pass trivially).
        items, run_one = _out_of_order_fixture()
        results = pi._run_legs_ordered(items, run_one)
        self.assertEqual([r.leg for r in results], ["slow", "fast"])

    def test_streaming_delivers_fast_leg_before_slow_finishes(self) -> None:
        # STREAMING half: SAME fixture. The fast leg's callback + verdict file must
        # land BEFORE the slow leg finishes, and the consolidated return is still
        # re-sorted to submission order.
        items, run_one = _out_of_order_fixture()
        landed: list[str] = []
        snap: dict[str, bool] = {}
        lock = threading.Lock()
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)

            def on_leg_complete(result: pi.PanelLegResult) -> None:
                with lock:
                    landed.append(result.leg)
                    if result.leg == "fast":
                        # fast's verdict file is already on disk (the helper writes
                        # BEFORE the callback), and slow's is NOT — slow is still
                        # in-flight. This IS "fast fires before slow finishes".
                        snap["fast_file_present"] = (review_dir / "leg-01-fast.verdict.json").exists()
                        snap["slow_file_absent"] = not (review_dir / "leg-00-slow.verdict.json").exists()

            results = pi._run_legs_ordered(
                items, run_one, on_leg_complete=on_leg_complete, review_dir=review_dir
            )

            # Callbacks fired in COMPLETION order (fast before slow), not submission.
            self.assertEqual(landed, ["fast", "slow"])
            # At fast's landing: its file present, slow's absent (no head-of-line block).
            self.assertTrue(snap.get("fast_file_present"))
            self.assertTrue(snap.get("slow_file_absent"))
            # Consolidated return re-sorted to SUBMISSION order.
            self.assertEqual([r.leg for r in results], ["slow", "fast"])
            # Incremental per-leg verdict files written for BOTH, index-prefixed.
            names = sorted(p.name for p in review_dir.glob("*.verdict.json"))
            self.assertEqual(names, ["leg-00-slow.verdict.json", "leg-01-fast.verdict.json"])
            payload = json.loads((review_dir / "leg-00-slow.verdict.json").read_text())
            self.assertEqual(payload["leg"], "slow")
            self.assertEqual(payload["status"], "OK")
            self.assertTrue(payload["usable"])


class StreamingFailOpenTests(unittest.TestCase):
    """The streaming side-channel is best-effort: a raising callback or an unwritable
    ``review_dir`` must NEVER break the pool or fail a leg — the consolidated ordered
    return is authoritative."""

    def test_raising_callback_never_breaks_the_pool(self) -> None:
        items, run_one = _out_of_order_fixture()

        def boom(_result: pi.PanelLegResult) -> None:
            raise RuntimeError("callback boom")

        results = pi._run_legs_ordered(items, run_one, on_leg_complete=boom)
        self.assertEqual([r.leg for r in results], ["slow", "fast"])  # full ordered results

    def test_unwritable_review_dir_is_fail_open(self) -> None:
        items, run_one = _out_of_order_fixture()
        with tempfile.NamedTemporaryFile() as f:
            bad = Path(f.name) / "sub"  # parent is a FILE → mkdir raises → swallowed
            results = pi._run_legs_ordered(items, run_one, review_dir=bad)
        self.assertEqual([r.leg for r in results], ["slow", "fast"])


class InvokeStreamingOptInTests(unittest.TestCase):
    """The public entry points thread the opt-in through to the shared helper; the
    default (no params) is unchanged (proven byte-identical by the advisor-board
    golden)."""

    def test_invoke_board_streams_when_opted_in(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            seen: list[str] = []
            lock = threading.Lock()

            def on_leg_complete(r: pi.PanelLegResult) -> None:
                with lock:
                    seen.append(r.leg)

            res = pi.invoke_board(
                DEFAULT_BOARD, "artifact",
                spawn=lambda leg, art: ("OK", f"{leg}\nAGREE"),
                on_leg_complete=on_leg_complete,
                stream_dir=d,
            )
            self.assertEqual(sorted(seen), sorted(r.leg for r in res.legs))
            self.assertEqual(
                len(list(Path(d).glob("*.verdict.json"))), len(res.legs)
            )
            # Consolidated return still in canonical seat order.
            self.assertEqual([r.leg for r in res.legs], list(pi.PANEL_LEGS))

    def test_invoke_panel_streams_when_opted_in(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            seen: list[str] = []
            lock = threading.Lock()

            def on_leg_complete(r: pi.PanelLegResult) -> None:
                with lock:
                    seen.append(r.leg)

            res = pi.invoke_panel(
                "artifact", pi.PANEL_LEGS,
                spawn=lambda leg, art: ("OK", f"{leg}\nAGREE"),
                on_leg_complete=on_leg_complete,
                stream_dir=d,
            )
            self.assertEqual(sorted(seen), sorted(pi.PANEL_LEGS))
            self.assertEqual(len(list(Path(d).glob("*.verdict.json"))), len(pi.PANEL_LEGS))
            self.assertEqual([r.leg for r in res.legs], list(pi.PANEL_LEGS))


if __name__ == "__main__":
    unittest.main()
