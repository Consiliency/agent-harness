"""President seam adapter (ah#736): ladder rung -> one landing-board seat.

``panel_invoker.invoke_president`` is transport-agnostic: it walks
``PRESIDENT_LADDER`` calling ``invoke(model, prompt) -> {"status", "code", "text"}``
and descends a rung ONLY on the typed ``{"status": "unavailable",
"code": "president_unavailable"}`` response. This module supplies that callable
for a real landing board:

* a rung names a seat by review alias (``fable``/``sol`` via
  ``DEFAULT_REVIEW_SEAT_ALIASES``) or by exact model id (``grok-4.6``,
  ``gemini-3.8-flash``); the rung is matched against the seats of the board that
  is landing, so no model id is spelled here (model-id-source guard). A rung with
  no seat on the board is a typed ``president_unavailable`` (descend).
* a seated rung has NO production execution route today, and the adapter says so
  instead of borrowing one. Post-HARDEN (EC-HARDEN-5) the only production
  execution operation is the governed review (``public_board_review.v1``): its
  brief and completion classifier are the frozen AGREE/PARTIALLY AGREE/DISAGREE
  grammar, ``invoke_board`` refuses ``advisory`` execution outside a sanctioned
  test seam (``harden_advisory_execution_refused``), and a president ruling ends
  with ``FORCING DECISION:``, which that classifier reads as an incomplete review.
  Running the ruling through the review operation would hand the seat two
  contradictory terminal grammars and launder a DEGRADED leg into a ruling.
  So a seated rung returns ``{"status": "failed", "code":
  "president_execution_route_unavailable"}``: ``invoke_president`` raises
  ``president_invocation_failed`` on the first seated rung (a missing operation is
  a structural failure, not seat unavailability, so the ladder is not walked),
  the board refuses with ``president_ruling_missing:president_invocation_failed``,
  and a president-requiring landing fails closed. A HARDEN-authorized president
  operation (its own mode, brief, completion grammar, and authorization
  identity) is the follow-up that replaces this branch.

Every attempt is kept on ``PresidentInvoke.attempts`` so the runner can persist
the ladder walk beside the ruling (or beside the refusal).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .advisor_board.schema import Board, Seat
from .panel_invoker import DEFAULT_REVIEW_SEAT_ALIASES

PRESIDENT_ROUTE_UNAVAILABLE = "president_execution_route_unavailable"


@dataclass(frozen=True)
class PresidentAttempt:
    rung: str
    seat_model: str | None
    leg: str | None
    status: str
    code: str | None
    detail: str | None
    chars: int

    def as_record(self) -> dict[str, object]:
        return {
            "rung": self.rung,
            "seat_model": self.seat_model,
            "leg": self.leg,
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
            "chars": self.chars,
        }


def seat_for_rung(
    board: Board,
    rung: str,
    *,
    seat_aliases: Mapping[str, str] | None = None,
) -> Seat | None:
    """First board seat whose review alias or exact model id equals ``rung``."""
    aliases = dict(DEFAULT_REVIEW_SEAT_ALIASES)
    aliases.update(seat_aliases or {})
    for seat in board.seats:
        if rung == seat.model or rung == aliases.get(seat.model):
            return seat
    return None


@dataclass
class PresidentInvoke:
    """Callable ``(rung, prompt) -> response`` bound to one landing board."""

    board: Board
    repo_dir: Path | str | None = None
    stream_dir: Path | str | None = None
    base_env: Mapping[str, str] | None = None
    seat_aliases: Mapping[str, str] | None = None
    attempts: list[PresidentAttempt] = field(default_factory=list)

    def __call__(self, rung: str, prompt: str) -> Mapping[str, str]:
        seat = seat_for_rung(self.board, rung, seat_aliases=self.seat_aliases)
        if seat is None:
            response = {
                "status": "unavailable",
                "code": "president_unavailable",
                "detail": f"no seat on board {self.board.name!r} matches ladder rung {rung!r}",
            }
            self.attempts.append(
                PresidentAttempt(
                    rung, None, None, "unavailable", "president_unavailable", response["detail"], 0
                )
            )
            return response
        # See the module docstring: no HARDEN-authorized president operation exists,
        # and the governed review operation's grammar cannot carry a ruling.
        response = {
            "status": "failed",
            "code": PRESIDENT_ROUTE_UNAVAILABLE,
            "detail": (
                f"seat {seat.model!r} ({seat.harness}) matches rung {rung!r} but no "
                "HARDEN-authorized president execution operation exists; the governed "
                "review operation cannot carry a FORCING DECISION ruling"
            ),
        }
        self.attempts.append(
            PresidentAttempt(
                rung, seat.model, seat.harness, "failed", PRESIDENT_ROUTE_UNAVAILABLE,
                response["detail"], 0,
            )
        )
        return response


def build_president_invoke(
    board: Board,
    *,
    repo_dir: Path | str | None = None,
    stream_dir: Path | str | None = None,
    base_env: Mapping[str, str] | None = None,
    seat_aliases: Mapping[str, str] | None = None,
) -> PresidentInvoke:
    return PresidentInvoke(
        board=board,
        repo_dir=repo_dir,
        stream_dir=stream_dir,
        base_env=base_env,
        seat_aliases=seat_aliases,
    )
