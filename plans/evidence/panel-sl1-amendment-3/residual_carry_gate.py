"""SL-3.3 closeout gate for PANEL-RESIDUAL-SL1B (plan amendment #3).

Exit 0 when the SL-1b residual is empty, or when the v10-PANEL manifest row
carries a valid ``panel_residual_carry`` record. Exit 1 otherwise, printing why.

A valid record is a JSON object with exactly these keys:
  issue          "agent-harness#1168"
  ratified       true (a JSON boolean, not a truthy value)
  ratified_by    non-empty string naming the maintainer
  date           ISO date, YYYY-MM-DD
  evidence       https://github.com/Consiliency/agent-harness/... URL of the
                 maintainer's ratifying comment or decision

Usage (SL-3.3):
  PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests \\
    python3 plans/evidence/panel-sl1-amendment-3/residual_carry_gate.py
Options: --manifest PATH (default plans/manifest.json);
         --residual-json PATH (a JSON list replacing the imported residual;
         falsifier use only).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys

CARRY_ISSUE = "agent-harness#1168"
CARRY_KEYS = frozenset({"issue", "ratified", "ratified_by", "date", "evidence"})
EVIDENCE_PREFIX = "https://github.com/Consiliency/agent-harness/"


def carry_problems(carry: object) -> list[str]:
    if carry is None:
        return ["panel_residual_carry is absent"]
    if not isinstance(carry, dict):
        return [f"panel_residual_carry must be an object, got {type(carry).__name__}"]
    problems = []
    keys = set(carry)
    if keys != CARRY_KEYS:
        missing, extra = sorted(CARRY_KEYS - keys), sorted(keys - CARRY_KEYS)
        problems.append(
            f"keys must be exactly {sorted(CARRY_KEYS)} (missing {missing}, extra {extra})"
        )
    if carry.get("issue") != CARRY_ISSUE:
        problems.append(f"issue must be {CARRY_ISSUE!r}, got {carry.get('issue')!r}")
    if carry.get("ratified") is not True:
        problems.append(f"ratified must be true, got {carry.get('ratified')!r}")
    by = carry.get("ratified_by")
    if not isinstance(by, str) or not by.strip():
        problems.append("ratified_by must be a non-empty string")
    date = carry.get("date")
    try:
        if (
            not isinstance(date, str)
            or datetime.date.fromisoformat(date).isoformat() != date
        ):
            raise ValueError
    except ValueError:
        problems.append(f"date must be YYYY-MM-DD, got {date!r}")
    ev = carry.get("evidence")
    if (
        not isinstance(ev, str)
        or not ev.startswith(EVIDENCE_PREFIX)
        or len(ev) == len(EVIDENCE_PREFIX)
    ):
        problems.append(f"evidence must be a {EVIDENCE_PREFIX}... URL, got {ev!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="plans/manifest.json")
    ap.add_argument("--residual-json")
    args = ap.parse_args(argv)
    if args.residual_json:
        with open(args.residual_json) as fh:
            residual = json.load(fh)
    else:
        import test_panel_sl1_contracts as t

        residual = t._TW_RESIDUAL_SL1B
    if not residual:
        print("PANEL-RESIDUAL-SL1B empty: pass")
        return 0
    with open(args.manifest) as fh:
        plans = json.load(fh)["plans"]
    row = next(p for p in plans if p.get("slug") == "v10-PANEL")
    problems = carry_problems(row.get("panel_residual_carry"))
    if problems:
        print(
            f"PANEL-RESIDUAL-SL1B has {len(residual)} open site(s) and no valid carry:"
        )
        for p in problems:
            print(f"  - {p}")
        return 1
    print(
        f"PANEL-RESIDUAL-SL1B has {len(residual)} open site(s), carried by a valid record: pass"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
