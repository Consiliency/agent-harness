"""President seam adapter (ah#736; PRESROUTE agent-harness#952): ladder rung -> one seat.

``panel_invoker.invoke_president`` is transport-agnostic: it walks
``PRESIDENT_LADDER`` calling ``invoke(rung, prompt) -> {"status", "code", "text"}``
and descends a rung ONLY on the typed ``{"status": "unavailable",
"code": "president_unavailable"}`` response. This module supplies that callable
for a real landing board:

* a rung names a seat by review alias (``sol``/``fable``/``grok``/``gemini`` via
  ``DEFAULT_REVIEW_SEAT_ALIASES``) or by exact model id; the rung is matched against
  the seats of the board that is landing, so no model id is spelled here
  (model-id-source guard). A rung with no seat on the board is a typed
  ``president_unavailable`` (descend).
* a SEATED rung runs through the HARDEN-authorized president operation
  ``public_board_president.v1`` (``president_operation``), never through the governed
  review operation: the review brief and its AGREE/DISAGREE completion grammar cannot
  carry a ``FORCING DECISION`` ruling, and borrowing them would launder a degraded leg
  into a ruling (EC-HARDEN-5). Before a rung launches, a president authorization is
  minted over the exact prompt and revalidated, as ``spawn`` revalidates the review
  authorization before it launches; the launch uses that authorization's route.

  - ``sol`` / ``grok`` / ``gemini``: the brokered provider route through
    ``panel_invoker._exec_leg`` (the single real-subprocess boundary), whose only
    process launch is ``panel_invoker.launch_provider``. The provider runs in a
    throwaway directory: no tree is staged and the live tree is never its cwd.
  - ``fable`` under Claude Code (decided from the PASSED ``base_env``): a deferred
    native fill -- ``{"status": "native_fill_deferred", "rung", "brief_digest",
    "findings_digest"}`` -- that ``invoke_board`` exposes as
    ``PanelResult.needs_native_president`` and resumes against; a second Claude TUI
    is never spawned. Refused with ``PRESIDENT_FILL_HEARTBEAT_REFUSED`` under
    ``heartbeat_only``, as a native leg fill is.
  - ``fable`` elsewhere: the brokered self-PTY Claude session
    (``panel_invoker._run_claude_tui_session``) with tools off and no directory grant.

  A launch that fails is a typed ``failed`` response (``invoke_president`` raises
  ``president_invocation_failed``): a broken route is a structural failure, not seat
  unavailability, so the ladder is not walked past it.

Every attempt is kept on ``PresidentInvoke.attempts`` so the runner can persist
the ladder walk beside the ruling (or beside the refusal).
"""
from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from . import panel_invoker
from .advisor_board import backing
from .advisor_board.schema import Board, Seat
from .panel_invoker import DEFAULT_REVIEW_SEAT_ALIASES, PresidentPolicyError
from .president_operation import (
    PRESIDENT_FILL_HEARTBEAT_REFUSED,
    brief_digest,
    findings_digest,
)

# Kept for callers that still name the pre-PRESROUTE refusal; a seated rung no longer
# returns it.
PRESIDENT_ROUTE_UNAVAILABLE = "president_execution_route_unavailable"
PRESIDENT_NATIVE_FILL_DEFERRED = "native_fill_deferred"

_PROMPT_PREFIX = panel_invoker._president_prompt(())
_REASK_SUFFIX = panel_invoker._president_prompt((), format_reask=True)[len(_PROMPT_PREFIX):]


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


def prompt_findings(prompt: str) -> str:
    """The ``"\\n".join(findings)`` a president prompt carries.

    ``_president_prompt`` is a constant prefix, the joined findings, and an optional
    constant re-ask suffix; stripping the two constants recovers the exact joined
    findings without splitting and re-joining them.
    """
    body = prompt[len(_PROMPT_PREFIX):] if prompt.startswith(_PROMPT_PREFIX) else prompt
    if _REASK_SUFFIX and body.endswith(_REASK_SUFFIX):
        body = body[: -len(_REASK_SUFFIX)]
    return body


@dataclass
class PresidentInvoke:
    """Callable ``(rung, prompt) -> response`` bound to one landing board."""

    board: Board
    repo_dir: Path | str | None = None
    stream_dir: Path | str | None = None
    base_env: Mapping[str, str] | None = None
    seat_aliases: Mapping[str, str] | None = None
    monitoring_policy: str = "bounded"
    attempts: list[PresidentAttempt] = field(default_factory=list)

    def _record(
        self, rung: str, seat: Seat | None, status: str, code: str | None, detail: str | None, chars: int = 0
    ) -> None:
        self.attempts.append(
            PresidentAttempt(
                rung,
                None if seat is None else seat.model,
                None if seat is None else seat.harness,
                status,
                code,
                detail,
                chars,
            )
        )

    def __call__(self, rung: str, prompt: str) -> Mapping[str, str]:
        seat = seat_for_rung(self.board, rung, seat_aliases=self.seat_aliases)
        if seat is None:
            detail = f"no seat on board {self.board.name!r} matches ladder rung {rung!r}"
            self._record(rung, None, "unavailable", "president_unavailable", detail)
            return {"status": "unavailable", "code": "president_unavailable", "detail": detail}
        harness = str(seat.harness or "").lower()
        if harness == "claude" and panel_invoker._under_claude_code(self.base_env):
            return self._native_fill(rung, seat, prompt)
        try:
            return self._launch(rung, seat, harness, prompt)
        except PresidentPolicyError:
            raise
        except Exception as exc:  # a broken route is a typed failure, never a descent
            detail = f"president {rung!r} route failed: {type(exc).__name__}: {exc}"
            self._record(rung, seat, "failed", "president_invocation_failed", detail)
            return {"status": "failed", "code": "president_invocation_failed", "detail": detail}

    def _native_fill(self, rung: str, seat: Seat, prompt: str) -> Mapping[str, str]:
        if self.monitoring_policy == "heartbeat_only":
            detail = "a native president fill cannot be bound under heartbeat_only monitoring"
            self._record(rung, seat, "refused", PRESIDENT_FILL_HEARTBEAT_REFUSED, detail)
            raise PresidentPolicyError(PRESIDENT_FILL_HEARTBEAT_REFUSED, detail)
        response = {
            "status": PRESIDENT_NATIVE_FILL_DEFERRED,
            "rung": rung,
            "brief_digest": brief_digest(prompt),
            "findings_digest": findings_digest((prompt_findings(prompt),)),
        }
        self._record(rung, seat, PRESIDENT_NATIVE_FILL_DEFERRED, None, "deferred to the driving Claude Code session")
        return response

    def _launch(self, rung: str, seat: Seat, harness: str, prompt: str) -> Mapping[str, str]:
        authorization = backing.prepare_president_isolation_authorization(
            self.board, prompt, canonical_repo_authority=self.repo_dir
        )
        backing.revalidate_president_isolation_authorization(
            authorization, self.board, prompt, canonical_repo_authority=self.repo_dir
        )
        routes = dict(authorization.routes)
        with tempfile.TemporaryDirectory(prefix="phase-loop-president-") as scratch:
            president_dir = Path(scratch) / "president"
            out_dir = Path(scratch) / "out"
            president_dir.mkdir()
            out_dir.mkdir()
            if harness == "claude":
                rc, text, log = self._launch_claude(seat, routes.get("claude"), prompt, out_dir)
            else:
                if harness not in routes:
                    raise ValueError(f"no authorized president route for {harness!r}")
                rc, text, log = panel_invoker._exec_leg(
                    harness,
                    president_dir,
                    out_dir,
                    None,
                    prompt,
                    "president",
                    routes[harness],
                    env=self.base_env,
                    broker_prompt=prompt,
                    broker_evidence={},
                )
        if rc != 0 or not (text or "").strip():
            detail = f"president {rung!r} ({harness}) returned rc={rc}: {(log or '')[-400:]}"
            self._record(rung, seat, "failed", "president_invocation_failed", detail)
            return {"status": "failed", "code": "president_invocation_failed", "detail": detail}
        self._record(rung, seat, "ok", None, None, len(text))
        return {"status": "ok", "text": text}

    def _launch_claude(
        self, seat: Seat, route_model: str | None, prompt: str, out_dir: Path
    ) -> tuple[int, str, str]:
        # The brokered self-PTY session: tools off, no directory grant, answer read from
        # the session transcript. Called directly (not through the review wrapper) so a
        # host without a supported, logged-in Claude still fails closed on the session
        # itself rather than before it.
        session_id = str(uuid.uuid4())
        cwd = out_dir.resolve()
        transcript = panel_invoker._claude_project_dir_for_cwd(str(cwd)) / f"{session_id}.jsonl"
        command = panel_invoker._broker_claude_tui_command(
            model=route_model or seat.model, effort=None, session_id=session_id
        )
        timeout_s = panel_invoker._leg_timeout_for(out_dir)
        backstop_s = max(1, int(timeout_s), panel_invoker._MAX_LEG_TIMEOUT_S)
        try:
            rc, text, log, _tail = panel_invoker._run_claude_tui_session(
                command=command,
                cwd=cwd,
                prompt=prompt,
                output_file=out_dir / "president-claude.txt",
                timeout_s=timeout_s,
                env=panel_invoker._broker_subscription_env(self.base_env),
                mode="president",
                backstop_s=backstop_s,
                stall_threshold_s=panel_invoker._broker_claude_stall_threshold(prompt, backstop_s),
                allow_transcript_final=True,
                broker_transcript_path=transcript,
            )
        finally:
            panel_invoker._cleanup_broker_claude_transcript(transcript, None)
        return rc, text, log


def build_president_invoke(
    board: Board,
    *,
    repo_dir: Path | str | None = None,
    stream_dir: Path | str | None = None,
    base_env: Mapping[str, str] | None = None,
    seat_aliases: Mapping[str, str] | None = None,
    monitoring_policy: str = "bounded",
) -> PresidentInvoke:
    return PresidentInvoke(
        board=board,
        repo_dir=repo_dir,
        stream_dir=stream_dir,
        base_env=base_env,
        seat_aliases=seat_aliases,
        monitoring_policy=monitoring_policy,
    )
