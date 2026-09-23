"""PRESROUTE is landed: its frozen contracts may no longer SKIP (agent-harness#998).

The SL-0 corpus adapter (``presroute_content_tdd_adapter.run_presroute_contract``,
frozen) turns a missing capability into ``pytest.skip`` in an ordinary run, so the
corpus could land before SL-1/SL-2 without redding CI. That same rule would let a
LATER regression that removes a PRESROUTE capability (the operation module, the ladder
order, ruling persistence, the resume seam, the override guard ...) turn its contract
into a quiet skip while every job stays green. Once PRESROUTE is on ``main`` that skip
is a regression, so this node -- outside the frozen corpus -- runs the two frozen files
and fails on any "presroute capability unimplemented" skip.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[1]
_FROZEN = ("tests/test_president_wiring.py", "tests/test_govlean_panel_policy.py")


def test_no_presroute_contract_skips_as_unimplemented() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_XDIST")}
    env.pop("PHASE_LOOP_TDD_EXPECT_PRESROUTE", None)  # the ordinary (skip-capable) mode
    env.pop("PYTEST_CURRENT_TEST", None)
    env["PYTHONPATH"] = os.pathsep.join(("src", "tests"))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", *_FROZEN],
        cwd=_RUNTIME, env=env, capture_output=True, text=True, check=False,
    )
    out = proc.stdout + proc.stderr
    skipped = [line for line in out.splitlines() if "presroute capability unimplemented" in line]
    assert not skipped, "a landed PRESROUTE contract skipped as unimplemented:\n" + "\n".join(skipped)
    assert proc.returncode == 0, out[-3000:]
