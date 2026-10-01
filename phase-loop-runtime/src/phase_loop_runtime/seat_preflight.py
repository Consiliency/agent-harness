"""Board-level seat preflight for pointer briefs (agent-harness#1204).

A *pointer brief* tells the reviewers to open files in the staged exact-head tree instead
of carrying their content inline. The caller declares it (``invoke_board(pointer_brief=True)``,
``advisor-board --pointer-brief``); nothing here guesses it from the brief's text.

Before ANY seat launches, :func:`pointer_brief_preflight` decides for every seat whether its
route gives it file access to the staged tree. A seat without file access gets the typed
notice :data:`POINTER_BRIEF_UNREADABLE`, which is published before launch. The seat still
runs (maintainer ruling, policy (ii)), but its verdict is **not source-grounded**: it never
counts as a passing grounded seat. :func:`counts_as_grounded_vote` is the landing rule and
:func:`uncounted_president_items` the president-input rule. Both mirror the existing D1 rule
for uncounted legs (``agy_qualification``): a non-blocking verdict is not counted, while a
blocking ``DISAGREE`` is kept as a review, so marking a seat never removes an objection.

This module decides policy only. It launches nothing and never changes a seat's route; the
route facts are passed in by the invoker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

POINTER_BRIEF_UNREADABLE = "seat_pointer_brief_unreadable"

#: The notice's rendered text: (what happens, why, how to fix it). Literals only.
NOTICE_TEXT: Mapping[str, tuple[str, str, str]] = {
    POINTER_BRIEF_UNREADABLE: (
        "seat runs, but its verdict is not counted as source-grounded",
        "the brief points at files in the staged tree and this seat's route gives it no "
        "file access",
        "inline the referenced content into the review bundle, or fill this seat through "
        "a route with file access (e.g. native fill)"),
}

#: The file a stream directory receives before the first seat launches.
PREFLIGHT_FILE = "seat-preflight.json"
PREFLIGHT_SCHEMA = "seat_preflight.v1"


@dataclass(frozen=True)
class SeatPreflightNotice:
    code: str
    seat_key: str
    leg: str
    #: The seat's position on the board. Seat keys are labels, not identities (two
    #: identical seats share one), so a notice is attached by position.
    position: int = -1

    def __post_init__(self) -> None:
        if self.code not in NOTICE_TEXT:
            raise ValueError(f"unknown seat preflight notice {self.code!r}")

    @property
    def what(self) -> str:
        return NOTICE_TEXT[self.code][0]

    @property
    def why(self) -> str:
        return NOTICE_TEXT[self.code][1]

    @property
    def fix(self) -> str:
        return NOTICE_TEXT[self.code][2]

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "seat_key": self.seat_key, "leg": self.leg,
                "what": self.what, "why": self.why, "fix": self.fix}

    def render(self) -> str:
        return f"seat {self.seat_key} ({self.leg}): {self.code}: {self.what} -- {self.why}; fix: {self.fix}"


def seat_has_file_access(leg: str, *, staged_tree: bool, brokered: bool,
                         native_fill: bool, sandbox_usable_by: Callable[..., bool]) -> bool:
    """Does this seat's route let it open files in the staged tree?

    A seat deferred to a native fill is reviewed by the host agent, which has file access.
    Otherwise it needs a staged tree AND a route that can act on it
    (``sandbox_usable_by``, the invoker's own capability rule)."""
    if native_fill:
        return True
    return staged_tree and bool(sandbox_usable_by(leg, brokered=brokered))


def pointer_brief_preflight(
    seats: Iterable[object], *, staged_tree: bool,
    brokered: Callable[[str], bool], native_fill: Callable[[object, str], bool],
    sandbox_usable_by: Callable[..., bool],
) -> tuple[SeatPreflightNotice, ...]:
    """One notice per seat that cannot open the pointer brief's files, in seat order."""
    notices = []
    for position, seat in enumerate(seats):
        leg = (getattr(seat, "harness", None) or "").lower()
        if not seat_has_file_access(leg, staged_tree=staged_tree, brokered=brokered(leg),
                                    native_fill=native_fill(seat, leg),
                                    sandbox_usable_by=sandbox_usable_by):
            notices.append(SeatPreflightNotice(POINTER_BRIEF_UNREADABLE,
                                               str(getattr(seat, "seat_key", "") or leg), leg,
                                               position))
    return tuple(notices)


def write_preflight_record(stream_dir: Path, notices: Sequence[SeatPreflightNotice]) -> Path:
    """Publish the notices to the stream directory before any seat launches."""
    Path(stream_dir).mkdir(parents=True, exist_ok=True)
    path = Path(stream_dir) / PREFLIGHT_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"schema": PREFLIGHT_SCHEMA, "pointer_brief": True,
                               "notices": [n.as_json() for n in notices]},
                              indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


# --------------------------------------------------------------------------------------
# Policy (ii): a marked seat is not source-grounded and never counts as a passing seat.
# --------------------------------------------------------------------------------------

def leg_record_marks(leg: object) -> dict[str, list[str]]:
    """What a persisted leg record carries so a resume restores the marks (inside the
    record's digest). Empty -- the record is byte-identical -- for an unmarked leg."""
    codes = [n.code for n in leg_notices(leg)]
    return {"seat_preflight": codes} if codes else {}


def notices_from_record(item: Mapping[str, object], position: int
                        ) -> tuple[SeatPreflightNotice, ...]:
    """The marks a persisted leg record carries. Raises ``ValueError`` when malformed."""
    if "seat_preflight" not in item:
        return ()
    codes = item["seat_preflight"]
    if not isinstance(codes, list) or not codes or not all(isinstance(c, str) for c in codes):
        raise ValueError("malformed seat_preflight marks in a persisted leg record")
    return tuple(SeatPreflightNotice(code, str(item.get("seat_key") or item.get("leg") or ""),
                                     str(item.get("leg") or ""), position) for code in codes)


def leg_notices(leg: object) -> tuple[SeatPreflightNotice, ...]:
    return tuple(getattr(leg, "_seat_preflight_notices", ()) or ())


def source_grounded(leg: object) -> bool:
    """False only for a leg the preflight marked (its seat could not open the brief's files)."""
    return not any(n.code == POINTER_BRIEF_UNREADABLE for n in leg_notices(leg))


def grounded_usable_legs(panel: object) -> tuple[object, ...]:
    """The usable legs a reviewer floor may count: usable AND source-grounded."""
    return tuple(leg for leg in getattr(panel, "usable_legs", ()) if source_grounded(leg))


def counts_as_grounded_vote(leg: object, counts_toward_landing: Callable[[object], bool]) -> bool:
    """The landing rule: the existing D1 rule AND the leg is source-grounded."""
    return counts_toward_landing(leg) and source_grounded(leg)


def uncounted_president_items(leg: object, terminal_verdict: Callable[[str], str | None]
                              ) -> list[str] | None:
    """The president's input for a usable leg that is NOT source-grounded: one synthetic item,
    so it can never stand as a seat's review. ``None`` (the builder's own rule) for every
    other leg, and for a blocking ``DISAGREE``, which is kept as its findings."""
    if not getattr(leg, "usable", False) or source_grounded(leg):
        return None
    if terminal_verdict(getattr(leg, "text", "")) == "DISAGREE":
        return None
    return [f"not counted (not source-grounded: {POINTER_BRIEF_UNREADABLE})"]
