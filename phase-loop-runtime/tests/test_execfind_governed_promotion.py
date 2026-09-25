"""A prose finding stays attributable without turning a dissent into approval."""

from phase_loop_runtime.governed_premerge import run_governed_premerge_loop
from phase_loop_runtime.governed_review import _gate_result_from_panel
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult


def _four_vendor_panel(*, claude_text: str) -> PanelResult:
    return PanelResult((
        PanelLegResult("codex", "OK", "AGREE", seat_key="codex:gpt-6-astra:max:red-team"),
        PanelLegResult("gemini", "OK", "AGREE", seat_key="gemini:gemini-3.8-flash:high:alternative-approach"),
        PanelLegResult("grok", "OK", "AGREE", seat_key="grok:grok-4.7:max:adversarial"),
        PanelLegResult("claude", "OK", claude_text, seat_key="claude:claude-opus-5-5:max:correctness"),
    ))


def test_four_vendor_optional_prose_dissent_cannot_promote():
    panel = _four_vendor_panel(claude_text="FINDING F001: blocking prose concern\nDISAGREE")
    gate = _gate_result_from_panel(panel, reviewed_sha="a" * 40)

    assert not gate.promoted
    assert gate.reason == "unresolved_prose_dissent"
    assert any(f.code == "finding_prose" and f.severity == "warn" for f in gate.findings)
    assert not any(f.code == "panel_block" for f in gate.findings)

    result = run_governed_premerge_loop(
        artifact="reviewed artifact", author_executor="train-coordinator",
        run_mode="governed", max_rounds=1, invoke=lambda **_kwargs: gate,
    )
    assert not result.mergeable
    assert result.rounds == 1
    assert any(f.code == "finding_prose" and f.severity == "warn" for f in result.findings)


def test_two_reviewer_floor_does_not_override_prose_dissent():
    four = _four_vendor_panel(claude_text="FINDING F001: blocking prose concern\nDISAGREE")
    panel = PanelResult((four.legs[0], four.legs[-1]))
    gate = _gate_result_from_panel(panel, reviewed_sha="a" * 40)

    assert not gate.promoted
    assert gate.reason == "unresolved_prose_dissent"
    result = run_governed_premerge_loop(
        artifact="reviewed artifact", author_executor="train-coordinator",
        run_mode="governed", max_rounds=1, invoke=lambda **_kwargs: gate,
    )
    assert not result.mergeable
    assert result.reason == "non_convergence"


def test_four_vendor_agreement_still_promotes():
    panel = _four_vendor_panel(claude_text="AGREE")
    gate = _gate_result_from_panel(panel, reviewed_sha="a" * 40)

    assert gate.promoted
    assert gate.reason is None
