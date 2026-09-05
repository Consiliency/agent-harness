"""G-1/G-2/G-6 from the 2026-09-01 codebase review: gate failures must be visible.

Each test pins one previously-silent fail-open path.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from phase_loop_runtime import closeout_validators as cv
from phase_loop_runtime.closeout_validation import verify_enforce_mode

SRC = str(Path(__file__).resolve().parents[1] / "src")

BUILTIN_VALIDATOR_MODULES = {
    "doc_delta_validator",
    "verification_evidence_validator",
    "visual_evidence_validator",
    "visual_avatar_evidence_validator",
    "fab_gate",
}


def test_all_builtin_closeout_validators_register() -> None:
    """G-2: every built-in gate must actually reach the registry.

    Run in a FRESH interpreter that imports only closeout_validators: registration
    happens at module import, so a test-session import order that already pulled
    in other modules would measure that order rather than the contract.
    """
    code = (
        "import phase_loop_runtime.closeout_validators as cv;"
        "print(sorted(f.__module__.rsplit('.',1)[-1] for f in cv.registered_closeout_validators()))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={"PYTHONPATH": SRC, "PATH": "/usr/bin:/bin"}, check=True,
    ).stdout
    registered = set(eval(out.strip()))  # noqa: S307 - our own literal list
    missing = BUILTIN_VALIDATOR_MODULES - registered
    assert not missing, f"built-in closeout gates missing from the registry: {sorted(missing)}"


def test_a_crashing_validator_is_reported_not_swallowed() -> None:
    """G-1: a validator that raises must produce a finding, not vanish."""
    def boom(_ctx):
        raise RuntimeError("gate exploded")

    cv.register_closeout_validator(boom)
    try:
        findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": "block"})
    finally:
        cv._VALIDATORS.remove(boom)

    # ctx=None also trips the real registered gates, which is itself G-1 working:
    # five previously-silent failures now surface. Select OURS by name.
    crashed = [f for f in findings if f.code == "gate_crashed" and "boom" in f.reason]
    assert crashed, f"no gate_crashed finding named boom; got {[f.reason for f in findings]}"
    assert crashed[0].severity == "block"
    assert "did not run" in crashed[0].reason
    assert "UNKNOWN, not pass" in (crashed[0].body or "")


def test_a_lazy_generator_validator_cannot_escape() -> None:
    """G-1: a validator that raises during ITERATION, not on call.

    `CloseoutValidator` permits any iterable. A generator does not execute its
    body until iterated, so wrapping only `fn(ctx)` left the raise outside the
    handler: it propagated out of run_closeout_validators and broke the closeout
    a review gate must never break.
    """
    def lazy_boom(_ctx):
        def gen():
            yield cv.ReviewFinding(code="ok", reason="emitted before the raise")
            raise RuntimeError("raised during iteration")

        return gen()

    cv.register_closeout_validator(lazy_boom)
    try:
        findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": "block"})
    except Exception as exc:  # pragma: no cover - the bug this pins
        pytest.fail(f"a lazy validator escaped closeout: {type(exc).__name__}: {exc}")
    finally:
        cv._VALIDATORS.remove(lazy_boom)
    ours = [f for f in findings if f.code == "gate_crashed" and "lazy_boom" in f.reason]
    assert ours, "a generator that raised during iteration produced no gate_crashed finding"
    # The partial yield before the raise is discarded: the gate did not complete,
    # so its partial output is not a verdict.
    assert not [f for f in findings if f.code == "ok"]


@pytest.mark.parametrize("mode,expected", [("warn", "warn"), ("block", "block")])
def test_gate_crashed_honours_the_review_mode(mode, expected) -> None:
    """G-1: the crash finding is appended past the severity-rewrite loop.

    If it does not apply the mode itself it blocks every closeout under the
    DEFAULT `warn` posture — a far larger behaviour change than intended. This
    caught exactly that during development.
    """
    def boom(_ctx):
        raise RuntimeError("gate exploded")

    cv.register_closeout_validator(boom)
    try:
        findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": mode})
    finally:
        cv._VALIDATORS.remove(boom)
    ours = [f for f in findings if f.code == "gate_crashed" and "boom" in f.reason]
    assert ours and ours[0].severity == expected


@pytest.mark.parametrize(
    "value,default,expected",
    [
        (None, "hard", "hard"), (None, "warn", "warn"),   # unset -> the DECLARED default
        ("hard", "warn", "hard"), ("warn", "hard", "warn"),  # explicit always wins
        ("HARD", "warn", "hard"), ("  warn  ", "hard", "warn"),  # case/space tolerant
        ("nonsense", "hard", "hard"), ("", "warn", "warn"),  # junk -> the default
    ],
)
def test_verify_enforce_mode_defaults_are_declared(value, default, expected) -> None:
    """G-6: one parse point; the unset-default is declared by the caller."""
    env = {} if value is None else {"PHASE_LOOP_VERIFY_ENFORCE": value}
    assert verify_enforce_mode(env, default=default) == expected


def test_no_module_reads_the_verify_enforce_env_var_directly() -> None:
    """G-6 grep-guard: the name may only appear where it is parsed or documented."""
    src = Path(SRC) / "phase_loop_runtime"
    offenders = []
    for path in src.rglob("*.py"):
        if path.name == "closeout_validation.py":
            continue  # THE parse point
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if "PHASE_LOOP_VERIFY_ENFORCE" in line and "environ" in line:
                offenders.append(f"{path.name}:{i}")
    assert not offenders, f"direct os.environ reads of PHASE_LOOP_VERIFY_ENFORCE: {offenders}"
