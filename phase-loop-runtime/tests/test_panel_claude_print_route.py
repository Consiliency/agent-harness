"""Stage 1b: headless `claude -p --output-format stream-json` is the default Claude seat route.

The PTY TUI adapter stays as the explicit fallback (`PHASE_LOOP_PANEL_CLAUDE_ROUTE=tui`).
The print route proves in-band that it runs on subscription OAuth: the first `system/init`
must report `apiKeySource == "none"`, and an auth or billing `system/api_retry` ends the run.

The session tests launch a REAL child (a POSIX `sh` script printing scripted stream-json)
through the owned seat launch, as the TUI liveness tests do; the leg tests replace the session.
"""
from __future__ import annotations

import json
import shutil
import time
import types
from pathlib import Path
from unittest.mock import patch

import pytest

import phase_loop_runtime.panel_invoker as pi
from phase_loop_runtime import president_adapter
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

_ROUTE_ENV = "PHASE_LOOP_PANEL_CLAUDE_ROUTE"
_BROKER_DENY = "Bash,Read,Edit,Write,WebFetch,WebSearch,Task,NotebookEdit"


def _event(**fields) -> str:
    return json.dumps(fields)


_INIT_OAUTH = _event(type="system", subtype="init", apiKeySource="none", tools=[])
_INIT_KEY = _event(type="system", subtype="init", apiKeySource="ANTHROPIC_API_KEY", tools=[])


def _result(text: str) -> str:
    return _event(type="result", subtype="success", result=text, permission_denials=[])


def _script(*lines: str, then: str = "") -> list[str]:
    body = "".join(f"printf '%s\\n' {_sh_quote(line)}; " for line in lines)
    return ["sh", "-c", "cat >/dev/null; " + body + then]


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _stage(tmp_path: Path) -> tuple[Path, Path]:
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("bundle", encoding="utf-8")
    (review_dir / "review-instructions.md").write_text("instructions", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return review_dir, out_dir


@pytest.fixture
def ready_host(monkeypatch):
    """A supported, subscription-authed host outside Claude Code (the gates pass)."""
    monkeypatch.delenv(_ROUTE_ENV, raising=False)
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))


# --- argv golden -----------------------------------------------------------------------


def _without_session(command: list[str]) -> list[str]:
    index = command.index("--session-id")
    return command[:index + 1] + ["<SESSION>"] + command[index + 2:]


def test_brokered_print_argv_golden():
    command = pi._claude_print_seat_command("claude-opus-5-5", None, brokered=True)
    assert _without_session(command) == [
        "claude", "-p", "--verbose", "--output-format", "stream-json", "--input-format", "text",
        "--model", "claude-opus-5-5", "--effort", "high",
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--setting-sources", "", "--strict-mcp-config",
        "--mcp-config", '{"mcpServers": {}}', "--agents", "{}",
        "--no-chrome", "--disable-slash-commands", "--session-id", "<SESSION>",
        "--tools", "", "--disallowedTools", _BROKER_DENY,
    ]


def test_direct_print_argv_golden(tmp_path):
    review_dir = tmp_path / "review"
    command = pi._claude_print_seat_command(
        None, None, brokered=False, add_dirs=[review_dir],
    )
    assert _without_session(command) == [
        "claude", "-p", "--verbose", "--output-format", "stream-json", "--input-format", "text",
        "--model", pi.DEFAULT_LEG_MODELS["claude"], "--effort", "high",
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--setting-sources", "", "--strict-mcp-config",
        "--mcp-config", '{"mcpServers": {}}', "--agents", "{}",
        "--no-chrome", "--disable-slash-commands", "--session-id", "<SESSION>",
        "--add-dir", str(review_dir), "--tools", "Read", "--allowedTools", "Read",
    ]


@pytest.mark.parametrize("brokered", [True, False])
def test_print_argv_never_bare_and_session_is_fresh(brokered):
    first = pi._claude_print_seat_command(None, None, brokered=brokered)
    second = pi._claude_print_seat_command(None, None, brokered=brokered)
    assert "--bare" not in first
    assert "--permission-prompts" in first
    assert first[first.index("--session-id") + 1] != second[second.index("--session-id") + 1]


def test_brokered_leg_puts_prompt_on_stdin_with_no_add_dir(tmp_path, monkeypatch, ready_host):
    review_dir, out_dir = _stage(tmp_path)
    seen = {}

    def fake_session(command, prompt, **kwargs):
        seen.update(command=list(command), prompt=prompt, kwargs=kwargs)
        kwargs["observed"]["api_key_source"] = "none"
        return 0, "Reviewed.\nAGREE", pi._HarnessCode("claude_print_result"), ""

    monkeypatch.setattr(pi, "_run_claude_print_session", fake_session)
    evidence: dict[str, object] = {}
    sealed = "SEALED-REVIEW-MATERIAL-1b"
    status, text = pi._exec_claude_tui_leg(
        review_dir, out_dir, 60, "bundle", broker_prompt=sealed, broker_evidence=evidence,
    )
    assert (status, text) == ("OK", "Reviewed.\nAGREE")
    assert seen["command"][:2] == ["claude", "-p"]
    assert "--add-dir" not in seen["command"]
    assert not any(sealed in part for part in seen["command"]), "the prompt never rides argv"
    assert seen["prompt"] == pi._BROKER_CLAUDE_DIRECT_REQUEST + sealed
    assert seen["kwargs"]["cwd"] == out_dir.resolve()
    assert evidence["claude_route"] == "print"
    assert evidence["claude_api_key_source"] == "none"
    assert evidence["provider_prompt_transport"] == "stdin"
    assert "<STDIN_SEALED_INLINE_PROMPT>" in evidence["provider_argv_shape"]
    assert "<CLAUDE_SESSION_ID>" in evidence["provider_argv_shape"]
    # Every key the TUI route records is still present.
    for key in ("claude_session_id_sha256", "claude_session_resume_forbidden",
                "claude_transcript_exact_path_sha256", "claude_transcript_preexisting",
                "provider_liveness_profile", "provider_liveness_stall_threshold_s",
                "provider_liveness_prompt_bytes", "claude_transcript_cleanup_verified"):
        assert key in evidence, key


def test_direct_leg_prompt_drops_the_file_handoff_and_keeps_the_verdict(
    tmp_path, monkeypatch, ready_host,
):
    review_dir, out_dir = _stage(tmp_path)
    seen = {}

    def fake_session(command, prompt, **kwargs):
        seen.update(command=list(command), prompt=prompt)
        return 0, "Fine.\nPARTIALLY AGREE", pi._HarnessCode("claude_print_result"), ""

    monkeypatch.setattr(pi, "_run_claude_print_session", fake_session)
    status, _text = pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle", repo_dir=review_dir)
    assert status == "OK"
    assert "panel-claude.txt" not in seen["prompt"]
    assert "Write tool" not in seen["prompt"]
    assert "AGREE, PARTIALLY AGREE, or DISAGREE" in seen["prompt"]
    assert seen["command"][seen["command"].index("--add-dir") + 1] == str(review_dir)
    assert seen["command"][-4:] == ["--tools", "Read", "--allowedTools", "Read"]


# --- session: the drift guard, the text, the stall --------------------------------------


@pytest.fixture
def owned_session(request):
    if shutil.which("sh") is None:
        pytest.skip("needs POSIX sh")
    request.getfixturevalue("owned_review_network")


def _session(command, tmp_path, **kwargs):
    observed: dict[str, object] = {}
    kwargs.setdefault("timeout_s", 30)
    result = pi._run_claude_print_session(
        command, "review this", env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path,
        observed=observed, **kwargs,
    )
    return result, observed


def _spy_group_kill(monkeypatch) -> list:
    killed: list = []
    real = pi._terminate_process_group

    def spy(proc, **kwargs):
        killed.append(proc)
        return real(proc, **kwargs)

    monkeypatch.setattr(pi, "_terminate_process_group", spy)
    return killed


def test_api_key_source_fails_closed_and_kills_the_group(tmp_path, monkeypatch, owned_session):
    killed = _spy_group_kill(monkeypatch)
    start = time.monotonic()
    (rc, text, log, _tail), observed = _session(
        _script(_INIT_KEY, then="sleep 60"), tmp_path, stall_s=30,
    )
    assert time.monotonic() - start < 20, "the guard must not wait for the child"
    assert (rc != 0, text, log) == (True, "", "claude_print_subscription_unproven")
    assert observed["api_key_source"] == "ANTHROPIC_API_KEY"
    assert killed, "the process group was not terminated"
    assert all(not pi._process_group_exists(proc.pid) for proc in killed)


@pytest.mark.parametrize("error", sorted(pi._CLAUDE_PRINT_AUTH_DRIFT_ERRORS))
def test_auth_or_billing_retry_is_auth_drift(tmp_path, monkeypatch, owned_session, error):
    killed = _spy_group_kill(monkeypatch)
    retry = _event(type="system", subtype="api_retry", attempt=1, error=error)
    (rc, text, log, _tail), _observed = _session(
        _script(_INIT_OAUTH, retry, then="sleep 60"), tmp_path, stall_s=30,
    )
    assert (rc != 0, text, log) == (True, "", "claude_print_auth_drift")
    assert killed and all(not pi._process_group_exists(proc.pid) for proc in killed)


def test_a_transient_retry_is_not_drift(tmp_path, owned_session):
    retry = _event(type="system", subtype="api_retry", attempt=1, error="overloaded")
    (rc, text, log, _tail), _observed = _session(
        _script(_INIT_OAUTH, retry, _result("ok\nAGREE")), tmp_path,
    )
    assert (rc, text, log) == (0, "ok\nAGREE", "claude_print_result")


def test_missing_init_fails_closed(tmp_path, owned_session):
    (rc, text, log, _tail), observed = _session(_script(_result("AGREE")), tmp_path)
    assert (rc != 0, text, log) == (True, "", "claude_print_subscription_unproven")
    assert observed["api_key_source"] is None


def test_happy_path_result_text_classifies_ok(tmp_path, owned_session):
    assistant = _event(type="assistant", message={"content": [{"type": "text", "text": "x"}]})
    (rc, text, log, _tail), observed = _session(
        _script(_INIT_OAUTH, assistant, _result("The change is sound.\nAGREE")), tmp_path,
    )
    assert (rc, text, log) == (0, "The change is sound.\nAGREE", "claude_print_result")
    assert observed["api_key_source"] == "none"
    assert pi._classify_leg(rc, text, log) == "OK"


def test_silence_is_claude_print_stalled(tmp_path, owned_session):
    start = time.monotonic()
    (rc, text, log, _tail), _observed = _session(
        _script(_INIT_OAUTH, then="sleep 60"), tmp_path, stall_s=1, backstop_s=30,
    )
    assert time.monotonic() - start < 20
    assert (rc != 0, text, log) == (True, "", "claude_print_stalled")


# --- leg status mapping ----------------------------------------------------------------


@pytest.mark.parametrize("code", ["claude_print_subscription_unproven", "claude_print_auth_drift"])
def test_guard_codes_end_the_leg_unavailable(tmp_path, monkeypatch, ready_host, code):
    review_dir, out_dir = _stage(tmp_path)
    monkeypatch.setattr(
        pi, "_run_claude_print_session",
        lambda *a, **k: (1, "", pi._HarnessCode(code), ""),
    )
    assert pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle") == ("UNAVAILABLE", code)
    assert code in pi._TYPED_UNAVAILABLE_DETAILS


def test_stall_ends_the_leg_degraded_with_no_text(tmp_path, monkeypatch, ready_host):
    review_dir, out_dir = _stage(tmp_path)
    monkeypatch.setattr(
        pi, "_run_claude_print_session",
        lambda *a, **k: (1, "", pi._HarnessCode("claude_print_stalled"), ""),
    )
    assert pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle") == ("DEGRADED", "")


# --- route selection and gates ---------------------------------------------------------


def test_route_selector(monkeypatch):
    monkeypatch.delenv(_ROUTE_ENV, raising=False)
    assert pi._panel_claude_route() == "print"
    monkeypatch.setenv(_ROUTE_ENV, "")
    assert pi._panel_claude_route() == "print"
    monkeypatch.setenv(_ROUTE_ENV, "tui")
    assert pi._panel_claude_route() == "tui"
    monkeypatch.setenv(_ROUTE_ENV, "print")
    assert pi._panel_claude_route() == "print"
    monkeypatch.setenv(_ROUTE_ENV, "sdk")
    assert pi._panel_claude_route() is None


def _forbid_launches(monkeypatch) -> list:
    launched: list = []
    for name in ("_run_claude_print_session", "_run_claude_tui_session", "_run_leg_with_liveness"):
        monkeypatch.setattr(pi, name, lambda *a, _n=name, **k: launched.append(_n))
    return launched


def test_default_route_runs_print_and_tui_route_runs_tui(tmp_path, monkeypatch, ready_host):
    review_dir, out_dir = _stage(tmp_path)
    launched: list = []
    monkeypatch.setattr(
        pi, "_run_claude_print_session",
        lambda *a, **k: launched.append("print") or (0, "AGREE", "claude_print_result", ""),
    )
    monkeypatch.setattr(
        pi, "_run_claude_tui_session",
        lambda **k: launched.append("tui") or (0, "AGREE", "claude_tui_file_output", ""),
    )
    pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle")
    monkeypatch.setenv(_ROUTE_ENV, "tui")
    pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle")
    assert launched == ["print", "tui"]


def test_invalid_route_fails_closed_without_launching(tmp_path, monkeypatch, ready_host):
    review_dir, out_dir = _stage(tmp_path)
    launched = _forbid_launches(monkeypatch)
    monkeypatch.setenv(_ROUTE_ENV, "Print-ish")
    assert pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle") == (
        "UNAVAILABLE", "panel_claude_route_invalid",
    )
    assert launched == []


def test_under_claude_code_defers_before_the_route_is_read(tmp_path, monkeypatch):
    review_dir, out_dir = _stage(tmp_path)
    launched = _forbid_launches(monkeypatch)
    monkeypatch.setenv(_ROUTE_ENV, "not-a-route")
    status = pi._exec_claude_tui_leg(
        review_dir, out_dir, 60, "bundle", env={"CLAUDECODE": "1"},
    )
    assert status == ("UNAVAILABLE", "under_claude_code")
    assert launched == []


def _version_probe(monkeypatch, version: str) -> None:
    monkeypatch.setattr(
        pi, "run_provider",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=f"{version} (Claude Code)", stderr=""),
    )


def test_print_route_minimum_version(monkeypatch):
    _version_probe(monkeypatch, "2.1.258")
    assert pi._claude_code_support_status(min_version=pi._CLAUDE_PRINT_MIN_VERSION) == (
        False, "claude_code_version_below_minimum:2.1.258",
    )
    # The TUI keeps its own, lower minimum.
    assert pi._claude_code_support_status()[0] is True
    _version_probe(monkeypatch, pi._CLAUDE_PRINT_MIN_VERSION_TEXT)
    assert pi._claude_code_support_status(min_version=pi._CLAUDE_PRINT_MIN_VERSION)[0] is True


def test_old_cli_is_unavailable_on_print_without_launching(tmp_path, monkeypatch):
    review_dir, out_dir = _stage(tmp_path)
    monkeypatch.delenv(_ROUTE_ENV, raising=False)
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))
    _version_probe(monkeypatch, "2.1.258")
    launched = _forbid_launches(monkeypatch)
    assert pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle") == (
        "UNAVAILABLE", "claude_code_version_below_minimum:2.1.258",
    )
    assert launched == []


# --- president -------------------------------------------------------------------------


class _Reached(Exception):
    pass


def test_president_fable_rung_runs_the_print_session_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(_ROUTE_ENV, raising=False)
    calls: list = []

    def spy_print(command, prompt, **kwargs):
        calls.append((list(command), prompt, kwargs))
        raise _Reached()

    def forbid_tui(*args, **kwargs):
        raise AssertionError("the president's default Claude route is print, not the TUI")

    with patch.object(pi, "_run_claude_print_session", spy_print), patch.object(
        pi, "_run_claude_tui_session", forbid_tui
    ):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}
        )
        # A raising route is a typed rung failure; the spy records that it was reached.
        seam("fable", "F001: [fable] the dispatch lock is never released")
    (command, prompt, kwargs), = calls
    assert command[:2] == ["claude", "-p"] and "--bare" not in command
    assert command[command.index("--tools") + 1] == ""
    assert prompt.startswith(pi._BROKER_CLAUDE_DIRECT_REQUEST)
    assert kwargs["mode"] == "president"


def test_president_invalid_route_fails_without_launching(tmp_path, monkeypatch):
    monkeypatch.setenv(_ROUTE_ENV, "bogus")
    launched = _forbid_launches(monkeypatch)
    seam = president_adapter.build_president_invoke(
        DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}
    )
    response = seam("fable", "F001: [fable] the dispatch lock is never released")
    assert response["status"] == "failed"
    assert "panel_claude_route_invalid" in response["detail"]
    assert launched == []
