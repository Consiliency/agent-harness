"""Falsifiers for residual_carry_gate.py; output recorded in residual_carry_gate_falsifiers.log.

Run from the repository root:
  python3 plans/evidence/panel-sl1-amendment-3/residual_carry_gate_falsifiers.py
Each case writes a residual file and a copy of plans/manifest.json with the
v10-PANEL row's panel_residual_carry set (or removed), then runs the gate in a
subprocess. With --cross-check-sl1, it also asserts that the four ruled sites
equal SL-1's _TW_RESIDUAL_SL1B (test_panel_sl1_contracts must be importable).
"""

import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "residual_carry_gate.py")
SRC = "phase-loop-runtime/src/phase_loop_runtime/"
RULED = [
    {
        "path": SRC + "convergence/broker/credsep.py",
        "function": "execute",
        "finding": "git push",
    },
    {
        "path": SRC + "convergence/broker/credsep.py",
        "function": "execute",
        "finding": "gh pr create",
    },
    {"path": SRC + "agy_watch.py", "function": "_push_argv", "finding": "git push"},
    {"path": SRC + "agy_watch.py", "function": "main", "finding": "gh pr create"},
]
FIFTH = {"path": SRC + "agy_watch.py", "function": "main", "finding": "git push"}
VALID = {
    "issue": "agent-harness#1168",
    "ratified": True,
    "ratified_by": "ViperJuice",
    "date": "2026-09-29",
    "evidence": {"kind": "issue_comment", "issue": 1168, "comment_id": 4321},
    "sites": RULED,
}
ABSENT = object()
NO_FILE = object()


def v(**kw):
    d = copy.deepcopy(VALID)
    for k, val in kw.items():
        if val is ABSENT:
            d.pop(k)
        else:
            d[k] = val
    return d


def ev(**kw):
    e = dict(VALID["evidence"])
    for k, val in kw.items():
        if val is ABSENT:
            e.pop(k)
        else:
            e[k] = val
    return v(evidence=e)


def residual(sites):
    return {"schema": "panel_residual_sl1b.v1", "sites": sites}


R4 = residual(RULED)
CODEX_NEWLINE = "https://github.com/Consiliency/agent-harness/\n"
CODEX_ESCAPE = "https://github.com/Consiliency/agent-harness/../another-repo/issues/1168#issuecomment-1"
OTHER_SITE = dict(RULED[3], finding="git push --force")

# (name, carry, residual file payload, expected exit)
CASES = [
    # r2 cases, carried over (with the r3 record shape)
    ("absent", ABSENT, R4, 1),
    ("true", True, R4, 1),
    (
        "codex r2 probe: wrong issue, unratified",
        {"issue": "agent-harness#9999", "ratified": False},
        R4,
        1,
    ),
    ("wrong issue", v(issue="agent-harness#9999"), R4, 1),
    ("unratified (false)", v(ratified=False), R4, 1),
    ("ratified truthy string", v(ratified="yes"), R4, 1),
    ("malformed: string", "agent-harness#1168", R4, 1),
    ("malformed: missing ratified_by", v(ratified_by=ABSENT), R4, 1),
    ("malformed: empty ratified_by", v(ratified_by=" "), R4, 1),
    ("malformed: bad date", v(date="2026-9-29"), R4, 1),
    ("malformed: missing evidence", v(evidence=ABSENT), R4, 1),
    ("malformed: non-github evidence", v(evidence="https://example.com/x"), R4, 1),
    ("malformed: extra key", v(note="x"), R4, 1),
    ("valid record", VALID, R4, 0),
    ("empty residual, no carry", ABSENT, residual([]), 0),
    # codex r3 repros: a URL string is no longer an accepted evidence shape
    ("codex r3 repro: URL with trailing newline", v(evidence=CODEX_NEWLINE), R4, 1),
    ("codex r3 repro: URL escaping the repo", v(evidence=CODEX_ESCAPE), R4, 1),
    # evidence type confusion
    ("evidence comment_id as string", ev(comment_id="4321"), R4, 1),
    ("evidence comment_id as float", ev(comment_id=4321.0), R4, 1),
    ("evidence comment_id as bool", ev(comment_id=True), R4, 1),
    ("evidence comment_id negative", ev(comment_id=-4321), R4, 1),
    ("evidence comment_id zero", ev(comment_id=0), R4, 1),
    ("evidence issue as string", ev(issue="1168"), R4, 1),
    ("evidence issue another number", ev(issue=1169), R4, 1),
    ("evidence other kind", ev(kind="pull_request_comment"), R4, 1),
    ("evidence extra key", ev(url=CODEX_ESCAPE), R4, 1),
    ("evidence missing comment_id", ev(comment_id=ABSENT), R4, 1),
    ("ratified_by with newline", v(ratified_by="ViperJuice\n"), R4, 1),
    ("date that is not a real day", v(date="2026-02-30"), R4, 1),
    # binding the carry to the live residual
    ("carry sites missing", v(sites=ABSENT), R4, 1),
    ("carry sites superset of residual", v(sites=RULED + [FIFTH]), R4, 1),
    ("carry sites subset of residual", v(sites=RULED[:3]), R4, 1),
    ("carry sites differ by one", v(sites=RULED[:3] + [OTHER_SITE]), R4, 1),
    ("residual grew past the carry", VALID, residual(RULED + [FIFTH]), 1),
    ("residual shrank below the carry", VALID, residual(RULED[1:]), 1),
    ("carry sites duplicate a site", v(sites=RULED + [RULED[0]]), R4, 1),
    (
        "carry site with extra field",
        v(sites=[dict(RULED[0], line=1)] + RULED[1:]),
        R4,
        1,
    ),
    ("carry sites as triples", v(sites=[list(s.values()) for s in RULED]), R4, 1),
    ("matching carry, sites reordered", v(sites=list(reversed(RULED))), R4, 0),
    # the residual file
    ("residual file absent (this branch)", ABSENT, NO_FILE, 1),
    ("residual file absent, valid carry", VALID, NO_FILE, 1),
    ("residual file wrong schema", VALID, {"schema": "x", "sites": RULED}, 1),
    ("residual file extra key", VALID, dict(R4, note="x"), 1),
    ("residual file duplicate site", ABSENT, residual(RULED + [RULED[0]]), 1),
    ("residual file not JSON", VALID, "not json", 1),
]


def run_cases():
    base = json.load(open("plans/manifest.json"))
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        for name, carry, rfile, want in CASES:
            m = copy.deepcopy(base)
            row = next(p for p in m["plans"] if p.get("slug") == "v10-PANEL")
            row.pop("panel_residual_carry", None)
            if carry is not ABSENT:
                row["panel_residual_carry"] = carry
            mp = os.path.join(td, "manifest.json")
            json.dump(m, open(mp, "w"))
            rp = os.path.join(td, "residual.json")
            if os.path.exists(rp):
                os.remove(rp)
            if rfile is not NO_FILE:
                with open(rp, "w") as fh:
                    fh.write(rfile if isinstance(rfile, str) else json.dumps(rfile))
            argv = [sys.executable, GATE, "--manifest", mp, "--residual", rp]
            got = subprocess.run(argv, capture_output=True, text=True).returncode
            ok = got == want
            failed += not ok
            print(f"{'OK  ' if ok else 'FAIL'} exit={got} want={want}  {name}")
    print(f"{len(CASES) - failed}/{len(CASES)} cases as expected")
    return failed


def main():
    failed = run_cases()
    if "--cross-check-sl1" in sys.argv:
        import test_panel_sl1_contracts as t

        ruled = {(s["path"], s["function"], s["finding"]) for s in RULED}
        same = ruled == set(t._TW_RESIDUAL_SL1B)
        print(f"cross-check: ruled sites == SL-1 _TW_RESIDUAL_SL1B: {same}")
        failed += not same
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
