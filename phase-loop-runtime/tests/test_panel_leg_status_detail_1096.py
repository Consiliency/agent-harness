"""agent-harness#1096 (+ the env-failure-as-OK half of agent-harness#1098 item 2).

On 2026-09-26 every brokered codex seat died about 9 s after launch with

    ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to
    purchase more credits or try again at Oct 1st, 2026 1:42 PM.

and the board reported a bare ``codex ERROR`` with ``detail=None``: the brokered path
dropped the CLI's log, and ``_AUTH_SIGNATURE`` does not match that wording. On dev0 a
codex seat returned ``OK`` whose text was a bubblewrap environment failure.

These tests drive the classifier AND the production seams that carry ``detail``:
the direct spawn, the brokered spawn (with a fake broker transport but the real
``_parent_infer`` / ``_exec_leg`` / ``_run_leg_with_liveness`` and a real subprocess),
the claude TUI sink, the governed-review consequence, and the board's stderr summary.
"""
from __future__ import annotations

import contextlib
import io
import sys
import textwrap
import time
import types
import unittest.mock
from pathlib import Path

import pytest

from phase_loop_runtime import governed_review as gr
from phase_loop_runtime import panel_invoker as pi


CODEX_USAGE_BANNER = (
    "ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage "
    "to purchase more credits or try again at Oct 1st, 2026 1:42 PM."
)
CODEX_BWRAP_FAILURE = (
    "error building bubblewrap command: app-server socket directory must be a "
    "user-owned directory with mode 0700"
)
CLAUDE_TMPDIR_REFUSAL = (
    "Temp directory /tmp/claude-0 is owned by uid 65534, expected 0. Refusing to use it "
    "— another user may have pre-created it. Set CLAUDE_CODE_TMPDIR to a directory "
    "you control, or ask an administrator to remove it."
)
# A codex transcript: the prompt is echoed FIRST, the CLI's own error comes LAST.
CODEX_LOG = (
    "OpenAI Codex v0.157.1 (research preview)\n--------\nworkdir: /tmp/x\nmodel: gpt-6-sol\n"
    "--------\nuser\nReview the attached phase change.\n" + CODEX_USAGE_BANNER + "\n"
)
CONFORMING_REVIEW_ABOUT_LIMITS = (
    "Findings:\n"
    "1. The retry wrapper treats `You've hit your usage limit` and `rate limit exceeded` "
    "as retryable; they are not, and hammering the backend makes it worse.\n"
    "2. A 401 Unauthorized from the token endpoint is logged but not surfaced.\n\n"
    "PARTIALLY AGREE"
)


# --- sourced wording --------------------------------------------------------------

@pytest.mark.parametrize("line", [
    CODEX_USAGE_BANNER,                                                   # measured, codex
    "You've hit your usage limit. Upgrade to Plus to continue using Codex",  # codex binary
    "You hit your spend cap set by the owner of your workspace.",          # codex binary
    "Increase your spend cap to continue.",                                # codex binary
    # claude: the binary holds "You've hit your" and "resets" as separate fragments; this
    # composed line is a SHAPE example, not a verbatim string.
    "You've hit your limit \u00b7 resets 3pm",
    "You've hit your monthly spend limit.",                                # claude binary
    "You've hit your team's shared budget. Switch to another model",       # claude binary
    "You've reached your Fable limit.",                                    # claude binary
    "Usage limit reached",                                                 # claude binary
    "You're out of usage credits. Switch to another model",                # claude binary
    "You hit your free usage limit.",                                      # grok binary
    "You hit your weekly limit.",                                          # grok binary
    "You've hit the rate limit for your plan. Upgrade your account or try again later.",
    "You've reached your free Grok Build usage limit for now.",            # grok binary
    "usage balance exhausted",                                             # grok binary
    "AI: Out of credits",                                                  # agy binary (UI)
    "Quota exhausted",                                                     # agy binary (UI)
    "stop_reason: STOP_REASON_QUOTA_EXHAUSTED",                            # agy binary
])
def test_sourced_usage_limit_wording_is_recognised(line):
    assert pi._PROVIDER_USAGE_LIMIT_RE.search(line), line


@pytest.mark.parametrize("line", [CODEX_BWRAP_FAILURE, CLAUDE_TMPDIR_REFUSAL])
def test_sourced_environment_failure_wording_is_recognised(line):
    assert pi._PROVIDER_ENV_FAILURE_RE.search(line), line


def test_server_capacity_is_not_a_usage_limit():
    """MODEL_CAPACITY_EXHAUSTED is the provider's capacity, not the account's quota."""
    assert not pi._PROVIDER_USAGE_LIMIT_RE.search("MODEL_CAPACITY_EXHAUSTED")


def test_a_recovered_per_minute_429_is_not_a_usage_limit():
    """agy retries a per-minute 429 in-process and then answers; the transcript keeps the
    RESOURCE_EXHAUSTED line (tests/test_phase_loop_launcher.py). Not an exhausted quota."""
    line = '[{"error":{"code":429,"status":"RESOURCE_EXHAUSTED"}}]'
    assert not pi._PROVIDER_USAGE_LIMIT_RE.search(line)
    body = "A substantive advisory answer that covers the question in full detail."
    assert pi._classify_leg(0, body, line, mode="advisory") == "OK"


# --- classifier + detail ------------------------------------------------------------

def test_usage_limit_banner_is_typed_degraded_with_reset_and_excerpt():
    status = pi._classify_leg(1, "", CODEX_LOG)
    assert status == "DEGRADED", "a provider usage limit must be typed, not a bare ERROR"
    detail = pi._leg_failure_detail(status, 1, "", CODEX_LOG)
    assert detail is not None
    assert detail.startswith("provider_usage_limit (resets Oct 1st, 2026 1:42 PM): ")
    assert "You've hit your usage limit" in detail
    assert "Review the attached phase change" not in detail, "detail is the prompt echo"


def test_conforming_review_that_discusses_limits_stays_ok():
    """The ah#252 invariant: prose ABOUT limits/auth is subject matter, not a failure —
    even when codex echoes that prose into its log."""
    log = CODEX_LOG.replace(CODEX_USAGE_BANNER, CONFORMING_REVIEW_ABOUT_LIMITS)
    status = pi._classify_leg(0, CONFORMING_REVIEW_ABOUT_LIMITS, log, mode="review")
    assert status == "OK"
    assert pi._leg_failure_detail(status, 0, CONFORMING_REVIEW_ABOUT_LIMITS, log) is None


def test_long_conforming_review_quoting_an_env_failure_stays_ok():
    """This panel reviews the very code that matches these strings. A real review that
    QUOTES one mid-body is a review, not the failure."""
    body = (
        "The classifier change looks right overall.\n"
        + "Context line explaining the change in detail. " * 12 + "\n"
        + f"Quoting the fixture: `{CODEX_BWRAP_FAILURE}` is matched only as a whole body.\n"
        + "AGREE"
    )
    assert len(body) > pi._PROVIDER_FAILURE_BODY_MAX_CHARS
    assert pi._classify_leg(0, body, body, mode="review") == "OK"


def test_long_conforming_review_that_OPENS_by_quoting_an_env_failure_stays_ok():
    """Reviewers of this very change will lead with the fixture string."""
    body = (
        f"The `{CODEX_BWRAP_FAILURE}` path is now typed.\n"
        + "Detailed finding about the classifier ordering. " * 15 + "\nAGREE"
    )
    assert len(body) > pi._PROVIDER_FAILURE_BODY_MAX_CHARS
    assert pi._classify_leg(0, body, body, mode="review") == "OK"


def test_gemini_broker_env_failure_detail_is_in_the_fixed_vocabulary():
    assert "Gemini broker response is a provider environment failure" in pi._GEMINI_BROKER_DETAILS


@pytest.mark.parametrize("body", [
    CODEX_BWRAP_FAILURE,
    CODEX_BWRAP_FAILURE + "\n\nDISAGREE",
    "DISAGREE — " + CODEX_BWRAP_FAILURE,
    CLAUDE_TMPDIR_REFUSAL,
])
@pytest.mark.parametrize("mode", ["review", "advisory"])
def test_environment_failure_output_with_rc0_is_never_ok(body, mode):
    status = pi._classify_leg(0, body, "", mode=mode)
    assert status != "OK", f"an environment failure was reported as a review: {body!r}"
    detail = pi._leg_failure_detail(status, 0, body, "")
    assert detail is not None and detail.startswith("provider_environment_failure: ")


def test_advisory_usage_banner_body_is_not_a_substantive_advisory():
    """Advisory completion is only len>=40, so a usage banner printed on stdout (grok /
    agy) used to clear it and fail OPEN."""
    banner = "You've hit the rate limit for your plan. Upgrade your account or try again later."
    assert len(banner) >= 40
    assert pi._classify_leg(0, banner, "", mode="advisory") == "DEGRADED"


def test_advisory_prose_mentioning_limits_deep_in_a_long_body_stays_ok():
    body = (
        "The architecture holds up. " * 30
        + "\nOne risk: when the provider says 'You hit your weekly limit.' the job stalls.\n"
    )
    assert pi._classify_leg(0, body, "", mode="advisory") == "OK"


def test_signature_only_in_the_echoed_prompt_head_does_not_type_the_failure():
    """Only the log TAIL is the CLI's own error; a bundle that merely contains the banner
    (this PR's own diff, for one) is echoed at the HEAD of codex's transcript."""
    log = "user\n" + CODEX_USAGE_BANNER + "\n" + "\n".join(
        f"bundle line {i}" for i in range(40)
    ) + "\nERROR: stream disconnected before completion: connection reset\n"
    status = pi._classify_leg(1, "", log)
    assert status == "ERROR"
    detail = pi._leg_failure_detail(status, 1, "", log)
    assert detail == "ERROR: stream disconnected before completion: connection reset"


def test_detail_is_redacted_and_bounded():
    secret_log = (
        "user\nsome prompt\n"
        "fatal: auth failed token=abcdefghijklmnopqrstuv Bearer abcdefghijklmnop "
        "for alice@example.com key sk-ant-api03-abcdefghijklmnop at /home/alice/.codex/auth.json "
        + "x" * 900 + "\n"
    )
    detail = pi._leg_failure_detail("ERROR", 1, "", secret_log)
    assert detail is not None
    for leaked in ("abcdefghijklmnopqrstuv", "Bearer abcdefghijklmnop", "alice@example.com",
                   "sk-ant-api03", "/home/alice"):
        assert leaked not in detail, f"{leaked!r} leaked into detail: {detail!r}"
    assert len(detail) <= pi._LEG_DETAIL_MAX_CHARS


def test_detail_never_carries_a_raw_diff_hunk():
    """detail reaches governed-review finding reasons; the closeout metadata gate treats
    a raw hunk header as a FATAL malformed closeout."""
    log = "user\nprompt\nerror: patch failed at @@ -1,3 +1,4 @@ in file\n"
    detail = pi._leg_failure_detail("ERROR", 1, "", log)
    assert detail is not None and "@@ -1,3 +1,4 @@" not in detail


def test_single_line_harness_diagnostics_are_kept_whole():
    for diag in ("timeout after 900s", "subscription_auth_unproven"):
        assert pi._leg_failure_detail("DEGRADED", 1, "", diag) == diag


# --- production seams ----------------------------------------------------------------

def test_direct_spawn_carries_typed_detail_and_stays_a_warn(monkeypatch):
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", CODEX_LOG))
    leg = pi.invoke_panel("ARTIFACT", ["codex"]).legs[0]
    assert leg.status == "DEGRADED"
    assert not leg.text.strip(), "a diagnostic leaked into text (governed BLOCK)"
    assert leg.detail and leg.detail.startswith("provider_usage_limit (resets Oct 1st, 2026")
    findings = gr._findings_from_panel(pi.PanelResult(legs=(leg,)))
    assert [f.code for f in findings] == ["panel_leg_degraded"]
    assert "provider_usage_limit" in findings[0].reason


def test_env_failure_reported_as_review_is_a_governed_block_not_a_pass(monkeypatch):
    """Fail CLOSED: the text is kept, so the governed gate reads a non-conforming review
    (BLOCK). Blanking it would turn a false-positive DISAGREE into a WARN (fail-open)."""
    body = CODEX_BWRAP_FAILURE + "\n\nAGREE"
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (0, body, body))
    leg = pi.invoke_panel("ARTIFACT", ["codex"]).legs[0]
    assert leg.status == "DEGRADED"
    assert leg.text == body
    assert leg.detail and leg.detail.startswith("provider_environment_failure: ")
    findings = gr._findings_from_panel(pi.PanelResult(legs=(leg,)))
    assert any(f.code == "panel_nonconforming" and f.severity == "block" for f in findings)


class _FakeBroker:
    """Only the transport is faked: ``run_credentialless_client`` invokes the REAL
    adapter (the production ``_parent_infer`` closure) in-process."""

    invoked = 0

    def __init__(self, *_a, **_k):
        self.evidence: dict[str, object] = {}

    def run_credentialless_client(self, adapter, *, deadline_s, cancel_event=None):
        type(self).invoked += 1
        status, text = adapter.invoke()
        return {"schema": "parent_unix_broker_v1", "status": status, "text": text}, {"fake": True}

    def close(self):
        return None


def _brokered_codex(monkeypatch, tmp_path, script: str):
    """Drive the production brokered branch of ``_default_spawn`` with a fake codex
    process. ``_exec_leg`` / ``_run_leg_with_liveness`` stay production (patching them
    would switch the injected-seam predicate and skip the brokered branch entirely)."""
    assert not pi._has_injected_review_execution_seam(leg="codex")
    monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(pi, "derive_review_leg_authorization",
                        lambda *a, **k: types.SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12))
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda leg, env: (True, ""))
    monkeypatch.setattr(pi, "_record_broker_provider_evidence", lambda *a, **k: None)

    def fake_command(*, out_file, **_kw):
        return [sys.executable, "-c", textwrap.dedent(script), str(out_file)]

    monkeypatch.setattr(pi, "_brokered_codex_command", fake_command)
    monkeypatch.setattr(_FakeBroker, "invoked", 0)
    spawned = pi._default_spawn(
        "codex", "ARTIFACT", mode="review", model="gpt-test",
        review_authorization=types.SimpleNamespace(staged_tree_sha256=None),
        canonical_repo_authority=tmp_path,
    )
    assert _FakeBroker.invoked == 1, f"the brokered branch never ran: {spawned!r}"
    return spawned


def test_brokered_codex_usage_limit_reaches_detail(monkeypatch, tmp_path):
    """THE 2026-09-26 path: brokered codex, rc=1, banner on stderr → previously
    ``("ERROR", "")`` with no detail at all."""
    spawned = _brokered_codex(monkeypatch, tmp_path, f"""
        import sys
        sys.stdin.read()
        sys.stderr.write("user\\nReview the attached phase change.\\n")
        sys.stderr.write({CODEX_USAGE_BANNER!r} + "\\n")
        sys.exit(1)
    """)
    assert len(spawned) == 3, f"brokered codex dropped the diagnostic: {spawned!r}"
    status, text, detail = spawned
    assert status == "DEGRADED"
    assert text == ""
    assert detail.startswith("provider_usage_limit (resets Oct 1st, 2026 1:42 PM): ")


def test_brokered_codex_conforming_review_about_limits_is_ok_without_detail(monkeypatch, tmp_path):
    spawned = _brokered_codex(monkeypatch, tmp_path, f"""
        import sys
        sys.stdin.read()
        review = {CONFORMING_REVIEW_ABOUT_LIMITS!r}
        sys.stderr.write("user\\nprompt\\ncodex\\n" + review + "\\n")
        open(sys.argv[1], "w").write(review)
    """)
    assert tuple(spawned) == ("OK", CONFORMING_REVIEW_ABOUT_LIMITS)


def test_brokered_codex_env_failure_text_is_not_ok(monkeypatch, tmp_path):
    body = CODEX_BWRAP_FAILURE + "\n\nAGREE"
    spawned = _brokered_codex(monkeypatch, tmp_path, f"""
        import sys
        sys.stdin.read()
        open(sys.argv[1], "w").write({body!r})
    """)
    assert spawned[0] == "DEGRADED"
    assert spawned[1] == body, "the text must be kept (fail-closed governed BLOCK)"
    assert spawned[2].startswith("provider_environment_failure: ")


def test_claude_tui_refusal_reaches_the_detail_sink(monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: (
        1, "", "claude_tui_pty_eof_no_output", pi._sanitized_pty_tail(CLAUDE_TMPDIR_REFUSAL.encode())
    ))
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list[str] = []
    status, _text = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert status != "OK"
    assert sink and sink[-1].startswith("provider_environment_failure: Temp directory /tmp/claude-0")


def test_claude_tui_ok_leaves_the_sink_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: (
        0, "Looks fine.\n\nAGREE", "claude_tui_file_output", ""
    ))
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list[str] = []
    status, _text = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert status == "OK" and sink == []


def test_board_stderr_summary_names_why_a_seat_failed(tmp_path):
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    real_compose = comp_mod.compose_review_board
    detail = "provider_usage_limit (resets Oct 1st, 2026 1:42 PM): " + CODEX_USAGE_BANNER
    result = pi.PanelResult(legs=(
        pi.PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:a"),
        pi.PanelLegResult(leg="gemini", status="OK", text="AGREE", seat_key="gemini:a"),
        pi.PanelLegResult(leg="claude", status="OK", text="AGREE", seat_key="claude:a"),
        pi.PanelLegResult(leg="codex", status="DEGRADED", text="", detail=detail, seat_key="codex:a"),
    ))
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    with (
        unittest.mock.patch.object(
            comp_mod, "compose_review_board",
            side_effect=lambda *a, **k: real_compose(
                is_available=lambda v: v in {"codex", "gemini", "claude", "grok"}
            ),
        ),
        unittest.mock.patch.object(pi, "invoke_board", return_value=result),
    ):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            cli_main(["advisor-board", str(artifact)])
    lines = [line for line in err.getvalue().splitlines() if "[DEGRADED] codex:a" in line]
    assert len(lines) == 1, err.getvalue()
    assert detail in lines[0]


def test_multiline_tool_denial_keeps_the_harness_explanation(monkeypatch, tmp_path):
    """The TOOL-DENIAL diagnostic embeds the CLI's stderr; a multi-line stderr must not
    reduce `detail` to the CLI's last line and drop the harness's own explanation."""
    class _Proc:
        returncode = 0
        stdout = ""
        stderr = (
            "Warning: 256-color support not detected.\n"
            'jetski: no output produced — a tool required the "command" permission that '
            "headless mode cannot prompt for, so it was auto-denied.\n"
        )

    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda cmd, **kw: _Proc())
    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("the diff")
    rc, text, log = pi._exec_leg("gemini", review_dir, out_dir, timeout_s=60, artifact="A", env={})
    detail = pi._leg_failure_detail(pi._classify_leg(rc, text, log), rc, text, log)
    assert detail and "TOOL-DENIAL" in detail and "auto-denied" in detail
