"""Falsifiers for residual_carry_gate.py; output recorded in residual_carry_gate_falsifiers.log.

Run from the amendment tree with the SL-1 tests importable, e.g.
  PYTHONPATH=<sl1-worktree>/phase-loop-runtime/src:<sl1-worktree>/phase-loop-runtime/tests \\
    python3 plans/evidence/panel-sl1-amendment-3/residual_carry_gate_falsifiers.py
Each case copies plans/manifest.json, sets (or removes) panel_residual_carry on
the v10-PANEL row, and runs the gate in a subprocess against the real residual.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "residual_carry_gate.py")
VALID = {
    "issue": "agent-harness#1168",
    "ratified": True,
    "ratified_by": "maintainer",
    "date": "2026-09-29",
    "evidence": "https://github.com/Consiliency/agent-harness/issues/1168#issuecomment-1",
}
ABSENT = object()


def v(**kw):
    d = dict(VALID)
    for k, val in kw.items():
        if val is ABSENT:
            d.pop(k)
        else:
            d[k] = val
    return d


CASES = [
    ("absent", ABSENT, None, 1),
    ("true", True, None, 1),
    (
        "codex r2 probe: wrong issue, unratified",
        {"issue": "agent-harness#9999", "ratified": False},
        None,
        1,
    ),
    ("wrong issue", v(issue="agent-harness#9999"), None, 1),
    ("unratified (false)", v(ratified=False), None, 1),
    ("ratified truthy string", v(ratified="yes"), None, 1),
    ("malformed: string", "agent-harness#1168", None, 1),
    ("malformed: missing ratified_by", v(ratified_by=ABSENT), None, 1),
    ("malformed: empty ratified_by", v(ratified_by=" "), None, 1),
    ("malformed: bad date", v(date="2026-9-29"), None, 1),
    ("malformed: missing evidence", v(evidence=ABSENT), None, 1),
    ("malformed: non-github evidence", v(evidence="https://example.com/x"), None, 1),
    ("malformed: extra key", v(note="x"), None, 1),
    ("valid record", VALID, None, 0),
    ("empty residual, no carry", ABSENT, [], 0),
]


def main():
    base = json.load(open("plans/manifest.json"))
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        for name, carry, residual, want in CASES:
            m = copy.deepcopy(base)
            row = next(p for p in m["plans"] if p.get("slug") == "v10-PANEL")
            row.pop("panel_residual_carry", None)
            if carry is not ABSENT:
                row["panel_residual_carry"] = carry
            mp = os.path.join(td, "manifest.json")
            json.dump(m, open(mp, "w"))
            argv = [sys.executable, GATE, "--manifest", mp]
            if residual is not None:
                rp = os.path.join(td, "residual.json")
                json.dump(residual, open(rp, "w"))
                argv += ["--residual-json", rp]
            got = subprocess.run(argv, capture_output=True, text=True).returncode
            ok = got == want
            failed += not ok
            print(f"{'OK  ' if ok else 'FAIL'} exit={got} want={want}  {name}")
    print(f"{len(CASES) - failed}/{len(CASES)} cases as expected")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
