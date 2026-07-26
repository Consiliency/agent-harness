"""Panel leg failure-diagnostic regression.

A leg CLI running headless cannot prompt for a tool permission: it auto-denies, prints
its reason on stderr, and exits rc==0 with a ZERO-byte body. The panel used to classify
that as an anonymous soft-empty and drop the leg — the gemini seat was dead for 6 of 11
rounds of the #309 review and it was misread as flakiness for that whole milestone.

These tests drive the PRODUCTION path. An earlier revision asserted on values built
inside the test body and never invoked the production function; it was tautological and
the review caught it twice. Do not reintroduce that shape.
"""
from __future__ import annotations

import pytest

from phase_loop_runtime import panel_invoker as pi


_REAL_AGY_STDERR = (
    'jetski: no output produced — a tool required the "command" permission that '
    "headless mode cannot prompt for, so it was auto-denied. Add an allow-rule under "
    "permissions.allow in settings.json (e.g. command(<target>))."
)


def test_tool_denial_regex_matches_the_real_agy_stderr():
    assert pi._TOOL_DENIED_RE.search(_REAL_AGY_STDERR)



def test_tool_denial_is_not_classified_as_a_transient_stall():
    assert not pi._GEMINI_TRANSIENT_RE.search(_REAL_AGY_STDERR)



def test_tool_denial_regex_does_not_fire_on_a_review_that_merely_discusses_it():
    """This panel reviews code about permissions and tooling; a real review body that
    QUOTES the phrase must not be discarded. (The classifier only consults it on an
    EMPTY body, but keep the phrasing distinct enough to be safe.)"""
    body = "The adapter should fail loudly rather than let a tool call be silently dropped."
    assert not pi._TOOL_DENIED_RE.search(body)



def test_denial_reason_goes_to_detail_never_to_text(monkeypatch):
    """CR round 5 (codex) + round 6 (claude leg): the reason must reach the operator, but
    via `detail` — NEVER `text`.

    Round 5 put it in text and that was a real regression:
    `governed_review._findings_from_panel` keys BLOCK-vs-WARN on `leg.text.strip()` for an
    unusable leg — non-empty text is treated as a NONCONFORMING REVIEW and BLOCKS
    promotion, while empty text records the correct non-gating warn. Stamping a diagnostic
    into text turns every routine timeout/auth failure into a promotion block. The
    invariant is documented at panel_invoker.py:2296-2301.
    """
    diagnostic = (
        "gemini leg: headless TOOL-DENIAL — the CLI auto-denied a tool permission it "
        "cannot prompt for and produced NO output."
    )
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", diagnostic))
    spawned = pi._default_spawn("gemini", "ARTIFACT")
    assert len(spawned) == 3, "no diagnostic channel returned"
    status, text, detail = spawned
    assert status != "OK"
    assert not str(text).strip(), (
        "diagnostic leaked into TEXT — this converts an operational failure into a "
        "governed promotion BLOCK (panel_invoker.py:2296-2301)"
    )
    assert "TOOL-DENIAL" in str(detail), "operator cannot see WHY the leg failed"



def test_operational_failure_stays_a_warn_not_a_governed_block(monkeypatch):
    """The consequence test, driven through the real classifier: an unusable leg carrying
    a diagnostic must still produce the non-gating `panel_leg_degraded` WARN, not
    `panel_nonconforming` BLOCK. A routine leg TIMEOUT must never block promotion."""
    from phase_loop_runtime import governed_review as gr

    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (124, "", "timeout after 900s"))
    # NO spawn kwarg — drives the PRODUCTION path through `_default_spawn_via_provider`.
    # Injecting `spawn=pi._default_spawn` bypasses that seam, and doing so is exactly why
    # this test passed while the production path was returning
    # text="too many values to unpack (expected 2)" and BLOCKING promotion.
    panel = pi.invoke_panel("ARTIFACT", ["gemini"])
    findings = gr._findings_from_panel(panel)
    codes = {f.code for f in findings}
    assert "panel_nonconforming" not in codes, (
        "a routine leg timeout was escalated to a promotion BLOCK"
    )
    assert not any(getattr(f, "severity", "") == "block" for f in findings), (
        "an operational leg failure produced a blocking finding"
    )



class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture()
def staged(tmp_path):
    """A review_dir staged the way the panel stages it, plus an out_dir."""
    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    review_dir.mkdir(); out_dir.mkdir()
    (review_dir / "review-instructions.md").write_text("be rigorous", encoding="utf-8")
    (review_dir / "review-bundle.md").write_text("the diff", encoding="utf-8")
    return review_dir, out_dir


def test_headless_denial_returns_nonzero_with_the_cli_reason(monkeypatch, staged):
    """Drives the production `_exec_leg`: rc==0 + empty body + the CLI's auto-denied
    marker must become a DIAGNOSABLE non-zero failure carrying the CLI's explanation —
    never an anonymous EMPTY."""
    review_dir, out_dir = staged
    monkeypatch.setattr(
        pi, "_run_leg_with_liveness",
        lambda cmd, **kw: _FakeProc(stdout="", stderr=_REAL_AGY_STDERR),
    )
    rc, text, log = pi._exec_leg(
        "gemini", review_dir, out_dir, timeout_s=60, artifact="A", env={}
    )
    assert rc != 0, "a headless tool-denial was reported as success"
    assert text == ""
    assert "TOOL-DENIAL" in log and "auto-denied" in log, "the CLI's reason was discarded"


def test_denial_is_attempted_once_not_retried_as_a_stall(monkeypatch, staged):
    """The permission is absent, not flaky — retrying reproduces it exactly. The denial
    check must run BEFORE the soft-empty/stall path, so only ONE attempt is made."""
    review_dir, out_dir = staged
    calls: list = []

    def _fake(cmd, **kw):
        calls.append(cmd)
        return _FakeProc(stdout="", stderr=_REAL_AGY_STDERR)

    monkeypatch.setattr(pi, "_run_leg_with_liveness", _fake)
    pi._exec_leg("gemini", review_dir, out_dir, timeout_s=60, artifact="A", env={})
    assert len(calls) == 1, f"denial retried {len(calls)}x; it is not transient"


def test_production_spawn_path_keeps_text_empty_and_carries_detail(monkeypatch):
    """The seam this PR's first revision missed. `invoke_panel` with NO spawn kwarg goes
    through `_default_spawn_via_provider`, whose provider unpacks a 2-TUPLE — a raw
    3-tuple raises there and the fail-closed handler puts the ValueError text into
    `text`, which the governed classifier reads as a nonconforming review and BLOCKS."""
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (124, "", "timeout after 900s"))
    leg = pi.invoke_panel("ARTIFACT", ["gemini"]).legs[0]
    assert "unpack" not in (leg.text or ""), "the 3-tuple broke the provider seam"
    assert not (leg.text or "").strip(), "diagnostic leaked into text on the production path"
    assert "timeout" in (leg.detail or ""), "the reason never reached the operator"
