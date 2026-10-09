"""pytest plugin loaded (``-p``) into the child run of the rule-enforcement registry gate.

It records every runtest report as one JSON line, so the gate can require a passed
*call*-phase report for each exact node id. A JUnit ``<testcase>`` with no children is
not that proof: ``--setup-only`` emits one for a test whose body never ran.

With ``NEGATIVE_CONTROL_KILL`` set it also disables one named enforcer, so the gate can
check that the row's control goes red without it.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import json
import os
import sys
import typing
from pathlib import Path

_LOG = os.environ.get("NEGATIVE_CONTROL_REPORT_LOG", "")
# kind|skill|module-or-path|symbol, e.g. "skill_script|plan-phase|scripts/validate_plan_doc.py|_check_c_dag_acyclic"
_KILL = os.environ.get("NEGATIVE_CONTROL_KILL", "")


def _record(event: dict) -> None:
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")


def _stub(original, script: Path | None):
    try:
        returns = typing.get_type_hints(original).get("return", type(None))
    except Exception:
        returns = type(None)
    empty = typing.get_origin(returns) or returns

    def disabled(*_args, **_kwargs):
        via_main = False
        if script is not None:
            frame = sys._getframe(1)
            while frame is not None:
                if frame.f_code.co_name == "main" and Path(frame.f_code.co_filename).resolve() == script:
                    via_main = True
                    break
                frame = frame.f_back
        _record({"killed_call": True, "via_main": via_main})
        return None if empty is type(None) else empty()

    return disabled


def pytest_configure(config):
    if not _KILL:
        return
    kind, skill, where, symbol = _KILL.split("|")
    if kind == "module":
        module = importlib.import_module(where)
        setattr(module, symbol, _stub(getattr(module, symbol), None))
        return
    original_exec = importlib.machinery.SourceFileLoader.exec_module
    depth = len(Path(where).parts)

    def exec_module(self, module):
        original_exec(self, module)
        script = Path(getattr(module, "__file__", "") or "").resolve()
        if script.as_posix().endswith("/" + where) and script.parents[depth - 1].name.endswith(skill):
            setattr(module, symbol, _stub(getattr(module, symbol), script))

    importlib.machinery.SourceFileLoader.exec_module = exec_module


def pytest_runtest_logreport(report):
    _record({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome})


def pytest_exception_interact(node, call, report):
    # A control that crashes with its enforcer disabled has not shown the enforcer's absence;
    # the gate requires the failure to be the control's own assertion.
    if report.when == "call" and call.excinfo is not None:
        _record({"nodeid": report.nodeid, "assertion_failed": call.excinfo.errisinstance(AssertionError)})
