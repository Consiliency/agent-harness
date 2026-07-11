"""EXECREG (IF-0-EXECREG-1) — registry-driven launch, no hardcoded branch.

Covers the structural half of the exit criteria:
  * ``ExecutorCapabilityRecord`` carries the new callable fields, all optional.
  * ``capability_registry()`` binds ``build_command`` for every executor.
  * ``build_launch_spec`` delegates to ``record.build_command`` and contains **no**
    ``if request.executor == "<literal>"`` runnable-command branch (AST lint, with
    an explicit — currently empty — allowlist).
  * adding/replacing an executor's ``build_command`` drives the launch with no edit
    to the delegator (the record IS the dispatch surface — GROKEXEC's zero-edit
    proof rests on this).
"""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from phase_loop_runtime.capability_registry import capability_registry
from phase_loop_runtime.models import EXECUTORS, ExecutorCapabilityRecord
from phase_loop_runtime import launcher

_LAUNCHER_SRC = Path(launcher.__file__)

# Functions whose bodies must never branch on a literal executor name to build the
# runnable command. Empty allowlist: no exempt literal is permitted in the
# command-construction surface. (Launch-time ``spec.executor`` branches in
# launch_with_spec / run_auth_preflight are a separate surface — post-build launch
# behavior, not runnable-command selection — and are out of this lint's scope.)
_COMMAND_BUILD_FUNCTIONS = {
    "build_launch_spec",
    "build_codex_launch_spec",
    "build_claude_launch_spec",
    "build_gemini_launch_spec",
    "build_opencode_launch_spec",
    "build_pi_launch_spec",
    "build_command_launch_spec",
    "build_manual_launch_spec",
}
_ALLOWLISTED_LITERAL_BRANCHES: set[str] = set()


def _request_executor_literal_compares(fn: ast.FunctionDef) -> list[str]:
    """Return the string literals any ``request.executor == "<lit>"`` compare in
    ``fn`` compares against (either operand order)."""
    hits: list[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        has_request_executor = any(
            isinstance(op, ast.Attribute)
            and op.attr == "executor"
            and isinstance(op.value, ast.Name)
            and op.value.id == "request"
            for op in operands
        )
        if not has_request_executor:
            continue
        for op in operands:
            if isinstance(op, ast.Constant) and isinstance(op.value, str):
                hits.append(op.value)
    return hits


def test_build_launch_spec_has_no_request_executor_literal_branch():
    tree = ast.parse(_LAUNCHER_SRC.read_text(encoding="utf-8"))
    offenders: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _COMMAND_BUILD_FUNCTIONS:
            literals = [
                lit
                for lit in _request_executor_literal_compares(node)
                if lit not in _ALLOWLISTED_LITERAL_BRANCHES
            ]
            if literals:
                offenders[node.name] = literals
    assert not offenders, (
        "runnable-command selection must be registry-driven, not a hardcoded "
        f"`if request.executor == \"...\"` branch. Offending functions: {offenders}. "
        "Add an executor by registering its capability record + build fn, not a branch."
    )


def test_every_executor_binds_build_command():
    registry = capability_registry()
    for executor in EXECUTORS:
        record = registry[executor]
        assert record.build_command is not None, f"{executor} has no bound build_command"
        assert callable(record.build_command)


def test_record_carries_optional_execreg_fields():
    # All new fields exist and default to None on a bare construction.
    bare = ExecutorCapabilityRecord(executor="manual", supported_actions=(), capabilities=())
    for field_name in (
        "build_command",
        "is_available",
        "auth_ok",
        "provider_backing",
        "get_session_transcript",
    ):
        assert hasattr(bare, field_name)
        assert getattr(bare, field_name) is None


def test_build_launch_spec_delegates_to_record_build_command(monkeypatch):
    # Replacing a record's build_command drives the launch with NO delegator edit:
    # build_launch_spec must call exactly record.build_command(request, record).
    sentinel = object()
    seen: dict[str, object] = {}

    def fake_build(request, record):
        seen["request"] = request
        seen["record"] = record
        return sentinel

    real = capability_registry()
    patched = dict(real)
    patched["codex"] = dataclasses.replace(real["codex"], build_command=fake_build)
    monkeypatch.setattr(launcher, "capability_registry", lambda: patched)

    class _Req:
        executor = "codex"

    result = launcher.build_launch_spec(_Req())
    assert result is sentinel
    assert seen["record"] is patched["codex"]
    assert seen["request"].executor == "codex"


def test_build_launch_spec_raises_when_build_command_unbound(monkeypatch):
    real = capability_registry()
    patched = dict(real)
    patched["codex"] = dataclasses.replace(real["codex"], build_command=None)
    monkeypatch.setattr(launcher, "capability_registry", lambda: patched)

    class _Req:
        executor = "codex"

    with pytest.raises(ValueError, match="no build_command"):
        launcher.build_launch_spec(_Req())
