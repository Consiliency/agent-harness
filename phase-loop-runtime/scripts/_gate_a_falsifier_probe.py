#!/usr/bin/env python3
"""Gate A in-venv probe (agent-harness#1357): the seat jail's qualification can import what it needs
from a clean install of the built wheel alone.

Runs INSIDE the isolated venv that gate_a_cleanroom.sh creates from the wheel and its declared
dependencies, BEFORE anything else installs pytest into it (the full-suite step does, which is why
a missing runtime dependency stayed invisible: `pytest` was only ever present because the test
harness put it there). Exits non-zero with a diagnostic on the first violation:

1. every module the falsifier run's trusted wrapper imports resolves in this environment;
2. the dependency snapshot can find `pytest` (the run executes without site processing, so the
   snapshot is the only way it gets pytest);
3. running the snapshot against an empty staged tree really stages `pytest` and its private
   companion `_pytest`, so the run can import them.
"""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys
import tempfile
from pathlib import Path


def fail(message: str) -> None:
    print(f"GATE-A FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def wrapper_imports(review_stage) -> list[str]:
    source = inspect.getsource(review_stage._run_bounded_falsifier_node)
    found = re.findall(r'"import ([A-Za-z_][A-Za-z0-9_,]*)\\n"', source)
    if len(found) != 1:
        fail("cannot find the falsifier wrapper's import line; update scripts/_gate_a_falsifier_probe.py")
    return found[0].split(",")


def main() -> None:
    from phase_loop_runtime import review_stage

    names = wrapper_imports(review_stage)
    third_party = [name for name in names if name not in sys.stdlib_module_names]
    if "pytest" not in third_party:
        fail(f"the falsifier wrapper no longer imports pytest ({names}); revisit agent-harness#1357")
    unresolved = [name for name in names if importlib.util.find_spec(name) is None]
    if unresolved:
        fail(f"the seat jail's falsifier run imports {unresolved}, which a clean install of the wheel "
             "does not provide; add them to [project].dependencies")
    if not review_stage.falsifier_distribution_available("pytest"):
        fail("the falsifier dependency snapshot cannot find an installed pytest in a clean install of the wheel")
    with tempfile.TemporaryDirectory(prefix="gate-a-falsifier-") as tmp:
        stage, destination = Path(tmp, "stage"), Path(tmp, "deps")
        stage.mkdir()
        destination.mkdir()
        review_stage._snapshot_falsifier_dependencies(stage, destination)
        for name in (*third_party, "_pytest"):
            if not (destination / name / "__init__.py").is_file() and not (destination / f"{name}.py").is_file():
                fail(f"the falsifier dependency snapshot did not stage {name!r} from a clean install of the wheel")
    print(f"falsifier imports: ok ({', '.join(names)}; pytest staged)")


if __name__ == "__main__":
    main()
