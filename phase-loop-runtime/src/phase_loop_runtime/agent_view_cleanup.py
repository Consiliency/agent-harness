"""Stop a finished Claude Agent View background session once its closeout is verified.

A `claude --bg` session that reaches `done` is not stopped by Claude Code: its Remote Control
(bridge) session stays open in the app until `claude stop <id>`, and only that clean shutdown
archives it. The phase-loop launch route waits for `done` and reads the final message but never
stopped the session, so every finished executor run stayed in the app's session panel until it
was archived by hand. Measured on Ubuntu 26.04 (Claude Code 2.1.289): the session reached `done`
with no archive; `claude stop <id>` logged `Archive ... status=200` and kept the conversation.

The rule (maintainer, 2026-10-06): never archive before the harness has verified that the
session produced its required output. The verifier is the closeout's schema verification with
the required data: the BAML parse plus the `PhaseLoopCloseoutV1` validators, which the runner
reports as a `native_closeout_payload` and nothing else produces. A session whose closeout is
missing, malformed, or not evaluated (a BAML worker outage) is left running and visible so it can
be inspected. `stop` keeps the conversation (`claude attach <id>` and `--resume` still work);
`remove` is never used.

Never raises: cleanup is a tidy-up and must not change a run's outcome.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Mapping

from .claude_agent_view import ClaudeAgentViewAdapter

#: Set to a true value to leave finished sessions running (for debugging a run in the app).
KEEP_ENV = "PHASE_LOOP_KEEP_AGENT_VIEW_SESSIONS"
_LOG = logging.getLogger(__name__)
_SESSION_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{2,63}")
_PLACEHOLDER_IDS = frozenset({"preflight", "unknown", "none"})
_TRUE = frozenset({"1", "true", "yes", "on"})


def verified_session_id(result: Any, child_automation: Mapping[str, Any] | None) -> tuple[str | None, str]:
    """``(session_id, reason)``: the id to stop, or ``None`` and the reason it is not eligible.

    Eligible only when the launch was an Agent View route that finished ``done`` AND the
    closeout it produced passed schema verification with the required data."""
    if getattr(result, "dry_run", False):
        return None, "dry_run"
    if getattr(result, "claude_route", None) != "claude_agent_view":
        return None, "not_agent_view"
    route = getattr(result, "claude_route_result", None)
    if not isinstance(route, dict):
        return None, "no_route_result"
    if route.get("status") != "done":
        return None, "route_not_done"
    session_id = route.get("session_id")
    if not isinstance(session_id, str) or session_id in _PLACEHOLDER_IDS or not _SESSION_ID.fullmatch(session_id):
        return None, "no_session_id"
    lifecycles = [a for a in route.get("artifacts") or ()
                  if isinstance(a, dict) and a.get("kind") == "claude_agent_view_lifecycle"]
    if not lifecycles or lifecycles[0].get("state") != "done" or lifecycles[0].get("session_id") != session_id:
        return None, "lifecycle_not_done"
    automation = child_automation or {}
    if automation.get("baml_worker_outage"):
        return None, "closeout_not_evaluated"
    if automation.get("automation_parse_error") or automation.get("native_closeout_extraction_failure"):
        return None, "closeout_not_verified"
    payload = automation.get("native_closeout_payload")
    if not isinstance(payload, dict) or not payload:
        return None, "closeout_not_verified"
    return session_id, "verified"


def stop_verified_session(
    result: Any,
    child_automation: Mapping[str, Any] | None,
    *,
    cwd: str | Path | None = None,
    adapter: ClaudeAgentViewAdapter | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Stop the launch's Agent View session if (and only if) its closeout was verified.

    Returns ``{"session_id", "action", "reason"}``; ``action`` is ``stopped``, ``kept`` or
    ``stop_failed``. Never raises."""
    try:
        session_id, reason = verified_session_id(result, child_automation)
        if session_id is None:
            return {"session_id": None, "action": "kept", "reason": reason}
        env = os.environ if environ is None else environ
        if str(env.get(KEEP_ENV, "")).strip().lower() in _TRUE:
            return {"session_id": session_id, "action": "kept", "reason": "kept_by_environment"}
        stopped = (adapter if adapter is not None else ClaudeAgentViewAdapter()).stop(session_id, cwd=cwd)
        if getattr(stopped, "stop_result", None) != "stopped":
            _LOG.warning("agent-view session %s verified but `claude stop` did not stop it", session_id)
            return {"session_id": session_id, "action": "stop_failed", "reason": "stop_command_failed"}
        return {"session_id": session_id, "action": "stopped", "reason": "verified"}
    except Exception as exc:  # cleanup never changes a run's outcome
        _LOG.warning("agent-view session cleanup failed (%s)", type(exc).__name__)
        return {"session_id": None, "action": "stop_failed", "reason": type(exc).__name__}
