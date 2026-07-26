"""Gemini/agy leg: headless legs may READ but must not be asked to RUN.

The gemini seat returned EMPTY in 6 of 11 rounds of the model-tier review (#309) and was
misread as flakiness. Root cause: headless `agy` auto-denies the "command" permission and
then emits NOTHING (rc==0, zero bytes). It reads the staged files fine — our review
prompts were asking it to VERIFY BY RUNNING, which is what triggered the denial.

These tests drive the PRODUCTION path and assert on the argv the code actually builds.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi


class _FakeProc:
    def __init__(self, stdout: str = "ok", stderr: str = "", returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture()
def staged(tmp_path: Path):
    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    review_dir.mkdir(); out_dir.mkdir()
    (review_dir / "review-instructions.md").write_text("be rigorous", encoding="utf-8")
    (review_dir / "review-bundle.md").write_text("the diff", encoding="utf-8")
    return review_dir, out_dir


def _gemini_argv(monkeypatch, staged) -> list[str]:
    review_dir, out_dir = staged
    seen: list[list[str]] = []
    monkeypatch.setattr(
        pi, "_run_leg_with_liveness",
        lambda cmd, **kw: (seen.append(list(cmd)), _FakeProc())[1],
    )
    pi._exec_leg("gemini", review_dir, out_dir, timeout_s=60, artifact="A", env={})
    return seen[0]


def test_gemini_prompt_permits_reading_and_forbids_running(monkeypatch, staged):
    prompt = _gemini_argv(monkeypatch, staged)[-1]
    assert prompt.startswith("OPERATING CONSTRAINT"), "constraint is not first"
    low = prompt.lower()
    assert "may read the staged files" in low, "the leg is not told it MAY read"
    assert "may not run shell commands" in low, "the leg is not told it may NOT run"


def test_gemini_keeps_the_pointer_form_bundle_never_inlined(monkeypatch, staged):
    """The bundle must stay a staged FILE. Inlining it would move untrusted material
    into the leg's own instruction channel and add an argv-size surface — the mistake the
    abandoned #313 made on a misdiagnosis."""
    prompt = _gemini_argv(monkeypatch, staged)[-1]
    assert "the diff" not in prompt, "bundle contents were inlined into the prompt"
    assert "review-bundle.md" in prompt, "the pointer to the staged bundle is missing"


def test_other_legs_are_untouched(monkeypatch, staged):
    """Only the gemini leg gets the preamble; the shared prompt (and every other leg's
    byte-identical argv golden) must be unchanged."""
    review_dir, out_dir = staged
    seen: list[list[str]] = []
    monkeypatch.setattr(
        pi, "_run_leg_with_liveness",
        lambda cmd, **kw: (seen.append(list(cmd)), _FakeProc())[1],
    )
    pi._exec_leg("grok", review_dir, out_dir, timeout_s=60, artifact="A", env={})
    assert not any("OPERATING CONSTRAINT" in str(a) for a in seen[0]), (
        "the gemini preamble leaked into another leg"
    )
