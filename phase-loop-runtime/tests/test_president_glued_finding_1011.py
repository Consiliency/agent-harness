"""agent-harness#1011: a ruling line glued onto a provider's preamble is restored, not re-asked.

Live qualification of the fixed president route (2026-09-24): the brokered Grok 4.7 rung
returned a complete, correct 35-finding ruling whose first line was a one-sentence
preamble joined to ``FINDING F001: ...`` with no line break (plain-text output). A
preamble on its OWN line is valid grammar; only the lost break made the ruling invalid.
"""
from __future__ import annotations

from unittest.mock import patch

from phase_loop_runtime import panel_invoker, president_adapter
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.president_adapter import _unglue_finding_lines

FINDINGS = ("F001: [grok] the lock is never released", "F002: [codex] the cache is stale")
GLUED = (
    "I'll adjudicate each board finding before issuing the forcing decision."
    "FINDING F001: DEFERRED — follow-up only\n"
    "FINDING F002: DEFERRED — confirmed closed\n"
    "FORCING DECISION: LAND"
)


def test_the_live_grok_shape_is_invalid_before_and_valid_after():
    assert not panel_invoker._valid_president_grammar(GLUED, FINDINGS)
    fixed = _unglue_finding_lines(GLUED)
    assert panel_invoker._valid_president_grammar(fixed, FINDINGS)
    # whitespace-only: the words are unchanged
    assert fixed.split() == GLUED.replace("decision.FINDING", "decision. FINDING").split()


def test_a_valid_ruling_that_quotes_a_finding_line_is_untouched():
    quoting = (
        "FINDING F001: DEFERRED — see FINDING F002: BLOCKING — quoted from the seat\n"
        "FINDING F002: DEFERRED — ok\n"
        "FORCING DECISION: LAND"
    )
    assert _unglue_finding_lines(quoting) == quoting
    assert panel_invoker._valid_president_grammar(quoting, FINDINGS)


def test_prose_and_a_clean_ruling_are_unchanged():
    clean = "Preamble on its own line.\nFINDING F001: DEFERRED — a\nFINDING F002: DEFERRED — b\nFORCING DECISION: LAND"
    assert _unglue_finding_lines(clean) == clean
    assert _unglue_finding_lines("no ruling here at all") == "no ruling here at all"


def test_the_ladder_accepts_the_glued_ruling_without_a_format_reask(tmp_path):
    # Through the real adapter response path (the in-process control seam under bounded
    # monitoring; the transport returns the live shape) and the real ladder walk.
    calls: list[str] = []

    def transport(self, harness, route_model, prompt, stage, out_dir, *, monitor=None, latch=None):
        calls.append(prompt)
        return 0, GLUED, ""

    seam = president_adapter.build_president_invoke(
        DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}, ladder=["grok"],
    )
    with patch.object(president_adapter.PresidentInvoke, "_transport", transport), patch.object(
        panel_invoker, "launch_provider", lambda *a, **k: None
    ):
        ruling = panel_invoker.invoke_president(findings=FINDINGS, invoke=seam, max_substantive_rounds=3)
    assert ruling.model == "grok" and ruling.format_reasks == 0
    assert len(calls) == 1, "a format re-ask was spent on a whitespace-only defect"
    assert [r.finding_id for r in panel_invoker.president_finding_rulings(ruling)] == ["F001", "F002"]
