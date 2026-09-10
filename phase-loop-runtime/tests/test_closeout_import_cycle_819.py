"""agent-harness#819: real entrypoint imports must register every built-in gate."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", [
    "cli", "closeout", "events", "panel_invoker", "runner", "closeout_validators", "fab_gate",
])
def test_fresh_import_keeps_all_builtin_gates_available(first):
    source = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ, PYTHONPATH=str(source))
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib, json, sys
importlib.import_module('phase_loop_runtime.' + sys.argv[1])
from phase_loop_runtime import closeout_validators as validators
print(json.dumps({
    'expected': sorted(validators.BUILTIN_VALIDATOR_MODULES),
    'registered': sorted(fn.__module__.rsplit('.', 1)[-1] for fn in validators.registered_closeout_validators()),
    'unavailable': validators.unavailable_builtin_closeout_validators(),
}))
""", first],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["registered"] == data["expected"], data
    assert data["unavailable"] == {}, data
    assert "gate NOT registered" not in result.stderr
