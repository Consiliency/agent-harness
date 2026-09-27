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


def test_detail_never_carries_a_raw_diff_hunk():
    """detail reaches governed-review finding reasons; the closeout metadata gate treats
    a raw hunk header as a FATAL malformed closeout."""
    log = "user\nprompt\nerror: patch failed at @@ -1,3 +1,4 @@ in file\n"
    detail = pi._leg_failure_detail("ERROR", 1, "", log)
    assert detail is not None and "@@ -1,3 +1,4 @@" not in detail


def test_single_line_harness_diagnostics_are_kept_whole():
    for diag in ("timeout after 900s", "subscription_auth_unproven"):
        assert pi._leg_failure_detail("DEGRADED", 1, "", diag) == diag


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
    assert detail.startswith("usage_limit (resets Oct 1st, 2026 1:42 PM): ")


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
    sink: list[str] = []
    status, _text = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert status == "OK" and sink == []


def test_board_stderr_summary_names_why_a_seat_failed(tmp_path):
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    real_compose = comp_mod.compose_review_board
    detail = "usage_limit (resets Oct 1st, 2026 1:42 PM): " + CODEX_USAGE_BANNER
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
    assert pi._leg_failure_detail(status, 1, "You hit your weekly limit.", "") == (
        "usage_limit: You hit your weekly limit."
    )


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


def test_usage_limit_banner_is_labeled_with_reset_and_excerpt():
    status = pi._classify_leg(1, "", CODEX_LOG)
    assert status == "DEGRADED"
    detail = pi._leg_failure_detail(status, 1, "", CODEX_LOG)
    assert detail.startswith("usage_limit (resets Oct 1st, 2026 1:42 PM): ")
    assert "You've hit your usage limit" in detail
    assert "Review the attached phase change" not in detail, "detail is the prompt echo"


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
    assert pi._leg_failure_detail(status, 1, "", log).startswith(
        "usage_limit (resets Oct 1st, 2026 1:42 PM): ERROR: You've hit your usage limit"
    )


@pytest.mark.parametrize("plan", sorted(_CODEX_PLANS))
@pytest.mark.parametrize("reset", sorted(_CODEX_RESETS))
def test_codex_usage_banner_every_plan_and_reset_form(plan, reset):
    bare_suffix, or_suffix, when = _CODEX_RESETS[reset]
    banner = _CODEX_PLANS[plan] + (bare_suffix if plan == "bare" else or_suffix)
    log = "user\n<prompt echo elided>\nERROR: " + banner + "\n"
    status = pi._classify_leg(1, "", log)
    assert status == "DEGRADED", banner
    detail = pi._leg_failure_detail(status, 1, "", log)
    label = f"usage_limit (resets {when}): " if when else "usage_limit: "
    assert detail.startswith(label), (banner, detail)


def test_direct_spawn_carries_labeled_detail_and_stays_a_warn(monkeypatch):
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", CODEX_LOG))
    leg = pi.invoke_panel("ARTIFACT", ["codex"]).legs[0]
    assert leg.status == "DEGRADED"
    assert not leg.text.strip(), "a diagnostic leaked into text (governed BLOCK)"
    assert leg.detail and leg.detail.startswith("usage_limit (resets Oct 1st, 2026")
    findings = gr._findings_from_panel(pi.PanelResult(legs=(leg,)))
    assert [f.code for f in findings] == ["panel_leg_degraded"]
    assert "usage_limit" in findings[0].reason


def test_claude_tui_refusal_reaches_the_detail_sink(monkeypatch, tmp_path):
    _claude_session(monkeypatch, (
        1, "", "claude_tui_pty_eof_no_output", pi._sanitized_pty_tail(CLAUDE_TMPDIR_REFUSAL.encode())
    ))
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list[str] = []
    status, _text = pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert status == "DEGRADED"
    assert sink and sink[-1].startswith("env_failure: Temp directory /tmp/claude-0")


def test_claude_untyped_sink_detail_is_prefixed_redacted_and_bounded(monkeypatch, tmp_path):
    marker = "claude_tui_failed token=abcdefghijklmnopqrstuv " + "y" * 3000
    _claude_session(monkeypatch, (1, "", marker, "fatal: something broke"))
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list[str] = []
    pi._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink,
    )
    assert sink and sink[-1].startswith("claude_tui_failed")
    assert "abcdefghijklmnopqrstuv" not in sink[-1]
    assert len(sink[-1]) <= pi._LEG_DETAIL_MAX_CHARS


def test_direct_default_spawn_returns_the_claude_sink_detail(monkeypatch):
    _claude_session(monkeypatch, (
        1, "", "claude_tui_pty_eof_no_output",
        pi._sanitized_pty_tail(CLAUDE_TMPDIR_REFUSAL.encode()),
    ))
    spawned = pi._default_spawn("claude", "ARTIFACT", mode="review")
    assert len(spawned) == 3, spawned
    status, _text, detail = spawned
    assert status == "DEGRADED"
    assert detail.startswith("env_failure: Temp directory /tmp/claude-0")


# --- REDACTION: known values --------------------------------------------------------------

@pytest.mark.parametrize("home", ["/Users/Jane Doe", "/home/Jane Doe", "/var/home/Jane Doe"])
@pytest.mark.parametrize("tail", ["", "/Library/Caches/claude"])
def test_the_real_home_is_substituted_whatever_its_shape(monkeypatch, home, tail):
    """rounds 3-4: a home with a space and no trailing slash leaked `~ Doe`. The running
    user's home is a KNOWN value; substitute it exactly instead of guessing path shapes."""
    monkeypatch.setattr(pi, "_redaction_identity", lambda: ((home,), ("jdoe",)))
    line = f"Temp directory {home}{tail} is owned by uid 501, expected 0. Refusing to use it"
    detail = pi._leg_failure_detail("DEGRADED", 1, "", line)
    assert detail.startswith("env_failure: Temp directory ~")
    assert "Jane" not in detail and "Doe" not in detail, detail


def test_the_username_and_seat_paths_are_substituted(monkeypatch):
    """claude r5 (a): the username boundary is [A-Za-z0-9_], so `jdoe-codex` / `jdoe.admin`
    are substituted too (the round-5 test pinned that leak; dropped)."""
    monkeypatch.setattr(pi, "_redaction_identity", lambda: (("/home/jdoe",), ("jdoe",)))
    log = (
        "fatal: jdoe cannot create /tmp/jdoe-codex/app.sock or write "
        "/srv/seat-42/out/panel.txt (owner jdoe.admin)"
    )
    detail = pi._leg_failure_detail("ERROR", 1, "", log, ("/srv/seat-42",))
    assert "jdoe" not in detail, detail
    assert "/srv/seat-42" not in detail and "<path>/out/panel.txt" in detail
    assert "fatal: <user> cannot" in detail
    # a longer word merely containing the name is not the name
    monkeypatch.setattr(pi, "_redaction_identity", lambda: ((), ("ann",)))
    assert "annotation" in pi._leg_failure_detail("ERROR", 1, "", "fatal: bad annotation")


def test_an_email_whose_local_part_is_the_username_is_redacted(monkeypatch):
    """claude/grok r5 (b): known values are substituted first, so `jane@x` became
    `<user>@x`; the shape pass now takes `<user>@domain` too."""
    monkeypatch.setattr(pi, "_redaction_identity", lambda: ((), ("jane",)))
    detail = pi._leg_failure_detail("ERROR", 1, "", "fatal: jane@janedoe.dev: request rejected")
    assert "janedoe" not in detail and "<email>" in detail, detail


def test_a_known_path_is_substituted_only_at_a_path_boundary(monkeypatch):
    """claude r5: HOME=/app must not rewrite /app-server."""
    monkeypatch.setattr(pi, "_redaction_identity", lambda: (("/app",), ()))
    detail = pi._leg_failure_detail("ERROR", 1, "", "fatal: /app-server failed; see /app/log")
    assert "/app-server" in detail and "~/log" in detail, detail


def test_finalizing_is_idempotent(monkeypatch):
    """claude r5: re-finalizing username `user` gave `<<user>>`."""
    monkeypatch.setattr(pi, "_redaction_identity", lambda: (("/home/user",), ("user",)))
    once = pi._finalize_leg_detail("user at /home/user/x token=abcdefghijklmnop jane@a.io " + "z" * 2000)
    assert once == pi._finalize_leg_detail(once)
    assert "<<" not in once and len(once) <= pi._LEG_DETAIL_MAX_CHARS


def test_the_real_identity_is_what_the_host_reports():
    homes, users = _REAL_REDACTION_IDENTITY()
    import os
    assert os.path.expanduser("~").rstrip("/") in homes
    assert users, "no username known to redact"


def test_the_final_labelled_detail_is_bounded_and_control_stripped():
    path = "/tmp/\x1b[2J\x07\x1bZ\x9b2J\x00" + "z" * 950
    line = f"Temp directory {path} is owned by uid 65534, expected 0. Refusing to use it"
    status = pi._classify_leg(1, "", line)
    assert status == "DEGRADED"
    detail = pi._leg_failure_detail(status, 1, "", line)
    assert detail.startswith("env_failure: Temp directory /tmp/")
    assert len(detail) <= pi._LEG_DETAIL_MAX_CHARS
    assert not re.search(r"[\x00-\x1f\x7f-\x9f]", detail), repr(detail)


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

def test_a_token_split_from_its_prefix_by_a_newline_is_redacted_before_selection():
    """codex r5 BLOCKING: the excerpt picked the last line FIRST, so `Bearer\n<token>` lost
    its prefix and leaked as `signal: <token>`. Redaction now runs over the whole uncut
    text before any line is selected."""
    log = "Bearer\nabcdefghijklmnopqrstuvwx"
    status = pi._classify_leg(-9, "", log)
    assert status == "ERROR"
    detail = pi._leg_failure_detail(status, -9, "", log)
    assert "abcdefghijklmnopqrstuvwx" not in detail, detail
    assert detail.startswith("signal: ")


def test_every_panel_leg_result_stores_a_finalized_detail(monkeypatch):
    """claude r5 (c): raw exception strings reached `PanelLegResult.detail`, then governed
    finding reasons and the verdict JSON. The dataclass now finalizes on construction."""
    monkeypatch.setattr(pi, "_redaction_identity", lambda: (("/home/jdoe",), ("jdoe",)))
    raw = "OSError: [Errno 13] /home/jdoe/.local/bin/codex token=abcdefghijklmnop \x1b[2J" + "q" * 3000
    leg = pi.PanelLegResult(leg="codex", status="DEGRADED", text="", detail=raw)
    assert "/home/jdoe" not in leg.detail and "jdoe" not in leg.detail
    assert "abcdefghijklmnop" not in leg.detail and "\x1b" not in leg.detail
    assert len(leg.detail) <= pi._LEG_DETAIL_MAX_CHARS
    reason = gr._findings_from_panel(pi.PanelResult(legs=(leg,)))[0].reason
    assert "jdoe" not in reason and "abcdefghijklmnop" not in reason
    import dataclasses
    assert dataclasses.replace(leg, status="ERROR").detail == leg.detail, "not idempotent"
    # the direct spawn's exception path builds a PanelLegResult too
    def boom(*a, **k):
        raise OSError("cannot exec /home/jdoe/.local/bin/codex")
    monkeypatch.setattr(pi, "_exec_leg", boom)
    detail = pi.invoke_panel("ARTIFACT", ["codex"]).legs[0].detail or ""
    assert "/home/jdoe" not in detail and "jdoe" not in detail, detail


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
