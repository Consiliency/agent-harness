"""agent-harness#1096 (+ the env-failure-as-OK half of agent-harness#1098 item 2).

On 2026-09-26 every brokered codex seat died about 9 s after launch with

    ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to
    purchase more credits or try again at Oct 1st, 2026 1:42 PM.

and the board reported a bare ``codex ERROR`` with ``detail=None``. On dev0 a codex seat
returned ``OK`` whose text was a bubblewrap environment failure.

The design these tests pin (agent-harness#1102 round 5):
  * OUTCOME — a leg is OK only with rc 0 plus its mode's success artifact; free text never
    decides or demotes an outcome.
  * LABEL — a failed leg's ``detail`` carries ``<failure_kind>: <the CLI's line>``; a wrong
    label is cosmetic.
  * REDACTION — known values (home, user, the seat's paths) and known credential shapes.

They drive the classifier AND the production seams that carry ``detail``: the direct
spawn, the brokered spawn (fake broker transport, real ``_parent_infer`` / ``_exec_leg`` /
``_run_leg_with_liveness`` and a real subprocess), the claude TUI sink, the governed-review
consequence, and the board's summary output.
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


_REAL_REDACTION_IDENTITY = pi._redaction_identity


@pytest.fixture(autouse=True)
def _fixed_identity(monkeypatch):
    """Host independence (agent-harness#1102 r5): the redactor substitutes the RUNNING
    user's home and name, so every test runs as one fixed fake identity — no assertion may
    pass or fail because of who runs the suite. The one test of the real lookup calls
    ``_REAL_REDACTION_IDENTITY`` directly."""
    monkeypatch.setattr(pi, "_redaction_identity", lambda: (("/home/pl-tester",), ("pl-tester",)))


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


def test_server_capacity_is_not_a_usage_limit():
    """MODEL_CAPACITY_EXHAUSTED is the provider's capacity, not the account's quota."""
    assert not pi._USAGE_LIMIT_LABEL_RE.search("MODEL_CAPACITY_EXHAUSTED")


def test_conforming_review_that_discusses_limits_stays_ok():
    """The ah#252 invariant: prose ABOUT limits/auth is subject matter, not a failure —
    even when codex echoes that prose into its log."""
    log = CODEX_LOG.replace(CODEX_USAGE_BANNER, CONFORMING_REVIEW_ABOUT_LIMITS)
    status = pi._classify_leg(0, CONFORMING_REVIEW_ABOUT_LIMITS, log, mode="review")
    assert status == "OK"
    assert pi._leg_failure_detail(status, 0, CONFORMING_REVIEW_ABOUT_LIMITS, log) is None


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
    assert pi._finalize_leg_detail(detail) == "usage_limit (resets 13:42, Oct 1 2026)"


def test_brokered_codex_conforming_review_about_limits_is_ok_without_detail(monkeypatch, tmp_path):
    spawned = _brokered_codex(monkeypatch, tmp_path, f"""
        import sys
        sys.stdin.read()
        review = {CONFORMING_REVIEW_ABOUT_LIMITS!r}
        sys.stderr.write("user\\nprompt\\ncodex\\n" + review + "\\n")
        open(sys.argv[1], "w").write(review)
    """)
    assert tuple(spawned) == ("OK", CONFORMING_REVIEW_ABOUT_LIMITS)


def test_claude_tui_ok_leaves_the_sink_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: (
        0, "Looks fine.\n\nAGREE", "claude_tui_file_output", ""
    ))
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list = []
    status, _text = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert status == "OK" and sink == []


def test_board_stderr_summary_names_why_a_seat_failed(tmp_path):
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    real_compose = comp_mod.compose_review_board
    detail = pi._HarnessCode("usage_limit (resets 13:42, Oct 1 2026)")
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


def _claude_session(monkeypatch, result):
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: result)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)


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
    failure = pi._leg_failure_detail(status, rc, text, log)
    assert pi._finalize_leg_detail(failure) == "unknown failure (exit 1); CLI output not retained"
    assert "You've hit your usage limit" not in failure.raw, "the elided echo must not reach the log"


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
    "same_day": (" Try again at 3:05 PM.", " or try again at 3:05 PM.", "15:05"),
    "dated": (" Try again at Oct 1st, 2026 1:42 PM.", " or try again at Oct 1st, 2026 1:42 PM.",
              "13:42, Oct 1 2026"),
}


ADVISORY_OK = (
    "The plan holds up; the main risk is the migration window, so stage it behind a flag.\n\n"
    "RECOMMENDATION: ship behind a feature flag and migrate in two steps."
)


# --- OUTCOME: positive evidence of success only --------------------------------------------

@pytest.mark.parametrize("mode", ["review", "advisory", "president"])
@pytest.mark.parametrize("body", [
    CODEX_BWRAP_FAILURE,                                   # the agent-harness#1098 dev0 text
    CLAUDE_TMPDIR_REFUSAL,
    # round 4's fail-open input: a valid path the old whole-line regex no longer matched
    "Temp directory /tmp/claude; cache is owned by uid 65534, expected 0. Refusing to use it",
    "You've hit your usage limit. Try again later.",
    "A long, fluent, entirely unsourced failure message the CLI printed instead of a review.",
    "",
])
def test_rc0_without_the_success_artifact_is_never_ok(mode, body):
    """agent-harness#1098 by construction: no text scan, no wording list — a leg that did not
    produce its artifact failed, whatever it printed and whatever its exit code."""
    assert pi._classify_leg(0, body, "", mode=mode) != "OK"
    assert pi._classify_leg(1, body, "", mode=mode) != "OK"


_PROVIDER_PROSE = (
    CONFORMING_REVIEW_ABOUT_LIMITS.rsplit("\n", 1)[0],
    "The `error building bubblewrap command` diagnostic is handled correctly.",
    CODEX_BWRAP_FAILURE,
    "Temp directory /tmp/claude checks pass; expected diagnostic: " + CLAUDE_TMPDIR_REFUSAL,
    "You've hit your usage limit. Try again later. 401 Unauthorized: please log in again.",
)
_ARTIFACT_LINE = {
    "review": "**Verdict:** DISAGREE",
    "advisory": "RECOMMENDATION: fix the classifier first.",
    "president": "FORCING DECISION: land after the fix.",
}


@pytest.mark.parametrize("mode", sorted(_ARTIFACT_LINE))
@pytest.mark.parametrize("prose", _PROVIDER_PROSE)
def test_a_conforming_artifact_is_ok_whatever_its_text_mentions(mode, prose):
    """Free text never demotes an OK leg, in ANY mode (claude r5: advisory and president are
    exactly the modes that lost the auth-first scan). A body ending in its mode's artifact
    IS the artifact, even when its prose is — or quotes — provider wording."""
    body = prose + "\n\n" + "Substantive analysis of the change. " * 2 + "\n" + _ARTIFACT_LINE[mode]
    assert pi._classify_leg(0, body, body, mode=mode) == "OK"
    assert pi._leg_failure_detail("OK", 0, body, body) is None


@pytest.mark.parametrize("mode", sorted(_ARTIFACT_LINE))
def test_a_conforming_artifact_with_nonzero_rc_is_never_ok(mode):
    """I1's rc condition (claude r5): the artifact is necessary, not sufficient."""
    body = "Substantive analysis of the change. " * 2 + "\n" + _ARTIFACT_LINE[mode]
    assert pi._classify_leg(0, body, "", mode=mode) == "OK"
    for rc in (1, 2, -9, None):
        assert pi._classify_leg(rc, body, "", mode=mode) != "OK", rc


def test_a_missing_rc_is_an_error_not_a_crash():
    """claude r5: `rc < 0` raised TypeError for rc None; main returned ERROR."""
    assert pi._classify_leg(None, "", "") == "ERROR"
    assert pi._leg_failure_kind(None, "", "") == "unknown"


def test_advisory_ok_requires_its_recommendation_line():
    """Advisory's success artifact (round 5): >= 40 chars ending in `RECOMMENDATION: …`.
    Before, any 40 characters passed, so a CLI banner could read as an advisory."""
    assert pi._classify_leg(0, ADVISORY_OK, "", mode="advisory") == "OK"
    no_line = ADVISORY_OK.rsplit("\n", 1)[0]
    assert len(no_line) >= 40
    assert pi._classify_leg(0, no_line, "", mode="advisory") == "DEGRADED"
    assert pi._classify_leg(0, "RECOMMENDATION:", "", mode="advisory") != "OK"
    assert pi._classify_leg(0, "- **RECOMMENDATION:** " + "x" * 40, "", mode="advisory") == "OK"


def test_advisory_instructions_ask_for_the_artifact():
    assert "RECOMMENDATION:" in pi._ADVISORY_INSTRUCTIONS


def test_advisory_with_a_banner_in_its_log_stays_ok():
    """A codex advisory whose echoed log carries a banner is still an advisory: the log only
    ever labels a failure."""
    log = "user\nExample failure:\n" + CODEX_USAGE_BANNER + "\ncodex\n" + ADVISORY_OK + "\n"
    assert pi._classify_leg(0, ADVISORY_OK, log, mode="advisory") == "OK"


def test_env_failure_as_the_whole_body_fails_closed_and_is_labeled(monkeypatch):
    """The 1098 shape through the production spawn: rc 0, the env text as the body, no
    verdict → failed. Its text is kept, so the governed gate reads a non-conforming review
    (BLOCK, fail-closed), and the detail is labeled env_failure."""
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (0, CODEX_BWRAP_FAILURE, CODEX_BWRAP_FAILURE))
    leg = pi.invoke_panel("ARTIFACT", ["codex"]).legs[0]
    assert leg.status == "DEGRADED"
    assert leg.detail and leg.detail.startswith("env_failure: ")
    findings = gr._findings_from_panel(pi.PanelResult(legs=(leg,)))
    assert any(f.code == "panel_nonconforming" and f.severity == "block" for f in findings)


def test_a_usage_banner_on_stdout_with_nonzero_rc_is_labeled():
    """grok / agy print the banner on stdout (the body), not stderr."""
    status = pi._classify_leg(1, "You hit your weekly limit.", "", mode="review")
    assert status == "DEGRADED"
    assert pi._finalize_leg_detail(
        pi._leg_failure_detail(status, 1, "You hit your weekly limit.", "")
    ) == "usage_limit"


# --- LABEL: on failed legs only, cosmetic --------------------------------------------------

@pytest.mark.parametrize("line", [
    CODEX_USAGE_BANNER,
    "You've hit your usage limit. Upgrade to Plus to continue using Codex",
    "Quota exceeded. Check your plan and billing details.",
    "You hit your spend cap set by the owner of your workspace.",
    "You've hit your monthly spend limit.",
    "You've hit your team's shared budget. Switch to another model",
    "You've reached your Fable limit.",
    "Usage limit reached",
    "You're out of usage credits.",
    "You hit your free usage limit.",
    "You hit your weekly limit.",
    "You've hit the rate limit for your plan. Upgrade your account or try again later.",
    "You've reached your free Grok Build usage limit for now.",
    "AI: Out of credits",
    "Quota exhausted",
    "stop_reason: STOP_REASON_QUOTA_EXHAUSTED",
])
def test_sourced_usage_wording_labels_usage_limit(line):
    assert pi._leg_failure_kind(1, "", "user\nprompt\n" + line) == "usage_limit"


@pytest.mark.parametrize("line", [
    CODEX_BWRAP_FAILURE,
    CLAUDE_TMPDIR_REFUSAL,
    "Temp directory /tmp/claude; cache is owned by uid 65534, expected 0. Refusing to use it",
    "Temp directory /tmp/x is not a directory (may be an attacker-planted symlink). Refusing to use it.",
])
def test_sourced_env_wording_labels_env_failure(line):
    assert pi._leg_failure_kind(1, "", line) == "env_failure"


def test_a_recovered_per_minute_429_is_not_a_usage_limit():
    line = '[{"error":{"code":429,"status":"RESOURCE_EXHAUSTED"}}]'
    assert not pi._USAGE_LIMIT_LABEL_RE.search(line)
    assert pi._leg_failure_kind(1, "", line) == "unknown"


def test_process_facts_label_before_text():
    assert pi._leg_failure_kind(124, "", CODEX_USAGE_BANNER) == "timeout"
    assert pi._leg_failure_kind(-9, "", CODEX_USAGE_BANNER) == "signal"


def test_usage_limit_banner_is_labeled_with_a_rerendered_reset():
    """The reset time is PARSED and RE-RENDERED by us (agent-harness#1102 r7) — never copied."""
    status = pi._classify_leg(1, "", CODEX_LOG)
    assert status == "DEGRADED"
    detail = pi._finalize_leg_detail(pi._leg_failure_detail(status, 1, "", CODEX_LOG))
    assert detail == "usage_limit (resets 13:42, Oct 1 2026)"


def test_codex_banner_followed_by_its_last_message_warning_is_labeled():
    """claude r4 B1: codex prints `Warning: no last agent message; …` AFTER the banner on a
    failed turn; round 4's tail dropped the banner and the leg went back to a bare ERROR."""
    log = (
        "user\n<prompt echo elided>\n"
        "ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
        "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again "
        "at Oct 1st, 2026 1:42 PM.\n"
        "Warning: no last agent message; wrote empty content to /tmp/pl-panel-x/out/last.md\n"
    )
    status = pi._classify_leg(1, "", log)
    assert status == "DEGRADED"
    assert pi._finalize_leg_detail(pi._leg_failure_detail(status, 1, "", log)) == (
        "usage_limit (resets 13:42, Oct 1 2026)"
    )


@pytest.mark.parametrize("plan", sorted(_CODEX_PLANS))
@pytest.mark.parametrize("reset", sorted(_CODEX_RESETS))
def test_codex_usage_banner_every_plan_and_reset_form(plan, reset):
    bare_suffix, or_suffix, when = _CODEX_RESETS[reset]
    banner = _CODEX_PLANS[plan] + (bare_suffix if plan == "bare" else or_suffix)
    log = "user\n<prompt echo elided>\nERROR: " + banner + "\n"
    status = pi._classify_leg(1, "", log)
    assert status == "DEGRADED", banner
    detail = pi._finalize_leg_detail(pi._leg_failure_detail(status, 1, "", log))
    assert detail == (f"usage_limit (resets {when})" if when else "usage_limit"), (banner, detail)


def test_direct_spawn_carries_labeled_detail_and_stays_a_warn(monkeypatch):
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", CODEX_LOG))
    leg = pi.invoke_panel("ARTIFACT", ["codex"]).legs[0]
    assert leg.status == "DEGRADED"
    assert not leg.text.strip(), "a diagnostic leaked into text (governed BLOCK)"
    assert leg.detail == "usage_limit (resets 13:42, Oct 1 2026)"
    findings = gr._findings_from_panel(pi.PanelResult(legs=(leg,)))
    assert [f.code for f in findings] == ["panel_leg_degraded"]
    assert "usage_limit" in findings[0].reason


def test_claude_tui_refusal_reaches_the_detail_sink(monkeypatch, tmp_path):
    _claude_session(monkeypatch, (
        1, "", "claude_tui_pty_eof_no_output", pi._sanitized_pty_tail(CLAUDE_TMPDIR_REFUSAL.encode())
    ))
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list = []
    status, _text = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert status == "DEGRADED"
    assert sink and pi._finalize_leg_detail(sink[-1]) == (
        "env_failure: temp dir owned by another account (uid 65534)"
    )


def test_direct_default_spawn_returns_the_claude_sink_detail(monkeypatch):
    _claude_session(monkeypatch, (
        1, "", "claude_tui_pty_eof_no_output",
        pi._sanitized_pty_tail(CLAUDE_TMPDIR_REFUSAL.encode()),
    ))
    spawned = pi._default_spawn("claude", "ARTIFACT", mode="review")
    assert len(spawned) == 3, spawned
    status, _text, detail = spawned
    assert status == "DEGRADED"
    assert pi._finalize_leg_detail(detail) == (
        "env_failure: temp dir owned by another account (uid 65534)"
    )


# --- REDACTION: known values --------------------------------------------------------------


def test_the_real_identity_is_what_the_host_reports():
    """The real lookup, on whatever host runs it (claude r6: it failed for HOME=/ and for a
    host with no passwd entry and no USER/LOGNAME). It returns only usable values: no empty
    or root home, no empty name; and the process home is among them when it is usable."""
    import os
    homes, users = _REAL_REDACTION_IDENTITY()
    assert all(h and h != "/" and not h.endswith("/") for h in homes), homes
    assert all(u for u in users), users
    home = os.path.expanduser("~").rstrip("/")
    if home and home != "~":
        assert home in homes


def test_the_real_identity_tolerates_a_bare_host(monkeypatch):
    """HOME=/, no passwd entry, no USER/LOGNAME: nothing to redact, and no crash."""
    import os
    import pwd
    monkeypatch.setenv("HOME", "/")
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError(uid)))
    assert _REAL_REDACTION_IDENTITY() == ((), ())
    assert os.path.expanduser("~") == "/"


# --- the advisory RECOMMENDATION artifact (lead conditions for option A) -------------------

def test_advisory_banner_falsifier():
    """A 40+ character provider banner with rc 0 and no RECOMMENDATION line is a failure in
    advisory mode — the exact fail-open the old `len >= 40` rule had."""
    banner = "You've hit the rate limit for your plan. Upgrade your account or try again later."
    assert len(banner) >= 40
    assert pi._classify_leg(0, banner, "", mode="advisory") != "OK"


@pytest.mark.parametrize("text,value", [
    ("advice\nRECOMMENDATION: go", "go"),
    ("advice\n**RECOMMENDATION**: go", "go"),           # colon outside the bold (r5)
    ("advice\n**RECOMMENDATION:** ship it", "ship it"),
    ("advice\n  recommendation:  do x  ", "do x"),
    ("advice\n- RECOMMENDATION: a", "a"),
    ("advice\nRECOMMENDATION:", None),                  # empty value
    ("advice\nRECOMMENDATION: go\n\nThanks, happy to help!", None),  # a sign-off after it
    ("RECOMMENDATION: go\nadvice after it", None),      # not the last line
])
def test_recommendation_parse_mirrors_the_verdict_parse(text, value):
    assert pi._advisory_recommendation(text) == value


def test_a_sign_off_fails_verdict_and_recommendation_alike():
    """Same parse shape: a line after the artifact defeats both."""
    assert pi.terminal_verdict("review\nAGREE\nThanks!") is None
    assert pi._advisory_recommendation("advice\nRECOMMENDATION: go\nThanks!") is None


def test_every_advisory_prompt_asks_for_the_recommendation_line(tmp_path):
    assert "RECOMMENDATION:" in pi._ADVISORY_INSTRUCTIONS
    assert "RECOMMENDATION:" in pi._ADVISORY_VERDICT_CONTRACT
    tui = pi._render_claude_tui_prompt("A", tmp_path, tmp_path / "out.txt", mode="advisory")
    assert "RECOMMENDATION:" in tui


def test_president_without_a_forcing_decision_fails_even_when_long():
    body = "A long, careful ruling that weighs every seat's findings in depth. " * 20
    assert pi._classify_leg(0, body, "", mode="president") != "OK"
    assert pi._classify_leg(0, body + "\nFORCING DECISION: land it", "", mode="president") == "OK"


# --- board round 5 (agent-harness#1102): redaction ORDER and the detail chokepoint -----------


def test_claude_tui_status_does_not_depend_on_the_sink(monkeypatch, tmp_path):
    """claude r5: the ERROR→DEGRADED rewrite ran only when a sink was passed."""
    _claude_session(monkeypatch, (
        1, "", "claude_tui_pty_eof_no_output", pi._sanitized_pty_tail(CLAUDE_TMPDIR_REFUSAL.encode())
    ))
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    with_sink, _ = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=[],
    )
    without_sink, _ = pi._exec_claude_tui_leg(tmp_path / "review", tmp_path / "out", 30, "bundle", env={})
    assert with_sink == without_sink == "DEGRADED"


@pytest.mark.parametrize("marker,tail,expected", [
    # auth now labels too (claude r5)
    ("claude_tui_pty_eof_no_output", "Error: not logged in · Please run /login", "DEGRADED"),
    # an existing DEGRADED typed-operational status is left alone, not rewritten
    ("claude_tui_stalled", "Usage limit reached", "DEGRADED"),
])
def test_claude_tui_rewrites_only_error_or_empty(monkeypatch, tmp_path, marker, tail, expected):
    _claude_session(monkeypatch, (1, "", marker, tail))
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    status, _ = pi._exec_claude_tui_leg(tmp_path / "review", tmp_path / "out", 30, "bundle", env={})
    assert status == expected


@pytest.mark.parametrize("body,expected", [
    (ADVISORY_OK, "OK"),
    (ADVISORY_OK.rsplit("\n", 1)[0], "DEGRADED"),
])
def test_claude_tui_advisory_ok_goes_through_the_artifact_rule(monkeypatch, tmp_path, body, expected):
    """claude r5: confirm the TUI's OK decision is `_completion_ok(text, "advisory")`."""
    _claude_session(monkeypatch, (0, body, "claude_tui_file_output", ""))
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    status, _ = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, mode="advisory",
    )
    assert status == expected


# --- board round 6 (agent-harness#1102): span-union redaction --------------------------------

TOK = "abcdefghijklmnopqrstuvwx"


def test_a_seat_path_crossing_the_pty_cut_is_redacted_first():
    """codex r6: the PTY tail was cut BEFORE seat paths were substituted, so the cut left
    `seat-private/review/…`."""
    raw = b"fatal: /srv/seat-private/review/" + b"y" * 580
    tail = pi._sanitized_pty_tail(raw, known=("/srv/seat-private/review",))
    assert "seat-private" not in tail, tail[:40]


def test_the_tui_passes_its_seat_paths_into_the_first_redaction(monkeypatch, tmp_path):
    seen = {}

    def session(**kw):
        seen.update(kw)
        return 1, "", "claude_tui_pty_eof_no_output", ""

    _claude_session(monkeypatch, (1, "", "x", ""))
    monkeypatch.setattr(pi, "_run_claude_tui_session", session)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    pi._exec_claude_tui_leg(tmp_path / "review", tmp_path / "out", 30, "bundle", env={})
    paths = [str(p) for p in seen.get("redaction_paths", ())]
    assert str(tmp_path / "review") in paths and str(tmp_path / "out") in paths


# A seeded property test: each secret, embedded at random offsets in random text, with the
# separators next to it randomly rewritten (spaces, tabs, newlines, CR, CSI, controls, case),
# never survives finalize, and finalize is a fixed point.




# --- board round 7 (agent-harness#1102): detail is OUR vocabulary only ----------------------
#
# Maintainer decision 2026-09-27: raw CLI text never enters `detail`. A detail is a harness
# code or a template whose only fields are validated (a re-rendered reset time, an exit code
# / signal number, a uid, a run-relative private-log name); the raw output goes to a PRIVATE
# 0600 per-leg log under the run's stream dir.

TOK = "abcdefghijklmnopqrstuvwx"
_REVIEWER_INPUTS = (
    # round 5
    f"Bearer\n{TOK}",
    f"OSError: [Errno 13] /home/jdoe/.local/bin/codex token={TOK}",
    "fatal: jane@janedoe.dev: request rejected",
    "fatal: /app-server failed; see /app/log",
    "fatal: cannot create /tmp/jdoe-codex/app.sock: File exists (owner jdoe.admin)",
    # round 6
    f"Authorization: Bearer\n{TOK}",
    f"fatal: request rejected (Authorization: Bearer {TOK})",
    f"Authorization: Basic {TOK}==",
    f'{{"access_token": "{TOK}"}}',
    f"auth header was Bearer\t{TOK}",
    f"auth header was Bearer\x1b[1C{TOK}",
    f"fatal: rejected sess-jane-{TOK}",
    f"fatal: rejected Bearer jane-{TOK}",
    "fatal: alice@jane.example.com denied",
    "fatal: john.doe@corp.com denied",
    f"fatal: sk-ant-api03-{TOK}",
    "fatal: <owner>jdoe</owner>",
    "signal: /app/app",
    "fatal: under /Users/Jane Doe.",
    "open file:///Users/Jane Doe/x failed",
    "fatal: /srv/seat-private/review/" + "y" * 580,
    # round 7
    f"ANTHROPIC_AUTH_TOKEN={TOK}",
    "db_password=hunter2hunter2hunter2",
    "see `/home/jdoe/.ssh/id_rsa`",
    "[/home/jdoe/x] <//home/jdoe/y> ,/home/jdoe/z;",
    f"fatal: sk-ant-api03-abc\x1b[0m{TOK}",
    f'token=Bearer "{TOK}"',
    f"{TOK}0123456789",
    "Bearer /home/J Doe/x",
)


def _longest_shared(a: str, b: str) -> int:
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = j - i
            else:
                break
    return best


@pytest.mark.parametrize("text", _REVIEWER_INPUTS)
@pytest.mark.parametrize("rc", [1, -9, 0])
def test_every_reviewer_input_yields_a_template_with_no_input_text(text, rc):
    """Every input rounds 5-7 used against the redactor now yields a detail from our own
    vocabulary; no run of 8+ characters of the CLI text reaches it."""
    failure = pi._leg_failure_detail("ERROR", rc, "", text)
    detail = pi._finalize_leg_detail(pi._resolve_leg_detail(failure, None, "codex"))
    assert detail is not None and pi._detail_is_valid(detail), detail
    assert _longest_shared(detail, text) < 8, (detail, text)


@pytest.mark.parametrize("detail", [
    "timeout", "signal 9", "auth_failure", "usage_limit", "usage_limit (resets 15:05)",
    "usage_limit (resets 13:42, Oct 1 2026)", "env_failure: temp dir owned by another account (uid 65534)",
    "env_failure: temp dir unusable", "env_failure: app-server socket dir not user-owned",
    "env_failure: sandbox command could not be built", "tool_denied: headless tool permission auto-denied",
    "unknown failure; CLI output not retained", "unknown failure (exit 2); CLI output: leg-logs/codex-0a1b2c3d4e5f0a1b2c3d4e5f.log",
    "claude_tui_pty_eof_no_output: unknown failure; CLI output not retained",
    "under_claude_code", "native_fill", "president_ruling_missing:president_invocation_failed",
    "timeout after 900s", "subscription_auth_unproven", "Gemini broker deadline exceeded",
])
def test_the_template_grammar_accepts_our_vocabulary(detail):
    """A detail WE built (typed provenance) that fits the grammar is kept as-is."""
    assert pi._detail_is_valid(detail)
    assert pi._finalize_leg_detail(pi._HarnessCode(detail)) == detail


@pytest.mark.parametrize("detail", [
    f"token={TOK}", "fatal: /home/jdoe/x", "usage_limit (resets 3:05 PM)", "usage_limit: You've hit",
    "env_failure: Temp directory /tmp/claude-0 is owned by uid 1", "signal 9; rm -rf /",
    "unknown failure; CLI output: /home/jdoe/run/leg-logs/x.log", "timeout after 900s /home/x",
    "unknown failure; CLI output: leg-logs/x.log",  # not our generator's `<harness>-<24 hex>.log`
    "unknown failure; CLI output: leg-logs/codex-0a1b2c3d4e5f.log",  # 12 hex: the old shape
    "unknown failure; CLI output: leg-logs/sk-ant-api03-0a1b2c3d4e5f0a1b2c3d4e5f.log",  # not a harness
    "unknown failure (exit \uff11); CLI output not retained",  # a non-ASCII digit (re.ASCII)
    "native_fill_refused:native_fill_digest_mismatch:claude:claude-opus-5-5:max:correctness",  # no seat
    "president_ruling_missing:ghp_abcdefghijklmnopqrstuv",  # an unenumerated token
    "claude_agent_state:idle; stop=ghp_abcdefghijklmnopqrstuv",  # no longer a template at all
    "claude_tui_pty_eof_no_output: fatal: boom",
])
def test_the_template_grammar_rejects_anything_else(detail):
    assert not pi._detail_is_valid(detail)
    assert pi._finalize_leg_detail(detail) == "unknown failure; CLI output not retained"
    # ... even when it arrives with harness provenance (the grammar is defense in depth)
    assert pi._finalize_leg_detail(pi._HarnessCode(detail)) == "unknown failure; CLI output not retained"


def test_the_gemini_broker_vocabulary_is_folded_into_the_template_set():
    assert pi._GEMINI_BROKER_DETAILS <= pi._HARNESS_DETAIL_CODES
    assert pi._TYPED_UNAVAILABLE_DETAILS <= pi._HARNESS_DETAIL_CODES


def test_env_failure_uid_is_a_validated_field(monkeypatch):
    failure = pi._leg_failure_detail(
        "ERROR", 1, "", "Temp directory /Users/Jane Doe is owned by uid 501, expected 0. Refusing to use it"
    )
    assert pi._finalize_leg_detail(failure) == "env_failure: temp dir owned by another account (uid 501)"


# The descriptor: validated on every write AND every read; no subclass may shadow it.

def test_object_setattr_cannot_store_a_raw_detail():
    leg = pi.PanelLegResult(leg="codex", status="ERROR", text="")
    object.__setattr__(leg, "detail", f"token={TOK}")
    assert leg.detail == "unknown failure; CLI output not retained"


def test_the_backing_slot_cannot_carry_a_raw_detail():
    """codex r7: `object.__setattr__(leg, "_detail", raw)` bypassed the setter."""
    leg = pi.PanelLegResult(leg="codex", status="ERROR", text="")
    object.__setattr__(leg, "_detail", f"token={TOK}")
    assert leg.detail == "unknown failure; CLI output not retained"
    leg.__dict__["_detail"] = "fatal: /home/jdoe/x"
    assert leg.detail == "unknown failure; CLI output not retained"
    import dataclasses
    assert dataclasses.asdict(leg)["detail"] == "unknown failure; CLI output not retained"


@pytest.mark.parametrize("shadow", ["detail", "_detail"])
def test_a_subclass_cannot_shadow_the_detail_chokepoint(shadow):
    with pytest.raises(TypeError):
        type("Shadow", (pi.PanelLegResult,), {shadow: None})


def test_a_raw_exception_is_an_unknown_failure_with_its_text_only_in_the_private_log(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError(f"cannot exec /home/jdoe/.local/bin/codex token={TOK}")
    monkeypatch.setattr(pi, "_exec_leg", boom)
    leg = pi.invoke_panel("ARTIFACT", ["codex"], stream_dir=tmp_path).legs[0]
    assert re.fullmatch(r"unknown failure; CLI output: leg-logs/codex-[0-9a-f]{24}\.log", leg.detail), leg.detail
    log = (tmp_path / leg.detail.rsplit(": ", 1)[1]).read_text()
    assert "cannot exec" in log and TOK not in log  # best-effort hygiene on the private log


# The private per-leg log.

_SECRET_RAW = f"user\nprompt\nfatal: provider exploded at /home/jdoe/x with Bearer {TOK}\n"


def _unknown_failure_panel(monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", _SECRET_RAW))
    return pi.invoke_panel("ARTIFACT", ["codex"], stream_dir=tmp_path).legs[0]


def test_an_unknown_failure_names_a_private_0600_log_in_a_0700_dir(monkeypatch, tmp_path):
    import stat as _stat
    leg = _unknown_failure_panel(monkeypatch, tmp_path)
    assert re.fullmatch(
        r"unknown failure \(exit 1\); CLI output: leg-logs/codex-[0-9a-f]{24}\.log", leg.detail
    ), leg.detail
    ref = leg.detail.rsplit(": ", 1)[1]
    log = tmp_path / ref
    assert _stat.S_IMODE(log.stat().st_mode) == 0o600
    assert _stat.S_IMODE((tmp_path / "leg-logs").stat().st_mode) == 0o700
    content = log.read_text()
    assert "provider exploded" in content


def test_the_private_log_never_reaches_the_verdict_json_or_governed_reasons(monkeypatch, tmp_path):
    leg = _unknown_failure_panel(monkeypatch, tmp_path)
    ref = leg.detail.rsplit(": ", 1)[1]
    absolute = str(tmp_path / ref)
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.name.endswith(".log"):
            body = path.read_text(errors="replace")
            assert absolute not in body and "provider exploded" not in body, path
    reason = gr._findings_from_panel(pi.PanelResult(legs=(leg,)))[0].reason
    assert "provider exploded" not in reason and absolute not in reason


def test_the_board_summary_carries_only_the_run_relative_name(monkeypatch, tmp_path):
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    leg = _unknown_failure_panel(monkeypatch, tmp_path)
    real_compose = comp_mod.compose_review_board
    result = pi.PanelResult(legs=(
        pi.PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:a"),
        pi.PanelLegResult(leg="gemini", status="OK", text="AGREE", seat_key="gemini:a"),
        pi.PanelLegResult(leg="claude", status="OK", text="AGREE", seat_key="claude:a"),
        pi.PanelLegResult(leg="codex", status="ERROR", text="", detail=leg.detail, seat_key="codex:a"),
    ))
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    for extra in ([], ["--json"]):
        with (
            unittest.mock.patch.object(comp_mod, "compose_review_board", side_effect=lambda *a, **k: real_compose(
                is_available=lambda v: v in {"codex", "gemini", "claude", "grok"})),
            unittest.mock.patch.object(pi, "invoke_board", return_value=result),
        ):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                cli_main(["advisor-board", str(artifact), *extra])
        both = out.getvalue() + err.getvalue()
        assert "provider exploded" not in both and str(tmp_path / "leg-logs") not in both


def test_without_a_run_dir_the_raw_output_is_not_retained(monkeypatch):
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", _SECRET_RAW))
    leg = pi.invoke_panel("ARTIFACT", ["codex"]).legs[0]
    assert leg.detail == "unknown failure (exit 1); CLI output not retained"


def test_a_planted_log_dir_is_never_followed_or_reused(monkeypatch, tmp_path):
    import os
    target = tmp_path / "elsewhere"
    target.mkdir()
    os.symlink(target, tmp_path / "leg-logs")
    leg = _unknown_failure_panel(monkeypatch, tmp_path)
    assert leg.detail == "unknown failure (exit 1); CLI output not retained"
    assert not any(target.iterdir())


def test_a_group_readable_log_dir_is_refused(monkeypatch, tmp_path):
    import os
    (tmp_path / "leg-logs").mkdir()
    os.chmod(tmp_path / "leg-logs", 0o750)
    leg = _unknown_failure_panel(monkeypatch, tmp_path)
    assert leg.detail == "unknown failure (exit 1); CLI output not retained"


# Negative: no sourced failure line (and no CLI prompt/flag line) parses as a verdict.

@pytest.mark.parametrize("line", [
    "Agree and continue", "--agree", "--agree --yes", "Agreed.", CODEX_USAGE_BANNER,
    CODEX_BWRAP_FAILURE, CLAUDE_TMPDIR_REFUSAL, "Usage limit reached", "You hit your weekly limit.",
    "Quota exhausted", "Out of credits", "401 Unauthorized: please log in again.",
])
def test_no_sourced_failure_line_parses_as_a_verdict(line):
    assert pi.terminal_verdict("some output\n" + line) is None
    assert pi._classify_leg(0, "some output\n" + line, "", mode="review") != "OK"


# Property: random CLI text containing secrets always yields a template detail.
_PROPERTY_SEED = 1102
_PROPERTY_CASES = 3000
_SEPARATORS = (" ", "  ", "\t", "\n", "\r\n", "\x1b[1C", "\x1b[0m ", "\x07", " \x00 ", "\x0b")
_FILLER = (
    "fatal:", "error", "request", "rejected", "while", "calling", "the", "API", "(", ")",
    "status=401", "retrying", "->", "[x]", "see", "log", "done.", "path", "at", ":", ",",
    "You've hit your usage limit.", "Try again at 3:05 PM.", "error building bubblewrap command:",
    "Temp directory /tmp/claude-0 is owned by uid 65534, expected 0. Refusing to use it",
)


def _random_cli_text(rng):
    body = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789")
                   for _ in range(rng.randint(20, 40)))
    sep = rng.choice(_SEPARATORS)
    secret = rng.choice([
        f"{rng.choice(['Bearer', 'bearer', 'Basic', 'token'])}{sep}{body}",
        f"Authorization:{rng.choice(['', ' '])}Bearer{sep}{body}",
        f"{rng.choice(['token', 'password', 'api_key', 'ANTHROPIC_AUTH_TOKEN', 'db_password'])}"
        f"{rng.choice(['=', ': ', ' = '])}{body}",
        f'"access_token":{rng.choice(["", " "])}"{body}"',
        f"{rng.choice(['sk-ant-api03-', 'xai-', 'ghp_', 'sess-'])}{body}",
        f"eyJ{body[:12]}.{body[12:]}.sig",
        f"{body[:10].lower()}.{body[10:18].lower()}@example-corp.com",
        f"/home/{body[:8].lower()}/x",
        body,  # a bare token: no scheme, key or prefix at all
    ])
    words = [rng.choice(_FILLER) for _ in range(rng.randint(0, 30))]
    words.insert(rng.randint(0, len(words)), secret)
    return "".join(w + rng.choice(_SEPARATORS) for w in words), body


def test_property_every_detail_is_a_template_and_carries_no_input_text():
    import random

    rng = random.Random(_PROPERTY_SEED)
    for case in range(_PROPERTY_CASES):
        text, body = _random_cli_text(rng)
        rc = rng.choice([1, 2, 0, -9, 124, None])
        failure = pi._leg_failure_detail("ERROR", rc, "", text)
        detail = pi._finalize_leg_detail(pi._resolve_leg_detail(failure, None, "codex"))
        if detail is None:
            continue
        assert pi._detail_is_valid(detail), (case, detail)
        assert body[:8] not in detail and body[-8:] not in detail, (case, repr(text), detail)
        assert _longest_shared(detail, text) < 12, (case, repr(text), detail)
        assert pi._finalize_leg_detail(detail) == detail



# --- board round 8 (agent-harness#1102): provenance by TYPE, closed tokens ------------------

_SECRET = "sk-ant-api03-abcdefghij0123456789"
# A CLI line or exception message that full-matches (or used to full-match) EACH harness /
# failure template, with a secret in a field. None may choose the detail.
_TEMPLATE_SHAPED_LINES = (
    f"claude_agent_state:Running; stop={_SECRET}",
    f"native_fill_refused:denied:{_SECRET}",
    f"native_fill_refused:native_fill_digest_mismatch:claude:{_SECRET}",
    "research_audit_denied",
    "president_ruling_missing:president_unavailable",
    "timeout after 900s",
    "skip: harness 'codex' not in live Omnigent catalog",
    "skip: no homebrew adapter for lane 'grok' — Omnigent-or-skip (ABDOMNI)",
    "omnigent auth: HTTP 401",
    "omnigent v0.4.0 lane=api_key",
    "slirp4netns exited (1) before the uplink was usable; the namespace has no network",
    "codex not logged in — run `codex login` (auth preflight failed)",
    "claude_tui_launch_error:OSError",
    f"unknown failure (exit 1); CLI output: leg-logs/{_SECRET}-0123456789ab.log",
    "usage_limit (resets 13:42, Oct 1 2026)",
    "env_failure: temp dir owned by another account (uid 1)",
    "signal 9",
)


@pytest.mark.parametrize("line", _TEMPLATE_SHAPED_LINES)
def test_a_cli_line_shaped_like_a_template_never_chooses_the_detail(line):
    """codex/claude/grok r8 B1: the single-line shortcut, `_exception_failure` and the TUI
    prefix accepted any line that full-matched a harness template. Now provenance is by
    TYPE: CLI output, exception text and PTY tails are never turned into a harness code."""
    for failure in (
        pi._leg_failure_detail("ERROR", 1, "", line),          # the CLI log channel
        pi._leg_failure_detail("ERROR", 1, line, ""),          # the body channel
        pi._exception_failure(ValueError(line)),               # an exception message
        line,                                                  # a plain string at the descriptor
    ):
        detail = pi._finalize_leg_detail(failure)
        assert detail != line, (line, detail)
        assert _SECRET not in (detail or "")
        # a failure LABEL (auth_failure, usage_limit ...) is fine; a template echo is not
        assert detail is None or pi._detail_is_valid(detail), (line, detail)


def test_a_fixed_literal_passes_only_by_exact_equality():
    """The one plain-string path left: an exception whose message EQUALS one of our fixed
    literals (a refusal this runtime raised). Equality carries no foreign text; any extra
    character makes it an unknown failure."""
    code = "review_monitoring_unsupported_route:codex"
    assert pi._finalize_leg_detail(pi._exception_failure(ValueError(code))) == code
    for line in (f"{code} {_SECRET}", f"{code}:{_SECRET}", f" {code}"):
        detail = pi._finalize_leg_detail(pi._exception_failure(ValueError(line)))
        assert detail == "unknown failure; CLI output not retained", (line, detail)


def test_a_tui_marker_prefix_needs_provenance():
    raw = pi._LegFailure(pi._UNKNOWN_DETAIL, raw="x", unknown=True, prefix=f"native_fill_refused:x:{_SECRET}")
    assert pi._finalize_leg_detail(raw) == "unknown failure; CLI output not retained"
    typed = pi._LegFailure(
        pi._UNKNOWN_DETAIL, raw="x", unknown=True, prefix=pi._HarnessCode("claude_tui_pty_eof_no_output"),
    )
    assert pi._finalize_leg_detail(typed) == "claude_tui_pty_eof_no_output: unknown failure; CLI output not retained"


def test_the_raw_field_is_not_in_the_repr():
    failure = pi._LegFailure(pi._UNKNOWN_DETAIL, raw=f"token={_SECRET}", unknown=True)
    assert _SECRET not in repr(failure)


def test_a_native_fill_refusal_carries_the_reason_only():
    """r9: the seat is not a closed field, so the code drops it (the leg carries seat_key)."""
    code = "native_fill_refused:native_fill_digest_mismatch"
    assert pi._finalize_leg_detail(pi._HarnessCode(code)) == code
    assert pi._finalize_leg_detail(pi._HarnessCode("native_fill_refused:not_a_code")) == (
        "unknown failure; CLI output not retained"
    )


def test_a_private_log_name_carries_only_the_registry_harness(tmp_path):
    for seat_key, harness in (("codex:gpt-6:max:red-team", "codex"), (f"{_SECRET}:x", "leg")):
        ref = pi._write_private_leg_log(tmp_path, seat_key, "boom")
        assert re.fullmatch(rf"leg-logs/{harness}-[0-9a-f]{{24}}\.log", ref), ref


def test_an_omnigent_detail_is_typed_only_when_it_fits_its_templates():
    assert pi._omnigent_detail("omnigent v0.4.0 lane=api_key") == "omnigent v0.4.0 lane=api_key"
    assert pi._omnigent_detail(f"omnigent auth: HTTP 401 {_SECRET}") == (
        "unknown failure; CLI output not retained"
    )
    assert pi._omnigent_detail(None) is None


# B2: the verdict forms main accepted must still parse; the CLI lines must not.

@pytest.mark.parametrize("line,verdict", [
    ("**Verdict:** **AGREE**", "AGREE"),
    ("**Verdict:** *PARTIALLY AGREE*", "PARTIALLY AGREE"),
    ("**Verdict:** `DISAGREE`", "DISAGREE"),
    ("*Verdict:* **AGREE**", "AGREE"),
    ("**Partially agree** — reason", "PARTIALLY AGREE"),
    ("**AGREE** — fine", "AGREE"),
    ("- AGREE", "AGREE"),
    ("> DISAGREE: blocking", "DISAGREE"),
    ("1. PARTIALLY AGREE", "PARTIALLY AGREE"),
    ("VERDICT: agree", "AGREE"),
    ("`AGREE`", "AGREE"),
    ("**Verdict**: DISAGREE", "DISAGREE"),
    (">**AGREE**", "AGREE"),  # r9: a blockquote needs no space after `>`
    ("> **AGREE**", "AGREE"),
    (">DISAGREE: blocking", "DISAGREE"),
])
def test_formatted_verdicts_parse(line, verdict):
    assert pi.terminal_verdict("review body\n" + line) == verdict


# B3: no subclass at all, so no mixin can shadow the descriptor.

def test_a_mixin_cannot_shadow_the_detail_chokepoint():
    class DetailMixin:
        detail = None

    with pytest.raises(TypeError):
        type("Leaky", (DetailMixin, pi.PanelLegResult), {})
    with pytest.raises(TypeError):
        type("Plain", (pi.PanelLegResult,), {})


# Other surfaces.

def test_the_research_ledger_gets_the_code_and_the_reason_goes_to_the_private_log(tmp_path):
    leg = pi._research_unavailable_result(
        leg="codex", seat_key="codex:a",
        detail=f"research_profile_unavailable: token={_SECRET}", run_dir=tmp_path,
    )
    assert leg.detail == "research_profile_unavailable"
    ledger = leg._research_ledger
    assert _SECRET not in repr(ledger) and ledger.detail == "research_profile_unavailable"
    logs = list((tmp_path / "leg-logs").iterdir())
    assert len(logs) == 1 and "research_profile_unavailable" in logs[0].read_text()


def test_the_tui_warning_carries_no_pty_text(monkeypatch, tmp_path, caplog):
    import logging
    _claude_session(monkeypatch, (1, "", "claude_tui_pty_eof_no_output", f"{TOK}0123456789"))
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    with caplog.at_level(logging.DEBUG):
        pi._exec_claude_tui_leg(tmp_path / "review", tmp_path / "out", 30, "bundle", env={})
    assert TOK not in caplog.text and "claude_tui_pty_eof_no_output" in caplog.text


def test_a_typed_unavailable_swap_writes_no_orphan_log(monkeypatch, tmp_path):
    failure = pi._LegFailure(pi._UNKNOWN_DETAIL, raw="boom", unknown=True, rc=1)
    leg = pi.invoke_panel(
        "ARTIFACT", ["claude"], stream_dir=tmp_path,
        spawn=lambda leg, art: ("UNAVAILABLE", "tui_backing_required", failure),
    ).legs[0]
    assert leg.detail == "tui_backing_required"
    assert not (tmp_path / "leg-logs").exists() or not any((tmp_path / "leg-logs").iterdir())


def test_the_private_log_is_written_whole(monkeypatch, tmp_path):
    """Short writes: the writer loops until every byte is on disk."""
    import os
    real_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: real_write(fd, bytes(data)[:7]))
    ref = pi._write_private_leg_log(tmp_path, "codex", "0123456789" * 20)
    assert ref and (tmp_path / ref).read_text() == "0123456789" * 20


# The property test, extended with template-shaped secret lines (r8).

def test_property_template_shaped_secret_lines_never_choose_the_detail():
    import random

    rng = random.Random(_PROPERTY_SEED + 8)
    for case in range(_PROPERTY_CASES):
        secret = "".join(rng.choice("abcdefghijkmnopqrstuvwxyz0123456789") for _ in range(24))
        line = rng.choice(_TEMPLATE_SHAPED_LINES).replace(_SECRET, "ghp_" + secret)
        line = line if _SECRET in line else f"{line} ghp_{secret}"
        words = [rng.choice(_FILLER) for _ in range(rng.randint(0, 10))]
        words.insert(rng.randint(0, len(words)), line)
        text = rng.choice(["\n", " "]).join(words)
        rc = rng.choice([1, 2, 0, -9, 124])
        for failure in (pi._leg_failure_detail("ERROR", rc, "", text), pi._exception_failure(ValueError(text))):
            detail = pi._finalize_leg_detail(pi._resolve_leg_detail(failure, None, "codex"))
            if detail is None:
                continue
            assert pi._detail_is_valid(detail), (case, detail)
            assert secret not in detail and secret[:8] not in detail, (case, repr(text), detail)



# --- board round 9 (agent-harness#1102): exact types, no dispatch through the input -----

def test_an_earlier_base_that_skips_init_subclass_still_cannot_subclass():
    """codex r9 #1: an earlier base whose `__init_subclass__` does not call super skips
    PanelLegResult's hook; the exact-type check in `__post_init__` and the descriptor holds."""

    class EarlierBase:
        detail = None

        def __init_subclass__(cls, **kwargs):
            pass

    class Leaky(EarlierBase, pi.PanelLegResult):
        pass

    with pytest.raises(TypeError):
        Leaky("codex", "ERROR", text="", detail="FOREIGN_CANARY_1096")


def test_a_forged_harness_code_subclass_is_foreign():
    """codex r9 #2: a `_HarnessCode` subclass overriding `partition` (or `__str__`) must not
    pass the grammar; only the exact type counts, read via `str.__str__`, and the stored value
    is a fresh `_HarnessCode`, never the supplied object."""

    class ForgedCode(pi._HarnessCode):
        def partition(self, sep):
            return "under_claude_code", ": ", "timeout"

        def __str__(self):
            return "timeout"

        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    leg = pi.PanelLegResult("codex", "ERROR", text="", detail=ForgedCode("FOREIGN_CANARY_1096"))
    assert leg.detail == "unknown failure; CLI output not retained"
    assert "FOREIGN_CANARY_1096" not in repr(leg)
    assert not pi._detail_is_valid(ForgedCode("FOREIGN_CANARY_1096"))
    genuine = pi._HarnessCode("timeout after 900s")
    stored = pi._finalize_leg_detail(genuine)
    assert stored == genuine and stored is not genuine and type(stored) is pi._HarnessCode


def test_a_forged_legfailure_subclass_is_foreign():
    class ForgedFailure(pi._LegFailure):
        def rendered(self, log_ref=None):
            return pi._HarnessCode("timeout")

    leg = pi.PanelLegResult("codex", "ERROR", detail=ForgedFailure("FOREIGN_CANARY_1096"))
    assert leg.detail == "unknown failure; CLI output not retained"
