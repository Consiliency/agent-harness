"""Gemini/agy headless TOOL-DENIAL regression (panel_invoker).

Root cause found while diagnosing the gemini seat returning EMPTY in 6 of 11 rounds of
the model-tier review (#309): the shared leg prompt is a POINTER to files staged under
``review_dir``, and `agy` running headless cannot READ them — it auto-denies the
permission, prints its reason on stderr, and exits rc==0 with a ZERO-BYTE body. The
panel classified that as an anonymous soft-empty and dropped the leg silently.

These tests drive the PRODUCTION path (`_exec_leg`) with a faked subprocess runner so
that deleting either fix makes them FAIL. An earlier revision of this module asserted on
strings concatenated inside the test body and never invoked `_exec_leg` at all — it was
tautological and both the codex and gemini review legs flagged it. Do not reintroduce
that shape: assert on the argv the production code actually builds.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi


_REAL_AGY_STDERR = (
    'jetski: no output produced — a tool required the "command" permission that '
    "headless mode cannot prompt for, so it was auto-denied. Add an allow-rule under "
    "permissions.allow in settings.json (e.g. command(<target>)). Alternatively, "
    "re-run with --dangerously-skip-permissions to auto-approve all tools."
)


class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture()
def staged(tmp_path: Path) -> tuple[Path, Path]:
    """A review_dir staged the way the panel stages it, plus an out_dir."""
    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()
    (review_dir / "review-instructions.md").write_text(
        "INSTRUCTIONS-SENTINEL: be rigorous.", encoding="utf-8"
    )
    (review_dir / "review-bundle.md").write_text(
        "BUNDLE-SENTINEL: the diff under review.", encoding="utf-8"
    )
    return review_dir, out_dir


def _run_gemini(monkeypatch, staged, *, proc: _FakeProc) -> tuple[list[str], tuple]:
    """Invoke the real `_exec_leg` gemini branch; capture the argv it builds."""
    review_dir, out_dir = staged
    seen: list[list[str]] = []

    def _fake_runner(cmd, **kwargs):
        seen.append(list(cmd))
        return proc

    monkeypatch.setattr(pi, "_run_leg_with_liveness", _fake_runner)
    result = pi._exec_leg(
        "gemini", review_dir, out_dir, timeout_s=60, artifact="ARTIFACT", env={}
    )
    return (seen[0] if seen else []), result


def _prompt_of(argv: list[str]) -> str:
    return argv[argv.index("-p") + 1]


def test_production_argv_inlines_the_staged_material(monkeypatch, staged):
    """FIX 1. Deleting the inlining in `_exec_leg` must fail this.

    The pointer form alone is unreadable to a headless agy, so the staged files must
    reach the leg through the prompt itself.
    """
    argv, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    prompt = _prompt_of(argv)
    assert "INSTRUCTIONS-SENTINEL" in prompt, "staged instructions never reached the leg"
    assert "BUNDLE-SENTINEL" in prompt, "staged bundle never reached the leg"


def test_production_argv_puts_the_constraint_before_the_untrusted_material(
    monkeypatch, staged
):
    """Ordering is load-bearing: the operating constraint must precede the bundle,
    which is UNTRUSTED material under review."""
    argv, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    prompt = _prompt_of(argv)
    assert prompt.startswith("OPERATING CONSTRAINT"), "constraint is not first"
    assert prompt.index("OPERATING CONSTRAINT") < prompt.index("BUNDLE-SENTINEL")


def test_headless_denial_returns_nonzero_with_the_cli_reason(monkeypatch, staged):
    """FIX 2. Deleting the denial branch must fail this.

    rc==0 + empty body + the CLI's auto-denied marker must surface as a DIAGNOSABLE
    failure carrying the CLI's own explanation — never an anonymous empty.
    """
    argv, (rc, text, log) = _run_gemini(
        monkeypatch, staged, proc=_FakeProc(stdout="", stderr=_REAL_AGY_STDERR)
    )
    assert rc != 0, "a headless tool-denial must not be reported as success"
    assert text == ""
    assert "TOOL-DENIAL" in log, "the failure reason was not surfaced"
    assert "auto-denied" in log, "the CLI's own explanation was discarded"


def test_denial_is_not_retried_as_a_transient_stall(monkeypatch, staged):
    """The permission is absent, not flaky — retrying reproduces it exactly. The denial
    check must run BEFORE the soft-empty/stall path, so only ONE attempt is made."""
    review_dir, out_dir = staged
    calls: list[list[str]] = []

    def _fake_runner(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeProc(stdout="", stderr=_REAL_AGY_STDERR)

    monkeypatch.setattr(pi, "_run_leg_with_liveness", _fake_runner)
    pi._exec_leg("gemini", review_dir, out_dir, timeout_s=60, artifact="A", env={})
    assert len(calls) == 1, f"denial was retried {len(calls)}x; it is not transient"


def test_oversize_bundle_keeps_the_pointer_rather_than_truncating(monkeypatch, staged):
    """Past the cap we must NOT truncate material a reviewer is meant to judge —
    a silently half-inlined bundle would be worse than the pointer form."""
    review_dir, _out = staged
    (review_dir / "review-bundle.md").write_text(
        "X" * (pi._GEMINI_INLINE_MAX_BYTES + 1), encoding="utf-8"
    )
    argv, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    prompt = _prompt_of(argv)
    assert "XXXX" not in prompt, "oversize bundle was inlined (or truncated) anyway"
    assert not prompt.startswith("OPERATING CONSTRAINT"), "should fall back to pointer form"


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


def test_untrusted_material_never_has_the_last_word(monkeypatch, staged):
    """INJECTION (CR round 2). Constraint-first defends PRIMACY; without an epilogue the
    untrusted bundle owns RECENCY — and the verdict-format rule tells a tail-injection
    exactly what shape to imitate. The prompt must END with the authority re-assertion."""
    argv, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    prompt = _prompt_of(argv)
    assert prompt.rstrip().endswith("ending with the structured verdict line."), (
        "untrusted material has the last word — epilogue missing or not last"
    )
    assert prompt.index("BUNDLE-SENTINEL") < prompt.index("END OF ALL INLINED MATERIAL")


def test_section_fences_carry_an_unguessable_per_run_nonce(monkeypatch, staged):
    """A PR author controls the diff, therefore the bundle bytes, therefore could forge a
    STATIC section header. Fences must carry a per-run nonce the material cannot know,
    and the nonce must differ between runs."""
    import re as _re
    argv1, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    argv2, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    p1, p2 = _prompt_of(argv1), _prompt_of(argv2)
    n1 = _re.search(r"=== BEGIN INLINED review-bundle\.md \[([0-9a-f]{8,})\] ===", p1)
    assert n1, "bundle fence carries no nonce"
    nonce = n1.group(1)
    assert f"=== END INLINED review-bundle.md [{nonce}] ===" in p1, "no closing fence"
    assert nonce in p1.split("BUNDLE-SENTINEL")[0], "nonce not declared before the material"
    n2 = _re.search(r"=== BEGIN INLINED review-bundle\.md \[([0-9a-f]{8,})\] ===", p2)
    assert n2 and n2.group(1) != nonce, "nonce is not per-run (replayable across runs)"


def test_preamble_declares_the_section_count_and_disarms_forged_headers(monkeypatch, staged):
    argv, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    head = _prompt_of(argv).split("BUNDLE-SENTINEL")[0]
    assert "exactly 2 section(s)" in head, "section count not declared"
    assert "FINDING TO REPORT" in head, "in-material instructions not disarmed"


def test_denial_marker_on_stderr_does_not_discard_a_REAL_review(monkeypatch, staged):
    """M4 (surviving mutation found by the CR): the denial branch must require an EMPTY
    body. A genuine review whose stderr merely carries auto-denied chatter must pass
    through as success, not be discarded as a leg failure."""
    _argv, (rc, text, _log) = _run_gemini(
        monkeypatch,
        staged,
        proc=_FakeProc(stdout="A real review body.\n\nVERDICT: AGREE", stderr=_REAL_AGY_STDERR),
    )
    assert rc == 0, "a real review was discarded because stderr mentioned auto-denied"
    assert "VERDICT: AGREE" in text


def test_advisory_mode_does_not_demand_a_structured_verdict(monkeypatch, staged):
    """CR round 2 (codex): `verdict_required = mode != "advisory"` — advisory mode's
    contract is substantial prose with NO verdict required. The preamble must not
    contradict the mode the leg is running in."""
    review_dir, out_dir = staged
    seen: list[list[str]] = []
    monkeypatch.setattr(
        pi, "_run_leg_with_liveness",
        lambda cmd, **kw: (seen.append(list(cmd)), _FakeProc(stdout="prose"))[1],
    )
    pi._exec_leg("gemini", review_dir, out_dir, timeout_s=60, artifact="A",
                 mode="advisory", env={})
    head = _prompt_of(seen[0]).split("BUNDLE-SENTINEL")[0]
    assert "no verdict" in head.lower(), "advisory run still demands a verdict"
    assert "must END with the structured verdict line" not in head


def test_by_reference_material_must_be_declared_unverified(monkeypatch, staged):
    """CR round 2 (codex): the by-reference contract tells legs to OPEN referenced paths
    (contents deliberately not inlined). This leg cannot. It must DECLARE the gap rather
    than review without the material and stay silent about it."""
    review_dir, _out = staged
    (review_dir / "review-bundle.md").write_text(
        "BUNDLE-SENTINEL\n\n" + pi._CONTEXT_REFS_HEADER + "\n\n- /some/spec.pdf\n",
        encoding="utf-8",
    )
    argv, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    head = _prompt_of(argv).split("BUNDLE-SENTINEL")[0]
    assert "UNVERIFIED" in head, "by-reference gap is not required to be declared"
    assert "cannot" in head.lower() or "CANNOT" in head


def test_no_by_reference_clause_when_there_are_no_refs(monkeypatch, staged):
    """Don't tell a leg to declare UNVERIFIED paths when the bundle has none — that
    would invite a spurious section in every ordinary review."""
    argv, _ = _run_gemini(monkeypatch, staged, proc=_FakeProc(stdout="a review"))
    head = _prompt_of(argv).split("BUNDLE-SENTINEL")[0]
    assert "UNVERIFIED" not in head
