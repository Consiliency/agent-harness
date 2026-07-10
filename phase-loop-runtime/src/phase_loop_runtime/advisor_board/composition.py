"""Availability-aware board composition — the 4-vendor default review panel.

The ``code-review`` board's IDEAL shape is one seat per frontier vendor, each at
its MAX thinking and each carrying a DISTINCT review lens:

    grok    grok-4.5         max   lens=adversarial
    claude  claude-fable-5   max   lens=correctness
    codex   gpt-5.6-sol      max   lens=red-team
    gemini  Gemini 3.1 Pro   high  lens=alternative-approach   (high == its ceiling)

The load-bearing behavior is the **availability-aware fallback**: a panel must
NEVER collapse to one or two reviewers just because one or two vendors are down.
``compose_review_board`` detects the available vendors (via the advisor-board's
canonical PATH probe — ``registries.DEFAULT_HARNESS_REGISTRY.is_available``, the
SAME probe the matrix uses, so it is registration-driven and covers grok) and
composes a board of ``target`` independent seats (default 4, HARD FLOOR 3):

* one vendor-pure seat per available vendor first (its primary lens, max thinking);
* then BACKFILL the remaining seats onto the available vendors, round-robin, each
  with a DIFFERENT lens drawn from the lens cycle — so two available providers
  still yield a full 4-seat board, and ONE available provider yields 4
  distinct-lens seats on that provider.

With at least one vendor up the board ALWAYS reaches ``target`` (the lens cycle is
longer than the floor), so the floor is a structural safety net, never a cliff.
Seats are emitted in a deterministic order (fixed vendor order, then round-robin
backfill) so the composed board is snapshot-stable. No two seats ever share the
same ``(vendor, model, lens)`` — lens-uniqueness per vendor guarantees it.

Backfill stays on the vendor's own HOMEBREW lane (same model, same lane, next
lens) — never a breadth/omnigent lane that would skip-with-warning without a
gateway, which would defeat the point of keeping the reviewer count up.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from .registries import DEFAULT_HARNESS_REGISTRY
from .schema import Board, Seat

# Ideal per-vendor seat, in deterministic composition order. Each vendor runs at
# its MAX thinking (gemini's ceiling is ``high``) with a distinct primary lens.
_VENDOR_ORDER: tuple[str, ...] = ("grok", "claude", "codex", "gemini")
_VENDOR_SEAT: dict[str, dict[str, str]] = {
    "grok": {"model": "grok-4.5", "harness": "grok", "effort": "max", "lens": "adversarial"},
    "claude": {"model": "claude-fable-5", "harness": "claude", "effort": "max", "lens": "correctness"},
    "codex": {"model": "gpt-5.6-sol", "harness": "codex", "effort": "max", "lens": "red-team"},
    "gemini": {"model": "Gemini 3.1 Pro", "harness": "gemini", "effort": "high", "lens": "alternative-approach"},
}

# Distinct lenses the backfill cycles through (each vendor's primary lens is drawn
# from this set, so backfill naturally hands a vendor a lens it does not yet hold).
# Longer than the floor so a single available vendor can always fill to target with
# distinct lenses.
LENS_CYCLE: tuple[str, ...] = (
    "adversarial",
    "correctness",
    "red-team",
    "opposing-counsel",
    "conservative",
    "alternative-approach",
)

DEFAULT_TARGET_SEATS = 4
FLOOR_SEATS = 3


def _seat_for(vendor: str, lens: str) -> Seat:
    spec = _VENDOR_SEAT[vendor]
    return Seat(model=spec["model"], effort=spec["effort"], harness=spec["harness"], lens=lens)


def compose_review_board(
    *,
    is_available: Callable[[str], bool] | None = None,
    target: int = DEFAULT_TARGET_SEATS,
    floor: int = FLOOR_SEATS,
    name: str = "code-review",
    purpose: str = "code-review",
) -> Board:
    """Compose the availability-aware review board.

    ``is_available(vendor) -> bool`` decides which vendors are up; it defaults to
    the advisor-board's canonical PATH probe
    (``DEFAULT_HARNESS_REGISTRY.is_available``) so composition is registration-
    driven and grok is probed exactly like codex/gemini/claude. Inject it in tests
    to simulate 4/3/2/1 vendors up.

    Returns a ``Board`` of exactly ``target`` seats whenever ≥1 vendor is available
    (never fewer than ``floor``); an empty board only when NO vendor is available.
    """
    if target < floor:
        raise ValueError(f"target {target} is below the floor {floor}")
    probe = is_available if is_available is not None else DEFAULT_HARNESS_REGISTRY.is_available
    available = [v for v in _VENDOR_ORDER if probe(v)]
    if not available:
        # Nothing to compose — the caller's run degrades wholesale. (The floor is a
        # count of INDEPENDENT reviewers to seat on AVAILABLE vendors; with zero up
        # there is no reviewer to seat, so an empty board is the honest result.)
        return Board(name=name, purpose=purpose, seats=())

    seats: list[Seat] = []
    used_keys: set[tuple[str, str, str]] = set()
    used_lenses: dict[str, set[str]] = defaultdict(set)

    def _add(vendor: str, lens: str) -> bool:
        spec = _VENDOR_SEAT[vendor]
        key = (vendor, spec["model"], lens)
        if key in used_keys:
            return False
        seats.append(_seat_for(vendor, lens))
        used_keys.add(key)
        used_lenses[vendor].add(lens)
        return True

    # Phase 1 — one vendor-pure seat per available vendor (its primary lens).
    for vendor in available:
        _add(vendor, _VENDOR_SEAT[vendor]["lens"])

    # Phase 2 — backfill to target, round-robin across available vendors, each next
    # seat carrying the vendor's next UNUSED lens from the cycle. A vendor that has
    # exhausted the lens cycle is skipped; the loop stops if no vendor can add a new
    # distinct seat (unreachable with target ≤ len(LENS_CYCLE) and ≥1 vendor).
    rr = 0
    while len(seats) < target:
        progressed = False
        for _ in range(len(available)):
            vendor = available[rr % len(available)]
            rr += 1
            next_lens = next((l for l in LENS_CYCLE if l not in used_lenses[vendor]), None)
            if next_lens is not None and _add(vendor, next_lens):
                progressed = True
                break
        if not progressed:
            break  # every available vendor exhausted its lens cycle

    return Board(name=name, purpose=purpose, seats=tuple(seats))


__all__ = [
    "compose_review_board",
    "LENS_CYCLE",
    "DEFAULT_TARGET_SEATS",
    "FLOOR_SEATS",
]
