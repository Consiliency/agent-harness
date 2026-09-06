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


@pytest.mark.parametrize("mode,expected", [("warn", "warn"), ("block", "block")])
def test_a_builtin_that_breaks_on_retry_cannot_escape(broken_builtin, mode, expected) -> None:
    """G-2: the closeout-time retry runs INSIDE the exception boundary.

    Load-time: the module raises ImportError and is recorded unavailable (the
    honest outcome). Closeout-time: the same module now raises something that
    is NOT an ImportError. ``_import_builtin_validator`` deliberately lets that
    through, and the retry used to be the one import in run_closeout_validators
    outside any handler -- so the RuntimeError propagated out of the closeout a
    review gate must never break. Found by the #787 board (fable seat, round 2).
    """
    broken_builtin("injected_flaky_validator", ImportError("injected: not yet"))
    cv.load_builtin_closeout_validators()
    assert "injected_flaky_validator" in cv.unavailable_builtin_closeout_validators()

    # Same name, now broken while executing rather than missing.
    finder = _RaisingFinder("injected_flaky_validator", RuntimeError("injected: broken on retry"))
    sys.meta_path.insert(0, finder)
    try:
        findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": mode})
    except Exception as exc:  # pragma: no cover - the bug this pins
        pytest.fail(f"a retried built-in escaped closeout: {type(exc).__name__}: {exc}")
    finally:
        sys.meta_path.remove(finder)
        sys.modules.pop(finder.fullname, None)
    ours = [f for f in findings if "injected_flaky_validator" in f.reason]
    assert [f.code for f in ours] == ["gate_crashed"], [f.reason for f in findings]
    assert ours[0].severity == expected
    assert "RuntimeError: injected: broken on retry" in (ours[0].body or "")
    assert "UNKNOWN, not pass" in (ours[0].body or "")
    # Still unresolved: the next closeout retries it again rather than forgetting it.
    assert "injected_flaky_validator" in cv.unavailable_builtin_closeout_validators()


class _UnformattableError(RuntimeError):
    """An exception whose ``__str__`` raises -- formatting it is itself a crash."""

    def __str__(self) -> str:
        raise ValueError("injected: __str__ raised")


@pytest.mark.parametrize("mode,expected", [("warn", "warn"), ("block", "block")])
def test_a_builtin_whose_exception_cannot_be_formatted_cannot_escape(
    broken_builtin, mode, expected
) -> None:
    """G-2: describing the retry crash must not be able to raise.

    The validator-crash handler already guards the validator NAME against a
    raising ``__repr__`` (#787 board, codex leg). The retry handler formatted
    the exception itself into the finding body, and an exception whose
    ``__str__`` raises escaped from inside the handler that exists to contain
    it. Found by the #794 board (codex leg, round 1).
    """
    broken_builtin("injected_flaky_validator", ImportError("injected: not yet"))
    cv.load_builtin_closeout_validators()
    assert "injected_flaky_validator" in cv.unavailable_builtin_closeout_validators()

    finder = _RaisingFinder("injected_flaky_validator", _UnformattableError("hidden"))
    sys.meta_path.insert(0, finder)
    try:
        findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": mode})
    except Exception as exc:  # pragma: no cover - the bug this pins
        pytest.fail(f"a retried built-in escaped closeout: {type(exc).__name__}")
    finally:
        sys.meta_path.remove(finder)
        sys.modules.pop(finder.fullname, None)
    ours = [f for f in findings if "injected_flaky_validator" in f.reason]
    assert [f.code for f in ours] == ["gate_crashed"], [f.reason for f in findings]
    assert ours[0].severity == expected
    # The type still names the crash; the unformattable message is replaced, not propagated.
    assert "_UnformattableError" in (ours[0].body or "")
    assert "UNKNOWN, not pass" in (ours[0].body or "")
    assert "injected_flaky_validator" in cv.unavailable_builtin_closeout_validators()


def test_a_validator_yielding_a_non_finding_cannot_escape() -> None:
    """G-1: the severity rewrite is inside the boundary too.

    ``replace`` on something that is not a ReviewFinding raises TypeError; that
    rewrite ran in a loop below the handler and escaped like the lazy generator.
    """
    def junk(_ctx):
        return ["not a finding"]

    cv.register_closeout_validator(junk)
    try:
        findings = cv.run_closeout_validators(ctx=None, env={"PHASE_LOOP_REVIEW": "block"})
    except Exception as exc:  # pragma: no cover - the bug this pins
        pytest.fail(f"a junk-yielding validator escaped closeout: {type(exc).__name__}: {exc}")
    finally:
        cv._VALIDATORS.remove(junk)
    ours = [f for f in findings if f.code == "gate_crashed" and "junk" in f.reason]
    assert ours, "a validator yielding a non-finding produced no gate_crashed finding"
    assert "not a finding" not in [getattr(f, "code", f) for f in findings]


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


def _env_aliases(tree: ast.Module) -> tuple[set[str], set[str], set[str]]:
    """Names bound in ``tree`` to the ``os`` module, ``os.environ`` and ``os.getenv``.

    Resolves ``import os [as X]``, ``from os import environ [as X]`` and
    ``from os import getenv [as X]`` at any depth of the module, and single-name
    assignment rebinding of any resolved spelling (``env = _os.environ``,
    ``ge = os.getenv``, ``o = os``) to a fixed point. The parse point itself is
    written that way (``closeout_validation.verify_enforce_mode``: ``import os
    as _os`` / ``env = _os.environ`` / ``env.get(VERIFY_ENFORCE_ENV)``), so a
    guard that did not follow it swept the sanctioned function's idiom as
    nothing at all and its skip was inert -- found by the #794 board (fable
    seat, round 1) and pinned by test_the_sweep_skip_is_load_bearing. Binding is
    name-level, not flow-sensitive: once a name is bound to environ anywhere in
    the module it is treated as environ everywhere in it (over-approximation,
    the right direction for a guard). NOT followed: re-exports through other
    modules, attribute/tuple targets, and containers. The recogniser tests below
    are the list of what IS covered.
    """
    modules, environs, getenvs = {"os"}, {"environ"}, {"getenv"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    modules.add(alias.asname or "os")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name == "environ":
                    environs.add(alias.asname or "environ")
                elif alias.name == "getenv":
                    getenvs.add(alias.asname or "getenv")
    # Assignment rebinding, iterated to a fixed point because ast.walk order is
    # breadth-first, not source order, and a chain (a = os; b = a.environ) may
    # be visited value-before-definition.
    assigns = [
        (node.targets[0].id, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]
    changed = True
    while changed:
        changed = False
        aliases = (modules, environs, getenvs)
        for target, value in assigns:
            if isinstance(value, ast.Name) and value.id in modules and target not in modules:
                modules.add(target)
                changed = True
            elif _is_environ(value, aliases) and target not in environs:
                environs.add(target)
                changed = True
            elif _is_getenv(value, aliases) and target not in getenvs:
                getenvs.add(target)
                changed = True
    return modules, environs, getenvs


def _names_the_var(expr: ast.AST) -> bool:
    if isinstance(expr, ast.Constant):
        return expr.value == "PHASE_LOOP_VERIFY_ENFORCE"
    if isinstance(expr, ast.Name):
        return expr.id == "VERIFY_ENFORCE_ENV"
    if isinstance(expr, ast.Attribute):
        return expr.attr == "VERIFY_ENFORCE_ENV"
    return False


def _is_environ(expr: ast.AST, aliases) -> bool:
    """``os.environ`` (any os alias), a bare environ alias, or ``getattr(os, "environ")``."""
    modules, environs, _ = aliases
    if isinstance(expr, ast.Name):
        return expr.id in environs
    if isinstance(expr, ast.Attribute):
        return expr.attr == "environ" and isinstance(expr.value, ast.Name) and expr.value.id in modules
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "getattr":
        args = expr.args
        return (
            len(args) >= 2
            and isinstance(args[0], ast.Name)
            and args[0].id in modules
            and isinstance(args[1], ast.Constant)
            and args[1].value == "environ"
        )
    return False


def _is_getenv(expr: ast.AST, aliases) -> bool:
    modules, _, getenvs = aliases
    if isinstance(expr, ast.Name):
        return expr.id in getenvs
    if isinstance(expr, ast.Attribute):
        return expr.attr == "getenv" and isinstance(expr.value, ast.Name) and expr.value.id in modules
    return False


def _reads_verify_enforce(node: ast.AST, aliases=({"os"}, {"environ"}, {"getenv"})) -> bool:
    """True when ``node`` is an environment read keyed on the verify-enforce variable.

    Matches ``<environ>.get(X)``, ``<environ>[X]`` and ``<getenv>(X)`` where
    ``<environ>``/``<getenv>`` are any spelling ``_env_aliases`` resolves and X
    is the literal name or the ``VERIFY_ENFORCE_ENV`` constant, across lines.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and _is_environ(func.value, aliases):
            return any(_names_the_var(a) for a in node.args)
        if _is_getenv(func, aliases):
            return any(_names_the_var(a) for a in node.args)
        return False
    if isinstance(node, ast.Subscript) and _is_environ(node.value, aliases):
        return _names_the_var(node.slice)
    return False


def _direct_reads(source: str, *, skip_function: str | None = None) -> list[int]:
    """Line numbers of direct reads in ``source``, skipping one named function.

    The skip covers the whole ``FunctionDef`` node as ``ast.walk`` reaches it:
    body, decorators, and default-argument expressions alike.
    """
    tree = ast.parse(source)
    aliases = _env_aliases(tree)
    skipped: set[ast.AST] = set()
    if skip_function is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == skip_function:
                skipped.update(ast.walk(node))
    return [
        node.lineno
        for node in ast.walk(tree)
        if node not in skipped and _reads_verify_enforce(node, aliases)
    ]


def test_the_sweep_skip_is_load_bearing() -> None:
    """The sweep's ``skip_function`` must remove something real.

    Without the skip, the parse point's own read is an offender; with it, the
    module is clean. A guard whose skip removes nothing has not seen the parse
    point, and would not see a copy of it elsewhere either. Found inert by the
    #794 board (fable seat, round 1).
    """
    source = (Path(SRC) / "phase_loop_runtime" / "closeout_validation.py").read_text()
    unskipped = _direct_reads(source)
    assert unskipped, "the guard does not recognise the parse point's own read"
    for lineno in unskipped:
        assert "VERIFY_ENFORCE_ENV" in source.splitlines()[lineno - 1]
    assert _direct_reads(source, skip_function="verify_enforce_mode") == []


def test_no_module_reads_the_verify_enforce_env_var_directly() -> None:
    """G-6 guard: outside the parse point, nothing reads the variable from the environment.

    AST-based, so ``os.environ.get(VERIFY_ENFORCE_ENV, "hard")``, ``os.getenv``,
    ``from os import environ`` and multi-line spellings are caught -- the
    literal-on-one-line grep this replaced missed every one of them. The parse
    point is ONE function, ``closeout_validation.verify_enforce_mode``; the rest
    of that module is swept like every other file. Coverage is exactly the
    recogniser list in test_the_guard_recognises_each_direct_read_spelling;
    see _env_aliases for what is not followed.
    """
    offenders = _sweep_direct_reads(Path(SRC) / "phase_loop_runtime")
    assert not offenders, f"direct environment reads of PHASE_LOOP_VERIFY_ENFORCE: {offenders}"


def _sweep_direct_reads(root: Path) -> list[str]:
    """Every direct read under ``root`` except the ONE sanctioned function."""
    offenders = []
    for path in sorted(root.rglob("*.py")):
        skip = "verify_enforce_mode" if path.name == "closeout_validation.py" else None
        for lineno in _direct_reads(path.read_text(), skip_function=skip):
            offenders.append(f"{path.relative_to(root)}:{lineno}")
    return offenders


def test_the_sweep_skips_the_function_not_the_module(tmp_path) -> None:
    """The sweep's exemption is ONE function, not the parse point's whole file.

    A copy of closeout_validation.py with a read added outside
    verify_enforce_mode must be reported; the real file must not. Reverting the
    sweep site to skipping the whole module passes the real tree unchanged (it
    has no such read today) -- this is the pin for that site. Found unpinned by
    the #794 board (fable seat, round 1).
    """
    real = (Path(SRC) / "phase_loop_runtime" / "closeout_validation.py").read_text()
    fake_root = tmp_path / "pkg"
    fake_root.mkdir()
    (fake_root / "closeout_validation.py").write_text(
        real + '\n\ndef _leak():\n    import os\n    return os.environ.get("PHASE_LOOP_VERIFY_ENFORCE")\n'
    )
    leak_line = real.count("\n") + 5
    assert _sweep_direct_reads(fake_root) == [f"closeout_validation.py:{leak_line}"]
    (fake_root / "closeout_validation.py").write_text(real)
    assert _sweep_direct_reads(fake_root) == []


@pytest.mark.parametrize(
    "snippet",
    [
        'import os\nos.environ.get("PHASE_LOOP_VERIFY_ENFORCE", "hard")',
        "import os\nos.environ.get(VERIFY_ENFORCE_ENV, 'hard')",
        'import os\nos.getenv("PHASE_LOOP_VERIFY_ENFORCE")',
        "from os import getenv\ngetenv(cv.VERIFY_ENFORCE_ENV)",
        'from os import environ\nenviron["PHASE_LOOP_VERIFY_ENFORCE"]',
        'import os\nos.environ.get(\n    "PHASE_LOOP_VERIFY_ENFORCE",\n    "warn",\n)',
        # aliases (found by the #787 board, fable seat, round 2)
        'from os import environ as _env\n_env["PHASE_LOOP_VERIFY_ENFORCE"]',
        'from os import environ as _env\n_env.get("PHASE_LOOP_VERIFY_ENFORCE")',
        "from os import getenv as _ge\n_ge(VERIFY_ENFORCE_ENV)",
        'import os as _o\n_o.environ.get("PHASE_LOOP_VERIFY_ENFORCE")',
        'import os as _o\n_o.getenv("PHASE_LOOP_VERIFY_ENFORCE")',
        'import os\ngetattr(os, "environ").get("PHASE_LOOP_VERIFY_ENFORCE")',
        'import os\ngetattr(os, "environ")["PHASE_LOOP_VERIFY_ENFORCE"]',
        # assignment rebinding, incl. the parse point's own idiom (found by the
        # #794 board, fable seat, round 1)
        'import os as _os\nenv = _os.environ\nenv.get(VERIFY_ENFORCE_ENV)',
        'import os\ne = os.environ\ne["PHASE_LOOP_VERIFY_ENFORCE"]',
        'import os\nge = os.getenv\nge("PHASE_LOOP_VERIFY_ENFORCE")',
        'import os\no = os\no.environ.get("PHASE_LOOP_VERIFY_ENFORCE")',
        # a chain whose inner link is nested DEEPER than its outer one: ast.walk
        # is breadth-first, so ``b = a.environ`` is seen before ``a = os`` and
        # only the fixed-point pass resolves ``b``
        'import os\ndef f():\n    a = os\nb = a.environ\nb.get(VERIFY_ENFORCE_ENV)',
    ],
)
def test_the_guard_recognises_each_direct_read_spelling(snippet) -> None:
    """The guard's own detector, checked against the spellings it must catch."""
    assert _direct_reads(snippet), snippet


def test_the_guard_skips_only_the_named_function() -> None:
    """Function-level exclusion: a second read in the parse-point MODULE is still an offender."""
    source = (
        "import os\n"
        "def verify_enforce_mode(env):\n"
        '    return os.environ.get("PHASE_LOOP_VERIFY_ENFORCE")\n'
        "def other():\n"
        '    return os.environ.get("PHASE_LOOP_VERIFY_ENFORCE")\n'
    )
    assert _direct_reads(source, skip_function="verify_enforce_mode") == [5]
    assert _direct_reads(source) == [3, 5]


def test_the_guard_ignores_the_sanctioned_call() -> None:
    assert not _direct_reads('verify_enforce_mode(env, default="warn")')
    # a Mapping parameter named env is not the process environment
    assert not _direct_reads('env.get("PHASE_LOOP_VERIFY_ENFORCE")')
