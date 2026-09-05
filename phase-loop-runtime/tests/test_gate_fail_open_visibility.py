"""G-1/G-2/G-6 from the 2026-09-01 codebase review: gate failures must be visible.

Each test pins one previously-silent fail-open path.
"""
from __future__ import annotations

import ast
import importlib.abc
import importlib.machinery
import subprocess
import sys
from pathlib import Path

import pytest

from phase_loop_runtime import closeout_validators as cv
from phase_loop_runtime.closeout_validation import verify_enforce_mode

SRC = str(Path(__file__).resolve().parents[1] / "src")

# Pinned as a literal on purpose: if the runtime table shrinks, this test must
# notice, not follow it.
BUILTIN_VALIDATOR_MODULES = {
    "doc_delta_validator",
    "verification_evidence_validator",
    "visual_evidence_validator",
    "visual_avatar_evidence_validator",
    "fab_gate",
}


def test_builtin_table_matches_the_pinned_set() -> None:
    assert set(cv.BUILTIN_VALIDATOR_MODULES) == BUILTIN_VALIDATOR_MODULES


def test_all_builtin_closeout_validators_register_on_the_production_path() -> None:
    """G-2: all five gates must register on the path the CLI actually takes.

    `cli` imports `closeout`, which imports this module, so the module-level
    `load_builtin_closeout_validators()` runs while `closeout_validators` is
    still initialising and `fab_gate` -- which imports back from it -- fails.
    That registered 4 of 5 with `fab_gate` silently absent, on the REAL
    entrypoint. An earlier version of this test imported `closeout_validators`
    alone, which passes while production does not; the #787 board (codex leg)
    caught that. Assert the production order, after a gate run.
    """
    code = (
        "import phase_loop_runtime.closeout;"                     # what cli imports first
        "import phase_loop_runtime.closeout_validators as cv;"
        "cv.run_closeout_validators(ctx=None, env={'PHASE_LOOP_REVIEW':'warn'});"
        "print(sorted(f.__module__.rsplit('.',1)[-1] for f in cv.registered_closeout_validators()))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={"PYTHONPATH": SRC, "PATH": "/usr/bin:/bin"}, check=True,
    ).stdout.strip().splitlines()[-1]
    registered = set(eval(out))  # noqa: S307 - our own literal list
    missing = BUILTIN_VALIDATOR_MODULES - registered
    assert not missing, f"built-in closeout gates missing on the production path: {sorted(missing)}"


def test_an_unnameable_validator_cannot_escape_the_handler() -> None:
    """G-1: building the crash report must not itself raise.

    The contract permits any callable. One whose __call__ AND __repr__ raise
    escaped from inside the very handler meant to stop it. #787 board, round 2.
    """
    class Unnameable:
        def __call__(self, _ctx):
            raise RuntimeError("call crash")

        def __repr__(self):
            raise RuntimeError("repr crash")

    bad = Unnameable()
    cv.register_closeout_validator(bad)
    try:
        findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": "block"})
    except Exception as exc:  # pragma: no cover - the bug this pins
        pytest.fail(f"an unnameable validator escaped: {type(exc).__name__}: {exc}")
    finally:
        cv._VALIDATORS.remove(bad)
    assert [f for f in findings if f.code == "gate_crashed"]


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


class _RaisingLoader(importlib.abc.Loader):
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def create_module(self, spec):  # noqa: D401 - importlib protocol
        return None

    def exec_module(self, module) -> None:
        raise self._exc


class _RaisingFinder(importlib.abc.MetaPathFinder):
    """Make ``phase_loop_runtime.<name>`` raise ``exc`` while it executes."""

    def __init__(self, name: str, exc: BaseException) -> None:
        self.fullname = f"phase_loop_runtime.{name}"
        self._exc = exc

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.fullname:
            return None
        return importlib.machinery.ModuleSpec(fullname, _RaisingLoader(self._exc))


@pytest.fixture
def isolated_registry():
    """Snapshot/restore the registry and the unavailable-builtin record."""
    validators = list(cv._VALIDATORS)
    unavailable = dict(cv._UNAVAILABLE_BUILTINS)
    cv.clear_closeout_validators()
    try:
        yield
    finally:
        cv._VALIDATORS[:] = validators
        cv._UNAVAILABLE_BUILTINS.clear()
        cv._UNAVAILABLE_BUILTINS.update(unavailable)


@pytest.fixture
def broken_builtin(monkeypatch, isolated_registry):
    """Register an injected built-in module name that raises ``exc`` on import."""
    installed: list[_RaisingFinder] = []

    def _install(name: str, exc: BaseException) -> None:
        finder = _RaisingFinder(name, exc)
        installed.append(finder)
        sys.meta_path.insert(0, finder)
        sys.modules.pop(finder.fullname, None)
        monkeypatch.setattr(cv, "BUILTIN_VALIDATOR_MODULES", (*cv.BUILTIN_VALIDATOR_MODULES, name))

    yield _install
    for finder in installed:
        sys.meta_path.remove(finder)
        sys.modules.pop(finder.fullname, None)


@pytest.mark.parametrize("mode,expected", [("warn", "warn"), ("block", "block")])
def test_an_unimportable_builtin_is_a_closeout_finding(broken_builtin, mode, expected) -> None:
    """G-2: a gate that never registered reaches the closeout ARTIFACT, not only the log.

    Injects an import failure for a built-in module name, loads, then runs: the
    retry at closeout time fails again (the module is still unimportable), so the
    closeout carries ``gate_unavailable`` at the mode-applied severity.
    """
    broken_builtin("injected_missing_validator", ImportError("injected: module unavailable"))
    cv.load_builtin_closeout_validators()
    assert "injected_missing_validator" in cv.unavailable_builtin_closeout_validators()

    findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": mode})
    ours = [f for f in findings if f.code == "gate_unavailable"]
    assert [f.reason for f in ours] == [
        "built-in closeout validator injected_missing_validator is not importable; its gate never registered"
    ]
    assert ours[0].severity == expected
    assert "injected: module unavailable" in (ours[0].body or "")
    assert "UNKNOWN, not pass" in (ours[0].body or "")


def test_gate_unavailable_blocks_the_closeout_under_block(broken_builtin) -> None:
    """G-2 end to end: the finding turns into the closeout blocker, not a note."""
    broken_builtin("injected_missing_validator", ImportError("injected"))
    cv.load_builtin_closeout_validators()
    findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": "block"})
    folded = cv.apply_review_findings(
        findings=findings, terminal={"terminal_status": "review_ready"}, automation={}, blocker={}
    )
    assert folded["terminal"]["terminal_status"] == "blocked"
    assert folded["automation"]["blocker_class"] == "review_gate_block"
    assert "gate_unavailable" in folded["blocker"]["blocker_summary"]
    assert "injected_missing_validator" in folded["blocker"]["blocker_summary"]
    assert [r["code"] for r in folded["results"]] == ["gate_unavailable"]


def test_a_builtin_that_becomes_importable_registers_on_retry(broken_builtin, monkeypatch) -> None:
    """G-2: the load-time failure can be an import-order circularity that is gone by
    closeout time. Then the gate registers and RUNS, and no finding is emitted.

    Modelled with a real ImportError at load and a real module at run time.
    """
    broken_builtin("injected_late_validator", ImportError("injected: not yet"))
    cv.load_builtin_closeout_validators()
    assert "injected_late_validator" in cv.unavailable_builtin_closeout_validators()

    # Now make the module importable: replace the raising finder with a module
    # that registers a validator on import.
    import types

    ran: list[object] = []

    def late_validator(ctx):
        ran.append(ctx)
        return ()

    module = types.ModuleType("phase_loop_runtime.injected_late_validator")

    class _RegisteringLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return module

        def exec_module(self, mod):
            cv.register_closeout_validator(late_validator)

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != "phase_loop_runtime.injected_late_validator":
                return None
            return importlib.machinery.ModuleSpec(fullname, _RegisteringLoader())

    finder = _Finder()
    sys.meta_path.insert(0, finder)
    try:
        findings = cv.run_closeout_validators(ctx="ctx-token", env={"PHASE_LOOP_REVIEW": "block"})
    finally:
        sys.meta_path.remove(finder)
        sys.modules.pop("phase_loop_runtime.injected_late_validator", None)
    assert not [f for f in findings if f.code == "gate_unavailable"]
    assert ran == ["ctx-token"], "the late-registered gate did not run in the same closeout"
    assert "injected_late_validator" not in cv.unavailable_builtin_closeout_validators()


def test_a_present_but_broken_builtin_fails_load_loudly(broken_builtin) -> None:
    """G-2 narrowing pin: the guard catches ImportError ONLY.

    A module that is present but raises while executing its own imports must NOT
    be recorded as "unavailable" (that is the silent-drop the narrowing exists to
    prevent): it propagates. Reverting the guard to ``except Exception`` fails this.
    """
    broken_builtin("injected_broken_validator", RuntimeError("injected: broken while importing"))
    with pytest.raises(RuntimeError, match="broken while importing"):
        cv.load_builtin_closeout_validators()
    assert "injected_broken_validator" not in cv.unavailable_builtin_closeout_validators()


def test_clearing_the_registry_also_clears_the_unavailable_record(broken_builtin) -> None:
    broken_builtin("injected_missing_validator", ImportError("injected"))
    cv.load_builtin_closeout_validators()
    assert cv.unavailable_builtin_closeout_validators()
    cv.clear_closeout_validators()
    assert cv.unavailable_builtin_closeout_validators() == {}
    assert not [f for f in cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": "block"})]


def test_the_live_call_sites_declare_their_defaults(monkeypatch) -> None:
    """G-6: pin the DEFAULTS AT THE CALL SITES, not just the parser.

    The PR names "which module happened to ask" as the hazard; the parser test
    cannot see a call site flipping its declared default. These are the three
    live consumers and the posture each one gets when the variable is unset.
    """
    from phase_loop_runtime import runner, train_runner
    from phase_loop_runtime.closeout_validation import verification_enforcement_mode

    monkeypatch.delenv("PHASE_LOOP_VERIFY_ENFORCE", raising=False)
    assert runner._verification_enforcement_mode() == "warn"
    assert train_runner._train_reverify_enforcement_mode() == "warn"
    assert verification_enforcement_mode({}) == "hard"
    assert verification_enforcement_mode(os_environ_without_the_variable()) == "hard"

    # and the explicit value reaches all three the same way
    monkeypatch.setenv("PHASE_LOOP_VERIFY_ENFORCE", "hard")
    assert runner._verification_enforcement_mode() == "hard"
    assert train_runner._train_reverify_enforcement_mode() == "hard"
    monkeypatch.setenv("PHASE_LOOP_VERIFY_ENFORCE", "warn")
    assert verification_enforcement_mode(dict(__import__("os").environ)) == "warn"


def os_environ_without_the_variable() -> dict:
    import os

    return {k: v for k, v in os.environ.items() if k != "PHASE_LOOP_VERIFY_ENFORCE"}


_ENV_READERS = {"get", "getenv", "environ"}


def _reads_verify_enforce(node: ast.AST) -> bool:
    """True when ``node`` is an environment read keyed on the verify-enforce variable.

    Matches ``os.environ.get(X)``, ``os.environ[X]``, ``environ.get(X)``,
    ``os.getenv(X)`` and ``getenv(X)`` where X is the literal name or the
    ``VERIFY_ENFORCE_ENV`` constant -- across lines, in any spelling.
    """
    def names_the_var(expr: ast.AST) -> bool:
        if isinstance(expr, ast.Constant):
            return expr.value == "PHASE_LOOP_VERIFY_ENFORCE"
        if isinstance(expr, ast.Name):
            return expr.id == "VERIFY_ENFORCE_ENV"
        if isinstance(expr, ast.Attribute):
            return expr.attr == "VERIFY_ENFORCE_ENV"
        return False

    def is_env_reader(func: ast.AST) -> bool:
        chain = []
        while isinstance(func, ast.Attribute):
            chain.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            chain.append(func.id)
        return bool(_ENV_READERS & set(chain)) and ("environ" in chain or "getenv" in chain)

    if isinstance(node, ast.Call) and is_env_reader(node.func):
        return any(names_the_var(a) for a in node.args)
    if isinstance(node, ast.Subscript) and is_env_reader(node.value):
        return names_the_var(node.slice)
    return False


def test_no_module_reads_the_verify_enforce_env_var_directly() -> None:
    """G-6 guard: outside the parse point, nothing reads the variable from the environment.

    AST-based, so ``os.environ.get(VERIFY_ENFORCE_ENV, "hard")``, ``os.getenv``,
    ``from os import environ`` and multi-line spellings are all caught -- the
    literal-on-one-line grep this replaces missed every one of them.
    """
    src = Path(SRC) / "phase_loop_runtime"
    offenders = []
    for path in src.rglob("*.py"):
        if path.name == "closeout_validation.py":
            continue  # THE parse point
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if _reads_verify_enforce(node):
                offenders.append(f"{path.relative_to(src)}:{node.lineno}")
    assert not offenders, f"direct environment reads of PHASE_LOOP_VERIFY_ENFORCE: {offenders}"


@pytest.mark.parametrize(
    "snippet",
    [
        'os.environ.get("PHASE_LOOP_VERIFY_ENFORCE", "hard")',
        "os.environ.get(VERIFY_ENFORCE_ENV, 'hard')",
        'os.getenv("PHASE_LOOP_VERIFY_ENFORCE")',
        "getenv(cv.VERIFY_ENFORCE_ENV)",
        'environ["PHASE_LOOP_VERIFY_ENFORCE"]',
        'os.environ.get(\n    "PHASE_LOOP_VERIFY_ENFORCE",\n    "warn",\n)',
    ],
)
def test_the_guard_recognises_each_direct_read_spelling(snippet) -> None:
    """The guard's own detector, checked against the spellings it must catch."""
    tree = ast.parse(snippet)
    assert any(_reads_verify_enforce(n) for n in ast.walk(tree)), snippet


def test_the_guard_ignores_the_sanctioned_call() -> None:
    tree = ast.parse('verify_enforce_mode(env, default="warn")')
    assert not any(_reads_verify_enforce(n) for n in ast.walk(tree))
