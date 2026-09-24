"""ah#196/#223 — the Claude TUI advisor leg must clear the workspace-trust modal
(answer ``y`` once, PRE-SUBMIT, path-scoped to its scratch cwd), submit only when the
editor is quiescent, and fail CLOSED with a typed reason (never the generic 180s
``claude_tui_stalled``) when the gate can't be cleared. Post-submit output that happens
to contain the trust strings must NEVER inject a keystroke or flip the leg to blocked
(this leg reviews agent-harness PRs about this very code).

Real-subprocess PTY tests (like test_panel_tui_liveness_188 / _eof_48): a synthetic
``sh -c`` fake-``claude`` prints the captured modal / editor bursts; only the timing
constants are monkeypatched short so the flows resolve in seconds.
"""

from __future__ import annotations

import shutil
import sys
import time
from hashlib import sha256

import pytest

import phase_loop_runtime.panel_invoker as pi
from phase_loop_runtime.panel_invoker import _exec_claude_tui_leg, _run_claude_tui_session

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs POSIX sh")


@pytest.fixture(autouse=True)
def _proven_subscription_auth(monkeypatch):
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))

_NO_TRANSCRIPT = lambda *a, **k: ""  # noqa: E731

# Fast timing so the startup state machine resolves in seconds, not the production
# 8s floor / 45s readiness deadline / 180s stall.
def _fast_timing(monkeypatch, *, submit_delay=0.5, quiescence=0.4, ready_deadline=4.0, stall=120):
    monkeypatch.setattr(pi, "_CLAUDE_TUI_SUBMIT_DELAY_S", submit_delay)
    monkeypatch.setattr(pi, "_CLAUDE_TUI_READY_QUIESCENCE_S", quiescence)
    monkeypatch.setattr(pi, "_CLAUDE_TUI_READY_DEADLINE_S", ready_deadline)
    monkeypatch.setattr(pi, "_LEG_STALL_THRESHOLD_S", stall)
    monkeypatch.setattr(pi, "_latest_claude_transcript_text", _NO_TRANSCRIPT)


# A fresh-cwd workspace-trust modal (the captured 2.1.208 shape), printed with the real
# ``$PWD`` so the path-scoped conjunction (header AND choice AND cwd token) matches.
_MODAL = (
    "printf 'Permission Required: Accessing workspace:\\n%s\\n"
    "Quick safety check: Is this a project you created or one you trust?\\n"
    "y. Yes, I trust this folder\\nn. No, exit\\nEnter y/n:' \"$PWD\"; "
)


@pytest.mark.parametrize("header", ["Permission Required: Accessing workspace:", "Accessing workspace:"])
def test_trust_modal_answered_once_then_leg_completes(tmp_path, monkeypatch, header):
    """The modal is answered ``y`` (recorded by the fake), the editor burst arms
    readiness, and the leg completes OK — the review prompt is NOT pasted into the
    y/n field (the reproduced bug)."""
    _fast_timing(monkeypatch)
    script = (
        _MODAL.replace("Permission Required: Accessing workspace:", header)
        + "IFS= read -r ans; printf '%s' \"$ans\" > answer.txt; "
        + "printf '\\nClaude Code v2.1.208\\nWelcome back\\nmanual mode on ready now\\n'; "
        + "printf 'The staged bundle looks correct.\\n\\nAGREE\\n' > panel-claude.txt; "
        + "sleep 3"
    )
    output_file = tmp_path / "panel-claude.txt"
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script],
        cwd=tmp_path,
        prompt="review this bundle\n",
        output_file=output_file,
        timeout_s=30,
        env={"PATH": "/usr/bin:/bin"},
        backstop_s=30,
    )
    assert status == "claude_tui_file_output", f"expected OK file verdict, got {status!r} / {text!r}"
    assert "AGREE" in text
    # The modal received exactly ``y`` — not the review prompt pasted into the y/n field.
    assert (tmp_path / "answer.txt").read_text().strip() == "y"


def test_trust_modal_never_clears_is_typed_blocked_before_stall(tmp_path, monkeypatch):
    """A modal that keeps rejecting the answer fails CLOSED as
    ``claude_tui_workspace_trust_blocked`` well before the 180s generic stall, with a
    non-empty redacted PTY tail."""
    _fast_timing(monkeypatch, ready_deadline=6.0, stall=120)
    script = (
        _MODAL
        + "IFS= read -r ans; "
        + "while :; do printf '\\nPlease answer y or n\\nEnter y/n:'; sleep 0.2; done"
    )
    start = time.monotonic()
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script],
        cwd=tmp_path,
        prompt="review this\n",
        output_file=tmp_path / "panel-claude.txt",
        timeout_s=120,
        env={"PATH": "/usr/bin:/bin"},
        backstop_s=120,
    )
    elapsed = time.monotonic() - start
    assert status == "claude_tui_workspace_trust_blocked", f"got {status!r}"
    assert rc != 0
    assert elapsed < 60, f"typed-blocked must precede the 180s stall; took {elapsed:.1f}s"
    assert tail, "a failed leg must carry a diagnostic PTY tail"


def test_no_modal_never_ready_is_editor_not_ready(tmp_path, monkeypatch):
    """A silent startup (no modal, no output) yields the DISTINCT
    ``claude_tui_editor_not_ready`` reason (not trust_blocked, not the generic stall)."""
    _fast_timing(monkeypatch, ready_deadline=3.0, stall=120)
    start = time.monotonic()
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", "sleep 60"],
        cwd=tmp_path,
        prompt="review this\n",
        output_file=tmp_path / "panel-claude.txt",
        timeout_s=120,
        env={"PATH": "/usr/bin:/bin"},
        backstop_s=120,
    )
    elapsed = time.monotonic() - start
    assert status == "claude_tui_editor_not_ready", f"got {status!r}"
    assert 3 <= elapsed < 30, f"must fire at the readiness deadline, not the stall; {elapsed:.1f}s"


def test_post_submit_trigger_text_does_not_block_or_inject(tmp_path, monkeypatch):
    """CRITICAL (self-referential): after submission, review OUTPUT containing the trust
    trigger strings ("Enter y/n:", "Please answer y or n") must NOT flip the leg to
    trust_blocked and must NOT inject a keystroke — the detector is disarmed at submit.
    The leg completes OK on its review file."""
    _fast_timing(monkeypatch)
    script = (
        # No modal: straight to an editor burst that arms readiness.
        "printf 'Claude Code v2.1.208\\nWelcome back\\nmanual mode on ready now\\n'; "
        + "sleep 2; "
        # AFTER the harness has submitted, emit output loaded with the trigger strings.
        + "printf 'The reviewed diff prints Enter y/n: and Please answer y or n verbatim.\\n"
        + "No real gate here.\\n\\nAGREE\\n' > panel-claude.txt; "
        + "sleep 3"
    )
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script],
        cwd=tmp_path,
        prompt="review this bundle\n",
        output_file=tmp_path / "panel-claude.txt",
        timeout_s=30,
        env={"PATH": "/usr/bin:/bin"},
        backstop_s=30,
    )
    assert status == "claude_tui_file_output", f"post-submit trigger text must not block; got {status!r}"
    assert status != "claude_tui_workspace_trust_blocked"
    assert "AGREE" in text


def test_production_shaped_cwd_full_path_token_answers(tmp_path, monkeypatch):
    """CR F1/R5: production allocates ``mkdtemp('pl-panel-')/out`` — basename ``out`` is
    vacuous. The modal must be answered via the run-unique FULL path, so a production
    ``<uniq>/out`` cwd still clears the gate and completes."""
    _fast_timing(monkeypatch)
    out = tmp_path / "out"  # basename == "out", like production
    out.mkdir()
    script = (
        _MODAL
        + "IFS= read -r ans; printf '%s' \"$ans\" > answer.txt; "
        + "printf '\\nClaude Code v2.1.208\\nmanual mode on ready now\\n'; "
        + "printf 'fine.\\n\\nAGREE\\n' > panel-claude.txt; sleep 3"
    )
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script], cwd=out, prompt="review this\n",
        output_file=out / "panel-claude.txt", timeout_s=30,
        env={"PATH": "/usr/bin:/bin"}, backstop_s=30,
    )
    assert status == "claude_tui_file_output", f"full-path token must clear the gate; got {status!r}"
    assert (out / "answer.txt").read_text().strip() == "y"


@pytest.mark.parametrize("header", ["Permission Required: Accessing workspace:", "Accessing workspace:"])
def test_wrong_dir_modal_is_not_answered(tmp_path, monkeypatch, header):
    """CR F1/R5 (negative): a trust modal for a DIFFERENT directory whose basename is
    also ``out`` must NOT be auto-answered (the old bare-basename token would have
    vacuously matched). No ``y`` is sent; the gate is never cleared."""
    _fast_timing(monkeypatch, ready_deadline=3.0, stall=120)
    out = tmp_path / "out"
    out.mkdir()
    # Modal for a FOREIGN path (basename "out", different full path than our cwd).
    script = (
        f"printf '{header}\\n/tmp/some-other-run/out\\n"
        "Quick safety check: Is this a project you created or one you trust?\\n"
        "y. Yes, I trust this folder\\nn. No, exit\\nEnter y/n:'; "
        "IFS= read -r ans; printf '%s' \"$ans\" > answer.txt; sleep 60"
    )
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script], cwd=out, prompt="review this\n",
        output_file=out / "panel-claude.txt", timeout_s=120,
        env={"PATH": "/usr/bin:/bin"}, backstop_s=120,
    )
    # The gate signature was seen but our path-scoped conjunction did NOT match the
    # foreign path, so we never answered and — crucially — never armed readiness / pasted
    # the prompt into the y/n field. It fails CLOSED as trust_blocked (an uncleared gate),
    # NOT by pasting the review into a foreign modal. And no stray "y" was written.
    assert status == "claude_tui_workspace_trust_blocked", f"foreign-dir modal must fail closed; got {status!r}"
    assert not (out / "answer.txt").exists(), "a stray y was written to a foreign-dir modal"


def test_modal_answered_but_editor_never_ready_is_editor_not_ready(tmp_path, monkeypatch):
    """CR F2/R6: a modal that IS answered but whose editor never reaches readiness is
    ``claude_tui_editor_not_ready`` (an editor-readiness failure), NOT the misleading
    ``claude_tui_workspace_trust_blocked``. (The prompt line is newline-terminated so the
    cooked-mode echo of ``y`` produces no post-answer novel content — isolating the
    "answered but no editor output" state, which in the real TUI is otherwise masked by
    the redraw that follows the answer.)"""
    _fast_timing(monkeypatch, ready_deadline=3.0, stall=120)
    modal_nl = (
        "printf 'Permission Required: Accessing workspace:\\n%s\\n"
        "y. Yes, I trust this folder\\nn. No, exit\\nEnter y/n:\\n' \"$PWD\"; "
    )
    script = modal_nl + "IFS= read -r ans; printf '%s' \"$ans\" > answer.txt; sleep 60"
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script], cwd=tmp_path, prompt="review this\n",
        output_file=tmp_path / "panel-claude.txt", timeout_s=120,
        env={"PATH": "/usr/bin:/bin"}, backstop_s=120,
    )
    assert (tmp_path / "answer.txt").read_text().strip() == "y", "the modal should have been answered"
    assert status == "claude_tui_editor_not_ready", f"answered-but-unready must be editor_not_ready; got {status!r}"


def test_trailing_modal_chunk_cannot_arm_editor_readiness(tmp_path, monkeypatch):
    _fast_timing(monkeypatch, submit_delay=0.1, quiescence=0.05, ready_deadline=2.0)
    marker = b"y. Yes, I trust this folder"
    pending = bytearray()
    split_count = 0
    real_read = pi.os.read
    real_select = pi.select.select

    def split_read(fd, length):
        nonlocal split_count
        if pending:
            data = bytes(pending)
            pending.clear()
            return data
        data = real_read(fd, length)
        if split_count == 0 and marker in data:
            end = data.index(marker) + len(marker)
            pending.extend(data[end:])
            split_count += 1
            return data[:end]
        return data

    def select_pending(readers, writers, errors, timeout=None):
        if pending:
            return readers, [], []
        return real_select(readers, writers, errors, timeout)

    script = (
        "printf 'Permission Required: Accessing workspace:\\n%s\\n"
        "y. Yes, I trust this folder\\nn. No, exit\\nEnter y/n:\\n' \"$PWD\"; "
        "IFS= read -r ans; printf '%s' \"$ans\" > answer.txt; sleep 5"
    )
    monkeypatch.setattr(pi.os, "read", split_read)
    monkeypatch.setattr(pi.select, "select", select_pending)
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script], cwd=tmp_path, prompt="review this\n",
        output_file=tmp_path / "panel-claude.txt", timeout_s=10,
        env={"PATH": "/usr/bin:/bin"}, backstop_s=10,
    )
    assert split_count == 1
    assert (tmp_path / "answer.txt").read_text().strip() == "y"
    assert status == "claude_tui_editor_not_ready", (rc, status, text, tail)


def test_post_trust_chunk_accepts_editor_after_modal_remainder():
    remainder = b"n. No, exit\nEnter y/n:\n"
    assert not pi._tui_post_trust_editor_content(remainder, (), set())
    assert pi._tui_post_trust_editor_content(
        remainder + b"Claude Code v2.1.208\nmanual mode on ready now\n", (), set()
    )
    assert not pi._tui_post_trust_editor_content(
        b"\xe2\x9d\xaf 2. No, exit\nEnter to confirm \xc2\xb7 Esc to cancel\n", (), set()
    )
    seen = {pi._normalize_tui_line("Claude Code v2.1.208")}
    assert not pi._tui_post_trust_editor_content(
        b"Accessing workspace:\nClaude Code v2.1.208\n", (), seen
    )


def test_post_trust_current_header_redraw_does_not_arm_editor(tmp_path, monkeypatch):
    _fast_timing(monkeypatch, submit_delay=0.1, quiescence=0.05, ready_deadline=2.0)
    script = (
        _MODAL
        + "IFS= read -r ans; printf '%s' \"$ans\" > answer.txt; "
        + "printf '\\nAccessing workspace:\\n'; "
        + "IFS= read -r unexpected; printf '%s' \"$unexpected\" > unexpected.txt"
    )
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script], cwd=tmp_path, prompt="review this\n",
        output_file=tmp_path / "panel-claude.txt", timeout_s=10,
        env={"PATH": "/usr/bin:/bin"}, backstop_s=10,
    )
    assert (tmp_path / "answer.txt").read_text().strip() == "y"
    assert status == "claude_tui_editor_not_ready", (rc, status, text, tail)
    assert not (tmp_path / "unexpected.txt").exists()


def test_post_trust_ansi_redraw_after_unterminated_prompt_keeps_editor(tmp_path, monkeypatch):
    _fast_timing(monkeypatch, submit_delay=0.1, quiescence=0.05, ready_deadline=2.0)
    assert pi._tui_post_trust_editor_content(
        b"Enter y/n:\x1b[2J\x1b[HClaude Code v2.1.208\n", (), set()
    )
    script = (
        "stty raw -echo; "
        + _MODAL
        + "dd bs=1 count=1 of=answer.txt 2>/dev/null; "
        + "printf '\\033[2J\\033[HClaude Code v2.1.208\\n'; "
        + "dd bs=1 count=1 of=prompt-byte.txt 2>/dev/null; "
        + "printf 'A complete review body with sufficient text to finish.\\nAGREE\\n' > panel-claude.txt; sleep 3"
    )
    rc, text, status, tail = _run_claude_tui_session(
        command=["sh", "-c", script], cwd=tmp_path, prompt="review this\n",
        output_file=tmp_path / "panel-claude.txt", timeout_s=10,
        env={"PATH": "/usr/bin:/bin"}, backstop_s=10,
    )
    assert (tmp_path / "answer.txt").read_text() == "y"
    assert status == "claude_tui_file_output", (rc, status, text, tail)
    assert (tmp_path / "prompt-byte.txt").exists()


def test_non_typed_failure_logs_pty_tail(tmp_path, monkeypatch, caplog):
    """CR F3/R3: the redacted tail is preserved as diagnosable evidence for EVERY non-OK
    failure — via a WARNING log, NOT stamped into ``text`` (which feeds verdict-conformance
    and would turn an operational failure into a promotion-blocking nonconforming review)."""
    monkeypatch.setattr(pi, "_run_claude_tui_session",
                        lambda **kw: (1, "", "claude_tui_missing_canonical_output", "diag tail Z"))
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    import logging as _logging
    with caplog.at_level(_logging.WARNING):
        status, text = _exec_claude_tui_leg(review_dir, out_dir, 30, "bundle", env={})
    assert status != "OK"
    assert "diag tail Z" in caplog.text, "the diagnostic tail must be logged for a non-OK leg"


def test_operational_degraded_leg_is_governed_warn_not_block(tmp_path, monkeypatch):
    """CR (codex, blocking): an operational DEGRADED leg (uncleared trust gate) must NOT
    stamp a diagnostic into ``text`` — because the governed-review classifier turns a
    non-empty-text unusable leg into a promotion-BLOCKING ``panel_nonconforming`` finding.
    End-to-end: the leg's empty text records a non-gating ``panel_leg_degraded`` WARN."""
    from phase_loop_runtime.governed_review import _findings_from_panel
    from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult

    monkeypatch.setattr(pi, "_run_claude_tui_session",
                        lambda **kw: (1, "", "claude_tui_workspace_trust_blocked", "redacted tail"))
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    status, text = _exec_claude_tui_leg(review_dir, out_dir, 30, "bundle", env={})
    assert status == "DEGRADED"
    assert text == "", "an operational failure must carry EMPTY text (a diagnostic in text blocks promotion)"
    # Feed it through the governed-review finding classifier: WARN, never a block.
    leg = PanelLegResult(leg="claude", status=status, text=text, seat_key="claude")
    findings = _findings_from_panel(PanelResult(legs=(leg,)))
    codes = {f.code for f in findings}
    severities = {f.severity for f in findings}
    assert "panel_nonconforming" not in codes, "operational DEGRADED leg wrongly hard-blocks promotion"
    assert "block" not in severities
    assert "panel_leg_degraded" in codes and "warn" in severities


def test_stalled_leg_with_partial_review_still_blocks(tmp_path, monkeypatch):
    """Fail-closed seam: only a PURE operational failure (empty text) degrades to WARN. A
    leg that DID emit partial review content but no conforming verdict must still fail
    CLOSED (governed ``panel_nonconforming`` BLOCK), never a silent WARN."""
    from phase_loop_runtime.governed_review import _findings_from_panel
    from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult

    partial = "I have concerns about the diff but never finished"
    monkeypatch.setattr(pi, "_run_claude_tui_session",
                        lambda **kw: (1, partial, "claude_tui_stalled", "tail"))
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    status, text = _exec_claude_tui_leg(review_dir, out_dir, 30, "bundle", env={})
    assert status == "DEGRADED"
    assert text == partial, "a partial review must be preserved (fail closed), not emptied"
    leg = PanelLegResult(leg="claude", status=status, text=text, seat_key="claude")
    findings = _findings_from_panel(PanelResult(legs=(leg,)))
    assert any(f.code == "panel_nonconforming" and f.severity == "block" for f in findings), \
        "a partial review with no verdict must fail closed as a block"


def test_sanitized_pty_tail_redacts_strips_and_keeps_end(tmp_path):
    """The evidence tail strips ANSI + control bytes, is bounded, and keeps the END of
    the buffer (where the modal / reject context lives)."""
    raw = b"\x1b[2Kstart-of-buffer\x00\x07\x1b]0;title\x07 " + b"filler " * 40 + b"THE_END_MARKER"
    out = pi._sanitized_pty_tail(raw, max_chars=90)
    assert len(out) <= 90
    assert "THE_END_MARKER" in out  # keeps the END, not the head
    assert "\x1b" not in out and "\x00" not in out and "\x07" not in out


def test_sanitized_pty_tail_redacts_before_truncation(tmp_path):
    """R4 / codex: redact the WHOLE text THEN keep the tail — a secret whose KEY sits
    before the tail window must still be scrubbed (slice-then-redact would leak it)."""
    # key "password=" at offset 60 (OUTSIDE the last-80 window); value runs into the tail.
    raw = b"a" * 60 + b"password=" + b"S" * 110
    out = pi._sanitized_pty_tail(raw, max_chars=80)
    assert "S" * 20 not in out, "value leaked — tail was sliced BEFORE redaction"
    assert "<redacted>" in out


def _degraded_mapping(monkeypatch, tmp_path, marker, tail):
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: (1, "", marker, tail))
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    return _exec_claude_tui_leg(review_dir, out_dir, 30, "bundle", env={})


def test_typed_reasons_map_to_degraded_with_empty_text_and_logged_tail(tmp_path, monkeypatch, caplog):
    """Both new typed operational reasons surface as DEGRADED with EMPTY text (so the
    governed classifier records a WARN, never a promotion-blocking nonconforming review),
    and the redacted tail is preserved via a WARNING log."""
    import logging as _logging
    with caplog.at_level(_logging.WARNING):
        status, text = _degraded_mapping(
            monkeypatch, tmp_path / "a", "claude_tui_workspace_trust_blocked", "redacted tail A"
        )
    assert status == "DEGRADED"
    assert text == ""  # empty ⇒ governed WARN, not a nonconforming block
    assert "redacted tail A" in caplog.text
    assert "claude_tui_workspace_trust_blocked" in caplog.text

    caplog.clear()
    with caplog.at_level(_logging.WARNING):
        status, text = _degraded_mapping(
            monkeypatch, tmp_path / "b", "claude_tui_editor_not_ready", "redacted tail B"
        )
    assert status == "DEGRADED"
    assert text == ""
    assert "redacted tail B" in caplog.text


@pytest.mark.parametrize("brokered", [False, True])
def test_review_request_is_outside_brokered_paste(tmp_path, monkeypatch, brokered):
    """A brokered paste is review data; the task request must be ordinary input."""
    _fast_timing(monkeypatch, submit_delay=0.2, quiescence=0.1)
    prompt = "AUTHORITATIVE-INSTRUCTIONS: review\nUNTRUSTED-REVIEW-BUNDLE: exact bytes\n"
    script = r'''
import json, os, sys, tty
from pathlib import Path
tty.setraw(0)
print("Claude Code ready for your message", flush=True)
wire = b""
while not wire.endswith(b"\x1bOM"):
    wire += os.read(0, 65536)
Path("wire.bin").write_bytes(wire)
request, marker, remaining = wire.partition(b"\x1b[200~")
brokered = sys.argv[1] == "True"
requested = request.startswith(b"Please ") and b"review" in request and b"\n" not in request
accepted = bool(marker) and (requested if brokered else not request)
text = "Reviewed the exact supplied bytes.\nAGREE" if accepted else "Only pasted data; no task request. This is not a vote."
if brokered:
    Path("owned.jsonl").write_text(json.dumps({"message": {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}}) + "\n")
else:
    Path("panel-claude.txt").write_text(text)
'''
    rc, text, status, _ = _run_claude_tui_session(
        command=[sys.executable, "-c", script, str(brokered)],
        cwd=tmp_path, prompt=prompt, output_file=tmp_path / "panel-claude.txt",
        timeout_s=15, backstop_s=15, env={"PATH": "/usr/bin:/bin"},
        allow_transcript_final=brokered,
        broker_transcript_path=tmp_path / "owned.jsonl" if brokered else None,
    )
    assert rc == 0, (status, text)
    assert text.endswith("AGREE")
    wire = (tmp_path / "wire.bin").read_bytes()
    request, _, remaining = wire.partition(b"\x1b[200~")
    assert remaining == prompt.encode() + b"\x1b[201~\x1bOM"
    assert request == (pi._BROKER_CLAUDE_DIRECT_REQUEST.encode() if brokered else b"")


def test_broker_evidence_binds_plain_request_and_sealed_paste(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    calls = []

    def completed_session(**kwargs):
        calls.append(kwargs)
        return 0, "Reviewed.\nAGREE", "claude_tui_broker_final_assistant", ""

    monkeypatch.setattr(pi, "_run_claude_tui_session", completed_session)
    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()
    prompt = "Exact sealed instructions and untrusted review bytes."
    evidence = {}
    status, _ = _exec_claude_tui_leg(
        review_dir, out_dir, 15, "bundle", broker_prompt=prompt,
        broker_evidence=evidence, env={"PATH": "/usr/bin:/bin"},
    )
    assert status == "OK"
    assert len(calls) == 1 and calls[0]["prompt"] == prompt
    assert calls[0]["broker_transcript_path"] is not None
    assert calls[0]["allow_transcript_final"] is True
    request = "Please perform the review requested in the following framed material. "
    assert evidence["provider_prompt_sha256"] == sha256(prompt.encode()).hexdigest()
    assert evidence["provider_transport_sha256"] == sha256((request + prompt).encode()).hexdigest()
    assert evidence["provider_transport_bytes"] == len((request + prompt).encode())
    assert evidence["provider_task_request_sha256"] == sha256(request.encode()).hexdigest()
    assert evidence["provider_task_request_bytes"] == len(request.encode())
    assert evidence["provider_task_request_delivery"] == "plain_text_before_bracketed_paste"
    assert "tools-empty" in evidence["provider_no_tool_controls"]


@pytest.mark.parametrize("control", ["\x1b[201~", "\r", "\x1bOM"])
@pytest.mark.parametrize("field", ["artifact", "instructions"])
def test_brokered_paste_rejects_terminal_controls(field, control):
    inputs = {"artifact": "review data", "instructions": "review this data"}
    inputs[field] += control + "escape attempt"
    with pytest.raises(ValueError, match="transport-active control character"):
        pi._render_broker_inline_prompt(**inputs, mode="review")


def test_brokered_typed_request_cannot_submit_or_select_a_tui_mode():
    request = pi._BROKER_CLAUDE_DIRECT_REQUEST
    assert request.startswith("Please ")
    assert request.isascii() and all(32 <= ord(char) <= 126 for char in request)
    assert not any(char.isdigit() for char in request)
    assert not request.startswith(tuple("/!#@?"))
    assert all(verdict not in request for verdict in ("AGREE", "DISAGREE"))
