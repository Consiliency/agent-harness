"""The agent-harness#1993 test modules collect cleanly in the Gate A standalone layout.

Gate A's clean room runs the suite from a tree that carries ``tests/`` and an allowlist of
``scripts/``, but not the CI host script, the workflows or these modules' scripts. A
module that loads a repository-only file at import time then fails *collection*, which
fails the whole standalone suite (agent-harness#2009, Gate A run 44630983560). Each module
is copied into such a tree and collected there: it must skip, never error.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
MODULES = (
    "test_seat_caps_readiness_report.py",
    "test_seat_caps_loop_validation.py",
    "test_seat_caps_host_script.py",
    "test_seat_caps_scratch_binding.py",
    "test_verify_qualified_agy_route_core.py",
    "test_agy_upstream_advisory.py",
)


@pytest.mark.parametrize("module", MODULES)
def test_the_module_skips_rather_than_errors_without_repository_only_files(module, tmp_path):
    # tmp/repo/phase-loop-runtime/tests/<module>: parents[1] has no scripts/, parents[2]
    # has no ci/ or .github/.
    tests = tmp_path / "repo" / "phase-loop-runtime" / "tests"
    tests.mkdir(parents=True)
    shutil.copyfile(TESTS / module, tests / module)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTEST_", "PYTHON", "CI_SCRATCH_"))}
    env.update(PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs", str(tests / module)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    output = done.stdout + done.stderr
    # A module-level skip leaves no items, which pytest reports as exit status 5 on its own;
    # in Gate A's full run the other modules supply items. A collection error is status 2.
    assert done.returncode in (0, 5), output[-3000:]
    assert "ERROR collecting" not in output and "Error:" not in output, output[-3000:]
    assert " skipped" in output and " passed" not in output and " failed" not in output, output[-3000:]
