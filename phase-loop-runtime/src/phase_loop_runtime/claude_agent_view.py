from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


AGENT_VIEW_STATES = {"running", "done", "blocked", "stopped", "failed", "unknown"}
AGENT_VIEW_POLL_INTERVAL_S = 5.0
# Consecutive polls on which the OBSERVER fails (listing error, or the bound record
# absent) before the wait fails closed. This bounds a broken observer, never a
# working session: a listed, running session resets the count.
AGENT_VIEW_OBSERVER_FAILURE_LIMIT = 12
SECRET_LIKE_KEYS = {
    "api_key",
    "authorization",
    "content",
    "data",
    "env",
    "environment",
    "key",
    "log",
    "logs",
    "payload",
    "private_key",
    "provider_payload",
    "raw",
    "secret",
    "stderr",
    "stdout",
    "text",
    "token",
}


@dataclass(frozen=True)
class BlockerSummary:
    reason: str
    summary: str

    def to_json(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AgentViewSession:
    id: str | None
    session_id: str | None
    cwd: str | None
    kind: str | None
    state: str
    status: str | None
    name: str | None
    started_at: str | None
    completed_at: str | None
    pid: int | None
    metadata: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int | None
    output: str = ""
    blocker: BlockerSummary | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.blocker is None

    def to_json(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "returncode": self.returncode,
            "output": self.output,
            "blocker": self.blocker.to_json() if self.blocker else None,
        }


@dataclass(frozen=True)
class AgentViewLifecycleResult:
    session_id: str
    state: str
    cwd: str | None
    logs_ref: str | None
    started_at: str | None
    completed_at: str | None
    stop_result: str | None
    auth_posture: str = "unknown"
    billing_posture: str = "unknown"
    blocker: BlockerSummary | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "cwd": self.cwd,
            "logs_ref": self.logs_ref,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stop_result": self.stop_result,
            "auth_posture": self.auth_posture,
            "billing_posture": self.billing_posture,
        }


@dataclass(frozen=True)
class AgentViewListResult:
    command: tuple[str, ...]
    sessions: tuple[AgentViewSession, ...]
    returncode: int | None
    blocker: BlockerSummary | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.blocker is None

    def to_json(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "sessions": [session.to_json() for session in self.sessions],
            "returncode": self.returncode,
            "blocker": self.blocker.to_json() if self.blocker else None,
        }


@dataclass(frozen=True)
class LaunchPreflightResult:
    trusted: bool
    trust_state: dict[str, str]
    command: tuple[str, ...]
    blocker: BlockerSummary | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "trusted": self.trusted,
            "trust_state": dict(self.trust_state),
            "command": list(self.command),
            "blocker": self.blocker.to_json() if self.blocker else None,
        }


class ClaudeAgentViewAdapter:
    def __init__(
        self,
        *,
        claude_bin: str = "claude",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.claude_bin = claude_bin
        self._runner = runner

    def list_command(self) -> list[str]:
        return [self.claude_bin, "agents", "--json", "--all"]

    def launch_command(
        self,
        prompt: str | None,
        *,
        cwd: str | Path | None = None,
        model: str | None = None,
        effort: str | None = None,
        permission: str | None = None,
        name: str | None = None,
        plugin_dirs: list[str | Path] | None = None,
        settings: str | Path | None = None,
        mcp_config: str | Path | None = None,
        add_dirs: list[str | Path] | None = None,
        safe_mode: bool = False,
        strict_mcp_config: bool = False,
        tools: str | list[str] | None = None,
        allowed_tools: str | None = None,
        disallowed_tools: str | None = None,
    ) -> list[str]:
        # `cwd` is the launch directory the caller runs this command from. The root
        # `claude` command has no `--cwd` option (only `claude agents` does), and an
        # unknown option fails the launch, so it is never rendered here.
        command = [self.claude_bin, "--bg"]
        if safe_mode:
            command.append("--safe-mode")
        if name:
            command.extend(["--name", name])
        if model:
            command.extend(["--model", model])
        if effort:
            command.extend(["--effort", effort])
        if permission:
            command.extend(["--permission-mode", permission])
        for plugin_dir in plugin_dirs or []:
            command.extend(["--plugin-dir", str(plugin_dir)])
        if settings is not None:
            command.extend(["--settings", str(settings)])
        if strict_mcp_config:
            command.append("--strict-mcp-config")
        if mcp_config is not None:
            command.extend(["--mcp-config", str(mcp_config)])
        for add_dir in add_dirs or []:
            command.extend(["--add-dir", str(add_dir)])
        if tools is not None:
            command.append("--tools")
            if isinstance(tools, str):
                command.append(tools)
            else:
                command.extend(tools)
        if allowed_tools:
            command.extend(["--allowedTools", allowed_tools])
        if disallowed_tools:
            command.extend(["--disallowedTools", disallowed_tools])
        if prompt is not None:
            # `--tools`, `--allowedTools`, `--disallowedTools` and `--add-dir` are
            # variadic (`<values...>`): without the end-of-options marker they swallow
            # the prompt and `claude --bg` starts with none (agent-harness#1099 proof).
            command.extend(["--", prompt])
        return command

    def logs_command(self, agent_id: str) -> list[str]:
        return [self.claude_bin, "logs", _validated_agent_id(agent_id)]

    def attach_command(self, agent_id: str) -> list[str]:
        return [self.claude_bin, "attach", _validated_agent_id(agent_id)]

    def stop_command(self, agent_id: str) -> list[str]:
        return [self.claude_bin, "stop", _validated_agent_id(agent_id)]

    def remove_command(self, agent_id: str) -> list[str]:
        return [self.claude_bin, "rm", _validated_agent_id(agent_id)]

    def list_sessions(self, *, cwd: str | Path | None = None) -> AgentViewListResult:
        command = self.list_command()
        result = self._runner(
            command,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            return AgentViewListResult(
                command=tuple(command),
                sessions=(),
                returncode=result.returncode,
                blocker=BlockerSummary("agents_list_failed", "claude agents did not return a successful session list."),
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return AgentViewListResult(
                command=tuple(command),
                sessions=(),
                returncode=result.returncode,
                blocker=BlockerSummary("agents_list_non_json", "claude agents returned non-JSON output."),
            )
        records = payload.get("agents") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            return AgentViewListResult(
                command=tuple(command),
                sessions=(),
                returncode=result.returncode,
                blocker=BlockerSummary("agents_list_unexpected_shape", "claude agents JSON did not contain a session array."),
            )
        sessions = tuple(_session_from_payload(record) for record in records if isinstance(record, dict))
        return AgentViewListResult(command=tuple(command), sessions=sessions, returncode=result.returncode)

    def prepare_launch(self, prompt: str, *, cwd: str | Path, **kwargs: Any) -> LaunchPreflightResult:
        command = tuple(self.launch_command(prompt, cwd=cwd, **kwargs))
        trust_state = workspace_trust_state(Path(cwd))
        if trust_state["status"] != "trusted":
            return LaunchPreflightResult(
                trusted=False,
                trust_state=trust_state,
                command=command,
                blocker=BlockerSummary("trust_preflight_blocked", "Agent View launch blocked before claude --bg because workspace or MCP trust is not ready."),
            )
        if shutil.which(self.claude_bin) is None:
            return LaunchPreflightResult(
                trusted=False,
                trust_state=trust_state,
                command=command,
                blocker=BlockerSummary("missing_claude_cli", "Agent View launch blocked because the Claude CLI is not available."),
            )
        support = self._runner(
            [self.claude_bin, "--bg", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if support.returncode != 0:
            return LaunchPreflightResult(
                trusted=False,
                trust_state=trust_state,
                command=command,
                blocker=BlockerSummary("unsupported_launch", "Agent View launch blocked because claude --bg is not supported by this Claude CLI."),
            )
        return LaunchPreflightResult(trusted=True, trust_state=trust_state, command=command)

    def launch_background(self, prompt: str, *, cwd: str | Path, **kwargs: Any) -> AgentViewLifecycleResult:
        bind_printed_id = bool(kwargs.pop("bind_printed_id", False))
        preflight = self.prepare_launch(prompt, cwd=cwd, **kwargs)
        if not preflight.trusted:
            return AgentViewLifecycleResult(
                session_id="preflight",
                state="blocked",
                cwd=str(cwd),
                logs_ref=None,
                started_at=None,
                completed_at=_utc_now(),
                stop_result=None,
                blocker=preflight.blocker,
            )
        result = self._runner(
            list(preflight.command),
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            return AgentViewLifecycleResult(
                session_id="launch",
                state="blocked",
                cwd=str(cwd),
                logs_ref=None,
                started_at=None,
                completed_at=_utc_now(),
                stop_result=None,
                blocker=BlockerSummary(
                    "agent_view_launch_failed",
                    "claude --bg did not launch a background session." + _cli_refusal_suffix(result.stdout),
                ),
            )

        session_id = _launch_session_id(result.stdout)
        if bind_printed_id:
            # Exact binding only (agent-harness#409): the session is the one this launch
            # printed, never another session that happens to share the cwd. The record
            # may not be listed yet; the waiter binds it by the printed id.
            if not session_id:
                return _lifecycle_from_parts(
                    session_id="launch",
                    state="blocked",
                    cwd=str(cwd),
                    started_at=None,
                    completed_at=_utc_now(),
                    stop_result=None,
                    blocker=BlockerSummary(
                        "agent_view_session_unbound",
                        "claude --bg did not print the id of the session it started.",
                    ),
                )
            session = _find_bound_session(self.list_sessions(cwd=cwd).sessions, session_id)
            if session:
                return _lifecycle_from_session(session)
            return _lifecycle_from_parts(
                session_id=session_id,
                state="running",
                cwd=str(cwd),
                started_at=_utc_now(),
                completed_at=None,
                stop_result=None,
            )
        session = _find_session(self.list_sessions(cwd=cwd).sessions, session_id=session_id, cwd=str(cwd))
        if session:
            return _lifecycle_from_session(session)
        return _lifecycle_from_parts(
            session_id=session_id or "unknown",
            state="running",
            cwd=str(cwd),
            started_at=_utc_now(),
            completed_at=None,
            stop_result=None,
        )

    def wait_for_terminal(
        self,
        session_id: str,
        *,
        cwd: str | Path | None = None,
        poll_interval_s: float = AGENT_VIEW_POLL_INTERVAL_S,
        timeout_s: float | None = None,
        on_poll: Callable[[AgentViewSession | None], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> AgentViewLifecycleResult:
        """Poll the exact session until Agent View reports a terminal state.

        `done`, `failed` and `stopped` are terminal; `blocked` means the session is
        waiting for input, which nothing unattended can supply, so it returns too and
        the session is left attachable. A running session is never timed out on
        silence: `timeout_s` applies only when the caller passes one, and it is None
        by default. Only the OBSERVER failing (the listing failing, or the record
        never appearing) for AGENT_VIEW_OBSERVER_FAILURE_LIMIT consecutive polls ends
        the wait, fail-closed.
        """
        started = clock()
        failures = 0
        last_blocker: BlockerSummary | None = None
        while True:
            listed = self.list_sessions(cwd=None)
            session = _find_bound_session(listed.sessions, session_id) if listed.ok else None
            if on_poll is not None:
                on_poll(session)
            if session is not None:
                failures = 0
                if session.state in {"done", "failed", "stopped", "blocked"}:
                    return _lifecycle_from_session(session)
            else:
                failures += 1
                last_blocker = listed.blocker or BlockerSummary(
                    "agent_view_session_missing", "claude agents did not list the launched background session."
                )
                if failures >= AGENT_VIEW_OBSERVER_FAILURE_LIMIT:
                    return _lifecycle_from_parts(
                        session_id=session_id,
                        state="blocked",
                        cwd=str(cwd) if cwd is not None else None,
                        started_at=None,
                        completed_at=_utc_now(),
                        stop_result=None,
                        blocker=last_blocker,
                    )
            if timeout_s is not None and clock() - started >= timeout_s:
                return _lifecycle_from_parts(
                    session_id=session.session_id or session.id or session_id if session else session_id,
                    state="unknown",
                    cwd=str(cwd) if cwd is not None else None,
                    started_at=session.started_at if session else None,
                    completed_at=None,
                    stop_result=None,
                    blocker=BlockerSummary(
                        "agent_view_launch_timeout",
                        f"Agent View session did not finish within the configured launch timeout ({timeout_s:g}s).",
                    ),
                )
            sleep(poll_interval_s)

    def final_text(self, session_id: str, *, cwd: str | Path) -> str:
        """The session's final assistant message from its local transcript, or "".

        Uses the same fail-closed final-turn reader as the brokered Claude seats
        (agent-harness#1002/#1077), so an ambiguous transcript yields "" rather than
        a guessed answer.
        """
        from .panel_invoker import _claude_project_dir_for_cwd, _final_assistant_text_from_jsonl

        path = session_transcript_path(session_id, cwd=cwd, project_dir_for_cwd=_claude_project_dir_for_cwd)
        if path is None:
            return ""
        return _final_assistant_text_from_jsonl(path)

    def inspect(self, agent_id: str, *, cwd: str | Path | None = None) -> AgentViewLifecycleResult:
        agent_id = _validated_agent_id(agent_id)
        listed = self.list_sessions(cwd=cwd)
        if not listed.ok:
            return _lifecycle_from_parts(
                session_id=agent_id,
                state="blocked",
                cwd=str(cwd) if cwd is not None else None,
                started_at=None,
                completed_at=_utc_now(),
                stop_result=None,
                blocker=listed.blocker,
            )
        session = _find_session(listed.sessions, session_id=agent_id, cwd=str(cwd) if cwd is not None else None)
        if session:
            return _lifecycle_from_session(session)
        return _lifecycle_from_parts(
            session_id=agent_id,
            state="stale",
            cwd=str(cwd) if cwd is not None else None,
            started_at=None,
            completed_at=None,
            stop_result=None,
            blocker=BlockerSummary("agent_view_session_missing", "claude agents did not list the requested background session."),
        )

    def logs(self, agent_id: str, *, cwd: str | Path | None = None) -> CommandResult:
        command = self.logs_command(agent_id)
        result = self._runner(
            command,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        blocker = None
        if result.returncode != 0:
            blocker = BlockerSummary("logs_command_failed", "claude logs did not return human-readable session text.")
        return CommandResult(command=tuple(command), returncode=result.returncode, output=result.stdout, blocker=blocker)

    def attach(self, agent_id: str, *, cwd: str | Path | None = None) -> CommandResult:
        command = self.attach_command(agent_id)
        result = self._runner(
            command,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        blocker = None
        if result.returncode != 0:
            blocker = BlockerSummary("attach_command_failed", "claude attach did not attach to the background session.")
        return CommandResult(command=tuple(command), returncode=result.returncode, output="", blocker=blocker)

    def stop(self, agent_id: str, *, cwd: str | Path | None = None) -> AgentViewLifecycleResult:
        command = self.stop_command(agent_id)
        result = self._runner(
            command,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            return _lifecycle_from_parts(
                session_id=_validated_agent_id(agent_id),
                state="blocked",
                cwd=str(cwd) if cwd is not None else None,
                started_at=None,
                completed_at=_utc_now(),
                stop_result="failed",
                blocker=BlockerSummary("stop_command_failed", "claude stop did not stop the background session."),
            )
        inspected = self.inspect(agent_id, cwd=cwd)
        return _lifecycle_from_parts(
            session_id=inspected.session_id,
            state="stopped" if inspected.state in {"stale", "unknown"} else inspected.state,
            cwd=inspected.cwd,
            started_at=inspected.started_at,
            completed_at=inspected.completed_at or _utc_now(),
            stop_result="stopped",
            auth_posture=inspected.auth_posture,
            billing_posture=inspected.billing_posture,
        )

    def remove(self, agent_id: str, *, cwd: str | Path | None = None) -> CommandResult:
        command = self.remove_command(agent_id)
        result = self._runner(
            command,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        blocker = None
        if result.returncode != 0:
            blocker = BlockerSummary("remove_refused", "claude rm refused to remove the session record.")
        return CommandResult(command=tuple(command), returncode=result.returncode, output="", blocker=blocker)


def workspace_trust_state(cwd: Path) -> dict[str, str]:
    mcp_path = cwd / ".mcp.json"
    mcp_status = "absent"
    if mcp_path.exists():
        try:
            payload = json.loads(mcp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"status": "blocked", "workspace": "trusted", "mcp": "invalid_json"}
        rendered = json.dumps(payload, sort_keys=True)
        if "pmcp" in rendered and "pending" in rendered.lower():
            return {"status": "blocked", "workspace": "trusted", "mcp": "pmcp_pending_approval"}
        mcp_status = "present"
    return {"status": "trusted", "workspace": "trusted", "mcp": mcp_status}


def _session_from_payload(payload: dict[str, Any]) -> AgentViewSession:
    state = _agent_state(payload.get("state") or payload.get("status"))
    return AgentViewSession(
        id=_optional_str(payload.get("id") or payload.get("agent_id")),
        session_id=_optional_str(payload.get("session_id") or payload.get("sessionId")),
        cwd=_optional_str(payload.get("cwd") or payload.get("workspace")),
        kind=_optional_str(payload.get("kind") or payload.get("type")),
        state=state,
        status=_optional_str(payload.get("status")),
        name=_optional_str(payload.get("name")),
        started_at=_optional_str(payload.get("started_at") or payload.get("startedAt")),
        completed_at=_optional_str(payload.get("completed_at") or payload.get("completedAt") or payload.get("finished_at") or payload.get("finishedAt")),
        pid=_optional_int(payload.get("pid")),
        metadata=_metadata_only(payload),
    )


def _agent_state(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"running", "started", "starting", "active", "working"}:
        return "running"
    if normalized in {"done", "complete", "completed", "success", "succeeded", "finished"}:
        return "done"
    if normalized in {"blocked", "waiting", "needs_input", "permission_required"}:
        return "blocked"
    if normalized in {"stopped", "cancelled", "canceled", "terminated", "killed"}:
        return "stopped"
    if normalized in {"failed", "failure", "error", "errored", "crashed"}:
        return "failed"
    return "unknown"


def _metadata_only(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if _secret_like_key(key):
                continue
            clean[str(key)] = _metadata_only(item)
        return clean
    if isinstance(value, list):
        return [_metadata_only(item) for item in value if isinstance(item, (dict, list, str, int, float, bool)) or item is None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)


def _secret_like_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in SECRET_LIKE_KEYS for part in re.split(r"[^a-z0-9_]+", normalized)) or normalized in SECRET_LIKE_KEYS


def _validated_agent_id(agent_id: str) -> str:
    if not isinstance(agent_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]+", agent_id):
        raise ValueError("agent id must contain only stable CLI identifier characters")
    return agent_id


def _lifecycle_from_session(session: AgentViewSession) -> AgentViewLifecycleResult:
    session_id = session.session_id or session.id or "unknown"
    failed = session.state == "failed"
    return _lifecycle_from_parts(
        session_id=session_id,
        state=session.state,
        cwd=session.cwd,
        started_at=session.started_at,
        completed_at=(
            (session.completed_at or _utc_now())
            if failed
            else (session.completed_at if session.state in {"done", "blocked", "stopped"} else None)
        ),
        stop_result="stopped" if session.state == "stopped" else None,
        auth_posture=_agent_auth_posture(session.metadata),
        billing_posture=_agent_billing_posture(session.metadata),
        blocker=BlockerSummary("agent_view_failed", "Claude Agent View reported a terminal failed state.") if failed else None,
    )


def _lifecycle_from_parts(
    *,
    session_id: str,
    state: str,
    cwd: str | None,
    started_at: str | None,
    completed_at: str | None,
    stop_result: str | None,
    auth_posture: str = "unknown",
    billing_posture: str = "unknown",
    blocker: BlockerSummary | None = None,
) -> AgentViewLifecycleResult:
    session_id = session_id if session_id and session_id != "unknown" else "unknown"
    state = state if state in AGENT_VIEW_STATES else "unknown"
    return AgentViewLifecycleResult(
        session_id=session_id,
        state=state,
        cwd=cwd,
        logs_ref=f"claude logs {session_id}" if session_id != "unknown" else None,
        started_at=started_at,
        completed_at=completed_at,
        stop_result=stop_result,
        auth_posture=auth_posture,
        billing_posture=billing_posture,
        blocker=blocker,
    )


def _cli_refusal_suffix(output: str) -> str:
    """The CLI's own one-line refusal (e.g. the --bg bypassPermissions disclaimer gate).

    Only a short line that reads as a CLI error or a `--bg` precondition is surfaced;
    anything else stays redacted like the rest of the launch output.
    """
    for line in str(output or "").splitlines():
        text = line.strip()
        if text and len(text) <= 300 and (
            text.lower().startswith(("error:", "error ")) or text.startswith("--bg ")
        ):
            return f" CLI: {text}"
    return ""


def _find_bound_session(sessions: tuple[AgentViewSession, ...], session_id: str) -> AgentViewSession | None:
    for session in sessions:
        if session.session_id == session_id or session.id == session_id:
            return session
    return None


def session_transcript_path(
    session_id: str,
    *,
    cwd: str | Path,
    project_dir_for_cwd: Callable[[str], Path],
    projects_root: Path | None = None,
) -> Path | None:
    """Locate `<session_id>.jsonl` under the Claude projects store.

    The CLI names the project directory after the session's cwd, which may be the
    resolved form of a symlinked path, so both spellings are tried before a lookup
    by the (unique) session id across all project directories.
    """
    session_id = _validated_agent_id(session_id)
    for spelling in dict.fromkeys((str(cwd), str(Path(cwd).resolve()))):
        candidate = project_dir_for_cwd(spelling) / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate
    root = projects_root if projects_root is not None else Path.home() / ".claude" / "projects"
    matches = sorted(root.glob(f"*/{session_id}.jsonl"))
    return matches[0] if len(matches) == 1 else None


def _find_session(sessions: tuple[AgentViewSession, ...], *, session_id: str | None, cwd: str | None) -> AgentViewSession | None:
    if session_id:
        for session in sessions:
            if session.id == session_id or session.session_id == session_id:
                return session
    if cwd:
        for session in sessions:
            if session.cwd == cwd and session.state in {"running", "blocked"}:
                return session
    return sessions[0] if len(sessions) == 1 else None


def _launch_session_id(output: str) -> str | None:
    text = str(output or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        value = payload.get("id") or payload.get("agent_id") or payload.get("agentId") or payload.get("session_id") or payload.get("sessionId")
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]+", value):
            return value
    for pattern in (
        # Claude Code 2.1.x prints `backgrounded · <short id>` (the same forms the
        # brokered seat parser in panel_invoker accepts).
        r"\bbackgrounded\s*[·•-]\s*([A-Za-z0-9._:-]+)",
        r"\bclaude\s+(?:attach|logs|stop)\s+([A-Za-z0-9._:-]+)\b",
        r"\b(?:agent|agent_id|session|session_id)\s*[:=]\s*([A-Za-z0-9._:-]+)",
        r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _agent_auth_posture(metadata: dict[str, Any]) -> str:
    auth = metadata.get("auth_posture") if isinstance(metadata.get("auth_posture"), dict) else metadata
    method = str(auth.get("method") or auth.get("authMethod") or auth.get("provider") or "").lower()
    status = str(auth.get("status") or "").lower()
    if method == "subscription" and status in {"authenticated", "ok", "ready"}:
        return "subscription_local"
    if method in {"api_key", "apikey", "key"}:
        return "api_key"
    return "unknown"


def _agent_billing_posture(metadata: dict[str, Any]) -> str:
    auth = _agent_auth_posture(metadata)
    if auth == "subscription_local":
        return "subscription_included"
    if auth == "api_key":
        return "api_key_billed"
    return "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
