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
import re
import sys
import textwrap
import time
import types
import unittest.mock

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
    "Quota exceeded. Check your plan and billing details.",                # codex binary
    "You hit your spend cap set by the owner of your workspace. Ask an owner to increase "
    "your spend cap to continue.",                                         # codex binary
    "You've hit your monthly spend limit.",                                # claude binary
    "You've hit your team's shared budget. Switch to another model",       # claude binary
    "You've reached your Fable limit.",                                    # claude binary
    "Usage limit reached",                                                 # claude binary
    "You're out of usage credits. Switch to another model",                # claude binary
    "You hit your free usage limit.",                                      # grok binary
    "You hit your weekly limit.",                                          # grok binary
    "You've hit the rate limit for your plan. Upgrade your account or try again later.",
    "You've reached your free Grok Build usage limit for now.",            # grok binary
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
    assert pi._classify_leg(0, body, body, mode="review") == "OK"


def test_long_conforming_review_that_OPENS_by_quoting_an_env_failure_stays_ok():
    """Reviewers of this very change will lead with the fixture string."""
    body = (
        f"The `{CODEX_BWRAP_FAILURE}` path is now typed.\n"
        + "Detailed finding about the classifier ordering. " * 15 + "\nAGREE"
    )
    assert pi._classify_leg(0, body, body, mode="review") == "OK"


def test_gemini_broker_env_failure_detail_is_in_the_fixed_vocabulary():
    assert "Gemini broker response is a provider environment failure" in pi._GEMINI_BROKER_DETAILS
    assert "Gemini broker response is a provider usage limit" in pi._GEMINI_BROKER_DETAILS


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


# --- board round 1 (agent-harness#1102): the length rule failed both directions ---------

def test_short_review_quoting_env_string_in_backticks_stays_ok():
    body = "The `error building bubblewrap command` diagnostic is handled correctly.\n\nAGREE"
    for mode in ("review", "advisory"):
        assert pi._classify_leg(0, body, body, mode=mode) == "OK", mode


def test_short_review_quoting_env_line_beside_its_own_prose_stays_ok():
    body = (
        "The bubblewrap failure is handled.\n\n" + CODEX_BWRAP_FAILURE + "\n\nAGREE"
    )
    assert pi._classify_leg(0, body, "", mode="review") == "OK"


@pytest.mark.parametrize("body", [
    "Handled:\n```\n" + CODEX_BWRAP_FAILURE + "\n```\nAGREE",
    # nothing but a fenced quote and a verdict: a fence is QUOTED text, never the CLI's line
    "```\n" + CODEX_BWRAP_FAILURE + "\n```\n\nAGREE",
])
def test_short_review_quoting_env_line_in_a_fence_stays_ok(body):
    assert pi._classify_leg(0, body, "", mode="review") == "OK"


@pytest.mark.parametrize("mode,suffix", [("advisory", ""), ("review", "\n\nAGREE")])
def test_long_env_failure_only_body_is_degraded(mode, suffix):
    body = "\n".join([CODEX_BWRAP_FAILURE] * 5) + suffix
    assert len(body) > 500
    assert pi._classify_leg(0, body, "", mode=mode) == "DEGRADED"
    detail = pi._leg_failure_detail("DEGRADED", 0, body, "")
    assert detail.startswith("provider_environment_failure: ")


@pytest.mark.parametrize("mode", ["advisory", "review"])
def test_long_temp_dir_refusal_is_degraded(mode):
    body = (
        "Temp directory /" + "p" * 431 + " is owned by uid 65534, expected 0. Refusing to use it"
    ) + ("\n\nAGREE" if mode == "review" else "")
    assert len(body) > 500
    assert pi._classify_leg(0, body, "", mode=mode) == "DEGRADED"


@pytest.mark.parametrize("body", [
    "Batch the calls; if you hit the rate limit, back off and retry.",
    # advice that STARTS a line with the generic shape but is not a sourced sentence
    "You hit the context limit quickly with this design; trim the prompt and retry.",
])
@pytest.mark.parametrize("echo", [False, True])
def test_advisory_advice_about_limits_is_not_a_usage_limit(body, echo):
    log = f"user\nprompt\ncodex\n{body}" if echo else ""
    assert pi._classify_leg(0, body, log, mode="advisory") == "OK"


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


def test_prompt_echo_and_provider_error_in_the_same_tail_window():
    """A short prompt puts its echo INSIDE the 20-line tail with the provider's output.
    Prompt prose that mentions a banner (mid-sentence, in backticks) must neither type the
    failure nor be chosen as the excerpt."""
    log = (
        "user\nPlease check how we handle `You've hit your usage limit` banners; the "
        "error path failed last week.\n"
        "ERROR: stream disconnected before completion: connection reset\n"
    )
    status = pi._classify_leg(1, "", log)
    assert status == "ERROR"
    assert pi._leg_failure_detail(status, 1, "", log) == (
        "ERROR: stream disconnected before completion: connection reset"
    )
    # ...and the reverse: the provider banner types it even with error-ish prompt text around.
    log = "user\nThe error path failed; see the limit handling.\n" + CODEX_USAGE_BANNER + "\n"
    status = pi._classify_leg(1, "", log)
    assert status == "DEGRADED"
    detail = pi._leg_failure_detail(status, 1, "", log)
    assert detail.startswith("provider_usage_limit (resets Oct 1st, 2026 1:42 PM): ERROR: You've")


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


@pytest.mark.parametrize("secret", [
    "xoxc-1234567890-abcdefghij", "xoxe-1234567890-abcdefghij", "ghu_abcdefghijklmnop",
    "ghr_abcdefghijklmnop", "xai-abcdefghijklmnopqrst", "/var/home/alice/.config",
])
def test_detail_redacts_additional_token_shapes(secret):
    detail = pi._leg_failure_detail("ERROR", 1, "", f"user\nprompt\nfatal: rejected {secret}\n")
    assert detail is not None
    assert secret not in detail and "alice" not in detail, detail


def test_the_final_labelled_detail_is_bounded_and_control_stripped():
    """The bound is on the STORED string, label included, and a terminal escape in a CLI
    line never reaches the operator's terminal via `advisor-board`."""
    path = "/tmp/\x1b[2J\x07\x1bZ\x9b2J\x00" + "z" * 950
    line = f"Temp directory {path} is owned by uid 65534, expected 0. Refusing to use it"
    log = line + "\n"
    status = pi._classify_leg(1, "", log)
    assert status == "DEGRADED"
    detail = pi._leg_failure_detail(status, 1, "", log)
    assert detail.startswith("provider_environment_failure: Temp directory /tmp/")
    assert len(detail) <= pi._LEG_DETAIL_MAX_CHARS
    assert not re.search(r"[\x00-\x1f\x7f-\x9f]", detail), repr(detail)


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
    assert status == "DEGRADED", "a typed environment failure is DEGRADED on every route"
    assert sink and sink[-1].startswith("provider_environment_failure: Temp directory /tmp/claude-0")


def test_claude_sink_prefix_is_redacted_and_bounded(monkeypatch, tmp_path):
    """The untyped sink detail is `<log_text>: <tail>`; the prefix goes through the same
    redaction and final bound as everything else."""
    marker = "claude_tui_failed token=abcdefghijklmnopqrstuv " + "y" * 3000
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: (
        1, "", marker, "fatal: something broke"
    ))
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list[str] = []
    pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert sink, "the untyped failure lost its detail"
    assert "abcdefghijklmnopqrstuv" not in sink[-1]
    assert len(sink[-1]) <= pi._LEG_DETAIL_MAX_CHARS


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


# --- board round 2 (agent-harness#1102) ------------------------------------------------

@pytest.mark.parametrize("body", [
    # codex r2: a reviewer line that BEGINS with a sourced fragment and goes on
    "App-server socket directory must be a user-owned directory with mode 0700; this "
    "implementation enforces that requirement correctly.\nAGREE",
    # grok r2
    "error building bubblewrap command is now classified before the early-OK path.\n\nAGREE",
    # claude r2 F2
    "Error building bubblewrap command output is now typed DEGRADED before the early-OK.\n\nAGREE",
    "You've hit your usage limit handling is now typed, which is right.\n\nAGREE",
])
def test_review_line_that_starts_with_a_sourced_fragment_stays_ok(body):
    assert pi._classify_leg(0, body, body, mode="review") == "OK"


@pytest.mark.parametrize("mode,suffix", [("advisory", ""), ("review", "\n\nAGREE")])
def test_temp_dir_path_with_spaces_is_still_detected(mode, suffix):
    body = (
        "Temp directory /tmp/claude cache is owned by uid 65534, expected 0. Refusing to use it"
        + suffix
    )
    assert pi._classify_leg(0, body, "", mode=mode) == "DEGRADED"


@pytest.mark.parametrize("mode", ["review", "advisory", "president"])
def test_usage_banner_plus_verdict_is_not_a_review(mode):
    """grok r2 FAIL-OPEN: in review mode the usage body check ran only for non-review
    modes and after the early-OK, so banner + AGREE was OK."""
    body = "You've hit your usage limit. Upgrade to Plus to continue using Codex\n\nAGREE"
    assert pi._classify_leg(0, body, "", mode=mode) == "DEGRADED"


def test_review_mode_usage_banner_body_with_nonzero_rc_is_typed_degraded():
    """claude r2 F1: grok prints its banner on stdout; review mode used to leave it ERROR."""
    assert pi._classify_leg(1, "You hit your weekly limit.", "", mode="review") == "DEGRADED"


def _no_8char_piece(token: str, text: str) -> bool:
    return all(token[k:k + 8] not in text for k in range(len(token) - 7))


@pytest.mark.parametrize("prefix,token,pad", [
    # codex r2's exact input: the 600-char cut lands inside the token
    (b"fatal: rejected ", "xai-abcdefghijklmnopqrst", 579),
    # claude r3: the Bearer half must actually straddle the cut (587 pads, not 590)
    (b"auth Bearer ", "abcdefghijklmnopqrstuvwx", 587),
])
def test_pty_tail_redacts_a_token_that_straddles_the_cut(prefix, token, pad):
    """codex r2: the 600-char cut ran BEFORE the token patterns, stranding a suffix after
    removing the prefix the pattern needs."""
    raw = prefix + token.encode() + b" " + b"y" * pad
    unredacted = raw.decode()[-600:]
    assert token[-8:] in unredacted and token[:8] not in unredacted, "the cut must straddle"
    tail = pi._sanitized_pty_tail(raw)
    assert _no_8char_piece(token, tail), tail[:60]


@pytest.mark.parametrize("body", [
    "You've reached your context limit. Trim the prompt and retry with a smaller diff so the "
    "seat can finish.",
    "out of credits handling: the seat should retry later with a smaller bundle, please.",
    "The agy stream reported STOP_REASON_QUOTA_EXHAUSTED once, which the adapter handles.",
])
def test_advisory_prose_near_a_sourced_sentence_stays_ok(body):
    assert pi._classify_leg(0, body, body, mode="advisory") == "OK"


def test_only_the_sourced_model_name_counts_for_reached_your_limit():
    assert pi._PROVIDER_USAGE_LIMIT_RE.search("You've reached your Fable limit.")
    assert not pi._PROVIDER_USAGE_LIMIT_RE.search("You've reached your context limit.")
    # agy prints "Out of credits"; grok's lowercase matcher-list entry is not printed output
    assert pi._PROVIDER_USAGE_LIMIT_RE.search("Out of credits")
    assert not pi._PROVIDER_USAGE_LIMIT_RE.search("out of credits")


def test_env_failure_with_a_markup_verdict_line_is_degraded():
    """claude r2: the verdict-line test is terminal_verdict's parser, so markup verdicts
    `_completion_ok` accepts are verdict lines here too."""
    body = CODEX_BWRAP_FAILURE + "\n\n**Verdict:** AGREE"
    assert pi.terminal_verdict(body) is not None
    assert pi._classify_leg(0, body, "", mode="review") == "DEGRADED"


def test_an_indented_echoed_line_in_the_tail_does_not_type_the_failure():
    """claude r2: a test docstring / prompt line with leading spaces inside the 20-line
    window used to type a stream disconnect as a usage limit."""
    log = (
        "user\n    ERROR: You've hit your usage limit. Visit "
        "https://chatgpt.com/codex/settings/usage to purchase more credits.\n"
        "ERROR: stream disconnected before completion: connection reset\n"
    )
    status = pi._classify_leg(1, "", log)
    assert status == "ERROR"
    assert pi._leg_failure_detail(status, 1, "", log) == (
        "ERROR: stream disconnected before completion: connection reset"
    )


def _claude_session(monkeypatch, result):
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: result)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)


def test_claude_pty_prose_quoting_a_sentence_does_not_retype_a_leg_with_text(monkeypatch, tmp_path):
    """claude r2 F4: the Claude seat's on-screen review prose can quote a sourced sentence;
    with review text present the tail is matched only as whole CLI lines and the status is
    left alone."""
    _claude_session(monkeypatch, (
        1, "partial review mentioning the classifier", "claude_tui_pty_eof_no_output",
        "…maps Usage limit reached to DEGRADED…",
    ))
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list[str] = []
    status, _ = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert status == "ERROR", "a leg WITH review text was retyped from its on-screen prose"
    assert not any(d.startswith("provider_") for d in sink)


def test_direct_default_spawn_returns_the_claude_sink_detail(monkeypatch):
    """claude r2 F5: the `_default_spawn` claude branch's sink wiring, end to end."""
    _claude_session(monkeypatch, (
        1, "", "claude_tui_pty_eof_no_output",
        pi._sanitized_pty_tail(CLAUDE_TMPDIR_REFUSAL.encode()),
    ))
    spawned = pi._default_spawn("claude", "ARTIFACT", mode="review")
    assert len(spawned) == 3, spawned
    status, _text, detail = spawned
    assert status == "DEGRADED"
    assert detail.startswith("provider_environment_failure: Temp directory /tmp/claude-0")


def test_cli_prints_the_finalized_detail(tmp_path):
    """claude r2 F6: a detail from ANY route (here a raw exception string) is sanitized at
    the print site."""
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    real_compose = comp_mod.compose_review_board
    raw = "boom \x1b[2J token=abcdefghijklmnopqrstuv " + "q" * 3000
    result = pi.PanelResult(legs=(
        pi.PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:a"),
        pi.PanelLegResult(leg="gemini", status="OK", text="AGREE", seat_key="gemini:a"),
        pi.PanelLegResult(leg="claude", status="OK", text="AGREE", seat_key="claude:a"),
        pi.PanelLegResult(leg="codex", status="DEGRADED", text="", detail=raw, seat_key="codex:a"),
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
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli_main(["advisor-board", str(artifact)])
    for stream in (out.getvalue(), err.getvalue()):
        codex_lines = [line for line in stream.splitlines() if "codex:a" in line]
        assert codex_lines, stream
        for line in codex_lines:
            assert "\x1b" not in line and "abcdefghijklmnopqrstuv" not in line
            assert len(line) <= pi._LEG_DETAIL_MAX_CHARS + 80



# --- board round 3 (agent-harness#1102) ------------------------------------------------

def test_body_mixing_usage_and_env_lines_is_a_failure():
    """codex r3: each kind's check rejected the other kind's line, so the mixed body got
    the early-OK."""
    body = (
        "You've hit your usage limit. Upgrade to Plus to continue using Codex\n"
        + CODEX_BWRAP_FAILURE + "\nAGREE"
    )
    assert pi._classify_leg(0, body, "", mode="review") == "DEGRADED"
    assert pi._leg_failure_detail("DEGRADED", 0, body, "").startswith("provider_usage_limit")


def test_temp_dir_path_cannot_swallow_reviewer_prose():
    """codex r3: the open path capture took "…checks pass; expected diagnostic: Temp directory
    /tmp/claude" as the path."""
    body = (
        "Temp directory /tmp/claude checks pass; expected diagnostic: Temp directory "
        "/tmp/claude is owned by uid 65534, expected 0. Refusing to use it\nAGREE"
    )
    assert pi._classify_leg(0, body, "", mode="review") == "OK"
    # the other direction: a real path with spaces is still a path
    real = "Temp directory /tmp/claude cache dir is owned by uid 65534, expected 0. Refusing to use it"
    assert pi._classify_leg(0, real, "", mode="advisory") == "DEGRADED"


def test_codex_exact_advisory_log_with_prompt_echo_stays_ok():
    """codex r3's exact log: an unindented sourced line INSIDE the echoed user block."""
    log = (
        "user\nExample failure:\nYou've hit your usage limit. Upgrade to Plus to continue "
        "using Codex\ncodex\nThe patch handles temporary directories correctly.\n"
    )
    body = "The patch handles temporary directories correctly."
    assert pi._classify_leg(0, body, log, mode="advisory") == "OK"


def test_codex_leg_elides_its_prompt_echo_before_classification(monkeypatch, tmp_path):
    """The production codex path: a bundle whose LAST line is a column-0 `ERROR: <banner>`
    (the residual `_provider_output_tail` cannot tell apart) is elided by `_exec_leg`, so a
    stream disconnect is not typed as a usage limit."""
    class _Proc:
        def __init__(self, stderr):
            self.returncode, self.stdout, self.stderr = 1, "", stderr

    def fake(cmd, **kw):
        prompt = kw["input_text"]
        return _Proc("user\n" + prompt + "\nERROR: stream disconnected before completion: reset\n")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda leg, env: (True, ""))
    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("x")
    # Brokered: the sealed prompt carries the bundle INLINE (the unbrokered prompt is only a
    # pointer to the staged file), so this is the route where a bundle is echoed.
    monkeypatch.setattr(pi, "_brokered_codex_command", lambda **kw: ["codex", "exec", "-"])
    monkeypatch.setattr(pi, "_record_broker_provider_evidence", lambda *a, **k: None)
    sealed = "Review this.\nThe bundle.\nERROR: You've hit your usage limit. Try again later."
    seen: list[str] = []
    real_fake = fake

    def recording(cmd, **kw):
        seen.append(kw["input_text"])
        return real_fake(cmd, **kw)

    monkeypatch.setattr(pi, "_run_leg_with_liveness", recording)
    rc, text, log = pi._exec_leg(
        "codex", review_dir, out_dir, timeout_s=60, artifact="A", env={}, broker_prompt=sealed,
    )
    assert seen and "You've hit your usage limit" in seen[0], "the test must echo the banner"
    assert "You've hit your usage limit" not in log
    status = pi._classify_leg(rc, text, log)
    assert status == "ERROR"
    assert pi._leg_failure_detail(status, rc, text, log) == (
        "ERROR: stream disconnected before completion: reset"
    )


_CODEX_PLANS = {
    "bare": "You've hit your usage limit.",
    "plus": "You've hit your usage limit. Upgrade to Plus to continue using Codex "
            "(https://chatgpt.com/explore/plus),",
    "pro": "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
           "visit https://chatgpt.com/codex/settings/usage to purchase more credits",
    "team": "You've hit your usage limit. To get more access now, send a request to your admin",
}
_CODEX_RESETS = {
    # codex error.rs retry_suffix / retry_suffix_after_or; both forms are in the binary
    "none": (" Try again later.", " or try again later.", None),
    "same_day": (" Try again at 3:05 PM.", " or try again at 3:05 PM.", "3:05 PM"),
    "dated": (" Try again at Oct 1st, 2026 1:42 PM.", " or try again at Oct 1st, 2026 1:42 PM.",
              "Oct 1st, 2026 1:42 PM"),
}


@pytest.mark.parametrize("plan", sorted(_CODEX_PLANS))
@pytest.mark.parametrize("reset", sorted(_CODEX_RESETS))
def test_codex_usage_banner_every_plan_and_reset_form(plan, reset):
    """claude r3 B1: the same-day and no-reset forms (the common 5-hour window) regressed
    to a bare ERROR / OK when the datetime was mandatory."""
    bare_suffix, or_suffix, when = _CODEX_RESETS[reset]
    banner = _CODEX_PLANS[plan] + (bare_suffix if plan == "bare" else or_suffix)
    log = "user\n<prompt echo elided>\nERROR: " + banner + "\n"
    status = pi._classify_leg(1, "", log)
    assert status == "DEGRADED", banner
    detail = pi._leg_failure_detail(status, 1, "", log)
    label = f"provider_usage_limit (resets {when}): " if when else "provider_usage_limit: "
    assert detail.startswith(label), (banner, detail)
    for mode in ("review", "advisory"):
        assert pi._classify_leg(0, banner + "\n\nAGREE", "", mode=mode) == "DEGRADED", banner


@pytest.mark.parametrize("home", ["/Users/Jane Doe/Library/Caches/claude", "/home/Jane Doe/.cache/claude"])
def test_home_segment_with_spaces_is_redacted_whole(home):
    """grok r3 BLOCKING: the one-word home segment regex left `~/ Doe/…`."""
    line = f"Temp directory {home} is owned by uid 501, expected 0. Refusing to use it"
    detail = pi._leg_failure_detail("DEGRADED", 1, "", line)
    assert detail.startswith("provider_environment_failure: Temp directory ~/")
    assert "Jane" not in detail and "Doe" not in detail, detail
