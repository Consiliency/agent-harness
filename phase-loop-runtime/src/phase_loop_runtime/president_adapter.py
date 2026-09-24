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

import contextlib
import hashlib
import json
import subprocess
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

from . import gemini_heartbeat, panel_invoker
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
# agent-harness#1001: a cancelled operation stops the walk (no later rung launches).
PRESIDENT_OPERATION_CANCELLED = "president_operation_cancelled"

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
    # The configured rung order (``load_president_ladder``); ``None`` walks the
    # built-in ``PRESIDENT_LADDER``.
    ladder: tuple[str, ...] | None = None
    # agent-harness#1001: the operation's cancellation, and the invocation id its
    # heartbeat records are filed under.
    cancel_event: threading.Event | None = None
    invocation: str = field(default_factory=lambda: uuid.uuid4().hex)
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
        # A cancelled operation stops the walk on EVERY route, the native fill included.
        self._raise_if_cancelled(rung, seat)
        if harness == "claude" and panel_invoker._under_claude_code(self.base_env):
            return self._native_fill(rung, seat, prompt)
        try:
            response = self._launch(rung, seat, harness, prompt)
            if response.get("status") != "ok":
                # A launch the cancellation ended is a cancellation, not a rung failure.
                self._raise_if_cancelled(rung, seat)
            return response
        except PresidentPolicyError:
            raise
        except Exception as exc:  # a broken route is a typed failure, never a descent
            # A cancelled operation stops the whole walk: no later rung may launch.
            self._raise_if_cancelled(rung, seat)
            detail = f"president {rung!r} route failed: {type(exc).__name__}: {exc}"
            self._record(rung, seat, "failed", "president_invocation_failed", detail)
            return {"status": "failed", "code": "president_invocation_failed", "detail": detail}

    def _raise_if_cancelled(self, rung: str, seat: Seat) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            detail = "the president operation was cancelled"
            self._record(rung, seat, "cancelled", PRESIDENT_OPERATION_CANCELLED, detail)
            raise PresidentPolicyError(PRESIDENT_OPERATION_CANCELLED, detail)

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
            self.board, prompt, canonical_repo_authority=self.repo_dir,
            monitoring_policy=self.monitoring_policy,
        )
        try:
            backing.revalidate_president_isolation_authorization(
                authorization, self.board, prompt, canonical_repo_authority=self.repo_dir
            )
            routes = dict(authorization.routes)
            # Every launch -- the Claude self-PTY session included -- uses the route the
            # revalidated authorization carries, never a fallback to the seat's own model: a
            # seat the authorization did not route is refused without launching.
            if harness not in routes:
                raise ValueError(f"no authorized president route for {harness!r}")
            if self.monitoring_policy != "heartbeat_only" and _injected_president_seam():
                # The in-process control seam (a patched transport or launch site), under
                # BOUNDED monitoring only -- the frozen corpus's seam, with the same
                # identity rule as review seats (``_has_injected_review_execution_seam``).
                # Never evidence. ``heartbeat_only`` never takes this branch: its guarantee
                # (monitor, broker, egress) holds whatever the launch site is.
                with tempfile.TemporaryDirectory(prefix="phase-loop-president-") as scratch:
                    stage = Path(scratch) / "president"
                    out_dir = Path(scratch) / "out"
                    stage.mkdir()
                    out_dir.mkdir()
                    rc, text, log = self._transport(harness, routes[harness], prompt, stage, out_dir)
            else:
                rc, text, log = self._launch_brokered(
                    rung, harness, routes[harness], prompt, authorization
                )
        finally:
            backing.close_president_isolation_authorization(authorization)
        if rc != 0 or not (text or "").strip():
            detail = f"president {rung!r} ({harness}) returned rc={rc}: {(log or '')[-400:]}"
            self._record(rung, seat, "failed", "president_invocation_failed", detail)
            return {"status": "failed", "code": "president_invocation_failed", "detail": detail}
        self._record(rung, seat, "ok", None, None, len(text))
        return {"status": "ok", "text": text}

    def _transport(
        self,
        harness: str,
        route_model: str,
        prompt: str,
        stage: Path,
        out_dir: Path,
        *,
        monitor: "panel_invoker._ReviewMonitor | None" = None,
        latch: "panel_invoker._ProviderQuiescenceLatch | None" = None,
    ) -> tuple[int, str, str]:
        if harness == "claude":
            return self._launch_claude(route_model, prompt, out_dir, monitor=monitor, latch=latch)
        if harness == "gemini":
            return self._launch_gemini(route_model, prompt, out_dir, monitor=monitor, latch=latch)
        return panel_invoker._exec_leg(
            harness,
            stage,
            out_dir,
            None,
            prompt,
            "president",
            route_model,
            env=self.base_env,
            broker_prompt=prompt,
            broker_evidence={},
            **({"review_monitor": monitor} if monitor is not None else {}),
            **({"quiescence_latch": latch} if latch is not None else {}),
        )

    def _monitor(self, rung: str) -> "panel_invoker._ReviewMonitor":
        ladder = panel_invoker.effective_president_ladder(self)
        position = list(ladder).index(rung) if rung in ladder else 0
        root = (
            Path(self.stream_dir) if self.stream_dir is not None
            else Path(self.repo_dir or ".") / ".phase-loop" / "review-monitoring"
        )
        return panel_invoker._ReviewMonitor(
            root / "president-monitoring" / self.invocation / f"rung-{position}.json",
            self.invocation, position, self.cancel_event or threading.Event(),
        )

    def _launch_brokered(
        self,
        rung: str,
        harness: str,
        route_model: str,
        prompt: str,
        authorization: "backing.PresidentIsolationAuthorization",
    ) -> tuple[int, str, str]:
        """agent-harness#1001: a rung launch through the SAME isolation a review seat gets.

        Egress isolation (no retained capabilities), a single-use broker capability that
        carries the president operation, the ``ParentUnixBroker`` over read-only staged
        bytes, and -- under ``heartbeat_only`` -- a ``_ReviewMonitor`` (no model-thinking
        deadline, no silence kill; cancellation and owner loss are the only stops). Any
        missing piece refuses before a provider starts, with the real reason.
        """
        heartbeat = self.monitoring_policy == "heartbeat_only"
        if self.repo_dir is None or not authorization.canonical_repo_sha256:
            raise ValueError("president broker isolation requires a canonical repository")
        repo = Path(self.repo_dir).resolve()
        backing.activate_president_isolation_authorization(
            authorization, self.board, prompt, canonical_repo_authority=repo
        )
        deadline_s = None if heartbeat else panel_invoker._MAX_LEG_TIMEOUT_S
        with tempfile.TemporaryDirectory(prefix="phase-loop-president-") as scratch, \
                contextlib.ExitStack() as egress_stack:
            stage = Path(scratch) / "stage"
            out_dir = Path(scratch) / "out"
            stage.mkdir()
            out_dir.mkdir()
            for name, content in (
                ("review-bundle.md", prompt),
                ("review-instructions.md", _PRESIDENT_STAGE_INSTRUCTIONS),
            ):
                (stage / name).write_text(content, encoding="utf-8")
                (stage / name).chmod(0o400)
            egress_prefix = egress_stack.enter_context(panel_invoker._sandbox_egress.isolated_network(
                timeout_s=None if heartbeat else float(panel_invoker._LEG_TIMEOUT_MAX_S) + 300.0,
            ))
            if not egress_prefix:
                # Unconditional, unlike the review path's operator opt-out: this
                # authorization DECLARES child_network_egress=False, and a launch without a
                # filtered namespace would contradict it.
                raise panel_invoker._sandbox_egress.EgressUnavailable(
                    "egress isolation unavailable: the president launch requires a filtered namespace"
                )
            token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(tuple(egress_prefix))
            egress_stack.callback(panel_invoker._EGRESS_LAUNCH_PREFIX.reset, token)
            leg = backing.derive_president_leg_authorization(
                authorization, self.board, prompt, harness=harness, model=route_model,
                deadline_s=None if deadline_s is None else float(deadline_s),
                instructions_sha256=hashlib.sha256(
                    _PRESIDENT_STAGE_INSTRUCTIONS.encode("utf-8")
                ).hexdigest(),
                canonical_repo_authority=repo,
            )
            monitor = self._monitor(rung) if heartbeat else None
            if monitor is not None:
                monitor.record.update(
                    admission_expires_monotonic_ns=leg.expires_monotonic_ns,
                    authorization_expiry_scope="admission_only",
                )
                monitor.observe()
            broker = backing.ParentUnixBroker(
                leg, harness=harness, model=route_model, staged_dir=stage, canonical_repo=repo,
            )
            outcome: dict[str, object] = {}
            try:
                latch = panel_invoker._ProviderQuiescenceLatch()

                def infer() -> tuple[str, str]:
                    rc, text, log = self._transport(
                        harness, route_model, prompt, stage, out_dir, monitor=monitor, latch=latch,
                    )
                    outcome.update(rc=rc, log=log)
                    return ("OK" if rc == 0 and (text or "").strip() else "ERROR"), text

                adapter = backing._make_broker_inference_adapter(infer, latch.cancel, latch.is_quiescent)
                cancel = monitor.cancel if monitor is not None else self.cancel_event
                response, _probe = broker.run_credentialless_client(
                    adapter, deadline_s=None if deadline_s is None else float(deadline_s),
                    **({"cancel_event": cancel} if cancel is not None else {}),
                )
                latch.raise_if_set()
            finally:
                broker.close()
        if response is None:
            return 1, "", "president broker completed without a response"
        rc = int(outcome.get("rc", 1)) if response["status"] == "OK" else (int(outcome.get("rc", 1)) or 1)
        return rc, str(response["text"]), str(outcome.get("log", ""))

    def _launch_gemini(
        self,
        route_model: str,
        prompt: str,
        out_dir: Path,
        *,
        monitor: "panel_invoker._ReviewMonitor | None" = None,
        latch: "panel_invoker._ProviderQuiescenceLatch | None" = None,
    ) -> tuple[int, str, str]:
        # The brokered agy transport with the PRESIDENT's own final instruction (the
        # review transport asks for "the complete review and its required terminal
        # verdict"), launched only through ``_run_leg_with_liveness`` ->
        # ``launch_provider`` and decoded by the same acknowledged-stream reader.
        protocol = _president_gemini_stream_protocol(prompt)
        deadline_s = panel_invoker._MAX_LEG_TIMEOUT_S
        command = panel_invoker._brokered_gemini_command(
            model=route_model, deadline_s=deadline_s, staged_tree=None,
            monitoring_policy="heartbeat_only" if monitor is not None else "bounded",
        )
        subscription_env = panel_invoker._broker_subscription_env(self.base_env)
        if monitor is not None:
            # agent-harness#1001: the heartbeat route is the review seat's -- an owned agy
            # profile under the monitor, no print timeout, no silence kill.
            gemini_heartbeat.require_capability(subscription_env)
            with gemini_heartbeat.owned_profile(
                subscription_env, settings_bytes=panel_invoker._broker_agy_settings_bytes(),
                credential_path=Path(subscription_env.get("HOME", str(Path.home())))
                / ".gemini/antigravity-cli/antigravity-oauth-token",
            ) as profile:
                proc = panel_invoker._run_leg_with_liveness(
                    [profile.executable, *command[1:]], cwd=out_dir, env=profile.env,
                    deadline_s=deadline_s, input_text=protocol.transport,
                    quiescence_latch=latch, review_monitor=monitor, gemini_profile=profile,
                )
        else:
            with _president_agy_environment(subscription_env) as env:
                try:
                    proc = panel_invoker._run_leg_with_liveness(
                        command, cwd=out_dir, env=env, deadline_s=deadline_s,
                        input_text=protocol.transport,
                        **({"quiescence_latch": latch} if latch is not None else {}),
                    )
                except subprocess.TimeoutExpired:
                    return 124, "", "Gemini president deadline exceeded"
        if proc.returncode != 0:
            return proc.returncode, "", proc.stderr or ""
        rc, text, detail, _metadata = panel_invoker._broker_gemini_stream_result(
            proc.stdout or "", protocol
        )
        return rc, text, detail or proc.stderr or ""

    def _launch_claude(
        self,
        route_model: str,
        prompt: str,
        out_dir: Path,
        *,
        monitor: "panel_invoker._ReviewMonitor | None" = None,
        latch: "panel_invoker._ProviderQuiescenceLatch | None" = None,
    ) -> tuple[int, str, str]:
        # The brokered self-PTY session: tools off, no directory grant, answer read from
        # the session transcript. Called directly (not through the review wrapper) so a
        # host without a supported, logged-in Claude still fails closed on the session
        # itself rather than before it.
        session_id = str(uuid.uuid4())
        cwd = out_dir.resolve()
        transcript = panel_invoker._claude_project_dir_for_cwd(str(cwd)) / f"{session_id}.jsonl"
        command = panel_invoker._broker_claude_tui_command(
            model=route_model, effort=None, session_id=session_id
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
                **({"review_monitor": monitor} if monitor is not None else {}),
                # The broker's stop path reaches the Claude process through the latch,
                # exactly as for the review TUI seat.
                **({"quiescence_latch": latch} if latch is not None else {}),
            )
        finally:
            panel_invoker._cleanup_broker_claude_transcript(transcript, None)
        return rc, text, log


# The staged instructions a brokered president rung binds (the prompt itself is the
# staged bundle): a fixed marker, so the broker's stage digest identifies the operation.
_PRESIDENT_STAGE_INSTRUCTIONS = "public_board_president.v1: rule on every finding in the staged brief.\n"

def _injected_president_seam() -> bool:
    """True for the in-process control seam: a patched transport or launch site.

    Nothing real can launch through it, so the broker is not constructed; like the
    review seam, it is never evidence of a brokered execution.
    """
    return (
        panel_invoker._has_injected_review_execution_seam()
        or panel_invoker.launch_provider is not panel_invoker._PRODUCTION_LAUNCH_PROVIDER
    )


_PRESIDENT_GEMINI_FINAL_INSTRUCTION = (
    "Rule on every finding in that complete input: one line per finding, exactly "
    "`FINDING <id>: BLOCKING|DEFERRED — <reason>`, then end with `FORCING DECISION: <decision>`; "
    "do not mention truncation."
)


def _president_gemini_stream_protocol(prompt: str):
    """The brokered agy ingestion transcript with the president's final instruction.

    Chunking, per-chunk acknowledgements and sealing are the broker's own; only the
    final synthesis event is the president's (it asks for a ruling, not a review
    verdict).
    """
    protocol = panel_invoker._broker_gemini_stream_protocol(prompt)
    events = protocol.transport.rstrip("\n").split("\n")
    final = json.loads(events[-1])
    lines = final["message"]["content"].split("\n")
    lines[-1] = _PRESIDENT_GEMINI_FINAL_INSTRUCTION
    final["message"]["content"] = "\n".join(lines)
    final_event = json.dumps(final, separators=(",", ":"), ensure_ascii=False)
    events[-1] = final_event
    return replace(
        protocol,
        transport="\n".join(events) + "\n",
        final_event_sha256=hashlib.sha256(final_event.encode("utf-8")).hexdigest(),
    )


@contextmanager
def _president_agy_environment(env: Mapping[str, str]):
    """The broker's agy profile when the subscription credential exists; otherwise an
    empty private HOME with no credential of any kind, so the launch still goes through
    the single launch site and the provider itself refuses (fail-closed, recorded)."""
    profile = panel_invoker._brokered_agy_environment(env, None)
    try:
        agy_env = profile.__enter__()  # raises ValueError when no credential reference exists
    except ValueError:
        profile = None
    if profile is not None:
        try:
            yield agy_env
        finally:
            profile.__exit__(None, None, None)
        return
    with tempfile.TemporaryDirectory(prefix="phase-loop-president-agy-") as empty_home:
        # Same fixed deny-all action profile the broker profile carries, so an agy that
        # runs at all under the credential-less HOME still cannot act.
        config_dir = Path(empty_home) / ".gemini" / "antigravity-cli"
        config_dir.mkdir(parents=True, mode=0o700)
        settings_path = config_dir / "settings.json"
        settings_path.write_bytes(panel_invoker._broker_agy_settings_bytes())
        settings_path.chmod(0o400)
        bare = dict(env)
        bare["HOME"] = empty_home
        bare["XDG_CONFIG_HOME"] = str(Path(empty_home) / ".config")
        yield bare


def build_president_invoke(
    board: Board,
    *,
    repo_dir: Path | str | None = None,
    stream_dir: Path | str | None = None,
    base_env: Mapping[str, str] | None = None,
    seat_aliases: Mapping[str, str] | None = None,
    monitoring_policy: str = "bounded",
    ladder: Sequence[str] | None = None,
    cancel_event: threading.Event | None = None,
) -> PresidentInvoke:
    from .panel_invoker import validate_president_ladder

    return PresidentInvoke(
        board=board,
        repo_dir=repo_dir,
        stream_dir=stream_dir,
        base_env=base_env,
        seat_aliases=seat_aliases,
        monitoring_policy=monitoring_policy,
        ladder=None if ladder is None else validate_president_ladder(ladder),
        cancel_event=cancel_event,
    )
