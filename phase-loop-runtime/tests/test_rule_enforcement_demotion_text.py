"""The warning-only mutation keeps each original finding intact (agent-harness#1421)."""

import dataclasses
from pathlib import Path

import pytest

import test_rule_enforcement_registry as gate
from _dotfiles_tree import skills_bundle_present
from phase_loop_runtime.rule_enforcement import load_registry

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "phase-loop-skills"
    / "plan-phase"
    / "scripts"
    / "validate_plan_doc.py"
)
NODE = "tests/test_demotion_text_only.py::test_text_only"

_TEXT_ONLY = '''import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path


def test_text_only():
    spec = importlib.util.spec_from_file_location("validate_plan_doc_text_only", {script!r})
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "plan.md"
        path.write_text({plan!r}, encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = mod.main(["validate_plan_doc.py", str(path)])
    assert code == 1
    assert {marker!r} in err.getvalue()
'''

_ROWS = {
    "plan-phase.lane-dag-acyclic": (
        {"sl0_depends": "SL-1"},
        "(C) lane DAG has a cycle",
    ),
    "plan-phase.owned-files-disjoint": (
        {"sl1_owned": "`src/a.py`"},
        "(D) duplicate owned glob `src/a.py`",
    ),
}


@pytest.mark.skipif(
    not skills_bundle_present(),
    reason="negative controls load the sibling phase-loop-skills bundle",
)
def test_demotion_gate_refuses_a_control_that_only_reads_the_findings_text(
    tmp_path, monkeypatch
):
    from test_rule_enforcement_controls import _plan

    rules = {rule.id: rule for rule in load_registry()}
    for row_id, (plan_args, marker) in _ROWS.items():
        rule = rules[row_id]
        (enforcer,) = [item for item in rule.enforcers if item.kind == "skill_script"]

        (tmp_path / row_id / "real").mkdir(parents=True)
        gate.test_demoting_a_named_check_to_a_warning_turns_its_rows_control_red(
            rule, enforcer, tmp_path / row_id / "real"
        )

        root = tmp_path / row_id / "runtime"
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_demotion_text_only.py").write_text(
            _TEXT_ONLY.format(
                script=str(SCRIPT),
                plan=_plan(**plan_args),
                marker=marker,
            ),
            encoding="utf-8",
        )
        reports = tmp_path / row_id / "reports"
        reports.mkdir()
        with monkeypatch.context() as patch:
            patch.setattr(gate, "RUNTIME_ROOT", root)
            _, passed, _ = gate._run_controls([NODE], reports)
            assert NODE in passed
            with pytest.raises(AssertionError, match="stays green"):
                gate.test_demoting_a_named_check_to_a_warning_turns_its_rows_control_red(
                    dataclasses.replace(rule, negative_control=NODE),
                    enforcer,
                    reports,
                )
